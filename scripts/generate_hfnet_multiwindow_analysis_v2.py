#!/usr/bin/env python3
"""Generate the frozen HFNet multi-window descriptive analysis bundle v2.

This is an analysis-only program.  It reads terminal run receipts and frozen
selectors; it never launches HFNet, ROS, VINS, an evaluator, or any detector.
The four output rows contain three current protocol windows plus one legacy
terminal context.  The legacy row is never included in the current n=3
denominator.  Accuracy is deliberately blocked for every row, so APE and RPE
fields are always null.

If either new run receipt is absent, the program emits a PENDING CSV/JSON/MD
snapshot and deliberately withholds figures.  Once all three current windows
are terminal, it emits three vector figures (PDF and SVG) showing usability,
score support, and the feed/score timeline.  No significance test, confidence
interval, cross-window mean, or winner ranking is computed.
"""

from __future__ import annotations

import argparse
import copy
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "papers/hfnet_multiwindow_comparison_protocol_v2.md"
ROW_SCHEMA = ROOT / "papers/hfnet_multiwindow_result_schema_v2.json"
CSV_TEMPLATE = ROOT / "papers/hfnet_multiwindow_results_template_v2.csv"
DEFAULT_OUTPUT_DIR = ROOT / "papers/hfnet_multiwindow_strict_analysis_v2"

BUNDLE_SCHEMA_VERSION = "aqua-fe-hfnet-multiwindow-analysis-bundle-v2"
PRESENTATION_REVISION = "v2.1"
ROW_SCHEMA_VERSION = "aqua-fe-hfnet-multiwindow-result-v2"
PROTOCOL_ID = "hfnet-multiwindow-comparison-20260822-v2"

A06 = "A06_SCORE_2210_2460"
H07 = "H07_SCORE_1660_1720"
A02 = "A02_FULLHISTORY_SCORE_4500_6300"
LEGACY_A02 = "A02_LEGACY_COLDSTART_SCORE_5400_6300"
WINDOW_ORDER = (A06, H07, A02, LEGACY_A02)
CURRENT_WINDOWS = (A06, H07, A02)

PASS_COVERAGE = 0.70
PASS_CONTIGUOUS = 0.70

H07_SELECTOR = ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_selector_freeze_v1.json"
A02_SELECTOR = ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_selector_freeze_v1.json"
A02_STRICT70_PROTOCOL = (
    ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_strict70_protocol_v2.json"
)
A02_STRICT70_EXECUTION_LOCK = (
    ROOT / "papers/hfnet_v6_a02_0001_6300_score_4500_6300_strict70_execution_lock_v2.json"
)

A06_CAMERA_CSV = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
    "aqualoc_archaeology_a06_0000_2460/mav0/cam0/data.csv"
)
H07_CAMERA_CSV = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_h07_exact_window_v1/"
    "aqualoc_harbor_h07_0001_1720/mav0/cam0/data.csv"
)
A02_CAMERA_CSV = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a02_full_history_v1/"
    "aqualoc_archaeology_a02_0001_6300/mav0/cam0/data.csv"
)
LEGACY_A02_CAMERA_CSV = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_shared_baselines_v1/"
    "a02_4500_6300_shared_r1/hfnet/mav0/cam0/data.csv"
)


class EvidenceError(RuntimeError):
    """Raised when frozen evidence is missing, malformed, or contradictory."""


@dataclass(frozen=True)
class WindowSource:
    window_id: str
    run_result: Path
    camera_csv: Path
    selector_or_contract: Optional[Path]
    execution_lock: Optional[Path]
    pending_allowed: bool
    feed_selector: Optional[Path] = None


@dataclass(frozen=True)
class AnalysisInputs:
    protocol: Path
    row_schema: Path
    csv_template: Path
    sources: Mapping[str, WindowSource]


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvidenceError("MISSING_JSON:%s" % path) from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EvidenceError("UNREADABLE_JSON:%s:%s" % (path, type(error).__name__)) from error
    if not isinstance(value, dict):
        raise EvidenceError("JSON_ROOT_NOT_OBJECT:%s" % path)
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Optional[Path]) -> Optional[Dict[str, Any]]:
    if path is None or not path.is_file():
        return None
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _h07_attempt_namespace(selector: Mapping[str, Any]) -> Path:
    selection = selector.get("selection")
    policy = selector.get("execution_policy")
    if not isinstance(selection, Mapping) or not isinstance(policy, Mapping):
        raise EvidenceError("H07_SELECTOR_NAMESPACE_FIELDS_MISSING")
    feed = selection.get("camera_indices_inclusive_for_feed")
    if feed != [1, 1720] or selection.get("sequence_id") != "H07":
        raise EvidenceError("H07_SELECTOR_FEED_OR_SEQUENCE_DRIFT")
    attempt = policy.get("fresh_attempt")
    if attempt != "attempt_001":
        raise EvidenceError("H07_SELECTOR_ATTEMPT_DRIFT")
    return Path(
        "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
        "aqualoc_harbor_h07_%04d_%04d/%s" % (feed[0], feed[1], attempt)
    )


def _a02_attempt_namespace(
    selector: Mapping[str, Any],
    strict_protocol: Mapping[str, Any],
    strict_lock: Mapping[str, Any],
) -> Path:
    protocol = selector.get("protocol")
    selection = selector.get("selection")
    if not isinstance(protocol, Mapping) or not isinstance(selection, Mapping):
        raise EvidenceError("A02_SELECTOR_NAMESPACE_FIELDS_MISSING")
    if selection.get("camera_indices_inclusive_for_feed") != [1, 6300]:
        raise EvidenceError("A02_SELECTOR_FEED_DRIFT")
    if selection.get("score_camera_indices_inclusive") != [4500, 6300]:
        raise EvidenceError("A02_SELECTOR_SCORE_DRIFT")
    if strict_protocol.get("schema_version") != "aqua-fe-hfnet-v6-a02-0001-6300-strict70-protocol-v2":
        raise EvidenceError("A02_STRICT70_PROTOCOL_SCHEMA_DRIFT")
    strict_input = strict_protocol.get("input")
    strict_gate = strict_protocol.get("primary_producer_gate")
    if not isinstance(strict_input, Mapping) or not isinstance(strict_gate, Mapping):
        raise EvidenceError("A02_STRICT70_PROTOCOL_FIELDS_MISSING")
    if strict_input.get("source_camera_indices_inclusive") != [1, 6300]:
        raise EvidenceError("A02_STRICT70_PROTOCOL_FEED_DRIFT")
    if strict_input.get("score_source_camera_indices_inclusive") != [4500, 6300]:
        raise EvidenceError("A02_STRICT70_PROTOCOL_SCORE_DRIFT")
    if strict_gate.get("minimum_score_poses") != 1261:
        raise EvidenceError("A02_STRICT70_PROTOCOL_SCORE_GATE_DRIFT")
    if strict_gate.get("minimum_contiguous_score_poses") != 1261:
        raise EvidenceError("A02_STRICT70_PROTOCOL_CONTIGUITY_GATE_DRIFT")
    if strict_lock.get("schema_version") != "aqua-fe-hfnet-v6-a02-0001-6300-strict70-execution-lock-v2":
        raise EvidenceError("A02_STRICT70_LOCK_SCHEMA_DRIFT")
    lock_attempt = strict_lock.get("attempt")
    if not isinstance(lock_attempt, Mapping):
        raise EvidenceError("A02_STRICT70_LOCK_ATTEMPT_MISSING")
    namespace = lock_attempt.get("path")
    if not isinstance(namespace, str) or not namespace:
        raise EvidenceError("A02_STRICT70_LOCK_ATTEMPT_NAMESPACE_MISSING")
    value = Path(namespace)
    expected_suffix = Path(
        "aqualoc_archaeology_a02_feed_0001_6300_score_4500_6300_strict70/attempt_001"
    )
    if not str(value).endswith(str(expected_suffix)):
        raise EvidenceError("A02_STRICT70_LOCK_ATTEMPT_NAMESPACE_DRIFT")
    old_namespace = protocol.get("attempt_namespace")
    if not isinstance(old_namespace, str) or "strict70" in old_namespace:
        raise EvidenceError("A02_V1_SELECTOR_PROVENANCE_DRIFT")
    strict_protocol_pin = strict_lock.get("strict70_protocol")
    if not isinstance(strict_protocol_pin, Mapping):
        raise EvidenceError("A02_STRICT70_LOCK_PROTOCOL_PIN_MISSING")
    if strict_protocol_pin.get("path") != str(A02_STRICT70_PROTOCOL):
        raise EvidenceError("A02_STRICT70_LOCK_PROTOCOL_PATH_DRIFT")
    if strict_protocol_pin.get("sha256") != _sha256(A02_STRICT70_PROTOCOL):
        raise EvidenceError("A02_STRICT70_LOCK_PROTOCOL_HASH_DRIFT")
    return value


