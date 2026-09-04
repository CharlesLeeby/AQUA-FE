#!/usr/bin/env python3
"""Read-only preflight for persistent XFeat tracks consumed by VINS-Fusion.

The default thresholds mirror the relevant VINS-Fusion initialization gates:
unique mono feature IDs, at least 40 active tracks with four consecutive
observations after warmup, and a viable lag-10 relative-pose pair.

The CLI prints one JSON document and never writes an artifact.  Exit status is
0 for PASS, 1 for a scientific FAIL, and 2 for an input/runtime ERROR.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Sequence

import cv2
import numpy as np


SCHEMA_VERSION = "aqua-fe-xfeat-persistent-preflight-v2"
DEFAULT_FEATURE_TOPIC = "/feature_tracker/feature"
MAX_REPORTED_FRAME_INDICES = 20


@dataclass(frozen=True)
class FeatureFrame:
    """One exported monocular feature frame in VINS normalized coordinates."""

    index: int
    stamp_s: float
    ids: np.ndarray
    normalized_points: np.ndarray


@dataclass(frozen=True)
class CheckConfig:
    """Thresholds matching the current VINS-Fusion initialization contract."""

    warmup_frames: int = 10
    long_track_length: int = 4
    min_long_tracks: int = 40
    lag: int = 10
    min_correspondences: int = 20
    focal_length_px: float = 460.0
    min_mean_parallax_px: float = 30.0
    ransac_pixel_threshold: float = 0.3
    ransac_confidence: float = 0.99
    ransac_seed: int = 0
    min_pose_inliers: int = 12


PoseSolver = Callable[[np.ndarray, np.ndarray, CheckConfig], int]


def _validate_config(config: CheckConfig) -> None:
    integer_positive = {
        "long_track_length": config.long_track_length,
        "min_long_tracks": config.min_long_tracks,
        "lag": config.lag,
        "min_correspondences": config.min_correspondences,
        "min_pose_inliers": config.min_pose_inliers,
    }
    if config.warmup_frames < 0:
        raise ValueError("warmup_frames must be non-negative")
    for name, value in integer_positive.items():
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    finite_positive = {
        "focal_length_px": config.focal_length_px,
        "min_mean_parallax_px": config.min_mean_parallax_px,
        "ransac_pixel_threshold": config.ransac_pixel_threshold,
        "ransac_confidence": config.ransac_confidence,
    }
    for name, value in finite_positive.items():
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{name} must be finite and positive")
    if config.ransac_confidence > 1.0:
        raise ValueError("ransac_confidence must not exceed 1")


def _validated_frames(frames: Sequence[FeatureFrame]) -> list[FeatureFrame]:
    checked: list[FeatureFrame] = []
    for position, frame in enumerate(frames):
        ids = np.asarray(frame.ids)
        points = np.asarray(frame.normalized_points)
        if ids.ndim != 1:
            raise ValueError(f"frame {position}: ids must be one-dimensional")
        if points.shape != (len(ids), 2):
            raise ValueError(
                f"frame {position}: normalized_points must have shape ({len(ids)}, 2)"
            )
        if not np.issubdtype(ids.dtype, np.integer):
            raise ValueError(f"frame {position}: ids must have integer dtype")
        if not np.isfinite(points).all():
            raise ValueError(f"frame {position}: normalized_points contain non-finite values")
        if not math.isfinite(float(frame.stamp_s)):
            raise ValueError(f"frame {position}: stamp_s must be finite")
        checked.append(
            FeatureFrame(
                index=int(frame.index),
                stamp_s=float(frame.stamp_s),
                ids=ids.astype(np.int64, copy=False),
                normalized_points=points.astype(np.float32, copy=False),
            )
        )
    return checked


def same_frame_unique_id_check(frames: Sequence[FeatureFrame]) -> dict[str, object]:
    """Return duplicate-ID evidence without mutating the input frames."""

    duplicate_observations = 0
    duplicate_frames: list[int] = []
    for frame in frames:
        _, counts = np.unique(frame.ids, return_counts=True)
        duplicates = int(np.sum(np.maximum(counts - 1, 0)))
        if duplicates:
            duplicate_observations += duplicates
            duplicate_frames.append(int(frame.index))
    return {
        "pass": duplicate_observations == 0,
        "duplicate_observations": duplicate_observations,
        "duplicate_frame_count": len(duplicate_frames),
        "duplicate_frame_indices": duplicate_frames[:MAX_REPORTED_FRAME_INDICES],
        "duplicate_frame_indices_truncated": (
            len(duplicate_frames) > MAX_REPORTED_FRAME_INDICES
        ),
    }


def consecutive_long_track_counts(
    frames: Sequence[FeatureFrame], *, minimum_length: int = 4
) -> list[int]:
    """Count IDs with a consecutive visible streak of ``minimum_length``."""

    if minimum_length <= 0:
        raise ValueError("minimum_length must be positive")
    previous_ages: dict[int, int] = {}
    counts: list[int] = []
    for frame in frames:
        current_ages = {
            int(feature_id): previous_ages.get(int(feature_id), 0) + 1
            for feature_id in np.unique(frame.ids)
        }
        counts.append(sum(age >= minimum_length for age in current_ages.values()))
        previous_ages = current_ages
    return counts


def post_warmup_long_track_check(
    frames: Sequence[FeatureFrame], config: CheckConfig
) -> dict[str, object]:
    counts = consecutive_long_track_counts(
        frames, minimum_length=config.long_track_length
    )
    post_warmup = counts[config.warmup_frames :]
    violating = [
        int(frames[index].index)
        for index in range(config.warmup_frames, len(frames))
        if counts[index] < config.min_long_tracks
    ]
    return {
        "pass": bool(post_warmup) and not violating,
        "warmup_frames": config.warmup_frames,
        "track_length": config.long_track_length,
        "required_long_tracks": config.min_long_tracks,
        "post_warmup_frame_count": len(post_warmup),
        "min": min(post_warmup) if post_warmup else None,
        "median": float(statistics.median(post_warmup)) if post_warmup else None,
        "max": max(post_warmup) if post_warmup else None,
        "violating_frame_count": len(violating),
        "violating_frame_indices": violating[:MAX_REPORTED_FRAME_INDICES],
        "violating_frame_indices_truncated": (
            len(violating) > MAX_REPORTED_FRAME_INDICES
        ),
    }


def vins_relative_pose_inliers(
    points0: np.ndarray, points1: np.ndarray, config: CheckConfig
) -> int:
    """Replicate VINS' normalized FM-RANSAC plus ``recoverPose`` inlier count."""

    left = np.ascontiguousarray(points0, dtype=np.float32)
    right = np.ascontiguousarray(points1, dtype=np.float32)
    if left.shape != right.shape or left.ndim != 2 or left.shape[1:] != (2,):
        raise ValueError("relative-pose points must have matching shape (N, 2)")
    if len(left) < 15:
        return 0
    cv2.setRNGSeed(int(config.ransac_seed))
    threshold = float(config.ransac_pixel_threshold) / float(config.focal_length_px)
    try:
        matrix, mask = cv2.findFundamentalMat(
            left,
            right,
            cv2.FM_RANSAC,
            threshold,
            float(config.ransac_confidence),
        )
        if matrix is None or mask is None or np.asarray(matrix).shape != (3, 3):
            return 0
        inliers, _, _, _ = cv2.recoverPose(
            np.asarray(matrix, dtype=np.float64),
            left,
            right,
            np.eye(3, dtype=np.float64),
            mask=np.asarray(mask, dtype=np.uint8).reshape(-1, 1).copy(),
        )
    except cv2.error:
        return 0
    return int(inliers)


