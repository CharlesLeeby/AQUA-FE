#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_multiwindow_stats"

SOURCE_SPECS = [
    ("texture_matrix", ROOT / "logs/paper_texture_matrix/texture_matrix_summary.csv"),
    ("texture_breadth", ROOT / "logs/paper_texture_breadth/texture_breadth_summary.csv"),
    ("a06_long_window", ROOT / "logs/agent_a06_long_window/a06_long_summary.csv"),
    ("long_window_v2", ROOT / "logs/opt_eval/long_window_v2/long_window_all_baselines_table.csv"),
    ("churn_gate_v2", ROOT / "logs/paper_texture_churn_gate_v2/churn_gate_v2_summary.csv"),
]

CONTROL_METHOD = "klt_adaptive_clahe"
WINLOSS_METHODS = {
    "normal_safe_sp_lg",
    "full_sp_lg_loftr",
    "full_xfeat_loftr",
}

SCENE_ORDER = {
    "normal": 0,
    "low contrast": 1,
    "planar low texture": 2,
    "degraded": 3,
    "identity churn": 4,
    "unmapped": 99,
}

METHOD_ORDER = {
    "klt": 0,
    "klt_adaptive_clahe": 1,
    "normal_safe_sp_lg": 2,
    "full_sp_lg_loftr": 3,
    "full_xfeat_loftr": 4,
    "continuity_optimized": 5,
    "backend_strict": 6,
}

METRICS = [
    "features_mean",
    "grid_cov_median",
    "track_age_median",
    "mean_track_age",
    "long_track_ratio",
    "dropout_mean",
    "dropout_ratio_median",
    "f_inlier_median",
    "h_inlier_median",
    "epi_error_median",
    "homography_error_median",
    "quality_median",
    "low_texture_age_median",
    "visual_sigma_median",
    "runtime_ms_median",
    "win_score_vs_klt_adaptive",
]

WINLOSS_METRICS = {
    "grid_cov_median": ("higher", 0.010),
    "track_age_median": ("higher", 0.500),
    "long_track_ratio": ("higher", 0.005),
    "dropout_mean": ("lower", 0.500),
    "dropout_ratio_median": ("lower", 0.005),
    "f_inlier_median": ("higher", 0.005),
    "h_inlier_median": ("higher", 0.005),
    "epi_error_median": ("lower", 0.005),
}

METHOD_DISPLAY = {
    "klt": "KLT",
    "klt_adaptive_clahe": "KLT + adaptive CLAHE",
    "normal_safe_sp_lg": "SP+LG sidecar",
    "full_sp_lg_loftr": "Hybrid SP+LG+LoFTR",
    "full_xfeat_loftr": "Hybrid XFeat+LoFTR",
    "continuity_optimized": "Continuity-optimized",
    "backend_strict": "Backend-strict",
    "orb": "ORB",
    "xfeat": "XFeat",
    "superpoint_lightglue": "SuperPoint+LightGlue",
    "loftr": "LoFTR",
}


def read_sources() -> tuple[pd.DataFrame, list[str]]:
    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for source_table, path in SOURCE_SPECS:
        if not path.exists():
            missing.append(str(path.relative_to(ROOT)))
            continue
        df = pd.read_csv(path)
        frames.append(standardize(df, source_table, path))
    if not frames:
        raise RuntimeError("No input CSV files were found.")
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined[combined["scene_type"].isin(SCENE_ORDER)].copy()
    combined["method_display"] = combined["method"].map(METHOD_DISPLAY).fillna(combined["method"])
    combined["method_family"] = combined["method"].map(method_family)
    combined["sort_scene"] = combined["scene_type"].map(SCENE_ORDER).fillna(99).astype(int)
    combined["sort_method"] = combined["method"].map(METHOD_ORDER).fillna(50).astype(int)
    combined = combined.sort_values(
        ["sort_scene", "dataset", "start", "end", "sort_method", "method", "source_table"]
    ).reset_index(drop=True)
    return combined, missing


