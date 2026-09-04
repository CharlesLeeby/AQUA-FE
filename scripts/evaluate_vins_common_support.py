#!/usr/bin/env python3
"""Evaluate multiple VINS trajectories on one reference-grid support mask."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
from typing import Sequence

import numpy as np

try:
    from trajectory_eval_core import (
        ResampledTrajectory,
        align_se3_positions,
        choose_evaluation_rate,
        evaluate_common_translation,
        legacy_unique_assignment,
        make_uniform_grid,
        prepare_reference_samples,
        rejection_histogram,
        resample_trajectory,
        transform_body_poses_to_sensor,
        validate_estimate_samples,
    )
except ModuleNotFoundError:
    from scripts.trajectory_eval_core import (
        ResampledTrajectory,
        align_se3_positions,
        choose_evaluation_rate,
        evaluate_common_translation,
        legacy_unique_assignment,
        make_uniform_grid,
        prepare_reference_samples,
        rejection_histogram,
        resample_trajectory,
        transform_body_poses_to_sensor,
        validate_estimate_samples,
    )


@dataclass(frozen=True)
class PoseSeries:
    stamps: np.ndarray
    positions: np.ndarray
    quaternions_xyzw: np.ndarray | None


def parse_nanosecond_timestamp(raw: str) -> np.longdouble:
    """Parse an integer nanosecond stamp without an intermediate float64.

    Epoch-scale nanoseconds lose low bits when evaluated as
    ``float(raw) * 1e-9``.  ``longdouble`` retains the integer-to-seconds
    conversion precision needed for monotonicity and interpolation audits.
    """

    stripped = raw.strip()
    if re.fullmatch(r"[+-]?\d+", stripped) is None:
        raise ValueError("timestamp must be integer nanoseconds")
    return np.longdouble(stripped) / np.longdouble("1000000000")


def load_vins_body_csv(path: Path) -> PoseSeries:
    stamps: list[np.longdouble] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for line_number, row in enumerate(csv.reader(handle), 1):
            if not row or all(not value.strip() for value in row):
                continue
            if len(row) < 8:
                raise ValueError(f"{path}:{line_number}: expected at least 8 columns")
            try:
                stamp_s = parse_nanosecond_timestamp(row[0])
                position = [float(row[index]) for index in range(1, 4)]
                qw, qx, qy, qz = [float(row[index]) for index in range(4, 8)]
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid numeric pose") from exc
            stamps.append(stamp_s)
            positions.append(position)
            quaternions.append([qx, qy, qz, qw])
    return PoseSeries(
        stamps=np.asarray(stamps, dtype=np.longdouble),
        positions=np.asarray(positions, dtype=float).reshape((-1, 3)),
        quaternions_xyzw=np.asarray(quaternions, dtype=float).reshape((-1, 4)),
    )


def load_tum_reference(path: Path) -> PoseSeries:
    stamps: list[np.longdouble] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    orientation_available: bool | None = None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 4:
                raise ValueError(f"{path}:{line_number}: expected at least 4 columns")
            has_orientation = len(parts) >= 8
            if orientation_available is None:
                orientation_available = has_orientation
            elif orientation_available != has_orientation:
                raise ValueError(f"{path}:{line_number}: mixed position-only and pose rows")
            try:
                stamps.append(np.longdouble(parts[0]))
                positions.append([float(value) for value in parts[1:4]])
                if has_orientation:
                    quaternions.append([float(value) for value in parts[4:8]])
            except ValueError as exc:
                raise ValueError(f"{path}:{line_number}: invalid numeric pose") from exc
    return PoseSeries(
        stamps=np.asarray(stamps, dtype=np.longdouble),
        positions=np.asarray(positions, dtype=float).reshape((-1, 3)),
        quaternions_xyzw=(
            np.asarray(quaternions, dtype=float).reshape((-1, 4))
            if orientation_available
            else None
        ),
    )


def load_ros_reference(path: Path, topic: str) -> PoseSeries:
    import rosbag

    stamps: list[float] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    orientation_available = True
    with rosbag.Bag(str(path)) as bag:
        for _, message, _ in bag.read_messages(topics=[topic]):
            pose = None
            if hasattr(message, "pose") and hasattr(message.pose, "pose"):
                pose = message.pose.pose
            elif hasattr(message, "pose"):
                pose = message.pose
            if pose is not None:
                position = pose.position
                orientation = getattr(pose, "orientation", None)
            elif hasattr(message, "transform"):
                position = message.transform.translation
                orientation = getattr(message.transform, "rotation", None)
            else:
                continue
            stamps.append(float(message.header.stamp.to_sec()))
            positions.append([float(position.x), float(position.y), float(position.z)])
            if orientation is None:
                orientation_available = False
                quaternions.append([math.nan] * 4)
            else:
                quaternions.append(
                    [
                        float(orientation.x),
                        float(orientation.y),
                        float(orientation.z),
                        float(orientation.w),
                    ]
                )
    return PoseSeries(
        stamps=np.asarray(stamps, dtype=np.longdouble),
        positions=np.asarray(positions, dtype=float).reshape((-1, 3)),
        quaternions_xyzw=(
            np.asarray(quaternions, dtype=float).reshape((-1, 4))
            if orientation_available
            else None
        ),
    )


def load_body_t_sensor(config_path: Path) -> np.ndarray:
    import cv2

    storage = cv2.FileStorage(str(config_path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ValueError(f"could not open OpenCV YAML: {config_path}")
    try:
        matrix = storage.getNode("body_T_cam0").mat()
    finally:
        storage.release()
    if matrix is None:
        raise ValueError(f"body_T_cam0 missing from {config_path}")
    matrix = np.asarray(matrix, dtype=float)
    if matrix.shape != (4, 4):
        raise ValueError(f"body_T_cam0 in {config_path} is not 4x4")
    return matrix


def parse_named_paths(values: Sequence[str], option: str) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} requires NAME=PATH, received {value!r}")
        name, raw_path = value.split("=", 1)
        if not name or not raw_path:
            raise ValueError(f"{option} requires non-empty NAME and PATH")
        if name in parsed:
            raise ValueError(f"duplicate {option} name: {name}")
        parsed[name] = Path(raw_path)
    return parsed


def parse_named_floats(values: Sequence[str], option: str) -> dict[str, float]:
    parsed: dict[str, float] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"{option} requires NAME=VALUE, received {value!r}")
        name, raw_value = value.split("=", 1)
        if not name or name in parsed:
            raise ValueError(f"invalid or duplicate {option} name: {name!r}")
        try:
            parsed[name] = float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{option} value must be numeric: {value!r}") from exc
        if not math.isfinite(parsed[name]):
            raise ValueError(f"{option} value must be finite: {value!r}")
    return parsed


def bracket_stats(trajectory: ResampledTrajectory) -> dict[str, float | int]:
    finite = trajectory.bracket_gaps_s[np.isfinite(trajectory.bracket_gaps_s)]
    return {
        "valid_grid_count": int(np.sum(trajectory.valid)),
        "bracket_gap_p50_s": float(np.median(finite)) if len(finite) else math.nan,
        "bracket_gap_p95_s": float(np.percentile(finite, 95)) if len(finite) else math.nan,
        "bracket_gap_max_s": float(np.max(finite)) if len(finite) else math.nan,
    }


def legacy_nearest_reuse_stats(
    estimate_stamps: Sequence[float] | np.ndarray,
    reference_stamps: Sequence[float] | np.ndarray,
) -> dict[str, float | int]:
    estimates = np.asarray(estimate_stamps, dtype=np.longdouble)
    references = np.asarray(reference_stamps, dtype=np.longdouble)
    counts = np.zeros(len(references), dtype=int)
    errors: list[float] = []
    for stamp in estimates:
        if not len(references) or stamp < references[0] or stamp > references[-1]:
            continue
        right = int(np.searchsorted(references, stamp, side="left"))
        candidates = [right]
        if right > 0:
            candidates.append(right - 1)
        index = min(candidates, key=lambda item: (abs(references[item] - stamp), references[item]))
        counts[index] += 1
        errors.append(float(abs(references[index] - stamp)))
    unique_pairs = legacy_unique_assignment(estimates, references)
    unique_errors = (
        np.abs(estimates[unique_pairs[:, 0]] - references[unique_pairs[:, 1]])
        if len(unique_pairs)
        else np.empty((0,), dtype=float)
    )
    return {
        "legacy_pair_count": int(np.sum(counts)),
        "legacy_unique_reference_used": int(np.sum(counts > 0)),
        "legacy_max_reference_reuse": int(np.max(counts)) if len(counts) else 0,
        "legacy_timestamp_error_p95_s": float(np.percentile(errors, 95)) if errors else math.nan,
        "legacy_timestamp_error_max_s": float(np.max(errors)) if errors else math.nan,
        "legacy_unique_assignment_pair_count": int(len(unique_pairs)),
        "legacy_unique_assignment_error_p95_s": (
            float(np.percentile(unique_errors, 95)) if len(unique_errors) else math.nan
        ),
        "legacy_unique_assignment_error_max_s": (
            float(np.max(unique_errors)) if len(unique_errors) else math.nan
        ),
    }


def serializable_summary(
    evaluation: dict[str, object],
    reference: ResampledTrajectory,
    arms: dict[str, ResampledTrajectory],
    protocol: dict[str, object],
    legacy_reuse: dict[str, dict[str, float | int]],
) -> dict[str, object]:
    arm_metrics = evaluation["arms"]
    assert isinstance(arm_metrics, dict)
    return {
        "protocol": protocol,
        "support": evaluation["support"],
        "reference": {
            "audit": asdict(reference.audit) if reference.audit else {},
            "rejection_histogram": rejection_histogram(reference),
            **bracket_stats(reference),
        },
        "arms": {
            name: {
                "audit": asdict(trajectory.audit) if trajectory.audit else {},
                "rejection_histogram": rejection_histogram(trajectory),
                **bracket_stats(trajectory),
                **legacy_reuse[name],
                **arm_metrics[name],
            }
            for name, trajectory in arms.items()
        },
    }


def clean_json_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): clean_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json_value(item) for item in value]
    if isinstance(value, np.generic):
        return clean_json_value(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_grid_audit(
    path: Path,
    reference: ResampledTrajectory,
    arms: dict[str, ResampledTrajectory],
    evaluation: dict[str, object],
) -> None:
    common_mask = np.asarray(evaluation["common_mask"], dtype=bool)
    segments = np.asarray(evaluation["segments"], dtype=int)
    fields = ["timestamp", "reference_valid"]
    for name in arms:
        fields.append(f"{name}_valid")
    fields.extend(["common_valid", "segment_id"])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, stamp in enumerate(reference.stamps):
            row: dict[str, object] = {
                "timestamp": format(float(stamp), ".17g"),
                "reference_valid": int(reference.valid[index]),
                "common_valid": int(common_mask[index]),
                "segment_id": int(segments[index]),
            }
            for name, arm in arms.items():
                row[f"{name}_valid"] = int(arm.valid[index])
            writer.writerow(row)


def write_metrics_csv(path: Path, summary: dict[str, object]) -> None:
    arms = summary["arms"]
    assert isinstance(arms, dict)
    fieldnames = sorted({"arm"} | {key for metrics in arms.values() for key in metrics if key != "audit" and key != "rejection_histogram"})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for name, metrics in arms.items():
            writer.writerow({"arm": name, **{key: value for key, value in metrics.items() if key in fieldnames}})


def format_identity_tum_line(stamp: float, position: np.ndarray) -> str:
    values = [stamp, float(position[0]), float(position[1]), float(position[2])]
    return " ".join(format(value, ".17g") for value in values) + " 0 0 0 1\n"


def write_identity_tum(
    path: Path, stamps: np.ndarray, positions: np.ndarray, indices: np.ndarray
) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for index in indices:
            handle.write(
                format_identity_tum_line(float(stamps[index]), positions[index])
            )


def parse_evo_rmse(output: str) -> float:
    for line in output.splitlines():
        fields = line.strip().split()
        if fields and fields[0] == "rmse":
            return float(fields[-1])
    raise ValueError("evo output did not contain an rmse row")


def run_evo_command(command: list[str], log_path: Path) -> float:
    process = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.write_text(
        "$ " + " ".join(command) + "\n" + process.stdout,
        encoding="utf-8",
    )
    if process.returncode != 0:
        raise RuntimeError(f"evo failed with code {process.returncode}: {log_path}")
    return parse_evo_rmse(process.stdout)


def run_segmented_evo_crosscheck(
    output_dir: Path,
    reference: ResampledTrajectory,
    arms: dict[str, ResampledTrajectory],
    evaluation: dict[str, object],
    evaluation_rate_hz: float,
    rpe_delta_s: float,
) -> dict[str, object]:
    if not shutil.which("evo_ape") or not shutil.which("evo_rpe"):
        raise RuntimeError("evo_ape/evo_rpe are required for --run-evo")
    common_mask = np.asarray(evaluation["common_mask"], dtype=bool)
    segments = np.asarray(evaluation["segments"], dtype=int)
    common_indices = np.flatnonzero(common_mask)
    delta_frames_float = evaluation_rate_hz * rpe_delta_s
    delta_frames = int(round(delta_frames_float))
    if delta_frames <= 0 or abs(delta_frames - delta_frames_float) > 1e-9:
        raise ValueError("evaluation_rate_hz * rpe_delta_s must be a positive integer")

    evo_dir = output_dir / "evo_crosscheck"
    evo_dir.mkdir(parents=True, exist_ok=True)
    reference_ape_path = evo_dir / "reference_common.tum"
    write_identity_tum(
        reference_ape_path, reference.stamps, reference.positions, common_indices
    )
    primary_metrics = evaluation["arms"]
    assert isinstance(primary_metrics, dict)
    arm_results: dict[str, object] = {}
    for name, arm in arms.items():
        aligned_common = align_se3_positions(
            arm.positions[common_mask], reference.positions[common_mask]
        )
        aligned_full = np.full_like(reference.positions, np.nan, dtype=float)
        aligned_full[common_mask] = aligned_common
        estimate_ape_path = evo_dir / f"{name}_common_aligned.tum"
        write_identity_tum(
            estimate_ape_path, reference.stamps, aligned_full, common_indices
        )
        ape_rmse = run_evo_command(
            [
                "evo_ape",
                "tum",
                str(reference_ape_path),
                str(estimate_ape_path),
                "-a",
                "-r",
                "trans_part",
            ],
            evo_dir / f"{name}_evo_ape.log",
        )

        weighted_squared_error = 0.0
        total_pairs = 0
        segment_results: list[dict[str, object]] = []
        for segment_id in sorted(set(int(value) for value in segments if value >= 0)):
            indices = np.flatnonzero(segments == segment_id)
            pair_count = max(0, len(indices) - delta_frames)
            if pair_count == 0:
                continue
            reference_segment = evo_dir / f"reference_segment_{segment_id:03d}.tum"
            estimate_segment = evo_dir / f"{name}_segment_{segment_id:03d}.tum"
            write_identity_tum(
                reference_segment, reference.stamps, reference.positions, indices
            )
            write_identity_tum(
                estimate_segment, reference.stamps, aligned_full, indices
            )
            rmse = run_evo_command(
                [
                    "evo_rpe",
                    "tum",
                    str(reference_segment),
                    str(estimate_segment),
                    "-r",
                    "trans_part",
                    "-d",
                    str(delta_frames),
                    "-u",
                    "f",
                    "--all_pairs",
                    "--pairs_from_reference",
                ],
                evo_dir / f"{name}_evo_rpe_segment_{segment_id:03d}.log",
            )
            weighted_squared_error += pair_count * rmse * rmse
            total_pairs += pair_count
            segment_results.append(
                {"segment_id": segment_id, "pair_count": pair_count, "rmse_m": rmse}
            )
        rpe_rmse = (
            math.sqrt(weighted_squared_error / total_pairs)
            if total_pairs
            else math.nan
        )
        primary = primary_metrics[name]
        assert isinstance(primary, dict)
        primary_ape = float(primary["ape_rmse_m"])
        primary_rpe = float(primary["rpe_rmse_m"])
        arm_results[name] = {
            "primary_ape_rmse_m": primary_ape,
            "evo_ape_rmse_m": ape_rmse,
            "ape_abs_diff_m": abs(primary_ape - ape_rmse),
            "primary_rpe_rmse_m": primary_rpe,
            "evo_segmented_rpe_rmse_m": rpe_rmse,
            "rpe_abs_diff_m": abs(primary_rpe - rpe_rmse),
            "rpe_pair_count": total_pairs,
            "segments": segment_results,
        }
    return {
        "evo_version": "1.31.1",
        "rpe_delta_frames": delta_frames,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "arms": arm_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    reference_group = parser.add_mutually_exclusive_group(required=True)
    reference_group.add_argument("--reference-tum")
    reference_group.add_argument("--reference-bag")
    parser.add_argument("--reference-topic")
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=VIO_CSV")
    parser.add_argument("--arm-config", action="append", default=[], metavar="NAME=VINS_YAML")
    parser.add_argument("--arm-time-offset-s", action="append", default=[], metavar="NAME=SECONDS")
    parser.add_argument("--reference-time-offset-s", type=np.longdouble, default=np.longdouble(0))
    parser.add_argument("--nominal-reference-rate-hz", type=float, required=True)
    parser.add_argument("--nominal-estimate-rate-hz", type=float, default=10.0)
    parser.add_argument("--evaluation-rate-hz", type=float)
    parser.add_argument("--max-reference-gap-s", type=float)
    parser.add_argument("--max-estimate-gap-s", type=float)
    parser.add_argument("--window-start-s", type=np.longdouble)
    parser.add_argument("--window-end-s", type=np.longdouble)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--min-ape-poses", type=int, default=30)
    parser.add_argument("--min-ape-span-s", type=float, default=10.0)
    parser.add_argument("--min-common-coverage", type=float, default=0.70)
    parser.add_argument("--min-rpe-pairs", type=int, default=10)
    parser.add_argument("--contrast-name", default="contrast")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-evo", action="store_true")
    args = parser.parse_args()

    arm_paths = parse_named_paths(args.arm, "--arm")
    arm_configs = parse_named_paths(args.arm_config, "--arm-config")
    arm_time_offsets = parse_named_floats(args.arm_time_offset_s, "--arm-time-offset-s")
    if not arm_paths:
        raise SystemExit("at least one --arm NAME=VIO_CSV is required")
    if set(arm_paths) != set(arm_configs):
        raise SystemExit("--arm and --arm-config names must match exactly")
    if not set(arm_time_offsets).issubset(arm_paths):
        raise SystemExit("--arm-time-offset-s names must be declared by --arm")

    if args.reference_tum:
        reference_series = load_tum_reference(Path(args.reference_tum))
        reference_identity = str(Path(args.reference_tum))
    else:
        if not args.reference_topic:
            raise SystemExit("--reference-topic is required with --reference-bag")
        reference_series = load_ros_reference(
            Path(args.reference_bag), args.reference_topic
        )
        reference_identity = f"{args.reference_bag}:{args.reference_topic}"
    reference_series = PoseSeries(
        stamps=reference_series.stamps + args.reference_time_offset_s,
        positions=reference_series.positions,
        quaternions_xyzw=reference_series.quaternions_xyzw,
    )

    reference_stamps, _, _, _ = prepare_reference_samples(
        reference_series.stamps,
        reference_series.positions,
        reference_series.quaternions_xyzw,
    )
    if len(reference_stamps) < 2:
        raise SystemExit("reference contains fewer than two unique finite poses")
    window_start = (
        args.window_start_s
        if args.window_start_s is not None
        else reference_stamps[0]
    )
    window_end = (
        args.window_end_s
        if args.window_end_s is not None
        else reference_stamps[-1]
    )
    evaluation_rate = (
        float(args.evaluation_rate_hz)
        if args.evaluation_rate_hz is not None
        else choose_evaluation_rate(float(args.nominal_reference_rate_hz))
    )
    max_reference_gap = (
        float(args.max_reference_gap_s)
        if args.max_reference_gap_s is not None
        else 2.5 / float(args.nominal_reference_rate_hz)
    )
    max_estimate_gap = (
        float(args.max_estimate_gap_s)
        if args.max_estimate_gap_s is not None
        else 2.5 / float(args.nominal_estimate_rate_hz)
    )
    grid = make_uniform_grid(window_start, window_end, evaluation_rate)
    reference = resample_trajectory(
        reference_series.stamps,
        reference_series.positions,
        grid,
        max_reference_gap,
        reference_series.quaternions_xyzw,
        sample_kind="reference",
    )

    resampled_arms: dict[str, ResampledTrajectory] = {}
    legacy_reuse: dict[str, dict[str, float | int]] = {}
    for name, path in arm_paths.items():
        body = load_vins_body_csv(path)
        body = PoseSeries(
            stamps=body.stamps + arm_time_offsets.get(name, 0.0),
            positions=body.positions,
            quaternions_xyzw=body.quaternions_xyzw,
        )
        if body.quaternions_xyzw is None:
            raise SystemExit(f"arm {name} has no body orientation")
        validate_estimate_samples(body.stamps, body.positions, body.quaternions_xyzw)
        legacy_reuse[name] = legacy_nearest_reuse_stats(
            body.stamps, reference_stamps
        )
        sensor_positions, sensor_quaternions = transform_body_poses_to_sensor(
            body.positions,
            body.quaternions_xyzw,
            load_body_t_sensor(arm_configs[name]),
        )
        resampled_arms[name] = resample_trajectory(
            body.stamps,
            sensor_positions,
            grid,
            max_estimate_gap,
            sensor_quaternions,
            sample_kind="estimate",
        )

    evaluation = evaluate_common_translation(
        reference,
        resampled_arms,
        window_start_s=window_start,
        window_end_s=window_end,
        max_segment_gap_s=max(max_reference_gap, max_estimate_gap),
        rpe_delta_s=float(args.rpe_delta_s),
        min_ape_poses=int(args.min_ape_poses),
        min_ape_span_s=float(args.min_ape_span_s),
        min_common_coverage=float(args.min_common_coverage),
        min_rpe_pairs=int(args.min_rpe_pairs),
    )
    protocol = {
        "contrast_name": args.contrast_name,
        "reference": reference_identity,
        "evaluation_rate_hz": evaluation_rate,
        "nominal_reference_rate_hz": float(args.nominal_reference_rate_hz),
        "nominal_estimate_rate_hz": float(args.nominal_estimate_rate_hz),
        "window_start_s": float(window_start),
        "window_end_s": float(window_end),
        "max_reference_gap_s": max_reference_gap,
        "max_estimate_gap_s": max_estimate_gap,
        "rpe_delta_s": float(args.rpe_delta_s),
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "reference_time_offset_s": float(args.reference_time_offset_s),
        "arm_time_offsets_s": {
            name: arm_time_offsets.get(name, 0.0) for name in arm_paths
        },
    }
    summary = clean_json_value(
        serializable_summary(
            evaluation, reference, resampled_arms, protocol, legacy_reuse
        )
    )
    assert isinstance(summary, dict)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "common_support_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    write_grid_audit(output_dir / "common_grid_audit.csv", reference, resampled_arms, evaluation)
    write_metrics_csv(output_dir / "common_support_metrics.csv", summary)
    if args.run_evo:
        evo_summary = clean_json_value(
            run_segmented_evo_crosscheck(
                output_dir,
                reference,
                resampled_arms,
                evaluation,
                evaluation_rate,
                float(args.rpe_delta_s),
            )
        )
        (output_dir / "evo_crosscheck.json").write_text(
            json.dumps(evo_summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(f"summary={summary_path}")
    print(f"ape_valid={int(bool(summary['support']['ape_valid']))}")
    print(f"rpe_valid={int(bool(summary['support']['rpe_valid']))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
