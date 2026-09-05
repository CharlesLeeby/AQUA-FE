from __future__ import annotations

import unittest

import numpy as np

from uw_frontend.ros.export_vins_features import (
    _ExportIdState,
    _finalize_mirror_sidecar_export,
)
from uw_frontend.tracking.track_state import TrackSet


def _tracks(
    ids: list[int],
    sources: list[str],
    *,
    age_start: int = 1,
    quality_start: float = 0.7,
) -> TrackSet:
    count = len(ids)
    x = np.arange(count, dtype=np.float32)
    points = np.column_stack([x * 10.0 + 1.0, x * 7.0 + 2.0]).astype(np.float32)
    return TrackSet(
        ids=np.asarray(ids, dtype=np.int64),
        prev_points=points - 0.5,
        points=points,
        ages=np.arange(age_start, age_start + count, dtype=np.int32),
        fb_errors=np.linspace(0.1, 0.2, count, dtype=np.float32),
        ncc_scores=np.linspace(0.8, 0.9, count, dtype=np.float32),
        local_texture=np.linspace(0.4, 0.8, count, dtype=np.float32),
        qualities=np.linspace(quality_start, quality_start + 0.1, count, dtype=np.float32),
        sources=sources,
    )


class FinalMirrorNoHarmContractTest(unittest.TestCase):
    def test_zero_sidecar_restores_mirror_exactly(self) -> None:
        mirror = _tracks([1, 2, 3, 4, 5], ["klt"] * 5)
        perturbed = _tracks([1, 2, 3], ["klt"] * 3, quality_start=0.2)

        final, info = _finalize_mirror_sidecar_export(
            perturbed,
            mirror,
            state=_ExportIdState(),
            max_features=5,
        )

        self.assertTrue(info.active)
        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(final.sources, mirror.sources)
        for name in (
            "ids",
            "prev_points",
            "points",
            "ages",
            "fb_errors",
            "ncc_scores",
            "local_texture",
            "qualities",
        ):
            np.testing.assert_array_equal(getattr(final, name), getattr(mirror, name))

    def test_sidecars_use_disjoint_stable_ids_and_strict_cap(self) -> None:
        mirror = _tracks([1, 2, 3, 4, 5], ["klt"] * 5)
        accepted = _tracks(
            [1, 2, 2, 9],
            ["klt", "klt", "xfeat_confirmed", "xfeat_confirmed"],
            age_start=4,
        )
        state = _ExportIdState()

        first, info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=state,
            max_features=5,
        )
        second, _ = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=state,
            max_features=5,
        )

        self.assertEqual(len(first), 5)
        self.assertEqual(len(np.unique(first.ids)), 5)
        self.assertEqual(info.input_sidecars, 2)
        self.assertEqual(info.kept_sidecars, 2)
        self.assertEqual(info.dropped_classical_for_cap, 2)
        learned_first = first.ids[["xfeat" in source for source in first.sources]]
        learned_second = second.ids[["xfeat" in source for source in second.sources]]
        self.assertTrue(np.all(learned_first >= 10_000_000))
        np.testing.assert_array_equal(learned_first, learned_second)

    def test_sidecars_are_capped_before_classical_refill(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt"] * 3)
        sidecars = _tracks(
            [10, 11, 12, 13],
            ["xfeat_confirmed"] * 4,
            age_start=3,
        )

        final, info = _finalize_mirror_sidecar_export(
            sidecars,
            mirror,
            state=_ExportIdState(),
            max_features=2,
        )

        self.assertEqual(len(final), 2)
        self.assertEqual(info.kept_sidecars, 2)
        self.assertEqual(info.dropped_sidecars_for_cap, 2)
        self.assertTrue(all("xfeat" in source for source in final.sources))

    def test_preserve_classical_budget_restores_full_mirror(self) -> None:
        mirror = _tracks([1, 2, 3, 4, 5], ["klt"] * 5)
        accepted = _tracks(
            [1, 9],
            ["xfeat_confirmed", "xfeat_confirmed"],
            age_start=4,
        )

        final, info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=5,
            preserve_classical_budget=True,
        )

        self.assertTrue(info.preserve_classical_budget)
        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(info.input_sidecars, 2)
        self.assertEqual(info.kept_sidecars, 0)
        self.assertEqual(info.dropped_sidecars_for_classical_budget, 2)
        self.assertEqual(info.dropped_classical_for_cap, 0)
        for name in (
            "ids",
            "prev_points",
            "points",
            "ages",
            "fb_errors",
            "ncc_scores",
            "local_texture",
            "qualities",
        ):
            np.testing.assert_array_equal(getattr(final, name), getattr(mirror, name))

    def test_preserve_classical_budget_uses_only_vacant_capacity(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt"] * 3)
        sidecars = _tracks(
            [10, 11, 12, 13],
            ["xfeat_confirmed"] * 4,
            age_start=3,
        )

        final, info = _finalize_mirror_sidecar_export(
            sidecars,
            mirror,
            state=_ExportIdState(),
            max_features=5,
            preserve_classical_budget=True,
        )

        self.assertEqual(len(final), 5)
        self.assertEqual(final.sources[:3], mirror.sources)
        np.testing.assert_array_equal(final.ids[:3], mirror.ids)
        self.assertEqual(info.kept_sidecars, 2)
        self.assertEqual(info.dropped_sidecars_for_classical_budget, 2)
        self.assertEqual(info.dropped_classical_for_cap, 0)

    def test_persistence_mode_replaces_only_gftt_births(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt", "gftt", "gftt"])
        mirror.ages = np.asarray([10, 1, 1], dtype=np.int32)
        sidecars = _tracks(
            [20, 21],
            ["xfeat_confirmed", "xfeat_confirmed"],
            age_start=3,
        )

        final, info = _finalize_mirror_sidecar_export(
            sidecars,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            selected_feature_index=2,
            persistence_max_selected_frame=4,
            persistence_min_age_advantage=2,
        )

        self.assertEqual(len(final), 3)
        self.assertIn(1, final.ids)
        self.assertNotIn(2, final.ids)
        self.assertNotIn(3, final.ids)
        self.assertEqual(info.persistence_replaced_gftt, 2)
        self.assertEqual(info.kept_sidecars, 2)
        self.assertEqual(info.dropped_classical_for_cap, 2)

    def test_persistence_mode_never_replaces_tracked_klt(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt"] * 3)
        accepted = _tracks([20], ["xfeat_confirmed"], age_start=20)

        final, info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            selected_feature_index=2,
        )

        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(info.persistence_replaced_gftt, 0)
        np.testing.assert_array_equal(final.ids, mirror.ids)

    def test_persistence_mode_enforces_horizon_and_age_advantage(self) -> None:
        mirror = _tracks([1, 2], ["klt", "gftt"])
        mirror.ages = np.asarray([8, 1], dtype=np.int32)
        accepted = _tracks([20], ["xfeat_confirmed"], age_start=2)

        too_late, late_info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=2,
            persistence_replacement=True,
            selected_feature_index=5,
            persistence_max_selected_frame=4,
            persistence_min_age_advantage=1,
        )
        too_young, young_info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=2,
            persistence_replacement=True,
            selected_feature_index=2,
            persistence_max_selected_frame=4,
            persistence_min_age_advantage=2,
        )

        self.assertTrue(late_info.persistence_horizon_blocked)
        self.assertEqual(late_info.persistence_replaced_gftt, 0)
        self.assertEqual(young_info.persistence_replaced_gftt, 0)
        np.testing.assert_array_equal(too_late.ids, mirror.ids)
        np.testing.assert_array_equal(too_young.ids, mirror.ids)

    def test_persistence_mode_keeps_vacant_capacity_without_displacement(self) -> None:
        mirror = _tracks([1, 2], ["klt", "klt"])
        accepted = _tracks([20], ["xfeat_confirmed"], age_start=3)

        final, info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            selected_feature_index=100,
        )

        self.assertEqual(len(final), 3)
        self.assertEqual(info.kept_sidecars, 1)
        self.assertEqual(info.persistence_replaced_gftt, 0)
        self.assertFalse(info.persistence_horizon_blocked)

    def test_single_chain_mode_commits_only_one_identity(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt", "gftt", "gftt"])
        mirror.ages = np.asarray([10, 1, 1], dtype=np.int32)
        accepted = _tracks(
            [20, 21],
            ["xfeat_confirmed", "xfeat_confirmed"],
            age_start=3,
        )
        state = _ExportIdState()

        first, first_info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=state,
            max_features=3,
            persistence_replacement=True,
            persistence_single_chain=True,
            selected_feature_index=2,
        )
        second, second_info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=state,
            max_features=3,
            persistence_replacement=True,
            persistence_single_chain=True,
            selected_feature_index=3,
        )

        learned_first = first.ids[["xfeat" in source for source in first.sources]]
        learned_second = second.ids[["xfeat" in source for source in second.sources]]
        self.assertEqual(len(learned_first), 1)
        np.testing.assert_array_equal(learned_first, learned_second)
        self.assertEqual(first_info.persistence_replaced_gftt, 1)
        self.assertEqual(first_info.persistence_single_chain_suppressed, 1)
        self.assertEqual(first_info.persistence_committed_sidecar_id, int(learned_first[0]))
        self.assertEqual(second_info.persistence_committed_sidecar_id, int(learned_first[0]))

    def test_single_chain_mode_never_switches_after_committed_id_disappears(self) -> None:
        mirror = _tracks([1, 2], ["klt", "gftt"])
        mirror.ages = np.asarray([10, 1], dtype=np.int32)
        initial = _tracks(
            [20, 21],
            ["xfeat_confirmed", "xfeat_confirmed"],
            age_start=3,
        )
        state = _ExportIdState()
        first, _ = _finalize_mirror_sidecar_export(
            initial,
            mirror,
            state=state,
            max_features=2,
            persistence_replacement=True,
            persistence_single_chain=True,
            selected_feature_index=2,
        )
        committed = int(first.ids[["xfeat" in source for source in first.sources]][0])

        replacement_candidate = _tracks(
            [20],
            ["xfeat_confirmed"],
            age_start=10,
        )
        final, info = _finalize_mirror_sidecar_export(
            replacement_candidate,
            mirror,
            state=state,
            max_features=2,
            persistence_replacement=True,
            persistence_single_chain=True,
            selected_feature_index=3,
        )

        self.assertEqual(info.persistence_committed_sidecar_id, committed)
        self.assertEqual(info.kept_sidecars, 0)
        self.assertEqual(info.persistence_replaced_gftt, 0)
        np.testing.assert_array_equal(final.ids, mirror.ids)

    def test_single_chain_mode_uses_only_one_vacant_slot(self) -> None:
        mirror = _tracks([1, 2], ["klt", "klt"])
        accepted = _tracks(
            [20, 21, 22],
            ["xfeat_confirmed"] * 3,
            age_start=3,
        )

        final, info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=_ExportIdState(),
            max_features=5,
            persistence_replacement=True,
            persistence_single_chain=True,
            selected_feature_index=2,
        )

        self.assertEqual(len(final), 3)
        self.assertEqual(info.kept_sidecars, 1)
        self.assertEqual(info.persistence_single_chain_suppressed, 2)

    def test_churn_guard_latches_closed_on_low_gftt_birth_reserve(self) -> None:
        mirror = _tracks(
            list(range(10)),
            ["klt"] * 9 + ["gftt"],
        )
        mirror.ages = np.asarray([10] * 9 + [1], dtype=np.int32)
        accepted = _tracks([20], ["xfeat_confirmed"], age_start=3)
        state = _ExportIdState()

        first, first_info = _finalize_mirror_sidecar_export(
            accepted,
            mirror,
            state=state,
            max_features=10,
            persistence_replacement=True,
            persistence_min_gftt_ratio=0.2,
            selected_feature_index=1,
        )
        high_churn_mirror = _tracks(
            list(range(30, 40)),
            ["klt"] * 6 + ["gftt"] * 4,
        )
        high_churn_mirror.ages = np.asarray([10] * 6 + [1] * 4, dtype=np.int32)
        second, second_info = _finalize_mirror_sidecar_export(
            accepted,
            high_churn_mirror,
            state=state,
            max_features=10,
            persistence_replacement=True,
            persistence_min_gftt_ratio=0.2,
            selected_feature_index=2,
        )

        np.testing.assert_array_equal(first.ids, mirror.ids)
        np.testing.assert_array_equal(second.ids, high_churn_mirror.ids)
        self.assertEqual(first_info.persistence_churn_guard_decision, 0)
        self.assertEqual(second_info.persistence_churn_guard_decision, 0)
        self.assertEqual(first_info.persistence_churn_guard_decision_frame, 1)
        self.assertAlmostEqual(first_info.persistence_churn_guard_ratio, 0.1)
        self.assertEqual(first_info.persistence_replaced_gftt, 0)
        self.assertEqual(second_info.persistence_replaced_gftt, 0)

    def test_churn_guard_latches_armed_and_preserves_v1_replacement(self) -> None:
        high_churn_mirror = _tracks(
            list(range(10)),
            ["klt"] * 6 + ["gftt"] * 4,
        )
        high_churn_mirror.ages = np.asarray([10] * 6 + [1] * 4, dtype=np.int32)
        accepted = _tracks([20, 21], ["xfeat_confirmed"] * 2, age_start=3)
        state = _ExportIdState()

        first, first_info = _finalize_mirror_sidecar_export(
            accepted,
            high_churn_mirror,
            state=state,
            max_features=10,
            persistence_replacement=True,
            persistence_min_gftt_ratio=0.2,
            selected_feature_index=1,
        )
        low_churn_mirror = _tracks(
            list(range(30, 40)),
            ["klt"] * 9 + ["gftt"],
        )
        low_churn_mirror.ages = np.asarray([10] * 9 + [1], dtype=np.int32)
        second, second_info = _finalize_mirror_sidecar_export(
            accepted,
            low_churn_mirror,
            state=state,
            max_features=10,
            persistence_replacement=True,
            persistence_min_gftt_ratio=0.2,
            selected_feature_index=2,
        )

        self.assertEqual(first_info.persistence_churn_guard_decision, 1)
        self.assertEqual(second_info.persistence_churn_guard_decision, 1)
        self.assertEqual(first_info.persistence_churn_guard_decision_frame, 1)
        self.assertAlmostEqual(first_info.persistence_churn_guard_ratio, 0.4)
        self.assertEqual(first_info.persistence_replaced_gftt, 2)
        self.assertEqual(second_info.persistence_replaced_gftt, 1)
        self.assertEqual(sum("xfeat" in source for source in first.sources), 2)
        self.assertEqual(sum("xfeat" in source for source in second.sources), 1)

    def test_geometry_router_admits_same_cell_splg_birth_swap(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt", "gftt", "gftt"])
        mirror.ages = np.asarray([10, 1, 1], dtype=np.int32)
        mirror.points = np.asarray(
            [[5.0, 5.0], [25.0, 10.0], [65.0, 60.0]], dtype=np.float32
        )
        sidecars = _tracks(
            [20, 21],
            ["superpoint_lightglue_confirmed", "loftr_confirmed"],
            age_start=3,
        )
        sidecars.points = np.asarray(
            [[28.0, 12.0], [66.0, 62.0]], dtype=np.float32
        )

        final, info = _finalize_mirror_sidecar_export(
            sidecars,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_same_grid_cell=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        self.assertEqual(len(final), 3)
        self.assertIn(1, final.ids)
        self.assertNotIn(2, final.ids)
        self.assertIn(3, final.ids)
        self.assertEqual(info.kept_sidecars, 1)
        self.assertEqual(info.persistence_replaced_gftt, 1)
        self.assertEqual(info.persistence_source_eligible_sidecars, 1)
        self.assertEqual(info.persistence_source_suppressed, 1)
        self.assertTrue(info.persistence_same_cell_active)
        self.assertEqual(info.persistence_replaced_gftt_max_age, 1)
        self.assertGreaterEqual(info.persistence_replacement_min_age_advantage_actual, 2)
        self.assertEqual(info.persistence_replacement_cell_mismatches, 0)
        self.assertTrue(any("superpoint" in source for source in final.sources))
        self.assertFalse(any("loftr" in source for source in final.sources))

    def test_geometry_router_fails_closed_without_same_cell_birth(self) -> None:
        mirror = _tracks([1, 2], ["klt", "gftt"])
        mirror.ages = np.asarray([10, 1], dtype=np.int32)
        mirror.points = np.asarray([[5.0, 5.0], [25.0, 10.0]], dtype=np.float32)
        sidecar = _tracks([20], ["xfeat_confirmed"], age_start=3)
        sidecar.points = np.asarray([[95.0, 80.0]], dtype=np.float32)

        final, info = _finalize_mirror_sidecar_export(
            sidecar,
            mirror,
            state=_ExportIdState(),
            max_features=2,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_same_grid_cell=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        np.testing.assert_array_equal(final.ids, mirror.ids)
        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(info.persistence_replaced_gftt, 0)
        self.assertEqual(info.persistence_same_cell_suppressed, 1)

    def test_geometry_router_enforces_six_per_frame_cap(self) -> None:
        mirror = _tracks(list(range(8)), ["gftt"] * 8)
        mirror.ages = np.ones(8, dtype=np.int32)
        mirror.points = np.asarray(
            [[10.0 + i, 10.0 + i] for i in range(8)], dtype=np.float32
        )
        sidecars = _tracks(
            list(range(20, 28)), ["xfeat_confirmed"] * 8, age_start=3
        )
        sidecars.points = np.asarray(
            [[11.0 + i, 11.0 + i] for i in range(8)], dtype=np.float32
        )

        final, info = _finalize_mirror_sidecar_export(
            sidecars,
            mirror,
            state=_ExportIdState(),
            max_features=8,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_same_grid_cell=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        self.assertEqual(len(final), 8)
        self.assertEqual(info.kept_sidecars, 6)
        self.assertEqual(info.persistence_replaced_gftt, 6)
        self.assertEqual(info.persistence_per_frame_cap_suppressed, 2)

    def test_geometry_router_rejects_loftr_even_with_vacant_capacity(self) -> None:
        mirror = _tracks([1, 2], ["klt", "klt"])
        loftr = _tracks([20], ["loftr_confirmed"], age_start=3)

        final, info = _finalize_mirror_sidecar_export(
            loftr,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_same_grid_cell=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        np.testing.assert_array_equal(final.ids, mirror.ids)
        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(info.persistence_source_eligible_sidecars, 0)
        self.assertEqual(info.persistence_source_suppressed, 1)

    def test_coverage_monotone_router_uses_occupied_cross_cell_donor(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt", "klt", "gftt"])
        mirror.ages = np.asarray([10, 10, 1], dtype=np.int32)
        mirror.points = np.asarray(
            [[5.0, 5.0], [25.0, 10.0], [27.0, 12.0]], dtype=np.float32
        )
        sidecar = _tracks([20], ["xfeat_confirmed"], age_start=3)
        sidecar.points = np.asarray([[95.0, 80.0]], dtype=np.float32)

        final, info = _finalize_mirror_sidecar_export(
            sidecar,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_coverage_monotone=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        self.assertEqual(len(final), 3)
        self.assertIn(1, final.ids)
        self.assertIn(2, final.ids)
        self.assertNotIn(3, final.ids)
        self.assertEqual(info.persistence_replaced_gftt, 1)
        self.assertEqual(info.persistence_cross_cell_replacements, 1)
        self.assertEqual(info.persistence_donor_cell_min_remaining, 1)
        self.assertGreaterEqual(info.persistence_grid_cell_delta, 0)
        self.assertEqual(info.persistence_coverage_monotone_suppressed, 0)

    def test_coverage_monotone_router_rejects_singleton_donor_cell(self) -> None:
        mirror = _tracks([1, 2], ["klt", "gftt"])
        mirror.ages = np.asarray([10, 1], dtype=np.int32)
        mirror.points = np.asarray([[5.0, 5.0], [25.0, 10.0]], dtype=np.float32)
        sidecar = _tracks([20], ["xfeat_confirmed"], age_start=3)
        sidecar.points = np.asarray([[95.0, 80.0]], dtype=np.float32)

        final, info = _finalize_mirror_sidecar_export(
            sidecar,
            mirror,
            state=_ExportIdState(),
            max_features=2,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_coverage_monotone=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        np.testing.assert_array_equal(final.ids, mirror.ids)
        self.assertTrue(info.zero_sidecar_restore)
        self.assertEqual(info.persistence_replaced_gftt, 0)
        self.assertEqual(info.persistence_coverage_monotone_suppressed, 1)

    def test_coverage_monotone_router_allows_same_cell_singleton_exchange(self) -> None:
        mirror = _tracks([1, 2], ["klt", "gftt"])
        mirror.ages = np.asarray([10, 1], dtype=np.int32)
        mirror.points = np.asarray([[5.0, 5.0], [25.0, 10.0]], dtype=np.float32)
        sidecar = _tracks([20], ["superpoint_lightglue_confirmed"], age_start=3)
        sidecar.points = np.asarray([[27.0, 12.0]], dtype=np.float32)

        final, info = _finalize_mirror_sidecar_export(
            sidecar,
            mirror,
            state=_ExportIdState(),
            max_features=2,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_coverage_monotone=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        self.assertEqual(info.persistence_replaced_gftt, 1)
        self.assertEqual(info.persistence_cross_cell_replacements, 0)
        self.assertEqual(info.persistence_donor_cell_min_remaining, 1)
        self.assertEqual(info.persistence_grid_cell_delta, 0)
        self.assertTrue(any("superpoint" in source for source in final.sources))

    def test_coverage_monotone_router_never_removes_old_gftt(self) -> None:
        mirror = _tracks([1, 2, 3], ["klt", "gftt", "gftt"])
        mirror.ages = np.asarray([10, 2, 8], dtype=np.int32)
        mirror.points = np.asarray(
            [[5.0, 5.0], [25.0, 10.0], [27.0, 12.0]], dtype=np.float32
        )
        sidecar = _tracks([20], ["xfeat_confirmed"], age_start=10)
        sidecar.points = np.asarray([[95.0, 80.0]], dtype=np.float32)

        final, info = _finalize_mirror_sidecar_export(
            sidecar,
            mirror,
            state=_ExportIdState(),
            max_features=3,
            persistence_replacement=True,
            persistence_source_router=True,
            persistence_allow_all_non_loftr=True,
            persistence_coverage_monotone=True,
            persistence_max_per_frame=6,
            image_shape=(100, 120),
            selected_feature_index=2,
        )

        np.testing.assert_array_equal(final.ids, mirror.ids)
        self.assertEqual(info.persistence_eligible_gftt, 0)
        self.assertEqual(info.persistence_replaced_gftt, 0)


if __name__ == "__main__":
    unittest.main()
