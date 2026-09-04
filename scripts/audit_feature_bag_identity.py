#!/usr/bin/env python3
"""Audit exact serialized equality of two header-stamped feature streams."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-bag", type=Path, required=True)
    parser.add_argument("--candidate-bag", type=Path, required=True)
    parser.add_argument("--topic", default="/feature_tracker/feature")
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def scan(path: Path, topic: str) -> tuple[list[tuple[int, int, bytes]], dict[str, object]]:
    result: list[tuple[int, int, bytes]] = []
    digest = hashlib.sha256()
    first_stamp_ns = None
    last_stamp_ns = None
    with rosbag.Bag(str(path), "r") as bag:
        for _topic, msg, record_stamp in bag.read_messages(topics=[topic]):
            payload = io.BytesIO()
            msg.serialize(payload)
            blob = payload.getvalue()
            header_ns = int(msg.header.stamp.to_nsec())
            record_ns = int(record_stamp.to_nsec())
            digest.update(header_ns.to_bytes(8, "little", signed=False))
            digest.update(record_ns.to_bytes(8, "little", signed=False))
            digest.update(len(blob).to_bytes(8, "little", signed=False))
            digest.update(blob)
            result.append((header_ns, record_ns, blob))
            first_stamp_ns = header_ns if first_stamp_ns is None else first_stamp_ns
            last_stamp_ns = header_ns
    return result, {
        "path": str(path.resolve()),
        "frames": len(result),
        "first_stamp_ns": first_stamp_ns,
        "last_stamp_ns": last_stamp_ns,
        "stream_sha256": digest.hexdigest(),
    }


def main() -> int:
    args = parse_args()
    reference, reference_meta = scan(args.reference_bag, args.topic)
    candidate, candidate_meta = scan(args.candidate_bag, args.topic)
    mismatch_indices: list[int] = []
    for index, (left, right) in enumerate(zip(reference, candidate)):
        if left != right:
            mismatch_indices.append(index)
            if len(mismatch_indices) >= 20:
                break
    length_equal = len(reference) == len(candidate)
    identical = length_equal and not mismatch_indices
    summary = {
        "schema": "feature_bag_serialized_identity_v1",
        "status": "PASS" if identical else "FAIL",
        "topic": args.topic,
        "reference": reference_meta,
        "candidate": candidate_meta,
        "frame_count_equal": length_equal,
        "serialized_messages_and_record_stamps_identical": identical,
        "first_mismatch_indices": mismatch_indices,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if identical else 2


if __name__ == "__main__":
    raise SystemExit(main())
