#!/usr/bin/env python3
"""Build the frozen P07 backend replay queue after frontend/D closeout.

The module deliberately separates live evidence collection from deterministic
queue construction.  Importing it, and running it without ``--write``, cannot
create a formal queue or authorize a VINS replay.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping, Sequence

try:
    from scripts import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_correction
    from scripts import build_p07_backend_legacy_d_compatibility_lock_v1 as legacy_d
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_backend_frontend_provenance_v1 as frontend_provenance
    from scripts import p07_g0_publisher_v1 as rooted_io
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_evaluator_epoch_ns_correction_lock_v1 as epoch_correction  # type: ignore
    import build_p07_backend_legacy_d_compatibility_lock_v1 as legacy_d  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_backend_frontend_provenance_v1 as frontend_provenance  # type: ignore
    import p07_g0_publisher_v1 as rooted_io  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"

MANIFEST = BUNDLE / "dataset_manifest_v4.csv"
ARM_ORDER = BUNDLE / "arm_order.csv"
METHOD_LOCK = BUNDLE / "method_lock.json"
ENVIRONMENT = BUNDLE / "environment_manifest_nativeq_v5_final.txt"
EVALUATOR = BUNDLE / "evaluator_protocol_v1.md"
FAILURE_TAXONOMY = BUNDLE / "failure_taxonomy_v1.yaml"
EVALUATOR_CORRECTION_LOCK = P07 / "evaluator_precision_correction_lock_v1.json"
EVALUATOR_CORRECTION_BUILDER = (
    ROOT / "scripts/build_p07_evaluator_precision_correction_lock_v1.py"
)
EVALUATOR_CORRECTION_TEST = (
    ROOT / "scripts/tests/test_p07_evaluator_precision_correction_lock_v1.py"
)
EVALUATOR_EPOCH_CORRECTION_LOCK = (
    P07 / "evaluator_epoch_ns_correction_lock_v1.json"
)
EVALUATOR_EPOCH_CORRECTION_BUILDER = (
    ROOT / "scripts/build_p07_evaluator_epoch_ns_correction_lock_v1.py"
)
EVALUATOR_EPOCH_CORRECTION_TEST = (
    ROOT / "scripts/tests/test_p07_evaluator_epoch_ns_correction_v1.py"
)
EVALUATOR_SOURCES = (
    ROOT / "scripts/evaluate_vins_common_support.py",
    ROOT / "scripts/trajectory_eval_core.py",
    ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py",
    ROOT / "scripts/p07_backend_evaluation_v1.py",
    ROOT / "scripts/run_p07_g0_evaluation_v1.py",
)
FRONTEND_QUEUE = P07 / "frontend_export_queue_v1.csv"
FRONTEND_ALLOCATION = P07 / "frontend_run_allocation_v1.csv"
FRONTEND_QUEUE_LOCK = P07 / "frontend_queue_lock_v1.json"
FRONTEND_QUEUE_VALIDATION = P07 / "frontend_queue_validation_v1.json"
D_QUEUE = P07 / "d_applicability_queue_v1.csv"
RUN_REGISTRY = BUNDLE / "run_registry.csv"
ARM_APPLICABILITY = BUNDLE / "arm_applicability.csv"

BACKEND_QUEUE = P07 / "backend_replay_queue_v1.csv"
BACKEND_ALLOCATION = P07 / "backend_run_allocation_v1.csv"
BACKEND_QUEUE_LOCK = P07 / "backend_queue_lock_v1.json"
BACKEND_QUEUE_VALIDATION = P07 / "backend_queue_validation_v1.json"
BACKEND_REGISTRATION_INTENT = P07 / "backend_registration_intent_v1.json"
BACKEND_REGISTRATION = P07 / "backend_registration_v1.json"
BACKEND_REPLACEMENT_CONTRACT = P07 / "backend_replacement_contract_v1.json"
BACKEND_EXECUTION_LOCK = P07 / "backend_replay_execution_lock_v1.json"

SCHEMA = "isj-p07-backend-replay-queue-v1"
ALLOCATION_SCHEMA = "isj-p07-backend-run-allocation-v1"
LOCK_SCHEMA = "isj-p07-backend-queue-lock-v1"
PROTOCOL = "isj-nativeq-v3-confirmatory-protocol-v1"
OUTCOME_BOUNDARY = "BACKEND_QUEUE_FROZEN_BEFORE_P07_TRAJECTORY_OUTCOME"
B0_PROVENANCE_KIND = "B0_NATIVE_DATA_IDENTITY_V1"
D_PROVENANCE_KIND = "D_EXACT_DERIVATION_V1"

B0 = "B0_native_vins_origin_v1"
B1 = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"
REQUIRED_ARMS = (B0, B1, P_ARM, M_ARM)
FEATURE_ARMS = (B1, P_ARM, M_ARM)
ALL_ARMS = (*REQUIRED_ARMS, D_ARM)

FRONTEND_AUDIT_NAMES = ("audit_v4.json", "audit_v3.json", "audit_v2.json")
ALLOWED_FRONTEND_AUDIT_SCHEMAS = {
    "isj-p07-b1-frontend-export-audit-v2",
    "isj-p07-mp-frontend-export-audit-v2",
    "isj-p07-a01-frontend-export-audit-v3",
    "isj-p07-frontend-export-audit-v3",
    "isj-p07-frontend-export-audit-v4",
}
CAPACITY_POLICY = "REMAINING_ESTIMATE_X1P2_PLUS_2GIB_RESERVE"
MIB = 1024**2

QUEUE_FIELDS = [
    "schema_version",
    "queue_index",
    "assignment_rank",
    "pattern_id",
    "arm_order_position",
    "replay_index",
    "algorithmic_slot",
    "run_id",
    "window_id",
    "dataset_family",
    "data_domain",
    "sequence",
    "window_start_s",
    "window_end_s",
    "runner_start",
    "runner_end_or_duration",
    "runner_unit",
    "runner_mode",
    "runner_method",
    "runner_every_n",
    "runner_tag",
    "texture_stratum",
    "selection_tier",
    "arm",
    "arm_role",
    "applicability",
    "source_frontend_queue_index",
    "source_d_slot_index",
    "source_run_id",
    "source_provenance_kind",
    "source_provenance_hash",
    "feature_bag",
    "feature_bag_sha256",
    "attestation_path",
    "attestation_sha256",
    "input_audit_path",
    "input_audit_sha256",
    "replay_argv_json",
    "replay_argv_sha256",
    "expected_run_dir",
    "expected_attempt_dir",
    "evaluator_profile_id",
    "estimated_output_bytes",
    "status",
    "method_lock_hash",
    "environment_manifest_sha256",
    "evaluator_protocol_sha256",
    "evaluator_implementation_sha256",
    "failure_taxonomy_sha256",
    "capacity_policy",
    "outcome_boundary",
]

ALLOCATION_FIELDS = [
    "schema_version",
    "queue_index",
    "run_id",
    "allocated_at",
    "window_id",
    "dataset_family",
    "sequence",
    "window_start_s",
    "window_end_s",
    "arm",
    "replay_index",
    "algorithmic_slot",
    "backend_replay",
    "source_frontend_queue_index",
    "source_run_id",
    "source_provenance_kind",
    "source_provenance_hash",
    "feature_bag",
    "feature_bag_sha256",
    "attestation_path",
    "attestation_sha256",
    "expected_run_dir",
    "expected_attempt_dir",
    "status",
    "method_lock_hash",
    "backend_queue_lock_hash",
    "outcome_boundary",
]


class ReadinessError(RuntimeError):
    """Raised when live P07 frontend/D evidence is not globally terminal."""


@dataclass(frozen=True)
class FileRecord:
    path: str
    sha256: str
    size_bytes: int

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class SourceEvidence:
    window_id: str
    arm: str
    feature_bag: str
    feature_bag_sha256: str
    feature_bag_size_bytes: int
    attestation_path: str
    attestation_sha256: str
    input_audit_path: str
    input_audit_sha256: str
    source_run_id: str
    source_provenance_kind: str
    source_provenance_hash: str
    source_provenance: Mapping[str, object]
    frontend_queue_index: int | None = None
    d_slot_index: int | None = None


@dataclass(frozen=True)
class DResolution:
    window_id: str
    slot_index: int
    resolution: str
    evidence_path: str
    evidence_sha256: str
    resolution_provenance_hash: str = ""
    resolution_provenance: Mapping[str, object] | None = None
    source: SourceEvidence | None = None


@dataclass(frozen=True)
class ReadinessSnapshot:
    manifest_rows: tuple[dict[str, str], ...]
    arm_order_rows: tuple[dict[str, str], ...]
    sources: Mapping[tuple[str, str], SourceEvidence]
    d_resolutions: Mapping[str, DResolution]
    frontend_completed: int
    frontend_total: int
    frontend_audit_pass: int
    d_terminal: int
    d_total: int
    input_records: tuple[FileRecord, ...] = ()
    mutable_prefix_records: tuple[FileRecord, ...] = ()


def read_csv(path: Path) -> list[dict[str, str]]:
    _fields, rows, _record = csv_snapshot(path)
    return rows


def _parse_csv_content(path: Path, content: bytes) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ValueError(f"invalid or ragged CSV: {path}")
    return fields, rows


def csv_snapshot(path: Path) -> tuple[list[str], list[dict[str, str]], FileRecord]:
    content, record = rooted_io.read_bytes_and_record_bound_input_rooted(
        ROOT, path, label="backend queue CSV"
    )
    fields, rows = _parse_csv_content(path, content)
    return fields, rows, FileRecord(
        str(record["path"]), str(record["sha256"]), int(record["size_bytes"])
    )


def read_csv_with_fields(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    fields, rows, _record = csv_snapshot(path)
    return fields, rows


def render_csv(fields: Sequence[str], rows: Sequence[Mapping[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256(path: Path, *, root: Path = ROOT) -> str:
    return str(
        rooted_io.direct_file_record_bound_input_rooted(
            root, path, label="backend queue artifact"
        )["sha256"]
    )


def lexical_repo_path(value: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"path must be a lexical repository-relative path: {value!r}")
    return ROOT.joinpath(*pure.parts)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact is outside the workspace: {path}") from exc


def file_record(path: Path) -> FileRecord:
    record = rooted_io.direct_file_record_bound_input_rooted(
        ROOT, path, label="backend queue artifact"
    )
    return FileRecord(
        str(record["path"]), str(record["sha256"]), int(record["size_bytes"])
    )


def json_snapshot(path: Path, *, label: str) -> tuple[dict[str, object], FileRecord]:
    try:
        content, record = rooted_io.read_bytes_and_record_bound_input_rooted(
            ROOT, path, label=label
        )
        value = json.loads(content)
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        rooted_io.gov.G0GovernanceError,
    ) as error:
        raise ReadinessError(f"invalid {label} JSON: {display_path(path)}") from error
    if not isinstance(value, dict):
        raise ReadinessError(f"{label} is not a JSON object: {display_path(path)}")
    return value, FileRecord(
        str(record["path"]), str(record["sha256"]), int(record["size_bytes"])
    )


def content_record(path: Path, content: bytes) -> FileRecord:
    return FileRecord(display_path(path), sha256_bytes(content), len(content))


def lock_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop("backend_queue_lock_hash", None)
    return sha256_bytes(canonical_json(clone).encode("utf-8"))


def slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not normalized:
        raise ValueError(f"cannot slug value: {value!r}")
    return normalized


def allocation_stamp(allocated_at: str) -> str:
    try:
        parsed = datetime.fromisoformat(allocated_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("allocated_at must be an ISO-8601 timestamp with timezone") from exc
    if parsed.tzinfo is None:
        raise ValueError("allocated_at must include a timezone")
    return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def runner_bounds(window: Mapping[str, str]) -> tuple[str, str, str]:
    start = float(window["window_start_s"])
    end = float(window["window_end_s"])
    if end <= start:
        raise ValueError(f"invalid window bounds: {window['window_id']}")
    if window["dataset_family"].startswith("aqualoc_"):
        return str(round(start * 20.0)), str(round(end * 20.0)), "frame"
    return number(start), number(end - start), "second"


def number(value: float | str) -> str:
    parsed = float(value)
    return str(int(parsed)) if parsed.is_integer() else format(parsed, ".9g")


def arm_short(arm: str) -> str:
    return {B0: "B0", B1: "B1", P_ARM: "P", M_ARM: "M", D_ARM: "D"}[arm]


def runner_root(dataset_family: str) -> str:
    return {
        "ntnu": "logs/ntnu_vins",
        "aqualoc_archaeology": "logs/aqualoc_archaeo_vins",
        "aqualoc_harbor": "logs/aqualoc_real_vins",
        "afrl": "logs/afrl_cave_v31",
    }[dataset_family]


def evaluator_profile(dataset_family: str) -> str:
    if dataset_family not in {"ntnu", "aqualoc_archaeology", "aqualoc_harbor", "afrl"}:
        raise ValueError(f"unsupported evaluator family: {dataset_family}")
    return f"g0_common_support_v1:{dataset_family}"


def estimated_output_bytes(source: SourceEvidence | None) -> int:
    # Backend outputs are not allowed to duplicate a frozen feature bag.  The
    # estimate covers logs/config/trajectory/evaluator staging and remains
    # deliberately conservative for the batch-level 1.2x capacity gate.
    source_quarter = 0 if source is None else math.ceil(source.feature_bag_size_bytes / 4)
    return max(16 * MIB, source_quarter)


def _b0_source(window: Mapping[str, str]) -> SourceEvidence:
    window_id = str(window["window_id"])
    source_run_id = f"B0_NATIVE_DATA:{window_id}"
    manifest_row = dict(window)
    payload: dict[str, object] = {
        "schema_version": "isj-p07-backend-b0-native-data-provenance-v1",
        "kind": B0_PROVENANCE_KIND,
        "source_run_id": source_run_id,
        "window_id": window_id,
        "dataset_manifest_row": manifest_row,
        "dataset_manifest_row_sha256": sha256_bytes(
            canonical_json(manifest_row).encode("utf-8")
        ),
        "play_input_identity_disposition": (
            "FINAL_EXACT_RAW_PLAY_INPUT_BOUND_BY_BACKEND_EXECUTION_LOCK_V1"
        ),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    return SourceEvidence(
        window_id=window_id,
        arm=B0,
        feature_bag="",
        feature_bag_sha256="",
        feature_bag_size_bytes=0,
        attestation_path="",
        attestation_sha256="",
        input_audit_path="",
        input_audit_sha256="",
        source_run_id=source_run_id,
        source_provenance_kind=B0_PROVENANCE_KIND,
        source_provenance_hash=frontend_provenance.provenance_hash(payload),
        source_provenance=payload,
    )


def sources_with_b0(snapshot: ReadinessSnapshot) -> dict[tuple[str, str], SourceEvidence]:
    sources = dict(snapshot.sources)
    for window in snapshot.manifest_rows:
        key = (window["window_id"], B0)
        if key in sources:
            raise ReadinessError(f"snapshot unexpectedly contains a B0 source: {key[0]}")
        sources[key] = _b0_source(window)
    return sources


def _latest_registry_by_run(rows: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    for row in rows:
        latest[row["run_id"]] = row
    return latest


def _locate_frontend_audit(queue_row: Mapping[str, str]) -> Path:
    if int(queue_row["queue_index"]) == frontend_provenance.Q55_INDEX:
        return lexical_repo_path(frontend_provenance.Q55_AUDIT)
    attempt = (
        P07
        / "frontend_attempts"
        / f"queue_{int(queue_row['queue_index']):03d}_{queue_row['tag']}"
    )
    for name in FRONTEND_AUDIT_NAMES:
        candidate = attempt / name
        if rooted_io.path_state_rooted(
            ROOT, candidate, label="frontend audit candidate"
        ) == "FILE":
            return candidate
    raise ReadinessError(f"missing PASS frontend audit under {attempt}")


def _checked_file_from_payload(record: Mapping[str, object], *, label: str) -> FileRecord:
    path_value = str(record.get("path", ""))
    expected_hash = str(record.get("sha256", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ReadinessError(f"{label} lacks a SHA-256 binding")
    path = lexical_repo_path(path_value)
    observed = file_record(path)
    if observed.sha256 != expected_hash:
        raise ReadinessError(f"{label} hash drift: {path_value}")
    return observed


def _frontend_source(
    queue_row: Mapping[str, str],
    *,
    audit_path: Path,
    provenance_payload: Mapping[str, object],
) -> SourceEvidence:
    audit, observed_audit_record = json_snapshot(
        audit_path, label="frontend audit"
    )
    checks = audit.get("checks")
    if (
        audit.get("schema_version") not in ALLOWED_FRONTEND_AUDIT_SCHEMAS
        or audit.get("status") != "PASS"
        or int(audit.get("queue_index", -1)) != int(queue_row["queue_index"])
        or audit.get("window_id") != queue_row["window_id"]
        or audit.get("arm") != queue_row["arm"]
        or audit.get("held_out_trajectory_outcome_read") is not False
        or audit.get("forbidden_outcome_artifacts") != []
        or not isinstance(checks, dict)
        or not (
            checks.get("arm_attestation_bound") is True
            or checks.get("nativeq_attestation_bound") is True
        )
    ):
        raise ReadinessError(f"frontend audit identity/boundary mismatch: {audit_path}")
    source_run_id = str(provenance_payload.get("source_run_id", ""))
    if source_run_id != audit.get("run_id"):
        raise ReadinessError(f"frontend provenance/audit run ID mismatch: {audit_path}")
    audit_record = provenance_payload.get("audit")
    if (
        not isinstance(audit_record, dict)
        or audit_record.get("path") != display_path(audit_path)
        or audit_record.get("sha256") != observed_audit_record.sha256
        or audit_record.get("size_bytes") != observed_audit_record.size_bytes
    ):
        raise ReadinessError(f"frontend provenance/audit record mismatch: {audit_path}")
    feature = audit.get("feature_bag")
    attestation = audit.get("attestation")
    if not isinstance(feature, dict) or not isinstance(attestation, dict):
        raise ReadinessError(f"frontend audit lacks bag/attestation records: {audit_path}")
    feature_record = _checked_file_from_payload(feature, label="feature bag")
    attestation_record = _checked_file_from_payload(attestation, label="attestation")
    return SourceEvidence(
        window_id=str(queue_row["window_id"]),
        arm=str(queue_row["arm"]),
        frontend_queue_index=int(queue_row["queue_index"]),
        d_slot_index=None,
        feature_bag=feature_record.path,
        feature_bag_sha256=feature_record.sha256,
        feature_bag_size_bytes=feature_record.size_bytes,
        attestation_path=attestation_record.path,
        attestation_sha256=attestation_record.sha256,
        input_audit_path=display_path(audit_path),
        input_audit_sha256=observed_audit_record.sha256,
        source_run_id=source_run_id,
        source_provenance_kind=str(provenance_payload.get("kind", "")),
        source_provenance_hash=frontend_provenance.provenance_hash(
            provenance_payload
        ),
        source_provenance=dict(provenance_payload),
    )


def _matching_applicability(
    rows: Sequence[dict[str, str]], window: Mapping[str, str]
) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if row["protocol_version"] == PROTOCOL
        and row["method_profile"] == P_ARM
        and row["dataset_family"] == window["dataset_family"]
        and row["sequence"] == window["sequence"]
        and float(row["window_start"]) == float(window["window_start_s"])
        and float(row["window_end"]) == float(window["window_end_s"])
        and row["proposed_arm"] == P_ARM
        and row["drop_arm"] == D_ARM
    ]


def _render_applicability_row(
    fields: Sequence[str], row: Mapping[str, str]
) -> bytes:
    stream = io.StringIO(newline="")
    csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n").writerow(row)
    return stream.getvalue().encode("utf-8")


def _validate_prefix_snapshot(snapshot: Mapping[str, object], *, label: str) -> None:
    try:
        path = lexical_repo_path(str(snapshot["path"]))
        size_value = (
            snapshot["size_bytes"]
            if "size_bytes" in snapshot
            else snapshot["prefix_size_bytes"]
        )
        hash_value = (
            snapshot["sha256"]
            if "sha256" in snapshot
            else snapshot["prefix_sha256"]
        )
        size = int(size_value)
        expected = str(hash_value)
    except (KeyError, TypeError, ValueError) as error:
        raise ReadinessError(f"invalid {label} prefix snapshot") from error
    content = rooted_io.read_bytes_bound_input_rooted(
        ROOT, path, label=f"{label} prefix"
    )
    if (
        size < 0
        or len(content) < size
        or hashlib.sha256(content[:size]).hexdigest() != expected
    ):
        raise ReadinessError(f"{label} prefix drift: {display_path(path)}")


def _load_legacy_d_context() -> tuple[
    dict[str, object], FileRecord, dict[str, tuple[dict[str, object], FileRecord]]
]:
    try:
        lock = legacy_d.validate_live_bundle(root=ROOT)
    except Exception as error:
        raise ReadinessError(f"legacy-D compatibility bundle is not ready: {error}") from error
    lock_record = file_record(legacy_d.OUTPUT)
    sidecars: dict[str, tuple[dict[str, object], FileRecord]] = {}
    for case in legacy_d.CASES:
        path = ROOT / case.sidecar_relative
        payload, record = json_snapshot(path, label="legacy-D sidecar")
        sidecars[case.window_id] = (payload, record)
    return lock, lock_record, sidecars


def _validate_general_d_lock(
    *,
    window: Mapping[str, str],
    evidence_path: Path,
    evidence_payload: Mapping[str, object],
    canonical_row: Mapping[str, str],
    applicability_fields: Sequence[str],
) -> tuple[dict[str, object], FileRecord]:
    lock_relative = str(evidence_payload.get("resolution_lock", ""))
    lock_path = lexical_repo_path(lock_relative)
    lock, lock_record = json_snapshot(lock_path, label="D resolution lock")
    schema = lock.get("schema_version")
    common_lock_keys = {
        "schema_version",
        "status",
        "frozen_at",
        "window_id",
        "dataset_family",
        "sequence",
        "lineage_contract",
        "decision",
        "parent_p",
        "b1",
        "expected_resolution_output",
        "expected_derivation_dir",
        "artifacts",
        "mutable_stream_prefix_snapshots",
        "outcome_boundary",
        "trajectory_outcome_read",
        "resolution_lock_hash",
    }
    expected_lock_keys = set(common_lock_keys)
    if schema == "isj-p07-d-resolution-lock-v3":
        expected_lock_keys.add("audit_compatibility_correction")
    elif schema == "isj-p07-d-resolution-lock-v4":
        expected_lock_keys.update(
            {
                "audit_compatibility_correction",
                "layout_replacement_compatibility",
                "parent_resolution_contracts",
                "a04_d_path_correction",
            }
        )
    if set(lock) != expected_lock_keys:
        raise ReadinessError(f"D resolution lock schema expansion/drift: {lock_relative}")
    lock_hash_value = str(lock.get("resolution_lock_hash", ""))
    if (
        schema
        not in {
            "isj-p07-d-resolution-lock-v2",
            "isj-p07-d-resolution-lock-v3",
            "isj-p07-d-resolution-lock-v4",
        }
        or lock.get("status") != "FROZEN_READY_TO_RESOLVE_D"
        or lock.get("window_id") != window["window_id"]
        or lock.get("expected_resolution_output") != display_path(evidence_path)
        or lock.get("trajectory_outcome_read") is not False
        or lock_hash_value
        != frontend_provenance.document_hash(lock, "resolution_lock_hash")
        or evidence_payload.get("resolver_hash") != lock_hash_value
        or canonical_row.get("resolver_hash") != lock_hash_value
    ):
        raise ReadinessError(f"D resolution lock mismatch: {lock_relative}")
    artifacts = lock.get("artifacts")
    prefixes = lock.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not isinstance(prefixes, list):
        raise ReadinessError(f"D resolution lock lacks evidence arrays: {lock_relative}")
    parent_p = lock.get("parent_p")
    b1 = lock.get("b1")
    lineage = lock.get("lineage_contract")
    if (
        not isinstance(parent_p, dict)
        or set(parent_p)
        != {"run_id", "registry_event_id", "audit", "feature_bag", "feature_bag_sha256"}
        or not isinstance(b1, dict)
        or set(b1)
        != {"run_id", "registry_event_id", "feature_bag", "feature_bag_sha256"}
        or not isinstance(lineage, dict)
        or set(lineage)
        != {
            "accepted_learned_born_lineage_count",
            "birth_rule",
            "late_marker_policy",
        }
        or lineage.get("birth_rule")
        != "first ID occurrence has is_learned=1 or source_code in {10,20,30}"
        or lineage.get("late_marker_policy") != "FAIL_CLOSED"
    ):
        raise ReadinessError(f"D resolution lock parent/lineage schema drift: {lock_relative}")
    common_artifact_paths = {
        display_path(FRONTEND_QUEUE),
        display_path(FRONTEND_ALLOCATION),
        display_path(FRONTEND_QUEUE_LOCK),
        display_path(METHOD_LOCK),
        display_path(D_QUEUE),
        str(parent_p["audit"]),
        str(parent_p["feature_bag"]),
        str(b1["feature_bag"]),
        "scripts/resolve_p07_d_applicability_v2.py",
        "scripts/build_p07_d_resolution_lock_v2.py",
        "scripts/filter_feature_bag_by_channel.py",
        "scripts/audit_whole_lineage_exact_drop_v1.py",
        "scripts/attest_nativeq_feature_bag.py",
        "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json",
    }
    expected_artifact_paths = set(common_artifact_paths)
    if schema in {"isj-p07-d-resolution-lock-v3", "isj-p07-d-resolution-lock-v4"}:
        expected_artifact_paths.update(
            {
                "scripts/resolve_p07_d_applicability_v3.py",
                "scripts/build_p07_d_resolution_lock_v3.py",
                "scripts/tests/test_p07_d_resolution_v3.py",
            }
        )
    if schema == "isj-p07-d-resolution-lock-v4":
        expected_artifact_paths.update(
            {
                "scripts/resolve_p07_d_applicability_v4.py",
                "scripts/build_p07_d_resolution_lock_v4.py",
                "scripts/tests/test_p07_d_resolution_v4.py",
            }
        )
        layout = lock.get("layout_replacement_compatibility")
        correction = lock.get("a04_d_path_correction")
        if not isinstance(layout, dict) or not isinstance(correction, dict):
            raise ReadinessError("D v4 recovery/correction evidence is invalid")
        for key in ("recovery_lock", "recovery_closeout"):
            record = layout.get(key)
            if not isinstance(record, dict):
                raise ReadinessError("D v4 layout replacement record is invalid")
            expected_artifact_paths.add(str(record.get("path", "")))
        added = correction.get("added_artifacts")
        if not isinstance(added, list) or len(added) != 4:
            raise ReadinessError("D v4 correction artifact set is invalid")
        expected_artifact_paths.update(
            str(record.get("path", ""))
            for record in added
            if isinstance(record, dict)
        )
    observed_artifact_paths: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}:
            raise ReadinessError(f"D resolution lock artifact malformed: {lock_relative}")
        path_value = str(item.get("path", ""))
        if path_value in observed_artifact_paths:
            raise ReadinessError(f"D resolution lock artifact duplicate: {path_value}")
        observed_artifact_paths.add(path_value)
        record = _checked_file_from_payload(item, label="D resolution lock artifact")
        if record.size_bytes != int(item.get("size_bytes", -1)):
            raise ReadinessError(f"D resolution lock artifact size drift: {record.path}")
    if observed_artifact_paths != expected_artifact_paths:
        raise ReadinessError(f"D resolution lock exact artifact set drift: {lock_relative}")
    expected_prefix_paths = {display_path(ARM_APPLICABILITY), display_path(RUN_REGISTRY)}
    observed_prefix_paths: set[str] = set()
    for item in prefixes:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "sha256", "size_bytes"}
            or type(item.get("size_bytes")) is not int
            or int(item["size_bytes"]) <= 0
        ):
            raise ReadinessError(f"D resolution prefix malformed: {lock_relative}")
        observed_prefix_paths.add(str(item["path"]))
        _validate_prefix_snapshot(item, label="D resolution lock")
    if len(prefixes) != 2 or observed_prefix_paths != expected_prefix_paths:
        raise ReadinessError(f"D resolution lock exact prefix set drift: {lock_relative}")
    try:
        lineage_count = int(lineage["accepted_learned_born_lineage_count"])
        canonical_count = int(canonical_row["accepted_lineage_count"])
        evidence_count = int(evidence_payload["accepted_learned_born_lineage_count"])
    except (KeyError, TypeError, ValueError) as error:
        raise ReadinessError("D resolution lineage count is invalid") from error
    resolution = str(evidence_payload.get("resolution", ""))
    expected_decision = (
        "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1"
        if lineage_count == 0
        else "APPLICABLE_DERIVE_EXACT_WHOLE_LINEAGE_DROP"
    )
    if (
        lineage_count < 0
        or canonical_count != lineage_count
        or evidence_count != lineage_count
        or canonical_row.get("resolution") != resolution
        or lock.get("decision") != expected_decision
        or (resolution == "NOT_APPLICABLE") != (lineage_count == 0)
        or (lock.get("expected_derivation_dir") is None) != (lineage_count == 0)
        or parent_p.get("run_id") != evidence_payload.get("parent_p_run_id")
        or parent_p.get("audit") != evidence_payload.get("p_audit")
    ):
        raise ReadinessError("D resolution decision/lineage cross-binding drift")
    artifact_by_path = {str(item["path"]): item for item in artifacts}
    p_audit_record = artifact_by_path[str(parent_p["audit"])]
    if p_audit_record.get("sha256") != evidence_payload.get("p_audit_sha256"):
        raise ReadinessError("D resolution parent audit hash drift")
    if resolution == "NOT_APPLICABLE":
        zero = evidence_payload.get("zero_action_identity")
        if (
            evidence_payload.get("derivation") is not None
            or not isinstance(zero, dict)
            or set(zero)
            != {
                "status",
                "p_feature_bag",
                "p_feature_bag_sha256",
                "b1_feature_bag",
                "b1_feature_bag_sha256",
            }
            or zero.get("status") != "PASS_BYTE_IDENTICAL_TO_B1"
            or zero.get("p_feature_bag") != parent_p.get("feature_bag")
            or zero.get("p_feature_bag_sha256") != parent_p.get("feature_bag_sha256")
            or zero.get("b1_feature_bag") != b1.get("feature_bag")
            or zero.get("b1_feature_bag_sha256") != b1.get("feature_bag_sha256")
            or parent_p.get("feature_bag_sha256") != b1.get("feature_bag_sha256")
        ):
            raise ReadinessError("D resolution zero-action identity drift")
    elif resolution == "APPLICABLE":
        derivation = evidence_payload.get("derivation")
        derivation_dir = str(lock.get("expected_derivation_dir", ""))
        expected_derivation = {
            "drop_bag": f"{derivation_dir}/features.bag",
            "producer_stats": f"{derivation_dir}/drop_whole_lineage_stats.csv",
            "exact_drop_audit": f"{derivation_dir}/exact_drop_audit.json",
            "attestation": f"{derivation_dir}/features.bag.quality-contract.json",
            "output_hash_manifest": f"{derivation_dir}/output_hash_manifest.sha256",
        }
        if (
            evidence_payload.get("zero_action_identity") is not None
            or not isinstance(derivation, dict)
            or set(derivation)
            != {
                "drop_bag",
                "drop_bag_sha256",
                "producer_stats",
                "exact_drop_audit",
                "exact_drop_audit_sha256",
                "attestation",
                "attestation_sha256",
                "output_hash_manifest",
            }
            or any(derivation.get(key) != value for key, value in expected_derivation.items())
            or any(
                re.fullmatch(r"[0-9a-f]{64}", str(derivation.get(key, ""))) is None
                for key in (
                    "drop_bag_sha256",
                    "exact_drop_audit_sha256",
                    "attestation_sha256",
                )
            )
        ):
            raise ReadinessError("D applicable derivation contract drift")
    else:
        raise ReadinessError("D resolution terminal value is invalid")
    canonical_stream = evidence_payload.get("canonical_stream")
    rendered_hash = sha256_bytes(
        _render_applicability_row(applicability_fields, canonical_row)
    )
    if (
        not isinstance(canonical_stream, dict)
        or canonical_stream.get("path") != display_path(ARM_APPLICABILITY)
        or canonical_stream.get("appended_row_sha256") != rendered_hash
    ):
        raise ReadinessError(
            f"D resolution canonical row binding mismatch: {window['window_id']}"
        )
    _validate_prefix_snapshot(canonical_stream, label="D terminal applicability")
    return lock, lock_record


def _d_resolution(
    window: Mapping[str, str],
    slot_index: int,
    applicability_fields: Sequence[str],
    applicability_rows: Sequence[dict[str, str]],
    *,
    legacy_lock: Mapping[str, object],
    legacy_lock_record: FileRecord,
    legacy_sidecars: Mapping[str, tuple[dict[str, object], FileRecord]],
) -> DResolution:
    matches = _matching_applicability(applicability_rows, window)
    terminal = [row for row in matches if row["resolution"] != "PENDING_APPLICABILITY"]
    if len(terminal) != 1:
        raise ReadinessError(
            f"window must have exactly one terminal D resolution: {window['window_id']}"
        )
    row = terminal[0]
    resolution = row["resolution"]
    if resolution not in {"APPLICABLE", "NOT_APPLICABLE"}:
        raise ReadinessError(
            f"D resolution is terminal but not replay-safe: {window['window_id']}:{resolution}"
        )
    legacy_item = legacy_sidecars.get(str(window["window_id"]))
    if legacy_item is not None:
        if resolution != "NOT_APPLICABLE":
            raise ReadinessError("legacy-D compatibility cannot authorize applicable D")
        sidecar, evidence_record = legacy_item
        if (
            sidecar.get("window_id") != window["window_id"]
            or int(sidecar.get("slot_index", -1)) != slot_index
            or sidecar.get("resolution") != resolution
            or sidecar.get("canonical_applicability_row") != dict(row)
            or sidecar.get("p_b1_byte_identical") is not True
            or sidecar.get("held_out_trajectory_outcome_read") is not False
        ):
            raise ReadinessError(
                f"legacy-D compatibility sidecar mismatch: {window['window_id']}"
            )
        resolution_provenance: dict[str, object] = {
            "schema_version": "isj-p07-backend-d-resolution-provenance-v1",
            "kind": "LEGACY_D_COMPATIBILITY_V1",
            "window_id": window["window_id"],
            "slot_index": slot_index,
            "resolution": resolution,
            "compatibility_lock": legacy_lock_record.as_dict(),
            "compatibility_lock_hash": legacy_lock.get("compatibility_lock_hash"),
            "sidecar": evidence_record.as_dict(),
            "sidecar_payload": dict(sidecar),
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        }
        return DResolution(
            window_id=str(window["window_id"]),
            slot_index=slot_index,
            resolution=resolution,
            evidence_path=evidence_record.path,
            evidence_sha256=evidence_record.sha256,
            resolution_provenance_hash=frontend_provenance.provenance_hash(
                resolution_provenance
            ),
            resolution_provenance=resolution_provenance,
        )

    evidence_path = lexical_repo_path(row["evidence_path"])
    payload, evidence_record = json_snapshot(
        evidence_path, label="D resolution evidence"
    )
    if (
        payload.get("schema_version") != "isj-p07-d-applicability-resolution-v2"
        or payload.get("status") != f"PASS_{resolution}"
        or payload.get("window_id") != window["window_id"]
        or payload.get("resolution") != resolution
        or int(payload.get("accepted_learned_born_lineage_count", -1))
        != int(row["accepted_lineage_count"])
        or payload.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ReadinessError(f"D resolution evidence mismatch: {evidence_path}")
    lock, lock_record = _validate_general_d_lock(
        window=window,
        evidence_path=evidence_path,
        evidence_payload=payload,
        canonical_row=row,
        applicability_fields=applicability_fields,
    )

    resolution_provenance = {
        "schema_version": "isj-p07-backend-d-resolution-provenance-v1",
        "kind": "GENERALIZED_D_LOCK_V2_TO_V4",
        "window_id": window["window_id"],
        "slot_index": slot_index,
        "resolution": resolution,
        "resolution_record": evidence_record.as_dict(),
        "resolution_lock": lock_record.as_dict(),
        "resolution_lock_hash": lock["resolution_lock_hash"],
        "canonical_applicability_row": dict(row),
        "canonical_applicability_row_sha256": sha256_bytes(
            _render_applicability_row(applicability_fields, row)
        ),
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }

    source: SourceEvidence | None = None
    if resolution == "APPLICABLE":
        derivation = payload.get("derivation")
        if not isinstance(derivation, dict):
            raise ReadinessError(f"applicable D lacks derivation evidence: {evidence_path}")
        drop = _checked_file_from_payload(
            {"path": derivation.get("drop_bag"), "sha256": derivation.get("drop_bag_sha256")},
            label="D feature bag",
        )
        attestation = _checked_file_from_payload(
            {"path": derivation.get("attestation"), "sha256": derivation.get("attestation_sha256")},
            label="D attestation",
        )
        exact_audit = _checked_file_from_payload(
            {
                "path": derivation.get("exact_drop_audit"),
                "sha256": derivation.get("exact_drop_audit_sha256"),
            },
            label="D exact-drop audit",
        )
        exact_payload, exact_observed = json_snapshot(
            lexical_repo_path(exact_audit.path), label="D exact-drop audit"
        )
        if exact_observed != exact_audit:
            raise ReadinessError(f"D exact-drop audit snapshot drift: {exact_audit.path}")
        if (
            exact_payload.get("decision") != "PASS_EXACT_WHOLE_LINEAGE_DROP"
            or exact_payload.get("contract_pass") is not True
        ):
            raise ReadinessError(f"D exact-drop audit is not PASS: {exact_audit.path}")
        source = SourceEvidence(
            window_id=str(window["window_id"]),
            arm=D_ARM,
            frontend_queue_index=None,
            d_slot_index=slot_index,
            feature_bag=drop.path,
            feature_bag_sha256=drop.sha256,
            feature_bag_size_bytes=drop.size_bytes,
            attestation_path=attestation.path,
            attestation_sha256=attestation.sha256,
            input_audit_path=exact_audit.path,
            input_audit_sha256=exact_audit.sha256,
            source_run_id=str(payload.get("parent_p_run_id", "")),
            source_provenance_kind=D_PROVENANCE_KIND,
            source_provenance_hash="",
            source_provenance={},
        )
        d_source_provenance: dict[str, object] = {
            **resolution_provenance,
            "kind": D_PROVENANCE_KIND,
            "source_run_id": source.source_run_id,
            "feature_bag": drop.as_dict(),
            "attestation": attestation.as_dict(),
            "exact_drop_audit": exact_audit.as_dict(),
        }
        source = SourceEvidence(
            **{
                **source.__dict__,
                "source_provenance_hash": frontend_provenance.provenance_hash(
                    d_source_provenance
                ),
                "source_provenance": d_source_provenance,
            }
        )
    else:
        zero = payload.get("zero_action_identity")
        if not isinstance(zero, dict):
            raise ReadinessError(f"not-applicable D lacks zero-action identity: {evidence_path}")
        p_bag = _checked_file_from_payload(
            {"path": zero.get("p_feature_bag"), "sha256": zero.get("p_feature_bag_sha256")},
            label="D parent P feature bag",
        )
        b1_bag = _checked_file_from_payload(
            {"path": zero.get("b1_feature_bag"), "sha256": zero.get("b1_feature_bag_sha256")},
            label="D B1 identity feature bag",
        )
        p_audit = _checked_file_from_payload(
            {"path": payload.get("p_audit"), "sha256": payload.get("p_audit_sha256")},
            label="D parent P audit",
        )
        if (
            int(payload.get("accepted_learned_born_lineage_count", -1)) != 0
            or payload.get("derivation") is not None
            or zero.get("status") != "PASS_BYTE_IDENTICAL_TO_B1"
            or p_bag.sha256 != b1_bag.sha256
        ):
            raise ReadinessError(f"not-applicable D zero-action identity mismatch: {evidence_path}")
        resolution_provenance["zero_action_identity"] = {
            "p_feature_bag": p_bag.as_dict(),
            "b1_feature_bag": b1_bag.as_dict(),
            "parent_p_audit": p_audit.as_dict(),
            "status": "PASS_BYTE_IDENTICAL_TO_B1",
        }
    return DResolution(
        window_id=str(window["window_id"]),
        slot_index=slot_index,
        resolution=resolution,
        evidence_path=evidence_record.path,
        evidence_sha256=evidence_record.sha256,
        resolution_provenance_hash=frontend_provenance.provenance_hash(
            resolution_provenance
        ),
        resolution_provenance=resolution_provenance,
        source=source,
    )


def _validate_frontend_queue_governance(
    *,
    frontend_queue_record: FileRecord | None = None,
    d_queue_record: FileRecord | None = None,
) -> tuple[FileRecord, FileRecord]:
    lock, lock_record = json_snapshot(
        FRONTEND_QUEUE_LOCK, label="frontend queue lock"
    )
    validation, validation_record = json_snapshot(
        FRONTEND_QUEUE_VALIDATION, label="frontend queue validation"
    )
    if frontend_queue_record is None:
        frontend_queue_record = file_record(FRONTEND_QUEUE)
    if d_queue_record is None:
        d_queue_record = file_record(D_QUEUE)
    lock_hash_value = str(lock.get("queue_lock_hash", ""))
    lock_clone = dict(lock)
    lock_clone.pop("queue_lock_hash", None)
    export = lock.get("frontend_export_queue")
    d_queue = lock.get("d_applicability_queue")
    if (
        lock.get("schema_version") != "isj-p07-frontend-queue-lock-v1"
        or lock.get("status") != "FROZEN_FOR_EXPORT_EXECUTION"
        or lock_hash_value
        != sha256_bytes(canonical_json(lock_clone).encode("utf-8"))
        or int(lock.get("frontend_export_jobs", -1)) != 60
        or int(lock.get("conditional_d_slots", -1)) != 20
        or lock.get("held_out_trajectory_outcome_read") is not False
        or not isinstance(export, dict)
        or not isinstance(d_queue, dict)
    ):
        raise ReadinessError("frontend queue lock semantic/hash mismatch")
    for item, expected_path, observed_record, label in (
        (
            export,
            FRONTEND_QUEUE,
            frontend_queue_record,
            "frontend export queue",
        ),
        (d_queue, D_QUEUE, d_queue_record, "D applicability queue"),
    ):
        if (
            item.get("path") != display_path(expected_path)
            or item.get("sha256") != observed_record.sha256
            or int(item.get("size_bytes", -1)) != observed_record.size_bytes
        ):
            raise ReadinessError(f"frontend queue lock {label} record mismatch")
    deterministic = validation.get("deterministic_rebuild")
    artifacts = validation.get("artifacts")
    if (
        validation.get("schema_version")
        != "isj-p07-frontend-queue-validation-v1"
        or validation.get("status") != "PASS"
        or validation.get("queue_lock_hash") != lock_hash_value
        or int(validation.get("frontend_export_jobs", -1)) != 60
        or int(validation.get("conditional_d_slots", -1)) != 20
        or validation.get("dry_run_all_requested") is not True
        or int(validation.get("dry_run_pass_count", -1)) != 60
        or validation.get("issues") != []
        or not isinstance(deterministic, dict)
        or set(deterministic) != {
            "frontend_queue_byte_identical",
            "d_queue_byte_identical",
            "queue_lock_semantic_identical",
        }
        or not all(value is True for value in deterministic.values())
        or validation.get("held_out_trajectory_outcome_read") is not False
        or not isinstance(artifacts, dict)
        or artifacts.get("frontend_queue_sha256") != frontend_queue_record.sha256
        or artifacts.get("d_queue_sha256") != d_queue_record.sha256
        or artifacts.get("queue_lock_sha256") != lock_record.sha256
    ):
        raise ReadinessError("frontend queue validation is not a bound PASS")
    return lock_record, validation_record


def collect_live_snapshot() -> ReadinessSnapshot:
    """Read frontend-only governance and assert global backend readiness.

    This function hashes feature bags and attestations.  It never opens a VINS
    trajectory, VINS log, APE result, or RPE result.
    """

    _manifest_fields, manifest, manifest_record = csv_snapshot(MANIFEST)
    _arm_fields, arm_order, arm_order_record = csv_snapshot(ARM_ORDER)
    _frontend_fields, frontend_queue, frontend_queue_record = csv_snapshot(
        FRONTEND_QUEUE
    )
    _allocation_fields, allocations, frontend_allocation_record = csv_snapshot(
        FRONTEND_ALLOCATION
    )
    _registry_fields, registry_rows, registry_record = csv_snapshot(RUN_REGISTRY)
    applicability_fields, applicability, applicability_record = csv_snapshot(
        ARM_APPLICABILITY
    )
    _d_queue_fields, d_queue_rows, d_queue_record = csv_snapshot(D_QUEUE)
    frontend_lock_record, frontend_validation_record = (
        _validate_frontend_queue_governance(
            frontend_queue_record=frontend_queue_record,
            d_queue_record=d_queue_record,
        )
    )
    legacy_lock, legacy_lock_record, legacy_sidecars = _load_legacy_d_context()
    if len(manifest) != 20 or len(frontend_queue) != 60 or len(allocations) != 60:
        raise ReadinessError("formal backend freeze requires 20 windows and 60 frontend rows")
    allocations_by_index = {int(row["queue_index"]): row for row in allocations}
    if len(allocations_by_index) != 60:
        raise ReadinessError("frontend allocation queue indices are not unique")

    sources: dict[tuple[str, str], SourceEvidence] = {}
    completed = 0
    audits = 0
    for row in frontend_queue:
        index = int(row["queue_index"])
        allocation = allocations_by_index.get(index)
        if allocation is None or allocation["window_id"] != row["window_id"] or allocation["arm"] != row["arm"]:
            raise ReadinessError(f"frontend allocation mismatch at queue {index}")
        audit_path = _locate_frontend_audit(row)
        try:
            provenance_payload = frontend_provenance.resolve_frontend_provenance(
                row,
                allocation,
                registry_rows,
                root=ROOT,
                canonical_audit_path=audit_path,
            )
        except frontend_provenance.ProvenanceError as error:
            raise ReadinessError(
                f"frontend source provenance failed at queue {index}: {error}"
            ) from error
        source = _frontend_source(
            row,
            audit_path=audit_path,
            provenance_payload=provenance_payload,
        )
        completed += 1
        audits += 1
        key = (source.window_id, source.arm)
        if key in sources:
            raise ReadinessError(f"duplicate frontend source: {key}")
        sources[key] = source

    d_slots = {row["window_id"]: int(row["slot_index"]) for row in d_queue_rows}
    if (
        len(d_slots) != 20
        or len(d_queue_rows) != 20
        or set(d_slots.values()) != set(range(1, 21))
    ):
        raise ReadinessError("D queue does not contain exactly 20 unique slots")
    resolutions: dict[str, DResolution] = {}
    for window in manifest:
        window_id = window["window_id"]
        if window_id not in d_slots:
            raise ReadinessError(f"D queue lacks manifest window: {window_id}")
        resolution = _d_resolution(
            window,
            d_slots[window_id],
            applicability_fields,
            applicability,
            legacy_lock=legacy_lock,
            legacy_lock_record=legacy_lock_record,
            legacy_sidecars=legacy_sidecars,
        )
        resolutions[window_id] = resolution
        if resolution.source is not None:
            sources[(window_id, D_ARM)] = resolution.source

    fixed_records = {
        record.path: record
        for record in (
            manifest_record,
            arm_order_record,
            frontend_queue_record,
            frontend_allocation_record,
            d_queue_record,
            frontend_lock_record,
            frontend_validation_record,
        )
    }
    inputs = tuple(
        (
            fixed_records[display_path(path)]
            if display_path(path) in fixed_records
            else file_record(path)
        )
        for path in (
            MANIFEST,
            ARM_ORDER,
            METHOD_LOCK,
            ENVIRONMENT,
            EVALUATOR,
            FAILURE_TAXONOMY,
            FRONTEND_QUEUE,
            FRONTEND_ALLOCATION,
            D_QUEUE,
            FRONTEND_QUEUE_LOCK,
            FRONTEND_QUEUE_VALIDATION,
            legacy_d.A01_SIDECAR,
            legacy_d.A02_SIDECAR,
            legacy_d.OUTPUT,
            EVALUATOR_CORRECTION_LOCK,
            EVALUATOR_CORRECTION_BUILDER,
            EVALUATOR_CORRECTION_TEST,
            EVALUATOR_EPOCH_CORRECTION_LOCK,
            EVALUATOR_EPOCH_CORRECTION_BUILDER,
            EVALUATOR_EPOCH_CORRECTION_TEST,
            *EVALUATOR_SOURCES,
        )
    )
    snapshot = ReadinessSnapshot(
        manifest_rows=tuple(manifest),
        arm_order_rows=tuple(arm_order),
        sources=sources,
        d_resolutions=resolutions,
        frontend_completed=completed,
        frontend_total=len(frontend_queue),
        frontend_audit_pass=audits,
        d_terminal=len(resolutions),
        d_total=len(d_slots),
        input_records=inputs,
        mutable_prefix_records=(registry_record, applicability_record),
    )
    assert_ready(snapshot)
    return snapshot


def assert_ready(snapshot: ReadinessSnapshot) -> None:
    if len(snapshot.manifest_rows) != 20:
        raise ReadinessError("backend queue requires exactly 20 frozen windows")
    if (
        snapshot.frontend_total != 60
        or snapshot.frontend_completed != 60
        or snapshot.frontend_audit_pass != 60
    ):
        raise ReadinessError("formal generation requires 60/60 completed, audited frontend exports")
    if snapshot.d_total != 20 or snapshot.d_terminal != 20:
        raise ReadinessError("formal generation requires 20/20 terminal D resolutions")
    window_ids = {row["window_id"] for row in snapshot.manifest_rows}
    if set(snapshot.d_resolutions) != window_ids:
        raise ReadinessError("D resolution window set differs from frozen manifest")
    for window_id in window_ids:
        for arm in FEATURE_ARMS:
            source = snapshot.sources.get((window_id, arm))
            if source is None:
                raise ReadinessError(f"missing frozen frontend source: {window_id}:{arm}")
            if (
                not source.source_run_id
                or not source.source_provenance_kind
                or source.source_provenance_hash
                != frontend_provenance.provenance_hash(source.source_provenance)
            ):
                raise ReadinessError(f"invalid frontend source provenance: {window_id}:{arm}")
        resolution = snapshot.d_resolutions[window_id]
        if resolution.resolution not in {"APPLICABLE", "NOT_APPLICABLE"}:
            raise ReadinessError(f"non-replay-safe D resolution: {window_id}")
        if (resolution.resolution == "APPLICABLE") != (
            (window_id, D_ARM) in snapshot.sources
        ):
            raise ReadinessError(f"D applicability/source mismatch: {window_id}")
        if (
            not resolution.resolution_provenance_hash
            or resolution.resolution_provenance is None
            or resolution.resolution_provenance_hash
            != frontend_provenance.provenance_hash(
                resolution.resolution_provenance
            )
        ):
            raise ReadinessError(f"invalid D resolution provenance: {window_id}")


def evaluator_implementation_hash(
    payload: Mapping[str, object] | None = None,
) -> str:
    if payload is None:
        relative = EVALUATOR_EPOCH_CORRECTION_LOCK.relative_to(ROOT).as_posix()
        content, _identity = formal_io.read_direct_bytes(ROOT, relative)
        loaded = json.loads(content)
        if not isinstance(loaded, dict):
            raise ValueError("evaluator epoch-ns correction lock must be an object")
        payload = loaded
    epoch_correction.validate_lock_payload(payload, root=ROOT, verify_files=True)
    binding = payload.get("corrected_implementation_binding")
    if not isinstance(binding, Mapping):
        raise ValueError("evaluator epoch-ns correction lacks implementation binding")
    files = binding.get("files")
    if not isinstance(files, list) or [item.get("path") for item in files] != [
        "scripts/evaluate_vins_common_support.py",
        "scripts/trajectory_eval_core.py",
        "scripts/evaluate_vins_common_support_epoch_v2.py",
    ]:
        raise ValueError("evaluator epoch-ns implementation paths are not exact")
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("evaluator correction file record is invalid")
        record = _checked_file_from_payload(
            item, label="corrected epoch-ns evaluator implementation"
        )
        if record.size_bytes != int(item.get("size_bytes", -1)):
            raise ValueError(f"corrected epoch-ns evaluator size drift: {record.path}")
    bundle = sha256_bytes(canonical_json(files).encode("utf-8"))
    if bundle != binding.get("implementation_bundle_sha256"):
        raise ValueError("evaluator epoch-ns implementation bundle hash mismatch")
    protocol = payload.get("protocol_binding")
    if (
        not isinstance(protocol, dict)
        or protocol.get("unchanged") is not True
        or protocol.get("sha256") != sha256(EVALUATOR)
    ):
        raise ValueError("evaluator protocol changed across the epoch-ns correction")
    return bundle


def _assert_snapshot_record(
    snapshot: ReadinessSnapshot | None, observed: FileRecord
) -> None:
    if snapshot is None:
        return
    frozen = {record.path: record for record in snapshot.input_records}.get(observed.path)
    if frozen is None or frozen != observed:
        raise ReadinessError(f"backend input drift after live snapshot: {observed.path}")


def _method_hashes(
    snapshot: ReadinessSnapshot | None = None,
) -> tuple[str, str, str, str, str]:
    method, method_record = json_snapshot(METHOD_LOCK, label="method lock")
    _assert_snapshot_record(snapshot, method_record)
    method_hash = str(method.get("method_lock_hash", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", method_hash):
        raise ValueError("method_lock.json lacks a valid method_lock_hash")
    environment_record = file_record(ENVIRONMENT)
    evaluator_record = file_record(EVALUATOR)
    failure_record = file_record(FAILURE_TAXONOMY)
    for record in (environment_record, evaluator_record, failure_record):
        _assert_snapshot_record(snapshot, record)
    epoch_payload, epoch_record = json_snapshot(
        EVALUATOR_EPOCH_CORRECTION_LOCK,
        label="evaluator epoch-ns correction lock",
    )
    _assert_snapshot_record(snapshot, epoch_record)
    return (
        method_hash,
        environment_record.sha256,
        evaluator_record.sha256,
        evaluator_implementation_hash(epoch_payload),
        failure_record.sha256,
    )


def build_queue_rows(
    snapshot: ReadinessSnapshot,
    *,
    allocated_at: str,
    method_hashes: tuple[str, str, str, str, str] | None = None,
) -> list[dict[str, object]]:
    assert_ready(snapshot)
    stamp = allocation_stamp(allocated_at)
    method_hash, environment_hash, evaluator_hash, evaluator_impl_hash, failure_hash = (
        method_hashes if method_hashes is not None else _method_hashes(snapshot)
    )
    manifest = {row["window_id"]: row for row in snapshot.manifest_rows}
    effective_sources = sources_with_b0(snapshot)
    orders: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in snapshot.arm_order_rows:
        if row["window_id"] in manifest:
            orders[row["window_id"]].append(row)
    if len(orders) != 20 or any(len(rows) != 5 for rows in orders.values()):
        raise ValueError("arm_order must contain five frozen arm rows per window")

    ordered_windows = sorted(
        manifest,
        key=lambda window_id: int(orders[window_id][0]["assignment_rank"]),
    )
    result: list[dict[str, object]] = []
    for window_id in ordered_windows:
        window = manifest[window_id]
        rows = sorted(orders[window_id], key=lambda row: int(row["order_position"]))
        required = [row["arm"] for row in rows if row["arm"] in REQUIRED_ARMS]
        if len(required) != 4 or set(required) != set(REQUIRED_ARMS):
            raise ValueError(f"invalid Williams required-arm order: {window_id}")
        d_resolution = snapshot.d_resolutions[window_id]
        selected_orders = [
            row
            for row in rows
            if row["arm"] in REQUIRED_ARMS
            or (row["arm"] == D_ARM and d_resolution.resolution == "APPLICABLE")
        ]
        start_arg, end_arg, unit = runner_bounds(window)
        for order_row in selected_orders:
            arm = order_row["arm"]
            source = effective_sources[(window_id, arm)]
            for replay_index in range(1, 4):
                queue_index = len(result) + 1
                short = arm_short(arm)
                run_id = (
                    f"isj-nativeq-v3_P07_{slug(window['dataset_family'])}-"
                    f"{slug(window['sequence'])}_{slug(start_arg)}-{slug(end_arg)}_"
                    f"{short}_f0_b{replay_index:02d}_{stamp}"
                )
                runner_mode = "origin" if arm == B0 else "external"
                runner_method = "xfeat" if arm == M_ARM else "klt"
                runner_tag = (
                    f"p07_backend_{slug(window_id)}_{short.lower()}_"
                    f"b{replay_index:02d}_{stamp}"
                )
                run_dir = (
                    f"{runner_root(window['dataset_family'])}/{runner_mode}_"
                    f"{runner_method}_every2_{runner_tag}"
                )
                attempt_dir = (
                    "papers/ieee_sensors_journal_experiments/p07/backend_attempts/"
                    f"queue_{queue_index:03d}_{run_id}_attempt01"
                )
                argv = [
                    "python3",
                    "scripts/run_p07_backend_replay_job_v1.py",
                    "--queue-index",
                    str(queue_index),
                    "--execution-lock",
                    (
                        "papers/ieee_sensors_journal_experiments/p07/"
                        "backend_replay_execution_lock_v1.json"
                    ),
                ]
                argv_json = canonical_json(argv)
                result.append(
                    {
                        "schema_version": SCHEMA,
                        "queue_index": queue_index,
                        "assignment_rank": int(order_row["assignment_rank"]),
                        "pattern_id": int(order_row["pattern_id"]),
                        "arm_order_position": int(order_row["order_position"]),
                        "replay_index": replay_index,
                        "algorithmic_slot": f"b{replay_index:02d}",
                        "run_id": run_id,
                        "window_id": window_id,
                        "dataset_family": window["dataset_family"],
                        "data_domain": window["data_domain"],
                        "sequence": window["sequence"],
                        "window_start_s": window["window_start_s"],
                        "window_end_s": window["window_end_s"],
                        "runner_start": start_arg,
                        "runner_end_or_duration": end_arg,
                        "runner_unit": unit,
                        "runner_mode": runner_mode,
                        "runner_method": runner_method,
                        "runner_every_n": 2,
                        "runner_tag": runner_tag,
                        "texture_stratum": window["texture_stratum"],
                        "selection_tier": window["selection_tier"],
                        "arm": arm,
                        "arm_role": order_row["arm_role"],
                        "applicability": (
                            "APPLICABLE" if arm == D_ARM else "REQUIRED"
                        ),
                        "source_frontend_queue_index": (
                            "" if source is None or source.frontend_queue_index is None else source.frontend_queue_index
                        ),
                        "source_d_slot_index": (
                            "" if source is None or source.d_slot_index is None else source.d_slot_index
                        ),
                        "source_run_id": source.source_run_id,
                        "source_provenance_kind": source.source_provenance_kind,
                        "source_provenance_hash": source.source_provenance_hash,
                        "feature_bag": "" if source is None else source.feature_bag,
                        "feature_bag_sha256": "" if source is None else source.feature_bag_sha256,
                        "attestation_path": "" if source is None else source.attestation_path,
                        "attestation_sha256": "" if source is None else source.attestation_sha256,
                        "input_audit_path": "" if source is None else source.input_audit_path,
                        "input_audit_sha256": "" if source is None else source.input_audit_sha256,
                        "replay_argv_json": argv_json,
                        "replay_argv_sha256": sha256_bytes(argv_json.encode("utf-8")),
                        "expected_run_dir": run_dir,
                        "expected_attempt_dir": attempt_dir,
                        "evaluator_profile_id": evaluator_profile(window["dataset_family"]),
                        "estimated_output_bytes": estimated_output_bytes(source),
                        "status": "PLANNED",
                        "method_lock_hash": method_hash,
                        "environment_manifest_sha256": environment_hash,
                        "evaluator_protocol_sha256": evaluator_hash,
                        "evaluator_implementation_sha256": evaluator_impl_hash,
                        "failure_taxonomy_sha256": failure_hash,
                        "capacity_policy": CAPACITY_POLICY,
                        "outcome_boundary": OUTCOME_BOUNDARY,
                    }
                )
    applicable = sum(
        resolution.resolution == "APPLICABLE"
        for resolution in snapshot.d_resolutions.values()
    )
    expected = 240 + 3 * applicable
    if len(result) != expected or not 240 <= len(result) <= 300:
        raise ValueError(f"backend queue size mismatch: {len(result)} != {expected}")
    if len({str(row["run_id"]) for row in result}) != len(result):
        raise ValueError("backend run IDs are not unique")
    return result


def build_allocation_rows(
    queue_rows: Sequence[Mapping[str, object]],
    *,
    allocated_at: str,
    backend_queue_lock_hash: str,
) -> list[dict[str, object]]:
    allocation_stamp(allocated_at)
    rows: list[dict[str, object]] = []
    for item in queue_rows:
        rows.append(
            {
                "schema_version": ALLOCATION_SCHEMA,
                "queue_index": item["queue_index"],
                "run_id": item["run_id"],
                "allocated_at": allocated_at,
                "window_id": item["window_id"],
                "dataset_family": item["dataset_family"],
                "sequence": item["sequence"],
                "window_start_s": item["window_start_s"],
                "window_end_s": item["window_end_s"],
                "arm": item["arm"],
                "replay_index": item["replay_index"],
                "algorithmic_slot": item["algorithmic_slot"],
                "backend_replay": item["algorithmic_slot"],
                "source_frontend_queue_index": item["source_frontend_queue_index"],
                "source_run_id": item["source_run_id"],
                "source_provenance_kind": item["source_provenance_kind"],
                "source_provenance_hash": item["source_provenance_hash"],
                "feature_bag": item["feature_bag"],
                "feature_bag_sha256": item["feature_bag_sha256"],
                "attestation_path": item["attestation_path"],
                "attestation_sha256": item["attestation_sha256"],
                "expected_run_dir": item["expected_run_dir"],
                "expected_attempt_dir": item["expected_attempt_dir"],
                "status": "PLANNED",
                "method_lock_hash": item["method_lock_hash"],
                "backend_queue_lock_hash": backend_queue_lock_hash,
                "outcome_boundary": OUTCOME_BOUNDARY,
            }
        )
    return rows


def build_outputs(
    snapshot: ReadinessSnapshot,
    *,
    allocated_at: str,
    method_hashes: tuple[str, str, str, str, str] | None = None,
    include_code_records: bool = True,
) -> dict[Path, bytes]:
    queue_rows = build_queue_rows(
        snapshot, allocated_at=allocated_at, method_hashes=method_hashes
    )
    effective_sources = sources_with_b0(snapshot)
    queue_content = render_csv(QUEUE_FIELDS, queue_rows)
    applicable = sum(
        resolution.resolution == "APPLICABLE"
        for resolution in snapshot.d_resolutions.values()
    )
    precision_correction_binding: dict[str, object] | None = None
    epoch_correction_binding: dict[str, object] | None = None
    if method_hashes is None:
        correction_payload, correction_record = json_snapshot(
            EVALUATOR_CORRECTION_LOCK,
            label="evaluator precision correction lock",
        )
        epoch_payload, epoch_record = json_snapshot(
            EVALUATOR_EPOCH_CORRECTION_LOCK,
            label="evaluator epoch-ns correction lock",
        )
        _assert_snapshot_record(snapshot, correction_record)
        _assert_snapshot_record(snapshot, epoch_record)
        precision_correction_binding = {
            "lock": correction_record.as_dict(),
            "correction_lock_hash": correction_payload.get("correction_lock_hash"),
        }
        epoch_correction_binding = {
            "lock": epoch_record.as_dict(),
            "epoch_ns_correction_lock_hash": epoch_payload.get(
                "epoch_ns_correction_lock_hash"
            ),
            "entrypoint": epoch_payload.get(
                "corrected_implementation_binding", {}
            ).get("entrypoint"),
            "implementation_bundle_sha256": next(
                iter(
                    {
                        str(row["evaluator_implementation_sha256"])
                        for row in queue_rows
                    }
                )
            ),
        }
    artifacts = [record.as_dict() for record in snapshot.input_records]
    if include_code_records:
        for path in (
            ROOT / "scripts/build_p07_backend_replay_queue_v1.py",
            ROOT / "scripts/validate_p07_backend_replay_queue_v1.py",
            ROOT / "scripts/register_p07_backend_allocations_v1.py",
            ROOT / "scripts/p07_backend_formal_io_v1.py",
            ROOT / "scripts/p07_backend_frontend_provenance_v1.py",
            ROOT / "scripts/build_p07_backend_legacy_d_compatibility_lock_v1.py",
            ROOT / "scripts/build_p07_backend_b0_materialization_lock_v1.py",
            ROOT / "scripts/run_p07_backend_b0_materialization_v1.py",
            ROOT / "scripts/tests/test_p07_backend_replay_queue_v1.py",
            ROOT / "scripts/tests/test_p07_backend_registration_v1.py",
            ROOT / "scripts/tests/test_p07_backend_formal_io_v1.py",
            ROOT / "scripts/tests/test_p07_backend_frontend_provenance_v1.py",
            ROOT / "scripts/tests/test_p07_backend_legacy_d_compatibility_lock_v1.py",
            ROOT / "scripts/tests/test_p07_backend_b0_materialization_v1.py",
            ROOT / "scripts/tests/test_p07_backend_execution_lock_v1.py",
        ):
            state = rooted_io.path_state_rooted(
                ROOT, path, label="backend queue code artifact"
            )
            if state == "FILE":
                artifacts.append(file_record(path).as_dict())
            elif state != "ABSENT":
                raise ReadinessError(
                    f"backend queue code artifact is not a direct file: {display_path(path)}"
                )
    lock: dict[str, object] = {
        "schema_version": LOCK_SCHEMA,
        "status": "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK",
        "frozen_at": allocated_at,
        "protocol_version": PROTOCOL,
        "backend_replay_jobs": len(queue_rows),
        "base_required_jobs": 240,
        "conditional_d_windows": applicable,
        "conditional_d_jobs": 3 * applicable,
        "maximum_backend_jobs": 300,
        "algorithmic_replays_per_window_arm": 3,
        "frontend_completion_gate": {
            "completed": snapshot.frontend_completed,
            "total": snapshot.frontend_total,
            "pass_audits": snapshot.frontend_audit_pass,
        },
        "d_resolution_gate": {
            "terminal": snapshot.d_terminal,
            "total": snapshot.d_total,
            "applicable": applicable,
            "not_applicable": snapshot.d_total - applicable,
        },
        "evaluator_precision_correction": precision_correction_binding,
        "evaluator_epoch_ns_correction": epoch_correction_binding,
        "backend_replay_queue": content_record(BACKEND_QUEUE, queue_content).as_dict(),
        "allocation_disposition": (
            "DERIVED_FROM_QUEUE_AND_BOUND_BY_BACKEND_EXECUTION_LOCK_V1"
        ),
        "source_evidence": [
            {
                "window_id": source.window_id,
                "arm": source.arm,
                "feature_bag": source.feature_bag,
                "feature_bag_sha256": source.feature_bag_sha256,
                "attestation_path": source.attestation_path,
                "attestation_sha256": source.attestation_sha256,
                "input_audit_path": source.input_audit_path,
                "input_audit_sha256": source.input_audit_sha256,
                "source_run_id": source.source_run_id,
                "source_provenance_kind": source.source_provenance_kind,
                "source_provenance_hash": source.source_provenance_hash,
                "source_provenance": dict(source.source_provenance),
            }
            for _key, source in sorted(effective_sources.items())
        ],
        "d_resolutions": [
            {
                "window_id": item.window_id,
                "slot_index": item.slot_index,
                "resolution": item.resolution,
                "evidence_path": item.evidence_path,
                "evidence_sha256": item.evidence_sha256,
                "resolution_provenance_hash": item.resolution_provenance_hash,
                "resolution_provenance": (
                    None
                    if item.resolution_provenance is None
                    else dict(item.resolution_provenance)
                ),
            }
            for _window, item in sorted(snapshot.d_resolutions.items())
        ],
        "artifacts": artifacts,
        "mutable_stream_prefix_snapshots": [
            record.as_dict() for record in snapshot.mutable_prefix_records
        ],
        "mutable_registry_prefix": next(
            (
                record.as_dict()
                for record in snapshot.mutable_prefix_records
                if record.path == display_path(RUN_REGISTRY)
            ),
            None,
        ),
        "ordering": (
            "assignment_rank_then_frozen_arm_order_position_then_three_serial_replays"
        ),
        "one_ros_vins_instance_at_a_time": True,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    lock["backend_queue_lock_hash"] = lock_hash(lock)
    lock_content = json_bytes(lock)
    allocation_rows = build_allocation_rows(
        queue_rows,
        allocated_at=allocated_at,
        backend_queue_lock_hash=str(lock["backend_queue_lock_hash"]),
    )
    allocation_content = render_csv(ALLOCATION_FIELDS, allocation_rows)
    return {
        BACKEND_QUEUE: queue_content,
        BACKEND_QUEUE_LOCK: lock_content,
        BACKEND_ALLOCATION: allocation_content,
    }


def _formal_relative(path: Path) -> str:
    return path.absolute().relative_to(ROOT.absolute()).as_posix()


def preflight_output_bundle(
    snapshot: ReadinessSnapshot,
    *,
    allocated_at: str,
    outputs: Mapping[Path, bytes] | None = None,
) -> tuple[dict[Path, bytes], dict[str, object]]:
    """Build exact timestamped bytes, validate them in memory, and check collisions."""

    built = (
        dict(outputs)
        if outputs is not None
        else build_outputs(snapshot, allocated_at=allocated_at)
    )
    try:
        from scripts import validate_p07_backend_replay_queue_v1 as validator
    except ModuleNotFoundError:
        import validate_p07_backend_replay_queue_v1 as validator  # type: ignore
    lock_payload = json.loads(built[BACKEND_QUEUE_LOCK])
    issues = validator.validate_artifacts(
        queue_content=built[BACKEND_QUEUE],
        allocation_content=built[BACKEND_ALLOCATION],
        lock_payload=lock_payload,
        arm_order_rows=snapshot.arm_order_rows,
    )
    if issues:
        raise ReadinessError(f"in-memory backend queue validation failed: {issues}")
    reconcile = formal_io.preflight_bundle_commit_absent(
        ROOT,
        [
            (_formal_relative(BACKEND_QUEUE), built[BACKEND_QUEUE]),
            (_formal_relative(BACKEND_ALLOCATION), built[BACKEND_ALLOCATION]),
        ],
        commit_relative=_formal_relative(BACKEND_QUEUE_LOCK),
    )
    formal_io.assert_all_absent(
        ROOT,
        [
            _formal_relative(BACKEND_QUEUE_VALIDATION),
            _formal_relative(BACKEND_REGISTRATION_INTENT),
            _formal_relative(BACKEND_REGISTRATION),
            _formal_relative(BACKEND_REPLACEMENT_CONTRACT),
            _formal_relative(BACKEND_EXECUTION_LOCK),
        ],
    )
    report = {
        "status": "READY_EXACT_TIMESTAMPED_OUTPUTS",
        "allocated_at": allocated_at,
        "backend_queue_lock_hash": lock_payload["backend_queue_lock_hash"],
        "backend_replay_jobs": lock_payload["backend_replay_jobs"],
        "queue_sha256": sha256_bytes(built[BACKEND_QUEUE]),
        "allocation_sha256": sha256_bytes(built[BACKEND_ALLOCATION]),
        "queue_lock_file_sha256": sha256_bytes(built[BACKEND_QUEUE_LOCK]),
        "crash_reconcile": reconcile,
        "held_out_trajectory_outcome_read": False,
    }
    return built, report


def publish_output_bundle(outputs: Mapping[Path, bytes]) -> None:
    formal_io.publish_bundle_commit_last(
        ROOT,
        [
            (_formal_relative(BACKEND_QUEUE), outputs[BACKEND_QUEUE]),
            (_formal_relative(BACKEND_ALLOCATION), outputs[BACKEND_ALLOCATION]),
        ],
        commit_artifact=(
            _formal_relative(BACKEND_QUEUE_LOCK),
            outputs[BACKEND_QUEUE_LOCK],
        ),
    )


def readiness_summary(snapshot: ReadinessSnapshot) -> dict[str, object]:
    applicable = sum(
        item.resolution == "APPLICABLE" for item in snapshot.d_resolutions.values()
    )
    return {
        "status": "READY",
        "frontend_completed": snapshot.frontend_completed,
        "frontend_total": snapshot.frontend_total,
        "frontend_audit_pass": snapshot.frontend_audit_pass,
        "d_terminal": snapshot.d_terminal,
        "d_total": snapshot.d_total,
        "d_applicable": applicable,
        "planned_backend_replays": 240 + 3 * applicable,
        "held_out_trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--allocated-at",
        help="ISO-8601 freeze/allocation time; required with --write",
    )
    args = parser.parse_args()
    snapshot = collect_live_snapshot()
    summary = readiness_summary(snapshot)
    if not args.preflight_only and not args.write:
        parser.error("refusing formal generation without explicit --write")
    if not args.allocated_at:
        parser.error("--allocated-at is required for exact preflight/write")
    outputs, exact = preflight_output_bundle(
        snapshot, allocated_at=args.allocated_at
    )
    if args.preflight_only:
        print(json.dumps({**summary, **exact}, indent=2, sort_keys=True))
        return 0
    publish_output_bundle(outputs)
    lock = json.loads(outputs[BACKEND_QUEUE_LOCK])
    print(
        "P07_BACKEND_QUEUE_FROZEN "
        f"jobs={lock['backend_replay_jobs']} "
        f"d_applicable={lock['conditional_d_windows']} "
        f"hash={lock['backend_queue_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
