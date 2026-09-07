#!/usr/bin/env python3
"""Bound NUM_OF_F for continuous IDs under arbitrary backend keyframe choice."""
import argparse
from collections import Counter,deque
import json
from pathlib import Path
import numpy as np
import rosbag
from run_additive_budget_v1 import RUNTIME,PAPER,save,sha,FEATURE


def audit_bag(path):
    last={};counts=Counter();max_count=0;max_ids11=0;max_depth11=0;recent=deque(maxlen=11);gaps=[]
    with rosbag.Bag(str(path)) as bag:
        for i,(_,m,_) in enumerate(bag.read_messages(topics=[FEATURE])):
            c={c.name:c.values for c in m.channels}
            keys=list(zip(c['camera_id'],c['id']))
            if len(set(keys))!=len(keys):raise RuntimeError('duplicate camera/id')
            ids=[]
            for cam,tid in keys:
                if cam!=0 or tid!=int(tid) or tid!=np.float32(tid) or abs(tid)>=2**24:
                    raise RuntimeError('unsupported public ID/camera encoding')
                tid=int(tid)
                if tid in last and last[tid]!=i-1:gaps.append(dict(id=tid,previous=last[tid],current=i))
                last[tid]=i;ids.append(tid)
            max_count=max(max_count,len(ids));counts.update(ids);recent.append(ids)
            window=Counter(x for f in recent for x in f)
            max_ids11=max(max_ids11,len(window));max_depth11=max(max_depth11,sum(n>=4 for n in window.values()))
    # For 11 retained frames, any contiguous >=4-observation interval hits index 3 or 7.
    # Thus all eligible features lie in the union of two input frames: <=2*max_count.
    bound=2*max_count
    return dict(feature_messages=i+1,max_per_message=max_count,unique_ids=len(last),
        whole_window_ge4=sum(n>=4 for n in counts.values()),max_consecutive11_ids=max_ids11,
        max_consecutive11_ge4=max_depth11,public_gap_count=len(gaps),gaps=gaps[:20],
        arbitrary_keyframe_depth_bound=bound if not gaps else None,capacity=1000,
        status=('PASS' if bound<=1000 else 'GUARDED_CAPACITY_PROBE_REQUIRED') if not gaps else 'CAPACITY_UNSUPPORTED',
        feature_bag=str(path),feature_bag_sha256=sha(path))


def main():
    p=argparse.ArgumentParser();p.add_argument('--window',required=True);a=p.parse_args()
    receipt=json.loads((RUNTIME/'frontend'/a.window/'receipt.json').read_text())
    target=PAPER/'capacity'/f'{a.window}.json'
    if target.exists():raise RuntimeError('capacity receipt exists')
    results={arm:audit_bag(r['feature_bag']) for arm,r in receipt['arms'].items()}
    save(target,dict(run_slug=a.window,arms=results,
        proof='WINDOW_SIZE=10; continuous public IDs remain contiguous under frame removal; every length>=4 interval among indices0..10 intersects {3,7}; depth_count<=2*max_input_count. Whole-window count is only a looser bound.',
        capacity_modified=False))
    print(json.dumps(results,indent=2))


if __name__=='__main__':main()
