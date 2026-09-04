#!/usr/bin/env python3
"""Build the strict MIMIR-UW learned-stereo seed ablation bundle.

The comparison unit is one frozen SeaFloor/track1 45--90 s window. Repeated
fixed-iteration replays check computational determinism; they are not
independent experimental units and are never used for inferential statistics.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rosbag

from analyze_mimir_vins_drift_growth import analyze_run
from evaluate_vins_sim_ape import load_vins


ROOT = Path("/mnt/data/AQUA-FE_WS/logs/mimir_uw_vins")

TRACK1_ARMS = {
    "external_klt": {
        "label": "Pure external KLT",
        "runs": ["mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_klt_r1"],
        "learned_left": 0,
        "learned_right": 0,
    },
    "internal_vins": {
        "label": "Original VINS stereo KLT",
        "runs": ["mimir_vins_stereoonly_deterministic_v1_seafloor_track1_s45_d45_r1"],
        "learned_left": 0,
        "learned_right": 0,
    },
    "qi_no_learned": {
        "label": "q_i + classical stereo; no learned",
        "runs": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_nolearned_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_nolearned_r2",
        ],
        "learned_left": 0,
        "learned_right": 0,
    },
    "proposed_safe": {
        "label": "Proposed safe: q_i + left learned seeds",
        "runs": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r2",
        ],
        "learned_left": 121,
        "learned_right": 0,
    },
    "unsafe_local_lk": {
        "label": "Unsafe: learned right via local LK",
        "runs": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_r2",
        ],
        "learned_left": 121,
        "learned_right": 103,
    },
    "global_ncc_1px": {
        "label": "Diagnostic: learned right; global NCC <=1 px",
        "runs": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_globalncc_r1"
        ],
        "learned_left": 121,
        "learned_right": 75,
    },
    "global_ncc_05px": {
        "label": "Diagnostic: learned right; global NCC <=0.5 px",
        "runs": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_globalncc_p5_r1"
        ],
        "learned_left": 121,
        "learned_right": 43,
    },
}

WALLCLOCK_RUNS = {
    ("q_i + learned", "0.04 s wall-clock cap"): [
        "mimir_extstereo_v2_seafloor_track0_s0_d45_ours",
        "mimir_extstereo_v2_seafloor_track0_s0_d45_ours_r2",
    ],
    ("q_i + learned", "fixed 8 iterations"): [
        "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_r1",
        "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_r2",
    ],
    ("q_i; no learned", "0.04 s wall-clock cap"): [
        "mimir_extstereo_v2_seafloor_track0_s0_d45_ours_nolearned",
        "mimir_extstereo_v2_seafloor_track0_s0_d45_ours_nolearned_r2",
    ],
    ("q_i; no learned", "fixed 8 iterations"): [
        "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_nolearned_r1",
        "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_nolearned_r2",
    ],
}

DRIFT_RUNS = {
    "No learned": (
        "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_nolearned_r1",
        "mimir_stereo_features_v3_seafloor_track1_ours_nolearned/features_stereo.bag",
    ),
    "Proposed safe": (
        "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r1",
        "mimir_stereo_features_v3_seafloor_track1_ours_leftonly/features_stereo.bag",
    ),
    "Unsafe learned-right": (
        "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_r1",
        "mimir_stereo_features_v3_seafloor_track1_ours/features_stereo.bag",
    ),
}

CROSS_WINDOW_SAFE = {
    "SeaFloor/track0 0--45 s": {
        "learned_left_observations": 144,
        "no_learned": [
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_nolearned_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_nolearned_r2",
        ],
        "proposed_safe": [
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_safe_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_safe_r2",
        ],
    },
    "SeaFloor/track1 45--90 s": {
        "learned_left_observations": 121,
        "no_learned": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_nolearned_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_nolearned_r2",
        ],
        "proposed_safe": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r2",
        ],
    },
}

THREE_WINDOW_BACKENDS = {
    "SeaFloor/track0 0--45 s": {
        "pure_external_klt": [
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_klt_r1"
        ],
        "original_vins_stereo": [
            "mimir_vins_stereoonly_deterministic_v1_seafloor_track0_s0_d45_r1"
        ],
        "ours_safe": [
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_safe_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track0_s0_d45_ours_safe_r2",
        ],
        "learned_left_observations": 144,
    },
    "SeaFloor/track1 45--90 s": {
        "pure_external_klt": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_klt_r1"
        ],
        "original_vins_stereo": [
            "mimir_vins_stereoonly_deterministic_v1_seafloor_track1_s45_d45_r1"
        ],
        "ours_safe": [
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r1",
            "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r2",
        ],
        "learned_left_observations": 121,
    },
    "SeaFloor/track2 0--45 s": {
        "pure_external_klt": [
            "mimir_extstereo_deterministic_v1_seafloor_track2_s0_d45_klt_r1"
        ],
        "original_vins_stereo": [
            "mimir_vins_stereoonly_deterministic_v1_seafloor_track2_s0_d45_r1"
        ],
        "ours_safe": [
            "mimir_extstereo_deterministic_v1_seafloor_track2_s0_d45_ours_safe_r1"
        ],
        "learned_left_observations": 0,
    },
}

BACKEND_LABELS = {
    "pure_external_klt": "Pure external KLT",
    "original_vins_stereo": "Original VINS stereo KLT",
    "ours_safe": "AQUA-FE safe",
}

COLORS = {
    "external_klt": "#56B4E9",
    "internal_vins": "#E69F00",
    "qi_no_learned": "#0072B2",
    "proposed_safe": "#009E73",
    "unsafe_local_lk": "#D55E00",
    "global_ncc_1px": "#CC79A7",
    "global_ncc_05px": "#000000",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "/mnt/data/AQUA-FE_WS/logs/mimir_alt_methods/analysis_bundle/"
            "learned_stereo_seed_analysis"
        ),
    )
    return parser.parse_args()


def read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def load_run(run_name: str) -> dict[str, float | str]:
    run_dir = ROOT / run_name
    metrics = read_key_values(run_dir / "ape.txt")
    return {
        "run": run_name,
        "run_dir": str(run_dir),
        "ape_rmse_m": float(metrics["se3_ape_rmse_m"]),
        "ape_median_m": float(metrics["se3_ape_median_m"]),
        "ape_max_m": float(metrics["se3_ape_max_m"]),
        "rpe_1s_rmse_m": float(metrics["rpe_trans_rmse_m"]),
        "rpe_1s_median_m": float(metrics["rpe_trans_median_m"]),
        "rpe_1s_max_m": float(metrics["rpe_trans_max_m"]),
        "output_coverage_ratio": float(metrics["output_coverage_ratio"]),
        "output_poses": int(float(metrics["output_poses"])),
    }


def load_track1_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for arm, spec in TRACK1_ARMS.items():
        for repeat, run_name in enumerate(spec["runs"], start=1):
            row = load_run(str(run_name))
            row.update(
                {
                    "arm": arm,
                    "label": spec["label"],
                    "repeat": repeat,
                    "learned_left_observations": spec["learned_left"],
                    "learned_right_observations": spec["learned_right"],
                }
            )
            rows.append(row)
    return pd.DataFrame(rows)


def summarize_track1(rows: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for arm, group in rows.groupby("arm", sort=False):
        record: dict[str, object] = {
            "arm": arm,
            "label": group.iloc[0].label,
            "deterministic_replays": len(group),
            "independent_windows": 1,
            "learned_left_observations": int(group.iloc[0].learned_left_observations),
            "learned_right_observations": int(group.iloc[0].learned_right_observations),
        }
        for metric in (
            "ape_rmse_m",
            "rpe_1s_rmse_m",
            "output_coverage_ratio",
        ):
            values = group[metric].astype(float)
            record[metric] = float(values.mean())
            record[f"{metric}_min"] = float(values.min())
            record[f"{metric}_max"] = float(values.max())
        records.append(record)
    result = pd.DataFrame(records)
    no_learned = float(result.loc[result.arm == "qi_no_learned", "ape_rmse_m"].iloc[0])
    no_learned_rpe = float(
        result.loc[result.arm == "qi_no_learned", "rpe_1s_rmse_m"].iloc[0]
    )
    result["ape_change_vs_qi_no_learned_pct"] = (
        (result.ape_rmse_m - no_learned) / no_learned * 100.0
    )
    result["rpe_change_vs_qi_no_learned_pct"] = (
        (result.rpe_1s_rmse_m - no_learned_rpe) / no_learned_rpe * 100.0
    )
    return result


def load_wallclock_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (arm, protocol), run_names in WALLCLOCK_RUNS.items():
        for repeat, run_name in enumerate(run_names, start=1):
            row = load_run(run_name)
            row.update({"arm": arm, "protocol": protocol, "repeat": repeat})
            rows.append(row)
    return pd.DataFrame(rows)


def load_cross_window_safe() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for window, spec in CROSS_WINDOW_SAFE.items():
        arm_values: dict[str, dict[str, float]] = {}
        for arm in ("no_learned", "proposed_safe"):
            runs = [load_run(name) for name in spec[arm]]
            arm_values[arm] = {
                "ape_rmse_m": float(np.mean([float(row["ape_rmse_m"]) for row in runs])),
                "rpe_1s_rmse_m": float(
                    np.mean([float(row["rpe_1s_rmse_m"]) for row in runs])
                ),
                "ape_range_m": float(
                    max(float(row["ape_rmse_m"]) for row in runs)
                    - min(float(row["ape_rmse_m"]) for row in runs)
                ),
                "rpe_range_m": float(
                    max(float(row["rpe_1s_rmse_m"]) for row in runs)
                    - min(float(row["rpe_1s_rmse_m"]) for row in runs)
                ),
            }
        baseline = arm_values["no_learned"]
        safe = arm_values["proposed_safe"]
        rows.append(
            {
                "window": window,
                "learned_left_observations": spec["learned_left_observations"],
                "no_learned_ape_rmse_m": baseline["ape_rmse_m"],
                "proposed_safe_ape_rmse_m": safe["ape_rmse_m"],
                "ape_change_pct": pct(safe["ape_rmse_m"], baseline["ape_rmse_m"]),
                "no_learned_rpe_1s_rmse_m": baseline["rpe_1s_rmse_m"],
                "proposed_safe_rpe_1s_rmse_m": safe["rpe_1s_rmse_m"],
                "rpe_change_pct": pct(
                    safe["rpe_1s_rmse_m"], baseline["rpe_1s_rmse_m"]
                ),
                "no_learned_ape_repeat_range_m": baseline["ape_range_m"],
                "proposed_safe_ape_repeat_range_m": safe["ape_range_m"],
                "no_learned_rpe_repeat_range_m": baseline["rpe_range_m"],
                "proposed_safe_rpe_repeat_range_m": safe["rpe_range_m"],
            }
        )
    return pd.DataFrame(rows)


def load_three_window_backends() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for window, spec in THREE_WINDOW_BACKENDS.items():
        for method in BACKEND_LABELS:
            runs = [load_run(name) for name in spec[method]]
            rows.append(
                {
                    "window": window,
                    "method": method,
                    "label": BACKEND_LABELS[method],
                    "deterministic_replays": len(runs),
                    "learned_left_observations": (
                        spec["learned_left_observations"] if method == "ours_safe" else 0
                    ),
                    "ape_rmse_m": float(
                        np.mean([float(row["ape_rmse_m"]) for row in runs])
                    ),
                    "rpe_1s_rmse_m": float(
                        np.mean([float(row["rpe_1s_rmse_m"]) for row in runs])
                    ),
                    "output_coverage_ratio": float(
                        np.mean([float(row["output_coverage_ratio"]) for row in runs])
                    ),
                }
            )
    result = pd.DataFrame(rows)
    for window in result.window.unique():
        mask = result.window == window
        klt_ape = float(
            result.loc[mask & (result.method == "pure_external_klt"), "ape_rmse_m"].iloc[0]
        )
        klt_rpe = float(
            result.loc[mask & (result.method == "pure_external_klt"), "rpe_1s_rmse_m"].iloc[0]
        )
        result.loc[mask, "ape_change_vs_external_klt_pct"] = (
            (result.loc[mask, "ape_rmse_m"] - klt_ape) / klt_ape * 100.0
        )
        result.loc[mask, "rpe_change_vs_external_klt_pct"] = (
            (result.loc[mask, "rpe_1s_rmse_m"] - klt_rpe) / klt_rpe * 100.0
        )
    return result


def build_drift_rows() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for label, (run_name, bag_rel) in DRIFT_RUNS.items():
        rows.extend(
            analyze_run(
                label,
                ROOT / run_name / "vins_output/vio.csv",
                ROOT / bag_rel,
                "/mimir/ground_truth",
                5.0,
                1.0,
            )
        )
    return pd.DataFrame(rows)


def learned_span_relative_to_output() -> tuple[float, float]:
    bag_path = ROOT / "mimir_stereo_features_v3_seafloor_track1_ours/features_stereo.bag"
    learned_stamps: list[float] = []
    with rosbag.Bag(str(bag_path)) as bag:
        for _, message, _ in bag.read_messages(topics=["/feature_tracker/feature"]):
            channels = {channel.name: channel.values for channel in message.channels}
            if any(value > 0.5 for value in channels.get("is_learned", [])):
                learned_stamps.append(message.header.stamp.to_sec())
    trajectory = load_vins(
        ROOT
        / "mimir_extstereo_deterministic_v1_seafloor_track1_s45_d45_ours_leftonly_r1"
        / "vins_output/vio.csv"
    )
    t0 = trajectory[0][0]
    return min(learned_stamps) - t0, max(learned_stamps) - t0


def plot_track1(summary: pd.DataFrame, figures: Path) -> None:
    order = list(TRACK1_ARMS)
    labels = [
        "External\nKLT",
        "Original\nVINS stereo",
        "$q_i$; no\nlearned",
        "Proposed\nsafe",
        "Unsafe\nlocal LK",
        "NCC gate\n1.0 px",
        "NCC gate\n0.5 px",
    ]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.3))
    for ax, metric, ylabel in (
        (axes[0], "ape_rmse_m", "SE(3) APE RMSE (m)"),
        (axes[1], "rpe_1s_rmse_m", "1 s translational RPE RMSE (m)"),
    ):
        values = [float(summary.loc[summary.arm == arm, metric].iloc[0]) for arm in order]
        bars = ax.bar(
            np.arange(len(order)),
            values,
            color=[COLORS[arm] for arm in order],
            edgecolor="black",
            linewidth=0.55,
        )
        ax.set_ylabel(ylabel)
        ax.set_xticks(np.arange(len(order)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.25)
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + max(values) * 0.025,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=7,
                rotation=90,
            )
        ax.set_ylim(0, max(values) * 1.24)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-01-track1-learned-stereo-ablation.{suffix}", dpi=600)
    plt.close(fig)


def plot_three_window_backends(rows: pd.DataFrame, figures: Path) -> None:
    windows = list(THREE_WINDOW_BACKENDS)
    methods = list(BACKEND_LABELS)
    short_windows = ["track0\n0--45 s", "track1\n45--90 s", "track2\n0--45 s"]
    colors = {
        "pure_external_klt": "#56B4E9",
        "original_vins_stereo": "#E69F00",
        "ours_safe": "#009E73",
    }
    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.0))
    x = np.arange(len(windows))
    width = 0.24
    for ax, metric, ylabel in (
        (axes[0], "ape_rmse_m", "SE(3) APE RMSE (m)"),
        (axes[1], "rpe_1s_rmse_m", "1 s translational RPE RMSE (m)"),
    ):
        for index, method in enumerate(methods):
            values = [
                float(
                    rows[(rows.window == window) & (rows.method == method)][metric].iloc[0]
                )
                for window in windows
            ]
            ax.bar(
                x + (index - 1) * width,
                values,
                width,
                color=colors[method],
                edgecolor="black",
                linewidth=0.5,
                label=BACKEND_LABELS[method],
            )
        ax.set_xticks(x)
        ax.set_xticklabels(short_windows)
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-04-three-window-backend-comparison.{suffix}", dpi=600)
    plt.close(fig)


def plot_drift(drift: pd.DataFrame, learned_span: tuple[float, float], figures: Path) -> None:
    colors = {
        "No learned": "#0072B2",
        "Proposed safe": "#009E73",
        "Unsafe learned-right": "#D55E00",
    }
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.0), sharex=True)
    for label, group in drift.groupby("run", sort=False):
        x = (group.start_s_rel.astype(float) + group.end_s_rel.astype(float)) / 2.0
        axes[0].plot(
            x,
            group.global_alignment_bin_ape_rmse_m,
            marker="o",
            linewidth=1.7,
            color=colors[label],
            label=label,
        )
        axes[1].plot(
            x,
            group.rpe_1s_rmse_m,
            marker="o",
            linewidth=1.7,
            color=colors[label],
            label=label,
        )
    for ax, ylabel in zip(
        axes,
        ("Global-alignment bin APE RMSE (m)", "1 s translational RPE RMSE (m)"),
    ):
        ax.axvspan(*learned_span, color="#F0E442", alpha=0.28, label="learned burst")
        ax.set_xlabel("Time from first VINS output (s)")
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        ax.grid(alpha=0.25)
    axes[0].legend(frameon=False, fontsize=8)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-02-drift-after-learned-burst.{suffix}", dpi=600)
    plt.close(fig)


def plot_solver_variability(rows: pd.DataFrame, figures: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(8.8, 4.0), sharey=True)
    protocol_order = ["0.04 s wall-clock cap", "fixed 8 iterations"]
    colors = {"q_i + learned": "#009E73", "q_i; no learned": "#0072B2"}
    for ax, arm in zip(axes, colors):
        subset = rows[rows.arm == arm]
        for repeat in sorted(subset.repeat.unique()):
            values = [
                float(
                    subset[
                        (subset.protocol == protocol) & (subset.repeat == repeat)
                    ].ape_rmse_m.iloc[0]
                )
                for protocol in protocol_order
            ]
            ax.plot(
                [0, 1],
                values,
                color=colors[arm],
                alpha=0.65,
                linewidth=1.3,
                marker="o",
            )
        ax.set_title(arm.replace("q_i", "$q_i$"))
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["0.04 s\nwall-clock", "fixed 8\niterations"])
        ax.set_ylabel("SE(3) APE RMSE (m)")
        ax.grid(axis="y", alpha=0.25)
    axes[0].set_ylim(0, float(rows.ape_rmse_m.max()) * 1.10)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-03-solver-stop-variability.{suffix}", dpi=600)
    plt.close(fig)


def pct(new: float, baseline: float) -> float:
    return (new - baseline) / baseline * 100.0


def write_reports(
    output: Path,
    summary: pd.DataFrame,
    wallclock: pd.DataFrame,
    cross_window: pd.DataFrame,
    three_window: pd.DataFrame,
    learned_span: tuple[float, float],
) -> None:
    by_arm = summary.set_index("arm")
    safe = by_arm.loc["proposed_safe"]
    nolearn = by_arm.loc["qi_no_learned"]
    klt = by_arm.loc["external_klt"]
    internal = by_arm.loc["internal_vins"]
    unsafe = by_arm.loc["unsafe_local_lk"]
    ncc1 = by_arm.loc["global_ncc_1px"]
    track0_cross = cross_window[cross_window.window.str.contains("track0")].iloc[0]

    backend_table = [
        "| Window | Method | learned-left obs | APE RMSE (m) | RPE RMSE (m) | Coverage |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for _, row in three_window.iterrows():
        backend_table.append(
            f"| {row.window} | {row.label} | {int(row.learned_left_observations)} | "
            f"{row.ape_rmse_m:.6f} | {row.rpe_1s_rmse_m:.6f} | "
            f"{row.output_coverage_ratio:.4f} |"
        )
    ours_three = three_window[three_window.method == "ours_safe"]

    table_lines = [
        "| Arm | learned L/R obs | APE RMSE (m) | RPE RMSE (m) | Coverage |",
        "|---|---:|---:|---:|---:|",
    ]
    for _, row in summary.iterrows():
        table_lines.append(
            f"| {row.label} | {int(row.learned_left_observations)}/"
            f"{int(row.learned_right_observations)} | {row.ape_rmse_m:.6f} | "
            f"{row.rpe_1s_rmse_m:.6f} | {row.output_coverage_ratio:.4f} |"
        )
    report = f"""# MIMIR-UW learned stereo-seed analysis

