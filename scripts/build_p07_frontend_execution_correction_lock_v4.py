#!/usr/bin/env python3
"""Freeze the pre-start v3 environment-adapter correction for queue indices 7..60."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_export_job_v4 as runner
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_export_job_v4 as runner  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


OUTPUT = governance.P07 / "frontend_execution_correction_lock_v4.json"
V3_LOCK = governance.P07 / "frontend_execution_lock_v3.json"
FAILURE = (
    governance.P07
    / "frontend_prestart_failures"
    / "queue_007_isj_p07_aqualoc_harbor_h05_0002_p_attempt01_v3_adapter_recursion"
    / "preexecution_failure.json"
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
    v3_lock = json.loads(V3_LOCK.read_text(encoding="utf-8"))
    if v3_lock.get("schema_version") != "isj-p07-frontend-execution-lock-v3":
        raise ValueError("invalid v3 parent lock")
    failure = json.loads(FAILURE.read_text(encoding="utf-8"))
    if failure.get("status") != "BLOCKED_PRESTART_NO_RUN_EVENT":
        raise ValueError("pre-start failure closeout is not terminal")
    allocation = auditor.allocation_row(7)
    chain = registry.registry_chain(allocation["run_id"])
    if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
        raise ValueError("queue 7 canonical allocation is no longer untouched PLANNED")
    row = auditor.queue_row(7)
    if registry.target_collisions(row):
        raise FileExistsError("queue 7 target collision after pre-start closeout")
    canonical_attempt = (
        governance.P07 / "frontend_attempts" / f"queue_007_{row['tag']}"
    )
    if canonical_attempt.exists():
        raise FileExistsError(canonical_attempt)

    artifacts = [
        V3_LOCK,
        FAILURE,
        governance.ROOT / "scripts/run_p07_frontend_export_job_v3.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v3.py",
        governance.ROOT / "scripts/run_p07_frontend_export_job_v4.py",
        governance.ROOT / "scripts/run_p07_frontend_queue_v4.py",
        governance.ROOT / "scripts/build_p07_frontend_execution_correction_lock_v4.py",
        governance.ROOT / "scripts/tests/test_p07_frontend_execution_correction_v4.py",
        governance.BUNDLE / "data_eligibility_manifest.csv",
        governance.ROOT / "scripts/run_learned_seedchain_eval.sh",
        governance.ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
        governance.ROOT / "scripts/run_aqualoc_real_vins_eval.sh",
        governance.ROOT / "scripts/run_ntnu_vins_eval.sh",
        governance.ROOT / "scripts/run_afrl_cave_vins_eval.sh",
        governance.ROOT / "uw_frontend/datasets/aqualoc_raw_to_rosbag.py",
        governance.ROOT / "uw_frontend/datasets/afrl_cave_to_rosbag.py",
        governance.ROOT / "uw_frontend/datasets/image_sequence.py",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-frontend-execution-correction-lock-v4",
        "status": "FROZEN_READY_AFTER_PRESTART_ADAPTER_CORRECTION",
        "frozen_at": now(),
        "allowed_queue_indices": list(range(7, 61)),
        "superseded_v3_lock": {
            "path": auditor.display_path(V3_LOCK),
            "file_sha256": sha256(V3_LOCK),
            "execution_lock_hash": v3_lock["execution_lock_hash"],
            "disposition": "PRESERVED_SCIENTIFIC_CONTRACT_IMPLEMENTATION_ADAPTER_CORRECTED",
        },
        "failure": {
            "path": auditor.display_path(FAILURE),
            "class": "PRESTART_EXECUTOR_ENVIRONMENT_ADAPTER_RECURSION",
            "registry_state": "PLANNED_UNCHANGED",
            "physical_frontend_started": False,
            "target_outputs_created": False,
        },
        "correction": {
            "old_call": "base.clean_environment_after_monkey_patch",
            "new_call": "captured_unpatched_base_clean_environment",
            "scientific_command_changed": False,
            "queue_identity_changed": False,
            "frontend_or_trajectory_outcome_read": False,
            "transitive_runner_files_directly_hash_bound": True,
        },
        "artifacts": [file_record(path) for path in artifacts],
        "outcome_boundary": "FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY",
        "next_action": "RETRY_UNSTARTED_QUEUE_INDEX_7_UNDER_V4_ADAPTER",
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
        "P07_FRONTEND_EXECUTION_CORRECTION_V4_PASS "
        f"hash={payload['correction_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
