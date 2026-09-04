#!/usr/bin/env python3
"""Segment a VINS trajectory APE report by time.

This uses the same lightweight SE(3) alignment and nearest ground-truth matching
as evaluate_vins_sim_ape.py, then reports APE/RPE on consecutive time bins.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np

from evaluate_vins_sim_ape import align_se3, compute_rpe, load_gt, load_vins, make_pairs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vins-csv", required=True)
    parser.add_argument("--bag", required=True)
    parser.add_argument("--gt-topic", default="/vrpn_client_node/cam0/pose")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--segments", type=int, default=4)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--max-match-dt", type=float, default=0.0)
    args = parser.parse_args()

    vins = load_vins(Path(args.vins_csv))
    gt = load_gt(Path(args.bag), args.gt_topic)
    if not vins:
        raise SystemExit(f"empty VINS trajectory: {args.vins_csv}")
    if not gt:
        raise SystemExit(f"empty GT topic: {args.gt_topic}")
    pairs, _ = make_pairs(vins, gt, args.max_match_dt)
    if len(pairs) < 3:
        raise SystemExit("not enough matched poses")

    stamps = np.asarray([item[0] for item in pairs], dtype=float)
    source = np.stack([item[1] for item in pairs])
    target = np.stack([item[2] for item in pairs])
    aligned = align_se3(source, target)
    errors = np.linalg.norm(aligned - target, axis=1)

    t0 = float(stamps[0])
    t1 = float(stamps[-1])
    bins = np.linspace(t0, t1, int(args.segments) + 1)
    rows = []
    for idx in range(int(args.segments)):
        lo = bins[idx]
        hi = bins[idx + 1]
        mask = (stamps >= lo) & (stamps <= hi if idx == int(args.segments) - 1 else stamps < hi)
        if int(mask.sum()) < 3:
            continue
        seg_stamps = stamps[mask]
        seg_aligned = aligned[mask]
        seg_target = target[mask]
        seg_errors = errors[mask]
        rpe = compute_rpe(seg_stamps, seg_aligned, seg_target, args.rpe_delta_s)
        rows.append(
            {
                "segment": idx,
                "start_s_rel": lo - t0,
                "end_s_rel": hi - t0,
                "poses": int(mask.sum()),
                "ape_rmse_m": float(np.sqrt(np.mean(seg_errors**2))),
                "ape_median_m": float(np.median(seg_errors)),
                "ape_max_m": float(np.max(seg_errors)),
                "rpe_pairs": int(len(rpe)),
                "rpe_rmse_m": float(np.sqrt(np.mean(rpe**2))) if len(rpe) else float("nan"),
                "rpe_median_m": float(np.median(rpe)) if len(rpe) else float("nan"),
            }
        )

    out = Path(args.output_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["segment"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
