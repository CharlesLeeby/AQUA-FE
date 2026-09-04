from __future__ import annotations

import os
import unittest
from unittest import mock

import cv2
import numpy as np

from uw_frontend.geometry import dl_vins_magsac as geometry


def _points(count: int) -> tuple[np.ndarray, np.ndarray]:
    points0 = np.column_stack((np.linspace(-0.2, 0.2, count), np.linspace(-0.1, 0.1, count)))
    points1 = points0 + np.asarray([0.01, -0.002])
    return points0.astype(np.float64), points1.astype(np.float64)


class DlVinsMagsacContractTests(unittest.TestCase):
    def _call_with_mask(self, mask: np.ndarray):
        points0, points1 = _points(10)
        with mock.patch.object(geometry.cv2, "USAC_MAGSAC", 38, create=True), mock.patch.object(
            geometry.cv2,
            "findEssentialMat",
            return_value=(np.eye(3), mask),
        ) as estimator:
            result = geometry.filter_dl_vins_magsac(
                points0,
                points1,
                focal_mean_px=500.0,
            )
        return result, estimator

    def test_capability_gate_has_no_classic_ransac_fallback(self) -> None:
        with mock.patch.object(geometry.cv2, "USAC_MAGSAC", None, create=True):
            with self.assertRaisesRegex(RuntimeError, r"USAC_MAGSAC.*OpenCV"):
                geometry.require_dl_vins_magsac_available()

    def test_exact_estimator_parameters_and_mask_filter(self) -> None:
        mask = np.asarray([[1], [0], [1], [1], [0], [1], [1], [0], [1], [0]], dtype=np.uint8)
        result, estimator = self._call_with_mask(mask)
        args, kwargs = estimator.call_args
        np.testing.assert_array_equal(args[2], np.eye(3))
        self.assertEqual(kwargs["method"], 38)
        self.assertEqual(kwargs["prob"], 0.999)
        self.assertAlmostEqual(kwargs["threshold"], 1.0 / 500.0)
        self.assertEqual(kwargs["maxIters"], 200)
        np.testing.assert_array_equal(
            result.keep_mask,
            np.asarray([True, False, True, True, False, True, True, False, True, False]),
        )
        self.assertEqual(result.candidate_count, 10)
        self.assertEqual(result.inlier_count, 6)
        self.assertEqual(result.inlier_ratio, 0.6)
        self.assertEqual(result.action, "filter_inliers")

    def test_fewer_than_eight_is_fail_open_without_estimator_call(self) -> None:
        points0, points1 = _points(7)
        with mock.patch.object(geometry.cv2, "USAC_MAGSAC", 38, create=True), mock.patch.object(
            geometry.cv2,
            "findEssentialMat",
            side_effect=AssertionError("estimator must not run"),
        ) as estimator:
            result = geometry.filter_dl_vins_magsac(
                points0,
                points1,
                focal_mean_px=500.0,
            )
        estimator.assert_not_called()
        np.testing.assert_array_equal(result.keep_mask, np.ones((7,), dtype=bool))
        self.assertEqual(result.action, "keep_all_fail_open")
        self.assertEqual(result.reason, "fewer_than_8_correspondences")
        self.assertTrue(np.isnan(result.inlier_ratio))

    def test_exception_missing_and_wrong_length_masks_are_fail_open(self) -> None:
        points0, points1 = _points(10)
        cases = [
            (RuntimeError("boom"), "find_essential_exception:RuntimeError"),
            ((None, None), "missing_inlier_mask"),
            ((np.eye(3), np.ones((9, 1), dtype=np.uint8)), "invalid_inlier_mask_length"),
        ]
        for outcome, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason), mock.patch.object(
                geometry.cv2, "USAC_MAGSAC", 38, create=True
            ), mock.patch.object(geometry.cv2, "findEssentialMat") as estimator:
                if isinstance(outcome, Exception):
                    estimator.side_effect = outcome
                else:
                    estimator.return_value = outcome
                result = geometry.filter_dl_vins_magsac(
                    points0,
                    points1,
                    focal_mean_px=500.0,
                )
                np.testing.assert_array_equal(result.keep_mask, np.ones((10,), dtype=bool))
                self.assertEqual(result.action, "keep_all_fail_open")
                self.assertEqual(result.reason, expected_reason)

    def test_inlier_ratio_boundary_matches_official_strict_less_than_gate(self) -> None:
        below = np.asarray([1, 1, 1, 1, 0, 0, 0, 0, 0, 0], dtype=np.uint8)
        result_below, _ = self._call_with_mask(below)
        np.testing.assert_array_equal(result_below.keep_mask, np.ones((10,), dtype=bool))
        self.assertEqual(result_below.inlier_count, 4)
        self.assertEqual(result_below.inlier_ratio, 0.4)
        self.assertEqual(result_below.action, "keep_all_fail_open")
        self.assertEqual(result_below.reason, "inlier_ratio_below_0.5")

        boundary = np.asarray([True, True, True, True, True, False, False, False, False, False])
        result_boundary, _ = self._call_with_mask(boundary)
        np.testing.assert_array_equal(result_boundary.keep_mask, boundary)
        self.assertEqual(result_boundary.inlier_count, 5)
        self.assertEqual(result_boundary.inlier_ratio, 0.5)
        self.assertEqual(result_boundary.action, "filter_inliers")


