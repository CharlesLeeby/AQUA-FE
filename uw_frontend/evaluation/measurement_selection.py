from __future__ import annotations

from dataclasses import dataclass, replace

import cv2
import numpy as np

from uw_frontend.tracking.track_state import TrackSet


@dataclass
class MeasurementSelectionConfig:
    enabled: bool = False
    min_age: int = 2
    min_quality: float = 0.05
    min_ncc: float = 0.35
    max_fb_error: float = 8.0
    min_model_tracks: int = 24
    max_features: int = 350
    min_features: int = 160
    model: str = "fundamental"
    f_ransac_threshold: float = 1.0
    h_ransac_threshold: float = 3.0
    f_residual_scale: float = 1.0
    h_residual_scale: float = 3.0
    residual_weight: float = 0.75
    residual_refine_enabled: bool = False
    residual_refine_keep_ratio: float = 0.85
    residual_refine_min_features: int = 80
    residual_refine_min_score: float = 0.0
    adaptive_min_tracks: int = 40
    adaptive_min_keep_ratio: float = 0.30
    adaptive_epipolar_weight: float = 0.45
    adaptive_homography_weight: float = 0.20
    adaptive_inlier_weight: float = 0.25
    adaptive_count_weight: float = 0.10
    adaptive_planar_h_ratio: float = 0.80
    adaptive_planar_score_ratio: float = 0.97
    adaptive_low_f_ratio: float = 0.90
    adaptive_strong_f_ratio: float = 0.95
    adaptive_f_score_margin: float = 0.95
    adaptive_f_only_ransac_threshold: float = 1.0
    adaptive_both_f_ransac_threshold: float = 0.75
    adaptive_both_h_ransac_threshold: float = 2.0
    grid_rows: int = 4
    grid_cols: int = 6
    max_per_cell: int = 18
    target_cell_count: int = 10
    coverage_weight: float = 0.60
    age_score_scale: float = 20.0
    fallback_to_quality: bool = True
    information_score_enabled: bool = False
    information_quality_power: float = 0.80
    information_age_power: float = 0.85
    information_ncc_power: float = 0.70
    information_fb_power: float = 0.65
    information_source_weight: float = 0.20
    information_spread_weight: float = 0.12
    information_cell_weight: float = 0.12
    information_post_validate_enabled: bool = False
    validation_min_pairs: int = 24
    validation_max_geometry_score_drop: float = 0.01
    validation_max_epi_error_ratio: float = 1.02
    validation_max_epi_error_abs: float = 0.01
    validation_max_inlier_drop: float = 0.02
    validation_min_count_ratio: float = 0.55
    information_refill_enabled: bool = False
    information_refill_target_count_ratio: float = 0.85
    information_refill_max_trials: int = 4
    information_refill_coverage_weight: float = 0.35
    coverage_refill_enabled: bool = False
    coverage_refill_target_grid_coverage: float = 0.65
    coverage_refill_max_extra_fraction: float = 0.35
    coverage_refill_max_per_cell: int = 8
    coverage_refill_target_cell_count: int = 2
    coverage_refill_weight: float = 0.70
    coverage_refill_max_trials: int = 5
    ransac_seed: int = -1


def select_backend_measurements(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
    geometry_mode: str = "unknown",
) -> TrackSet:
    if (
        config.enabled
        and config.information_score_enabled
        and config.information_post_validate_enabled
        and len(tracks) > 0
    ):
        baseline = _select_backend_measurements_once(
            tracks,
            image_shape,
            replace(
                config,
                information_score_enabled=False,
                information_post_validate_enabled=False,
            ),
            geometry_mode=geometry_mode,
        )
        proposed = _select_backend_measurements_once(
            tracks,
            image_shape,
            replace(config, information_post_validate_enabled=False),
            geometry_mode=geometry_mode,
        )
        if config.information_refill_enabled:
            proposed = _refill_information_selection(
                baseline,
                proposed,
                image_shape,
                config,
            )
        if config.coverage_refill_enabled:
            proposed = _coverage_refill_selection(
                baseline,
                proposed,
                image_shape,
                config,
            )
        if _accept_validated_information_selection(baseline, proposed, config):
            return proposed
        return baseline
    return _select_backend_measurements_once(tracks, image_shape, config, geometry_mode=geometry_mode)


