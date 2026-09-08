"""Same-frame recovery of the original KLT point, before GFTT replenishment.

The existing PairwiseMatcherRecovery associates a learned keypoint endpoint
with a lost ID. This module instead uses local learned motion only as an LK
initial guess for the exact old KLT point. It never creates learned births.
"""
from __future__ import annotations

from dataclasses import dataclass
import time

import cv2
import numpy as np

from uw_frontend.matchers.base import MatchResult
from uw_frontend.quality.image_quality import local_texture_scores
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker, _in_border, _patch_ncc
from uw_frontend.tracking.matcher_recovery import _epipolar_errors, _homography_errors
from uw_frontend.tracking.track_state import TrackSet


@dataclass(frozen=True)
class RecoveryConfig:
    win_size: int = 31
    max_level: int = 4
    iterations: int = 40
    min_current_distance: float = 8.0
    min_reference: int = 8
    max_epipolar_error: float = 2.5
    max_homography_error: float = 5.0
    support_radius: float = 80.0
    support_max: int = 24
    support_min: int = 6
    affine_ransac_px: float = 2.0
    affine_min_inlier_fraction: float = 0.75
    affine_p90_px: float = 3.0
    affine_max_condition: float = 100.0
    affine_min_scale: float = 0.5
    affine_max_scale: float = 2.0


def subset(tracks, mask):
    ix = np.flatnonzero(mask) if np.asarray(mask).dtype == bool else np.asarray(mask, dtype=int)
    return TrackSet(**{k: [tracks.sources[i] for i in ix] if k == 'sources'
                       else getattr(tracks, k)[ix].copy()
                       for k in tracks.__dataclass_fields__})


class GeometryReference:
    """A common final gate fitted only to ordinary successful KLT tracks."""
    def __init__(self, ordinary, config):
        self.config = config
        self.f = self.h = None
        ref = subset(ordinary, ordinary.ages > 1)
        if len(ref) < config.min_reference:
            return
        # Reset RANSAC RNG so paired C/L calls use the same geometric reference.
        cv2.setRNGSeed(20260909)
        f, fm = cv2.findFundamentalMat(ref.prev_points, ref.points, cv2.FM_RANSAC, 1.0, .99)
        cv2.setRNGSeed(20260909)
        h, hm = cv2.findHomography(ref.prev_points, ref.points, cv2.RANSAC, 3.0)
        if f is not None and f.shape == (3, 3) and np.isfinite(f).all() and fm is not None and np.mean(fm) >= .5:
            self.f = f
        if h is not None and np.isfinite(h).all() and hm is not None and np.mean(hm) >= .5:
            self.h = h

    @property
    def available(self):
        return self.f is not None or self.h is not None

    def accept(self, p0, p1):
        valid = np.zeros(len(p0), dtype=bool)
        if self.f is not None:
            valid |= _epipolar_errors(self.f, p0, p1) <= self.config.max_epipolar_error
        if self.h is not None:
            valid |= _homography_errors(self.h, p0, p1) <= self.config.max_homography_error
        return valid


def predict_original_point(point, matches, geometry, config):
    """Local affine support predicts a query point; no match endpoint is returned."""
    finite = np.isfinite(matches.points0).all(axis=1) & np.isfinite(matches.points1).all(axis=1)
    good = finite & geometry.accept(matches.points0, matches.points1)
    distances = np.linalg.norm(matches.points0 - point, axis=1)
    indices = np.flatnonzero(good & (distances <= config.support_radius))
    indices = indices[np.argsort(distances[indices], kind='stable')[:config.support_max]]
    if len(indices) < config.support_min:
        return None, 'insufficient_support', len(indices)
    src = matches.points0[indices].astype(np.float32)
    dst = matches.points1[indices].astype(np.float32)
    cv2.setRNGSeed(20260909)
    affine, inliers = cv2.estimateAffine2D(src - point, dst, method=cv2.RANSAC,
        ransacReprojThreshold=config.affine_ransac_px, maxIters=2000,
        confidence=.99, refineIters=10)
    if affine is None or inliers is None or not np.isfinite(affine).all():
        return None, 'affine_failed', len(indices)
    keep = inliers.ravel().astype(bool)
    if np.sum(keep) < config.support_min or np.mean(keep) < config.affine_min_inlier_fraction:
        return None, 'mixed_motion_or_outliers', int(np.sum(keep))
    design = np.column_stack(((src[keep] - point) / config.support_radius, np.ones(np.sum(keep))))
    if np.linalg.cond(design) > config.affine_max_condition:
        return None, 'ill_conditioned_support', int(np.sum(keep))
    hull = cv2.convexHull(src[keep])
    if cv2.pointPolygonTest(hull, (float(point[0]), float(point[1])), False) < 0:
        return None, 'outside_support_hull', int(np.sum(keep))
    singular = np.linalg.svd(affine[:, :2], compute_uv=False)
    if np.linalg.det(affine[:, :2]) <= 0 or min(singular) < config.affine_min_scale or max(singular) > config.affine_max_scale:
        return None, 'affine_deformation', int(np.sum(keep))
    prediction = (src - point) @ affine[:, :2].T + affine[:, 2]
    if np.percentile(np.linalg.norm(prediction - dst, axis=1), 90) > config.affine_p90_px:
        return None, 'local_motion_inconsistent', int(np.sum(keep))
    return affine[:, 2].astype(np.float32), 'predicted', int(np.sum(keep))


