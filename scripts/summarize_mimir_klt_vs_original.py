#!/usr/bin/env python3
"""Pair MIMIR pure-KLT and VINS built-in-tracker receipts by selected window."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Dict, Iterable, List


FIELDS = (
    "matched",
    "se3_ape_rmse_m",
    "se3_ape_median_m",
    "rpe_trans_rmse_m",
    "rpe_trans_median_m",
    "output_coverage_ratio",
    "first_output_delay_s",
    "init_success",
    "tracking_lost_count_proxy",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selected-windows", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--tag-prefix", default="mimir_klt_vs_original_v1")
    parser.add_argument("--output-csv", required=True, type=Path)
    parser.add_argument("--output-md", required=True, type=Path)
    return parser.parse_args()


def compact_number(value: str) -> str:
    number = float(value)
    return str(int(number)) if number.is_integer() else str(number).replace(".", "p")


def safe_stem(row: Dict[str, str]) -> str:
    environment = "".join(c if c.isalnum() else "_" for c in row["environment"].lower())
    track = "".join(c if c.isalnum() else "_" for c in row["track"].lower())
    start = compact_number(row["window_start_s"])
    duration = compact_number(str(float(row["window_end_s"]) - float(row["window_start_s"])))
    return f"{environment}_{track}_s{start}_d{duration}"


def parse_receipt(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def finite_float(value: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return math.nan
    return number if math.isfinite(number) else math.nan


def arm_metrics(run_dir: Path) -> Dict[str, object]:
    receipt = parse_receipt(run_dir / "ape.txt")
    vio = run_dir / "vins_output" / "vio.csv"
    pose_count = 0
    if vio.is_file():
        with vio.open(encoding="utf-8", errors="replace") as handle:
            pose_count = sum(1 for line in handle if line.strip())
    result: Dict[str, object] = {
        "run_dir": str(run_dir),
        "has_trajectory": int(pose_count > 0),
        "pose_count": pose_count,
    }
    for field in FIELDS:
        result[field] = receipt.get(field, "")
    return result


def classification(klt: Dict[str, object], original: Dict[str, object]) -> str:
    kt = bool(klt["has_trajectory"])
    ot = bool(original["has_trajectory"])
    ki = str(klt.get("init_success", "")) == "1"
    oi = str(original.get("init_success", "")) == "1"
    if ki and oi:
        return "both_pass"
    if ki:
        return "klt_only_pass"
    if oi:
        return "original_only_pass"
    if kt and ot:
        return "both_trajectory_no_gate_pass"
    if kt:
        return "klt_late_partial_only"
    if ot:
        return "original_late_partial_only"
    return "both_empty"


def paired_rows(selected: Iterable[Dict[str, str]], run_root: Path, prefix: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for rank, source in enumerate(selected, start=1):
        stem = safe_stem(source)
        klt_dir = run_root / f"{prefix}_{stem}_klt_vins_seed0"
        original_dir = run_root / f"{prefix}_{stem}_original_vins_seed0"
        klt = arm_metrics(klt_dir)
        original = arm_metrics(original_dir)
        row: Dict[str, object] = {
            "rank": rank,
            "sequence": source["sequence"],
            "window_start_s": compact_number(source["window_start_s"]),
            "window_end_s": compact_number(source["window_end_s"]),
            "screen_score": source["score"],
        }
        for label, metrics in (("klt", klt), ("original", original)):
            for key, value in metrics.items():
                row[f"{label}_{key}"] = value
        klt_ape = finite_float(str(klt.get("se3_ape_rmse_m", "")))
        original_ape = finite_float(str(original.get("se3_ape_rmse_m", "")))
        row["ape_rmse_klt_minus_original_m"] = (
            klt_ape - original_ape if math.isfinite(klt_ape) and math.isfinite(original_ape) else ""
        )
        row["classification"] = classification(klt, original)
        rows.append(row)
    return rows


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def fmt(value: object, digits: int = 3) -> str:
    number = finite_float(str(value))
    return f"{number:.{digits}f}" if math.isfinite(number) else "--"


def write_markdown(path: Path, rows: List[Dict[str, object]]) -> None:
    klt_trajectory = sum(int(row["klt_has_trajectory"]) for row in rows)
    original_trajectory = sum(int(row["original_has_trajectory"]) for row in rows)
    klt_pass = sum(str(row["klt_init_success"]) == "1" for row in rows)
    original_pass = sum(str(row["original_init_success"]) == "1" for row in rows)
    shared_pass = sum(
        str(row["klt_init_success"]) == "1" and str(row["original_init_success"]) == "1"
        for row in rows
    )
    lines = [
        "# MIMIR-UW pure KLT vs original VINS",
        "",
        "All runs use the nine low-texture windows selected by `isj-window-selection-v2`,",
        "the same 45 s raw window, camera/IMU timestamps, calibration, patched test VINS tree,",
        "and `VINS_INITIAL_RANSAC_SEED=0`.",
        "",
        "## Aggregate result",
        "",
        f"- Pure KLT external features produced a trajectory in {klt_trajectory}/9 windows and passed the strict initialization gate in {klt_pass}/9.",
        f"- Original VINS built-in image tracking produced a trajectory in {original_trajectory}/9 windows and passed the strict initialization gate in {original_pass}/9.",
        f"- Windows where both arms passed the strict gate: {shared_pass}/9.",
        "- The strict gate requires at least 10 matched poses, first output within 15 s, and at least 50% duration coverage.",
        "- Because no window has both arms passing the gate, there is no fair paired aggregate APE/RPE winner.",
        "",
        "## Per-window receipts",
        "",
        "| Window | KLT poses / gate | KLT APE / RPE (m) | Original poses / gate | Original APE / RPE (m) | Classification |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for row in rows:
        window = f"`{row['sequence']}` {row['window_start_s']}--{row['window_end_s']} s"
        klt_gate = row["klt_init_success"] if row["klt_init_success"] != "" else "--"
        original_gate = row["original_init_success"] if row["original_init_success"] != "" else "--"
        lines.append(
            f"| {window} | {row['klt_pose_count']} / {klt_gate} | "
            f"{fmt(row['klt_se3_ape_rmse_m'])} / {fmt(row['klt_rpe_trans_rmse_m'])} | "
            f"{row['original_pose_count']} / {original_gate} | "
            f"{fmt(row['original_se3_ape_rmse_m'])} / {fmt(row['original_rpe_trans_rmse_m'])} | "
            f"`{row['classification']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation guardrails",
            "",
            "`SeaFloor/track0` has a low numerical KLT APE only over a 12.0% tail trajectory with a 39.5 s first-output delay; it is not a KLT accuracy win.",
            "MIMIR monocular-inertial scale remains poorly conditioned: original-VINS strict-pass runs still have very large absolute APE.",
            "Use the initialization/coverage comparison as the primary result and treat APE/RPE as per-run diagnostics until both arms pass on the same window.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = parse_args()
    with args.selected_windows.open(newline="", encoding="utf-8") as handle:
        selected = list(csv.DictReader(handle))
    if len(selected) != 9:
        raise SystemExit(f"expected 9 selected windows, got {len(selected)}")
    rows = paired_rows(selected, args.run_root, args.tag_prefix)
    write_csv(args.output_csv, rows)
    write_markdown(args.output_md, rows)
    print(f"wrote {args.output_csv}")
    print(f"wrote {args.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
