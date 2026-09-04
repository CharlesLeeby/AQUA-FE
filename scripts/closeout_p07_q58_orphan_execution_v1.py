#!/usr/bin/env python3
"""Finish only the frozen post-child steps for orphaned P07 queue 58.

This adapter never invokes the frontend command.  It requires the additive
post-command lock, reuses the v5-installed M attester and v4 auditor, hashes the
preserved outputs, and appends the canonical RUNNING e01 -> COMPLETED e02 event.
Any partial post-processing artifact fails closed and is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import build_p07_q58_orphan_closeout_lock_v1 as contract
    from scripts import run_p07_frontend_export_job_v5 as v5
    from scripts import run_p07_mp_frontend_export_job_v2 as base
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import build_p07_q58_orphan_closeout_lock_v1 as contract  # type: ignore
    import run_p07_frontend_export_job_v5 as v5  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base  # type: ignore


SCHEMA = "isj-p07-q58-orphan-execution-closeout-v1"
STATUS = "PASS_COMPLETED_FROM_PRESERVED_ORPHANED_EXECUTION"


class OrphanExecutionCloseoutViolation(RuntimeError):
    """Fail-closed violation of the frozen queue-58 closeout."""


def _path(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else governance.ROOT / path


def validate_prefix_snapshot(snapshot: dict[str, Any]) -> None:
    path = _path(str(snapshot["path"]))
    content = path.read_bytes()
    size = int(snapshot["size_bytes"])
    if (
        len(content) < size
        or hashlib.sha256(content[:size]).hexdigest() != snapshot["sha256"]
    ):
        raise OrphanExecutionCloseoutViolation(
            f"q58 mutable stream prefix drift: {path}"
        )


def assert_closeout_outputs_absent() -> None:
    collisions = [path for path in contract.postprocess_paths() if path.exists()]
    partials: list[Path] = []
    for path in contract.postprocess_paths():
        if path.parent.is_dir():
            partials.extend(path.parent.glob(f"{path.name}.partial.*"))
    if collisions or partials:
        raise FileExistsError(
            "q58 orphan closeout refuses partial/no-clobber state: "
            f"complete={sorted(map(str, collisions))} partial={sorted(map(str, partials))}"
        )


def validate_preserved_artifacts(payload: dict[str, Any]) -> None:
    """Re-hash every byte frozen before attestation/audit."""

    for record in payload.get("artifacts", []):
        path = _path(str(record["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or contract.sha256(path) != record["sha256"]
        ):
            raise OrphanExecutionCloseoutViolation(
                f"q58 orphan closeout locked artifact drift: {path}"
            )
    raw_record = payload.get("preserved_run", {}).get("ephemeral_raw_cache", {})
    if (
        raw_record.get("path") != auditor.display_path(contract.RAW_BAG)
        or not contract.RAW_BAG.is_file()
        or contract.RAW_BAG.stat().st_size != int(raw_record.get("size_bytes", -1))
        or contract.sha256(contract.RAW_BAG) != raw_record.get("sha256")
    ):
        raise OrphanExecutionCloseoutViolation(
            "q58 raw materialization differs from the post-command lock"
        )


def load_and_validate_lock() -> tuple[dict[str, Any], dict[str, str], dict[str, str]]:
    if not contract.OUTPUT.is_file():
        raise OrphanExecutionCloseoutViolation(
            f"missing q58 orphan closeout lock: {contract.OUTPUT}"
        )
    payload = json.loads(contract.OUTPUT.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != contract.SCHEMA
        or payload.get("status") != contract.STATUS
        or payload.get("queue_index") != contract.QUEUE_INDEX
        or payload.get("closeout_lock_hash") != contract.document_hash(payload)
        or payload.get("physical_frontend_rerun") is not False
        or payload.get("trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != contract.OUTCOME_BOUNDARY
    ):
        raise OrphanExecutionCloseoutViolation(
            "q58 orphan closeout lock schema, status, hash, or boundary mismatch"
        )
    validate_preserved_artifacts(payload)
    for snapshot in payload.get("mutable_stream_prefix_snapshots", []):
        validate_prefix_snapshot(snapshot)

    active = contract.active_q58_processes()
    if active:
        raise OrphanExecutionCloseoutViolation(
            f"q58 physical process became active during closeout: {active}"
        )
    row = auditor.queue_row(contract.QUEUE_INDEX)
    allocation = auditor.allocation_row(contract.QUEUE_INDEX)
    if (
        payload.get("run_id") != allocation["run_id"]
        or payload.get("arm") != row["arm"]
        or payload.get("command_sha256") != row["command_sha256"]
    ):
        raise OrphanExecutionCloseoutViolation("q58 lock/queue/allocation identity mismatch")
    chain = base.registry_chain(allocation["run_id"])
    _e00, e01 = contract.validate_registry_chain(chain, allocation["run_id"])
    locked_e01 = payload.get("canonical_registry_state", {}).get("e01")
    if e01 != locked_e01:
        raise OrphanExecutionCloseoutViolation("q58 canonical e01 differs from frozen lock")
    contract.completion_markers(row)
    contract.validate_preserved_run(row)
    contract.parse_hash_manifest(contract.ATTEMPT / "input_hash_manifest.sha256")
    contract.validate_q55_binding_documents()
    return payload, row, allocation


def revalidate_after_postprocess(
    lock: dict[str, Any], row: dict[str, str], allocation: dict[str, str]
) -> None:
    """Close the attestation/audit TOCTOU window before e02 publication."""

    active = contract.active_q58_processes()
    if active:
        raise OrphanExecutionCloseoutViolation(
            f"q58 process active after postprocess: {active}"
        )
    validate_preserved_artifacts(lock)
    for snapshot in lock.get("mutable_stream_prefix_snapshots", []):
        validate_prefix_snapshot(snapshot)
    chain = base.registry_chain(allocation["run_id"])
    _e00, e01 = contract.validate_registry_chain(chain, allocation["run_id"])
    if e01 != lock.get("canonical_registry_state", {}).get("e01"):
        raise OrphanExecutionCloseoutViolation(
            "q58 e01 changed during attestation/audit postprocess"
        )
    contract.completion_markers(row)
    contract.validate_preserved_run(row)


def validate_audit(
    audit: dict[str, Any], *, allocation: dict[str, str], attestation: Path
) -> None:
    expected = {
        "schema_version": "isj-p07-frontend-export-audit-v4",
        "status": "PASS",
        "queue_index": contract.QUEUE_INDEX,
        "run_id": allocation["run_id"],
        "arm": governance.M_ARM,
        "run_dir": auditor.display_path(contract.RUN_DIR),
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
        "held_out_trajectory_outcome_read": False,
    }
    differences = {
        key: {"expected": value, "observed": audit.get(key)}
        for key, value in expected.items()
        if audit.get(key) != value
    }
    if differences:
        raise OrphanExecutionCloseoutViolation(
            f"q58 strict v4 audit identity mismatch: {differences}"
        )
    if (
        audit.get("checks", {}).get("no_trajectory_outcome_artifacts") is not True
        or audit.get("checks", {}).get("arm_attestation_bound") is not True
        or audit.get("feature_bag", {}).get("path")
        != auditor.display_path(contract.FEATURE_BAG)
        or audit.get("attestation", {}).get("path") != auditor.display_path(attestation)
        or audit.get("forbidden_outcome_artifacts") != []
    ):
        raise OrphanExecutionCloseoutViolation(
            "q58 strict v4 audit lacks exact attestation/no-trajectory evidence"
        )


def run_locked_postprocess(
    row: dict[str, str], allocation: dict[str, str]
) -> tuple[Path, Path, dict[str, Any], Path, Path]:
    """Run only v5's attestation and v4 audit steps on preserved bytes."""

    v5.install_corrected_contract()
    run_dir, feature_bag, probe_run, _summary, _duplicates = auditor.resolve_run_artifacts(
        row
    )
    if (
        run_dir != auditor.lexical_absolute(contract.RUN_DIR)
        or feature_bag != auditor.lexical_absolute(contract.FEATURE_BAG)
        or probe_run is not None
    ):
        raise OrphanExecutionCloseoutViolation(
            "q58 M artifact adapter resolved an unexpected run"
        )
    actual_guard = auditor.parse_guard_path(contract.ATTEMPT / "command.log")
    preflight_guard = auditor.parse_guard_path(contract.ATTEMPT / "guard_preflight.log")
    auditor.validate_guard(actual_guard, governance.M_ARM)
    auditor.validate_guard(preflight_guard, governance.M_ARM)
    attestation, _attestation_log = base.run_attestation(
        row, feature_bag, contract.ATTEMPT
    )
    audit_path, _audit_log, audit = base.run_audit(
        contract.QUEUE_INDEX,
        contract.ATTEMPT / "command.log",
        attestation,
        contract.ATTEMPT,
    )
    validate_audit(audit, allocation=allocation, attestation=attestation)
    return run_dir, attestation, audit, actual_guard, preflight_guard


