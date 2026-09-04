#!/usr/bin/env python3
"""Build P06 time mappings while honoring the reference-exclusion gate.

The v1 mapper opens every registered AFRL bag, including the already excluded
8 GB ``cave_gennie`` input. This version keeps the v1 row semantics for the
17 reference-eligible sequences and records the excluded sequence explicitly.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P06 = BUNDLE / "p06"
OUTPUT = P06 / "window_time_mapping_v2.csv"
SUMMARY = P06 / "window_time_mapping_v2.json"
EXCLUDED_KEYS = {("afrl", "cave_gennie")}
EXPECTED_BOUNDARY = "KLT_AND_IMAGE_QUALITY_ONLY_NO_LEARNED_OR_VINS_OUTCOME"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts import build_p06_window_time_mapping as v1


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def filter_support_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        row
        for row in rows
        if (row.get("dataset_family", ""), row.get("sequence", ""))
        not in EXCLUDED_KEYS
    ]


def build_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    original_read_csv = v1.read_csv

    def read_csv(path: Path) -> list[dict[str, str]]:
        rows = original_read_csv(path)
        if path.resolve() == v1.SUPPORT.resolve():
            return filter_support_rows(rows)
        return rows

    v1.read_csv = read_csv
    try:
        rows, summary = v1.build_rows()
    finally:
        v1.read_csv = original_read_csv
    result = dict(summary)
    result.update(
        {
            "schema_version": "isj-p06-window-time-mapping-summary-v2",
            "source_builder": {
                "path": "scripts/build_p06_window_time_mapping_v2.py",
                "sha256": sha256(Path(__file__)),
            },
            "excluded_sequences": ["afrl/cave_gennie"],
            "excluded_sequence_count": len(EXCLUDED_KEYS),
            "reference_eligible_sequence_count": 17,
            "outcome_boundary": EXPECTED_BOUNDARY,
            "learned_outcome_read": False,
            "trajectory_outcome_read": False,
        }
    )
    return rows, result


def main() -> int:
    if OUTPUT.exists() or SUMMARY.exists():
        raise FileExistsError("window time mapping v2 is immutable once written")
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
        f"P06_WINDOW_TIME_MAPPING_V2 rows={summary['row_count']} "
        f"pass={summary['pass_count']} excluded={summary['excluded_sequence_count']}"
    )
    return 0 if summary["fail_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
