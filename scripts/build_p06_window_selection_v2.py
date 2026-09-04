#!/usr/bin/env python3
"""Build the P06 development recalibration and threshold-retention audit."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

try:
    from scripts.p02_window_selection import TAU_LOW, TAU_NORMAL, score_metric_rows
except ModuleNotFoundError:  # direct ``python scripts/build_p06_window_selection_v2.py`` entry
    from p02_window_selection import TAU_LOW, TAU_NORMAL, score_metric_rows


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P02 = BUNDLE / "p02/development_screening"
P06 = BUNDLE / "p06"
NEW = P06 / "development_calibration_v2"
FIELDS = (
    "grid_coverage",
    "dropout_ratio",
    "flat_region_ratio",
    "degradation_score",
)


@dataclass(frozen=True)
class Fixture:
    role: str
    fixture_id: str
    dataset_family: str
    sequence: str
    old_name: str
    input_rate_hz: float
    expected_rows: int
    expected_stratum: str


FIXTURES = (
    Fixture("primary", "aqualoc_a06_2210_2460", "aqualoc_archaeology", "A06", "metrics.csv", 20.0, 251, "low"),
    Fixture("primary", "aqualoc_h06_2280_2490", "aqualoc_harbor", "H06", "metrics.csv", 20.0, 211, "normal"),
    Fixture("sensitivity", "aqualoc_h07_1660_1720", "aqualoc_harbor", "H07", "metrics.csv", 20.0, 61, "unclassified"),
    Fixture("primary", "afrl_cemetery_fr_005_410", "afrl", "cemetery_fr", "metrics_r2.csv", 3.0, 406, "low"),
    Fixture("primary", "afrl_cemetery_fl_080_319", "afrl", "cemetery_fl", "metrics.csv", 3.0, 240, "low"),
    Fixture("sensitivity", "tank_short_000_299", "tank", "short_test", "metrics.csv", 20.0, 300, "normal"),
    Fixture("sensitivity", "uvvid_cannon_000_179", "uvvid", "cannon_bottom", "metrics_r2.csv", 2.0, 180, "low"),
)


def main() -> int:
    output_csv = P06 / "development_score_audit_v2.csv"
    output_json = P06 / "development_calibration_v2.json"
    equivalence_path = P06 / "development_equivalence/aqualoc_a06_2210_2460/equivalence_audit.json"
    equivalence = json.loads(equivalence_path.read_text(encoding="utf-8"))
    rows = [audit_fixture(fixture) for fixture in FIXTURES]
    write_csv(output_csv, rows)

    all_pass = equivalence.get("status") == "PASS" and all(row["status"] == "PASS" for row in rows)
    payload = {
        "schema_version": "isj-window-selection-v2-development-calibration-v1",
        "status": "PASS" if all_pass else "FAIL",
        "protocol_version": "isj-window-selection-v2",
        "threshold_decision": "RETAIN_V1_THRESHOLDS" if all_pass else "REVISE_THRESHOLDS",
        "tau_low": TAU_LOW,
        "tau_normal": TAU_NORMAL,
        "fixture_count": len(rows),
        "exact_required_metric_fixture_count": sum(
            row["required_metrics_exact"] == "true" for row in rows
        ),
        "classification_match_fixture_count": sum(
            row["classification_match"] == "true" for row in rows
        ),
        "equivalence_audit": {
            "path": relative(equivalence_path),
            "sha256": sha256_file(equivalence_path),
            "status": equivalence.get("status"),
            "paired_rows": equivalence.get("paired_rows"),
            "max_abs_diff": equivalence.get("max_abs_diff"),
        },
        "development_score_audit": {
            "path": relative(output_csv),
            "sha256": sha256_file(output_csv),
        },
        "code": [
            file_record(ROOT / "scripts/p02_window_selection.py"),
            file_record(ROOT / "scripts/p06_window_selection_v2.py"),
            file_record(ROOT / "scripts/build_p06_window_selection_v2.py"),
            file_record(ROOT / "uw_frontend/evaluation/run_frontend_eval.py"),
            file_record(ROOT / "uw_frontend/ros/export_vins_features.py"),
            file_record(ROOT / "uw_frontend/configs/klt_frontend.yaml"),
        ],
        "fixtures": rows,
    }
    output_json.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        f"P06_V2_CALIBRATION_{payload['status']} fixtures={len(rows)} "
        f"threshold_decision={payload['threshold_decision']}"
    )
    return 0 if all_pass else 1


def audit_fixture(fixture: Fixture) -> dict[str, object]:
    old_path = P02 / fixture.fixture_id / fixture.old_name
    new_path = NEW / fixture.fixture_id / "metrics.csv"
    old_rows = read_rows(old_path)
    new_rows = read_rows(new_path)
    max_abs_diff = {field: 0.0 for field in FIELDS}
    if len(old_rows) == len(new_rows):
        for old, new in zip(old_rows, new_rows):
            for field in FIELDS:
                max_abs_diff[field] = max(
                    max_abs_diff[field],
                    abs(float(old[field]) - float(new[field])),
                )
    else:
        max_abs_diff = {field: float("inf") for field in FIELDS}

    old_score = score_metric_rows(old_rows)
    new_score = score_metric_rows(new_rows)
    old_stratum = absolute_stratum(old_score.score)
    new_stratum = absolute_stratum(new_score.score)
    metrics_exact = len(old_rows) == len(new_rows) and all(
        difference == 0.0 for difference in max_abs_diff.values()
    )
    classification_match = (
        old_stratum == new_stratum == fixture.expected_stratum
    )
    row_count_pass = len(new_rows) == fixture.expected_rows
    status = "PASS" if metrics_exact and classification_match and row_count_pass else "FAIL"
    return {
        "status": status,
        "fixture_role": fixture.role,
        "fixture_id": fixture.fixture_id,
        "dataset_family": fixture.dataset_family,
        "sequence": fixture.sequence,
        "old_metrics_path": relative(old_path),
        "new_metrics_path": relative(new_path),
        "old_sha256": sha256_file(old_path),
        "new_sha256": sha256_file(new_path),
        "old_row_count": len(old_rows),
        "new_row_count": len(new_rows),
        "expected_row_count": fixture.expected_rows,
        "input_rate_hz": fixture.input_rate_hz,
        "old_score": old_score.score,
        "new_score": new_score.score,
        "score_delta": new_score.score - old_score.score,
        "old_stratum": old_stratum,
        "new_stratum": new_stratum,
        "expected_stratum": fixture.expected_stratum,
        "required_metrics_exact": str(metrics_exact).lower(),
        "classification_match": str(classification_match).lower(),
        **{f"max_abs_diff_{field}": value for field, value in max_abs_diff.items()},
        "grid_coverage_p50": new_score.grid_coverage_p50,
        "dropout_ratio_p50": new_score.dropout_ratio_p50,
        "flat_region_ratio_p50": new_score.flat_region_ratio_p50,
        "degradation_score_p50": new_score.degradation_score_p50,
        "frame_score_q25": new_score.frame_score_p25,
        "window_score_q50": new_score.frame_score_p50,
        "frame_score_q75": new_score.frame_score_p75,
    }


def absolute_stratum(score: float) -> str:
    if score >= TAU_LOW:
        return "low"
    if score <= TAU_NORMAL:
        return "normal"
    return "unclassified"


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def file_record(path: Path) -> dict[str, object]:
    return {
        "path": relative(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
