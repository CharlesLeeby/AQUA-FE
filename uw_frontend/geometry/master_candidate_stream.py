"""Selector-independent master-candidate stream contract (P03 candidate).

This module contains no image, ROS, or selector code.  It defines the
machine-readable boundary between a common producer and arm-specific replay:

* ``K_t^0`` is the immutable native-KLT base;
* ``E_t`` is a standing pool of never-admitted, already eligible candidates;
* F/H models are fitted from sorted ``K_t^0`` correspondences only;
* H/P admission state ``L_t`` is represented by a separate arm-chain hash.

The distinction is intentional.  A final exported bag cannot be used to
reconstruct a selector-independent candidate pool after admission feedback has
changed the carrier.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "isj-master-candidate-stream-v1"
ARM_SCHEMA_VERSION = "isj-arm-chain-v1"
HASH_HEX_LENGTH = 64
LEARNED_SOURCES = frozenset({"learned", "learned_xfeat", "learned_sp_lg", "learned_loftr"})
CLASSICAL_SOURCES = frozenset({"classical", "classical_gftt", "classical_fast"})
BASE_SOURCE = "klt_base"


@dataclass(frozen=True)
class TrackEvidence:
    track_id: int
    source: str
    u: float
    v: float
    q_lower: float = 1.0
    normalized_residual: float = 0.0
    age: int = 0
    ncc: float = 1.0
    fb_error: float = 0.0
    survival_count: int = 0
    residual_history: tuple[float, ...] = ()
    motion_ratio: float | None = None


@dataclass(frozen=True)
class ModelFitEvidence:
    """Identity of the frozen base-only F/H fit at one decision event."""

    valid_models: tuple[str, ...]
    seed: int
    input_track_ids: tuple[int, ...]
    thresholds: tuple[tuple[str, float], ...]
    fit_hash: str
    arbitration: str = "min_normalized_residual"
    confidence: float = 0.999
    max_iterations: int = 2000
    e_max: float = 4.0


@dataclass(frozen=True)
class MasterEvent:
    sequence_id: str
    frame_index: int
    timestamp_s: float
    image_width: int
    image_height: int
    trigger_reason: str
    k0: tuple[TrackEvidence, ...]
    eligible_learned: tuple[TrackEvidence, ...]
    eligible_classical: tuple[TrackEvidence, ...]
    live_learned: tuple[TrackEvidence, ...]
    live_classical: tuple[TrackEvidence, ...]
    base_export_ids: tuple[int, ...]
    model_fit: ModelFitEvidence
    config_hash: str
    previous_master_hash: str
    master_pool_hash: str
    classical_pool_hash: str
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence_id": self.sequence_id,
            "frame_index": self.frame_index,
            "timestamp_s": self.timestamp_s,
            "image_width": self.image_width,
            "image_height": self.image_height,
            "trigger_reason": self.trigger_reason,
            "k0": [_track_dict(track) for track in self.k0],
            "eligible_learned": [_track_dict(track) for track in self.eligible_learned],
            "eligible_classical": [_track_dict(track) for track in self.eligible_classical],
            "live_learned": [_track_dict(track) for track in self.live_learned],
            "live_classical": [_track_dict(track) for track in self.live_classical],
            "base_export_ids": list(self.base_export_ids),
            "model_fit": _model_dict(self.model_fit),
            "config_hash": self.config_hash,
            "previous_master_hash": self.previous_master_hash,
            "master_pool_hash": self.master_pool_hash,
            "classical_pool_hash": self.classical_pool_hash,
        }


def master_event_from_dict(data: Mapping[str, object]) -> MasterEvent:
    """Parse and validate one JSONL event emitted by the P03 producer."""

    def track(value: Mapping[str, object]) -> TrackEvidence:
        return TrackEvidence(
            track_id=int(value["track_id"]),
            source=str(value["source"]),
            u=float(value["u"]),
            v=float(value["v"]),
            q_lower=float(value.get("q_lower", 1.0)),
            normalized_residual=float(value.get("normalized_residual", 0.0)),
            age=int(value.get("age", 0)),
            ncc=float(value.get("ncc", 1.0)),
            fb_error=float(value.get("fb_error", 0.0)),
            survival_count=int(value.get("survival_count", 0)),
            residual_history=tuple(float(item) for item in value.get("residual_history", [])),
            motion_ratio=(
                None if value.get("motion_ratio") is None else float(value["motion_ratio"])
            ),
        )

    raw_model = data["model_fit"]
    if not isinstance(raw_model, Mapping):
        raise ValueError("model_fit must be an object")
    raw_thresholds = raw_model.get("thresholds", [])
    model = ModelFitEvidence(
        valid_models=tuple(str(item) for item in raw_model.get("valid_models", [])),
        seed=int(raw_model["seed"]),
        input_track_ids=tuple(int(item) for item in raw_model["input_track_ids"]),
        thresholds=tuple((str(item[0]), float(item[1])) for item in raw_thresholds),
        fit_hash=str(raw_model["fit_hash"]),
        arbitration=str(raw_model.get("arbitration", "min_normalized_residual")),
        confidence=float(raw_model.get("confidence", 0.999)),
        max_iterations=int(raw_model.get("max_iterations", 2000)),
        e_max=float(raw_model.get("e_max", 4.0)),
    )
    event = MasterEvent(
        sequence_id=str(data["sequence_id"]),
        frame_index=int(data["frame_index"]),
        timestamp_s=float(data["timestamp_s"]),
        image_width=int(data["image_width"]),
        image_height=int(data["image_height"]),
        trigger_reason=str(data["trigger_reason"]),
        k0=tuple(track(item) for item in data.get("k0", [])),
        eligible_learned=tuple(track(item) for item in data.get("eligible_learned", [])),
        eligible_classical=tuple(track(item) for item in data.get("eligible_classical", [])),
        live_learned=tuple(track(item) for item in data.get("live_learned", data.get("eligible_learned", []))),
        live_classical=tuple(track(item) for item in data.get("live_classical", data.get("eligible_classical", []))),
        base_export_ids=tuple(int(item) for item in data.get("base_export_ids", [])),
        model_fit=model,
        config_hash=str(data["config_hash"]),
        previous_master_hash=str(data.get("previous_master_hash", "")),
        master_pool_hash=str(data["master_pool_hash"]),
        classical_pool_hash=str(data["classical_pool_hash"]),
        schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
    )
    validate_master_event(event)
    return event


@dataclass(frozen=True)
class AdmissionDecision:
    candidate_id: int
    selected: bool
    rank: int
    gain: float
    q_lower: float
    normalized_residual: float
    reason: str


@dataclass(frozen=True)
class ArmChainResult:
    arm_id: str
    active_ids: tuple[int, ...]
    exported_candidate_ids: tuple[int, ...]
    decisions: tuple[AdmissionDecision, ...]
    arm_chain_hash: str


def build_master_event(
    *,
    sequence_id: str,
    frame_index: int,
    timestamp_s: float,
    image_shape: tuple[int, int],
    trigger_reason: str,
    k0: Sequence[TrackEvidence],
    eligible_learned: Sequence[TrackEvidence],
    eligible_classical: Sequence[TrackEvidence],
    live_learned: Sequence[TrackEvidence] | None = None,
    live_classical: Sequence[TrackEvidence] | None = None,
    base_export_ids: Sequence[int],
    model_fit: ModelFitEvidence,
    config_hash: str,
    previous_master_hash: str = "",
) -> MasterEvent:
    width, height = _validate_image_shape(image_shape)
    event = MasterEvent(
        sequence_id=str(sequence_id),
        frame_index=int(frame_index),
        timestamp_s=float(timestamp_s),
        image_width=width,
        image_height=height,
        trigger_reason=str(trigger_reason),
        k0=tuple(sorted(k0, key=lambda track: int(track.track_id))),
        eligible_learned=tuple(sorted(eligible_learned, key=lambda track: int(track.track_id))),
        eligible_classical=tuple(sorted(eligible_classical, key=lambda track: int(track.track_id))),
        live_learned=tuple(sorted(live_learned if live_learned is not None else eligible_learned, key=lambda track: int(track.track_id))),
        live_classical=tuple(sorted(live_classical if live_classical is not None else eligible_classical, key=lambda track: int(track.track_id))),
        base_export_ids=tuple(sorted(int(value) for value in base_export_ids)),
        model_fit=model_fit,
        config_hash=str(config_hash),
        previous_master_hash=str(previous_master_hash),
        master_pool_hash="",
        classical_pool_hash="",
    )
    validate_master_event(event, verify_hashes=False)
    master_hash, classical_hash = compute_master_hashes(event)
    return MasterEvent(
        **{
            **event.__dict__,
            "master_pool_hash": master_hash,
            "classical_pool_hash": classical_hash,
        }
    )


def validate_master_event(event: MasterEvent, *, verify_hashes: bool = True) -> None:
    if event.schema_version != SCHEMA_VERSION:
        raise ValueError(f"unsupported master stream schema: {event.schema_version}")
    if not event.sequence_id or event.frame_index < 0:
        raise ValueError("sequence_id and non-negative frame_index are required")
    if not math.isfinite(float(event.timestamp_s)):
        raise ValueError("event timestamp must be finite")
    _validate_image_shape((event.image_width, event.image_height))
    _validate_hash(event.config_hash, "config_hash")
    if event.previous_master_hash:
        _validate_hash(event.previous_master_hash, "previous_master_hash")
    _validate_model_fit(event.model_fit)

    _validate_unique_tracks(event.k0, "K0")
    _validate_unique_tracks(event.eligible_learned, "E_learned")
    _validate_unique_tracks(event.eligible_classical, "E_classical")
    _validate_unique_tracks(event.live_learned, "live_learned")
    _validate_unique_tracks(event.live_classical, "live_classical")
    all_ids = [track.track_id for track in event.k0]
    all_ids.extend(track.track_id for track in event.live_learned)
    all_ids.extend(track.track_id for track in event.live_classical)
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("K0, learned, and classical IDs must be mutually disjoint")
    if not {track.track_id for track in event.eligible_learned} <= {track.track_id for track in event.live_learned}:
        raise ValueError("eligible learned candidates must be a subset of live learned candidates")
    if not {track.track_id for track in event.eligible_classical} <= {track.track_id for track in event.live_classical}:
        raise ValueError("eligible classical candidates must be a subset of live classical candidates")
    for track in event.k0:
        if track.source != BASE_SOURCE:
            raise ValueError("K0 contains a non-base source")
    for track in event.eligible_learned:
        if track.source not in LEARNED_SOURCES:
            raise ValueError("learned E contains a non-learned source")
    for track in event.eligible_classical:
        if track.source not in CLASSICAL_SOURCES:
            raise ValueError("classical E contains a non-classical source")
    for track in event.live_learned:
        if track.source not in LEARNED_SOURCES:
            raise ValueError("live learned pool contains a non-learned source")
    for track in event.live_classical:
        if track.source not in CLASSICAL_SOURCES:
            raise ValueError("live classical pool contains a non-classical source")
    if not set(event.base_export_ids) <= {track.track_id for track in event.k0}:
        raise ValueError("base_export_ids must be a subset of K0")
    if len(event.base_export_ids) != len(set(event.base_export_ids)):
        raise ValueError("base_export_ids must be unique")
    for label, tracks in (
        ("K0", event.k0),
        ("E_learned", event.eligible_learned),
        ("E_classical", event.eligible_classical),
        ("live_learned", event.live_learned),
        ("live_classical", event.live_classical),
    ):
        for track in tracks:
            if not (0.0 <= float(track.u) < event.image_width and 0.0 <= float(track.v) < event.image_height):
                raise ValueError(f"{label} coordinate is outside image bounds")
    if len(event.model_fit.valid_models) == 0 and (
        event.eligible_learned or event.eligible_classical
    ):
        raise ValueError("NO_VALID_BASE_MODEL must reject all new candidates")
    if set(event.model_fit.input_track_ids) != {track.track_id for track in event.k0}:
        raise ValueError("F/H fit input IDs must be exactly the sorted K0 IDs")
    if tuple(event.model_fit.input_track_ids) != tuple(sorted(event.model_fit.input_track_ids)):
        raise ValueError("F/H fit input IDs must be stably sorted")
    if verify_hashes:
        expected_master, expected_classical = compute_master_hashes(event)
        if event.master_pool_hash != expected_master:
            raise ValueError("master_pool_hash mismatch")
        if event.classical_pool_hash != expected_classical:
            raise ValueError("classical_pool_hash mismatch")


def compute_master_hashes(event: MasterEvent) -> tuple[str, str]:
    """Return hashes for learned H/P and independent classical pools."""

    common = {
        "schema_version": event.schema_version,
        "sequence_id": event.sequence_id,
        "frame_index": int(event.frame_index),
        "timestamp": _float_token(event.timestamp_s),
        "image_shape": [int(event.image_width), int(event.image_height)],
        "trigger_reason": event.trigger_reason,
        "base_export_ids": list(event.base_export_ids),
        "model_fit": _model_payload(event.model_fit),
        "config_hash": event.config_hash,
        "previous_master_hash": event.previous_master_hash,
        "k0": [_track_payload(track, event.image_width, event.image_height) for track in event.k0],
    }
    master_payload = {
        **common,
        "eligible_learned": [
            _track_payload(track, event.image_width, event.image_height)
            for track in event.eligible_learned
        ],
        "live_learned": [
            _track_payload(track, event.image_width, event.image_height)
            for track in event.live_learned
        ],
    }
    classical_payload = {
        **common,
        "eligible_classical": [
            _track_payload(track, event.image_width, event.image_height)
            for track in event.eligible_classical
        ],
        "live_classical": [
            _track_payload(track, event.image_width, event.image_height)
            for track in event.live_classical
        ],
    }
    return _hash_payload(master_payload), _hash_payload(classical_payload)


def build_arm_chain(
    *,
    arm_id: str,
    event: MasterEvent,
    active_tracks: Sequence[TrackEvidence],
    decisions: Sequence[AdmissionDecision],
    selector_config_hash: str,
    selector_model_hash: str,
    previous_arm_hash: str = "",
    b_active: int,
    total_feature_cap: int,
    backend_q: float = 1.0,
    candidate_pool: str = "learned",
) -> ArmChainResult:
    """Build and validate one arm-specific chain entry over a master event."""

    validate_master_event(event)
    _validate_hash(selector_config_hash, "selector_config_hash")
    _validate_hash(selector_model_hash, "selector_model_hash")
    if previous_arm_hash:
        _validate_hash(previous_arm_hash, "previous_arm_hash")
    if int(b_active) < 0 or int(total_feature_cap) < 0:
        raise ValueError("b_active and total_feature_cap must be non-negative")
    if abs(float(backend_q) - 1.0) > 1e-12:
        raise ValueError("controlled external arms must use backend q=1")

    if candidate_pool not in {"learned", "classical"}:
        raise ValueError("candidate_pool must be learned or classical")
    eligible_tracks = (
        event.eligible_learned
        if candidate_pool == "learned"
        else event.eligible_classical
    )
    allowed_sources = LEARNED_SOURCES if candidate_pool == "learned" else CLASSICAL_SOURCES
    eligible_by_id = {track.track_id: track for track in eligible_tracks}
    # active_tracks is L_t before this event. Newly selected E_t candidates
    # become part of the returned active state for the next event.
    active_before = tuple(sorted(active_tracks, key=lambda track: int(track.track_id)))
    active_before_ids = tuple(track.track_id for track in active_before)
    if len(active_before_ids) != len(set(active_before_ids)):
        raise ValueError("active L IDs must be unique")
    if any(track.source not in allowed_sources for track in active_before):
        raise ValueError(f"active L contains a non-{candidate_pool} proposal source")
    decisions_tuple = tuple(decisions)
    decision_ids = [decision.candidate_id for decision in decisions_tuple]
    if len(decision_ids) != len(set(decision_ids)):
        raise ValueError("candidate decisions must have unique IDs")
    if set(decision_ids) - set(eligible_by_id):
        raise ValueError("decisions must cover only current eligible E")
    selected = [decision for decision in decisions_tuple if decision.selected]
    if any(decision.candidate_id in set(active_before_ids) for decision in selected):
        raise ValueError("an active lineage cannot be admitted again")
    ranks = sorted(decision.rank for decision in selected)
    if ranks != list(range(1, len(selected) + 1)):
        raise ValueError("selected ranks must be contiguous and 1-based")
    if any(decision.selected and decision.reason != "ACCEPTED" for decision in decisions_tuple):
        raise ValueError("selected decisions must use reason ACCEPTED")
    if any(not decision.selected and decision.rank != 0 for decision in decisions_tuple):
        raise ValueError("rejected decisions must have rank zero")
    selected_ids = {decision.candidate_id for decision in selected}
    selected_tracks = tuple(eligible_by_id[candidate_id] for candidate_id in sorted(selected_ids))
    active = tuple(sorted((*active_before, *selected_tracks), key=lambda track: int(track.track_id)))
    active_ids = tuple(track.track_id for track in active)
    if len(active_ids) > int(b_active):
        raise ValueError("concurrent B_active lineage cap exceeded")

    exported = tuple(sorted(active_ids))
    if len(event.base_export_ids) + len(exported) > int(total_feature_cap):
        raise ValueError("total exported-feature cap exceeded")
    payload = {
        "schema_version": ARM_SCHEMA_VERSION,
        "arm_id": str(arm_id),
        "candidate_pool": candidate_pool,
        "sequence_id": event.sequence_id,
        "frame_index": int(event.frame_index),
        "previous_arm_hash": previous_arm_hash,
        "master_pool_hash": event.master_pool_hash,
        "selector_config_hash": selector_config_hash,
        "selector_model_hash": selector_model_hash,
        "image_shape": [event.image_width, event.image_height],
        "k0": [_track_payload(track, event.image_width, event.image_height) for track in event.k0],
        "active_l_before": [
            _track_payload(track, event.image_width, event.image_height)
            for track in active_before
        ],
        "active_l_after": [
            _track_payload(track, event.image_width, event.image_height) for track in active
        ],
        "eligible_e": [
            _track_payload(track, event.image_width, event.image_height)
            for track in eligible_tracks
        ],
        "active_slots_before": max(0, int(b_active) - len(active_before_ids)),
        "b_active": int(b_active),
        "total_feature_cap": int(total_feature_cap),
        "backend_q": _float_token(backend_q),
        "decisions": [_decision_payload(decision) for decision in decisions_tuple],
        "exported_candidate_ids": list(exported),
    }
    return ArmChainResult(
        arm_id=str(arm_id),
        active_ids=active_ids,
        exported_candidate_ids=exported,
        decisions=decisions_tuple,
        arm_chain_hash=_hash_payload(payload),
    )


class MasterStreamValidator:
    """Validate a complete, frame-ordered master stream and its retirement rule."""

    def __init__(self) -> None:
        self.sequence_id: str | None = None
        self.previous_hash = ""
        self.previous_frame = -1
        self.previous_timestamp = float("-inf")
        self.retired_learned: set[int] = set()
        self.retired_classical: set[int] = set()
        self.last_learned: set[int] | None = None
        self.last_classical: set[int] | None = None

    def push(self, event: MasterEvent) -> str:
        validate_master_event(event)
        if self.sequence_id is None:
            self.sequence_id = event.sequence_id
        if event.sequence_id != self.sequence_id:
            raise ValueError("master stream sequence changed")
        if event.frame_index <= self.previous_frame:
            raise ValueError("master stream frame index is not strictly increasing")
        if event.timestamp_s <= self.previous_timestamp:
            raise ValueError("master stream timestamp is not strictly increasing")
        if event.previous_master_hash != self.previous_hash:
            raise ValueError("master stream predecessor hash mismatch")
        learned = {track.track_id for track in event.live_learned}
        classical = {track.track_id for track in event.live_classical}
        if self.last_learned is not None:
            self.retired_learned.update(self.last_learned - learned)
            self.retired_classical.update((self.last_classical or set()) - classical)
        if self.retired_learned & learned:
            raise ValueError("terminated learned lineage was re-admitted to E")
        if self.retired_classical & classical:
            raise ValueError("terminated classical lineage was re-admitted to E")
        self.last_learned = learned
        self.last_classical = classical
        self.previous_hash = event.master_pool_hash
        self.previous_frame = event.frame_index
        self.previous_timestamp = event.timestamp_s
        return self.previous_hash


class ArmChainValidator:
    """Enforce never-readmit and termination semantics for one H/P arm."""

    def __init__(self, arm_id: str, candidate_pool: str = "learned") -> None:
        if candidate_pool not in {"learned", "classical"}:
            raise ValueError("candidate_pool must be learned or classical")
        self.arm_id = str(arm_id)
        self.candidate_pool = candidate_pool
        self.previous_hash = ""
        self.admitted: set[int] = set()
        self.retired: set[int] = set()
        self.active: set[int] = set()

    def push(
        self,
        event: MasterEvent,
        active_tracks: Sequence[TrackEvidence],
        decisions: Sequence[AdmissionDecision],
        *,
        selector_config_hash: str,
        selector_model_hash: str,
        b_active: int,
        total_feature_cap: int,
    ) -> ArmChainResult:
        live_tracks = event.live_learned if self.candidate_pool == "learned" else event.live_classical
        live_ids = {track.track_id for track in live_tracks}
        supplied_ids = {track.track_id for track in active_tracks}
        if not supplied_ids <= live_ids:
            raise ValueError("active L contains a terminated or non-live lineage")
        if (self.active & live_ids) - supplied_ids:
            raise ValueError("active lineage was dropped while still live")
        eligible_tracks = (
            event.eligible_learned
            if self.candidate_pool == "learned"
            else event.eligible_classical
        )
        selected_before_validation = {
            decision.candidate_id for decision in decisions if decision.selected
        }
        if selected_before_validation & self.admitted:
            raise ValueError("lineage was admitted more than once")
        expected_decisions = {
            track.track_id for track in eligible_tracks
        } - self.admitted
        supplied_decisions = {decision.candidate_id for decision in decisions}
        if supplied_decisions != expected_decisions:
            raise ValueError("decisions must provide a complete ranking of arm-filtered E")
        result = build_arm_chain(
            arm_id=self.arm_id,
            event=event,
            active_tracks=active_tracks,
            decisions=decisions,
            selector_config_hash=selector_config_hash,
            selector_model_hash=selector_model_hash,
            previous_arm_hash=self.previous_hash,
            b_active=b_active,
            total_feature_cap=total_feature_cap,
            candidate_pool=self.candidate_pool,
        )
        current = set(result.active_ids)
        selected = {decision.candidate_id for decision in result.decisions if decision.selected}
        if selected & self.admitted:
            raise ValueError("lineage was admitted more than once")
        if current & self.retired:
            raise ValueError("terminated lineage reappeared in active L")
        allowed_existing = self.active - current
        self.retired.update(allowed_existing)
        self.admitted.update(selected)
        if not current <= self.admitted:
            raise ValueError("active L contains a lineage that was never admitted")
        self.active = current
        self.previous_hash = result.arm_chain_hash
        return result


def _validate_unique_tracks(tracks: Sequence[TrackEvidence], label: str) -> None:
    ids = [int(track.track_id) for track in tracks]
    if any(track_id < 0 for track_id in ids):
        raise ValueError(f"{label} contains a negative track ID")
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} contains duplicate track IDs")
    for track in tracks:
        if not math.isfinite(float(track.u)) or not math.isfinite(float(track.v)):
            raise ValueError(f"{label} contains non-finite coordinates")
        if not 0.0 <= float(track.q_lower) <= 1.0:
            raise ValueError(f"{label} q_lower must be in [0,1]")
        if (
            float(track.normalized_residual) < 0.0
            or float(track.normalized_residual) > 4.0
            or not math.isfinite(float(track.normalized_residual))
        ):
            raise ValueError(f"{label} normalized residual must be finite in [0,4]")
        if int(track.age) < 0 or int(track.survival_count) < 0:
            raise ValueError(f"{label} age/survival must be non-negative")
        if not math.isfinite(float(track.ncc)) or not math.isfinite(float(track.fb_error)):
            raise ValueError(f"{label} NCC/FB evidence must be finite")
        if any(not math.isfinite(float(value)) for value in track.residual_history):
            raise ValueError(f"{label} residual history must be finite")


def _validate_model_fit(model: ModelFitEvidence) -> None:
    if model.seed != 20260730:
        raise ValueError("P03 F/H seed must be 20260730")
    if tuple(model.input_track_ids) != tuple(sorted(model.input_track_ids)):
        raise ValueError("model input IDs must be sorted")
    if not all(name in {"F", "H"} for name in model.valid_models):
        raise ValueError("only F/H models are allowed in the P03 base fit")
    _validate_hash(model.fit_hash, "model_fit_hash")
    thresholds = dict(model.thresholds)
    for name in model.valid_models:
        if name not in thresholds or float(thresholds[name]) <= 0.0:
            raise ValueError(f"missing positive threshold for model {name}")
    if model.arbitration != "min_normalized_residual":
        raise ValueError("unsupported F/H arbitration")
    if abs(float(model.confidence) - 0.999) > 1e-12:
        raise ValueError("P03 F/H confidence must be 0.999")
    if int(model.max_iterations) != 2000:
        raise ValueError("P03 F/H max_iterations must be 2000")
    if abs(float(model.e_max) - 4.0) > 1e-12:
        raise ValueError("P03 normalized residual e_max must be 4.0")
    if set(model.valid_models) - {"F", "H"}:
        raise ValueError("only F/H models are allowed in the P03 base fit")
    if set(thresholds) - {"F", "H"}:
        raise ValueError("model thresholds contain an unsupported model")
    frozen_thresholds = {"F": 2.5, "H": 5.0}
    for name, expected in frozen_thresholds.items():
        if name in thresholds and abs(float(thresholds[name]) - expected) > 1e-12:
            raise ValueError(f"P03 {name} threshold drift")


def _validate_image_shape(shape: tuple[int, int]) -> tuple[int, int]:
    width, height = (int(shape[0]), int(shape[1]))
    if width <= 0 or height <= 0:
        raise ValueError("image shape must be positive (width, height)")
    return width, height


def _validate_hash(value: str, label: str) -> None:
    if len(value) != HASH_HEX_LENGTH or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")


def _track_payload(track: TrackEvidence, width: int, height: int) -> dict[str, object]:
    return {
        "id": int(track.track_id),
        "source": track.source,
        "u": _float_token(track.u),
        "v": _float_token(track.v),
        "z": [_float_token(1.0), _float_token(2.0 * track.u / width - 1.0), _float_token(2.0 * track.v / height - 1.0)],
        "q_lower": _float_token(track.q_lower),
        "normalized_residual": _float_token(track.normalized_residual),
        "age": int(track.age),
        "ncc": _float_token(track.ncc),
        "fb_error": _float_token(track.fb_error),
        "survival_count": int(track.survival_count),
        "residual_history": [_float_token(value) for value in track.residual_history],
        "motion_ratio": None if track.motion_ratio is None else _float_token(track.motion_ratio),
    }


def _track_dict(track: TrackEvidence) -> dict[str, object]:
    return {
        "track_id": int(track.track_id),
        "source": track.source,
        "u": float(track.u),
        "v": float(track.v),
        "q_lower": float(track.q_lower),
        "normalized_residual": float(track.normalized_residual),
        "age": int(track.age),
        "ncc": float(track.ncc),
        "fb_error": float(track.fb_error),
        "survival_count": int(track.survival_count),
        "residual_history": [float(value) for value in track.residual_history],
        "motion_ratio": track.motion_ratio,
    }


def _model_payload(model: ModelFitEvidence) -> dict[str, object]:
    return {
        "valid_models": list(model.valid_models),
        "seed": int(model.seed),
        "input_track_ids": list(model.input_track_ids),
        "thresholds": [[name, _float_token(value)] for name, value in model.thresholds],
        "fit_hash": model.fit_hash,
        "arbitration": model.arbitration,
        "confidence": _float_token(model.confidence),
        "max_iterations": int(model.max_iterations),
        "e_max": _float_token(model.e_max),
    }


def _model_dict(model: ModelFitEvidence) -> dict[str, object]:
    return {
        "valid_models": list(model.valid_models),
        "seed": int(model.seed),
        "input_track_ids": list(model.input_track_ids),
        "thresholds": [[name, float(value)] for name, value in model.thresholds],
        "fit_hash": model.fit_hash,
        "arbitration": model.arbitration,
        "confidence": float(model.confidence),
        "max_iterations": int(model.max_iterations),
        "e_max": float(model.e_max),
    }


def _decision_payload(decision: AdmissionDecision) -> dict[str, object]:
    return {
        "candidate_id": int(decision.candidate_id),
        "selected": bool(decision.selected),
        "rank": int(decision.rank),
        "gain": _float_token(decision.gain),
        "q_lower": _float_token(decision.q_lower),
        "normalized_residual": _float_token(decision.normalized_residual),
        "reason": decision.reason,
    }


def _float_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def _hash_payload(payload: Mapping[str, object]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


__all__ = [
    "AdmissionDecision",
    "ArmChainResult",
    "ArmChainValidator",
    "CLASSICAL_SOURCES",
    "LEARNED_SOURCES",
    "MasterEvent",
    "MasterStreamValidator",
    "ModelFitEvidence",
    "SCHEMA_VERSION",
    "TrackEvidence",
    "build_arm_chain",
    "build_master_event",
    "compute_master_hashes",
    "master_event_from_dict",
    "validate_master_event",
]
