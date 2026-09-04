#!/usr/bin/env python3
"""Freeze the additive P07 queue-58 orphan-parent-loss recovery contract.

This builder is deliberately read-only until its final no-clobber lock publish.
It can run only after every process that can still mutate the queue-58 attempt,
raw bag, or frontend run directory has exited.  The canonical queue-58 chain is
frozen as ``PLANNED -> RUNNING``; the runtime governed by this lock later adds
an infrastructure ``FAILED`` event and allocates a distinct M attempt02.

No VINS process is started and no trajectory payload is read.  ROS-bag access
is limited to metadata/topic counts for the reproducible frontend raw cache.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import rosbag

try:
    from scripts import audit_p07_frontend_export_v3 as frontend_audit
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_queue_v6 as queue_v6
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as frontend_audit  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_queue_v6 as queue_v6  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


SCHEMA = "isj-p07-q58-orphan-parent-loss-replacement-lock-v1"
STATUS = "FROZEN_READY_FOR_Q58_ORPHAN_ATTEMPT02_RECOVERY"
SELF_HASH_FIELD = "replacement_lock_hash"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
REASON_CODE = "ORCHESTRATOR_PARENT_LOSS_AFTER_CANONICAL_E01"
ORIGINAL_QUEUE_INDEX = 58
WINDOW_ID = "aqualoc_archaeology:A07:0001"
ORIGINAL_TAG = "isj_p07_aqualoc_archaeology_a07_0001_m_attempt01"
REPLACEMENT_TAG = "isj_p07_aqualoc_archaeology_a07_0001_m_attempt02"
REPLACEMENT_SUFFIX = "_orphan_attempt02"
EXPECTED_RAW_TOPIC_COUNTS = {
    "/camera/image_raw": 901,
    "/rtimulib_node/imu": 8968,
    "/aqualoc/colmap_gt": 46,
}
FORBIDDEN_ORIGINAL_ATTEMPT_OUTPUTS = {
    "attestation.log",
    "audit_v3.json",
    "audit_v3.log",
    "audit_v4.json",
    "audit_v4.log",
    "output_hash_manifest.sha256",
}
ACTION_ORDER = [
    "classify-original",
    "register",
    "preflight-replacement",
    "execute-replacement",
    "closeout",
    "resume-preflight/resume-execute:59",
    "resume-preflight/resume-execute:60",
    "build-final-d-lock-v3-replacement-aware",
    "resolve-final-d-v3-replacement-aware",
]

ROOT = governance.ROOT
P07 = governance.P07
REPLACEMENT_ROOT = P07 / "frontend_replacements"
OUTPUT = REPLACEMENT_ROOT / "queue_058_a07_orphan_attempt02_lock_v1.json"
CLASSIFICATION = (
    REPLACEMENT_ROOT / "queue_058_a07_orphan_attempt01_classification_v1.json"
)
REGISTRATION = REPLACEMENT_ROOT / "queue_058_a07_orphan_attempt02_registration_v1.json"
CLOSEOUT = REPLACEMENT_ROOT / "queue_058_a07_orphan_attempt02_closeout_v1.json"
LEDGER = REPLACEMENT_ROOT / "replacement_ledger_v1.jsonl"
ATTEMPT_DIR = P07 / "frontend_attempts" / f"queue_058_{REPLACEMENT_TAG}"
ORIGINAL_ATTEMPT_DIR = P07 / "frontend_attempts" / f"queue_058_{ORIGINAL_TAG}"
RAW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo07_900_1800.bag"
ORIGINAL_RUN_DIR = (
    ROOT / "logs/aqualoc_archaeo_vins" / f"external_xfeat_every2_{ORIGINAL_TAG}"
)
REPLACEMENT_RUN_DIR = (
    ROOT / "logs/aqualoc_archaeo_vins" / f"external_xfeat_every2_{REPLACEMENT_TAG}"
)

Q55_LOCK = REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_lock_v1.json"
Q55_REGISTRATION = (
    REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_registration_v1.json"
)
Q55_CLOSEOUT = REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_closeout_v1.json"
Q55_RECLAIM_CLOSEOUT = (
    REPLACEMENT_ROOT / "queue_055_a04_layout_attempt02_raw_reclaim_closeout_v1.json"
)
A04_PATH_CORRECTION_LOCK = (
    REPLACEMENT_ROOT / "queue_055_a04_d_path_correction_lock_v1.json"
)
A04_D_LOCK = P07 / "d_resolution_locks/aqualoc_archaeology_a04_0002_v4.json"
A04_D_EVIDENCE = (
    P07 / "d_resolutions/aqualoc_archaeology_a04_0002_not_applicable_v2.json"
)


class OrphanReplacementLockError(RuntimeError):
    """Raised when queue 58 cannot be frozen without ambiguity."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hash(payload: dict[str, Any], field: str = SELF_HASH_FIELD) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def display_path(path: Path) -> str:
    return frontend_audit.display_path(path)


