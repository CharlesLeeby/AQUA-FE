from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ResultSpec:
    dataset: str
    method: str
    csv_path: Path


SUMMARY_COLUMNS = {
    "frames": ("frame_index", "count"),
    "features_mean": ("num_features", "mean"),
    "grid_cov_median": ("grid_coverage", "median"),
    "candidate_bank_count_mean": ("candidate_bank_count", "mean"),
    "candidate_bank_grid_gain_median": ("candidate_bank_grid_gain", "median"),
    "stable_candidate_grid_cov_median": ("stable_candidate_grid_coverage", "median"),
    "track_age_median": ("median_track_age", "median"),
    "long_track_ratio_mean": ("long_track_ratio", "mean"),
    "dropout_mean": ("dropped_features", "mean"),
    "dropout_ratio_median": ("dropout_ratio", "median"),
    "f_inlier_median": ("fundamental_inlier_ratio", "median"),
    "h_inlier_median": ("homography_inlier_ratio", "median"),
    "epi_error_median": ("median_epipolar_error", "median"),
    "homography_error_median": ("median_homography_error", "median"),
    "quality_median": ("median_quality", "median"),
    "visual_sigma_median": ("median_visual_sigma", "median"),
    "runtime_ms_median": ("runtime_ms", "median"),
    "lk_recovery_mean": ("lk_recovery_tracks", "mean"),
    "xfeat_recovery_mean": ("xfeat_recovery_tracks", "mean"),
    "xfeat_init_mean": ("xfeat_init_tracks", "mean"),
}

TABLE_COLUMNS = [
    "dataset",
    "method",
    "frames",
    "features_mean",
    "grid_cov_median",
    "candidate_bank_count_mean",
    "candidate_bank_grid_gain_median",
    "stable_candidate_grid_cov_median",
    "track_age_median",
    "long_track_ratio_mean",
    "dropout_mean",
    "dropout_ratio_median",
    "f_inlier_median",
    "h_inlier_median",
    "epi_error_median",
    "runtime_ms_median",
    "tracker_modes",
]


def parse_spec(raw: str) -> ResultSpec:
    parts = raw.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("spec must be dataset:method:path.csv")
    return ResultSpec(parts[0], parts[1], Path(parts[2]))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build the paper-facing compact frontend report with separate "
            "stable-track, backend-geometry, and optional coverage-ablation outputs."
        )
    )
    parser.add_argument("--baseline-spec", action="append", type=parse_spec, required=True)
    parser.add_argument("--full-spec", action="append", type=parse_spec, required=True)
    parser.add_argument("--backend-spec", action="append", type=parse_spec, required=True)
    parser.add_argument("--coverage-spec", action="append", type=parse_spec, default=[])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--full-method", default="full_default")
    parser.add_argument("--backend-method", default="backend_pool")
    parser.add_argument("--coverage-method", default="coverage_ablation")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = args.baseline_spec + args.full_spec + args.backend_spec + args.coverage_spec
    table = pd.DataFrame([_summarize(spec) for spec in specs])
    table.to_csv(output_dir / "final_report_table.csv", index=False)
    (output_dir / "final_report_table.md").write_text(
        _to_markdown(table[TABLE_COLUMNS]) + "\n",
        encoding="utf-8",
    )

    winloss = _make_winloss(
        table,
        full_method=args.full_method,
        backend_method=args.backend_method,
        coverage_method=args.coverage_method,
    )
    winloss.to_csv(output_dir / "final_report_winloss.csv", index=False)
    summary = _summarize_winloss(winloss)
    summary.to_csv(output_dir / "final_report_winloss_summary.csv", index=False)
    nonwin = winloss[winloss["status"] != "win"]
    report = (
        "# Final Compact Frontend Report\n\n"
        "Baselines are selected per metric and dataset from KLT, ORB, XFeat, "
        "SuperPoint+LightGlue, and LoFTR. The stable-track frontend is judged "
        "on continuity; the backend output is judged on geometric consistency. "
        "Coverage ablation is optional and should not be used as the default claim.\n\n"
        + summary.to_string(index=False)
        + "\n\n## Non-Win Cases\n\n"
        + (nonwin.to_string(index=False) if len(nonwin) else "All compared metrics win.")
        + "\n"
    )
    (output_dir / "final_report_winloss.md").write_text(report, encoding="utf-8")

    print(summary.to_string(index=False))
    print(f"wrote {output_dir}")
    return 0


