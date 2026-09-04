#!/usr/bin/env python3
"""Validate P06 count identity and selected-window reference support."""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import math
from pathlib import Path
from typing import Any

try:
    from scripts.validate_p06_screening_closeout import resolve_screening_dir
except ModuleNotFoundError:
    from validate_p06_screening_closeout import resolve_screening_dir


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
REFERENCES = BUNDLE / "reference_audit.csv"
PROGRESS = BUNDLE / "p06/screening_progress.json"
DATASET_MANIFEST = BUNDLE / "dataset_manifest.csv"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"invalid CSV header: {path}")
        rows = list(reader)
    if any(None in row for row in rows):
        raise ValueError(f"ragged CSV: {path}")
    return rows


def index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    result: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        key = (row.get("dataset_family", ""), row.get("sequence", ""))
        if not all(key) or key in result:
            raise ValueError(f"invalid or duplicate sequence identity: {key}")
        result[key] = row
    return result


def afrl_stamp(value: str, sequence: str) -> float:
    raw = float(value)
    if sequence != "cemetery" or raw > 1e9:
        return raw
    digits = "".join(character for character in value if character.isdigit())
    return float(f"{digits[:10]}.{digits[10:]}") if len(digits) > 10 else raw


def load_reference_stamps(family: str, sequence: str, path: Path) -> list[float]:
    values: list[float] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 8:
            continue
        try:
            if family.startswith("aqualoc_"):
                value = float(parts[0]) / 20.0
            elif family == "afrl":
                value = afrl_stamp(parts[0], sequence)
            else:
                value = float(parts[0])
        except ValueError:
            continue
        if math.isfinite(value):
            values.append(value)
    return sorted(set(values))


def reference_support(
    stamps: list[float],
    start_s: float,
    end_s: float,
    evaluation_rate_hz: float,
    max_reference_gap_s: float,
) -> dict[str, Any]:
    if len(stamps) < 2 or not start_s < end_s:
        return {"pass": False, "reason": "invalid_reference_or_window"}
    step = 1.0 / evaluation_rate_hz
    count = int(math.floor((end_s - start_s) * evaluation_rate_hz + 1e-9)) + 1
    grid = [start_s + index * step for index in range(count)]
    supported = 0
    worst_bracket_gap = 0.0
    tolerance = 1e-6
    for value in grid:
        position = bisect.bisect_left(stamps, value)
        if position < len(stamps) and abs(stamps[position] - value) <= tolerance:
            supported += 1
            continue
        if position == 0 or position == len(stamps):
            continue
        left = stamps[position - 1]
        right = stamps[position]
        gap = right - left
        worst_bracket_gap = max(worst_bracket_gap, gap)
        if gap <= max_reference_gap_s + tolerance:
            supported += 1
    coverage = supported / len(grid) if grid else 0.0
    return {
        "pass": supported >= 30 and math.isclose(coverage, 1.0, abs_tol=1e-12),
        "grid_count": len(grid),
        "supported_grid_count": supported,
        "coverage": coverage,
        "worst_bracket_gap_s": worst_bracket_gap,
        "max_reference_gap_s": max_reference_gap_s,
    }


def metrics_origin(family: str, sequence: str) -> tuple[float, list[dict[str, str]]]:
    run_dir, pointer_issues = resolve_screening_dir(family, sequence)
    if pointer_issues:
        raise ValueError(f"screening pointer invalid for {family}/{sequence}: {pointer_issues}")
    rows = read_csv(run_dir / "metrics.csv")
    timestamps = [
        float(row["timestamp"])
        for row in rows
        if row.get("timestamp") not in {None, "", "n/a", "nan"}
    ]
    return (min(timestamps) if timestamps else 0.0), rows