def default_inputs(
    *,
    a06_run_result: Optional[Path] = None,
    h07_run_result: Optional[Path] = None,
    a02_run_result: Optional[Path] = None,
    legacy_run_result: Optional[Path] = None,
) -> AnalysisInputs:
    """Resolve new attempt paths from their frozen selector namespaces."""
    h07_selector = _read_json(H07_SELECTOR)
    a02_selector = _read_json(A02_SELECTOR)
    a02_strict_protocol = _read_json(A02_STRICT70_PROTOCOL)
    a02_strict_lock = _read_json(A02_STRICT70_EXECUTION_LOCK)
    h07_attempt = _h07_attempt_namespace(h07_selector)
    a02_attempt = _a02_attempt_namespace(
        a02_selector, a02_strict_protocol, a02_strict_lock
    )
    sources = {
        A06: WindowSource(
            A06,
            a06_run_result or Path(
                "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/fresh_underwater/"
                "aqualoc_archaeology_a06_0000_2460/attempt_001/run_result.json"
            ),
            A06_CAMERA_CSV,
            ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_selector_freeze_v1.json",
            ROOT / "papers/hfnet_v6_a06_0000_2460_exact_window_execution_lock_v1.json",
            False,
        ),
        H07: WindowSource(
            H07,
            h07_run_result or h07_attempt / "run_result.json",
            H07_CAMERA_CSV,
            H07_SELECTOR,
            ROOT / "papers/hfnet_v6_h07_0001_1720_exact_window_execution_lock_v1.json",
            True,
        ),
        A02: WindowSource(
            A02,
            a02_run_result or a02_attempt / "run_result.json",
            A02_CAMERA_CSV,
            A02_STRICT70_PROTOCOL,
            A02_STRICT70_EXECUTION_LOCK,
            True,
            feed_selector=A02_SELECTOR,
        ),
        LEGACY_A02: WindowSource(
            LEGACY_A02,
            legacy_run_result or Path(
                "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v4/"
                "post_stop_a02_long1801_headless/drivers/"
                "aqualoc_a02_4500_6300_headless_r1/run_result.json"
            ),
            LEGACY_A02_CAMERA_CSV,
            ROOT / "papers/hfnet_slam_a02_long1801_headless_run_contract_v4.json",
            None,
            False,
        ),
    }
    return AnalysisInputs(PROTOCOL, ROW_SCHEMA, CSV_TEMPLATE, sources)


def _none(value: str) -> Optional[str]:
    return value if value != "" else None


def _integer(value: str) -> Optional[int]:
    return None if value == "" else int(value)


def _number(value: str) -> Optional[float]:
    return None if value == "" else float(value)


def _boolean(value: str) -> Optional[bool]:
    if value == "":
        return None
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise EvidenceError("INVALID_CSV_BOOLEAN:%s" % value)


def _pipe_strings(value: str) -> List[str]:
    return [] if value == "" else value.split("|")


def _pipe_integers(value: str) -> List[int]:
    return [] if value == "" else [int(item) for item in value.split("|")]


def _template_row_to_record(flat: Mapping[str, str]) -> Dict[str, Any]:
    return {
        "schema_version": flat["schema_version"],
        "protocol_id": flat["protocol_id"],
        "row_role": flat["row_role"],
        "attempt_relation": flat["attempt_relation"],
        "window_id": flat["window_id"],
        "dataset_family": flat["dataset_family"],
        "sequence": flat["sequence"],
        "method_id": flat["method_id"],
        "system_class": flat["system_class"],
        "evidence_role": flat["evidence_role"],
        "feed": {
            "start_index": int(flat["feed_start_index"]),
            "end_index": int(flat["feed_end_index"]),
            "frame_count": int(flat["feed_frame_count"]),
            "preroll_start_index": _integer(flat["preroll_start_index"]),
            "preroll_end_index": _integer(flat["preroll_end_index"]),
            "input_rate_hz": _number(flat["input_rate_hz"]),
        },
        "score": {
            "start_index": int(flat["score_start_index"]),
            "end_index": int(flat["score_end_index"]),
            "expected_frame_count": int(flat["score_frame_count_expected"]),
            "nominal_duration_s": float(flat["score_nominal_duration_s"]),
        },
        "synchronization": {
            "sync_trim_applied": bool(_boolean(flat["sync_trim_applied"])),
            "trimmed_source_indices": _pipe_integers(flat["sync_trimmed_source_indices"]),
            "trim_reason": flat["sync_trim_reason"],
            "camera0_has_shifted_imu_predecessor": _boolean(flat["camera0_has_shifted_imu_predecessor"]),
            "first_fed_camera_has_shifted_imu_predecessor": _boolean(flat["first_fed_camera_has_shifted_imu_predecessor"]),
            "synthetic_or_extrapolated_imu_permitted": bool(
                _boolean(flat["synthetic_or_extrapolated_imu_permitted"])
            ),
        },
        "execution": {
            "state": flat["execution_state"],
            "process_start_count": int(flat["process_start_count"]),
            "retry_count": int(flat["retry_count"]),
            "raw_returncode": _integer(flat["raw_returncode"]),
            "timed_out": _boolean(flat["timed_out"]),
            "wall_time_s": _number(flat["wall_time_s"]),
        },
        "usability": {
            "status": flat["usability_status"],
            "failure_code": flat["failure_code"],
            "score_pose_count": _integer(flat["score_pose_count"]),
            "score_coverage_fraction": _number(flat["score_coverage_fraction"]),
            "score_first_output_delay_s": _number(flat["score_first_output_delay_s"]),
            "score_first_output_censor_reason": _none(flat["score_first_output_censor_reason"]),
            "score_longest_contiguous_count": _integer(flat["score_longest_contiguous_count"]),
            "score_longest_contiguous_fraction": _number(flat["score_longest_contiguous_fraction"]),
            "score_gap_count": _integer(flat["score_gap_count"]),
            "score_trajectory_span_s": _number(flat["score_trajectory_span_s"]),
            "keyframe_score_count": _integer(flat["keyframe_score_count"]),
        },
        "reference": {
            "kind": flat["reference_kind"],
            "independent_ground_truth": bool(_boolean(flat["independent_ground_truth"])),
            "native_rows_in_score": int(flat["native_reference_rows_in_score"]),
            "path": _none(flat["reference_path"]),
            "sha256": _none(flat["reference_sha256"]),
        },
        "comparability": {
            "history_match_existing_aqua_fe": bool(_boolean(flat["history_match_existing_aqua_fe"])),
            "score_support_match_existing_aqua_fe": bool(_boolean(flat["score_support_match_existing_aqua_fe"])),
            "pose_convention_match": bool(_boolean(flat["pose_convention_match"])),
            "evaluator_identity_match": bool(_boolean(flat["evaluator_identity_match"])),
            "input_rate_disclosed": bool(_boolean(flat["input_rate_disclosed"])),
        },
        "accuracy": {
            "state": flat["accuracy_state"],
            "block_codes": _pipe_strings(flat["accuracy_block_codes"]),
            "common_grid_count": _integer(flat["common_grid_count"]),
            "common_coverage": _number(flat["common_coverage"]),
            "common_span_s": _number(flat["common_span_s"]),
            "ape_valid": bool(_boolean(flat["ape_valid"])),
            "ape_rmse_m": _number(flat["ape_rmse_m"]),
            "ape_median_m": _number(flat["ape_median_m"]),
            "ape_max_m": _number(flat["ape_max_m"]),
            "rpe_valid": bool(_boolean(flat["rpe_valid"])),
            "rpe_delta_s": _number(flat["rpe_delta_s"]),
            "rpe_pairs": _integer(flat["rpe_pairs"]),
            "rpe_rmse_m": _number(flat["rpe_rmse_m"]),
            "rpe_median_m": _number(flat["rpe_median_m"]),
            "rpe_max_m": _number(flat["rpe_max_m"]),
        },
        "artifacts": {
            "selector_or_contract_path": _none(flat["selector_or_contract_path"]),
            "run_result_path": _none(flat["run_result_path"]),
            "trajectory_path": _none(flat["trajectory_path"]),
            "keyframe_trajectory_path": _none(flat["keyframe_trajectory_path"]),
            "execution_lock_path": _none(flat["execution_lock_path"]),
        },
        "notes": _none(flat["notes"]),
    }


