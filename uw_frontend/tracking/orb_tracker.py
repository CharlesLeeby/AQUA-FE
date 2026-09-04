from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from uw_frontend.quality.image_quality import ImageQuality, local_texture_scores
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


@dataclass
class OrbConfig:
    max_features: int = 600
    output_features: int = 350
    scale_factor: float = 1.2
    n_levels: int = 8
    edge_threshold: int = 15
    patch_size: int = 31
    fast_threshold: int = 12
    max_hamming_distance: int = 72
    min_ncc: float = 0.55
    ncc_patch_radius: int = 5
    q_min: float = 0.05


class OrbTracker:
    """Pairwise ORB matching baseline with persistent track ids.

    ORB is not a long-term tracker in the same sense as KLT. This adapter keeps
    ids across consecutive descriptor matches and adds unmatched detections as
    new short tracks, which makes its metrics comparable in the frontend CSV.
    """

    def __init__(self, config: OrbConfig | None = None) -> None:
        self.config = config or OrbConfig()
        self.orb = cv2.ORB_create(
            nfeatures=self.config.max_features,
            scaleFactor=self.config.scale_factor,
            nlevels=self.config.n_levels,
            edgeThreshold=self.config.edge_threshold,
            patchSize=self.config.patch_size,
            fastThreshold=self.config.fast_threshold,
        )
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        self.prev_image: np.ndarray | None = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.descriptors: np.ndarray | None = None
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0

    def reset(self) -> None:
        self.prev_image = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.descriptors = None
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0

    def process(self, image: np.ndarray, image_quality: ImageQuality) -> tuple[TrackSet, TrackerDiagnostics]:
        gray = image.astype(np.uint8, copy=False)
        keypoints, descriptors = self.orb.detectAndCompute(gray, None)
        cur_points = _keypoints_to_points(keypoints)

        if descriptors is None or len(cur_points) == 0:
            dropped = len(self.ids)
            self.prev_image = gray.copy()
            self.points = np.empty((0, 2), dtype=np.float32)
            self.descriptors = None
            self.ids = np.empty((0,), dtype=np.int64)
            self.ages = np.empty((0,), dtype=np.int32)
            return TrackSet.empty(), TrackerDiagnostics(0, dropped, dropped, 0, float("nan"), float("nan"), float("nan"))

        if self.prev_image is None or self.descriptors is None or len(self.points) == 0:
            used = min(self.config.output_features, len(cur_points))
            order = _rank_keypoints_by_response(keypoints)[:used]
            self.points = cur_points[order].astype(np.float32)
            self.descriptors = descriptors[order].copy()
            self.ids = np.arange(self.next_id, self.next_id + used, dtype=np.int64)
            self.next_id += used
            self.ages = np.ones((used,), dtype=np.int32)
            qualities = _new_track_quality(gray, self.points, image_quality, self.config.q_min)
            tracks = TrackSet(
                ids=self.ids.copy(),
                prev_points=self.points.copy(),
                points=self.points.copy(),
                ages=self.ages.copy(),
                fb_errors=np.zeros((used,), dtype=np.float32),
                ncc_scores=np.ones((used,), dtype=np.float32),
                local_texture=local_texture_scores(gray, self.points),
                qualities=qualities,
                sources=["orb"] * used,
            )
            self.prev_image = gray.copy()
            return tracks, TrackerDiagnostics(used, 0, 0, 0, 0.0, 1.0, float(np.median(qualities)) if used else 0.0)

        prev_count = len(self.ids)
        matches = self.matcher.match(self.descriptors, descriptors)
        matches = [m for m in matches if m.distance <= self.config.max_hamming_distance]
        matches.sort(key=lambda m: m.distance)
        matches = matches[: self.config.output_features]

        prev_indices = np.asarray([m.queryIdx for m in matches], dtype=np.int64)
        cur_indices = np.asarray([m.trainIdx for m in matches], dtype=np.int64)
        distances = np.asarray([m.distance for m in matches], dtype=np.float32)

        matched_prev = self.points[prev_indices] if len(matches) else np.empty((0, 2), dtype=np.float32)
        matched_cur = cur_points[cur_indices] if len(matches) else np.empty((0, 2), dtype=np.float32)
        matched_ids = self.ids[prev_indices] if len(matches) else np.empty((0,), dtype=np.int64)
        matched_ages = self.ages[prev_indices] + 1 if len(matches) else np.empty((0,), dtype=np.int32)
        ncc_scores = _patch_ncc(self.prev_image, gray, matched_prev, matched_cur, self.config.ncc_patch_radius)
        valid = ncc_scores >= self.config.min_ncc

        matched_prev = matched_prev[valid]
        matched_cur = matched_cur[valid]
        matched_ids = matched_ids[valid]
        matched_ages = matched_ages[valid]
        distances = distances[valid]
        ncc_scores = ncc_scores[valid]

        local_tex = local_texture_scores(gray, matched_cur)
        descriptor_score = np.clip(1.0 - distances / max(1.0, float(self.config.max_hamming_distance)), 0.0, 1.0)
        age_score = np.clip(matched_ages.astype(np.float32) / 20.0, 0.0, 1.0)
        matched_quality = np.clip(
            image_quality.global_score
            * (0.25 + 0.75 * local_tex)
            * (0.30 + 0.70 * descriptor_score)
            * (0.30 + 0.70 * ncc_scores)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)

        unmatched_mask = np.ones((len(cur_points),), dtype=bool)
        if len(cur_indices):
            unmatched_mask[cur_indices] = False
        unmatched_indices = np.where(unmatched_mask)[0]
        if len(unmatched_indices):
            response_order = _rank_keypoints_by_response([keypoints[i] for i in unmatched_indices])
            unmatched_indices = unmatched_indices[response_order]

        add_count = max(0, self.config.output_features - len(matched_cur))
        add_indices = unmatched_indices[:add_count]
        new_points = cur_points[add_indices].astype(np.float32)
        new_ids = np.arange(self.next_id, self.next_id + len(new_points), dtype=np.int64)
        self.next_id += len(new_points)
        new_ages = np.ones((len(new_points),), dtype=np.int32)
        new_quality = _new_track_quality(gray, new_points, image_quality, self.config.q_min)

        all_points = np.vstack([matched_cur, new_points]).astype(np.float32)
        all_prev_points = np.vstack([matched_prev, new_points]).astype(np.float32)
        all_ids = np.concatenate([matched_ids, new_ids])
        all_ages = np.concatenate([matched_ages, new_ages])
        all_fb = np.concatenate([
            distances.astype(np.float32),
            np.zeros((len(new_points),), dtype=np.float32),
        ])
        all_ncc = np.concatenate([
            ncc_scores.astype(np.float32),
            np.ones((len(new_points),), dtype=np.float32),
        ])
        all_tex = np.concatenate([
            local_tex.astype(np.float32),
            local_texture_scores(gray, new_points),
        ])
        all_quality = np.concatenate([matched_quality, new_quality]).astype(np.float32)
        sources = ["orb_match"] * len(matched_cur) + ["orb"] * len(new_points)

        used_cur_indices = np.concatenate([cur_indices[valid], add_indices]).astype(np.int64)
        self.points = all_points
        self.descriptors = descriptors[used_cur_indices].copy() if len(used_cur_indices) else None
        self.ids = all_ids.astype(np.int64)
        self.ages = all_ages.astype(np.int32)
        self.prev_image = gray.copy()

        tracks = TrackSet(
            ids=self.ids.copy(),
            prev_points=all_prev_points,
            points=self.points.copy(),
            ages=self.ages.copy(),
            fb_errors=all_fb,
            ncc_scores=all_ncc,
            local_texture=all_tex,
            qualities=all_quality,
            sources=sources,
        )
        return tracks, TrackerDiagnostics(
            added_features=len(new_points),
            dropped_features=max(0, prev_count - len(matched_ids)),
            tracked_before_filter=prev_count,
            tracked_after_filter=len(matched_ids),
            median_fb_error=_median(distances),
            median_ncc=_median(ncc_scores),
            median_quality=_median(all_quality),
        )


