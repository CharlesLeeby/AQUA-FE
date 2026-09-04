#!/usr/bin/env python3
"""Run the additive fail-closed recovery for P07 queue 58.

The canonical queue-58 attempt is never promoted to success.  After proving
that its orphaned child processes have exited, ``classify-original`` appends a
terminal infrastructure failure.  A distinct M attempt02 then performs the
same frozen frontend export with only its output identity changed.

This module also supplies effective-slot adapters for canonical queues 59/60
and the final A07 D-resolution.  Every path remains frontend-only: VINS,
trajectory files, APE, and RPE are neither executed nor read.
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

try:
    from scripts import audit_p07_frontend_export_v3 as audit_v3
    from scripts import audit_p07_frontend_export_v4 as audit_v4
    from scripts import build_p07_d_resolution_lock_v2 as d_builder_v2
    from scripts import build_p07_d_resolution_lock_v3 as d_builder_v3
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import build_p07_q58_orphan_replacement_lock_v1 as contract
    from scripts import resolve_p07_d_applicability_v2 as d_resolver_v2
    from scripts import resolve_p07_d_applicability_v3 as d_resolver_v3
    from scripts import run_p07_frontend_export_job_v3 as job_v3
    from scripts import run_p07_frontend_export_job_v5 as job_v5
    from scripts import run_p07_frontend_queue_v4 as queue_v4
    from scripts import run_p07_mp_frontend_export_job_v2 as base_job
    from scripts import run_p07_q55_a04_layout_replacement_v1 as q55_recovery
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as audit_v3  # type: ignore
    import audit_p07_frontend_export_v4 as audit_v4  # type: ignore
    import build_p07_d_resolution_lock_v2 as d_builder_v2  # type: ignore
    import build_p07_d_resolution_lock_v3 as d_builder_v3  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import build_p07_q58_orphan_replacement_lock_v1 as contract  # type: ignore
    import resolve_p07_d_applicability_v2 as d_resolver_v2  # type: ignore
    import resolve_p07_d_applicability_v3 as d_resolver_v3  # type: ignore
    import run_p07_frontend_export_job_v3 as job_v3  # type: ignore
    import run_p07_frontend_export_job_v5 as job_v5  # type: ignore
    import run_p07_frontend_queue_v4 as queue_v4  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base_job  # type: ignore
    import run_p07_q55_a04_layout_replacement_v1 as q55_recovery  # type: ignore


LOCK_PATH = contract.OUTPUT
RUN_REGISTRY = governance.BUNDLE / "run_registry.csv"
ACTION_LOCK = contract.REPLACEMENT_ROOT / ".queue_058_a07_orphan_attempt02.lock"
LEDGER_SCHEMA = "isj-p07-frontend-replacement-ledger-event-v1"
CLASSIFICATION_SCHEMA = "isj-p07-q58-orphan-parent-loss-classification-v1"
REGISTRATION_SCHEMA = "isj-p07-q58-orphan-replacement-registration-v1"
CLOSEOUT_SCHEMA = "isj-p07-q58-orphan-replacement-closeout-v1"
RAW_PREFLIGHT = contract.ATTEMPT_DIR / "raw_reuse_preflight_v1.json"
RAW_POSTFLIGHT = contract.ATTEMPT_DIR / "raw_reuse_postflight_v1.json"


class OrphanReplacementRuntimeError(RuntimeError):
    """Raised for any q58 recovery state, evidence, or boundary violation."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    return contract.sha256(path)


def display_path(path: Path) -> str:
    return audit_v3.display_path(path)


def _json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OrphanReplacementRuntimeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OrphanReplacementRuntimeError(f"JSON is not an object: {path}")
    return value


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    contract.atomic_no_clobber_json(path, dict(payload))
    _fsync_directory(path.parent)