def load_template(path: Path) -> Tuple[List[str], List[Dict[str, Any]]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = list(reader.fieldnames or [])
            rows = [_template_row_to_record(row) for row in reader]
    except (OSError, csv.Error, KeyError, TypeError, ValueError) as error:
        raise EvidenceError("INVALID_TEMPLATE:%s:%s" % (path, type(error).__name__)) from error
    ids = tuple(row["window_id"] for row in rows)
    if ids != WINDOW_ORDER:
        raise EvidenceError("TEMPLATE_WINDOW_ORDER_DRIFT:%r" % (ids,))
    if len(fieldnames) != len(set(fieldnames)):
        raise EvidenceError("TEMPLATE_DUPLICATE_COLUMNS")
    return fieldnames, rows


def _required_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvidenceError("%s_NOT_INTEGER" % label)
    return value


def _required_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise EvidenceError("%s_NOT_BOOLEAN" % label)
    return value


def _optional_nonnegative_number(value: Any, label: str) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceError("%s_NOT_NUMBER" % label)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise EvidenceError("%s_NOT_FINITE_NONNEGATIVE" % label)
    return result


def _execution_from_result(result: Mapping[str, Any]) -> Dict[str, Any]:
    source = result.get("execution")
    if not isinstance(source, Mapping):
        raise EvidenceError("RUN_RESULT_EXECUTION_MISSING")
    if "popen_invocations" in source:
        starts = _required_int(source["popen_invocations"], "POPEN_INVOCATIONS")
    elif "process_start_count" in source:
        starts = _required_int(source["process_start_count"], "PROCESS_START_COUNT")
    else:
        raise EvidenceError("RUN_RESULT_PROCESS_START_COUNT_MISSING")
    if "retry_count" in source:
        retries = _required_int(source["retry_count"], "RETRY_COUNT")
    elif "retry_performed" in source:
        retries = 1 if _required_bool(source["retry_performed"], "RETRY_PERFORMED") else 0
    else:
        supervision = result.get("supervision")
        if isinstance(supervision, Mapping) and "retry_performed" in supervision:
            retries = 1 if _required_bool(
                supervision["retry_performed"], "SUPERVISION_RETRY_PERFORMED"
            ) else 0
        else:
            raise EvidenceError("RUN_RESULT_RETRY_EVIDENCE_MISSING")
    raw = source.get("raw_returncode")
    if raw is not None:
        raw = _required_int(raw, "RAW_RETURNCODE")
    timed_out = source.get("timed_out")
    if timed_out is not None:
        timed_out = _required_bool(timed_out, "TIMED_OUT")
    duration = source.get("duration_seconds", source.get("wall_time_s"))
    duration = _optional_nonnegative_number(duration, "WALL_TIME")
    state = "COMPLETED"
    status = str(result.get("status", ""))
    if "INFRASTRUCTURE" in status:
        state = "INFRASTRUCTURE_FAILURE"
    return {
        "state": state,
        "process_start_count": starts,
        "retry_count": retries,
        "raw_returncode": raw,
        "timed_out": timed_out,
        "wall_time_s": duration,
    }


def _load_camera_timestamps(path: Path, expected_count: int) -> List[int]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream)
            header = next(reader)
            if header != ["#timestamp [ns]", "filename"]:
                raise EvidenceError("CAMERA_CSV_HEADER_DRIFT:%s" % path)
            rows = list(reader)
    except StopIteration as error:
        raise EvidenceError("CAMERA_CSV_EMPTY:%s" % path) from error
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        raise EvidenceError("CAMERA_CSV_UNREADABLE:%s:%s" % (path, type(error).__name__)) from error
    if len(rows) != expected_count:
        raise EvidenceError("CAMERA_CSV_COUNT:%s:%d!=%d" % (path, len(rows), expected_count))
    timestamps: List[int] = []
    for index, row in enumerate(rows):
        if len(row) != 2:
            raise EvidenceError("CAMERA_CSV_ROW_WIDTH:%s:%d" % (path, index))
        try:
            timestamp = int(row[0])
        except ValueError as error:
            raise EvidenceError("CAMERA_CSV_TIMESTAMP_INVALID:%s:%d" % (path, index)) from error
        if row[1] != "%d.png" % timestamp:
            raise EvidenceError("CAMERA_CSV_FILENAME_MISMATCH:%s:%d" % (path, index))
        if timestamps and timestamp <= timestamps[-1]:
            raise EvidenceError("CAMERA_CSV_NOT_STRICTLY_INCREASING:%s:%d" % (path, index))
        timestamps.append(timestamp)
    return timestamps


