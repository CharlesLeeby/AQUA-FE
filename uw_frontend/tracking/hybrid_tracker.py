from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from uw_frontend.geometry.grid import grid_stats
from uw_frontend.geometry.mode import GeometryModeConfig, classify_geometry_mode
from uw_frontend.geometry.validation import GeometryStats, validate_geometry
from uw_frontend.matchers.base import BaseMatcher
from uw_frontend.quality.image_quality import (
    CellQualityMap,
    ImageQuality,
    cell_quality_at_points,
    local_texture_scores,
    score_cell_quality_map,
)
from uw_frontend.tracking.matcher_recovery import MatcherRecoveryConfig, PairwiseMatcherRecovery
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker, _patch_ncc
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


@dataclass
class _TrackMemoryEntry:
    frame_index: int
    image: np.ndarray
    points: np.ndarray
    ids: np.ndarray
    ages: np.ndarray


@dataclass
class _PendingPromotion:
    prev_image: np.ndarray
    points: np.ndarray
    ages: np.ndarray
    qualities: np.ndarray
    sources: list[str]


@dataclass
class _SourceProvenanceEntry:
    source: str
    expires_at_frame: int


@dataclass
class HybridConfig:
    min_tracks_for_recovery: int = 260
    min_grid_coverage_for_recovery: float = 0.80
    max_median_fb_for_recovery: float = 0.65
    orb_features: int = 900
    orb_fast_threshold: int = 10
    max_hamming_distance: int = 80
    lost_association_radius: float = 10.0
    min_current_distance: float = 8.0
    min_recovery_ncc: float = 0.50
    max_recovered: int = 120
    preserve_klt_replenish: bool = False
    # When enabled, newly detected classical GFTT points remain private
    # proposals until they survive the configured forward/backward KLT and
    # NCC checks on the following processed frame.  Public track IDs are
    # assigned only after that temporal confirmation.  Default-off preserves
    # the historical immediate-admission behavior.
    enable_temporal_gftt_admission: bool = False
    # Maintain private replacement proposals even while the public KLT state
    # is full.  Proposals near tracks that survive the next frame are rejected
    # by the unchanged distance gate; proposals near tracks that died may be
    # admitted only after passing the same temporal confirmation.  This avoids
    # a detect-after-death extra-frame gap without weakening any threshold.
    enable_temporal_gftt_shadow_replacement: bool = False
    # With shadow replacement enabled, merge a second proposal pool detected
    # under the historical active-track exclusion mask.  The shadow pool
    # provides immediate replacements; the masked pool preserves discovery in
    # uncovered image regions.  Both share the same pending cap and unchanged
    # grid/distance/temporal confirmation gates.
    enable_temporal_gftt_dual_pool_replenishment: bool = False
    enable_classical_recovery: bool = True
    enable_lk_recovery: bool = True
    lk_recovery_win_size: int = 31
    lk_recovery_max_level: int = 4
    lk_recovery_fb_threshold: float = 3.0
    lk_recovery_min_ncc: float = 0.35
    max_lk_recovered: int = 180
    learned_recovery: str = "none"
    learned_max_recovered: int = 120
    learned_candidate_pool_factor: int = 8
    learned_min_ncc: float = 0.45
    learned_min_confidence: float = 0.0
    learned_enable_geometry_filter: bool = True
    learned_geometry_min_tracks: int = 40
    learned_geometry_filter_mode: str = "any"
    learned_geometry_strict_min_f_inlier_ratio: float = 0.70
    learned_geometry_strict_min_h_inlier_ratio: float = 0.55
    learned_geometry_strict_max_reference_epipolar_error: float = 1.5
    learned_geometry_strict_max_reference_homography_error: float = 4.0
    learned_geometry_quality_weight: float = 0.60
    learned_max_epipolar_error: float = 2.5
    learned_max_homography_error: float = 5.0
    learned_coverage_rows: int = 4
    learned_coverage_cols: int = 6
    learned_target_cell_count: int = 10
    learned_coverage_bonus: float = 0.65
    learned_init_enable_grid_quota: bool = True
    learned_init_max_per_cell: int = 4
    learned_init_min_coverage_score: float = 0.05
    enable_learned_initialization: bool = True
    max_learned_initialized: int = 80
    learned_sidecar_max_extra: int = 0
    max_learned_init_fraction: float = 0.45
    reserve_gftt_features: int = 30
    reserve_gftt_when_grid_below: float = 0.88
    learned_init_requires_degradation: bool = True
    learned_init_critical_grid_coverage: float = 0.70
    learned_init_min_degradation: float = 0.45
    learned_init_min_flat_region_ratio: float = 0.75
    learned_init_min_grid_coverage: float = 0.86
    learned_init_on_track_churn: bool = False
    learned_init_churn_min_dropout_ratio: float = 0.60
    learned_init_churn_max_median_age: float = 2.0
    learned_init_rolling_churn: bool = False
    learned_init_rolling_churn_window: int = 3
    learned_init_rolling_churn_min_bad_frames: int = 2
    learned_init_rolling_churn_min_grid_coverage: float = 0.90
    learned_init_rolling_churn_max_long_track_ratio: float = 0.25
    enable_learned_churn_precision_gate: bool = False
    learned_churn_precision_only_on_churn: bool = True
    learned_churn_precision_min_reference_tracks: int = 40
    learned_churn_precision_max_new: int = 8
    learned_churn_precision_max_per_cell: int = 1
    learned_churn_precision_min_ncc: float = 0.58
    learned_churn_precision_max_fb_error: float = 0.80
    learned_churn_precision_max_epipolar_error: float = 0.22
    learned_churn_precision_max_homography_error: float = 0.45
    learned_churn_precision_epipolar_error_ratio: float = 1.00
    learned_churn_precision_homography_error_ratio: float = 1.03
    learned_churn_precision_epipolar_error_abs_increase: float = 0.015
    learned_churn_precision_homography_error_abs_increase: float = 0.040
    learned_init_requires_klt_confirmation: bool = False
    learned_confirmation_min_frames: int = 1
    learned_confirmation_max_pending: int = 500
    learned_confirmation_max_confirmed: int = 120
    learned_confirmation_reserve_capacity: int = 0
    learned_confirmation_preserve_new_pending: bool = False
    learned_confirmation_geometry_safe: bool = False
    promotion_default_min_quality: float = 0.08
    promotion_xfeat_min_quality: float = 0.12
    promotion_xfeat_max_fb_error: float = 1.20
    promotion_xfeat_min_ncc: float = 0.45
    promotion_xfeat_min_grid_coverage: float = 0.78
    promotion_xfeat_max_confirmed: int = 0
    promotion_lightglue_min_quality: float = 0.08
    promotion_lightglue_max_fb_error: float = 1.50
    promotion_lightglue_min_ncc: float = 0.40
    promotion_lightglue_max_confirmed: int = 0
    promotion_loftr_min_quality: float = 0.18
    promotion_loftr_max_fb_error: float = 0.90
    promotion_loftr_min_ncc: float = 0.55
    promotion_loftr_quality_scale: float = 1.0
    promotion_loftr_max_confirmed: int = 0
    promotion_loftr_max_grid_texture_score: float = 0.35
    promotion_loftr_min_flat_region_ratio: float = 0.70
    promotion_loftr_min_h_inlier_ratio: float = 0.72
    enable_semidense_fallback_initialization: bool = False
    semidense_fallback_requires_degradation: bool = True
    semidense_fallback_min_grid_coverage: float = 0.82
    semidense_fallback_min_coverage_score: float = 0.05
    semidense_fallback_max_new: int = 80
    semidense_fallback_sidecar_max_extra: int = 0
    semidense_fallback_max_fraction: float = 0.35
    semidense_fallback_reserve_gftt_features: int = 40
    semidense_fallback_min_degradation: float = 0.45
    semidense_fallback_min_flat_region_ratio: float = 0.70
    semidense_fallback_min_grid_texture_score: float = 0.12
    semidense_fallback_min_frame_gap: int = 3
    semidense_fallback_start_frame: int = 0
    semidense_fallback_cooldown_on_attempt: bool = False
    semidense_acceptance_enable: bool = True
    semidense_acceptance_min_new_tracks: int = 3
    semidense_acceptance_min_grid_gain: float = 0.02
    semidense_acceptance_min_new_cell_ratio: float = 0.45
    semidense_candidate_min_quality: float = 0.08
    semidense_candidate_min_ncc: float = 0.45
    semidense_candidate_max_fb_error: float = 1.0
    semidense_candidate_max_epipolar_error: float = 2.5
    semidense_candidate_max_homography_error: float = 5.0
    semidense_candidate_allow_low_occupancy_cell: bool = True
    semidense_acceptance_max_f_inlier_drop: float = 0.08
    semidense_acceptance_max_h_inlier_drop: float = 0.08
    semidense_acceptance_max_epipolar_error_ratio: float = 1.25
    semidense_acceptance_max_homography_error_ratio: float = 1.25
    semidense_acceptance_residual_neutral: bool = False
    semidense_acceptance_max_epipolar_error_abs_increase: float = 0.0
    semidense_acceptance_max_homography_error_abs_increase: float = 0.0
    semidense_acceptance_min_new_cells: int = 0
    semidense_acceptance_subset_on_geometry_fail: bool = False
    semidense_acceptance_subset_max_count: int = 6
    semidense_acceptance_subset_min_count: int = 3
    semidense_acceptance_subset_max_per_cell: int = 1
    semidense_use_mature_support: bool = False
    semidense_mature_support_min_age: int = 3
    loftr_requires_planar_severe: bool = True
    loftr_planar_min_h_inlier_ratio: float = 0.80
    loftr_planar_min_confidence: float = 0.55
    loftr_allow_sparse_homography: bool = False
    loftr_sparse_max_grid_coverage: float = 0.86
    loftr_sparse_min_h_inlier_ratio: float = 0.97
    loftr_sparse_min_planar_score: float = 0.98
    loftr_sparse_max_homography_error: float = 2.5
    loftr_sparse_min_median_track_age: float = 12.0
    loftr_max_epipolar_error: float = 2.0
    loftr_max_homography_error: float = 3.5
    loftr_extreme_only: bool = False
    loftr_requires_klt_degeneracy: bool = False
    loftr_extreme_max_grid_texture_score: float = 0.85
    loftr_extreme_min_flat_region_ratio: float = 0.15
    loftr_extreme_min_degradation: float = 0.24
    learned_after_orb: bool = False
    learned_before_lk_on_degradation: bool = True
    enable_learned_recovery: bool = True
    max_degradation_for_recovery: float = 0.55
    max_flat_region_ratio_for_recovery: float = 0.90
    max_illumination_nonuniformity_for_recovery: float = 0.48
    min_backscatter_score_for_recovery: float = 0.43
    min_grid_texture_score_for_recovery: float = 0.10
    enable_geometry_mode_scheduler: bool = False
    planar_recovery_prefers_lk: bool = True
    planar_min_h_inlier_ratio: float = 0.94
    planar_min_flat_region_ratio: float = 0.85
    planar_max_grid_texture_score: float = 0.15
    planar_min_confidence: float = 0.86
    planar_min_homography_score: float = 0.90
    planar_max_dropout_ratio: float = 0.20
    severe_max_texture_score: float = 0.245
    degraded_max_texture_score: float = 0.38
    enable_homography_recovery: bool = False
    homography_recovery_min_tracks: int = 35
    homography_recovery_max_error: float = 4.0
    homography_recovery_min_ncc: float = 0.45
    homography_recovery_max_fb_error: float = 2.0
    homography_recovery_max_recovered: int = 100
    homography_recovery_min_median_track_age: float = 0.0
    severe_low_texture_prefers_learned: bool = True
    q_min: float = 0.05
    enable_temporal_health_gate: bool = False
    health_history_size: int = 5
    health_min_score_for_recovery: float = 0.48
    health_drop_for_recovery: float = 0.18
    health_bad_frame_ratio_for_recovery: float = 0.60
    health_min_grid_for_learned_init: float = 0.82
    health_churn_min_dropout_ratio: float = 0.65
    health_churn_max_median_age: float = 2.0
    health_prefers_learned_before_lk: bool = True
    enable_unified_state_gate: bool = False
    state_history_size: int = 5
    state_min_score_for_recovery: float = 0.78
    state_drop_for_recovery: float = 0.12
    state_bad_frame_ratio_for_recovery: float = 0.60
    state_prefers_learned_before_lk: bool = True
    enable_geometry_safe_recovery: bool = False
    geometry_safe_apply_to_classical: bool = False
    geometry_safe_reject_weak_reference_classical: bool = False
    geometry_safe_classical_rescue_enabled: bool = False
    geometry_safe_classical_rescue_policy: str = "any"
    geometry_safe_classical_rescue_min_dropout_ratio: float = 0.10
    geometry_safe_classical_rescue_max_grid_coverage: float = 0.55
    geometry_safe_classical_rescue_max_tracks: int = 280
    geometry_safe_classical_rescue_max_backscatter_score: float = 0.43
    geometry_safe_classical_rescue_max_grid_texture_score: float = 0.35
    geometry_safe_classical_rescue_min_flat_region_ratio: float = 0.70
    geometry_safe_min_reference_tracks: int = 40
    geometry_safe_min_candidate_tracks: int = 3
    geometry_safe_max_f_inlier_drop: float = 0.02
    geometry_safe_max_h_inlier_drop: float = 0.03
    geometry_safe_max_epipolar_error_ratio: float = 1.08
    geometry_safe_max_homography_error_ratio: float = 1.15
    geometry_safe_residual_neutral: bool = False
    geometry_safe_max_epipolar_error_abs_increase: float = 0.0
    geometry_safe_max_homography_error_abs_increase: float = 0.0
    geometry_safe_min_subset_size: int = 3
    geometry_safe_subset_fractions: tuple[float, ...] = (0.75, 0.5, 0.25)
    enable_gftt_confirmation: bool = False
    gftt_confirmation_max_pending: int = 500
    gftt_confirmation_detect_factor: float = 2.0
    gftt_confirmation_enable_pending_grid_quota: bool = False
    gftt_confirmation_pending_max_per_cell: int = 40
    gftt_confirmation_enable_confirmed_grid_select: bool = False
    gftt_confirmation_max_confirmed: int = 0
    gftt_confirmation_confirmed_max_per_cell: int = 10
    gftt_confirmation_respect_max_features: bool = True
    gftt_confirmation_fb_threshold: float = 1.5
    gftt_confirmation_min_ncc: float = 0.62
    gftt_confirmation_min_distance: float = 8.0
    gftt_confirmation_min_output_tracks: int = 300
    gftt_confirmation_min_output_coverage: float = 0.65
    gftt_confirmation_immediate_max: int = 60
    gftt_confirmation_immediate_fraction: float = 0.20
    gftt_confirmation_immediate_min_texture: float = 0.12
    gftt_confirmation_immediate_max_per_cell: int = 4
    gftt_confirmation_immediate_min_grid_gain: float = 0.04
    gftt_confirmation_immediate_severe_min_tracks: int = 240
    enable_candidate_geometry_filter: bool = False
    candidate_geometry_apply_to_classical: bool = True
    candidate_geometry_apply_to_learned: bool = True
    candidate_geometry_min_reference_tracks: int = 40
    candidate_geometry_min_candidate_tracks: int = 3
    candidate_geometry_filter_mode: str = "adaptive_strict"
    candidate_geometry_strict_min_f_inlier_ratio: float = 0.78
    candidate_geometry_strict_min_h_inlier_ratio: float = 0.62
    candidate_geometry_strict_max_reference_epipolar_error: float = 1.25
    candidate_geometry_strict_max_reference_homography_error: float = 3.5
    candidate_geometry_max_epipolar_error: float = 1.8
    candidate_geometry_max_homography_error: float = 3.5
    candidate_geometry_quality_weight: float = 0.70
    enable_adaptive_birth_budget: bool = False
    adaptive_birth_min_budget: int = 8
    adaptive_birth_max_fraction: float = 0.22
    adaptive_birth_low_health_fraction: float = 0.12
    adaptive_birth_low_texture_fraction: float = 0.16
    adaptive_birth_severe_fraction: float = 0.10
    adaptive_birth_min_quality: float = 0.12
    adaptive_birth_min_cell_score: float = 0.05
    enable_learned_init_acceptance_gate: bool = False
    learned_init_acceptance_min_reference_tracks: int = 40
    learned_init_acceptance_min_quality: float = 0.08
    learned_init_acceptance_weak_max_new: int = 28
    learned_init_acceptance_weak_max_fraction: float = 0.10
    learned_init_acceptance_weak_min_grid_gain: float = 0.02
    learned_init_acceptance_weak_min_new_cell_ratio: float = 0.20
    enable_local_quality_map: bool = False
    local_quality_rows: int = 4
    local_quality_cols: int = 6
    local_quality_weight: float = 0.0
    local_quality_min_learned_score: float = 0.0
    local_quality_min_birth_score: float = 0.0
    local_quality_apply_to_candidate_scoring: bool = True
    local_quality_apply_to_output_q: bool = False
    enable_learned_track_memory: bool = False
    learned_track_memory_size: int = 3
    learned_track_memory_max_frame_gap: int = 6
    learned_track_memory_max_points: int = 500
    learned_track_memory_max_recovered: int = 80
    learned_track_memory_min_recovery_gap: int = 2
    enable_adaptive_geometry_model_selection: bool = False
    adaptive_geometry_planar_mode: str = "homography"
    adaptive_geometry_normal_mode: str = "fundamental"
    adaptive_geometry_degraded_mode: str = "adaptive_strict"
    adaptive_geometry_severe_mode: str = "homography"
    planar_new_track_quality_scale: float = 1.0
    severe_new_track_quality_scale: float = 1.0
    enable_three_layer_source_aware: bool = False
    three_layer_low_texture_max_grid_texture_score: float = 0.35
    three_layer_low_texture_min_flat_region_ratio: float = 0.65
    three_layer_low_texture_min_degradation: float = 0.42
    three_layer_extreme_max_grid_texture_score: float = 0.16
    three_layer_extreme_min_flat_region_ratio: float = 0.88
    three_layer_extreme_max_grid_coverage: float = 0.55
    source_aware_superpoint_lightglue_modes: tuple[str, ...] = (
        "low_texture",
        "identity_churn",
    )
    source_aware_xfeat_modes: tuple[str, ...] = (
        "low_texture",
        "identity_churn",
    )
    source_aware_loftr_modes: tuple[str, ...] = (
        "planar_near_wall",
        "extreme_textureless",
    )
    source_aware_loftr_min_grid_gain: float = 0.01
    source_aware_loftr_min_new_cells: int = 1
    source_aware_loftr_min_new_cell_ratio: float = 0.25
    source_aware_loftr_max_epipolar_error: float = 1.20
    source_aware_loftr_max_homography_error: float = 2.00
    source_aware_loftr_min_h_inlier_ratio: float = 0.80
    source_aware_loftr_geometry_filter_mode: str = "all"
    source_aware_loftr_requires_confirmation: bool = True
    source_aware_loftr_min_confirmation_frames: int = 3
    source_aware_learned_recovery_min_reference_tracks: int = 16
    enable_klt_degeneracy_loftr_gate: bool = False
    klt_degeneracy_loftr_max_grid_coverage: float = 0.82
    klt_degeneracy_loftr_max_track_count: int = 0
    klt_degeneracy_loftr_max_mature_track_count: int = 0
    klt_degeneracy_loftr_mature_track_min_age: int = 3
    klt_degeneracy_loftr_min_dropout_ratio: float = 0.45
    klt_degeneracy_loftr_max_median_track_age: float = 2.0
    klt_degeneracy_loftr_max_long_track_ratio: float = 0.20
    klt_degeneracy_loftr_max_frontend_state: float = 0.82
    klt_degeneracy_loftr_min_bad_signals: int = 2
    klt_degeneracy_loftr_history_size: int = 4
    klt_degeneracy_loftr_min_bad_history_ratio: float = 0.50
    klt_degeneracy_loftr_allow_degraded_texture: bool = True
    klt_degeneracy_loftr_reserve_budget: int = 12
    enable_source_provenance_memory: bool = False
    source_provenance_recovered_hold_frames: int = 16
    source_provenance_learned_hold_frames: int = 10
    source_provenance_quality_scale_recovered: float = 1.0
    source_provenance_quality_scale_learned: float = 1.0
    enable_classical_identity_safe_gate: bool = False
    classical_identity_safe_history_size: int = 5
    classical_identity_safe_min_recent_triggers: int = 2
    classical_identity_safe_max_grid_coverage: float = 0.72
    classical_identity_safe_min_dropout_ratio: float = 0.18
    classical_identity_safe_max_frontend_state: float = 0.87
    classical_identity_safe_max_track_health: float = 0.88
    classical_identity_safe_large_batch: int = 40
    classical_identity_safe_min_grid_gain: float = 0.01
    classical_identity_safe_max_fraction: float = 0.30
    classical_identity_safe_warmup_frames: int = 0


