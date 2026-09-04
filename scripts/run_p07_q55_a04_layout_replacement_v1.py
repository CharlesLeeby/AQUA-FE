#!/usr/bin/env python3
"""Execute and close the additive P07 q55 A04 layout replacement.

The canonical q55 registry chain remains terminal ``FAILED``.  This runtime
creates a new attempt02 chain, materializes the reproducible raw cache from the
root-layout archive, performs the unchanged RUN_VINS=0 frontend export, and
publishes a replacement closeout.  It also provides a narrowly scoped
replacement-aware predecessor adapter for canonical queue indices 56..60.
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
import subprocess
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

import rosbag

try:
    from scripts import audit_p07_frontend_export_v3 as audit_v3
    from scripts import audit_p07_frontend_export_v4 as audit_v4
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import build_p07_q55_a04_layout_replacement_lock_v1 as contract
    from scripts import reclaim_p07_raw_cache_v1 as raw_reclaim
    from scripts import resolve_p07_d_applicability_v2 as d_resolver_v2
    from scripts import resolve_p07_d_applicability_v4 as d_resolver_v4
    from scripts import run_p07_frontend_export_job_v3 as job_v3
    from scripts import run_p07_frontend_export_job_v5 as job_v5
    from scripts import run_p07_frontend_queue_v4 as queue_v4
    from scripts import run_p07_mp_frontend_export_job_v2 as base_job
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as audit_v3  # type: ignore
    import audit_p07_frontend_export_v4 as audit_v4  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import build_p07_q55_a04_layout_replacement_lock_v1 as contract  # type: ignore
    import reclaim_p07_raw_cache_v1 as raw_reclaim  # type: ignore
    import resolve_p07_d_applicability_v2 as d_resolver_v2  # type: ignore
    import resolve_p07_d_applicability_v4 as d_resolver_v4  # type: ignore
    import run_p07_frontend_export_job_v3 as job_v3  # type: ignore
    import run_p07_frontend_export_job_v5 as job_v5  # type: ignore
    import run_p07_frontend_queue_v4 as queue_v4  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base_job  # type: ignore


LOCK_PATH = contract.OUTPUT
RUN_REGISTRY = governance.BUNDLE / "run_registry.csv"
ACTION_LOCK = contract.REPLACEMENT_ROOT / ".queue_055_a04_layout_attempt02.lock"
MATERIALIZATION_REPORT = contract.ATTEMPT_DIR / "raw_materialization_v1.json"
MATERIALIZATION_LOG = contract.ATTEMPT_DIR / "raw_materialization.log"
MATERIALIZATION_ARGV = contract.ATTEMPT_DIR / "raw_materialization_argv.json"
MATERIALIZATION_CAPACITY = contract.ATTEMPT_DIR / "raw_materialization_capacity.json"
LEDGER_SCHEMA = "isj-p07-frontend-replacement-ledger-event-v1"
CLOSEOUT_SCHEMA = "isj-p07-frontend-layout-replacement-closeout-v1"


class ReplacementRuntimeError(RuntimeError):
    """Raised on any recovery contract, state, or evidence violation."""


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
        raise ReplacementRuntimeError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReplacementRuntimeError(f"JSON is not an object: {path}")
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


def validate_lock_payload(
    payload: dict[str, Any], *, root: Path = contract.ROOT, verify_artifacts: bool = True
) -> dict[str, Any]:
    if (
        payload.get("schema_version") != contract.SCHEMA
        or payload.get("status") != contract.STATUS
        or payload.get("original_queue_index") != contract.ORIGINAL_QUEUE_INDEX
        or payload.get("replacement_tag") != contract.REPLACEMENT_TAG
        or payload.get(contract.SELF_HASH_FIELD) != contract.document_hash(payload)
        or payload.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("vins_execution_allowed") is not False
    ):
        raise ReplacementRuntimeError("replacement lock schema, identity, hash, or boundary mismatch")
    original = payload.get("original")
    replacement = payload.get("replacement")
    materialization = payload.get("raw_materialization")
    if not all(isinstance(value, dict) for value in (original, replacement, materialization)):
        raise ReplacementRuntimeError("replacement lock sections are missing")
    assert isinstance(original, dict) and isinstance(replacement, dict)
    effective = replacement.get("effective_queue_row")
    if not isinstance(effective, dict):
        raise ReplacementRuntimeError("effective queue row missing")
    try:
        contract.assert_tag_only_command_diff(original["queue_row"], effective)
    except Exception as exc:
        raise ReplacementRuntimeError(f"scientific command drift: {exc}") from exc
    if (
        replacement.get("run_id") != payload.get("replacement_run_id")
        or replacement.get("tag") != contract.REPLACEMENT_TAG
        or replacement.get("command") != effective.get("command")
        or replacement.get("command_sha256") != effective.get("command_sha256")
        or not str(replacement.get("command", "")).startswith("RUN_VINS=0 ")
        or replacement.get("scientific_parameters_changed") is not False
        or replacement.get("scientific_command_change_scope") != ["TAG_BASE"]
    ):
        raise ReplacementRuntimeError("replacement identity or command policy mismatch")
    template = materialization.get("converter_argv_template")
    if (
        template != contract.materialization_argv_template()
        or materialization.get("expected_topic_counts") != contract.EXPECTED_TOPIC_COUNTS
        or materialization.get("target_raw_bag") != display_path(contract.RAW_BAG)
        or materialization.get("raw_bag_must_not_enter_replacement_output_manifest") is not True
    ):
        raise ReplacementRuntimeError("raw materialization contract mismatch")
    if payload.get("allowed_remaining_indices") != list(range(56, 61)):
        raise ReplacementRuntimeError("remaining queue range mismatch")
    if payload.get("action_order") != contract.ACTION_ORDER:
        raise ReplacementRuntimeError("replacement action order mismatch")
    if verify_artifacts:
        for record in payload.get("artifacts", []):
            if not isinstance(record, dict):
                raise ReplacementRuntimeError("invalid lock artifact record")
            path = root / str(record.get("path", ""))
            if (
                not path.is_file()
                or path.is_symlink()
                or path.stat().st_size != int(record.get("size_bytes", -1))
                or sha256(path) != record.get("sha256")
            ):
                raise ReplacementRuntimeError(f"locked artifact drift: {path}")
        for snapshot in payload.get("mutable_stream_prefix_snapshots", []):
            path = root / str(snapshot.get("path", ""))
            content = path.read_bytes()
            size = int(snapshot.get("size_bytes", -1))
            if (
                size < 0
                or len(content) < size
                or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
            ):
                raise ReplacementRuntimeError(f"append-only stream prefix drift: {path}")
    return payload


def load_lock(*, verify_artifacts: bool = True) -> dict[str, Any]:
    if not LOCK_PATH.is_file():
        raise ReplacementRuntimeError(f"missing formal replacement lock: {LOCK_PATH}")
    payload = validate_lock_payload(_json(LOCK_PATH), verify_artifacts=verify_artifacts)
    current_queue = audit_v3.queue_row(contract.ORIGINAL_QUEUE_INDEX)
    current_allocation = audit_v3.allocation_row(contract.ORIGINAL_QUEUE_INDEX)
    if (
        current_queue != payload["original"]["queue_row"]
        or current_allocation != payload["original"]["allocation_row"]
    ):
        raise ReplacementRuntimeError("canonical q55 queue or allocation drift")
    chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    frozen = payload["original"]["registry_failure_chain"]
    if chain[: len(frozen)] != frozen or len(chain) != len(frozen):
        raise ReplacementRuntimeError(
            "canonical q55 chain must remain exactly terminal e02 FAILED"
        )
    contract.validate_original_failure_chain(chain, payload["original_run_id"])
    return payload


def read_registry(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ReplacementRuntimeError(f"invalid registry: {path}")
    return fields, [dict(row) for row in rows]


def registry_chain(path: Path, run_id: str) -> list[dict[str, str]]:
    _fields, rows = read_registry(path)
    chain = [row for row in rows if row.get("run_id") == run_id]
    for index, row in enumerate(chain):
        expected_id = f"{run_id}_e{index:02d}"
        expected_parent = "" if index == 0 else f"{run_id}_e{index - 1:02d}"
        if (
            row.get("registry_event_id") != expected_id
            or row.get("supersedes_event_id") != expected_parent
        ):
            raise ReplacementRuntimeError(f"non-contiguous registry chain: {run_id}")
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
                raise ReplacementRuntimeError("registry row/header mismatch")
            run_id = row["run_id"]
            chain = [item for item in rows if item.get("run_id") == run_id]
            if expect_absent and chain:
                raise ReplacementRuntimeError(f"registry run already exists: {run_id}")
            if not expect_absent:
                if not chain or row["supersedes_event_id"] != chain[-1]["registry_event_id"]:
                    raise ReplacementRuntimeError("registry append parent mismatch")
            stream = io.StringIO(newline="")
            csv.DictWriter(stream, fieldnames=fields, lineterminator="\n").writerow(row)
            handle.seek(0, os.SEEK_END)
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def build_replacement_e00(
    payload: dict[str, Any], *, recorded_at: str
) -> dict[str, str]:
    original = dict(payload["original"]["registry_failure_chain"][0])
    replacement = payload["replacement"]
    new_run_id = payload["replacement_run_id"]
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
                f"replacement_for={payload['original_run_id']}; queue_index=55; "
                f"tag={contract.REPLACEMENT_TAG}; reason={contract.REASON_CODE}; "
                f"command_sha256={replacement['command_sha256']}; frontend export only; "
                "trajectory outcome not read; canonical q55 remains FAILED"
            ),
        }
    )
    return original


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
        raise ReplacementRuntimeError(f"registry latest {observed} != {expected_status}")
    previous = chain[-1]
    row = dict(previous)
    row.update(updates)
    row.update(
        {
            "registry_event_id": f"{run_id}_e{len(chain):02d}",
            "recorded_at": recorded_at or now(),
            "supersedes_event_id": previous["registry_event_id"],
            "status": status,
        }
    )
    _append_registry_row(path, row, expect_absent=False)
    return row


def ledger_events(path: Path, run_id: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReplacementRuntimeError(f"invalid replacement ledger line {number}") from exc
        if not isinstance(item, dict):
            raise ReplacementRuntimeError("replacement ledger event is not an object")
        if item.get("replacement_run_id") == run_id:
            events.append(item)
    for index, item in enumerate(events):
        expected = f"{run_id}_l{index:02d}"
        parent = "" if index == 0 else f"{run_id}_l{index - 1:02d}"
        if item.get("ledger_event_id") != expected or item.get("supersedes_event_id") != parent:
            raise ReplacementRuntimeError("replacement ledger chain is not contiguous")
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
            lines = handle.read().splitlines()
            all_items = [json.loads(line) for line in lines if line]
            if any(not isinstance(item, dict) for item in all_items):
                raise ReplacementRuntimeError("replacement ledger contains a non-object event")
            run_id = payload["replacement_run_id"]
            events = [item for item in all_items if item.get("replacement_run_id") == run_id]
            for position, item in enumerate(events):
                expected_id = f"{run_id}_l{position:02d}"
                expected_parent = "" if position == 0 else f"{run_id}_l{position - 1:02d}"
                if (
                    item.get("schema_version") != LEDGER_SCHEMA
                    or item.get("ledger_event_id") != expected_id
                    or item.get("supersedes_event_id") != expected_parent
                    or item.get("replacement_lock_hash")
                    != payload[contract.SELF_HASH_FIELD]
                    or item.get("trajectory_outcome_read") is not False
                ):
                    raise ReplacementRuntimeError(
                        "replacement ledger prefix identity or boundary mismatch"
                    )
            if events:
                exact_retries = [
                    item
                    for item in events
                    if item.get("event_type") == event_type
                    and item.get("status") == status
                    and item.get("registry_event_id")
                    == registry_event["registry_event_id"]
                    and item.get("replacement_lock_hash")
                    == payload[contract.SELF_HASH_FIELD]
                ]
                if len(exact_retries) == 1:
                    return exact_retries[0]
                if len(exact_retries) > 1 or any(
                    item.get("event_type") == event_type for item in events
                ):
                    raise ReplacementRuntimeError(
                        "replacement ledger contains a conflicting retry event"
                    )
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


def registration_record(payload: dict[str, Any]) -> dict[str, Any]:
    if not contract.REGISTRATION.is_file():
        raise ReplacementRuntimeError("replacement registration sidecar is missing")
    report = _json(contract.REGISTRATION)
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if (
        report.get("schema_version") != "isj-p07-frontend-layout-replacement-registration-v1"
        or report.get("status") != "ALLOCATED"
        or report.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or len(chain) < 1
        or report.get("registry_event") != chain[0]
    ):
        raise ReplacementRuntimeError("replacement registration sidecar mismatch")
    return report


def register(payload: dict[str, Any]) -> dict[str, Any]:
    if contract.REGISTRATION.exists():
        raise FileExistsError(contract.REGISTRATION)
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if chain:
        # Repair only the narrowly defined crash window in which the exact
        # immutable e00 reached the append-only registry but its sidecar did
        # not.  Any later/different state remains a hard collision.
        if len(chain) != 1 or chain[0].get("status") != "PLANNED":
            raise ReplacementRuntimeError("replacement registry chain already advanced")
        expected = build_replacement_e00(payload, recorded_at=chain[0]["recorded_at"])
        if chain[0] != expected:
            raise ReplacementRuntimeError("existing replacement e00 differs from frozen allocation")
        event = chain[0]
    else:
        event = build_replacement_e00(payload, recorded_at=now())
        _fields, _rows = read_registry(RUN_REGISTRY)
        _append_registry_row(RUN_REGISTRY, event, expect_absent=True)
    events = ledger_events(contract.LEDGER, payload["replacement_run_id"])
    if events:
        if (
            len(events) != 1
            or events[0].get("event_type") != "ALLOCATED"
            or events[0].get("status") != "PLANNED"
            or events[0].get("registry_event_id") != event["registry_event_id"]
        ):
            raise ReplacementRuntimeError("existing allocation ledger event mismatch")
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
        "schema_version": "isj-p07-frontend-layout-replacement-registration-v1",
        "status": "ALLOCATED",
        "recorded_at": now(),
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "original_run_id": payload["original_run_id"],
        "replacement_run_id": payload["replacement_run_id"],
        "replacement_tag": contract.REPLACEMENT_TAG,
        "effective_allocation_row": payload["replacement"]["effective_allocation_row"],
        "registry_event": event,
        "ledger_event": ledger,
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    atomic_json(contract.REGISTRATION, report)
    return report


def _capacity(path: Path, minimum: int) -> dict[str, Any]:
    usage = shutil.disk_usage(path)
    return {
        "path": display_path(path),
        "free_bytes": usage.free,
        "minimum_free_bytes": minimum,
        "pass": usage.free >= minimum,
    }


def _exclusive_text(path: Path, text: str) -> None:
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def inspect_raw_bag(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ReplacementRuntimeError(f"raw bag missing or symlink: {path}")
    counts: Counter[str] = Counter()
    previous_stamp: dict[str, int] = {}
    first_stamp: dict[str, int] = {}
    last_stamp: dict[str, int] = {}
    with rosbag.Bag(str(path), "r") as bag:
        for topic, message, record_stamp in bag.read_messages():
            counts[topic] += 1
            header = getattr(message, "header", None)
            message_stamp = getattr(header, "stamp", None)
            stamp = message_stamp if message_stamp is not None else record_stamp
            if not hasattr(stamp, "to_nsec"):
                raise ReplacementRuntimeError(f"raw bag topic lacks a ROS timestamp: {topic}")
            stamp_ns = int(stamp.to_nsec())
            if topic in previous_stamp and stamp_ns <= previous_stamp[topic]:
                raise ReplacementRuntimeError(
                    f"raw bag topic timestamps are not strictly increasing: {topic}"
                )
            first_stamp.setdefault(topic, stamp_ns)
            previous_stamp[topic] = stamp_ns
            last_stamp[topic] = stamp_ns
    if dict(counts) != contract.EXPECTED_TOPIC_COUNTS:
        raise ReplacementRuntimeError(
            f"raw bag topic counts {dict(counts)} != {contract.EXPECTED_TOPIC_COUNTS}"
        )
    stat = path.stat()
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "topic_counts": dict(counts),
        "topic_stamp_ranges_ns": {
            topic: {"first": first_stamp[topic], "last": last_stamp[topic]}
            for topic in sorted(counts)
        },
    }


def materialization_record(payload: dict[str, Any], *, require_raw: bool = True) -> dict[str, Any]:
    if not MATERIALIZATION_REPORT.is_file():
        raise ReplacementRuntimeError("raw materialization report is missing")
    report = _json(MATERIALIZATION_REPORT)
    if (
        report.get("schema_version") != "isj-p07-a04-raw-materialization-v1"
        or report.get("status") != "PASS"
        or report.get("replacement_run_id") != payload["replacement_run_id"]
        or report.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or report.get("expected_topic_counts") != contract.EXPECTED_TOPIC_COUNTS
        or report.get("trajectory_outcome_read") is not False
    ):
        raise ReplacementRuntimeError("raw materialization report mismatch")
    if require_raw:
        observed = inspect_raw_bag(contract.RAW_BAG)
        for key in (
            "path",
            "sha256",
            "size_bytes",
            "device",
            "inode",
            "topic_counts",
            "topic_stamp_ranges_ns",
        ):
            if report.get("raw_bag", {}).get(key) != observed[key]:
                raise ReplacementRuntimeError(f"raw materialization {key} drift")
    return report


def _materialize_impl(payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    registration_record(payload)
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
        raise ReplacementRuntimeError("materialize requires untouched replacement e00 PLANNED")
    if contract.RAW_BAG.exists() or contract.ATTEMPT_DIR.exists():
        raise FileExistsError("raw bag or replacement attempt collision")
    raw_minimum = int(payload["capacity_gate"]["raw_materialization_minimum_free_bytes"])
    governance_minimum = int(payload["capacity_gate"]["governance_minimum_free_bytes"])
    capacity = {
        "raw": _capacity(contract.RAW_BAG.parent, raw_minimum),
        "governance": _capacity(contract.P07, governance_minimum),
    }
    if not capacity["raw"]["pass"] or not capacity["governance"]["pass"]:
        raise ReplacementRuntimeError(f"raw materialization capacity gate failed: {capacity}")
    if sha256(contract.RAW_ARCHIVE) != contract.ARCHIVE_SHA256:
        raise ReplacementRuntimeError("A04 source archive checksum drift")
    layout = contract.validate_archive_layout(contract.RAW_ARCHIVE)
    contract.ATTEMPT_DIR.mkdir(parents=True, exist_ok=False)
    atomic_json(MATERIALIZATION_CAPACITY, capacity)
    temporary = contract.RAW_BAG.with_name(
        f".{contract.RAW_BAG.name}.partial.{os.getpid()}"
    )
    if temporary.exists():
        raise FileExistsError(temporary)
    template = list(payload["raw_materialization"]["converter_argv_template"])
    if template.count("{TEMP_OUTPUT_BAG}") != 1:
        raise ReplacementRuntimeError("materialization argv template token mismatch")
    argv = [str(temporary) if value == "{TEMP_OUTPUT_BAG}" else str(value) for value in template]
    atomic_json(
        MATERIALIZATION_ARGV,
        {
            "schema_version": "isj-p07-a04-raw-materialization-argv-v1",
            "argv": argv,
            "raw_root_argument": "",
            "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        },
    )
    try:
        with MATERIALIZATION_LOG.open("xb") as log:
            completed = subprocess.run(
                argv,
                cwd=contract.ROOT,
                env=job_v5.clean_environment(),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_s,
                check=False,
            )
        if completed.returncode != 0:
            raise ReplacementRuntimeError(f"raw converter failed rc={completed.returncode}")
        temporary_stats = inspect_raw_bag(temporary)
        try:
            os.link(temporary, contract.RAW_BAG)
        except FileExistsError as exc:
            raise FileExistsError(f"raw no-clobber publish collision: {contract.RAW_BAG}") from exc
        _fsync_directory(contract.RAW_BAG.parent)
        temporary.unlink()
        _fsync_directory(contract.RAW_BAG.parent)
        raw = inspect_raw_bag(contract.RAW_BAG)
        if any(raw[key] != temporary_stats[key] for key in ("sha256", "size_bytes", "device", "inode")):
            raise ReplacementRuntimeError("raw atomic publish changed inode or bytes")
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    report: dict[str, Any] = {
        "schema_version": "isj-p07-a04-raw-materialization-v1",
        "status": "PASS",
        "recorded_at": now(),
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "replacement_run_id": payload["replacement_run_id"],
        "converter_argv": argv,
        "source_archive": {
            "path": display_path(contract.RAW_ARCHIVE),
            "sha256": contract.ARCHIVE_SHA256,
            "layout": layout,
        },
        "ground_truth_input": {
            "path": display_path(contract.GT_INPUT),
            "sha256": contract.GT_SHA256,
        },
        "raw_bag": raw,
        "expected_topic_counts": contract.EXPECTED_TOPIC_COUNTS,
        "atomic_publish": "HARDLINK_NOREPLACE_THEN_UNLINK_TEMP",
        "reference_input_topics_read_for_integrity": True,
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    atomic_json(MATERIALIZATION_REPORT, report)
    return report


def _close_preexecution_failure(
    payload: dict[str, Any], *, phase: str, error: Exception
) -> None:
    """Make an ordinary pre-execution failure terminal and auditable."""

    run_id = payload["replacement_run_id"]
    chain = registry_chain(RUN_REGISTRY, run_id)
    if not chain:
        return
    latest = chain[-1]
    if latest["status"] == "PLANNED":
        running = append_transition(
            RUN_REGISTRY,
            run_id,
            expected_status="PLANNED",
            status="RUNNING",
            updates={
                "infrastructure_failure": "true",
                "notes": latest["notes"]
                + f"; replacement pre-execution phase entered: {phase}",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type=f"{phase}_STARTED",
            status="RUNNING",
            registry_event=running,
        )
        latest = running
    if latest["status"] == "RUNNING":
        failed = append_transition(
            RUN_REGISTRY,
            run_id,
            expected_status="RUNNING",
            status="FAILED",
            updates={
                "infrastructure_failure": "true",
                "notes": latest["notes"]
                + f"; replacement {phase} failed closed: {type(error).__name__}: {error}",
            },
        )
        append_ledger(
            contract.LEDGER,
            payload,
            event_type=f"{phase}_FAILED",
            status="FAILED",
            registry_event=failed,
        )


def materialize(payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    try:
        return _materialize_impl(payload, timeout_s=timeout_s)
    except Exception as error:
        if contract.ATTEMPT_DIR.exists():
            _close_preexecution_failure(
                payload, phase="RAW_MATERIALIZATION", error=error
            )
        raise


@contextmanager
def audit_overlay(
    effective_queue: dict[str, str], effective_allocation: dict[str, str]
) -> Iterator[None]:
    original_queue: Callable[[int], dict[str, str]] = audit_v3.queue_row
    original_allocation: Callable[[int], dict[str, str]] = audit_v3.allocation_row

    def queue(index: int) -> dict[str, str]:
        return dict(effective_queue) if index == contract.ORIGINAL_QUEUE_INDEX else original_queue(index)

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


def _write_input_manifest(payload: dict[str, Any], path: Path) -> None:
    if path.exists():
        raise FileExistsError(path)
    files = [LOCK_PATH, contract.REGISTRATION, MATERIALIZATION_REPORT]
    files.extend(contract.ROOT / str(item["path"]) for item in payload["artifacts"])
    base_job.write_hash_manifest(path, files)
    raw_real = str(contract.RAW_BAG.resolve())
    if raw_real in path.read_text(encoding="utf-8") or display_path(contract.RAW_BAG) in path.read_text(encoding="utf-8"):
        raise ReplacementRuntimeError("raw cache must be bound transitively, not directly in hash manifest")


def _run_inprocess_audit(
    payload: dict[str, Any], command_log: Path, attestation: Path
) -> tuple[Path, dict[str, Any]]:
    path = contract.ATTEMPT_DIR / "audit_v4.json"
    log_path = contract.ATTEMPT_DIR / "audit_v4.log"
    if path.exists() or log_path.exists():
        raise FileExistsError("replacement audit collision")
    effective_queue = payload["replacement"]["effective_queue_row"]
    effective_allocation = payload["replacement"]["effective_allocation_row"]
    with audit_overlay(effective_queue, effective_allocation):
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
        }
    )
    if (
        audit.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or audit.get("status") != "PASS"
        or audit.get("run_id") != payload["replacement_run_id"]
        or audit.get("command_sha256") != payload["replacement"]["command_sha256"]
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ReplacementRuntimeError("in-process v4 replacement audit mismatch")
    atomic_json(path, audit)
    _exclusive_text(
        log_path,
        "P07_FRONTEND_EXPORT_AUDIT_V4_PASS queue_index=55 "
        f"arm={audit['arm']} frames={audit['feature_bag']['feature_frames']}\n",
    )
    return path, audit


def _execute_impl(payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    registration_record(payload)
    materialization_record(payload)
    job_v5.load_and_validate_lock(contract.ORIGINAL_QUEUE_INDEX)
    chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
        raise ReplacementRuntimeError("execute requires replacement e00 PLANNED")
    row = dict(payload["replacement"]["effective_queue_row"])
    allocation = dict(payload["replacement"]["effective_allocation_row"])
    collisions = base_job.target_collisions(row)
    if collisions:
        raise FileExistsError(f"replacement output collision: {collisions}")
    expected_existing = {
        MATERIALIZATION_REPORT.name,
        MATERIALIZATION_LOG.name,
        MATERIALIZATION_ARGV.name,
        MATERIALIZATION_CAPACITY.name,
    }
    existing = {path.name for path in contract.ATTEMPT_DIR.iterdir() if path.is_file()}
    if existing != expected_existing:
        raise ReplacementRuntimeError(
            f"replacement attempt pre-execution contents mismatch: {sorted(existing)}"
        )
    output_minimum = int(payload["capacity_gate"]["frontend_output_minimum_free_bytes"])
    governance_minimum = int(payload["capacity_gate"]["governance_minimum_free_bytes"])
    capacity = {
        "output": _capacity(contract.ROOT / row["expected_run_root"], output_minimum),
        "governance": _capacity(contract.P07, governance_minimum),
    }
    if not capacity["output"]["pass"] or not capacity["governance"]["pass"]:
        raise ReplacementRuntimeError(f"replacement frontend capacity gate failed: {capacity}")
    command_path = contract.ATTEMPT_DIR / "command.txt"
    command_log = contract.ATTEMPT_DIR / "command.log"
    capacity_path = contract.ATTEMPT_DIR / "capacity_preflight.json"
    input_manifest = contract.ATTEMPT_DIR / "input_hash_manifest.sha256"
    _exclusive_text(command_path, row["command"] + "\n")
    atomic_json(capacity_path, capacity)
    _write_input_manifest(payload, input_manifest)
    environment = job_v5.clean_environment()
    running = False
    try:
        guard_log, guard_path = job_v3.run_guard_preflight(row, contract.ATTEMPT_DIR, environment)
        running_event = append_transition(
            RUN_REGISTRY,
            allocation["run_id"],
            expected_status="PLANNED",
            status="RUNNING",
            updates={
                "run_dir": row["expected_run_root"],
                "command_file": display_path(command_path),
                "input_hash_manifest": display_path(input_manifest),
                "notes": chain[-1]["notes"] + "; replacement executor started; guard-only preflight exact PASS",
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
            raise ReplacementRuntimeError(
                f"replacement frontend command failed rc={rc} timeout={str(timed_out).lower()}"
            )
        actual_guard = audit_v3.parse_guard_path(command_log)
        audit_v3.validate_guard(actual_guard, row["arm"])
        with audit_overlay(row, allocation):
            run_dir, feature_bag, probe_run, _summary, _duplicates = audit_v3.resolve_run_artifacts(row)
        attestation, _attestation_log = base_job.run_attestation(
            row, feature_bag, contract.ATTEMPT_DIR
        )
        audit_path, audit = _run_inprocess_audit(payload, command_log, attestation)
        run_dirs = [run_dir]
        if probe_run is not None and probe_run not in run_dirs:
            run_dirs.append(probe_run)
        output_manifest = contract.ATTEMPT_DIR / "output_hash_manifest.sha256"
        if output_manifest.exists():
            raise FileExistsError(output_manifest)
        files = base_job.output_files(
            run_dirs, contract.ATTEMPT_DIR, [guard_path, actual_guard]
        )
        files = [path for path in files if path.resolve() != contract.RAW_BAG.resolve()]
        base_job.write_hash_manifest(output_manifest, files)
        output_text = output_manifest.read_text(encoding="utf-8")
        if display_path(contract.RAW_BAG) in output_text or str(contract.RAW_BAG.resolve()) in output_text:
            raise ReplacementRuntimeError("replacement output manifest directly binds raw cache")
        lineage = str(audit["learned_lineages"]["accepted_learned_born_lineage_count"])
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
                "accepted_lineage_count": lineage,
                "active": str(int(lineage) > 0).lower(),
                "notes": registry_chain(RUN_REGISTRY, allocation["run_id"])[-1]["notes"]
                + "; replacement frontend export, attestation, and in-process strict v4 audit PASS; "
                + f"audit={display_path(audit_path)}; canonical q55 remains FAILED",
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
            "accepted_learned_born_lineage_count": int(lineage),
        }
    except Exception as error:
        if running:
            latest = registry_chain(RUN_REGISTRY, allocation["run_id"])[-1]
            if latest["status"] == "RUNNING":
                failed = append_transition(
                    RUN_REGISTRY,
                    allocation["run_id"],
                    expected_status="RUNNING",
                    status="FAILED",
                    updates={
                        "infrastructure_failure": "false",
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
            _close_preexecution_failure(
                payload, phase="GUARD_PREFLIGHT", error=error
            )
        raise


def execute(payload: dict[str, Any], *, timeout_s: int) -> dict[str, Any]:
    try:
        return _execute_impl(payload, timeout_s=timeout_s)
    except Exception as error:
        chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
        if chain and chain[-1]["status"] in {"PLANNED", "RUNNING"}:
            _close_preexecution_failure(
                payload, phase="FRONTEND_PREEXECUTION", error=error
            )
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
        raise ReplacementRuntimeError(
            f"replacement success ledger sequence mismatch: {observed}"
        )
    if any(
        item.get("schema_version") != LEDGER_SCHEMA
        or item.get("replacement_for") != payload["original_run_id"]
        or item.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or item.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or item.get("trajectory_outcome_read") is not False
        for item in events
    ):
        raise ReplacementRuntimeError("replacement success ledger identity drift")
    return events


def validate_closeout(payload: dict[str, Any], closeout: dict[str, Any]) -> dict[str, Any]:
    original_chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    replacement_chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    audit_path = contract.ATTEMPT_DIR / "audit_v4.json"
    if (
        closeout.get("schema_version") != CLOSEOUT_SCHEMA
        or closeout.get("status") != "PASS"
        or closeout.get("closeout_hash") != closeout_hash(closeout)
        or closeout.get("original_queue_index") != contract.ORIGINAL_QUEUE_INDEX
        or closeout.get("original_run_id") != payload["original_run_id"]
        or closeout.get("replacement_run_id") != payload["replacement_run_id"]
        or closeout.get("replacement_tag") != contract.REPLACEMENT_TAG
        or closeout.get("replacement_command")
        != payload["replacement"]["command"]
        or closeout.get("replacement_command_sha256")
        != payload["replacement"]["command_sha256"]
        or closeout.get("replacement_for")
        != payload["replacement"]["replacement_for"]
        or closeout.get("effective_slot_status") != "COMPLETED"
        or closeout.get("original_final_registry_event") != original_chain[-1]
        or closeout.get("completion_registry_event") != replacement_chain[-1]
        or closeout.get("physical_frontend_rerun") is not True
        or closeout.get("trajectory_outcome_read") is not False
        or closeout.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
        or closeout.get("replacement_lock_hash") != payload[contract.SELF_HASH_FIELD]
        or closeout.get("lock_path") != display_path(LOCK_PATH)
    ):
        raise ReplacementRuntimeError("replacement closeout identity, hash, or boundary mismatch")
    if len(original_chain) != 3 or original_chain[-1]["status"] != "FAILED":
        raise ReplacementRuntimeError("canonical q55 no longer terminal FAILED")
    if [row["status"] for row in original_chain] != ["PLANNED", "RUNNING", "FAILED"]:
        raise ReplacementRuntimeError("canonical q55 status chain drift")
    if len(replacement_chain) != 3 or [row["status"] for row in replacement_chain] != [
        "PLANNED",
        "RUNNING",
        "COMPLETED",
    ]:
        raise ReplacementRuntimeError("replacement registry chain is not e00/e01/e02 COMPLETED")
    ledger = validate_success_ledger(payload, replacement_chain)
    if closeout.get("replacement_ledger_event") != ledger[-1]:
        raise ReplacementRuntimeError("replacement closeout ledger event mismatch")
    audit_record = closeout.get("replacement_audit", {})
    if (
        not audit_path.is_file()
        or audit_record.get("path") != display_path(audit_path)
        or audit_record.get("sha256") != sha256(audit_path)
        or audit_record.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or audit_record.get("status") != "PASS"
    ):
        raise ReplacementRuntimeError("replacement closeout audit record mismatch")
    audit = _json(audit_path)
    if (
        audit.get("run_id") != payload["replacement_run_id"]
        or audit.get("tag") != contract.REPLACEMENT_TAG
        or audit.get("window_id") != contract.WINDOW_ID
        or audit.get("arm") != governance.P_ARM
        or audit.get("command_sha256") != payload["replacement"]["command_sha256"]
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ReplacementRuntimeError("replacement closeout audit identity mismatch")
    output_manifest_value = replacement_chain[-1].get("output_hash_manifest", "")
    output_manifest_path = contract.ROOT / output_manifest_value
    output_record = closeout.get("replacement_output_manifest", {})
    if (
        not output_manifest_value
        or not output_manifest_path.is_file()
        or output_record.get("path") != display_path(output_manifest_path)
        or output_record.get("sha256") != sha256(output_manifest_path)
        or output_record.get("size_bytes") != output_manifest_path.stat().st_size
    ):
        raise ReplacementRuntimeError("replacement closeout output manifest mismatch")
    materialization = materialization_record(payload, require_raw=False)
    materialization_record_in_closeout = closeout.get("raw_bag_materialization", {})
    if (
        materialization_record_in_closeout.get("path")
        != display_path(MATERIALIZATION_REPORT)
        or materialization_record_in_closeout.get("sha256")
        != sha256(MATERIALIZATION_REPORT)
        or materialization_record_in_closeout.get("schema_version")
        != materialization.get("schema_version")
        or materialization_record_in_closeout.get("status")
        != materialization.get("status")
        or materialization_record_in_closeout.get("raw_bag")
        != materialization.get("raw_bag")
    ):
        raise ReplacementRuntimeError("replacement closeout materialization record mismatch")
    return closeout


def load_closeout(payload: dict[str, Any]) -> dict[str, Any]:
    if not contract.CLOSEOUT.is_file():
        raise ReplacementRuntimeError("replacement closeout is missing")
    return validate_closeout(payload, _json(contract.CLOSEOUT))


def build_closeout_document(
    payload: dict[str, Any],
    *,
    original_final_event: dict[str, str],
    replacement_completion_event: dict[str, str],
    audit_path: Path,
    audit: dict[str, Any],
    output_manifest_path: Path,
    materialization: dict[str, Any],
    ledger_event: dict[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    """Build the immutable slot closeout without mutating either run chain."""

    if original_final_event.get("status") != "FAILED":
        raise ReplacementRuntimeError("closeout original event must remain FAILED")
    if replacement_completion_event.get("status") != "COMPLETED":
        raise ReplacementRuntimeError("closeout replacement event must be COMPLETED")
    report: dict[str, Any] = {
        "schema_version": CLOSEOUT_SCHEMA,
        "status": "PASS",
        "recorded_at": recorded_at,
        "original_queue_index": contract.ORIGINAL_QUEUE_INDEX,
        "original_run_id": payload["original_run_id"],
        "replacement_run_id": payload["replacement_run_id"],
        "replacement_tag": contract.REPLACEMENT_TAG,
        "replacement_command": payload["replacement"]["command"],
        "replacement_command_sha256": payload["replacement"]["command_sha256"],
        "replacement_for": payload["replacement"]["replacement_for"],
        "original_final_registry_event": original_final_event,
        "completion_registry_event": replacement_completion_event,
        "effective_slot_status": "COMPLETED",
        "replacement_audit": {
            "path": display_path(audit_path),
            "sha256": sha256(audit_path),
            "schema_version": audit["schema_version"],
            "status": audit["status"],
        },
        "replacement_output_manifest": {
            "path": display_path(output_manifest_path),
            "sha256": sha256(output_manifest_path),
            "size_bytes": output_manifest_path.stat().st_size,
        },
        "raw_bag_materialization": {
            "path": display_path(MATERIALIZATION_REPORT),
            "sha256": sha256(MATERIALIZATION_REPORT),
            "schema_version": materialization["schema_version"],
            "status": materialization["status"],
            "raw_bag": materialization["raw_bag"],
        },
        "replacement_ledger_event": ledger_event,
        "lock_path": display_path(LOCK_PATH),
        "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        "physical_frontend_rerun": True,
        "canonical_original_chain_preserved_failed": True,
        "scientific_parameters_changed": False,
        "scientific_command_change_scope": ["TAG_BASE"],
        "raw_cache_reclamation": payload["raw_cache_reclamation"],
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    report["closeout_hash"] = closeout_hash(report)
    return report


def closeout(payload: dict[str, Any]) -> dict[str, Any]:
    if contract.CLOSEOUT.exists():
        raise FileExistsError(contract.CLOSEOUT)
    original_chain = registry_chain(RUN_REGISTRY, payload["original_run_id"])
    replacement_chain = registry_chain(RUN_REGISTRY, payload["replacement_run_id"])
    if len(original_chain) != 3 or original_chain[-1]["status"] != "FAILED":
        raise ReplacementRuntimeError("canonical q55 must remain exact e02 FAILED")
    if len(replacement_chain) != 3 or [row["status"] for row in replacement_chain] != [
        "PLANNED",
        "RUNNING",
        "COMPLETED",
    ]:
        raise ReplacementRuntimeError("replacement must be exact e02 COMPLETED")
    materialization = materialization_record(payload)
    audit_path = contract.ATTEMPT_DIR / "audit_v4.json"
    audit = _json(audit_path)
    if (
        audit.get("status") != "PASS"
        or audit.get("run_id") != payload["replacement_run_id"]
        or audit.get("tag") != contract.REPLACEMENT_TAG
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ReplacementRuntimeError("replacement audit cannot close effective slot")
    output_manifest_path = (
        contract.ROOT / replacement_chain[-1]["output_hash_manifest"]
    )
    if not output_manifest_path.is_file():
        raise ReplacementRuntimeError("replacement output hash manifest is missing")
    # Reconcile the narrow crash window where registry e02 was durable but
    # the mirrored EXECUTION_COMPLETED ledger event was not.
    append_ledger(
        contract.LEDGER,
        payload,
        event_type="EXECUTION_COMPLETED",
        status="COMPLETED",
        registry_event=replacement_chain[-1],
    )
    ledger = append_ledger(
        contract.LEDGER,
        payload,
        event_type="EFFECTIVE_SLOT_CLOSEOUT",
        status="COMPLETED",
        registry_event=replacement_chain[-1],
    )
    report = build_closeout_document(
        payload,
        original_final_event=original_chain[-1],
        replacement_completion_event=replacement_chain[-1],
        audit_path=audit_path,
        audit=audit,
        output_manifest_path=output_manifest_path,
        materialization=materialization,
        ledger_event=ledger,
        recorded_at=now(),
    )
    atomic_json(contract.CLOSEOUT, report)
    return validate_closeout(payload, report)


def replacement_aware_ensure_predecessors(
    index: int, execution_lock: dict[str, Any], recovery: dict[str, Any]
) -> None:
    if index not in recovery["allowed_remaining_indices"]:
        raise ReplacementRuntimeError(f"queue index {index} is outside replacement-aware resume")
    load_closeout(recovery)
    order = [int(value) for value in execution_lock["execution_order"]]
    if index not in order:
        raise ReplacementRuntimeError("queue index absent from v5 execution order")
    for predecessor in order[: order.index(index)]:
        if predecessor == contract.ORIGINAL_QUEUE_INDEX:
            continue
        allocation = audit_v3.allocation_row(predecessor)
        chain = registry_chain(RUN_REGISTRY, allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ReplacementRuntimeError(
                f"queue {index} blocked by canonical predecessor {predecessor}"
            )
    if index >= 58 and not queue_v4.window_is_terminal_complete(contract.WINDOW_ID):
        raise ReplacementRuntimeError("queue 58+ requires terminal A04 D resolution")


def a04_terminal_d_evidence_files() -> list[Path]:
    """Return the exact terminal A04 D row evidence and its v4 resolution lock."""

    if not queue_v4.window_is_terminal_complete(contract.WINDOW_ID):
        raise ReplacementRuntimeError("A04 D is not terminal")
    applicability = governance.BUNDLE / "arm_applicability.csv"
    manifest = audit_v3.manifest_row(contract.WINDOW_ID)
    matched = d_resolver_v2.matching_applicability_rows(
        governance.read_csv(applicability), manifest
    )
    rows = [
        row for row in matched if row.get("resolution") != "PENDING_APPLICABILITY"
    ]
    if len(rows) != 1 or not rows[0].get("evidence_path"):
        raise ReplacementRuntimeError("A04 terminal D row is missing or ambiguous")
    try:
        validated_lock = d_resolver_v4.load_resolution_lock(contract.WINDOW_ID)
    except Exception as exc:
        raise ReplacementRuntimeError(f"A04 D v4 lock validation failed: {exc}") from exc
    if rows[0].get("resolver_hash") != validated_lock.get("resolution_lock_hash"):
        raise ReplacementRuntimeError("A04 terminal D row resolver hash mismatch")
    evidence = contract.ROOT / rows[0]["evidence_path"]
    resolution_lock = (
        contract.P07
        / "d_resolution_locks/aqualoc_archaeology_a04_0002_v4.json"
    )
    if not evidence.is_file() or not resolution_lock.is_file():
        raise ReplacementRuntimeError("A04 terminal D evidence or v4 lock is missing")
    # Do not hash-bind the mutable append-only applicability CSV itself: q60
    # will append a later D row.  The immutable v4 resolution lock already
    # binds the relevant applicability prefix.
    return [evidence, resolution_lock]


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
    """Bind every resumed canonical run to the additive dependency evidence."""

    original_writer = base_job.write_hash_manifest
    original_v3_append = job_v3.append_registry_event
    original_base_append = base_job.append_registry_event
    closeout_sha = sha256(contract.CLOSEOUT)
    extra_inputs = [
        LOCK_PATH,
        contract.CLOSEOUT,
        contract.REGISTRATION,
        Path(__file__).resolve(),
    ]
    if index >= 58:
        extra_inputs.extend(a04_terminal_d_evidence_files())

    def writer(path: Path, files: list[Path]) -> None:
        selected = list(files)
        if path.name == "input_hash_manifest.sha256":
            selected.extend(extra_inputs)
        original_writer(path, selected)
        if path.name == "input_hash_manifest.sha256":
            text = path.read_text(encoding="utf-8")
            for required in extra_inputs:
                if display_path(required) not in text and str(required) not in text:
                    raise ReplacementRuntimeError(
                        f"resumed input manifest omitted replacement evidence: {required}"
                    )

    def registry_append(*args, **kwargs):
        note = str(kwargs.get("note", ""))
        kwargs["note"] = (
            note
            + "; predecessor queue_index=55 satisfied by additive replacement "
            + f"run_id={recovery['replacement_run_id']}; "
            + f"closeout={display_path(contract.CLOSEOUT)}; closeout_sha256={closeout_sha}; "
            + "canonical q55 remains FAILED"
        )
        return original_v3_append(*args, **kwargs)

    base_job.write_hash_manifest = writer
    job_v3.append_registry_event = registry_append
    try:
        yield
    finally:
        base_job.write_hash_manifest = original_writer
        job_v3.append_registry_event = original_v3_append
        base_job.append_registry_event = original_base_append


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


def reclaim(payload: dict[str, Any]) -> dict[str, Any]:
    # Reserve the immutable binding-sidecar name before even a dry scan.  A
    # collision discovered after unlink would be an unrecoverable evidence
    # ordering violation.
    if contract.RECLAIM_CLOSEOUT.exists():
        raise FileExistsError(contract.RECLAIM_CLOSEOUT)
    close = load_closeout(payload)
    del close
    for index in (56, 57):
        allocation = audit_v3.allocation_row(index)
        chain = registry_chain(RUN_REGISTRY, allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ReplacementRuntimeError(f"raw reclaim blocked by queue {index}")
    if not queue_v4.window_is_terminal_complete(contract.WINDOW_ID):
        raise ReplacementRuntimeError("raw reclaim requires terminal A04 D")
    materialization_record(payload)
    original_loader = raw_reclaim._load_queue_and_allocations

    def overlay(root: Path):
        queues, allocations, queue_path, allocation_path = original_loader(root)
        queues[contract.ORIGINAL_QUEUE_INDEX] = dict(
            payload["replacement"]["effective_queue_row"]
        )
        allocations[contract.ORIGINAL_QUEUE_INDEX] = dict(
            payload["replacement"]["effective_allocation_row"]
        )
        return queues, allocations, queue_path, allocation_path

    raw_reclaim._load_queue_and_allocations = overlay
    try:
        dry = raw_reclaim.run(contract.ROOT, execute=False, window_id=contract.WINDOW_ID)
        candidates = dry.get("candidates", [])
        if len(candidates) != 1 or candidates[0].get("raw_cache_path") != display_path(contract.RAW_BAG):
            raise ReplacementRuntimeError(f"replacement-aware reclaim dry-run failed: {dry}")
        result = raw_reclaim.run(contract.ROOT, execute=True, window_id=contract.WINDOW_ID)
    finally:
        raw_reclaim._load_queue_and_allocations = original_loader
    if result.get("execution_errors"):
        raise ReplacementRuntimeError(f"replacement-aware raw reclaim failed: {result}")
    executed = result.get("executed", [])
    expected_path = display_path(contract.RAW_BAG)
    candidate_size = int(candidates[0]["size_bytes"])
    if (
        len(executed) != 1
        or executed[0].get("raw_cache_path") != expected_path
        or int(executed[0].get("bytes_freed", -1)) != candidate_size
        or int(result.get("bytes_freed", -1)) != candidate_size
        or contract.RAW_BAG.exists()
    ):
        raise ReplacementRuntimeError(
            f"replacement-aware raw reclaim terminal state mismatch: {result}"
        )
    receipt_path = contract.ROOT / str(executed[0].get("receipt_path", ""))
    if not receipt_path.is_file():
        raise ReplacementRuntimeError("replacement-aware reclaim receipt is missing")
    sidecar: dict[str, Any] = {
        "schema_version": "isj-p07-a04-replacement-raw-reclaim-closeout-v1",
        "status": "PASS",
        "recorded_at": now(),
        "window_id": contract.WINDOW_ID,
        "replacement_run_id": payload["replacement_run_id"],
        "raw_cache_path": expected_path,
        "raw_cache_sha256": candidates[0]["sha256"],
        "bytes_freed": candidate_size,
        "raw_cache_absent_after_unlink": True,
        "receipt": {
            "path": display_path(receipt_path),
            "sha256": sha256(receipt_path),
            "size_bytes": receipt_path.stat().st_size,
        },
        "recovery_lock": {
            "path": display_path(LOCK_PATH),
            "sha256": sha256(LOCK_PATH),
            "replacement_lock_hash": payload[contract.SELF_HASH_FIELD],
        },
        "replacement_closeout": {
            "path": display_path(contract.CLOSEOUT),
            "sha256": sha256(contract.CLOSEOUT),
            "closeout_hash": _json(contract.CLOSEOUT)["closeout_hash"],
        },
        "reclamation_result": {
            "event_id": executed[0].get("event_id"),
            "bytes_freed": result["bytes_freed"],
        },
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
    }
    sidecar["closeout_hash"] = contract.document_hash(sidecar, "closeout_hash")
    atomic_json(contract.RECLAIM_CLOSEOUT, sidecar)
    result["replacement_binding_sidecar"] = display_path(contract.RECLAIM_CLOSEOUT)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=(
            "register",
            "materialize",
            "execute",
            "closeout",
            "resume-preflight",
            "resume-execute",
            "reclaim",
        ),
    )
    parser.add_argument("--queue-index", type=int)
    parser.add_argument("--timeout-s", type=int, default=7200)
    args = parser.parse_args()
    if args.action.startswith("resume-"):
        if args.queue_index not in range(56, 61):
            raise ReplacementRuntimeError("resume action requires --queue-index 56..60")
    elif args.queue_index is not None:
        raise ReplacementRuntimeError("--queue-index is valid only for resume actions")
    with action_lock():
        payload = load_lock(verify_artifacts=True)
        if args.action == "register":
            result = register(payload)
        elif args.action == "materialize":
            result = materialize(payload, timeout_s=args.timeout_s)
        elif args.action == "execute":
            result = execute(payload, timeout_s=args.timeout_s)
        elif args.action == "closeout":
            result = closeout(payload)
        elif args.action == "resume-preflight":
            assert args.queue_index is not None
            result = resume_preflight(payload, args.queue_index)
        elif args.action == "resume-execute":
            assert args.queue_index is not None
            result = resume_execute(payload, args.queue_index, timeout_s=args.timeout_s)
        else:
            result = reclaim(payload)
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
