#!/usr/bin/env python3
"""Summarize repeated VINS replays grouped by case and variant.

Input is a small CSV with columns:
  case,variant,run_dir

The script reads each run's ape.txt and frontend_metrics.csv, then writes a
per-run table and a grouped median/IQR table. It is intentionally lightweight:
feature bags are treated as fixed frontend outputs, while VINS replay variation
is summarized statistically.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


FEATURE_TOPIC = "/feature_tracker/feature"
LEARNED_SOURCE_CODES = {10, 20, 30}
LOFTR_SOURCE_CODE = 30


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", required=True, help="CSV with case,variant,run_dir columns.")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    spec_path = Path(args.spec)
    rows = []
    with spec_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            run_dir = Path(row["run_dir"])
            rows.append(
                {
                    "case": row["case"],
                    "variant": row["variant"],
                    "run_dir": str(run_dir),
                    **read_ape(run_dir / "ape.txt"),
                    **read_frontend(run_dir / "frontend_metrics.csv"),
                    **audit_replayed_feature_bag(run_dir),
                }
            )

    per_run = pd.DataFrame(rows)
    grouped = summarize_groups(per_run)
    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    grouped.to_csv(out_csv, index=False)
    Path(args.output_md).write_text(render_markdown(grouped, per_run), encoding="utf-8")
    print(f"wrote {out_csv}")
    print(f"wrote {args.output_md}")
    print(grouped.to_string(index=False))
    return 0


def read_ape(path: Path) -> dict[str, float]:
    out = {
        "ape_rmse": math.nan,
        "rpe_rmse": math.nan,
        "coverage": math.nan,
        "init_success": math.nan,
        "lost": math.nan,
        "solver_failures": math.nan,
    }
    if not path.exists():
        return out
    text = path.read_text(encoding="utf-8", errors="ignore")
    key_map = {
        "se3_ape_rmse_m": "ape_rmse",
        "rpe_trans_rmse_m": "rpe_rmse",
        "output_coverage_ratio": "coverage",
        "init_success": "init_success",
        "tracking_lost_count_proxy": "lost",
        "log_linear_solver_failures": "solver_failures",
    }
    for source, target in key_map.items():
        match = re.search(rf"{re.escape(source)}=([0-9.eE+-]+)", text)
        if match:
            out[target] = float(match.group(1))
    return out


def read_frontend(path: Path) -> dict[str, float]:
    out = {
        "exported_features_median": math.nan,
        "exported_learned_sum": 0.0,
        "exported_xfeat_sum": 0.0,
        "exported_loftr_sum": 0.0,
        "learned_candidate_sum": 0.0,
        "learned_confirmed_sum": 0.0,
        "classical_grid_median": math.nan,
    }
    if not path.exists():
        return out
    df = pd.read_csv(path)
    columns = {
        "exported_features": ("exported_features_median", "median"),
        "exported_learned_features": ("exported_learned_sum", "sum"),
        "exported_xfeat_features": ("exported_xfeat_sum", "sum"),
        "exported_loftr_features": ("exported_loftr_sum", "sum"),
        "learned_candidate_count": ("learned_candidate_sum", "sum"),
        "learned_confirmed_count": ("learned_confirmed_sum", "sum"),
        "classical_grid_coverage": ("classical_grid_median", "median"),
    }
    for source, (target, op) in columns.items():
        if source not in df:
            continue
        series = pd.to_numeric(df[source], errors="coerce").fillna(0.0)
        out[target] = float(series.median() if op == "median" else series.sum())
    return out


def summarize_groups(per_run: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (case, variant), group in per_run.groupby(["case", "variant"], sort=True):
        rows.append(
            {
                "case": case,
                "variant": variant,
                "repeats": int(len(group)),
                "ape_median": finite_median(group["ape_rmse"]),
                "ape_iqr": finite_iqr(group["ape_rmse"]),
                "rpe_median": finite_median(group["rpe_rmse"]),
                "rpe_iqr": finite_iqr(group["rpe_rmse"]),
                "coverage_median": finite_median(group["coverage"]),
                "init_success_all": int(np.nanmin(group["init_success"].to_numpy(dtype=float)) >= 1.0),
                "lost_median": finite_median(group["lost"]),
                "solver_failures_median": finite_median(group["solver_failures"]),
                "exported_learned_sum_median": finite_median(group["exported_learned_sum"]),
                "exported_xfeat_sum_median": finite_median(group["exported_xfeat_sum"]),
                "exported_loftr_sum_median": finite_median(group["exported_loftr_sum"]),
                "published_observations_median": finite_median(group["published_observations"]),
                "published_learned_median": finite_median(group["published_learned"]),
                "published_loftr_median": finite_median(group["published_loftr"]),
                "classical_grid_median": finite_median(group["classical_grid_median"]),
            }
        )
    grouped = pd.DataFrame(rows)
    return add_pairwise_deltas(grouped)


def add_pairwise_deltas(grouped: pd.DataFrame) -> pd.DataFrame:
    out = grouped.copy()
    out["baseline_variant"] = ""
    out["ape_delta_vs_baseline"] = np.nan
    out["rpe_delta_vs_baseline"] = np.nan
    out["ape_delta_pct_vs_baseline"] = np.nan
    out["rpe_delta_pct_vs_baseline"] = np.nan
    for case, idxs in out.groupby("case").groups.items():
        sub = out.loc[list(idxs)]
        baseline = None
        for name in ("drop", "klt", "protected_klt", "baseline"):
            cand = sub[sub["variant"] == name]
            if not cand.empty:
                baseline = cand.iloc[0]
                break
        if baseline is None:
            continue
        for idx in idxs:
            out.at[idx, "baseline_variant"] = str(baseline["variant"])
            out.at[idx, "ape_delta_vs_baseline"] = float(out.at[idx, "ape_median"]) - float(
                baseline["ape_median"]
            )
            out.at[idx, "rpe_delta_vs_baseline"] = float(out.at[idx, "rpe_median"]) - float(
                baseline["rpe_median"]
            )
            if float(baseline["ape_median"]) > 0:
                out.at[idx, "ape_delta_pct_vs_baseline"] = (
                    100.0 * out.at[idx, "ape_delta_vs_baseline"] / float(baseline["ape_median"])
                )
            if float(baseline["rpe_median"]) > 0:
                out.at[idx, "rpe_delta_pct_vs_baseline"] = (
                    100.0 * out.at[idx, "rpe_delta_vs_baseline"] / float(baseline["rpe_median"])
                )
    return out


def finite_median(values: pd.Series) -> float:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    return float(np.median(arr)) if len(arr) else math.nan


def finite_iqr(values: pd.Series) -> float:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return math.nan
    return float(np.percentile(arr, 75) - np.percentile(arr, 25))


def render_markdown(grouped: pd.DataFrame, per_run: pd.DataFrame) -> str:
    lines = [
        "# VINS Replay Group Summary",
        "",
        "Grouped metrics use median over repeated VINS replays of fixed feature bags.",
        "",
        dataframe_to_markdown(grouped),
        "",
        "## Per-Run Inputs",
        "",
        dataframe_to_markdown(
            per_run[
                [
                    "case",
                    "variant",
                    "ape_rmse",
                    "rpe_rmse",
                    "coverage",
                    "exported_learned_sum",
                    "exported_xfeat_sum",
                    "exported_loftr_sum",
                    "published_learned",
                    "published_loftr",
                    "run_dir",
                ]
            ]
        ),
        "",
    ]
    return "\n".join(lines)


def audit_replayed_feature_bag(run_dir: Path) -> dict[str, float | str]:
    out: dict[str, float | str] = {
        "published_feature_bag": "",
        "published_observations": math.nan,
        "published_learned": math.nan,
        "published_loftr": math.nan,
        "published_bag_audit_status": "unavailable",
    }
    manifest = read_manifest(run_dir / "replay_manifest.txt")
    bag_path_text = manifest.get("play_bag") or manifest.get("feature_bag") or ""
    if not bag_path_text:
        ape_manifest = read_manifest(run_dir / "ape.txt")
        bag_path_text = ape_manifest.get("play_bag") or ape_manifest.get("feature_bag") or ""
    if not bag_path_text:
        return out
    out["published_feature_bag"] = bag_path_text
    bag_path = Path(bag_path_text)
    if not bag_path.exists():
        out["published_bag_audit_status"] = "missing_bag"
        return out
    try:
        import rosbag
    except ImportError:
        out["published_bag_audit_status"] = "rosbag_import_failed"
        return out

    total = 0
    learned = 0
    loftr = 0
    saw_source_channel = False
    with rosbag.Bag(str(bag_path), "r") as bag:
        for _, msg, _ in bag.read_messages(FEATURE_TOPIC):
            count = len(msg.points)
            total += count
            channels = {channel.name: list(channel.values) for channel in msg.channels}
            is_learned = channel_values(channels, "is_learned", count)
            source_code = channel_values(channels, "source_code", count)
            if is_learned is None and source_code is None:
                continue
            saw_source_channel = True
            for idx in range(count):
                source = safe_int(source_code[idx], 0) if source_code is not None else 0
                learned_flag = bool(is_learned is not None and float(is_learned[idx]) > 0.5)
                if learned_flag or source in LEARNED_SOURCE_CODES:
                    learned += 1
                if source == LOFTR_SOURCE_CODE:
                    loftr += 1
    out["published_observations"] = float(total)
    out["published_learned"] = float(learned)
    out["published_loftr"] = float(loftr)
    out["published_bag_audit_status"] = (
        "source_channels_audited" if saw_source_channel else "source_channels_missing"
    )
    return out


def read_manifest(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if "=" not in line:
                continue
            key, value = line.strip().split("=", 1)
            out[key] = value
    return out


def channel_values(
    channels: dict[str, list[Any]], name: str, length: int
) -> list[float] | None:
    values = channels.get(name)
    if values is None or len(values) != length:
        return None
    return [float(value) for value in values]


def safe_int(value: object, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def dataframe_to_markdown(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows._"
    columns = list(df.columns)
    rendered_rows = []
    for _, row in df.iterrows():
        rendered = []
        for col in columns:
            value = row[col]
            if isinstance(value, float):
                if math.isnan(value):
                    rendered.append("")
                else:
                    rendered.append(f"{value:.6g}")
            else:
                rendered.append(str(value))
        rendered_rows.append(rendered)
    widths = [
        max(len(str(col)), *(len(row[idx]) for row in rendered_rows))
        for idx, col in enumerate(columns)
    ]
    header = "| " + " | ".join(str(col).ljust(widths[idx]) for idx, col in enumerate(columns)) + " |"
    sep = "| " + " | ".join("-" * widths[idx] for idx in range(len(columns))) + " |"
    body = [
        "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(columns))) + " |"
        for row in rendered_rows
    ]
    return "\n".join([header, sep, *body])


if __name__ == "__main__":
    raise SystemExit(main())
