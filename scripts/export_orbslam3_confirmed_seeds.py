#!/usr/bin/env python3
"""Export confirmed learned observations as timestamped ORB keypoint seeds."""

from __future__ import annotations

import argparse
import bisect
import json
import math
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--feature-bag", required=True)
    parser.add_argument("--image-times", required=True)
    parser.add_argument("--output-seeds", required=True)
    parser.add_argument("--output-drop-seeds", required=True)
    parser.add_argument("--output-times", required=True)
    parser.add_argument("--stats-json", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--source-code", type=int, default=20)
    parser.add_argument("--max-time-diff-ns", type=int, default=1_000_000)
    parser.add_argument("--image-width", type=int, default=0)
    parser.add_argument("--image-height", type=int, default=0)
    parser.add_argument(
        "--seed-frame-stride",
        type=int,
        default=1,
        help="Export learned seeds only on every Nth feature frame.",
    )
    parser.add_argument(
        "--seed-frame-offset",
        type=int,
        default=0,
        help="Feature-frame offset within --seed-frame-stride.",
    )
    parser.add_argument(
        "--min-seed-lineage-observations",
        type=int,
        default=1,
        help=(
            "Export a feature id only after it has appeared this many times "
            "in the confirmed seed stream."
        ),
    )
    return parser.parse_args()


def nearest_timestamp(sorted_stamps: list[int], stamp: int) -> tuple[int, int]:
    index = bisect.bisect_left(sorted_stamps, stamp)
    candidates = [candidate for candidate in (index - 1, index) if 0 <= candidate < len(sorted_stamps)]
    if not candidates:
        raise ValueError("image timestamp list is empty")
    best = min(candidates, key=lambda candidate: abs(sorted_stamps[candidate] - stamp))
    return sorted_stamps[best], abs(sorted_stamps[best] - stamp)


def channel_map(msg: object) -> dict[str, list[float]]:
    return {channel.name: channel.values for channel in msg.channels}


def main() -> int:
    args = parse_args()
    if args.seed_frame_stride < 1:
        raise SystemExit("--seed-frame-stride must be positive")
    if not 0 <= args.seed_frame_offset < args.seed_frame_stride:
        raise SystemExit("--seed-frame-offset must be in [0, seed-frame-stride)")
    if args.min_seed_lineage_observations < 1:
        raise SystemExit("--min-seed-lineage-observations must be positive")
    feature_bag = Path(args.feature_bag).resolve()
    image_times_path = Path(args.image_times).resolve()
    if not feature_bag.is_file():
        raise SystemExit(f"missing feature bag: {feature_bag}")
    if not image_times_path.is_file():
        raise SystemExit(f"missing image times: {image_times_path}")

    image_stamps = sorted({int(line.strip()) for line in image_times_path.read_text().splitlines() if line.strip()})
    if not image_stamps:
        raise SystemExit("empty image timestamp list")

    mapped_feature_stamps: list[int] = []
    seed_rows: list[tuple[int, float, float, int, float]] = []
    source_messages = 0
    max_observed_dt = 0
    rejected_out_of_bounds = 0
    rejected_nonfinite = 0
    rejected_by_stride = 0
    rejected_by_lineage_maturity = 0
    lineage_observations: dict[int, int] = {}
    missing_channels: set[str] = set()

    with rosbag.Bag(str(feature_bag), "r") as bag:
        for frame_index, (_, msg, record_stamp) in enumerate(
            bag.read_messages(topics=[args.feature_topic])
        ):
            source_messages += 1
            stamp = msg.header.stamp.to_nsec() if msg.header.stamp.to_nsec() > 0 else record_stamp.to_nsec()
            mapped_stamp, time_diff = nearest_timestamp(image_stamps, stamp)
            max_observed_dt = max(max_observed_dt, time_diff)
            if time_diff > args.max_time_diff_ns:
                raise SystemExit(
                    f"feature/image timestamp mismatch {time_diff} ns exceeds "
                    f"{args.max_time_diff_ns} ns at {stamp}"
                )
            mapped_feature_stamps.append(mapped_stamp)

            channels = channel_map(msg)
            required = {"source_code", "p_u", "p_v", "id"}
            absent = required.difference(channels)
            if absent:
                missing_channels.update(absent)
                continue
            quality = channels.get("quality", [1.0] * len(msg.points))
            for index in range(len(msg.points)):
                if int(round(channels["source_code"][index])) != args.source_code:
                    continue
                feature_id = int(round(channels["id"][index]))
                lineage_observations[feature_id] = (
                    lineage_observations.get(feature_id, 0) + 1
                )
                if frame_index % args.seed_frame_stride != args.seed_frame_offset:
                    rejected_by_stride += 1
                    continue
                if (
                    lineage_observations[feature_id]
                    < args.min_seed_lineage_observations
                ):
                    rejected_by_lineage_maturity += 1
                    continue
                x = float(channels["p_u"][index])
                y = float(channels["p_v"][index])
                if not math.isfinite(x) or not math.isfinite(y):
                    rejected_nonfinite += 1
                    continue
                if args.image_width > 0 and not (0.0 <= x < args.image_width):
                    rejected_out_of_bounds += 1
                    continue
                if args.image_height > 0 and not (0.0 <= y < args.image_height):
                    rejected_out_of_bounds += 1
                    continue
                seed_rows.append((mapped_stamp, x, y, feature_id, float(quality[index])))

    if source_messages == 0:
        raise SystemExit(f"no messages on {args.feature_topic}")
    if missing_channels:
        raise SystemExit(f"feature messages missing channels: {sorted(missing_channels)}")

    unique_feature_stamps = sorted(set(mapped_feature_stamps))
    if len(unique_feature_stamps) != len(mapped_feature_stamps):
        raise SystemExit("multiple feature messages mapped to the same raw image timestamp")

    output_seeds = Path(args.output_seeds).resolve()
    output_drop = Path(args.output_drop_seeds).resolve()
    output_times = Path(args.output_times).resolve()
    stats_path = Path(args.stats_json).resolve()
    for path in (output_seeds, output_drop, output_times, stats_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    header = "# timestamp_ns p_u p_v feature_id quality\n"
    output_seeds.write_text(
        header
        + "".join(
            f"{stamp} {x:.9f} {y:.9f} {feature_id} {quality:.9f}\n"
            for stamp, x, y, feature_id, quality in seed_rows
        ),
        encoding="ascii",
    )
    output_drop.write_text(header, encoding="ascii")
    output_times.write_text("".join(f"{stamp}\n" for stamp in unique_feature_stamps), encoding="ascii")

    stats = {
        "feature_bag": str(feature_bag),
        "feature_topic": args.feature_topic,
        "source_code": args.source_code,
        "seed_frame_stride": args.seed_frame_stride,
        "seed_frame_offset": args.seed_frame_offset,
        "min_seed_lineage_observations": args.min_seed_lineage_observations,
        "source_messages": source_messages,
        "mapped_feature_frames": len(unique_feature_stamps),
        "seed_observations": len(seed_rows),
        "seed_frames": len({row[0] for row in seed_rows}),
        "seed_ids": len({row[3] for row in seed_rows}),
        "max_timestamp_difference_ns": max_observed_dt,
        "rejected_nonfinite": rejected_nonfinite,
        "rejected_out_of_bounds": rejected_out_of_bounds,
        "rejected_by_stride": rejected_by_stride,
        "rejected_by_lineage_maturity": rejected_by_lineage_maturity,
        "output_seeds": str(output_seeds),
        "output_drop_seeds": str(output_drop),
        "output_times": str(output_times),
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps(stats, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
