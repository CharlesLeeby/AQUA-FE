#!/usr/bin/env python3

from __future__ import annotations

import math
import unittest

import numpy as np

from scripts.trajectory_eval_core import (
    ResampledTrajectory,
    align_se3_positions,
    choose_evaluation_rate,
    common_valid_mask,
    evaluate_common_translation,
    make_uniform_grid,
    legacy_unique_assignment,
    prepare_reference_samples,
    resample_trajectory,
    rejection_histogram,
    segment_ids,
    strict_delta_pairs,
    transform_body_poses_to_sensor,
    validate_estimate_samples,
)


class TrajectoryEvalCoreTest(unittest.TestCase):
    def test_prepare_reference_sorts_audits_and_deduplicates_identical_pose(self) -> None:
        stamps, positions, _, audit = prepare_reference_samples(
            [1.0, 0.0, 1.0, float("nan")],
            [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2, 0, 0]],
        )
        np.testing.assert_array_equal(stamps, [0.0, 1.0])
        np.testing.assert_array_equal(positions[:, 0], [0.0, 1.0])
        self.assertEqual(audit.raw_count, 4)
        self.assertEqual(audit.rejected_nonfinite_count, 1)
        self.assertEqual(audit.duplicate_count, 1)

    def test_prepare_reference_rejects_conflicting_duplicate_pose(self) -> None:
        with self.assertRaisesRegex(ValueError, "conflicting reference poses"):
            prepare_reference_samples(
                [0.0, 0.0], [[0, 0, 0], [1, 0, 0]]
            )

    def test_estimate_validation_preserves_hard_failures(self) -> None:
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            validate_estimate_samples([0.0, 2.0, 1.0], np.zeros((3, 3)))
        with self.assertRaisesRegex(ValueError, "non-finite"):
            validate_estimate_samples([0.0, 1.0], [[0, 0, 0], [np.nan, 0, 0]])

    def test_uniform_grid_is_window_anchored_and_inclusive(self) -> None:
        np.testing.assert_allclose(make_uniform_grid(10.0, 11.0, 2.0), [10, 10.5, 11])

    def test_epoch_scale_grid_retains_sub_float64_increment_precision(self) -> None:
        start = np.longdouble("1542888916.0436223")
        grid = make_uniform_grid(start, start + np.longdouble("0.0000002"), 10_000_000)
        self.assertEqual(grid.dtype, np.dtype(np.longdouble))
        self.assertEqual(len(grid), 3)
        np.testing.assert_allclose(
            np.diff(grid),
            np.longdouble("0.0000001"),
            rtol=0.0,
            atol=np.longdouble("1e-12"),
        )

    def test_evaluation_rate_uses_largest_allowed_rate_below_reference(self) -> None:
        self.assertEqual(choose_evaluation_rate(1.0), 1.0)
        self.assertEqual(choose_evaluation_rate(4.0), 2.0)
        self.assertEqual(choose_evaluation_rate(49.36), 10.0)
        with self.assertRaisesRegex(ValueError, "below the minimum"):
            choose_evaluation_rate(0.5)

    def test_legacy_assignment_is_unique_global_and_prefers_earlier_tie(self) -> None:
        pairs = legacy_unique_assignment([0.0, 0.1, 0.9, 1.0], [0.0, 1.0])
        np.testing.assert_array_equal(pairs, [[0, 0], [3, 1]])
        tied = legacy_unique_assignment([0.5], [0.0, 1.0])
        np.testing.assert_array_equal(tied, [[0, 0]])

    def test_legacy_assignment_respects_match_tolerance(self) -> None:
        pairs = legacy_unique_assignment([0.0, 0.8], [0.0, 1.0], max_match_dt_s=0.1)
        np.testing.assert_array_equal(pairs, [[0, 0]])

    def test_translation_and_quaternion_interpolation(self) -> None:
        result = resample_trajectory(
            stamps=[0.0, 1.0],
            positions=[[0, 0, 0], [2, 0, 0]],
            quaternions=[[0, 0, 0, 1], [0, 0, 1, 0]],
            grid_stamps=[0.0, 0.5, 1.0],
            max_interp_gap_s=1.0,
            sample_kind="estimate",
        )
        self.assertTrue(np.all(result.valid))
        np.testing.assert_allclose(result.positions[:, 0], [0.0, 1.0, 2.0])
        assert result.quaternions is not None
        np.testing.assert_allclose(
            np.abs(result.quaternions[1]),
            [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)],
            atol=1e-8,
        )

    def test_body_to_sensor_transform_uses_body_orientation(self) -> None:
        positions = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])
        quaternions = np.array(
            [
                [0.0, 0.0, 0.0, 1.0],
                [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)],
            ]
        )
        body_t_sensor = np.eye(4)
        body_t_sensor[0, 3] = 0.5
        sensor_positions, sensor_quaternions = transform_body_poses_to_sensor(
            positions, quaternions, body_t_sensor
        )
        np.testing.assert_allclose(sensor_positions[0], [1.5, 2.0, 3.0], atol=1e-12)
        np.testing.assert_allclose(sensor_positions[1], [1.0, 2.5, 3.0], atol=1e-12)
        np.testing.assert_allclose(
            np.abs(sensor_quaternions[1]),
            [0.0, 0.0, math.sqrt(0.5), math.sqrt(0.5)],
            atol=1e-12,
        )

    def test_interpolation_rejects_out_of_range_and_long_brackets(self) -> None:
        result = resample_trajectory(
            stamps=[0.0, 2.0],
            positions=[[0, 0, 0], [2, 0, 0]],
            grid_stamps=[-1.0, 0.0, 1.0, 2.0, 3.0],
            max_interp_gap_s=1.0,
            sample_kind="estimate",
        )
        np.testing.assert_array_equal(result.valid, [False, True, False, True, False])
        self.assertEqual(result.bracket_gaps_s[2], 2.0)
        self.assertEqual(
            rejection_histogram(result),
            {"EXACT": 2, "GAP_EXCEEDED": 1, "OUT_OF_RANGE": 2},
        )

    def test_common_mask_and_segments_split_at_invalid_grid_points(self) -> None:
        grid = np.arange(5, dtype=float)
        reference = _resampled(grid, [True, True, True, True, True])
        arm_a = _resampled(grid, [True, True, False, True, True])
        arm_b = _resampled(grid, [True, True, True, True, False])
        mask = common_valid_mask(reference, [arm_a, arm_b])
        np.testing.assert_array_equal(mask, [True, True, False, True, False])
        np.testing.assert_array_equal(segment_ids(grid, mask, 1.0), [0, 0, -1, 1, -1])

    def test_strict_delta_pairs_stay_within_segments(self) -> None:
        stamps = np.arange(6, dtype=float)
        mask = np.array([True, True, True, False, True, True])
        segments = segment_ids(stamps, mask, 1.0)
        pairs = strict_delta_pairs(stamps, mask, segments, delta_s=1.0)
        np.testing.assert_array_equal(pairs, [[0, 1], [1, 2], [4, 5]])

    def test_se3_alignment_does_not_estimate_scale(self) -> None:
        target = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=float)
        rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=float)
        source = (rotation.T @ (target - np.array([2, 3, 4])).T).T
        np.testing.assert_allclose(align_se3_positions(source, target), target, atol=1e-10)

    def test_common_evaluation_uses_one_mask_and_exact_rpe_pairs(self) -> None:
        grid = np.arange(0.0, 5.0, 1.0)
        reference = _trajectory(grid, grid)
        translated = _trajectory(grid, grid + 10.0)
        dropped = _trajectory(grid, grid + 3.0, valid=[True, True, False, True, True])
        result = evaluate_common_translation(
            reference,
            {"translated": translated, "dropped": dropped},
            window_start_s=0.0,
            window_end_s=4.0,
            max_segment_gap_s=1.0,
            rpe_delta_s=1.0,
            min_ape_poses=3,
            min_ape_span_s=3.0,
            min_common_coverage=0.70,
            min_rpe_pairs=2,
        )
        support = result["support"]
        assert isinstance(support, dict)
        self.assertEqual(support["matched_count"], 4)
        self.assertEqual(support["segment_count"], 2)
        self.assertEqual(support["rpe_pairs"], 2)
        self.assertTrue(support["ape_valid"])
        arms = result["arms"]
        assert isinstance(arms, dict)
        self.assertAlmostEqual(arms["translated"]["ape_rmse_m"], 0.0, places=12)
        self.assertAlmostEqual(arms["dropped"]["rpe_rmse_m"], 0.0, places=12)

    def test_common_evaluation_reports_insufficient_support(self) -> None:
        grid = np.arange(3, dtype=float)
        reference = _trajectory(grid, grid)
        arm = _trajectory(grid, grid)
        result = evaluate_common_translation(
            reference,
            {"arm": arm},
            window_start_s=0.0,
            window_end_s=2.0,
            max_segment_gap_s=1.0,
            min_ape_poses=30,
            min_ape_span_s=10.0,
            min_common_coverage=0.70,
            min_rpe_pairs=10,
        )
        support = result["support"]
        assert isinstance(support, dict)
        self.assertFalse(support["ape_valid"])
        self.assertFalse(support["rpe_valid"])


def _resampled(grid: np.ndarray, valid: list[bool]) -> ResampledTrajectory:
    return ResampledTrajectory(
        stamps=grid,
        positions=np.zeros((len(grid), 3), dtype=float),
        valid=np.asarray(valid, dtype=bool),
        bracket_gaps_s=np.zeros(len(grid), dtype=float),
    )


def _trajectory(
    grid: np.ndarray, x_values: np.ndarray, valid: list[bool] | None = None
) -> ResampledTrajectory:
    positions = np.column_stack((x_values, np.zeros(len(grid)), np.zeros(len(grid))))
    return ResampledTrajectory(
        stamps=grid,
        positions=positions,
        valid=np.ones(len(grid), dtype=bool) if valid is None else np.asarray(valid),
        bracket_gaps_s=np.zeros(len(grid), dtype=float),
    )


if __name__ == "__main__":
    unittest.main()