def recover_same_frame(prev, cur, image_quality, lost_points, lost_ids, lost_ages,
                       ordinary, arm, matches=None, klt_config=None, config=None,
                       death_reasons=None):
    """Retry exactly one transition. C/L share all final validity checks."""
    if arm not in ('C', 'L'):
        raise ValueError('Recovery arm must be C or L')
    kc, rc = klt_config or KltConfig(), config or RecoveryConfig()
    old = np.asarray(lost_points, dtype=np.float32).reshape(-1, 2)
    ids = np.asarray(lost_ids, dtype=np.int64)
    if len(set(ids.tolist())) != len(ids) or set(ids.tolist()) & set(ordinary.ids.tolist()):
        raise ValueError('Lost and surviving identities must be unique and disjoint')
    events = [dict(track_id=int(tid), previous_x=float(pt[0]), previous_y=float(pt[1]),
                   previous_age=int(age), original_failure=(death_reasons or {}).get(int(tid), 'Unknown'),
                   attempted=False, accepted=False, reason='not_attempted', current_x='', current_y='',
                   predicted_x='', predicted_y='', support_count=0, fb_error='', ncc='')
              for tid, pt, age in zip(ids, old, lost_ages)]
    if not len(old):
        return TrackSet.empty(), events
    geometry = GeometryReference(ordinary, rc)
    if not geometry.available:
        for e in events:
            e['reason'] = 'no_common_geometry_reference'
        return TrackSet.empty(), events
    initial = old.copy()
    eligible = np.ones(len(old), dtype=bool)
    if arm == 'L':
        if matches is None:
            raise ValueError('L requires matches for this exact adjacent image pair')
        for i, point in enumerate(old):
            pred, reason, count = predict_original_point(point, matches, geometry, rc)
            events[i]['support_count'] = count
            events[i]['reason'] = reason
            if pred is None:
                eligible[i] = False
            else:
                initial[i] = pred
                events[i].update(predicted_x=float(pred[0]), predicted_y=float(pred[1]))
    ix = np.flatnonzero(eligible)
    if not len(ix):
        return TrackSet.empty(), events
    params = dict(winSize=(rc.win_size, rc.win_size), maxLevel=rc.max_level,
                  criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, rc.iterations, .01))
    p0 = old[ix].reshape(-1, 1, 2)
    p1, status, _ = cv2.calcOpticalFlowPyrLK(prev, cur, p0,
        initial[ix].reshape(-1, 1, 2).copy() if arm == 'L' else None,
        flags=cv2.OPTFLOW_USE_INITIAL_FLOW if arm == 'L' else 0, **params)
    for i in ix:
        events[i].update(attempted=True, reason='forward_fail')
    if p1 is None or status is None:
        return TrackSet.empty(), events
    # Reverse flow has no initial guess; it must return to the actual old point.
    back, backward, _ = cv2.calcOpticalFlowPyrLK(cur, prev, p1, None, **params)
    if back is None or backward is None:
        for i in ix:
            events[i]['reason'] = 'backward_fail'
        return TrackSet.empty(), events
    endpoints = p1.reshape(-1, 2)
    fb = np.linalg.norm(back.reshape(-1, 2) - old[ix], axis=1)
    finite = np.isfinite(endpoints).all(axis=1) & np.isfinite(fb)
    ncc = np.zeros(len(ix), dtype=np.float32)
    if np.any(finite):
        ncc[finite] = _patch_ncc(prev, cur, old[ix][finite], endpoints[finite], kc.patch_radius)
    borders = _in_border(endpoints, cur.shape, kc.border)
    geom = geometry.accept(old[ix], endpoints)
    occupied = ordinary.points.copy()
    selected = []
    for j, i in enumerate(ix):
        e = events[i]
        if finite[j]:
            e.update(current_x=float(endpoints[j, 0]), current_y=float(endpoints[j, 1]),
                     fb_error=float(fb[j]), ncc=float(ncc[j]))
        reason = ('forward_fail' if not status.ravel()[j] else
                  'backward_fail' if not backward.ravel()[j] else
                  'nonfinite' if not finite[j] else
                  'fb_fail' if fb[j] > kc.fb_threshold else
                  'ncc_fail' if ncc[j] < kc.min_ncc else
                  'border_fail' if not borders[j] else
                  'geometry_fail' if not geom[j] else
                  'identity_collision' if len(occupied) and np.any(np.linalg.norm(occupied-endpoints[j], axis=1) < rc.min_current_distance) else
                  'accepted')
        e['reason'] = reason
        if reason == 'accepted':
            e['accepted'] = True
            selected.append(j)
            occupied = np.vstack((occupied, endpoints[j]))
    if not selected:
        return TrackSet.empty(), events
    keep = np.asarray(selected)
    chosen = ix[keep]
    ages = np.asarray(lost_ages)[chosen] + 1
    texture = local_texture_scores(cur, endpoints[keep])
    # Exactly the ordinary KLT metadata principle, without a learned source bonus.
    quality = np.clip(image_quality.global_score * (.25+.75*texture)
        * (.20+.80*np.exp(-fb[keep]/max(kc.fb_threshold, 1e-3)))
        * (.30+.70*np.clip((ncc[keep]-kc.min_ncc)/max(1e-3, 1-kc.min_ncc), 0, 1))
        * (.50+.50*np.clip(ages.astype(np.float32)/20, 0, 1)), kc.q_min, 1).astype(np.float32)
    return TrackSet(ids=ids[chosen].copy(), prev_points=old[chosen].copy(),
        points=endpoints[keep].astype(np.float32), ages=ages.astype(np.int32),
        fb_errors=fb[keep].astype(np.float32), ncc_scores=ncc[keep],
        local_texture=texture.astype(np.float32), qualities=quality,
        sources=['klt']*len(keep)), events