class DlVinsMagsacSyntheticTests(unittest.TestCase):
    def test_synthetic_usac_magsac_geometry(self) -> None:
        require_usac = os.environ.get("AQUA_REQUIRE_USAC_MAGSAC") == "1"
        if getattr(cv2, "USAC_MAGSAC", None) is None:
            if require_usac:
                self.fail("AQUA_REQUIRE_USAC_MAGSAC=1 but cv2.USAC_MAGSAC is unavailable")
            self.skipTest("system OpenCV has no USAC_MAGSAC")

        rng = np.random.default_rng(20260810)
        count = 160
        xyz = np.column_stack(
            (
                rng.uniform(-2.0, 2.0, count),
                rng.uniform(-1.4, 1.4, count),
                rng.uniform(4.0, 9.0, count),
            )
        )
        rotation, _ = cv2.Rodrigues(np.asarray([0.015, -0.035, 0.010], dtype=np.float64))
        translation = np.asarray([0.22, 0.015, 0.025], dtype=np.float64)
        points0 = xyz[:, :2] / xyz[:, 2:3]
        xyz1 = (rotation @ xyz.T).T + translation
        points1 = xyz1[:, :2] / xyz1[:, 2:3]
        points0 += rng.normal(0.0, 0.00015, points0.shape)
        points1 += rng.normal(0.0, 0.00015, points1.shape)
        outliers = rng.choice(count, size=32, replace=False)
        points1[outliers] = np.column_stack(
            (
                rng.uniform(-0.40, 0.40, len(outliers)),
                rng.uniform(-0.30, 0.30, len(outliers)),
            )
        )
        true_inlier = np.ones((count,), dtype=bool)
        true_inlier[outliers] = False

        cv2.setRNGSeed(0)
        result = geometry.filter_dl_vins_magsac(
            points0,
            points1,
            focal_mean_px=543.0,
        )
        self.assertEqual(result.keep_mask.shape, (count,))
        self.assertEqual(result.keep_mask.dtype, np.bool_)
        self.assertEqual(result.action, "filter_inliers")
        self.assertGreaterEqual(np.mean(result.keep_mask[true_inlier]), 0.80)
        self.assertGreaterEqual(np.mean(~result.keep_mask[~true_inlier]), 0.50)
        self.assertGreaterEqual(result.inlier_ratio, 0.5)


if __name__ == "__main__":
    unittest.main()
