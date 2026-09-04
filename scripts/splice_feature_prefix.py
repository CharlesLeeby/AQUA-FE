#!/usr/bin/env python3
"""Splice a feature-message prefix from one bag into a complete feature bag."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-bag", required=True, help="Complete bag containing IMU/GT and all feature frames.")
    parser.add_argument("--prefix-bag", required=True, help="Bag providing replacement feature messages.")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--prefix-frames", type=int, default=0, help="Number of feature frames to replace.")
    args = parser.parse_args()

    stats = splice_feature_prefix(
        base_bag=Path(args.base_bag),
        prefix_bag=Path(args.prefix_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        prefix_frames=int(args.prefix_frames),
    )
    stats.update(
        {
            "base_bag": str(args.base_bag),
            "prefix_bag": str(args.prefix_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "prefix_frames_requested": int(args.prefix_frames),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "base_feature_frames={base_feature_frames} replaced_feature_frames={replaced_feature_frames} "
        "copied_prefix_messages={prefix_feature_frames}".format(**stats)
    )
    return 0


def splice_feature_prefix(
    *,
    base_bag: Path,
    prefix_bag: Path,
    output_bag: Path,
    feature_topic: str,
    prefix_frames: int,
) -> dict[str, int]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    prefix_messages = []
    with rosbag.Bag(str(prefix_bag), "r") as in_prefix:
        for _topic, msg, stamp in in_prefix.read_messages(topics=[feature_topic]):
            prefix_messages.append((msg, stamp))
            if prefix_frames > 0 and len(prefix_messages) >= prefix_frames:
                break

    replaced = 0
    base_feature_frames = 0
    base_non_feature_messages = 0
    written_messages = 0
    with rosbag.Bag(str(base_bag), "r") as in_base, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_base.read_messages():
            if topic == feature_topic:
                if replaced < prefix_frames and replaced < len(prefix_messages):
                    prefix_msg, _prefix_stamp = prefix_messages[replaced]
                    out_bag.write(topic, prefix_msg, stamp)
                    replaced += 1
                else:
                    out_bag.write(topic, msg, stamp)
                base_feature_frames += 1
            else:
                out_bag.write(topic, msg, stamp)
                base_non_feature_messages += 1
            written_messages += 1

    return {
        "prefix_feature_frames": len(prefix_messages),
        "base_feature_frames": base_feature_frames,
        "base_non_feature_messages": base_non_feature_messages,
        "replaced_feature_frames": replaced,
        "written_messages": written_messages,
    }


def write_stats(path: Path, stats: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats.keys()))
        writer.writeheader()
        writer.writerow(stats)


if __name__ == "__main__":
    raise SystemExit(main())
