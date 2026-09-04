#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import pandas as pd


METRICS: tuple[tuple[str, str, str, int], ...] = (
    ("num_features", "mean", "features_mean", 1),
    ("grid_coverage", "median", "grid_median", 1),
    ("median_track_age", "median", "age_median", 1),
    ("mean_track_age", "mean", "age_mean", 1),
    ("long_track_ratio", "median", "long_track_median", 1),
    ("dropout_ratio", "mean", "dropout_ratio_mean", -1),
    ("fundamental_inlier_ratio", "median", "f_inlier_median", 1),
    ("homography_inlier_ratio", "median", "h_inlier_median", 1),
    ("median_epipolar_error", "median", "epipolar_median", -1),
    ("median_homography_error", "median", "homography_median", -1),
    ("runtime_ms", "median", "runtime_ms_median", -1),
)

SOURCE_COLUMNS: tuple[str, ...] = (
    "superpoint_lightglue_init_tracks",
    "superpoint_lightglue_confirmed_tracks",
    "xfeat_init_tracks",
    "xfeat_confirmed_tracks",
    "xfeat_star_init_tracks",
    "xfeat_star_confirmed_tracks",
    "loftr_init_tracks",
    "loftr_confirmed_tracks",
    "learned_memory_tracks",
)

DIAGNOSTIC_COLUMNS: tuple[str, ...] = (
    "tracker_mode",
    "scheduler_mode",
    "geometry_mode",
    "adaptive_geometry_model",
    "semidense_acceptance",
    "geometry_safe_acceptance",
    "learned_mode_after_sparse_override",
    "learned_mode_sparse_homography_allowed",
    "learned_mode_sparse_homography_reason",
    "last_loftr_sparse_homography_check_allowed",
    "last_loftr_sparse_homography_check_reason",
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Supervise frontend candidate CSV pairs with metrics, source counters, and gate diagnostics."
    )
    parser.add_argument(
        "--pair",
        nargs=3,
        action="append",
        metavar=("LABEL", "BASE_CSV", "CAND_CSV"),
        required=True,
        help="Comparison label plus baseline/candidate CSV. Repeatable.",
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", default=None)
    args = parser.parse_args()

    rows = [compare_pair(label, Path(base), Path(cand)) for label, base, cand in args.pair]
    table = pd.DataFrame(rows)
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output_csv, index=False)
    if args.output_md:
        Path(args.output_md).write_text(to_markdown(table) + "\n", encoding="utf-8")
    print(to_markdown(table))
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
        "base_frames": len(base),
        "candidate_frames": len(cand),
    }
    score = 0
    available = 0
    for col, agg, out, direction in METRICS:
        base_value = aggregate(base, col, agg)
        cand_value = aggregate(cand, col, agg)
        delta = cand_value - base_value
        row[f"base_{out}"] = base_value
        row[f"candidate_{out}"] = cand_value
        row[f"delta_{out}"] = delta
        if pd.notna(delta) and out != "runtime_ms_median":
            available += 1
            score += sign_score(delta, direction)
    row["metric_vote_score"] = score
    row["metric_vote_total"] = available
    row.update(source_summary(cand))
    row.update(diagnostic_summary(cand))
    row["decision_hint"] = decision_hint(row)
    return row


def aggregate(df: pd.DataFrame, col: str, agg: str) -> float:
    if col not in df:
        return float("nan")
    values = pd.to_numeric(df[col], errors="coerce")
    if values.dropna().empty:
        return float("nan")
    if agg == "mean":
        return float(values.mean())
    if agg == "median":
        return float(values.median())
    raise ValueError(f"unknown aggregate {agg}")


def sign_score(delta: float, direction: int, eps: float = 1e-6) -> int:
    value = delta * direction
    if value > eps:
        return 1
    if value < -eps:
        return -1
    return 0


def source_summary(df: pd.DataFrame) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in SOURCE_COLUMNS:
        if col in df:
            values = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            row[f"{col}_mean"] = float(values.mean())
            row[f"{col}_max"] = float(values.max())
            row[f"{col}_sum"] = float(values.sum())
    row["sp_lg_sum"] = sum_existing(df, ("superpoint_lightglue_init_tracks", "superpoint_lightglue_confirmed_tracks"))
    row["xfeat_sum"] = sum_existing(df, ("xfeat_init_tracks", "xfeat_confirmed_tracks", "xfeat_star_init_tracks", "xfeat_star_confirmed_tracks"))
    row["loftr_sum"] = sum_existing(df, ("loftr_init_tracks", "loftr_confirmed_tracks"))
    row["accepted_loftr_tracks"] = parse_semidense_accepts(df, "loftr")
    row["accepted_loftr_frames"] = parse_semidense_accept_frames(df, "loftr")
    return row


