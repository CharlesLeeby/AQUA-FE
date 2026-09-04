#!/usr/bin/env python3
"""Summarize VINS-Fusion trajectory robustness metrics for existing run dirs."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_vins_sim_ape import (  # noqa: E402
    align_se3,
    compute_rpe,
    load_gt,
    load_vins,
    make_pairs,
    parse_vins_log,
    trajectory_gap_stats,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", default="logs/aqualoc_real_vins")
    parser.add_argument("--bag-dir", default="datasets/aqualoc/rosbags")
    parser.add_argument("--gt-topic", default="/aqualoc/colmap_gt")
    parser.add_argument("--output-csv", default="logs/aqualoc_real_vins/trajectory_robustness_summary.csv")
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--max-match-dt", type=float, default=0.0)
    parser.add_argument("--gap-threshold-s", type=float, default=0.0)
    parser.add_argument("--init-timeout-s", type=float, default=15.0)
    parser.add_argument("--min-init-poses", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.50)
    args = parser.parse_args()

    runs_root = Path(args.runs_root)
    bag_dir = Path(args.bag_dir)
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    gt_cache: dict[Path, list[tuple[float, np.ndarray]]] = {}
    rows = []
    for vio_csv in sorted(runs_root.glob("*/vins_output/vio.csv")):
        run_dir = vio_csv.parents[1]
        bag_path = infer_aqualoc_bag(run_dir.name, bag_dir)
        row = summarize_run(
            run_dir=run_dir,
            vio_csv=vio_csv,
            bag_path=bag_path,
            gt_topic=args.gt_topic,
            gt_cache=gt_cache,
            rpe_delta_s=float(args.rpe_delta_s),
            max_match_dt=float(args.max_match_dt),
            gap_threshold_s=float(args.gap_threshold_s),
            init_timeout_s=float(args.init_timeout_s),
            min_init_poses=int(args.min_init_poses),
            min_coverage_ratio=float(args.min_coverage_ratio),
        )
        rows.append(row)

    fieldnames = [
        "run",
        "status",
        "bag",
        "mode",
        "method",
        "window",
        "matched",
        "se3_ape_rmse_m",
        "se3_ape_median_m",
        "se3_ape_max_m",
        "rpe_delta_s",
        "rpe_pairs",
        "rpe_trans_rmse_m",
        "rpe_trans_median_m",
        "rpe_trans_max_m",
        "output_poses",
        "output_duration_s",
        "expected_duration_s",
        "output_coverage_ratio",
        "first_output_delay_s",
        "last_output_drop_s",
        "median_output_dt_s",
        "max_output_gap_s",
        "large_output_gap_count",
        "init_success",
        "tracking_lost_count_proxy",
        "log_linear_solver_failures",
        "log_failure_mentions",
        "log_restart_mentions",
        "log_waiting_mentions",
        "frontend_mean_exported",
        "frontend_median_backend_quality",
        "frontend_learned_confirmed_sum",
        "frontend_recovered_sum",
        "frontend_exported_learned_sum",
        "frontend_exported_non_loftr_learned_sum",
        "frontend_exported_sp_lg_sum",
        "frontend_exported_xfeat_sum",
        "frontend_exported_loftr_sum",
        "frontend_degraded_gate_frames",
        "frontend_init_klt_only_frames",
        "frontend_gate_reasons",
        "frontend_benefit_reasons",
        "frontend_geometry_reasons",
    ]
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
    print(f"wrote {output_csv}")
    print(f"runs={len(rows)}")
    ok_rows = [row for row in rows if row.get("status") == "ok"]
    print(f"ok={len(ok_rows)} failed={len(rows) - len(ok_rows)}")
    if ok_rows:
        best = sorted(ok_rows, key=lambda row: float(row["se3_ape_rmse_m"]))[:8]
        print("best_by_ape:")
        for row in best:
            print(
                f"{row['se3_ape_rmse_m']:.6f} "
                f"rpe={row['rpe_trans_rmse_m']:.6f} "
                f"lost={row['tracking_lost_count_proxy']} "
                f"{row['run']}"
            )
    return 0


def infer_aqualoc_bag(run_name: str, bag_dir: Path) -> Path | None:
    match = re.search(r"h07_(\d+)_(\d+)", run_name)
    if match:
        return bag_dir / f"harbor07_{match.group(1)}_{match.group(2)}.bag"
    match = re.search(r"a(0[5-9]|10)_(\d+)_(\d+)", run_name)
    if match:
        return bag_dir / f"archaeo{match.group(1)}_{match.group(2)}_{match.group(3)}.bag"
    shorthand = {
        "a05": "archaeo05_2800_3300.bag",
        "a06": "archaeo06_2100_2550.bag",
        "a08": "archaeo08_4480_4680.bag",
        "a09": "archaeo09_5800_6200.bag",
    }
    for token, bag_name in shorthand.items():
        if re.search(rf"(?:^|_){token}(?:_|$)", run_name):
            return bag_dir / bag_name
    return None


def summarize_run(
    run_dir: Path,
    vio_csv: Path,
    bag_path: Path | None,
    gt_topic: str,
    gt_cache: dict[Path, list[tuple[float, np.ndarray]]],
    rpe_delta_s: float,
    max_match_dt: float,
    gap_threshold_s: float,
    init_timeout_s: float,
    min_init_poses: int,
    min_coverage_ratio: float,
) -> dict[str, object]:
    row: dict[str, object] = {
        "run": run_dir.name,
        "mode": run_dir.name.split("_", 1)[0],
        "method": infer_method(run_dir.name),
        "window": infer_window(run_dir.name),
        "bag": "" if bag_path is None else str(bag_path),
    }
    if bag_path is None or not bag_path.exists():
        row.update({"status": "missing_bag"})
        return row
    vins = load_vins(vio_csv)
    if len(vins) < 3:
        row.update({"status": "empty_vins", **parse_vins_log(run_dir / "vins.log")})
        return row
    if bag_path not in gt_cache:
        gt_cache[bag_path] = load_gt(bag_path, gt_topic)
    gt = gt_cache[bag_path]
    if len(gt) < 3:
        row.update({"status": "empty_gt"})
        return row

    pairs, time_errors = make_pairs(vins, gt, max_match_dt=max_match_dt)
    if len(pairs) < 3:
        row.update({"status": "not_enough_matches"})
        return row
    stamps = np.asarray([item[0] for item in pairs], dtype=float)
    source = np.stack([item[1] for item in pairs])
    target = np.stack([item[2] for item in pairs])
    aligned = align_se3(source, target)
    ape = np.linalg.norm(aligned - target, axis=1)
    rpe = compute_rpe(stamps, aligned, target, delta_s=rpe_delta_s)
    gap_stats = trajectory_gap_stats(vins, gt, gap_threshold_s=gap_threshold_s)
    terminal_drop_count = 1 if gap_stats["last_output_drop_s"] > max(1.0, gap_threshold_s) else 0
    tracking_lost_proxy = int(gap_stats["large_output_gap_count"]) + terminal_drop_count
    init_success = (
        len(pairs) >= min_init_poses
        and gap_stats["first_output_delay_s"] <= init_timeout_s
        and gap_stats["output_coverage_ratio"] >= min_coverage_ratio
    )
    frontend_stats = summarize_frontend_metrics(run_dir / "frontend_metrics.csv")
    row.update(
        {
            "status": "ok",
            "matched": len(pairs),
            "se3_ape_rmse_m": float(np.sqrt(np.mean(ape**2))),
            "se3_ape_median_m": float(np.median(ape)),
            "se3_ape_max_m": float(np.max(ape)),
            "max_timestamp_error_s": float(max(time_errors)) if time_errors else float("nan"),
            "rpe_delta_s": rpe_delta_s,
            "rpe_pairs": len(rpe),
            "rpe_trans_rmse_m": float(np.sqrt(np.mean(rpe**2))) if len(rpe) else float("nan"),
            "rpe_trans_median_m": float(np.median(rpe)) if len(rpe) else float("nan"),
            "rpe_trans_max_m": float(np.max(rpe)) if len(rpe) else float("nan"),
            "init_success": 1 if init_success else 0,
            "tracking_lost_count_proxy": tracking_lost_proxy,
            **gap_stats,
            **parse_vins_log(run_dir / "vins.log"),
            **frontend_stats,
        }
    )
    return row


def infer_method(run_name: str) -> str:
    tokens = [
        "hybrid_superpoint_lightglue",
        "hybrid_xfeat",
        "hybrid_loftr",
        "hybrid",
        "klt",
        "origin",
    ]
    for token in tokens:
        if token in run_name:
            return token
    return "unknown"


def infer_window(run_name: str) -> str:
    match = re.search(r"h07_(\d+)_(\d+)", run_name)
    if not match:
        match = re.search(r"a(?:0[5-9]|10)_(\d+)_(\d+)", run_name)
    if not match:
        return "unknown"
    return f"{match.group(1)}-{match.group(2)}"


def summarize_frontend_metrics(path: Path) -> dict[str, float]:
    empty = {
        "frontend_mean_exported": float("nan"),
        "frontend_median_backend_quality": float("nan"),
        "frontend_learned_confirmed_sum": float("nan"),
        "frontend_recovered_sum": float("nan"),
        "frontend_exported_learned_sum": float("nan"),
        "frontend_exported_non_loftr_learned_sum": float("nan"),
        "frontend_exported_sp_lg_sum": float("nan"),
        "frontend_exported_xfeat_sum": float("nan"),
        "frontend_exported_loftr_sum": float("nan"),
        "frontend_degraded_gate_frames": float("nan"),
        "frontend_init_klt_only_frames": float("nan"),
        "frontend_gate_reasons": "",
        "frontend_benefit_reasons": "",
        "frontend_geometry_reasons": "",
    }
    if not path.exists():
        return empty
    exported = []
    backend_q = []
    learned = 0.0
    recovered = 0.0
    exported_learned = 0.0
    exported_non_loftr_learned = 0.0
    exported_sp_lg = 0.0
    exported_xfeat = 0.0
    exported_loftr = 0.0
    degraded_gate_frames = 0.0
    init_klt_only_frames = 0.0
    gate_reasons: set[str] = set()
    benefit_reasons: set[str] = set()
    geometry_reasons: set[str] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            exported.append(parse_float(row.get("exported_features")))
            backend_q.append(parse_float(row.get("median_backend_quality")))
            learned += parse_float(row.get("learned_confirmed_count"))
            recovered += parse_float(row.get("recovered_count"))
            exported_learned += parse_float(row.get("exported_learned_features"))
            exported_non_loftr_learned += parse_float(row.get("exported_non_loftr_learned_features"))
            exported_sp_lg += parse_float(row.get("exported_sp_lg_features"))
            exported_xfeat += parse_float(row.get("exported_xfeat_features"))
            exported_loftr += parse_float(row.get("exported_loftr_features"))
            degraded_gate_frames += parse_float(row.get("learned_export_gate_degraded"))
            init_klt_only_frames += parse_float(row.get("init_klt_only_active"))
            _add_reason(gate_reasons, row.get("learned_export_gate_reason"))
            _add_reason(benefit_reasons, row.get("learned_export_benefit_reason"))
            _add_reason(geometry_reasons, row.get("learned_export_geometry_reason"))
    exported = [item for item in exported if np.isfinite(item)]
    backend_q = [item for item in backend_q if np.isfinite(item)]
    return {
        "frontend_mean_exported": float(np.mean(exported)) if exported else float("nan"),
        "frontend_median_backend_quality": float(np.median(backend_q)) if backend_q else float("nan"),
        "frontend_learned_confirmed_sum": learned,
        "frontend_recovered_sum": recovered,
        "frontend_exported_learned_sum": exported_learned,
        "frontend_exported_non_loftr_learned_sum": exported_non_loftr_learned,
        "frontend_exported_sp_lg_sum": exported_sp_lg,
        "frontend_exported_xfeat_sum": exported_xfeat,
        "frontend_exported_loftr_sum": exported_loftr,
        "frontend_degraded_gate_frames": degraded_gate_frames,
        "frontend_init_klt_only_frames": init_klt_only_frames,
        "frontend_gate_reasons": "|".join(sorted(gate_reasons)),
        "frontend_benefit_reasons": "|".join(sorted(benefit_reasons)),
        "frontend_geometry_reasons": "|".join(sorted(geometry_reasons)),
    }


def parse_float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _add_reason(reasons: set[str], value: object) -> None:
    text = "" if value is None else str(value).strip()
    if text and text.lower() not in {"nan", "none", "n/a"}:
        reasons.add(text)


if __name__ == "__main__":
    raise SystemExit(main())
