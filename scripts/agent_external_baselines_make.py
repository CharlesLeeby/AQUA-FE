#!/usr/bin/env python3
"""Build the external/standalone baseline table from existing CSV summaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_external_baselines"

LONG_TABLE = ROOT / "logs" / "opt_eval" / "long_window_v2" / "long_window_all_baselines_table.csv"
BEST_COMPARISON = (
    ROOT / "logs" / "agent_paper_figures" / "long_window_external_best_comparison.csv"
)
TEXTURE_MATRIX = ROOT / "logs" / "paper_texture_matrix" / "texture_matrix_summary.csv"


@dataclass(frozen=True)
class MethodMeta:
    display: str
    group: str
    role: str
    note: str


METHOD_ORDER = [
    "klt",
    "orb",
    "xfeat",
    "superpoint_lightglue",
    "loftr",
    "continuity_optimized",
    "backend_strict",
]

METHOD_META = {
    "klt": MethodMeta(
        "GFTT+KLT / original frontend",
        "standalone baseline",
        "original classical frontend",
        "Standalone original frontend; not the adaptive-CLAHE internal control.",
    ),
    "orb": MethodMeta(
        "ORB",
        "standalone baseline",
        "external classical baseline",
        "External classical detector/descriptor baseline.",
    ),
    "xfeat": MethodMeta(
        "XFeat",
        "standalone baseline",
        "external learned baseline",
        "Standalone learned matcher; pairwise matches do not preserve long track IDs.",
    ),
    "superpoint_lightglue": MethodMeta(
        "SuperPoint+LightGlue",
        "standalone baseline",
        "external learned baseline",
        "Standalone learned pairwise matcher baseline.",
    ),
    "loftr": MethodMeta(
        "LoFTR",
        "standalone baseline",
        "external learned baseline",
        "Standalone dense pairwise matcher baseline.",
    ),
    "continuity_optimized": MethodMeta(
        "Continuity-optimized output",
        "proposed reference",
        "proposed frontend output",
        "Reference row for continuity metrics: track age and dropout.",
    ),
    "backend_strict": MethodMeta(
        "Backend-strict measurement",
        "proposed reference",
        "proposed geometry output",
        "Reference row for backend-facing geometry metrics.",
    ),
}

DATASET_ORDER = [
    "AQUALOC-H07",
    "AQUALOC-H06",
    "AQUALOC-A06",
    "AFRL-FL",
    "AFRL-FR",
]

WINDOW_LABELS = {
    "AQUALOC-H07": "1660-1950",
    "AQUALOC-H06": "2280-2490",
    "AQUALOC-A06": "2210-2460",
    "AFRL-FL": "80-319",
    "AFRL-FR": "5-410",
}

AGG_METRICS = [
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

MD_COLUMNS = [
    ("method_display", "Method"),
    ("method_group", "Group"),
    ("windows", "Windows"),
    ("features_mean_wavg", "Features"),
    ("grid_cov_median_wavg", "Grid cov."),
    ("track_age_median_wavg", "Track age"),
    ("dropout_ratio_median_wavg", "Dropout ratio"),
    ("dropout_mean_wavg", "Dropout mean"),
    ("epi_error_median_wavg", "Epi. residual"),
    ("f_inlier_median_wavg", "F inlier"),
    ("h_inlier_median_wavg", "H inlier"),
    ("runtime_ms_median_wavg", "Runtime ms"),
]

METRIC_LABELS = {
    "grid_cov_median": "grid coverage",
    "track_age_median": "track age",
    "dropout_ratio_median": "dropout ratio",
    "dropout_mean": "dropout mean",
    "epi_error_median": "epipolar residual",
    "f_inlier_median": "F inlier ratio",
    "h_inlier_median": "H inlier ratio",
}


def require_inputs() -> None:
    missing = [path for path in [LONG_TABLE, BEST_COMPARISON, TEXTURE_MATRIX] if not path.exists()]
    if missing:
        joined = "\n".join(f"- {path.relative_to(ROOT)}" for path in missing)
        raise FileNotFoundError(f"Missing required input CSV(s):\n{joined}")


def weighted_mean(series: pd.Series, weights: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce")
    valid = values.notna()
    if not valid.any():
        return np.nan
    valid_weights = pd.to_numeric(weights[valid], errors="coerce").fillna(1.0)
    return float(np.average(values[valid], weights=valid_weights))


def fmt_num(value: object, digits: int = 3) -> str:
    if pd.isna(value):
        return ""
    value = float(value)
    if abs(value) >= 100:
        return f"{value:.1f}"
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.{digits}f}"


def markdown_table(rows: list[dict[str, object]], columns: list[tuple[str, str]]) -> str:
    header = [label for _, label in columns]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * len(header)) + " |",
    ]
    for row in rows:
        cells = [str(row.get(key, "")) for key, _ in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def method_sort_key(method: str) -> int:
    try:
        return METHOD_ORDER.index(method)
    except ValueError:
        return len(METHOD_ORDER)


def dataset_sort_key(dataset: str) -> int:
    try:
        return DATASET_ORDER.index(dataset)
    except ValueError:
        return len(DATASET_ORDER)


def build_aggregate_table(long_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    selected = long_df[long_df["method"].isin(METHOD_ORDER)].copy()

    for method, group in selected.groupby("method", sort=False):
        meta = METHOD_META[method]
        row: dict[str, object] = {
            "method": method,
            "method_display": meta.display,
            "method_group": meta.group,
            "method_role": meta.role,
            "windows": int(group["dataset"].nunique()),
            "frames_total": int(group["frames"].sum()),
            "source_table": str(LONG_TABLE.relative_to(ROOT)),
            "notes": meta.note,
        }
        for metric in AGG_METRICS:
            row[f"{metric}_wavg"] = weighted_mean(group[metric], group["frames"])
            row[f"{metric}_windows"] = int(pd.to_numeric(group[metric], errors="coerce").notna().sum())
        rows.append(row)

    out = pd.DataFrame(rows)
    out["_sort"] = out["method"].map(method_sort_key)
    return out.sort_values("_sort").drop(columns=["_sort"]).reset_index(drop=True)


def build_markdown_table(agg_df: pd.DataFrame) -> str:
    rows: list[dict[str, object]] = []
    for _, row in agg_df.iterrows():
        item = {
            "method_display": row["method_display"],
            "method_group": row["method_group"],
            "windows": f"{int(row['windows'])}",
            "features_mean_wavg": fmt_num(row["features_mean_wavg"], 1),
            "grid_cov_median_wavg": fmt_num(row["grid_cov_median_wavg"]),
            "track_age_median_wavg": fmt_num(row["track_age_median_wavg"], 2),
            "dropout_ratio_median_wavg": fmt_num(row["dropout_ratio_median_wavg"]),
            "dropout_mean_wavg": fmt_num(row["dropout_mean_wavg"], 1),
            "epi_error_median_wavg": fmt_num(row["epi_error_median_wavg"]),
            "f_inlier_median_wavg": fmt_num(row["f_inlier_median_wavg"]),
            "h_inlier_median_wavg": fmt_num(row["h_inlier_median_wavg"]),
            "runtime_ms_median_wavg": fmt_num(row["runtime_ms_median_wavg"], 1),
        }
        rows.append(item)

    note = (
        "Values are frame-weighted means of the five long-window per-window summaries. "
        "They are not recomputed from raw frame logs.\n\n"
    )
    return note + markdown_table(rows, MD_COLUMNS)


def build_win_summary(best_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (method, metric), group in best_df.groupby(["proposed_method", "metric"], sort=False):
        rows.append(
            {
                "proposed_method": method,
                "proposed_method_display": group["proposed_method_display"].iloc[0],
                "metric": metric,
                "metric_label": group["metric_label"].iloc[0],
                "wins": int((group["status_code"] == 1).sum()),
                "ties": int((group["status_code"] == 0).sum()),
                "losses": int((group["status_code"] == -1).sum()),
                "windows": int(group["dataset"].nunique()),
            }
        )
    out = pd.DataFrame(rows)
    out["_method_sort"] = out["proposed_method"].map(method_sort_key)
    return out.sort_values(["_method_sort", "metric"]).drop(columns=["_method_sort"])


def summarize_learned_shortcomings(agg_df: pd.DataFrame) -> list[str]:
    lookup = agg_df.set_index("method")
    lines: list[str] = []
    for method in ["xfeat", "superpoint_lightglue", "loftr"]:
        row = lookup.loc[method]
        lines.append(
            "- "
            f"{row['method_display']}: track age {fmt_num(row['track_age_median_wavg'], 2)}, "
            f"dropout mean {fmt_num(row['dropout_mean_wavg'], 1)}, "
            f"dropout ratio {fmt_num(row['dropout_ratio_median_wavg'])} "
            f"({int(row['dropout_ratio_median_windows'])}/5 windows with ratio available), "
            f"runtime {fmt_num(row['runtime_ms_median_wavg'], 1)} ms."
        )
    return lines


def summarize_reference_wins(win_df: pd.DataFrame) -> list[str]:
    lines: list[str] = []
    desired = {
        "continuity_optimized": ["track_age_median", "dropout_ratio_median", "dropout_mean"],
        "backend_strict": ["epi_error_median", "f_inlier_median", "h_inlier_median"],
    }
    for method, metrics in desired.items():
        for metric in metrics:
            match = win_df[(win_df["proposed_method"] == method) & (win_df["metric"] == metric)]
            if match.empty:
                continue
            row = match.iloc[0]
            label = METRIC_LABELS.get(metric, str(row["metric_label"]))
            tie_word = "tie" if int(row["ties"]) == 1 else "ties"
            loss_word = "loss" if int(row["losses"]) == 1 else "losses"
            lines.append(
                "- "
                f"{row['proposed_method_display']} vs best standalone baseline on {label}: "
                f"{row['wins']}/{row['windows']} wins, {row['ties']} {tie_word}, "
                f"{row['losses']} {loss_word}."
            )
    return lines


def build_report(
    agg_df: pd.DataFrame,
    win_df: pd.DataFrame,
    texture_df: pd.DataFrame,
) -> str:
    controls = sorted(texture_df.loc[texture_df["method"] == "klt_adaptive_clahe", "dataset"].unique())
    windows = ", ".join(f"{dataset} `{WINDOW_LABELS[dataset]}`" for dataset in DATASET_ORDER)
    control_text = ", ".join(controls) if controls else "not present"

    lines = [
        "# External Baseline Report",
        "",
        f"Generated on {date.today().isoformat()} from existing CSV summaries only.",
        "",
        "## Scope",
        "",
        "This report separates external/standalone baselines from internal ablations.",
        "",
        "- External/standalone baseline set: GFTT+KLT/original frontend, ORB, XFeat, SuperPoint+LightGlue, and LoFTR.",
        "- Proposed reference rows: continuity-optimized output for continuity metrics and backend-strict measurement for geometry metrics.",
        "- Excluded from the external baseline set: KLT + adaptive CLAHE. It is a strong internal control / ablation reference.",
        "",
        "## Sources",
        "",
        f"- `{LONG_TABLE.relative_to(ROOT)}`: long-window table used for the numeric baseline table.",
        f"- `{BEST_COMPARISON.relative_to(ROOT)}`: proposed-vs-best-standalone win/loss checks.",
        f"- `{TEXTURE_MATRIX.relative_to(ROOT)}`: confirms the adaptive-CLAHE control appears in the texture matrix, not as an external baseline.",
        "",
        "No data were downloaded, no source code was modified, and no experiments were rerun. The long-window table already covers all required standalone baselines across five windows: "
        + windows
        + ".",
        "",
        "## Output Table",
        "",
        "- `logs/agent_external_baselines/external_baseline_table.csv`",
        "- `logs/agent_external_baselines/external_baseline_table.md`",
        "",
        "The table reports frame-weighted means of per-window summary metrics. Missing metric values are skipped per metric; notably, dropout-ratio availability is 4/5 for SuperPoint+LightGlue and LoFTR because the H07 long-window source row lacks that ratio, while dropout mean is available for all five windows.",
        "",
        "## Main Reading",
        "",
        *summarize_reference_wins(win_df),
        "",
        "Grid coverage is not claimed as a uniform win: continuity-optimized output trades some coverage for track continuity on several long windows. Keep coverage claims local to the windows where the value improves or ties.",
        "",
        "## Learned Matcher Caveat",
        "",
        "The standalone learned matchers are strong pairwise correspondence methods, but the long-window evidence does not make them stable VIO frontends by themselves. They re-associate frame pairs effectively, yet persistent track identity is short and dropout remains high compared with a continuity-aware frontend.",
        "",
        *summarize_learned_shortcomings(agg_df),
        "",
        "Suggested paper wording: pairwise learned matching quality does not by itself imply a stable frontend; the measured gain comes from preserving KLT tracks, scheduling learned recovery, and selecting backend-facing measurements rather than replacing the frontend with a standalone matcher.",
        "",
        "## Internal-Control Boundary",
        "",
        f"`klt_adaptive_clahe` appears in texture-matrix datasets ({control_text}) and should stay in the internal ablation/control table. Do not label it as an external baseline in the paper.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    require_inputs()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    long_df = pd.read_csv(LONG_TABLE)
    long_df["_dataset_sort"] = long_df["dataset"].map(dataset_sort_key)
    long_df["_method_sort"] = long_df["method"].map(method_sort_key)
    long_df = long_df.sort_values(["_dataset_sort", "_method_sort"])

    missing_methods = sorted(set(METHOD_ORDER) - set(long_df["method"].unique()))
    if missing_methods:
        raise ValueError(f"Long-window table is missing method(s): {missing_methods}")

    best_df = pd.read_csv(BEST_COMPARISON)
    texture_df = pd.read_csv(TEXTURE_MATRIX)

    agg_df = build_aggregate_table(long_df)
    win_df = build_win_summary(best_df)

    csv_path = OUT_DIR / "external_baseline_table.csv"
    md_path = OUT_DIR / "external_baseline_table.md"
    report_path = OUT_DIR / "external_baseline_report.md"

    agg_df.to_csv(csv_path, index=False)
    md_path.write_text(build_markdown_table(agg_df), encoding="utf-8")
    report_path.write_text(build_report(agg_df, win_df, texture_df), encoding="utf-8")

    print(f"Wrote {csv_path.relative_to(ROOT)}")
    print(f"Wrote {md_path.relative_to(ROOT)}")
    print(f"Wrote {report_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
