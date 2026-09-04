#!/usr/bin/env python3
"""Evaluate fixed-scale SE(3) and diagnostic Sim(3) on one common 1 Hz grid."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np

import evaluate_vins_common_support as base
from trajectory_eval_core import (
    evaluate_common_translation,
    make_uniform_grid,
    prepare_reference_samples,
    resample_trajectory,
    transform_body_poses_to_sensor,
    validate_estimate_samples,
)


def align_sim3_positions(source: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float]:
    source = np.asarray(source, dtype=float)
    target = np.asarray(target, dtype=float)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 3:
        raise ValueError("source and target must both have shape (N, 3)")
    if len(source) < 3:
        raise ValueError("at least three positions are required for Sim(3)")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_centered = source - source_mean
    target_centered = target - target_mean
    u_mat, _, vt_mat = np.linalg.svd(source_centered.T @ target_centered)
    rotation = vt_mat.T @ u_mat.T
    if np.linalg.det(rotation) < 0:
        vt_mat[-1] *= -1
        rotation = vt_mat.T @ u_mat.T
    rotated = (rotation @ source_centered.T).T
    denominator = float(np.sum(source_centered**2))
    if denominator <= 0.0:
        raise ValueError("degenerate source trajectory for Sim(3)")
    scale = float(np.sum(target_centered * rotated) / denominator)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError(f"non-positive Sim(3) scale: {scale}")
    aligned = scale * rotated + target_mean
    return aligned, scale


def error_metrics(
    aligned: np.ndarray,
    reference: np.ndarray,
    pairs: np.ndarray,
) -> dict[str, float]:
    ape = np.linalg.norm(aligned - reference, axis=1)
    metrics = {
        "ape_rmse_m": float(np.sqrt(np.mean(ape**2))),
        "ape_median_m": float(np.median(ape)),
        "ape_max_m": float(np.max(ape)),
    }
    if len(pairs):
        reference_delta = reference[pairs[:, 1]] - reference[pairs[:, 0]]
        estimate_delta = aligned[pairs[:, 1]] - aligned[pairs[:, 0]]
        rpe = np.linalg.norm(estimate_delta - reference_delta, axis=1)
        metrics.update(
            {
                "rpe_rmse_m": float(np.sqrt(np.mean(rpe**2))),
                "rpe_median_m": float(np.median(rpe)),
                "rpe_max_m": float(np.max(rpe)),
            }
        )
    return metrics


def parse_evo_rmse(output: str) -> float:
    for line in output.splitlines():
        fields = line.strip().split()
        if fields and fields[0] == "rmse":
            return float(fields[-1])
    raise RuntimeError("evo output contains no rmse row")


def evo(command: list[str], log: Path) -> float:
    process = subprocess.run(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False
    )
    log.write_text("$ " + " ".join(command) + "\n" + process.stdout, encoding="utf-8")
    if process.returncode != 0:
        raise RuntimeError(f"evo failed: {log}")
    return parse_evo_rmse(process.stdout)


def segmented_evo_rpe(
    evo_dir: Path,
    name: str,
    mode: str,
    stamps: np.ndarray,
    reference_positions: np.ndarray,
    aligned_positions: np.ndarray,
    segments: np.ndarray,
    delta_frames: int,
) -> tuple[float, int]:
    weighted = 0.0
    total = 0
    for segment_id in sorted(set(int(value) for value in segments if value >= 0)):
        indices = np.flatnonzero(segments == segment_id)
        pairs = max(0, len(indices) - delta_frames)
        if not pairs:
            continue
        reference_path = evo_dir / f"reference_segment_{segment_id:03d}.tum"
        estimate_path = evo_dir / f"{name}_{mode}_segment_{segment_id:03d}.tum"
        base.write_identity_tum(reference_path, stamps, reference_positions, indices)
        base.write_identity_tum(estimate_path, stamps, aligned_positions, indices)
        rmse = evo(
            [
                "evo_rpe", "tum", str(reference_path), str(estimate_path),
                "-r", "trans_part", "-d", str(delta_frames), "-u", "f",
                "--all_pairs", "--pairs_from_reference",
            ],
            evo_dir / f"{name}_{mode}_rpe_segment_{segment_id:03d}.log",
        )
        weighted += pairs * rmse * rmse
        total += pairs
    return (math.sqrt(weighted / total) if total else math.nan), total


def run_evo_crosscheck(
    output_dir: Path,
    reference,
    arms,
    evaluation: dict[str, object],
    aligned: dict[str, dict[str, np.ndarray]],
    metrics: dict[str, dict[str, object]],
    rate_hz: float,
) -> dict[str, object]:
    if not shutil.which("evo_ape") or not shutil.which("evo_rpe"):
        raise RuntimeError("evo_ape/evo_rpe are required")
    mask = np.asarray(evaluation["common_mask"], dtype=bool)
    segments = np.asarray(evaluation["segments"], dtype=int)
    indices = np.flatnonzero(mask)
    delta_frames = int(round(rate_hz))
    evo_dir = output_dir / "evo_crosscheck"
    evo_dir.mkdir(parents=True, exist_ok=True)
    reference_path = evo_dir / "reference_common.tum"
    base.write_identity_tum(reference_path, reference.stamps, reference.positions, indices)
    result: dict[str, object] = {"evo_version": "1.31.1", "arms": {}}
    for name, arm in arms.items():
        raw_path = evo_dir / f"{name}_raw_common.tum"
        base.write_identity_tum(raw_path, reference.stamps, arm.positions, indices)
        fixed_ape = evo(
            ["evo_ape", "tum", str(reference_path), str(raw_path), "-a", "-r", "trans_part"],
            evo_dir / f"{name}_fixed_ape.log",
        )
        sim3_ape = evo(
            ["evo_ape", "tum", str(reference_path), str(raw_path), "-a", "-s", "-r", "trans_part"],
            evo_dir / f"{name}_sim3_ape.log",
        )
        mode_result: dict[str, object] = {}
        for mode in ("fixed_se3", "sim3"):
            full = np.full_like(reference.positions, np.nan, dtype=float)
            full[mask] = aligned[name][mode]
            rpe, pair_count = segmented_evo_rpe(
                evo_dir, name, mode, reference.stamps, reference.positions,
                full, segments, delta_frames,
            )
            primary_ape = float(metrics[name][f"{mode}_ape_rmse_m"])
            primary_rpe = float(metrics[name][f"{mode}_rpe_rmse_m"])
            evo_ape_value = fixed_ape if mode == "fixed_se3" else sim3_ape
            mode_result[mode] = {
                "primary_ape_rmse_m": primary_ape,
                "evo_ape_rmse_m": evo_ape_value,
                "ape_abs_diff_m": abs(primary_ape - evo_ape_value),
                "primary_rpe_rmse_m": primary_rpe,
                "evo_segmented_rpe_rmse_m": rpe,
                "rpe_abs_diff_m": abs(primary_rpe - rpe),
                "rpe_pair_count": pair_count,
            }
        result["arms"][name] = mode_result
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-bag", required=True)
    parser.add_argument("--reference-topic", required=True)
    parser.add_argument("--arm", action="append", default=[], metavar="NAME=VIO_CSV")
    parser.add_argument("--arm-config", action="append", default=[], metavar="NAME=YAML")
    parser.add_argument("--nominal-reference-rate-hz", type=float, default=1.0)
    parser.add_argument("--max-reference-gap-s", type=float, default=2.5)
    parser.add_argument("--max-estimate-gap-s", type=float, default=0.25)
    parser.add_argument("--evaluation-rate-hz", type=float, default=1.0)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--run-evo", action="store_true")
    args = parser.parse_args()
    arm_paths = base.parse_named_paths(args.arm, "--arm")
    arm_configs = base.parse_named_paths(args.arm_config, "--arm-config")
    if not arm_paths or set(arm_paths) != set(arm_configs):
        raise SystemExit("--arm and --arm-config must name the same nonempty set")

    reference_series = base.load_ros_reference(Path(args.reference_bag), args.reference_topic)
    reference_stamps, _, _, _ = prepare_reference_samples(
        reference_series.stamps, reference_series.positions, reference_series.quaternions_xyzw
    )
    if len(reference_stamps) < 2:
        raise SystemExit("reference contains fewer than two usable poses")
    window_start, window_end = reference_stamps[0], reference_stamps[-1]
    grid = make_uniform_grid(window_start, window_end, args.evaluation_rate_hz)
    reference = resample_trajectory(
        reference_series.stamps, reference_series.positions, grid,
        args.max_reference_gap_s, reference_series.quaternions_xyzw,
        sample_kind="reference",
    )
    arms = {}
    for name, path in arm_paths.items():
        body = base.load_vins_body_csv(path)
        validate_estimate_samples(body.stamps, body.positions, body.quaternions_xyzw)
        sensor_positions, sensor_quaternions = transform_body_poses_to_sensor(
            body.positions, body.quaternions_xyzw, base.load_body_t_sensor(arm_configs[name])
        )
        arms[name] = resample_trajectory(
            body.stamps, sensor_positions, grid, args.max_estimate_gap_s,
            sensor_quaternions, sample_kind="estimate",
        )

    evaluation = evaluate_common_translation(
        reference, arms,
        window_start_s=window_start,
        window_end_s=window_end,
        max_segment_gap_s=max(args.max_reference_gap_s, args.max_estimate_gap_s),
        rpe_delta_s=1.0,
        min_ape_poses=30,
        min_ape_span_s=10.0,
        min_common_coverage=0.70,
        min_rpe_pairs=10,
    )
    mask = np.asarray(evaluation["common_mask"], dtype=bool)
    pairs_global = np.asarray(evaluation["rpe_pair_indices"], dtype=int)
    common_global = np.flatnonzero(mask)
    global_to_common = {int(value): index for index, value in enumerate(common_global)}
    pairs = np.asarray(
        [(global_to_common[int(left)], global_to_common[int(right)]) for left, right in pairs_global],
        dtype=int,
    ).reshape((-1, 2))
    reference_common = reference.positions[mask]
    fixed_metrics = evaluation["arms"]
    metrics: dict[str, dict[str, object]] = {}
    aligned: dict[str, dict[str, np.ndarray]] = {}
    for name, arm in arms.items():
        fixed_aligned = base.align_se3_positions(arm.positions[mask], reference_common)
        sim3_aligned, scale = align_sim3_positions(arm.positions[mask], reference_common)
        fixed = fixed_metrics[name]
        sim3 = error_metrics(sim3_aligned, reference_common, pairs)
        metrics[name] = {
            "matched_count": int(evaluation["support"]["matched_count"]),
            "rpe_pairs": int(evaluation["support"]["rpe_pairs"]),
            "fixed_se3_ape_rmse_m": float(fixed["ape_rmse_m"]),
            "fixed_se3_ape_median_m": float(fixed["ape_median_m"]),
            "fixed_se3_rpe_rmse_m": float(fixed["rpe_rmse_m"]),
            "fixed_se3_rpe_median_m": float(fixed["rpe_median_m"]),
            "sim3_scale": scale,
            "sim3_ape_rmse_m": sim3["ape_rmse_m"],
            "sim3_ape_median_m": sim3["ape_median_m"],
            "sim3_rpe_rmse_m": sim3["rpe_rmse_m"],
            "sim3_rpe_median_m": sim3["rpe_median_m"],
        }
        aligned[name] = {"fixed_se3": fixed_aligned, "sim3": sim3_aligned}

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "protocol": {
            "evaluation_rate_hz": args.evaluation_rate_hz,
            "rpe_delta_s": 1.0,
            "primary_alignment": "independent proper SE(3), fixed scale",
            "secondary_alignment": "independent proper Sim(3), fitted scale reported",
            "reference": f"{args.reference_bag}:{args.reference_topic}",
        },
        "support": evaluation["support"],
        "arms": metrics,
    }
    (output_dir / "common_support_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (output_dir / "common_support_metrics.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["arm", *next(iter(metrics.values())).keys()])
        writer.writeheader()
        for name, row in metrics.items():
            writer.writerow({"arm": name, **row})
    base.write_grid_audit(output_dir / "common_grid_audit.csv", reference, arms, evaluation)
    if args.run_evo:
        evo_result = run_evo_crosscheck(
            output_dir, reference, arms, evaluation, aligned, metrics, args.evaluation_rate_hz
        )
        (output_dir / "evo_crosscheck.json").write_text(
            json.dumps(evo_result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    print(json.dumps({"support": evaluation["support"], "output": str(output_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