def _select_backend_measurements_once(
    tracks: TrackSet,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
    geometry_mode: str = "unknown",
) -> TrackSet:
    if not config.enabled or len(tracks) == 0:
        return tracks

    eligible = _eligible_mask(tracks, config)
    if int(np.sum(eligible)) < max(8, int(config.min_model_tracks)):
        relaxed = (tracks.ages >= max(1, int(config.min_age))).astype(bool)
        relaxed &= np.isfinite(tracks.prev_points).all(axis=1)
        relaxed &= np.isfinite(tracks.points).all(axis=1)
        eligible = relaxed
    if int(np.sum(eligible)) < 8:
        return tracks

    eligible_indices = np.where(eligible)[0]
    geom_keep, geom_scores = _geometry_keep_mask_and_score(
        tracks.prev_points[eligible],
        tracks.points[eligible],
        config,
        geometry_mode=geometry_mode,
    )
    if len(geom_keep) != len(eligible_indices):
        return tracks

    candidate_indices = eligible_indices[geom_keep]
    candidate_geom_scores = geom_scores[geom_keep].astype(np.float32)
    if len(candidate_geom_scores) != len(candidate_indices):
        candidate_geom_scores = np.ones((len(candidate_indices),), dtype=np.float32)
    rank_scores = _selection_scores(
        tracks,
        candidate_indices,
        config,
        image_shape=image_shape,
    )
    residual_weight = np.clip(float(config.residual_weight), 0.0, 1.0)
    rank_scores = rank_scores * (
        (1.0 - residual_weight) + residual_weight * np.clip(candidate_geom_scores, 0.0, 1.0)
    )
    candidate_indices, candidate_geom_scores, rank_scores = _residual_refine_arrays(
        candidate_indices,
        candidate_geom_scores,
        rank_scores if config.information_score_enabled else candidate_geom_scores,
        config,
    )
    if len(candidate_indices) < max(8, int(config.min_features)) and config.fallback_to_quality:
        candidate_indices = _fill_with_quality(
            candidate_indices,
            eligible_indices,
            tracks,
            max_count=max(8, int(config.min_features)),
        )
        candidate_geom_scores = np.ones((len(candidate_indices),), dtype=np.float32)
        rank_scores = _selection_scores(
            tracks,
            candidate_indices,
            config,
            image_shape=image_shape,
        )
    if len(candidate_indices) == 0:
        return tracks

    scores = _selection_scores(
        tracks,
        candidate_indices,
        config,
        image_shape=image_shape,
    )
    scores = scores * ((1.0 - residual_weight) + residual_weight * np.clip(candidate_geom_scores, 0.0, 1.0))
    coverage_scores = _coverage_scores(
        tracks.points,
        tracks.points[candidate_indices],
        image_shape,
        max(1, int(config.grid_rows)),
        max(1, int(config.grid_cols)),
        max(1, int(config.target_cell_count)),
    )
    coverage_weight = np.clip(float(config.coverage_weight), 0.0, 1.0)
    scores = scores * ((1.0 - coverage_weight) + coverage_weight * coverage_scores)
    selected = _select_grid_balanced(
        indices=candidate_indices,
        points=tracks.points[candidate_indices],
        scores=scores,
        image_shape=image_shape,
        max_count=max(1, int(config.max_features)),
        rows=max(1, int(config.grid_rows)),
        cols=max(1, int(config.grid_cols)),
        max_per_cell=max(1, int(config.max_per_cell)),
    )
    selected = _residual_refine_selected(
        selected,
        candidate_indices,
        candidate_geom_scores,
        config,
    )
    if len(selected) < max(8, int(config.min_features)) and config.fallback_to_quality:
        selected = _fill_with_quality(
            selected,
            candidate_indices,
            tracks,
            max_count=min(len(candidate_indices), max(8, int(config.min_features))),
        )
    if len(selected) == 0:
        return tracks
    return _subset_tracks(tracks, selected)


def _accept_validated_information_selection(
    baseline: TrackSet,
    proposed: TrackSet,
    config: MeasurementSelectionConfig,
) -> bool:
    if len(proposed) == 0:
        return False
    if len(baseline) < 8:
        return True
    min_count_ratio = float(np.clip(config.validation_min_count_ratio, 0.0, 1.0))
    if len(proposed) < max(8, int(np.ceil(len(baseline) * min_count_ratio))):
        return False

    base_stats = _selection_validation_stats(baseline, config)
    prop_stats = _selection_validation_stats(proposed, config)
    min_pairs = max(8, int(config.validation_min_pairs))
    if prop_stats["pairs"] < min_pairs and base_stats["pairs"] >= min_pairs:
        return False
    if base_stats["pairs"] < min_pairs:
        return prop_stats["continuity"] >= base_stats["continuity"]

    epi_ratio = float(config.validation_max_epi_error_ratio)
    epi_abs = float(config.validation_max_epi_error_abs)
    if _finite(base_stats["epi"]) and _finite(prop_stats["epi"]):
        max_epi = base_stats["epi"] * max(1.0, epi_ratio) + max(0.0, epi_abs)
        if prop_stats["epi"] > max_epi:
            return False
    max_inlier_drop = max(0.0, float(config.validation_max_inlier_drop))
    if prop_stats["f_ratio"] + max_inlier_drop < base_stats["f_ratio"]:
        return False
    if prop_stats["h_ratio"] + max_inlier_drop < base_stats["h_ratio"]:
        return False

    max_score_drop = max(0.0, float(config.validation_max_geometry_score_drop))
    if prop_stats["geometry"] + max_score_drop < base_stats["geometry"]:
        return False
    return True


def _refill_information_selection(
    baseline: TrackSet,
    proposed: TrackSet,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
) -> TrackSet:
    if len(baseline) <= len(proposed) or len(proposed) == 0:
        return proposed
    proposed_ids = set(int(track_id) for track_id in proposed.ids)
    refill_indices = np.asarray(
        [idx for idx, track_id in enumerate(baseline.ids) if int(track_id) not in proposed_ids],
        dtype=np.int64,
    )
    if len(refill_indices) == 0:
        return proposed

    target_ratio = float(np.clip(config.information_refill_target_count_ratio, 0.0, 1.0))
    target_count = min(len(baseline), max(len(proposed), int(np.ceil(len(baseline) * target_ratio))))
    needed = target_count - len(proposed)
    if needed <= 0:
        return proposed

    scores = _refill_scores(
        baseline,
        refill_indices,
        proposed.points,
        image_shape,
        config,
    )
    order = refill_indices[np.argsort(-scores)]
    max_trials = max(1, int(config.information_refill_max_trials))
    trial_counts = np.unique(
        np.linspace(max(1, min(len(order), needed)), 1, num=max_trials, dtype=np.int32)
    )[::-1]
    best = proposed
    for trial_count in trial_counts:
        candidate = _append_track_subset(proposed, baseline, order[: int(trial_count)])
        if _accept_validated_information_selection(baseline, candidate, config):
            return candidate
        if len(candidate) > len(best) and _selection_validation_stats(candidate, config)["geometry"] >= (
            _selection_validation_stats(best, config)["geometry"] - max(0.0, float(config.validation_max_geometry_score_drop))
        ):
            best = candidate
    return best


