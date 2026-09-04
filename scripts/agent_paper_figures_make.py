#!/usr/bin/env python3
"""Build compact paper figures/tables from existing frontend result CSVs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm, ListedColormap


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_paper_figures"

INPUTS = {
    "texture_breadth": ROOT
    / "logs"
    / "paper_texture_breadth"
    / "texture_breadth_summary.csv",
    "texture_matrix": ROOT
    / "logs"
    / "paper_texture_matrix"
    / "texture_matrix_summary.csv",
    "churn_gate_v2": ROOT
    / "logs"
    / "paper_texture_churn_gate_v2"
    / "churn_gate_v2_summary.csv",
    "long_window_v2": ROOT
    / "logs"
    / "opt_eval"
    / "long_window_v2"
    / "long_window_all_baselines_table.csv",
}

METHOD_META = {
    "klt": ("KLT", "classical baseline"),
    "klt_adaptive_clahe": (
        "KLT + adaptive CLAHE",
        "strong internal control / ablation reference",
    ),
    "normal_safe_sp_lg": ("SP+LG sidecar", "internal ablation"),
    "full_sp_lg_loftr": ("Hybrid SP+LG+LoFTR", "proposed hybrid"),
    "full_xfeat_loftr": ("Hybrid XFeat+LoFTR", "proposed variant"),
    "full_sp_lg_loftr_sparse_probe": (
        "Hybrid SP+LG+LoFTR sparse probe",
        "internal experimental ablation",
    ),
    "orb": ("ORB", "external classical baseline"),
    "xfeat": ("XFeat", "external learned baseline"),
    "superpoint_lightglue": (
        "SuperPoint+LightGlue",
        "external learned baseline",
    ),
    "loftr": ("LoFTR", "external learned baseline"),
    "continuity_optimized": (
        "Continuity-optimized output",
        "proposed frontend output",
    ),
    "backend_strict": (
        "Backend-strict measurement",
        "proposed geometry output",
    ),
}

METHOD_ORDER_CORE = [
    "klt_adaptive_clahe",
    "normal_safe_sp_lg",
    "full_sp_lg_loftr",
    "full_xfeat_loftr",
]

METHOD_ORDER_CORE_NO_CONTROL = [
    "normal_safe_sp_lg",
    "full_sp_lg_loftr",
    "full_xfeat_loftr",
]

METHOD_ORDER_LONG = [
    "klt",
    "orb",
    "xfeat",
    "superpoint_lightglue",
    "loftr",
    "continuity_optimized",
    "backend_strict",
]

METHOD_ORDER_TABLE = [
    "klt",
    "klt_adaptive_clahe",
    "normal_safe_sp_lg",
    "full_sp_lg_loftr",
    "full_xfeat_loftr",
    "full_sp_lg_loftr_sparse_probe",
    "orb",
    "xfeat",
    "superpoint_lightglue",
    "loftr",
    "continuity_optimized",
    "backend_strict",
]

DATASET_LABELS = {
    "aqualoc_h07_normal_mid": "AQUALOC-H07 normal",
    "aqualoc_h07_lowtex_extreme": "AQUALOC-H07 low-texture extreme",
    "aqualoc_h06_lowcontrast": "AQUALOC-H06 low contrast",
    "aqualoc_a06_planar_extreme": "AQUALOC-A06 planar extreme",
    "afrl_fl_degraded_extreme": "AFRL-FL degraded extreme",
    "aqualoc_h07_normal": "AQUALOC-H07 normal",
    "aqualoc_h07_lowtex": "AQUALOC-H07 low texture",
    "aqualoc_a06_planar_lowtex": "AQUALOC-A06 planar low texture",
    "afrl_fl_degraded": "AFRL-FL degraded",
    "afrl_fr_lowcoverage": "AFRL-FR low coverage",
    "AQUALOC-H07": "AQUALOC-H07 long",
    "AQUALOC-H06": "AQUALOC-H06 long",
    "AQUALOC-A06": "AQUALOC-A06 long",
    "AFRL-FL": "AFRL-FL long",
    "AFRL-FR": "AFRL-FR long",
}

PLOT_LABELS = {
    "AQUALOC-H07 normal": "H07\nnormal",
    "AQUALOC-H07 low-texture extreme": "H07\nlowtex",
    "AQUALOC-H06 low contrast": "H06\nlowctr",
    "AQUALOC-A06 planar extreme": "A06\nplanar",
    "AFRL-FL degraded extreme": "AFRL-FL\ndegraded",
}

DATASET_ORDER_CORE = [
    "aqualoc_h07_normal_mid",
    "aqualoc_h07_lowtex_extreme",
    "aqualoc_h06_lowcontrast",
    "aqualoc_a06_planar_extreme",
    "afrl_fl_degraded_extreme",
]

DATASET_ORDER_TABLE = [
    "aqualoc_h07_normal_mid",
    "aqualoc_h07_normal",
    "aqualoc_h07_lowtex_extreme",
    "aqualoc_h07_lowtex",
    "aqualoc_h06_lowcontrast",
    "aqualoc_a06_planar_extreme",
    "aqualoc_a06_planar_lowtex",
    "afrl_fl_degraded_extreme",
    "afrl_fl_degraded",
    "afrl_fr_lowcoverage",
    "AQUALOC-H07",
    "AQUALOC-H06",
    "AQUALOC-A06",
    "AFRL-FL",
    "AFRL-FR",
]

PALETTE = {
    "KLT + adaptive CLAHE": "#666666",
    "SP+LG sidecar": "#7A9E7E",
    "Hybrid SP+LG+LoFTR": "#2F6FA3",
    "Hybrid XFeat+LoFTR": "#C07A2D",
}


@dataclass(frozen=True)
class MetricSpec:
    column: str
    label: str
    short_label: str
    direction: str


CORE_METRICS = [
    MetricSpec("grid_cov_median", "Median grid coverage", "Grid coverage", "higher"),
    MetricSpec("track_age_median", "Median track age", "Track age", "higher"),
    MetricSpec("dropout_ratio_median", "Median dropout ratio", "Dropout ratio", "lower"),
    MetricSpec("dropout_mean", "Mean dropout", "Dropout mean", "lower"),
    MetricSpec("epi_error_median", "Median epipolar residual", "Epipolar residual", "lower"),
]


def ensure_inputs() -> None:
    missing = [str(path.relative_to(ROOT)) for path in INPUTS.values() if not path.exists()]
    if missing:
        joined = "\n".join(f"- {item}" for item in missing)
        raise FileNotFoundError(f"Missing input CSV(s):\n{joined}")


def read_table(name: str) -> pd.DataFrame:
    df = pd.read_csv(INPUTS[name])
    df["source_table"] = name
    return add_metadata(df)


def add_metadata(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["dataset_display"] = out["dataset"].map(DATASET_LABELS).fillna(out["dataset"])
    out["method_display"] = out["method"].map(
        lambda m: METHOD_META.get(m, (m, "unclassified"))[0]
    )
    out["method_role"] = out["method"].map(
        lambda m: METHOD_META.get(m, (m, "unclassified"))[1]
    )
    if {"start", "end"}.issubset(out.columns):
        out["window"] = out["start"].astype(str) + "-" + out["end"].astype(str)
    else:
        out["window"] = ""
    return out


def fmt_value(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        if abs(float(value)) >= 100:
            return f"{float(value):.1f}"
        if abs(float(value)) >= 10:
            return f"{float(value):.2f}"
        if abs(float(value)) >= 1:
            return f"{float(value):.3f}"
        return f"{float(value):.4f}"
    return str(value)


def write_csv_md(
    df: pd.DataFrame,
    stem: str,
    title: str,
    note: str | None = None,
    md_columns: Iterable[str] | None = None,
) -> None:
    csv_path = OUT_DIR / f"{stem}.csv"
    md_path = OUT_DIR / f"{stem}.md"
    df.to_csv(csv_path, index=False)

    display = df.copy()
    if md_columns is not None:
        display = display[list(md_columns)]
    display = display.rename(
        columns={
            "dataset_display": "dataset",
            "method_display": "method",
            "method_role": "role",
            "grid_cov_median": "grid cov",
            "track_age_median": "track age",
            "dropout_ratio_median": "dropout ratio",
            "dropout_mean": "dropout mean",
            "epi_error_median": "epi residual",
            "win_score_vs_klt_adaptive": "win score vs control",
        }
    )
    lines = [f"# {title}", ""]
    if note:
        lines.extend([note, ""])
    if display.empty:
        lines.append("_No rows._")
    else:
        cols = list(display.columns)
        lines.append("| " + " | ".join(cols) + " |")
        lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
        for _, row in display.iterrows():
            lines.append("| " + " | ".join(fmt_value(row[col]) for col in cols) + " |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def plot_grouped_bars(
    ax: plt.Axes,
    df: pd.DataFrame,
    metric: str,
    ylabel: str,
    dataset_order: list[str],
    method_order: list[str],
) -> None:
    x = np.arange(len(dataset_order))
    width = min(0.18, 0.78 / len(method_order))
    offsets = (np.arange(len(method_order)) - (len(method_order) - 1) / 2.0) * width

    for idx, method in enumerate(method_order):
        method_display = METHOD_META[method][0]
        values = []
        for dataset in dataset_order:
            match = df[(df["dataset"] == dataset) & (df["method"] == method)]
            values.append(np.nan if match.empty else match.iloc[0][metric])
        ax.bar(
            x + offsets[idx],
            values,
            width=width * 0.92,
            label=method_display,
            color=PALETTE.get(method_display, "#999999"),
            edgecolor="white",
            linewidth=0.5,
        )

    ax.set_ylabel(ylabel)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [PLOT_LABELS.get(DATASET_LABELS.get(d, d), DATASET_LABELS.get(d, d)) for d in dataset_order],
        rotation=0,
    )
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def save_metric_figures(core: pd.DataFrame) -> None:
    fig_specs = [
        ("grid_cov_median", "Median grid coverage (higher is better)", "fig_grid_coverage.png"),
        ("track_age_median", "Median track age (higher is better)", "fig_median_track_age.png"),
        ("epi_error_median", "Median epipolar residual (lower is better)", "fig_epipolar_residual.png"),
    ]
    for metric, ylabel, filename in fig_specs:
        fig, ax = plt.subplots(figsize=(7.4, 3.4))
        plot_grouped_bars(ax, core, metric, ylabel, DATASET_ORDER_CORE, METHOD_ORDER_CORE)
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, 1.18),
            ncol=2,
            frameon=False,
            fontsize=8,
        )
        fig.tight_layout(pad=0.8)
        fig.savefig(OUT_DIR / filename, dpi=300, bbox_inches="tight")
        plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 3.4))
    plot_grouped_bars(
        axes[0],
        core,
        "dropout_ratio_median",
        "Median dropout ratio\n(lower is better)",
        DATASET_ORDER_CORE,
        METHOD_ORDER_CORE,
    )
    plot_grouped_bars(
        axes[1],
        core,
        "dropout_mean",
        "Mean dropout\n(lower is better)",
        DATASET_ORDER_CORE,
        METHOD_ORDER_CORE,
    )
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.08),
        ncol=2,
        frameon=False,
        fontsize=8,
    )
    for ax in axes:
        legend = ax.get_legend()
        if legend:
            legend.remove()
    fig.tight_layout(pad=0.8)
    fig.savefig(OUT_DIR / "fig_dropout_ratio_mean.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def build_core_metric_values(core: pd.DataFrame) -> pd.DataFrame:
    records = []
    for _, row in core.iterrows():
        for spec in CORE_METRICS:
            records.append(
                {
                    "source_table": row["source_table"],
                    "dataset": row["dataset"],
                    "dataset_display": row["dataset_display"],
                    "window": row.get("window", ""),
                    "method": row["method"],
                    "method_display": row["method_display"],
                    "method_role": row["method_role"],
                    "metric": spec.column,
                    "metric_label": spec.label,
                    "direction": spec.direction,
                    "value": row[spec.column],
                }
            )
    return pd.DataFrame(records)


def compare_status(value: float, reference: float, direction: str, eps: float = 1e-9):
    if pd.isna(value) or pd.isna(reference):
        return np.nan, "missing", 0
    raw_delta = value - reference
    beneficial_delta = raw_delta if direction == "higher" else -raw_delta
    if beneficial_delta > eps:
        return beneficial_delta, "win", 1
    if beneficial_delta < -eps:
        return beneficial_delta, "loss", -1
    return beneficial_delta, "tie", 0


def build_winloss(core: pd.DataFrame) -> pd.DataFrame:
    control = core[core["method"] == "klt_adaptive_clahe"].set_index("dataset")
    records = []
    for _, row in core[core["method"].isin(METHOD_ORDER_CORE_NO_CONTROL)].iterrows():
        ref = control.loc[row["dataset"]]
        for spec in CORE_METRICS:
            beneficial, status, status_code = compare_status(
                row[spec.column], ref[spec.column], spec.direction
            )
            records.append(
                {
                    "source_table": row["source_table"],
                    "dataset": row["dataset"],
                    "dataset_display": row["dataset_display"],
                    "window": row.get("window", ""),
                    "method": row["method"],
                    "method_display": row["method_display"],
                    "method_role": row["method_role"],
                    "metric": spec.column,
                    "metric_label": spec.short_label,
                    "direction": spec.direction,
                    "value": row[spec.column],
                    "control_value": ref[spec.column],
                    "raw_delta": row[spec.column] - ref[spec.column],
                    "beneficial_delta": beneficial,
                    "status": status,
                    "status_code": status_code,
                }
            )
    return pd.DataFrame(records)


def save_winloss_heatmap(winloss: pd.DataFrame) -> None:
    row_order = []
    row_labels = []
    for dataset in DATASET_ORDER_CORE:
        dataset_label = DATASET_LABELS[dataset]
        plot_dataset = PLOT_LABELS.get(dataset_label, dataset_label).replace("\n", " ")
        for method in METHOD_ORDER_CORE_NO_CONTROL:
            method_label = METHOD_META[method][0]
            row_order.append((dataset, method))
            row_labels.append(f"{plot_dataset} / {method_label}")

    col_order = [spec.column for spec in CORE_METRICS]
    col_labels = [spec.short_label for spec in CORE_METRICS]
    matrix = np.zeros((len(row_order), len(col_order)))
    annotations: list[list[str]] = []
    for ridx, (dataset, method) in enumerate(row_order):
        ann_row = []
        for cidx, metric in enumerate(col_order):
            match = winloss[
                (winloss["dataset"] == dataset)
                & (winloss["method"] == method)
                & (winloss["metric"] == metric)
            ]
            if match.empty:
                matrix[ridx, cidx] = 0
                ann_row.append("")
            else:
                status_code = int(match.iloc[0]["status_code"])
                matrix[ridx, cidx] = status_code
                ann_row.append({1: "W", 0: "T", -1: "L"}.get(status_code, ""))
        annotations.append(ann_row)

    cmap = ListedColormap(["#C86B5D", "#F2F2F2", "#4F81BD"])
    norm = BoundaryNorm([-1.5, -0.5, 0.5, 1.5], cmap.N)
    fig, ax = plt.subplots(figsize=(8.2, 5.6))
    ax.imshow(matrix, cmap=cmap, norm=norm, aspect="auto")
    ax.set_xticks(np.arange(len(col_labels)))
    ax.set_xticklabels(col_labels, rotation=20, ha="right")
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels, fontsize=8)
    ax.set_xticks(np.arange(-0.5, len(col_labels), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(row_labels), 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=1.0)
    ax.tick_params(which="minor", bottom=False, left=False)
    for ridx in range(matrix.shape[0]):
        for cidx in range(matrix.shape[1]):
            color = "white" if matrix[ridx, cidx] != 0 else "#333333"
            ax.text(
                cidx,
                ridx,
                annotations[ridx][cidx],
                ha="center",
                va="center",
                fontsize=8,
                fontweight="bold",
                color=color,
            )
    ax.set_title("Win/tie/loss vs KLT + adaptive CLAHE", fontsize=10)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout(pad=0.7)
    fig.savefig(OUT_DIR / "fig_winloss_heatmap_vs_klt_adaptive.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def compact_short_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "source_table",
        "dataset",
        "dataset_display",
        "window",
        "method",
        "method_display",
        "method_role",
        "frames",
        "features_mean",
        "grid_cov_median",
        "track_age_median",
        "dropout_ratio_median",
        "dropout_mean",
        "epi_error_median",
        "f_inlier_median",
        "h_inlier_median",
        "runtime_ms_median",
        "win_score_vs_klt_adaptive",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    dataset_order = {name: idx for idx, name in enumerate(DATASET_ORDER_TABLE)}
    method_order = {name: idx for idx, name in enumerate(METHOD_ORDER_TABLE)}
    out["_dataset_order"] = out["dataset"].map(dataset_order).fillna(999)
    out["_method_order"] = out["method"].map(method_order).fillna(999)
    out = out.sort_values(
        ["source_table", "_dataset_order", "dataset_display", "_method_order", "method_display"]
    )
    return out.drop(columns=["_dataset_order", "_method_order"])


def compact_long_table(df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "source_table",
        "dataset",
        "dataset_display",
        "method",
        "method_display",
        "method_role",
        "frames",
        "features_mean",
        "grid_cov_median",
        "track_age_median",
        "long_track_ratio_mean",
        "dropout_ratio_median",
        "dropout_mean",
        "epi_error_median",
        "f_inlier_median",
        "h_inlier_median",
        "runtime_ms_median",
    ]
    out = df[[c for c in cols if c in df.columns]].copy()
    dataset_order = {name: idx for idx, name in enumerate(DATASET_ORDER_TABLE)}
    method_order = {name: idx for idx, name in enumerate(METHOD_ORDER_TABLE)}
    out["_dataset_order"] = out["dataset"].map(dataset_order).fillna(999)
    out["_method_order"] = out["method"].map(method_order).fillna(999)
    out = out.sort_values(["_dataset_order", "dataset_display", "_method_order", "method_display"])
    return out.drop(columns=["_dataset_order", "_method_order"])


def build_external_best_comparison(long_df: pd.DataFrame) -> pd.DataFrame:
    external_methods = ["klt", "orb", "xfeat", "superpoint_lightglue", "loftr"]
    proposed_for_metric = {
        "grid_cov_median": "continuity_optimized",
        "track_age_median": "continuity_optimized",
        "dropout_ratio_median": "continuity_optimized",
        "dropout_mean": "continuity_optimized",
        "epi_error_median": "backend_strict",
        "f_inlier_median": "backend_strict",
        "h_inlier_median": "backend_strict",
    }
    directions = {
        "grid_cov_median": "higher",
        "track_age_median": "higher",
        "dropout_ratio_median": "lower",
        "dropout_mean": "lower",
        "epi_error_median": "lower",
        "f_inlier_median": "higher",
        "h_inlier_median": "higher",
    }
    metric_labels = {
        "grid_cov_median": "Grid coverage",
        "track_age_median": "Track age",
        "dropout_ratio_median": "Dropout ratio",
        "dropout_mean": "Dropout mean",
        "epi_error_median": "Epipolar residual",
        "f_inlier_median": "F inlier ratio",
        "h_inlier_median": "H inlier ratio",
    }

    records = []
    for dataset, group in long_df.groupby("dataset", sort=False):
        ext = group[group["method"].isin(external_methods)]
        for metric, proposed_method in proposed_for_metric.items():
            if metric not in group.columns:
                continue
            ext_metric = ext[["method", "method_display", metric]].dropna()
            proposed_rows = group[group["method"] == proposed_method]
            if ext_metric.empty or proposed_rows.empty or pd.isna(proposed_rows.iloc[0][metric]):
                continue
            direction = directions[metric]
            if direction == "higher":
                best_idx = ext_metric[metric].idxmax()
            else:
                best_idx = ext_metric[metric].idxmin()
            best = ext_metric.loc[best_idx]
            proposed = proposed_rows.iloc[0]
            beneficial_delta, status, status_code = compare_status(
                proposed[metric], best[metric], direction
            )
            records.append(
                {
                    "source_table": proposed["source_table"],
                    "dataset": dataset,
                    "dataset_display": proposed["dataset_display"],
                    "metric": metric,
                    "metric_label": metric_labels[metric],
                    "direction": direction,
                    "proposed_method": proposed_method,
                    "proposed_method_display": proposed["method_display"],
                    "proposed_value": proposed[metric],
                    "best_external_method": best["method"],
                    "best_external_method_display": best["method_display"],
                    "best_external_value": best[metric],
                    "beneficial_delta_vs_best_external": beneficial_delta,
                    "status_vs_best_external": status,
                    "status_code": status_code,
                }
            )
    return pd.DataFrame(records)


def write_manifest() -> None:
    rows = []
    for name, path in INPUTS.items():
        rows.append(
            {
                "source_table": name,
                "path": str(path.relative_to(ROOT)),
                "available": path.exists(),
            }
        )
    pd.DataFrame(rows).to_csv(OUT_DIR / "source_manifest.csv", index=False)


def write_readme(
    core: pd.DataFrame,
    winloss: pd.DataFrame,
    churn: pd.DataFrame,
    external_cmp: pd.DataFrame,
) -> None:
    a06 = winloss[
        (winloss["dataset"] == "aqualoc_a06_planar_extreme")
        & (winloss["method"].isin(["full_sp_lg_loftr", "full_xfeat_loftr"]))
    ]
    a06_wins = int((a06["status"] == "win").sum())
    a06_total = int(len(a06))
    h07_extreme = winloss[winloss["dataset"] == "aqualoc_h07_lowtex_extreme"]
    h07_ties = int((h07_extreme["status"] == "tie").sum())

    churn_summary = churn[
        churn["method"].isin(["full_sp_lg_loftr", "full_xfeat_loftr"])
    ].copy()
    churn_bits = []
    for _, row in churn_summary.iterrows():
        churn_bits.append(
            f"{row['method_display']}: dropout mean delta "
            f"{row['delta_dropout_mean_vs_klt_adaptive']:.2f}, "
            f"epipolar delta {row['delta_epi_error_median_vs_klt_adaptive']:.4f}"
        )

    ext_counts = (
        external_cmp.groupby(["proposed_method_display", "metric_label", "status_vs_best_external"])
        .size()
        .reset_index(name="count")
    )
    ext_win_lines = []
    for _, row in ext_counts[ext_counts["status_vs_best_external"] == "win"].iterrows():
        ext_win_lines.append(
            f"{row['proposed_method_display']} wins {int(row['count'])}/5 on {row['metric_label']}"
        )

    lines = [
        "# Agent Paper Figures",
        "",
        "This package was generated from existing CSV summaries only. No data were downloaded and no experiments were rerun.",
        "",
        "## Source Tables",
        "",
        "- `logs/paper_texture_breadth/texture_breadth_summary.csv`: primary short-window paper figures.",
        "- `logs/paper_texture_matrix/texture_matrix_summary.csv`: supplemental matrix with KLT, adaptive CLAHE, sparse-probe, and hybrid variants.",
        "- `logs/paper_texture_churn_gate_v2/churn_gate_v2_summary.csv`: experimental churn-gate probe for the H07 extreme window.",
        "- `logs/opt_eval/long_window_v2/long_window_all_baselines_table.csv`: long-window external baseline comparison, when available.",
        "",
        "## Method Roles",
        "",
        "- `KLT + adaptive CLAHE` is treated as a strong internal control / ablation reference, not as an external baseline.",
        "- `SP+LG sidecar` and `Hybrid SP+LG+LoFTR sparse probe` are internal ablations.",
        "- `Hybrid SP+LG+LoFTR` and `Hybrid XFeat+LoFTR` are the short-window proposed hybrid variants.",
        "- `ORB`, `XFeat`, `SuperPoint+LightGlue`, and `LoFTR` in the long-window table are external or standalone baselines.",
        "- `Continuity-optimized output` and `Backend-strict measurement` are proposed long-window outputs with different metric emphasis.",
        "",
        "## Figure And Table Inventory",
        "",
        "- `table_method_dataset_core.csv/.md`: compact method-vs-dataset table for the five primary breadth windows.",
        "- `table_method_dataset_win_score_vs_control.csv/.md`: win-score matrix against `KLT + adaptive CLAHE`; the reference row is excluded.",
        "- `fig_grid_coverage.png`: shows coverage no-harm on normal/low-contrast windows and the planar A06 coverage gain.",
        "- `fig_median_track_age.png`: shows track-continuity behavior; A06 improves, while H07 extreme remains a limitation under the default gate.",
        "- `fig_dropout_ratio_mean.png`: shows dropout ratio and mean dropout together; useful for arguing continuity gains without hiding absolute dropout count.",
        "- `fig_epipolar_residual.png`: checks geometry cost; this is the guardrail figure for conservative claims.",
        "- `fig_winloss_heatmap_vs_klt_adaptive.png`: categorical win/tie/loss view for the five core metrics against the strong internal control.",
        "- `texture_matrix_compact.csv/.md`: supplemental wider short-window matrix.",
        "- `churn_gate_v2_compact.csv/.md`: experimental churn-gate probe; keep it separate from the default method claim.",
        "- `long_window_external_best_comparison.csv/.md`: proposed outputs compared to the best standalone external baseline per dataset and metric.",
        "",
        "## Claim Support",
        "",
        f"- Planar low-texture support: the two full hybrid variants record {a06_wins}/{a06_total} core metric wins on `AQUALOC-A06 planar extreme` against `KLT + adaptive CLAHE`.",
        f"- H07 extreme limitation: the default breadth comparison has {h07_ties}/{len(h07_extreme)} ties against the strong control, so do not claim recovery there from the default gate.",
        "- No-harm framing: use `fig_winloss_heatmap_vs_klt_adaptive.png` to distinguish exact ties from small wins/losses instead of relying only on bars.",
        "- Geometry guardrail: use `fig_epipolar_residual.png` before claiming learned recovery is uniformly better; AFRL degraded imagery is a tradeoff case.",
    ]
    if churn_bits:
        lines.append(
            "- Churn-gate caveat: `churn_gate_v2` improves dropout on H07 extreme but increases epipolar residual; "
            + "; ".join(churn_bits)
            + "."
        )
    if ext_win_lines:
        lines.append(
            "- External-baseline framing: "
            + "; ".join(ext_win_lines)
            + ". Keep these claims separate from the KLT+adaptive-CLAHE ablation figures."
        )
    lines.extend(
        [
            "",
            "## Recommended Paper Use",
            "",
            "Use the compact table plus the win/loss heatmap as the main result summary. Then use the four metric plots as supporting figures or subfigures. Put the long-window external-baseline table in a separate paragraph or appendix so readers do not confuse standalone learned matchers with the internal ablation reference.",
            "",
        ]
    )
    (OUT_DIR / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    ensure_inputs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    breadth = read_table("texture_breadth")
    matrix = read_table("texture_matrix")
    churn = read_table("churn_gate_v2")
    long_df = read_table("long_window_v2")

    core = (
        breadth[
            breadth["dataset"].isin(DATASET_ORDER_CORE)
            & breadth["method"].isin(METHOD_ORDER_CORE)
        ]
        .copy()
        .sort_values(
            ["dataset", "method"],
            key=lambda s: s.map(
                {name: idx for idx, name in enumerate(DATASET_ORDER_CORE + METHOD_ORDER_CORE)}
            ).fillna(999),
        )
    )

    core_compact = compact_short_table(core)
    write_csv_md(
        core_compact,
        "table_method_dataset_core",
        "Primary Method-vs-Dataset Compact Table",
        "Primary short-window breadth results. `KLT + adaptive CLAHE` is the strong internal control / ablation reference.",
        [
            "dataset_display",
            "window",
            "method_display",
            "method_role",
            "grid_cov_median",
            "track_age_median",
            "dropout_ratio_median",
            "dropout_mean",
            "epi_error_median",
            "win_score_vs_klt_adaptive",
        ],
    )

    win_score = (
        core[core["method"].isin(METHOD_ORDER_CORE_NO_CONTROL)]
        .pivot(index="method_display", columns="dataset_display", values="win_score_vs_klt_adaptive")
        .reindex([METHOD_META[m][0] for m in METHOD_ORDER_CORE_NO_CONTROL])
    )
    win_score = win_score[
        [DATASET_LABELS[d] for d in DATASET_ORDER_CORE if DATASET_LABELS[d] in win_score.columns]
    ].reset_index()
    write_csv_md(
        win_score,
        "table_method_dataset_win_score_vs_control",
        "Win Score Matrix vs KLT + Adaptive CLAHE",
        "Win score is read from the source summary and the reference control row is excluded.",
    )

    metric_values = build_core_metric_values(core)
    write_csv_md(
        metric_values,
        "core_metric_plot_values",
        "Core Metric Plot Values",
        "Long-form values used by the four metric PNG figures.",
        [
            "dataset_display",
            "window",
            "method_display",
            "method_role",
            "metric_label",
            "direction",
            "value",
        ],
    )
    save_metric_figures(core)

    winloss = build_winloss(core)
    write_csv_md(
        winloss,
        "winloss_heatmap_vs_klt_adaptive_values",
        "Win/Tie/Loss Values vs KLT + Adaptive CLAHE",
        "Positive status means better in the metric's preferred direction.",
        [
            "dataset_display",
            "window",
            "method_display",
            "metric_label",
            "direction",
            "value",
            "control_value",
            "beneficial_delta",
            "status",
        ],
    )
    save_winloss_heatmap(winloss)

    matrix_compact = compact_short_table(matrix)
    write_csv_md(
        matrix_compact,
        "texture_matrix_compact",
        "Supplemental Texture Matrix Compact Table",
        "Wider short-window matrix with plain KLT, adaptive CLAHE, sparse-probe, and hybrid variants.",
        [
            "dataset_display",
            "window",
            "method_display",
            "method_role",
            "grid_cov_median",
            "track_age_median",
            "dropout_ratio_median",
            "dropout_mean",
            "epi_error_median",
            "win_score_vs_klt_adaptive",
        ],
    )

    churn_compact = compact_short_table(churn)
    write_csv_md(
        churn_compact,
        "churn_gate_v2_compact",
        "Churn Gate v2 Compact Table",
        "Experimental churn-gate probe for H07 extreme. Keep separate from the default paper method claim.",
        [
            "dataset_display",
            "window",
            "method_display",
            "method_role",
            "grid_cov_median",
            "track_age_median",
            "dropout_ratio_median",
            "dropout_mean",
            "epi_error_median",
            "win_score_vs_klt_adaptive",
        ],
    )

    long_compact = compact_long_table(long_df)
    write_csv_md(
        long_compact,
        "long_window_external_all_methods_compact",
        "Long-Window All-Methods Compact Table",
        "Long-window table separates standalone external baselines from proposed outputs.",
        [
            "dataset_display",
            "method_display",
            "method_role",
            "grid_cov_median",
            "track_age_median",
            "long_track_ratio_mean",
            "dropout_ratio_median",
            "dropout_mean",
            "epi_error_median",
        ],
    )

    external_cmp = build_external_best_comparison(long_df)
    write_csv_md(
        external_cmp,
        "long_window_external_best_comparison",
        "Long-Window Best External Baseline Comparison",
        "Each row compares the relevant proposed output to the best standalone external baseline on that dataset and metric.",
        [
            "dataset_display",
            "metric_label",
            "direction",
            "proposed_method_display",
            "proposed_value",
            "best_external_method_display",
            "best_external_value",
            "beneficial_delta_vs_best_external",
            "status_vs_best_external",
        ],
    )

    write_manifest()
    write_readme(core, winloss, churn, external_cmp)

    print(f"Wrote paper figure package to {OUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
