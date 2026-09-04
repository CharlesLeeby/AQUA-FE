from __future__ import annotations

import math
import unittest
from pathlib import Path

from uw_frontend.evaluation.failure_classifier import (
    FailureTaxonomy,
    ReplayEvidence,
)


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY = FailureTaxonomy.from_yaml(
    ROOT / "papers/ieee_sensors_journal_experiments/failure_taxonomy_v1.yaml"
)


def _evidence(**overrides) -> ReplayEvidence:
    values = dict(
        process_exit_code=0,
        timed_out=False,
        window_start_s=100.0,
        window_end_s=120.0,
        trajectory_timestamps_s=[100.0 + 0.5 * index for index in range(41)],
        trajectory_rows_finite=[True] * 41,
        log_text="",
        input_message_count=400,
        processed_message_count=400,
        observable_backlog_growth_s=0.0,
        infrastructure_evidence=(),
    )
    values.update(overrides)
    return ReplayEvidence(**values)


class FailureClassifierTests(unittest.TestCase):
    def test_valid_replay_and_exact_segment_coverage(self) -> None:
        decision = TAXONOMY.classify(_evidence())
        self.assertTrue(decision.replay_evaluable)
        self.assertFalse(decision.replay_hard_failure)
        self.assertEqual(decision.full_window_coverage, 1.0)
        self.assertEqual(decision.valid_pose_count, 41)

    def test_each_hard_failure_condition(self) -> None:
        cases = [
        ({"process_exit_code": 7}, "NONZERO_EXIT"),
        ({"timed_out": True}, "TIMEOUT"),
        ({"trajectory_timestamps_s": [], "trajectory_rows_finite": []}, "EMPTY_TRAJECTORY"),
        (
            {
                "trajectory_timestamps_s": [100.0, float("nan")],
                "trajectory_rows_finite": [True, False],
            },
            "NONFINITE_TRAJECTORY",
        ),
        (
            {
                "trajectory_timestamps_s": [100.0, 101.0, 100.5],
                "trajectory_rows_finite": [True, True, True],
            },
            "NONMONOTONIC_TRAJECTORY",
        ),
        (
            {
                "trajectory_timestamps_s": [111.0, 111.5, 112.0],
                "trajectory_rows_finite": [True, True, True],
            },
            "INITIALIZATION_FAILURE",
        ),
        (
            {
                "trajectory_timestamps_s": [100.0, 100.5, 101.0],
                "trajectory_rows_finite": [True, True, True],
            },
            "COVERAGE_BELOW_0P50",
        ),
        ]
        for overrides, reason in cases:
            with self.subTest(reason=reason):
                decision = TAXONOMY.classify(_evidence(**overrides))
                self.assertTrue(decision.replay_hard_failure)
                self.assertIn(reason, decision.hard_failure_reasons)

    def test_solver_risk_is_distinct_from_hard_failure(self) -> None:
        decision = TAXONOMY.classify(
            _evidence(log_text="Linear solver failure. Unable to perform dense Cholesky factorization.")
        )
        self.assertTrue(decision.replay_evaluable)
        self.assertTrue(decision.solver_risk)
        self.assertEqual(decision.solver_risk_signatures, ("linear_solver_failure",))

    def test_queue_drop_contract(self) -> None:
        exact = TAXONOMY.classify(_evidence(processed_message_count=396))
        above = TAXONOMY.classify(_evidence(processed_message_count=395))
        backlog = TAXONOMY.classify(_evidence(observable_backlog_growth_s=5.0))
        self.assertTrue(math.isclose(exact.queue_drop_rate or 0.0, 0.01))
        self.assertFalse(exact.sustained_queue_drop)
        self.assertTrue(above.sustained_queue_drop)
        self.assertTrue(backlog.sustained_queue_drop)

    def test_three_replay_reducer(self) -> None:
        cases = [
        (0, True),
        (1, True),
        (2, False),
        (3, False),
        ]
        good = TAXONOMY.classify(_evidence())
        bad = TAXONOMY.classify(_evidence(process_exit_code=1))
        metrics = [{"ape_rmse_m": float(index + 1)} for index in range(3)]
        for evaluable, window_failure in cases:
            with self.subTest(evaluable=evaluable):
                decisions = [good] * evaluable + [bad] * (3 - evaluable)
                reduced = TAXONOMY.reduce_window_arm(decisions, metrics)
                self.assertEqual(reduced.evaluable_replays, evaluable)
                self.assertIs(reduced.window_arm_hard_failure, window_failure)
                self.assertIs(reduced.any_repeat_hard_failure, evaluable < 3)

    def test_reducer_uses_median_and_any_of_three_solver_risk(self) -> None:
        plain = TAXONOMY.classify(_evidence())
        risky = TAXONOMY.classify(_evidence(log_text="failure detection!"))
        reduced = TAXONOMY.reduce_window_arm(
            [plain, risky, plain],
            [{"ape_rmse_m": 3.0}, {"ape_rmse_m": 100.0}, {"ape_rmse_m": 5.0}],
        )
        self.assertEqual(reduced.median_metrics["ape_rmse_m"], 5.0)
        self.assertTrue(reduced.window_arm_solver_risk)

    def test_infrastructure_attempt_cannot_enter_algorithmic_reducer(self) -> None:
        infra = TAXONOMY.classify(
            _evidence(process_exit_code=1, infrastructure_evidence=("DISK_FULL",))
        )
        good = TAXONOMY.classify(_evidence())
        with self.assertRaisesRegex(ValueError, "infrastructure"):
            TAXONOMY.reduce_window_arm([infra, good, good])


if __name__ == "__main__":
    unittest.main()
