from __future__ import annotations

import hashlib
import unittest

from uw_frontend.geometry.master_candidate_stream import (
    AdmissionDecision,
    ArmChainValidator,
    MasterStreamValidator,
    ModelFitEvidence,
    TrackEvidence,
    build_arm_chain,
    build_master_event,
    validate_master_event,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _fit(ids=(1, 2), valid=("F", "H")) -> ModelFitEvidence:
    return ModelFitEvidence(
        valid_models=tuple(valid),
        seed=20260730,
        input_track_ids=tuple(ids),
        thresholds=(("F", 2.5), ("H", 5.0)),
        fit_hash=_digest("fit-" + ",".join(str(item) for item in ids)),
    )


def _base() -> tuple[TrackEvidence, ...]:
    return (
        TrackEvidence(1, "klt_base", 10.0, 20.0),
        TrackEvidence(2, "klt_base", 100.0, 80.0),
    )


def _learned(track_id: int, u: float = 200.0) -> TrackEvidence:
    return TrackEvidence(
        track_id,
        "learned_xfeat",
        u,
        120.0,
        q_lower=0.8,
        normalized_residual=0.25,
        age=3,
        ncc=0.9,
        fb_error=0.2,
        survival_count=3,
        residual_history=(0.1, 0.2),
        motion_ratio=1.0,
    )


def _event(
    frame: int,
    previous: str = "",
    learned=(),
    classical=(),
    live_learned=None,
    live_classical=None,
    fit: ModelFitEvidence | None = None,
):
    return build_master_event(
        sequence_id="dev/A06",
        frame_index=frame,
        timestamp_s=10.0 + frame,
        image_shape=(640, 480),
        trigger_reason="KLT_DEGRADED" if frame else "WARMUP",
        k0=_base(),
        eligible_learned=learned,
        eligible_classical=classical,
        live_learned=learned if live_learned is None else live_learned,
        live_classical=classical if live_classical is None else live_classical,
        base_export_ids=(1, 2),
        model_fit=fit or _fit(),
        config_hash=_digest("master-config"),
        previous_master_hash=previous,
    )


class MasterCandidateStreamTests(unittest.TestCase):
    def test_event_hash_contains_pool_and_geometry_contract(self) -> None:
        first = _event(0, learned=(_learned(100),), classical=(TrackEvidence(200, "classical_gftt", 300, 300),))
        validate_master_event(first)
        second = _event(0, learned=(_learned(100, 201.0),), classical=(TrackEvidence(200, "classical_gftt", 300, 300),))
        self.assertNotEqual(first.master_pool_hash, second.master_pool_hash)
        self.assertEqual(first.classical_pool_hash, second.classical_pool_hash)
        self.assertEqual(first.as_dict()["schema_version"], "isj-master-candidate-stream-v1")

    def test_no_valid_base_model_rejects_new_lineages(self) -> None:
        with self.assertRaisesRegex(ValueError, "NO_VALID_BASE_MODEL"):
            _event(0, learned=(_learned(100),), fit=_fit(valid=()))

    def test_disjoint_ids_and_bounds_are_required(self) -> None:
        with self.assertRaisesRegex(ValueError, "mutually disjoint"):
            _event(0, learned=(TrackEvidence(1, "learned_xfeat", 200, 120),))
        with self.assertRaisesRegex(ValueError, "outside image"):
            _event(0, learned=(TrackEvidence(100, "learned_xfeat", 640, 120),))

    def test_stream_predecessor_and_never_reappear(self) -> None:
        first = _event(0, learned=(_learned(100),))
        second = _event(1, previous=first.master_pool_hash, learned=())
        validator = MasterStreamValidator()
        validator.push(first)
        validator.push(second)
        reappeared = _event(2, previous=second.master_pool_hash, learned=(_learned(100),))
        with self.assertRaisesRegex(ValueError, "re-admitted"):
            validator.push(reappeared)

    def test_live_pool_allows_transient_eligibility_gap(self) -> None:
        first = _event(0, learned=(_learned(100),), live_learned=(_learned(100),))
        second = _event(
            1,
            previous=first.master_pool_hash,
            learned=(),
            live_learned=(_learned(100),),
        )
        third = _event(2, previous=second.master_pool_hash, learned=(), live_learned=())
        validator = MasterStreamValidator()
        validator.push(first)
        validator.push(second)
        validator.push(third)
        self.assertEqual(validator.previous_hash, third.master_pool_hash)

    def test_arm_chain_contains_active_state_and_enforces_cap(self) -> None:
        first = _event(0, learned=(_learned(100), _learned(101, 300.0)))
        decision = (
            AdmissionDecision(100, True, 1, 0.4, 0.8, 0.25, "ACCEPTED"),
            AdmissionDecision(101, False, 0, 0.2, 0.8, 0.25, "NO_SLOT"),
        )
        result = build_arm_chain(
            arm_id="H",
            event=first,
            active_tracks=(),
            decisions=decision,
            selector_config_hash=_digest("selector"),
            selector_model_hash=_digest("model"),
            b_active=1,
            total_feature_cap=3,
        )
        self.assertEqual(result.active_ids, (100,))
        self.assertEqual(result.exported_candidate_ids, (100,))
        with self.assertRaisesRegex(ValueError, "cap"):
            build_arm_chain(
                arm_id="H",
                event=first,
                active_tracks=(_learned(100),),
                decisions=(AdmissionDecision(101, True, 1, 0.2, 0.8, 0.25, "ACCEPTED"),),
                selector_config_hash=_digest("selector"),
                selector_model_hash=_digest("model"),
                b_active=2,
                total_feature_cap=3,
            )

    def test_arm_validator_rejects_second_admission(self) -> None:
        first = _event(0, learned=(_learned(100),))
        validator = ArmChainValidator("P")
        decision = (AdmissionDecision(100, True, 1, 0.4, 0.8, 0.25, "ACCEPTED"),)
        first_result = validator.push(
            first,
            (),
            decision,
            selector_config_hash=_digest("selector"),
            selector_model_hash=_digest("model"),
            b_active=1,
            total_feature_cap=3,
        )
        second = _event(1, previous=first.master_pool_hash, learned=(_learned(100),))
        with self.assertRaisesRegex(ValueError, "active lineage|more than once"):
            validator.push(
                second,
                (_learned(100),),
                decision,
                selector_config_hash=_digest("selector"),
                selector_model_hash=_digest("model"),
                b_active=1,
                total_feature_cap=3,
            )
        self.assertTrue(first_result.arm_chain_hash)


if __name__ == "__main__":
    unittest.main()
