#!/usr/bin/env python3
"""Evaluate VINS-Fusion output against a TUM ground-truth trajectory."""

from __future__ import annotations

import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from evaluate_vins_sim_ape import (  # noqa: E402
    align_se3,
    compute_rpe,
    load_vins,
    parse_vins_log,
    trajectory_gap_stats,
)


def load_tum(path: Path) -> list[tuple[float, np.ndarray]]:
    rows: list[tuple[float, np.ndarray]] = []
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            try:
                stamp = float(parts[0])
                pos = np.array([float(parts[1]), float(parts[2]), float(parts[3])], dtype=float)
            except (TypeError, ValueError):
                continue
            if math.isfinite(stamp) and np.all(np.isfinite(pos)):
                rows.append((stamp, pos))
    rows.sort(key=lambda item: item[0])
    return rows


def nearest_gt(gt: list[tuple[float, np.ndarray]], t: float) -> tuple[np.ndarray, float]:
    lo = 0
    hi = len(gt) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if gt[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    candidates = [lo]
    if lo > 0:
        candidates.append(lo - 1)
    idx = min(candidates, key=lambda item: abs(gt[item][0] - t))
    return gt[idx][1], abs(gt[idx][0] - t)


def make_pairs(
    vins: list[tuple[float, np.ndarray]],
    gt: list[tuple[float, np.ndarray]],
    max_match_dt: float,
) -> tuple[list[tuple[float, np.ndarray, np.ndarray]], list[float]]:
    pairs = []
    time_errors = []
    if not gt:
        return pairs, time_errors
    for stamp, pos in vins:
        if gt[0][0] <= stamp <= gt[-1][0]:
            gt_pos, dt = nearest_gt(gt, stamp)
            if max_match_dt <= 0.0 or dt <= max_match_dt:
                pairs.append((stamp, pos, gt_pos))
                time_errors.append(dt)
    return pairs, time_errors


def write_tum_files(
    out_dir: Path,
    run_name: str,
    pairs: list[tuple[float, np.ndarray, np.ndarray]],
) -> tuple[Path, Path]:
    tum_dir = out_dir / "tum"
    tum_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", run_name)
    ref_path = tum_dir / f"{safe_name}_gt_matched.tum"
    est_path = tum_dir / f"{safe_name}_est_matched.tum"
    with ref_path.open("w", encoding="utf-8") as ref, est_path.open("w", encoding="utf-8") as est:
        for stamp, est_pos, gt_pos in pairs:
            ref.write(format_tum_line(stamp, gt_pos))
            est.write(format_tum_line(stamp, est_pos))
    return ref_path, est_path


def format_tum_line(stamp: float, pos: np.ndarray) -> str:
    return f"{stamp:.9f} {pos[0]:.9f} {pos[1]:.9f} {pos[2]:.9f} 0.0 0.0 0.0 1.0\n"


def make_evo_command(kind: str, ref_path: Path, est_path: Path) -> str:
    if kind == "ape":
        return f"evo_ape tum {ref_path} {est_path} -a -r trans_part"
    return f"evo_rpe tum {ref_path} {est_path} -a -r trans_part -d 10 -u f"


def parse_evo_rmse(text: str) -> float:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "rmse":
            try:
                return float(parts[-1])
            except ValueError:
                return float("nan")
    return float("nan")


def run_evo_metrics(ref_path: Path, est_path: Path) -> dict[str, object]:
    if not shutil.which("evo_ape") or not shutil.which("evo_rpe"):
        return {"evo_status": "blocked_evo_not_found"}
    out: dict[str, object] = {"evo_status": "completed"}
    for kind in ["ape", "rpe"]:
        cmd = make_evo_command(kind, ref_path, est_path).split()
        proc = subprocess.run(cmd, cwd=str(ROOT), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        out[f"evo_{kind}_returncode"] = proc.returncode
        out[f"evo_{kind}_rmse_m"] = parse_evo_rmse(proc.stdout)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vins-csv", required=True)
    parser.add_argument("--gt-tum", required=True)
    parser.add_argument("--vins-log", default=None)
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--max-match-dt", type=float, default=0.0)
    parser.add_argument("--gap-threshold-s", type=float, default=0.0)
    parser.add_argument("--expected-start", type=float, default=None)
    parser.add_argument("--expected-end", type=float, default=None)
    parser.add_argument("--init-timeout-s", type=float, default=15.0)
    parser.add_argument("--min-init-poses", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.50)
    parser.add_argument("--write-tum", action="store_true")
    parser.add_argument("--run-evo", action="store_true")
    args = parser.parse_args()

    vins = load_vins(Path(args.vins_csv))
    gt = load_tum(Path(args.gt_tum))
    if not vins:
        raise SystemExit(f"empty VINS trajectory: {args.vins_csv}")
    if not gt:
        raise SystemExit(f"empty GT trajectory: {args.gt_tum}")

    stats_gt = expected_window_gt(gt, args.expected_start, args.expected_end)
    gap_stats = trajectory_gap_stats(vins, stats_gt, args.gap_threshold_s)
    log_stats = parse_vins_log(Path(args.vins_log) if args.vins_log else None)
    pairs, time_errors = make_pairs(vins, gt, args.max_match_dt)
    if len(pairs) < 3:
        raise SystemExit("not enough matched poses")

    stamps = np.asarray([item[0] for item in pairs], dtype=float)
    source = np.stack([item[1] for item in pairs])
    target = np.stack([item[2] for item in pairs])
    aligned = align_se3(source, target)
    errors = np.linalg.norm(aligned - target, axis=1)
    rpe_errors = compute_rpe(stamps, aligned, target, args.rpe_delta_s)
    init_success = (
        len(pairs) >= int(args.min_init_poses)
        and gap_stats["first_output_delay_s"] <= float(args.init_timeout_s)
        and gap_stats["output_coverage_ratio"] >= float(args.min_coverage_ratio)
    )
    terminal_drop_count = 1 if gap_stats["last_output_drop_s"] > max(1.0, args.gap_threshold_s) else 0
    tracking_lost_proxy = int(gap_stats["large_output_gap_count"]) + terminal_drop_count

    print(f"matched={len(pairs)}")
    print(f"duration_s={vins[-1][0] - vins[0][0]:.3f}")
    print(f"max_timestamp_error_s={max(time_errors):.6f}")
    print(f"se3_ape_rmse_m={np.sqrt(np.mean(errors ** 2)):.6f}")
    print(f"se3_ape_median_m={np.median(errors):.6f}")
    print(f"se3_ape_max_m={np.max(errors):.6f}")
    print(f"rpe_delta_s={args.rpe_delta_s:.3f}")
    print(f"rpe_pairs={len(rpe_errors)}")
    print(f"rpe_trans_rmse_m={np.sqrt(np.mean(rpe_errors ** 2)):.6f}" if len(rpe_errors) else "rpe_trans_rmse_m=nan")
    print(f"rpe_trans_median_m={np.median(rpe_errors):.6f}" if len(rpe_errors) else "rpe_trans_median_m=nan")
    print(f"rpe_trans_max_m={np.max(rpe_errors):.6f}" if len(rpe_errors) else "rpe_trans_max_m=nan")
    for key, value in gap_stats.items():
        if isinstance(value, float):
            print(f"{key}={value:.6f}")
        else:
            print(f"{key}={value}")
    print(f"init_success={1 if init_success else 0}")
    print(f"tracking_lost_count_proxy={tracking_lost_proxy}")
    for key, value in log_stats.items():
        print(f"{key}={value}")

    if args.output_dir:
        out_dir = Path(args.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.write_tum or args.run_evo:
            tum_ref, tum_est = write_tum_files(out_dir, Path(args.vins_csv).parent.parent.name, pairs)
            print(f"tum_ref={tum_ref}")
            print(f"tum_est={tum_est}")
            print(f"evo_ape_command={make_evo_command('ape', tum_ref, tum_est)}")
            print(f"evo_rpe_command={make_evo_command('rpe', tum_ref, tum_est)}")
            if args.run_evo:
                evo_stats = run_evo_metrics(tum_ref, tum_est)
                for key, value in evo_stats.items():
                    print(f"{key}={value}")

    return 0


def expected_window_gt(
    gt: list[tuple[float, np.ndarray]],
    expected_start: float | None,
    expected_end: float | None,
) -> list[tuple[float, np.ndarray]]:
    if expected_start is None or expected_end is None or expected_end <= expected_start:
        return gt
    window = [item for item in gt if expected_start <= item[0] <= expected_end]
    return window if len(window) >= 2 else gt


if __name__ == "__main__":
    raise SystemExit(main())
