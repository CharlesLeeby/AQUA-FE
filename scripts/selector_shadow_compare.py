#!/usr/bin/env python3
"""Real-data shadow comparison: H (frozen heuristic) vs G/QG marginal-support.

Export-only shadow (ISJ plan 6.7). Reads a frozen full_merged + sidecar bag,
reproduces the real eligibility state machine via CausalLineageShadow, and at
each decision event runs the five-arm ranking comparison over a STANDING pool
of eligible-but-unadmitted candidates (the plan's E_t). It does NOT change any
export; it only records how differently each arm would select.

FIRST PASS is provisional: q_lower := 1 and residual e := 0, so QG reduces to G
(pure geometric marginal support). This isolates the geometric question --
"does set-conditional marginal support select differently from H's per-candidate
nearest-KLT distance, and how often do >=2 candidates actually compete?" The
conformal reliability layer (real q_lower) is wired in a later pass.

Run:
  source /opt/ros/noetic/setup.bash
  python3 scripts/selector_shadow_compare.py \
      --full  <dir>/full_merged.bag --sidecar <dir>/sidecar.bag \
      --out logs/selector_shadow/<window>.csv --b-active 4
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

import rosbag

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.ros.causal_lineage_shadow_node import (
    CausalLineageShadow,
    ShadowConfig,
    _channel_values,
    _pixels,
    _safe_int,
)
from uw_frontend.geometry.marginal_support import MarginalSupportConfig, Track
from uw_frontend.geometry.shadow_rankings import compare_event

FEATURE_TOPIC = "/feature_tracker/feature"
SIDECAR_TOPIC = "/feature_tracker/sidecar"


def _messages(path: Path, topic: str):
    with rosbag.Bag(str(path)) as bag:
        return [msg for _t, msg, _ts in bag.read_messages(topics=[topic])]


def _base_from_full(msg):
    """Native-KLT base of a merged feature frame: keep is_learned == 0."""
    is_learned = _channel_values(msg, "is_learned", len(msg.points), 0.0)
    keep = [i for i, v in enumerate(is_learned) if int(round(float(v))) == 0]
    import copy

    out = copy.deepcopy(msg)
    out.points = [msg.points[i] for i in keep]
    for ch in out.channels:
        ch.values = [ch.values[i] for i in keep]
    return out


def _seed_pixels(sidecar) -> dict[int, tuple[float, float]]:
    n = len(sidecar.points)
    ids = _channel_values(sidecar, "id", n, -1.0)
    p_u = _channel_values(sidecar, "p_u", n, float("nan"))
    p_v = _channel_values(sidecar, "p_v", n, float("nan"))
    out: dict[int, tuple[float, float]] = {}
    for i in range(n):
        fid = _safe_int(ids[i], -1)
        u, v = float(p_u[i]), float(p_v[i])
        if fid >= 0 and u == u and v == v:  # finite
            out.setdefault(fid, (u, v))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", required=True)
    ap.add_argument("--sidecar", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--b-active", type=int, default=4)
    ap.add_argument("--lambda-a", type=float, default=1.0)
    args = ap.parse_args()

    full_msgs = _messages(Path(args.full), FEATURE_TOPIC)
    side_msgs = _messages(Path(args.sidecar), SIDECAR_TOPIC)
    n_frames = min(len(full_msgs), len(side_msgs))

    # image size from observed pixel extent (+ margin)
    umax = vmax = 1.0
    for m in side_msgs + full_msgs:
        n = len(m.points)
        for u in _channel_values(m, "p_u", n, 0.0):
            umax = max(umax, float(u))
        for v in _channel_values(m, "p_v", n, 0.0):
            vmax = max(vmax, float(v))
    image_shape = (umax + 1.0, vmax + 1.0)

    cfg_node = ShadowConfig()
    selector = CausalLineageShadow(cfg_node)
    sel_cfg = MarginalSupportConfig(weight_mode="qg", lambda_a=args.lambda_a,
                                    b_active=args.b_active, min_gain=0.0)

    matured: set[int] = set()
    qg_active: dict[int, tuple[float, float]] = {}   # id -> last pixel
    last_pixel: dict[int, tuple[float, float]] = {}

    rows: list[dict] = []
    events = multi_events = contests = diverged = 0
    overlaps_contest: list[float] = []

    for f in range(n_frames):
        base_msg = _base_from_full(full_msgs[f])
        side_msg = side_msgs[f]
        selector.process(base_msg, side_msg)   # advance real eligibility state

        present = _seed_pixels(side_msg)
        last_pixel.update(present)
        # crude carrier termination: release an admitted lineage once out of view
        for fid in list(qg_active):
            if fid not in present:
                del qg_active[fid]

        # maturity per node semantics: novelty score passed + motion ratio in band
        for fid, score in selector.scores.items():
            if fid in matured:
                continue
            ratio = selector.motion_ratios.get(fid)
            if (score >= cfg_node.min_distance_px and ratio is not None
                    and cfg_node.min_motion_ratio <= ratio <= cfg_node.max_motion_ratio):
                matured.add(fid)

        # standing eligible pool E_t: matured, present now, not already admitted by QG
        elig_ids = [fid for fid in present if fid in matured and fid not in qg_active]
        if not elig_ids:
            continue

        base_tracks = [Track(1_000_000 + i, u, v, 1.0, 0.0)
                       for i, (u, v) in enumerate(_pixels(base_msg))]
        active_tracks = [Track(fid, *qg_active[fid], 1.0, 0.0) for fid in qg_active]
        eligible = [Track(fid, present[fid][0], present[fid][1], 1.0, 0.0) for fid in elig_ids]
        h_scores = {fid: float(selector.scores[fid]) for fid in elig_ids}

        cmp = compare_event(base_tracks, active_tracks, eligible, image_shape, sel_cfg, h_scores)
        events += 1
        n_elig = len(elig_ids)
        if n_elig >= 2:
            multi_events += 1
        # a real selection contest: >=2 candidates competing for >=1 admitted slot
        if n_elig >= 2 and cmp.n_t >= 1:
            contests += 1
            overlaps_contest.append(cmp.overlap_vs_qg["h"])
            if cmp.overlap_vs_qg["h"] < 1.0:
                diverged += 1

        # QG admits its top-n_t into the standing active lineage
        for fid in cmp.topn["qg"]:
            qg_active[fid] = present.get(fid, last_pixel.get(fid, (0.0, 0.0)))

        rows.append({
            "frame": f,
            "n_eligible": n_elig,
            "n_active_before": len(active_tracks),
            "n_t_qg_admit": cmp.n_t,
            "overlap_h_vs_qg": round(cmp.overlap_vs_qg["h"], 4),
            "overlap_r_vs_qg": round(cmp.overlap_vs_qg["r"], 4),
            "qg_topn": ";".join(str(i) for i in cmp.topn["qg"]),
            "h_topn": ";".join(str(i) for i in cmp.topn["h"]),
        })

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["frame"])
        w.writeheader()
        w.writerows(rows)

    print(f"frames={n_frames}  image_shape={image_shape[0]:.0f}x{image_shape[1]:.0f}  b_active={args.b_active}")
    print(f"distinct matured learned lineages (whole window): {len(matured)}")
    print(f"decision events (|E_t|>=1): {events}   multi-candidate (|E_t|>=2): {multi_events}")
    print(f"selection contests (|E_t|>=2 AND QG admits>=1): {contests}")
    if overlaps_contest:
        print(f"  H-vs-QG top-n_t overlap on contests: "
              f"median={statistics.median(overlaps_contest):.3f} min={min(overlaps_contest):.3f}")
        print(f"  contests where QG diverges from H (o<1): {diverged}/{contests}")
    else:
        print("  NO real contests -> candidate supply never exceeds budget; H and QG cannot diverge here")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
