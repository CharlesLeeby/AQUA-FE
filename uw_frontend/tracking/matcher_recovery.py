from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from uw_frontend.matchers.base import BaseMatcher, MatchResult
from uw_frontend.quality.image_quality import CellQualityMap, ImageQuality, cell_quality_at_points, local_texture_scores
from uw_frontend.tracking.klt_tracker import _patch_ncc
from uw_frontend.tracking.track_state import TrackSet


@dataclass
class MatcherRecoveryConfig:
    lost_association_radius: float = 10.0
    min_current_distance: float = 8.0
    min_ncc: float = 0.45
    max_recovered: int = 120
    candidate_pool_factor: int = 8
    min_confidence: float = 0.0
    enable_geometry_filter: bool = True
    geometry_min_tracks: int = 40
    geometry_filter_mode: str = "any"
    geometry_strict_min_f_inlier_ratio: float = 0.70
    geometry_strict_min_h_inlier_ratio: float = 0.55
    geometry_strict_max_reference_epipolar_error: float = 1.5
    geometry_strict_max_reference_homography_error: float = 4.0
    geometry_quality_weight: float = 0.60
    max_epipolar_error: float = 2.5
    max_homography_error: float = 5.0
    coverage_rows: int = 4
    coverage_cols: int = 6
    target_cell_count: int = 10
    coverage_bonus: float = 0.65
    init_enable_grid_quota: bool = True
    init_max_per_cell: int = 4
    init_min_coverage_score: float = 0.0
    border: int = 8
    q_min: float = 0.05
    local_quality_weight: float = 0.0
    local_quality_min_score: float = 0.0