def _coverage_refill_selection(
    baseline: TrackSet,
    proposed: TrackSet,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
) -> TrackSet:
    if len(baseline) <= len(proposed) or len(proposed) == 0:
        return proposed
    rows = max(1, int(config.grid_rows))
    cols = max(1, int(config.grid_cols))
    base_coverage = _grid_coverage_for_points(baseline.points, image_shape, rows, cols)
    proposed_coverage = _grid_coverage_for_points(proposed.points, image_shape, rows, cols)
    target_coverage = min(
        base_coverage,
        max(proposed_coverage, float(config.coverage_refill_target_grid_coverage)),
    )
    if proposed_coverage >= target_coverage:
        return proposed

    proposed_ids = set(int(track_id) for track_id in proposed.ids)
    refill_indices = np.asarray(
        [idx for idx, track_id in enumerate(baseline.ids) if int(track_id) not in proposed_ids],
        dtype=np.int64,
    )
    if len(refill_indices) == 0:
        return proposed

    max_features = max(1, int(config.max_features))
    max_extra_by_count = max(1, int(np.ceil(len(proposed) * max(0.0, float(config.coverage_refill_max_extra_fraction)))))
    max_extra = min(len(refill_indices), max(0, max_features - len(proposed)), max_extra_by_count)
    if max_extra <= 0:
        return proposed

    order = _coverage_refill_order(
        baseline,
        proposed,
        refill_indices,
        image_shape,
        config,
    )
    if len(order) == 0:
        return proposed
    extras = _coverage_refill_greedy_indices(
        baseline,
        proposed,
        order,
        image_shape,
        config,
        max_extra=max_extra,
        target_coverage=target_coverage,
    )
    if len(extras) == 0:
        return proposed

    trial_counts = np.unique(
        np.linspace(len(extras), 1, num=max(1, int(config.coverage_refill_max_trials)), dtype=np.int32)
    )[::-1]
    best = proposed
    best_coverage = proposed_coverage
    for trial_count in trial_counts:
        candidate = _append_track_subset(proposed, baseline, extras[: int(trial_count)])
        if not _accept_validated_information_selection(baseline, candidate, config):
            continue
        candidate_coverage = _grid_coverage_for_points(candidate.points, image_shape, rows, cols)
        if candidate_coverage >= target_coverage:
            return candidate
        if candidate_coverage > best_coverage or (
            abs(candidate_coverage - best_coverage) <= 1e-9 and len(candidate) > len(best)
        ):
            best = candidate
            best_coverage = candidate_coverage
    return best


def _coverage_refill_order(
    baseline: TrackSet,
    proposed: TrackSet,
    indices: np.ndarray,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
) -> np.ndarray:
    scores = _refill_scores(
        baseline,
        indices,
        proposed.points,
        image_shape,
        config,
    )
    if len(indices) == 0:
        return indices
    h, w = image_shape[:2]
    rows = max(1, int(config.grid_rows))
    cols = max(1, int(config.grid_cols))
    target_cell_count = max(1, int(config.coverage_refill_target_cell_count))
    counts = np.zeros((rows, cols), dtype=np.int32)
    if len(proposed.points):
        for row, col in _cell_indices(proposed.points, h, w, rows, cols):
            counts[row, col] += 1
    coverage_scores = []
    for row, col in _cell_indices(baseline.points[indices], h, w, rows, cols):
        if counts[row, col] <= 0:
            coverage_scores.append(1.0)
        else:
            shortage = np.clip(
                (target_cell_count - counts[row, col]) / float(target_cell_count),
                0.0,
                1.0,
            )
            coverage_scores.append(0.25 + 0.75 * shortage)
    coverage_scores = np.asarray(coverage_scores, dtype=np.float32)
    weight = np.clip(float(config.coverage_refill_weight), 0.0, 1.0)
    scores = scores * ((1.0 - weight) + weight * coverage_scores)
    return indices[np.argsort(-scores)]


def _coverage_refill_greedy_indices(
    baseline: TrackSet,
    proposed: TrackSet,
    ordered_indices: np.ndarray,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
    max_extra: int,
    target_coverage: float,
) -> np.ndarray:
    h, w = image_shape[:2]
    rows = max(1, int(config.grid_rows))
    cols = max(1, int(config.grid_cols))
    max_per_cell = max(1, int(config.coverage_refill_max_per_cell))
    counts = np.zeros((rows, cols), dtype=np.int32)
    if len(proposed.points):
        for row, col in _cell_indices(proposed.points, h, w, rows, cols):
            counts[row, col] += 1
    selected: list[int] = []
    for index in ordered_indices:
        row, col = _cell_indices(baseline.points[[int(index)]], h, w, rows, cols)[0]
        if counts[row, col] >= max_per_cell:
            continue
        selected.append(int(index))
        counts[row, col] += 1
        if len(selected) >= max_extra:
            break
        occupied = int(np.sum(counts > 0))
        if occupied / float(rows * cols) >= target_coverage and len(selected) >= max(1, rows):
            break
    return np.asarray(selected, dtype=np.int64)


def _grid_coverage_for_points(
    points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
) -> float:
    if len(points) == 0:
        return 0.0
    h, w = image_shape[:2]
    counts = np.zeros((rows, cols), dtype=np.int32)
    for row, col in _cell_indices(points, h, w, rows, cols):
        counts[row, col] += 1
    return float(np.sum(counts > 0) / float(rows * cols))


def _refill_scores(
    baseline: TrackSet,
    indices: np.ndarray,
    proposed_points: np.ndarray,
    image_shape: tuple[int, int],
    config: MeasurementSelectionConfig,
) -> np.ndarray:
    scores = _selection_scores(
        baseline,
        indices,
        replace(config, information_score_enabled=False),
        image_shape=image_shape,
    )
    if len(indices) == 0:
        return scores
    h, w = image_shape[:2]
    rows = max(1, int(config.grid_rows))
    cols = max(1, int(config.grid_cols))
    proposed_counts = np.zeros((rows, cols), dtype=np.int32)
    if len(proposed_points):
        for row, col in _cell_indices(proposed_points, h, w, rows, cols):
            proposed_counts[row, col] += 1
    candidate_cells = _cell_indices(baseline.points[indices], h, w, rows, cols)
    target_per_cell = max(1, int(config.target_cell_count))
    coverage_scores = []
    for row, col in candidate_cells:
        shortage = np.clip((target_per_cell - proposed_counts[row, col]) / float(target_per_cell), 0.0, 1.0)
        coverage_scores.append(0.35 + 0.65 * shortage)
    coverage = np.asarray(coverage_scores, dtype=np.float32)
    weight = np.clip(float(config.information_refill_coverage_weight), 0.0, 1.0)
    return (scores * ((1.0 - weight) + weight * coverage)).astype(np.float32)


