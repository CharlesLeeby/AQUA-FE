#!/usr/bin/env python3
"""Execute one locked P07 A01 B1/P/M export with append-only governance."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_a01_frontend_export_v3 as auditor
    from scripts import run_p07_mp_frontend_export_job_v2 as base
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_a01_frontend_export_v3 as auditor  # type: ignore
    import run_p07_mp_frontend_export_job_v2 as base  # type: ignore


LOCK_PATH = governance.P07 / "a01_frontend_execution_lock_v3.json"
ATTEMPT_ROOT = governance.P07 / "frontend_attempts"
BASE_MIN_OUTPUT_FREE_BYTES = base.BASE_MIN_OUTPUT_FREE_BYTES
MIN_GOVERNANCE_FREE_BYTES = base.MIN_GOVERNANCE_FREE_BYTES
SANITIZED_ENV_KEYS = set(base.SANITIZED_ENV_KEYS) | {
    "AQUAFE_B1_CHECKER",
    "AQUAFE_B1_DECISION_DIR",
    "AQUAFE_P07_TEST_HOOKS",
}


class ExecutionViolation(RuntimeError):
    """Raised when A01 execution cannot satisfy the frozen lock."""


def sha256(path: Path) -> str:
    return base.sha256(path)


def lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def clean_environment() -> dict[str, str]:
    environment = dict(os.environ)
    for key in SANITIZED_ENV_KEYS:
        environment.pop(key, None)
    environment["VINS_WS"] = "/home/ma/SLAM/VINS-Fusion-origin"
    return environment


def load_and_validate_lock(index: int) -> dict[str, object]:
    if not LOCK_PATH.is_file():
        raise ExecutionViolation(f"missing A01 execution lock: {LOCK_PATH}")
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-a01-frontend-execution-lock-v3"
        or payload.get("status") != "FROZEN_READY_FOR_A01_B1_P_M_EXPORT"
        or payload.get("execution_lock_hash") != lock_hash(payload)
    ):
        raise ExecutionViolation("A01 execution lock schema, status, or hash mismatch")
    if index not in payload.get("allowed_queue_indices", []):
        raise ExecutionViolation(f"queue index {index} is not allowed by the A01 lock")
    for record in payload.get("artifacts", []):
        path = governance.ROOT / str(record["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise ExecutionViolation(f"locked A01 artifact drift: {path}")
    for record in payload.get("external_artifacts", []):
        path = Path(str(record["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(record["size_bytes"])
            or sha256(path) != record["sha256"]
        ):
            raise ExecutionViolation(f"locked external artifact drift: {path}")
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    items = [item for item in payload["queue_items"] if int(item["queue_index"]) == index]
    if len(items) != 1:
        raise ExecutionViolation("lock does not contain exactly one queue item")
    item = items[0]
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
        key: {"expected": value, "observed": item.get(key)}
        for key, value in exact.items()
        if item.get(key) != value
    }
    if differences:
        raise ExecutionViolation(f"A01 lock/queue mismatch: {differences}")
    return payload


registry_chain = base.registry_chain
append_registry_event = base.append_registry_event


def target_collisions(row: dict[str, str]) -> list[Path]:
    root = auditor.lexical_absolute(governance.ROOT / row["expected_run_root"])
    if row["arm"] in {governance.B1, governance.M_ARM}:
        run_dir = auditor.lexical_absolute(
            (governance.ROOT / row["expected_feature_bag"]).parent
        )
        return [run_dir] if run_dir.exists() else []
    return sorted(
        auditor.lexical_absolute(path)
        for path in root.glob(f"*{row['tag']}*")
        if path.exists()
    )


def capacity_report(row: dict[str, str], lock: dict[str, object]) -> dict[str, object]:
    return base.capacity_report(row, lock)


def ensure_predecessor_completed(index: int, lock: dict[str, object]) -> None:
    order = [int(value) for value in lock["execution_order"]]
    position = order.index(index)
    for predecessor in order[:position]:
        allocation = auditor.allocation_row(predecessor)
        chain = registry_chain(allocation["run_id"])
        if not chain or chain[-1]["status"] != "COMPLETED":
            raise ExecutionViolation(
                f"queue index {index} is blocked by non-completed predecessor {predecessor}"
            )


def run_guard_preflight(
    row: dict[str, str], attempt_dir: Path, environment: dict[str, str]
) -> tuple[Path, Path]:
    if row["arm"] != governance.B1:
        return base.run_guard_preflight(row, attempt_dir, environment)
    decision = attempt_dir / "b1_guard_preflight_decision.json"
    command = (
        "python3 scripts/check_b1_klt_nativeq_contract_v1.py "
        "--contract papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json "
        "--backend-root /home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master "
        "--binary /home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node "
        "--exporter uw_frontend/ros/export_vins_features.py "
        "--frontend-config uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml "
        f"--decision-json {decision}"
    )
    command_path = attempt_dir / "guard_preflight_command.txt"
    log_path = attempt_dir / "guard_preflight.log"
    command_path.write_text(command + "\n", encoding="utf-8")
    rc, timed_out = base.run_command(
        command,
        log_path,
        timeout_s=180,
        environment=environment,
    )
    if rc != 0:
        raise ExecutionViolation(
            f"B1 guard-only preflight failed rc={rc} timeout={str(timed_out).lower()}"
        )
    auditor.validate_guard(decision, row["arm"])
    return log_path, decision


def run_attestation(
    row: dict[str, str], feature_bag: Path, attempt_dir: Path
) -> tuple[Path, Path]:
    if row["arm"] == governance.M_ARM:
        attestation = Path(str(feature_bag) + ".p05-xfeat-contract.json")
        command = [
            "python3",
            "scripts/attest_p05_xfeat_feature_bag_v1.py",
            "--feature-bag",
            str(feature_bag),
            "--frontend-metrics",
            str(feature_bag.parent / "frontend_metrics.csv"),
            "--contract",
            "papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json",
            "--output",
            str(attestation),
        ]
    else:
        attestation = Path(str(feature_bag) + ".quality-contract.json")
        command = [
            "python3",
            "scripts/attest_nativeq_feature_bag.py",
            "--feature-bag",
            str(feature_bag),
            "--contract",
            "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json",
            "--output",
            str(attestation),
        ]
    log_path = attempt_dir / "attestation.log"
    with log_path.open("wb") as log:
        completed = subprocess.run(
            command,
            cwd=governance.ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=clean_environment(),
            check=False,
        )
    if completed.returncode != 0:
        raise ExecutionViolation(f"arm attestation failed rc={completed.returncode}")
    return attestation, log_path


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
            "scripts/audit_p07_a01_frontend_export_v3.py",
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
        raise ExecutionViolation(f"strict A01 export audit failed rc={completed.returncode}")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ExecutionViolation("strict A01 export audit did not return PASS")
    return audit_path, audit_log, payload


def write_hash_manifest(path: Path, files: list[Path]) -> None:
    base.write_hash_manifest(path, files)


def execute(index: int, *, timeout_s: int) -> dict[str, object]:
    lock = load_and_validate_lock(index)
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    ensure_predecessor_completed(index, lock)
    chain = registry_chain(allocation["run_id"])
    if len(chain) != 1 or chain[-1]["status"] != "PLANNED":
        raise ExecutionViolation("queue item is not an untouched PLANNED allocation")
    collisions = target_collisions(row)
    if collisions:
        raise FileExistsError(f"no-clobber target collision: {collisions}")
    attempt_dir = ATTEMPT_ROOT / f"queue_{index:03d}_{row['tag']}"
    if attempt_dir.exists():
        raise FileExistsError(f"no-clobber attempt collision: {attempt_dir}")
    capacity = capacity_report(row, lock)
    if not capacity["output_pass"] or not capacity["governance_pass"]:
        waiting = governance.P07 / f"queue_{index:03d}_{row['tag']}_capacity_waiting.json"
        if waiting.exists():
            raise FileExistsError(waiting)
        waiting.write_text(
            json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise ExecutionViolation(
            f"storage capacity gate failed without attempt creation: {capacity}"
        )

    attempt_dir.mkdir(parents=True)
    command_path = attempt_dir / "command.txt"
    command_log = attempt_dir / "command.log"
    capacity_path = attempt_dir / "capacity_preflight.json"
    command_path.write_text(row["command"] + "\n", encoding="utf-8")
    capacity_path.write_text(
        json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if hashlib.sha256(row["command"].encode("utf-8")).hexdigest() != row["command_sha256"]:
        raise ExecutionViolation("frozen command hash mismatch")

    input_manifest = attempt_dir / "input_hash_manifest.sha256"
    locked_files = [governance.ROOT / item["path"] for item in lock["artifacts"]]
    raw_path = auditor.expected_raw_bag(row, allocation)
    input_files = [LOCK_PATH, *locked_files]
    if raw_path.is_file():
        input_files.append(raw_path)
    write_hash_manifest(input_manifest, input_files)
    command_rel = auditor.display_path(command_path)
    input_rel = auditor.display_path(input_manifest)
    provisional_run_dir = (
        auditor.display_path((governance.ROOT / row["expected_feature_bag"]).parent)
        if row["expected_feature_bag"]
        else row["expected_run_root"]
    )
    environment = clean_environment()
    running_appended = False
    try:
        guard_preflight_log, guard_preflight_path = run_guard_preflight(
            row, attempt_dir, environment
        )
        append_registry_event(
            allocation["run_id"],
            expected_previous_status="PLANNED",
            status="RUNNING",
            run_dir=provisional_run_dir,
            command_file=command_rel,
            input_hash_manifest=input_rel,
            note=(
                f"A01 v3 no-clobber executor started queue_index={index}; "
                "guard-only preflight exact PASS"
            ),
        )
        running_appended = True
        rc, timed_out = base.run_command(
            row["command"],
            command_log,
            timeout_s=timeout_s,
            environment=environment,
        )
        if rc != 0:
            raise ExecutionViolation(
                f"frontend export command failed rc={rc} timeout={str(timed_out).lower()}"
            )
        actual_guard_path = auditor.parse_guard_path(command_log)
        auditor.validate_guard(actual_guard_path, row["arm"])
        run_dir, feature_bag, probe_run, _summary, _duplicates = auditor.resolve_run_artifacts(row)
        attestation, _attestation_log = run_attestation(row, feature_bag, attempt_dir)
        audit_path, _audit_log, audit = run_audit(
            index, command_log, attestation, attempt_dir
        )

        run_dirs = [run_dir]
        if probe_run is not None and probe_run not in run_dirs:
            run_dirs.append(probe_run)
        output_manifest = attempt_dir / "output_hash_manifest.sha256"
        selected = base.output_files(
            run_dirs,
            attempt_dir,
            [guard_preflight_path, actual_guard_path],
        )
        selected.append(raw_path)
        write_hash_manifest(output_manifest, selected)
        lineage_count: str | None = None
        active: str | None = None
        if row["arm"] == governance.P_ARM:
            lineage_count = str(
                audit["learned_lineages"]["accepted_learned_born_lineage_count"]
            )
            active = str(int(lineage_count) > 0).lower()
        append_registry_event(
            allocation["run_id"],
            expected_previous_status="RUNNING",
            status="COMPLETED",
            run_dir=auditor.display_path(run_dir),
            command_file=command_rel,
            input_hash_manifest=input_rel,
            output_hash_manifest=auditor.display_path(output_manifest),
            infrastructure_failure="false",
            accepted_lineage_count=lineage_count,
            active=active,
            note=(
                f"A01 arm export, exact guard, attestation, and v3 audit PASS; "
                f"audit={auditor.display_path(audit_path)}"
            ),
        )
        return {
            "queue_index": index,
            "run_id": allocation["run_id"],
            "arm": row["arm"],
            "status": "COMPLETED",
            "run_dir": auditor.display_path(run_dir),
            "audit": auditor.display_path(audit_path),
            "output_hash_manifest": auditor.display_path(output_manifest),
            "accepted_learned_born_lineage_count": (
                int(lineage_count) if lineage_count is not None else None
            ),
        }
    except Exception as error:
        latest = registry_chain(allocation["run_id"])[-1]
        if running_appended and latest["status"] == "RUNNING":
            append_registry_event(
                allocation["run_id"],
                expected_previous_status="RUNNING",
                status="FAILED",
                run_dir=provisional_run_dir,
                command_file=command_rel,
                input_hash_manifest=input_rel,
                infrastructure_failure=("true" if "timeout=true" in str(error) else "false"),
                note=f"A01 v3 attempt failed closed: {type(error).__name__}: {error}",
            )
        elif not running_appended and latest["status"] == "PLANNED" and attempt_dir.exists():
            append_registry_event(
                allocation["run_id"],
                expected_previous_status="PLANNED",
                status="RUNNING",
                run_dir=provisional_run_dir,
                command_file=command_rel,
                input_hash_manifest=input_rel,
                note="A01 v3 attempt entered guard-only preflight",
            )
            append_registry_event(
                allocation["run_id"],
                expected_previous_status="RUNNING",
                status="FAILED",
                run_dir=provisional_run_dir,
                command_file=command_rel,
                input_hash_manifest=input_rel,
                infrastructure_failure="false",
                note=f"A01 guard-only preflight failed closed: {type(error).__name__}: {error}",
            )
        raise


def preflight(index: int) -> dict[str, object]:
    lock = load_and_validate_lock(index)
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    order = [int(value) for value in lock["execution_order"]]
    predecessors = []
    for predecessor in order[: order.index(index)]:
        predecessor_allocation = auditor.allocation_row(predecessor)
        predecessors.append(
            {
                "queue_index": predecessor,
                "latest_status": registry_chain(predecessor_allocation["run_id"])[-1]["status"],
            }
        )
    return {
        "queue_index": index,
        "run_id": allocation["run_id"],
        "arm": row["arm"],
        "collisions": [auditor.display_path(path) for path in target_collisions(row)],
        "attempt_collision": (
            ATTEMPT_ROOT / f"queue_{index:03d}_{row['tag']}"
        ).exists(),
        "raw_bag_preexisting": auditor.expected_raw_bag(row, allocation).is_file(),
        "capacity": capacity_report(row, lock),
        "registry_latest_status": registry_chain(allocation["run_id"])[-1]["status"],
        "predecessors": predecessors,
    }


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
            and all(item["latest_status"] == "COMPLETED" for item in report["predecessors"])
        ) else 1
    start = time.monotonic()
    result = execute(args.queue_index, timeout_s=args.timeout_s)
    result["elapsed_s"] = time.monotonic() - start
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
