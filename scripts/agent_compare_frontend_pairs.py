#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd


METRICS: tuple[tuple[str, str, str], ...] = (
    ("num_features", "mean", "features_mean"),
    ("grid_coverage", "median", "grid_median"),
    ("median_track_age", "median", "age_median"),
    ("long_track_ratio", "median", "long_track_median"),
    ("dropout_ratio", "mean", "dropout_ratio_mean"),
    ("fundamental_inlier_ratio", "median", "f_inlier_median"),
    ("homography_inlier_ratio", "median", "h_inlier_median"),
    ("median_epipolar_error", "median", "epipolar_median"),
    ("median_homography_error", "median", "homography_median"),
    ("runtime_ms", "median", "runtime_ms_median"),
)

SOURCE_COLUMNS: tuple[str, ...] = (
    "superpoint_lightglue_tracks",
    "superpoint_lightglue_init_tracks",
    "superpoint_lightglue_confirmed_tracks",
    "xfeat_tracks",
    "xfeat_init_tracks",
    "xfeat_confirmed_tracks",
    "xfeat_star_tracks",
    "xfeat_star_init_tracks",
    "xfeat_star_confirmed_tracks",
    "loftr_tracks",
    "loftr_init_tracks",
    "loftr_confirmed_tracks",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare frontend CSV pairs with consistent metrics and source counters."
    )
    parser.add_argument(
        "--pair",
        nargs=3,
        metavar=("LABEL", "BASE_CSV", "CAND_CSV"),
        action="append",
        required=True,
        help="Comparison label plus baseline and candidate CSV paths. Repeatable.",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    rows = []
    for label, base_path, cand_path in args.pair:
        rows.append(compare_pair(label, Path(base_path), Path(cand_path)))

    table = pd.DataFrame(rows)
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_csv, index=False)
    if args.output_md:
        Path(args.output_md).write_text(to_markdown(table) + "\n", encoding="utf-8")
    print(table.to_string(index=False))
    print(f"wrote {output_csv}")
    if args.output_md:
        print(f"wrote {args.output_md}")
    return 0


def compare_pair(label: str, base_path: Path, cand_path: Path) -> dict[str, Any]:
    base = pd.read_csv(base_path)
    cand = pd.read_csv(cand_path)
    row: dict[str, Any] = {
        "label": label,
        "base_csv": str(base_path),
        "candidate_csv": str(cand_path),
        "base_frames": int(len(base)),
        "candidate_frames": int(len(cand)),
    }
    for source_col, agg, out_name in METRICS:
        base_value = aggregate(base, source_col, agg)
        cand_value = aggregate(cand, source_col, agg)
        row[f"base_{out_name}"] = base_value
        row[f"candidate_{out_name}"] = cand_value
        row[f"delta_{out_name}"] = cand_value - base_value
    row.update(source_summary(cand))
    row["semidense_events"] = value_counts(cand, "semidense_acceptance")
    row["geometry_safe_events"] = value_counts(cand, "geometry_safe_acceptance", limit=6)
    row["decision_hint"] = decision_hint(row)
    return row


def aggregate(df: pd.DataFrame, col: str, agg: str) -> float:
    if col not in df:
        return float("nan")
    values = pd.to_numeric(df[col], errors="coerce")
    if agg == "mean":
        return float(values.mean())
    if agg == "median":
        return float(values.median())
    raise ValueError(f"unsupported aggregation: {agg}")


def source_summary(df: pd.DataFrame) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in SOURCE_COLUMNS:
        if col in df:
            values = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            row[f"{col}_max"] = float(values.max())
            row[f"{col}_mean"] = float(values.mean())
    row["loftr_accepted_tracks"] = parse_accepted_tracks(df, "loftr")
    row["accepted_loftr_frames"] = parse_accepted_frames(df, "loftr")
    return row


def parse_accepted_tracks(df: pd.DataFrame, source: str) -> int:
    if "semidense_acceptance" not in df:
        return 0
    total = 0
    pattern = re.compile(rf"accepted_{re.escape(source)}_(\d+)")
    for value in df["semidense_acceptance"].fillna("").astype(str):
        match = pattern.search(value)
        if match:
            total += int(match.group(1))
    return total


def parse_accepted_frames(df: pd.DataFrame, source: str) -> int:
    if "semidense_acceptance" not in df:
        return 0
    needle = f"accepted_{source}_"
    return int(df["semidense_acceptance"].fillna("").astype(str).str.contains(needle, regex=False).sum())


def value_counts(df: pd.DataFrame, col: str, limit: int = 8) -> str:
    if col not in df:
        return ""
    counts = df[col].fillna("nan").astype(str).value_counts().head(limit)
    return ";".join(f"{key}:{value}" for key, value in counts.items())


def decision_hint(row: dict[str, Any]) -> str:
    d_grid = float(row.get("delta_grid_median", float("nan")))
    d_age = float(row.get("delta_age_median", float("nan")))
    d_dropout = float(row.get("delta_dropout_ratio_mean", float("nan")))
    d_epi = float(row.get("delta_epipolar_median", float("nan")))
    if d_epi <= 0.005 and (d_grid > 0.0 or d_age > 0.0 or d_dropout < 0.0):
        return "candidate_positive"
    if d_epi <= 0.010 and d_grid >= -0.01 and d_dropout <= 0.01:
        return "near_tie_no_harm"
    return "needs_review"


def to_markdown(df: pd.DataFrame) -> str:
    compact_cols = [
        "label",
        "delta_grid_median",
        "delta_age_median",
        "delta_long_track_median",
        "delta_dropout_ratio_mean",
        "delta_epipolar_median",
        "delta_homography_median",
        "delta_runtime_ms_median",
        "loftr_accepted_tracks",
        "accepted_loftr_frames",
        "decision_hint",
    ]
    compact = df[[col for col in compact_cols if col in df.columns]].copy()
    headers = [str(col) for col in compact.columns]
    rows = [[fmt(value) for value in row] for row in compact.itertuples(index=False, name=None)]
    widths = [
        max([len(headers[idx])] + [len(row[idx]) for row in rows])
        for idx in range(len(headers))
    ]
    lines = [
        "| " + " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[idx] for idx in range(len(headers))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |"
        for row in rows
    )
    return "\n".join(lines)


def fmt(value: object) -> str:
    if isinstance(value, float):
        if value != value:
            return "nan"
        return f"{value:.4f}"
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