def _selection_validation_stats(tracks: TrackSet, config: MeasurementSelectionConfig) -> dict[str, float]:
    mask = tracks.ages > 1
    mask &= np.isfinite(tracks.prev_points).all(axis=1)
    mask &= np.isfinite(tracks.points).all(axis=1)
    pts0 = tracks.prev_points[mask]
    pts1 = tracks.points[mask]
    n = min(len(pts0), len(pts1))
    if n < 8:
        age = _median_or_zero(tracks.ages)
        long_ratio = _long_track_ratio(tracks.ages)
        continuity = 0.60 * np.clip(age / max(1e-6, float(config.age_score_scale)), 0.0, 1.0) + 0.40 * long_ratio
        return {
            "pairs": float(n),
            "f_ratio": 0.0,
            "h_ratio": 0.0,
            "epi": float("nan"),
            "hom": float("nan"),
            "geometry": 0.0,
            "continuity": float(continuity),
        }

    f_mat, f_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        cv2.FM_RANSAC,
        float(config.f_ransac_threshold),
        0.99,
    )
    h_mat, h_mask = cv2.findHomography(
        pts0,
        pts1,
        cv2.RANSAC,
        float(config.h_ransac_threshold),
    )
    f_ratio = _mask_ratio(f_mask, n)
    h_ratio = _mask_ratio(h_mask, n)
    epi = float(np.median(_epipolar_errors(f_mat, pts0, pts1))) if _valid_matrix(f_mat) else float("nan")
    hom = float(np.median(_homography_errors(h_mat, pts0, pts1))) if _valid_matrix(h_mat) else float("nan")
    epi_score = _residual_score(epi, float(config.f_residual_scale))
    hom_score = _residual_score(hom, float(config.h_residual_scale))
    count_score = min(1.0, n / max(1.0, float(config.validation_min_pairs)))
    age = _median_or_zero(tracks.ages)
    long_ratio = _long_track_ratio(tracks.ages)
    continuity = 0.60 * np.clip(age / max(1e-6, float(config.age_score_scale)), 0.0, 1.0) + 0.40 * long_ratio
    geometry = (
        0.42 * epi_score
        + 0.18 * hom_score
        + 0.22 * f_ratio
        + 0.10 * h_ratio
        + 0.08 * count_score
    )
    return {
        "pairs": float(n),
        "f_ratio": float(f_ratio),
        "h_ratio": float(h_ratio),
        "epi": float(epi),
        "hom": float(hom),
        "geometry": float(geometry),
        "continuity": float(continuity),
    }


def _eligible_mask(tracks: TrackSet, config: MeasurementSelectionConfig) -> np.ndarray:
    mask = tracks.ages >= int(config.min_age)
    mask &= tracks.qualities >= float(config.min_quality)
    mask &= tracks.ncc_scores >= float(config.min_ncc)
    mask &= tracks.fb_errors <= float(config.max_fb_error)
    mask &= np.isfinite(tracks.prev_points).all(axis=1)
    mask &= np.isfinite(tracks.points).all(axis=1)
    return mask.astype(bool)


def _geometry_keep_mask_and_score(
    pts0: np.ndarray,
    pts1: np.ndarray,
    config: MeasurementSelectionConfig,
    geometry_mode: str = "unknown",
) -> tuple[np.ndarray, np.ndarray]:
    pts0 = np.asarray(pts0, dtype=np.float32).reshape(-1, 2)
    pts1 = np.asarray(pts1, dtype=np.float32).reshape(-1, 2)
    n = min(len(pts0), len(pts1))
    if n < 8:
        return np.ones((n,), dtype=bool), np.ones((n,), dtype=np.float32)

    f_mask = None
    h_mask = None
    f_score = None
    h_score = None
    seed = int(getattr(config, "ransac_seed", -1))
    if seed >= 0:
        cv2.setRNGSeed(seed)
    f_mat, raw_f_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        cv2.FM_RANSAC,
        float(config.f_ransac_threshold),
        0.99,
    )
    if f_mat is not None and np.asarray(f_mat).shape == (3, 3) and raw_f_mask is not None:
        f_mask = raw_f_mask.reshape(-1).astype(bool)
        f_error = _epipolar_errors(f_mat, pts0, pts1)
        f_score = np.exp(-f_error / max(1e-6, float(config.f_residual_scale))).astype(np.float32)
    if seed >= 0:
        cv2.setRNGSeed(seed + 1)
    h_mat, raw_h_mask = cv2.findHomography(
        pts0,
        pts1,
        cv2.RANSAC,
        float(config.h_ransac_threshold),
    )
    if h_mat is not None and np.asarray(h_mat).shape == (3, 3) and raw_h_mask is not None:
        h_mask = raw_h_mask.reshape(-1).astype(bool)
        h_error = _homography_errors(h_mat, pts0, pts1)
        h_score = np.exp(-h_error / max(1e-6, float(config.h_residual_scale))).astype(np.float32)

    mode = str(config.model or "fundamental").lower()
    if mode in {"none", "all", "quality"}:
        return np.ones((n,), dtype=bool), np.ones((n,), dtype=np.float32)
    if mode in {"adaptive_best", "best", "auto"}:
        selected = _select_adaptive_geometry_mask(
            pts0,
            pts1,
            f_mask=f_mask,
            h_mask=h_mask,
            f_score=f_score,
            h_score=h_score,
            config=config,
        )
        if selected is not None:
            return selected
    if mode in {"adaptive_mode", "mode_aware", "geometry_mode"}:
        selected = _select_mode_aware_geometry_mask(
            pts0,
            pts1,
            f_mask=f_mask,
            h_mask=h_mask,
            f_score=f_score,
            h_score=h_score,
            config=config,
            geometry_mode=geometry_mode,
        )
        if selected is not None:
            return selected
    if mode == "fundamental" and f_mask is not None:
        return f_mask, f_score
    if mode == "homography" and h_mask is not None:
        return h_mask, h_score
    if mode in {"both", "and", "fundamental_and_homography"} and f_mask is not None and h_mask is not None:
        return f_mask & h_mask, np.minimum(f_score, h_score).astype(np.float32)
    if mode in {"either", "or"}:
        masks = [item for item in (f_mask, h_mask) if item is not None]
        scores = [item for item in (f_score, h_score) if item is not None]
        if masks:
            return np.logical_or.reduce(masks), np.maximum.reduce(scores).astype(np.float32)
    if mode in {"adaptive", "fundamental_then_homography"}:
        if f_mask is not None and float(np.mean(f_mask)) >= 0.45:
            return f_mask, f_score
        if h_mask is not None:
            return h_mask, h_score
    if f_mask is not None:
        return f_mask, f_score
    if h_mask is not None:
        return h_mask, h_score
    return np.ones((n,), dtype=bool), np.ones((n,), dtype=np.float32)


