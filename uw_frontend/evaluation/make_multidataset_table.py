from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ResultSpec:
    dataset: str
    method: str
    csv_path: Path


def parse_spec(raw: str) -> ResultSpec:
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("spec must be dataset:method:path.csv")
    return ResultSpec(parts[0], parts[1], Path(parts[2]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Create compact multi-dataset frontend table.")
    parser.add_argument("--spec", action="append", type=parse_spec, required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    table = pd.DataFrame([_summarize(spec) for spec in args.spec])
    table = _add_relative_metrics(table)
    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_csv, index=False)
    out_md = Path(args.output_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(_to_markdown(table) + "\n", encoding="utf-8")
    print(table.to_string(index=False))
    print(f"wrote {out_csv}")
    print(f"wrote {out_md}")
    return 0


def _summarize(spec: ResultSpec) -> dict:
    df = pd.read_csv(spec.csv_path)
    return {
        "dataset": spec.dataset,
        "method": spec.method,
        "frames": int(len(df)),
        "features_mean": _mean(df, "num_features"),
        "grid_cov_median": _median(df, "grid_coverage"),
        "track_age_median": _median(df, "median_track_age"),
        "long_track_ratio_mean": _mean(df, "long_track_ratio"),
        "dropout_mean": _mean(df, "dropped_features"),
        "dropout_ratio_median": _median(df, "dropout_ratio"),
        "f_inlier_median": _median(df, "fundamental_inlier_ratio"),
        "h_inlier_median": _median(df, "homography_inlier_ratio"),
        "epi_error_median": _median(df, "median_epipolar_error"),
        "quality_median": _median(df, "median_quality"),
        "low_texture_age_median": _median(df, "low_texture_track_age_median"),
        "visual_sigma_median": _median(df, "median_visual_sigma"),
        "runtime_ms_median": _median(df, "runtime_ms"),
        "candidate_bank_count_mean": _mean(df, "candidate_bank_count"),
        "candidate_bank_grid_gain_median": _median(df, "candidate_bank_grid_gain"),
        "stable_candidate_grid_cov_median": _median(df, "stable_candidate_grid_coverage"),
        "lk_recovery_mean": _mean(df, "lk_recovery_tracks"),
        "xfeat_recovery_mean": _mean(df, "xfeat_recovery_tracks"),
        "xfeat_init_mean": _mean(df, "xfeat_init_tracks"),
        "learned_memory_mean": _mean(df, "learned_memory_tracks"),
        "tracker_modes": _counts(df, "tracker_mode"),
    }


def _add_relative_metrics(table: pd.DataFrame) -> pd.DataFrame:
    table = table.copy()
    table["dropout_reduction_vs_klt_pct"] = float("nan")
    table["track_age_gain_vs_klt"] = float("nan")
    for dataset in table["dataset"].unique():
        subset = table[table["dataset"] == dataset]
        baseline = subset[subset["method"].str.lower().eq("klt")]
        if baseline.empty:
            continue
        base_dropout = float(baseline.iloc[0]["dropout_mean"])
        base_age = float(baseline.iloc[0]["track_age_median"])
        mask = table["dataset"] == dataset
        table.loc[mask, "dropout_reduction_vs_klt_pct"] = (
            (base_dropout - table.loc[mask, "dropout_mean"]) / max(base_dropout, 1e-6) * 100.0
        )
        table.loc[mask, "track_age_gain_vs_klt"] = table.loc[mask, "track_age_median"] - base_age
    return table


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
    rows = [[_format_value(value) for value in row] for row in df.itertuples(index=False, name=None)]
    widths = []
    for col_idx, header in enumerate(headers):
        values = [row[col_idx] for row in rows]
        widths.append(max([len(header)] + [len(value) for value in values]))
    header_line = "| " + " | ".join(header.ljust(widths[i]) for i, header in enumerate(headers)) + " |"
    sep_line = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    body = [
        "| " + " | ".join(value.ljust(widths[i]) for i, value in enumerate(row)) + " |"
        for row in rows
    ]
    return "\n".join([header_line, sep_line] + body)


def _format_value(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
