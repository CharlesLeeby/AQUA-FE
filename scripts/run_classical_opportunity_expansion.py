#!/usr/bin/env python3
"""Isolated orchestration; frozen candidate and backend mathematics are imported unchanged."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

from run_additive_budget_v1 import sha, save, rows

ROOT=Path(__file__).resolve().parents[1]
PAPER=ROOT/'papers/frontend_classical_opportunity_expansion_v1'
RUNTIME=Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_classical_opportunity_expansion_v1')
OLD=ROOT/'papers/frontend_additive_budget_v1'
PYTHON='/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python'
BRANCH='exp/classical-opportunity-expansion-v1-20260908'

def resources():
    free={str(p):shutil.disk_usage(p).free for p in [ROOT,RUNTIME]}
    mem=next(int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines() if l.startswith('MemAvailable:'))
    if free[str(ROOT)]<2*2**30 or free[str(RUNTIME)]<8*2**30 or mem<4*2**30:
        raise RuntimeError('WAITING_RESOURCE '+json.dumps(dict(free=free,available_memory=mem)))
    return dict(free_bytes=free,available_memory_bytes=mem)

def verify():
    lock=json.loads((PAPER/'source_and_backend_lock.json').read_text())
    for p,h in lock['files'].items():
        if sha(ROOT/p)!=h:raise RuntimeError('SOURCE_IDENTITY_CHANGED '+p)
    for p,h in json.loads((PAPER/'backend_execution_lock_v2.json').read_text())['files'].items():
        if sha(p)!=h:raise RuntimeError('BACKEND_IDENTITY_CHANGED '+p)
    return lock

def frozen_source():
    source=(ROOT/'scripts/run_additive_budget_v1.py').read_text()
    replacements=[
        ("    pools={'xfeat':PrivatePool(XFeatMatcher(top_k=2048,min_cossim=.82),'xfeat'),\n           'classical_gftt':PrivatePool(ClassicalGfttMatcher(),'classical_gftt')}",
         "    pools={'classical_gftt':PrivatePool(ClassicalGfttMatcher(),'classical_gftt')}"),
        ("[('B',None,0),('L6','xfeat',6),('L-all','xfeat',None),('C-all','classical_gftt',None)]", "[('B',None,0),('C-all','classical_gftt',None)]"),
        ('            if ns not in by_stamp:continue\n','            if ns not in by_stamp or not generate:continue\n'),
    ]
    for old,new in replacements:
        assert source.count(old)==1,old
        source=source.replace(old,new)
    return source

def freeze():
    # Must already have a remotely verified roster before execution freeze.
    sync=json.loads((RUNTIME/'roster_remote_readback.json').read_text())
    assert sync['remote_commit']==sync['local_commit']
    windows=[r for r in rows(PAPER/'window_roster_frozen.csv') if r['batch']]
    for w in windows:
        seq=w['sequence'];slug=w['run_slug'];family=w['family']
        oldslug='a02_0_900' if family=='aqualoc_archaeology' else 'h07_0_1000'
        d=ROOT/'papers/frontend_admission_continuation_v1/backend_config_snapshots'/oldslug
        camera=next(p for p in d.glob('*.yaml') if p.name!='vins_same_backend.yaml')
        w.update(input_bag=str(RUNTIME/'prepared'/slug/'input.bag'),image_topic='/camera/image_raw',
            baseline_bag=str(RUNTIME/'baseline'/slug/'features.bag'),camera=str(camera),camera_sha256=sha(camera),
            backend_config_source=str(d/'vins_same_backend.yaml'),backend_config_source_sha256=sha(d/'vins_same_backend.yaml'),
            start_arg=w['start_index'],end_or_duration_arg=str(int(w['end_index_exclusive'])-1))
    old=json.loads((OLD/'source_and_backend_lock.json').read_text())
    # Exact old source identities, plus all configuration ancestors used for B.
    for p,h in old['files'].items():assert sha(ROOT/p)==h,p
    files=set(old['files'])
    files.update(str(p.relative_to(ROOT)) for p in (ROOT/'uw_frontend/configs').rglob('*.yaml'))
    files.update(['scripts/run_classical_opportunity_expansion.py','scripts/analyze_classical_opportunity_expansion.py',
        'scripts/run_frontend_geometry_maturity_router_v1.py','scripts/run_learned_seedchain_eval.sh','scripts/learned_seedchain_env.sh',
        'scripts/run_aqualoc_archaeo_vins_eval.sh','scripts/run_aqualoc_real_vins_eval.sh',
        'scripts/audit_additive_budget_capacity.py','scripts/run_additive_budget_backend.py','scripts/analyze_additive_budget_v1.py'])
    files.update(str(p.relative_to(ROOT)) for p in PAPER.iterdir() if p.is_file() and p.suffix in ('.md','.csv','.json'))
    files.update(str(Path(w[k]).relative_to(ROOT)) for w in windows for k in ['camera','backend_config_source'])
    save(PAPER/'source_and_backend_lock.json',dict(schema='classical-opportunity-expansion-v1',
        base_commit='49c02471716e8ac960e35dd9dd44ef6fbb1428c6',roster_commit=sync['local_commit'],
        windows=windows,files={p:sha(ROOT/p) for p in sorted(files)},
        overlaid_frontend_runner_sha256=hashlib.sha256(frozen_source().encode()).hexdigest(),
        adaptation='B/C-only orchestration and previously audited raw-frame association guard; no method change'))
    execution=json.loads((OLD/'backend_execution_lock_v2.json').read_text())
    for p,h in execution['files'].items():assert sha(p)==h,p
    execution.update(ros_port=12691,source_lock_sha256=sha(PAPER/'source_and_backend_lock.json'),
        frozen_at=datetime.now(timezone.utc).isoformat(),resource_isolation='own port, own task lock, shared advisory replay lock, foreign process precheck')
    save(PAPER/'backend_execution_lock_v2.json',execution)
    save(PAPER/'evaluation_lock.json',json.loads((OLD/'evaluation_lock.json').read_text()))
    (PAPER/'capacity').mkdir(exist_ok=True)
    for name in ['frontend','baseline','prepared','window_failures','controller_logs']:
        (RUNTIME/name).mkdir(exist_ok=True)
    print('EXECUTION_FROZEN',flush=True)

def materialize(w):
    """One sequential raw archive pass; original timestamp/reference message constructors."""
    import csv
    import cv2
    import numpy as np
    import rosbag
    from uw_frontend.datasets import aqualoc_raw_to_rosbag as a
    slug=w['run_slug'];target=RUNTIME/'prepared'/slug;receipt=target/'receipt.json'
    if receipt.exists():
        r=json.loads(receipt.read_text());assert sha(w['input_bag'])==r['input_bag_sha256'];return r
    resources();target.mkdir(parents=True,exist_ok=False)
    start=time.monotonic();info=json.loads((RUNTIME/'metadata'/w['sequence']/'structure.json').read_text())
    for p,h in info['metadata_hashes'].items():assert sha(p)==h,p
    assert sha(info['reference'])==info['reference_sha256']
    image_rows=[a.ImageRow(int(r[0]),r[1]) for r in csv.reader(open(info['image_csv'])) if r and not r[0].startswith('#')]
    imu_rows=[a.ImuRow(int(r[0]),tuple(map(float,r[1:4])),tuple(map(float,r[4:7]))) for r in csv.reader(open(info['imu_csv'])) if r and not r[0].startswith('#')]
    first,end=int(w['start_index']),int(w['end_index_exclusive']);selected=image_rows[first:end]
    assert len(selected)==900
    needed={info['image_dir']+'/'+r.frame_name:i for i,r in enumerate(selected)};payloads={}
    with tarfile.open(info['archive'],'r|gz') as tar:
        for member in tar:
            name=member.name[2:] if member.name.startswith('./') else member.name
            if name in needed:
                assert needed[name] not in payloads,'duplicate archive image'
                payloads[needed[name]]=tar.extractfile(member).read()
    assert len(payloads)==900
    t0,t1=selected[0].stamp_ns,selected[-1].stamp_ns
    assert t0==int(w['start_stamp_ns']) and t1==int(w['end_stamp_ns'])
    ref=a._read_gt(Path(info['reference']))
    events=[(r.stamp_ns,'imu',r) for r in imu_rows if t0-250_000_000<=r.stamp_ns<=t1+250_000_000]
    events.extend((r.stamp_ns,'image',i) for i,r in enumerate(selected));events.sort(key=lambda e:e[0])
    counts=Counter();shape=None;pixels=hashlib.sha256()
    with rosbag.Bag(w['input_bag'],'w',compression=rosbag.Compression.BZ2) as bag:
        for ns,kind,data in events:
            stamp=a._ros_time(ns)
            if kind=='imu':bag.write('/rtimulib_node/imu',a._make_imu_msg(data,'aqualoc_imu'),stamp);counts['imu']+=1;continue
            image=cv2.imdecode(np.frombuffer(payloads[data],np.uint8),cv2.IMREAD_GRAYSCALE)
            assert image is not None
            if shape is None:shape=list(image.shape)
            assert list(image.shape)==shape
            pixels.update(str(ns).encode());pixels.update(image.tobytes())
            bag.write('/camera/image_raw',a._make_image_msg(image,stamp,'aqualoc_camera'),stamp);counts['images']+=1
            if first+data in ref:
                bag.write('/aqualoc/colmap_gt',a._make_gt_msg(ref[first+data],stamp,'aqualoc_world','aqualoc_camera'),stamp);counts['reference']+=1
    r=dict(run_slug=slug,status='PREPARED',input_bag_sha256=sha(w['input_bag']),
        raw_archive=info['archive'],raw_archive_sha256=sha(info['archive']),metadata_receipt_sha256=sha(RUNTIME/'metadata'/w['sequence']/'structure.json'),
        reference_sha256=info['reference_sha256'],image_shape=shape,pixel_stamp_stream_sha256=pixels.hexdigest(),counts=dict(counts),
        wall_s=time.monotonic()-start,start_index=first,end_index_exclusive=end)
    save(receipt,r);return r

def baseline(w):
    import run_frontend_geometry_maturity_router_v1 as base
    target=RUNTIME/'baseline'/w['run_slug'];receipt=target/'receipt.json'
    if receipt.exists():
        r=json.loads(receipt.read_text())
        for p,h in r['artifacts'].items():assert sha(p)==h,p
        return r
    resources();target.mkdir(parents=True,exist_ok=False)
    base.ROOT=ROOT;base.RUNTIME=RUNTIME;base.SHADOW=RUNTIME/'shadow_root'
    base.prepare_shadow();base.run_dir=lambda window,arm:target
    arm=dict(method='klt',profile='lineage_early_seed_coverage_monotone_v2',seed_source='xfeat',arm='klt')
    command,env,_=base.command_and_env(w,arm)
    env.update(AQUAFE_EXPORT_MODULE='uw_frontend.ros.export_vins_admission_continuation_v1',
        AQUAFE_LIFECYCLE_LOG_DIR=str(target),PYTHONDONTWRITEBYTECODE='1',RAW_TAR=w['raw_archive'],
        RAW_BAG=w['input_bag'],GT_TXT=w['reference'],PYTHONPATH=str(ROOT)+':'+os.environ.get('PYTHONPATH',''))
    start=time.monotonic()
    with (target/'console.log').open('x') as f:
        p=subprocess.run(command,env=env,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    if p.returncode:raise RuntimeError('BASELINE_EXPORT_FAILED '+str(target))
    assert Path(w['baseline_bag']).is_file()
    r=dict(run_slug=w['run_slug'],command=command,returncode=p.returncode,wall_s=time.monotonic()-start,
        input_bag_sha256=sha(w['input_bag']),baseline_sha256=sha(w['baseline_bag']),
        artifacts={str(p):sha(p) for p in target.iterdir() if p.is_file()})
    save(receipt,r);return r

def frontend(w):
    prep=materialize(w);b=baseline(w)
    w=dict(w,input_bag_sha256=prep['input_bag_sha256'],baseline_sha256=b['baseline_sha256'])
    lock=verify();source=frozen_source()
    assert hashlib.sha256(source.encode()).hexdigest()==lock['overlaid_frontend_runner_sha256']
    ns={'__file__':str(ROOT/'scripts/run_additive_budget_v1.py'),'__name__':'classical_opportunity_frozen_frontend'}
    exec(compile(source,'additive-v1[registered-B-C-only-adapter]','exec'),ns)
    ns.update(ROOT=ROOT,PAPER=PAPER,RUNTIME=RUNTIME,resource_check=resources,verify=lambda:dict(windows=[w]))
    with (RUNTIME/'frontend.lock').open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB);ns['frontend'](w['run_slug'])
    import audit_additive_budget_capacity as cap
    capfile=PAPER/'capacity'/f'{w["run_slug"]}.json'
    if not capfile.exists():
        rec=json.loads((RUNTIME/'frontend'/w['run_slug']/'receipt.json').read_text())
        save(capfile,dict(run_slug=w['run_slug'],arms={arm:cap.audit_bag(item['feature_bag']) for arm,item in rec['arms'].items()},capacity_modified=False))
    from analyze_classical_opportunity_expansion import readback
    readback(w,json.loads((RUNTIME/'frontend'/w['run_slug']/'receipt.json').read_text()))
    return w

def backend(w,arm,repeat):
    import run_additive_budget_backend as b
    b.ROOT=ROOT;b.PAPER=PAPER;b.RUNTIME=RUNTIME;b.EXECUTION_LOCK=PAPER/'backend_execution_lock_v2.json';b.resource_check=resources
    with (RUNTIME/'backend.lock').open('a') as own, Path('/tmp/aquafe_classical_expansion_backend_advisory.lock').open('a') as shared:
        try:
            fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(shared,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('WAITING_RESOURCE replay lock held')
        b.run(w['run_slug'],arm,repeat)

def main():
    p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--window');p.add_argument('--frontend',action='store_true');p.add_argument('--arm',choices=['B','C-all']);p.add_argument('--repeat',type=int,choices=[1,2,3]);a=p.parse_args()
    os.chdir(ROOT)
    if a.freeze:return freeze()
    lock=verify();w=next(w for w in lock['windows'] if w['run_slug']==a.window)
    if a.frontend:frontend(w)
    else:backend(w,a.arm,a.repeat)

if __name__=='__main__':main()