def _id_to_point(frame: FeatureFrame) -> dict[int, np.ndarray]:
    return {
        int(feature_id): frame.normalized_points[index]
        for index, feature_id in enumerate(frame.ids)
    }


def rolling_lag_pose_check(
    frames: Sequence[FeatureFrame],
    config: CheckConfig,
    *,
    pose_solver: PoseSolver = vins_relative_pose_inliers,
) -> dict[str, object]:
    """Check whether any exact-lag pair passes all VINS relative-pose gates."""

    evaluated_pairs = max(0, len(frames) - config.lag)
    count_gate_pairs = 0
    parallax_gate_pairs = 0
    pose_gate_pairs = 0
    max_common_ids = 0
    max_mean_parallax_px: float | None = None
    max_pose_inliers = 0
    first_passing_pair: dict[str, object] | None = None

    point_maps = [_id_to_point(frame) for frame in frames]
    for right_index in range(config.lag, len(frames)):
        left_index = right_index - config.lag
        common_ids = sorted(point_maps[left_index].keys() & point_maps[right_index].keys())
        correspondence_count = len(common_ids)
        max_common_ids = max(max_common_ids, correspondence_count)
        if correspondence_count <= config.min_correspondences:
            continue
        count_gate_pairs += 1
        points0 = np.asarray(
            [point_maps[left_index][feature_id] for feature_id in common_ids],
            dtype=np.float32,
        )
        points1 = np.asarray(
            [point_maps[right_index][feature_id] for feature_id in common_ids],
            dtype=np.float32,
        )
        mean_parallax_px = float(
            np.mean(np.linalg.norm(points0 - points1, axis=1))
            * config.focal_length_px
        )
        if max_mean_parallax_px is None or mean_parallax_px > max_mean_parallax_px:
            max_mean_parallax_px = mean_parallax_px
        if mean_parallax_px <= config.min_mean_parallax_px:
            continue
        parallax_gate_pairs += 1
        pose_inliers = int(pose_solver(points0, points1, config))
        max_pose_inliers = max(max_pose_inliers, pose_inliers)
        if pose_inliers <= config.min_pose_inliers:
            continue
        pose_gate_pairs += 1
        if first_passing_pair is None:
            first_passing_pair = {
                "left_frame_index": int(frames[left_index].index),
                "right_frame_index": int(frames[right_index].index),
                "left_stamp_s": float(frames[left_index].stamp_s),
                "right_stamp_s": float(frames[right_index].stamp_s),
                "common_ids": correspondence_count,
                "mean_parallax_px": mean_parallax_px,
                "pose_inliers": pose_inliers,
            }

    return {
        "pass": pose_gate_pairs > 0,
        "lag": config.lag,
        "evaluated_pairs": evaluated_pairs,
        "correspondence_gate": f">{config.min_correspondences}",
        "parallax_gate_px": f">{config.min_mean_parallax_px:g}",
        "pose_inlier_gate": f">{config.min_pose_inliers}",
        "count_gate_pairs": count_gate_pairs,
        "parallax_gate_pairs": parallax_gate_pairs,
        "pose_gate_pairs": pose_gate_pairs,
        "max_common_ids": max_common_ids,
        "max_mean_parallax_px": max_mean_parallax_px,
        "max_pose_inliers": max_pose_inliers,
        "first_passing_pair": first_passing_pair,
    }


