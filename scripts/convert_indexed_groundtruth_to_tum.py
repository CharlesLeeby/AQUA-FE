#!/usr/bin/env python3
"""Map frame-indexed ground truth to image-header TUM timestamps."""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", required=True)
    parser.add_argument("--image-topic", required=True)
    parser.add_argument("--indexed-groundtruth", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bag_path = Path(args.bag).resolve()
    gt_path = Path(args.indexed_groundtruth).resolve()
    output_path = Path(args.output).resolve()
    if not bag_path.is_file():
        raise SystemExit(f"missing bag: {bag_path}")
    if not gt_path.is_file():
        raise SystemExit(f"missing indexed ground truth: {gt_path}")

    image_stamps: list[int] = []
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _topic, msg, record_stamp in bag.read_messages(topics=[args.image_topic]):
            stamp = getattr(getattr(msg, "header", None), "stamp", None)
            stamp_ns = stamp.to_nsec() if stamp is not None else 0
            image_stamps.append(stamp_ns if stamp_ns > 0 else record_stamp.to_nsec())

    if not image_stamps:
        raise SystemExit(f"no messages on {args.image_topic}")
    if any(right <= left for left, right in zip(image_stamps, image_stamps[1:])):
        raise SystemExit("image timestamps are not strictly increasing")

    rows: list[str] = []
    used_indices: set[int] = set()
    for line_number, raw_line in enumerate(gt_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) < 8:
            raise SystemExit(f"ground-truth row {line_number} has fewer than 8 fields")
        try:
            frame_value = float(fields[0])
        except ValueError as exc:
            raise SystemExit(f"invalid frame index on row {line_number}: {fields[0]}") from exc
        frame_index = int(round(frame_value))
        if abs(frame_value - frame_index) > 1e-6:
            raise SystemExit(f"non-integral frame index on row {line_number}: {frame_value}")
        if not 0 <= frame_index < len(image_stamps):
            raise SystemExit(
                f"frame index {frame_index} outside image range [0, {len(image_stamps) - 1}]"
            )
        if frame_index in used_indices:
            raise SystemExit(f"duplicate ground-truth frame index: {frame_index}")
        used_indices.add(frame_index)
        rows.append(f"{image_stamps[frame_index] * 1e-9:.9f} {' '.join(fields[1:8])}\n")

    if not rows:
        raise SystemExit("no ground-truth rows converted")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(rows), encoding="ascii")
    print(
        f"wrote {len(rows)} poses from {len(image_stamps)} images to {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
