#!/usr/bin/env python3
"""Freeze per-window reference support before P06 score-based final selection."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import rosbag

try:
    from scripts.validate_p06_final_artifacts import (
        index,
        load_reference_stamps,
        read_csv,
        reference_support,
    )
    from scripts.validate_p06_screening_closeout import resolve_screening_dir
except ModuleNotFoundError:
    from validate_p06_final_artifacts import (
        index,
        load_reference_stamps,
        read_csv,
        reference_support,
    )
    from validate_p06_screening_closeout import resolve_screening_dir


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
CAPACITY = BUNDLE / "p02/candidate_capacity_audit.csv"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
REFERENCES = BUNDLE / "reference_audit.csv"
OUTPUT = P06 / "reference_window_support_audit.csv"
SUMMARY = P06 / "reference_window_support_summary.json"
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
    "worst_bracket_gap_s",
    "reference_support_pass",
    "outcome_boundary",
)


def first_image_stamp(family: str, sequence: str, raw_path: Path) -> float:
    run_dir, pointer_issues = resolve_screening_dir(family, sequence)
    metrics_path = run_dir / "metrics.csv"
    if not metrics_path.is_file():
        work_metrics = (
            Path("/mnt/data/AQUA-FE_WS/p06_screening_work")
            / family
            / sequence
            / "frontend_metrics.csv"
        )
        if family == "afrl" and sequence == "cave_gennie":
            work_metrics = work_metrics.parent / "attempt02" / work_metrics.name
        metrics_path = work_metrics
    if metrics_path.is_file():
        timestamps = [
            float(row["timestamp"])
            for row in read_csv(metrics_path)
            if row.get("timestamp") not in {None, "", "n/a", "nan"}
        ]
        if timestamps:
            return min(timestamps)
    if pointer_issues and sequence == "cave_gennie":
        # A running replacement has no pointer yet; its partial metrics above
        # are the only permitted active-attempt identity source.
        raise ValueError(f"missing cave attempt metrics: {pointer_issues}")
    topic = {
        "cave_gennie": "/slave1/image_raw/compressed",
        "bus_outside": "/slave1/image_raw/compressed",
        "cemetery": "/cam_fl/image_raw/compressed",
    }.get(sequence)
    if topic is None:
        raise ValueError(f"no registered image topic for {family}/{sequence}")
    with rosbag.Bag(str(raw_path)) as bag:
        for _topic, message, bag_time in bag.read_messages(topics=[topic]):
            stamp = message.header.stamp.to_sec()
            return stamp if stamp > 0.0 else bag_time.to_sec()
    raise ValueError(f"no image messages for {family}/{sequence}")


def build_rows() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    capacity = index(read_csv(CAPACITY))
    eligibility = index(read_csv(ELIGIBILITY))
    references = index(read_csv(REFERENCES))
    rows: list[dict[str, Any]] = []
    origins: dict[tuple[str, str], float] = {}
    for key, spec in sorted(capacity.items()):
        if spec.get("low_normal_sequence_capacity_status") != "CAPACITY_CANDIDATE":
            continue
        family, sequence = key
        eligible = eligibility[key]
        reference = references[key]
        origin = 0.0
        if not family.startswith("aqualoc_"):
            origin = first_image_stamp(family, sequence, ROOT / eligible["raw_input_path"])
        origins[key] = origin
        stamps = load_reference_stamps(
            family, sequence, ROOT / eligible["reference_path"]
        )
        for window_index in range(int(spec["gross_nonoverlap_windows"])):
            relative_start = 45.0 * window_index
            relative_end = relative_start + 45.0
            support = reference_support(
                stamps,
                origin + relative_start,
                origin + relative_end,
                float(reference["evaluation_rate_hz"]),
                float(reference["max_reference_gap_s"]),
            )
            rows.append(
                {
                    "schema_version": "isj-p06-reference-window-support-v1",
                    "protocol_version": "isj-window-selection-v2",
                    "dataset_family": family,
                    "sequence": sequence,
                    "window_index": window_index,
                    "window_start_s": relative_start,
                    "window_end_s": relative_end,
                    "absolute_start_s": origin + relative_start,
                    "absolute_end_s": origin + relative_end,
                    "evaluation_rate_hz": reference["evaluation_rate_hz"],
                    "max_reference_gap_s": reference["max_reference_gap_s"],
                    "grid_count": support.get("grid_count", 0),
                    "supported_grid_count": support.get("supported_grid_count", 0),
                    "coverage": support.get("coverage", 0.0),
                    "worst_bracket_gap_s": support.get("worst_bracket_gap_s", ""),
                    "reference_support_pass": str(bool(support.get("pass"))).lower(),
                    "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
                }
            )
    by_sequence: dict[str, dict[str, int]] = {}
    for row in rows:
        name = f"{row['dataset_family']}/{row['sequence']}"
        summary = by_sequence.setdefault(name, {"total": 0, "pass": 0, "fail": 0})
        summary["total"] += 1
        summary["pass" if row["reference_support_pass"] == "true" else "fail"] += 1
    return rows, {
        "schema_version": "isj-p06-reference-window-support-summary-v1",
        "protocol_version": "isj-window-selection-v2",
        "window_count": len(rows),
        "pass_count": sum(row["reference_support_pass"] == "true" for row in rows),
        "fail_count": sum(row["reference_support_pass"] == "false" for row in rows),
        "sequence_counts": by_sequence,
        "sequence_origins": {f"{key[0]}/{key[1]}": value for key, value in origins.items()},
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("reference support audit is immutable once written")
    rows, summary = build_rows()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_REFERENCE_SUPPORT rows={summary['window_count']} "
        f"pass={summary['pass_count']} fail={summary['fail_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
