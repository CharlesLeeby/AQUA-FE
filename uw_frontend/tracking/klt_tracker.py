from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from uw_frontend.quality.image_quality import ImageQuality, local_texture_scores
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


@dataclass
class KltConfig:
    max_features: int = 350
    min_distance: int = 18
    quality_level: float = 0.01
    block_size: int = 7
    lk_win_size: int = 21
    lk_max_level: int = 3
    fb_threshold: float = 1.0
    min_ncc: float = 0.65
    patch_radius: int = 5
    border: int = 8
    q_min: float = 0.05
    # Candidate-only online paths may disable local texture/quality metadata
    # when downstream publication forces a constant q_i.  Geometry, IDs,
    # FB/NCC filtering, and replenishment remain identical.
    compute_track_metadata: bool = True
    vectorized_ncc: bool = False


class KltTracker:
    def __init__(self, config: KltConfig | None = None) -> None:
        self.config = config or KltConfig()
        self.prev_image: np.ndarray | None = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0
        self.last_recovery_prev_image: np.ndarray | None = None
        self.last_lost_prev_points = np.empty((0, 2), dtype=np.float32)
        self.last_lost_ids = np.empty((0,), dtype=np.int64)
        self.last_lost_ages = np.empty((0,), dtype=np.int32)
        self.last_transition_diagnostics = _empty_transition_diagnostics()
        self.last_death_reasons: dict[int, str] = {}

    def reset(self) -> None:
        self.prev_image = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0
        self.last_recovery_prev_image = None
        self.last_lost_prev_points = np.empty((0, 2), dtype=np.float32)
        self.last_lost_ids = np.empty((0,), dtype=np.int64)
        self.last_lost_ages = np.empty((0,), dtype=np.int32)
        self.last_transition_diagnostics = _empty_transition_diagnostics()
        self.last_death_reasons = {}

    def process(
        self,
        image: np.ndarray,
        image_quality: ImageQuality,
        replenish: bool = True,
    ) -> tuple[TrackSet, TrackerDiagnostics]:
        gray = image.astype(np.uint8, copy=False)
        if self.prev_image is None:
            self.last_transition_diagnostics = _empty_transition_diagnostics()
            self.last_death_reasons = {}
            self.last_recovery_prev_image = None
            self.last_lost_prev_points = np.empty((0, 2), dtype=np.float32)
            self.last_lost_ids = np.empty((0,), dtype=np.int64)
            self.last_lost_ages = np.empty((0,), dtype=np.int32)
            # ``replenish=False`` must also apply to tracker initialization.
            # Hybrid temporal-admission profiles use this to keep first-frame
            # GFTT detections private until a later frame confirms them.
            added = self._detect_new(gray, self.config.max_features) if replenish else 0
            local_texture = (
                local_texture_scores(gray, self.points)
                if self.config.compute_track_metadata
                else np.ones((len(self.ids),), dtype=np.float32)
            )
            track_set = TrackSet(
                ids=self.ids.copy(),
                prev_points=self.points.copy(),
                points=self.points.copy(),
                ages=self.ages.copy(),
                fb_errors=np.zeros((len(self.ids),), dtype=np.float32),
                ncc_scores=np.ones((len(self.ids),), dtype=np.float32),
                local_texture=local_texture,
                qualities=np.full((len(self.ids),), image_quality.global_score, dtype=np.float32),
                sources=["gftt"] * len(self.ids),
            )
            self.prev_image = gray.copy()
            return track_set, TrackerDiagnostics(
                added_features=added,
                dropped_features=0,
                tracked_before_filter=0,
                tracked_after_filter=0,
                median_fb_error=0.0,
                median_ncc=1.0,
                median_quality=float(np.median(track_set.qualities)) if len(track_set) else 0.0,
            )

        prev_ids = self.ids.copy()
        tracked_before = len(self.points)
        track_set = self._track_existing(self.prev_image, gray, image_quality)
        dropped = tracked_before - len(track_set)

        need_new = max(0, self.config.max_features - len(self.points))
        added = self._detect_new(gray, need_new) if replenish else 0
        if added:
            new_slice = slice(len(self.points) - added, len(self.points))
            new_points = self.points[new_slice]
            new_ids = self.ids[new_slice]
            new_ages = self.ages[new_slice]
            new_local_texture = (
                local_texture_scores(gray, new_points)
                if self.config.compute_track_metadata
                else np.ones((added,), dtype=np.float32)
            )
            new_quality = (
                np.clip(
                    image_quality.global_score * (0.35 + 0.65 * new_local_texture),
                    self.config.q_min,
                    1.0,
                ).astype(np.float32)
                if self.config.compute_track_metadata
                else np.ones((added,), dtype=np.float32)
            )
            track_set = self._append_tracks(
                track_set,
                TrackSet(
                    ids=new_ids.copy(),
                    prev_points=new_points.copy(),
                    points=new_points.copy(),
                    ages=new_ages.copy(),
                    fb_errors=np.zeros((added,), dtype=np.float32),
                    ncc_scores=np.ones((added,), dtype=np.float32),
                    local_texture=new_local_texture,
                    qualities=new_quality,
                    sources=["gftt"] * added,
                ),
            )

        self.prev_image = gray.copy()
        return track_set, TrackerDiagnostics(
            added_features=added,
            dropped_features=dropped,
            tracked_before_filter=tracked_before,
            tracked_after_filter=len(prev_ids) - dropped,
            median_fb_error=_nanmedian(track_set.fb_errors),
            median_ncc=_nanmedian(track_set.ncc_scores),
            median_quality=_nanmedian(track_set.qualities),
        )

    def _track_existing(self, prev: np.ndarray, cur: np.ndarray, image_quality: ImageQuality) -> TrackSet:
        if len(self.points) == 0:
            self.last_transition_diagnostics = _empty_transition_diagnostics()
            self.last_death_reasons = {}
            self.last_recovery_prev_image = prev.copy()
            self.last_lost_prev_points = np.empty((0, 2), dtype=np.float32)
            self.last_lost_ids = np.empty((0,), dtype=np.int64)
            self.last_lost_ages = np.empty((0,), dtype=np.int32)
            return TrackSet.empty()

        old_points = self.points.copy()
        old_ids = self.ids.copy()
        old_ages = self.ages.copy()
        self.last_recovery_prev_image = prev.copy()
        prev_pts = self.points.reshape(-1, 1, 2).astype(np.float32)
        lk_params = dict(
            winSize=(self.config.lk_win_size, self.config.lk_win_size),
            maxLevel=self.config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        cur_pts, status, _ = cv2.calcOpticalFlowPyrLK(prev, cur, prev_pts, None, **lk_params)
        if cur_pts is None or status is None:
            self.last_transition_diagnostics = _empty_transition_diagnostics()
            self.last_transition_diagnostics.update(
                {
                    "klt_input_tracks": int(len(old_ids)),
                    "death_forward_fail": int(len(old_ids)),
                }
            )
            self.last_death_reasons = {
                int(track_id): "forward_fail" for track_id in old_ids
            }
            self.points = np.empty((0, 2), dtype=np.float32)
            self.ids = np.empty((0,), dtype=np.int64)
            self.ages = np.empty((0,), dtype=np.int32)
            return TrackSet.empty()

        back_pts, back_status, _ = cv2.calcOpticalFlowPyrLK(cur, prev, cur_pts, None, **lk_params)
        if back_pts is None or back_status is None:
            back_pts = prev_pts.copy()
            back_status = np.zeros_like(status)

        prev_flat = prev_pts.reshape(-1, 2)
        cur_flat = cur_pts.reshape(-1, 2)
        back_flat = back_pts.reshape(-1, 2)
        fb_errors = np.linalg.norm(prev_flat - back_flat, axis=1).astype(np.float32)
        ncc = (
            _patch_ncc_vectorized(
                prev, cur, prev_flat, cur_flat, self.config.patch_radius
            )
            if self.config.vectorized_ncc
            else _patch_ncc(prev, cur, prev_flat, cur_flat, self.config.patch_radius)
        )

        valid = (
            (status.reshape(-1) > 0)
            & (back_status.reshape(-1) > 0)
            & (fb_errors <= self.config.fb_threshold)
            & (ncc >= self.config.min_ncc)
            & _in_border(cur_flat, cur.shape, self.config.border)
        )
        forward_ok = status.reshape(-1) > 0
        backward_ok = forward_ok & (back_status.reshape(-1) > 0)
        fb_ok = backward_ok & np.isfinite(fb_errors) & (
            fb_errors <= self.config.fb_threshold
        )
        ncc_ok = fb_ok & np.isfinite(ncc) & (ncc >= self.config.min_ncc)
        border_ok = _in_border(cur_flat, cur.shape, self.config.border)
        exclusive = {
            "forward_fail": ~forward_ok,
            "backward_fail": forward_ok & ~(back_status.reshape(-1) > 0),
            "fb_fail": backward_ok
            & ~(np.isfinite(fb_errors) & (fb_errors <= self.config.fb_threshold)),
            "ncc_fail": fb_ok & ~(np.isfinite(ncc) & (ncc >= self.config.min_ncc)),
            "border_fail": ncc_ok & ~border_ok,
        }
        motion = np.linalg.norm(cur_flat[valid] - prev_flat[valid], axis=1)
        self.last_transition_diagnostics = {
            "klt_input_tracks": int(len(old_ids)),
            "klt_forward_status_ok": int(np.sum(forward_ok)),
            "klt_backward_status_ok": int(np.sum(backward_ok)),
            "klt_fb_pass": int(np.sum(fb_ok)),
            "klt_ncc_pass": int(np.sum(ncc_ok)),
            "klt_border_pass": int(np.sum(valid)),
            "klt_final_pass": int(np.sum(valid)),
            "death_forward_fail": int(np.sum(exclusive["forward_fail"])),
            "death_backward_fail": int(np.sum(exclusive["backward_fail"])),
            "death_fb_fail": int(np.sum(exclusive["fb_fail"])),
            "death_ncc_fail": int(np.sum(exclusive["ncc_fail"])),
            "death_border_fail": int(np.sum(exclusive["border_fail"])),
            "median_motion_px": float(np.median(motion)) if len(motion) else float("nan"),
            "p90_motion_px": float(np.percentile(motion, 90)) if len(motion) else float("nan"),
            "max_motion_px": float(np.max(motion)) if len(motion) else float("nan"),
        }
        self.last_death_reasons = {
            int(track_id): reason
            for reason, mask in exclusive.items()
            for track_id in old_ids[mask]
        }
        lost = ~valid
        self.last_lost_prev_points = old_points[lost].astype(np.float32)
        self.last_lost_ids = old_ids[lost].astype(np.int64)
        self.last_lost_ages = old_ages[lost].astype(np.int32)

        kept_prev = prev_flat[valid]
        kept_cur = cur_flat[valid]
        kept_ids = self.ids[valid]
        kept_ages = self.ages[valid] + 1
        kept_fb = fb_errors[valid]
        kept_ncc = ncc[valid]
        if self.config.compute_track_metadata:
            local_tex = local_texture_scores(cur, kept_cur)
            age_score = np.clip(kept_ages.astype(np.float32) / 20.0, 0.0, 1.0)
            fb_score = np.exp(-kept_fb / max(self.config.fb_threshold, 1e-3))
            ncc_score = np.clip((kept_ncc - self.config.min_ncc) / max(1e-3, 1.0 - self.config.min_ncc), 0.0, 1.0)
            quality = np.clip(
                image_quality.global_score
                * (0.25 + 0.75 * local_tex)
                * (0.20 + 0.80 * fb_score)
                * (0.30 + 0.70 * ncc_score)
                * (0.50 + 0.50 * age_score),
                self.config.q_min,
                1.0,
            ).astype(np.float32)
        else:
            local_tex = np.ones((len(kept_ids),), dtype=np.float32)
            quality = np.ones((len(kept_ids),), dtype=np.float32)

        self.points = kept_cur.astype(np.float32)
        self.ids = kept_ids.astype(np.int64)
        self.ages = kept_ages.astype(np.int32)

        return TrackSet(
            ids=self.ids.copy(),
            prev_points=kept_prev.astype(np.float32),
            points=self.points.copy(),
            ages=self.ages.copy(),
            fb_errors=kept_fb,
            ncc_scores=kept_ncc.astype(np.float32),
            local_texture=local_tex,
            qualities=quality,
            sources=["klt"] * len(self.ids),
        )

    def _detect_new(self, image: np.ndarray, count: int) -> int:
        if count <= 0:
            return 0
        mask = np.full(image.shape, 255, dtype=np.uint8)
        for x, y in self.points.reshape(-1, 2):
            cv2.circle(mask, (int(round(x)), int(round(y))), self.config.min_distance, 0, -1)
        pts = cv2.goodFeaturesToTrack(
            image,
            maxCorners=int(count),
            qualityLevel=self.config.quality_level,
            minDistance=self.config.min_distance,
            mask=mask,
            blockSize=self.config.block_size,
        )
        if pts is None:
            return 0
        new_points = pts.reshape(-1, 2).astype(np.float32)
        new_ids = np.arange(self.next_id, self.next_id + len(new_points), dtype=np.int64)
        self.next_id += len(new_points)
        self.points = np.vstack([self.points, new_points]).astype(np.float32)
        self.ids = np.concatenate([self.ids, new_ids])
        self.ages = np.concatenate([self.ages, np.ones((len(new_points),), dtype=np.int32)])
        return int(len(new_points))

    @staticmethod
    def _append_tracks(a: TrackSet, b: TrackSet) -> TrackSet:
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


def _in_border(points: np.ndarray, shape: tuple[int, int], border: int) -> np.ndarray:
    h, w = shape[:2]
    return (
        (points[:, 0] >= border)
        & (points[:, 0] < w - border)
        & (points[:, 1] >= border)
        & (points[:, 1] < h - border)
    )


def _empty_transition_diagnostics() -> dict[str, float | int]:
    return {
        "klt_input_tracks": 0,
        "klt_forward_status_ok": 0,
        "klt_backward_status_ok": 0,
        "klt_fb_pass": 0,
        "klt_ncc_pass": 0,
        "klt_border_pass": 0,
        "klt_final_pass": 0,
        "death_forward_fail": 0,
        "death_backward_fail": 0,
        "death_fb_fail": 0,
        "death_ncc_fail": 0,
        "death_border_fail": 0,
        "median_motion_px": float("nan"),
        "p90_motion_px": float("nan"),
        "max_motion_px": float("nan"),
    }


def _patch_ncc(
    prev: np.ndarray,
    cur: np.ndarray,
    prev_pts: np.ndarray,
    cur_pts: np.ndarray,
    radius: int,
) -> np.ndarray:
    scores = np.zeros((len(prev_pts),), dtype=np.float32)
    h, w = prev.shape[:2]
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(prev_pts, cur_pts)):
        ix0, iy0 = int(round(x0)), int(round(y0))
        ix1, iy1 = int(round(x1)), int(round(y1))
        if (
            ix0 - radius < 0
            or iy0 - radius < 0
            or ix0 + radius + 1 > w
            or iy0 + radius + 1 > h
            or ix1 - radius < 0
            or iy1 - radius < 0
            or ix1 + radius + 1 > w
            or iy1 + radius + 1 > h
        ):
            scores[i] = 0.0
            continue
        patch0 = prev[iy0 - radius : iy0 + radius + 1, ix0 - radius : ix0 + radius + 1].astype(np.float32)
        patch1 = cur[iy1 - radius : iy1 + radius + 1, ix1 - radius : ix1 + radius + 1].astype(np.float32)
        patch0 -= np.mean(patch0)
        patch1 -= np.mean(patch1)
        denom = float(np.linalg.norm(patch0) * np.linalg.norm(patch1))
        if denom <= 1e-6:
            scores[i] = 0.0
        else:
            scores[i] = float(np.clip(np.sum(patch0 * patch1) / denom, -1.0, 1.0))
    return scores


