#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


METHOD_SUFFIXES = [
    "klt_adaptive_clahe",
    "normal_safe_sp_lg",
    "loftr_extreme_sp_lg",
    "full_sp_lg_loftr",
    "full_sp_lg_loftr_sparse_probe",
    "gated_sp_lg_loftr",
    "full_xfeat_loftr",
    "superpoint_lightglue",
    "xfeat",
    "loftr",
    "orb",
    "klt",
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    rows = []
    for csv_path in sorted(Path(args.input_dir).glob("*.csv")):
        if csv_path.name.endswith("_summary.csv"):
            continue
        spec = _parse_name(csv_path)
        if spec is None:
            continue
        dataset, start, end, method = spec
        df = pd.read_csv(csv_path)
        rows.append(
            {
                "dataset": dataset,
                "start": start,
                "end": end,
                "method": method,
                "frames": len(df),
                "features_mean": _mean(df, "num_features"),
                "grid_cov_median": _median(df, "grid_coverage"),
                "track_age_median": _median(df, "median_track_age"),
                "mean_track_age": _mean(df, "mean_track_age"),
                "long_track_ratio": _mean(df, "long_track_ratio"),
                "dropout_mean": _mean(df, "dropped_features"),
                "dropout_ratio_median": _median(df, "dropout_ratio"),
                "f_inlier_median": _median(df, "fundamental_inlier_ratio"),
                "h_inlier_median": _median(df, "homography_inlier_ratio"),
                "epi_error_median": _median(df, "median_epipolar_error"),
                "homography_error_median": _median(df, "median_homography_error"),
                "quality_median": _median(df, "median_quality"),
                "low_texture_age_median": _median(df, "low_texture_track_age_median"),
                "runtime_ms_median": _median(df, "runtime_ms"),
                "sp_lg_init_mean": _mean(df, "superpoint_lightglue_init_tracks"),
                "sp_lg_confirmed_mean": _mean(df, "superpoint_lightglue_confirmed_tracks"),
                "xfeat_init_mean": _mean(df, "xfeat_init_tracks"),
                "xfeat_confirmed_mean": _mean(df, "xfeat_confirmed_tracks"),
                "loftr_init_mean": _mean(df, "loftr_init_tracks"),
                "tracker_modes": _counts(df, "tracker_mode"),
                "semidense_events": _counts(df, "semidense_acceptance"),
                "csv": str(csv_path),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        raise SystemExit("no matrix CSV files found")
    table = _add_vs_adaptive(table)
    table = table.sort_values(["dataset", "method"]).reset_index(drop=True)

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_csv, index=False)
    out_md = Path(args.output_md)
    out_md.write_text(_to_markdown(_compact_columns(table)) + "\n", encoding="utf-8")
    print(_compact_columns(table).to_string(index=False))
    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    return 0


def _parse_name(path: Path) -> tuple[str, int, int, str] | None:
    stem = path.stem
    for suffix in METHOD_SUFFIXES:
        token = f"_{suffix}"
        if stem.endswith(token):
            prefix = stem[: -len(token)]
            parts = prefix.rsplit("_", 2)
            if len(parts) != 3:
                return None
            dataset, start, end = parts
            return dataset, int(start), int(end), suffix
    return None


def _add_vs_adaptive(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    for col in [
        "features_mean",
        "grid_cov_median",
        "track_age_median",
        "long_track_ratio",
        "dropout_mean",
        "dropout_ratio_median",
        "f_inlier_median",
        "h_inlier_median",
        "epi_error_median",
    ]:
        table[f"delta_{col}_vs_klt_adaptive"] = float("nan")
    table["win_score_vs_klt_adaptive"] = float("nan")
    for dataset in table["dataset"].unique():
        subset = table[table["dataset"] == dataset]
        baseline = subset[subset["method"].eq("klt_adaptive_clahe")]
        if baseline.empty:
            continue
        base = baseline.iloc[0]
        mask = table["dataset"].eq(dataset)
        for col in [
            "features_mean",
            "grid_cov_median",
            "track_age_median",
            "long_track_ratio",
            "dropout_mean",
            "dropout_ratio_median",
            "f_inlier_median",
            "h_inlier_median",
            "epi_error_median",
        ]:
            table.loc[mask, f"delta_{col}_vs_klt_adaptive"] = table.loc[mask, col] - float(base[col])
        for idx in table[mask].index:
            row = table.loc[idx]
            wins = 0
            total = 0
            for col in ["grid_cov_median", "track_age_median", "long_track_ratio", "f_inlier_median", "h_inlier_median"]:
                total += 1
                wins += int(float(row[col]) >= float(base[col]))
            for col in ["dropout_mean", "dropout_ratio_median", "epi_error_median"]:
                total += 1
                wins += int(float(row[col]) <= float(base[col]))
            table.loc[idx, "win_score_vs_klt_adaptive"] = wins / max(1, total)
    return table


def _compact_columns(table: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "dataset",
        "method",
        "frames",
        "features_mean",
        "grid_cov_median",
        "track_age_median",
        "long_track_ratio",
        "dropout_mean",
        "dropout_ratio_median",
        "f_inlier_median",
        "h_inlier_median",
        "epi_error_median",
        "sp_lg_confirmed_mean",
        "xfeat_confirmed_mean",
        "loftr_init_mean",
        "win_score_vs_klt_adaptive",
        "runtime_ms_median",
        "semidense_events",
    ]
    return table[cols].copy()


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
    widths = [
        max([len(headers[col_idx])] + [len(row[col_idx]) for row in rows])
        for col_idx in range(len(headers))
    ]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
