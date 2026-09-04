#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import rosbag


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--mode", choices=["raw", "const", "blend", "floor"], required=True)
    parser.add_argument("--alpha", type=float, default=0.85, help="q' = alpha + (1-alpha)q for blend mode")
    parser.add_argument("--floor", type=float, default=0.8, help="minimum q for floor mode")
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    args = parser.parse_args()

    input_path = Path(args.input_bag)
    output_path = Path(args.output_bag)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pointcloud_count = 0
    point_count = 0
    q_values = []
    with rosbag.Bag(str(input_path), "r") as in_bag, rosbag.Bag(str(output_path), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == args.feature_topic and hasattr(msg, "channels"):
                q_idx = _channel_index(msg, "quality")
                sigma_idx = _channel_index(msg, "sigma")
                if q_idx is not None:
                    old_q = np.asarray(msg.channels[q_idx].values, dtype=np.float32)
                    new_q = _map_quality(old_q, args.mode, args.alpha, args.floor)
                    msg.channels[q_idx].values = [float(x) for x in new_q]
                    q_values.extend(float(x) for x in new_q)
                    point_count += int(len(new_q))
                    if sigma_idx is not None:
                        sigma = 1.0 / np.sqrt(np.maximum(0.05, new_q))
                        msg.channels[sigma_idx].values = [float(x) for x in sigma]
                    pointcloud_count += 1
            out_bag.write(topic, msg, stamp)

    q_arr = np.asarray(q_values, dtype=np.float32)
    print(f"wrote {output_path}")
    print(f"pointclouds={pointcloud_count} points={point_count}")
    if len(q_arr):
        print(
            "q_min={:.6f} q_median={:.6f} q_mean={:.6f} q_max={:.6f}".format(
                float(np.min(q_arr)), float(np.median(q_arr)), float(np.mean(q_arr)), float(np.max(q_arr))
            )
        )
    return 0


def _channel_index(msg, name: str) -> int | None:
    for idx, channel in enumerate(msg.channels):
        if channel.name == name:
            return idx
    return None


def _map_quality(q: np.ndarray, mode: str, alpha: float, floor: float) -> np.ndarray:
    q = np.clip(q.astype(np.float32), 0.05, 1.0)
    if mode == "raw":
        return q
    if mode == "const":
        return np.ones_like(q, dtype=np.float32)
    if mode == "blend":
        a = float(np.clip(alpha, 0.0, 1.0))
        return np.clip(a + (1.0 - a) * q, 0.05, 1.0).astype(np.float32)
    if mode == "floor":
        return np.clip(np.maximum(q, float(floor)), 0.05, 1.0).astype(np.float32)
    raise ValueError(mode)


if __name__ == "__main__":
    raise SystemExit(main())
