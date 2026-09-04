#!/usr/bin/env python3
"""Freeze the AFRL replay-manifest auditor correction before read-only re-audit."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_mp_frontend_export_job_v2 as registry
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as registry  # type: ignore


OUTPUT = governance.P07 / "afrl_replay_manifest_auditor_correction_lock_v4.json"
ATTEMPT = (
    governance.P07
    / "frontend_attempts/queue_028_isj_p07_afrl_bus_outside_0001_b1_attempt01"
)


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
    clone.pop("correction_lock_hash", None)
    return hashlib.sha256(
        json.dumps(clone, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_lock() -> dict[str, object]:
    if OUTPUT.exists():
        raise FileExistsError(OUTPUT)
    allocation = auditor.allocation_row(28)
    chain = registry.registry_chain(allocation["run_id"])
    if [row["status"] for row in chain] != ["PLANNED", "RUNNING", "FAILED"]:
        raise ValueError("queue 28 is not the preserved auditor-failure chain")
    failure = (ATTEMPT / "audit_v3.log").read_text(
        encoding="utf-8", errors="replace"
    )
    if "trajectory outcome artifact found" not in failure or "replay_manifest.txt" not in failure:
        raise ValueError("queue 28 failure is not the AFRL replay-manifest classification bug")
    queue = auditor.queue_row(28)
    run_dir, _feature_bag, _probe, _summary, _duplicates = auditor.resolve_run_artifacts(
        queue
    )
    if not run_dir.is_dir() or any((run_dir / "vins_output").rglob("*")):
        raise ValueError("AFRL preserved run lacks an empty VINS output directory")
    artifacts = [
        governance.P07 / "frontend_execution_correction_lock_v4.json",
        governance.ROOT / "scripts/audit_p07_frontend_export_v3.py",
        governance.ROOT / "scripts/audit_p07_frontend_export_v4.py",
        governance.ROOT / "scripts/build_p07_afrl_auditor_correction_lock_v4.py",
        governance.ROOT / "scripts/closeout_p07_afrl_auditor_correction_v4.py",
        governance.ROOT / "scripts/tests/test_p07_afrl_auditor_correction_v4.py",
        ATTEMPT / "command.txt",
        ATTEMPT / "command.log",
        ATTEMPT / "input_hash_manifest.sha256",
        ATTEMPT / "capacity_preflight.json",
        ATTEMPT / "attestation.log",
        ATTEMPT / "audit_v3.log",
        run_dir / "cave_gennie_short.bag",
        run_dir / "features.bag",
        run_dir / "features.bag.quality-contract.json",
        run_dir / "frontend_metrics.csv",
        run_dir / "replay_manifest.txt",
        run_dir / "afrl_cave_cam0_pinhole.yaml",
        run_dir / "vins_afrl_cave_external.yaml",
    ]
    payload: dict[str, object] = {
        "schema_version": "isj-p07-afrl-replay-manifest-auditor-correction-lock-v4",
        "status": "FROZEN_POST_ATTEMPT_PRE_REAUDIT",
        "queue_index": 28,
        "run_id": allocation["run_id"],
        "failed_registry_event": chain[-1]["registry_event_id"],
        "failure_class": "AUDITOR_STATIC_REPLAY_MANIFEST_NAME_CLASSIFICATION",
        "scientific_output_change": "NONE_REAUDIT_PRESERVED_BYTES_ONLY",
        "correction_scope": (
            "For frozen AFRL RUN_VINS=0 exports only, accept replay_manifest.txt as "
            "configuration metadata after exact key/path checks and proof that vio.csv, "
            "VINS logs, and all files under vins_output are absent."
        ),
        "artifacts": [file_record(path) for path in artifacts],
        "mutable_stream_prefix_snapshots": [
            prefix_snapshot(governance.BUNDLE / "run_registry.csv")
        ],
        "required_reaudit": {
            "auditor": "scripts/audit_p07_frontend_export_v4.py",
            "output": auditor.display_path(ATTEMPT / "audit_v4.json"),
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
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)
    print(
        "P07_AFRL_AUDITOR_CORRECTION_LOCK_V4_PASS "
        f"hash={payload['correction_lock_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
