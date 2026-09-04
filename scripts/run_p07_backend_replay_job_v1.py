#!/usr/bin/env python3
"""Run one locked P07 backend replay through the only governed entrypoint."""

from __future__ import annotations

import argparse
import csv
import fcntl
import io
import json
import math
import os
import re
import shutil
import errno
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts import allocate_p07_backend_replacement_v1 as replacement_allocator
    from scripts import audit_p07_backend_replay_v1 as auditor
    from scripts import check_p07_backend_replay_input_v1 as input_checker
    from scripts import p07_backend_replay_common_v1 as common
    from scripts import run_p07_backend_replay_adapter_v1 as adapter
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import allocate_p07_backend_replacement_v1 as replacement_allocator  # type: ignore
    import audit_p07_backend_replay_v1 as auditor  # type: ignore
    import check_p07_backend_replay_input_v1 as input_checker  # type: ignore
    import p07_backend_replay_common_v1 as common  # type: ignore
    import run_p07_backend_replay_adapter_v1 as adapter  # type: ignore


SCHEMA_VERSION = "isj-p07-backend-replay-job-result-v1"
FROZEN_TIMEOUT_S = 7200
ATTEMPT_INTENT_SCHEMA = "isj-p07-backend-attempt-intent-v1"
ATTEMPT_INTENT_STATUS = "CLAIMED_NO_REPLAY_STARTED"
ATTEMPT_INTENT_ROOT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_attempt_intents"
)


class JobViolation(common.BackendReplayViolation):
    """The governed job cannot proceed without violating its frozen lock."""


INFRASTRUCTURE_CATEGORIES = {
    "ROS_MASTER_CONFLICT",
    "FILE_NOT_FOUND",
    "DISK_FULL",
    "PERMISSION_DENIED",
    "HARDWARE_INTERRUPTION",
    "OPERATOR_INTERRUPTION",
    "SUPERVISOR_PROCESS_LOSS",
}


def _classify_infrastructure_error(
    error: Exception, adapter_result: Mapping[str, Any] | None
) -> str | None:
    error_type = type(error).__name__
    detail = str(error).lower()
    if adapter_result is not None:
        error_type = str(adapter_result.get("error_type") or error_type)
        detail += " " + str(adapter_result.get("error") or "").lower()
    if isinstance(error, FileNotFoundError) or error_type == "FileNotFoundError":
        return "FILE_NOT_FOUND"
    if isinstance(error, PermissionError) or error_type == "PermissionError":
        return "PERMISSION_DENIED"
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return "DISK_FULL"
    if "no space left on device" in detail:
        return "DISK_FULL"
    if "permission denied" in detail:
        return "PERMISSION_DENIED"
    if "ros port" in detail or "ros master" in detail:
        return "ROS_MASTER_CONFLICT"
    if "missing " in detail or "no such file" in detail:
        return "FILE_NOT_FOUND"
    return None


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_formal_cli_contract(
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
    registry_path: Path,
    timeout_s: int,
    replacement_lock_path: Path | None = None,
) -> None:
    frozen_root = common.lexical_absolute(common.ROOT)

    def normalized(path: Path) -> Path:
        return common.lexical_absolute(path if path.is_absolute() else frozen_root / path)

    expected = {
        "root": frozen_root,
        "queue": common.lexical_absolute(common.DEFAULT_QUEUE),
        "allocation": common.lexical_absolute(common.DEFAULT_ALLOCATION),
        "execution_lock": common.lexical_absolute(common.DEFAULT_EXECUTION_LOCK),
        "registry": common.lexical_absolute(common.DEFAULT_REGISTRY),
    }
    observed = {
        "root": normalized(root),
        "queue": normalized(queue_path),
        "allocation": normalized(allocation_path),
        "execution_lock": normalized(execution_lock_path),
        "registry": normalized(registry_path),
    }
    differences = {
        key: {"expected": os.fspath(expected[key]), "observed": os.fspath(value)}
        for key, value in observed.items()
        if value != expected[key]
    }
    if differences:
        raise JobViolation(f"formal backend CLI path override forbidden: {differences}")
    if timeout_s != FROZEN_TIMEOUT_S:
        raise JobViolation(
            f"formal backend timeout override forbidden: {timeout_s}!={FROZEN_TIMEOUT_S}"
        )
    if replacement_lock_path is not None:
        replacement_path = normalized(replacement_lock_path)
        expected_parent = normalized(
            frozen_root
            / "papers/ieee_sensors_journal_experiments/p07/backend_replacements"
        )
        if (
            replacement_path.parent != expected_parent
            or not replacement_path.name.startswith("queue_")
            or not replacement_path.name.endswith("_replacement_lock_v1.json")
            or replacement_path.is_symlink()
            or not replacement_path.is_file()
        ):
            raise JobViolation(
                "formal --replacement-lock must name one existing frozen direct-child lock"
            )


def _execution_order(payload: Mapping[str, Any]) -> list[int]:
    raw = payload.get("execution_order")
    if not isinstance(raw, list) or not raw:
        raise JobViolation("execution lock lacks a non-empty execution_order")
    order: list[int] = []
    for item in raw:
        value = item.get("queue_index") if isinstance(item, dict) else item
        try:
            order.append(int(value))
        except (TypeError, ValueError) as error:
            raise JobViolation("invalid execution_order queue index") from error
    if len(order) != len(set(order)) or order != list(range(1, len(order) + 1)):
        raise JobViolation("backend execution order must be contiguous and unique")
    return order


def _registry_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    fields, rows = common.read_csv(path)
    required = {
        "run_id",
        "registry_event_id",
        "recorded_at",
        "supersedes_event_id",
        "status",
        "run_dir",
        "command_file",
        "input_hash_manifest",
        "output_hash_manifest",
        "infrastructure_failure",
        "replay_hard_failure",
        "algorithm_hard_failure",
        "notes",
    }
    if required.difference(fields):
        raise JobViolation("canonical run registry lacks required backend fields")
    return fields, rows


def registry_chain(path: Path, run_id: str) -> list[dict[str, str]]:
    _fields, rows = _registry_rows(path)
    chain = [row for row in rows if row["run_id"] == run_id]
    if not chain:
        raise JobViolation(f"canonical registry lacks preallocated run_id={run_id}")
    for index, row in enumerate(chain):
        expected_event = f"{run_id}_e{index:02d}"
        expected_parent = "" if index == 0 else chain[index - 1]["registry_event_id"]
        if (
            row["registry_event_id"] != expected_event
            or row["supersedes_event_id"] != expected_parent
        ):
            raise JobViolation(f"invalid registry chain for {run_id}")
    return chain


def _terminal_manifest_entries(content: bytes) -> dict[str, str]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise JobViolation("terminal output manifest is not UTF-8") from error
    entries: dict[str, str] = {}
    previous = ""
    for line in lines:
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\n]+)", line)
        if match is None:
            raise JobViolation("terminal output manifest is malformed")
        digest, relative = match.groups()
        if relative in entries or relative <= previous:
            raise JobViolation("terminal output manifest is unsorted or duplicate")
        entries[relative] = digest
        previous = relative
    if not entries:
        raise JobViolation("terminal output manifest is empty")
    return entries