def _select_adaptive_geometry_mask(
    pts0: np.ndarray,
    pts1: np.ndarray,
    f_mask: np.ndarray | None,
    h_mask: np.ndarray | None,
    f_score: np.ndarray | None,
    h_score: np.ndarray | None,
    config: MeasurementSelectionConfig,
) -> tuple[np.ndarray, np.ndarray] | None:
    candidates: list[tuple[str, np.ndarray, np.ndarray]] = []
    if f_mask is not None and f_score is not None:
        candidates.append(("fundamental", f_mask, f_score))
    if h_mask is not None and h_score is not None:
        candidates.append(("homography", h_mask, h_score))
    if f_mask is not None and h_mask is not None and f_score is not None and h_score is not None:
        candidates.append(("both", f_mask & h_mask, np.minimum(f_score, h_score).astype(np.float32)))
        candidates.append(("either", f_mask | h_mask, np.maximum(f_score, h_score).astype(np.float32)))
    if not candidates:
        return None

    min_tracks = max(8, int(config.adaptive_min_tracks))
    min_keep_ratio = float(np.clip(config.adaptive_min_keep_ratio, 0.0, 1.0))
    best: tuple[float, np.ndarray, np.ndarray] | None = None
    for _, mask, score in candidates:
        keep = np.asarray(mask, dtype=bool)
        keep_count = int(np.sum(keep))
        if keep_count < 8:
            continue
        if keep_count < min_tracks and keep_count / max(1, len(keep)) < min_keep_ratio:
            continue
        quality = _candidate_geometry_quality(pts0[keep], pts1[keep], keep_count, len(keep), config)
        # Break near-ties in favor of keeping more measurements.
        quality += 1e-4 * min(1.0, keep_count / max(1.0, float(min_tracks)))
        if best is None or quality > best[0]:
            best = (quality, keep, np.asarray(score, dtype=np.float32))
    if best is not None:
        return best[1], best[2]
    return None


def _select_mode_aware_geometry_mask(
    pts0: np.ndarray,
    pts1: np.ndarray,
    f_mask: np.ndarray | None,
    h_mask: np.ndarray | None,
    f_score: np.ndarray | None,
    h_score: np.ndarray | None,
    config: MeasurementSelectionConfig,
    geometry_mode: str = "unknown",
) -> tuple[np.ndarray, np.ndarray] | None:
    if f_mask is None and h_mask is None:
        return None
    if f_mask is None and h_mask is not None and h_score is not None:
        return h_mask, h_score
    if h_mask is None and f_mask is not None and f_score is not None:
        return f_mask, f_score
    if f_mask is None or h_mask is None or f_score is None or h_score is None:
        return None

    strict_f_mask, strict_f_score = _fundamental_mask_and_score(
        pts0,
        pts1,
        threshold=float(config.adaptive_both_f_ransac_threshold),
        residual_scale=float(config.f_residual_scale),
    )
    strict_h_mask, strict_h_score = _homography_mask_and_score(
        pts0,
        pts1,
        threshold=float(config.adaptive_both_h_ransac_threshold),
        residual_scale=float(config.h_residual_scale),
    )
    loose_f_mask, loose_f_score = _fundamental_mask_and_score(
        pts0,
        pts1,
        threshold=float(config.adaptive_f_only_ransac_threshold),
        residual_scale=float(config.f_residual_scale),
    )
    f_mask_for_decision = strict_f_mask if strict_f_mask is not None else f_mask
    h_mask_for_decision = strict_h_mask if strict_h_mask is not None else h_mask
    f_score_for_decision = strict_f_score if strict_f_score is not None else f_score
    h_score_for_decision = strict_h_score if strict_h_score is not None else h_score
    if (
        f_mask_for_decision is None
        or h_mask_for_decision is None
        or f_score_for_decision is None
        or h_score_for_decision is None
    ):
        return None

    mode = str(geometry_mode or "unknown").lower()
    both = f_mask_for_decision & h_mask_for_decision
    both_count = int(np.sum(both))
    enough_both = both_count >= max(8, int(config.adaptive_min_tracks)) or (
        both_count / max(1, len(both)) >= float(config.adaptive_min_keep_ratio)
    )
    if mode == "normal" and loose_f_mask is not None and loose_f_score is not None:
        return loose_f_mask, loose_f_score
    if mode in {"planar_near_wall", "severe_low_texture", "degraded_texture"} and enough_both:
        return both, np.minimum(f_score_for_decision, h_score_for_decision).astype(np.float32)

    f_ratio = float(np.mean(f_mask_for_decision))
    h_ratio = float(np.mean(h_mask_for_decision))
    f_mean_score = float(np.mean(f_score_for_decision))
    h_mean_score = float(np.mean(h_score_for_decision))
    score_ratio = float(h_mean_score / (f_mean_score + 1e-6))
    planar_or_weak_f = (
        h_ratio >= float(config.adaptive_planar_h_ratio)
        and score_ratio >= float(config.adaptive_planar_score_ratio)
    ) or f_ratio < float(config.adaptive_low_f_ratio)
    strong_f = (
        f_ratio >= float(config.adaptive_strong_f_ratio)
        and f_mean_score >= float(config.adaptive_f_score_margin) * h_mean_score
    )
    if strong_f and loose_f_mask is not None and loose_f_score is not None:
        return loose_f_mask, loose_f_score
    if planar_or_weak_f and enough_both:
        return both, np.minimum(f_score_for_decision, h_score_for_decision).astype(np.float32)
    if loose_f_mask is not None and loose_f_score is not None:
        return loose_f_mask, loose_f_score
    return f_mask, f_score