def publish_output_manifest_no_clobber(files: Iterable[Path]) -> Path:
    output = contract.OUTPUT_MANIFEST
    if output.exists() or list(output.parent.glob(f"{output.name}.partial.*")):
        raise FileExistsError(output)
    temporary = output.with_name(f"{output.name}.partial.{os.getpid()}")
    try:
        base.write_hash_manifest(temporary, list(files))
        os.link(temporary, output)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return output


def append_completion_event(
    *,
    allocation: dict[str, str],
    run_dir: Path,
    output_manifest: Path,
    audit_path: Path,
) -> dict[str, str]:
    event = base.append_registry_event(
        allocation["run_id"],
        expected_previous_status="RUNNING",
        status="COMPLETED",
        run_dir=auditor.display_path(run_dir),
        command_file=auditor.display_path(contract.ATTEMPT / "command.txt"),
        input_hash_manifest=auditor.display_path(
            contract.ATTEMPT / "input_hash_manifest.sha256"
        ),
        output_hash_manifest=auditor.display_path(output_manifest),
        infrastructure_failure="false",
        note=(
            "q58 orphan closeout: preserved physical M export reached exact RUN_VINS=0 "
            "terminal markers; v5 M attestation and strict v4 audit PASS; outer executor "
            "was lost before post-child steps; no frontend rerun; "
            f"audit={auditor.display_path(audit_path)}; "
            f"lock={auditor.display_path(contract.OUTPUT)}"
        ),
    )
    expected_event = f"{allocation['run_id']}_e02"
    if (
        event.get("registry_event_id") != expected_event
        or event.get("supersedes_event_id") != f"{allocation['run_id']}_e01"
        or event.get("status") != "COMPLETED"
        or event.get("infrastructure_failure") != "false"
        or event.get("run_dir") != auditor.display_path(run_dir)
        or event.get("output_hash_manifest")
        != auditor.display_path(output_manifest)
    ):
        raise OrphanExecutionCloseoutViolation(
            f"q58 completion event is not exact canonical e02: {event}"
        )
    return event


