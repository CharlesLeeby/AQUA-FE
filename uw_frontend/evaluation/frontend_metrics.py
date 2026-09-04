from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from uw_frontend.geometry.grid import GridStats
from uw_frontend.geometry.validation import GeometryStats
from uw_frontend.quality.feature_confidence import quality_to_sigma
from uw_frontend.quality.image_quality import ImageQuality
from uw_frontend.scheduler.hybrid_scheduler import SchedulerDecision
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


@dataclass
class FrameMetrics:
    frame_index: int
    frame_name: str
    num_features: int
    added_features: int
    dropped_features: int
    dropout_ratio: float
    tracked_before_filter: int
    tracked_after_filter: int
    grid_coverage: float
    grid_occupied: int
    grid_total: int
    median_track_age: float
    mean_track_age: float
    long_track_ratio: float
    median_fb_error: float
    median_ncc: float
    median_quality: float
    mean_quality: float
    median_visual_sigma: float
    mean_visual_sigma: float
    low_texture_feature_ratio: float
    low_texture_track_age_median: float
    low_texture_quality_median: float
    mean_intensity: float
    contrast: float
    gradient_mean: float
    laplacian_var: float
    underexposed_ratio: float
    overexposed_ratio: float
    illumination_nonuniformity: float
    local_contrast: float
    flat_region_ratio: float
    texture_score: float
    blur_score: float
    exposure_score: float
    contrast_score: float
    illumination_score: float
    backscatter_score: float
    highlight_shadow_score: float
    grid_texture_score: float
    underwater_score: float
    degradation_score: float
    image_quality: float
    fundamental_inlier_ratio: float
    homography_inlier_ratio: float
    median_epipolar_error: float
    median_homography_error: float
    planar_score: float
    tracker_mode: str
    tracker_recovery_reason: str
    tracker_recovered_count: int
    track_health_score: float
    track_health_reason: str
    frontend_state_score: float
    frontend_state_reason: str
    semidense_acceptance: str
    geometry_safe_acceptance: str
    learned_mode_before_sparse_homography: str
    learned_mode_after_sparse_homography: str
    base_learned_mode_before_sparse_override: str
    learned_mode_after_sparse_override: str
    learned_mode_sparse_homography_allowed: bool
    learned_mode_sparse_homography_reason: str
    last_loftr_sparse_homography_check_allowed: bool
    last_loftr_sparse_homography_check_reason: str
    loftr_sparse_homography_allowed: bool
    loftr_sparse_homography_reason: str
    semidense_raw_candidates: int
    semidense_post_validate_candidates: int
    semidense_accepted_candidates: int
    semidense_queued_pending: int
    semidense_grid_gain: float
    semidense_new_cell_ratio: float
    semidense_before_f_inlier: float
    semidense_after_f_inlier: float
    semidense_before_h_inlier: float
    semidense_after_h_inlier: float
    semidense_before_epipolar: float
    semidense_after_epipolar: float
    semidense_before_homography: float
    semidense_after_homography: float
    pending_loftr_count: int
    pending_loftr_age_median: float
    loftr_confirmed_promoted: int
    klt_degeneracy_loftr_allowed: bool
    klt_degeneracy_loftr_reason: str
    klt_degeneracy_loftr_score: float
    scheduler_mode: str
    scheduler_reason: str
    geometry_mode: str
    geometry_reason: str
    planar_confidence: float
    adaptive_geometry_model: str
    klt_tracks: int
    gftt_tracks: int
    orb_tracks: int
    orb_match_tracks: int
    orb_recovery_tracks: int
    lk_recovery_tracks: int
    homography_recovery_tracks: int
    xfeat_tracks: int
    xfeat_recovery_tracks: int
    xfeat_init_tracks: int
    xfeat_confirmed_tracks: int
    xfeat_star_tracks: int
    xfeat_star_recovery_tracks: int
    xfeat_star_init_tracks: int
    xfeat_star_confirmed_tracks: int
    superpoint_lightglue_tracks: int
    superpoint_lightglue_recovery_tracks: int
    superpoint_lightglue_init_tracks: int
    superpoint_lightglue_confirmed_tracks: int
    learned_memory_tracks: int
    loftr_tracks: int
    loftr_recovery_tracks: int
    loftr_init_tracks: int
    loftr_confirmed_tracks: int
    candidate_bank_count: int
    candidate_bank_coverage: float
    candidate_bank_grid_gain: float
    stable_candidate_grid_coverage: float
    runtime_ms: float


