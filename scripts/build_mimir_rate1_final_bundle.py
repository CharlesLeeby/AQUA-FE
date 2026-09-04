#!/usr/bin/env python3
"""Build the strict final MIMIR-UW rate-1 analysis bundle.

This script treats each selected 45 s window as a repeated comparison unit,
keeps empty/late trajectories explicit, audits the published classical KLT
backbone against the frozen KLT bag, and uses Sim(3) only as a scale
diagnostic.  It intentionally does not run inferential statistics: the nine
windows are purposively selected and each arm has one deterministic seed.
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from analyze_mimir_final_debug import (
    LEARNED_SOURCE_CODES,
    compact,
    feature_frames,
    load_gt,
    number,
    parse_kv,
    safe_stem,
    trajectory_diagnostics,
)


ARMS = ("klt", "original", "ours")
ARM_LABELS = {"klt": "Pure KLT", "original": "Original VINS", "ours": "AQUA-FE"}
ARM_COLORS = {"klt": "#0072B2", "original": "#E69F00", "ours": "#009E73"}
ARM_MARKERS = {"klt": "o", "original": "s", "ours": "D"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-windows", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--baseline-prefix", required=True)
    parser.add_argument("--ours-prefix", required=True)
    parser.add_argument("--ours-override-prefix", default="")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--noloftr-skip0-run", required=True, type=Path)
    parser.add_argument("--full-skip0-run", required=True, type=Path)
    parser.add_argument("--noloftr-skip4-run", required=True, type=Path)
    parser.add_argument("--full-skip4-run", required=True, type=Path)
    parser.add_argument("--rate2-klt-run", required=True, type=Path)
    parser.add_argument("--rate2-noloftr-run", required=True, type=Path)
    parser.add_argument("--rate2-full-run", required=True, type=Path)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def is_completed_backend(run_dir: Path) -> bool:
    trajectory = run_dir / "vins_output/vio.csv"
    return (run_dir / "ape.txt").is_file() or (
        trajectory.is_file() and (run_dir / "runner_exit_status.txt").is_file()
    )


def choose_ours_dirs(args: argparse.Namespace, stem: str) -> tuple[Path, Path, str]:
    if args.ours_override_prefix:
        override_run = args.run_root / f"{args.ours_override_prefix}_{stem}_ours_vins_seed0"
        override_export = args.run_root / f"{args.ours_override_prefix}_{stem}_ours_export"
        if is_completed_backend(override_run) and (override_export / "features.bag").is_file():
            return override_run, override_export, args.ours_override_prefix
    return (
        args.run_root / f"{args.ours_prefix}_{stem}_ours_vins_seed0",
        args.run_root / f"{args.ours_prefix}_{stem}_ours_export",
        args.ours_prefix,
    )


def finite(value: object) -> bool:
    return math.isfinite(number(value))


def fmt(value: object, digits: int = 3) -> str:
    numeric = number(value)
    return f"{numeric:.{digits}f}" if math.isfinite(numeric) else "--"


def status(diag: dict[str, object]) -> str:
    if not int(diag["has_trajectory"]):
        return "empty"
    return "PASS" if str(diag.get("init_success", "")) == "1" else "partial"


def initial_skip_receipt(export_dir: Path) -> tuple[float, int, int]:
    rows = read_csv(export_dir / "frontend_metrics.csv")
    if not rows:
        return math.nan, 0, 0
    skipped = 0
    for row in rows:
        if row.get("init_parallax_skipped_feature") != "1":
            break
        skipped += 1
    return number(rows[0].get("init_parallax_mean_step_px")), skipped, len(rows)


def longest_contiguous(stamps: list[int], threshold_s: float) -> tuple[int, float]:
    if not stamps:
        return 0, 0.0
    best_count = current_count = 1
    current_start = stamps[0]
    best_duration = 0
    for left, right in zip(stamps, stamps[1:]):
        if (right - left) * 1e-9 <= threshold_s:
            current_count += 1
        else:
            best_count = max(best_count, current_count)
            best_duration = max(best_duration, left - current_start)
            current_count = 1
            current_start = right
    best_count = max(best_count, current_count)
    best_duration = max(best_duration, stamps[-1] - current_start)
    return best_count, best_duration * 1e-9


def audit_export(
    *, stem: str, sequence: str, export_dir: Path, klt_export_dir: Path
) -> tuple[dict[str, object], list[dict[str, object]]]:
    ours = feature_frames(export_dir / "features.bag")
    klt = feature_frames(klt_export_dir / "features.bag")
    ours_stamps = sorted(ours)
    klt_stamps = sorted(klt)
    shared = sorted(set(ours) & set(klt))
    frame_steps = np.diff(np.asarray(ours_stamps, dtype=np.float64)) * 1e-9
    frame_steps = frame_steps[frame_steps > 0]
    median_dt = float(np.median(frame_steps)) if len(frame_steps) else math.nan
    continuity_threshold = max(0.08, 1.75 * median_dt) if math.isfinite(median_dt) else 0.08

    learned: dict[int, list[int]] = {}
    learned_sources: Counter[int] = Counter()
    classical_observations = 0
    for stamp, frame in ours.items():
        for feature_id, values in frame.items():
            source_code = int(round(values[5]))
            if feature_id >= 10_000_000 or source_code in LEARNED_SOURCE_CODES:
                learned.setdefault(feature_id, []).append(stamp)
                learned_sources[source_code] += 1
            else:
                classical_observations += 1

    equal_id_frames = missing = extra = coordinate_mismatch = 0
    quality_differences: list[float] = []
    for stamp in shared:
        ours_classic = {
            feature_id: values
            for feature_id, values in ours[stamp].items()
            if feature_id < 10_000_000 and int(round(values[5])) not in LEARNED_SOURCE_CODES
        }
        base = {
            feature_id: values
            for feature_id, values in klt[stamp].items()
            if feature_id < 10_000_000 and int(round(values[5])) not in LEARNED_SOURCE_CODES
        }
        ours_ids, base_ids = set(ours_classic), set(base)
        equal_id_frames += ours_ids == base_ids
        missing += len(base_ids - ours_ids)
        extra += len(ours_ids - base_ids)
        for feature_id in ours_ids & base_ids:
            if max(abs(ours_classic[feature_id][idx] - base[feature_id][idx]) for idx in range(4)) > 1e-6:
                coordinate_mismatch += 1
            quality_differences.append(abs(ours_classic[feature_id][4] - base[feature_id][4]))

    track_rows: list[dict[str, object]] = []
    first_stamp = ours_stamps[0] if ours_stamps else 0
    for feature_id, stamps in sorted(learned.items()):
        stamps = sorted(stamps)
        gaps = np.diff(np.asarray(stamps, dtype=np.float64)) * 1e-9
        longest_count, longest_duration = longest_contiguous(stamps, continuity_threshold)
        source_code = int(round(ours[stamps[0]][feature_id][5]))
        track_rows.append(
            {
                "stem": stem,
                "sequence": sequence,
                "feature_id": feature_id,
                "source_code": source_code,
                "observations": len(stamps),
                "first_s": (stamps[0] - first_stamp) * 1e-9,
                "last_s": (stamps[-1] - first_stamp) * 1e-9,
                "span_s": (stamps[-1] - stamps[0]) * 1e-9,
                "median_gap_s": float(np.median(gaps)) if len(gaps) else math.nan,
                "max_gap_s": float(np.max(gaps)) if len(gaps) else math.nan,
                "longest_contiguous_observations": longest_count,
                "longest_contiguous_span_s": longest_duration,
            }
        )

    parallax, skipped, raw_metric_frames = initial_skip_receipt(export_dir)
    source_summary = ";".join(f"{key}:{value}" for key, value in sorted(learned_sources.items()))
    track_lengths = [len(stamps) for stamps in learned.values()]
    track_spans = [(max(stamps) - min(stamps)) * 1e-9 for stamps in learned.values()]
    audit = {
        "stem": stem,
        "sequence": sequence,
        "export_dir": str(export_dir),
        "klt_export_dir": str(klt_export_dir),
        "feature_frames": len(ours),
        "klt_feature_frames": len(klt),
        "timestamp_schedule_exact": int(ours_stamps == klt_stamps),
        "shared_klt_frames": len(shared),
        "classical_idset_exact_shared_frames": equal_id_frames,
        "classical_common_geometry_exact": int(
            equal_id_frames == len(shared) and missing == 0 and extra == 0 and coordinate_mismatch == 0
        ),
        "classical_missing_observations": missing,
        "classical_extra_observations": extra,
        "classical_coordinate_mismatch_observations": coordinate_mismatch,
        "classical_quality_abs_diff_median": (
            float(np.median(quality_differences)) if quality_differences else math.nan
        ),
        "classical_observations": classical_observations,
        "learned_observations": sum(track_lengths),
        "learned_unique_ids": len(learned),
        "learned_source_code_histogram": source_summary,
        "learned_track_observations_median": (
            float(np.median(track_lengths)) if track_lengths else math.nan
        ),
        "learned_track_observations_max": max(track_lengths, default=0),
        "learned_track_span_max_s": max(track_spans, default=0.0),
        "learned_longest_contiguous_span_max_s": max(
            (number(row["longest_contiguous_span_s"]) for row in track_rows), default=0.0
        ),
        "feature_median_dt_s": median_dt,
        "feature_rate_hz": 1.0 / median_dt if math.isfinite(median_dt) and median_dt > 0 else math.nan,
        "init_parallax_mean_step_px": parallax,
        "init_skip_feature_frames": skipped,
        "raw_metric_frames": raw_metric_frames,
    }
    return audit, track_rows


def ablation_row(label: str, run_dir: Path, *, rate_hz: float, skip: object, arm: str) -> dict[str, object]:
    receipt = parse_kv(run_dir / "ape.txt")
    trajectory_path = run_dir / "vins_output/vio.csv"
    pose_count = 0
    if trajectory_path.is_file():
        pose_count = sum(bool(line.strip()) for line in trajectory_path.read_text(errors="replace").splitlines())
    return {
        "label": label,
        "arm": arm,
        "feature_rate_hz": rate_hz,
        "skip_feature_frames": skip,
        "run_dir": str(run_dir),
        "has_trajectory": int(pose_count > 0),
        "pose_count": pose_count,
        "se3_ape_rmse_m": number(receipt.get("se3_ape_rmse_m")),
        "rpe_trans_rmse_m": number(receipt.get("rpe_trans_rmse_m")),
        "output_coverage_ratio": number(receipt.get("output_coverage_ratio")),
        "first_output_delay_s": number(receipt.get("first_output_delay_s")),
    }


def summary_stats(values: list[float]) -> dict[str, float]:
    array = np.asarray([value for value in values if math.isfinite(value)], dtype=float)
    if not len(array):
        return {key: math.nan for key in ("mean", "std", "median", "q1", "q3")}
    return {
        "mean": float(np.mean(array)),
        "std": float(np.std(array, ddof=1)) if len(array) > 1 else math.nan,
        "median": float(np.median(array)),
        "q1": float(np.percentile(array, 25)),
        "q3": float(np.percentile(array, 75)),
    }


def short_labels(rows: list[dict[str, object]]) -> list[str]:
    labels = {
        "oceanfloor_track0_dark_s45_d45": "OF0-dark 45",
        "sandpipe_track0_dark_s45_d45": "SP0-dark 45",
        "oceanfloor_track1_light_s135_d45": "OF1-light 135",
        "oceanfloor_track1_light_s90_d45": "OF1-light 90",
        "oceanfloor_track0_light_s45_d45": "OF0-light 45",
        "sandpipe_track0_light_s45_d45": "SP0-light 45",
        "seafloor_track0_s0_d45": "SF0 0",
        "seafloor_track2_s0_d45": "SF2 0",
        "seafloor_track1_s45_d45": "SF1 45",
    }
    return [labels.get(str(row["stem"]), str(row["stem"])) for row in rows]


def plot_window_metrics(rows: list[dict[str, object]], figures: Path) -> None:
    labels = short_labels(rows)
    x = np.arange(len(rows), dtype=float)
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 6.2), sharex=True, constrained_layout=True)
    specs = (
        ("se3_ape_rmse_m", "SE(3) APE RMSE (m)", 5.0, (0.1, 2000.0)),
        ("rpe_trans_rmse_m", "1 s translational RPE RMSE (m)", 2.0, (0.03, 200.0)),
    )
    offsets = {"klt": -0.22, "original": 0.0, "ours": 0.22}
    for axis, (metric, ylabel, threshold, limits) in zip(axes, specs):
        for arm in ARMS:
            values = np.asarray([number(row[f"{arm}_{metric}"]) for row in rows])
            present = np.isfinite(values)
            axis.scatter(
                x[present] + offsets[arm],
                values[present],
                s=34,
                marker=ARM_MARKERS[arm],
                color=ARM_COLORS[arm],
                edgecolor="black",
                linewidth=0.35,
                label=ARM_LABELS[arm],
                zorder=3,
            )
            axis.scatter(
                x[~present] + offsets[arm],
                np.full(np.count_nonzero(~present), limits[0] * 1.18),
                s=28,
                marker="x",
                color=ARM_COLORS[arm],
                linewidth=1.2,
                zorder=3,
            )
        axis.axhline(threshold, color="#666666", linestyle="--", linewidth=1.0)
        axis.set_yscale("log")
        axis.set_ylim(*limits)
        axis.set_ylabel(ylabel)
        axis.grid(axis="y", which="both", alpha=0.22)
    axes[0].legend(ncol=3, loc="upper left", frameon=False)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=35, ha="right")
    axes[1].set_xlabel("Selected 45 s window (start time in s)")
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-01-window-metrics.{suffix}", dpi=300)
    plt.close(fig)


def plot_scale_diagnostic(arm_rows: list[dict[str, object]], figures: Path) -> None:
    usable = [row for row in arm_rows if int(row["has_trajectory"])]
    usable.sort(key=lambda row: number(row["se3_ape_rmse_m"]))
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.0, 6.0), constrained_layout=True)
    y = np.arange(len(usable))
    labels = [f"{str(row['stem']).replace('_s45_d45', '').replace('_s0_d45', '')} / {row['arm']}" for row in usable]
    for index, row in enumerate(usable):
        se3 = number(row["se3_ape_rmse_m"])
        sim3 = number(row["sim3_ape_rmse_m"])
        color = ARM_COLORS[str(row["arm"])]
        left.plot([sim3, se3], [index, index], color=color, alpha=0.55, linewidth=1.2)
        left.scatter(sim3, index, marker="o", facecolors="white", edgecolors=color, s=28, zorder=3)
        left.scatter(se3, index, marker="D", color=color, edgecolor="black", linewidth=0.25, s=30, zorder=3)
    left.set_xscale("log")
    left.set_xlabel("APE RMSE (m): open circle Sim(3), diamond SE(3)")
    left.set_yticks(y)
    left.set_yticklabels(labels, fontsize=7)
    left.grid(axis="x", which="both", alpha=0.22)

    for arm in ARMS:
        selected = [row for row in usable if row["arm"] == arm]
        right.scatter(
            [number(row["scale_inflation_est_over_gt"]) for row in selected],
            [number(row["se3_ape_rmse_m"]) for row in selected],
            color=ARM_COLORS[arm], marker=ARM_MARKERS[arm], s=36,
            edgecolor="black", linewidth=0.3, label=ARM_LABELS[arm],
        )
    right.axvline(1.0, color="#666666", linestyle="--", linewidth=1.0)
    right.axhline(5.0, color="#666666", linestyle=":", linewidth=1.0)
    right.set_xscale("log")
    right.set_yscale("log")
    right.set_xlabel("Estimated / GT path scale")
    right.set_ylabel("SE(3) APE RMSE (m)")
    right.grid(which="both", alpha=0.22)
    right.legend(frameon=False, fontsize=8)
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-02-scale-diagnostic.{suffix}", dpi=300)
    plt.close(fig)


def plot_ablation(rows: list[dict[str, object]], figures: Path) -> None:
    numeric = [row for row in rows if int(row["has_trajectory"])]
    x = np.arange(len(numeric))
    labels = [str(row["label"]) for row in numeric]
    colors = [ARM_COLORS.get(str(row["arm"]), "#777777") for row in numeric]
    fig, axes = plt.subplots(1, 2, figsize=(9.0, 3.8), constrained_layout=True)
    for axis, metric, ylabel in (
        (axes[0], "se3_ape_rmse_m", "SE(3) APE RMSE (m)"),
        (axes[1], "rpe_trans_rmse_m", "1 s RPE RMSE (m)"),
    ):
        values = [number(row[metric]) for row in numeric]
        axis.bar(x, values, color=colors, edgecolor="black", linewidth=0.4)
        axis.set_yscale("log")
        axis.set_ylabel(ylabel)
        axis.set_xticks(x)
        axis.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        axis.grid(axis="y", which="both", alpha=0.22)
    axes[0].text(
        0.02, 0.98, "11 Hz: KLT / no-LoFTR / full all empty",
        transform=axes[0].transAxes, va="top", fontsize=8,
        bbox={"facecolor": "white", "edgecolor": "#999999", "alpha": 0.9},
    )
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-03-initialization-ablation.{suffix}", dpi=300)
    plt.close(fig)


def paired_summary(rows: list[dict[str, object]], left: str, right: str, metric: str) -> dict[str, object]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        a, b = number(row[f"{left}_{metric}"]), number(row[f"{right}_{metric}"])
        if math.isfinite(a) and math.isfinite(b):
            pairs.append((a, b))
    deltas = np.asarray([b - a for a, b in pairs], dtype=float)
    relative = np.asarray([(b - a) / a * 100.0 for a, b in pairs], dtype=float)
    return {
        "n": len(pairs),
        "right_better": int(np.count_nonzero(deltas < 0)),
        "left_better": int(np.count_nonzero(deltas > 0)),
        "ties": int(np.count_nonzero(deltas == 0)),
        "median_delta": float(np.median(deltas)) if len(deltas) else math.nan,
        "median_relative_delta_pct": float(np.median(relative)) if len(relative) else math.nan,
    }


def build_analysis_report(
    rows: list[dict[str, object]], source_rows: list[dict[str, object]], ablations: list[dict[str, object]]
) -> str:
    counts = {
        arm: {
            "trajectory": sum(int(row[f"{arm}_has_trajectory"]) for row in rows),
            "availability": sum(str(row[f"{arm}_init_success"]) == "1" for row in rows),
            "accurate": sum(int(row[f"{arm}_metric_sanity_ape5_rpe2"]) for row in rows),
        }
        for arm in ARMS
    }
    sources = {str(row["stem"]): row for row in source_rows}
    learned_total = sum(int(row["learned_observations"]) for row in source_rows)
    learned_windows = sum(int(row["learned_observations"]) > 0 for row in source_rows)
    common_exact = sum(int(row["classical_common_geometry_exact"]) for row in source_rows)
    schedule_exact = sum(int(row["timestamp_schedule_exact"]) for row in source_rows)
    ours_klt_ape = paired_summary(rows, "klt", "ours", "se3_ape_rmse_m")
    ours_klt_rpe = paired_summary(rows, "klt", "ours", "rpe_trans_rmse_m")
    ablation = {str(row["label"]): row for row in ablations}
    lines = [
        "# MIMIR-UW rate-1 final analysis",
        "",
        "## Analysis question",
        "",
        "On the same nine purposively selected 45 s low-texture windows, compare pure external KLT, original VINS image tracking, and AQUA-FE (full mirrored KLT backbone plus gated learned sidecars); then determine whether large APE/RPE values come from the learned points or from the replay/initialization contract.",
        "",
        "## Key findings",
        "",
        "| Arm | Any trajectory | Availability gate | APE<=5 m and RPE<=2 m |",
        "|---|---:|---:|---:|",
    ]
    for arm in ARMS:
        lines.append(
            f"| {ARM_LABELS[arm]} | {counts[arm]['trajectory']}/9 | {counts[arm]['availability']}/9 | {counts[arm]['accurate']}/9 |"
        )
    lines.extend(
        [
            "",
            "The availability gate is only delay/coverage based; it is not an accuracy claim. The last column is an explicit diagnostic screen, not a published MIMIR benchmark threshold.",
            "",
            f"AQUA-FE and KLT have the same trajectory count (6/9), availability count (5/9), and diagnostic-accuracy count (1/9). Across the {ours_klt_ape['n']} shared non-empty trajectories, AQUA-FE has lower APE in {ours_klt_ape['right_better']}/{ours_klt_ape['n']} and lower RPE in {ours_klt_rpe['right_better']}/{ours_klt_rpe['n']}; the median paired relative changes are {ours_klt_ape['median_relative_delta_pct']:.2f}% APE and {ours_klt_rpe['median_relative_delta_pct']:.2f}% RPE. These are descriptive only.",
            "",
            "## Per-window receipts",
            "",
            "| Window | Pure KLT | Original VINS | AQUA-FE | Learned obs / IDs |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        cells = []
        for arm in ARMS:
            cells.append(
                f"{row[f'{arm}_status']}; {fmt(row[f'{arm}_se3_ape_rmse_m'])}/{fmt(row[f'{arm}_rpe_trans_rmse_m'])}"
            )
        source = sources[str(row["stem"])]
        lines.append(
            f"| `{row['sequence']}` {row['window_start_s']}-{row['window_end_s']} s | {cells[0]} | {cells[1]} | {cells[2]} | {source['learned_observations']} / {source['learned_unique_ids']} |"
        )
    lines.extend(
        [
            "",
            "## What caused the previously huge APE",
            "",
            "1. **Feature publication was too slow.** The old every-2 export was about 11 Hz while original VINS received about 22-24 Hz images. On SeaFloor/track1, KLT, no-LoFTR, and full AQUA-FE all produced empty trajectories at 11 Hz. Restoring every_n=1 produced a valid KLT trajectory (APE about 1.66 m).",
            f"2. **The first four low-parallax feature frames could force a wrong visual-inertial scale.** At rate 1, no-LoFTR/full with no skip yielded {fmt(ablation['no-LoFTR, skip 0']['se3_ape_rmse_m'])}/{fmt(ablation['full, skip 0']['se3_ape_rmse_m'])} m APE. Removing only those four feature messages, with IMU and GT unchanged, reduced them to {fmt(ablation['no-LoFTR, skip 4']['se3_ape_rmse_m'])}/{fmt(ablation['full, skip 4']['se3_ape_rmse_m'])} m.",
            "3. **The remaining large values are real scale/shape failures, not timestamp mismatch.** Timestamp association error in every scored receipt is zero. In SeaFloor/track0 and track2, Sim(3) reduces hundreds of metres of SE(3) APE to roughly 9-10 m, while estimated/GT path scale grows to about 34-50x and velocity exceeds 100 m/s. Sim(3) is diagnostic only and cannot replace fixed-scale SE(3) scoring.",
            "4. **Some windows also have trajectory-shape/orientation drift.** OceanFloor/track1_light 90-135 s remains near 9.5 m Sim(3) APE despite only a 0.70x scale; SeaFloor/track2 has large orientation residuals. Scale correction alone is therefore insufficient.",
            "",
            "## Learned-point and no-harm audit",
            "",
            f"AQUA-FE publishes {learned_total} learned observations in {learned_windows}/9 windows. The shared classical KLT ID/coordinate geometry is exact in {common_exact}/9 windows, and the frozen KLT initialization schedule makes the feature timestamps exact in {schedule_exact}/9 windows.",
            "",
            "| Window | Learned obs | IDs | Max obs/ID | Longest contiguous span | Init parallax / skipped |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        source = sources[str(row["stem"])]
        lines.append(
            f"| `{row['sequence']}` {row['window_start_s']}-{row['window_end_s']} s | "
            f"{source['learned_observations']} | {source['learned_unique_ids']} | "
            f"{source['learned_track_observations_max']} | "
            f"{fmt(source['learned_longest_contiguous_span_max_s'], 3)} s | "
            f"{fmt(source['init_parallax_mean_step_px'], 3)} px / {source['init_skip_feature_frames']} |"
        )
    lines.extend(
        [
            "",
            "The only accuracy-screen positive is SeaFloor/track1 45-90 s. There, pure KLT is 1.657689/0.229495 m, no-LoFTR with the same four-frame skip is 1.648392/0.229785 m, and full AQUA-FE is 1.634598/0.229477 m. Thus q_i alone gives a small APE change, and learned geometry gives a further small APE change; neither supports a broad superiority claim from one deterministic run.",
            "",
            "No learned-point window creates a new backend-availability success over KLT. OceanFloor/track1_light 135-180 s contains many learned observations but starts with only about 0.30 px mean parallax and still never initializes; the learned burst begins late and cannot repair the initial visual-inertial structure.",
            "",
            "## Why KLT/AQUA-FE and original VINS disagree",
            "",
            "- OceanFloor/track0_light is the only original-VINS availability PASS where KLT/AQUA-FE are partial. The external arms miss the 15 s delay threshold by only 0.054 s, yet their APE (~20.4 m) is much lower than original VINS (~110.5 m). This is a threshold-boundary/lifecycle difference, not an original-VINS accuracy win.",
            "- OceanFloor/track1_light 90-135 s and SandPipe/track0_light are the reverse: KLT/AQUA-FE initialize early, whereas original VINS begins around 20 s and is partial. The internal and external trackers have different feature density and lifecycle.",
            "- In the dark/very-low-parallax failures, logs are dominated by `IMU excitation not enouth` and `Not enough features or parallax`. A few late or one-frame learned points cannot satisfy the multi-view initialization constraint.",
            "",
            "## Decision",
            "",
            "- Keep rate-1 feature publication, the full mirror KLT backbone, preserved classical budget, persistent LoFTR lineage, and the seeded-continuation gate.",
            "- Freeze AQUA-FE's initialization skip schedule from the pure-KLT frontend receipt for formal paired comparisons.",
            "- Retain fixed-scale SE(3) APE/RPE as primary. Do not use the high-APE runs as positive evidence and do not claim a new learned-point availability positive on MIMIR-UW.",
            "- Next backend work should reject/reinitialize implausible scale using initializer diagnostics; simply adding more learned points is not supported by these data.",
            "",
            "## Claim Candidates",
            "",
            "- Claim:",
            "  - Source evidence: `comparison.csv`, `source_audit.csv`, `ablation.csv`.",
            "  - Allowed wording: In these nine selected MIMIR-UW windows, the corrected AQUA-FE profile preserves the common KLT geometry and matches KLT availability, with one small learned-geometry APE positive on SeaFloor/track1.",
            "  - Forbidden stronger wording: AQUA-FE significantly or generally outperforms KLT/VINS on MIMIR-UW.",
            "  - Uncertainty: one seed, purposive windows, no independent sequence-level replication.",
            "  - Next check: repeat multiple backend seeds and test additional predeclared windows.",
            "  - Decision: keep",
            "",
            "- Claim:",
            "  - Source evidence: `trajectory_diagnostics.csv`, `figure-02-scale-diagnostic.pdf`.",
            "  - Allowed wording: The largest fixed-scale errors are dominated by visual-inertial scale failure and accompanied by shape/orientation drift.",
            "  - Forbidden stronger wording: Sim(3)-aligned values are valid replacements for VIO APE.",
            "  - Uncertainty: the exact backend state causing each scale failure still needs initializer-state intervention tests.",
            "  - Next check: add scale plausibility rejection/reinitialization, not post-hoc alignment.",
            "  - Decision: keep",
        ]
    )
    return "\n".join(lines) + "\n"


def build_stats_appendix(rows: list[dict[str, object]]) -> str:
    lines = [
        "# Statistical appendix",
        "",
        "## Design and valid unit",
        "",
        "The comparison unit is one preselected 45 s window. There are nine windows but only seven underlying sequence/track identities, including two windows from OceanFloor/track1_light. Each arm uses one deterministic VINS RANSAC seed (0). Pose samples within a trajectory are temporally dependent and are not independent replicates.",
        "",
        "The windows were deliberately selected for low texture, not sampled from a population. Therefore confidence intervals, paired significance tests, and population-level superiority claims are blocked. Missing trajectories are non-random failures and are never imputed as numeric APE/RPE.",
        "",
        "## Descriptive statistics among non-empty trajectories",
        "",
        "| Arm | Metric | n | Mean ± SD | Median [IQR] |",
        "|---|---|---:|---:|---:|",
    ]
    for arm in ARMS:
        for metric, label in (("se3_ape_rmse_m", "SE(3) APE (m)"), ("rpe_trans_rmse_m", "RPE (m)")):
            values = [number(row[f"{arm}_{metric}"]) for row in rows]
            stats = summary_stats(values)
            n = sum(math.isfinite(value) for value in values)
            lines.append(
                f"| {ARM_LABELS[arm]} | {label} | {n} | {fmt(stats['mean'])} ± {fmt(stats['std'])} | {fmt(stats['median'])} [{fmt(stats['q1'])}, {fmt(stats['q3'])}] |"
            )
    lines.extend(["", "## Paired descriptive contrasts", ""])
    for baseline in ("klt", "original"):
        for metric, label in (("se3_ape_rmse_m", "APE"), ("rpe_trans_rmse_m", "RPE")):
            paired = paired_summary(rows, baseline, "ours", metric)
            lines.append(
                f"- {ARM_LABELS[baseline]} vs AQUA-FE, {label}: n={paired['n']} shared non-empty windows; AQUA-FE lower in {paired['right_better']}, higher in {paired['left_better']}, ties {paired['ties']}; median AQUA-FE-minus-baseline delta {paired['median_delta']:.6f} m ({paired['median_relative_delta_pct']:.3f}%)."
            )
    lines.extend(
        [
            "",
            "## Inferential-test blocker",
            "",
            "No p-value or 95% CI is reported. A Wilcoxon/sign test over these rows would incorrectly treat purposively selected, partially repeated sequence windows as a population sample, while one backend seed provides no estimate of algorithmic run-to-run variance. The correct next evidence is multi-seed replay plus additional predeclared windows.",
            "",
            "## Threshold scope",
            "",
            "Availability PASS follows the existing receipt gate (trajectory length, first output delay, and coverage). APE<=5 m and RPE<=2 m is an explicit conservative debugging screen only; it is not a dataset-standard success threshold and was not optimized as a benchmark endpoint.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_figure_catalog() -> str:
    return """# Figure catalog