def build_report() -> dict[str, Any]:
    if not PROGRESS.is_file() or not DATASET_MANIFEST.is_file():
        return {
            "schema_version": "isj-p06-final-artifact-validation-v1",
            "status": "IN_PROGRESS",
            "issues": ["missing_final_p06_artifacts"],
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    progress = json.loads(PROGRESS.read_text(encoding="utf-8"))
    capacity = index(read_csv(CAPACITY))
    eligibility = index(read_csv(ELIGIBILITY))
    references = index(read_csv(REFERENCES))
    selected = read_csv(DATASET_MANIFEST)
    issues: list[str] = []
    if len(selected) != 20:
        issues.append(f"selected_window_count:{len(selected)}")
    count_audits: dict[str, dict[str, int]] = {}
    for audit in progress.get("sequence_audits", []):
        key = (str(audit.get("dataset_family", "")), str(audit.get("sequence", "")))
        spec = capacity.get(key)
        if spec is None:
            issues.append(f"count_audit_not_registered:{key[0]}/{key[1]}")
            continue
        actual = {
            "gross": int(audit.get("gross_windows_actual", -1)),
            "history": int(audit.get("history_excluded_actual", -1)),
            "available": int(audit.get("available_windows_actual", -1)),
        }
        registered = {
            "gross": int(spec["gross_nonoverlap_windows"]),
            "history": int(spec["history_overlap_windows"]),
            "available": int(spec["available_candidate_windows"]),
        }
        count_audits[f"{key[0]}/{key[1]}"] = {**actual, **{f"registered_{k}": v for k, v in registered.items()}}
        for name in ("gross", "history", "available"):
            if actual[name] != registered[name]:
                issues.append(f"count_mismatch:{key[0]}/{key[1]}:{name}")
    expected = {
        key
        for key, row in capacity.items()
        if row.get("low_normal_sequence_capacity_status") == "CAPACITY_CANDIDATE"
    }
    audited = {
        tuple(name.split("/", 1))
        for name in count_audits
    }
    for family, sequence in sorted(expected - audited):
        issues.append(f"missing_sequence_count_audit:{family}/{sequence}")

    support_rows: list[dict[str, Any]] = []
    origins: dict[tuple[str, str], float] = {}
    reference_stamps: dict[tuple[str, str], list[float]] = {}
    for row in selected:
        family = row.get("dataset_family", "")
        sequence = row.get("sequence", "")
        key = (family, sequence)
        window_id = row.get("window_id", "")
        eligibility_row = eligibility.get(key)
        reference_row = references.get(key)
        if eligibility_row is None or reference_row is None:
            issues.append(f"selected_reference_not_registered:{window_id}")
            continue
        if reference_row.get("reference_exists") != "true":
            issues.append(f"selected_reference_missing:{window_id}")
        if reference_row.get("calibration_status") != "PASS_ALL_PRESENT":
            issues.append(f"selected_calibration_fail:{window_id}")
        try:
            if int(float(row.get("input_frame_count", "0"))) < 200:
                issues.append(f"selected_input_support_fail:{window_id}")
        except ValueError:
            issues.append(f"selected_input_frame_count_invalid:{window_id}")
        if key not in origins:
            origins[key], _ = metrics_origin(family, sequence)
        if key not in reference_stamps:
            path = ROOT / eligibility_row["reference_path"]
            reference_stamps[key] = load_reference_stamps(family, sequence, path)
        start_s = origins[key] + float(row["window_start_s"])
        end_s = origins[key] + float(row["window_end_s"])
        support = reference_support(
            reference_stamps[key],
            start_s,
            end_s,
            float(reference_row["evaluation_rate_hz"]),
            float(reference_row["max_reference_gap_s"]),
        )
        support_rows.append(
            {
                "window_id": window_id,
                "dataset_family": family,
                "sequence": sequence,
                "absolute_start_s": start_s,
                "absolute_end_s": end_s,
                **support,
            }
        )
        if not support.get("pass"):
            issues.append(f"selected_reference_support_fail:{window_id}")
    return {
        "schema_version": "isj-p06-final-artifact-validation-v1",
        "status": "PASS" if not issues and progress.get("status") == "PASS" else "REVISE",
        "selected_window_count": len(selected),
        "sequence_count_audits": count_audits,
        "selected_reference_support": support_rows,
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
