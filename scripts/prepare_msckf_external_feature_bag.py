#!/usr/bin/env python3
"""Adapt VINS-Fusion feature PointCloud messages for MSCKF-DVIO.

VINS-Fusion stores normalized image coordinates in ``points`` and pixel
coordinates in the ``p_u``/``p_v`` channels. MSCKF-DVIO's external feature
callback expects pixel coordinates in ``points`` and the feature ID in the
first channel. This adapter performs only that representation change.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
from copy import deepcopy
from pathlib import Path
from typing import Iterable

import rosbag


FLOAT32_EXACT_INTEGER_LIMIT = 1 << 24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--audit-csv", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--image-width", type=int, required=True)
    parser.add_argument("--image-height", type=int, required=True)
    return parser.parse_args()


def channel_map(msg: object) -> dict[str, list[float]]:
    channels: dict[str, list[float]] = {}
    for channel in msg.channels:
        if channel.name in channels:
            raise ValueError(f"duplicate feature channel: {channel.name}")
        channels[channel.name] = channel.values
    return channels


def _hash_observations(
    stamp_ns: int,
    ids: Iterable[int],
    xs: Iterable[float],
    ys: Iterable[float],
) -> str:
    digest = hashlib.sha256()
    digest.update(struct.pack("<q", stamp_ns))
    for feature_id, x, y in zip(ids, xs, ys):
        digest.update(struct.pack("<Qdd", feature_id, x, y))
    return digest.hexdigest()


def adapt_feature_message(
    msg: object,
    *,
    image_width: int,
    image_height: int,
) -> tuple[object, dict[str, object]]:
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image dimensions must be positive")

    count = len(msg.points)
    channels = channel_map(msg)
    required = {"id", "p_u", "p_v"}
    missing = required.difference(channels)
    if missing:
        raise ValueError(f"missing required feature channels: {sorted(missing)}")

    for name, values in channels.items():
        if len(values) != count:
            raise ValueError(
                f"channel {name} has {len(values)} values for {count} points"
            )

    feature_ids: list[int] = []
    pixel_x: list[float] = []
    pixel_y: list[float] = []
    normalized_x: list[float] = []
    normalized_y: list[float] = []
    for index, point in enumerate(msg.points):
        raw_id = float(channels["id"][index])
        if not math.isfinite(raw_id) or not raw_id.is_integer():
            raise ValueError(f"feature id is not a finite integer at index {index}")
        feature_id = int(raw_id)
        if feature_id < 0 or feature_id >= FLOAT32_EXACT_INTEGER_LIMIT:
            raise ValueError(
                f"feature id {feature_id} cannot be represented exactly by ChannelFloat32"
            )

        u = float(channels["p_u"][index])
        v = float(channels["p_v"][index])
        if not math.isfinite(u) or not math.isfinite(v):
            raise ValueError(f"non-finite pixel coordinate at index {index}")
        if not 0.0 <= u < image_width or not 0.0 <= v < image_height:
            raise ValueError(
                f"pixel coordinate ({u}, {v}) is outside {image_width}x{image_height}"
            )
        if not math.isfinite(point.x) or not math.isfinite(point.y):
            raise ValueError(f"non-finite normalized coordinate at index {index}")

        feature_ids.append(feature_id)
        pixel_x.append(u)
        pixel_y.append(v)
        normalized_x.append(float(point.x))
        normalized_y.append(float(point.y))

    output = deepcopy(msg)
    id_index = next(
        index for index, channel in enumerate(output.channels) if channel.name == "id"
    )
    if id_index != 0:
        output.channels.insert(0, output.channels.pop(id_index))
    for index, point in enumerate(output.points):
        point.x = pixel_x[index]
        point.y = pixel_y[index]
        point.z = 1.0

    stamp_ns = msg.header.stamp.to_nsec()
    source_hash = _hash_observations(
        stamp_ns, feature_ids, normalized_x, normalized_y
    )
    contract_hash = _hash_observations(stamp_ns, feature_ids, pixel_x, pixel_y)
    return output, {
        "stamp_ns": stamp_ns,
        "count": count,
        "min_id": min(feature_ids) if feature_ids else None,
        "max_id": max(feature_ids) if feature_ids else None,
        "source_normalized_sha256": source_hash,
        "msckf_contract_sha256": contract_hash,
    }


def main() -> int:
    args = parse_args()
    input_bag = Path(args.input_bag).resolve()
    output_bag = Path(args.output_bag).resolve()
    audit_csv = Path(args.audit_csv).resolve()
    summary_json = Path(args.summary_json).resolve()
    if not input_bag.is_file():
        raise SystemExit(f"missing input bag: {input_bag}")
    if input_bag == output_bag:
        raise SystemExit("input and output bag paths must differ")

    for path in (output_bag, audit_csv, summary_json):
        path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    topic_counts: dict[str, int] = {}
    record_stamp_mismatches = 0
    with rosbag.Bag(str(input_bag), "r") as source, rosbag.Bag(
        str(output_bag), "w"
    ) as output:
        for topic, msg, record_stamp in source.read_messages():
            topic_counts[topic] = topic_counts.get(topic, 0) + 1
            if topic == args.feature_topic:
                msg, row = adapt_feature_message(
                    msg,
                    image_width=args.image_width,
                    image_height=args.image_height,
                )
                row["frame_index"] = len(rows)
                row["record_stamp_ns"] = record_stamp.to_nsec()
                if row["stamp_ns"] != row["record_stamp_ns"]:
                    record_stamp_mismatches += 1
                rows.append(row)
            output.write(topic, msg, record_stamp)

    if not rows:
        output_bag.unlink(missing_ok=True)
        raise SystemExit(f"no feature messages found on {args.feature_topic}")

    fieldnames = [
        "frame_index",
        "stamp_ns",
        "record_stamp_ns",
        "count",
        "min_id",
        "max_id",
        "source_normalized_sha256",
        "msckf_contract_sha256",
    ]
    with audit_csv.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update(str(row["msckf_contract_sha256"]).encode("ascii"))
    summary = {
        "input_bag": str(input_bag),
        "output_bag": str(output_bag),
        "feature_topic": args.feature_topic,
        "image_width": args.image_width,
        "image_height": args.image_height,
        "feature_frames": len(rows),
        "feature_observations": sum(int(row["count"]) for row in rows),
        "record_stamp_mismatches": record_stamp_mismatches,
        "topic_counts": dict(sorted(topic_counts.items())),
        "contract_aggregate_sha256": aggregate.hexdigest(),
        "audit_csv": str(audit_csv),
    }
    summary_json.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="ascii"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
