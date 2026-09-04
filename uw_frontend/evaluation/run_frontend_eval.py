from __future__ import annotations

import argparse
import csv
import copy
import time
from pathlib import Path

import cv2
import numpy as np
import yaml

from uw_frontend.datasets.image_sequence import ImageSequence
from uw_frontend.evaluation.frontend_metrics import draw_tracks, make_frame_metrics, metrics_to_dict
from uw_frontend.evaluation.measurement_selection import (
    MeasurementSelectionConfig,
    select_backend_measurements,
)
from uw_frontend.geometry.grid import grid_stats
from uw_frontend.geometry.validation import GeometryStats, validate_geometry
from uw_frontend.matchers.base import BaseMatcher
from uw_frontend.matchers.classical_gftt import ClassicalGfttMatcher
from uw_frontend.matchers.lightglue_adapter import SuperPointLightGlueMatcher
from uw_frontend.matchers.loftr_adapter import LoFTRMatcher
from uw_frontend.matchers.xfeat_adapter import XFeatMatcher
from uw_frontend.quality.image_quality import fuse_image_quality_for_gates, score_image_quality
from uw_frontend.quality.feature_confidence import ReliabilityCalibrator, quality_to_sigma
from uw_frontend.quality.reliability_features import RELIABILITY_FEATURE_NAMES, build_reliability_features
from uw_frontend.scheduler.hybrid_scheduler import HybridScheduler, SchedulerConfig
from uw_frontend.tracking.hybrid_tracker import HybridConfig, HybridKltOrbTracker
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker
from uw_frontend.tracking.orb_tracker import OrbConfig, OrbTracker
from uw_frontend.tracking.pairwise_matcher_tracker import PairwiseMatcherTracker, PairwiseMatcherTrackerConfig
from uw_frontend.tracking.track_state import TrackerDiagnostics


def load_config(path: str | Path | None) -> dict:
    if path is None:
        return {}
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    parents = cfg.pop("extends", None)
    if parents is None:
        return cfg
    if isinstance(parents, (str, Path)):
        parents = [parents]
    merged: dict = {}
    for parent in parents:
        parent_path = Path(parent)
        if not parent_path.is_absolute():
            parent_path = (config_path.parent / parent_path).resolve()
        merged = _deep_merge(merged, load_config(parent_path))
    return _deep_merge(merged, cfg)


