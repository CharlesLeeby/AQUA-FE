#!/usr/bin/env python3
"""Wait until selected ROS topics have subscribers.

`rosbag play --wait-for-subscribers` waits for every advertised topic in the
bag, which is unsuitable for evaluation bags that also contain ground truth.
This helper waits only for the topics that VINS actually consumes.
"""

from __future__ import annotations

import argparse
import sys
import time

import rosgraph


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("topics", nargs="+")
    parser.add_argument("--min-subscribers", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--poll", type=float, default=0.2)
    args = parser.parse_args()

    master = rosgraph.Master("/wait_for_ros_subscribers")
    deadline = time.time() + max(0.0, float(args.timeout))
    min_subs = max(1, int(args.min_subscribers))
    topics = list(dict.fromkeys(args.topics))
    last_counts: dict[str, int] = {topic: 0 for topic in topics}

    while True:
        try:
            _publishers, subscribers, _services = master.getSystemState()
        except Exception as exc:  # pragma: no cover - depends on live ROS master.
            print(f"waiting for ROS master: {exc}", file=sys.stderr)
            subscribers = []

        sub_counts = {topic: len(nodes) for topic, nodes in subscribers}
        last_counts = {topic: int(sub_counts.get(topic, 0)) for topic in topics}
        if all(count >= min_subs for count in last_counts.values()):
            counts = " ".join(f"{topic}={count}" for topic, count in last_counts.items())
            print(f"subscriber wait ok: {counts}")
            return 0
        if time.time() >= deadline:
            counts = " ".join(f"{topic}={count}" for topic, count in last_counts.items())
            print(f"subscriber wait timeout: {counts}", file=sys.stderr)
            return 1
        time.sleep(max(0.05, float(args.poll)))


if __name__ == "__main__":
    raise SystemExit(main())
