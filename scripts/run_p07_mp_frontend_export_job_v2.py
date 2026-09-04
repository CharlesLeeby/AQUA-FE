#!/usr/bin/env python3
"""Execute one locked P07 A02 M/P export with append-only governance."""

from __future__ import annotations

import argparse
import csv
import fcntl
import hashlib
import io
import json
import os
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as governance
    from scripts import audit_p07_mp_frontend_export_v2 as auditor
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    import audit_p07_mp_frontend_export_v2 as auditor  # type: ignore


RUN_REGISTRY = governance.BUNDLE / "run_registry.csv"
ATTEMPT_ROOT = governance.P07 / "frontend_attempts"
LOCK_PATH = governance.P07 / "mp_smoke_execution_lock_v2.json"
MIN_GOVERNANCE_FREE_BYTES = 512 * 1024**2
BASE_MIN_OUTPUT_FREE_BYTES = 3 * 1024**3
SANITIZED_ENV_KEYS = {
    "AQUAFE_BACKEND_QUALITY_CONTRACT",
    "AQUAFE_CONTRACT_CHECKER",
    "AQUAFE_DECISION_DIR",
    "AQUAFE_FALLBACK_RUNNER",
    "AQUAFE_GUARD_ONLY",
    "AQUAFE_P05_BACKEND_CONTRACT",
    "AQUAFE_P05_CONTRACT_CHECKER",
    "AQUAFE_P05_DECISION_DIR",
    "AQUAFE_P05_FALLBACK_RUNNER",
    "AQUAFE_P05_GUARD_ONLY",
    "AQUAFE_P05_ON_MISMATCH",
    "AQUAFE_P05_RUNNER",
    "AQUAFE_P05_TEST_HOOKS",
    "AQUAFE_PROPOSED_RUNNER",
    "EXPORT_FEATURES",
    "FEATURE_BAG",
    "FEATURE_BAG_OVERRIDE",
    "FORCE_EXPORT",
    "FORCE_RAW",
    "MODE",
    "P05_QUALITY_CONTRACT_ATTESTATION",
    "QUALITY_CONTRACT_ATTESTATION",
    "RAW_BAG",
    "ROOT",
    "RUN_DIR",
    "RUN_VINS",
    "TAG",
    "TAG_BASE",
}


class ExecutionViolation(RuntimeError):
    """Raised when execution cannot satisfy the frozen lock."""


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise ExecutionViolation(f"missing M/P execution lock: {LOCK_PATH}")
    payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    if (
        payload.get("schema_version") != "isj-p07-mp-smoke-execution-lock-v2"
        or payload.get("status") != "FROZEN_READY_FOR_A02_M_P_EXPORT"
        or payload.get("execution_lock_hash") != lock_hash(payload)
    ):
        raise ExecutionViolation("M/P execution lock schema, status, or hash mismatch")
    if index not in payload.get("allowed_queue_indices", []):
        raise ExecutionViolation(f"queue index {index} is not allowed by the M/P lock")
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
        raise ExecutionViolation(f"lock/queue allocation mismatch: {differences}")
    return payload


def read_registry_unlocked(handle) -> tuple[list[str], list[dict[str, str]]]:
    handle.seek(0)
    reader = csv.DictReader(handle)
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise ExecutionViolation("invalid canonical run registry")
    return fields, rows


def registry_chain(run_id: str) -> list[dict[str, str]]:
    with RUN_REGISTRY.open(newline="", encoding="utf-8") as handle:
        _fields, rows = read_registry_unlocked(handle)
    chain = [row for row in rows if row["run_id"] == run_id]
    for index, row in enumerate(chain):
        if row["registry_event_id"] != f"{run_id}_e{index:02d}":
            raise ExecutionViolation(f"non-contiguous registry chain for {run_id}")
        expected_parent = "" if index == 0 else chain[index - 1]["registry_event_id"]
        if row["supersedes_event_id"] != expected_parent:
            raise ExecutionViolation(f"invalid registry supersession for {run_id}")
    return chain