def _deep_merge(base: dict, override: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def resolve_process_skipped_frames(cli_value: bool | None, cfg: dict) -> bool:
    """Resolve bag cadence with explicit CLI precedence over the profile.

    Missing configuration remains False for backward compatibility.  Bag
    frontends use ``frontend_runtime.process_skipped_frames`` so cadence is a
    reproducible profile property instead of an implicit shell-script choice.
    """

    if cli_value is not None:
        return bool(cli_value)
    runtime_cfg = cfg.get("frontend_runtime", {})
    if not isinstance(runtime_cfg, dict):
        raise TypeError("frontend_runtime must be a mapping")
    return bool(runtime_cfg.get("process_skipped_frames", False))


def build_matcher(method: str, cfg: dict) -> BaseMatcher:
    if method in {"classical_gftt", "hybrid_classical_gftt"}:
        return ClassicalGfttMatcher(**cfg.get("classical_gftt", {}))
    if method in {"xfeat", "hybrid_xfeat"}:
        return XFeatMatcher(**cfg.get("xfeat", {}))
    if method in {"xfeat_star", "hybrid_xfeat_star"}:
        matcher_cfg = dict(cfg.get("xfeat", {}))
        matcher_cfg["semi_dense"] = True
        matcher = XFeatMatcher(**matcher_cfg)
        matcher.name = "xfeat_star"
        return matcher
    if method in {"superpoint_lightglue", "hybrid_superpoint_lightglue"}:
        return SuperPointLightGlueMatcher(**cfg.get("lightglue", {}))
    if method in {"loftr", "hybrid_loftr"}:
        return LoFTRMatcher(**cfg.get("loftr", {}))
    raise ValueError(f"Unsupported matcher method: {method}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run underwater frontend-only evaluation.")
    parser.add_argument("--input", required=True, help="Image directory, image file, or tar/tar.gz archive.")
    parser.add_argument("--image-prefix", default=None, help="Optional substring filter for image paths inside archives.")
    parser.add_argument("--output-csv", required=True)
    parser.add_argument(
        "--method",
        choices=[
            "klt",
            "orb",
            "hybrid",
            "xfeat",
            "xfeat_star",
            "superpoint_lightglue",
            "loftr",
            "hybrid_xfeat",
            "hybrid_xfeat_star",
            "hybrid_superpoint_lightglue",
            "hybrid_loftr",
            "classical_gftt",
            "hybrid_classical_gftt",
        ],
        default="klt",
    )
    parser.add_argument("--config", default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument("--start-index", type=int, default=0)
    parser.add_argument("--end-index", type=int, default=None)
    parser.add_argument("--save-viz-dir", default=None)
    parser.add_argument("--save-viz-every", type=int, default=30)
    parser.add_argument(
        "--preprocess",
        choices=["none", "equalize", "clahe", "adaptive_clahe"],
        default="none",
        help="Image preprocessing applied before frontend tracking.",
    )
    parser.add_argument("--reliability-model", default=None, help="Optional calibrated feature reliability JSON.")
    parser.add_argument("--reliability-log-csv", default=None, help="Optional per-feature reliability training log.")
    parser.add_argument(
        "--track-log-csv",
        default=None,
        help="Optional per-frame per-track export with q_i and visual sigma for backend integration.",
    )
    parser.add_argument(
        "--enable-temporal-health-gate",
        action="store_true",
        help="Enable temporal track-health recovery triggers for hybrid frontends.",
    )
    parser.add_argument(
        "--enable-unified-state-gate",
        action="store_true",
        help="Enable unified frontend-state recovery triggers for hybrid frontends.",
    )
    parser.add_argument(
        "--enable-homography-recovery",
        action="store_true",
        help="Enable planar near-wall Homography-guided lost-track recovery for hybrid frontends.",
    )
    parser.add_argument(
        "--enable-geometry-safe-recovery",
        action="store_true",
        help="Gate learned recovery/initialization batches if they degrade frame geometry.",
    )
    parser.add_argument(
        "--geometry-safe-apply-to-classical",
        action="store_true",
        help="Also apply geometry-safe gating to LK/ORB/Homography recovery batches.",
    )
    parser.add_argument(
        "--semidense-fallback-method",
        choices=["none", "xfeat_star", "loftr"],
        default="none",
        help="Optional second matcher for sparse-cell semi-dense fallback initialization.",
    )
    parser.add_argument(
        "--measurement-selection",
        action="store_true",
        help="Evaluate/export a backend-ready geometry- and quality-selected measurement set.",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    quality_gate_source = str(
        cfg.get("quality", {}).get("gate_source", cfg.get("quality_gate_source", "preprocessed"))
    )
    calibrator = ReliabilityCalibrator.from_json(args.reliability_model) if args.reliability_model else None
    if args.method == "klt":
        tracker = KltTracker(KltConfig(**cfg.get("klt", {})))
    elif args.method == "orb":
        tracker = OrbTracker(OrbConfig(**cfg.get("orb", {})))
    elif args.method == "hybrid":
        hybrid_config = HybridConfig(**cfg.get("hybrid", {}))
        if args.enable_temporal_health_gate:
            hybrid_config.enable_temporal_health_gate = True
        if args.enable_unified_state_gate:
            hybrid_config.enable_unified_state_gate = True
        if args.enable_homography_recovery:
            hybrid_config.enable_homography_recovery = True
        if args.enable_geometry_safe_recovery:
            hybrid_config.enable_geometry_safe_recovery = True
        if args.geometry_safe_apply_to_classical:
            hybrid_config.geometry_safe_apply_to_classical = True
        tracker = HybridKltOrbTracker(
            KltConfig(**cfg.get("klt", {})),
            hybrid_config,
        )
    elif args.method in {
        "xfeat",
        "xfeat_star",
        "superpoint_lightglue",
        "loftr",
        "classical_gftt",
    }:
        tracker = PairwiseMatcherTracker(
            build_matcher(args.method, cfg),
            PairwiseMatcherTrackerConfig(**cfg.get("pairwise", {})),
        )
    elif args.method in {
        "hybrid_xfeat",
        "hybrid_xfeat_star",
        "hybrid_superpoint_lightglue",
        "hybrid_loftr",
        "hybrid_classical_gftt",
    }:
        fallback_matcher = (
            build_matcher(args.semidense_fallback_method, cfg)
            if args.semidense_fallback_method != "none"
            else None
        )
        hybrid_config = HybridConfig(**cfg.get("hybrid", {}))
        if args.enable_temporal_health_gate:
            hybrid_config.enable_temporal_health_gate = True
        if args.enable_unified_state_gate:
            hybrid_config.enable_unified_state_gate = True
        if args.enable_homography_recovery:
            hybrid_config.enable_homography_recovery = True
        if args.enable_geometry_safe_recovery:
            hybrid_config.enable_geometry_safe_recovery = True
        if args.geometry_safe_apply_to_classical:
            hybrid_config.geometry_safe_apply_to_classical = True
        tracker = HybridKltOrbTracker(
            KltConfig(**cfg.get("klt", {})),
            hybrid_config,
            learned_matcher=build_matcher(args.method, cfg),
            semidense_fallback_matcher=fallback_matcher,
        )
    else:
        raise ValueError(f"Unsupported method: {args.method}")
    scheduler_cfg = SchedulerConfig(**cfg.get("scheduler", {}))
    grid_cfg = cfg.get("grid", {})
    grid_rows = int(grid_cfg.get("rows", 4))
    grid_cols = int(grid_cfg.get("cols", 6))
    measurement_selection_cfg = MeasurementSelectionConfig(
        **cfg.get("measurement_selection", {})
    )
    if args.measurement_selection:
        measurement_selection_cfg.enabled = True

    sequence = ImageSequence(
        args.input,
        image_prefix=args.image_prefix,
        every_n=args.every_n,
        max_frames=args.max_frames,
        start_index=args.start_index,
        end_index=args.end_index,
    )
    scheduler = HybridScheduler(scheduler_cfg)
    output_csv = Path(args.output_csv)
    output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = None
    previous_metric_track_ids: set[int] = set()
    reliability_handle = None
    reliability_writer = None
    track_log_handle = None
    track_log_writer = None
    pending_reliability: dict[int, dict] = {}
    if args.reliability_log_csv:
        reliability_path = Path(args.reliability_log_csv)
        reliability_path.parent.mkdir(parents=True, exist_ok=True)
        reliability_handle = reliability_path.open("w", newline="", encoding="utf-8")
        reliability_writer = csv.DictWriter(
            reliability_handle,
            fieldnames=[
                "frame_index",
                "frame_name",
                "track_id",
                "source",
                "label",
                "label_reason",
                "geometry_mode",
                "geometry_reason",
                "scheduler_mode",
                "scheduler_reason",
                "planar_confidence",
            ] + RELIABILITY_FEATURE_NAMES,
        )
        reliability_writer.writeheader()
    if args.track_log_csv:
        track_log_path = Path(args.track_log_csv)
        track_log_path.parent.mkdir(parents=True, exist_ok=True)
        track_log_handle = track_log_path.open("w", newline="", encoding="utf-8")
        track_log_writer = csv.DictWriter(
            track_log_handle,
            fieldnames=[
                "frame_index",
                "frame_name",
                "track_id",
                "source",
                "prev_x",
                "prev_y",
                "x",
                "y",
                "age",
                "fb_error",
                "ncc",
                "local_texture",
                "quality",
                "visual_sigma",
                "image_quality",
                "grid_coverage",
                "fundamental_inlier_ratio",
                "homography_inlier_ratio",
                "geometry_mode",
                "scheduler_mode",
                "track_health_score",
                "track_health_reason",
                "frontend_state_score",
                "frontend_state_reason",
                "adaptive_geometry_model",
            ],
        )
        track_log_writer.writeheader()
    try:
        emitted_frames = 0
        with output_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = None
            for frame in sequence:
                emitted_frames += 1
                start = time.perf_counter()
                raw_quality = score_image_quality(frame.image)
                image = _preprocess_gray(frame.image, args.preprocess)
                processed_quality = score_image_quality(image)
                quality = fuse_image_quality_for_gates(
                    processed_quality,
                    raw_quality,
                    quality_gate_source,
                )
                tracks, diagnostics = tracker.process(image, quality)
                tracker_recovery_reason = str(getattr(tracker, "last_recovery_reason", "n/a"))
                tracker_recovered_count = int(getattr(tracker, "last_recovered_count", 0))
                track_health_score = float(getattr(tracker, "last_track_health_score", float("nan")))
                track_health_reason = str(getattr(tracker, "last_track_health_reason", "n/a"))
                frontend_state_score = float(getattr(tracker, "last_frontend_state_score", float("nan")))
                frontend_state_reason = str(getattr(tracker, "last_frontend_state_reason", "n/a"))
                semidense_acceptance = str(getattr(tracker, "last_semidense_acceptance", "n/a"))
                geometry_safe_acceptance = str(getattr(tracker, "last_geometry_safe_acceptance", "n/a"))
                learned_mode_before_sparse_homography = str(
                    getattr(tracker, "last_learned_mode_before_sparse_homography", "n/a")
                )
                learned_mode_after_sparse_homography = str(
                    getattr(tracker, "last_learned_mode_after_sparse_homography", "n/a")
                )
                base_learned_mode_before_sparse_override = learned_mode_before_sparse_homography
                learned_mode_after_sparse_override = learned_mode_after_sparse_homography
                learned_mode_sparse_homography_allowed = bool(
                    getattr(tracker, "last_learned_mode_sparse_homography_allowed", False)
                )
                learned_mode_sparse_homography_reason = str(
                    getattr(tracker, "last_learned_mode_sparse_homography_reason", "n/a")
                )
                loftr_sparse_homography_allowed = bool(
                    getattr(tracker, "last_loftr_sparse_homography_allowed", False)
                )
                loftr_sparse_homography_reason = str(
                    getattr(tracker, "last_loftr_sparse_homography_reason", "n/a")
                )
                last_loftr_sparse_homography_check_allowed = loftr_sparse_homography_allowed
                last_loftr_sparse_homography_check_reason = loftr_sparse_homography_reason
                semidense_raw_candidates = int(getattr(tracker, "last_semidense_raw_candidates", 0))
                semidense_post_validate_candidates = int(
                    getattr(tracker, "last_semidense_post_validate_candidates", 0)
                )
                semidense_accepted_candidates = int(
                    getattr(tracker, "last_semidense_accepted_candidates", 0)
                )
                semidense_queued_pending = int(getattr(tracker, "last_semidense_queued_pending", 0))
                semidense_grid_gain = float(getattr(tracker, "last_semidense_grid_gain", float("nan")))
                semidense_new_cell_ratio = float(
                    getattr(tracker, "last_semidense_new_cell_ratio", float("nan"))
                )
                semidense_before_f_inlier = float(
                    getattr(tracker, "last_semidense_before_f_inlier", float("nan"))
                )
                semidense_after_f_inlier = float(
                    getattr(tracker, "last_semidense_after_f_inlier", float("nan"))
                )
                semidense_before_h_inlier = float(
                    getattr(tracker, "last_semidense_before_h_inlier", float("nan"))
                )
                semidense_after_h_inlier = float(
                    getattr(tracker, "last_semidense_after_h_inlier", float("nan"))
                )
                semidense_before_epipolar = float(
                    getattr(tracker, "last_semidense_before_epipolar", float("nan"))
                )
                semidense_after_epipolar = float(
                    getattr(tracker, "last_semidense_after_epipolar", float("nan"))
                )
                semidense_before_homography = float(
                    getattr(tracker, "last_semidense_before_homography", float("nan"))
                )
                semidense_after_homography = float(
                    getattr(tracker, "last_semidense_after_homography", float("nan"))
                )
                pending_loftr_count = int(getattr(tracker, "last_pending_loftr_count", 0))
                pending_loftr_age_median = float(
                    getattr(tracker, "last_pending_loftr_age_median", float("nan"))
                )
                loftr_confirmed_promoted = int(getattr(tracker, "last_loftr_confirmed_promoted", 0))
                klt_degeneracy_loftr_allowed = bool(
                    getattr(tracker, "last_klt_degeneracy_loftr_allowed", False)
                )
                klt_degeneracy_loftr_reason = str(
                    getattr(tracker, "last_klt_degeneracy_loftr_reason", "n/a")
                )
                klt_degeneracy_loftr_score = float(
                    getattr(tracker, "last_klt_degeneracy_loftr_score", 0.0)
                )
                candidate_bank_count = int(getattr(tracker, "last_candidate_bank_count", 0))
                candidate_bank_coverage = float(getattr(tracker, "last_candidate_bank_coverage", 0.0))
                candidate_bank_grid_gain = float(getattr(tracker, "last_candidate_bank_grid_gain", 0.0))
                stable_candidate_grid_coverage = float(
                    getattr(tracker, "last_stable_candidate_grid_coverage", 0.0)
                )
                adaptive_geometry_model = str(getattr(tracker, "last_adaptive_geometry_model", "n/a"))
                grid = grid_stats(tracks.points, image.shape, rows=grid_rows, cols=grid_cols)
                motion_mask = tracks.ages > 1
                if diagnostics.tracked_before_filter >= 8 and int(motion_mask.sum()) >= 8:
                    geometry, _ = validate_geometry(tracks.prev_points[motion_mask], tracks.points[motion_mask])
                else:
                    geometry = GeometryStats(0, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
                decision = scheduler.decide(quality, grid, geometry, diagnostics, len(tracks))
                if calibrator is not None and len(tracks):
                    features, base_quality = build_reliability_features(tracks, quality, grid, geometry, diagnostics)
                    features_for_calibrator = _align_reliability_features(features, calibrator.feature_names)
                    tracks.qualities = calibrator.predict(features_for_calibrator, base_quality, tracks.sources)
                    grid = grid_stats(tracks.points, image.shape, rows=grid_rows, cols=grid_cols)

                metric_tracks = select_backend_measurements(
                    tracks,
                    image.shape,
                    measurement_selection_cfg,
                    geometry_mode=decision.geometry_mode,
                )
                metric_grid = grid_stats(metric_tracks.points, image.shape, rows=grid_rows, cols=grid_cols)
                metric_motion_mask = metric_tracks.ages > 1
                if diagnostics.tracked_before_filter >= 8 and int(metric_motion_mask.sum()) >= 8:
                    metric_geometry, _ = validate_geometry(
                        metric_tracks.prev_points[metric_motion_mask],
                        metric_tracks.points[metric_motion_mask],
                    )
                else:
                    metric_geometry = GeometryStats(0, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
                metric_decision = scheduler.decide(
                    quality,
                    metric_grid,
                    metric_geometry,
                    diagnostics,
                    len(metric_tracks),
                )
                metric_diagnostics = _diagnostics_for_output_tracks(
                    metric_tracks,
                    previous_metric_track_ids,
                    fallback=diagnostics,
                )
                previous_metric_track_ids = set(int(track_id) for track_id in metric_tracks.ids)
                if track_log_writer is not None:
                    _write_track_rows(
                        track_log_writer,
                        frame.index,
                        frame.name,
                        metric_tracks,
                        quality,
                        metric_grid,
                        metric_geometry,
                        metric_decision,
                        track_health_score,
                        track_health_reason,
                        frontend_state_score,
                        frontend_state_reason,
                        adaptive_geometry_model,
                    )
                if reliability_writer is not None:
                    _write_reliability_rows(
                        reliability_writer,
                        pending_reliability,
                        frame.index,
                        frame.name,
                        tracks,
                        quality,
                        grid,
                        geometry,
                        diagnostics,
                        decision,
                    )
                runtime_ms = (time.perf_counter() - start) * 1000.0
                metrics = make_frame_metrics(
                    frame.index,
                    frame.name,
                    metric_tracks,
                    metric_diagnostics,
                    quality,
                    metric_grid,
                    metric_geometry,
                    metric_decision,
                    runtime_ms,
                    tracker_recovery_reason=tracker_recovery_reason,
                    tracker_recovered_count=tracker_recovered_count,
                    track_health_score=track_health_score,
                    track_health_reason=track_health_reason,
                    frontend_state_score=frontend_state_score,
                    frontend_state_reason=frontend_state_reason,
                    semidense_acceptance=semidense_acceptance,
                    geometry_safe_acceptance=geometry_safe_acceptance,
                    learned_mode_before_sparse_homography=learned_mode_before_sparse_homography,
                    learned_mode_after_sparse_homography=learned_mode_after_sparse_homography,
                    base_learned_mode_before_sparse_override=base_learned_mode_before_sparse_override,
                    learned_mode_after_sparse_override=learned_mode_after_sparse_override,
                    learned_mode_sparse_homography_allowed=learned_mode_sparse_homography_allowed,
                    learned_mode_sparse_homography_reason=learned_mode_sparse_homography_reason,
                    last_loftr_sparse_homography_check_allowed=last_loftr_sparse_homography_check_allowed,
                    last_loftr_sparse_homography_check_reason=last_loftr_sparse_homography_check_reason,
                    loftr_sparse_homography_allowed=loftr_sparse_homography_allowed,
                    loftr_sparse_homography_reason=loftr_sparse_homography_reason,
                    semidense_raw_candidates=semidense_raw_candidates,
                    semidense_post_validate_candidates=semidense_post_validate_candidates,
                    semidense_accepted_candidates=semidense_accepted_candidates,
                    semidense_queued_pending=semidense_queued_pending,
                    semidense_grid_gain=semidense_grid_gain,
                    semidense_new_cell_ratio=semidense_new_cell_ratio,
                    semidense_before_f_inlier=semidense_before_f_inlier,
                    semidense_after_f_inlier=semidense_after_f_inlier,
                    semidense_before_h_inlier=semidense_before_h_inlier,
                    semidense_after_h_inlier=semidense_after_h_inlier,
                    semidense_before_epipolar=semidense_before_epipolar,
                    semidense_after_epipolar=semidense_after_epipolar,
                    semidense_before_homography=semidense_before_homography,
                    semidense_after_homography=semidense_after_homography,
                    pending_loftr_count=pending_loftr_count,
                    pending_loftr_age_median=pending_loftr_age_median,
                    loftr_confirmed_promoted=loftr_confirmed_promoted,
                    klt_degeneracy_loftr_allowed=klt_degeneracy_loftr_allowed,
                    klt_degeneracy_loftr_reason=klt_degeneracy_loftr_reason,
                    klt_degeneracy_loftr_score=klt_degeneracy_loftr_score,
                    candidate_bank_count=candidate_bank_count,
                    candidate_bank_coverage=candidate_bank_coverage,
                    candidate_bank_grid_gain=candidate_bank_grid_gain,
                    stable_candidate_grid_coverage=stable_candidate_grid_coverage,
                    adaptive_geometry_model=adaptive_geometry_model,
                )
                row = metrics_to_dict(metrics)
                if writer is None:
                    fieldnames = list(row.keys())
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                writer.writerow(row)

                if args.save_viz_dir and (frame.index % max(1, args.save_viz_every) == 0):
                    viz_name = f"frame_{frame.index:06d}.jpg"
                    draw_tracks(image, tracks, Path(args.save_viz_dir) / viz_name)
        if emitted_frames == 0:
            raise RuntimeError(
                f"No frames were read from {args.input!r}; check --image-prefix, --start-index, and --end-index."
            )

        if reliability_writer is not None:
            for row in pending_reliability.values():
                row = dict(row)
                row["label"] = 0
                row["label_reason"] = "dropout_or_end"
                reliability_writer.writerow(row)
    finally:
        if reliability_handle is not None:
            reliability_handle.close()
        if track_log_handle is not None:
            track_log_handle.close()

    print(f"wrote {output_csv}")
    if args.save_viz_dir:
        print(f"wrote visualizations under {args.save_viz_dir}")
    if args.reliability_log_csv:
        print(f"wrote reliability log {args.reliability_log_csv}")
    if args.track_log_csv:
        print(f"wrote track log {args.track_log_csv}")
    return 0


def _preprocess_gray(gray: np.ndarray, mode: str) -> np.ndarray:
    if mode == "none":
        return gray
    if mode == "equalize":
        return cv2.equalizeHist(gray)
    if mode == "clahe":
        return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    if mode == "adaptive_clahe":
        quality = score_image_quality(gray)
        should_enhance = (
            quality.contrast_score < 0.72
            or quality.grid_texture_score < 0.58
            or quality.illumination_nonuniformity > 0.18
            or quality.degradation_score > 0.42
        )
        if should_enhance:
            return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        return gray
    raise ValueError(f"unsupported preprocess mode: {mode}")


def _diagnostics_for_output_tracks(
    tracks,
    previous_ids: set[int],
    fallback: TrackerDiagnostics,
) -> TrackerDiagnostics:
    current_ids = set(int(track_id) for track_id in tracks.ids)
    tracked_before = len(previous_ids)
    survived = len(previous_ids & current_ids)
    dropped = max(0, tracked_before - survived)
    added = max(0, len(current_ids - previous_ids))
    return TrackerDiagnostics(
        added_features=added,
        dropped_features=dropped,
        tracked_before_filter=tracked_before,
        tracked_after_filter=survived,
        median_fb_error=fallback.median_fb_error,
        median_ncc=fallback.median_ncc,
        median_quality=fallback.median_quality,
    )


def _write_track_rows(
    writer,
    frame_index: int,
    frame_name: str,
    tracks,
    image_quality,
    grid,
    geometry,
    decision,
    track_health_score: float,
    track_health_reason: str,
    frontend_state_score: float,
    frontend_state_reason: str,
    adaptive_geometry_model: str = "n/a",
) -> None:
    if len(tracks) == 0:
        return
    sigmas = quality_to_sigma(tracks.qualities)
    for idx, track_id in enumerate(tracks.ids):
        writer.writerow(
            {
                "frame_index": frame_index,
                "frame_name": frame_name,
                "track_id": int(track_id),
                "source": tracks.sources[idx] if idx < len(tracks.sources) else "unknown",
                "prev_x": float(tracks.prev_points[idx, 0]),
                "prev_y": float(tracks.prev_points[idx, 1]),
                "x": float(tracks.points[idx, 0]),
                "y": float(tracks.points[idx, 1]),
                "age": int(tracks.ages[idx]),
                "fb_error": float(tracks.fb_errors[idx]),
                "ncc": float(tracks.ncc_scores[idx]),
                "local_texture": float(tracks.local_texture[idx]),
                "quality": float(tracks.qualities[idx]),
                "visual_sigma": float(sigmas[idx]),
                "image_quality": float(image_quality.global_score),
                "grid_coverage": float(grid.coverage),
                "fundamental_inlier_ratio": float(geometry.fundamental_inlier_ratio),
                "homography_inlier_ratio": float(geometry.homography_inlier_ratio),
                "geometry_mode": decision.geometry_mode,
                "scheduler_mode": decision.mode,
                "track_health_score": float(track_health_score),
                "track_health_reason": track_health_reason,
                "frontend_state_score": float(frontend_state_score),
                "frontend_state_reason": frontend_state_reason,
                "adaptive_geometry_model": adaptive_geometry_model,
            }
        )


def _write_reliability_rows(
    writer,
    pending: dict[int, dict],
    frame_index: int,
    frame_name: str,
    tracks,
    image_quality,
    grid,
    geometry,
    diagnostics,
    decision,
) -> None:
    current_ids = set(int(track_id) for track_id in tracks.ids)
    for track_id in list(pending.keys()):
        row = pending.pop(track_id)
        if track_id in current_ids:
            row["label"] = 1
            row["label_reason"] = "survived_next_frame"
        else:
            row["label"] = 0
            row["label_reason"] = "dropout_next_frame"
        writer.writerow(row)

    features, _ = build_reliability_features(tracks, image_quality, grid, geometry, diagnostics)
    for idx, track_id in enumerate(tracks.ids):
        row = {
            "frame_index": frame_index,
            "frame_name": frame_name,
            "track_id": int(track_id),
            "source": tracks.sources[idx] if idx < len(tracks.sources) else "unknown",
            "geometry_mode": decision.geometry_mode,
            "geometry_reason": decision.geometry_reason,
            "scheduler_mode": decision.mode,
            "scheduler_reason": decision.reason,
            "planar_confidence": float(decision.planar_confidence),
        }
        for name, value in zip(RELIABILITY_FEATURE_NAMES, features[idx]):
            row[name] = float(value)
        pending[int(track_id)] = row


def _align_reliability_features(features, calibrator_feature_names: list[str]):
    if list(calibrator_feature_names) == RELIABILITY_FEATURE_NAMES:
        return features
    index = {name: idx for idx, name in enumerate(RELIABILITY_FEATURE_NAMES)}
    cols = []
    for name in calibrator_feature_names:
        if name not in index:
            raise ValueError(f"calibrator expects unknown reliability feature: {name}")
        cols.append(features[:, index[name]])
    return np.stack(cols, axis=1).astype("float32")


if __name__ == "__main__":
    raise SystemExit(main())
