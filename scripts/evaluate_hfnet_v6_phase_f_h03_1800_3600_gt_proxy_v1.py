#!/usr/bin/env python3
"""One-shot descriptive H03 HFNet evaluation against the frozen COLMAP proxy.

This evaluator is additive and process-free: it reads the already sealed HFNet
trajectory, the image-indexed AQUALOC H03 COLMAP reference, the frozen camera
clock, and the exact runtime calibration.  It never starts HFNet, VINS, ROS,
feature extraction, or a detector.  The primary translation metrics use a
fixed-scale SE(3) alignment; Sim(3) is emitted only as a scale diagnostic.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import asdict
from decimal import Decimal, InvalidOperation
import hashlib
import html
import json
import math
import os
from pathlib import Path
import stat
import sys
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import cv2
import numpy as np

try:
    from trajectory_eval_core import (
        align_se3_positions,
        evaluate_common_translation,
        rejection_histogram,
        resample_trajectory,
        transform_body_poses_to_sensor,
    )
except ModuleNotFoundError:
    from scripts.trajectory_eval_core import (
        align_se3_positions,
        evaluate_common_translation,
        rejection_histogram,
        resample_trajectory,
        transform_body_poses_to_sensor,
    )

try:
    from evaluate_anyfeature_vslam_sim3_common_support_v1 import (
        apply_sim3_positions,
        fit_umeyama_sim3,
        sim3_json,
    )
except ModuleNotFoundError:
    from scripts.evaluate_anyfeature_vslam_sim3_common_support_v1 import (
        apply_sim3_positions,
        fit_umeyama_sim3,
        sim3_json,
    )


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_gt_proxy_eval_freeze_v1.json"
OUTPUT = ROOT / "papers/hfnet_v6_phase_f_h03_1800_3600_gt_proxy_eval_v1"
AUTHORIZATION_TOKEN = "HFNET_PHASE_F_H03_GT_PROXY_EVAL_V1_ONCE"

FREEZE_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-gt-proxy-eval-freeze-v1"
RESULT_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-gt-proxy-eval-result-v1"
MANIFEST_SCHEMA = "aqua-fe-hfnet-v6-phase-f-h03-gt-proxy-eval-manifest-v1"

RC_OK = 0
RC_FAILED = 1
RC_BLOCKED = 2
MAX_TIMESTAMP_ASSOCIATION_NS = 256


class ContractError(RuntimeError):
    """A frozen identity, protocol, or no-clobber condition failed."""


def canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ContractError(f"{label}_SYMLINK_FORBIDDEN")
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise ContractError(f"{label}_MISSING:{error}") from error
    metadata = resolved.lstat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ContractError(f"{label}_NOT_REGULAR")
    return resolved


def file_identity(path: Path) -> Dict[str, object]:
    resolved = regular_file(path, "IDENTITY")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def require_identity(record: Mapping[str, object], label: str) -> Path:
    try:
        path = regular_file(Path(str(record["path"])), label)
        expected_size = int(record["size_bytes"])
        expected_hash = str(record["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise ContractError(f"{label}_PIN_SCHEMA") from error
    if path.stat().st_size != expected_size or sha256_file(path) != expected_hash:
        raise ContractError(f"{label}_PIN_MISMATCH")
    return path


def read_canonical_json(path: Path, label: str) -> Dict[str, Any]:
    resolved = regular_file(path, label)
    raw = resolved.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"{label}_INVALID_JSON") from error
    if not isinstance(value, dict) or raw != canonical_json_bytes(value):
        raise ContractError(f"{label}_NOT_CANONICAL")
    return value


def verify_self_hash(value: Mapping[str, Any]) -> bool:
    copy = json.loads(json.dumps(value, ensure_ascii=False))
    try:
        observed = str(copy["self_hash"]["value"])
        copy["self_hash"]["value"] = "0" * 64
    except (KeyError, TypeError) as error:
        raise ContractError("FREEZE_SELF_HASH_SCHEMA") from error
    return hashlib.sha256(canonical_json_bytes(copy)).hexdigest() == observed


def scan_forbidden_processes(hfnet_elf: Path) -> List[Dict[str, object]]:
    conflicts: List[Dict[str, object]] = []
    forbidden = ("mono_inertial_euroc_headless", "vins_node", "feature_tracker", "roscore")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            exe = os.readlink(str(entry / "exe"))
        except OSError:
            exe = ""
        try:
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            comm = ""
        if exe == str(hfnet_elf) or any(token in comm.lower() for token in forbidden):
            conflicts.append({"pid": int(entry.name), "comm": comm, "exe": exe})
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def audit_freeze(*, require_output_absent: bool) -> Tuple[Dict[str, Any], Dict[str, Path]]:
    freeze = read_canonical_json(FREEZE, "FREEZE")
    if freeze.get("schema_version") != FREEZE_SCHEMA:
        raise ContractError("FREEZE_SCHEMA_MISMATCH")
    if freeze.get("status") != "PRE_EVAL_GO_FROZEN_OUTCOME_UNREAD":
        raise ContractError("FREEZE_STATUS_MISMATCH")
    if not verify_self_hash(freeze):
        raise ContractError("FREEZE_SELF_HASH_MISMATCH")
    if FREEZE.stat().st_nlink != 1 or stat.S_IMODE(FREEZE.stat().st_mode) != 0o444:
        raise ContractError("FREEZE_MODE_OR_NLINK_MISMATCH")

    raw_pins = freeze.get("artifact_pins")
    if not isinstance(raw_pins, dict):
        raise ContractError("FREEZE_ARTIFACT_PINS_MISSING")
    paths = {
        str(name): require_identity(record, f"PIN_{name}")
        for name, record in raw_pins.items()
        if isinstance(record, dict)
    }
    if len(paths) != len(raw_pins):
        raise ContractError("FREEZE_ARTIFACT_PIN_SCHEMA_MISMATCH")
    if paths.get("evaluator_script") != Path(__file__).resolve(strict=True):
        raise ContractError("FREEZE_EVALUATOR_PATH_MISMATCH")

    protocol = freeze.get("protocol")
    expected = {
        "feed_source_indices_closed": [1800, 3600],
        "score_local_indices_closed": [900, 1800],
        "score_source_indices_closed": [2700, 3600],
        "native_score_camera_count": 901,
        "reference_source_stride_frames": 5,
        "reference_score_pose_count": 181,
        "evaluation_rate_hz": 2.0,
        "evaluation_grid_count": 91,
        "evaluation_step_ns": 500000000,
        "rpe_delta_s": 1.0,
        "primary_alignment": "SE3_FIXED_SCALE_POSITION_UMEYAMA_SVD",
        "secondary_alignment": "SIM3_SCALE_DIAGNOSTIC_ONLY",
        "max_reference_interp_gap_s": 0.625,
        "max_estimate_interp_gap_s": 0.25,
        "max_segment_gap_s": 0.75,
    }
    if not isinstance(protocol, dict) or any(protocol.get(key) != value for key, value in expected.items()):
        raise ContractError("FREEZE_PROTOCOL_MISMATCH")
    claims = freeze.get("claim_boundary")
    required_false = (
        "independent_ground_truth",
        "formal_accuracy_claim",
        "other_system_compared",
        "superiority_claim",
        "inferential_statistics_authorized",
        "dense_timestamps_are_independent_samples",
    )
    if not isinstance(claims, dict) or any(claims.get(key) is not False for key in required_false):
        raise ContractError("FREEZE_CLAIM_BOUNDARY_MISMATCH")
    if claims.get("descriptive_proxy_trajectory_error_authorized") is not True:
        raise ContractError("FREEZE_PROXY_EVAL_NOT_AUTHORIZED")
    execution = freeze.get("execution_contract")
    if not isinstance(execution, dict):
        raise ContractError("FREEZE_EXECUTION_CONTRACT_MISSING")
    if execution.get("authorization_token") != AUTHORIZATION_TOKEN:
        raise ContractError("FREEZE_AUTHORIZATION_TOKEN_MISMATCH")
    if execution.get("output") != str(OUTPUT):
        raise ContractError("FREEZE_OUTPUT_PATH_MISMATCH")
    if require_output_absent and (OUTPUT.exists() or OUTPUT.is_symlink()):
        raise ContractError("OUTPUT_NAMESPACE_NOT_FRESH")
    conflicts = scan_forbidden_processes(paths["official_elf"])
    if conflicts:
        raise ContractError(f"FORBIDDEN_PROCESS_PRESENT:{conflicts}")
    return freeze, paths


def parse_integer_decimal(raw: str, label: str) -> int:
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ContractError(f"{label}_INVALID_DECIMAL") from error
    if not value.is_finite() or value != value.to_integral_value():
        raise ContractError(f"{label}_NOT_INTEGER")
    return int(value)


def quaternion_xyzw_to_wxyz(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Explicitly adapt HFNet/TUM xyzw components to a wxyz-only consumer."""

    array = np.asarray(values, dtype=float)
    if array.shape[-1:] != (4,) or not np.all(np.isfinite(array)):
        raise ContractError("QUATERNION_XYZW_ADAPTER_INPUT_INVALID")
    return array[..., [3, 0, 1, 2]]