class PairwiseMatcherRecovery:
    """Recover recently lost KLT tracks from a pairwise learned matcher."""

    def __init__(self, matcher: BaseMatcher, config: MatcherRecoveryConfig | None = None) -> None:
        self.matcher = matcher
        self.config = config or MatcherRecoveryConfig()
        self._last_match_key: tuple[int, int] | None = None
        self._last_match_result: MatchResult | None = None

    def recover(
        self,
        prev: np.ndarray | None,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        lost_points: np.ndarray,
        lost_ids: np.ndarray,
        lost_ages: np.ndarray,
        exclude_ids: set[int] | None = None,
        cell_quality_map: CellQualityMap | None = None,
    ) -> TrackSet:
        if prev is None or len(lost_points) == 0:
            return TrackSet.empty()
        exclude_ids = exclude_ids or set()
        matches = self._match(prev, cur)
        if len(matches) == 0:
            return TrackSet.empty()
        return self._associate_matches(
            prev,
            cur,
            matches,
            image_quality,
            current_tracks,
            lost_points,
            lost_ids,
            lost_ages,
            exclude_ids,
            cell_quality_map,
        )

    def initialize_new_tracks(
        self,
        prev: np.ndarray | None,
        cur: np.ndarray,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        next_id: int,
        max_new: int,
        cell_quality_map: CellQualityMap | None = None,
    ) -> TrackSet:
        if prev is None or max_new <= 0:
            return TrackSet.empty()
        matches = self._match(prev, cur)
        if len(matches) == 0:
            return TrackSet.empty()
        confidences = matches.confidences.astype(np.float32) if len(matches.confidences) else np.ones((len(matches),), dtype=np.float32)
        order = np.argsort(-confidences)
        candidate_prev = []
        candidate_cur = []
        candidate_conf = []
        candidate_limit = max(max_new, max_new * self.config.candidate_pool_factor)
        for idx in order:
            conf = float(confidences[idx])
            if conf < self.config.min_confidence:
                continue
            prev_pt = matches.points0[idx].astype(np.float32)
            cur_pt = matches.points1[idx].astype(np.float32)
            if not _point_in_border(cur_pt, cur.shape, self.config.border):
                continue
            if _too_close(cur_pt, current_tracks.points, self.config.min_current_distance):
                continue
            candidate_prev.append(prev_pt)
            candidate_cur.append(cur_pt)
            candidate_conf.append(conf)
            if len(candidate_cur) >= candidate_limit:
                break
        if not candidate_cur:
            return TrackSet.empty()

        prev_arr = np.asarray(candidate_prev, dtype=np.float32)
        cur_arr = np.asarray(candidate_cur, dtype=np.float32)
        conf_arr = np.asarray(candidate_conf, dtype=np.float32)
        ncc = _patch_ncc(prev, cur, prev_arr, cur_arr, radius=5)
        valid = ncc >= self.config.min_ncc
        geometry_score = np.ones((len(prev_arr),), dtype=np.float32)
        if self.config.enable_geometry_filter:
            geometry_valid, geometry_score = _geometry_valid_mask_and_score(
                current_tracks,
                prev_arr,
                cur_arr,
                min_tracks=self.config.geometry_min_tracks,
                max_epipolar_error=self.config.max_epipolar_error,
                max_homography_error=self.config.max_homography_error,
                mode=self.config.geometry_filter_mode,
                strict_min_f_inlier_ratio=self.config.geometry_strict_min_f_inlier_ratio,
                strict_min_h_inlier_ratio=self.config.geometry_strict_min_h_inlier_ratio,
                strict_max_reference_epipolar_error=self.config.geometry_strict_max_reference_epipolar_error,
                strict_max_reference_homography_error=self.config.geometry_strict_max_reference_homography_error,
            )
            valid &= geometry_valid
        if not np.any(valid):
            return TrackSet.empty()

        prev_arr = prev_arr[valid]
        cur_arr = cur_arr[valid]
        conf_arr = conf_arr[valid]
        ncc = ncc[valid].astype(np.float32)
        geometry_score = geometry_score[valid].astype(np.float32)
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = _local_quality_scores(cell_quality_map, cur_arr, cur.shape)
        coverage_score = _coverage_scores(
            current_tracks.points,
            cur_arr,
            cur.shape,
            rows=self.config.coverage_rows,
            cols=self.config.coverage_cols,
            target_cell_count=self.config.target_cell_count,
        )
        coverage_valid = coverage_score >= self.config.init_min_coverage_score
        if not np.any(coverage_valid):
            return TrackSet.empty()
        prev_arr = prev_arr[coverage_valid]
        cur_arr = cur_arr[coverage_valid]
        conf_arr = conf_arr[coverage_valid]
        ncc = ncc[coverage_valid]
        local_tex = local_tex[coverage_valid]
        local_quality = local_quality[coverage_valid]
        coverage_score = coverage_score[coverage_valid]
        geometry_score = geometry_score[coverage_valid]

        if self.config.local_quality_min_score > 0.0:
            quality_valid = local_quality >= float(self.config.local_quality_min_score)
            if not np.any(quality_valid):
                return TrackSet.empty()
            prev_arr = prev_arr[quality_valid]
            cur_arr = cur_arr[quality_valid]
            conf_arr = conf_arr[quality_valid]
            ncc = ncc[quality_valid]
            local_tex = local_tex[quality_valid]
            local_quality = local_quality[quality_valid]
            coverage_score = coverage_score[quality_valid]
            geometry_score = geometry_score[quality_valid]

        match_score = np.clip(conf_arr, 0.0, 1.0)
        geometry_weight = np.clip(float(self.config.geometry_quality_weight), 0.0, 1.0)
        geometry_quality = (1.0 - geometry_weight) + geometry_weight * np.clip(geometry_score, 0.0, 1.0)
        quality_base = _quality_base(image_quality, local_quality, self.config.local_quality_weight)
        quality = np.clip(
            quality_base
            * (0.20 + 0.80 * local_tex)
            * (0.25 + 0.75 * match_score)
            * (0.30 + 0.70 * ncc)
            * (0.65 + 0.35 * coverage_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        quality = np.clip(
            quality * geometry_quality,
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        selection_score = quality * (1.0 + self.config.coverage_bonus * coverage_score)
        if self.config.init_enable_grid_quota:
            selected = _select_spatially_diverse_with_grid_quota(
                existing_points=current_tracks.points,
                points=cur_arr,
                scores=selection_score,
                image_shape=cur.shape,
                max_count=max_new,
                min_distance=self.config.min_current_distance,
                rows=self.config.coverage_rows,
                cols=self.config.coverage_cols,
                target_cell_count=self.config.target_cell_count,
                max_per_cell=self.config.init_max_per_cell,
            )
        else:
            selected = _select_spatially_diverse(
                cur_arr,
                selection_score,
                max_count=max_new,
                min_distance=self.config.min_current_distance,
            )
        if len(selected) == 0:
            return TrackSet.empty()

        prev_arr = prev_arr[selected]
        cur_arr = cur_arr[selected]
        ncc = ncc[selected]
        local_tex = local_tex[selected]
        local_quality = local_quality[selected]
        quality = quality[selected]
        conf_arr = conf_arr[selected]
        ids = np.arange(next_id, next_id + len(selected), dtype=np.int64)
        ages = np.full((len(selected),), 2, dtype=np.int32)
        source = f"{matches.method}_init"
        return TrackSet(
            ids=ids,
            prev_points=prev_arr,
            points=cur_arr,
            ages=ages,
            fb_errors=(1.0 - np.clip(conf_arr, 0.0, 1.0)).astype(np.float32),
            ncc_scores=ncc.astype(np.float32),
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=[source] * len(ids),
        )

    def _match(self, prev: np.ndarray, cur: np.ndarray) -> MatchResult:
        key = (id(prev), id(cur))
        if self._last_match_key == key and self._last_match_result is not None:
            return self._last_match_result
        result = self.matcher.match(prev, cur)
        self._last_match_key = key
        self._last_match_result = result
        return result

    def _associate_matches(
        self,
        prev: np.ndarray,
        cur: np.ndarray,
        matches: MatchResult,
        image_quality: ImageQuality,
        current_tracks: TrackSet,
        lost_points: np.ndarray,
        lost_ids: np.ndarray,
        lost_ages: np.ndarray,
        exclude_ids: set[int],
        cell_quality_map: CellQualityMap | None = None,
    ) -> TrackSet:
        current_points = current_tracks.points.copy()
        used_lost: set[int] = set()
        recovered_prev = []
        recovered_cur = []
        recovered_ids = []
        recovered_ages = []
        confidences = []
        association_distances = []
        candidate_limit = max(self.config.max_recovered, self.config.max_recovered * self.config.candidate_pool_factor)

        order = np.argsort(-matches.confidences) if len(matches.confidences) else np.arange(len(matches))
        for idx in order:
            confidence = float(matches.confidences[idx]) if len(matches.confidences) else 1.0
            if confidence < self.config.min_confidence:
                continue
            prev_pt = matches.points0[idx].astype(np.float32)
            cur_pt = matches.points1[idx].astype(np.float32)
            if not _point_in_border(cur_pt, cur.shape, self.config.border):
                continue
            lost_idx = _nearest_index(lost_points, prev_pt)
            if lost_idx is None or lost_idx in used_lost:
                continue
            track_id = int(lost_ids[lost_idx])
            if track_id in exclude_ids:
                continue
            association_distance = float(np.linalg.norm(lost_points[lost_idx] - prev_pt))
            if association_distance > self.config.lost_association_radius:
                continue
            if _too_close(cur_pt, current_points, self.config.min_current_distance):
                continue
            recovered_prev.append(lost_points[lost_idx])
            recovered_cur.append(cur_pt)
            recovered_ids.append(lost_ids[lost_idx])
            recovered_ages.append(lost_ages[lost_idx] + 1)
            confidences.append(confidence)
            association_distances.append(association_distance)
            used_lost.add(lost_idx)
            if len(recovered_ids) >= candidate_limit:
                break

        if not recovered_ids:
            return TrackSet.empty()

        prev_arr = np.asarray(recovered_prev, dtype=np.float32)
        cur_arr = np.asarray(recovered_cur, dtype=np.float32)
        ncc = _patch_ncc(prev, cur, prev_arr, cur_arr, radius=5)
        valid = ncc >= self.config.min_ncc
        geometry_score = np.ones((len(prev_arr),), dtype=np.float32)
        if self.config.enable_geometry_filter:
            geometry_valid, geometry_score = _geometry_valid_mask_and_score(
                current_tracks,
                prev_arr,
                cur_arr,
                min_tracks=self.config.geometry_min_tracks,
                max_epipolar_error=self.config.max_epipolar_error,
                max_homography_error=self.config.max_homography_error,
                mode=self.config.geometry_filter_mode,
                strict_min_f_inlier_ratio=self.config.geometry_strict_min_f_inlier_ratio,
                strict_min_h_inlier_ratio=self.config.geometry_strict_min_h_inlier_ratio,
                strict_max_reference_epipolar_error=self.config.geometry_strict_max_reference_epipolar_error,
                strict_max_reference_homography_error=self.config.geometry_strict_max_reference_homography_error,
            )
            valid &= geometry_valid
        if not np.any(valid):
            return TrackSet.empty()

        prev_arr = prev_arr[valid]
        cur_arr = cur_arr[valid]
        ids_arr = np.asarray(recovered_ids, dtype=np.int64)[valid]
        ages_arr = np.asarray(recovered_ages, dtype=np.int32)[valid]
        confidence_arr = np.asarray(confidences, dtype=np.float32)[valid]
        association_arr = np.asarray(association_distances, dtype=np.float32)[valid]
        ncc = ncc[valid].astype(np.float32)
        geometry_score = geometry_score[valid].astype(np.float32)
        local_tex = local_texture_scores(cur, cur_arr)
        local_quality = _local_quality_scores(cell_quality_map, cur_arr, cur.shape)
        age_score = np.clip(ages_arr.astype(np.float32) / 20.0, 0.0, 1.0)
        assoc_score = np.exp(-association_arr / max(1e-3, self.config.lost_association_radius))
        coverage_score = _coverage_scores(
            current_tracks.points,
            cur_arr,
            cur.shape,
            rows=self.config.coverage_rows,
            cols=self.config.coverage_cols,
            target_cell_count=self.config.target_cell_count,
        )
        if self.config.local_quality_min_score > 0.0:
            quality_valid = local_quality >= float(self.config.local_quality_min_score)
            if not np.any(quality_valid):
                return TrackSet.empty()
            prev_arr = prev_arr[quality_valid]
            cur_arr = cur_arr[quality_valid]
            ids_arr = ids_arr[quality_valid]
            ages_arr = ages_arr[quality_valid]
            confidence_arr = confidence_arr[quality_valid]
            association_arr = association_arr[quality_valid]
            ncc = ncc[quality_valid]
            geometry_score = geometry_score[quality_valid]
            local_tex = local_tex[quality_valid]
            local_quality = local_quality[quality_valid]
            age_score = age_score[quality_valid]
            assoc_score = assoc_score[quality_valid]
            coverage_score = coverage_score[quality_valid]

        geometry_weight = np.clip(float(self.config.geometry_quality_weight), 0.0, 1.0)
        geometry_quality = (1.0 - geometry_weight) + geometry_weight * np.clip(geometry_score, 0.0, 1.0)
        quality_base = _quality_base(image_quality, local_quality, self.config.local_quality_weight)
        quality = np.clip(
            quality_base
            * (0.20 + 0.80 * local_tex)
            * (0.25 + 0.75 * np.clip(confidence_arr, 0.0, 1.0))
            * (0.30 + 0.70 * ncc)
            * (0.40 + 0.60 * assoc_score)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        quality = np.clip(
            quality * geometry_quality,
            self.config.q_min,
            1.0,
        ).astype(np.float32)
        selection_score = quality * (1.0 + self.config.coverage_bonus * coverage_score)
        selected = _select_spatially_diverse(
            cur_arr,
            selection_score,
            max_count=self.config.max_recovered,
            min_distance=self.config.min_current_distance,
        )
        if len(selected) == 0:
            return TrackSet.empty()

        prev_arr = prev_arr[selected]
        cur_arr = cur_arr[selected]
        ids_arr = ids_arr[selected]
        ages_arr = ages_arr[selected]
        association_arr = association_arr[selected]
        ncc = ncc[selected]
        local_tex = local_tex[selected]
        local_quality = local_quality[selected]
        quality = quality[selected]

        source = f"{matches.method}_recovery"
        return TrackSet(
            ids=ids_arr,
            prev_points=prev_arr,
            points=cur_arr,
            ages=ages_arr,
            fb_errors=association_arr.astype(np.float32),
            ncc_scores=ncc,
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=[source] * len(ids_arr),
        )


def _nearest_index(points: np.ndarray, query: np.ndarray) -> int | None:
    if len(points) == 0:
        return None
    distances = np.linalg.norm(points - query.reshape(1, 2), axis=1)
    return int(np.argmin(distances))


def _too_close(point: np.ndarray, points: np.ndarray, threshold: float) -> bool:
    if len(points) == 0:
        return False
    return bool(np.any(np.linalg.norm(points - point.reshape(1, 2), axis=1) < threshold))


def _point_in_border(point: np.ndarray, shape: tuple[int, int], border: int) -> bool:
    h, w = shape[:2]
    x, y = float(point[0]), float(point[1])
    return border <= x < w - border and border <= y < h - border


def _geometry_valid_mask(
    current_tracks: TrackSet,
    candidate_prev: np.ndarray,
    candidate_cur: np.ndarray,
    min_tracks: int,
    max_epipolar_error: float,
    max_homography_error: float,
) -> np.ndarray:
    valid, _ = _geometry_valid_mask_and_score(
        current_tracks,
        candidate_prev,
        candidate_cur,
        min_tracks=min_tracks,
        max_epipolar_error=max_epipolar_error,
        max_homography_error=max_homography_error,
        mode="any",
        strict_min_f_inlier_ratio=0.70,
        strict_min_h_inlier_ratio=0.55,
        strict_max_reference_epipolar_error=1.5,
        strict_max_reference_homography_error=4.0,
    )
    return valid


def _geometry_valid_mask_and_score(
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
) -> tuple[np.ndarray, np.ndarray]:
    if len(candidate_prev) == 0:
        return np.empty((0,), dtype=bool), np.empty((0,), dtype=np.float32)
    valid = np.ones((len(candidate_prev),), dtype=bool)
    score = np.ones((len(candidate_prev),), dtype=np.float32)
    motion_mask = current_tracks.ages > 1 if len(current_tracks) else np.empty((0,), dtype=bool)
    if int(np.sum(motion_mask)) < min_tracks:
        return valid, score

    ref_prev = current_tracks.prev_points[motion_mask].astype(np.float32)
    ref_cur = current_tracks.points[motion_mask].astype(np.float32)
    if len(ref_prev) < 8:
        return valid, score

    f_mat, f_mask = cv2.findFundamentalMat(ref_prev, ref_cur, cv2.FM_RANSAC, 1.0, 0.99)
    h_mat, h_mask = cv2.findHomography(ref_prev, ref_cur, cv2.RANSAC, 3.0)
    has_f = f_mat is not None and np.asarray(f_mat).shape == (3, 3)
    has_h = h_mat is not None and np.asarray(h_mat).shape == (3, 3)
    if not has_f and not has_h:
        return valid, score

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
            return f_valid, f_score.astype(np.float32)
        if h_valid is not None and h_score is not None:
            return h_valid, h_score.astype(np.float32)
    if mode in {"homography", "planar", "h"}:
        if h_valid is not None and h_score is not None:
            return h_valid, h_score.astype(np.float32)
        if f_valid is not None and f_score is not None:
            return f_valid, f_score.astype(np.float32)
    if mode == "all":
        masks = [item for item in (f_valid, h_valid) if item is not None]
        valid = np.logical_and.reduce(masks) if masks else valid
        scores = [item for item in (f_score, h_score) if item is not None]
        score = np.minimum.reduce(scores).astype(np.float32) if scores else score
        return valid, score

    if mode in {"adaptive", "adaptive_strict", "strict_adaptive"}:
        f_ratio = _mask_ratio(f_mask, len(ref_prev)) if has_f else 0.0
        h_ratio = _mask_ratio(h_mask, len(ref_prev)) if has_h else 0.0
        f_ref_error = _median_epipolar_error(f_mat, ref_prev, ref_cur) if has_f else float("nan")
        h_ref_error = _median_homography_error(h_mat, ref_prev, ref_cur) if has_h else float("nan")
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
            valid = np.logical_and.reduce(required_masks)
            score = np.minimum.reduce(required_scores).astype(np.float32)
            return valid, score

    model_masks = [item for item in (f_valid, h_valid) if item is not None]
    model_scores = [item for item in (f_score, h_score) if item is not None]
    valid = np.logical_or.reduce(model_masks) if model_masks else valid
    score = np.maximum.reduce(model_scores).astype(np.float32) if model_scores else score
    return valid, score


def _mask_ratio(mask: np.ndarray | None, count: int) -> float:
    if mask is None or count <= 0:
        return 0.0
    return float(np.mean(np.asarray(mask).reshape(-1).astype(bool)))


def _finite_leq(value: float, threshold: float) -> bool:
    return bool(value == value and value <= threshold)


def _median_epipolar_error(f_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> float:
    if f_mat is None or len(pts0) == 0:
        return float("nan")
    return float(np.median(_epipolar_errors(f_mat, pts0, pts1)))


def _median_homography_error(h_mat: np.ndarray, pts0: np.ndarray, pts1: np.ndarray) -> float:
    if h_mat is None or len(pts0) == 0:
        return float("nan")
    return float(np.median(_homography_errors(h_mat, pts0, pts1)))


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


def _coverage_scores(
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
        existing_cells = _cell_indices(existing_points, h, w, rows, cols)
        for row, col in existing_cells:
            counts[row, col] += 1
    candidate_cells = _cell_indices(candidate_points, h, w, rows, cols)
    scores = []
    for row, col in candidate_cells:
        occupancy = counts[row, col]
        scores.append(np.clip((target_cell_count - occupancy) / max(1.0, float(target_cell_count)), 0.0, 1.0))
    return np.asarray(scores, dtype=np.float32)


def _local_quality_scores(
    cell_quality_map: CellQualityMap | None,
    points: np.ndarray,
    image_shape: tuple[int, int],
) -> np.ndarray:
    if cell_quality_map is None:
        return np.ones((len(points),), dtype=np.float32)
    return cell_quality_at_points(cell_quality_map, points, image_shape, "quality")


def _quality_base(
    image_quality: ImageQuality,
    local_quality: np.ndarray,
    local_weight: float,
) -> np.ndarray:
    weight = float(np.clip(local_weight, 0.0, 1.0))
    global_score = float(np.clip(image_quality.global_score, 0.0, 1.0))
    if weight <= 0.0:
        return np.full((len(local_quality),), global_score, dtype=np.float32)
    return np.clip(
        (1.0 - weight) * global_score + weight * np.clip(local_quality, 0.0, 1.0),
        0.0,
        1.0,
    ).astype(np.float32)


def _cell_indices(points: np.ndarray, h: int, w: int, rows: int, cols: int) -> np.ndarray:
    pts = points.reshape(-1, 2)
    xs = np.clip((pts[:, 0] / max(1, w) * cols).astype(np.int32), 0, cols - 1)
    ys = np.clip((pts[:, 1] / max(1, h) * rows).astype(np.int32), 0, rows - 1)
    return np.stack([ys, xs], axis=1)


def _select_spatially_diverse(
    points: np.ndarray,
    scores: np.ndarray,
    max_count: int,
    min_distance: float,
) -> np.ndarray:
    if len(points) == 0 or max_count <= 0:
        return np.empty((0,), dtype=np.int64)
    selected: list[int] = []
    selected_points: list[np.ndarray] = []
    order = np.argsort(-scores)
    for idx in order:
        point = points[idx]
        if selected_points:
            prev = np.vstack(selected_points)
            if _too_close(point, prev, min_distance):
                continue
        selected.append(int(idx))
        selected_points.append(point.reshape(1, 2))
        if len(selected) >= max_count:
            break
    return np.asarray(selected, dtype=np.int64)


def _select_spatially_diverse_with_grid_quota(
    existing_points: np.ndarray,
    points: np.ndarray,
    scores: np.ndarray,
    image_shape: tuple[int, int],
    max_count: int,
    min_distance: float,
    rows: int,
    cols: int,
    target_cell_count: int,
    max_per_cell: int,
) -> np.ndarray:
    if len(points) == 0 or max_count <= 0:
        return np.empty((0,), dtype=np.int64)
    h, w = image_shape[:2]
    existing_counts = np.zeros((rows, cols), dtype=np.int32)
    if len(existing_points):
        for row, col in _cell_indices(existing_points, h, w, rows, cols):
            existing_counts[row, col] += 1
    added_counts = np.zeros((rows, cols), dtype=np.int32)
    candidate_cells = _cell_indices(points, h, w, rows, cols)
    selected: list[int] = []
    selected_points: list[np.ndarray] = []
    order = sorted(
        range(len(points)),
        key=lambda idx: (
            existing_counts[candidate_cells[idx, 0], candidate_cells[idx, 1]],
            -float(scores[idx]),
        ),
    )
    for idx in order:
        row, col = candidate_cells[idx]
        if existing_counts[row, col] >= target_cell_count:
            continue
        if added_counts[row, col] >= max_per_cell:
            continue
        point = points[idx]
        if selected_points:
            prev = np.vstack(selected_points)
            if _too_close(point, prev, min_distance):
                continue
        selected.append(int(idx))
        selected_points.append(point.reshape(1, 2))
        added_counts[row, col] += 1
        existing_counts[row, col] += 1
        if len(selected) >= max_count:
            break
    if len(selected) < max_count:
        # Fill any remaining budget with the ordinary spatially diverse rule.
        already = set(selected)
        selected_points_arr = np.vstack(selected_points) if selected_points else np.empty((0, 2), dtype=np.float32)
        for idx in np.argsort(-scores):
            idx = int(idx)
            if idx in already:
                continue
            point = points[idx]
            if len(selected_points_arr) and _too_close(point, selected_points_arr, min_distance):
                continue
            selected.append(idx)
            already.add(idx)
            selected_points_arr = (
                np.vstack([selected_points_arr, point.reshape(1, 2)])
                if len(selected_points_arr)
                else point.reshape(1, 2)
            )
            if len(selected) >= max_count:
                break
    return np.asarray(selected, dtype=np.int64)