## Analysis question

On the frozen `SeaFloor/track1`, 45--90 s window, does AQUA-FE's learned-point
geometry help a stereo VINS backend, and is it safe to turn each learned cam0
track into a same-frame cam1 depth constraint using local LK?

## Exact comparison

{chr(10).join(table_lines)}

All primary numbers use fixed-scale SE(3), exact timestamp association, stereo
without IMU, a fixed RANSAC seed, single-thread numerical libraries, eight
Ceres iterations, and a generous solver-time ceiling. Coverage is approximately
0.985--0.989 for every arm.

## Three-window backend comparison

{chr(10).join(backend_table)}

Track2 contains zero learned observations. Its AQUA-FE-safe row therefore
isolates the `q_i`/classical-feature weighting path and is not evidence for a
learned-point contribution.

## Findings

1. The proposed safe policy (`q_i` + 121 left-camera learned observations,
   classical stereo only) reaches `{safe.ape_rmse_m:.6f}/{safe.rpe_1s_rmse_m:.6f}` m
   APE/RPE. Relative to the identical-quality no-learned ablation, APE changes
   by `{pct(safe.ape_rmse_m, nolearn.ape_rmse_m):.2f}%` and RPE by
   `{pct(safe.rpe_1s_rmse_m, nolearn.rpe_1s_rmse_m):.2f}%`. Thus the learned
   temporal geometry is an APE positive but not an across-metric win.
