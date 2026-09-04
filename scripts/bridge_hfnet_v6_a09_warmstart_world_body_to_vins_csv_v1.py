#!/usr/bin/env python3
"""Seal an A09 HFNet score crop through two non-evaluating text stages.

This tool is intentionally limited to the already sealed A09 warm-start score
artifact.  It has no ROS, HFNet, VINS, evaluator, or subprocess execution
surface.

Stages
------
``bridge``
    Convert the pinned rows
    ``timestamp_ns tx ty tz qx qy qz qw`` to headerless VINS CSV rows
    ``timestamp_ns,tx,ty,tz,qw,qx,qy,qz``.  Timestamp numeric values and all
    seven pose tokens are preserved; only integral timestamp spelling,
    delimiters, and quaternion column order change.

``canonicalize``
    Revalidate the first-stage output and its canonical receipt, then replace
    only each timestamp token with the exact pinned ``cam0_times`` value at
    source frame ``4000+i``.  All seven first-stage pose tokens remain byte for
    byte identical.  This is source-index spelling, never fitted time sync.

``audit`` performs both transformations in memory and writes only canonical
JSON to stdout.  The two publishing commands use O_EXCL-created temporary
regular files and same-directory hard-link publication.  Existing final
paths, including identical files and dangling symlinks, are never reused or
replaced.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import stat
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


ROOT = Path("/home/ma/AQUA-FE_WS")
TOOL_PATH = ROOT / "scripts/bridge_hfnet_v6_a09_warmstart_world_body_to_vins_csv_v1.py"
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a09_0000_4400_score_4000_4400_warmstart/attempt_001"
)

AUDIT_SCHEMA = "aqua-fe-hfnet-v6-a09-warmstart-bridge-canonicalize-audit-v1"
BRIDGE_RECEIPT_SCHEMA = "aqua-fe-hfnet-v6-a09-warmstart-lossless-bridge-receipt-v1"
CANONICAL_RECEIPT_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-warmstart-source-stamp-canonical-receipt-v1"
)

EXPECTED_ROWS = 401
FEED_ROWS = 4401
SCORE_FIRST_SOURCE_INDEX = 4000
SCORE_LAST_SOURCE_INDEX = 4400
SEALED_FIRST_STAMP_NS = 1_542_888_946_038_630_400
SEALED_LAST_STAMP_NS = 1_542_888_966_034_698_752
SOURCE_FIRST_STAMP_NS = 1_542_888_946_038_630_384
SOURCE_LAST_STAMP_NS = 1_542_888_966_034_698_672
FEED_FIRST_STAMP_NS = 1_542_888_746_071_008_208
FEED_LAST_STAMP_NS = SOURCE_LAST_STAMP_NS
EXPECTED_DELTA_HISTOGRAM_NS = {
    -112: 55,
    -80: 52,
    -48: 47,
    -16: 65,
    16: 51,
    48: 36,
    80: 41,
    112: 54,
}
EXPECTED_BRIDGE_CONTENT = {
    "size_bytes": 42_105,
    "sha256": "f58685b726495f851b5e36b2d5b9d5cbdad9d58f3a251328a617ebda945d3a77",
}
EXPECTED_CANONICAL_CONTENT = {
    "size_bytes": 42_105,
    "sha256": "2b5bd98de228b13c33a79e40b0462d51db57e3280449230d3e1f33f369072d5d",
}


@dataclass(frozen=True)
class AuthorityPin:
    path: str
    size_bytes: int
    sha256: str

    def identity(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


SEALED_PINS: Mapping[str, AuthorityPin] = {
    "score_source": AuthorityPin(
        path=str(ATTEMPT / "result/trajectory_score_4000_4400.txt"),
        size_bytes=44_912,
        sha256="4037e48ad1cdeace41ec8fbd4470debad275237934ccf0b734a670089bfec935",
    ),
    "terminal_freeze": AuthorityPin(
        path=str(
            ROOT
            / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_"
            "terminal_outcome_freeze_v1.json"
        ),
        size_bytes=6_762,
        sha256="0645080a46e0e6110210cc387693c98b23dc0860c853cbef3d2c6c98ce589d69",
    ),
    "execution_lock": AuthorityPin(
        path=str(
            ROOT
            / "papers/hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_"
            "execution_lock_v2.json"
        ),
        size_bytes=5_203,
        sha256="7200df40e0e28eec0a50f2e46efd45d3076c94ea31258105b870904e793f4217",
    ),
    "cam0_times": AuthorityPin(
        path=str(ATTEMPT / "cam0_times_0000_4400.txt"),
        size_bytes=88_020,
        sha256="c8b9bb58e1692ae570cfc855e2069bda734110c2866004093c8eefa4293f16a8",
    ),
}

DEFAULT_AUTHORITY_PATHS: Mapping[str, Path] = {
    name: Path(pin.path) for name, pin in SEALED_PINS.items()
}

CLAIM_BOUNDARY: Mapping[str, Any] = {
    "accuracy_evaluated": False,
    "ape_or_rpe_authorized": False,
    "development_only": True,
    "evaluation_execution_surface": False,
    "fair_head_to_head_authorized": False,
    "formal_paper_claim_authorized": False,
    "hfnet_ros_vins_execution_surface": False,
    "ranking_or_superiority_authorized": False,
    "significance_testing_authorized": False,
}

PUBLICATION_CONTRACT: Mapping[str, Any] = {
    "canonical_json_receipt": True,
    "directory_fsync_after_each_final_link": True,
    "existing_identical_target_reused": False,
    "file_fsync_before_final_link": True,
    "final_publication": "SAME_DIRECTORY_HARD_LINK_NO_REPLACE",
    "output_then_receipt": True,
    "receipt_failure_rollback": "UNLINK_ONLY_EXACT_OWNED_OUTPUT_INODE",
    "requested_file_mode": "0444",
    "temporary_file_creation": "O_CREAT|O_EXCL|O_NOFOLLOW",
}


class BridgeError(RuntimeError):
    """One frozen identity, semantic invariant, or publication gate failed."""


@dataclass(frozen=True)
class SourceRow:
    sealed_stamp_ns: int
    sealed_stamp_token: str
    source_pose_tokens: Tuple[str, str, str, str, str, str, str]
    bridge_pose_tokens: Tuple[str, str, str, str, str, str, str]


@dataclass(frozen=True)
class BridgeRow:
    stamp_ns: int
    stamp_token: str
    pose_tokens: Tuple[str, str, str, str, str, str, str]


@dataclass(frozen=True)
class PreparedEvidence:
    authority_identities: Mapping[str, Mapping[str, Any]]
    authority_checks: Mapping[str, Any]
    source_rows: Tuple[SourceRow, ...]
    score_source_times_ns: Tuple[int, ...]
    bridge_payload: bytes
    canonical_payload: bytes
    delta_histogram_ns: Mapping[int, int]
    bridge_pose_stream_sha256: str


@dataclass(frozen=True)
class OwnedTemporary:
    path: Path
    device: int
    inode: int


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BridgeError(code)


def canonical_json(value: Any) -> bytes:
    """Return the repository's deterministic, sorted receipt representation."""

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


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def normalized_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def identity_for_payload(path: Path, payload: bytes) -> Dict[str, Any]:
    return {
        "path": str(normalized_absolute(path)),
        "size_bytes": len(payload),
        "sha256": sha256_bytes(payload),
    }


