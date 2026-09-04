#!/usr/bin/env python3
"""Build the MIMIR-UW alternative-method comparison bundle.

The bundle intentionally separates fixed-scale SE(3) error, free-scale Sim(3)
diagnostics, trajectory scale, and output coverage.  It is descriptive: most
method/window cells contain one deterministic replay, so no inferential test is
valid.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from evaluate_vins_sim_ape import load_gt, load_vins, make_pairs


WINDOWS = {
    "seafloor_track0_s0_d45": "SeaFloor/track0 0–45 s",
    "seafloor_track2_s0_d45": "SeaFloor/track2 0–45 s",
    "seafloor_track1_s45_d45": "SeaFloor/track1 45–90 s",
}

ARM_NAMES = {
    "klt": "External KLT + VINS",
    "original": "Original VINS",
    "ours": "AQUA-FE + VINS",
}

COLORS = {
    "External KLT + VINS": "#56B4E9",
    "Original VINS": "#E69F00",
    "AQUA-FE + VINS": "#009E73",
    "ORB-SLAM3 stereo": "#CC79A7",
    "VINS stereo-only": "#6A3D9A",
    "ORB-SLAM3 mono": "#0072B2",
    "ORB-SLAM3 mono-inertial": "#D55E00",
    "DSO": "#000000",
}

VINS_STEREO_ONLY_RUNS = {
    "seafloor_track0_s0_d45": Path(
        "/mnt/data/AQUA-FE_WS/logs/mimir_uw_vins/"
        "mimir_vins_stereoonly_v3_seafloor_track0_s0_d45"
    ),
    "seafloor_track1_s45_d45": Path(
        "/mnt/data/AQUA-FE_WS/logs/mimir_uw_vins/"
        "mimir_vins_stereoonly_v3_seafloor_track1_s45_d45"
    ),
    "seafloor_track2_s0_d45": Path(
        "/mnt/data/AQUA-FE_WS/logs/mimir_uw_vins/"
        "mimir_vins_stereoonly_v3_seafloor_track2_s0_d45"
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--vins-diagnostics",
        type=Path,
        default=Path(
            "/mnt/data/AQUA-FE_WS/logs/mimir_rate1_final_bundle_v2/"
            "trajectory_diagnostics.csv"
        ),
    )
    parser.add_argument(
        "--alt-root",
        type=Path,
        default=Path("/mnt/data/AQUA-FE_WS/logs/mimir_alt_methods"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "/mnt/data/AQUA-FE_WS/logs/mimir_alt_methods/analysis_bundle"
        ),
    )
    return parser.parse_args()


def finite(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def read_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key] = value
    return values


def trajectory_path_ratio(vins_csv: Path, bag: Path) -> float:
    pairs, _ = make_pairs(load_vins(vins_csv), load_gt(bag, "/mimir/ground_truth"), 0.0)
    estimate = np.stack([row[1] for row in pairs])
    reference = np.stack([row[2] for row in pairs])
    estimate_length = float(np.linalg.norm(np.diff(estimate, axis=0), axis=1).sum())
    reference_length = float(np.linalg.norm(np.diff(reference, axis=0), axis=1).sum())
    return estimate_length / reference_length


def load_vins_stereo_only_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for window_id, run_dir in VINS_STEREO_ONLY_RUNS.items():
        metrics = read_key_values(run_dir / "ape.txt")
        manifest = read_key_values(run_dir / "replay_manifest.txt")
        trajectory = run_dir / "vins_output/vio.csv"
        bag = Path(manifest["raw_bag"])
        rows.append(
            {
                "window_id": window_id,
                "window": WINDOWS[window_id],
                "method": "VINS stereo-only",
                "family": "VINS-Fusion",
                "run": "internal_stereo_klt_no_imu",
                "pose_count": int(float(metrics["output_poses"])),
                "se3_ape_rmse_m": finite(metrics["se3_ape_rmse_m"]),
                "se3_rpe_1s_rmse_m": finite(metrics["rpe_trans_rmse_m"]),
                "output_coverage_ratio": finite(metrics["output_coverage_ratio"]),
                "first_output_delay_s": finite(metrics["first_output_delay_s"]),
                "path_length_ratio_est_gt": trajectory_path_ratio(trajectory, bag),
                "sim3_scale_est_to_gt": math.nan,
                "sim3_ape_rmse_m": math.nan,
                "sim3_rpe_1s_rmse_m": math.nan,
                "trajectory": str(trajectory),
                "coverage_note": (
                    "trajectory poses / input images; VINS internal stereo KLT, IMU disabled"
                ),
            }
        )
    return rows


def load_vins_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="") as handle:
        for src in csv.DictReader(handle):
            if src["stem"] not in WINDOWS or src["arm"] not in ARM_NAMES:
                continue
            rows.append(
                {
                    "window_id": src["stem"],
                    "window": WINDOWS[src["stem"]],
                    "method": ARM_NAMES[src["arm"]],
                    "family": "VINS-Fusion",
                    "run": "seed0",
                    "pose_count": int(src["pose_count"]),
                    "se3_ape_rmse_m": finite(src["se3_ape_rmse_m"]),
                    "se3_rpe_1s_rmse_m": finite(src["rpe_trans_rmse_m"]),
                    "output_coverage_ratio": finite(src["output_coverage_ratio"]),
                    "first_output_delay_s": finite(src["first_output_delay_s"]),
                    "path_length_ratio_est_gt": finite(
                        src["path_length_ratio_est_gt"]
                    ),
                    "sim3_scale_est_to_gt": finite(src["sim3_scale_est_to_gt"]),
                    "sim3_ape_rmse_m": finite(src["sim3_ape_rmse_m"]),
                    "sim3_rpe_1s_rmse_m": finite(src["sim3_rpe_rmse_m"]),
                    "trajectory": src["run_dir"],
                    "coverage_note": "trajectory poses / input images",
                }
            )
    return rows


def load_alt_csv(
    path: Path, window_id: str, include: set[str] | None = None
) -> list[dict[str, object]]:
    method_names = {
        "mono": "ORB-SLAM3 mono",
        "mono_inertial": "ORB-SLAM3 mono-inertial",
        "stereo": "ORB-SLAM3 stereo",
        "dso_r1": "DSO",
        "dso_r2": "DSO",
        "dso_r3": "DSO",
    }
    rows: list[dict[str, object]] = []
    with path.open(newline="") as handle:
        for src in csv.DictReader(handle):
            raw_method = src["method"]
            if include is not None and raw_method not in include:
                continue
            rows.append(
                {
                    "window_id": window_id,
                    "window": WINDOWS[window_id],
                    "method": method_names[raw_method],
                    "family": "direct VO" if raw_method.startswith("dso") else "ORB-SLAM3",
                    "run": raw_method,
                    "pose_count": int(src["pose_count"]),
                    "se3_ape_rmse_m": finite(src["se3_ape_rmse_m"]),
                    "se3_rpe_1s_rmse_m": finite(src["se3_rpe_1s_rmse_m"]),
                    "output_coverage_ratio": finite(src["output_coverage_ratio"]),
                    "first_output_delay_s": finite(src["first_output_delay_s"]),
                    "path_length_ratio_est_gt": finite(
                        src["path_length_ratio_est_gt"]
                    ),
                    "sim3_scale_est_to_gt": finite(src["sim3_scale_est_to_gt"]),
                    "sim3_ape_rmse_m": finite(src["sim3_ape_rmse_m"]),
                    "sim3_rpe_1s_rmse_m": finite(src["sim3_rpe_1s_rmse_m"]),
                    "trajectory": src["trajectory"],
                    "coverage_note": (
                        "keyframe output density; not tracking coverage"
                        if raw_method.startswith("dso")
                        else "trajectory poses / input images"
                    ),
                }
            )
    return rows


def write_summary(df: pd.DataFrame, path: Path) -> pd.DataFrame:
    grouped: list[dict[str, object]] = []
    for (window_id, method), group in df.groupby(["window_id", "method"], sort=False):
        record: dict[str, object] = {
            "window_id": window_id,
            "window": group.iloc[0]["window"],
            "method": method,
            "n_runs": len(group),
            "aggregation": "median [min, max]" if len(group) > 1 else "single run",
        }
        for col in (
            "se3_ape_rmse_m",
            "se3_rpe_1s_rmse_m",
            "output_coverage_ratio",
            "first_output_delay_s",
            "path_length_ratio_est_gt",
            "sim3_scale_est_to_gt",
            "sim3_ape_rmse_m",
            "sim3_rpe_1s_rmse_m",
        ):
            values = group[col].dropna().astype(float)
            record[col] = values.median() if len(values) else math.nan
            record[f"{col}_min"] = values.min() if len(values) else math.nan
            record[f"{col}_max"] = values.max() if len(values) else math.nan
        grouped.append(record)
    summary = pd.DataFrame(grouped)
    summary.to_csv(path, index=False)
    return summary


def plot_core(summary: pd.DataFrame, figures: Path) -> None:
    core_methods = [
        "External KLT + VINS",
        "Original VINS",
        "AQUA-FE + VINS",
        "VINS stereo-only",
        "ORB-SLAM3 stereo",
    ]
    window_ids = list(WINDOWS)
    fig, axes = plt.subplots(1, 3, figsize=(13.4, 4.2))
    metrics = [
        ("se3_ape_rmse_m", "SE(3) APE RMSE (m)", True),
        ("se3_rpe_1s_rmse_m", "1 s translational RPE RMSE (m)", True),
        ("output_coverage_ratio", "Exported-pose coverage", False),
    ]
    width = 0.16
    x = np.arange(len(window_ids))
    for ax, (metric, ylabel, log_scale) in zip(axes, metrics):
        for idx, method in enumerate(core_methods):
            vals = []
            for window_id in window_ids:
                cell = summary[
                    (summary.window_id == window_id) & (summary.method == method)
                ]
                vals.append(float(cell.iloc[0][metric]) if len(cell) else math.nan)
            ax.bar(
                x + (idx - (len(core_methods) - 1) / 2) * width,
                vals,
                width,
                color=COLORS[method],
                edgecolor="black",
                linewidth=0.45,
                label=method,
            )
        if log_scale:
            ax.set_yscale("log")
        else:
            ax.set_ylim(0, 1.08)
            ax.axhline(0.8, color="0.45", linestyle="--", linewidth=1)
        ax.set_ylabel(ylabel)
        ax.set_xticks(x)
        ax.set_xticklabels(["track0\n0–45 s", "track2\n0–45 s", "track1\n45–90 s"])
        ax.grid(axis="y", alpha=0.25, which="both")
    axes[0].legend(loc="upper center", bbox_to_anchor=(1.68, 1.22), ncol=5, frameon=False)
    fig.subplots_adjust(top=0.80, bottom=0.18, left=0.07, right=0.99, wspace=0.34)
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-01-core-comparison.{suffix}", dpi=600)
    plt.close(fig)


def plot_scale(summary: pd.DataFrame, figures: Path) -> None:
    keep = summary[
        summary.method.isin(
            [
                "External KLT + VINS",
                "Original VINS",
                "AQUA-FE + VINS",
                "VINS stereo-only",
                "ORB-SLAM3 stereo",
            ]
        )
    ].copy()
    markers = {
        "seafloor_track0_s0_d45": "o",
        "seafloor_track2_s0_d45": "s",
        "seafloor_track1_s45_d45": "^",
    }
    fig, ax = plt.subplots(figsize=(7.2, 4.8))
    ax.axvspan(0.8, 1.25, color="#F0E442", alpha=0.18, label="near-unit path scale")
    for _, row in keep.iterrows():
        ax.scatter(
            row.path_length_ratio_est_gt,
            row.se3_ape_rmse_m,
            s=40 + 150 * row.output_coverage_ratio,
            marker=markers[row.window_id],
            color=COLORS[row.method],
            edgecolor="black",
            linewidth=0.5,
            alpha=0.9,
        )
    for method in COLORS:
        if method not in set(keep.method):
            continue
        ax.scatter([], [], color=COLORS[method], edgecolor="black", label=method)
    for window_id, marker in markers.items():
        short_label = {
            "seafloor_track0_s0_d45": "track0 0–45 s",
            "seafloor_track2_s0_d45": "track2 0–45 s",
            "seafloor_track1_s45_d45": "track1 45–90 s",
        }[window_id]
        ax.scatter(
            [],
            [],
            marker=marker,
            facecolor="white",
            edgecolor="black",
            label=short_label,
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Estimated / ground-truth path length")
    ax.set_ylabel("SE(3) APE RMSE (m)")
    ax.grid(alpha=0.25, which="both")
    ax.legend(fontsize=8, ncol=2, frameon=False, loc="upper left")
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-02-scale-coverage-diagnostic.{suffix}", dpi=600)
    plt.close(fig)


def plot_track1_modalities(summary: pd.DataFrame, figures: Path) -> None:
    methods = [
        "External KLT + VINS",
        "Original VINS",
        "AQUA-FE + VINS",
        "ORB-SLAM3 mono",
        "ORB-SLAM3 mono-inertial",
        "DSO",
        "VINS stereo-only",
        "ORB-SLAM3 stereo",
    ]
    subset = summary[summary.window_id == "seafloor_track1_s45_d45"].set_index("method")
    x = np.arange(len(methods))
    se3 = np.array([subset.loc[m, "se3_ape_rmse_m"] for m in methods], dtype=float)
    sim3 = np.array([subset.loc[m, "sim3_ape_rmse_m"] for m in methods], dtype=float)
    fig, ax = plt.subplots(figsize=(9.3, 4.7))
    width = 0.36
    ax.bar(x - width / 2, se3, width, color="#0072B2", edgecolor="black", label="SE(3), fixed scale")
    ax.bar(x + width / 2, sim3, width, color="#E69F00", edgecolor="black", label="Sim(3), free scale")
    ax.set_yscale("log")
    ax.set_ylabel("APE RMSE (m)")
    ax.set_xticks(x)
    ax.set_xticklabels(
        [
            "KLT",
            "VINS",
            "AQUA-FE",
            "ORB mono",
            "ORB mono-IMU",
            "DSO",
            "VINS stereo-only",
            "ORB stereo",
        ],
        rotation=18,
        ha="right",
    )
    ax.grid(axis="y", alpha=0.25, which="both")
    ax.legend(frameon=False)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(figures / f"figure-03-track1-alignment-sensitivity.{suffix}", dpi=600)
    plt.close(fig)


def fmt(value: float) -> str:
    return "—" if not math.isfinite(value) else f"{value:.3f}"


def core_table(summary: pd.DataFrame) -> str:
    methods = [
        "External KLT + VINS",
        "Original VINS",
        "AQUA-FE + VINS",
        "VINS stereo-only",
        "ORB-SLAM3 stereo",
    ]
    lines = [
        "| Window | Method | APE (m) | RPE@1 s (m) | Coverage | Path ratio |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for window_id in WINDOWS:
        for method in methods:
            cell = summary[(summary.window_id == window_id) & (summary.method == method)]
            if not len(cell):
                continue
            row = cell.iloc[0]
            lines.append(
                f"| {WINDOWS[window_id]} | {method} | "
                f"{fmt(row.se3_ape_rmse_m)} | {fmt(row.se3_rpe_1s_rmse_m)} | "
                f"{row.output_coverage_ratio:.1%} | {fmt(row.path_length_ratio_est_gt)} |"
            )
    return "\n".join(lines)


def write_reports(summary: pd.DataFrame, output: Path) -> None:
    get = lambda w, m: summary[(summary.window_id == w) & (summary.method == m)].iloc[0]
    t0s = get("seafloor_track0_s0_d45", "ORB-SLAM3 stereo")
    t2s = get("seafloor_track2_s0_d45", "ORB-SLAM3 stereo")
    t1s = get("seafloor_track1_s45_d45", "ORB-SLAM3 stereo")
    t0v = get("seafloor_track0_s0_d45", "VINS stereo-only")
    t1v = get("seafloor_track1_s45_d45", "VINS stereo-only")
    t2v = get("seafloor_track2_s0_d45", "VINS stereo-only")
    t0a = get("seafloor_track0_s0_d45", "AQUA-FE + VINS")
    t2a = get("seafloor_track2_s0_d45", "AQUA-FE + VINS")
    t1a = get("seafloor_track1_s45_d45", "AQUA-FE + VINS")
    mono = get("seafloor_track1_s45_d45", "ORB-SLAM3 mono")
    dso = get("seafloor_track1_s45_d45", "DSO")
    health = pd.read_csv(output / "backend_health_profile.csv")
    drift = pd.read_csv(output / "backend_drift_growth.csv")
    health_accepted = int(health["accepted"].sum())
    health_total = int(len(health))
    health_track1 = health[
        (health.environment == "SeaFloor")
        & (health.track == "track1")
        & (health.start_offset_s == 45)
    ].iloc[0]
    health_track2 = health[
        (health.environment == "SeaFloor")
        & (health.track == "track2")
        & (health.start_offset_s == 0)
    ].iloc[0]
    drift_once = drift.drop_duplicates("run").set_index("run")
    drift_t0 = drift_once.loc["track0_bias_prior"]
    drift_t1 = drift_once.loc["track1_gated"]
    drift_t2 = drift_once.loc["track2_gated"]

    report = f"""# MIMIR-UW alternative-method analysis

