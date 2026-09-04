from __future__ import annotations

from dataclasses import dataclass

from uw_frontend.geometry.grid import GridStats
from uw_frontend.geometry.mode import GeometryModeConfig, classify_geometry_mode
from uw_frontend.geometry.validation import GeometryStats
from uw_frontend.quality.image_quality import ImageQuality
from uw_frontend.tracking.track_state import TrackerDiagnostics


@dataclass
class SchedulerDecision:
    mode: str
    should_rematch: bool
    should_fallback: bool
    reason: str
    geometry_mode: str = "unknown"
    geometry_reason: str = "n/a"
    planar_confidence: float = 0.0


@dataclass
class SchedulerConfig:
    min_tracks: int = 80
    min_grid_coverage: float = 0.45
    min_f_inlier_ratio: float = 0.55
    min_image_quality: float = 0.25
    max_median_fb_error: float = 0.85
    max_dropout_ratio: float = 0.45
    max_degradation_score: float = 0.55
    max_flat_region_ratio: float = 0.90
    max_illumination_nonuniformity: float = 0.48
    min_backscatter_score: float = 0.43
    min_grid_texture_score: float = 0.10
    planar_min_pairs: int = 40
    planar_min_h_inlier_ratio: float = 0.94
    planar_max_h_error: float = 2.5
    planar_min_score: float = 0.95
    planar_min_flat_region_ratio: float = 0.85
    planar_max_grid_texture_score: float = 0.15
    planar_min_confidence: float = 0.86
    planar_min_homography_score: float = 0.90
    planar_max_dropout_ratio: float = 0.20
    severe_max_image_quality: float = 0.20
    severe_max_texture_score: float = 0.245
    severe_min_flat_region_ratio: float = 0.90
    severe_max_grid_coverage: float = 0.55
    degraded_max_texture_score: float = 0.38
    degraded_max_image_quality: float = 0.32
    degraded_min_degradation_score: float = 0.50
    degraded_max_dropout_ratio: float = 0.40


class HybridScheduler:
    """Quality-driven policy used for frontend logging and learned rematching."""

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self.config = config or SchedulerConfig()

    def decide(
        self,
        image_quality: ImageQuality,
        grid: GridStats,
        geometry: GeometryStats,
        diagnostics: TrackerDiagnostics,
        num_tracks: int,
    ) -> SchedulerDecision:
        geometry_mode = classify_geometry_mode(
            image_quality,
            grid,
            geometry,
            diagnostics,
            num_tracks,
            GeometryModeConfig(
                planar_min_pairs=self.config.planar_min_pairs,
                planar_min_h_inlier_ratio=self.config.planar_min_h_inlier_ratio,
                planar_max_h_error=self.config.planar_max_h_error,
                planar_min_score=self.config.planar_min_score,
                planar_min_flat_region_ratio=self.config.planar_min_flat_region_ratio,
                planar_max_grid_texture_score=self.config.planar_max_grid_texture_score,
                planar_min_confidence=self.config.planar_min_confidence,
                planar_min_homography_score=self.config.planar_min_homography_score,
                planar_max_dropout_ratio=self.config.planar_max_dropout_ratio,
                severe_max_image_quality=self.config.severe_max_image_quality,
                severe_max_texture_score=self.config.severe_max_texture_score,
                severe_min_flat_region_ratio=self.config.severe_min_flat_region_ratio,
                severe_max_grid_coverage=self.config.severe_max_grid_coverage,
                degraded_max_texture_score=self.config.degraded_max_texture_score,
                degraded_max_image_quality=self.config.degraded_max_image_quality,
                degraded_min_degradation_score=self.config.degraded_min_degradation_score,
                degraded_max_dropout_ratio=self.config.degraded_max_dropout_ratio,
            ),
        )
        reasons: list[str] = []
        if num_tracks < self.config.min_tracks:
            reasons.append("low_track_count")
        if grid.coverage < self.config.min_grid_coverage:
            reasons.append("low_grid_coverage")
        if geometry.num_pairs >= 8 and geometry.fundamental_inlier_ratio < self.config.min_f_inlier_ratio:
            reasons.append("low_geometry_inlier_ratio")
        if image_quality.global_score < self.config.min_image_quality:
            reasons.append("low_image_quality")
        if image_quality.degradation_score > self.config.max_degradation_score:
            reasons.append("underwater_degradation")
        if image_quality.flat_region_ratio > self.config.max_flat_region_ratio:
            reasons.append("flat_regions")
        if image_quality.illumination_nonuniformity > self.config.max_illumination_nonuniformity:
            reasons.append("illumination_nonuniformity")
        if image_quality.backscatter_score < self.config.min_backscatter_score:
            reasons.append("backscatter_or_low_contrast")
        if image_quality.grid_texture_score < self.config.min_grid_texture_score:
            reasons.append("low_grid_texture")
        if diagnostics.median_fb_error == diagnostics.median_fb_error and diagnostics.median_fb_error > self.config.max_median_fb_error:
            reasons.append("high_fb_error")
        if diagnostics.tracked_before_filter > 0:
            dropout_ratio = diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
            if dropout_ratio > self.config.max_dropout_ratio:
                reasons.append("high_dropout")

        if not reasons:
            mode = "planar_klt" if geometry_mode.mode == "planar_near_wall" else "klt"
            return SchedulerDecision(
                mode,
                False,
                False,
                "healthy",
                geometry_mode=geometry_mode.mode,
                geometry_reason=geometry_mode.reason,
                planar_confidence=geometry_mode.planar_confidence,
            )

        severe_underwater = any(
            reason in reasons
            for reason in (
                "low_image_quality",
                "underwater_degradation",
                "flat_regions",
                "backscatter_or_low_contrast",
                "low_grid_texture",
            )
        )
        fallback = (
            geometry_mode.mode == "severe_low_texture"
            or severe_underwater
            and (
            num_tracks < self.config.min_tracks // 2
            or grid.coverage < 0.5 * self.config.min_grid_coverage
            )
        )
        if fallback:
            mode = "loftr_fallback"
        elif geometry_mode.mode == "planar_near_wall":
            mode = "homography_guided_recovery"
        else:
            mode = "learned_rematch"
        return SchedulerDecision(
            mode,
            True,
            fallback,
            "+".join(reasons),
            geometry_mode=geometry_mode.mode,
            geometry_reason=geometry_mode.reason,
            planar_confidence=geometry_mode.planar_confidence,
        )
