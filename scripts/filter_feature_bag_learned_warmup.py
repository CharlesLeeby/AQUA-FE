#!/usr/bin/env python3
"""Remove learned sidecars during a fixed VINS initialization warmup.

The filter is causal: its decision uses only elapsed feature-stream time and
the per-observation provenance channels already stored in the bag.  Classical
observations and all non-feature topics are copied byte-for-byte at message
level.  It is used to validate a no-harm policy after short learned lineages
were shown to perturb VINS's initialization RANSAC.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import rosbag


LEARNED_SOURCE_CODES = {10, 20, 30}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True, type=Path)
    parser.add_argument("--output-bag", required=True, type=Path)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--warmup-s", type=float, default=15.0)
    parser.add_argument("--manifest", type=Path, default=None)
    return parser.parse_args()


def channel_map(message: object) -> dict[str, object]:
    return {channel.name: channel for channel in message.channels}


def learned_mask(message: object) -> list[bool]:
    channels = channel_map(message)
    count = len(message.points)
    ids = channels.get("id")
    source = channels.get("source_code")
    is_learned = channels.get("is_learned")
    mask = []
    for index in range(count):
        feature_id = int(round(ids.values[index])) if ids is not None else -1
        source_code = (
            int(round(source.values[index])) if source is not None else 0
        )
        learned_flag = (
            is_learned is not None and is_learned.values[index] > 0.5
        )
        mask.append(
            feature_id >= 10_000_000
            or source_code in LEARNED_SOURCE_CODES
            or learned_flag
        )
    return mask


def first_feature_stamp(path: Path, topic: str) -> float:
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            return message.header.stamp.to_sec()
    raise ValueError(f"no messages on {topic} in {path}")


def main() -> int:
    args = parse_args()
    if args.warmup_s < 0.0:
        raise SystemExit("--warmup-s must be nonnegative")
    start = first_feature_stamp(args.input_bag, args.feature_topic)
    cutoff = start + args.warmup_s
    args.output_bag.parent.mkdir(parents=True, exist_ok=True)

    feature_frames = 0
    removed = 0
    retained_learned = 0
    retained_classical = 0
    with rosbag.Bag(str(args.input_bag), "r") as source, rosbag.Bag(
        str(args.output_bag), "w", compression=rosbag.Compression.LZ4
    ) as target:
        for topic, message, bag_stamp in source.read_messages():
            if topic == args.feature_topic:
                feature_frames += 1
                mask = learned_mask(message)
                before_cutoff = message.header.stamp.to_sec() < cutoff
                keep = [not (before_cutoff and learned) for learned in mask]
                removed += sum(learned and not selected for learned, selected in zip(mask, keep))
                retained_learned += sum(learned and selected for learned, selected in zip(mask, keep))
                retained_classical += sum(not learned and selected for learned, selected in zip(mask, keep))
                if not all(keep):
                    message.points = [point for point, selected in zip(message.points, keep) if selected]
                    for channel in message.channels:
                        channel.values = [
                            value for value, selected in zip(channel.values, keep) if selected
                        ]
            target.write(topic, message, bag_stamp)

    manifest = {
        "schema_version": "aqua-fe-learned-warmup-filter-v1",
        "input_bag": str(args.input_bag.resolve()),
        "output_bag": str(args.output_bag.resolve()),
        "feature_topic": args.feature_topic,
        "first_feature_stamp_s": start,
        "warmup_s": args.warmup_s,
        "cutoff_stamp_s": cutoff,
        "feature_frames": feature_frames,
        "removed_learned_observations": removed,
        "retained_learned_observations": retained_learned,
        "retained_classical_observations": retained_classical,
    }
    manifest_path = args.manifest or args.output_bag.with_suffix(
        args.output_bag.suffix + ".warmup_filter.json"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