def standardize(df: pd.DataFrame, source_table: str, path: Path) -> pd.DataFrame:
    rename = {
        "long_track_ratio_mean": "long_track_ratio",
        "grid_coverage_median": "grid_cov_median",
        "median_track_age_median": "track_age_median",
        "mean_track_age_mean": "mean_track_age",
        "dropout_ratio_mean": "dropout_mean",
        "fundamental_inlier_ratio_median": "f_inlier_median",
        "homography_inlier_ratio_median": "h_inlier_median",
        "median_epipolar_error_median": "epi_error_median",
        "median_homography_error_median": "homography_error_median",
        "frame_start": "start",
        "frame_end": "end",
        "source_csv": "csv",
    }
    out = df.rename(columns=rename).copy()
    for col in ["dataset", "method", "start", "end", "frames"]:
        if col not in out.columns:
            out[col] = np.nan
    for metric in METRICS:
        if metric not in out.columns:
            out[metric] = np.nan
    if "csv" not in out.columns:
        out["csv"] = np.nan
    out["source_table"] = source_table
    out["source_path"] = str(path.relative_to(ROOT))
    out["dataset"] = out["dataset"].astype(str)
    out["method"] = out["method"].astype(str)
    out["window"] = out.apply(make_window_label, axis=1)
    out["scene_type"] = out.apply(assign_scene_type, axis=1)
    keep = [
        "source_table",
        "source_path",
        "dataset",
        "scene_type",
        "window",
        "start",
        "end",
        "method",
        "frames",
        *METRICS,
        "csv",
    ]
    return out[keep]


def make_window_label(row: pd.Series) -> str:
    start = row.get("start", np.nan)
    end = row.get("end", np.nan)
    if pd.notna(start) and pd.notna(end):
        return f"{int(start)}-{int(end)}"
    return "long"


def assign_scene_type(row: pd.Series) -> str:
    dataset = str(row.get("dataset", "")).lower()
    source = str(row.get("source_table", "")).lower()

    if "normal" in dataset:
        return "normal"
    if "churn" in source or "h07_lowtex" in dataset:
        return "identity churn"
    if dataset in {"aqualoc-h07", "aqualoc_h07"}:
        return "identity churn"
    if "lowcontrast" in dataset or "aqualoc-h06" in dataset or "aqualoc_h06" in dataset:
        return "low contrast"
    if "planar" in dataset or "aqualoc-a06" in dataset or "aqualoc_a06" in dataset:
        return "planar low texture"
    if "degraded" in dataset or "lowcoverage" in dataset or dataset.startswith("afrl"):
        return "degraded"
    return "unmapped"


def method_family(method: str) -> str:
    if method == CONTROL_METHOD:
        return "control"
    if method in {"full_sp_lg_loftr", "full_xfeat_loftr"}:
        return "proposed_full"
    if method == "normal_safe_sp_lg":
        return "sidecar_ablation"
    if method in {"continuity_optimized", "backend_strict"}:
        return "long_window_proposed_output"
    if method in {"klt", "orb"}:
        return "classical_baseline"
    if method in {"xfeat", "superpoint_lightglue", "loftr"}:
        return "learned_baseline"
    return "other"


def mean_std(values: pd.Series) -> tuple[float, float]:
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if clean.empty:
        return (np.nan, np.nan)
    mean = float(clean.mean())
    std = float(clean.std(ddof=1)) if len(clean) > 1 else np.nan
    return mean, std


