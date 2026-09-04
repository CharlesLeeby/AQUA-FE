#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np


METRICS = [
    "num_features",
    "grid_coverage",
    "median_track_age",
    "long_track_ratio",
    "dropped_features",
    "dropout_ratio",
    "fundamental_inlier_ratio",
    "homography_inlier_ratio",
    "median_epipolar_error",
    "median_homography_error",
    "runtime_ms",
    "superpoint_lightglue_init_tracks",
    "superpoint_lightglue_confirmed_tracks",
    "xfeat_init_tracks",
    "xfeat_confirmed_tracks",
    "loftr_init_tracks",
    "loftr_confirmed_tracks",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize frontend CSV files into a compact comparison table.")
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--baseline-token", default="klt")
    return parser.parse_args()


def numeric_column(rows: list[dict[str, str]], name: str) -> np.ndarray:
    values = []
    for row in rows:
        text = row.get(name, "")
        if text == "" or text.lower() == "nan":
            continue
        try:
            value = float(text)
        except ValueError:
            continue
        if np.isfinite(value):
            values.append(value)
    return np.asarray(values, dtype=np.float64)


def infer_dataset_method(path: Path) -> tuple[str, str]:
    stem = path.stem
    tokens = stem.split("__")
    if len(tokens) >= 2:
        return "__".join(tokens[:-1]), tokens[-1]
    parts = stem.split("_")
    known = [
        "hybrid_superpoint_lightglue",
        "superpoint_lightglue",
        "loftr_extreme_only",
        "three_layer",
        "hybrid_xfeat",
        "xfeat_star",
        "loftr",
        "klt",
    ]
    for method in known:
        suffix = "_" + method
        if stem.endswith(suffix):
            return stem[: -len(suffix)], method
    return stem, "unknown"


def summarize_file(path: Path) -> dict[str, str]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    dataset, method = infer_dataset_method(path)
    out: dict[str, str] = {
        "dataset": dataset,
        "method": method,
        "path": str(path),
        "frames": str(len(rows)),
    }
    for metric in METRICS:
        arr = numeric_column(rows, metric)
        if arr.size == 0:
            out[f"{metric}_mean"] = ""
            out[f"{metric}_median"] = ""
        else:
            out[f"{metric}_mean"] = f"{float(np.mean(arr)):.6g}"
            out[f"{metric}_median"] = f"{float(np.median(arr)):.6g}"
    return out


def add_gains(rows: list[dict[str, str]], baseline_token: str) -> None:
    baselines: dict[str, dict[str, str]] = {}
    for row in rows:
        if baseline_token in row["method"]:
            baselines.setdefault(row["dataset"], row)
    for row in rows:
        base = baselines.get(row["dataset"])
        if not base or row is base:
            row["positive_track_continuity"] = ""
            row["track_age_gain_vs_baseline"] = ""
            row["dropout_reduction_vs_baseline_pct"] = ""
            row["coverage_gain_vs_baseline"] = ""
            continue
        age = _f(row.get("median_track_age_median"))
        base_age = _f(base.get("median_track_age_median"))
        drop = _f(row.get("dropped_features_mean"))
        base_drop = _f(base.get("dropped_features_mean"))
        cov = _f(row.get("grid_coverage_median"))
        base_cov = _f(base.get("grid_coverage_median"))
        age_gain = age - base_age
        drop_gain = (base_drop - drop) / max(base_drop, 1e-6) * 100.0
        cov_gain = cov - base_cov
        row["track_age_gain_vs_baseline"] = f"{age_gain:.6g}"
        row["dropout_reduction_vs_baseline_pct"] = f"{drop_gain:.6g}"
        row["coverage_gain_vs_baseline"] = f"{cov_gain:.6g}"
        row["positive_track_continuity"] = str(age_gain > 0.0 and drop_gain >= -5.0 and cov_gain >= -0.05)


def _f(text: str | None) -> float:
    try:
        value = float(text or "nan")
    except ValueError:
        value = float("nan")
    return value if np.isfinite(value) else 0.0


def main() -> int:
    args = parse_args()
    rows = [summarize_file(Path(p)) for p in args.inputs]
    add_gains(rows, args.baseline_token)
    fields = list(rows[0].keys()) if rows else []
    extras = [
        "positive_track_continuity",
        "track_age_gain_vs_baseline",
        "dropout_reduction_vs_baseline_pct",
        "coverage_gain_vs_baseline",
    ]
    for extra in extras:
        if extra not in fields:
            fields.append(extra)
    Path(args.output_csv).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.output_csv).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(args.output_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
