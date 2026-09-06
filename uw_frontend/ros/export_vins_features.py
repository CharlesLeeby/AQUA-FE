from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np
import rosbag
import yaml
from cv_bridge import CvBridge
from geometry_msgs.msg import Point32
from sensor_msgs.msg import ChannelFloat32, PointCloud

from uw_frontend.evaluation.measurement_selection import (
    MeasurementSelectionConfig,
    select_backend_measurements,
)
from uw_frontend.geometry.grid import grid_stats
from uw_frontend.evaluation.run_frontend_eval import (
    build_matcher,
    load_config,
    resolve_process_skipped_frames,
)
from uw_frontend.quality.image_quality import fuse_image_quality_for_gates, score_image_quality
from uw_frontend.tracking.hybrid_tracker import HybridConfig, HybridKltOrbTracker
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker
from uw_frontend.tracking.orb_tracker import OrbConfig, OrbTracker
from uw_frontend.tracking.pairwise_matcher_tracker import PairwiseMatcherTracker, PairwiseMatcherTrackerConfig
from uw_frontend.tracking.track_state import TrackSet


@dataclass(frozen=True)
class _InitParallaxGateState:
    enabled: bool
    triggered: bool
    mean_step_px: float
    skip_feature_frames: int

    @classmethod
    def disabled(cls) -> "_InitParallaxGateState":
        return cls(
            enabled=False,
            triggered=False,
            mean_step_px=float("nan"),
            skip_feature_frames=0,
        )


@dataclass(frozen=True)
class _AdaptiveWarmupFullMirrorState:
    enabled: bool
    reason: str


@dataclass(frozen=True)
class _FinalMirrorExportInfo:
    active: bool = False
    preserve_classical_budget: bool = False
    zero_sidecar_restore: bool = False
    input_sidecars: int = 0
    kept_sidecars: int = 0
    dropped_sidecars_for_cap: int = 0
    dropped_sidecars_for_classical_budget: int = 0
    dropped_classical_for_cap: int = 0
    remapped_sidecar_ids: int = 0
    persistence_replacement_active: bool = False
    persistence_horizon_blocked: bool = False
    persistence_eligible_sidecars: int = 0
    persistence_eligible_gftt: int = 0
    persistence_replaced_gftt: int = 0
    persistence_dropped_sidecars: int = 0
    persistence_single_chain_active: bool = False
    persistence_committed_sidecar_id: int = -1
    persistence_single_chain_suppressed: int = 0
    persistence_churn_guard_active: bool = False
    persistence_churn_guard_decision: int = -1
    persistence_churn_guard_decision_frame: int = -1
    persistence_churn_guard_gftt_births: int = 0
    persistence_churn_guard_denominator: int = 0
    persistence_churn_guard_ratio: float = float("nan")
    persistence_source_router_active: bool = False
    persistence_source_eligible_sidecars: int = 0
    persistence_source_suppressed: int = 0
    persistence_same_cell_active: bool = False
    persistence_same_cell_suppressed: int = 0
    persistence_coverage_monotone_active: bool = False
    persistence_coverage_monotone_suppressed: int = 0
    persistence_grid_cells_before: int = -1
    persistence_grid_cells_after: int = -1
    persistence_grid_cell_delta: int = 0
    persistence_cross_cell_replacements: int = 0
    persistence_donor_cell_min_remaining: int = -1
    persistence_per_frame_cap: int = 0
    persistence_per_frame_cap_suppressed: int = 0
    persistence_replaced_gftt_max_age: int = -1
    persistence_replacement_min_age_advantage_actual: int = -1
    persistence_replacement_cell_mismatches: int = 0
    prefill_slot_active: bool = False
    prefill_slot_horizon_blocked: bool = False
    prefill_slot_carried_observations: int = 0
    prefill_slot_baseline_newborns: int = 0
    prefill_slot_vacant_capacity: int = 0
    prefill_slot_eligible_sidecars: int = 0
    prefill_slot_admitted_sidecars: int = 0
    prefill_slot_omitted_newborns: int = 0
    prefill_slot_dropped_sidecars: int = 0
    prefill_slot_source_suppressed: int = 0
    prefill_slot_age_suppressed: int = 0
    prefill_slot_per_frame_cap: int = 0


@dataclass(frozen=True)
class _LearnedExportGateInfo:
    active: bool
    degraded: bool
    reason: str
    classical_count: int
    classical_grid_coverage: float
    dropped_learned: int
    geometry_dropped: int = 0
    geometry_reason: str = "not_run"
    benefit_dropped: int = 0
    benefit_reason: str = "not_run"
    learned_grid_gain: float = float("nan")
    learned_new_cells: int = 0
    learned_new_cell_ratio: float = float("nan")
    learned_weak_cells: int = 0
    classical_motion_px: float = float("nan")
    classical_median_age: float = float("nan")
    temporal_dropped: int = 0
    temporal_reason: str = "disabled"
    temporal_recent_frames: int = 0
    health_suppression_dropped: int = 0
    health_suppression_reason: str = "disabled"
    recent_healthy_frames: int = 0
    recovery_reason_suppression_dropped: int = 0
    recovery_reason_suppression_reason: str = "disabled"
    recovery_burst_suppression_dropped: int = 0
    recovery_burst_suppression_reason: str = "disabled"
    recovery_burst_recent_frames: int = 0

    @classmethod
    def disabled(cls, tracks: TrackSet, image_shape: tuple[int, int]) -> "_LearnedExportGateInfo":
        classical_mask = _classical_backbone_mask(tracks)
        classical_count = int(np.count_nonzero(classical_mask))
        classical_grid = _track_grid_coverage(tracks, image_shape, classical_mask)
        return cls(
            active=False,
            degraded=False,
            reason="disabled",
            classical_count=classical_count,
            classical_grid_coverage=classical_grid,
            dropped_learned=0,
            geometry_dropped=0,
            geometry_reason="disabled",
            benefit_dropped=0,
            benefit_reason="disabled",
            learned_grid_gain=float("nan"),
            learned_new_cells=0,
            learned_new_cell_ratio=float("nan"),
            learned_weak_cells=0,
            classical_motion_px=float("nan"),
            classical_median_age=float("nan"),
            temporal_dropped=0,
            temporal_reason="disabled",
            temporal_recent_frames=0,
            health_suppression_dropped=0,
            health_suppression_reason="disabled",
            recent_healthy_frames=0,
            recovery_reason_suppression_dropped=0,
            recovery_reason_suppression_reason="disabled",
            recovery_burst_suppression_dropped=0,
            recovery_burst_suppression_reason="disabled",
            recovery_burst_recent_frames=0,
        )


@dataclass(frozen=True)
class _SidecarGeometryConfig:
    enabled: bool
    require_confirmed_learned: bool
    max_epipolar_error: float
    max_essential_error: float
    max_homography_error: float
    residual_max_ratio: float
    residual_max_epipolar_abs: float
    residual_max_essential_abs: float
    residual_max_homography_abs: float
    min_reference_tracks: int
    loftr_requires_homography: bool


@dataclass(frozen=True)
class _GateParams:
    min_classical_tracks: int
    min_classical_grid: float
    min_age: int
    loftr_min_age: int | None
    min_quality: float
    min_ncc: float
    max_fb: float
    loftr_min_quality: float | None
    loftr_min_ncc: float | None
    loftr_max_fb: float | None
    benefit_gate: bool
    benefit_loftr_only: bool
    min_grid_gain: float
    min_new_cells: int
    min_new_cell_ratio: float
    max_per_new_cell: int
    coverage_gain_max_classical_tracks: int
    min_classical_motion_px: float
    min_classical_age: float
    weak_cell_rescue: bool
    non_loftr_weak_cell_rescue: bool
    weak_cell_max_count: int
    weak_cell_min_candidates: int
    weak_cell_max_occupancy: int
    weak_cell_min_classical_motion_px: float
    weak_cell_max_classical_grid: float
    weak_cell_max_classical_tracks: int
    mature_cell_rescue: bool
    mature_cell_max_count: int
    mature_cell_min_candidates: int
    mature_cell_min_classical_age: float
    mature_cell_min_classical_motion_px: float
    mature_cell_max_classical_grid: float
    mature_cell_max_per_cell: int
    mature_cell_max_occupancy: int
    loftr_planar_rescue: bool
    loftr_planar_max_count: int
    loftr_planar_min_candidates: int
    loftr_planar_max_classical_grid: float
    loftr_planar_min_classical_motion_px: float
    loftr_weak_cell_rescue: bool
    loftr_weak_cell_max_count: int
    loftr_weak_cell_max_occupancy: int
    loftr_rescue_max_classical_tracks: int
    loftr_support_max_init_parallax_px: float
    loftr_support_max_classical_motion_px: float
    init_parallax_mean_step_px: float
    non_loftr_requires_degraded_mode: bool


@dataclass
class _TemporalSidecarGateState:
    accepted_frames: list[int]
    candidate_frames: list[int] | None = None
    last_loftr_support_frame: int | None = None

    def recent_count(self, frame_index: int, window: int) -> int:
        window = max(0, int(window))
        if window <= 0:
            return 0
        first_allowed = int(frame_index) - window
        self.accepted_frames = [idx for idx in self.accepted_frames if idx >= first_allowed]
        return len(self.accepted_frames)

    def recent_candidate_count(self, frame_index: int, window: int) -> int:
        window = max(0, int(window))
        if window <= 0:
            return 0
        if self.candidate_frames is None:
            self.candidate_frames = []
        first_allowed = int(frame_index) - window
        self.candidate_frames = [idx for idx in self.candidate_frames if idx >= first_allowed]
        return len(self.candidate_frames)

    def record(self, frame_index: int) -> None:
        self.accepted_frames.append(int(frame_index))

    def record_candidate(self, frame_index: int) -> None:
        if self.candidate_frames is None:
            self.candidate_frames = []
        self.candidate_frames.append(int(frame_index))

    def loftr_support_in_cooldown(self, frame_index: int, cooldown_frames: int) -> bool:
        cooldown = max(0, int(cooldown_frames))
        if cooldown <= 0 or self.last_loftr_support_frame is None:
            return False
        return int(frame_index) - int(self.last_loftr_support_frame) <= cooldown

    def record_loftr_support(self, frame_index: int) -> None:
        self.last_loftr_support_frame = int(frame_index)


@dataclass
class _MotionAdaptiveMirrorRefillState:
    refill_until_frame: int = -1


@dataclass
class _VisibleSidecarTrackGateState:
    last_frame: dict[int, int]
    streak: dict[int, int]
    last_point: dict[int, np.ndarray]
    path_length_px: dict[int, float]
    step_count: dict[int, int]

    def update(
        self,
        tracks: TrackSet,
        *,
        frame_index: int,
        max_gap: int,
    ) -> None:
        active_ids: set[int] = set()
        for idx, source in enumerate(tracks.sources):
            if not (_is_learned_source(source) or _is_recovered_source(source)):
                continue
            track_id = int(tracks.ids[idx])
            point = np.asarray(tracks.points[idx], dtype=np.float32)
            active_ids.add(track_id)
            prev_frame = self.last_frame.get(track_id)
            if prev_frame is None or int(frame_index) - int(prev_frame) > max(1, int(max_gap)):
                self.streak[track_id] = 1
                self.path_length_px[track_id] = 0.0
                self.step_count[track_id] = 0
            else:
                self.streak[track_id] = self.streak.get(track_id, 0) + 1
                prev_point = self.last_point.get(track_id)
                if prev_point is not None:
                    self.path_length_px[track_id] = self.path_length_px.get(
                        track_id, 0.0
                    ) + float(np.linalg.norm(point - prev_point))
                    self.step_count[track_id] = self.step_count.get(track_id, 0) + 1
            self.last_frame[track_id] = int(frame_index)
            self.last_point[track_id] = point.copy()
        stale_before = int(frame_index) - max(1, int(max_gap)) * 4
        for track_id, last in list(self.last_frame.items()):
            if track_id not in active_ids and int(last) < stale_before:
                self.last_frame.pop(track_id, None)
                self.streak.pop(track_id, None)
                self.last_point.pop(track_id, None)
                self.path_length_px.pop(track_id, None)
                self.step_count.pop(track_id, None)

    def count(self, track_id: int) -> int:
        return int(self.streak.get(int(track_id), 0))

    def mean_step_px(self, track_id: int) -> float:
        track_id = int(track_id)
        count = int(self.step_count.get(track_id, 0))
        if count <= 0:
            return 0.0
        return float(self.path_length_px.get(track_id, 0.0)) / float(count)


@dataclass
class _FreshSidecarConfirmationGateState:
    confirmed_until: dict[int, int]

    def prune(self, frame_index: int) -> None:
        frame = int(frame_index)
        for track_id, last_allowed in list(self.confirmed_until.items()):
            if int(last_allowed) < frame:
                self.confirmed_until.pop(track_id, None)

    def record(self, track_id: int, *, frame_index: int, hold_frames: int) -> None:
        self.confirmed_until[int(track_id)] = int(frame_index) + max(0, int(hold_frames))

    def allowed(self, track_id: int, *, frame_index: int) -> bool:
        self.prune(int(frame_index))
        return int(self.confirmed_until.get(int(track_id), -1)) >= int(frame_index)


@dataclass
class _OnlineSeedFreshFrameGateState:
    hold_until: int = -1

    def record(self, *, frame_index: int, hold_frames: int) -> None:
        self.hold_until = max(
            int(self.hold_until),
            int(frame_index) + max(0, int(hold_frames)),
        )

    def allowed(self, *, frame_index: int) -> bool:
        return int(frame_index) <= int(self.hold_until)


@dataclass
class _OnlineSeedMicroburstGateState:
    start_frame: int = -1
    end_frame: int = -1
    base_end_frame: int = -1
    extension_decided: bool = False
    extension_enabled: bool = False
    observation_cap: int = 0
    observation_cap_reason: str = ""
    rejected_start_reason: str = ""
    restart_count: int = 0
    recorded_frames: set[int] = field(default_factory=set)
    initial_observations: int = 0
    initial_cells: set[tuple[int, int]] = field(default_factory=set)
    initial_points_x: list[float] = field(default_factory=list)
    initial_points_y: list[float] = field(default_factory=list)

    def maybe_start(self, *, frame_index: int, span_frames: int) -> None:
        if int(self.start_frame) >= 0:
            return
        span = max(1, int(span_frames))
        self.start_frame = int(frame_index)
        self.end_frame = int(frame_index) + span - 1
        self.base_end_frame = int(self.end_frame)

    def reject_start(self, *, frame_index: int, reason: str = "") -> None:
        if int(self.start_frame) >= 0:
            return
        frame = int(frame_index)
        self.start_frame = frame
        self.end_frame = frame - 1
        self.base_end_frame = frame - 1
        self.extension_decided = True
        self.extension_enabled = False
        self.rejected_start_reason = str(reason or "")
        self.recorded_frames.add(frame)

    def maybe_restart(
        self,
        *,
        frame_index: int,
        span_frames: int,
        cooldown_frames: int,
        max_restarts: int,
    ) -> bool:
        if int(max_restarts) <= 0 or int(self.start_frame) < 0:
            return False
        frame = int(frame_index)
        if frame <= int(self.end_frame) + max(0, int(cooldown_frames)):
            return False
        if int(self.restart_count) >= int(max_restarts):
            return False
        self.restart_count += 1
        self.start_frame = -1
        self.end_frame = -1
        self.base_end_frame = -1
        self.extension_decided = False
        self.extension_enabled = False
        self.rejected_start_reason = ""
        self.recorded_frames.clear()
        self.initial_observations = 0
        self.initial_cells.clear()
        self.initial_points_x.clear()
        self.initial_points_y.clear()
        self.maybe_start(frame_index=frame, span_frames=span_frames)
        return True

    def record_initial_candidates(
        self,
        *,
        frame_index: int,
        tracks: TrackSet,
        mask: np.ndarray,
        image_shape: tuple[int, int] | None,
        grid_rows: int,
        grid_cols: int,
    ) -> None:
        if int(self.start_frame) < 0:
            return
        frame = int(frame_index)
        if frame > int(self.base_end_frame) or frame in self.recorded_frames:
            return
        selected = np.flatnonzero(np.asarray(mask, dtype=bool)).astype(np.int64)
        if len(selected) == 0:
            self.recorded_frames.add(frame)
            return
        points = tracks.points[selected].astype(np.float32)
        finite = np.isfinite(points).all(axis=1)
        points = points[finite]
        self.initial_observations += int(len(points))
        if len(points):
            self.initial_points_x.extend(float(value) for value in points[:, 0])
            self.initial_points_y.extend(float(value) for value in points[:, 1])
            if image_shape is not None:
                cells = _grid_cell_indices(
                    points,
                    image_shape,
                    rows=max(1, int(grid_rows)),
                    cols=max(1, int(grid_cols)),
                )
                for row, col in cells:
                    self.initial_cells.add((int(row), int(col)))
        self.recorded_frames.add(frame)

    def maybe_apply_dense_start_cap(
        self,
        *,
        frame_index: int,
        tracks: TrackSet,
        mask: np.ndarray,
        image_shape: tuple[int, int] | None,
        max_observations: int,
        min_classical_tracks: int,
        min_classical_grid: float,
        min_frame_candidates: int,
    ) -> None:
        if int(max_observations) <= 0 or int(self.observation_cap) > 0:
            return
        if int(self.start_frame) < 0 or int(frame_index) != int(self.start_frame):
            return
        candidate_count = int(np.count_nonzero(np.asarray(mask, dtype=bool)))
        if candidate_count < max(0, int(min_frame_candidates)):
            return
        classical_mask = _classical_backbone_mask(tracks)
        classical_count = int(np.count_nonzero(classical_mask))
        if classical_count < max(0, int(min_classical_tracks)):
            return
        classical_grid = _track_grid_coverage(tracks, image_shape, classical_mask)
        if math.isfinite(float(min_classical_grid)) and classical_grid < float(min_classical_grid):
            return
        self.observation_cap = int(max_observations)
        self.observation_cap_reason = (
            "dense_start_cap"
            f":classical={classical_count}"
            f":grid={classical_grid:.3f}"
            f":candidates={candidate_count}"
        )

    def maybe_extend(
        self,
        *,
        frame_index: int,
        total_span_frames: int,
        min_initial_observations: int,
        min_initial_cells: int,
        min_initial_bbox_area_ratio: float,
        image_shape: tuple[int, int] | None,
    ) -> None:
        if int(self.start_frame) < 0 or bool(self.extension_decided):
            return
        if int(total_span_frames) <= 0 or int(total_span_frames) <= self.base_span_frames:
            return
        if int(frame_index) <= int(self.base_end_frame):
            return
        self.extension_decided = True
        ok = True
        if int(min_initial_observations) > 0:
            ok = ok and int(self.initial_observations) >= int(min_initial_observations)
        if int(min_initial_cells) > 0:
            ok = ok and len(self.initial_cells) >= int(min_initial_cells)
        if float(min_initial_bbox_area_ratio) > 0.0:
            ok = ok and self.initial_bbox_area_ratio(image_shape) >= float(
                min_initial_bbox_area_ratio
            )
        if ok:
            self.extension_enabled = True
            self.end_frame = int(self.start_frame) + max(1, int(total_span_frames)) - 1

    def allowed(self, *, frame_index: int) -> bool:
        if int(self.start_frame) < 0:
            return True
        return int(frame_index) <= int(self.end_frame)

    @property
    def base_span_frames(self) -> int:
        if int(self.start_frame) < 0 or int(self.base_end_frame) < int(self.start_frame):
            return 0
        return int(self.base_end_frame) - int(self.start_frame) + 1

    def initial_bbox_area_ratio(self, image_shape: tuple[int, int] | None) -> float:
        if image_shape is None or len(self.initial_points_x) < 2 or len(self.initial_points_y) < 2:
            return 0.0
        h, w = image_shape[:2]
        denom = max(1.0, float(h) * float(w))
        width = max(0.0, max(self.initial_points_x) - min(self.initial_points_x))
        height = max(0.0, max(self.initial_points_y) - min(self.initial_points_y))
        return float((width * height) / denom)


@dataclass
class _RecentClassicalHealthGateState:
    healthy_frames: list[int]

    def update(self, frame_index: int, *, healthy: bool, window: int) -> int:
        window = max(0, int(window))
        frame = int(frame_index)
        if window <= 0:
            self.healthy_frames.clear()
            return 0
        first_allowed = frame - window
        self.healthy_frames = [idx for idx in self.healthy_frames if idx >= first_allowed]
        if bool(healthy):
            self.healthy_frames.append(frame)
        return len(self.healthy_frames)


@dataclass
class _StaleHealthyUnconfirmedGateState:
    matched_frames: list[int]

    def update(self, frame_index: int, *, matched: bool, window: int) -> int:
        window = max(0, int(window))
        frame = int(frame_index)
        if window <= 0:
            self.matched_frames.clear()
            return 0
        first_allowed = frame - window
        self.matched_frames = [idx for idx in self.matched_frames if idx >= first_allowed]
        if bool(matched):
            self.matched_frames.append(frame)
        return len(self.matched_frames)


@dataclass
class _ShortLowGridSeedGateState:
    in_burst: bool = False
    last_sidecar_frame: int = -10_000_000
    low_grid_seed_frames: int = 0
    seen_non_low_grid: bool = False
    burst_index: int = 0
    burst_start_frame: int = -1

    def update(
        self,
        frame_index: int,
        *,
        has_non_loftr_sidecar: bool,
        low_grid_context: bool,
        max_gap: int,
    ) -> tuple[int, bool]:
        frame = int(frame_index)
        gap = frame - int(self.last_sidecar_frame)
        if not bool(has_non_loftr_sidecar):
            if self.in_burst and gap > max(1, int(max_gap)):
                self.reset()
            return int(self.low_grid_seed_frames), False
        if (not self.in_burst) or gap > max(1, int(max_gap)):
            self.in_burst = True
            self.burst_index += 1
            self.burst_start_frame = frame
            self.low_grid_seed_frames = 0
            self.seen_non_low_grid = False
        if (not self.seen_non_low_grid) and bool(low_grid_context):
            self.low_grid_seed_frames += 1
        elif not bool(low_grid_context):
            self.seen_non_low_grid = True
        self.last_sidecar_frame = frame
        return int(self.low_grid_seed_frames), bool(self.seen_non_low_grid)

    def reset(self) -> None:
        self.in_burst = False
        self.last_sidecar_frame = -10_000_000
        self.low_grid_seed_frames = 0
        self.seen_non_low_grid = False
        self.burst_start_frame = -1


@dataclass
class _RecoveryReasonBurstGateState:
    matched_frames: list[int]

    def update(
        self,
        frame_index: int,
        *,
        recovery_reason: str,
        tokens: str,
        window: int,
    ) -> int:
        window = max(0, int(window))
        frame = int(frame_index)
        if window <= 0:
            self.matched_frames.clear()
            return 0
        first_allowed = frame - window
        self.matched_frames = [idx for idx in self.matched_frames if idx >= first_allowed]
        if _recovery_reason_matches_tokens(recovery_reason, tokens):
            self.matched_frames.append(frame)
        return len(self.matched_frames)


@dataclass
class _CoverageSeededContinuationGateState:
    seeded_ids: set[int]

    def record(self, tracks: TrackSet, mask: np.ndarray) -> None:
        for track_id in tracks.ids[np.asarray(mask, dtype=bool)]:
            self.seeded_ids.add(int(track_id))

    def is_seeded(self, track_id: int) -> bool:
        return int(track_id) in self.seeded_ids


@dataclass
class _LoFTRSeededContinuationGateState:
    """Track contiguous LoFTR ids that already passed the full export gate."""

    last_accepted_frame: dict[int, int]

    def continuation_mask(
        self,
        ids: np.ndarray,
        *,
        frame_index: int,
        max_gap: int,
    ) -> np.ndarray:
        frame = int(frame_index)
        gap_limit = max(1, int(max_gap))
        stale = [
            track_id
            for track_id, last_frame in self.last_accepted_frame.items()
            if frame - int(last_frame) > gap_limit
        ]
        for track_id in stale:
            self.last_accepted_frame.pop(int(track_id), None)
        return np.asarray(
            [
                0 < frame - int(self.last_accepted_frame.get(int(track_id), -10_000_000))
                <= gap_limit
                for track_id in ids
            ],
            dtype=bool,
        )

    def record(self, ids: np.ndarray, *, frame_index: int) -> None:
        for track_id in ids:
            self.last_accepted_frame[int(track_id)] = int(frame_index)


@dataclass
class _LoFTREarlyPersistencePacket:
    source_frame: int
    source_stamp: float
    expires_after: int
    tracks: TrackSet
    pixel_velocity: np.ndarray


@dataclass
class _LoFTREarlyPersistenceState:
    packets: list[_LoFTREarlyPersistencePacket]
    source_frames_used: int = 0
    total_added: int = 0


@dataclass
class _XFeatRiskQualitySchedulerState:
    learned_frames: int = 0
    cumulative_gftt: int = 0
    latched: bool = False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export a VINS-Fusion external feature bag from a ROS image bag."
    )
    parser.add_argument("--bag", required=True)
    parser.add_argument("--image-topic", default="/wall_climber/camerafront/camera_image")
    parser.add_argument("--output-bag", required=True)
    parser.add_argument("--camera-config", required=True)
    parser.add_argument("--config", default="uw_frontend/configs/continuity_optimized_frontend.yaml")
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
        default="hybrid_xfeat",
    )
    parser.add_argument(
        "--semidense-fallback-method",
        choices=["none", "xfeat_star", "loftr"],
        default="none",
    )
    parser.add_argument("--feature-topic", default="/feature_tracker/feature")
    parser.add_argument("--copy-topic", action="append", default=[])
    parser.add_argument("--start-offset", type=float, default=0.0)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--every-n", type=int, default=1)
    parser.add_argument(
        "--frame-offset",
        type=int,
        default=0,
        help="Keep frames whose raw image index modulo every-n equals this offset.",
    )
    cadence_group = parser.add_mutually_exclusive_group()
    cadence_group.add_argument(
        "--process-skipped-frames",
        dest="process_skipped_frames",
        action="store_true",
        help=(
            "Run frontend state updates on skipped frames while publishing only selected "
            "frames; overrides frontend_runtime.process_skipped_frames."
        ),
    )
    cadence_group.add_argument(
        "--no-process-skipped-frames",
        dest="process_skipped_frames",
        action="store_false",
        help="Disable skipped-frame state updates even if the profile enables them.",
    )
    parser.set_defaults(process_skipped_frames=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--metrics-csv", default=None)
    parser.add_argument(
        "--timestamp-source",
        choices=["header", "bag"],
        default="header",
        help="Timestamp used in the exported PointCloud header.",
    )
    parser.add_argument(
        "--max-header-stamp-delta",
        type=float,
        default=0.0,
        help="If positive, treat image header/bag stamp differences larger than this as invalid.",
    )
    parser.add_argument(
        "--invalid-header-policy",
        choices=["skip", "use_bag", "use_header"],
        default="skip",
        help="Policy for invalid image header stamps detected by --max-header-stamp-delta.",
    )
    parser.add_argument(
        "--measurement-selection",
        action="store_true",
        help="Apply backend-ready geometry/quality measurement selection before publishing.",
    )
    parser.add_argument(
        "--preserve-sidecars-through-selection",
        action="store_true",
        help=(
            "When measurement selection is enabled, select only the classical "
            "KLT/GFTT backbone and append learned/LoFTR sidecar candidates "
            "afterward so the later source/geometry/degradation gates, rather "
            "than the backbone selector, decide whether sidecars may enter VINS."
        ),
    )
    parser.add_argument(
        "--formal-three-layer-export",
        action="store_true",
        help=(
            "Use the paper-facing three-layer VINS export policy: KLT-only "
            "initialization, KLT-dominant normal tracking, and geometry-safe "
            "learned/LoFTR sidecar export only under degradation."
        ),
    )
    parser.add_argument("--export-max-features", type=int, default=None)
    parser.add_argument(
        "--measurement-selection-max-features",
        type=int,
        default=None,
        help=(
            "Override only the backend measurement-selection cap. This lets "
            "VINS see a larger warmup backbone via --export-max-features while "
            "using a sparser post-warmup selected backbone."
        ),
    )
    parser.add_argument(
        "--measurement-selection-ransac-seed",
        type=int,
        default=None,
        help=(
            "Optional OpenCV RANSAC seed for backend measurement selection. "
            "Use this for reproducible counterexample audits; omit it to keep "
            "the existing OpenCV RNG behavior."
        ),
    )
    parser.add_argument("--measurement-selection-model", default=None)
    parser.add_argument("--measurement-selection-residual-weight", type=float, default=None)
    parser.add_argument("--measurement-selection-coverage-weight", type=float, default=None)
    parser.add_argument("--measurement-selection-max-per-cell", type=int, default=None)
    parser.add_argument("--measurement-selection-target-cell-count", type=int, default=None)
    parser.add_argument("--export-min-age", type=int, default=None)
    parser.add_argument(
        "--preprocess",
        choices=["none", "equalize", "clahe", "adaptive_clahe"],
        default="none",
        help="Image preprocessing used by the external frontend only.",
    )
    parser.add_argument(
        "--selection-warmup-frames",
        type=int,
        default=0,
        help="Disable backend measurement selection for the first N emitted frames.",
    )
    parser.add_argument(
        "--export-min-learned-age",
        type=int,
        default=0,
        help="Require learned/semi-dense features to survive this many frames before export.",
    )
    parser.add_argument(
        "--reset-recovered-export-ids",
        action="store_true",
        help="Give recovered/learned tracks fresh VINS ids so the backend treats them as new landmarks.",
    )
    parser.add_argument(
        "--learned-export-loftr-source-memory",
        action="store_true",
        help=(
            "After a confirmed LoFTR sidecar receives a fresh VINS id, keep that "
            "id for continuously tracked LK successors and label them as LoFTR memory."
        ),
    )
    parser.add_argument(
        "--vins-safe-source-selection",
        action="store_true",
        help=(
            "Apply a source-aware export gate for VINS: keep KLT/GFTT as the "
            "backbone and admit only a small, mature learned/recovery sidecar."
        ),
    )
    parser.add_argument(
        "--vins-safe-warmup-frames",
        type=int,
        default=0,
        help="Suppress learned/recovery exports for the first N emitted feature frames.",
    )
    parser.add_argument(
        "--vins-safe-max-total",
        type=int,
        default=None,
        help="Maximum exported tracks after source-aware VINS-safe selection.",
    )
    parser.add_argument(
        "--vins-safe-sidecar-low-cap-total",
        type=int,
        default=None,
        help=(
            "Optional lower exported-track cap used only on frames that carry "
            "learned/LoFTR sidecars. This keeps normal-texture KLT backbones "
            "dense while using a sparse, conservative cap during low-texture "
            "sidecar rescue."
        ),
    )
    parser.add_argument(
        "--vins-safe-low-cap-hold-frames",
        type=int,
        default=0,
        help=(
            "Keep the sidecar/low-texture cap active for this many emitted "
            "feature frames after a low-texture cap trigger. This hysteresis "
            "prevents late healthy-looking frames inside one degraded segment "
            "from abruptly changing the VINS measurement density."
        ),
    )
    parser.add_argument(
        "--vins-safe-max-learned",
        type=int,
        default=24,
        help="Maximum learned/semi-dense tracks exported per frame after warmup.",
    )
    parser.add_argument(
        "--vins-safe-max-recovered",
        type=int,
        default=16,
        help="Maximum recovered tracks exported per frame after warmup.",
    )
    parser.add_argument(
        "--vins-safe-min-learned-age",
        type=int,
        default=3,
        help="Minimum age for learned/semi-dense tracks to be exported by the VINS-safe gate.",
    )
    parser.add_argument(
        "--vins-safe-preserve-classical-budget",
        action="store_true",
        help=(
            "Treat --vins-safe-max-total as the KLT/GFTT backbone budget and "
            "append the small learned/recovery sidecar on top of it. Without "
            "this, sidecars reserve slots inside max_total and can displace "
            "stable KLT tracks, which is not a true sidecar policy."
        ),
    )
    parser.add_argument(
        "--vins-safe-classical-prefer-quality",
        action="store_true",
        help=(
            "When applying VINS-safe source selection, rank classical KLT/GFTT "
            "tracks by exported quality instead of track age. Default keeps "
            "the historical age-preferred ordering."
        ),
    )
    parser.add_argument(
        "--vins-safe-classical-prefer-klt",
        action="store_true",
        help=(
            "When applying VINS-safe source selection, rank KLT-propagated "
            "classical tracks before newly detected GFTT/ORB tracks. This is "
            "useful for low-texture VINS initialization where identity "
            "continuity matters more than single-frame detector score."
        ),
    )
    parser.add_argument(
        "--vins-safe-exact-cap-selection",
        action="store_true",
        help=(
            "Use the same deterministic cap policy as the offline feature-bag "
            "sweep: keep up to --vins-safe-max-learned learned/LoFTR tracks by "
            "quality, fill the remaining --vins-safe-max-total slots with a "
            "continuity-ranked non-learned backbone, and preserve original track order."
        ),
    )
    parser.add_argument(
        "--vins-safe-init-sidecar-support-selection",
        action="store_true",
        help=(
            "During VINS initialization frames that admit confirmed LoFTR "
            "sidecars, reserve a few classical KLT/GFTT slots for spatially "
            "supportive tracks instead of ranking only by short-term quality."
        ),
    )
    parser.add_argument(
        "--vins-safe-init-sidecar-support-count",
        type=int,
        default=2,
        help="Number of classical support tracks swapped in on init LoFTR sidecar frames.",
    )
    parser.add_argument(
        "--vins-safe-init-sidecar-classical-quality-floor",
        type=float,
        default=0.0,
        help=(
            "Optional quality floor applied only to classical KLT/GFTT tracks "
            "on warmup frames where confirmed LoFTR sidecars enter VINS."
        ),
    )
    parser.add_argument(
        "--init-parallax-gate",
        action="store_true",
        help=(
            "Pre-scan early selected feature frames and, when early KLT "
            "parallax is too small, keep learned/LoFTR sidecars out of VINS "
            "initialization. Classical KLT/GFTT backbone frames remain "
            "published unless --init-parallax-skip-feature-frames is set."
        ),
    )
    parser.add_argument("--init-parallax-probe-frames", type=int, default=5)
    parser.add_argument("--init-parallax-threshold-px", type=float, default=7.0)
    parser.add_argument("--init-parallax-skip-feature-frames", type=int, default=0)
    parser.add_argument(
        "--init-parallax-adaptive-skip",
        action="store_true",
        help=(
            "When the early parallax gate triggers, skip the first few KLT "
            "feature frames only for moderate-low parallax. Extremely low "
            "parallax keeps the KLT backbone published and only suppresses "
            "learned/LoFTR sidecars."
        ),
    )
    parser.add_argument("--init-parallax-adaptive-skip-frames", type=int, default=4)
    parser.add_argument("--init-parallax-adaptive-min-px", type=float, default=3.0)
    parser.add_argument("--init-parallax-adaptive-max-px", type=float, default=7.0)
    parser.add_argument(
        "--vins-init-klt-only-frames",
        type=int,
        default=0,
        help=(
            "Force the first N selected feature frames to export only classical "
            "KLT/GFTT backbone tracks. This is an offline proxy for keeping "
            "learned/LoFTR sidecars out of VINS initialization."
        ),
    )
    parser.add_argument(
        "--init-loftr-sidecar-rescue",
        action="store_true",
        help=(
            "During the VINS KLT-only warmup, keep confirmed LoFTR sidecars "
            "available for the strict learned export gates after the initial "
            "parallax-skip frames. This is a guarded low-texture initialization "
            "rescue, not a generic learned replacement."
        ),
    )
    parser.add_argument(
        "--init-loftr-sidecar-max-count",
        type=int,
        default=6,
        help=(
            "Maximum confirmed LoFTR sidecars that may survive the VINS-safe "
            "warmup when --init-loftr-sidecar-rescue is enabled. These tracks "
            "must still pass the learned export gates first."
        ),
    )
    parser.add_argument(
        "--low-parallax-learned-holdoff-frames",
        type=int,
        default=8,
        help=(
            "When the early parallax gate triggers, keep learned/LoFTR "
            "sidecars out of the VINS export for this many selected feature "
            "frames after the KLT-only initialization window."
        ),
    )
    parser.add_argument(
        "--learned-export-degradation-gate",
        action="store_true",
        help=(
            "Export learned/LoFTR sidecar tracks only when the classical KLT "
            "backbone is degraded and each sidecar track passes source/age/"
            "quality checks."
        ),
    )
    parser.add_argument(
        "--export-classical-mirror-backbone",
        action="store_true",
        help=(
            "Use an independent pure-KLT tracker as the VINS-visible classical "
            "backbone. Learned/LoFTR tracks from the main hybrid tracker are "
            "merged only as sidecars after the export gates pass."
        ),
    )
    parser.add_argument(
        "--final-mirror-preserve-classical-budget",
        action="store_true",
        help=(
            "At the final independent-KLT mirror publication boundary, never "
            "remove a classical mirror observation to admit a learned sidecar. "
            "Sidecars may use only capacity left below --export-max-features; "
            "when no capacity remains the exact mirror is restored."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-replacement",
        action="store_true",
        help=(
            "Experimental birth-for-birth arbitration: after the independent "
            "KLT mirror is formed, accepted confirmed-XFeat sidecars may replace "
            "only same-frame GFTT births with a strict age advantage and only "
            "inside the configured early selected-frame horizon."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-max-selected-frame",
        type=int,
        default=4,
        help="Last selected feature frame eligible for persistence replacement.",
    )
    parser.add_argument(
        "--final-mirror-persistence-min-age-advantage",
        type=int,
        default=2,
        help="Minimum raw track-age advantage required over a GFTT birth.",
    )
    parser.add_argument(
        "--final-mirror-persistence-single-chain",
        action="store_true",
        help=(
            "Restrict early persistence replacement to one committed XFeat "
            "identity for the whole startup horizon. The identity cannot be "
            "switched if it disappears."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-min-gftt-ratio",
        type=float,
        default=0.0,
        help=(
            "Optional latched startup churn guard for persistence replacement. "
            "At the first eligible sidecar frame, arm replacement only when "
            "same-frame GFTT births divided by the cap-limited mirror count "
            "meet this ratio. Values <=0 disable the guard."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-source-router",
        action="store_true",
        help=(
            "Fail closed to an explicit confirmed learned-source allowlist "
            "before persistence replacement or vacant-capacity admission."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-allow-all-non-loftr",
        action="store_true",
        help=(
            "Under the source router, allow confirmed XFeat or SP+LG/other "
            "non-LoFTR learned lineages. LoFTR remains ineligible."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-same-grid-cell",
        action="store_true",
        help=(
            "Permit a full-budget birth replacement only when the confirmed "
            "sidecar and the GFTT birth occupy the same image grid cell."
        ),
    )
    parser.add_argument(
        "--final-mirror-persistence-coverage-monotone",
        action="store_true",
        help=(
            "Permit an age-1 GFTT donor outside the sidecar cell only when "
            "the donor cell remains occupied and occupied grid-cell count "
            "cannot decrease after each deterministic exchange."
        ),
    )
    parser.add_argument("--final-mirror-persistence-grid-rows", type=int, default=4)
    parser.add_argument("--final-mirror-persistence-grid-cols", type=int, default=6)
    parser.add_argument(
        "--final-mirror-persistence-max-per-frame",
        type=int,
        default=0,
        help=(
            "Maximum persistence-router sidecars admitted on one published "
            "frame. Values <=0 preserve the historical unbounded behavior."
        ),
    )
    parser.add_argument(
        "--final-mirror-prefill-slot-admission",
        action="store_true",
        help=(
            "Development-only protected admission: retain every carried "
            "independent-mirror observation, admit a bounded number of "
            "confirmed non-LoFTR candidates into capacity available before "
            "same-frame GFTT refill, then fill remaining slots with mirror "
            "GFTT births in their original order. This changes potential "
            "newborn GFTT births and is not an intrinsically no-harm mode."
        ),
    )
    parser.add_argument(
        "--final-mirror-prefill-slot-max-selected-frame",
        type=int,
        default=4,
        help="Last selected feature frame eligible for pre-refill slot admission.",
    )
    parser.add_argument(
        "--final-mirror-prefill-slot-min-age",
        type=int,
        default=3,
        help="Minimum raw age for a confirmed candidate using a pre-refill slot.",
    )
    parser.add_argument(
        "--final-mirror-prefill-slot-allow-all-non-loftr",
        action="store_true",
        help=(
            "Allow confirmed XFeat and SP+LG/other non-LoFTR learned "
            "candidates. Without this flag, only confirmed XFeat is eligible."
        ),
    )
    parser.add_argument(
        "--final-mirror-prefill-slot-max-per-frame",
        type=int,
        default=0,
        help=(
            "Maximum candidates admitted before GFTT refill on one published "
            "frame. Values <=0 leave the available pre-refill capacity as the limit."
        ),
    )
    parser.add_argument(
        "--formal-export-allow-sparse-backbone",
        action="store_true",
        help=(
            "Keep the formal three-layer learned/LoFTR gates, but do not force "
            "the pure-KLT mirror backbone. This is useful for low-texture "
            "LoFTR sidecar profiles where KLT support should be allowed to "
            "decay naturally before a small confirmed sidecar enters VINS."
        ),
    )
    parser.add_argument(
        "--formal-export-preserve-input-backbone",
        action="store_true",
        help=(
            "Keep the formal three-layer learned/LoFTR gates, but prevent the "
            "formal defaults from enabling an extra KLT mirror/refill backbone. "
            "The exported classical backbone then follows the configured input "
            "frontend, and learned/LoFTR points may only change VINS input when "
            "the sidecar gates accept them."
        ),
    )
    parser.add_argument(
        "--formal-export-adaptive-mirror-fallback",
        action="store_true",
        help=(
            "With the formal three-layer policy, evaluate learned/LoFTR "
            "sidecars on the sparse hybrid backbone first. If no sidecar "
            "survives the strict gates, export the pure-KLT mirror backbone "
            "instead. This makes learned modules sidecar-only: they change "
            "VINS input only when they are actually accepted."
        ),
    )
    parser.add_argument(
        "--formal-export-zero-sidecar-mirror-restore",
        action="store_true",
        help=(
            "With the formal three-layer policy, force the final export back "
            "to the protected KLT mirror whenever no learned/recovered/LoFTR "
            "sidecar survives all gates. This enforces zero-learned parity."
        ),
    )
    parser.add_argument(
        "--formal-export-disable-post-sidecar-mirror-refill",
        action="store_true",
        help=(
            "Do not refill pruned sidecar frames back to the full KLT mirror "
            "count after the learned sidecar gates and sequence budget run. "
            "The default keeps the full-mirror no-harm contract; disabling "
            "this is intended for sparse low-texture contribution studies."
        ),
    )
    parser.add_argument(
        "--formal-export-motion-adaptive-post-sidecar-refill",
        action="store_true",
        help=(
            "When post-sidecar mirror refill is otherwise disabled, re-enable "
            "it for accepted sidecar bursts whose classical KLT motion is high. "
            "This preserves sparse learned support in low-motion low-texture "
            "windows but keeps the full mirror in high-motion windows where "
            "small learned sidecars can perturb VINS."
        ),
    )
    parser.add_argument(
        "--formal-export-motion-adaptive-refill-max-motion-px",
        type=float,
        default=9.0,
        help=(
            "Classical median track motion threshold for motion-adaptive "
            "post-sidecar mirror refill. Sidecar frames above this threshold "
            "use the full mirror refill."
        ),
    )
    parser.add_argument(
        "--formal-export-motion-adaptive-refill-hold-frames",
        type=int,
        default=8,
        help=(
            "Selected feature frames for which motion-adaptive mirror refill "
            "stays active after a high-motion sidecar frame."
        ),
    )
    parser.add_argument(
        "--formal-export-legacy-loftr-rescue",
        action="store_true",
        help=(
            "Keep the formal three-layer export gates but preserve the older "
            "LoFTR6 low-texture rescue budgets for reproducibility studies. "
            "This does not bypass confirmation, geometry, or benefit gates."
        ),
    )
    parser.add_argument(
        "--formal-export-allow-low-parallax-sidecars",
        action="store_true",
        help=(
            "Allow learned/LoFTR sidecars to enter VINS even when the early "
            "parallax initialization gate fires. The formal default blocks "
            "these sidecars for the whole low-parallax sequence because they "
            "can destabilize VINS initialization despite passing local gates."
        ),
    )
    parser.add_argument(
        "--formal-export-low-texture-active-sidecar",
        action="store_true",
        help=(
            "Use a less conservative formal sidecar profile for verified "
            "low-texture windows. The KLT mirror backbone and geometry gates "
            "remain active, but caller-specified low thresholds for confirmed "
            "XFeat/SP-LG weak-cell support are preserved instead of being "
            "clamped to the no-harm default profile."
        ),
    )
    parser.add_argument(
        "--mirror-measurement-selection-policy",
        choices=(
            "baseline",
            "config",
            "warmup_config",
            "klt_default",
            "warmup_full_klt_default",
            "adaptive_warmup_full_klt_default",
        ),
        default="baseline",
        help=(
            "Measurement-selection policy for the KLT mirror backbone. "
            "'baseline' preserves the full KLT/GFTT mirror output so gated-out "
            "learned sidecars cannot change the exported backbone; 'config' "
            "applies the active frontend selector to the mirror output; "
            "'warmup_config' applies the active selector only while the VINS "
            "warmup/KLT-only gate is active, then returns to the protected "
            "baseline backbone; 'klt_default' applies the default KLT-style "
            "geometry/coverage selector to the mirror, matching pure KLT "
            "baseline export contracts more closely than the hybrid sparse "
            "selector; 'warmup_full_klt_default' keeps the full KLT/GFTT "
            "mirror during VINS warmup and then switches to the KLT-style "
            "selector; 'adaptive_warmup_full_klt_default' does the same only "
            "when the early parallax probe falls in the configured "
            "initialization-risk interval."
        ),
    )
    parser.add_argument(
        "--adaptive-warmup-full-min-init-parallax-px",
        type=float,
        default=7.0,
        help=(
            "Lower bound for enabling adaptive full KLT/GFTT mirror during "
            "VINS warmup. Values below this stay in the low-parallax "
            "initialization-protection path."
        ),
    )
    parser.add_argument(
        "--adaptive-warmup-full-max-init-parallax-px",
        type=float,
        default=12.5,
        help=(
            "Upper bound for enabling adaptive full KLT/GFTT mirror during "
            "VINS warmup. Higher-parallax windows use the KLT-default mirror "
            "contract for no-harm."
        ),
    )
    parser.add_argument("--learned-export-min-classical-tracks", type=int, default=300)
    parser.add_argument("--learned-export-min-classical-grid", type=float, default=0.84)
    parser.add_argument("--learned-export-min-age", type=int, default=5)
    parser.add_argument("--learned-export-loftr-min-age", type=int, default=None)
    parser.add_argument("--learned-export-min-quality", type=float, default=0.20)
    parser.add_argument("--learned-export-min-ncc", type=float, default=0.58)
    parser.add_argument("--learned-export-max-fb", type=float, default=0.90)
    parser.add_argument(
        "--learned-export-non-loftr-requires-degraded-mode",
        action="store_true",
        help=(
            "Allow SuperPoint/LightGlue and XFeat sidecars to enter VINS only "
            "when the frontend learned-mode indicates a real degraded-texture "
            "case. This prevents normal-texture low-coverage frames from "
            "perturbing the backend while keeping LoFTR under its own planar/"
            "extreme low-texture gates."
        ),
    )
    parser.add_argument("--learned-export-loftr-min-quality", type=float, default=None)
    parser.add_argument("--learned-export-loftr-min-ncc", type=float, default=None)
    parser.add_argument("--learned-export-loftr-max-fb", type=float, default=None)
    parser.add_argument(
        "--learned-export-benefit-gate",
        action="store_true",
        help=(
            "After source/geometry checks, export learned/LoFTR sidecars only "
            "when they add grid coverage that the classical KLT backbone lacks."
        ),
    )
    parser.add_argument(
        "--learned-export-benefit-loftr-only",
        action="store_true",
        help=(
            "Apply the coverage/new-cell benefit gate only to LoFTR sidecars. "
            "Confirmed SuperPoint/LightGlue/XFeat sidecars still need geometry "
            "stability, but do not need to create empty-cell gain."
        ),
    )
    parser.add_argument(
        "--learned-export-benefit-all-sources",
        action="store_true",
        help=(
            "Apply the coverage/new-cell benefit gate to every learned sidecar "
            "source. This is the stricter paper-facing policy: SP/LG, XFeat, "
            "and LoFTR enter VINS only when they visibly compensate for KLT "
            "coverage loss."
        ),
    )
    parser.add_argument(
        "--learned-export-sidecar-max-observations",
        type=int,
        default=0,
        help=(
            "Optional sequence-level cap on learned/LoFTR sidecar observations "
            "exported after all gates. A value of 0 disables the cap."
        ),
    )
    parser.add_argument(
        "--learned-export-low-parallax-sidecar-max-observations",
        type=int,
        default=0,
        help=(
            "Optional sequence-level cap used instead of "
            "--learned-export-sidecar-max-observations when the initialization "
            "parallax probe is triggered. This keeps low-parallax boundary "
            "windows sparse while allowing a larger learned support budget in "
            "true low-texture windows with enough motion."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-gate",
        action="store_true",
        help=(
            "Apply an online-style admission gate to learned sidecar seeds "
            "after the normal source/geometry gates: protect early VINS "
            "initialization, require confirmed seed tracks when requested, "
            "and cap accepted sidecar observations per frame and per sequence."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-sources",
        choices=[
            "non_loftr",
            "xfeat",
            "all_learned",
            "loftr",
            "classical_gftt",
        ],
        default="non_loftr",
        help=(
            "Learned source family controlled by --learned-export-online-seed-gate. "
            "The default targets XFeat/SuperPoint/LightGlue while leaving LoFTR's "
            "separate rescue policy untouched."
        ),
    )
    parser.add_argument("--learned-export-online-seed-warmup-frames", type=int, default=0)
    parser.add_argument("--learned-export-online-seed-max-observations", type=int, default=0)
    parser.add_argument("--learned-export-online-seed-max-per-frame", type=int, default=0)
    parser.add_argument(
        "--learned-export-online-seed-post-quality-cap-per-frame",
        type=int,
        default=0,
        help=(
            "After the online seed gate has selected target learned sidecars, "
            "keep only the top-N by frontend quality in each exported frame. "
            "This differs from --learned-export-online-seed-max-per-frame by "
            "ranking after the full candidate set has passed the online seed "
            "checks, matching the offline quality-cap ablation more closely."
        ),
    )
    parser.add_argument("--learned-export-online-seed-min-age", type=int, default=1)
    parser.add_argument("--learned-export-online-seed-min-quality", type=float, default=0.10)
    parser.add_argument("--learned-export-online-seed-min-ncc", type=float, default=0.42)
    parser.add_argument("--learned-export-online-seed-max-fb", type=float, default=1.20)
    parser.add_argument(
        "--learned-export-online-seed-normal-start-max-motion-px",
        type=float,
        default=0.0,
        help=(
            "Reject the first online learned seed burst in normal-geometry "
            "frames when enough confirmed target seeds have large median "
            "motion. This protects healthy normal-texture VINS windows from "
            "high-motion learned seed injection. Values <=0 disable the check."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-normal-start-min-frame-candidates",
        type=int,
        default=0,
        help="Minimum eligible target seeds required before the normal-motion start check can reject.",
    )
    parser.add_argument(
        "--learned-export-online-seed-normal-start-max-frame-candidates",
        type=int,
        default=0,
        help=(
            "Optional maximum eligible target seeds allowed before the "
            "normal-motion start check can reject. Values <=0 disable this "
            "upper bound."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-normal-start-min-classical-tracks",
        type=int,
        default=0,
        help="Minimum classical tracks required before the normal-motion start check can reject.",
    )
    parser.add_argument(
        "--learned-export-online-seed-normal-start-min-classical-grid",
        type=float,
        default=0.0,
        help="Minimum classical grid coverage required before the normal-motion start check can reject.",
    )
    parser.add_argument(
        "--learned-export-online-seed-require-confirmed",
        action="store_true",
        help=(
            "Require the controlled learned seeds to have a confirmed/memory "
            "source label before entering the VINS feature bag."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-require-fresh",
        action="store_true",
        help=(
            "Within the online seed gate, require target learned sidecar IDs "
            "to be freshly confirmed after the warmup window, or still inside "
            "the configured fresh confirmation hold interval."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-fresh-scope",
        choices=["id", "frame"],
        default="id",
        help=(
            "Fresh-confirmation scope for --learned-export-online-seed-require-fresh. "
            "'id' admits only IDs observed in the fresh confirmation frame; "
            "'frame' opens a short post-warmup sidecar burst window."
        ),
    )
    parser.add_argument("--learned-export-online-seed-fresh-hold-frames", type=int, default=0)
    parser.add_argument(
        "--learned-export-online-seed-microburst-gate",
        action="store_true",
        help=(
            "Limit online learned seed admission to the first compact burst "
            "after warmup. The burst starts on the first frame with an eligible "
            "seed and remains open for "
            "--learned-export-online-seed-microburst-frames selected feature frames."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-frames",
        type=int,
        default=0,
        help=(
            "Number of selected feature frames kept by "
            "--learned-export-online-seed-microburst-gate. Values <=0 disable "
            "the span limit even if the flag is present."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-frames",
        type=int,
        default=0,
        help=(
            "Optional adaptive total span for the online seed micro-burst. "
            "When greater than --learned-export-online-seed-microburst-frames, "
            "the burst is extended only if the initial burst passes the "
            "configured count/coverage checks."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-min-initial-observations",
        type=int,
        default=0,
        help=(
            "Minimum eligible learned observations accumulated during the base "
            "micro-burst before allowing the adaptive extension. A value of 0 "
            "disables this check."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-min-initial-cells",
        type=int,
        default=0,
        help=(
            "Minimum occupied grid cells among eligible learned observations in "
            "the base micro-burst before allowing extension. A value of 0 "
            "disables this check."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-min-bbox-area-ratio",
        type=float,
        default=0.0,
        help=(
            "Minimum image-normalized bounding-box area covered by eligible "
            "learned observations in the base micro-burst before allowing "
            "extension. A value of 0 disables this check."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-grid-rows",
        type=int,
        default=6,
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-extend-grid-cols",
        type=int,
        default=6,
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-max-restarts",
        type=int,
        default=0,
        help=(
            "Allow the online seed micro-burst gate to restart after a failed "
            "or expired burst. This is useful for sparse confirmed lineage "
            "windows where XFeat appears in separated groups rather than one "
            "early dense burst. A value of 0 preserves the original one-shot "
            "behavior."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-microburst-restart-cooldown-frames",
        type=int,
        default=8,
        help=(
            "Selected feature frames to wait after the previous online seed "
            "burst ends before another burst may start. Used only when "
            "--learned-export-online-seed-microburst-max-restarts is positive."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-lineage-continuation",
        action="store_true",
        help=(
            "After the micro-burst window, allow a small number of mature, "
            "confirmed target-source tracks whose learned provenance survived "
            "inside the KLT state. This keeps the policy on chained tracks "
            "rather than pairwise matches."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-lineage-min-age",
        type=int,
        default=8,
        help="Minimum age for lineage-continuation target tracks.",
    )
    parser.add_argument(
        "--learned-export-online-seed-lineage-max-per-frame",
        type=int,
        default=2,
        help="Per-frame cap for lineage-continuation target tracks.",
    )
    parser.add_argument(
        "--learned-export-online-seed-lineage-max-observations",
        type=int,
        default=20,
        help="Sequence-level cap for lineage-continuation target tracks.",
    )
    parser.add_argument(
        "--learned-export-online-seed-lineage-separate-budget",
        action="store_true",
        help=(
            "Treat the lineage-continuation cap as an additional budget after "
            "the initial online-seed budget is exhausted. The default keeps "
            "the legacy shared-budget behavior."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-dense-start-max-observations",
        type=int,
        default=0,
        help=(
            "Optional online seed budget used when the first eligible seed "
            "frame arrives on an already dense classical backbone. This keeps "
            "redundant planar seed bursts from over-constraining VINS. Values "
            "<=0 disable this cap."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-dense-start-min-classical-tracks",
        type=int,
        default=0,
        help=(
            "Minimum classical backbone tracks required to activate "
            "--learned-export-online-seed-dense-start-max-observations."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-dense-start-min-classical-grid",
        type=float,
        default=1.0,
        help=(
            "Minimum classical grid coverage required to activate the online "
            "seed dense-start cap."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-dense-start-min-frame-candidates",
        type=int,
        default=0,
        help=(
            "Minimum eligible target seed candidates in the first seed frame "
            "required to activate the online seed dense-start cap."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-sparse-start-min-frame-candidates",
        type=int,
        default=0,
        help=(
            "When positive, suppress the first online seed frame if it has "
            "fewer eligible learned seed candidates than this value. This "
            "keeps isolated one-point seeds from perturbing VINS initialization."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-sparse-start-min-classical-tracks",
        type=int,
        default=0,
        help=(
            "Minimum classical tracks required before the sparse-start online "
            "seed suppressor can activate."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-sparse-start-min-classical-grid",
        type=float,
        default=0.0,
        help=(
            "Minimum classical grid coverage required before the sparse-start "
            "online seed suppressor can activate."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-start-min-classical-grid",
        type=float,
        default=0.0,
        help=(
            "When positive, suppress the first online seed burst unless the "
            "classical backbone already covers at least this grid fraction. "
            "This avoids letting learned seeds steer VINS initialization from "
            "a poorly distributed classical support set."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-start-min-classical-grid-tracks",
        type=int,
        default=0,
        help=(
            "Minimum classical tracks required before "
            "--learned-export-online-seed-start-min-classical-grid can "
            "suppress an online seed start."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-max-classical-gftt-ratio",
        type=float,
        default=0.0,
        help=(
            "When positive, suppress online learned seeds on frames where a "
            "healthy classical backbone is dominated by fresh GFTT births. "
            "Such frames are often already well covered but not mature enough "
            "for learned seeds to safely steer initialization."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-max-start-classical-gftt-ratio",
        type=float,
        default=0.0,
        help=(
            "When positive, suppress only the first online seed start if the "
            "classical backbone already has too many fresh GFTT births. This "
            "is milder than --learned-export-online-seed-max-classical-gftt-ratio "
            "because it does not prune later frames after a seed burst has "
            "been accepted."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-start-gftt-ratio-min-classical-tracks",
        type=int,
        default=0,
        help=(
            "Minimum classical tracks required before "
            "--learned-export-online-seed-max-start-classical-gftt-ratio can "
            "suppress an online seed start."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-start-gftt-ratio-min-classical-grid",
        type=float,
        default=0.0,
        help=(
            "Minimum classical grid coverage required before "
            "--learned-export-online-seed-max-start-classical-gftt-ratio can "
            "suppress an online seed start."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-gftt-ratio-min-classical-tracks",
        type=int,
        default=0,
        help=(
            "Minimum classical tracks required before "
            "--learned-export-online-seed-max-classical-gftt-ratio can activate."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-gftt-ratio-min-classical-grid",
        type=float,
        default=0.0,
        help=(
            "Minimum classical grid coverage required before "
            "--learned-export-online-seed-max-classical-gftt-ratio can activate."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-refill-rejected-with-mirror",
        action="store_true",
        help=(
            "When the online seed gate rejects learned seeds, refill the frame "
            "from the independent classical mirror backbone up to the pre-gate "
            "feature count. This makes learned rejection a true no-harm "
            "fallback instead of leaving holes where rejected seeds had been."
        ),
    )
    parser.add_argument(
        "--learned-export-online-seed-mirror-only-after-reject",
        action="store_true",
        help=(
            "When the first online seed burst is rejected as sparse or "
            "GFTT-dominated, export the independent classical mirror backbone "
            "for subsequent frames. This is a stronger no-harm fallback than "
            "per-frame refill because it also restores mirror track identity "
            "after a risky seed attempt."
        ),
    )
    parser.add_argument(
        "--learned-export-temporal-burst-gate",
        action="store_true",
        help=(
            "After source/geometry/benefit checks, suppress late isolated "
            "learned/LoFTR sidecars unless they are part of a recent accepted "
            "burst. This keeps pairwise learned matches from perturbing VINS "
            "as one-off backend observations."
        ),
    )
    parser.add_argument(
        "--learned-export-burst-window",
        type=int,
        default=12,
        help="Selected-frame lookback window used by the temporal sidecar burst gate.",
    )
    parser.add_argument(
        "--learned-export-burst-min-recent-frames",
        type=int,
        default=1,
        help=(
            "Number of accepted sidecar frames required in the recent lookback "
            "window before a late sidecar frame may enter VINS."
        ),
    )
    parser.add_argument(
        "--learned-export-burst-late-start-frame",
        type=int,
        default=80,
        help=(
            "Selected feature frame at which isolated sidecar frames become "
            "late enough to require temporal support. Earlier low-texture "
            "startup/rescue sidecars are left to the other gates."
        ),
    )
    parser.add_argument(
        "--learned-export-burst-min-sidecars",
        type=int,
        default=3,
        help=(
            "Allow a late sidecar frame without recent temporal support only "
            "when this many sidecars survive the earlier gates in the same frame."
        ),
    )
    parser.add_argument(
        "--learned-export-allow-postinit-loftr-support",
        action="store_true",
        help=(
            "Allow a late isolated LoFTR frame only when it is a small, confirmed "
            "post-initialization support-rescue batch that already passed the "
            "degradation, FEH residual, and benefit gates."
        ),
    )
    parser.add_argument(
        "--learned-export-allow-early-loftr-support",
        action="store_true",
        help=(
            "Allow an early LoFTR support-rescue batch through the temporal "
            "sidecar gate only when the initialization parallax gate did not "
            "fire. Low-parallax initialization stays KLT-only."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-early-persistence",
        action="store_true",
        help=(
            "After all learned export gates pass, keep a tiny early confirmed "
            "LoFTR support batch visible for a few following feature frames. "
            "This is default-off and intended for initialization-boundary "
            "low-texture windows."
        ),
    )
    parser.add_argument("--learned-export-loftr-persistence-hold-frames", type=int, default=5)
    parser.add_argument("--learned-export-loftr-persistence-max-source-frame", type=int, default=8)
    parser.add_argument("--learned-export-loftr-persistence-max-per-frame", type=int, default=3)
    parser.add_argument("--learned-export-loftr-persistence-max-source-frames", type=int, default=1)
    parser.add_argument("--learned-export-loftr-persistence-max-total", type=int, default=15)
    parser.add_argument("--learned-export-loftr-persistence-quality-scale", type=float, default=1.0)
    parser.add_argument(
        "--learned-export-allow-isolated-non-loftr-sidecars",
        action="store_true",
        help=(
            "Let a very small confirmed SuperPoint/LightGlue or XFeat sidecar "
            "frame pass the temporal burst gate after it has already passed "
            "degradation, coverage-benefit, and F/E/H residual gates. LoFTR is "
            "not covered by this exception."
        ),
    )
    parser.add_argument(
        "--learned-export-isolated-non-loftr-max-count",
        type=int,
        default=2,
        help=(
            "Maximum number of non-LoFTR sidecar observations allowed by the "
            "isolated non-LoFTR temporal exception."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-gate",
        action="store_true",
        help=(
            "After geometry/coverage gates, export learned sidecars only after "
            "the same sidecar id has appeared in the VINS-visible export stream "
            "for several nearby frames. This suppresses one-off learned matches "
            "that cannot form useful backend tracks."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-min-frames",
        type=int,
        default=3,
        help="Minimum VINS-visible sidecar streak before a learned id may be exported.",
    )
    parser.add_argument(
        "--learned-export-visible-track-max-gap",
        type=int,
        default=1,
        help="Maximum selected-frame gap still counted as the same visible sidecar streak.",
    )
    parser.add_argument(
        "--learned-export-visible-track-max-mean-step-px",
        type=float,
        default=0.0,
        help=(
            "Maximum online mean pixel step over the current visible sidecar "
            "streak. Values <= 0 disable the motion-consistency gate."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-min-count-per-frame",
        type=int,
        default=0,
        help=(
            "Minimum number of learned/recovered tracks that must jointly pass "
            "the visible-track gate in a frame. Values <= 1 disable this gate."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-motion-degraded-only",
        action="store_true",
        help=(
            "Apply the visible-track mean-step threshold only in degraded_texture "
            "or severe_low_texture mode; other geometry modes keep streak/count gating."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-motion-min-frame",
        type=int,
        default=0,
        help=(
            "Apply the visible-track mean-step threshold only at or after this "
            "selected feature frame. Zero enables it from the beginning."
        ),
    )
    parser.add_argument(
        "--learned-export-visible-track-min-count-min-classical-grid",
        type=float,
        default=0.0,
        help=(
            "Apply the per-frame learned-count minimum only when classical grid "
            "coverage is at least this value. Zero applies it unconditionally."
        ),
    )
    parser.add_argument(
        "--learned-export-require-fresh-non-loftr-confirmation",
        action="store_true",
        help=(
            "Export non-LoFTR learned sidecars only when the tracker reports "
            "a fresh LK/NCC/FB-confirmed learned promotion in the same feature "
            "frame, or within a short hold window. LoFTR is excluded because it "
            "uses its own extreme-texture/planar rescue policy."
        ),
    )
    parser.add_argument(
        "--learned-export-fresh-confirmation-hold-frames",
        type=int,
        default=0,
        help=(
            "Additional selected feature frames for which a freshly confirmed "
            "non-LoFTR sidecar id remains exportable after the confirmation "
            "frame. A value of 0 requires same-frame confirmation."
        ),
    )
    parser.add_argument(
        "--learned-export-recent-health-suppression",
        action="store_true",
        help=(
            "Suppress non-LoFTR learned sidecars when the recent KLT mirror "
            "backbone has been consistently healthy. This protects normal or "
            "stable-texture VINS windows from unnecessary XFeat/SP-LG support "
            "while leaving LoFTR's extreme low-texture rescue path separate."
        ),
    )
    parser.add_argument("--learned-export-recent-health-window", type=int, default=24)
    parser.add_argument("--learned-export-recent-health-min-frames", type=int, default=12)
    parser.add_argument("--learned-export-recent-health-min-tracks", type=int, default=300)
    parser.add_argument("--learned-export-recent-health-min-grid", type=float, default=0.88)
    parser.add_argument("--learned-export-recent-health-min-age", type=float, default=18.0)
    parser.add_argument(
        "--learned-export-final-mirror-health-suppression",
        action="store_true",
        help=(
            "In adaptive mirror fallback mode, suppress SuperPoint/LightGlue "
            "and XFeat sidecars before they are appended to the full KLT mirror "
            "when that final mirror backbone is already healthy. This keeps "
            "non-LoFTR learned points as true degraded-frame sidecars instead "
            "of perturbing a sufficiently constrained VINS export. LoFTR keeps "
            "its separate extreme low-texture/planar gates."
        ),
    )
    parser.add_argument("--learned-export-final-mirror-health-min-tracks", type=int, default=300)
    parser.add_argument("--learned-export-final-mirror-health-min-grid", type=float, default=0.84)
    parser.add_argument("--learned-export-final-mirror-health-min-age", type=float, default=0.0)
    parser.add_argument(
        "--learned-export-stale-healthy-unconfirmed-suppression",
        action="store_true",
        help=(
            "Suppress non-LoFTR learned sidecars when they appear as an "
            "unconfirmed burst while the export-gate diagnostics indicate a "
            "stable KLT backbone. This targets FR90-like identity churn: "
            "recovery_reason=healthy, zero fresh learned confirmations, "
            "mature KLT age, and adequate KLT grid coverage."
        ),
    )
    parser.add_argument("--learned-export-stale-healthy-window", type=int, default=12)
    parser.add_argument("--learned-export-stale-healthy-min-frames", type=int, default=1)
    parser.add_argument("--learned-export-stale-healthy-min-classical-tracks", type=int, default=0)
    parser.add_argument("--learned-export-stale-healthy-min-classical-grid", type=float, default=0.58)
    parser.add_argument("--learned-export-stale-healthy-min-classical-age", type=float, default=20.0)
    parser.add_argument(
        "--learned-export-stale-healthy-max-used-observations",
        type=int,
        default=0,
        help=(
            "If positive, apply stale-healthy suppression only while the "
            "sequence-level learned sidecar budget used so far is at or below "
            "this value. The default 0 disables this extra ceiling."
        ),
    )
    parser.add_argument(
        "--learned-export-short-lowgrid-seed-suppression",
        action="store_true",
        help=(
            "Suppress non-LoFTR learned sidecars when a sidecar burst starts "
            "with too few low-grid support frames and immediately transitions "
            "to recovery_reason=healthy. This targets FR85-like identity churn "
            "without suppressing longer FR80-style low-grid support bursts."
        ),
    )
    parser.add_argument("--learned-export-short-lowgrid-seed-min-frames", type=int, default=3)
    parser.add_argument("--learned-export-short-lowgrid-seed-max-gap", type=int, default=2)
    parser.add_argument(
        "--learned-export-short-lowgrid-seed-max-lowgrid-frames",
        type=int,
        default=0,
        help=(
            "If positive, suppress non-LoFTR sidecars after this many "
            "low-grid frames inside the same sidecar burst. This keeps learned "
            "support as a bounded refill instead of a long replacement track."
        ),
    )
    parser.add_argument(
        "--learned-export-short-lowgrid-long-tail-consumes-budget",
        action="store_true",
        help=(
            "Count sidecars vetoed by the long low-grid burst cap against the "
            "sequence sidecar observation budget, so risky long-tail proposals "
            "are not replaced by later learned bursts in the same window."
        ),
    )
    parser.add_argument(
        "--learned-export-lowgrid-seed-window-gate",
        action="store_true",
        help=(
            "Within a continuous low-grid non-LoFTR sidecar burst, export only "
            "a bounded seed-confirmed phase. Early bursts may use a shorter "
            "wait window than later bursts, so XFeat/SP-LG act as support "
            "pulses instead of replacing the KLT backbone for the whole burst."
        ),
    )
    parser.add_argument(
        "--learned-export-lowgrid-seed-early-max-start-frame",
        type=int,
        default=40,
        help=(
            "A low-grid sidecar burst whose first selected feature index is "
            "below this value uses the early seed window."
        ),
    )
    parser.add_argument("--learned-export-lowgrid-seed-early-min-frame", type=int, default=1)
    parser.add_argument("--learned-export-lowgrid-seed-early-max-frame", type=int, default=8)
    parser.add_argument("--learned-export-lowgrid-seed-late-min-frame", type=int, default=5)
    parser.add_argument("--learned-export-lowgrid-seed-late-max-frame", type=int, default=10)
    parser.add_argument(
        "--learned-export-lowgrid-seed-window-consumes-budget",
        action="store_true",
        help=(
            "Count non-LoFTR sidecars vetoed by the low-grid seed window "
            "against the sequence sidecar budget. This prevents early seed "
            "candidates that were held out of VINS from being replaced by "
            "later healthy-frame sidecars in the same sequence."
        ),
    )
    parser.add_argument(
        "--learned-export-suppress-non-loftr-recovery-reason",
        action="store_true",
        help=(
            "Suppress non-LoFTR learned sidecars when the frontend recovery "
            "reason contains any configured veto token. This is intended for "
            "degradation modes such as backscatter/low contrast where pairwise "
            "learned support passed local gates but was harmful to VINS. LoFTR "
            "is not affected."
        ),
    )
    parser.add_argument(
        "--learned-export-suppress-recovery-reason-tokens",
        default="backscatter_or_low_contrast",
        help=(
            "Comma-separated recovery-reason tokens used by "
            "--learned-export-suppress-non-loftr-recovery-reason."
        ),
    )
    parser.add_argument(
        "--learned-export-recovery-suppression-consumes-budget",
        action="store_true",
        help=(
            "Count non-LoFTR learned observations vetoed by recovery reason "
            "against the sequence sidecar observation budget. This prevents "
            "dangerous recovery-frame sidecars from simply being replaced by "
            "later learned observations in the same window."
        ),
    )
    parser.add_argument(
        "--learned-export-recovery-burst-suppression",
        action="store_true",
        help=(
            "Suppress non-LoFTR learned sidecars after a sustained burst of "
            "configured recovery reasons in a recent selected-frame window. "
            "This is a sequence-level reliability guard for persistent "
            "backscatter/low-contrast degradation; LoFTR remains available."
        ),
    )
    parser.add_argument(
        "--learned-export-recovery-burst-window",
        type=int,
        default=90,
        help="Selected-frame window used by recovery burst suppression.",
    )
    parser.add_argument(
        "--learned-export-recovery-burst-min-frames",
        type=int,
        default=16,
        help="Minimum matched recovery-reason frames needed to activate burst suppression.",
    )
    parser.add_argument(
        "--learned-export-recovery-burst-tokens",
        default="backscatter_or_low_contrast",
        help="Comma-separated recovery-reason tokens for burst suppression.",
    )
    parser.add_argument(
        "--learned-export-min-grid-gain",
        type=float,
        default=0.041,
        help="Minimum grid coverage gain required from accepted learned sidecars.",
    )
    parser.add_argument(
        "--learned-export-min-new-cells",
        type=int,
        default=1,
        help="Minimum number of previously empty KLT grid cells learned sidecars must fill.",
    )
    parser.add_argument(
        "--learned-export-min-new-cell-ratio",
        type=float,
        default=0.30,
        help="Minimum fraction of geometrically valid sidecars that must lie in new KLT grid cells.",
    )
    parser.add_argument(
        "--learned-export-max-per-new-cell",
        type=int,
        default=1,
        help="Maximum learned sidecars exported per newly covered grid cell.",
    )
    parser.add_argument(
        "--learned-export-coverage-gain-max-classical-tracks",
        type=int,
        default=0,
        help=(
            "Optional KLT-backbone count ceiling for ordinary non-LoFTR "
            "coverage-gain sidecars. A value of 0 disables the ceiling. "
            "This blocks sparse XFeat/SP-LG points from entering VINS when "
            "KLT already has strong global support, while leaving LoFTR's "
            "explicit planar rescue path available for textureless scenes."
        ),
    )
    parser.add_argument(
        "--learned-export-weak-cell-rescue",
        action="store_true",
        help=(
            "Allow a small number of learned sidecars in KLT-weak grid cells "
            "when no enough empty-cell gain is available."
        ),
    )
    parser.add_argument(
        "--learned-export-non-loftr-weak-cell-rescue",
        action="store_true",
        help=(
            "Allow confirmed non-LoFTR learned sidecars, such as XFeat or "
            "SuperPoint/LightGlue, to enter sparse occupied KLT cells. This "
            "is stricter than the normal new-cell benefit path because it is "
            "intended only for low-texture windows where a few geometry-stable "
            "learned observations can keep VINS initialized."
        ),
    )
    parser.add_argument("--learned-export-weak-cell-max-count", type=int, default=2)
    parser.add_argument("--learned-export-weak-cell-min-candidates", type=int, default=5)
    parser.add_argument("--learned-export-weak-cell-max-occupancy", type=int, default=8)
    parser.add_argument("--learned-export-weak-cell-min-classical-motion-px", type=float, default=3.0)
    parser.add_argument("--learned-export-weak-cell-max-classical-grid", type=float, default=0.82)
    parser.add_argument(
        "--learned-export-weak-cell-max-classical-tracks",
        type=int,
        default=0,
        help=(
            "Optional KLT-backbone count ceiling for weak-cell learned rescue. "
            "A value of 0 disables the count ceiling. This keeps weak-cell "
            "sidecars for genuinely sparse low-texture frames while blocking "
            "them when KLT already has enough global support."
        ),
    )
    parser.add_argument(
        "--learned-export-coverage-seeded-continuation-gate",
        action="store_true",
        help=(
            "For non-LoFTR learned sidecars, allow weak-cell or budget-partial "
            "continuation only for feature ids that were first admitted by an "
            "accepted coverage-gain frame. This keeps XFeat/SP-LG as coverage "
            "support instead of allowing weak-cell-only learned tracks."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-seeded-continuation-gate",
        action="store_true",
        help=(
            "Keep a confirmed LoFTR observation when the same internal id was "
            "admitted on the preceding exported frame and still passes the "
            "current basic and FEH geometry gates. This bypasses only repeated "
            "new-cell benefit testing; it does not reconnect gaps or relax KLT."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-seeded-continuation-max-gap",
        type=int,
        default=1,
        help="Maximum exported-frame gap for LoFTR seeded continuation.",
    )
    parser.add_argument(
        "--learned-export-continuation-max-classical-age",
        type=float,
        default=26.0,
        help=(
            "Maximum classical median track age for coverage-seeded learned "
            "continuation frames. Higher values indicate KLT is already stable."
        ),
    )
    parser.add_argument(
        "--learned-export-continuation-max-classical-motion-px",
        type=float,
        default=10.5,
        help=(
            "Maximum classical median motion in pixels for coverage-seeded "
            "learned continuation frames."
        ),
    )
    parser.add_argument(
        "--learned-export-mature-cell-rescue",
        action="store_true",
        help=(
            "Allow a small number of non-LoFTR learned sidecars in low-grid "
            "frames when the KLT backbone is already temporally mature. This "
            "recovers A06-like stable SP/LG support while blocking short-age "
            "identity churn."
        ),
    )
    parser.add_argument("--learned-export-mature-cell-max-count", type=int, default=6)
    parser.add_argument("--learned-export-mature-cell-min-candidates", type=int, default=4)
    parser.add_argument("--learned-export-mature-cell-min-classical-age", type=float, default=10.0)
    parser.add_argument("--learned-export-mature-cell-min-classical-motion-px", type=float, default=3.0)
    parser.add_argument("--learned-export-mature-cell-max-classical-grid", type=float, default=0.84)
    parser.add_argument("--learned-export-mature-cell-max-per-cell", type=int, default=2)
    parser.add_argument("--learned-export-mature-cell-max-occupancy", type=int, default=8)
    parser.add_argument(
        "--learned-export-loftr-planar-rescue",
        action="store_true",
        help=(
            "Allow a tiny number of confirmed LoFTR sidecars in planar/extreme "
            "low-texture frames even when they do not create brand-new grid cells."
        ),
    )
    parser.add_argument("--learned-export-loftr-planar-max-count", type=int, default=3)
    parser.add_argument("--learned-export-loftr-planar-min-candidates", type=int, default=3)
    parser.add_argument("--learned-export-loftr-planar-max-classical-grid", type=float, default=0.92)
    parser.add_argument("--learned-export-loftr-planar-min-classical-motion-px", type=float, default=1.2)
    parser.add_argument(
        "--learned-export-loftr-weak-cell-rescue",
        action="store_true",
        help=(
            "Allow a small burst of confirmed LoFTR sidecars in KLT weak/occupied "
            "cells when the classical grid is degraded and export-level geometry "
            "is stable. This is the lowest-texture fallback path."
        ),
    )
    parser.add_argument("--learned-export-loftr-weak-cell-max-count", type=int, default=0)
    parser.add_argument("--learned-export-loftr-weak-cell-max-occupancy", type=int, default=48)
    parser.add_argument(
        "--learned-export-loftr-rescue-max-classical-tracks",
        type=int,
        default=0,
        help=(
            "Optional maximum number of classical backend tracks for any "
            "LoFTR rescue sidecar. Values <=0 disable the count gate. This "
            "keeps LoFTR as an extreme low-support supplement rather than a "
            "perturbation in frames that already have many KLT constraints."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-support-max-init-parallax-px",
        type=float,
        default=0.0,
        help=(
            "Optional window-level initialization-parallax ceiling for LoFTR "
            "weak-cell/support rescue. Values <=0 disable the ceiling. This "
            "keeps LoFTR as an extreme low-texture support module and blocks "
            "support insertion in high-parallax windows where KLT already has "
            "enough initialization geometry."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-support-max-classical-motion-px",
        type=float,
        default=0.0,
        help=(
            "Optional median KLT motion ceiling for LoFTR weak-cell/support "
            "rescue. Values <=0 disable the ceiling. This keeps LoFTR as a "
            "slow near-wall, extreme low-texture support module instead of "
            "letting it perturb higher-motion VINS windows."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-min-export-count",
        type=int,
        default=0,
        help=(
            "If positive, drop a final LoFTR sidecar batch when fewer than this "
            "many LoFTR observations survive all gates in the current VINS "
            "feature frame. This prevents tiny LoFTR batches from perturbing "
            "the backend without enough support to improve conditioning."
        ),
    )
    parser.add_argument(
        "--learned-export-loftr-support-cooldown-frames",
        type=int,
        default=0,
        help=(
            "If positive, allow a LoFTR support-rescue batch only once in this "
            "many selected feature frames. Coverage-gain LoFTR sidecars are "
            "not affected. This prevents support rescue from becoming a "
            "continuous learned replacement in ordinary low-grid windows."
        ),
    )
    parser.add_argument(
        "--learned-export-min-classical-motion-px",
        type=float,
        default=0.0,
        help=(
            "Optional median KLT inter-frame motion floor before learned sidecars "
            "may enter VINS. Useful for suppressing low-parallax identity churn."
        ),
    )
    parser.add_argument(
        "--learned-export-min-classical-age",
        type=float,
        default=0.0,
        help=(
            "Optional median KLT track-age floor before learned sidecars may "
            "enter VINS. This protects fragile early VINS initialization."
        ),
    )
    parser.add_argument(
        "--learned-export-geometry-gate",
        action="store_true",
        help="Require accepted learned/recovery sidecars to pass export-level F/E/H residual gates.",
    )
    parser.add_argument(
        "--learned-export-require-confirmed",
        action="store_true",
        help="Require learned/LoFTR sidecar sources to be confirmed/memory tracks before export.",
    )
    parser.add_argument("--learned-export-max-epipolar-error", type=float, default=1.20)
    parser.add_argument("--learned-export-max-essential-error", type=float, default=0.006)
    parser.add_argument("--learned-export-max-homography-error", type=float, default=2.80)
    parser.add_argument("--learned-export-residual-max-ratio", type=float, default=1.05)
    parser.add_argument("--learned-export-residual-max-epipolar-abs", type=float, default=0.03)
    parser.add_argument("--learned-export-residual-max-essential-abs", type=float, default=0.0015)
    parser.add_argument("--learned-export-residual-max-homography-abs", type=float, default=0.12)
    parser.add_argument("--learned-export-geometry-min-reference-tracks", type=int, default=16)
    parser.add_argument(
        "--learned-export-loftr-requires-homography",
        action="store_true",
        help="Require LoFTR sidecars to satisfy the homography residual gate.",
    )
    parser.add_argument(
        "--raw-quality-to-backend",
        action="store_true",
        help="Send the raw frontend q_i to VINS instead of source/age calibrated backend reliability.",
    )
    parser.add_argument(
        "--constant-quality-to-backend",
        action="store_true",
        help="Send q_i=1 and sigma_i=1 for every exported feature as a backend-weighting ablation.",
    )
    parser.add_argument(
        "--backend-quality-mode",
        choices=[
            "default",
            "raw",
            "const",
            "floor",
            "blend",
            "source_aware",
            "vins_safe",
            "sidecar_only",
            "state_adaptive",
        ],
        default=None,
        help=(
            "Backend q_i mapping. Omitted uses config backend_quality.mode or default; "
            "legacy raw/constant flags override this when set."
        ),
    )
    parser.add_argument(
        "--backend-quality-floor",
        type=float,
        default=None,
        help="Optional final minimum backend q_i; floor/source_aware default to 0.8 when omitted.",
    )
    parser.add_argument(
        "--backend-quality-alpha",
        type=float,
        default=None,
        help="Blend alpha for q'=alpha+(1-alpha)q in blend/source_aware/sidecar_only modes.",
    )
    parser.add_argument(
        "--backend-learned-quality-scale",
        type=float,
        default=1.0,
        help=(
            "Optional post-calibration multiplier for learned/semi-dense "
            "sidecar feature q_i before publishing to VINS."
        ),
    )
    parser.add_argument(
        "--backend-sp-lg-quality-scale",
        type=float,
        default=1.0,
        help="Additional q_i multiplier for SuperPoint/LightGlue sidecar features.",
    )
    parser.add_argument(
        "--backend-xfeat-quality-scale",
        type=float,
        default=1.0,
        help="Additional q_i multiplier for XFeat sidecar features.",
    )
    parser.add_argument(
        "--backend-loftr-quality-scale",
        type=float,
        default=1.0,
        help="Additional q_i multiplier for LoFTR sidecar features.",
    )
    parser.add_argument(
        "--backend-learned-quality-const",
        type=float,
        default=None,
        help=(
            "Optional final constant backend q_i for all learned/semi-dense "
            "sidecar features. Source-specific constants below take precedence."
        ),
    )
    parser.add_argument(
        "--backend-sp-lg-quality-const",
        type=float,
        default=None,
        help="Optional final constant backend q_i for SuperPoint/LightGlue sidecar features.",
    )
    parser.add_argument(
        "--backend-xfeat-quality-const",
        type=float,
        default=None,
        help="Optional final constant backend q_i for XFeat sidecar features.",
    )
    parser.add_argument(
        "--backend-xfeat-risk-quality-scheduler",
        action="store_true",
        help=(
            "Use a FR90-like risk scheduler for XFeat q_i: XFeat sidecars "
            "start as soft constraints and remain soft when GFTT/refill risk "
            "is detected."
        ),
    )
    parser.add_argument(
        "--backend-xfeat-risk-quality-const",
        type=float,
        default=0.20,
        help="Backend q_i for XFeat sidecars while the risk scheduler is active.",
    )
    parser.add_argument(
        "--backend-xfeat-risk-probation-quality-const",
        type=float,
        default=None,
        help=(
            "Optional backend q_i for XFeat sidecars during the initial "
            "probation period before GFTT/refill risk latches. If unset, "
            "--backend-xfeat-risk-quality-const is used for the probation "
            "period, preserving the original conservative scheduler."
        ),
    )
    parser.add_argument(
        "--backend-xfeat-risk-probation-quality-requires-low-parallax",
        action="store_true",
        help=(
            "Apply --backend-xfeat-risk-probation-quality-const only while the "
            "formal low-parallax/init-support condition is active; otherwise "
            "probation frames use --backend-xfeat-risk-quality-const."
        ),
    )
    parser.add_argument(
        "--backend-xfeat-risk-probation-learned-frames",
        type=int,
        default=44,
        help="Number of XFeat-export frames kept soft before no-risk promotion.",
    )
    parser.add_argument(
        "--backend-xfeat-risk-latch-gftt-total",
        type=int,
        default=30,
        help="Latch soft XFeat q_i once cumulative GFTT/refill count reaches this value.",
    )
    parser.add_argument(
        "--backend-loftr-quality-const",
        type=float,
        default=None,
        help="Optional final constant backend q_i for LoFTR sidecar features.",
    )
    parser.add_argument(
        "--backend-state-adaptive-hold-frames",
        type=int,
        default=0,
        help=(
            "For backend-quality mode state_adaptive, keep recovery-state "
            "quality scheduling active for this many selected feature frames "
            "after an accepted learned/LoFTR sidecar trigger."
        ),
    )
    parser.add_argument("--zero-velocity", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    args.process_skipped_frames = resolve_process_skipped_frames(
        args.process_skipped_frames,
        cfg,
    )
    quality_gate_source = str(
        cfg.get("quality", {}).get("gate_source", cfg.get("quality_gate_source", "preprocessed"))
    )
    screening_grid_cfg = cfg.get("grid", {})
    screening_grid_rows = int(screening_grid_cfg.get("rows", 4))
    screening_grid_cols = int(screening_grid_cfg.get("cols", 6))
    _apply_formal_three_layer_export_defaults(args)
    if bool(args.learned_export_benefit_all_sources):
        args.learned_export_benefit_loftr_only = False
    backend_quality_mode, backend_quality_floor, backend_quality_alpha = _resolve_backend_quality_args(args, cfg)
    camera = _load_pinhole_camera(Path(args.camera_config))
    tracker = _build_tracker(
        args.method,
        cfg,
        args.semidense_fallback_method,
        camera=camera,
    )
    mirror_backbone_tracker = (
        KltTracker(KltConfig(**cfg.get("klt", {})))
        if (
            args.export_classical_mirror_backbone
            or args.learned_export_online_seed_refill_rejected_with_mirror
            or args.learned_export_online_seed_mirror_only_after_reject
        )
        else None
    )
    sidecar_geometry_cfg = _SidecarGeometryConfig(
        enabled=bool(args.learned_export_geometry_gate),
        require_confirmed_learned=bool(args.learned_export_require_confirmed),
        max_epipolar_error=float(args.learned_export_max_epipolar_error),
        max_essential_error=float(args.learned_export_max_essential_error),
        max_homography_error=float(args.learned_export_max_homography_error),
        residual_max_ratio=float(args.learned_export_residual_max_ratio),
        residual_max_epipolar_abs=float(args.learned_export_residual_max_epipolar_abs),
        residual_max_essential_abs=float(args.learned_export_residual_max_essential_abs),
        residual_max_homography_abs=float(args.learned_export_residual_max_homography_abs),
        min_reference_tracks=int(args.learned_export_geometry_min_reference_tracks),
        loftr_requires_homography=bool(args.learned_export_loftr_requires_homography),
    )
    measurement_selection_cfg = MeasurementSelectionConfig(
        **cfg.get("measurement_selection", {})
    )
    if args.measurement_selection:
        measurement_selection_cfg.enabled = True
    if args.export_max_features is not None:
        measurement_selection_cfg.max_features = int(args.export_max_features)
    if args.measurement_selection_max_features is not None:
        measurement_selection_cfg.max_features = int(args.measurement_selection_max_features)
    if args.measurement_selection_ransac_seed is not None:
        measurement_selection_cfg.ransac_seed = int(args.measurement_selection_ransac_seed)
    if args.measurement_selection_model is not None:
        measurement_selection_cfg.model = str(args.measurement_selection_model)
    if args.measurement_selection_residual_weight is not None:
        measurement_selection_cfg.residual_weight = float(args.measurement_selection_residual_weight)
    if args.measurement_selection_coverage_weight is not None:
        measurement_selection_cfg.coverage_weight = float(args.measurement_selection_coverage_weight)
    if args.measurement_selection_max_per_cell is not None:
        measurement_selection_cfg.max_per_cell = int(args.measurement_selection_max_per_cell)
    if args.measurement_selection_target_cell_count is not None:
        measurement_selection_cfg.target_cell_count = int(args.measurement_selection_target_cell_count)
    if args.export_min_age is not None:
        measurement_selection_cfg.min_age = int(args.export_min_age)
    mirror_measurement_selection_cfg = MeasurementSelectionConfig()
    if args.measurement_selection:
        mirror_measurement_selection_cfg.enabled = True
    if args.export_max_features is not None:
        mirror_measurement_selection_cfg.max_features = int(args.export_max_features)
    if args.export_min_age is not None:
        mirror_measurement_selection_cfg.min_age = int(args.export_min_age)
    bridge = CvBridge()

    init_gate = _resolve_init_parallax_gate(
        args=args,
        cfg=cfg,
        measurement_selection_cfg=measurement_selection_cfg,
    )
    adaptive_warmup_full_mirror = _resolve_adaptive_warmup_full_mirror(
        args=args,
        init_gate=init_gate,
    )
    mirror_selection_policy = _effective_mirror_selection_policy(
        str(args.mirror_measurement_selection_policy),
        adaptive_warmup_full_mirror,
    )

    input_bag = Path(args.bag)
    output_bag = Path(args.output_bag)
    output_bag.parent.mkdir(parents=True, exist_ok=True)
    if args.metrics_csv:
        metrics_path = Path(args.metrics_csv)
        metrics_path.parent.mkdir(parents=True, exist_ok=True)
        metrics_handle = metrics_path.open("w", newline="", encoding="utf-8")
        metrics_writer = csv.DictWriter(
            metrics_handle,
            fieldnames=[
                "frame_index",
                "timestamp",
                "num_features",
                "grid_coverage",
                "dropout_ratio",
                "flat_region_ratio",
                "degradation_score",
                "exported_features",
                "median_track_age",
                "median_quality",
                "median_backend_quality",
                "median_classical_backend_quality",
                "median_learned_backend_quality",
                "recovery_reason",
                "recovered_count",
                "geometry_mode",
                "pairwise_geometry_candidate_count",
                "pairwise_geometry_inlier_count",
                "pairwise_geometry_inlier_ratio",
                "pairwise_geometry_action",
                "pairwise_geometry_reason",
                "learned_candidate_count",
                "learned_confirmed_count",
                "learned_confirmed_xfeat_count",
                "proposer_confirmed_classical_gftt_count",
                "learned_confirmed_age_median",
                "pending_learned_count",
                "pending_learned_age_median",
                "pending_xfeat_count",
                "pending_xfeat_age_median",
                "source_provenance_count",
                "source_provenance_learned_count",
                "source_provenance_xfeat_count",
                "learned_mode",
                "learned_mode_before_sparse_h",
                "learned_mode_after_sparse_h",
                "loftr_sparse_h_allowed",
                "loftr_sparse_h_reason",
                "klt_degeneracy_loftr_allowed",
                "klt_degeneracy_loftr_reason",
                "klt_degeneracy_loftr_score",
                "semidense_acceptance",
                "semidense_raw_candidates",
                "semidense_post_validate_candidates",
                "semidense_accepted_candidates",
                "semidense_queued_pending",
                "semidense_grid_gain",
                "semidense_new_cell_ratio",
                "semidense_before_f_inlier",
                "semidense_after_f_inlier",
                "semidense_before_h_inlier",
                "semidense_after_h_inlier",
                "semidense_before_epipolar",
                "semidense_after_epipolar",
                "semidense_before_homography",
                "semidense_after_homography",
                "pending_loftr_count",
                "pending_loftr_age_median",
                "loftr_confirmed_promoted",
                "exported_learned_features",
                "exported_non_loftr_learned_features",
                "exported_sp_lg_features",
                "exported_xfeat_features",
                "exported_classical_gftt_features",
                "exported_loftr_features",
                "exported_loftr_early_persisted_features",
                "exported_recovered_features",
                "final_mirror_noharm_active",
                "final_mirror_preserve_classical_budget",
                "final_mirror_zero_sidecar_restore",
                "final_mirror_input_sidecars",
                "final_mirror_kept_sidecars",
                "final_mirror_dropped_sidecars_for_cap",
                "final_mirror_dropped_sidecars_for_classical_budget",
                "final_mirror_dropped_classical_for_cap",
                "final_mirror_remapped_sidecar_ids",
                "final_mirror_persistence_replacement_active",
                "final_mirror_persistence_horizon_blocked",
                "final_mirror_persistence_eligible_sidecars",
                "final_mirror_persistence_eligible_gftt",
                "final_mirror_persistence_replaced_gftt",
                "final_mirror_persistence_dropped_sidecars",
                "final_mirror_persistence_single_chain_active",
                "final_mirror_persistence_committed_sidecar_id",
                "final_mirror_persistence_single_chain_suppressed",
                "final_mirror_persistence_churn_guard_active",
                "final_mirror_persistence_churn_guard_decision",
                "final_mirror_persistence_churn_guard_decision_frame",
                "final_mirror_persistence_churn_guard_gftt_births",
                "final_mirror_persistence_churn_guard_denominator",
                "final_mirror_persistence_churn_guard_ratio",
                "final_mirror_persistence_source_router_active",
                "final_mirror_persistence_source_eligible_sidecars",
                "final_mirror_persistence_source_suppressed",
                "final_mirror_persistence_same_cell_active",
                "final_mirror_persistence_same_cell_suppressed",
                "final_mirror_persistence_coverage_monotone_active",
                "final_mirror_persistence_coverage_monotone_suppressed",
                "final_mirror_persistence_grid_cells_before",
                "final_mirror_persistence_grid_cells_after",
                "final_mirror_persistence_grid_cell_delta",
                "final_mirror_persistence_cross_cell_replacements",
                "final_mirror_persistence_donor_cell_min_remaining",
                "final_mirror_persistence_per_frame_cap",
                "final_mirror_persistence_per_frame_cap_suppressed",
                "final_mirror_persistence_replaced_gftt_max_age",
                "final_mirror_persistence_replacement_min_age_advantage_actual",
                "final_mirror_persistence_replacement_cell_mismatches",
                "final_mirror_prefill_slot_active",
                "final_mirror_prefill_slot_horizon_blocked",
                "final_mirror_prefill_slot_carried_observations",
                "final_mirror_prefill_slot_baseline_newborns",
                "final_mirror_prefill_slot_vacant_capacity",
                "final_mirror_prefill_slot_eligible_sidecars",
                "final_mirror_prefill_slot_admitted_sidecars",
                "final_mirror_prefill_slot_omitted_newborns",
                "final_mirror_prefill_slot_dropped_sidecars",
                "final_mirror_prefill_slot_source_suppressed",
                "final_mirror_prefill_slot_age_suppressed",
                "final_mirror_prefill_slot_per_frame_cap",
                "exported_learned_median_age",
                "exported_non_loftr_learned_median_age",
                "exported_xfeat_median_age",
                "exported_loftr_median_age",
                "exported_learned_age_lt3",
                "exported_xfeat_age_lt3",
                "exported_loftr_age_lt3",
                "exported_learned_median_visible_streak",
                "exported_xfeat_median_visible_streak",
                "exported_loftr_median_visible_streak",
                "exported_learned_median_motion_px",
                "exported_xfeat_median_motion_px",
                "exported_loftr_median_motion_px",
                "pre_gate_sidecar_total",
                "pre_gate_sidecar_confirmed",
                "pre_gate_sidecar_age_ok",
                "pre_gate_sidecar_quality_ok",
                "pre_gate_sidecar_ncc_ok",
                "pre_gate_sidecar_fb_ok",
                "pre_gate_sidecar_basic_ok",
                "pre_gate_loftr_total",
                "pre_gate_loftr_basic_ok",
                "pre_gate_non_loftr_total",
                "pre_gate_non_loftr_basic_ok",
                "source_selection_dropped",
                "selected_feature_index",
                "published_feature_frame",
                "init_parallax_gate_triggered",
                "init_parallax_mean_step_px",
                "init_parallax_skipped_feature",
                "init_klt_only_active",
                "adaptive_warmup_full_mirror_enabled",
                "adaptive_warmup_full_mirror_reason",
                "low_parallax_learned_holdoff_active",
                "state_adaptive_q_triggered",
                "state_adaptive_q_active",
                "backend_xfeat_risk_q_active",
                "backend_xfeat_quality_const_effective",
                "backend_xfeat_risk_learned_frames",
                "backend_xfeat_risk_cumulative_gftt",
                "learned_export_gate_active",
                "learned_export_gate_degraded",
                "learned_export_gate_reason",
                "learned_export_loftr_min_quality",
                "learned_export_loftr_min_age",
                "learned_export_loftr_min_ncc",
                "learned_export_loftr_max_fb",
                "export_classical_mirror_backbone",
                "classical_track_count",
                "classical_grid_coverage",
                "learned_export_gate_dropped",
                "learned_export_geometry_dropped",
                "learned_export_geometry_reason",
                "learned_export_benefit_dropped",
                        "learned_export_benefit_reason",
                        "learned_export_temporal_dropped",
                        "learned_export_temporal_reason",
                        "learned_export_temporal_recent_frames",
                        "learned_export_health_suppression_dropped",
                        "learned_export_health_suppression_reason",
                        "learned_export_recent_healthy_frames",
                        "learned_export_recovery_reason_suppression_dropped",
                        "learned_export_recovery_reason_suppression_reason",
                        "learned_export_recovery_burst_suppression_dropped",
                        "learned_export_recovery_burst_suppression_reason",
                        "learned_export_recovery_burst_recent_frames",
                        "learned_export_grid_gain",
                "learned_export_new_cells",
                "learned_export_new_cell_ratio",
                        "learned_export_weak_cells",
                        "classical_motion_px",
                        "classical_median_age",
                        "tracker_source_histogram",
                        "export_source_histogram",
                    ],
        )
        metrics_writer.writeheader()
    else:
        metrics_handle = None
        metrics_writer = None

    copy_topics = list(dict.fromkeys(args.copy_topic))
    read_topics = list(dict.fromkeys([args.image_topic] + copy_topics))
    emitted = 0
    selected_feature_index = 0
    seen_images = 0
    previous_screening_track_ids: set[int] = set()
    prev_stamp: float | None = None
    prev_feature_stamp_for_velocity: float | None = None
    start_time: float | None = None
    skipped_invalid_header = 0
    export_id_state = _ExportIdState()
    final_mirror_sidecar_id_state = _ExportIdState()
    learned_sidecar_observations_used = 0
    online_seed_sidecar_observations_used = 0
    online_seed_lineage_observations_used = 0
    state_adaptive_quality_hold_until = 0
    vins_safe_low_cap_hold_until = -1
    temporal_sidecar_gate_state = _TemporalSidecarGateState(accepted_frames=[])
    visible_sidecar_track_gate_state = _VisibleSidecarTrackGateState(
        last_frame={},
        streak={},
        last_point={},
        path_length_px={},
        step_count={},
    )
    fresh_sidecar_confirmation_gate_state = _FreshSidecarConfirmationGateState(
        confirmed_until={},
    )
    online_seed_fresh_gate_state = _FreshSidecarConfirmationGateState(
        confirmed_until={},
    )
    online_seed_fresh_frame_gate_state = _OnlineSeedFreshFrameGateState()
    online_seed_microburst_gate_state = _OnlineSeedMicroburstGateState()
    recent_classical_health_gate_state = _RecentClassicalHealthGateState(
        healthy_frames=[],
    )
    stale_healthy_unconfirmed_gate_state = _StaleHealthyUnconfirmedGateState(
        matched_frames=[],
    )
    short_low_grid_seed_gate_state = _ShortLowGridSeedGateState()
    recovery_reason_burst_gate_state = _RecoveryReasonBurstGateState(
        matched_frames=[],
    )
    motion_adaptive_mirror_refill_state = _MotionAdaptiveMirrorRefillState()
    coverage_seeded_continuation_gate_state = _CoverageSeededContinuationGateState(
        seeded_ids=set(),
    )
    loftr_seeded_continuation_gate_state = _LoFTRSeededContinuationGateState(
        last_accepted_frame={},
    )
    loftr_early_persistence_state = _LoFTREarlyPersistenceState(packets=[])
    xfeat_risk_quality_state = _XFeatRiskQualitySchedulerState()

    with rosbag.Bag(str(input_bag), "r") as in_bag, rosbag.Bag(str(output_bag), "w") as out_bag:
        bag_start = in_bag.get_start_time()
        window_start = bag_start + max(0.0, args.start_offset)
        window_end = None if args.duration is None else window_start + max(0.0, args.duration)
        for topic, msg, stamp in in_bag.read_messages(topics=read_topics):
            t = stamp.to_sec()
            if t < window_start:
                continue
            if window_end is not None and t > window_end:
                break
            if topic != args.image_topic:
                out_bag.write(topic, msg, stamp)
                continue

            raw_index = seen_images
            seen_images += 1
            every_n = max(1, args.every_n)
            should_publish = raw_index % every_n == (args.frame_offset % every_n)
            if args.max_frames is not None and emitted >= args.max_frames:
                continue
            feature_stamp, invalid_header = _select_feature_stamp(
                msg,
                stamp,
                source=args.timestamp_source,
                max_header_delta=args.max_header_stamp_delta,
                invalid_policy=args.invalid_header_policy,
            )
            if invalid_header and args.invalid_header_policy == "skip":
                skipped_invalid_header += 1
                continue
            if not should_publish and not args.process_skipped_frames:
                continue

            raw_gray = _image_msg_to_gray(bridge, msg)
            raw_quality = score_image_quality(raw_gray)
            gray = _preprocess_gray(raw_gray, args.preprocess)
            processed_quality = score_image_quality(gray)
            quality = fuse_image_quality_for_gates(
                processed_quality,
                raw_quality,
                quality_gate_source,
            )
            tracks, _diagnostics = tracker.process(gray, quality)
            mirror_tracks = (
                mirror_backbone_tracker.process(gray, quality)[0]
                if mirror_backbone_tracker is not None
                else None
            )
            if not should_publish:
                continue
            candidate_tracks = tracks
            if int(args.export_min_learned_age) > 0:
                candidate_tracks = _filter_young_learned_tracks(
                    candidate_tracks,
                    min_age=int(args.export_min_learned_age),
                )
            init_klt_only_active = selected_feature_index < max(0, int(args.vins_init_klt_only_frames))
            low_parallax_holdoff_until = _low_parallax_learned_holdoff_until(args, init_gate)
            low_parallax_learned_holdoff_active = bool(
                init_gate.triggered
                and selected_feature_index < low_parallax_holdoff_until
            )
            init_loftr_rescue_active = bool(
                args.init_loftr_sidecar_rescue
                and init_klt_only_active
                and not init_gate.triggered
                and selected_feature_index >= max(0, int(init_gate.skip_feature_frames))
            )
            select_cfg = measurement_selection_cfg
            if bool(args.formal_three_layer_export) and init_klt_only_active:
                select_cfg = replace(measurement_selection_cfg, enabled=False)
            if (
                int(args.selection_warmup_frames) > 0
                and selected_feature_index < int(args.selection_warmup_frames)
            ):
                select_cfg = replace(measurement_selection_cfg, enabled=False)
            adaptive_mirror_fallback = bool(
                args.formal_three_layer_export
                and args.formal_export_adaptive_mirror_fallback
                and mirror_tracks is not None
                and args.learned_export_degradation_gate
            )
            sparse_probe_tracks: TrackSet | None = None
            mirror_export_tracks: TrackSet | None = None
            if mirror_tracks is not None:
                mirror_candidate_tracks = mirror_tracks
                if int(args.export_min_learned_age) > 0:
                    mirror_candidate_tracks = _filter_young_learned_tracks(
                        mirror_candidate_tracks,
                        min_age=int(args.export_min_learned_age),
                    )
                mirror_export_tracks = select_backend_measurements(
                    mirror_candidate_tracks,
                    gray.shape,
                    _mirror_selection_config(
                        policy=mirror_selection_policy,
                        active_cfg=select_cfg,
                        baseline_cfg=mirror_measurement_selection_cfg,
                        warmup_active=bool(init_klt_only_active),
                    ),
                    geometry_mode="klt_mirror",
                )
            if mirror_tracks is not None and bool(args.export_classical_mirror_backbone):
                export_tracks = mirror_export_tracks if mirror_export_tracks is not None else TrackSet.empty()
                if adaptive_mirror_fallback:
                    should_probe_sidecars = bool(
                        _has_sidecar_source(candidate_tracks)
                        and (
                            bool(select_cfg.enabled)
                            or bool(init_loftr_rescue_active)
                            or bool(args.formal_export_low_texture_active_sidecar)
                            or bool(args.preserve_sidecars_through_selection)
                        )
                    )
                    if should_probe_sidecars:
                        classical_tracks = _select_classical_backbone_sources(candidate_tracks)
                        sparse_probe_tracks = select_backend_measurements(
                            classical_tracks,
                            gray.shape,
                            select_cfg,
                            geometry_mode=getattr(tracker, "last_geometry_mode", "unknown"),
                        )
                        sidecar_tracks = _select_sidecar_sources(candidate_tracks)
                        if len(sidecar_tracks):
                            sparse_probe_tracks = _append_tracksets(sparse_probe_tracks, sidecar_tracks)
                    else:
                        sparse_probe_tracks = export_tracks
                else:
                    sidecar_tracks = _select_sidecar_sources(candidate_tracks)
                    if len(sidecar_tracks):
                        export_tracks = _append_tracksets(export_tracks, sidecar_tracks)
            else:
                if (
                    (
                        bool(args.formal_three_layer_export)
                        or bool(args.preserve_sidecars_through_selection)
                    )
                    and bool(args.learned_export_degradation_gate)
                    and bool(select_cfg.enabled)
                    and _has_sidecar_source(candidate_tracks)
                ):
                    # Learned/LoFTR observations are not allowed to bypass the
                    # degradation/geometry/coverage gates. Measurement selection
                    # should sparsify the KLT backbone, but it must not silently
                    # discard sidecar candidates before those gates can evaluate
                    # them.
                    classical_tracks = _select_classical_backbone_sources(candidate_tracks)
                    export_tracks = select_backend_measurements(
                        classical_tracks,
                        gray.shape,
                        select_cfg,
                        geometry_mode=getattr(tracker, "last_geometry_mode", "unknown"),
                    )
                    sidecar_tracks = _select_sidecar_sources(candidate_tracks)
                    if len(sidecar_tracks):
                        export_tracks = _append_tracksets(export_tracks, sidecar_tracks)
                else:
                    export_tracks = select_backend_measurements(
                        candidate_tracks,
                        gray.shape,
                        select_cfg,
                        geometry_mode=getattr(tracker, "last_geometry_mode", "unknown"),
                    )
            if init_klt_only_active:
                if init_loftr_rescue_active:
                    export_tracks = _select_classical_and_confirmed_loftr_sources(export_tracks)
                else:
                    export_tracks = _select_classical_backbone_sources(export_tracks)
            before_source_selection = len(export_tracks)
            defer_vins_safe_selection = bool(args.learned_export_degradation_gate)
            if args.vins_safe_source_selection and not defer_vins_safe_selection:
                max_total = args.vins_safe_max_total
                if max_total is None:
                    max_total = (
                        int(args.export_max_features)
                        if args.export_max_features is not None
                        else before_source_selection
                    )
                warmup_frames = _effective_vins_safe_warmup_frames(
                    args,
                    init_gate,
                    low_parallax_holdoff_until=low_parallax_holdoff_until,
                )
                low_cap_context = _vins_safe_low_cap_context(tracker, export_tracks)
                if low_cap_context and int(args.vins_safe_low_cap_hold_frames) > 0:
                    vins_safe_low_cap_hold_until = max(
                        int(vins_safe_low_cap_hold_until),
                        int(selected_feature_index) + int(args.vins_safe_low_cap_hold_frames),
                    )
                force_low_cap = low_cap_context or (
                    int(selected_feature_index) <= int(vins_safe_low_cap_hold_until)
                )
                export_tracks = _select_vins_safe_sources(
                    export_tracks,
                    emitted_frame_index=selected_feature_index,
                    image_shape=gray.shape,
                    warmup_frames=warmup_frames,
                    max_total=int(max_total),
                    max_learned=int(args.vins_safe_max_learned),
                    max_recovered=int(args.vins_safe_max_recovered),
                    min_learned_age=int(args.vins_safe_min_learned_age),
                    preserve_classical_budget=bool(
                        args.vins_safe_preserve_classical_budget
                    ),
                    classical_prefer_age=not bool(args.vins_safe_classical_prefer_quality),
                    classical_prefer_klt=bool(args.vins_safe_classical_prefer_klt),
                    exact_cap_selection=bool(args.vins_safe_exact_cap_selection),
                    sidecar_low_cap_total=args.vins_safe_sidecar_low_cap_total,
                    force_low_cap=force_low_cap,
                    allow_warmup_confirmed_loftr=False,
                    warmup_confirmed_loftr_max_count=0,
                    init_sidecar_support_selection=bool(
                        args.vins_safe_init_sidecar_support_selection
                    ),
                    init_sidecar_support_count=int(
                        args.vins_safe_init_sidecar_support_count
                    ),
                    init_sidecar_selection_quality_floor=float(
                        args.vins_safe_init_sidecar_classical_quality_floor
                    ),
                )
            pre_gate_export_tracks = export_tracks
            learned_gate_info = _LearnedExportGateInfo.disabled(export_tracks, gray.shape)
            if args.learned_export_degradation_gate:
                gate_params = _gate_params_from_args(
                    args,
                    init_klt_only_active=init_klt_only_active,
                    init_parallax_mean_step_px=init_gate.mean_step_px,
                )
                if adaptive_mirror_fallback and sparse_probe_tracks is not None and mirror_export_tracks is not None:
                    pre_gate_export_tracks = sparse_probe_tracks
                    sparse_export_tracks, learned_gate_info = _apply_learned_export_gate_from_params(
                        sparse_probe_tracks,
                        image_shape=gray.shape,
                        tracker_recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                        tracker_learned_mode=getattr(tracker, "last_learned_mode", "n/a"),
                        camera=camera,
                        geometry_cfg=sidecar_geometry_cfg,
                        params=gate_params,
                        loftr_continuation_state=(
                            loftr_seeded_continuation_gate_state
                            if bool(args.learned_export_loftr_seeded_continuation_gate)
                            else None
                        ),
                        frame_index=int(selected_feature_index),
                        loftr_continuation_max_gap=int(
                            args.learned_export_loftr_seeded_continuation_max_gap
                        ),
                    )
                    sidecar_tracks = TrackSet.empty()
                    if _has_sidecar_source(sparse_export_tracks):
                        sidecar_tracks = _select_sidecar_sources(sparse_export_tracks)
                        sidecar_tracks, learned_gate_info = _drop_loftr_if_final_classical_support_high(
                            sidecar_tracks,
                            learned_gate_info,
                            # Use the pre-mirror probe as the support reference.
                            # The mirror fallback may refill to a full KLT/GFTT
                            # budget even when the actual low-texture backbone
                            # that triggered LoFTR is sparse and poorly covered.
                            final_classical_tracks=sparse_probe_tracks,
                            max_classical_tracks=int(
                                args.learned_export_loftr_rescue_max_classical_tracks
                            ),
                        )
                        if bool(args.learned_export_final_mirror_health_suppression):
                            sidecar_tracks, learned_gate_info = _apply_final_mirror_health_suppression(
                                sidecar_tracks,
                                learned_gate_info,
                                mirror_tracks=mirror_export_tracks,
                                image_shape=gray.shape,
                                min_tracks=int(args.learned_export_final_mirror_health_min_tracks),
                                min_grid=float(args.learned_export_final_mirror_health_min_grid),
                                min_age=float(args.learned_export_final_mirror_health_min_age),
                            )
                    if len(sidecar_tracks):
                        export_tracks = _append_tracksets(mirror_export_tracks, sidecar_tracks)
                    else:
                        export_tracks = mirror_export_tracks
                        learned_gate_info = replace(
                            learned_gate_info,
                            benefit_reason=(
                                learned_gate_info.benefit_reason
                                if learned_gate_info.benefit_reason not in {"disabled", "not_run"}
                                else "adaptive_mirror_fallback"
                            ),
                        )
                else:
                    export_tracks, learned_gate_info = _apply_learned_export_gate_from_params(
                        export_tracks,
                        image_shape=gray.shape,
                        tracker_recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                        tracker_learned_mode=getattr(tracker, "last_learned_mode", "n/a"),
                        camera=camera,
                        geometry_cfg=sidecar_geometry_cfg,
                        params=gate_params,
                        loftr_continuation_state=(
                            loftr_seeded_continuation_gate_state
                            if bool(args.learned_export_loftr_seeded_continuation_gate)
                            else None
                        ),
                        frame_index=int(selected_feature_index),
                        loftr_continuation_max_gap=int(
                            args.learned_export_loftr_seeded_continuation_max_gap
                        ),
                    )
            low_parallax_sidecar_block_active = bool(
                args.formal_three_layer_export
                and init_gate.triggered
                and not bool(args.formal_export_allow_low_parallax_sidecars)
            )
            if low_parallax_sidecar_block_active and _has_sidecar_source(export_tracks):
                before_low_parallax_block = len(export_tracks)
                export_tracks = _select_classical_backbone_sources(export_tracks)
                learned_gate_info = replace(
                    learned_gate_info,
                    dropped_learned=learned_gate_info.dropped_learned
                    + max(0, before_low_parallax_block - len(export_tracks)),
                    benefit_reason="low_parallax_sidecar_block",
                )
            if bool(args.learned_export_suppress_non_loftr_recovery_reason):
                before_recovery_suppression = (
                    learned_gate_info.recovery_reason_suppression_dropped
                )
                export_tracks, learned_gate_info = _apply_recovery_reason_suppression(
                    export_tracks,
                    learned_gate_info,
                    recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                    tokens=str(args.learned_export_suppress_recovery_reason_tokens),
                )
                if bool(args.learned_export_recovery_suppression_consumes_budget):
                    learned_sidecar_observations_used += max(
                        0,
                        int(learned_gate_info.recovery_reason_suppression_dropped)
                        - int(before_recovery_suppression),
                    )
            if bool(args.learned_export_recovery_burst_suppression):
                recovery_burst_recent_frames = recovery_reason_burst_gate_state.update(
                    selected_feature_index,
                    recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                    tokens=str(args.learned_export_recovery_burst_tokens),
                    window=int(args.learned_export_recovery_burst_window),
                )
                export_tracks, learned_gate_info = _apply_recovery_reason_burst_suppression(
                    export_tracks,
                    learned_gate_info,
                    recent_matched_frames=recovery_burst_recent_frames,
                    min_matched_frames=int(args.learned_export_recovery_burst_min_frames),
                )
            if bool(args.learned_export_short_lowgrid_seed_suppression):
                before_short_lowgrid_suppression = int(
                    learned_gate_info.health_suppression_dropped
                )
                export_tracks, learned_gate_info = _apply_short_low_grid_seed_suppression(
                    export_tracks,
                    learned_gate_info,
                    state=short_low_grid_seed_gate_state,
                    frame_index=selected_feature_index,
                    recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                    min_low_grid_seed_frames=int(
                        args.learned_export_short_lowgrid_seed_min_frames
                    ),
                    max_gap=int(args.learned_export_short_lowgrid_seed_max_gap),
                    max_low_grid_frames=int(
                        args.learned_export_short_lowgrid_seed_max_lowgrid_frames
                    ),
                    seed_window_gate=bool(args.learned_export_lowgrid_seed_window_gate),
                    early_max_start_frame=int(
                        args.learned_export_lowgrid_seed_early_max_start_frame
                    ),
                    early_min_seed=int(args.learned_export_lowgrid_seed_early_min_frame),
                    early_max_seed=int(args.learned_export_lowgrid_seed_early_max_frame),
                    late_min_seed=int(args.learned_export_lowgrid_seed_late_min_frame),
                    late_max_seed=int(args.learned_export_lowgrid_seed_late_max_frame),
                )
                if (
                    bool(args.learned_export_short_lowgrid_long_tail_consumes_budget)
                    and str(learned_gate_info.health_suppression_reason).startswith(
                        "suppressed_long_lowgrid_burst:"
                    )
                ):
                    learned_sidecar_observations_used += max(
                        0,
                        int(learned_gate_info.health_suppression_dropped)
                        - before_short_lowgrid_suppression,
                    )
                if (
                    bool(args.learned_export_lowgrid_seed_window_consumes_budget)
                    and str(learned_gate_info.health_suppression_reason).startswith(
                        "suppressed_lowgrid_seed_window_"
                    )
                ):
                    learned_sidecar_observations_used += max(
                        0,
                        int(learned_gate_info.health_suppression_dropped)
                        - before_short_lowgrid_suppression,
                    )
            if bool(args.learned_export_stale_healthy_unconfirmed_suppression):
                export_tracks, learned_gate_info = _apply_stale_healthy_unconfirmed_suppression(
                    export_tracks,
                    learned_gate_info,
                    state=stale_healthy_unconfirmed_gate_state,
                    frame_index=selected_feature_index,
                    recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                    learned_confirmed_count=int(
                        getattr(tracker, "last_learned_confirmed_count", 0) or 0
                    ),
                    sidecar_observations_used=int(learned_sidecar_observations_used),
                    window=int(args.learned_export_stale_healthy_window),
                    min_matched_frames=int(args.learned_export_stale_healthy_min_frames),
                    min_classical_tracks=int(
                        args.learned_export_stale_healthy_min_classical_tracks
                    ),
                    min_classical_grid=float(
                        args.learned_export_stale_healthy_min_classical_grid
                    ),
                    min_classical_age=float(
                        args.learned_export_stale_healthy_min_classical_age
                    ),
                    max_used_observations=int(
                        args.learned_export_stale_healthy_max_used_observations
                    ),
                )
            if bool(args.learned_export_recent_health_suppression):
                health_reference_tracks = (
                    mirror_export_tracks
                    if mirror_export_tracks is not None
                    else _select_classical_backbone_sources(export_tracks)
                )
                recent_healthy_frames = recent_classical_health_gate_state.update(
                    selected_feature_index,
                    healthy=_classical_tracks_are_healthy(
                        health_reference_tracks,
                        gray.shape,
                        min_tracks=int(args.learned_export_recent_health_min_tracks),
                        min_grid=float(args.learned_export_recent_health_min_grid),
                        min_age=float(args.learned_export_recent_health_min_age),
                    ),
                    window=int(args.learned_export_recent_health_window),
                )
                export_tracks, learned_gate_info = _apply_recent_classical_health_suppression(
                    export_tracks,
                    learned_gate_info,
                    recent_healthy_frames=recent_healthy_frames,
                    min_healthy_frames=int(args.learned_export_recent_health_min_frames),
                )
            if args.vins_safe_source_selection and defer_vins_safe_selection:
                max_total = args.vins_safe_max_total
                if max_total is None:
                    max_total = (
                        int(args.export_max_features)
                        if args.export_max_features is not None
                        else before_source_selection
                    )
                warmup_frames = _effective_vins_safe_warmup_frames(
                    args,
                    init_gate,
                    low_parallax_holdoff_until=low_parallax_holdoff_until,
                )
                low_cap_context = _vins_safe_low_cap_context(tracker, export_tracks)
                if low_cap_context and int(args.vins_safe_low_cap_hold_frames) > 0:
                    vins_safe_low_cap_hold_until = max(
                        int(vins_safe_low_cap_hold_until),
                        int(selected_feature_index) + int(args.vins_safe_low_cap_hold_frames),
                    )
                force_low_cap = low_cap_context or (
                    int(selected_feature_index) <= int(vins_safe_low_cap_hold_until)
                )
                export_tracks = _select_vins_safe_sources(
                    export_tracks,
                    emitted_frame_index=selected_feature_index,
                    image_shape=gray.shape,
                    warmup_frames=warmup_frames,
                    max_total=int(max_total),
                    max_learned=int(args.vins_safe_max_learned),
                    max_recovered=int(args.vins_safe_max_recovered),
                    min_learned_age=int(args.vins_safe_min_learned_age),
                    preserve_classical_budget=bool(
                        args.vins_safe_preserve_classical_budget
                    ),
                    classical_prefer_age=not bool(args.vins_safe_classical_prefer_quality),
                    classical_prefer_klt=bool(args.vins_safe_classical_prefer_klt),
                    exact_cap_selection=bool(args.vins_safe_exact_cap_selection),
                    sidecar_low_cap_total=args.vins_safe_sidecar_low_cap_total,
                    force_low_cap=force_low_cap,
                    allow_warmup_confirmed_loftr=bool(init_loftr_rescue_active),
                    warmup_confirmed_loftr_max_count=int(args.init_loftr_sidecar_max_count),
                    init_sidecar_support_selection=bool(
                        args.vins_safe_init_sidecar_support_selection
                    ),
                    init_sidecar_support_count=int(
                        args.vins_safe_init_sidecar_support_count
                    ),
                    init_sidecar_selection_quality_floor=float(
                        args.vins_safe_init_sidecar_classical_quality_floor
                    ),
                )
            mirror_refill_target_count = len(export_tracks)
            if (
                adaptive_mirror_fallback
                and mirror_export_tracks is not None
                and bool(args.vins_safe_preserve_classical_budget)
            ):
                mirror_refill_target_count = max(
                    int(mirror_refill_target_count),
                    int(len(mirror_export_tracks)),
                )
            remapped_before_visible_gate = False
            if (
                args.reset_recovered_export_ids
                and bool(args.learned_export_loftr_source_memory)
                and bool(args.learned_export_visible_track_gate)
            ):
                export_tracks = _remap_recovered_export_ids(
                    export_tracks,
                    export_id_state,
                    loftr_source_memory=bool(args.learned_export_loftr_source_memory),
                )
                remapped_before_visible_gate = True
            if bool(args.learned_export_visible_track_gate):
                visible_sidecar_track_gate_state.update(
                    export_tracks,
                    frame_index=selected_feature_index,
                    max_gap=int(args.learned_export_visible_track_max_gap),
                )
            if bool(args.learned_export_temporal_burst_gate):
                export_tracks, learned_gate_info = _apply_temporal_sidecar_burst_gate(
                    export_tracks,
                    learned_gate_info,
                    state=temporal_sidecar_gate_state,
                    frame_index=selected_feature_index,
                    window=int(args.learned_export_burst_window),
                    min_recent_frames=int(args.learned_export_burst_min_recent_frames),
                    late_start_frame=int(args.learned_export_burst_late_start_frame),
                    min_sidecars=int(args.learned_export_burst_min_sidecars),
                    allow_postinit_loftr_support=bool(
                        args.learned_export_allow_postinit_loftr_support
                        and (
                            not init_gate.triggered
                            or bool(args.formal_export_allow_low_parallax_sidecars)
                        )
                    ),
                    allow_early_loftr_support=bool(
                        args.learned_export_allow_early_loftr_support
                        and (
                            not init_gate.triggered
                            or bool(args.formal_export_allow_low_parallax_sidecars)
                        )
                    ),
                    loftr_support_holdoff_until=int(low_parallax_holdoff_until),
                    allow_isolated_non_loftr_sidecars=bool(
                        args.learned_export_allow_isolated_non_loftr_sidecars
                    ),
                    isolated_non_loftr_max_count=int(
                        args.learned_export_isolated_non_loftr_max_count
                    ),
                )
            if bool(args.learned_export_visible_track_gate):
                export_tracks, learned_gate_info = _apply_visible_sidecar_track_gate(
                    export_tracks,
                    learned_gate_info,
                    state=visible_sidecar_track_gate_state,
                    min_frames=int(args.learned_export_visible_track_min_frames),
                )
            if bool(args.learned_export_require_fresh_non_loftr_confirmation):
                export_tracks, learned_gate_info = _apply_fresh_non_loftr_confirmation_gate(
                    export_tracks,
                    learned_gate_info,
                    state=fresh_sidecar_confirmation_gate_state,
                    frame_index=selected_feature_index,
                    fresh_confirmed_count=int(
                        getattr(tracker, "last_learned_confirmed_count", 0)
                    ),
                    hold_frames=int(args.learned_export_fresh_confirmation_hold_frames),
                )
            if int(args.learned_export_loftr_min_export_count) > 0:
                export_tracks, learned_gate_info = _apply_loftr_min_export_count(
                    export_tracks,
                    learned_gate_info,
                    min_export_count=int(args.learned_export_loftr_min_export_count),
                )
            if int(args.learned_export_loftr_support_cooldown_frames) > 0:
                export_tracks, learned_gate_info = _apply_loftr_support_cooldown_gate(
                    export_tracks,
                    learned_gate_info,
                    state=temporal_sidecar_gate_state,
                    frame_index=selected_feature_index,
                    cooldown_frames=int(
                        args.learned_export_loftr_support_cooldown_frames
                    ),
                )
            if bool(args.learned_export_online_seed_gate):
                online_seed_pre_gate_count = len(export_tracks)
                (
                    export_tracks,
                    learned_gate_info,
                    online_seed_sidecar_observations_used,
                    online_seed_lineage_observations_used,
                ) = (
                    _apply_online_seed_sidecar_gate(
                        export_tracks,
                        learned_gate_info,
                        frame_index=selected_feature_index,
                        tracker_learned_mode=getattr(tracker, "last_geometry_mode", "n/a"),
                        target_sources=str(args.learned_export_online_seed_sources),
                        warmup_frames=int(args.learned_export_online_seed_warmup_frames),
                        max_observations=int(args.learned_export_online_seed_max_observations),
                        used_observations=int(online_seed_sidecar_observations_used),
                        max_per_frame=int(args.learned_export_online_seed_max_per_frame),
                        min_age=int(args.learned_export_online_seed_min_age),
                        min_quality=float(args.learned_export_online_seed_min_quality),
                        min_ncc=float(args.learned_export_online_seed_min_ncc),
                        max_fb=float(args.learned_export_online_seed_max_fb),
                        require_confirmed=bool(
                            args.learned_export_online_seed_require_confirmed
                        ),
                        require_fresh=bool(
                            args.learned_export_online_seed_require_fresh
                        ),
                        fresh_confirmed_count=int(
                            getattr(tracker, "last_learned_confirmed_count", 0)
                        ),
                        fresh_scope=str(args.learned_export_online_seed_fresh_scope),
                        fresh_hold_frames=int(
                            args.learned_export_online_seed_fresh_hold_frames
                        ),
                        fresh_state=online_seed_fresh_gate_state,
                        fresh_frame_state=online_seed_fresh_frame_gate_state,
                        microburst_gate=bool(
                            args.learned_export_online_seed_microburst_gate
                        ),
                        microburst_frames=int(
                            args.learned_export_online_seed_microburst_frames
                        ),
                        microburst_extend_frames=int(
                            args.learned_export_online_seed_microburst_extend_frames
                        ),
                        microburst_extend_min_initial_observations=int(
                            args.learned_export_online_seed_microburst_extend_min_initial_observations
                        ),
                        microburst_extend_min_initial_cells=int(
                            args.learned_export_online_seed_microburst_extend_min_initial_cells
                        ),
                        microburst_extend_min_bbox_area_ratio=float(
                            args.learned_export_online_seed_microburst_extend_min_bbox_area_ratio
                        ),
                        microburst_extend_grid_rows=int(
                            args.learned_export_online_seed_microburst_extend_grid_rows
                        ),
                        microburst_extend_grid_cols=int(
                            args.learned_export_online_seed_microburst_extend_grid_cols
                        ),
                        microburst_max_restarts=int(
                            args.learned_export_online_seed_microburst_max_restarts
                        ),
                        microburst_restart_cooldown_frames=int(
                            args.learned_export_online_seed_microburst_restart_cooldown_frames
                        ),
                        lineage_continuation=bool(
                            args.learned_export_online_seed_lineage_continuation
                        ),
                        lineage_min_age=int(
                            args.learned_export_online_seed_lineage_min_age
                        ),
                        lineage_max_per_frame=int(
                            args.learned_export_online_seed_lineage_max_per_frame
                        ),
                        lineage_max_observations=int(
                            args.learned_export_online_seed_lineage_max_observations
                        ),
                        lineage_used_observations=int(
                            online_seed_lineage_observations_used
                        ),
                        lineage_separate_budget=bool(
                            args.learned_export_online_seed_lineage_separate_budget
                        ),
                        dense_start_max_observations=int(
                            args.learned_export_online_seed_dense_start_max_observations
                        ),
                        dense_start_min_classical_tracks=int(
                            args.learned_export_online_seed_dense_start_min_classical_tracks
                        ),
                        dense_start_min_classical_grid=float(
                            args.learned_export_online_seed_dense_start_min_classical_grid
                        ),
                        dense_start_min_frame_candidates=int(
                            args.learned_export_online_seed_dense_start_min_frame_candidates
                        ),
                        sparse_start_min_frame_candidates=int(
                            args.learned_export_online_seed_sparse_start_min_frame_candidates
                        ),
                        sparse_start_min_classical_tracks=int(
                            args.learned_export_online_seed_sparse_start_min_classical_tracks
                        ),
                        sparse_start_min_classical_grid=float(
                            args.learned_export_online_seed_sparse_start_min_classical_grid
                        ),
                        start_min_classical_grid=float(
                            args.learned_export_online_seed_start_min_classical_grid
                        ),
                        start_min_classical_grid_tracks=int(
                            args.learned_export_online_seed_start_min_classical_grid_tracks
                        ),
                        max_start_classical_gftt_ratio=float(
                            args.learned_export_online_seed_max_start_classical_gftt_ratio
                        ),
                        start_gftt_ratio_min_classical_tracks=int(
                            args.learned_export_online_seed_start_gftt_ratio_min_classical_tracks
                        ),
                        start_gftt_ratio_min_classical_grid=float(
                            args.learned_export_online_seed_start_gftt_ratio_min_classical_grid
                        ),
                        normal_start_max_motion_px=float(
                            args.learned_export_online_seed_normal_start_max_motion_px
                        ),
                        normal_start_min_frame_candidates=int(
                            args.learned_export_online_seed_normal_start_min_frame_candidates
                        ),
                        normal_start_max_frame_candidates=int(
                            args.learned_export_online_seed_normal_start_max_frame_candidates
                        ),
                        normal_start_min_classical_tracks=int(
                            args.learned_export_online_seed_normal_start_min_classical_tracks
                        ),
                        normal_start_min_classical_grid=float(
                            args.learned_export_online_seed_normal_start_min_classical_grid
                        ),
                        max_classical_gftt_ratio=float(
                            args.learned_export_online_seed_max_classical_gftt_ratio
                        ),
                        gftt_ratio_min_classical_tracks=int(
                            args.learned_export_online_seed_gftt_ratio_min_classical_tracks
                        ),
                        gftt_ratio_min_classical_grid=float(
                            args.learned_export_online_seed_gftt_ratio_min_classical_grid
                        ),
                        microburst_state=online_seed_microburst_gate_state,
                        image_shape=gray.shape,
                    )
                )
                online_seed_refill_reason = str(learned_gate_info.benefit_reason)
                online_seed_refill_rejected = (
                    "online_seed_sparse_start" in online_seed_refill_reason
                    or "online_seed_gftt_dominated" in online_seed_refill_reason
                )
                if (
                    bool(args.learned_export_online_seed_refill_rejected_with_mirror)
                    and bool(online_seed_refill_rejected)
                    and mirror_export_tracks is not None
                    and len(export_tracks) < int(online_seed_pre_gate_count)
                ):
                    before_online_seed_refill = len(export_tracks)
                    online_seed_refill_target_count = min(
                        int(online_seed_pre_gate_count),
                        int(len(mirror_export_tracks)),
                    )
                    export_tracks = _restore_mirror_classical_after_sidecar_prune(
                        export_tracks,
                        mirror_export_tracks,
                        target_count=int(online_seed_refill_target_count),
                    )
                    if len(export_tracks) > before_online_seed_refill:
                        learned_gate_info = replace(
                            learned_gate_info,
                            benefit_reason=_append_benefit_reason(
                                learned_gate_info.benefit_reason,
                                "online_seed_mirror_refill",
                            ),
                        )
                online_seed_rejected_start_reason = str(
                    online_seed_microburst_gate_state.rejected_start_reason
                )
                online_seed_mirror_only_rejected = (
                    online_seed_rejected_start_reason.startswith("sparse_start")
                    or online_seed_rejected_start_reason.startswith("gftt_dominated")
                    or online_seed_rejected_start_reason.startswith("gftt_start")
                    or online_seed_rejected_start_reason.startswith("low_grid_start")
                )
                if (
                    bool(args.learned_export_online_seed_mirror_only_after_reject)
                    and bool(online_seed_mirror_only_rejected)
                    and mirror_export_tracks is not None
                ):
                    export_tracks = mirror_export_tracks
                    learned_gate_info = replace(
                        learned_gate_info,
                        benefit_reason=_append_benefit_reason(
                            learned_gate_info.benefit_reason,
                            "online_seed_mirror_only_after_reject",
                        ),
                    )
            if bool(args.learned_export_visible_track_gate) and (
                float(args.learned_export_visible_track_max_mean_step_px) > 0.0
                or int(args.learned_export_visible_track_min_count_per_frame) > 1
            ):
                visible_motion_threshold = float(
                    args.learned_export_visible_track_max_mean_step_px
                )
                if bool(args.learned_export_visible_track_motion_degraded_only):
                    geometry_mode = str(
                        getattr(tracker, "last_geometry_mode", "") or ""
                    ).lower()
                    if geometry_mode not in {"degraded_texture", "severe_low_texture"}:
                        visible_motion_threshold = 0.0
                if int(selected_feature_index) < int(
                    args.learned_export_visible_track_motion_min_frame
                ):
                    visible_motion_threshold = 0.0
                export_tracks, learned_gate_info = _apply_visible_sidecar_track_gate(
                    export_tracks,
                    learned_gate_info,
                    state=visible_sidecar_track_gate_state,
                    min_frames=1,
                    max_mean_step_px=visible_motion_threshold,
                    min_count_per_frame=int(
                        args.learned_export_visible_track_min_count_per_frame
                    ),
                    min_count_min_classical_grid=float(
                        args.learned_export_visible_track_min_count_min_classical_grid
                    ),
                )
            effective_sidecar_max_observations = int(
                args.learned_export_sidecar_max_observations
            )
            low_parallax_sidecar_max_observations = int(
                args.learned_export_low_parallax_sidecar_max_observations
            )
            if init_gate.triggered and low_parallax_sidecar_max_observations > 0:
                effective_sidecar_max_observations = (
                    low_parallax_sidecar_max_observations
                    if effective_sidecar_max_observations <= 0
                    else min(
                        effective_sidecar_max_observations,
                        low_parallax_sidecar_max_observations,
                    )
                )
            if effective_sidecar_max_observations > 0:
                # Apply the global sidecar budget after min-export and cooldown
                # gates. Otherwise short rejected LoFTR bursts can consume the
                # entire budget before any VINS-visible sidecar survives.
                export_tracks, learned_gate_info, learned_sidecar_observations_used = (
                    _apply_sidecar_observation_budget(
                        export_tracks,
                        learned_gate_info,
                        max_observations=effective_sidecar_max_observations,
                        used_observations=learned_sidecar_observations_used,
                    )
                )
            if args.reset_recovered_export_ids and not remapped_before_visible_gate:
                export_tracks = _remap_recovered_export_ids(
                    export_tracks,
                    export_id_state,
                    loftr_source_memory=bool(args.learned_export_loftr_source_memory),
                )
            if bool(args.learned_export_coverage_seeded_continuation_gate):
                export_tracks, learned_gate_info = _apply_coverage_seeded_continuation_gate(
                    export_tracks,
                    learned_gate_info,
                    state=coverage_seeded_continuation_gate_state,
                    max_classical_age=float(
                        args.learned_export_continuation_max_classical_age
                    ),
                    max_classical_motion_px=float(
                        args.learned_export_continuation_max_classical_motion_px
                    ),
                )
            motion_adaptive_post_refill = False
            if (
                adaptive_mirror_fallback
                and mirror_export_tracks is not None
                and bool(args.formal_export_disable_post_sidecar_mirror_refill)
                and bool(args.formal_export_motion_adaptive_post_sidecar_refill)
                and _has_sidecar_source(export_tracks)
            ):
                motion_px = float(learned_gate_info.classical_motion_px)
                max_motion_px = float(
                    args.formal_export_motion_adaptive_refill_max_motion_px
                )
                if math.isfinite(motion_px) and motion_px > max_motion_px:
                    motion_adaptive_mirror_refill_state.refill_until_frame = max(
                        int(motion_adaptive_mirror_refill_state.refill_until_frame),
                        int(selected_feature_index)
                        + max(
                            0,
                            int(
                                args.formal_export_motion_adaptive_refill_hold_frames
                            ),
                        ),
                    )
                motion_adaptive_post_refill = bool(
                    int(selected_feature_index)
                    <= int(motion_adaptive_mirror_refill_state.refill_until_frame)
                )
            if (
                adaptive_mirror_fallback
                and mirror_export_tracks is not None
                and (
                    not bool(args.formal_export_disable_post_sidecar_mirror_refill)
                    or motion_adaptive_post_refill
                )
            ):
                export_tracks = _restore_mirror_classical_after_sidecar_prune(
                    export_tracks,
                    mirror_export_tracks,
                    target_count=int(mirror_refill_target_count),
                )
                if motion_adaptive_post_refill:
                    learned_gate_info = replace(
                        learned_gate_info,
                        benefit_reason=_append_benefit_reason(
                            learned_gate_info.benefit_reason,
                            "motion_adaptive_mirror_refill",
                        ),
                    )
            zero_sidecar_mirror_restore = bool(
                args.formal_three_layer_export
                and args.formal_export_zero_sidecar_mirror_restore
                and mirror_export_tracks is not None
                and not _has_sidecar_source(export_tracks)
            )
            if (
                adaptive_mirror_fallback
                and mirror_export_tracks is not None
                and not _has_sidecar_source(export_tracks)
            ) or zero_sidecar_mirror_restore:
                export_tracks = mirror_export_tracks
                learned_gate_info = replace(
                    learned_gate_info,
                    benefit_reason=(
                        learned_gate_info.benefit_reason
                        if str(learned_gate_info.benefit_reason).endswith(
                            ":mirror_restore"
                        )
                        else f"{learned_gate_info.benefit_reason}:mirror_restore"
                    ),
                )
            skip_by_init_gate = (
                init_gate.triggered
                and selected_feature_index < int(init_gate.skip_feature_frames)
            )
            state_adaptive_q_triggered = _state_adaptive_quality_active(
                learned_gate_info,
                export_tracks,
                init_klt_only_active=init_klt_only_active,
                low_parallax_sidecar_block_active=low_parallax_sidecar_block_active,
            )
            if state_adaptive_q_triggered and int(args.backend_state_adaptive_hold_frames) > 0:
                state_adaptive_quality_hold_until = max(
                    state_adaptive_quality_hold_until,
                    selected_feature_index + int(args.backend_state_adaptive_hold_frames),
                )
            state_adaptive_q_active = bool(
                state_adaptive_q_triggered
                or selected_feature_index < state_adaptive_quality_hold_until
            )
            init_sidecar_support_q_active = bool(
                args.vins_safe_init_sidecar_support_selection
                and init_klt_only_active
                and _has_sidecar_source(export_tracks)
            )
            (
                effective_xfeat_quality_const,
                backend_xfeat_risk_q_active,
            ) = _resolve_xfeat_risk_quality_const(
                args,
                export_tracks,
                state=xfeat_risk_quality_state,
                skip_frame=skip_by_init_gate,
                low_parallax_active=bool(init_gate.triggered),
            )
            loftr_early_persistence_added = 0
            if bool(args.learned_export_loftr_early_persistence) and not skip_by_init_gate:
                export_tracks, loftr_early_persistence_added = _apply_loftr_early_persistence(
                    export_tracks,
                    state=loftr_early_persistence_state,
                    frame_index=selected_feature_index,
                    stamp=feature_stamp.to_sec(),
                    hold_frames=int(args.learned_export_loftr_persistence_hold_frames),
                    max_source_frame=int(args.learned_export_loftr_persistence_max_source_frame),
                    max_per_frame=int(args.learned_export_loftr_persistence_max_per_frame),
                    max_source_frames=int(args.learned_export_loftr_persistence_max_source_frames),
                    max_total=int(args.learned_export_loftr_persistence_max_total),
                    quality_scale=float(args.learned_export_loftr_persistence_quality_scale),
                )
            if bool(args.learned_export_online_seed_gate):
                export_tracks, learned_gate_info = (
                    _apply_online_seed_post_quality_cap_for_publication(
                        export_tracks,
                        learned_gate_info,
                        target_sources=str(args.learned_export_online_seed_sources),
                        max_per_frame=int(
                            args.learned_export_online_seed_post_quality_cap_per_frame
                        ),
                        raw_quality=bool(args.raw_quality_to_backend),
                        constant_quality=bool(args.constant_quality_to_backend),
                        backend_quality_mode=backend_quality_mode,
                        backend_quality_floor=backend_quality_floor,
                        backend_quality_alpha=backend_quality_alpha,
                        learned_quality_scale=float(args.backend_learned_quality_scale),
                        sp_lg_quality_scale=float(args.backend_sp_lg_quality_scale),
                        xfeat_quality_scale=float(args.backend_xfeat_quality_scale),
                        loftr_quality_scale=float(args.backend_loftr_quality_scale),
                        learned_quality_const=args.backend_learned_quality_const,
                        sp_lg_quality_const=args.backend_sp_lg_quality_const,
                        xfeat_quality_const=effective_xfeat_quality_const,
                        loftr_quality_const=args.backend_loftr_quality_const,
                        low_parallax_quality_boost=bool(
                            args.formal_three_layer_export and init_gate.triggered
                        ),
                        state_adaptive_active=state_adaptive_q_active,
                        init_sidecar_support_active=init_sidecar_support_q_active,
                        init_sidecar_classical_quality_floor=float(
                            args.vins_safe_init_sidecar_classical_quality_floor
                        ),
                    )
                )
            export_tracks, final_mirror_export_info = _finalize_mirror_sidecar_export(
                export_tracks,
                mirror_export_tracks,
                state=final_mirror_sidecar_id_state,
                max_features=args.export_max_features,
                preserve_classical_budget=bool(
                    args.final_mirror_preserve_classical_budget
                ),
                persistence_replacement=bool(
                    args.final_mirror_persistence_replacement
                ),
                selected_feature_index=int(selected_feature_index),
                persistence_max_selected_frame=int(
                    args.final_mirror_persistence_max_selected_frame
                ),
                persistence_min_age_advantage=int(
                    args.final_mirror_persistence_min_age_advantage
                ),
                persistence_single_chain=bool(
                    args.final_mirror_persistence_single_chain
                ),
                persistence_min_gftt_ratio=float(
                    args.final_mirror_persistence_min_gftt_ratio
                ),
                persistence_source_router=bool(
                    args.final_mirror_persistence_source_router
                ),
                persistence_allow_all_non_loftr=bool(
                    args.final_mirror_persistence_allow_all_non_loftr
                ),
                persistence_same_grid_cell=bool(
                    args.final_mirror_persistence_same_grid_cell
                ),
                persistence_coverage_monotone=bool(
                    args.final_mirror_persistence_coverage_monotone
                ),
                persistence_grid_rows=int(
                    args.final_mirror_persistence_grid_rows
                ),
                persistence_grid_cols=int(
                    args.final_mirror_persistence_grid_cols
                ),
                persistence_max_per_frame=int(
                    args.final_mirror_persistence_max_per_frame
                ),
                prefill_slot_admission=bool(
                    args.final_mirror_prefill_slot_admission
                ),
                prefill_slot_max_selected_frame=int(
                    args.final_mirror_prefill_slot_max_selected_frame
                ),
                prefill_slot_min_age=int(
                    args.final_mirror_prefill_slot_min_age
                ),
                prefill_slot_allow_all_non_loftr=bool(
                    args.final_mirror_prefill_slot_allow_all_non_loftr
                ),
                prefill_slot_max_per_frame=int(
                    args.final_mirror_prefill_slot_max_per_frame
                ),
                image_shape=gray.shape,
            )
            if final_mirror_export_info.zero_sidecar_restore:
                # A rejected/empty learned branch must not leave a quality-side
                # effect on the protected KLT mirror either.
                state_adaptive_q_triggered = False
                state_adaptive_q_active = False
                init_sidecar_support_q_active = False
                backend_xfeat_risk_q_active = False
            dt_for_velocity = (
                None
                if prev_feature_stamp_for_velocity is None
                else max(1e-6, feature_stamp.to_sec() - prev_feature_stamp_for_velocity)
            )
            point_cloud = _tracks_to_vins_pointcloud(
                tracks=export_tracks,
                stamp=feature_stamp,
                camera=camera,
                dt=dt_for_velocity,
                zero_velocity=args.zero_velocity,
                raw_quality=args.raw_quality_to_backend,
                constant_quality=args.constant_quality_to_backend,
                backend_quality_mode=backend_quality_mode,
                backend_quality_floor=backend_quality_floor,
                backend_quality_alpha=backend_quality_alpha,
                learned_quality_scale=float(args.backend_learned_quality_scale),
                sp_lg_quality_scale=float(args.backend_sp_lg_quality_scale),
                xfeat_quality_scale=float(args.backend_xfeat_quality_scale),
                loftr_quality_scale=float(args.backend_loftr_quality_scale),
                learned_quality_const=args.backend_learned_quality_const,
                sp_lg_quality_const=args.backend_sp_lg_quality_const,
                xfeat_quality_const=effective_xfeat_quality_const,
                loftr_quality_const=args.backend_loftr_quality_const,
                low_parallax_quality_boost=bool(
                    args.formal_three_layer_export and init_gate.triggered
                ),
                state_adaptive_active=state_adaptive_q_active,
                init_sidecar_support_active=init_sidecar_support_q_active,
                init_sidecar_classical_quality_floor=float(
                    args.vins_safe_init_sidecar_classical_quality_floor
                ),
            )
            if not skip_by_init_gate:
                out_bag.write(args.feature_topic, point_cloud, stamp)
            if metrics_writer is not None:
                backend_quality_for_metrics = _backend_reliability(
                    export_tracks,
                    raw_quality=args.raw_quality_to_backend,
                    constant_quality=args.constant_quality_to_backend,
                    mode=backend_quality_mode,
                    floor=backend_quality_floor,
                    alpha=backend_quality_alpha,
                    learned_quality_scale=float(args.backend_learned_quality_scale),
                    sp_lg_quality_scale=float(args.backend_sp_lg_quality_scale),
                    xfeat_quality_scale=float(args.backend_xfeat_quality_scale),
                    loftr_quality_scale=float(args.backend_loftr_quality_scale),
                    learned_quality_const=args.backend_learned_quality_const,
                    sp_lg_quality_const=args.backend_sp_lg_quality_const,
                    xfeat_quality_const=effective_xfeat_quality_const,
                    loftr_quality_const=args.backend_loftr_quality_const,
                    low_parallax_quality_boost=bool(
                        args.formal_three_layer_export and init_gate.triggered
                    ),
                    state_adaptive_active=state_adaptive_q_active,
                    init_sidecar_support_active=init_sidecar_support_q_active,
                    init_sidecar_classical_quality_floor=float(
                        args.vins_safe_init_sidecar_classical_quality_floor
                    ),
                )
                learned_mask_for_metrics = np.asarray(
                    [_is_learned_source(source) for source in export_tracks.sources],
                    dtype=bool,
                )
                classical_mask_for_metrics = ~learned_mask_for_metrics
                sidecar_export_diag = _sidecar_export_diagnostics(
                    export_tracks,
                    visible_state=(
                        visible_sidecar_track_gate_state
                        if bool(args.learned_export_visible_track_gate)
                        else None
                    ),
                )
                pre_gate_diag = _sidecar_pre_gate_diagnostics(
                    pre_gate_export_tracks,
                    min_age=int(args.learned_export_min_age),
                    loftr_min_age=(
                        None
                        if args.learned_export_loftr_min_age is None
                        else int(args.learned_export_loftr_min_age)
                    ),
                    min_quality=float(args.learned_export_min_quality),
                    loftr_min_quality=(
                        None
                        if args.learned_export_loftr_min_quality is None
                        else float(args.learned_export_loftr_min_quality)
                    ),
                    min_ncc=float(args.learned_export_min_ncc),
                    loftr_min_ncc=(
                        None
                        if args.learned_export_loftr_min_ncc is None
                        else float(args.learned_export_loftr_min_ncc)
                    ),
                    max_fb=float(args.learned_export_max_fb),
                    loftr_max_fb=(
                        None
                        if args.learned_export_loftr_max_fb is None
                        else float(args.learned_export_loftr_max_fb)
                    ),
                    require_confirmed=bool(sidecar_geometry_cfg.require_confirmed_learned),
                )
                screening_metrics, previous_screening_track_ids = _window_screening_metrics(
                    tracks,
                    gray.shape,
                    quality,
                    previous_screening_track_ids,
                    rows=screening_grid_rows,
                    cols=screening_grid_cols,
                )
                metrics_writer.writerow(
                    {
                        "frame_index": raw_index,
                        "timestamp": f"{feature_stamp.to_sec():.9f}",
                        "num_features": len(tracks),
                        **screening_metrics,
                        "exported_features": 0 if skip_by_init_gate else len(export_tracks),
                        "median_track_age": _median(export_tracks.ages),
                        "median_quality": _median(export_tracks.qualities),
                        "median_backend_quality": _median(backend_quality_for_metrics),
                        "median_classical_backend_quality": _median(
                            backend_quality_for_metrics[classical_mask_for_metrics]
                        ),
                        "median_learned_backend_quality": _median(
                            backend_quality_for_metrics[learned_mask_for_metrics]
                        ),
                        "recovery_reason": getattr(tracker, "last_recovery_reason", "n/a"),
                        "recovered_count": getattr(tracker, "last_recovered_count", 0),
                        "geometry_mode": getattr(tracker, "last_geometry_mode", "n/a"),
                        **_pairwise_geometry_metrics(tracker),
                        "learned_candidate_count": getattr(tracker, "last_learned_candidate_count", 0),
                        "learned_confirmed_count": getattr(tracker, "last_learned_confirmed_count", 0),
                        "learned_confirmed_xfeat_count": getattr(
                            tracker,
                            "last_confirmed_xfeat_count",
                            0,
                        ),
                        "proposer_confirmed_classical_gftt_count": getattr(
                            tracker,
                            "last_confirmed_classical_gftt_count",
                            0,
                        ),
                        "learned_confirmed_age_median": getattr(
                            tracker,
                            "last_confirmed_learned_age_median",
                            float("nan"),
                        ),
                        "pending_learned_count": getattr(tracker, "last_pending_learned_count", 0),
                        "pending_learned_age_median": getattr(
                            tracker,
                            "last_pending_learned_age_median",
                            float("nan"),
                        ),
                        "pending_xfeat_count": getattr(tracker, "last_pending_xfeat_count", 0),
                        "pending_xfeat_age_median": getattr(
                            tracker,
                            "last_pending_xfeat_age_median",
                            float("nan"),
                        ),
                        "source_provenance_count": getattr(
                            tracker,
                            "last_source_provenance_count",
                            0,
                        ),
                        "source_provenance_learned_count": getattr(
                            tracker,
                            "last_source_provenance_learned_count",
                            0,
                        ),
                        "source_provenance_xfeat_count": getattr(
                            tracker,
                            "last_source_provenance_xfeat_count",
                            0,
                        ),
                        "learned_mode": getattr(tracker, "last_learned_mode", "n/a"),
                        "learned_mode_before_sparse_h": getattr(
                            tracker,
                            "last_learned_mode_before_sparse_homography",
                            "n/a",
                        ),
                        "learned_mode_after_sparse_h": getattr(
                            tracker,
                            "last_learned_mode_after_sparse_homography",
                            "n/a",
                        ),
                        "loftr_sparse_h_allowed": (
                            1 if getattr(tracker, "last_loftr_sparse_homography_allowed", False) else 0
                        ),
                        "loftr_sparse_h_reason": getattr(
                            tracker,
                            "last_loftr_sparse_homography_reason",
                            "n/a",
                        ),
                        "klt_degeneracy_loftr_allowed": (
                            1 if getattr(tracker, "last_klt_degeneracy_loftr_allowed", False) else 0
                        ),
                        "klt_degeneracy_loftr_reason": getattr(
                            tracker,
                            "last_klt_degeneracy_loftr_reason",
                            "n/a",
                        ),
                        "klt_degeneracy_loftr_score": getattr(
                            tracker,
                            "last_klt_degeneracy_loftr_score",
                            0.0,
                        ),
                        "semidense_acceptance": getattr(tracker, "last_semidense_acceptance", "n/a"),
                        "semidense_raw_candidates": getattr(tracker, "last_semidense_raw_candidates", 0),
                        "semidense_post_validate_candidates": getattr(
                            tracker,
                            "last_semidense_post_validate_candidates",
                            0,
                        ),
                        "semidense_accepted_candidates": getattr(
                            tracker,
                            "last_semidense_accepted_candidates",
                            0,
                        ),
                        "semidense_queued_pending": getattr(tracker, "last_semidense_queued_pending", 0),
                        "semidense_grid_gain": getattr(tracker, "last_semidense_grid_gain", float("nan")),
                        "semidense_new_cell_ratio": getattr(
                            tracker,
                            "last_semidense_new_cell_ratio",
                            float("nan"),
                        ),
                        "semidense_before_f_inlier": getattr(
                            tracker,
                            "last_semidense_before_f_inlier",
                            float("nan"),
                        ),
                        "semidense_after_f_inlier": getattr(
                            tracker,
                            "last_semidense_after_f_inlier",
                            float("nan"),
                        ),
                        "semidense_before_h_inlier": getattr(
                            tracker,
                            "last_semidense_before_h_inlier",
                            float("nan"),
                        ),
                        "semidense_after_h_inlier": getattr(
                            tracker,
                            "last_semidense_after_h_inlier",
                            float("nan"),
                        ),
                        "semidense_before_epipolar": getattr(
                            tracker,
                            "last_semidense_before_epipolar",
                            float("nan"),
                        ),
                        "semidense_after_epipolar": getattr(
                            tracker,
                            "last_semidense_after_epipolar",
                            float("nan"),
                        ),
                        "semidense_before_homography": getattr(
                            tracker,
                            "last_semidense_before_homography",
                            float("nan"),
                        ),
                        "semidense_after_homography": getattr(
                            tracker,
                            "last_semidense_after_homography",
                            float("nan"),
                        ),
                        "pending_loftr_count": getattr(tracker, "last_pending_loftr_count", 0),
                        "pending_loftr_age_median": getattr(
                            tracker,
                            "last_pending_loftr_age_median",
                            float("nan"),
                        ),
                        "loftr_confirmed_promoted": getattr(tracker, "last_loftr_confirmed_promoted", 0),
                        "exported_learned_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_learned_source)
                        ),
                        "exported_non_loftr_learned_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_non_loftr_learned_source)
                        ),
                        "exported_sp_lg_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_sp_lg_source)
                        ),
                        "exported_xfeat_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_xfeat_source)
                        ),
                        "exported_classical_gftt_features": (
                            0
                            if skip_by_init_gate
                            else _count_sources(
                                export_tracks,
                                _is_classical_gftt_proposer_source,
                            )
                        ),
                        "exported_loftr_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_loftr_source)
                        ),
                        "exported_loftr_early_persisted_features": (
                            0 if skip_by_init_gate else int(loftr_early_persistence_added)
                        ),
                        "exported_recovered_features": (
                            0 if skip_by_init_gate else _count_sources(export_tracks, _is_recovered_source)
                        ),
                        "final_mirror_noharm_active": (
                            1 if final_mirror_export_info.active else 0
                        ),
                        "final_mirror_preserve_classical_budget": (
                            1
                            if final_mirror_export_info.preserve_classical_budget
                            else 0
                        ),
                        "final_mirror_zero_sidecar_restore": (
                            1 if final_mirror_export_info.zero_sidecar_restore else 0
                        ),
                        "final_mirror_input_sidecars": final_mirror_export_info.input_sidecars,
                        "final_mirror_kept_sidecars": final_mirror_export_info.kept_sidecars,
                        "final_mirror_dropped_sidecars_for_cap": (
                            final_mirror_export_info.dropped_sidecars_for_cap
                        ),
                        "final_mirror_dropped_sidecars_for_classical_budget": (
                            final_mirror_export_info.dropped_sidecars_for_classical_budget
                        ),
                        "final_mirror_dropped_classical_for_cap": (
                            final_mirror_export_info.dropped_classical_for_cap
                        ),
                        "final_mirror_remapped_sidecar_ids": (
                            final_mirror_export_info.remapped_sidecar_ids
                        ),
                        "final_mirror_persistence_replacement_active": (
                            1
                            if final_mirror_export_info.persistence_replacement_active
                            else 0
                        ),
                        "final_mirror_persistence_horizon_blocked": (
                            1
                            if final_mirror_export_info.persistence_horizon_blocked
                            else 0
                        ),
                        "final_mirror_persistence_eligible_sidecars": (
                            final_mirror_export_info.persistence_eligible_sidecars
                        ),
                        "final_mirror_persistence_eligible_gftt": (
                            final_mirror_export_info.persistence_eligible_gftt
                        ),
                        "final_mirror_persistence_replaced_gftt": (
                            final_mirror_export_info.persistence_replaced_gftt
                        ),
                        "final_mirror_persistence_dropped_sidecars": (
                            final_mirror_export_info.persistence_dropped_sidecars
                        ),
                        "final_mirror_persistence_single_chain_active": (
                            1
                            if final_mirror_export_info.persistence_single_chain_active
                            else 0
                        ),
                        "final_mirror_persistence_committed_sidecar_id": (
                            final_mirror_export_info.persistence_committed_sidecar_id
                        ),
                        "final_mirror_persistence_single_chain_suppressed": (
                            final_mirror_export_info.persistence_single_chain_suppressed
                        ),
                        "final_mirror_persistence_churn_guard_active": (
                            1
                            if final_mirror_export_info.persistence_churn_guard_active
                            else 0
                        ),
                        "final_mirror_persistence_churn_guard_decision": (
                            final_mirror_export_info.persistence_churn_guard_decision
                        ),
                        "final_mirror_persistence_churn_guard_decision_frame": (
                            final_mirror_export_info.persistence_churn_guard_decision_frame
                        ),
                        "final_mirror_persistence_churn_guard_gftt_births": (
                            final_mirror_export_info.persistence_churn_guard_gftt_births
                        ),
                        "final_mirror_persistence_churn_guard_denominator": (
                            final_mirror_export_info.persistence_churn_guard_denominator
                        ),
                        "final_mirror_persistence_churn_guard_ratio": (
                            final_mirror_export_info.persistence_churn_guard_ratio
                        ),
                        "final_mirror_persistence_source_router_active": (
                            1
                            if final_mirror_export_info.persistence_source_router_active
                            else 0
                        ),
                        "final_mirror_persistence_source_eligible_sidecars": (
                            final_mirror_export_info.persistence_source_eligible_sidecars
                        ),
                        "final_mirror_persistence_source_suppressed": (
                            final_mirror_export_info.persistence_source_suppressed
                        ),
                        "final_mirror_persistence_same_cell_active": (
                            1
                            if final_mirror_export_info.persistence_same_cell_active
                            else 0
                        ),
                        "final_mirror_persistence_same_cell_suppressed": (
                            final_mirror_export_info.persistence_same_cell_suppressed
                        ),
                        "final_mirror_persistence_coverage_monotone_active": (
                            1
                            if final_mirror_export_info.persistence_coverage_monotone_active
                            else 0
                        ),
                        "final_mirror_persistence_coverage_monotone_suppressed": (
                            final_mirror_export_info.persistence_coverage_monotone_suppressed
                        ),
                        "final_mirror_persistence_grid_cells_before": (
                            final_mirror_export_info.persistence_grid_cells_before
                        ),
                        "final_mirror_persistence_grid_cells_after": (
                            final_mirror_export_info.persistence_grid_cells_after
                        ),
                        "final_mirror_persistence_grid_cell_delta": (
                            final_mirror_export_info.persistence_grid_cell_delta
                        ),
                        "final_mirror_persistence_cross_cell_replacements": (
                            final_mirror_export_info.persistence_cross_cell_replacements
                        ),
                        "final_mirror_persistence_donor_cell_min_remaining": (
                            final_mirror_export_info.persistence_donor_cell_min_remaining
                        ),
                        "final_mirror_persistence_per_frame_cap": (
                            final_mirror_export_info.persistence_per_frame_cap
                        ),
                        "final_mirror_persistence_per_frame_cap_suppressed": (
                            final_mirror_export_info.persistence_per_frame_cap_suppressed
                        ),
                        "final_mirror_persistence_replaced_gftt_max_age": (
                            final_mirror_export_info.persistence_replaced_gftt_max_age
                        ),
                        "final_mirror_persistence_replacement_min_age_advantage_actual": (
                            final_mirror_export_info.persistence_replacement_min_age_advantage_actual
                        ),
                        "final_mirror_persistence_replacement_cell_mismatches": (
                            final_mirror_export_info.persistence_replacement_cell_mismatches
                        ),
                        "final_mirror_prefill_slot_active": (
                            1 if final_mirror_export_info.prefill_slot_active else 0
                        ),
                        "final_mirror_prefill_slot_horizon_blocked": (
                            1
                            if final_mirror_export_info.prefill_slot_horizon_blocked
                            else 0
                        ),
                        "final_mirror_prefill_slot_carried_observations": (
                            final_mirror_export_info.prefill_slot_carried_observations
                        ),
                        "final_mirror_prefill_slot_baseline_newborns": (
                            final_mirror_export_info.prefill_slot_baseline_newborns
                        ),
                        "final_mirror_prefill_slot_vacant_capacity": (
                            final_mirror_export_info.prefill_slot_vacant_capacity
                        ),
                        "final_mirror_prefill_slot_eligible_sidecars": (
                            final_mirror_export_info.prefill_slot_eligible_sidecars
                        ),
                        "final_mirror_prefill_slot_admitted_sidecars": (
                            final_mirror_export_info.prefill_slot_admitted_sidecars
                        ),
                        "final_mirror_prefill_slot_omitted_newborns": (
                            final_mirror_export_info.prefill_slot_omitted_newborns
                        ),
                        "final_mirror_prefill_slot_dropped_sidecars": (
                            final_mirror_export_info.prefill_slot_dropped_sidecars
                        ),
                        "final_mirror_prefill_slot_source_suppressed": (
                            final_mirror_export_info.prefill_slot_source_suppressed
                        ),
                        "final_mirror_prefill_slot_age_suppressed": (
                            final_mirror_export_info.prefill_slot_age_suppressed
                        ),
                        "final_mirror_prefill_slot_per_frame_cap": (
                            final_mirror_export_info.prefill_slot_per_frame_cap
                        ),
                        "exported_learned_median_age": sidecar_export_diag[
                            "learned_median_age"
                        ],
                        "exported_non_loftr_learned_median_age": sidecar_export_diag[
                            "non_loftr_learned_median_age"
                        ],
                        "exported_xfeat_median_age": sidecar_export_diag[
                            "xfeat_median_age"
                        ],
                        "exported_loftr_median_age": sidecar_export_diag[
                            "loftr_median_age"
                        ],
                        "exported_learned_age_lt3": sidecar_export_diag[
                            "learned_age_lt3"
                        ],
                        "exported_xfeat_age_lt3": sidecar_export_diag[
                            "xfeat_age_lt3"
                        ],
                        "exported_loftr_age_lt3": sidecar_export_diag[
                            "loftr_age_lt3"
                        ],
                        "exported_learned_median_visible_streak": sidecar_export_diag[
                            "learned_median_visible_streak"
                        ],
                        "exported_xfeat_median_visible_streak": sidecar_export_diag[
                            "xfeat_median_visible_streak"
                        ],
                        "exported_loftr_median_visible_streak": sidecar_export_diag[
                            "loftr_median_visible_streak"
                        ],
                        "exported_learned_median_motion_px": sidecar_export_diag[
                            "learned_median_motion_px"
                        ],
                        "exported_xfeat_median_motion_px": sidecar_export_diag[
                            "xfeat_median_motion_px"
                        ],
                        "exported_loftr_median_motion_px": sidecar_export_diag[
                            "loftr_median_motion_px"
                        ],
                        "pre_gate_sidecar_total": pre_gate_diag["sidecar_total"],
                        "pre_gate_sidecar_confirmed": pre_gate_diag["sidecar_confirmed"],
                        "pre_gate_sidecar_age_ok": pre_gate_diag["sidecar_age_ok"],
                        "pre_gate_sidecar_quality_ok": pre_gate_diag["sidecar_quality_ok"],
                        "pre_gate_sidecar_ncc_ok": pre_gate_diag["sidecar_ncc_ok"],
                        "pre_gate_sidecar_fb_ok": pre_gate_diag["sidecar_fb_ok"],
                        "pre_gate_sidecar_basic_ok": pre_gate_diag["sidecar_basic_ok"],
                        "pre_gate_loftr_total": pre_gate_diag["loftr_total"],
                        "pre_gate_loftr_basic_ok": pre_gate_diag["loftr_basic_ok"],
                        "pre_gate_non_loftr_total": pre_gate_diag["non_loftr_total"],
                        "pre_gate_non_loftr_basic_ok": pre_gate_diag["non_loftr_basic_ok"],
                        "source_selection_dropped": max(0, before_source_selection - len(export_tracks)),
                        "selected_feature_index": selected_feature_index,
                        "published_feature_frame": 0 if skip_by_init_gate else 1,
                        "init_parallax_gate_triggered": 1 if init_gate.triggered else 0,
                        "init_parallax_mean_step_px": init_gate.mean_step_px,
                        "init_parallax_skipped_feature": 1 if skip_by_init_gate else 0,
                        "init_klt_only_active": 1 if init_klt_only_active else 0,
                        "adaptive_warmup_full_mirror_enabled": (
                            1 if adaptive_warmup_full_mirror.enabled else 0
                        ),
                        "adaptive_warmup_full_mirror_reason": (
                            adaptive_warmup_full_mirror.reason
                        ),
                        "low_parallax_learned_holdoff_active": (
                            1 if low_parallax_learned_holdoff_active else 0
                        ),
                        "state_adaptive_q_triggered": 1 if state_adaptive_q_triggered else 0,
                        "state_adaptive_q_active": 1 if state_adaptive_q_active else 0,
                        "backend_xfeat_risk_q_active": (
                            1 if backend_xfeat_risk_q_active else 0
                        ),
                        "backend_xfeat_quality_const_effective": (
                            "none"
                            if effective_xfeat_quality_const is None
                            else effective_xfeat_quality_const
                        ),
                        "backend_xfeat_risk_learned_frames": (
                            xfeat_risk_quality_state.learned_frames
                        ),
                        "backend_xfeat_risk_cumulative_gftt": (
                            xfeat_risk_quality_state.cumulative_gftt
                        ),
                        "learned_export_gate_active": 1 if args.learned_export_degradation_gate else 0,
                        "learned_export_gate_degraded": 1 if learned_gate_info.degraded else 0,
                        "learned_export_gate_reason": learned_gate_info.reason,
                        "learned_export_loftr_min_quality": (
                            "none"
                            if args.learned_export_loftr_min_quality is None
                            else args.learned_export_loftr_min_quality
                        ),
                        "learned_export_loftr_min_age": (
                            "none"
                            if args.learned_export_loftr_min_age is None
                            else args.learned_export_loftr_min_age
                        ),
                        "learned_export_loftr_min_ncc": (
                            "none"
                            if args.learned_export_loftr_min_ncc is None
                            else args.learned_export_loftr_min_ncc
                        ),
                        "learned_export_loftr_max_fb": (
                            "none"
                            if args.learned_export_loftr_max_fb is None
                            else args.learned_export_loftr_max_fb
                        ),
                        "export_classical_mirror_backbone": 1 if mirror_backbone_tracker is not None else 0,
                        "classical_track_count": learned_gate_info.classical_count,
                        "classical_grid_coverage": learned_gate_info.classical_grid_coverage,
                        "learned_export_gate_dropped": learned_gate_info.dropped_learned,
                        "learned_export_geometry_dropped": learned_gate_info.geometry_dropped,
                        "learned_export_geometry_reason": learned_gate_info.geometry_reason,
                        "learned_export_benefit_dropped": learned_gate_info.benefit_dropped,
                        "learned_export_benefit_reason": learned_gate_info.benefit_reason,
                        "learned_export_temporal_dropped": learned_gate_info.temporal_dropped,
                        "learned_export_temporal_reason": learned_gate_info.temporal_reason,
                        "learned_export_temporal_recent_frames": learned_gate_info.temporal_recent_frames,
                        "learned_export_health_suppression_dropped": (
                            learned_gate_info.health_suppression_dropped
                        ),
                        "learned_export_health_suppression_reason": (
                            learned_gate_info.health_suppression_reason
                        ),
                        "learned_export_recent_healthy_frames": (
                            learned_gate_info.recent_healthy_frames
                        ),
                        "learned_export_recovery_reason_suppression_dropped": (
                            learned_gate_info.recovery_reason_suppression_dropped
                        ),
                        "learned_export_recovery_reason_suppression_reason": (
                            learned_gate_info.recovery_reason_suppression_reason
                        ),
                        "learned_export_recovery_burst_suppression_dropped": (
                            learned_gate_info.recovery_burst_suppression_dropped
                        ),
                        "learned_export_recovery_burst_suppression_reason": (
                            learned_gate_info.recovery_burst_suppression_reason
                        ),
                        "learned_export_recovery_burst_recent_frames": (
                            learned_gate_info.recovery_burst_recent_frames
                        ),
                        "learned_export_grid_gain": learned_gate_info.learned_grid_gain,
                        "learned_export_new_cells": learned_gate_info.learned_new_cells,
                        "learned_export_new_cell_ratio": learned_gate_info.learned_new_cell_ratio,
                        "learned_export_weak_cells": learned_gate_info.learned_weak_cells,
                        "classical_motion_px": learned_gate_info.classical_motion_px,
                        "classical_median_age": learned_gate_info.classical_median_age,
                        "tracker_source_histogram": _source_histogram(tracks),
                        "export_source_histogram": _source_histogram(export_tracks),
                    }
                )
            prev_feature_stamp_for_velocity = feature_stamp.to_sec()
            selected_feature_index += 1
            if not skip_by_init_gate:
                prev_stamp = feature_stamp.to_sec()
                if start_time is None:
                    start_time = feature_stamp.to_sec()
                emitted += 1

    if metrics_handle is not None:
        metrics_handle.close()

    span = 0.0 if start_time is None or prev_stamp is None else prev_stamp - start_time
    print(f"wrote {emitted} feature frames to {output_bag}")
    print(f"feature span: {span:.3f}s")
    if init_gate.enabled:
        print(
            "init parallax gate: "
            f"triggered={int(init_gate.triggered)} "
            f"mean_step_px={init_gate.mean_step_px:.6f} "
            f"skipped={init_gate.skip_feature_frames if init_gate.triggered else 0}"
        )
    floor_label = "none" if backend_quality_floor is None else f"{backend_quality_floor:.3f}"
    print(f"backend quality: mode={backend_quality_mode} floor={floor_label} alpha={backend_quality_alpha:.3f}")
    if skipped_invalid_header:
        print(f"skipped invalid-header frames: {skipped_invalid_header}")
    return 0


def _resolve_backend_quality_args(args: argparse.Namespace, cfg: dict) -> tuple[str, float | None, float]:
    quality_cfg = cfg.get("backend_quality", {}) or {}
    if not isinstance(quality_cfg, dict):
        raise ValueError("config backend_quality must be a mapping")

    mode = args.backend_quality_mode
    if mode is None:
        mode = quality_cfg.get("mode", cfg.get("backend_quality_mode", "default"))
    mode = str(mode or "default").lower()
    allowed_modes = {
        "default",
        "raw",
        "const",
        "floor",
        "blend",
        "source_aware",
        "vins_safe",
        "sidecar_only",
        "state_adaptive",
    }
    if mode not in allowed_modes:
        raise ValueError(f"unsupported backend quality mode: {mode}")

    # Preserve the existing legacy flag semantics. If both are set, constant
    # still wins because that was the first branch in the previous exporter.
    legacy_quality_flag = args.constant_quality_to_backend or args.raw_quality_to_backend
    if args.constant_quality_to_backend:
        mode = "const"
    elif args.raw_quality_to_backend:
        mode = "raw"

    alpha = _quality_arg_float(
        cli_value=args.backend_quality_alpha,
        nested_cfg=quality_cfg,
        nested_key="alpha",
        top_cfg=cfg,
        top_key="backend_quality_alpha",
        default=0.85,
    )
    if not 0.0 <= alpha <= 1.0:
        raise ValueError(f"backend quality alpha must be in [0, 1], got {alpha}")

    floor = _quality_arg_optional_float(
        cli_value=args.backend_quality_floor,
        nested_cfg=quality_cfg,
        nested_key="floor",
        top_cfg=cfg,
        top_key="backend_quality_floor",
    )
    if mode == "vins_safe" and args.backend_quality_floor is None:
        floor = None
    if floor is None and mode in {"floor", "source_aware"}:
        floor = 0.80
    if legacy_quality_flag and args.backend_quality_floor is None:
        floor = None
    if floor is not None and not 0.0 <= floor <= 1.0:
        raise ValueError(f"backend quality floor must be in [0, 1], got {floor}")
    return mode, floor, alpha


def _apply_formal_three_layer_export_defaults(args: argparse.Namespace) -> None:
    if not bool(getattr(args, "formal_three_layer_export", False)):
        return
    legacy_loftr_rescue = bool(getattr(args, "formal_export_legacy_loftr_rescue", False))
    preserve_input_backbone = bool(
        getattr(args, "formal_export_preserve_input_backbone", False)
    )
    adaptive_mirror_fallback = bool(
        getattr(args, "formal_export_adaptive_mirror_fallback", False)
        and not preserve_input_backbone
    )
    low_texture_active_sidecar = bool(
        getattr(args, "formal_export_low_texture_active_sidecar", False)
    )
    args.vins_safe_source_selection = True
    args.learned_export_degradation_gate = True
    args.learned_export_geometry_gate = True
    args.learned_export_require_confirmed = True
    args.learned_export_benefit_gate = True
    args.learned_export_benefit_loftr_only = True
    args.formal_export_zero_sidecar_mirror_restore = True
    # VINS-Fusion keys landmarks only by feature id. Learned/LoFTR sidecars
    # must therefore live in a separate export namespace; otherwise a learned
    # pairwise match can silently become the first observation of an ordinary
    # KLT landmark and corrupt initialization/triangulation.
    args.reset_recovered_export_ids = True
    if preserve_input_backbone:
        args.formal_export_allow_sparse_backbone = True
    if adaptive_mirror_fallback:
        args.formal_export_allow_sparse_backbone = True
        args.export_classical_mirror_backbone = True
    if (
        not preserve_input_backbone
        and not bool(getattr(args, "formal_export_allow_sparse_backbone", False))
    ):
        args.export_classical_mirror_backbone = True
    args.init_parallax_gate = True
    args.learned_export_loftr_requires_homography = True

    if not preserve_input_backbone:
        args.vins_init_klt_only_frames = max(int(args.vins_init_klt_only_frames), 20)
    args.init_loftr_sidecar_max_count = min(
        max(int(args.init_loftr_sidecar_max_count), 1),
        8,
    )
    args.low_parallax_learned_holdoff_frames = max(
        int(args.low_parallax_learned_holdoff_frames),
        0 if low_texture_active_sidecar else 8,
    )
    if not preserve_input_backbone:
        args.vins_safe_warmup_frames = max(int(args.vins_safe_warmup_frames), 20)
    args.vins_safe_max_learned = min(int(args.vins_safe_max_learned), 18)
    args.vins_safe_max_recovered = min(int(args.vins_safe_max_recovered), 10)
    args.vins_safe_min_learned_age = max(
        int(args.vins_safe_min_learned_age),
        1 if low_texture_active_sidecar else 3,
    )
    args.learned_export_temporal_burst_gate = True
    args.learned_export_require_fresh_non_loftr_confirmation = True
    args.learned_export_burst_window = max(int(args.learned_export_burst_window), 12)
    args.learned_export_burst_min_recent_frames = max(
        int(args.learned_export_burst_min_recent_frames),
        1,
    )
    args.learned_export_burst_late_start_frame = min(
        int(args.learned_export_burst_late_start_frame),
        80,
    )
    # A learned/LoFTR sidecar burst that survives all local gates but appears
    # only once late in the sequence is more likely to perturb VINS than to
    # improve track continuity. Requiring an unrealistically large same-frame
    # exception keeps acceptance tied to temporal support instead.
    args.learned_export_burst_min_sidecars = max(
        int(args.learned_export_burst_min_sidecars),
        3 if low_texture_active_sidecar else 99,
    )
    args.learned_export_allow_postinit_loftr_support = True
    args.learned_export_min_age = max(
        int(args.learned_export_min_age),
        1 if low_texture_active_sidecar else 3,
    )
    if args.learned_export_loftr_min_age is not None:
        args.learned_export_loftr_min_age = max(3, int(args.learned_export_loftr_min_age))
    args.learned_export_min_quality = max(
        float(args.learned_export_min_quality),
        0.05 if low_texture_active_sidecar else 0.18,
    )
    args.learned_export_min_ncc = max(
        float(args.learned_export_min_ncc),
        0.35 if low_texture_active_sidecar else 0.60,
    )
    args.learned_export_max_fb = min(
        float(args.learned_export_max_fb),
        1.50 if low_texture_active_sidecar else 0.85,
    )
    if args.learned_export_loftr_min_quality is not None:
        args.learned_export_loftr_min_quality = max(
            0.05,
            float(args.learned_export_loftr_min_quality),
        )
    if args.learned_export_loftr_min_ncc is not None:
        args.learned_export_loftr_min_ncc = max(
            0.48,
            float(args.learned_export_loftr_min_ncc),
        )
    if args.learned_export_loftr_max_fb is not None:
        args.learned_export_loftr_max_fb = min(
            1.00,
            float(args.learned_export_loftr_max_fb),
        )
    args.learned_export_min_grid_gain = max(
        float(args.learned_export_min_grid_gain),
        0.0 if low_texture_active_sidecar else 1.0 / 24.0,
    )
    # A single accepted LoFTR point can perturb VINS without providing a real
    # spatial-coverage benefit. Keep LoFTR support-rescue separate, but require
    # ordinary coverage-gain sidecars to open at least two new cells.
    args.learned_export_min_new_cells = max(
        int(args.learned_export_min_new_cells),
        1 if (legacy_loftr_rescue or low_texture_active_sidecar) else 2,
    )
    args.learned_export_min_new_cell_ratio = max(
        float(args.learned_export_min_new_cell_ratio),
        0.05 if low_texture_active_sidecar else 0.30,
    )
    args.learned_export_max_per_new_cell = min(max(int(args.learned_export_max_per_new_cell), 1), 2)
    args.learned_export_coverage_gain_max_classical_tracks = max(
        int(args.learned_export_coverage_gain_max_classical_tracks),
        0,
    )
    args.learned_export_weak_cell_max_count = min(
        max(int(args.learned_export_weak_cell_max_count), 1),
        10 if low_texture_active_sidecar else 2,
    )
    args.learned_export_weak_cell_min_candidates = max(
        int(args.learned_export_weak_cell_min_candidates),
        2 if low_texture_active_sidecar else 5,
    )
    args.learned_export_weak_cell_max_occupancy = min(
        max(int(args.learned_export_weak_cell_max_occupancy), 1),
        12 if low_texture_active_sidecar else 8,
    )
    args.learned_export_weak_cell_min_classical_motion_px = max(
        float(args.learned_export_weak_cell_min_classical_motion_px),
        0.0 if low_texture_active_sidecar else 3.0,
    )
    args.learned_export_weak_cell_max_classical_grid = min(
        float(args.learned_export_weak_cell_max_classical_grid),
        0.82,
    )
    args.learned_export_weak_cell_max_classical_tracks = max(
        int(args.learned_export_weak_cell_max_classical_tracks),
        0,
    )
    args.learned_export_mature_cell_max_count = min(
        max(int(args.learned_export_mature_cell_max_count), 1),
        8,
    )
    # If mature-cell rescue is explicitly enabled, trust the caller's
    # candidate/motion thresholds. This path is already protected by confirmed
    # source labels, export-level F/E/H residual gates, a low-grid degradation
    # trigger, and a small per-frame cap. Keeping the old hard floor of four
    # candidates silently blocked the intended "few but stable SP/LG sidecar"
    # case on AQUALOC A08.
    mature_rescue_enabled = bool(getattr(args, "learned_export_mature_cell_rescue", False))
    args.learned_export_mature_cell_min_candidates = max(
        int(args.learned_export_mature_cell_min_candidates),
        1 if mature_rescue_enabled else 4,
    )
    if not mature_rescue_enabled:
        args.learned_export_mature_cell_min_classical_age = max(
            float(args.learned_export_mature_cell_min_classical_age),
            10.0,
        )
    else:
        # Low-coverage underwater windows often have exactly the short KLT ages
        # that motivate a learned sidecar. When mature-cell rescue is explicitly
        # enabled, let the caller lower this age threshold while the confirmation,
        # F/E/H residual, and small per-frame budget gates remain active.
        args.learned_export_mature_cell_min_classical_age = float(
            args.learned_export_mature_cell_min_classical_age
        )
    args.learned_export_mature_cell_min_classical_motion_px = max(
        float(args.learned_export_mature_cell_min_classical_motion_px),
        0.0 if low_texture_active_sidecar else (2.0 if mature_rescue_enabled else 3.0),
    )
    args.learned_export_mature_cell_max_classical_grid = min(
        float(args.learned_export_mature_cell_max_classical_grid),
        0.84,
    )
    args.learned_export_mature_cell_max_per_cell = min(
        max(int(args.learned_export_mature_cell_max_per_cell), 1),
        2,
    )
    args.learned_export_mature_cell_max_occupancy = min(
        max(int(args.learned_export_mature_cell_max_occupancy), 1),
        48,
    )
    loftr_planar_rescue_enabled = bool(getattr(args, "learned_export_loftr_planar_rescue", False))
    loftr_weak_cell_rescue_enabled = bool(getattr(args, "learned_export_loftr_weak_cell_rescue", False))
    loftr_rescue_enabled = loftr_planar_rescue_enabled or loftr_weak_cell_rescue_enabled
    if loftr_rescue_enabled:
        if args.learned_export_loftr_min_quality is None:
            args.learned_export_loftr_min_quality = 0.05
        if args.learned_export_loftr_min_age is None:
            args.learned_export_loftr_min_age = 3
        if args.learned_export_loftr_min_ncc is None:
            args.learned_export_loftr_min_ncc = 0.48
        if args.learned_export_loftr_max_fb is None:
            args.learned_export_loftr_max_fb = 1.00
    args.learned_export_loftr_planar_max_count = min(
        max(int(args.learned_export_loftr_planar_max_count), 1),
        24 if (loftr_planar_rescue_enabled or legacy_loftr_rescue) else 3,
    )
    args.learned_export_loftr_planar_min_candidates = max(
        int(args.learned_export_loftr_planar_min_candidates),
        1 if legacy_loftr_rescue else 3,
    )
    args.learned_export_loftr_planar_max_classical_grid = min(
        float(args.learned_export_loftr_planar_max_classical_grid),
        0.86,
    )
    args.learned_export_loftr_planar_min_classical_motion_px = max(
        float(args.learned_export_loftr_planar_min_classical_motion_px),
        0.0 if low_texture_active_sidecar else 1.2,
    )
    args.learned_export_loftr_weak_cell_max_count = min(
        max(int(args.learned_export_loftr_weak_cell_max_count), 0),
        24,
    )
    args.learned_export_loftr_weak_cell_max_occupancy = min(
        max(int(args.learned_export_loftr_weak_cell_max_occupancy), 1),
        80,
    )
    args.learned_export_loftr_rescue_max_classical_tracks = max(
        int(args.learned_export_loftr_rescue_max_classical_tracks),
        0,
    )
    if loftr_weak_cell_rescue_enabled:
        loftr_support_max_init_parallax = float(
            args.learned_export_loftr_support_max_init_parallax_px
        )
        args.learned_export_loftr_support_max_init_parallax_px = (
            loftr_support_max_init_parallax
            if loftr_support_max_init_parallax > 0.0
            else 8.0
        )
        loftr_support_max_motion = float(
            args.learned_export_loftr_support_max_classical_motion_px
        )
        args.learned_export_loftr_support_max_classical_motion_px = (
            loftr_support_max_motion
            if loftr_support_max_motion > 0.0
            else (0.0 if low_texture_active_sidecar else 2.2)
        )
    args.learned_export_min_classical_tracks = max(int(args.learned_export_min_classical_tracks), 260)
    args.learned_export_min_classical_grid = max(float(args.learned_export_min_classical_grid), 0.78)
    args.learned_export_min_classical_age = max(float(args.learned_export_min_classical_age), 0.0)
    # LoFTR/learned sidecars are useful only when the KLT backbone has enough
    # inter-frame motion for VINS to benefit from the added observations. This
    # blocks low-parallax identity churn in normal or slowly moving texture,
    # while preserving the A06 low-texture planar support frames.
    args.learned_export_min_classical_motion_px = max(
        float(args.learned_export_min_classical_motion_px),
        0.0 if low_texture_active_sidecar else 2.0,
    )
    args.init_parallax_probe_frames = max(int(args.init_parallax_probe_frames), 5)
    args.init_parallax_threshold_px = max(float(args.init_parallax_threshold_px), 7.0)
    args.init_parallax_skip_feature_frames = max(int(args.init_parallax_skip_feature_frames), 0)
    args.init_parallax_adaptive_skip_frames = max(
        int(args.init_parallax_adaptive_skip_frames),
        4,
    )
    args.init_parallax_adaptive_min_px = max(float(args.init_parallax_adaptive_min_px), 0.0)
    args.init_parallax_adaptive_max_px = max(
        float(args.init_parallax_adaptive_max_px),
        float(args.init_parallax_adaptive_min_px),
    )
    if args.backend_quality_mode is None:
        args.backend_quality_mode = "vins_safe"
    if args.backend_quality_alpha is None:
        args.backend_quality_alpha = 0.65
    args.backend_loftr_quality_scale = min(float(args.backend_loftr_quality_scale), 0.85)


def _quality_arg_float(
    cli_value: float | None,
    nested_cfg: dict,
    nested_key: str,
    top_cfg: dict,
    top_key: str,
    default: float,
) -> float:
    if cli_value is not None:
        return float(cli_value)
    if nested_key in nested_cfg:
        return float(nested_cfg[nested_key])
    if top_key in top_cfg:
        return float(top_cfg[top_key])
    return float(default)


def _quality_arg_optional_float(
    cli_value: float | None,
    nested_cfg: dict,
    nested_key: str,
    top_cfg: dict,
    top_key: str,
) -> float | None:
    if cli_value is not None:
        return float(cli_value)
    if nested_key in nested_cfg:
        if nested_cfg[nested_key] is None:
            return None
        return float(nested_cfg[nested_key])
    if top_key in top_cfg:
        if top_cfg[top_key] is None:
            return None
        return float(top_cfg[top_key])
    return None


def _build_tracker(
    method: str,
    cfg: dict,
    semidense_fallback_method: str,
    *,
    camera: dict | None = None,
):
    if method == "klt":
        return KltTracker(KltConfig(**cfg.get("klt", {})))
    if method == "orb":
        return OrbTracker(OrbConfig(**cfg.get("orb", {})))
    if method == "hybrid":
        return HybridKltOrbTracker(
            KltConfig(**cfg.get("klt", {})),
            HybridConfig(**cfg.get("hybrid", {})),
        )
    if method in {
        "xfeat",
        "xfeat_star",
        "superpoint_lightglue",
        "loftr",
        "classical_gftt",
    }:
        pairwise_config = PairwiseMatcherTrackerConfig(**cfg.get("pairwise", {}))
        point_normalizer = None
        geometry_focal_mean_px = None
        if pairwise_config.geometry_mode == "dl_vins_magsac" and camera is not None:
            point_normalizer = lambda points: _pixels_to_normalized(points, camera)
            geometry_focal_mean_px = _camera_focal_mean_px(camera)
        return PairwiseMatcherTracker(
            build_matcher(method, cfg),
            pairwise_config,
            point_normalizer=point_normalizer,
            geometry_focal_mean_px=geometry_focal_mean_px,
        )
    if method in {
        "hybrid_xfeat",
        "hybrid_xfeat_star",
        "hybrid_superpoint_lightglue",
        "hybrid_loftr",
        "hybrid_classical_gftt",
    }:
        fallback_matcher = (
            build_matcher(semidense_fallback_method, cfg)
            if semidense_fallback_method != "none"
            else None
        )
        return HybridKltOrbTracker(
            KltConfig(**cfg.get("klt", {})),
            HybridConfig(**cfg.get("hybrid", {})),
            learned_matcher=build_matcher(method, cfg),
            semidense_fallback_matcher=fallback_matcher,
        )
    raise ValueError(f"unsupported frontend method: {method}")


def _gate_params_from_args(
    args: argparse.Namespace,
    *,
    init_klt_only_active: bool = False,
    init_parallax_mean_step_px: float = float("nan"),
) -> _GateParams:
    return _GateParams(
        min_classical_tracks=int(args.learned_export_min_classical_tracks),
        min_classical_grid=float(args.learned_export_min_classical_grid),
        min_age=int(args.learned_export_min_age),
        loftr_min_age=(
            None
            if args.learned_export_loftr_min_age is None
            else int(args.learned_export_loftr_min_age)
        ),
        min_quality=float(args.learned_export_min_quality),
        min_ncc=float(args.learned_export_min_ncc),
        max_fb=float(args.learned_export_max_fb),
        loftr_min_quality=(
            None
            if args.learned_export_loftr_min_quality is None
            else float(args.learned_export_loftr_min_quality)
        ),
        loftr_min_ncc=(
            None
            if args.learned_export_loftr_min_ncc is None
            else float(args.learned_export_loftr_min_ncc)
        ),
        loftr_max_fb=(
            None
            if args.learned_export_loftr_max_fb is None
            else float(args.learned_export_loftr_max_fb)
        ),
        benefit_gate=bool(args.learned_export_benefit_gate),
        benefit_loftr_only=bool(args.learned_export_benefit_loftr_only),
        min_grid_gain=float(args.learned_export_min_grid_gain),
        min_new_cells=int(args.learned_export_min_new_cells),
        min_new_cell_ratio=float(args.learned_export_min_new_cell_ratio),
        max_per_new_cell=int(args.learned_export_max_per_new_cell),
        coverage_gain_max_classical_tracks=int(args.learned_export_coverage_gain_max_classical_tracks),
        min_classical_motion_px=float(args.learned_export_min_classical_motion_px),
        min_classical_age=float(args.learned_export_min_classical_age),
        weak_cell_rescue=bool(args.learned_export_weak_cell_rescue),
        non_loftr_weak_cell_rescue=bool(args.learned_export_non_loftr_weak_cell_rescue),
        weak_cell_max_count=int(args.learned_export_weak_cell_max_count),
        weak_cell_min_candidates=int(args.learned_export_weak_cell_min_candidates),
        weak_cell_max_occupancy=int(args.learned_export_weak_cell_max_occupancy),
        weak_cell_min_classical_motion_px=float(args.learned_export_weak_cell_min_classical_motion_px),
        weak_cell_max_classical_grid=float(args.learned_export_weak_cell_max_classical_grid),
        weak_cell_max_classical_tracks=int(args.learned_export_weak_cell_max_classical_tracks),
        mature_cell_rescue=bool(args.learned_export_mature_cell_rescue),
        mature_cell_max_count=int(args.learned_export_mature_cell_max_count),
        mature_cell_min_candidates=int(args.learned_export_mature_cell_min_candidates),
        mature_cell_min_classical_age=float(args.learned_export_mature_cell_min_classical_age),
        mature_cell_min_classical_motion_px=float(args.learned_export_mature_cell_min_classical_motion_px),
        mature_cell_max_classical_grid=float(args.learned_export_mature_cell_max_classical_grid),
        mature_cell_max_per_cell=int(args.learned_export_mature_cell_max_per_cell),
        mature_cell_max_occupancy=int(args.learned_export_mature_cell_max_occupancy),
        loftr_planar_rescue=bool(args.learned_export_loftr_planar_rescue),
        loftr_planar_max_count=int(args.learned_export_loftr_planar_max_count),
        loftr_planar_min_candidates=int(args.learned_export_loftr_planar_min_candidates),
        loftr_planar_max_classical_grid=float(args.learned_export_loftr_planar_max_classical_grid),
        loftr_planar_min_classical_motion_px=float(args.learned_export_loftr_planar_min_classical_motion_px),
        # Initialization safety is enforced before this gate by selecting a
        # KLT-only backbone unless the explicit init LoFTR rescue path is
        # enabled. After initialization, formal three-layer export still needs
        # the weak-cell LoFTR path for planar low-texture support; blocking it
        # here silently turns accepted LoFTR candidates into "low motion"
        # rejections.
        loftr_weak_cell_rescue=bool(args.learned_export_loftr_weak_cell_rescue),
        loftr_weak_cell_max_count=int(args.learned_export_loftr_weak_cell_max_count),
        loftr_weak_cell_max_occupancy=int(args.learned_export_loftr_weak_cell_max_occupancy),
        loftr_rescue_max_classical_tracks=int(
            args.learned_export_loftr_rescue_max_classical_tracks
        ),
        loftr_support_max_init_parallax_px=float(
            args.learned_export_loftr_support_max_init_parallax_px
        ),
        loftr_support_max_classical_motion_px=float(
            args.learned_export_loftr_support_max_classical_motion_px
        ),
        init_parallax_mean_step_px=float(init_parallax_mean_step_px),
        non_loftr_requires_degraded_mode=bool(
            args.learned_export_non_loftr_requires_degraded_mode
        ),
    )


def _apply_learned_export_gate_from_params(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    tracker_recovery_reason: str,
    tracker_learned_mode: str,
    camera: dict | None,
    geometry_cfg: _SidecarGeometryConfig | None,
    params: _GateParams,
    loftr_continuation_state: _LoFTRSeededContinuationGateState | None = None,
    frame_index: int = -1,
    loftr_continuation_max_gap: int = 1,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    return _apply_learned_export_degradation_gate(
        tracks,
        image_shape=image_shape,
        tracker_recovery_reason=tracker_recovery_reason,
        tracker_learned_mode=tracker_learned_mode,
        min_classical_tracks=params.min_classical_tracks,
        min_classical_grid=params.min_classical_grid,
        min_age=params.min_age,
        loftr_min_age=params.loftr_min_age,
        min_quality=params.min_quality,
        min_ncc=params.min_ncc,
        max_fb=params.max_fb,
        loftr_min_quality=params.loftr_min_quality,
        loftr_min_ncc=params.loftr_min_ncc,
        loftr_max_fb=params.loftr_max_fb,
        camera=camera,
        geometry_cfg=geometry_cfg,
        benefit_gate=params.benefit_gate,
        benefit_loftr_only=params.benefit_loftr_only,
        min_grid_gain=params.min_grid_gain,
        min_new_cells=params.min_new_cells,
        min_new_cell_ratio=params.min_new_cell_ratio,
        max_per_new_cell=params.max_per_new_cell,
        coverage_gain_max_classical_tracks=params.coverage_gain_max_classical_tracks,
        min_classical_motion_px=params.min_classical_motion_px,
        min_classical_age=params.min_classical_age,
        weak_cell_rescue=params.weak_cell_rescue,
        non_loftr_weak_cell_rescue=params.non_loftr_weak_cell_rescue,
        weak_cell_max_count=params.weak_cell_max_count,
        weak_cell_min_candidates=params.weak_cell_min_candidates,
        weak_cell_max_occupancy=params.weak_cell_max_occupancy,
        weak_cell_min_classical_motion_px=params.weak_cell_min_classical_motion_px,
        weak_cell_max_classical_grid=params.weak_cell_max_classical_grid,
        weak_cell_max_classical_tracks=params.weak_cell_max_classical_tracks,
        mature_cell_rescue=params.mature_cell_rescue,
        mature_cell_max_count=params.mature_cell_max_count,
        mature_cell_min_candidates=params.mature_cell_min_candidates,
        mature_cell_min_classical_age=params.mature_cell_min_classical_age,
        mature_cell_min_classical_motion_px=params.mature_cell_min_classical_motion_px,
        mature_cell_max_classical_grid=params.mature_cell_max_classical_grid,
        mature_cell_max_per_cell=params.mature_cell_max_per_cell,
        mature_cell_max_occupancy=params.mature_cell_max_occupancy,
        loftr_planar_rescue=params.loftr_planar_rescue,
        loftr_planar_max_count=params.loftr_planar_max_count,
        loftr_planar_min_candidates=params.loftr_planar_min_candidates,
        loftr_planar_max_classical_grid=params.loftr_planar_max_classical_grid,
        loftr_planar_min_classical_motion_px=params.loftr_planar_min_classical_motion_px,
        loftr_weak_cell_rescue=params.loftr_weak_cell_rescue,
        loftr_weak_cell_max_count=params.loftr_weak_cell_max_count,
        loftr_weak_cell_max_occupancy=params.loftr_weak_cell_max_occupancy,
        loftr_rescue_max_classical_tracks=params.loftr_rescue_max_classical_tracks,
        loftr_support_max_init_parallax_px=params.loftr_support_max_init_parallax_px,
        loftr_support_max_classical_motion_px=params.loftr_support_max_classical_motion_px,
        init_parallax_mean_step_px=params.init_parallax_mean_step_px,
        non_loftr_requires_degraded_mode=params.non_loftr_requires_degraded_mode,
        loftr_continuation_state=loftr_continuation_state,
        frame_index=int(frame_index),
        loftr_continuation_max_gap=int(loftr_continuation_max_gap),
    )


def _resolve_init_parallax_gate(
    args: argparse.Namespace,
    cfg: dict,
    measurement_selection_cfg: MeasurementSelectionConfig,
) -> _InitParallaxGateState:
    if not bool(args.init_parallax_gate):
        return _InitParallaxGateState.disabled()

    quality_gate_source = str(
        cfg.get("quality", {}).get("gate_source", cfg.get("quality_gate_source", "preprocessed"))
    )
    probe_frames = max(2, int(args.init_parallax_probe_frames))
    bridge = CvBridge()
    camera = _load_pinhole_camera(Path(args.camera_config))
    tracker = _build_tracker(
        args.method,
        cfg,
        args.semidense_fallback_method,
        camera=camera,
    )
    sidecar_geometry_cfg = _SidecarGeometryConfig(
        enabled=bool(args.learned_export_geometry_gate),
        require_confirmed_learned=bool(args.learned_export_require_confirmed),
        max_epipolar_error=float(args.learned_export_max_epipolar_error),
        max_essential_error=float(args.learned_export_max_essential_error),
        max_homography_error=float(args.learned_export_max_homography_error),
        residual_max_ratio=float(args.learned_export_residual_max_ratio),
        residual_max_epipolar_abs=float(args.learned_export_residual_max_epipolar_abs),
        residual_max_essential_abs=float(args.learned_export_residual_max_essential_abs),
        residual_max_homography_abs=float(args.learned_export_residual_max_homography_abs),
        min_reference_tracks=int(args.learned_export_geometry_min_reference_tracks),
        loftr_requires_homography=bool(args.learned_export_loftr_requires_homography),
    )
    feature_frames: list[dict[int, tuple[float, float]]] = []
    seen_images = 0
    selected_feature_index = 0
    every_n = max(1, int(args.every_n))

    input_bag = Path(args.bag)
    with rosbag.Bag(str(input_bag), "r") as in_bag:
        bag_start = in_bag.get_start_time()
        window_start = bag_start + max(0.0, float(args.start_offset))
        window_end = None
        if args.duration is not None:
            window_end = window_start + max(0.0, float(args.duration))
        for topic, msg, stamp in in_bag.read_messages(topics=[args.image_topic]):
            t = stamp.to_sec()
            if t < window_start:
                continue
            if window_end is not None and t > window_end:
                break
            raw_index = seen_images
            seen_images += 1
            should_publish = raw_index % every_n == (int(args.frame_offset) % every_n)
            if args.max_frames is not None and selected_feature_index >= int(args.max_frames):
                break
            _feature_stamp, invalid_header = _select_feature_stamp(
                msg,
                stamp,
                source=args.timestamp_source,
                max_header_delta=args.max_header_stamp_delta,
                invalid_policy=args.invalid_header_policy,
            )
            if invalid_header and args.invalid_header_policy == "skip":
                continue
            if not should_publish and not args.process_skipped_frames:
                continue

            raw_gray = _image_msg_to_gray(bridge, msg)
            raw_quality = score_image_quality(raw_gray)
            gray = _preprocess_gray(raw_gray, args.preprocess)
            processed_quality = score_image_quality(gray)
            quality = fuse_image_quality_for_gates(
                processed_quality,
                raw_quality,
                quality_gate_source,
            )
            tracks, _diagnostics = tracker.process(gray, quality)
            if not should_publish:
                continue

            candidate_tracks = tracks
            if int(args.export_min_learned_age) > 0:
                candidate_tracks = _filter_young_learned_tracks(
                    candidate_tracks,
                    min_age=int(args.export_min_learned_age),
                )
            init_klt_only_active = selected_feature_index < max(0, int(args.vins_init_klt_only_frames))
            select_cfg = measurement_selection_cfg
            if bool(args.formal_three_layer_export) and init_klt_only_active:
                select_cfg = replace(measurement_selection_cfg, enabled=False)
            if (
                int(args.selection_warmup_frames) > 0
                and selected_feature_index < int(args.selection_warmup_frames)
            ):
                select_cfg = replace(measurement_selection_cfg, enabled=False)
            export_tracks = select_backend_measurements(
                candidate_tracks,
                gray.shape,
                select_cfg,
                geometry_mode=getattr(tracker, "last_geometry_mode", "unknown"),
            )
            if selected_feature_index < max(0, int(args.vins_init_klt_only_frames)):
                export_tracks = _select_classical_backbone_sources(export_tracks)
            defer_vins_safe_selection = bool(
                args.formal_three_layer_export and args.learned_export_degradation_gate
            )
            if args.vins_safe_source_selection and not defer_vins_safe_selection:
                max_total = args.vins_safe_max_total
                if max_total is None:
                    max_total = (
                        int(args.export_max_features)
                        if args.export_max_features is not None
                        else len(export_tracks)
                    )
                export_tracks = _select_vins_safe_sources(
                    export_tracks,
                    emitted_frame_index=selected_feature_index,
                    image_shape=gray.shape,
                    warmup_frames=int(args.vins_safe_warmup_frames),
                    max_total=int(max_total),
                    max_learned=int(args.vins_safe_max_learned),
                    max_recovered=int(args.vins_safe_max_recovered),
                    min_learned_age=int(args.vins_safe_min_learned_age),
                    preserve_classical_budget=bool(
                        args.vins_safe_preserve_classical_budget
                    ),
                    allow_warmup_confirmed_loftr=False,
                    warmup_confirmed_loftr_max_count=0,
                    init_sidecar_support_selection=False,
                    init_sidecar_support_count=0,
                )
            if args.learned_export_degradation_gate:
                export_tracks, _gate_info = _apply_learned_export_degradation_gate(
                    export_tracks,
                    image_shape=gray.shape,
                    tracker_recovery_reason=getattr(tracker, "last_recovery_reason", "n/a"),
                    tracker_learned_mode=getattr(tracker, "last_learned_mode", "n/a"),
                    min_classical_tracks=int(args.learned_export_min_classical_tracks),
                    min_classical_grid=float(args.learned_export_min_classical_grid),
                    min_age=int(args.learned_export_min_age),
                    min_quality=float(args.learned_export_min_quality),
                    min_ncc=float(args.learned_export_min_ncc),
                    max_fb=float(args.learned_export_max_fb),
                    loftr_min_quality=(
                        None
                        if args.learned_export_loftr_min_quality is None
                        else float(args.learned_export_loftr_min_quality)
                    ),
                    loftr_min_ncc=(
                        None
                        if args.learned_export_loftr_min_ncc is None
                        else float(args.learned_export_loftr_min_ncc)
                    ),
                    loftr_max_fb=(
                        None
                        if args.learned_export_loftr_max_fb is None
                        else float(args.learned_export_loftr_max_fb)
                    ),
                    camera=camera,
                    geometry_cfg=sidecar_geometry_cfg,
                    benefit_gate=bool(args.learned_export_benefit_gate),
                    benefit_loftr_only=bool(args.learned_export_benefit_loftr_only),
                    min_grid_gain=float(args.learned_export_min_grid_gain),
                    min_new_cells=int(args.learned_export_min_new_cells),
                    min_new_cell_ratio=float(args.learned_export_min_new_cell_ratio),
                    max_per_new_cell=int(args.learned_export_max_per_new_cell),
                    coverage_gain_max_classical_tracks=int(
                        args.learned_export_coverage_gain_max_classical_tracks
                    ),
                    min_classical_motion_px=float(args.learned_export_min_classical_motion_px),
                    min_classical_age=float(args.learned_export_min_classical_age),
                    weak_cell_rescue=bool(args.learned_export_weak_cell_rescue),
                    non_loftr_weak_cell_rescue=bool(args.learned_export_non_loftr_weak_cell_rescue),
                    weak_cell_max_count=int(args.learned_export_weak_cell_max_count),
                    weak_cell_min_candidates=int(args.learned_export_weak_cell_min_candidates),
                    weak_cell_max_occupancy=int(args.learned_export_weak_cell_max_occupancy),
                    weak_cell_min_classical_motion_px=float(
                        args.learned_export_weak_cell_min_classical_motion_px
                    ),
                    weak_cell_max_classical_grid=float(args.learned_export_weak_cell_max_classical_grid),
                    weak_cell_max_classical_tracks=int(args.learned_export_weak_cell_max_classical_tracks),
                    mature_cell_rescue=bool(args.learned_export_mature_cell_rescue),
                    mature_cell_max_count=int(args.learned_export_mature_cell_max_count),
                    mature_cell_min_candidates=int(args.learned_export_mature_cell_min_candidates),
                    mature_cell_min_classical_age=float(args.learned_export_mature_cell_min_classical_age),
                    mature_cell_min_classical_motion_px=float(
                        args.learned_export_mature_cell_min_classical_motion_px
                    ),
                    mature_cell_max_classical_grid=float(args.learned_export_mature_cell_max_classical_grid),
                    mature_cell_max_per_cell=int(args.learned_export_mature_cell_max_per_cell),
                    mature_cell_max_occupancy=int(args.learned_export_mature_cell_max_occupancy),
                    loftr_planar_rescue=bool(args.learned_export_loftr_planar_rescue),
                    loftr_planar_max_count=int(args.learned_export_loftr_planar_max_count),
                    loftr_planar_min_candidates=int(args.learned_export_loftr_planar_min_candidates),
                    loftr_planar_max_classical_grid=float(args.learned_export_loftr_planar_max_classical_grid),
                    loftr_planar_min_classical_motion_px=float(
                        args.learned_export_loftr_planar_min_classical_motion_px
                    ),
                    loftr_weak_cell_rescue=bool(args.learned_export_loftr_weak_cell_rescue),
                    loftr_weak_cell_max_count=int(args.learned_export_loftr_weak_cell_max_count),
                    loftr_weak_cell_max_occupancy=int(args.learned_export_loftr_weak_cell_max_occupancy),
                    loftr_rescue_max_classical_tracks=int(
                        args.learned_export_loftr_rescue_max_classical_tracks
                    ),
                )
            if args.vins_safe_source_selection and defer_vins_safe_selection:
                max_total = args.vins_safe_max_total
                if max_total is None:
                    max_total = (
                        int(args.export_max_features)
                        if args.export_max_features is not None
                        else len(export_tracks)
                    )
                export_tracks = _select_vins_safe_sources(
                    export_tracks,
                    emitted_frame_index=selected_feature_index,
                    image_shape=gray.shape,
                    warmup_frames=int(args.vins_safe_warmup_frames),
                    max_total=int(max_total),
                    max_learned=int(args.vins_safe_max_learned),
                    max_recovered=int(args.vins_safe_max_recovered),
                    min_learned_age=int(args.vins_safe_min_learned_age),
                    preserve_classical_budget=bool(
                        args.vins_safe_preserve_classical_budget
                    ),
                    allow_warmup_confirmed_loftr=False,
                    warmup_confirmed_loftr_max_count=0,
                    init_sidecar_support_selection=False,
                    init_sidecar_support_count=0,
                )
            feature_frames.append(_tracks_points_by_id(export_tracks))
            selected_feature_index += 1
            if len(feature_frames) >= probe_frames:
                break

    mean_step_px = _mean_interframe_parallax(feature_frames)
    triggered = math.isfinite(mean_step_px) and mean_step_px < float(args.init_parallax_threshold_px)
    skip_frames = 0
    if triggered:
        skip_frames = int(args.init_parallax_skip_feature_frames)
        if bool(args.init_parallax_adaptive_skip):
            moderate_low_parallax = (
                math.isfinite(mean_step_px)
                and float(args.init_parallax_adaptive_min_px)
                <= float(mean_step_px)
                < float(args.init_parallax_adaptive_max_px)
            )
            if moderate_low_parallax:
                skip_frames = max(skip_frames, int(args.init_parallax_adaptive_skip_frames))
    return _InitParallaxGateState(
        enabled=True,
        triggered=bool(triggered),
        mean_step_px=float(mean_step_px),
        skip_feature_frames=max(0, skip_frames),
    )


def _tracks_points_by_id(tracks: TrackSet) -> dict[int, tuple[float, float]]:
    points: dict[int, tuple[float, float]] = {}
    for track_id, point in zip(tracks.ids, tracks.points):
        points[int(track_id)] = (float(point[0]), float(point[1]))
    return points


def _low_parallax_learned_holdoff_until(
    args: argparse.Namespace,
    init_gate: _InitParallaxGateState,
) -> int:
    if not bool(init_gate.triggered):
        return 0
    return max(0, int(args.vins_init_klt_only_frames)) + max(
        0,
        int(args.low_parallax_learned_holdoff_frames),
    )


def _effective_vins_safe_warmup_frames(
    args: argparse.Namespace,
    init_gate: _InitParallaxGateState,
    low_parallax_holdoff_until: int,
) -> int:
    warmup = max(0, int(args.vins_safe_warmup_frames))
    if bool(init_gate.triggered):
        warmup = max(warmup, max(0, int(low_parallax_holdoff_until)))
    return warmup


def _mean_interframe_parallax(frames: list[dict[int, tuple[float, float]]]) -> float:
    steps: list[float] = []
    for prev, cur in zip(frames, frames[1:]):
        common = set(prev).intersection(cur)
        if not common:
            continue
        disp = [
            math.hypot(cur[fid][0] - prev[fid][0], cur[fid][1] - prev[fid][1])
            for fid in common
        ]
        if disp:
            steps.append(float(np.mean(np.asarray(disp, dtype=np.float32))))
    if not steps:
        return float("nan")
    return float(np.mean(np.asarray(steps, dtype=np.float32)))


def _load_pinhole_camera(path: Path) -> dict:
    text = "\n".join(
        line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("%YAML:")
    )
    data = yaml.safe_load(text) or {}
    if "cam0" in data:
        data = data["cam0"]
    if str(data.get("distortion_model", "")).lower() in {"equidistant", "fisheye"}:
        fx, fy, cx, cy = [float(v) for v in data["intrinsics"]]
        coeffs = [float(v) for v in data.get("distortion_coeffs", [0.0, 0.0, 0.0, 0.0])]
        return {
            "model": "fisheye",
            "K": np.array([[fx, 0.0, cx], [0.0, fy, cy], [0.0, 0.0, 1.0]], dtype=np.float64),
            "D": np.array(coeffs[:4], dtype=np.float64),
        }
    if str(data.get("model_type", "")).upper() in {"KANNALA_BRANDT", "EQUIDISTANT"}:
        proj = data.get("projection_parameters", {})
        return {
            "model": "fisheye",
            "K": np.array(
                [
                    [float(proj["mu"]), 0.0, float(proj["u0"])],
                    [0.0, float(proj["mv"]), float(proj["v0"])],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            ),
            "D": np.array(
                [
                    float(proj.get("k2", 0.0)),
                    float(proj.get("k3", 0.0)),
                    float(proj.get("k4", 0.0)),
                    float(proj.get("k5", 0.0)),
                ],
                dtype=np.float64,
            ),
        }
    proj = data.get("projection_parameters", {})
    dist = data.get("distortion_parameters", {})
    k_mat = np.array(
        [
            [float(proj["fx"]), 0.0, float(proj["cx"])],
            [0.0, float(proj["fy"]), float(proj["cy"])],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )
    d_vec = np.array(
        [
            float(dist.get("k1", 0.0)),
            float(dist.get("k2", 0.0)),
            float(dist.get("p1", 0.0)),
            float(dist.get("p2", 0.0)),
        ],
        dtype=np.float64,
    )
    return {"model": "pinhole", "K": k_mat, "D": d_vec}


def _image_msg_to_gray(bridge: CvBridge, msg) -> np.ndarray:
    if getattr(msg, "_type", "") == "sensor_msgs/CompressedImage":
        image = bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="mono8")
        return np.asarray(image, dtype=np.uint8)
    image = bridge.imgmsg_to_cv2(msg, desired_encoding="mono8")
    return np.asarray(image, dtype=np.uint8)


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


def _select_feature_stamp(msg, bag_stamp, source: str, max_header_delta: float, invalid_policy: str):
    header_stamp = msg.header.stamp if msg.header.stamp.to_sec() > 0.0 else bag_stamp
    invalid = False
    if max_header_delta > 0.0:
        invalid = abs(float(bag_stamp.to_sec()) - float(header_stamp.to_sec())) > float(max_header_delta)
    if invalid and invalid_policy == "use_bag":
        return bag_stamp, True
    if source == "bag":
        return bag_stamp, invalid
    return header_stamp, invalid


def _tracks_to_vins_pointcloud(
    tracks: TrackSet,
    stamp,
    camera: dict,
    dt: float | None,
    zero_velocity: bool = False,
    raw_quality: bool = False,
    constant_quality: bool = False,
    backend_quality_mode: str = "default",
    backend_quality_floor: float | None = None,
    backend_quality_alpha: float = 0.85,
    learned_quality_scale: float = 1.0,
    sp_lg_quality_scale: float = 1.0,
    xfeat_quality_scale: float = 1.0,
    loftr_quality_scale: float = 1.0,
    learned_quality_const: float | None = None,
    sp_lg_quality_const: float | None = None,
    xfeat_quality_const: float | None = None,
    loftr_quality_const: float | None = None,
    low_parallax_quality_boost: bool = False,
    state_adaptive_active: bool = False,
    init_sidecar_support_active: bool = False,
    init_sidecar_classical_quality_floor: float = 0.0,
) -> PointCloud:
    msg = PointCloud()
    msg.header.stamp = stamp
    msg.header.frame_id = "world"
    channel_names = [
        "id",
        "camera_id",
        "p_u",
        "p_v",
        "velocity_x",
        "velocity_y",
        "gx",
        "gy",
        "gz",
        "quality",
        "sigma",
        "source_code",
        "is_learned",
    ]
    msg.channels = [ChannelFloat32(name=name) for name in channel_names]
    tracks = _deduplicate_tracks_for_vins(tracks)
    if len(tracks) == 0:
        return msg

    cur_norm = _pixels_to_normalized(tracks.points, camera)
    prev_norm = _pixels_to_normalized(tracks.prev_points, camera)
    if zero_velocity or dt is None:
        velocity = np.zeros_like(cur_norm)
    else:
        velocity = (cur_norm - prev_norm) / float(dt)
    backend_quality = _backend_reliability(
        tracks,
        raw_quality=raw_quality,
        constant_quality=constant_quality,
        mode=backend_quality_mode,
        floor=backend_quality_floor,
        alpha=backend_quality_alpha,
        learned_quality_scale=learned_quality_scale,
        sp_lg_quality_scale=sp_lg_quality_scale,
        xfeat_quality_scale=xfeat_quality_scale,
        loftr_quality_scale=loftr_quality_scale,
        learned_quality_const=learned_quality_const,
        sp_lg_quality_const=sp_lg_quality_const,
        xfeat_quality_const=xfeat_quality_const,
        loftr_quality_const=loftr_quality_const,
        low_parallax_quality_boost=low_parallax_quality_boost,
        state_adaptive_active=state_adaptive_active,
        init_sidecar_support_active=init_sidecar_support_active,
        init_sidecar_classical_quality_floor=init_sidecar_classical_quality_floor,
    )

    for idx in range(len(tracks)):
        msg.points.append(Point32(float(cur_norm[idx, 0]), float(cur_norm[idx, 1]), 1.0))
        q_backend = float(backend_quality[idx])
        values = [
            float(int(tracks.ids[idx])),
            0.0,
            float(tracks.points[idx, 0]),
            float(tracks.points[idx, 1]),
            float(velocity[idx, 0]),
            float(velocity[idx, 1]),
            0.0,
            0.0,
            0.0,
            q_backend,
            float(1.0 / np.sqrt(max(0.05, q_backend))),
            float(_source_code(tracks.sources[idx])),
            1.0 if _is_learned_source(tracks.sources[idx]) else 0.0,
        ]
        for channel, value in zip(msg.channels, values):
            channel.values.append(value)
    return msg


def _backend_reliability(
    tracks: TrackSet,
    raw_quality: bool = False,
    constant_quality: bool = False,
    mode: str = "default",
    floor: float | None = None,
    alpha: float = 0.85,
    learned_quality_scale: float = 1.0,
    sp_lg_quality_scale: float = 1.0,
    xfeat_quality_scale: float = 1.0,
    loftr_quality_scale: float = 1.0,
    learned_quality_const: float | None = None,
    sp_lg_quality_const: float | None = None,
    xfeat_quality_const: float | None = None,
    loftr_quality_const: float | None = None,
    low_parallax_quality_boost: bool = False,
    state_adaptive_active: bool = False,
    init_sidecar_support_active: bool = False,
    init_sidecar_classical_quality_floor: float = 0.0,
) -> np.ndarray:
    if len(tracks) == 0:
        return np.empty((0,), dtype=np.float32)
    if floor is None and mode in {"floor", "source_aware"}:
        floor = 0.80
    if constant_quality or mode == "const":
        return np.ones((len(tracks),), dtype=np.float32)
    raw_q = np.clip(tracks.qualities.astype(np.float32), 0.05, 1.0)
    if raw_quality or mode == "raw":
        return _apply_backend_quality_floor(raw_q, floor)
    if mode == "floor":
        return _apply_backend_quality_floor(raw_q, floor)
    if mode == "blend":
        blended = _blend_backend_quality(raw_q, alpha)
        return _apply_backend_quality_floor(blended, floor)

    ages = np.maximum(0.0, tracks.ages.astype(np.float32))
    age_gain = 0.70 + 0.30 * np.clip(ages / 8.0, 0.0, 1.0)
    fb = np.maximum(0.0, tracks.fb_errors.astype(np.float32))
    fb_gain = np.exp(-fb / 3.0).astype(np.float32)
    fb_gain = np.clip(0.65 + 0.35 * fb_gain, 0.65, 1.0)
    ncc = np.clip((tracks.ncc_scores.astype(np.float32) + 1.0) * 0.5, 0.0, 1.0)
    ncc_gain = np.clip(0.75 + 0.25 * ncc, 0.75, 1.0)

    source_gain = np.asarray([_backend_source_reliability(source) for source in tracks.sources], dtype=np.float32)
    quality_gain = 0.85 + 0.15 * raw_q
    reliability = source_gain * age_gain * fb_gain * ncc_gain * quality_gain
    if mode == "source_aware":
        reliability = _source_aware_backend_reliability(tracks, raw_q, reliability, alpha)
        reliability = _apply_backend_sidecar_quality_scale(
            reliability,
            tracks.sources,
            learned_scale=learned_quality_scale,
            sp_lg_scale=sp_lg_quality_scale,
            xfeat_scale=xfeat_quality_scale,
            loftr_scale=loftr_quality_scale,
            learned_const=learned_quality_const,
            sp_lg_const=sp_lg_quality_const,
            xfeat_const=xfeat_quality_const,
            loftr_const=loftr_quality_const,
        )
        reliability = _apply_init_sidecar_classical_floor(
            reliability,
            tracks,
            active=init_sidecar_support_active,
            floor=init_sidecar_classical_quality_floor,
        )
        return _apply_backend_quality_floor(reliability, floor)
    if mode == "vins_safe":
        reliability = _vins_safe_backend_reliability(
            tracks,
            raw_q,
            reliability,
            alpha,
            low_parallax_quality_boost=low_parallax_quality_boost,
            state_adaptive_active=state_adaptive_active or init_sidecar_support_active,
        )
        reliability = _apply_backend_sidecar_quality_scale(
            reliability,
            tracks.sources,
            learned_scale=learned_quality_scale,
            sp_lg_scale=sp_lg_quality_scale,
            xfeat_scale=xfeat_quality_scale,
            loftr_scale=loftr_quality_scale,
            learned_const=learned_quality_const,
            sp_lg_const=sp_lg_quality_const,
            xfeat_const=xfeat_quality_const,
            loftr_const=loftr_quality_const,
        )
        reliability = _apply_init_sidecar_classical_floor(
            reliability,
            tracks,
            active=init_sidecar_support_active,
            floor=init_sidecar_classical_quality_floor,
        )
        return _apply_backend_quality_floor(reliability, floor)
    if mode == "sidecar_only":
        reliability = _sidecar_only_backend_reliability(
            tracks,
            raw_q,
            reliability,
            alpha,
            low_parallax_quality_boost=low_parallax_quality_boost,
            state_adaptive_active=state_adaptive_active or init_sidecar_support_active,
        )
        reliability = _apply_backend_sidecar_quality_scale(
            reliability,
            tracks.sources,
            learned_scale=learned_quality_scale,
            sp_lg_scale=sp_lg_quality_scale,
            xfeat_scale=xfeat_quality_scale,
            loftr_scale=loftr_quality_scale,
            learned_const=learned_quality_const,
            sp_lg_const=sp_lg_quality_const,
            xfeat_const=xfeat_quality_const,
            loftr_const=loftr_quality_const,
        )
        reliability = _apply_init_sidecar_classical_floor(
            reliability,
            tracks,
            active=init_sidecar_support_active,
            floor=init_sidecar_classical_quality_floor,
        )
        return _apply_backend_quality_floor(reliability, floor)
    if mode == "state_adaptive":
        reliability = _state_adaptive_backend_reliability(
            tracks,
            raw_q,
            reliability,
            alpha,
            recovery_active=state_adaptive_active,
            low_parallax_quality_boost=low_parallax_quality_boost,
            init_sidecar_support_active=init_sidecar_support_active,
        )
        reliability = _apply_backend_sidecar_quality_scale(
            reliability,
            tracks.sources,
            learned_scale=learned_quality_scale,
            sp_lg_scale=sp_lg_quality_scale,
            xfeat_scale=xfeat_quality_scale,
            loftr_scale=loftr_quality_scale,
            learned_const=learned_quality_const,
            sp_lg_const=sp_lg_quality_const,
            xfeat_const=xfeat_quality_const,
            loftr_const=loftr_quality_const,
        )
        reliability = _apply_init_sidecar_classical_floor(
            reliability,
            tracks,
            active=init_sidecar_support_active,
            floor=init_sidecar_classical_quality_floor,
        )
        return _apply_backend_quality_floor(reliability, floor)
    if mode != "default":
        raise ValueError(f"unsupported backend quality mode: {mode}")
    reliability = np.clip(reliability, 0.30, 1.0).astype(np.float32)
    reliability = _apply_backend_sidecar_quality_scale(
        reliability,
        tracks.sources,
        learned_scale=learned_quality_scale,
        sp_lg_scale=sp_lg_quality_scale,
        xfeat_scale=xfeat_quality_scale,
        loftr_scale=loftr_quality_scale,
        learned_const=learned_quality_const,
        sp_lg_const=sp_lg_quality_const,
        xfeat_const=xfeat_quality_const,
        loftr_const=loftr_quality_const,
    )
    reliability = _apply_init_sidecar_classical_floor(
        reliability,
        tracks,
        active=init_sidecar_support_active,
        floor=init_sidecar_classical_quality_floor,
    )
    return _apply_backend_quality_floor(reliability, floor)


def _apply_init_sidecar_classical_floor(
    quality: np.ndarray,
    tracks: TrackSet,
    *,
    active: bool,
    floor: float,
) -> np.ndarray:
    out = np.asarray(quality, dtype=np.float32).copy()
    if len(out) == 0 or not bool(active) or float(floor) <= 0.0:
        return out
    classical = _classical_backbone_mask(tracks)
    if np.any(classical):
        out[classical] = np.maximum(out[classical], float(floor))
    return np.clip(out, 0.05, 1.0).astype(np.float32)


def _apply_backend_sidecar_quality_scale(
    quality: np.ndarray,
    sources: list[str],
    learned_scale: float = 1.0,
    sp_lg_scale: float = 1.0,
    xfeat_scale: float = 1.0,
    loftr_scale: float = 1.0,
    learned_const: float | None = None,
    sp_lg_const: float | None = None,
    xfeat_const: float | None = None,
    loftr_const: float | None = None,
) -> np.ndarray:
    out = np.asarray(quality, dtype=np.float32).copy()
    if len(out) == 0:
        return out
    generic = float(np.clip(learned_scale, 0.05, 1.5))
    sp_lg = float(np.clip(sp_lg_scale, 0.05, 1.5))
    xfeat = float(np.clip(xfeat_scale, 0.05, 1.5))
    loftr = float(np.clip(loftr_scale, 0.05, 1.5))
    generic_const = _optional_backend_quality_const(learned_const)
    sp_lg_const_value = _optional_backend_quality_const(sp_lg_const)
    xfeat_const_value = _optional_backend_quality_const(xfeat_const)
    loftr_const_value = _optional_backend_quality_const(loftr_const)
    for idx, source in enumerate(sources):
        name = str(source).lower()
        const_value = None
        scale = 1.0
        if _is_learned_source(name):
            scale *= generic
        if "loftr" in name:
            scale *= loftr
            const_value = loftr_const_value
        elif "xfeat" in name:
            scale *= xfeat
            const_value = xfeat_const_value
        elif "superpoint" in name or "lightglue" in name or "learned" in name or "semidense" in name:
            scale *= sp_lg
            const_value = sp_lg_const_value
        if const_value is None and _is_learned_source(name):
            const_value = generic_const
        out[idx] = const_value if const_value is not None else float(out[idx]) * scale
    return np.clip(out, 0.05, 1.0).astype(np.float32)


def _optional_backend_quality_const(value: float | None) -> float | None:
    if value is None:
        return None
    return float(np.clip(float(value), 0.05, 1.0))


def _blend_backend_quality(raw_q: np.ndarray, alpha: float) -> np.ndarray:
    a = float(np.clip(alpha, 0.0, 1.0))
    return np.clip(a + (1.0 - a) * raw_q, 0.05, 1.0).astype(np.float32)


def _apply_backend_quality_floor(q: np.ndarray, floor: float | None) -> np.ndarray:
    q = np.clip(q.astype(np.float32), 0.05, 1.0)
    if floor is None:
        return q
    return np.clip(np.maximum(q, float(floor)), 0.05, 1.0).astype(np.float32)


def _resolve_xfeat_risk_quality_const(
    args: argparse.Namespace,
    tracks: TrackSet,
    *,
    state: _XFeatRiskQualitySchedulerState,
    skip_frame: bool,
    low_parallax_active: bool,
) -> tuple[float | None, bool]:
    base_const = args.backend_xfeat_quality_const
    if not bool(args.backend_xfeat_risk_quality_scheduler):
        return base_const, False

    xfeat_count = 0 if skip_frame else _count_sources(tracks, _is_xfeat_source)
    if xfeat_count <= 0:
        return base_const, False

    state.learned_frames += 1
    state.cumulative_gftt += _count_sources(tracks, _is_gftt_source)
    if state.cumulative_gftt >= int(args.backend_xfeat_risk_latch_gftt_total):
        state.latched = True

    in_probation = state.learned_frames <= max(
        0,
        int(args.backend_xfeat_risk_probation_learned_frames),
    )
    active = bool(in_probation or state.latched)
    if not active:
        return base_const, False
    if state.latched:
        return float(args.backend_xfeat_risk_quality_const), True
    probation_const = args.backend_xfeat_risk_probation_quality_const
    if (
        probation_const is not None
        and bool(args.backend_xfeat_risk_probation_quality_requires_low_parallax)
        and not bool(low_parallax_active)
    ):
        probation_const = None
    if probation_const is None:
        probation_const = args.backend_xfeat_risk_quality_const
    return float(probation_const), True


def _is_gftt_source(source: str) -> bool:
    return "gftt" in str(source).lower()


def _source_aware_backend_reliability(
    tracks: TrackSet,
    raw_q: np.ndarray,
    default_reliability: np.ndarray,
    alpha: float,
) -> np.ndarray:
    values = default_reliability.astype(np.float32).copy()
    blended_q = _blend_backend_quality(raw_q, alpha)
    for idx, source in enumerate(tracks.sources):
        name = str(source).lower()
        age = float(tracks.ages[idx])
        base = float(blended_q[idx])
        if "loftr" in name:
            ceiling = 0.92 if age >= 3 else 0.82
            floor = 0.68 if age < 2 else 0.78
            values[idx] = min(ceiling, max(floor, 0.65 + 0.25 * base + 0.03 * min(age, 4.0)))
        elif "xfeat" in name:
            ceiling = 0.94 if "confirmed" in name or age >= 3 else 0.88
            floor = 0.72 if age < 2 else 0.80
            values[idx] = min(ceiling, max(floor, 0.72 + 0.20 * base + 0.02 * min(age, 4.0)))
        elif "superpoint" in name or "lightglue" in name or "learned" in name:
            ceiling = 0.96 if "confirmed" in name or age >= 3 else 0.90
            floor = 0.76 if age < 2 else 0.84
            values[idx] = min(ceiling, max(floor, 0.76 + 0.18 * base + 0.02 * min(age, 4.0)))
        elif name in {"klt", "gftt_confirmed", "homography_recovery"}:
            values[idx] = max(values[idx], min(1.0, 0.94 + 0.06 * base))
        elif name in {"gftt", "gftt_seed", "lk_recovery"}:
            values[idx] = max(values[idx], min(0.98, 0.92 + 0.05 * base))
    return values.astype(np.float32)


def _vins_safe_backend_reliability(
    tracks: TrackSet,
    raw_q: np.ndarray,
    default_reliability: np.ndarray,
    alpha: float,
    low_parallax_quality_boost: bool = False,
    state_adaptive_active: bool = False,
) -> np.ndarray:
    values = np.clip(default_reliability.astype(np.float32), 0.35, 1.0)
    blended_q = _blend_backend_quality(raw_q, alpha)
    for idx, source in enumerate(tracks.sources):
        name = str(source).lower()
        age = float(tracks.ages[idx])
        base = float(blended_q[idx])
        age_boost = min(age, 6.0) / 6.0
        if name in {"klt", "gftt_confirmed", "homography_recovery"}:
            # Keep the empirically useful KLT dynamic q. These tracks are the
            # VINS backbone, so a global floor would remove the good H07 gain.
            values[idx] = np.clip(values[idx], 0.42, 1.0)
            if state_adaptive_active:
                values[idx] = max(float(values[idx]), min(0.92, 0.84 + 0.06 * base))
            if low_parallax_quality_boost:
                values[idx] = max(float(values[idx]), min(1.0, 0.94 + 0.06 * base))
        elif name in {"gftt", "gftt_seed", "lk_recovery"}:
            values[idx] = max(float(values[idx]), min(0.96, 0.70 + 0.18 * base + 0.06 * age_boost))
            if state_adaptive_active:
                values[idx] = max(float(values[idx]), min(0.92, 0.84 + 0.06 * base))
            if low_parallax_quality_boost:
                values[idx] = max(float(values[idx]), min(0.98, 0.90 + 0.06 * base))
        elif "loftr" in name:
            floor = 0.76 if _is_confirmed_sidecar_source(name) or age >= 4 else 0.68
            ceiling = 0.90 if _is_confirmed_sidecar_source(name) or age >= 4 else 0.82
            if state_adaptive_active and (_is_confirmed_sidecar_source(name) or age >= 1):
                floor = max(floor, 0.80)
                ceiling = max(ceiling, 0.90)
            values[idx] = min(ceiling, max(floor, 0.64 + 0.20 * base + 0.06 * age_boost))
        elif "xfeat" in name:
            floor = 0.78 if _is_confirmed_sidecar_source(name) or age >= 3 else 0.70
            ceiling = 0.92 if _is_confirmed_sidecar_source(name) or age >= 3 else 0.86
            values[idx] = min(ceiling, max(floor, 0.68 + 0.20 * base + 0.06 * age_boost))
        elif "superpoint" in name or "lightglue" in name or "learned" in name or "semidense" in name:
            floor = 0.80 if _is_confirmed_sidecar_source(name) or age >= 3 else 0.72
            ceiling = 0.94 if _is_confirmed_sidecar_source(name) or age >= 3 else 0.88
            values[idx] = min(ceiling, max(floor, 0.70 + 0.20 * base + 0.06 * age_boost))
        elif "orb" in name:
            values[idx] = max(float(values[idx]), 0.72)
    return np.clip(values, 0.35, 1.0).astype(np.float32)


def _state_adaptive_quality_active(
    gate_info: _LearnedExportGateInfo,
    tracks: TrackSet,
    init_klt_only_active: bool = False,
    low_parallax_sidecar_block_active: bool = False,
) -> bool:
    if bool(low_parallax_sidecar_block_active):
        return False
    if len(tracks) == 0 or not _has_sidecar_source(tracks):
        return False
    if not bool(gate_info.active) or not bool(gate_info.degraded):
        return False
    reason = f"{gate_info.reason} {gate_info.benefit_reason}".lower()
    positive_tokens = (
        "low_classical",
        "frontend_low",
        "frontend_dropout",
        "frontend_degraded",
        "frontend_texture",
        "frontend_planar",
        "frontend_extreme",
        "accepted",
        "support_rescue",
        "weak",
        "planar",
        "new_cell",
        "grid_gain",
    )
    return any(token in reason for token in positive_tokens)


def _sidecar_only_backend_reliability(
    tracks: TrackSet,
    raw_q: np.ndarray,
    default_reliability: np.ndarray,
    alpha: float,
    low_parallax_quality_boost: bool = False,
    state_adaptive_active: bool = False,
) -> np.ndarray:
    """Keep the stable classical backbone at unit weight; calibrate sidecars only."""

    values = np.ones((len(tracks),), dtype=np.float32)
    if len(tracks) == 0:
        return values
    sidecar_values = _vins_safe_backend_reliability(
        tracks,
        raw_q,
        default_reliability,
        alpha,
        low_parallax_quality_boost=low_parallax_quality_boost,
        state_adaptive_active=state_adaptive_active,
    )
    for idx, source in enumerate(tracks.sources):
        if _is_learned_source(source):
            values[idx] = float(sidecar_values[idx])
    return np.clip(values, 0.35, 1.0).astype(np.float32)


def _state_adaptive_backend_reliability(
    tracks: TrackSet,
    raw_q: np.ndarray,
    default_reliability: np.ndarray,
    alpha: float,
    recovery_active: bool = False,
    low_parallax_quality_boost: bool = False,
    init_sidecar_support_active: bool = False,
) -> np.ndarray:
    """Backend q schedule for learned sidecar recovery.

    The KLT/GFTT backbone is kept at unit information in normal operation.
    Only confirmed learned/LoFTR sidecars are source-calibrated. During an
    accepted low-texture recovery frame, classical recovery births get a mild
    quality blend, but mature KLT observations remain strong.
    """

    values = np.ones((len(tracks),), dtype=np.float32)
    if len(tracks) == 0:
        return values
    sidecar_values = _vins_safe_backend_reliability(
        tracks,
        raw_q,
        default_reliability,
        alpha,
        low_parallax_quality_boost=low_parallax_quality_boost,
        state_adaptive_active=recovery_active or init_sidecar_support_active,
    )
    blended_q = _blend_backend_quality(raw_q, alpha)
    for idx, source in enumerate(tracks.sources):
        name = str(source).lower()
        age = float(tracks.ages[idx])
        if _is_learned_source(name):
            values[idx] = float(sidecar_values[idx])
            continue
        if name in {"gftt", "gftt_seed", "lk_recovery"}:
            if recovery_active:
                values[idx] = max(0.88, min(0.99, 0.90 + 0.08 * float(blended_q[idx])))
            else:
                values[idx] = 0.98
            continue
        if name == "homography_recovery":
            values[idx] = 0.98 if not recovery_active else max(0.92, min(1.0, float(blended_q[idx])))
            continue
        if "orb" in name:
            values[idx] = 0.92
            continue
        # Mature KLT/GFTT-confirmed tracks anchor VINS. During a verified
        # recovery burst, use the same mild blend that worked in A06 q-only
        # ablations, but never let the classical backbone fall below a high
        # floor; otherwise return to unit information.
        if recovery_active or init_sidecar_support_active:
            values[idx] = max(0.88, min(1.0, float(blended_q[idx])))
        else:
            values[idx] = 1.0
    return np.clip(values, 0.35, 1.0).astype(np.float32)


def _backend_source_reliability(source: str) -> float:
    name = str(source).lower()
    if name in {"klt", "gftt_confirmed", "homography_recovery"}:
        return 1.00
    if name in {"gftt", "gftt_seed", "lk_recovery"}:
        return 0.96
    if "superpoint" in name or "lightglue" in name:
        return 0.90 if "confirmed" in name else 0.78
    if "xfeat" in name:
        return 0.84 if "confirmed" in name else 0.70
    if "loftr" in name:
        return 0.72 if "confirmed" in name else 0.55
    if "orb" in name:
        return 0.82
    if "learned" in name or "semidense" in name:
        return 0.76 if "confirmed" in name else 0.62
    return 0.90


def _deduplicate_tracks_for_vins(tracks: TrackSet) -> TrackSet:
    """Keep one mono observation per feature id.

    VINS-Fusion interprets repeated feature ids in one PointCloud as stereo
    observations. Our frontend is monocular, so per-frame duplicate ids must be
    collapsed before publishing.
    """
    if len(tracks) <= 1:
        return tracks
    best: dict[int, int] = {}
    for idx, track_id in enumerate(tracks.ids):
        key = int(track_id)
        prev = best.get(key)
        if prev is None:
            best[key] = idx
            continue
        prev_score = (int(tracks.ages[prev]), float(tracks.qualities[prev]))
        cur_score = (int(tracks.ages[idx]), float(tracks.qualities[idx]))
        if cur_score > prev_score:
            best[key] = idx
    # Keep VINS input deterministic.  Two policies can choose the same feature
    # set in a different order, and short low-parallax VIO windows are
    # surprisingly sensitive to that ordering during initialization.
    keep = np.array(list(best.values()), dtype=np.int64)
    keep = keep[np.argsort(tracks.ids[keep], kind="mergesort")]
    return TrackSet(
        ids=tracks.ids[keep],
        prev_points=tracks.prev_points[keep],
        points=tracks.points[keep],
        ages=tracks.ages[keep],
        fb_errors=tracks.fb_errors[keep],
        ncc_scores=tracks.ncc_scores[keep],
        local_texture=tracks.local_texture[keep],
        qualities=tracks.qualities[keep],
        sources=[tracks.sources[int(idx)] for idx in keep],
    )


def _select_vins_safe_sources(
    tracks: TrackSet,
    emitted_frame_index: int,
    image_shape: tuple[int, int] | None,
    warmup_frames: int,
    max_total: int,
    max_learned: int,
    max_recovered: int,
    min_learned_age: int,
    preserve_classical_budget: bool = False,
    classical_prefer_age: bool = True,
    classical_prefer_klt: bool = False,
    exact_cap_selection: bool = False,
    sidecar_low_cap_total: int | None = None,
    force_low_cap: bool = False,
    allow_warmup_confirmed_loftr: bool = False,
    warmup_confirmed_loftr_max_count: int = 0,
    init_sidecar_support_selection: bool = False,
    init_sidecar_support_count: int = 2,
    init_sidecar_selection_quality_floor: float = 0.0,
) -> TrackSet:
    if len(tracks) == 0:
        return tracks
    max_total = max(1, int(max_total))
    if (
        sidecar_low_cap_total is not None
        and int(sidecar_low_cap_total) > 0
        and _has_sidecar_source(tracks)
        and (bool(force_low_cap) or _has_learned_source(tracks))
    ):
        max_total = min(max_total, max(1, int(sidecar_low_cap_total)))
    if len(tracks) <= max_total and not _has_sidecar_source(tracks):
        return tracks

    indices = np.arange(len(tracks), dtype=np.int64)
    classical = np.asarray(
        [
            (not _is_learned_source(source)) and (not _is_recovered_source(source))
            for source in tracks.sources
        ],
        dtype=bool,
    )
    recovered = np.asarray(
        [
            _is_recovered_source(source) and not _is_learned_source(source)
            for source in tracks.sources
        ],
        dtype=bool,
    )
    learned = np.asarray([_is_learned_source(source) for source in tracks.sources], dtype=bool)

    keep: list[int] = []
    reserved_sidecar: list[int] = []
    warmup_active = int(emitted_frame_index) < max(0, int(warmup_frames))
    if bool(exact_cap_selection):
        learned_budget = 0 if warmup_active else max(0, int(max_learned))
        return _select_vins_safe_exact_cap_sources(
            tracks,
            max_total=max_total,
            max_learned=learned_budget,
            classical_prefer_age=bool(classical_prefer_age),
            classical_prefer_klt=bool(classical_prefer_klt),
        )
    if not warmup_active:
        sidecar_budget = max(0, int(max_learned)) + max(0, int(max_recovered))
        if sidecar_budget > 0:
            recovered_ready = recovered
            learned_age_threshold = np.full(
                (len(tracks),),
                max(1, int(min_learned_age)),
                dtype=np.int32,
            )
            confirmed_learned = np.asarray(
                [
                    _is_learned_source(source) and _is_confirmed_sidecar_source(source)
                    for source in tracks.sources
                ],
                dtype=bool,
            )
            # Confirmed sidecar labels are assigned only after the learned match
            # has already survived LK/NCC/FB promotion checks. Some exporters
            # reset the TrackSet age at that promotion, so keep raw learned
            # sidecars strict while letting confirmed sidecars use one export
            # frame of age.
            learned_age_threshold[confirmed_learned] = 1
            learned_ready = learned & (tracks.ages >= learned_age_threshold)
            sidecar_candidates = indices[learned_ready | recovered_ready]
            sidecar_order = _source_selection_order(tracks, sidecar_candidates, prefer_age=False)
            reserved_sidecar = [int(idx) for idx in sidecar_order[:sidecar_budget]]
    elif bool(allow_warmup_confirmed_loftr):
        loftr_budget = min(
            max(0, int(warmup_confirmed_loftr_max_count)),
            max(0, int(max_learned)),
        )
        if loftr_budget > 0:
            confirmed_loftr_ready = np.asarray(
                [
                    _is_loftr_source(source)
                    and _is_confirmed_sidecar_source(source)
                    and _is_learned_source(source)
                    for source in tracks.sources
                ],
                dtype=bool,
            ) & (tracks.ages >= 1)
            sidecar_candidates = indices[confirmed_loftr_ready]
            sidecar_order = _source_selection_order(tracks, sidecar_candidates, prefer_age=False)
            reserved_sidecar = [int(idx) for idx in sidecar_order[:loftr_budget]]
    # In true sidecar mode, max_total protects the KLT/GFTT backbone budget.
    # Learned/LoFTR observations that survive the gates are appended on top of
    # that backbone, instead of reserving slots and displacing stable classical
    # tracks during VINS initialization.
    classical_budget = max_total if bool(preserve_classical_budget) else max_total - len(reserved_sidecar)
    if classical_budget <= 0:
        return _subset_tracks_by_indices(tracks, np.asarray(reserved_sidecar[:max_total], dtype=np.int64))
    init_sidecar_support_active = bool(
        warmup_active
        and allow_warmup_confirmed_loftr
        and bool(reserved_sidecar)
        and bool(init_sidecar_support_selection)
    )
    if np.any(classical):
        if bool(classical_prefer_klt):
            classical_order = _source_selection_order_with_klt_priority(
                tracks,
                indices[classical],
                prefer_age=bool(classical_prefer_age),
            )
            if init_sidecar_support_active and float(init_sidecar_selection_quality_floor) > 0.0:
                classical_order = _source_selection_order_with_quality_floor(
                    tracks,
                    indices[classical],
                    prefer_age=bool(classical_prefer_age),
                    quality_floor=float(init_sidecar_selection_quality_floor),
                )
        else:
            if init_sidecar_support_active and float(init_sidecar_selection_quality_floor) > 0.0:
                classical_order = _source_selection_order_with_quality_floor(
                    tracks,
                    indices[classical],
                    prefer_age=bool(classical_prefer_age),
                    quality_floor=float(init_sidecar_selection_quality_floor),
                )
            else:
                classical_order = _source_selection_order(
                    tracks,
                    indices[classical],
                    prefer_age=bool(classical_prefer_age),
                )
        if init_sidecar_support_active:
            classical_order = _init_sidecar_classical_support_order(
                tracks,
                indices[classical],
                classical_order,
                image_shape=image_shape,
                budget=classical_budget,
                support_count=int(init_sidecar_support_count),
            )
        for idx in classical_order:
            if int(idx) not in keep:
                keep.append(int(idx))
            if len(keep) >= classical_budget:
                break

    for idx in reserved_sidecar:
        if int(idx) not in keep:
            keep.append(int(idx))

    if bool(preserve_classical_budget):
        if not keep:
            return tracks
        return _subset_tracks_by_indices(tracks, np.asarray(keep, dtype=np.int64))

    remaining = max_total - len(keep)
    if remaining <= 0:
        return _subset_tracks_by_indices(tracks, np.asarray(keep[:max_total], dtype=np.int64))

    if int(emitted_frame_index) < max(0, int(warmup_frames)):
        return _subset_tracks_by_indices(tracks, np.asarray(keep, dtype=np.int64))

    if np.any(recovered):
        recovered_budget = min(remaining, max(0, int(max_recovered)))
        recovered_candidates = indices[recovered]
        recovered_order = _source_selection_order(tracks, recovered_candidates, prefer_age=True)
        for idx in recovered_order[:recovered_budget]:
            if int(idx) not in keep:
                keep.append(int(idx))

    remaining = max_total - len(keep)
    if remaining <= 0:
        return _subset_tracks_by_indices(tracks, np.asarray(keep[:max_total], dtype=np.int64))

    if np.any(learned):
        learned_budget = min(remaining, max(0, int(max_learned)))
        learned_age_threshold = np.full(
            (len(tracks),),
            max(1, int(min_learned_age)),
            dtype=np.int32,
        )
        confirmed_learned = np.asarray(
            [
                _is_learned_source(source) and _is_confirmed_sidecar_source(source)
                for source in tracks.sources
            ],
            dtype=bool,
        )
        learned_age_threshold[confirmed_learned] = 1
        learned_candidates = indices[
            learned & (tracks.ages >= learned_age_threshold)
        ]
        learned_order = _source_selection_order(tracks, learned_candidates, prefer_age=False)
        for idx in learned_order[:learned_budget]:
            if int(idx) not in keep:
                keep.append(int(idx))

    if not keep:
        return tracks
    return _subset_tracks_by_indices(tracks, np.asarray(keep[:max_total], dtype=np.int64))


def _select_vins_safe_exact_cap_sources(
    tracks: TrackSet,
    *,
    max_total: int,
    max_learned: int,
    classical_prefer_age: bool = True,
    classical_prefer_klt: bool = False,
) -> TrackSet:
    if len(tracks) == 0:
        return tracks
    tracks = _deduplicate_tracks_for_vins(tracks)
    if len(tracks) == 0:
        return tracks
    max_total = max(1, int(max_total))
    max_learned = max(0, int(max_learned))
    indices = np.arange(len(tracks), dtype=np.int64)
    learned_mask = np.asarray([_is_learned_source(source) for source in tracks.sources], dtype=bool)
    learned_indices = indices[learned_mask]
    classical_indices = indices[~learned_mask]

    def quality_order(items: np.ndarray) -> list[int]:
        if len(items) == 0:
            return []
        return sorted(
            (int(item) for item in items.astype(np.int64)),
            key=lambda idx: (-float(tracks.qualities[idx]), idx),
        )

    selected_learned = quality_order(learned_indices)[: min(max_learned, max_total)]
    remaining = max(0, max_total - len(selected_learned))
    if bool(classical_prefer_klt):
        classical_order = _source_selection_order_with_klt_priority(
            tracks,
            classical_indices,
            prefer_age=bool(classical_prefer_age),
        )
        base_classical_order = _source_selection_order(
            tracks,
            classical_indices,
            prefer_age=bool(classical_prefer_age),
        )
    else:
        classical_order = _source_selection_order(
            tracks,
            classical_indices,
            prefer_age=bool(classical_prefer_age),
        )
        base_classical_order = classical_order
    selected_classical = [int(idx) for idx in classical_order[:remaining]]
    if bool(classical_prefer_klt) and remaining > 0:
        selected_classical = _restore_classical_refill_candidates(
            tracks,
            selected_classical,
            base_classical_order[:remaining],
            max_refill=max(1, remaining // 2),
        )
    selected = selected_learned + selected_classical
    if not selected:
        return TrackSet.empty()

    # Match the offline bag-filter sweep: selection decides membership, but the
    # published PointCloud keeps the original track ordering.
    selected_sorted = np.asarray(sorted(selected), dtype=np.int64)
    return _subset_tracks_by_indices(tracks, selected_sorted)


def _init_sidecar_classical_support_order(
    tracks: TrackSet,
    classical_indices: np.ndarray,
    base_order: np.ndarray,
    *,
    image_shape: tuple[int, int] | None,
    budget: int,
    support_count: int,
) -> np.ndarray:
    """Swap a tiny number of early-init KLT tracks for spatial support.

    In low-texture initialization frames, confirmed LoFTR sidecars can be useful
    only if the remaining classical backbone still constrains VINS geometry.
    Pure quality ranking tends to discard slightly lower-q peripheral KLT tracks;
    this helper makes a small, deterministic swap toward mid-depth/peripheral
    support while keeping the total feature count unchanged.
    """
    if (
        image_shape is None
        or len(base_order) == 0
        or int(budget) <= 0
        or int(support_count) <= 0
    ):
        return base_order
    budget = min(max(0, int(budget)), len(base_order))
    if budget <= 0 or budget >= len(base_order):
        return base_order

    selected = [int(idx) for idx in base_order[:budget]]
    selected_set = set(selected)
    pool = [int(idx) for idx in classical_indices.astype(np.int64) if int(idx) not in selected_set]
    if not pool:
        return base_order

    add_count = min(max(0, int(support_count)), len(pool), len(selected))
    if add_count <= 0:
        return base_order

    support_candidates = _pick_init_sidecar_support_candidates(
        tracks,
        pool,
        image_shape=image_shape,
        count=add_count,
    )
    if not support_candidates:
        return base_order

    removable = _pick_init_sidecar_support_removals(
        tracks,
        selected,
        image_shape=image_shape,
        count=len(support_candidates),
    )
    if not removable:
        return base_order

    updated = selected.copy()
    changed = False
    for add_idx, remove_idx in zip(support_candidates, removable):
        add_score = _init_sidecar_classical_support_score(tracks, add_idx, image_shape)
        remove_score = _init_sidecar_classical_support_score(tracks, remove_idx, image_shape)
        if add_score + 1e-9 < remove_score:
            continue
        try:
            pos = updated.index(int(remove_idx))
        except ValueError:
            continue
        updated[pos] = int(add_idx)
        selected_set.discard(int(remove_idx))
        selected_set.add(int(add_idx))
        changed = True

    if not changed:
        return base_order
    remainder = [int(idx) for idx in base_order.astype(np.int64) if int(idx) not in selected_set]
    return np.asarray(updated + remainder, dtype=np.int64)


def _pick_init_sidecar_support_candidates(
    tracks: TrackSet,
    pool: list[int],
    *,
    image_shape: tuple[int, int],
    count: int,
) -> list[int]:
    if not pool or int(count) <= 0:
        return []
    ordered = sorted(
        (int(idx) for idx in pool),
        key=lambda idx: (
            -_init_sidecar_classical_support_score(tracks, idx, image_shape),
            int(tracks.ids[idx]),
        ),
    )
    chosen: list[int] = []
    chosen_cells: set[tuple[int, int]] = set()
    for idx in ordered:
        cell = _grid_cell_indices(
            tracks.points[np.asarray([idx], dtype=np.int64)],
            image_shape,
            rows=4,
            cols=6,
        )[0]
        cell_key = (int(cell[0]), int(cell[1]))
        if cell_key in chosen_cells and len(chosen_cells) < 6:
            continue
        chosen.append(int(idx))
        chosen_cells.add(cell_key)
        if len(chosen) >= int(count):
            break
    if len(chosen) < int(count):
        for idx in ordered:
            if int(idx) not in chosen:
                chosen.append(int(idx))
            if len(chosen) >= int(count):
                break
    return chosen[: max(0, int(count))]


def _pick_init_sidecar_support_removals(
    tracks: TrackSet,
    selected: list[int],
    *,
    image_shape: tuple[int, int],
    count: int,
) -> list[int]:
    if not selected or int(count) <= 0:
        return []
    # The support swap is allowed to adjust only the low-q tail of the
    # classical backbone. High-q central KLT anchors are often important for
    # VINS initialization even if they are not spatially peripheral.
    selected_ages = tracks.ages[np.asarray(selected, dtype=np.int64)].astype(np.float32)
    finite_ages = selected_ages[np.isfinite(selected_ages)]
    age_guard = float(np.nanmedian(finite_ages)) if len(finite_ages) else float("inf")
    low_q_selected = [
        int(idx)
        for idx in selected
        if float(tracks.qualities[int(idx)]) <= 0.80 + 1e-9
        and float(tracks.ages[int(idx)]) <= age_guard + 1e-9
    ]
    if len(low_q_selected) < int(count):
        low_q_selected = [
            int(idx)
            for idx in selected
            if float(tracks.qualities[int(idx)]) <= 0.80 + 1e-9
        ]
    removal_pool = low_q_selected if len(low_q_selected) >= int(count) else selected
    cells = _grid_cell_indices(
        tracks.points[np.asarray(removal_pool, dtype=np.int64)],
        image_shape,
        rows=4,
        cols=6,
    )
    occupancy: dict[tuple[int, int], int] = {}
    for row, col in cells:
        key = (int(row), int(col))
        occupancy[key] = occupancy.get(key, 0) + 1

    def removal_key(idx: int) -> tuple[float, float, int]:
        cell = _grid_cell_indices(
            tracks.points[np.asarray([idx], dtype=np.int64)],
            image_shape,
            rows=4,
            cols=6,
        )[0]
        crowd = occupancy.get((int(cell[0]), int(cell[1])), 0)
        score = _init_sidecar_classical_support_score(tracks, idx, image_shape)
        q = float(np.clip(tracks.qualities[int(idx)], 0.0, 1.0))
        return (score - 0.015 * float(crowd), q, int(tracks.ids[int(idx)]))

    ordered = sorted((int(idx) for idx in removal_pool), key=removal_key)
    return ordered[: max(0, int(count))]


def _init_sidecar_classical_support_score(
    tracks: TrackSet,
    idx: int,
    image_shape: tuple[int, int],
) -> float:
    h, w = image_shape[:2]
    point = tracks.points[int(idx)].astype(np.float32)
    prev = tracks.prev_points[int(idx)].astype(np.float32)
    x = float(np.clip(point[0] / max(1.0, float(w)), 0.0, 1.0))
    y = float(np.clip(point[1] / max(1.0, float(h)), 0.0, 1.0))
    radial = math.hypot(x - 0.5, y - 0.5) / math.sqrt(0.5)
    # Near-wall A06-style initialization benefits from mid-depth peripheral
    # anchors; very top/bottom points often behave more like detector refill.
    mid_depth = math.exp(-abs(y - 0.66) / 0.22)
    motion = float(np.linalg.norm(point - prev)) / max(1.0, math.hypot(float(w), float(h)))
    motion_score = float(np.clip(motion / 0.08, 0.0, 1.0))
    q = float(np.clip(max(float(tracks.qualities[int(idx)]), 0.80), 0.0, 1.0))
    return float(0.34 * radial + 0.30 * mid_depth + 0.18 * motion_score + 0.18 * q)


def _restore_classical_refill_candidates(
    tracks: TrackSet,
    selected_classical: list[int],
    base_top_order: np.ndarray,
    *,
    max_refill: int,
) -> list[int]:
    """Keep KLT continuity priority from starving GFTT refill observations."""
    if not selected_classical or len(base_top_order) == 0 or int(max_refill) <= 0:
        return selected_classical
    selected = [int(idx) for idx in selected_classical]
    selected_set = set(selected)
    refill_candidates = [
        int(idx)
        for idx in base_top_order.astype(np.int64)
        if _is_gftt_source(tracks.sources[int(idx)]) and int(idx) not in selected_set
    ][: max(0, int(max_refill))]
    if not refill_candidates:
        return selected

    removable_klt = [
        int(idx)
        for idx in reversed(selected)
        if "klt" in str(tracks.sources[int(idx)]).lower()
    ]
    for add_idx, remove_idx in zip(refill_candidates, removable_klt):
        try:
            remove_pos = selected.index(int(remove_idx))
        except ValueError:
            continue
        selected[remove_pos] = int(add_idx)
        selected_set.discard(int(remove_idx))
        selected_set.add(int(add_idx))
    return selected


def _vins_safe_low_cap_context(tracker: object, tracks: TrackSet) -> bool:
    if len(tracks) == 0:
        return False
    if _has_learned_source(tracks):
        return True
    recovery_reason = str(getattr(tracker, "last_recovery_reason", "") or "").lower()
    geometry_mode = str(getattr(tracker, "last_geometry_mode", "") or "").lower()
    klt_degenerate = bool(getattr(tracker, "last_klt_degeneracy_loftr_allowed", False))
    low_texture_tokens = (
        "low_grid_texture",
        "identity_churn",
        "persistent_low_frontend_state",
        "underwater_degradation",
    )
    reason_low_texture = any(token in recovery_reason for token in low_texture_tokens)
    severe_low_texture = geometry_mode == "severe_low_texture"
    if klt_degenerate and (severe_low_texture or reason_low_texture):
        return True
    if severe_low_texture and recovery_reason not in {"healthy", "n/a", "none", ""}:
        return True
    return False


def _select_classical_backbone_sources(tracks: TrackSet) -> TrackSet:
    if len(tracks) == 0:
        return tracks
    mask = _classical_backbone_mask(tracks)
    if bool(np.all(mask)):
        return tracks
    return _subset_tracks_by_indices(tracks, np.flatnonzero(mask).astype(np.int64))


def _select_classical_and_confirmed_loftr_sources(tracks: TrackSet) -> TrackSet:
    if len(tracks) == 0:
        return tracks
    classical = _classical_backbone_mask(tracks)
    confirmed_loftr = np.asarray(
        [
            _is_loftr_source(source) and _is_confirmed_sidecar_source(source)
            for source in tracks.sources
        ],
        dtype=bool,
    )
    keep = classical | confirmed_loftr
    if bool(np.all(keep)):
        return tracks
    return _subset_tracks_by_indices(tracks, np.flatnonzero(keep).astype(np.int64))


def _drop_loftr_if_final_classical_support_high(
    sidecar_tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    final_classical_tracks: TrackSet,
    max_classical_tracks: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    cap = int(max_classical_tracks)
    if cap <= 0 or len(sidecar_tracks) == 0:
        return sidecar_tracks, gate_info
    final_count = int(np.count_nonzero(_classical_backbone_mask(final_classical_tracks)))
    if final_count <= cap:
        return sidecar_tracks, gate_info
    # A high final KLT count is only a veto for LoFTR support that does not
    # improve spatial coverage. If LoFTR opened new grid cells before the mirror
    # fallback, it is exactly the low-texture planar refill this path is meant to
    # preserve.
    if int(gate_info.learned_new_cells) > 0 and (
        not math.isfinite(float(gate_info.learned_grid_gain))
        or float(gate_info.learned_grid_gain) > 0.0
    ):
        return sidecar_tracks, gate_info
    reason = str(gate_info.benefit_reason)
    all_loftr = all(_is_loftr_source(source) for source in sidecar_tracks.sources)
    if (
        all_loftr
        and int(len(sidecar_tracks)) <= 8
        and (
            reason.startswith("accepted_loftr_support_rescue")
            or reason.startswith("accepted_early_loftr_support")
            or reason.startswith("accepted_postinit_loftr_support")
            or "loftr_support_topup" in reason
        )
    ):
        return sidecar_tracks, gate_info
    keep = np.asarray(
        [not _is_loftr_source(source) for source in sidecar_tracks.sources],
        dtype=bool,
    )
    dropped = int(np.count_nonzero(~keep))
    if dropped <= 0:
        return sidecar_tracks, gate_info
    filtered = (
        _subset_tracks_by_indices(sidecar_tracks, np.flatnonzero(keep).astype(np.int64))
        if np.any(keep)
        else TrackSet.empty()
    )
    return filtered, replace(
        gate_info,
        dropped_learned=int(gate_info.dropped_learned) + dropped,
        benefit_reason=f"mirror_high_classical_tracks_for_loftr_rescue:{final_count}",
    )


def _apply_final_mirror_health_suppression(
    sidecar_tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    mirror_tracks: TrackSet,
    image_shape: tuple[int, int],
    min_tracks: int,
    min_grid: float,
    min_age: float,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    if len(sidecar_tracks) == 0:
        return sidecar_tracks, gate_info
    if not _classical_tracks_are_healthy(
        mirror_tracks,
        image_shape,
        min_tracks=int(min_tracks),
        min_grid=float(min_grid),
        min_age=float(min_age),
    ):
        return sidecar_tracks, gate_info

    drop_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in sidecar_tracks.sources],
        dtype=bool,
    )
    dropped = int(np.count_nonzero(drop_mask))
    if dropped <= 0:
        return sidecar_tracks, gate_info

    keep = np.flatnonzero(~drop_mask).astype(np.int64)
    filtered = _subset_tracks_by_indices(sidecar_tracks, keep) if len(keep) else TrackSet.empty()
    return (
        filtered,
        replace(
            gate_info,
            dropped_learned=int(gate_info.dropped_learned) + dropped,
            health_suppression_dropped=int(gate_info.health_suppression_dropped) + dropped,
            health_suppression_reason=(
                "final_mirror_classical_healthy:"
                f"tracks>={int(min_tracks)},grid>={float(min_grid):.3f},age>={float(min_age):.1f}"
            ),
            benefit_reason=_append_benefit_reason(
                gate_info.benefit_reason,
                "final_mirror_classical_healthy",
            ),
        ),
    )


def _allows_non_loftr_backend_sidecar_mode(learned_mode: str, recovery_reason: str) -> bool:
    """Return True when XFeat/SP-LG sidecars are allowed into VINS.

    Low grid coverage alone is not enough: on normal-texture NTNU windows a
    single XFeat sidecar can perturb VINS despite passing local LK/NCC/F/H
    gates. Use learned-mode semantics to reserve non-LoFTR learned observations
    for actual degraded-texture cases; LoFTR is handled separately by its
    planar/extreme gates.
    """
    text = f"{learned_mode} {recovery_reason}".lower()
    positive_tokens = (
        "low_coverage_recovery",
        "low_grid_coverage",
        "low_coverage",
        "low_texture",
        "textureless",
        "extreme",
        "planar",
        "near_wall",
        "identity_churn",
        "churn",
        "severe",
        "degraded_texture",
    )
    negative_modes = {
        "normal",
        "healthy",
        "n/a",
        "none",
        "unknown",
    }
    mode = str(learned_mode or "").lower()
    if mode in negative_modes:
        return False
    return any(token in text for token in positive_tokens)


def _select_sidecar_sources(tracks: TrackSet) -> TrackSet:
    if len(tracks) == 0:
        return tracks
    mask = np.asarray(
        [_is_learned_source(source) or _is_recovered_source(source) for source in tracks.sources],
        dtype=bool,
    )
    if not np.any(mask):
        return TrackSet.empty()
    return _subset_tracks_by_indices(tracks, np.flatnonzero(mask).astype(np.int64))


def _source_specific_sidecar_age_thresholds(
    tracks: TrackSet,
    *,
    min_age: int,
    loftr_min_age: int | None,
    require_confirmed: bool,
) -> np.ndarray:
    """Return export age thresholds after source-level confirmation.

    Confirmed/memory sidecar labels are assigned only after the learned match
    has survived the frontend's LK/NCC/FB checks. In a few low-texture ROS-bag
    export paths that promotion can reset the TrackSet age, so using the same
    age gate as raw learned pairs silently blocks the already-confirmed
    sidecar. Once require-confirmed is enabled, the source label itself means
    the candidate has already survived frontend temporal checks; use a
    one-frame export age for confirmed sidecars and keep raw LoFTR pairs under
    the stricter source-specific age gate.
    """
    thresholds = np.full((len(tracks),), max(1, int(min_age)), dtype=np.int32)
    if len(tracks) == 0:
        return thresholds
    loftr = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    if loftr_min_age is not None:
        thresholds[loftr] = max(1, int(loftr_min_age))
    if require_confirmed:
        confirmed_sidecar = np.asarray(
            [
                _is_confirmed_sidecar_source(source)
                and _is_learned_source(source)
                for source in tracks.sources
            ],
            dtype=bool,
        )
        thresholds[confirmed_sidecar] = 1
    return thresholds


def _sidecar_pre_gate_diagnostics(
    tracks: TrackSet,
    *,
    min_age: int,
    loftr_min_age: int | None,
    min_quality: float,
    loftr_min_quality: float | None,
    min_ncc: float,
    loftr_min_ncc: float | None,
    max_fb: float,
    loftr_max_fb: float | None,
    require_confirmed: bool,
) -> dict[str, int]:
    if len(tracks) == 0:
        return {
            "sidecar_total": 0,
            "sidecar_confirmed": 0,
            "sidecar_age_ok": 0,
            "sidecar_quality_ok": 0,
            "sidecar_ncc_ok": 0,
            "sidecar_fb_ok": 0,
            "sidecar_basic_ok": 0,
            "loftr_total": 0,
            "loftr_basic_ok": 0,
            "non_loftr_total": 0,
            "non_loftr_basic_ok": 0,
        }

    sidecar = np.asarray(
        [_is_learned_source(source) or _is_recovered_source(source) for source in tracks.sources],
        dtype=bool,
    )
    loftr = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    confirmed = np.asarray(
        [
            (not _is_learned_source(source)) or _is_confirmed_sidecar_source(source)
            for source in tracks.sources
        ],
        dtype=bool,
    )

    age_threshold = _source_specific_sidecar_age_thresholds(
        tracks,
        min_age=min_age,
        loftr_min_age=loftr_min_age,
        require_confirmed=require_confirmed,
    )
    quality_threshold = np.full((len(tracks),), float(min_quality), dtype=np.float32)
    ncc_threshold = np.full((len(tracks),), float(min_ncc), dtype=np.float32)
    fb_threshold = np.full((len(tracks),), float(max_fb), dtype=np.float32)
    if loftr_min_quality is not None:
        quality_threshold[loftr] = float(loftr_min_quality)
    if loftr_min_ncc is not None:
        ncc_threshold[loftr] = float(loftr_min_ncc)
    if loftr_max_fb is not None:
        fb_threshold[loftr] = float(loftr_max_fb)

    age_ok = tracks.ages >= age_threshold
    quality_ok = tracks.qualities >= quality_threshold
    ncc_ok = np.asarray(tracks.ncc_scores, dtype=np.float32) >= ncc_threshold
    fb_ok = np.asarray(tracks.fb_errors, dtype=np.float32) <= fb_threshold
    basic_ok = sidecar & age_ok & quality_ok & ncc_ok & fb_ok
    if require_confirmed:
        basic_ok &= confirmed

    non_loftr = sidecar & ~loftr
    return {
        "sidecar_total": int(np.count_nonzero(sidecar)),
        "sidecar_confirmed": int(np.count_nonzero(sidecar & confirmed)),
        "sidecar_age_ok": int(np.count_nonzero(sidecar & age_ok)),
        "sidecar_quality_ok": int(np.count_nonzero(sidecar & quality_ok)),
        "sidecar_ncc_ok": int(np.count_nonzero(sidecar & ncc_ok)),
        "sidecar_fb_ok": int(np.count_nonzero(sidecar & fb_ok)),
        "sidecar_basic_ok": int(np.count_nonzero(basic_ok)),
        "loftr_total": int(np.count_nonzero(sidecar & loftr)),
        "loftr_basic_ok": int(np.count_nonzero(basic_ok & loftr)),
        "non_loftr_total": int(np.count_nonzero(non_loftr)),
        "non_loftr_basic_ok": int(np.count_nonzero(basic_ok & non_loftr)),
    }


def _sidecar_export_diagnostics(
    tracks: TrackSet,
    *,
    visible_state: _VisibleSidecarTrackGateState | None = None,
) -> dict[str, float | int]:
    learned = np.asarray([_is_learned_source(source) for source in tracks.sources], dtype=bool)
    non_loftr = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    xfeat = np.asarray([_is_xfeat_source(source) for source in tracks.sources], dtype=bool)
    loftr = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    learned_streaks = _visible_streaks_for_mask(tracks, learned, visible_state)
    xfeat_streaks = _visible_streaks_for_mask(tracks, xfeat, visible_state)
    loftr_streaks = _visible_streaks_for_mask(tracks, loftr, visible_state)
    return {
        "learned_median_age": _median_masked(tracks.ages, learned),
        "non_loftr_learned_median_age": _median_masked(tracks.ages, non_loftr),
        "xfeat_median_age": _median_masked(tracks.ages, xfeat),
        "loftr_median_age": _median_masked(tracks.ages, loftr),
        "learned_age_lt3": int(np.count_nonzero(learned & (tracks.ages < 3))),
        "xfeat_age_lt3": int(np.count_nonzero(xfeat & (tracks.ages < 3))),
        "loftr_age_lt3": int(np.count_nonzero(loftr & (tracks.ages < 3))),
        "learned_median_visible_streak": _median_float_list(learned_streaks),
        "xfeat_median_visible_streak": _median_float_list(xfeat_streaks),
        "loftr_median_visible_streak": _median_float_list(loftr_streaks),
        "learned_median_motion_px": _median_track_motion_px(tracks, learned),
        "xfeat_median_motion_px": _median_track_motion_px(tracks, xfeat),
        "loftr_median_motion_px": _median_track_motion_px(tracks, loftr),
    }


def _visible_streaks_for_mask(
    tracks: TrackSet,
    mask: np.ndarray,
    visible_state: _VisibleSidecarTrackGateState | None,
) -> list[float]:
    if visible_state is None or len(tracks) == 0 or not np.any(mask):
        return []
    return [float(visible_state.count(int(track_id))) for track_id in tracks.ids[mask]]


def _median_float_list(values: list[float]) -> float:
    if not values:
        return float("nan")
    return float(np.nanmedian(np.asarray(values, dtype=np.float32)))


def _resolve_adaptive_warmup_full_mirror(
    *,
    args: argparse.Namespace,
    init_gate: _InitParallaxGateState,
) -> _AdaptiveWarmupFullMirrorState:
    policy = str(getattr(args, "mirror_measurement_selection_policy", "baseline"))
    if policy != "adaptive_warmup_full_klt_default":
        return _AdaptiveWarmupFullMirrorState(enabled=False, reason="policy_inactive")
    mean_step_px = float(init_gate.mean_step_px)
    if not math.isfinite(mean_step_px):
        return _AdaptiveWarmupFullMirrorState(enabled=False, reason="unknown_init_parallax")
    min_px = float(getattr(args, "adaptive_warmup_full_min_init_parallax_px", 7.0))
    max_px = float(getattr(args, "adaptive_warmup_full_max_init_parallax_px", 12.5))
    if max_px < min_px:
        min_px, max_px = max_px, min_px
    if mean_step_px < min_px:
        return _AdaptiveWarmupFullMirrorState(
            enabled=False,
            reason=f"below_init_parallax_range:{mean_step_px:.3f}<{min_px:.3f}",
        )
    if mean_step_px >= max_px:
        return _AdaptiveWarmupFullMirrorState(
            enabled=False,
            reason=f"above_init_parallax_range:{mean_step_px:.3f}>={max_px:.3f}",
        )
    return _AdaptiveWarmupFullMirrorState(
        enabled=True,
        reason=f"in_init_parallax_risk_range:{min_px:.3f}<={mean_step_px:.3f}<{max_px:.3f}",
    )


def _effective_mirror_selection_policy(
    policy: str,
    adaptive_warmup_full_mirror: _AdaptiveWarmupFullMirrorState,
) -> str:
    if policy == "adaptive_warmup_full_klt_default":
        return "warmup_full_klt_default" if adaptive_warmup_full_mirror.enabled else "klt_default"
    return policy


def _mirror_selection_config(
    *,
    policy: str,
    active_cfg: MeasurementSelectionConfig,
    baseline_cfg: MeasurementSelectionConfig,
    warmup_active: bool = False,
) -> MeasurementSelectionConfig:
    if policy == "warmup_full_klt_default":
        if warmup_active:
            return replace(baseline_cfg, enabled=False)
        return baseline_cfg
    if policy == "klt_default":
        return baseline_cfg
    if policy == "config" or (policy == "warmup_config" and warmup_active):
        return active_cfg
    return replace(baseline_cfg, enabled=False)


def _online_seed_target_mask(tracks: TrackSet, target_sources: str) -> np.ndarray:
    if len(tracks) == 0:
        return np.empty((0,), dtype=bool)
    target = str(target_sources or "non_loftr").lower()
    if target == "xfeat":
        return np.asarray([_is_xfeat_source(source) for source in tracks.sources], dtype=bool)
    if target == "all_learned":
        return np.asarray([_is_learned_source(source) for source in tracks.sources], dtype=bool)
    if target == "loftr":
        return np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    if target == "classical_gftt":
        return np.asarray(
            [_is_classical_gftt_proposer_source(source) for source in tracks.sources],
            dtype=bool,
        )
    return np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )


def _apply_online_seed_post_quality_cap_for_publication(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    target_sources: str,
    max_per_frame: int,
    raw_quality: bool = False,
    constant_quality: bool = False,
    backend_quality_mode: str = "default",
    backend_quality_floor: float | None = None,
    backend_quality_alpha: float = 0.85,
    learned_quality_scale: float = 1.0,
    sp_lg_quality_scale: float = 1.0,
    xfeat_quality_scale: float = 1.0,
    loftr_quality_scale: float = 1.0,
    learned_quality_const: float | None = None,
    sp_lg_quality_const: float | None = None,
    xfeat_quality_const: float | None = None,
    loftr_quality_const: float | None = None,
    low_parallax_quality_boost: bool = False,
    state_adaptive_active: bool = False,
    init_sidecar_support_active: bool = False,
    init_sidecar_classical_quality_floor: float = 0.0,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    cap = max(0, int(max_per_frame))
    if cap <= 0 or len(tracks) == 0:
        return tracks, gate_info

    # Match the offline feature-bag cap: apply the learned cap to the exact
    # PointCloud publication order after VINS duplicate-ID cleanup.
    publish_tracks = _deduplicate_tracks_for_vins(tracks)
    target_mask = _online_seed_target_mask(publish_tracks, target_sources)
    target_indices = np.flatnonzero(target_mask).astype(np.int64)
    if len(target_indices) <= cap:
        return publish_tracks, gate_info

    backend_quality = _backend_reliability(
        publish_tracks,
        raw_quality=raw_quality,
        constant_quality=constant_quality,
        mode=backend_quality_mode,
        floor=backend_quality_floor,
        alpha=backend_quality_alpha,
        learned_quality_scale=learned_quality_scale,
        sp_lg_quality_scale=sp_lg_quality_scale,
        xfeat_quality_scale=xfeat_quality_scale,
        loftr_quality_scale=loftr_quality_scale,
        learned_quality_const=learned_quality_const,
        sp_lg_quality_const=sp_lg_quality_const,
        xfeat_quality_const=xfeat_quality_const,
        loftr_quality_const=loftr_quality_const,
        low_parallax_quality_boost=low_parallax_quality_boost,
        state_adaptive_active=state_adaptive_active,
        init_sidecar_support_active=init_sidecar_support_active,
        init_sidecar_classical_quality_floor=init_sidecar_classical_quality_floor,
    )
    quality = np.asarray(backend_quality[target_indices], dtype=np.float32)
    order = target_indices[np.lexsort((target_indices, -quality))]
    keep_target = {int(idx) for idx in order[:cap]}
    keep = np.ones((len(publish_tracks),), dtype=bool)
    for idx in target_indices:
        if int(idx) not in keep_target:
            keep[int(idx)] = False

    dropped = int(np.count_nonzero(target_mask & ~keep))
    kept_tracks = _subset_tracks_by_indices(
        publish_tracks,
        np.flatnonzero(keep).astype(np.int64),
    )
    return (
        kept_tracks,
        replace(
            gate_info,
            dropped_learned=int(gate_info.dropped_learned) + dropped,
            benefit_dropped=int(gate_info.benefit_dropped) + dropped,
            benefit_reason=_append_benefit_reason(
                gate_info.benefit_reason,
                "online_seed_post_quality_cap",
            ),
        ),
    )


def _apply_online_seed_sidecar_gate(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    frame_index: int,
    tracker_learned_mode: str,
    target_sources: str,
    warmup_frames: int,
    max_observations: int,
    used_observations: int,
    max_per_frame: int,
    min_age: int,
    min_quality: float,
    min_ncc: float,
    max_fb: float,
    require_confirmed: bool,
    require_fresh: bool,
    fresh_confirmed_count: int,
    fresh_scope: str,
    fresh_hold_frames: int,
    fresh_state: _FreshSidecarConfirmationGateState | None,
    fresh_frame_state: _OnlineSeedFreshFrameGateState | None,
    microburst_gate: bool,
    microburst_frames: int,
    microburst_extend_frames: int,
    microburst_extend_min_initial_observations: int,
    microburst_extend_min_initial_cells: int,
    microburst_extend_min_bbox_area_ratio: float,
    microburst_extend_grid_rows: int,
    microburst_extend_grid_cols: int,
    microburst_max_restarts: int,
    microburst_restart_cooldown_frames: int,
    lineage_continuation: bool,
    lineage_min_age: int,
    lineage_max_per_frame: int,
    lineage_max_observations: int,
    lineage_used_observations: int,
    lineage_separate_budget: bool,
    dense_start_max_observations: int,
    dense_start_min_classical_tracks: int,
    dense_start_min_classical_grid: float,
    dense_start_min_frame_candidates: int,
    sparse_start_min_frame_candidates: int,
    sparse_start_min_classical_tracks: int,
    sparse_start_min_classical_grid: float,
    start_min_classical_grid: float,
    start_min_classical_grid_tracks: int,
    max_start_classical_gftt_ratio: float,
    start_gftt_ratio_min_classical_tracks: int,
    start_gftt_ratio_min_classical_grid: float,
    normal_start_max_motion_px: float,
    normal_start_min_frame_candidates: int,
    normal_start_max_frame_candidates: int,
    normal_start_min_classical_tracks: int,
    normal_start_min_classical_grid: float,
    max_classical_gftt_ratio: float,
    gftt_ratio_min_classical_tracks: int,
    gftt_ratio_min_classical_grid: float,
    microburst_state: _OnlineSeedMicroburstGateState | None,
    image_shape: tuple[int, int] | None,
) -> tuple[TrackSet, _LearnedExportGateInfo, int, int]:
    if len(tracks) == 0:
        return tracks, gate_info, int(used_observations), int(lineage_used_observations)

    target_mask = _online_seed_target_mask(tracks, target_sources)
    target_count = int(np.count_nonzero(target_mask))
    if target_count == 0:
        return tracks, gate_info, int(used_observations), int(lineage_used_observations)

    keep = np.ones((len(tracks),), dtype=bool)
    reasons: list[str] = []

    if int(frame_index) < max(0, int(warmup_frames)):
        keep[target_mask] = False
        reasons.append("online_seed_warmup")
        dropped = target_count
        return (
            _subset_tracks_by_indices(tracks, np.flatnonzero(keep).astype(np.int64)),
            replace(
                gate_info,
                dropped_learned=int(gate_info.dropped_learned) + dropped,
                benefit_dropped=int(gate_info.benefit_dropped) + dropped,
                benefit_reason=_append_benefit_reason(
                    gate_info.benefit_reason,
                    ":".join(reasons),
                ),
            ),
            int(used_observations),
            int(lineage_used_observations),
        )

    confirmed_ok = np.ones((len(tracks),), dtype=bool)
    if bool(require_confirmed):
        confirmed_ok = np.asarray(
            [_is_confirmed_sidecar_source(source) for source in tracks.sources],
            dtype=bool,
        )
    fresh_ok = np.ones((len(tracks),), dtype=bool)
    if bool(require_fresh):
        if str(fresh_scope).lower() == "frame":
            if fresh_frame_state is None:
                fresh_ok[target_mask] = False
            else:
                if int(fresh_confirmed_count) > 0:
                    fresh_frame_state.record(
                        frame_index=int(frame_index),
                        hold_frames=max(0, int(fresh_hold_frames)),
                    )
                fresh_ok[target_mask] = fresh_frame_state.allowed(
                    frame_index=int(frame_index)
                )
        elif fresh_state is None:
            fresh_ok[target_mask] = False
        else:
            fresh_state.prune(int(frame_index))
            target_confirmed_indices = np.flatnonzero(target_mask & confirmed_ok).astype(np.int64)
            if int(fresh_confirmed_count) > 0:
                for idx in target_confirmed_indices:
                    fresh_state.record(
                        int(tracks.ids[int(idx)]),
                        frame_index=int(frame_index),
                        hold_frames=max(0, int(fresh_hold_frames)),
                    )
            fresh_ok = np.asarray(
                [
                    (not bool(target_mask[int(idx)]))
                    or fresh_state.allowed(int(tracks.ids[int(idx)]), frame_index=int(frame_index))
                    for idx in range(len(tracks))
                ],
                dtype=bool,
            )
    age_ok = np.asarray(tracks.ages, dtype=np.float32) >= max(1, int(min_age))
    quality_ok = np.asarray(tracks.qualities, dtype=np.float32) >= float(min_quality)
    ncc_ok = np.asarray(tracks.ncc_scores, dtype=np.float32) >= float(min_ncc)
    fb_ok = np.asarray(tracks.fb_errors, dtype=np.float32) <= float(max_fb)
    pre_microburst_ok = (
        target_mask & confirmed_ok & fresh_ok & age_ok & quality_ok & ncc_ok & fb_ok
    )
    if np.any(pre_microburst_ok):
        classical_mask = _classical_backbone_mask(tracks)
        classical_count = int(np.count_nonzero(classical_mask))
        classical_grid = _track_grid_coverage(tracks, image_shape, classical_mask)
        start_grid_threshold = float(start_min_classical_grid)
        start_candidate_count = int(np.count_nonzero(pre_microburst_ok))
        if (
            start_grid_threshold > 0.0
            and bool(microburst_gate)
            and microburst_state is not None
            and int(microburst_state.start_frame) < 0
            and classical_count >= max(0, int(start_min_classical_grid_tracks))
            and classical_grid < start_grid_threshold
        ):
            microburst_state.reject_start(
                frame_index=int(frame_index),
                reason=(
                    "low_grid_start"
                    f":classical={classical_count}"
                    f":grid={classical_grid:.3f}"
                ),
            )
            pre_microburst_ok[target_mask] = False
            reasons.append(
                "online_seed_low_grid_start"
                f":classical={classical_count}"
                f":grid={classical_grid:.3f}"
            )
        sparse_start_threshold = max(0, int(sparse_start_min_frame_candidates))
        if (
            sparse_start_threshold > 0
            and bool(microburst_gate)
            and microburst_state is not None
            and int(microburst_state.start_frame) < 0
            and str(tracker_learned_mode or "").lower() == "normal"
            and start_candidate_count < sparse_start_threshold
            and classical_count >= max(0, int(sparse_start_min_classical_tracks))
            and (
                float(sparse_start_min_classical_grid) <= 0.0
                or classical_grid >= float(sparse_start_min_classical_grid)
            )
        ):
            microburst_state.reject_start(
                frame_index=int(frame_index),
                reason=(
                    "sparse_start"
                    f":candidates={int(np.count_nonzero(target_mask & confirmed_ok & fresh_ok & age_ok & quality_ok & ncc_ok & fb_ok))}"
                    f":classical={classical_count}"
                    f":grid={classical_grid:.3f}"
                ),
            )
            pre_microburst_ok[target_mask] = False
            reasons.append(
                "online_seed_sparse_start"
                f":candidates={int(np.count_nonzero(target_mask & confirmed_ok & fresh_ok & age_ok & quality_ok & ncc_ok & fb_ok))}"
                f":classical={classical_count}"
                f":grid={classical_grid:.3f}"
            )
        start_gftt_ratio_limit = float(max_start_classical_gftt_ratio)
        if (
            start_gftt_ratio_limit > 0.0
            and np.any(pre_microburst_ok)
            and bool(microburst_gate)
            and microburst_state is not None
            and int(microburst_state.start_frame) < 0
            and str(tracker_learned_mode or "").lower() == "normal"
            and classical_count >= max(1, int(start_gftt_ratio_min_classical_tracks))
            and (
                float(start_gftt_ratio_min_classical_grid) <= 0.0
                or classical_grid >= float(start_gftt_ratio_min_classical_grid)
            )
        ):
            classical_indices = np.flatnonzero(classical_mask).astype(np.int64)
            gftt_count = sum(
                1
                for idx in classical_indices
                if _is_gftt_source(tracks.sources[int(idx)])
            )
            gftt_ratio = float(gftt_count) / max(1.0, float(classical_count))
            if gftt_ratio >= start_gftt_ratio_limit:
                microburst_state.reject_start(
                    frame_index=int(frame_index),
                    reason=(
                        "gftt_start"
                        f":ratio={gftt_ratio:.3f}"
                        f":classical={classical_count}"
                        f":grid={classical_grid:.3f}"
                    ),
                )
                pre_microburst_ok[target_mask] = False
                reasons.append(
                    "online_seed_gftt_start"
                    f":ratio={gftt_ratio:.3f}"
                    f":classical={classical_count}"
                    f":grid={classical_grid:.3f}"
                )
        normal_motion_limit = float(normal_start_max_motion_px)
        if (
            normal_motion_limit > 0.0
            and np.any(pre_microburst_ok)
            and bool(microburst_gate)
            and microburst_state is not None
            and int(microburst_state.start_frame) < 0
            and str(tracker_learned_mode or "").lower() == "normal"
            and start_candidate_count >= max(1, int(normal_start_min_frame_candidates))
            and (
                int(normal_start_max_frame_candidates) <= 0
                or start_candidate_count <= int(normal_start_max_frame_candidates)
            )
            and classical_count >= max(0, int(normal_start_min_classical_tracks))
            and (
                float(normal_start_min_classical_grid) <= 0.0
                or classical_grid >= float(normal_start_min_classical_grid)
            )
        ):
            candidate_indices = np.flatnonzero(pre_microburst_ok).astype(np.int64)
            motion_px = _median_track_motion_px(
                tracks,
                np.isin(np.arange(len(tracks)), candidate_indices),
            )
            if math.isfinite(float(motion_px)) and motion_px >= normal_motion_limit:
                microburst_state.reject_start(
                    frame_index=int(frame_index),
                    reason=(
                        "normal_motion_start"
                        f":motion={float(motion_px):.3f}"
                        f":candidates={start_candidate_count}"
                        f":classical={classical_count}"
                        f":grid={classical_grid:.3f}"
                    ),
                )
                pre_microburst_ok[target_mask] = False
                reasons.append(
                    "online_seed_normal_motion_start"
                    f":motion={float(motion_px):.3f}"
                    f":candidates={start_candidate_count}"
                    f":classical={classical_count}"
                    f":grid={classical_grid:.3f}"
                )
        gftt_ratio_limit = float(max_classical_gftt_ratio)
        if gftt_ratio_limit > 0.0 and np.any(pre_microburst_ok):
            if (
                classical_count >= max(1, int(gftt_ratio_min_classical_tracks))
                and (
                    float(gftt_ratio_min_classical_grid) <= 0.0
                    or classical_grid >= float(gftt_ratio_min_classical_grid)
                )
            ):
                classical_indices = np.flatnonzero(classical_mask).astype(np.int64)
                gftt_count = sum(
                    1
                    for idx in classical_indices
                    if _is_gftt_source(tracks.sources[int(idx)])
                )
                gftt_ratio = float(gftt_count) / max(1.0, float(classical_count))
                if gftt_ratio >= gftt_ratio_limit:
                    if bool(microburst_gate) and microburst_state is not None:
                        microburst_state.reject_start(
                            frame_index=int(frame_index),
                            reason=(
                                "gftt_dominated"
                                f":ratio={gftt_ratio:.3f}"
                                f":classical={classical_count}"
                                f":grid={classical_grid:.3f}"
                            ),
                        )
                    pre_microburst_ok[target_mask] = False
                    reasons.append(
                        "online_seed_gftt_dominated"
                        f":ratio={gftt_ratio:.3f}"
                        f":classical={classical_count}"
                        f":grid={classical_grid:.3f}"
                    )
    microburst_ok = np.ones((len(tracks),), dtype=bool)
    if bool(microburst_gate) and int(microburst_frames) > 0:
        if microburst_state is None:
            microburst_ok[target_mask] = False
        else:
            if np.any(pre_microburst_ok):
                restarted = microburst_state.maybe_restart(
                    frame_index=int(frame_index),
                    span_frames=max(1, int(microburst_frames)),
                    cooldown_frames=max(0, int(microburst_restart_cooldown_frames)),
                    max_restarts=max(0, int(microburst_max_restarts)),
                )
                if restarted:
                    reasons.append("online_seed_microburst_restart")
                microburst_state.maybe_start(
                    frame_index=int(frame_index),
                    span_frames=max(1, int(microburst_frames)),
                )
                microburst_state.record_initial_candidates(
                    frame_index=int(frame_index),
                    tracks=tracks,
                    mask=pre_microburst_ok,
                    image_shape=image_shape,
                    grid_rows=int(microburst_extend_grid_rows),
                    grid_cols=int(microburst_extend_grid_cols),
                )
                microburst_state.maybe_apply_dense_start_cap(
                    frame_index=int(frame_index),
                    tracks=tracks,
                    mask=pre_microburst_ok,
                    image_shape=image_shape,
                    max_observations=int(dense_start_max_observations),
                    min_classical_tracks=int(dense_start_min_classical_tracks),
                    min_classical_grid=float(dense_start_min_classical_grid),
                    min_frame_candidates=int(dense_start_min_frame_candidates),
                )
                microburst_state.maybe_extend(
                    frame_index=int(frame_index),
                    total_span_frames=int(microburst_extend_frames),
                    min_initial_observations=int(
                        microburst_extend_min_initial_observations
                    ),
                    min_initial_cells=int(microburst_extend_min_initial_cells),
                    min_initial_bbox_area_ratio=float(
                        microburst_extend_min_bbox_area_ratio
                    ),
                    image_shape=image_shape,
                )
            if not microburst_state.allowed(frame_index=int(frame_index)):
                microburst_ok[target_mask] = False
    basic_ok = pre_microburst_ok & microburst_ok

    lineage_accepted: list[int] = []
    lineage_keep = np.zeros((len(tracks),), dtype=bool)
    if bool(lineage_continuation) and not np.any(basic_ok):
        lineage_confirmed = np.asarray(
            [_is_confirmed_sidecar_source(source) for source in tracks.sources],
            dtype=bool,
        )
        lineage_ok = (
            target_mask
            & lineage_confirmed
            & age_ok
            & quality_ok
            & ncc_ok
            & fb_ok
            & (np.asarray(tracks.ages, dtype=np.int32) >= max(1, int(lineage_min_age)))
            & ~basic_ok
        )
        lineage_candidates = np.flatnonzero(lineage_ok).astype(np.int64)
        if len(lineage_candidates):
            lineage_remaining = None
            if int(lineage_max_observations) > 0:
                lineage_remaining = max(
                    0,
                    int(lineage_max_observations) - max(0, int(lineage_used_observations)),
                )
            total_remaining = None
            if int(max_observations) > 0 and not bool(lineage_separate_budget):
                total_remaining = max(
                    0,
                    int(max_observations) - max(0, int(used_observations)),
                )
            limit = len(lineage_candidates)
            if lineage_remaining is not None:
                limit = min(limit, int(lineage_remaining))
            if total_remaining is not None:
                limit = min(limit, int(total_remaining))
            if int(lineage_max_per_frame) > 0:
                limit = min(limit, int(lineage_max_per_frame))
            if limit > 0:
                order = _source_selection_order(tracks, lineage_candidates, prefer_age=True)
                lineage_accepted = [int(idx) for idx in order[:limit]]
                if lineage_accepted:
                    lineage_keep[np.asarray(lineage_accepted, dtype=np.int64)] = True
                    reasons.append("online_seed_lineage_continuation")
            elif lineage_remaining == 0:
                reasons.append("online_seed_lineage_budget")

    rejected_basic = target_mask & ~basic_ok & ~lineage_keep
    if np.any(rejected_basic):
        keep[rejected_basic] = False
        if np.any(pre_microburst_ok & ~microburst_ok):
            if microburst_state is not None and str(microburst_state.rejected_start_reason):
                reasons.append(
                    "online_seed_" + str(microburst_state.rejected_start_reason)
                )
            elif (
                microburst_state is not None
                and bool(microburst_state.extension_decided)
                and not bool(microburst_state.extension_enabled)
            ):
                reasons.append("online_seed_microburst_no_extend")
            else:
                reasons.append("online_seed_microburst")
        if bool(require_fresh) and np.any(target_mask & ~fresh_ok):
            reasons.append("online_seed_fresh")
        if np.any(target_mask & fresh_ok & ~(confirmed_ok & age_ok & quality_ok & ncc_ok & fb_ok)):
            reasons.append("online_seed_basic")

    candidates = np.flatnonzero(basic_ok).astype(np.int64)
    accepted: list[int] = []
    remaining = None
    max_observations = max(0, int(max_observations))
    effective_max_observations = max_observations
    if microburst_state is not None and int(microburst_state.observation_cap) > 0:
        dense_cap = int(microburst_state.observation_cap)
        effective_max_observations = (
            dense_cap
            if effective_max_observations <= 0
            else min(effective_max_observations, dense_cap)
        )
        if microburst_state.observation_cap_reason:
            reasons.append(f"online_seed_{microburst_state.observation_cap_reason}")
    if effective_max_observations > 0:
        remaining = max(0, effective_max_observations - max(0, int(used_observations)))
        if remaining <= 0:
            keep[candidates] = False
            if len(candidates):
                reasons.append("online_seed_budget")
            candidates = np.empty((0,), dtype=np.int64)

    if len(candidates):
        limit = len(candidates)
        if remaining is not None:
            limit = min(limit, int(remaining))
        if int(max_per_frame) > 0:
            limit = min(limit, max(0, int(max_per_frame)))
        order = _source_selection_order(tracks, candidates, prefer_age=False)
        accepted = [int(idx) for idx in order[:limit]]
        accepted_set = set(accepted)
        for idx in candidates:
            if int(idx) not in accepted_set:
                keep[int(idx)] = False
        if len(accepted) < len(candidates):
            if remaining is not None and len(accepted) >= int(remaining):
                reasons.append("online_seed_budget")
            if int(max_per_frame) > 0 and len(accepted) >= int(max_per_frame):
                reasons.append("online_seed_per_frame")

    dropped = int(np.count_nonzero(target_mask & ~keep))
    used_after = int(used_observations) + len(accepted)
    if lineage_accepted:
        used_after += len(lineage_accepted)
    lineage_used_after = int(lineage_used_observations) + len(lineage_accepted)
    if dropped == 0:
        ok_reason = "online_seed_ok"
        if lineage_accepted:
            ok_reason = _append_benefit_reason(ok_reason, "online_seed_lineage_continuation")
        elif "online_seed_microburst_restart" in reasons:
            ok_reason = _append_benefit_reason(ok_reason, "online_seed_microburst_restart")
        return (
            tracks,
            replace(
                gate_info,
                benefit_reason=_append_benefit_reason(
                    gate_info.benefit_reason,
                    ok_reason,
                ),
            ),
            used_after,
            lineage_used_after,
        )

    if not reasons:
        reasons.append("online_seed_limited")
    return (
        _subset_tracks_by_indices(tracks, np.flatnonzero(keep).astype(np.int64)),
        replace(
            gate_info,
            dropped_learned=int(gate_info.dropped_learned) + dropped,
            benefit_dropped=int(gate_info.benefit_dropped) + dropped,
            benefit_reason=_append_benefit_reason(
                gate_info.benefit_reason,
                ":".join(dict.fromkeys(reasons)),
            ),
        ),
        used_after,
        lineage_used_after,
    )


def _apply_sidecar_observation_budget(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    max_observations: int,
    used_observations: int,
) -> tuple[TrackSet, _LearnedExportGateInfo, int]:
    max_observations = max(0, int(max_observations))
    if max_observations <= 0 or len(tracks) == 0:
        return tracks, gate_info, used_observations
    classical = _classical_backbone_mask(tracks)
    sidecar_indices = np.flatnonzero(~classical).astype(np.int64)
    sidecar_count = int(len(sidecar_indices))
    if sidecar_count == 0:
        return tracks, gate_info, used_observations

    remaining = max(0, max_observations - max(0, int(used_observations)))
    if remaining <= 0:
        kept = np.flatnonzero(classical).astype(np.int64)
        return (
            _subset_tracks_by_indices(tracks, kept),
            replace(
                gate_info,
                benefit_dropped=gate_info.benefit_dropped + sidecar_count,
                benefit_reason=_append_benefit_reason(
                    gate_info.benefit_reason,
                    "sidecar_observation_budget",
                ),
            ),
            used_observations,
        )
    if sidecar_count <= remaining:
        return tracks, gate_info, used_observations + sidecar_count

    keep_sidecar = sidecar_indices[:remaining]
    keep = np.concatenate([np.flatnonzero(classical).astype(np.int64), keep_sidecar])
    dropped = sidecar_count - remaining
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            gate_info,
            benefit_dropped=gate_info.benefit_dropped + dropped,
            benefit_reason=_append_benefit_reason(
                gate_info.benefit_reason,
                "sidecar_observation_budget_partial",
            ),
        ),
        used_observations + remaining,
    )


def _append_benefit_reason(base: str, suffix: str) -> str:
    base = str(base or "")
    suffix = str(suffix)
    if not base or base in {"disabled", "not_run"}:
        return suffix
    if suffix in base.split(":"):
        return base
    return f"{base}:{suffix}"


def _apply_loftr_seeded_continuation(
    tracks: TrackSet,
    *,
    pre_benefit_mask: np.ndarray,
    accepted_mask: np.ndarray,
    benefit_reason: str,
    state: _LoFTRSeededContinuationGateState,
    frame_index: int,
    max_gap: int,
) -> tuple[np.ndarray, str, int]:
    """Restore only contiguous, still-verified LoFTR lineages.

    ``pre_benefit_mask`` has already passed the source-specific age, quality,
    NCC, forward/backward, confirmation, and FEH residual checks.  This helper
    therefore bypasses only the repeated coverage/new-cell benefit decision.
    """

    pre_benefit = np.asarray(pre_benefit_mask, dtype=bool)
    accepted = np.asarray(accepted_mask, dtype=bool).copy()
    if len(tracks) == 0 or int(frame_index) < 0:
        return accepted, str(benefit_reason), 0

    confirmed_loftr = np.asarray(
        [
            _is_loftr_source(source) and _is_confirmed_sidecar_source(source)
            for source in tracks.sources
        ],
        dtype=bool,
    )
    contiguous = state.continuation_mask(
        tracks.ids,
        frame_index=int(frame_index),
        max_gap=max(1, int(max_gap)),
    )
    restore = pre_benefit & confirmed_loftr & contiguous & ~accepted
    restored = int(np.count_nonzero(restore))
    if restored:
        accepted |= restore
        benefit_reason = _append_benefit_reason(
            str(benefit_reason),
            "accepted_loftr_support_rescue_seeded_continuation",
        )

    state.record(
        tracks.ids[accepted & confirmed_loftr],
        frame_index=int(frame_index),
    )
    return accepted, str(benefit_reason), restored


def _apply_coverage_seeded_continuation_gate(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    state: _CoverageSeededContinuationGateState,
    max_classical_age: float,
    max_classical_motion_px: float,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    if len(tracks) == 0:
        return tracks, gate_info

    learned_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    learned_count = int(np.count_nonzero(learned_mask))
    if learned_count == 0:
        return tracks, gate_info

    reason = str(gate_info.benefit_reason)
    budget_limited = (
        "sidecar_observation_budget_partial" in reason
        or "sidecar_observation_budget" in reason
    )
    if "accepted_coverage_gain" in reason and not budget_limited:
        state.record(tracks, learned_mask)
        return tracks, gate_info

    continuation_tokens = {
        "accepted_weak_cell_rescue",
        "sidecar_observation_budget_partial",
        "sidecar_observation_budget",
    }
    if not any(token in reason for token in continuation_tokens):
        return tracks, gate_info

    age = float(gate_info.classical_median_age)
    motion = float(gate_info.classical_motion_px)
    continuation_ok = (
        math.isfinite(age)
        and math.isfinite(motion)
        and age <= float(max_classical_age) + 1e-9
        and motion <= float(max_classical_motion_px) + 1e-9
    )
    seeded = np.asarray([state.is_seeded(track_id) for track_id in tracks.ids], dtype=bool)
    keep_mask = (~learned_mask) | (learned_mask & seeded & continuation_ok)
    dropped = int(np.count_nonzero(learned_mask & ~keep_mask))
    if dropped == 0:
        return tracks, gate_info

    keep = np.flatnonzero(keep_mask).astype(np.int64)
    detail = "coverage_seeded_continuation"
    if not continuation_ok:
        detail = "coverage_seeded_continuation_context"
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            gate_info,
            benefit_dropped=gate_info.benefit_dropped + dropped,
            benefit_reason=f"{reason}:{detail}",
        ),
    )


def _apply_loftr_min_export_count(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    min_export_count: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    min_export_count = max(0, int(min_export_count))
    if min_export_count <= 0 or len(tracks) == 0:
        return tracks, gate_info
    loftr_mask = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    loftr_count = int(np.count_nonzero(loftr_mask))
    if loftr_count == 0 or loftr_count >= min_export_count:
        return tracks, gate_info

    keep = np.flatnonzero(~loftr_mask).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            gate_info,
            dropped_learned=int(gate_info.dropped_learned) + loftr_count,
            benefit_dropped=int(gate_info.benefit_dropped) + loftr_count,
            benefit_reason=f"loftr_min_export_count:{loftr_count}<{min_export_count}",
        ),
    )


def _apply_loftr_support_cooldown_gate(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    state: _TemporalSidecarGateState,
    frame_index: int,
    cooldown_frames: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    cooldown = max(0, int(cooldown_frames))
    if cooldown <= 0 or len(tracks) == 0:
        return tracks, gate_info
    reason = str(gate_info.benefit_reason)
    if not reason.startswith("accepted_loftr_support_rescue"):
        return tracks, gate_info
    classical = _classical_backbone_mask(tracks)
    sidecar_indices = np.flatnonzero(~classical).astype(np.int64)
    if len(sidecar_indices) == 0:
        return tracks, gate_info
    if not all(_is_loftr_source(tracks.sources[int(idx)]) for idx in sidecar_indices):
        return tracks, gate_info
    if state.loftr_support_in_cooldown(int(frame_index), cooldown):
        dropped = int(len(sidecar_indices))
        keep = np.flatnonzero(classical).astype(np.int64)
        return (
            _subset_tracks_by_indices(tracks, keep),
            replace(
                gate_info,
                dropped_learned=int(gate_info.dropped_learned) + dropped,
                temporal_dropped=int(gate_info.temporal_dropped) + dropped,
                temporal_reason=(
                    f"loftr_support_cooldown:{state.last_loftr_support_frame}"
                ),
            ),
        )
    state.record_loftr_support(int(frame_index))
    return tracks, gate_info


def _apply_temporal_sidecar_burst_gate(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    *,
    state: _TemporalSidecarGateState,
    frame_index: int,
    window: int,
    min_recent_frames: int,
    late_start_frame: int,
    min_sidecars: int,
    allow_postinit_loftr_support: bool = False,
    allow_early_loftr_support: bool = False,
    loftr_support_holdoff_until: int = 0,
    allow_isolated_non_loftr_sidecars: bool = False,
    isolated_non_loftr_max_count: int = 2,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    if len(tracks) == 0:
        return tracks, replace(gate_info, temporal_reason="empty")

    classical = _classical_backbone_mask(tracks)
    sidecar_indices = np.flatnonzero(~classical).astype(np.int64)
    sidecar_count = int(len(sidecar_indices))
    recent = state.recent_count(int(frame_index), int(window))
    recent_candidates = state.recent_candidate_count(int(frame_index), int(window))
    if sidecar_count == 0:
        return tracks, replace(
            gate_info,
            temporal_reason="no_sidecar",
            temporal_recent_frames=recent,
        )

    late = int(frame_index) >= max(0, int(late_start_frame))
    enough_recent = recent >= max(0, int(min_recent_frames))
    enough_candidate_recent = recent_candidates >= max(0, int(min_recent_frames))
    enough_same_frame = sidecar_count >= max(1, int(min_sidecars))
    state.record_candidate(int(frame_index))
    early_loftr_support = (
        (not late)
        and _is_loftr_support_rescue_sidecar_frame(
            tracks,
            gate_info,
            sidecar_indices,
            allow=bool(allow_postinit_loftr_support),
        )
    )
    if early_loftr_support:
        if bool(allow_early_loftr_support):
            state.record(int(frame_index))
            return tracks, replace(
                gate_info,
                temporal_reason="accepted_early_loftr_support",
                temporal_recent_frames=recent,
            )
        if int(frame_index) >= max(0, int(loftr_support_holdoff_until)):
            state.record(int(frame_index))
            return tracks, replace(
                gate_info,
                temporal_reason="accepted_postinit_loftr_support",
                temporal_recent_frames=recent,
            )
        keep = np.flatnonzero(classical).astype(np.int64)
        return (
            _subset_tracks_by_indices(tracks, keep),
            replace(
                gate_info,
                dropped_learned=gate_info.dropped_learned + sidecar_count,
                temporal_dropped=gate_info.temporal_dropped + sidecar_count,
                temporal_reason="early_loftr_support_holdoff",
                temporal_recent_frames=recent,
            ),
        )
    postinit_loftr_support = _is_postinit_loftr_support_rescue(
        tracks,
        gate_info,
        sidecar_indices,
        allow=bool(allow_postinit_loftr_support),
    )
    if (
        (not late)
        or enough_recent
        or enough_candidate_recent
        or enough_same_frame
        or postinit_loftr_support
    ):
        state.record(int(frame_index))
        if not late:
            reason = "accepted_early_sidecar"
        elif enough_recent:
            reason = "accepted_temporal_burst"
        elif enough_candidate_recent:
            reason = "accepted_candidate_burst"
        elif postinit_loftr_support:
            reason = "accepted_postinit_loftr_support"
        else:
            reason = "accepted_same_frame_burst"
        return tracks, replace(
            gate_info,
            temporal_reason=reason,
            temporal_recent_frames=recent,
        )

    isolated_non_loftr_sidecar = _is_isolated_non_loftr_sidecar(
        tracks,
        gate_info,
        sidecar_indices,
        allow=bool(allow_isolated_non_loftr_sidecars),
        max_count=int(isolated_non_loftr_max_count),
    )
    if isolated_non_loftr_sidecar:
        state.record(int(frame_index))
        return tracks, replace(
            gate_info,
            temporal_reason="accepted_isolated_non_loftr_sidecar",
            temporal_recent_frames=recent,
        )

    keep = np.flatnonzero(classical).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            gate_info,
            dropped_learned=gate_info.dropped_learned + sidecar_count,
            temporal_dropped=gate_info.temporal_dropped + sidecar_count,
            temporal_reason="late_isolated_sidecar",
            temporal_recent_frames=recent,
        ),
    )


def _is_isolated_non_loftr_sidecar(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    sidecar_indices: np.ndarray,
    *,
    allow: bool,
    max_count: int,
) -> bool:
    if not allow or len(sidecar_indices) == 0:
        return False
    if int(len(sidecar_indices)) > max(0, int(max_count)):
        return False
    if not bool(gate_info.active) or not bool(gate_info.degraded):
        return False
    benefit_reason = str(gate_info.benefit_reason).lower()
    accepted_benefit = (
        "accepted_coverage_gain" in benefit_reason
        or "accepted_weak_cell_rescue" in benefit_reason
        or "accepted_mature_non_loftr" in benefit_reason
    )
    if not accepted_benefit:
        return False
    if "accepted" not in str(gate_info.geometry_reason).lower():
        return False
    return all(
        (not _is_loftr_source(tracks.sources[int(idx)]))
        and _is_confirmed_sidecar_source(tracks.sources[int(idx)])
        for idx in sidecar_indices
    )


def _is_loftr_support_rescue_sidecar_frame(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    sidecar_indices: np.ndarray,
    *,
    allow: bool,
) -> bool:
    if not allow or len(sidecar_indices) == 0:
        return False
    if not bool(gate_info.active) or not bool(gate_info.degraded):
        return False
    reason = f"{gate_info.benefit_reason} {gate_info.geometry_reason}".lower()
    if "accepted_loftr_support_rescue" not in reason:
        return False
    return all(
        _is_loftr_source(tracks.sources[int(idx)])
        and _is_confirmed_sidecar_source(tracks.sources[int(idx)])
        for idx in sidecar_indices
    )


def _is_postinit_loftr_support_rescue(
    tracks: TrackSet,
    gate_info: _LearnedExportGateInfo,
    sidecar_indices: np.ndarray,
    *,
    allow: bool,
) -> bool:
    if not allow or len(sidecar_indices) == 0:
        return False
    if not bool(gate_info.active) or not bool(gate_info.degraded):
        return False
    reason = f"{gate_info.benefit_reason} {gate_info.geometry_reason}".lower()
    accepted_late_rescue = (
        "accepted_loftr_support_rescue" in reason
        or "accepted_loftr_planar_rescue_low_motion" in reason
    )
    if not accepted_late_rescue:
        return False
    if "accepted" not in str(gate_info.geometry_reason).lower():
        return False
    # Match the formal LoFTR per-frame rescue cap: a small six-point verified
    # support batch may seed a late recovery burst, while larger batches remain
    # blocked as possible replacement frontends.
    if int(len(sidecar_indices)) > 6:
        return False
    if gate_info.classical_grid_coverage > 0.76 + 1e-9:
        return False
    motion = float(gate_info.classical_motion_px)
    if not math.isfinite(motion) or motion > 2.2:
        return False
    age = float(gate_info.classical_median_age)
    if not math.isfinite(age) or age < 20.0:
        return False
    return all(
        _is_loftr_source(tracks.sources[int(idx)])
        and _is_confirmed_sidecar_source(tracks.sources[int(idx)])
        for idx in sidecar_indices
    )


def _append_tracksets(a: TrackSet, b: TrackSet) -> TrackSet:
    if len(a) == 0:
        return b
    if len(b) == 0:
        return a
    return TrackSet(
        ids=np.concatenate([a.ids, b.ids]),
        prev_points=np.vstack([a.prev_points, b.prev_points]),
        points=np.vstack([a.points, b.points]),
        ages=np.concatenate([a.ages, b.ages]),
        fb_errors=np.concatenate([a.fb_errors, b.fb_errors]),
        ncc_scores=np.concatenate([a.ncc_scores, b.ncc_scores]),
        local_texture=np.concatenate([a.local_texture, b.local_texture]),
        qualities=np.concatenate([a.qualities, b.qualities]),
        sources=a.sources + b.sources,
    )


def _apply_loftr_early_persistence(
    tracks: TrackSet,
    *,
    state: _LoFTREarlyPersistenceState,
    frame_index: int,
    stamp: float,
    hold_frames: int,
    max_source_frame: int,
    max_per_frame: int,
    max_source_frames: int,
    max_total: int,
    quality_scale: float,
) -> tuple[TrackSet, int]:
    """Keep a tiny accepted LoFTR init-support batch visible briefly.

    This runs after the learned export gate and VINS-safe source selection, so
    it cannot admit raw learned proposals. It only reuses LoFTR observations
    that already survived the normal export path in an early frame.
    """
    frame = int(frame_index)
    state.packets = [packet for packet in state.packets if int(packet.expires_after) >= frame]
    max_per_frame = max(0, int(max_per_frame))
    max_total = max(0, int(max_total))
    added = 0
    existing_ids = {int(track_id) for track_id in tracks.ids.astype(np.int64)} if len(tracks) else set()
    additions: list[TrackSet] = []

    if max_per_frame > 0 and state.packets:
        for packet in state.packets:
            if int(packet.source_frame) == frame:
                continue
            remaining_frame = max(0, max_per_frame - added)
            if remaining_frame <= 0:
                break
            if max_total > 0:
                remaining_total = max(0, max_total - int(state.total_added))
                remaining_frame = min(remaining_frame, remaining_total)
                if remaining_frame <= 0:
                    break
            keep: list[int] = []
            for local_idx, track_id in enumerate(packet.tracks.ids.astype(np.int64)):
                if int(track_id) in existing_ids:
                    continue
                keep.append(int(local_idx))
                existing_ids.add(int(track_id))
                if len(keep) >= remaining_frame:
                    break
            if not keep:
                continue
            local_keep = np.asarray(keep, dtype=np.int64)
            delta_frames = max(1, frame - int(packet.source_frame))
            source = _subset_tracks_by_indices(packet.tracks, local_keep)
            step = packet.pixel_velocity[local_keep]
            points = source.points + step * float(delta_frames)
            prev_points = points - step
            ages = np.clip(
                source.ages.astype(np.int32) + int(delta_frames),
                1,
                127,
            ).astype(np.int32)
            qualities = np.clip(
                source.qualities.astype(np.float32) * float(quality_scale),
                0.05,
                1.0,
            ).astype(np.float32)
            persisted = TrackSet(
                ids=source.ids.copy(),
                prev_points=prev_points.astype(np.float32),
                points=points.astype(np.float32),
                ages=ages,
                fb_errors=source.fb_errors.copy(),
                ncc_scores=source.ncc_scores.copy(),
                local_texture=source.local_texture.copy(),
                qualities=qualities,
                sources=[f"{item}:confirmed_early_persist" for item in source.sources],
            )
            additions.append(persisted)
            added += len(persisted)
            state.total_added += len(persisted)

    if additions:
        for addition in additions:
            tracks = _append_tracksets(tracks, addition)

    if (
        int(hold_frames) > 0
        and int(max_source_frames) > int(state.source_frames_used)
        and frame <= int(max_source_frame)
        and len(tracks) > 0
    ):
        indices = np.arange(len(tracks), dtype=np.int64)
        candidate_mask = np.asarray(
            [
                _is_loftr_source(source)
                and _is_confirmed_sidecar_source(source)
                and "early_persist" not in str(source).lower()
                for source in tracks.sources
            ],
            dtype=bool,
        )
        candidate_indices = indices[candidate_mask]
        if len(candidate_indices):
            order = sorted(
                (int(idx) for idx in candidate_indices.astype(np.int64)),
                key=lambda idx: (-float(tracks.qualities[idx]), int(tracks.ids[idx])),
            )[: max(1, max_per_frame)]
            source_tracks = _subset_tracks_by_indices(tracks, np.asarray(order, dtype=np.int64))
            pixel_velocity = source_tracks.points - source_tracks.prev_points
            state.packets.append(
                _LoFTREarlyPersistencePacket(
                    source_frame=frame,
                    source_stamp=float(stamp),
                    expires_after=frame + max(0, int(hold_frames)),
                    tracks=source_tracks,
                    pixel_velocity=pixel_velocity.astype(np.float32),
                )
            )
            state.source_frames_used += 1

    return tracks, int(added)


def _restore_mirror_classical_after_sidecar_prune(
    tracks: TrackSet,
    mirror_tracks: TrackSet,
    *,
    target_count: int,
) -> TrackSet:
    """Refill KLT/GFTT mirror points after later sidecar gates shrink export.

    In adaptive mirror fallback, VINS-safe selection may reserve room for a
    learned sidecar before later gates or the global sidecar budget prune it.
    Without refill, a frame can accidentally publish fewer measurements than
    the protected KLT mirror even though learned points are only meant to be a
    small sidecar.  Refill only from classical mirror tracks, so this does not
    weaken any learned acceptance gate.
    """

    target_count = max(0, int(target_count))
    if target_count <= 0 or len(tracks) >= target_count or len(mirror_tracks) == 0:
        return tracks
    existing_classical_ids = {
        int(track_id)
        for track_id, source in zip(tracks.ids, tracks.sources)
        if not _is_learned_source(source)
    }
    refill: list[int] = []
    for idx, (track_id, source) in enumerate(zip(mirror_tracks.ids, mirror_tracks.sources)):
        if _is_learned_source(source):
            continue
        key = int(track_id)
        if key in existing_classical_ids:
            continue
        refill.append(int(idx))
        existing_classical_ids.add(key)
        if len(tracks) + len(refill) >= target_count:
            break
    if not refill:
        return tracks
    return _append_tracksets(
        tracks,
        _subset_tracks_by_indices(mirror_tracks, np.asarray(refill, dtype=np.int64)),
    )


def _finalize_mirror_sidecar_export(
    tracks: TrackSet,
    mirror_tracks: TrackSet | None,
    *,
    state: "_ExportIdState",
    max_features: int | None,
    preserve_classical_budget: bool = False,
    persistence_replacement: bool = False,
    selected_feature_index: int = 0,
    persistence_max_selected_frame: int = 4,
    persistence_min_age_advantage: int = 2,
    persistence_single_chain: bool = False,
    persistence_min_gftt_ratio: float = 0.0,
    persistence_source_router: bool = False,
    persistence_allow_all_non_loftr: bool = False,
    persistence_same_grid_cell: bool = False,
    persistence_coverage_monotone: bool = False,
    persistence_grid_rows: int = 4,
    persistence_grid_cols: int = 6,
    persistence_max_per_frame: int = 0,
    prefill_slot_admission: bool = False,
    prefill_slot_max_selected_frame: int = 4,
    prefill_slot_min_age: int = 3,
    prefill_slot_allow_all_non_loftr: bool = False,
    prefill_slot_max_per_frame: int = 0,
    image_shape: tuple[int, int] | None = None,
) -> tuple[TrackSet, _FinalMirrorExportInfo]:
    """Enforce the final KLT-mirror no-harm and feature-budget contract.

    Learned candidates may mutate the hybrid tracker's private state, but only
    the independently tracked KLT mirror is authoritative at publication time.
    If no sidecar survives all gates, return that mirror verbatim. In legacy
    mode, accepted sidecars replace the lowest-ranked mirror tracks. With
    ``preserve_classical_budget`` enabled, sidecars can use only vacant capacity
    below the final cap and can never evict an independent KLT observation.
    Experimental ``persistence_replacement`` instead permits a deterministic
    early birth-for-birth swap. Its historical default is confirmed XFeat;
    the optional source router can admit confirmed non-LoFTR learned lineages
    under the same-cell or coverage-monotone donor contract and per-frame cap.
    ``prefill_slot_admission`` keeps every carried mirror observation, admits a
    bounded confirmed candidate before the mirror's age-1 GFTT birth pool, and
    uses that pool only for the remaining capacity. Both experimental paths
    change counterfactual newborn GFTT publication, but neither removes a
    carried source="klt" observation.
    """

    if mirror_tracks is None:
        return tracks, _FinalMirrorExportInfo()

    mirror = _deduplicate_tracks_for_vins(mirror_tracks)
    sidecars = _select_sidecar_sources(tracks)
    input_sidecars = len(sidecars)
    cap = 0 if max_features is None else max(0, int(max_features))
    if bool(persistence_replacement) and bool(prefill_slot_admission):
        raise ValueError(
            "persistence replacement and pre-refill slot admission are mutually exclusive"
        )
    prefill_newborn_mask = np.asarray(
        [
            str(source).lower() == "gftt" and int(age) == 1
            for source, age in zip(mirror.sources, mirror.ages)
        ],
        dtype=bool,
    )
    prefill_carried_count = int(np.count_nonzero(~prefill_newborn_mask))
    prefill_newborn_count = int(np.count_nonzero(prefill_newborn_mask))
    prefill_vacant_capacity = (
        max(0, int(cap) - prefill_carried_count) if cap > 0 else 0
    )

    if input_sidecars == 0:
        # Strong no-harm invariant: rejection is a true rollback, including
        # track ids, order, positions, ages, and frontend qualities.
        restored = mirror
        dropped_classical = 0
        if cap > 0 and len(restored) > cap:
            restored = _subset_tracks_by_indices(
                restored,
                np.arange(cap, dtype=np.int64),
            )
            dropped_classical = len(mirror) - len(restored)
        return restored, _FinalMirrorExportInfo(
            active=True,
            preserve_classical_budget=bool(preserve_classical_budget),
            zero_sidecar_restore=True,
            dropped_classical_for_cap=dropped_classical,
            persistence_replacement_active=bool(persistence_replacement),
            persistence_single_chain_active=bool(persistence_single_chain),
            persistence_committed_sidecar_id=(
                int(state.persistence_committed_sidecar_id)
                if state.persistence_committed_sidecar_id is not None
                else -1
            ),
            persistence_churn_guard_active=float(persistence_min_gftt_ratio) > 0.0,
            persistence_churn_guard_decision=(
                -1
                if state.persistence_churn_guard_armed is None
                else int(bool(state.persistence_churn_guard_armed))
            ),
            persistence_churn_guard_decision_frame=int(
                state.persistence_churn_guard_decision_frame
            ),
            persistence_churn_guard_gftt_births=int(
                state.persistence_churn_guard_gftt_births
            ),
            persistence_churn_guard_denominator=int(
                state.persistence_churn_guard_denominator
            ),
            persistence_churn_guard_ratio=float(
                state.persistence_churn_guard_ratio
            ),
            persistence_source_router_active=bool(persistence_source_router),
            persistence_same_cell_active=bool(persistence_same_grid_cell),
            persistence_coverage_monotone_active=bool(
                persistence_coverage_monotone
            ),
            persistence_per_frame_cap=max(0, int(persistence_max_per_frame)),
            prefill_slot_active=bool(prefill_slot_admission),
            prefill_slot_carried_observations=prefill_carried_count,
            prefill_slot_baseline_newborns=prefill_newborn_count,
            prefill_slot_vacant_capacity=prefill_vacant_capacity,
            prefill_slot_per_frame_cap=max(0, int(prefill_slot_max_per_frame)),
        )

    # Main hybrid and mirror KLT trackers allocate ids independently. Their
    # numeric ids can collide even when they refer to different observations.
    if len(mirror.ids):
        state.next_export_id = max(
            int(state.next_export_id),
            int(np.max(mirror.ids.astype(np.int64))) + 1,
        )
    original_sidecar_ids = sidecars.ids.copy()
    sidecars = _remap_recovered_export_ids(sidecars, state)
    remapped_sidecar_ids = int(np.count_nonzero(sidecars.ids != original_sidecar_ids))
    sidecars = _deduplicate_tracks_for_vins(sidecars)

    if bool(prefill_slot_admission):
        return _finalize_prefill_slot_mirror_export(
            mirror,
            sidecars,
            max_features=cap,
            selected_feature_index=int(selected_feature_index),
            max_selected_frame=int(prefill_slot_max_selected_frame),
            min_age=int(prefill_slot_min_age),
            allow_all_non_loftr=bool(prefill_slot_allow_all_non_loftr),
            max_per_frame=int(prefill_slot_max_per_frame),
            input_sidecars=input_sidecars,
            remapped_sidecar_ids=remapped_sidecar_ids,
        )

    if bool(persistence_replacement):
        return _finalize_persistence_conditioned_mirror_export(
            mirror,
            sidecars,
            state=state,
            single_chain=bool(persistence_single_chain),
            min_gftt_ratio=float(persistence_min_gftt_ratio),
            source_router=bool(persistence_source_router),
            allow_all_non_loftr=bool(persistence_allow_all_non_loftr),
            same_grid_cell=bool(persistence_same_grid_cell),
            coverage_monotone=bool(persistence_coverage_monotone),
            grid_rows=int(persistence_grid_rows),
            grid_cols=int(persistence_grid_cols),
            max_per_frame=int(persistence_max_per_frame),
            image_shape=image_shape,
            max_features=cap,
            selected_feature_index=int(selected_feature_index),
            max_selected_frame=int(persistence_max_selected_frame),
            min_age_advantage=int(persistence_min_age_advantage),
            input_sidecars=input_sidecars,
            remapped_sidecar_ids=remapped_sidecar_ids,
        )

    dropped_sidecars = 0
    dropped_sidecars_for_classical_budget = 0
    sidecar_cap = cap
    if bool(preserve_classical_budget) and cap > 0:
        sidecar_cap = max(0, cap - min(len(mirror), cap))
        dropped_sidecars_for_classical_budget = max(0, len(sidecars) - sidecar_cap)
    if sidecar_cap > 0 and len(sidecars) > sidecar_cap:
        order = _source_selection_order(
            sidecars,
            np.arange(len(sidecars), dtype=np.int64),
            prefer_age=False,
        )
        keep = np.sort(order[:sidecar_cap].astype(np.int64))
        dropped_sidecars = len(sidecars) - len(keep)
        sidecars = _subset_tracks_by_indices(sidecars, keep)
    elif sidecar_cap == 0 and cap > 0:
        dropped_sidecars = len(sidecars)
        sidecars = TrackSet.empty()

    if bool(preserve_classical_budget) and len(sidecars) == 0:
        restored = mirror
        dropped_classical = 0
        if cap > 0 and len(restored) > cap:
            restored = _subset_tracks_by_indices(
                restored,
                np.arange(cap, dtype=np.int64),
            )
            dropped_classical = len(mirror) - len(restored)
        return restored, _FinalMirrorExportInfo(
            active=True,
            preserve_classical_budget=True,
            zero_sidecar_restore=True,
            input_sidecars=input_sidecars,
            kept_sidecars=0,
            dropped_sidecars_for_cap=dropped_sidecars,
            dropped_sidecars_for_classical_budget=(
                dropped_sidecars_for_classical_budget
            ),
            dropped_classical_for_cap=dropped_classical,
            remapped_sidecar_ids=remapped_sidecar_ids,
        )

    classical_budget = (
        len(mirror)
        if cap <= 0
        else (
            min(len(mirror), cap)
            if bool(preserve_classical_budget)
            else max(0, cap - len(sidecars))
        )
    )
    classical = mirror
    dropped_classical = 0
    if len(classical) > classical_budget:
        order = _source_selection_order(
            classical,
            np.arange(len(classical), dtype=np.int64),
            prefer_age=True,
        )
        keep = np.sort(order[:classical_budget].astype(np.int64))
        dropped_classical = len(classical) - len(keep)
        classical = _subset_tracks_by_indices(classical, keep)

    finalized = _deduplicate_tracks_for_vins(_append_tracksets(classical, sidecars))
    if cap > 0 and len(finalized) > cap:
        raise RuntimeError(
            f"final mirror-sidecar export exceeds cap: {len(finalized)} > {cap}"
        )
    if len(np.unique(finalized.ids.astype(np.int64))) != len(finalized):
        raise RuntimeError("final mirror-sidecar export contains duplicate feature ids")

    return finalized, _FinalMirrorExportInfo(
        active=True,
        preserve_classical_budget=bool(preserve_classical_budget),
        input_sidecars=input_sidecars,
        kept_sidecars=len(sidecars),
        dropped_sidecars_for_cap=dropped_sidecars,
        dropped_sidecars_for_classical_budget=(
            dropped_sidecars_for_classical_budget
        ),
        dropped_classical_for_cap=dropped_classical,
        remapped_sidecar_ids=remapped_sidecar_ids,
    )


def _finalize_prefill_slot_mirror_export(
    mirror: TrackSet,
    sidecars: TrackSet,
    *,
    max_features: int,
    selected_feature_index: int,
    max_selected_frame: int,
    min_age: int,
    allow_all_non_loftr: bool,
    max_per_frame: int,
    input_sidecars: int,
    remapped_sidecar_ids: int,
) -> tuple[TrackSet, _FinalMirrorExportInfo]:
    """Admit confirmed sidecars before deterministic same-frame GFTT refill.

    The cap-limited independent mirror is the baseline reference. Every
    carried observation is retained. Only age-1 ``gftt`` births can be omitted
    when a candidate consumes pre-refill capacity. The resulting opportunity
    cost is explicit and must not be described as free/no-harm capacity.
    """

    cap = max(0, int(max_features))
    frame_cap = max(0, int(max_per_frame))
    baseline_count = min(len(mirror), cap) if cap > 0 else len(mirror)
    baseline = _subset_tracks_by_indices(
        mirror,
        np.arange(baseline_count, dtype=np.int64),
    )
    base_cap_drop = max(0, len(mirror) - len(baseline))
    newborn_mask = np.asarray(
        [
            str(source).lower() == "gftt" and int(age) == 1
            for source, age in zip(baseline.sources, baseline.ages)
        ],
        dtype=bool,
    )
    newborn_indices = np.flatnonzero(newborn_mask).astype(np.int64)
    carried_indices = np.flatnonzero(~newborn_mask).astype(np.int64)
    carried_count = len(carried_indices)
    newborn_count = len(newborn_indices)
    vacant_capacity = max(0, cap - carried_count) if cap > 0 else 0

    raw_order = _source_selection_order(
        sidecars,
        np.arange(len(sidecars), dtype=np.int64),
        prefer_age=True,
    )
    source_eligible = np.asarray(
        [
            int(idx)
            for idx in raw_order
            if _is_confirmed_sidecar_source(sidecars.sources[int(idx)])
            and (
                (
                    bool(allow_all_non_loftr)
                    and _is_non_loftr_learned_source(sidecars.sources[int(idx)])
                )
                or (
                    not bool(allow_all_non_loftr)
                    and _is_xfeat_source(sidecars.sources[int(idx)])
                )
            )
        ],
        dtype=np.int64,
    )
    eligible = np.asarray(
        [
            int(idx)
            for idx in source_eligible
            if int(sidecars.ages[int(idx)]) >= max(1, int(min_age))
        ],
        dtype=np.int64,
    )
    source_suppressed = max(0, len(sidecars) - len(source_eligible))
    age_suppressed = max(0, len(source_eligible) - len(eligible))
    horizon_blocked = bool(
        len(eligible) > 0
        and int(selected_feature_index) > int(max_selected_frame)
    )
    admission_limit = vacant_capacity
    if frame_cap > 0:
        admission_limit = min(admission_limit, frame_cap)
    selected_indices = (
        np.empty((0,), dtype=np.int64)
        if horizon_blocked or cap <= 0
        else eligible[:admission_limit]
    )
    selected = (
        _subset_tracks_by_indices(sidecars, selected_indices)
        if len(selected_indices)
        else TrackSet.empty()
    )
    dropped_sidecars = max(0, len(eligible) - len(selected))

    if len(selected) == 0:
        return baseline, _FinalMirrorExportInfo(
            active=True,
            zero_sidecar_restore=True,
            input_sidecars=int(input_sidecars),
            kept_sidecars=0,
            dropped_classical_for_cap=int(base_cap_drop),
            remapped_sidecar_ids=int(remapped_sidecar_ids),
            prefill_slot_active=True,
            prefill_slot_horizon_blocked=bool(horizon_blocked),
            prefill_slot_carried_observations=int(carried_count),
            prefill_slot_baseline_newborns=int(newborn_count),
            prefill_slot_vacant_capacity=int(vacant_capacity),
            prefill_slot_eligible_sidecars=int(len(eligible)),
            prefill_slot_admitted_sidecars=0,
            prefill_slot_omitted_newborns=0,
            prefill_slot_dropped_sidecars=int(dropped_sidecars),
            prefill_slot_source_suppressed=int(source_suppressed),
            prefill_slot_age_suppressed=int(age_suppressed),
            prefill_slot_per_frame_cap=int(frame_cap),
        )

    remaining_for_newborns = max(0, cap - carried_count - len(selected))
    kept_newborn_indices = newborn_indices[:remaining_for_newborns]
    classical_keep_indices = np.sort(
        np.concatenate([carried_indices, kept_newborn_indices]).astype(np.int64)
    )
    classical = _subset_tracks_by_indices(baseline, classical_keep_indices)
    omitted_newborns = max(0, newborn_count - len(kept_newborn_indices))
    finalized = _deduplicate_tracks_for_vins(
        _append_tracksets(classical, selected)
    )
    if len(finalized) > cap:
        raise RuntimeError(
            f"pre-refill slot export exceeds cap: {len(finalized)} > {cap}"
        )
    if len(np.unique(finalized.ids.astype(np.int64))) != len(finalized):
        raise RuntimeError("pre-refill slot export contains duplicate feature ids")

    return finalized, _FinalMirrorExportInfo(
        active=True,
        input_sidecars=int(input_sidecars),
        kept_sidecars=int(len(selected)),
        dropped_classical_for_cap=int(base_cap_drop + omitted_newborns),
        remapped_sidecar_ids=int(remapped_sidecar_ids),
        prefill_slot_active=True,
        prefill_slot_horizon_blocked=False,
        prefill_slot_carried_observations=int(carried_count),
        prefill_slot_baseline_newborns=int(newborn_count),
        prefill_slot_vacant_capacity=int(vacant_capacity),
        prefill_slot_eligible_sidecars=int(len(eligible)),
        prefill_slot_admitted_sidecars=int(len(selected)),
        prefill_slot_omitted_newborns=int(omitted_newborns),
        prefill_slot_dropped_sidecars=int(dropped_sidecars),
        prefill_slot_source_suppressed=int(source_suppressed),
        prefill_slot_age_suppressed=int(age_suppressed),
        prefill_slot_per_frame_cap=int(frame_cap),
    )


def _finalize_persistence_conditioned_mirror_export(
    mirror: TrackSet,
    sidecars: TrackSet,
    *,
    state: "_ExportIdState",
    single_chain: bool,
    min_gftt_ratio: float,
    source_router: bool,
    allow_all_non_loftr: bool,
    same_grid_cell: bool,
    coverage_monotone: bool,
    grid_rows: int,
    grid_cols: int,
    max_per_frame: int,
    image_shape: tuple[int, int] | None,
    max_features: int,
    selected_feature_index: int,
    max_selected_frame: int,
    min_age_advantage: int,
    input_sidecars: int,
    remapped_sidecar_ids: int,
) -> tuple[TrackSet, _FinalMirrorExportInfo]:
    """Apply the preregistered early birth-for-birth replacement rule.

    The optional source router admits only confirmed non-LoFTR learned
    lineages, can require a same-cell GFTT birth or a coverage-monotone newborn
    donor, and caps changes per frame. Defaults preserve the historical
    XFeat-only persistence path.
    """

    cap = max(0, int(max_features))
    if cap <= 0:
        selected = sidecars
        suppressed = 0
        if bool(single_chain):
            order = _source_selection_order(
                sidecars,
                np.asarray(
                    [
                        idx
                        for idx, source in enumerate(sidecars.sources)
                        if _is_xfeat_source(source)
                        and _is_confirmed_sidecar_source(source)
                    ],
                    dtype=np.int64,
                ),
                prefer_age=True,
            )
            committed = state.persistence_committed_sidecar_id
            if committed is not None:
                order = np.asarray(
                    [idx for idx in order if int(sidecars.ids[int(idx)]) == committed],
                    dtype=np.int64,
                )
            else:
                order = order[:1]
            selected = (
                _subset_tracks_by_indices(sidecars, order[:1])
                if len(order)
                else TrackSet.empty()
            )
            if len(selected) and committed is None:
                state.persistence_committed_sidecar_id = int(selected.ids[0])
            suppressed = len(sidecars) - len(selected)
        finalized = _deduplicate_tracks_for_vins(_append_tracksets(mirror, selected))
        return finalized, _FinalMirrorExportInfo(
            active=True,
            input_sidecars=int(input_sidecars),
            kept_sidecars=len(selected),
            remapped_sidecar_ids=int(remapped_sidecar_ids),
            persistence_replacement_active=True,
            persistence_eligible_sidecars=int(
                sum(
                    _is_xfeat_source(source) and _is_confirmed_sidecar_source(source)
                    for source in sidecars.sources
                )
            ),
            persistence_single_chain_active=bool(single_chain),
            persistence_committed_sidecar_id=(
                int(state.persistence_committed_sidecar_id)
                if state.persistence_committed_sidecar_id is not None
                else -1
            ),
            persistence_single_chain_suppressed=int(suppressed),
        )

    baseline_count = min(len(mirror), cap)
    baseline = _subset_tracks_by_indices(
        mirror,
        np.arange(baseline_count, dtype=np.int64),
    )
    base_cap_drop = len(mirror) - len(baseline)
    raw_sidecar_order = _source_selection_order(
        sidecars,
        np.arange(len(sidecars), dtype=np.int64),
        prefer_age=True,
    )
    eligible_source_order = np.asarray(
        [
            idx
            for idx in raw_sidecar_order
            if _is_confirmed_sidecar_source(sidecars.sources[int(idx)])
            and (
                (
                    bool(allow_all_non_loftr)
                    and _is_non_loftr_learned_source(sidecars.sources[int(idx)])
                )
                or (
                    not bool(allow_all_non_loftr)
                    and _is_xfeat_source(sidecars.sources[int(idx)])
                )
            )
        ],
        dtype=np.int64,
    )
    gftt_indices = np.asarray(
        [
            idx
            for idx, source in enumerate(baseline.sources)
            if str(source).lower() == "gftt"
            and (
                not bool(source_router)
                or int(baseline.ages[int(idx)]) == 1
            )
        ],
        dtype=np.int64,
    )
    churn_guard_active = float(min_gftt_ratio) > 0.0
    if (
        churn_guard_active
        and state.persistence_churn_guard_armed is None
        and int(selected_feature_index) <= int(max_selected_frame)
        and len(eligible_source_order) > 0
        and len(gftt_indices) > 0
    ):
        denominator = max(1, int(len(baseline)))
        ratio = float(len(gftt_indices)) / float(denominator)
        state.persistence_churn_guard_armed = bool(
            ratio >= float(min_gftt_ratio)
        )
        state.persistence_churn_guard_decision_frame = int(selected_feature_index)
        state.persistence_churn_guard_gftt_births = int(len(gftt_indices))
        state.persistence_churn_guard_denominator = int(denominator)
        state.persistence_churn_guard_ratio = float(ratio)

    sidecar_order = (
        eligible_source_order if bool(source_router) else raw_sidecar_order
    )
    source_suppressed = (
        len(sidecars) - len(eligible_source_order) if bool(source_router) else 0
    )
    single_chain_suppressed = 0
    if churn_guard_active and state.persistence_churn_guard_armed is False:
        sidecar_order = np.empty((0,), dtype=np.int64)
    elif bool(source_router) and int(selected_feature_index) > int(max_selected_frame):
        sidecar_order = np.empty((0,), dtype=np.int64)
    elif bool(single_chain):
        committed = state.persistence_committed_sidecar_id
        if int(selected_feature_index) > int(max_selected_frame):
            sidecar_order = np.empty((0,), dtype=np.int64)
        elif committed is not None:
            sidecar_order = np.asarray(
                [
                    idx
                    for idx in eligible_source_order
                    if int(sidecars.ids[int(idx)]) == int(committed)
                ],
                dtype=np.int64,
            )
        else:
            sidecar_order = eligible_source_order[:1]
        single_chain_suppressed = len(sidecars) - len(sidecar_order)
    vacant = max(0, cap - len(baseline))
    frame_cap = max(0, int(max_per_frame))
    vacant_limit = vacant if frame_cap <= 0 else min(vacant, frame_cap)
    selected_sidecars = [int(idx) for idx in sidecar_order[:vacant_limit]]
    remaining_sidecars = [int(idx) for idx in sidecar_order[vacant_limit:]]

    eligible_source_set = {int(value) for value in eligible_source_order}
    replacement_candidates = [
        idx
        for idx in remaining_sidecars
        if int(idx) in eligible_source_set
    ]
    if len(gftt_indices):
        weakest_gftt_first = list(
            reversed(
                _source_selection_order(
                    baseline,
                    gftt_indices,
                    prefer_age=True,
                ).tolist()
            )
        )
    else:
        weakest_gftt_first = []

    horizon_blocked = bool(
        (
            len(eligible_source_order)
            if bool(single_chain) or bool(source_router)
            else replacement_candidates
        )
        and int(selected_feature_index) > int(max_selected_frame)
    )
    replaced_gftt: list[int] = []
    replaced_age_advantages: list[int] = []
    replacement_cell_mismatches = 0
    same_cell_suppressed = 0
    coverage_monotone_suppressed = 0
    cross_cell_replacements = 0
    donor_cell_remaining: list[int] = []
    grid_cells_before = -1
    grid_cells_after = -1
    frame_cap_suppressed = 0
    if not horizon_blocked:
        available_gftt = weakest_gftt_first.copy()
        age_advantage = max(1, int(min_age_advantage))
        sidecar_cells: dict[int, tuple[int, int]] = {}
        gftt_cells: dict[int, tuple[int, int]] = {}
        baseline_cells: dict[int, tuple[int, int]] = {}
        current_cell_counts: dict[tuple[int, int], int] = {}
        spatial_guard = bool(same_grid_cell) or bool(coverage_monotone)
        if spatial_guard and image_shape is not None:
            spatial_sidecar_indices = sorted(
                set(selected_sidecars + replacement_candidates)
            )
            sidecar_cell_values = _grid_cell_indices(
                sidecars.points[
                    np.asarray(spatial_sidecar_indices, dtype=np.int64)
                ],
                image_shape,
                rows=max(1, int(grid_rows)),
                cols=max(1, int(grid_cols)),
            )
            sidecar_cells = {
                int(idx): (int(cell[0]), int(cell[1]))
                for idx, cell in zip(spatial_sidecar_indices, sidecar_cell_values)
            }
            baseline_cell_values = _grid_cell_indices(
                baseline.points,
                image_shape,
                rows=max(1, int(grid_rows)),
                cols=max(1, int(grid_cols)),
            )
            baseline_cells = {
                int(idx): (int(cell[0]), int(cell[1]))
                for idx, cell in enumerate(baseline_cell_values)
            }
            gftt_cells = {
                int(idx): baseline_cells[int(idx)]
                for idx in gftt_indices.tolist()
            }
            for cell in baseline_cells.values():
                current_cell_counts[cell] = current_cell_counts.get(cell, 0) + 1
            grid_cells_before = len(current_cell_counts)
            for sidecar_idx in selected_sidecars:
                cell = sidecar_cells[int(sidecar_idx)]
                current_cell_counts[cell] = current_cell_counts.get(cell, 0) + 1
        for sidecar_idx in replacement_candidates:
            if frame_cap > 0 and len(selected_sidecars) >= frame_cap:
                frame_cap_suppressed += 1
                continue
            if (bool(same_grid_cell) or bool(coverage_monotone)) and image_shape is None:
                same_cell_suppressed += 1
                if bool(coverage_monotone):
                    coverage_monotone_suppressed += 1
                continue
            valid_targets: list[tuple[tuple[int, int, int], int]] = []
            sidecar_cell = sidecar_cells.get(int(sidecar_idx))
            current_occupied = sum(
                count > 0 for count in current_cell_counts.values()
            )
            for pos, gftt_idx in enumerate(available_gftt):
                if int(sidecars.ages[sidecar_idx]) < (
                    int(baseline.ages[gftt_idx]) + age_advantage
                ):
                    continue
                victim_cell = gftt_cells.get(int(gftt_idx))
                if bool(same_grid_cell) and sidecar_cell != victim_cell:
                    continue
                if bool(coverage_monotone):
                    if sidecar_cell is None or victim_cell is None:
                        continue
                    donor_remaining = (
                        current_cell_counts.get(victim_cell, 0)
                        - 1
                        + int(sidecar_cell == victim_cell)
                    )
                    if donor_remaining < 1:
                        continue
                    after_counts = dict(current_cell_counts)
                    after_counts[victim_cell] = after_counts.get(victim_cell, 0) - 1
                    after_counts[sidecar_cell] = after_counts.get(sidecar_cell, 0) + 1
                    after_occupied = sum(count > 0 for count in after_counts.values())
                    if after_occupied < current_occupied:
                        continue
                same_cell_priority = int(sidecar_cell != victim_cell)
                donor_occupancy_priority = -current_cell_counts.get(victim_cell, 0)
                valid_targets.append(
                    (
                        (same_cell_priority, donor_occupancy_priority, int(pos)),
                        int(pos),
                    )
                )
            target_pos = (
                min(valid_targets, key=lambda item: item[0])[1]
                if valid_targets
                else None
            )
            if target_pos is None:
                if bool(same_grid_cell):
                    same_cell_suppressed += 1
                if bool(coverage_monotone):
                    coverage_monotone_suppressed += 1
                continue
            selected_sidecars.append(int(sidecar_idx))
            victim = int(available_gftt.pop(int(target_pos)))
            replaced_gftt.append(victim)
            replaced_age_advantages.append(
                int(sidecars.ages[int(sidecar_idx)]) - int(baseline.ages[victim])
            )
            if (
                bool(same_grid_cell)
                and sidecar_cells.get(int(sidecar_idx)) != gftt_cells.get(victim)
            ):
                replacement_cell_mismatches += 1
            if bool(coverage_monotone):
                victim_cell = gftt_cells[victim]
                sidecar_cell = sidecar_cells[int(sidecar_idx)]
                current_cell_counts[victim_cell] -= 1
                current_cell_counts[sidecar_cell] = (
                    current_cell_counts.get(sidecar_cell, 0) + 1
                )
                remaining = int(current_cell_counts[victim_cell])
                donor_cell_remaining.append(remaining)
                if sidecar_cell != victim_cell:
                    cross_cell_replacements += 1

        if spatial_guard and image_shape is not None:
            grid_cells_after = sum(
                count > 0 for count in current_cell_counts.values()
            )

    if bool(single_chain) and selected_sidecars and state.persistence_committed_sidecar_id is None:
        state.persistence_committed_sidecar_id = int(
            sidecars.ids[int(selected_sidecars[0])]
        )

    classical_keep = np.ones((len(baseline),), dtype=bool)
    if replaced_gftt:
        classical_keep[np.asarray(replaced_gftt, dtype=np.int64)] = False
    classical = _subset_tracks_by_indices(
        baseline,
        np.flatnonzero(classical_keep).astype(np.int64),
    )
    selected_sidecars = sorted(set(selected_sidecars))
    kept_sidecars = _subset_tracks_by_indices(
        sidecars,
        np.asarray(selected_sidecars, dtype=np.int64),
    ) if selected_sidecars else TrackSet.empty()
    finalized = _deduplicate_tracks_for_vins(_append_tracksets(classical, kept_sidecars))
    if len(finalized) > cap:
        raise RuntimeError(
            f"persistence-conditioned mirror export exceeds cap: {len(finalized)} > {cap}"
        )
    if len(np.unique(finalized.ids.astype(np.int64))) != len(finalized):
        raise RuntimeError("persistence-conditioned export contains duplicate feature ids")

    dropped_sidecars = len(sidecars) - len(kept_sidecars)
    return finalized, _FinalMirrorExportInfo(
        active=True,
        zero_sidecar_restore=len(kept_sidecars) == 0,
        input_sidecars=int(input_sidecars),
        kept_sidecars=len(kept_sidecars),
        dropped_sidecars_for_cap=int(dropped_sidecars),
        dropped_classical_for_cap=int(base_cap_drop + len(replaced_gftt)),
        remapped_sidecar_ids=int(remapped_sidecar_ids),
        persistence_replacement_active=True,
        persistence_horizon_blocked=bool(horizon_blocked),
        persistence_eligible_sidecars=len(replacement_candidates),
        persistence_eligible_gftt=len(gftt_indices),
        persistence_replaced_gftt=len(replaced_gftt),
        persistence_dropped_sidecars=int(dropped_sidecars),
        persistence_single_chain_active=bool(single_chain),
        persistence_committed_sidecar_id=(
            int(state.persistence_committed_sidecar_id)
            if state.persistence_committed_sidecar_id is not None
            else -1
        ),
        persistence_single_chain_suppressed=int(single_chain_suppressed),
        persistence_churn_guard_active=bool(churn_guard_active),
        persistence_churn_guard_decision=(
            -1
            if state.persistence_churn_guard_armed is None
            else int(bool(state.persistence_churn_guard_armed))
        ),
        persistence_churn_guard_decision_frame=int(
            state.persistence_churn_guard_decision_frame
        ),
        persistence_churn_guard_gftt_births=int(
            state.persistence_churn_guard_gftt_births
        ),
        persistence_churn_guard_denominator=int(
            state.persistence_churn_guard_denominator
        ),
        persistence_churn_guard_ratio=float(
            state.persistence_churn_guard_ratio
        ),
        persistence_source_router_active=bool(source_router),
        persistence_source_eligible_sidecars=len(eligible_source_order),
        persistence_source_suppressed=int(source_suppressed),
        persistence_same_cell_active=bool(same_grid_cell),
        persistence_same_cell_suppressed=int(same_cell_suppressed),
        persistence_coverage_monotone_active=bool(coverage_monotone),
        persistence_coverage_monotone_suppressed=int(
            coverage_monotone_suppressed
        ),
        persistence_grid_cells_before=int(grid_cells_before),
        persistence_grid_cells_after=int(grid_cells_after),
        persistence_grid_cell_delta=(
            int(grid_cells_after - grid_cells_before)
            if grid_cells_before >= 0 and grid_cells_after >= 0
            else 0
        ),
        persistence_cross_cell_replacements=int(cross_cell_replacements),
        persistence_donor_cell_min_remaining=(
            min(donor_cell_remaining) if donor_cell_remaining else -1
        ),
        persistence_per_frame_cap=int(frame_cap),
        persistence_per_frame_cap_suppressed=int(frame_cap_suppressed),
        persistence_replaced_gftt_max_age=(
            max(int(baseline.ages[idx]) for idx in replaced_gftt)
            if replaced_gftt
            else -1
        ),
        persistence_replacement_min_age_advantage_actual=(
            min(replaced_age_advantages) if replaced_age_advantages else -1
        ),
        persistence_replacement_cell_mismatches=int(replacement_cell_mismatches),
    )


def _apply_learned_export_degradation_gate(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    tracker_recovery_reason: str,
    tracker_learned_mode: str,
    min_classical_tracks: int,
    min_classical_grid: float,
    min_age: int,
    min_quality: float,
    min_ncc: float,
    max_fb: float,
    loftr_min_age: int | None = None,
    loftr_min_quality: float | None = None,
    loftr_min_ncc: float | None = None,
    loftr_max_fb: float | None = None,
    camera: dict | None = None,
    geometry_cfg: _SidecarGeometryConfig | None = None,
    benefit_gate: bool = False,
    benefit_loftr_only: bool = False,
    min_grid_gain: float = 0.0,
    min_new_cells: int = 0,
    min_new_cell_ratio: float = 0.0,
    max_per_new_cell: int = 1,
    coverage_gain_max_classical_tracks: int = 0,
    min_classical_motion_px: float = 0.0,
    min_classical_age: float = 0.0,
    weak_cell_rescue: bool = False,
    non_loftr_weak_cell_rescue: bool = False,
    weak_cell_max_count: int = 0,
    weak_cell_min_candidates: int = 0,
    weak_cell_max_occupancy: int = 0,
    weak_cell_min_classical_motion_px: float = 0.0,
    weak_cell_max_classical_grid: float = 1.0,
    weak_cell_max_classical_tracks: int = 0,
    mature_cell_rescue: bool = False,
    mature_cell_max_count: int = 0,
    mature_cell_min_candidates: int = 0,
    mature_cell_min_classical_age: float = 0.0,
    mature_cell_min_classical_motion_px: float = 0.0,
    mature_cell_max_classical_grid: float = 1.0,
    mature_cell_max_per_cell: int = 1,
    mature_cell_max_occupancy: int = 8,
    loftr_planar_rescue: bool = False,
    loftr_planar_max_count: int = 0,
    loftr_planar_min_candidates: int = 0,
    loftr_planar_max_classical_grid: float = 1.0,
    loftr_planar_min_classical_motion_px: float = 0.0,
    loftr_weak_cell_rescue: bool = False,
    loftr_weak_cell_max_count: int = 0,
    loftr_weak_cell_max_occupancy: int = 48,
    loftr_rescue_max_classical_tracks: int = 0,
    loftr_support_max_init_parallax_px: float = 0.0,
    loftr_support_max_classical_motion_px: float = 0.0,
    init_parallax_mean_step_px: float = float("nan"),
    non_loftr_requires_degraded_mode: bool = False,
    loftr_continuation_state: _LoFTRSeededContinuationGateState | None = None,
    frame_index: int = -1,
    loftr_continuation_max_gap: int = 1,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    if len(tracks) == 0:
        return tracks, _LearnedExportGateInfo(
            active=True,
            degraded=True,
            reason="empty_tracks",
            classical_count=0,
            classical_grid_coverage=0.0,
            dropped_learned=0,
            geometry_dropped=0,
            geometry_reason="empty",
        )

    indices = np.arange(len(tracks), dtype=np.int64)
    classical_mask = _classical_backbone_mask(tracks)
    sidecar_mask = ~classical_mask
    classical_count = int(np.count_nonzero(classical_mask))
    classical_grid = _track_grid_coverage(tracks, image_shape, classical_mask)
    classical_median_age = _median_masked(tracks.ages, classical_mask)

    degraded_reasons: list[str] = []
    if classical_count < int(min_classical_tracks):
        degraded_reasons.append("low_classical_tracks")
    if classical_grid < float(min_classical_grid):
        degraded_reasons.append("low_classical_grid")
    recovery_reason = str(tracker_recovery_reason or "").lower()
    reason_tokens = (
        "low_grid",
        "grid",
        "dropout",
        "degraded",
        "low_texture",
        "texture",
        "churn",
        "planar",
        "extreme",
        "few_tracks",
        "low_tracks",
    )
    matched_tokens = [token for token in reason_tokens if token in recovery_reason]
    if matched_tokens and recovery_reason not in {"healthy", "n/a", "none"}:
        degraded_reasons.append("frontend_" + matched_tokens[0])
    learned_mode = str(tracker_learned_mode or "").lower()
    if learned_mode in {
        "extreme_textureless",
        "planar_near_wall",
        "severe_low_texture",
        "low_texture",
    }:
        degraded_reasons.append("learned_mode_" + learned_mode)

    sidecar_total = int(np.count_nonzero(sidecar_mask))
    if not degraded_reasons:
        keep = indices[classical_mask]
        dropped = sidecar_total
        return _subset_tracks_by_indices(tracks, keep), _LearnedExportGateInfo(
            active=True,
            degraded=False,
            reason="classical_healthy",
            classical_count=classical_count,
            classical_grid_coverage=classical_grid,
            dropped_learned=dropped,
            geometry_dropped=0,
            geometry_reason="not_degraded",
            classical_median_age=classical_median_age,
        )

    ncc = np.asarray(tracks.ncc_scores, dtype=np.float32)
    # Some newly detected tracks have NCC=1 by construction; still require the
    # age/quality gates so a one-frame learned pair cannot directly perturb VINS.
    loftr_source_mask = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
    quality_threshold = np.full((len(tracks),), float(min_quality), dtype=np.float32)
    ncc_threshold = np.full((len(tracks),), float(min_ncc), dtype=np.float32)
    fb_threshold = np.full((len(tracks),), float(max_fb), dtype=np.float32)
    if loftr_min_quality is not None:
        quality_threshold[loftr_source_mask] = float(loftr_min_quality)
    if loftr_min_ncc is not None:
        ncc_threshold[loftr_source_mask] = float(loftr_min_ncc)
    if loftr_max_fb is not None:
        fb_threshold[loftr_source_mask] = float(loftr_max_fb)
    age_threshold = _source_specific_sidecar_age_thresholds(
        tracks,
        min_age=min_age,
        loftr_min_age=loftr_min_age,
        require_confirmed=bool(
            geometry_cfg is not None and geometry_cfg.require_confirmed_learned
        ),
    )
    accepted_sidecar = (
        sidecar_mask
        & (tracks.ages >= age_threshold)
        & (tracks.qualities >= quality_threshold)
        & (ncc >= ncc_threshold)
        & (tracks.fb_errors <= fb_threshold)
    )
    if geometry_cfg is not None and geometry_cfg.require_confirmed_learned:
        confirmed_or_classical = np.asarray(
            [
                (not _is_learned_source(source)) or _is_confirmed_sidecar_source(source)
                for source in tracks.sources
            ],
            dtype=bool,
        )
        accepted_sidecar &= confirmed_or_classical
    if bool(non_loftr_requires_degraded_mode) and np.any(accepted_sidecar):
        learned_mode = str(tracker_learned_mode or "").lower()
        recovery_for_mode = str(tracker_recovery_reason or "").lower()
        if not _allows_non_loftr_backend_sidecar_mode(learned_mode, recovery_for_mode):
            non_loftr_sidecar = np.asarray(
                [_is_non_loftr_learned_source(source) for source in tracks.sources],
                dtype=bool,
            )
            accepted_sidecar &= ~non_loftr_sidecar
    geometry_dropped = 0
    geometry_reason = "disabled"
    if geometry_cfg is not None and geometry_cfg.enabled and np.any(accepted_sidecar):
        before_geometry = accepted_sidecar.copy()
        accepted_sidecar, geometry_reason = _apply_sidecar_geometry_gate(
            tracks,
            classical_mask=classical_mask,
            sidecar_mask=accepted_sidecar,
            camera=camera,
            config=geometry_cfg,
        )
        geometry_dropped = int(np.count_nonzero(before_geometry & ~accepted_sidecar))
    pre_benefit_accepted_sidecar = accepted_sidecar.copy()
    benefit_dropped = 0
    benefit_reason = "disabled"
    learned_grid_gain = float("nan")
    learned_new_cells = 0
    learned_new_cell_ratio = float("nan")
    learned_weak_cells = 0
    classical_motion_px = _median_track_motion_px(tracks, classical_mask)
    if bool(benefit_gate) and bool(benefit_loftr_only) and np.any(accepted_sidecar):
        loftr_mask = np.asarray([_is_loftr_source(source) for source in tracks.sources], dtype=bool)
        non_loftr_learned_mask = np.asarray(
            [_is_non_loftr_learned_source(source) for source in tracks.sources],
            dtype=bool,
        )
        non_loftr_accepted = _select_mature_cell_sidecars(
            tracks,
            image_shape=image_shape,
            sidecar_mask=accepted_sidecar & non_loftr_learned_mask,
            classical_mask=classical_mask,
            classical_grid=classical_grid,
            classical_motion_px=classical_motion_px,
            classical_median_age=classical_median_age,
            enabled=bool(mature_cell_rescue),
            max_count=int(mature_cell_max_count),
            min_candidates=int(mature_cell_min_candidates),
            min_classical_age=float(mature_cell_min_classical_age),
            min_classical_motion_px=float(mature_cell_min_classical_motion_px),
            max_classical_grid=float(mature_cell_max_classical_grid),
            max_per_cell=int(mature_cell_max_per_cell),
            max_occupancy=int(mature_cell_max_occupancy),
        )
        before_benefit = accepted_sidecar.copy()
        loftr_accept, benefit_reason, learned_grid_gain, learned_new_cells, learned_new_cell_ratio, learned_weak_cells = (
            _apply_sidecar_coverage_benefit_gate(
                tracks,
                image_shape=image_shape,
                classical_mask=classical_mask | non_loftr_accepted,
                sidecar_mask=accepted_sidecar & loftr_mask,
                min_grid_gain=float(min_grid_gain),
                min_new_cells=int(min_new_cells),
                min_new_cell_ratio=float(min_new_cell_ratio),
                max_per_new_cell=int(max_per_new_cell),
                coverage_gain_max_classical_tracks=int(coverage_gain_max_classical_tracks),
                min_classical_motion_px=float(min_classical_motion_px),
                min_classical_age=float(min_classical_age),
                classical_motion_px=classical_motion_px,
                classical_median_age=classical_median_age,
                weak_cell_rescue=bool(weak_cell_rescue),
                non_loftr_weak_cell_rescue=bool(non_loftr_weak_cell_rescue),
                weak_cell_max_count=int(weak_cell_max_count),
                weak_cell_min_candidates=int(weak_cell_min_candidates),
                weak_cell_max_occupancy=int(weak_cell_max_occupancy),
                weak_cell_min_classical_motion_px=float(weak_cell_min_classical_motion_px),
                weak_cell_max_classical_grid=float(weak_cell_max_classical_grid),
                weak_cell_max_classical_tracks=int(weak_cell_max_classical_tracks),
                loftr_planar_rescue=bool(loftr_planar_rescue),
                loftr_planar_max_count=int(loftr_planar_max_count),
                loftr_planar_min_candidates=int(loftr_planar_min_candidates),
                loftr_planar_max_classical_grid=float(loftr_planar_max_classical_grid),
                loftr_planar_min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
                loftr_weak_cell_rescue=bool(loftr_weak_cell_rescue),
                loftr_weak_cell_max_count=int(loftr_weak_cell_max_count),
                loftr_weak_cell_max_occupancy=int(loftr_weak_cell_max_occupancy),
                loftr_rescue_max_classical_tracks=int(loftr_rescue_max_classical_tracks),
                loftr_support_max_init_parallax_px=float(loftr_support_max_init_parallax_px),
                loftr_support_max_classical_motion_px=float(
                    loftr_support_max_classical_motion_px
                ),
                init_parallax_mean_step_px=float(init_parallax_mean_step_px),
            )
        )
        accepted_sidecar = non_loftr_accepted | loftr_accept
        benefit_dropped = int(np.count_nonzero(before_benefit & ~accepted_sidecar))
        if np.any(non_loftr_accepted):
            benefit_reason = "accepted_mature_non_loftr+" + str(benefit_reason)
    elif bool(benefit_gate) and np.any(accepted_sidecar):
        before_benefit = accepted_sidecar.copy()
        (
            accepted_sidecar,
            benefit_reason,
            learned_grid_gain,
            learned_new_cells,
            learned_new_cell_ratio,
            learned_weak_cells,
        ) = _apply_sidecar_coverage_benefit_gate(
            tracks,
            image_shape=image_shape,
            classical_mask=classical_mask,
            sidecar_mask=accepted_sidecar,
            min_grid_gain=float(min_grid_gain),
            min_new_cells=int(min_new_cells),
            min_new_cell_ratio=float(min_new_cell_ratio),
            max_per_new_cell=int(max_per_new_cell),
            coverage_gain_max_classical_tracks=int(coverage_gain_max_classical_tracks),
            min_classical_motion_px=float(min_classical_motion_px),
            min_classical_age=float(min_classical_age),
            classical_motion_px=classical_motion_px,
            classical_median_age=classical_median_age,
            weak_cell_rescue=bool(weak_cell_rescue),
            non_loftr_weak_cell_rescue=bool(non_loftr_weak_cell_rescue),
            weak_cell_max_count=int(weak_cell_max_count),
            weak_cell_min_candidates=int(weak_cell_min_candidates),
            weak_cell_max_occupancy=int(weak_cell_max_occupancy),
            weak_cell_min_classical_motion_px=float(weak_cell_min_classical_motion_px),
            weak_cell_max_classical_grid=float(weak_cell_max_classical_grid),
            weak_cell_max_classical_tracks=int(weak_cell_max_classical_tracks),
            loftr_planar_rescue=bool(loftr_planar_rescue),
            loftr_planar_max_count=int(loftr_planar_max_count),
            loftr_planar_min_candidates=int(loftr_planar_min_candidates),
            loftr_planar_max_classical_grid=float(loftr_planar_max_classical_grid),
            loftr_planar_min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
            loftr_weak_cell_rescue=bool(loftr_weak_cell_rescue),
            loftr_weak_cell_max_count=int(loftr_weak_cell_max_count),
            loftr_weak_cell_max_occupancy=int(loftr_weak_cell_max_occupancy),
            loftr_rescue_max_classical_tracks=int(loftr_rescue_max_classical_tracks),
            loftr_support_max_init_parallax_px=float(loftr_support_max_init_parallax_px),
            loftr_support_max_classical_motion_px=float(
                loftr_support_max_classical_motion_px
            ),
            init_parallax_mean_step_px=float(init_parallax_mean_step_px),
        )
        benefit_dropped = int(np.count_nonzero(before_benefit & ~accepted_sidecar))
    if bool(benefit_gate) and loftr_continuation_state is not None:
        accepted_sidecar, benefit_reason, continuation_restored = (
            _apply_loftr_seeded_continuation(
                tracks,
                pre_benefit_mask=pre_benefit_accepted_sidecar,
                accepted_mask=accepted_sidecar,
                benefit_reason=benefit_reason,
                state=loftr_continuation_state,
                frame_index=int(frame_index),
                max_gap=int(loftr_continuation_max_gap),
            )
        )
        benefit_dropped = max(0, int(benefit_dropped) - int(continuation_restored))
    keep_mask = classical_mask | accepted_sidecar
    dropped = int(np.count_nonzero(sidecar_mask & ~accepted_sidecar))
    reason = "+".join(dict.fromkeys(degraded_reasons))
    return _subset_tracks_by_indices(tracks, indices[keep_mask]), _LearnedExportGateInfo(
        active=True,
        degraded=True,
        reason=reason,
        classical_count=classical_count,
        classical_grid_coverage=classical_grid,
        dropped_learned=dropped,
        geometry_dropped=geometry_dropped,
        geometry_reason=geometry_reason,
        benefit_dropped=benefit_dropped,
        benefit_reason=benefit_reason,
        learned_grid_gain=learned_grid_gain,
        learned_new_cells=learned_new_cells,
        learned_new_cell_ratio=learned_new_cell_ratio,
        learned_weak_cells=learned_weak_cells,
        classical_motion_px=classical_motion_px,
        classical_median_age=classical_median_age,
    )


def _apply_sidecar_geometry_gate(
    tracks: TrackSet,
    classical_mask: np.ndarray,
    sidecar_mask: np.ndarray,
    camera: dict | None,
    config: _SidecarGeometryConfig,
) -> tuple[np.ndarray, str]:
    accepted = np.zeros((len(tracks),), dtype=bool)
    sidecar_indices = np.flatnonzero(sidecar_mask).astype(np.int64)
    if len(sidecar_indices) == 0:
        return accepted, "no_sidecar"

    finite = (
        np.isfinite(tracks.prev_points).all(axis=1)
        & np.isfinite(tracks.points).all(axis=1)
    )
    reference_mask = classical_mask & finite
    fit_mask = reference_mask
    if int(np.count_nonzero(fit_mask)) < max(8, int(config.min_reference_tracks)):
        fit_mask = (reference_mask | sidecar_mask) & finite
    models = _fit_export_geometry_models(tracks, fit_mask, camera, config)
    if not _has_any_export_geometry_model(models):
        return accepted, "no_feh_model"

    valid, scores = _sidecar_geometry_valid(tracks, sidecar_indices, models, camera, config)
    if not np.any(valid):
        return accepted, "all_sidecars_fail_feh"

    order = sidecar_indices[valid][np.argsort(scores[valid])]
    kept: list[int] = []
    for idx in order:
        trial_mask = classical_mask.copy()
        if kept:
            trial_mask[np.asarray(kept, dtype=np.int64)] = True
        trial_mask[int(idx)] = True
        if _residual_stability_ok(tracks, classical_mask, trial_mask, models, camera, config):
            kept.append(int(idx))
    if not kept:
        return accepted, "residual_stability_rejected"
    accepted[np.asarray(kept, dtype=np.int64)] = True
    return accepted, "accepted_feh_residual_stable"


def _apply_sidecar_coverage_benefit_gate(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    classical_mask: np.ndarray,
    sidecar_mask: np.ndarray,
    min_grid_gain: float,
    min_new_cells: int,
    min_new_cell_ratio: float,
    max_per_new_cell: int,
    coverage_gain_max_classical_tracks: int,
    min_classical_motion_px: float,
    min_classical_age: float,
    classical_motion_px: float,
    classical_median_age: float,
    weak_cell_rescue: bool,
    non_loftr_weak_cell_rescue: bool,
    weak_cell_max_count: int,
    weak_cell_min_candidates: int,
    weak_cell_max_occupancy: int,
    weak_cell_min_classical_motion_px: float,
    weak_cell_max_classical_grid: float,
    weak_cell_max_classical_tracks: int,
    loftr_planar_rescue: bool,
    loftr_planar_max_count: int,
    loftr_planar_min_candidates: int,
    loftr_planar_max_classical_grid: float,
    loftr_planar_min_classical_motion_px: float,
    loftr_weak_cell_rescue: bool,
    loftr_weak_cell_max_count: int,
    loftr_weak_cell_max_occupancy: int,
    loftr_rescue_max_classical_tracks: int,
    loftr_support_max_init_parallax_px: float,
    loftr_support_max_classical_motion_px: float,
    init_parallax_mean_step_px: float,
) -> tuple[np.ndarray, str, float, int, float, int]:
    accepted = np.zeros((len(tracks),), dtype=bool)
    sidecar_indices = np.flatnonzero(sidecar_mask).astype(np.int64)
    if len(sidecar_indices) == 0:
        return accepted, "no_sidecar", 0.0, 0, float("nan"), 0
    low_classical_motion = (
        float(min_classical_motion_px) > 0.0
        and math.isfinite(float(classical_motion_px))
        and float(classical_motion_px) < float(min_classical_motion_px)
    )
    if (
        float(min_classical_age) > 0.0
        and (
            not math.isfinite(float(classical_median_age))
            or float(classical_median_age) < float(min_classical_age)
        )
    ):
        return accepted, "immature_classical_tracks", 0.0, 0, 0.0, 0

    rows, cols = 4, 6
    sidecar_all_loftr = all(_is_loftr_source(tracks.sources[int(idx)]) for idx in sidecar_indices)
    coverage_classical_mask = np.asarray(classical_mask, dtype=bool)
    if sidecar_all_loftr and int(loftr_rescue_max_classical_tracks) > 0:
        coverage_classical_mask = coverage_classical_mask & (tracks.ages.astype(np.int32) >= 3)
    classical_counts = _grid_counts_for_mask(
        tracks,
        image_shape,
        coverage_classical_mask,
        rows=rows,
        cols=cols,
    )
    classical_count = int(np.sum(classical_counts))
    classical_mature_count = int(
        np.count_nonzero(
            np.asarray(classical_mask, dtype=bool)
            & (tracks.ages.astype(np.int32) >= 3)
        )
    )
    loftr_classical_support_count = (
        classical_mature_count
        if int(loftr_rescue_max_classical_tracks) > 0
        else classical_count
    )
    classical_occupied = classical_counts > 0
    classical_coverage = float(np.count_nonzero(classical_occupied) / float(rows * cols))
    loftr_high_support = int(loftr_rescue_max_classical_tracks) > 0 and loftr_classical_support_count > int(
        loftr_rescue_max_classical_tracks
    )
    if loftr_high_support:
        non_loftr_indices = np.asarray(
            [
                int(idx)
                for idx in sidecar_indices
                if not _is_loftr_source(tracks.sources[int(idx)])
            ],
            dtype=np.int64,
        )
        if len(non_loftr_indices) == 0:
            # Do not let the mature-KLT count become an unconditional LoFTR
            # veto. In low-texture planar windows A06-style LoFTR sidecars can
            # still be useful as a tiny support set, but only if the stricter
            # weak-cell / new-cell, motion, init-parallax, and downstream
            # temporal gates accept them. The helper calls below receive a
            # relaxed support-count cap only for this all-LoFTR case.
            pass
        else:
            sidecar_indices = non_loftr_indices
    loftr_helper_max_classical_tracks = (
        0 if (loftr_high_support and sidecar_all_loftr) else int(loftr_rescue_max_classical_tracks)
    )
    sidecar_cells = _grid_cell_indices(tracks.points[sidecar_indices], image_shape, rows=rows, cols=cols)
    new_cell_flags = np.asarray(
        [not bool(classical_occupied[int(row), int(col)]) for row, col in sidecar_cells],
        dtype=bool,
    )
    if low_classical_motion:
        # Slow near-wall underwater motion is exactly where KLT can become
        # under-constrained but LoFTR can still provide a few planar support
        # observations. Keep the global motion guard for ordinary learned
        # sidecars, but let the explicitly enabled LoFTR rescue paths decide
        # under their own stricter source/geometry/coverage gates.
        planar_sidecar_indices = sidecar_indices[new_cell_flags]
        loftr_accept = _select_loftr_planar_sidecars(
            tracks,
            sidecar_indices=planar_sidecar_indices,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_planar_rescue),
            max_count=int(loftr_planar_max_count),
            min_candidates=int(loftr_planar_min_candidates),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_accept):
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            new_cell_ratio = float(np.count_nonzero(new_cell_flags) / max(1, len(sidecar_indices)))
            return loftr_accept, "accepted_loftr_planar_rescue_low_motion", 0.0, 0, new_cell_ratio, selected_cells
        loftr_weak_accept = _select_loftr_weak_cell_sidecars(
            tracks,
            image_shape=image_shape,
            sidecar_indices=sidecar_indices,
            sidecar_cells=sidecar_cells,
            classical_counts=classical_counts,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_weak_cell_rescue),
            max_count=int(loftr_weak_cell_max_count),
            max_occupancy=int(loftr_weak_cell_max_occupancy),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_weak_accept):
            if not _loftr_support_motion_ok(
                loftr_support_max_classical_motion_px,
                classical_motion_px,
            ):
                return (
                    accepted,
                    _loftr_support_motion_reason(classical_motion_px),
                    0.0,
                    0,
                    new_cell_ratio,
                    0,
                )
            if not _loftr_support_init_parallax_ok(
                loftr_support_max_init_parallax_px,
                init_parallax_mean_step_px,
            ):
                return (
                    accepted,
                    _loftr_support_init_parallax_reason(init_parallax_mean_step_px),
                    0.0,
                    0,
                    new_cell_ratio,
                    0,
                )
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_weak_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            new_cell_ratio = float(np.count_nonzero(new_cell_flags) / max(1, len(sidecar_indices)))
            return loftr_weak_accept, "accepted_loftr_support_rescue_low_motion", 0.0, 0, new_cell_ratio, selected_cells
        return accepted, "low_classical_motion", 0.0, 0, 0.0, 0
    new_cell_ratio = float(np.count_nonzero(new_cell_flags) / max(1, len(sidecar_indices)))
    loftr_support_accept = _select_loftr_weak_cell_sidecars(
        tracks,
        image_shape=image_shape,
        sidecar_indices=sidecar_indices,
        sidecar_cells=sidecar_cells,
        classical_counts=classical_counts,
        classical_coverage=classical_coverage,
        classical_motion_px=classical_motion_px,
        classical_count=loftr_classical_support_count,
        enabled=bool(loftr_weak_cell_rescue),
        max_count=int(loftr_weak_cell_max_count),
        max_occupancy=int(loftr_weak_cell_max_occupancy),
        max_classical_grid=float(loftr_planar_max_classical_grid),
        max_classical_tracks=int(loftr_helper_max_classical_tracks),
        min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
    )
    if np.any(loftr_support_accept):
        if not _loftr_support_motion_ok(
            loftr_support_max_classical_motion_px,
            classical_motion_px,
        ):
            return (
                accepted,
                _loftr_support_motion_reason(classical_motion_px),
                0.0,
                0,
                new_cell_ratio,
                0,
            )
        if not _loftr_support_init_parallax_ok(
            loftr_support_max_init_parallax_px,
            init_parallax_mean_step_px,
        ):
            return (
                accepted,
                _loftr_support_init_parallax_reason(init_parallax_mean_step_px),
                0.0,
                0,
                new_cell_ratio,
                0,
            )
        selected_cells = _count_selected_cells(
            tracks.points[np.flatnonzero(loftr_support_accept)],
            image_shape,
            rows=rows,
            cols=cols,
        )
        return loftr_support_accept, "accepted_loftr_support_rescue", 0.0, 0, new_cell_ratio, selected_cells
    if new_cell_ratio < float(min_new_cell_ratio):
        # Planar rescue is still a sidecar, not a generic LoFTR replacement:
        # only candidates that open a previously empty grid cell are allowed to
        # bypass the global new-cell-ratio check.
        planar_sidecar_indices = sidecar_indices[new_cell_flags]
        loftr_accept = _select_loftr_planar_sidecars(
            tracks,
            sidecar_indices=planar_sidecar_indices,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_planar_rescue),
            max_count=int(loftr_planar_max_count),
            min_candidates=int(loftr_planar_min_candidates),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_accept):
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_accept, "accepted_loftr_planar_rescue", 0.0, 0, new_cell_ratio, selected_cells
        loftr_weak_accept = _select_loftr_weak_cell_sidecars(
            tracks,
            image_shape=image_shape,
            sidecar_indices=sidecar_indices,
            sidecar_cells=sidecar_cells,
            classical_counts=classical_counts,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_weak_cell_rescue),
            max_count=int(loftr_weak_cell_max_count),
            max_occupancy=int(loftr_weak_cell_max_occupancy),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_weak_accept):
            if not _loftr_support_motion_ok(
                loftr_support_max_classical_motion_px,
                classical_motion_px,
            ):
                return (
                    accepted,
                    _loftr_support_motion_reason(classical_motion_px),
                    0.0,
                    0,
                    new_cell_ratio,
                    0,
                )
            if not _loftr_support_init_parallax_ok(
                loftr_support_max_init_parallax_px,
                init_parallax_mean_step_px,
            ):
                return (
                    accepted,
                    _loftr_support_init_parallax_reason(init_parallax_mean_step_px),
                    0.0,
                    0,
                    new_cell_ratio,
                    0,
                )
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_weak_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_weak_accept, "accepted_loftr_support_rescue", 0.0, 0, new_cell_ratio, selected_cells
        if bool(weak_cell_rescue) and bool(non_loftr_weak_cell_rescue):
            weak_accept = _select_weak_cell_sidecars(
                tracks,
                image_shape=image_shape,
                sidecar_indices=sidecar_indices,
                sidecar_cells=sidecar_cells,
                classical_counts=classical_counts,
                classical_coverage=classical_coverage,
                classical_motion_px=classical_motion_px,
                enabled=True,
                max_count=int(weak_cell_max_count),
                min_candidates=int(weak_cell_min_candidates),
                max_occupancy=int(weak_cell_max_occupancy),
                min_classical_motion_px=float(weak_cell_min_classical_motion_px),
                max_classical_grid=float(weak_cell_max_classical_grid),
                max_classical_tracks=int(weak_cell_max_classical_tracks),
            )
            if np.any(weak_accept):
                selected_cells = _count_selected_cells(
                    tracks.points[np.flatnonzero(weak_accept)],
                    image_shape,
                    rows=rows,
                    cols=cols,
                )
                return weak_accept, "accepted_weak_cell_rescue", 0.0, 0, new_cell_ratio, selected_cells
        if bool(weak_cell_rescue):
            return accepted, "ordinary_weak_cell_requires_new_cells", 0.0, 0, new_cell_ratio, 0
        return accepted, "too_few_new_cell_candidates", 0.0, 0, new_cell_ratio, 0

    new_cell_indices = sidecar_indices[new_cell_flags]
    if len(new_cell_indices) == 0:
        return accepted, "no_new_cells", 0.0, 0, new_cell_ratio, 0

    per_cell_used: dict[tuple[int, int], int] = {}
    selected: list[int] = []
    order = _source_selection_order(tracks, new_cell_indices, prefer_age=False)
    max_per_cell = max(1, int(max_per_new_cell))
    for idx in order:
        row, col = _grid_cell_indices(tracks.points[np.asarray([idx], dtype=np.int64)], image_shape, rows=rows, cols=cols)[0]
        key = (int(row), int(col))
        used = per_cell_used.get(key, 0)
        if used >= max_per_cell:
            continue
        per_cell_used[key] = used + 1
        selected.append(int(idx))

    if int(coverage_gain_max_classical_tracks) > 0 and int(np.sum(classical_counts)) > int(
        coverage_gain_max_classical_tracks
    ):
        # In high-support frames, sparse XFeat/SP-LG points that open only a
        # peripheral grid cell have repeatedly behaved like perturbations rather
        # than rescue observations. Keep confirmed LoFTR candidates because
        # they are governed by the planar/textureless rescue policy; reject
        # ordinary learned coverage-gain points until the KLT backbone is truly
        # sparse.
        selected = [
            int(idx)
            for idx in selected
            if _is_loftr_source(tracks.sources[int(idx)])
        ]
        if not selected:
            return (
                accepted,
                "high_classical_tracks_for_coverage_gain",
                0.0,
                0,
                new_cell_ratio,
                0,
            )
        per_cell_used = {}
        for idx in selected:
            row, col = _grid_cell_indices(
                tracks.points[np.asarray([idx], dtype=np.int64)],
                image_shape,
                rows=rows,
                cols=cols,
            )[0]
            per_cell_used[(int(row), int(col))] = per_cell_used.get((int(row), int(col)), 0) + 1

    learned_new_cells = len(per_cell_used)
    if learned_new_cells < max(0, int(min_new_cells)):
        loftr_accept = _select_loftr_planar_sidecars(
            tracks,
            sidecar_indices=new_cell_indices,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_planar_rescue),
            max_count=int(loftr_planar_max_count),
            min_candidates=int(loftr_planar_min_candidates),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_accept):
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_accept, "accepted_loftr_planar_rescue", 0.0, learned_new_cells, new_cell_ratio, selected_cells
        loftr_weak_accept = _select_loftr_weak_cell_sidecars(
            tracks,
            image_shape=image_shape,
            sidecar_indices=sidecar_indices,
            sidecar_cells=sidecar_cells,
            classical_counts=classical_counts,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_weak_cell_rescue),
            max_count=int(loftr_weak_cell_max_count),
            max_occupancy=int(loftr_weak_cell_max_occupancy),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_weak_accept):
            if not _loftr_support_motion_ok(
                loftr_support_max_classical_motion_px,
                classical_motion_px,
            ):
                return (
                    accepted,
                    _loftr_support_motion_reason(classical_motion_px),
                    0.0,
                    learned_new_cells,
                    new_cell_ratio,
                    0,
                )
            if not _loftr_support_init_parallax_ok(
                loftr_support_max_init_parallax_px,
                init_parallax_mean_step_px,
            ):
                return (
                    accepted,
                    _loftr_support_init_parallax_reason(init_parallax_mean_step_px),
                    0.0,
                    learned_new_cells,
                    new_cell_ratio,
                    0,
                )
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_weak_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_weak_accept, "accepted_loftr_support_rescue", 0.0, learned_new_cells, new_cell_ratio, selected_cells
        return accepted, "insufficient_new_cells", 0.0, learned_new_cells, new_cell_ratio, 0

    if selected:
        accepted[np.asarray(selected, dtype=np.int64)] = True
    combined_counts = _grid_counts_for_mask(tracks, image_shape, classical_mask | accepted, rows=rows, cols=cols)
    combined_coverage = float(np.count_nonzero(combined_counts > 0) / float(rows * cols))
    grid_gain = max(0.0, combined_coverage - classical_coverage)
    if grid_gain + 1e-9 < float(min_grid_gain):
        loftr_accept = _select_loftr_planar_sidecars(
            tracks,
            sidecar_indices=new_cell_indices,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_planar_rescue),
            max_count=int(loftr_planar_max_count),
            min_candidates=int(loftr_planar_min_candidates),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_accept):
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_accept, "accepted_loftr_planar_rescue", grid_gain, learned_new_cells, new_cell_ratio, selected_cells
        loftr_weak_accept = _select_loftr_weak_cell_sidecars(
            tracks,
            image_shape=image_shape,
            sidecar_indices=sidecar_indices,
            sidecar_cells=sidecar_cells,
            classical_counts=classical_counts,
            classical_coverage=classical_coverage,
            classical_motion_px=classical_motion_px,
            classical_count=loftr_classical_support_count,
            enabled=bool(loftr_weak_cell_rescue),
            max_count=int(loftr_weak_cell_max_count),
            max_occupancy=int(loftr_weak_cell_max_occupancy),
            max_classical_grid=float(loftr_planar_max_classical_grid),
            max_classical_tracks=int(loftr_helper_max_classical_tracks),
            min_classical_motion_px=float(loftr_planar_min_classical_motion_px),
        )
        if np.any(loftr_weak_accept):
            if not _loftr_support_motion_ok(
                loftr_support_max_classical_motion_px,
                classical_motion_px,
            ):
                return (
                    accepted,
                    _loftr_support_motion_reason(classical_motion_px),
                    grid_gain,
                    learned_new_cells,
                    new_cell_ratio,
                    0,
                )
            if not _loftr_support_init_parallax_ok(
                loftr_support_max_init_parallax_px,
                init_parallax_mean_step_px,
            ):
                return (
                    accepted,
                    _loftr_support_init_parallax_reason(init_parallax_mean_step_px),
                    grid_gain,
                    learned_new_cells,
                    new_cell_ratio,
                    0,
                )
            selected_cells = _count_selected_cells(
                tracks.points[np.flatnonzero(loftr_weak_accept)],
                image_shape,
                rows=rows,
                cols=cols,
            )
            return loftr_weak_accept, "accepted_loftr_support_rescue", grid_gain, learned_new_cells, new_cell_ratio, selected_cells
        return np.zeros((len(tracks),), dtype=bool), "insufficient_grid_gain", grid_gain, learned_new_cells, new_cell_ratio, 0

    if (
        bool(sidecar_all_loftr)
        and bool(loftr_weak_cell_rescue)
        and int(loftr_weak_cell_max_count) > 0
        and int(np.count_nonzero(accepted)) > 0
        and int(np.count_nonzero(accepted)) < int(loftr_weak_cell_max_count)
        and math.isfinite(float(classical_median_age))
        and float(classical_median_age) >= 8.0
        and classical_coverage <= float(loftr_planar_max_classical_grid) + 1e-9
        and _loftr_support_motion_ok(
            loftr_support_max_classical_motion_px,
            classical_motion_px,
        )
        and _loftr_support_init_parallax_ok(
            loftr_support_max_init_parallax_px,
            init_parallax_mean_step_px,
        )
    ):
        remaining = int(loftr_weak_cell_max_count) - int(np.count_nonzero(accepted))
        occupancy_ok: list[int] = []
        for local_idx, (row, col) in enumerate(sidecar_cells):
            idx = int(sidecar_indices[int(local_idx)])
            if bool(accepted[idx]):
                continue
            occupancy = int(classical_counts[int(row), int(col)])
            if 0 <= occupancy <= max(1, int(loftr_weak_cell_max_occupancy)):
                occupancy_ok.append(idx)
        if occupancy_ok and remaining > 0:
            order = _source_selection_order(
                tracks,
                np.asarray(occupancy_ok, dtype=np.int64),
                prefer_age=True,
            )
            chosen = order[:remaining]
            if len(chosen):
                accepted[chosen.astype(np.int64)] = True
                selected_cells = _count_selected_cells(
                    tracks.points[chosen.astype(np.int64)],
                    image_shape,
                    rows=rows,
                    cols=cols,
                )
                return (
                    accepted,
                    "accepted_coverage_gain+loftr_support_topup",
                    grid_gain,
                    learned_new_cells,
                    new_cell_ratio,
                    selected_cells,
                )

    return accepted, "accepted_coverage_gain", grid_gain, learned_new_cells, new_cell_ratio, 0


def _loftr_support_init_parallax_ok(max_init_parallax_px: float, mean_step_px: float) -> bool:
    max_px = float(max_init_parallax_px)
    if max_px <= 0.0:
        return True
    mean_px = float(mean_step_px)
    if not math.isfinite(mean_px):
        return True
    return mean_px <= max_px + 1e-9


def _loftr_support_motion_ok(max_motion_px: float, motion_px: float) -> bool:
    max_px = float(max_motion_px)
    if max_px <= 0.0:
        return True
    motion = float(motion_px)
    if not math.isfinite(motion):
        return False
    return motion <= max_px + 1e-9


def _loftr_support_motion_reason(motion_px: float) -> str:
    if math.isfinite(float(motion_px)):
        return f"loftr_support_high_classical_motion:{float(motion_px):.3f}"
    return "loftr_support_unknown_classical_motion"


def _loftr_support_init_parallax_reason(mean_step_px: float) -> str:
    if math.isfinite(float(mean_step_px)):
        return f"loftr_support_high_init_parallax:{float(mean_step_px):.3f}"
    return "loftr_support_unknown_init_parallax"


def _select_loftr_planar_sidecars(
    tracks: TrackSet,
    sidecar_indices: np.ndarray,
    classical_coverage: float,
    classical_motion_px: float,
    classical_count: int,
    enabled: bool,
    max_count: int,
    min_candidates: int,
    max_classical_grid: float,
    max_classical_tracks: int,
    min_classical_motion_px: float,
) -> np.ndarray:
    accepted = np.zeros((len(tracks),), dtype=bool)
    if not enabled or len(sidecar_indices) == 0 or max_count <= 0:
        return accepted
    if classical_coverage > float(max_classical_grid) + 1e-9:
        return accepted
    if int(max_classical_tracks) > 0 and int(classical_count) > int(max_classical_tracks):
        return accepted
    if (
        float(min_classical_motion_px) > 0.0
        and math.isfinite(float(classical_motion_px))
        and float(classical_motion_px) < float(min_classical_motion_px)
    ):
        return accepted
    loftr_indices = np.asarray(
        [idx for idx in sidecar_indices if _is_loftr_source(tracks.sources[int(idx)])],
        dtype=np.int64,
    )
    if len(loftr_indices) < max(1, int(min_candidates)):
        return accepted
    order = _source_selection_order(tracks, loftr_indices, prefer_age=True)
    selected = order[: max(1, int(max_count))]
    if len(selected):
        accepted[selected.astype(np.int64)] = True
    return accepted


def _select_loftr_weak_cell_sidecars(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    sidecar_indices: np.ndarray,
    sidecar_cells: np.ndarray,
    classical_counts: np.ndarray,
    classical_coverage: float,
    classical_motion_px: float,
    classical_count: int,
    enabled: bool,
    max_count: int,
    max_occupancy: int,
    max_classical_grid: float,
    max_classical_tracks: int,
    min_classical_motion_px: float,
) -> np.ndarray:
    accepted = np.zeros((len(tracks),), dtype=bool)
    if not enabled or len(sidecar_indices) == 0 or max_count <= 0:
        return accepted
    if classical_coverage > float(max_classical_grid) + 1e-9:
        return accepted
    if int(max_classical_tracks) > 0 and int(classical_count) > int(max_classical_tracks):
        return accepted
    if (
        float(min_classical_motion_px) > 0.0
        and math.isfinite(float(classical_motion_px))
        and float(classical_motion_px) < float(min_classical_motion_px)
    ):
        return accepted
    weak_local: list[int] = []
    for local_idx, (row, col) in enumerate(sidecar_cells):
        idx = int(sidecar_indices[int(local_idx)])
        if not _is_loftr_source(tracks.sources[idx]):
            continue
        occupancy = int(classical_counts[int(row), int(col)])
        if 0 <= occupancy <= max(1, int(max_occupancy)):
            weak_local.append(int(local_idx))
    if not weak_local:
        return accepted
    weak_indices = sidecar_indices[np.asarray(weak_local, dtype=np.int64)]
    order = _source_selection_order(tracks, weak_indices, prefer_age=True)
    selected = order[: max(1, int(max_count))]
    if len(selected):
        accepted[selected.astype(np.int64)] = True
    return accepted


def _select_weak_cell_sidecars(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    sidecar_indices: np.ndarray,
    sidecar_cells: np.ndarray,
    classical_counts: np.ndarray,
    classical_coverage: float,
    classical_motion_px: float,
    enabled: bool,
    max_count: int,
    min_candidates: int,
    max_occupancy: int,
    min_classical_motion_px: float,
    max_classical_grid: float,
    max_classical_tracks: int = 0,
) -> np.ndarray:
    accepted = np.zeros((len(tracks),), dtype=bool)
    if not enabled or len(sidecar_indices) == 0 or max_count <= 0:
        return accepted
    if len(sidecar_indices) < max(1, int(min_candidates)):
        return accepted
    if classical_coverage > float(max_classical_grid) + 1e-9:
        return accepted
    if int(max_classical_tracks) > 0 and int(np.sum(classical_counts)) > int(max_classical_tracks):
        return accepted
    if not math.isfinite(float(classical_motion_px)) or float(classical_motion_px) < float(min_classical_motion_px):
        return accepted
    weak_local: list[int] = []
    for local_idx, (row, col) in enumerate(sidecar_cells):
        occupancy = int(classical_counts[int(row), int(col)])
        if 0 < occupancy <= max(1, int(max_occupancy)):
            weak_local.append(local_idx)
    if not weak_local:
        return accepted
    weak_indices = sidecar_indices[np.asarray(weak_local, dtype=np.int64)]
    order = _source_selection_order(tracks, weak_indices, prefer_age=False)
    per_cell_used: set[tuple[int, int]] = set()
    chosen: list[int] = []
    for idx in order:
        row, col = _grid_cell_indices(
            tracks.points[np.asarray([idx], dtype=np.int64)],
            image_shape,
            rows=int(classical_counts.shape[0]),
            cols=int(classical_counts.shape[1]),
        )[0]
        key = (int(row), int(col))
        if key in per_cell_used:
            continue
        per_cell_used.add(key)
        chosen.append(int(idx))
        if len(chosen) >= int(max_count):
            break
    if chosen:
        accepted[np.asarray(chosen, dtype=np.int64)] = True
    return accepted


def _select_mature_cell_sidecars(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    sidecar_mask: np.ndarray,
    classical_mask: np.ndarray,
    classical_grid: float,
    classical_motion_px: float,
    classical_median_age: float,
    enabled: bool,
    max_count: int,
    min_candidates: int,
    min_classical_age: float,
    min_classical_motion_px: float,
    max_classical_grid: float,
    max_per_cell: int,
    max_occupancy: int,
) -> np.ndarray:
    accepted = np.zeros((len(tracks),), dtype=bool)
    sidecar_indices = np.flatnonzero(sidecar_mask).astype(np.int64)
    if not enabled or len(sidecar_indices) == 0 or max_count <= 0:
        return accepted
    if len(sidecar_indices) < max(1, int(min_candidates)):
        return accepted
    if float(classical_grid) > float(max_classical_grid) + 1e-9:
        return accepted
    if not math.isfinite(float(classical_median_age)) or float(classical_median_age) < float(min_classical_age):
        return accepted
    if (
        float(min_classical_motion_px) > 0.0
        and (
            not math.isfinite(float(classical_motion_px))
            or float(classical_motion_px) < float(min_classical_motion_px)
        )
    ):
        return accepted

    rows, cols = 4, 6
    classical_counts = _grid_counts_for_mask(tracks, image_shape, classical_mask, rows=rows, cols=cols)
    sidecar_cells = _grid_cell_indices(tracks.points[sidecar_indices], image_shape, rows=rows, cols=cols)
    order = _source_selection_order(tracks, sidecar_indices, prefer_age=True)
    per_cell_used: dict[tuple[int, int], int] = {}
    selected: list[int] = []
    max_per = max(1, int(max_per_cell))
    for idx in order:
        cell = _grid_cell_indices(
            tracks.points[np.asarray([idx], dtype=np.int64)],
            image_shape,
            rows=rows,
            cols=cols,
        )[0]
        key = (int(cell[0]), int(cell[1]))
        # Prefer empty or sparse KLT cells; mature rescue is not a generic
        # learned replacement path.
        if int(classical_counts[key[0], key[1]]) > max(1, int(max_occupancy)):
            continue
        used = per_cell_used.get(key, 0)
        if used >= max_per:
            continue
        per_cell_used[key] = used + 1
        selected.append(int(idx))
        if len(selected) >= int(max_count):
            break
    if selected:
        accepted[np.asarray(selected, dtype=np.int64)] = True
    return accepted


def _count_selected_cells(
    points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
) -> int:
    cells = _grid_cell_indices(points, image_shape, rows=rows, cols=cols)
    return len({(int(row), int(col)) for row, col in cells})


def _fit_export_geometry_models(
    tracks: TrackSet,
    mask: np.ndarray,
    camera: dict | None,
    config: _SidecarGeometryConfig,
) -> dict[str, np.ndarray | None]:
    idx = np.flatnonzero(mask).astype(np.int64)
    models: dict[str, np.ndarray | None] = {"F": None, "E": None, "H": None}
    if len(idx) < 8:
        return models
    pts0 = tracks.prev_points[idx].astype(np.float32)
    pts1 = tracks.points[idx].astype(np.float32)
    try:
        f_mat, _ = cv2.findFundamentalMat(
            pts0,
            pts1,
            cv2.FM_RANSAC,
            max(0.25, float(config.max_epipolar_error)),
            0.999,
        )
        if _valid_matrix(f_mat):
            models["F"] = np.asarray(f_mat, dtype=np.float64)[:3, :3]
    except cv2.error:
        models["F"] = None
    try:
        h_mat, _ = cv2.findHomography(
            pts0,
            pts1,
            cv2.RANSAC,
            max(0.5, float(config.max_homography_error)),
        )
        if _valid_matrix(h_mat):
            models["H"] = np.asarray(h_mat, dtype=np.float64)[:3, :3]
    except cv2.error:
        models["H"] = None
    if camera is not None:
        try:
            norm0 = _pixels_to_normalized(pts0, camera).astype(np.float32)
            norm1 = _pixels_to_normalized(pts1, camera).astype(np.float32)
            e_mat, _ = cv2.findEssentialMat(
                norm0,
                norm1,
                focal=1.0,
                pp=(0.0, 0.0),
                method=cv2.RANSAC,
                prob=0.999,
                threshold=max(1e-5, float(config.max_essential_error)),
            )
            if _valid_matrix(e_mat):
                models["E"] = np.asarray(e_mat, dtype=np.float64)[:3, :3]
        except cv2.error:
            models["E"] = None
    return models


def _has_any_export_geometry_model(models: dict[str, np.ndarray | None]) -> bool:
    return any(_valid_matrix(model) for model in models.values())


def _sidecar_geometry_valid(
    tracks: TrackSet,
    sidecar_indices: np.ndarray,
    models: dict[str, np.ndarray | None],
    camera: dict | None,
    config: _SidecarGeometryConfig,
) -> tuple[np.ndarray, np.ndarray]:
    valid = np.zeros((len(sidecar_indices),), dtype=bool)
    scores = np.full((len(sidecar_indices),), np.inf, dtype=np.float32)
    if len(sidecar_indices) == 0:
        return valid, scores
    pts0 = tracks.prev_points[sidecar_indices].astype(np.float32)
    pts1 = tracks.points[sidecar_indices].astype(np.float32)
    residuals: list[np.ndarray] = []
    labels: list[str] = []
    if _valid_matrix(models.get("F")):
        residuals.append(_export_epipolar_errors(models["F"], pts0, pts1) / max(1e-6, float(config.max_epipolar_error)))
        labels.append("F")
    if _valid_matrix(models.get("E")) and camera is not None:
        norm0 = _pixels_to_normalized(pts0, camera)
        norm1 = _pixels_to_normalized(pts1, camera)
        residuals.append(_export_essential_errors(models["E"], norm0, norm1) / max(1e-9, float(config.max_essential_error)))
        labels.append("E")
    if _valid_matrix(models.get("H")):
        residuals.append(_export_homography_errors(models["H"], pts0, pts1) / max(1e-6, float(config.max_homography_error)))
        labels.append("H")
    if not residuals:
        return valid, scores
    residual_stack = np.vstack(residuals).astype(np.float32)
    scores = np.nanmin(residual_stack, axis=0).astype(np.float32)
    generic_valid = np.any(residual_stack <= 1.0, axis=0)
    if config.loftr_requires_homography and "H" in labels:
        h_row = residual_stack[labels.index("H")]
        for local_idx, source in enumerate([tracks.sources[int(idx)] for idx in sidecar_indices]):
            if _is_loftr_source(source):
                generic_valid[local_idx] = bool(h_row[local_idx] <= 1.0)
                scores[local_idx] = float(h_row[local_idx])
    valid = generic_valid & np.isfinite(scores)
    return valid, scores


def _residual_stability_ok(
    tracks: TrackSet,
    reference_mask: np.ndarray,
    trial_mask: np.ndarray,
    models: dict[str, np.ndarray | None],
    camera: dict | None,
    config: _SidecarGeometryConfig,
) -> bool:
    checks = [
        (
            "F",
            lambda pts0, pts1: _export_epipolar_errors(models["F"], pts0, pts1),
            float(config.residual_max_epipolar_abs),
        ),
        (
            "H",
            lambda pts0, pts1: _export_homography_errors(models["H"], pts0, pts1),
            float(config.residual_max_homography_abs),
        ),
    ]
    if _valid_matrix(models.get("E")) and camera is not None:
        checks.append(
            (
                "E",
                lambda pts0, pts1: _export_essential_errors(
                    models["E"],
                    _pixels_to_normalized(pts0, camera),
                    _pixels_to_normalized(pts1, camera),
                ),
                float(config.residual_max_essential_abs),
            )
        )
    for label, residual_fn, abs_limit in checks:
        if not _valid_matrix(models.get(label)):
            continue
        ref_idx = np.flatnonzero(reference_mask).astype(np.int64)
        trial_idx = np.flatnonzero(trial_mask).astype(np.int64)
        if len(ref_idx) < 8 or len(trial_idx) < 8:
            continue
        ref_res = residual_fn(
            tracks.prev_points[ref_idx].astype(np.float32),
            tracks.points[ref_idx].astype(np.float32),
        )
        trial_res = residual_fn(
            tracks.prev_points[trial_idx].astype(np.float32),
            tracks.points[trial_idx].astype(np.float32),
        )
        ref_med = _finite_median(ref_res)
        trial_med = _finite_median(trial_res)
        if not math.isfinite(ref_med) or not math.isfinite(trial_med):
            continue
        limit = ref_med * max(1.0, float(config.residual_max_ratio)) + max(0.0, abs_limit)
        if trial_med > limit:
            return False
    return True


def _export_epipolar_errors(f_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    if len(pts0) == 0 or not _valid_matrix(f_mat):
        return np.empty((0,), dtype=np.float32)
    pts0_h = np.column_stack([pts0, np.ones((len(pts0),), dtype=np.float32)])
    pts1_h = np.column_stack([pts1, np.ones((len(pts1),), dtype=np.float32)])
    lines1 = (f_mat @ pts0_h.T).T
    numer = np.abs(np.sum(pts1_h * lines1, axis=1))
    denom = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2) + 1e-9
    return (numer / denom).astype(np.float32)


def _export_essential_errors(e_mat: np.ndarray, pts0_norm: np.ndarray, pts1_norm: np.ndarray) -> np.ndarray:
    if len(pts0_norm) == 0 or not _valid_matrix(e_mat):
        return np.empty((0,), dtype=np.float32)
    pts0_h = np.column_stack([pts0_norm, np.ones((len(pts0_norm),), dtype=np.float32)])
    pts1_h = np.column_stack([pts1_norm, np.ones((len(pts1_norm),), dtype=np.float32)])
    lines1 = (e_mat @ pts0_h.T).T
    numer = np.abs(np.sum(pts1_h * lines1, axis=1))
    denom = np.sqrt(lines1[:, 0] ** 2 + lines1[:, 1] ** 2) + 1e-12
    return (numer / denom).astype(np.float32)


def _export_homography_errors(h_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> np.ndarray:
    if len(pts0) == 0 or not _valid_matrix(h_mat):
        return np.empty((0,), dtype=np.float32)
    pts0_h = np.column_stack([pts0, np.ones((len(pts0),), dtype=np.float32)])
    proj = (h_mat @ pts0_h.T).T
    denom = proj[:, 2:3]
    valid = np.abs(denom[:, 0]) > 1e-9
    out = np.full((len(pts0),), np.inf, dtype=np.float32)
    if np.any(valid):
        proj_xy = proj[valid, :2] / denom[valid]
        out[valid] = np.linalg.norm(proj_xy - pts1[valid], axis=1).astype(np.float32)
    return out


def _valid_matrix(mat: np.ndarray | None) -> bool:
    if mat is None:
        return False
    arr = np.asarray(mat)
    return arr.ndim == 2 and arr.shape[0] >= 3 and arr.shape[1] >= 3 and np.isfinite(arr[:3, :3]).all()


def _finite_median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if len(finite) == 0:
        return float("nan")
    return float(np.median(finite))


def _classical_backbone_mask(tracks: TrackSet) -> np.ndarray:
    if len(tracks) == 0:
        return np.empty((0,), dtype=bool)
    return np.asarray(
        [
            (not _is_learned_source(source)) and (not _is_recovered_source(source))
            for source in tracks.sources
        ],
        dtype=bool,
    )


def _track_grid_coverage(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    mask: np.ndarray | None = None,
) -> float:
    if len(tracks) == 0:
        return 0.0
    points = tracks.points if mask is None else tracks.points[np.asarray(mask, dtype=bool)]
    if len(points) == 0:
        return 0.0
    return float(grid_stats(points, image_shape, rows=4, cols=6).coverage)


def _window_screening_metrics(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    quality,
    previous_track_ids: set[int],
    *,
    rows: int = 4,
    cols: int = 6,
) -> tuple[dict[str, float], set[int]]:
    """Return the four outcome-blind P06 metrics on the tracker output."""

    current_track_ids = {int(track_id) for track_id in tracks.ids}
    tracked_before = len(previous_track_ids)
    dropped = len(previous_track_ids - current_track_ids)
    dropout_ratio = float(dropped / tracked_before) if tracked_before > 0 else 0.0
    coverage = grid_stats(
        tracks.points,
        image_shape,
        rows=max(1, int(rows)),
        cols=max(1, int(cols)),
    ).coverage
    return (
        {
            "grid_coverage": float(coverage),
            "dropout_ratio": dropout_ratio,
            "flat_region_ratio": float(quality.flat_region_ratio),
            "degradation_score": float(quality.degradation_score),
        },
        current_track_ids,
    )


def _grid_counts_for_mask(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    mask: np.ndarray,
    rows: int = 4,
    cols: int = 6,
) -> np.ndarray:
    if len(tracks) == 0:
        return np.zeros((rows, cols), dtype=np.int32)
    points = tracks.points[np.asarray(mask, dtype=bool)]
    return grid_stats(points, image_shape, rows=rows, cols=cols).counts


def _grid_cell_indices(
    points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int = 4,
    cols: int = 6,
) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0, 2), dtype=np.int32)
    h, w = image_shape[:2]
    pts = points.reshape(-1, 2)
    xs = np.clip((pts[:, 0] / max(1, w) * cols).astype(np.int32), 0, cols - 1)
    ys = np.clip((pts[:, 1] / max(1, h) * rows).astype(np.int32), 0, rows - 1)
    return np.column_stack([ys, xs]).astype(np.int32)


def _median_track_motion_px(tracks: TrackSet, mask: np.ndarray) -> float:
    if len(tracks) == 0:
        return float("nan")
    selected = np.asarray(mask, dtype=bool)
    if not np.any(selected):
        return float("nan")
    prev_points = tracks.prev_points[selected].astype(np.float32)
    points = tracks.points[selected].astype(np.float32)
    finite = np.isfinite(prev_points).all(axis=1) & np.isfinite(points).all(axis=1)
    if not np.any(finite):
        return float("nan")
    disp = np.linalg.norm(points[finite] - prev_points[finite], axis=1)
    if len(disp) == 0:
        return float("nan")
    return float(np.median(disp.astype(np.float32)))


def _median_masked(values: np.ndarray, mask: np.ndarray) -> float:
    arr = np.asarray(values)
    selected = arr[np.asarray(mask, dtype=bool)]
    if len(selected) == 0:
        return float("nan")
    finite = selected[np.isfinite(selected.astype(np.float64))]
    if len(finite) == 0:
        return float("nan")
    return float(np.median(finite.astype(np.float64)))


def _source_selection_order(tracks: TrackSet, indices: np.ndarray, prefer_age: bool) -> np.ndarray:
    return _source_selection_order_with_quality_floor(
        tracks,
        indices,
        prefer_age=prefer_age,
        quality_floor=None,
    )


def _source_selection_order_with_quality_floor(
    tracks: TrackSet,
    indices: np.ndarray,
    *,
    prefer_age: bool,
    quality_floor: float | None,
) -> np.ndarray:
    if len(indices) == 0:
        return indices.astype(np.int64)
    idx = indices.astype(np.int64)
    q = np.clip(tracks.qualities[idx].astype(np.float32), 0.0, 1.0)
    if quality_floor is not None and float(quality_floor) > 0.0:
        q = np.maximum(q, float(quality_floor)).astype(np.float32)
    ncc = np.clip((tracks.ncc_scores[idx].astype(np.float32) + 1.0) * 0.5, 0.0, 1.0)
    fb = np.maximum(0.0, tracks.fb_errors[idx].astype(np.float32))
    fb_score = np.exp(-fb / 2.0).astype(np.float32)
    age = np.clip(tracks.ages[idx].astype(np.float32) / 20.0, 0.0, 1.0)
    age_weight = 0.45 if prefer_age else 0.20
    score = age_weight * age + 0.30 * q + 0.20 * ncc + 0.10 * fb_score
    return idx[np.argsort(-score)]


def _source_selection_order_with_klt_priority(
    tracks: TrackSet,
    indices: np.ndarray,
    prefer_age: bool,
) -> np.ndarray:
    if len(indices) == 0:
        return indices.astype(np.int64)
    idx = indices.astype(np.int64)
    base_order = _source_selection_order(tracks, idx, prefer_age=prefer_age)
    rank_by_index = {int(item): pos for pos, item in enumerate(base_order)}

    def source_priority(index: int) -> tuple[int, int]:
        source = str(tracks.sources[int(index)]).lower()
        if "klt" in source:
            group = 0
        elif "gftt" in source:
            group = 1
        else:
            group = 2
        return group, rank_by_index.get(int(index), len(rank_by_index))

    ordered = sorted((int(item) for item in idx), key=source_priority)
    return np.asarray(ordered, dtype=np.int64)


def _has_sidecar_source(tracks: TrackSet) -> bool:
    return any(_is_learned_source(source) or _is_recovered_source(source) for source in tracks.sources)


def _has_learned_source(tracks: TrackSet) -> bool:
    return any(_is_learned_source(source) for source in tracks.sources)


def _is_learned_source(source: str) -> bool:
    source_l = str(source).lower()
    return any(
        token in source_l
        for token in ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense")
    )


def _is_loftr_source(source: str) -> bool:
    return "loftr" in str(source).lower()


def _is_non_loftr_learned_source(source: str) -> bool:
    return _is_learned_source(source) and not _is_loftr_source(source)


def _is_sp_lg_source(source: str) -> bool:
    source_l = str(source).lower()
    return any(token in source_l for token in ("superpoint", "lightglue", "learned"))


def _is_xfeat_source(source: str) -> bool:
    return "xfeat" in str(source).lower()


def _is_classical_gftt_proposer_source(source: str) -> bool:
    return "classical_gftt" in str(source).lower()


def _is_confirmed_sidecar_source(source: str) -> bool:
    source_l = str(source).lower()
    return any(token in source_l for token in ("confirmed", "memory"))


def _is_recovered_source(source: str) -> bool:
    source_l = str(source).lower()
    if any(token in source_l for token in ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense")):
        return False
    return any(token in source_l for token in ("recovery", "memory"))


def _count_sources(tracks: TrackSet, predicate) -> int:
    return int(sum(1 for source in tracks.sources if predicate(source)))


def _source_histogram(tracks: TrackSet) -> str:
    counts: dict[str, int] = {}
    for source in tracks.sources:
        key = str(source)
        counts[key] = counts.get(key, 0) + 1
    return ";".join(f"{key}:{counts[key]}" for key in sorted(counts))


def _source_code(source: str) -> int:
    name = str(source).lower()
    if "classical_gftt" in name:
        return 21
    if "loftr" in name:
        return 30
    if "xfeat" in name:
        return 20
    if "superpoint" in name or "lightglue" in name or "learned" in name or "semidense" in name:
        return 10
    if "homography_recovery" in name:
        return 6
    if "lk_recovery" in name:
        return 5
    if "orb" in name:
        return 4
    if "gftt" in name:
        return 2
    if "klt" in name:
        return 1
    return 0


def _subset_tracks_by_indices(tracks: TrackSet, keep: np.ndarray) -> TrackSet:
    if len(keep) == 0:
        return TrackSet.empty()
    keep = np.asarray(keep, dtype=np.int64)
    return TrackSet(
        ids=tracks.ids[keep],
        prev_points=tracks.prev_points[keep],
        points=tracks.points[keep],
        ages=tracks.ages[keep],
        fb_errors=tracks.fb_errors[keep],
        ncc_scores=tracks.ncc_scores[keep],
        local_texture=tracks.local_texture[keep],
        qualities=tracks.qualities[keep],
        sources=[tracks.sources[int(idx)] for idx in keep],
    )


def _filter_young_learned_tracks(tracks: TrackSet, min_age: int) -> TrackSet:
    if len(tracks) == 0 or min_age <= 0:
        return tracks
    keep = []
    learned_tokens = ("learned", "xfeat", "superpoint", "lightglue", "loftr", "semidense")
    for idx, source in enumerate(tracks.sources):
        source_l = str(source).lower()
        is_learned = any(token in source_l for token in learned_tokens)
        keep.append((not is_learned) or int(tracks.ages[idx]) >= min_age)
    mask = np.asarray(keep, dtype=bool)
    if bool(np.all(mask)):
        return tracks
    return TrackSet(
        ids=tracks.ids[mask],
        prev_points=tracks.prev_points[mask],
        points=tracks.points[mask],
        ages=tracks.ages[mask],
        fb_errors=tracks.fb_errors[mask],
        ncc_scores=tracks.ncc_scores[mask],
        local_texture=tracks.local_texture[mask],
        qualities=tracks.qualities[mask],
        sources=[source for source, item_keep in zip(tracks.sources, mask) if bool(item_keep)],
    )


def _classical_tracks_are_healthy(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    *,
    min_tracks: int,
    min_grid: float,
    min_age: float,
) -> bool:
    if len(tracks) == 0:
        return False
    classical = _classical_backbone_mask(tracks)
    classical_count = int(np.count_nonzero(classical))
    if classical_count < max(0, int(min_tracks)):
        return False
    classical_grid = _track_grid_coverage(tracks, image_shape, classical)
    if classical_grid + 1e-9 < float(min_grid):
        return False
    if float(min_age) <= 0.0:
        return True
    classical_age = _median_masked(tracks.ages, classical)
    return math.isfinite(classical_age) and classical_age + 1e-9 >= float(min_age)


def _apply_recent_classical_health_suppression(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    recent_healthy_frames: int,
    min_healthy_frames: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    recent = max(0, int(recent_healthy_frames))
    threshold = max(1, int(min_healthy_frames))
    if len(tracks) == 0:
        return tracks, replace(
            info,
            health_suppression_reason="empty",
            recent_healthy_frames=recent,
        )
    if recent < threshold:
        return tracks, replace(
            info,
            health_suppression_reason=f"recent_health_below_threshold:{recent}/{threshold}",
            recent_healthy_frames=recent,
        )

    drop_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    dropped = int(np.count_nonzero(drop_mask))
    if dropped <= 0:
        return tracks, replace(
            info,
            health_suppression_reason=f"recent_health_no_non_loftr:{recent}/{threshold}",
            recent_healthy_frames=recent,
        )

    keep = np.flatnonzero(~drop_mask).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            info,
            dropped_learned=int(info.dropped_learned) + dropped,
            health_suppression_dropped=int(info.health_suppression_dropped) + dropped,
            health_suppression_reason=f"recent_classical_healthy:{recent}/{threshold}",
            recent_healthy_frames=recent,
        ),
    )


def _apply_stale_healthy_unconfirmed_suppression(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    state: _StaleHealthyUnconfirmedGateState,
    frame_index: int,
    recovery_reason: str,
    learned_confirmed_count: int,
    sidecar_observations_used: int,
    window: int,
    min_matched_frames: int,
    min_classical_tracks: int,
    min_classical_grid: float,
    min_classical_age: float,
    max_used_observations: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    threshold = max(1, int(min_matched_frames))
    non_loftr_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    non_loftr_count = int(np.count_nonzero(non_loftr_mask))
    reason = str(recovery_reason or "").lower()
    confirmed = max(0, int(learned_confirmed_count))
    count_ok = int(min_classical_tracks) <= 0 or int(info.classical_count) >= int(
        min_classical_tracks
    )
    grid_ok = (
        math.isfinite(float(info.classical_grid_coverage))
        and float(info.classical_grid_coverage) + 1e-9 >= float(min_classical_grid)
    )
    age_ok = (
        math.isfinite(float(info.classical_median_age))
        and float(info.classical_median_age) + 1e-9 >= float(min_classical_age)
    )
    used_ok = int(max_used_observations) <= 0 or int(sidecar_observations_used) <= int(
        max_used_observations
    )
    matched = bool(
        non_loftr_count > 0
        and reason == "healthy"
        and confirmed == 0
        and count_ok
        and grid_ok
        and age_ok
        and used_ok
    )
    recent = state.update(int(frame_index), matched=matched, window=int(window))
    base_reason = (
        f"stale_healthy_probe:{recent}/{threshold};"
        f"reason={reason or 'none'};confirmed={confirmed};"
        f"count={int(info.classical_count)};"
        f"grid={float(info.classical_grid_coverage):.3f};"
        f"age={float(info.classical_median_age):.1f};"
        f"used={int(sidecar_observations_used)}"
    )
    if non_loftr_count <= 0:
        return tracks, replace(
            info,
            health_suppression_reason="stale_healthy_no_non_loftr",
            recent_healthy_frames=recent,
        )
    if not matched or recent < threshold:
        return tracks, replace(
            info,
            health_suppression_reason=base_reason,
            recent_healthy_frames=recent,
        )

    keep = np.flatnonzero(~non_loftr_mask).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            info,
            dropped_learned=int(info.dropped_learned) + non_loftr_count,
            health_suppression_dropped=int(info.health_suppression_dropped)
            + non_loftr_count,
            health_suppression_reason=f"stale_healthy_unconfirmed:{base_reason}",
            recent_healthy_frames=recent,
        ),
    )


def _apply_short_low_grid_seed_suppression(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    state: _ShortLowGridSeedGateState,
    frame_index: int,
    recovery_reason: str,
    min_low_grid_seed_frames: int,
    max_gap: int,
    max_low_grid_frames: int,
    seed_window_gate: bool = False,
    early_max_start_frame: int = 40,
    early_min_seed: int = 3,
    early_max_seed: int = 8,
    late_min_seed: int = 5,
    late_max_seed: int = 10,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    non_loftr_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    non_loftr_count = int(np.count_nonzero(non_loftr_mask))
    reason = str(recovery_reason or "").lower()
    gate_reason = str(info.reason or "").lower()
    low_grid_context = ("low_grid" in reason) or ("frontend_low_grid" in gate_reason)
    seed_frames, seen_non_low_grid = state.update(
        int(frame_index),
        has_non_loftr_sidecar=non_loftr_count > 0,
        low_grid_context=bool(low_grid_context),
        max_gap=int(max_gap),
    )
    threshold = max(1, int(min_low_grid_seed_frames))
    base_reason = (
        f"short_lowgrid_seed_probe:seed={seed_frames}/{threshold};"
        f"seen_non_low_grid={int(seen_non_low_grid)};"
        f"burst_start={int(state.burst_start_frame)};"
        f"burst_index={int(state.burst_index)};"
        f"reason={reason or 'none'};gate={gate_reason or 'none'}"
    )
    if non_loftr_count <= 0:
        return tracks, replace(
            info,
            health_suppression_reason="short_lowgrid_seed_no_non_loftr",
        )
    seed_window_label = ""
    seed_window_suppression = False
    if (
        bool(seed_window_gate)
        and bool(low_grid_context)
        and not bool(seen_non_low_grid)
    ):
        burst_start = int(state.burst_start_frame)
        early_burst = bool(
            burst_start >= 0 and burst_start < int(early_max_start_frame)
        )
        min_seed = max(
            1,
            int(early_min_seed) if early_burst else int(late_min_seed),
        )
        max_seed = max(
            min_seed,
            int(early_max_seed) if early_burst else int(late_max_seed),
        )
        phase = "early" if early_burst else "late"
        base_reason = (
            f"{base_reason};seed_window={phase}:{min_seed}-{max_seed}"
        )
        if int(seed_frames) < min_seed:
            seed_window_suppression = True
            seed_window_label = "lowgrid_seed_window_wait"
        elif int(seed_frames) > max_seed:
            seed_window_suppression = True
            seed_window_label = "lowgrid_seed_window_after"
    risky_transition = bool(
        reason == "healthy"
        and bool(seen_non_low_grid)
        and 0 < int(seed_frames) < threshold
    )
    long_low_grid_tail = bool(
        int(max_low_grid_frames) > 0
        and bool(low_grid_context)
        and int(seed_frames) > int(max_low_grid_frames)
    )
    if not risky_transition and not long_low_grid_tail and not seed_window_suppression:
        return tracks, replace(
            info,
            health_suppression_reason=base_reason,
        )

    keep = np.flatnonzero(~non_loftr_mask).astype(np.int64)
    if seed_window_suppression:
        label = seed_window_label
    elif risky_transition:
        label = "short_lowgrid_seed"
    else:
        label = "long_lowgrid_burst"
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            info,
            dropped_learned=int(info.dropped_learned) + non_loftr_count,
            health_suppression_dropped=int(info.health_suppression_dropped)
            + non_loftr_count,
            health_suppression_reason=f"suppressed_{label}:{base_reason}",
        ),
    )


def _apply_recovery_reason_suppression(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    recovery_reason: str,
    tokens: str,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    reason = str(recovery_reason or "").lower()
    token_list = [
        token.strip().lower()
        for token in str(tokens or "").split(",")
        if token.strip()
    ]
    if len(tracks) == 0:
        return tracks, replace(info, recovery_reason_suppression_reason="empty")
    if not token_list:
        return tracks, replace(info, recovery_reason_suppression_reason="no_tokens")
    matched = [token for token in token_list if token in reason]
    if not matched:
        return tracks, replace(
            info,
            recovery_reason_suppression_reason=f"not_matched:{reason or 'none'}",
        )

    drop_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    dropped = int(np.count_nonzero(drop_mask))
    if dropped <= 0:
        return tracks, replace(
            info,
            recovery_reason_suppression_reason=f"matched_no_non_loftr:{'+'.join(matched)}",
        )

    keep = np.flatnonzero(~drop_mask).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            info,
            dropped_learned=int(info.dropped_learned) + dropped,
            recovery_reason_suppression_dropped=(
                int(info.recovery_reason_suppression_dropped) + dropped
            ),
            recovery_reason_suppression_reason=(
                f"suppressed_non_loftr:{'+'.join(matched)}"
            ),
        ),
    )


def _recovery_reason_matches_tokens(recovery_reason: str, tokens: str) -> bool:
    reason = str(recovery_reason or "").lower()
    token_list = [
        token.strip().lower()
        for token in str(tokens or "").split(",")
        if token.strip()
    ]
    return any(token in reason for token in token_list)


def _apply_recovery_reason_burst_suppression(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    recent_matched_frames: int,
    min_matched_frames: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    recent = max(0, int(recent_matched_frames))
    threshold = max(1, int(min_matched_frames))
    if len(tracks) == 0:
        return tracks, replace(
            info,
            recovery_burst_suppression_reason="empty",
            recovery_burst_recent_frames=recent,
        )
    if recent < threshold:
        return tracks, replace(
            info,
            recovery_burst_suppression_reason=f"recent_below_threshold:{recent}/{threshold}",
            recovery_burst_recent_frames=recent,
        )

    drop_mask = np.asarray(
        [_is_non_loftr_learned_source(source) for source in tracks.sources],
        dtype=bool,
    )
    dropped = int(np.count_nonzero(drop_mask))
    if dropped <= 0:
        return tracks, replace(
            info,
            recovery_burst_suppression_reason=f"burst_no_non_loftr:{recent}/{threshold}",
            recovery_burst_recent_frames=recent,
        )

    keep = np.flatnonzero(~drop_mask).astype(np.int64)
    return (
        _subset_tracks_by_indices(tracks, keep),
        replace(
            info,
            dropped_learned=int(info.dropped_learned) + dropped,
            recovery_burst_suppression_dropped=(
                int(info.recovery_burst_suppression_dropped) + dropped
            ),
            recovery_burst_suppression_reason=(
                f"burst_suppressed_non_loftr:{recent}/{threshold}"
            ),
            recovery_burst_recent_frames=recent,
        ),
    )


def _apply_visible_sidecar_track_gate(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    state: _VisibleSidecarTrackGateState,
    min_frames: int,
    max_mean_step_px: float = 0.0,
    min_count_per_frame: int = 0,
    min_count_min_classical_grid: float = 0.0,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    min_frames = max(1, int(min_frames))
    if len(tracks) == 0:
        return tracks, info
    if (
        min_frames <= 1
        and float(max_mean_step_px) <= 0.0
        and int(min_count_per_frame) <= 1
    ):
        return tracks, info
    keep: list[bool] = []
    dropped = 0
    for idx, source in enumerate(tracks.sources):
        if not (_is_learned_source(source) or _is_recovered_source(source)):
            keep.append(True)
            continue
        track_id = int(tracks.ids[idx])
        streak_ok = state.count(track_id) >= min_frames
        motion_ok = (
            float(max_mean_step_px) <= 0.0
            or state.mean_step_px(track_id) <= float(max_mean_step_px)
        )
        allow = bool(streak_ok and motion_ok)
        keep.append(bool(allow))
        if not allow:
            dropped += 1
    minimum_count = max(0, int(min_count_per_frame))
    count_gate_active = minimum_count > 1 and (
        float(min_count_min_classical_grid) <= 0.0
        or float(info.classical_grid_coverage)
        >= float(min_count_min_classical_grid)
    )
    allowed_sidecars = sum(
        bool(flag)
        for flag, source in zip(keep, tracks.sources)
        if _is_learned_source(source) or _is_recovered_source(source)
    )
    if count_gate_active and 0 < allowed_sidecars < minimum_count:
        for idx, source in enumerate(tracks.sources):
            if not (_is_learned_source(source) or _is_recovered_source(source)):
                continue
            if keep[idx]:
                keep[idx] = False
                dropped += 1
    if dropped == 0:
        return tracks, replace(
            info,
            temporal_reason=(
                info.temporal_reason
                if info.temporal_reason not in {"disabled", "not_run"}
                else f"visible_track_ok:{min_frames}"
            ),
        )
    mask = np.asarray(keep, dtype=bool)
    kept_tracks = _subset_tracks_by_indices(tracks, np.flatnonzero(mask).astype(np.int64))
    return kept_tracks, replace(
        info,
        dropped_learned=info.dropped_learned + int(dropped),
        temporal_dropped=info.temporal_dropped + int(dropped),
        temporal_reason=(
            f"visible_track_gate:{min_frames}:"
            f"max_mean_step_px={float(max_mean_step_px):.3f}:"
            f"min_count={minimum_count}:"
            f"min_count_grid={float(min_count_min_classical_grid):.3f}"
        ),
    )


def _apply_fresh_non_loftr_confirmation_gate(
    tracks: TrackSet,
    info: _LearnedExportGateInfo,
    *,
    state: _FreshSidecarConfirmationGateState,
    frame_index: int,
    fresh_confirmed_count: int,
    hold_frames: int,
) -> tuple[TrackSet, _LearnedExportGateInfo]:
    if len(tracks) == 0:
        state.prune(int(frame_index))
        return tracks, info

    sidecar_indices = [
        idx
        for idx, source in enumerate(tracks.sources)
        if _is_non_loftr_learned_source(source)
    ]
    if not sidecar_indices:
        state.prune(int(frame_index))
        return tracks, info

    confirmed_indices = [
        idx
        for idx in sidecar_indices
        if _is_confirmed_sidecar_source(tracks.sources[int(idx)])
    ]
    if int(fresh_confirmed_count) > 0:
        for idx in confirmed_indices:
            state.record(
                int(tracks.ids[int(idx)]),
                frame_index=int(frame_index),
                hold_frames=int(hold_frames),
            )

    keep = np.ones((len(tracks),), dtype=bool)
    dropped = 0
    for idx in sidecar_indices:
        source = tracks.sources[int(idx)]
        if not _is_confirmed_sidecar_source(source):
            keep[int(idx)] = False
            dropped += 1
            continue
        stable_confirmed = int(tracks.ages[int(idx)]) >= 1
        if stable_confirmed:
            state.record(
                int(tracks.ids[int(idx)]),
                frame_index=int(frame_index),
                hold_frames=max(0, int(hold_frames)),
            )
        if not state.allowed(int(tracks.ids[int(idx)]), frame_index=int(frame_index)):
            keep[int(idx)] = False
            dropped += 1

    if dropped == 0:
        return tracks, replace(
            info,
            temporal_reason=(
                info.temporal_reason
                if info.temporal_reason not in {"disabled", "not_run"}
                else "fresh_non_loftr_confirmation_ok"
            ),
        )

    kept_tracks = _subset_tracks_by_indices(
        tracks,
        np.flatnonzero(keep).astype(np.int64),
    )
    return kept_tracks, replace(
        info,
        dropped_learned=info.dropped_learned + int(dropped),
        temporal_dropped=info.temporal_dropped + int(dropped),
        temporal_reason="fresh_non_loftr_confirmation_required",
    )


class _ExportIdState:
    def __init__(self) -> None:
        self.id_map: dict[tuple[str, int], int] = {}
        self.prev_active: set[tuple[str, int]] = set()
        self.sidecar_memory_source: dict[int, str] = {}
        self.next_export_id = 10_000_000
        self.persistence_committed_sidecar_id: int | None = None
        self.persistence_churn_guard_armed: bool | None = None
        self.persistence_churn_guard_decision_frame = -1
        self.persistence_churn_guard_gftt_births = 0
        self.persistence_churn_guard_denominator = 0
        self.persistence_churn_guard_ratio = float("nan")

    def fresh_id(self) -> int:
        value = self.next_export_id
        self.next_export_id += 1
        return value


def _remap_recovered_export_ids(
    tracks: TrackSet,
    state: _ExportIdState,
    *,
    loftr_source_memory: bool = False,
) -> TrackSet:
    if len(tracks) == 0:
        state.prev_active = set()
        return tracks
    ids = tracks.ids.copy()
    sources = list(tracks.sources)
    current_active: set[tuple[str, int]] = set()
    for idx, (track_id, source) in enumerate(zip(tracks.ids, tracks.sources)):
        internal_id = int(track_id)
        reset_source = _is_learned_source(source) or _is_recovered_source(source)
        sidecar_key = ("sidecar", internal_id)
        memory_source = state.sidecar_memory_source.get(internal_id, "")
        continue_sidecar = (
            bool(loftr_source_memory)
            and (not reset_source)
            and sidecar_key in state.prev_active
            and _is_loftr_source(memory_source)
        )
        namespace = "sidecar" if (reset_source or continue_sidecar) else "classical"
        export_key = (namespace, internal_id)
        current_active.add(export_key)
        if export_key not in state.id_map:
            state.id_map[export_key] = (
                state.fresh_id() if namespace == "sidecar" else internal_id
            )
        elif namespace == "sidecar" and reset_source and export_key not in state.prev_active:
            # A revived sidecar starts a new landmark, while the simultaneous
            # mirror-KLT point with the same numeric id stays in its classical
            # namespace and keeps its identity.
            state.id_map[export_key] = state.fresh_id()
        if reset_source:
            state.sidecar_memory_source[internal_id] = _sidecar_memory_source_name(source)
        elif continue_sidecar:
            sources[idx] = state.sidecar_memory_source.get(internal_id, "learned_memory")
        ids[idx] = state.id_map[export_key]
    state.prev_active = current_active
    return TrackSet(
        ids=ids,
        prev_points=tracks.prev_points,
        points=tracks.points,
        ages=tracks.ages,
        fb_errors=tracks.fb_errors,
        ncc_scores=tracks.ncc_scores,
        local_texture=tracks.local_texture,
        qualities=tracks.qualities,
        sources=sources,
    )


def _sidecar_memory_source_name(source: str) -> str:
    if _is_loftr_source(source):
        return "loftr_memory"
    if _is_xfeat_source(source):
        return "xfeat_memory"
    if _is_sp_lg_source(source):
        return "superpoint_lightglue_memory"
    if _is_learned_source(source):
        return "learned_memory"
    if _is_recovered_source(source):
        return "recovery_memory"
    return "learned_memory"


def _pixels_to_normalized(points: np.ndarray, camera: dict) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0, 2), dtype=np.float32)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 1, 2)
    if camera.get("model") == "fisheye":
        undistorted = cv2.fisheye.undistortPoints(pts, camera["K"], camera["D"])
    else:
        undistorted = cv2.undistortPoints(pts, camera["K"], camera["D"])
    return undistorted.reshape(-1, 2).astype(np.float32)


def _camera_focal_mean_px(camera: dict) -> float:
    k_mat = np.asarray(camera.get("K"), dtype=np.float64)
    if k_mat.shape != (3, 3):
        return float("nan")
    return float(0.5 * (k_mat[0, 0] + k_mat[1, 1]))


def _pairwise_geometry_metrics(tracker) -> dict[str, object]:
    return {
        "pairwise_geometry_candidate_count": getattr(
            tracker,
            "last_pairwise_geometry_candidate_count",
            0,
        ),
        "pairwise_geometry_inlier_count": getattr(
            tracker,
            "last_pairwise_geometry_inlier_count",
            0,
        ),
        "pairwise_geometry_inlier_ratio": getattr(
            tracker,
            "last_pairwise_geometry_inlier_ratio",
            float("nan"),
        ),
        "pairwise_geometry_action": getattr(
            tracker,
            "last_pairwise_geometry_action",
            "not_applicable",
        ),
        "pairwise_geometry_reason": getattr(
            tracker,
            "last_pairwise_geometry_reason",
            "not_applicable",
        ),
    }


def _median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))


if __name__ == "__main__":
    raise SystemExit(main())
