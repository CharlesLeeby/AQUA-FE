#!/usr/bin/env python3
"""One frozen frontend correctness comparison; never launches VINS."""
import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from uw_frontend.matchers.xfeat_adapter import XFeatMatcher
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.ros.export_vins_features import _image_msg_to_gray, _preprocess_gray
from uw_frontend.tracking.klt_tracker import KltConfig, KltTracker, _in_border
from uw_frontend.tracking.same_frame_recovery import SameFrameRecoveryTracker, RecoveryConfig, recover_same_frame, subset

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / 'papers/frontend_learned_klt_recovery_v1'


def write_csv(path, rows, extra_fields=()):
    fields = list(dict.fromkeys([k for r in rows for k in r] + list(extra_fields)))
    with Path(path).open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator='\n')
        w.writeheader()
        w.writerows(rows)


def save(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2)
        f.write('\n')


class PairCache:
    def __init__(self, matcher):
        self.matcher = matcher
        self.previous = self.current = self.result = None
        self.seconds = 0.
        self.calls = 0

    def begin(self, previous, current):
        self.previous, self.current, self.result = previous, current, None
        self.seconds = 0.
        self.calls = 0

    def match(self, previous, current):
        if not np.array_equal(previous, self.previous) or not np.array_equal(current, self.current):
            raise ValueError('Shared matcher requested for a different image transition')
        if self.result is None:
            t = time.perf_counter()
            self.result = self.matcher.match(previous, current)
            self.seconds = time.perf_counter()-t
            self.calls = 1
        return self.result


def load_window(window):
    import rosbag
    from cv_bridge import CvBridge
    bridge = CvBridge()
    raw, gray, qualities, stamps = [], [], [], []
    preprocessing_s = 0.
    with rosbag.Bag(window['input_bag']) as bag:
        for i, (_, msg, _) in enumerate(bag.read_messages(topics=[window['image_topic']])):
            if i >= window['raw_count']:
                break
            image = _image_msg_to_gray(bridge, msg)
            raw.append(image)
            t = time.perf_counter()
            gray.append(_preprocess_gray(image, 'adaptive_clahe'))
            qualities.append(score_image_quality(gray[-1]))
            preprocessing_s += time.perf_counter()-t
            stamps.append(msg.header.stamp.to_nsec())
    assert len(gray) == 200 and stamps[0] == window['first_stamp_ns'] and stamps[-1] == window['last_stamp_ns']
    assert all(x < y for x, y in zip(stamps, stamps[1:]))
    return raw, gray, qualities, stamps, preprocessing_s


