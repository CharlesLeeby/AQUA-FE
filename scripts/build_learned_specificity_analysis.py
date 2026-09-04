#!/usr/bin/env python3
"""Build the machine summary and descriptive figure for the learned audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-root",
        type=Path,
        default=Path("/mnt/data/AQUA-FE_WS/validation_20260803"),
    )
    parser.add_argument(
        "--a02-run",
        type=Path,
        default=Path(
            "/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins/"
            "external_hybrid_superpoint_lightglue_every2_"
            "validation_20260803_a02_2800_3200_loftr"
        ),
    )
    parser.add_argument(
        "--ntnu-validation-root",
        type=Path,
        default=Path("/mnt/data/AQUA-FE_WS/validation_20260804"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def parse_key_values(path: Path) -> dict[str, object]:
    result: dict[str, object] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, raw = line.split("=", 1)
        try:
            result[key] = float(raw)
        except ValueError:
            result[key] = raw
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"no rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def a08_legacy_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for replay in (1, 2, 3):
        paths = {
            "learned": root / f"a08_full_replay_r{replay}" / "ape.txt",
            "classical_preserve_id": (
                root / f"a08_gftt_preserve_id_replay_r{replay}" / "ape.txt"
            ),
        }
        for arm, path in paths.items():
            values = parse_key_values(path)
            rows.append(
                {
                    "dataset": "AQUALOC",
                    "window": "A08_4500_4660",
                    "profile": "oldcontract_microburst",
                    "evaluator": "legacy_nearest_reference",
                    "arm": arm,
                    "replay": replay,
                    "scientific_unit": "A08_4500_4660_event",
                    "technical_repeat": True,
                    "ape_rmse_m": values["se3_ape_rmse_m"],
                    "rpe_rmse_m": values["rpe_trans_rmse_m"],
                    "coverage": values["output_coverage_ratio"],
                    "init_success": int(values["init_success"]),
                    "solver_failures": int(values["log_linear_solver_failures"]),
                    "rpe_pairs": int(values["rpe_pairs"]),
                    "ape_valid": False,
                    "rpe_valid": False,
                    "validity_reason": "only 7 unique GT assignments; reference reuse",
                    "source_artifact": str(path),
                }
            )
    return rows


def common_support_rows(
    path: Path,
    dataset: str,
    window: str,
    profile: str,
    scientific_unit: str,
) -> list[dict[str, object]]:
    summary = json.loads(path.read_text(encoding="utf-8"))
    support = summary["support"]
    rows: list[dict[str, object]] = []
    for arm, values in sorted(summary["arms"].items()):
        replay = ""
        if arm.rsplit("_r", 1)[-1].isdigit():
            replay = int(arm.rsplit("_r", 1)[-1])
        rows.append(
            {
                "dataset": dataset,
                "window": window,
                "profile": profile,
                "evaluator": "g0_common_support",
                "arm": arm,
                "replay": replay,
                "scientific_unit": scientific_unit,
                "technical_repeat": bool(replay),
                "ape_rmse_m": values["ape_rmse_m"],
                "rpe_rmse_m": values["rpe_rmse_m"],
                "coverage": support["common_coverage"],
                "init_success": "",
                "solver_failures": "",
                "rpe_pairs": values["rpe_pairs"],
                "ape_valid": bool(support["ape_valid"]),
                "rpe_valid": bool(support["rpe_valid"]),
                "validity_reason": (
                    f"common_poses={support['matched_count']};"
                    f"span_s={support['common_span_s']};"
                    f"rpe_pairs={support['rpe_pairs']}"
                ),
                "source_artifact": str(path),
            }
        )
    return rows


def a03_replay_rows(root: Path, summary: dict[str, object]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    run_root = Path("/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins")
    for arm in ("learned", "gftt", "klt"):
        for replay in (1, 2, 3):
            key = f"{arm}_r{replay}"
            strict = summary["arms"][key]
            run_dir = run_root / (
                "external_hybrid_xfeat_every2_validation_20260803_"
                f"a03_5000_5900_{arm}_r{replay}"
            )
            legacy = parse_key_values(run_dir / "ape.txt")
            rows.append(
                {
                    "dataset": "AQUALOC",
                    "window": "A03_5000_5900",
                    "profile": "oldcontract_single_xfeat_lineage",
                    "arm": arm,
                    "replay": replay,
                    "scientific_unit": "A03_5000_5900_event",
                    "technical_repeat": True,
                    "g0_ape_rmse_m": strict["ape_rmse_m"],
                    "g0_rpe_rmse_m": strict["rpe_rmse_m"],
                    "g0_matched_poses": strict["matched_count"],
                    "g0_rpe_pairs": strict["rpe_pairs"],
                    "legacy_ape_rmse_m": legacy["se3_ape_rmse_m"],
                    "legacy_rpe_rmse_m": legacy["rpe_trans_rmse_m"],
                    "output_coverage": legacy["output_coverage_ratio"],
                    "first_output_delay_s": legacy["first_output_delay_s"],
                    "init_success": int(legacy["init_success"]),
                    "solver_failures": int(legacy["log_linear_solver_failures"]),
                    "failure_mentions": int(legacy["log_failure_mentions"]),
                    "g0_ape_valid": bool(summary["support"]["ape_valid"]),
                    "g0_rpe_valid": bool(summary["support"]["rpe_valid"]),
                    "source_artifact": str(run_dir),
                }
            )
    return rows


def ntnu_run_dir(label: str, replay: int) -> Path:
    root = Path("/home/ma/AQUA-FE_WS/logs/ntnu_vins")
    stem = "external_hybrid_xfeat_every2_validation_20260804_ntnu_fjord1_s83_d30"
    if label == "nativeq_learned":
        return root / f"{stem}_nativeq_r{replay}"
    if label == "nativeq_klt":
        return root / (
            "external_klt_every2_validation_20260804_ntnu_fjord1_s83_d30_"
            f"nativeq_klt_r{replay}"
        )
    if label in {"nativeq_gftt", "nativeq_drop"}:
        arm = label.split("_", 1)[1]
        return root / f"{stem}_nativeq_{arm}_r{replay}"
    if label == "nativeq_xfeatq1":
        return root / f"{stem}_nativeq_xfeatq1_r{replay}"
    if label == "constq_klt":
        return root / (
            "external_klt_every2_validation_20260804_ntnu_fjord1_s83_d30_"
            f"klt_r{replay}"
        )
    if label.startswith("constq_"):
        arm = label.split("_", 1)[1]
        return root / f"{stem}_{arm}_r{replay}"
    raise ValueError(f"unknown NTNU replay label: {label}")


def ntnu_replay_rows(
    summary_path: Path, summary: dict[str, object]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    support = summary["support"]
    for key, strict in sorted(summary["arms"].items()):
        label, replay_raw = key.rsplit("_r", 1)
        replay = int(replay_raw)
        run_dir = ntnu_run_dir(label, replay)
        legacy = parse_key_values(run_dir / "ape.txt")
        if label == "nativeq_xfeatq1":
            quality_contract = "vins_safe_classical_xfeat_q1"
            arm = "learned_xfeat_q1"
        else:
            quality_contract, arm = label.split("_", 1)
        rows.append(
            {
                "dataset": "NTNU",
                "window": "fjord1_s83_d30",
                "profile": "historical_active_xfeat_microburst",
                "quality_contract": quality_contract,
                "arm": arm,
                "replay": replay,
                "scientific_unit": "NTNU_fjord1_s83_d30_event",
                "technical_repeat": True,
                "g0_ape_rmse_m": strict["ape_rmse_m"],
                "g0_rpe_rmse_m": strict["rpe_rmse_m"],
                "g0_matched_poses": strict["matched_count"],
                "g0_rpe_pairs": strict["rpe_pairs"],
                "legacy_ape_rmse_m": legacy["se3_ape_rmse_m"],
                "legacy_rpe_rmse_m": legacy["rpe_trans_rmse_m"],
                "output_coverage": legacy["output_coverage_ratio"],
                "first_output_delay_s": legacy["first_output_delay_s"],
                "init_success": int(legacy["init_success"]),
                "solver_failures": int(legacy["log_linear_solver_failures"]),
                "failure_mentions": int(legacy["log_failure_mentions"]),
                "g0_ape_valid": bool(support["ape_valid"]),
                "g0_rpe_valid": bool(support["rpe_valid"]),
                "trajectory_sha256": sha256(run_dir / "vins_output" / "vio.csv"),
                "source_artifact": str(run_dir),
                "g0_source_artifact": str(summary_path),
            }
        )
    return rows


def ntnu_prefix_rows(root: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for duration_s in (10, 20, 30):
        path = (
            root
            / f"ntnu_fjord1_s83_d{duration_s}_common_support_nativeq_four_arm"
            / "common_support_summary.json"
        )
        summary = json.loads(path.read_text(encoding="utf-8"))
        support = summary["support"]
        for arm in ("learned", "gftt", "drop", "klt"):
            values = [
                summary["arms"][f"{arm}_r{replay}"]["rpe_rmse_m"]
                for replay in (1, 2, 3)
            ]
            rows.append(
                {
                    "dataset": "NTNU",
                    "window": "fjord1_s83",
                    "prefix_duration_s": duration_s,
                    "quality_contract": "nativeq_vins_safe",
                    "arm": arm,
                    "scientific_unit": "NTNU_fjord1_s83_d30_event",
                    "technical_replays": 3,
                    "rpe_median_m": statistics.median(values),
                    "rpe_min_m": min(values),
                    "rpe_max_m": max(values),
                    "matched_poses": support["matched_count"],
                    "common_span_s": support["common_span_s"],
                    "common_coverage": support["common_coverage"],
                    "rpe_pairs": support["rpe_pairs"],
                    "ape_valid": bool(support["ape_valid"]),
                    "rpe_valid": bool(support["rpe_valid"]),
                    "source_artifact": str(path),
                }
            )
    return rows


def comparison_row(
    name: str,
    evaluator: str,
    learned: list[float],
    control: list[float],
    rpe_valid: bool,
    rpe_pairs: int,
    independent_units: int,
    limitation: str,
) -> dict[str, object]:
    learned_mean = statistics.mean(learned)
    control_mean = statistics.mean(control)
    reductions = [100.0 * (b - a) / b for a, b in zip(learned, control)]
    return {
        "comparison": name,
        "evaluator": evaluator,
        "metric": "1s_translation_rpe_rmse_m",
        "direction": "lower_is_better",
        "technical_replays": len(learned),
        "independent_units": independent_units,
        "learned_mean_m": learned_mean,
        "learned_sample_sd_m": (
            statistics.stdev(learned) if len(learned) > 1 else ""
        ),
        "control_mean_m": control_mean,
        "control_sample_sd_m": (
            statistics.stdev(control) if len(control) > 1 else ""
        ),
        "arm_mean_reduction_percent": 100.0
        * (control_mean - learned_mean)
        / control_mean,
        "paired_reduction_mean_percent": statistics.mean(reductions),
        "paired_reduction_sample_sd_percent": (
            statistics.stdev(reductions) if len(reductions) > 1 else ""
        ),
        "rpe_pairs": rpe_pairs,
        "rpe_valid": rpe_valid,
        "inferential_test": "not_run",
        "limitation": limitation,
    }


def median_comparison_row(
    name: str,
    learned: list[float],
    control: list[float],
    control_label: str,
    limitation: str,
) -> dict[str, object]:
    learned_median = statistics.median(learned)
    control_median = statistics.median(control)
    return {
        "comparison": name,
        "evaluator": "g0_common_support",
        "metric": "1s_translation_rpe_rmse_m",
        "direction": "lower_is_better",
        "technical_replays": len(learned),
        "independent_units": 1,
        "reducer": "median_across_technical_replays",
        "learned_median_m": learned_median,
        "learned_min_m": min(learned),
        "learned_max_m": max(learned),
        "control_label": control_label,
        "control_median_m": control_median,
        "control_min_m": min(control),
        "control_max_m": max(control),
        "learned_reduction_percent": 100.0
        * (control_median - learned_median)
        / control_median,
        "rpe_pairs": 259,
        "rpe_valid": True,
        "inferential_test": "not_run",
        "limitation": limitation,
    }


def summarize_a02(path: Path) -> dict[str, object]:
    metrics_path = path / "frontend_metrics.csv"
    rows = list(csv.DictReader(metrics_path.open(encoding="utf-8")))

    def total(column: str) -> int:
        return sum(int(float(row.get(column) or 0)) for row in rows)

    return {
        "probe": "A02_2800_3200_current_loftr",
        "frames": len(rows),
        "raw_candidates": total("semidense_raw_candidates"),
        "learned_candidates": total("learned_candidate_count"),
        "learned_confirmed": total("learned_confirmed_count"),
        "exported_learned": total("exported_loftr_features"),
        "action_status": "zero_action",
        "interpretation": "adaptive mirror fallback restored classical observations",
        "source_artifact": str(metrics_path),
    }


def build_figure(
    path_png: Path,
    path_pdf: Path,
    a06: dict[str, object],
    a08: dict[str, object],
) -> None:
    colors = {
        "learned": "#0072B2",
        "classical": "#D55E00",
        "klt": "#666666",
        "drop": "#009E73",
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.1), constrained_layout=True)

    a06_order = ["learned", "classical_frame6", "klt", "drop_frame29"]
    a06_labels = ["Learned", "Classical\nframe 6", "KLT", "Drop\nframe 29"]
    a06_colors = [
        colors["learned"],
        colors["classical"],
        colors["klt"],
        colors["drop"],
    ]
    a06_values = [a06["arms"][arm]["rpe_rmse_m"] for arm in a06_order]
    axes[0].bar(a06_labels, a06_values, color=a06_colors, edgecolor="#222222", linewidth=0.6)
    axes[0].set_ylabel("1 s translation RPE RMSE (m)")
    axes[0].set_title("A06 matched initialization event")
    axes[0].text(
        0.02,
        0.98,
        "G0 valid: 21 common-support pairs",
        transform=axes[0].transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
    )
    axes[0].grid(axis="y", alpha=0.22, linewidth=0.7)

    learned = [a08["arms"][f"learned_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    classical = [a08["arms"][f"classical_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    label_offsets = {1: 0.00035, 2: 0.00065, 3: -0.00045}
    for index, (left, right) in enumerate(zip(learned, classical), start=1):
        axes[1].plot(
            [0, 1],
            [left, right],
            color="#777777",
            alpha=0.7,
            linewidth=1.1,
            marker="o",
            markersize=4,
        )
        axes[1].text(
            1.04,
            right + label_offsets[index],
            f"r{index}",
            va="center",
            fontsize=8,
        )
    axes[1].scatter([0] * 3, learned, color=colors["learned"], s=34, zorder=3)
    axes[1].scatter([1] * 3, classical, color=colors["classical"], s=34, zorder=3)
    axes[1].set_xticks([0, 1], ["Learned", "GFTT\nsame ID"])
    axes[1].set_ylabel("1 s translation RPE RMSE (m)")
    axes[1].set_title("A08 technical replay direction")
    axes[1].text(
        0.02,
        0.98,
        "G0 descriptive only: 5 pairs; scientific n=1",
        transform=axes[1].transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
    )
    axes[1].set_xlim(-0.25, 1.25)
    axes[1].grid(axis="y", alpha=0.22, linewidth=0.7)

    for label, axis in zip(("a", "b"), axes):
        axis.text(-0.14, 1.04, label, transform=axis.transAxes, fontweight="bold")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    path_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_png, dpi=300, facecolor="white")
    fig.savefig(path_pdf, facecolor="white")
    plt.close(fig)


def build_a03_figure(
    path_png: Path,
    path_pdf: Path,
    summary: dict[str, object],
    replay_rows: list[dict[str, object]],
) -> None:
    colors = {"learned": "#0072B2", "gftt": "#D55E00", "klt": "#666666"}
    labels = {"learned": "Learned", "gftt": "GFTT same ID", "klt": "KLT / exact drop"}
    linestyles = {"learned": "-", "gftt": "-", "klt": "--"}
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0), constrained_layout=True)
    replay_axis = [1, 2, 3]

    for arm in ("learned", "gftt", "klt"):
        values = [summary["arms"][f"{arm}_r{i}"]["rpe_rmse_m"] for i in replay_axis]
        axes[0].plot(
            replay_axis,
            values,
            color=colors[arm],
            linestyle=linestyles[arm],
            marker="o",
            linewidth=1.7,
            markersize=5,
            label=labels[arm],
        )
    axes[0].set_yscale("log")
    axes[0].set_xticks(replay_axis, ["r1", "r2", "r3"])
    axes[0].set_ylabel("1 s translation RPE RMSE (m, log scale)")
    axes[0].text(
        0.02,
        0.98,
        "G0 valid: 31 pairs; scientific n=1",
        transform=axes[0].transAxes,
        ha="left",
        va="top",
        fontsize=8.5,
    )
    axes[0].grid(axis="y", which="both", alpha=0.22, linewidth=0.7)
    axes[0].legend(frameon=False, fontsize=8.5, loc="center left")

    width = 0.24
    for offset, arm in zip((-width, 0.0, width), ("learned", "gftt", "klt")):
        failures = [
            row["solver_failures"]
            for row in replay_rows
            if row["arm"] == arm
        ]
        axes[1].bar(
            [value + offset for value in replay_axis],
            failures,
            width=width,
            color=colors[arm],
            edgecolor="#222222",
            linewidth=0.5,
            label=labels[arm],
        )
        for position, failure in zip(
            [value + offset for value in replay_axis], failures
        ):
            if failure == 0:
                axes[1].text(
                    position,
                    0.15,
                    "0",
                    ha="center",
                    va="bottom",
                    fontsize=8,
                    color=colors[arm],
                )
    axes[1].set_xticks(replay_axis, ["r1", "r2", "r3"])
    axes[1].set_ylabel("Linear solver failure count")
    axes[1].set_ylim(bottom=0)
    axes[1].grid(axis="y", alpha=0.22, linewidth=0.7)
    axes[1].legend(frameon=False, fontsize=8.5, loc="upper right")

    for label, axis in zip(("a", "b"), axes):
        axis.text(-0.14, 1.04, label, transform=axis.transAxes, fontweight="bold")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    path_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_png, dpi=600, facecolor="white")
    fig.savefig(path_pdf, facecolor="white")
    plt.close(fig)


def build_ntnu_figure(
    path_png: Path,
    path_pdf: Path,
    summary: dict[str, object],
) -> None:
    colors = {
        "learned": "#0072B2",
        "gftt": "#D55E00",
        "drop": "#009E73",
        "klt": "#666666",
        "xfeatq1": "#CC79A7",
        "constq": "#E69F00",
    }
    labels = {
        "learned": "Learned",
        "gftt": "GFTT same ID",
        "drop": "Exact drop",
        "klt": "KLT",
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0), constrained_layout=True)
    replay_axis = [1, 2, 3]

    for arm in ("learned", "gftt", "drop", "klt"):
        values = [
            summary["arms"][f"nativeq_{arm}_r{replay}"]["rpe_rmse_m"]
            for replay in replay_axis
        ]
        axes[0].plot(
            replay_axis,
            values,
            color=colors[arm],
            marker="o",
            linewidth=1.6,
            markersize=5,
            label=labels[arm],
        )
    axes[0].set_yscale("log")
    axes[0].set_xticks(replay_axis, ["r1", "r2", "r3"])
    axes[0].set_ylabel("1 s translation RPE RMSE (m, log scale)")
    axes[0].text(
        0.02,
        0.98,
        "Native q; 259 common pairs; scientific n=1",
        transform=axes[0].transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
    )
    axes[0].grid(axis="y", which="both", alpha=0.22, linewidth=0.7)
    axes[0].legend(frameon=False, fontsize=8.2, loc="center right")

    conditions = [
        ("nativeq_learned", "Native q", colors["learned"]),
        ("nativeq_xfeatq1", "XFeat q=1\nonly", colors["xfeatq1"]),
        ("constq_learned", "Global q=1", colors["constq"]),
    ]
    offsets = [-0.06, 0.0, 0.06]
    for x_pos, (prefix, label, color) in enumerate(conditions):
        values = [
            summary["arms"][f"{prefix}_r{replay}"]["rpe_rmse_m"]
            for replay in replay_axis
        ]
        axes[1].scatter(
            [x_pos + offset for offset in offsets],
            values,
            color=color,
            edgecolor="#222222",
            linewidth=0.4,
            s=32,
            zorder=3,
        )
        median = statistics.median(values)
        axes[1].plot(
            [x_pos - 0.18, x_pos + 0.18],
            [median, median],
            color=color,
            linewidth=2.0,
        )
    axes[1].set_yscale("log")
    axes[1].set_xticks(range(len(conditions)), [item[1] for item in conditions])
    axes[1].set_ylabel("1 s translation RPE RMSE (m, log scale)")
    axes[1].text(
        0.02,
        0.98,
        "Points: technical replays; bars: medians",
        transform=axes[1].transAxes,
        ha="left",
        va="top",
        fontsize=8.2,
    )
    axes[1].grid(axis="y", which="both", alpha=0.22, linewidth=0.7)

    for label, axis in zip(("a", "b"), axes):
        axis.text(-0.14, 1.04, label, transform=axis.transAxes, fontweight="bold")
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    path_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path_png, dpi=600, facecolor="white")
    fig.savefig(path_pdf, facecolor="white")
    plt.close(fig)


def main() -> int:
    args = parse_args()
    root = args.validation_root
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)

    a06_path = root / "a06_2700_common_support_matched" / "common_support_summary.json"
    a08_path = root / "a08_preserve_id_common_support" / "common_support_summary.json"
    a03_path = root / "a03_5000_5900_common_support_all" / "common_support_summary.json"
    ntnu_path = (
        args.ntnu_validation_root
        / "ntnu_fjord1_s83_d30_common_support_nativeq_constq_xfeatq1_all"
        / "common_support_summary.json"
    )
    a06 = json.loads(a06_path.read_text(encoding="utf-8"))
    a08 = json.loads(a08_path.read_text(encoding="utf-8"))
    a03 = json.loads(a03_path.read_text(encoding="utf-8"))
    ntnu = json.loads(ntnu_path.read_text(encoding="utf-8"))

    legacy_rows = a08_legacy_rows(root)
    common_rows = common_support_rows(
        a06_path,
        "AQUALOC",
        "A06_2210_2700",
        "frozen_loftr_initialization",
        "A06_2210_2700_event",
    ) + common_support_rows(
        a08_path,
        "AQUALOC",
        "A08_4500_4660",
        "oldcontract_microburst",
        "A08_4500_4660_event",
    ) + common_support_rows(
        a03_path,
        "AQUALOC",
        "A03_5000_5900",
        "oldcontract_single_xfeat_lineage",
        "A03_5000_5900_event",
    ) + common_support_rows(
        ntnu_path,
        "NTNU",
        "fjord1_s83_d30",
        "historical_active_xfeat_microburst",
        "NTNU_fjord1_s83_d30_event",
    )
    write_csv(output / "replay-metrics.csv", legacy_rows + common_rows)
    a03_rows = a03_replay_rows(root, a03)
    write_csv(output / "a03-replay-summary.csv", a03_rows)
    ntnu_rows = ntnu_replay_rows(ntnu_path, ntnu)
    write_csv(output / "ntnu-replay-summary.csv", ntnu_rows)
    write_csv(
        output / "ntnu-prefix-summary.csv",
        ntnu_prefix_rows(args.ntnu_validation_root),
    )

    a06_learned = [a06["arms"]["learned"]["rpe_rmse_m"]]
    a06_control = [a06["arms"]["classical_frame6"]["rpe_rmse_m"]]
    a08_legacy_learned = [
        row["rpe_rmse_m"]
        for row in legacy_rows
        if row["arm"] == "learned"
    ]
    a08_legacy_control = [
        row["rpe_rmse_m"]
        for row in legacy_rows
        if row["arm"] == "classical_preserve_id"
    ]
    a08_g0_learned = [a08["arms"][f"learned_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    a08_g0_control = [a08["arms"][f"classical_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    comparisons = [
        comparison_row(
            "A06 learned vs same-frame classical replacement",
            "g0_common_support",
            a06_learned,
            a06_control,
            True,
            21,
            1,
            "development window; APE invalid; one event",
        ),
        comparison_row(
            "A08 learned vs same-ID GFTT replacement",
            "legacy_nearest_reference",
            a08_legacy_learned,
            a08_legacy_control,
            False,
            57,
            1,
            "three technical replays; only 7 unique GT assignments",
        ),
        comparison_row(
            "A08 learned vs same-ID GFTT replacement",
            "g0_common_support",
            a08_g0_learned,
            a08_g0_control,
            False,
            5,
            1,
            "three technical replays; 6 common poses over 5 seconds",
        ),
    ]
    a03_learned = [a03["arms"][f"learned_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    a03_gftt = [a03["arms"][f"gftt_r{i}"]["rpe_rmse_m"] for i in (1, 2, 3)]
    a03_learned_median = statistics.median(a03_learned)
    a03_gftt_median = statistics.median(a03_gftt)
    comparisons.append(
        {
            "comparison": "A03 learned vs same-ID GFTT replacement",
            "evaluator": "g0_common_support",
            "metric": "1s_translation_rpe_rmse_m",
            "direction": "lower_is_better",
            "technical_replays": 3,
            "independent_units": 1,
            "reducer": "median_across_technical_replays",
            "learned_median_m": a03_learned_median,
            "learned_sample_sd_m": statistics.stdev(a03_learned),
            "control_median_m": a03_gftt_median,
            "control_sample_sd_m": statistics.stdev(a03_gftt),
            "lower_arm": "gftt",
            "lower_arm_reduction_percent": 100.0
            * (a03_learned_median - a03_gftt_median)
            / a03_learned_median,
            "rpe_pairs": 31,
            "rpe_valid": True,
            "inferential_test": "not_run",
            "limitation": (
                "one development window; technical repeats are not independent; "
                "retrospective survival/proximity-matched control"
            ),
        }
    )
    ntnu_values = {
        prefix: [
            ntnu["arms"][f"{prefix}_r{replay}"]["rpe_rmse_m"]
            for replay in (1, 2, 3)
        ]
        for prefix in (
            "nativeq_learned",
            "nativeq_gftt",
            "nativeq_drop",
            "nativeq_klt",
            "nativeq_xfeatq1",
            "constq_learned",
        )
    }
    for comparator, label, control_label, limitation in (
        (
            "nativeq_klt",
            "NTNU native-q learned vs independent KLT",
            "klt",
            "one development event; KLT is an independent exporter baseline",
        ),
        (
            "nativeq_gftt",
            "NTNU native-q learned vs same-ID GFTT replacement",
            "gftt",
            "one development event; GFTT is retrospective and backend-outcome-blind",
        ),
        (
            "nativeq_drop",
            "NTNU native-q learned vs exact drop",
            "drop",
            "one development event; drop has two optimizer branches across technical repeats",
        ),
        (
            "nativeq_xfeatq1",
            "NTNU native-q learned vs XFeat-only q=1",
            "learned_xfeat_q1",
            "source-specific backend sensitivity ablation; not an independent method",
        ),
        (
            "constq_learned",
            "NTNU native-q learned vs global q=1 learned",
            "global_q1_learned",
            "global q=1 rewrites all observations and is an interaction ablation",
        ),
    ):
        comparisons.append(
            median_comparison_row(
                label,
                ntnu_values["nativeq_learned"],
                ntnu_values[comparator],
                control_label,
                limitation,
            )
        )
    write_csv(output / "comparison-summary.csv", comparisons)

    ntnu_dir = root / "ntnu_cqg"
    classical_bag = ntnu_dir / "fjord1_s83_d10_classical_same_pipeline.bag"
    xfeat_bag = ntnu_dir / "fjord1_s83_d10_xfeat_same_pipeline.bag"
    probe_rows = [
        summarize_a02(args.a02_run),
        {
            "probe": "NTNU_fjord1_s83_d10_current_default_same_pipeline",
            "frames": 100,
            "raw_candidates": "",
            "learned_candidates": "",
            "learned_confirmed": "",
            "exported_learned": 0,
            "action_status": "zero_action_both_arms",
            "interpretation": "current default classical and XFeat outputs are byte-identical base-only bags",
            "classical_bag_sha256": sha256(classical_bag),
            "xfeat_bag_sha256": sha256(xfeat_bag),
            "source_artifact": str(ntnu_dir / "classical_vs_xfeat.md"),
        },
    ]
    write_csv(output / "probe-summary.csv", probe_rows)

    build_figure(
        output / "figures" / "figure-01-matched-control-rpe.png",
        output / "figures" / "figure-01-matched-control-rpe.pdf",
        a06,
        a08,
    )
    build_a03_figure(
        output / "figures" / "figure-02-a03-classical-control.png",
        output / "figures" / "figure-02-a03-classical-control.pdf",
        a03,
        a03_rows,
    )
    build_ntnu_figure(
        output / "figures" / "figure-03-ntnu-quality-interaction.png",
        output / "figures" / "figure-03-ntnu-quality-interaction.pdf",
        ntnu,
    )
    print(f"wrote analysis artifacts to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