def _keypoints_to_points(keypoints: tuple[cv2.KeyPoint, ...] | list[cv2.KeyPoint]) -> np.ndarray:
    if not keypoints:
        return np.empty((0, 2), dtype=np.float32)
    return np.asarray([kp.pt for kp in keypoints], dtype=np.float32)


def _rank_keypoints_by_response(keypoints: tuple[cv2.KeyPoint, ...] | list[cv2.KeyPoint]) -> np.ndarray:
    if not keypoints:
        return np.empty((0,), dtype=np.int64)
    responses = np.asarray([kp.response for kp in keypoints], dtype=np.float32)
    return np.argsort(-responses)


def _new_track_quality(gray: np.ndarray, points: np.ndarray, image_quality: ImageQuality, q_min: float) -> np.ndarray:
    local_tex = local_texture_scores(gray, points)
    return np.clip(image_quality.global_score * (0.35 + 0.65 * local_tex), q_min, 1.0).astype(np.float32)


def _patch_ncc(prev: np.ndarray, cur: np.ndarray, prev_pts: np.ndarray, cur_pts: np.ndarray, radius: int) -> np.ndarray:
    scores = np.zeros((len(prev_pts),), dtype=np.float32)
    if prev is None:
        return scores
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
        scores[i] = 0.0 if denom <= 1e-6 else float(np.clip(np.sum(patch0 * patch1) / denom, -1.0, 1.0))
    return scores


def _median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))