## Analysis question

Do the very large MIMIR-UW APE values come from an unavoidable dataset limitation, or from monocular/VIO scale initialization? Compare KLT+VINS, original VINS, AQUA-FE+VINS, VINS stereo-only, ORB-SLAM3 mono/mono-inertial/stereo, and DSO while keeping fixed-scale SE(3) and free-scale Sim(3) interpretations separate.

## Exact core comparison

{core_table(summary)}

APE and RPE are lower-is-better. “Coverage” is exported poses divided by input images. For DSO only, the analogous field is keyframe output density and must not be read as tracking availability. ORB stereo on track0/track2 exports the largest single internally consistent map; disconnected maps are not stitched with ground truth.

## Key findings

1. **Stereo removes the catastrophic scale failure on the valid segments.** Track0 stereo has APE/RPE {t0s.se3_ape_rmse_m:.3f}/{t0s.se3_rpe_1s_rmse_m:.3f} m and path ratio {t0s.path_length_ratio_est_gt:.3f}, versus AQUA-FE+VINS {t0a.se3_ape_rmse_m:.1f}/{t0a.se3_rpe_1s_rmse_m:.1f} m and path ratio {t0a.path_length_ratio_est_gt:.1f}. Track2 stereo has {t2s.se3_ape_rmse_m:.3f}/{t2s.se3_rpe_1s_rmse_m:.3f} m and path ratio {t2s.path_length_ratio_est_gt:.3f}, versus AQUA-FE+VINS {t2a.se3_ape_rmse_m:.1f}/{t2a.se3_rpe_1s_rmse_m:.1f} m and path ratio {t2a.path_length_ratio_est_gt:.1f}.
2. **Stereo does not solve continuity.** The selected track0 and track2 stereo maps cover only {t0s.output_coverage_ratio:.1%} and {t2s.output_coverage_ratio:.1%}; logs show map resets and multiple disconnected maps. This is a feature persistence/local-map problem, distinct from metric-scale observability.
3. **AQUA-FE remains the best tested monocular-VIO frontend on the already-good track1 window, but not the best overall backend.** AQUA-FE+VINS gives {t1a.se3_ape_rmse_m:.3f}/{t1a.se3_rpe_1s_rmse_m:.3f} m, versus ORB stereo {t1s.se3_ape_rmse_m:.3f}/{t1s.se3_rpe_1s_rmse_m:.3f} m and VINS stereo-only {t1v.se3_ape_rmse_m:.3f}/{t1v.se3_rpe_1s_rmse_m:.3f} m. This is one deterministic window, not a general winner claim.
4. **The published monocular-style success is alignment-sensitive.** ORB mono changes from fixed-scale APE {mono.se3_ape_rmse_m:.3f} m to free-scale {mono.sim3_ape_rmse_m:.3f} m, requiring scale {mono.sim3_scale_est_to_gt:.2f} from estimate to ground truth. The latter nearly reproduces the MIMIR paper’s reported 8.78 m for SeaFloor track1. DSO’s three-run median free-scale APE is {dso.sim3_ape_rmse_m:.3f} m, but its median fixed-scale APE is {dso.se3_ape_rmse_m:.3f} m and its path ratio is {dso.path_length_ratio_est_gt:.3f}.
5. **Learned points are not the direct cause of the huge monocular-VIO APE.** KLT and AQUA-FE share the same failure scale on track0/track2, and track2 has no learned observations. The later controlled stereo ablation on track1 shows that 121 learned cam0 temporal observations reduce APE from 0.599 to 0.536 m relative to an identical-quality no-learned input, although RPE changes from 0.192 to 0.209 m. Naively turning those tracks into 103 local-LK cam1 depth observations instead degrades APE/RPE to 1.739/0.614 m; details are in `learned_stereo_seed_analysis/`.
6. **The backend health repair prevents false success but does not restore availability.** With zero-bias priors, bias reset, initialization gates, and a 10 m/s fail-fast threshold, {health_accepted}/{health_total} frozen windows pass. SeaFloor/track1 remains usable at APE/RPE {health_track1.se3_ape_rmse_m:.3f}/{health_track1.rpe_1s_rmse_m:.3f} m and {health_track1.coverage_ratio:.1%} coverage; SeaFloor/track2 is cut after {health_track2.output_poses:.0f} poses at {health_track2.coverage_ratio:.1%} coverage and is classified as failed, not as a low-APE success.
7. **VINS stereo-only is the first continuous metric backend on all three SeaFloor windows.** It gives APE/RPE/coverage of {t0v.se3_ape_rmse_m:.3f}/{t0v.se3_rpe_1s_rmse_m:.3f} m/{t0v.output_coverage_ratio:.1%} on track0, {t1v.se3_ape_rmse_m:.3f}/{t1v.se3_rpe_1s_rmse_m:.3f} m/{t1v.output_coverage_ratio:.1%} on track1, and {t2v.se3_ape_rmse_m:.3f}/{t2v.se3_rpe_1s_rmse_m:.3f} m/{t2v.output_coverage_ratio:.1%} on track2. It uses VINS's internal stereo KLT and no IMU, so it is an alternative backend baseline rather than the learned AQUA-FE result.
8. **The later AQUA-FE-safe stereo replay is continuous and bounded, but the source of improvement differs by window.** Under the fixed-iteration protocol it gives APE/RPE 1.372/0.498 m on track0, 0.536/0.209 m on track1, and 0.863/0.403 m on track2. Track1 contains 121 left-camera learned observations and is the learned APE positive; track0 is a learned no-harm result; track2 contains zero learned observations and isolates q_i. Exact ablations and solver-stop sensitivity are in `learned_stereo_seed_analysis/`.