def _exclusive_text(path: Path, text: str) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def action_lock() -> Iterator[None]:
    contract.REPLACEMENT_ROOT.mkdir(parents=True, exist_ok=True)
    fd = os.open(ACTION_LOCK, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def read_registry(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise OrphanReplacementRuntimeError(f"invalid registry: {path}")
    return fields, [dict(row) for row in rows]


def registry_chain(path: Path, run_id: str) -> list[dict[str, str]]:
    _fields, rows = read_registry(path)
    chain = [row for row in rows if row.get("run_id") == run_id]
    for index, row in enumerate(chain):
        expected_parent = "" if index == 0 else f"{run_id}_e{index - 1:02d}"
        if (
            row.get("registry_event_id") != f"{run_id}_e{index:02d}"
            or row.get("supersedes_event_id") != expected_parent
        ):
            raise OrphanReplacementRuntimeError(f"non-contiguous registry chain: {run_id}")
    return chain


def _append_registry_row(path: Path, row: dict[str, str], *, expect_absent: bool) -> None:
    with path.open("r+", newline="", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = [dict(item) for item in reader]
            if not fields or any(None in item for item in rows) or set(row) != set(fields):
                raise OrphanReplacementRuntimeError("registry row/header mismatch")
            chain = [item for item in rows if item.get("run_id") == row["run_id"]]
            if expect_absent:
                if chain:
                    raise OrphanReplacementRuntimeError("registry identity already exists")
            elif (
                not chain
                or row["supersedes_event_id"] != chain[-1]["registry_event_id"]
                or row["registry_event_id"] != f"{row['run_id']}_e{len(chain):02d}"
            ):
                raise OrphanReplacementRuntimeError("registry append parent mismatch")
            stream = io.StringIO(newline="")
            csv.DictWriter(stream, fieldnames=fields, lineterminator="\n").writerow(row)
            handle.seek(0, os.SEEK_END)
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def append_transition(
    path: Path,
    run_id: str,
    *,
    expected_status: str,
    status: str,
    updates: Mapping[str, str],
    recorded_at: str | None = None,
) -> dict[str, str]:
    chain = registry_chain(path, run_id)
    if not chain or chain[-1]["status"] != expected_status:
        observed = chain[-1]["status"] if chain else "MISSING"
        raise OrphanReplacementRuntimeError(
            f"registry latest {observed} != {expected_status}"
        )
    row = dict(chain[-1])
    row.update(updates)
    row.update(
        {
            "registry_event_id": f"{run_id}_e{len(chain):02d}",
            "recorded_at": recorded_at or now(),
            "supersedes_event_id": chain[-1]["registry_event_id"],
            "status": status,
        }
    )
    _append_registry_row(path, row, expect_absent=False)
    return row


def _validate_record(record: Mapping[str, Any], *, root: Path = contract.ROOT) -> Path:
    path = root / str(record.get("path", ""))
    if (
        not path.is_file()
        or path.is_symlink()
        or path.stat().st_size != int(record.get("size_bytes", -1))
        or sha256(path) != record.get("sha256")
    ):
        raise OrphanReplacementRuntimeError(f"frozen artifact drift: {path}")
    return path


def validate_raw_cache(payload: dict[str, Any], *, require_inode: bool = True) -> dict[str, Any]:
    frozen = payload["raw_cache"]
    observed = contract.inspect_raw_bag(contract.RAW_BAG)
    keys = ("path", "sha256", "size_bytes", "topic_counts")
    if any(observed.get(key) != frozen.get(key) for key in keys):
        raise OrphanReplacementRuntimeError("q58 raw cache differs from frozen recovery lock")
    if require_inode and any(
        observed.get(key) != frozen.get(key) for key in ("device", "inode")
    ):
        raise OrphanReplacementRuntimeError("q58 raw cache physical identity changed")
    return observed


def build_original_failure_event(
    payload: dict[str, Any], *, recorded_at: str
) -> dict[str, str]:
    running = dict(payload["original"]["registry_running_chain"][-1])
    running.update(
        {
            "registry_event_id": f"{payload['original_run_id']}_e02",
            "recorded_at": recorded_at,
            "supersedes_event_id": running["registry_event_id"],
            "status": "FAILED",
            "infrastructure_failure": "true",
            "output_hash_manifest": "",
            "notes": running["notes"]
            + "; orphan parent-loss recovery classified canonical q58 as infrastructure failure; "
            + "child process exited without outer attestation/audit/registry completion; "
            + "unattested child output is not reused; trajectory outcome not read",
        }
    )
    return running


def validate_classification(
    payload: dict[str, Any], report: dict[str, Any]
) -> dict[str, Any]:
    chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    if len(chain) != 3:
        raise OrphanReplacementRuntimeError("canonical q58 is not exact e02 terminal")
    expected = build_original_failure_event(payload, recorded_at=chain[-1]["recorded_at"])
    if chain[:2] != payload["original"]["registry_running_chain"] or chain[-1] != expected:
        raise OrphanReplacementRuntimeError("canonical q58 failure event is not exact")
    if (
        report.get("schema_version") != CLASSIFICATION_SCHEMA
        or report.get("status") != "PASS_INFRASTRUCTURE_FAILED"
        or report.get("original_run_id") != payload["original_run_id"]
        or report.get("classification_event") != expected
        or report.get("reason_code") != contract.REASON_CODE
        or report.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or report.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or report.get("trajectory_outcome_read") is not False
        or report.get("unattested_child_output_promoted") is not False
    ):
        raise OrphanReplacementRuntimeError("q58 classification sidecar mismatch")
    return report


def load_classification(payload: dict[str, Any]) -> dict[str, Any]:
    if not contract.CLASSIFICATION.is_file():
        raise OrphanReplacementRuntimeError("q58 classification sidecar is missing")
    return validate_classification(payload, _json(contract.CLASSIFICATION))


def validate_lock_payload(
    payload: dict[str, Any], *, verify_artifacts: bool = True
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != contract.SCHEMA
        or payload.get("status") != contract.STATUS
        or payload.get("original_queue_index") != contract.ORIGINAL_QUEUE_INDEX
        or payload.get("window_id") != contract.WINDOW_ID
        or payload.get("reason_code") != contract.REASON_CODE
        or payload.get("replacement_tag") != contract.REPLACEMENT_TAG
        or payload.get(contract.SELF_HASH_FIELD) != contract.document_hash(payload)
        or payload.get("action_order") != contract.ACTION_ORDER
        or payload.get("allowed_remaining_indices") != [59, 60]
        or payload.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("vins_execution_allowed") is not False
    ):
        raise OrphanReplacementRuntimeError(
            "q58 recovery lock schema, identity, hash, order, or boundary mismatch"
        )
    original = payload.get("original")
    replacement = payload.get("replacement")
    if not isinstance(original, dict) or not isinstance(replacement, dict):
        raise OrphanReplacementRuntimeError("q58 recovery lock sections missing")
    effective = replacement.get("effective_queue_row")
    allocation = replacement.get("effective_allocation_row")
    if not isinstance(effective, dict) or not isinstance(allocation, dict):
        raise OrphanReplacementRuntimeError("q58 effective identity missing")
    try:
        contract.assert_tag_only_command_diff(original["queue_row"], effective)
    except Exception as exc:
        raise OrphanReplacementRuntimeError(f"scientific command drift: {exc}") from exc
    if (
        replacement.get("run_id") != payload.get("replacement_run_id")
        or replacement.get("tag") != contract.REPLACEMENT_TAG
        or replacement.get("command") != effective.get("command")
        or replacement.get("command_sha256") != effective.get("command_sha256")
        or allocation.get("run_id") != payload.get("replacement_run_id")
        or allocation.get("tag") != contract.REPLACEMENT_TAG
        or allocation.get("expected_feature_bag") != effective.get("expected_feature_bag")
        or not str(replacement.get("command", "")).startswith("RUN_VINS=0 ")
        or replacement.get("scientific_parameters_changed") is not False
        or replacement.get("scientific_command_change_scope")
        != ["TAG", "output_identity"]
        or replacement.get("reuse_verified_raw_cache") is not True
    ):
        raise OrphanReplacementRuntimeError("q58 replacement identity or policy mismatch")
    contract.validate_original_running_chain(
        original["registry_running_chain"], payload["original_run_id"]
    )
    if verify_artifacts:
        for record in payload.get("artifacts", []):
            if not isinstance(record, dict):
                raise OrphanReplacementRuntimeError("invalid q58 lock artifact record")
            _validate_record(record)
        for record in [
            *original.get("attempt_artifacts", []),
            *original.get("run_artifacts", []),
            *payload.get("correction_and_d_evidence", []),
        ]:
            _validate_record(record)
        for snapshot in payload.get("mutable_stream_prefix_snapshots", []):
            path = contract.ROOT / str(snapshot.get("path", ""))
            size = int(snapshot.get("size_bytes", -1))
            if not path.exists() and size == 0:
                content = b""
            else:
                content = path.read_bytes()
            if (
                size < 0
                or len(content) < size
                or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
            ):
                raise OrphanReplacementRuntimeError(f"append-only prefix drift: {path}")
    return payload


def load_lock(
    *,
    require_classified: bool = False,
    require_raw: bool = True,
    verify_artifacts: bool = True,
) -> dict[str, Any]:
    if not LOCK_PATH.is_file():
        raise OrphanReplacementRuntimeError(f"missing formal q58 recovery lock: {LOCK_PATH}")
    payload = validate_lock_payload(_json(LOCK_PATH), verify_artifacts=verify_artifacts)
    if (
        audit_v3.queue_row(contract.ORIGINAL_QUEUE_INDEX)
        != payload["original"]["queue_row"]
        or audit_v3.allocation_row(contract.ORIGINAL_QUEUE_INDEX)
        != payload["original"]["allocation_row"]
    ):
        raise OrphanReplacementRuntimeError("canonical q58 queue or allocation drift")
    chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    frozen = payload["original"]["registry_running_chain"]
    if chain == frozen:
        if require_classified:
            raise OrphanReplacementRuntimeError("canonical q58 has not been classified")
    elif len(chain) == 3 and chain[:2] == frozen:
        expected = build_original_failure_event(payload, recorded_at=chain[-1]["recorded_at"])
        if chain[-1] != expected:
            raise OrphanReplacementRuntimeError("canonical q58 terminal event drift")
        if require_classified:
            load_classification(payload)
    else:
        raise OrphanReplacementRuntimeError("canonical q58 chain is outside frozen recovery states")
    matches = contract.matching_mutator_processes()
    if matches:
        raise OrphanReplacementRuntimeError(
            "q58 orphan mutator process is still alive: " + json.dumps(matches)
        )
    if require_raw:
        validate_raw_cache(payload)
    return payload


def classify_original(payload: dict[str, Any]) -> dict[str, Any]:
    matches = contract.matching_mutator_processes()
    if matches:
        raise OrphanReplacementRuntimeError("cannot classify q58 while a mutator is alive")
    validate_raw_cache(payload)
    chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    if len(chain) == 2:
        if chain != payload["original"]["registry_running_chain"]:
            raise OrphanReplacementRuntimeError("q58 running prefix differs from lock")
        event = build_original_failure_event(payload, recorded_at=now())
        _append_registry_row(RUN_REGISTRY, event, expect_absent=False)
    elif len(chain) == 3:
        event = build_original_failure_event(payload, recorded_at=chain[-1]["recorded_at"])
        if chain[:2] != payload["original"]["registry_running_chain"] or chain[-1] != event:
            raise OrphanReplacementRuntimeError("existing q58 e02 is not exact recovery event")
    else:
        raise OrphanReplacementRuntimeError("q58 classification requires e01 or exact e02")
    report: dict[str, Any] = {
        "schema_version": CLASSIFICATION_SCHEMA,
        "status": "PASS_INFRASTRUCTURE_FAILED",
        "recorded_at": now(),
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "original_run_id": payload["original_run_id"],
        "reason_code": contract.REASON_CODE,
        "classification_event": event,
        "orphan_quiescence_rechecked": {
            "matching_processes": [],
            "signal_or_process_mutation_performed": False,
        },
        "unattested_child_output_promoted": False,
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "lock_path": display_path(LOCK_PATH),
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    if contract.CLASSIFICATION.exists():
        return validate_classification(payload, _json(contract.CLASSIFICATION))
    atomic_json(contract.CLASSIFICATION, report)
    return validate_classification(payload, report)


def build_replacement_e00(
    payload: dict[str, Any], *, recorded_at: str
) -> dict[str, str]:
    original = dict(payload["original"]["registry_running_chain"][0])
    new_run_id = payload["replacement_run_id"]
    replacement = payload["replacement"]
    original.update(
        {
            "run_id": new_run_id,
            "registry_event_id": f"{new_run_id}_e00",
            "recorded_at": recorded_at,
            "supersedes_event_id": "",
            "status": "PLANNED",
            "replacement_for": payload["original_run_id"],
            "run_dir": replacement["effective_queue_row"]["expected_run_root"],
            "command_file": display_path(LOCK_PATH),
            "input_hash_manifest": "",
            "output_hash_manifest": "",
            "infrastructure_failure": "",
            "accepted_lineage_count": "",
            "active": "",
            "notes": (
                f"replacement_for={payload['original_run_id']}; queue_index=58; "
                f"tag={contract.REPLACEMENT_TAG}; reason={contract.REASON_CODE}; "
                f"command_sha256={replacement['command_sha256']}; frontend export only; "
                "trajectory outcome not read; canonical q58 remains infrastructure FAILED"
            ),
        }
    )
    return original


def ledger_events(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise OrphanReplacementRuntimeError(
                f"invalid replacement ledger line {number}"
            ) from exc
        if not isinstance(item, dict):
            raise OrphanReplacementRuntimeError("replacement ledger event is not an object")
        if item.get("replacement_run_id") == run_id:
            events.append(item)
    for index, item in enumerate(events):
        if (
            item.get("ledger_event_id") != f"{run_id}_l{index:02d}"
            or item.get("supersedes_event_id")
            != ("" if index == 0 else f"{run_id}_l{index - 1:02d}")
        ):
            raise OrphanReplacementRuntimeError("q58 replacement ledger is not contiguous")
    return events


def append_ledger(
    path: Path,
    payload: dict[str, Any],
    *,
    event_type: str,
    status: str,
    registry_event: dict[str, str],
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    with os.fdopen(fd, "r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            all_items = [json.loads(line) for line in handle.read().splitlines() if line]
            if any(not isinstance(item, dict) for item in all_items):
                raise OrphanReplacementRuntimeError("replacement ledger has non-object event")
            run_id = payload["replacement_run_id"]
            events = [item for item in all_items if item.get("replacement_run_id") == run_id]
            for index, item in enumerate(events):
                if (
                    item.get("schema_version") != LEDGER_SCHEMA
                    or item.get("ledger_event_id") != f"{run_id}_l{index:02d}"
                    or item.get("supersedes_event_id")
                    != ("" if index == 0 else f"{run_id}_l{index - 1:02d}")
                    or item.get("replacement_lock_hash")
                    != payload[contract.SELF_HASH_FIELD]
                    or item.get("trajectory_outcome_read") is not False
                ):
                    raise OrphanReplacementRuntimeError("q58 ledger prefix identity drift")
            exact = [
                item
                for item in events
                if item.get("event_type") == event_type
                and item.get("status") == status
                and item.get("registry_event_id") == registry_event["registry_event_id"]
            ]
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1 or any(
                item.get("event_type") == event_type for item in events
            ):
                raise OrphanReplacementRuntimeError("conflicting q58 ledger retry")
            index = len(events)
            event = {
                "schema_version": LEDGER_SCHEMA,
                "ledger_event_id": f"{run_id}_l{index:02d}",
                "recorded_at": now(),
                "supersedes_event_id": "" if index == 0 else events[-1]["ledger_event_id"],
                "replacement_run_id": run_id,
                "replacement_for": payload["original_run_id"],
                "queue_index": contract.ORIGINAL_QUEUE_INDEX,
                "event_type": event_type,
                "status": status,
                "registry_event_id": registry_event["registry_event_id"],
                "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
                "outcome_boundary": contract.OUTCOME_BOUNDARY,
                "trajectory_outcome_read": False,
            }
            handle.seek(0, os.SEEK_END)
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return event


def validate_registration(payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    events = ledger_events(contract.LEDGER, payload["replacement_run_id"])
    if (
        report.get("schema_version") != REGISTRATION_SCHEMA
        or report.get("status") != "ALLOCATED"
        or report.get("original_run_id") != payload["original_run_id"]
        or report.get("replacement_run_id") != payload["replacement_run_id"]
        or report.get("effective_allocation_row")
        != payload["replacement"]["effective_allocation_row"]
        or not chain
        or report.get("registry_event") != chain[0]
        or not events
        or report.get("ledger_event") != events[0]
        or report.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or report.get("trajectory_outcome_read") is not False
    ):
        raise OrphanReplacementRuntimeError("q58 replacement registration mismatch")
    return report


def load_registration(payload: dict[str, Any]) -> dict[str, Any]:
    if not contract.REGISTRATION.is_file():
        raise OrphanReplacementRuntimeError("q58 replacement registration missing")
    return validate_registration(payload, _json(contract.REGISTRATION))


def register(payload: dict[str, Any]) -> dict[str, Any]:
    load_classification(payload)
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if chain:
        if len(chain) != 1 or chain[0].get("status") != "PLANNED":
            raise OrphanReplacementRuntimeError("q58 replacement registry already advanced")
        expected = build_replacement_e00(payload, recorded_at=chain[0]["recorded_at"])
        if chain[0] != expected:
            raise OrphanReplacementRuntimeError("existing q58 replacement e00 differs")
        event = chain[0]
    else:
        event = build_replacement_e00(payload, recorded_at=now())
        _append_registry_row(RUN_REGISTRY, event, expect_absent=True)
    events = ledger_events(contract.LEDGER, payload["replacement_run_id"])
    if events:
        if (
            len(events) != 1
            or events[0].get("event_type") != "ALLOCATED"
            or events[0].get("status") != "PLANNED"
            or events[0].get("registry_event_id") != event["registry_event_id"]
        ):
            raise OrphanReplacementRuntimeError("q58 allocation ledger mismatch")
        ledger = events[0]
    else:
        ledger = append_ledger(
            contract.LEDGER,
            payload,
            event_type="ALLOCATED",
            status="PLANNED",
            registry_event=event,
        )
    report: dict[str, Any] = {
        "schema_version": REGISTRATION_SCHEMA,
        "status": "ALLOCATED",
        "recorded_at": now(),
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "original_run_id": payload["original_run_id"],
        "replacement_run_id": payload["replacement_run_id"],
        "replacement_tag": contract.REPLACEMENT_TAG,
        "effective_allocation_row": payload["replacement"]["effective_allocation_row"],
        "registry_event": event,
        "ledger_event": ledger,
        "classification": {
            "path": display_path(contract.CLASSIFICATION),
            "sha256": sha256(contract.CLASSIFICATION),
        },
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    if contract.REGISTRATION.exists():
        return validate_registration(payload, _json(contract.REGISTRATION))
    atomic_json(contract.REGISTRATION, report)
    return validate_registration(payload, report)


def _capacity(payload: dict[str, Any]) -> dict[str, Any]:
    output = shutil.disk_usage(contract.REPLACEMENT_RUN_DIR.parent)
    governance_usage = shutil.disk_usage(contract.P07)
    output_min = int(payload["capacity_gate"]["frontend_output_minimum_free_bytes"])
    governance_min = int(payload["capacity_gate"]["governance_minimum_free_bytes"])
    return {
        "output_root": display_path(contract.REPLACEMENT_RUN_DIR.parent),
        "output_free_bytes": output.free,
        "output_minimum_free_bytes": output_min,
        "output_pass": output.free >= output_min,
        "governance_free_bytes": governance_usage.free,
        "governance_minimum_free_bytes": governance_min,
        "governance_pass": governance_usage.free >= governance_min,
    }


def _load_q55_dependency() -> dict[str, Any]:
    recovery = q55_recovery.load_lock(verify_artifacts=True)
    return q55_recovery.load_closeout(recovery)


def _canonical_completed(index: int) -> dict[str, str]:
    allocation = audit_v3.allocation_row(index)
    chain = registry_chain(RUN_REGISTRY, allocation["run_id"])
    if not chain or chain[-1]["status"] != "COMPLETED":
        raise OrphanReplacementRuntimeError(f"canonical queue {index} is not COMPLETED")
    return chain[-1]


def preflight_replacement(payload: dict[str, Any]) -> dict[str, Any]:
    load_classification(payload)
    load_registration(payload)
    _load_q55_dependency()
    _canonical_completed(57)
    if not queue_v4.window_is_terminal_complete("aqualoc_archaeology:A04:0002"):
        raise OrphanReplacementRuntimeError("A04 D dependency is not terminal")
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
        raise OrphanReplacementRuntimeError("q58 replacement preflight requires e00 PLANNED")
    validate_raw_cache(payload)
    row = payload["replacement"]["effective_queue_row"]
    collisions = [display_path(path) for path in base_job.target_collisions(row)]
    report = {
        "queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "replacement_run_id": payload["replacement_run_id"],
        "arm": governance.M_ARM,
        "collisions": collisions,
        "attempt_collision": contract.ATTEMPT_DIR.exists(),
        "capacity": _capacity(payload),
        "registry_latest_status": chain[-1]["status"],
        "raw_cache_sha256": payload["raw_cache"]["sha256"],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    return report


@contextmanager
def audit_overlay(
    effective_queue: dict[str, str], effective_allocation: dict[str, str]
) -> Iterator[None]:
    original_queue: Callable[[int], dict[str, str]] = audit_v3.queue_row
    original_allocation: Callable[[int], dict[str, str]] = audit_v3.allocation_row

    def queue(index: int) -> dict[str, str]:
        return (
            dict(effective_queue)
            if index == contract.ORIGINAL_QUEUE_INDEX
            else original_queue(index)
        )

    def allocation(index: int) -> dict[str, str]:
        return (
            dict(effective_allocation)
            if index == contract.ORIGINAL_QUEUE_INDEX
            else original_allocation(index)
        )

    audit_v3.queue_row = queue
    audit_v3.allocation_row = allocation
    try:
        yield
    finally:
        audit_v3.queue_row = original_queue
        audit_v3.allocation_row = original_allocation


def _write_raw_report(path: Path, payload: dict[str, Any], *, phase: str) -> dict[str, Any]:
    observed = validate_raw_cache(payload)
    report = {
        "schema_version": "isj-p07-q58-raw-cache-reuse-check-v1",
        "status": "PASS",
        "recorded_at": now(),
        "phase": phase,
        "replacement_run_id": payload["replacement_run_id"],
        "raw_cache": observed,
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "rosbag_metadata_only": True,
        "trajectory_outcome_read": False,
    }
    atomic_json(path, report)
    return report


def _write_input_manifest(payload: dict[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    files = [
        LOCK_PATH,
        contract.CLASSIFICATION,
        contract.REGISTRATION,
        RAW_PREFLIGHT,
        Path(__file__).resolve(),
        contract.Q55_LOCK,
        contract.Q55_REGISTRATION,
        contract.Q55_CLOSEOUT,
        contract.Q55_RECLAIM_CLOSEOUT,
        contract.A04_PATH_CORRECTION_LOCK,
        contract.A04_D_LOCK,
        contract.A04_D_EVIDENCE,
    ]
    files.extend(contract.ROOT / record["path"] for record in payload["artifacts"])
    files.extend(
        contract.ROOT / record["path"]
        for record in [
            *payload["original"]["attempt_artifacts"],
            *payload["original"]["run_artifacts"],
        ]
    )
    base_job.write_hash_manifest(path, files)
    text = path.read_text(encoding="utf-8")
    if display_path(contract.RAW_BAG) in text or str(contract.RAW_BAG.resolve()) in text:
        raise OrphanReplacementRuntimeError(
            "raw cache must be bound by immutable lock/report, not direct manifest entry"
        )
    for required in (
        LOCK_PATH,
        contract.CLASSIFICATION,
        contract.REGISTRATION,
        contract.A04_PATH_CORRECTION_LOCK,
        contract.A04_D_LOCK,
        contract.A04_D_EVIDENCE,
    ):
        if display_path(required) not in text and str(required) not in text:
            raise OrphanReplacementRuntimeError(
                f"replacement input manifest omitted evidence: {required}"
            )


def _run_inprocess_audit(
    payload: dict[str, Any], command_log: Path, attestation: Path
) -> tuple[Path, dict[str, Any]]:
    path = contract.ATTEMPT_DIR / "audit_v4.json"
    log_path = contract.ATTEMPT_DIR / "audit_v4.log"
    if path.exists() or log_path.exists():
        raise FileExistsError("q58 replacement audit collision")
    row = payload["replacement"]["effective_queue_row"]
    allocation = payload["replacement"]["effective_allocation_row"]
    with audit_overlay(row, allocation):
        audit = audit_v4.build_audit(
            index=contract.ORIGINAL_QUEUE_INDEX,
            command_log=command_log,
            attestation=attestation,
        )
    audit.update(
        {
            "tag": contract.REPLACEMENT_TAG,
            "replacement_for": payload["original_run_id"],
            "physical_frontend_rerun": True,
            "raw_cache_reused": True,
        }
    )
    if (
        audit.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or audit.get("status") != "PASS"
        or audit.get("run_id") != payload["replacement_run_id"]
        or audit.get("arm") != governance.M_ARM
        or audit.get("command_sha256") != payload["replacement"]["command_sha256"]
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise OrphanReplacementRuntimeError("q58 in-process strict v4 audit mismatch")
    atomic_json(path, audit)
    _exclusive_text(
        log_path,
        "P07_FRONTEND_EXPORT_AUDIT_V4_PASS queue_index=58 "
        f"arm={audit['arm']} frames={audit['feature_bag']['feature_frames']}\n",
    )
    return path, audit


def _close_preexecution_failure(
    payload: dict[str, Any], *, phase: str, error: Exception
) -> None:
    run_id = payload["replacement_run_id"]
    chain = registry_chain(RUN_REGISTRY, run_id)
    if not chain or chain[-1]["status"] not in {"PLANNED", "RUNNING"}:
        return
    command_path = contract.ATTEMPT_DIR / "command.txt"
    input_manifest = contract.ATTEMPT_DIR / "input_hash_manifest.sha256"
    if chain[-1]["status"] == "PLANNED":
        running = append_transition(
            RUN_REGISTRY,
            run_id,
            expected_status="PLANNED",
            status="RUNNING",
            updates={
                "run_dir": payload["replacement"]["effective_queue_row"][
                    "expected_run_root"
                ],
                "command_file": display_path(command_path),
                "input_hash_manifest": (
                    display_path(input_manifest) if input_manifest.exists() else ""
                ),
                "notes": chain[-1]["notes"] + f"; replacement entered {phase}",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type="EXECUTION_STARTED",
            status="RUNNING",
            registry_event=running,
        )
    latest = registry_chain(RUN_REGISTRY, run_id)[-1]
    if latest["status"] == "RUNNING":
        failed = append_transition(
            RUN_REGISTRY,
            run_id,
            expected_status="RUNNING",
            status="FAILED",
            updates={
                "infrastructure_failure": "true",
                "notes": latest["notes"]
                + f"; replacement preexecution failed closed phase={phase}: "
                + f"{type(error).__name__}: {error}",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type="EXECUTION_FAILED",
            status="FAILED",
            registry_event=failed,
        )


def execute_replacement(payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    report = preflight_replacement(payload)
    if (
        report["collisions"]
        or report["attempt_collision"]
        or not report["capacity"]["output_pass"]
        or not report["capacity"]["governance_pass"]
    ):
        raise OrphanReplacementRuntimeError(
            f"q58 replacement preflight failed without attempt creation: {report}"
        )
    contract.ATTEMPT_DIR.mkdir(parents=True, exist_ok=False)
    row = dict(payload["replacement"]["effective_queue_row"])
    allocation = dict(payload["replacement"]["effective_allocation_row"])
    command_path = contract.ATTEMPT_DIR / "command.txt"
    command_log = contract.ATTEMPT_DIR / "command.log"
    capacity_path = contract.ATTEMPT_DIR / "capacity_preflight.json"
    input_manifest = contract.ATTEMPT_DIR / "input_hash_manifest.sha256"
    _exclusive_text(command_path, row["command"] + "\n")
    atomic_json(capacity_path, report["capacity"])
    _write_raw_report(RAW_PREFLIGHT, payload, phase="BEFORE_REPLACEMENT_COMMAND")
    _write_input_manifest(payload, input_manifest)
    environment = job_v5.clean_environment()
    running = False
    try:
        guard_log, guard_path = job_v3.run_guard_preflight(
            row, contract.ATTEMPT_DIR, environment
        )
        running_event = append_transition(
            RUN_REGISTRY,
            allocation["run_id"],
            expected_status="PLANNED",
            status="RUNNING",
            updates={
                "run_dir": row["expected_run_root"],
                "command_file": display_path(command_path),
                "input_hash_manifest": display_path(input_manifest),
                "notes": registry_chain(RUN_REGISTRY, allocation["run_id"])[-1]["notes"]
                + "; q58 replacement executor started; guard-only preflight exact PASS; "
                + "verified raw cache reused without direct output-manifest binding",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type="EXECUTION_STARTED",
            status="RUNNING",
            registry_event=running_event,
        )
        running = True
        rc, timed_out = base_job.run_command(
            row["command"], command_log, timeout_s=timeout_s, environment=environment
        )
        if rc != 0:
            raise OrphanReplacementRuntimeError(
                f"replacement frontend command failed rc={rc} timeout={str(timed_out).lower()}"
            )
        raw_after = _write_raw_report(
            RAW_POSTFLIGHT, payload, phase="AFTER_REPLACEMENT_COMMAND"
        )
        raw_before = _json(RAW_PREFLIGHT)["raw_cache"]
        if raw_after["raw_cache"] != raw_before:
            raise OrphanReplacementRuntimeError("raw cache changed across replacement command")
        actual_guard = audit_v3.parse_guard_path(command_log)
        audit_v3.validate_guard(actual_guard, row["arm"])
        with audit_overlay(row, allocation):
            run_dir, feature_bag, probe_run, _summary, _duplicates = (
                audit_v3.resolve_run_artifacts(row)
            )
        attestation, _attestation_log = base_job.run_attestation(
            row, feature_bag, contract.ATTEMPT_DIR
        )
        audit_path, audit = _run_inprocess_audit(payload, command_log, attestation)
        run_dirs = [run_dir]
        if probe_run is not None and probe_run not in run_dirs:
            run_dirs.append(probe_run)
        output_manifest = contract.ATTEMPT_DIR / "output_hash_manifest.sha256"
        files = base_job.output_files(
            run_dirs, contract.ATTEMPT_DIR, [guard_path, actual_guard]
        )
        files = [path for path in files if path.resolve() != contract.RAW_BAG.resolve()]
        base_job.write_hash_manifest(output_manifest, files)
        output_text = output_manifest.read_text(encoding="utf-8")
        if display_path(contract.RAW_BAG) in output_text or str(contract.RAW_BAG.resolve()) in output_text:
            raise OrphanReplacementRuntimeError("replacement output manifest binds raw cache")
        completed = append_transition(
            RUN_REGISTRY,
            allocation["run_id"],
            expected_status="RUNNING",
            status="COMPLETED",
            updates={
                "run_dir": display_path(run_dir),
                "command_file": display_path(command_path),
                "input_hash_manifest": display_path(input_manifest),
                "output_hash_manifest": display_path(output_manifest),
                "infrastructure_failure": "false",
                "notes": registry_chain(RUN_REGISTRY, allocation["run_id"])[-1]["notes"]
                + "; replacement frontend export, attestation, and strict v4 audit PASS; "
                + f"audit={display_path(audit_path)}; canonical q58 remains infrastructure FAILED",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type="EXECUTION_COMPLETED",
            status="COMPLETED",
            registry_event=completed,
        )
        return {
            "status": "COMPLETED",
            "replacement_run_id": allocation["run_id"],
            "run_dir": display_path(run_dir),
            "audit": display_path(audit_path),
            "raw_cache_sha256": payload["raw_cache"]["sha256"],
            "trajectory_outcome_read": False,
        }
    except Exception as error:
        if running:
            latest = registry_chain(RUN_REGISTRY, allocation["run_id"])[-1]
            if latest["status"] == "RUNNING":
                infrastructure = (
                    "true"
                    if "timeout=true" in str(error).lower()
                    or "raw cache" in str(error).lower()
                    else "false"
                )
                failed = append_transition(
                    RUN_REGISTRY,
                    allocation["run_id"],
                    expected_status="RUNNING",
                    status="FAILED",
                    updates={
                        "infrastructure_failure": infrastructure,
                        "notes": latest["notes"]
                        + f"; replacement failed closed: {type(error).__name__}: {error}",
                    },
                )
                append_ledger(
                    contract.LEDGER,
                    payload,
                    event_type="EXECUTION_FAILED",
                    status="FAILED",
                    registry_event=failed,
                )
        else:
            _close_preexecution_failure(payload, phase="GUARD_PREFLIGHT", error=error)
        raise


def closeout_hash(payload: dict[str, Any]) -> str:
    return contract.document_hash(payload, "closeout_hash")


def validate_success_ledger(
    payload: dict[str, Any], replacement_chain: list[dict[str, str]]
) -> list[dict[str, Any]]:
    events = ledger_events(contract.LEDGER, payload["replacement_run_id"])
    expected = [
        ("ALLOCATED", "PLANNED", replacement_chain[0]["registry_event_id"]),
        ("EXECUTION_STARTED", "RUNNING", replacement_chain[1]["registry_event_id"]),
        ("EXECUTION_COMPLETED", "COMPLETED", replacement_chain[2]["registry_event_id"]),
        ("EFFECTIVE_SLOT_CLOSEOUT", "COMPLETED", replacement_chain[2]["registry_event_id"]),
    ]
    observed = [
        (item.get("event_type"), item.get("status"), item.get("registry_event_id"))
        for item in events
    ]
    if observed != expected:
        raise OrphanReplacementRuntimeError(
            f"q58 replacement success ledger sequence mismatch: {observed}"
        )
    return events


def build_closeout_document(
    payload: dict[str, Any],
    *,
    original_failure: dict[str, str],
    replacement_completion: dict[str, str],
    audit_path: Path,
    audit: dict[str, Any],
    output_manifest: Path,
    ledger_event: dict[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    if original_failure.get("status") != "FAILED" or original_failure.get(
        "infrastructure_failure"
    ) != "true":
        raise OrphanReplacementRuntimeError("q58 original is not infrastructure FAILED")
    if replacement_completion.get("status") != "COMPLETED":
        raise OrphanReplacementRuntimeError("q58 replacement is not COMPLETED")
    report: dict[str, Any] = {
        "schema_version": CLOSEOUT_SCHEMA,
        "status": "PASS",
        "recorded_at": recorded_at,
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "window_id": contract.WINDOW_ID,
        "original_run_id": payload["original_run_id"],
        "replacement_run_id": payload["replacement_run_id"],
        "replacement_tag": contract.REPLACEMENT_TAG,
        "replacement_command": payload["replacement"]["command"],
        "replacement_command_sha256": payload["replacement"]["command_sha256"],
        "replacement_for": payload["replacement"]["replacement_for"],
        "original_final_registry_event": original_failure,
        "completion_registry_event": replacement_completion,
        "effective_slot_status": "COMPLETED",
        "classification": {
            "path": display_path(contract.CLASSIFICATION),
            "sha256": sha256(contract.CLASSIFICATION),
        },
        "replacement_audit": {
            "path": display_path(audit_path),
            "sha256": sha256(audit_path),
            "schema_version": audit["schema_version"],
            "status": audit["status"],
        },
        "replacement_output_manifest": {
            "path": display_path(output_manifest),
            "sha256": sha256(output_manifest),
            "size_bytes": output_manifest.stat().st_size,
        },
        "raw_cache_reuse": {
            "frozen_sha256": payload["raw_cache"]["sha256"],
            "preflight": {
                "path": display_path(RAW_PREFLIGHT),
                "sha256": sha256(RAW_PREFLIGHT),
            },
            "postflight": {
                "path": display_path(RAW_POSTFLIGHT),
                "sha256": sha256(RAW_POSTFLIGHT),
            },
            "unchanged": True,
        },
        "replacement_ledger_event": ledger_event,
        "lock_path": display_path(LOCK_PATH),
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "physical_frontend_rerun": True,
        "canonical_original_chain_preserved_failed": True,
        "unattested_child_output_promoted": False,
        "scientific_parameters_changed": False,
        "scientific_command_change_scope": ["TAG", "output_identity"],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    report["closeout_hash"] = closeout_hash(report)
    return report


def validate_closeout(payload: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    original = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    replacement = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(original) != 3 or len(replacement) != 3:
        raise OrphanReplacementRuntimeError("q58 closeout registry chain length mismatch")
    expected_original = build_original_failure_event(
        payload, recorded_at=original[-1]["recorded_at"]
    )
    if original[-1] != expected_original or [row["status"] for row in replacement] != [
        "PLANNED",
        "RUNNING",
        "COMPLETED",
    ]:
        raise OrphanReplacementRuntimeError("q58 closeout terminal chains mismatch")
    ledger = validate_success_ledger(payload, replacement)
    if (
        report.get("schema_version") != CLOSEOUT_SCHEMA
        or report.get("status") != "PASS"
        or report.get("closeout_hash") != closeout_hash(report)
        or report.get("original_run_id") != payload["original_run_id"]
        or report.get("replacement_run_id") != payload["replacement_run_id"]
        or report.get("original_final_registry_event") != original[-1]
        or report.get("completion_registry_event") != replacement[-1]
        or report.get("effective_slot_status") != "COMPLETED"
        or report.get("replacement_ledger_event") != ledger[-1]
        or report.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or report.get("unattested_child_output_promoted") is not False
        or report.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or report.get("trajectory_outcome_read") is not False
    ):
        raise OrphanReplacementRuntimeError("q58 replacement closeout mismatch")
    audit_path = contract.ATTEMPT_DIR / "audit_v4.json"
    audit = _json(audit_path)
    if (
        audit.get("status") != "PASS"
        or audit.get("run_id") != payload["replacement_run_id"]
        or audit.get("tag") != contract.REPLACEMENT_TAG
        or audit.get("arm") != governance.M_ARM
        or audit.get("held_out_trajectory_outcome_read") is not False
        or report.get("replacement_audit", {}).get("sha256") != sha256(audit_path)
    ):
        raise OrphanReplacementRuntimeError("q58 closeout audit mismatch")
    output = contract.ROOT / replacement[-1]["output_hash_manifest"]
    if (
        not output.is_file()
        or report.get("replacement_output_manifest", {}).get("sha256") != sha256(output)
    ):
        raise OrphanReplacementRuntimeError("q58 closeout output manifest mismatch")
    pre = _json(RAW_PREFLIGHT)
    post = _json(RAW_POSTFLIGHT)
    if pre.get("raw_cache") != post.get("raw_cache") or pre.get("raw_cache", {}).get(
        "sha256"
    ) != payload["raw_cache"]["sha256"]:
        raise OrphanReplacementRuntimeError("q58 closeout raw reuse evidence mismatch")
    return report


def load_closeout(payload: dict[str, Any]) -> dict[str, Any]:
    if not contract.CLOSEOUT.is_file():
        raise OrphanReplacementRuntimeError("q58 replacement closeout missing")
    return validate_closeout(payload, _json(contract.CLOSEOUT))


def closeout(payload: dict[str, Any]) -> dict[str, Any]:
    if contract.CLOSEOUT.exists():
        return load_closeout(payload)
    load_classification(payload)
    original = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    replacement = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(original) != 3 or len(replacement) != 3 or replacement[-1]["status"] != "COMPLETED":
        raise OrphanReplacementRuntimeError("q58 closeout requires terminal original/replacement")
    audit_path = contract.ATTEMPT_DIR / "audit_v4.json"
    audit = _json(audit_path)
    output = contract.ROOT / replacement[-1]["output_hash_manifest"]
    if not output.is_file():
        raise OrphanReplacementRuntimeError("q58 replacement output manifest missing")
    append_ledger(
        contract.LEDGER,
        payload,
        event_type="EXECUTION_COMPLETED",
        status="COMPLETED",
        registry_event=replacement[-1],
    )
    ledger = append_ledger(
        contract.LEDGER,
        payload,
        event_type="EFFECTIVE_SLOT_CLOSEOUT",
        status="COMPLETED",
        registry_event=replacement[-1],
    )
    report = build_closeout_document(
        payload,
        original_failure=original[-1],
        replacement_completion=replacement[-1],
        audit_path=audit_path,
        audit=audit,
        output_manifest=output,
        ledger_event=ledger,
        recorded_at=now(),
    )
    atomic_json(contract.CLOSEOUT, report)
    return validate_closeout(payload, report)


def replacement_aware_ensure_predecessors(
    index: int, execution_lock: dict[str, Any], recovery: dict[str, Any]
) -> None:
    if index not in recovery["allowed_remaining_indices"]:
        raise OrphanReplacementRuntimeError(f"queue {index} outside q58 recovery resume")
    load_closeout(recovery)
    _load_q55_dependency()
    order = [int(value) for value in execution_lock["execution_order"]]
    if index not in order:
        raise OrphanReplacementRuntimeError("queue index absent from v5 execution order")
    for predecessor in order[: order.index(index)]:
        if predecessor in {55, 58}:
            continue
        _canonical_completed(predecessor)
    if not queue_v4.window_is_terminal_complete("aqualoc_archaeology:A04:0002"):
        raise OrphanReplacementRuntimeError("A04 D dependency is not terminal")


@contextmanager
def replacement_aware_predecessor_overlay(recovery: dict[str, Any]) -> Iterator[None]:
    original = base_job.ensure_predecessor_completed

    def helper(index: int, execution_lock: dict[str, Any]) -> None:
        replacement_aware_ensure_predecessors(index, execution_lock, recovery)

    base_job.ensure_predecessor_completed = helper
    try:
        yield
    finally:
        base_job.ensure_predecessor_completed = original


@contextmanager
def replacement_aware_execution_evidence_overlay(
    recovery: dict[str, Any], index: int
) -> Iterator[None]:
    original_writer = base_job.write_hash_manifest
    original_append = job_v3.append_registry_event
    closeout_sha = sha256(contract.CLOSEOUT)
    extra = [
        LOCK_PATH,
        contract.CLASSIFICATION,
        contract.REGISTRATION,
        contract.CLOSEOUT,
        Path(__file__).resolve(),
        contract.Q55_LOCK,
        contract.Q55_CLOSEOUT,
        contract.A04_PATH_CORRECTION_LOCK,
        contract.A04_D_LOCK,
        contract.A04_D_EVIDENCE,
    ]

    def writer(path: Path, files: list[Path]) -> None:
        selected = list(files)
        if path.name == "input_hash_manifest.sha256":
            selected.extend(extra)
        original_writer(path, selected)
        if path.name == "input_hash_manifest.sha256":
            text = path.read_text(encoding="utf-8")
            for required in extra:
                if display_path(required) not in text and str(required) not in text:
                    raise OrphanReplacementRuntimeError(
                        f"resumed input manifest omitted q58 evidence: {required}"
                    )

    def registry_append(*args, **kwargs):
        note = str(kwargs.get("note", ""))
        kwargs["note"] = (
            note
            + "; predecessor queue_index=58 satisfied by additive replacement "
            + f"run_id={recovery['replacement_run_id']}; "
            + f"closeout={display_path(contract.CLOSEOUT)}; closeout_sha256={closeout_sha}; "
            + "canonical q58 remains infrastructure FAILED; trajectory outcome not read"
        )
        return original_append(*args, **kwargs)

    base_job.write_hash_manifest = writer
    job_v3.append_registry_event = registry_append
    try:
        yield
    finally:
        base_job.write_hash_manifest = original_writer
        job_v3.append_registry_event = original_append


def resume_preflight(payload: dict[str, Any], index: int) -> dict[str, Any]:
    load_closeout(payload)
    execution_lock = job_v5.load_and_validate_lock(index)
    replacement_aware_ensure_predecessors(index, execution_lock, payload)
    with replacement_aware_predecessor_overlay(payload):
        return job_v5.preflight(index)


def resume_execute(payload: dict[str, Any], index: int, *, timeout_s: int) -> dict[str, Any]:
    load_closeout(payload)
    execution_lock = job_v5.load_and_validate_lock(index)
    replacement_aware_ensure_predecessors(index, execution_lock, payload)
    with replacement_aware_predecessor_overlay(payload):
        with replacement_aware_execution_evidence_overlay(payload, index):
            return job_v5.execute(index, timeout_s=timeout_s)


@contextmanager
def effective_allocation_overlay(payload: dict[str, Any]) -> Iterator[None]:
    original = audit_v3.allocation_row

    def allocation(index: int) -> dict[str, str]:
        return (
            dict(payload["replacement"]["effective_allocation_row"])
            if index == contract.ORIGINAL_QUEUE_INDEX
            else original(index)
        )

    audit_v3.allocation_row = allocation
    try:
        yield
    finally:
        audit_v3.allocation_row = original


def _require_final_triplet(payload: dict[str, Any]) -> None:
    load_closeout(payload)
    _canonical_completed(59)
    _canonical_completed(60)
    if queue_v4.window_is_terminal_complete(contract.WINDOW_ID):
        raise OrphanReplacementRuntimeError("final A07 D is already terminal")


def build_final_d_lock(payload: dict[str, Any]) -> dict[str, Any]:
    _require_final_triplet(payload)
    output = d_resolver_v3.resolution_lock_path(contract.WINDOW_ID)
    if output.exists():
        raise FileExistsError(output)
    with effective_allocation_overlay(payload):
        result = d_builder_v3.build_lock(contract.WINDOW_ID)
    extra_paths = [
        LOCK_PATH,
        contract.CLASSIFICATION,
        contract.REGISTRATION,
        contract.CLOSEOUT,
        Path(__file__).resolve(),
        contract.Q55_LOCK,
        contract.Q55_CLOSEOUT,
        contract.A04_PATH_CORRECTION_LOCK,
        contract.A04_D_LOCK,
        contract.A04_D_EVIDENCE,
    ]
    records = [d_builder_v2.file_record(path) for path in extra_paths]
    by_path = {
        str(record["path"]): record for record in [*result["artifacts"], *records]
    }
    result["artifacts"] = list(by_path.values())
    result["replacement_effective_slots"] = {
        "58": {
            "canonical_final_status": "FAILED",
            "canonical_infrastructure_failure": True,
            "replacement_run_id": payload["replacement_run_id"],
            "replacement_closeout": display_path(contract.CLOSEOUT),
            "effective_status": "COMPLETED",
        }
    }
    result["trajectory_outcome_read"] = False
    result["resolution_lock_hash"] = d_resolver_v3.resolution_lock_hash(result)
    contract.atomic_no_clobber_json(output, result)
    _fsync_directory(output.parent)
    return result


def resolve_final_d(payload: dict[str, Any]) -> dict[str, Any]:
    load_closeout(payload)
    _canonical_completed(59)
    _canonical_completed(60)
    with effective_allocation_overlay(payload):
        return d_resolver_v3.append_resolution(contract.WINDOW_ID)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "classify-original",
            "register",
            "preflight-replacement",
            "execute-replacement",
            "closeout",
            "resume-preflight",
            "resume-execute",
            "build-final-d-lock",
            "resolve-final-d",
        ),
    )
    parser.add_argument("--queue-index", type=int)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if args.action.startswith("resume-"):
        if args.queue_index not in {59, 60}:
            raise OrphanReplacementRuntimeError(
                "resume action requires --queue-index 59 or 60"
            )
    elif args.queue_index is not None:
        raise OrphanReplacementRuntimeError(
            "--queue-index is valid only for resume actions"
        )
    with action_lock():
        require_classified = args.action != "classify-original"
        payload = load_lock(require_classified=require_classified, require_raw=True)
        if args.action == "classify-original":
            result = classify_original(payload)
        elif args.action == "register":
            result = register(payload)
        elif args.action == "preflight-replacement":
            result = preflight_replacement(payload)
        elif args.action == "execute-replacement":
            result = execute_replacement(payload, timeout_s=args.timeout_s)
        elif args.action == "closeout":
            result = closeout(payload)
        elif args.action == "resume-preflight":
            assert args.queue_index is not None
            result = resume_preflight(payload, args.queue_index)
        elif args.action == "resume-execute":
            assert args.queue_index is not None
            result = resume_execute(payload, args.queue_index, timeout_s=args.timeout_s)
        elif args.action == "build-final-d-lock":
            result = build_final_d_lock(payload)
        else:
            result = resolve_final_d(payload)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
