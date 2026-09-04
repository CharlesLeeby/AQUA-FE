#!/usr/bin/env python3
"""Close queue 28 after the frozen AFRL read-only v4 audit passes."""

from __future__ import annotations

import json
import os

from scripts import audit_p07_frontend_export_v3 as auditor
from scripts import build_p07_afrl_auditor_correction_lock_v4 as correction
from scripts import build_p07_preoutcome_governance_v1 as governance
from scripts import run_p07_mp_frontend_export_job_v2 as registry


ATTEMPT = correction.ATTEMPT
LOCK = correction.OUTPUT
AUDIT = ATTEMPT / "audit_v4.json"
OUTPUT_MANIFEST = ATTEMPT / "output_hash_manifest_v4.sha256"
REPORT = ATTEMPT / "audit_correction_closeout_v4.json"


def validate_precloseout() -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
    row = auditor.queue_row(28)
    allocation = auditor.allocation_row(28)
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    if lock.get("correction_lock_hash") != correction.lock_hash(lock):
        raise ValueError("AFRL auditor correction lock hash mismatch")
    for record in lock["artifacts"]:
        path = governance.ROOT / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or correction.sha256(path) != record["sha256"]
        ):
            raise ValueError(f"AFRL correction locked artifact drift: {path}")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if (
        audit.get("schema_version") != "isj-p07-frontend-export-audit-v4"
        or audit.get("status") != "PASS"
        or audit.get("queue_index") != 28
        or audit.get("run_id") != allocation["run_id"]
        or audit.get("checks", {}).get("afrl_replay_manifest_metadata_only") is not True
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ValueError("AFRL v4 audit is not an exact queue-28 PASS")
    chain = registry.registry_chain(allocation["run_id"])
    if [item["status"] for item in chain] != ["PLANNED", "RUNNING", "FAILED"]:
        raise ValueError("unexpected queue-28 precloseout registry chain")
    return row, allocation, audit


def main() -> int:
    if OUTPUT_MANIFEST.exists() or REPORT.exists():
        raise FileExistsError("refusing to overwrite AFRL correction closeout artifacts")
    row, allocation, audit = validate_precloseout()
    run_dir = governance.ROOT / audit["run_dir"]
    files = [path for path in run_dir.rglob("*") if path.is_file()]
    files.extend(path for path in ATTEMPT.iterdir() if path.is_file())
    files.extend([LOCK, AUDIT])
    registry.write_hash_manifest(OUTPUT_MANIFEST, files)
    event = registry.append_registry_event(
        allocation["run_id"],
        expected_previous_status="FAILED",
        status="COMPLETED",
        run_dir=auditor.display_path(run_dir),
        command_file=auditor.display_path(ATTEMPT / "command.txt"),
        input_hash_manifest=auditor.display_path(ATTEMPT / "input_hash_manifest.sha256"),
        output_hash_manifest=auditor.display_path(OUTPUT_MANIFEST),
        infrastructure_failure="false",
        note=(
            "e03 evidence correction: preserved AFRL export passed v4 read-only audit; "
            "e02 retained as replay-manifest filename auditor failure; no frontend rerun"
        ),
    )
    report = {
        "schema_version": "isj-p07-afrl-auditor-correction-closeout-v4",
        "status": "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE",
        "queue_index": 28,
        "run_id": allocation["run_id"],
        "superseded_registry_event": f"{allocation['run_id']}_e02",
        "completion_registry_event": event["registry_event_id"],
        "physical_frontend_rerun": False,
        "audit": governance.file_record(AUDIT),
        "correction_lock": governance.file_record(LOCK),
        "output_hash_manifest": governance.file_record(OUTPUT_MANIFEST),
        "feature_bag_sha256": audit["feature_bag"]["sha256"],
        "feature_frames": audit["feature_bag"]["feature_frames"],
        "feature_observations": audit["feature_bag"]["feature_observations"],
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
    }
    temporary = REPORT.with_name(f"{REPORT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, REPORT)
    print(
        "P07_AFRL_AUDITOR_CORRECTION_CLOSEOUT_PASS "
        f"event={event['registry_event_id']} frames={report['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
