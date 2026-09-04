#!/usr/bin/env python3
"""Allocate one immutable P07 infrastructure replacement, fail closed.

The allocator never changes an algorithmic slot.  It derives an effective row
from the frozen queue and may override only the run identity and output target
fields frozen by ``backend_replacement_contract_v1.json``.  The default mode is
read-only preflight; ``--apply`` is required for the no-clobber replacement
lock, append-only allocation index, and canonical PLANNED e00 registry row.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import build_p07_backend_replacement_contract_v1 as contract
    from scripts import build_p07_backend_replay_queue_v1 as queue_builder
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import register_p07_backend_allocations_v1 as registration
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_replacement_contract_v1 as contract  # type: ignore
    import build_p07_backend_replay_queue_v1 as queue_builder  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import register_p07_backend_allocations_v1 as registration  # type: ignore


SCHEMA = contract.LOCK_SCHEMA
STATUS = contract.LOCK_STATUS
SELF_HASH_FIELD = "replacement_lock_hash"
INDEX_FIELDS = [
    "schema_version",
    "allocation_index",
    "event_id",
    "previous_event_hash",
    "event_hash",
    "allocated_at",
    "queue_index",
    "algorithmic_slot",
    "root_queue_run_id",
    "failed_run_id",
    "replacement_for",
    "run_id",
    "attempt_number",
    "runner_tag",
    "expected_run_dir",
    "expected_attempt_dir",
    "failure_evidence_path",
    "failure_evidence_sha256",
    "execution_lock_hash",
    "replacement_contract_hash",
    "replacement_lock_path",
    "replacement_lock_sha256",
    "status",
    "outcome_boundary",
]
INDEX_STATUS = "ALLOCATED"
OUTCOME_BOUNDARY = "INFRASTRUCTURE_ONLY_ALGORITHMIC_SLOT_UNCONSUMED"
_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,239}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MANIFEST_LINE_RE = re.compile(r"^([0-9a-f]{64})  ([^\n]+)$")
INFRASTRUCTURE_EVIDENCE_SCHEMA = (
    "isj-p07-backend-infrastructure-failure-evidence-v2"
)


class ReplacementAllocationError(RuntimeError):
    """The requested replacement is unsafe, stale, or already consumed."""


@dataclass(frozen=True)
class ReplacementPlan:
    replacement_lock_path: Path
    replacement_lock_payload: dict[str, object]
    replacement_lock_bytes: bytes
    index_row: dict[str, str]
    registry_row: dict[str, str]
    existing_exact_allocation: bool = False


def replacement_lock_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop(SELF_HASH_FIELD, None)
    return hashlib.sha256(
        queue_builder.canonical_json(clone).encode("utf-8")
    ).hexdigest()


def row_hash(row: Mapping[str, str]) -> str:
    return hashlib.sha256(
        queue_builder.canonical_json(dict(row)).encode("utf-8")
    ).hexdigest()


def immutable_row_hash(row: Mapping[str, str]) -> str:
    immutable = {
        key: value
        for key, value in row.items()
        if key not in contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES
    }
    return row_hash(immutable)


def index_event_hash(row: Mapping[str, str]) -> str:
    clone = dict(row)
    clone.pop("event_hash", None)
    return row_hash(clone)


def _attempt_suffix(attempt_number: int) -> str:
    if attempt_number < 2 or attempt_number > 99:
        raise ReplacementAllocationError("replacement attempt must be in [2, 99]")
    return f"attempt{attempt_number:02d}"


def lock_relative_path(queue_index: int, attempt_number: int) -> str:
    suffix = _attempt_suffix(attempt_number)
    return (
        "papers/ieee_sensors_journal_experiments/p07/backend_replacements/"
        f"queue_{queue_index:03d}_{suffix}_replacement_lock_v1.json"
    )


def build_effective_row(
    base_row: Mapping[str, str], *, attempt_number: int
) -> dict[str, str]:
    suffix = _attempt_suffix(attempt_number)
    if not base_row.get("expected_attempt_dir", "").endswith("_attempt01"):
        raise ReplacementAllocationError("base attempt target lacks _attempt01 suffix")
    run_id = f"{base_row['run_id']}_infra_{suffix}"
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ReplacementAllocationError("replacement run_id is not safe or is too long")
    effective = dict(base_row)
    effective.update(
        {
            "run_id": run_id,
            "runner_tag": f"{base_row['runner_tag']}_{suffix}",
            "expected_run_dir": f"{base_row['expected_run_dir']}_{suffix}",
            "expected_attempt_dir": (
                f"{base_row['expected_attempt_dir'][:-len('_attempt01')]}_{suffix}"
            ),
        }
    )
    changed = {key for key in base_row if effective[key] != base_row[key]}
    if changed != set(contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES):
        raise ReplacementAllocationError(
            f"effective row changed an unexpected field set: {sorted(changed)}"
        )
    if immutable_row_hash(effective) != immutable_row_hash(base_row):
        raise ReplacementAllocationError("effective row changed frozen scientific fields")
    return effective


def exact_job_argv(queue_index: int, replacement_lock_relative: str) -> list[str]:
    return [
        "python3",
        "scripts/run_p07_backend_replay_job_v1.py",
        "--queue-index",
        str(queue_index),
        "--execution-lock",
        common.DEFAULT_EXECUTION_LOCK_RELATIVE,
        "--replacement-lock",
        replacement_lock_relative,
    ]


def _file_record(path: Path, *, root: Path) -> dict[str, object]:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise ReplacementAllocationError(f"artifact is outside workspace: {path}") from error
    return {
        "path": relative,
        "sha256": common.sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_evidence_record(
    record: Mapping[str, object], *, root: Path, label: str
) -> Path:
    try:
        raw = str(record["path"])
        digest = str(record["sha256"])
        size = int(record["size_bytes"])
    except (KeyError, TypeError, ValueError) as error:
        raise ReplacementAllocationError(f"invalid {label} record") from error
    if size < 0 or not _SHA256_RE.fullmatch(digest):
        raise ReplacementAllocationError(f"invalid {label} SHA/size")
    path = common.workspace_path(root, raw, label=label)
    if path.is_symlink() or path.stat().st_size != size or common.sha256(path) != digest:
        raise ReplacementAllocationError(f"{label} record drift")
    return path


def parse_hash_manifest(path: Path, *, root: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    parsed: dict[str, str] = {}
    previous = ""
    for line in lines:
        match = _MANIFEST_LINE_RE.fullmatch(line)
        if match is None:
            raise ReplacementAllocationError(f"malformed hash manifest: {path}")
        digest, raw = match.groups()
        if raw in parsed or raw <= previous:
            raise ReplacementAllocationError(f"unsorted/duplicate hash manifest: {path}")
        target = common.workspace_path(root, raw, label="hash-manifest target")
        if common.sha256(target) != digest:
            raise ReplacementAllocationError(f"hash-manifest target drift: {raw}")
        parsed[raw] = digest
        previous = raw
    if not parsed:
        raise ReplacementAllocationError(f"empty hash manifest: {path}")
    return parsed


def validate_infrastructure_evidence_bundle(
    payload: Mapping[str, object],
    *,
    evidence_path: Path,
    source_registry_event: Mapping[str, str],
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
) -> dict[str, object]:
    records: dict[str, tuple[Path, Mapping[str, object]]] = {}
    for field in (
        "input_hash_manifest",
        "failure_output_precommit",
        "attempt_intent",
        "attempt_state_journal",
    ):
        record = payload.get(field)
        if not isinstance(record, dict):
            raise ReplacementAllocationError(f"infrastructure evidence lacks {field}")
        records[field] = (
            _validate_evidence_record(record, root=root, label=field),
            record,
        )
    adapter_record = payload.get("adapter_result")
    pre_adapter_without_result = payload.get("pre_adapter_without_result_proven") is True
    if adapter_record is None:
        if (
            not pre_adapter_without_result
            or payload.get("failure_phase") not in {"PRE_ADAPTER", "ADAPTER_RUNNING"}
            or payload.get("boundary_may_have_been_crossed") is not False
            or payload.get("active_recorded_process") is not False
        ):
            raise ReplacementAllocationError(
                "missing adapter result lacks exact pre-adapter proof"
            )
    elif isinstance(adapter_record, dict):
        records["adapter_result"] = (
            _validate_evidence_record(
                adapter_record, root=root, label="adapter_result"
            ),
            adapter_record,
        )
        adapter_result = json.loads(
            records["adapter_result"][0].read_text(encoding="utf-8")
        )
        if (
            not isinstance(adapter_result, dict)
            or adapter_result.get("status")
            not in {"FAIL_GOVERNANCE", "FAIL_INPUT_IMMUTABILITY"}
            or adapter_result.get("replay_started") is not False
            or adapter_result.get("evaluation_invoked") is not False
        ):
            raise ReplacementAllocationError(
                "adapter result is not pre-slot infrastructure"
            )
    else:
        raise ReplacementAllocationError("invalid nullable adapter-result record")
    try:
        intent_payload = json.loads(
            records["attempt_intent"][0].read_text(encoding="utf-8")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReplacementAllocationError("invalid attempt-intent JSON") from error
    if (
        not isinstance(intent_payload, dict)
        or intent_payload.get("schema_version")
        != "isj-p07-backend-attempt-intent-v1"
        or intent_payload.get("status") != "CLAIMED_NO_REPLAY_STARTED"
        or intent_payload.get("attempt_intent_hash")
        != common.canonical_json_hash(intent_payload, "attempt_intent_hash")
        or intent_payload.get("queue_index") != int(payload.get("queue_index", -1))
        or intent_payload.get("run_id") != payload.get("run_id")
        or intent_payload.get("replay_started") is not False
        or intent_payload.get("algorithmic_slot_consumed") is not False
    ):
        raise ReplacementAllocationError("attempt intent identity/self-hash drift")
    try:
        execution_payload = json.loads(execution_lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReplacementAllocationError("invalid bound backend execution lock") from error
    g0_authority = (
        execution_payload.get(common.g0_governance.EXECUTION_LOCK_BINDING_KEY)
        if isinstance(execution_payload, dict)
        else None
    )
    if not isinstance(g0_authority, dict) or not isinstance(
        g0_authority.get("evaluation_lock"), dict
    ) or (
        intent_payload.get("g0_execution_authority_hash")
        != g0_authority.get("g0_execution_authority_hash")
        or intent_payload.get("g0_evaluation_lock_hash")
        != g0_authority["evaluation_lock"].get("evaluation_lock_hash")
    ):
        raise ReplacementAllocationError("attempt intent G0 authority binding drift")
    creator = intent_payload.get("creator_process")
    if (
        not isinstance(creator, dict)
        or set(creator) != {"pid", "starttime_ticks", "cmdline_sha256"}
        or not isinstance(creator.get("pid"), int)
        or int(creator["pid"]) <= 0
        or not isinstance(creator.get("starttime_ticks"), int)
        or int(creator["starttime_ticks"]) <= 0
        or not isinstance(creator.get("cmdline_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", str(creator["cmdline_sha256"]))
    ):
        raise ReplacementAllocationError("attempt intent creator identity drift")
    state_events = common.read_hash_chain_jsonl(records["attempt_state_journal"][0])
    if not state_events:
        raise ReplacementAllocationError(
            "attempt-state journal does not prove the replay boundary untouched"
        )
    try:
        state_analysis = common.analyze_attempt_state_events(
            state_events,
            queue_index=int(payload.get("queue_index", -1)),
            run_id=str(payload.get("run_id", "")),
        )
    except common.BackendReplayViolation as error:
        raise ReplacementAllocationError(
            f"attempt-state journal semantic drift: {error}"
        ) from error
    if (
        state_analysis["boundary_may_have_been_crossed"]
        or state_analysis["unpaired_launch_pending"]
    ):
        raise ReplacementAllocationError(
            "attempt-state journal does not prove the replay boundary untouched"
        )
    if state_analysis["active_processes"]:
        raise ReplacementAllocationError("attempt-state journal names a live process")
    input_entries = parse_hash_manifest(records["input_hash_manifest"][0], root=root)
    for required in (queue_path, allocation_path, execution_lock_path):
        relative = common.display_path(root, required)
        if input_entries.get(relative) != common.sha256(required):
            raise ReplacementAllocationError(
                f"input manifest does not bind required control artifact: {relative}"
            )
    precommit_entries = parse_hash_manifest(
        records["failure_output_precommit"][0], root=root
    )
    precommit_fields = [
        "input_hash_manifest",
        "attempt_intent",
        "attempt_state_journal",
    ]
    if "adapter_result" in records:
        precommit_fields.append("adapter_result")
    for field in precommit_fields:
        record = records[field][1]
        if precommit_entries.get(str(record["path"])) != record["sha256"]:
            raise ReplacementAllocationError(
                f"failure precommit does not bind {field}"
            )
    final_raw = source_registry_event.get("output_hash_manifest", "")
    if not final_raw:
        raise ReplacementAllocationError("registry terminal event lacks final manifest")
    final_path = common.workspace_path(
        root, final_raw, label="infrastructure output manifest"
    )
    final_entries = parse_hash_manifest(final_path, root=root)
    evidence_record = _file_record(evidence_path, root=root)
    precommit_record = records["failure_output_precommit"][1]
    for record, label in (
        (evidence_record, "infrastructure evidence"),
        (precommit_record, "failure precommit"),
    ):
        if final_entries.get(str(record["path"])) != record["sha256"]:
            raise ReplacementAllocationError(
                f"final infrastructure manifest does not bind {label}"
            )
    return {
        "adapter_result": (
            dict(records["adapter_result"][1])
            if "adapter_result" in records
            else None
        ),
        "input_hash_manifest": dict(records["input_hash_manifest"][1]),
        "failure_output_precommit": dict(precommit_record),
        "attempt_intent": dict(records["attempt_intent"][1]),
        "attempt_state_journal": dict(records["attempt_state_journal"][1]),
        "infrastructure_output_hash_manifest": _file_record(final_path, root=root),
    }


def build_registry_row(
    base_registry_e00: Mapping[str, str],
    effective_row: Mapping[str, str],
    *,
    allocated_at: str,
    replacement_for: str,
    replacement_lock_relative: str,
    execution_lock_hash: str,
    replacement_contract_hash: str,
    registry_fields: Sequence[str],
) -> dict[str, str]:
    queue_builder.allocation_stamp(allocated_at)
    required = {
        "run_id",
        "registry_event_id",
        "recorded_at",
        "supersedes_event_id",
        "status",
        "replacement_for",
        "run_dir",
        "command_file",
        "input_hash_manifest",
        "output_hash_manifest",
        "infrastructure_failure",
        "notes",
    }
    if required.difference(registry_fields):
        raise ReplacementAllocationError("canonical registry lacks replacement fields")
    row = {field: base_registry_e00.get(field, "") for field in registry_fields}
    row.update(
        {
            "run_id": effective_row["run_id"],
            "registry_event_id": f"{effective_row['run_id']}_e00",
            "recorded_at": allocated_at,
            "supersedes_event_id": "",
            "status": "PLANNED",
            "replacement_for": replacement_for,
            "run_dir": effective_row["expected_run_dir"],
            "command_file": replacement_lock_relative,
            "input_hash_manifest": replacement_lock_relative,
            "output_hash_manifest": "",
            "infrastructure_failure": "",
            "notes": (
                f"P07 infrastructure replacement; queue_index={effective_row['queue_index']}; "
                f"algorithmic_slot={effective_row['algorithmic_slot']}; "
                f"replacement_for={replacement_for}; "
                f"execution_lock_hash={execution_lock_hash}; "
                f"replacement_contract_hash={replacement_contract_hash}; "
                "trajectory outcome unread at replacement allocation"
            ),
        }
    )
    for field in (
        "replay_evaluable",
        "replay_hard_failure",
        "window_arm_hard_failure",
        "any_repeat_hard_failure",
        "init_failure",
        "full_coverage",
        "algorithm_hard_failure",
        "solver_risk",
        "window_arm_solver_risk",
        "queue_drop_rate",
        "sustained_queue_drop",
    ):
        if field in row:
            row[field] = "false" if field == "replay_evaluable" else ""
    exact = {
        "stage": "P07_BACKEND_REPLAY",
        "dataset_family": effective_row["dataset_family"],
        "sequence": effective_row["sequence"],
        "arm": effective_row["arm"],
        "backend_replay": effective_row["algorithmic_slot"],
    }
    differences = {
        key: {"expected": value, "observed": row.get(key)}
        for key, value in exact.items()
        if row.get(key) != value
    }
    if differences:
        raise ReplacementAllocationError(
            f"base registry row differs from frozen queue slot: {differences}"
        )
    return row


def build_replacement_lock_payload(
    *,
    allocated_at: str,
    allocation_index: int,
    attempt_number: int,
    base_row: Mapping[str, str],
    effective_row: Mapping[str, str],
    replacement_for: str,
    replacement_lock_relative: str,
    failure_evidence_record: Mapping[str, object],
    failure_evidence_payload: Mapping[str, object],
    infrastructure_evidence_bundle: Mapping[str, object],
    source_registry_event: Mapping[str, str],
    registry_planned_event: Mapping[str, str],
    queue_record: Mapping[str, object],
    allocation_record: Mapping[str, object],
    base_allocation: Mapping[str, str],
    allocation_index_prefix: Mapping[str, object],
    execution_lock_record: Mapping[str, object],
    execution_lock_hash: str,
    contract_record: Mapping[str, object],
    replacement_contract_hash: str,
) -> dict[str, object]:
    queue_builder.allocation_stamp(allocated_at)
    if int(base_row["queue_index"]) <= 0:
        raise ReplacementAllocationError("invalid base queue index")
    if effective_row["run_id"] == base_row["run_id"]:
        raise ReplacementAllocationError("replacement must use a new run_id")
    if immutable_row_hash(base_row) != immutable_row_hash(effective_row):
        raise ReplacementAllocationError("replacement changed immutable queue fields")
    argv = exact_job_argv(int(base_row["queue_index"]), replacement_lock_relative)
    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "allocated_at": allocated_at,
        "allocation_index": allocation_index,
        "attempt_number": attempt_number,
        "queue_index": int(base_row["queue_index"]),
        "algorithmic_slot": base_row["algorithmic_slot"],
        "root_queue_run_id": base_row["run_id"],
        "failed_run_id": replacement_for,
        "replacement_for": replacement_for,
        "base_queue_row": dict(base_row),
        "base_queue_row_sha256": row_hash(base_row),
        "frozen_queue": dict(queue_record),
        "base_allocation_row": dict(base_allocation),
        "base_allocation_row_sha256": row_hash(base_allocation),
        "frozen_allocation": dict(allocation_record),
        "effective_queue_row": dict(effective_row),
        "effective_queue_row_sha256": row_hash(effective_row),
        "immutable_queue_fields_sha256": immutable_row_hash(base_row),
        "effective_row_overrides": {
            key: effective_row[key]
            for key in contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES
        },
        "allowed_effective_row_overrides": list(
            contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES
        ),
        "source_failure_evidence": {
            **dict(failure_evidence_record),
            "schema_version": failure_evidence_payload.get("schema_version"),
            "failure_class": failure_evidence_payload.get("failure_class"),
            "failure_code": failure_evidence_payload.get("failure_code"),
            "infrastructure_category": failure_evidence_payload.get(
                "infrastructure_category"
            ),
            "failure_phase": failure_evidence_payload.get("failure_phase"),
            "status": failure_evidence_payload.get("status"),
            "replacement_eligible": failure_evidence_payload.get(
                "replacement_eligible"
            ),
            "infrastructure_failure": failure_evidence_payload.get(
                "infrastructure_failure"
            ),
            "algorithmic_slot_consumed": failure_evidence_payload.get(
                "algorithmic_slot_consumed"
            ),
            "slot_consumption_boundary_crossed": failure_evidence_payload.get(
                "slot_consumption_boundary_crossed"
            ),
            "trajectory_outcome_read": failure_evidence_payload.get(
                "trajectory_outcome_read"
            ),
            "evaluation_invoked": failure_evidence_payload.get(
                "evaluation_invoked"
            ),
            "audit_artifact_created": failure_evidence_payload.get(
                "audit_artifact_created"
            ),
            "pre_adapter_without_result_proven": failure_evidence_payload.get(
                "pre_adapter_without_result_proven"
            ),
            "boundary_may_have_been_crossed": failure_evidence_payload.get(
                "boundary_may_have_been_crossed"
            ),
            "active_recorded_process": failure_evidence_payload.get(
                "active_recorded_process"
            ),
            "orphan_reconciled": failure_evidence_payload.get("orphan_reconciled"),
        },
        "infrastructure_evidence_bundle": dict(infrastructure_evidence_bundle),
        "source_registry_terminal_event": {
            "run_id": source_registry_event["run_id"],
            "registry_event_id": source_registry_event["registry_event_id"],
            "status": source_registry_event["status"],
            "infrastructure_failure": source_registry_event[
                "infrastructure_failure"
            ],
            "event_sha256": row_hash(source_registry_event),
        },
        "registry_planned_event": dict(registry_planned_event),
        "registry_planned_event_sha256": row_hash(registry_planned_event),
        "execution_lock": {
            **dict(execution_lock_record),
            "execution_lock_hash": execution_lock_hash,
        },
        "replacement_contract": {
            **dict(contract_record),
            "replacement_contract_hash": replacement_contract_hash,
        },
        "allocation_index": {
            "schema_version": contract.INDEX_SCHEMA,
            "path": queue_builder.display_path(contract.INDEX_PATH),
            "append_only": True,
            "previous_prefix": dict(allocation_index_prefix),
        },
        "job_argv": argv,
        "job_argv_sha256": common.sha256_bytes(
            queue_builder.canonical_json(argv).encode("utf-8")
        ),
        "single_use_via_untouched_planned_e00": True,
        "trajectory_outcome_read_at_allocation": False,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    payload[SELF_HASH_FIELD] = replacement_lock_hash(payload)
    return payload


def validate_replacement_lock_payload(
    payload: Mapping[str, object], *, expected_relative_path: str | None = None
) -> None:
    if (
        payload.get("schema_version") != SCHEMA
        or payload.get("status") != STATUS
        or payload.get(SELF_HASH_FIELD) != replacement_lock_hash(payload)
        or payload.get("trajectory_outcome_read_at_allocation") is not False
    ):
        raise ReplacementAllocationError("replacement lock schema/status/hash mismatch")
    base = payload.get("base_queue_row")
    effective = payload.get("effective_queue_row")
    if not isinstance(base, dict) or not isinstance(effective, dict):
        raise ReplacementAllocationError("replacement lock lacks queue rows")
    if payload.get("base_queue_row_sha256") != row_hash(base):
        raise ReplacementAllocationError("replacement base-row hash mismatch")
    if payload.get("effective_queue_row_sha256") != row_hash(effective):
        raise ReplacementAllocationError("replacement effective-row hash mismatch")
    if payload.get("immutable_queue_fields_sha256") != immutable_row_hash(base):
        raise ReplacementAllocationError("replacement immutable-row hash mismatch")
    if immutable_row_hash(base) != immutable_row_hash(effective):
        raise ReplacementAllocationError("replacement changed scientific queue fields")
    changed = {key for key in base if base.get(key) != effective.get(key)}
    if changed != set(contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES):
        raise ReplacementAllocationError("replacement effective override set mismatch")
    overrides = payload.get("effective_row_overrides")
    if not isinstance(overrides, dict) or overrides != {
        key: effective[key] for key in contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES
    }:
        raise ReplacementAllocationError("replacement override values mismatch")
    if payload.get("registry_planned_event_sha256") != row_hash(
        payload.get("registry_planned_event", {})  # type: ignore[arg-type]
    ):
        raise ReplacementAllocationError("replacement registry e00 hash mismatch")
    allocation = payload.get("base_allocation_row")
    if (
        not isinstance(allocation, dict)
        or payload.get("base_allocation_row_sha256") != row_hash(allocation)
        or allocation.get("queue_index") != base.get("queue_index")
        or allocation.get("run_id") != base.get("run_id")
        or allocation.get("algorithmic_slot") != base.get("algorithmic_slot")
    ):
        raise ReplacementAllocationError("replacement base allocation binding mismatch")
    for field in ("frozen_queue", "frozen_allocation"):
        record = payload.get(field)
        if (
            not isinstance(record, dict)
            or not _SHA256_RE.fullmatch(str(record.get("sha256", "")))
            or int(record.get("size_bytes", -1)) < 0
        ):
            raise ReplacementAllocationError(f"replacement lacks {field} binding")
    failure = payload.get("source_failure_evidence")
    if (
        not isinstance(failure, dict)
        or failure.get("failure_class") != "INFRASTRUCTURE"
        or failure.get("status") != "REPLACEMENT_ELIGIBLE"
        or failure.get("replacement_eligible") is not True
        or failure.get("infrastructure_category")
        not in contract.ALLOWED_INFRASTRUCTURE_FAILURE_CODES
        or failure.get("infrastructure_failure") is not True
        or failure.get("algorithmic_slot_consumed") is not False
        or failure.get("slot_consumption_boundary_crossed") is not False
        or failure.get("trajectory_outcome_read") is not False
        or failure.get("evaluation_invoked") is not False
        or failure.get("audit_artifact_created") is not False
        or not _SHA256_RE.fullmatch(str(failure.get("sha256", "")))
    ):
        raise ReplacementAllocationError("replacement lacks exact infrastructure evidence")
    attempt_number = int(payload.get("attempt_number", 0))
    source_attempt = attempt_number - 1
    if source_attempt == 1:
        source_attempt_dir = str(base.get("expected_attempt_dir", ""))
    else:
        source_attempt_dir = (
            f"{str(base.get('expected_attempt_dir', ''))[:-len('_attempt01')]}_"
            f"attempt{source_attempt:02d}"
        )
    if failure.get("path") != f"{source_attempt_dir}/infrastructure_failure_evidence_v2.json":
        raise ReplacementAllocationError("replacement failure-evidence path mismatch")
    if payload.get("root_queue_run_id") != base.get("run_id"):
        raise ReplacementAllocationError("replacement root queue run mismatch")
    if payload.get("failed_run_id") != payload.get("replacement_for"):
        raise ReplacementAllocationError("replacement failed-run parent mismatch")
    terminal = payload.get("source_registry_terminal_event")
    if (
        not isinstance(terminal, dict)
        or terminal.get("run_id") != payload.get("failed_run_id")
        or terminal.get("status") != "FAILED"
        or terminal.get("infrastructure_failure") != "true"
        or not _SHA256_RE.fullmatch(str(terminal.get("event_sha256", "")))
    ):
        raise ReplacementAllocationError("replacement terminal registry binding mismatch")
    bundle = payload.get("infrastructure_evidence_bundle")
    if not isinstance(bundle, dict) or set(bundle) != {
        "adapter_result",
        "input_hash_manifest",
        "failure_output_precommit",
        "attempt_intent",
        "attempt_state_journal",
        "infrastructure_output_hash_manifest",
    }:
        raise ReplacementAllocationError("replacement evidence bundle is incomplete")
    for name, record in bundle.items():
        if name == "adapter_result" and record is None:
            continue
        if (
            not isinstance(record, dict)
            or not _SHA256_RE.fullmatch(str(record.get("sha256", "")))
            or int(record.get("size_bytes", -1)) < 0
        ):
            raise ReplacementAllocationError("replacement evidence record is invalid")
    if bundle.get("adapter_result") is None and (
        failure.get("failure_phase") not in {"PRE_ADAPTER", "ADAPTER_RUNNING"}
        or failure.get("pre_adapter_without_result_proven") is not True
        or failure.get("boundary_may_have_been_crossed") is not False
        or failure.get("active_recorded_process") is not False
    ):
        raise ReplacementAllocationError(
            "replacement adapter-free evidence lacks frozen pre-adapter proof"
        )
    index = payload.get("allocation_index")
    prefix = index.get("previous_prefix") if isinstance(index, dict) else None
    if (
        not isinstance(prefix, dict)
        or prefix.get("path")
        != queue_builder.display_path(contract.INDEX_PATH)
        or not _SHA256_RE.fullmatch(str(prefix.get("sha256", "")))
        or int(prefix.get("size_bytes", -1)) < 0
    ):
        raise ReplacementAllocationError("replacement allocation-index prefix is invalid")
    relative = expected_relative_path
    if relative is None:
        job = payload.get("job_argv")
        if not isinstance(job, list) or len(job) < 2:
            raise ReplacementAllocationError("replacement lock lacks job argv")
        try:
            relative = str(job[job.index("--replacement-lock") + 1])
        except (ValueError, IndexError) as error:
            raise ReplacementAllocationError("replacement job lacks lock flag") from error
    expected = exact_job_argv(int(payload["queue_index"]), relative)
    if payload.get("job_argv") != expected or payload.get("job_argv_sha256") != (
        common.sha256_bytes(queue_builder.canonical_json(expected).encode("utf-8"))
    ):
        raise ReplacementAllocationError("replacement job argv drift")


def _read_direct_or_absent(path: Path) -> bytes | None:
    try:
        path_info = os.lstat(path)
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(path_info.st_mode):
        raise ReplacementAllocationError(f"formal stream is not direct regular: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_dev != path_info.st_dev or info.st_ino != path_info.st_ino:
            raise ReplacementAllocationError(f"formal stream identity drift: {path}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def read_index(path: Path) -> list[dict[str, str]]:
    content = _read_direct_or_absent(path)
    if content is None:
        return []
    with io.StringIO(content.decode("utf-8"), newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if fields != INDEX_FIELDS or any(None in row for row in rows):
        raise ReplacementAllocationError("replacement allocation index is malformed")
    for position, row in enumerate(rows, 1):
        expected_previous = "" if position == 1 else rows[position - 2]["event_hash"]
        if (
            row["schema_version"] != contract.INDEX_SCHEMA
            or int(row["allocation_index"]) != position
            or row["event_id"] != f"p07_backend_replacement_a{position:04d}"
            or row["previous_event_hash"] != expected_previous
            or row["event_hash"] != index_event_hash(row)
            or row["status"] != INDEX_STATUS
            or not _SHA256_RE.fullmatch(row["replacement_lock_sha256"])
        ):
            raise ReplacementAllocationError("replacement allocation index chain drift")
    return rows


def index_prefix_snapshot(path: Path) -> dict[str, object]:
    content = _read_direct_or_absent(path)
    if content is None:
        content = b""
    return {
        "path": queue_builder.display_path(contract.INDEX_PATH),
        "sha256": common.sha256_bytes(content),
        "size_bytes": len(content),
    }


def _registry_chains(
    rows: Sequence[Mapping[str, str]],
) -> dict[str, list[Mapping[str, str]]]:
    chains: dict[str, list[Mapping[str, str]]] = {}
    for row in rows:
        chains.setdefault(row["run_id"], []).append(row)
    for run_id, chain in chains.items():
        for index, row in enumerate(chain):
            if (
                row["registry_event_id"] != f"{run_id}_e{index:02d}"
                or row["supersedes_event_id"]
                != ("" if index == 0 else chain[index - 1]["registry_event_id"])
            ):
                raise ReplacementAllocationError(f"invalid registry chain for {run_id}")
    return chains


def _slot_identity(row: Mapping[str, str]) -> tuple[str, ...]:
    return (
        "P07_BACKEND_REPLAY",
        row["dataset_family"],
        row["sequence"],
        row["window_start_s"],
        row["window_end_s"],
        row["arm"],
        row["algorithmic_slot"],
    )


def _registry_slot_identity(row: Mapping[str, str]) -> tuple[str, ...]:
    return (
        row.get("stage", ""),
        row.get("dataset_family", ""),
        row.get("sequence", ""),
        row.get("window_start", ""),
        row.get("window_end", ""),
        row.get("arm", ""),
        row.get("backend_replay", ""),
    )


def validate_failure_evidence(
    payload: Mapping[str, object],
    *,
    queue_index: int,
    failed_run_id: str,
) -> None:
    if (
        payload.get("schema_version")
        != INFRASTRUCTURE_EVIDENCE_SCHEMA
        or payload.get("status") != "REPLACEMENT_ELIGIBLE"
        or int(payload.get("queue_index", -1)) != queue_index
        or payload.get("run_id") != failed_run_id
        or payload.get("failure_class") != "INFRASTRUCTURE"
        or payload.get("infrastructure_category")
        not in contract.ALLOWED_INFRASTRUCTURE_FAILURE_CODES
        or payload.get("infrastructure_failure") is not True
        or payload.get("replacement_eligible") is not True
        or payload.get("algorithmic_slot_consumed") is not False
        or payload.get("slot_consumption_boundary_crossed") is not False
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("evaluation_invoked") is not False
        or payload.get("audit_artifact_created") is not False
        or payload.get("failure_phase")
        not in {"PRE_ADAPTER", "ADAPTER_RUNNING", "ADAPTER_RETURNED"}
        or payload.get("failure_code") != "EXECUTION_ENVELOPE_FAILURE"
    ):
        raise ReplacementAllocationError("failure evidence is not replacement-eligible")
    adapter_record = payload.get("adapter_result")
    if adapter_record is None:
        if (
            payload.get("failure_phase") not in {"PRE_ADAPTER", "ADAPTER_RUNNING"}
            or payload.get("pre_adapter_without_result_proven") is not True
            or payload.get("boundary_may_have_been_crossed") is not False
            or payload.get("active_recorded_process") is not False
            or not isinstance(payload.get("attempt_intent"), dict)
            or not isinstance(payload.get("attempt_state_journal"), dict)
        ):
            raise ReplacementAllocationError(
                "adapter-free infrastructure evidence lacks durable pre-adapter proof"
            )
    elif not isinstance(adapter_record, dict):
        raise ReplacementAllocationError("invalid adapter-result evidence record")


def _validate_slot_unconsumed(
    base_row: Mapping[str, str],
    *,
    failed_run_id: str,
    index_rows: Sequence[Mapping[str, str]],
    registry_rows: Sequence[Mapping[str, str]],
) -> tuple[Mapping[str, str], Mapping[str, str]]:
    relevant_index = [
        row for row in index_rows if row["queue_index"] == base_row["queue_index"]
    ]
    attempts = [int(row["attempt_number"]) for row in relevant_index]
    if attempts != list(range(2, 2 + len(attempts))):
        raise ReplacementAllocationError("replacement attempts are not contiguous")
    expected_parent = base_row["run_id"]
    for attempt, item in zip(attempts, relevant_index):
        if (
            item["root_queue_run_id"] != base_row["run_id"]
            or item["algorithmic_slot"] != base_row["algorithmic_slot"]
            or item["failed_run_id"] != expected_parent
            or item["replacement_for"] != expected_parent
            or not item["run_id"].endswith(f"_infra_attempt{attempt:02d}")
        ):
            raise ReplacementAllocationError("replacement allocation chain branched")
        expected_parent = item["run_id"]
    authorized = [base_row["run_id"], *[row["run_id"] for row in relevant_index]]
    expected_source = authorized[-1]
    if failed_run_id != expected_source:
        raise ReplacementAllocationError(
            f"replacement source is not latest authorized attempt: {failed_run_id} != {expected_source}"
        )
    chains = _registry_chains(registry_rows)
    base_chain = chains.get(base_row["run_id"], [])
    if not base_chain:
        raise ReplacementAllocationError("canonical registry lacks base backend allocation")
    slot = _slot_identity(base_row)
    slot_runs = {
        row["run_id"]
        for row in registry_rows
        if _registry_slot_identity(row) == slot
    }
    if slot_runs != set(authorized):
        raise ReplacementAllocationError(
            f"unknown or missing run in algorithmic slot: {sorted(slot_runs ^ set(authorized))}"
        )
    for run_id in authorized:
        chain = chains.get(run_id, [])
        if not chain:
            raise ReplacementAllocationError(f"replacement chain lacks {run_id}")
        if [item.get("status") for item in chain] != [
            "PLANNED",
            "RUNNING",
            "FAILED",
        ]:
            raise ReplacementAllocationError(
                f"replacement source registry chain is not PLANNED/RUNNING/FAILED: {run_id}"
            )
        latest = chain[-1]
        if (
            latest.get("status") != "FAILED"
            or latest.get("infrastructure_failure") != "true"
            or latest.get("replay_evaluable") != "false"
            or latest.get("replay_hard_failure") != "false"
            or latest.get("algorithm_hard_failure") != "false"
        ):
            raise ReplacementAllocationError(
                f"algorithmic slot consumed or source nonterminal: {run_id} "
                f"status={latest.get('status')} infra={latest.get('infrastructure_failure')}"
            )
    return base_chain[0], chains[failed_run_id][-1]


def _load_prior_effective_row(
    *, root: Path, base_row: Mapping[str, str], relevant_index: Sequence[Mapping[str, str]]
) -> Mapping[str, str]:
    if not relevant_index:
        return base_row
    last = relevant_index[-1]
    path = common.workspace_path(
        root, last["replacement_lock_path"], label="prior replacement lock"
    )
    if common.sha256(path) != last["replacement_lock_sha256"]:
        raise ReplacementAllocationError("prior replacement lock SHA drift")
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_replacement_lock_payload(
        payload, expected_relative_path=last["replacement_lock_path"]
    )
    effective = payload["effective_queue_row"]
    if not isinstance(effective, dict) or effective.get("run_id") != last["run_id"]:
        raise ReplacementAllocationError("prior replacement effective row mismatch")
    return effective  # type: ignore[return-value]


def _binding_from_execution_lock(
    execution: Mapping[str, object],
    contract_payload: Mapping[str, object],
    *,
    contract_record: Mapping[str, object],
) -> None:
    binding = execution.get("infrastructure_replacement")
    if not isinstance(binding, dict):
        raise ReplacementAllocationError("execution lock lacks replacement contract")
    if (
        binding.get("replacement_contract_hash")
        != contract_payload.get(contract.SELF_HASH_FIELD)
        or binding.get("contract") != dict(contract_record)
        or binding.get("replacement_lock_schema") != SCHEMA
        or binding.get("replacement_lock_status") != STATUS
        or binding.get("allocation_index_path")
        != queue_builder.display_path(contract.INDEX_PATH)
    ):
        raise ReplacementAllocationError("execution/replacement contract binding drift")


def _existing_exact_plan(
    *,
    root: Path,
    row: Mapping[str, str],
    failed_run_id: str,
    allocated_at: str,
    index_rows: Sequence[Mapping[str, str]],
    registry_fields: Sequence[str],
) -> ReplacementPlan | None:
    matches = [
        item
        for item in index_rows
        if item["queue_index"] == row["queue_index"]
        and item["replacement_for"] == failed_run_id
        and item["allocated_at"] == allocated_at
    ]
    if not matches:
        return None
    if len(matches) != 1 or matches[0] is not index_rows[-1]:
        raise ReplacementAllocationError("replacement idempotence key is ambiguous")
    item = matches[0]
    lock_path = common.workspace_path(
        root, item["replacement_lock_path"], label="replacement lock"
    )
    content = lock_path.read_bytes()
    if common.sha256_bytes(content) != item["replacement_lock_sha256"]:
        raise ReplacementAllocationError("existing replacement lock SHA drift")
    payload = json.loads(content)
    validate_replacement_lock_payload(
        payload, expected_relative_path=item["replacement_lock_path"]
    )
    registry_event = payload.get("registry_planned_event")
    if not isinstance(registry_event, dict) or set(registry_event) != set(registry_fields):
        raise ReplacementAllocationError("replacement lock registry e00/header mismatch")
    return ReplacementPlan(
        replacement_lock_path=lock_path,
        replacement_lock_payload=dict(payload),
        replacement_lock_bytes=content,
        index_row=dict(item),
        registry_row={key: str(value) for key, value in registry_event.items()},
        existing_exact_allocation=True,
    )


def build_live_plan(
    queue_index: int,
    *,
    failed_run_id: str,
    allocated_at: str,
    root: Path = common.ROOT,
    queue_path: Path | None = None,
    allocation_path: Path | None = None,
    execution_lock_path: Path | None = None,
    contract_path: Path | None = None,
    index_path: Path | None = None,
    registry_path: Path | None = None,
) -> ReplacementPlan:
    queue_builder.allocation_stamp(allocated_at)
    queue_path = queue_path or root / queue_builder.display_path(queue_builder.BACKEND_QUEUE)
    allocation_path = allocation_path or root / queue_builder.display_path(
        queue_builder.BACKEND_ALLOCATION
    )
    execution_lock_path = execution_lock_path or root / common.DEFAULT_EXECUTION_LOCK_RELATIVE
    contract_path = contract_path or root / queue_builder.display_path(contract.OUTPUT)
    index_path = index_path or root / queue_builder.display_path(contract.INDEX_PATH)
    registry_path = registry_path or root / queue_builder.display_path(queue_builder.RUN_REGISTRY)

    execution = common.validate_execution_lock(
        root,
        execution_lock_path,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    contract_payload = json.loads(contract_path.read_text(encoding="utf-8"))
    contract.validate_contract_payload(contract_payload, root=root)
    contract_record = _file_record(contract_path, root=root)
    _binding_from_execution_lock(
        execution, contract_payload, contract_record=contract_record
    )
    base_row = common.indexed_row(queue_path, queue_index)
    allocation = common.indexed_row(allocation_path, queue_index)
    common.validate_allocation(base_row, allocation)
    index_rows = read_index(index_path)
    for item in index_rows:
        if (
            item["execution_lock_hash"] != execution.get("execution_lock_hash")
            or item["replacement_contract_hash"]
            != contract_payload.get(contract.SELF_HASH_FIELD)
        ):
            raise ReplacementAllocationError(
                "replacement allocation index parent-lock drift"
            )
    registry_fields, registry_rows = registration.read_csv_with_fields(registry_path)

    existing = _existing_exact_plan(
        root=root,
        row=base_row,
        failed_run_id=failed_run_id,
        allocated_at=allocated_at,
        index_rows=index_rows,
        registry_fields=registry_fields,
    )
    if existing is not None:
        return existing

    relevant_index = [
        item for item in index_rows if item["queue_index"] == base_row["queue_index"]
    ]
    base_registry_e00, source_terminal = _validate_slot_unconsumed(
        base_row,
        failed_run_id=failed_run_id,
        index_rows=index_rows,
        registry_rows=registry_rows,
    )
    source_effective = _load_prior_effective_row(
        root=root, base_row=base_row, relevant_index=relevant_index
    )
    if source_effective["run_id"] != failed_run_id:
        raise ReplacementAllocationError("failure source/effective row mismatch")
    failure_path = common.output_path(
        root,
        source_effective["expected_attempt_dir"],
        label="failed attempt directory",
    ) / "infrastructure_failure_evidence_v2.json"
    if not failure_path.is_file():
        raise ReplacementAllocationError(f"missing failure evidence: {failure_path}")
    failure_payload = json.loads(failure_path.read_text(encoding="utf-8"))
    validate_failure_evidence(
        failure_payload, queue_index=queue_index, failed_run_id=failed_run_id
    )
    evidence_bundle = validate_infrastructure_evidence_bundle(
        failure_payload,
        evidence_path=failure_path,
        source_registry_event=source_terminal,
        root=root,
        queue_path=queue_path,
        allocation_path=allocation_path,
        execution_lock_path=execution_lock_path,
    )

    attempt_number = 2 + len(relevant_index)
    effective = build_effective_row(base_row, attempt_number=attempt_number)
    relative_lock = lock_relative_path(queue_index, attempt_number)
    replacement_lock_path = root / relative_lock
    if common.output_path(
        root, effective["expected_run_dir"], label="replacement run dir"
    ).exists():
        raise ReplacementAllocationError("replacement run target already exists")
    if common.output_path(
        root, effective["expected_attempt_dir"], label="replacement attempt dir"
    ).exists():
        raise ReplacementAllocationError("replacement attempt target already exists")
    execution_record = _file_record(execution_lock_path, root=root)
    execution_hash = str(execution["execution_lock_hash"])
    contract_hash = str(contract_payload[contract.SELF_HASH_FIELD])
    registry_row = build_registry_row(
        base_registry_e00,
        effective,
        allocated_at=allocated_at,
        replacement_for=failed_run_id,
        replacement_lock_relative=relative_lock,
        execution_lock_hash=execution_hash,
        replacement_contract_hash=contract_hash,
        registry_fields=registry_fields,
    )
    lock_payload = build_replacement_lock_payload(
        allocated_at=allocated_at,
        allocation_index=len(index_rows) + 1,
        attempt_number=attempt_number,
        base_row=base_row,
        effective_row=effective,
        replacement_for=failed_run_id,
        replacement_lock_relative=relative_lock,
        failure_evidence_record=_file_record(failure_path, root=root),
        failure_evidence_payload=failure_payload,
        infrastructure_evidence_bundle=evidence_bundle,
        source_registry_event=source_terminal,
        registry_planned_event=registry_row,
        queue_record=_file_record(queue_path, root=root),
        allocation_record=_file_record(allocation_path, root=root),
        base_allocation=allocation,
        allocation_index_prefix=index_prefix_snapshot(index_path),
        execution_lock_record=execution_record,
        execution_lock_hash=execution_hash,
        contract_record=contract_record,
        replacement_contract_hash=contract_hash,
    )
    validate_replacement_lock_payload(
        lock_payload, expected_relative_path=relative_lock
    )
    lock_bytes = queue_builder.json_bytes(lock_payload)
    previous_event_hash = index_rows[-1]["event_hash"] if index_rows else ""
    index_row = {
        "schema_version": contract.INDEX_SCHEMA,
        "allocation_index": str(len(index_rows) + 1),
        "event_id": f"p07_backend_replacement_a{len(index_rows) + 1:04d}",
        "previous_event_hash": previous_event_hash,
        "event_hash": "",
        "allocated_at": allocated_at,
        "queue_index": base_row["queue_index"],
        "algorithmic_slot": base_row["algorithmic_slot"],
        "root_queue_run_id": base_row["run_id"],
        "failed_run_id": failed_run_id,
        "replacement_for": failed_run_id,
        "run_id": effective["run_id"],
        "attempt_number": str(attempt_number),
        "runner_tag": effective["runner_tag"],
        "expected_run_dir": effective["expected_run_dir"],
        "expected_attempt_dir": effective["expected_attempt_dir"],
        "failure_evidence_path": queue_builder.display_path(failure_path),
        "failure_evidence_sha256": common.sha256(failure_path),
        "execution_lock_hash": execution_hash,
        "replacement_contract_hash": contract_hash,
        "replacement_lock_path": relative_lock,
        "replacement_lock_sha256": common.sha256_bytes(lock_bytes),
        "status": INDEX_STATUS,
        "outcome_boundary": OUTCOME_BOUNDARY,
    }
    index_row["event_hash"] = index_event_hash(index_row)
    return ReplacementPlan(
        replacement_lock_path=replacement_lock_path,
        replacement_lock_payload=lock_payload,
        replacement_lock_bytes=lock_bytes,
        index_row=index_row,
        registry_row=registry_row,
    )


def _write_exact_no_clobber(path: Path, content: bytes, *, root: Path) -> None:
    relative = path.absolute().relative_to(root.absolute()).as_posix()
    try:
        queue_builder.formal_io.publish_bytes_no_clobber(
            root, relative, content, allow_exact_existing=True
        )
    except (FileExistsError, queue_builder.formal_io.FormalIOError) as error:
        raise ReplacementAllocationError(
            f"replacement lock collision or unsafe path: {path}"
        ) from error


def _index_row_bytes(row: Mapping[str, str], *, include_header: bool) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS, lineterminator="\n")
    if include_header:
        writer.writeheader()
    writer.writerow(row)
    return stream.getvalue().encode("utf-8")


def append_index_exact(path: Path, row: Mapping[str, str]) -> None:
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o644)
    try:
        info = os.fstat(fd)
        path_info = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(path_info.st_mode)
            or info.st_dev != path_info.st_dev
            or info.st_ino != path_info.st_ino
        ):
            raise ReplacementAllocationError(
                "replacement allocation index is not direct regular"
            )
        with os.fdopen(fd, "r+b", closefd=False) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            content = handle.read()
            if content and not content.endswith(b"\n"):
                raise ReplacementAllocationError("replacement index lacks final newline")
            if content:
                reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
                fields = list(reader.fieldnames or [])
                rows = list(reader)
                if fields != INDEX_FIELDS or any(None in item for item in rows):
                    raise ReplacementAllocationError("replacement index is malformed")
            else:
                rows = []
            key = row["allocation_index"]
            observed = [item for item in rows if item["allocation_index"] == key]
            if observed:
                if len(observed) != 1 or observed[0] != dict(row):
                    raise ReplacementAllocationError("replacement index collision")
                return
            if int(key) != len(rows) + 1:
                raise ReplacementAllocationError("replacement index append is non-contiguous")
            expected_previous = "" if not rows else rows[-1]["event_hash"]
            if (
                row["event_id"] != f"p07_backend_replacement_a{int(key):04d}"
                or row["previous_event_hash"] != expected_previous
                or row["event_hash"] != index_event_hash(row)
            ):
                raise ReplacementAllocationError("replacement index event hash chain drift")
            handle.seek(0, os.SEEK_END)
            handle.write(_index_row_bytes(row, include_header=not content))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(fd)


def apply_plan(
    plan: ReplacementPlan, *, index_path: Path, registry_path: Path, root: Path | None = None
) -> None:
    workspace = common.ROOT if root is None else root
    queue_builder.formal_io.ensure_exact_leaf_directory(
        workspace,
        queue_builder.display_path(queue_builder.P07),
        contract.LOCK_DIRECTORY.name,
    )
    _write_exact_no_clobber(
        plan.replacement_lock_path, plan.replacement_lock_bytes, root=workspace
    )
    # Index precedes registry.  The governed job requires both, so an
    # interruption here cannot execute an unregistered replacement; rerunning
    # with the same allocation timestamp repairs the exact PLANNED e00.
    append_index_exact(index_path, plan.index_row)
    registration.append_missing(registry_path, [plan.registry_row])
    index_rows = read_index(index_path)
    if not index_rows or index_rows[-1] != plan.index_row:
        raise ReplacementAllocationError("replacement index postcondition failed")
    _fields, registry_rows = registration.read_csv_with_fields(registry_path)
    exact = [
        row
        for row in registry_rows
        if row["run_id"] == plan.registry_row["run_id"]
    ]
    if exact != [plan.registry_row] or exact[0]["status"] != "PLANNED":
        raise ReplacementAllocationError("replacement registry postcondition failed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--failed-run-id", required=True)
    parser.add_argument("--allocated-at", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--root", type=Path, default=common.ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    allocator_lock = Path(contract.GLOBAL_ALLOCATOR_FLOCK)
    with queue_builder.formal_io.global_formal_lock(allocator_lock):
        plan = build_live_plan(
            args.queue_index,
            failed_run_id=args.failed_run_id,
            allocated_at=args.allocated_at,
            root=root,
        )
        if args.apply:
            apply_plan(
                plan,
                index_path=root / queue_builder.display_path(contract.INDEX_PATH),
                registry_path=root / queue_builder.display_path(queue_builder.RUN_REGISTRY),
                root=root,
            )
    print(
        json.dumps(
            {
                "status": "APPLIED" if args.apply else "READY",
                "queue_index": args.queue_index,
                "replacement_for": args.failed_run_id,
                "run_id": plan.index_row["run_id"],
                "attempt_number": int(plan.index_row["attempt_number"]),
                "replacement_lock": plan.index_row["replacement_lock_path"],
                "replacement_lock_sha256": plan.index_row[
                    "replacement_lock_sha256"
                ],
                "existing_exact_allocation": plan.existing_exact_allocation,
                "trajectory_outcome_read_at_allocation": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