def make_frame_metrics(
    frame_index: int,
    frame_name: str,
    tracks: TrackSet,
    diagnostics: TrackerDiagnostics,
    image_quality: ImageQuality,
    grid: GridStats,
    geometry: GeometryStats,
    decision: SchedulerDecision,
    runtime_ms: float,
    tracker_recovery_reason: str = "n/a",
    tracker_recovered_count: int = 0,
    track_health_score: float = float("nan"),
    track_health_reason: str = "n/a",
    frontend_state_score: float = float("nan"),
    frontend_state_reason: str = "n/a",
    semidense_acceptance: str = "n/a",
    geometry_safe_acceptance: str = "n/a",
    learned_mode_before_sparse_homography: str = "n/a",
    learned_mode_after_sparse_homography: str = "n/a",
    base_learned_mode_before_sparse_override: str = "n/a",
    learned_mode_after_sparse_override: str = "n/a",
    learned_mode_sparse_homography_allowed: bool = False,
    learned_mode_sparse_homography_reason: str = "n/a",
    last_loftr_sparse_homography_check_allowed: bool = False,
    last_loftr_sparse_homography_check_reason: str = "n/a",
    loftr_sparse_homography_allowed: bool = False,
    loftr_sparse_homography_reason: str = "n/a",
    semidense_raw_candidates: int = 0,
    semidense_post_validate_candidates: int = 0,
    semidense_accepted_candidates: int = 0,
    semidense_queued_pending: int = 0,
    semidense_grid_gain: float = float("nan"),
    semidense_new_cell_ratio: float = float("nan"),
    semidense_before_f_inlier: float = float("nan"),
    semidense_after_f_inlier: float = float("nan"),
    semidense_before_h_inlier: float = float("nan"),
    semidense_after_h_inlier: float = float("nan"),
    semidense_before_epipolar: float = float("nan"),
    semidense_after_epipolar: float = float("nan"),
    semidense_before_homography: float = float("nan"),
    semidense_after_homography: float = float("nan"),
    pending_loftr_count: int = 0,
    pending_loftr_age_median: float = float("nan"),
    loftr_confirmed_promoted: int = 0,
    klt_degeneracy_loftr_allowed: bool = False,
    klt_degeneracy_loftr_reason: str = "n/a",
    klt_degeneracy_loftr_score: float = 0.0,
    candidate_bank_count: int = 0,
    candidate_bank_coverage: float = 0.0,
    candidate_bank_grid_gain: float = 0.0,
    stable_candidate_grid_coverage: float = 0.0,
    adaptive_geometry_model: str = "n/a",
) -> FrameMetrics:
    ages = tracks.ages.astype(np.float32) if len(tracks) else np.empty((0,), dtype=np.float32)
    qualities = tracks.qualities.astype(np.float32) if len(tracks) else np.empty((0,), dtype=np.float32)
    sigmas = quality_to_sigma(qualities) if len(qualities) else np.empty((0,), dtype=np.float32)
    local_texture = tracks.local_texture.astype(np.float32) if len(tracks) else np.empty((0,), dtype=np.float32)
    return FrameMetrics(
        frame_index=frame_index,
        frame_name=frame_name,
        num_features=len(tracks),
        added_features=diagnostics.added_features,
        dropped_features=diagnostics.dropped_features,
        dropout_ratio=(
            float(diagnostics.dropped_features / diagnostics.tracked_before_filter)
            if diagnostics.tracked_before_filter > 0
            else 0.0
        ),
        tracked_before_filter=diagnostics.tracked_before_filter,
        tracked_after_filter=diagnostics.tracked_after_filter,
        grid_coverage=grid.coverage,
        grid_occupied=grid.occupied,
        grid_total=grid.total,
        median_track_age=_median(ages),
        mean_track_age=_mean(ages),
        long_track_ratio=float(np.mean(ages >= 5)) if len(ages) else 0.0,
        median_fb_error=diagnostics.median_fb_error,
        median_ncc=diagnostics.median_ncc,
        median_quality=_median(qualities),
        mean_quality=_mean(qualities),
        median_visual_sigma=_median(sigmas),
        mean_visual_sigma=_mean(sigmas),
        low_texture_feature_ratio=float(np.mean(local_texture < 0.25)) if len(local_texture) else 0.0,
        low_texture_track_age_median=_median(ages[local_texture < 0.25]) if len(local_texture) else float("nan"),
        low_texture_quality_median=_median(qualities[local_texture < 0.25]) if len(local_texture) else float("nan"),
        mean_intensity=image_quality.mean_intensity,
        contrast=image_quality.contrast,
        gradient_mean=image_quality.gradient_mean,
        laplacian_var=image_quality.laplacian_var,
        underexposed_ratio=image_quality.underexposed_ratio,
        overexposed_ratio=image_quality.overexposed_ratio,
        illumination_nonuniformity=image_quality.illumination_nonuniformity,
        local_contrast=image_quality.local_contrast,
        flat_region_ratio=image_quality.flat_region_ratio,
        texture_score=image_quality.texture_score,
        blur_score=image_quality.blur_score,
        exposure_score=image_quality.exposure_score,
        contrast_score=image_quality.contrast_score,
        illumination_score=image_quality.illumination_score,
        backscatter_score=image_quality.backscatter_score,
        highlight_shadow_score=image_quality.highlight_shadow_score,
        grid_texture_score=image_quality.grid_texture_score,
        underwater_score=image_quality.underwater_score,
        degradation_score=image_quality.degradation_score,
        image_quality=image_quality.global_score,
        fundamental_inlier_ratio=geometry.fundamental_inlier_ratio,
        homography_inlier_ratio=geometry.homography_inlier_ratio,
        median_epipolar_error=geometry.median_epipolar_error,
        median_homography_error=geometry.median_homography_error,
        planar_score=geometry.planar_score,
        tracker_mode=_tracker_mode(tracks, tracker_recovery_reason),
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
        base_learned_mode_before_sparse_override=(
            base_learned_mode_before_sparse_override
            if base_learned_mode_before_sparse_override != "n/a"
            else learned_mode_before_sparse_homography
        ),
        learned_mode_after_sparse_override=(
            learned_mode_after_sparse_override
            if learned_mode_after_sparse_override != "n/a"
            else learned_mode_after_sparse_homography
        ),
        learned_mode_sparse_homography_allowed=bool(learned_mode_sparse_homography_allowed),
        learned_mode_sparse_homography_reason=learned_mode_sparse_homography_reason,
        last_loftr_sparse_homography_check_allowed=bool(last_loftr_sparse_homography_check_allowed),
        last_loftr_sparse_homography_check_reason=last_loftr_sparse_homography_check_reason,
        loftr_sparse_homography_allowed=bool(loftr_sparse_homography_allowed),
        loftr_sparse_homography_reason=loftr_sparse_homography_reason,
        semidense_raw_candidates=int(semidense_raw_candidates),
        semidense_post_validate_candidates=int(semidense_post_validate_candidates),
        semidense_accepted_candidates=int(semidense_accepted_candidates),
        semidense_queued_pending=int(semidense_queued_pending),
        semidense_grid_gain=float(semidense_grid_gain),
        semidense_new_cell_ratio=float(semidense_new_cell_ratio),
        semidense_before_f_inlier=float(semidense_before_f_inlier),
        semidense_after_f_inlier=float(semidense_after_f_inlier),
        semidense_before_h_inlier=float(semidense_before_h_inlier),
        semidense_after_h_inlier=float(semidense_after_h_inlier),
        semidense_before_epipolar=float(semidense_before_epipolar),
        semidense_after_epipolar=float(semidense_after_epipolar),
        semidense_before_homography=float(semidense_before_homography),
        semidense_after_homography=float(semidense_after_homography),
        pending_loftr_count=int(pending_loftr_count),
        pending_loftr_age_median=float(pending_loftr_age_median),
        loftr_confirmed_promoted=int(loftr_confirmed_promoted),
        klt_degeneracy_loftr_allowed=bool(klt_degeneracy_loftr_allowed),
        klt_degeneracy_loftr_reason=klt_degeneracy_loftr_reason,
        klt_degeneracy_loftr_score=float(klt_degeneracy_loftr_score),
        scheduler_mode=decision.mode,
        scheduler_reason=decision.reason,
        geometry_mode=decision.geometry_mode,
        geometry_reason=decision.geometry_reason,
        planar_confidence=decision.planar_confidence,
        adaptive_geometry_model=adaptive_geometry_model,
        klt_tracks=_source_count(tracks, "klt"),
        gftt_tracks=_source_count(tracks, "gftt"),
        orb_tracks=_source_count(tracks, "orb"),
        orb_match_tracks=_source_count(tracks, "orb_match"),
        orb_recovery_tracks=_source_count(tracks, "orb_recovery"),
        lk_recovery_tracks=_source_count(tracks, "lk_recovery"),
        homography_recovery_tracks=_source_count(tracks, "homography_recovery"),
        xfeat_tracks=_source_count(tracks, "xfeat"),
        xfeat_recovery_tracks=_source_count(tracks, "xfeat_recovery"),
        xfeat_init_tracks=_source_count(tracks, "xfeat_init"),
        xfeat_confirmed_tracks=_source_count(tracks, "xfeat_confirmed"),
        xfeat_star_tracks=_source_count(tracks, "xfeat_star"),
        xfeat_star_recovery_tracks=_source_count(tracks, "xfeat_star_recovery"),
        xfeat_star_init_tracks=_source_count(tracks, "xfeat_star_init"),
        xfeat_star_confirmed_tracks=_source_count(tracks, "xfeat_star_confirmed"),
        superpoint_lightglue_tracks=_source_count(tracks, "superpoint_lightglue"),
        superpoint_lightglue_recovery_tracks=_source_count(tracks, "superpoint_lightglue_recovery"),
        superpoint_lightglue_init_tracks=_source_count(tracks, "superpoint_lightglue_init"),
        superpoint_lightglue_confirmed_tracks=_source_count(tracks, "superpoint_lightglue_confirmed"),
        learned_memory_tracks=_source_suffix_count(tracks, "_memory"),
        loftr_tracks=_source_count(tracks, "loftr"),
        loftr_recovery_tracks=_source_count(tracks, "loftr_recovery"),
        loftr_init_tracks=_source_count(tracks, "loftr_init"),
        loftr_confirmed_tracks=_source_count(tracks, "loftr_confirmed"),
        candidate_bank_count=int(candidate_bank_count),
        candidate_bank_coverage=float(candidate_bank_coverage),
        candidate_bank_grid_gain=float(candidate_bank_grid_gain),
        stable_candidate_grid_coverage=float(stable_candidate_grid_coverage),
        runtime_ms=runtime_ms,
    )


