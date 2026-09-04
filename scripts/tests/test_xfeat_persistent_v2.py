from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from uw_frontend.matchers.base import BaseMatcher, MatchResult
from uw_frontend.matchers.xfeat_adapter import XFeatMatcher
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.pairwise_matcher_tracker import (
    PairwiseMatcherTracker,
    PairwiseMatcherTrackerConfig,
)


class _SequenceMatcher(BaseMatcher):
    name = "xfeat"

    def __init__(self, results: list[MatchResult]) -> None:
        self.results = list(results)

    def match(self, _image0: np.ndarray, _image1: np.ndarray) -> MatchResult:
        if not self.results:
            raise AssertionError("unexpected matcher call")
        return self.results.pop(0)


def _result(points0, points1, confidences) -> MatchResult:
    return MatchResult(
        points0=np.asarray(points0, dtype=np.float32),
        points1=np.asarray(points1, dtype=np.float32),
        confidences=np.asarray(confidences, dtype=np.float32),
        method="xfeat",
    )


class PairwisePersistentTrackerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = np.arange(64 * 64, dtype=np.uint8).reshape(64, 64)
        self.quality = score_image_quality(self.image)
        self.ncc_patch = mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker._patch_ncc",
            side_effect=lambda _a, _b, p0, _p1, radius=5: np.ones(
                (len(p0),), dtype=np.float32
            ),
        )
        self.texture_patch = mock.patch(
            "uw_frontend.tracking.pairwise_matcher_tracker.local_texture_scores",
            side_effect=lambda _image, points: np.ones(
                (len(points),), dtype=np.float32
            ),
        )
        self.ncc_mock = self.ncc_patch.start()
        self.texture_mock = self.texture_patch.start()

    def tearDown(self) -> None:
        self.texture_patch.stop()
        self.ncc_patch.stop()

    def _run_two_matches(self, mode: str):
        first = _result(
            [(0, 0), (10, 0), (20, 0), (30, 0), (40, 0), (50, 0)],
            [(1, 0), (11, 0), (21, 0), (31, 0), (41, 0), (51, 0)],
            [0.99, 0.98, 0.97, 0.96, 0.95, 0.94],
        )
        # The continuations of the first capped state occur after three high-score
        # births.  A pre-association cap loses all IDs; a continuity-first cap does
        # not.
        second = _result(
            [(100, 0), (110, 0), (120, 0), (1, 0), (11, 0), (21, 0)],
            [(101, 0), (111, 0), (121, 0), (2, 0), (12, 0), (22, 0)],
            [0.99, 0.98, 0.97, 0.90, 0.89, 0.88],
        )
        tracker = PairwiseMatcherTracker(
            _SequenceMatcher([first, second]),
            PairwiseMatcherTrackerConfig(
                max_features=3,
                association_radius=2.0,
                min_ncc=0.0,
                persistent_id_mode=mode,
            ),
        )
        tracker.process(self.image, self.quality)  # primes prev_image
        tracks1, _ = tracker.process(self.image, self.quality)
        tracks2, _ = tracker.process(self.image, self.quality)
        return tracks1, tracks2

    def test_continuity_first_caps_after_id_association(self) -> None:
        tracks1, tracks2 = self._run_two_matches("continuity_first_v2")
        self.assertEqual(set(tracks1.ids), set(tracks2.ids))
        self.assertTrue(np.all(tracks2.ages == 2))
        self.assertTrue(np.allclose(tracks2.points[:, 0], [2, 12, 22]))
        self.assertEqual(
            [len(call.args[2]) for call in self.ncc_mock.call_args_list],
            [6, 6],
        )
        self.assertEqual(
            [len(call.args[1]) for call in self.texture_mock.call_args_list],
            [3, 3],
        )

    def test_legacy_preassociation_cap_loses_ids(self) -> None:
        tracks1, tracks2 = self._run_two_matches("legacy")
        self.assertFalse(set(tracks1.ids).intersection(tracks2.ids))
        self.assertTrue(np.all(tracks2.ages == 1))

    def test_exact_endpoint_wins_before_nearby_candidate(self) -> None:
        first = _result([(0, 0)], [(10, 10)], [0.8])
        second = _result(
            [(10.5, 10), (10, 10)],
            [(11.5, 10), (11, 10)],
            [0.99, 0.80],
        )
        tracker = PairwiseMatcherTracker(
            _SequenceMatcher([first, second]),
            PairwiseMatcherTrackerConfig(
                max_features=1,
                association_radius=2.0,
                min_ncc=0.0,
                persistent_id_mode="continuity_first_v2",
            ),
        )
        tracker.process(self.image, self.quality)
        tracks1, _ = tracker.process(self.image, self.quality)
        tracks2, _ = tracker.process(self.image, self.quality)
        self.assertEqual(tracks1.ids.tolist(), tracks2.ids.tolist())
        self.assertEqual(tracks2.ages.tolist(), [2])
        self.assertTrue(np.allclose(tracks2.points[0], [11, 10]))

    def test_low_ncc_exact_endpoint_cannot_steal_persistent_id(self) -> None:
        first = _result([(0, 0)], [(10, 10)], [0.8])
        second = _result(
            [(10, 10), (10.2, 10)],
            [(11, 10), (11.2, 10)],
            [0.99, 0.80],
        )
        self.ncc_mock.side_effect = [
            np.asarray([1.0], dtype=np.float32),
            np.asarray([0.1, 0.9], dtype=np.float32),
        ]
        tracker = PairwiseMatcherTracker(
            _SequenceMatcher([first, second]),
            PairwiseMatcherTrackerConfig(
                max_features=1,
                association_radius=2.0,
                min_ncc=0.35,
                persistent_id_mode="continuity_first_v2",
            ),
        )
        tracker.process(self.image, self.quality)
        tracks1, _ = tracker.process(self.image, self.quality)
        tracks2, _ = tracker.process(self.image, self.quality)
        self.assertEqual(tracks1.ids.tolist(), tracks2.ids.tolist())
        self.assertEqual(tracks2.ages.tolist(), [2])
        self.assertTrue(np.allclose(tracks2.points[0], [11.2, 10]))

    def test_ncc_rejection_backfills_and_does_not_advance_next_id(self) -> None:
        first = _result([(0, 0)], [(10, 10)], [0.8])
        second = _result(
            [(100, 10), (200, 10)],
            [(101, 10), (201, 10)],
            [0.99, 0.80],
        )
        self.ncc_mock.side_effect = [
            np.asarray([1.0], dtype=np.float32),
            np.asarray([0.1, 0.9], dtype=np.float32),
        ]
        tracker = PairwiseMatcherTracker(
            _SequenceMatcher([first, second]),
            PairwiseMatcherTrackerConfig(
                max_features=2,
                association_radius=2.0,
                min_ncc=0.35,
                persistent_id_mode="continuity_first_v2",
            ),
        )
        tracker.process(self.image, self.quality)
        tracker.process(self.image, self.quality)
        tracks2, _ = tracker.process(self.image, self.quality)
        self.assertEqual(tracks2.ids.tolist(), [1])
        self.assertEqual(tracker.next_id, 2)

    def test_ncc_breaks_equal_age_and_confidence_cap_tie(self) -> None:
        first = _result(
            [(0, 0), (20, 0)],
            [(10, 0), (30, 0)],
            [0.8, 0.8],
        )
        second = _result(
            [(10, 0), (30, 0)],
            [(11, 0), (31, 0)],
            [0.8, 0.8],
        )
        self.ncc_mock.side_effect = [
            np.asarray([1.0, 1.0], dtype=np.float32),
            np.asarray([0.8, 0.9], dtype=np.float32),
        ]
        tracker = PairwiseMatcherTracker(
            _SequenceMatcher([first, second]),
            PairwiseMatcherTrackerConfig(
                max_features=2,
                association_radius=2.0,
                min_ncc=0.35,
                persistent_id_mode="continuity_first_v2",
            ),
        )
        tracker.process(self.image, self.quality)
        tracks1, _ = tracker.process(self.image, self.quality)
        tracker.config.max_features = 1
        tracks2, _ = tracker.process(self.image, self.quality)
        self.assertEqual(tracks2.ids.tolist(), [int(tracks1.ids[1])])
        self.assertTrue(np.allclose(tracks2.points[0], [31, 0]))

    def test_invalid_persistent_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "persistent_id_mode"):
            PairwiseMatcherTracker(
                _SequenceMatcher([]),
                PairwiseMatcherTrackerConfig(persistent_id_mode="unknown"),
            )


