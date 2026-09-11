#!/usr/bin/env python3
"""Fixed two-window frontend integration and original backend runner adapter."""
import argparse,csv,hashlib,io,json,os,subprocess,time
from collections import Counter,defaultdict
from pathlib import Path
import cv2,numpy as np
from run_additive_budget_v1 import sha,save
ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_searaft_system_probe_v1'
STORE=Path('/media/ma/Data/AQUA-FE_WS_storage_offload')
RT=STORE/'frontend_searaft_system_probe_v1'
SOURCE=STORE/'frontend_searaft_screening_v1'
FEATURE='/feature_tracker/feature'


def table(path,rows):
    with Path(path).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for r in rows for k in r)));w.writeheader();w.writerows(rows)


def freeze():
    import rosbag
    RT.mkdir(exist_ok=False);(RT/'tmp').mkdir()
    old=json.loads((ROOT/'papers/frontend_learned_klt_recovery_v1/input_manifest.json').read_text())
    windows=[]
    for seq,name,slug in [('H02','frontend_classical_opportunity_expansion_v1','coe1_h02_00000_00900'),('A02','frontend_additive_budget_v1','a02_0_900')]:
        src=ROOT/'papers'/name/'source_and_backend_lock.json'
        w=dict(next(w for w in json.loads(src.read_text())['windows'] if w['run_slug']==slug))
        w.update(sequence=seq,run_slug=seq.lower()+'_0_900',raw_start=0,raw_end_exclusive=900,source_lock=str(src),old_run_slug=slug,heldout_type='outcome-known development')
        stamps=[];counts={}
        with rosbag.Bag(w['input_bag']) as bag:
            counts={t:v.message_count for t,v in bag.get_type_and_topic_info().topics.items()}
            for i,(_,m,_) in enumerate(bag.read_messages(topics=[w['image_topic']])):
                if i==900:break
                stamps.append(m.header.stamp.to_nsec())
                shape=[m.height,m.width]
        assert len(stamps)==900 and all(a<b for a,b in zip(stamps,stamps[1:]))
        for k in ('camera','backend_config_source'):
            assert sha(w[k])==w[k+'_sha256']
        w.update(image_shape=shape,first_stamp_ns=stamps[0],last_stamp_ns=stamps[-1],actual_raw_dt_min_s=min(np.diff(stamps))*1e-9,actual_raw_dt_max_s=max(np.diff(stamps))*1e-9,input_topic_counts=counts)
        windows.append(w)
    save(PAPER/'input_manifest.json',dict(windows=windows,klt=old['klt'],public_every_n=2,public_frame_offset=1,
        quality_gate_source='raw_degradation',backend_quality=dict(backend_quality_mode='vins_safe',backend_quality_floor=.8,backend_quality_alpha=.65),baseline_reuse='No backend reuse; all arms fresh unless R/C serialize identically.'))
    save(PAPER/'source_and_backend_lock.json',dict(windows=windows))
    lock=json.loads((ROOT/'papers/frontend_classical_opportunity_expansion_v1/backend_execution_lock_v2.json').read_text())
    # Inherit the exact existing binary/dependency lock; only task port changes.
    lock['ros_port']=12731;lock['source_lock_sha256']=sha(PAPER/'source_and_backend_lock.json')
    for p,h in lock['files'].items():
        assert sha(p)==h, p
    save(PAPER/'backend_execution_lock_v2.json',lock)
    (PAPER/'evaluation_lock.json').write_bytes((ROOT/'papers/frontend_classical_opportunity_expansion_v1/evaluation_lock.json').read_bytes())
    print('INPUT_AND_BACKEND_FROZEN',[(w['sequence'],w['input_topic_counts']) for w in windows],flush=True)


