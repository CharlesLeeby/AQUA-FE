#!/usr/bin/env python3
"""Summarize balanced MSCKF-DVIO full/drop/KLT replay rounds."""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path


ROLES = ("full", "drop", "klt")


def parse_metrics(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def as_float(values: dict[str, str], key: str) -> float:
    try:
        return float(values[key])
    except (KeyError, TypeError, ValueError):
        return float("nan")


def median(rows: list[dict[str, object]], key: str) -> float:
    values = [float(row[key]) for row in rows if math.isfinite(float(row[key]))]
    return statistics.median(values) if values else float("nan")


def fmt(value: float, digits: int = 6) -> str:
    return "nan" if not math.isfinite(value) else f"{value:.{digits}f}"


def improvement(baseline: float, proposed: float) -> float:
    if not math.isfinite(baseline) or not math.isfinite(proposed) or baseline == 0.0:
        return float("nan")
    return 100.0 * (baseline - proposed) / baseline


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-report", required=True)
    args = parser.parse_args()

    run_root = Path(args.run_root).resolve()
    rows: list[dict[str, object]] = []
    for round_index in range(1, args.rounds + 1):
        for role in ROLES:
            run_dir = run_root / f"round_{round_index:02d}_{role}"
            metrics = parse_metrics(run_dir / "metrics.txt")
            estimator_log = run_dir / "estimator.log"
            log_text = (
                estimator_log.read_text(encoding="utf-8", errors="replace")
                if estimator_log.is_file()
                else ""
            )
            row: dict[str, object] = {
                "round": round_index,
                "role": role,
                "run_dir": str(run_dir),
                "complete": int(bool(metrics)),
                "ape_rmse_m": as_float(metrics, "se3_ape_rmse_m"),
                "rpe_rmse_m": as_float(metrics, "rpe_trans_rmse_m"),
                "coverage": as_float(metrics, "output_coverage_ratio"),
                "output_poses": as_float(metrics, "output_poses"),
                "init_success": int(as_float(metrics, "init_success") == 1.0),
                "linear_solver_failures": int(
                    as_float(metrics, "log_linear_solver_failures")
                    if math.isfinite(as_float(metrics, "log_linear_solver_failures"))
                    else -1
                ),
                "chi2_rejections": log_text.count("chi2 failed:"),
            }
            row["hard_failure"] = int(
                not row["complete"]
                or not row["init_success"]
                or int(row["linear_solver_failures"]) != 0
            )
            rows.append(row)

    output_csv = Path(args.output_csv).resolve()
    output_report = Path(args.output_report).resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_report.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    by_role = {role: [row for row in rows if row["role"] == role] for role in ROLES}
    medians = {
        role: {
            "ape": median(by_role[role], "ape_rmse_m"),
            "rpe": median(by_role[role], "rpe_rmse_m"),
            "coverage": median(by_role[role], "coverage"),
            "chi2": median(by_role[role], "chi2_rejections"),
        }
        for role in ROLES
    }

    wins: dict[str, dict[str, int]] = {}
    for baseline in ("drop", "klt"):
        wins[baseline] = {"ape": 0, "rpe": 0, "dual": 0, "comparable": 0}
        for round_index in range(1, args.rounds + 1):
            full = next(
                row
                for row in rows
                if row["round"] == round_index and row["role"] == "full"
            )
            control = next(
                row
                for row in rows
                if row["round"] == round_index and row["role"] == baseline
            )
            values = [
                float(full["ape_rmse_m"]),
                float(full["rpe_rmse_m"]),
                float(control["ape_rmse_m"]),
                float(control["rpe_rmse_m"]),
            ]
            if int(full["hard_failure"]) or int(control["hard_failure"]) or not all(
                math.isfinite(value) for value in values
            ):
                continue
            wins[baseline]["comparable"] += 1
            ape_win = values[0] < values[2]
            rpe_win = values[1] < values[3]
            wins[baseline]["ape"] += int(ape_win)
            wins[baseline]["rpe"] += int(rpe_win)
            wins[baseline]["dual"] += int(ape_win and rpe_win)

    lines = [
        "# MSCKF-DVIO 三路复跑汇总",
        "",
        "| 方法 | APE 中位数 (m) | RPE 中位数 (m) | coverage 中位数 | chi2 拒绝中位数 | hard failure |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for role in ROLES:
        hard_failures = sum(int(row["hard_failure"]) for row in by_role[role])
        lines.append(
            f"| {role} | {fmt(medians[role]['ape'])} | {fmt(medians[role]['rpe'])} | "
            f"{fmt(medians[role]['coverage'])} | {fmt(medians[role]['chi2'], 1)} | "
            f"{hard_failures}/{args.rounds} |"
        )
    lines.extend(
        [
            "",
            "| 比较 | APE 胜 | RPE 胜 | 双指标胜 | APE 中位改善 | RPE 中位改善 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for baseline in ("drop", "klt"):
        comparable = wins[baseline]["comparable"]
        lines.append(
            f"| full vs {baseline} | {wins[baseline]['ape']}/{comparable} | "
            f"{wins[baseline]['rpe']}/{comparable} | {wins[baseline]['dual']}/{comparable} | "
            f"{fmt(improvement(medians[baseline]['ape'], medians['full']['ape']), 3)}% | "
            f"{fmt(improvement(medians[baseline]['rpe'], medians['full']['rpe']), 3)}% |"
        )
    lines.extend(["", f"逐轮数据：`{output_csv}`。", ""])
    output_report.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
