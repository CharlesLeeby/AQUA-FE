#!/usr/bin/env python3
"""Deterministic reference-grid trajectory evaluation primitives.

The module is ROS-independent so timestamp, interpolation, common-support,
and RPE contracts can be tested with small synthetic trajectories.
Quaternions use the TUM order ``[qx, qy, qz, qw]``.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class SampleAudit:
    raw_count: int
    finite_count: int
    unique_count: int
    rejected_nonfinite_count: int
    duplicate_count: int


@dataclass(frozen=True)
class ResampledTrajectory:
    stamps: np.ndarray
    positions: np.ndarray
    valid: np.ndarray
    bracket_gaps_s: np.ndarray
    quaternions: np.ndarray | None = None
    audit: SampleAudit | None = None
    rejection_reasons: np.ndarray | None = None


def prepare_reference_samples(
    stamps: Sequence[float] | np.ndarray,
    positions: Sequence[Sequence[float]] | np.ndarray,
    quaternions: Sequence[Sequence[float]] | np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, SampleAudit]:
    """Clean reference samples while rejecting conflicting duplicate poses."""

    stamp_arr, position_arr, quaternion_arr = _sample_arrays(
        stamps, positions, quaternions
    )
    raw_count = len(stamp_arr)

    finite = np.isfinite(stamp_arr) & np.all(np.isfinite(position_arr), axis=1)
    if quaternion_arr is not None:
        finite &= np.all(np.isfinite(quaternion_arr), axis=1)
        finite &= np.linalg.norm(quaternion_arr, axis=1) > 1e-12

    stamp_arr = stamp_arr[finite]
    position_arr = position_arr[finite]
    if quaternion_arr is not None:
        quaternion_arr = quaternion_arr[finite]

    order = np.argsort(stamp_arr, kind="mergesort")
    stamp_arr = stamp_arr[order]
    position_arr = position_arr[order]
    if quaternion_arr is not None:
        quaternion_arr = quaternion_arr[order]

    duplicate_count = 0
    if len(stamp_arr):
        keep = np.ones(len(stamp_arr), dtype=bool)
        for index in range(1, len(stamp_arr)):
            if stamp_arr[index] != stamp_arr[index - 1]:
                continue
            duplicate_count += 1
            same_position = np.allclose(
                position_arr[index], position_arr[index - 1], rtol=0.0, atol=1e-12
            )
            same_orientation = True
            if quaternion_arr is not None:
                current = quaternion_arr[index] / np.linalg.norm(quaternion_arr[index])
                previous = quaternion_arr[index - 1] / np.linalg.norm(
                    quaternion_arr[index - 1]
                )
                same_orientation = bool(
                    np.allclose(current, previous, rtol=0.0, atol=1e-12)
                    or np.allclose(current, -previous, rtol=0.0, atol=1e-12)
                )
            if not same_position or not same_orientation:
                raise ValueError(
                    f"conflicting reference poses at duplicate timestamp {stamp_arr[index]:.17g}"
                )
            keep[index] = False
        stamp_arr = stamp_arr[keep]
        position_arr = position_arr[keep]
        if quaternion_arr is not None:
            quaternion_arr = quaternion_arr[keep]
            quaternion_arr = quaternion_arr / np.linalg.norm(
                quaternion_arr, axis=1, keepdims=True
            )

    audit = SampleAudit(
        raw_count=raw_count,
        finite_count=int(np.sum(finite)),
        unique_count=len(stamp_arr),
        rejected_nonfinite_count=int(raw_count - np.sum(finite)),
        duplicate_count=duplicate_count,
    )
    return stamp_arr, position_arr, quaternion_arr, audit


def validate_estimate_samples(
    stamps: Sequence[float] | np.ndarray,
    positions: Sequence[Sequence[float]] | np.ndarray,
    quaternions: Sequence[Sequence[float]] | np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, SampleAudit]:
    """Validate estimate samples without sorting, filtering, or deduplicating."""

    stamp_arr, position_arr, quaternion_arr = _sample_arrays(
        stamps, positions, quaternions
    )
    finite = np.isfinite(stamp_arr) & np.all(np.isfinite(position_arr), axis=1)
    if quaternion_arr is not None:
        finite &= np.all(np.isfinite(quaternion_arr), axis=1)
        finite &= np.linalg.norm(quaternion_arr, axis=1) > 1e-12
    if not np.all(finite):
        raise ValueError("estimate trajectory contains non-finite or invalid pose data")
    if len(stamp_arr) > 1 and np.any(np.diff(stamp_arr) <= 0.0):
        raise ValueError("estimate timestamps must be strictly increasing")
    if quaternion_arr is not None:
        quaternion_arr = quaternion_arr / np.linalg.norm(
            quaternion_arr, axis=1, keepdims=True
        )
    audit = SampleAudit(
        raw_count=len(stamp_arr),
        finite_count=len(stamp_arr),
        unique_count=len(stamp_arr),
        rejected_nonfinite_count=0,
        duplicate_count=0,
    )
    return stamp_arr, position_arr, quaternion_arr, audit


def _sample_arrays(
    stamps: Sequence[float] | np.ndarray,
    positions: Sequence[Sequence[float]] | np.ndarray,
    quaternions: Sequence[Sequence[float]] | np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    # Keep epoch-scale timestamps above float64 precision.  Positions remain
    # float64; only timestamp ordering/interpolation needs extended precision.
    stamp_arr = np.asarray(stamps, dtype=np.longdouble)
    position_arr = np.asarray(positions, dtype=float)
    if stamp_arr.ndim != 1:
        raise ValueError("stamps must be one-dimensional")
    if position_arr.shape != (len(stamp_arr), 3):
        raise ValueError("positions must have shape (N, 3)")
    quaternion_arr: np.ndarray | None = None
    if quaternions is not None:
        quaternion_arr = np.asarray(quaternions, dtype=float)
        if quaternion_arr.shape != (len(stamp_arr), 4):
            raise ValueError("quaternions must have shape (N, 4)")
    return stamp_arr, position_arr, quaternion_arr


def make_uniform_grid(start_s: float, end_s: float, rate_hz: float) -> np.ndarray:
    """Create an inclusive grid anchored exactly at ``start_s``."""

    if not all(math.isfinite(value) for value in (start_s, end_s, rate_hz)):
        raise ValueError("grid arguments must be finite")
    if rate_hz <= 0.0:
        raise ValueError("rate_hz must be positive")
    if end_s < start_s:
        raise ValueError("end_s must be greater than or equal to start_s")
    start = np.longdouble(str(start_s))
    end = np.longdouble(str(end_s))
    rate = np.longdouble(str(rate_hz))
    count = int(np.floor((end - start) * rate + np.longdouble("1e-9"))) + 1
    grid = start + np.arange(count, dtype=np.longdouble) / rate
    return grid[grid <= end + np.longdouble("1e-9")]


def choose_evaluation_rate(
    nominal_reference_rate_hz: float,
    allowed_rates_hz: Sequence[float] = (1.0, 2.0, 5.0, 10.0),
) -> float:
    """Choose the largest preregistered rate not above the reference rate."""

    if not math.isfinite(nominal_reference_rate_hz) or nominal_reference_rate_hz <= 0.0:
        raise ValueError("nominal_reference_rate_hz must be positive and finite")
    allowed = sorted(
        {
            float(rate)
            for rate in allowed_rates_hz
            if math.isfinite(float(rate)) and float(rate) > 0.0
        }
    )
    candidates = [rate for rate in allowed if rate <= nominal_reference_rate_hz + 1e-12]
    if not candidates:
        raise ValueError("reference rate is below the minimum allowed evaluation rate")
    return candidates[-1]


def legacy_unique_assignment(
    estimate_stamps: Sequence[float] | np.ndarray,
    reference_stamps: Sequence[float] | np.ndarray,
    max_match_dt_s: float = 0.0,
) -> np.ndarray:
    """Globally match sorted timestamps one-to-one with deterministic ties.

    The objective first maximizes pair count, then minimizes total absolute
    timestamp error, then prefers earlier reference and estimate indices.
    Estimate timestamps outside the reference range are excluded, matching the
    historical evaluator's support convention.
    """

    estimates_all = np.asarray(estimate_stamps, dtype=np.longdouble)
    references = np.asarray(reference_stamps, dtype=np.longdouble)
    if estimates_all.ndim != 1 or references.ndim != 1:
        raise ValueError("timestamp arrays must be one-dimensional")
    if not np.all(np.isfinite(estimates_all)) or not np.all(np.isfinite(references)):
        raise ValueError("timestamp arrays must be finite")
    if np.any(np.diff(estimates_all) <= 0.0) or np.any(np.diff(references) <= 0.0):
        raise ValueError("timestamp arrays must be strictly increasing")
    if not len(estimates_all) or not len(references):
        return np.empty((0, 2), dtype=int)

    eligible_indices = np.flatnonzero(
        (estimates_all >= references[0]) & (estimates_all <= references[-1])
    )
    estimates = estimates_all[eligible_indices]
    reference_start = max(0, int(np.searchsorted(references, estimates[0], side="left")) - 1)
    reference_end = min(
        len(references), int(np.searchsorted(references, estimates[-1], side="right")) + 1
    )
    reference_indices = np.arange(reference_start, reference_end, dtype=int)
    references_local = references[reference_indices]
    rows, columns = len(estimates), len(references_local)
    counts = np.zeros((rows + 1, columns + 1), dtype=np.int32)
    costs = np.zeros((rows + 1, columns + 1), dtype=float)
    reference_sums = np.zeros((rows + 1, columns + 1), dtype=np.int64)
    estimate_sums = np.zeros((rows + 1, columns + 1), dtype=np.int64)
    actions = np.zeros((rows + 1, columns + 1), dtype=np.int8)

    for row in range(1, rows + 1):
        for column in range(1, columns + 1):
            candidates: list[tuple[tuple[float, ...], int, int, float, int, int]] = []
            for previous_row, previous_column, action, priority in (
                (row - 1, column, 1, 1),
                (row, column - 1, 2, 0),
            ):
                count = int(counts[previous_row, previous_column])
                cost = float(costs[previous_row, previous_column])
                ref_sum = int(reference_sums[previous_row, previous_column])
                est_sum = int(estimate_sums[previous_row, previous_column])
                score = (count, -cost, -ref_sum, -est_sum, priority)
                candidates.append((score, action, count, cost, ref_sum, est_sum))

            delta = abs(float(estimates[row - 1] - references_local[column - 1]))
            if max_match_dt_s <= 0.0 or delta <= max_match_dt_s:
                count = int(counts[row - 1, column - 1]) + 1
                cost = float(costs[row - 1, column - 1]) + delta
                ref_sum = int(reference_sums[row - 1, column - 1]) + column - 1
                est_sum = int(estimate_sums[row - 1, column - 1]) + row - 1
                score = (count, -cost, -ref_sum, -est_sum, 2)
                candidates.append((score, 3, count, cost, ref_sum, est_sum))

            _, action, count, cost, ref_sum, est_sum = max(
                candidates, key=lambda candidate: candidate[0]
            )
            counts[row, column] = count
            costs[row, column] = cost
            reference_sums[row, column] = ref_sum
            estimate_sums[row, column] = est_sum
            actions[row, column] = action

    pairs: list[tuple[int, int]] = []
    row, column = rows, columns
    while row > 0 or column > 0:
        action = int(actions[row, column]) if row > 0 and column > 0 else (1 if row > 0 else 2)
        if action == 3:
            pairs.append(
                (int(eligible_indices[row - 1]), int(reference_indices[column - 1]))
            )
            row -= 1
            column -= 1
        elif action == 1:
            row -= 1
        else:
            column -= 1
    pairs.reverse()
    return np.asarray(pairs, dtype=int).reshape((-1, 2))


def slerp_xyzw(q0: np.ndarray, q1: np.ndarray, alpha: float) -> np.ndarray:
    """Spherical interpolation with deterministic shortest-path handling."""

    q0 = np.asarray(q0, dtype=float)
    q1 = np.asarray(q1, dtype=float)
    q0 = q0 / np.linalg.norm(q0)
    q1 = q1 / np.linalg.norm(q1)
    dot = float(np.dot(q0, q1))
    if dot < 0.0:
        q1 = -q1
        dot = -dot
    dot = float(np.clip(dot, -1.0, 1.0))
    if dot > 0.9995:
        result = q0 + alpha * (q1 - q0)
        return result / np.linalg.norm(result)
    angle = math.acos(dot)
    sin_angle = math.sin(angle)
    left = math.sin((1.0 - alpha) * angle) / sin_angle
    right = math.sin(alpha * angle) / sin_angle
    result = left * q0 + right * q1
    return result / np.linalg.norm(result)


def quaternion_xyzw_to_rotation(quaternion: np.ndarray) -> np.ndarray:
    """Convert one normalized-or-normalizable xyzw quaternion to a matrix."""

    qx, qy, qz, qw = np.asarray(quaternion, dtype=float)
    norm = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw)
    if not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("quaternion must be finite and non-zero")
    qx, qy, qz, qw = qx / norm, qy / norm, qz / norm, qw / norm
    return np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ],
        dtype=float,
    )


def rotation_to_quaternion_xyzw(rotation: np.ndarray) -> np.ndarray:
    """Convert a proper rotation matrix to a deterministic xyzw quaternion."""

    matrix = np.asarray(rotation, dtype=float)
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
            scale = math.sqrt(1.0 + matrix[0, 0] - matrix[1, 1] - matrix[2, 2]) * 2.0
            qw = (matrix[2, 1] - matrix[1, 2]) / scale
            qx = 0.25 * scale
            qy = (matrix[0, 1] + matrix[1, 0]) / scale
            qz = (matrix[0, 2] + matrix[2, 0]) / scale
        elif index == 1:
            scale = math.sqrt(1.0 + matrix[1, 1] - matrix[0, 0] - matrix[2, 2]) * 2.0
            qw = (matrix[0, 2] - matrix[2, 0]) / scale
            qx = (matrix[0, 1] + matrix[1, 0]) / scale
            qy = 0.25 * scale
            qz = (matrix[1, 2] + matrix[2, 1]) / scale
        else:
            scale = math.sqrt(1.0 + matrix[2, 2] - matrix[0, 0] - matrix[1, 1]) * 2.0
            qw = (matrix[1, 0] - matrix[0, 1]) / scale
            qx = (matrix[0, 2] + matrix[2, 0]) / scale
            qy = (matrix[1, 2] + matrix[2, 1]) / scale
            qz = 0.25 * scale
    quaternion = np.array([qx, qy, qz, qw], dtype=float)
    quaternion /= np.linalg.norm(quaternion)
    if quaternion[3] < 0.0:
        quaternion = -quaternion
    return quaternion


def transform_body_poses_to_sensor(
    body_positions: Sequence[Sequence[float]] | np.ndarray,
    body_quaternions_xyzw: Sequence[Sequence[float]] | np.ndarray,
    body_t_sensor: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Compose world_T_body with body_T_sensor for every pose."""

    positions = np.asarray(body_positions, dtype=float)
    quaternions = np.asarray(body_quaternions_xyzw, dtype=float)
    transform = np.asarray(body_t_sensor, dtype=float)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("body_positions must have shape (N, 3)")
    if quaternions.shape != (len(positions), 4):
        raise ValueError("body_quaternions_xyzw must have shape (N, 4)")
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise ValueError("body_t_sensor must be a finite 4x4 matrix")
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-12):
        raise ValueError("body_t_sensor must be homogeneous")

    sensor_positions = np.empty_like(positions)
    sensor_quaternions = np.empty_like(quaternions)
    rotation_body_sensor = transform[:3, :3]
    translation_body_sensor = transform[:3, 3]
    for index, (position, quaternion) in enumerate(zip(positions, quaternions)):
        rotation_world_body = quaternion_xyzw_to_rotation(quaternion)
        sensor_positions[index] = position + rotation_world_body @ translation_body_sensor
        sensor_quaternions[index] = rotation_to_quaternion_xyzw(
            rotation_world_body @ rotation_body_sensor
        )
    return sensor_positions, sensor_quaternions


