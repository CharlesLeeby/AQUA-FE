#!/usr/bin/env python3
"""Build compact comparison tables and figures for the pool lifetime audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


SEQUENCES = ("171342", "171944", "172529")
CAUSES = ("forward_fail", "backward_fail", "fb_fail", "ncc_fail", "border_fail")
COLORS = {"original": "#D55E00", "process_all": "#0072B2"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/home/ma/real_pool_frontend_lifetime_diag")
    return parser.parse_args()


def histogram(path: Path, lineage: str = "gftt_klt") -> Counter[int]:
    result: Counter[int] = Counter()
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row["lineage"] == lineage:
            result[int(row["lifetime_selected_frames"])] += int(row["track_count"])
    return result


def quantile(counter: Counter[int], q: float) -> float:
    total = sum(counter.values())
    rank = q * (total - 1)
    cumulative = 0
    for value in sorted(counter):
        cumulative += counter[value]
        if rank < cumulative:
            return float(value)
    return float("nan")


def share(counter: Counter[int], predicate) -> float:
    total = sum(counter.values())
    return sum(count for life, count in counter.items() if predicate(life)) / max(1, total)


def binned(counter: Counter[int]) -> list[float]:
    predicates = (
        lambda x: x == 1,
        lambda x: x == 2,
        lambda x: 3 <= x <= 4,
        lambda x: 5 <= x <= 9,
        lambda x: x >= 10,
    )
    return [share(counter, predicate) for predicate in predicates]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def make_comparison(root: Path) -> pd.DataFrame:
    rows = []
    for sequence in SEQUENCES:
        base_dir = root / "full" / "baseline_existing" / sequence
        fixed_dir = root / "full" / "hybrid_processall" / sequence
        if not (fixed_dir / "summary.json").exists():
            continue
        base = read_json(base_dir / "summary.json")
        fixed = read_json(fixed_dir / "summary.json")
        base_hist = histogram(base_dir / "lifetime_histogram.csv")
        fixed_hist = histogram(fixed_dir / "lifetime_histogram.csv")
        base_metrics = pd.read_csv(base_dir / "per_frame_lineage.csv")
        for profile, summary, counts in (
            ("original", base, base_hist),
            ("process_all", fixed, fixed_hist),
        ):
            if profile == "original":
                candidates = int(base_metrics["learned_candidates"].sum())
                confirmed = int(base_metrics["xfeat_confirmed"].sum())
                dropout = float(base["selected_median_dropout_ratio"])
            else:
                candidates = int(fixed["xfeat_candidates_total"])
                confirmed = int(fixed["xfeat_confirmed_total"])
                dropout = float(fixed["selected_median_dropout_ratio"])
            rows.append(
                {
                    "sequence": sequence,
                    "profile": profile,
                    "selected_output_hz": 10,
                    "complete_gftt_tracks": sum(counts.values()),
                    "lifetime_1_fraction": share(counts, lambda x: x == 1),
                    "lifetime_gt1_fraction": share(counts, lambda x: x > 1),
                    "lifetime_gt2_fraction": share(counts, lambda x: x > 2),
                    "lifetime_ge5_fraction": share(counts, lambda x: x >= 5),
                    "lifetime_median_selected_frames": quantile(counts, 0.5),
                    "lifetime_p75_selected_frames": quantile(counts, 0.75),
                    "lifetime_p90_selected_frames": quantile(counts, 0.9),
                    "median_transition_dropout_ratio": dropout,
                    "xfeat_candidates": candidates,
                    "xfeat_confirmed": confirmed,
                    "xfeat_complete_tracks": int(summary["xfeat_complete_track_count"]),
                    "xfeat_lifetime_median_selected_frames": float(summary["xfeat_lifetime_median_selected_frames"]),
                }
            )
    frame = pd.DataFrame(rows)
    frame.to_csv(root / "before_after_summary.csv", index=False)
    return frame


def make_cadence_histogram_figure(root: Path, comparison: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(12.0, 3.6), sharey=True, constrained_layout=True)
    labels = ["1", "2", "3–4", "5–9", "≥10"]
    x = np.arange(len(labels))
    width = 0.37
    for axis, sequence in zip(axes, SEQUENCES):
        for offset, profile in ((-width / 2, "original"), (width / 2, "process_all")):
            path = root / "full" / ("baseline_existing" if profile == "original" else "hybrid_processall") / sequence / "lifetime_histogram.csv"
            values = binned(histogram(path))
            axis.bar(x + offset, values, width, label=profile.replace("_", " "), color=COLORS[profile])
        subset = comparison[comparison.sequence.astype(str) == sequence].set_index("profile")
        base_l1 = 100 * subset.loc["original", "lifetime_1_fraction"]
        fixed_l1 = 100 * subset.loc["process_all", "lifetime_1_fraction"]
        axis.set_title(f"{sequence}\nL=1: {base_l1:.1f}% → {fixed_l1:.1f}%")
        axis.set_xticks(x, labels)
        axis.set_xlabel("complete GFTT lifetime (10 Hz output frames)")
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("fraction of completed tracks")
    axes[0].legend(frameon=False)
    fig.suptitle("Real-pool GFTT lifetime: process every camera frame helps, but median stays 1")
    fig.savefig(root / "lifetime_cadence_only_full.png", dpi=180)
    fig.savefig(root / "lifetime_cadence_only_full.pdf")
    plt.close(fig)


def make_probe_tables(root: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    records = []
    for path in sorted((root / "probes").glob("*_s*_*/summary.json")):
        match = re.fullmatch(
            r"(\d+)_s(\d+)_(baseline|processall|adaptiveclahe|gftt_confirmed|processall_gftt_confirmed)",
            path.parent.name,
        )
        if not match:
            continue
        sequence, start, profile = match.groups()
        summary = read_json(path)
        record = {
            "sequence": sequence,
            "start_raw_index": int(start),
            "profile": profile,
            "processed_frames": summary["processed_frames"],
            "selected_frames": summary["selected_frames"],
            "median_dropout_ratio_per_transition": summary["selected_median_dropout_ratio"],
            "median_internal_age_processed_frames": summary["selected_median_track_age"],
            "median_internal_age_seconds_approx": summary["selected_median_track_age"] / (20 if profile == "processall" else 10),
            "median_motion_px_per_transition": summary["selected_median_motion_px"],
            "flat_region_ratio": summary["selected_median_raw_flat_region_ratio"],
            "contrast": summary["selected_median_raw_contrast"],
            "laplacian_variance": summary["selected_median_raw_laplacian_var"],
            "degradation_score": summary["selected_median_raw_degradation_score"],
            "lifetime_p75_selected_frames": summary["gftt_klt_lifetime_p75_selected_frames"],
            "lifetime_p90_selected_frames": summary["gftt_klt_lifetime_p90_selected_frames"],
            "output_tracks_median": summary["selected_median_output_tracks"],
            "output_grid_coverage_median": summary.get("selected_median_output_grid_coverage", float("nan")),
        }
        for cause in CAUSES:
            record[f"death_{cause}"] = summary["klt_death_reason_counts"].get(cause, 0)
            record[f"death_{cause}_fraction"] = summary["klt_death_reason_fractions"].get(cause, 0.0)
        records.append(record)
    probes = pd.DataFrame(records)
    probes.to_csv(root / "probe_window_summary.csv", index=False)

    baseline_csvs = sorted((root / "probes").glob("*_s*_baseline/per_frame.csv"))
    baseline_frames = pd.concat((pd.read_csv(path) for path in baseline_csvs), ignore_index=True)
    variables = [
        "dropout_ratio",
        "raw_flat_region_ratio",
        "raw_degradation_score",
        "median_motion_px",
        "interframe_mean_absdiff",
        "raw_contrast",
        "raw_laplacian_var",
        "raw_blur_score",
    ]
    correlations = (
        baseline_frames[variables]
        .corr(method="spearman")["dropout_ratio"]
        .rename("spearman_with_dropout")
        .rename_axis("variable")
        .reset_index()
    )
    correlations.to_csv(root / "quality_dropout_spearman.csv", index=False)
    return probes, baseline_frames


def make_rootfix_table_and_figure(root: Path, probes: pd.DataFrame) -> None:
    rows = []
    for sequence in SEQUENCES:
        for profile in ("baseline", "processall", "adaptiveclahe", "gftt_confirmed", "processall_gftt_confirmed"):
            directory = root / "probes" / f"{sequence}_s0_{profile}"
            counts = histogram(directory / "lifetime_histogram.csv")
            frame = pd.read_csv(directory / "per_frame.csv")
            selected = frame[frame.selected_for_output == 1]
            coverage = (
                float(selected.output_grid_coverage.median())
                if "output_grid_coverage" in selected
                else float("nan")
            )
            rows.append(
                {
                    "sequence": sequence,
                    "window_raw_frames": "0:300",
                    "profile": profile,
                    "single_variable_role": {
                        "baseline": "frozen original",
                        "processall": "cadence only",
                        "adaptiveclahe": "preprocess only",
                        "gftt_confirmed": "birth semantics only",
                        "processall_gftt_confirmed": "combined candidate repair",
                    }[profile],
                    "lifetime_1_fraction": share(counts, lambda x: x == 1),
                    "lifetime_median_selected_frames": quantile(counts, 0.5),
                    "lifetime_p75_selected_frames": quantile(counts, 0.75),
                    "lifetime_p90_selected_frames": quantile(counts, 0.9),
                    "output_tracks_median": float(selected.output_tracks.median()),
                    "output_tracks_p10": float(selected.output_tracks.quantile(0.1, interpolation="lower")),
                    "output_grid_coverage_median": coverage,
                    "output_grid_coverage_p10": (
                        float(selected.output_grid_coverage.quantile(0.1, interpolation="lower"))
                        if "output_grid_coverage" in selected
                        else float("nan")
                    ),
                    "median_dropout_per_processed_transition": float(selected.dropout_ratio.median()),
                    "pending_gftt_candidates_median": (
                        float(selected.gftt_pending_candidates.median())
                        if "gftt_pending_candidates" in selected
                        else float("nan")
                    ),
                }
            )
    table = pd.DataFrame(rows)
    table.to_csv(root / "rootfix_s0_summary.csv", index=False)

    fig, axes = plt.subplots(1, 3, figsize=(12.2, 3.8), sharey=True, constrained_layout=True)
    labels = ["1", "2", "3–4", "5–9", "≥10"]
    x = np.arange(len(labels))
    width = 0.37
    for axis, sequence in zip(axes, SEQUENCES):
        for offset, profile, label in (
            (-width / 2, "baseline", "original"),
            (width / 2, "processall_gftt_confirmed", "process all + confirm births"),
        ):
            directory = root / "probes" / f"{sequence}_s0_{profile}"
            values = binned(histogram(directory / "lifetime_histogram.csv"))
            color = COLORS["original"] if profile == "baseline" else COLORS["process_all"]
            axis.bar(x + offset, values, width, label=label, color=color)
        subset = table[(table.sequence.astype(str) == sequence) & (table.profile == "processall_gftt_confirmed")].iloc[0]
        axis.set_title(
            f"{sequence}: median {int(subset.lifetime_median_selected_frames)}\n"
            f"tracks med/p10 {subset.output_tracks_median:.0f}/{subset.output_tracks_p10:.0f}"
        )
        axis.set_xticks(x, labels)
        axis.set_xlabel("complete lifetime (10 Hz output frames)")
        axis.grid(axis="y", alpha=0.25)
    axes[0].set_ylabel("fraction of completed tracks")
    axes[0].legend(frameon=False, fontsize=8)
    fig.suptitle("High-churn first 15 s: temporal birth semantics moves the median past 1, with supply cost")
    fig.savefig(root / "lifetime_before_after.png", dpi=180)
    fig.savefig(root / "lifetime_before_after.pdf")
    plt.close(fig)


def make_death_figure(root: Path, probes: pd.DataFrame) -> None:
    baseline = probes[probes.profile == "baseline"]
    rows = []
    for sequence, group in baseline.groupby("sequence"):
        totals = np.array([group[f"death_{cause}"].sum() for cause in CAUSES], dtype=float)
        totals /= totals.sum()
        rows.append((str(sequence), totals))
    fig, axis = plt.subplots(figsize=(8.2, 3.5), constrained_layout=True)
    bottom = np.zeros(len(rows))
    palette = ["#56B4E9", "#009E73", "#E69F00", "#CC79A7", "#999999"]
    for index, cause in enumerate(CAUSES):
        values = np.array([row[1][index] for row in rows])
        axis.bar([row[0] for row in rows], values, bottom=bottom, label=cause.replace("_", " "), color=palette[index])
        bottom += values
    axis.set_ylim(0, 1)
    axis.set_ylabel("fraction of KLT deaths")
    axis.set_xlabel("sequence (three stratified 15 s windows combined)")
    axis.legend(ncol=3, frameon=False, fontsize=8, loc="upper center", bbox_to_anchor=(0.5, 1.19))
    axis.grid(axis="y", alpha=0.2)
    fig.savefig(root / "klt_death_causes.png", dpi=180)
    fig.savefig(root / "klt_death_causes.pdf")
    plt.close(fig)


def make_quality_figure(root: Path, frames: pd.DataFrame) -> None:
    usable = frames.replace([np.inf, -np.inf], np.nan).dropna(subset=["dropout_ratio", "raw_flat_region_ratio", "median_motion_px"])
    fig, axes = plt.subplots(1, 2, figsize=(9.5, 3.7), constrained_layout=True)
    axes[0].hexbin(usable.raw_flat_region_ratio, usable.dropout_ratio, gridsize=28, mincnt=1, cmap="viridis")
    axes[0].set(xlabel="flat-region ratio", ylabel="KLT dropout", title="Flat imagery raises churn")
    axes[1].hexbin(usable.median_motion_px, usable.dropout_ratio, gridsize=28, mincnt=1, cmap="viridis", xscale="log")
    axes[1].set(xlabel="median surviving motion (px, log)", ylabel="KLT dropout", title="Motion compounds the failure")
    for axis in axes:
        axis.grid(alpha=0.15)
    fig.savefig(root / "quality_motion_dropout.png", dpi=180)
    fig.savefig(root / "quality_motion_dropout.pdf")
    plt.close(fig)


def closest_overlay(directory: Path, target: int) -> Path:
    candidates = list(directory.glob("frame_*.jpg"))
    if not candidates:
        raise FileNotFoundError(directory)
    return min(candidates, key=lambda path: abs(int(path.name.split("_")[1]) - target))


def make_overlay_montage(root: Path) -> None:
    fig, axes = plt.subplots(3, 2, figsize=(12.8, 8.1), constrained_layout=True)
    for row_index, sequence in enumerate(SEQUENCES):
        for col_index, profile in enumerate(("baseline", "processall")):
            directory = root / "probes" / f"{sequence}_s0_{profile}" / "overlays"
            path = closest_overlay(directory, 150)
            image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            axes[row_index, col_index].imshow(image)
            axes[row_index, col_index].set_title(f"{sequence} — {profile} — {path.stem}")
            axes[row_index, col_index].axis("off")
    fig.suptitle("Same frames and thresholds; only intermediate-frame tracking differs")
    fig.savefig(root / "overlay_samples_before_after.jpg", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(12.8, 8.1), constrained_layout=True)
    for row_index, sequence in enumerate(SEQUENCES):
        for col_index, profile in enumerate(("baseline", "processall_gftt_confirmed")):
            directory = root / "probes" / f"{sequence}_s0_{profile}" / "overlays"
            path = closest_overlay(directory, 150)
            image = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
            axes[row_index, col_index].imshow(image)
            axes[row_index, col_index].set_title(f"{sequence} — {profile} — {path.stem}")
            axes[row_index, col_index].axis("off")
    fig.suptitle("Root-fix probe: unconfirmed GFTT births are no longer public tracks")
    fig.savefig(root / "overlay_samples_rootfix.jpg", dpi=140)
    plt.close(fig)

    high = cv2.cvtColor(
        cv2.imread(str(root / "probes" / "171342_s0_baseline" / "overlays" / "frame_000140_event.jpg")),
        cv2.COLOR_BGR2RGB,
    )
    calm_path = root / "overlays_calm" / "171342_s2200" / "overlays" / "frame_002260_periodic.jpg"
    calm = cv2.cvtColor(cv2.imread(str(calm_path)), cv2.COLOR_BGR2RGB)
    fig, axes = plt.subplots(1, 2, figsize=(12.8, 4.4), constrained_layout=True)
    for axis, image, title in (
        (axes[0], high, "171342 raw 140: flat/moving, dropout 0.697"),
        (axes[1], calm, "171342 raw 2260: textured/calm, dropout 0.011"),
    ):
        axis.imshow(image)
        axis.set_title(title)
        axis.axis("off")
    fig.suptitle("Same camera, bag, calibration, and thresholds: this is a local regime boundary")
    fig.savefig(root / "texture_regime_boundary.jpg", dpi=150)
    plt.close(fig)


def make_input_and_config_manifests(root: Path) -> None:
    audits = pd.concat(
        (
            pd.read_csv(root / "input_audit_early" / "imgshift_audit.csv"),
            pd.read_csv(root / "input_audit_172529" / "imgshift_audit.csv"),
        ),
        ignore_index=True,
    ).sort_values("sequence")
    audits.to_csv(root / "imgshift_audit.csv", index=False)

    paths = [
        Path("/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
        Path("/home/ma/AQUA-FE_WS/uw_frontend/configs/experiments/real_pool_gftt_confirmed_diagnostic.yaml"),
        Path("/mnt/data/Dataset_pool/aqua_fe_real_pool_vins/front_cam_20260415_pinhole.yaml"),
        Path("/home/ma/AQUA-FE_WS/external_tools/accelerated_features/weights/xfeat.pt"),
    ]
    rows = []
    for path in paths:
        rows.append(
            {
                "path": str(path),
                "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    pd.DataFrame(rows).to_csv(root / "config_manifest.csv", index=False)


def validate_csv_integrity(root: Path) -> None:
    expected = {}
    for sequence, frames, raw_frames in (("171342", 1325, 2650), ("171944", 1037, 2074), ("172529", 3597, 7193)):
        expected[str(root / "full" / "baseline_existing" / sequence / "per_frame_lineage.csv")] = frames
        expected[str(root / "full" / "hybrid_processall" / sequence / "per_frame.csv")] = raw_frames
    for path in root.glob("probes/*/per_frame.csv"):
        expected.setdefault(str(path), None)
    rows = []
    for path_string, expected_rows in sorted(expected.items()):
        path = Path(path_string)
        with path.open(newline="", encoding="utf-8") as handle:
            records = list(csv.reader(handle))
        header = records[0]
        widths_ok = all(len(record) == len(header) for record in records[1:])
        data_rows = len(records) - 1
        count_ok = expected_rows is None or data_rows == expected_rows
        rows.append(
            {
                "path": str(path),
                "data_rows": data_rows,
                "expected_rows": "" if expected_rows is None else expected_rows,
                "column_count": len(header),
                "unique_header": int(len(header) == len(set(header))),
                "consistent_row_width": int(widths_ok),
                "row_count_matches": int(count_ok),
                "status": "pass" if widths_ok and len(header) == len(set(header)) and count_ok else "fail",
            }
        )
    pd.DataFrame(rows).to_csv(root / "csv_integrity.csv", index=False)
    failures = [row for row in rows if row["status"] != "pass"]
    if failures:
        raise RuntimeError(f"CSV integrity failures: {failures}")


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    comparison = make_comparison(root)
    if set(comparison.sequence.astype(str)) != set(SEQUENCES):
        missing = sorted(set(SEQUENCES) - set(comparison.sequence.astype(str)))
        raise RuntimeError(f"missing completed full runs: {missing}")
    make_cadence_histogram_figure(root, comparison)
    probes, frames = make_probe_tables(root)
    make_rootfix_table_and_figure(root, probes)
    make_death_figure(root, probes)
    make_quality_figure(root, frames)
    make_overlay_montage(root)
    make_input_and_config_manifests(root)
    validate_csv_integrity(root)
    print(f"artifacts={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
