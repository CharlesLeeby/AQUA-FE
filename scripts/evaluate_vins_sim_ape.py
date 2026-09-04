#!/usr/bin/env python3
"""Evaluate VINS-Fusion output against a ROS ground-truth trajectory.

The script keeps the original APE text keys used by the project run scripts,
and adds trajectory-level diagnostics that are useful for VIO/SLAM robustness:
RPE, output coverage, initialization success, and a tracking-loss proxy.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
from pathlib import Path

import numpy as np
import rosbag


def load_vins(path: Path) -> list[tuple[float, np.ndarray]]:
    rows: list[tuple[float, np.ndarray]] = []
    if not path.exists():
        return rows
    with path.open(newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 4:
                continue
            try:
                stamp = float(row[0]) * 1e-9
                pos = np.array([float(row[1]), float(row[2]), float(row[3])], dtype=float)
            except (TypeError, ValueError):
                continue
            if np.all(np.isfinite(pos)) and math.isfinite(stamp):
                rows.append((stamp, pos))
    rows.sort(key=lambda item: item[0])
    return rows


def load_gt(bag_path: Path, topic: str) -> list[tuple[float, np.ndarray]]:
    rows: list[tuple[float, np.ndarray]] = []
    with rosbag.Bag(str(bag_path)) as bag:
        for _, msg, _ in bag.read_messages(topics=[topic]):
            if hasattr(msg, "pose") and hasattr(msg.pose, "pose"):
                p = msg.pose.pose.position
                stamp = msg.header.stamp.to_sec()
            elif hasattr(msg, "pose"):
                p = msg.pose.position
                stamp = msg.header.stamp.to_sec()
            elif hasattr(msg, "transform"):
                p = msg.transform.translation
                stamp = msg.header.stamp.to_sec()
            else:
                continue
            rows.append((msg.header.stamp.to_sec(), np.array([p.x, p.y, p.z], dtype=float)))
            rows[-1] = (stamp, rows[-1][1])
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


def align_se3(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    src_centered = source - source.mean(axis=0)
    dst_centered = target - target.mean(axis=0)
    u_mat, _, vt_mat = np.linalg.svd(src_centered.T @ dst_centered)
    rot = vt_mat.T @ u_mat.T
    if np.linalg.det(rot) < 0:
        vt_mat[-1] *= -1
        rot = vt_mat.T @ u_mat.T
    trans = target.mean(axis=0) - rot @ source.mean(axis=0)
    return (rot @ source.T).T + trans


def make_pairs(
    vins: list[tuple[float, np.ndarray]],
    gt: list[tuple[float, np.ndarray]],
    max_match_dt: float,
) -> tuple[list[tuple[float, np.ndarray, np.ndarray]], list[float]]:
    pairs = []
    time_errors = []
    for stamp, pos in vins:
        if gt[0][0] <= stamp <= gt[-1][0]:
            gt_pos, dt = nearest_gt(gt, stamp)
            if max_match_dt <= 0.0 or dt <= max_match_dt:
                pairs.append((stamp, pos, gt_pos))
                time_errors.append(dt)
    return pairs, time_errors


def compute_rpe(
    stamps: np.ndarray,
    aligned: np.ndarray,
    target: np.ndarray,
    delta_s: float,
) -> np.ndarray:
    if len(stamps) < 3:
        return np.empty((0,), dtype=float)
    errors = []
    for idx, stamp in enumerate(stamps):
        target_stamp = stamp + delta_s
        j = int(np.searchsorted(stamps, target_stamp, side="left"))
        if j >= len(stamps):
            break
        if idx == j:
            continue
        est_delta = aligned[j] - aligned[idx]
        gt_delta = target[j] - target[idx]
        errors.append(float(np.linalg.norm(est_delta - gt_delta)))
    return np.asarray(errors, dtype=float)


def trajectory_gap_stats(
    vins: list[tuple[float, np.ndarray]],
    gt: list[tuple[float, np.ndarray]],
    gap_threshold_s: float,
) -> dict[str, float]:
    if not vins:
        expected_duration = max(0.0, gt[-1][0] - gt[0][0]) if gt else 0.0
        return {
            "output_poses": 0.0,
            "output_duration_s": 0.0,
            "expected_duration_s": expected_duration,
            "output_coverage_ratio": 0.0,
            "first_output_delay_s": float("inf"),
            "last_output_drop_s": float("inf"),
            "median_output_dt_s": 0.0,
            "max_output_gap_s": 0.0,
            "large_output_gap_count": 0.0,
        }
    stamps = np.asarray([item[0] for item in vins], dtype=float)
    gaps = np.diff(stamps)
    output_duration = max(0.0, float(stamps[-1] - stamps[0]))
    expected_duration = max(0.0, float(gt[-1][0] - gt[0][0])) if gt else output_duration
    if gap_threshold_s <= 0.0:
        nominal = float(np.median(gaps)) if len(gaps) else 0.0
        gap_threshold_s = max(0.75, 5.0 * nominal)
    large_gap_count = int(np.sum(gaps > gap_threshold_s)) if len(gaps) else 0
    coverage = output_duration / expected_duration if expected_duration > 1e-9 else 1.0
    return {
        "output_poses": float(len(vins)),
        "output_duration_s": output_duration,
        "expected_duration_s": expected_duration,
        "output_coverage_ratio": float(max(0.0, min(1.0, coverage))),
        "first_output_delay_s": float(stamps[0] - gt[0][0]) if gt else 0.0,
        "last_output_drop_s": float(gt[-1][0] - stamps[-1]) if gt else 0.0,
        "median_output_dt_s": float(np.median(gaps)) if len(gaps) else 0.0,
        "max_output_gap_s": float(np.max(gaps)) if len(gaps) else 0.0,
        "large_output_gap_count": float(large_gap_count),
    }


def parse_vins_log(path: Path | None) -> dict[str, int]:
    if path is None or not path.exists():
        return {
            "log_linear_solver_failures": 0,
            "log_failure_mentions": 0,
            "log_restart_mentions": 0,
            "log_waiting_mentions": 0,
        }
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    return {
        "log_linear_solver_failures": len(re.findall(r"linear solver failure", text)),
        "log_failure_mentions": len(re.findall(r"\bfail(?:ed|ure)?\b", text)),
        "log_restart_mentions": len(re.findall(r"restart", text)),
        "log_waiting_mentions": len(re.findall(r"waiting for image and imu", text)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vins-csv", default="logs/vins_origin/sim_pure_vins_output/vio.csv")
    parser.add_argument("--bag", default="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_40s.bag")
    parser.add_argument("--gt-topic", default="/ground_truth/state")
    parser.add_argument("--vins-log", default=None)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument(
        "--max-match-dt",
        type=float,
        default=0.0,
        help="Maximum VINS/GT timestamp distance in seconds; <=0 keeps the legacy nearest-match behavior.",
    )
    parser.add_argument(
        "--gap-threshold-s",
        type=float,
        default=0.0,
        help="Output timestamp gap counted as a lost-tracking proxy; <=0 uses max(0.75s, 5x median dt).",
    )
    parser.add_argument("--init-timeout-s", type=float, default=15.0)
    parser.add_argument("--min-init-poses", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.50)
    parser.add_argument(
        "--score-start-offset-s",
        type=float,
        default=0.0,
        help="Score only poses at or after this offset from the first GT timestamp.",
    )
    parser.add_argument(
        "--score-duration-s",
        type=float,
        default=0.0,
        help="Optional score duration; <=0 scores through the end of the bag.",
    )
    args = parser.parse_args()

    all_vins = load_vins(Path(args.vins_csv))
    all_gt = load_gt(Path(args.bag), args.gt_topic)
    if not all_vins:
        raise SystemExit(f"empty VINS trajectory: {args.vins_csv}")
    if not all_gt:
        raise SystemExit(f"empty GT topic: {args.gt_topic}")
    if args.score_start_offset_s < 0.0:
        raise SystemExit("--score-start-offset-s must be non-negative")
    score_start = all_gt[0][0] + float(args.score_start_offset_s)
    score_end = (
        score_start + float(args.score_duration_s)
        if args.score_duration_s > 0.0
        else all_gt[-1][0]
    )
    gt = [item for item in all_gt if score_start <= item[0] <= score_end]
    vins = [item for item in all_vins if score_start <= item[0] <= score_end]
    if len(gt) < 3:
        raise SystemExit("not enough GT poses in requested score interval")
    if not vins:
        raise SystemExit("empty VINS trajectory in requested score interval")

    gap_stats = trajectory_gap_stats(vins, gt, args.gap_threshold_s)
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
    print(f"score_start_offset_s={args.score_start_offset_s:.6f}")
    print(f"score_duration_requested_s={args.score_duration_s:.6f}")
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


if __name__ == "__main__":
    main()