def _candidate_geometry_quality(
    pts0: np.ndarray,
    pts1: np.ndarray,
    keep_count: int,
    total_count: int,
    config: MeasurementSelectionConfig,
) -> float:
    if len(pts0) < 8:
        return -1.0
    f_mat, f_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        cv2.FM_RANSAC,
        float(config.f_ransac_threshold),
        0.99,
    )
    h_mat, h_mask = cv2.findHomography(
        pts0,
        pts1,
        cv2.RANSAC,
        float(config.h_ransac_threshold),
    )
    f_ratio = _mask_ratio(f_mask, len(pts0))
    h_ratio = _mask_ratio(h_mask, len(pts0))
    epi = float(np.median(_epipolar_errors(f_mat, pts0, pts1))) if _valid_matrix(f_mat) else float("nan")
    hom = float(np.median(_homography_errors(h_mat, pts0, pts1))) if _valid_matrix(h_mat) else float("nan")
    epi_score = _residual_score(epi, float(config.f_residual_scale))
    hom_score = _residual_score(hom, float(config.h_residual_scale))
    inlier_score = 0.65 * f_ratio + 0.35 * h_ratio
    count_score = min(1.0, keep_count / max(1.0, float(config.adaptive_min_tracks)))
    keep_ratio = keep_count / max(1.0, float(total_count))
    score = (
        float(config.adaptive_epipolar_weight) * epi_score
        + float(config.adaptive_homography_weight) * hom_score
        + float(config.adaptive_inlier_weight) * inlier_score
        + float(config.adaptive_count_weight) * count_score
    )
    return float(score * (0.85 + 0.15 * keep_ratio))


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


def _fundamental_mask_and_score(
    pts0: np.ndarray,
    pts1: np.ndarray,
    threshold: float,
    residual_scale: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    f_mat, raw_mask = cv2.findFundamentalMat(
        pts0,
        pts1,
        cv2.FM_RANSAC,
        float(threshold),
        0.99,
    )
    if not _valid_matrix(f_mat) or raw_mask is None:
        return None, None
    error = _epipolar_errors(f_mat, pts0, pts1)
    score = np.exp(-error / max(1e-6, float(residual_scale))).astype(np.float32)
    return raw_mask.reshape(-1).astype(bool), score


def _homography_mask_and_score(
    pts0: np.ndarray,
    pts1: np.ndarray,
    threshold: float,
    residual_scale: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    h_mat, raw_mask = cv2.findHomography(
        pts0,
        pts1,
        cv2.RANSAC,
        float(threshold),
    )
    if not _valid_matrix(h_mat) or raw_mask is None:
        return None, None
    error = _homography_errors(h_mat, pts0, pts1)
    score = np.exp(-error / max(1e-6, float(residual_scale))).astype(np.float32)
    return raw_mask.reshape(-1).astype(bool), score


def _valid_matrix(mat: np.ndarray | None) -> bool:
    return mat is not None and np.asarray(mat).shape == (3, 3)


def _mask_ratio(mask: np.ndarray | None, count: int) -> float:
    if mask is None or count <= 0:
        return 0.0
    return float(np.mean(np.asarray(mask).reshape(-1).astype(bool)))


def _residual_score(value: float, scale: float) -> float:
    if value != value:
        return 0.0
    return float(np.exp(-max(0.0, float(value)) / max(1e-6, float(scale))))


def _finite(value: float) -> bool:
    return bool(np.isfinite(float(value)))


def _median_or_zero(values: np.ndarray) -> float:
    values = np.asarray(values)
    if len(values) == 0:
        return 0.0
    return float(np.median(values))


def _long_track_ratio(ages: np.ndarray, threshold: int = 5) -> float:
    ages = np.asarray(ages)
    if len(ages) == 0:
        return 0.0
    return float(np.mean(ages >= int(threshold)))


def _selection_scores(
    tracks: TrackSet,
    indices: np.ndarray,
    config: MeasurementSelectionConfig,
    image_shape: tuple[int, int] | None = None,
) -> np.ndarray:
    qualities = np.clip(tracks.qualities[indices].astype(np.float32), 0.0, 1.0)
    ages = tracks.ages[indices].astype(np.float32)
    ncc = np.clip((tracks.ncc_scores[indices].astype(np.float32) + 1.0) * 0.5, 0.0, 1.0)
    fb = np.maximum(0.0, tracks.fb_errors[indices].astype(np.float32))
    age_score = np.clip(ages / max(1e-6, float(config.age_score_scale)), 0.0, 1.0)
    fb_score = np.exp(-fb / max(1e-6, float(config.max_fb_error))).astype(np.float32)
    if not config.information_score_enabled:
        return qualities * (0.35 + 0.65 * age_score) * (0.35 + 0.65 * ncc) * (0.35 + 0.65 * fb_score)

    quality_term = np.power(np.clip(0.05 + 0.95 * qualities, 1e-3, 1.0), float(config.information_quality_power))
    age_term = np.power(np.clip(0.10 + 0.90 * age_score, 1e-3, 1.0), float(config.information_age_power))
    ncc_term = np.power(np.clip(0.10 + 0.90 * ncc, 1e-3, 1.0), float(config.information_ncc_power))
    fb_term = np.power(np.clip(0.10 + 0.90 * fb_score, 1e-3, 1.0), float(config.information_fb_power))
    source_term = _source_prior_scores([tracks.sources[int(idx)] for idx in indices])
    source_weight = np.clip(float(config.information_source_weight), 0.0, 1.0)
    source_gain = (1.0 - source_weight) + source_weight * source_term
    spread_gain = 1.0
    if image_shape is not None and len(indices):
        points = tracks.points[indices]
        spread = _spatial_spread_scores(points, image_shape)
        spread_weight = np.clip(float(config.information_spread_weight), 0.0, 1.0)
        spread_gain = (1.0 - spread_weight) + spread_weight * spread
        cell = _cell_rarity_scores(
            points,
            image_shape,
            max(1, int(config.grid_rows)),
            max(1, int(config.grid_cols)),
        )
        cell_weight = np.clip(float(config.information_cell_weight), 0.0, 1.0)
        spread_gain = spread_gain * ((1.0 - cell_weight) + cell_weight * cell)
    return (quality_term * age_term * ncc_term * fb_term * source_gain * spread_gain).astype(np.float32)


def _source_prior_scores(sources: list[str]) -> np.ndarray:
    priors = []
    for source in sources:
        name = str(source)
        if name in {"klt", "gftt_confirmed", "homography_recovery"}:
            priors.append(1.0)
        elif name in {"gftt", "gftt_seed", "lk_recovery"}:
            priors.append(0.92)
        elif name in {"orb_recovery", "orb_match", "orb"}:
            priors.append(0.78)
        elif name.endswith("_recovery"):
            priors.append(0.72)
        elif name.endswith("_init"):
            priors.append(0.62)
        else:
            priors.append(0.80)
    return np.asarray(priors, dtype=np.float32)


def _spatial_spread_scores(points: np.ndarray, image_shape: tuple[int, int]) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0,), dtype=np.float32)
    h, w = image_shape[:2]
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    center = np.asarray([0.5 * max(1, w), 0.5 * max(1, h)], dtype=np.float32)
    scale = np.asarray([0.5 * max(1, w), 0.5 * max(1, h)], dtype=np.float32)
    radius = np.linalg.norm((pts - center.reshape(1, 2)) / scale.reshape(1, 2), axis=1)
    return np.clip(0.50 + 0.50 * radius / np.sqrt(2.0), 0.50, 1.0).astype(np.float32)


