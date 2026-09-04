#!/usr/bin/env python3
"""Verify that pool imgshift bags preserve pixels and apply one timestamp shift.

The audit reads bags only.  It compares every image payload and records the
pairwise header/bag timestamp deltas without materializing image files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from itertools import zip_longest
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bag-dir", default="/mnt/data/Dataset_pool/ros1_bags")
    parser.add_argument("--sequences", nargs="+", default=["171342", "171944", "172529"])
    parser.add_argument("--suffix", default="m085375")
    parser.add_argument("--image-topic", default="/cam0/image_raw")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for sequence in args.sequences:
        bag_dir = Path(args.bag_dir)
        raw_path = bag_dir / f"full_slam_20260608_{sequence}_cam_imu_dvl.bag"
        shifted_path = bag_dir / f"full_slam_20260608_{sequence}_cam_imu_dvl_imgshift_{args.suffix}.bag"
        raw_hash = hashlib.sha256()
        shifted_hash = hashlib.sha256()
        header_deltas: list[float] = []
        bag_deltas: list[float] = []
        payload_mismatches = 0
        metadata_mismatches = 0
        count = 0
        with rosbag.Bag(raw_path, "r") as raw_bag, rosbag.Bag(shifted_path, "r") as shifted_bag:
            raw_messages = raw_bag.read_messages(topics=[args.image_topic])
            shifted_messages = shifted_bag.read_messages(topics=[args.image_topic])
            for raw_item, shifted_item in zip_longest(raw_messages, shifted_messages):
                if raw_item is None or shifted_item is None:
                    metadata_mismatches += 1
                    continue
                _raw_topic, raw_message, raw_stamp = raw_item
                _shift_topic, shifted_message, shifted_stamp = shifted_item
                raw_payload = bytes(raw_message.data)
                shifted_payload = bytes(shifted_message.data)
                raw_hash.update(raw_payload)
                shifted_hash.update(shifted_payload)
                if raw_payload != shifted_payload:
                    payload_mismatches += 1
                raw_meta = (raw_message.width, raw_message.height, raw_message.step, raw_message.encoding)
                shifted_meta = (
                    shifted_message.width,
                    shifted_message.height,
                    shifted_message.step,
                    shifted_message.encoding,
                )
                if raw_meta != shifted_meta:
                    metadata_mismatches += 1
                header_deltas.append(
                    shifted_message.header.stamp.to_sec() - raw_message.header.stamp.to_sec()
                )
                bag_deltas.append(shifted_stamp.to_sec() - raw_stamp.to_sec())
                count += 1
        rows.append(
            {
                "sequence": sequence,
                "raw_bag": str(raw_path),
                "shifted_bag": str(shifted_path),
                "image_count": count,
                "payload_mismatch_count": payload_mismatches,
                "metadata_mismatch_count": metadata_mismatches,
                "payload_stream_sha256_raw": raw_hash.hexdigest(),
                "payload_stream_sha256_shifted": shifted_hash.hexdigest(),
                "payload_streams_identical": int(raw_hash.digest() == shifted_hash.digest()),
                "header_shift_median_s": statistics.median(header_deltas),
                "header_shift_min_s": min(header_deltas),
                "header_shift_max_s": max(header_deltas),
                "bag_record_time_shift_median_s": statistics.median(bag_deltas),
                "bag_record_time_shift_min_s": min(bag_deltas),
                "bag_record_time_shift_max_s": max(bag_deltas),
            }
        )
        print(json.dumps(rows[-1], sort_keys=True))
    output_csv = output_dir / "imgshift_audit.csv"
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "imgshift_audit.json").write_text(
        json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