class Predictor:
    def __init__(self,cache_only=False):
        self.model=None;self.new_pairs=self.reused_pairs=0;self.sequence=None;self.raw_index=None;self.stamp_ns=None
        self.cache_only=cache_only
        if cache_only:
            self.previous_timing={(r['sequence'],int(r['raw_index'])):r for r in csv.DictReader((RT/'pre_velocity_fix/network_timing.csv').open())}
        self.old={}
        for r in csv.DictReader((ROOT/'papers/frontend_searaft_screening_v1/natural_results.csv').open()):
            self.old[(r['sequence'],int(r['raw_index']),int(r['stamp_ns']),float(r['previous_x']),float(r['previous_y']))]=r
        self.counts=Counter();self.timing=[]

    def __call__(self,previous,current,points):
        if self.cache_only:
            path=RT/'network'/self.sequence/(str(self.raw_index)+'.npz')
            with np.load(path) as saved:
                assert np.array_equal(points,saved['previous_points']), 'Cached query set must match exactly; inference prohibited'
                result=dict(points=saved['predicted_points'].copy(),fb_error=saved['fb_error'].copy())
            row=self.previous_timing[self.sequence,self.raw_index]
            assert int(row['stamp_ns'])==self.stamp_ns
            self.timing.append(row);self.counts[self.sequence,row['mode']]+=1
            self.new_pairs+=row['mode']=='NEW_REQUIRED_QUERY_SET'
            self.reused_pairs+=row['mode']=='REUSED_SPARSE_EXACT_QUERY'
            return result
        found=[self.old.get((self.sequence,self.raw_index,self.stamp_ns,float(p[0]),float(p[1]))) for p in points]
        tick=time.perf_counter()
        if all(r is not None for r in found):
            result=dict(points=np.asarray([[float(r['S_x']),float(r['S_y'])] for r in found]),fb_error=np.asarray([float(r['S_fb']) for r in found]))
            self.reused_pairs+=1;mode='REUSED_SPARSE_EXACT_QUERY'
        else:
            if self.model is None:
                import torch
                from uw_frontend.matchers.searaft_points import SeaRaftPoints
                torch.set_num_threads(1);torch.manual_seed(20260909);torch.backends.cudnn.benchmark=False
                torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
                self.model=SeaRaftPoints(SOURCE/'official_SEA-RAFT',SOURCE/'model')
                lock=json.loads((ROOT/'papers/frontend_searaft_screening_v1/model_lock.json').read_text())
                assert self.model.config==lock['inference_config'] and self.model.loading['local_pth_sha256']==lock['loading']['local_pth_sha256']
                save(RT/'model_loading.json',dict(loading=self.model.loading,config=self.model.config))
            result=self.model.predict_points(previous,current,points)
            self.new_pairs+=1;mode='NEW_REQUIRED_QUERY_SET'
        self.counts[self.sequence,mode]+=1
        folder=RT/'network'/self.sequence;folder.mkdir(parents=True,exist_ok=True)
        path=folder/(str(self.raw_index)+'.npz')
        assert not path.exists(),'Do not repeat a completed source transition'
        np.savez_compressed(path,previous_points=points,predicted_points=result['points'],fb_error=result['fb_error'])
        self.timing.append(dict(sequence=self.sequence,raw_index=self.raw_index,stamp_ns=self.stamp_ns,queries=len(points),mode=mode,wall_s=time.perf_counter()-tick))
        return result


