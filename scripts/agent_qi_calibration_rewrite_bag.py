#!/usr/bin/env python3
"""Rewrite exported VINS feature bags with calibrated backend q schedules."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Callable

import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite the quality/sigma channels in a VINS external-feature bag."
    )
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--schedule", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--stats-csv", required=True)
    parser.add_argument("--min-q", type=float, default=0.05)
    args = parser.parse_args()

    schedule_name, schedule_fn = parse_schedule(args.schedule)
    stats = rewrite_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        feature_topic=args.feature_topic,
        schedule_name=schedule_name,
        schedule_fn=schedule_fn,
        min_q=float(args.min_q),
    )
    stats["schedule"] = schedule_name
    stats["input_bag"] = str(Path(args.input_bag))
    stats["output_bag"] = str(Path(args.output_bag))
    write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(f"schedule={schedule_name}")
    print(f"feature_points={stats['feature_points']}")
    print(f"q_backend_median={stats['backend_q_median']:.6f}")
    return 0


def parse_schedule(spec: str) -> tuple[str, Callable[[np.ndarray], np.ndarray]]:
    token = spec.strip().lower().replace("_", "").replace("-", "")
    if token in {"constq", "const", "one", "ones", "q1"}:
        return "constq", lambda raw_q: np.ones_like(raw_q, dtype=np.float32)
    if token in {"raw", "rawq", "q"}:
        return "raw", lambda raw_q: raw_q.astype(np.float32, copy=True)
    if token.startswith("blend"):
        alpha = float(token[len("blend") :])
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"blend alpha must be in [0, 1], got {alpha}")
        label = f"blend{alpha:g}"
        return label, lambda raw_q: (alpha + (1.0 - alpha) * raw_q).astype(np.float32)
    if token.startswith("alpha"):
        alpha = float(token[len("alpha") :])
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"blend alpha must be in [0, 1], got {alpha}")
        label = f"blend{alpha:g}"
        return label, lambda raw_q: (alpha + (1.0 - alpha) * raw_q).astype(np.float32)
    if token.startswith("clamp"):
        floor = float(token[len("clamp") :])
        if not 0.0 <= floor <= 1.0:
            raise ValueError(f"clamp floor must be in [0, 1], got {floor}")
        label = f"clamp{floor:g}"
        return label, lambda raw_q: np.maximum(raw_q, floor).astype(np.float32)
    raise ValueError(
        "unsupported schedule; use constq, raw, blend0.5/blend0.7/blend0.85, "
        "or clamp0.6/clamp0.8"
    )


def rewrite_bag(
    input_bag: Path,
    output_bag: Path,
    feature_topic: str,
    schedule_name: str,
    schedule_fn: Callable[[np.ndarray], np.ndarray],
    min_q: float,
) -> dict[str, float | int | str]:
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    raw_values: list[float] = []
    backend_values: list[float] = []
    sigma_values: list[float] = []
    points_per_frame: list[int] = []
    feature_frames = 0
    empty_feature_frames = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                channel_map = {channel.name: channel for channel in msg.channels}
                quality_channel = channel_map.get("quality")
                if quality_channel is None:
                    raise ValueError(f"{input_bag} has no quality channel on {feature_topic}")
                raw_q = np.asarray(quality_channel.values, dtype=np.float32)
                if len(raw_q) != len(msg.points):
                    raise ValueError(
                        f"quality channel length {len(raw_q)} does not match point count "
                        f"{len(msg.points)} on {feature_topic}"
                    )
                raw_q = np.clip(raw_q, min_q, 1.0)
                backend_q = np.clip(schedule_fn(raw_q), min_q, 1.0).astype(np.float32)
                sigma = np.asarray(
                    [1.0 / math.sqrt(max(min_q, float(item))) for item in backend_q],
                    dtype=np.float32,
                )

                quality_channel.values = [float(item) for item in backend_q]
                sigma_channel = channel_map.get("sigma")
                if sigma_channel is None:
                    sigma_channel = ChannelFloat32(name="sigma")
                    msg.channels.append(sigma_channel)
                sigma_channel.values = [float(item) for item in sigma]

                raw_values.extend(float(item) for item in raw_q)
                backend_values.extend(float(item) for item in backend_q)
                sigma_values.extend(float(item) for item in sigma)
                points_per_frame.append(len(msg.points))
                if len(msg.points) == 0:
                    empty_feature_frames += 1
            out_bag.write(topic, msg, stamp)

    raw_arr = np.asarray(raw_values, dtype=np.float64)
    backend_arr = np.asarray(backend_values, dtype=np.float64)
    sigma_arr = np.asarray(sigma_values, dtype=np.float64)
    count_arr = np.asarray(points_per_frame, dtype=np.float64)
    return {
        "schedule": schedule_name,
        "feature_frames": feature_frames,
        "empty_feature_frames": empty_feature_frames,
        "feature_points": int(len(backend_arr)),
        "points_per_frame_median": finite_stat(count_arr, np.median),
        "points_per_frame_mean": finite_stat(count_arr, np.mean),
        "raw_q_min": finite_stat(raw_arr, np.min),
        "raw_q_p10": finite_stat(raw_arr, lambda arr: np.percentile(arr, 10)),
        "raw_q_median": finite_stat(raw_arr, np.median),
        "raw_q_mean": finite_stat(raw_arr, np.mean),
        "raw_q_p90": finite_stat(raw_arr, lambda arr: np.percentile(arr, 90)),
        "raw_q_max": finite_stat(raw_arr, np.max),
        "backend_q_min": finite_stat(backend_arr, np.min),
        "backend_q_p10": finite_stat(backend_arr, lambda arr: np.percentile(arr, 10)),
        "backend_q_median": finite_stat(backend_arr, np.median),
        "backend_q_mean": finite_stat(backend_arr, np.mean),
        "backend_q_p90": finite_stat(backend_arr, lambda arr: np.percentile(arr, 90)),
        "backend_q_max": finite_stat(backend_arr, np.max),
        "sigma_median": finite_stat(sigma_arr, np.median),
        "sigma_mean": finite_stat(sigma_arr, np.mean),
    }


def finite_stat(values: np.ndarray, fn: Callable[[np.ndarray], float]) -> float:
    if values.size == 0:
        return float("nan")
    return float(fn(values))


def write_stats(path: Path, row: dict[str, float | int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
