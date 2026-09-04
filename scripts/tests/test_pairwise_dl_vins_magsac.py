from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

import numpy as np

from uw_frontend.evaluation.run_frontend_eval import load_config
from uw_frontend.geometry.dl_vins_magsac import DlVinsMagsacResult
from uw_frontend.matchers.base import BaseMatcher, MatchResult
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.pairwise_matcher_tracker import (
    PairwiseMatcherTracker,
    PairwiseMatcherTrackerConfig,
)


ROOT = Path(__file__).resolve().parents[2]


class _SequenceMatcher(BaseMatcher):
    name = "superpoint_lightglue"

    def __init__(self, results: list[MatchResult]) -> None:
        self.results = list(results)
        self.match_calls = 0

    def match(self, _image0: np.ndarray, _image1: np.ndarray) -> MatchResult:
        self.match_calls += 1
        if not self.results:
            raise AssertionError("unexpected matcher call")
        return self.results.pop(0)


def _result(points0, points1, confidences) -> MatchResult:
    return MatchResult(
        points0=np.asarray(points0, dtype=np.float32),
        points1=np.asarray(points1, dtype=np.float32),
        confidences=np.asarray(confidences, dtype=np.float32),
        method="superpoint_lightglue",
    )


def _exact_config(**overrides) -> PairwiseMatcherTrackerConfig:
    values = dict(
        max_features=350,
        association_radius=0.25,
        min_confidence=0.0,
        persistent_id_mode="continuity_first_v2",
        use_ncc=False,
        geometry_mode="dl_vins_magsac",
    )
    values.update(overrides)
    return PairwiseMatcherTrackerConfig(**values)


class PairwiseDlVinsMagsacTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
        self.quality = score_image_quality(self.image)
        self.texture_patch = mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.local_texture_scores",
            side_effect=lambda _image, points: np.ones((len(points),), dtype=np.float32),
        )
        self.texture_patch.start()

    def tearDown(self) -> None:
        self.texture_patch.stop()

    def test_default_disabled_does_not_probe_usac_and_keeps_ncc_path(self) -> None:
        matcher = _SequenceMatcher(
            [_result([(0, 0), (10, 0), (20, 0)], [(1, 0), (11, 0), (21, 0)], [0.9, 0.8, 0.7])]
        )
        with mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.require_dl_vins_magsac_available",
            side_effect=AssertionError("disabled path probed USAC"),
        ) as capability, mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.filter_dl_vins_magsac",
            side_effect=AssertionError("disabled path ran geometry"),
        ) as geometry, mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker._patch_ncc",
            return_value=np.asarray([0.9, 0.8, 0.7], dtype=np.float32),
        ) as ncc:
            tracker = PairwiseMatcherTracker(matcher, PairwiseMatcherTrackerConfig())
            tracker.process(self.image, self.quality)
            tracks, diagnostics = tracker.process(self.image, self.quality)

        capability.assert_not_called()
        geometry.assert_not_called()
        ncc.assert_called_once()
        np.testing.assert_array_equal(tracks.ids, np.asarray([0, 1, 2], dtype=np.int64))
        np.testing.assert_array_equal(tracks.ages, np.ones((3,), dtype=np.int32))
        np.testing.assert_array_equal(
            tracks.points,
            np.asarray([(1, 0), (11, 0), (21, 0)], dtype=np.float32),
        )
        np.testing.assert_array_equal(
            tracks.ncc_scores,
            np.asarray([0.9, 0.8, 0.7], dtype=np.float32),
        )
        self.assertEqual(diagnostics.added_features, 3)
        self.assertEqual(tracker.last_pairwise_geometry_action, "disabled")
        self.assertEqual(tracker.last_pairwise_geometry_candidate_count, 3)

    def test_enabled_without_usac_fails_before_matcher_use(self) -> None:
        matcher = _SequenceMatcher([])
        with mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.require_dl_vins_magsac_available",
            side_effect=RuntimeError(
                "cv2.USAC_MAGSAC requires an isolated OpenCV build"
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, r"USAC_MAGSAC.*OpenCV"):
                PairwiseMatcherTracker(
                    matcher,
                    _exact_config(),
                    point_normalizer=lambda points: points,
                    geometry_focal_mean_px=500.0,
                )
        self.assertEqual(matcher.match_calls, 0)

    def test_geometry_filters_before_id_association_and_ncc_is_not_run(self) -> None:
        first = _result([(0, 0)], [(10, 10)], [0.8])
        second = _result(
            [(10, 10), (10.2, 10), (40, 40)],
            [(11, 10), (11.2, 10), (41, 40)],
            [0.99, 0.80, 0.10],
        )
        geometry_results = [
            DlVinsMagsacResult(
                keep_mask=np.asarray([True]),
                candidate_count=1,
                inlier_count=1,
                inlier_ratio=1.0,
                action="filter_inliers",
                reason="magsac_inlier_mask_applied",
            ),
            DlVinsMagsacResult(
                keep_mask=np.asarray([False, True]),
                candidate_count=2,
                inlier_count=1,
                inlier_ratio=0.5,
                action="filter_inliers",
                reason="magsac_inlier_mask_applied",
            ),
        ]
        with mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.require_dl_vins_magsac_available"
        ), mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.filter_dl_vins_magsac",
            side_effect=geometry_results,
        ) as geometry, mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker._patch_ncc",
            side_effect=AssertionError("NCC must be disabled"),
        ) as ncc:
            tracker = PairwiseMatcherTracker(
                _SequenceMatcher([first, second]),
                _exact_config(min_confidence=0.5),
                point_normalizer=lambda points: np.asarray(points, dtype=np.float64),
                geometry_focal_mean_px=500.0,
            )
            tracker.process(self.image, self.quality)
            tracks1, _ = tracker.process(self.image, self.quality)
            tracks2, diagnostics2 = tracker.process(self.image, self.quality)

        ncc.assert_not_called()
        self.assertEqual(geometry.call_count, 2)
        second_prev = geometry.call_args_list[1].args[0]
        second_cur = geometry.call_args_list[1].args[1]
        np.testing.assert_allclose(second_prev, [[10, 10], [10.2, 10]])
        np.testing.assert_allclose(second_cur, [[11, 10], [11.2, 10]])
        np.testing.assert_array_equal(tracks1.ids, tracks2.ids)
        np.testing.assert_array_equal(tracks2.ages, np.asarray([2], dtype=np.int32))
        np.testing.assert_allclose(tracks2.points, np.asarray([[11.2, 10]], dtype=np.float32))
        np.testing.assert_array_equal(tracks2.ncc_scores, np.ones((1,), dtype=np.float32))
        self.assertTrue(np.all(np.isfinite(tracks2.qualities)))
        self.assertEqual(diagnostics2.median_ncc, 1.0)
        self.assertEqual(tracker.next_id, 1)
        self.assertEqual(tracker.last_pairwise_geometry_candidate_count, 2)
        self.assertEqual(tracker.last_pairwise_geometry_inlier_count, 1)
        self.assertEqual(tracker.last_pairwise_geometry_inlier_ratio, 0.5)
        self.assertEqual(tracker.last_pairwise_geometry_action, "filter_inliers")

    def test_geometry_rejection_is_not_backfilled_after_cap(self) -> None:
        count = 400
        points0 = np.column_stack((np.arange(count), np.zeros(count)))
        points1 = points0 + np.asarray([1.0, 0.0])
        keep = np.zeros((count,), dtype=bool)
        keep[:200] = True
        result = DlVinsMagsacResult(
            keep_mask=keep,
            candidate_count=count,
            inlier_count=200,
            inlier_ratio=0.5,
            action="filter_inliers",
            reason="test_mask",
        )
        with mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.require_dl_vins_magsac_available"
        ), mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.filter_dl_vins_magsac",
            return_value=result,
        ), mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker._patch_ncc",
            side_effect=AssertionError("NCC must be disabled"),
        ):
            tracker = PairwiseMatcherTracker(
                _SequenceMatcher([_result(points0, points1, np.ones(count))]),
                _exact_config(),
                point_normalizer=lambda points: points,
                geometry_focal_mean_px=500.0,
            )
            tracker.process(self.image, self.quality)
            tracks, _ = tracker.process(self.image, self.quality)

        self.assertEqual(len(tracks), 200)
        self.assertEqual(tracker.next_id, 200)
        np.testing.assert_allclose(tracks.points, points1[:200].astype(np.float32))

    def test_geometry_diagnostics_do_not_leak_across_empty_frame_or_reset(self) -> None:
        success = DlVinsMagsacResult(
            keep_mask=np.asarray([True]),
            candidate_count=1,
            inlier_count=1,
            inlier_ratio=1.0,
            action="filter_inliers",
            reason="magsac_inlier_mask_applied",
        )
        empty = _result([], [], [])
        with mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.require_dl_vins_magsac_available"
        ), mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.filter_dl_vins_magsac",
            return_value=success,
        ):
            tracker = PairwiseMatcherTracker(
                _SequenceMatcher([_result([(0, 0)], [(1, 0)], [1.0]), empty]),
                _exact_config(),
                point_normalizer=lambda points: points,
                geometry_focal_mean_px=500.0,
            )
            tracker.process(self.image, self.quality)
            tracker.process(self.image, self.quality)
            tracker.process(self.image, self.quality)
            self.assertEqual(tracker.last_pairwise_geometry_candidate_count, 0)
            self.assertEqual(tracker.last_pairwise_geometry_action, "not_run")
            self.assertEqual(tracker.last_pairwise_geometry_reason, "matcher_empty")
            self.assertTrue(math.isnan(tracker.last_pairwise_geometry_inlier_ratio))
            tracker.reset()
            self.assertEqual(tracker.last_pairwise_geometry_candidate_count, 0)
            self.assertEqual(tracker.last_pairwise_geometry_reason, "reset")

    def test_invalid_config_values_fail_fast(self) -> None:
        with self.assertRaisesRegex(ValueError, "use_ncc must be a boolean"):
            PairwiseMatcherTracker(
                _SequenceMatcher([]),
                PairwiseMatcherTrackerConfig(use_ncc="false"),  # type: ignore[arg-type]
            )
        with self.assertRaisesRegex(ValueError, "geometry_mode"):
            PairwiseMatcherTracker(
                _SequenceMatcher([]),
                PairwiseMatcherTrackerConfig(geometry_mode="typo"),
            )


