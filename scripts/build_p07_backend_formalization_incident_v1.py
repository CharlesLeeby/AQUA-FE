#!/usr/bin/env python3
"""Record, without adopting, an unauthorized P07 backend formalization.

The default command is a read-only preview.  A future, separately authorized
``--write`` publishes only this incident record with no-clobber semantics; the
record never authorizes scientific adoption, backend execution, VINS, or G0.

This module deliberately reads only governance/formalization artifacts and the
canonical run registry.  It does not discover or read trajectory, APE, RPE, or
backend run-result artifacts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import secrets
import stat
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import p07_backend_formal_io_v1 as formal_io  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
P07 = ROOT / "papers/ieee_sensors_journal_experiments/p07"
OUTPUT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_incident_v1.json"
)
OUTPUT = ROOT / OUTPUT_RELATIVE

SCHEMA = "isj-p07-backend-formalization-incident-v1"
STATUS = "RECORDED_NON_AUTHORIZING_PREOUTCOME_INCIDENT"
SELF_HASH_FIELD = "incident_hash"

REGISTRY_RELATIVE = "papers/ieee_sensors_journal_experiments/run_registry.csv"
QUEUE_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv"
)
ALLOCATION_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_run_allocation_v1.csv"
)
QUEUE_LOCK_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json"
)
QUEUE_VALIDATION_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_queue_validation_v1.json"
)
REGISTRATION_INTENT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_registration_intent_v1.json"
)
REGISTRATION_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_registration_v1.json"
)

PRESENT_PATHS = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_a02_0005_legacy_d_sidecar_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_a01_0018_legacy_d_sidecar_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_legacy_d_resolution_compatibility_lock_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "evaluator_epoch_ns_correction_lock_v1.json",
    QUEUE_RELATIVE,
    ALLOCATION_RELATIVE,
    QUEUE_LOCK_RELATIVE,
    QUEUE_VALIDATION_RELATIVE,
    REGISTRATION_INTENT_RELATIVE,
    REGISTRATION_RELATIVE,
)

DOWNSTREAM_ABSENT_PATHS = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_replacement_contract_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_intent_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_play_inputs_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_receipt_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_lock_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_replay_execution_lock_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "g0_reference_contracts_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/g0_evaluation_lock_v1.json",
)

POST_INCIDENT_GOVERNANCE_ABSENT_PATHS = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_external_review_manifest_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_g0_global_stable_review_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_g0_independent_adoption_go_v1.json",
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_adoption_v1.json",
)
GLOBAL_POST_INCIDENT_OUTPUT_PATHS = (
    *POST_INCIDENT_GOVERNANCE_ABSENT_PATHS,
    *DOWNSTREAM_ABSENT_PATHS,
)

EXECUTION_OUTPUT_ROOT_PATHS = (
    "papers/ieee_sensors_journal_experiments/p07/backend_attempts",
    "papers/ieee_sensors_journal_experiments/p07/backend_attempt_intents",
    "papers/ieee_sensors_journal_experiments/p07/g0_jobs",
    "papers/ieee_sensors_journal_experiments/p07/g0_results",
)
REPLACEMENT_CONTRACT_RELATIVE = DOWNSTREAM_ABSENT_PATHS[0]
REPLACEMENT_ALLOCATION_INDEX_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_replacement_allocation_v1.csv"
)
REPLACEMENT_LOCK_ROOT_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/backend_replacements"
)
REPLACEMENT_OUTPUT_PATHS = (
    REPLACEMENT_CONTRACT_RELATIVE,
    REPLACEMENT_ALLOCATION_INDEX_RELATIVE,
    REPLACEMENT_LOCK_ROOT_RELATIVE,
    EXECUTION_OUTPUT_ROOT_PATHS[0],
    EXECUTION_OUTPUT_ROOT_PATHS[1],
)
GLOBAL_PREOUTCOME_ABSENT_PATHS = tuple(
    dict.fromkeys(
        (
            *GLOBAL_POST_INCIDENT_OUTPUT_PATHS,
            *EXECUTION_OUTPUT_ROOT_PATHS,
            *REPLACEMENT_OUTPUT_PATHS,
        )
    )
)

QUEUE_SCHEMA = "isj-p07-backend-replay-queue-v1"
ALLOCATION_SCHEMA = "isj-p07-backend-run-allocation-v1"
OUTCOME_BOUNDARY = "BACKEND_QUEUE_FROZEN_BEFORE_P07_TRAJECTORY_OUTCOME"
EXPECTED_BACKEND_ROWS = 240

# (kind, exact schema, exact status, optional self-hash field)
_PRESENT_SPECS = {
    PRESENT_PATHS[0]: (
        "json",
        "isj-p07-backend-legacy-d-resolution-sidecar-v1",
        "PASS_NOT_APPLICABLE_LEGACY_LOCK_BOUND",
        "sidecar_hash",
    ),
    PRESENT_PATHS[1]: (
        "json",
        "isj-p07-backend-legacy-d-resolution-sidecar-v1",
        "PASS_NOT_APPLICABLE_LEGACY_LOCK_BOUND",
        "sidecar_hash",
    ),
    PRESENT_PATHS[2]: (
        "json",
        "isj-p07-backend-legacy-d-resolution-compatibility-lock-v1",
        "FROZEN_READY_FOR_BACKEND_QUEUE_INPUT",
        "compatibility_lock_hash",
    ),
    PRESENT_PATHS[3]: (
        "json",
        "isj-p07-evaluator-epoch-ns-correction-lock-v1",
        "FROZEN_OUTCOME_BLIND_ADDITIVE_ROS_BAG_EPOCH_NS_CORRECTION",
        "epoch_ns_correction_lock_hash",
    ),
    PRESENT_PATHS[4]: ("csv", QUEUE_SCHEMA, "PLANNED", None),
    PRESENT_PATHS[5]: ("csv", ALLOCATION_SCHEMA, "PLANNED", None),
    PRESENT_PATHS[6]: (
        "json",
        "isj-p07-backend-queue-lock-v1",
        "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK",
        "backend_queue_lock_hash",
    ),
    PRESENT_PATHS[7]: (
        "json",
        "isj-p07-backend-queue-validation-v1",
        "PASS",
        None,
    ),
    PRESENT_PATHS[8]: (
        "json",
        "isj-p07-backend-registration-intent-v1",
        "FROZEN_BEFORE_CANONICAL_REGISTRY_APPEND",
        "registration_intent_hash",
    ),
    PRESENT_PATHS[9]: (
        "json",
        "isj-p07-backend-registration-v1",
        "PASS",
        "registration_report_hash",
    ),
}

_STAT_RECORD_KEYS = {
    "path",
    "device",
    "inode",
    "mode",
    "uid",
    "gid",
    "nlink",
    "size_bytes",
    "mtime_ns",
    "ctime_ns",
    "sha256",
}
_ARTIFACT_RECORD_KEYS = _STAT_RECORD_KEYS | {
    "schema_version",
    "status",
    "self_hash_field",
    "self_hash",
}


class IncidentError(RuntimeError):
    """The observed state is not the exact pre-outcome incident shape."""


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def document_hash(payload: Mapping[str, object]) -> str:
    clone = dict(payload)
    clone.pop(SELF_HASH_FIELD, None)
    return hashlib.sha256(_canonical_json(clone).encode("utf-8")).hexdigest()


def _hash_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _require_hash(value: object, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise IncidentError("{} is not a SHA-256 value".format(label))
    return value


def _observed_at(value: Optional[str]) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise IncidentError("observed_at is not ISO-8601") from error
    if parsed.tzinfo is None:
        raise IncidentError("observed_at must include a timezone")
    return value


def _timestamp_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    utc = parsed.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc - epoch
    return (
        delta.days * 86_400 * 1_000_000_000
        + delta.seconds * 1_000_000_000
        + delta.microseconds * 1_000
    )


def _safe_relative(relative: str) -> str:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\x00" in relative
        or pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise IncidentError("unsafe workspace-relative path: {!r}".format(relative))
    return pure.as_posix()


def _leaf_exists(root: Path, relative: str) -> bool:
    path = root.absolute() / _safe_relative(relative)
    try:
        os.lstat(str(path))
    except FileNotFoundError:
        return False
    except OSError as error:
        raise IncidentError("cannot inspect path state: {}".format(relative)) from error
    return True


def _direct_leaf_exists(root: Path, relative: str) -> bool:
    """Inspect one exact leaf through a direct, no-follow parent chain."""

    relative = _safe_relative(relative)
    try:
        return formal_io.destination_exists(root.absolute(), relative)
    except formal_io.FormalIOError as error:
        raise IncidentError(
            "cannot directly inspect no-follow path state: {}".format(relative)
        ) from error


def _exact_absence_records(
    root: Path,
    relatives: Sequence[str],
    *,
    label: str,
    state_key: str,
) -> list[dict[str, str]]:
    records = []
    for relative in relatives:
        if _direct_leaf_exists(root, relative):
            raise IncidentError("{} path is present: {}".format(label, relative))
        records.append({"path": relative, state_key: "ABSENT"})
    return records


def _direct_snapshot(root: Path, relative: str) -> Tuple[bytes, dict[str, object]]:
    relative = _safe_relative(relative)
    try:
        first, first_identity = formal_io.read_direct_bytes(root, relative)
        info = os.stat(str(root.absolute() / relative), follow_symlinks=False)
        second, second_identity = formal_io.read_direct_bytes(root, relative)
    except (OSError, formal_io.FormalIOError) as error:
        raise IncidentError("cannot snapshot direct file: {}".format(relative)) from error
    if (
        first != second
        or first_identity != second_identity
        or first_identity.get("device") != info.st_dev
        or first_identity.get("inode") != info.st_ino
        or first_identity.get("size_bytes") != info.st_size
        or not stat.S_ISREG(info.st_mode)
        or info.st_nlink != 1
        or len(first) != info.st_size
    ):
        raise IncidentError("file identity drift while snapshotting: {}".format(relative))
    return first, {
        "path": relative,
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "nlink": int(info.st_nlink),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
        "sha256": _hash_bytes(first),
    }


def _reject_duplicate_json_pairs(pairs: Sequence[Tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IncidentError("duplicate JSON key: {}".format(key))
        result[key] = value
    return result


def _parse_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=_reject_duplicate_json_pairs
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IncidentError("invalid JSON: {}".format(label)) from error
    if not isinstance(value, dict):
        raise IncidentError("JSON document is not an object: {}".format(label))
    return value


def _parse_csv(content: bytes, label: str) -> Tuple[list[str], list[dict[str, str]]]:
    if not content or not content.endswith(b"\n"):
        raise IncidentError("CSV is empty or lacks final newline: {}".format(label))
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise IncidentError("CSV is not UTF-8: {}".format(label)) from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if (
        not fields
        or len(fields) != len(set(fields))
        or any(field in {None, ""} for field in fields)
        or any(None in row for row in rows)
    ):
        raise IncidentError("invalid or ragged CSV: {}".format(label))
    return fields, rows


def _rows_bytes(fields: Sequence[str], rows: Sequence[Mapping[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(fields), lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return _hash_bytes(_canonical_json(clone).encode("utf-8"))


def _semantic_identity(
    relative: str, content: bytes
) -> Tuple[dict[str, object], object]:
    kind, expected_schema, expected_status, self_hash_field = _PRESENT_SPECS[relative]
    if kind == "json":
        parsed = _parse_json(content, relative)
        if (
            parsed.get("schema_version") != expected_schema
            or parsed.get("status") != expected_status
        ):
            raise IncidentError("JSON schema/status mismatch: {}".format(relative))
        self_hash: Optional[str] = None
        if self_hash_field is not None:
            self_hash = _require_hash(
                parsed.get(self_hash_field), "{} embedded self-hash".format(relative)
            )
            if self_hash != _self_hash(parsed, self_hash_field):
                raise IncidentError("embedded self-hash mismatch: {}".format(relative))
        if (
            "held_out_trajectory_outcome_read" in parsed
            and parsed.get("held_out_trajectory_outcome_read") is not False
        ):
            raise IncidentError("outcome-read flag is not false: {}".format(relative))
        if relative == PRESENT_PATHS[3]:
            audit = parsed.get("outcome_blind_audit")
            false_fields = {
                "ape_artifact_read",
                "backend_queue_generated",
                "evaluation_plan_generated",
                "evaluator_executed",
                "real_trajectory_artifact_read",
                "result_artifact_read",
                "rpe_artifact_read",
                "vins_executed",
                "workspace_discovery_used",
            }
            if not isinstance(audit, dict) or any(audit.get(key) is not False for key in false_fields):
                raise IncidentError("epoch correction is not outcome-blind")
        return {
            "schema_version": expected_schema,
            "status": expected_status,
            "self_hash_field": self_hash_field,
            "self_hash": self_hash,
        }, parsed

    fields, rows = _parse_csv(content, relative)
    if not rows:
        raise IncidentError("incident CSV has no rows: {}".format(relative))
    schemas = {row.get("schema_version") for row in rows}
    statuses = {row.get("status") for row in rows}
    if schemas != {expected_schema} or statuses != {expected_status}:
        raise IncidentError("CSV schema/status mismatch: {}".format(relative))
    return {
        "schema_version": expected_schema,
        "status": expected_status,
        "self_hash_field": None,
        "self_hash": None,
    }, (fields, rows)


def _simple_file_record(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        "path": snapshot["path"],
        "sha256": snapshot["sha256"],
        "size_bytes": snapshot["size_bytes"],
    }


def _require_bound_record(
    value: object, expected: Mapping[str, object], label: str
) -> None:
    if not isinstance(value, dict) or set(value) != {"path", "sha256", "size_bytes"}:
        raise IncidentError("{} is not an exact file record".format(label))
    if value != _simple_file_record(expected):
        raise IncidentError("{} file record drift".format(label))


def _queue_and_allocation_state(
    parsed: Mapping[str, object], root: Path
) -> Tuple[list[dict[str, str]], list[dict[str, str]], dict[str, object]]:
    queue_value = parsed[QUEUE_RELATIVE]
    allocation_value = parsed[ALLOCATION_RELATIVE]
    if not (
        isinstance(queue_value, tuple)
        and len(queue_value) == 2
        and isinstance(allocation_value, tuple)
        and len(allocation_value) == 2
    ):
        raise IncidentError("queue/allocation parse state is invalid")
    queue_fields, queue_rows = queue_value
    allocation_fields, allocation_rows = allocation_value
    required_queue = {
        "schema_version",
        "queue_index",
        "run_id",
        "expected_run_dir",
        "expected_attempt_dir",
        "status",
        "outcome_boundary",
    }
    required_allocation = {
        "schema_version",
        "queue_index",
        "run_id",
        "status",
    }
    if not required_queue.issubset(queue_fields) or not required_allocation.issubset(
        allocation_fields
    ):
        raise IncidentError("queue/allocation required columns are missing")
    if len(queue_rows) != EXPECTED_BACKEND_ROWS or len(allocation_rows) != EXPECTED_BACKEND_ROWS:
        raise IncidentError("incident does not contain exactly 240 backend rows")
    expected_indices = [str(index) for index in range(1, EXPECTED_BACKEND_ROWS + 1)]
    if [row["queue_index"] for row in queue_rows] != expected_indices or [
        row["queue_index"] for row in allocation_rows
    ] != expected_indices:
        raise IncidentError("backend queue/allocation indices are not exact 1..240")
    queue_run_ids = [row["run_id"] for row in queue_rows]
    allocation_run_ids = [row["run_id"] for row in allocation_rows]
    if (
        queue_run_ids != allocation_run_ids
        or len(set(queue_run_ids)) != EXPECTED_BACKEND_ROWS
        or any(not run_id for run_id in queue_run_ids)
    ):
        raise IncidentError("backend queue/allocation run IDs drift")
    if any(row["outcome_boundary"] != OUTCOME_BOUNDARY for row in queue_rows):
        raise IncidentError("backend queue outcome boundary drift")

    run_dirs = [row["expected_run_dir"] for row in queue_rows]
    attempt_dirs = [row["expected_attempt_dir"] for row in queue_rows]
    if (
        len(set(run_dirs)) != EXPECTED_BACKEND_ROWS
        or len(set(attempt_dirs)) != EXPECTED_BACKEND_ROWS
    ):
        raise IncidentError("expected backend run/attempt paths are not unique")
    for relative in run_dirs:
        _safe_relative(relative)
        if not relative.startswith("logs/"):
            raise IncidentError("expected backend run path is outside logs: {}".format(relative))
    attempt_prefix = (
        "papers/ieee_sensors_journal_experiments/p07/backend_attempts/"
    )
    for relative in attempt_dirs:
        _safe_relative(relative)
        if not relative.startswith(attempt_prefix):
            raise IncidentError(
                "expected backend attempt path is outside its root: {}".format(relative)
            )

    present_run_dirs = [relative for relative in run_dirs if _leaf_exists(root, relative)]
    present_attempt_dirs = [
        relative for relative in attempt_dirs if _leaf_exists(root, relative)
    ]
    if present_run_dirs or present_attempt_dirs:
        raise IncidentError(
            "expected backend execution directories already exist: run={} attempt={}".format(
                len(present_run_dirs), len(present_attempt_dirs)
            )
        )
    state = {
        "queue_rows": EXPECTED_BACKEND_ROWS,
        "unique_expected_run_dirs": EXPECTED_BACKEND_ROWS,
        "expected_run_dirs_sha256": _hash_bytes(
            _canonical_json(run_dirs).encode("utf-8")
        ),
        "present_expected_run_dirs": [],
        "present_expected_run_dir_count": 0,
        "unique_expected_attempt_dirs": EXPECTED_BACKEND_ROWS,
        "expected_attempt_dirs_sha256": _hash_bytes(
            _canonical_json(attempt_dirs).encode("utf-8")
        ),
        "present_expected_attempt_dirs": [],
        "present_expected_attempt_dir_count": 0,
    }
    return queue_rows, allocation_rows, state


def _registry_state(
    root: Path,
    contents: Mapping[str, bytes],
    snapshots: Mapping[str, Mapping[str, object]],
    parsed: Mapping[str, object],
    queue_rows: Sequence[Mapping[str, str]],
    allocation_rows: Sequence[Mapping[str, str]],
) -> Tuple[dict[str, object], dict[str, object]]:
    registry_content, registry_snapshot = _direct_snapshot(root, REGISTRY_RELATIVE)
    queue_lock = parsed[QUEUE_LOCK_RELATIVE]
    intent = parsed[REGISTRATION_INTENT_RELATIVE]
    report = parsed[REGISTRATION_RELATIVE]
    validation = parsed[QUEUE_VALIDATION_RELATIVE]
    if not all(isinstance(value, dict) for value in (queue_lock, intent, report, validation)):
        raise IncidentError("backend JSON governance parse state is invalid")

    queue_lock_hash = _require_hash(
        queue_lock.get("backend_queue_lock_hash"), "backend queue lock self-hash"
    )
    if (
        queue_lock.get("backend_replay_jobs") != EXPECTED_BACKEND_ROWS
        or validation.get("backend_replay_jobs") != EXPECTED_BACKEND_ROWS
        or intent.get("intended_backend_runs") != EXPECTED_BACKEND_ROWS
        or intent.get("backend_queue_lock_hash") != queue_lock_hash
        or validation.get("backend_queue_lock_hash") != queue_lock_hash
        or report.get("backend_queue_lock_hash") != queue_lock_hash
    ):
        raise IncidentError("backend 240-row queue-lock chain mismatch")
    if any(
        row.get("backend_queue_lock_hash") not in {None, "", queue_lock_hash}
        for row in allocation_rows
    ):
        raise IncidentError("allocation queue-lock binding mismatch")

    _require_bound_record(
        queue_lock.get("backend_replay_queue"), snapshots[QUEUE_RELATIVE], "queue lock queue"
    )
    intent_records = {
        "backend_queue": QUEUE_RELATIVE,
        "backend_allocation": ALLOCATION_RELATIVE,
        "backend_queue_lock": QUEUE_LOCK_RELATIVE,
        "backend_queue_validation": QUEUE_VALIDATION_RELATIVE,
    }
    for key, relative in intent_records.items():
        _require_bound_record(intent.get(key), snapshots[relative], "intent {}".format(key))

    prefix = queue_lock.get("mutable_registry_prefix")
    if not isinstance(prefix, dict) or set(prefix) != {"path", "sha256", "size_bytes"}:
        raise IncidentError("queue lock lacks exact registry prefix record")
    if intent.get("registry_prefix") != prefix or prefix.get("path") != REGISTRY_RELATIVE:
        raise IncidentError("queue lock/intent registry prefix mismatch")
    prefix_size = prefix.get("size_bytes")
    prefix_hash = _require_hash(prefix.get("sha256"), "registry prefix hash")
    if not isinstance(prefix_size, int) or prefix_size <= 0 or prefix_size >= len(registry_content):
        raise IncidentError("registry prefix size is invalid for appended incident")
    prefix_content = registry_content[:prefix_size]
    suffix_content = registry_content[prefix_size:]
    if not prefix_content.endswith(b"\n") or _hash_bytes(prefix_content) != prefix_hash:
        raise IncidentError("canonical registry original prefix drift")

    prefix_fields, prefix_rows = _parse_csv(prefix_content, "registry original prefix")
    full_fields, full_rows = _parse_csv(registry_content, "registry full file")
    if prefix_fields != full_fields or full_rows[: len(prefix_rows)] != prefix_rows:
        raise IncidentError("registry full file does not retain the exact original prefix")
    suffix_rows = full_rows[len(prefix_rows) :]
    if (
        len(suffix_rows) != EXPECTED_BACKEND_ROWS
        or _rows_bytes(full_fields, suffix_rows) != suffix_content
    ):
        raise IncidentError("registry is not prefix plus exactly 240 complete rows")

    queue_run_ids = [row["run_id"] for row in queue_rows]
    suffix_run_ids = [row.get("run_id", "") for row in suffix_rows]
    if suffix_run_ids != queue_run_ids or set(queue_run_ids).intersection(
        row.get("run_id", "") for row in prefix_rows
    ):
        raise IncidentError("registry suffix is not the exact new backend run set")
    for index, (registry_row, queue_row, allocation_row) in enumerate(
        zip(suffix_rows, queue_rows, allocation_rows), start=1
    ):
        run_id = queue_row["run_id"]
        if (
            registry_row.get("registry_event_id") != "{}_e00".format(run_id)
            or registry_row.get("status") != "PLANNED"
            or registry_row.get("run_dir") != queue_row["expected_run_dir"]
            or allocation_row["run_id"] != run_id
            or allocation_row["queue_index"] != str(index)
        ):
            raise IncidentError("registry PLANNED/e00 suffix drift at row {}".format(index))
        if "backend_replay" in allocation_row and registry_row.get(
            "backend_replay"
        ) != allocation_row.get("backend_replay"):
            raise IncidentError("registry backend replay slot drift at row {}".format(index))

    intended_rows_hash = _hash_bytes(
        _canonical_json([dict(row) for row in suffix_rows]).encode("utf-8")
    )
    if intent.get("intended_registry_rows_sha256") != intended_rows_hash:
        raise IncidentError("registration intent does not bind the exact registry suffix")
    if (
        report.get("before_registry_sha256") != prefix_hash
        or report.get("after_registry_sha256") != registry_snapshot["sha256"]
        or report.get("allocation_sha256") != snapshots[ALLOCATION_RELATIVE]["sha256"]
        or report.get("registry_rows_appended_this_invocation") != EXPECTED_BACKEND_ROWS
        or report.get("registry_rows_reconciled_existing") != 0
        or report.get("validation")
        != {
            "intended_backend_runs": EXPECTED_BACKEND_ROWS,
            "unique_untouched_planned_e00": EXPECTED_BACKEND_ROWS,
            "pass": True,
        }
    ):
        raise IncidentError("backend registration report/full registry mismatch")
    registration_intent_record = report.get("registration_intent")
    if not isinstance(registration_intent_record, dict):
        raise IncidentError("registration report lacks intent record")
    expected_intent_record = _simple_file_record(snapshots[REGISTRATION_INTENT_RELATIVE])
    if any(
        registration_intent_record.get(key) != value
        for key, value in expected_intent_record.items()
    ) or registration_intent_record.get("registration_intent_hash") != intent.get(
        "registration_intent_hash"
    ):
        raise IncidentError("registration report intent binding mismatch")

    return {
        "full_file": registry_snapshot,
        "full_row_count": len(full_rows),
        "original_prefix": {
            "path": REGISTRY_RELATIVE,
            "size_bytes": prefix_size,
            "sha256": prefix_hash,
            "row_count": len(prefix_rows),
            "field_order_sha256": _hash_bytes(
                _canonical_json(prefix_fields).encode("utf-8")
            ),
        },
        "exact_planned_e00_suffix": {
            "offset_bytes": prefix_size,
            "size_bytes": len(suffix_content),
            "sha256": _hash_bytes(suffix_content),
            "row_count": EXPECTED_BACKEND_ROWS,
            "canonical_rows_sha256": intended_rows_hash,
            "first_registry_event_id": suffix_rows[0]["registry_event_id"],
            "last_registry_event_id": suffix_rows[-1]["registry_event_id"],
            "all_status_planned": True,
            "all_event_ids_e00": True,
        },
        "composition": "FULL_BYTES_EQUAL_ORIGINAL_PREFIX_CONCAT_EXACT_240_ROW_SUFFIX",
    }, registry_snapshot


def _timeline(
    artifacts: Sequence[Mapping[str, object]], registry: Mapping[str, object]
) -> dict[str, object]:
    entries = []
    for artifact in artifacts:
        entries.append(
            {
                "path": artifact["path"],
                "event_kind": "PRESENT_FORMALIZATION_FILE_TIMESTAMP",
                "mtime_ns": artifact["mtime_ns"],
                "ctime_ns": artifact["ctime_ns"],
            }
        )
    entries.append(
        {
            "path": registry["path"],
            "event_kind": "CANONICAL_REGISTRY_APPEND_STATE_TIMESTAMP",
            "mtime_ns": registry["mtime_ns"],
            "ctime_ns": registry["ctime_ns"],
        }
    )
    entries.sort(key=lambda row: (int(row["ctime_ns"]), str(row["path"])))
    sequenced = [dict({"sequence": index}, **row) for index, row in enumerate(entries, 1)]
    return {
        "basis": "FILESYSTEM_MTIME_CTIME_OBSERVATIONS_NOT_CREATOR_ATTRIBUTION",
        "creator_inference_performed": False,
        "earliest_ctime_ns": min(int(row["ctime_ns"]) for row in entries),
        "latest_ctime_ns": max(int(row["ctime_ns"]) for row in entries),
        "events": sequenced,
    }


def build_incident(
    root: Path = ROOT,
    observed_at: Optional[str] = None,
    require_output_absent: bool = True,
) -> dict[str, object]:
    """Build the exact incident record without publishing or authorizing it."""

    root = root.absolute()
    observed_at = _observed_at(observed_at)
    if require_output_absent and _direct_leaf_exists(root, OUTPUT_RELATIVE):
        raise FileExistsError(OUTPUT_RELATIVE)

    # Fail before reading incident sources when any future execution, G0, or
    # replacement output root/leaf already exists.  Checking the roots (not
    # only the 240 expected paths) also detects orphan attempts and broken
    # symlink placeholders.
    global_output_absence = _exact_absence_records(
        root,
        GLOBAL_POST_INCIDENT_OUTPUT_PATHS,
        label="post-incident output",
        state_key="state",
    )
    execution_output_root_absence = _exact_absence_records(
        root,
        EXECUTION_OUTPUT_ROOT_PATHS,
        label="pre-outcome execution output root",
        state_key="path_state",
    )
    replacement_output_absence = _exact_absence_records(
        root,
        REPLACEMENT_OUTPUT_PATHS,
        label="pre-outcome replacement output",
        state_key="path_state",
    )

    contents: dict[str, bytes] = {}
    snapshots: dict[str, dict[str, object]] = {}
    parsed: dict[str, object] = {}
    artifacts: list[dict[str, object]] = []
    for relative in PRESENT_PATHS:
        content, snapshot = _direct_snapshot(root, relative)
        semantic, value = _semantic_identity(relative, content)
        contents[relative] = content
        snapshots[relative] = snapshot
        parsed[relative] = value
        artifacts.append(dict(snapshot, **semantic))

    queue_rows, allocation_rows, expected_paths = _queue_and_allocation_state(
        parsed, root
    )
    registry, registry_snapshot = _registry_state(
        root,
        contents,
        snapshots,
        parsed,
        queue_rows,
        allocation_rows,
    )

    # Repeat all absence observations after reading the bound incident facts;
    # publication repeats the entire build immediately before and after link.
    if global_output_absence != _exact_absence_records(
        root,
        GLOBAL_POST_INCIDENT_OUTPUT_PATHS,
        label="post-incident output",
        state_key="state",
    ):
        raise IncidentError("post-incident output absence observation drift")
    if execution_output_root_absence != _exact_absence_records(
        root,
        EXECUTION_OUTPUT_ROOT_PATHS,
        label="pre-outcome execution output root",
        state_key="path_state",
    ):
        raise IncidentError("execution output root absence observation drift")
    if replacement_output_absence != _exact_absence_records(
        root,
        REPLACEMENT_OUTPUT_PATHS,
        label="pre-outcome replacement output",
        state_key="path_state",
    ):
        raise IncidentError("replacement output absence observation drift")
    downstream = [
        {"path": relative, "state": "ABSENT"}
        for relative in DOWNSTREAM_ABSENT_PATHS
    ]
    timeline = _timeline(artifacts, registry_snapshot)
    if _timestamp_ns(observed_at) < int(timeline["latest_ctime_ns"]):
        raise IncidentError("observed_at precedes the latest incident filesystem ctime")

    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "observed_at": observed_at,
        "incident_scope": (
            "UNAUTHORIZED_BACKEND_FORMALIZATION_AND_EXACT_PLANNED_REGISTRY_APPEND"
        ),
        "creator_provenance": {
            "creator_identity": "UNKNOWN",
            "creator_command": "UNKNOWN",
            "creator_process": "UNKNOWN",
            "provenance_determination": "NOT_ESTABLISHED_BY_THIS_RECORDER",
        },
        "authorization": {
            "parent_formalization_authorization_observed": False,
            "backend_execution_authorized": False,
            "scientific_adoption_authorized": False,
            "incident_record_is_execution_authority": False,
            "incident_record_is_scientific_adoption": False,
        },
        "present_artifacts": artifacts,
        "creation_timeline": timeline,
        "canonical_run_registry": registry,
        "expected_execution_path_absence": expected_paths,
        "downstream_formal_absence": downstream,
        "global_post_incident_output_absence": global_output_absence,
        "execution_output_root_absence": execution_output_root_absence,
        "replacement_output_absence": replacement_output_absence,
        "outcome_and_execution_boundary": {
            "recorder_read_real_trajectory_artifact": False,
            "recorder_read_ape_artifact": False,
            "recorder_read_rpe_artifact": False,
            "recorder_invoked_vins": False,
            "expected_run_directory_present_count": 0,
            "expected_attempt_directory_present_count": 0,
            "backend_execution_observed_in_expected_paths": False,
            "outcome_boundary": "GOVERNANCE_ONLY_NO_TRAJECTORY_APE_RPE_OR_VINS",
        },
        "scientific_disposition": {
            "scientific_validity_assessed": False,
            "scientific_adoption_performed": False,
            "backend_formalization_adopted": False,
            "execution_transition_performed": False,
            "separate_additive_adoption_gate_required": True,
        },
        "publication_policy": {
            "default_operation": "READ_ONLY_PREVIEW",
            "write_requires_explicit_cli_flag": "--write",
            "write_semantics": "SINGLE_FILE_NO_CLOBBER",
            "output_path": OUTPUT_RELATIVE,
            "output_is_not_downstream_execution_authority": True,
        },
    }
    payload[SELF_HASH_FIELD] = document_hash(payload)
    return payload


def _validate_structural(payload: Mapping[str, object]) -> None:
    expected_keys = {
        "schema_version",
        "status",
        "observed_at",
        "incident_scope",
        "creator_provenance",
        "authorization",
        "present_artifacts",
        "creation_timeline",
        "canonical_run_registry",
        "expected_execution_path_absence",
        "downstream_formal_absence",
        "global_post_incident_output_absence",
        "execution_output_root_absence",
        "replacement_output_absence",
        "outcome_and_execution_boundary",
        "scientific_disposition",
        "publication_policy",
        SELF_HASH_FIELD,
    }
    if set(payload) != expected_keys:
        raise IncidentError("incident top-level key set mismatch")
    if payload.get("schema_version") != SCHEMA or payload.get("status") != STATUS:
        raise IncidentError("incident schema/status mismatch")
    _observed_at(payload.get("observed_at") if isinstance(payload.get("observed_at"), str) else "")
    incident_hash = _require_hash(payload.get(SELF_HASH_FIELD), "incident self-hash")
    if incident_hash != document_hash(payload):
        raise IncidentError("incident self-hash mismatch")

    if payload.get("creator_provenance") != {
        "creator_identity": "UNKNOWN",
        "creator_command": "UNKNOWN",
        "creator_process": "UNKNOWN",
        "provenance_determination": "NOT_ESTABLISHED_BY_THIS_RECORDER",
    }:
        raise IncidentError("incident creator provenance overclaims attribution")
    if payload.get("authorization") != {
        "parent_formalization_authorization_observed": False,
        "backend_execution_authorized": False,
        "scientific_adoption_authorized": False,
        "incident_record_is_execution_authority": False,
        "incident_record_is_scientific_adoption": False,
    }:
        raise IncidentError("incident authorization boundary mismatch")
    if payload.get("scientific_disposition") != {
        "scientific_validity_assessed": False,
        "scientific_adoption_performed": False,
        "backend_formalization_adopted": False,
        "execution_transition_performed": False,
        "separate_additive_adoption_gate_required": True,
    }:
        raise IncidentError("incident scientific disposition mismatch")
    if payload.get("outcome_and_execution_boundary") != {
        "recorder_read_real_trajectory_artifact": False,
        "recorder_read_ape_artifact": False,
        "recorder_read_rpe_artifact": False,
        "recorder_invoked_vins": False,
        "expected_run_directory_present_count": 0,
        "expected_attempt_directory_present_count": 0,
        "backend_execution_observed_in_expected_paths": False,
        "outcome_boundary": "GOVERNANCE_ONLY_NO_TRAJECTORY_APE_RPE_OR_VINS",
    }:
        raise IncidentError("incident outcome/execution boundary mismatch")
    if payload.get("publication_policy") != {
        "default_operation": "READ_ONLY_PREVIEW",
        "write_requires_explicit_cli_flag": "--write",
        "write_semantics": "SINGLE_FILE_NO_CLOBBER",
        "output_path": OUTPUT_RELATIVE,
        "output_is_not_downstream_execution_authority": True,
    }:
        raise IncidentError("incident publication policy mismatch")

    artifacts = payload.get("present_artifacts")
    if not isinstance(artifacts, list) or [row.get("path") for row in artifacts if isinstance(row, dict)] != list(PRESENT_PATHS):
        raise IncidentError("incident present artifact set/order mismatch")
    for relative, record in zip(PRESENT_PATHS, artifacts):
        if not isinstance(record, dict) or set(record) != _ARTIFACT_RECORD_KEYS:
            raise IncidentError("incident artifact record key set mismatch")
        kind, schema, status_value, self_field = _PRESENT_SPECS[relative]
        if (
            record.get("path") != relative
            or record.get("schema_version") != schema
            or record.get("status") != status_value
            or record.get("self_hash_field") != self_field
            or record.get("nlink") != 1
            or not isinstance(record.get("mode"), int)
            or not stat.S_ISREG(int(record["mode"]))
        ):
            raise IncidentError("incident artifact semantic/stat mismatch: {}".format(relative))
        _require_hash(record.get("sha256"), "artifact SHA-256")
        if self_field is None:
            if record.get("self_hash") is not None:
                raise IncidentError("unexpected artifact self-hash")
        else:
            _require_hash(record.get("self_hash"), "artifact embedded self-hash")

    downstream = payload.get("downstream_formal_absence")
    if downstream != [
        {"path": relative, "state": "ABSENT"}
        for relative in DOWNSTREAM_ABSENT_PATHS
    ]:
        raise IncidentError("incident downstream absence set mismatch")
    global_absence = payload.get("global_post_incident_output_absence")
    if global_absence != [
        {"path": relative, "state": "ABSENT"}
        for relative in GLOBAL_POST_INCIDENT_OUTPUT_PATHS
    ]:
        raise IncidentError("incident global post-output absence set mismatch")
    execution_root_absence = payload.get("execution_output_root_absence")
    if execution_root_absence != [
        {"path": relative, "path_state": "ABSENT"}
        for relative in EXECUTION_OUTPUT_ROOT_PATHS
    ]:
        raise IncidentError("incident execution output root absence set mismatch")
    replacement_absence = payload.get("replacement_output_absence")
    if replacement_absence != [
        {"path": relative, "path_state": "ABSENT"}
        for relative in REPLACEMENT_OUTPUT_PATHS
    ]:
        raise IncidentError("incident replacement output absence set mismatch")
    expected_paths = payload.get("expected_execution_path_absence")
    if not isinstance(expected_paths, dict) or (
        expected_paths.get("queue_rows") != EXPECTED_BACKEND_ROWS
        or expected_paths.get("present_expected_run_dirs") != []
        or expected_paths.get("present_expected_run_dir_count") != 0
        or expected_paths.get("present_expected_attempt_dirs") != []
        or expected_paths.get("present_expected_attempt_dir_count") != 0
    ):
        raise IncidentError("incident expected execution path absence mismatch")
    for key in ("expected_run_dirs_sha256", "expected_attempt_dirs_sha256"):
        _require_hash(expected_paths.get(key), key)

    registry = payload.get("canonical_run_registry")
    if not isinstance(registry, dict) or registry.get("composition") != (
        "FULL_BYTES_EQUAL_ORIGINAL_PREFIX_CONCAT_EXACT_240_ROW_SUFFIX"
    ):
        raise IncidentError("incident registry composition mismatch")
    full_file = registry.get("full_file")
    if not isinstance(full_file, dict) or set(full_file) != _STAT_RECORD_KEYS:
        raise IncidentError("incident registry full-file record mismatch")
    suffix = registry.get("exact_planned_e00_suffix")
    if not isinstance(suffix, dict) or (
        suffix.get("row_count") != EXPECTED_BACKEND_ROWS
        or suffix.get("all_status_planned") is not True
        or suffix.get("all_event_ids_e00") is not True
    ):
        raise IncidentError("incident registry suffix mismatch")
    for key in ("sha256", "canonical_rows_sha256"):
        _require_hash(suffix.get(key), "registry suffix {}".format(key))

    timeline = payload.get("creation_timeline")
    if not isinstance(timeline, dict) or timeline.get("creator_inference_performed") is not False:
        raise IncidentError("incident timeline attribution mismatch")
    expected_timeline = _timeline(artifacts, full_file)
    if timeline != expected_timeline:
        raise IncidentError("incident creation timeline mismatch")
    if _timestamp_ns(str(payload["observed_at"])) < int(
        timeline["latest_ctime_ns"]
    ):
        raise IncidentError("incident observed_at precedes latest filesystem ctime")


def validate_incident(
    payload: Mapping[str, object], root: Path = ROOT, verify_live: bool = True
) -> str:
    """Validate structure/self-hash and, by default, exact current live facts."""

    if not isinstance(payload, Mapping):
        raise IncidentError("incident payload is not a mapping")
    _validate_structural(payload)
    incident_hash = str(payload[SELF_HASH_FIELD])
    if verify_live:
        expected = build_incident(
            root=root,
            observed_at=str(payload["observed_at"]),
            require_output_absent=False,
        )
        if _canonical_json(dict(payload)) != _canonical_json(expected):
            raise IncidentError("incident payload does not equal current live facts")
        if _direct_leaf_exists(root, OUTPUT_RELATIVE):
            observed, _record = formal_io.read_direct_bytes(root, OUTPUT_RELATIVE)
            if observed != json_bytes(payload):
                raise IncidentError("published incident path differs from payload")
    return incident_hash


def _same_inode(left: os.stat_result, right: os.stat_result) -> bool:
    return left.st_dev == right.st_dev and left.st_ino == right.st_ino


def _rollback_own_destination(
    *, parent_fd: int, name: str, staged: os.stat_result
) -> None:
    try:
        observed = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not _same_inode(observed, staged):
        return
    os.unlink(name, dir_fd=parent_fd)
    formal_io._fsync_directory(parent_fd)


def publish_incident(
    payload: Mapping[str, object],
    root: Path = ROOT,
    *,
    _pre_link_test_hook: Optional[Callable[[], None]] = None,
    _post_link_test_hook: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    """Fresh-rebuild and commit under one flock, rolling back only our inode."""

    root = root.absolute()
    observed_at = str(payload.get("observed_at", ""))
    content = json_bytes(payload)
    guard_paths = [*PRESENT_PATHS, REGISTRY_RELATIVE]
    for relative in (
        "scripts/build_p07_backend_formalization_incident_v1.py",
        "scripts/tests/test_p07_backend_formalization_incident_v1.py",
    ):
        if os.path.lexists(root / relative):
            guard_paths.append(relative)

    with formal_io.global_formal_lock():
        if formal_io.destination_exists(root, OUTPUT_RELATIVE):
            raise FileExistsError(OUTPUT_RELATIVE)
        fresh = build_incident(
            root=root,
            observed_at=observed_at,
            require_output_absent=True,
        )
        if _canonical_json(fresh) != _canonical_json(dict(payload)):
            raise IncidentError("incident publication payload is not the fresh rebuild")
        expected_inputs = {
            relative: formal_io.read_direct_bytes(root, relative)[0]
            for relative in sorted(set(guard_paths))
        }
        with ExitStack() as stack:
            leases = [
                stack.enter_context(
                    formal_io._retained_exact_leaf(
                        root, relative, expected_inputs[relative]
                    )
                )
                for relative in sorted(expected_inputs)
            ]

            def validate_fresh_snapshot() -> None:
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)
                rebuilt = build_incident(
                    root=root,
                    observed_at=observed_at,
                    require_output_absent=False,
                )
                if _canonical_json(rebuilt) != _canonical_json(fresh):
                    raise IncidentError("incident fresh rebuild drift during commit")
                validate_incident(fresh, root=root, verify_live=True)
                for lease in leases:
                    formal_io._validate_retained_exact_leaf(lease)

            validate_fresh_snapshot()
            with formal_io._parent_dirfd(root, OUTPUT_RELATIVE) as (parent_fd, name):
                try:
                    os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    raise FileExistsError(OUTPUT_RELATIVE)

                temporary = (
                    ".{}.partial.{}.{}".format(
                        name, os.getpid(), secrets.token_hex(12)
                    )
                )
                staged_fd = -1
                staged: Optional[os.stat_result] = None
                linked = False
                temporary_present = False
                try:
                    flags = (
                        os.O_WRONLY
                        | os.O_CREAT
                        | os.O_EXCL
                        | os.O_CLOEXEC
                        | os.O_NOFOLLOW
                    )
                    staged_fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
                    temporary_present = True
                    formal_io._write_all(staged_fd, content)
                    os.fsync(staged_fd)
                    staged = os.fstat(staged_fd)
                    if (
                        not stat.S_ISREG(staged.st_mode)
                        or staged.st_size != len(content)
                        or staged.st_nlink != 1
                    ):
                        raise IncidentError("staged incident identity/size mismatch")
                    if _pre_link_test_hook is not None:
                        _pre_link_test_hook()
                    validate_fresh_snapshot()
                    try:
                        os.link(
                            temporary,
                            name,
                            src_dir_fd=parent_fd,
                            dst_dir_fd=parent_fd,
                            follow_symlinks=False,
                        )
                    except FileExistsError:
                        raise FileExistsError(OUTPUT_RELATIVE)
                    linked = True
                    formal_io._fsync_directory(parent_fd)
                    os.unlink(temporary, dir_fd=parent_fd)
                    temporary_present = False
                    formal_io._fsync_directory(parent_fd)
                    if _post_link_test_hook is not None:
                        _post_link_test_hook()
                    validate_fresh_snapshot()
                    reachable = os.stat(
                        name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    observed, opened = formal_io._read_direct_at(parent_fd, name)
                    if (
                        staged is None
                        or not _same_inode(reachable, staged)
                        or not _same_inode(opened, staged)
                        or reachable.st_nlink != 1
                        or opened.st_nlink != 1
                        or observed != content
                    ):
                        raise IncidentError("published incident identity/bytes drift")
                except BaseException:
                    if linked and staged is not None:
                        _rollback_own_destination(
                            parent_fd=parent_fd, name=name, staged=staged
                        )
                    raise
                finally:
                    if staged_fd >= 0:
                        os.close(staged_fd)
                    if temporary_present:
                        try:
                            os.unlink(temporary, dir_fd=parent_fd)
                        except FileNotFoundError:
                            pass
                        formal_io._fsync_directory(parent_fd)
                if staged is None or not linked:
                    raise IncidentError("incident was not linked")
                return {
                    "path": OUTPUT_RELATIVE,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "device": staged.st_dev,
                    "inode": staged.st_ino,
                    "resumed_exact_existing": False,
                }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--observed-at",
        help="ISO-8601 observation time; defaults to the current UTC time",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="future explicit no-clobber publication of this incident record only",
    )
    args = parser.parse_args(argv)
    payload = build_incident(
        root=args.root,
        observed_at=args.observed_at,
        require_output_absent=True,
    )
    validate_incident(payload, root=args.root, verify_live=True)
    if not args.write:
        print(json_bytes(payload).decode("utf-8"), end="")
        return 0
    record = publish_incident(payload, root=args.root)
    print(
        "P07_BACKEND_FORMALIZATION_INCIDENT_RECORDED "
        "hash={} path={} sha256={}".format(
            payload[SELF_HASH_FIELD], record["path"], record["sha256"]
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
