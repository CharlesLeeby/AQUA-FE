#!/usr/bin/env python3
"""Resume serial backend cells as immutable frontend receipts become available.

Does not launch frontend jobs, alter contracts or rerun receipted failures.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import subprocess
import time
from run_additive_budget_v1 import ROOT,PAPER,RUNTIME,PYTHON,save


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--start-window',default='a09_6000_6800');args=parser.parse_args()
    windows=json.loads((PAPER/'source_and_backend_lock.json').read_text())['windows']
    start=next(i for i,w in enumerate(windows) if w['run_slug']==args.start_window)
    for w in windows[start:]:
        slug=w['run_slug']
        while not (RUNTIME/'frontend'/slug/'receipt.json').exists():
            print('WAITING_FRONTEND',slug,datetime.now(timezone.utc).isoformat(),flush=True)
            time.sleep(30)
        if not (PAPER/'capacity'/f'{slug}.json').exists():
            subprocess.run([PYTHON,str(ROOT/'scripts/audit_additive_budget_capacity.py'),'--window',slug],cwd=ROOT,check=True)
        for arm in ['B','L6','L-all','C-all']:
            for repeat in [1,2,3]:
                # The frozen leaf checks existing receipts and refuses overwrite.
                cmd=['taskset','-c','2,3,8,9',PYTHON,str(ROOT/'scripts/run_additive_budget_backend.py'),
                     '--window',slug,'--arm',arm,'--repeat',str(repeat)]
                wait_start=time.monotonic()
                while True:
                    proc=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
                    print(proc.stdout,flush=True)
                    if proc.returncode==0:break
                    if 'WAITING_RESOURCE' not in proc.stdout or time.monotonic()-wait_start>600:
                        raise RuntimeError('Recover at: '+' '.join(cmd))
                    time.sleep(30)
        print('WINDOW_BACKEND_FINISHED',slug,flush=True)


if __name__=='__main__':main()
