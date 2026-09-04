#!/usr/bin/env python3
"""Validate and optionally dry-run every frozen P07 frontend export command."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from pathlib import Path

try:
    from scripts import build_p07_frontend_export_queue_v1 as builder
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_frontend_export_queue_v1 as builder  # type: ignore


OUTPUT = builder.P07 / "frontend_queue_validation_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_report(*, dry_run_all: bool) -> dict[str, object]:
    issues: list[str] = []
    exports, d_rows, expected_lock = builder.build_rows()
    export_content = builder.render_csv(builder.EXPORT_FIELDS, exports)
    d_content = builder.render_csv(builder.D_FIELDS, d_rows)
    observed_lock = json.loads(builder.QUEUE_LOCK.read_text(encoding="utf-8"))
    expected_lock["frontend_export_queue"] = {
        "path": builder.EXPORT_QUEUE.relative_to(builder.ROOT).as_posix(),
        "sha256": hashlib.sha256(export_content).hexdigest(),
        "size_bytes": len(export_content),
    }
    expected_lock["d_applicability_queue"] = {
        "path": builder.D_QUEUE.relative_to(builder.ROOT).as_posix(),
        "sha256": hashlib.sha256(d_content).hexdigest(),
        "size_bytes": len(d_content),
    }
    expected_lock["queue_lock_hash"] = builder.queue_hash(expected_lock)
    deterministic = {
        "frontend_queue_byte_identical": builder.EXPORT_QUEUE.read_bytes() == export_content,
        "d_queue_byte_identical": builder.D_QUEUE.read_bytes() == d_content,
        "queue_lock_semantic_identical": observed_lock == expected_lock,
    }
    if not all(deterministic.values()):
        issues.append("deterministic_queue_rebuild_mismatch")

    dry_runs: list[dict[str, object]] = []
    if dry_run_all:
        for row in exports:
            command = f"AQUAFE_DRY_RUN=1 {row['command']}"
            completed = subprocess.run(
                ["bash", "-lc", command],
                cwd=builder.ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            combined = completed.stdout + completed.stderr
            passed = completed.returncode == 0
            dry_runs.append(
                {
                    "queue_index": row["queue_index"],
                    "window_id": row["window_id"],
                    "arm": row["arm"],
                    "returncode": completed.returncode,
                    "output_sha256": hashlib.sha256(combined.encode("utf-8")).hexdigest(),
                    "pass": passed,
                }
            )
            if not passed:
                issues.append(f"dry_run_failed:{row['queue_index']}:{row['window_id']}:{row['arm']}")
    return {
        "schema_version": "isj-p07-frontend-queue-validation-v1",
        "status": "PASS" if not issues else "REVISE",
        "queue_lock_hash": observed_lock.get("queue_lock_hash"),
        "frontend_export_jobs": len(exports),
        "conditional_d_slots": len(d_rows),
        "deterministic_rebuild": deterministic,
        "dry_run_all_requested": dry_run_all,
        "dry_run_pass_count": sum(row["pass"] for row in dry_runs),
        "dry_runs": dry_runs,
        "artifacts": {
            "frontend_queue_sha256": sha256(builder.EXPORT_QUEUE),
            "d_queue_sha256": sha256(builder.D_QUEUE),
            "queue_lock_sha256": sha256(builder.QUEUE_LOCK),
        },
        "issues": sorted(set(issues)),
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
        "held_out_frontend_outcome_read": False,
        "held_out_trajectory_outcome_read": False,
    }


def write_no_clobber(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run-all", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report(dry_run_all=args.dry_run_all)
    write_no_clobber(args.output, report)
    print(
        f"P07_FRONTEND_QUEUE_VALIDATION_{report['status']} "
        f"jobs={report['frontend_export_jobs']} dry_pass={report['dry_run_pass_count']}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
