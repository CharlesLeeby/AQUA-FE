#!/usr/bin/env python3
"""Validate reference-aware P06 final selection and corrected capacity."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from scripts.validate_p06_final_artifacts import index, read_csv
except ModuleNotFoundError:
    from validate_p06_final_artifacts import index, read_csv


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
PROGRESS = P06 / "screening_progress.json"
DATASET_MANIFEST = BUNDLE / "dataset_manifest.csv"
WINDOW_AUDIT = BUNDLE / "window_selection_audit.csv"
CORRECTED_CAPACITY = P06 / "candidate_capacity_reference_support_v2.csv"
REFERENCE_SUPPORT = P06 / "reference_window_support_audit_v2.csv"
REQUIRED_SNAPSHOT_PATHS = {
    "papers/ieee_sensors_journal_experiments/p06/afrl_calibration_correction_v1.json",
    "papers/ieee_sensors_journal_experiments/p06/afrl_calibration_correction_v1.sha256",
    "papers/ieee_sensors_journal_experiments/p06/screening_runner_hashes_v3.sha256",
    "papers/ieee_sensors_journal_experiments/p06/screening_attestations_v2.jsonl",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_selected_consistency(
    selected: list[dict[str, str]], audit: list[dict[str, str]]
) -> list[str]:
    issues: list[str] = []
    if len(selected) != 20:
        issues.append(f"selected_window_count:{len(selected)}")
    selected_ids = [row.get("window_id", "") for row in selected]
    if any(not value for value in selected_ids) or len(selected_ids) != len(set(selected_ids)):
        issues.append("selected_window_id_not_unique")
    audit_by_id: dict[str, dict[str, str]] = {}
    for row in audit:
        window_id = row.get("window_id", "")
        if not window_id or window_id in audit_by_id:
            issues.append("window_audit_id_not_unique")
            continue
        audit_by_id[window_id] = row
    flagged = {
        row.get("window_id", "")
        for row in audit
        if row.get("selected_final", "").lower() == "true"
    }
    if flagged != set(selected_ids) or len(flagged) != 20:
        issues.append("selected_final_identity_mismatch")
    common_fields = (
        "dataset_family",
        "data_domain",
        "sequence",
        "window_index",
        "window_start_s",
        "window_end_s",
        "texture_stratum",
        "score",
        "input_frame_count",
    )
    for selected_row in selected:
        window_id = selected_row.get("window_id", "")
        source = audit_by_id.get(window_id)
        if source is None:
            issues.append(f"selected_not_in_audit:{window_id}")
            continue
        for field in common_fields:
            if selected_row.get(field) != source.get(field):
                issues.append(f"selected_audit_field_mismatch:{window_id}:{field}")
        if source.get("history_excluded", "").lower() != "false":
            issues.append(f"selected_history_excluded:{window_id}")
        if source.get("reference_support_pass", "").lower() != "true":
            issues.append(f"selected_reference_support_fail:{window_id}")
        try:
            if int(float(source.get("input_frame_count", "0"))) < 200:
                issues.append(f"selected_input_support_fail:{window_id}")
        except ValueError:
            issues.append(f"selected_input_frame_count_invalid:{window_id}")
    strata = Counter(row.get("texture_stratum", "") for row in selected)
    if strata["low"] != 10:
        issues.append(f"selected_low_count:{strata['low']}")
    if strata["normal"] != 10:
        issues.append(f"selected_normal_count:{strata['normal']}")
    for stratum in ("low", "normal"):
        rows = [row for row in selected if row.get("texture_stratum") == stratum]
        if len({row.get("sequence") for row in rows}) < 6:
            issues.append(f"{stratum}_sequence_diversity")
        if len({row.get("data_domain") for row in rows}) < 2:
            issues.append(f"{stratum}_domain_diversity")
        counts = Counter(row.get("sequence") for row in rows)
        if max(counts.values(), default=0) > 2:
            issues.append(f"{stratum}_sequence_cap")
    all_counts = Counter(row.get("sequence") for row in selected)
    if max(all_counts.values(), default=0) > 4:
        issues.append("overall_sequence_cap")
    if len({row.get("data_domain") for row in selected}) < 3:
        issues.append("overall_domain_diversity")
    return sorted(set(issues))


def build_report() -> dict[str, Any]:
    if not all(path.is_file() for path in (PROGRESS, DATASET_MANIFEST, WINDOW_AUDIT)):
        return {
            "schema_version": "isj-p06-final-artifact-validation-v2",
            "status": "IN_PROGRESS",
            "issues": ["missing_final_p06_artifacts"],
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    selected = read_csv(DATASET_MANIFEST)
    audit = read_csv(WINDOW_AUDIT)
    correction_rows = read_csv(CORRECTED_CAPACITY)
    corrected = {
        (row["dataset_family"], row["sequence"]): row
        for row in correction_rows
        if row["capacity_decision"] == "CAPACITY_CANDIDATE_REFERENCE_VALIDATED"
    }
    support = {
        (row["dataset_family"], row["sequence"], row["window_index"]): row
        for row in read_csv(REFERENCE_SUPPORT)
    }
    issues = validate_selected_consistency(selected, audit)
    if progress.get("status") != "PASS":
        issues.append(f"screening_progress_status:{progress.get('status')}")
    if progress.get("registered_sequence_count") != 18:
        issues.append("registered_sequence_count_mismatch")
    if progress.get("reference_eligible_sequence_count") != len(corrected):
        issues.append("reference_eligible_sequence_count_mismatch")
    if progress.get("reference_excluded_sequences") != ["cave_gennie"]:
        issues.append("reference_excluded_sequence_mismatch")
    snapshot = progress.get("input_snapshot")
    if not isinstance(snapshot, dict) or not snapshot:
        issues.append("input_snapshot_missing")
        snapshot = {}
    missing_snapshot_paths = REQUIRED_SNAPSHOT_PATHS - set(snapshot)
    for relative in sorted(missing_snapshot_paths):
        issues.append(f"input_snapshot_required_path_missing:{relative}")
    for relative, digest in snapshot.items():
        target = ROOT / str(relative)
        if (
            Path(str(relative)).is_absolute()
            or ".." in Path(str(relative)).parts
            or not target.is_file()
        ):
            issues.append(f"input_snapshot_path_invalid:{relative}")
        elif sha256(target) != digest:
            issues.append(f"input_snapshot_hash_mismatch:{relative}")
    for key, expected in (
        ("window_selection_audit", WINDOW_AUDIT),
        ("dataset_manifest", DATASET_MANIFEST),
    ):
        record = progress.get(key)
        if not isinstance(record, dict):
            issues.append(f"progress_hash_record_missing:{key}")
        elif record.get("path") != expected.relative_to(ROOT).as_posix() or record.get(
            "sha256"
        ) != sha256(expected):
            issues.append(f"progress_hash_mismatch:{key}")
    sequence_audits: dict[tuple[str, str], dict[str, Any]] = {}
    for row in progress.get("sequence_audits", []):
        key = (str(row.get("dataset_family", "")), str(row.get("sequence", "")))
        if key in sequence_audits:
            issues.append(f"duplicate_sequence_audit:{key[0]}/{key[1]}")
        sequence_audits[key] = row
    if set(sequence_audits) != set(corrected):
        issues.append("sequence_audit_denominator_mismatch")
    for key, capacity in corrected.items():
        row = sequence_audits.get(key)
        if row is None:
            continue
        comparisons = {
            "gross_windows_actual": int(capacity["gross_windows"]),
            "history_excluded_actual": int(capacity["history_excluded_windows"]),
            "reference_failed_actual": int(capacity["reference_failed_windows"]),
            "reference_history_overlap_actual": int(
                capacity["history_reference_overlap_windows"]
            ),
            "available_windows_actual": int(capacity["corrected_available_windows"]),
            "available_windows_registered_corrected": int(
                capacity["corrected_available_windows"]
            ),
        }
        for field, value in comparisons.items():
            if row.get(field) != value:
                issues.append(f"sequence_count_mismatch:{key[0]}/{key[1]}:{field}")
    for row in selected:
        key = (row["dataset_family"], row["sequence"], row["window_index"])
        support_row = support.get(key)
        if support_row is None or support_row["reference_support_pass"] != "true":
            issues.append(f"selected_support_crosslink_fail:{row['window_id']}")
    return {
        "schema_version": "isj-p06-final-artifact-validation-v2",
        "status": "PASS" if not issues else "REVISE",
        "selected_window_count": len(selected),
        "reference_eligible_sequence_count": len(corrected),
        "reference_excluded_sequences": ["cave_gennie"],
        "issues": sorted(set(issues)),
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    report = build_report()
    rendered = json.dumps(report, sort_keys=True, indent=2) + "\n"
    print(rendered, end="")
    if args.output:
        Path(args.output).write_text(rendered, encoding="utf-8")
    return 0 if report["status"] == "PASS" else (2 if report["status"] == "IN_PROGRESS" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
