#!/usr/bin/env python3
"""Rewrite a VINS external-feature bag with an early parallax initialization gate.

The gate is intentionally simple and observable: it estimates the mean
inter-frame displacement of persistent feature IDs in the first few feature
frames. If the early displacement is below a threshold, the first N feature
messages are withheld so VINS initializes after a short, higher-baseline
visual window. Non-feature topics are copied unchanged.
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--probe-frames", type=int, default=5)
    parser.add_argument("--parallax-threshold-px", type=float, default=7.0)
    parser.add_argument("--skip-feature-frames", type=int, default=4)
    parser.add_argument("--max-skip-feature-frames", type=int, default=4)
    parser.add_argument("--summary-csv", default=None)
    args = parser.parse_args()

    input_bag = Path(args.input_bag)
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)

    probe_frames = max(2, int(args.probe_frames))
    feature_frames = _load_probe_feature_frames(input_bag, args.feature_topic, probe_frames)
    mean_step = _mean_interframe_parallax(feature_frames)
    triggered = math.isfinite(mean_step) and mean_step < float(args.parallax_threshold_px)
    skip_count = int(args.skip_feature_frames) if triggered else 0
    skip_count = min(max(0, skip_count), max(0, int(args.max_skip_feature_frames)))

    stats = _rewrite_bag(input_bag, output_bag, args.feature_topic, skip_count)
    row = {
        "input_bag": str(input_bag),
        "output_bag": str(output_bag),
        "feature_topic": args.feature_topic,
        "probe_frames": probe_frames,
        "mean_step_px": mean_step,
        "parallax_threshold_px": float(args.parallax_threshold_px),
        "triggered": int(triggered),
        "skip_feature_frames": skip_count,
        **stats,
    }
    if args.summary_csv:
        _write_summary(Path(args.summary_csv), row)
    print(
        "triggered={triggered} mean_step_px={mean_step_px:.6f} "
        "skip_feature_frames={skip_feature_frames} written_features={written_feature_frames}".format(
            **row
        )
    )
    return 0


def _load_probe_feature_frames(
    bag_path: Path,
    feature_topic: str,
    max_frames: int,
) -> list[dict[int, tuple[float, float]]]:
    frames: list[dict[int, tuple[float, float]]] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            frames.append(_feature_points_by_id(msg))
            if len(frames) >= max_frames:
                break
    return frames


def _feature_points_by_id(msg) -> dict[int, tuple[float, float]]:
    channels = {channel.name: channel.values for channel in getattr(msg, "channels", [])}
    ids = channels.get("id", [])
    pu = channels.get("p_u", [])
    pv = channels.get("p_v", [])
    count = min(len(ids), len(pu), len(pv))
    points: dict[int, tuple[float, float]] = {}
    for idx in range(count):
        try:
            points[int(ids[idx])] = (float(pu[idx]), float(pv[idx]))
        except (TypeError, ValueError):
            continue
    return points


def _mean_interframe_parallax(frames: list[dict[int, tuple[float, float]]]) -> float:
    steps: list[float] = []
    for prev, cur in zip(frames, frames[1:]):
        common = set(prev).intersection(cur)
        if not common:
            continue
        disp = [
            math.hypot(cur[fid][0] - prev[fid][0], cur[fid][1] - prev[fid][1])
            for fid in common
        ]
        if disp:
            steps.append(float(statistics.mean(disp)))
    return float(statistics.mean(steps)) if steps else float("nan")


def _rewrite_bag(
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    skip_feature_frames: int,
) -> dict[str, int]:
    seen_features = 0
    written_features = 0
    skipped_features = 0
    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                if seen_features < skip_feature_frames:
                    skipped_features += 1
                    seen_features += 1
                    continue
                seen_features += 1
                written_features += 1
            out_bag.write(topic, msg, stamp)
    return {
        "input_feature_frames": seen_features,
        "written_feature_frames": written_features,
        "skipped_feature_frames": skipped_features,
    }


def _write_summary(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
