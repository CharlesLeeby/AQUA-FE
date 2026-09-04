#!/usr/bin/env python3
"""Audit direct-runner and ROS-adapter P06 screening metrics frame by frame."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path


METRICS = (
    "grid_coverage",
    "dropout_ratio",
    "flat_region_ratio",
    "degradation_score",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-csv", required=True)
    parser.add_argument("--ros-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-json", required=True)
    parser.add_argument("--tolerance", type=float, default=1e-12)
    args = parser.parse_args()

    direct_path = Path(args.direct_csv).resolve()
    ros_path = Path(args.ros_csv).resolve()
    output_csv = Path(args.output_csv).resolve()
    output_json = Path(args.output_json).resolve()
    direct_rows = read_rows(direct_path)
    ros_rows = read_rows(ros_path)
    result, detail_rows = audit_rows(
        direct_rows,
        ros_rows,
        tolerance=float(args.tolerance),
    )
    result.update(
        {
            "schema_version": "isj-p06-screening-equivalence-v1",
            "direct_csv": file_record(direct_path),
            "ros_csv": file_record(ros_path),
            "audit_script": file_record(Path(__file__).resolve()),
        }
    )
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    write_details(output_csv, detail_rows)
    output_json.write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"P06_EQUIVALENCE_{result['status']} rows={result['paired_rows']} "
        f"index_mismatches={result['normalized_index_mismatches']} "
        f"max_abs_diff={max(result['max_abs_diff'].values(), default=float('nan'))}"
    )
    return 0 if result["status"] == "PASS" else 1


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"frame_index", *METRICS}
        missing = sorted(required - fields)
        if missing:
            raise ValueError(f"{path} missing required columns: {missing}")
        return list(reader)


def audit_rows(
    direct_rows: list[dict[str, str]],
    ros_rows: list[dict[str, str]],
    *,
    tolerance: float,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    direct_start = parse_index(direct_rows[0]["frame_index"]) if direct_rows else None
    ros_start = parse_index(ros_rows[0]["frame_index"]) if ros_rows else None
    paired = min(len(direct_rows), len(ros_rows))
    max_abs_diff = {metric: 0.0 for metric in METRICS}
    mismatch_count = {metric: 0 for metric in METRICS}
    range_violations = {metric: 0 for metric in METRICS}
    normalized_index_mismatches = 0
    detail_rows: list[dict[str, object]] = []

    for position, (direct, ros) in enumerate(zip(direct_rows, ros_rows)):
        direct_index = parse_index(direct["frame_index"])
        ros_index = parse_index(ros["frame_index"])
        direct_normalized = direct_index - int(direct_start)
        ros_normalized = ros_index - int(ros_start)
        index_match = direct_normalized == ros_normalized
        if not index_match:
            normalized_index_mismatches += 1
        detail: dict[str, object] = {
            "position": position,
            "direct_frame_index": direct_index,
            "ros_frame_index": ros_index,
            "direct_normalized_index": direct_normalized,
            "ros_normalized_index": ros_normalized,
            "normalized_index_match": str(index_match).lower(),
        }
        for metric in METRICS:
            direct_value = float(direct[metric])
            ros_value = float(ros[metric])
            direct_in_range = math.isfinite(direct_value) and 0.0 <= direct_value <= 1.0
            ros_in_range = math.isfinite(ros_value) and 0.0 <= ros_value <= 1.0
            if not direct_in_range:
                range_violations[metric] += 1
            if not ros_in_range:
                range_violations[metric] += 1
            difference = (
                abs(direct_value - ros_value)
                if math.isfinite(direct_value) and math.isfinite(ros_value)
                else float("inf")
            )
            max_abs_diff[metric] = max(max_abs_diff[metric], difference)
            if difference > tolerance:
                mismatch_count[metric] += 1
            detail[f"direct_{metric}"] = direct_value
            detail[f"ros_{metric}"] = ros_value
            detail[f"abs_diff_{metric}"] = difference
        detail_rows.append(detail)

    pass_checks = [
        len(direct_rows) > 0,
        len(direct_rows) == len(ros_rows),
        normalized_index_mismatches == 0,
        all(count == 0 for count in mismatch_count.values()),
        all(count == 0 for count in range_violations.values()),
    ]
    return (
        {
            "status": "PASS" if all(pass_checks) else "FAIL",
            "tolerance": float(tolerance),
            "required_metrics": list(METRICS),
            "direct_rows": len(direct_rows),
            "ros_rows": len(ros_rows),
            "paired_rows": paired,
            "direct_start_index": direct_start,
            "ros_start_index": ros_start,
            "normalized_index_mismatches": normalized_index_mismatches,
            "max_abs_diff": max_abs_diff,
            "metric_mismatch_count": mismatch_count,
            "range_violation_count": range_violations,
        },
        detail_rows,
    )


def parse_index(value: str) -> int:
    number = float(value)
    rounded = int(round(number))
    if not math.isfinite(number) or abs(number - rounded) > 1e-9:
        raise ValueError(f"frame_index is not an integer: {value!r}")
    return rounded


def write_details(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames = [
        "position",
        "direct_frame_index",
        "ros_frame_index",
        "direct_normalized_index",
        "ros_normalized_index",
        "normalized_index_match",
    ]
    for metric in METRICS:
        fieldnames.extend((f"direct_{metric}", f"ros_{metric}", f"abs_diff_{metric}"))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
