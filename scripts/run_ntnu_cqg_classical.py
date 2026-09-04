#!/usr/bin/env python3
"""E2 C-QG: produce a CLASSICAL-seed merged feature bag for NTNU fjord1.

Feeds the SAME native-KLT base stream (reconstructed from the learned run's
features.bag, is_learned==0) + the SAME raw images through the SAME
LearnedSeedKltSidecar pipeline, but with ``ClassicalGfttMatcher`` in place of
XFeat. Everything downstream (LK probation, NCC, motion/homography gates,
novelty admission, export) is byte-identical -> the only changed variable is the
detector. Output = a classical merged features bag playable by the same VINS
config, so its trajectory can be compared to learned (0.073) and KLT (0.187).

Also supports --matcher xfeat to produce a fresh learned arm under the identical
config for a fully-controlled head-to-head.
"""

from __future__ import annotations

import argparse
import copy
import csv
from pathlib import Path

import rosbag
import rospy
from cv_bridge import CvBridge

from uw_frontend.ros.export_vins_features import _load_pinhole_camera
from uw_frontend.ros.xfeat_seed_sidecar_node import (
    LearnedSeedKltSidecar,
    SeedSidecarConfig,
    _channel_values,
)
from uw_frontend.ros.causal_lineage_shadow_node import ShadowConfig
from uw_frontend.matchers.classical_gftt import ClassicalGfttMatcher

FEATURE_TOPIC = "/feature_tracker/feature"


def _base_only(msg):
    """Native-KLT base = feature message filtered to is_learned == 0."""
    n = len(msg.points)
    il = _channel_values(msg, "is_learned", n, 0.0)
    keep = [i for i, v in enumerate(il) if int(round(float(v))) == 0]
    out = copy.deepcopy(msg)
    out.points = [msg.points[i] for i in keep]
    for ch in out.channels:
        ch.values = [ch.values[i] for i in keep]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--learned-bag", required=True, help="learned run features.bag (base+IMU source)")
    ap.add_argument("--raw-bag", required=True)
    ap.add_argument("--image-topic", default="/alphasense_driver_ros/cam0")
    ap.add_argument("--camera", required=True)
    ap.add_argument("--matcher", choices=["classical", "xfeat"], default="classical")
    ap.add_argument("--out-bag", required=True)
    ap.add_argument("--match-tolerance", type=float, default=0.03)
    ap.add_argument("--trigger-warmup-frames", type=int, default=8)
    ap.add_argument("--trigger-cooldown-frames", type=int, default=12)
    ap.add_argument("--max-triggers", type=int, default=3)
    ap.add_argument("--max-lineages", type=int, default=1)
    ap.add_argument("--min-observations", type=int, default=5)
    ap.add_argument("--rank-observations", type=int, default=5)
    ap.add_argument("--min-distance-px", type=float, default=40.0)
    ap.add_argument("--base-gate", action="store_true", help="enable base-stability injection gate")
    ap.add_argument("--metrics-csv", type=Path)
    args = ap.parse_args()

    bridge = CvBridge()
    camera = _load_pinhole_camera(Path(args.camera))

    if args.matcher == "classical":
        matcher = ClassicalGfttMatcher()
    else:
        from uw_frontend.evaluation.run_frontend_eval import build_matcher, load_config
        matcher = build_matcher("hybrid_xfeat", load_config(None))

    core_config = SeedSidecarConfig(
        trigger_warmup_frames=args.trigger_warmup_frames,
        trigger_cooldown_frames=args.trigger_cooldown_frames,
        max_triggers=args.max_triggers,
        base_gate_enabled=args.base_gate,
    )
    selector_config = ShadowConfig(
        source_code=20,
        min_observations=args.min_observations,
        rank_observations=args.rank_observations,
        min_distance_px=args.min_distance_px,
        max_lineages=args.max_lineages,
    )
    core = LearnedSeedKltSidecar(matcher, camera, core_config, selector_config)

    # 1) base frames (stamp, PointCloud) from learned bag
    feat_msgs = []
    with rosbag.Bag(args.learned_bag) as b:
        for _t, m, _ts in b.read_messages(topics=[FEATURE_TOPIC]):
            feat_msgs.append((m.header.stamp.to_sec(), m))
    fmin = feat_msgs[0][0] - 0.5
    fmax = feat_msgs[-1][0] + 0.5

    # 2) raw images in the window
    imgs = []
    with rosbag.Bag(args.raw_bag) as b:
        # The NTNU source bags are multi-camera, multi-sensor recordings. The
        # feature bag already fixes the exact replay interval, so use the
        # indexed interval to avoid scanning unrelated hours of raw messages.
        for _t, m, _ts in b.read_messages(
            topics=[args.image_topic],
            start_time=rospy.Time.from_sec(fmin),
            end_time=rospy.Time.from_sec(fmax),
        ):
            s = m.header.stamp.to_sec()
            if fmin <= s <= fmax:
                imgs.append((s, bridge.imgmsg_to_cv2(m, "mono8")))
    imgs.sort(key=lambda x: x[0])

    def nearest_img(stamp):
        best, bd = None, 1e9
        for s, g in imgs:
            d = abs(s - stamp)
            if d < bd:
                bd, best = d, g
        return best if bd <= args.match_tolerance else None

    # 3) run sidecar per frame -> merged
    merged_by_stamp = {}
    metric_rows = []
    admitted = 0
    injected = 0
    for stamp, fmsg in feat_msgs:
        gray = nearest_img(stamp)
        base_pc = _base_only(fmsg)
        if gray is None:
            merged_by_stamp[stamp] = fmsg  # no image -> passthrough base+learned as-is
            continue
        _sidecar, merged, row = core.process(gray, base_pc)
        merged_by_stamp[stamp] = merged
        metric_rows.append(row)
        injected += int(row.get("selector_injected_observations", 0) or 0)
    admitted = len(core.selector.selected_ids)

    # 4) write out bag = copy learned bag, replace feature topic with classical merged
    out = Path(args.out_bag)
    out.parent.mkdir(parents=True, exist_ok=True)
    with rosbag.Bag(args.learned_bag) as src, rosbag.Bag(str(out), "w") as dst:
        for topic, msg, t in src.read_messages():
            if topic == FEATURE_TOPIC:
                s = msg.header.stamp.to_sec()
                msg = merged_by_stamp.get(s, msg)
            dst.write(topic, msg, t)

    if args.metrics_csv:
        args.metrics_csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = []
        for row in metric_rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        with args.metrics_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(metric_rows)

    print(f"matcher={args.matcher} frames={len(feat_msgs)} images_in_window={len(imgs)}")
    print(f"admitted_lineages={admitted} selected_ids={sorted(core.selector.selected_ids)} injected_obs={injected}")
    print(f"triggers={core.trigger_count} active_seeds_final={len(core.active)}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
