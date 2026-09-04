#!/usr/bin/env python3
"""Independently validate the frozen P07 pre-outcome governance bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

try:
    from scripts import build_p07_preoutcome_governance_v1 as builder
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p07_preoutcome_governance_v1 as builder  # type: ignore


OUTPUT = builder.P07 / "preoutcome_governance_validation_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not reader.fieldnames or any(None in row for row in rows):
        raise ValueError(f"invalid CSV: {path}")
    return rows


def build_report() -> dict[str, object]:
    issues: list[str] = []
    expected = builder.build_outputs()
    deterministic = {
        path.name: path.is_file() and path.read_bytes() == content
        for path, content in expected.items()
    }
    if not all(deterministic.values()):
        issues.append("preoutcome_artifact_rebuild_mismatch")

    splits = read_csv(builder.SPLIT_CSV)
    allocations = read_csv(builder.ALLOCATION_CSV)
    split_summary = json.loads(builder.SPLIT_JSON.read_text(encoding="utf-8"))
    analysis = json.loads(builder.ANALYSIS_LOCK.read_text(encoding="utf-8"))
    queue = read_csv(builder.EXPORT_QUEUE)
    queue_validation = json.loads(builder.QUEUE_VALIDATION.read_text(encoding="utf-8"))
    method = json.loads(builder.METHOD_LOCK.read_text(encoding="utf-8"))

    semantic = {
        "selected_windows_20": len(splits) == 20,
        "history_overlap_zero": all(
            row["selected_interval_overlaps_history"] == "false" for row in splits
        ),
        "sequence_unseen_window_count_1": sum(
            row["corrected_split_role"] == "SEQUENCE_UNSEEN_OUTCOME_BLIND_WINDOW"
            for row in splits
        )
        == 1,
        "sequence_unseen_low_count_0": split_summary.get("sequence_unseen_low_windows")
        == 0,
        "external_held_out_count_0": split_summary.get("external_held_out_windows") == 0,
        "allocations_60": len(allocations) == 60,
        "allocation_run_ids_unique": len({row["run_id"] for row in allocations}) == 60,
        "allocation_queue_index_exact": [row["queue_index"] for row in allocations]
        == [row["queue_index"] for row in queue],
        "allocation_command_hash_exact": [row["command_sha256"] for row in allocations]
        == [row["command_sha256"] for row in queue],
        "queue_dry_run_60_pass": queue_validation.get("status") == "PASS"
        and queue_validation.get("dry_run_pass_count") == 60,
        "analysis_method_hash_exact": analysis.get("method_lock_hash")
        == method.get("method_lock_hash"),
        "analysis_primary_is_RPE": analysis.get("metrics", {}).get("primary")
        == "G0_common_support_exact_1s_translation_RPE_RMSE",
        "H2_not_applicable": analysis.get("hypotheses", {})
        .get("H2_source_specificity", {})
        .get("status")
        == "NOT_APPLICABLE_CARRIER_FEEDBACK",
        "base_replay_count_240": analysis.get("execution", {}).get(
            "base_backend_replays"
        )
        == 240,
        "max_replay_count_300": analysis.get("execution", {}).get(
            "maximum_backend_replays"
        )
        == 300,
    }
    if not all(semantic.values()):
        issues.extend(f"semantic_check_failed:{name}" for name, passed in semantic.items() if not passed)

    artifact_hashes: list[dict[str, object]] = []
    for record in analysis.get("artifacts", []):
        path = builder.ROOT / str(record["path"])
        observed = sha256(path) if path.is_file() else None
        passed = observed == record.get("sha256")
        artifact_hashes.append(
            {
                "path": record["path"],
                "expected_sha256": record.get("sha256"),
                "observed_sha256": observed,
                "pass": passed,
            }
        )
        if not passed:
            issues.append(f"analysis_artifact_hash_mismatch:{record['path']}")

    return {
        "schema_version": "isj-p07-preoutcome-governance-validation-v1",
        "status": "PASS" if not issues else "REVISE",
        "deterministic_rebuild": deterministic,
        "semantic_checks": semantic,
        "analysis_artifact_hashes": artifact_hashes,
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
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    report = build_report()
    write_no_clobber(args.output, report)
    print(
        f"P07_PREOUTCOME_GOVERNANCE_VALIDATION_{report['status']} "
        f"artifacts={len(report['analysis_artifact_hashes'])}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
