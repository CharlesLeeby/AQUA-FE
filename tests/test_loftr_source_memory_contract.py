from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.ros.export_vins_features import (
    _ExportIdState,
    _remap_recovered_export_ids,
)
from uw_frontend.tracking.track_state import TrackSet


def _tracks(ids: list[int], sources: list[str]) -> TrackSet:
    count = len(ids)
    zeros_2d = np.zeros((count, 2), dtype=np.float32)
    return TrackSet(
        ids=np.asarray(ids, dtype=np.int64),
        prev_points=zeros_2d.copy(),
        points=zeros_2d.copy(),
        ages=np.ones((count,), dtype=np.int32),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
        local_texture=np.ones((count,), dtype=np.float32),
        qualities=np.ones((count,), dtype=np.float32),
        sources=sources,
    )


class LoFTRSourceMemoryContractTest(unittest.TestCase):
    def test_confirmed_seed_keeps_high_id_through_lk_carrier(self) -> None:
        state = _ExportIdState()
        seeded = _remap_recovered_export_ids(
            _tracks([17, 18, 3], ["loftr_confirmed", "loftr_confirmed", "klt"]),
            state,
            loftr_source_memory=True,
        )
        carried = _remap_recovered_export_ids(
            _tracks([17, 18, 3], ["klt", "klt", "klt"]),
            state,
            loftr_source_memory=True,
        )

        self.assertEqual(seeded.ids[:2].tolist(), [10_000_000, 10_000_001])
        self.assertEqual(carried.ids.tolist(), seeded.ids.tolist())
        self.assertEqual(carried.sources, ["loftr_memory", "loftr_memory", "klt"])

    def test_memory_is_contiguous_and_revived_seed_gets_fresh_id(self) -> None:
        state = _ExportIdState()
        first = _remap_recovered_export_ids(
            _tracks([17], ["loftr_confirmed"]),
            state,
            loftr_source_memory=True,
        )
        _remap_recovered_export_ids(
            _tracks([3], ["klt"]),
            state,
            loftr_source_memory=True,
        )
        revived = _remap_recovered_export_ids(
            _tracks([17], ["loftr_confirmed"]),
            state,
            loftr_source_memory=True,
        )

        self.assertGreater(int(revived.ids[0]), int(first.ids[0]))

    def test_disabled_memory_returns_lk_successor_to_classical_namespace(self) -> None:
        state = _ExportIdState()
        _remap_recovered_export_ids(
            _tracks([17], ["loftr_confirmed"]),
            state,
            loftr_source_memory=False,
        )
        carried = _remap_recovered_export_ids(
            _tracks([17], ["klt"]),
            state,
            loftr_source_memory=False,
        )

        self.assertEqual(carried.ids.tolist(), [17])
        self.assertEqual(carried.sources, ["klt"])


if __name__ == "__main__":
    unittest.main()
