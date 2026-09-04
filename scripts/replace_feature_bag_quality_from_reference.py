#!/usr/bin/env python3
"""Replace a feature bag's quality channel from a timestamp/ID reference bag."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True, type=Path)
    parser.add_argument("--reference-bag", required=True, type=Path)
    parser.add_argument("--output-bag", required=True, type=Path)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--manifest", type=Path, default=None)
    return parser.parse_args()


def values(message: object, name: str) -> list[float]:
    for channel in message.channels:
        if channel.name == name:
            return channel.values
    raise ValueError(f"missing {name!r} channel at {message.header.stamp.to_nsec()}")


def load_reference(path: Path, topic: str) -> dict[int, dict[int, float]]:
    result = {}
    with rosbag.Bag(str(path), "r") as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            ids = values(message, "id")
            quality = values(message, "quality")
            result[message.header.stamp.to_nsec()] = {
                int(round(feature_id)): float(quality[index])
                for index, feature_id in enumerate(ids)
            }
    return result


def main() -> int:
    args = parse_args()
    reference = load_reference(args.reference_bag, args.feature_topic)
    args.output_bag.parent.mkdir(parents=True, exist_ok=True)
    replaced = 0
    missing = 0
    with rosbag.Bag(str(args.input_bag), "r") as source, rosbag.Bag(
        str(args.output_bag), "w", compression=rosbag.Compression.LZ4
    ) as target:
        for topic, message, stamp in source.read_messages():
            if topic == args.feature_topic:
                frame_reference = reference.get(message.header.stamp.to_nsec(), {})
                ids = values(message, "id")
                quality = list(values(message, "quality"))
                for index, feature_id in enumerate(ids):
                    reference_quality = frame_reference.get(int(round(feature_id)))
                    if reference_quality is None:
                        missing += 1
                    else:
                        quality[index] = reference_quality
                        replaced += 1
                for channel in message.channels:
                    if channel.name == "quality":
                        channel.values = quality
                        break
            target.write(topic, message, stamp)
    manifest = {
        "schema_version": "aqua-fe-quality-reference-ablation-v1",
        "input_bag": str(args.input_bag.resolve()),
        "reference_bag": str(args.reference_bag.resolve()),
        "output_bag": str(args.output_bag.resolve()),
        "replaced_quality_observations": replaced,
        "missing_reference_observations": missing,
    }
    manifest_path = args.manifest or args.output_bag.with_suffix(
        args.output_bag.suffix + ".quality_ablation.json"
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