def _summarize(spec: ResultSpec) -> dict:
    df = pd.read_csv(spec.csv_path)
    row = {
        "dataset": spec.dataset,
        "method": spec.method,
        "csv": str(spec.csv_path),
    }
    for out_name, (col, agg) in SUMMARY_COLUMNS.items():
        row[out_name] = _aggregate(df, col, agg)
    if "tracker_mode" in df:
        row["tracker_modes"] = ";".join(
            f"{key}:{value}" for key, value in df["tracker_mode"].value_counts().items()
        )
    else:
        row["tracker_modes"] = ""
    return row


def _aggregate(df: pd.DataFrame, col: str, agg: str) -> float | int:
    if col not in df:
        return float("nan")
    series = df[col]
    if agg == "count":
        return int(series.count())
    if agg == "mean":
        return float(series.mean())
    if agg == "median":
        return float(series.median())
    raise ValueError(agg)


def _make_winloss(
    table: pd.DataFrame,
    full_method: str,
    backend_method: str,
    coverage_method: str,
) -> pd.DataFrame:
    metric_groups = {
        "full_continuity_core": (
            full_method,
            {
                "dropout_mean": "lower",
                "dropout_ratio_median": "lower",
                "track_age_median": "higher",
                "long_track_ratio_mean": "higher",
            },
        ),
        "backend_geometry_core": (
            backend_method,
            {
                "epi_error_median": "lower",
                "f_inlier_median": "higher",
                "h_inlier_median": "higher",
                "track_age_median": "higher",
                "long_track_ratio_mean": "higher",
            },
        ),
        "coverage_ablation_secondary": (
            coverage_method,
            {
                "grid_cov_median": "higher",
                "features_mean": "higher",
            },
        ),
    }
    baseline_methods = {"klt", "orb", "xfeat", "superpoint_lightglue", "loftr"}
    rows = []
    for group, (proposed_method, metrics) in metric_groups.items():
        for dataset in sorted(table["dataset"].unique()):
            proposed = table[(table["dataset"] == dataset) & (table["method"] == proposed_method)]
            baselines = table[
                (table["dataset"] == dataset) & (table["method"].isin(baseline_methods))
            ]
            if proposed.empty or baselines.empty:
                continue
            for metric, direction in metrics.items():
                proposed_value = float(proposed.iloc[0][metric])
                valid = baselines[["method", metric]].dropna()
                if valid.empty or math.isnan(proposed_value):
                    continue
                baseline_index = (
                    valid[metric].astype(float).idxmax()
                    if direction == "higher"
                    else valid[metric].astype(float).idxmin()
                )
                baseline_value = float(valid.loc[baseline_index, metric])
                status, delta = _compare(proposed_value, baseline_value, direction)
                rows.append(
                    {
                        "metric_group": group,
                        "dataset": dataset,
                        "metric": metric,
                        "direction": direction,
                        "proposed": proposed_value,
                        "best_baseline": baseline_value,
                        "best_baseline_method": valid.loc[baseline_index, "method"],
                        "status": status,
                        "delta": delta,
                    }
                )
    return pd.DataFrame(rows)


def _compare(proposed: float, baseline: float, direction: str) -> tuple[str, float]:
    if direction == "higher":
        delta = proposed - baseline
        if proposed > baseline + 1e-9:
            return "win", delta
        if abs(delta) <= 1e-9:
            return "tie", delta
        return "loss", delta
    delta = baseline - proposed
    if proposed < baseline - 1e-9:
        return "win", delta
    if abs(proposed - baseline) <= 1e-9:
        return "tie", delta
    return "loss", delta


def _summarize_winloss(winloss: pd.DataFrame) -> pd.DataFrame:
    if winloss.empty:
        return pd.DataFrame(columns=["metric_group", "metric", "loss", "tie", "win"])
    summary = (
        winloss.groupby(["metric_group", "metric", "status"])
        .size()
        .unstack(fill_value=0)
        .reset_index()
    )
    for col in ["loss", "tie", "win"]:
        if col not in summary:
            summary[col] = 0
    return summary[["metric_group", "metric", "loss", "tie", "win"]]


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
