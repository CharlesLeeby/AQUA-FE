#!/usr/bin/env python3
"""Merge timestamp-sorted ROS bags and optionally remove boundary duplicates."""

from __future__ import annotations

import argparse
import csv
import heapq
from pathlib import Path
from typing import Iterator, Tuple

import rosbag


BagItem = Tuple[int, int, int, str, object, object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", action="append", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--deduplicate-topic-stamp", action="store_true")
    return parser.parse_args()


def bag_items(path: Path, input_index: int) -> Iterator[BagItem]:
    with rosbag.Bag(str(path), "r") as bag:
        for sequence, (topic, msg, stamp) in enumerate(bag.read_messages()):
            yield stamp.to_nsec(), input_index, sequence, topic, msg, stamp


def main() -> int:
    args = parse_args()
    inputs = [Path(path).resolve() for path in args.input_bag]
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"missing input bag: {path}")

    output = Path(args.output_bag).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    iterators = [bag_items(path, index) for index, path in enumerate(inputs)]
    merged = heapq.merge(*iterators)
    seen: set[tuple[str, int]] = set()
    input_counts = [0] * len(inputs)
    written = 0
    duplicates = 0
    first_stamp_ns: int | None = None
    last_stamp_ns: int | None = None

    with rosbag.Bag(str(output), "w") as destination:
        for stamp_ns, input_index, _sequence, topic, msg, stamp in merged:
            input_counts[input_index] += 1
            key = (topic, stamp_ns)
            if args.deduplicate_topic_stamp and key in seen:
                duplicates += 1
                continue
            seen.add(key)
            destination.write(topic, msg, stamp)
            written += 1
            first_stamp_ns = stamp_ns if first_stamp_ns is None else first_stamp_ns
            last_stamp_ns = stamp_ns

    stats: dict[str, object] = {
        "output_bag": str(output),
        "input_bags": ";".join(str(path) for path in inputs),
        "input_message_counts": ";".join(str(count) for count in input_counts),
        "written_messages": written,
        "dropped_duplicate_topic_stamps": duplicates,
        "deduplicate_topic_stamp": int(args.deduplicate_topic_stamp),
        "first_stamp_ns": "" if first_stamp_ns is None else first_stamp_ns,
        "last_stamp_ns": "" if last_stamp_ns is None else last_stamp_ns,
    }
    stats_path = Path(args.stats_csv).resolve()
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    with stats_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stats))
        writer.writeheader()
        writer.writerow(stats)
    print(f"wrote {output}")
    print(" ".join(f"{key}={value}" for key, value in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
