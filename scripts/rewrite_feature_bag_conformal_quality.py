#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import rosbag
from sensor_msgs.msg import ChannelFloat32

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from uw_frontend.quality.conformal_calibrator import MondrianConformalCalibrator
from uw_frontend.quality.feature_confidence import quality_to_sigma


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite a VINS feature bag with conformal backend quality/sigma."
    )
    parser.add_argument("--input-bag", required=True)
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--conformal-json", required=True)
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument(
        "--bucket-mode",
        choices=["global", "source_code"],
        default="global",
        help="How to assign Mondrian buckets for bag-only rewriting.",
    )
    parser.add_argument("--min-quality", type=float, default=0.05)
    parser.add_argument(
        "--backend-blend-alpha",
        type=float,
        default=None,
        help=(
            "Optional tempered backend mapping: q_out = alpha + (1-alpha) * "
            "q_conformal. This preserves conformal ordering while preventing "
            "overly weak VINS visual constraints."
        ),
    )
    parser.add_argument("--stats-csv", default=None)
    args = parser.parse_args()

    conformal = MondrianConformalCalibrator.from_json(args.conformal_json)
    stats = rewrite_bag(
        input_bag=Path(args.input_bag),
        output_bag=Path(args.output_bag),
        conformal=conformal,
        feature_topic=str(args.feature_topic),
        bucket_mode=str(args.bucket_mode),
        min_quality=float(args.min_quality),
        backend_blend_alpha=args.backend_blend_alpha,
    )
    stats["input_bag"] = str(Path(args.input_bag))
    stats["output_bag"] = str(Path(args.output_bag))
    stats["conformal_json"] = str(Path(args.conformal_json))
    if args.stats_csv:
        _write_stats(Path(args.stats_csv), stats)
    print(f"wrote {args.output_bag}")
    print(f"points={stats['feature_points']} q_backend_median={stats['backend_q_median']:.6f}")
    return 0


def rewrite_bag(
    *,
    input_bag: Path,
    output_bag: Path,
    conformal: MondrianConformalCalibrator,
    feature_topic: str,
    bucket_mode: str,
    min_quality: float,
    backend_blend_alpha: float | None,
) -> dict[str, float | int | str]:
    if backend_blend_alpha is not None and not 0.0 <= float(backend_blend_alpha) <= 1.0:
        raise ValueError("--backend-blend-alpha must be in [0, 1]")
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    raw_values: list[float] = []
    conformal_values: list[float] = []
    backend_values: list[float] = []
    sigma_values: list[float] = []
    frame_counts: list[int] = []
    feature_frames = 0
    empty_feature_frames = 0

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        for topic, msg, stamp in in_bag.read_messages():
            if topic == feature_topic:
                feature_frames += 1
                n = len(msg.points)
                channels = {channel.name: channel for channel in msg.channels}
                quality_channel = channels.get("quality")
                if quality_channel is None:
                    raise ValueError(f"{input_bag} has no quality channel on {feature_topic}")
                q_hat = np.clip(np.asarray(quality_channel.values, dtype=np.float32), min_quality, 1.0)
                if len(q_hat) != n:
                    raise ValueError(
                        f"quality channel length {len(q_hat)} does not match point count {n}"
                    )
                buckets = _bag_buckets(channels, n, bucket_mode)
                q_conformal = conformal.backend_quality(q_hat, buckets, min_quality=min_quality)
                q_backend = _temper_quality(q_conformal, backend_blend_alpha, min_quality)
                sigma = quality_to_sigma(q_backend)
                quality_channel.values = [float(item) for item in q_backend]
                sigma_channel = channels.get("sigma")
                if sigma_channel is None:
                    sigma_channel = ChannelFloat32(name="sigma")
                    msg.channels.append(sigma_channel)
                sigma_channel.values = [float(item) for item in sigma]

                raw_values.extend(float(item) for item in q_hat)
                conformal_values.extend(float(item) for item in q_conformal)
                backend_values.extend(float(item) for item in q_backend)
                sigma_values.extend(float(item) for item in sigma)
                frame_counts.append(n)
                if n == 0:
                    empty_feature_frames += 1
            out_bag.write(topic, msg, stamp)

    raw = np.asarray(raw_values, dtype=np.float64)
    conformal_arr = np.asarray(conformal_values, dtype=np.float64)
    backend = np.asarray(backend_values, dtype=np.float64)
    sigma = np.asarray(sigma_values, dtype=np.float64)
    counts = np.asarray(frame_counts, dtype=np.float64)
    return {
        "feature_frames": int(feature_frames),
        "empty_feature_frames": int(empty_feature_frames),
        "feature_points": int(len(backend)),
        "points_per_frame_median": _finite_stat(counts, np.median),
        "raw_q_median": _finite_stat(raw, np.median),
        "raw_q_mean": _finite_stat(raw, np.mean),
        "conformal_q_min": _finite_stat(conformal_arr, np.min),
        "conformal_q_median": _finite_stat(conformal_arr, np.median),
        "conformal_q_mean": _finite_stat(conformal_arr, np.mean),
        "backend_q_min": _finite_stat(backend, np.min),
        "backend_q_median": _finite_stat(backend, np.median),
        "backend_q_mean": _finite_stat(backend, np.mean),
        "backend_q_p90": _finite_stat(backend, lambda arr: np.percentile(arr, 90)),
        "sigma_median": _finite_stat(sigma, np.median),
        "sigma_mean": _finite_stat(sigma, np.mean),
        "backend_blend_alpha": "" if backend_blend_alpha is None else float(backend_blend_alpha),
    }


def _bag_buckets(channels: dict[str, ChannelFloat32], count: int, mode: str) -> np.ndarray:
    if mode == "global":
        return np.full((count,), "global", dtype=object)
    if mode == "source_code":
        values = np.asarray(channels.get("source_code", ChannelFloat32()).values, dtype=np.float32)
        if len(values) != count:
            return np.full((count,), "unknown", dtype=object)
        return np.asarray([_bucket_from_source_code(value) for value in values], dtype=object)
    raise ValueError(mode)


def _bucket_from_source_code(value: float) -> str:
    code = int(round(float(value)))
    return {
        1: "klt",
        2: "gftt",
        4: "orb",
        5: "lk_recovery",
        6: "homography_recovery",
        10: "learned",
        20: "xfeat",
        30: "loftr",
    }.get(code, "unknown")


def _temper_quality(
    q_conformal: np.ndarray,
    backend_blend_alpha: float | None,
    min_quality: float,
) -> np.ndarray:
    q = np.clip(np.asarray(q_conformal, dtype=np.float32), float(min_quality), 1.0)
    if backend_blend_alpha is None:
        return q
    alpha = float(backend_blend_alpha)
    return np.clip(alpha + (1.0 - alpha) * q, float(min_quality), 1.0).astype(np.float32)


def _finite_stat(values: np.ndarray, fn) -> float:
    if values.size == 0:
        return float("nan")
    return float(fn(values))


def _write_stats(path: Path, row: dict[str, float | int | str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


if __name__ == "__main__":
    raise SystemExit(main())
