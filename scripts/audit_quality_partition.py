#!/usr/bin/env python3
"""Fail-closed audit for a source-partition quality rewrite of a ROS bag."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
from pathlib import Path

import rosbag


FEATURE_TOPIC = "/feature_tracker/feature"
QUALITY_CHANNELS = {"quality", "sigma"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", type=Path, required=True)
    parser.add_argument("--output-bag", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC)
    parser.add_argument("--source-code", action="append", type=int, required=True)
    parser.add_argument("--quality", type=float, required=True)
    parser.add_argument("--min-quality", type=float, default=0.05)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def deserialize(raw_message):
    _msg_type, serialized, _md5sum, _position, pytype = raw_message
    msg = pytype()
    msg.deserialize(serialized)
    return msg


def channels(msg) -> dict[str, list[float]]:
    names = [channel.name for channel in msg.channels]
    if len(names) != len(set(names)):
        raise ValueError("duplicate feature channel name")
    return {channel.name: list(channel.values) for channel in msg.channels}


def same_stamp(left, right) -> bool:
    return left.secs == right.secs and left.nsecs == right.nsecs


def audit_bags(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    source_codes: set[int],
    quality: float,
    min_quality: float,
) -> dict[str, object]:
    q = max(float(min_quality), min(1.0, float(quality)))
    sigma = 1.0 / math.sqrt(q)
    total_messages = 0
    raw_equal_nonfeature_messages = 0
    feature_frames = 0
    selected_observations = 0
    changed_observations = 0
    untouched_observations = 0

    with rosbag.Bag(str(input_bag), "r") as left_bag, rosbag.Bag(str(output_bag), "r") as right_bag:
        left_messages = left_bag.read_messages(raw=True, return_connection_header=True)
        right_messages = right_bag.read_messages(raw=True, return_connection_header=True)
        for message_index, pair in enumerate(
            itertools.zip_longest(left_messages, right_messages, fillvalue=None)
        ):
            left, right = pair
            if left is None or right is None:
                raise ValueError("message count differs")
            total_messages += 1
            if left.topic != right.topic or not same_stamp(left.timestamp, right.timestamp):
                raise ValueError(f"message topology differs at index {message_index}")
            if left.message[0] != right.message[0] or left.message[2] != right.message[2]:
                raise ValueError(f"message type differs at index {message_index}")
            if left.topic != feature_topic:
                if left.message[1] != right.message[1]:
                    raise ValueError(f"non-feature payload differs at index {message_index}")
                raw_equal_nonfeature_messages += 1
                continue

            feature_frames += 1
            left_msg = deserialize(left.message)
            right_msg = deserialize(right.message)
            if left_msg.header != right_msg.header or left_msg.points != right_msg.points:
                raise ValueError(f"feature header/points differ at frame {feature_frames - 1}")
            left_channels = channels(left_msg)
            right_channels = channels(right_msg)
            if list(left_channels) != list(right_channels):
                raise ValueError(f"feature channel order differs at frame {feature_frames - 1}")
            if set(left_channels) != set(right_channels):
                raise ValueError(f"feature channel set differs at frame {feature_frames - 1}")
            for name in left_channels:
                if name not in QUALITY_CHANNELS and left_channels[name] != right_channels[name]:
                    raise ValueError(
                        f"non-quality channel {name} differs at frame {feature_frames - 1}"
                    )

            required = {"source_code", "quality", "sigma"}
            if not required.issubset(left_channels):
                raise ValueError(f"missing required channel at frame {feature_frames - 1}")
            count = len(left_msg.points)
            for name in required:
                if len(left_channels[name]) != count or len(right_channels[name]) != count:
                    raise ValueError(f"channel length mismatch for {name}")
            for observation_index in range(count):
                source_code = int(round(left_channels["source_code"][observation_index]))
                left_q = left_channels["quality"][observation_index]
                right_q = right_channels["quality"][observation_index]
                left_sigma = left_channels["sigma"][observation_index]
                right_sigma = right_channels["sigma"][observation_index]
                if source_code in source_codes:
                    selected_observations += 1
                    if not math.isclose(right_q, q, rel_tol=0.0, abs_tol=1e-6):
                        raise ValueError("selected observation has unexpected quality")
                    if not math.isclose(right_sigma, sigma, rel_tol=0.0, abs_tol=1e-6):
                        raise ValueError("selected observation has unexpected sigma")
                    if left_q != right_q or left_sigma != right_sigma:
                        changed_observations += 1
                else:
                    untouched_observations += 1
                    if left_q != right_q or left_sigma != right_sigma:
                        raise ValueError("unselected observation quality/sigma changed")

    if feature_frames == 0 or selected_observations == 0:
        raise ValueError("audit has no selected feature observations")
    return {
        "schema_version": "aqua-fe-quality-partition-audit-v1",
        "contract_pass": True,
        "input_bag": str(input_bag),
        "input_sha256": sha256(input_bag),
        "output_bag": str(output_bag),
        "output_sha256": sha256(output_bag),
        "feature_topic": feature_topic,
        "source_codes": sorted(source_codes),
        "quality": q,
        "sigma": sigma,
        "total_messages": total_messages,
        "raw_equal_nonfeature_messages": raw_equal_nonfeature_messages,
        "feature_frames": feature_frames,
        "selected_observations": selected_observations,
        "changed_observations": changed_observations,
        "untouched_observations": untouched_observations,
    }


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    args = parse_args()
    result = audit_bags(
        input_bag=args.input_bag,
        output_bag=args.output_bag,
        feature_topic=str(args.feature_topic),
        source_codes=set(args.source_code),
        quality=float(args.quality),
        min_quality=float(args.min_quality),
    )
    write_json(args.audit_json, result)
    print(
        "QUALITY_PARTITION_AUDIT PASS "
        f"messages={result['total_messages']} features={result['feature_frames']} "
        f"selected={result['selected_observations']} changed={result['changed_observations']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
