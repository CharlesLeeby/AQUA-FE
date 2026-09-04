#!/usr/bin/env python3
"""Frozen camera-only Sim(3) evaluator for the AnyFeature-VSLAM A02 pair.

The evaluator is intentionally narrower than the project's general trajectory
tools.  It consumes the two official sparse keyframe TUM files and the frozen
46-pose A02 COLMAP-plus-pressure reference proxy.  Association is performed
only at those original reference timestamps.  There is no nearest-neighbour
association, reference-pose reuse, extrapolation, or result-dependent choice.

TUM rows are interpreted in the convention written by AnyFeature-VSLAM's
``SaveKeyFrameTrajectoryTUM``: translation is the camera centre in the SLAM
world and the xyzw quaternion is the camera-to-world rotation ``R_wc``.

Return codes are part of the interface:

* 0: both inputs are structurally valid and all frozen numeric-support and
  Sim(3) identifiability gates pass; numeric APE/RPE is emitted;
* 1: the attempt is auditable but a trajectory, support, or alignment gate
  fails; no numeric APE/RPE is emitted;
* 2: invocation, frozen-reference, input-file, or no-clobber contract blocks
  the attempt before a valid evaluation artifact can be published.
"""

from __future__ import annotations

import argparse
from bisect import bisect_left
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = ROOT / "papers/anyfeature_vslam_r2d2_a02_preregistration.md"

SCHEMA_VERSION = "aqua-fe-anyfeature-vslam-a02-sim3-common-support-v1"
MANIFEST_SCHEMA_VERSION = SCHEMA_VERSION + "-artifact-manifest-v1"
REFERENCE_ROLE = (
    "same-image COLMAP plus pressure-scale reference proxy; not independent "
    "ground truth"
)
COMPARISON_LABEL = "camera-only monocular AnyFeature-VSLAM / Sim(3)"

ARM_ORDER = ("orb32", "r2d2_128")
EXPECTED_REFERENCE_COUNT = 46
NOMINAL_REFERENCE_RATE_HZ = 1
MAX_BRACKET_GAP_S = Decimal("2.0")
MIN_COMMON_COVERAGE = 0.70
MIN_COMMON_POSES = 30
MIN_COMMON_SPAN_S = 10.0
MIN_RPE_PAIRS = 10
RPE_DELTA_REFERENCE_STEPS = 1

RC_NUMERIC_VALID = 0
RC_SCIENTIFIC_INVALID = 1
RC_CONTRACT_BLOCKED = 2

RESULT_FILENAME = "anyfeature_sim3_common_support_result.json"
METRICS_FILENAME = "anyfeature_sim3_common_support_metrics.csv"
AUDIT_FILENAME = "anyfeature_sim3_common_support_audit.csv"
MANIFEST_FILENAME = "artifact_manifest.json"


class ContractError(ValueError):
    """A frozen input/output contract prevents formal evaluation."""


