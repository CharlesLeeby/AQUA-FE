#!/usr/bin/env python3
"""Validate the final full-reference P06 v4 selection artifacts."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path

try:
    from scripts import build_p06_screening_manifest_v3 as v3_builder
    from scripts import build_p06_screening_manifest_v4 as builder
    from scripts import validate_p06_final_artifacts_v3 as v3_validator
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_p06_screening_manifest_v3 as v3_builder  # type: ignore
    import build_p06_screening_manifest_v4 as builder  # type: ignore
    import validate_p06_final_artifacts_v3 as v3_validator  # type: ignore


ROOT = builder.ROOT
BUNDLE = builder.BUNDLE
OUTPUT = BUNDLE / "p06/final_artifact_validation_v4.json"


def deterministic_rebuild() -> dict[str, object]:
    rows, selected, progress = builder.build_selection()
    audit_bytes = v3_validator.render_csv(v3_builder.audit_fields(rows), rows)
    manifest_bytes = v3_validator.render_csv(
        builder.MANIFEST_FIELDS, builder.manifest_rows(selected)
    )
    observed_progress = json.loads(builder.OUTPUT_PROGRESS.read_text(encoding="utf-8"))
    expected_progress = dict(progress)
    expected_progress["window_selection_audit"] = {
        "path": v3_builder.relative(builder.OUTPUT_AUDIT),
        "sha256": v3_validator.hash_bytes(audit_bytes),
        "size_bytes": len(audit_bytes),
    }
    expected_progress["dataset_manifest"] = {
        "path": v3_builder.relative(builder.OUTPUT_MANIFEST),
        "sha256": v3_validator.hash_bytes(manifest_bytes),
        "size_bytes": len(manifest_bytes),
    }
    return {
        "pass": (
            v3_validator.hash_bytes(audit_bytes)
            == v3_validator.sha256(builder.OUTPUT_AUDIT)
            and v3_validator.hash_bytes(manifest_bytes)
            == v3_validator.sha256(builder.OUTPUT_MANIFEST)
            and expected_progress == observed_progress
        ),
        "window_audit_sha256": v3_validator.sha256(builder.OUTPUT_AUDIT),
        "manifest_sha256": v3_validator.sha256(builder.OUTPUT_MANIFEST),
        "expected_progress_equals_observed": expected_progress == observed_progress,
    }


def build_report() -> dict[str, object]:
    issues: list[str] = []
    required = (
        builder.OUTPUT_AUDIT,
        builder.OUTPUT_MANIFEST,
        builder.OUTPUT_PROGRESS,
    )
    if any(not path.is_file() for path in required):
        return {
            "schema_version": "isj-p06-final-artifact-validation-v4",
            "status": "IN_PROGRESS",
            "issues": ["missing_v4_selection_artifacts"],
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    audit = v3_validator.read_csv(builder.OUTPUT_AUDIT)
    selected = v3_validator.read_csv(builder.OUTPUT_MANIFEST)
    progress = json.loads(builder.OUTPUT_PROGRESS.read_text(encoding="utf-8"))
    if len(audit) != 156:
        issues.append(f"window_audit_count:{len(audit)}")
    if len(selected) != 20:
        issues.append(f"selected_window_count:{len(selected)}")
    if (
        progress.get("status") != "PASS"
        or progress.get("all_selected_full_reference_support") is not True
    ):
        issues.append("screening_progress_not_pass")
    if progress.get("learned_outcome_read") is not False:
        issues.append("learned_outcome_boundary_violation")
    if progress.get("trajectory_outcome_read") is not False:
        issues.append("trajectory_outcome_boundary_violation")

    selected_ids = [row.get("window_id", "") for row in selected]
    audit_by_id = {row["window_id"]: row for row in audit}
    if len(selected_ids) != len(set(selected_ids)) or any(not value for value in selected_ids):
        issues.append("duplicate_or_empty_selected_window_id")
    if len(audit_by_id) != len(audit):
        issues.append("duplicate_window_audit_id")
    if set(selected_ids) != {
        row["window_id"] for row in audit if row.get("selected_final") == "true"
    }:
        issues.append("manifest_audit_selection_mismatch")

    strata = Counter(row.get("texture_stratum", "") for row in selected)
    tiers = Counter(row.get("selection_tier", "") for row in selected)
    if strata != {"low": 10, "normal": 10}:
        issues.append(f"stratum_counts:{dict(strata)}")
    if tiers != {
        "ABSOLUTE_LOW": 3,
        "RELATIVE_Q80_FALLBACK": 7,
        "STRICT_NORMAL": 10,
    }:
        issues.append(f"tier_counts:{dict(tiers)}")

    sequence_stratum: Counter[tuple[str, str]] = Counter()
    for row in selected:
        window_id = row["window_id"]
        source = audit_by_id.get(window_id)
        if source is None:
            issues.append(f"selected_missing_from_audit:{window_id}")
            continue
        if source.get("history_excluded") != "false":
            issues.append(f"history_excluded_selected:{window_id}")
        if source.get("full_reference_support") != "true":
            issues.append(f"full_reference_gate_selected:{window_id}")
        if int(row["reference_supported_grid_count"]) != int(row["reference_grid_count"]):
            issues.append(f"reference_grid_count_selected:{window_id}")
        if float(row["reference_full_coverage"]) != 1.0:
            issues.append(f"reference_coverage_selected:{window_id}")
        if int(float(row["input_frame_count"])) < 200:
            issues.append(f"input_support_selected:{window_id}")
        score = float(row["score"])
        q20 = float(row["sequence_q20"])
        q80 = float(row["sequence_q80"])
        tier = row["selection_tier"]
        if tier == "ABSOLUTE_LOW" and not (score >= 0.17 and score >= q80):
            issues.append(f"absolute_low_rule:{window_id}")
        elif tier == "RELATIVE_Q80_FALLBACK" and not (
            0.10 < score < 0.17 and score >= q80
        ):
            issues.append(f"relative_low_rule:{window_id}")
        elif tier == "STRICT_NORMAL" and not (score <= 0.10 and score <= q20):
            issues.append(f"strict_normal_rule:{window_id}")
        sequence_stratum[(row["sequence"], row["texture_stratum"])] += 1
    if max(sequence_stratum.values(), default=0) > 2:
        issues.append("per_sequence_stratum_cap_exceeded")

    for stratum in ("low", "normal"):
        subset = [row for row in selected if row["texture_stratum"] == stratum]
        if len({row["sequence"] for row in subset}) < 6:
            issues.append(f"sequence_diversity:{stratum}")
        if len({row["data_domain"] for row in subset}) < 2:
            issues.append(f"domain_diversity:{stratum}")
    if len({row["data_domain"] for row in selected}) < 3:
        issues.append("joint_domain_diversity")

    deterministic = deterministic_rebuild()
    if deterministic["pass"] is not True:
        issues.append("deterministic_rebuild_mismatch")
    support, support_issues = v3_validator.reference_support_report(selected)
    issues.extend(support_issues)
    return {
        "schema_version": "isj-p06-final-artifact-validation-v4",
        "status": "PASS" if not issues else "REVISE",
        "protocol_version": builder.PROTOCOL_VERSION,
        "selected_window_count": len(selected),
        "stratum_counts": dict(sorted(strata.items())),
        "tier_counts": dict(sorted(tiers.items())),
        "selected_sequence_count": len({row["sequence"] for row in selected}),
        "selected_domain_count": len({row["data_domain"] for row in selected}),
        "deterministic_rebuild": deterministic,
        "selected_reference_support": support,
        "artifacts": {
            "window_selection_audit": {
                "path": v3_builder.relative(builder.OUTPUT_AUDIT),
                "sha256": v3_validator.sha256(builder.OUTPUT_AUDIT),
            },
            "dataset_manifest": {
                "path": v3_builder.relative(builder.OUTPUT_MANIFEST),
                "sha256": v3_validator.sha256(builder.OUTPUT_MANIFEST),
            },
            "screening_progress": {
                "path": v3_builder.relative(builder.OUTPUT_PROGRESS),
                "sha256": v3_validator.sha256(builder.OUTPUT_PROGRESS),
            },
        },
        "issues": sorted(set(issues)),
        "outcome_boundary": v3_builder.OUTCOME_BOUNDARY,
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
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
        f"P06_FINAL_ARTIFACTS_V4_{report['status']} "
        f"selected={report.get('selected_window_count', 0)} "
        f"issues={len(report.get('issues', []))}"
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
