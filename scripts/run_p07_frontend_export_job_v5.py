#!/usr/bin/env python3
"""Run P07 exports with the AFRL replay-manifest auditor correction."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_frontend_export_job_v3 as v3
    from scripts import run_p07_frontend_export_job_v4 as v4
    from scripts import run_p07_mp_frontend_export_job_v2 as base
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_frontend_export_job_v3 as v3  # type: ignore
    import run_p07_frontend_export_job_v4 as v4  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base  # type: ignore


LOCK_PATH = governance.P07 / "frontend_execution_correction_lock_v5.json"
clean_environment = v4.clean_environment


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def correction_lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("correction_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_and_validate_lock(index: int) -> dict[str, object]:
    if not LOCK_PATH.is_file():
        raise base.ExecutionViolation(f"missing v5 correction lock: {LOCK_PATH}")
    correction = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        correction.get("schema_version")
        != "isj-p07-frontend-execution-correction-lock-v5"
        or correction.get("status")
        != "FROZEN_READY_AFTER_AFRL_MANIFEST_AUDITOR_CORRECTION"
        or correction.get("correction_lock_hash")
        != correction_lock_hash(correction)
    ):
        raise base.ExecutionViolation("v5 correction lock schema, status, or hash mismatch")
    if index not in correction.get("allowed_queue_indices", []):
        raise base.ExecutionViolation(f"queue index {index} is outside the v5 lock")
    for record in correction.get("artifacts", []):
        path = governance.ROOT / str(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise base.ExecutionViolation(f"v5 locked artifact drift: {path}")
    original = v4.load_and_validate_lock(index)
    expected_hash = correction["superseded_v4_lock"]["correction_lock_hash"]
    parent = json.loads(v4.LOCK_PATH.read_text(encoding="utf-8"))
    if parent.get("correction_lock_hash") != expected_hash:
        raise base.ExecutionViolation("v4 parent correction-lock hash mismatch")
    merged = dict(original)
    by_path = {
        str(record["path"]): record
        for record in [*original["artifacts"], *correction["artifacts"]]
    }
    merged["artifacts"] = list(by_path.values())
    return merged


def run_audit(
    index: int,
    command_log: Path,
    attestation: Path,
    attempt_dir: Path,
) -> tuple[Path, Path, dict[str, object]]:
    audit_path = attempt_dir / "audit_v4.json"
    audit_log = attempt_dir / "audit_v4.log"
    completed = subprocess.run(
        [
            "python3",
            "scripts/audit_p07_frontend_export_v4.py",
            "--queue-index",
            str(index),
            "--command-log",
            str(command_log),
            "--attestation",
            str(attestation),
            "--output",
            str(audit_path),
        ],
        cwd=governance.ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=clean_environment(),
        check=False,
    )
    audit_log.write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0 or not audit_path.is_file():
        raise base.ExecutionViolation(f"strict v4 export audit failed rc={completed.returncode}")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise base.ExecutionViolation("strict v4 export audit did not return PASS")
    return audit_path, audit_log, payload


def install_corrected_contract() -> None:
    base.auditor = auditor
    base.LOCK_PATH = LOCK_PATH
    base.clean_environment = clean_environment
    base.load_and_validate_lock = load_and_validate_lock
    base.capacity_report = v3.capacity_report
    base.run_guard_preflight = v3.run_guard_preflight
    base.run_audit = run_audit
    base.append_registry_event = v3.append_registry_event


def preflight(index: int) -> dict[str, object]:
    install_corrected_contract()
    lock = load_and_validate_lock(index)
    base.ensure_predecessor_completed(index, lock)
    return base.preflight(index)


def execute(index: int, *, timeout_s: int) -> dict[str, object]:
    install_corrected_contract()
    return base.execute(index, timeout_s=timeout_s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--timeout-s", type=int, default=7200)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.preflight_only:
        report = preflight(args.queue_index)
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0 if (
            not report["collisions"]
            and not report["attempt_collision"]
            and report["capacity"]["output_pass"]
            and report["capacity"]["governance_pass"]
            and report["registry_latest_status"] == "PLANNED"
        ) else 1
    start = time.monotonic()
    result = execute(args.queue_index, timeout_s=args.timeout_s)
    result["elapsed_s"] = time.monotonic() - start
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
