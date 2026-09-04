#!/usr/bin/env python3
"""Export the validated dense KLT candidate stream on a frozen VINS grid.

Every input image is processed causally so KLT state follows the complete image
history.  A candidate PointCloud is written only when the image header stamp is
present in the frozen base feature bag.  This makes the resulting bag directly
usable by ``build_adaptive_klt_candidate_pool_bag.py`` without interpolation or
future-frame access.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import rosbag


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from uw_frontend.evaluation.run_frontend_eval import load_config
from uw_frontend.ros.dense_klt_candidate_node import DenseKltCandidatePublisher
from uw_frontend.ros.export_vins_features import _load_pinhole_camera
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-bag", type=Path, required=True)
    parser.add_argument("--base-feature-bag", type=Path, required=True)
    parser.add_argument("--output-bag", type=Path, required=True)
    parser.add_argument("--stats-csv", type=Path, required=True)
    parser.add_argument("--summary-json", type=Path, required=True)
    parser.add_argument("--image-topic", default="/cam0/image_raw")
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument(
        "--stamp-tolerance-ns",
        type=int,
        default=100,
        help="Maximum image/base header rounding difference for greedy matching.",
    )
    parser.add_argument("--camera-config", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "uw_frontend/configs/klt_frontend.yaml",
    )
    parser.add_argument(
        "--preprocess",
        choices=("none", "equalize", "clahe", "adaptive_clahe"),
        default="clahe",
    )
    return parser.parse_args()


def header_stamps(path: Path, topic: str) -> list[int]:
    with rosbag.Bag(str(path), "r") as bag:
        stamps = [
            int(msg.header.stamp.to_nsec())
            for _topic, msg, _stamp in bag.read_messages(topics=[topic])
        ]
    if not stamps:
        raise ValueError(f"no messages on {topic!r} in {path}")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ValueError("base feature header stamps are not strictly increasing")
    return stamps


def main() -> int:
    args = parse_args()
    for path in (args.image_bag, args.base_feature_bag, args.camera_config, args.config):
        if not path.is_file():
            raise SystemExit(f"missing input: {path}")
    for path in (args.output_bag, args.stats_csv, args.summary_json):
        path.parent.mkdir(parents=True, exist_ok=True)
    if args.output_bag.exists():
        raise SystemExit(f"refusing to overwrite output bag: {args.output_bag}")

    target_stamps = header_stamps(args.base_feature_bag, args.feature_topic)
    if args.stamp_tolerance_ns < 0:
        raise SystemExit("--stamp-tolerance-ns must be non-negative")
    cfg = load_config(args.config)
    klt_config = KltConfig(**cfg.get("klt", {}))
    klt_config.compute_track_metadata = False
    klt_config.vectorized_ncc = True
    processor = DenseKltCandidatePublisher(
        tracker=KltTracker(klt_config),
        camera=_load_pinhole_camera(args.camera_config),
        preprocess=args.preprocess,
        constant_quality=True,
    )

    rows: list[dict[str, object]] = []
    emitted: list[int] = []
    stamp_corrections_ns: list[int] = []
    images_processed = 0
    target_index = 0
    started = time.perf_counter()
    first_target = target_stamps[0]
    last_target = target_stamps[-1]
    with rosbag.Bag(str(args.output_bag), "w") as output:
        with rosbag.Bag(str(args.image_bag), "r") as source:
            for _topic, msg, _stamp in source.read_messages(topics=[args.image_topic]):
                stamp_ns = int(msg.header.stamp.to_nsec())
                if stamp_ns > last_target + args.stamp_tolerance_ns:
                    break
                candidate, decision = processor.process(msg)
                images_processed += 1
                while (
                    target_index < len(target_stamps)
                    and target_stamps[target_index]
                    < stamp_ns - args.stamp_tolerance_ns
                ):
                    target_index += 1
                if target_index >= len(target_stamps):
                    break
                target_stamp_ns = target_stamps[target_index]
                correction_ns = target_stamp_ns - stamp_ns
                if abs(correction_ns) > args.stamp_tolerance_ns:
                    continue
                candidate.header.stamp.secs = target_stamp_ns // 1_000_000_000
                candidate.header.stamp.nsecs = target_stamp_ns % 1_000_000_000
                output.write(args.feature_topic, candidate, candidate.header.stamp)
                emitted.append(target_stamp_ns)
                stamp_corrections_ns.append(correction_ns)
                rows.append(decision)
                target_index += 1

    target_set = set(target_stamps)
    missing = sorted(target_set - set(emitted))
    extra = sorted(set(emitted) - target_set)
    duplicate_count = len(emitted) - len(set(emitted))
    exact_order = emitted == target_stamps
    processing_ms = np.asarray(
        [float(row["processing_ms"]) for row in rows], dtype=np.float64
    )
    tracks = np.asarray([int(row["tracks"]) for row in rows], dtype=np.float64)
    mature = np.asarray(
        [int(row["mature_tracks"]) for row in rows], dtype=np.float64
    )
    status = (
        "PASS"
        if not missing and not extra and duplicate_count == 0 and exact_order
        else "FAIL"
    )
    summary = {
        "schema": "dense_klt_candidate_frozen_grid_v1",
        "status": status,
        "base_bag": str(args.base_feature_bag.resolve()),
        "image_bag": str(args.image_bag.resolve()),
        "output_bag": str(args.output_bag.resolve()),
        "target_frames": len(target_stamps),
        "frames": len(emitted),
        "images_processed": images_processed,
        "first_target_stamp_ns": first_target,
        "last_target_stamp_ns": last_target,
        "missing_count": len(missing),
        "missing_first": missing[:10],
        "extra_count": len(extra),
        "extra_first": extra[:10],
        "duplicate_count": duplicate_count,
        "exact_order": exact_order,
        "stamp_tolerance_ns": args.stamp_tolerance_ns,
        "max_abs_stamp_correction_ns": (
            max(map(abs, stamp_corrections_ns)) if stamp_corrections_ns else None
        ),
        "elapsed_s": time.perf_counter() - started,
        "mean_processing_ms": float(np.mean(processing_ms)) if len(rows) else None,
        "p95_processing_ms": float(np.percentile(processing_ms, 95)) if len(rows) else None,
        "mean_tracks": float(np.mean(tracks)) if len(rows) else None,
        "mean_mature_tracks": float(np.mean(mature)) if len(rows) else None,
        "config": {
            "camera": str(args.camera_config.resolve()),
            "klt": str(args.config.resolve()),
            "preprocess": args.preprocess,
            "constant_quality": True,
            "compute_track_metadata": False,
            "vectorized_ncc": True,
        },
    }

    fieldnames = list(rows[0]) if rows else ["frame_index", "stamp"]
    with args.stats_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    args.summary_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
