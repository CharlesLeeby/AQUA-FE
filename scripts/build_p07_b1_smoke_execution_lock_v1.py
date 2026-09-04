#!/usr/bin/env python3
"""Freeze the no-clobber queue-index-1 B1 smoke execution contract."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts.audit_p07_b1_frontend_export_v1 import allocation_row, queue_row
    from scripts.run_p07_frontend_export_job_v1 import (
        MIN_GOVERNANCE_FREE_BYTES,
        MIN_OUTPUT_FREE_BYTES,
        capacity_report,
        read_registry,
        target_collisions,
    )
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    from audit_p07_b1_frontend_export_v1 import allocation_row, queue_row  # type: ignore
    from run_p07_frontend_export_job_v1 import (  # type: ignore
        MIN_GOVERNANCE_FREE_BYTES,
        MIN_OUTPUT_FREE_BYTES,
        capacity_report,
        read_registry,
        target_collisions,
    )


OUTPUT = governance.P07 / "b1_smoke_execution_lock_v1.json"


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_lock() -> dict[str, object]:
    queue = queue_row(1)
    allocation = allocation_row(1)
    _fields, registry = read_registry()
    chain = [row for row in registry if row["run_id"] == allocation["run_id"]]
    if len(chain) != 1 or chain[0]["status"] != "PLANNED":
        raise ValueError("queue-index-1 registry chain is not exactly one PLANNED event")
    collisions = target_collisions(queue)
    capacity = capacity_report(queue)
    if collisions:
        raise FileExistsError(f"queue-index-1 target collision: {collisions}")
    if not capacity["output_pass"] or not capacity["governance_pass"]:
        raise RuntimeError(f"queue-index-1 capacity gate failed: {capacity}")

    payload: dict[str, object] = {
        "schema_version": "isj-p07-b1-smoke-execution-lock-v1",
        "status": "FROZEN_READY_FOR_SINGLE_B1_SMOKE",
        "protocol_version": "isj-nativeq-v3-confirmatory-protocol-v1",
        "method_lock_hash": json.loads(
            governance.METHOD_LOCK.read_text(encoding="utf-8")
        )["method_lock_hash"],
        "queue_lock_hash": json.loads(
            governance.QUEUE_LOCK.read_text(encoding="utf-8")
        )["queue_lock_hash"],
        "allowed_queue_indices": [1],
        "allowed_arms": [governance.B1],
        "queue_item": {
            "queue_index": 1,
            "run_id": allocation["run_id"],
            "window_id": queue["window_id"],
            "command": queue["command"],
            "command_sha256": queue["command_sha256"],
            "tag": queue["tag"],
            "expected_feature_bag": queue["expected_feature_bag"],
            "expected_feature_frames": 450,
            "expected_raw_images": 901,
        },
        "no_clobber": {
            "target_collision_count": 0,
            "attempt_directory_must_not_exist": True,
            "replacement_requires_new_run_id_and_attempt_tag": True,
        },
        "capacity_gate": {
            "minimum_output_free_bytes": MIN_OUTPUT_FREE_BYTES,
            "minimum_governance_free_bytes": MIN_GOVERNANCE_FREE_BYTES,
            "observed": capacity,
            "recompute_immediately_before_execution": True,
        },
        "required_terminal_evidence": [
            "exact B1 guard ALLOW_B1_KLT_NATIVEQ",
            "readable derived raw bag with 901 images and copied IMU/reference",
            "readable feature bag with 450 feature frames",
            "13-channel classical-only native-q schema and 350 cap",
            "frontend metrics count equality",
            "native-q bag attestation",
            "absence of VINS/APE/RPE/trajectory artifacts",
            "exact command, logs, input/output hashes, and registry e01/e02 chain",
        ],
        "artifacts": [
            governance.file_record(path)
            for path in (
                governance.EXPORT_QUEUE,
                governance.QUEUE_LOCK,
                governance.ALLOCATION_CSV,
                governance.ANALYSIS_LOCK,
                governance.BUNDLE / "run_registry.csv",
                governance.BUNDLE / "arm_applicability.csv",
                governance.ROOT / "scripts/run_p07_frontend_export_job_v1.py",
                governance.ROOT / "scripts/audit_p07_b1_frontend_export_v1.py",
                governance.ROOT / "scripts/attest_nativeq_feature_bag.py",
                governance.ROOT / "scripts/run_isj_b1_klt_nativeq_guarded_v1.sh",
                governance.ROOT / "scripts/check_b1_klt_nativeq_contract_v1.py",
                governance.ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
                governance.ROOT / "uw_frontend/ros/export_vins_features.py",
                governance.ROOT
                / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml",
                governance.ROOT / "scripts/build_p07_b1_smoke_execution_lock_v1.py",
            )
        ],
        "outcome_boundary": "B1_SMOKE_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "held_out_frontend_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
        "next_action": "EXECUTE_QUEUE_INDEX_1_ONCE",
    }
    payload["execution_lock_hash"] = lock_hash(payload)
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
        "P07_B1_SMOKE_EXECUTION_LOCK_PASS "
        f"hash={payload['execution_lock_hash']} queue_index=1"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
