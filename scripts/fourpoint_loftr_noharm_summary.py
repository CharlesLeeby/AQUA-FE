#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

import pandas as pd


ROWS = [
    (
        "h07_normal_0_50",
        "normal",
        "logs/paper_texture_matrix/aqualoc_h07_normal_0_50_klt_adaptive_clahe.csv",
        "logs/paper_texture_matrix/aqualoc_h07_normal_0_50_full_sp_lg_loftr.csv",
        "logs/fourpoint_loftr_noharm/h07_normal_0_50_tuned_quality.csv",
    ),
    (
        "h07_lowtex_1660_1710",
        "low texture",
        "logs/paper_texture_matrix/aqualoc_h07_lowtex_1660_1710_klt_adaptive_clahe.csv",
        "logs/paper_texture_matrix/aqualoc_h07_lowtex_1660_1710_full_sp_lg_loftr.csv",
        "logs/fourpoint_loftr_noharm/h07_lowtex_1660_1710_tuned_quality.csv",
    ),
    (
        "h06_lowcontrast_2280_2330",
        "low contrast",
        "logs/paper_texture_matrix/aqualoc_h06_lowcontrast_2280_2330_klt_adaptive_clahe.csv",
        "logs/paper_texture_matrix/aqualoc_h06_lowcontrast_2280_2330_full_sp_lg_loftr.csv",
        "logs/fourpoint_loftr_noharm/h06_lowcontrast_2280_2330_tuned_quality.csv",
    ),
    (
        "a06_planar_2210_2460",
        "planar low texture",
        "logs/agent_a06_loftr_tune/a06_planar_long_2210_2460_klt_adaptive_clahe.csv",
        "logs/agent_a06_loftr_tune/a06_planar_long_2210_2460_full_sp_lg_loftr.csv",
        "logs/agent_a06_loftr_tune/a06_planar_long_2210_2460_tuned_quality.csv",
    ),
    (
        "a06_planar_2210_2700",
        "planar low texture",
        "logs/agent_a06_loftr_tune/a06_planar_longer_2210_2700_klt_adaptive_clahe.csv",
        "logs/agent_a06_loftr_tune/a06_planar_longer_2210_2700_full_sp_lg_loftr.csv",
        "logs/agent_a06_loftr_tune/a06_planar_longer_2210_2700_tuned_quality.csv",
    ),
]


def main() -> int:
    out_dir = Path("logs/fourpoint_loftr_noharm")
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for window, scene, klt, full, tuned in ROWS:
        for method, path in [
            ("klt_adaptive", klt),
            ("current_full", full),
            ("tuned_quality", tuned),
        ]:
            csv_path = Path(path)
            if not csv_path.exists():
                records.append({"window": window, "scene": scene, "method": method, "missing": True, "csv": path})
                continue
            df = pd.read_csv(csv_path)
            records.append(
                {
                    "window": window,
                    "scene": scene,
                    "method": method,
                    "missing": False,
                    "frames": len(df),
                    "grid_cov_median": _median(df, "grid_coverage"),
                    "track_age_median": _median(df, "median_track_age"),
                    "long_track_ratio": _mean(df, "long_track_ratio"),
                    "dropout_mean": _mean(df, "dropped_features"),
                    "dropout_ratio_median": _median(df, "dropout_ratio"),
                    "f_inlier_median": _median(df, "fundamental_inlier_ratio"),
                    "h_inlier_median": _median(df, "homography_inlier_ratio"),
                    "epi_error_median": _median(df, "median_epipolar_error"),
                    "runtime_ms_median": _median(df, "runtime_ms"),
                    "loftr_init_mean": _mean(df, "loftr_init_tracks"),
                    "semidense_events": _counts(df, "semidense_acceptance"),
                    "csv": path,
                }
            )
    table = pd.DataFrame(records)
    table = _add_deltas(table)
    table.to_csv(out_dir / "loftr_noharm_summary.csv", index=False)
    compact = table[table["method"].eq("tuned_quality")].copy()
    compact = compact[
        [
            "window",
            "scene",
            "frames",
            "delta_grid_vs_klt",
            "delta_age_vs_klt",
            "delta_dropout_vs_klt",
            "delta_dropout_ratio_vs_klt",
            "delta_epi_vs_klt",
            "delta_epi_vs_full",
            "loftr_init_mean",
            "noharm_pass",
            "decision",
        ]
    ]
    (out_dir / "loftr_noharm_summary.md").write_text(_to_markdown(compact) + "\n", encoding="utf-8")
    (out_dir / "loftr_noharm_report.md").write_text(_report(compact), encoding="utf-8")
    print(compact.to_string(index=False))
    return 0


