"""Conditional natural query opportunity check. No feature bags or VINS."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import time

import cv2
import numpy as np
from uw_frontend.tracking.klt_tracker import KltTracker,KltConfig
from uw_frontend.quality.image_quality import score_image_quality
from uw_frontend.matchers.searaft_points import common_mask
from searaft_screening_measurements import ROOT,PAPER,RT,PREPROCESS,working,to_original,strong_lk,write_csv,save


def offline_follow(rows,arm,offset,gray,quality,scale,klt):
    accepted=[r for r in rows if r[arm+'_accepted']]
    if not accepted:return
    tracker=KltTracker(klt)
    original=np.array([[r[arm+'_x'],r[arm+'_y']] for r in accepted])
    tracker.points=np.float32((original+.5)*scale-.5)
    tracker.ids=np.arange(len(accepted));tracker.ages=np.full(len(accepted),2,np.int32)
    for r in accepted:
        r[arm+'_offline_steps']=0;r[arm+'_offline_displacement_px']=0.;r[arm+'_termination']='right_censored_window_end'
    for step in range(1,min(3,len(gray)-1-offset)+1):
        before=set(int(x) for x in tracker.ids)
        kept=tracker._track_existing(gray[offset+step-1],gray[offset+step],quality[offset+step])
        for tid in before-set(int(x) for x in kept.ids):
            accepted[tid][arm+'_termination']=tracker.last_death_reasons.get(tid,'Unknown')
        for tid,point in zip(kept.ids,kept.points):
            r=accepted[int(tid)];r[arm+'_offline_steps']+=1
            r[arm+'_offline_displacement_px']=float(np.linalg.norm(to_original(point,scale)-original[int(tid)]))
            if step==3:r[arm+'_termination']='completed_3_step_check'


def render_samples(selected,rows,manifest):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    destination=PAPER/'samples';destination.mkdir(exist_ok=False)
    by_frame={(r['sequence'],r['raw_index']):r['image'] for r in manifest}
    for seq in ['A02','A08','H02']:
        fig,axes=plt.subplots(4,3,figsize=(10,12),constrained_layout=True)
        fig.suptitle(seq+' | fixed samples | physical identity Unknown\nPrevious query / C current / SEA-RAFT current; circle accepted, x rejected',fontsize=11)
        for i,s in enumerate(x for x in selected if x['sequence']==seq):
            if s['event'] is None:
                for ax in axes[i]:ax.text(.05,.5,s['category']+': no event');ax.set_axis_off()
                continue
            raw,tid=s['event']
            r=next(r for r in rows if r['sequence']==seq and r['raw_index']==raw and r['track_id']==tid)
            for col,arm in enumerate(['previous','C','S']):
                image=cv2.imread(by_frame[(seq,raw-1 if col==0 else raw)],cv2.IMREAD_GRAYSCALE)
                point=np.array([r['previous_x'],r['previous_y']]) if col==0 else np.array([r[arm+'_x'],r[arm+'_y']])
                center=point if np.isfinite(point).all() else np.array([r['previous_x'],r['previous_y']])
                h,w=image.shape;cx=np.clip(center[0],48,w-49);cy=np.clip(center[1],48,h-49)
                ax=axes[i,col];ax.imshow(image,cmap='gray',vmin=0,vmax=255);ax.set_xlim(cx-48,cx+48);ax.set_ylim(cy+48,cy-48)
                if np.isfinite(point).all():
                    ax.plot(*point,marker='+' if col==0 else 'o' if r[arm+'_accepted'] else 'x',color='#F0E442' if col==0 else '#56B4E9' if arm=='C' else '#E69F00',markersize=10,markerfacecolor='none')
                title='{} raw {} ID {}\nB: {}'.format(s['category'],raw,tid,r['B_failure']) if col==0 else '{} accepted={} FB={:.2f}\noffline steps {}'.format(arm,r[arm+'_accepted'],r[arm+'_fb'],r[arm+'_offline_steps'])
                ax.set_title(title,fontsize=8);ax.tick_params(labelsize=7)
        fig.savefig(destination/(seq+'_natural_samples.png'),dpi=120);plt.close(fig)


def run_natural(model,contract):
    if not (RT/'natural_inputs/manifest.json').exists():
        cmd='source /opt/ros/noetic/setup.bash\nexport PYTHONPATH=.:scripts:$PYTHONPATH\n/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/prepare_searaft_inputs.py --natural'
        with (RT/'prepare_natural.log').open('x') as log:
            subprocess.run(['bash','-c',cmd],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    manifest=json.loads((RT/'natural_inputs/manifest.json').read_text())
    rows=[];times=[];summaries=[];selected=[];model_pairs_before=model.pairs
    for w in contract['windows']:
        seq=w['sequence'];files=[r for r in manifest if r['sequence']==seq]
        raw=[cv2.imread(r['image'],cv2.IMREAD_GRAYSCALE) for r in files]
        tick=time.perf_counter();gray=[];quality=[]
        for image in raw:
            work,scale=working(image,model.longest_edge)
            gray.append(PREPROCESS(work,'adaptive_clahe'));quality.append(score_image_quality(gray[-1]))
        prep=time.perf_counter()-tick
        tracker=KltTracker(KltConfig(**contract['klt']));sequence_rows=[]
        for i,(image,q) in enumerate(zip(gray,quality)):
            old_points,old_ids=tracker.points.copy(),tracker.ids.copy()
            tick=time.perf_counter();b,_=tracker.process(image,q);b_time=time.perf_counter()-tick
            lost=~np.isin(old_ids,b.ids)
            if not np.any(lost):continue
            points=to_original(old_points[lost],scale);ids=old_ids[lost]
            cx,cfb,ct=strong_lk(gray[i-1],image,old_points[lost],scale)
            cm=common_mask(points,cx,cfb,raw[i].shape)
            s=model.predict_points(raw[i-1],raw[i],points)
            current_rows=[]
            for k,tid in enumerate(ids):
                ca,sa=bool(cm[k]),bool(s['valid'][k])
                category='both' if ca and sa else 'C_only' if ca else 'S_only' if sa else 'neither'
                r=dict(sequence=seq,raw_index=w['raw_start']+i,stamp_ns=files[i]['stamp_ns'],track_id=int(tid),
                    previous_x=float(points[k,0]),previous_y=float(points[k,1]),B_failure=tracker.last_death_reasons.get(int(tid),'Unknown'),
                    C_x=float(cx[k,0]),C_y=float(cx[k,1]),C_fb=float(cfb[k]),C_accepted=ca,
                    S_x=float(s['points'][k,0]),S_y=float(s['points'][k,1]),S_fb=float(s['fb_error'][k]),S_accepted=sa,
                    category=category,C_offline_steps=0,S_offline_steps=0,C_termination='not_accepted',S_termination='not_accepted',
                    visual_identity='Unknown',physical_correctness='Unknown')
                for j in range(4):r['S_info_'+str(j)]=float(s['raw_info'][k,j])
                current_rows.append(r)
            offline_follow(current_rows,'C',i,gray,quality,scale,tracker.config)
            offline_follow(current_rows,'S',i,gray,quality,scale,tracker.config)
            sequence_rows.extend(current_rows)
            times.append(dict(sequence=seq,raw_index=w['raw_start']+i,queries=len(ids),B_s=b_time,C_raw_s=ct,**s['timing']))
            if i%25==0:print('NATURAL_PROGRESS',seq,i,len(sequence_rows),flush=True)
        counts=Counter(r['category'] for r in sequence_rows)
        long=sum(r['category']=='S_only' and r['S_offline_steps']==3 for r in sequence_rows)
        summaries.append(dict(sequence=seq,raw_frames=200,B_failure_events=len(sequence_rows),S_only_3steps=long,
            preprocessing_quality_s=prep,**{key:counts[key] for key in ['S_only','C_only','both','neither']}))
        for category in ['S_only','C_only','both','neither']:
            group=[r for r in sequence_rows if r['category']==category]
            key=lambda r:hashlib.sha256('{sequence}/{raw_index}/{track_id}'.format(**r).encode()).hexdigest()
            chosen=min(group,key=key) if group else None
            selected.append(dict(sequence=seq,category=category,event=[chosen['raw_index'],chosen['track_id']] if chosen else None,visual_identity='Unknown'))
        write_csv(RT/('natural_'+seq+'_checkpoint.csv'),sequence_rows)
        rows.extend(sequence_rows)
        print('NATURAL_COMPLETE',seq,counts,flush=True)
    write_csv(PAPER/'natural_results.csv',rows);write_csv(PAPER/'natural_timing.csv',times)
    render_samples(selected,rows,manifest)
    count_pass=sum(r['S_only_3steps']>=5 for r in summaries)>=2
    return dict(sequence_summaries=summaries,selected_samples=selected,model_pairs=model.pairs-model_pairs_before,
        opportunity_count_pass=bool(count_pass),opportunity_pass=False,visual_review='PENDING',
        identity='Unknown; offline ordinary LK is not independent truth')
