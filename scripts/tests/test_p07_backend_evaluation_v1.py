#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import unittest

from scripts.p07_backend_evaluation_v1 import (
    ARM_B0,
    ARM_B1,
    ARM_D,
    ARM_M,
    ARM_P,
    B0_METRIC_ROLE,
    EvaluationContractError,
    ROUTE_B0_DESCRIPTIVE,
    ROUTE_PAIRWISE_COMMON_SUPPORT,
    build_evaluation_plan,
    classify_replay_evidence,
    materialize_reducer_records,
    reduce_pairwise_contrast,
    reduce_window_arm_replays,
    validate_evaluation_job,
)
from scripts.run_p07_g0_evaluation_v1 import build_g0_command


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> dict[str, object]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def make_terminal_records(spec: dict[str, object]) -> tuple[list[dict[str, object]], dict[str, bool]]:
    reference = spec["reference"]
    windows = spec["windows"]
    assert isinstance(windows, list)
    rows: list[dict[str, object]] = []
    applicability: dict[str, bool] = {}
    for window in windows:
        assert isinstance(window, dict)
        window_id = str(window["window_id"])
        d_applicable = bool(window["d_applicable"])
        applicability[window_id] = d_applicable
        arms = [ARM_B0, ARM_B1, ARM_P, ARM_M] + ([ARM_D] if d_applicable else [])
        for arm in arms:
            for replay_index in (1, 2, 3):
                run_id = f"{window_id}_{arm[:2].lower()}_r{replay_index}"
                evidence = clean_evidence(arm, replay_index)
                evidence["run_id"] = run_id
                evidence["window_id"] = window_id
                rows.append(
                    {
                        "run_id": run_id,
                        "window_id": window_id,
                        "arm": arm,
                        "replay_index": replay_index,
                        "algorithmic_slot": True,
                        "terminal": True,
                        "trajectory_path": f"fixtures/{window_id}/{arm}/r{replay_index}/vio.csv",
                        "config_path": f"fixtures/{window_id}/{arm}/r{replay_index}/config.yaml",
                        "failure_evidence_path": f"fixtures/{window_id}/{arm}/r{replay_index}/failure.json",
                        "arm_time_offset_s": 0.0,
                        "reference": copy.deepcopy(reference),
                        "evaluator_profile_id": "fixture_profile_v1",
                        "evaluator_protocol_sha256": spec["evaluator_protocol_sha256"],
                        "evaluator_script_sha256": spec["evaluator_script_sha256"],
                        "classification": classify_replay_evidence(evidence),
                    }
                )
    return rows, applicability


def clean_evidence(arm: str, replay_index: int, *, log_text: str = "") -> dict[str, object]:
    return {
        "run_id": f"fixture_{arm[:2]}_r{replay_index}",
        "window_id": "fixture_low_0001",
        "arm": arm,
        "replay_index": replay_index,
        "algorithmic_slot": True,
        "infrastructure_codes": [],
        "process": {"exit_code": 0, "timed_out": False},
        "trajectory": {
            "present": True,
            "row_count": 100,
            "finite": True,
            "strictly_increasing": True,
        },
        "initialization": {"success": True, "first_output_delay_s": 1.0},
        "support": {"coverage_ratio": 0.9},
        "solver_log_inspected": True,
        "solver_log_text": log_text,
        "queue": {"drop_rate": 0.0, "backlog_growth_s": 0.0},
    }


def hard_evidence(arm: str, replay_index: int) -> dict[str, object]:
    value = clean_evidence(arm, replay_index)
    value["trajectory"] = {"present": False, "row_count": 0}
    return value


def reduction_record(
    arm: str,
    replay_index: int,
    rpe: float | None,
    *,
    hard: bool = False,
    solver_log: str = "",
) -> dict[str, object]:
    evidence = (
        hard_evidence(arm, replay_index)
        if hard
        else clean_evidence(arm, replay_index, log_text=solver_log)
    )
    evaluation = None
    if rpe is not None:
        evaluation = {
            "status": "COMPLETED",
            "rpe_valid": True,
            "rpe_rmse_m": rpe,
            "ape_valid": True,
            "ape_rmse_m": rpe * 2.0,
            "common_coverage": 0.9,
        }
    return {
        "classification": classify_replay_evidence(evidence),
        "route": ROUTE_PAIRWISE_COMMON_SUPPORT,
        "contrast_name": "P_vs_B1",
        "evaluation": evaluation,
    }


