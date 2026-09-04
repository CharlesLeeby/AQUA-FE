#!/usr/bin/env python3
"""Close queue-index-1 after the frozen v2 read-only audit correction passes."""

from __future__ import annotations

import json
import os
from pathlib import Path

from scripts import build_p07_preoutcome_governance_v1 as governance
from scripts.audit_p07_b1_frontend_export_v1 import allocation_row, queue_row
from scripts.build_p07_b1_auditor_correction_lock_v2 import lock_hash
from scripts.run_p07_frontend_export_job_v1 import (
    append_registry_event,
    parse_guard_path,
    read_registry,
    write_hash_manifest,
)


ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01"
)
CORRECTION_LOCK = governance.P07 / "b1_auditor_correction_lock_v2.json"
AUDIT = ATTEMPT / "audit_v2.json"
OUTPUT_MANIFEST = ATTEMPT / "output_hash_manifest.sha256"
REPORT = ATTEMPT / "audit_correction_closeout_v2.json"


def validate_precloseout() -> tuple[dict[str, str], dict[str, str], dict[str, object]]:
    queue = queue_row(1)
    allocation = allocation_row(1)
    lock = json.loads(CORRECTION_LOCK.read_text(encoding="utf-8"))
    if lock.get("correction_lock_hash") != lock_hash(lock):
        raise ValueError("auditor correction lock hash mismatch")
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    if (
        audit.get("schema_version") != "isj-p07-b1-frontend-export-audit-v2"
        or audit.get("status") != "PASS"
        or audit.get("queue_index") != 1
        or audit.get("run_id") != allocation["run_id"]
        or audit.get("held_out_trajectory_outcome_read") is not False
    ):
        raise ValueError("v2 B1 audit is not an exact PASS for queue index 1")
    _fields, registry = read_registry()
    chain = [row for row in registry if row["run_id"] == allocation["run_id"]]
    if [row["status"] for row in chain] != ["PLANNED", "RUNNING", "FAILED"]:
        raise ValueError(f"unexpected precloseout registry chain: {[row['status'] for row in chain]}")
    if "attestation or B1 export audit failed" not in chain[-1]["notes"]:
        raise ValueError("e02 is not the preserved v1 auditor failure")
    return queue, allocation, audit


def main() -> int:
    if OUTPUT_MANIFEST.exists() or REPORT.exists():
        raise FileExistsError("refusing to overwrite B1 correction closeout artifacts")
    queue, allocation, audit = validate_precloseout()
    feature_bag = governance.ROOT / queue["expected_feature_bag"]
    run_dir = feature_bag.parent
    raw_bag = governance.ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_5400.bag"
    guard = parse_guard_path(ATTEMPT / "command.log")
    files = [
        raw_bag,
        run_dir / "features.bag",
        run_dir / "frontend_metrics.csv",
        run_dir / "aqualoc_archaeo02_pinhole.yaml",
        run_dir / "features.bag.quality-contract.json",
        guard,
        ATTEMPT / "command.txt",
        ATTEMPT / "command.log",
        ATTEMPT / "input_hash_manifest.sha256",
        ATTEMPT / "capacity_preflight.json",
        ATTEMPT / "attestation.log",
        ATTEMPT / "audit.log",
        AUDIT,
        CORRECTION_LOCK,
    ]
    write_hash_manifest(OUTPUT_MANIFEST, files)
    output_rel = OUTPUT_MANIFEST.relative_to(governance.ROOT).as_posix()
    run_rel = run_dir.relative_to(governance.ROOT).as_posix()
    event = append_registry_event(
        allocation["run_id"],
        event_number=3,
        status="COMPLETED",
        run_dir=run_rel,
        command_file=(ATTEMPT / "command.txt").relative_to(governance.ROOT).as_posix(),
        output_hash_manifest=output_rel,
        infrastructure_failure="false",
        note=(
            "e03 evidence correction: preserved export passed v2 read-only audit; "
            "e02 retained as v1 workspace-symlink display-path auditor failure; no rerun"
        ),
    )
    report = {
        "schema_version": "isj-p07-b1-smoke-audit-correction-closeout-v2",
        "status": "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE",
        "queue_index": 1,
        "run_id": allocation["run_id"],
        "superseded_registry_event": f"{allocation['run_id']}_e02",
        "completion_registry_event": event["registry_event_id"],
        "physical_frontend_rerun": False,
        "audit": governance.file_record(AUDIT),
        "correction_lock": governance.file_record(CORRECTION_LOCK),
        "output_hash_manifest": governance.file_record(OUTPUT_MANIFEST),
        "feature_bag_sha256": audit["feature_bag"]["sha256"],
        "feature_frames": audit["feature_bag"]["feature_frames"],
        "feature_observations": audit["feature_bag"]["feature_observations"],
        "learned_observations": 0,
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
        "P07_B1_SMOKE_CORRECTION_CLOSEOUT_PASS "
        f"event={event['registry_event_id']} frames={report['feature_frames']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