2. Relative to pure external KLT, the safe policy changes APE/RPE by
   `{pct(safe.ape_rmse_m, klt.ape_rmse_m):.2f}%/`
   `{pct(safe.rpe_1s_rmse_m, klt.rpe_1s_rmse_m):.2f}%`. Most of that gap is
   already present in the `q_i` no-learned arm; it must not be attributed only
   to 121 learned observations.
3. Relative to original VINS stereo KLT, the safe policy changes APE/RPE by
   `{pct(safe.ape_rmse_m, internal.ape_rmse_m):.2f}%/`
   `{pct(safe.rpe_1s_rmse_m, internal.rpe_1s_rmse_m):.2f}%` on this one window.
4. Adding 103 local-LK learned cam1 observations changes APE/RPE by
   `{pct(unsafe.ape_rmse_m, safe.ape_rmse_m):.2f}%/`
   `{pct(unsafe.rpe_1s_rmse_m, safe.rpe_1s_rmse_m):.2f}%` versus the safe arm.
   A full-epipolar NCC agreement gate rejects 28 observations and reduces the
   damage to `{ncc1.ape_rmse_m:.6f}/{ncc1.rpe_1s_rmse_m:.6f}` m, but still does
   not establish no-harm.
5. Learned tracks appear from `{learned_span[0]:.2f}` to `{learned_span[1]:.2f}` s
   after the first VINS output. The unsafe trajectory's RPE increases in the
   same 30--35 s bin; the no-learned and safe arms do not show that jump.
