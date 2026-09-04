#!/usr/bin/env python3
"""Lightweight XFeat seed to LK lineage sidecar for an external KLT frontend."""

from __future__ import annotations

import argparse
import copy
import csv
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import rosbag
from sensor_msgs.msg import PointCloud

from uw_frontend.evaluation.run_frontend_eval import build_matcher, load_config
from uw_frontend.matchers.base import BaseMatcher
from uw_frontend.quality.image_quality import ImageQuality, score_image_quality
from uw_frontend.ros.causal_lineage_shadow_node import (
    CausalLineageShadow,
    ShadowConfig,
    _channel_values,
    _median_speed,
)
from uw_frontend.ros.export_vins_features import (
    _image_msg_to_gray,
    _load_pinhole_camera,
    _pixels_to_normalized,
    _preprocess_gray,
    _tracks_to_vins_pointcloud,
)
from uw_frontend.tracking.klt_tracker import _patch_ncc
from uw_frontend.tracking.track_state import TrackSet


@dataclass(frozen=True)
class SeedSidecarConfig:
    image_scale: float = 0.5
    preprocess: str = "adaptive_clahe"
    trigger_warmup_frames: int = 8
    trigger_cooldown_frames: int = 12
    max_triggers: int = 3
    force_periodic_trigger: bool = False
    rearm_on_seed_loss: bool = True
    trigger_degradation_min: float = 0.18
    trigger_flat_region_min: float = 0.10
    trigger_grid_texture_max: float = 0.90
    trigger_base_tracks_max: int = 300
    trigger_base_grid_max: float = 0.80
    trigger_dropout_min: float = 0.18
    trigger_long_track_ratio_max: float = 0.45
    seed_max_per_trigger: int = 8
    max_active_seeds: int = 24
    seed_min_base_distance_px: float = 8.0
    seed_min_active_distance_px: float = 10.0
    seed_grid_rows: int = 6
    seed_grid_cols: int = 6
    seed_max_per_cell: int = 2
    lk_win_size: int = 21
    lk_max_level: int = 3
    lk_fb_threshold: float = 1.20
    lk_min_ncc: float = 0.42
    birth_max_match_lk_error: float = 2.5
    motion_confirm_observations: int = 5
    min_motion_ratio: float = 0.6
    max_motion_ratio: float = 1.5
    max_homography_residual_px: float = 0.75
    ignore_zero_base_speeds: bool = False
    lk_patch_radius: int = 4
    border: int = 8
    id_base: int = 1_000_000


@dataclass
class _SeedTrack:
    feature_id: int
    prev_point: np.ndarray
    point: np.ndarray
    age: int
    fb_error: float
    ncc: float
    quality: float
    motion_ratios: list[float] = field(default_factory=list)
    homography_residuals: list[float] = field(default_factory=list)


