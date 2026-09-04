from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from uw_frontend.geometry.dl_vins_magsac import (
    DlVinsMagsacResult,
    filter_dl_vins_magsac,
    require_dl_vins_magsac_available,
)
from uw_frontend.matchers.base import BaseMatcher
from uw_frontend.quality.image_quality import ImageQuality, local_texture_scores
from uw_frontend.tracking.klt_tracker import _patch_ncc
from uw_frontend.tracking.track_state import TrackerDiagnostics, TrackSet


@dataclass
class PairwiseMatcherTrackerConfig:
    max_features: int = 350
    association_radius: float = 8.0
    min_ncc: float = 0.35
    min_confidence: float = 0.0
    q_min: float = 0.05
    persistent_id_mode: str = "legacy"
    use_ncc: bool = True
    geometry_mode: str = "disabled"


class PairwiseMatcherTracker:
    """Frame-to-frame learned matcher baseline with approximate persistent ids."""

    def __init__(
        self,
        matcher: BaseMatcher,
        config: PairwiseMatcherTrackerConfig | None = None,
        *,
        point_normalizer: Callable[[np.ndarray], np.ndarray] | None = None,
        geometry_focal_mean_px: float | None = None,
    ) -> None:
        self.matcher = matcher
        self.config = config or PairwiseMatcherTrackerConfig()
        if self.config.persistent_id_mode not in {"legacy", "continuity_first_v2"}:
            raise ValueError(
                "persistent_id_mode must be 'legacy' or 'continuity_first_v2'"
            )
        if not isinstance(self.config.use_ncc, bool):
            raise ValueError("use_ncc must be a boolean")
        if self.config.geometry_mode not in {"disabled", "dl_vins_magsac"}:
            raise ValueError(
                "geometry_mode must be 'disabled' or 'dl_vins_magsac'"
            )
        self._point_normalizer = point_normalizer
        self._geometry_focal_mean_px = geometry_focal_mean_px
        if self.config.geometry_mode == "dl_vins_magsac":
            require_dl_vins_magsac_available()
            if self.matcher.name != "superpoint_lightglue":
                raise RuntimeError(
                    "DL-VINS MAGSAC comparator requires the superpoint_lightglue matcher"
                )
            if self.config.persistent_id_mode != "continuity_first_v2":
                raise RuntimeError(
                    "DL-VINS MAGSAC comparator requires continuity_first_v2 ID association"
                )
            if self.config.use_ncc:
                raise RuntimeError(
                    "DL-VINS MAGSAC comparator requires use_ncc=false"
                )
            if self._point_normalizer is None:
                raise RuntimeError(
                    "DL-VINS MAGSAC geometry requires a calibrated point normalizer"
                )
            if (
                self._geometry_focal_mean_px is None
                or not np.isfinite(self._geometry_focal_mean_px)
                or float(self._geometry_focal_mean_px) <= 0.0
            ):
                raise RuntimeError(
                    "DL-VINS MAGSAC geometry requires a positive finite focal mean"
                )
        self.prev_image: np.ndarray | None = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0
        self._record_geometry_diagnostics(
            candidate_count=0,
            inlier_count=0,
            inlier_ratio=float("nan"),
            action="disabled" if self.config.geometry_mode == "disabled" else "not_run",
            reason="geometry_disabled" if self.config.geometry_mode == "disabled" else "not_run",
        )

    def reset(self) -> None:
        self.prev_image = None
        self.points = np.empty((0, 2), dtype=np.float32)
        self.ids = np.empty((0,), dtype=np.int64)
        self.ages = np.empty((0,), dtype=np.int32)
        self.next_id = 0
        self._record_geometry_diagnostics(
            candidate_count=0,
            inlier_count=0,
            inlier_ratio=float("nan"),
            action="disabled" if self.config.geometry_mode == "disabled" else "not_run",
            reason="geometry_disabled" if self.config.geometry_mode == "disabled" else "reset",
        )
        reset_matcher = getattr(self.matcher, "reset", None)
        if callable(reset_matcher):
            reset_matcher()

    def process(self, image: np.ndarray, image_quality: ImageQuality) -> tuple[TrackSet, TrackerDiagnostics]:
        gray = image.astype(np.uint8, copy=False)
        self._record_geometry_diagnostics(
            candidate_count=0,
            inlier_count=0,
            inlier_ratio=float("nan"),
            action="disabled" if self.config.geometry_mode == "disabled" else "not_run",
            reason="geometry_disabled" if self.config.geometry_mode == "disabled" else "not_run",
        )
        if self.prev_image is None:
            self.prev_image = gray.copy()
            if self.config.geometry_mode != "disabled":
                self.last_pairwise_geometry_reason = "priming_frame"
            return TrackSet.empty(), TrackerDiagnostics(0, 0, 0, 0, float("nan"), float("nan"), float("nan"))

        prev_count = len(self.ids)
        match_result = self.matcher.match(self.prev_image, gray)
        if len(match_result) == 0:
            dropped = prev_count
            if self.config.geometry_mode != "disabled":
                self.last_pairwise_geometry_reason = "matcher_empty"
            self.prev_image = gray.copy()
            self.points = np.empty((0, 2), dtype=np.float32)
            self.ids = np.empty((0,), dtype=np.int64)
            self.ages = np.empty((0,), dtype=np.int32)
            return TrackSet.empty(), TrackerDiagnostics(0, dropped, prev_count, 0, float("nan"), float("nan"), float("nan"))

        confidences = match_result.confidences.astype(np.float32) if len(match_result.confidences) else np.ones((len(match_result),), dtype=np.float32)
        valid_conf = confidences >= self.config.min_confidence
        prev_points = match_result.points0[valid_conf].astype(np.float32)
        cur_points = match_result.points1[valid_conf].astype(np.float32)
        confidences = confidences[valid_conf]
        if len(confidences) == 0:
            dropped = prev_count
            if self.config.geometry_mode != "disabled":
                self.last_pairwise_geometry_reason = "confidence_filter_empty"
            self.prev_image = gray.copy()
            self.points = np.empty((0, 2), dtype=np.float32)
            self.ids = np.empty((0,), dtype=np.int64)
            self.ages = np.empty((0,), dtype=np.int32)
            return TrackSet.empty(), TrackerDiagnostics(0, dropped, prev_count, 0, float("nan"), float("nan"), float("nan"))

        if (
            self.config.persistent_id_mode == "legacy"
            and len(confidences) > self.config.max_features
        ):
            order = np.argsort(-confidences)[: self.config.max_features]
            prev_points = prev_points[order]
            cur_points = cur_points[order]
            confidences = confidences[order]

        if self.config.use_ncc:
            ncc = _patch_ncc(self.prev_image, gray, prev_points, cur_points, radius=5)
            valid_ncc = ncc >= self.config.min_ncc
            prev_points = prev_points[valid_ncc]
            cur_points = cur_points[valid_ncc]
            confidences = confidences[valid_ncc]
            ncc = ncc[valid_ncc].astype(np.float32)
        else:
            # A neutral value preserves the existing TrackSet and cap contracts
            # without running or implicitly ranking by the NCC ablation.
            ncc = np.ones((len(cur_points),), dtype=np.float32)

        if self.config.geometry_mode == "dl_vins_magsac":
            geometry = self._filter_dl_vins_geometry(prev_points, cur_points)
            keep = geometry.keep_mask
            prev_points = prev_points[keep]
            cur_points = cur_points[keep]
            confidences = confidences[keep]
            ncc = ncc[keep]
        else:
            count = int(len(cur_points))
            self._record_geometry_diagnostics(
                candidate_count=count,
                inlier_count=count,
                inlier_ratio=1.0 if count else float("nan"),
                action="disabled",
                reason="geometry_disabled",
            )

        if self.config.persistent_id_mode == "continuity_first_v2":
            assigned_ids, assigned_ages = self._associate_continuity_first(
                prev_points, confidences
            )
        else:
            assigned_ids = np.empty((len(cur_points),), dtype=np.int64)
            assigned_ages = np.empty((len(cur_points),), dtype=np.int32)
            matched_prev_ids: set[int] = set()
            for i, prev_point in enumerate(prev_points):
                prev_idx = _nearest_index(self.points, prev_point)
                if prev_idx is not None and prev_idx not in matched_prev_ids:
                    distance = float(np.linalg.norm(self.points[prev_idx] - prev_point))
                    if distance <= self.config.association_radius:
                        assigned_ids[i] = self.ids[prev_idx]
                        assigned_ages[i] = self.ages[prev_idx] + 1
                        matched_prev_ids.add(prev_idx)
                        continue
                assigned_ids[i] = self.next_id
                self.next_id += 1
                assigned_ages[i] = 1

        if (
            self.config.persistent_id_mode == "continuity_first_v2"
            and len(cur_points) > self.config.max_features
        ):
            # The legacy path truncates an arbitrarily ordered pairwise match list
            # before it attempts to continue IDs.  XFeat returns many valid matches,
            # so that ordering destroys almost every multi-frame lineage.  M2 first
            # continues IDs over the full candidate set and only then applies the
            # backend cap: existing/older tracks win, while native confidence and
            # NCC deterministically rank births that fill the remaining budget.
            indices = np.arange(len(cur_points), dtype=np.int64)
            persisted = (assigned_ages > 1).astype(np.int8)
            order = np.lexsort(
                (
                    indices,
                    -ncc.astype(np.float64),
                    -confidences.astype(np.float64),
                    -assigned_ages.astype(np.int64),
                    -persisted.astype(np.int64),
                )
            )[: self.config.max_features]
            prev_points = prev_points[order]
            cur_points = cur_points[order]
            confidences = confidences[order]
            ncc = ncc[order]
            assigned_ids = assigned_ids[order]
            assigned_ages = assigned_ages[order]

        # Local texture and final quality do not participate in the M2 cap.  They
        # are therefore evaluated only for the selected backend budget, preserving
        # the exact selected tracks while avoiding work on discarded candidates.
        local_tex = local_texture_scores(gray, cur_points)
        age_score = np.clip(assigned_ages.astype(np.float32) / 20.0, 0.0, 1.0)
        quality = np.clip(
            image_quality.global_score
            * (0.20 + 0.80 * local_tex)
            * (0.25 + 0.75 * np.clip(confidences, 0.0, 1.0))
            * (0.30 + 0.70 * ncc)
            * (0.50 + 0.50 * age_score),
            self.config.q_min,
            1.0,
        ).astype(np.float32)

        self.prev_image = gray.copy()
        self.points = cur_points.astype(np.float32)
        self.ids = assigned_ids.astype(np.int64)
        self.ages = assigned_ages.astype(np.int32)
        tracked_after = int(np.sum(assigned_ages > 1))
        dropped = max(0, prev_count - tracked_after)
        tracks = TrackSet(
            ids=self.ids.copy(),
            prev_points=prev_points.astype(np.float32),
            points=self.points.copy(),
            ages=self.ages.copy(),
            fb_errors=1.0 - np.clip(confidences.astype(np.float32), 0.0, 1.0),
            ncc_scores=ncc,
            local_texture=local_tex.astype(np.float32),
            qualities=quality,
            sources=[self.matcher.name] * len(self.ids),
        )
        return tracks, TrackerDiagnostics(
            added_features=int(np.sum(assigned_ages == 1)),
            dropped_features=dropped,
            tracked_before_filter=prev_count,
            tracked_after_filter=tracked_after,
            median_fb_error=_median(tracks.fb_errors),
            median_ncc=_median(ncc),
            median_quality=_median(quality),
        )

    def _filter_dl_vins_geometry(
        self,
        prev_points: np.ndarray,
        cur_points: np.ndarray,
    ) -> DlVinsMagsacResult:
        candidate_count = int(len(prev_points))
        assert self._point_normalizer is not None
        assert self._geometry_focal_mean_px is not None
        try:
            prev_normalized = self._point_normalizer(prev_points)
            cur_normalized = self._point_normalizer(cur_points)
        except Exception as exc:
            result = DlVinsMagsacResult.fail_open(
                candidate_count,
                f"normalization_exception:{type(exc).__name__}",
            )
        else:
            try:
                result = filter_dl_vins_magsac(
                    prev_normalized,
                    cur_normalized,
                    focal_mean_px=float(self._geometry_focal_mean_px),
                )
            except Exception as exc:
                result = DlVinsMagsacResult.fail_open(
                    candidate_count,
                    f"geometry_exception:{type(exc).__name__}",
                )
        self._record_geometry_diagnostics(
            candidate_count=result.candidate_count,
            inlier_count=result.inlier_count,
            inlier_ratio=result.inlier_ratio,
            action=result.action,
            reason=result.reason,
        )
        return result

    def _record_geometry_diagnostics(
        self,
        *,
        candidate_count: int,
        inlier_count: int,
        inlier_ratio: float,
        action: str,
        reason: str,
    ) -> None:
        self.last_pairwise_geometry_candidate_count = int(candidate_count)
        self.last_pairwise_geometry_inlier_count = int(inlier_count)
        self.last_pairwise_geometry_inlier_ratio = float(inlier_ratio)
        self.last_pairwise_geometry_action = str(action)
        self.last_pairwise_geometry_reason = str(reason)

    def _associate_continuity_first(
        self, prev_points: np.ndarray, confidences: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Continue IDs globally before the feature cap is applied.

        Pairwise endpoints refer to the same previous image as ``self.points``.
        Exact/repeatable endpoints therefore have zero (or near-zero) distance.
        Sorting all candidate-to-state edges by distance before assignment prevents
        a nearby, arbitrarily ordered birth from stealing an established ID.
        """

        count = len(prev_points)
        assigned_ids = np.full((count,), -1, dtype=np.int64)
        assigned_ages = np.ones((count,), dtype=np.int32)
        if count and len(self.points):
            delta = prev_points[:, None, :] - self.points[None, :, :]
            distances = np.linalg.norm(delta, axis=2)
            nearest = np.argmin(distances, axis=1)
            nearest_distance = distances[np.arange(count), nearest]
            candidates = np.flatnonzero(
                nearest_distance <= float(self.config.association_radius)
            )
            # Distance is the primary key; confidence and stable input index only
            # break ties.  This makes exact endpoint identity dominate proximity.
            order = candidates[
                np.lexsort(
                    (
                        candidates,
                        -confidences[candidates].astype(np.float64),
                        nearest_distance[candidates].astype(np.float64),
                    )
                )
            ]
            used_state: set[int] = set()
            for candidate in order:
                state_index = int(nearest[candidate])
                if state_index in used_state:
                    continue
                assigned_ids[candidate] = self.ids[state_index]
                assigned_ages[candidate] = self.ages[state_index] + 1
                used_state.add(state_index)

        for index in np.flatnonzero(assigned_ids < 0):
            assigned_ids[index] = self.next_id
            self.next_id += 1
        return assigned_ids, assigned_ages


def _nearest_index(points: np.ndarray, query: np.ndarray) -> int | None:
    if len(points) == 0:
        return None
    distances = np.linalg.norm(points - query.reshape(1, 2), axis=1)
    return int(np.argmin(distances))


def _median(values: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    return float(np.nanmedian(values))
