from __future__ import annotations

import unittest
from dataclasses import fields
from pathlib import Path

import cv2
import numpy as np

from uw_frontend.evaluation.run_frontend_eval import (
    load_config,
    resolve_process_skipped_frames,
)
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.tracking.hybrid_tracker import HybridConfig, HybridKltOrbTracker
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker


ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_processall_frontend.yaml"
CANDIDATE = ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_temporal_gftt_frontend.yaml"
SHADOW_CANDIDATE = ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_temporal_gftt_shadow_frontend.yaml"
DUAL_POOL_CANDIDATE = ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_temporal_gftt_dualpool_frontend.yaml"


def textured_frame(shift_x: float = 0.0) -> np.ndarray:
    image = np.zeros((240, 320), dtype=np.uint8)
    for y in range(20, 221, 20):
        for x in range(20, 301, 20):
            cv2.rectangle(image, (x - 3, y - 3), (x + 3, y + 3), 230, -1)
    transform = np.float32([[1.0, 0.0, shift_x], [0.0, 1.0, 0.0]])
    return cv2.warpAffine(image, transform, (image.shape[1], image.shape[0]))


class TemporalGfttAdmissionTest(unittest.TestCase):
    def test_default_is_off_and_profiles_are_paired(self) -> None:
        self.assertFalse(HybridConfig().enable_temporal_gftt_admission)
        self.assertFalse(HybridConfig().enable_temporal_gftt_shadow_replacement)
        self.assertFalse(HybridConfig().enable_temporal_gftt_dual_pool_replenishment)
        control = load_config(CONTROL)
        candidate = load_config(CANDIDATE)
        self.assertTrue(control["frontend_runtime"]["process_skipped_frames"])
        self.assertTrue(candidate["frontend_runtime"]["process_skipped_frames"])
        self.assertFalse(control["hybrid"]["enable_temporal_gftt_admission"])
        self.assertTrue(candidate["hybrid"]["enable_temporal_gftt_admission"])
        hybrid_keys = {field.name for field in fields(HybridConfig)}
        differing = {
            key
            for key in set(control["hybrid"]) | set(candidate["hybrid"])
            if control["hybrid"].get(key) != candidate["hybrid"].get(key)
        }
        self.assertEqual(differing, {"enable_temporal_gftt_admission"})
        self.assertTrue(set(candidate["hybrid"]).issubset(hybrid_keys))

        shadow = load_config(SHADOW_CANDIDATE)
        shadow_differing = {
            key
            for key in set(candidate["hybrid"]) | set(shadow["hybrid"])
            if candidate["hybrid"].get(key) != shadow["hybrid"].get(key)
        }
        self.assertEqual(
            shadow_differing,
            {"enable_temporal_gftt_shadow_replacement"},
        )
        dual_pool = load_config(DUAL_POOL_CANDIDATE)
        dual_pool_differing = {
            key
            for key in set(shadow["hybrid"]) | set(dual_pool["hybrid"])
            if shadow["hybrid"].get(key) != dual_pool["hybrid"].get(key)
        }
        self.assertEqual(
            dual_pool_differing,
            {"enable_temporal_gftt_dual_pool_replenishment"},
        )

    def test_profile_cadence_and_cli_precedence(self) -> None:
        candidate = load_config(CANDIDATE)
        self.assertTrue(resolve_process_skipped_frames(None, candidate))
        self.assertFalse(resolve_process_skipped_frames(False, candidate))
        self.assertTrue(resolve_process_skipped_frames(True, {}))
        self.assertFalse(resolve_process_skipped_frames(None, {}))

    def test_klt_replenish_false_applies_on_first_frame(self) -> None:
        image = textured_frame()
        tracker = KltTracker(KltConfig(max_features=80, min_distance=10))
        tracks, diagnostics = tracker.process(
            image,
            score_image_quality(image),
            replenish=False,
        )
        self.assertEqual(len(tracks), 0)
        self.assertEqual(diagnostics.added_features, 0)

    def test_temporal_admission_publishes_only_confirmed_unique_ids(self) -> None:
        config = HybridConfig(
            preserve_klt_replenish=True,
            enable_temporal_gftt_admission=True,
            enable_classical_recovery=False,
            enable_lk_recovery=False,
            enable_learned_initialization=False,
            gftt_confirmation_max_pending=160,
            gftt_confirmation_max_confirmed=80,
            gftt_confirmation_immediate_max=0,
        )
        tracker = HybridKltOrbTracker(
            KltConfig(max_features=80, min_distance=10),
            config,
        )
        frame0 = textured_frame(0.0)
        frame1 = textured_frame(1.0)
        frame2 = textured_frame(2.0)

        tracks0, _ = tracker.process(frame0, score_image_quality(frame0))
        self.assertEqual(len(tracks0), 0)
        self.assertGreater(len(tracker._pending_gftt_points), 0)
        self.assertEqual(tracker.klt.next_id, 0)

        tracks1, _ = tracker.process(frame1, score_image_quality(frame1))
        self.assertGreater(len(tracks1), 0)
        self.assertTrue(all(source == "gftt_confirmed" for source in tracks1.sources))
        self.assertTrue(np.all(tracks1.ages >= 2))
        ids1 = set(int(value) for value in tracks1.ids)
        self.assertEqual(len(ids1), len(tracks1))

        tracks2, _ = tracker.process(frame2, score_image_quality(frame2))
        ids2 = [int(value) for value in tracks2.ids]
        self.assertEqual(len(ids2), len(set(ids2)))
        self.assertGreaterEqual(tracker.klt.next_id, len(set(ids1) | set(ids2)))

    def test_shadow_replacements_remain_private_while_state_is_full(self) -> None:
        config = HybridConfig(
            preserve_klt_replenish=True,
            enable_temporal_gftt_admission=True,
            enable_temporal_gftt_shadow_replacement=True,
            enable_classical_recovery=False,
            enable_lk_recovery=False,
            enable_learned_initialization=False,
            gftt_confirmation_max_pending=160,
            gftt_confirmation_max_confirmed=80,
            gftt_confirmation_immediate_max=0,
        )
        tracker = HybridKltOrbTracker(
            KltConfig(max_features=80, min_distance=10),
            config,
        )
        frame0 = textured_frame(0.0)
        frame1 = textured_frame(1.0)
        tracks0, _ = tracker.process(frame0, score_image_quality(frame0))
        tracks1, _ = tracker.process(frame1, score_image_quality(frame1))

        self.assertEqual(len(tracks0), 0)
        self.assertGreater(len(tracks1), 0)
        self.assertEqual(len(tracker.klt.points), len(tracks1))
        self.assertGreater(len(tracker._pending_gftt_points), 0)
        public_ids = set(int(value) for value in tracks1.ids)
        self.assertEqual(len(public_ids), len(tracks1))
        self.assertEqual(tracker.klt.next_id, len(public_ids))


if __name__ == "__main__":
    unittest.main()
