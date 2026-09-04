#!/usr/bin/env python3
"""Keep every Nth external-feature message while preserving IMU/GT topics."""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bag", required=True, type=Path)
    parser.add_argument("--output-bag", required=True, type=Path)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--stride", required=True, type=int)
    parser.add_argument("--offset", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.stride < 1:
        raise SystemExit("--stride must be positive")
    offset = args.offset % args.stride
    args.output_bag.parent.mkdir(parents=True, exist_ok=True)
    seen = kept = copied = 0
    with rosbag.Bag(str(args.input_bag), "r") as source, rosbag.Bag(
        str(args.output_bag), "w", compression=rosbag.Compression.LZ4
    ) as target:
        for topic, message, stamp in source.read_messages():
            if topic == args.feature_topic:
                keep = seen % args.stride == offset
                seen += 1
                if not keep:
                    continue
                kept += 1
            else:
                copied += 1
            target.write(topic, message, stamp)
    print(f"feature_seen={seen}")
    print(f"feature_kept={kept}")
    print(f"nonfeature_copied={copied}")
    print(f"output_bag={args.output_bag.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
