#!/usr/bin/env python3
"""Export a selector-independent P03 master candidate stream on development data.

The producer is an export-only tool.  It runs one immutable KLT mirror, an
independent GFTT pool, and optionally XFeat proposals.  It never consumes a
VINS trajectory or an arm admission decision.  H/P selectors are expected to
replay the resulting JSONL independently.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import yaml

from uw_frontend.datasets.image_sequence import ImageSequence
from uw_frontend.evaluation.run_frontend_eval import _preprocess_gray
from uw_frontend.geometry.fh_residuals import FHConfig, FHFitResult, classify_correspondences, fit_base_models
from uw_frontend.geometry.grid import grid_stats
from uw_frontend.geometry.master_candidate_stream import (
    MasterEvent,
    TrackEvidence,
    build_master_event,
)
from uw_frontend.matchers.xfeat_adapter import XFeatMatcher
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.quality.temporal_reliability import (
    PooledReliabilityModel,
    TemporalSnapshot,
    build_calibration_rows,
    selector_features,
    write_calibration_rows,
)
from uw_frontend.tracking.classical_proposer import (
    ClassicalProposerConfig,
    GFTTClassicalProposer,
)
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker, _in_border, _patch_ncc


DEFAULT_CONFIG = ROOT / "uw_frontend/configs/isj_p03_core_method_candidate.yaml"


@dataclass
class _CandidateState:
    lineage_id: int
    source: str
    point: np.ndarray
    birth_frame: int
    age: int = 1
    survival_count: int = 1
    fb_error: float = 0.0
    ncc: float = 1.0
    residual_history: list[float] | None = None
    motion_ratios: list[float] | None = None
    correctness_failures: int = 0

    def __post_init__(self) -> None:
        if self.residual_history is None:
            self.residual_history = []
        if self.motion_ratios is None:
            self.motion_ratios = []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--sequence-id", required=True)
    parser.add_argument("--output-jsonl", required=True)
    parser.add_argument("--output-calibration-csv", required=True)
    parser.add_argument("--output-metrics-csv", required=True)
    parser.add_argument("--split", choices=["train", "calibration"], default="train")
    parser.add_argument("--geometry-stratum", default="development")
    parser.add_argument("--image-prefix")
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int)
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--input-rate-hz", type=float, default=20.0)
    parser.add_argument(
        "--timestamps-csv",
        help="Optional frame_index,timestamp CSV produced by a bag image extractor.",
    )
    parser.add_argument("--proposal-mode", choices=["all", "classical_only", "none"], default="all")
    parser.add_argument("--reliability-model")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    args = parser.parse_args()

    config_path = Path(args.config)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    config_hash = _sha256_file(config_path)
    model = PooledReliabilityModel.from_json(args.reliability_model) if args.reliability_model else None
    timestamps = _load_timestamps(args.timestamps_csv) if args.timestamps_csv else {}
    output_jsonl = Path(args.output_jsonl)
    output_calibration = Path(args.output_calibration_csv)
    output_metrics = Path(args.output_metrics_csv)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    output_calibration.parent.mkdir(parents=True, exist_ok=True)
    output_metrics.parent.mkdir(parents=True, exist_ok=True)

    klt_cfg = KltConfig(**_klt_config(config))
    klt = KltTracker(klt_cfg)
    classical = GFTTClassicalProposer(
        ClassicalProposerConfig(**_classical_config(config))
    )
    xfeat = None
    if args.proposal_mode == "all":
        xfeat_cfg = config.get("learned_proposer", {})
        xfeat = XFeatMatcher(
            repo_path=xfeat_cfg.get("repository", "external_tools/accelerated_features"),
            top_k=int(xfeat_cfg.get("top_k", 2048)),
            semi_dense=bool(xfeat_cfg.get("semi_dense", False)),
            min_cossim=float(xfeat_cfg.get("min_cossim", 0.82)),
        )

    fh_cfg = FHConfig(**_fh_config(config))
    trigger_cfg = config.get("health_trigger", {})
    probation_cfg = config.get("probation_and_carrier", {})
    selector_cfg = config.get("selector", {})
    b_active = int(selector_cfg.get("b_active", 8))
    base_export_cap = int(selector_cfg.get("base_export_cap", 342))
    total_feature_cap = int(selector_cfg.get("total_feature_cap", 350))

    learned_states: dict[int, _CandidateState] = {}
    classical_states: dict[int, _CandidateState] = {}
    learned_next_id = 10_000_000
    k0_histories: dict[int, list[float]] = {}
    snapshots: list[TemporalSnapshot] = []
    previous_gray: np.ndarray | None = None
    previous_master_hash = ""
    last_trigger_frame = -10_000_000
    bad_history: list[bool] = []
    events: list[MasterEvent] = []
    metrics_rows: list[dict[str, object]] = []

    sequence = ImageSequence(
        args.input,
        image_prefix=args.image_prefix,
        start_index=args.start_index,
        end_index=args.end_index,
        max_frames=args.max_frames,
    )
    with output_jsonl.open("w", encoding="utf-8") as event_handle:
        for emitted, frame in enumerate(sequence):
            raw = frame.image
            gray = _preprocess_gray(raw, "adaptive_clahe")
            quality = score_image_quality(raw)
            k0_tracks, diagnostics = klt.process(gray, score_image_quality(gray))
            image_shape = (int(gray.shape[1]), int(gray.shape[0]))
            grid = grid_stats(k0_tracks.points, gray.shape, rows=4, cols=6)
            median_fb = float(np.median(k0_tracks.fb_errors)) if len(k0_tracks) else float("inf")
            long_ratio = float(np.mean(k0_tracks.ages >= 10)) if len(k0_tracks) else 0.0
            instant_bad = bool(
                len(k0_tracks) < int(trigger_cfg.get("min_k0_tracks", 260))
                or grid.coverage < float(trigger_cfg.get("min_grid_coverage", 0.80))
                or median_fb > float(trigger_cfg.get("max_median_fb_error", 0.65))
                or quality.degradation_score >= float(trigger_cfg.get("min_image_degradation", 0.40))
            )
            bad_history.append(bool(long_ratio < float(trigger_cfg.get("max_long_track_ratio", 0.30))))
            bad_history = bad_history[-int(trigger_cfg.get("rolling_window_frames", 3)) :]
            rolling_bad = sum(bad_history) >= int(trigger_cfg.get("rolling_min_bad_frames", 2))
            trigger = bool(
                emitted >= int(trigger_cfg.get("warmup_frames", 8))
                and (instant_bad or rolling_bad)
                and emitted - last_trigger_frame >= int(trigger_cfg.get("minimum_trigger_gap_frames", 3))
            )
            fit = _fit_k0(k0_tracks, fh_cfg)
            k0_evidence = _make_k0_evidence(
                k0_tracks,
                fit,
                k0_histories,
                image_shape,
                model,
                fh_cfg,
            )
            _record_k0_snapshots(
                snapshots,
                args.sequence_id,
                args.geometry_stratum,
                frame.index,
                k0_tracks,
                k0_evidence,
                fit,
                fh_cfg,
            )
            _append_k0_histories(k0_tracks, fit, k0_histories, fh_cfg)

            base_motion = _median_motion(k0_tracks)
            learned_eligible, learned_alive, learned_live = _advance_pool(
                learned_states,
                previous_gray,
                gray,
                frame.index,
                fit,
                fh_cfg,
                probation_cfg,
                base_motion,
                args.sequence_id,
                args.geometry_stratum,
                snapshots,
                model,
                source_group="learned",
                image_shape=image_shape,
            )
            classical_eligible, classical_alive, classical_live = _advance_pool(
                classical_states,
                previous_gray,
                gray,
                frame.index,
                fit,
                fh_cfg,
                probation_cfg,
                base_motion,
                args.sequence_id,
                args.geometry_stratum,
                snapshots,
                model,
                source_group="classical",
                image_shape=image_shape,
            )

            learned_added = 0
            classical_added = 0
            if trigger:
                last_trigger_frame = emitted
                # Keep proposal pools independent. A classical pool may only
                # be masked by immutable K0 and its own live classical tracks;
                # learned proposals use the analogous learned-only mask.
                # Cross-source masking would make C-QG depend on P's learned
                # proposal realization and invalidate master pairing.
                k0_points = (
                    k0_tracks.points
                    if len(k0_tracks)
                    else np.empty((0, 2), dtype=np.float32)
                )
                classical_blocked = np.vstack(
                    [k0_points]
                    + [
                        state.point.reshape(1, 2)
                        for state in classical_states.values()
                    ]
                )
                learned_blocked = np.vstack(
                    [k0_points]
                    + [
                        state.point.reshape(1, 2)
                        for state in learned_states.values()
                    ]
                )
                proposals = classical.propose(
                    gray,
                    trigger_frame=frame.index,
                    exclusion_points=classical_blocked,
                )
                for proposal in proposals:
                    if proposal.lineage_id in classical_states:
                        continue
                    classical_states[proposal.lineage_id] = _CandidateState(
                        lineage_id=proposal.lineage_id,
                        source="classical_gftt",
                        point=np.asarray([proposal.u, proposal.v], dtype=np.float32),
                        birth_frame=frame.index,
                    )
                    classical_added += 1
                if xfeat is not None and previous_gray is not None:
                    learned_added, learned_next_id = _add_xfeat_states(
                        learned_states,
                        xfeat,
                        previous_gray,
                        gray,
                        frame.index,
                        learned_blocked,
                        learned_next_id,
                    )

            event = build_master_event(
                sequence_id=args.sequence_id,
                frame_index=frame.index,
                timestamp_s=(
                    float(timestamps.get(frame.index, frame.timestamp))
                    if frame.index in timestamps or frame.timestamp is not None
                    else float(frame.index) / float(args.input_rate_hz)
                ),
                image_shape=image_shape,
                trigger_reason=(
                    "KLT_HEALTH_TRIGGER" if trigger else "NO_TRIGGER"
                ),
                k0=k0_evidence,
                eligible_learned=learned_eligible,
                eligible_classical=classical_eligible,
                live_learned=learned_live,
                live_classical=classical_live,
                base_export_ids=_base_export_ids(k0_evidence, base_export_cap),
                model_fit=fit.evidence,
                config_hash=config_hash,
                previous_master_hash=previous_master_hash,
            )
            event_handle.write(json.dumps(event.as_dict(), sort_keys=True) + "\n")
            events.append(event)
            previous_master_hash = event.master_pool_hash
            metrics_rows.append(
                {
                    "frame_index": frame.index,
                    "timestamp_s": event.timestamp_s,
                    "trigger": int(trigger),
                    "trigger_reason": event.trigger_reason,
                    "k0_count": len(k0_evidence),
                    "k0_grid_coverage": grid.coverage,
                    "k0_median_fb": median_fb,
                    "degradation_score": quality.degradation_score,
                    "valid_models": ";".join(fit.evidence.valid_models),
                    "learned_eligible": len(learned_eligible),
                    "classical_eligible": len(classical_eligible),
                    "learned_added": learned_added,
                    "classical_added": classical_added,
                    "learned_alive": learned_alive,
                    "classical_alive": classical_alive,
                    "master_pool_hash": event.master_pool_hash,
                    "classical_pool_hash": event.classical_pool_hash,
                }
            )
            previous_gray = gray.copy()

    _write_metrics(output_metrics, metrics_rows)
    if snapshots:
        rows = build_calibration_rows(
            snapshots,
            sequence_splits={args.sequence_id: args.split},
            sequence_end_frames={args.sequence_id: events[-1].frame_index if events else 0},
            horizon_frames=5,
        )
        write_calibration_rows(output_calibration, rows)
    else:
        _write_empty_calibration(output_calibration)
    summary = {
        "schema_version": "isj-master-producer-v1",
        "sequence_id": args.sequence_id,
        "frames": len(events),
        "trigger_frames": sum(int(row["trigger"]) for row in metrics_rows),
        "learned_lineages": len({track.track_id for event in events for track in event.eligible_learned}),
        "classical_lineages": len({track.track_id for event in events for track in event.eligible_classical}),
        "master_final_hash": events[-1].master_pool_hash if events else "",
        "config_hash": config_hash,
        "reliability_model_hash": model.model_hash if model else "PROVISIONAL_Q_ONE",
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


def _klt_config(config: dict) -> dict:
    source = dict(config.get("b1_klt", {}))
    return {
        key: source[key]
        for key in (
            "max_features",
            "min_distance",
            "quality_level",
            "block_size",
            "lk_win_size",
            "lk_max_level",
            "fb_threshold",
            "min_ncc",
            "patch_radius",
            "border",
        )
        if key in source
    } or {
        "max_features": 350,
        "min_distance": 18,
        "quality_level": 0.01,
        "block_size": 7,
        "lk_win_size": 21,
        "lk_max_level": 3,
        "fb_threshold": 1.0,
        "min_ncc": 0.65,
        "patch_radius": 5,
        "border": 8,
    }


def _classical_config(config: dict) -> dict:
    value = dict(config.get("classical_proposer", {}))
    value.pop("identity", None)
    value.pop("adapter", None)
    value.pop("detector_response_used_by_selector", None)
    return value


def _fh_config(config: dict) -> dict:
    value = dict(config.get("fh_correctness", {}))
    value.pop("implementation", None)
    value.pop("fit_source", None)
    value.pop("models", None)
    value.pop("arbitration", None)
    value.pop("no_valid_base_model", None)
    return value


def _fit_k0(tracks, config: FHConfig) -> FHFitResult:
    return fit_base_models(tracks.ids, tracks.prev_points, tracks.points, config)


def _make_k0_evidence(tracks, fit, histories, image_shape, model, fh_cfg):
    decisions = classify_correspondences(fit, tracks.prev_points, tracks.points, fh_cfg)
    output = []
    for index, track_id in enumerate(tracks.ids):
        prior = tuple(histories.get(int(track_id), []))
        evidence = TrackEvidence(
            track_id=int(track_id),
            source="klt_base",
            u=float(tracks.points[index, 0]),
            v=float(tracks.points[index, 1]),
            q_lower=1.0,
            normalized_residual=float(decisions[index].normalized_residual),
            age=int(tracks.ages[index]),
            ncc=float(tracks.ncc_scores[index]),
            fb_error=float(tracks.fb_errors[index]),
            survival_count=int(tracks.ages[index]),
            residual_history=prior,
        )
        output.append(_apply_model_q(evidence, model))
    return output


def _record_k0_snapshots(snapshots, sequence_id, stratum, frame, tracks, evidence, fit, fh_cfg):
    decisions = classify_correspondences(fit, tracks.prev_points, tracks.points, fh_cfg)
    for track, decision in zip(evidence, decisions):
        snapshots.append(
            TemporalSnapshot(
                sequence_id=sequence_id,
                lineage_id=track.track_id,
                source_group="klt",
                geometry_stratum=stratum,
                frame_index=int(frame),
                evidence=track,
                klt_valid=True,
                geometry_correct=decision.accepted,
            )
        )


def _append_k0_histories(tracks, fit, histories, fh_cfg):
    decisions = classify_correspondences(fit, tracks.prev_points, tracks.points, fh_cfg)
    for track_id, decision in zip(tracks.ids, decisions):
        values = histories.setdefault(int(track_id), [])
        values.append(float(decision.normalized_residual))
        del values[:-30]


def _advance_pool(
    states,
    previous_gray,
    gray,
    frame_index,
    fit,
    fh_cfg,
    probation_cfg,
    base_motion,
    sequence_id,
    stratum,
    snapshots,
    model,
    *,
    source_group,
    image_shape,
):
    if previous_gray is None or not states:
        return [], len(states), []
    ordered = sorted(states.values(), key=lambda state: int(state.lineage_id))
    previous_points = np.asarray([state.point for state in ordered], dtype=np.float32)
    current_points, status, _ = cv2.calcOpticalFlowPyrLK(
        previous_gray,
        gray,
        previous_points.reshape(-1, 1, 2),
        None,
        winSize=(int(probation_cfg.get("lk_win_size", 21)),) * 2,
        maxLevel=int(probation_cfg.get("lk_max_level", 3)),
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if current_points is None or status is None:
        states.clear()
        return [], 0, []
    current_points = current_points.reshape(-1, 2)
    back_points, back_status, _ = cv2.calcOpticalFlowPyrLK(
        gray,
        previous_gray,
        current_points.reshape(-1, 1, 2),
        None,
        winSize=(int(probation_cfg.get("lk_win_size", 21)),) * 2,
        maxLevel=int(probation_cfg.get("lk_max_level", 3)),
        criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
    )
    if back_points is None or back_status is None:
        back_points = previous_points.copy()
        back_status = np.zeros_like(status)
    back_points = back_points.reshape(-1, 2)
    fb = np.linalg.norm(previous_points - back_points, axis=1)
    ncc = _patch_ncc(
        previous_gray,
        gray,
        previous_points,
        current_points,
        int(probation_cfg.get("patch_radius", 5)),
    )
    valid = (
        (status.reshape(-1) > 0)
        & (back_status.reshape(-1) > 0)
        & np.isfinite(current_points).all(axis=1)
        & (fb <= float(probation_cfg.get("max_fb_error", 1.2)))
        & (ncc >= float(probation_cfg.get("min_ncc", 0.42)))
        & _in_border(current_points, gray.shape, int(probation_cfg.get("border_px", 8)))
    )
    safe_current = np.where(np.isfinite(current_points), current_points, previous_points)
    decisions = classify_correspondences(fit, previous_points, safe_current, fh_cfg)
    eligible = []
    live_evidence = []
    for index, state in enumerate(ordered):
        if not valid[index]:
            states.pop(state.lineage_id, None)
            continue
        prior = tuple(state.residual_history or [])
        state.age += 1
        state.survival_count += 1
        state.fb_error = float(fb[index])
        state.ncc = float(ncc[index])
        state.point = current_points[index].astype(np.float32)
        if base_motion > 1e-6:
            state.motion_ratios.append(float(np.linalg.norm(current_points[index] - previous_points[index]) / base_motion))
            del state.motion_ratios[:-10]
        decision = decisions[index]
        if decision.reason != "NO_VALID_BASE_MODEL":
            state.correctness_failures = 0 if decision.accepted else state.correctness_failures + 1
        evidence = TrackEvidence(
            track_id=int(state.lineage_id),
            source=state.source,
            u=float(current_points[index, 0]),
            v=float(current_points[index, 1]),
            q_lower=1.0,
            normalized_residual=float(decision.normalized_residual),
            age=int(state.age),
            ncc=float(state.ncc),
            fb_error=float(state.fb_error),
            survival_count=int(state.survival_count),
            residual_history=prior,
            motion_ratio=(
                float(np.median(state.motion_ratios)) if state.motion_ratios else None
            ),
        )
        evidence = _apply_model_q(evidence, model)
        live_evidence.append(evidence)
        snapshots.append(
            TemporalSnapshot(
                sequence_id=sequence_id,
                lineage_id=state.lineage_id,
                source_group=source_group,
                geometry_stratum=stratum,
                frame_index=int(frame_index),
                evidence=evidence,
                klt_valid=True,
                geometry_correct=decision.accepted,
                decision_eligible=state.age >= int(probation_cfg.get("min_observations", 5)),
            )
        )
        state.residual_history.append(float(decision.normalized_residual))
        del state.residual_history[:-30]
        motion_ok = (
            state.motion_ratios
            and float(probation_cfg.get("min_motion_ratio", 0.6))
            <= float(np.median(state.motion_ratios))
            <= float(probation_cfg.get("max_motion_ratio", 1.5))
        )
        if (
            state.age >= int(probation_cfg.get("min_observations", 5))
            and decision.accepted
            and motion_ok
        ):
            eligible.append(evidence)
        if state.correctness_failures >= int(probation_cfg.get("sustained_correctness_failures", 2)):
            states.pop(state.lineage_id, None)
    return eligible, len(states), live_evidence


def _add_xfeat_states(states, matcher, previous_gray, gray, frame_index, blocked_points, next_id):
    result = matcher.match(previous_gray, gray)
    points0 = np.asarray(result.points0, dtype=np.float32).reshape(-1, 2)
    points1 = np.asarray(result.points1, dtype=np.float32).reshape(-1, 2)
    if len(points0) != len(points1):
        return 0, next_id
    order = sorted(
        range(len(points0)),
        key=lambda index: (
            float(points1[index, 1]),
            float(points1[index, 0]),
            float(points0[index, 1]),
            float(points0[index, 0]),
        ),
    )
    added = 0
    for index in order:
        point = points1[index]
        if not np.isfinite(point).all() or not _far_from(point, blocked_points, 18.0):
            continue
        if any(np.linalg.norm(point - state.point) < 18.0 for state in states.values()):
            continue
        states[next_id] = _CandidateState(
            lineage_id=next_id,
            source="learned_xfeat",
            point=point.copy(),
            birth_frame=int(frame_index),
        )
        next_id += 1
        if next_id >= 16_777_216:
            raise OverflowError("learned lineage IDs exceeded exact float32 range")
        added += 1
        if added >= 256:
            break
    return added, next_id


def _far_from(point, others, radius):
    if others is None or len(others) == 0:
        return True
    array = np.asarray(others, dtype=np.float32).reshape(-1, 2)
    return bool(np.all(np.linalg.norm(array - point.reshape(1, 2), axis=1) >= float(radius)))


def _apply_model_q(evidence, model):
    if model is None:
        return evidence
    q = float(model.q_lower([selector_features(evidence)])[0])
    return replace(evidence, q_lower=q)


def _median_motion(tracks):
    if len(tracks) == 0:
        return 0.0
    mask = np.isfinite(tracks.prev_points).all(axis=1) & np.isfinite(tracks.points).all(axis=1)
    mask &= tracks.ages > 1
    if not np.any(mask):
        return 0.0
    return float(np.median(np.linalg.norm(tracks.points[mask] - tracks.prev_points[mask], axis=1)))


def _base_export_ids(evidence, cap):
    ordered = sorted(
        evidence,
        key=lambda track: (-int(track.age), float(track.fb_error), -float(track.ncc), int(track.track_id)),
    )
    return tuple(sorted(int(track.track_id) for track in ordered[: int(cap)]))


def _write_metrics(path, rows):
    fields = list(rows[0].keys()) if rows else ["frame_index"]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _write_empty_calibration(path):
    fields = [
        "sequence_id", "lineage_id", "source_group", "geometry_stratum",
        "decision_frame", "label_end_frame", "split",
        "age_norm_30", "ncc_score", "fb_score_tau_1px", "survival_ratio",
        "prior_residual_median_score", "prior_residual_p95_score", "label",
    ]
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        csv.DictWriter(handle, fieldnames=fields).writeheader()


def _load_timestamps(path: str | Path) -> dict[int, float]:
    """Load a deterministic frame-index timestamp sidecar for bag extracts."""

    result: dict[int, float] = {}
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if not {"frame_index", "timestamp"} <= set(reader.fieldnames or ()):
            raise ValueError("timestamps CSV requires frame_index,timestamp columns")
        for row_number, row in enumerate(reader, start=2):
            index = int(row["frame_index"])
            timestamp = float(row["timestamp"])
            if not math.isfinite(timestamp):
                raise ValueError(f"timestamps CSV row {row_number} is non-finite")
            if index in result:
                raise ValueError(f"timestamps CSV duplicates frame_index {index}")
            result[index] = timestamp
    ordered = sorted(result)
    if any(result[b] <= result[a] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("timestamps CSV must be strictly increasing by frame index")
    return result


def _sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
