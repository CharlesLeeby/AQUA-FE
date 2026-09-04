#!/usr/bin/env python3
"""Execute one frozen P07 B1 smoke job with no-clobber governance."""

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
    from scripts.audit_p07_b1_frontend_export_v1 import queue_row
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore
    from audit_p07_b1_frontend_export_v1 import queue_row  # type: ignore


RUN_REGISTRY = governance.BUNDLE / "run_registry.csv"
ATTEMPT_ROOT = governance.P07 / "frontend_attempts"
MIN_OUTPUT_FREE_BYTES = 3 * 1024**3
MIN_GOVERNANCE_FREE_BYTES = 512 * 1024**2


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_registry() -> tuple[list[str], list[dict[str, str]]]:
    with RUN_REGISTRY.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if not fields or any(None in row for row in rows):
        raise ValueError("invalid canonical run registry")
    return fields, rows


def append_registry_event(
    run_id: str,
    *,
    event_number: int,
    status: str,
    run_dir: str,
    command_file: str,
    output_hash_manifest: str = "",
    infrastructure_failure: str = "",
    note: str,
) -> dict[str, str]:
    fields, rows = read_registry()
    chain = [row for row in rows if row["run_id"] == run_id]
    if len(chain) != event_number:
        raise ValueError(
            f"run registry chain length {len(chain)} != expected event {event_number}"
        )
    previous = chain[-1]
    expected_previous = f"{run_id}_e{event_number - 1:02d}"
    if previous["registry_event_id"] != expected_previous:
        raise ValueError("run registry chain is not contiguous")
    row = dict(previous)
    row.update(
        {
            "registry_event_id": f"{run_id}_e{event_number:02d}",
            "recorded_at": now(),
            "supersedes_event_id": previous["registry_event_id"],
            "status": status,
            "run_dir": run_dir,
            "command_file": command_file,
            "output_hash_manifest": output_hash_manifest,
            "infrastructure_failure": infrastructure_failure,
            "notes": previous["notes"] + "; " + note,
        }
    )
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writerow(row)
    content = stream.getvalue().encode("utf-8")
    with RUN_REGISTRY.open("ab", buffering=0) as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(content)
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return row


def allocation_row(index: int) -> dict[str, str]:
    rows = governance.read_csv(governance.ALLOCATION_CSV)
    matches = [row for row in rows if int(row["queue_index"]) == index]
    if len(matches) != 1:
        raise ValueError(f"expected one allocation row for index {index}")
    return matches[0]


def write_hash_manifest(path: Path, files: list[Path]) -> None:
    lines = []
    for item in files:
        if not item.is_file():
            raise FileNotFoundError(item)
        try:
            display = item.relative_to(governance.ROOT).as_posix()
        except ValueError:
            display = str(item)
        lines.append(f"{sha256(item)}  {display}\n")
    path.write_text("".join(lines), encoding="utf-8")


def target_collisions(row: dict[str, str]) -> list[Path]:
    root = governance.ROOT / row["expected_run_root"]
    collisions: list[Path] = []
    if row["expected_feature_bag"]:
        run_dir = (governance.ROOT / row["expected_feature_bag"]).parent
        if run_dir.exists():
            collisions.append(run_dir)
    else:
        if root.is_dir():
            collisions.extend(path for path in root.glob(f"*{row['tag']}*") if path.exists())
    return collisions


def capacity_report(row: dict[str, str]) -> dict[str, object]:
    output_root = governance.ROOT / row["expected_run_root"]
    output_root.mkdir(parents=True, exist_ok=True)
    output = shutil.disk_usage(output_root)
    governance_usage = shutil.disk_usage(governance.P07)
    return {
        "output_root": output_root.relative_to(governance.ROOT).as_posix(),
        "output_free_bytes": output.free,
        "output_minimum_free_bytes": MIN_OUTPUT_FREE_BYTES,
        "output_pass": output.free >= MIN_OUTPUT_FREE_BYTES,
        "governance_free_bytes": governance_usage.free,
        "governance_minimum_free_bytes": MIN_GOVERNANCE_FREE_BYTES,
        "governance_pass": governance_usage.free >= MIN_GOVERNANCE_FREE_BYTES,
    }


def run_command(command: str, log_path: Path, *, timeout_s: int) -> tuple[int, bool]:
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            ["bash", "-lc", command],
            cwd=governance.ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
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


def output_files(run_dir: Path, attempt_dir: Path, guard_path: Path) -> list[Path]:
    selected = [
        run_dir / "features.bag",
        run_dir / "frontend_metrics.csv",
        run_dir / "aqualoc_archaeo02_pinhole.yaml",
        run_dir / "features.bag.quality-contract.json",
        attempt_dir / "command.txt",
        attempt_dir / "command.log",
        attempt_dir / "input_hash_manifest.sha256",
        attempt_dir / "capacity_preflight.json",
        attempt_dir / "audit.json",
        guard_path,
    ]
    return [path for path in selected if path.is_file()]


def parse_guard_path(log_path: Path) -> Path:
    import re

    text = log_path.read_text(encoding="utf-8", errors="replace")
    matches = list(dict.fromkeys(re.findall(r"\bdecision=([^\s]+_decision\.json)", text)))
    if len(matches) != 1:
        raise ValueError(f"expected one guard decision path, found {matches}")
    path = Path(matches[0])
    return (path if path.is_absolute() else governance.ROOT / path).resolve()


