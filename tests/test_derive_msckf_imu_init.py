from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "derive_msckf_imu_init.py"
SPEC = importlib.util.spec_from_file_location("derive_msckf_imu_init", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def jpl_rotation(quaternion: np.ndarray) -> np.ndarray:
    vector = quaternion[:3]
    scalar = quaternion[3]
    skew = np.array(
        [
            [0.0, -vector[2], vector[1]],
            [vector[2], 0.0, -vector[0]],
            [-vector[1], vector[0], 0.0],
        ]
    )
    return (
        (2.0 * scalar * scalar - 1.0) * np.eye(3)
        - 2.0 * scalar * skew
        + 2.0 * np.outer(vector, vector)
    )


class DeriveMsckfImuInitTest(unittest.TestCase):
    def test_quaternion_maps_global_gravity_to_measured_axis(self) -> None:
        acceleration = np.array([1.6, 8.5, 4.5])
        quaternion = MODULE.gravity_aligned_jpl_quaternion(acceleration)
        rotation = jpl_rotation(quaternion)

        self.assertAlmostEqual(float(np.linalg.norm(quaternion)), 1.0, places=12)
        np.testing.assert_allclose(
            rotation @ np.array([0.0, 0.0, 1.0]),
            acceleration / np.linalg.norm(acceleration),
            atol=1e-12,
        )
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=12)

    def test_rejects_invalid_acceleration(self) -> None:
        with self.assertRaisesRegex(ValueError, "too small"):
            MODULE.gravity_aligned_jpl_quaternion(np.zeros(3))
        with self.assertRaisesRegex(ValueError, "finite 3-vector"):
            MODULE.gravity_aligned_jpl_quaternion(
                np.array([float("nan"), 0.0, 1.0])
            )

    def test_rotation_between_vectors_handles_general_and_antiparallel(self) -> None:
        source = np.array([0.2, -0.3, -0.9])
        target = np.array([0.0, 0.0, 1.0])
        rotation = MODULE.rotation_between_vectors(source, target)
        np.testing.assert_allclose(
            rotation @ (source / np.linalg.norm(source)), target, atol=1e-12
        )
        self.assertAlmostEqual(float(np.linalg.det(rotation)), 1.0, places=12)

        antiparallel = MODULE.rotation_between_vectors(-target, target)
        np.testing.assert_allclose(
            antiparallel @ (-target), target, atol=1e-12
        )
        self.assertAlmostEqual(float(np.linalg.det(antiparallel)), 1.0, places=12)


if __name__ == "__main__":
    unittest.main()
