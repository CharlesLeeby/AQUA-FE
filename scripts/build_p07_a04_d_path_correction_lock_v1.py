#!/usr/bin/env python3
"""Freeze the additive A04 D-v4 workspace-path correction contract.

The queue-55 recovery contract is already immutable.  Its D-v4 resolver
rejects the workspace's long-standing top-level ``datasets`` symlink because
the resolved data files live on ``/mnt/data``.  This lock records that exact
filesystem topology and authorizes a narrowly scoped, fail-closed adapter; it
does not change the recovery lock, any frontend result, or D semantics.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts import audit_p07_frontend_export_v3 as audit_v3
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import build_p07_q55_a04_layout_replacement_lock_v1 as recovery_contract
    from scripts import resolve_p07_d_applicability_v2 as d_v2
    from scripts import resolve_p07_d_applicability_v4 as d_v4
    from scripts import run_p07_q55_a04_layout_replacement_v1 as recovery_runtime
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as audit_v3  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import build_p07_q55_a04_layout_replacement_lock_v1 as recovery_contract  # type: ignore
    import resolve_p07_d_applicability_v2 as d_v2  # type: ignore
    import resolve_p07_d_applicability_v4 as d_v4  # type: ignore
    import run_p07_q55_a04_layout_replacement_v1 as recovery_runtime  # type: ignore


ROOT = governance.ROOT
P07 = governance.P07
WINDOW_ID = "aqualoc_archaeology:A04:0002"
SCHEMA = "isj-p07-a04-d-path-correction-lock-v1"
STATUS = "FROZEN_READY_FOR_A04_D_PATH_CORRECTION"
SELF_HASH_FIELD = "correction_lock_hash"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
CORRECTION_ROOT = P07 / "frontend_replacements"
OUTPUT = CORRECTION_ROOT / "queue_055_a04_d_path_correction_lock_v1.json"
DATASETS_LINK = ROOT / "datasets"
D_V4_LOCK = d_v4.resolution_lock_path(WINDOW_ID)
APPLICABILITY = d_v2.APPLICABILITY
RUN_REGISTRY = governance.BUNDLE / "run_registry.csv"
REPLACEMENT_LEDGER = recovery_contract.LEDGER
RECOVERY_LOCK = recovery_contract.OUTPUT
RECOVERY_REGISTRATION = recovery_contract.REGISTRATION
RECOVERY_CLOSEOUT = recovery_contract.CLOSEOUT
WRAPPER = ROOT / "scripts/run_p07_a04_d_path_correction_v1.py"
TEST_FILE = ROOT / "scripts/tests/test_p07_a04_d_path_correction_v1.py"
EXPECTED_ZERO_ACTION_BAG_SHA256 = (
    "aa8cb878ec40d907d63f9b2f04f92fb500b0ce9cb0a368d40e06fc2410403548"
)
EXPECTED_ZERO_ACTION_BAG_SIZE = 13_727_106

ACTION_ORDER = [
    "FREEZE_CORRECTION_LOCK",
    "PREFLIGHT_CORRECTED_D_V4_NO_COLLISION",
    "BUILD_CORRECTED_D_V4_LOCK_NO_CLOBBER",
    "VALIDATE_ENHANCED_D_V4_LOCK",
    "RESOLVE_CORRECTED_D_V4_NO_CLOBBER",
    "VALIDATE_A04_D_TERMINAL_NOT_APPLICABLE",
    "RECLAIM_A04_RAW_CACHE",
    "RESUME_Q58",
    "RESUME_Q59",
    "RESUME_Q60",
    "RESOLVE_FINAL_A07_0001_D_V3",
]

LEGACY_D_FILES = [
    ROOT / "scripts/resolve_p07_d_applicability_v2.py",
    ROOT / "scripts/build_p07_d_resolution_lock_v2.py",
    ROOT / "scripts/resolve_p07_d_applicability_v3.py",
    ROOT / "scripts/build_p07_d_resolution_lock_v3.py",
    ROOT / "scripts/tests/test_p07_d_resolution_v3.py",
    ROOT / "scripts/resolve_p07_d_applicability_v4.py",
    ROOT / "scripts/build_p07_d_resolution_lock_v4.py",
    ROOT / "scripts/tests/test_p07_d_resolution_v4.py",
    ROOT / "scripts/run_p07_q55_a04_layout_replacement_v1.py",
]
CORRECTION_FILES = [Path(__file__).resolve(), WRAPPER, TEST_FILE]


class CorrectionLockError(RuntimeError):
    """Raised when the additive correction cannot be frozen safely."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.absolute().relative_to(ROOT.absolute()).as_posix()
    except ValueError as exc:
        raise CorrectionLockError(f"path is not lexically inside workspace: {path}") from exc