def sum_existing(df: pd.DataFrame, cols: tuple[str, ...]) -> float:
    total = 0.0
    for col in cols:
        if col in df:
            total += float(pd.to_numeric(df[col], errors="coerce").fillna(0.0).sum())
    return total


def parse_semidense_accepts(df: pd.DataFrame, source: str) -> int:
    if "semidense_acceptance" not in df:
        return 0
    pattern = re.compile(rf"accepted_{re.escape(source)}_(\d+)")
    total = 0
    for value in df["semidense_acceptance"].fillna("").astype(str):
        match = pattern.search(value)
        if match:
            total += int(match.group(1))
    return total


def parse_semidense_accept_frames(df: pd.DataFrame, source: str) -> int:
    if "semidense_acceptance" not in df:
        return 0
    return int(df["semidense_acceptance"].fillna("").astype(str).str.contains(f"accepted_{source}_", regex=False).sum())


def diagnostic_summary(df: pd.DataFrame) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for col in DIAGNOSTIC_COLUMNS:
        if col in df:
            row[f"{col}_counts"] = counts(df[col], limit=5)
    for col in (
        "semidense_raw_candidates",
        "semidense_post_validate_candidates",
        "semidense_accepted_candidates",
        "semidense_queued_pending",
        "loftr_confirmed_promoted",
        "pending_loftr_count",
    ):
        if col in df:
            values = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            row[f"{col}_sum"] = float(values.sum())
            row[f"{col}_max"] = float(values.max())
    for col in ("semidense_grid_gain", "semidense_new_cell_ratio"):
        if col in df:
            values = pd.to_numeric(df[col], errors="coerce")
            row[f"{col}_max"] = float(values.max()) if not values.dropna().empty else float("nan")
    row["has_new_gate_diagnostics"] = bool(
        {"learned_mode_after_sparse_override", "semidense_raw_candidates"}.issubset(df.columns)
    )
    return row


def counts(series: pd.Series, limit: int = 5) -> str:
    vc = series.fillna("nan").astype(str).value_counts().head(limit)
    return ";".join(f"{idx}:{val}" for idx, val in vc.items())


def decision_hint(row: dict[str, Any]) -> str:
    d_grid = float(row.get("delta_grid_median", float("nan")))
    d_age = float(row.get("delta_age_median", float("nan")))
    d_dropout = float(row.get("delta_dropout_ratio_mean", float("nan")))
    d_epi = float(row.get("delta_epipolar_median", float("nan")))
    source_sum = float(row.get("sp_lg_sum", 0.0)) + float(row.get("xfeat_sum", 0.0)) + float(row.get("loftr_sum", 0.0))
    if source_sum <= 0:
        return "no_learned_effect"
    if pd.notna(d_epi) and d_epi > 0.02:
        return "geometry_regression_review"
    if (pd.notna(d_grid) and d_grid > 0) or (pd.notna(d_age) and d_age > 0) or (pd.notna(d_dropout) and d_dropout < 0):
        return "candidate_positive"
    return "needs_review"


def to_markdown(df: pd.DataFrame) -> str:
    cols = [
        "label",
        "delta_grid_median",
        "delta_age_median",
        "delta_dropout_ratio_mean",
        "delta_f_inlier_median",
        "delta_epipolar_median",
        "sp_lg_sum",
        "xfeat_sum",
        "loftr_sum",
        "accepted_loftr_tracks",
        "has_new_gate_diagnostics",
        "metric_vote_score",
        "decision_hint",
    ]
    compact = df[[col for col in cols if col in df.columns]].copy()
    headers = [str(col) for col in compact.columns]
    rows = [[fmt(value) for value in row] for row in compact.itertuples(index=False, name=None)]
    widths = [max([len(headers[i])] + [len(row[i]) for row in rows]) for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    lines.extend(
        "| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |"
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