6. The old 0.04 s wall-clock solver cap is not a valid deterministic comparison
   protocol under concurrent load. On track0, identical replays swap apparent
   winners across two runs, while fixed-iteration duplicates are identical.
7. The same safe policy is numerically neutral on track0: APE/RPE change by
   `{track0_cross.ape_change_pct:.3f}%/{track0_cross.rpe_change_pct:.3f}%`
   relative to its identical-quality no-learned input. Track2 exports no learned
   observations, so it is a zero-injection control rather than a learned test.
8. Against pure external KLT, AQUA-FE-safe changes APE by
   `{', '.join(f'{value:.1f}%' for value in ours_three.ape_change_vs_external_klt_pct)}`
   and RPE by
   `{', '.join(f'{value:.1f}%' for value in ours_three.rpe_change_vs_external_klt_pct)}`
   on track0/track1/track2 respectively. Against original VINS stereo KLT it is
   better on track1/track2 but worse on track0, so the receipts do not support
   a universal backend winner claim.

## Decision

- Keep learned points as seeds for the cam0 temporal KLT carrier.
- Keep `q_i` backend weighting.
- Do not create learned cam1/depth observations with local LK by default.
- Keep cam1 stereo support for classical tracks; re-enable learned cam1 only
  after a sequence-independent depth/epipolar validator passes no-harm tests.