def frontend(cache_only=False):
    import rosbag
    from cv_bridge import CvBridge
    from uw_frontend.ros.export_vins_features import _image_msg_to_gray,_preprocess_gray,_load_pinhole_camera,_tracks_to_vins_pointcloud
    from uw_frontend.quality.image_quality import score_image_quality,fuse_image_quality_for_gates
    from uw_frontend.tracking.klt_tracker import KltConfig
    from uw_frontend.tracking.searaft_system_recovery import SeaRaftSystemTracker
    from audit_additive_budget_capacity import audit_bag
    cv2.setNumThreads(1);np.random.seed(20260909)
    conf=json.loads((PAPER/'input_manifest.json').read_text());provider=Predictor(cache_only);summaries=[]
    for w in conf['windows']:
        seq=w['sequence'];folder=RT/'frontend'/w['run_slug'];folder.mkdir(parents=True,exist_ok=False)
        camera=_load_pinhole_camera(Path(w['camera']));trackers={a:SeaRaftSystemTracker(a,KltConfig(**conf['klt']),provider if a=='R' else None) for a in ['B','C','R']}
        clouds={a:{} for a in trackers};previous_public={a:set() for a in trackers};ended={a:set() for a in trackers}
        events=[];active={a:defaultdict(list) for a in trackers};frames=[];public_rows=[];preprocessing=0.;start=time.perf_counter();previous_stamp=None
        old_clouds={}
        with rosbag.Bag(w['baseline_bag']) as bag:
            old_clouds={m.header.stamp.to_nsec():m for _,m,_ in bag.read_messages(topics=[FEATURE])}
        baseline_mismatch=Counter();diff_CR=0;gftt_diff=0
        with rosbag.Bag(w['input_bag']) as bag:
            for i,(_,msg,_) in enumerate(bag.read_messages(topics=[w['image_topic']])):
                if i>=900:break
                raw=_image_msg_to_gray(CvBridge(),msg);stamp=msg.header.stamp.to_nsec()
                tick=time.perf_counter();gray=_preprocess_gray(raw,'adaptive_clahe');quality=fuse_image_quality_for_gates(score_image_quality(gray),score_image_quality(raw),conf['quality_gate_source']);preprocessing+=time.perf_counter()-tick
                provider.sequence,provider.raw_index,provider.stamp_ns=seq,i,stamp
                current={};publish=i%2==1
                for arm,tr in trackers.items():
                    tick=time.perf_counter();tracks,diag=tr.process_raw(raw,gray,quality,i,stamp);wall=time.perf_counter()-tick;current[arm]=tracks
                    live=set(map(int,tracks.ids))
                    for tid in list(active[arm]):
                        if tid not in live:
                            for e in active[arm].pop(tid):e['termination']='RAW_TRACK_ENDED'
                    for e in tr.events:
                        row=dict(sequence=seq,arm=arm,raw_index=i,stamp_ns=stamp,public_observations_after=0,termination='WINDOW_CENSORED',**e)
                        events.append(row);active[arm][e['track_id']].append(row)
                    frames.append(dict(sequence=seq,arm=arm,raw_index=i,stamp_ns=stamp,features=len(tracks),new_gftt=diag.added_features,wall_s=wall,**tr.frame_stats))
                    if publish:
                        assert not live.intersection(ended[arm]),'Publicly ended ID resurrected'
                        ended[arm]|=previous_public[arm]-live;previous_public[arm]=live
                        # Match original export's ROS epoch float subtraction,
                        # including its rounding, rather than integer-ns dt.
                        dt=None if previous_stamp is None else max(1e-6,msg.header.stamp.to_sec()-previous_stamp)
                        cloud=_tracks_to_vins_pointcloud(tracks,msg.header.stamp,camera,dt,**conf['backend_quality'])
                        assert len(cloud.points)==len(tracks) and len(tracks)<=350
                        assert np.isfinite(tracks.points).all()
                        clouds[arm][stamp]=cloud
                        for tid in live:
                            for e in active[arm].get(tid,[]):e['public_observations_after']+=1
                        for j,tid in enumerate(tracks.ids):
                            public_rows.append(dict(sequence=seq,arm=arm,raw_index=i,stamp_ns=stamp,track_id=int(tid),x=float(tracks.points[j,0]),y=float(tracks.points[j,1]),age=int(tracks.ages[j]),has_S_history=any(e['source']=='S' for e in active[arm].get(int(tid),[]))))
                if not (np.array_equal(current['C'].points[current['C'].ages==1],current['R'].points[current['R'].ages==1])):gftt_diff+=1
                if publish:
                    def serial(m):
                        f=io.BytesIO();m.serialize(f);return f.getvalue()
                    baseline=old_clouds[stamp];b=clouds['B'][stamp]
                    bc={c.name:c.values for c in baseline.channels};nc={c.name:c.values for c in b.channels}
                    for k in ['id','p_u','p_v']:
                        if not np.array_equal(np.asarray(bc[k],np.float32),np.asarray(nc[k],np.float32)):baseline_mismatch[k]+=1
                    if serial(b)!=serial(baseline):baseline_mismatch['serialized']+=1
                    if serial(clouds['C'][stamp])!=serial(clouds['R'][stamp]):diff_CR+=1
                    previous_stamp=msg.header.stamp.to_sec()
                if i%100==0:print('FRONTEND_PROGRESS',seq,i,'S_recovered',sum(e['source']=='S' for e in events),'new_network_pairs',provider.new_pairs,flush=True)
        assert i>=899 and len(clouds['B'])==450
        table(folder/'recovery_events.csv',events) if events else (folder/'recovery_events.csv').write_text('sequence,arm,raw_index,stamp_ns,track_id,source,public_observations_after,termination\n')
        table(folder/'frames.csv',frames);table(folder/'public_tracks.csv',public_rows);table(RT/'network_timing.csv',provider.timing)
        arms={}
        for arm in trackers:
            output=folder/(arm+'.bag')
            with rosbag.Bag(w['baseline_bag']) as oldbag,rosbag.Bag(str(output),'w') as newbag:
                for topic,msg,t in oldbag.read_messages():
                    if topic==FEATURE:msg=clouds[arm][msg.header.stamp.to_nsec()]
                    newbag.write(topic,msg,t)
            arms[arm]=dict(feature_bag=str(output),sha256=sha(output))
            ee=[e for e in events if e['arm']==arm]
            ff=[r for r in frames if r['arm']==arm]
            summaries.append(dict(sequence=seq,arm=arm,raw_frames=900,public_frames=450,C_recoveries=sum(e['source']=='C' for e in ee),S_recoveries=sum(e['source']=='S' for e in ee),
                S_recoveries_public_ge1=sum(e['source']=='S' and e['public_observations_after']>=1 for e in ee),S_recoveries_public_ge4=sum(e['source']=='S' and e['public_observations_after']>=4 for e in ee),
                S_recovery_unique_ids=len({e['track_id'] for e in ee if e['source']=='S'}),frontend_wall_s=sum(r['wall_s'] for r in ff),shared_preprocessing_s=preprocessing,
                network_new_pairs=provider.counts[seq,'NEW_REQUIRED_QUERY_SET'] if arm=='R' else 0,network_reused_pairs=provider.counts[seq,'REUSED_SPARSE_EXACT_QUERY'] if arm=='R' else 0,
                forward_calls=2*provider.counts[seq,'NEW_REQUIRED_QUERY_SET'] if arm=='R' else 0,C_R_different_feature_frames=diff_CR,C_R_different_GFTT_frames=gftt_diff,baseline_mismatch=json.dumps(dict(baseline_mismatch)),physical_correctness='Unknown'))
        capacity={arm:audit_bag(item['feature_bag']) for arm,item in arms.items()}
        assert all(c['status']=='PASS' for c in capacity.values())
        save(PAPER/'capacity'/(w['run_slug']+'.json'),dict(arms=capacity))
        assert not baseline_mismatch, 'Original B serialization differs; inspect before backend'
        if cache_only:
            original=RT/'pre_velocity_fix/frontend'/w['run_slug']
            assert (folder/'recovery_events.csv').read_bytes()==(original/'recovery_events.csv').read_bytes()
            assert (folder/'public_tracks.csv').read_bytes()==(original/'public_tracks.csv').read_bytes()
            old_summary=list(csv.DictReader((RT/'pre_velocity_fix/recovery_summary.csv').open()))
            for r in summaries[-3:]:
                old_r=next(v for v in old_summary if v['sequence']==seq and v['arm']==r['arm'])
                r['cached_reexport_wall_s']=r['frontend_wall_s']
                r['frontend_wall_s']=float(old_r['frontend_wall_s'])
                r['shared_preprocessing_s']=float(old_r['shared_preprocessing_s'])
        save(folder/'receipt.json',dict(sequence=seq,arms=arms,C_R_different_feature_frames=diff_CR,baseline_mismatch=dict(baseline_mismatch),input_structural_pass=True,wall_s=time.perf_counter()-start,
            recovery_events=str(folder/'recovery_events.csv'),public_tracks=str(folder/'public_tracks.csv')))
        table(PAPER/'recovery_summary.csv',summaries)
        print('FRONTEND_COMPLETE',seq,json.dumps(summaries[-3:]),flush=True)
    save(RT/'frontend_complete.json',dict(new_network_pairs=provider.new_pairs,reused_network_pairs=provider.reused_pairs,forward_calls=2*provider.new_pairs,model_loads=1 if cache_only else int(provider.model is not None),additional_inference_in_export_repair=0 if cache_only else None))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['freeze','frontend']);p.add_argument('--cached-export',action='store_true');a=p.parse_args()
    if a.stage=='freeze':freeze()
    else:frontend(a.cached_export)
