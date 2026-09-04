#!/usr/bin/python3
"""Receipt-validated progress summary for runtime-exclusive fair stability v5."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
import itertools
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

from fair_stability_ordinal_common_v5 import (  # noqa: E402
    EXPERIMENT_ID,
    SCHEDULE_SHA256,
    identity,
    inspect_cell,
    load_attempt_matrix,
    load_schedule,
)


EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v5"
)
BACKEND_FREEZE = (
    EXPERIMENT_ROOT
    / "vins_dev_nativeq_schedfix_runtimeexcl_v5"
    / "backend_freeze.json"
)
MATRIX_FREEZE = EXPERIMENT_ROOT / "attempt_matrix_freeze_v5.json"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def finite_median(values: Iterable[object]) -> tuple[float | None, int]:
    numeric = [
        float(value)
        for value in values
        if type(value) in (int, float) and math.isfinite(float(value))
    ]
    return (statistics.median(numeric), len(numeric)) if len(numeric) >= 2 else (None, len(numeric))


def nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def tri_state_any(
    rows: Iterable[Mapping[str, Any]],
    value_key: str,
    observable_key: str,
    planned_replicates: int = 3,
) -> bool | None:
    """Return false only when every planned replicate is terminal and observable."""
    selected = list(rows)
    observed = [row for row in selected if row.get(observable_key) is True]
    if any(bool(row.get(value_key)) for row in observed):
        return True
    if len(selected) == planned_replicates and len(observed) == planned_replicates:
        return False
    return None


def exact_window_block_swap(integer_differences: Iterable[int]) -> dict[str, Any]:
    """Two-sided paired exact test, exchanging complete three-repeat window blocks."""
    differences = tuple(int(value) for value in integer_differences)
    observed = abs(sum(differences))
    extreme = sum(
        abs(sum(sign * value for sign, value in zip(signs, differences))) >= observed
        for signs in itertools.product((-1, 1), repeat=len(differences))
    )
    assignments = 2 ** len(differences)
    return {
        "alternative": "two_sided",
        "inclusive_ties": True,
        "extreme_assignments": extreme,
        "enumerated_assignments": assignments,
        "p_value": extreme / assignments,
    }


def exact_window_block_swap_p(integer_differences: Iterable[int]) -> float:
    return float(exact_window_block_swap(integer_differences)["p_value"])


@lru_cache(maxsize=None)
def multinomial_window_count_vectors(n: int) -> tuple[tuple[tuple[int, ...], int], ...]:
    """All n-out-of-n cluster-bootstrap count vectors and exact multiplicities."""
    factorial_n = math.factorial(n)
    weighted: list[tuple[tuple[int, ...], int]] = []
    for sample in itertools.combinations_with_replacement(range(n), n):
        counts = tuple(sample.count(index) for index in range(n))
        weight = factorial_n // math.prod(math.factorial(count) for count in counts)
        weighted.append((counts, weight))
    return tuple(weighted)


def paired_window_bootstrap_interval(
    integer_values: Iterable[int], within_window_denominator: int
) -> dict[str, Any]:
    """Exact weighted interval; retain integer endpoints before final display division."""
    values = tuple(int(value) for value in integer_values)
    n = len(values)
    if n == 0:
        raise ValueError("BOOTSTRAP_REQUIRES_WINDOWS")
    if within_window_denominator <= 0:
        raise ValueError("BOOTSTRAP_DENOMINATOR_INVALID")
    distribution = sorted(
        (
            sum(count * value for count, value in zip(counts, values)),
            weight,
        )
        for counts, weight in multinomial_window_count_vectors(n)
    )
    total_weight = n ** n

    def inverse_cdf(numerator: int, denominator: int) -> int:
        target = (total_weight * numerator + denominator - 1) // denominator
        cumulative = 0
        for value, weight in distribution:
            cumulative += weight
            if cumulative >= target:
                return value
        raise RuntimeError("BOOTSTRAP_WEIGHT_UNDERRUN")

    endpoint_numerators = [inverse_cdf(1, 40), inverse_cdf(39, 40)]
    common_denominator = n * within_window_denominator
    return {
        "multinomial_weighted": True,
        "quantile_definition": "left_continuous_weighted_inverse_cdf",
        "ci_level": 0.95,
        "ci_integer_numerators": endpoint_numerators,
        "ci_common_denominator": common_denominator,
        "ci": [value / common_denominator for value in endpoint_numerators],
        "unique_count_vectors": len(distribution),
    }


def holm_adjusted_p_values(raw: Mapping[str, float]) -> dict[str, float]:
    ordered = sorted(raw.items(), key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 0.0
    total = len(ordered)
    for rank, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (total - rank) * float(value)))
        adjusted[name] = running
    return adjusted


def window_level_analysis(
    rows: Iterable[Mapping[str, Any]],
    cases: Iterable[str],
    complete_120: bool,
) -> dict[str, Any]:
    """Pre-registered inference with case_id, never a replicate, as independent unit."""
    selected_rows = list(rows)
    case_order = list(cases)
    arms = (
        "learned_klt_vins",
        "pure_klt_vins",
        "hfnet_openloop_675",
        "hfnet_openloop_350",
    )
    scores: list[dict[str, Any]] = []
    score_index: dict[tuple[str, str], dict[str, Any]] = {}
    all_cells_complete = True
    for case_id in case_order:
        for arm in arms:
            cell_rows = sorted(
                (
                    row for row in selected_rows
                    if row["case_id"] == case_id and row["arm"] == arm
                ),
                key=lambda row: int(row["repeat"]),
            )
            repeats = [int(row["repeat"]) for row in cell_rows]
            complete = repeats == [1, 2, 3]
            all_cells_complete = all_cells_complete and complete
            clean = [bool(row["clean_success"]) for row in cell_rows]
            item = {
                "case_id": case_id,
                "arm": arm,
                "terminal_repeats": repeats,
                "complete_three_repeats": complete,
                "clean_success_by_repeat": clean,
                "clean_count": sum(clean),
                "window_clean_rate": sum(clean) / 3 if complete else None,
            }
            scores.append(item)
            score_index[(case_id, arm)] = item
    authorized = bool(
        complete_120
        and len(selected_rows) == 120
        and len(case_order) == 10
        and len(set(case_order)) == 10
        and len(scores) == 40
        and all_cells_complete
    )
    result: dict[str, Any] = {
        "schema_version": "aqua-fe-fair-stability-window-analysis-v5",
        "analysis_authorized": authorized,
        "authorization_failure_reason": (
            None if authorized else "REQUIRES_ALL_120_TERMINAL_AND_40_COMPLETE_CASE_ARM_CELLS"
        ),
        "design": {
            "independent_unit": "case_id",
            "n_independent_windows": 10,
            "nested_repeats_per_window_arm": 3,
            "primary_endpoint": "clean_success",
            "primary_contrast": ["learned_klt_vins", "hfnet_openloop_675"],
            "alpha_two_sided": 0.05,
            "exact_test_assumptions": {
                "sharp_null": "whole_three_repeat_arm_blocks_exchangeable_within_case",
                "case_blocks_independent": True,
                "algorithm_labels_randomized": False,
                "unconditional_test_of_mean_effect_zero": False,
                "interpretation": "paired_sign_flip_diagnostic_on_fixed_roster",
            },
        },
        "validity_gates": {
            "complete_120_terminal_cells": complete_120 and len(selected_rows) == 120,
            "exactly_three_terminal_repeats_per_case_arm": all_cells_complete,
            "no_complete_case_deletion": (
                len(case_order) == 10 and len(set(case_order)) == 10
            ),
            "pipeline_invalid_attempts_receipt_adjudicated": authorized,
        },
        "window_arm_scores": scores,
        "arm_estimates": None,
        "contrasts": None,
        "multiplicity": {
            "strategy": "primary_fixed_sequence_gate_then_holm_two_secondary",
            "primary": "learned_klt_vins_vs_hfnet_openloop_675",
            "secondary": [
                "learned_klt_vins_vs_pure_klt_vins",
                "hfnet_openloop_675_vs_hfnet_openloop_350",
            ],
            "all_other_metrics_descriptive_only": True,
        },
        "scope": {
            "outcome_selected_roster": True,
            "dataset_wide_generalization": False,
            "learned_frontend_causal_claim": False,
            "current_paper_final_system_claim": False,
            "accuracy_analyzed": False,
            "system_boundary": (
                "frozen_feature_stream_vins_replay_vs_native_online_hfnet_openloop"
            ),
            "exact_test_rejects_only_sharp_block_exchangeability_null": True,
        },
    }
    if not authorized:
        return result

    arm_estimates: dict[str, Any] = {}
    for arm in arms:
        counts = [int(score_index[(case_id, arm)]["clean_count"]) for case_id in case_order]
        interval = paired_window_bootstrap_interval(counts, 3)
        distribution = Counter(counts)
        arm_estimates[arm] = {
            "clean_count": sum(counts),
            "run_denominator": 30,
            "equal_window_mean_clean_rate": sum(counts) / 30,
            "window_rate_distribution": {
                f"{count}_of_3": distribution.get(count, 0) for count in range(4)
            },
            "windows_three_of_three_clean": distribution.get(3, 0),
            "windows_at_least_two_of_three_clean": sum(count >= 2 for count in counts),
            "windows_with_any_nonclean_run": sum(count < 3 for count in counts),
            "paired_window_bootstrap": interval,
        }

    contrast_specs = {
        "primary": ("learned_klt_vins", "hfnet_openloop_675"),
        "secondary_learned_vs_pure_klt": ("learned_klt_vins", "pure_klt_vins"),
        "secondary_hfnet_675_vs_350": ("hfnet_openloop_675", "hfnet_openloop_350"),
    }
    contrasts: dict[str, Any] = {}
    for name, (arm_a, arm_b) in contrast_specs.items():
        differences = [
            int(score_index[(case_id, arm_a)]["clean_count"])
            - int(score_index[(case_id, arm_b)]["clean_count"])
            for case_id in case_order
        ]
        interval = paired_window_bootstrap_interval(differences, 3)
        exact_test = exact_window_block_swap(differences)
        contrasts[name] = {
            "arm_a": arm_a,
            "arm_b": arm_b,
            "window_clean_count_differences": differences,
            "mean_rate_difference_integer_numerator": sum(differences),
            "mean_rate_difference_common_denominator": 30,
            "mean_rate_difference": sum(differences) / 30,
            "mean_rate_difference_percentage_points": 100 * sum(differences) / 30,
            "window_wins_ties_losses": [
                sum(value > 0 for value in differences),
                sum(value == 0 for value in differences),
                sum(value < 0 for value in differences),
            ],
            "exact_window_block_swap": exact_test,
            "paired_window_bootstrap": interval,
        }
    primary = contrasts["primary"]
    primary_p = float(primary["exact_window_block_swap"]["p_value"])
    primary_ci_numerators = primary["paired_window_bootstrap"][
        "ci_integer_numerators"
    ]
    primary["supports_higher_clean_stability_for_arm_a"] = bool(
        primary["mean_rate_difference_integer_numerator"] > 0
        and primary_p < 0.05
        and primary_ci_numerators[0] > 0
    )
    primary_gate_open = primary_p < 0.05
    secondary_names = [
        "secondary_learned_vs_pure_klt",
        "secondary_hfnet_675_vs_350",
    ]
    if primary_gate_open:
        adjusted = holm_adjusted_p_values(
            {
                name: float(contrasts[name]["exact_window_block_swap"]["p_value"])
                for name in secondary_names
            }
        )
        for name in secondary_names:
            contrasts[name]["inferential_status"] = "HOLM_CONFIRMATORY_AFTER_PRIMARY_GATE"
            contrasts[name]["holm_adjusted_p_value"] = adjusted[name]
            contrasts[name]["holm_reject_at_alpha_0_05"] = adjusted[name] < 0.05
            contrasts[name][
                "holm_rejects_and_observed_direction_favors_arm_a"
            ] = bool(
                contrasts[name]["mean_rate_difference_integer_numerator"] > 0
                and adjusted[name] < 0.05
            )
            contrasts[name]["paired_window_bootstrap"][
                "multiplicity_adjusted"
            ] = False
            contrasts[name]["paired_window_bootstrap"][
                "secondary_inferential_use"
            ] = "DESCRIPTIVE_SUPPORT_ONLY_HOLM_CONTROLS_REJECTION"
    else:
        for name in secondary_names:
            contrasts[name]["inferential_status"] = "DESCRIPTIVE_PRIMARY_GATE_CLOSED"
            contrasts[name]["holm_adjusted_p_value"] = None
            contrasts[name]["holm_reject_at_alpha_0_05"] = None
            contrasts[name][
                "holm_rejects_and_observed_direction_favors_arm_a"
            ] = None
            contrasts[name]["paired_window_bootstrap"][
                "multiplicity_adjusted"
            ] = False
            contrasts[name]["paired_window_bootstrap"][
                "secondary_inferential_use"
            ] = "DESCRIPTIVE_PRIMARY_GATE_CLOSED"
    result["arm_estimates"] = arm_estimates
    result["contrasts"] = contrasts
    result["multiplicity"]["primary_gate_open"] = primary_gate_open
    return result


def normalize_result(cell: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    result = state["result"]
    arm = str(cell["arm"])
    if arm.startswith("hfnet_openloop_"):
        trajectory = result.get("support", {}).get("trajectory", {})
        log = result.get("support", {}).get("log", {})
        events = result.get("support", {}).get("events", {})
        event_log_observable = bool(
            isinstance(log, Mapping)
            and isinstance(log.get("stdout_identity"), Mapping)
            and isinstance(log.get("stderr_identity"), Mapping)
            and all(
                nonnegative_int(log.get(key))
                for key in (
                    "active_map_reset_count",
                    "reinitialization_count",
                    "solver_risk_count",
                )
            )
            and all(
                isinstance(log.get(key), list)
                for key in ("init_frame_ids", "reset_events", "solver_risk_events")
            )
            and isinstance(events, Mapping)
            and all(
                isinstance(events.get(key), list)
                for key in (
                    "unresolved_resets",
                    "unresolved_solver_risks",
                    "support_reinitializations",
                )
            )
        )
        reset_count = int(log["active_map_reset_count"]) if event_log_observable else None
        reinit_count = int(log["reinitialization_count"]) if event_log_observable else None
        solver_count = int(log["solver_risk_count"]) if event_log_observable else None
        unresolved_reset = (
            bool(events["unresolved_resets"]) if event_log_observable else None
        )
        unresolved_solver = (
            bool(events["unresolved_solver_risks"]) if event_log_observable else None
        )
    else:
        trajectory = result.get("trajectory", {})
        log = result.get("log", {})
        event_log_observable = bool(
            isinstance(log, Mapping)
            and log.get("valid") is True
            and isinstance(log.get("identity"), Mapping)
            and all(
                nonnegative_int(log.get(key))
                for key in (
                    "reboot_or_reset_count",
                    "reinitialization_count",
                    "solver_risk_count",
                    "reboot_or_reset_in_support_count",
                    "reboot_or_reset_unresolved_postinit_count",
                    "solver_risk_in_support_count",
                    "solver_risk_unresolved_postinit_count",
                )
            )
        )
        reset_count = int(log["reboot_or_reset_count"]) if event_log_observable else None
        reinit_count = int(log["reinitialization_count"]) if event_log_observable else None
        solver_count = int(log["solver_risk_count"]) if event_log_observable else None
        unresolved_reset = (
            bool(
                log["reboot_or_reset_in_support_count"]
                or log["reboot_or_reset_unresolved_postinit_count"]
            )
            if event_log_observable
            else None
        )
        unresolved_solver = (
            bool(
                log["solver_risk_in_support_count"]
                or log["solver_risk_unresolved_postinit_count"]
            )
            if event_log_observable
            else None
        )
    execution = result.get("execution", {})
    codes = [str(value) for value in result.get("algorithm_failure_codes", result.get("failure_codes", []))]
    execution_observable = bool(
        isinstance(execution, Mapping)
        and type(execution.get("timed_out")) is bool
        and (
            execution.get("raw_returncode") is None
            or type(execution.get("raw_returncode")) is int
        )
    )
    crashed = (
        bool(
            execution["timed_out"]
            or execution.get("raw_returncode") not in (None, 0)
            or any("EXIT" in code or "TIMEOUT" in code or "CRASH" in code for code in codes)
        )
        if execution_observable
        else None
    )
    invalid_reasons: list[dict[str, Any]] = []
    for invalid in state.get("invalid_chain", []):
        path = Path(str(invalid["attempt_root"])) / "run_result.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        invalid_reasons.append(
            {
                "attempt_index": int(invalid["attempt_index"]),
                "pipeline_failure_codes": list(value.get("pipeline_failure_codes", [])),
                "runtime_resource_monitor": value.get("runtime_resource_monitor"),
            }
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
        "unresolved_solver_risk": unresolved_solver,
        "event_log_observable": event_log_observable,
        "crashed_or_timed_out": crashed,
        "execution_observable": execution_observable,
        "pipeline_invalid_attempts_before_terminal": len(state.get("invalid_chain", [])),
        "pipeline_invalid_attempt_reasons": invalid_reasons,
        "runtime_resource_monitor": result.get("runtime_resource_monitor"),
    }


def summarize() -> dict[str, Any]:
    matrix = load_attempt_matrix(EXPERIMENT_ROOT)
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
                    "event_log_observable_terminal_replicates": sum(
                        row["event_log_observable"] is True for row in selected
                    ),
                    "all_planned_event_logs_observable": (
                        len(selected) == 3
                        and all(row["event_log_observable"] is True for row in selected)
                    ),
                    "any_crash_or_timeout": tri_state_any(
                        selected, "crashed_or_timed_out", "execution_observable"
                    ),
                    "any_reset": tri_state_any(
                        selected, "reset_count", "event_log_observable"
                    ),
                    "any_reinitialization": tri_state_any(
                        selected, "reinitialization_count", "event_log_observable"
                    ),
                    "any_solver_risk": tri_state_any(
                        selected, "solver_risk_count", "event_log_observable"
                    ),
                    "tri_state_event_fields": "true_false_or_null_unknown",
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
    complete = len(rows) == 120 and states == Counter({"TERMINAL": 120})
    paired_analysis = window_level_analysis(rows, cases, complete)
    return {
        "schema_version": "aqua-fe-fair-stability-receipt-summary-v5",
        "experiment_id": EXPERIMENT_ID,
        "generated_at_utc": now_utc(), "schedule_sha256": SCHEDULE_SHA256,
        "experiment_manifest": identity(EXPERIMENT_ROOT / "experiment_manifest.json"),
        "backend_freeze": identity(BACKEND_FREEZE),
        "attempt_matrix_freeze": identity(MATRIX_FREEZE),
        "complete": complete, "terminal_replicates": len(rows),
        "planned_replicates": 120, "schedule_state_counts": dict(sorted(states.items())),
        "rows": rows, "case_arm_cells": cell_summaries, "arms": arm_summaries,
        "window_level_analysis": paired_analysis,
        "analysis_boundary": {
            "outcome_selected_roster": True,
            "repetitions_nested_within_window_not_independent_samples": True,
            "pipeline_invalid_attempts_excluded_only_after_receipt_adjudication": True,
            "non_success_accuracy_is_na": True,
            "p07_backend_reproduction": False,
            "dataset_wide_or_paper_final_superiority_supported": False,
            "v1_results_imported": False,
            "v2_results_imported": False,
            "v3_results_imported": False,
            "v4_results_imported": False,
            "runtime_performance_claim_allowed": False,
            "runtime_exclusivity_is_sampled_not_kernel_exec_trace": True,
            "independent_statistical_unit": "case_id",
            "n_independent_windows": 10,
            "primary_endpoint": "clean_success",
            "primary_contrast": "learned_klt_vins_minus_hfnet_openloop_675",
            "flat_30_run_counts_are_descriptive_not_independent_samples": True,
        },
    }


def main() -> int:
    report = summarize()
    target = EXPERIMENT_ROOT / "fair_stability_progress_summary_v5.json"
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_json(report))
    os.replace(temporary, target)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
