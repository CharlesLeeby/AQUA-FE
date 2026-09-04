#!/usr/bin/env python3
"""Append frozen P07 backend allocations to the canonical run registry."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import stat
from pathlib import Path
from typing import Mapping, Sequence

try:
    from scripts import build_p07_backend_replay_queue_v1 as builder
    from scripts import validate_p07_backend_replay_queue_v1 as validator
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_backend_replay_queue_v1 as builder  # type: ignore
    import validate_p07_backend_replay_queue_v1 as validator  # type: ignore


RUN_REGISTRY = builder.RUN_REGISTRY
REPORT = builder.P07 / "backend_registration_v1.json"
INTENT = builder.P07 / "backend_registration_intent_v1.json"
STAGE = "P07_BACKEND_REPLAY"
SCHEMA = "isj-p07-backend-registration-v1"
INTENT_SCHEMA = "isj-p07-backend-registration-intent-v1"
INTENT_STATUS = "FROZEN_BEFORE_CANONICAL_REGISTRY_APPEND"

ARM_VERSION = {
    builder.B0: "vins-origin-v1",
    builder.B1: "nativeq-v3",
    builder.P_ARM: "actual-v3",
    builder.M_ARM: "xfeat-pairwise-nativeq-v1",
    builder.D_ARM: "exact-lineage-drop-v3",
}


def _document_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return builder.sha256_bytes(builder.canonical_json(clone).encode("utf-8"))


def _parse_csv_content(
    path: Path, content: bytes
) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ValueError(f"invalid canonical CSV: {path}")
    return fields, rows


def read_csv_with_fields(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    content = _read_absolute_direct_bytes(path, label="canonical CSV")
    return _parse_csv_content(path, content)


def _read_absolute_direct_bytes(path: Path, *, label: str) -> bytes:
    absolute = path.absolute()
    try:
        parent_fd = builder.rooted_io._open_absolute_directory(
            absolute.parent, label=f"{label} parent"
        )
    except builder.rooted_io.gov.G0GovernanceError as error:
        raise ValueError(f"unsafe {label} parent: {absolute}") from error
    descriptor = -1
    try:
        before = os.stat(absolute.name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise ValueError(f"{label} is not a direct single-link file: {absolute}")
        descriptor = os.open(
            absolute.name,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if builder.rooted_io._identity_tuple(opened) != builder.rooted_io._identity_tuple(
            before
        ):
            raise ValueError(f"{label} changed before read: {absolute}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        reachable = os.stat(
            absolute.name, dir_fd=parent_fd, follow_symlinks=False
        )
        if (
            builder.rooted_io._identity_tuple(after)
            != builder.rooted_io._identity_tuple(opened)
            or builder.rooted_io._identity_tuple(reachable)
            != builder.rooted_io._identity_tuple(opened)
            or len(content) != opened.st_size
        ):
            raise ValueError(f"{label} changed while reading: {absolute}")
        _assert_absolute_leaf_reachable(absolute, after, label=label)
        return content
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)


def _assert_absolute_leaf_reachable(
    path: Path, expected: os.stat_result, *, label: str
) -> None:
    """Reopen an absolute leaf from ``/`` and require the same exact inode state."""

    absolute = path.absolute()
    try:
        parent_fd = builder.rooted_io._open_absolute_directory(
            absolute.parent, label=f"{label} reachability parent"
        )
    except builder.rooted_io.gov.G0GovernanceError as error:
        raise ValueError(f"{label} parent is no longer directly reachable") from error
    try:
        observed = os.stat(
            absolute.name, dir_fd=parent_fd, follow_symlinks=False
        )
    finally:
        os.close(parent_fd)
    if builder.rooted_io._identity_tuple(observed) != builder.rooted_io._identity_tuple(
        expected
    ):
        raise ValueError(f"{label} is no longer directly reachable")


def build_registry_rows(
    queue_rows: Sequence[Mapping[str, str]],
    allocation_rows: Sequence[Mapping[str, str]],
    *,
    registry_fields: Sequence[str],
    split_roles: Mapping[str, str],
) -> list[dict[str, str]]:
    queue_by_index = {int(row["queue_index"]): row for row in queue_rows}
    if len(queue_by_index) != len(queue_rows):
        raise ValueError("backend queue indices are not unique")
    intended: list[dict[str, str]] = []
    for allocation in allocation_rows:
        index = int(allocation["queue_index"])
        queue = queue_by_index.get(index)
        if queue is None or queue["run_id"] != allocation["run_id"]:
            raise ValueError(f"backend queue/allocation mismatch: {index}")
        arm = allocation["arm"]
        values = {
            "run_id": allocation["run_id"],
            "registry_event_id": f"{allocation['run_id']}_e00",
            "recorded_at": allocation["allocated_at"],
            "supersedes_event_id": "",
            "protocol_version": builder.PROTOCOL,
            "method_profile": arm,
            "stage": STAGE,
            "dataset_family": allocation["dataset_family"],
            "sequence": allocation["sequence"],
            "window_start": allocation["window_start_s"],
            "window_end": allocation["window_end_s"],
            "texture_stratum": queue["texture_stratum"],
            "split_role": split_roles[allocation["window_id"]],
            "arm": arm,
            "arm_version": ARM_VERSION[arm],
            "arm_applicability": "APPLICABLE" if arm == builder.D_ARM else "REQUIRED",
            "applicability_rule": (
                "accepted_learned_born_lineage_count>0"
                if arm == builder.D_ARM
                else "ALWAYS"
            ),
            "frontend_seed": "0",
            "backend_replay": allocation["backend_replay"],
            "status": "PLANNED",
            "replay_evaluable": "false",
            "run_dir": allocation["expected_run_dir"],
            "command_file": (
                "papers/ieee_sensors_journal_experiments/p07/"
                f"backend_replay_queue_v1.csv#queue_index={index}"
            ),
            "input_hash_manifest": (
                "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json"
            ),
            "notes": (
                f"window_id={allocation['window_id']}; replay_index={allocation['replay_index']}; "
                f"algorithmic_slot={allocation['algorithmic_slot']}; "
                f"backend_queue_lock_hash={allocation['backend_queue_lock_hash']}; "
                "trajectory outcome unread at allocation"
            ),
        }
        unknown = set(values).difference(registry_fields)
        if unknown:
            raise ValueError(f"run registry header missing fields: {sorted(unknown)}")
        intended.append({field: values.get(field, "") for field in registry_fields})
    if len(intended) != len(queue_rows) or len({row["run_id"] for row in intended}) != len(
        intended
    ):
        raise ValueError("backend registration rows are incomplete or duplicate")
    return intended


def _row_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def append_missing(
    path: Path,
    intended: Sequence[dict[str, str]],
    *,
    key_field: str = "registry_event_id",
    expected_prefix: Mapping[str, object] | None = None,
) -> int:
    flags = os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW
    absolute = path.absolute()
    try:
        parent_fd = builder.rooted_io._open_absolute_directory(
            absolute.parent, label="canonical registry parent"
        )
    except builder.rooted_io.gov.G0GovernanceError as error:
        raise ValueError(f"canonical registry parent is unsafe: {path}") from error
    try:
        fd = os.open(absolute.name, flags, dir_fd=parent_fd)
        path_info = os.stat(
            absolute.name, dir_fd=parent_fd, follow_symlinks=False
        )
    except BaseException:
        os.close(parent_fd)
        raise
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(path_info.st_mode)
        or info.st_nlink != 1
        or info.st_dev != path_info.st_dev
        or info.st_ino != path_info.st_ino
    ):
        os.close(fd)
        os.close(parent_fd)
        raise ValueError(f"canonical registry is not a direct regular file: {path}")
    with os.fdopen(fd, "r+b", buffering=0) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            content = handle.read()
            if expected_prefix is not None:
                size = int(expected_prefix["size_bytes"])
                if (
                    len(content) < size
                    or hashlib.sha256(content[:size]).hexdigest()
                    != expected_prefix["sha256"]
                ):
                    raise ValueError("canonical registry prefix drift before registration")
            reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
            fields = list(reader.fieldnames or [])
            existing = list(reader)
            if (
                not fields
                or len(fields) != len(set(fields))
                or any(None in row for row in existing)
                or (content and not content.endswith(b"\n"))
            ):
                raise ValueError(f"invalid append-only registry: {path}")
            by_key = {row[key_field]: row for row in existing}
            missing: list[dict[str, str]] = []
            for row in intended:
                observed = by_key.get(row[key_field])
                if observed is None:
                    missing.append(row)
                elif observed != row:
                    raise ValueError(
                        f"canonical registry collision with different content: {row[key_field]}"
                    )
            if not missing:
                _assert_absolute_leaf_reachable(
                    absolute,
                    os.fstat(handle.fileno()),
                    label="canonical registry",
                )
                return 0
            handle.seek(0, os.SEEK_END)
            handle.write(_row_bytes(fields, missing))
            os.fsync(handle.fileno())
            _assert_absolute_leaf_reachable(
                absolute,
                os.fstat(handle.fileno()),
                label="canonical registry",
            )
            return len(missing)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            os.close(parent_fd)


def validate_registered(
    intended: Sequence[Mapping[str, str]], registry_rows: Sequence[Mapping[str, str]]
) -> dict[str, object]:
    by_run: dict[str, list[Mapping[str, str]]] = {}
    intended_ids = {row["run_id"] for row in intended}
    for row in registry_rows:
        if row["run_id"] in intended_ids:
            by_run.setdefault(row["run_id"], []).append(row)
    valid = 0
    for row in intended:
        chain = by_run.get(row["run_id"], [])
        if len(chain) == 1 and chain[0] == row and chain[0]["status"] == "PLANNED":
            valid += 1
    return {
        "intended_backend_runs": len(intended),
        "unique_untouched_planned_e00": valid,
        "pass": valid == len(intended),
    }


def _live_inputs() -> tuple[
    list[dict[str, str]],
    list[dict[str, str]],
    list[str],
    dict[str, str],
    dict[str, object],
    dict[str, dict[str, object]],
]:
    queue_content, queue_record = (
        builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            builder.ROOT, builder.BACKEND_QUEUE, label="backend registration queue"
        )
    )
    allocation_content, allocation_record = (
        builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            builder.ROOT,
            builder.BACKEND_ALLOCATION,
            label="backend registration allocation",
        )
    )
    lock_content, lock_record = (
        builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            builder.ROOT,
            builder.BACKEND_QUEUE_LOCK,
            label="backend registration queue lock",
        )
    )
    validation_content, validation_record = (
        builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            builder.ROOT,
            builder.BACKEND_QUEUE_VALIDATION,
            label="backend registration queue validation",
        )
    )
    arm_content = builder.rooted_io.read_bytes_bound_input_rooted(
        builder.ROOT, builder.ARM_ORDER, label="backend registration arm order"
    )
    split_path = builder.P07 / "split_role_audit_v1.csv"
    split_content, split_record = (
        builder.rooted_io.read_bytes_and_record_bound_input_rooted(
            builder.ROOT, split_path, label="backend registration split roles"
        )
    )
    queue_fields, queue_rows = validator.parse_csv(queue_content)
    allocation_fields, allocation_rows = validator.parse_csv(allocation_content)
    if queue_fields != builder.QUEUE_FIELDS or allocation_fields != builder.ALLOCATION_FIELDS:
        raise ValueError("backend queue/allocation header drift")
    lock = json.loads(lock_content)
    _arm_fields, arm_rows = builder._parse_csv_content(builder.ARM_ORDER, arm_content)
    issues = validator.validate_artifacts(
        queue_content=queue_content,
        allocation_content=allocation_content,
        lock_payload=lock,
        arm_order_rows=arm_rows,
    )
    if issues:
        raise ValueError(f"backend queue is not valid for registration: {issues}")
    saved_validation = json.loads(validation_content)
    deterministic = saved_validation.get("deterministic_live_rebuild")
    artifacts = saved_validation.get("artifacts")
    if (
        saved_validation.get("schema_version") != validator.REPORT_SCHEMA
        or saved_validation.get("status") != "PASS"
        or saved_validation.get("backend_queue_lock_hash")
        != lock.get("backend_queue_lock_hash")
        or saved_validation.get("live_rebuild_requested") is not True
        or saved_validation.get("issues") != []
        or not isinstance(deterministic, dict)
        or set(deterministic) != {
            "queue_byte_identical",
            "allocation_byte_identical",
            "queue_lock_semantic_identical",
        }
        or not all(value is True for value in deterministic.values())
        or not isinstance(artifacts, dict)
        or artifacts.get("queue_sha256") != queue_record["sha256"]
        or artifacts.get("allocation_sha256")
        != allocation_record["sha256"]
        or artifacts.get("queue_lock_sha256")
        != lock_record["sha256"]
        or saved_validation.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ValueError("saved backend queue validation is not a bound live PASS")
    fields, _registry = read_csv_with_fields(RUN_REGISTRY)
    _split_fields, split_rows = builder._parse_csv_content(split_path, split_content)
    split_roles = {
        row["window_id"]: row["corrected_split_role"]
        for row in split_rows
    }
    return queue_rows, allocation_rows, fields, split_roles, lock, {
        "backend_queue": dict(queue_record),
        "backend_allocation": dict(allocation_record),
        "backend_queue_lock": dict(lock_record),
        "backend_queue_validation": dict(validation_record),
        "split_role_audit": dict(split_record),
    }


def build_registration_intent(
    *,
    queue_lock: Mapping[str, object],
    intended: Sequence[Mapping[str, str]],
    registry_prefix: Mapping[str, object],
    allocated_at: str,
    artifact_records: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    records = artifact_records
    if set(records) != {
        "backend_queue",
        "backend_allocation",
        "backend_queue_lock",
        "backend_queue_validation",
        "split_role_audit",
    }:
        raise ValueError("registration intent artifact record set mismatch")
    payload: dict[str, object] = {
        "schema_version": INTENT_SCHEMA,
        "status": INTENT_STATUS,
        "created_at": allocated_at,
        "backend_queue_lock_hash": queue_lock["backend_queue_lock_hash"],
        "backend_queue": dict(records["backend_queue"]),
        "backend_allocation": dict(records["backend_allocation"]),
        "backend_queue_lock": dict(records["backend_queue_lock"]),
        "backend_queue_validation": dict(records["backend_queue_validation"]),
        "split_role_audit": dict(records["split_role_audit"]),
        "registry_prefix": dict(registry_prefix),
        "intended_backend_runs": len(intended),
        "intended_registry_rows_sha256": builder.sha256_bytes(
            builder.canonical_json([dict(row) for row in intended]).encode("utf-8")
        ),
        "first_registry_event_id": intended[0]["registry_event_id"],
        "last_registry_event_id": intended[-1]["registry_event_id"],
        "append_policy": "IDEMPOTENT_EXACT_ROWS_UNDER_CANONICAL_REGISTRY_FLOCK",
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
    }
    payload["registration_intent_hash"] = _document_hash(
        payload, "registration_intent_hash"
    )
    return payload


def validate_registration_intent(
    payload: Mapping[str, object],
    *,
    intended: Sequence[Mapping[str, str]],
    queue_lock: Mapping[str, object],
    root: Path = builder.ROOT,
    verify_artifacts: bool = False,
    expected_artifact_records: Mapping[str, Mapping[str, object]] | None = None,
) -> None:
    expected_keys = {
        "schema_version",
        "status",
        "created_at",
        "backend_queue_lock_hash",
        "backend_queue",
        "backend_allocation",
        "backend_queue_lock",
        "backend_queue_validation",
        "split_role_audit",
        "registry_prefix",
        "intended_backend_runs",
        "intended_registry_rows_sha256",
        "first_registry_event_id",
        "last_registry_event_id",
        "append_policy",
        "held_out_trajectory_outcome_read",
        "outcome_boundary",
        "registration_intent_hash",
    }
    artifact_paths = {
        "backend_queue": builder.display_path(builder.BACKEND_QUEUE),
        "backend_allocation": builder.display_path(builder.BACKEND_ALLOCATION),
        "backend_queue_lock": builder.display_path(builder.BACKEND_QUEUE_LOCK),
        "backend_queue_validation": builder.display_path(
            builder.BACKEND_QUEUE_VALIDATION
        ),
        "split_role_audit": builder.display_path(
            builder.P07 / "split_role_audit_v1.csv"
        ),
    }
    if not verify_artifacts and expected_artifact_records is None:
        raise ValueError(
            "backend registration intent validation requires artifact authority"
        )
    if expected_artifact_records is not None and set(expected_artifact_records) != set(
        artifact_paths
    ):
        raise ValueError("backend registration expected artifact record set mismatch")
    if (
        set(payload) != expected_keys
        or payload.get("schema_version") != INTENT_SCHEMA
        or payload.get("status") != INTENT_STATUS
        or payload.get("registration_intent_hash")
        != _document_hash(payload, "registration_intent_hash")
        or payload.get("backend_queue_lock_hash")
        != queue_lock.get("backend_queue_lock_hash")
        or int(payload.get("intended_backend_runs", -1)) != len(intended)
        or payload.get("intended_registry_rows_sha256")
        != builder.sha256_bytes(
            builder.canonical_json([dict(row) for row in intended]).encode("utf-8")
        )
        or payload.get("first_registry_event_id")
        != intended[0]["registry_event_id"]
        or payload.get("last_registry_event_id") != intended[-1]["registry_event_id"]
        or payload.get("append_policy")
        != "IDEMPOTENT_EXACT_ROWS_UNDER_CANONICAL_REGISTRY_FLOCK"
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != builder.OUTCOME_BOUNDARY
    ):
        raise ValueError("backend registration intent semantic/hash mismatch")
    prefixes = [
        item
        for item in queue_lock.get("mutable_stream_prefix_snapshots", [])
        if isinstance(item, dict)
        and item.get("path") == builder.display_path(RUN_REGISTRY)
    ]
    if len(prefixes) != 1 or payload.get("registry_prefix") != prefixes[0]:
        raise ValueError("backend registration intent registry prefix mismatch")
    for name, relative in artifact_paths.items():
        record = payload.get(name)
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256", "size_bytes"}
            or record.get("path") != relative
            or not isinstance(record.get("sha256"), str)
            or len(str(record["sha256"])) != 64
            or any(character not in "0123456789abcdef" for character in str(record["sha256"]))
            or not isinstance(record.get("size_bytes"), int)
            or int(record["size_bytes"]) <= 0
        ):
            raise ValueError(f"backend registration intent {name} record mismatch")
        if expected_artifact_records is not None and record != dict(
            expected_artifact_records[name]
        ):
            raise ValueError(f"backend registration intent {name} authority mismatch")
        if verify_artifacts:
            observed = builder.rooted_io.direct_file_record_bound_input_rooted(
                root, root / relative, label=f"backend registration {name}"
            )
            if any(
                observed.get(field) != record.get(field)
                for field in ("path", "sha256", "size_bytes")
            ):
                raise ValueError(f"backend registration intent {name} drift")


def apply_registration() -> dict[str, object]:
    (
        queue_rows,
        allocation_rows,
        fields,
        split_roles,
        queue_lock,
        artifact_records,
    ) = _live_inputs()
    intended = build_registry_rows(
        queue_rows,
        allocation_rows,
        registry_fields=fields,
        split_roles=split_roles,
    )
    registry_prefixes = [
        item
        for item in queue_lock.get("mutable_stream_prefix_snapshots", [])
        if item.get("path") == builder.display_path(RUN_REGISTRY)
    ]
    if len(registry_prefixes) != 1:
        raise ValueError("backend queue lock lacks one canonical registry prefix")
    expected_intent = build_registration_intent(
        queue_lock=queue_lock,
        intended=intended,
        registry_prefix=registry_prefixes[0],
        allocated_at=allocation_rows[0]["allocated_at"],
        artifact_records=artifact_records,
    )
    intent_bytes = builder.json_bytes(expected_intent)
    intent_relative = builder.display_path(INTENT)
    report_relative = builder.display_path(REPORT)
    with builder.formal_io.global_formal_lock():
        if builder.formal_io.destination_exists(builder.ROOT, report_relative):
            raise FileExistsError(REPORT)
        if builder.formal_io.destination_exists(builder.ROOT, intent_relative):
            observed_intent_bytes, _identity = builder.formal_io.read_direct_bytes(
                builder.ROOT, intent_relative
            )
            if observed_intent_bytes != intent_bytes:
                raise ValueError("existing backend registration intent differs")
            observed_intent = json.loads(observed_intent_bytes)
            validate_registration_intent(
                observed_intent,
                intended=intended,
                queue_lock=queue_lock,
                verify_artifacts=True,
            )
        else:
            builder.formal_io.publish_bytes_no_clobber(
                builder.ROOT, intent_relative, intent_bytes
            )
        before_content = _read_absolute_direct_bytes(
            RUN_REGISTRY, label="canonical registry before append"
        )
        added = append_missing(
            RUN_REGISTRY, intended, expected_prefix=registry_prefixes[0]
        )
        after_content = _read_absolute_direct_bytes(
            RUN_REGISTRY, label="canonical registry after append"
        )
        _fields, observed = _parse_csv_content(RUN_REGISTRY, after_content)
        validation = validate_registered(intended, observed)
        if validation["pass"] is not True:
            raise ValueError(f"backend registry postcondition failed: {validation}")
        payload: dict[str, object] = {
            "schema_version": SCHEMA,
            "status": "PASS",
            "recorded_at": allocation_rows[0]["allocated_at"],
            "backend_queue_lock_hash": queue_lock["backend_queue_lock_hash"],
            "registration_intent": {
                "path": intent_relative,
                "sha256": builder.sha256_bytes(intent_bytes),
                "size_bytes": len(intent_bytes),
                "registration_intent_hash": expected_intent[
                    "registration_intent_hash"
                ],
            },
            "registry_rows_appended_this_invocation": added,
            "registry_rows_reconciled_existing": len(intended) - added,
            "validation": validation,
            "before_registry_sha256": builder.sha256_bytes(before_content),
            "after_registry_sha256": builder.sha256_bytes(after_content),
            "allocation_sha256": artifact_records["backend_allocation"]["sha256"],
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": builder.OUTCOME_BOUNDARY,
        }
        payload["registration_report_hash"] = _document_hash(
            payload, "registration_report_hash"
        )
        builder.formal_io.publish_bytes_no_clobber(
            builder.ROOT, report_relative, builder.json_bytes(payload)
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    (
        queue_rows,
        allocation_rows,
        fields,
        split_roles,
        _queue_lock,
        _artifact_records,
    ) = _live_inputs()
    intended = build_registry_rows(
        queue_rows,
        allocation_rows,
        registry_fields=fields,
        split_roles=split_roles,
    )
    if not args.apply:
        _fields, observed = read_csv_with_fields(RUN_REGISTRY)
        print(json.dumps(validate_registered(intended, observed), indent=2, sort_keys=True))
        return 0
    payload = apply_registration()
    print(
        "P07_BACKEND_REGISTRATION_PASS "
        f"appended={payload['registry_rows_appended_this_invocation']} "
        f"total={payload['validation']['intended_backend_runs']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