class LearnedSeedKltSidecar:
    """Run XFeat only at trigger frames and LK only on learned seed tracks."""

    def __init__(
        self,
        matcher: BaseMatcher,
        camera: dict,
        config: SeedSidecarConfig,
        selector_config: ShadowConfig,
    ) -> None:
        if not 0.0 < config.image_scale <= 1.0:
            raise ValueError("image_scale must be in (0, 1]")
        self.matcher = matcher
        self.camera = camera
        self.config = config
        self.selector = CausalLineageShadow(selector_config)
        self.frame_index = 0
        self.trigger_count = 0
        self.last_trigger_frame = -10**9
        self.pending_optical_trigger = False
        self.next_id = int(config.id_base)
        self.prev_image: np.ndarray | None = None
        self.prev_stamp: float | None = None
        self.active: dict[int, _SeedTrack] = {}
        self.prev_base_ids: set[int] = set()
        self.base_id_ages: dict[int, int] = {}
        self.prev_base_norm_points: dict[int, np.ndarray] = {}
        self.velocity_scale_samples: list[float] = []
        self.velocity_contract_scale = 1.0

    def process(
        self,
        raw_gray: np.ndarray,
        base: PointCloud,
    ) -> tuple[PointCloud, PointCloud, dict[str, object]]:
        started = time.perf_counter()
        stamp = float(base.header.stamp.to_sec())
        gray = self._prepare_image(raw_gray)
        image_quality = score_image_quality(gray)
        dt = None if self.prev_stamp is None else max(1e-6, stamp - self.prev_stamp)
        base_motion_model = self._base_motion_model(base, dt)
        self._update_velocity_contract_scale(base, dt)
        tracked_before = len(self.active)
        self._track_existing(gray, image_quality, base, dt, base_motion_model)
        tracked_after = len(self.active)
        base_health = self._base_health(base, raw_gray.shape)
        trigger, trigger_reason = self._should_trigger(image_quality, base_health)
        match_count = 0
        added = 0
        match_ms = 0.0
        if trigger and self.prev_image is not None:
            match_started = time.perf_counter()
            matches = self.matcher.match(self.prev_image, gray)
            match_ms = (time.perf_counter() - match_started) * 1000.0
            match_count = len(matches)
            added = self._add_matches(matches, base, gray, image_quality, dt, base_motion_model)
            if added > 0:
                self.trigger_count += 1
                self.last_trigger_frame = self.frame_index
                self.pending_optical_trigger = False
            else:
                trigger_reason = f"{trigger_reason}+no_seed_retry"

        tracks = self._trackset_full_scale()
        sidecar_dt = (
            None
            if dt is None
            else float(dt) / max(1e-6, float(self.velocity_contract_scale))
        )
        sidecar = _tracks_to_vins_pointcloud(
            tracks,
            base.header.stamp,
            self.camera,
            sidecar_dt,
            backend_quality_mode="vins_safe",
            backend_quality_alpha=0.65,
        )
        sidecar.header = copy.deepcopy(base.header)
        merged, selector_decision = self.selector.process(base, sidecar)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        row: dict[str, object] = {
            "frame_index": self.frame_index,
            "stamp": stamp,
            "base_tracks": base_health["track_count"],
            "base_grid_coverage": base_health["grid_coverage"],
            "base_dropout_ratio": base_health["dropout_ratio"],
            "base_long_track_ratio": base_health["long_track_ratio"],
            "image_degradation": image_quality.degradation_score,
            "image_flat_region_ratio": image_quality.flat_region_ratio,
            "image_grid_texture": image_quality.grid_texture_score,
            "triggered": int(trigger),
            "trigger_reason": trigger_reason,
            "trigger_count": self.trigger_count,
            "match_count": match_count,
            "added_seeds": added,
            "tracked_before": tracked_before,
            "tracked_after": tracked_after,
            "active_seeds": len(self.active),
            "max_seed_age": max((track.age for track in self.active.values()), default=0),
            "velocity_contract_scale": self.velocity_contract_scale,
            "match_ms": match_ms,
            "processing_ms": elapsed_ms,
        }
        row.update({f"selector_{key}": value for key, value in selector_decision.items()})
        self.prev_image = gray.copy()
        self.prev_stamp = stamp
        self.frame_index += 1
        return sidecar, merged, row

    def _prepare_image(self, raw_gray: np.ndarray) -> np.ndarray:
        gray = np.asarray(raw_gray, dtype=np.uint8)
        if self.config.image_scale < 1.0:
            height, width = gray.shape[:2]
            output_size = (
                max(8, int(round(width * self.config.image_scale))),
                max(8, int(round(height * self.config.image_scale))),
            )
            gray = cv2.resize(gray, output_size, interpolation=cv2.INTER_AREA)
        return _preprocess_gray(gray, self.config.preprocess)

    def _update_velocity_contract_scale(self, base: PointCloud, dt: float | None) -> None:
        count = len(base.points)
        ids = [int(round(value)) for value in _channel_values(base, "id", count, -1.0)]
        current = {
            feature_id: np.asarray((point.x, point.y), dtype=np.float32)
            for feature_id, point in zip(ids, base.points)
            if feature_id >= 0
        }
        if dt is not None and self.prev_base_norm_points:
            velocity_x = _channel_values(base, "velocity_x", count, float("nan"))
            velocity_y = _channel_values(base, "velocity_y", count, float("nan"))
            ratios: list[float] = []
            for feature_id, point, vx, vy in zip(ids, base.points, velocity_x, velocity_y):
                previous = self.prev_base_norm_points.get(feature_id)
                if previous is None or not np.isfinite(vx) or not np.isfinite(vy):
                    continue
                actual_speed = float(
                    np.linalg.norm(np.asarray((point.x, point.y), dtype=np.float32) - previous)
                    / float(dt)
                )
                reported_speed = float(np.hypot(vx, vy))
                if actual_speed > 1e-6 and reported_speed > 1e-9:
                    ratios.append(reported_speed / actual_speed)
            if len(ratios) >= 3:
                frame_scale = float(np.median(ratios))
                if 0.2 <= frame_scale <= 2.0:
                    self.velocity_scale_samples.append(frame_scale)
                    self.velocity_scale_samples = self.velocity_scale_samples[-10:]
                    self.velocity_contract_scale = float(np.median(self.velocity_scale_samples))
        self.prev_base_norm_points = current

    def _track_existing(
        self,
        gray: np.ndarray,
        image_quality: ImageQuality,
        base: PointCloud,
        dt: float | None,
        base_motion_model: tuple[np.ndarray, float, float] | None,
    ) -> None:
        if self.prev_image is None or not self.active:
            return
        states = list(self.active.values())
        previous = np.asarray([track.point for track in states], dtype=np.float32).reshape(-1, 1, 2)
        current, status_forward, _ = cv2.calcOpticalFlowPyrLK(
            self.prev_image,
            gray,
            previous,
            None,
            winSize=(self.config.lk_win_size, self.config.lk_win_size),
            maxLevel=self.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if current is None or status_forward is None:
            self.active.clear()
            return
        backward, status_backward, _ = cv2.calcOpticalFlowPyrLK(
            gray,
            self.prev_image,
            current,
            None,
            winSize=(self.config.lk_win_size, self.config.lk_win_size),
            maxLevel=self.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if backward is None or status_backward is None:
            self.active.clear()
            return
        previous_2d = previous.reshape(-1, 2)
        current_2d = current.reshape(-1, 2)
        backward_2d = backward.reshape(-1, 2)
        fb = np.linalg.norm(previous_2d - backward_2d, axis=1)
        ncc = _patch_ncc(
            self.prev_image,
            gray,
            previous_2d,
            current_2d,
            self.config.lk_patch_radius,
        )
        motion_ratios = self._motion_ratios(previous_2d, current_2d, base, dt)
        geometry_residuals = self._homography_residuals(
            previous_2d, current_2d, base_motion_model
        )
        height, width = gray.shape[:2]
        keep = (
            status_forward.reshape(-1).astype(bool)
            & status_backward.reshape(-1).astype(bool)
            & (fb <= self.config.lk_fb_threshold)
            & (ncc >= self.config.lk_min_ncc)
            & (current_2d[:, 0] >= self.config.border)
            & (current_2d[:, 0] < width - self.config.border)
            & (current_2d[:, 1] >= self.config.border)
            & (current_2d[:, 1] < height - self.config.border)
        )
        updated: dict[int, _SeedTrack] = {}
        for index, (state, accepted) in enumerate(zip(states, keep)):
            if not bool(accepted):
                continue
            history = list(state.motion_ratios)
            if np.isfinite(motion_ratios[index]):
                history.append(float(motion_ratios[index]))
            if len(history) >= self.config.motion_confirm_observations:
                ratio = float(np.median(history[: self.config.motion_confirm_observations]))
                if not self.config.min_motion_ratio <= ratio <= self.config.max_motion_ratio:
                    continue
            geometry_history = list(state.homography_residuals)
            if np.isfinite(geometry_residuals[index]):
                geometry_history.append(float(geometry_residuals[index]))
            if len(geometry_history) >= self.config.motion_confirm_observations:
                residual = float(
                    np.median(geometry_history[: self.config.motion_confirm_observations])
                )
                if residual > self.config.max_homography_residual_px:
                    continue
            fb_score = max(0.0, 1.0 - float(fb[index]) / max(1e-6, self.config.lk_fb_threshold))
            ncc_score = max(0.0, min(1.0, (float(ncc[index]) + 1.0) * 0.5))
            quality = max(0.05, min(1.0, image_quality.global_score * (0.3 + 0.7 * fb_score) * ncc_score))
            updated[state.feature_id] = _SeedTrack(
                feature_id=state.feature_id,
                prev_point=previous_2d[index].copy(),
                point=current_2d[index].copy(),
                age=state.age + 1,
                fb_error=float(fb[index]),
                ncc=float(ncc[index]),
                quality=quality,
                motion_ratios=history,
                homography_residuals=geometry_history,
            )
        self.active = updated

    def _base_motion_model(
        self,
        base: PointCloud,
        dt: float | None,
    ) -> tuple[np.ndarray, float, float] | None:
        if dt is None or not self.prev_base_norm_points:
            return None
        count = len(base.points)
        ids = [int(round(value)) for value in _channel_values(base, "id", count, -1.0)]
        pairs = [
            (self.prev_base_norm_points[feature_id], np.asarray((point.x, point.y), dtype=np.float32))
            for feature_id, point in zip(ids, base.points)
            if feature_id in self.prev_base_norm_points
        ]
        if len(pairs) < 4:
            return None
        previous = np.asarray([pair[0] for pair in pairs], dtype=np.float32)
        current = np.asarray([pair[1] for pair in pairs], dtype=np.float32)
        finite = np.isfinite(previous).all(axis=1) & np.isfinite(current).all(axis=1)
        previous, current = previous[finite], current[finite]
        if len(previous) < 4:
            return None
        focal_x, focal_y = self._camera_focal_lengths()
        homography, _ = cv2.findHomography(
            previous,
            current,
            cv2.RANSAC,
            3.0 / max(focal_x, focal_y),
        )
        if homography is None:
            return None
        return homography, focal_x, focal_y

    def _camera_focal_lengths(self) -> tuple[float, float]:
        matrix = np.asarray(self.camera.get("K"), dtype=np.float64)
        if matrix.shape == (3, 3):
            return float(matrix[0, 0]), float(matrix[1, 1])
        projection = self.camera.get("projection_parameters", {})
        return float(projection.get("mu", 1.0)), float(projection.get("mv", 1.0))

    def _homography_residuals(
        self,
        previous: np.ndarray,
        current: np.ndarray,
        base_motion_model: tuple[np.ndarray, float, float] | None,
    ) -> np.ndarray:
        residuals = np.full((len(current),), float("nan"), dtype=np.float32)
        if base_motion_model is None or len(current) == 0:
            return residuals
        homography, focal_x, focal_y = base_motion_model
        inverse_scale = 1.0 / float(self.config.image_scale)
        previous_norm = _pixels_to_normalized(previous * inverse_scale, self.camera)
        current_norm = _pixels_to_normalized(current * inverse_scale, self.camera)
        points = np.column_stack(
            [previous_norm[:, 0], previous_norm[:, 1], np.ones((len(previous_norm),))]
        )
        projected = points @ homography.T
        valid = np.abs(projected[:, 2]) > 1e-9
        projected[valid, :2] /= projected[valid, 2:3]
        delta = projected[:, :2] - current_norm
        residuals[valid] = np.sqrt(
            (delta[valid, 0] * focal_x) ** 2 + (delta[valid, 1] * focal_y) ** 2
        )
        return residuals

    def _motion_ratios(
        self,
        previous: np.ndarray,
        current: np.ndarray,
        base: PointCloud,
        dt: float | None,
    ) -> np.ndarray:
        ratios = np.full((len(current),), float("nan"), dtype=np.float32)
        base_speed = _median_speed(
            base,
            ignore_zeros=self.config.ignore_zero_base_speeds,
        )
        if dt is None or base_speed is None or base_speed <= 1e-9 or len(current) == 0:
            return ratios
        inverse_scale = 1.0 / float(self.config.image_scale)
        previous_norm = _pixels_to_normalized(previous * inverse_scale, self.camera)
        current_norm = _pixels_to_normalized(current * inverse_scale, self.camera)
        speeds = (
            np.linalg.norm((current_norm - previous_norm) / float(dt), axis=1)
            * float(self.velocity_contract_scale)
        )
        return np.asarray(speeds / float(base_speed), dtype=np.float32)

    def _base_health(self, base: PointCloud, image_shape: tuple[int, ...]) -> dict[str, float | int]:
        count = len(base.points)
        raw_ids = _channel_values(base, "id", count, -1.0)
        ids = {int(round(value)) for value in raw_ids if float(value) >= 0.0}
        dropout = (
            1.0 - len(ids & self.prev_base_ids) / max(1, len(self.prev_base_ids))
            if self.prev_base_ids
            else 0.0
        )
        self.base_id_ages = {feature_id: self.base_id_ages.get(feature_id, 0) + 1 for feature_id in ids}
        long_ratio = sum(age >= 5 for age in self.base_id_ages.values()) / max(1, len(ids))
        p_u = _channel_values(base, "p_u", count, float("nan"))
        p_v = _channel_values(base, "p_v", count, float("nan"))
        height, width = image_shape[:2]
        cells: set[tuple[int, int]] = set()
        rows, cols = 6, 6
        for u, v in zip(p_u, p_v):
            if not np.isfinite(float(u)) or not np.isfinite(float(v)):
                continue
            row = min(rows - 1, max(0, int(float(v) / max(1, height) * rows)))
            col = min(cols - 1, max(0, int(float(u) / max(1, width) * cols)))
            cells.add((row, col))
        self.prev_base_ids = ids
        return {
            "track_count": len(ids),
            "grid_coverage": len(cells) / float(rows * cols),
            "dropout_ratio": dropout,
            "long_track_ratio": long_ratio,
        }

    def _should_trigger(
        self,
        quality: ImageQuality,
        base_health: dict[str, float | int],
    ) -> tuple[bool, str]:
        optical_reasons: list[str] = []
        if quality.degradation_score >= self.config.trigger_degradation_min:
            optical_reasons.append("degradation")
        if quality.flat_region_ratio >= self.config.trigger_flat_region_min:
            optical_reasons.append("flat_regions")
        if quality.grid_texture_score <= self.config.trigger_grid_texture_max:
            optical_reasons.append("low_grid_texture")
        if optical_reasons and self.frame_index < self.config.trigger_warmup_frames:
            self.pending_optical_trigger = True
        if self.prev_image is None:
            return False, "no_previous_image"
        if self.frame_index < self.config.trigger_warmup_frames:
            return False, "warmup_optical_latched" if self.pending_optical_trigger else "warmup"
        if self.trigger_count >= self.config.max_triggers:
            return False, "trigger_budget"
        in_cooldown = self.frame_index - self.last_trigger_frame < self.config.trigger_cooldown_frames
        severe_base = int(base_health["track_count"]) <= self.config.trigger_base_tracks_max
        identity_churn = (
            float(base_health["dropout_ratio"]) >= self.config.trigger_dropout_min
            and float(base_health["long_track_ratio"]) <= self.config.trigger_long_track_ratio_max
        )
        reasons = list(optical_reasons)
        if self.pending_optical_trigger:
            reasons.append("latched_optical")
        if severe_base:
            reasons.append("low_base_tracks")
        if identity_churn:
            reasons.append("identity_churn")
        if reasons and float(base_health["grid_coverage"]) <= self.config.trigger_base_grid_max:
            reasons.append("low_base_grid")
        if self.config.force_periodic_trigger:
            reasons.append("forced_periodic")
        if in_cooldown:
            if not self.config.rearm_on_seed_loss or self.active:
                return False, "cooldown"
            if reasons:
                reasons.append("seed_loss_rearm")
        if not reasons and float(base_health["grid_coverage"]) <= self.config.trigger_base_grid_max:
            return False, "low_base_grid_only"
        return bool(reasons), "+".join(reasons) if reasons else "healthy"

    def _add_matches(
        self,
        matches,
        base: PointCloud,
        gray: np.ndarray,
        image_quality: ImageQuality,
        dt: float | None,
        base_motion_model: tuple[np.ndarray, float, float] | None,
    ) -> int:
        if len(matches) == 0 or len(self.active) >= self.config.max_active_seeds:
            return 0
        previous = np.asarray(matches.points0, dtype=np.float32).reshape(-1, 2)
        current = np.asarray(matches.points1, dtype=np.float32).reshape(-1, 2)
        confidence = np.asarray(matches.confidences, dtype=np.float32).reshape(-1)
        if self.prev_image is None:
            return 0
        lk_current, forward_status, _ = cv2.calcOpticalFlowPyrLK(
            self.prev_image,
            gray,
            previous.reshape(-1, 1, 2),
            None,
            winSize=(self.config.lk_win_size, self.config.lk_win_size),
            maxLevel=self.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if lk_current is None or forward_status is None:
            return 0
        lk_backward, backward_status, _ = cv2.calcOpticalFlowPyrLK(
            gray,
            self.prev_image,
            lk_current,
            None,
            winSize=(self.config.lk_win_size, self.config.lk_win_size),
            maxLevel=self.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if lk_backward is None or backward_status is None:
            return 0
        lk_current_2d = lk_current.reshape(-1, 2)
        lk_backward_2d = lk_backward.reshape(-1, 2)
        birth_fb = np.linalg.norm(previous - lk_backward_2d, axis=1)
        birth_ncc = _patch_ncc(
            self.prev_image,
            gray,
            previous,
            lk_current_2d,
            self.config.lk_patch_radius,
        )
        match_lk_error = np.linalg.norm(current - lk_current_2d, axis=1)
        current = lk_current_2d
        birth_motion_ratios = self._motion_ratios(previous, current, base, dt)
        birth_geometry_residuals = self._homography_residuals(
            previous, current, base_motion_model
        )
        image_shape = gray.shape
        height, width = image_shape[:2]
        finite = np.isfinite(previous).all(axis=1) & np.isfinite(current).all(axis=1)
        finite &= (
            forward_status.reshape(-1).astype(bool)
            & backward_status.reshape(-1).astype(bool)
            & (birth_fb <= self.config.lk_fb_threshold)
            & (birth_ncc >= self.config.lk_min_ncc)
            & (match_lk_error <= self.config.birth_max_match_lk_error)
        )
        border = self.config.border
        finite &= (
            (current[:, 0] >= border)
            & (current[:, 0] < width - border)
            & (current[:, 1] >= border)
            & (current[:, 1] < height - border)
        )
        previous, current, confidence = previous[finite], current[finite], confidence[finite]
        birth_fb, birth_ncc = birth_fb[finite], birth_ncc[finite]
        birth_motion_ratios = birth_motion_ratios[finite]
        birth_geometry_residuals = birth_geometry_residuals[finite]
        if len(current) == 0:
            return 0
        base_points = self._base_points_scaled(base)
        if len(base_points):
            nearest_base = np.sqrt(
                np.min(np.sum((current[:, None, :] - base_points[None, :, :]) ** 2, axis=2), axis=1)
            ) / self.config.image_scale
        else:
            nearest_base = np.full((len(current),), float("inf"), dtype=np.float32)
        active_points = np.asarray([track.point for track in self.active.values()], dtype=np.float32)
        if len(active_points):
            nearest_active = np.sqrt(
                np.min(np.sum((current[:, None, :] - active_points[None, :, :]) ** 2, axis=2), axis=1)
            ) / self.config.image_scale
        else:
            nearest_active = np.full((len(current),), float("inf"), dtype=np.float32)
        eligible = (
            (nearest_base >= self.config.seed_min_base_distance_px)
            & (nearest_active >= self.config.seed_min_active_distance_px)
        )
        indices = np.flatnonzero(eligible)
        if len(indices) == 0:
            return 0
        order = indices[
            np.lexsort((-confidence[indices], -birth_ncc[indices], -nearest_base[indices]))
        ]
        cell_counts: dict[tuple[int, int], int] = {}
        for track in self.active.values():
            cell = self._cell(track.point, image_shape)
            cell_counts[cell] = cell_counts.get(cell, 0) + 1
        capacity = min(
            self.config.seed_max_per_trigger,
            self.config.max_active_seeds - len(self.active),
        )
        added = 0
        for index in order:
            cell = self._cell(current[index], image_shape)
            if cell_counts.get(cell, 0) >= self.config.seed_max_per_cell:
                continue
            feature_id = self.next_id
            self.next_id += 1
            self.active[feature_id] = _SeedTrack(
                feature_id=feature_id,
                prev_point=previous[index].copy(),
                point=current[index].copy(),
                age=1,
                fb_error=float(birth_fb[index]),
                ncc=float(birth_ncc[index]),
                quality=max(0.05, min(1.0, float(confidence[index]) * image_quality.global_score)),
                motion_ratios=(
                    [float(birth_motion_ratios[index])]
                    if np.isfinite(birth_motion_ratios[index])
                    else []
                ),
                homography_residuals=(
                    [float(birth_geometry_residuals[index])]
                    if np.isfinite(birth_geometry_residuals[index])
                    else []
                ),
            )
            cell_counts[cell] = cell_counts.get(cell, 0) + 1
            added += 1
            if added >= capacity:
                break
        return added

    def _base_points_scaled(self, base: PointCloud) -> np.ndarray:
        count = len(base.points)
        p_u = _channel_values(base, "p_u", count, float("nan"))
        p_v = _channel_values(base, "p_v", count, float("nan"))
        points = np.asarray(
            [(float(u), float(v)) for u, v in zip(p_u, p_v) if np.isfinite(u) and np.isfinite(v)],
            dtype=np.float32,
        ).reshape(-1, 2)
        return points * float(self.config.image_scale)

    def _cell(self, point: np.ndarray, shape: tuple[int, int]) -> tuple[int, int]:
        height, width = shape[:2]
        row = min(
            self.config.seed_grid_rows - 1,
            max(0, int(float(point[1]) / max(1, height) * self.config.seed_grid_rows)),
        )
        col = min(
            self.config.seed_grid_cols - 1,
            max(0, int(float(point[0]) / max(1, width) * self.config.seed_grid_cols)),
        )
        return row, col

    def _trackset_full_scale(self) -> TrackSet:
        if not self.active:
            return TrackSet.empty()
        states = list(self.active.values())
        inverse_scale = 1.0 / float(self.config.image_scale)
        return TrackSet(
            ids=np.asarray([track.feature_id for track in states], dtype=np.int64),
            prev_points=np.asarray([track.prev_point for track in states], dtype=np.float32) * inverse_scale,
            points=np.asarray([track.point for track in states], dtype=np.float32) * inverse_scale,
            ages=np.asarray([track.age for track in states], dtype=np.int32),
            fb_errors=np.asarray([track.fb_error for track in states], dtype=np.float32),
            ncc_scores=np.asarray([track.ncc for track in states], dtype=np.float32),
            local_texture=np.ones((len(states),), dtype=np.float32),
            qualities=np.asarray([track.quality for track in states], dtype=np.float32),
            sources=["xfeat_seed_klt"] * len(states),
        )


def _write_stats(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]) if rows else ["frame_index"])
        writer.writeheader()
        writer.writerows(rows)


def _stamp_seconds(msg, bag_stamp) -> float:
    if hasattr(msg, "header") and msg.header.stamp.to_sec() > 0.0:
        return float(msg.header.stamp.to_sec())
    return float(bag_stamp.to_sec())


def run_bag(args: argparse.Namespace) -> int:
    from cv_bridge import CvBridge

    core = _build_core(args)
    bridge = CvBridge()
    base_messages: list[tuple[float, PointCloud]] = []
    with rosbag.Bag(args.base_bag, "r") as bag:
        for _topic, msg, stamp in bag.read_messages(topics=[args.base_topic]):
            base_messages.append((_stamp_seconds(msg, stamp), msg))
    base_index = 0
    merged_messages: list[PointCloud] = []
    sidecar_messages: list[PointCloud] = []
    rows: list[dict[str, object]] = []
    with rosbag.Bag(args.image_bag, "r") as bag:
        for _topic, msg, stamp in bag.read_messages(topics=[args.image_topic]):
            if base_index >= len(base_messages):
                break
            image_stamp = _stamp_seconds(msg, stamp)
            while (
                base_index < len(base_messages)
                and base_messages[base_index][0] < image_stamp - args.match_tolerance
            ):
                raise ValueError(f"missing image for base frame {base_index}")
            if base_index >= len(base_messages):
                break
            delta = abs(base_messages[base_index][0] - image_stamp)
            if delta > args.match_tolerance:
                continue
            gray = _image_msg_to_gray(bridge, msg)
            sidecar, merged, row = core.process(gray, base_messages[base_index][1])
            row["image_match_delta_s"] = delta
            sidecar_messages.append(sidecar)
            merged_messages.append(merged)
            rows.append(row)
            base_index += 1
    if base_index != len(base_messages):
        raise ValueError(f"matched {base_index}/{len(base_messages)} base feature frames")

    output_path = Path(args.output_bag)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    feature_index = 0
    with rosbag.Bag(args.base_bag, "r") as source, rosbag.Bag(str(output_path), "w") as output:
        for topic, msg, stamp in source.read_messages():
            if topic == args.base_topic:
                msg = merged_messages[feature_index]
                feature_index += 1
            output.write(topic, msg, stamp)
    sidecar_path = Path(args.sidecar_bag)
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with rosbag.Bag(str(sidecar_path), "w") as output:
        for msg in sidecar_messages:
            output.write(args.sidecar_topic, msg, msg.header.stamp)
    _write_stats(Path(args.stats_csv), rows)
    injected = sum(int(row["selector_injected_observations"]) for row in rows)
    print(
        f"frames={len(rows)} triggers={core.trigger_count} "
        f"selected={';'.join(str(item) for item in sorted(core.selector.selected_ids))} "
        f"injected={injected}"
    )
    return 0


def run_ros(args: argparse.Namespace) -> int:
    from cv_bridge import CvBridge
    import message_filters
    import rospy

    rospy.init_node("xfeat_seed_sidecar")
    core = _build_core(args)
    bridge = CvBridge()
    sidecar_publisher = rospy.Publisher(args.sidecar_topic, PointCloud, queue_size=10)
    output_publisher = rospy.Publisher(args.output_topic, PointCloud, queue_size=10)
    jobs: queue.Queue[tuple[object, PointCloud]] = queue.Queue(maxsize=args.worker_queue)
    stopped = threading.Event()
    dropped_jobs = 0

    def worker() -> None:
        while not stopped.is_set() or not jobs.empty():
            try:
                image_msg, base_msg = jobs.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                gray = _image_msg_to_gray(bridge, image_msg)
                sidecar, merged, row = core.process(gray, base_msg)
                sidecar_publisher.publish(sidecar)
                output_publisher.publish(merged)
                if int(row["triggered"]):
                    rospy.loginfo(
                        "XFeat sidecar trigger=%s matches=%d added=%d active=%d processing_ms=%.1f",
                        row["trigger_reason"],
                        row["match_count"],
                        row["added_seeds"],
                        row["active_seeds"],
                        row["processing_ms"],
                    )
            except Exception as exc:  # pragma: no cover - ROS runtime guard
                rospy.logerr("XFeat sidecar worker failed: %s", exc)
            finally:
                jobs.task_done()

    worker_thread = threading.Thread(target=worker, name="xfeat-seed-worker", daemon=True)
    worker_thread.start()

    def callback(image_msg, base_msg: PointCloud) -> None:
        nonlocal dropped_jobs
        try:
            jobs.put_nowait((image_msg, base_msg))
        except queue.Full:
            dropped_jobs += 1
            rospy.logwarn_throttle(2.0, "XFeat sidecar queue full; dropped jobs=%d", dropped_jobs)

    image_sub = message_filters.Subscriber(args.image_topic, args.image_message_type)
    base_sub = message_filters.Subscriber(args.base_topic, PointCloud)
    synchronizer = message_filters.ApproximateTimeSynchronizer(
        [image_sub, base_sub], queue_size=args.sync_queue, slop=args.match_tolerance
    )
    synchronizer.registerCallback(callback)

    def shutdown() -> None:
        stopped.set()
        worker_thread.join(timeout=2.0)

    rospy.on_shutdown(shutdown)
    rospy.spin()
    return 0


def _build_core(args: argparse.Namespace) -> LearnedSeedKltSidecar:
    cfg = load_config(args.config)
    matcher = build_matcher("hybrid_xfeat", cfg)
    camera = _load_pinhole_camera(Path(args.camera_config))
    sidecar_config = SeedSidecarConfig(
        image_scale=args.image_scale,
        preprocess=args.preprocess,
        trigger_warmup_frames=args.trigger_warmup_frames,
        trigger_cooldown_frames=args.trigger_cooldown_frames,
        max_triggers=args.max_triggers,
        force_periodic_trigger=args.force_periodic_trigger,
        rearm_on_seed_loss=not args.disable_seed_loss_rearm,
        trigger_degradation_min=args.trigger_degradation_min,
        trigger_flat_region_min=args.trigger_flat_region_min,
        trigger_grid_texture_max=args.trigger_grid_texture_max,
        trigger_base_tracks_max=args.trigger_base_tracks_max,
        trigger_base_grid_max=args.trigger_base_grid_max,
        trigger_dropout_min=args.trigger_dropout_min,
        trigger_long_track_ratio_max=args.trigger_long_track_ratio_max,
        seed_max_per_trigger=args.seed_max_per_trigger,
        max_active_seeds=args.max_active_seeds,
        seed_min_base_distance_px=args.seed_min_base_distance_px,
        seed_min_active_distance_px=args.seed_min_active_distance_px,
        seed_max_per_cell=args.seed_max_per_cell,
        lk_fb_threshold=args.lk_fb_threshold,
        lk_min_ncc=args.lk_min_ncc,
        motion_confirm_observations=args.rank_observations,
        min_motion_ratio=args.min_motion_ratio,
        max_motion_ratio=args.max_motion_ratio,
        max_homography_residual_px=args.max_homography_residual_px,
        ignore_zero_base_speeds=args.ignore_zero_base_speeds,
    )
    selector_config = ShadowConfig(
        source_code=20,
        min_observations=args.min_observations,
        rank_observations=args.rank_observations,
        min_distance_px=args.min_distance_px,
        min_motion_ratio=args.min_motion_ratio,
        max_motion_ratio=args.max_motion_ratio,
        max_lineages=args.max_lineages,
        remap_id_base=args.remap_id_base,
        ignore_zero_base_speeds=args.ignore_zero_base_speeds,
    )
    return LearnedSeedKltSidecar(matcher, camera, sidecar_config, selector_config)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for name in ("bag", "ros"):
        child = subparsers.add_parser(name)
        child.add_argument("--config", required=True)
        child.add_argument("--camera-config", required=True)
        child.add_argument("--image-topic", default="/camera/image_raw")
        child.add_argument("--base-topic", default="/feature_tracker/base")
        child.add_argument("--sidecar-topic", default="/feature_tracker/sidecar")
        child.add_argument("--image-scale", type=float, default=0.5)
        child.add_argument(
            "--preprocess",
            choices=["none", "equalize", "clahe", "adaptive_clahe"],
            default="adaptive_clahe",
        )
        child.add_argument("--trigger-cooldown-frames", type=int, default=12)
        child.add_argument("--trigger-warmup-frames", type=int, default=8)
        child.add_argument("--max-triggers", type=int, default=3)
        child.add_argument("--force-periodic-trigger", action="store_true")
        child.add_argument("--disable-seed-loss-rearm", action="store_true")
        child.add_argument("--trigger-degradation-min", type=float, default=0.18)
        child.add_argument("--trigger-flat-region-min", type=float, default=0.10)
        child.add_argument("--trigger-grid-texture-max", type=float, default=0.90)
        child.add_argument("--trigger-base-tracks-max", type=int, default=300)
        child.add_argument("--trigger-base-grid-max", type=float, default=0.80)
        child.add_argument("--trigger-dropout-min", type=float, default=0.18)
        child.add_argument("--trigger-long-track-ratio-max", type=float, default=0.45)
        child.add_argument("--seed-max-per-trigger", type=int, default=8)
        child.add_argument("--max-active-seeds", type=int, default=24)
        child.add_argument("--seed-min-base-distance-px", type=float, default=8.0)
        child.add_argument("--seed-min-active-distance-px", type=float, default=10.0)
        child.add_argument("--seed-max-per-cell", type=int, default=2)
        child.add_argument("--lk-fb-threshold", type=float, default=1.20)
        child.add_argument("--lk-min-ncc", type=float, default=0.42)
        child.add_argument("--min-observations", type=int, default=5)
        child.add_argument("--rank-observations", type=int, default=5)
        child.add_argument("--min-distance-px", type=float, default=40.0)
        child.add_argument("--min-motion-ratio", type=float, default=0.6)
        child.add_argument("--max-motion-ratio", type=float, default=1.5)
        child.add_argument("--max-homography-residual-px", type=float, default=0.75)
        child.add_argument("--ignore-zero-base-speeds", action="store_true")
        child.add_argument("--max-lineages", type=int, default=1)
        child.add_argument("--remap-id-base", type=int, default=10_000_000)
        child.add_argument("--match-tolerance", type=float, default=0.02)
    bag = subparsers.choices["bag"]
    bag.add_argument("--image-bag", required=True)
    bag.add_argument("--base-bag", required=True)
    bag.add_argument("--output-bag", required=True)
    bag.add_argument("--sidecar-bag", required=True)
    bag.add_argument("--stats-csv", required=True)
    ros = subparsers.choices["ros"]
    ros.add_argument("--output-topic", default="/feature_tracker/feature")
    ros.add_argument("--sync-queue", type=int, default=50)
    ros.add_argument("--worker-queue", type=int, default=8)
    ros.add_argument("--compressed-image", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.mode == "ros":
        from sensor_msgs.msg import CompressedImage, Image

        args.image_message_type = CompressedImage if args.compressed_image else Image
    return run_bag(args) if args.mode == "bag" else run_ros(args)


if __name__ == "__main__":
    raise SystemExit(main())
