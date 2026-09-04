#!/usr/bin/env python3
"""Resolve outcome-blind frontend provenance for the unfrozen P07 backend queue.

Most frontend slots are ordinary canonical COMPLETED chains.  Queue 55 is an
explicit additive replacement whose original run remains FAILED, and queue 58
is a preserved physical export closed out after its outer supervisor was lost.
Those two cases must never be silently flattened into the ordinary path.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

try:
    from scripts import p07_g0_publisher_v1 as rooted_io
except ModuleNotFoundError:
    import p07_g0_publisher_v1 as rooted_io  # type: ignore


CANONICAL = "CANONICAL_FRONTEND_COMPLETED_V1"
AUDITOR_CORRECTION = "AUDITOR_ONLY_CORRECTION_CLOSEOUT_V1"
Q55_REPLACEMENT = "Q55_LAYOUT_REPLACEMENT_CLOSEOUT_V1"
Q58_ORPHAN = "Q58_ORPHAN_EXECUTION_CLOSEOUT_V1"

Q55_INDEX = 55
Q58_INDEX = 58
Q55_LOCK = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_replacements/"
    "queue_055_a04_layout_attempt02_lock_v1.json"
)
Q55_REGISTRATION = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_replacements/"
    "queue_055_a04_layout_attempt02_registration_v1.json"
)
Q55_CLOSEOUT = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_replacements/"
    "queue_055_a04_layout_attempt02_closeout_v1.json"
)
Q55_AUDIT = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
    "queue_055_isj_p07_aqualoc_archaeology_a04_0002_p_attempt02/audit_v4.json"
)
Q58_LOCK = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_orphan_recoveries/"
    "queue_058_orphan_closeout_lock_v1.json"
)
Q58_CLOSEOUT = (
    "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
    "queue_058_isj_p07_aqualoc_archaeology_a07_0001_m_attempt01/"
    "orphan_execution_closeout_v1.json"
)

AUDITOR_CORRECTIONS = {
    1: {
        "closeout": (
            "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
            "queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01/"
            "audit_correction_closeout_v2.json"
        ),
        "closeout_schema": "isj-p07-b1-smoke-audit-correction-closeout-v2",
        "lock_schema": "isj-p07-b1-auditor-correction-lock-v2",
    },
    28: {
        "closeout": (
            "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
            "queue_028_isj_p07_afrl_bus_outside_0001_b1_attempt01/"
            "audit_correction_closeout_v4.json"
        ),
        "closeout_schema": "isj-p07-afrl-auditor-correction-closeout-v4",
        "lock_schema": "isj-p07-afrl-replay-manifest-auditor-correction-lock-v4",
    },
}


class ProvenanceError(RuntimeError):
    """A frontend slot cannot be used as an immutable backend input."""


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def provenance_hash(payload: Mapping[str, object]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def document_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return provenance_hash(clone)


def _path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or ".." in pure.parts:
        raise ProvenanceError(f"unsafe provenance path: {relative!r}")
    return root.joinpath(*pure.parts)


def _display(root: Path, path: Path) -> str:
    try:
        return path.absolute().relative_to(root.absolute()).as_posix()
    except ValueError as error:
        raise ProvenanceError(f"provenance file escapes workspace: {path}") from error


def file_record(root: Path, path: Path) -> dict[str, object]:
    try:
        return rooted_io.direct_file_record_bound_input_rooted(
            root, path, label="backend frontend provenance"
        )
    except Exception as error:
        raise ProvenanceError(f"cannot directly record provenance file: {path}") from error


def _json_path(
    root: Path, path: Path, *, label: str
) -> tuple[dict[str, Any], dict[str, object]]:
    try:
        content, record = rooted_io.read_bytes_and_record_bound_input_rooted(
            root, path, label=label
        )
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"invalid provenance JSON: {_display(root, path)}") from error
    except Exception as error:
        raise ProvenanceError(f"cannot directly read provenance JSON: {path}") from error
    if not isinstance(value, dict):
        raise ProvenanceError(f"provenance JSON is not an object: {_display(root, path)}")
    return value, record


def _json(root: Path, relative: str) -> tuple[dict[str, Any], dict[str, object]]:
    path = _path(root, relative)
    return _json_path(root, path, label=f"frontend provenance {relative}")


def registry_chain(
    rows: Sequence[Mapping[str, str]], run_id: str
) -> list[dict[str, str]]:
    chain = [dict(row) for row in rows if row.get("run_id") == run_id]
    if not chain:
        raise ProvenanceError(f"registry lacks frontend run: {run_id}")
    for index, row in enumerate(chain):
        if (
            row.get("registry_event_id") != f"{run_id}_e{index:02d}"
            or row.get("supersedes_event_id")
            != ("" if index == 0 else chain[index - 1]["registry_event_id"])
            or row.get("stage") != "P07_FRONTEND_EXPORT"
        ):
            raise ProvenanceError(f"invalid frontend registry chain: {run_id}")
    return chain


def _validate_audit(
    audit: Mapping[str, Any],
    *,
    queue_row: Mapping[str, str],
    source_run_id: str,
) -> None:
    if (
        audit.get("status") != "PASS"
        or int(audit.get("queue_index", -1)) != int(queue_row["queue_index"])
        or audit.get("run_id") != source_run_id
        or audit.get("window_id") != queue_row["window_id"]
        or audit.get("arm") != queue_row["arm"]
        or audit.get("held_out_trajectory_outcome_read") is not False
        or audit.get("forbidden_outcome_artifacts") != []
    ):
        raise ProvenanceError("frontend audit identity/status/outcome boundary mismatch")


def _output_manifest_record(
    root: Path, terminal: Mapping[str, str]
) -> dict[str, object]:
    relative = str(terminal.get("output_hash_manifest", ""))
    if not relative:
        raise ProvenanceError("COMPLETED frontend event lacks output manifest")
    return file_record(root, _path(root, relative))


def _record_matches(record: object, expected: Mapping[str, object]) -> bool:
    return isinstance(record, dict) and all(
        record.get(field) == expected.get(field)
        for field in ("path", "sha256", "size_bytes")
    )


def _base_payload(
    *,
    kind: str,
    queue_row: Mapping[str, str],
    source_run_id: str,
    chain: Sequence[Mapping[str, str]],
    audit_record: Mapping[str, object],
    output_manifest_record: Mapping[str, object],
    governance_records: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": "isj-p07-backend-frontend-source-provenance-v1",
        "kind": kind,
        "queue_index": int(queue_row["queue_index"]),
        "window_id": queue_row["window_id"],
        "arm": queue_row["arm"],
        "source_run_id": source_run_id,
        "registry_chain": [dict(row) for row in chain],
        "registry_chain_sha256": provenance_hash(
            {"events": [dict(row) for row in chain]}
        ),
        "terminal_registry_event": dict(chain[-1]),
        "audit": dict(audit_record),
        "output_hash_manifest": dict(output_manifest_record),
        "governance_records": [dict(record) for record in governance_records],
        "physical_frontend_rerun": None,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
    }


def resolve_frontend_provenance(
    queue_row: Mapping[str, str],
    allocation: Mapping[str, str],
    registry_rows: Sequence[Mapping[str, str]],
    *,
    root: Path,
    canonical_audit_path: Path,
) -> dict[str, object]:
    index = int(queue_row["queue_index"])
    if allocation.get("run_id") is None:
        raise ProvenanceError("frontend allocation lacks run_id")
    if index == Q55_INDEX:
        return _resolve_q55(queue_row, allocation, registry_rows, root=root)
    if index == Q58_INDEX:
        return _resolve_q58(
            queue_row,
            allocation,
            registry_rows,
            root=root,
            audit_path=canonical_audit_path,
        )

    source_run_id = str(allocation["run_id"])
    chain = registry_chain(registry_rows, source_run_id)
    audit, audit_record = _json_path(
        root, canonical_audit_path, label="canonical frontend audit"
    )
    _validate_audit(audit, queue_row=queue_row, source_run_id=source_run_id)
    output = _output_manifest_record(root, chain[-1])
    statuses = [row.get("status") for row in chain]
    if statuses == ["PLANNED", "RUNNING", "COMPLETED"]:
        kind = CANONICAL
        governance: list[dict[str, object]] = []
        correction_payload: dict[str, object] | None = None
    elif statuses == ["PLANNED", "RUNNING", "FAILED", "COMPLETED"]:
        kind = AUDITOR_CORRECTION
        correction_payload, governance = _auditor_correction(
            queue_row=queue_row,
            source_run_id=source_run_id,
            chain=chain,
            audit_record=audit_record,
            output_record=output,
            root=root,
        )
    else:
        raise ProvenanceError(
            f"unsupported canonical frontend registry chain at queue {index}: {statuses}"
        )
    payload = _base_payload(
        kind=kind,
        queue_row=queue_row,
        source_run_id=source_run_id,
        chain=chain,
        audit_record=audit_record,
        output_manifest_record=output,
        governance_records=governance,
    )
    if correction_payload is not None:
        payload["physical_frontend_rerun"] = False
        payload["auditor_correction"] = correction_payload
    return payload


def _auditor_correction(
    *,
    queue_row: Mapping[str, str],
    source_run_id: str,
    chain: Sequence[Mapping[str, str]],
    audit_record: Mapping[str, object],
    output_record: Mapping[str, object],
    root: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    index = int(queue_row["queue_index"])
    specification = AUDITOR_CORRECTIONS.get(index)
    if specification is None:
        raise ProvenanceError(
            f"unallowlisted FAILED-to-COMPLETED frontend chain: queue {index}"
        )
    closeout, closeout_record = _json(root, str(specification["closeout"]))
    correction_lock_record_raw = closeout.get("correction_lock")
    if not isinstance(correction_lock_record_raw, dict):
        raise ProvenanceError("auditor correction closeout lacks correction lock")
    correction_lock_relative = str(correction_lock_record_raw.get("path", ""))
    correction_lock, correction_lock_record = _json(root, correction_lock_relative)
    if not _record_matches(correction_lock_record_raw, correction_lock_record):
        raise ProvenanceError("auditor correction lock record drift")
    if (
        correction_lock.get("schema_version") != specification["lock_schema"]
        or correction_lock.get("status") != "FROZEN_POST_ATTEMPT_PRE_REAUDIT"
        or correction_lock.get("correction_lock_hash")
        != document_hash(correction_lock, "correction_lock_hash")
        or int(correction_lock.get("queue_index", -1)) != index
        or correction_lock.get("run_id") != source_run_id
        or correction_lock.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ProvenanceError("auditor correction lock identity/hash/boundary mismatch")
    if (
        closeout.get("schema_version") != specification["closeout_schema"]
        or closeout.get("status")
        != "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE"
        or int(closeout.get("queue_index", -1)) != index
        or closeout.get("run_id") != source_run_id
        or closeout.get("physical_frontend_rerun") is not False
        or closeout.get("held_out_trajectory_outcome_read") is not False
        or closeout.get("superseded_registry_event")
        != chain[-2].get("registry_event_id")
        or closeout.get("completion_registry_event")
        != chain[-1].get("registry_event_id")
        or not _record_matches(closeout.get("audit"), audit_record)
        or not _record_matches(closeout.get("output_hash_manifest"), output_record)
    ):
        raise ProvenanceError("auditor correction closeout mismatch")
    return (
        {
            "correction_lock_hash": correction_lock["correction_lock_hash"],
            "superseded_registry_event": chain[-2]["registry_event_id"],
            "completion_registry_event": chain[-1]["registry_event_id"],
            "physical_frontend_rerun": False,
        },
        [correction_lock_record, closeout_record],
    )


def _resolve_q55(
    queue_row: Mapping[str, str],
    allocation: Mapping[str, str],
    registry_rows: Sequence[Mapping[str, str]],
    *,
    root: Path,
) -> dict[str, object]:
    lock, lock_record = _json(root, Q55_LOCK)
    registration, registration_record = _json(root, Q55_REGISTRATION)
    closeout, closeout_record = _json(root, Q55_CLOSEOUT)
    if (
        lock.get("schema_version") != "isj-p07-a04-layout-replacement-lock-v1"
        or lock.get("status") != "FROZEN_READY_FOR_Q55_A04_LAYOUT_ATTEMPT02_RECOVERY"
        or lock.get("replacement_lock_hash")
        != document_hash(lock, "replacement_lock_hash")
        or int(lock.get("original_queue_index", -1)) != Q55_INDEX
        or lock.get("original_run_id") != allocation["run_id"]
        or lock.get("trajectory_outcome_read") is not False
        or lock.get("vins_execution_allowed") is not False
    ):
        raise ProvenanceError("q55 replacement lock identity/hash/boundary mismatch")
    source_run_id = str(lock.get("replacement_run_id", ""))
    if (
        registration.get("schema_version")
        != "isj-p07-frontend-layout-replacement-registration-v1"
        or registration.get("status") != "ALLOCATED"
        or registration.get("replacement_lock_hash") != lock["replacement_lock_hash"]
        or registration.get("original_run_id") != allocation["run_id"]
        or registration.get("replacement_run_id") != source_run_id
        or registration.get("trajectory_outcome_read") is not False
    ):
        raise ProvenanceError("q55 replacement registration mismatch")
    if (
        closeout.get("schema_version")
        != "isj-p07-frontend-layout-replacement-closeout-v1"
        or closeout.get("status") != "PASS"
        or closeout.get("closeout_hash") != document_hash(closeout, "closeout_hash")
        or int(closeout.get("original_queue_index", -1)) != Q55_INDEX
        or closeout.get("original_run_id") != allocation["run_id"]
        or closeout.get("replacement_run_id") != source_run_id
        or closeout.get("replacement_lock_hash") != lock["replacement_lock_hash"]
        or closeout.get("effective_slot_status") != "COMPLETED"
        or closeout.get("physical_frontend_rerun") is not True
        or closeout.get("trajectory_outcome_read") is not False
    ):
        raise ProvenanceError("q55 replacement closeout mismatch")
    original_chain = registry_chain(registry_rows, str(allocation["run_id"]))
    replacement_chain = registry_chain(registry_rows, source_run_id)
    if (
        [row["status"] for row in original_chain] != ["PLANNED", "RUNNING", "FAILED"]
        or [row["status"] for row in replacement_chain]
        != ["PLANNED", "RUNNING", "COMPLETED"]
        or closeout.get("original_final_registry_event") != original_chain[-1]
        or closeout.get("completion_registry_event") != replacement_chain[-1]
    ):
        raise ProvenanceError("q55 original/replacement registry chains mismatch")
    audit, audit_record = _json(root, Q55_AUDIT)
    _validate_audit(audit, queue_row=queue_row, source_run_id=source_run_id)
    closeout_audit = closeout.get("replacement_audit")
    if (
        not isinstance(closeout_audit, dict)
        or closeout_audit.get("path") != audit_record["path"]
        or closeout_audit.get("sha256") != audit_record["sha256"]
    ):
        raise ProvenanceError("q55 closeout/audit binding mismatch")
    output = _output_manifest_record(root, replacement_chain[-1])
    closeout_output = closeout.get("replacement_output_manifest")
    if (
        not isinstance(closeout_output, dict)
        or closeout_output.get("path") != output["path"]
        or closeout_output.get("sha256") != output["sha256"]
    ):
        raise ProvenanceError("q55 closeout/output-manifest binding mismatch")
    payload = _base_payload(
        kind=Q55_REPLACEMENT,
        queue_row=queue_row,
        source_run_id=source_run_id,
        chain=replacement_chain,
        audit_record=audit_record,
        output_manifest_record=output,
        governance_records=(lock_record, registration_record, closeout_record),
    )
    payload["physical_frontend_rerun"] = True
    payload["original_run_id"] = allocation["run_id"]
    payload["original_terminal_registry_event"] = original_chain[-1]
    payload["replacement_lock_hash"] = lock["replacement_lock_hash"]
    payload["replacement_closeout_hash"] = closeout["closeout_hash"]
    return payload


def _resolve_q58(
    queue_row: Mapping[str, str],
    allocation: Mapping[str, str],
    registry_rows: Sequence[Mapping[str, str]],
    *,
    root: Path,
    audit_path: Path,
) -> dict[str, object]:
    lock, lock_record = _json(root, Q58_LOCK)
    closeout, closeout_record = _json(root, Q58_CLOSEOUT)
    source_run_id = str(allocation["run_id"])
    if (
        lock.get("schema_version") != "isj-p07-q58-orphan-closeout-lock-v1"
        or lock.get("status") != "FROZEN_POST_PHYSICAL_COMMAND_PRE_ATTESTATION_AUDIT"
        or lock.get("closeout_lock_hash") != document_hash(lock, "closeout_lock_hash")
        or int(lock.get("queue_index", -1)) != Q58_INDEX
        or lock.get("run_id") != source_run_id
        or lock.get("physical_frontend_rerun") is not False
        or lock.get("trajectory_outcome_read") is not False
        or lock.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ProvenanceError("q58 orphan lock identity/hash/boundary mismatch")
    if (
        closeout.get("schema_version")
        != "isj-p07-q58-orphan-execution-closeout-v1"
        or closeout.get("status")
        != "PASS_COMPLETED_FROM_PRESERVED_ORPHANED_EXECUTION"
        or closeout.get("closeout_hash") != document_hash(closeout, "closeout_hash")
        or int(closeout.get("queue_index", -1)) != Q58_INDEX
        or closeout.get("run_id") != source_run_id
        or closeout.get("orphan_closeout_lock_hash") != lock["closeout_lock_hash"]
        or closeout.get("physical_frontend_rerun") is not False
        or closeout.get("trajectory_outcome_read") is not False
        or closeout.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ProvenanceError("q58 orphan closeout identity/hash/boundary mismatch")
    chain = registry_chain(registry_rows, source_run_id)
    if (
        [row["status"] for row in chain] != ["PLANNED", "RUNNING", "COMPLETED"]
        or closeout.get("completion_registry_event") != chain[-1]
    ):
        raise ProvenanceError("q58 canonical completion chain/closeout mismatch")
    audit, audit_record = _json_path(root, audit_path, label="q58 frontend audit")
    _validate_audit(audit, queue_row=queue_row, source_run_id=source_run_id)
    closeout_audit = closeout.get("audit")
    if (
        not isinstance(closeout_audit, dict)
        or closeout_audit.get("path") != audit_record["path"]
        or closeout_audit.get("sha256") != audit_record["sha256"]
    ):
        raise ProvenanceError("q58 closeout/audit binding mismatch")
    output = _output_manifest_record(root, chain[-1])
    closeout_output = closeout.get("output_hash_manifest")
    if (
        not isinstance(closeout_output, dict)
        or closeout_output.get("path") != output["path"]
        or closeout_output.get("sha256") != output["sha256"]
    ):
        raise ProvenanceError("q58 closeout/output-manifest binding mismatch")
    payload = _base_payload(
        kind=Q58_ORPHAN,
        queue_row=queue_row,
        source_run_id=source_run_id,
        chain=chain,
        audit_record=audit_record,
        output_manifest_record=output,
        governance_records=(lock_record, closeout_record),
    )
    payload["physical_frontend_rerun"] = False
    payload["orphan_closeout_lock_hash"] = lock["closeout_lock_hash"]
    payload["orphan_execution_closeout_hash"] = closeout["closeout_hash"]
    return payload