- Use `scripts/run_mimir_uw_vins_deterministic_profile.sh` for formal replay
  comparisons; reserve the 0.04 s cap for real-time latency tests.

## Claim Candidates

- Claim:
  - Source evidence: `comparison.csv`, `run_metrics.csv`, Figure 1.
  - Allowed wording: On the frozen SeaFloor/track1 window, left-camera learned
    temporal seeds reduce APE by 10.6% relative to an identical-quality
    no-learned ablation, while RPE increases by 8.4%.
  - Forbidden stronger wording: Learned points generally improve stereo VINS
    or significantly outperform all baselines on MIMIR-UW.
  - Uncertainty: one purposively selected window and one frozen feature bag.
  - Next check: predeclare and run the safe policy in additional environments;
    track0 is already a numerically neutral no-harm check.
  - Decision: keep, bounded to this window.

- Claim:
  - Source evidence: `drift_growth.csv`, Figures 1--2.
  - Allowed wording: Naive local-LK learned cam1 constraints cause a repeatable
    error jump after the learned burst in this window.
  - Forbidden stronger wording: All learned stereo matching is harmful.
  - Uncertainty: global-NCC filters were diagnostic threshold sweeps on the same
    window.
  - Next check: validate an independent learned depth matcher on held-out data.
  - Decision: keep as a negative/no-harm finding.

