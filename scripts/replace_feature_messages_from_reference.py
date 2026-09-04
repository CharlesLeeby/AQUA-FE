#!/usr/bin/env python3
"""Replace selected feature PointCloud messages from a reference bag."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-bag", required=True)
    parser.add_argument("--reference-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--frame-index", action="append", type=int, required=True)
    args = parser.parse_args()

    stats = replace_messages(
        target_bag=Path(args.target_bag),
        reference_bag=Path(args.reference_bag),
        output_bag=Path(args.output_bag),
        feature_topic=str(args.feature_topic),
        frame_indices={int(item) for item in args.frame_index},
    )
    stats.update(
        {
            "target_bag": str(args.target_bag),
            "reference_bag": str(args.reference_bag),
            "output_bag": str(args.output_bag),
            "feature_topic": str(args.feature_topic),
            "frame_indices": ",".join(str(idx) for idx in sorted(set(args.frame_index))),
        }
    )
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(
        "feature_frames={feature_frames} replaced_frames={replaced_frames} "
        "missing_reference_frames={missing_reference_frames}".format(**stats)
    )
    return 0


def replace_messages(
    *,
    target_bag: Path,
    reference_bag: Path,
    output_bag: Path,
    feature_topic: str,
    frame_indices: set[int],
) -> dict[str, int]:
    reference_messages = load_reference_messages(reference_bag, feature_topic, frame_indices)
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    feature_frames = 0
    non_feature_messages = 0
    replaced_frames = 0
    missing_reference_frames = 0
    with rosbag.Bag(str(target_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                frame_index = feature_frames
                feature_frames += 1
                if frame_index in frame_indices:
                    replacement = reference_messages.get(frame_index)
                    if replacement is None:
                        missing_reference_frames += 1
                    else:
                        msg = replacement
                        replaced_frames += 1
            else:
                non_feature_messages += 1
            out_bag.write(topic, msg, stamp)
    return {
        "feature_frames": feature_frames,
        "non_feature_messages": non_feature_messages,
        "requested_frames": len(frame_indices),
        "replaced_frames": replaced_frames,
        "missing_reference_frames": missing_reference_frames,
    }


def load_reference_messages(
    reference_bag: Path,
    feature_topic: str,
    frame_indices: set[int],
) -> dict[int, object]:
    out: dict[int, object] = {}
    with rosbag.Bag(str(reference_bag), "r") as bag:
        for frame_index, (_topic, msg, _stamp) in enumerate(bag.read_messages(topics=[feature_topic])):
            if frame_index in frame_indices:
                out[frame_index] = msg
    return out


def write_stats(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