def _path_from_identity(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        path = value.get("path")
        if isinstance(path, str) and path:
            return path
    return None


def _accuracy_fail_closed(record: MutableMapping[str, Any], unusable: bool) -> None:
    accuracy = record["accuracy"]
    accuracy["state"] = "BLOCKED_UNUSABLE" if unusable else "BLOCKED"
    codes = list(accuracy.get("block_codes") or [])
    if unusable and "SYSTEM_UNUSABLE" not in codes:
        codes.insert(0, "SYSTEM_UNUSABLE")
    accuracy["block_codes"] = codes
    accuracy["common_grid_count"] = None
    accuracy["common_coverage"] = None
    accuracy["common_span_s"] = None
    accuracy["ape_valid"] = False
    accuracy["ape_rmse_m"] = None
    accuracy["ape_median_m"] = None
    accuracy["ape_max_m"] = None
    accuracy["rpe_valid"] = False
    accuracy["rpe_delta_s"] = 1.0
    accuracy["rpe_pairs"] = None
    accuracy["rpe_rmse_m"] = None
    accuracy["rpe_median_m"] = None
    accuracy["rpe_max_m"] = None


def _pending_record(base: Mapping[str, Any], source: WindowSource) -> Dict[str, Any]:
    record = copy.deepcopy(base)
    claim_path = source.run_result.parent / "process_start_claim.json"
    starts = 1 if claim_path.is_file() else 0
    record["execution"] = {
        "state": "PENDING",
        "process_start_count": starts,
        "retry_count": 0,
        "raw_returncode": None,
        "timed_out": None,
        "wall_time_s": None,
    }
    record["usability"] = {
        "status": "PENDING",
        "failure_code": "PENDING_NOT_STARTED",
        "score_pose_count": None,
        "score_coverage_fraction": None,
        "score_first_output_delay_s": None,
        "score_first_output_censor_reason": (
            "PROCESS_STARTED_TERMINAL_RUN_RESULT_NOT_SEALED" if starts else "NOT_STARTED_OR_NO_START_CLAIM"
        ),
        "score_longest_contiguous_count": None,
        "score_longest_contiguous_fraction": None,
        "score_gap_count": None,
        "score_trajectory_span_s": None,
        "keyframe_score_count": None,
    }
    record["artifacts"]["selector_or_contract_path"] = (
        str(source.selector_or_contract) if source.selector_or_contract else None
    )
    record["artifacts"]["run_result_path"] = str(source.run_result)
    record["artifacts"]["trajectory_path"] = None
    record["artifacts"]["keyframe_trajectory_path"] = None
    record["artifacts"]["execution_lock_path"] = (
        str(source.execution_lock) if source.execution_lock else None
    )
    record["notes"] = (
        (record.get("notes") or "")
        + "; run_result absent at analysis snapshot: PENDING, never imputed as FAIL or zero support"
    ).lstrip("; ")
    _accuracy_fail_closed(record, unusable=False)
    return record


def _current_failure_code(
    execution: Mapping[str, Any], trajectory: Mapping[str, Any], usability: Mapping[str, Any]
) -> str:
    if execution["state"] == "INFRASTRUCTURE_FAILURE":
        return "INFRASTRUCTURE_FAILURE"
    if execution["process_start_count"] != 1 or execution["retry_count"] != 0:
        return "INFRASTRUCTURE_FAILURE"
    if execution["timed_out"] is True:
        return "TIMEOUT"
    if execution["raw_returncode"] != 0:
        return "NONZERO_RETURN_CODE" if execution["raw_returncode"] is not None else "INFRASTRUCTURE_FAILURE"
    if trajectory.get("exists") is not True:
        return "NO_TRAJECTORY"
    errors = "|".join(str(value).upper() for value in (trajectory.get("errors") or []))
    if "NONFINITE" in errors or "NOT_FINITE" in errors:
        return "NONFINITE_TRAJECTORY"
    if trajectory.get("strictly_increasing_timestamps") is not True:
        return "NONMONOTONIC_TRAJECTORY"
    if trajectory.get("valid") is not True:
        return "INFRASTRUCTURE_FAILURE"
    coverage = usability.get("score_coverage_fraction")
    contiguous = usability.get("score_longest_contiguous_fraction")
    keyframes = usability.get("keyframe_score_count")
    if coverage is None or coverage < PASS_COVERAGE:
        return "INSUFFICIENT_SCORE_COVERAGE"
    if contiguous is None or contiguous < PASS_CONTIGUOUS:
        return "INSUFFICIENT_CONTINUOUS_SUPPORT"
    if keyframes is None or keyframes < 1:
        return "NO_SCORE_KEYFRAME"
    return "NONE"


def _normalise_current(
    base: Mapping[str, Any], source: WindowSource, result: Mapping[str, Any]
) -> Dict[str, Any]:
    record = copy.deepcopy(base)
    record["execution"] = _execution_from_result(result)
    support = result.get("support")
    if not isinstance(support, Mapping):
        record["execution"]["state"] = "INFRASTRUCTURE_FAILURE"
        record["usability"] = {
            "status": "FAIL",
            "failure_code": "INFRASTRUCTURE_FAILURE",
            "score_pose_count": None,
            "score_coverage_fraction": None,
            "score_first_output_delay_s": None,
            "score_first_output_censor_reason": "RUN_RESULT_SUPPORT_MISSING",
            "score_longest_contiguous_count": None,
            "score_longest_contiguous_fraction": None,
            "score_gap_count": None,
            "score_trajectory_span_s": None,
            "keyframe_score_count": None,
        }
        trajectory: Mapping[str, Any] = {}
        keyframes: Mapping[str, Any] = {}
    else:
        trajectory_value = support.get("trajectory")
        keyframes_value = support.get("keyframes")
        trajectory = trajectory_value if isinstance(trajectory_value, Mapping) else {}
        keyframes = keyframes_value if isinstance(keyframes_value, Mapping) else {}
        score_value = trajectory.get("score")
        keyframe_score_value = keyframes.get("score")
        score = score_value if isinstance(score_value, Mapping) else {}
        keyframe_score = keyframe_score_value if isinstance(keyframe_score_value, Mapping) else {}
        expected = record["score"]["expected_frame_count"]
        count = score.get("count")
        if count is not None:
            count = _required_int(count, "SCORE_POSE_COUNT")
        coverage = _optional_nonnegative_number(score.get("coverage_fraction"), "SCORE_COVERAGE")
        if count is not None and coverage is not None:
            exact = count / expected
            if abs(exact - coverage) > 1e-12:
                raise EvidenceError("SCORE_COVERAGE_CONTRADICTS_COUNT:%s" % record["window_id"])
        longest = score.get("longest_contiguous_run")
        if longest is not None:
            longest = _required_int(longest, "LONGEST_CONTIGUOUS")
        longest_fraction = None if longest is None else longest / expected
        gap_count = score.get("gap_count")
        if gap_count is not None:
            gap_count = _required_int(gap_count, "SCORE_GAP_COUNT")
        keyframe_count = keyframe_score.get("count")
        if keyframe_count is not None:
            keyframe_count = _required_int(keyframe_count, "KEYFRAME_SCORE_COUNT")
        first_index = score.get("first_index")
        last_index = score.get("last_index")
        if first_index is not None:
            first_index = _required_int(first_index, "SCORE_FIRST_INDEX")
        if last_index is not None:
            last_index = _required_int(last_index, "SCORE_LAST_INDEX")
        delay: Optional[float] = None
        span: Optional[float] = None
        censor: Optional[str] = None
        if count is not None and count > 0:
            if first_index is None or last_index is None:
                raise EvidenceError("POSITIVE_SCORE_COUNT_WITHOUT_ENDPOINTS:%s" % record["window_id"])
            timestamps = _load_camera_timestamps(source.camera_csv, record["feed"]["frame_count"])
            score_relative_start = record["score"]["start_index"] - record["feed"]["start_index"]
            score_relative_end = record["score"]["end_index"] - record["feed"]["start_index"]
            if not (score_relative_start <= first_index <= last_index <= score_relative_end):
                raise EvidenceError("SCORE_SUPPORT_OUTSIDE_FROZEN_WINDOW:%s" % record["window_id"])
            delay = (timestamps[first_index] - timestamps[score_relative_start]) / 1e9
            span = (timestamps[last_index] - timestamps[first_index]) / 1e9
        elif count == 0:
            censor = "NO_SCORE_TRAJECTORY_OUTPUT"
        else:
            censor = "SCORE_SUPPORT_FIELDS_MISSING"
        usability = {
            "status": "FAIL",
            "failure_code": "INFRASTRUCTURE_FAILURE",
            "score_pose_count": count,
            "score_coverage_fraction": coverage,
            "score_first_output_delay_s": delay,
            "score_first_output_censor_reason": censor,
            "score_longest_contiguous_count": longest,
            "score_longest_contiguous_fraction": longest_fraction,
            "score_gap_count": gap_count,
            "score_trajectory_span_s": span,
            "keyframe_score_count": keyframe_count,
        }
        code = _current_failure_code(record["execution"], trajectory, usability)
        usability["failure_code"] = code
        usability["status"] = "PASS" if code == "NONE" else "FAIL"
        record["usability"] = usability

    producer_status = result.get("status")
    controller_return_code = result.get("return_code")
    if not isinstance(producer_status, str) or not producer_status:
        raise EvidenceError("PRODUCER_TERMINAL_STATUS_MISSING:%s" % record["window_id"])
    controller_return_code = _required_int(
        controller_return_code, "PRODUCER_CONTROLLER_RETURN_CODE"
    )
    if producer_status.startswith("PASS_"):
        if record["usability"]["status"] != "PASS" or controller_return_code != 0:
            raise EvidenceError("PRODUCER_PASS_CONTRADICTS_STRICT_ANALYSIS:%s" % record["window_id"])
    elif producer_status.startswith("FAIL_"):
        if record["usability"]["status"] != "FAIL" or controller_return_code == 0:
            raise EvidenceError("PRODUCER_FAIL_CONTRADICTS_STRICT_ANALYSIS:%s" % record["window_id"])
    else:
        raise EvidenceError("UNKNOWN_PRODUCER_TERMINAL_STATUS:%s:%s" % (record["window_id"], producer_status))

    if record["window_id"] == A02:
        if result.get("schema_version") != "aqua-fe-hfnet-v6-a02-0001-6300-strict70-run-result-v2":
            raise EvidenceError("A02_STRICT70_RESULT_SCHEMA_DRIFT")
        adjudication = support.get("strict70_trajectory_adjudication") if isinstance(support, Mapping) else None
        if not isinstance(adjudication, Mapping):
            raise EvidenceError("A02_STRICT70_ADJUDICATION_MISSING")
        expected_adjudication = {
            "score_camera_count": 1801,
            "minimum_score_poses": 1261,
            "minimum_contiguous_score_poses": 1261,
            "score_pose_count": record["usability"]["score_pose_count"],
            "longest_contiguous_score_poses": record["usability"]["score_longest_contiguous_count"],
            "pass": False,
        }
        for name, expected_value in expected_adjudication.items():
            if adjudication.get(name) != expected_value:
                raise EvidenceError("A02_STRICT70_ADJUDICATION_DRIFT:%s" % name)
        pins = result.get("pins")
        lock_pin = pins.get("execution_lock") if isinstance(pins, Mapping) else None
        if not isinstance(lock_pin, Mapping):
            raise EvidenceError("A02_STRICT70_RESULT_LOCK_PIN_MISSING")
        if source.execution_lock is None or lock_pin.get("path") != str(source.execution_lock):
            raise EvidenceError("A02_STRICT70_RESULT_LOCK_PATH_DRIFT")
        if lock_pin.get("sha256") != _sha256(source.execution_lock):
            raise EvidenceError("A02_STRICT70_RESULT_LOCK_HASH_DRIFT")

    record["notes"] = (
        (record.get("notes") or "")
        + "; producer_status=%s; controller_return_code=%d; raw_returncode=%s"
        % (producer_status, controller_return_code, record["execution"]["raw_returncode"])
    ).lstrip("; ")

    record["artifacts"]["selector_or_contract_path"] = (
        str(source.selector_or_contract) if source.selector_or_contract else None
    )
    record["artifacts"]["run_result_path"] = str(source.run_result)
    record["artifacts"]["trajectory_path"] = _path_from_identity(trajectory.get("identity"))
    record["artifacts"]["keyframe_trajectory_path"] = _path_from_identity(keyframes.get("identity"))
    record["artifacts"]["execution_lock_path"] = (
        str(source.execution_lock) if source.execution_lock else None
    )
    _accuracy_fail_closed(record, unusable=record["usability"]["status"] == "FAIL")
    return record


def _normalise_legacy(
    base: Mapping[str, Any], source: WindowSource, result: Mapping[str, Any]
) -> Dict[str, Any]:
    record = copy.deepcopy(base)
    execution = _execution_from_result(result)
    record["execution"] = execution
    gate = result.get("gate")
    if not isinstance(gate, Mapping):
        raise EvidenceError("LEGACY_GATE_MISSING")
    trajectory = gate.get("trajectory")
    keyframes = gate.get("keyframe_trajectory")
    if not isinstance(trajectory, Mapping) or not isinstance(keyframes, Mapping):
        raise EvidenceError("LEGACY_TRAJECTORY_GATE_MISSING")
    count = _required_int(trajectory.get("score_pose_count"), "LEGACY_SCORE_POSE_COUNT")
    first_index = _required_int(
        trajectory.get("associated_first_relative_camera_index"), "LEGACY_FIRST_INDEX"
    )
    last_index = _required_int(
        trajectory.get("associated_last_relative_camera_index"), "LEGACY_LAST_INDEX"
    )
    expected = record["score"]["expected_frame_count"]
    timestamps = _load_camera_timestamps(source.camera_csv, record["feed"]["frame_count"])
    score_relative_start = record["score"]["start_index"] - record["feed"]["start_index"]
    delay = (timestamps[first_index] - timestamps[score_relative_start]) / 1e9
    associated_span = (timestamps[last_index] - timestamps[first_index]) / 1e9
    span = _optional_nonnegative_number(
        trajectory.get("score_span_seconds"), "LEGACY_SCORE_TRAJECTORY_SPAN"
    )
    if span is None:
        raise EvidenceError("LEGACY_SCORE_TRAJECTORY_SPAN_MISSING")
    association_tolerance_s = float(trajectory.get("association_max_abs_error_ns", 0)) * 2.0 / 1e9
    if abs(span - associated_span) > association_tolerance_s + 1e-12:
        raise EvidenceError("LEGACY_SCORE_SPAN_EXCEEDS_ASSOCIATION_TOLERANCE")
    skipped = _required_int(trajectory.get("associated_skipped_camera_count"), "LEGACY_SKIPPED")
    max_gap = _required_int(trajectory.get("associated_max_camera_index_gap"), "LEGACY_MAX_GAP")
    if skipped == 0 and max_gap <= 1:
        longest = count
        gap_count = 0
    else:
        raise EvidenceError("LEGACY_CONTIGUITY_CANNOT_BE_DERIVED_WITHOUT_IMPUTATION")
    keyframe_count = _required_int(keyframes.get("score_pose_count"), "LEGACY_KEYFRAME_COUNT")
    record["usability"] = {
        "status": "FAIL",
        "failure_code": "LATE_INITIALIZATION_INSUFFICIENT_SCORE_SUPPORT",
        "score_pose_count": count,
        "score_coverage_fraction": count / expected,
        "score_first_output_delay_s": delay,
        "score_first_output_censor_reason": None,
        "score_longest_contiguous_count": longest,
        "score_longest_contiguous_fraction": longest / expected,
        "score_gap_count": gap_count,
        "score_trajectory_span_s": span,
        "keyframe_score_count": keyframe_count,
    }
    frozen = base["usability"]
    for field in (
        "score_pose_count",
        "score_coverage_fraction",
        "score_first_output_delay_s",
        "score_longest_contiguous_count",
        "score_longest_contiguous_fraction",
        "score_gap_count",
        "score_trajectory_span_s",
        "keyframe_score_count",
    ):
        observed = record["usability"][field]
        expected_value = frozen[field]
        if isinstance(observed, float):
            if expected_value is None or abs(observed - float(expected_value)) > 1e-12:
                raise EvidenceError("LEGACY_FROZEN_METRIC_DRIFT:%s" % field)
        elif observed != expected_value:
            raise EvidenceError("LEGACY_FROZEN_METRIC_DRIFT:%s" % field)
    record["artifacts"]["selector_or_contract_path"] = (
        str(source.selector_or_contract) if source.selector_or_contract else None
    )
    record["artifacts"]["run_result_path"] = str(source.run_result)
    record["artifacts"]["trajectory_path"] = _path_from_identity(trajectory.get("identity"))
    record["artifacts"]["keyframe_trajectory_path"] = _path_from_identity(keyframes.get("identity"))
    record["artifacts"]["execution_lock_path"] = None
    _accuracy_fail_closed(record, unusable=True)
    return record


def _schema_type_ok(instance: Any, expected: str) -> bool:
    if expected == "null":
        return instance is None
    if expected == "boolean":
        return isinstance(instance, bool)
    if expected == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if expected == "number":
        return isinstance(instance, (int, float)) and not isinstance(instance, bool) and math.isfinite(instance)
    if expected == "string":
        return isinstance(instance, str)
    if expected == "object":
        return isinstance(instance, Mapping)
    if expected == "array":
        return isinstance(instance, list)
    return True


def _schema_errors(instance: Any, schema: Mapping[str, Any], path: str = "$") -> List[str]:
    errors: List[str] = []
    expected = schema.get("type")
    if expected is not None:
        choices = expected if isinstance(expected, list) else [expected]
        if not any(_schema_type_ok(instance, choice) for choice in choices):
            return ["%s:type:%r" % (path, expected)]
    if "const" in schema and instance != schema["const"]:
        errors.append("%s:const:%r" % (path, schema["const"]))
    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s:enum:%r" % (path, schema["enum"]))
    if isinstance(instance, Mapping):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for name in required:
            if name not in instance:
                errors.append("%s:required:%s" % (path, name))
        if schema.get("additionalProperties") is False:
            for name in instance:
                if name not in properties:
                    errors.append("%s:additional:%s" % (path, name))
        for name, subschema in properties.items():
            if name in instance:
                errors.extend(_schema_errors(instance[name], subschema, "%s.%s" % (path, name)))
    if isinstance(instance, list):
        if schema.get("uniqueItems"):
            serialised = [json.dumps(value, sort_keys=True) for value in instance]
            if len(serialised) != len(set(serialised)):
                errors.append("%s:uniqueItems" % path)
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, value in enumerate(instance):
                errors.extend(_schema_errors(value, item_schema, "%s[%d]" % (path, index)))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append("%s:minLength" % path)
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            errors.append("%s:pattern" % path)
    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append("%s:minimum" % path)
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append("%s:maximum" % path)
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append("%s:exclusiveMinimum" % path)
    for conditional in schema.get("allOf", []):
        condition = conditional.get("if")
        if isinstance(condition, Mapping) and not _schema_errors(instance, condition, path):
            then = conditional.get("then")
            if isinstance(then, Mapping):
                errors.extend(_schema_errors(instance, then, path))
    return errors


def validate_records(records: Sequence[Mapping[str, Any]], schema: Mapping[str, Any]) -> None:
    ids = tuple(record.get("window_id") for record in records)
    if ids != WINDOW_ORDER:
        raise EvidenceError("OUTPUT_WINDOW_ORDER_DRIFT:%r" % (ids,))
    if sum(record["row_role"] == "CURRENT_PROTOCOL_WINDOW" for record in records) != 3:
        raise EvidenceError("CURRENT_WINDOW_DENOMINATOR_NOT_THREE")
    if sum(record["row_role"] == "LEGACY_TERMINAL_CONTEXT" for record in records) != 1:
        raise EvidenceError("LEGACY_CONTEXT_COUNT_NOT_ONE")
    for record in records:
        errors = _schema_errors(record, schema)
        if errors:
            raise EvidenceError("ROW_SCHEMA_INVALID:%s:%s" % (record.get("window_id"), ";".join(errors[:20])))
        if record["schema_version"] != ROW_SCHEMA_VERSION or record["protocol_id"] != PROTOCOL_ID:
            raise EvidenceError("ROW_PROTOCOL_IDENTITY_DRIFT:%s" % record["window_id"])
        accuracy = record["accuracy"]
        if accuracy["state"] not in ("BLOCKED", "BLOCKED_UNUSABLE"):
            raise EvidenceError("ACCURACY_GATE_OPEN_FORBIDDEN:%s" % record["window_id"])
        if accuracy["ape_valid"] or accuracy["rpe_valid"]:
            raise EvidenceError("ACCURACY_VALID_FLAG_FORBIDDEN:%s" % record["window_id"])
        for metric in (
            "ape_rmse_m", "ape_median_m", "ape_max_m",
            "rpe_rmse_m", "rpe_median_m", "rpe_max_m",
        ):
            if accuracy[metric] is not None:
                raise EvidenceError("ACCURACY_NUMERIC_IMPUTATION_FORBIDDEN:%s:%s" % (record["window_id"], metric))
        usability = record["usability"]
        if usability["status"] == "PENDING":
            for metric in (
                "score_pose_count", "score_coverage_fraction", "score_first_output_delay_s",
                "score_longest_contiguous_count", "score_longest_contiguous_fraction",
                "score_gap_count", "score_trajectory_span_s", "keyframe_score_count",
            ):
                if usability[metric] is not None:
                    raise EvidenceError("PENDING_SUPPORT_IMPUTATION_FORBIDDEN:%s:%s" % (record["window_id"], metric))
        if usability["status"] == "PASS":
            if usability["failure_code"] != "NONE":
                raise EvidenceError("PASS_WITH_FAILURE_CODE:%s" % record["window_id"])
            if usability["score_coverage_fraction"] < PASS_COVERAGE:
                raise EvidenceError("PASS_BELOW_COVERAGE_GATE:%s" % record["window_id"])
            if usability["score_longest_contiguous_fraction"] < PASS_CONTIGUOUS:
                raise EvidenceError("PASS_BELOW_CONTIGUITY_GATE:%s" % record["window_id"])
            if usability["keyframe_score_count"] < 1:
                raise EvidenceError("PASS_WITHOUT_KEYFRAME:%s" % record["window_id"])


def build_records(inputs: AnalysisInputs) -> Tuple[List[str], List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not inputs.protocol.is_file():
        raise EvidenceError("PROTOCOL_MISSING:%s" % inputs.protocol)
    fieldnames, bases = load_template(inputs.csv_template)
    schema = _read_json(inputs.row_schema)
    records: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    for base in bases:
        window_id = base["window_id"]
        source = inputs.sources[window_id]
        if not source.run_result.is_file():
            if not source.pending_allowed:
                raise EvidenceError("REQUIRED_TERMINAL_RUN_RESULT_MISSING:%s:%s" % (window_id, source.run_result))
            record = _pending_record(base, source)
            result_identity = None
        else:
            result = _read_json(source.run_result)
            if window_id == LEGACY_A02:
                record = _normalise_legacy(base, source, result)
            else:
                record = _normalise_current(base, source, result)
            result_identity = _identity(source.run_result)
        records.append(record)
        evidence.append({
            "window_id": window_id,
            "row_role": record["row_role"],
            "selector_or_contract": _identity(source.selector_or_contract),
            "feed_selector_provenance": _identity(source.feed_selector),
            "run_result": result_identity or {"path": str(source.run_result), "state": "PENDING_ABSENT"},
            "camera_csv": _identity(source.camera_csv),
            "execution_lock": _identity(source.execution_lock),
            "producer_terminal": (
                {
                    "status": result.get("status"),
                    "controller_return_code": result.get("return_code"),
                    "raw_returncode": result.get("execution", {}).get("raw_returncode")
                    if isinstance(result.get("execution"), Mapping) else None,
                }
                if source.run_result.is_file() else None
            ),
        })
    validate_records(records, schema)
    return fieldnames, records, evidence


def _flat_bool(value: bool) -> str:
    return "true" if value else "false"


def _flat_optional(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return _flat_bool(value)
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _record_to_flat(record: Mapping[str, Any]) -> Dict[str, str]:
    feed = record["feed"]
    score = record["score"]
    sync = record["synchronization"]
    execution = record["execution"]
    usability = record["usability"]
    reference = record["reference"]
    comparability = record["comparability"]
    accuracy = record["accuracy"]
    artifacts = record["artifacts"]
    return {
        "schema_version": record["schema_version"],
        "protocol_id": record["protocol_id"],
        "row_role": record["row_role"],
        "attempt_relation": record["attempt_relation"],
        "window_id": record["window_id"],
        "dataset_family": record["dataset_family"],
        "sequence": record["sequence"],
        "method_id": record["method_id"],
        "system_class": record["system_class"],
        "evidence_role": record["evidence_role"],
        "feed_start_index": _flat_optional(feed["start_index"]),
        "feed_end_index": _flat_optional(feed["end_index"]),
        "feed_frame_count": _flat_optional(feed["frame_count"]),
        "preroll_start_index": _flat_optional(feed["preroll_start_index"]),
        "preroll_end_index": _flat_optional(feed["preroll_end_index"]),
        "score_start_index": _flat_optional(score["start_index"]),
        "score_end_index": _flat_optional(score["end_index"]),
        "score_frame_count_expected": _flat_optional(score["expected_frame_count"]),
        "score_nominal_duration_s": _flat_optional(score["nominal_duration_s"]),
        "input_rate_hz": _flat_optional(feed["input_rate_hz"]),
        "sync_trim_applied": _flat_bool(sync["sync_trim_applied"]),
        "sync_trimmed_source_indices": "|".join(str(value) for value in sync["trimmed_source_indices"]),
        "sync_trim_reason": sync["trim_reason"],
        "camera0_has_shifted_imu_predecessor": _flat_optional(sync["camera0_has_shifted_imu_predecessor"]),
        "first_fed_camera_has_shifted_imu_predecessor": _flat_optional(sync["first_fed_camera_has_shifted_imu_predecessor"]),
        "synthetic_or_extrapolated_imu_permitted": _flat_bool(sync["synthetic_or_extrapolated_imu_permitted"]),
        "execution_state": execution["state"],
        "process_start_count": _flat_optional(execution["process_start_count"]),
        "retry_count": _flat_optional(execution["retry_count"]),
        "raw_returncode": _flat_optional(execution["raw_returncode"]),
        "timed_out": _flat_optional(execution["timed_out"]),
        "wall_time_s": _flat_optional(execution["wall_time_s"]),
        "usability_status": usability["status"],
        "failure_code": usability["failure_code"],
        "score_pose_count": _flat_optional(usability["score_pose_count"]),
        "score_coverage_fraction": _flat_optional(usability["score_coverage_fraction"]),
        "score_first_output_delay_s": _flat_optional(usability["score_first_output_delay_s"]),
        "score_first_output_censor_reason": _flat_optional(usability["score_first_output_censor_reason"]),
        "score_longest_contiguous_count": _flat_optional(usability["score_longest_contiguous_count"]),
        "score_longest_contiguous_fraction": _flat_optional(usability["score_longest_contiguous_fraction"]),
        "score_gap_count": _flat_optional(usability["score_gap_count"]),
        "score_trajectory_span_s": _flat_optional(usability["score_trajectory_span_s"]),
        "keyframe_score_count": _flat_optional(usability["keyframe_score_count"]),
        "reference_kind": reference["kind"],
        "independent_ground_truth": _flat_bool(reference["independent_ground_truth"]),
        "native_reference_rows_in_score": _flat_optional(reference["native_rows_in_score"]),
        "reference_path": _flat_optional(reference["path"]),
        "reference_sha256": _flat_optional(reference["sha256"]),
        "history_match_existing_aqua_fe": _flat_bool(comparability["history_match_existing_aqua_fe"]),
        "score_support_match_existing_aqua_fe": _flat_bool(comparability["score_support_match_existing_aqua_fe"]),
        "pose_convention_match": _flat_bool(comparability["pose_convention_match"]),
        "evaluator_identity_match": _flat_bool(comparability["evaluator_identity_match"]),
        "input_rate_disclosed": _flat_bool(comparability["input_rate_disclosed"]),
        "accuracy_state": accuracy["state"],
        "accuracy_block_codes": "|".join(accuracy["block_codes"]),
        "common_grid_count": _flat_optional(accuracy["common_grid_count"]),
        "common_coverage": _flat_optional(accuracy["common_coverage"]),
        "common_span_s": _flat_optional(accuracy["common_span_s"]),
        "ape_valid": _flat_bool(accuracy["ape_valid"]),
        "ape_rmse_m": _flat_optional(accuracy["ape_rmse_m"]),
        "ape_median_m": _flat_optional(accuracy["ape_median_m"]),
        "ape_max_m": _flat_optional(accuracy["ape_max_m"]),
        "rpe_valid": _flat_bool(accuracy["rpe_valid"]),
        "rpe_delta_s": _flat_optional(accuracy["rpe_delta_s"]),
        "rpe_pairs": _flat_optional(accuracy["rpe_pairs"]),
        "rpe_rmse_m": _flat_optional(accuracy["rpe_rmse_m"]),
        "rpe_median_m": _flat_optional(accuracy["rpe_median_m"]),
        "rpe_max_m": _flat_optional(accuracy["rpe_max_m"]),
        "selector_or_contract_path": _flat_optional(artifacts["selector_or_contract_path"]),
        "run_result_path": _flat_optional(artifacts["run_result_path"]),
        "trajectory_path": _flat_optional(artifacts["trajectory_path"]),
        "keyframe_trajectory_path": _flat_optional(artifacts["keyframe_trajectory_path"]),
        "execution_lock_path": _flat_optional(artifacts["execution_lock_path"]),
        "notes": _flat_optional(record.get("notes")),
    }


def _current_summary(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    current = [record for record in records if record["row_role"] == "CURRENT_PROTOCOL_WINDOW"]
    pending = [record for record in current if record["usability"]["status"] == "PENDING"]
    usable = [record for record in current if record["usability"]["status"] == "PASS"]
    failed = [record for record in current if record["usability"]["status"] == "FAIL"]
    final_display = None if pending else "%d/3" % len(usable)
    return {
        "unit_of_analysis": "frozen_current_protocol_window",
        "denominator": 3,
        "legacy_context_excluded_from_denominator": True,
        "terminal_count": 3 - len(pending),
        "pending_count": len(pending),
        "usable_terminal_count": len(usable),
        "failed_terminal_count": len(failed),
        "final_usable_k_of_3": final_display,
    }


def _figure_catalog(generated: bool) -> List[Dict[str, Any]]:
    items = [
        (
            "figure-01-usability-matrix-v2",
            "Show each protocol usability gate without collapsing heterogeneous windows into a mean.",
            "Columns are three current windows plus a visually separated legacy context; cells are PASS/FAIL/PENDING.",
            "Current denominator is n=3; legacy A02 is excluded; no uncertainty bars or significance marks apply.",
        ),
        (
            "figure-02-score-support-v2",
            "Compare observed score-pose support with each row's frozen expected support.",
            "Bars encode support fractions and annotate exact produced/expected counts; missing terminal results are never plotted as zero.",
            "Legacy A02 is isolated from the current panel and failures retain observed support rather than a penalty value.",
        ),
        (
            "figure-03-feed-score-timeline-v2",
            "Expose feed history, preroll, score interval, synchronization trim, and first score output timing.",
            "Time is measured from each feed start; the first-output marker appears only when observed.",
            "Different histories block a head-to-head accuracy claim even when usability passes.",
        ),
    ]
    return [
        {
            "stem": stem,
            "pdf": "figures/%s.pdf" % stem if generated else None,
            "svg": "figures/%s.svg" % stem if generated else None,
            "state": "GENERATED" if generated else "WITHHELD_PENDING_CURRENT_RESULTS",
            "purpose": purpose,
            "caption_requirements": caption,
            "interpretation_boundary": boundary,
        }
        for stem, purpose, caption, boundary in items
    ]


def build_bundle(
    records: Sequence[Mapping[str, Any]], evidence: Sequence[Mapping[str, Any]], generated_at: str
) -> Dict[str, Any]:
    summary = _current_summary(records)
    pending = summary["pending_count"] > 0
    return {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "presentation_revision": PRESENTATION_REVISION,
        "protocol_id": PROTOCOL_ID,
        "analysis_state": "PENDING_CURRENT_RESULTS" if pending else "TERMINAL_DESCRIPTIVE_ONLY",
        "generated_at_utc": generated_at,
        "analysis_question": "Can official HFNet-SLAM produce usable trajectories on three frozen AQUALOC development windows?",
        "current_protocol_summary": summary,
        "statistical_gate": {
            "current_n": 3,
            "legacy_n_context": 1,
            "legacy_in_current_denominator": False,
            "independent_repeated_runs_per_window": 1,
            "significance_tests_permitted": False,
            "confidence_intervals_permitted": False,
            "mean_or_standard_deviation_across_windows_permitted": False,
            "cross_window_winner_ranking_permitted": False,
            "reason": "Three heterogeneous development-exposed windows with one frozen run each are not independent repeated samples.",
        },
        "accuracy_gate": {
            "state": "BLOCKED_ALL_ROWS",
            "ape_rpe_numeric_values_permitted": False,
            "failure_penalty_or_zero_imputation_permitted": False,
            "reason": "History/support/evaluator mismatches remain; short windows also lack required native proxy support, and unusable rows cannot enter accuracy analysis.",
        },
        "rows": list(records),
        "input_evidence": list(evidence),
        "figures_generated": not pending,
        "figure_catalog": _figure_catalog(not pending),
    }


def _short_label(window_id: str) -> str:
    return {
        A06: "A06\ncurrent",
        H07: "H07\ncurrent",
        A02: "A02 full history\ncurrent",
        LEGACY_A02: "A02 cold start\nlegacy (excluded)",
    }[window_id]


def _gate_cells(record: Mapping[str, Any]) -> List[str]:
    execution = record["execution"]
    usability = record["usability"]
    if usability["status"] == "PENDING":
        return ["PENDING"] * 5
    execution_pass = (
        execution["state"] == "COMPLETED"
        and execution["process_start_count"] == 1
        and execution["retry_count"] == 0
        and execution["raw_returncode"] == 0
        and execution["timed_out"] is False
    )
    coverage = usability["score_coverage_fraction"]
    contiguous = usability["score_longest_contiguous_fraction"]
    keyframes = usability["keyframe_score_count"]
    return [
        "PASS" if execution_pass else "FAIL",
        "PASS" if coverage is not None and coverage >= PASS_COVERAGE else "FAIL",
        "PASS" if contiguous is not None and contiguous >= PASS_CONTIGUOUS else "FAIL",
        "PASS" if keyframes is not None and keyframes >= 1 else "FAIL",
        usability["status"],
    ]


def _save_vector(fig: Any, directory: Path, stem: str) -> None:
    metadata_svg = {"Date": None, "Creator": "AQUA-FE strict multi-window generator v2"}
    metadata_pdf = {
        "Creator": "AQUA-FE strict multi-window generator v2",
        "CreationDate": None,
        "ModDate": None,
    }
    fig.savefig(directory / (stem + ".svg"), bbox_inches="tight", metadata=metadata_svg)
    fig.savefig(directory / (stem + ".pdf"), bbox_inches="tight", metadata=metadata_pdf)


def generate_figures(records: Sequence[Mapping[str, Any]], sources: Mapping[str, WindowSource], directory: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch, Rectangle
    from matplotlib.lines import Line2D

    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 9,
        "axes.labelsize": 10,
        "xtick.labelsize": 8,
        "ytick.labelsize": 8,
        "legend.fontsize": 8,
        "pdf.fonttype": 42,
        "svg.fonttype": "none",
    })
    colours = {"PASS": "#0072B2", "FAIL": "#D55E00", "PENDING": "#BDBDBD"}

    # Figure 1: explicit gate matrix, with legacy visually separated.
    gate_names = ["Execution\n1 start, 0 retry", "Coverage\n>= 0.70", "Contiguous\n>= 0.70", "Score KFs\n>= 1", "Overall\nusability"]
    fig, ax = plt.subplots(figsize=(7.2, 3.55))
    for x, record in enumerate(records):
        for y, state in enumerate(_gate_cells(record)):
            ax.add_patch(Rectangle((x, y), 1, 1, facecolor=colours[state], edgecolor="white", linewidth=1.5))
            ax.text(x + 0.5, y + 0.5, state, ha="center", va="center", color="white" if state != "PENDING" else "black", fontsize=8, weight="bold")
    ax.axvline(3, color="black", linewidth=1.6, linestyle="--")
    ax.text(1.5, -0.48, "current protocol denominator: n=3", ha="center", va="center", fontsize=8)
    ax.text(3.5, -0.48, "legacy context\nexcluded", ha="center", va="center", fontsize=8)
    ax.set_xlim(0, 4)
    ax.set_ylim(5, -0.75)
    ax.set_xticks([0.5, 1.5, 2.5, 3.5], [_short_label(record["window_id"]) for record in records])
    ax.set_yticks([index + 0.5 for index in range(5)], gate_names)
    ax.tick_params(length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.legend(
        handles=[Patch(facecolor=colours[state], label=state) for state in ("PASS", "FAIL", "PENDING")],
        loc="upper center", bbox_to_anchor=(0.5, 1.13), ncol=3, frameon=False,
    )
    fig.subplots_adjust(top=0.82, bottom=0.22, left=0.19, right=0.99)
    _save_vector(fig, directory, "figure-01-usability-matrix-v2")
    plt.close(fig)

    # Figure 2: normalized support with exact count annotations.
    fig, (ax_current, ax_legacy) = plt.subplots(
        1, 2, figsize=(7.6, 3.45), sharex=True,
        gridspec_kw={"width_ratios": [3.15, 1.15], "wspace": 0.30},
    )
    for ax, subset, title in (
        (ax_current, records[:3], "Current protocol windows (n=3)"),
        (ax_legacy, records[3:], "Legacy context\n(excluded)"),
    ):
        for y, record in enumerate(subset):
            expected = record["score"]["expected_frame_count"]
            observed = record["usability"]["score_pose_count"]
            ax.barh(y, 1.0, color="#EEEEEE", edgecolor="#555555", height=0.58, linewidth=1.0, hatch="//" if record["row_role"] == "LEGACY_TERMINAL_CONTEXT" else None)
            if observed is None:
                ax.text(0.03, y, "PENDING; produced count unknown", va="center", ha="left", fontsize=8)
            else:
                fraction = observed / expected
                colour = colours[record["usability"]["status"]]
                ax.barh(y, fraction, color=colour, height=0.42)
                label = "%d / %d\n(%.3f)" % (observed, expected, fraction)
                if fraction >= 0.55:
                    ax.text(
                        0.975, y, label, va="center", ha="right", fontsize=8,
                        color="white", weight="bold", linespacing=1.05,
                    )
                else:
                    ax.text(
                        max(fraction + 0.03, 0.05), y, label,
                        va="center", ha="left", fontsize=8, color="black", linespacing=1.05,
                    )
        ax.set_yticks(range(len(subset)), [record["sequence"] for record in subset])
        ax.invert_yaxis()
        ax.set_xlim(0, 1.06)
        ax.set_title(title, fontsize=9)
        ax.grid(axis="x", alpha=0.25, linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    ax_current.set_xlabel("Observed score-pose support / frozen expected frames")
    ax_legacy.set_xlabel("Support fraction")
    fig.legend(
        handles=[
            Patch(facecolor="#EEEEEE", edgecolor="#555555", label="frozen expected support"),
            Patch(facecolor=colours["PASS"], label="observed: usability PASS"),
            Patch(facecolor=colours["FAIL"], label="observed: usability FAIL"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, 1.01), ncol=3, frameon=False,
    )
    fig.subplots_adjust(left=0.10, right=0.98, bottom=0.20, top=0.76)
    _save_vector(fig, directory, "figure-02-score-support-v2")
    plt.close(fig)

    # Figure 3: exact camera-grid timeline for each feed.
    fig, ax = plt.subplots(figsize=(7.2, 3.45))
    max_duration = 0.0
    timeline_rows: List[Tuple[float, float, float, Optional[float]]] = []
    for record in records:
        source = sources[record["window_id"]]
        timestamps = _load_camera_timestamps(source.camera_csv, record["feed"]["frame_count"])
        score_start_relative = record["score"]["start_index"] - record["feed"]["start_index"]
        score_end_relative = record["score"]["end_index"] - record["feed"]["start_index"]
        feed_span = (timestamps[-1] - timestamps[0]) / 1e9
        score_start = (timestamps[score_start_relative] - timestamps[0]) / 1e9
        score_end = (timestamps[score_end_relative] - timestamps[0]) / 1e9
        delay = record["usability"]["score_first_output_delay_s"]
        first_output = None if delay is None else score_start + delay
        timeline_rows.append((feed_span, score_start, score_end, first_output))
        max_duration = max(max_duration, feed_span)
    for y, (record, values) in enumerate(zip(records, timeline_rows)):
        feed_span, score_start, score_end, first_output = values
        ax.plot([0, feed_span], [y, y], color="#BDBDBD", linewidth=9, solid_capstyle="butt")
        if score_start > 0:
            ax.plot([0, score_start], [y, y], color="#56B4E9", linewidth=7, solid_capstyle="butt")
        ax.plot([score_start, score_end], [y, y], color="#E69F00", linewidth=7, solid_capstyle="butt")
        if first_output is not None:
            ax.plot(first_output, y, marker="o", markersize=5.5, markerfacecolor="black", markeredgecolor="white", markeredgewidth=0.6)
            ax.text(first_output, y - 0.22, "first +%.3fs" % record["usability"]["score_first_output_delay_s"], ha="center", va="top", fontsize=7)
        else:
            ax.text(score_start + 0.5 * (score_end - score_start), y, "PENDING", ha="center", va="center", fontsize=7, weight="bold")
        if record["synchronization"]["sync_trim_applied"]:
            ax.plot(0, y, marker="v", color="#CC79A7", markersize=6)
            ax.text(0, y + 0.23, "source 0 sync trim", ha="left", va="bottom", fontsize=6.8, color="#7A3D68")
    ax.axhline(2.5, color="black", linestyle="--", linewidth=1.0)
    ax.text(max_duration * 1.005, 2.75, "legacy excluded", ha="right", va="center", fontsize=7)
    ax.set_yticks(range(4), [_short_label(record["window_id"]).replace("\n", " ") for record in records])
    ax.invert_yaxis()
    ax.set_xlim(-0.02 * max_duration, 1.04 * max_duration)
    ax.set_xlabel("Elapsed time from each method feed start (s; camera timestamp grid)")
    ax.grid(axis="x", alpha=0.25, linewidth=0.6)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.tick_params(axis="y", length=0)
    ax.legend(
        handles=[
            Line2D([0], [0], color="#56B4E9", lw=7, label="preroll/history"),
            Line2D([0], [0], color="#E69F00", lw=7, label="score interval"),
            Line2D([0], [0], marker="o", color="black", lw=0, label="first score output"),
            Line2D([0], [0], marker="v", color="#CC79A7", lw=0, label="sync trim"),
        ],
        loc="upper center", bbox_to_anchor=(0.5, 1.17), ncol=4, frameon=False,
    )
    fig.subplots_adjust(top=0.80, bottom=0.18, left=0.22, right=0.98)
    _save_vector(fig, directory, "figure-03-feed-score-timeline-v2")
    plt.close(fig)


def _fmt(value: Any, digits: int = 6) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return ("%%.%df" % digits) % value
    return str(value)


def render_report(bundle: Mapping[str, Any]) -> str:
    records = bundle["rows"]
    evidence_by_window = {
        item["window_id"]: item for item in bundle["input_evidence"]
    }
    summary = bundle["current_protocol_summary"]
    if bundle["analysis_state"] == "PENDING_CURRENT_RESULTS":
        headline = (
            "当前分析仍为 **PENDING**：3 个 current 窗口中 %d 个已有终态、%d 个等待 sealed run_result。"
            "缺失结果没有按失败或零支持处理。"
            % (summary["terminal_count"], summary["pending_count"])
        )
        usable_line = "最终 `usable k/3` 暂不报告；当前只记录已终态窗口，不把 PENDING 计入失败。"
    else:
        headline = "三个 current 窗口均已终态；严格 usability 结果为 **%s**。" % summary["final_usable_k_of_3"]
        usable_line = "分母固定为 3；legacy A02 cold-start 仅作终态上下文，不进入分母。"
    lines = [
        "# HFNet-SLAM 多窗口严格分析 v2",
        "",
        "状态：`%s`" % bundle["analysis_state"],
        "",
        "呈现修订：`%s`（仅修正图 2 annotation 布局；机器结果与门控不变）。"
        % bundle["presentation_revision"],
        "",
        headline,
        "",
        usable_line,
        "",
        "## 逐窗原始 usability",
        "",
        "| role | window | strict status | producer terminal | raw/controller RC | score poses | coverage | longest contiguous | first output delay (s) | score KFs | failure code |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in records:
        usability = record["usability"]
        producer = evidence_by_window[record["window_id"]].get("producer_terminal") or {}
        produced = usability["score_pose_count"]
        expected = record["score"]["expected_frame_count"]
        support = "— / %d" % expected if produced is None else "%d / %d" % (produced, expected)
        lines.append(
            "| %s | `%s` | %s | `%s` | %s/%s | %s | %s | %s | %s | %s | `%s` |"
            % (
                "current" if record["row_role"] == "CURRENT_PROTOCOL_WINDOW" else "legacy (excluded)",
                record["window_id"],
                usability["status"],
                producer.get("status") or "PENDING",
                _fmt(producer.get("raw_returncode"), 0),
                _fmt(producer.get("controller_return_code"), 0),
                support,
                _fmt(usability["score_coverage_fraction"]),
                _fmt(usability["score_longest_contiguous_fraction"]),
                _fmt(usability["score_first_output_delay_s"]),
                _fmt(usability["keyframe_score_count"], 0),
                usability["failure_code"],
            )
        )
    lines.extend([
        "",
        "## 证据边界",
        "",
        "- 统计单元是冻结窗口，current `n=3`；每窗只有一次冻结运行，且窗口异质、开发暴露。",
        "- 不计算显著性检验、置信区间、跨窗 mean±std、逐 pose 推断或平均值 winner。",
        "- accuracy gate 对四行全部关闭：history/support/evaluator 尚未统一；APE/RPE 保持 null。",
        "- 失败行只保留实际观察到的支持；不填 0、Inf、惩罚值，也不进入 accuracy 排名。",
        "- H07 与新 A02 的 source frame 0 裁剪是 shifted-IMU predecessor 安全边界；score 窗未移动，未使用 synthetic/extrapolated IMU。",
        "",
        "## 图件",
        "",
    ])
    if bundle["figures_generated"]:
        lines.extend([
            "- `figure-01-usability-matrix-v2`: 逐门显示 PASS/FAIL，legacy 以分隔列呈现。",
            "- `figure-02-score-support-v2`: 显示 produced/expected 支持，失败保留观测值。",
            "- `figure-03-feed-score-timeline-v2`: 显示 feed、pre-roll、score、sync trim 与 first output。",
        ])
    else:
        lines.append("- 因 current 结果未齐，严格分析工作流暂不生成图；图件状态为 `WITHHELD_PENDING_CURRENT_RESULTS`。")
    lines.extend([
        "",
        "## 当前允许结论",
        "",
        "本 bundle 只回答外部 learned whole-system 在各冻结窗口是否达到 usability 门。它不支持 HFNet 与 AQUA-FE/KLT 的轨迹精度优劣结论。",
        "",
    ])
    return "\n".join(lines)


def _write_csv(path: Path, fieldnames: Sequence[str], records: Sequence[Mapping[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="raise", lineterminator="\n")
        writer.writeheader()
        for record in records:
            writer.writerow(_record_to_flat(record))


def emit_bundle(
    inputs: AnalysisInputs,
    output_dir: Path,
    *,
    require_current_terminal: bool = False,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    fieldnames, records, evidence = build_records(inputs)
    stamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    bundle = build_bundle(records, evidence, stamp)
    if require_current_terminal and bundle["analysis_state"] != "TERMINAL_DESCRIPTIVE_ONLY":
        raise EvidenceError("STRICT_FINAL_BLOCKED_PENDING_CURRENT_RESULTS")
    if output_dir.exists():
        raise EvidenceError("OUTPUT_DIRECTORY_ALREADY_EXISTS:%s" % output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".%s.staging-" % output_dir.name, dir=str(output_dir.parent)))
    try:
        _write_csv(staging / "hfnet_multiwindow_results_final_v2.csv", fieldnames, records)
        (staging / "hfnet_multiwindow_analysis_bundle_v2.json").write_text(
            json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (staging / "hfnet_multiwindow_analysis_report_v2.md").write_text(
            render_report(bundle), encoding="utf-8"
        )
        if bundle["figures_generated"]:
            figures = staging / "figures"
            figures.mkdir()
            generate_figures(records, inputs.sources, figures)
        os.replace(staging, output_dir)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return bundle


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    value.add_argument("--require-current-terminal", action="store_true")
    value.add_argument("--a06-run-result", type=Path)
    value.add_argument("--h07-run-result", type=Path)
    value.add_argument("--a02-run-result", type=Path)
    value.add_argument("--legacy-a02-run-result", type=Path)
    return value


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        inputs = default_inputs(
            a06_run_result=args.a06_run_result,
            h07_run_result=args.h07_run_result,
            a02_run_result=args.a02_run_result,
            legacy_run_result=args.legacy_a02_run_result,
        )
        bundle = emit_bundle(
            inputs,
            args.output_dir,
            require_current_terminal=args.require_current_terminal,
        )
    except EvidenceError as error:
        sys.stderr.write(json.dumps({"status": "BLOCKED", "error": str(error)}, sort_keys=True) + "\n")
        return 2
    sys.stdout.write(json.dumps({
        "status": bundle["analysis_state"],
        "output_dir": str(args.output_dir),
        "current_summary": bundle["current_protocol_summary"],
        "figures_generated": bundle["figures_generated"],
    }, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