- Claim:
  - Source evidence: `three_window_backend.csv`, Figure 4.
  - Allowed wording: Under the fixed-iteration stereo-only protocol, AQUA-FE-safe
    has lower APE and RPE than pure external KLT on all three selected SeaFloor
    windows, and lower errors than original VINS stereo KLT on track1/track2.
  - Forbidden stronger wording: Learned points outperform both baselines on all
    windows; track2 contains no learned observations and track0 remains worse
    than original VINS stereo KLT.
  - Uncertainty: three purposively selected windows and frozen feature bags.
  - Next check: expand to independently predeclared stereo windows when disk
    capacity permits.
  - Decision: keep as a bounded backend comparison.
"""
    (output / "analysis-report.md").write_text(report, encoding="utf-8")

    variability = (
        wallclock.groupby(["arm", "protocol"])["ape_rmse_m"]
        .agg(["min", "max"])
        .reset_index()
    )
    variability_lines = [
        f"- {row.arm}, {row.protocol}: APE range {row['min']:.6f}--{row['max']:.6f} m"
        for _, row in variability.iterrows()
    ]
    stats = f"""# Statistical appendix

## Units and validity

- The learned-geometry/right-depth ablation has **1 independent window**
  (`SeaFloor/track1`, 45--90 s).
- The safe/no-learned no-harm table covers **2 selected windows** (track0 and
  track1); track2 contains no learned observations.
