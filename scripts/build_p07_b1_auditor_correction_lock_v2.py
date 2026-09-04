#!/usr/bin/env python3
"""Freeze the symlink-only B1 auditor correction before re-auditing attempt01."""

from __future__ import annotations

import hashlib
import json
import os

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts.audit_p07_b1_frontend_export_v1 import allocation_row, queue_row
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    from audit_p07_b1_frontend_export_v1 import allocation_row, queue_row  # type: ignore


OUTPUT = governance.P07 / "b1_auditor_correction_lock_v2.json"
ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01"
)


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("correction_lock_hash", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_lock() -> dict[str, object]:
    queue = queue_row(1)
    allocation = allocation_row(1)
    audit_log = ATTEMPT / "audit.log"
    failure = audit_log.read_text(encoding="utf-8", errors="replace")
    required = (
        "ValueError: '/mnt/data/AQUA-FE_WS/logs/backend_contract_decisions/"
        "b1/b1_guard_"
    )
    if required not in failure or "does not start with '/home/ma/AQUA-FE_WS'" not in failure:
        raise ValueError("attempt01 failure is not the frozen workspace-symlink display bug")
    feature_bag = governance.ROOT / queue["expected_feature_bag"]
    attestation = governance.ROOT / (queue["expected_feature_bag"] + ".quality-contract.json")
    payload: dict[str, object] = {
        "schema_version": "isj-p07-b1-auditor-correction-lock-v2",
        "status": "FROZEN_POST_ATTEMPT_PRE_REAUDIT",
        "run_id": allocation["run_id"],
        "queue_index": 1,
        "failed_registry_event": f"{allocation['run_id']}_e02",
        "failure_class": "AUDITOR_PATH_DISPLAY_IMPLEMENTATION",
        "scientific_output_change": "NONE_REAUDIT_PRESERVED_BYTES_ONLY",
        "correction_scope": (
            "Do not resolve the workspace logs symlink before rendering a "
            "workspace-relative guard path; retain every v1 data/contract check."
        ),
        "artifacts": [
            governance.file_record(path)
            for path in (
                governance.P07 / "b1_smoke_execution_lock_v1.json",
                governance.ROOT / "scripts/audit_p07_b1_frontend_export_v1.py",
                governance.ROOT / "scripts/audit_p07_b1_frontend_export_v2.py",
                ATTEMPT / "command.txt",
                ATTEMPT / "command.log",
                ATTEMPT / "attestation.log",
                ATTEMPT / "audit.log",
                feature_bag,
                feature_bag.parent / "frontend_metrics.csv",
                attestation,
            )
        ],
        "required_reaudit": {
            "auditor": "scripts/audit_p07_b1_frontend_export_v2.py",
            "output": (
                "papers/ieee_sensors_journal_experiments/p07/frontend_attempts/"
                "queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01/audit_v2.json"
            ),
            "no_frontend_rerun": True,
            "on_pass_registry_transition": "append_e03_COMPLETED_correction",
        },
        "held_out_frontend_outcome_read": True,
        "held_out_trajectory_outcome_read": False,
        "outcome_boundary": "REAUDIT_EXISTING_FRONTEND_BYTES_NO_VINS_APE_RPE_TRAJECTORY",
    }
    payload["correction_lock_hash"] = lock_hash(payload)
    return payload


def main() -> int:
    payload = build_lock()
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)
    print(
        "P07_B1_AUDITOR_CORRECTION_LOCK_V2_PASS "
        f"hash={payload['correction_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