def metrics_to_dict(metrics: FrameMetrics) -> dict[str, Any]:
    return asdict(metrics)


def draw_tracks(image: np.ndarray, tracks: TrackSet, output_path: str | Path) -> None:
    if image.ndim == 2:
        canvas = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        canvas = image.copy()
    for idx, (prev_pt, cur_pt) in enumerate(zip(tracks.prev_points, tracks.points)):
        q = float(tracks.qualities[idx]) if idx < len(tracks.qualities) else 0.0
        color = (0, int(255 * q), int(255 * (1.0 - q)))
        p0 = tuple(np.round(prev_pt).astype(int))
        p1 = tuple(np.round(cur_pt).astype(int))
        cv2.line(canvas, p0, p1, color, 1, cv2.LINE_AA)
        cv2.circle(canvas, p1, 2, color, -1, cv2.LINE_AA)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), canvas)


def _median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))


def _mean(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmean(values))


def _source_count(tracks: TrackSet, source: str) -> int:
    if source == "gftt":
        aliases = {"gftt", "gftt_confirmed", "gftt_seed"}
        return int(sum(1 for item in tracks.sources if item in aliases))
    return int(sum(1 for item in tracks.sources if item == source))


def _source_suffix_count(tracks: TrackSet, suffix: str) -> int:
    return int(sum(1 for item in tracks.sources if str(item).endswith(suffix)))


def _tracker_mode(tracks: TrackSet, reason: str) -> str:
    sources = set(tracks.sources)
    learned_recovery_sources = {
        "xfeat_recovery",
        "xfeat_star_recovery",
        "superpoint_lightglue_recovery",
        "xfeat_recovery_memory",
        "xfeat_star_recovery_memory",
        "superpoint_lightglue_recovery_memory",
        "loftr_recovery_memory",
    }
    if "loftr_recovery" in sources:
        return "loftr_fallback"
    learned_init_sources = {
        "xfeat_init",
        "xfeat_star_init",
        "superpoint_lightglue_init",
        "loftr_init",
        "xfeat_confirmed",
        "xfeat_star_confirmed",
        "superpoint_lightglue_confirmed",
        "loftr_confirmed",
    }
    if sources & learned_recovery_sources:
        return "learned_recovery"
    if sources & learned_init_sources:
        return "learned_initialization"
    if "homography_recovery" in sources:
        return "homography_recovery"
    if "lk_recovery" in sources or "orb_recovery" in sources:
        return "classical_recovery"
    if reason not in {"n/a", "init", "reset", "healthy"}:
        return "trigger_no_recovery"
    return "klt"
