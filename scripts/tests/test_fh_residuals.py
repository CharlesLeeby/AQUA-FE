from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.geometry.fh_residuals import (
    FHConfig,
    classify_correspondences,
    fit_base_models,
    homography_residual_px,
)


def _planar_grid():
    points = np.asarray(
        [(x, y) for y in (40, 100, 160, 220) for x in (40, 120, 200, 280, 360)],
        dtype=np.float64,
    )
    moved = points + np.asarray([7.0, -3.0])
    ids = np.arange(100, 100 + len(points), dtype=np.int64)
    return ids, points, moved


class FHResidualTests(unittest.TestCase):
    def test_fit_is_sorted_and_repeatable(self) -> None:
        ids, previous, current = _planar_grid()
        first = fit_base_models(ids[::-1], previous[::-1], current[::-1])
        second = fit_base_models(ids, previous, current)
        self.assertEqual(first.evidence.input_track_ids, tuple(ids))
        self.assertEqual(first.evidence.fit_hash, second.evidence.fit_hash)
        self.assertIn("H", first.evidence.valid_models)

    def test_homography_residual_has_pixel_units(self) -> None:
        _, previous, current = _planar_grid()
        homography = np.asarray([[1, 0, 7], [0, 1, -3], [0, 0, 1]], dtype=float)
        residual = homography_residual_px(homography, previous, current)
        np.testing.assert_allclose(residual, 0.0, atol=1e-12)
        shifted = current.copy()
        shifted[0] += np.asarray([3.0, 4.0])
        residual = homography_residual_px(homography, previous[:1], shifted[:1])
        self.assertAlmostEqual(float(residual[0]), 5.0, places=10)

    def test_normalized_fh_accept_and_reject(self) -> None:
        ids, previous, current = _planar_grid()
        fit = fit_base_models(ids, previous, current)
        candidates0 = np.asarray([[80.0, 80.0], [80.0, 80.0]])
        candidates1 = np.asarray([[87.0, 77.0], [87.0, 97.0]])
        decisions = classify_correspondences(fit, candidates0, candidates1)
        self.assertTrue(decisions[0].accepted)
        self.assertEqual(decisions[0].reason, "CORRECTNESS_PASS")
        self.assertFalse(decisions[1].accepted)
        self.assertEqual(decisions[1].reason, "FH_RESIDUAL_REJECT")

    def test_no_valid_model_rejects_by_default(self) -> None:
        ids = np.asarray([1, 2, 3])
        points = np.asarray([[0, 0], [1, 1], [2, 2]], dtype=float)
        fit = fit_base_models(ids, points, points)
        self.assertFalse(fit.has_valid_model)
        decision = classify_correspondences(fit, points[:1], points[:1])[0]
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "NO_VALID_BASE_MODEL")
        self.assertEqual(decision.normalized_residual, FHConfig().e_max)

    def test_fit_hash_changes_with_frozen_threshold(self) -> None:
        ids, previous, current = _planar_grid()
        first = fit_base_models(ids, previous, current, FHConfig(homography_threshold_px=5.0))
        second = fit_base_models(ids, previous, current, FHConfig(homography_threshold_px=4.0))
        self.assertNotEqual(first.evidence.fit_hash, second.evidence.fit_hash)


if __name__ == "__main__":
    unittest.main()