def evaluate_frames(
    frames: Sequence[FeatureFrame],
    config: CheckConfig | None = None,
    *,
    pose_solver: PoseSolver = vins_relative_pose_inliers,
) -> dict[str, object]:
    """Pure scientific evaluation over already-decoded feature frames."""

    effective = config or CheckConfig()
    _validate_config(effective)
    checked = _validated_frames(frames)
    unique = same_frame_unique_id_check(checked)
    long_tracks = post_warmup_long_track_check(checked, effective)
    lag_pose = rolling_lag_pose_check(
        checked, effective, pose_solver=pose_solver
    )
    reasons: list[str] = []
    if not checked:
        reasons.append("NO_FEATURE_FRAMES")
    if not unique["pass"]:
        reasons.append("DUPLICATE_ID_WITHIN_FRAME")
    if not long_tracks["pass"]:
        reasons.append("LONG4_BELOW_THRESHOLD_AFTER_WARMUP")
    if not lag_pose["pass"]:
        reasons.append("NO_VIABLE_LAG10_RELATIVE_POSE_PAIR")
    passed = not reasons
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "pass": passed,
        "reasons": reasons,
        "frame_count": len(checked),
        "feature_observation_count": int(sum(len(frame.ids) for frame in checked)),
        "config": asdict(effective),
        "checks": {
            "same_frame_unique_ids": unique,
            "post_warmup_long_tracks": long_tracks,
            "rolling_lag_relative_pose": lag_pose,
        },
    }


