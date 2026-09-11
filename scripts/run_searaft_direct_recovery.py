#!/usr/bin/env python3
"""D ablation adapter over the existing causal exporter and frozen replay."""
import argparse,csv,fcntl,hashlib,json,time
from pathlib import Path
import numpy as np
import run_searaft_system_probe as shared
from run_additive_budget_v1 import sha,save

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_searaft_direct_recovery_v1'
OLD_PAPER=ROOT/'papers/frontend_searaft_system_probe_v1'
RT=shared.STORE/'frontend_searaft_direct_recovery_v1'
OLD_RT=shared.STORE/'frontend_searaft_system_probe_v1'
BASE_COMMIT='1138fab635910d3e1c34d57f99dab84c6ff8e9f5'


def freeze():
    import rosbag
    RT.mkdir(exist_ok=False);(RT/'tmp').mkdir()
    manifest=json.loads((OLD_PAPER/'input_manifest.json').read_text())
    timelines={};identities={}
    for w in manifest['windows']:
        expected=w.get('input_bag_sha256')
        if expected is None:expected=json.loads((Path(w['input_bag']).parent/'receipt.json').read_text())['input_bag_sha256']
        assert sha(w['input_bag'])==expected
        stamps=[]
        with rosbag.Bag(w['input_bag']) as bag:
            for i,(_,m,_) in enumerate(bag.read_messages(topics=[w['image_topic']])):
                if i==900:break
                stamps.append(m.header.stamp.to_nsec())
        assert len(stamps)==900 and stamps[0]==w['first_stamp_ns'] and stamps[-1]==w['last_stamp_ns']
        assert all(a<b for a,b in zip(stamps,stamps[1:]))
        timelines[w['sequence']]=stamps;identities[w['sequence']]=dict(input_bag=w['input_bag'],sha256=expected)
    save(RT/'raw_timestamps.json',timelines)
    save(PAPER/'cache_identity.json',dict(base_commit=BASE_COMMIT,inputs=identities,old_runtime=str(OLD_RT),
        model_loading_sha256=sha(OLD_PAPER/'model_loading.json'),coordinates='original raw pixels',preprocessing='raw mono8 repeated to RGB; official scale -1',
        cache_rule='same frozen input bag and adjacent raw stamps; exact coordinate key, no ID or spatial-neighbor approximation'))
    manifest['baseline_reuse']='Fresh B and D backend; map identical D/B input only.'
    save(PAPER/'input_manifest.json',manifest)
    save(PAPER/'source_and_backend_lock.json',dict(windows=manifest['windows']))
    lock=json.loads((OLD_PAPER/'backend_execution_lock_v2.json').read_text());lock['ros_port']=12741
    lock['source_lock_sha256']=sha(PAPER/'source_and_backend_lock.json')
    save(PAPER/'backend_execution_lock_v2.json',lock)
    (PAPER/'evaluation_lock.json').write_bytes((OLD_PAPER/'evaluation_lock.json').read_bytes())
    print('DIRECT_INPUT_FROZEN',flush=True)


