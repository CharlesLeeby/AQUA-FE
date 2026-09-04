#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

import numpy as np
import pandas as pd


METRIC_KEYS = [
    "se3_ape_rmse_m",
    "rpe_trans_rmse_m",
    "output_coverage_ratio",
    "first_output_delay_s",
    "tracking_lost_count_proxy",
    "log_linear_solver_failures",
    "log_failure_mentions",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize C3 VINS replay repeats from ape.txt files.")
    parser.add_argument("--repeats-root", action="append", default=["logs/conformal_calibration/repeats"])
    parser.add_argument("--alpha-root", action="append", default=[
        "logs/conformal_calibration/alpha_scan_a06",
        "logs/conformal_calibration/alpha_scan_h07",
    ])
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--report-md", required=True)
    parser.add_argument("--raw-output-csv", default=None)
    parser.add_argument(
        "--exclude-run-regex",
        action="append",
        default=[],
        help="Exclude run_name values matching this regex. Repeatable.",
    )
    args = parser.parse_args()

    rows = []
    for root in args.repeats_root:
        rows.extend(_rows_from_repeats(Path(root)))
    for root in args.alpha_root:
        rows.extend(_rows_from_alpha_root(Path(root)))
    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("no ape.txt files found")
    for pattern in args.exclude_run_regex:
        df = df[~df["run_name"].astype(str).str.contains(pattern, regex=True)].copy()

    summary = _summarize(df)
    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out_csv, index=False)
    if args.raw_output_csv:
        raw_csv = Path(args.raw_output_csv)
        raw_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(raw_csv, index=False)

    report = _make_report(summary)
    report_md = Path(args.report_md)
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(report, encoding="utf-8")
    if args.raw_output_csv:
        print(f"wrote {Path(args.raw_output_csv)}")
    print(f"wrote {out_csv}")
    print(f"wrote {report_md}")
    print(summary.to_string(index=False))
    return 0


def _rows_from_repeats(root: Path) -> list[dict]:
    rows = []
    if not root.exists():
        return rows
    for ape_path in sorted(root.glob("*/ape.txt")):
        run_name = ape_path.parent.name
        metrics = _read_ape(ape_path)
        if not metrics:
            continue
        dataset, alpha, method, repeat = _parse_repeat_name(run_name)
        rows.append({
            "source": "repeats",
            "run_name": run_name,
            "dataset": dataset,
            "alpha": alpha,
            "method": method,
            "repeat": repeat,
            "ape_path": str(ape_path),
            **metrics,
        })
    return rows


def _rows_from_alpha_root(root: Path) -> list[dict]:
    rows = []
    if not root.exists():
        return rows
    dataset = root.name.replace("alpha_scan_", "")
    for ape_path in sorted(root.glob("a*_vins/ape.txt")):
        run_name = ape_path.parent.name
        alpha = _alpha_from_token(run_name.replace("_vins", ""))
        metrics = _read_ape(ape_path)
        if not metrics:
            continue
        rows.append({
            "source": "alpha_single",
            "run_name": run_name,
            "dataset": dataset,
            "alpha": alpha,
            "method": "c95_blend",
            "repeat": 1,
            "ape_path": str(ape_path),
            **metrics,
        })
    return rows


def _read_ape(path: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key not in METRIC_KEYS:
            continue
        try:
            out[key] = float(value.strip())
        except ValueError:
            out[key] = float("nan")
    return out


def _parse_repeat_name(name: str) -> tuple[str, float, str, int]:
    repeat = 1
    m = re.search(r"(?:_r|_rep)(\d+)$", name)
    if m:
        repeat = int(m.group(1))
    dataset = "unknown"
    for key in ["h07", "a06", "afrl_fl", "afrl_fr"]:
        if name.startswith(key):
            dataset = key
            break
    alpha = float("nan")
    m = re.search(r"blend(\d{3})", name)
    if m:
        alpha = _alpha_from_token("a" + m.group(1))
    else:
        m = re.search(r"_a(\d{3})(?:_|$)", name)
        if m:
            alpha = _alpha_from_token("a" + m.group(1))
    method = "baseline" if "baseline" in name or "constq" in name else "c95_blend"
    if "c90" in name:
        method = "c90_blend"
    if "xfeat" in name:
        method += "_xfeat"
    elif "klt" in name:
        method += "_klt"
    elif "mirrorinject" in name:
        method += "_mirrorinject"
    return dataset, alpha, method, repeat


def _alpha_from_token(token: str) -> float:
    token = token.lower().strip()
    digits = re.sub(r"[^0-9]", "", token)
    if not digits:
        return float("nan")
    if len(digits) == 3:
        return float(digits) / 100.0
    if len(digits) == 2:
        return float(digits) / 100.0
    return float(digits)


def _summarize(df: pd.DataFrame) -> pd.DataFrame:
    group_cols = ["dataset", "method", "alpha"]
    rows = []
    for key, group in df.groupby(group_cols, dropna=False, sort=True):
        dataset, method, alpha = key
        row = {
            "dataset": dataset,
            "method": method,
            "alpha": alpha,
            "n": int(len(group)),
            "runs": ";".join(str(v) for v in group["run_name"].tolist()),
        }
        for metric in METRIC_KEYS:
            values = group[metric].to_numpy(dtype=float) if metric in group else np.asarray([], dtype=float)
            values = values[np.isfinite(values)]
            row[f"{metric}_median"] = float(np.median(values)) if values.size else float("nan")
            row[f"{metric}_min"] = float(np.min(values)) if values.size else float("nan")
            row[f"{metric}_max"] = float(np.max(values)) if values.size else float("nan")
            row[f"{metric}_values"] = ";".join(f"{item:.6f}" for item in values)
        rows.append(row)
    return pd.DataFrame(rows)


def _make_report(summary: pd.DataFrame) -> str:
    lines = ["# C3 Replay Repeat Summary", ""]
    for dataset, group in summary.groupby("dataset", sort=True):
        lines.append(f"## {dataset}")
        lines.append("")
        cols = [
            "method",
            "alpha",
            "n",
            "se3_ape_rmse_m_median",
            "se3_ape_rmse_m_min",
            "se3_ape_rmse_m_max",
            "rpe_trans_rmse_m_median",
            "output_coverage_ratio_median",
            "log_failure_mentions_median",
        ]
        lines.append(_markdown_table(group[cols]))
        lines.append("")
    return "\n".join(lines)


def _markdown_table(df: pd.DataFrame) -> str:
    cols = [str(c) for c in df.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join("---" for _ in cols) + " |",
    ]
    for _, row in df.iterrows():
        values = []
        for col in df.columns:
            value = row[col]
            if isinstance(value, float):
                values.append("" if np.isnan(value) else f"{value:.6f}")
            else:
                values.append(str(value))
        lines.append("| " + " | ".join(values) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
