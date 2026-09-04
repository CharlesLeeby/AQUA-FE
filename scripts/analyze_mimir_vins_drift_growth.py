#!/usr/bin/env python3
"""Diagnose when a MIMIR-UW VINS trajectory starts to drift.

The report deliberately separates full-run SE(3) APE from per-bin, locally
aligned shape error and from metric path-length scale.  A low local APE with a
large path ratio indicates a metric-scale failure; a growing local APE points
to deformation/drift inside the sliding-window estimate.
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

import numpy as np

from evaluate_vins_sim_ape import align_se3, compute_rpe, load_gt, load_vins, make_pairs


def path_length(points: np.ndarray) -> float:
    if len(points) < 2:
        return 0.0
    return float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum())


def rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(values)))) if len(values) else float("nan")


def analyze_run(
    label: str,
    vins_csv: Path,
    bag: Path,
    gt_topic: str,
    bin_s: float,
    rpe_delta_s: float,
) -> list[dict[str, object]]:
    pairs, _ = make_pairs(load_vins(vins_csv), load_gt(bag, gt_topic), 0.0)
    if len(pairs) < 3:
        raise RuntimeError(f"{label}: fewer than three associated poses")

    stamps = np.asarray([item[0] for item in pairs], dtype=float)
    estimate = np.stack([item[1] for item in pairs])
    reference = np.stack([item[2] for item in pairs])
    full_aligned = align_se3(estimate, reference)
    full_errors = np.linalg.norm(full_aligned - reference, axis=1)
    full_ape = rmse(full_errors)
    t0 = float(stamps[0])
    duration = float(stamps[-1] - t0)
    relative_t = stamps - t0
    position_error = full_aligned - reference
    quadratic_design = np.column_stack(
        [np.ones(len(relative_t)), relative_t, 0.5 * relative_t * relative_t]
    )
    quadratic_coefficients = np.linalg.lstsq(
        quadratic_design, position_error, rcond=None
    )[0]
    quadratic_prediction = quadratic_design @ quadratic_coefficients
    residual_energy = float(np.square(position_error - quadratic_prediction).sum())
    total_energy = float(np.square(position_error - position_error.mean(axis=0)).sum())
    quadratic_r2 = 1.0 - residual_energy / total_energy if total_energy > 0.0 else float("nan")

    rows: list[dict[str, object]] = []
    for bin_index, lo_rel in enumerate(np.arange(0.0, duration + 1e-9, bin_s)):
        hi_rel = min(duration, float(lo_rel + bin_s))
        final_bin = math.isclose(hi_rel, duration)
        mask = (stamps >= t0 + lo_rel) & (
            stamps <= t0 + hi_rel if final_bin else stamps < t0 + hi_rel
        )
        if int(mask.sum()) < 3:
            continue
        seg_t = stamps[mask]
        seg_est = estimate[mask]
        seg_ref = reference[mask]
        seg_full_aligned = full_aligned[mask]
        local_aligned = align_se3(seg_est, seg_ref)
        est_length = path_length(seg_est)
        ref_length = path_length(seg_ref)
        # Match the project evaluator: RPE is computed after the one full-run
        # rigid alignment.  Translation increments are rotation-sensitive, so
        # using the raw estimator axes here would report a spurious frame-axis
        # error instead of drift.
        rpe = compute_rpe(seg_t, seg_full_aligned, seg_ref, rpe_delta_s)
        dt = np.diff(seg_t)
        est_speed = np.linalg.norm(np.diff(seg_est, axis=0), axis=1) / dt
        ref_speed = np.linalg.norm(np.diff(seg_ref, axis=0), axis=1) / dt
        rows.append(
            {
                "run": label,
                "bin": bin_index,
                "start_s_rel": float(lo_rel),
                "end_s_rel": hi_rel,
                "poses": int(mask.sum()),
                "full_run_ape_rmse_m": full_ape,
                "quadratic_error_accel_norm_mps2": float(
                    np.linalg.norm(quadratic_coefficients[2])
                ),
                "quadratic_error_velocity_norm_mps": float(
                    np.linalg.norm(quadratic_coefficients[1])
                ),
                "quadratic_error_fit_r2": quadratic_r2,
                "global_alignment_bin_ape_rmse_m": rmse(
                    np.linalg.norm(seg_full_aligned - seg_ref, axis=1)
                ),
                "local_alignment_bin_ape_rmse_m": rmse(
                    np.linalg.norm(local_aligned - seg_ref, axis=1)
                ),
                "rpe_1s_rmse_m": rmse(rpe),
                "estimate_path_m": est_length,
                "reference_path_m": ref_length,
                "path_ratio": est_length / ref_length if ref_length > 0.0 else float("nan"),
                "estimate_speed_median_mps": float(np.median(est_speed)),
                "reference_speed_median_mps": float(np.median(ref_speed)),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        nargs=3,
        action="append",
        metavar=("LABEL", "VINS_CSV", "BAG"),
        required=True,
    )
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--gt-topic", default="/mimir/ground_truth")
    parser.add_argument("--bin-s", type=float, default=5.0)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    args = parser.parse_args()

    rows: list[dict[str, object]] = []
    for label, vins_csv, bag in args.run:
        rows.extend(
            analyze_run(
                label,
                Path(vins_csv),
                Path(bag),
                args.gt_topic,
                args.bin_s,
                args.rpe_delta_s,
            )
        )
    output = Path(args.output_csv)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
