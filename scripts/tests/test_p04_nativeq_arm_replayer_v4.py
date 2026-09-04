from __future__ import annotations

import hashlib
import unittest

from scripts.p04_nativeq_arm_replayer_v4 import (
    B2_ALL_ELIGIBLE,
    B_ACTIVE,
    C_LEGACY,
    ContractViolation,
    FHModelContract,
    NATIVE_Q_MAPPER_HASH,
    NormalizedMasterEvent,
    NormalizedObservation,
    P_LEGACY,
    TOTAL_FEATURE_CAP,
    derive_exact_lineage_drop,
    native_q_for_observation,
    normalized_event_digest,
    normalized_stream_digest,
    replay_master_events,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _klt(track_id: int, u: float, v: float) -> NormalizedObservation:
    return NormalizedObservation(
        track_id=track_id,
        source="klt_base",
        u=u,
        v=v,
        raw_quality=0.9,
        age=8,
        ncc=0.9,
        fb_error=0.1,
    )


def _learned(track_id: int, u: float, v: float, *, eligible: bool = True) -> NormalizedObservation:
    return NormalizedObservation(
        track_id=track_id,
        source="learned_xfeat_confirmed",
        u=u,
        v=v,
        raw_quality=0.85,
        age=3,
        ncc=0.8,
        fb_error=0.2,
        normalized_residual=0.2,
        fh_eligible=eligible,
    )


def _classical(track_id: int, u: float, v: float, *, eligible: bool = True) -> NormalizedObservation:
    return NormalizedObservation(
        track_id=track_id,
        source="classical_gftt",
        u=u,
        v=v,
        raw_quality=0.75,
        age=2,
        ncc=0.75,
        fb_error=0.3,
        normalized_residual=0.3,
        fh_eligible=eligible,
    )


def _event(
    frame: int,
    *,
    learned=(),
    classical=(),
    k0=None,
    base_export_ids=None,
    trigger_open: bool = True,
    valid_models=("F", "H"),
    previous_timestamp: float | None = None,
) -> NormalizedMasterEvent:
    base = tuple(k0 if k0 is not None else (_klt(1, 20.0, 20.0), _klt(2, 620.0, 460.0)))
    return NormalizedMasterEvent(
        sequence_id="synthetic/seq0",
        frame_index=frame,
        timestamp_s=float(frame + 1) if previous_timestamp is None else previous_timestamp,
        image_width=640,
        image_height=480,
        trigger_open=trigger_open,
        trigger_reason="KLT_DEGRADED" if trigger_open else "NORMAL",
        k0=base,
        base_export_ids=tuple(base_export_ids if base_export_ids is not None else [track.track_id for track in base]),
        learned_pool=tuple(learned),
        classical_pool=tuple(classical),
        fh_model=FHModelContract(
            fit_hash=_digest("fit"),
            input_track_ids=tuple(sorted(track.track_id for track in base)),
            valid_models=tuple(valid_models),
        ),
    )


class P04NativeQArmReplayerV4Tests(unittest.TestCase):
    def test_pool_independence(self) -> None:
        first = replay_master_events(
            [_event(0, learned=(_learned(100, 320, 80),), classical=(_classical(200, 500, 80),))]
        )
        changed_learned = replay_master_events(
            [_event(0, learned=(_learned(101, 320, 80),), classical=(_classical(200, 500, 80),))]
        )
        first_c = first.frames_for(C_LEGACY)[0]
        changed_c = changed_learned.frames_for(C_LEGACY)[0]
        self.assertEqual(first_c.candidate_pool_hash, changed_c.candidate_pool_hash)
        self.assertEqual(first_c.native_q_vector_hash, changed_c.native_q_vector_hash)
        self.assertEqual(first_c.arm_frame_hash, changed_c.arm_frame_hash)

        changed_classical = replay_master_events(
            [_event(0, learned=(_learned(100, 320, 80),), classical=(_classical(201, 500, 80),))]
        )
        self.assertEqual(
            first.frames_for(P_LEGACY)[0].arm_frame_hash,
            changed_classical.frames_for(P_LEGACY)[0].arm_frame_hash,
        )

    def test_exact_drop_removes_whole_learned_lineage_and_preserves_k0(self) -> None:
        bundle = replay_master_events(
            [
                _event(0, learned=(_learned(100, 320, 80),)),
                _event(1, learned=(_learned(100, 322, 82),)),
            ]
        )
        dropped = derive_exact_lineage_drop(bundle)
        self.assertEqual(dropped.dropped_lineage_ids, (100,))
        for source, result in zip(bundle.frames_for(P_LEGACY), dropped.frames):
            self.assertNotIn(100, result.exported_ids)
            self.assertEqual(result.exported_ids, (1, 2))
            self.assertEqual(
                [item.track_id for item in result.native_q_vector],
                [1, 2],
            )
            self.assertEqual(result.source_arm_frame_hash, source.arm_frame_hash)

    def test_terminated_lineage_cannot_reappear(self) -> None:
        with self.assertRaisesRegex(ContractViolation, "reappeared"):
            replay_master_events(
                [
                    _event(0, learned=(_learned(100, 320, 80),)),
                    _event(1, learned=()),
                    _event(2, learned=(_learned(100, 324, 84),)),
                ]
            )

    def test_active_and_total_budget_are_both_enforced(self) -> None:
        # Seven sidecars fit under B_active, but the total cap leaves only five.
        base = tuple(_klt(i, 10.0 + i, 10.0) for i in range(345))
        learned = tuple(_learned(10_000 + i, 40.0 + i, 100.0) for i in range(12))
        first = replay_master_events(
            [_event(0, k0=base, base_export_ids=tuple(range(345)), learned=learned)]
        )
        p = first.frames_for(P_LEGACY)[0]
        b2 = first.frames_for(B2_ALL_ELIGIBLE)[0]
        self.assertEqual(TOTAL_FEATURE_CAP, 350)
        self.assertEqual(len(p.selected_ids), 5)
        self.assertEqual(len(p.active_after_ids), 5)
        self.assertLessEqual(len(p.active_after_ids), B_ACTIVE)
        self.assertEqual(len(b2.selected_ids), 5)

        # With a smaller base, the concurrent lineage cap becomes the limit.
        second = replay_master_events(
            [_event(0, learned=tuple(_learned(20_000 + i, 40.0 + i, 100.0) for i in range(12)))]
        )
        self.assertEqual(len(second.frames_for(P_LEGACY)[0].selected_ids), B_ACTIVE)

    def test_native_q_mapping_and_mapper_hash(self) -> None:
        klt_q = native_q_for_observation(_klt(1, 20, 20))
        learned_q = native_q_for_observation(_learned(100, 300, 100))
        classical_q = native_q_for_observation(_classical(200, 300, 100))
        self.assertEqual(NATIVE_Q_MAPPER_HASH.__len__(), 64)
        self.assertGreaterEqual(klt_q, 0.80)
        self.assertGreaterEqual(learned_q, 0.80)
        self.assertGreaterEqual(classical_q, 0.80)
        self.assertLessEqual(klt_q, 1.0)
        self.assertLessEqual(learned_q, 1.0)
        self.assertLessEqual(classical_q, 1.0)
        self.assertNotEqual(learned_q, classical_q)
        matched_classical = NormalizedObservation(
            track_id=201,
            source="classical_gftt",
            u=300.0,
            v=100.0,
            raw_quality=0.85,
            age=3,
            ncc=0.8,
            fb_error=0.2,
        )
        self.assertEqual(
            learned_q,
            native_q_for_observation(matched_classical),
            "provenance must not choose a different candidate-sidecar q branch",
        )

    def test_deterministic_repeat_and_input_order_normalization(self) -> None:
        first_event = _event(
            0,
            learned=(_learned(102, 500, 100), _learned(101, 300, 100)),
            classical=(_classical(202, 500, 300), _classical(201, 300, 300)),
        )
        second_event = _event(
            1,
            learned=(_learned(101, 302, 101), _learned(102, 502, 101)),
            classical=(_classical(201, 302, 301), _classical(202, 502, 301)),
        )
        left = replay_master_events([first_event, second_event])
        right = replay_master_events(
            [
                NormalizedMasterEvent(
                    **{
                        **second_event.__dict__,
                        "learned_pool": tuple(reversed(second_event.learned_pool)),
                        "classical_pool": tuple(reversed(second_event.classical_pool)),
                    }
                ),
                NormalizedMasterEvent(
                    **{
                        **first_event.__dict__,
                        "learned_pool": tuple(reversed(first_event.learned_pool)),
                        "classical_pool": tuple(reversed(first_event.classical_pool)),
                    }
                ),
            ]
        )
        self.assertEqual(left.to_json(), right.to_json())
        self.assertEqual(normalized_stream_digest([first_event, second_event]), left.normalized_stream_hash)
        self.assertEqual(normalized_event_digest(first_event), normalized_event_digest(first_event.as_dict()))
        self.assertEqual(left.outcome_boundary, "NORMALIZED_FRONTEND_ONLY_NO_VINS_APE_RPE")
        self.assertEqual(left.b_active, B_ACTIVE)
        self.assertEqual(left.total_feature_cap, TOTAL_FEATURE_CAP)

    def test_zero_action_classical_supply_is_retained_and_ineligible(self) -> None:
        bundle = replay_master_events([_event(0, learned=(_learned(100, 320, 80),), classical=())])
        self.assertEqual(
            bundle.source_attribution_status,
            "H2_INELIGIBLE_SUPPLY_ZERO",
        )
        self.assertEqual(
            bundle.summary_for(C_LEGACY).status,
            "ZERO_ACTION_NO_CLASSICAL_SUPPLY",
        )
        self.assertEqual(bundle.summary_for(C_LEGACY).admitted_lineage_ids, ())
        self.assertEqual(bundle.frames_for(C_LEGACY)[0].live_supply_count, 0)

    def test_shared_gate_closes_all_arms_without_source_specific_override(self) -> None:
        bundle = replay_master_events(
            [_event(0, learned=(_learned(100, 320, 80),), classical=(_classical(200, 500, 80),), trigger_open=False)]
        )
        for arm_id in (P_LEGACY, C_LEGACY, B2_ALL_ELIGIBLE):
            frame = bundle.frames_for(arm_id)[0]
            self.assertEqual(frame.gate_reason, "TRIGGER_CLOSED")
            self.assertEqual(frame.selected_ids, ())
        self.assertEqual(
            bundle.frames_for(P_LEGACY)[0].gate_hash,
            bundle.frames_for(C_LEGACY)[0].gate_hash,
        )

    def test_invalid_outcome_field_and_invalid_fh_contract_fail_closed(self) -> None:
        event = _event(0, learned=(_learned(100, 320, 80),))
        self.assertEqual(NormalizedMasterEvent.from_mapping(event.as_dict()), event)
        raw = {**event.as_dict(), "ape_rmse": 0.1}
        with self.assertRaisesRegex(ContractViolation, "outcome"):
            NormalizedMasterEvent.from_mapping(raw)

        bad_bool = {**event.as_dict(), "trigger_open": "false"}
        with self.assertRaisesRegex(ContractViolation, "JSON boolean"):
            NormalizedMasterEvent.from_mapping(bad_bool)

        bad_schema = {**event.as_dict(), "schema_version": "isj-master-candidate-stream-v1"}
        with self.assertRaisesRegex(ContractViolation, "schema"):
            replay_master_events([NormalizedMasterEvent.from_mapping(bad_schema)])

        bad = NormalizedMasterEvent(
            **{
                **event.__dict__,
                "fh_model": FHModelContract(
                    fit_hash=_digest("fit"),
                    input_track_ids=(1, 2),
                    valid_models=(),
                ),
            }
        )
        with self.assertRaisesRegex(ContractViolation, "reject all candidates"):
            replay_master_events([bad])


if __name__ == "__main__":
    unittest.main()
