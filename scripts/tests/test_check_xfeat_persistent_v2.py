from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest import mock

import numpy as np

from scripts.check_xfeat_persistent_v2 import (
    CheckConfig,
    FeatureFrame,
    evaluate_frames,
    main,
    same_frame_unique_id_check,
    vins_relative_pose_inliers,
)


def _persistent_frames(frame_count: int = 15, feature_count: int = 80) -> list[FeatureFrame]:
    rng = np.random.default_rng(7)
    world_points = np.column_stack(
        (
            rng.uniform(-1.5, 1.5, feature_count),
            rng.uniform(-1.0, 1.0, feature_count),
            rng.uniform(3.0, 7.0, feature_count),
        )
    )
    frames: list[FeatureFrame] = []
    for index in range(frame_count):
        camera_points = world_points.copy()
        camera_points[:, 0] -= 0.06 * index
        normalized = camera_points[:, :2] / camera_points[:, 2, None]
        frames.append(
            FeatureFrame(
                index=index,
                stamp_s=0.1 * index,
                ids=np.arange(feature_count, dtype=np.int64),
                normalized_points=normalized.astype(np.float32),
            )
        )
    return frames


def _config() -> CheckConfig:
    return CheckConfig(warmup_frames=4, min_long_tracks=40, lag=10)


class XFeatPersistentCheckerPureTests(unittest.TestCase):
    def test_persistent_synthetic_sequence_passes_vins_gates(self) -> None:
        result = evaluate_frames(_persistent_frames(), _config())
        self.assertTrue(result["pass"], result)
        checks = result["checks"]
        self.assertGreaterEqual(checks["post_warmup_long_tracks"]["min"], 40)
        pose = checks["rolling_lag_relative_pose"]
        self.assertGreater(pose["max_common_ids"], 20)
        self.assertGreater(pose["max_mean_parallax_px"], 30.0)
        self.assertGreater(pose["max_pose_inliers"], 12)

    def test_identity_churn_fails_long4_and_lag10(self) -> None:
        frames = _persistent_frames()
        churned = [
            FeatureFrame(
                index=frame.index,
                stamp_s=frame.stamp_s,
                ids=frame.ids + 1000 * frame.index,
                normalized_points=frame.normalized_points,
            )
            for frame in frames
        ]
        result = evaluate_frames(churned, _config())
        self.assertFalse(result["pass"])
        self.assertIn("LONG4_BELOW_THRESHOLD_AFTER_WARMUP", result["reasons"])
        self.assertIn("NO_VIABLE_LAG10_RELATIVE_POSE_PAIR", result["reasons"])
        self.assertEqual(
            result["checks"]["rolling_lag_relative_pose"]["max_common_ids"], 0
        )

    def test_same_frame_duplicate_id_is_a_hard_failure(self) -> None:
        frames = _persistent_frames()
        first = frames[0]
        duplicate_ids = first.ids.copy()
        duplicate_ids[1] = duplicate_ids[0]
        frames[0] = FeatureFrame(
            index=first.index,
            stamp_s=first.stamp_s,
            ids=duplicate_ids,
            normalized_points=first.normalized_points,
        )
        duplicate_check = same_frame_unique_id_check(frames)
        self.assertFalse(duplicate_check["pass"])
        self.assertEqual(duplicate_check["duplicate_observations"], 1)
        result = evaluate_frames(frames, _config())
        self.assertIn("DUPLICATE_ID_WITHIN_FRAME", result["reasons"])

    def test_pose_inlier_gate_is_strictly_greater_than_twelve(self) -> None:
        frames = _persistent_frames()
        rejected = evaluate_frames(
            frames,
            _config(),
            pose_solver=lambda _left, _right, _config: 12,
        )
        accepted = evaluate_frames(
            frames,
            _config(),
            pose_solver=lambda _left, _right, _config: 13,
        )
        self.assertFalse(rejected["checks"]["rolling_lag_relative_pose"]["pass"])
        self.assertTrue(accepted["checks"]["rolling_lag_relative_pose"]["pass"])

    def test_fixed_seed_relative_pose_is_deterministic(self) -> None:
        frames = _persistent_frames(frame_count=11)
        left = frames[0].normalized_points
        right = frames[10].normalized_points
        first = vins_relative_pose_inliers(left, right, _config())
        second = vins_relative_pose_inliers(left, right, _config())
        self.assertEqual(first, second)
        self.assertGreater(first, 12)


class XFeatPersistentCheckerCliTests(unittest.TestCase):
    def test_cli_prints_json_and_returns_scientific_exit_code(self) -> None:
        output = io.StringIO()
        with mock.patch(
            "scripts.check_xfeat_persistent_v2.load_feature_frames",
            return_value=_persistent_frames(),
        ), contextlib.redirect_stdout(output):
            return_code = main(
                [
                    "/does/not/write/features.bag",
                    "--warmup-frames",
                    "4",
                ]
            )
        payload = json.loads(output.getvalue())
        self.assertEqual(return_code, 0)
        self.assertEqual(payload["status"], "PASS")
        self.assertTrue(payload["pass"])

    def test_cli_reports_input_error_as_json_and_exit_two(self) -> None:
        output = io.StringIO()
        with mock.patch(
            "scripts.check_xfeat_persistent_v2.load_feature_frames",
            side_effect=ValueError("bad bag"),
        ), contextlib.redirect_stdout(output):
            return_code = main(["/bad/features.bag"])
        payload = json.loads(output.getvalue())
        self.assertEqual(return_code, 2)
        self.assertEqual(payload["status"], "ERROR")
        self.assertEqual(payload["error"]["type"], "ValueError")


if __name__ == "__main__":
    unittest.main()
