#!/usr/bin/env python3
"""Identity-locked source generation and additive merge; no legacy writes."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT/'papers/frontend_additive_budget_v1'
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1')
FEATURE = '/feature_tracker/feature'
PYTHON = '/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()


def rows(path):
    with Path(path).open(newline='') as f: return list(csv.DictReader(f))


def save(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: json.dump(payload,f,indent=2,sort_keys=True); f.write('\n')


def write_csv(path, data):
    with Path(path).open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)


def resource_check():
    free = {str(p):shutil.disk_usage(p).free for p in (ROOT,RUNTIME)}
    mem = next(int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    if free[str(ROOT)]<2*2**30 or free[str(RUNTIME)]<8*2**30 or mem<4*2**30:
        raise RuntimeError('RESOURCE_LIMIT: '+json.dumps(dict(free=free,mem=mem)))
    return dict(free_bytes=free,available_memory_bytes=mem)


def freeze():
    import rosbag
    lockfile=PAPER/'source_and_backend_lock.json'
    if lockfile.exists(): raise RuntimeError('lock already frozen')
    old={r['run_slug']:r for r in rows(ROOT/'papers/frontend_admission_continuation_v1/frontend_audit.csv') if r['arm']=='klt'}
    windows=rows(PAPER/'windows.csv')
    for w in windows:
        b=old[w['run_slug']]
        if sha(w['input_bag'])!=w['input_bag_sha256'] or sha(b['feature_bag'])!=b['feature_bag_sha256']:
            raise RuntimeError('input identity mismatch: '+w['run_slug'])
        receipt=Path(b['feature_bag']).parent/'frontend_receipt.json'
        rec=json.loads(receipt.read_text())
        if rec['input_bag_sha256']!=w['input_bag_sha256'] or not rec['integrity_pass']:
            raise RuntimeError('invalid baseline receipt')
        w.update(baseline_bag=b['feature_bag'],baseline_sha256=b['feature_bag_sha256'],
                 baseline_receipt=str(receipt),baseline_receipt_sha256=sha(receipt))
        with rosbag.Bag(w['input_bag']) as bag:
            topics=bag.get_type_and_topic_info().topics
            images=[t for t,v in topics.items() if v.msg_type in ('sensor_msgs/Image','sensor_msgs/CompressedImage')]
            if len(images)!=1: raise RuntimeError('ambiguous image topic')
            w['image_topic']=images[0]
            w['image_messages']=topics[images[0]].message_count
        camera_dir=ROOT/'papers/frontend_admission_continuation_v1/backend_config_snapshots'/w['run_slug']
        config=camera_dir/'vins_same_backend.yaml'
        w['backend_config_source']=str(config)
        w['backend_config_source_sha256']=sha(config)
        camera=next(p for p in camera_dir.glob('*.yaml') if p.name!='vins_same_backend.yaml')
        w['camera']=str(camera);w['camera_sha256']=sha(camera)
    files=[*sorted((ROOT/'uw_frontend').rglob('*.py')),
           ROOT/'scripts/run_additive_budget_v1.py', ROOT/'tests/test_additive_budget_v1.py',
           PAPER/'preregistration.md',PAPER/'windows.csv',PAPER/'arms.csv',
           ROOT/'scripts/evaluate_vins_common_support_epoch_v2.py',ROOT/'scripts/evaluate_vins_common_support.py',
           ROOT/'scripts/trajectory_eval_core.py']
    ext=ROOT/'external_tools/accelerated_features'
    deps=[*sorted((ext/'modules').rglob('*.py')),ext/'weights/xfeat.pt']
    backend=Path('/home/ma/SLAM/VINS-Fusion-origin')
    backend_files=[*sorted((backend/'src/VINS-Fusion-master/vins_estimator').rglob('*.cpp')),
                   *sorted((backend/'src/VINS-Fusion-master/vins_estimator').rglob('*.h')),
                   backend/'devel/lib/vins/vins_node',backend/'devel/lib/libvins_lib.so']
    save(lockfile,dict(schema='additive-budget-v1',frozen_at=datetime.now(timezone.utc).isoformat(),
         base_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip(),
         branch=subprocess.check_output(['git','branch','--show-current'],text=True,cwd=ROOT).strip(),
         windows=windows,files={str(p.relative_to(ROOT)):sha(p) for p in files},
         dependencies={str(p.resolve()):sha(p) for p in deps},
         backend_original_files={str(p):sha(p) for p in backend_files},
         backend_execution_status='PENDING_CAPACITY_AND_DIAGNOSTIC_LOCK',resources=resource_check()))


def verify():
    lock=json.loads((PAPER/'source_and_backend_lock.json').read_text())
    for rel,expected in lock['files'].items():
        if sha(ROOT/rel)!=expected: raise RuntimeError('source lock mismatch '+rel)
    for p,expected in lock['dependencies'].items():
        if sha(p)!=expected: raise RuntimeError('dependency lock mismatch '+p)
    return lock


def frontend(slug):
    import cv2
    import numpy as np
    import rosbag
    from cv_bridge import CvBridge
    from uw_frontend.matchers.xfeat_adapter import XFeatMatcher
    from uw_frontend.matchers.classical_gftt import ClassicalGfttMatcher
    from uw_frontend.ros import export_vins_features as ex
    from uw_frontend.ros.additive_budget_v1 import PrivatePool, Publisher, channels, serialized, assert_backbone
    lock=verify()
    w=next(w for w in lock['windows'] if w['run_slug']==slug)
    target=RUNTIME/'frontend'/slug
    if (target/'receipt.json').exists():
        receipt=json.loads((target/'receipt.json').read_text())
        for p,h in receipt['artifacts'].items():
            if sha(p)!=h: raise RuntimeError('completed artifact changed '+p)
        print('REUSE',slug,flush=True);return
    target.mkdir(exist_ok=False)
    start=time.monotonic();before=resource_check()
    cv2.setNumThreads(1)
    np.random.seed(0)
    pools={'xfeat':PrivatePool(XFeatMatcher(top_k=2048,min_cossim=.82),'xfeat'),
           'classical_gftt':PrivatePool(ClassicalGfttMatcher(),'classical_gftt')}
    camera=ex._load_pinhole_camera(Path(w['camera']))
    with rosbag.Bag(w['baseline_bag']) as bag:
        base=[m for _,m,_ in bag.read_messages(topics=[FEATURE])]
    by_stamp={m.header.stamp.to_nsec():m for m in base}
    if len(by_stamp)!=len(base):raise RuntimeError('baseline duplicate timestamps')
    source_files={s:(target/(s+'_source.jsonl')).open('x') for s in pools}
    bridge=CvBridge();previous={};source_index=0;seen=set();shape=None
    timings=Counter()
    with rosbag.Bag(w['input_bag']) as bag:
        for raw_index,(_,msg,bt) in enumerate(bag.read_messages(topics=[w['image_topic']])):
            step=time.monotonic()
            ns=msg.header.stamp.to_nsec()
            gray=ex._image_msg_to_gray(bridge,msg)
            if shape is None:shape=list(gray.shape)
            if list(gray.shape)!=shape:raise RuntimeError('image dimensions changed')
            gray=ex._preprocess_gray(gray,'adaptive_clahe')
            timings['image_preprocessing_s']+=time.monotonic()-step
            generate=raw_index%int(w['every_n'])==int(w['frame_offset'])
            for source,pool in pools.items():
                tick=time.monotonic();pool.process(gray,generate)
                timings[source+'_tracking_generation_s']+=time.monotonic()-tick
            if ns not in by_stamp:continue
            seen.add(ns)
            baseline=by_stamp[ns]
            for source,pool in pools.items():
                tick=time.monotonic()
                record=pool.eligible(baseline,previous,camera,ns,source_index)
                source_files[source].write(json.dumps(record,sort_keys=True)+'\n')
                timings[source+'_eligibility_s']+=time.monotonic()-tick
            c=channels(baseline)
            previous={int(i):np.asarray([u,v],np.float32) for i,u,v in zip(c['id'],c['p_u'],c['p_v'])}
            source_index+=1
            if source_index%50==0:
                resource_check()
                print(slug,'feature',source_index,'pool',[(s,len(p.tracker.ids),p.counters['eligible_observations']) for s,p in pools.items()],flush=True)
    for f in source_files.values():f.close()
    if seen!=set(by_stamp):raise RuntimeError('source/baseline timestamps do not match')
    generation_s=time.monotonic()-start
    audits=[];lifecycles=[];resources=[];arm_records={}
    for arm,source,limit in [('B',None,0),('L6','xfeat',6),('L-all','xfeat',None),('C-all','classical_gftt',None)]:
        tick=time.monotonic();publisher=Publisher(limit);counts=[];ids=Counter();frame_ids=[];maps={}
        records=[] if source is None else [json.loads(l) for l in (target/(source+'_source.jsonl')).read_text().splitlines()]
        no_action=source is None or not any(r['observations'] for r in records)
        output=Path(w['baseline_bag']) if no_action else target/(arm+'.bag')
        writer=None if no_action else rosbag.Bag(str(output),'w')
        index=0
        with rosbag.Bag(w['baseline_bag']) as bag:
            for topic,msg,stamp in bag.read_messages():
                result=msg
                if topic==FEATURE:
                    if source is not None:
                        result,chosen=publisher.publish(msg,records[index]);maps[index]=chosen
                    else:chosen=[]
                    assert_backbone(msg,result)
                    count=len(result.points)-len(msg.points);counts.append(count)
                    current=[int(x) for x in channels(result)['id']]
                    ids.update(current);frame_ids.append(set(current))
                    audits.append(dict(run_slug=slug,arm=arm,frame=index,stamp_ns=msg.header.stamp.to_nsec(),
                        KLT=len(msg.points),candidates=count,total=len(result.points),backbone_exact=True))
                    index+=1
                if writer:writer.write(topic,result,stamp)
        if writer:writer.close()
        # Read serialized bag back: validate encoding and every non-feature message.
        if writer:
            with rosbag.Bag(w['baseline_bag']) as b,rosbag.Bag(str(output)) as a:
                ai=iter(a.read_messages());checked=0
                for bt,bm,bs in b.read_messages():
                    at,am,ats=next(ai)
                    if bt!=at or bs!=ats:raise RuntimeError('bag message ordering changed')
                    if bt==FEATURE:assert_backbone(bm,am)
                    elif serialized(bm)!=serialized(am):raise RuntimeError('nonfeature message changed')
                    checked+=1
                if next(ai,None) is not None:raise RuntimeError('extra bag message')
        life=list(publisher.lengths.values())
        unions=[len(set().union(*frame_ids[max(0,i-10):i+1])) for i in range(len(frame_ids))]
        # Whole-window >=4 ID bound dominates any keyframe-selected optimizer state.
        capacity_bound=sum(n>=4 for n in ids.values())
        arm_records[arm]=dict(feature_bag=str(output),sha256=sha(output),feature_messages=len(counts),
            total_published=sum(counts),max_concurrent=max(counts),frames_at_six=sum(n==6 for n in counts),
            frames_over_six=sum(n>6 for n in counts),public_ids=len(life),lifetime_median=float(np.median(life)) if life else 0,
            lifetime_max=max(life,default=0),chains_ge4=sum(n>=4 for n in life),chains_ge10=sum(n>=10 for n in life),
            max_total=max(len(s) for s in frame_ids),unique_ids=len(ids),max_11_frame_id_union=max(unions),
            conservative_depth_id_bound=capacity_bound,capacity_status='PASS' if capacity_bound<=1000 else 'CAPACITY_REVIEW_REQUIRED',
            backbone_exact=True,zero_action_identity=no_action,merge_wall_s=time.monotonic()-tick,
            source_stream_sha256=sha(target/(source+'_source.jsonl')) if source else None)
        lifecycles.extend(dict(run_slug=slug,arm=arm,**e) for e in publisher.events)
        if arm=='L6':sixmaps=maps
        if arm=='L-all':
            if any(not set(sixmaps[i]).issubset(maps[i]) for i in sixmaps):
                raise RuntimeError('L6 is not a source-ID/timestamp subset of L-all')
    write_csv(target/'frontend_frames.csv',audits)
    if lifecycles:write_csv(target/'candidate_lifecycle.csv',lifecycles)
    elapsed=time.monotonic()-start
    save(target/'receipt.json',dict(run_slug=slug,status='FRONTEND_COMPLETE',source_lock_sha256=sha(PAPER/'source_and_backend_lock.json'),
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        input_bag_sha256=w['input_bag_sha256'],baseline_sha256=w['baseline_sha256'],
        image_shape=shape,raw_frames=raw_index+1,arms=arm_records,
        source_counters={s:dict(p.counters) for s,p in pools.items()},timings=dict(timings),
        generation_wall_s=generation_s,total_wall_s=elapsed,peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        resource_pre=before,resource_post=resource_check(),
        artifacts={str(p):sha(p) for p in target.iterdir() if p.is_file()}))
    print('COMPLETE',slug,json.dumps(arm_records),flush=True)


def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--window');args=p.parse_args()
    os.chdir(ROOT)
    with (RUNTIME/'frontend.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.freeze:freeze()
        elif args.window:frontend(args.window)
        else:raise RuntimeError('choose --freeze or --window')


if __name__=='__main__':main()