## Mechanism diagnosis

- The MIMIR-UW subset is not intrinsically monocular: synchronized cam0/cam1 data and a calibrated 0.12 m stereo baseline are available.
- Monocular ORB/DSO have an arbitrary scale; Sim(3) can diagnose trajectory shape but cannot validate metric localization.
- VINS should recover scale from IMU, but the bad runs show implausible accepted scale/velocity and large path inflation. Time-resolved residuals are strongly quadratic: fitted error acceleration is {drift_t0.quadratic_error_accel_norm_mps2:.3f} m/s² on track0 and {drift_t2.quadratic_error_accel_norm_mps2:.3f} m/s² on track2, versus {drift_t1.quadratic_error_accel_norm_mps2:.3f} m/s² on usable track1; track2's quadratic fit has R²={drift_t2.quadratic_error_fit_r2:.3f}. This is consistent with a bad visual attitude/gravity initialization leaking gravity into translation, rather than a timestamp mismatch. The causal wording remains an inference because no direct ground-truth gravity-state probe is available inside the optimizer.
- Stereo anchors metric depth immediately. ORB stereo's partial coverage isolates its remaining problem as map continuity, while VINS stereo-only demonstrates that continuous near-metric tracking is possible on all three windows.
- A controlled 10 s track0 ablation uses identical stereo images/extrinsics: VINS stereo+IMU gives APE/RPE 11.336/4.928 m with a 1.313 m/s² quadratic error signature, while stereo-only gives 0.265/0.276 m at the same 95.4% coverage. This isolates the remaining VINS failure to the stereo+IMU state initialization/optimization path, not stereo calibration or synchronization.

