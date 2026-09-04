#!/usr/bin/env python3
"""Generate H07 identity-churn diagnostics from existing frontend CSV logs."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_h07_churn"

MAIN_RUNS = [
    {
        "run_group": "default_breadth",
        "run_label": "default_full_xfeat_loftr",
        "method": "full_xfeat_loftr",
        "csv": ROOT
        / "logs/paper_texture_breadth/aqualoc_h07_lowtex_extreme_1740_1820_full_xfeat_loftr.csv",
    },
    {
        "run_group": "default_breadth",
        "run_label": "default_full_sp_lg_loftr",
        "method": "full_sp_lg_loftr",
        "csv": ROOT
        / "logs/paper_texture_breadth/aqualoc_h07_lowtex_extreme_1740_1820_full_sp_lg_loftr.csv",
    },
    {
        "run_group": "default_breadth",
        "run_label": "default_klt_adaptive_clahe",
        "method": "klt_adaptive_clahe",
        "csv": ROOT
        / "logs/paper_texture_breadth/aqualoc_h07_lowtex_extreme_1740_1820_klt_adaptive_clahe.csv",
    },
    {
        "run_group": "churn_gate_v2",
        "run_label": "churn_v2_full_sp_lg_loftr",
        "method": "full_sp_lg_loftr",
        "csv": ROOT
        / "logs/paper_texture_churn_gate_v2/aqualoc_h07_lowtex_extreme_1740_1820_full_sp_lg_loftr.csv",
    },
    {
        "run_group": "churn_gate_v2",
        "run_label": "churn_v2_full_xfeat_loftr",
        "method": "full_xfeat_loftr",
        "csv": ROOT
        / "logs/paper_texture_churn_gate_v2/aqualoc_h07_lowtex_extreme_1740_1820_full_xfeat_loftr.csv",
    },
    {
        "run_group": "churn_gate_v2",
        "run_label": "churn_v2_klt_adaptive_clahe",
        "method": "klt_adaptive_clahe",
        "csv": ROOT
        / "logs/paper_texture_churn_gate_v2/aqualoc_h07_lowtex_extreme_1740_1820_klt_adaptive_clahe.csv",
    },
]

NORMAL_REFERENCE = {
    "run_group": "default_breadth",
    "run_label": "default_h07_normal_mid_full_xfeat_loftr",
    "method": "full_xfeat_loftr",
    "csv": ROOT
    / "logs/paper_texture_breadth/aqualoc_h07_normal_mid_0_100_full_xfeat_loftr.csv",
}

LONG_CONTEXT = {
    "run_label": "hybrid_xfeat_1660_1950",
    "csv": ROOT / "logs/aqualoc_harbor07_1660_1950_hybrid_xfeat.csv",
}


def _safe_numeric(df: pd.DataFrame, col: str, default: float = np.nan) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(default, index=df.index, dtype="float64")


def _safe_text(df: pd.DataFrame, col: str, default: str = "") -> pd.Series:
    if col in df.columns:
        return df[col].fillna("").astype(str)
    return pd.Series(default, index=df.index, dtype="object")


def _dropout_ratio(df: pd.DataFrame) -> pd.Series:
    if "dropout_ratio" in df.columns:
        return _safe_numeric(df, "dropout_ratio")
    tracked = _safe_numeric(df, "tracked_before_filter")
    dropped = _safe_numeric(df, "dropped_features")
    return dropped / tracked.replace(0, np.nan)


def _learned_confirmed_count(df: pd.DataFrame) -> pd.Series:
    learned_cols = [
        c
        for c in df.columns
        if c.endswith("_confirmed_tracks")
        and any(k in c for k in ["xfeat", "superpoint", "loftr"])
    ]
    if not learned_cols:
        return pd.Series(0, index=df.index, dtype="int64")
    return df[learned_cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum(axis=1)


def _accepted_token_count(text: str) -> int:
    total = 0
    for match in re.finditer(r"accepted(?:_subset)?_(\d+)", text or ""):
        total += int(match.group(1))
    return total


def _reason_token_counts(series: pd.Series) -> Counter:
    counts: Counter[str] = Counter()
    for text in series.fillna("").astype(str):
        if not text:
            continue
        for token in text.split(";"):
            token = token.strip()
            if token:
                counts[token] += 1
    return counts


def load_frame_diag(spec: dict[str, object]) -> pd.DataFrame:
    df = pd.read_csv(spec["csv"])
    diag = pd.DataFrame(
        {
            "run_group": spec["run_group"],
            "run_label": spec["run_label"],
            "method": spec["method"],
            "source_csv": str(Path(spec["csv"]).relative_to(ROOT)),
            "frame_index": _safe_numeric(df, "frame_index").astype("Int64"),
            "num_features": _safe_numeric(df, "num_features"),
            "added_features": _safe_numeric(df, "added_features"),
            "dropped_features": _safe_numeric(df, "dropped_features"),
            "dropout_ratio": _dropout_ratio(df),
            "tracked_before_filter": _safe_numeric(df, "tracked_before_filter"),
            "tracked_after_filter": _safe_numeric(df, "tracked_after_filter"),
            "grid_coverage": _safe_numeric(df, "grid_coverage"),
            "grid_occupied": _safe_numeric(df, "grid_occupied"),
            "grid_total": _safe_numeric(df, "grid_total"),
            "median_track_age": _safe_numeric(df, "median_track_age"),
            "mean_track_age": _safe_numeric(df, "mean_track_age"),
            "long_track_ratio": _safe_numeric(df, "long_track_ratio"),
            "fundamental_inlier_ratio": _safe_numeric(df, "fundamental_inlier_ratio"),
            "homography_inlier_ratio": _safe_numeric(df, "homography_inlier_ratio"),
            "median_epipolar_error": _safe_numeric(df, "median_epipolar_error"),
            "median_homography_error": _safe_numeric(df, "median_homography_error"),
            "tracker_mode": _safe_text(df, "tracker_mode"),
            "tracker_recovery_reason": _safe_text(df, "tracker_recovery_reason"),
            "track_health_reason": _safe_text(df, "track_health_reason"),
            "frontend_state_reason": _safe_text(df, "frontend_state_reason"),
            "semidense_acceptance": _safe_text(df, "semidense_acceptance"),
            "geometry_safe_acceptance": _safe_text(df, "geometry_safe_acceptance"),
            "scheduler_mode": _safe_text(df, "scheduler_mode"),
            "scheduler_reason": _safe_text(df, "scheduler_reason"),
            "geometry_mode": _safe_text(df, "geometry_mode"),
            "geometry_reason": _safe_text(df, "geometry_reason"),
            "runtime_ms": _safe_numeric(df, "runtime_ms"),
        }
    )
    diag["learned_accepted_count"] = _learned_confirmed_count(df).astype(int)
    diag["accepted_token_count"] = _safe_text(df, "geometry_safe_acceptance").map(
        _accepted_token_count
    )
    diag["has_geometry_degradation_reject"] = _safe_text(
        df, "geometry_safe_acceptance"
    ).str.contains("rejected_geometry_degradation", regex=False)
    diag["has_source_gate_reject"] = _safe_text(df, "geometry_safe_acceptance").str.contains(
        "rejected_source_gate", regex=False
    )
    diag["has_too_few_candidates"] = _safe_text(df, "geometry_safe_acceptance").str.contains(
        "too_few_candidates", regex=False
    )
    diag["has_empty_candidates"] = _safe_text(df, "geometry_safe_acceptance").str.contains(
        "learned_initialization:empty", regex=False
    )
    return diag


def summarize_run(diag: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (group, label, method, source), g in diag.groupby(
        ["run_group", "run_label", "method", "source_csv"], dropna=False
    ):
        geom_counts = _reason_token_counts(g["geometry_safe_acceptance"])
        tracker_modes = ";".join(
            f"{k}:{v}" for k, v in g["tracker_mode"].value_counts().items() if k
        )
        track_reasons = ";".join(
            f"{k}:{v}"
            for k, v in g["track_health_reason"].value_counts().items()
            if k
        )
        rows.append(
            {
                "run_group": group,
                "run_label": label,
                "method": method,
                "source_csv": source,
                "frames": len(g),
                "frame_start": int(g["frame_index"].min()),
                "frame_end": int(g["frame_index"].max()),
                "features_mean": g["num_features"].mean(),
                "features_median": g["num_features"].median(),
                "grid_coverage_mean": g["grid_coverage"].mean(),
                "grid_coverage_median": g["grid_coverage"].median(),
                "grid_coverage_min": g["grid_coverage"].min(),
                "dropout_ratio_mean": g["dropout_ratio"].mean(),
                "dropout_ratio_median": g["dropout_ratio"].median(),
                "dropout_ratio_p90": g["dropout_ratio"].quantile(0.9),
                "median_track_age_median": g["median_track_age"].median(),
                "median_track_age_min": g["median_track_age"].min(),
                "median_track_age_max": g["median_track_age"].max(),
                "mean_track_age_mean": g["mean_track_age"].mean(),
                "long_track_ratio_mean": g["long_track_ratio"].mean(),
                "long_track_ratio_median": g["long_track_ratio"].median(),
                "fundamental_inlier_ratio_median": g[
                    "fundamental_inlier_ratio"
                ].median(),
                "homography_inlier_ratio_median": g["homography_inlier_ratio"].median(),
                "median_epipolar_error_median": g["median_epipolar_error"].median(),
                "median_epipolar_error_mean": g["median_epipolar_error"].mean(),
                "median_homography_error_median": g["median_homography_error"].median(),
                "learned_accepted_total": int(g["learned_accepted_count"].sum()),
                "learned_accepted_frames": int((g["learned_accepted_count"] > 0).sum()),
                "learned_accepted_max_frame": int(g["learned_accepted_count"].max()),
                "accepted_token_total": int(g["accepted_token_count"].sum()),
                "geometry_degradation_reject_frames": int(
                    g["has_geometry_degradation_reject"].sum()
                ),
                "source_gate_reject_frames": int(g["has_source_gate_reject"].sum()),
                "too_few_candidate_frames": int(g["has_too_few_candidates"].sum()),
                "empty_candidate_frames": int(g["has_empty_candidates"].sum()),
                "tracker_modes": tracker_modes,
                "track_health_reasons": track_reasons,
                "scheduler_reasons": ";".join(
                    f"{k}:{v}"
                    for k, v in g["scheduler_reason"].value_counts().items()
                    if k
                ),
                "semidense_events": ";".join(
                    f"{k}:{v}"
                    for k, v in g["semidense_acceptance"].value_counts().items()
                    if k
                ),
                "geometry_safe_top_tokens": ";".join(
                    f"{k}:{v}" for k, v in geom_counts.most_common(8)
                ),
                "runtime_ms_median": g["runtime_ms"].median(),
            }
        )
    return pd.DataFrame(rows)


def load_long_context() -> pd.DataFrame:
    df = pd.read_csv(LONG_CONTEXT["csv"])
    context = pd.DataFrame(
        {
            "run_label": LONG_CONTEXT["run_label"],
            "source_csv": str(Path(LONG_CONTEXT["csv"]).relative_to(ROOT)),
            "frame_index": _safe_numeric(df, "frame_index").astype("Int64"),
            "num_features": _safe_numeric(df, "num_features"),
            "dropout_ratio": _dropout_ratio(df),
            "dropped_features": _safe_numeric(df, "dropped_features"),
            "tracked_before_filter": _safe_numeric(df, "tracked_before_filter"),
            "grid_coverage": _safe_numeric(df, "grid_coverage"),
            "median_track_age": _safe_numeric(df, "median_track_age"),
            "mean_track_age": _safe_numeric(df, "mean_track_age"),
            "fundamental_inlier_ratio": _safe_numeric(df, "fundamental_inlier_ratio"),
            "median_epipolar_error": _safe_numeric(df, "median_epipolar_error"),
            "scheduler_mode": _safe_text(df, "scheduler_mode"),
            "scheduler_reason": _safe_text(df, "scheduler_reason"),
            "xfeat_recovery_tracks": _safe_numeric(df, "xfeat_recovery_tracks", 0),
            "runtime_ms": _safe_numeric(df, "runtime_ms"),
        }
    )
    frames = pd.to_numeric(context["frame_index"], errors="coerce")
    context["segment"] = np.select(
        [
            frames.between(1660, 1739).to_numpy(dtype=bool),
            frames.between(1740, 1820).to_numpy(dtype=bool),
            frames.between(1821, 1950).to_numpy(dtype=bool),
        ],
        ["pre_1660_1739", "extreme_1740_1820", "post_1821_1950"],
        default="outside",
    )
    return context


def summarize_context(context: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for seg, g in context.groupby("segment", sort=False):
        if seg == "outside" or g.empty:
            continue
        rows.append(
            {
                "segment": seg,
                "frames": len(g),
                "frame_start": int(g["frame_index"].min()),
                "frame_end": int(g["frame_index"].max()),
                "features_mean": g["num_features"].mean(),
                "grid_coverage_median": g["grid_coverage"].median(),
                "dropout_ratio_mean": g["dropout_ratio"].mean(),
                "dropout_ratio_median": g["dropout_ratio"].median(),
                "median_track_age_median": g["median_track_age"].median(),
                "mean_track_age_mean": g["mean_track_age"].mean(),
                "median_epipolar_error_median": g["median_epipolar_error"].median(),
                "fundamental_inlier_ratio_median": g[
                    "fundamental_inlier_ratio"
                ].median(),
                "scheduler_reasons": ";".join(
                    f"{k}:{v}"
                    for k, v in g["scheduler_reason"].value_counts().items()
                    if k
                ),
                "xfeat_recovery_tracks_total": int(g["xfeat_recovery_tracks"].sum()),
            }
        )
    return pd.DataFrame(rows)


def fmt(value: object, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return f"{value:.{digits}f}"
    return str(value)


def plot_main_timeseries(diag: pd.DataFrame) -> None:
    labels = [
        "default_full_xfeat_loftr",
        "churn_v2_full_sp_lg_loftr",
        "churn_v2_full_xfeat_loftr",
        "churn_v2_klt_adaptive_clahe",
    ]
    colors = {
        "default_full_xfeat_loftr": "#222222",
        "churn_v2_full_sp_lg_loftr": "#1f77b4",
        "churn_v2_full_xfeat_loftr": "#d95f02",
        "churn_v2_klt_adaptive_clahe": "#7f7f7f",
    }
    linestyles = {
        "default_full_xfeat_loftr": "-",
        "churn_v2_full_sp_lg_loftr": "-",
        "churn_v2_full_xfeat_loftr": "-",
        "churn_v2_klt_adaptive_clahe": "--",
    }
    pretty = {
        "default_full_xfeat_loftr": "default full XFeat",
        "churn_v2_full_sp_lg_loftr": "churn gate v2 SP-LG",
        "churn_v2_full_xfeat_loftr": "churn gate v2 XFeat",
        "churn_v2_klt_adaptive_clahe": "KLT ref",
    }
    metrics = [
        ("dropout_ratio", "Dropout ratio", (0, 1.0)),
        ("median_track_age", "Median track age", (0, 3.0)),
        ("grid_coverage", "Grid coverage", (0.85, 1.03)),
        ("median_epipolar_error", "Median epipolar residual", None),
        ("learned_accepted_count", "Learned accepted count", (-0.1, 2.4)),
    ]

    fig, axes = plt.subplots(len(metrics), 1, figsize=(11, 12), sharex=True)
    for ax, (metric, ylabel, ylim) in zip(axes, metrics):
        for label in labels:
            g = diag[diag["run_label"] == label].sort_values("frame_index")
            ax.plot(
                g["frame_index"],
                g[metric],
                label=pretty[label],
                color=colors[label],
                linestyle=linestyles[label],
                linewidth=1.7,
                marker="o" if metric == "learned_accepted_count" else None,
                markersize=3,
                alpha=0.92,
            )
        ax.set_ylabel(ylabel)
        if ylim is not None:
            ax.set_ylim(*ylim)
        ax.grid(True, color="#dddddd", linewidth=0.7, alpha=0.8)
    axes[0].set_title("H07 1740-1820 Identity Churn Diagnostics")
    axes[-1].set_xlabel("Frame index")
    handles, legend_labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center", ncol=4, frameon=False)
    fig.tight_layout(rect=[0, 0, 1, 0.965])
    fig.savefig(OUT_DIR / "h07_churn_timeseries.png", dpi=180)
    plt.close(fig)


def plot_summary_bars(summary: pd.DataFrame, normal_summary: pd.DataFrame) -> None:
    rows = pd.concat([summary, normal_summary], ignore_index=True)
    selected = [
        "default_h07_normal_mid_full_xfeat_loftr",
        "default_full_xfeat_loftr",
        "churn_v2_full_sp_lg_loftr",
        "churn_v2_full_xfeat_loftr",
    ]
    pretty = {
        "default_h07_normal_mid_full_xfeat_loftr": "H07 normal 0-100",
        "default_full_xfeat_loftr": "default extreme",
        "churn_v2_full_sp_lg_loftr": "churn v2 SP-LG",
        "churn_v2_full_xfeat_loftr": "churn v2 XFeat",
    }
    rows = rows[rows["run_label"].isin(selected)].set_index("run_label").loc[selected]
    metrics = [
        ("dropout_ratio_median", "Dropout median"),
        ("long_track_ratio_mean", "Long-track ratio mean"),
        ("grid_coverage_median", "Grid coverage median"),
        ("median_epipolar_error_median", "Epipolar residual median"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11, 7))
    axes = axes.ravel()
    palette = ["#2b8cbe", "#222222", "#1f77b4", "#d95f02"]
    x = np.arange(len(selected))
    for ax, (metric, title) in zip(axes, metrics):
        ax.bar(x, rows[metric].to_numpy(dtype=float), color=palette, width=0.72)
        ax.set_title(title)
        ax.set_xticks(x)
        ax.set_xticklabels([pretty[s] for s in selected], rotation=20, ha="right")
        ax.grid(True, axis="y", color="#dddddd", linewidth=0.7, alpha=0.8)
    fig.suptitle("Coverage Stays High While Track Identity Collapses")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(OUT_DIR / "h07_churn_summary_bars.png", dpi=180)
    plt.close(fig)


def plot_context(context: pd.DataFrame) -> None:
    metrics = [
        ("dropout_ratio", "Dropout ratio"),
        ("median_track_age", "Median track age"),
        ("grid_coverage", "Grid coverage"),
        ("median_epipolar_error", "Median epipolar residual"),
    ]
    fig, axes = plt.subplots(len(metrics), 1, figsize=(11, 9), sharex=True)
    for ax, (metric, ylabel) in zip(axes, metrics):
        ax.plot(
            context["frame_index"],
            context[metric],
            color="#333333",
            linewidth=1.5,
        )
        ax.axvspan(1740, 1820, color="#fdae61", alpha=0.18)
        ax.set_ylabel(ylabel)
        ax.grid(True, color="#dddddd", linewidth=0.7, alpha=0.8)
    axes[0].set_title("H07 1660-1950 Hybrid XFeat Context")
    axes[-1].set_xlabel("Frame index")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "h07_churn_long_context.png", dpi=180)
    plt.close(fig)


def write_report(
    summary: pd.DataFrame,
    normal_summary: pd.DataFrame,
    context_summary: pd.DataFrame,
) -> None:
    all_summary = pd.concat([summary, normal_summary], ignore_index=True).set_index(
        "run_label"
    )
    default = all_summary.loc["default_full_xfeat_loftr"]
    normal = all_summary.loc["default_h07_normal_mid_full_xfeat_loftr"]
    churn_sp = all_summary.loc["churn_v2_full_sp_lg_loftr"]
    churn_xfeat = all_summary.loc["churn_v2_full_xfeat_loftr"]
    churn_klt = all_summary.loc["churn_v2_klt_adaptive_clahe"]

    def delta(new: pd.Series, old: pd.Series, col: str) -> float:
        return float(new[col] - old[col])

    table_rows = [
        ("H07 normal 0-100 默认 full XFeat", normal),
        ("H07 1740-1820 默认 full XFeat", default),
        ("H07 1740-1820 churn v2 KLT 参照", churn_klt),
        ("H07 1740-1820 churn v2 SP-LG", churn_sp),
        ("H07 1740-1820 churn v2 XFeat", churn_xfeat),
    ]

    lines = [
        "# H07 Identity Churn 诊断报告",
        "",
        "本报告只复算既有 CSV 日志，没有重新跑 bag。主证据来自 H07 1740-1820 的逐帧 frontend 诊断；1660-1950 hybrid-XFeat 日志仅作为长窗口上下文参考。",
        "",
        "## 生成产物",
        "",
        "- `h07_churn_frame_diagnostics.csv`: 默认 breadth 与 churn-gate-v2 在 H07 1740-1820 上的统一逐帧诊断表。",
        "- `h07_churn_summary.csv`: 每个 run 的汇总指标、gate 状态和 reason 计数。",
        "- `h07_churn_long_context_1660_1950.csv`: H07 1660-1950 hybrid-XFeat 长窗口上下文。",
        "- `h07_churn_long_context_summary.csv`: 1660-1739、1740-1820、1821-1950 三段摘要。",
        "- `h07_churn_timeseries.png`: dropout ratio、median age、grid coverage、epipolar residual、learned accepted count 随帧变化。",
        "- `h07_churn_summary_bars.png`: 与 H07 normal 0-100 的紧凑对比。",
        "- `h07_churn_long_context.png`: 长窗口曲线，并标出 1740-1820 区间。",
        "",
        "## 结论",
        "",
        f"H07 1740-1820 不是低 coverage 失败。默认 full-XFeat run 的平均特征数是 {fmt(default['features_mean'], 1)}，grid coverage 中位数是 {fmt(default['grid_coverage_median'])}，最小值也有 {fmt(default['grid_coverage_min'])}。真正的失败形态是 identity churn：median track age 固定在 {fmt(default['median_track_age_median'])}，dropout ratio 中位数达到 {fmt(default['dropout_ratio_median'])}，mean long-track ratio 只有 {fmt(default['long_track_ratio_mean'])}。",
        "",
        f"H07 normal 0-100 参照段同样 coverage 很高（中位数 {fmt(normal['grid_coverage_median'])}），但连续性完全不同：median age 为 {fmt(normal['median_track_age_median'])}，dropout 中位数为 {fmt(normal['dropout_ratio_median'])}，mean long-track ratio 为 {fmt(normal['long_track_ratio_mean'])}。这个对比把问题从“覆盖不足”定位到“身份连续性崩塌”。",
        "",
        "## 关键指标",
        "",
        "| run | feature mean | grid cov med/min | dropout med/mean | median age | long-track mean | epi residual med | F inlier med | learned accepted |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, row in table_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    name,
                    fmt(row["features_mean"], 1),
                    f"{fmt(row['grid_coverage_median'])}/{fmt(row['grid_coverage_min'])}",
                    f"{fmt(row['dropout_ratio_median'])}/{fmt(row['dropout_ratio_mean'])}",
                    fmt(row["median_track_age_median"]),
                    fmt(row["long_track_ratio_mean"]),
                    fmt(row["median_epipolar_error_median"]),
                    fmt(row["fundamental_inlier_ratio_median"]),
                    f"{int(row['learned_accepted_total'])} / {int(row['learned_accepted_frames'])} frames",
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 默认 Gate 为什么不触发",
            "",
            "默认 breadth run 把 81/81 帧都标成 `tracker_mode=klt`、`tracker_recovery_reason=healthy`、`track_health_reason=healthy`、`frontend_state_reason=healthy`。与此同时，`scheduler_reason=high_dropout` 出现在 80/81 帧。关键分裂点就在这里：scheduler 看到了高 dropout，但 health/recovery gate 因为特征数量和 grid coverage 仍然很高，继续把 frontend 判为 healthy。",
            "",
            "因此默认 run 里 learned/semidense 实际没有贡献：`semidense_acceptance=loftr_gate_rejected_mode` 覆盖 81/81 帧，`geometry_safe_acceptance=disabled` 覆盖 81/81 帧，learned accepted count 为 0。",
            "",
            "## Churn Gate V2 改变了什么",
            "",
            f"churn gate v2 将 SP-LG run 的 80/81 帧标成 `track_identity_churn`。SP-LG 的 tracker mode 分布变为 `{churn_sp['tracker_modes']}`，并记录 {int(churn_sp['learned_accepted_total'])} 个 learned accepted tracks，分布在 {int(churn_sp['learned_accepted_frames'])} 帧。XFeat 同样触发 churn，但 learned acceptance 仍为 0，因为 source gate 拒绝了它（`source_gate_reject_frames={int(churn_xfeat['source_gate_reject_frames'])}`）。",
            "",
            f"SP-LG 的 churn proxy 确实朝预期方向移动：dropout 中位数相对默认变化 {fmt(delta(churn_sp, default, 'dropout_ratio_median'))}，mean long-track ratio 变化 {fmt(delta(churn_sp, default, 'long_track_ratio_mean'))}，mean track age 变化 {fmt(delta(churn_sp, default, 'mean_track_age_mean'))}。这些改善是真实的，但幅度小，而且 median track age 仍是 {fmt(churn_sp['median_track_age_median'])}。",
            "",
            "## 为什么几何残差变差",
            "",
            f"SP-LG churn gate 改善了连续性 proxy，但 median epipolar residual 从 {fmt(default['median_epipolar_error_median'])} 变差到 {fmt(churn_sp['median_epipolar_error_median'])}；XFeat 进一步变差到 {fmt(churn_xfeat['median_epipolar_error_median'])}。Fundamental inlier 中位数也从默认的 {fmt(default['fundamental_inlier_ratio_median'])} 降到 SP-LG 的 {fmt(churn_sp['fundamental_inlier_ratio_median'])}、XFeat 的 {fmt(churn_xfeat['fundamental_inlier_ratio_median'])}。",
            "",
            "这说明实验 trigger 抓住了正确失败模式，但 learned 接纳策略还不够 geometry-safe。它减少了马上丢失的 identity，却没有充分证明新接纳 identity 的几何一致性。SP-LG run 还记录了几何侧警告："
            f"`too_few_candidate_frames={int(churn_sp['too_few_candidate_frames'])}`、`empty_candidate_frames={int(churn_sp['empty_candidate_frames'])}`、`geometry_degradation_reject_frames={int(churn_sp['geometry_degradation_reject_frames'])}`。也就是说，learned 路径本身很稀疏，并且有部分候选被明确判为 geometry degradation；即使被接纳，也可能把 residual 拉高。",
            "",
            "长窗口 hybrid-XFeat 日志在更大尺度上支持同一诊断：1740-1820 区间的 median track age 和 dropout 明显劣于周边帧，而 coverage 仍非低值。不过它来自不同 run/configuration，因此只作为上下文，不作为主比较。",
            "",
            "## 下一步 Geometry-Safe 接纳策略",
            "",
            "1. 将 churn trigger 和 learned admission 分离。trigger 可以采用 rolling 条件：高 coverage + 高 dropout + 低 median age 或低 long-track ratio，例如连续多帧满足 coverage >= 0.9、dropout > 0.5、median age <= 2 或 long-track ratio < 0.25。",
            "2. 将 learned tracks 设为 probationary。先进入 staging pool，要求 2-3 帧 descriptor/patch consistency 和运动一致性，再进入可影响 backend 的特征集合。",
            "3. 几何先于补数量。接纳 learned addition 之前，要求 median epipolar residual 和 fundamental inlier ratio 相对 KLT-only 当前参考或短时 rolling baseline 不退化。",
            "4. 使用 per-cell quota 和 residual-ranked selection。优先选择少量、空间分散、通过 strict symmetric epipolar check 的 learned tracks，而不是在已经有 coverage 的 grid 里填身份数。",
            "5. 保留 source-specific gate。这个切片上 XFeat 被 source gate 阻断是合理的；除非能通过 residual-neutral admission test，否则不应进默认配置。",
            "6. 未来 churn fix 必须成对报告：dropout/age/long-track ratio 改善的同时，epipolar residual 和 inlier ratio 至少保持中性。",
            "",
            "## 长窗口上下文摘要",
            "",
            "| segment | frames | grid cov med | dropout med | median age | epi residual med | F inlier med | scheduler reasons |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for _, row in context_summary.iterrows():
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["segment"]),
                    str(int(row["frames"])),
                    fmt(row["grid_coverage_median"]),
                    fmt(row["dropout_ratio_median"]),
                    fmt(row["median_track_age_median"]),
                    fmt(row["median_epipolar_error_median"]),
                    fmt(row["fundamental_inlier_ratio_median"]),
                    str(row["scheduler_reasons"]),
                ]
            )
            + " |"
        )
    lines.append("")

    (OUT_DIR / "h07_churn_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    diag = pd.concat([load_frame_diag(spec) for spec in MAIN_RUNS], ignore_index=True)
    normal_diag = load_frame_diag(NORMAL_REFERENCE)
    summary = summarize_run(diag)
    normal_summary = summarize_run(normal_diag)
    context = load_long_context()
    context_summary = summarize_context(context)

    diag.to_csv(OUT_DIR / "h07_churn_frame_diagnostics.csv", index=False)
    summary.to_csv(OUT_DIR / "h07_churn_summary.csv", index=False)
    normal_diag.to_csv(OUT_DIR / "h07_churn_normal_reference_frame_diagnostics.csv", index=False)
    normal_summary.to_csv(OUT_DIR / "h07_churn_normal_reference_summary.csv", index=False)
    context.to_csv(OUT_DIR / "h07_churn_long_context_1660_1950.csv", index=False)
    context_summary.to_csv(OUT_DIR / "h07_churn_long_context_summary.csv", index=False)

    plot_main_timeseries(diag)
    plot_summary_bars(summary, normal_summary)
    plot_context(context)
    write_report(summary, normal_summary, context_summary)

    print(f"Wrote H07 churn diagnostics to {OUT_DIR}")


if __name__ == "__main__":
    main()
