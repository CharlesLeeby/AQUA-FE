#!/usr/bin/env python3
"""Drop feature observations whose ids are above a threshold from a ROS bag."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--id-min", type=int, default=10_000_000)
    args = parser.parse_args()

    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        id_min=int(args.id_min),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "id_min": int(args.id_min),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} dropped_observations={dropped_observations} "
        "kept_observations={kept_observations}".format(**stats)
    )
    return 0


def filter_bag(
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    id_min: int,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frames = 0
    frames_with_drops = 0
    dropped_observations = 0
    kept_observations = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                ids = channel_values(msg, "id")
                keep = [int(round(feature_id)) < int(id_min) for feature_id in ids]
                dropped = len(keep) - sum(1 for item in keep if item)
                if dropped:
                    frames_with_drops += 1
                    dropped_observations += dropped
                    filter_channels(msg, keep)
                kept_observations += sum(1 for item in keep if item)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "frames_with_drops": frames_with_drops,
        "dropped_observations": dropped_observations,
        "kept_observations": kept_observations,
    }


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def filter_channels(msg, keep: list[bool]) -> None:
    if len(msg.points) == len(keep):
        msg.points = [point for point, keep_value in zip(msg.points, keep) if keep_value]
    for channel in msg.channels:
        if len(channel.values) == len(keep):
            channel.values = [float(value) for value, keep_value in zip(channel.values, keep) if keep_value]


def write_stats(path: Path, row: dict[str, int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