## Backend repair and fail-safe validation

- The test backend now actually consumes the synthetic accelerometer/gyroscope zero-bias priors that the runner previously only advertised. The priors are opt-in and are applied to every active speed-bias state; the protected backend is untouched.
- Resetting and repropagating the synthetic biases after alignment makes the usable track1 result deterministic at approximately 1.740 m APE and 0.266 m RPE.
- Initialization scale and gyro-bias gates reject seven windows before publication. The remaining divergent track2 initialization is stopped when speed exceeds 10 m/s; its short-segment APE is not accepted because coverage is only {health_track2.coverage_ratio:.1%} and RPE is {health_track2.rpe_1s_rmse_m:.3f} m.
- `backend_health_profile.csv` is the nine-window acceptance table. `backend_drift_growth.csv` contains the 5 s scale/error-growth diagnosis. `scripts/run_mimir_uw_vins_health_profile.sh` is the reproducible replay entry point.
- The MIMIR adapter now supports exact synchronized cam0/cam1 bags, two-camera VINS configs, stereo-only mode, and split-bag replay. On all three SeaFloor windows, stereo-only keeps roughly 99% temporal coverage without restarts.

## Decision

- Keep SE(3) APE/RPE and coverage as the primary acceptance criteria; report Sim(3) only as a shape/scale diagnostic.
- Keep the new MIMIR-specific health profile as a fail-safe: it prevents divergent trajectories from being reported as successes, but its {health_accepted}/{health_total} acceptance rate is not deployable availability.
- Use VINS stereo-only as the current MIMIR metric backend baseline. Do not enable the existing stereo+IMU path until its initial attitude/gravity alignment is repaired and passes the same ablation.
- Learned 2-D seeds alone cannot make monocular scale observable. For the stereo backend, keep learned points as cam0 temporal KLT seeds and keep cam1 support classical by default; local-LK learned cam1 depth failed no-harm on track1. Use `learned_stereo_seed_analysis/` as the focused receipt and require a held-out depth validator before re-enabling learned cam1 observations.