def _assert_no_symlink_components(path: Path) -> None:
    absolute = normalized_absolute(path)
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError as error:
            raise BridgeError(f"PATH_COMPONENT_MISSING:{current}") from error
        if stat.S_ISLNK(info.st_mode):
            raise BridgeError(f"SYMLINK_COMPONENT_FORBIDDEN:{current}")


def read_regular(path: Path) -> Tuple[bytes, Dict[str, Any]]:
    absolute = normalized_absolute(path)
    _assert_no_symlink_components(absolute)
    descriptor = os.open(
        absolute,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise BridgeError(f"NOT_REGULAR:{absolute}")
        chunks: List[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
        stable_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        )
        stable_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        )
        if stable_before != stable_after:
            raise BridgeError(f"CHANGED_WHILE_READING:{absolute}")
    finally:
        os.close(descriptor)
    return payload, identity_for_payload(absolute, payload)


def parse_json_object(payload: bytes, label: str) -> Mapping[str, Any]:
    def reject_constant(value: str) -> None:
        raise BridgeError(f"{label}_NONFINITE_JSON:{value}")

    try:
        value = json.loads(
            payload.decode("utf-8"),
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BridgeError(f"{label}_INVALID_JSON") from error
    if not isinstance(value, dict):
        raise BridgeError(f"{label}_NOT_OBJECT")
    return value


def tool_identity() -> Dict[str, Any]:
    actual_path = normalized_absolute(Path(__file__))
    require(actual_path == TOOL_PATH, "TOOL_PATH_NOT_CANONICAL")
    _payload, identity = read_regular(actual_path)
    return identity


def validate_terminal_freeze_value(
    value: Mapping[str, Any], pins: Mapping[str, AuthorityPin]
) -> Mapping[str, Any]:
    require(
        value.get("schema_version")
        == "aqua-fe-hfnet-v6-a09-warmstart-terminal-outcome-freeze-v1",
        "TERMINAL_FREEZE_SCHEMA",
    )
    require(value.get("status") == "SEALED_TERMINAL_PASS_NO_RETRY", "TERMINAL_FREEZE_STATUS")
    require(
        value.get("scientific_role")
        == "DEVELOPMENT_ONLY_EXTERNAL_LEARNED_WHOLE_SYSTEM_RUNABILITY_ON_PRIOR_KLT_POSITIVE_WINDOW",
        "TERMINAL_FREEZE_ROLE",
    )
    require(value.get("execution_lock") == pins["execution_lock"].identity(), "TERMINAL_LOCK_BINDING")
    selection = value.get("selection")
    require(isinstance(selection, dict), "TERMINAL_SELECTION_TYPE")
    require(selection.get("feed_source_frame_indices_inclusive") == [0, 4400], "TERMINAL_FEED_RANGE")
    require(selection.get("feed_camera_count") == FEED_ROWS, "TERMINAL_FEED_COUNT")
    require(
        selection.get("score_source_frame_indices_inclusive") == [4000, 4400],
        "TERMINAL_SCORE_RANGE",
    )
    require(selection.get("score_camera_count") == EXPECTED_ROWS, "TERMINAL_SCORE_COUNT")
    require(selection.get("development_result_conditioned_selection") is True, "TERMINAL_SELECTION_ROLE")
    require(selection.get("held_out_confirmatory_claim_permitted") is False, "TERMINAL_HELDOUT_BOUNDARY")
    score = value.get("score_adjudication")
    require(isinstance(score, dict), "TERMINAL_SCORE_TYPE")
    expected_score = {
        "passed": True,
        "pose_count": EXPECTED_ROWS,
        "expected_pose_count": EXPECTED_ROWS,
        "first_source_frame_index": SCORE_FIRST_SOURCE_INDEX,
        "last_source_frame_index": SCORE_LAST_SOURCE_INDEX,
        "exact_contiguous_coverage": True,
    }
    for key, expected in expected_score.items():
        require(score.get(key) == expected, f"TERMINAL_SCORE_FIELD:{key}")
    history = value.get("history_events")
    require(isinstance(history, dict), "TERMINAL_HISTORY_TYPE")
    require(history.get("score_window_init_count") == 0, "TERMINAL_SCORE_INIT_COUNT")
    require(history.get("score_window_reset_count") == 0, "TERMINAL_SCORE_RESET_COUNT")
    require(history.get("all_resets_before_score_window") is True, "TERMINAL_RESET_HISTORY")
    require(history.get("reset_parse_complete") is True, "TERMINAL_RESET_PARSE")
    require(history.get("ambiguous_or_unresolved_reset_events") == [], "TERMINAL_RESET_AMBIGUITY")
    artifacts = value.get("artifacts")
    require(isinstance(artifacts, dict), "TERMINAL_ARTIFACTS_TYPE")
    require(
        artifacts.get("score_trajectory_crop") == pins["score_source"].identity(),
        "TERMINAL_SCORE_SOURCE_BINDING",
    )
    execution = value.get("execution")
    require(isinstance(execution, dict), "TERMINAL_EXECUTION_TYPE")
    execution_expected = {
        "official_hfnet_elf_popen_invocations": 1,
        "raw_returncode": 0,
        "timed_out": False,
        "child_reaped": True,
        "retry_performed": False,
        "retry_permitted": False,
        "watchdog_triggered": False,
        "post_audit_process_residue": False,
    }
    for key, expected in execution_expected.items():
        require(execution.get(key) == expected, f"TERMINAL_EXECUTION_FIELD:{key}")
    claim = value.get("claim_boundary")
    require(isinstance(claim, dict), "TERMINAL_CLAIM_TYPE")
    claim_expected = {
        "development_only": True,
        "runability_supported": True,
        "accuracy_evaluated": False,
        "ape_or_rpe_authorized": False,
        "fair_head_to_head": False,
        "ranking_or_superiority_authorized": False,
        "significance_testing_authorized": False,
        "formal_paper_claim_authorized": False,
    }
    require(claim == claim_expected, "TERMINAL_CLAIM_BOUNDARY")
    independent = value.get("independent_audit")
    require(isinstance(independent, dict), "TERMINAL_INDEPENDENT_AUDIT_TYPE")
    require(independent.get("decision") == "GO", "TERMINAL_INDEPENDENT_AUDIT")
    require(
        independent.get("score_mapping_reconstructed_from_raw_timestamps") is True,
        "TERMINAL_SCORE_MAPPING_AUDIT",
    )
    policy = value.get("terminal_policy")
    require(
        policy
        == {
            "attempt_namespace_reusable": False,
            "retry_authorized": False,
            "post_hoc_gate_relaxation_authorized": False,
        },
        "TERMINAL_POLICY",
    )
    return {
        "schema_version": value["schema_version"],
        "status": value["status"],
        "score_exact_contiguous_rows": EXPECTED_ROWS,
        "accuracy_authorized": False,
    }


def validate_execution_lock_value(value: Mapping[str, Any]) -> Mapping[str, Any]:
    require(
        value.get("schema_version") == "aqua-fe-hfnet-v6-a09-warmstart-execution-lock-v2",
        "EXECUTION_LOCK_SCHEMA",
    )
    require(
        value.get("status")
        == "AUTHORIZED_EXACTLY_ONE_HFNET_ELF_START_ATTEMPT_001_NO_RETRY_V2",
        "EXECUTION_LOCK_STATUS",
    )
    claims = value.get("claims")
    require(isinstance(claims, dict), "EXECUTION_LOCK_CLAIMS_TYPE")
    claims_expected = {
        "accuracy_comparison_authorized": False,
        "execution_authorized": True,
        "hfnet_started_at_lock_time": False,
        "process_claim_created_at_lock_time": False,
        "scientific_comparison_produced": False,
        "trajectory_produced_at_lock_time": False,
        "v1_lock_must_never_be_invoked": True,
    }
    require(claims == claims_expected, "EXECUTION_LOCK_CLAIMS")
    consumption = value.get("claim_and_consumption_contract")
    require(isinstance(consumption, dict), "EXECUTION_LOCK_CONSUMPTION_TYPE")
    require(consumption.get("maximum_hfnet_elf_starts") == 1, "EXECUTION_LOCK_MAX_STARTS")
    require(consumption.get("maximum_supervisor_invocations") == 1, "EXECUTION_LOCK_MAX_INVOCATIONS")
    require(consumption.get("retry_permitted") is False, "EXECUTION_LOCK_RETRY")
    scientific = value.get("scientific_boundary")
    require(isinstance(scientific, dict), "EXECUTION_LOCK_SCIENTIFIC_TYPE")
    require(scientific.get("development_result_conditioned") is True, "EXECUTION_LOCK_SELECTION")
    require(scientific.get("failure_accuracy_state") == "NA_NOT_ZERO", "EXECUTION_LOCK_FAILURE_STATE")
    terminal = value.get("terminal_contract")
    require(isinstance(terminal, dict), "EXECUTION_LOCK_TERMINAL_TYPE")
    require(terminal.get("crop_only_after_all_runability_gates_pass") is True, "EXECUTION_LOCK_CROP_GATE")
    require(terminal.get("result_and_crop_publication") == "O_EXCL_ATOMIC", "EXECUTION_LOCK_PUBLICATION")
    return {
        "schema_version": value["schema_version"],
        "status": value["status"],
        "historical_execution_authority_only": True,
        "new_execution_authorized_by_this_tool": False,
    }


def parse_cam0_times(payload: bytes) -> Tuple[int, ...]:
    try:
        text = payload.decode("ascii")
    except UnicodeError as error:
        raise BridgeError("CAM0_TIMES_NOT_ASCII") from error
    require(text.endswith("\n"), "CAM0_TIMES_FINAL_NEWLINE")
    require("\r" not in text, "CAM0_TIMES_CR_FORBIDDEN")
    lines = text.splitlines()
    require(len(lines) == FEED_ROWS, f"CAM0_TIMES_ROW_COUNT:{len(lines)}")
    stamps: List[int] = []
    for index, token in enumerate(lines):
        require(token != "" and token == token.strip(), f"CAM0_TIMES_TOKEN:{index}")
        try:
            stamp = int(token)
        except ValueError as error:
            raise BridgeError(f"CAM0_TIMES_PARSE:{index}") from error
        require(str(stamp) == token and stamp >= 0, f"CAM0_TIMES_CANONICAL_INTEGER:{index}")
        stamps.append(stamp)
    require(all(right > left for left, right in zip(stamps, stamps[1:])), "CAM0_TIMES_NOT_STRICT")
    require(stamps[0] == FEED_FIRST_STAMP_NS, "CAM0_TIMES_FEED_FIRST")
    require(stamps[-1] == FEED_LAST_STAMP_NS, "CAM0_TIMES_FEED_LAST")
    require(stamps[SCORE_FIRST_SOURCE_INDEX] == SOURCE_FIRST_STAMP_NS, "CAM0_TIMES_SCORE_FIRST")
    require(stamps[SCORE_LAST_SOURCE_INDEX] == SOURCE_LAST_STAMP_NS, "CAM0_TIMES_SCORE_LAST")
    return tuple(stamps)


def _finite_pose_tokens(tokens: Sequence[str], quaternion_wxyz: bool, label: str) -> None:
    require(len(tokens) == 7, f"{label}_POSE_TOKEN_COUNT")
    try:
        values = [float(token) for token in tokens]
    except ValueError as error:
        raise BridgeError(f"{label}_POSE_PARSE") from error
    require(all(math.isfinite(value) for value in values), f"{label}_POSE_NONFINITE")
    quaternion = values[3:7]
    norm = math.sqrt(sum(value * value for value in quaternion))
    require(0.99 <= norm <= 1.01, f"{label}_QUATERNION_NORM")
    if not quaternion_wxyz:
        # The numeric norm is order independent.  This branch documents that
        # source tokens 3..6 are xyzw while bridge tokens 3..6 are wxyz.
        require(len(quaternion) == 4, f"{label}_QUATERNION_COUNT")


def parse_score_source(payload: bytes) -> Tuple[SourceRow, ...]:
    try:
        text = payload.decode("ascii")
    except UnicodeError as error:
        raise BridgeError("SCORE_SOURCE_NOT_ASCII") from error
    require(text.endswith("\n"), "SCORE_SOURCE_FINAL_NEWLINE")
    require("\r" not in text, "SCORE_SOURCE_CR_FORBIDDEN")
    lines = text.splitlines()
    rows: List[SourceRow] = []
    previous: Optional[int] = None
    for index, line in enumerate(lines):
        require(line.strip() != "", f"SCORE_SOURCE_BLANK_ROW:{index}")
        fields = line.split()
        require(len(fields) == 8, f"SCORE_SOURCE_FIELD_COUNT:{index}")
        try:
            decimal_stamp = Decimal(fields[0])
        except InvalidOperation as error:
            raise BridgeError(f"SCORE_SOURCE_TIMESTAMP_PARSE:{index}") from error
        require(
            decimal_stamp.is_finite()
            and decimal_stamp == decimal_stamp.to_integral_value(),
            f"SCORE_SOURCE_TIMESTAMP_NOT_INTEGER_NS:{index}",
        )
        stamp = int(decimal_stamp)
        if previous is not None:
            require(stamp > previous, f"SCORE_SOURCE_TIMESTAMP_NOT_STRICT:{index}")
        previous = stamp
        source_pose = tuple(fields[1:8])
        _finite_pose_tokens(source_pose, False, f"SCORE_SOURCE_ROW_{index}")
        bridge_pose = (
            source_pose[0],
            source_pose[1],
            source_pose[2],
            source_pose[6],
            source_pose[3],
            source_pose[4],
            source_pose[5],
        )
        reconstructed = (
            bridge_pose[0],
            bridge_pose[1],
            bridge_pose[2],
            bridge_pose[4],
            bridge_pose[5],
            bridge_pose[6],
            bridge_pose[3],
        )
        require(reconstructed == source_pose, f"SCORE_SOURCE_POSE_TOKEN_REORDER:{index}")
        rows.append(
            SourceRow(
                sealed_stamp_ns=stamp,
                sealed_stamp_token=fields[0],
                source_pose_tokens=source_pose,  # type: ignore[arg-type]
                bridge_pose_tokens=bridge_pose,
            )
        )
    return tuple(rows)


def pose_stream_sha256(rows: Iterable[Sequence[str]]) -> str:
    payload = ("\n".join(",".join(tokens) for tokens in rows) + "\n").encode("ascii")
    return sha256_bytes(payload)


def build_bridge_payload(rows: Sequence[SourceRow]) -> bytes:
    lines = [
        ",".join((str(row.sealed_stamp_ns),) + row.bridge_pose_tokens)
        for row in rows
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def parse_bridge_payload(payload: bytes) -> Tuple[BridgeRow, ...]:
    try:
        text = payload.decode("ascii")
    except UnicodeError as error:
        raise BridgeError("BRIDGE_NOT_ASCII") from error
    require(text.endswith("\n"), "BRIDGE_FINAL_NEWLINE")
    require("\r" not in text, "BRIDGE_CR_FORBIDDEN")
    rows: List[BridgeRow] = []
    previous: Optional[int] = None
    for index, line in enumerate(text.splitlines()):
        fields = line.split(",")
        require(len(fields) == 8 and line == ",".join(fields), f"BRIDGE_FIELD_COUNT:{index}")
        require(all(field != "" for field in fields), f"BRIDGE_EMPTY_FIELD:{index}")
        try:
            stamp = int(fields[0])
        except ValueError as error:
            raise BridgeError(f"BRIDGE_TIMESTAMP_PARSE:{index}") from error
        require(str(stamp) == fields[0] and stamp >= 0, f"BRIDGE_TIMESTAMP_CANONICAL:{index}")
        if previous is not None:
            require(stamp > previous, f"BRIDGE_TIMESTAMP_NOT_STRICT:{index}")
        previous = stamp
        pose_tokens = tuple(fields[1:8])
        _finite_pose_tokens(pose_tokens, True, f"BRIDGE_ROW_{index}")
        rows.append(
            BridgeRow(
                stamp_ns=stamp,
                stamp_token=fields[0],
                pose_tokens=pose_tokens,  # type: ignore[arg-type]
            )
        )
    return tuple(rows)


def build_canonical_payload(
    bridge_rows: Sequence[BridgeRow], source_times_ns: Sequence[int]
) -> bytes:
    require(len(bridge_rows) == len(source_times_ns), "CANONICAL_ROW_TIME_COUNT")
    lines = [
        ",".join((str(stamp),) + row.pose_tokens)
        for stamp, row in zip(source_times_ns, bridge_rows)
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def _require_content(payload: bytes, expected: Mapping[str, Any], label: str) -> None:
    actual = {"size_bytes": len(payload), "sha256": sha256_bytes(payload)}
    require(actual == dict(expected), f"{label}_CONTENT_IDENTITY")


def prepare_evidence(
    authority_paths: Mapping[str, Path] = DEFAULT_AUTHORITY_PATHS,
    pins: Mapping[str, AuthorityPin] = SEALED_PINS,
) -> PreparedEvidence:
    require(set(authority_paths) == set(pins), "AUTHORITY_KEY_SET")
    payloads: Dict[str, bytes] = {}
    identities: Dict[str, Mapping[str, Any]] = {}
    for name in ("score_source", "terminal_freeze", "execution_lock", "cam0_times"):
        pin = pins[name]
        path = normalized_absolute(authority_paths[name])
        require(str(path) == pin.path, f"AUTHORITY_PATH_NOT_ALLOWLISTED:{name}")
        payload, identity = read_regular(path)
        require(identity == pin.identity(), f"AUTHORITY_IDENTITY_MISMATCH:{name}")
        payloads[name] = payload
        identities[name] = identity

    terminal_value = parse_json_object(payloads["terminal_freeze"], "TERMINAL_FREEZE")
    lock_value = parse_json_object(payloads["execution_lock"], "EXECUTION_LOCK")
    terminal_check = validate_terminal_freeze_value(terminal_value, pins)
    lock_check = validate_execution_lock_value(lock_value)
    cam0_times = parse_cam0_times(payloads["cam0_times"])
    source_rows = parse_score_source(payloads["score_source"])
    require(len(source_rows) == EXPECTED_ROWS, f"SCORE_SOURCE_ROW_COUNT:{len(source_rows)}")
    require(source_rows[0].sealed_stamp_ns == SEALED_FIRST_STAMP_NS, "SCORE_SOURCE_FIRST_STAMP")
    require(source_rows[-1].sealed_stamp_ns == SEALED_LAST_STAMP_NS, "SCORE_SOURCE_LAST_STAMP")
    score_times = cam0_times[SCORE_FIRST_SOURCE_INDEX : SCORE_LAST_SOURCE_INDEX + 1]
    require(len(score_times) == EXPECTED_ROWS, "SCORE_TIME_SLICE_COUNT")

    deltas = [
        row.sealed_stamp_ns - source_stamp
        for row, source_stamp in zip(source_rows, score_times)
    ]
    histogram = dict(sorted(Counter(deltas).items()))
    require(histogram == EXPECTED_DELTA_HISTOGRAM_NS, "SOURCE_STAMP_DELTA_HISTOGRAM")
    require(max(abs(delta) for delta in deltas) == 112, "SOURCE_STAMP_MAX_ABS_DELTA")

    bridge_payload = build_bridge_payload(source_rows)
    _require_content(bridge_payload, EXPECTED_BRIDGE_CONTENT, "BRIDGE")
    bridge_rows = parse_bridge_payload(bridge_payload)
    require(len(bridge_rows) == EXPECTED_ROWS, "BRIDGE_ROW_COUNT")
    for index, (source_row, bridge_row) in enumerate(zip(source_rows, bridge_rows)):
        require(
            source_row.bridge_pose_tokens == bridge_row.pose_tokens,
            f"BRIDGE_POSE_TOKEN_DRIFT:{index}",
        )
        require(source_row.sealed_stamp_ns == bridge_row.stamp_ns, f"BRIDGE_STAMP_DRIFT:{index}")

    canonical_payload = build_canonical_payload(bridge_rows, score_times)
    _require_content(canonical_payload, EXPECTED_CANONICAL_CONTENT, "CANONICAL")
    canonical_rows = parse_bridge_payload(canonical_payload)
    for index, (bridge_row, canonical_row, source_stamp) in enumerate(
        zip(bridge_rows, canonical_rows, score_times)
    ):
        require(bridge_row.pose_tokens == canonical_row.pose_tokens, f"CANONICAL_POSE_TOKEN_DRIFT:{index}")
        require(canonical_row.stamp_ns == source_stamp, f"CANONICAL_STAMP_DRIFT:{index}")

    stream_hash = pose_stream_sha256(row.bridge_pose_tokens for row in source_rows)
    require(
        stream_hash == pose_stream_sha256(row.pose_tokens for row in canonical_rows),
        "CANONICAL_POSE_STREAM_HASH",
    )
    return PreparedEvidence(
        authority_identities=identities,
        authority_checks={
            "terminal_freeze": terminal_check,
            "execution_lock": lock_check,
            "cam0_times": {
                "feed_rows": len(cam0_times),
                "feed_first_stamp_ns": cam0_times[0],
                "feed_last_stamp_ns": cam0_times[-1],
                "score_source_indices_inclusive": [4000, 4400],
                "score_first_stamp_ns": score_times[0],
                "score_last_stamp_ns": score_times[-1],
            },
        },
        source_rows=source_rows,
        score_source_times_ns=tuple(score_times),
        bridge_payload=bridge_payload,
        canonical_payload=canonical_payload,
        delta_histogram_ns=histogram,
        bridge_pose_stream_sha256=stream_hash,
    )


def audit_record(prepared: PreparedEvidence) -> Dict[str, Any]:
    source_timestamp_spelling_changes = sum(
        row.sealed_stamp_token != str(row.sealed_stamp_ns) for row in prepared.source_rows
    )
    canonical_timestamp_changes = sum(
        row.sealed_stamp_ns != source_stamp
        for row, source_stamp in zip(prepared.source_rows, prepared.score_source_times_ns)
    )
    return {
        "schema_version": AUDIT_SCHEMA,
        "status": "AUDIT_PASS_NO_WRITE",
        "tool": tool_identity(),
        "authorities": dict(prepared.authority_identities),
        "authority_checks": dict(prepared.authority_checks),
        "row_count": EXPECTED_ROWS,
        "source_indices_inclusive": [4000, 4400],
        "lossless_bridge": {
            **EXPECTED_BRIDGE_CONTENT,
            "first_stamp_ns": SEALED_FIRST_STAMP_NS,
            "last_stamp_ns": SEALED_LAST_STAMP_NS,
            "timestamp_numeric_values_changed": False,
            "timestamp_spelling_changes": source_timestamp_spelling_changes,
            "pose_tokens_preserved_with_only_quaternion_reorder": True,
            "bridge_pose_stream_sha256": prepared.bridge_pose_stream_sha256,
        },
        "source_stamp_canonicalization": {
            **EXPECTED_CANONICAL_CONTENT,
            "first_stamp_ns": SOURCE_FIRST_STAMP_NS,
            "last_stamp_ns": SOURCE_LAST_STAMP_NS,
            "timestamp_values_changed": canonical_timestamp_changes,
            "maximum_absolute_delta_ns": 112,
            "complete_sealed_minus_source_delta_histogram_ns": {
                str(key): value for key, value in prepared.delta_histogram_ns.items()
            },
            "seven_bridge_pose_tokens_unchanged_byte_for_byte": True,
            "bridge_pose_stream_sha256": prepared.bridge_pose_stream_sha256,
            "semantics": "source-index timestamp replacement only; no fitted synchronization",
        },
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def stage1_receipt(
    prepared: PreparedEvidence, output_identity: Mapping[str, Any]
) -> Dict[str, Any]:
    return {
        "schema_version": BRIDGE_RECEIPT_SCHEMA,
        "status": "PASS_SEALED_A09_HFNET_LOSSLESS_COLUMN_BRIDGE",
        "stage": "LOSSLESS_COLUMN_BRIDGE",
        "scientific_role": "FORMAT_CONVERSION_ONLY_NO_EVALUATION",
        "tool": tool_identity(),
        "authorities": dict(prepared.authority_identities),
        "authority_checks": dict(prepared.authority_checks),
        "input": prepared.authority_identities["score_source"],
        "output": dict(output_identity),
        "row_count": EXPECTED_ROWS,
        "source_indices_inclusive": [4000, 4400],
        "timestamp_contract": {
            "input_first_ns": SEALED_FIRST_STAMP_NS,
            "input_last_ns": SEALED_LAST_STAMP_NS,
            "numeric_value_changed": False,
            "integral_decimal_spelling_canonicalized": True,
            "fitted_scale_offset_or_snapping_applied": False,
        },
        "pose_token_contract": {
            "input_columns": ["tx", "ty", "tz", "qx", "qy", "qz", "qw"],
            "output_columns": ["tx", "ty", "tz", "qw", "qx", "qy", "qz"],
            "seven_tokens_preserved_byte_for_byte": True,
            "only_quaternion_column_order_changed": True,
            "output_pose_stream_sha256": prepared.bridge_pose_stream_sha256,
        },
        "semantics": {
            "input_pose": "world_T_body",
            "output_pose": "world_T_body",
            "pose_inversion_or_transform_applied": False,
            "extrinsic_composition_applied": False,
            "interpolation_or_resampling_applied": False,
            "alignment_or_scale_applied": False,
        },
        "publication_contract": dict(PUBLICATION_CONTRACT),
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def stage2_receipt(
    prepared: PreparedEvidence,
    bridge_identity: Mapping[str, Any],
    bridge_receipt_identity: Mapping[str, Any],
    output_identity: Mapping[str, Any],
) -> Dict[str, Any]:
    return {
        "schema_version": CANONICAL_RECEIPT_SCHEMA,
        "status": "PASS_SEALED_A09_HFNET_SOURCE_STAMP_CANONICALIZATION",
        "stage": "SOURCE_INDEX_TIMESTAMP_CANONICALIZATION",
        "scientific_role": "TIMESTAMP_SPELLING_ONLY_NO_EVALUATION",
        "tool": tool_identity(),
        "authorities": dict(prepared.authority_identities),
        "authority_checks": dict(prepared.authority_checks),
        "upstream_bridge": dict(bridge_identity),
        "upstream_bridge_receipt": dict(bridge_receipt_identity),
        "output": dict(output_identity),
        "row_count": EXPECTED_ROWS,
        "source_indices_inclusive": [4000, 4400],
        "timestamp_contract": {
            "sealed_first_stamp_ns": SEALED_FIRST_STAMP_NS,
            "sealed_last_stamp_ns": SEALED_LAST_STAMP_NS,
            "canonical_first_stamp_ns": SOURCE_FIRST_STAMP_NS,
            "canonical_last_stamp_ns": SOURCE_LAST_STAMP_NS,
            "source_mapping": "cam0_times_0000_4400[source_index=4000+i]",
            "timestamp_values_changed": EXPECTED_ROWS,
            "maximum_absolute_delta_ns": 112,
            "complete_sealed_minus_source_delta_histogram_ns": {
                str(key): value for key, value in prepared.delta_histogram_ns.items()
            },
            "fitted_scale_offset_or_snapping_applied": False,
        },
        "pose_token_contract": {
            "columns": ["tx", "ty", "tz", "qw", "qx", "qy", "qz"],
            "seven_upstream_tokens_unchanged_byte_for_byte": True,
            "upstream_and_output_pose_stream_sha256": prepared.bridge_pose_stream_sha256,
        },
        "semantics": {
            "pose": "world_T_body",
            "source_index_timestamp_replacement_only": True,
            "pose_inversion_or_transform_applied": False,
            "extrinsic_composition_applied": False,
            "interpolation_or_resampling_applied": False,
            "alignment_or_scale_applied": False,
        },
        "publication_contract": dict(PUBLICATION_CONTRACT),
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("zero-length write")
        offset += written


def _path_exists_lstat(path: Path) -> bool:
    try:
        os.lstat(path)
    except FileNotFoundError:
        return False
    return True


def _validate_publish_paths(output: Path, receipt: Path) -> Tuple[Path, Path]:
    output = normalized_absolute(output)
    receipt = normalized_absolute(receipt)
    require(output != receipt, "OUTPUT_RECEIPT_PATH_COLLISION")
    require(output.parent == receipt.parent, "OUTPUT_RECEIPT_PARENT_MISMATCH")
    _assert_no_symlink_components(output.parent)
    parent_info = os.lstat(output.parent)
    require(stat.S_ISDIR(parent_info.st_mode), "OUTPUT_PARENT_NOT_DIRECTORY")
    for label, path in (("OUTPUT", output), ("RECEIPT", receipt)):
        require(not _path_exists_lstat(path), f"{label}_ALREADY_EXISTS")
    authority_paths = {pin.path for pin in SEALED_PINS.values()}
    require(str(output) not in authority_paths, "OUTPUT_COLLIDES_WITH_AUTHORITY")
    require(str(receipt) not in authority_paths, "RECEIPT_COLLIDES_WITH_AUTHORITY")
    return output, receipt


def _create_owned_temporary(parent: Path, stem: str, payload: bytes) -> OwnedTemporary:
    temporary = parent / f".{stem}.tmp.{os.getpid()}.{secrets.token_hex(12)}"
    descriptor = os.open(
        temporary,
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | os.O_CLOEXEC
        | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        _write_all(descriptor, payload)
        os.fchmod(descriptor, 0o444)
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode), "TEMPORARY_NOT_REGULAR")
    finally:
        os.close(descriptor)
    return OwnedTemporary(temporary, info.st_dev, info.st_ino)


def _unlink_if_owned(path: Path, owned: OwnedTemporary) -> bool:
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return True
    if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino) != (
        owned.device,
        owned.inode,
    ):
        return False
    os.unlink(path)
    return True


@contextmanager
def _blocked_commit_signals() -> Iterable[None]:
    signals = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def publish_output_and_receipt(
    output: Path,
    output_payload: bytes,
    receipt: Path,
    receipt_payload: bytes,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Publish a two-file bundle without replacing or adopting any path."""

    output, receipt = _validate_publish_paths(output, receipt)
    output_temp: Optional[OwnedTemporary] = None
    receipt_temp: Optional[OwnedTemporary] = None
    output_linked = False
    receipt_linked = False
    with _blocked_commit_signals():
        try:
            output_temp = _create_owned_temporary(output.parent, output.name, output_payload)
            receipt_temp = _create_owned_temporary(receipt.parent, receipt.name, receipt_payload)
            try:
                os.link(output_temp.path, output, follow_symlinks=False)
            except FileExistsError as error:
                raise BridgeError("OUTPUT_RACE_ALREADY_EXISTS") from error
            output_linked = True
            _fsync_directory(output.parent)
            try:
                os.link(receipt_temp.path, receipt, follow_symlinks=False)
            except FileExistsError as error:
                raise BridgeError("RECEIPT_RACE_ALREADY_EXISTS") from error
            receipt_linked = True
            _fsync_directory(receipt.parent)

            actual_output_payload, output_identity = read_regular(output)
            actual_receipt_payload, receipt_identity = read_regular(receipt)
            require(actual_output_payload == output_payload, "PUBLISHED_OUTPUT_BYTES_CHANGED")
            require(actual_receipt_payload == receipt_payload, "PUBLISHED_RECEIPT_BYTES_CHANGED")
        except BaseException:
            rollback_ok = True
            if receipt_linked and receipt_temp is not None:
                rollback_ok = _unlink_if_owned(receipt, receipt_temp) and rollback_ok
            if output_linked and output_temp is not None:
                rollback_ok = _unlink_if_owned(output, output_temp) and rollback_ok
            _fsync_directory(output.parent)
            if not rollback_ok:
                raise BridgeError("PUBLICATION_FAILED_AND_OWNED_ROLLBACK_INCOMPLETE")
            raise
        finally:
            for temporary in (receipt_temp, output_temp):
                if temporary is None:
                    continue
                try:
                    os.unlink(temporary.path)
                except FileNotFoundError:
                    pass
            _fsync_directory(output.parent)
    return output_identity, receipt_identity


def read_canonical_receipt(path: Path, label: str) -> Tuple[Mapping[str, Any], Dict[str, Any]]:
    payload, identity = read_regular(path)
    value = parse_json_object(payload, label)
    require(payload == canonical_json(value), f"{label}_NOT_CANONICAL_JSON")
    return value, identity


def validate_stage1_bridge(
    prepared: PreparedEvidence,
    bridge_path: Path,
    bridge_receipt_path: Path,
) -> Tuple[Tuple[BridgeRow, ...], Dict[str, Any], Dict[str, Any]]:
    bridge_payload, bridge_identity = read_regular(bridge_path)
    _require_content(bridge_payload, EXPECTED_BRIDGE_CONTENT, "UPSTREAM_BRIDGE")
    rows = parse_bridge_payload(bridge_payload)
    require(len(rows) == EXPECTED_ROWS, "UPSTREAM_BRIDGE_ROW_COUNT")
    for index, (source_row, bridge_row) in enumerate(zip(prepared.source_rows, rows)):
        require(source_row.sealed_stamp_ns == bridge_row.stamp_ns, f"UPSTREAM_BRIDGE_STAMP:{index}")
        require(source_row.bridge_pose_tokens == bridge_row.pose_tokens, f"UPSTREAM_BRIDGE_POSE:{index}")
    receipt_value, receipt_identity = read_canonical_receipt(
        bridge_receipt_path, "UPSTREAM_BRIDGE_RECEIPT"
    )
    expected_receipt = stage1_receipt(prepared, bridge_identity)
    require(receipt_value == expected_receipt, "UPSTREAM_BRIDGE_RECEIPT_CONTRACT")
    return rows, bridge_identity, receipt_identity


def bridge_stage(output: Path, receipt: Optional[Path] = None) -> Dict[str, Any]:
    prepared = prepare_evidence()
    output = normalized_absolute(output)
    receipt = normalized_absolute(receipt or Path(str(output) + ".receipt.json"))
    expected_output = identity_for_payload(output, prepared.bridge_payload)
    record = stage1_receipt(prepared, expected_output)
    output_identity, receipt_identity = publish_output_and_receipt(
        output,
        prepared.bridge_payload,
        receipt,
        canonical_json(record),
    )
    require(output_identity == expected_output, "BRIDGE_POSTCOMMIT_IDENTITY")
    actual_record, actual_receipt_identity = read_canonical_receipt(receipt, "BRIDGE_RECEIPT")
    require(actual_record == record, "BRIDGE_RECEIPT_POSTCOMMIT_CONTRACT")
    require(actual_receipt_identity == receipt_identity, "BRIDGE_RECEIPT_POSTCOMMIT_IDENTITY")
    return {
        "status": record["status"],
        "stage": record["stage"],
        "output": output_identity,
        "receipt": receipt_identity,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def canonicalize_stage(
    bridge_path: Path,
    bridge_receipt_path: Path,
    output: Path,
    receipt: Optional[Path] = None,
) -> Dict[str, Any]:
    prepared = prepare_evidence()
    bridge_rows, bridge_identity, bridge_receipt_identity = validate_stage1_bridge(
        prepared,
        bridge_path,
        bridge_receipt_path,
    )
    canonical_payload = build_canonical_payload(
        bridge_rows,
        prepared.score_source_times_ns,
    )
    require(canonical_payload == prepared.canonical_payload, "CANONICAL_REBUILD_BYTES")
    _require_content(canonical_payload, EXPECTED_CANONICAL_CONTENT, "CANONICAL_REBUILD")
    canonical_rows = parse_bridge_payload(canonical_payload)
    require(
        pose_stream_sha256(row.pose_tokens for row in bridge_rows)
        == pose_stream_sha256(row.pose_tokens for row in canonical_rows)
        == prepared.bridge_pose_stream_sha256,
        "CANONICAL_REBUILD_POSE_STREAM",
    )

    output = normalized_absolute(output)
    receipt = normalized_absolute(receipt or Path(str(output) + ".receipt.json"))
    require(output not in (normalized_absolute(bridge_path), normalized_absolute(bridge_receipt_path)), "CANONICAL_OUTPUT_UPSTREAM_COLLISION")
    require(receipt not in (normalized_absolute(bridge_path), normalized_absolute(bridge_receipt_path)), "CANONICAL_RECEIPT_UPSTREAM_COLLISION")
    expected_output = identity_for_payload(output, canonical_payload)
    record = stage2_receipt(
        prepared,
        bridge_identity,
        bridge_receipt_identity,
        expected_output,
    )
    output_identity, receipt_identity = publish_output_and_receipt(
        output,
        canonical_payload,
        receipt,
        canonical_json(record),
    )
    require(output_identity == expected_output, "CANONICAL_POSTCOMMIT_IDENTITY")
    actual_record, actual_receipt_identity = read_canonical_receipt(receipt, "CANONICAL_RECEIPT")
    require(actual_record == record, "CANONICAL_RECEIPT_POSTCOMMIT_CONTRACT")
    require(actual_receipt_identity == receipt_identity, "CANONICAL_RECEIPT_POSTCOMMIT_IDENTITY")
    return {
        "status": record["status"],
        "stage": record["stage"],
        "output": output_identity,
        "receipt": receipt_identity,
        "upstream_bridge": bridge_identity,
        "upstream_bridge_receipt": bridge_receipt_identity,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("audit", help="validate both stages in memory; write only stdout")
    bridge_parser = commands.add_parser("bridge", help="publish the lossless column bridge")
    bridge_parser.add_argument("--output", type=Path, required=True)
    bridge_parser.add_argument("--receipt", type=Path)
    canonical_parser = commands.add_parser(
        "canonicalize", help="publish exact source-index timestamp rows"
    )
    canonical_parser.add_argument("--bridge", type=Path, required=True)
    canonical_parser.add_argument("--bridge-receipt", type=Path, required=True)
    canonical_parser.add_argument("--output", type=Path, required=True)
    canonical_parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            result = audit_record(prepare_evidence())
        elif args.command == "bridge":
            result = bridge_stage(args.output, args.receipt)
        else:
            result = canonicalize_stage(
                args.bridge,
                args.bridge_receipt,
                args.output,
                args.receipt,
            )
        sys.stdout.buffer.write(canonical_json(result))
        return 0
    except (BridgeError, OSError) as error:
        print(f"CONTRACT_BLOCKED:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
