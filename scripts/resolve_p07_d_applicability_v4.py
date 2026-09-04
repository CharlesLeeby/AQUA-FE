#!/usr/bin/env python3
"""Resolve P07 D with fail-closed support for the queue-55 A04 replacement.

The v4 correction changes only how the P frontend audit is located for the
single AQUALOC A04 layout-recovery case.  D derivation, the append-only
applicability update, and the zero-action byte-identity contract remain the v2
implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts import audit_p07_frontend_export_v3 as frontend_audit
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import resolve_p07_d_applicability_v2 as v2
    from scripts import resolve_p07_d_applicability_v3 as v3
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as frontend_audit  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import resolve_p07_d_applicability_v2 as v2  # type: ignore
    import resolve_p07_d_applicability_v3 as v3  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


ResolutionViolation = v2.ResolutionViolation
APPLICABILITY = v2.APPLICABILITY
RESOLUTION_ROOT = v2.RESOLUTION_ROOT
LOCK_ROOT = v2.LOCK_ROOT
matching_applicability_rows = v2.matching_applicability_rows
output_paths = v2.output_paths
queue_rows = v2.queue_rows
slug = v2.slug

SPECIAL_WINDOW_ID = "aqualoc_archaeology:A04:0002"
SPECIAL_QUEUE_INDEX = 55
CLOSEOUT_SCHEMA = "isj-p07-frontend-layout-replacement-closeout-v1"
RECOVERY_LOCK_SCHEMA = "isj-p07-a04-layout-replacement-lock-v1"
REPLACEMENT_AUDIT_SCHEMA = "isj-p07-frontend-export-audit-v4"
OUTCOME_BOUNDARY = "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
REPLACEMENT_REASON = "AQUALOC_ARCHIVE_ROOT_LAYOUT_MISMATCH"
REPLACEMENT_TAG = "isj_p07_aqualoc_archaeology_a04_0002_p_attempt02"
RECOVERY_LOCK_STATUS = "FROZEN_READY_FOR_Q55_A04_LAYOUT_ATTEMPT02_RECOVERY"
WORKSPACE_ROOT = governance.ROOT
REPLACEMENT_CLOSEOUT = (
    governance.P07
    / "frontend_replacements/queue_055_a04_layout_attempt02_closeout_v1.json"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def document_hash(payload: dict[str, Any], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def resolution_lock_path(window_id: str) -> Path:
    return LOCK_ROOT / f"{slug(window_id)}_v4.json"


def resolution_lock_hash(payload: dict[str, object]) -> str:
    return document_hash(payload, "resolution_lock_hash")


def _json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResolutionViolation(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResolutionViolation(f"{label} is not a JSON object: {path}")
    return payload


def _workspace_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ResolutionViolation(f"{label} path is missing")
    relative = Path(value)
    if relative.is_absolute():
        raise ResolutionViolation(f"{label} path must be workspace-relative")
    root = WORKSPACE_ROOT.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ResolutionViolation(f"{label} path escapes the workspace") from exc
    if not candidate.is_file():
        raise ResolutionViolation(f"missing {label}: {candidate}")
    return candidate


def _canonical_p_audit_path(p_row: dict[str, str]) -> Path:
    """Indirection retained so the replacement fallback can be unit-tested."""

    return v3.p_audit_path(p_row)


def _registry_chain(run_id: str, label: str) -> list[dict[str, str]]:
    try:
        chain = registry.registry_chain(run_id)
    except Exception as exc:
        raise ResolutionViolation(f"invalid {label} registry chain: {exc}") from exc
    if not chain:
        raise ResolutionViolation(f"missing {label} registry chain: {run_id}")
    return chain


def _exact_event(
    reported: object, observed: dict[str, str], label: str
) -> None:
    if not isinstance(reported, dict) or reported != observed:
        raise ResolutionViolation(f"{label} is not the exact canonical registry event")


def _validate_recovery_lock(
    closeout: dict[str, Any],
    *,
    p_row: dict[str, str],
    original_allocation: dict[str, str],
    original_chain: list[dict[str, str]],
    original_run_id: str,
    replacement_run_id: str,
    replacement_tag: str,
    replacement_command: str,
    replacement_command_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    lock_path = _workspace_path(closeout.get("lock_path"), "A04 recovery lock")
    lock = _json_object(lock_path, "A04 recovery lock")
    observed_hash = lock.get("replacement_lock_hash")
    if (
        lock.get("schema_version") != RECOVERY_LOCK_SCHEMA
        or lock.get("status") != RECOVERY_LOCK_STATUS
        or lock.get("original_queue_index") != SPECIAL_QUEUE_INDEX
        or lock.get("original_run_id") != original_run_id
        or lock.get("replacement_run_id") != replacement_run_id
        or lock.get("replacement_tag") != replacement_tag
        or not isinstance(observed_hash, str)
        or observed_hash != document_hash(lock, "replacement_lock_hash")
        or closeout.get("replacement_lock_hash") != observed_hash
    ):
        raise ResolutionViolation("A04 recovery lock schema or self-hash mismatch")
    replacement = lock.get("replacement")
    if (
        not isinstance(replacement, dict)
        or replacement.get("run_id") != replacement_run_id
        or replacement.get("tag") != replacement_tag
        or replacement.get("command") != replacement_command
        or replacement.get("command_sha256") != replacement_command_sha256
    ):
        raise ResolutionViolation("A04 recovery lock replacement identity mismatch")
    original = lock.get("original")
    effective_queue = replacement.get("effective_queue_row")
    effective_allocation = replacement.get("effective_allocation_row")
    if (
        not isinstance(original, dict)
        or original.get("queue_row") != p_row
        or original.get("allocation_row") != original_allocation
        or original.get("registry_failure_chain") != original_chain
    ):
        raise ResolutionViolation("A04 recovery lock original evidence mismatch")
    if not isinstance(effective_queue, dict) or not isinstance(effective_allocation, dict):
        raise ResolutionViolation("A04 recovery effective rows are missing")
    for key, expected in {
        "queue_index": p_row.get("queue_index"),
        "window_id": SPECIAL_WINDOW_ID,
        "dataset_family": p_row.get("dataset_family"),
        "sequence": p_row.get("sequence"),
        "arm": governance.P_ARM,
        "tag": replacement_tag,
        "command": replacement_command,
        "command_sha256": replacement_command_sha256,
    }.items():
        if effective_queue.get(key) != expected:
            raise ResolutionViolation(f"A04 recovery effective queue {key} mismatch")
    for key, expected in {
        "queue_index": original_allocation.get("queue_index"),
        "run_id": replacement_run_id,
        "window_id": SPECIAL_WINDOW_ID,
        "dataset_family": original_allocation.get("dataset_family"),
        "sequence": original_allocation.get("sequence"),
        "arm": governance.P_ARM,
        "tag": replacement_tag,
        "command_sha256": replacement_command_sha256,
    }.items():
        if effective_allocation.get(key) != expected:
            raise ResolutionViolation(f"A04 recovery effective allocation {key} mismatch")
    artifacts = lock.get("artifacts")
    snapshots = lock.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not artifacts:
        raise ResolutionViolation("A04 recovery lock has no artifact records")
    if not isinstance(snapshots, list) or not snapshots:
        raise ResolutionViolation("A04 recovery lock has no stream-prefix snapshots")
    for record in artifacts:
        if not isinstance(record, dict):
            raise ResolutionViolation("invalid A04 recovery artifact record")
        path = _workspace_path(record.get("path"), "A04 recovery artifact")
        try:
            expected_size = int(record.get("size_bytes", -1))
        except (TypeError, ValueError) as exc:
            raise ResolutionViolation("invalid A04 recovery artifact size") from exc
        if expected_size < 0 or path.stat().st_size != expected_size or sha256(path) != record.get("sha256"):
            raise ResolutionViolation(f"A04 recovery locked artifact drift: {path}")
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ResolutionViolation("invalid A04 recovery stream snapshot")
        path = _workspace_path(snapshot.get("path"), "A04 recovery stream")
        try:
            size = int(snapshot.get("size_bytes", -1))
            content = path.read_bytes()
        except (OSError, TypeError, ValueError) as exc:
            raise ResolutionViolation(f"cannot inspect A04 recovery stream: {path}") from exc
        if (
            size < 0
            or len(content) < size
            or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
        ):
            raise ResolutionViolation(f"A04 recovery stream prefix drift: {path}")
    return lock_path, lock


def load_replacement_evidence(
    p_row: dict[str, str],
) -> dict[str, object]:
    """Validate and return the queue-55 replacement evidence bundle.

    This routine intentionally validates live append-only registry chains in
    addition to file hashes.  A copied PASS audit without both terminal chains
    is therefore not accepted as the canonical P evidence.
    """

    if (
        p_row.get("window_id") != SPECIAL_WINDOW_ID
        or int(p_row.get("queue_index", "-1")) != SPECIAL_QUEUE_INDEX
        or p_row.get("arm") != governance.P_ARM
    ):
        raise ResolutionViolation("A04 replacement fallback requested for wrong queue mapping")
    if not REPLACEMENT_CLOSEOUT.is_file():
        raise ResolutionViolation(f"missing A04 replacement closeout: {REPLACEMENT_CLOSEOUT}")
    closeout = _json_object(REPLACEMENT_CLOSEOUT, "A04 replacement closeout")
    if closeout.get("closeout_hash") != document_hash(closeout, "closeout_hash"):
        raise ResolutionViolation("A04 replacement closeout self-hash mismatch")
    try:
        original_allocation = frontend_audit.allocation_row(SPECIAL_QUEUE_INDEX)
    except Exception as exc:
        raise ResolutionViolation(f"cannot load canonical queue-55 allocation: {exc}") from exc
    original_run_id = original_allocation.get("run_id", "")

    replacement_run_id = closeout.get("replacement_run_id")
    replacement_tag = closeout.get("replacement_tag")
    replacement_command = closeout.get("replacement_command")
    replacement_command_sha256 = closeout.get("replacement_command_sha256")
    if (
        closeout.get("schema_version") != CLOSEOUT_SCHEMA
        or closeout.get("status") != "PASS"
        or closeout.get("original_queue_index") != SPECIAL_QUEUE_INDEX
        or closeout.get("original_run_id") != original_run_id
        or not isinstance(replacement_run_id, str)
        or not replacement_run_id
        or replacement_run_id == original_run_id
        or not isinstance(replacement_tag, str)
        or replacement_tag != REPLACEMENT_TAG
        or not isinstance(replacement_command, str)
        or not replacement_command
        or replacement_command_sha256
        != hashlib.sha256(replacement_command.encode("utf-8")).hexdigest()
        or closeout.get("physical_frontend_rerun") is not True
        or closeout.get("trajectory_outcome_read") is not False
        or closeout.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise ResolutionViolation("A04 replacement closeout identity, command, or boundary mismatch")

    replacement_for = closeout.get("replacement_for")
    if not isinstance(replacement_for, dict):
        raise ResolutionViolation("A04 replacement_for mapping is missing")
    if (
        replacement_for.get("original_queue_index") != SPECIAL_QUEUE_INDEX
        or replacement_for.get("original_run_id") != original_run_id
        or replacement_for.get("reason_code") != REPLACEMENT_REASON
    ):
        raise ResolutionViolation("A04 replacement_for mapping mismatch")

    original_chain = _registry_chain(original_run_id, "canonical original")
    original_latest = original_chain[-1]
    if (
        [row.get("status") for row in original_chain]
        != ["PLANNED", "RUNNING", "FAILED"]
        or replacement_for.get("original_failed_registry_event_id")
        != original_latest.get("registry_event_id")
    ):
        raise ResolutionViolation("canonical queue-55 chain does not preserve its terminal FAILED event")
    _exact_event(
        closeout.get("original_final_registry_event"),
        original_latest,
        "original_final_registry_event",
    )

    replacement_chain = _registry_chain(replacement_run_id, "replacement")
    replacement_latest = replacement_chain[-1]
    if (
        [row.get("status") for row in replacement_chain]
        != ["PLANNED", "RUNNING", "COMPLETED"]
        or any(row.get("replacement_for") != original_run_id for row in replacement_chain)
        or closeout.get("effective_slot_status") != "COMPLETED"
    ):
        raise ResolutionViolation("A04 replacement chain is not terminal COMPLETED")
    _exact_event(
        closeout.get("completion_registry_event"),
        replacement_latest,
        "completion_registry_event",
    )
    for key, expected in {
        "dataset_family": original_allocation.get("dataset_family"),
        "sequence": original_allocation.get("sequence"),
        "window_start": original_allocation.get("window_start"),
        "window_end": original_allocation.get("window_end"),
        "arm": governance.P_ARM,
    }.items():
        if replacement_latest.get(key) != expected:
            raise ResolutionViolation(f"replacement registry {key} mismatch")

    lock_path, recovery_lock = _validate_recovery_lock(
        closeout,
        p_row=p_row,
        original_allocation=original_allocation,
        original_chain=original_chain,
        original_run_id=original_run_id,
        replacement_run_id=replacement_run_id,
        replacement_tag=replacement_tag,
        replacement_command=replacement_command,
        replacement_command_sha256=replacement_command_sha256,
    )
    audit_record = closeout.get("replacement_audit")
    if not isinstance(audit_record, dict):
        raise ResolutionViolation("replacement_audit record is missing")
    audit_path = _workspace_path(audit_record.get("path"), "replacement audit")
    if (
        audit_record.get("sha256") != sha256(audit_path)
        or audit_record.get("schema_version") != REPLACEMENT_AUDIT_SCHEMA
        or audit_record.get("status") != "PASS"
    ):
        raise ResolutionViolation("replacement audit record or SHA-256 mismatch")
    audit = _json_object(audit_path, "replacement audit")
    if (
        audit.get("schema_version") != REPLACEMENT_AUDIT_SCHEMA
        or audit.get("status") != "PASS"
        or audit.get("queue_index") != SPECIAL_QUEUE_INDEX
        or audit.get("run_id") != replacement_run_id
        or audit.get("window_id") != SPECIAL_WINDOW_ID
        or audit.get("dataset_family") != p_row.get("dataset_family")
        or audit.get("arm") != governance.P_ARM
        or audit.get("outcome_boundary") != OUTCOME_BOUNDARY
        or audit.get("held_out_trajectory_outcome_read") is not False
        or not isinstance(audit.get("learned_lineages"), dict)
        or not isinstance(audit.get("feature_bag"), dict)
    ):
        raise ResolutionViolation("replacement P audit identity, status, or boundary mismatch")
    if audit.get("command_sha256") != replacement_command_sha256:
        raise ResolutionViolation("replacement audit command hash mismatch")

    return {
        "closeout_path": REPLACEMENT_CLOSEOUT,
        "closeout": closeout,
        "recovery_lock_path": lock_path,
        "recovery_lock": recovery_lock,
        "audit_path": audit_path,
        "audit": audit,
        "original_run_id": original_run_id,
        "replacement_run_id": replacement_run_id,
        "replacement_tag": replacement_tag,
        "replacement_registry_event": replacement_latest,
    }


def latest_registry_rows(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    """Resolve terminal frontend events, substituting only the frozen q55 recovery."""

    result: dict[str, dict[str, str]] = {}
    for row in rows:
        allocation = frontend_audit.allocation_row(int(row["queue_index"]))
        chain = _registry_chain(allocation["run_id"], f"queue {row['queue_index']}")
        if (
            row.get("window_id") == SPECIAL_WINDOW_ID
            and int(row.get("queue_index", "-1")) == SPECIAL_QUEUE_INDEX
            and row.get("arm") == governance.P_ARM
        ):
            try:
                _canonical_p_audit_path(row)
            except ResolutionViolation:
                evidence = load_replacement_evidence(row)
                event = evidence["replacement_registry_event"]
                assert isinstance(event, dict)
                result[row["arm"]] = event
                continue
        if chain[-1].get("status") != "COMPLETED":
            raise ResolutionViolation(
                f"queue index {row['queue_index']} is not terminal COMPLETED"
            )
        result[row["arm"]] = chain[-1]
    return result


def p_audit_path(p_row: dict[str, str]) -> Path:
    try:
        return _canonical_p_audit_path(p_row)
    except ResolutionViolation as canonical_error:
        if p_row.get("window_id") != SPECIAL_WINDOW_ID:
            raise canonical_error
    return Path(load_replacement_evidence(p_row)["audit_path"])


def load_p_audit(window_id: str, p_row: dict[str, str]) -> tuple[Path, dict[str, object]]:
    path = p_audit_path(p_row)
    payload = _json_object(path, "P v4/v3 audit")
    if (
        payload.get("schema_version")
        not in {
            REPLACEMENT_AUDIT_SCHEMA,
            "isj-p07-frontend-export-audit-v3",
            "isj-p07-a01-frontend-export-audit-v3",
        }
        or payload.get("status") != "PASS"
        or payload.get("window_id") != window_id
        or payload.get("arm") != governance.P_ARM
        or not isinstance(payload.get("learned_lineages"), dict)
        or payload.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ResolutionViolation("P v4/v3 audit identity, status, or boundary mismatch")
    if payload.get("dataset_family") == "afrl" and (
        payload.get("schema_version") != REPLACEMENT_AUDIT_SCHEMA
        or payload.get("checks", {}).get("afrl_replay_manifest_metadata_only") is not True
    ):
        raise ResolutionViolation("AFRL P audit lacks the frozen metadata-only v4 check")
    return path, payload


def load_resolution_lock(window_id: str) -> dict[str, object]:
    path = resolution_lock_path(window_id)
    if not path.is_file():
        raise ResolutionViolation(f"missing D v4 resolution lock: {path}")
    payload = _json_object(path, "D v4 resolution lock")
    if (
        payload.get("schema_version") != "isj-p07-d-resolution-lock-v4"
        or payload.get("status") != "FROZEN_READY_TO_RESOLVE_D"
        or payload.get("window_id") != window_id
        or payload.get("resolution_lock_hash") != resolution_lock_hash(payload)
    ):
        raise ResolutionViolation("D v4 lock schema, identity, status, or hash mismatch")
    artifacts = payload.get("artifacts")
    snapshots = payload.get("mutable_stream_prefix_snapshots")
    if not isinstance(artifacts, list) or not isinstance(snapshots, list):
        raise ResolutionViolation("D v4 lock artifact or stream list is invalid")
    for record in artifacts:
        if not isinstance(record, dict):
            raise ResolutionViolation("invalid D v4 artifact record")
        artifact = governance.ROOT / str(record.get("path", ""))
        if (
            not artifact.is_file()
            or artifact.stat().st_size != int(record.get("size_bytes", -1))
            or sha256(artifact) != record.get("sha256")
        ):
            raise ResolutionViolation(f"locked D v4 artifact drift: {artifact}")
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            raise ResolutionViolation("invalid append-only D v4 stream snapshot")
        stream = governance.ROOT / str(snapshot.get("path", ""))
        try:
            content = stream.read_bytes()
            size = int(snapshot.get("size_bytes", -1))
        except (OSError, ValueError) as exc:
            raise ResolutionViolation(f"cannot inspect D v4 stream: {stream}: {exc}") from exc
        if (
            size < 0
            or len(content) < size
            or hashlib.sha256(content[:size]).hexdigest() != snapshot.get("sha256")
        ):
            raise ResolutionViolation(f"append-only D v4 stream prefix drift: {stream}")
    compatibility = payload.get("layout_replacement_compatibility")
    audit_correction = payload.get("audit_compatibility_correction")
    parent_contracts = payload.get("parent_resolution_contracts")
    if (
        not isinstance(compatibility, dict)
        or not isinstance(audit_correction, dict)
        or not isinstance(parent_contracts, dict)
        or audit_correction.get("lineage_or_drop_contract_changed") is not False
        or audit_correction.get("trajectory_outcome_read") is not False
    ):
        raise ResolutionViolation("D v4 compatibility or parent-contract metadata is invalid")
    if window_id == SPECIAL_WINDOW_ID:
        p_row = next(
            row for row in queue_rows(window_id) if row["arm"] == governance.P_ARM
        )
        evidence = load_replacement_evidence(p_row)
        parent_p = payload.get("parent_p")
        if (
            not isinstance(parent_p, dict)
            or compatibility.get("applied") is not True
            or compatibility.get("original_queue_index") != SPECIAL_QUEUE_INDEX
            or compatibility.get("original_run_id") != evidence["original_run_id"]
            or compatibility.get("replacement_run_id") != evidence["replacement_run_id"]
            or compatibility.get("replacement_tag") != evidence["replacement_tag"]
            or compatibility.get("physical_frontend_rerun") is not True
            or compatibility.get("lineage_or_drop_contract_changed") is not False
            or compatibility.get("trajectory_outcome_read") is not False
            or parent_p.get("run_id") != evidence["replacement_run_id"]
        ):
            raise ResolutionViolation("D v4 A04 replacement compatibility mismatch")
        required_paths = {
            frontend_audit.display_path(Path(evidence["closeout_path"])),
            frontend_audit.display_path(Path(evidence["audit_path"])),
            frontend_audit.display_path(Path(evidence["recovery_lock_path"])),
            "scripts/resolve_p07_d_applicability_v2.py",
            "scripts/build_p07_d_resolution_lock_v2.py",
            "scripts/resolve_p07_d_applicability_v3.py",
            "scripts/build_p07_d_resolution_lock_v3.py",
            "scripts/tests/test_p07_d_resolution_v3.py",
            "scripts/resolve_p07_d_applicability_v4.py",
            "scripts/build_p07_d_resolution_lock_v4.py",
            "scripts/tests/test_p07_d_resolution_v4.py",
        }
        locked_paths = {str(record.get("path", "")) for record in artifacts}
        missing = sorted(required_paths - locked_paths)
        if missing:
            raise ResolutionViolation(f"D v4 lock omits replacement/parent artifacts: {missing}")
    elif compatibility.get("applied") is not False:
        raise ResolutionViolation("non-A04 D v4 lock claims replacement compatibility")
    return payload


def install_v4_contract() -> None:
    v3.install_v3_contract()
    v2.p_audit_path = p_audit_path
    v2.load_p_audit = load_p_audit
    v2.resolution_lock_path = resolution_lock_path
    v2.resolution_lock_hash = resolution_lock_hash
    v2.load_resolution_lock = load_resolution_lock
    v2.latest_registry_rows = latest_registry_rows


def append_resolution(window_id: str) -> dict[str, object]:
    install_v4_contract()
    return v2.append_resolution(window_id)


def preflight(window_id: str) -> dict[str, object]:
    rows = queue_rows(window_id)
    latest = latest_registry_rows(rows)
    statuses = {arm: row["status"] for arm, row in latest.items()}
    p_row = next(row for row in rows if row["arm"] == governance.P_ARM)
    count = None
    if statuses[governance.P_ARM] == "COMPLETED":
        audit_path = p_audit_path(p_row)
        payload = _json_object(audit_path, "P v4/v3 audit")
        count = int(payload["learned_lineages"]["accepted_learned_born_lineage_count"])
    resolution_path = output_paths(window_id, count or 0)[0] if count is not None else None
    return {
        "window_id": window_id,
        "frontend_statuses": statuses,
        "accepted_learned_born_lineage_count": count,
        "resolution_output": (
            frontend_audit.display_path(resolution_path) if resolution_path else None
        ),
        "resolution_collision": bool(resolution_path and resolution_path.exists()),
        "resolution_lock": frontend_audit.display_path(resolution_lock_path(window_id)),
        "resolution_lock_exists": resolution_lock_path(window_id).is_file(),
        "effective_p_run_id": latest[governance.P_ARM]["run_id"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        print(json.dumps(preflight(args.window_id), indent=2, sort_keys=True))
        return 0
    result = append_resolution(args.window_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