class HybridKltOrbTracker:
    """Quality-guided KLT tracker with optional pairwise matcher recovery.

    KLT carries normal frames. When track health, grid coverage, or underwater
    image quality degrades, the tracker can reorder relaxed LK, ORB, and a
    learned matcher such as XFeat, SuperPoint+LightGlue, or LoFTR.
    """

    def __init__(
        self,
        klt_config: KltConfig | None = None,
        hybrid_config: HybridConfig | None = None,
        learned_matcher: BaseMatcher | None = None,
        semidense_fallback_matcher: BaseMatcher | None = None,
    ) -> None:
        self.klt = KltTracker(klt_config)
        self.config = hybrid_config or HybridConfig()
        self.orb = cv2.ORB_create(
            nfeatures=self.config.orb_features,
            fastThreshold=self.config.orb_fast_threshold,
            edgeThreshold=15,
            patchSize=31,
        )
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.learned_matcher = learned_matcher
        self.learned_recovery = self._build_recovery(learned_matcher)
        self.semidense_fallback_matcher = semidense_fallback_matcher
        self.semidense_fallback_recovery = self._build_recovery(semidense_fallback_matcher)
        self.last_recovery_reason = "init"
        self.last_recovered_count = 0
        self.last_geometry_mode = "unknown"
        self.last_degradation_mode = "unknown"
        self.last_learned_mode = "unknown"
        self.last_adaptive_geometry_model = "disabled"
        self.last_semidense_acceptance = "none"
        self.last_geometry_safe_acceptance = "disabled"
        self.last_candidate_bank_count = 0
        self.last_candidate_bank_coverage = 0.0
        self.last_candidate_bank_grid_gain = 0.0
        self.last_stable_candidate_grid_coverage = 0.0
        self.last_learned_mode_before_sparse_homography = "unknown"
        self.last_learned_mode_after_sparse_homography = "unknown"
        self.last_learned_mode_sparse_homography_allowed = False
        self.last_learned_mode_sparse_homography_reason = "not_checked"
        self.last_loftr_sparse_homography_allowed = False
        self.last_loftr_sparse_homography_reason = "not_checked"
        self.last_semidense_raw_candidates = 0
        self.last_semidense_post_validate_candidates = 0
        self.last_semidense_accepted_candidates = 0
        self.last_semidense_queued_pending = 0
        self.last_semidense_grid_gain = float("nan")
        self.last_semidense_new_cell_ratio = float("nan")
        self.last_semidense_before_f_inlier = float("nan")
        self.last_semidense_after_f_inlier = float("nan")
        self.last_semidense_before_h_inlier = float("nan")
        self.last_semidense_after_h_inlier = float("nan")
        self.last_semidense_before_epipolar = float("nan")
        self.last_semidense_after_epipolar = float("nan")
        self.last_semidense_before_homography = float("nan")
        self.last_semidense_after_homography = float("nan")
        self.last_pending_loftr_count = 0
        self.last_pending_loftr_age_median = float("nan")
        self.last_pending_learned_count = 0
        self.last_pending_learned_age_median = float("nan")
        self.last_pending_xfeat_count = 0
        self.last_pending_xfeat_age_median = float("nan")
        self.last_loftr_confirmed_promoted = 0
        self.last_confirmed_xfeat_count = 0
        self.last_confirmed_classical_gftt_count = 0
        self.last_confirmed_learned_age_median = float("nan")
        self.last_confirmation_diagnostics: dict[str, dict[str, int]] = {}
        self.last_klt_degeneracy_loftr_allowed = False
        self.last_klt_degeneracy_loftr_reason = "init"
        self.last_klt_degeneracy_loftr_score = 0.0
        self._geometry_safe_events: list[str] = []
        self.last_track_health_score = 1.0
        self.last_track_health_reason = "healthy"
        self.last_frontend_state_score = 1.0
        self.last_frontend_state_reason = "healthy"
        self._frame_counter = 0
        self._last_semidense_fallback_frame = -10**9
        self._health_history: list[float] = []
        self._state_history: list[float] = []
        self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
        self._pending_learned_points = np.empty((0, 2), dtype=np.float32)
        self._pending_learned_promotions: list[_PendingPromotion] = []
        self._last_klt_diagnostics: TrackerDiagnostics | None = None
        self._last_image_quality: ImageQuality | None = None
        self._last_image_shape: tuple[int, int] | None = None
        self._last_cell_quality_map: CellQualityMap | None = None
        self._track_memory: list[_TrackMemoryEntry] = []
        self._last_memory_recovery_frame = -10**9
        self.last_learned_candidate_count = 0
        self.last_learned_confirmed_count = 0
        self._churn_history: list[bool] = []
        self._last_churn_update_frame = -1
        self._last_churn_decision = False
        self._source_provenance: dict[int, _SourceProvenanceEntry] = {}
        self.last_source_provenance_count = 0
        self.last_source_provenance_learned_count = 0
        self.last_source_provenance_xfeat_count = 0
        self._classical_trigger_history: list[bool] = []
        self._klt_degeneracy_loftr_history: list[bool] = []

    def reset(self) -> None:
        self.klt.reset()
        self.last_recovery_reason = "reset"
        self.last_recovered_count = 0
        self.last_geometry_mode = "unknown"
        self.last_degradation_mode = "unknown"
        self.last_learned_mode = "unknown"
        self.last_geometry_safe_acceptance = "reset"
        self.last_adaptive_geometry_model = "disabled"
        self.last_candidate_bank_count = 0
        self.last_candidate_bank_coverage = 0.0
        self.last_candidate_bank_grid_gain = 0.0
        self.last_stable_candidate_grid_coverage = 0.0
        self.last_learned_mode_before_sparse_homography = "unknown"
        self.last_learned_mode_after_sparse_homography = "unknown"
        self.last_learned_mode_sparse_homography_allowed = False
        self.last_learned_mode_sparse_homography_reason = "reset"
        self.last_loftr_sparse_homography_allowed = False
        self.last_loftr_sparse_homography_reason = "reset"
        self._reset_semidense_diagnostics()
        self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
        self._pending_learned_points = np.empty((0, 2), dtype=np.float32)
        self._pending_learned_promotions = []
        self._track_memory = []
        self._last_memory_recovery_frame = -10**9
        self._last_cell_quality_map = None
        self._last_image_shape = None
        self.last_learned_candidate_count = 0
        self.last_learned_confirmed_count = 0
        self.last_confirmed_xfeat_count = 0
        self.last_confirmed_classical_gftt_count = 0
        self.last_confirmed_learned_age_median = float("nan")
        self.last_confirmation_diagnostics = {}
        self._churn_history = []
        self._last_churn_update_frame = -1
        self._last_churn_decision = False
        self._source_provenance = {}
        self.last_source_provenance_count = 0
        self.last_source_provenance_learned_count = 0
        self.last_source_provenance_xfeat_count = 0
        self._classical_trigger_history = []
        self._klt_degeneracy_loftr_history = []
        self.last_klt_degeneracy_loftr_allowed = False
        self.last_klt_degeneracy_loftr_reason = "reset"
        self.last_klt_degeneracy_loftr_score = 0.0

    def process(self, image: np.ndarray, image_quality: ImageQuality) -> tuple[TrackSet, TrackerDiagnostics]:
        gray = image.astype(np.uint8, copy=False)
        self.last_learned_mode_before_sparse_homography = "not_checked"
        self.last_learned_mode_after_sparse_homography = "not_checked"
        self.last_learned_mode_sparse_homography_allowed = False
        self.last_learned_mode_sparse_homography_reason = "not_checked_this_frame"
        self.last_loftr_sparse_homography_allowed = False
        self.last_loftr_sparse_homography_reason = "not_checked_this_frame"
        self.last_klt_degeneracy_loftr_allowed = False
        self.last_klt_degeneracy_loftr_reason = "not_checked_this_frame"
        self.last_klt_degeneracy_loftr_score = 0.0
        self._last_image_shape = gray.shape
        cell_quality_map = self._cell_quality_map(gray)
        self._last_cell_quality_map = cell_quality_map
        prev_for_pending = self.klt.prev_image.copy() if self.klt.prev_image is not None else None
        pending_points = self._pending_gftt_points.copy()
        self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
        pending_learned_points = self._pending_learned_points.copy()
        self._pending_learned_points = np.empty((0, 2), dtype=np.float32)
        pending_learned_promotions = list(self._pending_learned_promotions)
        self._pending_learned_promotions = []
        self.last_learned_candidate_count = 0
        self.last_learned_confirmed_count = 0
        self.last_confirmed_xfeat_count = 0
        self.last_confirmed_classical_gftt_count = 0
        self.last_confirmed_learned_age_median = float("nan")
        self.last_confirmation_diagnostics = {}
        self.last_loftr_confirmed_promoted = 0
        self._reset_semidense_diagnostics()
        self._geometry_safe_events = []
        direct_klt_replenish = bool(
            self.config.preserve_klt_replenish
            and not self.config.enable_temporal_gftt_admission
        )
        tracks, diagnostics = self.klt.process(
            gray,
            image_quality,
            replenish=direct_klt_replenish,
        )
        tracks = self._apply_source_provenance(tracks)
        self._last_klt_diagnostics = diagnostics
        self._last_image_quality = image_quality
        reason = self._recovery_reason(gray, image_quality, tracks, diagnostics)
        health_reason = self._temporal_health_reason(gray, image_quality, tracks, diagnostics)
        reason = _merge_reasons(reason, health_reason)
        geometry_mode = self._geometry_mode(gray, image_quality, tracks, diagnostics)
        self.last_geometry_mode = geometry_mode
        learned_mode = self._three_layer_learned_mode(gray, image_quality, tracks, diagnostics, geometry_mode)
        self.last_degradation_mode = learned_mode
        self.last_learned_mode = learned_mode
        state_reason = self._frontend_state_reason(
            gray,
            image_quality,
            tracks,
            diagnostics,
            geometry_mode,
        )
        reason = _merge_reasons(reason, state_reason)
        self._update_classical_trigger_history(reason)
        recovered = TrackSet.empty()
        if reason != "healthy" and self.config.enable_classical_recovery:
            recovered = self._recover_lost_tracks(gray, image_quality, tracks, reason, geometry_mode)
        if len(recovered):
            tracks = KltTracker._append_tracks(tracks, recovered)
            self._append_to_klt_state(recovered)
            self._remember_source_provenance(recovered)

        memory_recovered = self._recover_lost_with_learned_memory(
            gray,
            image_quality,
            tracks,
            geometry_mode,
        )
        if len(memory_recovered):
            tracks = KltTracker._append_tracks(tracks, memory_recovered)
            self._append_to_klt_state(memory_recovered)
            self._remember_source_provenance(memory_recovered)

        learned_initialized_active = False
        learned_initialized = self._initialize_new_tracks_with_learned(gray, image_quality, tracks)
        defer_learned_for_loftr = bool(
            (
                getattr(self, "last_klt_degeneracy_loftr_allowed", False)
                or getattr(self, "last_loftr_sparse_homography_allowed", False)
            )
            and self.semidense_fallback_recovery is not None
            and self._source_family_from_matcher(self.semidense_fallback_matcher) == "loftr"
        )
        if defer_learned_for_loftr and len(learned_initialized):
            self._record_geometry_safe("learned_initialization:deferred_for_loftr_degeneracy_gate")
            learned_initialized = TrackSet.empty()
        if len(learned_initialized):
            if self.config.learned_init_requires_klt_confirmation or self._requires_source_aware_confirmation(
                learned_initialized
            ):
                self._queue_pending_learned(learned_initialized)
            else:
                learned_initialized = self._assign_fresh_klt_ids(learned_initialized)
                tracks = KltTracker._append_tracks(tracks, learned_initialized)
                self._append_to_klt_state(learned_initialized)
                self._remember_source_provenance(learned_initialized)
                learned_initialized_active = True

        semidense_initialized_active = False
        semidense_initialized = self._initialize_sparse_cells_with_semidense_fallback(
            gray,
            image_quality,
            tracks,
            geometry_mode,
        )
        if len(semidense_initialized):
            if self._requires_source_aware_confirmation(semidense_initialized):
                self._queue_pending_learned(semidense_initialized)
            else:
                semidense_initialized = self._assign_fresh_klt_ids(semidense_initialized)
                tracks = KltTracker._append_tracks(tracks, semidense_initialized)
                self._append_to_klt_state(semidense_initialized)
                self._remember_source_provenance(semidense_initialized)
                semidense_initialized_active = True

        confirmed_learned = TrackSet.empty()
        if int(self.config.learned_confirmation_min_frames) <= 1 and len(pending_learned_points) > 0:
            confirmed_learned = self._confirm_pending_gftt(
                prev_for_pending,
                gray,
                image_quality,
                tracks,
                pending_learned_points,
                source_label="learned_confirmed",
                geometry_label="learned_confirmation",
                max_confirmed=self.config.learned_confirmation_max_confirmed,
                force=True,
            )
        if pending_learned_promotions:
            advanced_learned = self._advance_pending_learned_promotions(
                pending_learned_promotions,
                gray,
                image_quality,
                tracks,
            )
            confirmed_learned = KltTracker._append_tracks(confirmed_learned, advanced_learned)
        if len(confirmed_learned):
            tracks = KltTracker._append_tracks(tracks, confirmed_learned)
            self._append_to_klt_state(confirmed_learned)
            self._remember_source_provenance(confirmed_learned)
            self.last_learned_confirmed_count = len(confirmed_learned)
            self.last_confirmed_xfeat_count = int(
                sum(1 for source in confirmed_learned.sources if _source_family_name(source) == "xfeat")
            )
            self.last_confirmed_classical_gftt_count = int(
                sum(
                    1
                    for source in confirmed_learned.sources
                    if _source_family_name(source) == "classical_gftt"
                )
            )
            self.last_confirmed_learned_age_median = float(
                np.median(confirmed_learned.ages.astype(np.float32))
            )
            self.last_loftr_confirmed_promoted = int(
                sum(1 for source in confirmed_learned.sources if _source_family_name(source) == "loftr")
            )

        confirmed_gftt = self._confirm_pending_gftt(
            prev_for_pending,
            gray,
            image_quality,
            tracks,
            pending_points,
            source_label="gftt_confirmed",
            geometry_label="gftt_confirmation",
        )
        if len(confirmed_gftt):
            tracks = KltTracker._append_tracks(tracks, confirmed_gftt)
            self._append_to_klt_state(confirmed_gftt)
            self._remember_source_provenance(confirmed_gftt)

        added = (
            TrackSet.empty()
            if direct_klt_replenish
            else self._replenish_new_tracks(gray, image_quality, tracks, geometry_mode)
        )
        if len(added):
            tracks = KltTracker._append_tracks(tracks, added)

        tracks = self._apply_local_quality_to_output_tracks(tracks, gray, image_quality)
        self._prune_source_provenance(tracks.ids)

        dropped_after_recovery = max(0, diagnostics.dropped_features - len(recovered))
        merged_diagnostics = TrackerDiagnostics(
            added_features=(
                diagnostics.added_features
                + len(recovered)
                + len(memory_recovered)
                + len(learned_initialized)
                + len(semidense_initialized)
                + len(confirmed_learned)
                + len(confirmed_gftt)
                + len(added)
            ),
            dropped_features=dropped_after_recovery,
            tracked_before_filter=diagnostics.tracked_before_filter,
            tracked_after_filter=diagnostics.tracked_after_filter
            + len(recovered)
            + len(memory_recovered)
            + (len(learned_initialized) if learned_initialized_active else 0)
            + len(confirmed_learned)
            + (len(semidense_initialized) if semidense_initialized_active else 0),
            median_fb_error=_median(tracks.fb_errors),
            median_ncc=_median(tracks.ncc_scores),
            median_quality=_median(tracks.qualities),
        )
        self.klt.prev_image = gray.copy()
        self.last_recovery_reason = reason
        self.last_recovered_count = (
            len(recovered)
            + len(memory_recovered)
            + (len(learned_initialized) if learned_initialized_active else 0)
            + (len(semidense_initialized) if semidense_initialized_active else 0)
            + len(confirmed_learned)
        )
        if self._geometry_safe_events:
            self.last_geometry_safe_acceptance = ";".join(self._geometry_safe_events)
        elif self.config.enable_geometry_safe_recovery:
            self.last_geometry_safe_acceptance = "not_triggered"
        self.last_pending_learned_count = self._pending_total_count()
        self.last_pending_learned_age_median = self._pending_total_age_median()
        self.last_pending_xfeat_count = self._pending_source_count("xfeat")
        self.last_pending_xfeat_age_median = self._pending_source_age_median("xfeat")
        self.last_pending_loftr_count = self._pending_source_count("loftr")
        self.last_pending_loftr_age_median = self._pending_source_age_median("loftr")
        self._update_source_provenance_diagnostics()
        self._update_track_memory(gray, tracks)
        self._frame_counter += 1
        return tracks, merged_diagnostics

    def _reset_semidense_diagnostics(self) -> None:
        self.last_semidense_raw_candidates = 0
        self.last_semidense_post_validate_candidates = 0
        self.last_semidense_accepted_candidates = 0
        self.last_semidense_queued_pending = 0
        self.last_semidense_grid_gain = float("nan")
        self.last_semidense_new_cell_ratio = float("nan")
        self.last_semidense_before_f_inlier = float("nan")
        self.last_semidense_after_f_inlier = float("nan")
        self.last_semidense_before_h_inlier = float("nan")
        self.last_semidense_after_h_inlier = float("nan")
        self.last_semidense_before_epipolar = float("nan")
        self.last_semidense_after_epipolar = float("nan")
        self.last_semidense_before_homography = float("nan")
        self.last_semidense_after_homography = float("nan")
        self.last_pending_learned_count = self._pending_total_count()
        self.last_pending_learned_age_median = self._pending_total_age_median()
        self.last_pending_xfeat_count = self._pending_source_count("xfeat")
        self.last_pending_xfeat_age_median = self._pending_source_age_median("xfeat")
        self.last_pending_loftr_count = self._pending_source_count("loftr")
        self.last_pending_loftr_age_median = self._pending_source_age_median("loftr")

    def _pending_total_count(self) -> int:
        return int(sum(len(item.points) for item in self._pending_learned_promotions))

    def _pending_total_age_median(self) -> float:
        ages: list[int] = []
        for item in self._pending_learned_promotions:
            ages.extend(int(age) for age in item.ages)
        return float(np.median(np.asarray(ages, dtype=np.float32))) if ages else float("nan")

    def _pending_source_count(self, source_family: str) -> int:
        family = _source_family_name(source_family)
        count = 0
        for item in self._pending_learned_promotions:
            count += sum(1 for source in item.sources if _source_family_name(source) == family)
        return int(count)

    def _pending_source_age_median(self, source_family: str) -> float:
        family = _source_family_name(source_family)
        ages: list[int] = []
        for item in self._pending_learned_promotions:
            ages.extend(
                int(age)
                for age, source in zip(item.ages, item.sources)
                if _source_family_name(source) == family
            )
        return float(np.median(np.asarray(ages, dtype=np.float32))) if ages else float("nan")

    def _update_source_provenance_diagnostics(self) -> None:
        self.last_source_provenance_count = int(len(self._source_provenance))
        learned = 0
        xfeat = 0
        for entry in self._source_provenance.values():
            source_l = str(entry.source).lower()
            is_learned = any(
                token in source_l
                for token in ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense", "confirmed")
            )
            if is_learned:
                learned += 1
            if "xfeat" in source_l:
                xfeat += 1
        self.last_source_provenance_learned_count = int(learned)
        self.last_source_provenance_xfeat_count = int(xfeat)

    def _build_recovery(self, matcher: BaseMatcher | None) -> PairwiseMatcherRecovery | None:
        if matcher is None:
            return None
        return PairwiseMatcherRecovery(
            matcher,
            MatcherRecoveryConfig(
                lost_association_radius=self.config.lost_association_radius,
                min_current_distance=self.config.min_current_distance,
                min_ncc=self.config.learned_min_ncc,
                max_recovered=self.config.learned_max_recovered,
                candidate_pool_factor=self.config.learned_candidate_pool_factor,
                min_confidence=self.config.learned_min_confidence,
                enable_geometry_filter=self.config.learned_enable_geometry_filter,
                geometry_min_tracks=self.config.learned_geometry_min_tracks,
                geometry_filter_mode=self.config.learned_geometry_filter_mode,
                geometry_strict_min_f_inlier_ratio=self.config.learned_geometry_strict_min_f_inlier_ratio,
                geometry_strict_min_h_inlier_ratio=self.config.learned_geometry_strict_min_h_inlier_ratio,
                geometry_strict_max_reference_epipolar_error=self.config.learned_geometry_strict_max_reference_epipolar_error,
                geometry_strict_max_reference_homography_error=self.config.learned_geometry_strict_max_reference_homography_error,
                geometry_quality_weight=self.config.learned_geometry_quality_weight,
                max_epipolar_error=self.config.learned_max_epipolar_error,
                max_homography_error=self.config.learned_max_homography_error,
                coverage_rows=self.config.learned_coverage_rows,
                coverage_cols=self.config.learned_coverage_cols,
                target_cell_count=self.config.learned_target_cell_count,
                coverage_bonus=self.config.learned_coverage_bonus,
                init_enable_grid_quota=self.config.learned_init_enable_grid_quota,
                init_max_per_cell=self.config.learned_init_max_per_cell,
                init_min_coverage_score=self.config.learned_init_min_coverage_score,
                border=self.klt.config.border,
                q_min=self.config.q_min,
                local_quality_weight=(
                    self.config.local_quality_weight
                    if self.config.enable_local_quality_map
                    and self.config.local_quality_apply_to_candidate_scoring
                    else 0.0
                ),
                local_quality_min_score=(
                    self.config.local_quality_min_learned_score
                    if self.config.enable_local_quality_map
                    and self.config.local_quality_apply_to_candidate_scoring
                    else 0.0
                ),
            ),
        )

    def _recovery_reason(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
    ) -> str:
        reasons = []
        if len(tracks) < self.config.min_tracks_for_recovery:
            reasons.append("low_track_count")
        coverage = grid_stats(tracks.points, image.shape).coverage
        if coverage < self.config.min_grid_coverage_for_recovery:
            reasons.append("low_grid_coverage")
        if image_quality.degradation_score > self.config.max_degradation_for_recovery:
            reasons.append("underwater_degradation")
        if image_quality.flat_region_ratio > self.config.max_flat_region_ratio_for_recovery:
            reasons.append("flat_regions")
        if image_quality.illumination_nonuniformity > self.config.max_illumination_nonuniformity_for_recovery:
            reasons.append("illumination_nonuniformity")
        if image_quality.backscatter_score < self.config.min_backscatter_score_for_recovery:
            reasons.append("backscatter_or_low_contrast")
        if image_quality.grid_texture_score < self.config.min_grid_texture_score_for_recovery:
            reasons.append("low_grid_texture")
        if diagnostics.median_fb_error == diagnostics.median_fb_error and diagnostics.median_fb_error > self.config.max_median_fb_for_recovery:
            reasons.append("high_fb_error")
        return "+".join(reasons) if reasons else "healthy"

    def _recover_lost_tracks(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        reason: str,
        geometry_mode: str = "unknown",
    ) -> TrackSet:
        exclude_ids: set[int] = set()
        recovered = TrackSet.empty()
        working_tracks = current_tracks

        if geometry_mode == "planar_near_wall" and self.config.enable_homography_recovery:
            homography_recovered = self._recover_lost_with_homography(cur, image_quality, working_tracks, exclude_ids)
            homography_recovered = self._accept_geometry_safe_batch(
                working_tracks,
                homography_recovered,
                "homography_recovery",
            )
            recovered = KltTracker._append_tracks(recovered, homography_recovered)
            working_tracks = KltTracker._append_tracks(working_tracks, homography_recovered)
            exclude_ids.update(int(item) for item in homography_recovered.ids)

        learned_before_lk = self._prefer_learned_before_lk(reason, geometry_mode)
        if learned_before_lk and self.config.enable_learned_recovery:
            learned_recovered = self._recover_lost_with_learned(cur, image_quality, working_tracks, exclude_ids)
            learned_recovered = self._accept_geometry_safe_batch(
                working_tracks,
                learned_recovered,
                "learned_recovery",
            )
            recovered = KltTracker._append_tracks(recovered, learned_recovered)
            working_tracks = KltTracker._append_tracks(working_tracks, learned_recovered)
            exclude_ids.update(int(item) for item in learned_recovered.ids)

        lk_recovered = self._recover_lost_with_relaxed_lk(cur, image_quality, working_tracks, exclude_ids)
        lk_recovered = self._accept_geometry_safe_batch(
            working_tracks,
            lk_recovered,
            "lk_recovery",
        )
        recovered = KltTracker._append_tracks(recovered, lk_recovered)
        working_tracks = KltTracker._append_tracks(working_tracks, lk_recovered)
        exclude_ids.update(int(item) for item in lk_recovered.ids)

        learned_between_lk_and_orb = (
            self.learned_recovery is not None
            and self.config.enable_learned_recovery
            and not learned_before_lk
            and not self.config.learned_after_orb
        )
        if learned_between_lk_and_orb:
            learned_recovered = self._recover_lost_with_learned(cur, image_quality, working_tracks, exclude_ids)
            learned_recovered = self._accept_geometry_safe_batch(
                working_tracks,
                learned_recovered,
                "learned_recovery",
            )
            recovered = KltTracker._append_tracks(recovered, learned_recovered)
            working_tracks = KltTracker._append_tracks(working_tracks, learned_recovered)
            exclude_ids.update(int(item) for item in learned_recovered.ids)

        orb_recovered = self._recover_lost_with_orb(cur, image_quality, working_tracks, exclude_ids=exclude_ids)
        orb_recovered = self._accept_geometry_safe_batch(
            working_tracks,
            orb_recovered,
            "orb_recovery",
        )
        recovered = KltTracker._append_tracks(recovered, orb_recovered)
        working_tracks = KltTracker._append_tracks(working_tracks, orb_recovered)
        exclude_ids.update(int(item) for item in orb_recovered.ids)

        learned_after_orb = (
            self.learned_recovery is not None
            and self.config.enable_learned_recovery
            and not learned_before_lk
            and self.config.learned_after_orb
        )
        if learned_after_orb:
            learned_recovered = self._recover_lost_with_learned(cur, image_quality, working_tracks, exclude_ids)
            learned_recovered = self._accept_geometry_safe_batch(
                working_tracks,
                learned_recovered,
                "learned_recovery",
            )
            recovered = KltTracker._append_tracks(recovered, learned_recovered)

        return recovered

    def _accept_geometry_safe_batch(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        source_label: str,
    ) -> TrackSet:
        candidate_tracks = self._filter_candidate_geometry(current_tracks, candidate_tracks, source_label)
        candidate_tracks = self._filter_learned_churn_precision(
            current_tracks,
            candidate_tracks,
            source_label,
        )
        if not self.config.enable_geometry_safe_recovery:
            self.last_geometry_safe_acceptance = "disabled"
            return candidate_tracks
        classical_sources = {"lk_recovery", "orb_recovery", "homography_recovery"}
        if source_label in classical_sources and not self.config.geometry_safe_apply_to_classical:
            self._record_geometry_safe(f"{source_label}:skipped_classical")
            return candidate_tracks
        if source_label in classical_sources and self._should_rescue_classical_batch(current_tracks):
            self._record_geometry_safe(f"{source_label}:rescued_classical_{len(candidate_tracks)}")
            return candidate_tracks
        if len(candidate_tracks) == 0:
            self._record_geometry_safe(f"{source_label}:empty")
            return candidate_tracks
        if len(candidate_tracks) < self.config.geometry_safe_min_candidate_tracks:
            self._record_geometry_safe(f"{source_label}:too_few_candidates")
            return candidate_tracks
        if source_label in classical_sources and not self._classical_identity_safe_accepts(
            current_tracks,
            candidate_tracks,
            source_label,
        ):
            return TrackSet.empty()

        before = _track_geometry(current_tracks)
        if before.num_pairs < self.config.geometry_safe_min_reference_tracks:
            if self.config.enable_three_layer_source_aware and source_label.startswith("learned"):
                self._record_geometry_safe(f"{source_label}:rejected_weak_reference_{before.num_pairs}")
                return TrackSet.empty()
            if source_label in classical_sources and self.config.geometry_safe_reject_weak_reference_classical:
                self._record_geometry_safe(f"{source_label}:rejected_weak_reference_{before.num_pairs}")
                return TrackSet.empty()
            self._record_geometry_safe(f"{source_label}:weak_reference")
            return candidate_tracks

        if self._geometry_safe_accepts(current_tracks, candidate_tracks):
            self._record_geometry_safe(f"{source_label}:accepted_{len(candidate_tracks)}")
            return candidate_tracks

        order = np.argsort(-candidate_tracks.qualities)
        for fraction in self.config.geometry_safe_subset_fractions:
            keep_count = int(round(len(candidate_tracks) * float(fraction)))
            keep_count = min(len(candidate_tracks), max(self.config.geometry_safe_min_subset_size, keep_count))
            if keep_count >= len(candidate_tracks):
                continue
            subset_mask = np.zeros((len(candidate_tracks),), dtype=bool)
            subset_mask[order[:keep_count]] = True
            subset = _subset_tracks(candidate_tracks, subset_mask)
            if self._geometry_safe_accepts(current_tracks, subset):
                self._record_geometry_safe(f"{source_label}:accepted_subset_{len(subset)}")
                return subset

        self._record_geometry_safe(f"{source_label}:rejected_geometry_degradation")
        return TrackSet.empty()

    def _filter_learned_churn_precision(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        source_label: str,
    ) -> TrackSet:
        if not self.config.enable_learned_churn_precision_gate:
            return candidate_tracks
        if source_label not in {"learned_initialization", "learned_confirmation", "learned_confirmed"}:
            return candidate_tracks
        if len(candidate_tracks) == 0:
            return candidate_tracks
        if self.config.learned_churn_precision_only_on_churn and not self._learned_init_track_churn(current_tracks):
            self._record_geometry_safe(f"{source_label}:churn_precision_skipped_no_churn")
            return candidate_tracks

        before = _track_geometry(current_tracks)
        if before.num_pairs < int(self.config.learned_churn_precision_min_reference_tracks):
            self._record_geometry_safe(f"{source_label}:churn_precision_rejected_weak_reference")
            return TrackSet.empty()

        valid = np.ones((len(candidate_tracks),), dtype=bool)
        valid &= candidate_tracks.ncc_scores >= float(self.config.learned_churn_precision_min_ncc)
        valid &= candidate_tracks.fb_errors <= float(self.config.learned_churn_precision_max_fb_error)

        geometry = _reference_geometry(current_tracks)
        residual_scores: list[np.ndarray] = []
        if geometry["f_mat"] is not None:
            epi = _epipolar_errors(geometry["f_mat"], candidate_tracks.prev_points, candidate_tracks.points)
            epi_limit = _residual_dynamic_limit(
                before.median_epipolar_error,
                max_error=float(self.config.learned_churn_precision_max_epipolar_error),
                max_ratio=float(self.config.learned_churn_precision_epipolar_error_ratio),
                max_abs_increase=float(self.config.learned_churn_precision_epipolar_error_abs_increase),
            )
            valid &= epi <= epi_limit
            residual_scores.append(np.exp(-epi / max(1e-6, epi_limit)).astype(np.float32))
        if geometry["h_mat"] is not None:
            hom = _homography_errors(geometry["h_mat"], candidate_tracks.prev_points, candidate_tracks.points)
            hom_limit = _residual_dynamic_limit(
                before.median_homography_error,
                max_error=float(self.config.learned_churn_precision_max_homography_error),
                max_ratio=float(self.config.learned_churn_precision_homography_error_ratio),
                max_abs_increase=float(self.config.learned_churn_precision_homography_error_abs_increase),
            )
            valid &= hom <= hom_limit
            residual_scores.append(np.exp(-hom / max(1e-6, hom_limit)).astype(np.float32))
        if not residual_scores:
            self._record_geometry_safe(f"{source_label}:churn_precision_rejected_no_model")
            return TrackSet.empty()
        if not np.any(valid):
            self._record_geometry_safe(f"{source_label}:churn_precision_rejected_all")
            return TrackSet.empty()

        candidate_tracks = _subset_tracks(candidate_tracks, valid)
        score = (
            np.clip(candidate_tracks.qualities.astype(np.float32), 0.0, 1.0)
            * (0.25 + 0.75 * np.clip(candidate_tracks.ncc_scores.astype(np.float32), 0.0, 1.0))
        )
        residual_score = np.minimum.reduce([item[valid] for item in residual_scores]).astype(np.float32)
        score *= residual_score
        image_shape = self._last_image_shape
        if image_shape is not None:
            cell_scores = _cell_need_scores(
                current_tracks.points,
                candidate_tracks.points,
                image_shape,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                target_cell_count=self.config.learned_target_cell_count,
            )
            score *= 0.35 + 0.65 * cell_scores.astype(np.float32)

        max_new = min(len(candidate_tracks), max(0, int(self.config.learned_churn_precision_max_new)))
        if max_new <= 0:
            self._record_geometry_safe(f"{source_label}:churn_precision_rejected_no_budget")
            return TrackSet.empty()
        if image_shape is not None:
            selected = _select_grid_quota_candidates(
                points=candidate_tracks.points,
                scores=score,
                image_shape=image_shape,
                max_count=max_new,
                min_distance=self.config.min_current_distance,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                max_per_cell=max(1, int(self.config.learned_churn_precision_max_per_cell)),
            )
        else:
            selected = np.argsort(-score)[:max_new].astype(np.int64)
        if len(selected) == 0:
            self._record_geometry_safe(f"{source_label}:churn_precision_rejected_selection_empty")
            return TrackSet.empty()
        keep = np.zeros((len(candidate_tracks),), dtype=bool)
        keep[selected] = True
        filtered = _subset_tracks(candidate_tracks, keep)
        if len(filtered) == len(candidate_tracks) and len(valid) == len(candidate_tracks):
            self._record_geometry_safe(f"{source_label}:churn_precision_accepted_{len(filtered)}")
        else:
            self._record_geometry_safe(f"{source_label}:churn_precision_filtered_{len(filtered)}_of_{len(valid)}")
        return filtered

    def _should_rescue_classical_batch(self, current_tracks: TrackSet) -> bool:
        if not self.config.geometry_safe_classical_rescue_enabled:
            return False
        diagnostics = getattr(self, "_last_klt_diagnostics", None)
        if diagnostics is not None and diagnostics.tracked_before_filter > 0:
            dropout_ratio = diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
        else:
            dropout_ratio = 0.0
        grid_coverage = grid_stats(
            current_tracks.points,
            self.klt.prev_image.shape if self.klt.prev_image is not None else (1, 1),
        ).coverage
        low_grid = grid_coverage <= float(self.config.geometry_safe_classical_rescue_max_grid_coverage)
        few_tracks = len(current_tracks) <= int(self.config.geometry_safe_classical_rescue_max_tracks)
        high_dropout = dropout_ratio >= float(self.config.geometry_safe_classical_rescue_min_dropout_ratio)
        image_quality = getattr(self, "_last_image_quality", None)
        underwater_degraded = False
        if image_quality is not None:
            underwater_degraded = bool(
                image_quality.backscatter_score
                <= float(self.config.geometry_safe_classical_rescue_max_backscatter_score)
                and image_quality.grid_texture_score
                <= float(self.config.geometry_safe_classical_rescue_max_grid_texture_score)
                and image_quality.flat_region_ratio
                >= float(self.config.geometry_safe_classical_rescue_min_flat_region_ratio)
            )
        policy = str(self.config.geometry_safe_classical_rescue_policy or "any").lower()
        if policy in {"underwater_degraded_with_dropout", "underwater_low_visibility"}:
            return bool(low_grid and high_dropout and underwater_degraded)
        if policy in {"all", "and"}:
            return bool(low_grid and few_tracks and high_dropout)
        if policy in {"low_grid_and_high_dropout", "grid_and_dropout"}:
            return bool(low_grid and high_dropout)
        if policy in {"few_tracks_and_high_dropout", "tracks_and_dropout"}:
            return bool(few_tracks and high_dropout)
        if policy in {"low_grid_or_few_tracks_with_dropout", "sparse_with_dropout"}:
            return bool((low_grid or few_tracks) and high_dropout)
        return bool(low_grid or few_tracks or high_dropout)

    def _update_classical_trigger_history(self, reason: str) -> None:
        if not self.config.enable_classical_identity_safe_gate:
            return
        triggered = bool(str(reason or "healthy") != "healthy")
        self._classical_trigger_history.append(triggered)
        history_size = max(1, int(self.config.classical_identity_safe_history_size))
        if len(self._classical_trigger_history) > history_size:
            self._classical_trigger_history = self._classical_trigger_history[-history_size:]

    def _classical_identity_safe_accepts(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        source_label: str,
    ) -> bool:
        if not self.config.enable_classical_identity_safe_gate:
            return True
        if len(candidate_tracks) == 0:
            return True
        image_shape = self._last_image_shape or (
            self.klt.prev_image.shape if self.klt.prev_image is not None else (1, 1)
        )
        current_grid = grid_stats(
            current_tracks.points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        merged_points = (
            np.vstack([current_tracks.points, candidate_tracks.points]).astype(np.float32)
            if len(current_tracks)
            else candidate_tracks.points.astype(np.float32)
        )
        merged_grid = grid_stats(
            merged_points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        grid_gain = float(max(0.0, merged_grid.coverage - current_grid.coverage))

        diagnostics = getattr(self, "_last_klt_diagnostics", None)
        if diagnostics is not None and diagnostics.tracked_before_filter > 0:
            dropout_ratio = float(diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter))
        else:
            dropout_ratio = 0.0
        recent_triggers = int(sum(self._classical_trigger_history))
        persistent_trigger = recent_triggers >= int(self.config.classical_identity_safe_min_recent_triggers)
        warmup_frames = int(self.config.classical_identity_safe_warmup_frames)
        warmup_min_recent = max(2, min(int(self.config.classical_identity_safe_min_recent_triggers), warmup_frames))
        warmup_trigger = (
            int(self._frame_counter) < warmup_frames
            and recent_triggers >= warmup_min_recent
        )
        severe_grid = current_grid.coverage <= float(self.config.classical_identity_safe_max_grid_coverage)
        high_dropout = dropout_ratio >= float(self.config.classical_identity_safe_min_dropout_ratio)
        low_state = float(getattr(self, "last_frontend_state_score", 1.0)) <= float(
            self.config.classical_identity_safe_max_frontend_state
        )
        low_health = float(getattr(self, "last_track_health_score", 1.0)) <= float(
            self.config.classical_identity_safe_max_track_health
        )
        large_batch = len(candidate_tracks) >= int(self.config.classical_identity_safe_large_batch)
        fraction = len(candidate_tracks) / max(1, len(current_tracks))
        fraction_ok = fraction <= float(self.config.classical_identity_safe_max_fraction) or high_dropout or low_state
        utility_ok = (
            warmup_trigger
            or persistent_trigger
            or large_batch
            or grid_gain >= float(self.config.classical_identity_safe_min_grid_gain)
            or severe_grid
            or high_dropout
            or low_state
            or low_health
        )
        trigger_ok = (
            warmup_trigger
            or persistent_trigger
            or severe_grid
            or high_dropout
            or low_state
            or low_health
            or large_batch
        )
        accepted = bool(trigger_ok and utility_ok and fraction_ok)
        if not accepted:
            self._record_geometry_safe(
                f"{source_label}:identity_safe_rejected"
                f"_recent{recent_triggers}"
                f"_drop{dropout_ratio:.3f}"
                f"_grid{current_grid.coverage:.3f}"
                f"_gain{grid_gain:.3f}"
                f"_frac{fraction:.3f}"
                f"_state{float(getattr(self, 'last_frontend_state_score', 1.0)):.3f}"
            )
            return False
        self._record_geometry_safe(
            f"{source_label}:identity_safe_accepted"
            f"_recent{recent_triggers}"
            f"_drop{dropout_ratio:.3f}"
            f"_grid{current_grid.coverage:.3f}"
            f"_gain{grid_gain:.3f}"
            f"_frac{fraction:.3f}"
        )
        return True

    def _filter_candidate_geometry(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        source_label: str,
    ) -> TrackSet:
        if not self.config.enable_candidate_geometry_filter:
            return candidate_tracks
        classical_sources = {"lk_recovery", "orb_recovery", "homography_recovery"}
        learned_sources = {
            "learned_recovery",
            "learned_initialization",
            "learned_confirmation",
            "learned_confirmed",
        }
        if source_label in classical_sources and not self.config.candidate_geometry_apply_to_classical:
            return candidate_tracks
        if source_label in learned_sources and not self.config.candidate_geometry_apply_to_learned:
            return candidate_tracks
        if len(candidate_tracks) == 0:
            return candidate_tracks
        source_family = _source_family_from_sources(candidate_tracks.sources)
        if (
            len(candidate_tracks) < self.config.candidate_geometry_min_candidate_tracks
            and not (self.config.enable_three_layer_source_aware and source_family == "loftr")
        ):
            return candidate_tracks
        mode = self._candidate_geometry_filter_mode(source_label)
        self.last_adaptive_geometry_model = mode
        max_epipolar = float(self.config.candidate_geometry_max_epipolar_error)
        max_homography = float(self.config.candidate_geometry_max_homography_error)
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            mode = str(self.config.source_aware_loftr_geometry_filter_mode)
            max_epipolar = min(max_epipolar, float(self.config.source_aware_loftr_max_epipolar_error))
            max_homography = min(max_homography, float(self.config.source_aware_loftr_max_homography_error))
            self.last_adaptive_geometry_model = mode
        if self.config.enable_adaptive_geometry_model_selection and not (
            self.config.enable_three_layer_source_aware and source_family == "loftr"
        ):
            geometry_mode = str(getattr(self, "last_geometry_mode", "unknown"))
            if geometry_mode == "planar_near_wall":
                max_homography = min(max_homography, float(self.config.homography_recovery_max_error))
            elif geometry_mode == "severe_low_texture":
                max_epipolar = min(max_epipolar, float(self.config.loftr_max_epipolar_error))
                max_homography = min(max_homography, float(self.config.loftr_max_homography_error))
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            max_epipolar = min(max_epipolar, float(self.config.source_aware_loftr_max_epipolar_error))
            max_homography = min(max_homography, float(self.config.source_aware_loftr_max_homography_error))

        valid, geometry_score, status = _candidate_geometry_mask_and_score(
            current_tracks,
            candidate_tracks.prev_points,
            candidate_tracks.points,
            min_tracks=self.config.candidate_geometry_min_reference_tracks,
            max_epipolar_error=max_epipolar,
            max_homography_error=max_homography,
            mode=mode,
            strict_min_f_inlier_ratio=self.config.candidate_geometry_strict_min_f_inlier_ratio,
            strict_min_h_inlier_ratio=self.config.candidate_geometry_strict_min_h_inlier_ratio,
            strict_max_reference_epipolar_error=self.config.candidate_geometry_strict_max_reference_epipolar_error,
            strict_max_reference_homography_error=self.config.candidate_geometry_strict_max_reference_homography_error,
        )
        if status != "filtered":
            self._record_geometry_safe(f"{source_label}:candidate_{status}")
            return candidate_tracks
        kept = int(np.sum(valid))
        if kept <= 0:
            self._record_geometry_safe(f"{source_label}:candidate_rejected_all")
            return TrackSet.empty()

        adjusted = TrackSet(
            ids=candidate_tracks.ids.copy(),
            prev_points=candidate_tracks.prev_points.copy(),
            points=candidate_tracks.points.copy(),
            ages=candidate_tracks.ages.copy(),
            fb_errors=candidate_tracks.fb_errors.copy(),
            ncc_scores=candidate_tracks.ncc_scores.copy(),
            local_texture=candidate_tracks.local_texture.copy(),
            qualities=candidate_tracks.qualities.copy(),
            sources=list(candidate_tracks.sources),
        )
        geometry_weight = np.clip(float(self.config.candidate_geometry_quality_weight), 0.0, 1.0)
        geometry_quality = (1.0 - geometry_weight) + geometry_weight * np.clip(geometry_score, 0.0, 1.0)
        adjusted.qualities = np.clip(adjusted.qualities * geometry_quality, self.config.q_min, 1.0).astype(np.float32)
        if kept == len(candidate_tracks):
            self._record_geometry_safe(f"{source_label}:candidate_accepted_all")
            return adjusted

        self._record_geometry_safe(f"{source_label}:candidate_filtered_{kept}_of_{len(candidate_tracks)}")
        return _subset_tracks(adjusted, valid)

    def _candidate_geometry_filter_mode(self, source_label: str) -> str:
        if not self.config.enable_adaptive_geometry_model_selection:
            return self.config.candidate_geometry_filter_mode
        geometry_mode = str(getattr(self, "last_geometry_mode", "unknown"))
        if geometry_mode == "planar_near_wall":
            return str(self.config.adaptive_geometry_planar_mode)
        if geometry_mode == "severe_low_texture":
            return str(self.config.adaptive_geometry_severe_mode)
        if geometry_mode == "degraded_texture":
            return str(self.config.adaptive_geometry_degraded_mode)
        return str(self.config.adaptive_geometry_normal_mode)

    def _record_geometry_safe(self, event: str) -> None:
        self._geometry_safe_events.append(event)
        self.last_geometry_safe_acceptance = event

    def _geometry_safe_accepts(self, current_tracks: TrackSet, candidate_tracks: TrackSet) -> bool:
        merged = KltTracker._append_tracks(current_tracks, candidate_tracks)
        before = _track_geometry(current_tracks)
        after = _track_geometry(merged)
        return _geometry_gate_accepts(
            before,
            after,
            max_f_drop=self.config.geometry_safe_max_f_inlier_drop,
            max_h_drop=self.config.geometry_safe_max_h_inlier_drop,
            max_epi_ratio=self.config.geometry_safe_max_epipolar_error_ratio,
            max_hom_ratio=self.config.geometry_safe_max_homography_error_ratio,
            residual_neutral=self.config.geometry_safe_residual_neutral,
            max_epi_abs_increase=self.config.geometry_safe_max_epipolar_error_abs_increase,
            max_hom_abs_increase=self.config.geometry_safe_max_homography_error_abs_increase,
        )

    def _prefer_learned_before_lk(self, reason: str, geometry_mode: str = "unknown") -> bool:
        if self.learned_recovery is None or not self.config.learned_before_lk_on_degradation:
            return False
        if self.config.enable_geometry_mode_scheduler:
            if geometry_mode == "planar_near_wall" and self.config.planar_recovery_prefers_lk:
                return False
            if geometry_mode == "severe_low_texture" and self.config.severe_low_texture_prefers_learned:
                return True
        degradation_reasons = {
            "low_image_quality",
            "underwater_degradation",
            "flat_regions",
            "illumination_nonuniformity",
            "backscatter_or_low_contrast",
            "low_grid_texture",
        }
        if self.config.health_prefers_learned_before_lk and "track_health_decline" in reason.split("+"):
            return True
        if self.config.state_prefers_learned_before_lk and bool(
            {
                "low_frontend_state",
                "frontend_state_decline",
                "persistent_low_frontend_state",
            }
            & set(reason.split("+"))
        ):
            return True
        return bool(set(reason.split("+")) & degradation_reasons)

    def _temporal_health_reason(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
    ) -> str:
        score = self._track_health_score(image, image_quality, tracks, diagnostics)
        self.last_track_health_score = score
        if not self.config.enable_temporal_health_gate:
            self.last_track_health_reason = "disabled"
            return "healthy"

        history_size = max(2, int(self.config.health_history_size))
        previous = self._health_history[-history_size:]
        self._health_history.append(score)
        if len(self._health_history) > history_size:
            self._health_history = self._health_history[-history_size:]

        reasons: list[str] = []
        if score < self.config.health_min_score_for_recovery:
            reasons.append("low_track_health")
        if self._track_identity_churn_decision(
            tracks,
            diagnostics,
            min_dropout_ratio=float(self.config.health_churn_min_dropout_ratio),
            max_median_age=float(self.config.health_churn_max_median_age),
        ):
            reasons.append("track_identity_churn")
        if previous:
            recent = previous[-max(1, min(len(previous), history_size - 1)) :]
            baseline = float(np.median(recent))
            if baseline - score >= self.config.health_drop_for_recovery:
                reasons.append("track_health_decline")
            bad_threshold = self.config.health_min_score_for_recovery
            bad_count = sum(1 for value in recent if value < bad_threshold) + int(score < bad_threshold)
            bad_ratio = bad_count / max(1, len(recent) + 1)
            if bad_ratio >= self.config.health_bad_frame_ratio_for_recovery:
                reasons.append("persistent_low_track_health")
        self.last_track_health_reason = "+".join(reasons) if reasons else "healthy"
        return self.last_track_health_reason

    def _frontend_state_reason(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
        geometry_mode: str,
    ) -> str:
        score = self._frontend_state_score(image, image_quality, tracks, diagnostics, geometry_mode)
        self.last_frontend_state_score = score
        if not self.config.enable_unified_state_gate:
            self.last_frontend_state_reason = "disabled"
            return "healthy"

        history_size = max(2, int(self.config.state_history_size))
        previous = self._state_history[-history_size:]
        self._state_history.append(score)
        if len(self._state_history) > history_size:
            self._state_history = self._state_history[-history_size:]

        reasons: list[str] = []
        if score < float(self.config.state_min_score_for_recovery):
            reasons.append("low_frontend_state")
        if previous:
            recent = previous[-max(1, min(len(previous), history_size - 1)) :]
            baseline = float(np.median(recent))
            if baseline - score >= float(self.config.state_drop_for_recovery):
                reasons.append("frontend_state_decline")
            bad_threshold = float(self.config.state_min_score_for_recovery)
            bad_count = sum(1 for value in recent if value < bad_threshold) + int(score < bad_threshold)
            bad_ratio = bad_count / max(1, len(recent) + 1)
            if bad_ratio >= float(self.config.state_bad_frame_ratio_for_recovery):
                reasons.append("persistent_low_frontend_state")

        self.last_frontend_state_reason = "+".join(reasons) if reasons else "healthy"
        return self.last_frontend_state_reason

    def _frontend_state_score(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
        geometry_mode: str,
    ) -> float:
        track_health = self._track_health_score(image, image_quality, tracks, diagnostics)
        image_score = float(
            np.clip(
                0.30 * np.clip(image_quality.global_score, 0.0, 1.0)
                + 0.20 * np.clip(1.0 - image_quality.degradation_score, 0.0, 1.0)
                + 0.15 * np.clip(1.0 - image_quality.flat_region_ratio, 0.0, 1.0)
                + 0.15 * np.clip(image_quality.backscatter_score, 0.0, 1.0)
                + 0.20 * np.clip(image_quality.grid_texture_score, 0.0, 1.0),
                0.0,
                1.0,
            )
        )
        geometry = _track_geometry(tracks)
        geometry_score = _geometry_consistency_score(geometry)
        mode = str(geometry_mode or "unknown")
        mode_score = {
            "normal": 1.0,
            "planar_near_wall": 0.92,
            "degraded_texture": 0.78,
            "severe_low_texture": 0.62,
            "disabled": 0.85,
            "unknown": 0.80,
        }.get(mode, 0.80)
        return float(
            np.clip(
                0.50 * track_health
                + 0.20 * image_score
                + 0.20 * geometry_score
                + 0.10 * mode_score,
                0.0,
                1.0,
            )
        )

    def _klt_degeneracy_loftr_allowed(
        self,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
        image_shape: tuple[int, int],
    ) -> bool:
        if not self.config.enable_klt_degeneracy_loftr_gate:
            self.last_klt_degeneracy_loftr_allowed = False
            self.last_klt_degeneracy_loftr_reason = "disabled"
            self.last_klt_degeneracy_loftr_score = 0.0
            return False
        grid = grid_stats(
            tracks.points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        ages = tracks.ages.astype(np.float32) if len(tracks) else np.empty((0,), dtype=np.float32)
        median_age = float(np.median(ages)) if len(ages) else 0.0
        long_track_ratio = float(np.mean(ages >= 5.0)) if len(ages) else 0.0
        dropout_ratio = (
            diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
            if diagnostics.tracked_before_filter > 0
            else 0.0
        )
        frontend_state = float(getattr(self, "last_frontend_state_score", 1.0))
        signals: list[str] = []
        if (
            int(self.config.klt_degeneracy_loftr_max_track_count) > 0
            and len(tracks) <= int(self.config.klt_degeneracy_loftr_max_track_count)
        ):
            signals.append(f"low_tracks:{len(tracks)}")
        mature_min_age = max(1, int(self.config.klt_degeneracy_loftr_mature_track_min_age))
        mature_count = int(np.count_nonzero(ages >= float(mature_min_age))) if len(ages) else 0
        if (
            int(self.config.klt_degeneracy_loftr_max_mature_track_count) > 0
            and mature_count <= int(self.config.klt_degeneracy_loftr_max_mature_track_count)
        ):
            signals.append(f"low_mature_tracks:{mature_count}@{mature_min_age}")
        if grid.coverage <= float(self.config.klt_degeneracy_loftr_max_grid_coverage):
            signals.append(f"low_grid:{grid.coverage:.3f}")
        if dropout_ratio >= float(self.config.klt_degeneracy_loftr_min_dropout_ratio):
            signals.append(f"high_dropout:{dropout_ratio:.3f}")
        if median_age <= float(self.config.klt_degeneracy_loftr_max_median_track_age):
            signals.append(f"short_age:{median_age:.3f}")
        if long_track_ratio <= float(self.config.klt_degeneracy_loftr_max_long_track_ratio):
            signals.append(f"low_long:{long_track_ratio:.3f}")
        if frontend_state <= float(self.config.klt_degeneracy_loftr_max_frontend_state):
            signals.append(f"low_state:{frontend_state:.3f}")

        enough_signals = len(signals) >= int(self.config.klt_degeneracy_loftr_min_bad_signals)
        history_size = max(1, int(self.config.klt_degeneracy_loftr_history_size))
        recent = self._klt_degeneracy_loftr_history[-max(0, history_size - 1) :]
        bad_ratio = (sum(1 for item in recent if item) + int(enough_signals)) / max(1, len(recent) + 1)
        persistent = bad_ratio >= float(self.config.klt_degeneracy_loftr_min_bad_history_ratio)
        allowed = bool(enough_signals and persistent)
        self._klt_degeneracy_loftr_history.append(allowed)
        if len(self._klt_degeneracy_loftr_history) > history_size:
            self._klt_degeneracy_loftr_history = self._klt_degeneracy_loftr_history[-history_size:]
        self.last_klt_degeneracy_loftr_allowed = allowed
        self.last_klt_degeneracy_loftr_score = float(bad_ratio)
        if signals:
            reason = "+".join(signals)
            if not persistent:
                reason = f"{reason}+not_persistent:{bad_ratio:.3f}"
            self.last_klt_degeneracy_loftr_reason = reason
        else:
            self.last_klt_degeneracy_loftr_reason = "healthy"
        return allowed

    def _track_health_score(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
    ) -> float:
        grid = grid_stats(tracks.points, image.shape)
        track_score = np.clip(len(tracks) / max(1.0, float(self.config.min_tracks_for_recovery)), 0.0, 1.0)
        grid_score = np.clip(
            grid.coverage / max(1e-6, float(self.config.min_grid_coverage_for_recovery)),
            0.0,
            1.0,
        )
        if diagnostics.median_fb_error == diagnostics.median_fb_error:
            fb_score = float(np.exp(-max(0.0, diagnostics.median_fb_error) / max(1e-6, self.config.max_median_fb_for_recovery)))
        else:
            fb_score = 1.0
        ncc_score = np.clip((diagnostics.median_ncc + 1.0) * 0.5, 0.0, 1.0) if diagnostics.median_ncc == diagnostics.median_ncc else 0.5
        dropout_ratio = (
            diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
            if diagnostics.tracked_before_filter > 0
            else 0.0
        )
        dropout_score = np.clip(1.0 - dropout_ratio, 0.0, 1.0)
        quality_score = np.clip(image_quality.global_score, 0.0, 1.0)
        return float(
            np.clip(
                0.22 * track_score
                + 0.24 * grid_score
                + 0.20 * dropout_score
                + 0.16 * fb_score
                + 0.10 * ncc_score
                + 0.08 * quality_score,
                0.0,
                1.0,
            )
        )

    def _geometry_mode(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
    ) -> str:
        if not self.config.enable_geometry_mode_scheduler:
            return "disabled"
        grid = grid_stats(tracks.points, image.shape)
        motion_mask = tracks.ages > 1 if len(tracks) else np.empty((0,), dtype=bool)
        if diagnostics.tracked_before_filter >= 8 and int(motion_mask.sum()) >= 8:
            geometry, _ = validate_geometry(tracks.prev_points[motion_mask], tracks.points[motion_mask])
        else:
            geometry = GeometryStats(0, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
        decision = classify_geometry_mode(
            image_quality,
            grid,
            geometry,
            diagnostics,
            len(tracks),
            GeometryModeConfig(
                planar_min_h_inlier_ratio=self.config.planar_min_h_inlier_ratio,
                planar_min_flat_region_ratio=self.config.planar_min_flat_region_ratio,
                planar_max_grid_texture_score=self.config.planar_max_grid_texture_score,
                planar_min_confidence=self.config.planar_min_confidence,
                planar_min_homography_score=self.config.planar_min_homography_score,
                planar_max_dropout_ratio=self.config.planar_max_dropout_ratio,
                severe_max_texture_score=self.config.severe_max_texture_score,
                degraded_max_texture_score=self.config.degraded_max_texture_score,
            ),
        )
        if decision.mode == "planar_near_wall":
            if geometry.homography_inlier_ratio < self.config.planar_min_h_inlier_ratio:
                return "degraded_texture"
            planar_texture = (
                image_quality.flat_region_ratio >= self.config.planar_min_flat_region_ratio
                or image_quality.grid_texture_score <= self.config.planar_max_grid_texture_score
            )
            if not planar_texture:
                return "degraded_texture"
        return decision.mode

    def _three_layer_learned_mode(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
        geometry_mode: str,
    ) -> str:
        if not self.config.enable_three_layer_source_aware:
            self.last_learned_mode_before_sparse_homography = "disabled"
            self.last_learned_mode_after_sparse_homography = (
                geometry_mode if geometry_mode not in {"disabled", "unknown"} else "normal"
            )
            self.last_learned_mode_sparse_homography_allowed = False
            self.last_learned_mode_sparse_homography_reason = "three_layer_disabled"
            return geometry_mode if geometry_mode not in {"disabled", "unknown"} else "normal"
        grid = grid_stats(
            tracks.points,
            image.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        mode_before_sparse = "normal"
        klt_degenerate_for_loftr = self._klt_degeneracy_loftr_allowed(
            tracks,
            diagnostics,
            image.shape,
        )
        if self._track_identity_churn_decision(
            tracks,
            diagnostics,
            min_dropout_ratio=float(self.config.learned_init_churn_min_dropout_ratio),
            max_median_age=float(self.config.learned_init_churn_max_median_age),
        ):
            self.last_learned_mode_before_sparse_homography = "identity_churn"
            self.last_learned_mode_after_sparse_homography = "identity_churn"
            self.last_learned_mode_sparse_homography_allowed = False
            self.last_learned_mode_sparse_homography_reason = "identity_churn_priority"
            return "identity_churn"
        if geometry_mode == "planar_near_wall":
            self.last_learned_mode_before_sparse_homography = "planar_near_wall"
            self.last_learned_mode_after_sparse_homography = "planar_near_wall"
            self.last_learned_mode_sparse_homography_allowed = False
            self.last_learned_mode_sparse_homography_reason = "geometry_mode_planar"
            return "planar_near_wall"

        sparse_allowed = self._loftr_sparse_homography_allowed(tracks, image.shape)
        self.last_learned_mode_sparse_homography_allowed = bool(sparse_allowed)
        self.last_learned_mode_sparse_homography_reason = str(self.last_loftr_sparse_homography_reason)
        if sparse_allowed and self.config.loftr_extreme_only and not self._loftr_extreme_texture_allowed(image_quality):
            sparse_allowed = False
            self.last_learned_mode_sparse_homography_allowed = False
            self.last_learned_mode_sparse_homography_reason = (
                f"{self.last_loftr_sparse_homography_reason}:not_extreme_texture"
            )
        if sparse_allowed:
            self.last_learned_mode_before_sparse_homography = mode_before_sparse
            mode_after_sparse = "extreme_textureless" if self.config.loftr_extreme_only else "planar_near_wall"
            self.last_learned_mode_after_sparse_homography = mode_after_sparse
            return mode_after_sparse
        if klt_degenerate_for_loftr:
            self.last_learned_mode_before_sparse_homography = "low_texture"
            self.last_learned_mode_after_sparse_homography = "extreme_textureless"
            if self.last_learned_mode_sparse_homography_reason == "not_checked":
                self.last_learned_mode_sparse_homography_reason = self.last_klt_degeneracy_loftr_reason
            return "extreme_textureless"
        critical_low_coverage = grid.coverage <= float(self.config.learned_init_critical_grid_coverage)
        if critical_low_coverage:
            self.last_learned_mode_before_sparse_homography = "low_coverage_recovery"
            self.last_learned_mode_after_sparse_homography = "low_coverage_recovery"
            if self.last_learned_mode_sparse_homography_reason == "not_checked":
                self.last_learned_mode_sparse_homography_reason = str(self.last_loftr_sparse_homography_reason)
            return "low_coverage_recovery"
        extreme = (
            image_quality.flat_region_ratio >= float(self.config.three_layer_extreme_min_flat_region_ratio)
            and image_quality.grid_texture_score <= float(self.config.three_layer_extreme_max_grid_texture_score)
        ) or (
            geometry_mode == "severe_low_texture"
            and grid.coverage <= float(self.config.three_layer_extreme_max_grid_coverage)
        )
        if extreme:
            self.last_learned_mode_before_sparse_homography = "extreme_textureless"
            self.last_learned_mode_after_sparse_homography = "extreme_textureless"
            if self.last_learned_mode_sparse_homography_reason == "not_checked":
                self.last_learned_mode_sparse_homography_reason = str(self.last_loftr_sparse_homography_reason)
            return "extreme_textureless"

        low_texture = (
            geometry_mode == "severe_low_texture"
            or image_quality.grid_texture_score <= float(self.config.three_layer_low_texture_max_grid_texture_score)
            or image_quality.flat_region_ratio >= float(self.config.three_layer_low_texture_min_flat_region_ratio)
            or image_quality.degradation_score >= float(self.config.three_layer_low_texture_min_degradation)
        )
        if low_texture:
            self.last_learned_mode_before_sparse_homography = "low_texture"
            self.last_learned_mode_after_sparse_homography = "low_texture"
            if self.last_learned_mode_sparse_homography_reason == "not_checked":
                self.last_learned_mode_sparse_homography_reason = str(self.last_loftr_sparse_homography_reason)
            return "low_texture"
        self.last_learned_mode_before_sparse_homography = mode_before_sparse
        self.last_learned_mode_after_sparse_homography = mode_before_sparse
        if self.last_learned_mode_sparse_homography_reason == "not_checked":
            self.last_learned_mode_sparse_homography_reason = str(self.last_loftr_sparse_homography_reason)
        return "normal"

    def _recover_lost_with_learned(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        exclude_ids: set[int],
    ) -> TrackSet:
        if self.learned_recovery is None:
            return TrackSet.empty()
        source_family = self._source_family_from_matcher(self.learned_matcher)
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            self._record_geometry_safe("learned_recovery:loftr_rejected_requires_confirmed_sparse_refill")
            return TrackSet.empty()
        if self.config.enable_three_layer_source_aware:
            reference = _track_geometry(current_tracks)
            if reference.num_pairs < int(self.config.source_aware_learned_recovery_min_reference_tracks):
                self._record_geometry_safe(
                    f"learned_recovery:{source_family}_rejected_weak_reference_{reference.num_pairs}"
                )
                return TrackSet.empty()
        if not self._source_family_admission_allowed(
            source_family,
            image_quality,
            current_tracks,
            cur.shape,
            context="learned_recovery",
        ):
            return TrackSet.empty()
        return self.learned_recovery.recover(
            self.klt.last_recovery_prev_image,
            cur,
            image_quality,
            current_tracks,
            self.klt.last_lost_prev_points,
            self.klt.last_lost_ids,
            self.klt.last_lost_ages,
            exclude_ids=exclude_ids,
            cell_quality_map=self._last_cell_quality_map,
        )

    def _recover_lost_with_learned_memory(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        geometry_mode: str,
    ) -> TrackSet:
        if (
            self.learned_recovery is None
            or not self.config.enable_learned_track_memory
            or len(self._track_memory) == 0
        ):
            return TrackSet.empty()
        if self._frame_counter - self._last_memory_recovery_frame < int(self.config.learned_track_memory_min_recovery_gap):
            return TrackSet.empty()
        coverage = grid_stats(
            current_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        ).coverage
        if (
            len(current_tracks) >= int(self.config.min_tracks_for_recovery)
            and coverage >= float(self.config.min_grid_coverage_for_recovery)
            and geometry_mode not in {"severe_low_texture", "planar_near_wall"}
        ):
            return TrackSet.empty()

        current_ids = set(int(item) for item in current_tracks.ids)
        recovered = TrackSet.empty()
        working = current_tracks
        exclude_ids: set[int] = set()
        for entry in reversed(self._track_memory):
            if self._frame_counter - int(entry.frame_index) > int(self.config.learned_track_memory_max_frame_gap):
                continue
            if len(recovered) >= int(self.config.learned_track_memory_max_recovered):
                break
            mask = np.asarray([int(track_id) not in current_ids and int(track_id) not in exclude_ids for track_id in entry.ids], dtype=bool)
            if not np.any(mask):
                continue
            budget = int(self.config.learned_track_memory_max_recovered) - len(recovered)
            original_max = self.learned_recovery.config.max_recovered
            original_radius = self.learned_recovery.config.lost_association_radius
            try:
                self.learned_recovery.config.max_recovered = max(1, budget)
                self.learned_recovery.config.lost_association_radius = max(
                    float(original_radius),
                    float(original_radius) * (1.0 + 0.35 * max(0, self._frame_counter - int(entry.frame_index) - 1)),
                )
                candidate = self.learned_recovery.recover(
                    entry.image,
                    cur,
                    image_quality,
                    working,
                    entry.points[mask],
                    entry.ids[mask],
                    entry.ages[mask],
                    exclude_ids=exclude_ids,
                    cell_quality_map=self._last_cell_quality_map,
                )
            finally:
                self.learned_recovery.config.max_recovered = original_max
                self.learned_recovery.config.lost_association_radius = original_radius
            candidate = self._accept_geometry_safe_batch(working, candidate, "learned_memory_recovery")
            if len(candidate) == 0:
                continue
            candidate.sources = [f"{source}_memory" if not str(source).endswith("_memory") else source for source in candidate.sources]
            recovered = KltTracker._append_tracks(recovered, candidate)
            working = KltTracker._append_tracks(working, candidate)
            exclude_ids.update(int(item) for item in candidate.ids)
        if len(recovered):
            self._last_memory_recovery_frame = self._frame_counter
            self._record_geometry_safe(f"learned_memory_recovery:accepted_{len(recovered)}")
        return recovered

    def _recover_lost_with_homography(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        exclude_ids: set[int],
    ) -> TrackSet:
        prev = self.klt.last_recovery_prev_image
        lost_points = self.klt.last_lost_prev_points
        lost_ids = self.klt.last_lost_ids
        lost_ages = self.klt.last_lost_ages
        if prev is None or len(lost_points) == 0 or len(current_tracks) < self.config.homography_recovery_min_tracks:
            return TrackSet.empty()
        motion_mask = current_tracks.ages > 1
        if int(np.sum(motion_mask)) < self.config.homography_recovery_min_tracks:
            return TrackSet.empty()
        if self.config.homography_recovery_min_median_track_age > 0.0:
            median_age = float(np.median(current_tracks.ages[motion_mask]))
            if median_age < self.config.homography_recovery_min_median_track_age:
                return TrackSet.empty()

        pts0 = current_tracks.prev_points[motion_mask].astype(np.float32)
        pts1 = current_tracks.points[motion_mask].astype(np.float32)
        h_mat, h_mask = cv2.findHomography(pts0, pts1, cv2.RANSAC, 3.0)
        if h_mat is None or np.asarray(h_mat).shape != (3, 3) or h_mask is None:
            return TrackSet.empty()
        h_inlier_ratio = float(np.mean(h_mask.reshape(-1).astype(bool)))
        if h_inlier_ratio < self.config.planar_min_h_inlier_ratio:
            return TrackSet.empty()

        predicted = _warp_points(h_mat, lost_points.astype(np.float32))
        in_border = _in_border(predicted, cur.shape, border=self.klt.config.border)
        ncc = _patch_ncc(prev, cur, lost_points.astype(np.float32), predicted.astype(np.float32), radius=5)
        hom_error = _homography_errors(h_mat, lost_points.astype(np.float32), predicted.astype(np.float32))
        valid = (
            in_border
            & (ncc >= self.config.homography_recovery_min_ncc)
            & (hom_error <= self.config.homography_recovery_max_error)
        )
        if (
            self.config.enable_local_quality_map
            and self.config.local_quality_apply_to_candidate_scoring
            and self.config.local_quality_min_learned_score > 0.0
        ):
            lost_local_quality = self._point_quality_base(predicted, cur.shape, image_quality)
            valid &= lost_local_quality >= float(self.config.local_quality_min_learned_score)
        if exclude_ids:
            valid &= ~np.asarray([int(track_id) in exclude_ids for track_id in lost_ids], dtype=bool)
        if len(current_tracks.points):
            for idx, point in enumerate(predicted):
                if valid[idx] and _too_close(point, current_tracks.points, self.config.min_current_distance):
                    valid[idx] = False

        indices = np.where(valid)[0]
        if len(indices) == 0:
            return TrackSet.empty()
        score = ncc[indices] * np.exp(-hom_error[indices] / max(1e-6, self.config.homography_recovery_max_error))
        order = indices[np.argsort(-score)[: self.config.homography_recovery_max_recovered]]
        prev_arr = lost_points[order].astype(np.float32)
        cur_arr = predicted[order].astype(np.float32)
        ids_arr = lost_ids[order].astype(np.int64)
        ages_arr = (lost_ages[order] + 1).astype(np.int32)
        ncc_arr = ncc[order].astype(np.float32)
        hom_arr = hom_error[order].astype(np.float32)
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = self._point_quality_base(cur_arr, cur.shape, image_quality)
        hom_score = np.exp(-hom_arr / max(1e-6, self.config.homography_recovery_max_error))
        age_score = np.clip(ages_arr.astype(np.float32) / 20.0, 0.0, 1.0)
        quality = np.clip(
            local_quality
            * (0.25 + 0.75 * local_tex)
            * (0.30 + 0.70 * ncc_arr)
            * (0.30 + 0.70 * hom_score)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)

        return TrackSet(
            ids=ids_arr,
            prev_points=prev_arr,
            points=cur_arr,
            ages=ages_arr,
            fb_errors=hom_arr,
            ncc_scores=ncc_arr,
            local_texture=local_tex.astype(np.float32),
            qualities=self._scale_new_track_quality(quality, "planar_near_wall"),
            sources=["homography_recovery"] * len(ids_arr),
        )

    def _initialize_new_tracks_with_learned(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
    ) -> TrackSet:
        if self.learned_recovery is None or not self.config.enable_learned_initialization:
            return TrackSet.empty()
        if not self._should_initialize_with_learned(cur, image_quality, current_tracks):
            return TrackSet.empty()
        extra_budget = max(0, int(self.config.learned_sidecar_max_extra)) if self.config.preserve_klt_replenish else 0
        remaining_budget = self.klt.config.max_features + extra_budget - len(current_tracks)
        if remaining_budget <= 0:
            return TrackSet.empty()
        fraction_budget = int(round(self.klt.config.max_features * self.config.max_learned_init_fraction))
        support_tracks = self._semidense_support_tracks(current_tracks)
        coverage = grid_stats(support_tracks.points, cur.shape).coverage
        reserve = self.config.reserve_gftt_features if coverage < self.config.reserve_gftt_when_grid_below else 0
        learned_budget = max(0, min(remaining_budget - reserve, self.config.max_learned_initialized, fraction_budget))
        if self.config.enable_adaptive_birth_budget:
            learned_budget = min(
                learned_budget,
                self._adaptive_birth_budget(
                    cur,
                    image_quality,
                    current_tracks,
                    source="learned_init",
                ),
            )
        if learned_budget <= 0:
            return TrackSet.empty()
        source_family = self._source_family_from_matcher(self.learned_matcher)
        if not self._source_family_admission_allowed(
            source_family,
            image_quality,
            current_tracks,
            cur.shape,
            context="learned_initialization",
        ):
            return TrackSet.empty()
        if not self._source_promotion_allowed(image_quality, current_tracks, cur.shape):
            self._record_geometry_safe("learned_initialization:rejected_source_gate")
            return TrackSet.empty()
        prev = self.klt.last_recovery_prev_image
        initialized = self.learned_recovery.initialize_new_tracks(
            prev,
            cur,
            image_quality,
            current_tracks,
            next_id=self.klt.next_id,
            max_new=learned_budget,
            cell_quality_map=self._last_cell_quality_map,
        )
        initialized = self._accept_geometry_safe_batch(
            current_tracks,
            initialized,
            "learned_initialization",
        )
        initialized = self._accept_learned_initialization_batch(
            cur,
            current_tracks,
            initialized,
        )
        initialized = self._scale_new_tracks_for_mode(initialized)
        return initialized

    def _accept_learned_initialization_batch(
        self,
        cur: np.ndarray,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
    ) -> TrackSet:
        if not self.config.enable_learned_init_acceptance_gate:
            return self._filter_promotion_candidates(candidate_tracks, cur, current_tracks)
        if len(candidate_tracks) == 0:
            return candidate_tracks
        candidate_tracks = self._filter_promotion_candidates(candidate_tracks, cur, current_tracks)
        if len(candidate_tracks) == 0:
            self._record_geometry_safe("learned_initialization:rejected_source_specific_filter")
            return candidate_tracks
        median_quality = _median(candidate_tracks.qualities)
        if median_quality == median_quality and median_quality < float(self.config.learned_init_acceptance_min_quality):
            self._record_geometry_safe("learned_initialization:rejected_low_init_quality")
            return TrackSet.empty()

        if self._learned_init_track_churn(current_tracks):
            return self._accept_geometry_safe_batch(
                current_tracks,
                candidate_tracks,
                "learned_initialization",
            )

        source_family = _source_family_from_sources(candidate_tracks.sources)
        requires_grid_refill = bool(
            self.config.enable_three_layer_source_aware and source_family == "loftr"
        )
        before_geometry = _track_geometry(current_tracks)
        if (
            before_geometry.num_pairs >= int(self.config.learned_init_acceptance_min_reference_tracks)
            and not requires_grid_refill
        ):
            return candidate_tracks

        before_grid = grid_stats(
            current_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        after_points = (
            np.vstack([current_tracks.points, candidate_tracks.points]).astype(np.float32)
            if len(current_tracks.points)
            else candidate_tracks.points
        )
        after_grid = grid_stats(
            after_points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        grid_gain = float(after_grid.coverage - before_grid.coverage)
        new_cell_ratio = _new_cell_ratio(
            current_tracks.points,
            candidate_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        severely_sparse = len(current_tracks) < int(self.config.min_tracks_for_recovery)
        min_grid_gain = float(self.config.learned_init_acceptance_weak_min_grid_gain)
        min_new_cell_ratio = float(self.config.learned_init_acceptance_weak_min_new_cell_ratio)
        if requires_grid_refill:
            min_grid_gain = max(min_grid_gain, float(self.config.source_aware_loftr_min_grid_gain))
            min_new_cell_ratio = max(
                min_new_cell_ratio,
                float(self.config.source_aware_loftr_min_new_cell_ratio),
            )
        useful_coverage = (
            grid_gain >= min_grid_gain
            or new_cell_ratio >= min_new_cell_ratio
        )
        if not useful_coverage and (requires_grid_refill or not severely_sparse):
            self._record_geometry_safe("learned_initialization:rejected_weak_reference_no_grid_gain")
            return TrackSet.empty()
        if requires_grid_refill and before_geometry.num_pairs >= int(self.config.learned_init_acceptance_min_reference_tracks):
            return candidate_tracks

        max_new = min(
            int(self.config.learned_init_acceptance_weak_max_new),
            int(round(self.klt.config.max_features * float(self.config.learned_init_acceptance_weak_max_fraction))),
            len(candidate_tracks),
        )
        if max_new <= 0:
            self._record_geometry_safe("learned_initialization:rejected_weak_reference_no_budget")
            return TrackSet.empty()
        if len(candidate_tracks) <= max_new:
            self._record_geometry_safe(f"learned_initialization:accepted_weak_reference_{len(candidate_tracks)}")
            return candidate_tracks

        cell_scores = _cell_need_scores(
            current_tracks.points,
            candidate_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            target_cell_count=self.config.learned_target_cell_count,
        )
        scores = (
            np.clip(candidate_tracks.qualities.astype(np.float32), 0.0, 1.0)
            * (0.35 + 0.65 * np.clip(candidate_tracks.ncc_scores.astype(np.float32), 0.0, 1.0))
            * (0.35 + 0.65 * cell_scores.astype(np.float32))
        )
        selected = _select_grid_quota_candidates(
            points=candidate_tracks.points,
            scores=scores,
            image_shape=cur.shape,
            max_count=max_new,
            min_distance=self.config.min_current_distance,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            max_per_cell=max(1, self.config.learned_init_max_per_cell),
        )
        if len(selected) == 0:
            self._record_geometry_safe("learned_initialization:rejected_weak_reference_selection_empty")
            return TrackSet.empty()
        mask = np.zeros((len(candidate_tracks),), dtype=bool)
        mask[selected] = True
        self._record_geometry_safe(f"learned_initialization:accepted_weak_reference_subset_{len(selected)}")
        return _subset_tracks(candidate_tracks, mask)

    def _source_promotion_allowed(
        self,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        image_shape: tuple[int, int],
    ) -> bool:
        if self.config.enable_three_layer_source_aware:
            return self._source_family_admission_allowed(
                self._source_family_from_matcher(self.learned_matcher),
                image_quality,
                current_tracks,
                image_shape,
                context="learned_promotion",
            )
        matcher_name = str(getattr(self.learned_matcher, "name", "")).lower()
        if "loftr" in matcher_name:
            if image_quality.grid_texture_score > float(self.config.promotion_loftr_max_grid_texture_score):
                return False
            if image_quality.flat_region_ratio < float(self.config.promotion_loftr_min_flat_region_ratio):
                return False
            geom = _track_geometry(current_tracks)
            if geom.num_pairs >= 16 and geom.homography_inlier_ratio < float(self.config.promotion_loftr_min_h_inlier_ratio):
                return False
            return True
        if "xfeat" in matcher_name:
            coverage = grid_stats(
                current_tracks.points,
                image_shape,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
            ).coverage
            return coverage < float(self.config.promotion_xfeat_min_grid_coverage)
        return True

    def _source_family_admission_allowed(
        self,
        source_family: str,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        image_shape: tuple[int, int],
        context: str,
    ) -> bool:
        if not self.config.enable_three_layer_source_aware:
            return True
        learned_mode = str(getattr(self, "last_learned_mode", "normal"))
        source_family = _source_family_name(source_family)
        allowed_modes = set(self._source_family_allowed_modes(source_family))
        if allowed_modes and learned_mode not in allowed_modes:
            if source_family == "loftr" and bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False)):
                pass
            else:
                self._record_geometry_safe(f"{context}:{source_family}_rejected_mode_{learned_mode}")
                return False
        if source_family == "xfeat":
            coverage = grid_stats(
                current_tracks.points,
                image_shape,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
            ).coverage
            if coverage >= float(self.config.promotion_xfeat_min_grid_coverage):
                self._record_geometry_safe(f"{context}:xfeat_rejected_grid_full")
                return False
        if source_family == "loftr":
            if not self._loftr_planar_extreme_gate(image_quality, current_tracks, image_shape, context):
                return False
        return True

    def _source_family_allowed_modes(self, source_family: str) -> tuple[str, ...]:
        if source_family == "superpoint_lightglue":
            return tuple(str(item) for item in self.config.source_aware_superpoint_lightglue_modes)
        if source_family == "xfeat":
            return tuple(str(item) for item in self.config.source_aware_xfeat_modes)
        if source_family == "loftr":
            return tuple(str(item) for item in self.config.source_aware_loftr_modes)
        return ()

    def _loftr_extreme_texture_allowed(self, image_quality: ImageQuality) -> bool:
        if not self.config.loftr_extreme_only:
            return True
        low_grid_texture = (
            image_quality.grid_texture_score <= float(self.config.loftr_extreme_max_grid_texture_score)
        )
        flat_or_degraded = (
            image_quality.flat_region_ratio >= float(self.config.loftr_extreme_min_flat_region_ratio)
            or image_quality.degradation_score >= float(self.config.loftr_extreme_min_degradation)
        )
        return bool(low_grid_texture and flat_or_degraded)

    def _loftr_planar_extreme_gate(
        self,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        image_shape: tuple[int, int],
        context: str,
    ) -> bool:
        learned_mode = str(getattr(self, "last_learned_mode", "normal"))
        klt_degenerate = bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False))
        allowed_modes = set(self._source_family_allowed_modes("loftr"))
        if allowed_modes:
            mode_allowed = learned_mode in allowed_modes
        else:
            mode_allowed = learned_mode in {"planar_near_wall", "extreme_textureless"}
        if not mode_allowed and not klt_degenerate:
            self._record_geometry_safe(f"{context}:loftr_rejected_not_planar_extreme")
            return False
        if (
            self.config.loftr_extreme_only
            and not self._loftr_extreme_texture_allowed(image_quality)
            and not klt_degenerate
        ):
            self._record_geometry_safe(f"{context}:loftr_rejected_not_extreme_texture")
            return False
        sparse_homography = self._loftr_sparse_homography_allowed(current_tracks, image_shape)
        if klt_degenerate:
            planar_texture = True
        elif self.config.loftr_extreme_only:
            planar_texture = self._loftr_extreme_texture_allowed(image_quality)
        else:
            planar_texture = (
                image_quality.flat_region_ratio >= float(self.config.semidense_fallback_min_flat_region_ratio)
                or image_quality.grid_texture_score <= float(self.config.semidense_fallback_min_grid_texture_score)
                or image_quality.grid_texture_score <= float(self.config.promotion_loftr_max_grid_texture_score)
                or sparse_homography
            )
        if not planar_texture:
            self._record_geometry_safe(f"{context}:loftr_rejected_texture")
            return False
        grid = grid_stats(
            current_tracks.points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        sparse_enough = grid.coverage < float(self.config.semidense_fallback_min_grid_coverage)
        if not sparse_enough and learned_mode != "extreme_textureless" and not klt_degenerate:
            self._record_geometry_safe(f"{context}:loftr_rejected_grid_full")
            return False
        if klt_degenerate:
            return True
        geometry = _track_geometry(current_tracks)
        min_pairs = min(16, int(self.config.learned_geometry_min_tracks))
        if geometry.num_pairs >= min_pairs:
            min_h = max(
                float(self.config.promotion_loftr_min_h_inlier_ratio),
                float(self.config.source_aware_loftr_min_h_inlier_ratio),
            )
            if geometry.homography_inlier_ratio < min_h and not sparse_homography:
                self._record_geometry_safe(f"{context}:loftr_rejected_h_inliers")
                return False
            if geometry.median_homography_error == geometry.median_homography_error:
                if (
                    geometry.median_homography_error > float(self.config.source_aware_loftr_max_homography_error)
                    and not sparse_homography
                ):
                    self._record_geometry_safe(f"{context}:loftr_rejected_h_residual")
                    return False
        return True

    def _filter_promotion_candidates(
        self,
        candidate_tracks: TrackSet,
        cur: np.ndarray,
        current_tracks: TrackSet,
    ) -> TrackSet:
        if len(candidate_tracks) == 0:
            return candidate_tracks
        matcher_name = str(getattr(self.learned_matcher, "name", "")).lower()
        min_quality = float(self.config.promotion_default_min_quality)
        if "xfeat" in matcher_name:
            min_quality = float(self.config.promotion_xfeat_min_quality)
        elif "lightglue" in matcher_name or "superpoint" in matcher_name:
            min_quality = float(self.config.promotion_lightglue_min_quality)
        elif "loftr" in matcher_name:
            min_quality = float(self.config.promotion_loftr_min_quality)
        valid = candidate_tracks.qualities >= min_quality
        if len(current_tracks.points):
            for idx, point in enumerate(candidate_tracks.points):
                if valid[idx] and _too_close(point, current_tracks.points, self.config.gftt_confirmation_min_distance):
                    valid[idx] = False
        if self.config.enable_three_layer_source_aware and "loftr" in matcher_name:
            geometry = _reference_geometry(current_tracks)
            if geometry["f_mat"] is not None:
                epi = _epipolar_errors(geometry["f_mat"], candidate_tracks.prev_points, candidate_tracks.points)
                valid &= epi <= float(self.config.source_aware_loftr_max_epipolar_error)
            if geometry["h_mat"] is not None:
                hom = _homography_errors(geometry["h_mat"], candidate_tracks.prev_points, candidate_tracks.points)
                valid &= hom <= float(self.config.source_aware_loftr_max_homography_error)
        if self.config.enable_three_layer_source_aware and "xfeat" in matcher_name:
            geometry = _reference_geometry(current_tracks)
            if geometry["f_mat"] is not None:
                epi = _epipolar_errors(geometry["f_mat"], candidate_tracks.prev_points, candidate_tracks.points)
                valid &= epi <= float(self.config.candidate_geometry_max_epipolar_error)
            if geometry["h_mat"] is not None:
                hom = _homography_errors(geometry["h_mat"], candidate_tracks.prev_points, candidate_tracks.points)
                valid &= hom <= float(self.config.candidate_geometry_max_homography_error)
        return _subset_tracks(candidate_tracks, valid) if np.any(valid) else TrackSet.empty()

    def _should_initialize_with_learned(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
    ) -> bool:
        extra_budget = max(0, int(self.config.learned_sidecar_max_extra)) if self.config.preserve_klt_replenish else 0
        if len(current_tracks) >= self.klt.config.max_features + extra_budget:
            return False
        coverage = grid_stats(current_tracks.points, cur.shape).coverage
        degraded = (
            image_quality.degradation_score >= self.config.learned_init_min_degradation
            or image_quality.flat_region_ratio >= self.config.learned_init_min_flat_region_ratio
        )
        sparse = coverage < self.config.learned_init_min_grid_coverage
        critical_sparse = coverage < self.config.learned_init_critical_grid_coverage
        churn = self._learned_init_track_churn(current_tracks)
        if churn:
            return True
        if self.config.learned_init_requires_degradation:
            return (degraded and sparse) or critical_sparse
        return degraded or sparse

    def _learned_init_track_churn(self, current_tracks: TrackSet) -> bool:
        if not self.config.learned_init_on_track_churn:
            return False
        diagnostics = self._last_klt_diagnostics
        if diagnostics is None or diagnostics.tracked_before_filter <= 0:
            return False
        return self._track_identity_churn_decision(
            current_tracks,
            diagnostics,
            min_dropout_ratio=float(self.config.learned_init_churn_min_dropout_ratio),
            max_median_age=float(self.config.learned_init_churn_max_median_age),
        )

    def _track_identity_churn_decision(
        self,
        current_tracks: TrackSet,
        diagnostics: TrackerDiagnostics,
        min_dropout_ratio: float,
        max_median_age: float,
    ) -> bool:
        if diagnostics.tracked_before_filter <= 0:
            return False
        dropout_ratio = diagnostics.dropped_features / max(1, diagnostics.tracked_before_filter)
        median_age = _median(current_tracks.ages)
        instant_churn = bool(
            dropout_ratio >= float(min_dropout_ratio)
            and median_age == median_age
            and median_age <= float(max_median_age)
        )
        if not self.config.learned_init_rolling_churn:
            return instant_churn

        min_dropout_ratio = float(self.config.learned_init_churn_min_dropout_ratio)
        max_median_age = float(self.config.learned_init_churn_max_median_age)
        if self._last_churn_update_frame == self._frame_counter:
            return bool(self._last_churn_decision)

        image_shape = self._last_image_shape
        coverage = (
            grid_stats(current_tracks.points, image_shape).coverage
            if image_shape is not None and len(current_tracks.points)
            else 0.0
        )
        long_track_ratio = (
            float(np.mean(current_tracks.ages.astype(np.float32) >= 5.0))
            if len(current_tracks.ages)
            else 0.0
        )
        coverage_ok = coverage >= float(self.config.learned_init_rolling_churn_min_grid_coverage)
        continuity_bad = bool(
            median_age == median_age
            and (
                median_age <= float(max_median_age)
                or long_track_ratio <= float(self.config.learned_init_rolling_churn_max_long_track_ratio)
            )
        )
        bad = bool(dropout_ratio >= float(min_dropout_ratio) and coverage_ok and continuity_bad)
        window = max(1, int(self.config.learned_init_rolling_churn_window))
        min_bad = max(1, min(window, int(self.config.learned_init_rolling_churn_min_bad_frames)))
        self._churn_history.append(bad)
        self._churn_history = self._churn_history[-window:]
        decision = sum(1 for item in self._churn_history if item) >= min_bad
        self._last_churn_update_frame = self._frame_counter
        self._last_churn_decision = bool(decision)
        return bool(decision)

    def _initialize_sparse_cells_with_semidense_fallback(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        geometry_mode: str,
    ) -> TrackSet:
        self.last_semidense_acceptance = "not_triggered"
        if (
            self.semidense_fallback_recovery is None
            or not self.config.enable_semidense_fallback_initialization
        ):
            self.last_semidense_acceptance = "disabled"
            return TrackSet.empty()
        if not self._should_initialize_with_semidense_fallback(cur, image_quality, current_tracks, geometry_mode):
            return TrackSet.empty()
        extra_budget = max(0, int(self.config.semidense_fallback_sidecar_max_extra))
        remaining_budget = self.klt.config.max_features + extra_budget - len(current_tracks)
        if remaining_budget <= 0:
            return TrackSet.empty()
        fraction_budget = int(round(self.klt.config.max_features * self.config.semidense_fallback_max_fraction))
        reserve_gftt = int(self.config.semidense_fallback_reserve_gftt_features)
        if (
            self._source_family_from_matcher(self.semidense_fallback_matcher) == "loftr"
            and (
                bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False))
                or bool(getattr(self, "last_loftr_sparse_homography_allowed", False))
            )
        ):
            reserve_gftt = min(
                reserve_gftt,
                max(0, remaining_budget - int(self.config.klt_degeneracy_loftr_reserve_budget)),
            )
        learned_budget = max(
            0,
            min(
                remaining_budget - reserve_gftt,
                self.config.semidense_fallback_max_new,
                fraction_budget,
            ),
        )
        if learned_budget <= 0:
            self.last_semidense_acceptance = "no_budget"
            return TrackSet.empty()
        prev = self.klt.last_recovery_prev_image
        if prev is None:
            self.last_semidense_acceptance = "no_previous_frame"
            return TrackSet.empty()
        source_family = self._source_family_from_matcher(self.semidense_fallback_matcher)
        if not self._source_family_admission_allowed(
            source_family,
            image_quality,
            current_tracks,
            cur.shape,
            context="semidense_fallback",
        ):
            self.last_semidense_acceptance = f"{source_family}_source_gate_rejected"
            return TrackSet.empty()
        original_min_coverage_score = self.semidense_fallback_recovery.config.init_min_coverage_score
        original_enable_grid_quota = self.semidense_fallback_recovery.config.init_enable_grid_quota
        original_max_epipolar = self.semidense_fallback_recovery.config.max_epipolar_error
        original_max_homography = self.semidense_fallback_recovery.config.max_homography_error
        original_geometry_mode = self.semidense_fallback_recovery.config.geometry_filter_mode
        try:
            self.semidense_fallback_recovery.config.init_min_coverage_score = (
                self.config.semidense_fallback_min_coverage_score
            )
            self.semidense_fallback_recovery.config.init_enable_grid_quota = True
            if self.config.enable_adaptive_geometry_model_selection:
                self.semidense_fallback_recovery.config.geometry_filter_mode = self._candidate_geometry_filter_mode(
                    "semidense_fallback"
                )
            if source_family == "loftr":
                if self.config.enable_three_layer_source_aware:
                    self.semidense_fallback_recovery.config.geometry_filter_mode = (
                        self.config.source_aware_loftr_geometry_filter_mode
                    )
                    self.semidense_fallback_recovery.config.max_epipolar_error = (
                        self.config.source_aware_loftr_max_epipolar_error
                    )
                    self.semidense_fallback_recovery.config.max_homography_error = (
                        self.config.source_aware_loftr_max_homography_error
                    )
                else:
                    self.semidense_fallback_recovery.config.max_epipolar_error = self.config.loftr_max_epipolar_error
                    self.semidense_fallback_recovery.config.max_homography_error = self.config.loftr_max_homography_error
            initialized = self.semidense_fallback_recovery.initialize_new_tracks(
                prev,
                cur,
                image_quality,
                current_tracks,
                next_id=self.klt.next_id,
                max_new=learned_budget,
                cell_quality_map=self._last_cell_quality_map,
            )
        finally:
            self.semidense_fallback_recovery.config.init_min_coverage_score = original_min_coverage_score
            self.semidense_fallback_recovery.config.init_enable_grid_quota = original_enable_grid_quota
            self.semidense_fallback_recovery.config.max_epipolar_error = original_max_epipolar
            self.semidense_fallback_recovery.config.max_homography_error = original_max_homography
            self.semidense_fallback_recovery.config.geometry_filter_mode = original_geometry_mode
        self.last_semidense_raw_candidates = int(len(initialized))
        if len(initialized) and bool(self.config.semidense_fallback_cooldown_on_attempt):
            self._last_semidense_fallback_frame = self._frame_counter
        initialized = self._post_validate_semidense_candidates(current_tracks, initialized, cur.shape)
        self.last_semidense_post_validate_candidates = int(len(initialized))
        initialized = self._accept_semidense_fallback(cur, current_tracks, initialized)
        self.last_semidense_accepted_candidates = int(len(initialized))
        initialized = self._scale_new_tracks_for_mode(initialized)
        if len(initialized):
            self._last_semidense_fallback_frame = self._frame_counter
            self.last_semidense_acceptance = f"accepted_{self._semidense_fallback_method()}_{len(initialized)}"
        return initialized

    def _should_initialize_with_semidense_fallback(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        geometry_mode: str,
    ) -> bool:
        extra_budget = max(0, int(self.config.semidense_fallback_sidecar_max_extra))
        if len(current_tracks) >= self.klt.config.max_features + extra_budget:
            return False
        if self._frame_counter < int(self.config.semidense_fallback_start_frame):
            self.last_semidense_acceptance = "waiting_start_frame"
            return False
        if self._frame_counter - self._last_semidense_fallback_frame < self.config.semidense_fallback_min_frame_gap:
            return False
        coverage = grid_stats(current_tracks.points, cur.shape).coverage
        sparse = coverage < self.config.semidense_fallback_min_grid_coverage
        source_family = self._source_family_from_matcher(self.semidense_fallback_matcher)
        sparse_homography = False
        degraded = (
            image_quality.degradation_score >= self.config.semidense_fallback_min_degradation
            or image_quality.flat_region_ratio >= self.config.semidense_fallback_min_flat_region_ratio
            or image_quality.grid_texture_score <= self.config.semidense_fallback_min_grid_texture_score
            or geometry_mode in {"severe_low_texture", "planar_near_wall"}
        )
        if source_family == "loftr" and self.config.loftr_requires_planar_severe:
            klt_degenerate = bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False))
            if (
                self.config.loftr_extreme_only
                and not self._loftr_extreme_texture_allowed(image_quality)
                and not klt_degenerate
            ):
                self.last_semidense_acceptance = "loftr_gate_rejected_not_extreme_texture"
                return False
            if self.config.loftr_requires_klt_degeneracy and not klt_degenerate:
                self.last_semidense_acceptance = "loftr_gate_rejected_klt_not_degenerate"
                return False
            planar_or_severe = geometry_mode in {"severe_low_texture", "planar_near_wall"}
            sparse_homography = self._loftr_sparse_homography_allowed(current_tracks, cur.shape)
            if klt_degenerate:
                planar_texture = True
            elif self.config.loftr_extreme_only:
                planar_texture = self._loftr_extreme_texture_allowed(image_quality)
            else:
                planar_texture = (
                    image_quality.flat_region_ratio >= self.config.semidense_fallback_min_flat_region_ratio
                    or image_quality.grid_texture_score <= self.config.semidense_fallback_min_grid_texture_score
                )
            degeneracy_proposal = (
                bool(self.config.klt_degeneracy_loftr_allow_degraded_texture)
                and klt_degenerate
                and planar_texture
            )
            if not ((sparse and planar_or_severe and planar_texture) or sparse_homography or degeneracy_proposal):
                self.last_semidense_acceptance = "loftr_gate_rejected_mode"
                return False
            if self.config.enable_three_layer_source_aware:
                learned_mode = str(getattr(self, "last_learned_mode", "normal"))
                allowed_modes = set(self._source_family_allowed_modes("loftr"))
                if not allowed_modes:
                    allowed_modes = {"planar_near_wall", "extreme_textureless"}
                if learned_mode not in allowed_modes and not klt_degenerate:
                    self.last_semidense_acceptance = f"loftr_source_mode_rejected_{learned_mode}"
                    return False
        if self.config.semidense_fallback_requires_degradation:
            if source_family == "loftr" and bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False)):
                return degraded or sparse_homography or bool(self.config.klt_degeneracy_loftr_allow_degraded_texture)
            return sparse and (degraded or sparse_homography or bool(getattr(self, "last_klt_degeneracy_loftr_allowed", False)))
        return sparse or degraded

    def _semidense_support_tracks(self, tracks: TrackSet) -> TrackSet:
        if not bool(self.config.semidense_use_mature_support) or len(tracks) == 0:
            return tracks
        min_age = max(1, int(self.config.semidense_mature_support_min_age))
        mature = tracks.ages >= min_age
        if not np.any(mature):
            return TrackSet.empty()
        return _subset_tracks(tracks, mature)

    def _loftr_sparse_homography_allowed(
        self,
        current_tracks: TrackSet,
        image_shape: tuple[int, int],
    ) -> bool:
        if not self.config.loftr_allow_sparse_homography:
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = "disabled"
            return False
        coverage = grid_stats(
            current_tracks.points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        ).coverage
        if coverage > float(self.config.loftr_sparse_max_grid_coverage):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"coverage_high:{coverage:.3f}"
            return False
        if len(current_tracks) == 0:
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = "no_tracks"
            return False
        mature = current_tracks.ages > 1
        if int(np.sum(mature)) < int(self.config.learned_geometry_min_tracks):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"few_mature:{int(np.sum(mature))}"
            return False
        median_age = float(np.median(current_tracks.ages[mature]))
        if median_age < float(self.config.loftr_sparse_min_median_track_age):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"age_low:{median_age:.3f}"
            return False
        geometry = _track_geometry(current_tracks)
        if geometry.num_pairs < int(self.config.learned_geometry_min_tracks):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"few_pairs:{geometry.num_pairs}"
            return False
        if geometry.homography_inlier_ratio < float(self.config.loftr_sparse_min_h_inlier_ratio):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"h_inlier_low:{geometry.homography_inlier_ratio:.3f}"
            return False
        if geometry.planar_score < float(self.config.loftr_sparse_min_planar_score):
            self.last_loftr_sparse_homography_allowed = False
            self.last_loftr_sparse_homography_reason = f"planar_score_low:{geometry.planar_score:.3f}"
            return False
        if geometry.median_homography_error == geometry.median_homography_error:
            if geometry.median_homography_error > float(self.config.loftr_sparse_max_homography_error):
                self.last_loftr_sparse_homography_allowed = False
                self.last_loftr_sparse_homography_reason = f"homography_error_high:{geometry.median_homography_error:.3f}"
                return False
        self.last_loftr_sparse_homography_allowed = True
        self.last_loftr_sparse_homography_reason = "allowed"
        return True

    def _accept_semidense_fallback(
        self,
        cur: np.ndarray,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
    ) -> TrackSet:
        if len(candidate_tracks) == 0:
            self.last_semidense_acceptance = "no_candidates"
            return TrackSet.empty()
        if not self.config.semidense_acceptance_enable:
            return candidate_tracks
        source_family = _source_family_from_sources(candidate_tracks.sources)
        min_candidate_tracks = int(self.config.semidense_acceptance_min_new_tracks)
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            min_candidate_tracks = max(1, min_candidate_tracks)
        if len(candidate_tracks) < min_candidate_tracks:
            self.last_semidense_acceptance = "rejected_too_few_candidates"
            return TrackSet.empty()

        support_tracks = self._semidense_support_tracks(current_tracks)
        before_grid = grid_stats(support_tracks.points, cur.shape, rows=self.config.learned_coverage_rows, cols=self.config.learned_coverage_cols)
        merged_support = KltTracker._append_tracks(support_tracks, candidate_tracks)
        merged = KltTracker._append_tracks(current_tracks, candidate_tracks)
        after_grid = grid_stats(merged_support.points, cur.shape, rows=self.config.learned_coverage_rows, cols=self.config.learned_coverage_cols)
        grid_gain = after_grid.coverage - before_grid.coverage
        new_cell_ratio = _new_cell_ratio(
            support_tracks.points,
            candidate_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        new_cells = _new_cell_count(
            support_tracks.points,
            candidate_tracks.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        self.last_semidense_grid_gain = float(grid_gain)
        self.last_semidense_new_cell_ratio = float(new_cell_ratio)
        min_grid_gain = float(self.config.semidense_acceptance_min_grid_gain)
        min_new_cell_ratio = float(self.config.semidense_acceptance_min_new_cell_ratio)
        min_new_cells = int(self.config.semidense_acceptance_min_new_cells)
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            min_grid_gain = max(min_grid_gain, float(self.config.source_aware_loftr_min_grid_gain))
            min_new_cells = max(min_new_cells, int(self.config.source_aware_loftr_min_new_cells))
            min_new_cell_ratio = max(
                min_new_cell_ratio,
                float(self.config.source_aware_loftr_min_new_cell_ratio),
            )
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            low_utility = grid_gain < min_grid_gain or (
                new_cell_ratio < min_new_cell_ratio and new_cells < min_new_cells
            )
        else:
            low_utility = (
                grid_gain < min_grid_gain
                and new_cell_ratio < min_new_cell_ratio
                and new_cells < min_new_cells
            )
        if low_utility:
            self.last_semidense_acceptance = (
                f"rejected_low_coverage_gain:{grid_gain:.3f}"
                f":new_cell_ratio:{new_cell_ratio:.3f}:new_cells:{new_cells}"
            )
            return TrackSet.empty()

        before_geometry = _track_geometry(current_tracks)
        after_geometry = _track_geometry(merged)
        self.last_semidense_before_f_inlier = float(before_geometry.fundamental_inlier_ratio)
        self.last_semidense_after_f_inlier = float(after_geometry.fundamental_inlier_ratio)
        self.last_semidense_before_h_inlier = float(before_geometry.homography_inlier_ratio)
        self.last_semidense_after_h_inlier = float(after_geometry.homography_inlier_ratio)
        self.last_semidense_before_epipolar = float(before_geometry.median_epipolar_error)
        self.last_semidense_after_epipolar = float(after_geometry.median_epipolar_error)
        self.last_semidense_before_homography = float(before_geometry.median_homography_error)
        self.last_semidense_after_homography = float(after_geometry.median_homography_error)
        if not _geometry_gate_accepts(
            before_geometry,
            after_geometry,
            max_f_drop=self.config.semidense_acceptance_max_f_inlier_drop,
            max_h_drop=self.config.semidense_acceptance_max_h_inlier_drop,
            max_epi_ratio=self.config.semidense_acceptance_max_epipolar_error_ratio,
            max_hom_ratio=self.config.semidense_acceptance_max_homography_error_ratio,
            residual_neutral=bool(self.config.semidense_acceptance_residual_neutral),
            max_epi_abs_increase=float(self.config.semidense_acceptance_max_epipolar_error_abs_increase),
            max_hom_abs_increase=float(self.config.semidense_acceptance_max_homography_error_abs_increase),
        ):
            if (
                bool(self.config.enable_three_layer_source_aware)
                and source_family == "loftr"
                and bool(self.config.semidense_acceptance_subset_on_geometry_fail)
            ):
                subset = self._select_semidense_geometry_safe_subset(
                    current_tracks,
                    candidate_tracks,
                    cur.shape,
                    before_geometry,
                    max_count=int(self.config.semidense_acceptance_subset_max_count),
                    min_count=int(self.config.semidense_acceptance_subset_min_count),
                    max_per_cell=int(self.config.semidense_acceptance_subset_max_per_cell),
                )
                if len(subset):
                    self.last_semidense_acceptance = f"accepted_loftr_subset_{len(subset)}"
                    return subset
            self.last_semidense_acceptance = "rejected_geometry_degradation"
            return TrackSet.empty()
        return candidate_tracks

    def _select_semidense_geometry_safe_subset(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        image_shape: tuple[int, int],
        before_geometry: GeometryStats,
        max_count: int,
        min_count: int,
        max_per_cell: int,
    ) -> TrackSet:
        if len(candidate_tracks) == 0 or max_count <= 0:
            return TrackSet.empty()
        rows = int(self.config.learned_coverage_rows)
        cols = int(self.config.learned_coverage_cols)
        cell_scores = _cell_need_scores(
            current_tracks.points,
            candidate_tracks.points,
            image_shape,
            rows=rows,
            cols=cols,
            target_cell_count=int(self.config.learned_target_cell_count),
        )
        geometry = _reference_geometry(current_tracks)
        geo_score = np.ones((len(candidate_tracks),), dtype=np.float32)
        if geometry["f_mat"] is not None:
            epi = _epipolar_errors(
                geometry["f_mat"],
                candidate_tracks.prev_points,
                candidate_tracks.points,
            )
            geo_score *= np.exp(
                -epi / max(1e-6, float(self.config.source_aware_loftr_max_epipolar_error))
            ).astype(np.float32)
        if geometry["h_mat"] is not None:
            hom = _homography_errors(
                geometry["h_mat"],
                candidate_tracks.prev_points,
                candidate_tracks.points,
            )
            geo_score *= np.exp(
                -hom / max(1e-6, float(self.config.source_aware_loftr_max_homography_error))
            ).astype(np.float32)
        scores = (
            candidate_tracks.qualities.astype(np.float32)
            * (0.35 + 0.65 * np.clip(cell_scores, 0.0, 1.0).astype(np.float32))
            * (0.35 + 0.65 * np.clip(geo_score, 0.0, 1.0).astype(np.float32))
        )
        order = _select_grid_quota_candidates(
            points=candidate_tracks.points,
            scores=scores,
            image_shape=image_shape,
            max_count=max(1, int(max_count)),
            min_distance=float(self.config.min_current_distance),
            rows=rows,
            cols=cols,
            max_per_cell=max(1, int(max_per_cell)),
        )
        if len(order) == 0:
            return TrackSet.empty()

        selected: list[int] = []
        for idx in order:
            trial_indices = np.asarray(selected + [int(idx)], dtype=np.int64)
            trial_candidates = _subset_tracks_by_indices(candidate_tracks, trial_indices)
            merged = KltTracker._append_tracks(current_tracks, trial_candidates)
            after_geometry = _track_geometry(merged)
            if _geometry_gate_accepts(
                before_geometry,
                after_geometry,
                max_f_drop=self.config.semidense_acceptance_max_f_inlier_drop,
                max_h_drop=self.config.semidense_acceptance_max_h_inlier_drop,
                max_epi_ratio=self.config.semidense_acceptance_max_epipolar_error_ratio,
                max_hom_ratio=self.config.semidense_acceptance_max_homography_error_ratio,
                residual_neutral=bool(self.config.semidense_acceptance_residual_neutral),
                max_epi_abs_increase=float(self.config.semidense_acceptance_max_epipolar_error_abs_increase),
                max_hom_abs_increase=float(self.config.semidense_acceptance_max_homography_error_abs_increase),
            ):
                selected.append(int(idx))
                if len(selected) >= max(1, int(max_count)):
                    break
        if len(selected) < max(1, int(min_count)):
            return TrackSet.empty()
        return _subset_tracks_by_indices(candidate_tracks, np.asarray(selected, dtype=np.int64))

    def _post_validate_semidense_candidates(
        self,
        current_tracks: TrackSet,
        candidate_tracks: TrackSet,
        image_shape: tuple[int, int],
    ) -> TrackSet:
        if len(candidate_tracks) == 0:
            return TrackSet.empty()
        valid = np.ones((len(candidate_tracks),), dtype=bool)
        valid &= candidate_tracks.qualities >= self.config.semidense_candidate_min_quality
        valid &= candidate_tracks.ncc_scores >= self.config.semidense_candidate_min_ncc
        valid &= candidate_tracks.fb_errors <= self.config.semidense_candidate_max_fb_error

        cell_scores = _cell_need_scores(
            current_tracks.points,
            candidate_tracks.points,
            image_shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            target_cell_count=self.config.learned_target_cell_count,
        )
        if self.config.semidense_candidate_allow_low_occupancy_cell:
            valid &= cell_scores > 0.0
        else:
            valid &= cell_scores >= self.config.semidense_fallback_min_coverage_score

        geometry = _reference_geometry(current_tracks)
        source_family = _source_family_from_sources(candidate_tracks.sources)
        max_epipolar = float(self.config.semidense_candidate_max_epipolar_error)
        max_homography = float(self.config.semidense_candidate_max_homography_error)
        if self.config.enable_three_layer_source_aware and source_family == "loftr":
            max_epipolar = min(max_epipolar, float(self.config.source_aware_loftr_max_epipolar_error))
            max_homography = min(max_homography, float(self.config.source_aware_loftr_max_homography_error))
        if geometry["f_mat"] is not None:
            epi = _epipolar_errors(geometry["f_mat"], candidate_tracks.prev_points, candidate_tracks.points)
            valid &= epi <= max_epipolar
        if geometry["h_mat"] is not None:
            hom = _homography_errors(geometry["h_mat"], candidate_tracks.prev_points, candidate_tracks.points)
            valid &= hom <= max_homography
        if not np.any(valid):
            self.last_semidense_acceptance = "rejected_all_candidates_post_validation"
            return TrackSet.empty()
        return _subset_tracks(candidate_tracks, valid)

    def _semidense_fallback_method(self) -> str:
        matcher = self.semidense_fallback_matcher
        name = str(getattr(matcher, "name", "none"))
        return name

    @staticmethod
    def _source_family_from_matcher(matcher: BaseMatcher | None) -> str:
        return _source_family_name(str(getattr(matcher, "name", "")))

    def _recover_lost_with_relaxed_lk(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        exclude_ids: set[int] | None = None,
    ) -> TrackSet:
        if not self.config.enable_lk_recovery:
            return TrackSet.empty()
        exclude_ids = exclude_ids or set()
        prev = self.klt.last_recovery_prev_image
        lost_points = self.klt.last_lost_prev_points
        lost_ids = self.klt.last_lost_ids
        lost_ages = self.klt.last_lost_ages
        if prev is None or len(lost_points) == 0:
            return TrackSet.empty()

        prev_pts = lost_points.reshape(-1, 1, 2).astype(np.float32)
        lk_params = dict(
            winSize=(self.config.lk_recovery_win_size, self.config.lk_recovery_win_size),
            maxLevel=self.config.lk_recovery_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01),
        )
        cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev, cur, prev_pts, None, **lk_params)
        if cur_pts is None or status is None:
            return TrackSet.empty()
        back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(cur, prev, cur_pts, None, **lk_params)
        if back_pts is None or back_status is None:
            return TrackSet.empty()

        prev_flat = prev_pts.reshape(-1, 2)
        cur_flat = cur_pts.reshape(-1, 2)
        back_flat = back_pts.reshape(-1, 2)
        fb_errors = np.linalg.norm(prev_flat - back_flat, axis=1).astype(np.float32)
        ncc = _patch_ncc(prev, cur, prev_flat, cur_flat, radius=5)
        valid = (
            (status.reshape(-1) > 0)
            & (back_status.reshape(-1) > 0)
            & (fb_errors <= self.config.lk_recovery_fb_threshold)
            & (ncc >= self.config.lk_recovery_min_ncc)
            & _in_border(cur_flat, cur.shape, border=self.klt.config.border)
        )
        if (
            self.config.enable_local_quality_map
            and self.config.local_quality_apply_to_candidate_scoring
            and self.config.local_quality_min_learned_score > 0.0
        ):
            valid &= self._point_quality_base(cur_flat, cur.shape, image_quality) >= float(
                self.config.local_quality_min_learned_score
            )
        if exclude_ids:
            valid &= ~np.asarray([int(track_id) in exclude_ids for track_id in lost_ids], dtype=bool)
        if len(current_tracks.points):
            for i, point in enumerate(cur_flat):
                if valid[i] and _too_close(point, current_tracks.points, self.config.min_current_distance):
                    valid[i] = False
        indices = np.where(valid)[0]
        if len(indices) == 0:
            return TrackSet.empty()

        score = ncc[indices] * np.exp(-fb_errors[indices] / max(1e-3, self.config.lk_recovery_fb_threshold))
        order = indices[np.argsort(-score)[: self.config.max_lk_recovered]]
        prev_arr = prev_flat[order].astype(np.float32)
        cur_arr = cur_flat[order].astype(np.float32)
        ids_arr = lost_ids[order].astype(np.int64)
        ages_arr = (lost_ages[order] + 1).astype(np.int32)
        fb_arr = fb_errors[order].astype(np.float32)
        ncc_arr = ncc[order].astype(np.float32)
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = self._point_quality_base(cur_arr, cur.shape, image_quality)
        fb_score = np.exp(-fb_arr / max(1e-3, self.config.lk_recovery_fb_threshold))
        age_score = np.clip(ages_arr.astype(np.float32) / 20.0, 0.0, 1.0)
        quality = np.clip(
            local_quality
            * (0.20 + 0.80 * local_tex)
            * (0.20 + 0.80 * fb_score)
            * (0.20 + 0.80 * ncc_arr)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)

        return TrackSet(
            ids=ids_arr,
            prev_points=prev_arr,
            points=cur_arr,
            ages=ages_arr,
            fb_errors=fb_arr,
            ncc_scores=ncc_arr,
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=["lk_recovery"] * len(ids_arr),
        )

    def _recover_lost_with_orb(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        exclude_ids: set[int],
    ) -> TrackSet:
        prev = self.klt.last_recovery_prev_image
        lost_points = self.klt.last_lost_prev_points
        lost_ids = self.klt.last_lost_ids
        lost_ages = self.klt.last_lost_ages
        if prev is None or len(lost_points) == 0:
            return TrackSet.empty()

        kp0, desc0 = self.orb.detectAndCompute(prev, None)
        kp1, desc1 = self.orb.detectAndCompute(cur, None)
        if desc0 is None or desc1 is None or not kp0 or not kp1:
            return TrackSet.empty()
        matches = self.matcher.match(desc0, desc1)
        matches = [m for m in matches if m.distance <= self.config.max_hamming_distance]
        matches.sort(key=lambda item: item.distance)

        current_points = current_tracks.points.copy()
        recovered_prev = []
        recovered_cur = []
        recovered_ids = []
        recovered_ages = []
        distances = []
        used_lost: set[int] = set()
        used_current: list[np.ndarray] = []

        for match in matches:
            prev_pt = np.asarray(kp0[match.queryIdx].pt, dtype=np.float32)
            cur_pt = np.asarray(kp1[match.trainIdx].pt, dtype=np.float32)
            lost_idx = _nearest_index(lost_points, prev_pt)
            if lost_idx is None or lost_idx in used_lost:
                continue
            if int(lost_ids[lost_idx]) in exclude_ids:
                continue
            if np.linalg.norm(lost_points[lost_idx] - prev_pt) > self.config.lost_association_radius:
                continue
            if _too_close(cur_pt, current_points, self.config.min_current_distance):
                continue
            if used_current and _too_close(cur_pt, np.vstack(used_current), self.config.min_current_distance):
                continue
            recovered_prev.append(lost_points[lost_idx])
            recovered_cur.append(cur_pt)
            recovered_ids.append(lost_ids[lost_idx])
            recovered_ages.append(lost_ages[lost_idx] + 1)
            distances.append(match.distance)
            used_lost.add(lost_idx)
            used_current.append(cur_pt.reshape(1, 2))
            if len(recovered_ids) >= self.config.max_recovered:
                break

        if not recovered_ids:
            return TrackSet.empty()

        prev_arr = np.asarray(recovered_prev, dtype=np.float32)
        cur_arr = np.asarray(recovered_cur, dtype=np.float32)
        ncc = _patch_ncc(prev, cur, prev_arr, cur_arr, radius=5)
        valid = ncc >= self.config.min_recovery_ncc
        if (
            self.config.enable_local_quality_map
            and self.config.local_quality_apply_to_candidate_scoring
            and self.config.local_quality_min_learned_score > 0.0
        ):
            valid &= self._point_quality_base(cur_arr, cur.shape, image_quality) >= float(
                self.config.local_quality_min_learned_score
            )
        if not np.any(valid):
            return TrackSet.empty()

        prev_arr = prev_arr[valid]
        cur_arr = cur_arr[valid]
        ids_arr = np.asarray(recovered_ids, dtype=np.int64)[valid]
        ages_arr = np.asarray(recovered_ages, dtype=np.int32)[valid]
        dist_arr = np.asarray(distances, dtype=np.float32)[valid]
        ncc = ncc[valid]
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = self._point_quality_base(cur_arr, cur.shape, image_quality)
        descriptor_score = np.clip(1.0 - dist_arr / max(1.0, float(self.config.max_hamming_distance)), 0.0, 1.0)
        age_score = np.clip(ages_arr.astype(np.float32) / 20.0, 0.0, 1.0)
        quality = np.clip(
            local_quality
            * (0.25 + 0.75 * local_tex)
            * (0.30 + 0.70 * descriptor_score)
            * (0.30 + 0.70 * ncc)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)

        return TrackSet(
            ids=ids_arr,
            prev_points=prev_arr,
            points=cur_arr,
            ages=ages_arr,
            fb_errors=dist_arr,
            ncc_scores=ncc.astype(np.float32),
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=["orb_recovery"] * len(ids_arr),
        )

    def _replenish_new_tracks(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        geometry_mode: str = "unknown",
    ) -> TrackSet:
        if self.config.enable_gftt_confirmation or self.config.enable_temporal_gftt_admission:
            self._queue_pending_gftt(cur, tracks)
            return self._seed_immediate_gftt_if_sparse(cur, image_quality, tracks)
        target_max_features = int(self.klt.config.max_features)
        if self.config.learned_init_requires_klt_confirmation and len(self._pending_learned_points) > 0:
            reserve = min(
                max(0, int(self.config.learned_confirmation_reserve_capacity)),
                int(len(self._pending_learned_points)),
            )
            target_max_features = max(0, target_max_features - reserve)
        need_new = max(0, target_max_features - len(self.klt.points))
        if need_new <= 0:
            return TrackSet.empty()
        if self.config.enable_adaptive_birth_budget:
            need_new = min(
                need_new,
                self._adaptive_birth_budget(
                    cur,
                    image_quality,
                    tracks,
                    source="gftt",
                    geometry_mode=geometry_mode,
                ),
            )
            if need_new <= 0:
                return TrackSet.empty()
        before = len(self.klt.points)
        added = self.klt._detect_new(cur, need_new)
        if added <= 0:
            return TrackSet.empty()
        new_slice = slice(before, before + added)
        points = self.klt.points[new_slice]
        ids = self.klt.ids[new_slice]
        ages = self.klt.ages[new_slice]
        local_tex = local_texture_scores(cur, points)
        local_quality = self._point_quality_base(points, cur.shape, image_quality)
        quality = np.clip(local_quality * (0.35 + 0.65 * local_tex), self.config.q_min, 1.0).astype(np.float32)
        if self.config.enable_adaptive_birth_budget:
            cell_scores = _cell_need_scores(
                tracks.points,
                points,
                cur.shape,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                target_cell_count=self.config.learned_target_cell_count,
            )
            valid = (
                (quality >= float(self.config.adaptive_birth_min_quality))
                | (cell_scores >= float(self.config.adaptive_birth_min_cell_score))
            )
            if (
                self.config.enable_local_quality_map
                and self.config.local_quality_apply_to_candidate_scoring
                and self.config.local_quality_min_birth_score > 0.0
            ):
                valid &= local_quality >= float(self.config.local_quality_min_birth_score)
            if not np.any(valid):
                self._replace_klt_detected_tail(before, np.empty((0, 2), dtype=np.float32), np.empty((0,), dtype=np.int64), np.empty((0,), dtype=np.int32))
                return TrackSet.empty()
            points = points[valid]
            ids = ids[valid]
            ages = ages[valid]
            local_tex = local_tex[valid]
            local_quality = local_quality[valid]
            quality = quality[valid]
            added = len(points)
            self._replace_klt_detected_tail(before, points, ids, ages)
        elif (
            self.config.enable_local_quality_map
            and self.config.local_quality_apply_to_candidate_scoring
            and self.config.local_quality_min_birth_score > 0.0
        ):
            valid = local_quality >= float(self.config.local_quality_min_birth_score)
            if not np.any(valid):
                self._replace_klt_detected_tail(before, np.empty((0, 2), dtype=np.float32), np.empty((0,), dtype=np.int64), np.empty((0,), dtype=np.int32))
                return TrackSet.empty()
            points = points[valid]
            ids = ids[valid]
            ages = ages[valid]
            local_tex = local_tex[valid]
            quality = quality[valid]
            added = len(points)
            self._replace_klt_detected_tail(before, points, ids, ages)
        return TrackSet(
            ids=ids.copy(),
            prev_points=points.copy(),
            points=points.copy(),
            ages=ages.copy(),
            fb_errors=np.zeros((added,), dtype=np.float32),
            ncc_scores=np.ones((added,), dtype=np.float32),
            local_texture=local_tex,
            qualities=quality,
            sources=["gftt"] * added,
        )

    def _adaptive_birth_budget(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
        source: str,
        geometry_mode: str = "unknown",
    ) -> int:
        remaining = max(0, self.klt.config.max_features - len(self.klt.points))
        if remaining <= 0:
            return 0
        grid = grid_stats(tracks.points, cur.shape, rows=self.config.learned_coverage_rows, cols=self.config.learned_coverage_cols)
        health = float(getattr(self, "last_track_health_score", 1.0))
        degraded = (
            image_quality.degradation_score >= self.config.learned_init_min_degradation
            or image_quality.flat_region_ratio >= self.config.learned_init_min_flat_region_ratio
            or image_quality.grid_texture_score <= self.config.min_grid_texture_score_for_recovery
        )
        severe = str(geometry_mode) == "severe_low_texture" or (
            image_quality.flat_region_ratio >= 0.90
            and grid.coverage <= max(0.55, self.config.learned_init_critical_grid_coverage)
        )
        fraction = float(self.config.adaptive_birth_max_fraction)
        if degraded:
            fraction = min(fraction, float(self.config.adaptive_birth_low_texture_fraction))
        if health < float(self.config.health_min_score_for_recovery):
            fraction = min(fraction, float(self.config.adaptive_birth_low_health_fraction))
        if severe:
            fraction = min(fraction, float(self.config.adaptive_birth_severe_fraction))
        if source == "learned_init":
            fraction *= 0.75
        coverage_deficit = max(0.0, float(self.config.min_grid_coverage_for_recovery) - float(grid.coverage))
        coverage_boost = int(round(coverage_deficit * self.config.learned_coverage_rows * self.config.learned_coverage_cols))
        budget = int(round(self.klt.config.max_features * max(0.0, fraction))) + coverage_boost
        budget = max(int(self.config.adaptive_birth_min_budget), budget)
        return max(0, min(remaining, budget))

    def _confirm_pending_gftt(
        self,
        prev: np.ndarray | None,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        pending_points: np.ndarray,
        source_label: str = "gftt_confirmed",
        geometry_label: str = "gftt_confirmation",
        max_confirmed: int | None = None,
        force: bool = False,
    ) -> TrackSet:
        confirmation_diagnostics = {
            "pending_input": int(len(pending_points)),
            "forward_pass": 0,
            "backward_pass": 0,
            "fb_pass": 0,
            "ncc_pass": 0,
            "border_pass": 0,
            "distance_pass": 0,
            "geometry_pass": 0,
            "selected": 0,
            "admitted": 0,
        }
        self.last_confirmation_diagnostics[geometry_label] = confirmation_diagnostics
        if not force and not (
            self.config.enable_gftt_confirmation
            or self.config.enable_temporal_gftt_admission
        ):
            return TrackSet.empty()
        if prev is None or len(pending_points) == 0:
            return TrackSet.empty()
        prev_pts = pending_points.reshape(-1, 1, 2).astype(np.float32)
        lk_params = dict(
            winSize=(self.klt.config.lk_win_size, self.klt.config.lk_win_size),
            maxLevel=self.klt.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev, cur, prev_pts, None, **lk_params)
        if cur_pts is None or status is None:
            return TrackSet.empty()
        back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(cur, prev, cur_pts, None, **lk_params)
        if back_pts is None or back_status is None:
            return TrackSet.empty()

        prev_flat = prev_pts.reshape(-1, 2)
        cur_flat = cur_pts.reshape(-1, 2)
        back_flat = back_pts.reshape(-1, 2)
        fb_errors = np.linalg.norm(prev_flat - back_flat, axis=1).astype(np.float32)
        ncc = _patch_ncc(prev, cur, prev_flat, cur_flat, radius=self.klt.config.patch_radius)
        forward_pass = status.reshape(-1) > 0
        backward_pass = forward_pass & (back_status.reshape(-1) > 0)
        fb_pass = backward_pass & np.isfinite(fb_errors) & (
            fb_errors <= self.config.gftt_confirmation_fb_threshold
        )
        ncc_pass = fb_pass & np.isfinite(ncc) & (
            ncc >= self.config.gftt_confirmation_min_ncc
        )
        border_pass = ncc_pass & _in_border(
            cur_flat,
            cur.shape,
            border=self.klt.config.border,
        )
        valid = border_pass.copy()
        confirmation_diagnostics.update(
            {
                "forward_pass": int(np.sum(forward_pass)),
                "backward_pass": int(np.sum(backward_pass)),
                "fb_pass": int(np.sum(fb_pass)),
                "ncc_pass": int(np.sum(ncc_pass)),
                "border_pass": int(np.sum(border_pass)),
            }
        )
        if len(current_tracks.points):
            for idx, point in enumerate(cur_flat):
                if valid[idx] and _too_close(point, current_tracks.points, self.config.gftt_confirmation_min_distance):
                    valid[idx] = False
        confirmation_diagnostics["distance_pass"] = int(np.sum(valid))
        if not np.any(valid):
            return TrackSet.empty()

        prev_arr = prev_flat[valid].astype(np.float32)
        cur_arr = cur_flat[valid].astype(np.float32)
        fb_arr = fb_errors[valid].astype(np.float32)
        ncc_arr = ncc[valid].astype(np.float32)
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = self._point_quality_base(cur_arr, cur.shape, image_quality)
        fb_score = np.exp(-fb_arr / max(1e-3, self.config.gftt_confirmation_fb_threshold))
        quality = np.clip(
            local_quality
            * (0.25 + 0.75 * local_tex)
            * (0.25 + 0.75 * fb_score)
            * (0.30 + 0.70 * ncc_arr),
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        candidate = TrackSet(
            ids=np.arange(len(cur_arr), dtype=np.int64),
            prev_points=prev_arr,
            points=cur_arr,
            ages=np.full((len(cur_arr),), 2, dtype=np.int32),
            fb_errors=fb_arr,
            ncc_scores=ncc_arr,
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=[source_label] * len(cur_arr),
        )
        candidate = self._filter_candidate_geometry(current_tracks, candidate, geometry_label)
        confirmation_diagnostics["geometry_pass"] = int(len(candidate))
        if len(candidate) == 0:
            return TrackSet.empty()
        candidate = self._select_confirmed_gftt_for_coverage(
            cur,
            current_tracks,
            candidate,
            max_confirmed_override=max_confirmed,
        )
        confirmation_diagnostics["selected"] = int(len(candidate))
        if len(candidate) == 0:
            return TrackSet.empty()
        if source_label.startswith("learned") and self.config.learned_confirmation_geometry_safe:
            candidate = self._accept_geometry_safe_batch(
                current_tracks,
                candidate,
                geometry_label,
            )
            if len(candidate) == 0:
                return TrackSet.empty()
        confirmation_diagnostics["admitted"] = int(len(candidate))
        # Candidate IDs above are private, batch-local placeholders.  Allocate
        # globally unique public IDs only after every temporal/geometry check
        # has accepted the candidate batch.
        return self._assign_fresh_klt_ids(candidate)

    def _select_confirmed_gftt_for_coverage(
        self,
        cur: np.ndarray,
        current_tracks: TrackSet,
        candidate: TrackSet,
        max_confirmed_override: int | None = None,
        sidecar_extra_capacity: int = 0,
    ) -> TrackSet:
        if len(candidate) == 0:
            return TrackSet.empty()
        max_confirmed = (
            int(self.config.gftt_confirmation_max_confirmed)
            if max_confirmed_override is None
            else int(max_confirmed_override)
        )
        if self.config.gftt_confirmation_respect_max_features:
            output_capacity = self.klt.config.max_features + max(0, int(sidecar_extra_capacity))
            remaining_capacity = max(0, output_capacity - len(self.klt.points))
            if remaining_capacity <= 0:
                return TrackSet.empty()
            max_confirmed = remaining_capacity if max_confirmed <= 0 else min(max_confirmed, remaining_capacity)
        if max_confirmed <= 0:
            max_confirmed = len(candidate)
        max_confirmed = min(len(candidate), max_confirmed)
        if max_confirmed >= len(candidate) and not self.config.gftt_confirmation_enable_confirmed_grid_select:
            return candidate

        cell_scores = _cell_need_scores(
            current_tracks.points,
            candidate.points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            target_cell_count=self.config.learned_target_cell_count,
        )
        scores = (
            np.clip(candidate.qualities.astype(np.float32), 0.0, 1.0)
            * (0.35 + 0.65 * np.clip(candidate.ncc_scores.astype(np.float32), 0.0, 1.0))
            * (0.35 + 0.65 * cell_scores.astype(np.float32))
        )
        if self.config.gftt_confirmation_enable_confirmed_grid_select:
            selected = _select_grid_quota_candidates(
                points=candidate.points,
                scores=scores,
                image_shape=cur.shape,
                max_count=max_confirmed,
                min_distance=self.config.gftt_confirmation_min_distance,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                max_per_cell=self.config.gftt_confirmation_confirmed_max_per_cell,
            )
        else:
            selected = np.argsort(-scores)[:max_confirmed].astype(np.int64)
        if len(selected) == 0:
            return TrackSet.empty()
        mask = np.zeros((len(candidate),), dtype=bool)
        mask[selected] = True
        return _subset_tracks(candidate, mask)

    def _queue_pending_gftt(self, cur: np.ndarray, tracks: TrackSet) -> None:
        shadow_replacement = bool(
            self.config.enable_temporal_gftt_admission
            and self.config.enable_temporal_gftt_shadow_replacement
        )
        need_new = (
            int(self.klt.config.max_features)
            if shadow_replacement
            else max(0, self.klt.config.max_features - len(self.klt.points))
        )
        if need_new <= 0:
            self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
            self._update_candidate_bank_stats(cur.shape, tracks)
            return
        max_pending = max(0, int(self.config.gftt_confirmation_max_pending))
        if max_pending <= 0:
            self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
            self._update_candidate_bank_stats(cur.shape, tracks)
            return
        detect_count = (
            max_pending
            if shadow_replacement
            else int(
                np.ceil(
                    need_new
                    * max(1.0, float(self.config.gftt_confirmation_detect_factor))
                )
            )
        )
        detect_count = min(max_pending, max(need_new, detect_count))
        mask = np.full(cur.shape, 255, dtype=np.uint8)
        if not shadow_replacement:
            exclusion_radius = max(1, int(round(self.klt.config.min_distance)))
            for x, y in tracks.points.reshape(-1, 2):
                cv2.circle(mask, (int(round(x)), int(round(y))), exclusion_radius, 0, -1)
        pts = cv2.goodFeaturesToTrack(
            cur,
            maxCorners=detect_count,
            qualityLevel=self.klt.config.quality_level,
            minDistance=self.klt.config.min_distance,
            mask=mask,
            blockSize=self.klt.config.block_size,
        )
        proposal_arrays: list[np.ndarray] = []
        if pts is not None:
            proposal_arrays.append(pts.reshape(-1, 2).astype(np.float32))
        dual_pool = bool(
            shadow_replacement
            and self.config.enable_temporal_gftt_dual_pool_replenishment
        )
        if dual_pool:
            coverage_mask = np.full(cur.shape, 255, dtype=np.uint8)
            exclusion_radius = max(1, int(round(self.klt.config.min_distance)))
            for x, y in tracks.points.reshape(-1, 2):
                cv2.circle(
                    coverage_mask,
                    (int(round(x)), int(round(y))),
                    exclusion_radius,
                    0,
                    -1,
                )
            coverage_pts = cv2.goodFeaturesToTrack(
                cur,
                maxCorners=max_pending,
                qualityLevel=self.klt.config.quality_level,
                minDistance=self.klt.config.min_distance,
                mask=coverage_mask,
                blockSize=self.klt.config.block_size,
            )
            if coverage_pts is not None:
                proposal_arrays.append(
                    coverage_pts.reshape(-1, 2).astype(np.float32)
                )
        if not proposal_arrays:
            self._pending_gftt_points = np.empty((0, 2), dtype=np.float32)
            self._update_candidate_bank_stats(cur.shape, tracks)
            return
        pending = np.vstack(proposal_arrays).astype(np.float32)
        if self.config.gftt_confirmation_enable_pending_grid_quota and len(pending) > 0:
            local_tex = local_texture_scores(cur, pending)
            cell_scores = _cell_need_scores(
                tracks.points,
                pending,
                cur.shape,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                target_cell_count=self.config.learned_target_cell_count,
            )
            scores = local_tex.astype(np.float32) * (0.35 + 0.65 * cell_scores.astype(np.float32))
            selected = _select_grid_quota_candidates(
                points=pending,
                scores=scores,
                image_shape=cur.shape,
                max_count=min(max_pending, len(pending)),
                min_distance=self.config.gftt_confirmation_min_distance,
                rows=self.config.learned_coverage_rows,
                cols=self.config.learned_coverage_cols,
                max_per_cell=self.config.gftt_confirmation_pending_max_per_cell,
            )
            if len(selected):
                pending = pending[selected].astype(np.float32)
        elif len(pending) > max_pending:
            pending = pending[:max_pending].astype(np.float32)
        self._pending_gftt_points = pending.astype(np.float32)
        self._update_candidate_bank_stats(cur.shape, tracks)

    def _queue_pending_learned(self, candidate_tracks: TrackSet) -> None:
        if len(candidate_tracks) == 0:
            return
        max_pending = max(0, int(self.config.learned_confirmation_max_pending))
        if max_pending <= 0:
            self._pending_learned_points = np.empty((0, 2), dtype=np.float32)
            self._pending_learned_promotions = []
            return
        points = candidate_tracks.points.astype(np.float32)
        qualities = candidate_tracks.qualities.astype(np.float32)
        sources = list(candidate_tracks.sources)
        if len(points) > max_pending:
            scores = candidate_tracks.qualities.astype(np.float32)
            selected = np.argsort(-scores)[:max_pending]
            points = points[selected].astype(np.float32)
            qualities = qualities[selected].astype(np.float32)
            sources = [sources[int(idx)] for idx in selected]
        self.last_semidense_queued_pending = int(
            sum(1 for source in sources if _source_family_name(source) == "loftr")
        )
        min_frames = max(
            int(self.config.learned_confirmation_min_frames),
            max((self._source_confirmation_min_frames(source) for source in sources), default=1),
        )
        if min_frames <= 1:
            self._pending_learned_points = (
                np.vstack([self._pending_learned_points, points]).astype(np.float32)
                if len(self._pending_learned_points)
                else points
            )
        else:
            if self.klt.prev_image is not None:
                self._pending_learned_promotions.append(
                    _PendingPromotion(
                        prev_image=self.klt.prev_image.copy(),
                        points=points,
                        ages=np.ones((len(points),), dtype=np.int32),
                        qualities=qualities,
                        sources=sources,
                    )
                )
            self._pending_learned_points = np.empty((0, 2), dtype=np.float32)
        self.last_learned_candidate_count = int(len(points))

    def _requires_source_aware_confirmation(self, candidate_tracks: TrackSet) -> bool:
        if not self.config.enable_three_layer_source_aware:
            return False
        return any(self._source_confirmation_min_frames(source) > 1 for source in candidate_tracks.sources)

    def _source_confirmation_min_frames(self, source: str) -> int:
        if (
            self.config.enable_three_layer_source_aware
            and self.config.source_aware_loftr_requires_confirmation
            and _source_family_name(source) == "loftr"
        ):
            return max(3, int(self.config.source_aware_loftr_min_confirmation_frames))
        return max(1, int(self.config.learned_confirmation_min_frames))

    def _advance_pending_learned_promotions(
        self,
        pending: list[_PendingPromotion],
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
    ) -> TrackSet:
        if not pending:
            return TrackSet.empty()
        queued_current = (
            list(self._pending_learned_promotions)
            if self.config.learned_confirmation_preserve_new_pending
            else []
        )
        confirmed = TrackSet.empty()
        next_pending: list[_PendingPromotion] = []
        for item in pending:
            tracked = self._track_pending_promotion_once(item, cur, image_quality, current_tracks)
            if len(tracked) == 0:
                continue
            min_frames_by_source = np.asarray(
                [self._source_confirmation_min_frames(source) for source in tracked.sources],
                dtype=np.int32,
            )
            mature = tracked.ages >= min_frames_by_source
            if np.any(mature):
                mature_tracks = _subset_tracks(tracked, mature)
                mature_tracks = self._select_confirmed_gftt_for_coverage(
                    cur,
                    current_tracks,
                    mature_tracks,
                    max_confirmed_override=self._source_confirmation_max_confirmed(mature_tracks.sources),
                    sidecar_extra_capacity=(
                        self.config.learned_sidecar_max_extra
                        if self.config.preserve_klt_replenish
                        else 0
                    ),
                )
                if len(mature_tracks) and self.config.learned_confirmation_geometry_safe:
                    mature_tracks = self._accept_geometry_safe_batch(
                        current_tracks,
                        mature_tracks,
                        "learned_confirmation",
                    )
                if len(mature_tracks):
                    mature_tracks = self._assign_fresh_klt_ids(mature_tracks)
                    confirmed = KltTracker._append_tracks(confirmed, mature_tracks)
            keep_pending = ~mature
            if np.any(keep_pending):
                pending_tracks = _subset_tracks(tracked, keep_pending)
                next_pending.append(
                    _PendingPromotion(
                        prev_image=cur.copy(),
                        points=pending_tracks.points.astype(np.float32),
                        ages=pending_tracks.ages.astype(np.int32),
                        qualities=pending_tracks.qualities.astype(np.float32),
                        sources=list(pending_tracks.sources),
                    )
                )
        self._pending_learned_promotions = next_pending + queued_current
        return confirmed

    def _track_pending_promotion_once(
        self,
        item: _PendingPromotion,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
    ) -> TrackSet:
        if len(item.points) == 0:
            return TrackSet.empty()
        prev_pts = item.points.reshape(-1, 1, 2).astype(np.float32)
        lk_params = dict(
            winSize=(self.klt.config.lk_win_size, self.klt.config.lk_win_size),
            maxLevel=self.klt.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(item.prev_image, cur, prev_pts, None, **lk_params)
        if cur_pts is None or status is None:
            return TrackSet.empty()
        back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(cur, item.prev_image, cur_pts, None, **lk_params)
        if back_pts is None or back_status is None:
            return TrackSet.empty()
        prev_flat = prev_pts.reshape(-1, 2)
        cur_flat = cur_pts.reshape(-1, 2)
        back_flat = back_pts.reshape(-1, 2)
        fb_errors = np.linalg.norm(prev_flat - back_flat, axis=1).astype(np.float32)
        ncc = _patch_ncc(item.prev_image, cur, prev_flat, cur_flat, radius=self.klt.config.patch_radius)
        max_fb = np.asarray(
            [self._promotion_max_fb_error(source) for source in item.sources],
            dtype=np.float32,
        )
        min_ncc = np.asarray(
            [self._promotion_min_ncc(source) for source in item.sources],
            dtype=np.float32,
        )
        valid = (
            (status.reshape(-1) > 0)
            & (back_status.reshape(-1) > 0)
            & (fb_errors <= max_fb)
            & (ncc >= min_ncc)
            & _in_border(cur_flat, cur.shape, border=self.klt.config.border)
        )
        if len(current_tracks.points):
            for idx, point in enumerate(cur_flat):
                if valid[idx] and _too_close(point, current_tracks.points, self.config.gftt_confirmation_min_distance):
                    valid[idx] = False
        if not np.any(valid):
            return TrackSet.empty()
        prev_arr = prev_flat[valid].astype(np.float32)
        cur_arr = cur_flat[valid].astype(np.float32)
        fb_arr = fb_errors[valid].astype(np.float32)
        ncc_arr = ncc[valid].astype(np.float32)
        old_quality = item.qualities[valid].astype(np.float32)
        source_arr = [item.sources[int(idx)] for idx in np.flatnonzero(valid)]
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = self._point_quality_base(cur_arr, cur.shape, image_quality)
        max_fb_arr = max_fb[valid].astype(np.float32)
        fb_score = np.exp(-fb_arr / np.maximum(1e-3, max_fb_arr))
        quality = np.clip(
            np.minimum(old_quality, local_quality)
            * (0.25 + 0.75 * local_tex)
            * (0.25 + 0.75 * fb_score)
            * (0.30 + 0.70 * ncc_arr),
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        for idx, source in enumerate(source_arr):
            if _source_family_name(source) == "loftr":
                quality[idx] = float(
                    np.clip(
                        quality[idx] * float(self.config.promotion_loftr_quality_scale),
                        self.config.q_min,
                        1.0,
                    )
                )
        tracks = TrackSet(
            ids=np.arange(len(cur_arr), dtype=np.int64),
            prev_points=prev_arr,
            points=cur_arr,
            ages=(item.ages[valid] + 1).astype(np.int32),
            fb_errors=fb_arr,
            ncc_scores=ncc_arr,
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=[self._confirmed_source_label(source) for source in source_arr],
        )
        if self.config.enable_three_layer_source_aware and any(_source_family_name(source) == "loftr" for source in source_arr):
            tracks = self._filter_candidate_geometry(current_tracks, tracks, "learned_confirmation")
        return tracks

    def _promotion_max_fb_error(self, source: str) -> float:
        source_l = str(source).lower()
        if "loftr" in source_l:
            return float(self.config.promotion_loftr_max_fb_error)
        if "xfeat" in source_l:
            return float(self.config.promotion_xfeat_max_fb_error)
        if "lightglue" in source_l or "superpoint" in source_l:
            return float(self.config.promotion_lightglue_max_fb_error)
        return float(self.config.gftt_confirmation_fb_threshold)

    def _promotion_min_ncc(self, source: str) -> float:
        source_l = str(source).lower()
        if "loftr" in source_l:
            return float(self.config.promotion_loftr_min_ncc)
        if "xfeat" in source_l:
            return float(self.config.promotion_xfeat_min_ncc)
        if "lightglue" in source_l or "superpoint" in source_l:
            return float(self.config.promotion_lightglue_min_ncc)
        return float(self.config.gftt_confirmation_min_ncc)

    def _source_confirmation_max_confirmed(self, sources: list[str]) -> int:
        max_confirmed = int(self.config.learned_confirmation_max_confirmed)
        families = {_source_family_name(source) for source in sources}
        if "xfeat" in families:
            source_cap = int(self.config.promotion_xfeat_max_confirmed)
            if source_cap > 0:
                max_confirmed = source_cap if max_confirmed <= 0 else min(max_confirmed, source_cap)
        if "superpoint_lightglue" in families:
            source_cap = int(self.config.promotion_lightglue_max_confirmed)
            if source_cap > 0:
                max_confirmed = source_cap if max_confirmed <= 0 else min(max_confirmed, source_cap)
        if "loftr" in families:
            source_cap = int(self.config.promotion_loftr_max_confirmed)
            if source_cap > 0:
                max_confirmed = source_cap if max_confirmed <= 0 else min(max_confirmed, source_cap)
        return max_confirmed

    @staticmethod
    def _confirmed_source_label(source: str) -> str:
        source_l = str(source).lower()
        if "loftr" in source_l:
            return "loftr_confirmed"
        if "xfeat_star" in source_l:
            return "xfeat_star_confirmed"
        if "xfeat" in source_l:
            return "xfeat_confirmed"
        if "lightglue" in source_l or "superpoint" in source_l:
            return "superpoint_lightglue_confirmed"
        if "classical_gftt" in source_l:
            return "classical_gftt_confirmed"
        return "learned_confirmed"

    def _update_candidate_bank_stats(self, image_shape: tuple[int, int], tracks: TrackSet) -> None:
        pending = self._pending_gftt_points.astype(np.float32)
        rows = self.config.learned_coverage_rows
        cols = self.config.learned_coverage_cols
        stable_grid = grid_stats(tracks.points, image_shape, rows=rows, cols=cols)
        candidate_grid = grid_stats(pending, image_shape, rows=rows, cols=cols)
        if len(tracks.points) and len(pending):
            combined_points = np.vstack([tracks.points, pending]).astype(np.float32)
        elif len(pending):
            combined_points = pending
        else:
            combined_points = tracks.points
        combined_grid = grid_stats(combined_points, image_shape, rows=rows, cols=cols)
        self.last_candidate_bank_count = int(len(pending))
        self.last_candidate_bank_coverage = float(candidate_grid.coverage)
        self.last_stable_candidate_grid_coverage = float(combined_grid.coverage)
        self.last_candidate_bank_grid_gain = float(max(0.0, combined_grid.coverage - stable_grid.coverage))

    def _seed_immediate_gftt_if_sparse(
        self,
        cur: np.ndarray,
        image_quality: ImageQuality,
        tracks: TrackSet,
    ) -> TrackSet:
        if len(self._pending_gftt_points) == 0:
            return TrackSet.empty()
        remaining_capacity = max(0, self.klt.config.max_features - len(self.klt.points))
        if remaining_capacity <= 0:
            return TrackSet.empty()
        grid = grid_stats(tracks.points, cur.shape, rows=self.config.learned_coverage_rows, cols=self.config.learned_coverage_cols)
        track_deficit = max(0, int(self.config.gftt_confirmation_min_output_tracks) - len(tracks))
        coverage_deficit = grid.coverage < float(self.config.gftt_confirmation_min_output_coverage)
        if track_deficit <= 0 and not coverage_deficit:
            return TrackSet.empty()

        fraction_budget = int(round(self.klt.config.max_features * float(self.config.gftt_confirmation_immediate_fraction)))
        budget = max(track_deficit, fraction_budget if coverage_deficit else 0)
        budget = min(
            remaining_capacity,
            max(0, int(self.config.gftt_confirmation_immediate_max)),
            max(0, budget),
        )
        if budget <= 0:
            return TrackSet.empty()

        candidates = self._pending_gftt_points.astype(np.float32)
        local_tex = local_texture_scores(cur, candidates)
        valid = local_tex >= float(self.config.gftt_confirmation_immediate_min_texture)
        if len(tracks.points):
            for idx, point in enumerate(candidates):
                if valid[idx] and _too_close(point, tracks.points, self.config.gftt_confirmation_min_distance):
                    valid[idx] = False
        if not np.any(valid):
            return TrackSet.empty()

        valid_indices = np.where(valid)[0]
        candidate_points = candidates[valid]
        candidate_tex = local_tex[valid]
        cell_scores = _cell_need_scores(
            tracks.points,
            candidate_points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            target_cell_count=self.config.learned_target_cell_count,
        )
        scores = candidate_tex.astype(np.float32) * (0.35 + 0.65 * cell_scores.astype(np.float32))
        selected_local = _select_grid_quota_candidates(
            points=candidate_points,
            scores=scores,
            image_shape=cur.shape,
            max_count=budget,
            min_distance=self.config.gftt_confirmation_min_distance,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
            max_per_cell=self.config.gftt_confirmation_immediate_max_per_cell,
        )
        if len(selected_local) == 0:
            return TrackSet.empty()
        selected_pending = valid_indices[selected_local]
        selected_points = candidates[selected_pending].astype(np.float32)
        after_grid = grid_stats(
            np.vstack([tracks.points, selected_points]).astype(np.float32)
            if len(tracks.points)
            else selected_points,
            cur.shape,
            rows=self.config.learned_coverage_rows,
            cols=self.config.learned_coverage_cols,
        )
        grid_gain = after_grid.coverage - grid.coverage
        severe_sparse = len(tracks) < int(self.config.gftt_confirmation_immediate_severe_min_tracks)
        if grid_gain < float(self.config.gftt_confirmation_immediate_min_grid_gain) and not severe_sparse:
            return TrackSet.empty()
        keep_pending = np.ones((len(self._pending_gftt_points),), dtype=bool)
        keep_pending[selected_pending] = False
        self._pending_gftt_points = self._pending_gftt_points[keep_pending].astype(np.float32)

        ids = np.arange(self.klt.next_id, self.klt.next_id + len(selected_points), dtype=np.int64)
        self.klt.next_id += len(selected_points)
        ages = np.ones((len(selected_points),), dtype=np.int32)
        selected_tex = local_texture_scores(cur, selected_points)
        selected_local_quality = self._point_quality_base(selected_points, cur.shape, image_quality)
        quality = np.clip(
            selected_local_quality * (0.35 + 0.65 * selected_tex),
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        self.klt.points = np.vstack([self.klt.points, selected_points]).astype(np.float32)
        self.klt.ids = np.concatenate([self.klt.ids, ids]).astype(np.int64)
        self.klt.ages = np.concatenate([self.klt.ages, ages]).astype(np.int32)
        return TrackSet(
            ids=ids.copy(),
            prev_points=selected_points.copy(),
            points=selected_points.copy(),
            ages=ages.copy(),
            fb_errors=np.zeros((len(selected_points),), dtype=np.float32),
            ncc_scores=np.ones((len(selected_points),), dtype=np.float32),
            local_texture=selected_tex.astype(np.float32),
            qualities=quality,
            sources=["gftt_seed"] * len(selected_points),
        )

    def _append_to_klt_state(self, recovered: TrackSet) -> None:
        self.klt.points = np.vstack([self.klt.points, recovered.points]).astype(np.float32)
        self.klt.ids = np.concatenate([self.klt.ids, recovered.ids]).astype(np.int64)
        self.klt.ages = np.concatenate([self.klt.ages, recovered.ages]).astype(np.int32)

    def _assign_fresh_klt_ids(self, tracks: TrackSet) -> TrackSet:
        if len(tracks) == 0:
            return tracks
        ids = np.arange(self.klt.next_id, self.klt.next_id + len(tracks), dtype=np.int64)
        self.klt.next_id += len(tracks)
        return TrackSet(
            ids=ids,
            prev_points=tracks.prev_points,
            points=tracks.points,
            ages=tracks.ages,
            fb_errors=tracks.fb_errors,
            ncc_scores=tracks.ncc_scores,
            local_texture=tracks.local_texture,
            qualities=tracks.qualities,
            sources=tracks.sources,
        )

    def _remember_source_provenance(self, tracks: TrackSet) -> None:
        if not self.config.enable_source_provenance_memory or len(tracks) == 0:
            return
        for track_id, source in zip(tracks.ids, tracks.sources):
            source_l = str(source).lower()
            is_recovered = "recovery" in source_l or "memory" in source_l
            is_learned = any(
                token in source_l
                for token in ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense", "confirmed")
            )
            if not (is_recovered or is_learned):
                continue
            hold_frames = (
                int(self.config.source_provenance_recovered_hold_frames)
                if is_recovered
                else int(self.config.source_provenance_learned_hold_frames)
            )
            if hold_frames <= 0:
                continue
            self._source_provenance[int(track_id)] = _SourceProvenanceEntry(
                source=str(source),
                expires_at_frame=int(self._frame_counter) + hold_frames,
            )

    def _apply_source_provenance(self, tracks: TrackSet) -> TrackSet:
        if not self.config.enable_source_provenance_memory or len(tracks) == 0:
            return tracks
        sources = list(tracks.sources)
        qualities = tracks.qualities.astype(np.float32, copy=True)
        changed = False
        for idx, track_id in enumerate(tracks.ids):
            entry = self._source_provenance.get(int(track_id))
            if entry is None:
                continue
            if int(self._frame_counter) > int(entry.expires_at_frame):
                self._source_provenance.pop(int(track_id), None)
                continue
            current_source = str(sources[idx]).lower()
            if current_source in {"klt", "gftt", "gftt_seed", "gftt_confirmed"}:
                source_l = entry.source.lower()
                sources[idx] = entry.source
                if "recovery" in source_l or "memory" in source_l:
                    qualities[idx] *= float(self.config.source_provenance_quality_scale_recovered)
                elif any(
                    token in source_l
                    for token in ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense", "confirmed")
                ):
                    qualities[idx] *= float(self.config.source_provenance_quality_scale_learned)
                changed = True
        if not changed:
            return tracks
        return TrackSet(
            ids=tracks.ids,
            prev_points=tracks.prev_points,
            points=tracks.points,
            ages=tracks.ages,
            fb_errors=tracks.fb_errors,
            ncc_scores=tracks.ncc_scores,
            local_texture=tracks.local_texture,
            qualities=np.clip(qualities, self.config.q_min, 1.0).astype(np.float32),
            sources=sources,
        )

    def _prune_source_provenance(self, active_ids: np.ndarray) -> None:
        if not self.config.enable_source_provenance_memory or not self._source_provenance:
            return
        active = {int(item) for item in active_ids}
        expired = [
            track_id
            for track_id, entry in self._source_provenance.items()
            if int(self._frame_counter) > int(entry.expires_at_frame)
            or (track_id not in active and int(self._frame_counter) > int(entry.expires_at_frame) + 2)
        ]
        for track_id in expired:
            self._source_provenance.pop(track_id, None)

    def _replace_klt_detected_tail(
        self,
        before: int,
        points: np.ndarray,
        ids: np.ndarray,
        ages: np.ndarray,
    ) -> None:
        self.klt.points = np.vstack([self.klt.points[:before], points.astype(np.float32)]).astype(np.float32)
        self.klt.ids = np.concatenate([self.klt.ids[:before], ids.astype(np.int64)]).astype(np.int64)
        self.klt.ages = np.concatenate([self.klt.ages[:before], ages.astype(np.int32)]).astype(np.int32)

    def _cell_quality_map(self, gray: np.ndarray) -> CellQualityMap | None:
        if not self.config.enable_local_quality_map:
            return None
        return score_cell_quality_map(
            gray,
            rows=self.config.local_quality_rows,
            cols=self.config.local_quality_cols,
        )

    def _point_quality_base(
        self,
        points: np.ndarray,
        image_shape: tuple[int, int],
        image_quality: ImageQuality,
    ) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0,), dtype=np.float32)
        global_score = float(np.clip(image_quality.global_score, 0.0, 1.0))
        if (
            not self.config.enable_local_quality_map
            or not self.config.local_quality_apply_to_candidate_scoring
            or self._last_cell_quality_map is None
        ):
            return np.full((len(points),), global_score, dtype=np.float32)
        local_quality = self._raw_local_quality_at_points(points, image_shape)
        weight = float(np.clip(self.config.local_quality_weight, 0.0, 1.0))
        return np.clip((1.0 - weight) * global_score + weight * local_quality, self.config.q_min, 1.0).astype(np.float32)

    def _output_quality_base(
        self,
        points: np.ndarray,
        image_shape: tuple[int, int],
        image_quality: ImageQuality,
    ) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0,), dtype=np.float32)
        global_score = float(np.clip(image_quality.global_score, 0.0, 1.0))
        if not self.config.enable_local_quality_map or self._last_cell_quality_map is None:
            return np.full((len(points),), global_score, dtype=np.float32)
        local_quality = self._raw_local_quality_at_points(points, image_shape)
        weight = float(np.clip(self.config.local_quality_weight, 0.0, 1.0))
        return np.clip((1.0 - weight) * global_score + weight * local_quality, self.config.q_min, 1.0).astype(np.float32)

    def _raw_local_quality_at_points(
        self,
        points: np.ndarray,
        image_shape: tuple[int, int],
    ) -> np.ndarray:
        if len(points) == 0:
            return np.empty((0,), dtype=np.float32)
        if self._last_cell_quality_map is None:
            return np.ones((len(points),), dtype=np.float32)
        return cell_quality_at_points(self._last_cell_quality_map, points, image_shape, "quality")

    def _apply_local_quality_to_output_tracks(
        self,
        tracks: TrackSet,
        cur: np.ndarray,
        image_quality: ImageQuality,
    ) -> TrackSet:
        if (
            len(tracks) == 0
            or not self.config.enable_local_quality_map
            or not self.config.local_quality_apply_to_output_q
            or self._last_cell_quality_map is None
        ):
            return tracks
        local_base = self._output_quality_base(tracks.points, cur.shape, image_quality)
        global_score = float(np.clip(image_quality.global_score, self.config.q_min, 1.0))
        if global_score <= self.config.q_min + 1e-6:
            scale = np.ones((len(tracks),), dtype=np.float32)
        else:
            scale = np.clip(local_base / global_score, 0.25, 1.75).astype(np.float32)
        tracks.qualities = np.clip(
            tracks.qualities.astype(np.float32) * scale,
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        return tracks

    def _scale_new_tracks_for_mode(self, tracks: TrackSet) -> TrackSet:
        if len(tracks) == 0:
            return tracks
        tracks.qualities = self._scale_new_track_quality(
            tracks.qualities,
            str(getattr(self, "last_learned_mode", "normal")),
        )
        return tracks

    def _scale_new_track_quality(self, qualities: np.ndarray, mode: str) -> np.ndarray:
        scale = 1.0
        if mode == "planar_near_wall":
            scale = float(self.config.planar_new_track_quality_scale)
        elif mode in {"low_texture", "low_coverage_recovery", "extreme_textureless", "severe_low_texture"}:
            scale = float(self.config.severe_new_track_quality_scale)
        if abs(scale - 1.0) < 1e-6:
            return qualities.astype(np.float32, copy=False)
        return np.clip(
            qualities.astype(np.float32) * scale,
            self.config.q_min,
            1.0,
        ).astype(np.float32)

    def _update_track_memory(self, gray: np.ndarray, tracks: TrackSet) -> None:
        if not self.config.enable_learned_track_memory:
            self._track_memory = []
            return
        if len(tracks) == 0:
            return
        max_points = max(1, int(self.config.learned_track_memory_max_points))
        order = np.argsort(-tracks.ages.astype(np.float32))
        order = order[: min(len(order), max_points)]
        entry = _TrackMemoryEntry(
            frame_index=int(self._frame_counter),
            image=gray.copy(),
            points=tracks.points[order].astype(np.float32).copy(),
            ids=tracks.ids[order].astype(np.int64).copy(),
            ages=tracks.ages[order].astype(np.int32).copy(),
        )
        self._track_memory.append(entry)
        history = max(1, int(self.config.learned_track_memory_size))
        self._track_memory = self._track_memory[-history:]


def _nearest_index(points: np.ndarray, query: np.ndarray) -> int | None:
    if len(points) == 0:
        return None
    distances = np.linalg.norm(points - query.reshape(1, 2), axis=1)
    return int(np.argmin(distances))


def _too_close(point: np.ndarray, points: np.ndarray, threshold: float) -> bool:
    if len(points) == 0:
        return False
    return bool(np.any(np.linalg.norm(points - point.reshape(1, 2), axis=1) < threshold))


def _in_border(points: np.ndarray, shape: tuple[int, int], border: int) -> np.ndarray:
    h, w = shape[:2]
    return (
        (points[:, 0] >= border)
        & (points[:, 0] < w - border)
        & (points[:, 1] >= border)
        & (points[:, 1] < h - border)
    )


def _source_family_name(source: str) -> str:
    source_l = str(source or "").lower()
    if "loftr" in source_l:
        return "loftr"
    if "xfeat" in source_l:
        return "xfeat"
    if "lightglue" in source_l or "superpoint" in source_l:
        return "superpoint_lightglue"
    if "classical_gftt" in source_l:
        return "classical_gftt"
    return "generic"


def _source_family_from_sources(sources: list[str]) -> str:
    families = [_source_family_name(source) for source in sources]
    for family in ("loftr", "xfeat", "superpoint_lightglue", "classical_gftt"):
        if family in families:
            return family
    return "generic"


def _track_geometry(tracks: TrackSet) -> GeometryStats:
    if len(tracks) == 0:
        return GeometryStats(0, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
    motion_mask = tracks.ages > 1
    if int(np.sum(motion_mask)) < 8:
        return GeometryStats(0, 0, 0.0, 0, 0.0, float("nan"), float("nan"), 0.0)
    geometry, _ = validate_geometry(tracks.prev_points[motion_mask], tracks.points[motion_mask])
    return geometry


def _reference_geometry(tracks: TrackSet) -> dict[str, np.ndarray | None]:
    result: dict[str, np.ndarray | None] = {"f_mat": None, "h_mat": None}
    if len(tracks) == 0:
        return result
    motion_mask = tracks.ages > 1
    if int(np.sum(motion_mask)) < 8:
        return result
    pts0 = tracks.prev_points[motion_mask].astype(np.float32)
    pts1 = tracks.points[motion_mask].astype(np.float32)
    f_mat, _ = cv2.findFundamentalMat(pts0, pts1, cv2.FM_RANSAC, 1.0, 0.99)
    h_mat, _ = cv2.findHomography(pts0, pts1, cv2.RANSAC, 3.0)
    if f_mat is not None and np.asarray(f_mat).shape == (3, 3):
        result["f_mat"] = f_mat
    if h_mat is not None and np.asarray(h_mat).shape == (3, 3):
        result["h_mat"] = h_mat
    return result


def _candidate_geometry_mask_and_score(
    current_tracks: TrackSet,
    candidate_prev: np.ndarray,
    candidate_cur: np.ndarray,
    min_tracks: int,
    max_epipolar_error: float,
    max_homography_error: float,
    mode: str,
    strict_min_f_inlier_ratio: float,
    strict_min_h_inlier_ratio: float,
    strict_max_reference_epipolar_error: float,
    strict_max_reference_homography_error: float,
) -> tuple[np.ndarray, np.ndarray, str]:
    candidate_prev = np.asarray(candidate_prev, dtype=np.float32).reshape(-1, 2)
    candidate_cur = np.asarray(candidate_cur, dtype=np.float32).reshape(-1, 2)
    if len(candidate_prev) == 0:
        return np.empty((0,), dtype=bool), np.empty((0,), dtype=np.float32), "empty"
    valid = np.ones((len(candidate_prev),), dtype=bool)
    score = np.ones((len(candidate_prev),), dtype=np.float32)
    motion_mask = current_tracks.ages > 1 if len(current_tracks) else np.empty((0,), dtype=bool)
    if int(np.sum(motion_mask)) < min_tracks:
        return valid, score, "weak_reference"
    ref_prev = current_tracks.prev_points[motion_mask].astype(np.float32)
    ref_cur = current_tracks.points[motion_mask].astype(np.float32)
    if len(ref_prev) < 8:
        return valid, score, "weak_reference"

    f_mat, f_mask = cv2.findFundamentalMat(ref_prev, ref_cur, cv2.FM_RANSAC, 1.0, 0.99)
    h_mat, h_mask = cv2.findHomography(ref_prev, ref_cur, cv2.RANSAC, 3.0)
    has_f = f_mat is not None and np.asarray(f_mat).shape == (3, 3)
    has_h = h_mat is not None and np.asarray(h_mat).shape == (3, 3)
    if not has_f and not has_h:
        return valid, score, "no_model"

    f_valid = None
    h_valid = None
    f_score = None
    h_score = None
    if has_f:
        epi = _epipolar_errors(f_mat, candidate_prev, candidate_cur)
        f_valid = epi <= max_epipolar_error
        f_score = np.exp(-epi / max(1e-6, float(max_epipolar_error))).astype(np.float32)
    if has_h:
        hom = _homography_errors(h_mat, candidate_prev, candidate_cur)
        h_valid = hom <= max_homography_error
        h_score = np.exp(-hom / max(1e-6, float(max_homography_error))).astype(np.float32)

    mode = str(mode or "any").lower()
    if mode in {"fundamental", "essential", "epipolar", "f"}:
        if f_valid is not None and f_score is not None:
            return f_valid, f_score.astype(np.float32), "filtered"
        if h_valid is not None and h_score is not None:
            return h_valid, h_score.astype(np.float32), "filtered"
    if mode in {"homography", "planar", "h"}:
        if h_valid is not None and h_score is not None:
            return h_valid, h_score.astype(np.float32), "filtered"
        if f_valid is not None and f_score is not None:
            return f_valid, f_score.astype(np.float32), "filtered"
    if mode == "all":
        masks = [item for item in (f_valid, h_valid) if item is not None]
        scores = [item for item in (f_score, h_score) if item is not None]
        return np.logical_and.reduce(masks), np.minimum.reduce(scores).astype(np.float32), "filtered"

    if mode in {"adaptive", "adaptive_strict", "strict_adaptive"}:
        f_ratio = _mask_ratio(f_mask, len(ref_prev)) if has_f else 0.0
        h_ratio = _mask_ratio(h_mask, len(ref_prev)) if has_h else 0.0
        f_ref_error = float(np.median(_epipolar_errors(f_mat, ref_prev, ref_cur))) if has_f else float("nan")
        h_ref_error = float(np.median(_homography_errors(h_mat, ref_prev, ref_cur))) if has_h else float("nan")
        require_f = bool(
            has_f
            and (
                not has_h
                or f_ratio >= strict_min_f_inlier_ratio
                or _finite_leq(f_ref_error, strict_max_reference_epipolar_error)
            )
        )
        require_h = bool(
            has_h
            and (
                not has_f
                or h_ratio >= strict_min_h_inlier_ratio
                or _finite_leq(h_ref_error, strict_max_reference_homography_error)
            )
        )
        required_masks = []
        required_scores = []
        if require_f and f_valid is not None:
            required_masks.append(f_valid)
            required_scores.append(f_score)
        if require_h and h_valid is not None:
            required_masks.append(h_valid)
            required_scores.append(h_score)
        if required_masks:
            return (
                np.logical_and.reduce(required_masks),
                np.minimum.reduce(required_scores).astype(np.float32),
                "filtered",
            )

    masks = [item for item in (f_valid, h_valid) if item is not None]
    scores = [item for item in (f_score, h_score) if item is not None]
    return np.logical_or.reduce(masks), np.maximum.reduce(scores).astype(np.float32), "filtered"


def _epipolar_errors(f_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    p0 = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    p1 = np.concatenate([pts1, np.ones((len(pts1), 1), dtype=np.float32)], axis=1)
    lines1 = (f_mat @ p0.T).T
    numer = np.abs(np.sum(p1 * lines1, axis=1))
    denom = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2) + 1e-6
    return (numer / denom).astype(np.float32)


def _homography_errors(h_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    pts0_h = np.concatenate([pts0, np.ones((len(pts0), 1), dtype=np.float32)], axis=1)
    warped = (h_mat @ pts0_h.T).T
    warped = warped[:, :2] / (warped[:, 2:3] + 1e-6)
    return np.linalg.norm(warped - pts1, axis=1).astype(np.float32)


def _warp_points(h_mat: np.ndarray, pts: np.ndarray) -> np.ndarray:
    pts_h = np.concatenate([pts.reshape(-1, 2), np.ones((len(pts), 1), dtype=np.float32)], axis=1)
    warped = (h_mat @ pts_h.T).T
    return (warped[:, :2] / (warped[:, 2:3] + 1e-6)).astype(np.float32)


def _geometry_gate_accepts(
    before: GeometryStats,
    after: GeometryStats,
    max_f_drop: float,
    max_h_drop: float,
    max_epi_ratio: float,
    max_hom_ratio: float,
    residual_neutral: bool = False,
    max_epi_abs_increase: float = 0.0,
    max_hom_abs_increase: float = 0.0,
) -> bool:
    if after.num_pairs < 8:
        return False
    if before.num_pairs >= 8:
        if after.fundamental_inlier_ratio + max_f_drop < before.fundamental_inlier_ratio:
            return False
        if after.homography_inlier_ratio + max_h_drop < before.homography_inlier_ratio:
            return False
        if not _residual_ratio_ok(before.median_epipolar_error, after.median_epipolar_error, max_epi_ratio):
            return False
        if not _residual_ratio_ok(before.median_homography_error, after.median_homography_error, max_hom_ratio):
            return False
        if residual_neutral:
            if not _residual_abs_ok(
                before.median_epipolar_error,
                after.median_epipolar_error,
                max_epi_abs_increase,
            ):
                return False
            if not _residual_abs_ok(
                before.median_homography_error,
                after.median_homography_error,
                max_hom_abs_increase,
            ):
                return False
    return True


def _geometry_consistency_score(geometry: GeometryStats) -> float:
    if geometry.num_pairs < 8:
        return 0.55
    inlier_score = np.clip(
        0.55 * float(geometry.fundamental_inlier_ratio)
        + 0.45 * float(geometry.homography_inlier_ratio),
        0.0,
        1.0,
    )
    if geometry.median_epipolar_error == geometry.median_epipolar_error:
        epi_score = float(np.exp(-max(0.0, geometry.median_epipolar_error) / 1.0))
    else:
        epi_score = 0.55
    if geometry.median_homography_error == geometry.median_homography_error:
        hom_score = float(np.exp(-max(0.0, geometry.median_homography_error) / 3.0))
    else:
        hom_score = 0.55
    return float(np.clip(0.55 * inlier_score + 0.30 * epi_score + 0.15 * hom_score, 0.0, 1.0))


def _residual_ratio_ok(before: float, after: float, max_ratio: float) -> bool:
    if before != before or after != after:
        return True
    return after <= max(1e-6, before) * max_ratio + 1e-3


def _residual_abs_ok(before: float, after: float, max_abs_increase: float) -> bool:
    if before != before or after != after:
        return True
    return after <= before + max(0.0, float(max_abs_increase)) + 1e-6


def _residual_dynamic_limit(
    before: float,
    max_error: float,
    max_ratio: float,
    max_abs_increase: float,
) -> float:
    limit = max(0.0, float(max_error))
    if before == before:
        limit = min(
            limit,
            max(1e-6, float(before)) * float(max_ratio)
            + max(0.0, float(max_abs_increase)),
        )
    return max(1e-6, limit)


def _mask_ratio(mask: np.ndarray | None, count: int) -> float:
    if mask is None or count <= 0:
        return 0.0
    return float(np.mean(np.asarray(mask).reshape(-1).astype(bool)))


def _finite_leq(value: float, threshold: float) -> bool:
    return bool(value == value and value <= threshold)


def _merge_reasons(primary: str, secondary: str) -> str:
    items: list[str] = []
    for raw in (primary, secondary):
        if raw in {"", "healthy", "disabled", "n/a"}:
            continue
        for item in raw.split("+"):
            if item and item not in items:
                items.append(item)
    return "+".join(items) if items else "healthy"


def _new_cell_ratio(
    existing_points: np.ndarray,
    candidate_points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
) -> float:
    if len(candidate_points) == 0:
        return 0.0
    h, w = image_shape[:2]
    existing_cells = set()
    if len(existing_points):
        for row, col in _cell_indices(existing_points, h, w, rows, cols):
            existing_cells.add((int(row), int(col)))
    new_count = 0
    for row, col in _cell_indices(candidate_points, h, w, rows, cols):
        if (int(row), int(col)) not in existing_cells:
            new_count += 1
    return float(new_count / max(1, len(candidate_points)))


def _new_cell_count(
    existing_points: np.ndarray,
    candidate_points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
) -> int:
    if len(candidate_points) == 0:
        return 0
    h, w = image_shape[:2]
    existing_cells = set()
    if len(existing_points):
        for row, col in _cell_indices(existing_points, h, w, rows, cols):
            existing_cells.add((int(row), int(col)))
    new_cells = set()
    for row, col in _cell_indices(candidate_points, h, w, rows, cols):
        key = (int(row), int(col))
        if key not in existing_cells:
            new_cells.add(key)
    return int(len(new_cells))


def _cell_indices(points: np.ndarray, h: int, w: int, rows: int, cols: int) -> np.ndarray:
    pts = points.reshape(-1, 2)
    xs = np.clip((pts[:, 0] / max(1, w) * cols).astype(np.int32), 0, cols - 1)
    ys = np.clip((pts[:, 1] / max(1, h) * rows).astype(np.int32), 0, rows - 1)
    return np.stack([ys, xs], axis=1)


def _cell_need_scores(
    existing_points: np.ndarray,
    candidate_points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
    target_cell_count: int,
) -> np.ndarray:
    if len(candidate_points) == 0:
        return np.empty((0,), dtype=np.float32)
    h, w = image_shape[:2]
    counts = np.zeros((rows, cols), dtype=np.int32)
    if len(existing_points):
        for row, col in _cell_indices(existing_points, h, w, rows, cols):
            counts[row, col] += 1
    scores = []
    for row, col in _cell_indices(candidate_points, h, w, rows, cols):
        scores.append(np.clip((target_cell_count - counts[row, col]) / max(1.0, float(target_cell_count)), 0.0, 1.0))
    return np.asarray(scores, dtype=np.float32)


def _select_grid_quota_candidates(
    points: np.ndarray,
    scores: np.ndarray,
    image_shape: tuple[int, int],
    max_count: int,
    min_distance: float,
    rows: int,
    cols: int,
    max_per_cell: int,
) -> np.ndarray:
    points = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    if len(points) == 0 or max_count <= 0:
        return np.empty((0,), dtype=np.int64)
    h, w = image_shape[:2]
    cells = _cell_indices(points, h, w, rows, cols)
    cell_counts = np.zeros((rows, cols), dtype=np.int32)
    selected: list[int] = []
    selected_points: list[np.ndarray] = []
    for idx in np.argsort(-scores):
        row, col = cells[idx]
        if cell_counts[row, col] >= max(1, int(max_per_cell)):
            continue
        point = points[idx]
        if selected_points:
            selected_arr = np.vstack(selected_points)
            if _too_close(point, selected_arr, min_distance):
                continue
        selected.append(int(idx))
        selected_points.append(point.reshape(1, 2))
        cell_counts[row, col] += 1
        if len(selected) >= max_count:
            break
    return np.asarray(selected, dtype=np.int64)


def _subset_tracks(tracks: TrackSet, mask: np.ndarray) -> TrackSet:
    mask = np.asarray(mask, dtype=bool)
    if not np.any(mask):
        return TrackSet.empty()
    sources = [source for source, keep in zip(tracks.sources, mask) if keep]
    return TrackSet(
        ids=tracks.ids[mask].copy(),
        prev_points=tracks.prev_points[mask].copy(),
        points=tracks.points[mask].copy(),
        ages=tracks.ages[mask].copy(),
        fb_errors=tracks.fb_errors[mask].copy(),
        ncc_scores=tracks.ncc_scores[mask].copy(),
        local_texture=tracks.local_texture[mask].copy(),
        qualities=tracks.qualities[mask].copy(),
        sources=sources,
    )


def _subset_tracks_by_indices(tracks: TrackSet, indices: np.ndarray) -> TrackSet:
    indices = np.asarray(indices, dtype=np.int64).reshape(-1)
    if len(indices) == 0:
        return TrackSet.empty()
    mask = np.zeros((len(tracks),), dtype=bool)
    mask[np.clip(indices, 0, max(0, len(tracks) - 1))] = True
    return _subset_tracks(tracks, mask)


def _median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))