def controlled_pair(image, case, config, index):
    h, w = image.shape
    transform = cv2.getRotationMatrix2D((w/2., h/2.), case['angle'], case['scale'])
    transform[:, 2] += [case['dx'], case['dy']]
    current = cv2.warpAffine(image, transform, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    occ = None
    if case['illumination']:
        x = np.linspace(0., 1., w)[None, :]
        y = np.linspace(0., 1., h)[:, None]
        photo = config['controlled_illumination']
        current = np.clip(current*(photo['gain_min']+(photo['gain_max']-photo['gain_min'])*x)
                          + photo['bias_amplitude']*np.sin(2*np.pi*y), 0, 255).astype(np.uint8)
        current = cv2.GaussianBlur(current, (0, 0), photo['gaussian_sigma'])
    if case['occlusion']:
        x0, y0, x1, y1 = config['occlusion_rectangle_fraction']
        occ = [int(x0*w), int(y0*h), int(x1*w), int(y1*h)]
        rng = np.random.RandomState(config['seed']+index)
        current[occ[1]:occ[3], occ[0]:occ[2]] = rng.randint(32, 224, (occ[3]-occ[1], occ[2]-occ[0]), dtype=np.uint8)
    return current, transform, occ


def controlled(window, raw, matcher, config, runtime, events, summaries):
    point_rows = []
    seq = window['sequence']
    for offset in config['controlled_base_offsets']:
        for ci, case in enumerate(config['controlled_cases']):
            image = raw[offset]
            current, transform, occlusion = controlled_pair(image, case, config, offset*10+ci)
            previous = _preprocess_gray(image, 'adaptive_clahe')
            current = _preprocess_gray(current, 'adaptive_clahe')
            q = score_image_quality(current)
            baseline = SameFrameRecoveryTracker('B', config=KltConfig(**config['klt']))
            initial, _ = baseline.process(previous, score_image_quality(previous), frame_index=0)
            t = time.perf_counter()
            tracked, _ = baseline.process(current, q, replenish=False, frame_index=1)
            b_seconds = time.perf_counter()-t
            truth = initial.points @ transform[:, :2].T + transform[:, 2]
            visible = _in_border(truth, current.shape, config['klt']['border'])
            if occlusion:
                x0, y0, x1, y1 = occlusion
                guard = config['occlusion_patch_guard_px']
                visible &= ~((truth[:, 0] >= x0-guard) & (truth[:, 0] < x1+guard)
                             & (truth[:, 1] >= y0-guard) & (truth[:, 1] < y1+guard))
            truth_by_id = {int(tid): (pt, bool(v)) for tid, pt, v in zip(initial.ids, truth, visible)}
            t = time.perf_counter()
            match = matcher.match(previous, current) if len(baseline.last_lost_ids) else None
            match_s = time.perf_counter()-t
            for arm in ['B', 'C', 'L']:
                t = time.perf_counter()
                if arm == 'B':
                    accepted = tracked
                    arm_events = []
                    input_ids = initial.ids
                else:
                    accepted, arm_events = recover_same_frame(previous, current, q,
                        baseline.last_lost_prev_points, baseline.last_lost_ids,
                        baseline.last_lost_ages, baseline.last_ordinary_tracks, arm, match,
                        KltConfig(**config['klt']), RecoveryConfig(**config['recovery']), baseline.last_death_reasons)
                    input_ids = baseline.last_lost_ids
                seconds = b_seconds if arm == 'B' else time.perf_counter()-t + (match_s if arm == 'L' else 0.)
                visible_n = sum(truth_by_id[int(tid)][1] for tid in input_ids)
                outcomes = {}
                errors = []
                for tid, point in zip(accepted.ids, accepted.points):
                    actual, vis = truth_by_id[int(tid)]
                    error = float(np.linalg.norm(point-actual))
                    correct = vis and error <= config['correct_pixel_tolerance']
                    outcomes[int(tid)] = (error, correct, vis)
                    errors.append(error)
                    point_rows.append(dict(sequence=seq,base_offset=offset,case=case['name'],arm=arm,
                        track_id=int(tid),x=float(point[0]),y=float(point[1]),truth_x=float(actual[0]),truth_y=float(actual[1]),
                        visible=vis,error_px=error,correct=correct))
                for e in arm_events:
                    actual, vis = truth_by_id[e['track_id']]
                    error, correct, _ = outcomes.get(e['track_id'], ('', False, vis))
                    e.update(stage='controlled',sequence=seq,raw_index=window['raw_start']+offset,
                        stamp_ns='',case=case['name'],arm=arm,truth_x=float(actual[0]),truth_y=float(actual[1]),
                        truth_visible=vis,oracle_error_px=error,correct_recovery=correct,
                        continuation_raw_observations='',continuation_output_observations='',termination_reason='single_pair_control')
                    events.append(e)
                correct_n = sum(v[1] for v in outcomes.values())
                summaries.append(dict(stage='controlled',sequence=seq,case=case['name'],base_offset=offset,arm=arm,
                    input_points=len(input_ids),visible_input_points=visible_n,invisible_input_points=len(input_ids)-visible_n,
                    accepted=len(accepted),correct=correct_n,wrong_accepted=len(accepted)-correct_n,
                    invisible_accepted=sum(not v[2] for v in outcomes.values()),
                    accepted_error_median_px=float(np.median(errors)) if errors else '',
                    accepted_error_p95_px=float(np.percentile(errors,95)) if errors else '',
                    wall_s=seconds,xfeat_matching_s=match_s if arm=='L' else 0.))
            print('CONTROLLED',seq,offset,case['name'],'failed',len(baseline.last_lost_ids),flush=True)
    write_csv(runtime/(seq+'_controlled_accepted_points.csv'), point_rows)


class Continuation:
    """Offline ordinary-LK continuation of paired endpoints; never used for admission."""
    def __init__(self, klt):
        self.tracker = KltTracker(klt)
        self.next_episode = 0
        self.rows = {}

    def advance(self, previous, current, q, published, raw_index):
        tr = self.tracker
        before = tr.ids.copy()
        kept = tr._track_existing(previous, current, q)
        dead = set(before)-set(kept.ids)
        for tid in dead:
            row = self.rows[int(tid)]
            row['termination_reason'] = tr.last_death_reasons.get(int(tid),'Unknown')
            row['termination_raw_index'] = raw_index
        for tid in kept.ids:
            row = self.rows[int(tid)]
            row['continuation_raw_observations'] += 1
            row['continuation_output_observations'] += int(published)

    def add(self, row, point, published):
        tr = self.tracker
        tid = self.next_episode
        self.next_episode += 1
        self.rows[tid] = row
        row.update(continuation_raw_observations=1,continuation_output_observations=int(published),
                   termination_reason='right_censored_at_window_end',continuation_scope='offline ordinary-LK from paired endpoint; not evolving-arm publication')
        tr.points = np.vstack((tr.points,np.float32(point)))
        tr.ids = np.append(tr.ids,tid).astype(np.int64)
        tr.ages = np.append(tr.ages,1).astype(np.int32)


def natural(window, images, qualities, stamps, matcher, config, runtime, events, summaries):
    seq = window['sequence']
    shared = PairCache(matcher)
    trackers = {arm:SameFrameRecoveryTracker(arm, shared if arm=='L' else None,
        KltConfig(**config['klt']),RecoveryConfig(**config['recovery'])) for arm in ['B','C','L']}
    continuation = {arm:Continuation(KltConfig(**config['klt'])) for arm in ['C','L']}
    active_recoveries = {arm:defaultdict(list) for arm in ['C','L']}
    previous_public = {arm:set() for arm in trackers}
    ended_public = {arm:set() for arm in trackers}
    frame_rows, output_rows, pair_rows = [], [], []
    for i, (image,q,stamp) in enumerate(zip(images,qualities,stamps)):
        publish = i%config['public_every_n']==config['public_frame_offset']
        shared.begin(images[i-1] if i else None,image)
        if i:
            for c in continuation.values():
                c.advance(images[i-1],image,q,publish,window['raw_start']+i)
        t = time.perf_counter()
        b, diag = trackers['B'].process(image,q,frame_index=i,stamp_ns=stamp)
        timings = {'B':time.perf_counter()-t}
        current_tracks = {'B':b}
        if i:
            bt = trackers['B']
            paired = {}
            for arm in ['C','L']:
                match = shared.match(images[i-1],image) if arm=='L' and len(bt.last_lost_ids) else None
                t = time.perf_counter()
                recovered, ee = recover_same_frame(images[i-1],image,q,bt.last_lost_prev_points,
                    bt.last_lost_ids,bt.last_lost_ages,bt.last_ordinary_tracks,arm,match,
                    KltConfig(**config['klt']),RecoveryConfig(**config['recovery']),bt.last_death_reasons)
                paired[arm] = {e['track_id']:e for e in ee}
                point_map = dict(zip(recovered.ids,recovered.points))
                for e in ee:
                    e.update(stage='natural_paired',sequence=seq,raw_index=window['raw_start']+i,stamp_ns=stamp,
                        case='real_adjacent',arm=arm,visual_identity='Unknown',correct_recovery='Unknown',
                        continuation_raw_observations=0,continuation_output_observations=0,
                        termination_reason='not_recovered')
                    if e['accepted']:
                        continuation[arm].add(e,point_map[e['track_id']],publish)
                    events.append(e)
                    pair_rows.append(e)
                frame_rows.append(dict(sequence=seq,raw_index=window['raw_start']+i,stage='paired_retry',arm=arm,
                    failed=len(ee),accepted=len(recovered),wall_s=time.perf_counter()-t))
            assert paired['C'].keys()==paired['L'].keys()
            for tid in paired['C']:
                cc,ll=paired['C'][tid],paired['L'][tid]
                category=('both_recovered' if cc['accepted'] and ll['accepted'] else 'C_only' if cc['accepted'] else 'L_only' if ll['accepted'] else 'both_failed')
                cc['paired_category']=ll['paired_category']=category
        for arm in ['C','L']:
            tracker=trackers[arm]
            t=time.perf_counter()
            tr,diag=tracker.process(image,q,frame_index=i,stamp_ns=stamp)
            timings[arm]=time.perf_counter()-t
            current_tracks[arm]=tr
            # Publication lifetimes come from each actual evolving 350-cap stream.
            live=set(int(x) for x in tr.ids)
            for tid in list(active_recoveries[arm]):
                for row in active_recoveries[arm][tid]:
                    if tid in live:
                        row['continuation_raw_observations']+=1
                        row['continuation_output_observations']+=int(publish)
                    else:
                        row['termination_reason']=tracker.last_death_reasons.get(tid,'Unknown')
                        row['termination_raw_index']=window['raw_start']+i
                if tid not in live:
                    del active_recoveries[arm][tid]
            for e in tracker.last_recovery_events:
                if e['accepted']:
                    row=dict(e,stage='natural_stream',sequence=seq,raw_index=window['raw_start']+i,
                        stamp_ns=stamp,case='real_adjacent',arm=arm,visual_identity='Unknown',correct_recovery='Unknown',
                        continuation_raw_observations=1,continuation_output_observations=int(publish),
                        continuation_scope='actual evolving-arm output stream',termination_reason='right_censored_at_window_end')
                    active_recoveries[arm][e['track_id']].append(row)
                    events.append(row)
        if i==0:
            for arm in ['C','L']:
                np.testing.assert_array_equal(current_tracks[arm].ids,b.ids)
                np.testing.assert_array_equal(current_tracks[arm].points,b.points)
        for arm,tr in current_tracks.items():
            frame_rows.append(dict(sequence=seq,raw_index=window['raw_start']+i,stage='evolving_stream',arm=arm,
                features=len(tr),births=int(np.sum(tr.ages==1)),failed=len(trackers[arm].last_lost_ids),
                accepted=sum(e['accepted'] for e in trackers[arm].last_recovery_events),
                wall_s=timings[arm],recovery_s=trackers[arm].last_recovery_s,
                shared_xfeat_s=shared.seconds if arm=='L' else 0.,shared_xfeat_calls=shared.calls if arm=='L' else 0))
            if publish:
                ids=set(int(x) for x in tr.ids)
                assert not ids & ended_public[arm], 'ID revived after a public gap'
                ended_public[arm] |= previous_public[arm]-ids
                previous_public[arm]=ids
                for tid,point,age in zip(tr.ids,tr.points,tr.ages):
                    output_rows.append(dict(sequence=seq,arm=arm,raw_index=window['raw_start']+i,stamp_ns=stamp,
                        track_id=int(tid),x=float(point[0]),y=float(point[1]),age=int(age)))
        if i%25==0:
            print('NATURAL',seq,i,{arm:len(t.ids) for arm,t in trackers.items()},flush=True)
    for arm in ['C','L']:
        pp=[r for r in pair_rows if r['arm']==arm]
        ss=[r for r in events if r['stage']=='natural_stream' and r['sequence']==seq and r['arm']==arm]
        for stage,rr in [('natural_paired',pp),('natural_stream',ss)]:
            accepted=[r for r in rr if r['accepted']]
            denominator = len(rr) if stage=='natural_paired' else sum(r['failed'] for r in frame_rows if r['stage']=='evolving_stream' and r['arm']==arm)
            summaries.append(dict(stage=stage,sequence=seq,case='real_adjacent',arm=arm,input_points=denominator,
                accepted=len(accepted),correct='Unknown',wrong_accepted='Unknown',
                chains_ge4_outputs=sum(r['continuation_output_observations']>=4 for r in accepted),
                continuation_outputs_median=float(np.median([r['continuation_output_observations'] for r in accepted])) if accepted else 0,
                continuation_outputs_max=max([r['continuation_output_observations'] for r in accepted] or [0])))
    write_csv(runtime/(seq+'_natural_frames.csv'),frame_rows)
    write_csv(runtime/(seq+'_actual_output_tracks.csv'),output_rows)
    return pair_rows


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--sequence',choices=['A02','A08','H02'],required=True)
    args=parser.parse_args()
    config=json.loads((PAPER/'input_manifest.json').read_text())
    runtime=Path(config['runtime'])/args.sequence
    runtime.mkdir(exist_ok=False)
    cv2.setNumThreads(1)
    np.random.seed(config['seed'])
    import torch
    torch.set_num_threads(1)
    torch.manual_seed(config['seed'])
    torch.backends.cudnn.benchmark=False
    matcher=XFeatMatcher(**config['xfeat'])
    w=next(x for x in config['windows'] if x['sequence']==args.sequence)
    raw,images,qualities,stamps,preprocessing_s=load_window(w)
    events,summaries=[],[]
    started=time.perf_counter()
    controlled(w,raw,matcher,config,runtime,events,summaries)
    write_csv(runtime/'controlled_events_checkpoint.csv',events)
    write_csv(runtime/'controlled_results_checkpoint.csv',summaries)
    try:
        natural(w,images,qualities,stamps,matcher,config,runtime,events,summaries)
    except Exception as error:
        write_csv(runtime/'partial_recovery_events.csv',events)
        write_csv(runtime/'partial_frontend_results.csv',summaries)
        save(runtime/'failure.json',dict(status='FAILED',error=repr(error)))
        raise
    write_csv(runtime/'recovery_events.csv',events)
    write_csv(runtime/'frontend_results.csv',summaries)
    save(runtime/'completion.json',dict(status='COMPLETE',sequence=args.sequence,raw_frames=len(images),
        preprocessing_s=preprocessing_s,experiment_wall_s=time.perf_counter()-started,
        matcher_device=str(matcher._model.dev),torch=torch.__version__,opencv=cv2.__version__,
        protocol_manifest_sha256=hashlib.sha256((PAPER/'input_manifest.json').read_bytes()).hexdigest(),
        runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        module_sha256=hashlib.sha256((ROOT/'uw_frontend/tracking/same_frame_recovery.py').read_bytes()).hexdigest()))
    print('FRONTEND_SEQUENCE_COMPLETE',args.sequence,flush=True)


if __name__=='__main__':
    main()