## Claim Candidates

- Claim:
  - Source evidence: `comparison.csv`, `summary.csv`, `figures/figure-01-core-comparison.pdf`, and ORB run logs.
  - Allowed wording: On three selected SeaFloor windows, stereo kept valid-segment path scale within roughly 1.6–5.4% of ground-truth path length and removed the catastrophic VINS scale divergence.
  - Forbidden stronger wording: ORB-SLAM3 stereo solves MIMIR-UW or outperforms AQUA-FE overall.
  - Uncertainty: one run per stereo window; track0/track2 contain disconnected maps and partial single-map coverage.
  - Next check: repeat seeds/runs and evaluate all predeclared windows with a map-fragmentation metric.
  - Decision: keep

- Claim:
  - Source evidence: track1 mono and DSO rows in `comparison.csv` and `figures/figure-03-track1-alignment-sensitivity.pdf`.
  - Allowed wording: Monocular results on this window depend strongly on free-scale alignment and do not establish metric-scale accuracy.
  - Forbidden stronger wording: The original MIMIR paper’s monocular evaluation is invalid.
  - Uncertainty: our run uses a locally instrumented ORB-SLAM3 build; the mono APE nevertheless closely matches the reported paper value.
  - Next check: reproduce with a clean author-fork build when disk capacity permits.
  - Decision: keep

