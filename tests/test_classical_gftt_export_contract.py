from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.evaluation.run_frontend_eval import build_matcher
from uw_frontend.matchers.classical_gftt import ClassicalGfttMatcher
from uw_frontend.ros.export_vins_features import (
    _online_seed_target_mask,
    _source_code,
)
from uw_frontend.tracking.hybrid_tracker import (
    HybridKltOrbTracker,
    _source_family_name,
)
from uw_frontend.tracking.track_state import TrackSet


def _tracks(sources: list[str]) -> TrackSet:
    count = len(sources)
    zeros_2d = np.zeros((count, 2), dtype=np.float32)
    return TrackSet(
        ids=np.arange(count, dtype=np.int64),
        prev_points=zeros_2d.copy(),
        points=zeros_2d.copy(),
        ages=np.ones((count,), dtype=np.int32),
        fb_errors=np.zeros((count,), dtype=np.float32),
        ncc_scores=np.ones((count,), dtype=np.float32),
        local_texture=np.ones((count,), dtype=np.float32),
        qualities=np.ones((count,), dtype=np.float32),
        sources=sources,
    )


class ClassicalGfttExportContractTest(unittest.TestCase):
    def test_hybrid_method_builds_classical_matcher(self) -> None:
        matcher = build_matcher("hybrid_classical_gftt", {})
        self.assertIsInstance(matcher, ClassicalGfttMatcher)
        self.assertEqual(matcher.name, "classical_gftt")

    def test_source_family_and_confirmation_preserve_attribution(self) -> None:
        self.assertEqual(
            _source_family_name("classical_gftt_init"),
            "classical_gftt",
        )
        self.assertEqual(
            HybridKltOrbTracker._confirmed_source_label(
                "classical_gftt_init"
            ),
            "classical_gftt_confirmed",
        )
        self.assertEqual(_source_code("classical_gftt_confirmed"), 21)

    def test_online_gate_targets_only_classical_proposer(self) -> None:
        tracks = _tracks(
            [
                "klt",
                "gftt",
                "classical_gftt_init",
                "classical_gftt_confirmed",
                "xfeat_confirmed",
            ]
        )
        mask = _online_seed_target_mask(tracks, "classical_gftt")
        self.assertEqual(mask.tolist(), [False, False, True, True, False])


if __name__ == "__main__":
    unittest.main()
