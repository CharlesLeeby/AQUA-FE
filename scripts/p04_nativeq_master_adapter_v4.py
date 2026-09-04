#!/usr/bin/env python3
"""Outcome-blind adapter from P03 master events to the P04 v4 schema.

P03 ``TrackEvidence`` intentionally stores calibrated ``q_lower`` but not the
raw frontend quality needed by the v4 native-q mapper.  It also does not carry
an independently cross-linked publication attestation.  This adapter therefore
requires two
explicit evidence tables and fails closed when either is incomplete:

* one ``RawQualityEvidence`` row for every K0/live observation;
* one ``PublicationEvidence`` envelope for every event.

The adapter never reads VINS, APE/RPE, or any trajectory outcome.  It preserves
the P03 live-versus-eligible distinction by emitting all live tracks with the
``fh_eligible`` bit set from the corresponding eligible pool.  Birth and
termination are emitted in a separate immutable lineage ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from uw_frontend.geometry.master_candidate_stream import (
    MasterEvent,
    MasterStreamValidator,
    master_event_from_dict,
    validate_master_event,
)

from scripts.p04_nativeq_arm_replayer_v4 import (
    FHModelContract,
    NormalizedMasterEvent,
    NormalizedObservation,
    normalized_event_digest,
    normalized_stream_digest,
)


ADAPTER_SCHEMA_VERSION = "isj-p04-nativeq-p03-adapter-v4"
ADAPTER_OUTCOME_BOUNDARY = "P03_FRONTEND_ONLY_NO_VINS_APE_RPE"
MAX_EVENTS = 100_000
MAX_JSONL_LINE_BYTES = 64 * 1024 * 1024
MAX_RAW_QUALITY_ROWS = 10_000_000
MAX_PUBLICATION_ROWS = MAX_EVENTS
_P03_EVENT_KEYS = frozenset(
    {
        "base_export_ids",
        "classical_pool_hash",
        "config_hash",
        "eligible_classical",
        "eligible_learned",
        "frame_index",
        "image_height",
        "image_width",
        "k0",
        "live_classical",
        "live_learned",
        "master_pool_hash",
        "model_fit",
        "previous_master_hash",
        "schema_version",
        "sequence_id",
        "timestamp_s",
        "trigger_reason",
    }
)


class AdapterContractViolation(ValueError):
    """Raised when source/evidence data cannot be losslessly adapted."""


def _f64_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def _hash_payload(payload: object) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("ascii")).hexdigest()


def _canonical_json_hash(value: object) -> str:
    return _hash_payload(value)


@dataclass(frozen=True)
class RawQualityEvidence:
    """Raw frontend quality attached to one source observation."""

    sequence_id: str
    frame_index: int
    track_id: int
    source: str
    raw_quality: float
    evidence_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "RawQualityEvidence":
        _require_keys(
            value,
            required={
                "sequence_id",
                "frame_index",
                "track_id",
                "source",
                "raw_quality",
                "evidence_id",
            },
            optional=set(),
            label="raw_quality_evidence",
        )
        return cls(
            sequence_id=str(value["sequence_id"]),
            frame_index=int(value["frame_index"]),
            track_id=int(value["track_id"]),
            source=str(value["source"]),
            raw_quality=float(value["raw_quality"]),
            evidence_id=str(value["evidence_id"]),
        )

    def key(self) -> tuple[str, int, int]:
        return self.sequence_id, self.frame_index, self.track_id

    def payload(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "track_id": int(self.track_id),
            "source": self.source,
            "raw_quality": _f64_token(self.raw_quality),
            "evidence_id": self.evidence_id,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "track_id": int(self.track_id),
            "source": self.source,
            "raw_quality": float(self.raw_quality),
            "evidence_id": self.evidence_id,
        }


@dataclass(frozen=True)
class PublicationEvidence:
    """Cross-linked publication envelope for one P03 decision event."""

    sequence_id: str
    frame_index: int
    publication_id: str
    publication_timestamp_s: float
    image_width: int
    image_height: int
    coordinate_space: str
    published_track_ids: tuple[int, ...]
    source_master_pool_hash: str
    source_classical_pool_hash: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "PublicationEvidence":
        _require_keys(
            value,
            required={
                "sequence_id",
                "frame_index",
                "publication_id",
                "publication_timestamp_s",
                "image_width",
                "image_height",
                "coordinate_space",
                "published_track_ids",
                "source_master_pool_hash",
                "source_classical_pool_hash",
            },
            optional=set(),
            label="publication_evidence",
        )
        return cls(
            sequence_id=str(value["sequence_id"]),
            frame_index=int(value["frame_index"]),
            publication_id=str(value["publication_id"]),
            publication_timestamp_s=float(value["publication_timestamp_s"]),
            image_width=int(value["image_width"]),
            image_height=int(value["image_height"]),
            coordinate_space=str(value["coordinate_space"]),
            published_track_ids=tuple(int(item) for item in value["published_track_ids"]),
            source_master_pool_hash=str(value["source_master_pool_hash"]),
            source_classical_pool_hash=str(value["source_classical_pool_hash"]),
        )

    def key(self) -> tuple[str, int]:
        return self.sequence_id, self.frame_index

    def payload(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "publication_id": self.publication_id,
            "publication_timestamp_s": _f64_token(self.publication_timestamp_s),
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "coordinate_space": self.coordinate_space,
            "published_track_ids": list(sorted(self.published_track_ids)),
            "source_master_pool_hash": self.source_master_pool_hash,
            "source_classical_pool_hash": self.source_classical_pool_hash,
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "publication_id": self.publication_id,
            "publication_timestamp_s": float(self.publication_timestamp_s),
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "coordinate_space": self.coordinate_space,
            "published_track_ids": list(self.published_track_ids),
            "source_master_pool_hash": self.source_master_pool_hash,
            "source_classical_pool_hash": self.source_classical_pool_hash,
        }


@dataclass(frozen=True)
class LineageLifecycle:
    sequence_id: str
    pool: str
    track_id: int
    source: str
    birth_event_ordinal: int | None
    birth_frame_index: int | None
    birth_timestamp_s: float | None
    birth_left_censored: bool
    first_live_event_ordinal: int
    first_live_frame_index: int
    first_live_timestamp_s: float
    last_live_frame_index: int
    last_live_timestamp_s: float
    termination_event_ordinal: int | None
    termination_frame_index: int | None
    termination_timestamp_s: float | None
    termination_right_censored: bool
    eligible_frame_indices: tuple[int, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "pool": self.pool,
            "track_id": int(self.track_id),
            "source": self.source,
            "birth_event_ordinal": self.birth_event_ordinal,
            "birth_frame_index": self.birth_frame_index,
            "birth_timestamp_s": self.birth_timestamp_s,
            "birth_left_censored": bool(self.birth_left_censored),
            "first_live_event_ordinal": int(self.first_live_event_ordinal),
            "first_live_frame_index": int(self.first_live_frame_index),
            "first_live_timestamp_s": float(self.first_live_timestamp_s),
            "last_live_frame_index": int(self.last_live_frame_index),
            "last_live_timestamp_s": float(self.last_live_timestamp_s),
            "termination_event_ordinal": self.termination_event_ordinal,
            "termination_frame_index": self.termination_frame_index,
            "termination_timestamp_s": self.termination_timestamp_s,
            "termination_right_censored": bool(self.termination_right_censored),
            "eligible_frame_indices": list(self.eligible_frame_indices),
        }


@dataclass(frozen=True)
class EventCrossLink:
    sequence_id: str
    frame_index: int
    source_event_hash: str
    source_roundtrip_event_hash: str
    source_master_pool_hash: str
    source_classical_pool_hash: str
    source_config_hash: str
    source_model_fit_hash: str
    raw_quality_frame_hash: str
    publication_frame_hash: str
    normalized_event_digest: str
    cross_link_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "source_event_hash": self.source_event_hash,
            "source_roundtrip_event_hash": self.source_roundtrip_event_hash,
            "source_master_pool_hash": self.source_master_pool_hash,
            "source_classical_pool_hash": self.source_classical_pool_hash,
            "source_config_hash": self.source_config_hash,
            "source_model_fit_hash": self.source_model_fit_hash,
            "raw_quality_frame_hash": self.raw_quality_frame_hash,
            "publication_frame_hash": self.publication_frame_hash,
            "normalized_event_digest": self.normalized_event_digest,
            "cross_link_hash": self.cross_link_hash,
        }


@dataclass(frozen=True)
class P04AdapterResult:
    schema_version: str
    source_schema_version: str
    outcome_boundary: str
    events: tuple[NormalizedMasterEvent, ...]
    lineages: tuple[LineageLifecycle, ...]
    cross_links: tuple[EventCrossLink, ...]
    normalized_stream_hash: str
    raw_quality_evidence_hash: str
    publication_evidence_hash: str
    source_final_master_pool_hash: str
    source_final_classical_pool_hash: str
    adapter_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_schema_version": self.source_schema_version,
            "outcome_boundary": self.outcome_boundary,
            "events": [event.as_dict() for event in self.events],
            "lineages": [lineage.as_dict() for lineage in self.lineages],
            "cross_links": [link.as_dict() for link in self.cross_links],
            "normalized_stream_hash": self.normalized_stream_hash,
            "raw_quality_evidence_hash": self.raw_quality_evidence_hash,
            "publication_evidence_hash": self.publication_evidence_hash,
            "source_final_master_pool_hash": self.source_final_master_pool_hash,
            "source_final_classical_pool_hash": self.source_final_classical_pool_hash,
            "adapter_hash": self.adapter_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


def adapt_p03_master_events(
    records: Sequence[MasterEvent | Mapping[str, object]],
    *,
    raw_quality_evidence: Sequence[RawQualityEvidence | Mapping[str, object]],
    publication_evidence: Sequence[PublicationEvidence | Mapping[str, object]],
) -> P04AdapterResult:
    """Adapt a validated P03 stream using explicit evidence sidecars."""

    events = _parse_source_events(records)
    if len(events) > MAX_EVENTS:
        raise AdapterContractViolation(f"event count exceeds bounded limit {MAX_EVENTS}")
    quality_rows = _parse_quality_rows(raw_quality_evidence)
    publication_rows = _parse_publication_rows(publication_evidence)
    _validate_quality_coverage(events, quality_rows)
    _validate_publication_coverage(events, publication_rows)

    stream_validator = MasterStreamValidator()
    normalized_events: list[NormalizedMasterEvent] = []
    links: list[EventCrossLink] = []
    for event in events:
        try:
            stream_validator.push(event)
        except ValueError as exc:
            raise AdapterContractViolation(f"P03 stream contract failure: {exc}") from exc
        publication = publication_rows[(event.sequence_id, event.frame_index)]
        _validate_publication_against_event(publication, event)
        normalized = _convert_event(event, quality_rows, publication)
        normalized_events.append(normalized)
        source_payload = event.as_dict()
        source_event_hash = _canonical_json_hash(source_payload)
        roundtrip = master_event_from_dict(source_payload)
        roundtrip_hash = _canonical_json_hash(roundtrip.as_dict())
        if roundtrip_hash != source_event_hash:
            raise AdapterContractViolation("P03 event round-trip hash drift")
        quality_hash = _quality_frame_hash(event, quality_rows)
        publication_hash = _hash_payload(publication.payload())
        v4_digest = normalized_event_digest(normalized)
        link_payload = {
            "adapter_schema_version": ADAPTER_SCHEMA_VERSION,
            "sequence_id": event.sequence_id,
            "frame_index": int(event.frame_index),
            "source_event_hash": source_event_hash,
            "source_roundtrip_event_hash": roundtrip_hash,
            "source_master_pool_hash": event.master_pool_hash,
            "source_classical_pool_hash": event.classical_pool_hash,
            "source_config_hash": event.config_hash,
            "source_model_fit_hash": event.model_fit.fit_hash,
            "raw_quality_frame_hash": quality_hash,
            "publication_frame_hash": publication_hash,
            "normalized_event_digest": v4_digest,
        }
        links.append(
            EventCrossLink(
                sequence_id=event.sequence_id,
                frame_index=event.frame_index,
                source_event_hash=source_event_hash,
                source_roundtrip_event_hash=roundtrip_hash,
                source_master_pool_hash=event.master_pool_hash,
                source_classical_pool_hash=event.classical_pool_hash,
                source_config_hash=event.config_hash,
                source_model_fit_hash=event.model_fit.fit_hash,
                raw_quality_frame_hash=quality_hash,
                publication_frame_hash=publication_hash,
                normalized_event_digest=v4_digest,
                cross_link_hash=_hash_payload(link_payload),
            )
        )

    lineages = _build_lineage_ledger(events)
    normalized_stream_hash = normalized_stream_digest(tuple(normalized_events))
    quality_hash = _hash_payload(
        [row.payload() for row in sorted(quality_rows.values(), key=lambda item: item.key())]
    )
    publication_hash = _hash_payload(
        [row.payload() for row in sorted(publication_rows.values(), key=lambda item: item.key())]
    )
    adapter_payload = {
        "schema_version": ADAPTER_SCHEMA_VERSION,
        "source_schema_version": events[0].schema_version,
        "outcome_boundary": ADAPTER_OUTCOME_BOUNDARY,
        "normalized_stream_hash": normalized_stream_hash,
        "raw_quality_evidence_hash": quality_hash,
        "publication_evidence_hash": publication_hash,
        "source_final_master_pool_hash": events[-1].master_pool_hash,
        "source_final_classical_pool_hash": events[-1].classical_pool_hash,
        "cross_links": [link.as_dict() for link in links],
        "lineages": [lineage.as_dict() for lineage in lineages],
    }
    return P04AdapterResult(
        schema_version=ADAPTER_SCHEMA_VERSION,
        source_schema_version=events[0].schema_version,
        outcome_boundary=ADAPTER_OUTCOME_BOUNDARY,
        events=tuple(normalized_events),
        lineages=tuple(lineages),
        cross_links=tuple(links),
        normalized_stream_hash=normalized_stream_hash,
        raw_quality_evidence_hash=quality_hash,
        publication_evidence_hash=publication_hash,
        source_final_master_pool_hash=events[-1].master_pool_hash,
        source_final_classical_pool_hash=events[-1].classical_pool_hash,
        adapter_hash=_hash_payload(adapter_payload),
    )


def adapt_p03_jsonl(
    source: str | Path | Iterable[str],
    *,
    raw_quality_evidence: Sequence[RawQualityEvidence | Mapping[str, object]],
    publication_evidence: Sequence[PublicationEvidence | Mapping[str, object]],
) -> P04AdapterResult:
    """Read P03 JSONL lines and invoke the pure adapter."""

    if isinstance(source, (str, Path)):
        with Path(source).open(encoding="utf-8") as handle:
            records = _parse_jsonl_lines(handle)
    else:
        records = _parse_jsonl_lines(source)
    return adapt_p03_master_events(
        records,
        raw_quality_evidence=raw_quality_evidence,
        publication_evidence=publication_evidence,
    )


def _parse_jsonl_lines(lines: Iterable[str]) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for line_number, line in enumerate(lines, start=1):
        text = str(line)
        if len(text.encode("utf-8")) > MAX_JSONL_LINE_BYTES:
            raise AdapterContractViolation(
                f"P03 JSONL line {line_number} exceeds the bounded line limit"
            )
        if not text.strip():
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AdapterContractViolation(
                f"invalid P03 JSONL at line {line_number}: {exc}"
            ) from exc
        if not isinstance(value, Mapping):
            raise AdapterContractViolation(f"P03 JSONL line {line_number} is not an object")
        records.append(value)
        if len(records) > MAX_EVENTS:
            raise AdapterContractViolation(f"event count exceeds bounded limit {MAX_EVENTS}")
    return records


def _parse_source_events(
    records: Sequence[MasterEvent | Mapping[str, object]],
) -> tuple[MasterEvent, ...]:
    if not records:
        raise AdapterContractViolation("at least one P03 event is required")
    if len(records) > MAX_EVENTS:
        raise AdapterContractViolation(f"event count exceeds bounded limit {MAX_EVENTS}")
    result: list[MasterEvent] = []
    for position, record in enumerate(records):
        if isinstance(record, MasterEvent):
            try:
                validate_master_event(record)
            except ValueError as exc:
                raise AdapterContractViolation(
                    f"invalid P03 event object {position}: {exc}"
                ) from exc
            result.append(record)
            continue
        if not isinstance(record, Mapping):
            raise AdapterContractViolation(f"P03 record {position} is not an object")
        keys = {str(key) for key in record}
        missing = _P03_EVENT_KEYS - keys
        unknown = keys - _P03_EVENT_KEYS
        if missing:
            raise AdapterContractViolation(
                f"P03 record {position} missing required fields: {sorted(missing)}"
            )
        if unknown:
            raise AdapterContractViolation(
                f"P03 record {position} contains unsupported fields: {sorted(unknown)}"
            )
        try:
            result.append(master_event_from_dict(record))
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterContractViolation(f"invalid P03 record {position}: {exc}") from exc
    sequence_ids = {event.sequence_id for event in result}
    if len(sequence_ids) != 1:
        raise AdapterContractViolation("one adapter invocation must contain one sequence")
    return tuple(result)


def _parse_quality_rows(
    rows: Sequence[RawQualityEvidence | Mapping[str, object]],
) -> dict[tuple[str, int, int], RawQualityEvidence]:
    result: dict[tuple[str, int, int], RawQualityEvidence] = {}
    if len(rows) > MAX_RAW_QUALITY_ROWS:
        raise AdapterContractViolation(
            f"raw-quality row count exceeds bounded limit {MAX_RAW_QUALITY_ROWS}"
        )
    evidence_ids: set[str] = set()
    for position, row in enumerate(rows):
        try:
            evidence = row if isinstance(row, RawQualityEvidence) else RawQualityEvidence.from_mapping(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterContractViolation(f"invalid raw-quality row {position}: {exc}") from exc
        if not evidence.sequence_id or not evidence.evidence_id:
            raise AdapterContractViolation("raw-quality evidence requires IDs")
        if evidence.frame_index < 0 or evidence.track_id < 0:
            raise AdapterContractViolation("raw-quality evidence index is invalid")
        if not math.isfinite(evidence.raw_quality) or not 0.0 <= evidence.raw_quality <= 1.0:
            raise AdapterContractViolation("raw_quality must be finite in [0,1]")
        if evidence.key() in result:
            raise AdapterContractViolation(f"duplicate raw-quality key: {evidence.key()}")
        if evidence.evidence_id in evidence_ids:
            raise AdapterContractViolation(f"duplicate raw-quality evidence_id: {evidence.evidence_id}")
        evidence_ids.add(evidence.evidence_id)
        result[evidence.key()] = evidence
    return result


def _parse_publication_rows(
    rows: Sequence[PublicationEvidence | Mapping[str, object]],
) -> dict[tuple[str, int], PublicationEvidence]:
    result: dict[tuple[str, int], PublicationEvidence] = {}
    if len(rows) > MAX_PUBLICATION_ROWS:
        raise AdapterContractViolation(
            f"publication row count exceeds bounded limit {MAX_PUBLICATION_ROWS}"
        )
    publication_ids: set[str] = set()
    for position, row in enumerate(rows):
        try:
            evidence = row if isinstance(row, PublicationEvidence) else PublicationEvidence.from_mapping(row)
        except (KeyError, TypeError, ValueError) as exc:
            raise AdapterContractViolation(f"invalid publication row {position}: {exc}") from exc
        if not evidence.sequence_id or not evidence.publication_id:
            raise AdapterContractViolation("publication evidence requires IDs")
        if evidence.frame_index < 0 or evidence.image_width <= 0 or evidence.image_height <= 0:
            raise AdapterContractViolation("publication envelope dimensions/index are invalid")
        if not math.isfinite(evidence.publication_timestamp_s):
            raise AdapterContractViolation("publication timestamp must be finite")
        if evidence.coordinate_space != "pixel_uv":
            raise AdapterContractViolation("publication coordinate_space must be pixel_uv")
        ids = tuple(sorted(evidence.published_track_ids))
        if ids != evidence.published_track_ids or len(ids) != len(set(ids)):
            raise AdapterContractViolation("published_track_ids must be unique and sorted")
        _validate_hash(evidence.source_master_pool_hash, "publication master hash")
        _validate_hash(evidence.source_classical_pool_hash, "publication classical hash")
        if evidence.key() in result:
            raise AdapterContractViolation(f"duplicate publication key: {evidence.key()}")
        if evidence.publication_id in publication_ids:
            raise AdapterContractViolation(
                f"duplicate publication_id: {evidence.publication_id}"
            )
        publication_ids.add(evidence.publication_id)
        result[evidence.key()] = evidence
    return result


def _validate_quality_coverage(
    events: Sequence[MasterEvent],
    rows: Mapping[tuple[str, int, int], RawQualityEvidence],
) -> None:
    expected: set[tuple[str, int, int]] = set()
    for event in events:
        for track in (*event.k0, *event.live_learned, *event.live_classical):
            key = (event.sequence_id, event.frame_index, track.track_id)
            expected.add(key)
            evidence = rows.get(key)
            if evidence is None:
                raise AdapterContractViolation(
                    f"missing raw_quality evidence for {key}; no default is allowed"
                )
            if evidence.source != track.source:
                raise AdapterContractViolation(f"raw-quality source mismatch for {key}")
    extra = set(rows) - expected
    if extra:
        raise AdapterContractViolation(f"raw-quality evidence has extra keys: {sorted(extra)[:3]}")


def _validate_publication_coverage(
    events: Sequence[MasterEvent],
    rows: Mapping[tuple[str, int], PublicationEvidence],
) -> None:
    expected = {(event.sequence_id, event.frame_index) for event in events}
    missing = expected - set(rows)
    if missing:
        raise AdapterContractViolation(
            f"missing publication evidence for {sorted(missing)[0]}; no default is allowed"
        )
    extra = set(rows) - expected
    if extra:
        raise AdapterContractViolation(f"publication evidence has extra keys: {sorted(extra)[:3]}")


def _validate_publication_against_event(
    publication: PublicationEvidence,
    event: MasterEvent,
) -> None:
    if _f64_token(publication.publication_timestamp_s) != _f64_token(event.timestamp_s):
        raise AdapterContractViolation(
            f"publication timestamp mismatch at {event.sequence_id}/{event.frame_index}"
        )
    if publication.image_width != event.image_width or publication.image_height != event.image_height:
        raise AdapterContractViolation("publication image shape mismatch")
    if publication.published_track_ids != tuple(event.base_export_ids):
        raise AdapterContractViolation("published_track_ids must equal base_export_ids")
    if publication.source_master_pool_hash != event.master_pool_hash:
        raise AdapterContractViolation("publication master hash cross-link mismatch")
    if publication.source_classical_pool_hash != event.classical_pool_hash:
        raise AdapterContractViolation("publication classical hash cross-link mismatch")


def _convert_event(
    event: MasterEvent,
    quality_rows: Mapping[tuple[str, int, int], RawQualityEvidence],
    publication: PublicationEvidence,
) -> NormalizedMasterEvent:
    eligible_learned = {track.track_id for track in event.eligible_learned}
    eligible_classical = {track.track_id for track in event.eligible_classical}
    live_learned = {track.track_id: track for track in event.live_learned}
    live_classical = {track.track_id: track for track in event.live_classical}
    for track in event.eligible_learned:
        if live_learned[track.track_id] != track:
            raise AdapterContractViolation("learned eligible/live evidence differs")
    for track in event.eligible_classical:
        if live_classical[track.track_id] != track:
            raise AdapterContractViolation("classical eligible/live evidence differs")

    def convert(track: object, eligible: bool) -> NormalizedObservation:
        # The explicit type check keeps this adapter independent of private
        # producer state while still making failures readable.
        if not hasattr(track, "track_id"):
            raise AdapterContractViolation("invalid P03 track evidence")
        track_id = int(track.track_id)
        key = (event.sequence_id, event.frame_index, track_id)
        quality = quality_rows[key]
        return NormalizedObservation(
            track_id=track_id,
            source=str(track.source),
            u=float(track.u),
            v=float(track.v),
            raw_quality=float(quality.raw_quality),
            age=int(track.age),
            ncc=float(track.ncc),
            fb_error=float(track.fb_error),
            normalized_residual=float(track.normalized_residual),
            fh_eligible=bool(eligible),
        )

    k0 = tuple(convert(track, True) for track in event.k0)
    learned = tuple(convert(track, track.track_id in eligible_learned) for track in event.live_learned)
    classical = tuple(convert(track, track.track_id in eligible_classical) for track in event.live_classical)
    valid_models = tuple(event.model_fit.valid_models)
    fh_model = FHModelContract(
        fit_hash=event.model_fit.fit_hash,
        input_track_ids=tuple(event.model_fit.input_track_ids),
        valid_models=valid_models,
        seed=event.model_fit.seed,
        thresholds=tuple(event.model_fit.thresholds),
        arbitration=event.model_fit.arbitration,
        e_max=event.model_fit.e_max,
    )
    return NormalizedMasterEvent(
        sequence_id=event.sequence_id,
        frame_index=event.frame_index,
        timestamp_s=publication.publication_timestamp_s,
        image_width=event.image_width,
        image_height=event.image_height,
        trigger_open=_trigger_open(event.trigger_reason),
        trigger_reason=event.trigger_reason,
        k0=k0,
        base_export_ids=tuple(event.base_export_ids),
        learned_pool=learned,
        classical_pool=classical,
        fh_model=fh_model,
    )


def _trigger_open(reason: str) -> bool:
    if reason in {"NO_TRIGGER", "WARMUP"}:
        return False
    if reason in {"KLT_HEALTH_TRIGGER", "KLT_DEGRADED"}:
        return True
    raise AdapterContractViolation(f"unsupported P03 trigger reason: {reason}")


def _quality_frame_hash(
    event: MasterEvent,
    rows: Mapping[tuple[str, int, int], RawQualityEvidence],
) -> str:
    tracks = (*event.k0, *event.live_learned, *event.live_classical)
    payload = [rows[(event.sequence_id, event.frame_index, track.track_id)].payload() for track in tracks]
    return _hash_payload(sorted(payload, key=lambda item: int(item["track_id"])))


def _build_lineage_ledger(events: Sequence[MasterEvent]) -> tuple[LineageLifecycle, ...]:
    states: dict[tuple[str, int], dict[str, object]] = {}
    previous_live: dict[str, set[int]] = {"learned": set(), "classical": set()}
    retired: dict[str, set[int]] = {"learned": set(), "classical": set()}
    seen_pool: dict[int, str] = {}
    for event_ordinal, event in enumerate(events):
        for pool, live_tracks, eligible_tracks in (
            ("learned", event.live_learned, event.eligible_learned),
            ("classical", event.live_classical, event.eligible_classical),
        ):
            live_by_id = {track.track_id: track for track in live_tracks}
            live_ids = set(live_by_id)
            if retired[pool] & live_ids:
                raise AdapterContractViolation(f"{pool} lineage reappeared after termination")
            eligible_ids = {track.track_id for track in eligible_tracks}
            for track_id, track in live_by_id.items():
                prior_pool = seen_pool.get(track_id)
                if prior_pool is not None and prior_pool != pool:
                    raise AdapterContractViolation("lineage changed source pool")
                seen_pool[track_id] = pool
                key = (pool, track_id)
                state = states.get(key)
                if int(track.age) <= 0:
                    raise AdapterContractViolation("live candidate age must be positive")
                derived_birth_ordinal = int(event_ordinal) - int(track.age) + 1
                if state is None:
                    if derived_birth_ordinal >= 0:
                        birth_event = events[derived_birth_ordinal]
                        birth_frame = birth_event.frame_index
                        birth_timestamp = birth_event.timestamp_s
                    else:
                        birth_frame = None
                        birth_timestamp = None
                    state = {
                        "sequence_id": event.sequence_id,
                        "pool": pool,
                        "track_id": track_id,
                        "source": track.source,
                        "birth_event_ordinal": (
                            derived_birth_ordinal if derived_birth_ordinal >= 0 else None
                        ),
                        "birth_frame_index": birth_frame,
                        "birth_timestamp_s": birth_timestamp,
                        "birth_left_censored": birth_timestamp is None,
                        "first_live_event_ordinal": event_ordinal,
                        "first_live_frame_index": event.frame_index,
                        "first_live_timestamp_s": event.timestamp_s,
                        "last_live_frame_index": event.frame_index,
                        "last_live_timestamp_s": event.timestamp_s,
                        "termination_event_ordinal": None,
                        "termination_frame_index": None,
                        "termination_timestamp_s": None,
                        "termination_right_censored": True,
                        "eligible_frame_indices": [],
                    }
                    states[key] = state
                elif state["birth_event_ordinal"] != (
                    derived_birth_ordinal if derived_birth_ordinal >= 0 else None
                ):
                    raise AdapterContractViolation(
                        "candidate age implies inconsistent birth event"
                    )
                state["last_live_frame_index"] = event.frame_index
                state["last_live_timestamp_s"] = event.timestamp_s
                if track_id in eligible_ids:
                    state["eligible_frame_indices"].append(event.frame_index)
            terminated_now = previous_live[pool] - live_ids
            for track_id in terminated_now:
                state = states[(pool, track_id)]
                state["termination_event_ordinal"] = event_ordinal
                state["termination_frame_index"] = event.frame_index
                state["termination_timestamp_s"] = event.timestamp_s
                state["termination_right_censored"] = False
                retired[pool].add(track_id)
            previous_live[pool] = live_ids
    output = []
    for key in sorted(states):
        state = states[key]
        state["eligible_frame_indices"] = tuple(state["eligible_frame_indices"])
        output.append(LineageLifecycle(**state))
    return tuple(output)


def _require_keys(
    value: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str],
    label: str,
) -> None:
    keys = {str(key) for key in value}
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise AdapterContractViolation(f"{label} missing fields: {sorted(missing)}")
    if unknown:
        raise AdapterContractViolation(f"{label} contains unsupported fields: {sorted(unknown)}")


def _validate_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise AdapterContractViolation(f"{label} must be lowercase SHA-256")


__all__ = [
    "ADAPTER_OUTCOME_BOUNDARY",
    "ADAPTER_SCHEMA_VERSION",
    "AdapterContractViolation",
    "EventCrossLink",
    "LineageLifecycle",
    "P04AdapterResult",
    "PublicationEvidence",
    "RawQualityEvidence",
    "adapt_p03_jsonl",
    "adapt_p03_master_events",
]