## Figure 01 — window metrics

- Filename: `figures/figure-01-window-metrics.pdf`
- Purpose: show every available fixed-scale APE/RPE receipt without hiding empty trajectories.
- Data source: `comparison.csv`; nine selected windows, one deterministic seed per arm.
- Caption requirements: log axes; dashed lines are the exploratory 5 m APE and 2 m RPE screens; crosses at the lower boundary denote empty trajectories, not zero error; no error bars exist because n=1 per arm/window.
- Key observation: only SeaFloor/track1 passes both diagnostic screens for KLT/AQUA-FE; several availability-pass trajectories have catastrophic metric values.
- Interpretation: availability and metric usability must be reported separately.
- Caveat: the diagnostic thresholds are not official MIMIR criteria.

## Figure 02 — scale diagnostic

- Filename: `figures/figure-02-scale-diagnostic.pdf`
- Purpose: distinguish fixed-scale failure from residual trajectory-shape error.
- Data source: `trajectory_diagnostics.csv`; all non-empty trajectories.
- Caption requirements: diamonds are primary SE(3) APE, open circles are diagnostic Sim(3) APE; right panel uses estimated/GT path scale; both axes are logarithmic where shown.
- Key observation: SeaFloor track0/track2 shrink from hundreds of metres under SE(3) to roughly 9-10 m under Sim(3), with 34-50x path scale, but non-zero Sim(3) error remains.
- Interpretation: scale initialization dominates the largest failures, while remaining Sim(3) and orientation error show additional shape drift.
- Caveat: Sim(3) must not replace fixed-scale VIO scoring.

