#!/usr/bin/env python3
"""Keep high-id feature observations only within a feature-frame index range."""

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
    parser.add_argument("--id-min", type=int, default=10_000_000)
    parser.add_argument("--keep-start", type=int, required=True)
    parser.add_argument("--keep-end", type=int, required=True)
    parser.add_argument("--quality", type=float, default=None)
    parser.add_argument("--min-quality", type=float, default=0.05)
    args = parser.parse_args()

    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=args.feature_topic,
        id_min=int(args.id_min),
        keep_start=int(args.keep_start),
        keep_end=int(args.keep_end),
        quality=args.quality,
        min_quality=float(args.min_quality),
    )
    stats.update(
        {
            "input_bag": args.input_bag,
            "output_bag": args.output_bag,
            "feature_topic": args.feature_topic,
            "id_min": int(args.id_min),
            "keep_start": int(args.keep_start),
            "keep_end": int(args.keep_end),
            "quality": "" if args.quality is None else float(args.quality),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} kept_high_id={kept_high_id} "
        "dropped_high_id={dropped_high_id} kept_total={kept_total}".format(**stats)
    )
    return 0


def filter_bag(
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    id_min: int,
    keep_start: int,
    keep_end: int,
    quality: float | None,
    min_quality: float,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frame = -1
    feature_frames = 0
    kept_high_id = 0
    dropped_high_id = 0
    kept_total = 0
    q = None if quality is None else max(float(min_quality), min(1.0, float(quality)))
    sigma = None if q is None else 1.0 / math.sqrt(q)

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frame += 1
                feature_frames += 1
                ids = [int(round(item)) for item in channel_values(msg, "id")]
                keep_high = keep_start <= feature_frame <= keep_end
                keep_mask = []
                for feature_id in ids:
                    is_high = feature_id >= int(id_min)
                    if is_high and not keep_high:
                        keep_mask.append(False)
                        dropped_high_id += 1
                    else:
                        keep_mask.append(True)
                        kept_total += 1
                        if is_high:
                            kept_high_id += 1
                apply_mask(msg, keep_mask)
                if q is not None and kept_high_id:
                    rewrite_high_quality(msg, id_min, q, sigma)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "kept_high_id": kept_high_id,
        "dropped_high_id": dropped_high_id,
        "kept_total": kept_total,
    }


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def apply_mask(msg, keep_mask: list[bool]) -> None:
    msg.points = [point for point, keep in zip(msg.points, keep_mask) if keep]
    for channel in msg.channels:
        channel.values = [value for value, keep in zip(channel.values, keep_mask) if keep]


def rewrite_high_quality(msg, id_min: int, q: float, sigma: float) -> None:
    ids = [int(round(item)) for item in channel_values(msg, "id")]
    q_values = channel_values_or_default(msg, "quality", 1.0, len(ids))
    sigma_values = channel_values_or_default(msg, "sigma", 1.0, len(ids))
    for idx, feature_id in enumerate(ids):
        if feature_id >= int(id_min):
            q_values[idx] = q
            sigma_values[idx] = sigma
    set_channel(msg, "quality", q_values)
    set_channel(msg, "sigma", sigma_values)


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
