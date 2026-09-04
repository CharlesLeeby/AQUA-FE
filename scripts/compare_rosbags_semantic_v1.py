#!/usr/bin/env python3
"""Compare two ROS1 bags by ordered topic, time, type, and message bytes."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path

import rosbag


def bag_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stream_digest(path: Path) -> dict:
    digest = hashlib.sha256()
    topics = Counter()
    first_ns = None
    last_ns = None
    count = 0
    with rosbag.Bag(str(path)) as bag:
        for topic, message, stamp in bag.read_messages():
            stamp_ns = int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs)
            buffer = io.BytesIO()
            message.serialize(buffer)
            payload = buffer.getvalue()
            fields = (
                topic.encode("utf-8"), b"\0", message._type.encode("utf-8"), b"\0",
                str(stamp_ns).encode("ascii"), b"\0", str(len(payload)).encode("ascii"),
                b"\0", payload,
            )
            for field in fields:
                digest.update(field)
            topics[topic] += 1
            first_ns = stamp_ns if first_ns is None else min(first_ns, stamp_ns)
            last_ns = stamp_ns if last_ns is None else max(last_ns, stamp_ns)
            count += 1
    return {
        "ordered_message_stream_sha256": digest.hexdigest(),
        "message_count": count,
        "topic_counts": dict(sorted(topics.items())),
        "first_bag_stamp_ns": first_ns,
        "last_bag_stamp_ns": last_ns,
    }


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("left", type=Path)
    parser.add_argument("right", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for path in (args.left, args.right):
        if not path.is_file():
            raise FileNotFoundError(path)
    left = {"path": str(args.left), "bag_sha256": bag_sha256(args.left), **stream_digest(args.left)}
    right = {"path": str(args.right), "bag_sha256": bag_sha256(args.right), **stream_digest(args.right)}
    payload = {
        "schema_version": "rosbag-semantic-comparison-v1",
        "status": "IDENTICAL" if left["ordered_message_stream_sha256"] == right["ordered_message_stream_sha256"] else "DIFFERENT",
        "container_bytes_identical": left["bag_sha256"] == right["bag_sha256"],
        "ordered_message_stream_identical": left["ordered_message_stream_sha256"] == right["ordered_message_stream_sha256"],
        "left": left,
        "right": right,
    }
    atomic_json(args.output, payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["status"] == "IDENTICAL" else 1


if __name__ == "__main__":
    raise SystemExit(main())
