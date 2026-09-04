#!/usr/bin/env python3
"""Validate every published P06 final-freeze artifact byte for byte."""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path

try:
    from scripts import build_p06_final_freeze_v1 as builder
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p06_final_freeze_v1 as builder  # type: ignore


OUTPUT = builder.P06 / "final_freeze_validation_v1.json"


def build_report() -> dict[str, object]:
    issues: list[str] = []
    expected = builder.build_outputs()
    artifact_checks: dict[str, dict[str, object]] = {}
    for path, content in expected.items():
        exists = path.is_file()
        observed = path.read_bytes() if exists else b""
        identical = exists and observed == content
        artifact_checks[builder.relative(path)] = {
            "exists": exists,
            "byte_identical_to_rebuild": identical,
            "sha256": builder.sha256_bytes(observed) if exists else None,
            "size_bytes": len(observed) if exists else None,
        }
        if not identical:
            issues.append(f"rebuild_mismatch:{builder.relative(path)}")

    method = json.loads(builder.METHOD_LOCK.read_text(encoding="utf-8"))
    if builder.final_method_hash(method) != method.get("method_lock_hash"):
        issues.append("method_lock_hash_mismatch")
    arm_rows = list(
        csv.DictReader(io.StringIO(builder.ARM_ORDER.read_text(encoding="utf-8")))
    )
    try:
        normalized_arm_rows = [
            {
                **row,
                "assignment_rank": int(row["assignment_rank"]),
                "pattern_id": int(row["pattern_id"]),
                "order_position": int(row["order_position"]),
                "algorithmic_replay_slots": int(row["algorithmic_replay_slots"]),
            }
            for row in arm_rows
        ]
        builder.validate_arm_rows(normalized_arm_rows)
    except Exception as exc:
        issues.append(f"arm_order_invalid:{type(exc).__name__}:{exc}")

    freeze_lines = builder.FREEZE_HASHES.read_text(encoding="ascii").splitlines()
    freeze_checks: list[dict[str, object]] = []
    for line in freeze_lines:
        digest, raw_path = line.split("  ", 1)
        path = builder.ROOT / raw_path
        observed = builder.sha256_bytes(path.read_bytes()) if path.is_file() else None
        passed = observed == digest
        freeze_checks.append(
            {"path": raw_path, "expected_sha256": digest, "observed_sha256": observed, "pass": passed}
        )
        if not passed:
            issues.append(f"freeze_hash_mismatch:{raw_path}")

    checksum_lines = builder.DATASET_CHECKSUM_MANIFEST.read_text(
        encoding="ascii"
    ).splitlines()
    if len(checksum_lines) != 41:
        issues.append(f"dataset_checksum_count:{len(checksum_lines)}")
    for line in checksum_lines:
        _digest, raw_path = line.split("  ", 1)
        if not (builder.ROOT / raw_path).is_file():
            issues.append(f"selected_input_missing:{raw_path}")

    return {
        "schema_version": "isj-p06-final-freeze-validation-v1",
        "status": "PASS" if not issues else "REVISE",
        "method_lock_hash": method.get("method_lock_hash"),
        "published_artifacts": artifact_checks,
        "freeze_hash_checks": freeze_checks,
        "dataset_checksum_entry_count": len(checksum_lines),
        "arm_order_row_count": len(arm_rows),
        "issues": sorted(set(issues)),
        "outcome_boundary": builder.OUTCOME_BOUNDARY,
        "held_out_learned_outcome_read": False,
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
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    write_no_clobber(args.output, report)
    print(
        f"P06_FINAL_FREEZE_VALIDATION_{report['status']} "
        f"issues={len(report['issues'])}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