- Claim:
  - Source evidence: `backend_health_profile.csv`, `backend_drift_growth.csv`, and the corresponding VINS logs.
  - Allowed wording: On the frozen nine-window set, the MIMIR-specific backend health profile retained the usable SeaFloor/track1 result and prevented the eight other windows from being counted as valid full trajectories.
  - Forbidden stronger wording: The backend repair solves MIMIR-UW localization or proves gravity misalignment as the sole cause.
  - Uncertainty: one deterministic replay per window; the constant-acceleration signature supports, but does not uniquely prove, gravity leakage.
  - Next check: evaluate a stereo/depth-constrained VINS backend on all nine windows and report full-window coverage including resets.
  - Decision: keep

- Claim:
  - Source evidence: the three `mimir_vins_stereoonly_v3_*` runs, `comparison.csv`, and `vins_stereoonly_drift.csv`.
  - Allowed wording: VINS stereo-only produced continuous near-metric trajectories on all three tested SeaFloor windows, with 0.719–1.230 m APE and 98.9–99.0% temporal coverage.
  - Forbidden stronger wording: AQUA-FE solves all MIMIR-UW windows or the learned frontend caused the stereo-only improvement.
  - Uncertainty: the result uses VINS's internal stereo KLT, three selected windows, and one deterministic replay per window.
  - Next check: evaluate the safe cam0-learned/classical-stereo policy on additional predeclared stereo windows; do not reuse the track1 global-NCC threshold sweep as confirmatory evidence.
  - Decision: keep