def file_record(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    stat = path.stat()
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def prefix_snapshot(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {
        "path": display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise OrphanReplacementLockError(f"invalid CSV: {path}")
    return fields, [dict(row) for row in rows]


def replacement_run_id(original_run_id: str) -> str:
    if not original_run_id or original_run_id.endswith(REPLACEMENT_SUFFIX):
        raise OrphanReplacementLockError("invalid original run_id")
    return original_run_id + REPLACEMENT_SUFFIX


def build_effective_queue_row(original: dict[str, str]) -> dict[str, str]:
    if (
        original.get("queue_index") != str(ORIGINAL_QUEUE_INDEX)
        or original.get("window_id") != WINDOW_ID
        or original.get("tag") != ORIGINAL_TAG
        or original.get("arm") != governance.M_ARM
    ):
        raise OrphanReplacementLockError("canonical q58 queue identity mismatch")
    old_token = f"TAG={ORIGINAL_TAG}"
    new_token = f"TAG={REPLACEMENT_TAG}"
    command = original.get("command", "")
    if command.count(old_token) != 1 or REPLACEMENT_TAG in command:
        raise OrphanReplacementLockError("q58 command lacks one exact TAG assignment")
    effective = dict(original)
    effective["tag"] = REPLACEMENT_TAG
    effective["command"] = command.replace(old_token, new_token, 1)
    effective["command_sha256"] = hashlib.sha256(
        effective["command"].encode("utf-8")
    ).hexdigest()
    expected_bag = original.get("expected_feature_bag", "")
    if ORIGINAL_TAG not in expected_bag:
        raise OrphanReplacementLockError("q58 expected feature bag lacks original tag")
    effective["expected_feature_bag"] = expected_bag.replace(
        ORIGINAL_TAG, REPLACEMENT_TAG, 1
    )
    assert_tag_only_command_diff(original, effective)
    return effective


def assert_tag_only_command_diff(
    original: dict[str, str], effective: dict[str, str]
) -> None:
    changed = {
        key for key in set(original) | set(effective) if original.get(key) != effective.get(key)
    }
    if changed != {"tag", "command", "command_sha256", "expected_feature_bag"}:
        raise OrphanReplacementLockError(
            f"replacement changes forbidden queue fields: {sorted(changed)}"
        )
    expected_command = original["command"].replace(
        f"TAG={ORIGINAL_TAG}", f"TAG={REPLACEMENT_TAG}", 1
    )
    expected_bag = original["expected_feature_bag"].replace(
        ORIGINAL_TAG, REPLACEMENT_TAG, 1
    )
    if (
        effective["command"] != expected_command
        or effective["expected_feature_bag"] != expected_bag
        or hashlib.sha256(effective["command"].encode("utf-8")).hexdigest()
        != effective["command_sha256"]
    ):
        raise OrphanReplacementLockError("replacement is not an exact identity-only rewrite")


def build_effective_allocation_row(
    original: dict[str, str], effective_queue: dict[str, str], *, allocated_at: str
) -> dict[str, str]:
    effective = dict(original)
    effective.update(
        {
            "run_id": replacement_run_id(original["run_id"]),
            "allocated_at": allocated_at,
            "tag": effective_queue["tag"],
            "command_sha256": effective_queue["command_sha256"],
            "command_source": display_path(OUTPUT) + "#replacement.effective_queue_row",
            "expected_feature_bag": effective_queue["expected_feature_bag"],
            "status": "PLANNED",
        }
    )
    return effective


def validate_original_running_chain(
    chain: Iterable[dict[str, str]], original_run_id: str
) -> list[dict[str, str]]:
    observed = [dict(row) for row in chain]
    if len(observed) != 2 or [row.get("status") for row in observed] != [
        "PLANNED",
        "RUNNING",
    ]:
        raise OrphanReplacementLockError("q58 must be exact e00/e01 RUNNING")
    for index, row in enumerate(observed):
        if (
            row.get("run_id") != original_run_id
            or row.get("registry_event_id") != f"{original_run_id}_e{index:02d}"
            or row.get("supersedes_event_id")
            != ("" if index == 0 else f"{original_run_id}_e{index - 1:02d}")
        ):
            raise OrphanReplacementLockError("q58 registry chain is not contiguous")
    running = observed[-1]
    if (
        running.get("command_file") != display_path(ORIGINAL_ATTEMPT_DIR / "command.txt")
        or running.get("input_hash_manifest")
        != display_path(ORIGINAL_ATTEMPT_DIR / "input_hash_manifest.sha256")
        or running.get("infrastructure_failure") not in {"", None}
        or "generalized v3 no-clobber executor started queue_index=58" not in running.get(
            "notes", ""
        )
        or "trajectory outcome not read" not in running.get("notes", "")
    ):
        raise OrphanReplacementLockError("q58 e01 identity or boundary mismatch")
    return observed


def _process_identity(pid_path: Path) -> dict[str, Any] | None:
    try:
        raw_cmdline = (pid_path / "cmdline").read_bytes()
        stat_fields = (pid_path / "stat").read_text(encoding="utf-8").split()
        status = (pid_path / "status").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    cmdline = " ".join(
        part.decode("utf-8", errors="replace") for part in raw_cmdline.split(b"\0") if part
    )
    if not cmdline or len(stat_fields) < 22:
        return None
    ppid = ""
    state = ""
    for line in status.splitlines():
        if line.startswith("PPid:"):
            ppid = line.split(":", 1)[1].strip()
        elif line.startswith("State:"):
            state = line.split(":", 1)[1].strip()
    return {
        "pid": int(pid_path.name),
        "ppid": int(ppid or 0),
        "state": state,
        "start_ticks": int(stat_fields[21]),
        "cmdline": cmdline,
    }


def matching_mutator_processes(proc_root: Path = Path("/proc")) -> list[dict[str, Any]]:
    markers = (
        str(RAW_BAG.resolve()),
        str(ORIGINAL_RUN_DIR.resolve()),
        ORIGINAL_TAG,
        "run_aqualoc_archaeo_vins_eval.sh external 7 900 1800 xfeat 2",
    )
    matches: list[dict[str, Any]] = []
    for pid_path in proc_root.iterdir():
        if not pid_path.name.isdigit() or int(pid_path.name) == os.getpid():
            continue
        identity = _process_identity(pid_path)
        if identity is not None and any(marker in identity["cmdline"] for marker in markers):
            matches.append(identity)
    return sorted(matches, key=lambda item: item["pid"])


def require_orphan_quiescence() -> dict[str, Any]:
    matches = matching_mutator_processes()
    if matches:
        raise OrphanReplacementLockError(
            "q58 mutator process still alive; recovery freeze forbidden: "
            + json.dumps(matches, sort_keys=True)
        )
    return {
        "observed_at": now(),
        "proc_scan": "NO_CMDLINE_MATCH_FOR_RAW_ATTEMPT_OR_RUN_DIR",
        "matching_processes": [],
        "natural_exit_required": True,
        "signal_or_process_mutation_performed": False,
    }


def inspect_raw_bag(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    try:
        with rosbag.Bag(str(path), "r") as bag:
            info = bag.get_type_and_topic_info().topics
            counts = {
                topic: int(info[topic].message_count) if topic in info else 0
                for topic in EXPECTED_RAW_TOPIC_COUNTS
            }
            compression = bag.get_compression_info()
    except Exception as exc:
        raise OrphanReplacementLockError(f"q58 raw bag is not readable: {exc}") from exc
    if counts != EXPECTED_RAW_TOPIC_COUNTS:
        raise OrphanReplacementLockError(
            f"q58 raw topic counts {counts} != {EXPECTED_RAW_TOPIC_COUNTS}"
        )
    stat = path.stat()
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": stat.st_size,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "topic_counts": counts,
        "compression_chunks": len(compression),
        "rosbag_metadata_only": True,
        "trajectory_payload_read": False,
    }


def verify_hash_manifest(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line:
            continue
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise OrphanReplacementLockError(
                f"invalid q58 input manifest line {number}"
            ) from exc
        candidate = ROOT / relative
        if (
            len(expected) != 64
            or not candidate.is_file()
            or candidate.is_symlink()
            or sha256(candidate) != expected
        ):
            raise OrphanReplacementLockError(
                f"q58 input manifest drift at line {number}: {relative}"
            )
        records.append({"path": relative, "sha256": expected})
    required = {
        display_path(Q55_LOCK),
        display_path(Q55_REGISTRATION),
        display_path(Q55_CLOSEOUT),
        display_path(A04_PATH_CORRECTION_LOCK),
        display_path(A04_D_LOCK),
        display_path(A04_D_EVIDENCE),
        "scripts/run_p07_a04_d_path_correction_v1.py",
    }
    observed = {record["path"] for record in records}
    missing = sorted(required - observed)
    if missing:
        raise OrphanReplacementLockError(
            f"q58 input manifest lacks correction/D evidence: {missing}"
        )
    return records


def tree_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir() or path.is_symlink():
        raise FileNotFoundError(path)
    files = sorted(item for item in path.rglob("*") if item.is_file())
    if any(item.is_symlink() for item in files):
        raise OrphanReplacementLockError(f"symlink in frozen orphan tree: {path}")
    return [file_record(item) for item in files]


def required_artifact_paths() -> list[Path]:
    return [
        P07 / "frontend_export_queue_v1.csv",
        P07 / "frontend_run_allocation_v1.csv",
        P07 / "frontend_orchestration_correction_lock_v6.json",
        P07 / "frontend_execution_correction_lock_v5.json",
        ROOT / "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
        Q55_LOCK,
        Q55_REGISTRATION,
        Q55_CLOSEOUT,
        Q55_RECLAIM_CLOSEOUT,
        A04_PATH_CORRECTION_LOCK,
        A04_D_LOCK,
        A04_D_EVIDENCE,
        ROOT / "scripts/run_p07_q55_a04_layout_replacement_v1.py",
        ROOT / "scripts/run_p07_a04_d_path_correction_v1.py",
        ROOT / "scripts/run_p07_frontend_export_job_v5.py",
        ROOT / "scripts/audit_p07_frontend_export_v4.py",
        ROOT / "scripts/build_p07_d_resolution_lock_v3.py",
        ROOT / "scripts/resolve_p07_d_applicability_v3.py",
        ROOT / "scripts/run_p07_mp_frontend_export_job_v2.py",
        ROOT / "scripts/build_p07_q58_orphan_replacement_lock_v1.py",
        ROOT / "scripts/run_p07_q58_orphan_replacement_v1.py",
        ROOT / "scripts/tests/test_p07_q58_orphan_replacement_v1.py",
    ]


def build_payload(
    *,
    frozen_at: str,
    original_queue: dict[str, str],
    original_allocation: dict[str, str],
    original_chain: list[dict[str, str]],
    artifacts: list[dict[str, Any]],
    stream_snapshots: list[dict[str, Any]],
    orphan_attempt_artifacts: list[dict[str, Any]],
    orphan_run_artifacts: list[dict[str, Any]],
    raw_cache: dict[str, Any],
    quiescence: dict[str, Any],
) -> dict[str, Any]:
    effective_queue = build_effective_queue_row(original_queue)
    effective_allocation = build_effective_allocation_row(
        original_allocation, effective_queue, allocated_at=frozen_at
    )
    new_run_id = effective_allocation["run_id"]
    payload: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": frozen_at,
        "original_queue_index": ORIGINAL_QUEUE_INDEX,
        "window_id": WINDOW_ID,
        "reason_code": REASON_CODE,
        "original_run_id": original_allocation["run_id"],
        "replacement_run_id": new_run_id,
        "replacement_tag": REPLACEMENT_TAG,
        "original": {
            "queue_row": original_queue,
            "allocation_row": original_allocation,
            "registry_running_chain": original_chain,
            "attempt_dir": display_path(ORIGINAL_ATTEMPT_DIR),
            "run_dir": display_path(ORIGINAL_RUN_DIR),
            "attempt_artifacts": orphan_attempt_artifacts,
            "run_artifacts": orphan_run_artifacts,
            "input_manifest_verified": True,
            "classification_path": display_path(CLASSIFICATION),
            "classification_required_status": "FAILED",
            "classification_infrastructure_failure": True,
            "unattested_output_must_not_be_reused": True,
        },
        "replacement": {
            "run_id": new_run_id,
            "tag": REPLACEMENT_TAG,
            "command": effective_queue["command"],
            "command_sha256": effective_queue["command_sha256"],
            "effective_queue_row": effective_queue,
            "effective_allocation_row": effective_allocation,
            "attempt_dir": display_path(ATTEMPT_DIR),
            "run_dir": display_path(REPLACEMENT_RUN_DIR),
            "registration_path": display_path(REGISTRATION),
            "closeout_path": display_path(CLOSEOUT),
            "replacement_for": {
                "original_queue_index": ORIGINAL_QUEUE_INDEX,
                "original_run_id": original_allocation["run_id"],
                "original_running_registry_event_id": original_chain[-1][
                    "registry_event_id"
                ],
                "reason_code": REASON_CODE,
            },
            "physical_frontend_rerun": True,
            "reuse_verified_raw_cache": True,
            "scientific_command_change_scope": ["TAG", "output_identity"],
            "scientific_parameters_changed": False,
        },
        "raw_cache": raw_cache,
        "orphan_quiescence": quiescence,
        "correction_and_d_evidence": [
            file_record(path)
            for path in (
                Q55_LOCK,
                Q55_REGISTRATION,
                Q55_CLOSEOUT,
                Q55_RECLAIM_CLOSEOUT,
                A04_PATH_CORRECTION_LOCK,
                A04_D_LOCK,
                A04_D_EVIDENCE,
            )
        ],
        "action_order": ACTION_ORDER,
        "allowed_remaining_indices": [59, 60],
        "remaining_queue_policy": {
            "canonical_rows_allocations_commands_unchanged": True,
            "effective_completed_slots": [55, 58],
            "q55_closeout_required": display_path(Q55_CLOSEOUT),
            "q58_closeout_required": display_path(CLOSEOUT),
            "final_d_resolution_requires_replacement_aware_adapter": True,
        },
        "replacement_ledger": {
            "path": display_path(LEDGER),
            "schema_version": "isj-p07-frontend-replacement-ledger-event-v1",
            "append_only": True,
        },
        "crash_policy": {
            "classification_e02_sidecar_gap": "RECONCILE_ONLY_IF_E02_BYTE_EXACT",
            "replacement_e00_sidecar_gap": "RECONCILE_ONLY_IF_E00_BYTE_EXACT",
            "replacement_registry_e02_ledger_gap": "RECONCILE_ONLY_EXACT_EVENT",
            "unknown_running_after_process_loss": (
                "FAIL_CLOSED_REQUIRES_NEW_ADDITIVE_REPLACEMENT_GOVERNANCE"
            ),
            "canonical_success_reconstruction_allowed": False,
        },
        "capacity_gate": {
            "frontend_output_minimum_free_bytes": 3 * 1024**3,
            "governance_minimum_free_bytes": 512 * 1024**2,
            "capacity_failure_creates_no_attempt": True,
        },
        "artifacts": artifacts,
        "mutable_stream_prefix_snapshots": stream_snapshots,
        "outcome_boundary": OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
        "vins_execution_allowed": False,
    }
    payload[SELF_HASH_FIELD] = document_hash(payload)
    return payload


def build_lock() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    queue_v6.validate_lock(ORIGINAL_QUEUE_INDEX, ORIGINAL_QUEUE_INDEX)
    original_queue = frontend_audit.queue_row(ORIGINAL_QUEUE_INDEX)
    original_allocation = frontend_audit.allocation_row(ORIGINAL_QUEUE_INDEX)
    chain = validate_original_running_chain(
        registry.registry_chain(original_allocation["run_id"]),
        original_allocation["run_id"],
    )
    if registry.registry_chain(replacement_run_id(original_allocation["run_id"])):
        raise OrphanReplacementLockError("q58 replacement registry identity already exists")
    for index, expected in ((57, "COMPLETED"), (59, "PLANNED"), (60, "PLANNED")):
        allocation = frontend_audit.allocation_row(index)
        status = registry.registry_chain(allocation["run_id"])[-1]["status"]
        if status != expected:
            raise OrphanReplacementLockError(
                f"queue {index} status {status} != {expected}"
            )
    collisions = [
        path
        for path in (CLASSIFICATION, REGISTRATION, CLOSEOUT, ATTEMPT_DIR, REPLACEMENT_RUN_DIR)
        if path.exists()
    ]
    if collisions:
        raise FileExistsError(f"q58 recovery collision: {collisions}")
    if not ORIGINAL_ATTEMPT_DIR.is_dir() or not ORIGINAL_RUN_DIR.is_dir():
        raise FileNotFoundError("q58 original attempt or run directory is missing")
    forbidden = sorted(
        name
        for name in FORBIDDEN_ORIGINAL_ATTEMPT_OUTPUTS
        if (ORIGINAL_ATTEMPT_DIR / name).exists()
    )
    if forbidden:
        raise OrphanReplacementLockError(
            f"q58 has post-command outer-executor artifacts; generic orphan path forbidden: {forbidden}"
        )
    command = (ORIGINAL_ATTEMPT_DIR / "command.txt").read_text(encoding="utf-8")
    if command != original_queue["command"] + "\n":
        raise OrphanReplacementLockError("q58 attempt command drift")
    verify_hash_manifest(ORIGINAL_ATTEMPT_DIR / "input_hash_manifest.sha256")
    quiescence = require_orphan_quiescence()
    raw_cache = inspect_raw_bag(RAW_BAG)
    attempt_artifacts = tree_records(ORIGINAL_ATTEMPT_DIR)
    run_artifacts = tree_records(ORIGINAL_RUN_DIR)
    if not run_artifacts:
        raise OrphanReplacementLockError("q58 orphan run directory contains no evidence")
    artifacts = [file_record(path) for path in required_artifact_paths()]
    return build_payload(
        frozen_at=now(),
        original_queue=original_queue,
        original_allocation=original_allocation,
        original_chain=chain,
        artifacts=artifacts,
        stream_snapshots=[
            prefix_snapshot(governance.BUNDLE / "run_registry.csv"),
            prefix_snapshot(LEDGER) if LEDGER.exists() else {
                "path": display_path(LEDGER),
                "sha256": hashlib.sha256(b"").hexdigest(),
                "size_bytes": 0,
            },
        ],
        orphan_attempt_artifacts=attempt_artifacts,
        orphan_run_artifacts=run_artifacts,
        raw_cache=raw_cache,
        quiescence=quiescence,
    )


def atomic_no_clobber_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    temporary = path.with_name(
        f".{path.name}.partial.{os.getpid()}.{secrets.token_hex(8)}"
    )
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.output != OUTPUT:
        raise OrphanReplacementLockError("formal lock path is fixed")
    payload = build_lock()
    atomic_no_clobber_json(args.output, payload)
    print(f"P07_Q58_ORPHAN_REPLACEMENT_LOCK_PASS hash={payload[SELF_HASH_FIELD]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
