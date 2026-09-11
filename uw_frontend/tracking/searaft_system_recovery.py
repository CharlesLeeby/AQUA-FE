"""One same-frame C -> SEA-RAFT recovery path; ordinary KLT stays unchanged."""
import time
import numpy as np
from uw_frontend.quality.image_quality import local_texture_scores
from uw_frontend.tracking.klt_tracker import KltTracker
from uw_frontend.tracking.track_state import TrackSet
from uw_frontend.tracking.correspondence_evidence import check_correspondence_evidence
from uw_frontend.matchers.searaft_points import common_mask
from searaft_screening_measurements import strong_lk


def recovery_tracks(points, ids, ages, predicted, fb, ncc, accepted, cur, quality, kc):
    ix = np.flatnonzero(accepted)
    if not len(ix):
        return TrackSet.empty()
    age = ages[ix]+1
    texture = local_texture_scores(cur, predicted[ix])
    # Unchanged KLT recovery metadata formula from same_frame_recovery.py.
    q = np.clip(quality.global_score*(.25+.75*texture)
        *(.20+.80*np.exp(-fb[ix]/max(kc.fb_threshold,1e-3)))
        *(.30+.70*np.clip((ncc[ix]-kc.min_ncc)/max(1e-3,1-kc.min_ncc),0,1))
        *(.50+.50*np.clip(age.astype(np.float32)/20,0,1)),kc.q_min,1).astype(np.float32)
    return TrackSet(ids=ids[ix].copy(),prev_points=points[ix].copy(),points=predicted[ix].astype(np.float32),
        ages=age.astype(np.int32),fb_errors=fb[ix].astype(np.float32),ncc_scores=ncc[ix].astype(np.float32),
        local_texture=texture.astype(np.float32),qualities=q,sources=['klt']*len(ix))


class SeaRaftSystemTracker(KltTracker):
    def __init__(self, arm, config, predictor=None):
        super().__init__(config)
        if arm not in ('B','C','R','D'):
            raise ValueError(arm)
        self.arm, self.predictor = arm, predictor
        self.raw_previous = self.raw_current = None
        self.frame_index = -1
        self.stamp_ns = None
        self.events = []
        self.frame_stats = {}

    def process_raw(self, raw, processed, quality, frame_index, stamp_ns):
        if frame_index != self.frame_index+1 or (self.stamp_ns is not None and stamp_ns <= self.stamp_ns):
            raise ValueError('Recovery requires adjacent raw frames and strictly increasing stamps')
        self.raw_current = raw
        self.events = []
        self.frame_stats = dict(ordinary_failed=0,C_recovered=0,S_attempted=0,S_recovered=0,C_seconds=0.,S_seconds=0.,strong_lk_calls=0)
        result = super().process(processed,quality)
        self.raw_previous = raw
        self.frame_index, self.stamp_ns = frame_index, stamp_ns
        assert len(self.ids)<=350 and len(set(self.ids))==len(self.ids)
        return result

    def _track_existing(self, previous, current, quality):
        old, ids, ages = self.points.copy(),self.ids.copy(),self.ages.copy()
        ordinary = super()._track_existing(previous,current,quality)
        lost = ~np.isin(ids,ordinary.ids)
        self.frame_stats['ordinary_failed'] = int(lost.sum())
        if self.arm=='B' or not np.any(lost):
            return ordinary
        p, ti, age = old[lost],ids[lost],ages[lost]
        ca = np.zeros(len(p),dtype=bool)
        combined = ordinary
        if self.arm!='D':
            cx, cf, seconds = strong_lk(previous,current,p,np.ones(2))
            ce = check_correspondence_evidence(self.raw_previous,self.raw_current,p,cx)
            ca = common_mask(p,cx,cf,current.shape)&ce['evidence_accepted']
            recovered = recovery_tracks(p,ti,age,cx,cf,ce['ncc'],ca,current,quality,self.config)
            self.frame_stats.update(C_recovered=len(recovered),C_seconds=seconds)
            for j in np.flatnonzero(ca):
                self.events.append(dict(track_id=int(ti[j]),source='C',previous_x=float(p[j,0]),previous_y=float(p[j,1]),
                    x=float(cx[j,0]),y=float(cx[j,1]),fb=float(cf[j]),ncc=float(ce['ncc'][j]),physical_correctness='Unknown'))
            combined = self._append_tracks(ordinary,recovered)
            self.frame_stats['strong_lk_calls'] = 1
        if self.arm in ('R','D') and np.any(~ca):
            remain = ~ca
            tick = time.perf_counter()
            s = self.predictor(self.raw_previous,self.raw_current,p[remain])
            evidence = check_correspondence_evidence(self.raw_previous,self.raw_current,p[remain],s['points'])
            accepted = common_mask(p[remain],s['points'],s['fb_error'],current.shape)&evidence['evidence_accepted']
            restored = recovery_tracks(p[remain],ti[remain],age[remain],s['points'],s['fb_error'],evidence['ncc'],accepted,current,quality,self.config)
            self.frame_stats.update(S_attempted=int(remain.sum()),S_recovered=len(restored),S_seconds=time.perf_counter()-tick)
            for j in np.flatnonzero(accepted):
                self.events.append(dict(track_id=int(ti[remain][j]),source='S',previous_x=float(p[remain][j,0]),previous_y=float(p[remain][j,1]),
                    x=float(s['points'][j,0]),y=float(s['points'][j,1]),fb=float(s['fb_error'][j]),ncc=float(evidence['ncc'][j]),physical_correctness='Unknown'))
            before = combined
            combined = self._append_tracks(combined,restored)
            assert np.array_equal(combined.points[:len(before)],before.points)
        assert np.array_equal(combined.points[:len(ordinary)],ordinary.points)
        assert set(combined.ids).issubset(set(ids))
        self.points,self.ids,self.ages=combined.points.copy(),combined.ids.copy(),combined.ages.copy()
        for e in self.events:
            self.last_death_reasons.pop(e['track_id'],None)
        return combined
