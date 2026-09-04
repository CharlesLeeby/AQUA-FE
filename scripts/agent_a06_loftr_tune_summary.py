#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


METRICS = [
    "features_mean",
    "grid_cov_median",
    "track_age_median",
    "long_track_ratio",
    "dropout_mean",
    "dropout_ratio_median",
    "f_inlier_median",
    "h_inlier_median",
    "epi_error_median",
    "runtime_ms_median",
    "loftr_init_mean",
    "sp_lg_confirmed_mean",
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
        window, method = spec
        df = pd.read_csv(csv_path)
        rows.append(
            {
                "window": window,
                "method": method,
                "frames": len(df),
                "features_mean": _mean(df, "num_features"),
                "grid_cov_median": _median(df, "grid_coverage"),
                "track_age_median": _median(df, "median_track_age"),
                "long_track_ratio": _mean(df, "long_track_ratio"),
                "dropout_mean": _mean(df, "dropped_features"),
                "dropout_ratio_median": _median(df, "dropout_ratio"),
                "f_inlier_median": _median(df, "fundamental_inlier_ratio"),
                "h_inlier_median": _median(df, "homography_inlier_ratio"),
                "epi_error_median": _median(df, "median_epipolar_error"),
                "homography_error_median": _median(df, "median_homography_error"),
                "runtime_ms_median": _median(df, "runtime_ms"),
                "loftr_init_mean": _mean(df, "loftr_init_tracks"),
                "sp_lg_confirmed_mean": _mean(df, "superpoint_lightglue_confirmed_tracks"),
                "semidense_events": _counts(df, "semidense_acceptance"),
                "csv": str(csv_path),
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        raise SystemExit("no tune CSV files found")
    table = _add_deltas(table)
    table = table.sort_values(["window", "method"]).reset_index(drop=True)

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_csv, index=False)
    compact = _compact(table)
    Path(args.output_md).write_text(_to_markdown(compact) + "\n", encoding="utf-8")
    print(compact.to_string(index=False))
    print(f"wrote {out_csv}")
    print(f"wrote {args.output_md}")
    return 0


def _parse_name(path: Path) -> tuple[str, str] | None:
    stem = path.stem
    prefix = "a06_"
    if not stem.startswith(prefix):
        return None
    rest = stem[len(prefix) :]
    for token in ("_2210_2460_", "_2210_2700_"):
        if token in rest:
            left, method = rest.split(token, 1)
            window = token.strip("_")
            return window, method
    return None


def _add_deltas(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    for ref_name, suffix in [
        ("klt_adaptive_clahe", "vs_klt"),
        ("full_sp_lg_loftr", "vs_full"),
    ]:
        for col in METRICS:
            table[f"delta_{col}_{suffix}"] = float("nan")
        for window in table["window"].unique():
            subset = table[table["window"].eq(window)]
            ref = subset[subset["method"].eq(ref_name)]
            if ref.empty:
                continue
            base = ref.iloc[0]
            mask = table["window"].eq(window)
            for col in METRICS:
                table.loc[mask, f"delta_{col}_{suffix}"] = table.loc[mask, col] - float(base[col])
    table["continuity_win_vs_klt"] = table.apply(_continuity_win_vs_klt, axis=1)
    table["residual_neutral_vs_full"] = table["delta_epi_error_median_vs_full"] <= 0.0005
    return table


def _continuity_win_vs_klt(row: pd.Series) -> bool:
    return bool(
        row.get("delta_grid_cov_median_vs_klt", 0.0) >= -1e-9
        and row.get("delta_track_age_median_vs_klt", 0.0) >= -1e-9
        and row.get("delta_dropout_mean_vs_klt", 0.0) <= 1e-9
    )


def _compact(table: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "window",
        "method",
        "frames",
        "grid_cov_median",
        "delta_grid_cov_median_vs_klt",
        "track_age_median",
        "delta_track_age_median_vs_klt",
        "dropout_mean",
        "delta_dropout_mean_vs_klt",
        "dropout_ratio_median",
        "delta_dropout_ratio_median_vs_klt",
        "epi_error_median",
        "delta_epi_error_median_vs_klt",
        "delta_epi_error_median_vs_full",
        "continuity_win_vs_klt",
        "residual_neutral_vs_full",
        "runtime_ms_median",
        "loftr_init_mean",
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