def resample_trajectory(
    stamps: Sequence[float] | np.ndarray,
    positions: Sequence[Sequence[float]] | np.ndarray,
    grid_stamps: Sequence[float] | np.ndarray,
    max_interp_gap_s: float,
    quaternions: Sequence[Sequence[float]] | np.ndarray | None = None,
    *,
    sample_kind: str,
) -> ResampledTrajectory:
    """Interpolate a trajectory on a fixed grid and expose its validity mask."""

    if sample_kind == "reference":
        sample_stamps, sample_positions, sample_quaternions, audit = (
            prepare_reference_samples(stamps, positions, quaternions)
        )
    elif sample_kind == "estimate":
        sample_stamps, sample_positions, sample_quaternions, audit = (
            validate_estimate_samples(stamps, positions, quaternions)
        )
    else:
        raise ValueError("sample_kind must be 'reference' or 'estimate'")
    grid = np.asarray(grid_stamps, dtype=np.longdouble)
    if grid.ndim != 1 or not np.all(np.isfinite(grid)):
        raise ValueError("grid_stamps must be a finite one-dimensional array")

    output_positions = np.full((len(grid), 3), np.nan, dtype=float)
    output_quaternions = (
        np.full((len(grid), 4), np.nan, dtype=float)
        if sample_quaternions is not None
        else None
    )
    valid = np.zeros(len(grid), dtype=bool)
    bracket_gaps = np.full(len(grid), np.nan, dtype=float)
    rejection_reasons = np.full(
        len(grid), "NO_SAMPLES" if not len(sample_stamps) else "OUT_OF_RANGE", dtype=object
    )

    for grid_index, stamp in enumerate(grid):
        right = int(np.searchsorted(sample_stamps, stamp, side="left"))
        if right < len(sample_stamps) and abs(sample_stamps[right] - stamp) <= np.longdouble(
            "1e-12"
        ):
            output_positions[grid_index] = sample_positions[right]
            if output_quaternions is not None and sample_quaternions is not None:
                output_quaternions[grid_index] = sample_quaternions[right]
            valid[grid_index] = True
            bracket_gaps[grid_index] = 0.0
            rejection_reasons[grid_index] = "EXACT"
            continue
        if right == 0 or right >= len(sample_stamps):
            continue

        left = right - 1
        gap = float(sample_stamps[right] - sample_stamps[left])
        bracket_gaps[grid_index] = gap
        if gap <= 0.0 or (max_interp_gap_s > 0.0 and gap > max_interp_gap_s):
            rejection_reasons[grid_index] = "GAP_EXCEEDED"
            continue
        alpha = float((stamp - sample_stamps[left]) / gap)
        output_positions[grid_index] = (
            (1.0 - alpha) * sample_positions[left] + alpha * sample_positions[right]
        )
        if output_quaternions is not None and sample_quaternions is not None:
            output_quaternions[grid_index] = slerp_xyzw(
                sample_quaternions[left], sample_quaternions[right], alpha
            )
        valid[grid_index] = True
        rejection_reasons[grid_index] = "INTERPOLATED"

    return ResampledTrajectory(
        stamps=grid,
        positions=output_positions,
        valid=valid,
        bracket_gaps_s=bracket_gaps,
        quaternions=output_quaternions,
        audit=audit,
        rejection_reasons=rejection_reasons,
    )


