from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.ros.export_vins_admission_continuation_v1 import PublishedLifecycle, load_frozen_exporter
from uw_frontend.tracking.track_state import TrackSet


def tracks(ids, sources, age=3):
    n = len(ids)
    points = np.tile(np.array([[10., 10.]], dtype=np.float32), (n, 1))
    return TrackSet(np.array(ids, dtype=np.int64), points - .5, points,
                    np.full(n, age, dtype=np.int32), np.full(n, .1),
                    np.full(n, .9), np.full(n, .9), np.full(n, .9), sources)


class LifecycleTest(unittest.TestCase):
    def setUp(self):
        self.code = load_frozen_exporter()
        self.controller = PublishedLifecycle(self.code)
        self.state = self.code._ExportIdState()

    def step(self, frame, stage_ids=(), new_ids=(), newborns=6, bad=False):
        c = self.controller
        c.stage = tracks(list(stage_ids), ["xfeat_confirmed"] * len(stage_ids))
        if bad:
            c.stage.fb_errors[:] = 2.
        c.stage_frame = frame
        c.basic = dict(min_age=1, min_quality=.1, min_ncc=.42, max_fb=1.2)
        mirror = tracks(list(range(350)), ["klt"] * (350 - newborns) + ["gftt"] * newborns, age=10)
        if newborns:
            mirror.ages[-newborns:] = 1
        new = tracks(list(new_ids), ["xfeat_confirmed"] * len(new_ids))
        return c.finalize(new, mirror, state=self.state, max_features=350,
                          selected_feature_index=frame, persistence_replacement=True,
                          persistence_source_router=True, persistence_allow_all_non_loftr=True,
                          persistence_max_per_frame=6, persistence_max_selected_frame=4,
                          persistence_min_age_advantage=2, persistence_coverage_monotone=True,
                          persistence_grid_rows=4, persistence_grid_cols=6, image_shape=(480, 640))

    def test_inactive_is_exact_klt(self):
        final, info = self.step(0)
        np.testing.assert_array_equal(final.ids, np.arange(350))
        self.assertEqual(info.kept_sidecars, 0)

    def test_never_admit_an_unpublished_id_via_continuation(self):
        final, info = self.step(0, stage_ids=[1000])
        self.assertEqual(info.kept_sidecars, 0)
        self.assertFalse(self.controller.active)

    def test_same_id_continues_beyond_first_admission_horizon(self):
        final, _ = self.step(0, [1000], [1000])
        public_id = int(final.ids[-1])
        for frame in range(1, 8):
            final, info = self.step(frame, [1000])
            self.assertEqual(info.kept_sidecars, 1)
            self.assertIn(public_id, final.ids)
            self.assertEqual(len(final), 350)
        self.assertEqual(self.controller.published, 8)

    def test_missing_and_bad_current_observations_terminate_without_revival(self):
        for bad in [False, True]:
            with self.subTest(bad=bad):
                self.setUp()
                self.step(0, [1000], [1000])
                _, info = self.step(1, [1000] if bad else [], bad=bad)
                self.assertEqual(info.kept_sidecars, 0)
                _, info = self.step(2, [1000], [1000])
                self.assertEqual(info.kept_sidecars, 0)

    def test_full_carried_capacity_terminates_instead_of_deleting_mature_klt(self):
        self.step(0, [1000], [1000])
        final, info = self.step(1, [1000], newborns=0)
        np.testing.assert_array_equal(final.ids, np.arange(350))
        self.assertEqual(info.kept_sidecars, 0)
        self.assertIn(1000, self.controller.closed)

    def test_continuation_priority_and_global_six_capacity(self):
        ids = list(range(1000, 1006))
        self.step(0, ids, ids)
        public = {value[0] for value in self.controller.active.values()}
        final, info = self.step(1, ids + [2000], [2000])
        self.assertEqual(info.kept_sidecars, 6)
        self.assertTrue(public.issubset(set(final.ids)))
        self.assertNotIn(2000, self.controller.active)

    def test_actual_publication_cap_fifty_without_partial_overflow(self):
        ids = list(range(1000, 1006))
        self.step(0, ids, ids)
        for frame in range(1, 8):
            self.step(frame, ids)
        self.assertEqual(self.controller.published, 48)
        _, info = self.step(8, ids)
        self.assertEqual((info.kept_sidecars, self.controller.published), (2, 50))
        final, info = self.step(9, ids)
        self.assertEqual((info.kept_sidecars, self.controller.published), (0, 50))
        np.testing.assert_array_equal(final.ids, np.arange(350))

    def test_no_new_first_admission_after_frame_four(self):
        for frame in range(5):
            self.step(frame)
        _, info = self.step(5, [1000], [1000])
        self.assertEqual(info.kept_sidecars, 0)


if __name__ == "__main__":
    unittest.main()