def quaternion_wxyz_to_xyzw(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Invert :func:`quaternion_xyzw_to_wxyz` without changing pose meaning."""

    array = np.asarray(values, dtype=float)
    if array.shape[-1:] != (4,) or not np.all(np.isfinite(array)):
        raise ContractError("QUATERNION_WXYZ_ADAPTER_INPUT_INVALID")
    return array[..., [1, 2, 3, 0]]


def load_camera_times(path: Path) -> List[int]:
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ContractError("CAMERA_TIMES_FINAL_NEWLINE_MISSING")
    try:
        stamps = [int(line) for line in raw.decode("ascii").splitlines()]
    except (UnicodeError, ValueError) as error:
        raise ContractError("CAMERA_TIMES_INVALID") from error
    if len(stamps) != 1801 or any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("CAMERA_TIMES_COUNT_OR_ORDER")
    return stamps


def load_body_trajectory(path: Path, camera_ns: Sequence[int]) -> Dict[str, np.ndarray]:
    indices: List[int] = []
    stamps: List[int] = []
    positions: List[List[float]] = []
    quaternions: List[List[float]] = []
    association_errors: List[int] = []
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        fields = line.split()
        if len(fields) != 8:
            raise ContractError(f"TRAJECTORY_FIELD_COUNT:{line_number}")
        stamp = parse_integer_decimal(fields[0], f"TRAJECTORY_TIMESTAMP_{line_number}")
        try:
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"TRAJECTORY_NUMERIC:{line_number}") from error
        if not all(math.isfinite(value) for value in values):
            raise ContractError(f"TRAJECTORY_NONFINITE:{line_number}")
        right = bisect.bisect_left(camera_ns, stamp)
        candidates = [index for index in (right - 1, right) if 0 <= index < len(camera_ns)]
        if not candidates:
            raise ContractError(f"TRAJECTORY_NO_CAMERA_ASSOCIATION:{line_number}")
        index = min(candidates, key=lambda item: (abs(camera_ns[item] - stamp), item))
        error_ns = abs(camera_ns[index] - stamp)
        if error_ns > MAX_TIMESTAMP_ASSOCIATION_NS:
            raise ContractError(f"TRAJECTORY_ASSOCIATION_ERROR:{line_number}:{error_ns}")
        indices.append(index)
        stamps.append(camera_ns[index])
        positions.append(values[:3])
        quaternions.append(values[3:])
        association_errors.append(error_ns)
    if (
        len(indices) != 926
        or indices != list(range(875, 1801))
        or len(set(indices)) != len(indices)
    ):
        raise ContractError("TRAJECTORY_FROZEN_SUFFIX_MISMATCH")
    return {
        "indices": np.asarray(indices, dtype=int),
        "stamps_ns": np.asarray(stamps, dtype=np.int64),
        "positions": np.asarray(positions, dtype=float),
        "quaternions": np.asarray(quaternions, dtype=float),
        "association_errors_ns": np.asarray(association_errors, dtype=int),
    }


def load_reference(path: Path, camera_ns: Sequence[int]) -> Dict[str, np.ndarray]:
    source_indices: List[int] = []
    positions: List[List[float]] = []
    quaternions: List[List[float]] = []
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        fields = line.split()
        if len(fields) != 8:
            raise ContractError(f"REFERENCE_FIELD_COUNT:{line_number}")
        source_index = parse_integer_decimal(fields[0], f"REFERENCE_INDEX_{line_number}")
        try:
            values = [float(value) for value in fields[1:]]
        except ValueError as error:
            raise ContractError(f"REFERENCE_NUMERIC:{line_number}") from error
        if not all(math.isfinite(value) for value in values):
            raise ContractError(f"REFERENCE_NONFINITE:{line_number}")
        source_indices.append(source_index)
        positions.append(values[:3])
        quaternions.append(values[3:])
    if source_indices != list(range(0, 5151, 5)):
        raise ContractError("REFERENCE_GLOBAL_INDEX_GRID_MISMATCH")
    selected = [index for index, source in enumerate(source_indices) if 2700 <= source <= 3600]
    if [source_indices[index] for index in selected] != list(range(2700, 3601, 5)):
        raise ContractError("REFERENCE_SCORE_SUPPORT_INCOMPLETE")
    score_source = np.asarray([source_indices[index] for index in selected], dtype=int)
    local_indices = score_source - 1800
    return {
        "source_indices": score_source,
        "stamps_ns": np.asarray([camera_ns[index] for index in local_indices], dtype=np.int64),
        "positions": np.asarray([positions[index] for index in selected], dtype=float),
        "quaternions": np.asarray([quaternions[index] for index in selected], dtype=float),
    }


def load_body_t_camera(path: Path) -> np.ndarray:
    storage = cv2.FileStorage(str(path), cv2.FILE_STORAGE_READ)
    if not storage.isOpened():
        raise ContractError("RUNTIME_CONFIG_OPEN_FAILED")
    try:
        matrix = storage.getNode("IMU.T_b_c1").mat()
    finally:
        storage.release()
    if matrix is None:
        raise ContractError("RUNTIME_CONFIG_IMU_T_B_C1_MISSING")
    result = np.asarray(matrix, dtype=float)
    if result.shape != (4, 4) or not np.all(np.isfinite(result)):
        raise ContractError("RUNTIME_CONFIG_IMU_T_B_C1_INVALID")
    if not np.allclose(result[3], [0.0, 0.0, 0.0, 1.0], atol=1e-12):
        raise ContractError("RUNTIME_CONFIG_IMU_T_B_C1_NOT_HOMOGENEOUS")
    return result


def seconds_from_ns(values: Sequence[int] | np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=np.longdouble) / np.longdouble("1000000000")


def fit_se3_transform(source: np.ndarray, target: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    source_mean = np.mean(source, axis=0)
    target_mean = np.mean(target, axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    u_matrix, _, vt_matrix = np.linalg.svd(source_centered.T @ target_centered)
    rotation = vt_matrix.T @ u_matrix.T
    if np.linalg.det(rotation) < 0.0:
        vt_matrix[-1] *= -1
        rotation = vt_matrix.T @ u_matrix.T
    translation = target_mean - rotation @ source_mean
    return rotation, translation


def metric_summary(errors: np.ndarray) -> Dict[str, float]:
    values = np.asarray(errors, dtype=float)
    if values.ndim != 1 or not len(values) or not np.all(np.isfinite(values)):
        raise ContractError("METRIC_ERROR_VECTOR_INVALID")
    return {
        "rmse_m": float(np.sqrt(np.mean(values ** 2))),
        "median_m": float(np.median(values)),
        "max_m": float(np.max(values)),
        "mean_m": float(np.mean(values)),
        "p95_m": float(np.percentile(values, 95)),
    }


def histogram(values: Iterable[str]) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for value in values:
        result[str(value)] = result.get(str(value), 0) + 1
    return {key: result[key] for key in sorted(result)}


def bracket_summary(trajectory: Any) -> Dict[str, object]:
    finite = trajectory.bracket_gaps_s[np.isfinite(trajectory.bracket_gaps_s)]
    return {
        "valid_count": int(np.sum(trajectory.valid)),
        "method_histogram": rejection_histogram(trajectory),
        "bracket_gap_max_s": float(np.max(finite)) if len(finite) else None,
        "bracket_gap_p95_s": float(np.percentile(finite, 95)) if len(finite) else None,
        "sample_audit": asdict(trajectory.audit) if trajectory.audit else {},
    }


def svg_line_plot(
    title: str,
    x_label: str,
    y_label: str,
    series: Sequence[Tuple[str, Sequence[float], Sequence[float], str]],
) -> str:
    width, height = 900, 560
    left, right, top, bottom = 90.0, 35.0, 55.0, 75.0
    xs = [float(value) for _, x_values, _, _ in series for value in x_values]
    ys = [float(value) for _, _, y_values, _ in series for value in y_values]
    if not xs or not ys:
        raise ContractError("SVG_SERIES_EMPTY")
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max <= x_min:
        x_max = x_min + 1.0
    if y_max <= y_min:
        y_max = y_min + 1.0
    x_pad = 0.03 * (x_max - x_min)
    y_pad = 0.08 * (y_max - y_min)
    x_min, x_max = x_min - x_pad, x_max + x_pad
    y_min, y_max = y_min - y_pad, y_max + y_pad
    plot_w, plot_h = width - left - right, height - top - bottom

    def px(value: float) -> float:
        return left + (value - x_min) / (x_max - x_min) * plot_w

    def py(value: float) -> float:
        return top + (y_max - value) / (y_max - y_min) * plot_h

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        f'<text x="{width/2:.1f}" y="30" text-anchor="middle" font-family="sans-serif" font-size="20">{html.escape(title)}</text>',
    ]
    for tick in range(6):
        fraction = tick / 5.0
        x_value = x_min + fraction * (x_max - x_min)
        y_value = y_min + fraction * (y_max - y_min)
        x_pos = px(x_value)
        y_pos = py(y_value)
        parts.extend(
            [
                f'<line x1="{x_pos:.2f}" y1="{top:.2f}" x2="{x_pos:.2f}" y2="{top+plot_h:.2f}" stroke="#e5e7eb"/>',
                f'<text x="{x_pos:.2f}" y="{top+plot_h+24:.2f}" text-anchor="middle" font-family="sans-serif" font-size="12">{x_value:.3g}</text>',
                f'<line x1="{left:.2f}" y1="{y_pos:.2f}" x2="{left+plot_w:.2f}" y2="{y_pos:.2f}" stroke="#e5e7eb"/>',
                f'<text x="{left-10:.2f}" y="{y_pos+4:.2f}" text-anchor="end" font-family="sans-serif" font-size="12">{y_value:.3g}</text>',
            ]
        )
    parts.extend(
        [
            f'<rect x="{left:.2f}" y="{top:.2f}" width="{plot_w:.2f}" height="{plot_h:.2f}" fill="none" stroke="#111827"/>',
            f'<text x="{left+plot_w/2:.2f}" y="{height-20:.2f}" text-anchor="middle" font-family="sans-serif" font-size="15">{html.escape(x_label)}</text>',
            f'<text x="22" y="{top+plot_h/2:.2f}" transform="rotate(-90 22 {top+plot_h/2:.2f})" text-anchor="middle" font-family="sans-serif" font-size="15">{html.escape(y_label)}</text>',
        ]
    )
    legend_x, legend_y = left + 12, top + 18
    for offset, (name, x_values, y_values, color) in enumerate(series):
        points = " ".join(
            f"{px(float(x)):.2f},{py(float(y)):.2f}"
            for x, y in zip(x_values, y_values)
        )
        parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
        y_legend = legend_y + 22 * offset
        parts.append(f'<line x1="{legend_x:.2f}" y1="{y_legend:.2f}" x2="{legend_x+24:.2f}" y2="{y_legend:.2f}" stroke="{color}" stroke-width="3"/>')
        parts.append(f'<text x="{legend_x+32:.2f}" y="{y_legend+4:.2f}" font-family="sans-serif" font-size="13">{html.escape(name)}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(descriptor)
    os.chmod(str(path), mode)


def write_csv_exclusive(path: Path, fieldnames: Sequence[str], rows: Sequence[Mapping[str, object]]) -> None:
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(fieldnames), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    write_exclusive(path, buffer.getvalue().encode("utf-8"))


def evaluate(freeze: Mapping[str, Any], paths: Mapping[str, Path]) -> Dict[str, Any]:
    camera_ns = load_camera_times(paths["cam0_times"])
    body = load_body_trajectory(paths["trajectory"], camera_ns)
    reference_native = load_reference(paths["reference_proxy"], camera_ns)
    body_t_camera = load_body_t_camera(paths["runtime_config"])
    quaternion_roundtrip = quaternion_wxyz_to_xyzw(
        quaternion_xyzw_to_wxyz(body["quaternions"])
    )
    if not np.array_equal(quaternion_roundtrip, body["quaternions"]):
        raise ContractError("QUATERNION_COMPONENT_ORDER_ROUNDTRIP_FAILED")
    camera_positions, camera_quaternions = transform_body_poses_to_sensor(
        body["positions"], body["quaternions"], body_t_camera
    )

    score_mask_native = (body["indices"] >= 900) & (body["indices"] <= 1800)
    estimate_stamps_ns = body["stamps_ns"][score_mask_native]
    estimate_positions = camera_positions[score_mask_native]
    estimate_quaternions = camera_quaternions[score_mask_native]
    if len(estimate_stamps_ns) != 901:
        raise ContractError("NATIVE_SCORE_TRAJECTORY_NOT_901")

    score_start_ns = int(camera_ns[900])
    score_end_ns = int(camera_ns[1800])
    grid_ns = np.arange(
        score_start_ns,
        score_end_ns + 1,
        int(freeze["protocol"]["evaluation_step_ns"]),
        dtype=np.int64,
    )
    if len(grid_ns) != 91 or int(grid_ns[-1]) > score_end_ns:
        raise ContractError("EVALUATION_GRID_MISMATCH")
    grid_s = seconds_from_ns(grid_ns)

    reference = resample_trajectory(
        seconds_from_ns(reference_native["stamps_ns"]),
        reference_native["positions"],
        grid_s,
        float(freeze["protocol"]["max_reference_interp_gap_s"]),
        reference_native["quaternions"],
        sample_kind="reference",
    )
    estimate = resample_trajectory(
        seconds_from_ns(estimate_stamps_ns),
        estimate_positions,
        grid_s,
        float(freeze["protocol"]["max_estimate_interp_gap_s"]),
        estimate_quaternions,
        sample_kind="estimate",
    )
    evaluation = evaluate_common_translation(
        reference,
        {"hfnet": estimate},
        window_start_s=float(grid_s[0]),
        window_end_s=float(grid_s[-1]),
        max_segment_gap_s=float(freeze["protocol"]["max_segment_gap_s"]),
        rpe_delta_s=float(freeze["protocol"]["rpe_delta_s"]),
        min_ape_poses=30,
        min_ape_span_s=10.0,
        min_common_coverage=0.70,
        min_rpe_pairs=10,
    )
    support = evaluation["support"]
    if not support["ape_valid"] or not support["rpe_valid"]:
        raise ContractError(f"NUMERIC_SUPPORT_GATE_FAILED:{support}")
    common_mask = np.asarray(evaluation["common_mask"], dtype=bool)
    common_indices = np.flatnonzero(common_mask)
    pairs = np.asarray(evaluation["rpe_pair_indices"], dtype=int)
    reference_common = reference.positions[common_mask]
    estimate_common = estimate.positions[common_mask]

    se3_aligned = align_se3_positions(estimate_common, reference_common)
    se3_rotation, se3_translation = fit_se3_transform(estimate_common, reference_common)
    if not np.allclose(
        se3_aligned,
        (se3_rotation @ estimate_common.T).T + se3_translation,
        rtol=0.0,
        atol=1e-12,
    ):
        raise ContractError("SE3_CORE_CROSSCHECK_FAILED")
    se3_ape_errors = np.linalg.norm(se3_aligned - reference_common, axis=1)

    common_lookup = {
        int(grid_index): local_index for local_index, grid_index in enumerate(common_indices)
    }
    pair_left = np.asarray([common_lookup[int(pair[0])] for pair in pairs], dtype=int)
    pair_right = np.asarray([common_lookup[int(pair[1])] for pair in pairs], dtype=int)
    reference_deltas = reference_common[pair_right] - reference_common[pair_left]
    se3_deltas = se3_aligned[pair_right] - se3_aligned[pair_left]
    se3_rpe_errors = np.linalg.norm(se3_deltas - reference_deltas, axis=1)

    core_metrics = evaluation["arms"]["hfnet"]
    if not (
        math.isclose(metric_summary(se3_ape_errors)["rmse_m"], core_metrics["ape_rmse_m"], rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(metric_summary(se3_rpe_errors)["rmse_m"], core_metrics["rpe_rmse_m"], rel_tol=0.0, abs_tol=1e-12)
    ):
        raise ContractError("SE3_METRIC_CORE_CROSSCHECK_FAILED")

    sim3 = fit_umeyama_sim3(estimate_common, reference_common)
    sim3_aligned = apply_sim3_positions(sim3, estimate_common)
    sim3_ape_errors = np.linalg.norm(sim3_aligned - reference_common, axis=1)
    sim3_deltas = sim3_aligned[pair_right] - sim3_aligned[pair_left]
    sim3_rpe_errors = np.linalg.norm(sim3_deltas - reference_deltas, axis=1)

    relative_grid_s = np.asarray((grid_s - grid_s[0]), dtype=float)
    feed_delay_s = (int(body["stamps_ns"][0]) - int(camera_ns[0])) / 1e9
    score_lead_s = (score_start_ns - int(body["stamps_ns"][0])) / 1e9

    result: Dict[str, Any] = {
        "schema_version": RESULT_SCHEMA,
        "status": "PASS_DESCRIPTIVE_PROXY_EVALUATION",
        "scientific_role": freeze["scientific_role"],
        "claim_boundary": freeze["claim_boundary"],
        "reference": {
            "identity": file_identity(paths["reference_proxy"]),
            "method": "offline COLMAP exhaustive same-image reconstruction",
            "pose_convention": "world_T_camera; xyzw",
            "metric_scale": "updated AQUALOC reference scale corrected with depth metadata",
            "sensor_independent": False,
            "score_native_pose_count": int(len(reference_native["stamps_ns"])),
            "score_source_indices_closed": [2700, 3600],
            "native_source_stride_frames": 5,
            "resampling": bracket_summary(reference),
        },
        "estimate": {
            "identity": file_identity(paths["trajectory"]),
            "source_pose_convention": "world_T_body; xyzw; official IMU SaveTrajectoryEuRoC",
            "evaluated_pose_convention": "world_T_camera = world_T_body * body_T_camera",
            "body_T_camera": body_t_camera.tolist(),
            "native_total_pose_count": int(len(body["indices"])),
            "native_total_local_indices_closed": [int(body["indices"][0]), int(body["indices"][-1])],
            "native_score_pose_count": int(len(estimate_stamps_ns)),
            "native_score_camera_coverage": float(len(estimate_stamps_ns) / 901.0),
            "quaternion_adapter_audit": {
                "hfnet_raw_order": "xyzw",
                "legacy_vins_csv_loader_expected_order": "wxyz",
                "legacy_vins_csv_loader_used": False,
                "synthetic_component_order_tests_required_by_freeze": True,
                "xyzw_to_wxyz_to_xyzw_roundtrip_exact": True,
            },
            "timestamp_association_max_abs_error_ns": int(np.max(body["association_errors_ns"])),
            "resampling": bracket_summary(estimate),
        },
        "support": {
            **support,
            "score_closed_span_s": (score_end_ns - score_start_ns) / 1e9,
            "evaluation_grid_first_ns": int(grid_ns[0]),
            "evaluation_grid_last_ns": int(grid_ns[-1]),
            "score_endpoint_after_grid_ns": int(score_end_ns - int(grid_ns[-1])),
            "evaluation_grid_rate_hz": 2.0,
            "rpe_delta_s": 1.0,
            "rpe_pairs_overlap_and_are_not_independent": True,
            "native_901_camera_samples_are_not_independent": True,
        },
        "initialization_and_coverage": {
            "feed_first_output_local_index": int(body["indices"][0]),
            "feed_first_output_delay_s": feed_delay_s,
            "score_first_output_delay_s": 0.0,
            "trajectory_available_before_score_s": score_lead_s,
            "preroll_pose_count": int(np.sum(body["indices"] < 900)),
            "preroll_camera_count": 900,
            "score_native_pose_count": int(len(estimate_stamps_ns)),
            "score_native_camera_count": 901,
            "score_native_coverage": float(len(estimate_stamps_ns) / 901.0),
        },
        "primary_se3_fixed_scale": {
            "definition": "reference_position = rotation * estimated_camera_position + translation; scale fixed to 1",
            "rotation": se3_rotation.tolist(),
            "translation": se3_translation.tolist(),
            "rotation_determinant": float(np.linalg.det(se3_rotation)),
            "translation_ape": metric_summary(se3_ape_errors),
            "translation_rpe_exact_1s_grid": metric_summary(se3_rpe_errors),
        },
        "secondary_sim3_scale_diagnostic": {
            "not_primary_metric": True,
            "must_not_replace_fixed_scale_result": True,
            "alignment": sim3_json(sim3),
            "translation_ape": metric_summary(sim3_ape_errors),
            "translation_rpe_exact_1s_grid": metric_summary(sim3_rpe_errors),
        },
        "statistics_policy": {
            "trajectory_run_count": 1,
            "independent_experimental_units": 1,
            "inferential_statistics_performed": False,
            "confidence_intervals_performed": False,
            "significance_tests_performed": False,
            "effect_size_between_systems_performed": False,
            "reason": "one frozen development-only trajectory; dense and overlapping temporal samples are dependent",
        },
        "inputs": {name: file_identity(path) for name, path in paths.items()},
    }

    grid_rows: List[Dict[str, object]] = []
    local_for_grid = {int(grid_index): local for local, grid_index in enumerate(common_indices)}
    for grid_index, stamp_ns in enumerate(grid_ns):
        local = local_for_grid.get(grid_index)
        row: Dict[str, object] = {
            "grid_index": grid_index,
            "timestamp_ns": int(stamp_ns),
            "relative_time_s": float(relative_grid_s[grid_index]),
            "reference_valid": int(reference.valid[grid_index]),
            "estimate_valid": int(estimate.valid[grid_index]),
            "common_valid": int(common_mask[grid_index]),
            "reference_method": str(reference.rejection_reasons[grid_index]),
            "estimate_method": str(estimate.rejection_reasons[grid_index]),
        }
        if local is not None:
            for prefix, values in (
                ("reference", reference_common[local]),
                ("estimate_raw_camera", estimate_common[local]),
                ("estimate_se3", se3_aligned[local]),
                ("estimate_sim3", sim3_aligned[local]),
            ):
                row.update({f"{prefix}_{axis}": float(values[index]) for index, axis in enumerate("xyz")})
            row["se3_ape_m"] = float(se3_ape_errors[local])
            row["sim3_ape_m"] = float(sim3_ape_errors[local])
        grid_rows.append(row)

    rpe_rows: List[Dict[str, object]] = []
    for pair_index, (left_grid, right_grid) in enumerate(pairs):
        left_local, right_local = pair_left[pair_index], pair_right[pair_index]
        rpe_rows.append(
            {
                "pair_index": pair_index,
                "left_grid_index": int(left_grid),
                "right_grid_index": int(right_grid),
                "left_timestamp_ns": int(grid_ns[left_grid]),
                "right_timestamp_ns": int(grid_ns[right_grid]),
                "delta_s": 1.0,
                "se3_translation_rpe_m": float(se3_rpe_errors[pair_index]),
                "sim3_translation_rpe_m": float(sim3_rpe_errors[pair_index]),
            }
        )

    result["_arrays"] = {
        "grid_rows": grid_rows,
        "rpe_rows": rpe_rows,
        "reference_common": reference_common,
        "se3_aligned": se3_aligned,
        "sim3_aligned": sim3_aligned,
        "relative_grid_s": relative_grid_s,
        "se3_ape_errors": se3_ape_errors,
        "sim3_ape_errors": sim3_ape_errors,
        "rpe_times_s": relative_grid_s[pairs[:, 1]],
        "se3_rpe_errors": se3_rpe_errors,
        "sim3_rpe_errors": sim3_rpe_errors,
    }
    return result


def markdown_reports(result: Mapping[str, Any]) -> Dict[str, str]:
    se3 = result["primary_se3_fixed_scale"]
    sim3 = result["secondary_sim3_scale_diagnostic"]
    support = result["support"]
    init = result["initialization_and_coverage"]
    analysis = f"""# HFNet H03 descriptive proxy evaluation

## Outcome

The frozen HFNet Phase-F H03 trajectory has valid reference support on all {support['matched_count']} points of the frozen 2 Hz evaluation grid.  Primary fixed-scale SE(3) translation APE is **{se3['translation_ape']['rmse_m']:.9f} m RMSE** (median {se3['translation_ape']['median_m']:.9f} m; max {se3['translation_ape']['max_m']:.9f} m).  Exact-1 s translation RPE is **{se3['translation_rpe_exact_1s_grid']['rmse_m']:.9f} m RMSE** over {support['rpe_pairs']} overlapping pairs (median {se3['translation_rpe_exact_1s_grid']['median_m']:.9f} m; max {se3['translation_rpe_exact_1s_grid']['max_m']:.9f} m).

The native score suffix covers {init['score_native_pose_count']}/{init['score_native_camera_count']} camera samples.  First usable trajectory output occurs {init['feed_first_output_delay_s']:.9f} s after feed start and {init['trajectory_available_before_score_s']:.9f} s before score start; scored-output delay is 0 s.

## Alignment and reference boundary

- Primary: fixed-scale SE(3), after converting `world_T_body` to `world_T_camera` with the exact runtime `body_T_camera` calibration.
- Secondary diagnostic only: Sim(3), fitted scale {sim3['alignment']['scale']:.9f}; it must not replace the fixed-scale result.
- Reference: updated AQUALOC H03 offline COLMAP camera trajectory, scale corrected with depth metadata.  It is reconstructed from the same image sequence and is not sensor-independent ground truth.
- Unit of analysis: one frozen development-only trajectory.  The 901 native timestamps, 91 evaluation-grid poses, and 89 overlapping RPE pairs are temporally dependent, not independent experimental samples.

## Claim candidates

- Claim:
  - Source evidence: `evaluation_result.json`, `grid_metrics.csv`, `rpe_pairs.csv`.
  - Allowed wording: the frozen H03 run has the reported descriptive translation errors against the image-derived COLMAP proxy and full frozen score coverage.
  - Forbidden stronger wording: independent-GT accuracy, statistical significance, superiority to another system, general underwater robustness, or a formal paper claim.
  - Uncertainty: one development-only sequence/run and image-derived reference.
  - Next check: repeat the same preregistered evaluator on genuinely held-out sequences and independent reference where available.
  - Decision: keep with caveat.
"""
    stats = f"""# Statistical appendix

## Descriptive support

- Independent experimental units: 1 trajectory run.
- Native score coverage: {init['score_native_pose_count']}/{init['score_native_camera_count']} = {init['score_native_coverage']:.9f}.
- Evaluation grid: {support['matched_count']}/{support['grid_count']} valid points across {support['common_span_s']:.9f} s.
- Translation RPE: {support['rpe_pairs']} overlapping exact-1 s pairs.
- Fixed-scale SE(3) APE RMSE / median / max: {se3['translation_ape']['rmse_m']:.9f} / {se3['translation_ape']['median_m']:.9f} / {se3['translation_ape']['max_m']:.9f} m.
- Fixed-scale SE(3) RPE RMSE / median / max: {se3['translation_rpe_exact_1s_grid']['rmse_m']:.9f} / {se3['translation_rpe_exact_1s_grid']['median_m']:.9f} / {se3['translation_rpe_exact_1s_grid']['max_m']:.9f} m.
- Sim(3) diagnostic scale: {sim3['alignment']['scale']:.9f}.

## Inferential-statistics gate

No confidence interval, p-value, significance test, between-system effect size, or winner declaration is valid here.  Camera frames and overlapping RPE pairs are repeated, dependent measurements from one trajectory and are not treated as n=901, n=91, or n=89 independent samples.
"""
    figures = """# Figure catalog

## figure-01-trajectory-xy.svg

- Purpose: show the XY geometry of the COLMAP proxy and the fixed-scale/diagnostic aligned estimates.
- Data source: `grid_metrics.csv`.
- Reader should notice: whether fixed-scale geometry follows the reference and how much the diagnostic scale fit changes it.
- Belief update: geometric visualization only; it does not create another experimental replicate.
- Caveat: XY projection hides Z error and the reference is image-derived.

## figure-02-errors-over-time.svg

- Purpose: show temporal concentration of translation APE and exact-1 s RPE.
- Data source: `grid_metrics.csv` and `rpe_pairs.csv`.
- Reader should notice: whether error is localized or sustained across the frozen score interval.
- Belief update: descriptive localization only; adjacent points and RPE pairs overlap.
- Caveat: no confidence band or inferential annotation is valid for this single dependent trajectory.
"""
    return {
        "analysis-output/analysis-report.md": analysis,
        "analysis-output/stats-appendix.md": stats,
        "analysis-output/figure-catalog.md": figures,
    }


def publish_result(result_with_arrays: Dict[str, Any], freeze: Mapping[str, Any]) -> Dict[str, Any]:
    arrays = result_with_arrays.pop("_arrays")
    if OUTPUT.exists() or OUTPUT.is_symlink():
        raise ContractError("OUTPUT_NAMESPACE_NOT_FRESH_AT_PUBLISH")
    os.mkdir(str(OUTPUT), 0o755)
    claim = {
        "schema_version": RESULT_SCHEMA + "-start-claim-v1",
        "status": "O_EXCL_CLAIM_BEFORE_PURE_EVALUATION_PUBLICATION",
        "authorization_token": AUTHORIZATION_TOKEN,
        "freeze": file_identity(FREEZE),
        "evaluator": file_identity(Path(__file__)),
        "process_starts": {"hfnet": 0, "vins": 0, "detector": 0, "ros": 0},
        "retry": False,
    }
    write_exclusive(OUTPUT / "evaluation_start_claim.json", canonical_json_bytes(claim))

    write_exclusive(OUTPUT / "evaluation_result.json", canonical_json_bytes(result_with_arrays))
    grid_rows = arrays["grid_rows"]
    grid_fields = list(grid_rows[0].keys())
    write_csv_exclusive(OUTPUT / "grid_metrics.csv", grid_fields, grid_rows)
    rpe_rows = arrays["rpe_rows"]
    write_csv_exclusive(OUTPUT / "rpe_pairs.csv", list(rpe_rows[0].keys()), rpe_rows)

    reports = markdown_reports(result_with_arrays)
    for relative, content in reports.items():
        write_exclusive(OUTPUT / relative, content.encode("utf-8"))

    ref = arrays["reference_common"]
    se3 = arrays["se3_aligned"]
    sim3 = arrays["sim3_aligned"]
    trajectory_svg = svg_line_plot(
        "H03 score trajectory XY (descriptive proxy)",
        "world X after alignment (m)",
        "world Y after alignment (m)",
        (
            ("COLMAP proxy", ref[:, 0], ref[:, 1], "#111827"),
            ("HFNet SE(3), primary", se3[:, 0], se3[:, 1], "#2563eb"),
            ("HFNet Sim(3), diagnostic", sim3[:, 0], sim3[:, 1], "#dc2626"),
        ),
    )
    error_svg = svg_line_plot(
        "H03 translation errors over frozen score time",
        "time from score start (s)",
        "translation error (m)",
        (
            ("SE(3) APE", arrays["relative_grid_s"], arrays["se3_ape_errors"], "#2563eb"),
            ("Sim(3) APE diagnostic", arrays["relative_grid_s"], arrays["sim3_ape_errors"], "#dc2626"),
            ("SE(3) 1 s RPE", arrays["rpe_times_s"], arrays["se3_rpe_errors"], "#059669"),
            ("Sim(3) 1 s RPE diagnostic", arrays["rpe_times_s"], arrays["sim3_rpe_errors"], "#d97706"),
        ),
    )
    write_exclusive(
        OUTPUT / "analysis-output/figures/figure-01-trajectory-xy.svg",
        trajectory_svg.encode("utf-8"),
    )
    write_exclusive(
        OUTPUT / "analysis-output/figures/figure-02-errors-over-time.svg",
        error_svg.encode("utf-8"),
    )

    records = []
    for path in sorted(OUTPUT.rglob("*"), key=lambda item: item.relative_to(OUTPUT).as_posix()):
        if path.is_file():
            identity = file_identity(path)
            identity["path"] = path.relative_to(OUTPUT).as_posix()
            records.append(identity)
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "status": "SEALED_DESCRIPTIVE_PROXY_EVALUATION_BUNDLE",
        "freeze": file_identity(FREEZE),
        "evaluator": file_identity(Path(__file__)),
        "result": file_identity(OUTPUT / "evaluation_result.json"),
        "files_excluding_manifest": records,
        "file_count_excluding_manifest": len(records),
        "total_bytes_excluding_manifest": sum(int(item["size_bytes"]) for item in records),
        "tree_sha256_excluding_manifest": hashlib.sha256(canonical_json_bytes(records)).hexdigest(),
        "process_starts": {"hfnet": 0, "vins": 0, "detector": 0, "ros": 0},
        "inferential_statistics": False,
        "reference_sensor_independent": False,
    }
    write_exclusive(OUTPUT / "artifact_manifest.json", canonical_json_bytes(manifest))
    for directory in sorted(
        [path for path in OUTPUT.rglob("*") if path.is_dir()],
        key=lambda item: len(item.parts),
        reverse=True,
    ):
        os.chmod(str(directory), 0o555)
    os.chmod(str(OUTPUT), 0o555)
    parent_fd = os.open(str(OUTPUT.parent), os.O_RDONLY)
    try:
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return manifest


def preflight() -> Dict[str, Any]:
    try:
        freeze, paths = audit_freeze(require_output_absent=True)
        camera_ns = load_camera_times(paths["cam0_times"])
        body = load_body_trajectory(paths["trajectory"], camera_ns)
        reference = load_reference(paths["reference_proxy"], camera_ns)
        body_t_camera = load_body_t_camera(paths["runtime_config"])
        return {
            "schema_version": RESULT_SCHEMA + "-preflight-v1",
            "status": "PRE_EVAL_GO",
            "return_code": RC_OK,
            "freeze": file_identity(FREEZE),
            "trajectory_pose_count": int(len(body["indices"])),
            "reference_score_pose_count": int(len(reference["source_indices"])),
            "body_T_camera": body_t_camera.tolist(),
            "output_absent": True,
            "claims": {
                "numeric_ape_rpe_computed": False,
                "filesystem_writes": False,
                "hfnet_started": False,
                "vins_started": False,
                "detector_started": False,
            },
        }
    except Exception as error:
        return {
            "schema_version": RESULT_SCHEMA + "-preflight-v1",
            "status": "PRE_EVAL_BLOCKED",
            "return_code": RC_BLOCKED,
            "errors": [f"{type(error).__name__}:{error}"],
            "claims": {"numeric_ape_rpe_computed": False, "filesystem_writes": False},
        }


def run_once(token: str) -> Dict[str, Any]:
    if token != AUTHORIZATION_TOKEN:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "EVALUATION_NOT_AUTHORIZED",
            "return_code": RC_BLOCKED,
            "errors": ["EXACT_AUTHORIZATION_TOKEN_REQUIRED"],
        }
    try:
        freeze, paths = audit_freeze(require_output_absent=True)
        result = evaluate(freeze, paths)
        manifest = publish_result(result, freeze)
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "PASS_DESCRIPTIVE_PROXY_EVALUATION_PUBLISHED",
            "return_code": RC_OK,
            "output": str(OUTPUT),
            "manifest": file_identity(OUTPUT / "artifact_manifest.json"),
            "result": file_identity(OUTPUT / "evaluation_result.json"),
            "file_count_excluding_manifest": manifest["file_count_excluding_manifest"],
            "claims": {
                "hfnet_started": False,
                "vins_started": False,
                "detector_started": False,
                "inferential_statistics": False,
            },
        }
    except Exception as error:
        return {
            "schema_version": RESULT_SCHEMA,
            "status": "EVALUATION_FAILED_OR_BLOCKED",
            "return_code": RC_FAILED if OUTPUT.exists() else RC_BLOCKED,
            "errors": [f"{type(error).__name__}:{error}"],
            "output_exists": OUTPUT.exists(),
        }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("preflight", "evaluate"), default="preflight")
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args(argv)
    decision = preflight() if args.action == "preflight" else run_once(args.authorization_token)
    sys.stdout.buffer.write(canonical_json_bytes(decision))
    return int(decision["return_code"])


if __name__ == "__main__":
    raise SystemExit(main())
