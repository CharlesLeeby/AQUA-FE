#!/usr/bin/env python3
"""Pure, outcome-blind P04 arm replay contract (v4).

The module consumes normalized master-event records and emits three frontend
arms without reading images, ROS bags, VINS output, or trajectory metrics:

* ``P_legacy``: learned candidates under the frozen distance/grid heuristic;
* ``C_legacy``: an independent classical pool under the same heuristic;
* ``B2_all_eligible``: all post-F/H-eligible learned candidates, bounded only
  by the shared active-lineage and total-feature budgets.

"All eligible" does not bypass the shared trigger or F/H correctness gate.
The core entrypoint, :func:`replay_master_events`, is a pure function.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = "isj-p04-nativeq-arm-replay-v4"
DROP_SCHEMA_VERSION = "isj-p04-nativeq-exact-drop-v4"
B_ACTIVE = 8
TOTAL_FEATURE_CAP = 350
MAX_EVENTS = 100_000
MAX_POOL_TRACKS = 4_096
MAX_EXACT_FLOAT32_ID = 16_777_216
MAX_TRACK_AGE = 1_000_000
GRID_ROWS = 4
GRID_COLS = 6
FH_SEED = 20260730
FH_THRESHOLDS = (("F", 2.5), ("H", 5.0))
FH_E_MAX = 4.0
NATIVE_Q_MODE = "vins_safe"
NATIVE_Q_ALPHA = 0.65
NATIVE_Q_FLOOR = 0.80
QUALITY_ROLE_KLT = "klt_backbone"
QUALITY_ROLE_SIDECAR = "candidate_sidecar"
OUTCOME_BOUNDARY = "NORMALIZED_FRONTEND_ONLY_NO_VINS_APE_RPE"

P_LEGACY = "P_legacy"
C_LEGACY = "C_legacy"
B2_ALL_ELIGIBLE = "B2_all_eligible"
ARM_IDS = (P_LEGACY, C_LEGACY, B2_ALL_ELIGIBLE)

_KLT_SOURCES = frozenset({"klt", "klt_base"})
_LEARNED_SOURCES = frozenset(
    {"xfeat", "xfeat_confirmed", "learned_xfeat", "learned_xfeat_confirmed"}
)
_CLASSICAL_SOURCES = frozenset(
    {
        "gftt",
        "gftt_seed",
        "gftt_confirmed",
        "classical_gftt",
        "classical_gftt_confirmed",
    }
)


class ContractViolation(ValueError):
    """Raised when a normalized record violates the frozen v4 contract."""


def _f64_token(value: float) -> str:
    return struct.pack(">d", float(value)).hex()


def _f32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", float(value)))[0]


def _f32_token(value: float) -> str:
    return struct.pack(">f", _f32(value)).hex()


def _hash_payload(payload: Mapping[str, object]) -> str:
    blob = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return hashlib.sha256(blob).hexdigest()


GATE_POLICY_SPEC = {
    "version": "shared-trigger-fh-gate-v4",
    "inputs": ["trigger_open", "fh.valid_models", "candidate.fh_eligible"],
    "forbidden_inputs": ["source", "detector_score", "trajectory", "APE", "RPE"],
    "decision": "trigger_open and valid_F_or_H and candidate_fh_eligible",
}
GATE_POLICY_HASH = _hash_payload(GATE_POLICY_SPEC)

NATIVE_Q_MAPPER_SPEC = {
    "version": "candidate-v3-vins-safe-scalar-v4",
    "mode": NATIVE_Q_MODE,
    "alpha": _f64_token(NATIVE_Q_ALPHA),
    "floor": _f64_token(NATIVE_Q_FLOOR),
    "raw_clip": [_f64_token(0.05), _f64_token(1.0)],
    "quality_roles": [QUALITY_ROLE_KLT, QUALITY_ROLE_SIDECAR],
    "inputs": ["quality_role", "raw_quality", "age", "fb_error", "ncc"],
    "float_contract": "float32-staged-output",
}
NATIVE_Q_MAPPER_HASH = _hash_payload(NATIVE_Q_MAPPER_SPEC)

REPLAY_CONTRACT_SPEC = {
    "schema_version": SCHEMA_VERSION,
    "arms": list(ARM_IDS),
    "b_active": B_ACTIVE,
    "total_feature_cap": TOTAL_FEATURE_CAP,
    "grid": [GRID_ROWS, GRID_COLS],
    "heuristic": "empty_K0_cell_then_descending_nearest_K0_distance_then_id",
    "b2": "canonical_id_all_post_gate_eligible",
    "gate_policy_hash": GATE_POLICY_HASH,
    "native_q_mapper_hash": NATIVE_Q_MAPPER_HASH,
    "outcome_boundary": OUTCOME_BOUNDARY,
}
REPLAY_CONTRACT_HASH = _hash_payload(REPLAY_CONTRACT_SPEC)


@dataclass(frozen=True)
class NormalizedObservation:
    track_id: int
    source: str
    u: float
    v: float
    raw_quality: float
    age: int
    ncc: float
    fb_error: float
    normalized_residual: float = 0.0
    fh_eligible: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NormalizedObservation":
        _require_keys(
            value,
            required={
                "track_id",
                "source",
                "u",
                "v",
                "raw_quality",
                "age",
                "ncc",
                "fb_error",
            },
            optional={"normalized_residual", "fh_eligible"},
            label="observation",
        )
        return cls(
            track_id=int(value["track_id"]),
            source=str(value["source"]),
            u=float(value["u"]),
            v=float(value["v"]),
            raw_quality=float(value["raw_quality"]),
            age=int(value["age"]),
            ncc=float(value["ncc"]),
            fb_error=float(value["fb_error"]),
            normalized_residual=float(value.get("normalized_residual", 0.0)),
            fh_eligible=_strict_bool(value.get("fh_eligible", True), "fh_eligible"),
        )

    def payload(self) -> dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "source": _canonical_source(self.source),
            "u": _f64_token(self.u),
            "v": _f64_token(self.v),
            "raw_quality": _f64_token(self.raw_quality),
            "age": int(self.age),
            "ncc": _f64_token(self.ncc),
            "fb_error": _f64_token(self.fb_error),
            "normalized_residual": _f64_token(self.normalized_residual),
            "fh_eligible": bool(self.fh_eligible),
        }

    def as_dict(self) -> dict[str, object]:
        """Return the external normalized-record representation."""

        return {
            "track_id": int(self.track_id),
            "source": self.source,
            "u": float(self.u),
            "v": float(self.v),
            "raw_quality": float(self.raw_quality),
            "age": int(self.age),
            "ncc": float(self.ncc),
            "fb_error": float(self.fb_error),
            "normalized_residual": float(self.normalized_residual),
            "fh_eligible": bool(self.fh_eligible),
        }


@dataclass(frozen=True)
class FHModelContract:
    fit_hash: str
    input_track_ids: tuple[int, ...]
    valid_models: tuple[str, ...] = ("F", "H")
    seed: int = FH_SEED
    thresholds: tuple[tuple[str, float], ...] = FH_THRESHOLDS
    arbitration: str = "min_normalized_residual"
    e_max: float = FH_E_MAX

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "FHModelContract":
        _require_keys(
            value,
            required={"fit_hash", "input_track_ids"},
            optional={"valid_models", "seed", "thresholds", "arbitration", "e_max"},
            label="fh_model",
        )
        return cls(
            fit_hash=str(value["fit_hash"]),
            input_track_ids=tuple(int(item) for item in value["input_track_ids"]),
            valid_models=tuple(str(item) for item in value.get("valid_models", ("F", "H"))),
            seed=int(value.get("seed", FH_SEED)),
            thresholds=tuple(
                (str(item[0]), float(item[1]))
                for item in value.get("thresholds", FH_THRESHOLDS)
            ),
            arbitration=str(value.get("arbitration", "min_normalized_residual")),
            e_max=float(value.get("e_max", FH_E_MAX)),
        )

    def payload(self) -> dict[str, object]:
        return {
            "fit_hash": self.fit_hash,
            "input_track_ids": list(self.input_track_ids),
            "valid_models": list(self.valid_models),
            "seed": int(self.seed),
            "thresholds": [[name, _f64_token(value)] for name, value in self.thresholds],
            "arbitration": self.arbitration,
            "e_max": _f64_token(self.e_max),
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "fit_hash": self.fit_hash,
            "input_track_ids": list(self.input_track_ids),
            "valid_models": list(self.valid_models),
            "seed": int(self.seed),
            "thresholds": [[name, float(value)] for name, value in self.thresholds],
            "arbitration": self.arbitration,
            "e_max": float(self.e_max),
        }


@dataclass(frozen=True)
class NormalizedMasterEvent:
    sequence_id: str
    frame_index: int
    timestamp_s: float
    image_width: int
    image_height: int
    trigger_open: bool
    trigger_reason: str
    k0: tuple[NormalizedObservation, ...]
    base_export_ids: tuple[int, ...]
    learned_pool: tuple[NormalizedObservation, ...]
    classical_pool: tuple[NormalizedObservation, ...]
    fh_model: FHModelContract
    schema_version: str = SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "NormalizedMasterEvent":
        _require_keys(
            value,
            required={
                "sequence_id",
                "frame_index",
                "timestamp_s",
                "image_width",
                "image_height",
                "trigger_open",
                "trigger_reason",
                "k0",
                "base_export_ids",
                "learned_pool",
                "classical_pool",
                "fh_model",
            },
            optional={"schema_version"},
            label="master_event",
        )
        raw_fh = value["fh_model"]
        if not isinstance(raw_fh, Mapping):
            raise ContractViolation("fh_model must be an object")
        return cls(
            sequence_id=str(value["sequence_id"]),
            frame_index=int(value["frame_index"]),
            timestamp_s=float(value["timestamp_s"]),
            image_width=int(value["image_width"]),
            image_height=int(value["image_height"]),
            trigger_open=_strict_bool(value["trigger_open"], "trigger_open"),
            trigger_reason=str(value["trigger_reason"]),
            k0=_observation_tuple(value["k0"], "k0"),
            base_export_ids=tuple(int(item) for item in value["base_export_ids"]),
            learned_pool=_observation_tuple(value["learned_pool"], "learned_pool"),
            classical_pool=_observation_tuple(value["classical_pool"], "classical_pool"),
            fh_model=FHModelContract.from_mapping(raw_fh),
            schema_version=str(value.get("schema_version", SCHEMA_VERSION)),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "timestamp_s": float(self.timestamp_s),
            "image_width": int(self.image_width),
            "image_height": int(self.image_height),
            "trigger_open": bool(self.trigger_open),
            "trigger_reason": self.trigger_reason,
            "k0": [track.as_dict() for track in self.k0],
            "base_export_ids": list(self.base_export_ids),
            "learned_pool": [track.as_dict() for track in self.learned_pool],
            "classical_pool": [track.as_dict() for track in self.classical_pool],
            "fh_model": self.fh_model.as_dict(),
        }


@dataclass(frozen=True)
class NativeQObservation:
    track_id: int
    source: str
    quality_role: str
    q_backend: float
    sigma_scale: float

    def as_dict(self) -> dict[str, object]:
        return {
            "track_id": int(self.track_id),
            "source": self.source,
            "quality_role": self.quality_role,
            "q_backend": float(self.q_backend),
            "sigma_scale": float(self.sigma_scale),
        }


@dataclass(frozen=True)
class ArmFrameResult:
    arm_id: str
    sequence_id: str
    frame_index: int
    timestamp_s: float
    candidate_pool: str
    gate_reason: str
    gate_hash: str
    common_context_hash: str
    candidate_pool_hash: str
    live_supply_count: int
    eligible_supply_count: int
    admission_candidate_count: int
    available_slots: int
    active_before_ids: tuple[int, ...]
    selected_ids: tuple[int, ...]
    dropped_ids: tuple[int, ...]
    active_after_ids: tuple[int, ...]
    exported_ids: tuple[int, ...]
    native_q_vector: tuple[NativeQObservation, ...]
    native_q_vector_hash: str
    previous_arm_hash: str
    arm_frame_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "timestamp_s": float(self.timestamp_s),
            "candidate_pool": self.candidate_pool,
            "gate_reason": self.gate_reason,
            "gate_hash": self.gate_hash,
            "common_context_hash": self.common_context_hash,
            "candidate_pool_hash": self.candidate_pool_hash,
            "live_supply_count": int(self.live_supply_count),
            "eligible_supply_count": int(self.eligible_supply_count),
            "admission_candidate_count": int(self.admission_candidate_count),
            "available_slots": int(self.available_slots),
            "active_before_ids": list(self.active_before_ids),
            "selected_ids": list(self.selected_ids),
            "dropped_ids": list(self.dropped_ids),
            "active_after_ids": list(self.active_after_ids),
            "exported_ids": list(self.exported_ids),
            "native_q_vector": [item.as_dict() for item in self.native_q_vector],
            "native_q_vector_hash": self.native_q_vector_hash,
            "previous_arm_hash": self.previous_arm_hash,
            "arm_frame_hash": self.arm_frame_hash,
        }


@dataclass(frozen=True)
class ArmSummary:
    arm_id: str
    total_live_supply: int
    total_eligible_supply: int
    admitted_lineage_ids: tuple[int, ...]
    emitted_sidecar_observations: int
    status: str

    def as_dict(self) -> dict[str, object]:
        return {
            "arm_id": self.arm_id,
            "total_live_supply": int(self.total_live_supply),
            "total_eligible_supply": int(self.total_eligible_supply),
            "admitted_lineage_ids": list(self.admitted_lineage_ids),
            "emitted_sidecar_observations": int(self.emitted_sidecar_observations),
            "status": self.status,
        }


@dataclass(frozen=True)
class ReplayBundle:
    schema_version: str
    contract_hash: str
    b_active: int
    total_feature_cap: int
    gate_policy_hash: str
    native_q_mapper_hash: str
    outcome_boundary: str
    normalized_stream_hash: str
    source_attribution_status: str
    frames: tuple[ArmFrameResult, ...]
    summaries: tuple[ArmSummary, ...]
    bundle_hash: str

    def frames_for(self, arm_id: str) -> tuple[ArmFrameResult, ...]:
        return tuple(frame for frame in self.frames if frame.arm_id == arm_id)

    def summary_for(self, arm_id: str) -> ArmSummary:
        matches = [summary for summary in self.summaries if summary.arm_id == arm_id]
        if len(matches) != 1:
            raise KeyError(arm_id)
        return matches[0]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "contract_hash": self.contract_hash,
            "b_active": int(self.b_active),
            "total_feature_cap": int(self.total_feature_cap),
            "gate_policy_hash": self.gate_policy_hash,
            "native_q_mapper_hash": self.native_q_mapper_hash,
            "outcome_boundary": self.outcome_boundary,
            "normalized_stream_hash": self.normalized_stream_hash,
            "source_attribution_status": self.source_attribution_status,
            "frames": [frame.as_dict() for frame in self.frames],
            "summaries": [summary.as_dict() for summary in self.summaries],
            "bundle_hash": self.bundle_hash,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class ExactDropFrame:
    sequence_id: str
    frame_index: int
    source_arm_frame_hash: str
    dropped_lineage_ids: tuple[int, ...]
    exported_ids: tuple[int, ...]
    native_q_vector: tuple[NativeQObservation, ...]
    native_q_vector_hash: str
    frame_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "sequence_id": self.sequence_id,
            "frame_index": int(self.frame_index),
            "source_arm_frame_hash": self.source_arm_frame_hash,
            "dropped_lineage_ids": list(self.dropped_lineage_ids),
            "exported_ids": list(self.exported_ids),
            "native_q_vector": [item.as_dict() for item in self.native_q_vector],
            "native_q_vector_hash": self.native_q_vector_hash,
            "frame_hash": self.frame_hash,
        }


@dataclass(frozen=True)
class ExactDropBundle:
    schema_version: str
    source_bundle_hash: str
    dropped_lineage_ids: tuple[int, ...]
    frames: tuple[ExactDropFrame, ...]
    bundle_hash: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "source_bundle_hash": self.source_bundle_hash,
            "dropped_lineage_ids": list(self.dropped_lineage_ids),
            "frames": [frame.as_dict() for frame in self.frames],
            "bundle_hash": self.bundle_hash,
        }


class _PoolLifecycle:
    def __init__(self, label: str) -> None:
        self.label = label
        self.previous_live: set[int] | None = None
        self.retired: set[int] = set()

    def push(self, live_ids: set[int]) -> None:
        if self.retired & live_ids:
            raise ContractViolation(f"retired {self.label} lineage reappeared")
        if self.previous_live is not None:
            self.retired.update(self.previous_live - live_ids)
        self.previous_live = set(live_ids)


class _ArmState:
    def __init__(self, arm_id: str, candidate_pool: str, selector: str) -> None:
        self.arm_id = arm_id
        self.candidate_pool = candidate_pool
        self.selector = selector
        self.active: dict[int, NormalizedObservation] = {}
        self.admitted: set[int] = set()
        self.previous_hash = ""

    def replay(
        self,
        event: NormalizedMasterEvent,
        common_hash: str,
        pool_hash: str,
        gate_reason: str,
        gate_hash: str,
    ) -> ArmFrameResult:
        pool = event.learned_pool if self.candidate_pool == "learned" else event.classical_pool
        live_by_id = {track.track_id: track for track in pool}
        active_before_ids = tuple(sorted(self.active))
        dropped_ids = tuple(sorted(set(self.active) - set(live_by_id)))
        for track_id in dropped_ids:
            self.active.pop(track_id, None)
        for track_id in tuple(self.active):
            self.active[track_id] = live_by_id[track_id]

        if len(event.base_export_ids) + len(self.active) > TOTAL_FEATURE_CAP:
            raise ContractViolation(
                f"{self.arm_id} surviving active state exceeds total feature cap"
            )
        available_slots = min(
            B_ACTIVE - len(self.active),
            TOTAL_FEATURE_CAP - len(event.base_export_ids) - len(self.active),
        )
        available_slots = max(0, available_slots)
        eligible_supply = [track for track in pool if track.fh_eligible]
        admission_candidates = [
            track for track in eligible_supply if track.track_id not in self.admitted
        ]
        ordered = _candidate_order(event, admission_candidates, self.selector)
        selected = tuple(
            track.track_id for track in ordered[:available_slots]
        ) if gate_reason == "OPEN" else ()
        selected_by_id = {track.track_id: track for track in ordered if track.track_id in selected}
        for track_id in selected:
            self.active[track_id] = selected_by_id[track_id]
            self.admitted.add(track_id)

        active_after_ids = tuple(sorted(self.active))
        if len(active_after_ids) > B_ACTIVE:
            raise ContractViolation(f"{self.arm_id} exceeded B_active={B_ACTIVE}")
        exported_tracks = [
            track for track in event.k0 if track.track_id in set(event.base_export_ids)
        ] + list(self.active.values())
        q_vector = build_native_q_vector(exported_tracks)
        q_hash = native_q_vector_hash(q_vector, exported_tracks)
        exported_ids = tuple(item.track_id for item in q_vector)
        payload = {
            "schema_version": SCHEMA_VERSION,
            "contract_hash": REPLAY_CONTRACT_HASH,
            "arm_id": self.arm_id,
            "candidate_pool": self.candidate_pool,
            "selector": self.selector,
            "sequence_id": event.sequence_id,
            "frame_index": int(event.frame_index),
            "timestamp_s": _f64_token(event.timestamp_s),
            "common_context_hash": common_hash,
            "candidate_pool_hash": pool_hash,
            "gate_reason": gate_reason,
            "gate_hash": gate_hash,
            "previous_arm_hash": self.previous_hash,
            "b_active": B_ACTIVE,
            "total_feature_cap": TOTAL_FEATURE_CAP,
            "active_before_ids": list(active_before_ids),
            "selected_ids": list(selected),
            "dropped_ids": list(dropped_ids),
            "active_after_ids": list(active_after_ids),
            "exported_ids": list(exported_ids),
            "live_supply_count": len(pool),
            "eligible_supply_count": len(eligible_supply),
            "admission_candidate_count": len(admission_candidates),
            "native_q_vector_hash": q_hash,
        }
        frame_hash = _hash_payload(payload)
        result = ArmFrameResult(
            arm_id=self.arm_id,
            sequence_id=event.sequence_id,
            frame_index=event.frame_index,
            timestamp_s=event.timestamp_s,
            candidate_pool=self.candidate_pool,
            gate_reason=gate_reason,
            gate_hash=gate_hash,
            common_context_hash=common_hash,
            candidate_pool_hash=pool_hash,
            live_supply_count=len(pool),
            eligible_supply_count=len(eligible_supply),
            admission_candidate_count=len(admission_candidates),
            available_slots=available_slots,
            active_before_ids=active_before_ids,
            selected_ids=selected,
            dropped_ids=dropped_ids,
            active_after_ids=active_after_ids,
            exported_ids=exported_ids,
            native_q_vector=q_vector,
            native_q_vector_hash=q_hash,
            previous_arm_hash=self.previous_hash,
            arm_frame_hash=frame_hash,
        )
        self.previous_hash = frame_hash
        return result


def replay_master_events(
    records: Sequence[NormalizedMasterEvent | Mapping[str, object]],
) -> ReplayBundle:
    """Replay one sequence into P_legacy, C_legacy, and B2_all_eligible."""

    events = _canonical_events(records)

    learned_lifecycle = _PoolLifecycle("learned")
    classical_lifecycle = _PoolLifecycle("classical")
    states = (
        _ArmState(P_LEGACY, "learned", "distance_grid"),
        _ArmState(C_LEGACY, "classical", "distance_grid"),
        _ArmState(B2_ALL_ELIGIBLE, "learned", "all_eligible"),
    )
    frames: list[ArmFrameResult] = []
    stream_items: list[dict[str, object]] = []
    previous_frame = -1
    previous_timestamp = float("-inf")

    for event in events:
        _validate_event(event)
        if event.frame_index <= previous_frame:
            raise ContractViolation("frame_index must be strictly increasing")
        if event.timestamp_s <= previous_timestamp:
            raise ContractViolation("timestamp_s must be strictly increasing")
        previous_frame = event.frame_index
        previous_timestamp = event.timestamp_s

        learned_lifecycle.push({track.track_id for track in event.learned_pool})
        classical_lifecycle.push({track.track_id for track in event.classical_pool})
        common_hash = _common_context_hash(event)
        learned_hash = _candidate_pool_hash(event, "learned", common_hash)
        classical_hash = _candidate_pool_hash(event, "classical", common_hash)
        gate_reason, gate_hash = _shared_gate(event, common_hash)
        stream_items.append(
            {
                "common_context_hash": common_hash,
                "learned_pool_hash": learned_hash,
                "classical_pool_hash": classical_hash,
            }
        )
        for state in states:
            frames.append(
                state.replay(
                    event,
                    common_hash,
                    learned_hash if state.candidate_pool == "learned" else classical_hash,
                    gate_reason,
                    gate_hash,
                )
            )

    frames_tuple = tuple(frames)
    summaries = tuple(_summarize_arm(frames_tuple, arm_id) for arm_id in ARM_IDS)
    p_summary = next(item for item in summaries if item.arm_id == P_LEGACY)
    c_summary = next(item for item in summaries if item.arm_id == C_LEGACY)
    if not p_summary.admitted_lineage_ids:
        attribution_status = "NOT_APPLICABLE_PROPOSED_ZERO_ACTION"
    elif c_summary.total_live_supply == 0:
        attribution_status = "H2_INELIGIBLE_SUPPLY_ZERO"
    elif not c_summary.admitted_lineage_ids:
        attribution_status = "H2_INELIGIBLE_ADMISSION_ZERO"
    else:
        attribution_status = "APPLICABLE"
    stream_hash = _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "contract_hash": REPLAY_CONTRACT_HASH,
            "events": stream_items,
        }
    )
    bundle_payload = {
        "schema_version": SCHEMA_VERSION,
        "contract_hash": REPLAY_CONTRACT_HASH,
        "b_active": B_ACTIVE,
        "total_feature_cap": TOTAL_FEATURE_CAP,
        "gate_policy_hash": GATE_POLICY_HASH,
        "native_q_mapper_hash": NATIVE_Q_MAPPER_HASH,
        "outcome_boundary": OUTCOME_BOUNDARY,
        "normalized_stream_hash": stream_hash,
        "source_attribution_status": attribution_status,
        "frame_hashes": [frame.arm_frame_hash for frame in frames_tuple],
        "summaries": [summary.as_dict() for summary in summaries],
    }
    return ReplayBundle(
        schema_version=SCHEMA_VERSION,
        contract_hash=REPLAY_CONTRACT_HASH,
        b_active=B_ACTIVE,
        total_feature_cap=TOTAL_FEATURE_CAP,
        gate_policy_hash=GATE_POLICY_HASH,
        native_q_mapper_hash=NATIVE_Q_MAPPER_HASH,
        outcome_boundary=OUTCOME_BOUNDARY,
        normalized_stream_hash=stream_hash,
        source_attribution_status=attribution_status,
        frames=frames_tuple,
        summaries=summaries,
        bundle_hash=_hash_payload(bundle_payload),
    )


def normalized_event_digest(
    record: NormalizedMasterEvent | Mapping[str, object],
) -> str:
    """Return a deterministic digest of one normalized event, excluding outcomes."""

    event = record if isinstance(record, NormalizedMasterEvent) else NormalizedMasterEvent.from_mapping(record)
    _validate_event(event)
    common_hash = _common_context_hash(event)
    return _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "common_context_hash": common_hash,
            "learned_pool_hash": _candidate_pool_hash(event, "learned", common_hash),
            "classical_pool_hash": _candidate_pool_hash(event, "classical", common_hash),
        }
    )


def normalized_stream_digest(
    records: Sequence[NormalizedMasterEvent | Mapping[str, object]],
) -> str:
    """Return the canonical stream digest without replaying any arm."""

    events = _canonical_events(records)
    items = []
    for event in events:
        common_hash = _common_context_hash(event)
        items.append(
            {
                "common_context_hash": common_hash,
                "learned_pool_hash": _candidate_pool_hash(event, "learned", common_hash),
                "classical_pool_hash": _candidate_pool_hash(event, "classical", common_hash),
            }
        )
    return _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "contract_hash": REPLAY_CONTRACT_HASH,
            "events": items,
        }
    )


def native_q_for_observation(
    track: NormalizedObservation,
    *,
    quality_role: str | None = None,
) -> float:
    """Return native q using a provenance-independent quality role.

    ``klt_backbone`` is used for K0. Every learned/classical candidate uses
    ``candidate_sidecar``; source names never choose a different q branch.
    """

    _validate_observation(track, None, None, "native_q")
    source = _canonical_source(track.source)
    role = quality_role or (
        QUALITY_ROLE_KLT if source == "klt" else QUALITY_ROLE_SIDECAR
    )
    if role not in {QUALITY_ROLE_KLT, QUALITY_ROLE_SIDECAR}:
        raise ContractViolation(f"unsupported native-q quality role: {role}")
    expected_role = QUALITY_ROLE_KLT if source == "klt" else QUALITY_ROLE_SIDECAR
    if role != expected_role:
        raise ContractViolation(
            f"quality role {role} is incompatible with source provenance {track.source}"
        )
    raw_q = _f32(min(1.0, max(0.05, _f32(track.raw_quality))))
    age = _f32(max(0.0, _f32(track.age)))
    age_ratio = _f32(min(1.0, max(0.0, _f32(age / _f32(8.0)))))
    age_gain = _f32(_f32(0.70) + _f32(_f32(0.30) * age_ratio))
    fb = _f32(max(0.0, _f32(track.fb_error)))
    fb_exp = _f32(math.exp(-float(fb) / 3.0))
    fb_gain = _f32(min(1.0, max(0.65, _f32(_f32(0.65) + _f32(_f32(0.35) * fb_exp)))))
    ncc = _f32(min(1.0, max(0.0, _f32(_f32(_f32(track.ncc) + _f32(1.0)) * _f32(0.5)))))
    ncc_gain = _f32(min(1.0, max(0.75, _f32(_f32(0.75) + _f32(_f32(0.25) * ncc)))))
    source_gain = _f32(1.00 if role == QUALITY_ROLE_KLT else 0.84)
    quality_gain = _f32(_f32(0.85) + _f32(_f32(0.15) * raw_q))
    default = _f32(source_gain * age_gain)
    default = _f32(default * fb_gain)
    default = _f32(default * ncc_gain)
    default = _f32(default * quality_gain)
    blended = _f32(_f32(NATIVE_Q_ALPHA) + _f32(_f32(1.0 - NATIVE_Q_ALPHA) * raw_q))
    age_boost = min(float(track.age), 6.0) / 6.0

    if role == QUALITY_ROLE_KLT:
        value = min(1.0, max(0.42, float(default)))
    else:
        # The sidecar branch intentionally ignores proposer provenance. The
        # age-based confirmation schedule is shared by learned and classical
        # candidates, making C_legacy a proposer-only attribution control.
        confirmed = track.age >= 3
        floor = 0.78 if confirmed else 0.70
        ceiling = 0.92 if confirmed else 0.86
        value = min(ceiling, max(floor, 0.68 + 0.20 * float(blended) + 0.06 * age_boost))
    value = _f32(min(1.0, max(0.35, value)))
    return _f32(min(1.0, max(NATIVE_Q_FLOOR, value)))


def build_native_q_vector(
    tracks: Sequence[NormalizedObservation],
) -> tuple[NativeQObservation, ...]:
    ordered = tuple(sorted(tracks, key=lambda track: int(track.track_id)))
    if len({track.track_id for track in ordered}) != len(ordered):
        raise ContractViolation("native-q vector contains duplicate track IDs")
    result = []
    for track in ordered:
        quality_role = (
            QUALITY_ROLE_KLT
            if _canonical_source(track.source) == "klt"
            else QUALITY_ROLE_SIDECAR
        )
        q_backend = native_q_for_observation(track, quality_role=quality_role)
        result.append(
            NativeQObservation(
                track_id=track.track_id,
                source=_canonical_source(track.source),
                quality_role=quality_role,
                q_backend=q_backend,
                sigma_scale=1.0 / math.sqrt(max(0.05, q_backend)),
            )
        )
    return tuple(result)


def native_q_vector_hash(
    vector: Sequence[NativeQObservation],
    source_tracks: Sequence[NormalizedObservation],
) -> str:
    by_id = {track.track_id: track for track in source_tracks}
    payload_rows = []
    for item in vector:
        track = by_id.get(item.track_id)
        if track is None:
            raise ContractViolation("native-q vector is missing source evidence")
        payload_rows.append(
            {
                "track_id": int(item.track_id),
                "source": item.source,
                "quality_role": item.quality_role,
                "raw_quality": _f64_token(track.raw_quality),
                "age": int(track.age),
                "ncc": _f64_token(track.ncc),
                "fb_error": _f64_token(track.fb_error),
                "q_backend_f32": _f32_token(item.q_backend),
                "sigma_scale": _f64_token(item.sigma_scale),
            }
        )
    return _hash_payload(
        {
            "mapper_hash": NATIVE_Q_MAPPER_HASH,
            "observations": payload_rows,
        }
    )


def derive_exact_lineage_drop(
    bundle: ReplayBundle,
    lineage_ids: Iterable[int] | None = None,
) -> ExactDropBundle:
    """Derive D_legacy by removing whole P_legacy lineages on every frame."""

    p_frames = bundle.frames_for(P_LEGACY)
    available = {track_id for frame in p_frames for track_id in frame.active_after_ids}
    dropped = tuple(sorted(available if lineage_ids is None else {int(item) for item in lineage_ids}))
    if set(dropped) - available:
        raise ContractViolation("exact-drop IDs must be admitted P_legacy lineages")
    drop_set = set(dropped)
    output_frames: list[ExactDropFrame] = []
    for frame in p_frames:
        vector = tuple(item for item in frame.native_q_vector if item.track_id not in drop_set)
        exported_ids = tuple(item.track_id for item in vector)
        q_hash = _hash_payload(
            {
                "schema_version": DROP_SCHEMA_VERSION,
                "source_q_hash": frame.native_q_vector_hash,
                "drop_ids": list(dropped),
                "remaining": [
                    [
                        item.track_id,
                        item.source,
                        item.quality_role,
                        _f32_token(item.q_backend),
                    ]
                    for item in vector
                ],
            }
        )
        frame_payload = {
            "schema_version": DROP_SCHEMA_VERSION,
            "source_arm_frame_hash": frame.arm_frame_hash,
            "drop_ids": list(dropped),
            "exported_ids": list(exported_ids),
            "native_q_vector_hash": q_hash,
        }
        output_frames.append(
            ExactDropFrame(
                sequence_id=frame.sequence_id,
                frame_index=frame.frame_index,
                source_arm_frame_hash=frame.arm_frame_hash,
                dropped_lineage_ids=dropped,
                exported_ids=exported_ids,
                native_q_vector=vector,
                native_q_vector_hash=q_hash,
                frame_hash=_hash_payload(frame_payload),
            )
        )
    frames_tuple = tuple(output_frames)
    payload = {
        "schema_version": DROP_SCHEMA_VERSION,
        "source_bundle_hash": bundle.bundle_hash,
        "drop_ids": list(dropped),
        "frame_hashes": [frame.frame_hash for frame in frames_tuple],
    }
    return ExactDropBundle(
        schema_version=DROP_SCHEMA_VERSION,
        source_bundle_hash=bundle.bundle_hash,
        dropped_lineage_ids=dropped,
        frames=frames_tuple,
        bundle_hash=_hash_payload(payload),
    )


def _canonical_events(
    records: Sequence[NormalizedMasterEvent | Mapping[str, object]],
) -> tuple[NormalizedMasterEvent, ...]:
    if len(records) == 0:
        raise ContractViolation("at least one master event is required")
    if len(records) > MAX_EVENTS:
        raise ContractViolation(f"event count exceeds bounded limit {MAX_EVENTS}")
    normalized = [
        record
        if isinstance(record, NormalizedMasterEvent)
        else NormalizedMasterEvent.from_mapping(record)
        for record in records
    ]
    events = tuple(
        event
        for _position, event in sorted(
            enumerate(normalized),
            key=lambda item: (
                item[1].sequence_id,
                int(item[1].frame_index),
                float(item[1].timestamp_s),
                item[0],
            ),
        )
    )
    if len({event.sequence_id for event in events}) != 1:
        raise ContractViolation("one replay invocation must contain exactly one sequence")
    previous_frame = -1
    previous_timestamp = float("-inf")
    for event in events:
        _validate_event(event)
        if event.frame_index <= previous_frame:
            raise ContractViolation("frame_index must be strictly increasing")
        if event.timestamp_s <= previous_timestamp:
            raise ContractViolation("timestamp_s must be strictly increasing")
        previous_frame = event.frame_index
        previous_timestamp = event.timestamp_s
    return events


def _validate_event(event: NormalizedMasterEvent) -> None:
    if event.schema_version != SCHEMA_VERSION:
        raise ContractViolation(f"unsupported master-event schema: {event.schema_version}")
    if not event.sequence_id:
        raise ContractViolation("sequence_id is required")
    if event.frame_index < 0 or not math.isfinite(event.timestamp_s):
        raise ContractViolation("frame index and timestamp are invalid")
    if event.image_width <= 0 or event.image_height <= 0:
        raise ContractViolation("image dimensions must be positive")
    if not event.trigger_reason:
        raise ContractViolation("trigger_reason is required")
    if (
        len(event.k0) > MAX_POOL_TRACKS
        or len(event.learned_pool) > MAX_POOL_TRACKS
        or len(event.classical_pool) > MAX_POOL_TRACKS
    ):
        raise ContractViolation(f"event pool exceeds bounded limit {MAX_POOL_TRACKS}")
    _validate_hash(event.fh_model.fit_hash, "F/H fit hash")
    if event.fh_model.seed != FH_SEED:
        raise ContractViolation(f"F/H seed must be {FH_SEED}")
    if tuple(event.fh_model.thresholds) != FH_THRESHOLDS:
        raise ContractViolation("F/H thresholds drift")
    if event.fh_model.arbitration != "min_normalized_residual":
        raise ContractViolation("F/H arbitration drift")
    if abs(float(event.fh_model.e_max) - FH_E_MAX) > 1e-12:
        raise ContractViolation("F/H e_max drift")
    if any(model not in {"F", "H"} for model in event.fh_model.valid_models):
        raise ContractViolation("only F/H models are allowed")
    if event.fh_model.valid_models != tuple(sorted(set(event.fh_model.valid_models))):
        raise ContractViolation("F/H valid_models must be unique and canonical")

    k0 = _validated_pool(event.k0, event, _KLT_SOURCES, "K0")
    learned = _validated_pool(event.learned_pool, event, _LEARNED_SOURCES, "learned")
    classical = _validated_pool(event.classical_pool, event, _CLASSICAL_SOURCES, "classical")
    all_ids = list(k0) + list(learned) + list(classical)
    if len(all_ids) != len(set(all_ids)):
        raise ContractViolation("K0, learned, and classical IDs must be mutually disjoint")
    base_ids = tuple(sorted(int(item) for item in event.base_export_ids))
    if len(base_ids) != len(set(base_ids)) or not set(base_ids) <= set(k0):
        raise ContractViolation("base_export_ids must be a unique subset of K0")
    if len(base_ids) > TOTAL_FEATURE_CAP:
        raise ContractViolation("base export exceeds total feature cap")
    if tuple(event.fh_model.input_track_ids) != tuple(sorted(k0)):
        raise ContractViolation("F/H input IDs must equal canonical K0 IDs")
    if event.fh_model.valid_models and not k0:
        raise ContractViolation("a valid F/H model requires non-empty K0")
    if not event.fh_model.valid_models and any(
        track.fh_eligible for track in event.learned_pool + event.classical_pool
    ):
        raise ContractViolation("no valid F/H model must reject all candidates")


def _validated_pool(
    tracks: Sequence[NormalizedObservation],
    event: NormalizedMasterEvent,
    allowed_sources: frozenset[str],
    label: str,
) -> dict[int, NormalizedObservation]:
    by_id: dict[int, NormalizedObservation] = {}
    for track in tracks:
        _validate_observation(track, event.image_width, event.image_height, label)
        if str(track.source).lower() not in allowed_sources:
            raise ContractViolation(f"{label} contains unsupported source {track.source}")
        if track.track_id in by_id:
            raise ContractViolation(f"{label} contains duplicate track IDs")
        by_id[track.track_id] = track
    return by_id


def _validate_observation(
    track: NormalizedObservation,
    width: int | None,
    height: int | None,
    label: str,
) -> None:
    if not 0 <= int(track.track_id) < MAX_EXACT_FLOAT32_ID:
        raise ContractViolation(f"{label} track ID is outside exact float32 range")
    values = (track.u, track.v, track.raw_quality, track.ncc, track.fb_error, track.normalized_residual)
    if any(not math.isfinite(float(value)) for value in values):
        raise ContractViolation(f"{label} contains non-finite evidence")
    if width is not None and height is not None and not (0.0 <= track.u < width and 0.0 <= track.v < height):
        raise ContractViolation(f"{label} coordinate is outside the image")
    if not 0.0 <= track.raw_quality <= 1.0:
        raise ContractViolation(f"{label} raw_quality must be in [0,1]")
    if track.age < 0 or track.age > MAX_TRACK_AGE or track.fb_error < 0.0:
        raise ContractViolation(f"{label} age/fb_error is outside the bounded range")
    if not -1.0 <= track.ncc <= 1.0:
        raise ContractViolation(f"{label} ncc must be in [-1,1]")
    if not 0.0 <= track.normalized_residual <= FH_E_MAX:
        raise ContractViolation(f"{label} normalized residual must be in [0,{FH_E_MAX}]")
    _canonical_source(track.source)


def _common_context_hash(event: NormalizedMasterEvent) -> str:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "sequence_id": event.sequence_id,
        "frame_index": int(event.frame_index),
        "timestamp_s": _f64_token(event.timestamp_s),
        "image_shape": [event.image_width, event.image_height],
        "trigger_open": bool(event.trigger_open),
        "trigger_reason": event.trigger_reason,
        "k0": [track.payload() for track in sorted(event.k0, key=lambda item: item.track_id)],
        "base_export_ids": sorted(event.base_export_ids),
        "fh_model": event.fh_model.payload(),
        "gate_policy_hash": GATE_POLICY_HASH,
    }
    return _hash_payload(payload)


def _candidate_pool_hash(
    event: NormalizedMasterEvent, candidate_pool: str, common_hash: str
) -> str:
    tracks = event.learned_pool if candidate_pool == "learned" else event.classical_pool
    return _hash_payload(
        {
            "schema_version": SCHEMA_VERSION,
            "candidate_pool": candidate_pool,
            "common_context_hash": common_hash,
            "tracks": [track.payload() for track in sorted(tracks, key=lambda item: item.track_id)],
        }
    )


def _shared_gate(event: NormalizedMasterEvent, common_hash: str) -> tuple[str, str]:
    if not event.trigger_open:
        reason = "TRIGGER_CLOSED"
    elif not event.fh_model.valid_models:
        reason = "NO_VALID_FH_MODEL"
    else:
        reason = "OPEN"
    gate_hash = _hash_payload(
        {
            "gate_policy_hash": GATE_POLICY_HASH,
            "common_context_hash": common_hash,
            "reason": reason,
        }
    )
    return reason, gate_hash


def _candidate_order(
    event: NormalizedMasterEvent,
    candidates: Sequence[NormalizedObservation],
    selector: str,
) -> tuple[NormalizedObservation, ...]:
    if selector == "all_eligible":
        return tuple(sorted(candidates, key=lambda track: int(track.track_id)))
    if selector != "distance_grid":
        raise ContractViolation(f"unsupported selector: {selector}")
    occupied = {
        _grid_cell(track, event.image_width, event.image_height) for track in event.k0
    }

    def key(track: NormalizedObservation) -> tuple[int, float, int]:
        cell_priority = 0 if _grid_cell(track, event.image_width, event.image_height) not in occupied else 1
        nearest = min(
            (
                math.hypot(track.u - base.u, track.v - base.v)
                for base in event.k0
            ),
            default=0.0,
        )
        return cell_priority, -nearest, int(track.track_id)

    return tuple(sorted(candidates, key=key))


def _grid_cell(track: NormalizedObservation, width: int, height: int) -> tuple[int, int]:
    row = min(GRID_ROWS - 1, max(0, int(track.v / height * GRID_ROWS)))
    col = min(GRID_COLS - 1, max(0, int(track.u / width * GRID_COLS)))
    return row, col


def _summarize_arm(frames: Sequence[ArmFrameResult], arm_id: str) -> ArmSummary:
    selected_frames = [frame for frame in frames if frame.arm_id == arm_id]
    admitted = tuple(sorted({track_id for frame in selected_frames for track_id in frame.selected_ids}))
    live_supply = sum(frame.live_supply_count for frame in selected_frames)
    eligible_supply = sum(frame.eligible_supply_count for frame in selected_frames)
    emitted = sum(len(frame.active_after_ids) for frame in selected_frames)
    if admitted:
        status = "ACTIVE"
    elif arm_id == C_LEGACY and live_supply == 0:
        status = "ZERO_ACTION_NO_CLASSICAL_SUPPLY"
    elif arm_id == C_LEGACY and eligible_supply == 0:
        status = "ZERO_ACTION_NO_ELIGIBLE_CLASSICAL_SUPPLY"
    else:
        status = "ZERO_ACTION"
    return ArmSummary(
        arm_id=arm_id,
        total_live_supply=live_supply,
        total_eligible_supply=eligible_supply,
        admitted_lineage_ids=admitted,
        emitted_sidecar_observations=emitted,
        status=status,
    )


def _canonical_source(source: str) -> str:
    name = str(source).lower()
    aliases = {
        "klt_base": "klt",
        "classical_gftt": "gftt",
        "classical_gftt_confirmed": "gftt_confirmed",
        "learned_xfeat": "xfeat",
        "learned_xfeat_confirmed": "xfeat_confirmed",
    }
    canonical = aliases.get(name, name)
    if canonical not in {
        "klt",
        "gftt",
        "gftt_seed",
        "gftt_confirmed",
        "xfeat",
        "xfeat_confirmed",
    }:
        raise ContractViolation(f"unsupported normalized source: {source}")
    return canonical


def _validate_hash(value: str, label: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractViolation(f"{label} must be a lowercase SHA-256 digest")


def _observation_tuple(value: object, label: str) -> tuple[NormalizedObservation, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractViolation(f"{label} must be an array")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ContractViolation(f"{label} entries must be objects")
        result.append(NormalizedObservation.from_mapping(item))
    return tuple(result)


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
        raise ContractViolation(f"{label} missing fields: {sorted(missing)}")
    if unknown:
        raise ContractViolation(
            f"{label} contains unsupported/outcome fields: {sorted(unknown)}"
        )


def _strict_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ContractViolation(f"{label} must be a JSON boolean")
    return value


__all__ = [
    "ARM_IDS",
    "B2_ALL_ELIGIBLE",
    "B_ACTIVE",
    "C_LEGACY",
    "ContractViolation",
    "DROP_SCHEMA_VERSION",
    "ExactDropBundle",
    "FHModelContract",
    "GATE_POLICY_HASH",
    "MAX_TRACK_AGE",
    "NATIVE_Q_MAPPER_HASH",
    "OUTCOME_BOUNDARY",
    "QUALITY_ROLE_KLT",
    "QUALITY_ROLE_SIDECAR",
    "NormalizedMasterEvent",
    "NormalizedObservation",
    "P_LEGACY",
    "REPLAY_CONTRACT_HASH",
    "ReplayBundle",
    "SCHEMA_VERSION",
    "TOTAL_FEATURE_CAP",
    "build_native_q_vector",
    "derive_exact_lineage_drop",
    "native_q_for_observation",
    "native_q_vector_hash",
    "normalized_event_digest",
    "normalized_stream_digest",
    "replay_master_events",
]