class SameFrameRecoveryTracker(KltTracker):
    """Optional wrapper. Ordinary KLT and parent GFTT replenishment are reused."""
    def __init__(self, arm, matcher=None, config=None, recovery_config=None):
        super().__init__(config)
        if arm not in ('B', 'C', 'L'):
            raise ValueError('Unknown arm')
        self.arm, self.matcher = arm, matcher
        self.recovery_config = recovery_config or RecoveryConfig()
        self.last_recovery_events = []
        self.last_ordinary_tracks = TrackSet.empty()
        self.last_recovery_s = 0.0
        self._frame_index = None
        self._stamp_ns = None

    def process(self, image, image_quality, replenish=True, *, frame_index=None, stamp_ns=None):
        frame_index = (0 if self._frame_index is None else self._frame_index+1) if frame_index is None else frame_index
        if self._frame_index is not None and frame_index != self._frame_index+1:
            raise ValueError('Same-frame recovery requires every adjacent raw frame; no gap revival')
        if stamp_ns is not None and self._stamp_ns is not None and stamp_ns <= self._stamp_ns:
            raise ValueError('Image timestamps must increase strictly')
        self.last_recovery_events = []
        self.last_recovery_s = 0.0
        result = super().process(image, image_quality, replenish)
        self._frame_index, self._stamp_ns = frame_index, stamp_ns
        assert len(self.ids) <= self.config.max_features and len(set(self.ids)) == len(self.ids)
        return result

    def reset(self):
        super().reset()
        self.last_recovery_events = []
        self.last_ordinary_tracks = TrackSet.empty()
        self.last_recovery_s = 0.0
        self._frame_index = self._stamp_ns = None

    def _track_existing(self, prev, cur, image_quality):
        old_points, old_ids, old_ages = self.points.copy(), self.ids.copy(), self.ages.copy()
        ordinary = super()._track_existing(prev, cur, image_quality)
        self.last_ordinary_tracks = ordinary
        # Also captures complete forward-LK failure, where the legacy lost buffer
        # is not populated. The original tracker and its frozen behavior are untouched.
        lost = ~np.isin(old_ids, ordinary.ids)
        self.last_lost_prev_points = old_points[lost].copy()
        self.last_lost_ids = old_ids[lost].copy()
        self.last_lost_ages = old_ages[lost].copy()
        if self.arm == 'B' or not np.any(lost):
            return ordinary
        tick = time.perf_counter()
        matches = self.matcher.match(prev, cur) if self.arm == 'L' else None
        recovered, self.last_recovery_events = recover_same_frame(prev, cur, image_quality,
            self.last_lost_prev_points, self.last_lost_ids, self.last_lost_ages, ordinary,
            self.arm, matches=matches, klt_config=self.config, config=self.recovery_config,
            death_reasons=self.last_death_reasons)
        self.last_recovery_s = time.perf_counter()-tick
        combined = self._append_tracks(ordinary, recovered)
        assert np.array_equal(combined.points[:len(ordinary)], ordinary.points)
        self.points, self.ids, self.ages = combined.points.copy(), combined.ids.copy(), combined.ages.copy()
        for track_id in recovered.ids:
            self.last_death_reasons.pop(int(track_id), None)
        return combined
