#!/usr/bin/env python3
"""Build deterministic frontend-only no-harm tables and plots.

This consumes diagnostic CSV/JSON files only.  It does not open ROS bags, run
VINS, or write feature bags.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


DATASETS = (
    "a09_6000_6800",
    "harbor07_1660_1720",
    "pool_171342",
    "pool_171944",
    "pool_172529",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def selected_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [row for row in csv.DictReader(handle) if row["selected_for_output"] == "1"]


def complete_histogram(path: Path) -> Counter[int]:
    result: Counter[int] = Counter()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            result[int(row["lifetime_selected_frames"])] += int(row["track_count"])
    return result


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ratio(on: float, off: float) -> float:
    return on / off if off else float("nan")


def main() -> int:
    args = parse_args()
    root = Path(args.input_root)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    a09 = root / "noharm/a09"
    summaries = {
        side: json.loads((a09 / side / "summary.json").read_text(encoding="utf-8"))
        for side in ("off", "on")
    }
    rows = {
        side: selected_rows(a09 / side / "per_frame.csv")
        for side in ("off", "on")
    }
    if [row["raw_frame_index"] for row in rows["off"]] != [
        row["raw_frame_index"] for row in rows["on"]
    ]:
        raise RuntimeError("A09 selected-frame indices are not paired")

    off = summaries["off"]
    on = summaries["on"]
    gate_rows = [
        {
            "criterion": "completed_lifetime_median_non_decrease",
            "off": off["all_lifetime_median_selected_frames"],
            "on": on["all_lifetime_median_selected_frames"],
            "required": "on >= off",
            "pass": on["all_lifetime_median_selected_frames"]
            >= off["all_lifetime_median_selected_frames"],
        },
        {
            "criterion": "completed_lifetime_p75_non_decrease",
            "off": off["all_lifetime_p75_selected_frames"],
            "on": on["all_lifetime_p75_selected_frames"],
            "required": "on >= off",
            "pass": on["all_lifetime_p75_selected_frames"]
            >= off["all_lifetime_p75_selected_frames"],
        },
    ]
    for label, key in (
        ("output_tracks_median_retain_90pct", "selected_median_output_tracks"),
        ("output_tracks_p10_retain_90pct", "selected_p10_output_tracks"),
    ):
        gate_rows.append(
            {
                "criterion": label,
                "off": off[key],
                "on": on[key],
                "required": "on/off >= 0.90",
                "pass": ratio(float(on[key]), float(off[key])) >= 0.90,
            }
        )
    for label, key in (
        ("grid_coverage_median_loss_at_most_one_cell", "selected_median_output_grid_coverage"),
        ("grid_coverage_p10_loss_at_most_one_cell", "selected_p10_output_grid_coverage"),
    ):
        gate_rows.append(
            {
                "criterion": label,
                "off": off[key],
                "on": on[key],
                "required": "on >= off - 1/24",
                "pass": float(on[key]) >= float(off[key]) - 1.0 / 24.0,
            }
        )
    gate_rows.append(
        {
            "criterion": "dropout_median_increase_at_most_0.02",
            "off": off["selected_median_dropout_ratio"],
            "on": on["selected_median_dropout_ratio"],
            "required": "on <= off + 0.02",
            "pass": on["selected_median_dropout_ratio"]
            <= off["selected_median_dropout_ratio"] + 0.02,
        }
    )
    for label, key in (
        ("selected_births_total_increase_at_most_10pct", "selected_total_births"),
        ("selected_deaths_total_increase_at_most_10pct", "selected_total_deaths"),
    ):
        gate_rows.append(
            {
                "criterion": label,
                "off": off[key],
                "on": on[key],
                "required": "on/off <= 1.10",
                "pass": ratio(float(on[key]), float(off[key])) <= 1.10,
            }
        )
    write_csv(
        output / "noharm_gate_results.csv",
        ["criterion", "off", "on", "required", "pass"],
        gate_rows,
    )

    table_fields = [
        "dataset",
        "fix",
        "run_status",
        "processed_frames",
        "selected_frames",
        "lifetime_median_selected_frames",
        "lifetime_p75_selected_frames",
        "gftt_lifetime_median_selected_frames",
        "gftt_lifetime_p75_selected_frames",
        "output_tracks_median",
        "output_tracks_p10",
        "grid_coverage_median",
        "grid_coverage_p10",
        "selected_births_total",
        "selected_deaths_total",
        "dropout_median",
        "gate_result",
        "artifact_dir",
    ]
    table_rows: list[dict[str, object]] = []
    for side in ("off", "on"):
        summary = summaries[side]
        table_rows.append(
            {
                "dataset": "a09_6000_6800",
                "fix": side,
                "run_status": "complete",
                "processed_frames": summary["processed_frames"],
                "selected_frames": summary["selected_frames"],
                "lifetime_median_selected_frames": summary["all_lifetime_median_selected_frames"],
                "lifetime_p75_selected_frames": summary["all_lifetime_p75_selected_frames"],
                "gftt_lifetime_median_selected_frames": summary["gftt_klt_lifetime_median_selected_frames"],
                "gftt_lifetime_p75_selected_frames": summary["gftt_klt_lifetime_p75_selected_frames"],
                "output_tracks_median": summary["selected_median_output_tracks"],
                "output_tracks_p10": summary["selected_p10_output_tracks"],
                "grid_coverage_median": summary["selected_median_output_grid_coverage"],
                "grid_coverage_p10": summary["selected_p10_output_grid_coverage"],
                "selected_births_total": summary["selected_total_births"],
                "selected_deaths_total": summary["selected_total_deaths"],
                "dropout_median": summary["selected_median_dropout_ratio"],
                "gate_result": "FAIL" if side == "on" else "control",
                "artifact_dir": str((a09 / side).resolve()),
            }
        )
    for dataset in DATASETS[1:]:
        for side in ("off", "on"):
            table_rows.append(
                {
                    "dataset": dataset,
                    "fix": side,
                    "run_status": "not_run_due_a09_noharm_failure",
                    "gate_result": "NOT_EVALUATED",
                }
            )
    write_csv(output / "cross_dataset_comparison.csv", table_fields, table_rows)

    on_counts = np.asarray([int(row["output_tracks"]) for row in rows["on"]])
    bad_indices = [
        int(row["raw_frame_index"])
        for row in rows["on"]
        if int(row["output_tracks"]) < 0.90 * float(off["selected_p10_output_tracks"])
    ]
    intervals: list[list[int]] = []
    for raw_index in bad_indices:
        if not intervals or raw_index > intervals[-1][-1] + 2:
            intervals.append([raw_index])
        else:
            intervals[-1].append(raw_index)
    interval_rows = []
    on_by_raw = {int(row["raw_frame_index"]): row for row in rows["on"]}
    for values in intervals:
        subset = [on_by_raw[index] for index in values]
        interval_rows.append(
            {
                "raw_start": values[0],
                "raw_end": values[-1],
                "selected_frames": len(values),
                "output_tracks_min": min(int(row["output_tracks"]) for row in subset),
                "output_tracks_median": float(np.median([int(row["output_tracks"]) for row in subset])),
                "dropout_median": float(np.median([float(row["dropout_ratio"]) for row in subset])),
                "pending_gftt_median": float(np.median([int(row["gftt_pending_candidates"]) for row in subset])),
            }
        )
    write_csv(
        output / "a09_low_supply_intervals.csv",
        [
            "raw_start",
            "raw_end",
            "selected_frames",
            "output_tracks_min",
            "output_tracks_median",
            "dropout_median",
            "pending_gftt_median",
        ],
        interval_rows,
    )

    paired_rows = []
    for off_row, on_row in zip(rows["off"], rows["on"]):
        paired_rows.append(
            {
                "raw_frame_index": off_row["raw_frame_index"],
                "off_output_tracks": off_row["output_tracks"],
                "on_output_tracks": on_row["output_tracks"],
                "off_grid_coverage": off_row["output_grid_coverage"],
                "on_grid_coverage": on_row["output_grid_coverage"],
                "off_births": off_row["selected_births"],
                "on_births": on_row["selected_births"],
                "off_deaths": off_row["selected_deaths"],
                "on_deaths": on_row["selected_deaths"],
                "off_dropout": off_row["dropout_ratio"],
                "on_dropout": on_row["dropout_ratio"],
            }
        )
    write_csv(
        output / "a09_paired_selected_frames.csv",
        list(paired_rows[0]),
        paired_rows,
    )

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(8.2, 4.8), constrained_layout=True)
    max_lifetime = 20
    x = np.arange(1, max_lifetime + 2)
    labels = [str(value) for value in range(1, max_lifetime + 1)] + [">20"]
    width = 0.42
    for offset, side, color in ((-width / 2, "off", "#6b7280"), (width / 2, "on", "#0072B2")):
        histogram = complete_histogram(a09 / side / "lifetime_histogram.csv")
        counts = [histogram[value] for value in range(1, max_lifetime + 1)]
        counts.append(sum(count for lifetime, count in histogram.items() if lifetime > max_lifetime))
        ax.bar(x + offset, counts, width=width, label=f"admission {side}", color=color)
    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_xlabel("Completed track lifetime (selected output frames)")
    ax.set_ylabel("Track count (log scale)")
    ax.set_title("A09 6000–6800: temporal GFTT admission lifetime")
    ax.legend()
    fig.savefig(output / "a09_lifetime_histogram_before_after.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9.2, 4.6), constrained_layout=True)
    raw = np.asarray([int(row["raw_frame_index"]) for row in rows["off"]])
    off_counts = np.asarray([int(row["output_tracks"]) for row in rows["off"]])
    ax.plot(raw, off_counts, color="#6b7280", linewidth=1.2, label="admission off")
    ax.plot(raw, on_counts, color="#0072B2", linewidth=1.2, label="admission on")
    ax.axhline(315, color="#D55E00", linestyle="--", linewidth=1.2, label="90% retention gate (315)")
    ax.set_xlabel("Raw image index")
    ax.set_ylabel("Output tracks")
    ax.set_ylim(0, 370)
    ax.set_title("A09 paired selected-frame feature supply")
    ax.legend(loc="lower right")
    fig.savefig(output / "a09_track_supply_timeseries.png", dpi=180)
    plt.close(fig)

    off_overlay = plt.imread(a09 / "off/viz/frame_000001_periodic.jpg")
    on_overlay = plt.imread(a09 / "on/viz/frame_000001_periodic.jpg")
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.2), constrained_layout=True)
    for ax, image, title in (
        (axes[0], off_overlay, "Admission off: 350 public tracks"),
        (axes[1], on_overlay, "Admission on: 120 confirmed tracks"),
    ):
        ax.imshow(image)
        ax.set_title(title)
        ax.axis("off")
    fig.suptitle("A09 raw frame 1: same image, cadence, preprocessing, and thresholds")
    fig.savefig(output / "a09_overlay_comparison_raw000001.png", dpi=180)
    plt.close(fig)

    manifest = {
        "overall_gate": "FAIL",
        "failure": "A09 output-track p10 retention below 90%",
        "a09_on_frames_below_315": int(np.sum(on_counts < 315)),
        "a09_selected_frames": int(len(on_counts)),
        "downstream_replays": "not_run_due_a09_noharm_failure",
        "inputs": {
            side: {
                "summary": str((a09 / side / "summary.json").resolve()),
                "per_frame": str((a09 / side / "per_frame.csv").resolve()),
                "histogram": str((a09 / side / "lifetime_histogram.csv").resolve()),
            }
            for side in ("off", "on")
        },
    }
    (output / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote frontend-only artifacts to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
