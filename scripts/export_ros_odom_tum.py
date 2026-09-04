#!/usr/bin/env python3
"""Export a nav_msgs/Odometry topic from a ROS bag to TUM format."""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", required=True)
    parser.add_argument("--topic", default="/uvvid/local_odom_gt")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with rosbag.Bag(str(Path(args.bag).resolve()), "r") as bag, output.open(
        "w", encoding="ascii"
    ) as stream:
        for topic, msg, record_stamp in bag.read_messages(topics=[args.topic]):
            stamp = msg.header.stamp if msg.header.stamp.to_sec() > 0.0 else record_stamp
            position = msg.pose.pose.position
            orientation = msg.pose.pose.orientation
            values = (
                stamp.to_sec(),
                position.x,
                position.y,
                position.z,
                orientation.x,
                orientation.y,
                orientation.z,
                orientation.w,
            )
            stream.write(" ".join(f"{value:.12f}" for value in values) + "\n")
            rows += 1
    if rows == 0:
        raise SystemExit(f"no messages on {args.topic}")
    print(f"wrote {rows} TUM rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
