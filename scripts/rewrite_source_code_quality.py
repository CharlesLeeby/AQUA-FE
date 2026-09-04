#!/usr/bin/env python3
"""Rewrite quality/sigma for feature observations with a specific source_code."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import rosbag
from sensor_msgs.msg import ChannelFloat32


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--source-code", type=int, required=True)
    parser.add_argument("--quality", type=float, required=True)
    parser.add_argument("--min-quality", type=float, default=0.05)
    args = parser.parse_args()

    stats = rewrite(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        source_code=int(args.source_code),
        quality=float(args.quality),
        min_quality=float(args.min_quality),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "source_code": int(args.source_code),
            "quality": float(args.quality),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} frames_with_rewrites={frames_with_rewrites} "
        "rewritten_observations={rewritten_observations} untouched_observations={untouched_observations}".format(
            **stats
        )
    )
    return 0


def rewrite(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    source_code: int,
    quality: float,
    min_quality: float,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    q = max(float(min_quality), min(1.0, float(quality)))
    sigma = 1.0 / math.sqrt(q)

    feature_frames = 0
    frames_with_rewrites = 0
    rewritten_observations = 0
    untouched_observations = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                sources = [int(round(item)) for item in channel_values(msg, "source_code")]
                q_values = channel_values_or_default(msg, "quality", 1.0, len(sources))
                sigma_values = channel_values_or_default(msg, "sigma", 1.0, len(sources))
                frame_rewrites = 0
                for idx, code in enumerate(sources):
                    if int(code) == int(source_code):
                        q_values[idx] = q
                        sigma_values[idx] = sigma
                        rewritten_observations += 1
                        frame_rewrites += 1
                    else:
                        untouched_observations += 1
                if frame_rewrites:
                    frames_with_rewrites += 1
                set_channel(msg, "quality", q_values)
                set_channel(msg, "sigma", sigma_values)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "frames_with_rewrites": frames_with_rewrites,
        "rewritten_observations": rewritten_observations,
        "untouched_observations": untouched_observations,
    }


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def channel_values_or_default(msg, name: str, default: float, size: int) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    return [float(default)] * int(size)


def set_channel(msg, name: str, values: list[float]) -> None:
    for channel in msg.channels:
        if channel.name == name:
            channel.values = [float(item) for item in values]
            return
    channel = ChannelFloat32(name=name)
    channel.values = [float(item) for item in values]
    msg.channels.append(channel)


def write_stats(path: Path, row: dict[str, int | float | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