## Figure 03 — initialization ablation

- Filename: `figures/figure-03-initialization-ablation.pdf`
- Purpose: isolate feature rate and the first-four-frame initialization effect on SeaFloor/track1.
- Data source: `ablation.csv`; exact single-seed receipts.
- Caption requirements: 11 Hz KLT/no-LoFTR/full all produced empty trajectories; numeric bars are 22 Hz runs; skip-4 bags remove only the first four feature messages while preserving IMU and GT.
- Key observation: no-LoFTR/full APE drops from 56.3/136.0 m to about 1.65/1.63 m after the four-frame timing correction.
- Interpretation: the previously huge representative APE was caused by early visual-inertial initialization, not by learned-point quality alone.
- Caveat: this causal ablation is one window and one seed.
"""


def main() -> int:
    args = parse_args()
    selected = read_csv(args.selected_windows)
    if len(selected) != 9:
        raise SystemExit(f"expected nine selected windows, found {len(selected)}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    figures = args.output_dir / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    gt_cache: dict[Path, list[tuple[float, np.ndarray, np.ndarray]]] = {}
    comparison_rows: list[dict[str, object]] = []
    arm_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    track_rows: list[dict[str, object]] = []
    for source in selected:
        stem = safe_stem(source)
        klt_run = args.run_root / f"{args.baseline_prefix}_{stem}_klt_vins_seed0"
        original_run = args.run_root / f"{args.baseline_prefix}_{stem}_original_vins_seed0"
        klt_export = args.run_root / f"{args.baseline_prefix}_{stem}_klt_export"
        ours_run, ours_export, resolved_prefix = choose_ours_dirs(args, stem)
        manifest = parse_kv(klt_run / "comparison_arm_manifest.txt")
        raw_bag = Path(manifest["raw_bag"])
        gt = gt_cache.setdefault(raw_bag, load_gt(raw_bag))
        row: dict[str, object] = {
            "stem": stem,
            "sequence": source["sequence"],
            "window_start_s": compact(source["window_start_s"]),
            "window_end_s": compact(source["window_end_s"]),
            "ours_resolved_prefix": resolved_prefix,
        }
        for arm, run_dir in (("klt", klt_run), ("original", original_run), ("ours", ours_run)):
            diag = trajectory_diagnostics(run_dir, gt)
            diag_row = {"stem": stem, "sequence": source["sequence"], "arm": arm, **diag}
            arm_rows.append(diag_row)
            row[f"{arm}_status"] = status(diag)
            for key, value in diag.items():
                row[f"{arm}_{key}"] = value
        comparison_rows.append(row)
        audit, tracks = audit_export(
            stem=stem,
            sequence=source["sequence"],
            export_dir=ours_export,
            klt_export_dir=klt_export,
        )
        source_rows.append(audit)
        track_rows.extend(tracks)

    ablations = [
        ablation_row("KLT, 11 Hz", args.rate2_klt_run, rate_hz=11.1, skip="adaptive", arm="klt"),
        ablation_row("no-LoFTR, 11 Hz", args.rate2_noloftr_run, rate_hz=11.1, skip="adaptive", arm="klt"),
        ablation_row("full, 11 Hz", args.rate2_full_run, rate_hz=11.1, skip="adaptive", arm="ours"),
        ablation_row("no-LoFTR, skip 0", args.noloftr_skip0_run, rate_hz=22.2, skip=0, arm="klt"),
        ablation_row("full, skip 0", args.full_skip0_run, rate_hz=22.2, skip=0, arm="ours"),
        ablation_row(
            "KLT, skip 4",
            args.run_root / "mimir_rate1_final_v1_seafloor_track1_s45_d45_klt_vins_seed0",
            rate_hz=22.2, skip=4, arm="klt",
        ),
        ablation_row("no-LoFTR, skip 4", args.noloftr_skip4_run, rate_hz=22.2, skip=4, arm="klt"),
        ablation_row("full, skip 4", args.full_skip4_run, rate_hz=22.2, skip=4, arm="ours"),
    ]

    write_csv(args.output_dir / "comparison.csv", comparison_rows)
    write_csv(args.output_dir / "trajectory_diagnostics.csv", arm_rows)
    write_csv(args.output_dir / "source_audit.csv", source_rows)
    write_csv(args.output_dir / "learned_tracks.csv", track_rows)
    write_csv(args.output_dir / "ablation.csv", ablations)
    plot_window_metrics(comparison_rows, figures)
    plot_scale_diagnostic(arm_rows, figures)
    plot_ablation(ablations, figures)
    (args.output_dir / "analysis-report.md").write_text(
        build_analysis_report(comparison_rows, source_rows, ablations), encoding="utf-8"
    )
    (args.output_dir / "stats-appendix.md").write_text(
        build_stats_appendix(comparison_rows), encoding="utf-8"
    )
    (args.output_dir / "figure-catalog.md").write_text(
        build_figure_catalog(), encoding="utf-8"
    )
    print(f"wrote strict analysis bundle: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