def _cell_rarity_scores(
    points: np.ndarray,
    image_shape: tuple[int, int],
    rows: int,
    cols: int,
) -> np.ndarray:
    if len(points) == 0:
        return np.empty((0,), dtype=np.float32)
    h, w = image_shape[:2]
    cells = _cell_indices(points, h, w, rows, cols)
    counts = np.zeros((rows, cols), dtype=np.int32)
    for row, col in cells:
        counts[row, col] += 1
    rarity = np.asarray([1.0 / np.sqrt(max(1, counts[row, col])) for row, col in cells], dtype=np.float32)
    if len(rarity) and float(np.max(rarity)) > 0.0:
        rarity = rarity / float(np.max(rarity))
    return np.clip(rarity, 0.25, 1.0).astype(np.float32)


def _residual_refine_indices(
    indices: np.ndarray,
    scores: np.ndarray,
    config: MeasurementSelectionConfig,
) -> tuple[np.ndarray, np.ndarray]:
    if not config.residual_refine_enabled:
        return indices, scores
    indices = np.asarray(indices, dtype=np.int64)
    scores = np.asarray(scores, dtype=np.float32)
    if len(indices) == 0 or len(indices) != len(scores):
        return indices, scores
    min_features = max(8, int(config.residual_refine_min_features), int(config.min_features))
    if len(indices) <= min_features:
        return indices, scores
    keep_ratio = float(np.clip(config.residual_refine_keep_ratio, 0.0, 1.0))
    keep_count = max(min_features, int(np.ceil(len(indices) * keep_ratio)))
    keep_count = min(len(indices), keep_count)
    min_score = float(config.residual_refine_min_score)
    if min_score > 0.0:
        score_mask = scores >= min_score
        if int(np.sum(score_mask)) >= min_features:
            indices = indices[score_mask]
            scores = scores[score_mask]
            keep_count = min(len(indices), max(min_features, int(np.ceil(len(indices) * keep_ratio))))
    if len(indices) <= keep_count:
        return indices, scores
    order = np.argsort(-scores)[:keep_count]
    return indices[order], scores[order]


