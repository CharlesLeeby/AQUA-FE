#!/usr/bin/env python3
"""Serial frozen batch, resumable only by immutable receipts; no outcome-based retries."""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
import threading
from run_classical_opportunity_expansion import ROOT,PAPER,RUNTIME,PYTHON,sha,save,verify

def invoke(cmd,log):
    with log.open('x') as f:
        p=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    return p.returncode,log.read_text(errors='replace')

def prepare_windows(windows,wait_first_pid):
    try:
        for i,w in enumerate(windows):
            slug=w["run_slug"];ready=RUNTIME/"frontend"/slug/"independent_delivery_receipt.json"
            if i==0 and wait_first_pid:
                while Path(f"/proc/{wait_first_pid}").exists() and not ready.exists():time.sleep(10)
            if ready.exists():continue
            error=RUNTIME/"window_failures"/f"{slug}.json"
            if error.exists():continue
            cmd=["taskset","-c","0,6",PYTHON,str(ROOT/"scripts/run_classical_opportunity_expansion.py"),"--window",slug,"--frontend"]
            while True:
                logfile=RUNTIME/"controller_logs"/f"{slug}.frontend.{time.time_ns()}.log"
                print("FRONTEND_START",slug,str(logfile),flush=True)
                rc,text=invoke(cmd,logfile)
                if not rc:break
                if "WAITING_RESOURCE" in text:
                    print("WAITING_RESOURCE_FRONTEND",slug,flush=True);time.sleep(30);continue
                save(error,dict(run_slug=slug,status="FAIL",stage="frontend",reason="FRONTEND_STRUCTURAL_FAILURE",returncode=rc,console=str(logfile),console_sha256=sha(logfile),time=datetime.now(timezone.utc).isoformat()))
                print("STRUCTURAL_FAILURE_RETAINED",slug,flush=True);break
    except Exception as exc:
        save(RUNTIME/f"controller_preparation_error_{time.time_ns()}.json",dict(error=str(exc)))
        raise

def run(batch,wait_first_pid=0):
    lock=verify()
    if batch=='B':
        gate=json.loads((RUNTIME/'batch_A_gate.json').read_text())
        assert gate['execute_batch_B'],'Batch B is not authorized by the frozen gate'
    windows=sorted([w for w in lock['windows'] if w['batch']==batch],key=lambda w:int(w['batch_order']))
    producer=threading.Thread(target=prepare_windows,args=(windows,wait_first_pid),daemon=True)
    producer.start()
    for w in windows:
        slug=w['run_slug'];error=RUNTIME/'window_failures'/f'{slug}.json'
        ready=RUNTIME/'frontend'/slug/'independent_delivery_receipt.json'
        while not ready.exists() and not error.exists():
            if not producer.is_alive():raise RuntimeError('Frontend producer stopped before ready receipt: '+slug)
            print('WAITING_FRONTEND',slug,flush=True);time.sleep(30)
        if error.exists():
            print('RETAIN_PREVIOUS_STRUCTURAL_FAILURE',slug,flush=True);continue
        for arm in ['B','C-all']:
            for repeat in [1,2,3]:
                cmd=['taskset','-c','2,3,8,9',PYTHON,str(ROOT/'scripts/run_classical_opportunity_expansion.py'),
                    '--window',slug,'--arm',arm,'--repeat',str(repeat)]
                while True:
                    logfile=RUNTIME/'controller_logs'/f'{slug}.{arm}.r{repeat}.{time.time_ns()}.log'
                    rc,text=invoke(cmd,logfile)
                    print(text[-1600:],flush=True)
                    if not rc:break
                    if 'WAITING_RESOURCE' in text or 'Address already in use' in text:
                        print('WAITING_RESOURCE',slug,arm,repeat,flush=True);time.sleep(30);continue
                    if 'CAPACITY_UNSUPPORTED' in text:
                        save(error,dict(run_slug=slug,status='FAIL',stage='capacity_preflight',reason='CAPACITY_UNSUPPORTED',console=str(logfile),console_sha256=sha(logfile)))
                        break
                    raise RuntimeError('Unresolved infrastructure/identity error; preserve outputs: '+str(logfile))
                if error.exists():break
            if error.exists():break
        print('WINDOW_RESOLVED',slug,flush=True)
        # Analysis cannot affect subsequent arm ordering or source generation.
        from analyze_classical_opportunity_expansion import analyze
        analyze()
    producer.join()
    from analyze_classical_opportunity_expansion import analyze
    result=analyze()
    snapshot=PAPER/f'checkpoint_batch_{batch}'
    if not snapshot.exists():
        snapshot.mkdir()
        for n in ['decision.json','window_outcomes.csv','case_registry.csv','frontend_audit.csv','backend_results.csv']:
            with (snapshot/n).open('xb') as f:f.write((PAPER/n).read_bytes())
    if batch=='A':
        from run_additive_budget_v1 import rows
        out=[r for r in rows(PAPER/'window_outcomes.csv') if r['batch']=='A']
        assert len(out)==12 and not any(r['classification']=='PENDING' for r in out)
        gains=sum(r['classification']=='PRACTICAL_GAIN' for r in out)
        severe=sum(r['severe_regression']=='True' for r in out)
        structural=sum(r['structural_failure']=='True' for r in out)
        gate=dict(batch='A',practical_gain=gains,severe_regression=severe,structural_failure_windows=structural,
            execute_batch_B=gains>=1 and severe<=1 and structural<2,
            evidence_window_outcomes_sha256=sha(PAPER/'window_outcomes.csv'),
            timestamp=datetime.now(timezone.utc).isoformat())
        if not (RUNTIME/'batch_A_gate.json').exists():save(RUNTIME/'batch_A_gate.json',gate)
        else:
            old=json.loads((RUNTIME/'batch_A_gate.json').read_text());assert old['execute_batch_B']==gate['execute_batch_B']
        print('BATCH_A_GATE',json.dumps(gate),flush=True)
        analyze()
    print('BATCH_FINISHED',batch,flush=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--batch',required=True,choices=['A','B']);p.add_argument('--wait-first-pid',type=int,default=0);a=p.parse_args()
    with (RUNTIME/'controller.lock').open('a') as f:
        fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);run(a.batch,a.wait_first_pid)

if __name__=='__main__':main()