def document_hash(payload: Mapping[str, Any], field: str = SELF_HASH_FIELD) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CorrectionLockError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CorrectionLockError(f"{label} is not a JSON object: {path}")
    return value


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise CorrectionLockError(f"artifact must be a non-symlink regular file: {path}")
    return {
        "path": display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def prefix_snapshot(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise CorrectionLockError(f"stream must be a non-symlink regular file: {path}")
    content = path.read_bytes()
    return {
        "path": display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def _stat_record(value: os.stat_result) -> dict[str, int]:
    return {
        "device": int(value.st_dev),
        "inode": int(value.st_ino),
        "mode": int(value.st_mode),
        "nlink": int(value.st_nlink),
        "uid": int(value.st_uid),
        "gid": int(value.st_gid),
        "size_bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
    }


def datasets_symlink_identity(path: Path = DATASETS_LINK) -> dict[str, object]:
    try:
        link_stat = os.lstat(path)
        link_text = os.readlink(path)
        resolved = path.resolve(strict=True)
        target_stat = os.lstat(resolved)
    except OSError as exc:
        raise CorrectionLockError(f"cannot inspect datasets symlink: {path}: {exc}") from exc
    if not stat.S_ISLNK(link_stat.st_mode):
        raise CorrectionLockError(f"datasets entry is not the required top-level symlink: {path}")
    if not stat.S_ISDIR(target_stat.st_mode) or stat.S_ISLNK(target_stat.st_mode):
        raise CorrectionLockError("datasets resolved target is not a real directory")
    return {
        "workspace_entry": display_path(path),
        "lstat": _stat_record(link_stat),
        "readlink": link_text,
        "resolved_target": str(resolved),
        "resolved_target_lstat": _stat_record(target_stat),
    }


def _read_csv_prefix(snapshot: Mapping[str, object]) -> list[dict[str, str]]:
    path = ROOT / str(snapshot["path"])
    size = int(snapshot["size_bytes"])
    content = path.read_bytes()[:size]
    reader = csv.DictReader(io.StringIO(content.decode("utf-8"), newline=""))
    rows = list(reader)
    if not reader.fieldnames or any(None in row for row in rows):
        raise CorrectionLockError(f"invalid frozen CSV prefix: {path}")
    return rows


def _chain(run_id: str) -> list[dict[str, str]]:
    try:
        chain = recovery_runtime.registry_chain(RUN_REGISTRY, run_id)
    except Exception as exc:
        raise CorrectionLockError(f"invalid registry chain {run_id}: {exc}") from exc
    if not chain:
        raise CorrectionLockError(f"missing registry chain: {run_id}")
    return chain


def _attempt_evidence(
    *, queue_index: int, run_id: str, event: dict[str, str], attempt_dir: Path
) -> dict[str, object]:
    audit_path = attempt_dir / "audit_v4.json"
    input_manifest = ROOT / event.get("input_hash_manifest", "")
    output_manifest = ROOT / event.get("output_hash_manifest", "")
    audit = _json_object(audit_path, f"queue {queue_index} audit")
    feature = audit.get("feature_bag")
    if not isinstance(feature, dict):
        raise CorrectionLockError(f"queue {queue_index} feature-bag audit record missing")
    feature_path = ROOT / str(feature.get("path", ""))
    if (
        event.get("status") != "COMPLETED"
        or event.get("run_id") != run_id
        or audit.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or audit.get("status") != "PASS"
        or audit.get("queue_index") != queue_index
        or audit.get("run_id") != run_id
        or audit.get("window_id") != WINDOW_ID
        or audit.get("held_out_trajectory_outcome_read") is not False
        or not input_manifest.is_file()
        or not output_manifest.is_file()
        or not feature_path.is_file()
        or feature.get("sha256") != sha256(feature_path)
        or int(feature.get("size_bytes", -1)) != feature_path.stat().st_size
    ):
        raise CorrectionLockError(f"queue {queue_index} terminal evidence mismatch")
    return {
        "queue_index": queue_index,
        "run_id": run_id,
        "terminal_registry_event": event,
        "audit": file_record(audit_path),
        "input_hash_manifest": file_record(input_manifest),
        "output_hash_manifest": file_record(output_manifest),
        "feature_bag": file_record(feature_path),
        "accepted_learned_born_lineage_count": (
            audit.get("learned_lineages", {}).get(
                "accepted_learned_born_lineage_count"
            )
            if isinstance(audit.get("learned_lineages"), dict)
            else None
        ),
    }


def _applicability_state() -> dict[str, object]:
    manifest = audit_v3.manifest_row(WINDOW_ID)
    matched = d_v2.matching_applicability_rows(
        governance.read_csv(APPLICABILITY), manifest
    )
    pending = [row for row in matched if row.get("resolution") == "PENDING_APPLICABILITY"]
    terminal = [row for row in matched if row.get("resolution") != "PENDING_APPLICABILITY"]
    if len(pending) != 1 or terminal:
        raise CorrectionLockError(
            f"A04 D must be exactly one pending/no terminal before correction: {matched}"
        )
    return {
        "manifest_row": manifest,
        "matching_rows": matched,
        "pending_count": 1,
        "terminal_count": 0,
    }


def _assert_d_outputs_absent() -> dict[str, object]:
    possible = [d_v2.output_paths(WINDOW_ID, count)[0] for count in (0, 1)]
    derivation = d_v2.output_paths(WINDOW_ID, 1)[1]
    patterns = [
        D_V4_LOCK.parent.glob(f"{D_V4_LOCK.name}.partial.*"),
        possible[0].parent.glob(f"{possible[0].name}.partial.*"),
        possible[1].parent.glob(f"{possible[1].name}.partial.*"),
    ]
    partials = sorted(path for matches in patterns for path in matches)
    candidates = [D_V4_LOCK, *possible, *partials]
    if derivation is not None:
        candidates.append(derivation)
    collisions = [path for path in candidates if os.path.lexists(path)]
    if collisions:
        raise CorrectionLockError(f"preexisting A04 D artifact collision: {collisions}")
    return {
        "canonical_v4_lock": display_path(D_V4_LOCK),
        "canonical_v4_lock_exists": False,
        "legacy_partial_lock_paths": [],
        "legacy_partial_resolution_paths": [],
        "not_applicable_output": display_path(possible[0]),
        "not_applicable_output_exists": False,
        "applicable_output": display_path(possible[1]),
        "applicable_output_exists": False,
        "applicable_derivation_dir": display_path(derivation) if derivation else None,
        "applicable_derivation_dir_exists": False,
    }


def _legacy_failure_proof(
    d_state: Mapping[str, object],
    symlink: Mapping[str, object],
    allowlist: list[dict[str, object]],
) -> dict[str, object]:
    argv = [
        "python3",
        "scripts/build_p07_d_resolution_lock_v4.py",
        "--window-id",
        WINDOW_ID,
    ]
    watched = [RUN_REGISTRY, REPLACEMENT_LEDGER, APPLICABILITY]
    before = {display_path(path): prefix_snapshot(path) for path in watched}
    completed = subprocess.run(
        argv,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    after = {display_path(path): prefix_snapshot(path) for path in watched}
    observed_state = _assert_d_outputs_absent()
    combined = f"{completed.stdout}\n{completed.stderr}"
    if (
        completed.returncode != 1
        or "path escapes the workspace" not in combined
        or before != after
        or observed_state != dict(d_state)
    ):
        raise CorrectionLockError(
            "legacy D-v4 failure was not exact rc=1/pre-lock/no-mutation path escape"
        )
    archive = next(
        record for record in allowlist if "raw_data.tar.gz" in str(record["path"])
    )
    lexical = ROOT / str(archive["path"])
    return {
        "attempted_argv": argv,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "exception_type": "ResolutionViolation",
        "message_contains": "path escapes the workspace",
        "classification": "WORKSPACE_TOP_LEVEL_DATASETS_SYMLINK_FALSE_ESCAPE",
        "failure_phase": "PRE_LOCK_WRITE",
        "failing_workspace_relative_path": archive["path"],
        "failing_lexical_path": str(lexical),
        "failing_resolved_path": str(lexical.resolve(strict=True)),
        "frozen_datasets_target": symlink["resolved_target"],
        "canonical_d_lock_absent_after_failure": True,
        "mutable_streams_unchanged": True,
        "legacy_code_modified": False,
        "legacy_contract_hashes": {
            display_path(path): sha256(path) for path in LEGACY_D_FILES
        },
    }


def _terminal_evidence() -> tuple[dict[str, Any], list[dict[str, object]]]:
    recovery = recovery_runtime.load_lock(verify_artifacts=False)
    closeout = recovery_runtime.load_closeout(recovery)
    registration = _json_object(RECOVERY_REGISTRATION, "replacement registration")
    if (
        registration.get("schema_version")
        != "isj-p07-frontend-layout-replacement-registration-v1"
        or registration.get("status") != "ALLOCATED"
        or registration.get("replacement_run_id") != recovery["replacement_run_id"]
        or closeout.get("replacement_run_id") != recovery["replacement_run_id"]
    ):
        raise CorrectionLockError("q55 recovery registration/closeout identity mismatch")

    q55_event = closeout.get("completion_registry_event")
    if not isinstance(q55_event, dict):
        raise CorrectionLockError("q55 replacement completion event missing")
    q55 = _attempt_evidence(
        queue_index=55,
        run_id=str(recovery["replacement_run_id"]),
        event=q55_event,
        attempt_dir=recovery_contract.ATTEMPT_DIR,
    )

    evidence = [q55]
    for index in (56, 57):
        allocation = audit_v3.allocation_row(index)
        chain = _chain(allocation["run_id"])
        if len(chain) != 3 or [row["status"] for row in chain] != [
            "PLANNED",
            "RUNNING",
            "COMPLETED",
        ]:
            raise CorrectionLockError(f"queue {index} is not exact terminal COMPLETED")
        queue_row = next(
            row
            for row in governance.read_csv(governance.EXPORT_QUEUE)
            if int(row["queue_index"]) == index
        )
        attempt = P07 / "frontend_attempts" / f"queue_{index:03d}_{queue_row['tag']}"
        evidence.append(
            _attempt_evidence(
                queue_index=index,
                run_id=allocation["run_id"],
                event=chain[-1],
                attempt_dir=attempt,
            )
        )

    original_chain = _chain(str(recovery["original_run_id"]))
    replacement_chain = _chain(str(recovery["replacement_run_id"]))
    if (
        [row["status"] for row in original_chain] != ["PLANNED", "RUNNING", "FAILED"]
        or [row["status"] for row in replacement_chain]
        != ["PLANNED", "RUNNING", "COMPLETED"]
        or replacement_chain[-1] != q55_event
    ):
        raise CorrectionLockError("q55 original/replacement registry boundary drift")

    return (
        {
            "original_q55_terminal_event": original_chain[-1],
            "replacement_q55_terminal_event": replacement_chain[-1],
            "recovery_lock_hash": recovery[recovery_contract.SELF_HASH_FIELD],
            "recovery_closeout_hash": closeout["closeout_hash"],
        },
        evidence,
    )


def _datasets_allowlist() -> list[dict[str, object]]:
    """Derive the only two external-target paths from the frozen recovery lock."""

    recovery = _json_object(RECOVERY_LOCK, "q55 recovery lock")
    materialization = recovery.get("raw_materialization")
    artifacts = recovery.get("artifacts")
    if not isinstance(materialization, dict) or not isinstance(artifacts, list):
        raise CorrectionLockError("recovery lock lacks materialization/artifact records")
    expected_paths = {
        str(materialization.get("source_archive", "")),
        str(materialization.get("ground_truth_input", "")),
    }
    if "" in expected_paths or len(expected_paths) != 2:
        raise CorrectionLockError("recovery lock does not identify exactly archive plus GT")
    records: list[dict[str, object]] = []
    for record in artifacts:
        if not isinstance(record, dict) or str(record.get("path", "")) not in expected_paths:
            continue
        if (
            not isinstance(record.get("sha256"), str)
            or len(str(record["sha256"])) != 64
            or int(record.get("size_bytes", -1)) < 0
        ):
            raise CorrectionLockError("invalid frozen datasets artifact record")
        records.append(
            {
                "path": str(record["path"]),
                "sha256": str(record["sha256"]),
                "size_bytes": int(record["size_bytes"]),
                "source": "q55_recovery_lock.artifacts",
            }
        )
    if {str(record["path"]) for record in records} != expected_paths or len(records) != 2:
        raise CorrectionLockError(
            "recovery lock datasets allowlist must be exact archive and ground truth"
        )
    return sorted(records, key=lambda record: str(record["path"]))


def verify_datasets_allowlist(
    records: list[dict[str, object]], symlink: Mapping[str, object]
) -> None:
    """Hash both external files after proving no second symlink is traversed."""

    target = Path(str(symlink["resolved_target"]))
    for record in records:
        relative = Path(str(record["path"]))
        if relative.is_absolute() or relative.parts[:1] != ("datasets",):
            raise CorrectionLockError(f"invalid datasets allowlist path: {relative}")
        candidate = ROOT / relative
        cursor = ROOT / "datasets"
        for component in relative.parts[1:]:
            cursor = cursor / component
            try:
                item_stat = os.lstat(cursor)
            except OSError as exc:
                raise CorrectionLockError(f"missing allowlisted data component: {cursor}") from exc
            if stat.S_ISLNK(item_stat.st_mode):
                raise CorrectionLockError(f"nested/leaf datasets symlink is forbidden: {cursor}")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(target)
        except (OSError, ValueError) as exc:
            raise CorrectionLockError(f"allowlisted data path escapes frozen target: {candidate}") from exc
        if (
            not stat.S_ISREG(os.lstat(candidate).st_mode)
            or candidate.stat().st_size != int(record["size_bytes"])
            or sha256(candidate) != record["sha256"]
        ):
            raise CorrectionLockError(f"allowlisted datasets artifact drift: {candidate}")


def _strict_internal_file(relative_text: str) -> Path:
    relative = Path(relative_text)
    if (
        not relative_text
        or relative.is_absolute()
        or ".." in relative.parts
        or relative.parts[:1] == ("datasets",)
    ):
        raise CorrectionLockError(f"invalid internal recovery artifact path: {relative_text}")
    cursor = ROOT
    for component in relative.parts:
        cursor = cursor / component
        try:
            item_stat = os.lstat(cursor)
        except OSError as exc:
            raise CorrectionLockError(f"missing recovery artifact component: {cursor}") from exc
        if stat.S_ISLNK(item_stat.st_mode):
            raise CorrectionLockError(f"recovery artifact traverses symlink: {cursor}")
    try:
        cursor.resolve(strict=True).relative_to(ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise CorrectionLockError(f"recovery artifact escapes workspace: {cursor}") from exc
    if not stat.S_ISREG(os.lstat(cursor).st_mode):
        raise CorrectionLockError(f"recovery artifact is not regular: {cursor}")
    return cursor


def verify_frozen_recovery_contract(
    recovery: dict[str, Any],
    allowlist: list[dict[str, object]],
    symlink: Mapping[str, object],
) -> None:
    """Verify every old-lock artifact and stream against its old frozen record."""

    recovery_runtime.validate_lock_payload(recovery, verify_artifacts=False)
    artifacts = recovery.get("artifacts")
    snapshots = recovery.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not isinstance(snapshots, list):
        raise CorrectionLockError("frozen recovery artifacts/snapshots are missing")
    allowed = {str(record["path"]): record for record in allowlist}
    seen_external: set[str] = set()
    for record in artifacts:
        if not isinstance(record, dict):
            raise CorrectionLockError("invalid frozen recovery artifact record")
        relative = str(record.get("path", ""))
        if relative.startswith("datasets/"):
            if relative not in allowed or {
                "sha256": str(record.get("sha256", "")),
                "size_bytes": int(record.get("size_bytes", -1)),
            } != {
                "sha256": str(allowed[relative]["sha256"]),
                "size_bytes": int(allowed[relative]["size_bytes"]),
            }:
                raise CorrectionLockError(
                    f"recovery datasets record is not in exact allowlist: {relative}"
                )
            seen_external.add(relative)
            continue  # verify_datasets_allowlist already performed the live hashes.
        path = _strict_internal_file(relative)
        if (
            path.stat().st_size != int(record.get("size_bytes", -1))
            or sha256(path) != record.get("sha256")
        ):
            raise CorrectionLockError(f"frozen recovery artifact drift: {path}")
    if seen_external != set(allowed):
        raise CorrectionLockError("frozen recovery lock does not use exact datasets allowlist")
    verify_datasets_allowlist(allowlist, symlink)
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise CorrectionLockError("invalid frozen recovery stream snapshot")
        path = _strict_internal_file(str(snapshot.get("path", "")))
        content = path.read_bytes()
        size = int(snapshot.get("size_bytes", -1))
        if (
            size < 0
            or len(content) < size
            or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
        ):
            raise CorrectionLockError(f"frozen recovery stream prefix drift: {path}")


def _pre_resume_rows() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index in range(58, 61):
        allocation = audit_v3.allocation_row(index)
        chain = _chain(allocation["run_id"])
        if len(chain) != 1 or chain[0].get("status") != "PLANNED":
            raise CorrectionLockError(f"queue {index} is not pristine PLANNED")
        result.append(
            {
                "queue_index": index,
                "run_id": allocation["run_id"],
                "frozen_planned_registry_event": chain[0],
            }
        )
    return result


def build_lock() -> dict[str, object]:
    if os.path.lexists(OUTPUT):
        raise FileExistsError(OUTPUT)
    d_state = _assert_d_outputs_absent()
    applicability = _applicability_state()
    recovery_summary, frontend_evidence = _terminal_evidence()
    symlink = datasets_symlink_identity()
    datasets_allowlist = _datasets_allowlist()
    recovery_payload = _json_object(RECOVERY_LOCK, "q55 recovery lock")
    verify_frozen_recovery_contract(recovery_payload, datasets_allowlist, symlink)
    legacy_failure = _legacy_failure_proof(d_state, symlink, datasets_allowlist)

    p_evidence = next(
        item for item in frontend_evidence if item["queue_index"] == 55
    )
    b1_evidence = next(
        item for item in frontend_evidence if item["queue_index"] == 57
    )
    if (
        p_evidence.get("accepted_learned_born_lineage_count") != 0
        or p_evidence["feature_bag"]["sha256"] != EXPECTED_ZERO_ACTION_BAG_SHA256  # type: ignore[index]
        or b1_evidence["feature_bag"]["sha256"] != EXPECTED_ZERO_ACTION_BAG_SHA256  # type: ignore[index]
        or int(p_evidence["feature_bag"]["size_bytes"]) != EXPECTED_ZERO_ACTION_BAG_SIZE  # type: ignore[index]
        or int(b1_evidence["feature_bag"]["size_bytes"]) != EXPECTED_ZERO_ACTION_BAG_SIZE  # type: ignore[index]
    ):
        raise CorrectionLockError("A04 zero-action P/B1 identity contract mismatch")

    artifacts = [
        RECOVERY_LOCK,
        RECOVERY_REGISTRATION,
        RECOVERY_CLOSEOUT,
        governance.D_QUEUE,
        *LEGACY_D_FILES,
        *CORRECTION_FILES,
    ]
    for item in frontend_evidence:
        artifacts.extend(
            [
                ROOT / str(item["audit"]["path"]),  # type: ignore[index]
                ROOT / str(item["input_hash_manifest"]["path"]),  # type: ignore[index]
                ROOT / str(item["output_hash_manifest"]["path"]),  # type: ignore[index]
            ]
        )
    artifact_records = [file_record(path) for path in dict.fromkeys(artifacts)]
    snapshots = [
        prefix_snapshot(RUN_REGISTRY),
        prefix_snapshot(REPLACEMENT_LEDGER),
        prefix_snapshot(APPLICABILITY),
        prefix_snapshot(governance.D_QUEUE),
    ]

    payload: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "frozen_at": now(),
        "window_id": WINDOW_ID,
        "reason_code": "LEGACY_V4_WORKSPACE_PATH_REJECTS_FROZEN_DATASETS_SYMLINK",
        "legacy_failure_evidence": legacy_failure,
        "legacy_d_v4_artifact_state": d_state,
        "recovery_evidence": recovery_summary,
        "frontend_terminal_evidence": frontend_evidence,
        "pre_resume_registry_state": _pre_resume_rows(),
        "applicability_precondition": applicability,
        "expected_d_decision": "NOT_APPLICABLE_REQUIRE_BYTE_IDENTICAL_B1",
        "zero_action_identity": {
            "accepted_learned_born_lineage_count": 0,
            "p_feature_bag": p_evidence["feature_bag"],
            "b1_feature_bag": b1_evidence["feature_bag"],
            "byte_identical_sha256": EXPECTED_ZERO_ACTION_BAG_SHA256,
            "byte_identical_size_bytes": EXPECTED_ZERO_ACTION_BAG_SIZE,
        },
        "datasets_symlink_identity": symlink,
        "datasets_external_file_allowlist": datasets_allowlist,
        "path_policy": {
            "input_must_be_workspace_relative": True,
            "absolute_paths_allowed": False,
            "dotdot_components_allowed": False,
            "only_allowed_symlink_entry": "datasets",
            "only_allowed_symlink_depth": 1,
            "datasets_paths_not_in_exact_allowlist_allowed": False,
            "leaf_symlinks_allowed": False,
            "nested_symlinks_allowed": False,
            "resolved_data_path_must_remain_under_frozen_datasets_target": True,
            "non_dataset_path_must_resolve_under_workspace": True,
        },
        "enhanced_d_v4_contract": {
            "schema_version_remains": "isj-p07-d-resolution-lock-v4",
            "scientific_decision_contract_changed": False,
            "lineage_or_drop_contract_changed": False,
            "allowed_payload_addition": "a04_d_path_correction",
            "required_added_artifacts": [
                display_path(OUTPUT),
                display_path(Path(__file__).resolve()),
                display_path(WRAPPER),
                display_path(TEST_FILE),
            ],
            "canonical_output": display_path(D_V4_LOCK),
            "write_policy": "ATOMIC_NO_CLOBBER",
            "crash_policy": {
                "d_lock_publish": "HARDLINK_NO_REPLACE_FROM_FSYNCED_HIDDEN_TEMP",
                "preexisting_target_or_partial": "FAIL_CLOSED",
                "resolution_publish": "INHERIT_FROZEN_V2_APPEND_AND_CLOSEOUT_PROTOCOL",
                "ambiguous_terminal_row_without_closeout": "FAIL_CLOSED_NO_RERUN",
            },
        },
        "authorized_wrapper_actions": [
            "preflight-d",
            "build-d",
            "resolve-d",
            "resume-preflight",
            "resume-execute",
        ],
        "resume_queue_indices": [58, 59, 60],
        "action_order": ACTION_ORDER,
        "artifacts": artifact_records,
        "mutable_stream_prefix_snapshots": snapshots,
        "outcome_boundary": OUTCOME_BOUNDARY,
        "trajectory_outcome_read": False,
        "vins_execution_allowed": False,
    }
    payload[SELF_HASH_FIELD] = document_hash(payload)
    return payload


def atomic_no_clobber_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path):
        raise FileExistsError(path)
    temporary = path.with_name(f".{path.name}.partial.{os.getpid()}")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        content = (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        ).encode("utf-8")
        with os.fdopen(fd, "wb", closefd=True) as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    payload = build_lock()
    atomic_no_clobber_json(OUTPUT, payload)
    print(
        "P07_A04_D_PATH_CORRECTION_LOCK_V1_PASS "
        f"hash={payload[SELF_HASH_FIELD]} output={display_path(OUTPUT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
