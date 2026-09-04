#!/usr/bin/env python3
"""Execute one queue-index-4+ P07 frontend export under the generalized lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

try:
    from scripts import audit_p07_frontend_export_v3 as auditor
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import run_p07_mp_frontend_export_job_v2 as base
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import audit_p07_frontend_export_v3 as auditor  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base  # type: ignore


LOCK_PATH = governance.P07 / "frontend_execution_lock_v3.json"
ExecutionViolation = base.ExecutionViolation
sha256 = base.sha256
lock_hash = base.lock_hash
registry_chain = base.registry_chain
target_collisions = base.target_collisions
ATTEMPT_ROOT = base.ATTEMPT_ROOT
MIN_GOVERNANCE_FREE_BYTES = base.MIN_GOVERNANCE_FREE_BYTES
BASE_MIN_OUTPUT_FREE_BYTES = base.BASE_MIN_OUTPUT_FREE_BYTES

EXTRA_SANITIZED_ENV_KEYS = {
    "AQUAFE_B1_CHECKER",
    "AQUAFE_B1_DECISION_DIR",
    "AQUAFE_DRY_RUN",
    "AQUAFE_P07_TEST_HOOKS",
}


def clean_environment() -> dict[str, str]:
    environment = base.clean_environment()
    for key in EXTRA_SANITIZED_ENV_KEYS:
        environment.pop(key, None)
    environment["VINS_WS"] = "/home/ma/SLAM/VINS-Fusion-origin"
    return environment


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load_and_validate_lock(index: int) -> dict[str, object]:
    if not LOCK_PATH.is_file():
        raise ExecutionViolation(f"missing generalized execution lock: {LOCK_PATH}")
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-frontend-execution-lock-v3"
        or payload.get("status") != "FROZEN_READY_FOR_QUEUE_INDEX_4_PLUS"
        or payload.get("execution_lock_hash") != lock_hash(payload)
    ):
        raise ExecutionViolation("generalized execution lock schema, status, or hash mismatch")
    if index not in payload.get("allowed_queue_indices", []):
        raise ExecutionViolation(f"queue index {index} is outside the generalized lock")

    for record in payload.get("artifacts", []):
        path = governance.ROOT / str(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise ExecutionViolation(f"locked artifact drift: {path}")
    for record in payload.get("external_artifacts", []):
        path = Path(str(record["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise ExecutionViolation(f"locked external artifact drift: {path}")
    for snapshot in payload.get("mutable_stream_prefix_snapshots", []):
        path = governance.ROOT / str(snapshot["path"])
        content = path.read_bytes()
        size = int(snapshot["size_bytes"])
        if len(content) < size or _sha256_bytes(content[:size]) != snapshot["sha256"]:
            raise ExecutionViolation(f"append-only stream prefix drift: {path}")

    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    items = [item for item in payload["queue_items"] if int(item["queue_index"]) == index]
    if len(items) != 1:
        raise ExecutionViolation("lock does not contain exactly one queue item")
    exact = {
        "run_id": allocation["run_id"],
        "arm": row["arm"],
        "window_id": row["window_id"],
        "tag": row["tag"],
        "command": row["command"],
        "command_sha256": row["command_sha256"],
        "expected_run_root": row["expected_run_root"],
        "expected_feature_bag": row["expected_feature_bag"],
        "feature_bag_resolution": row["feature_bag_resolution"],
    }
    differences = {
        key: {"expected": value, "observed": items[0].get(key)}
        for key, value in exact.items()
        if items[0].get(key) != value
    }
    if differences:
        raise ExecutionViolation(f"lock/queue/allocation mismatch: {differences}")

    for predecessor in payload["dependencies"]["required_completed_queue_indices"]:
        predecessor_allocation = auditor.allocation_row(int(predecessor))
        chain = registry_chain(predecessor_allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ExecutionViolation(
                f"generalized queue blocked by predecessor {predecessor}"
            )
    return payload


def capacity_report(row: dict[str, str], lock: dict[str, object]) -> dict[str, object]:
    output_root = auditor.lexical_absolute(governance.ROOT / row["expected_run_root"])
    if not output_root.is_dir():
        raise ExecutionViolation(f"missing frozen output root: {output_root}")
    current_index = int(row["queue_index"])
    current_window = str(row["window_id"])
    remaining_items = [
        item
        for item in lock["queue_items"]
        if int(item["queue_index"]) >= current_index
        and str(item["window_id"]) == current_window
        and registry_chain(str(item["run_id"]))[-1]["status"] == "PLANNED"
    ]
    remaining_run_bytes = sum(int(item["estimated_output_bytes"]) for item in remaining_items)
    remaining_d_bytes = int(
        lock["capacity_gate"]["d_upper_bound_bytes_by_window"].get(current_window, 0)
    )
    reserve = int(lock["capacity_gate"]["separate_reserve_bytes"])
    margin = float(lock["capacity_gate"]["margin_multiplier"])
    estimated = math.ceil((remaining_run_bytes + remaining_d_bytes) * margin + reserve)
    minimum_output = max(BASE_MIN_OUTPUT_FREE_BYTES, estimated)
    output = shutil.disk_usage(output_root)
    governance_usage = shutil.disk_usage(governance.P07)
    return {
        "output_root": auditor.display_path(output_root),
        "output_free_bytes": output.free,
        "batch_window_id": current_window,
        "remaining_batch_job_count": len(remaining_items),
        "remaining_batch_run_bytes": remaining_run_bytes,
        "batch_d_upper_bound_bytes": remaining_d_bytes,
        "output_minimum_free_bytes": minimum_output,
        "output_pass": output.free >= minimum_output,
        "governance_free_bytes": governance_usage.free,
        "governance_minimum_free_bytes": MIN_GOVERNANCE_FREE_BYTES,
        "governance_pass": governance_usage.free >= MIN_GOVERNANCE_FREE_BYTES,
    }


def run_guard_preflight(
    row: dict[str, str], attempt_dir: Path, environment: dict[str, str]
) -> tuple[Path, Path]:
    if row["arm"] == governance.B1:
        prefix = "AQUAFE_DRY_RUN=1"
    elif row["arm"] == governance.M_ARM:
        prefix = "AQUAFE_P05_GUARD_ONLY=1"
    else:
        prefix = "AQUAFE_GUARD_ONLY=1"
    command = f"{prefix} {row['command']}"
    command_path = attempt_dir / "guard_preflight_command.txt"
    log_path = attempt_dir / "guard_preflight.log"
    command_path.write_text(command + "\n", encoding="utf-8")
    rc, timed_out = base.run_command(
        command, log_path, timeout_s=180, environment=environment
    )
    if rc != 0:
        raise ExecutionViolation(
            f"guard-only preflight failed rc={rc} timeout={str(timed_out).lower()}"
        )
    guard_path = auditor.parse_guard_path(log_path)
    auditor.validate_guard(guard_path, row["arm"])
    return log_path, guard_path


def run_audit(
    index: int,
    command_log: Path,
    attestation: Path,
    attempt_dir: Path,
) -> tuple[Path, Path, dict[str, object]]:
    audit_path = attempt_dir / "audit_v3.json"
    audit_log = attempt_dir / "audit_v3.log"
    completed = subprocess.run(
        [
            "python3",
            "scripts/audit_p07_frontend_export_v3.py",
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
        raise ExecutionViolation(f"strict generalized export audit failed rc={completed.returncode}")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ExecutionViolation("strict generalized export audit did not return PASS")
    return audit_path, audit_log, payload


_append_registry_event_v2 = base.append_registry_event


def append_registry_event(*args, **kwargs):
    note = str(kwargs.get("note", ""))
    kwargs["note"] = note.replace("M/P v2", "generalized v3").replace(
        "strict v2", "strict v3"
    )
    return _append_registry_event_v2(*args, **kwargs)


def install_generalized_contract() -> None:
    base.auditor = auditor
    base.LOCK_PATH = LOCK_PATH
    base.clean_environment = clean_environment
    base.load_and_validate_lock = load_and_validate_lock
    base.capacity_report = capacity_report
    base.run_guard_preflight = run_guard_preflight
    base.run_audit = run_audit
    base.append_registry_event = append_registry_event


def preflight(index: int) -> dict[str, object]:
    install_generalized_contract()
    return base.preflight(index)


def execute(index: int, *, timeout_s: int) -> dict[str, object]:
    install_generalized_contract()
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