def append_registry_event(
    run_id: str,
    *,
    expected_previous_status: str,
    status: str,
    run_dir: str,
    command_file: str,
    input_hash_manifest: str = "",
    output_hash_manifest: str = "",
    infrastructure_failure: str = "",
    accepted_lineage_count: str | None = None,
    active: str | None = None,
    note: str,
) -> dict[str, str]:
    with RUN_REGISTRY.open("r+", newline="", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            fields, rows = read_registry_unlocked(handle)
            chain = [row for row in rows if row["run_id"] == run_id]
            if not chain:
                raise ExecutionViolation(f"missing registry allocation for {run_id}")
            for index, item in enumerate(chain):
                if item["registry_event_id"] != f"{run_id}_e{index:02d}":
                    raise ExecutionViolation(f"non-contiguous registry chain for {run_id}")
            previous = chain[-1]
            if previous["status"] != expected_previous_status:
                raise ExecutionViolation(
                    f"registry latest status {previous['status']} != {expected_previous_status}"
                )
            event_number = len(chain)
            row = dict(previous)
            row.update(
                {
                    "registry_event_id": f"{run_id}_e{event_number:02d}",
                    "recorded_at": now(),
                    "supersedes_event_id": previous["registry_event_id"],
                    "status": status,
                    "run_dir": run_dir,
                    "command_file": command_file,
                    "input_hash_manifest": input_hash_manifest,
                    "output_hash_manifest": output_hash_manifest,
                    "infrastructure_failure": infrastructure_failure,
                    "notes": previous["notes"] + "; " + note,
                }
            )
            if accepted_lineage_count is not None:
                row["accepted_lineage_count"] = accepted_lineage_count
            if active is not None:
                row["active"] = active
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writerow(row)
            handle.seek(0, os.SEEK_END)
            handle.write(stream.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return row


def target_collisions(row: dict[str, str]) -> list[Path]:
    root = auditor.lexical_absolute(governance.ROOT / row["expected_run_root"])
    if row["arm"] == governance.M_ARM:
        run_dir = auditor.lexical_absolute(
            (governance.ROOT / row["expected_feature_bag"]).parent
        )
        return [run_dir] if run_dir.exists() else []
    return sorted(
        auditor.lexical_absolute(path)
        for path in root.glob(f"*{row['tag']}*")
        if path.exists()
    )


def _tree_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    if path.is_dir():
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    return total


def required_output_free_bytes(lock: dict[str, object]) -> int:
    estimate = lock["capacity_gate"]["estimated_required_output_free_bytes"]
    return max(BASE_MIN_OUTPUT_FREE_BYTES, int(estimate))


def capacity_report(row: dict[str, str], lock: dict[str, object]) -> dict[str, object]:
    output_root = auditor.lexical_absolute(governance.ROOT / row["expected_run_root"])
    if not output_root.is_dir():
        raise ExecutionViolation(f"missing frozen output root: {output_root}")
    output = shutil.disk_usage(output_root)
    governance_usage = shutil.disk_usage(governance.P07)
    minimum_output = required_output_free_bytes(lock)
    return {
        "output_root": auditor.display_path(output_root),
        "output_free_bytes": output.free,
        "output_minimum_free_bytes": minimum_output,
        "output_pass": output.free >= minimum_output,
        "governance_free_bytes": governance_usage.free,
        "governance_minimum_free_bytes": MIN_GOVERNANCE_FREE_BYTES,
        "governance_pass": governance_usage.free >= MIN_GOVERNANCE_FREE_BYTES,
    }


def run_command(
    command: str,
    log_path: Path,
    *,
    timeout_s: int,
    environment: dict[str, str],
) -> tuple[int, bool]:
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=governance.ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=timeout_s), False
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
            return 124, True


def write_hash_manifest(path: Path, files: list[Path]) -> None:
    unique = sorted({auditor.lexical_absolute(item) for item in files}, key=str)
    lines = []
    for item in unique:
        if not item.is_file():
            raise FileNotFoundError(item)
        lines.append(f"{sha256(item)}  {auditor.display_path(item)}\n")
    path.write_text("".join(lines), encoding="utf-8")


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
    variable = (
        "AQUAFE_P05_GUARD_ONLY" if row["arm"] == governance.M_ARM else "AQUAFE_GUARD_ONLY"
    )
    command = f"{variable}=1 {row['command']}"
    command_path = attempt_dir / "guard_preflight_command.txt"
    log_path = attempt_dir / "guard_preflight.log"
    command_path.write_text(command + "\n", encoding="utf-8")
    rc, timed_out = run_command(
        command, log_path, timeout_s=180, environment=environment
    )
    if rc != 0:
        raise ExecutionViolation(
            f"guard-only preflight failed rc={rc} timeout={str(timed_out).lower()}"
        )
    guard_path = auditor.parse_guard_path(log_path)
    auditor.validate_guard(guard_path, row["arm"])
    return log_path, guard_path


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
    audit_path = attempt_dir / "audit_v2.json"
    audit_log = attempt_dir / "audit_v2.log"
    completed = subprocess.run(
        [
            "python3",
            "scripts/audit_p07_mp_frontend_export_v2.py",
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
        raise ExecutionViolation(f"strict M/P export audit failed rc={completed.returncode}")
    payload = json.loads(audit_path.read_text(encoding="utf-8"))
    if payload.get("status") != "PASS":
        raise ExecutionViolation("strict M/P export audit did not return PASS")
    return audit_path, audit_log, payload


def output_files(
    run_dirs: list[Path],
    attempt_dir: Path,
    guard_paths: list[Path],
) -> list[Path]:
    selected: list[Path] = []
    for run_dir in run_dirs:
        if run_dir.is_dir():
            selected.extend(path for path in run_dir.rglob("*") if path.is_file())
    selected.extend(path for path in attempt_dir.iterdir() if path.is_file())
    selected.extend(guard_paths)
    return selected


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
        preflight = governance.P07 / f"queue_{index:03d}_{row['tag']}_capacity_waiting.json"
        if preflight.exists():
            raise FileExistsError(preflight)
        preflight.write_text(
            json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise ExecutionViolation(f"storage capacity gate failed without attempt creation: {capacity}")

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
    write_hash_manifest(input_manifest, [LOCK_PATH, *locked_files])
    command_rel = auditor.display_path(command_path)
    input_rel = auditor.display_path(input_manifest)
    provisional_run_dir = row["expected_run_root"]
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
                f"M/P v2 no-clobber executor started queue_index={index}; "
                "guard-only preflight exact PASS"
            ),
        )
        running_appended = True

        rc, timed_out = run_command(
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
        write_hash_manifest(
            output_manifest,
            output_files(
                run_dirs,
                attempt_dir,
                [guard_preflight_path, actual_guard_path],
            ),
        )
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
                f"arm export, exact nonfallback guard, attestation, and strict v2 audit PASS; "
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
        if running_appended:
            latest = registry_chain(allocation["run_id"])[-1]
            if latest["status"] == "RUNNING":
                append_registry_event(
                    allocation["run_id"],
                    expected_previous_status="RUNNING",
                    status="FAILED",
                    run_dir=provisional_run_dir,
                    command_file=command_rel,
                    input_hash_manifest=input_rel,
                    infrastructure_failure=(
                        "true" if "timeout=true" in str(error) else "false"
                    ),
                    note=f"M/P v2 export attempt failed closed: {type(error).__name__}: {error}",
                )
        else:
            latest = registry_chain(allocation["run_id"])[-1]
            if latest["status"] == "PLANNED" and attempt_dir.exists():
                append_registry_event(
                    allocation["run_id"],
                    expected_previous_status="PLANNED",
                    status="RUNNING",
                    run_dir=provisional_run_dir,
                    command_file=command_rel,
                    input_hash_manifest=input_rel,
                    note="M/P v2 attempt entered guard-only preflight",
                )
                append_registry_event(
                    allocation["run_id"],
                    expected_previous_status="RUNNING",
                    status="FAILED",
                    run_dir=provisional_run_dir,
                    command_file=command_rel,
                    input_hash_manifest=input_rel,
                    infrastructure_failure="false",
                    note=f"guard-only preflight failed closed: {type(error).__name__}: {error}",
                )
        raise


def preflight(index: int) -> dict[str, object]:
    lock = load_and_validate_lock(index)
    row = auditor.queue_row(index)
    allocation = auditor.allocation_row(index)
    return {
        "queue_index": index,
        "run_id": allocation["run_id"],
        "arm": row["arm"],
        "collisions": [auditor.display_path(path) for path in target_collisions(row)],
        "attempt_collision": (
            ATTEMPT_ROOT / f"queue_{index:03d}_{row['tag']}"
        ).exists(),
        "capacity": capacity_report(row, lock),
        "registry_latest_status": registry_chain(allocation["run_id"])[-1]["status"],
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
        ) else 1
    start = time.monotonic()
    result = execute(args.queue_index, timeout_s=args.timeout_s)
    result["elapsed_s"] = time.monotonic() - start
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
