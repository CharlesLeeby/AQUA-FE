#!/usr/bin/env python3
"""Build auditable long-form and case-level tables for the frozen evaluation."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path


ARMS = ("full", "drop", "klt")


def read_kv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def number(value: str | None) -> float:
    try:
        result = float(value) if value is not None else math.nan
    except ValueError:
        return math.nan
    return result if math.isfinite(result) else math.nan


def integer(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value)) if value is not None else default
    except ValueError:
        return default


def first_csv_row(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.DictReader(handle), {})


def metric_row(
    case: dict[str, str],
    state: dict[str, str],
    status_dir: Path,
    drop_stats: dict[str, str],
    arm: str,
) -> dict[str, object]:
    run_dir = Path(state.get(f"{arm}_run", ""))
    metrics = read_kv(run_dir / "ape_strict_dt0p6.txt") if str(run_dir) != "." else {}
    ape = number(metrics.get("se3_ape_rmse_m"))
    rpe = number(metrics.get("rpe_trans_rmse_m"))
    coverage = number(metrics.get("output_coverage_ratio"))
    init_success = integer(metrics.get("init_success"), default=0)
    solver_failures = integer(metrics.get("log_linear_solver_failures"), default=0)
    failure_mentions = integer(metrics.get("log_failure_mentions"), default=0)
    evaluation_error = metrics.get("evaluation_error", "")
    evaluation_valid = not evaluation_error and math.isfinite(ape) and math.isfinite(rpe)
    hard_failure = (not evaluation_valid) or init_success == 0 or not math.isfinite(coverage) or coverage < 0.5
    exit_code = integer(
        (status_dir / f"{case['case_id']}.{arm}_exit_code").read_text().strip()
        if (status_dir / f"{case['case_id']}.{arm}_exit_code").exists()
        else None,
        default=-1,
    )
    return {
        "case_id": case["case_id"],
        "cohort": case["cohort"],
        "independent_cluster": case["independent_cluster"],
        "dataset_family": case["dataset_family"],
        "window": case["window"],
        "planned_profile": case["profile"],
        "selected_profile": state.get("profile", ""),
        "fresh_export": case["fresh_export"],
        "arm": arm,
        "run_dir": str(run_dir) if str(run_dir) != "." else "",
        "bag_sha256": state.get(f"{arm}_bag_sha256", ""),
        "exit_code": exit_code,
        "evaluation_valid": int(evaluation_valid),
        "ape_rmse_m": ape,
        "rpe_rmse_m": rpe,
        "coverage_ratio": coverage,
        "init_success": init_success,
        "solver_failure_count": solver_failures,
        "failure_mention_count": failure_mentions,
        "hard_failure": int(hard_failure),
        "solver_risk": int(solver_failures > 0),
        "learned_track_ids": integer(drop_stats.get("learned_track_ids")),
        "dropped_lineage_observations": integer(drop_stats.get("dropped_observations")),
        "notes": case["notes"],
    }


def as_bool(row: dict[str, object], key: str) -> bool:
    return bool(int(row[key]))


def relative_improvement(full: dict[str, object], control: dict[str, object]) -> float:
    if as_bool(full, "hard_failure") or as_bool(control, "hard_failure"):
        return math.nan
    full_ape = float(full["ape_rmse_m"])
    control_ape = float(control["ape_rmse_m"])
    if not math.isfinite(full_ape) or not math.isfinite(control_ape) or control_ape <= 0.0:
        return math.nan
    return (control_ape - full_ape) / control_ape


def control_passes(full: dict[str, object], control: dict[str, object], metric: str) -> bool:
    if as_bool(control, "hard_failure"):
        return True
    return float(full[metric]) <= float(control[metric])


def summarize_case(case: dict[str, str], rows: list[dict[str, object]]) -> dict[str, object]:
    by_arm = {str(row["arm"]): row for row in rows}
    full, drop, klt = (by_arm[arm] for arm in ARMS)
    full_ok = not as_bool(full, "hard_failure")
    ape_win = full_ok and control_passes(full, drop, "ape_rmse_m") and control_passes(full, klt, "ape_rmse_m")
    dual_win = (
        ape_win
        and control_passes(full, drop, "rpe_rmse_m")
        and control_passes(full, klt, "rpe_rmse_m")
    )
    klt_rescue = full_ok and as_bool(klt, "hard_failure")
    drop_rescue = full_ok and as_bool(drop, "hard_failure")
    learned_active = int(full["learned_track_ids"]) > 0
    strict_better_klt = (
        full_ok
        and not as_bool(klt, "hard_failure")
        and float(full["ape_rmse_m"]) < float(klt["ape_rmse_m"])
    )
    strict_better_drop = (
        full_ok
        and not as_bool(drop, "hard_failure")
        and float(full["ape_rmse_m"]) < float(drop["ape_rmse_m"])
    )
    if as_bool(klt, "hard_failure"):
        no_harm = full_ok
    else:
        no_harm = full_ok and float(full["ape_rmse_m"]) <= 1.05 * float(klt["ape_rmse_m"])
    ape_values = [float(row["ape_rmse_m"]) for row in rows if math.isfinite(float(row["ape_rmse_m"]))]
    replay_spread = (max(ape_values) - min(ape_values)) / min(ape_values) if ape_values and min(ape_values) > 0 else math.nan
    same_frontend_input = (
        not learned_active
        and int(full["dropped_lineage_observations"]) == 0
        and str(full["bag_sha256"]) == str(klt["bag_sha256"])
    )
    hard_failure_pattern = {int(row["hard_failure"]) for row in rows}
    backend_replay_unstable = same_frontend_input and (
        (math.isfinite(replay_spread) and replay_spread > 0.05) or len(hard_failure_pattern) > 1
    )
    summary: dict[str, object] = {
        "case_id": case["case_id"],
        "cohort": case["cohort"],
        "independent_cluster": case["independent_cluster"],
        "dataset_family": case["dataset_family"],
        "window": case["window"],
        "planned_profile": case["profile"],
        "selected_profile": full["selected_profile"],
        "fresh_export": case["fresh_export"],
        "complete": int(all(row["exit_code"] != -1 for row in rows)),
        "learned_track_ids": full["learned_track_ids"],
        "dropped_lineage_observations": full["dropped_lineage_observations"],
        "learned_active": int(learned_active),
        "same_frontend_input": int(same_frontend_input),
        "ape_replay_relative_spread": replay_spread,
        "backend_replay_unstable": int(backend_replay_unstable),
        "ape_win": int(ape_win),
        "dual_metric_win": int(dual_win),
        "strict_ape_better_than_klt": int(strict_better_klt),
        "strict_ape_better_than_drop": int(strict_better_drop),
        "strict_ape_better_than_both": int(strict_better_klt and strict_better_drop),
        "active_ape_win": int(learned_active and ape_win),
        "no_harm_vs_klt": int(no_harm),
        "klt_hard_failure_rescue": int(klt_rescue),
        "drop_hard_failure_rescue": int(drop_rescue),
        "full_vs_klt_relative_improvement": relative_improvement(full, klt),
        "full_vs_drop_relative_improvement": relative_improvement(full, drop),
        "notes": case["notes"],
    }
    for arm in ARMS:
        row = by_arm[arm]
        summary[f"{arm}_bag_sha256"] = row["bag_sha256"]
        for key in (
            "ape_rmse_m",
            "rpe_rmse_m",
            "coverage_ratio",
            "init_success",
            "hard_failure",
            "solver_risk",
            "solver_failure_count",
        ):
            summary[f"{arm}_{key}"] = row[key]
    return summary


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    artifact_root = Path(args.artifact_root)
    status_dir = artifact_root / "status"
    out_dir = Path(args.output_dir)
    with Path(args.manifest).open(newline="", encoding="utf-8") as handle:
        manifest = list(csv.DictReader(handle))

    long_rows: list[dict[str, object]] = []
    case_rows: list[dict[str, object]] = []
    for case in manifest:
        state_path = status_dir / f"{case['case_id']}.env"
        if not state_path.exists():
            continue
        state = read_kv(state_path)
        drop_stats_path = Path(
            state.get(
                "drop_stats_path",
                str(artifact_root / "bags" / case["case_id"] / "drop_whole_lineage_stats.csv"),
            )
        )
        drop_stats = first_csv_row(drop_stats_path)
        rows = [metric_row(case, state, status_dir, drop_stats, arm) for arm in ARMS]
        long_rows.extend(rows)
        case_rows.append(summarize_case(case, rows))

    write_csv(out_dir / "results_long.csv", long_rows)
    write_csv(out_dir / "case_summary.csv", case_rows)
    print(f"cases={len(case_rows)}")
    print(f"arms={len(long_rows)}")
    print(f"output_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