def load_feature_frames(
    feature_bag: Path, feature_topic: str = DEFAULT_FEATURE_TOPIC
) -> list[FeatureFrame]:
    """Decode PointCloud feature messages; ROS is imported only for bag I/O."""

    if not feature_bag.is_file():
        raise FileNotFoundError(feature_bag)
    try:
        import rosbag  # type: ignore
    except ModuleNotFoundError as exc:  # Keep pure-function imports ROS-free.
        raise RuntimeError("rosbag is required only for feature bag input") from exc

    frames: list[FeatureFrame] = []
    with rosbag.Bag(str(feature_bag), "r") as bag:
        for _, message, record_stamp in bag.read_messages(topics=[feature_topic]):
            id_channels = [
                channel for channel in message.channels if channel.name == "id"
            ]
            if len(id_channels) != 1:
                raise ValueError(
                    f"feature frame {len(frames)} must contain exactly one id channel"
                )
            raw_ids = np.asarray(id_channels[0].values, dtype=np.float64)
            if len(raw_ids) != len(message.points):
                raise ValueError(
                    f"feature frame {len(frames)} id/point length mismatch: "
                    f"{len(raw_ids)} != {len(message.points)}"
                )
            if not np.isfinite(raw_ids).all():
                raise ValueError(f"feature frame {len(frames)} contains non-finite IDs")
            rounded_ids = np.rint(raw_ids)
            if not np.array_equal(raw_ids, rounded_ids):
                raise ValueError(f"feature frame {len(frames)} contains non-integer IDs")
            if len(rounded_ids):
                limits = np.iinfo(np.int64)
                if rounded_ids.min() < limits.min or rounded_ids.max() > limits.max:
                    raise ValueError(f"feature frame {len(frames)} ID exceeds int64 range")
            points = np.asarray(
                [(point.x, point.y) for point in message.points], dtype=np.float32
            ).reshape(-1, 2)
            if not np.isfinite(points).all():
                raise ValueError(
                    f"feature frame {len(frames)} contains non-finite normalized points"
                )
            header = getattr(message, "header", None)
            stamp_s = (
                float(header.stamp.to_sec())
                if header is not None and header.stamp.to_sec() > 0.0
                else float(record_stamp.to_sec())
            )
            frames.append(
                FeatureFrame(
                    index=len(frames),
                    stamp_s=stamp_s,
                    ids=rounded_ids.astype(np.int64),
                    normalized_points=points,
                )
            )
    if not frames:
        raise ValueError(f"no messages found on feature topic {feature_topic}")
    return frames


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check whether an XFeat feature bag has VINS-usable persistent IDs."
    )
    parser.add_argument("feature_bag", type=Path)
    parser.add_argument("--feature-topic", default=DEFAULT_FEATURE_TOPIC)
    parser.add_argument("--warmup-frames", type=int, default=10)
    parser.add_argument("--min-long4", type=int, default=40)
    parser.add_argument("--lag", type=int, default=10)
    parser.add_argument("--min-correspondences", type=int, default=20)
    parser.add_argument("--focal-length-px", type=float, default=460.0)
    parser.add_argument("--min-mean-parallax-px", type=float, default=30.0)
    parser.add_argument("--ransac-pixel-threshold", type=float, default=0.3)
    parser.add_argument("--ransac-confidence", type=float, default=0.99)
    parser.add_argument("--ransac-seed", type=int, default=0)
    parser.add_argument("--min-pose-inliers", type=int, default=12)
    return parser


def _print_json(payload: dict[str, object]) -> None:
    print(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = CheckConfig(
        warmup_frames=args.warmup_frames,
        min_long_tracks=args.min_long4,
        lag=args.lag,
        min_correspondences=args.min_correspondences,
        focal_length_px=args.focal_length_px,
        min_mean_parallax_px=args.min_mean_parallax_px,
        ransac_pixel_threshold=args.ransac_pixel_threshold,
        ransac_confidence=args.ransac_confidence,
        ransac_seed=args.ransac_seed,
        min_pose_inliers=args.min_pose_inliers,
    )
    try:
        frames = load_feature_frames(args.feature_bag, args.feature_topic)
        result = evaluate_frames(frames, config)
        result["input"] = {
            "feature_bag": str(args.feature_bag.expanduser().resolve(strict=False)),
            "feature_topic": args.feature_topic,
        }
    except Exception as exc:
        _print_json(
            {
                "schema_version": SCHEMA_VERSION,
                "status": "ERROR",
                "pass": False,
                "input": {
                    "feature_bag": str(
                        args.feature_bag.expanduser().resolve(strict=False)
                    ),
                    "feature_topic": args.feature_topic,
                },
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        return 2
    _print_json(result)
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