def terminal_slot_disposition(
    *, root: Path, row: Mapping[str, str], latest: Mapping[str, str]
) -> str | None:
    """Validate one effective terminal event before consuming its algorithmic slot."""

    status = latest.get("status")
    if status not in {"COMPLETED", "FAILED"}:
        return None
    if latest.get("run_id") != row.get("run_id"):
        raise JobViolation("terminal registry/effective-row run identity drift")
    infrastructure = latest.get("infrastructure_failure")
    if infrastructure == "true":
        if (
            status != "FAILED"
            or latest.get("replay_hard_failure") != "false"
            or latest.get("algorithm_hard_failure") != "false"
            or not latest.get("output_hash_manifest")
        ):
            raise JobViolation("infrastructure terminal event is incomplete")
        return "INFRASTRUCTURE_FAILURE"
    if infrastructure != "false":
        raise JobViolation("scientific terminal lacks infrastructure=false")

    attempt = str(row.get("expected_attempt_dir", ""))
    expected_manifest = f"{attempt}/output_hash_manifest.sha256"
    expected_audit = f"{attempt}/audit_v1.json"
    expected_input = f"{attempt}/input_hash_manifest.sha256"
    expected_command = f"{attempt}/command.json"
    if (
        not attempt
        or latest.get("run_dir") != row.get("expected_run_dir")
        or latest.get("command_file") != expected_command
        or latest.get("input_hash_manifest") != expected_input
        or latest.get("output_hash_manifest") != expected_manifest
    ):
        raise JobViolation("terminal registry paths do not match the effective row")
    _manifest_path, manifest_content, _manifest_identity = (
        common.read_direct_workspace_bytes(
            root, expected_manifest, label="terminal output manifest"
        )
    )
    entries = _terminal_manifest_entries(manifest_content)
    expected_audit_hash = entries.get(expected_audit)
    if expected_audit_hash is None:
        raise JobViolation("terminal output manifest does not bind the exact audit")
    _audit_path, audit_content, _audit_identity = common.read_direct_workspace_bytes(
        root, expected_audit, label="terminal replay audit"
    )
    if common.sha256_bytes(audit_content) != expected_audit_hash:
        raise JobViolation("terminal replay audit hash differs from output manifest")
    notes = latest.get("notes", "")

    def note_value(name: str) -> str:
        matches = re.findall(rf"(?:^|; ){re.escape(name)}=([^;]+)", notes)
        if len(matches) != 1:
            raise JobViolation(f"terminal registry lacks one {name} binding")
        return matches[0]

    if (
        note_value("audit") != expected_audit
        or note_value("audit_sha256") != expected_audit_hash
        or note_value("output_manifest_sha256")
        != common.sha256_bytes(manifest_content)
    ):
        raise JobViolation("terminal registry evidence-hash binding drift")
    try:
        audit = json.loads(audit_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JobViolation("terminal replay audit is invalid JSON") from error
    checks = audit.get("checks") if isinstance(audit, dict) else None
    if (
        not isinstance(audit, dict)
        or audit.get("schema_version") != auditor.SCHEMA_VERSION
        or audit.get("status") != "PASS"
        or audit.get("queue_index") != int(row["queue_index"])
        or audit.get("run_id") != row["run_id"]
        or audit.get("window_id") != row.get("window_id")
        or audit.get("arm") != row.get("arm")
        or audit.get("terminal") is not True
        or audit.get("outcome_boundary")
        != "BACKEND_EXECUTION_ENVELOPE_ONLY_G0_EVALUATION_SEPARATE"
        or not isinstance(checks, dict)
        or any(
            checks.get(key) is not True
            for key in (
                "job_only_governed_adapter",
                "job_authority_manifest_valid",
                "data_identity_manifest_link_target_revalidated",
                "durable_attempt_intent_and_state_chain_valid",
                "expected_run_no_clobber",
            )
        )
        or checks.get("trajectory_values_read") is not False
        or checks.get("ape_rpe_values_read") is not False
    ):
        raise JobViolation("terminal replay audit is not an exact terminal PASS")

    hard_failure = status == "FAILED"
    expected_flag = "true" if hard_failure else "false"
    if (
        latest.get("replay_hard_failure") != expected_flag
        or latest.get("algorithm_hard_failure") != expected_flag
        or audit.get("replay_hard_failure") is not hard_failure
        or audit.get("numeric_evaluation_candidate") is hard_failure
        or audit.get("g0_evaluation_pending") is hard_failure
    ):
        raise JobViolation("terminal algorithmic disposition evidence drift")
    failure_code = audit.get("failure_code")
    failure_relative = f"{attempt}/failure_evidence.json"
    if hard_failure:
        if failure_code not in {"TIMEOUT", "NONZERO_EXIT", "EMPTY_TRAJECTORY"}:
            raise JobViolation("algorithm hard failure lacks a terminal failure code")
        expected_failure_hash = entries.get(failure_relative)
        if expected_failure_hash is None:
            raise JobViolation("algorithm hard failure manifest lacks failure evidence")
        _failure_path, failure_content, _failure_identity = (
            common.read_direct_workspace_bytes(
                root, failure_relative, label="terminal failure evidence"
            )
        )
        if common.sha256_bytes(failure_content) != expected_failure_hash:
            raise JobViolation("terminal failure evidence hash drift")
        try:
            failure = json.loads(failure_content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise JobViolation("terminal failure evidence is invalid JSON") from error
        if (
            not isinstance(failure, dict)
            or failure.get("schema_version")
            != "isj-p07-backend-replay-failure-evidence-v1"
            or failure.get("queue_index") != int(row["queue_index"])
            or failure.get("run_id") != row["run_id"]
            or failure.get("failure_code") != failure_code
            or failure.get("infrastructure_failure") is not False
        ):
            raise JobViolation("terminal failure evidence identity drift")
        return "ALGORITHM_HARD_FAILURE"
    if failure_code is not None or failure_relative in entries:
        raise JobViolation("completed terminal unexpectedly binds failure evidence")
    return "COMPLETED"


def append_registry_event(
    path: Path,
    run_id: str,
    *,
    expected_status: str,
    status: str,
    updates: Mapping[str, str],
    note: str,
) -> dict[str, str]:
    with path.open("r+", newline="", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or [])
            rows = list(reader)
            if not fields or any(None in row for row in rows):
                raise JobViolation("canonical registry became invalid")
            chain = [row for row in rows if row["run_id"] == run_id]
            if not chain or chain[-1]["status"] != expected_status:
                observed = chain[-1]["status"] if chain else "MISSING"
                raise JobViolation(
                    f"registry status transition {observed}->{status} expected {expected_status}"
                )
            for index, item in enumerate(chain):
                if item["registry_event_id"] != f"{run_id}_e{index:02d}":
                    raise JobViolation("registry event chain is not contiguous")
            unknown = set(updates).difference(fields)
            if unknown:
                raise JobViolation(f"registry lacks update fields: {sorted(unknown)}")
            previous = chain[-1]
            row = dict(previous)
            row.update(updates)
            row.update(
                {
                    "registry_event_id": f"{run_id}_e{len(chain):02d}",
                    "recorded_at": now(),
                    "supersedes_event_id": previous["registry_event_id"],
                    "status": status,
                    "notes": (previous.get("notes", "") + "; " + note).strip("; "),
                }
            )
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writerow(row)
            handle.seek(0, os.SEEK_END)
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
            return row
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _validate_registry_allocation(
    registry_path: Path,
    allocation: Mapping[str, str],
    row: Mapping[str, str],
) -> list[dict[str, str]]:
    chain = registry_chain(registry_path, row["run_id"])
    if len(chain) != 1 or chain[0]["status"] != "PLANNED":
        raise JobViolation("backend run is not an untouched canonical PLANNED allocation")
    initial = chain[0]
    exact = {
        "stage": "P07_BACKEND_REPLAY",
        "dataset_family": row["dataset_family"],
        "sequence": row["sequence"],
        "arm": row["arm"],
        "backend_replay": allocation["backend_replay"],
    }
    differences = {
        key: {"expected": value, "observed": initial.get(key)}
        for key, value in exact.items()
        if initial.get(key) != value
    }
    if differences:
        raise JobViolation(f"canonical registry/allocation mismatch: {differences}")
    return chain


def _require_predecessors_complete(
    order: Sequence[int],
    index: int,
    *,
    queue_path: Path,
    registry_path: Path,
    root: Path | None = None,
) -> None:
    try:
        position = order.index(index)
    except ValueError as error:
        raise JobViolation(f"queue index {index} is outside execution_order") from error
    root = root or common.ROOT
    index_path = (
        root
        / "papers/ieee_sensors_journal_experiments/p07/"
        "backend_replacement_allocation_v1.csv"
    )
    try:
        replacement_rows = replacement_allocator.read_index(index_path)
    except replacement_allocator.ReplacementAllocationError as error:
        raise JobViolation(f"replacement allocation index drift: {error}") from error
    for predecessor in order[:position]:
        row = common.indexed_row(queue_path, predecessor)
        effective_run_id = row["run_id"]
        effective_row: Mapping[str, str] = row
        relevant = [
            item
            for item in replacement_rows
            if item.get("queue_index") == row["queue_index"]
        ]
        expected_parent = row["run_id"]
        for attempt_number, item in enumerate(relevant, 2):
            if (
                int(item.get("attempt_number", "0")) != attempt_number
                or item.get("root_queue_run_id") != row["run_id"]
                or item.get("failed_run_id") != expected_parent
                or item.get("replacement_for") != expected_parent
                or item.get("algorithmic_slot") != row["algorithmic_slot"]
            ):
                raise JobViolation(
                    f"replacement chain drift for predecessor queue {predecessor}"
                )
            _lock_path, lock_content, _lock_identity = (
                common.read_direct_workspace_bytes(
                    root,
                    item["replacement_lock_path"],
                    label="predecessor replacement lock",
                )
            )
            if common.sha256_bytes(lock_content) != item["replacement_lock_sha256"]:
                raise JobViolation("predecessor replacement lock SHA drift")
            try:
                replacement_payload = json.loads(lock_content)
                replacement_allocator.validate_replacement_lock_payload(
                    replacement_payload,
                    expected_relative_path=item["replacement_lock_path"],
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
                replacement_allocator.ReplacementAllocationError,
            ) as error:
                raise JobViolation("invalid predecessor replacement lock") from error
            effective = replacement_payload.get("effective_queue_row")
            if (
                not isinstance(effective, dict)
                or replacement_payload.get("base_queue_row") != dict(row)
                or replacement_payload.get("attempt_number") != attempt_number
                or replacement_payload.get("failed_run_id") != expected_parent
                or replacement_payload.get("replacement_for") != expected_parent
                or effective.get("run_id") != item["run_id"]
                or effective.get("algorithmic_slot") != row["algorithmic_slot"]
            ):
                raise JobViolation("predecessor replacement effective-row drift")
            expected_parent = item["run_id"]
            effective_run_id = item["run_id"]
            effective_row = {key: str(value) for key, value in effective.items()}
        chain = registry_chain(registry_path, effective_run_id)
        latest = chain[-1]
        try:
            disposition = terminal_slot_disposition(
                root=root, row=effective_row, latest=latest
            )
        except JobViolation as error:
            raise JobViolation(
                f"queue index {index} blocked by predecessor {predecessor}: "
                "invalid terminal evidence"
            ) from error
        if disposition not in {"COMPLETED", "ALGORITHM_HARD_FAILURE"}:
            raise JobViolation(
                f"queue index {index} blocked by predecessor {predecessor} "
                f"effective_run_id={effective_run_id} status={latest['status']} "
                f"infrastructure_failure={latest.get('infrastructure_failure')}"
            )


def _capacity_report(
    rows: Sequence[Mapping[str, str]],
    order: Sequence[int],
    index: int,
    *,
    root: Path,
    lock: Mapping[str, Any],
) -> dict[str, Any]:
    capacity = lock["capacity_gate"]
    by_index = {int(row["queue_index"]): row for row in rows}
    if set(by_index) != set(order):
        raise JobViolation("queue rows differ from execution lock order")
    total = sum(int(row["estimated_output_bytes"]) for row in rows)
    numerator = int(capacity["margin_numerator"])
    denominator = int(capacity["margin_denominator"])
    reserve = int(capacity["reserve_bytes"])
    frozen_required = math.ceil(total * numerator / denominator) + reserve
    if (
        int(capacity["estimated_total_output_bytes"]) != total
        or int(capacity["required_output_free_bytes"]) != frozen_required
    ):
        raise JobViolation("frozen capacity total/required bytes mismatch queue estimates")
    position = order.index(index)
    remaining = sum(int(by_index[item]["estimated_output_bytes"]) for item in order[position:])
    required_output = math.ceil(remaining * numerator / denominator) + reserve
    output_root = common.output_path(
        root, str(capacity["output_filesystem_path"]), label="capacity output filesystem"
    )
    governance_root = common.output_path(
        root,
        str(capacity["governance_filesystem_path"]),
        label="capacity governance filesystem",
    )
    if not output_root.is_dir() or not governance_root.is_dir():
        raise JobViolation("capacity filesystem root is missing")
    output_usage = shutil.disk_usage(output_root)
    governance_usage = shutil.disk_usage(governance_root)
    minimum_governance = int(capacity["minimum_governance_free_bytes"])
    return {
        "policy": capacity["policy"],
        "queue_index": index,
        "remaining_jobs": len(order) - position,
        "remaining_estimated_output_bytes": remaining,
        "margin_numerator": numerator,
        "margin_denominator": denominator,
        "reserve_bytes": reserve,
        "output_filesystem_path": common.display_path(root, output_root),
        "output_free_bytes": output_usage.free,
        "output_required_free_bytes": required_output,
        "output_pass": output_usage.free >= required_output,
        "governance_filesystem_path": common.display_path(root, governance_root),
        "governance_free_bytes": governance_usage.free,
        "governance_required_free_bytes": minimum_governance,
        "governance_pass": governance_usage.free >= minimum_governance,
        "insufficient_action": "WAITING",
    }


def _hash_manifest_text(root: Path, files: Sequence[Path]) -> str:
    lines: list[str] = []
    unique = sorted({common.lexical_absolute(item) for item in files}, key=os.fspath)
    for item in unique:
        if not item.is_file():
            raise JobViolation(f"hash manifest input is missing: {item}")
        lines.append(f"{common.sha256(item)}  {common.display_path(root, item)}\n")
    return "".join(lines)


def _write_hash_manifest(path: Path, root: Path, files: Sequence[Path]) -> None:
    common.write_text_exclusive(path, _hash_manifest_text(root, files))


def _write_or_validate_json(path: Path, payload: Mapping[str, Any]) -> None:
    expected = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise JobViolation(f"no-clobber JSON target is not a plain file: {path}")
        try:
            observed = path.read_bytes()
        except OSError as error:
            raise JobViolation(f"existing no-clobber JSON is unreadable: {path}") from error
        if observed != expected:
            raise JobViolation(f"existing no-clobber JSON bytes differ: {path}")
        return
    try:
        common.write_json_exclusive(path, payload)
    except FileExistsError:
        _write_or_validate_json(path, payload)


def _write_or_validate_manifest(path: Path, root: Path, files: Sequence[Path]) -> None:
    expected = _hash_manifest_text(root, files)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise JobViolation(f"no-clobber manifest target is not a plain file: {path}")
        if path.read_text(encoding="utf-8") != expected:
            raise JobViolation(f"existing no-clobber manifest differs: {path}")
        return
    try:
        common.write_text_exclusive(path, expected)
    except FileExistsError:
        _write_or_validate_manifest(path, root, files)


def _output_files(run_dir: Path, attempt_dir: Path) -> list[Path]:
    selected: list[Path] = []
    for base in (run_dir, attempt_dir):
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if path.is_symlink():
                raise JobViolation(f"output evidence contains a symlink: {path}")
            if path.is_file() and path.name not in {
                "output_hash_manifest.sha256",
                "infrastructure_output_hash_manifest.sha256",
            }:
                selected.append(path)
    return selected


def _failure_precommit_files(run_dir: Path, attempt_dir: Path) -> list[Path]:
    recovery_names = {
        "failure_output_precommit.sha256",
        "infrastructure_failure_evidence_v2.json",
        "infrastructure_output_hash_manifest.sha256",
    }
    return [
        path
        for path in _output_files(run_dir, attempt_dir)
        if path.name not in recovery_names
    ]


def _evidence_file_record(root: Path, path: Path) -> dict[str, Any] | None:
    if path.is_symlink():
        raise JobViolation(f"evidence file is a symlink: {path}")
    if not path.is_file():
        return None
    return {
        "path": common.display_path(root, path),
        "sha256": common.sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _analyze_orphan_state_events(
    events: Sequence[Mapping[str, Any]], row: Mapping[str, str]
) -> dict[str, Any]:
    return common.analyze_attempt_state_events(
        events,
        queue_index=int(row["queue_index"]),
        run_id=row["run_id"],
    )


def attempt_intent_hash(payload: Mapping[str, Any]) -> str:
    return common.canonical_json_hash(payload, "attempt_intent_hash")


def attempt_intent_path(root: Path, row: Mapping[str, str]) -> Path:
    token = common.sha256_bytes(row["run_id"].encode("utf-8"))[:20]
    return common.output_path(
        root,
        f"{ATTEMPT_INTENT_ROOT_RELATIVE}/"
        f"queue_{int(row['queue_index']):03d}_{token}_attempt_intent_v1.json",
        label="backend attempt intent",
    )


def build_attempt_intent(
    row: Mapping[str, str],
    *,
    root: Path,
    execution_lock_path: Path,
    execution_lock: Mapping[str, Any],
    registry_path: Path,
    replacement: Mapping[str, Any] | None,
    data_identity_report: Mapping[str, Any],
    b0_play_input_report: Mapping[str, Any] | None,
) -> dict[str, Any]:
    chain = registry_chain(registry_path, row["run_id"])
    if len(chain) != 1 or chain[0]["status"] != "PLANNED":
        raise JobViolation("attempt intent requires an untouched PLANNED registry row")
    execution_hash = execution_lock.get("execution_lock_hash")
    if not isinstance(execution_hash, str) or len(execution_hash) != 64:
        raise JobViolation("attempt intent lacks execution-lock self-hash")
    g0_authority = execution_lock.get(
        common.g0_governance.EXECUTION_LOCK_BINDING_KEY
    )
    if not isinstance(g0_authority, dict) or not isinstance(
        g0_authority.get("evaluation_lock"), dict
    ):
        raise JobViolation("attempt intent lacks pre-replay G0 authority")
    g0_authority_hash = g0_authority.get("g0_execution_authority_hash")
    g0_evaluation_lock_hash = g0_authority["evaluation_lock"].get(
        "evaluation_lock_hash"
    )
    if not all(
        isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
        for value in (g0_authority_hash, g0_evaluation_lock_hash)
    ):
        raise JobViolation("attempt intent G0 authority hashes are invalid")
    payload: dict[str, Any] = {
        "schema_version": ATTEMPT_INTENT_SCHEMA,
        "status": ATTEMPT_INTENT_STATUS,
        "claimed_at": now(),
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "algorithmic_slot": row["algorithmic_slot"],
        "row_sha256": adapter._row_sha256(row),
        "expected_run_dir": row["expected_run_dir"],
        "expected_attempt_dir": row["expected_attempt_dir"],
        "execution_lock_path": common.display_path(root, execution_lock_path),
        "execution_lock_sha256": common.sha256(execution_lock_path),
        "execution_lock_hash": execution_hash,
        "g0_execution_authority_hash": g0_authority_hash,
        "g0_evaluation_lock_hash": g0_evaluation_lock_hash,
        "registry_path": common.display_path(root, registry_path),
        "registry_planned_event_id": chain[0]["registry_event_id"],
        "registry_planned_event_sha256": replacement_allocator.row_hash(chain[0]),
        "replacement": dict(replacement) if replacement is not None else None,
        "data_identity_snapshot_hash": data_identity_report.get(
            "data_identity_snapshot_hash"
        ),
        "data_identity_preflight_sha256": common.sha256_bytes(
            json.dumps(
                dict(data_identity_report),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ),
        "b0_play_input_preflight_sha256": (
            common.sha256_bytes(
                json.dumps(
                    dict(b0_play_input_report),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            if b0_play_input_report is not None
            else None
        ),
        "creator_process": common.process_identity(os.getpid()),
        "replay_started": False,
        "algorithmic_slot_consumed": False,
        "trajectory_outcome_read": False,
        "evaluation_invoked": False,
        "no_clobber": True,
    }
    payload["attempt_intent_hash"] = attempt_intent_hash(payload)
    return payload


def validate_attempt_intent(
    payload: Mapping[str, Any], row: Mapping[str, str]
) -> None:
    creator = payload.get("creator_process")
    if (
        payload.get("schema_version") != ATTEMPT_INTENT_SCHEMA
        or payload.get("status") != ATTEMPT_INTENT_STATUS
        or payload.get("attempt_intent_hash") != attempt_intent_hash(payload)
        or payload.get("queue_index") != int(row["queue_index"])
        or payload.get("run_id") != row["run_id"]
        or payload.get("algorithmic_slot") != row["algorithmic_slot"]
        or payload.get("row_sha256") != adapter._row_sha256(row)
        or payload.get("expected_run_dir") != row["expected_run_dir"]
        or payload.get("expected_attempt_dir") != row["expected_attempt_dir"]
        or payload.get("replay_started") is not False
        or payload.get("algorithmic_slot_consumed") is not False
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("evaluation_invoked") is not False
        or payload.get("no_clobber") is not True
        or not isinstance(payload.get("g0_execution_authority_hash"), str)
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(payload["g0_execution_authority_hash"])
        )
        or not isinstance(payload.get("g0_evaluation_lock_hash"), str)
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(payload["g0_evaluation_lock_hash"])
        )
        or not isinstance(creator, dict)
        or set(creator) != {"pid", "starttime_ticks", "cmdline_sha256"}
        or not isinstance(creator.get("pid"), int)
        or int(creator["pid"]) <= 0
        or not isinstance(creator.get("starttime_ticks"), int)
        or int(creator["starttime_ticks"]) <= 0
        or not isinstance(creator.get("cmdline_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", str(creator["cmdline_sha256"]))
    ):
        raise JobViolation("attempt intent identity or self-hash drift")


def _lock_artifact_paths(root: Path, lock: Mapping[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for record in lock.get("artifacts", []):
        if isinstance(record, dict):
            paths.append(
                common.workspace_path(root, str(record.get("path", "")), label="locked artifact")
            )
    return paths


def _validate_replacement_lock(
    path: Path,
    *,
    root: Path,
    base_row: Mapping[str, str],
    base_allocation: Mapping[str, str],
    execution_lock_path: Path,
    execution_lock: Mapping[str, Any],
    queue_path: Path,
    allocation_path: Path,
    registry_path: Path,
    require_untouched: bool = True,
) -> tuple[dict[str, str], dict[str, Any]]:
    relative = common.display_path(root, path)
    path, lock_content, _lock_identity = common.read_direct_workspace_bytes(
        root, relative, label="replacement lock"
    )
    expected_parent = common.lexical_absolute(
        root
        / "papers/ieee_sensors_journal_experiments/p07/backend_replacements"
    )
    if path.parent != expected_parent:
        raise JobViolation("replacement lock is outside the frozen immutable directory")
    try:
        payload = json.loads(lock_content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JobViolation("invalid replacement lock JSON") from error
    if not isinstance(payload, dict):
        raise JobViolation("replacement lock is not a JSON object")
    try:
        replacement_allocator.validate_replacement_lock_payload(
            payload, expected_relative_path=relative
        )
    except replacement_allocator.ReplacementAllocationError as error:
        raise JobViolation(f"replacement lock validation failed: {error}") from error
    if payload.get("base_queue_row") != dict(base_row):
        raise JobViolation("replacement lock base queue row differs from frozen queue")
    if payload.get("base_allocation_row") != dict(base_allocation):
        raise JobViolation("replacement lock base allocation differs from frozen allocation")
    for field, actual in (
        ("frozen_queue", queue_path),
        ("frozen_allocation", allocation_path),
        ("execution_lock", execution_lock_path),
    ):
        record = payload.get(field)
        if not isinstance(record, dict):
            raise JobViolation(f"replacement lock lacks {field} record")
        _actual_path, actual_content, _actual_identity = (
            common.read_direct_workspace_bytes(
                root,
                common.display_path(root, actual),
                label=f"replacement {field}",
            )
        )
        if (
            record.get("path") != common.display_path(root, actual)
            or record.get("sha256") != common.sha256_bytes(actual_content)
            or int(record.get("size_bytes", -1)) != len(actual_content)
        ):
            raise JobViolation(f"replacement lock {field} record drift")
    execution_record = payload["execution_lock"]
    if execution_record.get("execution_lock_hash") != execution_lock.get(
        "execution_lock_hash"
    ):
        raise JobViolation("replacement/execution-lock self-hash mismatch")
    contract_record = payload.get("replacement_contract")
    binding = execution_lock.get("infrastructure_replacement")
    if not isinstance(contract_record, dict) or not isinstance(binding, dict):
        raise JobViolation("replacement contract binding is absent")
    frozen_contract = binding.get("contract")
    if not isinstance(frozen_contract, dict) or any(
        contract_record.get(key) != frozen_contract.get(key)
        for key in ("path", "sha256", "size_bytes")
    ) or contract_record.get("replacement_contract_hash") != binding.get(
        "replacement_contract_hash"
    ):
        raise JobViolation("replacement contract binding drift")
    _contract_path, contract_content, _contract_identity = (
        common.read_direct_workspace_bytes(
            root,
            str(contract_record.get("path", "")),
            label="replacement contract",
        )
    )
    if (
        common.sha256_bytes(contract_content) != contract_record.get("sha256")
        or len(contract_content) != int(contract_record.get("size_bytes", -1))
    ):
        raise JobViolation("replacement contract artifact drift")

    effective_raw = payload.get("effective_queue_row")
    if not isinstance(effective_raw, dict) or set(effective_raw) != set(base_row):
        raise JobViolation("replacement effective row has a different schema")
    effective = {key: str(value) for key, value in effective_raw.items()}
    common.validate_queue_row(effective)
    changed = {
        key for key in base_row if effective.get(key) != base_row.get(key)
    }
    if changed != set(replacement_allocator.contract.ALLOWED_EFFECTIVE_ROW_OVERRIDES):
        raise JobViolation(f"replacement changed forbidden queue fields: {sorted(changed)}")
    if effective["queue_index"] != base_row["queue_index"]:
        raise JobViolation("replacement changed the queue index")

    index_rows = replacement_allocator.read_index(
        root
        / "papers/ieee_sensors_journal_experiments/p07/"
        "backend_replacement_allocation_v1.csv"
    )
    index_matches = [
        item for item in index_rows if item["replacement_lock_path"] == relative
    ]
    if (
        len(index_matches) != 1
        or index_matches[0]["replacement_lock_sha256"]
        != common.sha256_bytes(lock_content)
        or index_matches[0]["run_id"] != effective["run_id"]
        or index_matches[0]["algorithmic_slot"] != effective["algorithmic_slot"]
    ):
        raise JobViolation("replacement allocation-index binding mismatch")
    planned = payload.get("registry_planned_event")
    if not isinstance(planned, dict):
        raise JobViolation("replacement lock lacks the frozen registry e00")
    chain = registry_chain(registry_path, effective["run_id"])
    if (
        not chain
        or chain[0] != planned
        or chain[0]["status"] != "PLANNED"
        or (require_untouched and (len(chain) != 1 or chain[-1]["status"] != "PLANNED"))
        or (
            not require_untouched
            and chain[-1]["status"] not in {"PLANNED", "RUNNING", "FAILED"}
        )
    ):
        raise JobViolation("replacement registry chain is not authorized for this action")
    failed_run_id = str(payload.get("failed_run_id", ""))
    failed_chain = registry_chain(registry_path, failed_run_id)
    failed_terminal = failed_chain[-1]
    terminal_binding = payload.get("source_registry_terminal_event")
    if (
        not isinstance(terminal_binding, dict)
        or failed_terminal.get("status") != "FAILED"
        or failed_terminal.get("infrastructure_failure") != "true"
        or terminal_binding.get("event_sha256")
        != replacement_allocator.row_hash(failed_terminal)
        or terminal_binding.get("registry_event_id")
        != failed_terminal.get("registry_event_id")
    ):
        raise JobViolation("replacement source terminal registry event drift")
    evidence = payload.get("source_failure_evidence")
    if not isinstance(evidence, dict):
        raise JobViolation("replacement source failure evidence is absent")
    evidence_path = common.workspace_path(
        root, str(evidence.get("path", "")), label="replacement failure evidence"
    )
    if (
        common.sha256(evidence_path) != evidence.get("sha256")
        or evidence_path.stat().st_size != int(evidence.get("size_bytes", -1))
    ):
        raise JobViolation("replacement source failure evidence drift")
    exact_argv = replacement_allocator.exact_job_argv(
        int(base_row["queue_index"]), relative
    )
    if payload.get("job_argv") != exact_argv:
        raise JobViolation("replacement job argv differs from immutable lock")
    return effective, {
        "path": relative,
        "sha256": common.sha256(path),
        "run_id": effective["run_id"],
        "replacement_for": failed_run_id,
        "attempt_number": int(payload["attempt_number"]),
        "job_argv": exact_argv,
        "replacement_lock_hash": payload["replacement_lock_hash"],
    }


def preflight(
    index: int,
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
    registry_path: Path,
    replacement_lock_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, str], dict[str, Any]]:
    lock = common.validate_execution_lock(
        root,
        execution_lock_path,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    common.validate_sealed_runtime_context(
        lock,
        execution_lock_sha256=common.sha256(execution_lock_path),
    )
    base_row, allocation = input_checker.load_bound_row(
        index,
        root=root,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    replacement: dict[str, Any] | None = None
    row = base_row
    if replacement_lock_path is not None:
        row, replacement = _validate_replacement_lock(
            replacement_lock_path,
            root=root,
            base_row=base_row,
            base_allocation=allocation,
            execution_lock_path=execution_lock_path,
            execution_lock=lock,
            queue_path=queue_path,
            allocation_path=allocation_path,
            registry_path=registry_path,
        )
    _validate_registry_allocation(registry_path, allocation, row)
    order = _execution_order(lock)
    _require_predecessors_complete(
        order,
        index,
        queue_path=queue_path,
        registry_path=registry_path,
        root=root,
    )
    _fields, queue_rows = common.read_csv(queue_path)
    capacity = _capacity_report(queue_rows, order, index, root=root, lock=lock)
    run_dir = common.output_path(root, row["expected_run_dir"], label="expected run dir")
    attempt_dir = common.output_path(
        root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    try:
        adapter.assert_ros_port_available(13000 + index)
    except adapter.AdapterViolation as error:
        raise common.InfrastructureWaiting(
            f"backend ROS port gate WAITING before attempt creation: {error}"
        ) from error
    input_report = input_checker.check_row_inputs(row, root=root)
    snapshot = lock.get("data_identity_snapshot")
    if not isinstance(snapshot, dict):
        raise JobViolation("execution lock lacks data-identity snapshot")
    data_identity_report = common.revalidate_data_identity_snapshot(
        root, snapshot, phase="JOB_PREFLIGHT"
    )
    b0_play_input_report = None
    if row["arm"] == common.B0_ARM:
        b0_play_input_report = common.revalidate_b0_play_input(
            root, lock, row, phase="JOB_PREFLIGHT", verify_sha256=False
        )
    run_dir_collision = os.path.lexists(run_dir)
    attempt_dir_collision = os.path.lexists(attempt_dir)
    report = {
        "schema_version": "isj-p07-backend-replay-preflight-v1",
        "status": "PASS"
        if (
            not run_dir_collision
            and not attempt_dir_collision
            and capacity["output_pass"]
            and capacity["governance_pass"]
        )
        else "WAITING_OR_COLLISION",
        "queue_index": index,
        "run_id": row["run_id"],
        "run_dir_collision": run_dir_collision,
        "attempt_dir_collision": attempt_dir_collision,
        "capacity": capacity,
        "input_status": input_report["status"],
        "data_identity": data_identity_report,
        "b0_play_input": b0_play_input_report,
        "replacement": replacement,
    }
    return report, row, allocation, lock


def execute(
    index: int,
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
    registry_path: Path,
    lock_fd: int,
    timeout_s: int,
    replacement_lock_path: Path | None = None,
) -> dict[str, Any]:
    report, row, allocation, lock = preflight(
        index,
        root=root,
        queue_path=queue_path,
        allocation_path=allocation_path,
        execution_lock_path=execution_lock_path,
        registry_path=registry_path,
        replacement_lock_path=replacement_lock_path,
    )
    run_dir = common.output_path(root, row["expected_run_dir"], label="expected run dir")
    attempt_dir = common.output_path(
        root, row["expected_attempt_dir"], label="expected attempt dir"
    )
    if report["run_dir_collision"] or report["attempt_dir_collision"]:
        raise FileExistsError(f"backend no-clobber collision: {report}")
    capacity = report["capacity"]
    if not capacity["output_pass"] or not capacity["governance_pass"]:
        raise common.CapacityWaiting(
            f"backend storage gate WAITING before attempt creation: {capacity}"
        )
    runtime_context = common.validate_sealed_runtime_context(
        lock,
        execution_lock_sha256=common.sha256(execution_lock_path),
    )

    data_identity_report = report.get("data_identity")
    b0_play_input_report = report.get("b0_play_input")
    if not isinstance(data_identity_report, dict):
        raise JobViolation("preflight lacks runtime data-identity evidence")
    if row["arm"] == common.B0_ARM and not isinstance(b0_play_input_report, dict):
        raise JobViolation("B0 preflight lacks frozen play-input evidence")
    replacement = report.get("replacement")
    intent_path = attempt_intent_path(root, row)
    if os.path.lexists(intent_path):
        raise FileExistsError(
            f"backend durable attempt intent already exists; reconcile, do not rerun: {intent_path}"
        )
    intent = build_attempt_intent(
        row,
        root=root,
        execution_lock_path=execution_lock_path,
        execution_lock=lock,
        registry_path=registry_path,
        replacement=replacement if isinstance(replacement, dict) else None,
        data_identity_report=data_identity_report,
        b0_play_input_report=(
            b0_play_input_report if isinstance(b0_play_input_report, dict) else None
        ),
    )
    # The durable exclusive intent is the first job mutation.  A crash after
    # this point is reconciled; the same algorithmic slot is never blindly run.
    common.write_json_exclusive(intent_path, intent)
    attempt_dir.mkdir(parents=True, exist_ok=False)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(mode=0o700, exist_ok=False)
    run_dir_lease = common.snapshot_owned_directory(run_dir, require_empty=True)
    state_journal = attempt_dir / "attempt_state_v1.jsonl"
    common.append_hash_chain_jsonl(
        state_journal,
        {
            "queue_index": index,
            "run_id": row["run_id"],
            "state": "ATTEMPT_DIRECTORIES_CLAIMED",
            "phase": "PRE_ADAPTER",
            "attempt_intent_hash": intent["attempt_intent_hash"],
            "recorded_at": now(),
            "replay_boundary_may_be_crossed": False,
        },
    )
    capacity_path = attempt_dir / "capacity_preflight.json"
    command_path = attempt_dir / "command.json"
    command_log = attempt_dir / "command.log"
    input_manifest = attempt_dir / "input_hash_manifest.sha256"
    output_manifest = attempt_dir / "output_hash_manifest.sha256"
    audit_path = attempt_dir / "audit_v1.json"
    failure_path = attempt_dir / "failure_evidence.json"
    infrastructure_failure_path = (
        attempt_dir / "infrastructure_failure_evidence_v2.json"
    )
    failure_precommit_path = attempt_dir / "failure_output_precommit.sha256"
    infrastructure_output_manifest = (
        attempt_dir / "infrastructure_output_hash_manifest.sha256"
    )
    run_dir_lease_path = attempt_dir / "run_dir_lease.json"
    job_authority_path = attempt_dir / "job_authority_v1.json"
    attempt_intent_binding_path = attempt_dir / "attempt_intent_binding_v1.json"
    data_identity_preflight_path = attempt_dir / "data_identity_preflight.json"
    b0_play_input_preflight_path = attempt_dir / "b0_play_input_preflight.json"
    common.write_json_exclusive(capacity_path, capacity)
    common.write_json_exclusive(data_identity_preflight_path, data_identity_report)
    if isinstance(b0_play_input_report, dict):
        common.write_json_exclusive(
            b0_play_input_preflight_path, b0_play_input_report
        )
    common.write_json_exclusive(
        attempt_intent_binding_path,
        {
            "schema_version": "isj-p07-backend-attempt-intent-binding-v1",
            "path": common.display_path(root, intent_path),
            "sha256": common.sha256(intent_path),
            "attempt_intent_hash": intent["attempt_intent_hash"],
        },
    )
    common.write_json_exclusive(
        run_dir_lease_path,
        {
            "schema_version": "isj-p07-backend-run-dir-lease-v1",
            **run_dir_lease.__dict__,
            "no_clobber": True,
        },
    )
    replay_argv = (
        list(replacement["job_argv"])
        if isinstance(replacement, dict)
        else common.parse_replay_argv(row)
    )
    common.write_json_exclusive(
        command_path,
        {
            "schema_version": "isj-p07-backend-replay-job-command-v1",
            "queue_index": index,
            "run_id": row["run_id"],
            "replay_argv": replay_argv,
            "replay_argv_json": row["replay_argv_json"],
            "replay_argv_sha256": row["replay_argv_sha256"],
            "replacement": replacement,
        },
    )
    input_files = [
        queue_path,
        allocation_path,
        execution_lock_path,
        intent_path,
        attempt_intent_binding_path,
        data_identity_preflight_path,
        *_lock_artifact_paths(root, lock),
    ]
    if b0_play_input_preflight_path.is_file():
        input_files.append(b0_play_input_preflight_path)
    if replacement_lock_path is not None:
        input_files.append(replacement_lock_path)
    if row["arm"] in common.FEATURE_BAG_ARMS:
        input_files.extend(
            common.workspace_path(root, row[field], label=field)
            for field in ("feature_bag", "attestation_path", "input_audit_path")
        )
    _write_hash_manifest(input_manifest, root, input_files)

    running = False
    failure_phase = "PRE_ADAPTER"
    slot_consumption_boundary_crossed = False
    adapter_result: dict[str, Any] | None = None
    try:
        running_event = append_registry_event(
            registry_path,
            row["run_id"],
            expected_status="PLANNED",
            status="RUNNING",
            updates={
                "run_dir": common.display_path(root, run_dir),
                "command_file": common.display_path(root, command_path),
                "input_hash_manifest": common.display_path(root, input_manifest),
                "output_hash_manifest": "",
                "infrastructure_failure": "false",
            },
            note=(
                f"P07 backend replay queue_index={index} entered the governed serial job; "
                "capacity/input/no-clobber preflight PASS"
            ),
        )
        running = True
        common.append_hash_chain_jsonl(
            state_journal,
            {
                "queue_index": index,
                "run_id": row["run_id"],
                "state": "REGISTRY_RUNNING",
                "phase": "PRE_ADAPTER",
                "registry_event_id": running_event["registry_event_id"],
                "recorded_at": now(),
                "replay_boundary_may_be_crossed": False,
            },
        )
        lock_info = os.fstat(lock_fd)
        authority_token = secrets.token_hex(32)
        common.write_json_exclusive(
            job_authority_path,
            {
                "schema_version": adapter.JOB_AUTHORITY_SCHEMA_VERSION,
                "token": authority_token,
                "queue_index": index,
                "run_id": row["run_id"],
                "row_sha256": adapter._row_sha256(row),
                "attempt_dir": common.display_path(root, attempt_dir),
                "run_dir": common.display_path(root, run_dir),
                "run_dir_device": run_dir_lease.device,
                "run_dir_inode": run_dir_lease.inode,
                "global_lock_device": lock_info.st_dev,
                "global_lock_inode": lock_info.st_ino,
                "execution_lock_path": common.display_path(
                    root, execution_lock_path
                ),
                "execution_lock_sha256": common.sha256(execution_lock_path),
                "g0_execution_authority_hash": intent[
                    "g0_execution_authority_hash"
                ],
                "g0_evaluation_lock_hash": intent["g0_evaluation_lock_hash"],
                "registry_path": common.display_path(root, registry_path),
                "registry_event_id": running_event["registry_event_id"],
                "input_hash_manifest_sha256": common.sha256(input_manifest),
                "capacity_preflight_sha256": common.sha256(capacity_path),
                "command_sha256": common.sha256(command_path),
                "attempt_intent_path": common.display_path(root, intent_path),
                "attempt_intent_sha256": common.sha256(intent_path),
                "attempt_intent_hash": intent["attempt_intent_hash"],
                "data_identity_snapshot_hash": data_identity_report[
                    "data_identity_snapshot_hash"
                ],
                "data_identity_preflight_sha256": common.sha256(
                    data_identity_preflight_path
                ),
                "b0_play_input_preflight_sha256": (
                    common.sha256(b0_play_input_preflight_path)
                    if b0_play_input_preflight_path.is_file()
                    else None
                ),
                "attempt_state_journal": common.display_path(root, state_journal),
                "outcome_boundary": (
                    "JOB_AUTHORITY_ONLY_NO_TRAJECTORY_OR_EVALUATION_OUTCOME"
                ),
            },
        )
        job_authority = {
            "path": common.display_path(root, job_authority_path),
            "sha256": common.sha256(job_authority_path),
            "token": authority_token,
        }
        failure_phase = "ADAPTER_RUNNING"
        common.append_hash_chain_jsonl(
            state_journal,
            {
                "queue_index": index,
                "run_id": row["run_id"],
                "state": "ADAPTER_CALL_PENDING",
                "phase": "ADAPTER_RUNNING",
                "recorded_at": now(),
                "replay_boundary_may_be_crossed": False,
            },
        )
        with command_log.open("xb") as log:
            adapter_result = adapter.execute_replay(
                row,
                root=root,
                attempt_dir=attempt_dir,
                lock_fd=lock_fd,
                run_dir_lease=run_dir_lease,
                job_authority=job_authority,
                execution_lock=lock,
                runtime_context=runtime_context,
                state_journal=state_journal,
                timeout_s=timeout_s,
                log=log,
            )
            log.flush()
            os.fsync(log.fileno())
        failure_phase = "ADAPTER_RETURNED"
        common.append_hash_chain_jsonl(
            state_journal,
            {
                "queue_index": index,
                "run_id": row["run_id"],
                "state": "ADAPTER_RETURNED",
                "phase": failure_phase,
                "adapter_status": adapter_result.get("status"),
                "replay_boundary_may_be_crossed": adapter_result.get(
                    "replay_started"
                )
                is True,
                "recorded_at": now(),
            },
        )
        adapter_status = adapter_result.get("status")
        slot_consumption_boundary_crossed = (
            adapter_result.get("replay_started") is True
        )
        if adapter_status in {"FAIL_GOVERNANCE", "FAIL_INPUT_IMMUTABILITY"}:
            raise JobViolation(
                f"adapter failed before algorithmic slot boundary: {adapter_status}"
            )
        if adapter_status not in {
            "PASS_EXECUTION_ENVELOPE",
            "TERMINAL_PROCESS_FAILURE",
        }:
            raise JobViolation(f"adapter returned unknown status: {adapter_status}")
        slot_consumption_boundary_crossed = True
        failure_phase = "AUDIT_STARTED"
        audit = auditor.build_audit(
            row,
            root=root,
            attempt_dir=attempt_dir,
            command_log=command_log,
        )
        common.write_json_exclusive(audit_path, audit)
        failure_phase = "AUDIT_WRITTEN"
        if audit["failure_code"] is not None:
            common.write_json_exclusive(
                failure_path,
                {
                    "schema_version": "isj-p07-backend-replay-failure-evidence-v1",
                    "queue_index": index,
                    "run_id": row["run_id"],
                    "failure_code": audit["failure_code"],
                    "returncode": adapter_result["returncode"],
                    "timed_out": adapter_result["timed_out"],
                    "infrastructure_failure": False,
                    "failure_taxonomy": "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml",
                },
            )
        _write_hash_manifest(
            output_manifest,
            root,
            _output_files(run_dir, attempt_dir),
        )
        failure_phase = "OUTPUT_MANIFEST_WRITTEN"
        updates = {
            "run_dir": common.display_path(root, run_dir),
            "command_file": common.display_path(root, command_path),
            "input_hash_manifest": common.display_path(root, input_manifest),
            "output_hash_manifest": common.display_path(root, output_manifest),
            "infrastructure_failure": "false",
        }
        optional = {
            "replay_hard_failure": str(bool(audit["replay_hard_failure"])).lower(),
            "algorithm_hard_failure": str(bool(audit["replay_hard_failure"])).lower(),
        }
        registry_fields, _rows = _registry_rows(registry_path)
        updates.update({key: value for key, value in optional.items() if key in registry_fields})
        terminal_status = "FAILED" if audit["replay_hard_failure"] else "COMPLETED"
        append_registry_event(
            registry_path,
            row["run_id"],
            expected_status="RUNNING",
            status=terminal_status,
            updates=updates,
            note=(
                f"backend-only adapter and execution-envelope audit PASS; "
                f"terminal_status={terminal_status}; "
                f"failure_code={audit['failure_code']}; "
                f"audit={common.display_path(root, audit_path)}; "
                f"audit_sha256={common.sha256(audit_path)}; "
                f"output_manifest_sha256={common.sha256(output_manifest)}; "
                f"G0 evaluation pending={str(audit['g0_evaluation_pending']).lower()}"
            ),
        )
        failure_phase = "TERMINAL_REGISTRY_WRITTEN"
        return {
            "schema_version": SCHEMA_VERSION,
            "status": terminal_status,
            "queue_index": index,
            "run_id": row["run_id"],
            "arm": row["arm"],
            "run_dir": common.display_path(root, run_dir),
            "attempt_dir": common.display_path(root, attempt_dir),
            "audit": common.display_path(root, audit_path),
            "output_hash_manifest": common.display_path(root, output_manifest),
            "failure_code": audit["failure_code"],
            "g0_evaluation_pending": audit["g0_evaluation_pending"],
        }
    except Exception as error:
        recovery_errors: list[str] = []
        adapter_record_path = attempt_dir / "adapter_result.json"
        if adapter_result is None and adapter_record_path.is_file():
            try:
                candidate = json.loads(adapter_record_path.read_text(encoding="utf-8"))
                if isinstance(candidate, dict):
                    adapter_result = candidate
                    slot_consumption_boundary_crossed = (
                        candidate.get("replay_started") is True
                    )
            except Exception as secondary:
                recovery_errors.append(f"adapter_result_parse: {secondary}")
        infrastructure_category = _classify_infrastructure_error(
            error, adapter_result
        )
        try:
            state_events = common.read_hash_chain_jsonl(state_journal)
        except Exception as secondary:
            state_events = []
            recovery_errors.append(f"attempt_state_parse: {secondary}")
        boundary_may_have_been_crossed = any(
            event.get("replay_boundary_may_be_crossed") is True
            for event in state_events
        )
        active_recorded_process = any(
            isinstance(event.get("process_identity"), dict)
            and common.same_process_alive(event["process_identity"])
            for event in state_events
        )
        pre_adapter_without_result_proven = bool(
            adapter_result is None
            and failure_phase in {"PRE_ADAPTER", "ADAPTER_RUNNING"}
            and not boundary_may_have_been_crossed
            and not active_recorded_process
        )
        replacement_eligible = bool(
            infrastructure_category in INFRASTRUCTURE_CATEGORIES
            and not slot_consumption_boundary_crossed
            and failure_phase
            in {"PRE_ADAPTER", "ADAPTER_RUNNING", "ADAPTER_RETURNED"}
            and (
                pre_adapter_without_result_proven
                or (
                    isinstance(adapter_result, dict)
                    and adapter_result.get("status")
                    in {"FAIL_GOVERNANCE", "FAIL_INPUT_IMMUTABILITY"}
                    and adapter_result.get("replay_started") is False
                )
            )
            and not audit_path.exists()
        )
        failure_code = (
            "EXECUTION_ENVELOPE_FAILURE"
            if not slot_consumption_boundary_crossed
            else "POST_REPLAY_GOVERNANCE_FAILURE"
        )

        try:
            _write_or_validate_manifest(
                failure_precommit_path,
                root,
                [intent_path, *_failure_precommit_files(run_dir, attempt_dir)],
            )
        except Exception as secondary:
            recovery_errors.append(f"failure_precommit: {secondary}")

        try:
            precommit_record = _evidence_file_record(
                root, failure_precommit_path
            )
            if precommit_record is None:
                raise JobViolation("failure output precommit is unavailable")
            infrastructure_payload = {
                "schema_version": (
                    "isj-p07-backend-infrastructure-failure-evidence-v2"
                ),
                "status": (
                    "REPLACEMENT_ELIGIBLE"
                    if replacement_eligible
                    else "QUARANTINED_NOT_AUTOMATICALLY_REPLACEABLE"
                ),
                "queue_index": index,
                "run_id": row["run_id"],
                "window_id": row["window_id"],
                "arm": row["arm"],
                "replay_index": int(row["replay_index"]),
                "algorithmic_slot": row["algorithmic_slot"],
                "failure_class": "INFRASTRUCTURE",
                "failure_code": failure_code,
                "infrastructure_category": infrastructure_category,
                "failure_phase": failure_phase,
                "error_type": type(error).__name__,
                "error": str(error),
                "infrastructure_failure": True,
                "replacement_eligible": replacement_eligible,
                "slot_consumption_boundary_crossed": (
                    slot_consumption_boundary_crossed
                ),
                "algorithmic_slot_consumed": slot_consumption_boundary_crossed,
                "trajectory_outcome_read": False,
                "evaluation_invoked": False,
                "audit_artifact_created": audit_path.is_file(),
                "adapter_result": _evidence_file_record(root, adapter_record_path),
                "attempt_intent": _evidence_file_record(root, intent_path),
                "attempt_state_journal": _evidence_file_record(
                    root, state_journal
                ),
                "pre_adapter_without_result_proven": (
                    pre_adapter_without_result_proven
                ),
                "boundary_may_have_been_crossed": boundary_may_have_been_crossed,
                "active_recorded_process": active_recorded_process,
                "input_hash_manifest": _evidence_file_record(root, input_manifest),
                "failure_output_precommit": precommit_record,
                "prior_output_hash_manifest": _evidence_file_record(
                    root, output_manifest
                ),
                "failure_taxonomy": (
                    "papers/ieee_sensors_journal_experiments/"
                    "failure_taxonomy_v1.yaml"
                ),
            }
            _write_or_validate_json(
                infrastructure_failure_path, infrastructure_payload
            )
        except Exception as secondary:
            recovery_errors.append(f"infrastructure_failure_evidence: {secondary}")

        try:
            _write_or_validate_manifest(
                infrastructure_output_manifest,
                root,
                _output_files(run_dir, attempt_dir),
            )
        except Exception as secondary:
            recovery_errors.append(f"infrastructure_output_manifest: {secondary}")

        if not recovery_errors:
            try:
                chain = registry_chain(registry_path, row["run_id"])
                latest_status = chain[-1]["status"]
                if latest_status in {"PLANNED", "RUNNING"}:
                    registry_fields, _rows = _registry_rows(registry_path)
                    failure_updates = {
                        "run_dir": common.display_path(root, run_dir),
                        "command_file": common.display_path(root, command_path),
                        "input_hash_manifest": common.display_path(root, input_manifest),
                        "output_hash_manifest": common.display_path(
                            root, infrastructure_output_manifest
                        ),
                        "infrastructure_failure": "true",
                    }
                    optional_failure_updates = {
                        "replay_evaluable": "false",
                        "replay_hard_failure": "false",
                        "algorithm_hard_failure": "false",
                    }
                    failure_updates.update(
                        {
                            key: value
                            for key, value in optional_failure_updates.items()
                            if key in registry_fields
                        }
                    )
                    append_registry_event(
                        registry_path,
                        row["run_id"],
                        expected_status=latest_status,
                        status="FAILED",
                        updates=failure_updates,
                        note=(
                            "P07 backend job failed closed as infrastructure; "
                            f"failure_phase={failure_phase}; "
                            "replacement_eligible="
                            f"{str(replacement_eligible).lower()}; "
                            "slot_consumption_boundary_crossed="
                            f"{str(slot_consumption_boundary_crossed).lower()}; "
                            f"{type(error).__name__}: {error}"
                        ),
                    )
                elif latest_status not in {"FAILED", "COMPLETED"}:
                    raise JobViolation(
                        f"cannot recover unexpected registry status: {latest_status}"
                    )
            except Exception as secondary:
                recovery_errors.append(f"terminal_registry: {secondary}")

        if recovery_errors:
            raise JobViolation(
                "backend infrastructure recovery was incomplete; "
                f"original={type(error).__name__}: {error}; "
                f"secondary={recovery_errors}"
            ) from error
        raise


def reconcile_orphan(
    index: int,
    *,
    root: Path,
    queue_path: Path,
    allocation_path: Path,
    execution_lock_path: Path,
    registry_path: Path,
    replacement_lock_path: Path | None = None,
) -> dict[str, Any]:
    """Close one durable orphan without launching, deleting, or reading metrics.

    Automatic replacement eligibility is granted only when the append-only
    state journal proves that no replay launch could have occurred.  Any live
    recorded child or an unpaired process-launch gap remains WAITING.
    """

    lock = common.validate_execution_lock(
        root,
        execution_lock_path,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    common.validate_sealed_runtime_context(
        lock,
        execution_lock_sha256=common.sha256(execution_lock_path),
    )
    base_row, allocation = input_checker.load_bound_row(
        index,
        root=root,
        queue_path=queue_path,
        allocation_path=allocation_path,
    )
    row = base_row
    replacement: dict[str, Any] | None = None
    if replacement_lock_path is not None:
        row, replacement = _validate_replacement_lock(
            replacement_lock_path,
            root=root,
            base_row=base_row,
            base_allocation=allocation,
            execution_lock_path=execution_lock_path,
            execution_lock=lock,
            queue_path=queue_path,
            allocation_path=allocation_path,
            registry_path=registry_path,
            require_untouched=False,
        )
    intent_path = attempt_intent_path(root, row)
    if intent_path.is_symlink() or not intent_path.is_file():
        raise JobViolation("orphan reconcile lacks a plain durable attempt intent")
    try:
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JobViolation("invalid orphan attempt intent JSON") from error
    if not isinstance(intent, dict):
        raise JobViolation("orphan attempt intent is not an object")
    validate_attempt_intent(intent, row)
    snapshot = lock.get("data_identity_snapshot")
    if not isinstance(snapshot, dict):
        raise JobViolation("orphan execution lock lacks data-identity snapshot")
    if (
        intent.get("execution_lock_path") != common.display_path(root, execution_lock_path)
        or intent.get("execution_lock_sha256") != common.sha256(execution_lock_path)
        or intent.get("execution_lock_hash") != lock.get("execution_lock_hash")
        or intent.get("registry_path") != common.display_path(root, registry_path)
        or intent.get("data_identity_snapshot_hash")
        != snapshot.get(common.DATA_IDENTITY_SELF_HASH)
        or intent.get("g0_execution_authority_hash")
        != lock[common.g0_governance.EXECUTION_LOCK_BINDING_KEY].get(
            "g0_execution_authority_hash"
        )
        or intent.get("g0_evaluation_lock_hash")
        != lock[common.g0_governance.EXECUTION_LOCK_BINDING_KEY]
        .get("evaluation_lock", {})
        .get("evaluation_lock_hash")
        or intent.get("replacement") != replacement
    ):
        raise JobViolation("orphan attempt intent parent binding drift")
    creator = intent.get("creator_process")
    assert isinstance(creator, dict)
    if common.same_process_alive(creator):
        raise common.InfrastructureWaiting("attempt owner is still alive; reconcile refused")

    attempt_dir = common.output_path(
        root, row["expected_attempt_dir"], label="orphan attempt directory"
    )
    run_dir = common.output_path(root, row["expected_run_dir"], label="orphan run directory")
    if os.path.lexists(attempt_dir) and (
        attempt_dir.is_symlink() or not attempt_dir.is_dir()
    ):
        raise JobViolation("orphan attempt path is not a plain directory")
    if os.path.lexists(run_dir):
        if run_dir.is_symlink() or not run_dir.is_dir():
            raise JobViolation("orphan run path is not a plain directory")
        common.snapshot_owned_directory(run_dir, require_empty=False)
    state_journal = attempt_dir / "attempt_state_v1.jsonl"
    events = common.read_hash_chain_jsonl(state_journal) if attempt_dir.exists() else []
    state_analysis = _analyze_orphan_state_events(events, row)
    if state_analysis["active_processes"]:
        raise common.InfrastructureWaiting(
            "recorded backend child remains alive; orphan reconcile refused"
        )
    if state_analysis["unpaired_launch_pending"]:
        raise common.InfrastructureWaiting(
            "process launch was pending without a captured PID; external orphan closeout required"
        )
    boundary_may_have_been_crossed = bool(
        state_analysis["boundary_may_have_been_crossed"]
    )
    replacement_eligible = not boundary_may_have_been_crossed

    chain = registry_chain(registry_path, row["run_id"])
    if (
        intent.get("registry_planned_event_id") != chain[0].get("registry_event_id")
        or intent.get("registry_planned_event_sha256")
        != replacement_allocator.row_hash(chain[0])
    ):
        raise JobViolation("orphan attempt intent/registry e00 binding drift")
    if chain[-1]["status"] not in {"PLANNED", "RUNNING", "FAILED"}:
        raise JobViolation(
            "orphan reconcile requires PLANNED/RUNNING or its own completed "
            f"FAILED closeout, got {chain[-1]['status']}"
        )
    terminal_existing: dict[str, str] | None = None
    if chain[-1]["status"] == "FAILED":
        expected_output = common.display_path(
            root, attempt_dir / "infrastructure_output_hash_manifest.sha256"
        )
        expected_intent = common.display_path(root, intent_path)
        latest = chain[-1]
        if (
            latest.get("output_hash_manifest") != expected_output
            or latest.get("infrastructure_failure") != "true"
            or "P07 backend orphan reconciled without execution" not in latest.get(
                "notes", ""
            )
            or f"attempt_intent={expected_intent}" not in latest.get("notes", "")
        ):
            raise JobViolation(
                "FAILED registry row is not this orphan closeout; reconcile refused"
            )
        terminal_existing = latest
    frozen_preflight = common.revalidate_data_identity_snapshot(
        root, snapshot, phase="JOB_PREFLIGHT"
    )
    frozen_preflight_hash = common.sha256_bytes(
        json.dumps(
            frozen_preflight,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    )
    if intent.get("data_identity_preflight_sha256") != frozen_preflight_hash:
        raise JobViolation("orphan attempt intent/data preflight binding drift")
    data_identity = common.revalidate_data_identity_snapshot(
        root, snapshot, phase="ORPHAN_RECONCILE"
    )
    b0_report: dict[str, Any] | None = None
    if row["arm"] == common.B0_ARM:
        frozen_b0_preflight = common.revalidate_b0_play_input(
            root, lock, row, phase="JOB_PREFLIGHT", verify_sha256=False
        )
        frozen_b0_hash = common.sha256_bytes(
            json.dumps(
                frozen_b0_preflight,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )
        if intent.get("b0_play_input_preflight_sha256") != frozen_b0_hash:
            raise JobViolation("orphan attempt intent/B0 preflight binding drift")
        b0_report = common.revalidate_b0_play_input(
            root,
            lock,
            row,
            phase="ORPHAN_RECONCILE",
            verify_sha256=False,
        )
    elif intent.get("b0_play_input_preflight_sha256") is not None:
        raise JobViolation("non-B0 orphan intent contains a B0 preflight binding")
    if not attempt_dir.exists():
        attempt_dir.mkdir(parents=True, exist_ok=False)
    else:
        common.snapshot_owned_directory(attempt_dir, require_empty=False)
    current_events = common.read_hash_chain_jsonl(state_journal)
    reconcile_started = [
        event
        for event in current_events
        if event.get("state") == "ORPHAN_RECONCILE_STARTED"
    ]
    if len(reconcile_started) > 1:
        raise JobViolation("orphan reconcile start event is duplicated")
    if reconcile_started:
        started = reconcile_started[0]
        expected_phase = "PRE_ADAPTER" if replacement_eligible else "ADAPTER_RUNNING"
        if (
            started.get("queue_index") != index
            or started.get("run_id") != row["run_id"]
            or started.get("phase") != expected_phase
            or started.get("attempt_intent_hash") != intent["attempt_intent_hash"]
            or started.get("replay_boundary_may_be_crossed")
            is not boundary_may_have_been_crossed
        ):
            raise JobViolation("orphan reconcile start event binding drift")
    else:
        common.append_hash_chain_jsonl(
            state_journal,
            {
                "queue_index": index,
                "run_id": row["run_id"],
                "state": "ORPHAN_RECONCILE_STARTED",
                "phase": "PRE_ADAPTER" if replacement_eligible else "ADAPTER_RUNNING",
                "attempt_intent_hash": intent["attempt_intent_hash"],
                "recorded_at": now(),
                "replay_boundary_may_be_crossed": boundary_may_have_been_crossed,
            },
        )
    data_identity_path = attempt_dir / "data_identity_orphan_reconcile.json"
    _write_or_validate_json(data_identity_path, data_identity)
    b0_path: Path | None = None
    if b0_report is not None:
        b0_path = attempt_dir / "b0_play_input_orphan_reconcile.json"
        _write_or_validate_json(b0_path, b0_report)

    command_path = attempt_dir / "command.json"
    command_payload = {
        "schema_version": "isj-p07-backend-orphan-reconcile-command-v1",
        "queue_index": index,
        "run_id": row["run_id"],
        "action": "RECONCILE_ORPHAN_NO_EXECUTION",
        "replacement": replacement,
        "trajectory_outcome_read": False,
        "evaluation_invoked": False,
    }
    _write_or_validate_json(command_path, command_payload)
    input_manifest = attempt_dir / "input_hash_manifest.sha256"
    input_files = [
        queue_path,
        allocation_path,
        execution_lock_path,
        intent_path,
        data_identity_path,
        *_lock_artifact_paths(root, lock),
    ]
    if b0_path is not None:
        input_files.append(b0_path)
    if replacement_lock_path is not None:
        input_files.append(replacement_lock_path)
    _write_or_validate_manifest(input_manifest, root, input_files)
    current_events = common.read_hash_chain_jsonl(state_journal)
    reconcile_decisions = [
        event
        for event in current_events
        if event.get("state") == "ORPHAN_RECONCILE_DECISION_FROZEN"
    ]
    if len(reconcile_decisions) > 1:
        raise JobViolation("orphan reconcile decision event is duplicated")
    if reconcile_decisions:
        decision = reconcile_decisions[0]
        if (
            decision.get("queue_index") != index
            or decision.get("run_id") != row["run_id"]
            or decision.get("phase")
            != ("PRE_ADAPTER" if replacement_eligible else "ADAPTER_RUNNING")
            or decision.get("replacement_eligible") is not replacement_eligible
            or decision.get("replay_boundary_may_be_crossed")
            is not boundary_may_have_been_crossed
        ):
            raise JobViolation("orphan reconcile frozen decision drift")
    else:
        common.append_hash_chain_jsonl(
            state_journal,
            {
                "queue_index": index,
                "run_id": row["run_id"],
                "state": "ORPHAN_RECONCILE_DECISION_FROZEN",
                "phase": "PRE_ADAPTER" if replacement_eligible else "ADAPTER_RUNNING",
                "replacement_eligible": replacement_eligible,
                "recorded_at": now(),
                "replay_boundary_may_be_crossed": boundary_may_have_been_crossed,
            },
        )
    adapter_path = attempt_dir / "adapter_result.json"
    adapter_record = _evidence_file_record(root, adapter_path)
    precommit_files = [
        intent_path,
        state_journal,
        data_identity_path,
        command_path,
        input_manifest,
    ]
    if b0_path is not None:
        precommit_files.append(b0_path)
    if adapter_record is not None:
        precommit_files.append(adapter_path)
    failure_precommit = attempt_dir / "failure_output_precommit.sha256"
    _write_or_validate_manifest(failure_precommit, root, precommit_files)
    evidence_path = attempt_dir / "infrastructure_failure_evidence_v2.json"
    evidence_payload = {
        "schema_version": "isj-p07-backend-infrastructure-failure-evidence-v2",
        "status": (
            "REPLACEMENT_ELIGIBLE"
            if replacement_eligible
            else "QUARANTINED_NOT_AUTOMATICALLY_REPLACEABLE"
        ),
        "queue_index": index,
        "run_id": row["run_id"],
        "window_id": row["window_id"],
        "arm": row["arm"],
        "replay_index": int(row["replay_index"]),
        "algorithmic_slot": row["algorithmic_slot"],
        "failure_class": "INFRASTRUCTURE",
        "failure_code": "EXECUTION_ENVELOPE_FAILURE",
        "infrastructure_category": "SUPERVISOR_PROCESS_LOSS",
        "failure_phase": "PRE_ADAPTER" if replacement_eligible else "ADAPTER_RUNNING",
        "error_type": "SupervisorProcessLoss",
        "error": "durable attempt owner disappeared before terminal closeout",
        "infrastructure_failure": True,
        "replacement_eligible": replacement_eligible,
        "slot_consumption_boundary_crossed": boundary_may_have_been_crossed,
        "algorithmic_slot_consumed": boundary_may_have_been_crossed,
        "trajectory_outcome_read": False,
        "evaluation_invoked": False,
        "audit_artifact_created": False,
        "adapter_result": adapter_record,
        "attempt_intent": _evidence_file_record(root, intent_path),
        "attempt_state_journal": _evidence_file_record(root, state_journal),
        "pre_adapter_without_result_proven": (
            replacement_eligible and adapter_record is None
        ),
        "boundary_may_have_been_crossed": boundary_may_have_been_crossed,
        "active_recorded_process": False,
        "input_hash_manifest": _evidence_file_record(root, input_manifest),
        "failure_output_precommit": _evidence_file_record(root, failure_precommit),
        "prior_output_hash_manifest": None,
        "orphan_reconciled": True,
        "failure_taxonomy": (
            "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml"
        ),
    }
    _write_or_validate_json(evidence_path, evidence_payload)
    output_manifest = attempt_dir / "infrastructure_output_hash_manifest.sha256"
    output_files = [
        intent_path,
        state_journal,
        data_identity_path,
        command_path,
        input_manifest,
        failure_precommit,
        evidence_path,
    ]
    if b0_path is not None:
        output_files.append(b0_path)
    if adapter_record is not None:
        output_files.append(adapter_path)
    _write_or_validate_manifest(output_manifest, root, output_files)
    fields, _rows = _registry_rows(registry_path)
    updates = {
        "run_dir": common.display_path(root, run_dir),
        "command_file": common.display_path(root, command_path),
        "input_hash_manifest": common.display_path(root, input_manifest),
        "output_hash_manifest": common.display_path(root, output_manifest),
        "infrastructure_failure": "true",
    }
    updates.update(
        {
            key: value
            for key, value in {
                "replay_evaluable": "false",
                "replay_hard_failure": "false",
                "algorithm_hard_failure": "false",
            }.items()
            if key in fields
        }
    )
    if terminal_existing is not None:
        mismatches = {
            key: {"expected": value, "observed": terminal_existing.get(key)}
            for key, value in updates.items()
            if terminal_existing.get(key) != value
        }
        if mismatches:
            raise JobViolation(
                f"completed orphan registry closeout binding drift: {mismatches}"
            )
        terminal = terminal_existing
    else:
        terminal = append_registry_event(
            registry_path,
            row["run_id"],
            expected_status=chain[-1]["status"],
            status="FAILED",
            updates=updates,
            note=(
                "P07 backend orphan reconciled without execution or outcome evaluation; "
                f"replacement_eligible={str(replacement_eligible).lower()}; "
                f"attempt_intent={common.display_path(root, intent_path)}"
            ),
        )
    return {
        "schema_version": "isj-p07-backend-orphan-reconcile-result-v1",
        "status": "FAILED_CLOSED_RECONCILED",
        "queue_index": index,
        "run_id": row["run_id"],
        "registry_event_id": terminal["registry_event_id"],
        "replacement_eligible": replacement_eligible,
        "algorithmic_slot_consumed": boundary_may_have_been_crossed,
        "attempt_intent": common.display_path(root, intent_path),
        "failure_evidence": common.display_path(root, evidence_path),
        "output_hash_manifest": common.display_path(root, output_manifest),
        "trajectory_outcome_read": False,
        "evaluation_invoked": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument(
        "--execution-lock", type=Path, default=common.DEFAULT_EXECUTION_LOCK
    )
    parser.add_argument("--replacement-lock", type=Path)
    parser.add_argument("--root", type=Path, default=common.ROOT)
    parser.add_argument("--queue", type=Path, default=common.DEFAULT_QUEUE)
    parser.add_argument("--allocation", type=Path, default=common.DEFAULT_ALLOCATION)
    parser.add_argument("--registry", type=Path, default=common.DEFAULT_REGISTRY)
    parser.add_argument("--timeout-s", type=int, default=FROZEN_TIMEOUT_S)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--reconcile-orphan", action="store_true")
    args = parser.parse_args()
    if args.preflight_only and args.reconcile_orphan:
        parser.error("--preflight-only and --reconcile-orphan are mutually exclusive")
    try:
        validate_formal_cli_contract(
            root=args.root,
            queue_path=args.queue,
            allocation_path=args.allocation,
            execution_lock_path=args.execution_lock,
            registry_path=args.registry,
            timeout_s=args.timeout_s,
            replacement_lock_path=args.replacement_lock,
        )
        with common.global_execution_lock() as lock_fd:
            if args.reconcile_orphan:
                result = reconcile_orphan(
                    args.queue_index,
                    root=args.root,
                    queue_path=args.queue,
                    allocation_path=args.allocation,
                    execution_lock_path=args.execution_lock,
                    registry_path=args.registry,
                    replacement_lock_path=args.replacement_lock,
                )
                print(json.dumps(result, indent=2, sort_keys=True))
                return 0
            if args.preflight_only:
                report, _row, _allocation, _lock = preflight(
                    args.queue_index,
                    root=args.root,
                    queue_path=args.queue,
                    allocation_path=args.allocation,
                    execution_lock_path=args.execution_lock,
                    registry_path=args.registry,
                    replacement_lock_path=args.replacement_lock,
                )
                print(json.dumps(report, indent=2, sort_keys=True))
                return 0 if report["status"] == "PASS" else 75
            result = execute(
                args.queue_index,
                root=args.root,
                queue_path=args.queue,
                allocation_path=args.allocation,
                execution_lock_path=args.execution_lock,
                registry_path=args.registry,
                lock_fd=lock_fd,
                timeout_s=args.timeout_s,
                replacement_lock_path=args.replacement_lock,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except (
        common.CapacityWaiting,
        common.InfrastructureWaiting,
        common.LockBusy,
    ) as error:
        print(f"P07_BACKEND_WAITING: {error}", file=os.sys.stderr)
        return 75
    except (common.BackendReplayViolation, FileExistsError) as error:
        print(f"P07_BACKEND_FAIL_CLOSED: {error}", file=os.sys.stderr)
        return 64


if __name__ == "__main__":
    raise SystemExit(main())
