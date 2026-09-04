#!/usr/bin/env python3
"""Freeze v5 execution after the queue-28 AFRL auditor correction."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_export_job_v4 as v4
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_export_job_v4 as v4  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


OUTPUT = governance.P07 / "frontend_execution_correction_lock_v5.json"
V4_LOCK = governance.P07 / "frontend_execution_correction_lock_v4.json"
AFRL_LOCK = governance.P07 / "afrl_replay_manifest_auditor_correction_lock_v4.json"
ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_028_isj_p07_afrl_bus_outside_0001_b1_attempt01"
)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": auditor.display_path(path),
        "sha256": sha256(path),
        "size_bytes": path.stat().st_size,
    }


def prefix_snapshot(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": auditor.display_path(path),
        "sha256": hashlib.sha256(content).hexdigest(),
        "size_bytes": len(content),
    }


def correction_lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("correction_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    parent = json.loads(V4_LOCK.read_text(encoding="utf-8"))
    closeout_path = ATTEMPT / "audit_correction_closeout_v4.json"
    closeout = json.loads(closeout_path.read_text(encoding="utf-8"))
    allocation = auditor.allocation_row(28)
    chain = registry.registry_chain(allocation["run_id"])
    if [row["status"] for row in chain] != [
        "PLANNED",
        "RUNNING",
        "FAILED",
        "COMPLETED",
    ]:
        raise ValueError("queue 28 correction chain is not terminal COMPLETED")
    if (
        closeout.get("status") != "PASS_COMPLETED_WITH_PRESERVED_AUDITOR_FAILURE"
        or closeout.get("physical_frontend_rerun") is not False
    ):
        raise ValueError("queue 28 correction closeout is not an exact PASS")
    for index in range(29, 61):
        allocation = auditor.allocation_row(index)
        state = registry.registry_chain(allocation["run_id"])
        if len(state) != 1 or state[-1]["status"] != "PLANNED":
            raise ValueError(f"queue {index} is not untouched PLANNED")
        row = auditor.queue_row(index)
        if registry.target_collisions(row):
            raise FileExistsError(f"queue {index} target collision")
        attempt = governance.P07 / "frontend_attempts" / f"queue_{index:03d}_{row['tag']}"
        if attempt.exists():
            raise FileExistsError(attempt)
    artifacts = [
        V4_LOCK,
        AFRL_LOCK,
        ATTEMPT / "audit_v4.json",
        ATTEMPT / "audit_correction_closeout_v4.json",
        ATTEMPT / "output_hash_manifest_v4.sha256",
        governance.ROOT / "scripts/audit_p07_frontend_export_v3.py",
        governance.ROOT / "scripts/audit_p07_frontend_export_v4.py",
        governance.ROOT / "scripts/run_p07_frontend_export_job_v4.py",
        governance.ROOT / "scripts/run_p07_frontend_export_job_v5.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v4.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v5.py",
        governance.ROOT / "scripts/build_p07_frontend_execution_correction_lock_v5.py",
        governance.ROOT / "scripts/tests/test_p07_frontend_execution_correction_v5.py",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-frontend-execution-correction-lock-v5",
        "status": "FROZEN_READY_AFTER_AFRL_MANIFEST_AUDITOR_CORRECTION",
        "frozen_at": now(),
        "allowed_queue_indices": list(range(29, 61)),
        "superseded_v4_lock": {
            "path": auditor.display_path(V4_LOCK),
            "file_sha256": sha256(V4_LOCK),
            "correction_lock_hash": parent["correction_lock_hash"],
            "disposition": "PRESERVED_EXECUTION_ADAPTER_AUDITOR_UPDATED_ONLY",
        },
        "queue_28_correction": {
            "registry_chain": [row["status"] for row in chain],
            "closeout": auditor.display_path(closeout_path),
            "physical_frontend_rerun": False,
        },
        "correction": {
            "auditor": "scripts/audit_p07_frontend_export_v4.py",
            "afrl_replay_manifest_policy": "EXACT_METADATA_ONLY_WITH_ABSENT_VINS_OUTPUT",
            "scientific_command_changed": False,
            "queue_identity_changed": False,
            "frontend_or_trajectory_outcome_read": False,
        },
        "artifacts": [file_record(path) for path in artifacts],
        "mutable_stream_prefix_snapshots": [
            prefix_snapshot(governance.BUNDLE / "run_registry.csv"),
            prefix_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "next_action": "RESUME_QUEUE_INDEX_29_THROUGH_60_SERIAL",
    }
    payload["correction_lock_hash"] = correction_lock_hash(payload)
    return payload


def main() -> int:
    payload = build_lock()
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)
    print(
        "P07_FRONTEND_EXECUTION_CORRECTION_V5_PASS "
        f"hash={payload['correction_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
