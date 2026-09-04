#!/usr/bin/env python3
"""Cap VINS feature PointCloud observations per frame while preserving sidecars."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


LEARNED_SOURCE_CODES = {10, 20, 30}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--max-features", type=int, required=True)
    parser.add_argument("--max-learned-per-frame", type=int, default=0)
    parser.add_argument("--learned-id-min", type=int, default=0)
    args = parser.parse_args()

    stats = filter_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        max_features=int(args.max_features),
        max_learned_per_frame=int(args.max_learned_per_frame),
        learned_id_min=int(args.learned_id_min),
    )
    stats.update(
        {
            "input_bag": str(args.input_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "max_features": int(args.max_features),
            "max_learned_per_frame": int(args.max_learned_per_frame),
            "learned_id_min": int(args.learned_id_min),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} dropped_observations={dropped_observations} "
        "kept_observations={kept_observations} kept_learned={kept_learned_observations}".format(
            **stats
        )
    )
    return 0


def filter_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    max_features: int,
    max_learned_per_frame: int,
    learned_id_min: int,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frames = 0
    dropped_observations = 0
    kept_observations = 0
    kept_learned_observations = 0
    frames_with_drops = 0
    frames_with_learned = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                n = len(msg.points)
                if n > 0 and max_features > 0:
                    keep = select_indices(msg, max_features, max_learned_per_frame, learned_id_min)
                    dropped = n - sum(1 for item in keep if item)
                    if dropped:
                        frames_with_drops += 1
                        dropped_observations += dropped
                        filter_channels(msg, keep)
                    kept = sum(1 for item in keep if item)
                    kept_observations += kept
                    learned_kept = count_learned(msg, learned_id_min)
                    kept_learned_observations += learned_kept
                    if learned_kept:
                        frames_with_learned += 1
            out_bag.write(topic, msg, stamp)

    return {
        "feature_frames": feature_frames,
        "frames_with_drops": frames_with_drops,
        "frames_with_learned": frames_with_learned,
        "dropped_observations": dropped_observations,
        "kept_observations": kept_observations,
        "kept_learned_observations": kept_learned_observations,
    }


def select_indices(
    msg,
    max_features: int,
    max_learned_per_frame: int,
    learned_id_min: int,
) -> list[bool]:
    n = len(msg.points)
    quality = optional_channel_values(msg, "quality", n, 1.0)
    source_code = optional_channel_values(msg, "source_code", n, 0.0)
    is_learned = optional_channel_values(msg, "is_learned", n, 0.0)
    ids = optional_channel_values(msg, "id", n, float("nan"))
    learned: list[int] = []
    classical: list[int] = []
    for idx in range(n):
        source = int(round(float(source_code[idx])))
        feature_id = safe_int(ids[idx], -1)
        if (
            float(is_learned[idx]) > 0.5
            or source in LEARNED_SOURCE_CODES
            or (learned_id_min > 0 and feature_id >= learned_id_min)
        ):
            learned.append(idx)
        else:
            classical.append(idx)

    learned.sort(key=lambda i: (-float(quality[i]), i))
    classical.sort(key=lambda i: (-float(quality[i]), i))
    learned_budget = max(0, int(max_learned_per_frame))
    if learned_budget <= 0:
        selected = classical[:max_features]
    else:
        selected_learned = learned[: min(learned_budget, max_features)]
        remaining = max(0, max_features - len(selected_learned))
        selected = selected_learned + classical[:remaining]
    keep = [False] * n
    for idx in selected:
        keep[idx] = True
    return keep


def count_learned(msg, learned_id_min: int) -> int:
    n = len(msg.points)
    source_code = optional_channel_values(msg, "source_code", n, 0.0)
    is_learned = optional_channel_values(msg, "is_learned", n, 0.0)
    ids = optional_channel_values(msg, "id", n, float("nan"))
    count = 0
    for idx in range(n):
        source = int(round(float(source_code[idx])))
        feature_id = safe_int(ids[idx], -1)
        if (
            float(is_learned[idx]) > 0.5
            or source in LEARNED_SOURCE_CODES
            or (learned_id_min > 0 and feature_id >= learned_id_min)
        ):
            count += 1
    return count


def optional_channel_values(msg, name: str, length: int, default: float) -> list[float]:
    for channel in msg.channels:
        if channel.name == name and len(channel.values) == length:
            return list(channel.values)
    return [float(default)] * length


def safe_int(value: float, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


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
