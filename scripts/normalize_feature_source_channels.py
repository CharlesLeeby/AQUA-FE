#!/usr/bin/env python3
"""Add complete source_code/is_learned channels to legacy feature bags."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag
from sensor_msgs.msg import ChannelFloat32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--learned-id-min", type=int, required=True)
    parser.add_argument("--learned-source-code", type=int, default=20)
    return parser.parse_args()


def channel_map(msg: object) -> dict[str, ChannelFloat32]:
    return {channel.name: channel for channel in msg.channels}


def add_channel(msg: object, name: str, values: list[float]) -> None:
    channel = ChannelFloat32(name=name)
    channel.values = values
    msg.channels.append(channel)


def normalize(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    learned_id_min: int,
    learned_source_code: int,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    stats = {
        "feature_frames": 0,
        "observations": 0,
        "learned_observations": 0,
        "source_code_channels_added": 0,
        "is_learned_channels_added": 0,
        "existing_channels_verified": 0,
    }

    with rosbag.Bag(str(input_bag), "r") as source, rosbag.Bag(
        str(output_bag), "w"
    ) as output:
        for topic, msg, stamp in source.read_messages():
            if topic == feature_topic:
                stats["feature_frames"] += 1
                channels = channel_map(msg)
                count = len(msg.points)
                ids = channels.get("id")
                if ids is None or len(ids.values) != count:
                    raise ValueError(
                        f"feature frame {stats['feature_frames'] - 1} has invalid id channel"
                    )
                learned = [
                    int(round(value)) >= learned_id_min for value in ids.values
                ]
                expected_source = [
                    float(learned_source_code if value else 0) for value in learned
                ]
                expected_learned = [float(value) for value in learned]

                source_code = channels.get("source_code")
                if source_code is None:
                    add_channel(msg, "source_code", expected_source)
                    stats["source_code_channels_added"] += 1
                elif list(source_code.values) != expected_source:
                    raise ValueError(
                        f"feature frame {stats['feature_frames'] - 1} source_code conflicts "
                        "with learned-id contract"
                    )
                else:
                    stats["existing_channels_verified"] += 1

                is_learned = channels.get("is_learned")
                if is_learned is None:
                    add_channel(msg, "is_learned", expected_learned)
                    stats["is_learned_channels_added"] += 1
                elif list(is_learned.values) != expected_learned:
                    raise ValueError(
                        f"feature frame {stats['feature_frames'] - 1} is_learned conflicts "
                        "with learned-id contract"
                    )

                stats["observations"] += count
                stats["learned_observations"] += sum(learned)
            output.write(topic, msg, stamp)
    return stats


def write_stats(path: Path, stats: dict[str, int], args: argparse.Namespace) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, int | str] = {
        **stats,
        "input_bag": str(Path(args.input_bag).resolve()),
        "output_bag": str(Path(args.output_bag).resolve()),
        "feature_topic": args.feature_topic,
        "learned_id_min": args.learned_id_min,
        "learned_source_code": args.learned_source_code,
    }
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row), lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def main() -> int:
    args = parse_args()
    if args.learned_id_min <= 0:
        raise SystemExit("--learned-id-min must be positive")
    stats = normalize(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=args.feature_topic,
        learned_id_min=args.learned_id_min,
        learned_source_code=args.learned_source_code,
    )
    write_stats(Path(args.stats_csv), stats, args)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} observations={observations} "
        "learned_observations={learned_observations} "
        "source_code_channels_added={source_code_channels_added} "
        "is_learned_channels_added={is_learned_channels_added}".format(**stats)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
