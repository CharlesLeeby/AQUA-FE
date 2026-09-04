#!/usr/bin/env python3
"""Derive P06 candidate capacity after frozen reference-support exclusion."""

from __future__ import annotations

import csv
import json
from pathlib import Path

try:
    from scripts.build_p06_screening_manifest import history_excluded_indices
    from scripts.validate_p06_final_artifacts import read_csv
except ModuleNotFoundError:
    from build_p06_screening_manifest import history_excluded_indices
    from validate_p06_final_artifacts import read_csv


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
HISTORY = BUNDLE / "history_exclusion_manifest.csv"
SUPPORT = P06 / "reference_window_support_audit_v2.csv"
OUTPUT = P06 / "candidate_capacity_reference_support_v2.csv"
SUMMARY = P06 / "candidate_capacity_reference_support_v2.json"
FIELDS = (
    "schema_version",
    "protocol_version",
    "dataset_family",
    "data_domain",
    "sequence",
    "gross_windows",
    "history_excluded_windows",
    "reference_failed_windows",
    "history_reference_overlap_windows",
    "corrected_available_windows",
    "corrected_max_per_sequence_cap",
    "p02_registered_available_windows",
    "p02_registered_max_per_sequence_cap",
    "capacity_decision",
    "outcome_boundary",
)


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    capacity = [
        row
        for row in read_csv(CAPACITY)
        if row["low_normal_sequence_capacity_status"] == "CAPACITY_CANDIDATE"
    ]
    history = read_csv(HISTORY)
    support = read_csv(SUPPORT)
    failed: dict[tuple[str, str], set[int]] = {}
    for row in support:
        key = (row["dataset_family"], row["sequence"])
        failed.setdefault(key, set())
        if row["reference_support_pass"] == "false":
            failed[key].add(int(row["window_index"]))
    rows: list[dict[str, object]] = []
    for spec in capacity:
        family = spec["dataset_family"]
        sequence = spec["sequence"]
        gross = int(spec["gross_nonoverlap_windows"])
        history_indices = history_excluded_indices(family, sequence, gross, history)
        reference_indices = failed[(family, sequence)]
        available = gross - len(history_indices | reference_indices)
        cap = min(4, available)
        rows.append(
            {
                "schema_version": "isj-p06-reference-capacity-v2",
                "protocol_version": "isj-window-selection-v2",
                "dataset_family": family,
                "data_domain": spec["data_domain"],
                "sequence": sequence,
                "gross_windows": gross,
                "history_excluded_windows": len(history_indices),
                "reference_failed_windows": len(reference_indices),
                "history_reference_overlap_windows": len(
                    history_indices & reference_indices
                ),
                "corrected_available_windows": available,
                "corrected_max_per_sequence_cap": cap,
                "p02_registered_available_windows": spec[
                    "available_candidate_windows"
                ],
                "p02_registered_max_per_sequence_cap": spec[
                    "max_per_sequence_cap"
                ],
                "capacity_decision": (
                    "CAPACITY_CANDIDATE_REFERENCE_VALIDATED"
                    if available > 0
                    else "EXCLUDE_SEQUENCE_REFERENCE_INELIGIBLE"
                ),
                "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
            }
        )
    active = [row for row in rows if int(row["corrected_available_windows"]) > 0]
    return rows, {
        "schema_version": "isj-p06-reference-capacity-summary-v2",
        "protocol_version": "isj-window-selection-v2",
        "registered_sequence_count": len(rows),
        "reference_eligible_sequence_count": len(active),
        "excluded_sequences": [
            f"{row['dataset_family']}/{row['sequence']}"
            for row in rows
            if int(row["corrected_available_windows"]) == 0
        ],
        "corrected_capped_slot_count": sum(
            int(row["corrected_max_per_sequence_cap"]) for row in active
        ),
        "corrected_domain_count": len({row["data_domain"] for row in active}),
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("reference capacity correction is immutable once written")
    rows, summary = build_rows()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_REFERENCE_CAPACITY sequences={summary['reference_eligible_sequence_count']} "
        f"slots={summary['corrected_capped_slot_count']} "
        f"domains={summary['corrected_domain_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
