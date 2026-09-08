"""Behavioral checks independent of the preregistered image experiments."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from uw_frontend.matchers.base import MatchResult
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.klt_tracker import KltTracker, KltConfig
from uw_frontend.tracking.same_frame_recovery import (
    GeometryReference, RecoveryConfig, SameFrameRecoveryTracker,
    predict_original_point, recover_same_frame,
)
from uw_frontend.tracking.track_state import TrackSet


def tracks(p0, p1, offset=0):
    n = len(p0)
    return TrackSet(np.arange(offset, offset+n), np.float32(p0), np.float32(p1),
        np.full(n, 10, dtype=np.int32), np.zeros(n, np.float32), np.ones(n, np.float32),
        np.ones(n, np.float32), np.ones(n, np.float32), ['klt']*n)


class EmptyMatcher:
    def match(self, prev, cur):
        return MatchResult(np.empty((0, 2), np.float32), np.empty((0, 2), np.float32),
                           np.empty(0, np.float32), 'fixture')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        cv2.setNumThreads(1)
        self.image = np.random.RandomState(83).randint(0, 256, (240, 320)).astype(np.uint8)
        self.image = cv2.GaussianBlur(self.image, (3, 3), .6)
        self.delta = np.float32([12.25, -4.5])
        self.current = cv2.warpAffine(self.image, np.float32([[1, 0, self.delta[0]], [0, 1, self.delta[1]]]), (320, 240))
        self.support = np.float32([[x, y] for y in [50, 80, 110, 140, 170, 200]
                                  for x in [50, 80, 110, 140, 170, 200, 230, 260]])
        self.ordinary = tracks(self.support, self.support+self.delta)
        self.matches = MatchResult(self.support, self.support+self.delta, np.ones(len(self.support), np.float32), 'fixture')

    def test_affine_predicts_query_not_a_nearby_match_endpoint(self):
        q = np.float32([123.5, 123.0])
        pred, reason, count = predict_original_point(q, self.matches, GeometryReference(self.ordinary, RecoveryConfig()), RecoveryConfig())
        self.assertEqual(reason, 'predicted')
        np.testing.assert_allclose(pred, q+self.delta, atol=1e-4)
        self.assertGreater(np.min(np.linalg.norm(self.matches.points1-pred, axis=1)), 3)
        self.assertGreaterEqual(count, 6)

    def test_original_point_refinement_identity_and_common_quality(self):
        q = np.float32([[123.5, 123.0]])
        quality = score_image_quality(self.current)
        endpoints = []
        for arm in ['C', 'L']:
            recovered, events = recover_same_frame(self.image, self.current, quality, q,
                np.array([500]), np.array([15]), self.ordinary, arm, self.matches)
            self.assertEqual(len(recovered), 1, events)
            np.testing.assert_array_equal(recovered.ids, [500])
            np.testing.assert_array_equal(recovered.prev_points, q)
            self.assertLess(np.linalg.norm(recovered.points[0]-(q[0]+self.delta)), .35)
            self.assertEqual(recovered.sources, ['klt'])
            endpoints.append(recovered)
        np.testing.assert_allclose(endpoints[0].qualities, endpoints[1].qualities, atol=.01)

    def test_insufficient_or_degenerate_support_is_rejected(self):
        geom = GeometryReference(self.ordinary, RecoveryConfig())
        short = MatchResult(self.support[:3], self.support[:3]+self.delta, np.ones(3), 'fixture')
        self.assertIsNone(predict_original_point(np.float32([123, 120]), short, geom, RecoveryConfig())[0])
        line = np.float32([[x, 100] for x in range(50, 201, 10)])
        degenerate = MatchResult(line, line+self.delta, np.ones(len(line)), 'fixture')
        self.assertIsNone(predict_original_point(np.float32([123, 120]), degenerate, geom, RecoveryConfig())[0])

    def test_B_wrapper_preserves_ordinary_tracker_outputs(self):
        original, wrapper = KltTracker(), SameFrameRecoveryTracker('B')
        for i in range(4):
            im = cv2.warpAffine(self.image, np.float32([[1, 0, i*2], [0, 1, i]]), (320, 240))
            quality = score_image_quality(im)
            a, _ = original.process(im, quality)
            b, _ = wrapper.process(im, quality, frame_index=i, stamp_ns=100+i)
            for k in a.__dataclass_fields__:
                np.testing.assert_equal(getattr(a, k), getattr(b, k))
        with self.assertRaisesRegex(ValueError, 'adjacent'):
            wrapper.process(self.image, quality, frame_index=5, stamp_ns=105)

    def test_total_forward_failure_is_captured_and_dead_IDs_do_not_revive(self):
        tracker = SameFrameRecoveryTracker('L', EmptyMatcher(), KltConfig(max_features=50))
        q = score_image_quality(self.image)
        first, _ = tracker.process(self.image, q, frame_index=0)
        old = first.ids.copy()
        with patch('cv2.calcOpticalFlowPyrLK', return_value=(None, None, None)):
            second, _ = tracker.process(self.image, q, frame_index=1)
        np.testing.assert_array_equal(tracker.last_lost_ids, old)
        self.assertFalse(set(old) & set(second.ids))
        self.assertEqual(len(tracker.last_recovery_events), len(old))
        third, _ = tracker.process(self.image, q, frame_index=2)
        self.assertFalse(set(old) & set(third.ids))


if __name__ == '__main__':
    unittest.main()