class XFeatNativeConfidenceTests(unittest.TestCase):
    def test_sparse_cosine_confidence_is_returned(self) -> None:
        import torch

        class _FakeModel:
            def __init__(self) -> None:
                self.calls = 0

            def detectAndCompute(self, _tensor, top_k=None):
                self.calls += 1
                if self.calls == 1:
                    keypoints = torch.tensor([[1.0, 2.0], [3.0, 4.0]])
                    descriptors = torch.tensor([[1.0, 0.0], [0.0, 1.0]])
                else:
                    keypoints = torch.tensor([[2.0, 2.0], [4.0, 4.0]])
                    descriptors = torch.tensor([[0.8, 0.6], [0.0, 1.0]])
                return [{"keypoints": keypoints, "descriptors": descriptors}]

            def match(self, _descriptors0, _descriptors1, min_cossim=-1):
                return torch.tensor([0, 1]), torch.tensor([0, 1])

        matcher = XFeatMatcher(confidence_mode="cosine")
        matcher._torch = torch
        matcher._model = _FakeModel()
        result = matcher.match(
            np.zeros((8, 8), dtype=np.uint8),
            np.ones((8, 8), dtype=np.uint8),
        )
        self.assertTrue(np.allclose(result.confidences, [0.8, 1.0]))
        self.assertTrue(np.allclose(result.points0, [[1, 2], [3, 4]]))
        self.assertTrue(np.allclose(result.points1, [[2, 2], [4, 4]]))

    def test_sparse_feature_cache_reuses_the_shared_endpoint(self) -> None:
        import torch

        class _FakeModel:
            def __init__(self) -> None:
                self.detect_calls = 0

            def detectAndCompute(self, tensor, top_k=None):
                self.detect_calls += 1
                marker = float(tensor.mean())
                return [
                    {
                        "keypoints": torch.tensor([[marker, marker]]),
                        "descriptors": torch.tensor([[1.0, 0.0]]),
                    }
                ]

            def match(self, _descriptors0, _descriptors1, min_cossim=-1):
                return torch.tensor([0]), torch.tensor([0])

        matcher = XFeatMatcher(
            confidence_mode="cosine", cache_sparse_features=True
        )
        matcher._torch = torch
        matcher._model = _FakeModel()
        image0 = np.zeros((8, 8), dtype=np.uint8)
        image1 = np.ones((8, 8), dtype=np.uint8) * 64
        image2 = np.ones((8, 8), dtype=np.uint8) * 128
        with mock.patch(
            "uw_frontend.matchers.xfeat_adapter._image_to_tensor",
            wraps=__import__(
                "uw_frontend.matchers.xfeat_adapter",
                fromlist=["_image_to_tensor"],
            )._image_to_tensor,
        ) as tensor_builder:
            matcher.match(image0, image1)
            matcher.match(image1, image2)
        self.assertEqual(tensor_builder.call_count, 3)
        self.assertEqual(matcher._model.detect_calls, 3)
        matcher.reset()
        matcher.match(image1, image2)
        self.assertEqual(matcher._model.detect_calls, 5)

    def test_invalid_confidence_modes_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "confidence_mode"):
            XFeatMatcher(confidence_mode="unknown")
        with self.assertRaisesRegex(ValueError, "sparse XFeat"):
            XFeatMatcher(semi_dense=True, confidence_mode="cosine")


if __name__ == "__main__":
    unittest.main()