- The three-backend descriptive table covers **3 selected SeaFloor windows**.
- Deterministic replay count: 2 for the no-learned, proposed-safe, and unsafe
  arms; 1 for the remaining diagnostic/baseline arms.
- The duplicated replays are exact computational reproducibility checks on the
  same frozen messages, not independent seeds, windows, or subjects.
- Therefore no confidence interval, p-value, normality test, or inferential
  effect size is valid. All percentage changes are descriptive relative changes.
- Multiple-threshold global-NCC results are diagnostic and not confirmatory.

## Solver-stop sensitivity on track0

{chr(10).join(variability_lines)}

The wall-clock-capped repeats are unstable and are quarantined from the primary
method comparison. The fixed-iteration duplicates have zero numeric range to
the six decimals reported by the evaluator.

## Metric definitions

- APE: RMSE of positions after one full-trajectory rigid SE(3) alignment; lower
  is better and metric scale is preserved.
- RPE: translational RMSE at approximately 1 s after the same SE(3) alignment;
  lower is better.
- Coverage: output trajectory duration divided by ground-truth duration.
"""
    (output / "stats-appendix.md").write_text(stats, encoding="utf-8")

    catalog = """# Figure catalog

## Figure 1: `figure-01-track1-learned-stereo-ablation`

- Purpose: separate pure KLT, q_i, left learned temporal seeds, and learned
  cam1/depth constraints.
