#!/usr/bin/env python3
"""Synthetic adapter tests; no frozen trajectory metric is evaluated here."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts import evaluate_hfnet_v6_phase_f_h03_1800_3600_gt_proxy_v1 as target
from scripts import evaluate_vins_common_support as legacy_vins
from scripts.trajectory_eval_core import quaternion_xyzw_to_rotation


class HfnetH03ProxyAdapterTests(unittest.TestCase):
    def test_xyzw_to_wxyz_component_adapter_and_exact_roundtrip(self) -> None:
        xyzw = np.asarray(
            [
                [0.1, 0.2, 0.3, 0.9],
                [-0.4, 0.5, -0.6, 0.7],
            ],
            dtype=float,
        )
        wxyz = target.quaternion_xyzw_to_wxyz(xyzw)
        np.testing.assert_array_equal(
            wxyz,
            [[0.9, 0.1, 0.2, 0.3], [0.7, -0.4, 0.5, -0.6]],
        )
        np.testing.assert_array_equal(target.quaternion_wxyz_to_xyzw(wxyz), xyzw)

    def test_world_t_body_times_body_t_camera_rotates_lever_arm(self) -> None:
        sine = np.sqrt(0.5)
        body_position = np.asarray([[10.0, 20.0, 30.0]])
        body_quaternion_xyzw = np.asarray([[0.0, 0.0, sine, sine]])
        body_t_camera = np.eye(4)
        body_t_camera[:3, 3] = [1.0, 2.0, 3.0]

        camera_position, camera_quaternion = target.transform_body_poses_to_sensor(
            body_position, body_quaternion_xyzw, body_t_camera
        )
        np.testing.assert_allclose(camera_position, [[8.0, 21.0, 33.0]], atol=1e-12)
        np.testing.assert_allclose(
            quaternion_xyzw_to_rotation(camera_quaternion[0]),
            quaternion_xyzw_to_rotation(body_quaternion_xyzw[0]),
            atol=1e-12,
        )

    def test_decimal_epoch_timestamp_association_is_exact(self) -> None:
        base_ns = 1_523_966_900_000_000_123
        camera_ns = [base_ns + 50_000_000 * index for index in range(1801)]
        rows = [
            f"{camera_ns[index]}.000000 {index} 0 0 0 0 0 1\n"
            for index in range(875, 1801)
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic_hfnet_trajectory.txt"
            path.write_text("".join(rows), encoding="ascii")
            loaded = target.load_body_trajectory(path, camera_ns)

        np.testing.assert_array_equal(loaded["indices"], np.arange(875, 1801))
        np.testing.assert_array_equal(
            loaded["stamps_ns"], np.asarray(camera_ns[875:1801], dtype=np.int64)
        )
        self.assertEqual(int(np.max(loaded["association_errors_ns"])), 0)

    def test_wrong_inverse_and_legacy_wxyz_loader_are_negative_controls(self) -> None:
        body_t_camera = np.eye(4)
        body_t_camera[:3, 3] = [0.25, -0.5, 0.75]
        body_position = np.asarray([[1.0, 2.0, 3.0]])
        body_quaternion_xyzw = np.asarray([[0.0, 0.0, 0.0, 1.0]])
        correct, _ = target.transform_body_poses_to_sensor(
            body_position, body_quaternion_xyzw, body_t_camera
        )
        wrong_inverse, _ = target.transform_body_poses_to_sensor(
            body_position, body_quaternion_xyzw, np.linalg.inv(body_t_camera)
        )
        np.testing.assert_allclose(correct, [[1.25, 1.5, 3.75]], atol=1e-12)
        self.assertFalse(np.allclose(wrong_inverse, correct))

        raw_xyzw = np.asarray([0.0, 0.0, np.sqrt(0.5), np.sqrt(0.5)])
        legacy_interpretation = np.asarray(
            [raw_xyzw[1], raw_xyzw[2], raw_xyzw[3], raw_xyzw[0]]
        )
        self.assertFalse(np.allclose(legacy_interpretation, raw_xyzw))
        with tempfile.TemporaryDirectory() as directory:
            raw_path = Path(directory) / "raw_hfnet_tum.txt"
            raw_path.write_text("1 0 0 0 0 0 0 1\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "expected at least 8 columns"):
                legacy_vins.load_vins_body_csv(raw_path)

    def test_closed_score_endpoint_is_not_forced_onto_uniform_grid(self) -> None:
        score_start_ns = 1_523_966_967_662_354_150
        score_end_ns = 1_523_967_012_680_410_986
        grid_ns = np.arange(
            score_start_ns,
            score_end_ns + 1,
            500_000_000,
            dtype=np.int64,
        )
        self.assertEqual(len(grid_ns), 91)
        self.assertEqual(int(grid_ns[0]), score_start_ns)
        self.assertEqual(int(grid_ns[-1]), score_start_ns + 45_000_000_000)
        self.assertEqual(score_end_ns - int(grid_ns[-1]), 18_056_836)
        self.assertNotIn(score_end_ns, set(int(value) for value in grid_ns))


if __name__ == "__main__":
    unittest.main()
