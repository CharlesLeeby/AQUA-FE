#!/usr/bin/env python3
"""Build the final P06 mapping with reference exclusion and start clamping."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
OUTPUT = P06 / "window_time_mapping_v3.csv"
SUMMARY = P06 / "window_time_mapping_v3.json"
CLAMP_TOLERANCE_S = 0.25

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_p06_window_time_mapping as v1
from scripts import build_p06_window_time_mapping_v2 as v2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_runner_start(
    source: dict[str, object],
) -> tuple[dict[str, object], dict[str, object] | None]:
    row = dict(source)
    if row.get("runner_interface") != "ROS_BAG_START_OFFSET_AND_DURATION":
        return row, None
    start = float(row["runner_start"])
    if not -CLAMP_TOLERANCE_S <= start < 0.0:
        return row, None
    duration = float(row["runner_end_or_duration"])
    absolute_end = float(row["absolute_image_end_s"])
    raw_end = float(row["raw_bag_end_s"])
    row["runner_start"] = 0.0
    row["mapping_pass"] = str(
        abs(duration - 45.0) <= 1e-9 and absolute_end <= raw_end + CLAMP_TOLERANCE_S
    ).lower()
    return row, {
        "dataset_family": row["dataset_family"],
        "sequence": row["sequence"],
        "window_index": row["window_index"],
        "original_runner_start": start,
        "clamped_runner_start": 0.0,
        "tolerance_s": CLAMP_TOLERANCE_S,
    }


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    source_rows, source_summary = v2.build_rows()
    rows: list[dict[str, object]] = []
    adjustments: list[dict[str, object]] = []
    for source in source_rows:
        row, adjustment = normalize_runner_start(source)
        rows.append(row)
        if adjustment is not None:
            adjustments.append(adjustment)
    summary = dict(source_summary)
    summary.update(
        {
            "schema_version": "isj-p06-window-time-mapping-summary-v3",
            "row_count": len(rows),
            "pass_count": sum(row["mapping_pass"] == "true" for row in rows),
            "fail_count": sum(row["mapping_pass"] == "false" for row in rows),
            "source_builder": {
                "path": "scripts/build_p06_window_time_mapping_v3.py",
                "sha256": sha256(Path(__file__)),
            },
            "supersedes": {
                "summary_path": v2.SUMMARY.resolve().relative_to(ROOT).as_posix(),
                "summary_sha256": sha256(v2.SUMMARY),
                "mapping_path": v2.OUTPUT.resolve().relative_to(ROOT).as_posix(),
                "mapping_sha256": sha256(v2.OUTPUT),
            },
            "runner_start_clamp_tolerance_s": CLAMP_TOLERANCE_S,
            "runner_start_adjustments": adjustments,
            "runner_start_adjustment_count": len(adjustments),
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    )
    return rows, summary


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("window time mapping v3 is immutable once written")
    rows, summary = build_rows()
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=v1.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary["output"] = {
        "path": OUTPUT.resolve().relative_to(ROOT).as_posix(),
        "sha256": sha256(OUTPUT),
        "size_bytes": OUTPUT.stat().st_size,
    }
    SUMMARY.write_text(
        json.dumps(summary, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"P06_WINDOW_TIME_MAPPING_V3 rows={summary['row_count']} "
        f"pass={summary['pass_count']} adjusted={summary['runner_start_adjustment_count']}"
    )
    return 0 if summary["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