def rejection_histogram(trajectory: ResampledTrajectory) -> dict[str, int]:
    if trajectory.rejection_reasons is None:
        return {}
    values, counts = np.unique(trajectory.rejection_reasons, return_counts=True)
    return {str(value): int(count) for value, count in zip(values, counts)}


def common_valid_mask(
    reference: ResampledTrajectory, arms: Sequence[ResampledTrajectory]
) -> np.ndarray:
    """Return the intersection of reference and arm validity masks."""

    mask = reference.valid.copy()
    for arm in arms:
        if len(arm.stamps) != len(reference.stamps) or not np.array_equal(
            arm.stamps, reference.stamps
        ):
            raise ValueError("all trajectories must use the same grid")
        mask &= arm.valid
    return mask


def segment_ids(
    stamps: Sequence[float] | np.ndarray,
    valid_mask: Sequence[bool] | np.ndarray,
    max_segment_gap_s: float,
) -> np.ndarray:
    """Label contiguous valid grid segments; invalid entries receive ``-1``."""

    stamp_arr = np.asarray(stamps, dtype=np.longdouble)
    mask = np.asarray(valid_mask, dtype=bool)
    if stamp_arr.shape != mask.shape:
        raise ValueError("stamps and valid_mask must have matching shapes")
    labels = np.full(len(stamp_arr), -1, dtype=int)
    segment = -1
    previous_index: int | None = None
    for index in np.flatnonzero(mask):
        starts_segment = previous_index is None or index != previous_index + 1
        if previous_index is not None and max_segment_gap_s > 0.0:
            starts_segment |= (
                float(stamp_arr[index] - stamp_arr[previous_index])
                > max_segment_gap_s
            )
        if starts_segment:
            segment += 1
        labels[index] = segment
        previous_index = int(index)
    return labels


