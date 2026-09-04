#!/usr/bin/env python3
"""Build audited frontend-only artifacts for the real-pool admission-v2 replay."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


ROOT = Path("/home/ma/AQUA-FE_WS")
OUTPUT = ROOT / "logs/real_pool_temporal_admission_v2"
POOL_ROOT = Path("/home/ma/real_pool_temporal_admission_v2")
POOL_OFF_ROOT = Path(
    "/home/ma/real_pool_frontend_lifetime_diag/full/hybrid_processall"
)
CAMERA_SHA256 = "3fe337a9dcf7eb0514f0a84a09a333c1acb3659291f8a039445d89171a3d3dc8"
V2_CONFIG_SHA256 = "db675143f510e0fdf6d694882cb3af6ca4968bd1b9eb00d054f7958140ef968c"
OFF_CONFIG_SHA256 = "6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3"
EXPECTED_FRAMES = {
    "171342": (2650, 1325),
    "171944": (2074, 1037),
    "172529": (7193, 3597),
}

RUNS = {
    ("a09_6000_6800", "off"): Path(
        "/home/ma/gftt_admission_noharm/noharm/a09/off"
    ),
    ("a09_6000_6800", "v2_shadow"): Path(
        "/home/ma/gftt_admission_noharm_v2/noharm/a09/on"
    ),
    ("harbor07_1660_1720", "off"): Path(
        "/home/ma/gftt_admission_persistent_coverage/h07/off"
    ),
    ("harbor07_1660_1720", "v2_shadow"): Path(
        "/home/ma/gftt_admission_persistent_coverage/h07/v2"
    ),
}
for sequence in EXPECTED_FRAMES:
    RUNS[(f"pool_{sequence}", "off")] = POOL_OFF_ROOT / sequence
    RUNS[(f"pool_{sequence}", "v2_shadow")] = POOL_ROOT / sequence / "on"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def selected_rows(directory: Path) -> list[dict[str, str]]:
    return [
        row
        for row in read_csv(directory / "per_frame.csv")
        if int(row["selected_for_output"])
    ]


def percentile(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), q))


def finite_median(values: list[float]) -> float | str:
    finite = [value for value in values if math.isfinite(value)]
    return float(np.median(finite)) if finite else ""


def optional_summary(summary: dict, key: str) -> object:
    return summary[key] if key in summary else ""


def validate_pool_v2(sequence: str, directory: Path) -> dict[str, object]:
    summary = load_json(directory / "summary.json")
    raw_frames, output_frames = EXPECTED_FRAMES[sequence]
    expected = {
        "input_bag": (
            "/mnt/data/Dataset_pool/ros1_bags/"
            f"full_slam_20260608_{sequence}_cam_imu_dvl_imgshift_m085375.bag"
        ),
        "camera_config_sha256": CAMERA_SHA256,
        "config_sha256": V2_CONFIG_SHA256,
        "raw_image_messages_seen": raw_frames,
        "processed_frames": raw_frames,
        "selected_frames": output_frames,
        "process_skipped_frames": True,
        "temporal_gftt_admission": True,
        "method": "hybrid_xfeat",
        "preprocess": "none",
    }
    mismatches = {
        key: {"observed": summary.get(key), "expected": value}
        for key, value in expected.items()
        if summary.get(key) != value
    }
    rows = read_csv(directory / "per_frame.csv")
    selected = [row for row in rows if int(row["selected_for_output"])]
    required = [
        "output_grid_coverage",
        "output_age_ge2_tracks",
        "output_age_ge2_grid_coverage",
        "output_age_ge3_tracks",
        "output_age_ge3_grid_coverage",
    ]
    missing_columns = [key for key in required if not rows or key not in rows[0]]
    nonfinite_count = 0
    for row in selected:
        for key in required:
            if key in row and not math.isfinite(float(row[key])):
                nonfinite_count += 1
    stamps = [float(row["header_stamp_s"]) for row in rows]
    timestamps_strict = all(b > a for a, b in zip(stamps, stamps[1:]))
    histogram = read_csv(directory / "lifetime_histogram.csv")
    histogram_complete = sum(
        int(row["track_count"])
        for row in histogram
        if row["lineage"] == "gftt_klt"
    )
    summary_complete = int(summary["gftt_klt_complete_track_count"])
    errors = {
        "lineage_mismatches": mismatches,
        "row_count": len(rows),
        "selected_row_count": len(selected),
        "missing_columns": missing_columns,
        "nonfinite_selected_values": nonfinite_count,
        "timestamps_strictly_increasing": timestamps_strict,
        "histogram_complete_track_count": histogram_complete,
        "summary_complete_track_count": summary_complete,
        "histogram_matches_summary": histogram_complete == summary_complete,
    }
    valid = (
        not mismatches
        and len(rows) == raw_frames
        and len(selected) == output_frames
        and not missing_columns
        and nonfinite_count == 0
        and timestamps_strict
        and histogram_complete == summary_complete
    )
    errors["valid"] = valid
    if not valid:
        raise RuntimeError(f"invalid pool v2 artifact {sequence}: {errors}")
    return errors


def validate_pool_off(sequence: str, directory: Path) -> dict[str, object]:
    summary = load_json(directory / "summary.json")
    raw_frames, output_frames = EXPECTED_FRAMES[sequence]
    expected = {
        "input_bag": (
            "/mnt/data/Dataset_pool/ros1_bags/"
            f"full_slam_20260608_{sequence}_cam_imu_dvl_imgshift_m085375.bag"
        ),
        "camera_config_sha256": CAMERA_SHA256,
        "config_sha256": OFF_CONFIG_SHA256,
        "raw_image_messages_seen": raw_frames,
        "processed_frames": raw_frames,
        "selected_frames": output_frames,
        "process_skipped_frames": True,
        "method": "hybrid_xfeat",
        "preprocess": "none",
    }
    mismatches = {
        key: {"observed": summary.get(key), "expected": value}
        for key, value in expected.items()
        if summary.get(key) != value
    }
    rows = read_csv(directory / "per_frame.csv")
    selected = [row for row in rows if int(row["selected_for_output"])]
    stamps = [float(row["header_stamp_s"]) for row in rows]
    timestamps_strict = all(b > a for a, b in zip(stamps, stamps[1:]))
    histogram = read_csv(directory / "lifetime_histogram.csv")
    histogram_complete = sum(
        int(row["track_count"])
        for row in histogram
        if row["lineage"] == "gftt_klt"
    )
    summary_complete = int(summary["gftt_klt_complete_track_count"])
    valid = (
        not mismatches
        and len(rows) == raw_frames
        and len(selected) == output_frames
        and timestamps_strict
        and histogram_complete == summary_complete
    )
    audit = {
        "lineage_mismatches": mismatches,
        "row_count": len(rows),
        "selected_row_count": len(selected),
        "timestamps_strictly_increasing": timestamps_strict,
        "histogram_complete_track_count": histogram_complete,
        "summary_complete_track_count": summary_complete,
        "histogram_matches_summary": histogram_complete == summary_complete,
        "persistent_instrumentation": "legacy_not_recorded",
        "valid": valid,
    }
    if not valid:
        raise RuntimeError(f"invalid pool off artifact {sequence}: {audit}")
    return audit


def summary_row(dataset: str, condition: str, directory: Path) -> dict[str, object]:
    summary = load_json(directory / "summary.json")
    selected = selected_rows(directory)
    raw_tracks = [float(row["output_tracks"]) for row in selected]
    # Legacy pool-off artifacts predate behavior-neutral grid/age columns.  Do
    # not invent those values; retain empty cells and identify instrumentation.
    has_raw_coverage = bool(selected and "output_grid_coverage" in selected[0])
    has_persistent = bool(selected and "output_age_ge2_tracks" in selected[0])
    lifetime_prefix = "gftt_klt_lifetime"
    row: dict[str, object] = {
        "dataset": dataset,
        "condition": condition,
        "processed_frames": summary.get("processed_frames", ""),
        "selected_frames": summary.get("selected_frames", ""),
        "lifetime_median": summary[f"{lifetime_prefix}_median_selected_frames"],
        "lifetime_p75": summary[f"{lifetime_prefix}_p75_selected_frames"],
        "lifetime_p90": summary[f"{lifetime_prefix}_p90_selected_frames"],
        "tracks_median": (
            optional_summary(summary, "selected_median_output_tracks")
            if "selected_median_output_tracks" in summary
            else float(np.median(raw_tracks))
        ),
        "tracks_p10": (
            optional_summary(summary, "selected_p10_output_tracks")
            if "selected_p10_output_tracks" in summary
            else percentile(raw_tracks, 10)
        ),
        "raw_coverage_median": (
            optional_summary(summary, "selected_median_output_grid_coverage")
            if has_raw_coverage
            else ""
        ),
        "raw_coverage_p10": (
            optional_summary(summary, "selected_p10_output_grid_coverage")
            if has_raw_coverage
            else ""
        ),
        "age_ge2_tracks_median": (
            optional_summary(summary, "selected_median_age_ge2_tracks")
            if has_persistent
            else ""
        ),
        "age_ge2_tracks_p10": (
            optional_summary(summary, "selected_p10_age_ge2_tracks")
            if has_persistent
            else ""
        ),
        "age_ge2_coverage_median": (
            optional_summary(summary, "selected_median_age_ge2_grid_coverage")
            if has_persistent
            else ""
        ),
        "age_ge2_coverage_p10": (
            optional_summary(summary, "selected_p10_age_ge2_grid_coverage")
            if has_persistent
            else ""
        ),
        "dropout_median": optional_summary(summary, "selected_median_dropout_ratio"),
        "births_total": (
            optional_summary(summary, "selected_total_births")
            if "selected_total_births" in summary
            else sum(int(row["selected_births"]) for row in selected)
        ),
        "deaths_total": (
            optional_summary(summary, "selected_total_deaths")
            if "selected_total_deaths" in summary
            else sum(int(row["selected_deaths"]) for row in selected)
        ),
        "xfeat_candidates_total": optional_summary(summary, "xfeat_candidates_total"),
        "xfeat_confirmed_total": optional_summary(summary, "xfeat_confirmed_total"),
        "persistent_instrumentation": "available" if has_persistent else "legacy_not_recorded",
        "artifact_dir": str(directory),
    }
    return row


def pool_gate_rows(comparison: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    by_key = {(row["dataset"], row["condition"]): row for row in comparison}
    for sequence in EXPECTED_FRAMES:
        dataset = f"pool_{sequence}"
        on = by_key[(dataset, "v2_shadow")]
        checks = [
            ("gftt_lifetime_median", on["lifetime_median"], ">= 2", float(on["lifetime_median"]) >= 2),
            ("age_ge2_tracks_p10", on["age_ge2_tracks_p10"], ">= 200", float(on["age_ge2_tracks_p10"]) >= 200),
            ("age_ge2_coverage_p10", on["age_ge2_coverage_p10"], ">= 0.75", float(on["age_ge2_coverage_p10"]) >= 0.75),
            ("all_age_tracks_p10", on["tracks_p10"], ">= 200", float(on["tracks_p10"]) >= 200),
        ]
        for metric, value, required, passed in checks:
            rows.append(
                {
                    "dataset": dataset,
                    "metric": metric,
                    "observed": value,
                    "required": required,
                    "pass": passed,
                }
            )
    return rows


def build_selected_frame_rows() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    frame_rows: list[dict[str, object]] = []
    interval_rows: list[dict[str, object]] = []
    copied_fields = [
        "selected_frame_index",
        "header_stamp_s",
        "raw_contrast",
        "raw_laplacian_var",
        "raw_flat_region_ratio",
        "median_motion_px",
        "dropout_ratio",
        "klt_input_tracks",
        "klt_final_pass",
        "gftt_pending_candidates",
        "gftt_confirm_ncc_pass",
        "gftt_confirm_admitted",
        "selected_births",
        "selected_deaths",
        "output_tracks",
        "output_grid_coverage",
        "output_age_ge2_tracks",
        "output_age_ge2_grid_coverage",
        "output_age_ge3_tracks",
        "output_age_ge3_grid_coverage",
        "xfeat_candidates",
        "xfeat_confirmed",
    ]
    for sequence in EXPECTED_FRAMES:
        selected = selected_rows(POOL_ROOT / sequence / "on")
        t0 = float(selected[0]["header_stamp_s"])
        failures: list[bool] = []
        for row in selected:
            output = {"sequence": sequence}
            output.update({key: row[key] for key in copied_fields})
            output["time_from_first_output_s"] = float(row["header_stamp_s"]) - t0
            failed = (
                float(row["output_age_ge2_tracks"]) < 200
                or float(row["output_age_ge2_grid_coverage"]) < 0.75
            )
            output["persistent_supply_frame_pass"] = not failed
            frame_rows.append(output)
            failures.append(failed)

        start: int | None = None
        for index, failed in enumerate(failures):
            if failed and start is None:
                start = index
            if start is not None and (not failed or index == len(failures) - 1):
                end = index - 1 if not failed else index
                block = selected[start : end + 1]
                interval_rows.append(
                    {
                        "sequence": sequence,
                        "start_selected_frame": start,
                        "end_selected_frame": end,
                        "selected_frame_count": end - start + 1,
                        "start_time_s": float(block[0]["header_stamp_s"]) - t0,
                        "end_time_s": float(block[-1]["header_stamp_s"]) - t0,
                        "min_age_ge2_tracks": min(
                            float(row["output_age_ge2_tracks"]) for row in block
                        ),
                        "min_age_ge2_coverage": min(
                            float(row["output_age_ge2_grid_coverage"]) for row in block
                        ),
                        "median_motion_px": finite_median(
                            [float(row["median_motion_px"]) for row in block]
                        ),
                        "median_raw_contrast": float(
                            np.median([float(row["raw_contrast"]) for row in block])
                        ),
                        "median_raw_flat_region_ratio": float(
                            np.median(
                                [float(row["raw_flat_region_ratio"]) for row in block]
                            )
                        ),
                        "median_dropout_ratio": float(
                            np.median([float(row["dropout_ratio"]) for row in block])
                        ),
                    }
                )
                start = None
    return frame_rows, interval_rows


def lifetime_buckets(directory: Path) -> np.ndarray:
    histogram = read_csv(directory / "lifetime_histogram.csv")
    counts = np.zeros(6, dtype=float)
    for row in histogram:
        if row["lineage"] != "gftt_klt":
            continue
        lifetime = int(row["lifetime_selected_frames"])
        count = int(row["track_count"])
        bucket = (
            0 if lifetime == 1 else
            1 if lifetime == 2 else
            2 if lifetime <= 4 else
            3 if lifetime <= 9 else
            4 if lifetime <= 19 else 5
        )
        counts[bucket] += count
    return counts / counts.sum()


def plot_lifetimes() -> None:
    labels = ["1", "2", "3–4", "5–9", "10–19", "≥20"]
    x = np.arange(len(labels))
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    colors = ("#7A8A99", "#0072B2")
    for axis, sequence in zip(axes, EXPECTED_FRAMES):
        off = lifetime_buckets(POOL_OFF_ROOT / sequence)
        on = lifetime_buckets(POOL_ROOT / sequence / "on")
        width = 0.38
        axis.bar(x - width / 2, 100 * off, width, label="off", color=colors[0])
        axis.bar(x + width / 2, 100 * on, width, label="v2", color=colors[1])
        axis.set_title(sequence)
        axis.set_xticks(x, labels, rotation=35)
        axis.set_xlabel("lifetime (selected frames)")
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("completed GFTT/KLT tracks (%)")
    axes[-1].legend(frameon=False)
    fig.suptitle("Real-pool GFTT/KLT lifetime distribution: admission off vs v2")
    fig.tight_layout()
    fig.savefig(OUTPUT / "pool_lifetime_histogram_before_after.png", dpi=180)
    plt.close(fig)


def plot_supply() -> None:
    fig, axes = plt.subplots(3, 2, figsize=(12, 8), sharex=False)
    for row_index, sequence in enumerate(EXPECTED_FRAMES):
        selected = selected_rows(POOL_ROOT / sequence / "on")
        time_s = np.asarray([float(row["header_stamp_s"]) for row in selected])
        time_s -= time_s[0]
        tracks = np.asarray([float(row["output_age_ge2_tracks"]) for row in selected])
        coverage = np.asarray(
            [float(row["output_age_ge2_grid_coverage"]) for row in selected]
        )
        track_axis, coverage_axis = axes[row_index]
        track_axis.plot(time_s, tracks, color="#0072B2", linewidth=0.8)
        track_axis.axhline(200, color="#D55E00", linestyle="--", linewidth=1)
        coverage_axis.plot(time_s, coverage, color="#009E73", linewidth=0.8)
        coverage_axis.axhline(0.75, color="#D55E00", linestyle="--", linewidth=1)
        track_axis.set_ylabel(f"{sequence}\nage≥2 tracks")
        coverage_axis.set_ylabel("age≥2 coverage")
        coverage_axis.set_ylim(-0.02, 1.02)
        for axis in (track_axis, coverage_axis):
            axis.set_xlabel("time from first output (s)")
            axis.grid(alpha=0.2)
    fig.suptitle("Real-pool v2 persistent visual supply (dashed = frozen gate)")
    fig.tight_layout()
    fig.savefig(OUTPUT / "pool_persistent_supply_timeline.png", dpi=180)
    plt.close(fig)


def plot_overlay_samples() -> None:
    samples = [
        (
            POOL_OFF_ROOT / "171342/overlays/frame_000248_event.jpg",
            "171342 off, raw 248",
        ),
        (
            POOL_ROOT / "171342/on/overlays/frame_000248_event.jpg",
            "171342 v2, raw 248 (paired)",
        ),
        (
            POOL_ROOT / "171944/on/overlays/frame_001500_periodic.jpg",
            "171944 v2, raw 1500",
        ),
        (
            POOL_ROOT / "172529/on/overlays/frame_001408_event.jpg",
            "172529 v2, raw 1408",
        ),
    ]
    missing = [str(path) for path, _ in samples if not path.is_file()]
    if missing:
        raise RuntimeError(f"missing overlay samples: {missing}")
    fig, axes = plt.subplots(2, 2, figsize=(13, 7.8))
    for axis, (path, title) in zip(axes.flat, samples):
        axis.imshow(plt.imread(path))
        axis.set_title(title)
        axis.axis("off")
    fig.suptitle("Frontend overlay samples (cyan/orange vectors; green/cyan points)")
    fig.tight_layout()
    fig.savefig(OUTPUT / "pool_overlay_samples.png", dpi=150)
    plt.close(fig)


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    audits = {
        sequence: validate_pool_v2(sequence, POOL_ROOT / sequence / "on")
        for sequence in EXPECTED_FRAMES
    }
    off_audits = {
        sequence: validate_pool_off(sequence, POOL_OFF_ROOT / sequence)
        for sequence in EXPECTED_FRAMES
    }
    comparison = [
        summary_row(dataset, condition, directory)
        for (dataset, condition), directory in RUNS.items()
    ]
    fields = list(comparison[0])
    write_csv(OUTPUT / "cross_dataset_fix_comparison.csv", comparison, fields)
    gates = pool_gate_rows(comparison)
    write_csv(
        OUTPUT / "pool_gate_matrix.csv",
        gates,
        ["dataset", "metric", "observed", "required", "pass"],
    )
    frame_rows, interval_rows = build_selected_frame_rows()
    write_csv(
        OUTPUT / "pool_selected_frame_metrics.csv",
        frame_rows,
        list(frame_rows[0]),
    )
    write_csv(
        OUTPUT / "pool_persistent_supply_failure_intervals.csv",
        interval_rows,
        list(interval_rows[0]),
    )
    plot_lifetimes()
    plot_supply()
    plot_overlay_samples()
    sequence_pass = {
        f"pool_{sequence}": all(
            bool(row["pass"])
            for row in gates
            if row["dataset"] == f"pool_{sequence}"
        )
        for sequence in EXPECTED_FRAMES
    }
    manifest = {
        "decision": "GO" if all(sequence_pass.values()) else "NO_GO",
        "sequence_gate": sequence_pass,
        "pool_v2_audits": audits,
        "pool_off_audits": off_audits,
        "protocol": str(OUTPUT / "protocol.md"),
        "report": str(OUTPUT / "real_pool_temporal_admission_v2_report.md"),
        "superseded_frontend_usability_report": str(
            ROOT / "logs/real_pool_vins/real_pool_report.md"
        ),
        "machine_tables": [
            str(OUTPUT / "cross_dataset_fix_comparison.csv"),
            str(OUTPUT / "pool_gate_matrix.csv"),
            str(OUTPUT / "pool_selected_frame_metrics.csv"),
            str(OUTPUT / "pool_persistent_supply_failure_intervals.csv"),
        ],
        "figures": [
            str(OUTPUT / "pool_lifetime_histogram_before_after.png"),
            str(OUTPUT / "pool_persistent_supply_timeline.png"),
            str(OUTPUT / "pool_overlay_samples.png"),
        ],
        "vins_run": False,
        "feature_bag_written": False,
        "raw_pool_bag_modified": False,
    }
    (OUTPUT / "artifact_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
