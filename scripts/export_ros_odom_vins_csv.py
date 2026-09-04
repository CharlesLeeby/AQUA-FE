#!/usr/bin/env python3
"""Export nav_msgs/Odometry as the timestamp-nanoseconds CSV used by evaluators."""

from __future__ import annotations

import argparse
from pathlib import Path

import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bag", required=True)
    parser.add_argument("--topic", default="/odom")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    bag_path = Path(args.bag).resolve()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    previous_stamp_ns = -1
    with rosbag.Bag(str(bag_path), "r") as bag, output.open(
        "w", encoding="ascii"
    ) as stream:
        for _, msg, record_stamp in bag.read_messages(topics=[args.topic]):
            stamp = msg.header.stamp if msg.header.stamp.to_nsec() > 0 else record_stamp
            stamp_ns = stamp.to_nsec()
            if stamp_ns <= previous_stamp_ns:
                continue
            previous_stamp_ns = stamp_ns
            position = msg.pose.pose.position
            orientation = msg.pose.pose.orientation
            velocity = msg.twist.twist.linear
            values = (
                stamp_ns,
                position.x,
                position.y,
                position.z,
                orientation.w,
                orientation.x,
                orientation.y,
                orientation.z,
                velocity.x,
                velocity.y,
                velocity.z,
            )
            stream.write(
                str(values[0])
                + ","
                + ",".join(f"{value:.12f}" for value in values[1:])
                + ",\n"
            )
            rows += 1
    if rows == 0:
        output.unlink(missing_ok=True)
        raise SystemExit(f"no messages on {args.topic}")
    print(f"wrote {rows} odometry rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
