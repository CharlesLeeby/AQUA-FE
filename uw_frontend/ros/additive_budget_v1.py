"""Independent causal private pools and additive publication, experiment v1.

No default frontend/exporter mutation. Source records precede public budgeting.
"""
from __future__ import annotations

from collections import Counter
import copy
from dataclasses import replace
import io
import math

import cv2
import numpy as np

from uw_frontend.tracking.klt_tracker import KltTracker, KltConfig, _in_border
from uw_frontend.tracking.track_state import TrackSet
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.ros import export_vins_features as ex

GEOMETRY = ex._SidecarGeometryConfig(True, True, 1.20, .006, 2.80,
                                    1.05, .03, .0015, .12, 16, True)
ID_BASE = 10_000_000


def serialized(msg):
    stream = io.BytesIO()
    msg.serialize(stream)
    return stream.getvalue()


def channels(msg):
    return {c.name: c.values for c in msg.channels}


def message_tracks(msg, previous):
    c = channels(msg)
    ids = np.asarray(c['id'], dtype=np.int64)
    pts = np.asarray(list(zip(c['p_u'], c['p_v'])), dtype=np.float32).reshape(-1, 2)
    keep = np.asarray([i for i, tid in enumerate(ids) if int(tid) in previous], dtype=int)
    return TrackSet(ids[keep], np.asarray([previous[int(ids[i])] for i in keep],
                    dtype=np.float32).reshape(-1, 2), pts[keep],
                    np.full(len(keep), 3, np.int32), np.zeros(len(keep), np.float32),
                    np.ones(len(keep), np.float32), np.ones(len(keep), np.float32),
                    np.ones(len(keep), np.float32), ['klt'] * len(keep))


def close(point, points, radius=18.):
    return bool(len(points) and np.any(np.linalg.norm(np.asarray(points)-point, axis=1) < radius))


class PrivatePool:
    """Source state does not observe L6/L-all decisions, IDs or residuals."""
    def __init__(self, matcher, source):
        self.matcher, self.source = matcher, source
        self.tracker = KltTracker(KltConfig(max_features=800))
        self.previous_image = None
        self.previous_output = {}
        self.counters = Counter()
        self.last_tracks = TrackSet.empty()

    def process(self, gray, generate):
        quality = score_image_quality(gray)
        tracks, _ = self.tracker.process(gray, quality, replenish=False)
        self.counters.update(self.tracker.last_death_reasons.values())
        if generate and self.previous_image is not None:
            matched = self.matcher.match(self.previous_image, gray)
            self.counters['generation_calls'] += 1
            self.counters['matcher_output'] += len(matched.points1)
            # Native source score ranks only seeds from this source and this pair.
            order = np.argsort(-np.asarray(matched.confidences), kind='stable')
            occupied = [p.copy() for p in tracks.points]
            added = []
            for j in order:
                p = np.asarray(matched.points1[j], dtype=np.float32)
                if not np.isfinite(p).all():
                    self.counters['seed_nonfinite'] += 1
                    continue
                if not _in_border(p.reshape(1,2), gray.shape, border=8)[0]:
                    self.counters['seed_boundary'] += 1
                    continue
                if close(p, occupied):
                    self.counters['seed_duplicate_private'] += 1
                    continue
                if len(added) >= 60:
                    self.counters['generator_seed_limit'] += 1
                    continue
                if len(occupied) >= 800:
                    self.counters['generator_pool_limit'] += 1
                    continue
                added.append(p)
                occupied.append(p)
            n = len(added)
            if n:
                pts = np.asarray(added, np.float32)
                t = self.tracker
                ids = np.arange(t.next_id, t.next_id+n, dtype=np.int64)
                t.next_id += n
                t.points = np.vstack([t.points, pts]).astype(np.float32)
                t.ids = np.concatenate([t.ids, ids])
                t.ages = np.concatenate([t.ages, np.ones(n, np.int32)])
                self.counters['seeds_created'] += n
        self.previous_image = gray
        self.last_tracks = tracks
        self.counters['processed_frames'] += 1
        self.counters['peak_pool'] = max(self.counters['peak_pool'], len(self.tracker.ids))

    def eligible(self, baseline, previous_baseline, camera, stamp_ns, frame):
        tracks = self.last_tracks
        reasons = Counter()
        c = channels(baseline)
        bpoints = np.asarray(list(zip(c['p_u'], c['p_v'])), np.float32).reshape(-1,2)
        occupied = [p.copy() for p in bpoints]
        keep = []
        for i in np.argsort(tracks.ids):
            tid = int(tracks.ids[i])
            if int(tracks.ages[i]) < 3:
                reasons['confirmation_age'] += 1
            elif tid not in self.previous_output:
                reasons['source_history_missing'] += 1
            elif not np.isfinite([*tracks.points[i], tracks.qualities[i],
                                  tracks.fb_errors[i], tracks.ncc_scores[i]]).all():
                reasons['nonfinite'] += 1
            elif float(tracks.qualities[i]) < .10:
                reasons['quality'] += 1
            elif float(tracks.fb_errors[i]) > 1.:
                reasons['FB'] += 1
            elif float(tracks.ncc_scores[i]) < .65:
                reasons['NCC'] += 1
            elif close(tracks.points[i], occupied):
                reasons['duplicate_KLT_or_prior_candidate'] += 1
            else:
                keep.append(int(i))
                occupied.append(tracks.points[i].copy())
        candidate = ex._subset_tracks_by_indices(tracks, np.asarray(keep, int))
        if len(candidate):
            candidate.prev_points = np.asarray([self.previous_output[int(t)] for t in candidate.ids], np.float32)
            candidate.sources = [('xfeat_confirmed' if self.source == 'xfeat'
                                  else 'classical_gftt_confirmed')] * len(candidate)
        reference = message_tracks(baseline, previous_baseline)
        combined = KltTracker._append_tracks(reference, candidate)
        refmask = np.arange(len(combined)) < len(reference)
        # Fixed RNG per frame: neither arm order nor previous RANSAC consumes it.
        cv2.setRNGSeed(frame)
        accepted, geom_reason = ex._apply_sidecar_geometry_gate(
            combined, refmask, ~refmask, camera, GEOMETRY)
        selected = ex._subset_tracks_by_indices(combined, np.flatnonzero(accepted))
        reasons['geometry'] += len(candidate)-len(selected)
        observations = []
        norm = ex._pixels_to_normalized(selected.points, camera)
        q = ex._backend_reliability(selected, mode='vins_safe', floor=.8, alpha=.65)
        for i, tid in enumerate(selected.ids):
            observations.append(dict(source_id=int(tid), point=selected.points[i].tolist(),
                normalized=norm[i].tolist(), quality=float(q[i]), raw_quality=float(selected.qualities[i]),
                age=int(selected.ages[i]), fb=float(selected.fb_errors[i]),
                ncc=float(selected.ncc_scores[i]), source=self.source))
        self.previous_output = {int(t):p.copy() for t,p in zip(tracks.ids, tracks.points)}
        self.counters.update({'eligible_observations':len(observations)})
        return dict(frame=frame, stamp_ns=stamp_ns, source=self.source,
                    observations=observations, rejected=dict(reasons),
                    geometry_reason=geom_reason, counters=dict(self.counters))