def strict_delta_pairs(
    stamps: Sequence[float] | np.ndarray,
    valid_mask: Sequence[bool] | np.ndarray,
    segments: Sequence[int] | np.ndarray,
    delta_s: float,
    tolerance_s: float = 1e-9,
) -> np.ndarray:
    """Pair valid poses at an exact time delta within the same segment."""

    stamp_arr = np.asarray(stamps, dtype=np.longdouble)
    mask = np.asarray(valid_mask, dtype=bool)
    segment_arr = np.asarray(segments, dtype=int)
    if stamp_arr.shape != mask.shape or stamp_arr.shape != segment_arr.shape:
        raise ValueError("stamps, valid_mask, and segments must match")
    pairs: list[tuple[int, int]] = []
    for left in np.flatnonzero(mask):
        target_stamp = stamp_arr[left] + np.longdouble(str(delta_s))
        right = int(np.searchsorted(stamp_arr, target_stamp, side="left"))
        if right >= len(stamp_arr):
            continue
        if abs(stamp_arr[right] - target_stamp) > np.longdouble(str(tolerance_s)):
            continue
        if not mask[right] or segment_arr[right] != segment_arr[left]:
            continue
        pairs.append((int(left), right))
    return np.asarray(pairs, dtype=int).reshape((-1, 2))


