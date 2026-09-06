"""Characterize the exact frozen v2 code, not a new frontend configuration.

Synthetic tracks isolate bookkeeping, budget-tag, horizon, and donor behavior.
No images, bags, VINS replay, or frozen file writes occur in these tests.
"""
from __future__ import annotations

import hashlib
import inspect
import subprocess
import sys
import types
import unittest
from pathlib import Path

import numpy as np

from scripts.audit_frontend_v2_budget_continuation import FROZEN_EXPORTER_SHA, classify
from uw_frontend.tracking.track_state import TrackSet

ROOT = Path(__file__).resolve().parents[1]
SOURCE_REF = "3c50b742d6e0c69796a69813e42823e9895ed684"
SOURCE_PATH = "uw_frontend/ros/export_vins_features.py"


def frozen_module():
    source = subprocess.check_output(["git", "show", f"{SOURCE_REF}:{SOURCE_PATH}"], cwd=ROOT)
    if hashlib.sha256(source).hexdigest() != FROZEN_EXPORTER_SHA:
        raise RuntimeError("Frozen v2 exporter identity mismatch")
    module = types.ModuleType("_v2_frozen_accounting_characterization")
    sys.modules[module.__name__] = module
    exec(compile(source, f"{SOURCE_REF}:{SOURCE_PATH}", "exec"), module.__dict__)
    return module


def tracks(ids, sources, age=3):
    n = len(ids)
    points = np.tile(np.array([[10.0, 10.0]], dtype=np.float32), (n, 1))
    return TrackSet(np.array(ids, dtype=np.int64), points - 0.5, points,
                    np.full(n, age, dtype=np.int32), np.full(n, 0.1),
                    np.full(n, 0.9), np.full(n, 0.9), np.full(n, 0.9), sources)


class FrozenV2Characterization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = frozen_module()

    def gate(self, candidates, used=0, frame=2, burst=None):
        function = self.code._apply_online_seed_sidecar_gate
        # Explicitly isolated synthetic gate: numeric optional policy limits
        # disabled, then only the budget/microburst under test enabled below.
        kwargs = {}
        for name, param in inspect.signature(function).parameters.items():
            if param.kind != inspect.Parameter.KEYWORD_ONLY:
                continue
            kind = str(param.annotation)
            kwargs[name] = {"int": 0, "float": 0.0, "bool": False, "str": ""}.get(kind)
        kwargs.update(frame_index=frame, target_sources="xfeat", max_observations=50,
                      used_observations=used, min_age=1, min_quality=0.10,
                      min_ncc=0.42, max_fb=1.20, require_confirmed=True,
                      image_shape=(480, 640), microburst_state=burst,
                      microburst_gate=burst is not None, microburst_frames=3,
                      microburst_extend_frames=12,
                      microburst_extend_min_initial_observations=20,
                      microburst_extend_grid_rows=6, microburst_extend_grid_cols=6)
        info = self.code._LearnedExportGateInfo(
            active=True, degraded=False, reason="synthetic_characterization",
            classical_count=0, classical_grid_coverage=0.0, dropped_learned=0)
        return function(candidates, info, **kwargs)

    def final(self, candidates, frame, state, donor=True):
        sources = ["klt"] * 349 + ["gftt" if donor else "klt"]
        mirror = tracks(list(range(350)), sources, age=10)
        if donor:
            mirror.ages[-1] = 1
        return self.code._finalize_mirror_sidecar_export(
            candidates, mirror, state=state, max_features=350,
            persistence_replacement=True, selected_feature_index=frame,
            persistence_max_selected_frame=4, persistence_min_age_advantage=2,
            persistence_source_router=True, persistence_allow_all_non_loftr=True,
            persistence_coverage_monotone=True, persistence_grid_rows=4,
            persistence_grid_cols=6, persistence_max_per_frame=6,
            image_shape=(480, 640))

    def test_budget_reason_can_mean_partial_acceptance_not_full_block(self):
        kept, info, used, _ = self.gate(tracks(list(range(1000, 1036)), ["xfeat_confirmed"] * 36), used=27)
        self.assertEqual((len(kept), used), (23, 50))
        self.assertIn("online_seed_budget", info.benefit_reason)
        row = dict(learned_export_benefit_reason=info.benefit_reason,
                   final_mirror_input_sidecars="23", final_mirror_persistence_horizon_blocked="0")
        self.assertEqual(classify(row), "BUDGET_TAG_WITH_SURVIVING_PREFINAL_CANDIDATES")

    def test_final_rejection_does_not_refund_upstream_reservation(self):
        kept, _, used, _ = self.gate(tracks(list(range(1000, 1050)), ["xfeat_confirmed"] * 50))
        _, info = self.final(kept, 2, self.code._ExportIdState(), donor=False)
        self.assertEqual((used, info.kept_sidecars), (50, 0))
        after, _, used_after, _ = self.gate(tracks([1000], ["xfeat_confirmed"]), used=used, frame=3)
        self.assertEqual((len(after), used_after), (0, 50))

    def test_same_admitted_id_requires_donor_again_at_full_capacity(self):
        state = self.code._ExportIdState()
        candidate = tracks([1000], ["xfeat_confirmed"])
        first, one = self.final(candidate, 2, state)
        second, two = self.final(candidate, 3, state)
        self.assertEqual((one.kept_sidecars, two.kept_sidecars), (1, 1))
        self.assertEqual((one.persistence_replaced_gftt, two.persistence_replaced_gftt), (1, 1))
        np.testing.assert_array_equal(first.ids[-1:], second.ids[-1:])
        _, no_donor = self.final(candidate, 4, state, donor=False)
        self.assertEqual(no_donor.kept_sidecars, 0)

    def test_final_horizon_blocks_already_admitted_id_even_with_donor(self):
        state = self.code._ExportIdState()
        candidate = tracks([1000], ["xfeat_confirmed"])
        _, before = self.final(candidate, 4, state)
        _, after = self.final(candidate, 5, state)
        self.assertEqual(before.kept_sidecars, 1)
        self.assertTrue(after.persistence_horizon_blocked)
        self.assertEqual(after.kept_sidecars, 0)

    def test_microburst_can_end_with_47_reservations_unused(self):
        burst = self.code._OnlineSeedMicroburstGateState()
        candidate = tracks([1000], ["xfeat_confirmed"])
        used = 0
        for frame in (2, 3, 4):
            kept, _, used, _ = self.gate(candidate, used=used, frame=frame, burst=burst)
            self.assertEqual(len(kept), 1)
        kept, info, used, _ = self.gate(candidate, used=used, frame=5, burst=burst)
        self.assertEqual((len(kept), used), (0, 3))
        self.assertIn("online_seed_microburst_no_extend", info.benefit_reason)


if __name__ == "__main__":
    unittest.main()
