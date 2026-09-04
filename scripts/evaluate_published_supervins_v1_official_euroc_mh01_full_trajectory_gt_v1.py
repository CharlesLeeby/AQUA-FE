#!/usr/bin/env python3
"""One-shot, ROS-free GT evaluation of the sealed SuperVINS MH01 trajectory.

The ``preflight`` action validates identities, formats, timestamp support, and
freshness without reading positional errors or performing alignment.  The
``run`` action is authority-gated and burns exactly one additive attempt.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import traceback
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:
    from scripts.trajectory_eval_core import align_se3_positions as core_align_se3_positions
except ImportError:  # Direct absolute-path execution places scripts/ on sys.path.
    from trajectory_eval_core import align_se3_positions as core_align_se3_positions


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
TESTS = ROOT / "scripts/tests/test_evaluate_published_supervins_v1_official_euroc_mh01_full_trajectory_gt_v1.py"
FREEZE = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_gt_evaluation_freeze_v1.json"
LOCK = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_gt_evaluation_execution_lock_v1.json"
AUTHORITY = ROOT / "papers/supervins_v1_official_euroc_mh01_full_trajectory_gt_evaluation_execution_authority_v1.json"

EVIDENCE_ROOT = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_gt_evaluation_20260821_r1"
ATTEMPT = EVIDENCE_ROOT / "attempt_001"
ANALYSIS = ATTEMPT / "analysis-output"
FIGURES = ANALYSIS / "figures"
START_CLAIM = ATTEMPT / "evaluation_start_claim.json"
PREFLIGHT_RESULT = ATTEMPT / "preflight_result.json"
RUN_RESULT = ATTEMPT / "run_result.json"

STAGE4_RESULT = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1/attempt_001/run_result.json"
TRAJECTORY = ROOT / "experiments/published_supervins_v1_official_euroc_mh01_full_trajectory_20260817_r1/attempt_001/trajectory_output/vio.csv"
DATASET = Path("/mnt/data/AQUA-FE_WS/datasets/official_euroc_v1/MH01/MH_01_easy/mav0")
CAMERA_CSV = DATASET / "cam0/data.csv"
GT_CSV = DATASET / "state_groundtruth_estimate0/data.csv"
GT_SENSOR = DATASET / "state_groundtruth_estimate0/sensor.yaml"
IMU_SENSOR = DATASET / "imu0/sensor.yaml"
CORE = ROOT / "scripts/trajectory_eval_core.py"

TOKEN = "SUPERVINS_STAGE5_MH01_GT_EVALUATION_ATTEMPT_001_START_ONCE"
TOKEN_SHA256 = hashlib.sha256(TOKEN.encode("utf-8")).hexdigest()
CONTROLLER_COMMAND = [
    "/usr/bin/python3",
    "-B",
    str(RUNNER),
    "--action",
    "run",
    "--authorization-token",
    TOKEN,
]

FREEZE_SCHEMA = "aqua-fe-supervins-mh01-full-trajectory-gt-evaluation-freeze-v1"
LOCK_SCHEMA = "aqua-fe-supervins-mh01-full-trajectory-gt-evaluation-execution-lock-v1"
AUTHORITY_SCHEMA = "aqua-fe-supervins-mh01-full-trajectory-gt-evaluation-root-authority-v1"
RESULT_SCHEMA = "aqua-fe-supervins-mh01-full-trajectory-gt-evaluation-result-v1"

EXPECTED_TRAJECTORY_ROWS = 1810
EXPECTED_ESTIMATOR_OUTPUT_ROWS = 1841
EXPECTED_MISSING_INITIALIZATION_PREFIX = 31
EXPECTED_GT_ROWS = 36382
EXPECTED_CAMERA_ROWS = 3682
EXPECTED_MATCHED = 1799
EXPECTED_TAIL = 11
EXPECTED_RPE_PAIRS = 1789
CAMERA_FIRST_INDEX = 63
CAMERA_INDEX_STEP = 2
MAX_TEXT_TO_CAMERA_NS = 1000
RPE_INDEX_DELTA = 10
RPE_CAMERA_INDEX_DELTA = 20
RPE_NOMINAL_DELTA_NS = 1_000_000_000
RPE_DELTA_TOLERANCE_NS = 1000

REQUIRED_BUNDLE_FILES = [
    "analysis-output/metrics.json",
    "analysis-output/input-audit.json",
    "analysis-output/association-audit.json",
    "analysis-output/alignment.json",
    "analysis-output/associated-pairs.csv",
    "analysis-output/rpe-pairs-1s.csv",
    "analysis-output/analysis-report.md",
    "analysis-output/stats-appendix.md",
    "analysis-output/figure-catalog.md",
    "analysis-output/figures/figure-01-trajectory-overlay.svg",
    "analysis-output/figures/figure-02-error-over-time.svg",
    "analysis-output/artifact-manifest.json",
]

ASSOCIATED_HEADER = [
    "estimate_row_index", "camera_row_index", "estimate_timestamp_text", "display_timestamp_ns", "source_camera_timestamp_ns", "gt_row_index", "timestamp_text_minus_source_ns",
    "gt_x_m", "gt_y_m", "gt_z_m", "estimate_x_m", "estimate_y_m", "estimate_z_m",
    "se3_aligned_x_m", "se3_aligned_y_m", "se3_aligned_z_m", "se3_ape_m",
    "sim3_aligned_x_m", "sim3_aligned_y_m", "sim3_aligned_z_m", "sim3_ape_m",
]

RPE_HEADER = [
    "left_estimate_row_index", "right_estimate_row_index", "left_camera_row_index", "right_camera_row_index",
    "left_source_timestamp_ns", "right_source_timestamp_ns", "delta_ns", "se3_rpe_m", "sim3_rpe_m",
]

PENDING_SIGNAL: Optional[int] = None
NAMESPACE_OWNED = False
TERMINAL_COMMITTED = False


class ControlledSignal(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_identity(path: Path) -> Dict[str, Any]:
    info = path.stat()
    return {"sha256": sha256_file(path), "size_bytes": info.st_size}


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"
    ).encode("utf-8")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return json.load(stream)


def write_bytes_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> Dict[str, Any]:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            offset += os.write(descriptor, payload[offset:])
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    fsync_directory(path.parent)
    return file_identity(path)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def mkdir_exclusive_durable(path: Path, mode: int = 0o755) -> None:
    os.mkdir(str(path), mode)
    fsync_directory(path.parent)


def write_json_exclusive(path: Path, value: Any, mode: int = 0o444) -> Dict[str, Any]:
    return write_bytes_exclusive(path, canonical_json_bytes(value), mode=mode)


def write_text_exclusive(path: Path, text: str, mode: int = 0o444) -> Dict[str, Any]:
    return write_bytes_exclusive(path, text.encode("utf-8"), mode=mode)


def _signal_handler(signum: int, _frame: Any) -> None:
    global PENDING_SIGNAL
    if PENDING_SIGNAL is None:
        PENDING_SIGNAL = signum


def install_signal_handlers() -> Dict[int, Any]:
    previous: Dict[int, Any] = {}
    for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, _signal_handler)
    return previous


def restore_signal_handlers(previous: Mapping[int, Any]) -> None:
    for signum, handler in previous.items():
        signal.signal(signum, handler)


def raise_if_pending() -> None:
    if PENDING_SIGNAL is not None:
        raise ControlledSignal("caught signal {}".format(PENDING_SIGNAL))


def declared_identities(value: Any) -> Dict[str, Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if {"path", "sha256", "size_bytes"}.issubset(node):
                path = str(Path(str(node["path"])).resolve())
                expected = {"sha256": str(node["sha256"]), "size_bytes": int(node["size_bytes"])}
                if path in found and found[path] != expected:
                    raise ValueError("conflicting frozen identity for {}".format(path))
                found[path] = expected
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return found


def canonical_pin_digest(pins: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        {"path": path, "sha256": spec["sha256"], "size_bytes": int(spec["size_bytes"])}
        for path, spec in sorted(pins.items())
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def artifact_tree_digest(entries: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        {"path": path, "sha256": spec["sha256"], "size_bytes": int(spec["size_bytes"])}
        for path, spec in sorted(entries.items())
    ]
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def inspect_pins(expected: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    failures: List[str] = []
    for path_text, spec in sorted(expected.items()):
        path = Path(path_text)
        observed: Optional[Dict[str, Any]] = None
        error: Optional[str] = None
        try:
            observed = file_identity(path)
        except Exception as exc:  # Evidence, not control flow.
            error = "{}: {}".format(type(exc).__name__, exc)
        ok = observed == {"sha256": spec["sha256"], "size_bytes": int(spec["size_bytes"])}
        checks[path_text] = {"expected": dict(spec), "observed": observed, "error": error, "ok": ok}
        if not ok:
            failures.append(path_text)
    return {"checks": checks, "failures": failures, "ok": not failures}


def decimal_seconds_to_display_ns(text: str) -> int:
    if not re.fullmatch(r"[0-9]+\.[0-9]{6}", text):
        raise ValueError("trajectory timestamp is not fixed-six decimal: {}".format(text))
    try:
        value = Decimal(text) * Decimal(1_000_000_000)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal timestamp {}".format(text)) from exc
    integral = value.to_integral_value()
    if integral != value:
        raise ValueError("timestamp cannot be represented as integral display ns")
    return int(integral)


def audit_trajectory_structure(include_values: bool = False) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    previous: Optional[int] = None
    text_minus_source_histogram: Dict[str, int] = {}
    with TRAJECTORY.open("r", encoding="utf-8") as stream:
        for row_index, raw in enumerate(stream):
            line = raw.strip()
            if not line:
                raise ValueError("blank trajectory line {}".format(row_index + 1))
            fields = line.split()
            if len(fields) != 8:
                raise ValueError("trajectory line {} has {} columns".format(row_index + 1, len(fields)))
            display_ns = decimal_seconds_to_display_ns(fields[0])
            values = [float(item) for item in fields[1:]]
            if not all(math.isfinite(item) for item in values):
                raise ValueError("non-finite trajectory value at row {}".format(row_index))
            quaternion_norm = math.sqrt(sum(item * item for item in values[3:7]))
            if not (0.9 <= quaternion_norm <= 1.1):
                raise ValueError("invalid trajectory quaternion at row {}".format(row_index))
            if previous is not None and display_ns <= previous:
                raise ValueError("trajectory timestamps are not strictly increasing")
            previous = display_ns
            row: Dict[str, Any] = {
                "row_index": row_index,
                "timestamp_text": fields[0],
                "display_timestamp_ns": display_ns,
            }
            if include_values:
                row["position"] = values[0:3]
                row["quaternion_xyzw"] = values[3:7]
            rows.append(row)
    return {
        "rows": rows,
        "row_count": len(rows),
        "first_timestamp_text": rows[0]["timestamp_text"] if rows else None,
        "last_timestamp_text": rows[-1]["timestamp_text"] if rows else None,
        "text_minus_source_histogram": text_minus_source_histogram,
    }


def audit_camera_structure() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    with CAMERA_CSV.open("r", encoding="utf-8", newline="") as stream:
        for record in csv.reader(stream):
            if not record or record[0].startswith("#"):
                continue
            if len(record) != 2:
                raise ValueError("camera CSV row has {} columns".format(len(record)))
            timestamp_ns = int(record[0])
            if rows and timestamp_ns <= rows[-1]["timestamp_ns"]:
                raise ValueError("camera timestamps are not strictly increasing")
            rows.append({"row_index": len(rows), "timestamp_ns": timestamp_ns, "filename": record[1]})
    return {"rows": rows, "row_count": len(rows)}


def audit_gt_structure(include_values: bool = False) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    with GT_CSV.open("r", encoding="utf-8", newline="") as stream:
        for record in csv.reader(stream):
            if not record or record[0].startswith("#"):
                continue
            if len(record) != 17:
                raise ValueError("GT CSV row has {} columns".format(len(record)))
            timestamp_ns = int(record[0])
            values = [float(item) for item in record[1:]]
            if not all(math.isfinite(item) for item in values):
                raise ValueError("GT row {} has non-finite values".format(len(rows)))
            quaternion_wxyz = values[3:7]
            quaternion_norm = math.sqrt(sum(item * item for item in quaternion_wxyz))
            if not (0.999 <= quaternion_norm <= 1.001):
                raise ValueError("GT row {} has invalid quaternion".format(len(rows)))
            if rows and timestamp_ns <= rows[-1]["timestamp_ns"]:
                raise ValueError("GT timestamps are not strictly increasing")
            row: Dict[str, Any] = {"row_index": len(rows), "timestamp_ns": timestamp_ns}
            if include_values:
                row["position"] = values[0:3]
                row["quaternion_xyzw"] = [values[4], values[5], values[6], values[3]]
            rows.append(row)
    return {
        "rows": rows,
        "row_count": len(rows),
        "first_timestamp_ns": rows[0]["timestamp_ns"] if rows else None,
        "last_timestamp_ns": rows[-1]["timestamp_ns"] if rows else None,
    }


def parse_t_bs(path: Path) -> List[List[float]]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"T_BS:.*?data:\s*\[(.*?)\]", text, flags=re.DOTALL)
    if not match:
        raise ValueError("T_BS matrix not found in {}".format(path))
    values = [float(token) for token in re.split(r"[\s,]+", match.group(1).strip()) if token]
    if len(values) != 16:
        raise ValueError("T_BS matrix in {} has {} values".format(path, len(values)))
    return [values[index : index + 4] for index in range(0, 16, 4)]


def associate_via_official_camera(
    trajectory_rows: Sequence[Mapping[str, Any]],
    camera_rows: Sequence[Mapping[str, Any]],
    gt_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    camera_ns = [int(row["timestamp_ns"]) for row in camera_rows]
    gt_by_ns = {int(row["timestamp_ns"]): int(row["row_index"]) for row in gt_rows}
    if len(gt_by_ns) != len(gt_rows):
        raise ValueError("GT timestamps are not unique")
    matched: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    errors: List[str] = []
    used_camera: set[int] = set()
    used_gt: set[int] = set()
    signed_histogram: Dict[str, int] = {}
    gt_first = int(gt_rows[0]["timestamp_ns"])
    gt_last = int(gt_rows[-1]["timestamp_ns"])

    for trajectory_row in trajectory_rows:
        trajectory_index = int(trajectory_row["row_index"])
        display_ns = int(trajectory_row["display_timestamp_ns"])
        insertion = bisect.bisect_left(camera_ns, display_ns)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(camera_ns)]
        candidates.sort(key=lambda index: (abs(camera_ns[index] - display_ns), index))
        if not candidates:
            errors.append("trajectory row {} has no camera candidate".format(trajectory_index))
            continue
        nearest = candidates[0]
        nearest_delta = abs(camera_ns[nearest] - display_ns)
        tied = [index for index in candidates if abs(camera_ns[index] - display_ns) == nearest_delta]
        expected_camera_index = CAMERA_FIRST_INDEX + CAMERA_INDEX_STEP * trajectory_index
        if len(tied) != 1:
            errors.append("trajectory row {} has non-unique nearest camera".format(trajectory_index))
            continue
        if nearest_delta > MAX_TEXT_TO_CAMERA_NS:
            errors.append("trajectory row {} camera delta {} ns exceeds tolerance".format(trajectory_index, nearest_delta))
            continue
        if nearest != expected_camera_index:
            errors.append(
                "trajectory row {} maps to camera {}, expected {}".format(
                    trajectory_index, nearest, expected_camera_index
                )
            )
            continue
        if nearest in used_camera:
            errors.append("camera row {} reused".format(nearest))
            continue
        used_camera.add(nearest)
        source_ns = camera_ns[nearest]
        signed_delta = display_ns - source_ns
        signed_histogram[str(signed_delta)] = signed_histogram.get(str(signed_delta), 0) + 1
        base = {
            "estimate_row_index": trajectory_index,
            "camera_row_index": nearest,
            "estimate_timestamp_text": trajectory_row["timestamp_text"],
            "display_timestamp_ns": display_ns,
            "source_camera_timestamp_ns": source_ns,
            "timestamp_text_minus_source_ns": signed_delta,
        }
        if source_ns in gt_by_ns:
            gt_index = gt_by_ns[source_ns]
            if gt_index in used_gt:
                errors.append("GT row {} reused".format(gt_index))
                continue
            used_gt.add(gt_index)
            entry = dict(base)
            entry["gt_row_index"] = gt_index
            matched.append(entry)
        elif source_ns > gt_last or source_ns < gt_first:
            entry = dict(base)
            entry["reason"] = "EXCLUDED_OUTSIDE_GT_COVERAGE"
            excluded.append(entry)
        else:
            errors.append(
                "camera timestamp {} is within GT range but has no exact GT row".format(source_ns)
            )

    return {
        "matched": matched,
        "excluded": excluded,
        "errors": errors,
        "trajectory_row_count": len(trajectory_rows),
        "unique_camera_row_count": len(used_camera),
        "unique_gt_row_count": len(used_gt),
        "matched_count": len(matched),
        "excluded_count": len(excluded),
        "max_abs_text_to_camera_ns": max(
            [abs(int(row["timestamp_text_minus_source_ns"])) for row in matched + excluded] or [0]
        ),
        "signed_text_minus_source_ns_histogram": signed_histogram,
    }


def generation_support_audit(
    camera_rows: Sequence[Mapping[str, Any]],
    association: Mapping[str, Any],
) -> Dict[str, Any]:
    expected_indices = list(range(1, len(camera_rows), CAMERA_INDEX_STEP))
    associated_rows = sorted(
        list(association["matched"]) + list(association["excluded"]),
        key=lambda row: int(row["estimate_row_index"]),
    )
    generated_indices = [int(row["camera_row_index"]) for row in associated_rows]
    if generated_indices and generated_indices[0] in expected_indices:
        first_expected_position = expected_indices.index(generated_indices[0])
    else:
        first_expected_position = None
    if generated_indices and generated_indices[-1] in expected_indices:
        last_expected_position = expected_indices.index(generated_indices[-1])
    else:
        last_expected_position = None
    missing_prefix = first_expected_position if first_expected_position is not None else len(expected_indices)
    expected_between = (
        expected_indices[first_expected_position : last_expected_position + 1]
        if first_expected_position is not None and last_expected_position is not None
        else []
    )
    generated_set = set(generated_indices)
    missing_interior = [index for index in expected_between if index not in generated_set]
    missing_terminal = (
        expected_indices[last_expected_position + 1 :]
        if last_expected_position is not None
        else expected_indices
    )
    first_source_ns = int(associated_rows[0]["source_camera_timestamp_ns"]) if associated_rows else None
    first_cam_ns = int(camera_rows[0]["timestamp_ns"]) if camera_rows else None
    first_expected_ns = int(camera_rows[1]["timestamp_ns"]) if len(camera_rows) > 1 else None

    def fraction(numerator: int, denominator: int) -> Dict[str, Any]:
        value = numerator / denominator
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": value,
            "decimal_17g": format(value, ".17g"),
        }

    audit = {
        "expected_estimator_output_rows": len(expected_indices),
        "expected_first_camera_row_index": expected_indices[0] if expected_indices else None,
        "expected_last_camera_row_index": expected_indices[-1] if expected_indices else None,
        "generated_trajectory_rows": len(generated_indices),
        "generated_first_camera_row_index": generated_indices[0] if generated_indices else None,
        "generated_last_camera_row_index": generated_indices[-1] if generated_indices else None,
        "generated_camera_rows_are_exact_contiguous_suffix": (
            first_expected_position is not None
            and generated_indices == expected_indices[first_expected_position:]
        ),
        "missing_initialization_prefix_rows": missing_prefix,
        "missing_interior_rows": len(missing_interior),
        "missing_terminal_rows": len(missing_terminal),
        "generation_coverage": fraction(len(generated_indices), len(expected_indices)),
        "first_generated_output_delay_from_sequence_cam0_ns": (
            first_source_ns - first_cam_ns if first_source_ns is not None and first_cam_ns is not None else None
        ),
        "first_generated_output_delay_from_sequence_cam0_s": (
            (first_source_ns - first_cam_ns) / 1e9
            if first_source_ns is not None and first_cam_ns is not None
            else None
        ),
        "first_generated_output_delay_from_first_expected_output_ns": (
            first_source_ns - first_expected_ns
            if first_source_ns is not None and first_expected_ns is not None
            else None
        ),
        "first_generated_output_delay_from_first_expected_output_s": (
            (first_source_ns - first_expected_ns) / 1e9
            if first_source_ns is not None and first_expected_ns is not None
            else None
        ),
        "gt_evaluable_generated": fraction(int(association["matched_count"]), len(generated_indices)),
        "gt_evaluable_expected": fraction(int(association["matched_count"]), len(expected_indices)),
        "excluded_tail_is_gt_coverage_not_generation_failure": (
            int(association["excluded_count"]) == EXPECTED_TAIL
            and all(row.get("reason") == "EXCLUDED_OUTSIDE_GT_COVERAGE" for row in association["excluded"])
        ),
    }
    audit["ok"] = (
        audit["expected_estimator_output_rows"] == EXPECTED_ESTIMATOR_OUTPUT_ROWS
        and audit["expected_first_camera_row_index"] == 1
        and audit["expected_last_camera_row_index"] == 3681
        and audit["generated_trajectory_rows"] == EXPECTED_TRAJECTORY_ROWS
        and audit["generated_first_camera_row_index"] == CAMERA_FIRST_INDEX
        and audit["generated_last_camera_row_index"] == 3681
        and audit["generated_camera_rows_are_exact_contiguous_suffix"] is True
        and audit["missing_initialization_prefix_rows"] == EXPECTED_MISSING_INITIALIZATION_PREFIX
        and audit["missing_interior_rows"] == 0
        and audit["missing_terminal_rows"] == 0
        and audit["first_generated_output_delay_from_sequence_cam0_ns"] == 3_149_999_872
        and audit["first_generated_output_delay_from_first_expected_output_ns"] == 3_100_000_000
        and audit["gt_evaluable_generated"]["numerator"] == EXPECTED_MATCHED
        and audit["gt_evaluable_generated"]["denominator"] == EXPECTED_TRAJECTORY_ROWS
        and audit["gt_evaluable_expected"]["numerator"] == EXPECTED_MATCHED
        and audit["gt_evaluable_expected"]["denominator"] == EXPECTED_ESTIMATOR_OUTPUT_ROWS
        and audit["excluded_tail_is_gt_coverage_not_generation_failure"] is True
    )
    return audit


def build_rpe_pairs(associations: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    pairs: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for left_position in range(max(0, len(associations) - RPE_INDEX_DELTA)):
        right_position = left_position + RPE_INDEX_DELTA
        left = associations[left_position]
        right = associations[right_position]
        source_index_delta = int(right["estimate_row_index"]) - int(left["estimate_row_index"])
        camera_index_delta = int(right["camera_row_index"]) - int(left["camera_row_index"])
        contiguous = all(
            int(associations[index + 1]["estimate_row_index"])
            == int(associations[index]["estimate_row_index"]) + 1
            and int(associations[index + 1]["camera_row_index"])
            == int(associations[index]["camera_row_index"]) + CAMERA_INDEX_STEP
            for index in range(left_position, right_position)
        )
        delta_ns = int(right["source_camera_timestamp_ns"]) - int(left["source_camera_timestamp_ns"])
        ok = (
            source_index_delta == RPE_INDEX_DELTA
            and camera_index_delta == RPE_CAMERA_INDEX_DELTA
            and contiguous
            and abs(delta_ns - RPE_NOMINAL_DELTA_NS) <= RPE_DELTA_TOLERANCE_NS
        )
        entry = {
            "left_association_index": left_position,
            "right_association_index": right_position,
            "left_estimate_row_index": int(left["estimate_row_index"]),
            "right_estimate_row_index": int(right["estimate_row_index"]),
            "left_camera_row_index": int(left["camera_row_index"]),
            "right_camera_row_index": int(right["camera_row_index"]),
            "left_source_timestamp_ns": int(left["source_camera_timestamp_ns"]),
            "right_source_timestamp_ns": int(right["source_camera_timestamp_ns"]),
            "delta_ns": delta_ns,
            "contiguous": contiguous,
        }
        (pairs if ok else rejected).append(entry)
    return {
        "pairs": pairs,
        "rejected": rejected,
        "pair_count": len(pairs),
        "actual_delta_min_ns": min([row["delta_ns"] for row in pairs] or [0]),
        "actual_delta_max_ns": max([row["delta_ns"] for row in pairs] or [0]),
    }


def relevant_processes() -> List[Dict[str, Any]]:
    patterns = (
        "supervins_node",
        "publish_supervins_euroc_mh01_full_v1.py",
        "run_published_supervins_v1_official_euroc_mh01_full_trajectory_v1.py --action run",
        "roscore -p 11555",
        "rosmaster --core -p 11555",
    )
    rows: List[Dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            command = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        except Exception:
            continue
        if any(pattern in command for pattern in patterns):
            rows.append({"pid": int(entry.name), "command": command})
    return sorted(rows, key=lambda row: row["pid"])


def validate_authority(authority: Any, lock: Mapping[str, Any]) -> List[str]:
    failures: List[str] = []

    def require(condition: bool, name: str) -> None:
        if not condition:
            failures.append(name)

    runner_identity = file_identity(RUNNER)
    tests_identity = file_identity(TESTS)
    freeze_identity = file_identity(FREEZE)
    lock_identity = file_identity(LOCK)
    require(isinstance(authority, dict), "authority_not_object")
    if not isinstance(authority, dict):
        return failures
    require(authority.get("schema_version") == AUTHORITY_SCHEMA, "authority_schema")
    require(
        authority.get("status") == "AUTHORIZED_EXACTLY_ONE_PURE_GT_EVALUATION_ATTEMPT_001_START",
        "authority_status",
    )
    require(authority.get("root_confirmation") is True, "authority_root_confirmation")
    require(authority.get("authorization_token_sha256") == TOKEN_SHA256, "authority_token")
    require(authority.get("fresh_evidence_root") == str(EVIDENCE_ROOT), "authority_root")
    require(authority.get("controller_command") == CONTROLLER_COMMAND, "authority_command")
    require(authority.get("protocol") == freeze_identity, "authority_protocol_identity")
    require(authority.get("lock") == lock_identity, "authority_lock_identity")
    require(authority.get("runner") == runner_identity, "authority_runner_identity")
    require(authority.get("tests") == tests_identity, "authority_tests_identity")
    require(authority.get("maximum_evaluator_starts") == 1, "authority_start_limit")
    require(authority.get("retry_authorized") is False, "authority_retry")
    boundary = authority.get("claim_boundary", {})
    require(boundary.get("pure_gt_computation_only") is True, "authority_pure_gt_only")
    for key in (
        "model_or_ros_rerun_authorized",
        "cross_system_comparison_authorized",
        "superiority_claim_authorized",
        "statistical_inference_authorized",
    ):
        require(boundary.get(key) is False, "authority_boundary_{}".format(key))
    return failures


def collect_preflight(require_authority: bool = False) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    failures: List[str] = []

    def check(name: str, ok: bool, observed: Any = None, expected: Any = None) -> None:
        checks[name] = {"ok": bool(ok), "observed": observed, "expected": expected}
        if not ok:
            failures.append(name)

    freeze: Any = None
    lock: Any = None
    try:
        freeze = load_json(FREEZE)
        check("freeze_schema", freeze.get("schema_version") == FREEZE_SCHEMA, freeze.get("schema_version"), FREEZE_SCHEMA)
        freeze_stat = FREEZE.stat()
        check(
            "freeze_seal",
            stat.S_IMODE(freeze_stat.st_mode) == 0o444 and freeze_stat.st_nlink == 1,
            {"mode": oct(stat.S_IMODE(freeze_stat.st_mode)), "nlink": freeze_stat.st_nlink},
            {"mode": "0o444", "nlink": 1},
        )
    except Exception as exc:
        check("freeze_readable", False, "{}: {}".format(type(exc).__name__, exc), "valid JSON")

    try:
        lock = load_json(LOCK)
        check("lock_schema", lock.get("schema_version") == LOCK_SCHEMA, lock.get("schema_version"), LOCK_SCHEMA)
        check(
            "lock_status",
            lock.get("status") == "LOCKED_PRESTART_AWAITING_SEPARATE_ROOT_EXECUTION_AUTHORITY",
            lock.get("status"),
            "LOCKED_PRESTART_AWAITING_SEPARATE_ROOT_EXECUTION_AUTHORITY",
        )
        check("lock_command", lock.get("controller_command") == CONTROLLER_COMMAND, lock.get("controller_command"), CONTROLLER_COMMAND)
        check("lock_token", lock.get("authorization_token") == TOKEN, lock.get("authorization_token"), TOKEN)
        check("lock_start_limit", lock.get("maximum_evaluator_starts") == 1, lock.get("maximum_evaluator_starts"), 1)
        check("lock_retry", lock.get("retry_authorized") is False, lock.get("retry_authorized"), False)
        lock_stat = LOCK.stat()
        check(
            "lock_seal",
            stat.S_IMODE(lock_stat.st_mode) == 0o444 and lock_stat.st_nlink == 1,
            {"mode": oct(stat.S_IMODE(lock_stat.st_mode)), "nlink": lock_stat.st_nlink},
            {"mode": "0o444", "nlink": 1},
        )
    except Exception as exc:
        check("lock_readable", False, "{}: {}".format(type(exc).__name__, exc), "valid execution lock")

    expected_pins: Dict[str, Dict[str, Any]] = {}
    if isinstance(freeze, dict):
        try:
            expected_pins.update(declared_identities(freeze))
        except Exception as exc:
            check("freeze_declared_identities", False, str(exc), "no conflicting identities")
    if isinstance(lock, dict):
        lock_pins = lock.get("pinned_files", {})
        if isinstance(lock_pins, dict):
            for path, spec in lock_pins.items():
                normalized = str(Path(path).resolve())
                expected = {"sha256": spec.get("sha256"), "size_bytes": spec.get("size_bytes")}
                if normalized in expected_pins and expected_pins[normalized] != expected:
                    check("lock_pin_conflict_{}".format(normalized), False, expected, expected_pins[normalized])
                expected_pins[normalized] = expected
            digest = canonical_pin_digest(lock_pins)
            check(
                "lock_pin_digest",
                digest == lock.get("pinned_files_canonical_sha256"),
                digest,
                lock.get("pinned_files_canonical_sha256"),
            )
        else:
            check("lock_pinned_files", False, type(lock_pins).__name__, "object")

    pin_audit = inspect_pins(expected_pins) if expected_pins else {"checks": {}, "failures": [], "ok": False}
    check("all_frozen_pins", pin_audit["ok"], pin_audit["failures"], [])

    try:
        result = load_json(STAGE4_RESULT)
        stage4_ok = (
            result.get("status") == "PASS_DEVELOPMENT_OFFICIAL_MH01_FULL_TRAJECTORY_GENERATION"
            and result.get("return_code") == 0
            and result.get("evaluable") is True
            and result.get("claim_boundary", {}).get("groundtruth_consumed") is False
        )
        check("stage4_terminal_result", stage4_ok, {k: result.get(k) for k in ("status", "return_code", "evaluable")}, "sealed PASS/0/evaluable")
        mode = stat.S_IMODE(STAGE4_RESULT.stat().st_mode)
        check("stage4_result_mode", mode == 0o444 and STAGE4_RESULT.stat().st_nlink == 1, {"mode": oct(mode), "nlink": STAGE4_RESULT.stat().st_nlink}, {"mode": "0o444", "nlink": 1})
    except Exception as exc:
        check("stage4_terminal_result", False, "{}: {}".format(type(exc).__name__, exc), "sealed PASS")

    timestamp_audit: Optional[Dict[str, Any]] = None
    try:
        trajectory_audit = audit_trajectory_structure(include_values=False)
        camera_audit = audit_camera_structure()
        gt_audit = audit_gt_structure(include_values=False)
        association = associate_via_official_camera(trajectory_audit["rows"], camera_audit["rows"], gt_audit["rows"])
        rpe = build_rpe_pairs(association["matched"])
        generation = generation_support_audit(camera_audit["rows"], association)
        timestamp_audit = {
            "trajectory_row_count": trajectory_audit["row_count"],
            "trajectory_first_timestamp_text": trajectory_audit["first_timestamp_text"],
            "trajectory_last_timestamp_text": trajectory_audit["last_timestamp_text"],
            "camera_row_count": camera_audit["row_count"],
            "gt_row_count": gt_audit["row_count"],
            "gt_first_timestamp_ns": gt_audit["first_timestamp_ns"],
            "gt_last_timestamp_ns": gt_audit["last_timestamp_ns"],
            "matched_count": association["matched_count"],
            "excluded_tail_count": association["excluded_count"],
            "unique_camera_row_count": association["unique_camera_row_count"],
            "unique_gt_row_count": association["unique_gt_row_count"],
            "max_abs_text_to_camera_ns": association["max_abs_text_to_camera_ns"],
            "signed_text_minus_source_ns_histogram": association["signed_text_minus_source_ns_histogram"],
            "association_errors": association["errors"],
            "first_matched": association["matched"][0] if association["matched"] else None,
            "last_matched": association["matched"][-1] if association["matched"] else None,
            "first_excluded": association["excluded"][0] if association["excluded"] else None,
            "rpe_pair_count": rpe["pair_count"],
            "rpe_rejected_count": len(rpe["rejected"]),
            "rpe_actual_delta_min_ns": rpe["actual_delta_min_ns"],
            "rpe_actual_delta_max_ns": rpe["actual_delta_max_ns"],
            "generation_support": generation,
        }
        association_ok = (
            trajectory_audit["row_count"] == EXPECTED_TRAJECTORY_ROWS
            and camera_audit["row_count"] == EXPECTED_CAMERA_ROWS
            and gt_audit["row_count"] == EXPECTED_GT_ROWS
            and association["matched_count"] == EXPECTED_MATCHED
            and association["excluded_count"] == EXPECTED_TAIL
            and association["unique_camera_row_count"] == EXPECTED_TRAJECTORY_ROWS
            and association["unique_gt_row_count"] == EXPECTED_MATCHED
            and association["max_abs_text_to_camera_ns"] == 544
            and association["signed_text_minus_source_ns_histogram"] == {"-456": 1086, "544": 724}
            and not association["errors"]
            and rpe["pair_count"] == EXPECTED_RPE_PAIRS
            and not rpe["rejected"]
            and rpe["actual_delta_min_ns"] == RPE_NOMINAL_DELTA_NS
            and rpe["actual_delta_max_ns"] == RPE_NOMINAL_DELTA_NS
            and generation["ok"] is True
        )
        check("timestamp_only_association_contract", association_ok, timestamp_audit, "exact frozen counts and deltas")
    except Exception as exc:
        check("timestamp_only_association_contract", False, "{}: {}".format(type(exc).__name__, exc), "exact frozen counts and deltas")

    identity_matrix = [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]
    try:
        gt_t_bs = parse_t_bs(GT_SENSOR)
        imu_t_bs = parse_t_bs(IMU_SENSOR)
        check("body_frame_identity", gt_t_bs == identity_matrix and imu_t_bs == identity_matrix, {"gt": gt_t_bs, "imu": imu_t_bs}, identity_matrix)
    except Exception as exc:
        check("body_frame_identity", False, "{}: {}".format(type(exc).__name__, exc), identity_matrix)

    check("numpy_version", np.__version__ == "1.24.4", np.__version__, "1.24.4")
    check("fresh_evidence_root", not EVIDENCE_ROOT.exists(), "ABSENT" if not EVIDENCE_ROOT.exists() else "PRESENT", "ABSENT")
    processes = relevant_processes()
    check("no_stage4_ros_or_model_processes", not processes, processes, [])

    authority_state: Dict[str, Any]
    if AUTHORITY.exists():
        try:
            authority = load_json(AUTHORITY)
            authority_failures = validate_authority(authority, lock if isinstance(lock, dict) else {})
            authority_stat = AUTHORITY.stat()
            if stat.S_IMODE(authority_stat.st_mode) != 0o444 or authority_stat.st_nlink != 1:
                authority_failures.append("authority_seal")
            authority_state = {"present": True, "identity": file_identity(AUTHORITY), "failures": authority_failures}
            check("authority_valid", not authority_failures, authority_failures, [])
        except Exception as exc:
            authority_state = {"present": True, "error": "{}: {}".format(type(exc).__name__, exc)}
            check("authority_valid", False, authority_state, "valid authority")
    else:
        authority_state = {"present": False}
        if require_authority:
            check("authority_required", False, "ABSENT", "PRESENT and valid")

    if require_authority and AUTHORITY.exists() and str(AUTHORITY.resolve()) not in expected_pins:
        # Authority is dynamic after lock; snapshot it for immutable postflight comparison.
        try:
            authority_identity = file_identity(AUTHORITY)
            expected_pins[str(AUTHORITY.resolve())] = authority_identity
            pin_audit = inspect_pins(expected_pins)
        except Exception as exc:
            check("authority_snapshot", False, str(exc), "stable identity")

    ready = not failures
    if ready and authority_state.get("present"):
        status = "GO_EXACTLY_ONE_PURE_GT_EVALUATION_START"
    elif ready:
        status = "GO_PRESTART_ONLY_AWAITING_ROOT_EXECUTION_AUTHORITY"
    else:
        status = "NO_GO"
    return {
        "schema_version": "aqua-fe-supervins-mh01-gt-evaluation-preflight-v1",
        "checked_at": now_iso(),
        "status": status,
        "ready": ready,
        "failures": failures,
        "check_count": len(checks),
        "checks": checks,
        "timestamp_only_audit": timestamp_audit,
        "authority": authority_state,
        "pin_snapshot": pin_audit,
        "scientific_computation_run": False,
        "boundary": {
            "trajectory_positions_aligned": False,
            "ape_computed": False,
            "rpe_computed": False,
            "ros_or_model_started": False,
        },
    }


def rigid_se3_alignment(source: np.ndarray, target: np.ndarray) -> Dict[str, Any]:
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("SE3 alignment inputs must be matching Nx3 arrays with N>=3")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = source_centered.T @ target_centered
    rank_audit = {
        "source_rank": int(np.linalg.matrix_rank(source_centered)),
        "target_rank": int(np.linalg.matrix_rank(target_centered)),
        "covariance_rank": int(np.linalg.matrix_rank(covariance)),
    }
    if min(rank_audit.values()) < 2:
        raise ValueError("SE3 alignment requires source/target/covariance rank >=2")
    u_matrix, singular_values, vt_matrix = np.linalg.svd(covariance)
    rotation = vt_matrix.T @ u_matrix.T
    if np.linalg.det(rotation) < 0.0:
        vt_matrix[-1, :] *= -1.0
        rotation = vt_matrix.T @ u_matrix.T
    translation = target_mean - rotation @ source_mean
    aligned = (rotation @ source.T).T + translation
    return {
        "rotation": rotation,
        "translation": translation,
        "scale": 1.0,
        "aligned": aligned,
        "singular_values": singular_values,
        "rank_audit": rank_audit,
    }


def proper_umeyama_sim3(source: np.ndarray, target: np.ndarray) -> Dict[str, Any]:
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3 or len(source) < 3:
        raise ValueError("Sim3 alignment inputs must be matching Nx3 arrays with N>=3")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    covariance = (target_centered.T @ source_centered) / float(len(source))
    rank_audit = {
        "source_rank": int(np.linalg.matrix_rank(source_centered)),
        "target_rank": int(np.linalg.matrix_rank(target_centered)),
        "covariance_rank": int(np.linalg.matrix_rank(covariance)),
    }
    if min(rank_audit.values()) < 2:
        raise ValueError("Sim3 alignment requires source/target/covariance rank >=2")
    u_matrix, singular_values, vt_matrix = np.linalg.svd(covariance)
    diagonal = np.ones(3, dtype=float)
    if np.linalg.det(u_matrix) * np.linalg.det(vt_matrix) < 0.0:
        diagonal[-1] = -1.0
    rotation = u_matrix @ np.diag(diagonal) @ vt_matrix
    variance = float(np.mean(np.sum(source_centered * source_centered, axis=1)))
    if not math.isfinite(variance) or variance <= 1e-15:
        raise ValueError("source variance is insufficient for Sim3")
    scale = float(np.dot(singular_values, diagonal) / variance)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Sim3 scale must be finite and positive")
    translation = target_mean - scale * (rotation @ source_mean)
    aligned = scale * (rotation @ source.T).T + translation
    return {
        "rotation": rotation,
        "translation": translation,
        "scale": scale,
        "aligned": aligned,
        "singular_values": singular_values,
        "rank_audit": rank_audit,
    }


def alignment_audit(alignment: Mapping[str, Any]) -> Dict[str, Any]:
    rotation = np.asarray(alignment["rotation"], dtype=float)
    translation = np.asarray(alignment["translation"], dtype=float)
    scale = float(alignment["scale"])
    determinant = float(np.linalg.det(rotation))
    orthonormal_error = float(np.max(np.abs(rotation.T @ rotation - np.eye(3))))
    finite = bool(
        np.all(np.isfinite(rotation))
        and np.all(np.isfinite(translation))
        and math.isfinite(scale)
    )
    rank_audit = dict(alignment.get("rank_audit", {}))
    rank_ok = (
        set(rank_audit) == {"source_rank", "target_rank", "covariance_rank"}
        and min(int(value) for value in rank_audit.values()) >= 2
    )
    proper = finite and scale > 0.0 and abs(determinant - 1.0) <= 1e-12 and orthonormal_error <= 1e-12 and rank_ok
    return {
        "rotation": rotation.tolist(),
        "translation": translation.tolist(),
        "scale": scale,
        "rotation_determinant": determinant,
        "rotation_orthonormal_max_abs_error": orthonormal_error,
        "finite": finite,
        "rank_audit": rank_audit,
        "rank_ok": rank_ok,
        "proper": proper,
    }


def descriptive_stats(errors: np.ndarray) -> Dict[str, Any]:
    values = np.asarray(errors, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("metric sample array must be non-empty and one-dimensional")
    if not np.all(np.isfinite(values)) or np.any(values < 0.0):
        raise ValueError("metric samples must be finite and nonnegative")
    return {
        "n": int(len(values)),
        "rmse_m": float(np.sqrt(np.mean(values * values))),
        "mean_m": float(np.mean(values)),
        "population_std_m": float(np.std(values, ddof=0)),
        "median_m": float(np.median(values)),
        "min_m": float(np.min(values)),
        "p90_m": float(np.quantile(values, 0.90, method="linear")),
        "p95_m": float(np.quantile(values, 0.95, method="linear")),
        "max_m": float(np.max(values)),
        "sse_m2": float(np.sum(values * values)),
    }


def metrics_are_finite_nonnegative(metrics: Mapping[str, Any]) -> bool:
    expected_counts = {
        ("primary_fixed_scale_se3", "ape"): EXPECTED_MATCHED,
        ("primary_fixed_scale_se3", "rpe_1s"): EXPECTED_RPE_PAIRS,
        ("secondary_sim3_scale_diagnostic", "ape"): EXPECTED_MATCHED,
        ("secondary_sim3_scale_diagnostic", "rpe_1s"): EXPECTED_RPE_PAIRS,
    }
    numeric_keys = {
        "rmse_m", "mean_m", "population_std_m", "median_m", "min_m",
        "p90_m", "p95_m", "max_m", "sse_m2",
    }
    try:
        for (alignment_key, metric_key), count in expected_counts.items():
            stats_row = metrics[alignment_key][metric_key]
            if int(stats_row["n"]) != count:
                return False
            if set(stats_row) != numeric_keys | {"n"}:
                return False
            if any(not math.isfinite(float(stats_row[key])) or float(stats_row[key]) < 0.0 for key in numeric_keys):
                return False
        primary_scale = float(metrics["primary_fixed_scale_se3"]["scale"])
        secondary_scale = float(metrics["secondary_sim3_scale_diagnostic"]["scale"])
        return primary_scale == 1.0 and math.isfinite(secondary_scale) and secondary_scale > 0.0
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def metric_samples(
    gt_positions: np.ndarray,
    aligned_positions: np.ndarray,
    rpe_pairs: Sequence[Mapping[str, Any]],
) -> Tuple[np.ndarray, np.ndarray]:
    ape = np.linalg.norm(aligned_positions - gt_positions, axis=1)
    rpe_values: List[float] = []
    for pair in rpe_pairs:
        left = int(pair["left_association_index"])
        right = int(pair["right_association_index"])
        gt_delta = gt_positions[right] - gt_positions[left]
        estimate_delta = aligned_positions[right] - aligned_positions[left]
        rpe_values.append(float(np.linalg.norm(estimate_delta - gt_delta)))
    return ape, np.asarray(rpe_values, dtype=float)


def extract_associated_positions(
    trajectory_rows: Sequence[Mapping[str, Any]],
    gt_rows: Sequence[Mapping[str, Any]],
    associations: Sequence[Mapping[str, Any]],
) -> Tuple[np.ndarray, np.ndarray]:
    """Extract raw world_T_body positions without composing a camera extrinsic."""

    estimate_positions = np.asarray(
        [trajectory_rows[int(row["estimate_row_index"])]["position"] for row in associations],
        dtype=float,
    )
    gt_positions = np.asarray(
        [gt_rows[int(row["gt_row_index"])]["position"] for row in associations],
        dtype=float,
    )
    if estimate_positions.shape != gt_positions.shape or estimate_positions.shape != (len(associations), 3):
        raise ValueError("associated body position arrays must both have shape (N,3)")
    return estimate_positions, gt_positions


def csv_text(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def number_text(value: float) -> str:
    return format(float(value), ".17g")


def svg_panel(
    x: Sequence[float],
    series: Sequence[Tuple[Sequence[float], str, str]],
    x0: float,
    y0: float,
    width: float,
    height: float,
    xlabel: str,
    ylabel: str,
    panel_label: str,
) -> str:
    all_x = np.asarray(x, dtype=float)
    all_y = np.concatenate([np.asarray(values, dtype=float) for values, _colour, _name in series])
    xmin, xmax = float(np.min(all_x)), float(np.max(all_x))
    ymin, ymax = float(np.min(all_y)), float(np.max(all_y))
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    xpad = 0.04 * (xmax - xmin)
    ypad = 0.06 * (ymax - ymin)
    xmin, xmax = xmin - xpad, xmax + xpad
    ymin, ymax = ymin - ypad, ymax + ypad

    def map_point(xvalue: float, yvalue: float) -> Tuple[float, float]:
        px = x0 + (xvalue - xmin) / (xmax - xmin) * width
        py = y0 + height - (yvalue - ymin) / (ymax - ymin) * height
        return px, py

    parts = [
        '<rect x="{:.2f}" y="{:.2f}" width="{:.2f}" height="{:.2f}" fill="white" stroke="#777" stroke-width="1"/>'.format(x0, y0, width, height),
        '<text x="{:.2f}" y="{:.2f}" font-size="16" font-weight="bold">{}</text>'.format(x0 + 5, y0 + 20, html.escape(panel_label)),
    ]
    for tick in range(5):
        alpha = tick / 4.0
        px = x0 + alpha * width
        py = y0 + height - alpha * height
        xv = xmin + alpha * (xmax - xmin)
        yv = ymin + alpha * (ymax - ymin)
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{0:.2f}" y2="{2:.2f}" stroke="#ddd"/>'.format(px, y0, y0 + height))
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{2:.2f}" y2="{1:.2f}" stroke="#ddd"/>'.format(py, x0, x0 + width))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10" text-anchor="middle">{:.3g}</text>'.format(px, y0 + height + 17, xv))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10" text-anchor="end">{:.3g}</text>'.format(x0 - 6, py + 3, yv))
    for values, colour, name in series:
        points = " ".join(
            "{:.2f},{:.2f}".format(*map_point(float(xvalue), float(yvalue)))
            for xvalue, yvalue in zip(all_x, values)
        )
        parts.append('<polyline fill="none" stroke="{}" stroke-width="1.7" points="{}"/>'.format(colour, points))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="12" text-anchor="middle">{}</text>'.format(x0 + width / 2, y0 + height + 38, html.escape(xlabel)))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="12" text-anchor="middle" transform="rotate(-90 {:.2f} {:.2f})">{}</text>'.format(x0 - 48, y0 + height / 2, x0 - 48, y0 + height / 2, html.escape(ylabel)))
    legend_x = x0 + width - 145
    legend_y = y0 + 14
    for index, (_values, colour, name) in enumerate(series):
        yy = legend_y + index * 17
        parts.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" stroke-width="2"/>'.format(legend_x, yy, legend_x + 22, yy, colour))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10">{}</text>'.format(legend_x + 27, yy + 3, html.escape(name)))
    return "\n".join(parts)


def svg_xy_panel(
    series: Sequence[Tuple[Sequence[float], Sequence[float], str, str]],
    x0: float,
    y0: float,
    width: float,
    height: float,
    xlabel: str,
    ylabel: str,
    panel_label: str,
) -> str:
    all_x = np.concatenate([np.asarray(xvalues, dtype=float) for xvalues, _y, _c, _n in series])
    all_y = np.concatenate([np.asarray(yvalues, dtype=float) for _x, yvalues, _c, _n in series])
    xmin, xmax = float(np.min(all_x)), float(np.max(all_x))
    ymin, ymax = float(np.min(all_y)), float(np.max(all_y))
    if xmax <= xmin:
        xmax = xmin + 1.0
    if ymax <= ymin:
        ymax = ymin + 1.0
    xpad = 0.04 * (xmax - xmin)
    ypad = 0.06 * (ymax - ymin)
    xmin, xmax = xmin - xpad, xmax + xpad
    ymin, ymax = ymin - ypad, ymax + ypad

    def map_point(xvalue: float, yvalue: float) -> Tuple[float, float]:
        return (
            x0 + (xvalue - xmin) / (xmax - xmin) * width,
            y0 + height - (yvalue - ymin) / (ymax - ymin) * height,
        )

    parts = [
        '<rect x="{:.2f}" y="{:.2f}" width="{:.2f}" height="{:.2f}" fill="white" stroke="#777" stroke-width="1"/>'.format(x0, y0, width, height),
        '<text x="{:.2f}" y="{:.2f}" font-size="16" font-weight="bold">{}</text>'.format(x0 + 5, y0 + 20, html.escape(panel_label)),
    ]
    for tick in range(5):
        alpha = tick / 4.0
        px = x0 + alpha * width
        py = y0 + height - alpha * height
        xv = xmin + alpha * (xmax - xmin)
        yv = ymin + alpha * (ymax - ymin)
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{0:.2f}" y2="{2:.2f}" stroke="#ddd"/>'.format(px, y0, y0 + height))
        parts.append('<line x1="{0:.2f}" y1="{1:.2f}" x2="{2:.2f}" y2="{1:.2f}" stroke="#ddd"/>'.format(py, x0, x0 + width))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10" text-anchor="middle">{:.3g}</text>'.format(px, y0 + height + 17, xv))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10" text-anchor="end">{:.3g}</text>'.format(x0 - 6, py + 3, yv))
    for xvalues, yvalues, colour, _name in series:
        points = " ".join(
            "{:.2f},{:.2f}".format(*map_point(float(xvalue), float(yvalue)))
            for xvalue, yvalue in zip(xvalues, yvalues)
        )
        parts.append('<polyline fill="none" stroke="{}" stroke-width="1.7" points="{}"/>'.format(colour, points))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="12" text-anchor="middle">{}</text>'.format(x0 + width / 2, y0 + height + 38, html.escape(xlabel)))
    parts.append('<text x="{:.2f}" y="{:.2f}" font-size="12" text-anchor="middle" transform="rotate(-90 {:.2f} {:.2f})">{}</text>'.format(x0 - 48, y0 + height / 2, x0 - 48, y0 + height / 2, html.escape(ylabel)))
    legend_x = x0 + width - 145
    legend_y = y0 + 14
    for index, (_x, _y, colour, name) in enumerate(series):
        yy = legend_y + index * 17
        parts.append('<line x1="{:.2f}" y1="{:.2f}" x2="{:.2f}" y2="{:.2f}" stroke="{}" stroke-width="2"/>'.format(legend_x, yy, legend_x + 22, yy, colour))
        parts.append('<text x="{:.2f}" y="{:.2f}" font-size="10">{}</text>'.format(legend_x + 27, yy + 3, html.escape(name)))
    return "\n".join(parts)


def trajectory_figure(gt: np.ndarray, se3: np.ndarray, sim3: np.ndarray) -> str:
    panels = [
        svg_xy_panel([(gt[:, 0], gt[:, 1], "#000000", "Official GT"), (se3[:, 0], se3[:, 1], "#0072B2", "SE(3) aligned"), (sim3[:, 0], sim3[:, 1], "#E69F00", "Sim(3) diagnostic")], 90, 55, 420, 315, "x [m]", "y [m]", "(a) XY trajectory"),
        svg_xy_panel([(gt[:, 0], gt[:, 2], "#000000", "Official GT"), (se3[:, 0], se3[:, 2], "#0072B2", "SE(3) aligned"), (sim3[:, 0], sim3[:, 2], "#E69F00", "Sim(3) diagnostic")], 620, 55, 420, 315, "x [m]", "z [m]", "(b) XZ trajectory"),
    ]
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="430" viewBox="0 0 1120 430">\n<rect width="100%" height="100%" fill="white"/>\n{}\n</svg>\n'.format("\n".join(panels))


def error_figure(elapsed: np.ndarray, ape: np.ndarray, rpe_elapsed: np.ndarray, rpe: np.ndarray) -> str:
    panels = [
        svg_panel(elapsed, [(ape, "#D55E00", "SE(3) translation APE")], 90, 55, 420, 315, "source time since first match [s]", "error [m]", "(a) APE over time"),
        svg_panel(rpe_elapsed, [(rpe, "#0072B2", "SE(3) 1 s translation RPE")], 620, 55, 420, 315, "pair end time since first match [s]", "error [m]", "(b) RPE over time"),
    ]
    return '<svg xmlns="http://www.w3.org/2000/svg" width="1120" height="430" viewBox="0 0 1120 430">\n<rect width="100%" height="100%" fill="white"/>\n{}\n</svg>\n'.format("\n".join(panels))


def metrics_markdown_table(primary: Mapping[str, Any], secondary: Mapping[str, Any]) -> str:
    rows = [
        ("Primary fixed-scale SE(3)", "APE", primary["ape"]),
        ("Primary fixed-scale SE(3)", "1 s RPE", primary["rpe_1s"]),
        ("Secondary Sim(3) scale diagnostic", "APE", secondary["ape"]),
        ("Secondary Sim(3) scale diagnostic", "1 s RPE", secondary["rpe_1s"]),
    ]
    lines = [
        "| Alignment | Metric | n | RMSE [m] | Mean [m] | Median [m] | P95 [m] | Max [m] |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for alignment, metric, values in rows:
        lines.append(
            "| {} | {} | {} | {:.9f} | {:.9f} | {:.9f} | {:.9f} | {:.9f} |".format(
                alignment,
                metric,
                values["n"],
                values["rmse_m"],
                values["mean_m"],
                values["median_m"],
                values["p95_m"],
                values["max_m"],
            )
        )
    return "\n".join(lines)


def generate_analysis_bundle() -> Dict[str, Any]:
    trajectory_audit = audit_trajectory_structure(include_values=True)
    camera_audit = audit_camera_structure()
    gt_audit = audit_gt_structure(include_values=True)
    association = associate_via_official_camera(trajectory_audit["rows"], camera_audit["rows"], gt_audit["rows"])
    if association["errors"] or association["matched_count"] != EXPECTED_MATCHED or association["excluded_count"] != EXPECTED_TAIL:
        raise ValueError("association contract failed during evaluation")
    generation = generation_support_audit(camera_audit["rows"], association)
    if not generation["ok"]:
        raise ValueError("initialization and generation-support contract failed during evaluation")
    rpe_audit = build_rpe_pairs(association["matched"])
    if rpe_audit["rejected"] or rpe_audit["pair_count"] != EXPECTED_RPE_PAIRS:
        raise ValueError("RPE pair contract failed during evaluation")

    trajectory_rows = trajectory_audit["rows"]
    gt_rows = gt_audit["rows"]
    estimate_positions, gt_positions = extract_associated_positions(
        trajectory_rows, gt_rows, association["matched"]
    )

    se3 = rigid_se3_alignment(estimate_positions, gt_positions)
    se3_audit = alignment_audit(se3)
    if not se3_audit["proper"] or se3_audit["scale"] != 1.0:
        raise ValueError("primary fixed-scale SE3 alignment is not proper")
    core_aligned = core_align_se3_positions(estimate_positions, gt_positions)
    core_crosscheck_max_abs_m = float(np.max(np.abs(core_aligned - se3["aligned"])))
    if core_crosscheck_max_abs_m > 1e-12:
        raise ValueError("frozen core SE3 cross-check failed")

    sim3 = proper_umeyama_sim3(estimate_positions, gt_positions)
    sim3_audit = alignment_audit(sim3)
    if not sim3_audit["proper"] or sim3_audit["scale"] <= 0.0:
        raise ValueError("secondary Sim3 alignment is not proper positive-scale")

    se3_ape, se3_rpe = metric_samples(gt_positions, se3["aligned"], rpe_audit["pairs"])
    sim3_ape, sim3_rpe = metric_samples(gt_positions, sim3["aligned"], rpe_audit["pairs"])
    primary = {"alignment": "fixed-scale proper SE(3)", "scale": 1.0, "ape": descriptive_stats(se3_ape), "rpe_1s": descriptive_stats(se3_rpe)}
    secondary = {"alignment": "proper Umeyama Sim(3)", "role": "secondary scale diagnostic only", "scale": sim3_audit["scale"], "ape": descriptive_stats(sim3_ape), "rpe_1s": descriptive_stats(sim3_rpe), "may_replace_primary": False, "may_enter_ranking": False}

    support = {
        "expected_estimator_output_rows": EXPECTED_ESTIMATOR_OUTPUT_ROWS,
        "generated_trajectory_rows": EXPECTED_TRAJECTORY_ROWS,
        "missing_initialization_prefix_rows": EXPECTED_MISSING_INITIALIZATION_PREFIX,
        "missing_interior_generation_rows": 0,
        "missing_terminal_generation_rows": 0,
        "generation_coverage": generation["generation_coverage"],
        "first_generated_output_delay_from_sequence_cam0_ns": generation["first_generated_output_delay_from_sequence_cam0_ns"],
        "first_generated_output_delay_from_sequence_cam0_s": generation["first_generated_output_delay_from_sequence_cam0_s"],
        "first_generated_output_delay_from_first_expected_output_ns": generation["first_generated_output_delay_from_first_expected_output_ns"],
        "first_generated_output_delay_from_first_expected_output_s": generation["first_generated_output_delay_from_first_expected_output_s"],
        "accuracy_associated_pairs": EXPECTED_MATCHED,
        "gt_evaluable_generated": generation["gt_evaluable_generated"],
        "gt_evaluable_expected": generation["gt_evaluable_expected"],
        "excluded_outside_gt_tail_rows": EXPECTED_TAIL,
        "excluded_tail_is_gt_coverage_not_generation_failure": generation["excluded_tail_is_gt_coverage_not_generation_failure"],
        "rpe_pairs_1s": EXPECTED_RPE_PAIRS,
        "first_source_timestamp_ns": int(association["matched"][0]["source_camera_timestamp_ns"]),
        "last_source_timestamp_ns": int(association["matched"][-1]["source_camera_timestamp_ns"]),
        "associated_span_s": (int(association["matched"][-1]["source_camera_timestamp_ns"]) - int(association["matched"][0]["source_camera_timestamp_ns"])) / 1e9,
        "single_contiguous_segment": True,
        "max_trajectory_text_to_camera_error_ns": association["max_abs_text_to_camera_ns"],
        "gt_join_error_ns": 0,
    }
    metrics = {
        "schema_version": "aqua-fe-supervins-mh01-gt-metrics-v1",
        "support": support,
        "primary_fixed_scale_se3": primary,
        "secondary_sim3_scale_diagnostic": secondary,
        "statistical_boundary": {
            "unit_of_analysis": "one sealed trajectory run",
            "timestamp_samples_independent_replicates": False,
            "confidence_intervals_or_p_values_computed": False,
            "significance_or_superiority_claim_authorized": False,
        },
    }

    input_audit = {
        "schema_version": "aqua-fe-supervins-mh01-gt-input-audit-v1",
        "source_run_result": file_identity(STAGE4_RESULT),
        "source_trajectory": file_identity(TRAJECTORY),
        "official_camera_csv": file_identity(CAMERA_CSV),
        "official_gt_csv": file_identity(GT_CSV),
        "official_gt_sensor": file_identity(GT_SENSOR),
        "official_imu_sensor": file_identity(IMU_SENSOR),
        "trajectory_structure": {k: v for k, v in trajectory_audit.items() if k != "rows"},
        "camera_row_count": camera_audit["row_count"],
        "gt_structure": {k: v for k, v in gt_audit.items() if k != "rows"},
        "gt_T_BS": parse_t_bs(GT_SENSOR),
        "imu_T_BS": parse_t_bs(IMU_SENSOR),
        "position_frame": "body-to-body; no camera extrinsic composition",
    }
    association_audit = {
        "schema_version": "aqua-fe-supervins-mh01-gt-association-audit-v1",
        "policy": "trajectory text -> frozen unique official camera row -> exact same integer GT timestamp",
        "generated_rows_are_not_accuracy_n": True,
        "generation_support": generation,
        "accuracy_sample_count": association["matched_count"],
        "excluded_tail_count": association["excluded_count"],
        "max_abs_text_to_camera_ns": association["max_abs_text_to_camera_ns"],
        "signed_text_minus_source_ns_histogram": association["signed_text_minus_source_ns_histogram"],
        "gt_interpolation_or_extrapolation": False,
        "rpe_pair_rule": "source estimate index +10, official camera index +20, exact 1 second in one contiguous matched segment",
        "rpe_pair_count": rpe_audit["pair_count"],
        "rpe_actual_delta_min_ns": rpe_audit["actual_delta_min_ns"],
        "rpe_actual_delta_max_ns": rpe_audit["actual_delta_max_ns"],
        "excluded_rows": association["excluded"],
    }
    alignment_json = {
        "schema_version": "aqua-fe-supervins-mh01-gt-alignment-v1",
        "primary_fixed_scale_se3": dict(se3_audit, core_crosscheck_max_abs_m=core_crosscheck_max_abs_m),
        "secondary_sim3_scale_diagnostic": sim3_audit,
        "same_support_for_primary_and_secondary": EXPECTED_MATCHED,
        "reflection_forbidden": True,
    }

    associated_rows: List[List[Any]] = []
    for index, row in enumerate(association["matched"]):
        associated_rows.append([
            row["estimate_row_index"], row["camera_row_index"], row["estimate_timestamp_text"], row["display_timestamp_ns"], row["source_camera_timestamp_ns"], row["gt_row_index"], row["timestamp_text_minus_source_ns"],
            *[number_text(value) for value in gt_positions[index]],
            *[number_text(value) for value in estimate_positions[index]],
            *[number_text(value) for value in se3["aligned"][index]], number_text(se3_ape[index]),
            *[number_text(value) for value in sim3["aligned"][index]], number_text(sim3_ape[index]),
        ])

    rpe_rows: List[List[Any]] = []
    for index, row in enumerate(rpe_audit["pairs"]):
        rpe_rows.append([
            row["left_estimate_row_index"], row["right_estimate_row_index"], row["left_camera_row_index"], row["right_camera_row_index"],
            row["left_source_timestamp_ns"], row["right_source_timestamp_ns"], row["delta_ns"], number_text(se3_rpe[index]), number_text(sim3_rpe[index]),
        ])

    metrics_table = metrics_markdown_table(primary, secondary)
    report = """# Analysis Report\n\n## Analysis question\n\nWhat descriptive translation error does the one sealed SuperVINS stage-4 trajectory exhibit on its exact official EuRoC MH_01_easy GT overlap?\n\n## Evidence and support\n\n- Unit of analysis: one sealed trajectory run.\n- Expected 10 Hz estimator-output support: {expected} odd-index camera rows; generated trajectory rows: {generated}.\n- The generated rows are one exact suffix after a {missing_prefix}-row initialization prefix, with zero interior and zero terminal generation gaps (generation coverage {generation_coverage}).\n- First generated output delay: {sequence_delay:.9f} s from sequence cam0 and {expected_delay:.1f} s from the first expected odd-index output.\n- Accuracy-associated pairs: {matched}; GT-evaluable/generated coverage {evaluable_generated}; GT-evaluable/expected coverage {evaluable_expected}.\n- Eleven generated post-GT tail rows are excluded and never counted as accuracy samples; this is a GT-coverage boundary, not a trajectory-generation failure.\n- Association is trajectory text to the frozen official camera row, then an exact integer timestamp join to GT; no GT interpolation or extrapolation is used.\n- Primary alignment is fixed-scale proper SE(3). The proper Sim(3) result is a secondary scale diagnostic only.\n\n## Exact descriptive summary\n\n{table}\n\nSecondary Sim(3) diagnostic scale: `{scale:.17g}`.\n\n## Claim Candidates\n\n- Claim:\n  - Source evidence: this single pinned official MH01 trajectory and analysis bundle.\n  - Allowed wording: The sealed SuperVINS MH01 run has the reported descriptive fixed-scale SE(3)-aligned translation APE and one-second positional-delta RPE on 1799 exact GT timestamp joins.\n  - Forbidden stronger wording: SuperVINS is superior to AQUA-FE or another system; the result generalizes; the result is statistically significant; this is a V2_01 or underwater result.\n  - Uncertainty: one deterministic run, one sequence, and serially correlated timestamp residuals.\n  - Next check: preregister comparable frozen trajectories before any cross-system comparison.\n  - Decision: keep as a bounded descriptive result.\n\n## Interpretation boundary\n\nNo confidence interval, p-value, effect size, ranking, or superiority claim is valid from this single run. The Sim(3) diagnostic cannot replace the primary metric.\n""".format(
        expected=EXPECTED_ESTIMATOR_OUTPUT_ROWS,
        generated=EXPECTED_TRAJECTORY_ROWS,
        missing_prefix=EXPECTED_MISSING_INITIALIZATION_PREFIX,
        generation_coverage=generation["generation_coverage"]["decimal_17g"],
        sequence_delay=generation["first_generated_output_delay_from_sequence_cam0_s"],
        expected_delay=generation["first_generated_output_delay_from_first_expected_output_s"],
        matched=EXPECTED_MATCHED,
        evaluable_generated=generation["gt_evaluable_generated"]["decimal_17g"],
        evaluable_expected=generation["gt_evaluable_expected"]["decimal_17g"],
        table=metrics_table,
        scale=secondary["scale"],
    )

    stats_appendix = """# Statistics Appendix\n\n## Protocol\n\n- Primary: translation APE after fixed-scale proper SE(3) Kabsch alignment on all 1799 exact joined body-position pairs.\n- RPE: global-frame positional-delta error at source-row index difference 10 / camera-row difference 20; all 1789 pairs are exactly 1,000,000,000 ns.\n- Secondary: proper Umeyama Sim(3) on the identical support, reported only as a scale diagnostic.\n- Quantiles: NumPy linear method. Standard deviation is the population standard deviation over observed timestamp residuals.\n\n## Descriptive statistics\n\n{table}\n\n## Inferential-statistics blocker\n\nThere is one run (`n_runs=1`). The 1799 APE and 1789 RPE timestamp residuals are serially correlated measurements within that run, not independent replications. Therefore normality tests, confidence intervals, p-values, effect sizes against other methods, and significance tests are not computed.\n\n## Scale diagnostic\n\nThe secondary proper Sim(3) scale is `{scale:.17g}`. It is not a ranking metric and does not replace the fixed-scale SE(3) primary result.\n""".format(table=metrics_table, scale=secondary["scale"])

    figure_catalog = """# Figure Catalog\n\n## figure-01-trajectory-overlay.svg\n\n- Purpose: show the spatial relationship between official GT, the primary fixed-scale SE(3) alignment, and the secondary Sim(3) scale diagnostic.\n- Data source: `associated-pairs.csv`, 1799 exact GT joins.\n- Caption requirements: identify MH01, body-to-body poses, fixed-scale SE(3) primary, Sim(3) diagnostic, and `n=1799`; state that there are no repeated-run error bars.\n- Observation checklist: inspect overall shape agreement, drift direction, and whether Sim(3) visibly changes scale.\n- Interpretation limit: the overlay cannot establish statistical significance or cross-system superiority.\n\n## figure-02-error-over-time.svg\n\n- Purpose: expose temporal structure in primary APE and exact-one-second RPE rather than hiding it in one aggregate.\n- Data source: `associated-pairs.csv` and `rpe-pairs-1s.csv`.\n- Caption requirements: define APE, the exact index-based one-second RPE rule, `n_APE=1799`, and `n_RPE=1789`; state that samples are serially correlated and no uncertainty interval is shown.\n- Observation checklist: inspect error growth, local peaks, and non-stationarity.\n- Interpretation limit: timestamp samples are not independent experimental repetitions.\n"""

    elapsed = np.asarray(
        [(int(row["source_camera_timestamp_ns"]) - int(association["matched"][0]["source_camera_timestamp_ns"])) / 1e9 for row in association["matched"]],
        dtype=float,
    )
    rpe_elapsed = np.asarray(
        [(int(row["right_source_timestamp_ns"]) - int(association["matched"][0]["source_camera_timestamp_ns"])) / 1e9 for row in rpe_audit["pairs"]],
        dtype=float,
    )

    outputs: List[Tuple[Path, bytes]] = [
        (ANALYSIS / "metrics.json", canonical_json_bytes(metrics)),
        (ANALYSIS / "input-audit.json", canonical_json_bytes(input_audit)),
        (ANALYSIS / "association-audit.json", canonical_json_bytes(association_audit)),
        (ANALYSIS / "alignment.json", canonical_json_bytes(alignment_json)),
        (ANALYSIS / "associated-pairs.csv", csv_text(ASSOCIATED_HEADER, associated_rows).encode("utf-8")),
        (ANALYSIS / "rpe-pairs-1s.csv", csv_text(RPE_HEADER, rpe_rows).encode("utf-8")),
        (ANALYSIS / "analysis-report.md", report.encode("utf-8")),
        (ANALYSIS / "stats-appendix.md", stats_appendix.encode("utf-8")),
        (ANALYSIS / "figure-catalog.md", figure_catalog.encode("utf-8")),
        (FIGURES / "figure-01-trajectory-overlay.svg", trajectory_figure(gt_positions, se3["aligned"], sim3["aligned"]).encode("utf-8")),
        (FIGURES / "figure-02-error-over-time.svg", error_figure(elapsed, se3_ape, rpe_elapsed, se3_rpe).encode("utf-8")),
    ]
    written: Dict[str, Dict[str, Any]] = {}
    for path, payload in outputs:
        raise_if_pending()
        identity = write_bytes_exclusive(path, payload)
        written[str(path.relative_to(ATTEMPT))] = identity

    manifest_entries = {
        relative: identity for relative, identity in sorted(written.items())
    }
    manifest = {
        "schema_version": "aqua-fe-supervins-mh01-gt-analysis-artifact-manifest-v1",
        "algorithm": "SHA-256 per exact file; bundle tree digest over compact canonical sorted [{path,sha256,size_bytes}]; manifest excludes itself",
        "entry_count": len(manifest_entries),
        "bundle_content_tree_sha256": artifact_tree_digest(manifest_entries),
        "entries": manifest_entries,
    }
    manifest_identity = write_json_exclusive(ANALYSIS / "artifact-manifest.json", manifest)
    written["analysis-output/artifact-manifest.json"] = manifest_identity
    return {
        "metrics": metrics,
        "input_audit": input_audit,
        "association_audit": association_audit,
        "alignment": alignment_json,
        "bundle_artifacts": written,
    }