"""
    (output / "analysis-report.md").write_text(report)

    stats = """# Statistical appendix

## Unit of analysis

The unit is a predeclared 45 s sequence window. Most method/window cells have one deterministic run (`n=1`). DSO has three runs on one window; these characterize within-window run variability but are not three independent sequence samples.

## Valid statistics

- Exact per-run APE, RPE, path ratio, pose-output ratio, and delay.
- DSO median and observed minimum/maximum across three runs.
- Absolute and relative descriptive differences between paired methods on the same window.
- Exact acceptance, rejection, fail-fast, and coverage outcomes for the nine-window health-profile replay.

## Blocked statistics

- No t-test, Wilcoxon test, confidence interval, or significance claim is valid with one run per method/window and only three selected SeaFloor windows.
- Windows are not independent random samples from all MIMIR-UW conditions; they were selected to diagnose known successes and scale failures.
- ORB stereo track0/track2 metrics describe the selected largest internally consistent map, not the full fragmented 45 s trajectory.
- DSO output density is keyframe density, not a comparable frame-level availability measure.
- The 1/9 health-profile acceptance fraction is descriptive for this frozen diagnostic roster, not a population success-rate estimate.

## Evaluation protocol

- Primary: fixed-scale SE(3) position APE RMSE and 1 s translational RPE RMSE after rigid alignment.
- Diagnostic: Sim(3) APE/RPE and fitted scale.
- Scale sanity: estimated path length divided by matched ground-truth path length.
- Availability: exported trajectory poses divided by input-image count, interpreted together with first-output delay and map-reset logs.
- No multiple-comparison correction is applied because no inferential hypothesis tests are performed.
"""
    (output / "stats-appendix.md").write_text(stats)

    catalog = """# Figure catalog