def execute(index: int, *, timeout_s: int) -> dict[str, object]:
    row = queue_row(index)
    allocation = allocation_row(index)
    if row["arm"] != governance.B1:
        raise ValueError("executor v1 is intentionally restricted to B1 smoke jobs")
    if row["status"] != "PLANNED" or allocation["status"] != "PLANNED":
        raise ValueError("queue/allocation is not PLANNED")
    if target_collisions(row):
        raise FileExistsError(f"no-clobber target collision: {target_collisions(row)}")

    attempt_dir = ATTEMPT_ROOT / f"queue_{index:03d}_{row['tag']}"
    if attempt_dir.exists():
        raise FileExistsError(f"no-clobber governance collision: {attempt_dir}")
    attempt_dir.mkdir(parents=True)
    command_path = attempt_dir / "command.txt"
    command_log = attempt_dir / "command.log"
    command_path.write_text(row["command"] + "\n", encoding="utf-8")
    if hashlib.sha256(row["command"].encode("utf-8")).hexdigest() != row["command_sha256"]:
        raise ValueError("frozen command hash mismatch")

    capacity = capacity_report(row)
    capacity_path = attempt_dir / "capacity_preflight.json"
    capacity_path.write_text(
        json.dumps(capacity, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not capacity["output_pass"] or not capacity["governance_pass"]:
        raise RuntimeError(f"storage capacity gate failed: {capacity}")

    input_manifest = attempt_dir / "input_hash_manifest.sha256"
    write_hash_manifest(
        input_manifest,
        [
            governance.EXPORT_QUEUE,
            governance.ALLOCATION_CSV,
            governance.QUEUE_LOCK,
            governance.METHOD_LOCK,
            governance.MANIFEST,
            governance.BUNDLE / "dataset_checksum_manifest.txt",
        ],
    )
    command_file_rel = command_path.relative_to(governance.ROOT).as_posix()
    expected_run_dir = (governance.ROOT / row["expected_feature_bag"]).parent
    run_dir_rel = expected_run_dir.relative_to(governance.ROOT).as_posix()
    append_registry_event(
        allocation["run_id"],
        event_number=1,
        status="RUNNING",
        run_dir=run_dir_rel,
        command_file=command_file_rel,
        note=f"formal no-clobber executor started queue_index={index}",
    )

    rc, timed_out = run_command(row["command"], command_log, timeout_s=timeout_s)
    if rc != 0:
        append_registry_event(
            allocation["run_id"],
            event_number=2,
            status="FAILED",
            run_dir=run_dir_rel,
            command_file=command_file_rel,
            infrastructure_failure="true" if timed_out else "",
            note=f"frontend export process failed rc={rc} timeout={str(timed_out).lower()}",
        )
        raise RuntimeError(f"frontend export failed rc={rc} timeout={timed_out}")

    feature_bag = governance.ROOT / row["expected_feature_bag"]
    attestation = Path(str(feature_bag) + ".quality-contract.json")
    attest_log = attempt_dir / "attestation.log"
    with attest_log.open("wb") as log:
        completed = subprocess.run(
            [
                "python3",
                "scripts/attest_nativeq_feature_bag.py",
                "--feature-bag",
                str(feature_bag),
                "--output",
                str(attestation),
            ],
            cwd=governance.ROOT,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=False,
        )
    audit_path = attempt_dir / "audit.json"
    if completed.returncode == 0:
        completed = subprocess.run(
            [
                "python3",
                "scripts/audit_p07_b1_frontend_export_v1.py",
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
            check=False,
        )
        (attempt_dir / "audit.log").write_text(completed.stdout, encoding="utf-8")
    if completed.returncode != 0:
        append_registry_event(
            allocation["run_id"],
            event_number=2,
            status="FAILED",
            run_dir=run_dir_rel,
            command_file=command_file_rel,
            note="process returned zero but attestation or B1 export audit failed",
        )
        raise RuntimeError("B1 attestation/export audit failed")

    guard_path = parse_guard_path(command_log)
    output_manifest = attempt_dir / "output_hash_manifest.sha256"
    write_hash_manifest(output_manifest, output_files(expected_run_dir, attempt_dir, guard_path))
    output_manifest_rel = output_manifest.relative_to(governance.ROOT).as_posix()
    append_registry_event(
        allocation["run_id"],
        event_number=2,
        status="COMPLETED",
        run_dir=run_dir_rel,
        command_file=command_file_rel,
        output_hash_manifest=output_manifest_rel,
        infrastructure_failure="false",
        note="B1 export process, native-q attestation, and strict export-only audit PASS",
    )
    return {
        "queue_index": index,
        "run_id": allocation["run_id"],
        "status": "COMPLETED",
        "run_dir": run_dir_rel,
        "audit": audit_path.relative_to(governance.ROOT).as_posix(),
        "output_hash_manifest": output_manifest_rel,
        "elapsed_s": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-index", type=int, required=True)
    parser.add_argument("--timeout-s", type=int, default=3600)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    row = queue_row(args.queue_index)
    allocation = allocation_row(args.queue_index)
    preflight = {
        "queue_index": args.queue_index,
        "run_id": allocation["run_id"],
        "arm": row["arm"],
        "collisions": [str(path) for path in target_collisions(row)],
        "capacity": capacity_report(row),
    }
    if args.preflight_only:
        print(json.dumps(preflight, indent=2, sort_keys=True))
        return 0 if not preflight["collisions"] and all(
            preflight["capacity"][name]
            for name in ("output_pass", "governance_pass")
        ) else 1
    start = time.monotonic()
    result = execute(args.queue_index, timeout_s=args.timeout_s)
    result["elapsed_s"] = time.monotonic() - start
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
