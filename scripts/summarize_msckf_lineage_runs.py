#!/usr/bin/env python3
"""Summarize MSCKF lineage shadow and compression runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Iterable


WINDOW_PATTERN = re.compile(r"a\d+_\d+_\d+", re.IGNORECASE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", action="append", required=True)
    parser.add_argument("--output-runs-csv", required=True)
    parser.add_argument("--output-lineages-csv", required=True)
    parser.add_argument("--output-json", required=True)
    return parser.parse_args()


def key_values(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value
    return result


def optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def optional_int(value: str | None) -> int | None:
    return None if value is None or value == "" else int(value)


def window_name(feature_bag: str) -> str:
    for component in reversed(Path(feature_bag).parts):
        if WINDOW_PATTERN.fullmatch(component):
            return component.lower()
    return "unknown"


def read_csv_checked(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="ascii") as handle:
        raw_rows = list(csv.reader(handle))
    if not raw_rows:
        raise ValueError(f"empty CSV: {path}")
    expected_width = len(raw_rows[0])
    bad_rows = [index + 1 for index, row in enumerate(raw_rows) if len(row) != expected_width]
    if bad_rows:
        raise ValueError(f"ragged CSV rows in {path}: {bad_rows[:10]}")
    with path.open(newline="", encoding="ascii") as handle:
        return list(csv.DictReader(handle))


def sum_float(rows: Iterable[dict[str, str]], field: str) -> float:
    return sum(float(row[field]) for row in rows if row.get(field, "") != "")


def summarize_run(run_dir: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    manifest = key_values(run_dir / "run_manifest.txt")
    metrics = key_values(run_dir / "metrics.txt")
    shadow_path = Path(manifest.get("lineage_shadow_path", run_dir / "lineage_shadow.csv"))
    stage_path = Path(
        manifest.get("lineage_shadow_stage_path", str(shadow_path) + ".stages.csv")
    )
    shadow = read_csv_checked(shadow_path)
    stages = read_csv_checked(stage_path)
    learned = [row for row in shadow if row.get("ever_learned") == "1"]
    learned_stages = [row for row in stages if row.get("ever_learned") == "1"]
    passed = [row for row in learned if row.get("chi2_pass") == "1"]
    failed = [row for row in learned if row.get("chi2_pass") == "0"]
    nis_ratios = [
        float(row["gamma"]) / float(row["chi2_threshold"])
        for row in learned
        if row.get("gamma", "") != "" and float(row["chi2_threshold"]) > 0.0
    ]
    stage_events = Counter(row["event"] for row in learned_stages)
    feature_bag = manifest.get("feature_bag", "")
    update_learned_ids = sorted(
        {int(row["external_feature_id"]) for row in learned if row["external_feature_id"]}
    )
    selected_learned_ids = sorted(
        {
            int(row["external_feature_id"])
            for row in learned_stages
            if row["external_feature_id"] and row["event"] == "selected"
        }
    )
    candidate_learned_ids = sorted(
        {
            int(row["external_feature_id"])
            for row in learned_stages
            if row["external_feature_id"]
            and row["event"] == "selection_candidate_before_clone_filter"
        }
    )
    run_row: dict[str, object] = {
        "run_dir": str(run_dir),
        "run_name": run_dir.name,
        "window": window_name(feature_bag),
        "role": manifest.get("role", ""),
        "k": int(manifest.get("learned_lineage_max_update_observations", "0")),
        "ape_rmse_m": optional_float(metrics.get("se3_ape_rmse_m")),
        "rpe_rmse_m": optional_float(metrics.get("rpe_trans_rmse_m")),
        "coverage": optional_float(metrics.get("output_coverage_ratio")),
        "solver_failures": optional_int(metrics.get("log_linear_solver_failures")),
        "failure_mentions": optional_int(metrics.get("log_failure_mentions")),
        "learned_candidate_lineage_count": len(candidate_learned_ids),
        "learned_candidate_lineage_ids": ";".join(
            str(value) for value in candidate_learned_ids
        ),
        "learned_selected_lineage_count": len(selected_learned_ids),
        "learned_selected_lineage_ids": ";".join(
            str(value) for value in selected_learned_ids
        ),
        "learned_update_lineage_count": len(update_learned_ids),
        "learned_update_lineage_ids": ";".join(
            str(value) for value in update_learned_ids
        ),
        "learned_selected_events": stage_events["selected"],
        "learned_selection_rejected": stage_events[
            "selection_rejected_insufficient_clone_observations"
        ],
        "learned_marginalization_rejected": stage_events[
            "marginalization_rejected_insufficient_measurements"
        ],
        "learned_triangulation_success": stage_events["triangulation_succeeded"]
        + stage_events["triangulation_reused"],
        "learned_triangulation_fail": stage_events["triangulation_failed"],
        "learned_update_attempts": len(learned),
        "learned_chi2_pass": len(passed),
        "learned_chi2_fail": len(failed),
        "learned_compressed_attempts": sum(
            row.get("compression_applied") == "1" for row in learned
        ),
        "learned_pass_information_trace_sum": sum_float(passed, "information_trace"),
        "learned_pass_trace_hph_sum": sum_float(passed, "trace_hph"),
        "learned_nis_ratio_median": median(nis_ratios) if nis_ratios else None,
        "learned_nis_ratio_max": max(nis_ratios) if nis_ratios else None,
        "metadata_contract_errors": sum(
            int(row["metadata_contract_errors"]) for row in shadow
        ),
        "feature_bag_sha256": manifest.get("feature_bag_sha256", ""),
        "source_tree_sha256": manifest.get("msckf_source_tree_sha256", ""),
        "runner_sha256": manifest.get("runner_sha256", ""),
    }

    per_id: dict[int, list[dict[str, str]]] = defaultdict(list)
    per_id_stages: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in learned:
        per_id[int(row["external_feature_id"])].append(row)
    for row in learned_stages:
        if row["external_feature_id"]:
            per_id_stages[int(row["external_feature_id"])].append(row)

    lineage_rows: list[dict[str, object]] = []
    for feature_id in sorted(set(per_id) | set(per_id_stages)):
        update_rows = per_id[feature_id]
        stage_rows = per_id_stages[feature_id]
        update_pass = [row for row in update_rows if row.get("chi2_pass") == "1"]
        events = Counter(row["event"] for row in stage_rows)
        lineage_rows.append(
            {
                "run_dir": str(run_dir),
                "window": run_row["window"],
                "k": run_row["k"],
                "external_feature_id": feature_id,
                "internal_feature_ids": ";".join(
                    sorted({row["feature_id"] for row in update_rows})
                ),
                "selected_events": events["selected"],
                "selection_candidate_events": events[
                    "selection_candidate_before_clone_filter"
                ],
                "selection_rejected": events[
                    "selection_rejected_insufficient_clone_observations"
                ],
                "marginalization_rejected": events[
                    "marginalization_rejected_insufficient_measurements"
                ],
                "triangulation_success": events["triangulation_succeeded"]
                + events["triangulation_reused"],
                "triangulation_fail": events["triangulation_failed"],
                "update_attempts": len(update_rows),
                "chi2_pass": len(update_pass),
                "chi2_fail": sum(row.get("chi2_pass") == "0" for row in update_rows),
                "compressed_attempts": sum(
                    row.get("compression_applied") == "1" for row in update_rows
                ),
                "maximum_lineage_observations": max(
                    (int(row["lineage_observation_count"]) for row in update_rows),
                    default=0,
                ),
                "used_measurement_counts": ";".join(
                    row["used_measurement_count"] for row in update_rows
                ),
                "pass_information_trace_sum": sum_float(
                    update_pass, "information_trace"
                ),
                "pass_trace_hph_sum": sum_float(update_pass, "trace_hph"),
                "seed_seen_pre_backend_init": int(
                    any(
                        row.get("seed_seen_pre_backend_init") == "1"
                        for row in update_rows
                    )
                ),
            }
        )
    return run_row, lineage_rows


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"no rows for {path}")
    with path.open("w", newline="", encoding="ascii") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    manifests: list[Path] = []
    for root_value in args.run_root:
        root = Path(root_value).resolve()
        manifests.extend(root.rglob("run_manifest.txt"))
    if not manifests:
        raise SystemExit("no run_manifest.txt files found")

    run_rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    for manifest in sorted(set(manifests)):
        run_row, run_lineages = summarize_run(manifest.parent)
        run_rows.append(run_row)
        lineage_rows.extend(run_lineages)

    output_runs = Path(args.output_runs_csv).resolve()
    output_lineages = Path(args.output_lineages_csv).resolve()
    output_json = Path(args.output_json).resolve()
    write_csv(output_runs, run_rows)
    write_csv(output_lineages, lineage_rows)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(
            {
                "run_count": len(run_rows),
                "lineage_row_count": len(lineage_rows),
                "runs_csv": str(output_runs),
                "lineages_csv": str(output_lineages),
                "source_tree_sha256_values": sorted(
                    {str(row["source_tree_sha256"]) for row in run_rows}
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    print(f"summarized {len(run_rows)} runs and {len(lineage_rows)} lineage rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