class DlVinsMagsacConfigAndMetricsTests(unittest.TestCase):
    def test_new_config_is_an_additive_exact_comparator(self) -> None:
        old_cfg = load_config(
            ROOT / "uw_frontend/configs/experiments/literature_splg_direct_persistent_v1.yaml"
        )
        new_cfg = load_config(
            ROOT
            / "uw_frontend/configs/experiments/literature_splg_direct_dl_vins_magsac_v1.yaml"
        )
        old_pairwise = PairwiseMatcherTrackerConfig(**old_cfg["pairwise"])
        new_pairwise = PairwiseMatcherTrackerConfig(**new_cfg["pairwise"])
        self.assertIs(old_pairwise.use_ncc, True)
        self.assertEqual(old_pairwise.geometry_mode, "disabled")
        self.assertIs(new_pairwise.use_ncc, False)
        self.assertEqual(new_pairwise.geometry_mode, "dl_vins_magsac")
        self.assertEqual(new_pairwise.max_features, 350)
        self.assertEqual(new_pairwise.association_radius, 0.25)
        self.assertEqual(new_pairwise.persistent_id_mode, "continuity_first_v2")
        self.assertEqual(new_cfg["lightglue"]["filter_threshold"], 0.1)
        self.assertIs(new_cfg["lightglue"]["cache_sparse_features"], True)
        self.assertIs(new_cfg["measurement_selection"]["enabled"], False)
        self.assertEqual(new_cfg["backend_quality"]["mode"], "const")

    def test_exporter_wires_each_geometry_metric_into_header_and_row(self) -> None:
        source = (ROOT / "uw_frontend/ros/export_vins_features.py").read_text()
        columns = [
            "pairwise_geometry_candidate_count",
            "pairwise_geometry_inlier_count",
            "pairwise_geometry_inlier_ratio",
            "pairwise_geometry_action",
            "pairwise_geometry_reason",
        ]
        for column in columns:
            self.assertEqual(source.count(f'"{column}"'), 2, column)
        self.assertIn("**_pairwise_geometry_metrics(tracker)", source)

        from uw_frontend.ros.export_vins_features import _pairwise_geometry_metrics

        mapped = _pairwise_geometry_metrics(
            SimpleNamespace(
                last_pairwise_geometry_candidate_count=20,
                last_pairwise_geometry_inlier_count=12,
                last_pairwise_geometry_inlier_ratio=0.6,
                last_pairwise_geometry_action="filter_inliers",
                last_pairwise_geometry_reason="magsac_inlier_mask_applied",
            )
        )
        self.assertEqual(mapped["pairwise_geometry_candidate_count"], 20)
        self.assertEqual(mapped["pairwise_geometry_inlier_count"], 12)
        self.assertEqual(mapped["pairwise_geometry_inlier_ratio"], 0.6)
        self.assertEqual(mapped["pairwise_geometry_action"], "filter_inliers")
        self.assertEqual(mapped["pairwise_geometry_reason"], "magsac_inlier_mask_applied")
        defaults = _pairwise_geometry_metrics(SimpleNamespace())
        self.assertEqual(defaults["pairwise_geometry_candidate_count"], 0)
        self.assertEqual(defaults["pairwise_geometry_inlier_count"], 0)
        self.assertTrue(math.isnan(defaults["pairwise_geometry_inlier_ratio"]))
        self.assertEqual(defaults["pairwise_geometry_action"], "not_applicable")
        self.assertEqual(defaults["pairwise_geometry_reason"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
