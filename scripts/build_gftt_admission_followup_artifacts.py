#!/usr/bin/env python3
"""Build v2/v3 temporal-admission gate tables from frontend summaries only."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path("/home/ma/AQUA-FE_WS")
OUTPUT = ROOT / "logs/gftt_admission_noharm_v2"
RUNS = {
    ("a09_6000_6800", "off"): Path("/home/ma/gftt_admission_noharm/noharm/a09/off"),
    ("a09_6000_6800", "v2_shadow"): Path("/home/ma/gftt_admission_noharm_v2/noharm/a09/on"),
    ("harbor07_1660_1720", "off"): Path("/home/ma/gftt_admission_noharm_v2/noharm/h07/off"),
    ("harbor07_1660_1720", "v2_shadow"): Path("/home/ma/gftt_admission_noharm_v2/noharm/h07/on"),
    ("harbor07_1660_1720", "v3_dualpool_probe"): Path("/home/ma/gftt_admission_dualpool_probe/h07/on"),
}


def load(dataset: str, candidate: str) -> dict:
    return json.loads((RUNS[(dataset, candidate)] / "summary.json").read_text(encoding="utf-8"))


def gate_rows(dataset: str, candidate: str) -> list[dict[str, object]]:
    off = load(dataset, "off")
    on = load(dataset, candidate)
    rows = [
        ("lifetime_median_non_decrease", "all_lifetime_median_selected_frames", on["all_lifetime_median_selected_frames"] >= off["all_lifetime_median_selected_frames"], "on >= off"),
        ("lifetime_p75_non_decrease", "all_lifetime_p75_selected_frames", on["all_lifetime_p75_selected_frames"] >= off["all_lifetime_p75_selected_frames"], "on >= off"),
        ("tracks_median_retain_90pct", "selected_median_output_tracks", on["selected_median_output_tracks"] >= 0.9 * off["selected_median_output_tracks"], "on/off >= 0.90"),
        ("tracks_p10_retain_90pct", "selected_p10_output_tracks", on["selected_p10_output_tracks"] >= 0.9 * off["selected_p10_output_tracks"], "on/off >= 0.90"),
        ("coverage_median_loss_at_most_one_cell", "selected_median_output_grid_coverage", on["selected_median_output_grid_coverage"] >= off["selected_median_output_grid_coverage"] - 1.0 / 24.0, "on >= off - 1/24"),
        ("coverage_p10_loss_at_most_one_cell", "selected_p10_output_grid_coverage", on["selected_p10_output_grid_coverage"] >= off["selected_p10_output_grid_coverage"] - 1.0 / 24.0, "on >= off - 1/24"),
        ("dropout_median_increase_at_most_0.02", "selected_median_dropout_ratio", on["selected_median_dropout_ratio"] <= off["selected_median_dropout_ratio"] + 0.02, "on <= off + 0.02"),
        ("births_total_increase_at_most_10pct", "selected_total_births", on["selected_total_births"] <= 1.1 * off["selected_total_births"], "on/off <= 1.10"),
        ("deaths_total_increase_at_most_10pct", "selected_total_deaths", on["selected_total_deaths"] <= 1.1 * off["selected_total_deaths"], "on/off <= 1.10"),
    ]
    return [
        {
            "dataset": dataset,
            "candidate": candidate,
            "criterion": name,
            "off": off[key],
            "on": on[key],
            "required": required,
            "pass": passed,
        }
        for name, key, passed, required in rows
    ]


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    gate = []
    for dataset, candidate in (
        ("a09_6000_6800", "v2_shadow"),
        ("harbor07_1660_1720", "v2_shadow"),
        ("harbor07_1660_1720", "v3_dualpool_probe"),
    ):
        gate.extend(gate_rows(dataset, candidate))
    write_csv(
        OUTPUT / "candidate_gate_matrix.csv",
        gate,
        ["dataset", "candidate", "criterion", "off", "on", "required", "pass"],
    )

    metric_fields = [
        "dataset",
        "candidate",
        "run_status",
        "lifetime_median",
        "lifetime_p75",
        "tracks_median",
        "tracks_p10",
        "coverage_median",
        "coverage_p10",
        "dropout_median",
        "births_total",
        "deaths_total",
        "overall_gate",
        "artifact_dir",
    ]
    rows: list[dict[str, object]] = []
    for (dataset, candidate), directory in RUNS.items():
        summary = load(dataset, candidate)
        candidate_gate = [
            row for row in gate if row["dataset"] == dataset and row["candidate"] == candidate
        ]
        rows.append(
            {
                "dataset": dataset,
                "candidate": candidate,
                "run_status": "complete",
                "lifetime_median": summary["all_lifetime_median_selected_frames"],
                "lifetime_p75": summary["all_lifetime_p75_selected_frames"],
                "tracks_median": summary["selected_median_output_tracks"],
                "tracks_p10": summary["selected_p10_output_tracks"],
                "coverage_median": summary["selected_median_output_grid_coverage"],
                "coverage_p10": summary["selected_p10_output_grid_coverage"],
                "dropout_median": summary["selected_median_dropout_ratio"],
                "births_total": summary["selected_total_births"],
                "deaths_total": summary["selected_total_deaths"],
                "overall_gate": (
                    "control"
                    if candidate == "off"
                    else "PASS" if all(row["pass"] for row in candidate_gate) else "FAIL"
                ),
                "artifact_dir": str(directory),
            }
        )
    for dataset in ("pool_171342", "pool_171944", "pool_172529"):
        rows.append(
            {
                "dataset": dataset,
                "candidate": "v2/v3",
                "run_status": "not_run_due_harbor07_noharm_failure",
                "overall_gate": "NOT_EVALUATED",
            }
        )
    write_csv(OUTPUT / "cross_dataset_status.csv", rows, metric_fields)

    stage_path = Path(
        "/home/ma/gftt_admission_confirmation_diag/a09_on_200/per_frame.csv"
    )
    stage_fields = [
        "gftt_confirm_input",
        "gftt_confirm_forward_pass",
        "gftt_confirm_backward_pass",
        "gftt_confirm_fb_pass",
        "gftt_confirm_ncc_pass",
        "gftt_confirm_border_pass",
        "gftt_confirm_distance_pass",
        "gftt_confirm_geometry_pass",
        "gftt_confirm_selected",
        "gftt_confirm_admitted",
    ]
    with stage_path.open(newline="", encoding="utf-8") as handle:
        stage_source = list(csv.DictReader(handle))
    stage_rows = []
    previous_total: int | None = None
    for stage in stage_fields:
        total = sum(int(row[stage]) for row in stage_source)
        stage_rows.append(
            {
                "stage": stage,
                "total": total,
                "retain_from_previous": (
                    "" if previous_total in (None, 0) else total / previous_total
                ),
            }
        )
        previous_total = total
    write_csv(
        OUTPUT / "a09_v1_confirmation_stage_totals.csv",
        stage_rows,
        ["stage", "total", "retain_from_previous"],
    )

    manifest = {
        "decision": "NO_GO",
        "a09_v2": "PASS",
        "harbor07_v2": "FAIL_coverage",
        "harbor07_v3_probe": "FAIL_coverage",
        "pool": "not_run_due_harbor07_noharm_failure",
        "vins_run": False,
        "feature_bag_written": False,
        "confirmation_stage_diagnostic": str(stage_path),
    }
    (OUTPUT / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
