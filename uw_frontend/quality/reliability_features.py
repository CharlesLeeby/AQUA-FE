from __future__ import annotations

import numpy as np

from uw_frontend.geometry.grid import GridStats
from uw_frontend.geometry.validation import GeometryStats
from uw_frontend.quality.image_quality import ImageQuality
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


RELIABILITY_FEATURE_NAMES = [
    "base_quality",
    "track_age_norm",
    "fb_score",
    "ncc_score",
    "local_texture",
    "image_quality",
    "texture_score",
    "blur_score",
    "contrast_score",
    "illumination_score",
    "backscatter_score",
    "highlight_shadow_score",
    "grid_texture_score",
    "degradation_inv",
    "flat_region_inv",
    "grid_coverage",
    "dropout_inv",
    "f_inlier_ratio",
    "h_inlier_ratio",
    "epipolar_score",
    "homography_score",
    "source_klt",
    "source_gftt",
    "source_lk_recovery",
    "source_homography_recovery",
    "source_orb_recovery",
    "source_learned_recovery",
    "source_learned_init",
]


def build_reliability_features(
    tracks: TrackSet,
    image_quality: ImageQuality,
    grid: GridStats,
    geometry: GeometryStats,
    diagnostics: TrackerDiagnostics,
) -> tuple[np.ndarray, np.ndarray]:
    if len(tracks) == 0:
        return (
            np.empty((0, len(RELIABILITY_FEATURE_NAMES)), dtype=np.float32),
            np.empty((0,), dtype=np.float32),
        )
    base_quality = np.clip(tracks.qualities.astype(np.float32), 0.0, 1.0)
    ages = tracks.ages.astype(np.float32)
    fb = tracks.fb_errors.astype(np.float32)
    ncc = tracks.ncc_scores.astype(np.float32)
    local_texture = np.clip(tracks.local_texture.astype(np.float32), 0.0, 1.0)
    dropout_ratio = (
        diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
        if diagnostics.tracked_before_filter > 0
        else 0.0
    )
    source = np.asarray(tracks.sources, dtype=object)
    learned_recovery = np.asarray([item.endswith("_recovery") and item not in {"lk_recovery", "orb_recovery"} for item in source], dtype=np.float32)
    learned_init = np.asarray([item.endswith("_init") for item in source], dtype=np.float32)
    cols = [
        base_quality,
        np.clip(ages / 30.0, 0.0, 1.0),
        np.exp(-np.clip(fb, 0.0, 20.0) / 3.0),
        np.clip((ncc + 1.0) * 0.5, 0.0, 1.0),
        local_texture,
        _full(len(tracks), image_quality.global_score),
        _full(len(tracks), image_quality.texture_score),
        _full(len(tracks), image_quality.blur_score),
        _full(len(tracks), image_quality.contrast_score),
        _full(len(tracks), image_quality.illumination_score),
        _full(len(tracks), image_quality.backscatter_score),
        _full(len(tracks), image_quality.highlight_shadow_score),
        _full(len(tracks), image_quality.grid_texture_score),
        _full(len(tracks), 1.0 - image_quality.degradation_score),
        _full(len(tracks), 1.0 - image_quality.flat_region_ratio),
        _full(len(tracks), grid.coverage),
        _full(len(tracks), 1.0 - dropout_ratio),
        _full(len(tracks), geometry.fundamental_inlier_ratio),
        _full(len(tracks), geometry.homography_inlier_ratio),
        _full(len(tracks), _residual_score(geometry.median_epipolar_error, 3.0)),
        _full(len(tracks), _residual_score(geometry.median_homography_error, 5.0)),
        (source == "klt").astype(np.float32),
        (source == "gftt").astype(np.float32),
        (source == "lk_recovery").astype(np.float32),
        (source == "homography_recovery").astype(np.float32),
        (source == "orb_recovery").astype(np.float32),
        learned_recovery,
        learned_init,
    ]
    features = np.stack(cols, axis=1).astype(np.float32)
    return features, base_quality


def _full(count: int, value: float) -> np.ndarray:
    if value != value:
        value = 0.0
    return np.full((count,), np.clip(float(value), 0.0, 1.0), dtype=np.float32)


def _residual_score(value: float, scale: float) -> float:
    if value != value:
        return 0.0
    return float(np.exp(-max(0.0, float(value)) / max(1e-6, float(scale))))