def build_closeout_report(
    *,
    lock: dict[str, Any],
    allocation: dict[str, str],
    event: dict[str, str],
    audit: dict[str, Any],
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "schema_version": SCHEMA,
        "status": STATUS,
        "queue_index": contract.QUEUE_INDEX,
        "run_id": allocation["run_id"],
        "superseded_registry_event": f"{allocation['run_id']}_e01",
        "completion_registry_event": event,
        "completion_registry_event_id": event["registry_event_id"],
        "orphan_closeout_lock": contract.file_record(contract.OUTPUT),
        "orphan_closeout_lock_hash": lock["closeout_lock_hash"],
        "audit": contract.file_record(contract.AUDIT),
        "output_hash_manifest": contract.file_record(contract.OUTPUT_MANIFEST),
        "feature_bag_sha256": audit["feature_bag"]["sha256"],
        "feature_frames": audit["feature_bag"]["feature_frames"],
        "feature_observations": audit["feature_bag"]["feature_observations"],
        "physical_frontend_rerun": False,
        "fabricated_failed_registry_event": False,
        "supervisor_loss_recovered": True,
        "physical_command_returncode_directly_observed": False,
        "terminal_completion_markers_exact": True,
        "held_out_frontend_outcome_read_after_lock_only": True,
        "trajectory_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": contract.OUTCOME_BOUNDARY,
    }
    report["closeout_hash"] = contract.document_hash(report, "closeout_hash")
    return report


def perform_locked_closeout() -> dict[str, Any]:
    """Perform the transaction while the shared correction action lock is held."""

    assert_closeout_outputs_absent()
    lock, row, allocation = load_and_validate_lock()
    run_dir, _attestation, audit, actual_guard, preflight_guard = run_locked_postprocess(
        row, allocation
    )
    revalidate_after_postprocess(lock, row, allocation)
    output_files = base.output_files(
        [run_dir], contract.ATTEMPT, [preflight_guard, actual_guard]
    )
    output_manifest = publish_output_manifest_no_clobber(
        [*output_files, contract.OUTPUT]
    )
    event = append_completion_event(
        allocation=allocation,
        run_dir=run_dir,
        output_manifest=output_manifest,
        audit_path=contract.AUDIT,
    )
    report = build_closeout_report(
        lock=lock, allocation=allocation, event=event, audit=audit
    )
    contract.atomic_write_json_no_clobber(contract.CLOSEOUT, report)
    return report


def main() -> int:
    # Serialize with q55 replacement correction and its frozen queue 56..60
    # resume actions.  The lock spans the entire validation/postprocess/e02
    # transaction, not only registry publication.
    with contract.correction_runtime.action_lock():
        report = perform_locked_closeout()
    print(
        "P07_Q58_ORPHAN_EXECUTION_CLOSEOUT_V1_PASS "
        f"event={report['completion_registry_event_id']} "
        f"frames={report['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
