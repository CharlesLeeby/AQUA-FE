#!/usr/bin/env python3
"""Rewrite backend quality for selected feature sources with raw message copying."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import time
from collections import Counter
from pathlib import Path

import rosbag


FEATURE_TOPIC = "/feature_tracker/feature"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", type=Path, required=True)
    parser.add_argument("--output-bag", type=Path, required=True)
    parser.add_argument("--stats-json", type=Path, required=True)
    parser.add_argument("--feature-topic", default=FEATURE_TOPIC)
    parser.add_argument(
        "--source-code",
        action="append",
        type=int,
        required=True,
        help="Source code to rewrite; repeat for a source partition.",
    )
    parser.add_argument("--quality", type=float, required=True)
    parser.add_argument("--min-quality", type=float, default=0.05)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def channel_values(msg, name: str) -> list[float]:
    for channel in msg.channels:
        if channel.name == name:
            return list(channel.values)
    raise ValueError(f"missing channel {name}")


def set_channel(msg, name: str, values: list[float]) -> None:
    for channel in msg.channels:
        if channel.name == name:
            channel.values = [float(value) for value in values]
            return
    raise ValueError(f"missing channel {name}")


def deserialize(raw_message):
    _msg_type, serialized, _md5sum, _position, pytype = raw_message
    msg = pytype()
    msg.deserialize(serialized)
    return msg


def rewrite_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    source_codes: set[int],
    quality: float,
    min_quality: float,
) -> dict[str, object]:
    if not input_bag.is_file():
        raise FileNotFoundError(input_bag)
    if input_bag.resolve() == output_bag.resolve():
        raise ValueError("input and output bag must differ")
    if output_bag.exists():
        raise FileExistsError(output_bag)
    if not source_codes:
        raise ValueError("at least one source code is required")

    q = max(float(min_quality), min(1.0, float(quality)))
    sigma = 1.0 / math.sqrt(q)
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    partial = output_bag.with_name(f"{output_bag.name}.partial.{os.getpid()}")
    if partial.exists():
        raise FileExistsError(partial)

    started = time.monotonic()
    total_messages = 0
    raw_copied_messages = 0
    feature_frames = 0
    selected_observations = 0
    changed_observations = 0
    untouched_observations = 0
    source_counts: Counter[int] = Counter()

    try:
        with rosbag.Bag(str(input_bag), "r") as source:
            with rosbag.Bag(
                str(partial),
                "w",
                compression=source.compression,
                chunk_threshold=source.chunk_threshold,
            ) as target:
                messages = source.read_messages(raw=True, return_connection_header=True)
                for item in messages:
                    total_messages += 1
                    topic = item.topic
                    raw_message = item.message
                    stamp = item.timestamp
                    header = item.connection_header
                    if topic != feature_topic:
                        target.write(
                            topic,
                            raw_message,
                            stamp,
                            raw=True,
                            connection_header=header,
                        )
                        raw_copied_messages += 1
                        continue

                    feature_frames += 1
                    msg = deserialize(raw_message)
                    sources = [int(round(value)) for value in channel_values(msg, "source_code")]
                    quality_values = channel_values(msg, "quality")
                    sigma_values = channel_values(msg, "sigma")
                    if not (len(sources) == len(quality_values) == len(sigma_values) == len(msg.points)):
                        raise ValueError(
                            f"feature channel length mismatch at frame {feature_frames - 1}"
                        )
                    for index, source_code in enumerate(sources):
                        source_counts[source_code] += 1
                        if source_code in source_codes:
                            selected_observations += 1
                            if quality_values[index] != q or sigma_values[index] != sigma:
                                changed_observations += 1
                            quality_values[index] = q
                            sigma_values[index] = sigma
                        else:
                            untouched_observations += 1
                    set_channel(msg, "quality", quality_values)
                    set_channel(msg, "sigma", sigma_values)
                    target.write(topic, msg, stamp, connection_header=header)
        os.replace(partial, output_bag)
    except Exception:
        if partial.exists():
            partial.unlink()
        raise

    return {
        "schema_version": "aqua-fe-quality-partition-rewrite-v1",
        "input_bag": str(input_bag),
        "input_sha256": sha256(input_bag),
        "output_bag": str(output_bag),
        "output_sha256": sha256(output_bag),
        "feature_topic": feature_topic,
        "source_codes": sorted(source_codes),
        "quality": q,
        "sigma": sigma,
        "total_messages": total_messages,
        "raw_copied_messages": raw_copied_messages,
        "feature_frames": feature_frames,
        "selected_observations": selected_observations,
        "changed_observations": changed_observations,
        "untouched_observations": untouched_observations,
        "source_counts": {str(key): value for key, value in sorted(source_counts.items())},
        "elapsed_s": time.monotonic() - started,
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
    stats = rewrite_bag(
        input_bag=args.input_bag,
        output_bag=args.output_bag,
        feature_topic=str(args.feature_topic),
        source_codes=set(args.source_code),
        quality=float(args.quality),
        min_quality=float(args.min_quality),
    )
    write_json(args.stats_json, stats)
    print(
        "QUALITY_PARTITION_REWRITE "
        f"selected={stats['selected_observations']} changed={stats['changed_observations']} "
        f"raw_copied={stats['raw_copied_messages']} elapsed_s={stats['elapsed_s']:.3f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