class P07EvaluationPlanTest(unittest.TestCase):
    def test_fixture_plan_freezes_pairwise_and_b0_routes(self) -> None:
        spec = fixture("p07_backend_evaluation_v1.json")
        rows, applicability = make_terminal_records(spec)
        jobs = build_evaluation_plan(rows, d_applicability=applicability)

        self.assertEqual(len(jobs), 21)  # 9 without D, 12 with D.
        b0_jobs = [job for job in jobs if job["route"] == ROUTE_B0_DESCRIPTIVE]
        pairwise = [
            job for job in jobs if job["route"] == ROUTE_PAIRWISE_COMMON_SUPPORT
        ]
        self.assertEqual(len(b0_jobs), 6)
        self.assertEqual(len(pairwise), 15)
        for job in b0_jobs:
            self.assertEqual(set(job["arms"]), {ARM_B0})
            self.assertEqual(job["metric_role"], B0_METRIC_ROLE)
            self.assertNotIn("comparator_arm", job)
        for job in pairwise:
            self.assertEqual(set(job["arms"]), {ARM_P, job["comparator_arm"]})
            self.assertNotEqual(job["comparator_arm"], ARM_B0)
            self.assertEqual(
                {value["replay_index"] for value in job["arms"].values()},
                {job["replay_index"]},
            )

    def test_plan_rejects_missing_replay_and_unresolved_d(self) -> None:
        spec = fixture("p07_backend_evaluation_v1.json")
        rows, applicability = make_terminal_records(spec)
        rows.pop()
        with self.assertRaisesRegex(EvaluationContractError, "exactly replay"):
            build_evaluation_plan(rows, d_applicability=applicability)

        rows, applicability = make_terminal_records(spec)
        applicability.pop("fixture_low_0001")
        with self.assertRaisesRegex(EvaluationContractError, "exactly match"):
            build_evaluation_plan(rows, d_applicability=applicability)

    def test_wrapper_uses_two_arms_for_pairwise_and_one_for_b0(self) -> None:
        spec = fixture("p07_backend_evaluation_v1.json")
        rows, applicability = make_terminal_records(spec)
        jobs = build_evaluation_plan(rows, d_applicability=applicability)
        b0 = next(job for job in jobs if job["route"] == ROUTE_B0_DESCRIPTIVE)
        pair = next(
            job for job in jobs if job["route"] == ROUTE_PAIRWISE_COMMON_SUPPORT
        )

        b0_command = build_g0_command(b0)
        pair_command = build_g0_command(pair)
        self.assertEqual(b0_command.count("--arm"), 1)
        self.assertEqual(pair_command.count("--arm"), 2)
        self.assertIn("--min-rpe-pairs", pair_command)
        self.assertEqual(pair_command[pair_command.index("--rpe-delta-s") + 1], "1")

        invalid = copy.deepcopy(pair)
        invalid["comparator_arm"] = ARM_B0
        invalid["arms"] = {ARM_P: invalid["arms"][ARM_P], ARM_B0: b0["arms"][ARM_B0]}
        with self.assertRaisesRegex(EvaluationContractError, "comparator"):
            validate_evaluation_job(invalid)

    def test_g0_summary_adapter_preserves_one_pairwise_support_decision(self) -> None:
        spec = fixture("p07_backend_evaluation_v1.json")
        rows, applicability = make_terminal_records(spec)
        job = next(
            item
            for item in build_evaluation_plan(rows, d_applicability=applicability)
            if item["route"] == ROUTE_PAIRWISE_COMMON_SUPPORT
        )
        summary = {
            "protocol": {"contrast_name": job["contrast_name"]},
            "support": {
                "rpe_valid": True,
                "ape_valid": True,
                "common_coverage": 0.85,
            },
            "arms": {
                arm: {"rpe_rmse_m": value, "ape_rmse_m": value * 2.0}
                for arm, value in zip(job["arms"], (0.8, 0.9))
            },
        }
        reducer_records = materialize_reducer_records(job, summary)
        self.assertEqual(len(reducer_records), 2)
        self.assertEqual(
            {record["evaluation"]["common_coverage"] for record in reducer_records},
            {0.85},
        )
        self.assertEqual(
            {record["classification"]["replay_index"] for record in reducer_records},
            {job["replay_index"]},
        )

    def test_hard_failure_pair_is_planned_as_failure_only_not_executable(self) -> None:
        spec = fixture("p07_backend_evaluation_v1.json")
        rows, applicability = make_terminal_records(spec)
        row = next(
            value
            for value in rows
            if value["window_id"] == "fixture_low_0001"
            and value["arm"] == ARM_P
            and value["replay_index"] == 1
        )
        evidence = hard_evidence(ARM_P, 1)
        evidence["run_id"] = row["run_id"]
        evidence["window_id"] = row["window_id"]
        row["classification"] = classify_replay_evidence(evidence)
        row["trajectory_path"] = None

        job = next(
            item
            for item in build_evaluation_plan(rows, d_applicability=applicability)
            if item["window_id"] == "fixture_low_0001"
            and item["contrast_name"] == "P_vs_B1"
            and item["replay_index"] == 1
        )
        self.assertEqual(job["evaluation_disposition"], "SKIP_NUMERIC_HARD_FAILURE")
        records = materialize_reducer_records(job, None)
        self.assertEqual(len(records), 2)
        self.assertTrue(
            next(
                record
                for record in records
                if record["classification"]["arm"] == ARM_P
            )["classification"]["hard_failure"]
        )
        with self.assertRaisesRegex(EvaluationContractError, "no numeric G0 command"):
            build_g0_command(job)


