from __future__ import annotations

from dataclasses import dataclass
import math

from uw_frontend.geometry.grid import GridStats
from uw_frontend.geometry.validation import GeometryStats
from uw_frontend.quality.image_quality import ImageQuality
from uw_frontend.tracking.track_state import TrackerDiagnostics


@dataclass
class GeometryModeConfig:
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


@dataclass
class GeometryModeDecision:
    mode: str
    reason: str
    planar_confidence: float


def classify_geometry_mode(
    image_quality: ImageQuality,
    grid: GridStats,
    geometry: GeometryStats,
    diagnostics: TrackerDiagnostics,
    num_tracks: int,
    config: GeometryModeConfig | None = None,
) -> GeometryModeDecision:
    cfg = config or GeometryModeConfig()
    dropout_ratio = (
        diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
        if diagnostics.tracked_before_filter > 0
        else 0.0
    )
    planar_confidence = _planar_confidence(image_quality, geometry, cfg)

    severe_reasons: list[str] = []
    if image_quality.global_score <= cfg.severe_max_image_quality:
        severe_reasons.append("very_low_image_quality")
    if image_quality.texture_score <= cfg.severe_max_texture_score:
        severe_reasons.append("very_low_texture")
    if image_quality.flat_region_ratio >= cfg.severe_min_flat_region_ratio:
        severe_reasons.append("mostly_flat")
    if grid.coverage <= cfg.severe_max_grid_coverage:
        severe_reasons.append("poor_grid_coverage")
    if num_tracks < 80:
        severe_reasons.append("few_tracks")
    if len(severe_reasons) >= 2:
        return GeometryModeDecision("severe_low_texture", "+".join(severe_reasons), planar_confidence)

    if _is_planar_near_wall(image_quality, geometry, cfg, planar_confidence, dropout_ratio):
        reasons = [
            "homography_consistent",
            "flat_or_low_grid_texture",
        ]
        if geometry.planar_score >= cfg.planar_min_score:
            reasons.append("planar_score")
        return GeometryModeDecision("planar_near_wall", "+".join(reasons), planar_confidence)

    degraded_reasons: list[str] = []
    if image_quality.texture_score <= cfg.degraded_max_texture_score:
        degraded_reasons.append("low_texture")
    if image_quality.global_score <= cfg.degraded_max_image_quality:
        degraded_reasons.append("low_image_quality")
    if image_quality.degradation_score >= cfg.degraded_min_degradation_score:
        degraded_reasons.append("underwater_degradation")
    if dropout_ratio >= cfg.degraded_max_dropout_ratio:
        degraded_reasons.append("high_dropout")
    if degraded_reasons:
        return GeometryModeDecision("degraded_texture", "+".join(degraded_reasons), planar_confidence)

    return GeometryModeDecision("normal", "healthy", planar_confidence)


def _is_planar_near_wall(
    image_quality: ImageQuality,
    geometry: GeometryStats,
    cfg: GeometryModeConfig,
    planar_confidence: float,
    dropout_ratio: float,
) -> bool:
    if dropout_ratio > cfg.planar_max_dropout_ratio:
        return False
    if geometry.num_pairs < cfg.planar_min_pairs:
        return False
    if geometry.homography_inlier_ratio < cfg.planar_min_h_inlier_ratio:
        return False
    if geometry.median_homography_error == geometry.median_homography_error:
        if geometry.median_homography_error > cfg.planar_max_h_error:
            return False
    if planar_confidence < cfg.planar_min_confidence:
        return False
    homography_score = _homography_score(geometry, cfg)
    if homography_score < cfg.planar_min_homography_score:
        return False
    return (
        image_quality.flat_region_ratio >= cfg.planar_min_flat_region_ratio
        or image_quality.grid_texture_score <= cfg.planar_max_grid_texture_score
    )


def _planar_confidence(
    image_quality: ImageQuality,
    geometry: GeometryStats,
    cfg: GeometryModeConfig,
) -> float:
    if geometry.num_pairs <= 0:
        return 0.0
    h_term = _clip01((geometry.homography_inlier_ratio - 0.55) / 0.40)
    score_term = _clip01(geometry.planar_score / max(1e-6, cfg.planar_min_score))
    flat_term = _clip01(image_quality.flat_region_ratio / max(1e-6, cfg.planar_min_flat_region_ratio))
    texture_term = _clip01((cfg.planar_max_grid_texture_score - image_quality.grid_texture_score + 0.20) / 0.55)
    if geometry.median_homography_error == geometry.median_homography_error:
        error_term = _clip01(1.0 - geometry.median_homography_error / max(1e-6, cfg.planar_max_h_error))
    else:
        error_term = 0.0
    return float(
        _clip01(
            0.35 * h_term
            + 0.20 * score_term
            + 0.20 * flat_term
            + 0.15 * texture_term
            + 0.10 * error_term
        )
    )


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _homography_score(geometry: GeometryStats, cfg: GeometryModeConfig) -> float:
    if geometry.median_homography_error == geometry.median_homography_error:
        return float(math.exp(-max(0.0, geometry.median_homography_error) / 5.0))
    return 0.0
