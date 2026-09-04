from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from scripts.p04_nativeq_master_adapter_v4 import (
    AdapterContractViolation,
    PublicationEvidence,
    RawQualityEvidence,
    adapt_p03_jsonl,
    adapt_p03_master_events,
)
from uw_frontend.geometry.master_candidate_stream import (
    ModelFitEvidence,
    TrackEvidence,
    build_master_event,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _klt(track_id: int, u: float, v: float) -> TrackEvidence:
    return TrackEvidence(
        track_id=track_id,
        source="klt_base",
        u=u,
        v=v,
        q_lower=0.91,
        normalized_residual=0.1,
        age=4,
        ncc=0.88,
        fb_error=0.2,
        survival_count=4,
        residual_history=(0.1,),
        motion_ratio=1.0,
    )


def _learned(track_id: int = 100, *, age: int = 1) -> TrackEvidence:
    return TrackEvidence(
        track_id=track_id,
        source="learned_xfeat",
        u=320.0,
        v=100.0,
        q_lower=0.42,
        normalized_residual=0.25,
        age=age,
        ncc=0.82,
        fb_error=0.3,
        survival_count=age,
        residual_history=(0.2,),
        motion_ratio=1.0,
    )


def _classical(track_id: int = 200, *, age: int = 1) -> TrackEvidence:
    return TrackEvidence(
        track_id=track_id,
        source="classical_gftt",
        u=500.0,
        v=100.0,
        q_lower=0.31,
        normalized_residual=0.35,
        age=age,
        ncc=0.79,
        fb_error=0.4,
        survival_count=age,
        residual_history=(0.3,),
        motion_ratio=1.0,
    )


def _fit() -> ModelFitEvidence:
    return ModelFitEvidence(
        valid_models=("F", "H"),
        seed=20260730,
        input_track_ids=(1, 2),
        thresholds=(("F", 2.5), ("H", 5.0)),
        fit_hash=_digest("fit"),
    )


def _events() -> tuple[object, ...]:
    base = (_klt(1, 20.0, 20.0), _klt(2, 620.0, 460.0))
    first = build_master_event(
        sequence_id="synthetic/adapter",
        frame_index=0,
        timestamp_s=10.0,
        image_shape=(640, 480),
        trigger_reason="KLT_HEALTH_TRIGGER",
        k0=base,
        eligible_learned=(),
        eligible_classical=(_classical(),),
        live_learned=(_learned(),),
        live_classical=(_classical(),),
        base_export_ids=(1, 2),
        model_fit=_fit(),
        config_hash=_digest("config"),
    )
    second = build_master_event(
        sequence_id="synthetic/adapter",
        frame_index=1,
        timestamp_s=10.1,
        image_shape=(640, 480),
        trigger_reason="NO_TRIGGER",
        k0=base,
        eligible_learned=(_learned(age=2),),
        eligible_classical=(),
        live_learned=(_learned(age=2),),
        live_classical=(),
        base_export_ids=(1, 2),
        model_fit=_fit(),
        config_hash=_digest("config"),
        previous_master_hash=first.master_pool_hash,
    )
    third = build_master_event(
        sequence_id="synthetic/adapter",
        frame_index=2,
        timestamp_s=10.2,
        image_shape=(640, 480),
        trigger_reason="NO_TRIGGER",
        k0=base,
        eligible_learned=(),
        eligible_classical=(),
        live_learned=(),
        live_classical=(),
        base_export_ids=(1, 2),
        model_fit=_fit(),
        config_hash=_digest("config"),
        previous_master_hash=second.master_pool_hash,
    )
    return first, second, third


def _evidence(events: tuple[object, ...]):
    quality = []
    publication = []
    for event in events:
        tracks = (*event.k0, *event.live_learned, *event.live_classical)
        for track in tracks:
            quality.append(
                RawQualityEvidence(
                    sequence_id=event.sequence_id,
                    frame_index=event.frame_index,
                    track_id=track.track_id,
                    source=track.source,
                    raw_quality=(0.66 if track.track_id >= 100 else 0.97),
                    evidence_id=f"raw/{event.frame_index}/{track.track_id}",
                )
            )
        publication.append(
            PublicationEvidence(
                sequence_id=event.sequence_id,
                frame_index=event.frame_index,
                publication_id=f"pub/{event.frame_index}",
                publication_timestamp_s=event.timestamp_s,
                image_width=event.image_width,
                image_height=event.image_height,
                coordinate_space="pixel_uv",
                published_track_ids=event.base_export_ids,
                source_master_pool_hash=event.master_pool_hash,
                source_classical_pool_hash=event.classical_pool_hash,
            )
        )
    return quality, publication


class P04NativeQMasterAdapterV4Tests(unittest.TestCase):
    def test_preserves_live_eligible_fh_base_and_lineage_lifecycle(self) -> None:
        events = _events()
        quality, publication = _evidence(events)
        result = adapt_p03_master_events(
            events,
            raw_quality_evidence=quality,
            publication_evidence=publication,
        )
        self.assertEqual(len(result.events), 3)
        self.assertEqual(len(result.events[0].learned_pool), 1)
        self.assertFalse(result.events[0].learned_pool[0].fh_eligible)
        self.assertTrue(result.events[1].learned_pool[0].fh_eligible)
        self.assertEqual(result.events[1].classical_pool, ())
        self.assertEqual(result.events[0].base_export_ids, (1, 2))
        self.assertEqual(result.events[0].fh_model.fit_hash, events[0].model_fit.fit_hash)
        learned = next(item for item in result.lineages if item.pool == "learned")
        classical = next(item for item in result.lineages if item.pool == "classical")
        self.assertEqual((learned.birth_frame_index, learned.termination_frame_index), (0, 2))
        self.assertEqual((classical.birth_frame_index, classical.termination_frame_index), (0, 1))
        self.assertEqual((learned.birth_event_ordinal, learned.termination_event_ordinal), (0, 2))
        self.assertEqual((classical.birth_event_ordinal, classical.termination_event_ordinal), (0, 1))
        self.assertEqual(learned.eligible_frame_indices, (1,))
        self.assertFalse(learned.birth_left_censored)
        self.assertEqual(learned.birth_timestamp_s, 10.0)
        self.assertFalse(learned.termination_right_censored)
        self.assertFalse(classical.termination_right_censored)

    def test_birth_is_recovered_from_age_not_first_live_frame(self) -> None:
        base = (_klt(1, 20.0, 20.0), _klt(2, 620.0, 460.0))
        first = build_master_event(
            sequence_id="synthetic/birth",
            frame_index=0,
            timestamp_s=20.0,
            image_shape=(640, 480),
            trigger_reason="KLT_HEALTH_TRIGGER",
            k0=base,
            eligible_learned=(),
            eligible_classical=(),
            live_learned=(),
            live_classical=(),
            base_export_ids=(1, 2),
            model_fit=_fit(),
            config_hash=_digest("config"),
        )
        second = build_master_event(
            sequence_id="synthetic/birth",
            frame_index=1,
            timestamp_s=20.1,
            image_shape=(640, 480),
            trigger_reason="NO_TRIGGER",
            k0=base,
            eligible_learned=(_learned(age=2),),
            eligible_classical=(),
            live_learned=(_learned(age=2),),
            live_classical=(),
            base_export_ids=(1, 2),
            model_fit=_fit(),
            config_hash=_digest("config"),
            previous_master_hash=first.master_pool_hash,
        )
        events = (first, second)
        quality, publication = _evidence(events)
        result = adapt_p03_master_events(
            events,
            raw_quality_evidence=quality,
            publication_evidence=publication,
        )
        learned = result.lineages[0]
        self.assertEqual(learned.birth_frame_index, 0)
        self.assertEqual(learned.birth_timestamp_s, 20.0)
        self.assertEqual(learned.first_live_frame_index, 1)
        self.assertFalse(learned.birth_left_censored)
        self.assertTrue(learned.termination_right_censored)

    def test_raw_quality_is_explicit_and_not_q_lower_default(self) -> None:
        events = _events()
        quality, publication = _evidence(events)
        result = adapt_p03_master_events(
            events,
            raw_quality_evidence=quality,
            publication_evidence=publication,
        )
        learned = result.events[0].learned_pool[0]
        self.assertEqual(learned.raw_quality, 0.66)
        self.assertNotEqual(learned.raw_quality, _learned().q_lower)

        missing = quality[:-1]
        with self.assertRaisesRegex(AdapterContractViolation, "missing raw_quality"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=missing,
                publication_evidence=publication,
            )
        malformed = [row.as_dict() for row in quality]
        malformed[0].pop("raw_quality")
        with self.assertRaisesRegex(AdapterContractViolation, "raw_quality"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=malformed,
                publication_evidence=publication,
            )

    def test_publication_evidence_is_required_and_cross_linked(self) -> None:
        events = _events()
        quality, publication = _evidence(events)
        with self.assertRaisesRegex(AdapterContractViolation, "missing publication"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=quality,
                publication_evidence=publication[:-1],
            )
        malformed = [row.as_dict() for row in publication]
        malformed[0].pop("publication_timestamp_s")
        with self.assertRaisesRegex(AdapterContractViolation, "publication_timestamp_s"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=quality,
                publication_evidence=malformed,
            )
        bad = list(publication)
        bad[0] = PublicationEvidence(
            **{**bad[0].__dict__, "source_master_pool_hash": _digest("wrong")}
        )
        with self.assertRaisesRegex(AdapterContractViolation, "cross-link"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=quality,
                publication_evidence=bad,
            )

    def test_p03_roundtrip_and_hash_cross_link_are_deterministic(self) -> None:
        events = _events()
        quality, publication = _evidence(events)
        left = adapt_p03_master_events(
            events,
            raw_quality_evidence=quality,
            publication_evidence=publication,
        )
        lines = [json.dumps(event.as_dict(), sort_keys=True) for event in reversed(events)]
        # Source stream order is contractually meaningful; JSONL reversal is
        # rejected rather than silently reordered around the predecessor hash.
        with self.assertRaises(AdapterContractViolation):
            adapt_p03_jsonl(
                lines,
                raw_quality_evidence=quality,
                publication_evidence=publication,
            )

        ordered_lines = [json.dumps(event.as_dict(), sort_keys=True) for event in events]
        roundtrip = adapt_p03_jsonl(
            ordered_lines,
            raw_quality_evidence=list(reversed(quality)),
            publication_evidence=list(reversed(publication)),
        )
        self.assertEqual(left.adapter_hash, roundtrip.adapter_hash)
        links_by_frame = {link.frame_index: link for link in roundtrip.cross_links}
        for link, source in zip(left.cross_links, events):
            self.assertEqual(link.source_master_pool_hash, source.master_pool_hash)
            self.assertEqual(link.source_classical_pool_hash, source.classical_pool_hash)
            self.assertEqual(link.source_config_hash, source.config_hash)
            self.assertEqual(link.source_model_fit_hash, source.model_fit.fit_hash)
            self.assertEqual(link.source_event_hash, link.source_roundtrip_event_hash)
            self.assertEqual(link.normalized_event_digest, links_by_frame[source.frame_index].normalized_event_digest)

    def test_raw_p03_jsonl_without_live_fields_is_rejected(self) -> None:
        event = _events()[0].as_dict()
        event.pop("live_learned")
        quality, publication = _evidence(_events())
        with self.assertRaisesRegex(AdapterContractViolation, "missing required fields"):
            adapt_p03_jsonl(
                [json.dumps(event)],
                raw_quality_evidence=quality,
                publication_evidence=publication,
            )

    def test_repository_p03_jsonl_cannot_be_silently_upgraded(self) -> None:
        root = Path(__file__).resolve().parents[2]
        source = (
            root
            / "papers/ieee_sensors_journal_experiments/p03/smoke_a06_learned_v3/master_stream.jsonl"
        )
        with self.assertRaisesRegex(AdapterContractViolation, "missing raw_quality"):
            adapt_p03_jsonl(
                source,
                raw_quality_evidence=(),
                publication_evidence=(),
            )

    def test_outcome_fields_are_rejected_from_evidence_tables(self) -> None:
        events = _events()
        quality, publication = _evidence(events)
        bad_quality = [row.as_dict() for row in quality]
        bad_quality[0]["ape_rmse"] = 0.1
        with self.assertRaisesRegex(AdapterContractViolation, "unsupported fields"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=bad_quality,
                publication_evidence=publication,
            )
        bad_publication = [row.as_dict() for row in publication]
        bad_publication[0]["rpe_rmse"] = 0.2
        with self.assertRaisesRegex(AdapterContractViolation, "unsupported fields"):
            adapt_p03_master_events(
                events,
                raw_quality_evidence=quality,
                publication_evidence=bad_publication,
            )


if __name__ == "__main__":
    unittest.main()
