#!/usr/bin/env python3
"""Collect one terminal P07 backend audit into failure/classification evidence.

The collector consumes an explicit audited replay, its exact backend queue
row, and the pre-outcome absolute reference contract.  It reads no APE/RPE
artifact.  When a trajectory exists, only technical validity/timestamp/finite
coverage properties needed by the frozen failure taxonomy are inspected.

Epoch timestamp handling is exact: integer nanoseconds are ordered and
subtracted as integers before any conversion to seconds.
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import io
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

try:
    from scripts import build_p07_g0_reference_contracts_v1 as references
    from scripts import p07_backend_evaluation_v1 as evaluation
    from scripts import p07_backend_replay_common_v1 as backend
    from scripts import p07_g0_governance_v1 as gov
    from scripts import p07_g0_publisher_v1 as publisher
    from scripts import run_p07_backend_replay_job_v1 as backend_job
    from scripts import run_p07_backend_serial_queue_v1 as serial_controller
except ModuleNotFoundError:
    import build_p07_g0_reference_contracts_v1 as references  # type: ignore
    import p07_backend_evaluation_v1 as evaluation  # type: ignore
    import p07_backend_replay_common_v1 as backend  # type: ignore
    import p07_g0_governance_v1 as gov  # type: ignore
    import p07_g0_publisher_v1 as publisher  # type: ignore
    import run_p07_backend_replay_job_v1 as backend_job  # type: ignore
    import run_p07_backend_serial_queue_v1 as serial_controller  # type: ignore


AUDIT_SCHEMA = "isj-p07-backend-replay-audit-v1"
NUMERIC_TIMESTAMP_RE = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
TERMINAL_PROVENANCE_SCHEMA = "isj-p07-backend-controller-terminal-provenance-v1"
CANONICAL_FAILURE_NAME = "g0_failure_evidence_v1.json"
CANONICAL_CLASSIFICATION_NAME = "g0_failure_classification_v1.json"
CANONICAL_BINDING_NAME = "g0_terminal_binding_v1.json"


def timestamp_token_to_ns(token: str) -> tuple[int, str]:
    value = token.strip()
    if not value:
        raise gov.G0GovernanceError("empty trajectory timestamp")
    try:
        if value.lstrip("+-").isdigit():
            integer = int(value)
            if abs(integer) >= 100_000_000_000_000_000:
                return integer, "INTEGER_NANOSECONDS"
        scaled = Decimal(value) * Decimal(1_000_000_000)
    except (InvalidOperation, ValueError) as error:
        raise gov.G0GovernanceError(f"invalid trajectory timestamp: {token!r}") from error
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise gov.G0GovernanceError(
            f"trajectory timestamp is not exact to nanoseconds: {token!r}"
        )
    result = int(integral)
    if result < 100_000_000 * 1_000_000_000:
        raise gov.G0GovernanceError("trajectory timestamp is not an absolute epoch")
    return result, "DECIMAL_EPOCH_SECONDS_EXACT_TO_NS"


def _inspect_trajectory_bytes(
    content: bytes, *, label: str
) -> tuple[dict[str, Any], list[int]]:
    timestamps: list[int] = []
    finite = True
    formats: set[str] = set()
    nonempty_rows = 0
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid UTF-8 trajectory: {label}") from error
    for row in csv.reader(io.StringIO(text, newline="")):
        if not row or all(not value.strip() for value in row):
            continue
        nonempty_rows += 1
        first = row[0].strip()
        # Tolerate one conventional header, but never skip a malformed
        # numeric data line later in the file.
        if nonempty_rows == 1 and NUMERIC_TIMESTAMP_RE.fullmatch(first) is None:
            continue
        timestamp, source_format = timestamp_token_to_ns(first)
        timestamps.append(timestamp)
        formats.add(source_format)
        for token in row[1:]:
            stripped = token.strip()
            if not stripped:
                finite = False
                continue
            try:
                number = float(stripped)
            except ValueError:
                finite = False
                continue
            if not math.isfinite(number):
                finite = False
    increasing = all(right > left for left, right in zip(timestamps, timestamps[1:]))
    report = {
        "present": True,
        "row_count": len(timestamps),
        "finite": finite,
        "strictly_increasing": increasing,
        "first_timestamp_ns": timestamps[0] if timestamps else None,
        "last_timestamp_ns": timestamps[-1] if timestamps else None,
        "timestamp_source_formats": sorted(formats),
        "timestamp_conversion": (
            "ORDER_AND_SUBTRACT_INTEGER_NS_BEFORE_DECIMAL_SECONDS_CONVERSION"
        ),
    }
    return report, timestamps


def inspect_trajectory(path: Path, *, root: Path | None = None) -> dict[str, Any]:
    anchor = root if root is not None else path.parent
    content = publisher.read_bytes_bound_input_rooted(
        anchor, path, label="trajectory"
    )
    report, _timestamps = _inspect_trajectory_bytes(
        content, label=gov.display_path(anchor, path)
    )
    return report


def _structure_artifact(
    audit: Mapping[str, Any], key: str, *, root: Path
) -> tuple[Path, bytes, dict[str, object]] | None:
    structure = audit.get("output_structure")
    if not isinstance(structure, Mapping):
        return None
    value = structure.get(key)
    if not isinstance(value, Mapping) or value.get("exists") is not True:
        return None
    path = value.get("path")
    if not isinstance(path, str) or not path:
        raise gov.G0GovernanceError(f"terminal audit {key} path is invalid")
    result = Path(path)
    if not result.is_absolute():
        result = root / result
    result = Path(os.path.abspath(os.fspath(result)))
    content, record = publisher.read_bytes_and_record_bound_input_rooted(
        root, result, label=f"terminal audit bound {key}"
    )
    size = value.get("size_bytes")
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
        or record["size_bytes"] != size
    ):
        raise gov.G0GovernanceError(f"terminal audit {key} size drift")
    return result, content, record


def _key_value_manifest(content: bytes, *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(
            f"invalid UTF-8 backend replay manifest: {label}"
        ) from error
    for line in text.splitlines():
        if not line or "=" not in line:
            raise gov.G0GovernanceError("malformed backend replay manifest")
        key, value = line.split("=", 1)
        if not key or key in result:
            raise gov.G0GovernanceError("duplicate backend replay manifest key")
        result[key] = value
    return result


def _process_evidence(audit: Mapping[str, Any]) -> dict[str, object]:
    technical = audit.get("technical_evidence")
    process = technical.get("process") if isinstance(technical, Mapping) else None
    if isinstance(process, Mapping):
        return {
            "exit_code": process.get("exit_code"),
            "timed_out": process.get("timed_out"),
        }
    status = audit.get("terminal_process_status")
    failure = audit.get("failure_code")
    if status == "PASS_EXECUTION_ENVELOPE":
        return {"exit_code": 0, "timed_out": False}
    if failure == "TIMEOUT":
        return {"exit_code": None, "timed_out": True}
    if failure == "NONZERO_EXIT":
        return {"exit_code": 1, "timed_out": False}
    if failure == "EMPTY_TRAJECTORY":
        return {"exit_code": 0, "timed_out": False}
    return {"exit_code": None, "timed_out": False}


def _queue_evidence(audit: Mapping[str, Any]) -> dict[str, object]:
    technical = audit.get("technical_evidence")
    queue = technical.get("queue") if isinstance(technical, Mapping) else None
    if not isinstance(queue, Mapping):
        return {
            "evidence_status": "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
            "drop_rate": None,
            "backlog_growth_s": None,
        }
    drop_rate = queue.get("drop_rate")
    backlog_growth_s = queue.get("backlog_growth_s")
    if drop_rate is None and backlog_growth_s is None:
        return {
            "evidence_status": "NOT_INSTRUMENTED_NO_ZERO_IMPUTATION",
            "drop_rate": None,
            "backlog_growth_s": None,
        }
    return {
        "evidence_status": (
            "MEASURED"
            if drop_rate is not None and backlog_growth_s is not None
            else "PARTIAL_INCOMPLETE"
        ),
        "drop_rate": drop_rate,
        "backlog_growth_s": backlog_growth_s,
    }


def _reference_record(
    reference_payload: Mapping[str, Any], window_id: str
) -> Mapping[str, Any]:
    contracts = reference_payload.get("contracts")
    if not isinstance(contracts, list):
        raise gov.G0GovernanceError("reference contract payload is invalid")
    matches = [
        item
        for item in contracts
        if isinstance(item, Mapping) and item.get("window_id") == window_id
    ]
    if len(matches) != 1:
        raise gov.G0GovernanceError(f"expected one reference contract for {window_id}")
    return matches[0]


def build_failure_evidence(
    row: Mapping[str, str],
    audit: Mapping[str, Any],
    *,
    root: Path,
    audit_path: Path,
    audit_record: Mapping[str, object] | None = None,
    reference_record: Mapping[str, Any],
    infrastructure_codes: Iterable[str] = (),
    algorithmic_slot: bool = True,
    governance_authority: Mapping[str, object] | None = None,
    terminal_provenance: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    backend.validate_queue_row(row)
    expected_identity = {
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
    }
    if audit.get("schema_version") != AUDIT_SCHEMA or audit.get("status") != "PASS":
        raise gov.G0GovernanceError("terminal backend audit schema/status mismatch")
    gov.exact_json_identity(audit, expected_identity, label="terminal backend audit")
    if audit.get("terminal") is not True:
        raise gov.G0GovernanceError("backend audit is not terminal")
    checks = audit.get("checks")
    if not isinstance(checks, Mapping) or checks.get("trajectory_values_read") is not False:
        raise gov.G0GovernanceError("backend terminal audit crossed its execution boundary")
    if checks.get("ape_rpe_values_read") is not False:
        raise gov.G0GovernanceError("backend terminal audit read APE/RPE")

    reference = reference_record.get("reference_contract")
    if not isinstance(reference, Mapping):
        raise gov.G0GovernanceError("window reference contract is missing")
    start_ns = reference.get("window_start_ns")
    end_ns = reference.get("window_end_ns")
    if (
        isinstance(start_ns, bool)
        or not isinstance(start_ns, int)
        or isinstance(end_ns, bool)
        or not isinstance(end_ns, int)
        or end_ns <= start_ns
    ):
        raise gov.G0GovernanceError("reference contract lacks exact ns endpoints")

    trajectory_artifact = _structure_artifact(audit, "trajectory", root=root)
    if trajectory_artifact is None:
        trajectory = {
            "present": False,
            "row_count": 0,
            "finite": None,
            "strictly_increasing": None,
            "first_timestamp_ns": None,
            "last_timestamp_ns": None,
            "timestamp_source_formats": [],
            "timestamp_conversion": (
                "ORDER_AND_SUBTRACT_INTEGER_NS_BEFORE_DECIMAL_SECONDS_CONVERSION"
            ),
        }
        trajectory_record = None
    else:
        trajectory_path, trajectory_bytes, trajectory_record = trajectory_artifact
        trajectory, trajectory_timestamps = _inspect_trajectory_bytes(
            trajectory_bytes, label=gov.display_path(root, trajectory_path)
        )

    first_ns = trajectory.get("first_timestamp_ns")
    last_ns = trajectory.get("last_timestamp_ns")
    if isinstance(first_ns, int) and isinstance(last_ns, int):
        first_at_or_after_start_ns = next(
            (value for value in trajectory_timestamps if value >= start_ns),
            None,
        )
        delay_ns = (
            first_at_or_after_start_ns - start_ns
            if first_at_or_after_start_ns is not None
            else None
        )
        overlap_ns = max(0, min(last_ns, end_ns) - max(first_ns, start_ns))
        duration_ns = end_ns - start_ns
        first_output_delay_s: float | None = (
            float(Decimal(delay_ns) / Decimal(1_000_000_000))
            if delay_ns is not None
            else None
        )
        coverage_ratio: float | None = float(Decimal(overlap_ns) / Decimal(duration_ns))
        initialization_success: bool | None = (
            delay_ns
            is not None
            and delay_ns
            <= int(evaluation.INITIALIZATION_DEADLINE_S * 1_000_000_000)
        )
    else:
        first_at_or_after_start_ns = None
        delay_ns = None
        overlap_ns = 0
        first_output_delay_s = None
        coverage_ratio = None
        initialization_success = None

    log_artifact = _structure_artifact(audit, "vins_log", root=root)
    if log_artifact is None:
        solver_log_text = ""
        solver_log_record = None
        solver_log_inspected = True
    else:
        _log_path, log_bytes, solver_log_record = log_artifact
        solver_log_text = log_bytes.decode("utf-8", errors="replace")
        solver_log_inspected = True

    bound_audit_record = (
        dict(audit_record)
        if audit_record is not None
        else publisher.direct_file_record_bound_input_rooted(
            root, audit_path, label="terminal backend audit"
        )
    )

    evidence: dict[str, Any] = {
        "schema_version": gov.FAILURE_EVIDENCE_SCHEMA,
        **expected_identity,
        "backend_algorithmic_slot": row["algorithmic_slot"],
        "source_run_id": row["source_run_id"],
        "source_provenance_kind": row["source_provenance_kind"],
        "source_provenance_hash": row["source_provenance_hash"],
        "algorithmic_slot": algorithmic_slot,
        "infrastructure_codes": sorted(set(infrastructure_codes)),
        "process": _process_evidence(audit),
        "trajectory": trajectory,
        "trajectory_artifact": trajectory_record,
        "initialization": {
            "success": initialization_success,
            "first_output_delay_s": first_output_delay_s,
            "first_output_delay_ns": delay_ns,
            "first_output_at_or_after_reference_start_ns": (
                first_at_or_after_start_ns
            ),
            "reference_window_start_ns": start_ns,
        },
        "support": {
            "coverage_ratio": coverage_ratio,
            "overlap_ns": overlap_ns,
            "reference_span_ns": end_ns - start_ns,
        },
        "solver_log_inspected": solver_log_inspected,
        "solver_log_text": solver_log_text,
        "solver_log_artifact": solver_log_record,
        "queue": _queue_evidence(audit),
        "terminal_audit": bound_audit_record,
        "reference_contract_hash": reference_record.get("reference_contract_hash"),
        "timestamp_policy": {
            "raw_integer_ns_preserved": True,
            "ordering_before_conversion": True,
            "subtraction_before_conversion": True,
            "absolute_epoch_required": True,
            "relative_queue_window_as_epoch_forbidden": True,
        },
        "governance_authority": (
            dict(governance_authority)
            if governance_authority is not None
            else None
        ),
        "terminal_provenance": (
            dict(terminal_provenance)
            if terminal_provenance is not None
            else None
        ),
        "outcome_boundary": (
            "FAILURE_TECHNICAL_EVIDENCE_ONLY_NO_APE_RPE_OR_COMMON_SUPPORT_METRIC_READ"
        ),
    }
    evidence["failure_evidence_hash"] = gov.canonical_json_hash(evidence)
    return evidence


def classifier_input(evidence: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "run_id",
        "window_id",
        "arm",
        "replay_index",
        "algorithmic_slot",
        "infrastructure_codes",
        "process",
        "trajectory",
        "initialization",
        "support",
        "solver_log_inspected",
        "solver_log_text",
        "queue",
    )
    return {key: evidence.get(key) for key in keys}


def build_classification(
    evidence: Mapping[str, Any],
    *,
    evidence_record: Mapping[str, object],
    classifier_record: Mapping[str, object],
) -> dict[str, Any]:
    if evidence.get("schema_version") != gov.FAILURE_EVIDENCE_SCHEMA:
        raise gov.G0GovernanceError("unexpected failure evidence schema")
    gov.validate_self_hash(evidence, "failure_evidence_hash", label="failure evidence")
    core = evaluation.classify_replay_evidence(classifier_input(evidence))
    wrapper: dict[str, Any] = {
        "schema_version": gov.CLASSIFICATION_SCHEMA,
        "status": "PASS_CLASSIFIED_FROZEN_FAILURE_TAXONOMY",
        "run_id": core["run_id"],
        "window_id": core["window_id"],
        "arm": core["arm"],
        "replay_index": core["replay_index"],
        "failure_evidence": dict(evidence_record),
        "classifier_implementation": dict(classifier_record),
        "classification": core,
        "outcome_boundary": (
            "FAILURE_CLASSIFICATION_ONLY_NO_APE_RPE_OR_COMMON_SUPPORT_METRIC_READ"
        ),
    }
    wrapper["classification_hash"] = gov.canonical_json_hash(wrapper)
    return wrapper


def _config_artifact(
    audit: Mapping[str, Any], *, root: Path
) -> tuple[Path, dict[str, object]] | None:
    manifest_artifact = _structure_artifact(
        audit, "backend_replay_manifest", root=root
    )
    if manifest_artifact is None:
        return None
    manifest_path, manifest_bytes, _manifest_record = manifest_artifact
    manifest = _key_value_manifest(
        manifest_bytes, label=gov.display_path(root, manifest_path)
    )
    raw = manifest.get("vins_config")
    if not raw:
        raise gov.G0GovernanceError("backend replay manifest lacks vins_config")
    path = Path(raw)
    if not path.is_absolute():
        path = root / path
    path = Path(os.path.abspath(os.fspath(path)))
    record = publisher.direct_file_record_bound_input_rooted(
        root, path, label="backend replay config"
    )
    return path, record


def _direct_json_with_record(
    root: Path, path: Path, *, label: str
) -> tuple[dict[str, Any], dict[str, object]]:
    content, record = publisher.read_bytes_and_record_bound_input_rooted(
        root, path, label=label
    )
    payload = gov._json_object_bytes(content, label=label)
    return payload, record


def _validate_bound_record(
    root: Path, record: Mapping[str, object], *, label: str
) -> Path:
    path = gov.workspace_path(root, record.get("path"), label=label)
    observed = publisher.direct_file_record_bound_input_rooted(
        root, path, label=label
    )
    if any(
        observed.get(key) != record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise gov.G0GovernanceError(f"{label} direct record differs")
    return path


def _read_bound_csv(
    root: Path, path: Path, *, label: str
) -> tuple[list[str], list[dict[str, str]]]:
    content = publisher.read_bytes_bound_input_rooted(root, path, label=label)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise gov.G0GovernanceError(f"invalid {label} UTF-8") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = [dict(row) for row in reader]
    if not fields or len(fields) != len(set(fields)) or any(
        set(row) != set(fields) for row in rows
    ):
        raise gov.G0GovernanceError(f"malformed {label} CSV")
    return fields, rows


def _publish_or_reconcile_exact(
    root: Path, path: Path, payload: Mapping[str, Any], *, label: str
) -> str:
    """Publish exclusively, or accept only an exact prior crash-prefix file."""

    state = publisher.path_state_rooted(root, path, label=label)
    if state == "FILE":
        observed = publisher.read_json_direct_rooted(root, path, label=label)
        if observed != payload:
            raise gov.G0GovernanceError(
                f"existing {label} differs; crash evidence preserved: {path}"
            )
        return "RECONCILED_IDENTICAL_EXISTING"
    if state != "ABSENT":
        raise gov.G0GovernanceError(f"existing {label} is not a direct file: {path}")
    publisher.write_json_exclusive_rooted(root, path, payload)
    observed = publisher.read_json_direct_rooted(root, path, label=label)
    if observed != payload:
        raise gov.G0GovernanceError(f"published {label} verification failed")
    return "PUBLISHED_EXCLUSIVE"


def _controller_terminal_authority(
    base_row: Mapping[str, str],
    *,
    root: Path,
    audit_path: Path,
    registry_path: Path,
) -> tuple[dict[str, str], dict[str, object]]:
    queue_index = int(base_row["queue_index"])
    effective_row, replacement_relative = serial_controller._replacement_for_index(
        root, queue_index, base_row
    )
    effective_row = {key: str(value) for key, value in effective_row.items()}
    backend.validate_queue_row(effective_row)
    changed = {
        key
        for key in base_row
        if effective_row.get(key) != base_row.get(key)
    }
    allowed = {
        "run_id",
        "runner_tag",
        "expected_run_dir",
        "expected_attempt_dir",
    }
    if changed not in (set(), allowed):
        raise gov.G0GovernanceError(
            f"effective backend row changed forbidden fields: {sorted(changed)}"
        )
    registry_path = gov.workspace_path(
        root, registry_path, label="canonical backend registry"
    )
    chain = backend_job.registry_chain(registry_path, effective_row["run_id"])
    latest = chain[-1]
    try:
        disposition = backend_job.terminal_slot_disposition(
            root=root, row=effective_row, latest=latest
        )
    except backend_job.JobViolation as error:
        raise gov.G0GovernanceError(
            f"backend controller terminal disposition is invalid: {error}"
        ) from error
    if disposition not in {"COMPLETED", "ALGORITHM_HARD_FAILURE"}:
        raise gov.G0GovernanceError(
            f"backend slot is not scientifically terminal: {disposition}"
        )
    attempt_relative = str(effective_row["expected_attempt_dir"])
    expected_audit = gov.workspace_path(
        root,
        f"{attempt_relative}/audit_v1.json",
        label="canonical terminal backend audit",
    )
    observed_audit = gov.workspace_path(
        root, audit_path, label="collector terminal backend audit"
    )
    if observed_audit != expected_audit:
        raise gov.G0GovernanceError(
            "collector terminal audit path differs from effective attempt authority"
        )
    manifest_path = gov.workspace_path(
        root,
        f"{attempt_relative}/output_hash_manifest.sha256",
        label="canonical terminal output manifest",
    )
    manifest_record = publisher.direct_file_record_bound_input_rooted(
        root, manifest_path, label="terminal output manifest"
    )
    replacement_binding: dict[str, object] | None = None
    if replacement_relative is not None:
        replacement_path = gov.workspace_path(
            root, replacement_relative, label="effective replacement lock"
        )
        replacement_payload, replacement_record = _direct_json_with_record(
            root, replacement_path, label="effective replacement lock"
        )
        replacement_binding = {
            **replacement_record,
            "replacement_lock_hash": replacement_payload.get(
                "replacement_lock_hash"
            ),
            "attempt_number": replacement_payload.get("attempt_number"),
            "replacement_for": replacement_payload.get("replacement_for"),
        }
    provenance: dict[str, object] = {
        "schema_version": TERMINAL_PROVENANCE_SCHEMA,
        "queue_index": queue_index,
        "base_queue_row": dict(base_row),
        "effective_queue_row": dict(effective_row),
        "allowed_effective_row_overrides": sorted(allowed),
        "changed_effective_row_fields": sorted(changed),
        "replacement_lock": replacement_binding,
        "terminal_disposition": disposition,
        "terminal_registry_event": dict(latest),
        "terminal_registry_event_sha256": (
            backend_job.replacement_allocator.row_hash(latest)
        ),
        "output_manifest": manifest_record,
        "terminal_audit_path": backend.display_path(root, expected_audit),
        "outcome_boundary": (
            "BACKEND_CONTROLLER_TERMINAL_AUTHORITY_NO_APE_RPE_RESULT_READ"
        ),
    }
    provenance["terminal_provenance_hash"] = gov.canonical_json_hash(provenance)
    return effective_row, provenance


def canonical_collection_paths(
    root: Path, effective_row: Mapping[str, str]
) -> tuple[Path, Path, Path]:
    attempt = gov.workspace_path(
        root,
        effective_row["expected_attempt_dir"],
        label="effective backend attempt directory",
    )
    return (
        attempt / CANONICAL_FAILURE_NAME,
        attempt / CANONICAL_CLASSIFICATION_NAME,
        attempt / CANONICAL_BINDING_NAME,
    )


def publish_collection(
    row: Mapping[str, str],
    *,
    root: Path,
    queue_path: Path,
    evaluation_lock_path: Path,
    execution_lock_path: Path,
    audit_path: Path,
    reference_contracts_path: Path,
    failure_output: Path,
    classification_output: Path,
    binding_output: Path,
    strict_execution_lock_validation: bool = True,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    lock, evaluation_lock_record = _direct_json_with_record(
        root, evaluation_lock_path, label="G0 evaluation lock"
    )
    evaluation_lock_hash = gov.validate_lock_payload(
        lock, root=root, verify_files=True
    )
    frozen = {
        str(record.get("role")): record
        for record in lock["frozen_inputs"]
        if isinstance(record, Mapping)
    }
    for role, observed in (
        ("backend_queue", queue_path),
        ("reference_contracts", reference_contracts_path),
    ):
        record = frozen.get(role)
        if not isinstance(record, Mapping):
            raise gov.G0GovernanceError(f"G0 lock lacks {role}")
        expected = _validate_bound_record(root, record, label=f"locked {role}")
        observed_path = gov.workspace_path(root, observed, label=f"collector {role}")
        if observed_path != expected:
            raise gov.G0GovernanceError(f"collector {role} path differs from G0 lock")
    _queue_fields, frozen_queue_rows = _read_bound_csv(
        root, queue_path, label="collector frozen backend queue"
    )
    frozen_matches = [
        candidate
        for candidate in frozen_queue_rows
        if int(candidate["queue_index"]) == int(row["queue_index"])
    ]
    if len(frozen_matches) != 1 or dict(row) != frozen_matches[0]:
        raise gov.G0GovernanceError(
            "collector base row differs from the frozen backend queue"
        )
    if row.get("evaluator_protocol_sha256") != lock["evaluation_template"][
        "evaluator"
    ]["protocol_sha256"]:
        raise gov.G0GovernanceError("queue evaluator protocol differs from G0 lock")
    execution_lock_path = gov.workspace_path(
        root,
        execution_lock_path,
        label="backend execution lock",
    )
    allocation_record = frozen.get("backend_allocation")
    if not isinstance(allocation_record, Mapping):
        raise gov.G0GovernanceError("G0 lock lacks backend allocation")
    allocation_path = _validate_bound_record(
        root, allocation_record, label="locked backend allocation"
    )
    if strict_execution_lock_validation:
        backend.validate_execution_lock(
            root,
            execution_lock_path,
            queue_path=queue_path,
            allocation_path=allocation_path,
        )
    execution_lock, execution_lock_record = _direct_json_with_record(
        root, execution_lock_path, label="backend execution lock"
    )
    execution_lock_hash = gov.validate_self_hash(
        execution_lock, "execution_lock_hash", label="backend execution lock"
    )
    authority = execution_lock.get(gov.EXECUTION_LOCK_BINDING_KEY)
    if not isinstance(authority, Mapping):
        raise gov.G0GovernanceError("execution lock lacks G0 authority binding")
    authority_hash = gov.validate_execution_authority_binding(authority, root=root)
    if authority["evaluation_lock"]["evaluation_lock_hash"] != evaluation_lock_hash:
        raise gov.G0GovernanceError("execution lock binds a different G0 lock")

    effective_row, terminal_provenance = _controller_terminal_authority(
        row,
        root=root,
        audit_path=audit_path,
        registry_path=lock["mutable_registry_prefix"]["path"],
    )
    canonical_outputs = canonical_collection_paths(root, effective_row)
    outputs = [failure_output, classification_output, binding_output]
    normalized_outputs = [
        gov.workspace_path(
            root, path, label=f"collector output {index}", require_absolute=True
        )
        for index, path in enumerate(outputs)
    ]
    if len(set(normalized_outputs)) != 3:
        raise gov.G0GovernanceError("collector outputs are duplicate")
    if tuple(normalized_outputs) != canonical_outputs:
        raise gov.G0GovernanceError(
            "collector outputs differ from the effective attempt authority"
        )
    for path in normalized_outputs:
        state = publisher.path_state_rooted(root, path, label="collector output")
        if state not in {"ABSENT", "FILE"}:
            raise gov.G0GovernanceError(
                "collector output path is an existing non-file"
            )
    audit, audit_record = _direct_json_with_record(
        root, audit_path, label="terminal backend audit"
    )
    reference_payload, _reference_contracts_record = _direct_json_with_record(
        root, reference_contracts_path, label="G0 reference contracts"
    )
    references.validate_reference_contracts(reference_payload, root=root)
    reference_record = _reference_record(
        reference_payload, effective_row["window_id"]
    )
    evidence = build_failure_evidence(
        effective_row,
        audit,
        root=root,
        audit_path=audit_path,
        audit_record=audit_record,
        reference_record=reference_record,
        governance_authority={
            "evaluation_lock_hash": evaluation_lock_hash,
            "backend_execution_lock_hash": execution_lock_hash,
            "g0_execution_authority_hash": authority_hash,
        },
        terminal_provenance=terminal_provenance,
    )
    _publish_or_reconcile_exact(
        root, failure_output, evidence, label="failure evidence"
    )
    evidence_file = publisher.direct_file_record_rooted(
        root, failure_output, label="failure evidence"
    )
    classifier_bindings = [
        item
        for item in lock["code_bindings"]
        if isinstance(item, Mapping)
        and item.get("role") == "planner_classifier_reducer_primitives"
    ]
    if len(classifier_bindings) != 1:
        raise gov.G0GovernanceError("G0 lock does not bind exactly one classifier")
    classification = build_classification(
        evidence,
        evidence_record=evidence_file,
        classifier_record=classifier_bindings[0],
    )
    _publish_or_reconcile_exact(
        root,
        classification_output,
        classification,
        label="failure classification",
    )
    classification_file = publisher.direct_file_record_rooted(
        root, classification_output, label="failure classification"
    )
    core = classification["classification"]
    assert isinstance(core, Mapping)
    trajectory_record = evidence.get("trajectory_artifact")
    config_artifact = _config_artifact(audit, root=root)
    config_record = config_artifact[1] if config_artifact is not None else None
    reference_artifact = reference_record["reference_artifact"]
    assert isinstance(reference_artifact, Mapping)
    artifact_bindings: dict[str, object] = {
        "terminal_audit": audit_record,
        "failure_evidence": evidence_file,
        "classification": classification_file,
        "trajectory": dict(trajectory_record) if isinstance(trajectory_record, Mapping) else None,
        "config": config_record,
        "reference": dict(reference_artifact),
        "g0_evaluation_lock": evaluation_lock_record,
        "backend_execution_lock": execution_lock_record,
    }
    evaluator_bindings = [
        item
        for item in lock["code_bindings"]
        if isinstance(item, Mapping) and item.get("role") == "evaluator"
    ]
    if len(evaluator_bindings) != 1:
        raise gov.G0GovernanceError("G0 lock does not bind exactly one evaluator")
    evaluator_hash = evaluator_bindings[0]["sha256"]
    terminal: dict[str, Any] = {
        "schema_version": gov.TERMINAL_BINDING_SCHEMA,
        "queue_index": int(effective_row["queue_index"]),
        "run_id": effective_row["run_id"],
        "window_id": effective_row["window_id"],
        "arm": effective_row["arm"],
        "replay_index": int(effective_row["replay_index"]),
        "backend_algorithmic_slot": effective_row["algorithmic_slot"],
        "source_run_id": effective_row["source_run_id"],
        "source_provenance_kind": effective_row["source_provenance_kind"],
        "source_provenance_hash": effective_row["source_provenance_hash"],
        "algorithmic_slot": True,
        "terminal": True,
        "evaluation_lock_hash": evaluation_lock_hash,
        "backend_execution_lock_hash": execution_lock_hash,
        "g0_execution_authority_hash": authority_hash,
        "classification": classification,
        "backend_terminal_provenance": terminal_provenance,
        "artifact_bindings": artifact_bindings,
        "reference": reference_record["reference_contract"],
        "reference_contract_hash": reference_record["reference_contract_hash"],
        "arm_time_offset_s": 0.0,
        "evaluator_profile_id": effective_row["evaluator_profile_id"],
        "evaluator_protocol_sha256": effective_row["evaluator_protocol_sha256"],
        "evaluator_script_sha256": evaluator_hash,
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    terminal["terminal_binding_hash"] = gov.canonical_json_hash(terminal)
    # Validate before the third exclusive publication.  Hard failures may lack
    # config/trajectory; the validator handles that schema branch.
    gov.validate_terminal_binding(terminal, root=root, verify_files=True)
    _publish_or_reconcile_exact(
        root, binding_output, terminal, label="terminal binding"
    )
    return evidence, classification, terminal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--evaluation-lock", type=Path, required=True)
    parser.add_argument("--execution-lock", type=Path, required=True)
    parser.add_argument("--terminal-audit", type=Path, required=True)
    parser.add_argument("--reference-contracts", type=Path, required=True)
    parser.add_argument("--failure-output", type=Path)
    parser.add_argument("--classification-output", type=Path)
    parser.add_argument("--binding-output", type=Path)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    _fields, rows = _read_bound_csv(
        args.root, args.queue, label="backend queue"
    )
    matches = [row for row in rows if int(row["queue_index"]) == args.queue_index]
    if len(matches) != 1:
        raise SystemExit("expected exactly one backend queue row")
    lock, _evaluation_lock_record = _direct_json_with_record(
        args.root, args.evaluation_lock, label="G0 evaluation lock"
    )
    evaluation_lock_hash = gov.validate_lock_payload(
        lock, root=args.root, verify_files=True
    )
    frozen = {
        str(record.get("role")): record
        for record in lock["frozen_inputs"]
        if isinstance(record, Mapping)
    }
    for role, observed in (
        ("backend_queue", args.queue),
        ("reference_contracts", args.reference_contracts),
    ):
        record = frozen.get(role)
        if not isinstance(record, Mapping):
            raise SystemExit(f"G0 lock lacks {role}")
        expected = _validate_bound_record(
            args.root, record, label=f"locked {role}"
        )
        observed_path = gov.workspace_path(
            args.root, observed, label=f"collector {role}"
        )
        if observed_path != expected:
            raise SystemExit(f"{role} path differs from frozen G0 lock")
    allocation = frozen.get("backend_allocation")
    if not isinstance(allocation, Mapping):
        raise SystemExit("G0 lock lacks backend allocation")
    allocation_path = _validate_bound_record(
        args.root, allocation, label="locked backend allocation"
    )
    backend.validate_execution_lock(
        args.root,
        args.execution_lock,
        queue_path=args.queue,
        allocation_path=allocation_path,
    )
    execution_lock, _execution_lock_record = _direct_json_with_record(
        args.root, args.execution_lock, label="backend execution lock"
    )
    execution_lock_hash = gov.validate_self_hash(
        execution_lock, "execution_lock_hash", label="backend execution lock"
    )
    authority = execution_lock.get(gov.EXECUTION_LOCK_BINDING_KEY)
    if not isinstance(authority, Mapping):
        raise SystemExit("backend execution lock lacks G0 authority")
    authority_hash = gov.validate_execution_authority_binding(
        authority, root=args.root
    )
    if authority["evaluation_lock"]["evaluation_lock_hash"] != evaluation_lock_hash:
        raise SystemExit("backend execution lock binds a different G0 lock")
    if not args.publish:
        effective_row, terminal_provenance = _controller_terminal_authority(
            matches[0],
            root=args.root,
            audit_path=args.terminal_audit,
            registry_path=lock["mutable_registry_prefix"]["path"],
        )
        audit, audit_record = _direct_json_with_record(
            args.root, args.terminal_audit, label="terminal backend audit"
        )
        refs, _refs_record = _direct_json_with_record(
            args.root, args.reference_contracts, label="reference contracts"
        )
        references.validate_reference_contracts(refs, root=args.root)
        reference_record = _reference_record(refs, effective_row["window_id"])
        evidence = build_failure_evidence(
            effective_row,
            audit,
            root=args.root,
            audit_path=args.terminal_audit,
            audit_record=audit_record,
            reference_record=reference_record,
            governance_authority={
                "evaluation_lock_hash": evaluation_lock_hash,
                "backend_execution_lock_hash": execution_lock_hash,
                "g0_execution_authority_hash": authority_hash,
            },
            terminal_provenance=terminal_provenance,
        )
        print(json.dumps(evidence, indent=2, sort_keys=True))
        return 0
    if any(
        path is None
        for path in (
            args.failure_output,
            args.classification_output,
            args.binding_output,
        )
    ):
        raise SystemExit(
            "--publish requires --failure-output, --classification-output, and --binding-output"
        )
    values = publish_collection(
        matches[0],
        root=args.root,
        queue_path=args.queue,
        evaluation_lock_path=args.evaluation_lock,
        execution_lock_path=args.execution_lock,
        audit_path=args.terminal_audit,
        reference_contracts_path=args.reference_contracts,
        failure_output=args.failure_output,
        classification_output=args.classification_output,
        binding_output=args.binding_output,
    )
    print(json.dumps(values[-1], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
