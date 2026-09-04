#!/usr/bin/env python3
"""Freeze the v6 queue orchestration compatibility contract."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_queue_v4 as v4_queue
    from scripts import run_p07_frontend_queue_v6 as queue
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_queue_v4 as v4_queue  # type: ignore
    import run_p07_frontend_queue_v6 as queue  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


OUTPUT = queue.LOCK_PATH
V5_LOCK = governance.P07 / "frontend_execution_correction_lock_v5.json"
BUS_D_LOCK = governance.P07 / "d_resolution_locks/afrl_bus_outside_0001_v3.json"
BUS_D_RESULT = governance.P07 / "d_resolutions/afrl_bus_outside_0001_not_applicable_v2.json"


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


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("orchestration_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    if not v4_queue.window_is_terminal_complete("afrl:bus_outside:0001"):
        raise ValueError("AFRL bus_outside D is not terminal with evidence")
    for index in range(31, 61):
        allocation = auditor.allocation_row(index)
        chain = registry.registry_chain(allocation["run_id"])
        if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
            raise ValueError(f"queue {index} is not untouched PLANNED")
        row = auditor.queue_row(index)
        if registry.target_collisions(row):
            raise FileExistsError(f"queue {index} target collision")
        attempt = governance.P07 / "frontend_attempts" / f"queue_{index:03d}_{row['tag']}"
        if attempt.exists():
            raise FileExistsError(attempt)
    artifacts = [
        V5_LOCK,
        BUS_D_LOCK,
        BUS_D_RESULT,
        governance.ROOT / "scripts/run_p07_frontend_export_job_v5.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v6.py",
        governance.ROOT / "scripts/resolve_p07_d_applicability_v3.py",
        governance.ROOT / "scripts/build_p07_d_resolution_lock_v3.py",
        governance.ROOT / "scripts/build_p07_frontend_orchestration_correction_lock_v6.py",
        governance.ROOT / "scripts/tests/test_p07_frontend_orchestration_v6.py",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-frontend-orchestration-correction-lock-v6",
        "status": "FROZEN_READY_WITH_V4_AUDIT_AND_V3_D_RESOLUTION",
        "frozen_at": now(),
        "allowed_queue_indices": list(range(31, 61)),
        "frontend_executor": "scripts/run_p07_frontend_export_job_v5.py",
        "d_lock_builder": "scripts/build_p07_d_resolution_lock_v3.py",
        "d_resolver": "scripts/resolve_p07_d_applicability_v3.py",
        "correction": {
            "accepted_p_audit_schema_added": "isj-p07-frontend-export-audit-v4",
            "frontend_scientific_command_changed": False,
            "lineage_or_exact_drop_contract_changed": False,
            "trajectory_outcome_read": False,
        },
        "artifacts": [file_record(path) for path in artifacts],
        "mutable_stream_prefix_snapshots": [
            prefix_snapshot(governance.BUNDLE / "run_registry.csv"),
            prefix_snapshot(governance.BUNDLE / "arm_applicability.csv"),
        ],
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "next_action": "RESUME_QUEUE_INDEX_31_THROUGH_60_SERIAL",
    }
    payload["orchestration_lock_hash"] = lock_hash(payload)
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
        "P07_FRONTEND_ORCHESTRATION_CORRECTION_V6_PASS "
        f"hash={payload['orchestration_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