def inventory_attempt_files(exclude_result: bool = True) -> Dict[str, Dict[str, Any]]:
    files: Dict[str, Dict[str, Any]] = {}
    if not ATTEMPT.exists():
        return files
    for path in sorted(ATTEMPT.rglob("*")):
        if not path.is_file():
            continue
        if exclude_result and path == RUN_RESULT:
            continue
        files[str(path.relative_to(ATTEMPT))] = file_identity(path)
    return files


def audit_completed_bundle(expected_identities: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    observed_paths = sorted(
        str(path.relative_to(ATTEMPT)) for path in ANALYSIS.rglob("*") if path.is_file()
    )
    path_set_ok = observed_paths == sorted(REQUIRED_BUNDLE_FILES)
    file_checks: Dict[str, Any] = {}
    all_ok = path_set_ok
    for relative in observed_paths:
        path = ATTEMPT / relative
        info = path.stat()
        identity = file_identity(path)
        expected = expected_identities.get(relative)
        mode = stat.S_IMODE(info.st_mode)
        ok = identity == expected and mode == 0o444 and info.st_nlink == 1
        file_checks[relative] = {
            "identity": identity,
            "expected": expected,
            "mode": oct(mode),
            "nlink": info.st_nlink,
            "ok": ok,
        }
        all_ok &= ok
    manifest = load_json(ANALYSIS / "artifact-manifest.json")
    manifest_entries = manifest.get("entries", {})
    manifest_tree_observed = artifact_tree_digest(manifest_entries)
    manifest_tree_ok = (
        manifest.get("entry_count") == len(manifest_entries)
        and manifest.get("bundle_content_tree_sha256") == manifest_tree_observed
        and set(manifest_entries) == set(REQUIRED_BUNDLE_FILES) - {"analysis-output/artifact-manifest.json"}
    )
    for relative, expected in manifest_entries.items():
        manifest_tree_ok &= file_identity(ATTEMPT / relative) == expected
    all_ok &= manifest_tree_ok
    return {
        "ok": bool(all_ok),
        "exact_file_set": path_set_ok,
        "file_checks": file_checks,
        "manifest_tree_ok": bool(manifest_tree_ok),
        "bundle_content_tree_sha256": manifest.get("bundle_content_tree_sha256"),
    }


def post_pin_audit(preflight: Mapping[str, Any]) -> Dict[str, Any]:
    expected: Dict[str, Dict[str, Any]] = {}
    for path, row in preflight.get("pin_snapshot", {}).get("checks", {}).items():
        observed = row.get("observed")
        if observed is not None:
            expected[path] = observed
    return inspect_pins(expected)


def best_effort_inventory() -> Dict[str, Any]:
    try:
        return {"files": inventory_attempt_files(exclude_result=True), "error": None}
    except Exception as exc:
        return {"files": {}, "error": "{}: {}".format(type(exc).__name__, exc)}


def best_effort_post_pins(preflight: Mapping[str, Any]) -> Dict[str, Any]:
    try:
        return post_pin_audit(preflight)
    except Exception as exc:
        return {"ok": False, "checks": {}, "failures": [], "error": "{}: {}".format(type(exc).__name__, exc)}


def ensure_failure_attempt_namespace() -> bool:
    if not NAMESPACE_OWNED or not EVIDENCE_ROOT.exists():
        return False
    if ATTEMPT.exists():
        return ATTEMPT.is_dir()
    try:
        mkdir_exclusive_durable(ATTEMPT, 0o755)
        return True
    except Exception:
        return False


def run_once(token: str) -> int:
    global NAMESPACE_OWNED, TERMINAL_COMMITTED
    if token != TOKEN:
        print(json.dumps({"status": "NO_GO", "error": "authorization token mismatch"}, sort_keys=True))
        return 2
    preflight = collect_preflight(require_authority=True)
    if not preflight["ready"] or preflight["status"] != "GO_EXACTLY_ONE_PURE_GT_EVALUATION_START":
        print(json.dumps({"status": "NO_GO", "failures": preflight["failures"]}, sort_keys=True))
        return 2

    previous_handlers = install_signal_handlers()
    started_at = now_iso()
    try:
        mkdir_exclusive_durable(EVIDENCE_ROOT, 0o755)
        NAMESPACE_OWNED = True
        mkdir_exclusive_durable(ATTEMPT, 0o755)
        # The signal handler is pending-only: ownership and a writable terminal
        # namespace are established before a controlled signal is raised.
        raise_if_pending()
        claim = {
            "schema_version": "aqua-fe-supervins-mh01-gt-evaluation-start-claim-v1",
            "created_at": now_iso(),
            "attempt": "attempt_001",
            "evaluation_start_count_before": 0,
            "evaluation_start_count_after": 1,
            "retry_authorized": False,
            "controller_command": CONTROLLER_COMMAND,
            "authorization_token_sha256": TOKEN_SHA256,
            "protocol": file_identity(FREEZE),
            "lock": file_identity(LOCK),
            "authority": file_identity(AUTHORITY),
            "runner": file_identity(RUNNER),
            "tests": file_identity(TESTS),
            "scientific_boundary": "pure GT computation only; no ROS/model/trajectory generation",
        }
        write_json_exclusive(START_CLAIM, claim)
        raise_if_pending()
        write_json_exclusive(PREFLIGHT_RESULT, preflight)
        mkdir_exclusive_durable(ANALYSIS, 0o755)
        mkdir_exclusive_durable(FIGURES, 0o755)
        raise_if_pending()

        evaluation = generate_analysis_bundle()
        raise_if_pending()
        bundle_paths = sorted(evaluation["bundle_artifacts"])
        if bundle_paths != sorted(REQUIRED_BUNDLE_FILES):
            raise ValueError("analysis bundle file set differs from freeze")
        bundle_audit = audit_completed_bundle(evaluation["bundle_artifacts"])
        if not bundle_audit["ok"]:
            raise ValueError("analysis bundle identity/mode/tree audit failed")
        post_pins = post_pin_audit(preflight)
        if not post_pins["ok"]:
            raise ValueError("postflight pin audit failed")
        processes = relevant_processes()
        if processes:
            raise ValueError("stage4 ROS/model process observed during closeout")
        artifacts = inventory_attempt_files(exclude_result=True)
        pass_conditions = {
            "run_preflight_go": True,
            "exact_one_evaluator_start": True,
            "retry_absent": True,
            "stage4_and_gt_pins_unchanged": post_pins["ok"],
            "trajectory_to_camera_to_exact_gt_association_counts_exact": evaluation["association_audit"]["accuracy_sample_count"] == EXPECTED_MATCHED,
            "initialization_and_generation_coverage_exact": evaluation["association_audit"]["generation_support"]["ok"] is True,
            "eleven_post_gt_tail_rows_excluded": evaluation["association_audit"]["excluded_tail_count"] == EXPECTED_TAIL,
            "excluded_tail_is_gt_coverage_not_generation_failure": evaluation["association_audit"]["generation_support"]["excluded_tail_is_gt_coverage_not_generation_failure"] is True,
            "rpe_exact_index_and_one_second_pair_count": evaluation["association_audit"]["rpe_pair_count"] == EXPECTED_RPE_PAIRS,
            "primary_fixed_scale_se3_proper": evaluation["alignment"]["primary_fixed_scale_se3"]["proper"],
            "frozen_core_se3_crosscheck": evaluation["alignment"]["primary_fixed_scale_se3"]["core_crosscheck_max_abs_m"] <= 1e-12,
            "secondary_sim3_positive_scale_proper": evaluation["alignment"]["secondary_sim3_scale_diagnostic"]["proper"],
            "all_primary_and_secondary_metrics_finite_nonnegative": metrics_are_finite_nonnegative(evaluation["metrics"]),
            "analysis_bundle_complete_manifested_and_tree_hashed": bundle_audit["ok"],
            "no_ros_model_publisher_or_trajectory_generation": not processes,
            "single_run_descriptive_statistics_only": evaluation["metrics"]["statistical_boundary"]["confidence_intervals_or_p_values_computed"] is False,
        }
        if not all(pass_conditions.values()):
            raise ValueError("one or more terminal pass conditions failed")
        result = {
            "schema_version": RESULT_SCHEMA,
            "status": "PASS_DEVELOPMENT_OFFICIAL_MH01_PURE_GT_EVALUATION",
            "return_code": 0,
            "started_at": started_at,
            "completed_at": now_iso(),
            "evaluable": True,
            "authorization": {
                "evaluation_start_count": 1,
                "retry_authorized": False,
                "root_execution_authority": file_identity(AUTHORITY),
            },
            "pass_conditions": pass_conditions,
            "metrics": evaluation["metrics"],
            "association_audit": evaluation["association_audit"],
            "alignment": evaluation["alignment"],
            "bundle_audit": bundle_audit,
            "post_pin_audit": post_pins,
            "artifact_count_before_result": len(artifacts),
            "artifacts": artifacts,
            "claim_boundary": {
                "official_mh01_single_run_descriptive_gt_evaluation": True,
                "readme_recommended_v2_01": False,
                "model_or_ros_rerun": False,
                "cross_system_comparison": False,
                "superiority_or_underwater_claim": False,
                "confidence_interval_p_value_or_significance": False,
                "sim3_replaces_primary": False,
            },
            "next_stage_automatically_authorized": False,
        }
        raise_if_pending()
        result_identity = write_json_exclusive(RUN_RESULT, result)
        TERMINAL_COMMITTED = True
        try:
            print(json.dumps({"status": result["status"], "return_code": 0, "run_result_identity": result_identity}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 0
    except BaseException as exc:
        if ensure_failure_attempt_namespace() and not TERMINAL_COMMITTED and not RUN_RESULT.exists():
            failure = {
                "schema_version": RESULT_SCHEMA,
                "status": "FAIL_DEVELOPMENT_OFFICIAL_MH01_PURE_GT_EVALUATION",
                "return_code": 1,
                "started_at": started_at,
                "completed_at": now_iso(),
                "error": {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()},
                "pending_signal": PENDING_SIGNAL,
                "retry_authorized": False,
                "preflight_pin_snapshot": preflight.get("pin_snapshot", {}),
                "post_pin_audit": best_effort_post_pins(preflight),
                "artifacts_before_result": best_effort_inventory(),
                "claim_boundary": {"model_or_ros_rerun": False, "metrics_may_be_used": False},
            }
            try:
                write_json_exclusive(RUN_RESULT, failure)
                TERMINAL_COMMITTED = True
            except Exception:
                pass
        try:
            print(json.dumps({"status": "FAIL", "error": "{}: {}".format(type(exc).__name__, exc)}, sort_keys=True))
        except (BrokenPipeError, OSError):
            pass
        return 1
    finally:
        restore_signal_handlers(previous_handlers)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", choices=("preflight", "run"), required=True)
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args(argv)
    if args.action == "preflight":
        result = collect_preflight(require_authority=False)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ready"] else 2
    return run_once(args.authorization_token)


if __name__ == "__main__":
    raise SystemExit(main())
