#!/usr/bin/env python3
"""Strict A/A-first use of frozen leaf runner; no algorithmic config changes."""
from pathlib import Path
import argparse,fcntl,json,os,subprocess,time
import numpy as np
import run_additive_budget_backend as leaf
from analyze_observation_utility_v1 import ROOT,PAPER,OLD,RUNTIME,SOURCE,sha,save,table
WINDOWS=['a02_0_900','a08_2700_3600','afrl_bus_s180_d045']

def freeze():
 base=json.loads((OLD/'backend_execution_lock_v2.json').read_text());build=json.loads((PAPER/'backend_utility_build_receipt.json').read_text())
 for variant in ['frozen','diagnostic']:
  lock=dict(base);lock.update(ros_port=12681)
  if variant=='diagnostic':lock.update(binary=build['binary'],library=build['library'])
  lock['files']=dict(base['files'])
  for p in [Path(lock['binary']),Path(lock['library']),Path(__file__),ROOT/'scripts/build_observation_utility_backend.py',PAPER/'backend_utility_build_receipt.json',PAPER/'research_questions.md',PAPER/'backend_utility.patch',PAPER/'backend_utility_header.txt']:
   lock['files'][str(p)]=sha(p)
  lock['utility_log_only']=True;path=PAPER/('execution_'+variant+'_lock.json');assert not path.exists();save(path,lock)
 save(PAPER/'diagnostic_plan.json',dict(windows=WINDOWS,aa=[dict(window=w,variants=['frozen','diagnostic']) for w in WINDOWS],formal_max=27,formal_arms=['B','L-all','C-all'],repeats=[1,2,3],position_max_tolerance_m=1e-5,orientation_max_tolerance_rad=1e-5,exact_timestamps_required=True,aa_all_required=True,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()))

def run_one(w,arm,r,variant,role):
 path=RUNTIME/role/variant;path.mkdir(parents=True,exist_ok=True);(path/'tmp').mkdir(exist_ok=True)
 if not (path/'frontend').exists():(path/'frontend').symlink_to(SOURCE/'frontend',target_is_directory=True)
 leaf.RUNTIME=path;leaf.ROOT=ROOT;leaf.EXECUTION_LOCK=PAPER/('execution_'+variant+'_lock.json')
 target=path/'backend'/w/arm/('repeat'+str(r))
 # Frozen runner intentionally strips AQUAFE_*; add diagnostic env at launch through a scoped Popen wrapper.
 original=leaf.subprocess.Popen
 def diagnostic_popen(*args,**kwargs):
  env=kwargs.get('env')
  if env is not None and variant=='diagnostic':env['AQUAFE_UTILITY_LOG']=str(target/'utility.csv')
  return original(*args,**kwargs)
 leaf.subprocess.Popen=diagnostic_popen
 try:
  while True:
   found=leaf.other_replays()
   if not found:break
   print('WAITING_RESOURCE',json.dumps(found),flush=True);time.sleep(20)
  leaf.run(w,arm,r)
 finally:leaf.subprocess.Popen=original
 receipt=json.loads((target/'receipt.json').read_text());assert receipt['status']=='COMPLETE',receipt['status']
 return target

def compare(w):
 paths=[RUNTIME/'aa'/v/'backend'/w/'B/repeat1/vins_output/vio.csv' for v in ['frozen','diagnostic']]
 txt=[p.read_text().splitlines() for p in paths];ts=[[l.split(',')[0] for l in lines] for lines in txt]
 a,b=[np.array([[float(x) for x in l.split(',') if x] for l in lines]) for lines in txt]
 equal=ts[0]==ts[1];pmax=qmax=None
 if equal:
  pmax=float(np.linalg.norm(a[:,1:4]-b[:,1:4],axis=1).max());qa=a[:,4:8];qb=b[:,4:8];qa=qa/np.linalg.norm(qa,axis=1,keepdims=True);qb=qb/np.linalg.norm(qb,axis=1,keepdims=True)
  qmax=float((2*np.arccos(np.clip(np.abs(np.sum(qa*qb,axis=1)),-1,1))).max())
 status='PASS' if equal and pmax<=1e-5 and qmax<=1e-5 else 'FAIL'
 return dict(run_slug=w,status=status,exact_timestamps=equal,poses_frozen=len(a),poses_diagnostic=len(b),position_max_m=pmax,orientation_max_rad=qmax,frozen_path=str(paths[0]),diagnostic_path=str(paths[1]),frozen_sha256=sha(paths[0]),diagnostic_sha256=sha(paths[1]),tolerance_m=1e-5,tolerance_rad=1e-5,alignment='none')

def main():
 p=argparse.ArgumentParser();p.add_argument('--freeze',action='store_true');p.add_argument('--aa',action='store_true');p.add_argument('--formal',action='store_true');a=p.parse_args()
 with (RUNTIME/'diagnostics.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if a.freeze:freeze()
  if a.aa:
   results=[]
   for w in WINDOWS:
    for variant in ['frozen','diagnostic']:run_one(w,'B',1,variant,'aa')
    r=compare(w);results.append(r);print('AA',json.dumps(r),flush=True);table(PAPER/'diagnostic_aa.csv',results)
   save(PAPER/'diagnostic_aa_decision.json',dict(status='PASS' if all(r['status']=='PASS' for r in results) else 'FAIL',results=results,formal_authorized=all(r['status']=='PASS' for r in results),formal_replay_count=0,diagnostic_state_usable_for_mechanism=all(r['status']=='PASS' for r in results)))
  if a.formal:
   aa=json.loads((PAPER/'diagnostic_aa_decision.json').read_text());assert aa['status']=='PASS','A/A failed; formal diagnostics forbidden'
   for w in WINDOWS:
    for arm in ['B','L-all','C-all']:
     for r in [1,2,3]:run_one(w,arm,r,'diagnostic','formal')
if __name__=='__main__':main()