class DirectPredictor(shared.Predictor):
    def __init__(self,cache_only=False):
        if cache_only:raise ValueError('Explicit cache repair must not silently start inference')
        super().__init__(False)
        self.timeline=json.loads((RT/'raw_timestamps.json').read_text())
        self.old_timing={(r['sequence'],int(r['raw_index'])):r for r in csv.DictReader((OLD_RT/'network_timing.csv').open())}
        self.seen=set();self.model_identity=sha(OLD_PAPER/'model_loading.json')

    def __call__(self,previous,current,points):
        tick=time.perf_counter();key=(self.sequence,self.raw_index)
        assert key not in self.seen and 1<=self.raw_index<=899
        self.seen.add(key);assert len(self.seen)<=1798
        stamps=self.timeline[self.sequence];assert self.stamp_ns==stamps[self.raw_index]
        # The old cache's image identity follows the verified immutable input
        # bag and adjacent raw index/stamp, not a guessed nearest feature ID.
        lookup={}
        oldpath=OLD_RT/'network'/self.sequence/(str(self.raw_index)+'.npz')
        if oldpath.exists():
            assert int(self.old_timing[key]['stamp_ns'])==self.stamp_ns
            with np.load(oldpath) as old:
                for q,p,fb in zip(old['previous_points'],old['predicted_points'],old['fb_error']):lookup[tuple(q)]=(p.copy(),float(fb))
        found=[]
        for q in points:
            value=lookup.get(tuple(q))
            if value is None:
                r=self.old.get((self.sequence,self.raw_index,self.stamp_ns,float(q[0]),float(q[1])))
                if r is not None:value=(np.array([float(r['S_x']),float(r['S_y'])]),float(r['S_fb']))
            found.append(value)
        missing=np.array([v is None for v in found]);pred=np.full((len(points),2),np.nan);fb=np.full(len(points),np.nan)
        for j,v in enumerate(found):
            if v is not None:pred[j],fb[j]=v
        folder=RT/'network'/self.sequence;folder.mkdir(parents=True,exist_ok=True)
        attempt=folder/(str(self.raw_index)+'.json')
        save(attempt,dict(previous_stamp_ns=stamps[self.raw_index-1],stamp_ns=self.stamp_ns,
            previous_image_sha256=hashlib.sha256(previous.tobytes()).hexdigest(),current_image_sha256=hashlib.sha256(current.tobytes()).hexdigest(),
            cached_queries=int((~missing).sum()),missing_queries=int(missing.sum()),model_identity=self.model_identity))
        if missing.any():
            self.load_model();before=self.model.forward_calls
            new=self.model.predict_points(previous,current,points[missing])
            assert self.model.forward_calls-before==2, 'Exactly one shared forward/backward inference per new pair'
            pred[missing]=new['points'];fb[missing]=new['fb_error']
            self.new_pairs+=1;mode='NEW_REQUIRED_QUERY_SET'
        else:self.reused_pairs+=1;mode='REUSED_SPARSE_EXACT_QUERY'
        self.counts[self.sequence,mode]+=1
        np.savez_compressed(folder/(str(self.raw_index)+'.npz'),previous_points=points,predicted_points=pred,fb_error=fb)
        self.timing.append(dict(sequence=self.sequence,raw_index=self.raw_index,stamp_ns=self.stamp_ns,queries=len(points),
            cached_queries=int((~missing).sum()),new_queries=int(missing.sum()),mode=mode,wall_s=time.perf_counter()-tick))
        return dict(points=pred,fb_error=fb)


def frontend():
    shared.ROOT,shared.PAPER,shared.RT=ROOT,PAPER,RT
    shared.frontend(arm_names=('B','D'),contrast=('B','D'),provider_factory=DirectPredictor)


def backend():
    import run_additive_budget_v1 as resources
    import run_additive_budget_backend as runner
    assert (RT/'frontend_complete.json').exists()
    resources.ROOT,resources.RUNTIME=ROOT,RT
    runner.ROOT,runner.PAPER,runner.RUNTIME=ROOT,PAPER,RT;runner.EXECUTION_LOCK=PAPER/'backend_execution_lock_v2.json'
    with (RT/'backend.lock').open('a') as own,open('/tmp/aquafe_classical_expansion_backend_advisory.lock','a') as common:
        for f in (own,common):fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=[]
        for w in json.loads((PAPER/'input_manifest.json').read_text())['windows']:
            slug=w['run_slug'];r=json.loads((RT/'frontend'/slug/'receipt.json').read_text())
            assert r['input_structural_pass'] and not r['baseline_mismatch']
            frames=list(csv.DictReader((RT/'frontend'/slug/'frames.csv').open()))
            assert all(int(f['strong_lk_calls'])==0 and int(f['C_recovered'])==0 for f in frames)
            for arm in ('B','D'):
                for rep in (1,2,3):plan.append(dict(run_slug=slug,arm=arm,repeat=rep,mapped_to='B' if arm=='D' and r['B_D_different_feature_frames']==0 else arm))
        plan_path=RT/'backend_plan.json'
        if plan_path.exists():assert json.loads(plan_path.read_text())==plan
        else:save(plan_path,plan)
        for p in plan:
            if p['arm']==p['mapped_to']:runner.run(p['run_slug'],p['arm'],p['repeat'])
        print('DIRECT_MATRIX_COMPLETE',sum(p['arm']==p['mapped_to'] for p in plan),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['freeze','frontend','backend']);a=p.parse_args()
    globals()[a.stage]()