class P07FailureClassifierTest(unittest.TestCase):
    def test_fixture_failure_cases(self) -> None:
        cases = fixture("p07_failure_cases_v1.json")["cases"]
        assert isinstance(cases, list)
        for case in cases:
            with self.subTest(case=case["expected_status"]):
                result = classify_replay_evidence(case["evidence"])
                self.assertEqual(result["classification_status"], case["expected_status"])
                self.assertEqual(
                    result["observed_hard_failure_codes"],
                    case["expected_hard_codes"],
                )
                self.assertEqual(result["solver_risk_codes"], case["expected_solver_codes"])
        infrastructure = classify_replay_evidence(cases[-1]["evidence"])
        self.assertFalse(infrastructure["hard_failure"])
        self.assertFalse(infrastructure["numeric_evaluable_before_common_support"])

    def test_infrastructure_attempt_cannot_claim_algorithmic_slot(self) -> None:
        evidence = clean_evidence(ARM_P, 1)
        evidence["infrastructure_codes"] = ["DISK_FULL"]
        with self.assertRaisesRegex(EvaluationContractError, "cannot occupy"):
            classify_replay_evidence(evidence)


class P07TwoOfThreeReducerTest(unittest.TestCase):
    def test_two_numeric_replays_reduce_but_hard_failure_is_any_of_three(self) -> None:
        rows = [
            reduction_record(ARM_P, 1, 0.8),
            reduction_record(ARM_P, 2, None, hard=True),
            reduction_record(
                ARM_P,
                3,
                1.0,
                solver_log="Unable to perform dense Cholesky factorization",
            ),
        ]
        result = reduce_window_arm_replays(rows)

        self.assertEqual(result["reduction_status"], "NUMERIC_2_OF_3")
        self.assertAlmostEqual(result["rpe_rmse_median"], 0.9)
        self.assertTrue(result["hard_failure_any_of_three"])
        self.assertTrue(result["solver_risk_any_of_three"])
        self.assertEqual(result["registered_algorithmic_replays"], 3)
        self.assertEqual(result["evaluable_replay_indices"], [1, 3])

    def test_one_evaluable_replay_is_inconclusive(self) -> None:
        rows = [
            reduction_record(ARM_P, 1, 0.8),
            reduction_record(ARM_P, 2, None, hard=True),
            reduction_record(ARM_P, 3, None),
        ]
        # Replay 3 completed classification but has contrast-specific
        # insufficient support, represented by no numeric evaluation.
        rows[2]["evaluation"] = {
            "status": "COMPLETED",
            "rpe_valid": False,
            "rpe_rmse_m": None,
            "ape_valid": False,
            "ape_rmse_m": None,
            "common_coverage": 0.4,
        }
        result = reduce_window_arm_replays(rows)
        self.assertEqual(
            result["reduction_status"],
            "INCONCLUSIVE_FEWER_THAN_2_EVALUABLE_REPLAYS",
        )
        self.assertIsNone(result["rpe_rmse_median"])
        self.assertEqual(result["insufficient_common_support_replay_indices"], [3])

    def test_pairwise_failure_precedence_overrides_available_numeric_median(self) -> None:
        proposed = reduce_window_arm_replays(
            [
                reduction_record(ARM_P, 1, 0.8),
                reduction_record(ARM_P, 2, None, hard=True),
                reduction_record(ARM_P, 3, 1.0),
            ]
        )
        comparator = reduce_window_arm_replays(
            [
                reduction_record(ARM_B1, 1, 1.0),
                reduction_record(ARM_B1, 2, 1.1),
                reduction_record(ARM_B1, 3, 1.2),
            ]
        )
        contrast = reduce_pairwise_contrast(proposed, comparator)
        self.assertEqual(
            contrast["pair_status"],
            "PROPOSED_ONLY_HARD_FAILURE_AUTOMATIC_LOSS",
        )
        self.assertIsNone(contrast["log_rpe_ratio"])
        self.assertTrue(contrast["retained_in_failure_denominator"])

    def test_clean_numeric_pair_uses_log_ratio(self) -> None:
        proposed = reduce_window_arm_replays(
            [reduction_record(ARM_P, index, value) for index, value in enumerate((0.8, 0.9, 1.0), 1)]
        )
        comparator = reduce_window_arm_replays(
            [reduction_record(ARM_B1, index, value) for index, value in enumerate((1.0, 1.1, 1.2), 1)]
        )
        contrast = reduce_pairwise_contrast(proposed, comparator)
        self.assertEqual(contrast["pair_status"], "NUMERIC_PAIR")
        self.assertAlmostEqual(contrast["rpe_ratio_proposed_over_comparator"], 0.9 / 1.1)
        self.assertAlmostEqual(contrast["log_rpe_ratio"], math.log(0.9 / 1.1))


if __name__ == "__main__":
    unittest.main()
