#!/usr/bin/env python3
"""Keep selected source_code observations only within a feature-frame range."""

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
    parser.add_argument("--source-code", type=int, action="append", required=True)
    parser.add_argument("--keep-start", type=int, required=True)
    parser.add_argument("--keep-end", type=int, required=True)
    args = parser.parse_args()

    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        source_codes={int(code) for code in args.source_code},
        keep_start=int(args.keep_start),
        keep_end=int(args.keep_end),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "source_code": ",".join(str(code) for code in sorted(set(args.source_code))),
            "keep_start": int(args.keep_start),
            "keep_end": int(args.keep_end),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} kept_selected={kept_selected} "
        "dropped_selected={dropped_selected} kept_total={kept_total}".format(**stats)
    )
    return 0


def filter_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    source_codes: set[int],
    keep_start: int,
    keep_end: int,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frame = -1
    feature_frames = 0
    kept_selected = 0
    dropped_selected = 0
    kept_total = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frame += 1
                feature_frames += 1
                source_values = channel_values(msg, "source_code")
                keep_selected_frame = int(keep_start) <= feature_frame <= int(keep_end)
                keep_mask: list[bool] = []
                for value in source_values:
                    selected = int(round(float(value))) in source_codes
                    keep = (not selected) or keep_selected_frame
                    keep_mask.append(keep)
                    if keep:
                        kept_total += 1
                        if selected:
                            kept_selected += 1
                    elif selected:
                        dropped_selected += 1
                apply_mask(msg, keep_mask)
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "kept_selected": kept_selected,
        "dropped_selected": dropped_selected,
        "kept_total": kept_total,
    }


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def apply_mask(msg, keep_mask: list[bool]) -> None:
    if len(msg.points) == len(keep_mask):
        msg.points = [point for point, keep in zip(msg.points, keep_mask) if keep]
    for channel in msg.channels:
        if len(channel.values) == len(keep_mask):
            channel.values = [float(value) for value, keep in zip(channel.values, keep_mask) if keep]


def write_stats(path: Path, row: dict[str, int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
