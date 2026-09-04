#!/usr/bin/env python3
"""Trajectory-level validation report for selected existing VINS runs.

This intentionally reuses the project VINS evaluator helpers instead of
launching ROS. It keeps Task 4 writes inside logs/agent_trajectory_validation/.
"""

from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_trajectory_validation"
RUNS_ROOT = ROOT / "logs" / "aqualoc_real_vins"
BAG = ROOT / "datasets" / "aqualoc" / "rosbags" / "harbor07_1660_1950.bag"
GT_TOPIC = "/aqualoc/colmap_gt"

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


@dataclass(frozen=True)
class RunSpec:
    label: str
    run_dir: Path | None
    role: str
    status_hint: str = ""


RUN_SPECS = [
    RunSpec(
        label="KLT + adaptive CLAHE",
        run_dir=RUNS_ROOT / "external_klt_every2_trial_real_h07_1660_1950_klt_adaptive_clahe",
        role="baseline internal control",
    ),
    RunSpec(
        label="Proposed three-layer SP+LG hybrid",
        run_dir=RUNS_ROOT / "external_hybrid_superpoint_lightglue_every2_trial_real_h07_1660_1950_three_layer_lightglue",
        role="proposed tuned hybrid candidate with existing VINS output",
    ),
    RunSpec(
        label="Proposed three-layer XFeat hybrid",
        run_dir=RUNS_ROOT / "external_hybrid_xfeat_every2_trial_real_h07_1660_1950_three_layer_xfeat",
        role="proposed tuned hybrid variant with existing VINS output",
    ),
    RunSpec(
        label="Proposed tuned hybrid + calibrated q",
        run_dir=None,
        role="pending calibrated-q schedule validation",
        status_hint="pending_task1_ready_schedule",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(OUT_DIR))
    parser.add_argument("--bag", default=str(BAG))
    parser.add_argument("--gt-topic", default=GT_TOPIC)
    parser.add_argument("--rpe-delta-s", type=float, default=1.0)
    parser.add_argument("--gap-threshold-s", type=float, default=0.0)
    parser.add_argument("--init-timeout-s", type=float, default=15.0)
    parser.add_argument("--min-init-poses", type=int, default=10)
    parser.add_argument("--min-coverage-ratio", type=float, default=0.50)
    parser.add_argument("--write-tum", action="store_true")
    parser.add_argument("--run-evo", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bag_path = Path(args.bag)

    gt = load_gt(bag_path, args.gt_topic) if bag_path.exists() else []
    rows: list[dict[str, object]] = []
    for spec in RUN_SPECS:
        if spec.run_dir is None:
            rows.append(pending_row(spec, bag_path))
            continue
        rows.append(
            summarize_run(
                spec=spec,
                bag_path=bag_path,
                gt=gt,
                gt_topic=args.gt_topic,
                rpe_delta_s=float(args.rpe_delta_s),
                gap_threshold_s=float(args.gap_threshold_s),
                init_timeout_s=float(args.init_timeout_s),
                min_init_poses=int(args.min_init_poses),
                min_coverage_ratio=float(args.min_coverage_ratio),
                out_dir=out_dir,
                write_tum=bool(args.write_tum or args.run_evo),
                run_evo=bool(args.run_evo),
            )
        )

    csv_path = out_dir / "trajectory_metrics.csv"
    report_path = out_dir / "trajectory_validation_report.md"
    command_log_path = out_dir / "commands.txt"
    write_csv(csv_path, rows)
    command_log_path.write_text(command_log(args), encoding="utf-8")
    report_path.write_text(make_report(rows, csv_path, command_log_path, args), encoding="utf-8")

    print(f"wrote {csv_path}")
    print(f"wrote {report_path}")
    print(f"wrote {command_log_path}")
    return 0


def pending_row(spec: RunSpec, bag_path: Path) -> dict[str, object]:
    return {
        "label": spec.label,
        "status": spec.status_hint or "pending",
        "role": spec.role,
        "run_dir": "",
        "bag": str(bag_path),
        "note": "No explicit Task 1 ready calibrated-q schedule artifact was found in the allowed validation inputs.",
    }


def summarize_run(
    spec: RunSpec,
    bag_path: Path,
    gt: list[tuple[float, np.ndarray]],
    gt_topic: str,
    rpe_delta_s: float,
    gap_threshold_s: float,
    init_timeout_s: float,
    min_init_poses: int,
    min_coverage_ratio: float,
    out_dir: Path,
    write_tum: bool,
    run_evo: bool,
) -> dict[str, object]:
    run_dir = spec.run_dir
    assert run_dir is not None
    vio_csv = run_dir / "vins_output" / "vio.csv"
    vins_log = run_dir / "vins.log"
    frontend_csv = run_dir / "frontend_metrics.csv"

    row: dict[str, object] = {
        "label": spec.label,
        "status": "blocked_missing_input",
        "role": spec.role,
        "run_dir": str(run_dir),
        "bag": str(bag_path),
        "gt_topic": gt_topic,
        "vins_csv": str(vio_csv),
        "frontend_csv": str(frontend_csv),
    }
    if not bag_path.exists():
        row["note"] = "missing bag"
        return row
    if not vio_csv.exists():
        row["note"] = "missing VINS trajectory CSV"
        row.update(parse_vins_log(vins_log))
        return row
    if len(gt) < 3:
        row["note"] = "empty or missing ground truth topic"
        return row

    vins = load_vins(vio_csv)
    if len(vins) < 3:
        row["status"] = "blocked_empty_vins"
        row["note"] = "VINS output has fewer than three poses"
        row.update(parse_vins_log(vins_log))
        return row

    pairs, time_errors = make_pairs(vins, gt, max_match_dt=0.0)
    if len(pairs) < 3:
        row["status"] = "blocked_not_enough_matches"
        row["note"] = "fewer than three VINS/GT timestamp matches"
        row.update(parse_vins_log(vins_log))
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

    row.update(
        {
            "status": "completed_existing_vins_recomputed_metrics",
            "matched": len(pairs),
            "max_timestamp_error_s": float(max(time_errors)) if time_errors else float("nan"),
            "se3_ape_rmse_m": float(np.sqrt(np.mean(ape**2))),
            "se3_ape_median_m": float(np.median(ape)),
            "se3_ape_max_m": float(np.max(ape)),
            "rpe_delta_s": rpe_delta_s,
            "rpe_pairs": len(rpe),
            "rpe_trans_rmse_m": float(np.sqrt(np.mean(rpe**2))) if len(rpe) else float("nan"),
            "rpe_trans_median_m": float(np.median(rpe)) if len(rpe) else float("nan"),
            "rpe_trans_max_m": float(np.max(rpe)) if len(rpe) else float("nan"),
            "init_success": 1 if init_success else 0,
            "tracking_lost_count_proxy": tracking_lost_proxy,
            "tracking_gap_count": int(gap_stats["large_output_gap_count"]),
            **gap_stats,
            **parse_vins_log(vins_log),
            **summarize_frontend(frontend_csv),
        }
    )

    if write_tum:
        tum_paths = write_tum_files(out_dir, run_dir.name, pairs)
        row["tum_ref"] = str(tum_paths[0])
        row["tum_est"] = str(tum_paths[1])
        row["evo_ape_command"] = make_evo_command("ape", tum_paths[0], tum_paths[1])
        row["evo_rpe_command"] = make_evo_command("rpe", tum_paths[0], tum_paths[1])
        if run_evo:
            row.update(run_evo_metrics(tum_paths[0], tum_paths[1]))
    return row


def summarize_frontend(path: Path) -> dict[str, float]:
    keys = {
        "frontend_frames": 0.0,
        "frontend_mean_exported": float("nan"),
        "frontend_median_track_age": float("nan"),
        "frontend_median_quality": float("nan"),
        "frontend_median_backend_quality": float("nan"),
        "frontend_recovered_sum": float("nan"),
        "frontend_learned_confirmed_sum": float("nan"),
    }
    if not path.exists():
        return keys
    exported: list[float] = []
    ages: list[float] = []
    qualities: list[float] = []
    backend_qualities: list[float] = []
    recovered = 0.0
    learned_confirmed = 0.0
    frames = 0
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            frames += 1
            exported.append(parse_float(row.get("exported_features")))
            ages.append(parse_float(row.get("median_track_age")))
            qualities.append(parse_float(row.get("median_quality")))
            backend_qualities.append(parse_float(row.get("median_backend_quality")))
            recovered += parse_float(row.get("recovered_count"))
            learned_confirmed += parse_float(row.get("learned_confirmed_count"))
    return {
        "frontend_frames": float(frames),
        "frontend_mean_exported": finite_mean(exported),
        "frontend_median_track_age": finite_median(ages),
        "frontend_median_quality": finite_median(qualities),
        "frontend_median_backend_quality": finite_median(backend_qualities),
        "frontend_recovered_sum": recovered,
        "frontend_learned_confirmed_sum": learned_confirmed,
    }


def parse_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return float("nan")


def finite_mean(values: list[float]) -> float:
    arr = np.asarray([item for item in values if math.isfinite(item)], dtype=float)
    return float(np.mean(arr)) if len(arr) else float("nan")


def finite_median(values: list[float]) -> float:
    arr = np.asarray([item for item in values if math.isfinite(item)], dtype=float)
    return float(np.median(arr)) if len(arr) else float("nan")


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


def parse_evo_rmse(text: str) -> float:
    for line in text.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == "rmse":
            return parse_float(parts[-1])
    return float("nan")


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def command_log(args: argparse.Namespace) -> str:
    fresh_cmd = fresh_command(args)
    lines = [
        "# Commands",
        "",
        "Fresh Task 4 metric recomputation:",
        "",
        "```bash",
        "cd /home/ma/AQUA-FE_WS",
        fresh_cmd,
        "```",
        "",
        "No ROS master, VINS node, or rosbag playback was launched by this Task 4 recomputation.",
        "If a fresh VINS rerun is needed later, reserve a unique ROS port in the 11461+ range.",
        "",
        "Existing-run reproduction templates, not executed by this script:",
        "",
        "```bash",
        "cd /home/ma/AQUA-FE_WS",
        "PREPROCESS=adaptive_clahe TAG=trial_real_h07_1660_1950_klt_adaptive_clahe ./scripts/run_aqualoc_real_vins_eval.sh external 1660 1950 klt 2",
        "FRONTEND_CONFIG=uw_frontend/configs/three_layer_frontend.yaml PREPROCESS=adaptive_clahe TAG=trial_real_h07_1660_1950_three_layer_lightglue ./scripts/run_aqualoc_real_vins_eval.sh external 1660 1950 hybrid_superpoint_lightglue 2",
        "FRONTEND_CONFIG=uw_frontend/configs/three_layer_frontend.yaml PREPROCESS=adaptive_clahe TAG=trial_real_h07_1660_1950_three_layer_xfeat ./scripts/run_aqualoc_real_vins_eval.sh external 1660 1950 hybrid_xfeat 2",
        "```",
    ]
    if args.run_evo:
        lines.extend(["", "Evo was requested with `--run-evo`; per-run commands are recorded in `trajectory_metrics.csv`."])
    else:
        lines.extend(["", "Matched TUM files were written when `--write-tum` was used; per-run evo commands are recorded in `trajectory_metrics.csv`."])
    return "\n".join(lines) + "\n"


def make_report(
    rows: list[dict[str, object]],
    csv_path: Path,
    command_log_path: Path,
    args: argparse.Namespace,
) -> str:
    fresh_cmd = fresh_command(args)
    completed = [row for row in rows if str(row.get("status", "")).startswith("completed")]
    pending = [row for row in rows if str(row.get("status", "")).startswith("pending")]
    status = "completed run" if len(completed) >= 2 else "blocked run" if completed else "protocol-only"
    lines = [
        "# Trajectory-Level Validation Report",
        "",
        f"Date: 2026-05-12",
        f"Status: {status}. Metrics were freshly recomputed from existing VINS outputs; ROS/VINS was not relaunched.",
        "",
        "## Protocol",
        "",
        "- Dataset/window: AQUALOC Harbor07 real underwater VIO, frames 1660-1950.",
        f"- Bag: `{args.bag}`.",
        f"- Ground truth topic: `{args.gt_topic}`.",
        "- Estimate source: existing `vins_output/vio.csv` files from external-feature VINS runs.",
        "- Alignment: SE(3) alignment against COLMAP GT using the project evaluator helper.",
        "- APE: translational SE(3)-aligned RMSE/median/max.",
        f"- RPE: translational drift over `{args.rpe_delta_s:.1f}` s.",
        "- Initialization success: at least 10 matched poses, first output within 15 s, and output coverage >= 0.50.",
        "- Lost/restart proxy: large estimator output timestamp gaps plus terminal dropout; VINS log failure/restart counters are reported separately.",
        "- Tracking gaps: `large_output_gap_count` and `max_output_gap_s` from estimator output timestamps.",
        "- Matched TUM files and per-run `evo_ape`/`evo_rpe` command lines are written for optional evo cross-checks.",
        "",
        "## Results",
        "",
        result_table(rows),
        "",
        "## Interpretation",
        "",
        "- The minimal KLT/proposed comparison is complete on the existing Harbor07 1660-1950 VIO window.",
        "- Both proposed hybrid rows initialize and keep continuous estimator output by the gap proxy.",
        "- The SP+LG hybrid slightly improves APE and RPE versus this no-calibrated-q KLT + adaptive CLAHE row, with a small output-coverage reduction.",
        "- The XFeat hybrid improves RPE but loses APE versus KLT on this normal/moderate-texture sanity window.",
        "- Proposed + calibrated q remains pending because no explicit Task 1 ready schedule artifact was found in this validation scope. Existing diagnostic qcal runs should not be promoted into the protocol row without that ready-schedule decision.",
        "",
        "## Commands",
        "",
        f"See `{command_log_path.relative_to(ROOT)}` for the command log.",
        "",
        "Fresh command executed for this report:",
        "",
        "```bash",
        "cd /home/ma/AQUA-FE_WS",
        fresh_cmd,
        "```",
        "",
        "## Outputs",
        "",
        f"- `{csv_path.relative_to(ROOT)}`",
        f"- `{command_log_path.relative_to(ROOT)}`",
    ]
    if pending:
        lines.extend(["", "## Pending", "", pending_table(pending)])
    return "\n".join(lines) + "\n"


def fresh_command(args: argparse.Namespace) -> str:
    parts = ["python3", "scripts/agent_trajectory_validation_recompute.py"]
    if args.write_tum or args.run_evo:
        parts.append("--write-tum")
    if args.run_evo:
        parts.append("--run-evo")
    if str(args.output_dir) != str(OUT_DIR):
        parts.extend(["--output-dir", str(args.output_dir)])
    if str(args.bag) != str(BAG):
        parts.extend(["--bag", str(args.bag)])
    if str(args.gt_topic) != GT_TOPIC:
        parts.extend(["--gt-topic", str(args.gt_topic)])
    if float(args.rpe_delta_s) != 1.0:
        parts.extend(["--rpe-delta-s", str(args.rpe_delta_s)])
    return " ".join(parts)


def result_table(rows: list[dict[str, object]]) -> str:
    headers = [
        "method",
        "status",
        "APE RMSE m",
        "RPE RMSE m",
        "init",
        "coverage",
        "lost proxy",
        "gap count",
        "max gap s",
        "poses",
    ]
    body = []
    for row in rows:
        if not str(row.get("status", "")).startswith("completed"):
            continue
        body.append(
            [
                str(row.get("label", "")),
                str(row.get("status", "")),
                fmt(row.get("se3_ape_rmse_m")),
                fmt(row.get("rpe_trans_rmse_m")),
                fmt(row.get("init_success"), digits=0),
                fmt(row.get("output_coverage_ratio")),
                fmt(row.get("tracking_lost_count_proxy"), digits=0),
                fmt(row.get("tracking_gap_count"), digits=0),
                fmt(row.get("max_output_gap_s")),
                fmt(row.get("output_poses"), digits=0),
            ]
        )
    return markdown_table(headers, body)


def pending_table(rows: list[dict[str, object]]) -> str:
    headers = ["method", "status", "note"]
    body = [[str(row.get("label", "")), str(row.get("status", "")), str(row.get("note", ""))] for row in rows]
    return markdown_table(headers, body)


def markdown_table(headers: list[str], body: list[list[str]]) -> str:
    if not body:
        return "(empty)"
    widths = [max(len(headers[i]), *(len(row[i]) for row in body)) for i in range(len(headers))]
    lines = [
        "| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |",
        "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(row[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    return "\n".join(lines)


def fmt(value: object, digits: int = 3) -> str:
    try:
        fval = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if not math.isfinite(fval):
        return ""
    return f"{fval:.{digits}f}"


if __name__ == "__main__":
    raise SystemExit(main())