## Figure 01 — Core comparison

- Files: `figures/figure-01-core-comparison.pdf` and `.png`
- Purpose: compare fixed-scale accuracy and exported-pose coverage on the three SeaFloor diagnostic windows.
- Data source: `summary.csv`.
- Caption requirements: APE/RPE axes are logarithmic; bars are single runs without error bars; the dashed coverage line is 0.8; stereo track0/track2 represent the largest consistent map only.
- Observation: VINS stereo-only removes the hundreds-of-metres error while retaining about 99% temporal coverage; ORB stereo is accurate on track0/track2 but loses continuity.
- Interpretation: stereo metric scale and continuous tracking are both achievable on these windows, but not with the current stereo+IMU initialization.

## Figure 02 — Scale and coverage diagnostic

- Files: `figures/figure-02-scale-coverage-diagnostic.pdf` and `.png`
- Purpose: show the relationship between path-scale inflation and fixed-scale APE.
- Data source: `summary.csv`; marker area encodes exported-pose coverage and marker shape encodes window.
- Caption requirements: both axes are logarithmic; the yellow band marks path ratios 0.8–1.25; marker area is descriptive rather than an uncertainty interval.
- Observation: catastrophic VINS errors cluster far outside the near-unit scale band; stereo remains near unit scale.
- Interpretation: the largest APE values are scale failures, while stereo’s remaining limitation is fragmentation.

## Figure 03 — Alignment sensitivity on track1

- Files: `figures/figure-03-track1-alignment-sensitivity.pdf` and `.png`
- Purpose: distinguish metric fixed-scale error from free-scale trajectory-shape error.
- Data source: `summary.csv`; DSO is the median of three runs, all other bars are one run.
- Caption requirements: logarithmic APE axis; state that Sim(3) is diagnostic and cannot replace metric SE(3) scoring.
- Observation: ORB mono and DSO improve strongly after Sim(3), while well-scaled VINS/stereo change less or can worsen under the separately optimized criterion.
- Interpretation: a paper-reported monocular ATE after scale alignment is not evidence of metric-scale localization.
"""
    (output / "figure-catalog.md").write_text(catalog)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    figures = args.output_dir / "figures"
    figures.mkdir(exist_ok=True)

    rows = load_vins_rows(args.vins_diagnostics)
    rows += load_vins_stereo_only_rows()
    rows += load_alt_csv(
        args.alt_root / "seafloor_track1_s45_d45/evaluation/metrics.csv",
        "seafloor_track1_s45_d45",
    )
    rows += load_alt_csv(
        args.alt_root / "seafloor_track0_s0_d45/evaluation/metrics.csv",
        "seafloor_track0_s0_d45",
        {"stereo"},
    )
    rows += load_alt_csv(
        args.alt_root / "seafloor_track2_s0_d45/evaluation/metrics.csv",
        "seafloor_track2_s0_d45",
        {"stereo"},
    )
    df = pd.DataFrame(rows)
    df.to_csv(args.output_dir / "comparison.csv", index=False)
    summary = write_summary(df, args.output_dir / "summary.csv")
    plot_core(summary, figures)
    plot_scale(summary, figures)
    plot_track1_modalities(summary, figures)
    write_reports(summary, args.output_dir)
    print(f"wrote {len(df)} run rows and {len(summary)} summary rows to {args.output_dir}")


if __name__ == "__main__":
    main()
