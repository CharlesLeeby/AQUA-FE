from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.ros.export_vins_features import (
    _LoFTRSeededContinuationGateState,
    _apply_loftr_seeded_continuation,
)
from uw_frontend.tracking.track_state import TrackSet


def _tracks(ids: list[int], sources: list[str]) -> TrackSet:
    count = len(ids)
    zeros_2d = np.zeros((count, 2), dtype=np.float32)
    return TrackSet(
        ids=np.asarray(ids, dtype=np.int64),
        prev_points=zeros_2d.copy(),
        points=zeros_2d.copy(),
        ages=np.full((count,), 5, dtype=np.int32),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
        local_texture=np.ones((count,), dtype=np.float32),
        qualities=np.ones((count,), dtype=np.float32),
        sources=sources,
    )


class LoFTRSeededContinuationContractTest(unittest.TestCase):
    def test_only_previously_admitted_verified_id_is_restored(self) -> None:
        state = _LoFTRSeededContinuationGateState(last_accepted_frame={})
        first = _tracks([17, 18], ["loftr_confirmed", "loftr_confirmed"])
        accepted, reason, restored = _apply_loftr_seeded_continuation(
            first,
            pre_benefit_mask=np.asarray([True, True]),
            accepted_mask=np.asarray([True, False]),
            benefit_reason="accepted_loftr_support_rescue",
            state=state,
            frame_index=10,
            max_gap=1,
        )
        self.assertEqual(accepted.tolist(), [True, False])
        self.assertEqual(restored, 0)

        accepted, reason, restored = _apply_loftr_seeded_continuation(
            first,
            pre_benefit_mask=np.asarray([True, True]),
            accepted_mask=np.asarray([False, False]),
            benefit_reason="too_few_new_cell_candidates",
            state=state,
            frame_index=11,
            max_gap=1,
        )
        self.assertEqual(accepted.tolist(), [True, False])
        self.assertEqual(restored, 1)
        self.assertIn("accepted_loftr_support_rescue_seeded_continuation", reason)

    def test_failed_current_gate_is_not_restored(self) -> None:
        state = _LoFTRSeededContinuationGateState(last_accepted_frame={17: 10})
        tracks = _tracks([17], ["loftr_confirmed"])
        accepted, _reason, restored = _apply_loftr_seeded_continuation(
            tracks,
            pre_benefit_mask=np.asarray([False]),
            accepted_mask=np.asarray([False]),
            benefit_reason="too_few_new_cell_candidates",
            state=state,
            frame_index=11,
            max_gap=1,
        )
        self.assertEqual(accepted.tolist(), [False])
        self.assertEqual(restored, 0)

    def test_gap_and_non_loftr_source_cannot_continue(self) -> None:
        state = _LoFTRSeededContinuationGateState(last_accepted_frame={17: 10, 18: 12})
        tracks = _tracks([17, 18], ["loftr_confirmed", "klt"])
        accepted, _reason, restored = _apply_loftr_seeded_continuation(
            tracks,
            pre_benefit_mask=np.asarray([True, True]),
            accepted_mask=np.asarray([False, False]),
            benefit_reason="too_few_new_cell_candidates",
            state=state,
            frame_index=13,
            max_gap=1,
        )
        self.assertEqual(accepted.tolist(), [False, False])
        self.assertEqual(restored, 0)


if __name__ == "__main__":
    unittest.main()