def _patch_ncc_vectorized(
    prev: np.ndarray,
    cur: np.ndarray,
    prev_pts: np.ndarray,
    cur_pts: np.ndarray,
    radius: int,
) -> np.ndarray:
    """Batch equivalent of :func:`_patch_ncc` for online candidate tracking."""
    scores = np.zeros((len(prev_pts),), dtype=np.float32)
    if len(prev_pts) == 0:
        return scores
    h, w = prev.shape[:2]
    x0 = np.rint(prev_pts[:, 0]).astype(np.int64)
    y0 = np.rint(prev_pts[:, 1]).astype(np.int64)
    x1 = np.rint(cur_pts[:, 0]).astype(np.int64)
    y1 = np.rint(cur_pts[:, 1]).astype(np.int64)
    inside = (
        (x0 - radius >= 0)
        & (y0 - radius >= 0)
        & (x0 + radius + 1 <= w)
        & (y0 + radius + 1 <= h)
        & (x1 - radius >= 0)
        & (y1 - radius >= 0)
        & (x1 + radius + 1 <= w)
        & (y1 + radius + 1 <= h)
    )
    indices = np.flatnonzero(inside)
    if len(indices) == 0:
        return scores
    offsets = np.arange(-radius, radius + 1, dtype=np.int64)
    dy = offsets.reshape(1, -1, 1)
    dx = offsets.reshape(1, 1, -1)
    patch0 = prev[
        y0[indices].reshape(-1, 1, 1) + dy,
        x0[indices].reshape(-1, 1, 1) + dx,
    ].astype(np.float32)
    patch1 = cur[
        y1[indices].reshape(-1, 1, 1) + dy,
        x1[indices].reshape(-1, 1, 1) + dx,
    ].astype(np.float32)
    patch0 -= np.mean(patch0, axis=(1, 2), keepdims=True)
    patch1 -= np.mean(patch1, axis=(1, 2), keepdims=True)
    numerator = np.sum(patch0 * patch1, axis=(1, 2))
    denominator = np.linalg.norm(patch0, axis=(1, 2)) * np.linalg.norm(
        patch1, axis=(1, 2)
    )
    valid = denominator > 1e-6
    selected_scores = np.zeros((len(indices),), dtype=np.float32)
    selected_scores[valid] = np.clip(
        numerator[valid] / denominator[valid], -1.0, 1.0
    )
    scores[indices] = selected_scores
    return scores


def _nanmedian(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))
