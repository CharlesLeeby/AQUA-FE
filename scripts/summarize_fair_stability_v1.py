#!/usr/bin/python3
"""Receipt-validated progress summary for the fair-stability experiment."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable, Mapping
import uuid


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fair_stability_ordinal_common_v1 import (  # noqa: E402
    SCHEDULE_SHA256,
    inspect_cell,
    load_schedule,
)


EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v1"
)


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def finite_median(values: Iterable[object]) -> tuple[float | None, int]:
    numeric = [float(value) for value in values if isinstance(value, (int, float)) and math.isfinite(float(value))]
    return (statistics.median(numeric), len(numeric)) if len(numeric) >= 2 else (None, len(numeric))


def normalize_result(cell: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    result = state["result"]
    arm = str(cell["arm"])
    if arm.startswith("hfnet_openloop_"):
        trajectory = result.get("support", {}).get("trajectory", {})
        log = result.get("support", {}).get("log", {})
        events = result.get("support", {}).get("events", {})
        reset_count = int(log.get("active_map_reset_count", 0))
        reinit_count = int(log.get("reinitialization_count", 0))
        solver_count = int(log.get("solver_risk_count", 0))
        unresolved_reset = bool(events.get("unresolved_resets"))
        unresolved_solver = bool(events.get("unresolved_solver_risks"))
    else:
        trajectory = result.get("trajectory", {})
        log = result.get("log", {})
        reset_count = int(log.get("reboot_or_reset_count", 0))
        reinit_count = int(log.get("reinitialization_count", 0))
        solver_count = int(log.get("solver_risk_count", 0))
        unresolved_reset = bool(
            log.get("reboot_or_reset_in_support_count", 0)
            or log.get("reboot_or_reset_unresolved_postinit_count", 0)
        )
        unresolved_solver = bool(
            log.get("solver_risk_in_support_count", 0)
            or log.get("solver_risk_unresolved_postinit_count", 0)
        )
    execution = result.get("execution", {})
    codes = [str(value) for value in result.get("algorithm_failure_codes", result.get("failure_codes", []))]
    crashed = bool(
        execution.get("timed_out")
        or execution.get("raw_returncode") not in (None, 0)
        or any("EXIT" in code or "TIMEOUT" in code or "CRASH" in code for code in codes)
    )
    return {
        "ordinal": int(cell["ordinal"]), "case_id": str(cell["case_id"]),
        "arm": arm, "repeat": int(cell["repeat"]),
        "attempt_index": int(state["attempt_index"]),
        "status": str(result["status"]), "clean_success": bool(result.get("clean_success")),
        "failure_codes": list(result.get("failure_codes", [])),
        "algorithm_failure_codes": codes,
        "coverage": trajectory.get("coverage_fraction"),
        "longest_contiguous_coverage": trajectory.get("longest_contiguous_fraction"),
        "initialization_latency_seconds": result.get("initialization_latency_seconds"),
        "reset_count": reset_count, "reinitialization_count": reinit_count,
        "solver_risk_count": solver_count, "unresolved_reset": unresolved_reset,
        "unresolved_solver_risk": unresolved_solver, "crashed_or_timed_out": crashed,
        "pipeline_invalid_attempts_before_terminal": len(state.get("invalid_chain", [])),
    }


def summarize() -> dict[str, Any]:
    schedule = load_schedule(EXPERIMENT_ROOT)
    rows: list[dict[str, Any]] = []
    states: Counter[str] = Counter()
    for cell in schedule:
        state = inspect_cell(EXPERIMENT_ROOT, cell)
        states[str(state["state"])] += 1
        if state["state"] == "TERMINAL":
            rows.append(normalize_result(cell, state))
    cell_summaries: list[dict[str, Any]] = []
    arms = sorted({str(cell["arm"]) for cell in schedule})
    cases = list(dict.fromkeys(str(cell["case_id"]) for cell in schedule))
    for case_id in cases:
        for arm in arms:
            selected = [row for row in rows if row["case_id"] == case_id and row["arm"] == arm]
            init_median, init_n = finite_median(row["initialization_latency_seconds"] for row in selected)
            coverage_median, coverage_n = finite_median(row["coverage"] for row in selected)
            modes = Counter(
                code for row in selected for code in row["algorithm_failure_codes"]
            )
            cell_summaries.append(
                {
                    "case_id": case_id, "arm": arm, "terminal_replicates": len(selected),
                    "planned_replicates": 3,
                    "successes": sum(row["status"] == "SUCCESS" for row in selected),
                    "clean_successes": sum(row["clean_success"] for row in selected),
                    "failure_modes": dict(sorted(modes.items())),
                    "median_initialization_latency_seconds": init_median,
                    "initialization_latency_numeric_replicates": init_n,
                    "median_coverage": coverage_median,
                    "coverage_numeric_replicates": coverage_n,
                    "any_crash_or_timeout": any(row["crashed_or_timed_out"] for row in selected),
                    "any_reset": any(row["reset_count"] > 0 for row in selected),
                    "any_reinitialization": any(row["reinitialization_count"] > 0 for row in selected),
                    "any_solver_risk": any(row["solver_risk_count"] > 0 for row in selected),
                    "numeric_median_requires_at_least_two": True,
                }
            )
    arm_summaries = {
        arm: {
            "terminal_replicates": sum(row["arm"] == arm for row in rows),
            "planned_replicates": 30,
            "successes": sum(row["arm"] == arm and row["status"] == "SUCCESS" for row in rows),
            "clean_successes": sum(row["arm"] == arm and row["clean_success"] for row in rows),
            "windows_with_all_three_terminal": sum(
                summary["arm"] == arm and summary["terminal_replicates"] == 3
                for summary in cell_summaries
            ),
        }
        for arm in arms
    }
    return {
        "schema_version": "aqua-fe-fair-stability-receipt-summary-v1",
        "generated_at_utc": now_utc(), "schedule_sha256": SCHEDULE_SHA256,
        "complete": len(rows) == 120, "terminal_replicates": len(rows),
        "planned_replicates": 120, "schedule_state_counts": dict(sorted(states.items())),
        "rows": rows, "case_arm_cells": cell_summaries, "arms": arm_summaries,
        "analysis_boundary": {
            "outcome_selected_roster": True,
            "repetitions_nested_within_window_not_independent_samples": True,
            "pipeline_invalid_attempts_excluded_only_after_receipt_adjudication": True,
            "non_success_accuracy_is_na": True,
            "p07_backend_reproduction": False,
            "dataset_wide_or_paper_final_superiority_supported": False,
        },
    }


def main() -> int:
    report = summarize()
    target = EXPERIMENT_ROOT / "fair_stability_progress_summary_v1.json"
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_json(report))
    os.replace(temporary, target)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