def _residual_refine_arrays(
    indices: np.ndarray,
    geom_scores: np.ndarray,
    rank_scores: np.ndarray,
    config: MeasurementSelectionConfig,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not config.residual_refine_enabled:
        return indices, geom_scores, rank_scores
    indices = np.asarray(indices, dtype=np.int64)
    geom_scores = np.asarray(geom_scores, dtype=np.float32)
    rank_scores = np.asarray(rank_scores, dtype=np.float32)
    if len(indices) == 0 or len(indices) != len(geom_scores) or len(indices) != len(rank_scores):
        return indices, geom_scores, rank_scores
    min_features = max(8, int(config.residual_refine_min_features), int(config.min_features))
    if len(indices) <= min_features:
        return indices, geom_scores, rank_scores
    keep_ratio = float(np.clip(config.residual_refine_keep_ratio, 0.0, 1.0))
    keep_count = min(len(indices), max(min_features, int(np.ceil(len(indices) * keep_ratio))))
    min_score = float(config.residual_refine_min_score)
    if min_score > 0.0:
        score_mask = rank_scores >= min_score
        if int(np.sum(score_mask)) >= min_features:
            indices = indices[score_mask]
            geom_scores = geom_scores[score_mask]
            rank_scores = rank_scores[score_mask]
            keep_count = min(len(indices), max(min_features, int(np.ceil(len(indices) * keep_ratio))))
    if len(indices) <= keep_count:
        return indices, geom_scores, rank_scores
    order = np.argsort(-rank_scores)[:keep_count]
    return indices[order], geom_scores[order], rank_scores[order]


def _residual_refine_selected(
    selected: np.ndarray,
    candidate_indices: np.ndarray,
    candidate_scores: np.ndarray,
    config: MeasurementSelectionConfig,
) -> np.ndarray:
    if not config.residual_refine_enabled:
        return selected
    selected = np.asarray(selected, dtype=np.int64)
    if len(selected) == 0 or len(candidate_indices) != len(candidate_scores):
        return selected
    score_by_index = {
        int(index): float(score)
        for index, score in zip(candidate_indices, candidate_scores)
    }
    scores = np.asarray([score_by_index.get(int(index), 1.0) for index in selected], dtype=np.float32)
    refined, _ = _residual_refine_indices(selected, scores, config)
    return refined


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
        for row, col in _cell_indices(existing_points, h, w, rows, cols):
            counts[row, col] += 1
    scores = []
    for row, col in _cell_indices(candidate_points, h, w, rows, cols):
        occupancy = counts[row, col]
        scores.append(np.clip((target_cell_count - occupancy) / max(1.0, float(target_cell_count)), 0.0, 1.0))
    return np.asarray(scores, dtype=np.float32)


def _select_grid_balanced(
    indices: np.ndarray,
    points: np.ndarray,
    scores: np.ndarray,
    image_shape: tuple[int, int],
    max_count: int,
    rows: int,
    cols: int,
    max_per_cell: int,
) -> np.ndarray:
    if len(indices) == 0 or max_count <= 0:
        return np.empty((0,), dtype=np.int64)
    h, w = image_shape[:2]
    cells = _cell_indices(points, h, w, rows, cols)
    selected: list[int] = []
    selected_set: set[int] = set()
    cell_counts = np.zeros((rows, cols), dtype=np.int32)

    order = np.argsort(-scores)
    for idx in order:
        row, col = cells[idx]
        if cell_counts[row, col] >= max_per_cell:
            continue
        track_index = int(indices[idx])
        selected.append(track_index)
        selected_set.add(track_index)
        cell_counts[row, col] += 1
        if len(selected) >= max_count:
            break

    if len(selected) < max_count:
        for idx in order:
            track_index = int(indices[idx])
            if track_index in selected_set:
                continue
            selected.append(track_index)
            selected_set.add(track_index)
            if len(selected) >= max_count:
                break
    return np.asarray(selected, dtype=np.int64)


def _fill_with_quality(
    selected: np.ndarray,
    candidates: np.ndarray,
    tracks: TrackSet,
    max_count: int,
) -> np.ndarray:
    selected = np.asarray(selected, dtype=np.int64)
    selected_set = set(int(item) for item in selected)
    fill = [int(item) for item in selected]
    remaining = [int(item) for item in candidates if int(item) not in selected_set]
    remaining.sort(key=lambda idx: float(tracks.qualities[idx]), reverse=True)
    for idx in remaining:
        fill.append(idx)
        if len(fill) >= max_count:
            break
    return np.asarray(fill, dtype=np.int64)


def _subset_tracks(tracks: TrackSet, indices: np.ndarray) -> TrackSet:
    indices = np.asarray(indices, dtype=np.int64)
    if len(indices) == 0:
        return TrackSet.empty()
    return TrackSet(
        ids=tracks.ids[indices].copy(),
        prev_points=tracks.prev_points[indices].copy(),
        points=tracks.points[indices].copy(),
        ages=tracks.ages[indices].copy(),
        fb_errors=tracks.fb_errors[indices].copy(),
        ncc_scores=tracks.ncc_scores[indices].copy(),
        local_texture=tracks.local_texture[indices].copy(),
        qualities=tracks.qualities[indices].copy(),
        sources=[tracks.sources[int(idx)] for idx in indices],
    )


def _append_track_subset(base: TrackSet, extra: TrackSet, extra_indices: np.ndarray) -> TrackSet:
    extra_indices = np.asarray(extra_indices, dtype=np.int64)
    if len(extra_indices) == 0:
        return base
    return TrackSet(
        ids=np.concatenate([base.ids, extra.ids[extra_indices]]).copy(),
        prev_points=np.concatenate([base.prev_points, extra.prev_points[extra_indices]], axis=0).copy(),
        points=np.concatenate([base.points, extra.points[extra_indices]], axis=0).copy(),
        ages=np.concatenate([base.ages, extra.ages[extra_indices]]).copy(),
        fb_errors=np.concatenate([base.fb_errors, extra.fb_errors[extra_indices]]).copy(),
        ncc_scores=np.concatenate([base.ncc_scores, extra.ncc_scores[extra_indices]]).copy(),
        local_texture=np.concatenate([base.local_texture, extra.local_texture[extra_indices]]).copy(),
        qualities=np.concatenate([base.qualities, extra.qualities[extra_indices]]).copy(),
        sources=base.sources + [extra.sources[int(idx)] for idx in extra_indices],
    )


def _cell_indices(points: np.ndarray, h: int, w: int, rows: int, cols: int) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
    xs = np.clip((pts[:, 0] / max(1, w) * cols).astype(np.int32), 0, cols - 1)
    ys = np.clip((pts[:, 1] / max(1, h) * rows).astype(np.int32), 0, rows - 1)
    return np.stack([ys, xs], axis=1)
