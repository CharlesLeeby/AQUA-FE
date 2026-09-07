#!/usr/bin/env python3
"""Separate first/current admission from continuation; no outcome labels as features."""
from collections import defaultdict
import gzip,json
import numpy as np
import pandas as pd
import rosbag
from analyze_observation_utility_v1 import OLD,PAPER,RUNTIME,SOURCE,FEATURE,rows,table,stats,flow_jacobian,infometrics,save,sha

def main():
 out=[];birthinfo=[];missing=[]
 for w in json.loads((OLD/'source_and_backend_lock.json').read_text())['windows']:
  slug=w['run_slug'];d=RUNTIME/'existing_data'/slug
  if not (d/'receipt.json').exists():continue
  frame=pd.read_csv(d/'observations.csv.gz')
  for arm in ['B','L-all','C-all']:
   for cohort in ['first_publication_or_readmission','continuation']:
    sub=frame[(frame.arm==arm)&((frame.public_streak_so_far==1) if cohort.startswith('first') else (frame.public_streak_so_far>1))]
    z=dict(run_slug=slug,arm=arm,cohort=cohort,observations=len(sub))
    for c in frame.columns:
     if c not in ['run_slug','arm','frame','stamp_ns','track_id']:z.update(stats(sub[c].to_numpy(),c+'_'))
    out.append(z)
    if cohort.startswith('first'):
     missing.append(dict(run_slug=slug,arm=arm,first_publication_rows=len(sub),two_frame_motion_available=int(sub.rotation_compensated_parallax_norm.notna().sum()),first_admission_true_private_parallax='Unknown: only previously eligible source observations saved',parallax_so_far_at_first_publication='recorded-history lower bound; not complete private age displacement'))
  base=[]
  with rosbag.Bag(w['baseline_bag']) as b:
   for _,m,_ in b.read_messages(topics=[FEATURE]):base.append(m)
  for source,arm in [('xfeat','L-all'),('classical_gftt','C-all')]:
   prev=set()
   for f,(m,line) in enumerate(zip(base,(SOURCE/'frontend'/slug/(source+'_source.jsonl')).open())):
    rec=json.loads(line);obs=rec['observations'];new=[o for o in obs if o['source_id'] not in prev];prev={o['source_id'] for o in obs}
    if not new:continue
    bc={c.name:c.values for c in m.channels};bx=np.array([[p.x,p.y] for p in m.points]);x=np.array([o['normalized'] for o in new]);j=flow_jacobian(x);jb=flow_jacobian(bx)
    for weight in ['original_q','unit_q']:
     z=infometrics(jb,j,np.array(bc['quality']) if weight=='original_q' else np.ones(len(bx)),np.array([o['quality'] for o in new]) if weight=='original_q' else np.ones(len(new)))
     z.update(run_slug=slug,arm=arm,frame=f,stamp_ns=rec['stamp_ns'],weighting=weight,cohort='first_publication_or_readmission',model='unit_depth_flow');birthinfo.append(z)
  print('ADMISSION',slug,flush=True)
 table(PAPER/'admission_cohort_summary.csv',out);table(PAPER/'first_admission_availability.csv',missing)
 p=RUNTIME/'first_admission_information_frames.csv';table(p,birthinfo);summary=[]
 for w in sorted({r['run_slug'] for r in birthinfo}):
  for arm in ['L-all','C-all']:
   for weight in ['original_q','unit_q']:
    sub=[r for r in birthinfo if r['run_slug']==w and r['arm']==arm and r['weighting']==weight];r=dict(run_slug=w,arm=arm,weighting=weight,frames=len(sub))
    for k in ['logdet_gain','trace_gain','min_eigen_gain','weak_direction_gain','condition_change','individual_logdet_median','nearest_KLT_row_cosine_median']:
     r.update(stats([z[k] for z in sub if k in z],k+'_'))
    summary.append(r)
 table(PAPER/'first_admission_information_summary.csv',summary);save(PAPER/'admission_analysis_provenance.json',{'script_sha256':sha(__file__),'detail_path':str(p),'detail_sha256':sha(p),'windows_completed':len({r['run_slug'] for r in out}),'causal_point_labels':'Unknown','no_threshold_search':True})
if __name__=='__main__':main()