def align_se3_positions(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Rigidly align source positions to target positions without scale change."""

    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("source and target must both have shape (N, 3)")
    if len(source) < 3:
        raise ValueError("at least three positions are required for alignment")
    src_centered = source - source.mean(axis=0)
    dst_centered = target - target.mean(axis=0)
    u_mat, _, vt_mat = np.linalg.svd(src_centered.T @ dst_centered)
    rotation = vt_mat.T @ u_mat.T
    if np.linalg.det(rotation) < 0:
        vt_mat[-1] *= -1
        rotation = vt_mat.T @ u_mat.T
    translation = target.mean(axis=0) - rotation @ source.mean(axis=0)
    return (rotation @ source.T).T + translation


def evaluate_common_translation(
    reference: ResampledTrajectory,
    arms: Mapping[str, ResampledTrajectory],
    *,
    window_start_s: float,
    window_end_s: float,
    max_segment_gap_s: float,
    rpe_delta_s: float = 1.0,
    min_ape_poses: int = 30,
    min_ape_span_s: float = 10.0,
    min_common_coverage: float = 0.70,
    min_rpe_pairs: int = 10,
) -> dict[str, object]:
    """Evaluate several arms on one contrast-specific common grid mask."""

    if window_end_s <= window_start_s:
        raise ValueError("window_end_s must be greater than window_start_s")
    if not arms:
        raise ValueError("at least one arm is required")
    mask = common_valid_mask(reference, list(arms.values()))
    valid_indices = np.flatnonzero(mask)
    matched_count = int(len(valid_indices))
    common_span_s = (
        float(reference.stamps[valid_indices[-1]] - reference.stamps[valid_indices[0]])
        if matched_count >= 2
        else 0.0
    )
    common_coverage = float(matched_count / len(reference.stamps)) if len(reference.stamps) else 0.0
    segments = segment_ids(reference.stamps, mask, max_segment_gap_s)
    rpe_pairs = strict_delta_pairs(
        reference.stamps, mask, segments, delta_s=rpe_delta_s
    )
    ape_valid = (
        matched_count >= min_ape_poses
        and common_span_s >= min_ape_span_s
        and common_coverage >= min_common_coverage
    )
    rpe_valid = len(rpe_pairs) >= min_rpe_pairs

    arm_metrics: dict[str, dict[str, float | int]] = {}
    for name, arm in arms.items():
        metrics: dict[str, float | int] = {
            "matched_count": matched_count,
            "rpe_pairs": int(len(rpe_pairs)),
        }
        if matched_count >= 3:
            reference_positions = reference.positions[mask]
            arm_positions = arm.positions[mask]
            aligned = align_se3_positions(arm_positions, reference_positions)
            ape = np.linalg.norm(aligned - reference_positions, axis=1)
            metrics.update(
                {
                    "ape_rmse_m": float(np.sqrt(np.mean(ape**2))),
                    "ape_median_m": float(np.median(ape)),
                    "ape_max_m": float(np.max(ape)),
                }
            )
            if len(rpe_pairs):
                aligned_full = np.full_like(reference.positions, np.nan, dtype=float)
                aligned_full[mask] = aligned
                reference_delta = (
                    reference.positions[rpe_pairs[:, 1]]
                    - reference.positions[rpe_pairs[:, 0]]
                )
                estimated_delta = (
                    aligned_full[rpe_pairs[:, 1]]
                    - aligned_full[rpe_pairs[:, 0]]
                )
                rpe = np.linalg.norm(estimated_delta - reference_delta, axis=1)
                metrics.update(
                    {
                        "rpe_rmse_m": float(np.sqrt(np.mean(rpe**2))),
                        "rpe_median_m": float(np.median(rpe)),
                        "rpe_max_m": float(np.max(rpe)),
                    }
                )
        arm_metrics[name] = metrics

    return {
        "support": {
            "grid_count": int(len(reference.stamps)),
            "matched_count": matched_count,
            "common_span_s": common_span_s,
            "common_coverage": common_coverage,
            "segment_count": int(np.max(segments) + 1) if np.any(segments >= 0) else 0,
            "rpe_pairs": int(len(rpe_pairs)),
            "ape_valid": bool(ape_valid),
            "rpe_valid": bool(rpe_valid),
            "window_duration_s": float(window_end_s - window_start_s),
        },
        "common_mask": mask,
        "segments": segments,
        "rpe_pair_indices": rpe_pairs,
        "arms": arm_metrics,
    }