class TrajectoryValidationError(ValueError):
    """A present trajectory is not a syntactically usable official TUM file."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class DegenerateAlignmentError(ValueError):
    """The common positions do not identify a 3-D similarity transform."""


@dataclass(frozen=True)
class PoseSeries:
    stamps: Tuple[Decimal, ...]
    positions: np.ndarray
    quaternions_xyzw: np.ndarray
    data_row_count: int
    quaternion_norm_min: float
    quaternion_norm_max: float


@dataclass(frozen=True)
class Association:
    valid: bool
    method: str
    position: Optional[np.ndarray]
    quaternion_xyzw: Optional[np.ndarray]
    left_stamp: Optional[Decimal]
    right_stamp: Optional[Decimal]
    bracket_gap_s: Optional[Decimal]
    alpha: Optional[float]


@dataclass(frozen=True)
class Sim3:
    scale: float
    rotation: np.ndarray
    translation: np.ndarray
    source_rank: int
    target_rank: int
    covariance_rank: int
    source_variance: float
    target_variance: float


def canonical_json_bytes(value: object) -> bytes:
    """Serialize finite JSON deterministically, including one final newline."""

    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> Dict[str, object]:
    absolute = path.expanduser().resolve(strict=True)
    return {
        "path": str(absolute),
        "sha256": sha256_file(absolute),
        "size_bytes": absolute.stat().st_size,
    }


def require_regular_input(path: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ContractError("{} must not be a symlink".format(label))
    try:
        absolute = expanded.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContractError("{} is unavailable: {}".format(label, error)) from error
    if not absolute.is_file() or absolute.is_symlink():
        raise ContractError("{} must be a regular non-symlink file".format(label))
    return absolute


def parse_decimal_timestamp(raw: str, path: Path, line_number: int) -> Decimal:
    try:
        stamp = Decimal(raw)
    except InvalidOperation as error:
        raise TrajectoryValidationError(
            "INVALID_TIMESTAMP",
            "{}:{}: invalid decimal timestamp".format(path, line_number),
        ) from error
    if not stamp.is_finite():
        raise TrajectoryValidationError(
            "NONFINITE_TIMESTAMP",
            "{}:{}: timestamp must be finite".format(path, line_number),
        )
    try:
        stamp_float = float(stamp)
    except (OverflowError, ValueError) as error:
        raise TrajectoryValidationError(
            "TIMESTAMP_OUT_OF_RANGE",
            "{}:{}: timestamp is outside evaluator range".format(path, line_number),
        ) from error
    if not math.isfinite(stamp_float):
        raise TrajectoryValidationError(
            "TIMESTAMP_OUT_OF_RANGE",
            "{}:{}: timestamp is outside evaluator range".format(path, line_number),
        )
    return stamp


def _parse_finite_floats(
    fields: Sequence[str], path: Path, line_number: int
) -> List[float]:
    try:
        values = [float(value) for value in fields]
    except ValueError as error:
        raise TrajectoryValidationError(
            "INVALID_POSE",
            "{}:{}: invalid numeric pose".format(path, line_number),
        ) from error
    if not all(math.isfinite(value) for value in values):
        raise TrajectoryValidationError(
            "NONFINITE_POSE",
            "{}:{}: pose values must be finite".format(path, line_number),
        )
    return values


def load_strict_tum(path: Path, *, expected_count: Optional[int]) -> PoseSeries:
    """Load one strict TUM pose file without sorting or deduplication."""

    stamps: List[Decimal] = []
    positions: List[List[float]] = []
    quaternions: List[np.ndarray] = []
    quaternion_norms: List[float] = []
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            fields = stripped.split()
            if len(fields) != 8:
                raise TrajectoryValidationError(
                    "INVALID_COLUMN_COUNT",
                    "{}:{}: expected exactly 8 TUM columns, found {}".format(
                        path, line_number, len(fields)
                    ),
                )
            stamp = parse_decimal_timestamp(fields[0], path, line_number)
            values = _parse_finite_floats(fields[1:], path, line_number)
            quaternion = np.asarray(values[3:7], dtype=np.float64)
            norm = float(np.linalg.norm(quaternion))
            if not math.isfinite(norm) or norm <= 1e-12:
                raise TrajectoryValidationError(
                    "INVALID_QUATERNION",
                    "{}:{}: quaternion must be finite and non-zero".format(
                        path, line_number
                    ),
                )
            stamps.append(stamp)
            positions.append(values[0:3])
            quaternions.append(quaternion / norm)
            quaternion_norms.append(norm)

    if not stamps:
        raise TrajectoryValidationError("EMPTY_TRAJECTORY", "{} has no TUM poses".format(path))
    if expected_count is not None and len(stamps) != expected_count:
        raise TrajectoryValidationError(
            "REFERENCE_COUNT_MISMATCH",
            "{} must contain exactly {} poses, found {}".format(
                path, expected_count, len(stamps)
            ),
        )
    for index in range(1, len(stamps)):
        if stamps[index] == stamps[index - 1]:
            raise TrajectoryValidationError(
                "DUPLICATE_TIMESTAMP",
                "{} has duplicate timestamp {} at data rows {} and {}".format(
                    path, decimal_text(stamps[index]), index, index + 1
                ),
            )
        if stamps[index] < stamps[index - 1]:
            raise TrajectoryValidationError(
                "NONMONOTONIC_TIMESTAMP",
                "{} timestamps must be strictly increasing in file order".format(path),
            )
        if not math.isfinite(float(stamps[index] - stamps[index - 1])):
            raise TrajectoryValidationError(
                "TIMESTAMP_RANGE_OVERFLOW",
                "{} timestamp range is outside evaluator precision".format(path),
            )
    return PoseSeries(
        stamps=tuple(stamps),
        positions=np.asarray(positions, dtype=np.float64).reshape((-1, 3)),
        quaternions_xyzw=np.asarray(quaternions, dtype=np.float64).reshape((-1, 4)),
        data_row_count=len(stamps),
        quaternion_norm_min=float(min(quaternion_norms)),
        quaternion_norm_max=float(max(quaternion_norms)),
    )


def decimal_text(value: Decimal) -> str:
    """Render a Decimal without a binary floating-point round trip."""

    return format(value, "f")


def float_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if not math.isfinite(value):
        raise ValueError("CSV values must be finite")
    return format(value, ".17g")


def quaternion_xyzw_to_rotation(quaternion: np.ndarray) -> np.ndarray:
    qx, qy, qz, qw = np.asarray(quaternion, dtype=np.float64)
    norm = float(np.linalg.norm([qx, qy, qz, qw]))
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("quaternion must be finite and non-zero")
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    return np.asarray(
        [
            [
                1.0 - 2.0 * (qy * qy + qz * qz),
                2.0 * (qx * qy - qz * qw),
                2.0 * (qx * qz + qy * qw),
            ],
            [
                2.0 * (qx * qy + qz * qw),
                1.0 - 2.0 * (qx * qx + qz * qz),
                2.0 * (qy * qz - qx * qw),
            ],
            [
                2.0 * (qx * qz - qy * qw),
                2.0 * (qy * qz + qx * qw),
                1.0 - 2.0 * (qx * qx + qy * qy),
            ],
        ],
        dtype=np.float64,
    )


def rotation_to_quaternion_xyzw(rotation: np.ndarray) -> np.ndarray:
    matrix = np.asarray(rotation, dtype=np.float64)
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("rotation must be a finite 3x3 matrix")
    trace = float(np.trace(matrix))
    if trace > 0.0:
        scale = math.sqrt(trace + 1.0) * 2.0
        qw = 0.25 * scale
        qx = (matrix[2, 1] - matrix[1, 2]) / scale
        qy = (matrix[0, 2] - matrix[2, 0]) / scale
        qz = (matrix[1, 0] - matrix[0, 1]) / scale
    else:
        diagonal = np.diag(matrix)
        index = int(np.argmax(diagonal))
        if index == 0:
            scale = math.sqrt(
                max(0.0, 1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2])
            ) * 2.0
            if scale <= 1e-15:
                raise ValueError("rotation-to-quaternion conversion is degenerate")
            qw = (matrix[2, 1] - matrix[1, 2]) / scale
            qx = 0.25 * scale
            qy = (matrix[0, 1] + matrix[1, 0]) / scale
            qz = (matrix[0, 2] + matrix[2, 0]) / scale
        elif index == 1:
            scale = math.sqrt(
                max(0.0, 1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2])
            ) * 2.0
            if scale <= 1e-15:
                raise ValueError("rotation-to-quaternion conversion is degenerate")
            qw = (matrix[0, 2] - matrix[2, 0]) / scale
            qx = (matrix[0, 1] + matrix[1, 0]) / scale
            qy = 0.25 * scale
            qz = (matrix[1, 2] + matrix[2, 1]) / scale
        else:
            scale = math.sqrt(
                max(0.0, 1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1])
            ) * 2.0
            if scale <= 1e-15:
                raise ValueError("rotation-to-quaternion conversion is degenerate")
            qw = (matrix[1, 0] - matrix[0, 1]) / scale
            qx = (matrix[0, 2] + matrix[2, 0]) / scale
            qy = (matrix[1, 2] + matrix[2, 1]) / scale
            qz = 0.25 * scale
    quaternion = np.asarray([qx, qy, qz, qw], dtype=np.float64)
    quaternion /= np.linalg.norm(quaternion)
    # q and -q encode the same rotation.  Canonicalize the sign for stable CSV.
    for component in quaternion[::-1]:
        if abs(float(component)) <= 1e-15:
            continue
        if component < 0.0:
            quaternion = -quaternion
        break
    return quaternion


def slerp_shortest_xyzw(q0: np.ndarray, q1: np.ndarray, alpha: float) -> np.ndarray:
    """Normalized shortest-arc quaternion SLERP."""

    if not math.isfinite(alpha) or alpha < 0.0 or alpha > 1.0:
        raise ValueError("SLERP alpha must be in [0, 1]")
    left = np.asarray(q0, dtype=np.float64)
    right = np.asarray(q1, dtype=np.float64)
    left /= np.linalg.norm(left)
    right /= np.linalg.norm(right)
    dot = float(np.dot(left, right))
    if dot < 0.0:
        right = -right
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    if dot > 0.9995:
        result = left + alpha * (right - left)
        result /= np.linalg.norm(result)
        return result
    angle = math.acos(dot)
    sine = math.sin(angle)
    result = (
        math.sin((1.0 - alpha) * angle) / sine * left
        + math.sin(alpha * angle) / sine * right
    )
    result /= np.linalg.norm(result)
    return result


def associate_reference_stamps(
    reference_stamps: Sequence[Decimal], series: PoseSeries
) -> List[Association]:
    """Associate only by exact timestamp or the unique adjacent two-sided bracket."""

    associations: List[Association] = []
    stamps = series.stamps
    for target in reference_stamps:
        right_index = bisect_left(stamps, target)
        if right_index < len(stamps) and stamps[right_index] == target:
            associations.append(
                Association(
                    valid=True,
                    method="EXACT",
                    position=series.positions[right_index].copy(),
                    quaternion_xyzw=series.quaternions_xyzw[right_index].copy(),
                    left_stamp=target,
                    right_stamp=target,
                    bracket_gap_s=Decimal(0),
                    alpha=0.0,
                )
            )
            continue

        if right_index == 0 or right_index == len(stamps):
            associations.append(
                Association(
                    valid=False,
                    method="OUT_OF_RANGE",
                    position=None,
                    quaternion_xyzw=None,
                    left_stamp=(stamps[-1] if right_index == len(stamps) else None),
                    right_stamp=(stamps[0] if right_index == 0 else None),
                    bracket_gap_s=None,
                    alpha=None,
                )
            )
            continue

        left_index = right_index - 1
        left_stamp = stamps[left_index]
        right_stamp = stamps[right_index]
        gap = right_stamp - left_stamp
        if gap <= 0 or gap > MAX_BRACKET_GAP_S:
            associations.append(
                Association(
                    valid=False,
                    method="GAP_EXCEEDED",
                    position=None,
                    quaternion_xyzw=None,
                    left_stamp=left_stamp,
                    right_stamp=right_stamp,
                    bracket_gap_s=gap,
                    alpha=None,
                )
            )
            continue

        alpha = float((target - left_stamp) / gap)
        position = (
            (1.0 - alpha) * series.positions[left_index]
            + alpha * series.positions[right_index]
        )
        quaternion = slerp_shortest_xyzw(
            series.quaternions_xyzw[left_index],
            series.quaternions_xyzw[right_index],
            alpha,
        )
        associations.append(
            Association(
                valid=True,
                method="INTERPOLATED",
                position=position,
                quaternion_xyzw=quaternion,
                left_stamp=left_stamp,
                right_stamp=right_stamp,
                bracket_gap_s=gap,
                alpha=alpha,
            )
        )
    return associations


def fit_umeyama_sim3(source: np.ndarray, target: np.ndarray) -> Sim3:
    """Fit ``target = scale * rotation @ source + translation``.

    A rank-two centred point set is sufficient (the common trajectory may be
    planar); a rank-zero or rank-one set leaves the 3-D rotation unidentifiable
    and is rejected rather than silently selecting an arbitrary SVD rotation.
    """

    source_arr = np.asarray(source, dtype=np.float64)
    target_arr = np.asarray(target, dtype=np.float64)
    if (
        source_arr.shape != target_arr.shape
        or source_arr.ndim != 2
        or source_arr.shape[1] != 3
        or len(source_arr) < 3
    ):
        raise DegenerateAlignmentError(
            "source and target must have matching shape (N,3), N>=3"
        )
    if not np.all(np.isfinite(source_arr)) or not np.all(np.isfinite(target_arr)):
        raise DegenerateAlignmentError("alignment positions must be finite")

    source_mean = np.mean(source_arr, axis=0)
    target_mean = np.mean(target_arr, axis=0)
    source_centered = source_arr - source_mean
    target_centered = target_arr - target_mean
    source_rank = int(np.linalg.matrix_rank(source_centered))
    target_rank = int(np.linalg.matrix_rank(target_centered))
    source_variance = float(np.mean(np.sum(source_centered ** 2, axis=1)))
    target_variance = float(np.mean(np.sum(target_centered ** 2, axis=1)))
    if source_rank < 2 or target_rank < 2:
        raise DegenerateAlignmentError(
            "common positions are rank deficient (source_rank={}, target_rank={})".format(
                source_rank, target_rank
            )
        )
    if source_variance <= 0.0 or target_variance <= 0.0:
        raise DegenerateAlignmentError("common positions have zero variance")

    covariance = (target_centered.T @ source_centered) / float(len(source_arr))
    covariance_rank = int(np.linalg.matrix_rank(covariance))
    if covariance_rank < 2:
        raise DegenerateAlignmentError(
            "paired common positions have rank-deficient covariance "
            "(covariance_rank={})".format(covariance_rank)
        )
    u_matrix, singular_values, vt_matrix = np.linalg.svd(covariance)
    correction = np.eye(3, dtype=np.float64)
    if np.linalg.det(u_matrix @ vt_matrix) < 0.0:
        correction[-1, -1] = -1.0
    rotation = u_matrix @ correction @ vt_matrix
    scale = float(np.sum(singular_values * np.diag(correction)) / source_variance)
    translation = target_mean - scale * (rotation @ source_mean)
    if (
        not math.isfinite(scale)
        or scale <= 0.0
        or not np.all(np.isfinite(rotation))
        or not np.all(np.isfinite(translation))
        or abs(float(np.linalg.det(rotation)) - 1.0) > 1e-8
    ):
        raise DegenerateAlignmentError("Umeyama produced an invalid proper Sim(3)")
    return Sim3(
        scale=scale,
        rotation=rotation,
        translation=translation,
        source_rank=source_rank,
        target_rank=target_rank,
        covariance_rank=covariance_rank,
        source_variance=source_variance,
        target_variance=target_variance,
    )


def apply_sim3_positions(sim3: Sim3, positions: np.ndarray) -> np.ndarray:
    values = np.asarray(positions, dtype=np.float64)
    return sim3.scale * (sim3.rotation @ values.T).T + sim3.translation


def apply_sim3_orientations(sim3: Sim3, quaternions: np.ndarray) -> np.ndarray:
    """Rotate camera-to-world orientations by the Sim(3) world rotation."""

    output = np.empty_like(np.asarray(quaternions, dtype=np.float64))
    for index, quaternion in enumerate(quaternions):
        aligned_rotation = sim3.rotation @ quaternion_xyzw_to_rotation(quaternion)
        output[index] = rotation_to_quaternion_xyzw(aligned_rotation)
    return output


def metric_summary(errors: np.ndarray) -> Dict[str, float]:
    values = np.asarray(errors, dtype=np.float64)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)):
        raise ValueError("metric errors must be a nonempty finite vector")
    return {
        "rmse_m": float(np.sqrt(np.mean(values ** 2))),
        "median_m": float(np.median(values)),
        "max_m": float(np.max(values)),
    }


def association_histogram(associations: Sequence[Association]) -> Dict[str, int]:
    histogram: Dict[str, int] = {}
    for item in associations:
        histogram[item.method] = histogram.get(item.method, 0) + 1
    return {key: histogram[key] for key in sorted(histogram)}


def pose_series_audit(series: PoseSeries) -> Dict[str, object]:
    timestamp_deltas = [
        float(series.stamps[index] - series.stamps[index - 1])
        for index in range(1, len(series.stamps))
    ]
    return {
        "data_row_count": series.data_row_count,
        "first_timestamp": decimal_text(series.stamps[0]),
        "last_timestamp": decimal_text(series.stamps[-1]),
        "finite_pose_fields": True,
        "strictly_increasing_unique_timestamps": True,
        "quaternion_norm_before_normalization_min": series.quaternion_norm_min,
        "quaternion_norm_before_normalization_max": series.quaternion_norm_max,
        "timestamp_delta_s_min": min(timestamp_deltas) if timestamp_deltas else None,
        "timestamp_delta_s_median": (
            float(np.median(timestamp_deltas)) if timestamp_deltas else None
        ),
        "timestamp_delta_s_max": max(timestamp_deltas) if timestamp_deltas else None,
    }


def sim3_json(sim3: Sim3) -> Dict[str, object]:
    return {
        "definition": "reference_position = scale * rotation * arm_position + translation",
        "scale": sim3.scale,
        "rotation": sim3.rotation.tolist(),
        "translation": sim3.translation.tolist(),
        "rotation_determinant": float(np.linalg.det(sim3.rotation)),
        "source_rank": sim3.source_rank,
        "target_rank": sim3.target_rank,
        "covariance_rank": sim3.covariance_rank,
        "source_variance": sim3.source_variance,
        "target_variance": sim3.target_variance,
        "orientation_rule": "R_wc_aligned = rotation * R_wc_arm; scale is not applied",
    }


def evaluate_pair(
    reference: PoseSeries,
    arms: Mapping[str, PoseSeries],
) -> Tuple[Dict[str, object], Dict[str, List[Association]], Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    """Evaluate the fixed pair and return summary plus arrays for CSV audit."""

    if tuple(arms.keys()) != ARM_ORDER:
        raise ValueError("arms must be supplied in frozen orb32, r2d2_128 order")
    associations = {
        name: associate_reference_stamps(reference.stamps, arms[name])
        for name in ARM_ORDER
    }
    common_mask = np.asarray(
        [
            all(associations[name][index].valid for name in ARM_ORDER)
            for index in range(len(reference.stamps))
        ],
        dtype=bool,
    )
    common_indices = np.flatnonzero(common_mask)
    common_count = int(len(common_indices))
    coverage = float(common_count / len(reference.stamps))
    span_s = (
        float(reference.stamps[common_indices[-1]] - reference.stamps[common_indices[0]])
        if common_count >= 2
        else 0.0
    )
    rpe_pairs = np.asarray(
        [
            (index, index + RPE_DELTA_REFERENCE_STEPS)
            for index in range(
                0, len(reference.stamps) - RPE_DELTA_REFERENCE_STEPS
            )
            if common_mask[index]
            and common_mask[index + RPE_DELTA_REFERENCE_STEPS]
        ],
        dtype=int,
    ).reshape((-1, 2))

    threshold_pass = {
        "common_coverage_at_least_0p70": coverage >= MIN_COMMON_COVERAGE,
        "common_poses_at_least_30": common_count >= MIN_COMMON_POSES,
        "common_span_at_least_10s": span_s >= MIN_COMMON_SPAN_S,
        "rpe_pairs_at_least_10": len(rpe_pairs) >= MIN_RPE_PAIRS,
    }
    support_valid = all(threshold_pass.values())
    failure_reasons = [
        key for key, passed in threshold_pass.items() if not passed
    ]
    alignments: Dict[str, Sim3] = {}
    alignment_failures: Dict[str, str] = {}
    aligned_positions: Dict[str, np.ndarray] = {}
    aligned_quaternions: Dict[str, np.ndarray] = {}
    metrics: Optional[Dict[str, object]] = None

    if support_valid:
        reference_common = reference.positions[common_mask]
        for name in ARM_ORDER:
            arm_common_positions = np.asarray(
                [
                    associations[name][index].position
                    for index in common_indices
                ],
                dtype=np.float64,
            )
            arm_common_quaternions = np.asarray(
                [
                    associations[name][index].quaternion_xyzw
                    for index in common_indices
                ],
                dtype=np.float64,
            )
            try:
                sim3 = fit_umeyama_sim3(arm_common_positions, reference_common)
                alignments[name] = sim3
                aligned_positions[name] = apply_sim3_positions(
                    sim3, arm_common_positions
                )
                aligned_quaternions[name] = apply_sim3_orientations(
                    sim3, arm_common_quaternions
                )
            except (DegenerateAlignmentError, ValueError) as error:
                alignment_failures[name] = str(error)
        if alignment_failures:
            for name in ARM_ORDER:
                if name in alignment_failures:
                    failure_reasons.append("{}_sim3_degenerate".format(name))
        else:
            arm_metrics: Dict[str, object] = {}
            reference_deltas = (
                reference.positions[rpe_pairs[:, 1]]
                - reference.positions[rpe_pairs[:, 0]]
            )
            common_lookup = {
                int(reference_index): local_index
                for local_index, reference_index in enumerate(common_indices)
            }
            local_left = np.asarray(
                [common_lookup[int(pair[0])] for pair in rpe_pairs], dtype=int
            )
            local_right = np.asarray(
                [common_lookup[int(pair[1])] for pair in rpe_pairs], dtype=int
            )
            for name in ARM_ORDER:
                ape_errors = np.linalg.norm(
                    aligned_positions[name] - reference_common, axis=1
                )
                arm_deltas = (
                    aligned_positions[name][local_right]
                    - aligned_positions[name][local_left]
                )
                rpe_errors = np.linalg.norm(arm_deltas - reference_deltas, axis=1)
                arm_metrics[name] = {
                    "translation_ape": metric_summary(ape_errors),
                    "translation_rpe_1s_reference_grid": metric_summary(rpe_errors),
                }
            metrics = arm_metrics

    numeric_valid = support_valid and metrics is not None
    support = {
        "reference_count": len(reference.stamps),
        "per_arm_valid_reference_count": {
            name: int(sum(item.valid for item in associations[name]))
            for name in ARM_ORDER
        },
        "common_reference_indices": [int(value) for value in common_indices],
        "common_reference_count": common_count,
        "common_reference_coverage": coverage,
        "common_reference_span_s": span_s,
        "rpe_pair_count": int(len(rpe_pairs)),
        "rpe_pairs_reference_indices": rpe_pairs.tolist(),
        "threshold_pass": threshold_pass,
        "support_valid": support_valid,
        "numeric_claim_valid": numeric_valid,
        "failure_reasons": failure_reasons,
    }
    evaluation = {
        "support": support,
        "associations": {
            name: {
                "valid_reference_count": int(
                    sum(item.valid for item in associations[name])
                ),
                "method_histogram": association_histogram(associations[name]),
            }
            for name in ARM_ORDER
        },
        "alignments": (
            {name: sim3_json(alignments[name]) for name in ARM_ORDER}
            if numeric_valid
            else None
        ),
        "alignment_failures": alignment_failures or None,
        "metrics": metrics if numeric_valid else None,
    }

    # Expand common-only aligned arrays to reference-row arrays for audit CSV.
    expanded_positions: Dict[str, np.ndarray] = {}
    expanded_quaternions: Dict[str, np.ndarray] = {}
    if numeric_valid:
        for name in ARM_ORDER:
            position_rows = np.full((len(reference.stamps), 3), np.nan)
            quaternion_rows = np.full((len(reference.stamps), 4), np.nan)
            position_rows[common_mask] = aligned_positions[name]
            quaternion_rows[common_mask] = aligned_quaternions[name]
            expanded_positions[name] = position_rows
            expanded_quaternions[name] = quaternion_rows
    evaluation["_common_mask"] = common_mask
    evaluation["_rpe_pairs"] = rpe_pairs
    return evaluation, associations, expanded_positions, expanded_quaternions


def _series_or_error_audit(
    series: Optional[PoseSeries], error: Optional[TrajectoryValidationError]
) -> Dict[str, object]:
    if series is not None:
        return {"status": "VALID", **pose_series_audit(series)}
    assert error is not None
    return {
        "status": "INVALID",
        "error_code": error.code,
        "error": str(error),
    }


def build_invalid_arm_evaluation(
    reference: PoseSeries,
    arm_series: Mapping[str, Optional[PoseSeries]],
    arm_errors: Mapping[str, TrajectoryValidationError],
) -> Tuple[Dict[str, object], Dict[str, List[Association]], Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    associations: Dict[str, List[Association]] = {}
    for name in ARM_ORDER:
        series = arm_series.get(name)
        if series is not None:
            associations[name] = associate_reference_stamps(reference.stamps, series)
        else:
            associations[name] = [
                Association(
                    valid=False,
                    method="INPUT_INVALID",
                    position=None,
                    quaternion_xyzw=None,
                    left_stamp=None,
                    right_stamp=None,
                    bracket_gap_s=None,
                    alpha=None,
                )
                for _ in reference.stamps
            ]
    failure_reasons = ["{}_trajectory_invalid".format(name) for name in arm_errors]
    threshold_pass = {
        "common_coverage_at_least_0p70": False,
        "common_poses_at_least_30": False,
        "common_span_at_least_10s": False,
        "rpe_pairs_at_least_10": False,
    }
    evaluation: Dict[str, object] = {
        "support": {
            "reference_count": len(reference.stamps),
            "per_arm_valid_reference_count": {
                name: int(sum(item.valid for item in associations[name]))
                for name in ARM_ORDER
            },
            "common_reference_indices": [],
            "common_reference_count": 0,
            "common_reference_coverage": 0.0,
            "common_reference_span_s": 0.0,
            "rpe_pair_count": 0,
            "rpe_pairs_reference_indices": [],
            "threshold_pass": threshold_pass,
            "support_valid": False,
            "numeric_claim_valid": False,
            "failure_reasons": failure_reasons,
        },
        "associations": {
            name: {
                "valid_reference_count": int(
                    sum(item.valid for item in associations[name])
                ),
                "method_histogram": association_histogram(associations[name]),
            }
            for name in ARM_ORDER
        },
        "alignments": None,
        "alignment_failures": None,
        "metrics": None,
        "_common_mask": np.zeros(len(reference.stamps), dtype=bool),
        "_rpe_pairs": np.empty((0, 2), dtype=int),
    }
    return evaluation, associations, {}, {}


def _clean_evaluation(evaluation: Mapping[str, object]) -> Dict[str, object]:
    return {
        key: value
        for key, value in evaluation.items()
        if not key.startswith("_")
    }


def build_result(
    *,
    input_identities: Mapping[str, Mapping[str, object]],
    reference: PoseSeries,
    arm_series: Mapping[str, Optional[PoseSeries]],
    arm_errors: Mapping[str, TrajectoryValidationError],
    evaluation: Mapping[str, object],
) -> Dict[str, object]:
    support = evaluation["support"]
    assert isinstance(support, Mapping)
    numeric_valid = bool(support["numeric_claim_valid"])
    return_code = RC_NUMERIC_VALID if numeric_valid else RC_SCIENTIFIC_INVALID
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "NUMERIC_VALID" if numeric_valid else "SCIENTIFIC_INVALID",
        "return_code": return_code,
        "claim_boundary": {
            "comparison_label": COMPARISON_LABEL,
            "camera_only": True,
            "metric_alignment": "independent Sim(3) per arm on one identical common mask",
            "must_not_mix_with_metric_se3_vio": True,
            "reference_role": REFERENCE_ROLE,
            "reference_is_independent_ground_truth": False,
        },
        "protocol": {
            "arm_order": list(ARM_ORDER),
            "expected_reference_count": EXPECTED_REFERENCE_COUNT,
            "nominal_reference_rate_hz": NOMINAL_REFERENCE_RATE_HZ,
            "reference_timestamp_policy": "use each original reference timestamp exactly once",
            "association_policy": (
                "exact timestamp else unique adjacent two-sided keyframe bracket; "
                "timestamp-only selection"
            ),
            "forbidden_association": [
                "nearest-neighbour",
                "extrapolation",
                "reference reuse",
                "new evaluation timestamps",
                "one-sided mask",
                "reference-position-dependent or outcome-dependent matching",
            ],
            "max_keyframe_bracket_gap_s": float(MAX_BRACKET_GAP_S),
            "translation_interpolation": "linear",
            "orientation_interpolation": "normalized shortest-arc quaternion SLERP",
            "tum_pose_semantics": (
                "translation=camera centre in world; xyzw quaternion=R_wc"
            ),
            "common_mask": "intersection of reference validity for orb32 and r2d2_128",
            "alignment": "separate proper Umeyama Sim(3) per arm on identical common positions",
            "rpe": {
                "kind": "global-frame translational delta after the same Sim(3)",
                "delta_reference_grid_steps": RPE_DELTA_REFERENCE_STEPS,
                "nominal_delta_s": 1.0,
                "pairing": "adjacent original 1 Hz reference rows; never bridge a missing common row",
            },
            "numeric_claim_thresholds": {
                "min_common_coverage": MIN_COMMON_COVERAGE,
                "min_common_poses": MIN_COMMON_POSES,
                "min_common_span_s": MIN_COMMON_SPAN_S,
                "min_rpe_pairs": MIN_RPE_PAIRS,
            },
            "invalid_support_output_policy": "APE/RPE and Sim(3) values are null",
        },
        "inputs": {key: dict(value) for key, value in input_identities.items()},
        "trajectory_audit": {
            "reference_proxy": pose_series_audit(reference),
            **{
                name: _series_or_error_audit(
                    arm_series.get(name), arm_errors.get(name)
                )
                for name in ARM_ORDER
            },
        },
        "evaluation": _clean_evaluation(evaluation),
        "artifacts": {
            "result_json": RESULT_FILENAME,
            "metrics_csv": METRICS_FILENAME,
            "reference_support_audit_csv": AUDIT_FILENAME,
            "artifact_manifest_json": MANIFEST_FILENAME,
        },
    }


def _audit_fieldnames() -> List[str]:
    fields = [
        "reference_index",
        "reference_timestamp",
        "reference_tx",
        "reference_ty",
        "reference_tz",
        "reference_qx",
        "reference_qy",
        "reference_qz",
        "reference_qw",
    ]
    for name in ARM_ORDER:
        fields.extend(
            [
                "{}_method".format(name),
                "{}_valid".format(name),
                "{}_left_timestamp".format(name),
                "{}_right_timestamp".format(name),
                "{}_bracket_gap_s".format(name),
                "{}_alpha".format(name),
                "{}_tx".format(name),
                "{}_ty".format(name),
                "{}_tz".format(name),
                "{}_qx".format(name),
                "{}_qy".format(name),
                "{}_qz".format(name),
                "{}_qw".format(name),
                "{}_aligned_tx".format(name),
                "{}_aligned_ty".format(name),
                "{}_aligned_tz".format(name),
                "{}_aligned_qx".format(name),
                "{}_aligned_qy".format(name),
                "{}_aligned_qz".format(name),
                "{}_aligned_qw".format(name),
            ]
        )
    fields.extend(["common_valid", "rpe_pair_to_next", "reference_role"])
    return fields


def audit_rows(
    reference: PoseSeries,
    associations: Mapping[str, Sequence[Association]],
    aligned_positions: Mapping[str, np.ndarray],
    aligned_quaternions: Mapping[str, np.ndarray],
    evaluation: Mapping[str, object],
) -> List[Dict[str, object]]:
    common_mask = np.asarray(evaluation["_common_mask"], dtype=bool)
    rpe_pairs = np.asarray(evaluation["_rpe_pairs"], dtype=int).reshape((-1, 2))
    rpe_left = set(int(pair[0]) for pair in rpe_pairs)
    rows: List[Dict[str, object]] = []
    for index, stamp in enumerate(reference.stamps):
        row: Dict[str, object] = {
            "reference_index": index,
            "reference_timestamp": decimal_text(stamp),
            "reference_tx": float_text(float(reference.positions[index, 0])),
            "reference_ty": float_text(float(reference.positions[index, 1])),
            "reference_tz": float_text(float(reference.positions[index, 2])),
            "reference_qx": float_text(float(reference.quaternions_xyzw[index, 0])),
            "reference_qy": float_text(float(reference.quaternions_xyzw[index, 1])),
            "reference_qz": float_text(float(reference.quaternions_xyzw[index, 2])),
            "reference_qw": float_text(float(reference.quaternions_xyzw[index, 3])),
        }
        for name in ARM_ORDER:
            item = associations[name][index]
            position = item.position
            quaternion = item.quaternion_xyzw
            row.update(
                {
                    "{}_method".format(name): item.method,
                    "{}_valid".format(name): int(item.valid),
                    "{}_left_timestamp".format(name): (
                        decimal_text(item.left_stamp) if item.left_stamp is not None else ""
                    ),
                    "{}_right_timestamp".format(name): (
                        decimal_text(item.right_stamp) if item.right_stamp is not None else ""
                    ),
                    "{}_bracket_gap_s".format(name): (
                        decimal_text(item.bracket_gap_s)
                        if item.bracket_gap_s is not None
                        else ""
                    ),
                    "{}_alpha".format(name): float_text(item.alpha),
                }
            )
            for component_index, component in enumerate(("tx", "ty", "tz")):
                row["{}_{}".format(name, component)] = (
                    float_text(float(position[component_index]))
                    if position is not None
                    else ""
                )
            for component_index, component in enumerate(("qx", "qy", "qz", "qw")):
                row["{}_{}".format(name, component)] = (
                    float_text(float(quaternion[component_index]))
                    if quaternion is not None
                    else ""
                )
            aligned_position = aligned_positions.get(name)
            aligned_quaternion = aligned_quaternions.get(name)
            for component_index, component in enumerate(("tx", "ty", "tz")):
                row["{}_aligned_{}".format(name, component)] = (
                    float_text(float(aligned_position[index, component_index]))
                    if aligned_position is not None and common_mask[index]
                    else ""
                )
            for component_index, component in enumerate(("qx", "qy", "qz", "qw")):
                row["{}_aligned_{}".format(name, component)] = (
                    float_text(float(aligned_quaternion[index, component_index]))
                    if aligned_quaternion is not None and common_mask[index]
                    else ""
                )
        row["common_valid"] = int(common_mask[index])
        row["rpe_pair_to_next"] = int(index in rpe_left)
        row["reference_role"] = REFERENCE_ROLE
        rows.append(row)
    return rows


def metrics_rows(result: Mapping[str, object]) -> List[Dict[str, object]]:
    evaluation = result["evaluation"]
    assert isinstance(evaluation, Mapping)
    support = evaluation["support"]
    assert isinstance(support, Mapping)
    trajectory_audit = result["trajectory_audit"]
    assert isinstance(trajectory_audit, Mapping)
    metrics = evaluation.get("metrics")
    alignments = evaluation.get("alignments")
    rows: List[Dict[str, object]] = []
    for name in ARM_ORDER:
        arm_audit = trajectory_audit[name]
        assert isinstance(arm_audit, Mapping)
        arm_metrics = metrics.get(name) if isinstance(metrics, Mapping) else None
        alignment = alignments.get(name) if isinstance(alignments, Mapping) else None
        ape = (
            arm_metrics.get("translation_ape")
            if isinstance(arm_metrics, Mapping)
            else None
        )
        rpe = (
            arm_metrics.get("translation_rpe_1s_reference_grid")
            if isinstance(arm_metrics, Mapping)
            else None
        )
        rows.append(
            {
                "arm": name,
                "status": arm_audit.get("status"),
                "keyframe_count": arm_audit.get("data_row_count", ""),
                "valid_reference_count": support["per_arm_valid_reference_count"][name],
                "common_reference_count": support["common_reference_count"],
                "common_reference_coverage": float_text(
                    float(support["common_reference_coverage"])
                ),
                "common_reference_span_s": float_text(
                    float(support["common_reference_span_s"])
                ),
                "rpe_pair_count": support["rpe_pair_count"],
                "sim3_scale": (
                    float_text(float(alignment["scale"]))
                    if isinstance(alignment, Mapping)
                    else ""
                ),
                "ape_rmse_m": (
                    float_text(float(ape["rmse_m"])) if isinstance(ape, Mapping) else ""
                ),
                "ape_median_m": (
                    float_text(float(ape["median_m"])) if isinstance(ape, Mapping) else ""
                ),
                "ape_max_m": (
                    float_text(float(ape["max_m"])) if isinstance(ape, Mapping) else ""
                ),
                "rpe_rmse_m": (
                    float_text(float(rpe["rmse_m"])) if isinstance(rpe, Mapping) else ""
                ),
                "rpe_median_m": (
                    float_text(float(rpe["median_m"])) if isinstance(rpe, Mapping) else ""
                ),
                "rpe_max_m": (
                    float_text(float(rpe["max_m"])) if isinstance(rpe, Mapping) else ""
                ),
                "numeric_claim_valid": int(bool(support["numeric_claim_valid"])),
                "comparison_label": COMPARISON_LABEL,
                "reference_role": REFERENCE_ROLE,
            }
        )
    return rows


def encode_csv(fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> bytes:
    import io

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(fieldnames),
        extrasaction="raise",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(dict(row))
    return stream.getvalue().encode("utf-8")


def publish_no_clobber(
    output_dir: Path,
    result: Mapping[str, object],
    metric_rows_value: Sequence[Mapping[str, object]],
    audit_rows_value: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    absolute_output = output_dir.expanduser().resolve(strict=False)
    if absolute_output.exists() or absolute_output.is_symlink():
        raise ContractError("no-clobber output already exists: {}".format(absolute_output))
    result_bytes = canonical_json_bytes(result)
    metric_fieldnames = [
        "arm",
        "status",
        "keyframe_count",
        "valid_reference_count",
        "common_reference_count",
        "common_reference_coverage",
        "common_reference_span_s",
        "rpe_pair_count",
        "sim3_scale",
        "ape_rmse_m",
        "ape_median_m",
        "ape_max_m",
        "rpe_rmse_m",
        "rpe_median_m",
        "rpe_max_m",
        "numeric_claim_valid",
        "comparison_label",
        "reference_role",
    ]
    metrics_bytes = encode_csv(metric_fieldnames, metric_rows_value)
    audit_bytes = encode_csv(_audit_fieldnames(), audit_rows_value)

    absolute_output.mkdir(parents=True, exist_ok=False)
    payloads = {
        RESULT_FILENAME: result_bytes,
        METRICS_FILENAME: metrics_bytes,
        AUDIT_FILENAME: audit_bytes,
    }
    for filename, payload in payloads.items():
        with (absolute_output / filename).open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "files": {
            filename: {
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
            for filename, payload in sorted(payloads.items())
        },
    }
    manifest_bytes = canonical_json_bytes(manifest)
    with (absolute_output / MANIFEST_FILENAME).open("xb") as stream:
        stream.write(manifest_bytes)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "output_dir": str(absolute_output),
        "result": str(absolute_output / RESULT_FILENAME),
        "manifest": str(absolute_output / MANIFEST_FILENAME),
    }


def _same_identity(left: Mapping[str, object], right: Mapping[str, object]) -> bool:
    return (
        left.get("path") == right.get("path")
        and left.get("sha256") == right.get("sha256")
        and left.get("size_bytes") == right.get("size_bytes")
    )


def run_formal_evaluation(
    reference_path: Path,
    orb32_path: Path,
    r2d2_path: Path,
    output_dir: Path,
) -> Tuple[int, Dict[str, object]]:
    output_absolute = output_dir.expanduser().resolve(strict=False)
    if output_absolute.exists() or output_absolute.is_symlink():
        raise ContractError("no-clobber output already exists: {}".format(output_absolute))

    paths = {
        "reference_proxy": require_regular_input(reference_path, "reference proxy"),
        "orb32_keyframe_tum": require_regular_input(orb32_path, "orb32 trajectory"),
        "r2d2_128_keyframe_tum": require_regular_input(r2d2_path, "r2d2 trajectory"),
        "evaluator": require_regular_input(Path(__file__), "evaluator"),
        "preregistration": require_regular_input(PREREGISTRATION, "preregistration"),
    }
    input_identities = {name: file_identity(path) for name, path in paths.items()}

    try:
        reference = load_strict_tum(paths["reference_proxy"], expected_count=EXPECTED_REFERENCE_COUNT)
    except (TrajectoryValidationError, OSError, UnicodeError) as error:
        raise ContractError("frozen reference proxy is invalid: {}".format(error)) from error

    arm_series: Dict[str, Optional[PoseSeries]] = {}
    arm_errors: Dict[str, TrajectoryValidationError] = {}
    arm_paths = {
        "orb32": paths["orb32_keyframe_tum"],
        "r2d2_128": paths["r2d2_128_keyframe_tum"],
    }
    for name in ARM_ORDER:
        try:
            arm_series[name] = load_strict_tum(arm_paths[name], expected_count=None)
        except TrajectoryValidationError as error:
            arm_series[name] = None
            arm_errors[name] = error
        except (OSError, UnicodeError) as error:
            arm_series[name] = None
            arm_errors[name] = TrajectoryValidationError(
                "TRAJECTORY_READ_ERROR",
                "{} could not be read as UTF-8 TUM: {}".format(arm_paths[name], error),
            )

    if arm_errors:
        evaluation, associations, aligned_positions, aligned_quaternions = (
            build_invalid_arm_evaluation(reference, arm_series, arm_errors)
        )
    else:
        valid_arms = {
            name: arm_series[name] for name in ARM_ORDER
        }
        assert all(series is not None for series in valid_arms.values())
        evaluation, associations, aligned_positions, aligned_quaternions = evaluate_pair(
            reference,
            {name: valid_arms[name] for name in ARM_ORDER},  # type: ignore[arg-type]
        )

    # Fail closed if an input changed between hashing/parsing and publication.
    for name, path in paths.items():
        observed = file_identity(path)
        if not _same_identity(input_identities[name], observed):
            raise ContractError("input changed during evaluation: {}".format(name))

    result = build_result(
        input_identities=input_identities,
        reference=reference,
        arm_series=arm_series,
        arm_errors=arm_errors,
        evaluation=evaluation,
    )
    rows = audit_rows(
        reference,
        associations,
        aligned_positions,
        aligned_quaternions,
        evaluation,
    )
    publication = publish_no_clobber(
        output_absolute,
        result,
        metrics_rows(result),
        rows,
    )
    return int(result["return_code"]), publication


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate official AnyFeature-VSLAM orb32 and R2D2 keyframe TUM "
            "files on the frozen A02 camera-only common support."
        )
    )
    parser.add_argument("--reference-proxy", type=Path, required=True)
    parser.add_argument("--orb32-trajectory", type=Path, required=True)
    parser.add_argument("--r2d2-trajectory", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return_code, publication = run_formal_evaluation(
            args.reference_proxy,
            args.orb32_trajectory,
            args.r2d2_trajectory,
            args.output_dir,
        )
    except (ContractError, OSError) as error:
        document = {
            "schema_version": SCHEMA_VERSION,
            "status": "CONTRACT_BLOCKED",
            "return_code": RC_CONTRACT_BLOCKED,
            "error": str(error),
        }
        sys.stdout.buffer.write(canonical_json_bytes(document))
        return RC_CONTRACT_BLOCKED
    document = {
        "schema_version": SCHEMA_VERSION,
        "status": "NUMERIC_VALID" if return_code == 0 else "SCIENTIFIC_INVALID",
        "return_code": return_code,
        **publication,
    }
    sys.stdout.buffer.write(canonical_json_bytes(document))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