- Data source: `comparison.csv`.
- Caption requirements: fixed SeaFloor/track1 45--90 s window; fixed-iteration
  protocol; exact APE/RPE values; no error bars because repeats are not
  independent samples.
- Observation: proposed-safe has the lowest APE; no-learned has the lowest RPE;
  local-LK learned-right is much worse.
- Implication: use a left-only learned seed policy for no-harm.

## Figure 2: `figure-02-drift-after-learned-burst`

- Purpose: test whether the learned-right failure begins near the learned burst.
- Data source: `drift_growth.csv`; yellow span is the actual learned-observation
  interval.
- Caption requirements: 5 s bins, one global SE(3) alignment, 1 s RPE.
- Observation: unsafe learned-right RPE rises in the burst bin and remains high.
- Implication: the error is tied to learned depth constraints, not timestamps or
  pre-existing early drift.

## Figure 3: `figure-03-solver-stop-variability`

- Purpose: show why the previous 0.04 s wall-clock protocol could reverse an
  ablation conclusion.
- Data source: `solver_stop_sensitivity.csv`.
- Caption requirements: track0, two exact replays per cell, connected dots are
  repeats rather than uncertainty estimates.
- Observation: wall-clock runs vary by metres; fixed-iteration runs coincide.
- Implication: formal APE/RPE comparisons must use fixed iteration stopping.

## Figure 4: `figure-04-three-window-backend-comparison`

- Purpose: compare pure external KLT, original VINS internal stereo KLT, and
  AQUA-FE-safe on every currently available full stereo SeaFloor window.
- Data source: `three_window_backend.csv`.
- Caption requirements: fixed-iteration stereo-only protocol; track2 has zero
  learned observations; no error bars because deterministic duplicates are not
  independent samples.
- Observation: AQUA-FE-safe is below external KLT on all three windows and below
  original VINS on track1/track2, while original VINS remains best on track0.
- Implication: keep q_i and the safe learned policy, but do not claim a universal
  winner or attribute track2's improvement to learned geometry.
"""
    (output / "figure-catalog.md").write_text(catalog, encoding="utf-8")


def main() -> int:
    args = parse_args()
    output = args.output_dir.resolve()
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)

    rows = load_track1_rows()
    summary = summarize_track1(rows)
    wallclock = load_wallclock_rows()
    cross_window = load_cross_window_safe()
    three_window = load_three_window_backends()
    drift = build_drift_rows()
    learned_span = learned_span_relative_to_output()

    rows.to_csv(output / "run_metrics.csv", index=False)
    summary.to_csv(output / "comparison.csv", index=False)
    wallclock.to_csv(output / "solver_stop_sensitivity.csv", index=False)
    cross_window.to_csv(output / "cross_window_safe.csv", index=False)
    three_window.to_csv(output / "three_window_backend.csv", index=False)
    drift.to_csv(output / "drift_growth.csv", index=False)

    plot_track1(summary, figures)
    plot_drift(drift, learned_span, figures)
    plot_solver_variability(wallclock, figures)
    plot_three_window_backends(three_window, figures)
    write_reports(
        output, summary, wallclock, cross_window, three_window, learned_span
    )
    print(f"output_dir={output}")
    print(
        f"run_rows={len(rows)} comparison_rows={len(summary)} "
        f"cross_window_rows={len(cross_window)} "
        f"three_window_rows={len(three_window)} drift_rows={len(drift)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