class Publisher:
    def __init__(self, limit=None):
        self.limit = limit
        self.active = {}
        self.next_id = ID_BASE
        self.previous_ns = None
        self.lengths = Counter()
        self.events = []

    def publish(self, baseline, record):
        stamp_ns = baseline.header.stamp.to_nsec()
        if stamp_ns != record['stamp_ns'] or (self.previous_ns is not None and stamp_ns <= self.previous_ns):
            raise ValueError('nonmonotone or mismatched source timestamp')
        observations = record['observations']
        ids = [r['source_id'] for r in observations]
        if len(set(ids)) != len(ids):
            raise ValueError('duplicate source identity')
        eligible = {r['source_id']:r for r in observations}
        continued = [sid for sid in self.active if sid in eligible]
        new = sorted(set(eligible)-set(continued))
        selected = continued+new
        if self.limit is not None:
            selected = selected[:self.limit]
        previous = self.active
        self.active = {}
        msg = copy.deepcopy(baseline)
        base_ids = set(int(v) for v in channels(baseline)['id'])
        for sid in selected:
            o = eligible[sid]
            if sid in previous:
                public_id, prevnorm = previous[sid]
                dt = (stamp_ns-self.previous_ns)*1e-9
                velocity = (np.asarray(o['normalized'])-prevnorm)/dt
                event = 'continue'
            else:
                public_id = self.next_id
                self.next_id += 1
                velocity = [0.,0.]
                event = 'admit'
            if public_id in base_ids or public_id >= 2**24 or int(np.float32(public_id)) != public_id:
                raise ValueError('public identity collision or float32 encoding loss')
            from geometry_msgs.msg import Point32
            msg.points.append(Point32(*o['normalized'],1.))
            values = dict(id=public_id,camera_id=0,p_u=o['point'][0],p_v=o['point'][1],
                          velocity_x=velocity[0],velocity_y=velocity[1],gx=0.,gy=0.,gz=0.,
                          quality=o['quality'],sigma=1/math.sqrt(o['quality']),
                          source_code=ex._source_code('xfeat_confirmed') if o['source']=='xfeat' else 0,
                          is_learned=1 if o['source']=='xfeat' else 0)
            for channel in msg.channels:
                if channel.name not in values:
                    raise ValueError('unsupported baseline channel '+channel.name)
                channel.values = list(channel.values)+[float(values[channel.name])]
            self.active[sid] = (public_id,np.asarray(o['normalized']))
            self.lengths[public_id] += 1
            self.events.append(dict(frame=record['frame'],stamp_ns=stamp_ns,source_id=sid,
                public_id=public_id,event=event,reason='valid',age=o['age']))
        for sid, (pid, _) in previous.items():
            if sid not in self.active:
                self.events.append(dict(frame=record['frame'],stamp_ns=stamp_ns,source_id=sid,
                    public_id=pid,event='terminate',reason='source_missing_or_invalid',age='Unknown'))
        for sid in set(eligible)-set(selected):
            self.events.append(dict(frame=record['frame'],stamp_ns=stamp_ns,source_id=sid,
                public_id='',event='reject',reason='L6_quantity',age=eligible[sid]['age']))
        self.previous_ns = stamp_ns
        assert_backbone(baseline,msg)
        return msg, selected


def assert_backbone(baseline, augmented):
    n = len(baseline.points)
    if len(augmented.points) < n:
        raise ValueError('KLT observation removed')
    stripped = copy.deepcopy(augmented)
    stripped.points = stripped.points[:n]
    for c in stripped.channels:
        c.values = c.values[:n]
    if serialized(stripped) != serialized(baseline):
        raise ValueError('KLT message differs after stripping additions')
    c = channels(augmented)
    keys = list(zip(c['camera_id'],c['id']))
    if len(set(keys)) != len(keys):
        raise ValueError('duplicate camera/public ID')
    for channel in augmented.channels:
        if len(channel.values) != len(augmented.points) or not np.isfinite(channel.values).all():
            raise ValueError('invalid channel shape or nonfinite')