def _add_deltas(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    for col in ["grid_cov_median", "track_age_median", "dropout_mean", "dropout_ratio_median", "epi_error_median"]:
        table[f"delta_{col}_vs_klt"] = float("nan")
        table[f"delta_{col}_vs_full"] = float("nan")
    table["noharm_pass"] = False
    table["decision"] = ""
    for window in table["window"].dropna().unique():
        subset = table[table["window"].eq(window)]
        klt = subset[subset["method"].eq("klt_adaptive")]
        full = subset[subset["method"].eq("current_full")]
        if klt.empty:
            continue
        klt_row = klt.iloc[0]
        full_row = full.iloc[0] if not full.empty else None
        mask = table["window"].eq(window)
        for col in ["grid_cov_median", "track_age_median", "dropout_mean", "dropout_ratio_median", "epi_error_median"]:
            table.loc[mask, f"delta_{col}_vs_klt"] = table.loc[mask, col] - float(klt_row[col])
            if full_row is not None:
                table.loc[mask, f"delta_{col}_vs_full"] = table.loc[mask, col] - float(full_row[col])
        tuned_mask = mask & table["method"].eq("tuned_quality")
        if not tuned_mask.any():
            continue
        row = table[tuned_mask].iloc[0]
        noharm = (
            float(row["delta_epi_error_median_vs_klt"]) <= 0.005
            and float(row["delta_dropout_mean_vs_klt"]) <= 1.0
            and float(row["delta_grid_cov_median_vs_klt"]) >= -0.02
        )
        table.loc[tuned_mask, "noharm_pass"] = bool(noharm)
        if bool(noharm) and str(row["scene"]) == "planar low texture":
            decision = "positive planar candidate"
        elif bool(noharm):
            decision = "no-harm only"
        else:
            decision = "do not promote globally"
        table.loc[tuned_mask, "decision"] = decision
    rename = {
        "delta_grid_cov_median_vs_klt": "delta_grid_vs_klt",
        "delta_track_age_median_vs_klt": "delta_age_vs_klt",
        "delta_dropout_mean_vs_klt": "delta_dropout_vs_klt",
        "delta_dropout_ratio_median_vs_klt": "delta_dropout_ratio_vs_klt",
        "delta_epi_error_median_vs_klt": "delta_epi_vs_klt",
        "delta_epi_error_median_vs_full": "delta_epi_vs_full",
    }
    return table.rename(columns=rename)


def _mean(df: pd.DataFrame, col: str) -> float:
    return float(df[col].mean()) if col in df else float("nan")


def _median(df: pd.DataFrame, col: str) -> float:
    return float(df[col].median()) if col in df else float("nan")


def _counts(df: pd.DataFrame, col: str) -> str:
    if col not in df:
        return ""
    return ";".join(f"{key}:{value}" for key, value in df[col].value_counts().items())


def _to_markdown(df: pd.DataFrame) -> str:
    headers = [str(col) for col in df.columns]
    rows = [[_fmt(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = [max([len(headers[i])] + [len(row[i]) for row in rows]) for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    lines.extend("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |" for row in rows)
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.4f}"
    return str(value)


def _report(compact: pd.DataFrame) -> str:
    passed = int(compact["noharm_pass"].sum())
    total = int(len(compact))
    return (
        "# LoFTR No-Harm Check\n\n"
        "This check compares the A06 residual-neutral LoFTR quality gate against KLT + adaptive CLAHE on local AQUALOC windows. "
        "A pass requires near-neutral epipolar residual, no large dropout regression, and no large coverage regression.\n\n"
        f"Pass count: {passed}/{total} tuned-quality windows.\n\n"
        + _to_markdown(compact)
        + "\n\nDecision: keep the tuned LoFTR gate as a planar low-texture candidate. "
        "Do not promote it as a blanket global fallback unless more non-A06 windows pass without geometry/runtime regressions.\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
