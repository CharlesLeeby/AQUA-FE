#!/usr/bin/env python3
"""Summarize exported backend q/sigma channels in VINS feature bags."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import rosbag


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute q distribution stats for exported VINS external feature bags."
    )
    parser.add_argument(
        "--bag",
        action="append",
        required=True,
        help="Feature bag path, or label=path. May be repeated.",
    )
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--output-csv", default=None)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    rows = [
        summarize_bag(label, path, args.feature_topic)
        for label, path in (_parse_bag_spec(item) for item in args.bag)
    ]
    if args.output_csv:
        write_csv(Path(args.output_csv), rows)
    if args.output_md:
        write_markdown(Path(args.output_md), rows)
    print_markdown(rows)
    return 0


def _parse_bag_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        label, value = spec.split("=", 1)
        return label.strip(), Path(value.strip())
    path = Path(spec)
    return path.parent.name or path.stem, path


def summarize_bag(label: str, path: Path, feature_topic: str) -> dict[str, float | int | str]:
    q_values: list[float] = []
    sigma_values: list[float] = []
    sigma_errors: list[float] = []
    points_per_frame: list[int] = []
    feature_frames = 0
    empty_feature_frames = 0

    with rosbag.Bag(str(path), "r") as bag:
        for topic, msg, _stamp in bag.read_messages(topics=[feature_topic]):
            feature_frames += 1
            count = int(len(msg.points))
            points_per_frame.append(count)
            if count == 0:
                empty_feature_frames += 1
            channels = {channel.name: channel for channel in getattr(msg, "channels", [])}
            quality = channels.get("quality")
            if quality is None:
                raise ValueError(f"{path} has no quality channel on {feature_topic}")
            q = np.asarray(quality.values, dtype=np.float32)
            if len(q) != count:
                raise ValueError(
                    f"{path} quality channel length {len(q)} does not match point count {count}"
                )
            q_values.extend(float(item) for item in q)
            sigma = channels.get("sigma")
            if sigma is not None:
                sigma_arr = np.asarray(sigma.values, dtype=np.float32)
                if len(sigma_arr) != count:
                    raise ValueError(
                        f"{path} sigma channel length {len(sigma_arr)} does not match point count {count}"
                    )
                sigma_values.extend(float(item) for item in sigma_arr)
                expected = 1.0 / np.sqrt(np.maximum(0.05, q))
                sigma_errors.extend(float(item) for item in np.abs(sigma_arr - expected))

    q_arr = np.asarray(q_values, dtype=np.float64)
    sigma_arr = np.asarray(sigma_values, dtype=np.float64)
    sigma_err_arr = np.asarray(sigma_errors, dtype=np.float64)
    count_arr = np.asarray(points_per_frame, dtype=np.float64)
    return {
        "label": label,
        "bag": str(path),
        "feature_frames": feature_frames,
        "empty_feature_frames": empty_feature_frames,
        "feature_points": int(len(q_arr)),
        "points_per_frame_median": _stat(count_arr, np.median),
        "points_per_frame_mean": _stat(count_arr, np.mean),
        "q_min": _stat(q_arr, np.min),
        "q_p10": _stat(q_arr, lambda arr: np.percentile(arr, 10)),
        "q_median": _stat(q_arr, np.median),
        "q_mean": _stat(q_arr, np.mean),
        "q_p90": _stat(q_arr, lambda arr: np.percentile(arr, 90)),
        "q_max": _stat(q_arr, np.max),
        "sigma_median": _stat(sigma_arr, np.median),
        "sigma_mean": _stat(sigma_arr, np.mean),
        "sigma_max_abs_error": _stat(sigma_err_arr, np.max),
    }


def _stat(values: np.ndarray, fn) -> float:
    if values.size == 0:
        return float("nan")
    return float(fn(values))


def write_csv(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, float | int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_markdown_table(rows), encoding="utf-8")


def print_markdown(rows: list[dict[str, float | int | str]]) -> None:
    print(_markdown_table(rows))


def _markdown_table(rows: list[dict[str, float | int | str]]) -> str:
    headers = [
        "label",
        "feature_frames",
        "feature_points",
        "points_per_frame_median",
        "q_min",
        "q_p10",
        "q_median",
        "q_mean",
        "q_p90",
        "q_max",
        "sigma_median",
        "sigma_max_abs_error",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_fmt(row[key]) for key in headers) + " |")
    return "\n".join(lines)


def _fmt(value: float | int | str) -> str:
    if isinstance(value, float):
        if np.isnan(value):
            return "nan"
        return f"{value:.6f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
