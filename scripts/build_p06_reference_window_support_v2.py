#!/usr/bin/env python3
"""Apply the frozen G0 reference-only validity gate to P06 fixed windows."""

from __future__ import annotations

import bisect
import csv
import json
import math
from pathlib import Path
from typing import Any

try:
    from scripts.validate_p06_final_artifacts import index, load_reference_stamps, read_csv
except ModuleNotFoundError:
    from validate_p06_final_artifacts import index, load_reference_stamps, read_csv


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
REFERENCES = BUNDLE / "reference_audit.csv"
V1_AUDIT = P06 / "reference_window_support_audit.csv"
V1_SUMMARY = P06 / "reference_window_support_summary.json"
OUTPUT = P06 / "reference_window_support_audit_v2.csv"
SUMMARY = P06 / "reference_window_support_summary_v2.json"
FIELDS = (
    "schema_version",
    "protocol_version",
    "dataset_family",
    "sequence",
    "window_index",
    "window_start_s",
    "window_end_s",
    "absolute_start_s",
    "absolute_end_s",
    "evaluation_rate_hz",
    "max_reference_gap_s",
    "grid_count",
    "supported_grid_count",
    "coverage",
    "supported_span_s",
    "worst_bracket_gap_s",
    "reference_support_pass",
    "reference_support_reason",
    "outcome_boundary",
)


def g0_reference_support(
    stamps: list[float],
    start_s: float,
    end_s: float,
    evaluation_rate_hz: float,
    max_reference_gap_s: float,
) -> dict[str, Any]:
    step = 1.0 / evaluation_rate_hz
    count = int(math.floor((end_s - start_s) * evaluation_rate_hz + 1e-9)) + 1
    grid = [start_s + index * step for index in range(count)]
    supported_values: list[float] = []
    worst_bracket_gap = 0.0
    tolerance = 1e-6
    for value in grid:
        position = bisect.bisect_left(stamps, value)
        if position < len(stamps) and abs(stamps[position] - value) <= tolerance:
            supported_values.append(value)
            continue
        if position == 0 or position == len(stamps):
            continue
        left = stamps[position - 1]
        right = stamps[position]
        gap = right - left
        worst_bracket_gap = max(worst_bracket_gap, gap)
        if gap <= max_reference_gap_s + tolerance:
            supported_values.append(value)
    supported = len(supported_values)
    coverage = supported / len(grid) if grid else 0.0
    span = (
        supported_values[-1] - supported_values[0]
        if len(supported_values) >= 2
        else 0.0
    )
    reasons: list[str] = []
    if supported < 30:
        reasons.append("REFERENCE_POSES_LT_30")
    if coverage < 0.70:
        reasons.append("REFERENCE_COVERAGE_LT_0P70")
    if span < 10.0:
        reasons.append("REFERENCE_SPAN_LT_10S")
    return {
        "pass": not reasons,
        "grid_count": len(grid),
        "supported_grid_count": supported,
        "coverage": coverage,
        "supported_span_s": span,
        "worst_bracket_gap_s": worst_bracket_gap,
        "reason": ";".join(reasons) if reasons else "PASS_G0_REFERENCE_ONLY",
    }


def build_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not V1_AUDIT.is_file() or not V1_SUMMARY.is_file():
        raise FileNotFoundError("v1 strict support preflight is required")
    strict_rows = read_csv(V1_AUDIT)
    origins = {
        tuple(key.split("/", 1)): float(value)
        for key, value in json.loads(V1_SUMMARY.read_text(encoding="utf-8"))[
            "sequence_origins"
        ].items()
    }
    eligibility = index(read_csv(ELIGIBILITY))
    references = index(read_csv(REFERENCES))
    stamps_by_sequence: dict[tuple[str, str], list[float]] = {}
    rows: list[dict[str, Any]] = []
    for source in strict_rows:
        key = (source["dataset_family"], source["sequence"])
        family, sequence = key
        if key not in stamps_by_sequence:
            stamps_by_sequence[key] = load_reference_stamps(
                family,
                sequence,
                ROOT / eligibility[key]["reference_path"],
            )
        reference = references[key]
        start_s = origins[key] + float(source["window_start_s"])
        end_s = origins[key] + float(source["window_end_s"])
        support = g0_reference_support(
            stamps_by_sequence[key],
            start_s,
            end_s,
            float(reference["evaluation_rate_hz"]),
            float(reference["max_reference_gap_s"]),
        )
        rows.append(
            {
                "schema_version": "isj-p06-reference-window-support-v2",
                "protocol_version": "isj-window-selection-v2",
                "dataset_family": family,
                "sequence": sequence,
                "window_index": source["window_index"],
                "window_start_s": source["window_start_s"],
                "window_end_s": source["window_end_s"],
                "absolute_start_s": start_s,
                "absolute_end_s": end_s,
                "evaluation_rate_hz": reference["evaluation_rate_hz"],
                "max_reference_gap_s": reference["max_reference_gap_s"],
                "grid_count": support["grid_count"],
                "supported_grid_count": support["supported_grid_count"],
                "coverage": support["coverage"],
                "supported_span_s": support["supported_span_s"],
                "worst_bracket_gap_s": support["worst_bracket_gap_s"],
                "reference_support_pass": str(bool(support["pass"])).lower(),
                "reference_support_reason": support["reason"],
                "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
            }
        )
    sequence_counts: dict[str, dict[str, int | str]] = {}
    for row in rows:
        name = f"{row['dataset_family']}/{row['sequence']}"
        values = sequence_counts.setdefault(
            name, {"total": 0, "pass": 0, "fail": 0, "decision": ""}
        )
        values["total"] = int(values["total"]) + 1
        bucket = "pass" if row["reference_support_pass"] == "true" else "fail"
        values[bucket] = int(values[bucket]) + 1
    for values in sequence_counts.values():
        values["decision"] = (
            "RETAIN_SUPPORTED_WINDOWS"
            if int(values["pass"]) > 0
            else "EXCLUDE_SEQUENCE_FROM_REFERENCE_BEARING_FINAL_SELECTION"
        )
    return rows, {
        "schema_version": "isj-p06-reference-window-support-summary-v2",
        "protocol_version": "isj-window-selection-v2",
        "validity_contract": "G0_REFERENCE_ONLY_POSES_GE30_COVERAGE_GE0P70_SPAN_GE10S",
        "window_count": len(rows),
        "pass_count": sum(row["reference_support_pass"] == "true" for row in rows),
        "fail_count": sum(row["reference_support_pass"] == "false" for row in rows),
        "sequence_counts": sequence_counts,
        "supersedes_interpretation_only": str(V1_SUMMARY.relative_to(ROOT)),
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("reference support v2 audit is immutable once written")
    rows, summary = build_rows()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_REFERENCE_SUPPORT_V2 rows={summary['window_count']} "
        f"pass={summary['pass_count']} fail={summary['fail_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
