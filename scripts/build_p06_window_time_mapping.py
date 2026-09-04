#!/usr/bin/env python3
"""Freeze P06 image-relative windows into dataset-runner coordinates."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import rosbag

try:
    from scripts.validate_p06_final_artifacts import index, read_csv
except ModuleNotFoundError:
    from validate_p06_final_artifacts import index, read_csv


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
SUPPORT = P06 / "reference_window_support_audit_v2.csv"
ELIGIBILITY = BUNDLE / "data_eligibility_manifest.csv"
OUTPUT = P06 / "window_time_mapping_v1.csv"
SUMMARY = P06 / "window_time_mapping_v1.json"
FIELDS = (
    "schema_version",
    "protocol_version",
    "dataset_family",
    "sequence",
    "window_index",
    "window_start_s",
    "window_end_s",
    "absolute_image_start_s",
    "absolute_image_end_s",
    "runner_interface",
    "runner_start",
    "runner_end_or_duration",
    "runner_unit",
    "raw_bag_start_s",
    "raw_bag_end_s",
    "mapping_pass",
    "outcome_boundary",
)


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    support = read_csv(SUPPORT)
    eligibility = index(read_csv(ELIGIBILITY))
    bag_bounds: dict[tuple[str, str], tuple[float, float]] = {}
    rows: list[dict[str, object]] = []
    for source in support:
        family = source["dataset_family"]
        sequence = source["sequence"]
        key = (family, sequence)
        relative_start = float(source["window_start_s"])
        relative_end = float(source["window_end_s"])
        absolute_start = float(source["absolute_start_s"])
        absolute_end = float(source["absolute_end_s"])
        raw_start = ""
        raw_end = ""
        if family.startswith("aqualoc_"):
            runner_interface = "AQUALOC_FRAME_INTERVAL_HALF_OPEN"
            runner_start: int | float = int(round(relative_start * 20.0))
            runner_end_or_duration: int | float = int(round(relative_end * 20.0))
            unit = "frame"
            mapping_pass = (
                runner_end_or_duration - runner_start == 900
                and runner_start >= 0
            )
        else:
            if key not in bag_bounds:
                raw_path = ROOT / eligibility[key]["raw_input_path"]
                with rosbag.Bag(str(raw_path)) as bag:
                    bag_bounds[key] = (bag.get_start_time(), bag.get_end_time())
            raw_start_value, raw_end_value = bag_bounds[key]
            runner_interface = "ROS_BAG_START_OFFSET_AND_DURATION"
            runner_start = absolute_start - raw_start_value
            runner_end_or_duration = relative_end - relative_start
            unit = "second"
            raw_start = raw_start_value
            raw_end = raw_end_value
            mapping_pass = (
                runner_start >= -1e-6
                and absolute_end <= raw_end_value + 1e-6
                and abs(float(runner_end_or_duration) - 45.0) <= 1e-9
            )
        rows.append(
            {
                "schema_version": "isj-p06-window-time-mapping-v1",
                "protocol_version": "isj-window-selection-v2",
                "dataset_family": family,
                "sequence": sequence,
                "window_index": source["window_index"],
                "window_start_s": source["window_start_s"],
                "window_end_s": source["window_end_s"],
                "absolute_image_start_s": absolute_start,
                "absolute_image_end_s": absolute_end,
                "runner_interface": runner_interface,
                "runner_start": runner_start,
                "runner_end_or_duration": runner_end_or_duration,
                "runner_unit": unit,
                "raw_bag_start_s": raw_start,
                "raw_bag_end_s": raw_end,
                "mapping_pass": str(bool(mapping_pass)).lower(),
                "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
            }
        )
    return rows, {
        "schema_version": "isj-p06-window-time-mapping-summary-v1",
        "protocol_version": "isj-window-selection-v2",
        "row_count": len(rows),
        "pass_count": sum(row["mapping_pass"] == "true" for row in rows),
        "fail_count": sum(row["mapping_pass"] == "false" for row in rows),
        "interfaces": sorted({str(row["runner_interface"]) for row in rows}),
        "outcome_boundary": "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME",
        "learned_outcome_read": False,
        "trajectory_outcome_read": False,
    }


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("window time mapping is immutable once written")
    rows, summary = build_rows()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    SUMMARY.write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_WINDOW_TIME_MAPPING rows={summary['row_count']} "
        f"pass={summary['pass_count']} fail={summary['fail_count']}"
    )
    return 0 if summary["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
