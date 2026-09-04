from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


SUMMARY_COLUMNS = {
    "frames": ("frame_index", "count"),
    "features_mean": ("num_features", "mean"),
    "grid_coverage_median": ("grid_coverage", "median"),
    "track_age_median": ("median_track_age", "median"),
    "long_track_ratio_mean": ("long_track_ratio", "mean"),
    "dropout_mean": ("dropped_features", "mean"),
    "dropout_ratio_median": ("dropout_ratio", "median"),
    "fb_error_median": ("median_fb_error", "median"),
    "ncc_median": ("median_ncc", "median"),
    "quality_median": ("median_quality", "median"),
    "visual_sigma_median": ("median_visual_sigma", "median"),
    "low_texture_ratio_mean": ("low_texture_feature_ratio", "mean"),
    "low_texture_age_median": ("low_texture_track_age_median", "median"),
    "low_texture_quality_median": ("low_texture_quality_median", "median"),
    "underwater_score_median": ("underwater_score", "median"),
    "degradation_median": ("degradation_score", "median"),
    "illumination_nonuniformity_median": ("illumination_nonuniformity", "median"),
    "flat_region_ratio_median": ("flat_region_ratio", "median"),
    "backscatter_score_median": ("backscatter_score", "median"),
    "grid_texture_score_median": ("grid_texture_score", "median"),
    "tracker_recovered_mean": ("tracker_recovered_count", "mean"),
    "f_inlier_median": ("fundamental_inlier_ratio", "median"),
    "h_inlier_median": ("homography_inlier_ratio", "median"),
    "epi_error_median": ("median_epipolar_error", "median"),
    "homography_error_median": ("median_homography_error", "median"),
    "runtime_ms_median": ("runtime_ms", "median"),
    "klt_tracks_mean": ("klt_tracks", "mean"),
    "gftt_tracks_mean": ("gftt_tracks", "mean"),
    "orb_tracks_mean": ("orb_tracks", "mean"),
    "orb_match_tracks_mean": ("orb_match_tracks", "mean"),
    "orb_recovery_tracks_mean": ("orb_recovery_tracks", "mean"),
    "lk_recovery_tracks_mean": ("lk_recovery_tracks", "mean"),
    "xfeat_tracks_mean": ("xfeat_tracks", "mean"),
    "xfeat_recovery_tracks_mean": ("xfeat_recovery_tracks", "mean"),
    "xfeat_init_tracks_mean": ("xfeat_init_tracks", "mean"),
    "xfeat_star_tracks_mean": ("xfeat_star_tracks", "mean"),
    "xfeat_star_recovery_tracks_mean": ("xfeat_star_recovery_tracks", "mean"),
    "xfeat_star_init_tracks_mean": ("xfeat_star_init_tracks", "mean"),
    "sp_lg_tracks_mean": ("superpoint_lightglue_tracks", "mean"),
    "sp_lg_recovery_tracks_mean": ("superpoint_lightglue_recovery_tracks", "mean"),
    "sp_lg_init_tracks_mean": ("superpoint_lightglue_init_tracks", "mean"),
    "loftr_tracks_mean": ("loftr_tracks", "mean"),
    "loftr_recovery_tracks_mean": ("loftr_recovery_tracks", "mean"),
    "loftr_init_tracks_mean": ("loftr_init_tracks", "mean"),
    "candidate_bank_count_mean": ("candidate_bank_count", "mean"),
    "candidate_bank_coverage_median": ("candidate_bank_coverage", "median"),
    "candidate_bank_grid_gain_median": ("candidate_bank_grid_gain", "median"),
    "stable_candidate_grid_coverage_median": ("stable_candidate_grid_coverage", "median"),
}


def summarize_csv(path: Path, method: str | None = None) -> dict:
    df = pd.read_csv(path)
    row = {"method": method or _guess_method(path), "csv": str(path)}
    for out_name, (col, agg) in SUMMARY_COLUMNS.items():
        if col not in df:
            row[out_name] = float("nan")
            continue
        series = df[col]
        if agg == "count":
            row[out_name] = int(series.count())
        elif agg == "mean":
            row[out_name] = float(series.mean())
        elif agg == "median":
            row[out_name] = float(series.median())
        else:
            raise ValueError(agg)
    if "scheduler_mode" in df:
        row["scheduler_modes"] = ";".join(f"{k}:{v}" for k, v in df["scheduler_mode"].value_counts().items())
    if "tracker_mode" in df:
        row["tracker_modes"] = ";".join(f"{k}:{v}" for k, v in df["tracker_mode"].value_counts().items())
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize frontend CSV files into paper-table style metrics.")
    parser.add_argument("csv", nargs="+", help="Frontend metric CSV files.")
    parser.add_argument("--output-csv", default=None)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    rows = [summarize_csv(Path(item)) for item in args.csv]
    summary = pd.DataFrame(rows)
    print(summary.drop(columns=["csv"]).to_string(index=False))
    if args.output_csv:
        out_csv = Path(args.output_csv)
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(out_csv, index=False)
        print(f"wrote {out_csv}")
    if args.output_md:
        out_md = Path(args.output_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(_to_markdown(summary.drop(columns=["csv"])) + "\n", encoding="utf-8")
        print(f"wrote {out_md}")
    return 0


def _guess_method(path: Path) -> str:
    name = path.stem.lower()
    aliases = {
        "hybrid_sp_lg": "hybrid_superpoint_lightglue",
        "hybrid_splg": "hybrid_superpoint_lightglue",
        "sp_lg": "superpoint_lightglue",
        "splg": "superpoint_lightglue",
    }
    for alias, method in aliases.items():
        if alias in name:
            return method
    for method in ["superpoint_lightglue", "hybrid_superpoint_lightglue", "hybrid_xfeat_star", "hybrid_xfeat", "hybrid_loftr", "xfeat_star", "xfeat", "lightglue", "loftr", "hybrid", "klt", "orb"]:
        if method in name:
            return method
    return path.stem


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
