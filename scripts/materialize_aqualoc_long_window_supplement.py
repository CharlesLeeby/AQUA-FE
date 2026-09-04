#!/usr/bin/env python3
"""Materialize one preregistered AQUALOC long window from overlapping bags."""

from __future__ import annotations

import argparse
import heapq
import json
from pathlib import Path
from typing import Iterator

import rosbag


TOPICS = ("/camera/image_raw", "/rtimulib_node/imu", "/aqualoc/colmap_gt")


def stamp_ns(message, fallback) -> int:
    stamp = getattr(getattr(message, "header", None), "stamp", None)
    if stamp is not None and (stamp.secs != 0 or stamp.nsecs != 0):
        return int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs)
    return int(fallback.secs) * 1_000_000_000 + int(fallback.nsecs)


def stream(path: Path) -> Iterator[tuple[str, object, object]]:
    bag = rosbag.Bag(str(path), "r")
    try:
        yield from bag.read_messages(topics=list(TOPICS))
    finally:
        bag.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", action="append", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--origin-ns", type=int, required=True)
    parser.add_argument("--start-s", type=float, required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--audit-json", required=True)
    args = parser.parse_args()

    inputs = [Path(value).resolve() for value in args.input_bag]
    output = Path(args.output_bag).resolve()
    audit_path = Path(args.audit_json).resolve()
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f"missing input bag: {path}")
    if output.exists():
        raise SystemExit(f"refusing existing output: {output}")

    lo_ns = int(args.origin_ns + round(args.start_s * 1_000_000_000))
    hi_ns = int(lo_ns + round(args.duration_s * 1_000_000_000))
    output.parent.mkdir(parents=True, exist_ok=True)
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    iterators = [iter(stream(path)) for path in inputs]
    heap: list[tuple[int, int, str, object, object]] = []
    for index, iterator in enumerate(iterators):
        try:
            topic, message, record_stamp = next(iterator)
        except StopIteration:
            continue
        heapq.heappush(
            heap, (stamp_ns(message, record_stamp), index, topic, message, record_stamp)
        )

    counts = {topic: 0 for topic in TOPICS}
    first_ns: dict[str, int] = {}
    last_ns: dict[str, int] = {}
    seen: set[tuple[str, int]] = set()
    duplicate_count = 0
    with rosbag.Bag(str(output), "w", compression=rosbag.Compression.BZ2) as dst:
        while heap:
            message_ns, index, topic, message, record_stamp = heapq.heappop(heap)
            key = (topic, message_ns)
            if lo_ns <= message_ns < hi_ns:
                if key in seen:
                    duplicate_count += 1
                else:
                    seen.add(key)
                    dst.write(topic, message, record_stamp)
                    counts[topic] += 1
                    first_ns.setdefault(topic, message_ns)
                    last_ns[topic] = message_ns
            try:
                next_topic, next_message, next_record_stamp = next(iterators[index])
                heapq.heappush(
                    heap,
                    (
                        stamp_ns(next_message, next_record_stamp),
                        index,
                        next_topic,
                        next_message,
                        next_record_stamp,
                    ),
                )
            except StopIteration:
                pass

    expected_images = 901 if abs(args.start_s) < 1e-12 else 900
    if counts["/camera/image_raw"] != expected_images:
        raise SystemExit(
            f"image count mismatch: expected {expected_images}, got {counts['/camera/image_raw']}"
        )
    if counts["/rtimulib_node/imu"] == 0 or counts["/aqualoc/colmap_gt"] < 40:
        raise SystemExit(f"insufficient IMU/proxy support: {counts}")

    payload = {
        "schema_version": "aqua-fe-a06-long-window-materialization-v1",
        "inputs": [str(path) for path in inputs],
        "output": str(output),
        "half_open_start_ns": lo_ns,
        "half_open_end_ns": hi_ns,
        "counts": counts,
        "first_header_stamp_ns": first_ns,
        "last_header_stamp_ns": last_ns,
        "deduplicated_topic_stamp_pairs": duplicate_count,
    }
    audit_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