def build_scene_stats(records: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["scene_type", "method", "method_display", "method_family"]
    for key, group in records.groupby(group_cols, dropna=False, sort=False):
        scene_type, method, method_display, method_family_name = key
        row = {
            "scene_type": scene_type,
            "method": method,
            "method_display": method_display,
            "method_family": method_family_name,
            "n_rows": int(len(group)),
            "n_windows": int(group["source_table"].astype(str).str.cat(
                [group["dataset"].astype(str), group["window"].astype(str)], sep=":"
            ).nunique()),
            "frames_sum": float(pd.to_numeric(group["frames"], errors="coerce").sum()),
        }
        for metric in METRICS:
            mean, std = mean_std(group[metric])
            row[f"{metric}_mean"] = mean
            row[f"{metric}_std"] = std
        rows.append(row)
    stats = pd.DataFrame(rows)
    stats["sort_scene"] = stats["scene_type"].map(SCENE_ORDER).fillna(99).astype(int)
    stats["sort_method"] = stats["method"].map(METHOD_ORDER).fillna(50).astype(int)
    stats = stats.sort_values(["sort_scene", "sort_method", "method"]).drop(
        columns=["sort_scene", "sort_method"]
    )
    return stats.reset_index(drop=True)


def build_winloss(records: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    detail_rows = []
    pair_cols = ["source_table", "dataset", "scene_type", "window"]
    for pair_key, group in records.groupby(pair_cols, dropna=False, sort=False):
        control = group[group["method"] == CONTROL_METHOD]
        if control.empty:
            continue
        control_row = control.iloc[0]
        competitors = group[group["method"].isin(WINLOSS_METHODS)]
        for _, method_row in competitors.iterrows():
            for metric, (direction, eps) in WINLOSS_METRICS.items():
                value = numeric_or_nan(method_row.get(metric))
                control_value = numeric_or_nan(control_row.get(metric))
                if pd.isna(value) or pd.isna(control_value):
                    continue
                raw_delta = value - control_value
                beneficial_delta = raw_delta if direction == "higher" else -raw_delta
                if beneficial_delta > eps:
                    status = "win"
                elif beneficial_delta < -eps:
                    status = "loss"
                else:
                    status = "tie"
                detail_rows.append(
                    {
                        "source_table": pair_key[0],
                        "dataset": pair_key[1],
                        "scene_type": pair_key[2],
                        "window": pair_key[3],
                        "method": method_row["method"],
                        "method_display": method_row["method_display"],
                        "method_family": method_row["method_family"],
                        "control_method": CONTROL_METHOD,
                        "metric": metric,
                        "direction": direction,
                        "tie_epsilon": eps,
                        "value": value,
                        "control_value": control_value,
                        "raw_delta": raw_delta,
                        "beneficial_delta": beneficial_delta,
                        "status": status,
                    }
                )
    details = pd.DataFrame(detail_rows)
    if details.empty:
        return details, pd.DataFrame(), pd.DataFrame()

    window_scores = build_window_scores(details)
    summary = summarize_winloss(details, window_scores)
    return details, window_scores, summary


def numeric_or_nan(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def build_window_scores(details: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_cols = ["method", "method_display", "method_family", "scene_type", "source_table", "dataset", "window"]
    for key, group in details.groupby(group_cols, dropna=False, sort=False):
        counts = group["status"].value_counts()
        wins = int(counts.get("win", 0))
        ties = int(counts.get("tie", 0))
        losses = int(counts.get("loss", 0))
        valid = wins + ties + losses
        score = (wins - losses) / valid if valid else np.nan
        if pd.isna(score) or abs(score) < 1e-12:
            window_status = "tie"
        elif score > 0:
            window_status = "win"
        else:
            window_status = "loss"
        rows.append(
            {
                "method": key[0],
                "method_display": key[1],
                "method_family": key[2],
                "scene_type": key[3],
                "source_table": key[4],
                "dataset": key[5],
                "window": key[6],
                "metric_wins": wins,
                "metric_ties": ties,
                "metric_losses": losses,
                "valid_metrics": valid,
                "window_score": score,
                "window_status": window_status,
            }
        )
    return pd.DataFrame(rows)


def summarize_winloss(details: pd.DataFrame, window_scores: pd.DataFrame) -> pd.DataFrame:
    rows = []
    group_specs = [
        ("overall", ["method", "method_display", "method_family"]),
        ("by_scene", ["method", "method_display", "method_family", "scene_type"]),
    ]
    for aggregation, group_cols in group_specs:
        for key, detail_group in details.groupby(group_cols, dropna=False, sort=False):
            if not isinstance(key, tuple):
                key = (key,)
            selector = pd.Series(True, index=window_scores.index)
            for col, value in zip(group_cols, key):
                selector &= window_scores[col].eq(value)
            ws = window_scores[selector]
            counts = detail_group["status"].value_counts()
            metric_wins = int(counts.get("win", 0))
            metric_ties = int(counts.get("tie", 0))
            metric_losses = int(counts.get("loss", 0))
            window_counts = ws["window_status"].value_counts()
            window_wins = int(window_counts.get("win", 0))
            window_ties = int(window_counts.get("tie", 0))
            window_losses = int(window_counts.get("loss", 0))
            scores = pd.to_numeric(ws["window_score"], errors="coerce").dropna().to_numpy()
            ci_low, ci_high = bootstrap_mean_ci(scores)
            row = {
                "aggregation": aggregation,
                "method": key[0],
                "method_display": key[1],
                "method_family": key[2],
                "scene_type": "all" if aggregation == "overall" else key[3],
                "n_windows": int(len(ws)),
                "n_metric_pairs": int(len(detail_group)),
                "metric_wins": metric_wins,
                "metric_ties": metric_ties,
                "metric_losses": metric_losses,
                "metric_win_rate_excl_ties": safe_div(metric_wins, metric_wins + metric_losses),
                "window_wins": window_wins,
                "window_ties": window_ties,
                "window_losses": window_losses,
                "mean_window_score": float(np.mean(scores)) if len(scores) else np.nan,
                "bootstrap_mean_window_score_ci_low": ci_low,
                "bootstrap_mean_window_score_ci_high": ci_high,
                "window_sign_test_p_two_sided": exact_sign_test_p(window_wins, window_losses),
                "test_note": "Exact two-sided sign test on per-window score signs; ties ignored.",
            }
            rows.append(row)
    summary = pd.DataFrame(rows)
    summary["sort_agg"] = summary["aggregation"].map({"overall": 0, "by_scene": 1}).fillna(9).astype(int)
    summary["sort_scene"] = summary["scene_type"].map(SCENE_ORDER).fillna(-1).astype(int)
    summary["sort_method"] = summary["method"].map(METHOD_ORDER).fillna(50).astype(int)
    summary = summary.sort_values(["sort_agg", "sort_method", "sort_scene", "method"]).drop(
        columns=["sort_agg", "sort_scene", "sort_method"]
    )
    return summary.reset_index(drop=True)


def safe_div(num: int, den: int) -> float:
    return float(num / den) if den else np.nan


def exact_sign_test_p(wins: int, losses: int) -> float:
    n = wins + losses
    if n == 0:
        return np.nan
    observed = min(wins, losses)
    tail = sum(math.comb(n, k) for k in range(observed + 1)) / (2**n)
    return min(1.0, 2.0 * tail)


def bootstrap_mean_ci(values: np.ndarray, iterations: int = 10000, seed: int = 20260512) -> tuple[float, float]:
    clean = np.asarray(values, dtype=float)
    clean = clean[np.isfinite(clean)]
    if len(clean) == 0:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    draws = rng.choice(clean, size=(iterations, len(clean)), replace=True)
    means = draws.mean(axis=1)
    return (float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)))


def write_markdown_tables(scene_stats: pd.DataFrame, winloss_summary: pd.DataFrame) -> None:
    scene_md = compact_scene_markdown(scene_stats)
    (OUT_DIR / "multiwindow_scene_stats.md").write_text(scene_md, encoding="utf-8")
    winloss_md = compact_winloss_markdown(winloss_summary)
    (OUT_DIR / "multiwindow_winloss.md").write_text(winloss_md, encoding="utf-8")


def compact_scene_markdown(scene_stats: pd.DataFrame) -> str:
    rows = []
    for _, row in scene_stats.iterrows():
        rows.append(
            {
                "scene_type": row["scene_type"],
                "method": row["method_display"],
                "family": row["method_family"],
                "n_windows": row["n_windows"],
                "features": fmt_mean_std(row, "features_mean"),
                "grid_cov": fmt_mean_std(row, "grid_cov_median"),
                "track_age": fmt_mean_std(row, "track_age_median"),
                "dropout_ratio": fmt_mean_std(row, "dropout_ratio_median"),
                "f_inlier": fmt_mean_std(row, "f_inlier_median"),
                "epi_error": fmt_mean_std(row, "epi_error_median"),
                "runtime_ms": fmt_mean_std(row, "runtime_ms_median"),
            }
        )
    table = df_to_md(pd.DataFrame(rows))
    return "\n".join(
        [
            "# Multi-window scene statistics",
            "",
            "Values are mean +/- sample std across available summary rows in each scene/method group.",
            "A blank std means only one window-level row was available.",
            "",
            table,
            "",
        ]
    )


def compact_winloss_markdown(winloss_summary: pd.DataFrame) -> str:
    if winloss_summary.empty:
        body = "No paired rows with KLT + adaptive CLAHE were available."
    else:
        view = winloss_summary.copy()
        view["metric_W/T/L"] = view.apply(
            lambda r: f"{int(r['metric_wins'])}/{int(r['metric_ties'])}/{int(r['metric_losses'])}",
            axis=1,
        )
        view["window_W/T/L"] = view.apply(
            lambda r: f"{int(r['window_wins'])}/{int(r['window_ties'])}/{int(r['window_losses'])}",
            axis=1,
        )
        view["mean_window_score_95ci"] = view.apply(
            lambda r: (
                f"{fmt_float(r['mean_window_score'])} "
                f"[{fmt_float(r['bootstrap_mean_window_score_ci_low'])}, "
                f"{fmt_float(r['bootstrap_mean_window_score_ci_high'])}]"
            ),
            axis=1,
        )
        view["sign_p"] = view["window_sign_test_p_two_sided"].map(fmt_float)
        columns = [
            "aggregation",
            "scene_type",
            "method_display",
            "method_family",
            "n_windows",
            "metric_W/T/L",
            "window_W/T/L",
            "mean_window_score_95ci",
            "sign_p",
        ]
        body = df_to_md(view[columns])
    return "\n".join(
        [
            "# Multi-window win/tie/loss vs KLT + adaptive CLAHE",
            "",
            "Only rows with a same-source, same-dataset, same-window KLT + adaptive CLAHE control are included.",
            "Metric ties use practical epsilons; the sign test is exploratory and uses per-window score signs.",
            "",
            body,
            "",
        ]
    )


def fmt_mean_std(row: pd.Series, metric: str) -> str:
    mean = row.get(f"{metric}_mean", np.nan)
    std = row.get(f"{metric}_std", np.nan)
    if pd.isna(mean):
        return ""
    if pd.isna(std):
        return fmt_float(mean)
    return f"{fmt_float(mean)} +/- {fmt_float(std)}"


def fmt_float(value: object) -> str:
    try:
        val = float(value)
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(val):
        return ""
    if abs(val) >= 100:
        return f"{val:.1f}"
    if abs(val) >= 10:
        return f"{val:.2f}"
    return f"{val:.3f}"


def df_to_md(df: pd.DataFrame) -> str:
    if df.empty:
        return ""
    columns = list(df.columns)
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join(["---"] * len(columns)) + " |",
    ]
    for _, row in df.iterrows():
        values = [escape_md(row.get(col, "")) for col in columns]
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


def escape_md(value: object) -> str:
    if pd.isna(value):
        return ""
    if isinstance(value, (float, np.floating)):
        return fmt_float(value)
    return str(value).replace("|", "\\|")


def write_report(
    records: pd.DataFrame,
    scene_stats: pd.DataFrame,
    winloss_summary: pd.DataFrame,
    missing: Iterable[str],
) -> None:
    records_for_counts = records.copy()
    records_for_counts["window_key"] = records_for_counts["source_table"].astype(str).str.cat(
        [records_for_counts["dataset"].astype(str), records_for_counts["window"].astype(str)], sep=":"
    )
    source_counts = (
        records.groupby("source_table")
        .agg(rows=("method", "size"), datasets=("dataset", "nunique"))
        .reset_index()
        .sort_values("source_table")
    )
    scene_counts = (
        records_for_counts.groupby("scene_type")
        .agg(rows=("method", "size"), windows=("window_key", "nunique"), methods=("method", "nunique"))
        .reset_index()
    )
    overall = winloss_summary[winloss_summary["aggregation"] == "overall"].copy()
    if not overall.empty:
        overall["metric_W/T/L"] = overall.apply(
            lambda r: f"{int(r['metric_wins'])}/{int(r['metric_ties'])}/{int(r['metric_losses'])}", axis=1
        )
        overall["window_W/T/L"] = overall.apply(
            lambda r: f"{int(r['window_wins'])}/{int(r['window_ties'])}/{int(r['window_losses'])}", axis=1
        )
        overall["mean_window_score_95ci"] = overall.apply(
            lambda r: (
                f"{fmt_float(r['mean_window_score'])} "
                f"[{fmt_float(r['bootstrap_mean_window_score_ci_low'])}, "
                f"{fmt_float(r['bootstrap_mean_window_score_ci_high'])}]"
            ),
            axis=1,
        )
        overall["sign_p"] = overall["window_sign_test_p_two_sided"].map(fmt_float)
        overall_view = overall[
            [
                "method_display",
                "method_family",
                "n_windows",
                "metric_W/T/L",
                "window_W/T/L",
                "mean_window_score_95ci",
                "sign_p",
            ]
        ]
    else:
        overall_view = pd.DataFrame()

    lines = [
        "# Multi-window statistics report",
        "",
        "This report reuses existing CSV summaries only; no source code, bags, or new data were modified or downloaded.",
        "The goal is to avoid relying on a single window by aggregating available short-window, long-window, and churn-gated summaries.",
        "",
        "## Inputs",
        "",
        df_to_md(source_counts),
        "",
    ]
    missing = list(missing)
    if missing:
        lines += ["Missing optional inputs:", "", *[f"- {item}" for item in missing], ""]
    lines += [
        "## Scene coverage",
        "",
        "Scene labels are assigned from dataset/source names. AFRL low-coverage/degraded windows are grouped under degraded; AQUALOC-H07 low-texture/churn windows are grouped under identity churn.",
        "",
        df_to_md(scene_counts),
        "",
        "## Descriptive statistics",
        "",
        "Full numeric mean/std columns are in `multiwindow_scene_stats.csv`; the Markdown companion is compact.",
        "",
        "## Paired win/tie/loss",
        "",
        "Paired comparisons use same-source, same-dataset, same-window rows against `klt_adaptive_clahe` only. `long_window_v2` contributes to scene statistics, but not to this adaptive-CLAHE win/loss table because its control is `klt`, not `klt_adaptive_clahe`.",
        "",
        "Core metrics and practical tie epsilons:",
        "",
        *[f"- `{m}`: {direction}, epsilon={eps:g}" for m, (direction, eps) in WINLOSS_METRICS.items()],
        "",
        "Overall paired summary:",
        "",
        df_to_md(overall_view),
        "",
        "## Statistical caution",
        "",
        "The bootstrap interval is over per-window scores, where score = (metric wins - metric losses) / valid metrics. The exact sign test is two-sided on per-window score signs with ties ignored. Because windows can overlap and metrics within a window are correlated, these p-values are exploratory robustness checks rather than confirmatory significance claims.",
        "",
        "## Generated files",
        "",
        "- `multiwindow_scene_stats.csv` / `multiwindow_scene_stats.md`",
        "- `multiwindow_winloss.csv` / `multiwindow_winloss.md`",
        "- `multiwindow_winloss_details.csv`",
        "- `multiwindow_window_scores.csv`",
        "- `multiwindow_input_records.csv`",
        "",
    ]
    (OUT_DIR / "multiwindow_stats_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records, missing = read_sources()
    scene_stats = build_scene_stats(records)
    details, window_scores, winloss_summary = build_winloss(records)

    records.to_csv(OUT_DIR / "multiwindow_input_records.csv", index=False)
    scene_stats.to_csv(OUT_DIR / "multiwindow_scene_stats.csv", index=False)
    winloss_summary.to_csv(OUT_DIR / "multiwindow_winloss.csv", index=False)
    details.to_csv(OUT_DIR / "multiwindow_winloss_details.csv", index=False)
    window_scores.to_csv(OUT_DIR / "multiwindow_window_scores.csv", index=False)
    write_markdown_tables(scene_stats, winloss_summary)
    write_report(records, scene_stats, winloss_summary, missing)
    print(f"Wrote multi-window stats to {OUT_DIR.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
