#!/usr/bin/env python3
"""Summarize existing three-repeat G0 replay groups without treating repeats as n."""

from __future__ import annotations

import csv
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = (
    ROOT
    / "papers/ieee_sensors_journal_experiments/learned_specificity_20260803/analysis-output/replay-metrics.csv"
)
OUTPUT = ROOT / "papers/replay_stability.csv"


def number(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def base_arm(raw: str) -> str:
    return re.sub(r"_r[123]$", "", raw)


def main() -> int:
    with INPUT.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    groups: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        if (
            row["evaluator"] != "g0_common_support"
            or row["technical_repeat"] != "True"
            or not row["replay"]
        ):
            continue
        key = (row["dataset"], row["window"], row["profile"], base_arm(row["arm"]))
        groups[key].append(row)

    output: list[dict[str, object]] = []
    for (dataset, window, profile, arm), values in sorted(groups.items()):
        replay_numbers = sorted(int(row["replay"]) for row in values)
        if replay_numbers != [1, 2, 3]:
            continue
        ape = [number(row["ape_rmse_m"]) for row in values]
        rpe = [number(row["rpe_rmse_m"]) for row in values]
        ape_values = [value for value in ape if value is not None]
        rpe_values = [value for value in rpe if value is not None]
        solver_failures = [int(float(row["solver_failures"] or 0)) for row in values]
        valid_replays = sum(row["rpe_valid"] == "True" for row in values)
        output.append(
            {
                "dataset": dataset,
                "window": window,
                "profile": profile,
                "arm": arm,
                "feature_export_reused": 1,
                "feature_bag_hash_bound": 0,
                "replay_count": 3,
                "valid_rpe_replays": valid_replays,
                "window_arm_hard_failure": int(valid_replays < 2),
                "any_repeat_hard_failure": int(valid_replays < 3),
                "ape_median_m": statistics.median(ape_values) if ape_values else "",
                "ape_sample_variance_m2": (
                    statistics.variance(ape_values) if len(ape_values) >= 2 else ""
                ),
                "ape_min_m": min(ape_values) if ape_values else "",
                "ape_max_m": max(ape_values) if ape_values else "",
                "rpe_median_m": statistics.median(rpe_values) if rpe_values else "",
                "rpe_sample_variance_m2": (
                    statistics.variance(rpe_values) if len(rpe_values) >= 2 else ""
                ),
                "rpe_min_m": min(rpe_values) if rpe_values else "",
                "rpe_max_m": max(rpe_values) if rpe_values else "",
                "solver_failure_replays": sum(value > 0 for value in solver_failures),
                "solver_risk_rate": sum(value > 0 for value in solver_failures) / 3.0,
                "window_arm_solver_risk": int(any(value > 0 for value in solver_failures)),
                "scientific_units": 1,
                "evidence_scope": "DEVELOPMENT_TECHNICAL_REPEATS_NOT_P07_CONFIRMATORY",
                "source_artifacts": ";".join(row["source_artifact"] for row in values),
            }
        )
    if not output:
        raise ValueError("no complete three-replay groups found")
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader()
        writer.writerows(output)
    print(f"REPLAY_STABILITY_COMPLETE groups={len(output)}")
    print(f"output={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
