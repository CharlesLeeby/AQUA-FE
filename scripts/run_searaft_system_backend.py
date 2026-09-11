#!/usr/bin/env python3
"""Adapt the frozen serial runner; no backend rebuild or additional repeats."""
import fcntl,json
from run_searaft_system_probe import ROOT,PAPER,RT,save
import run_additive_budget_v1 as resources
import run_additive_budget_backend as runner

def main():
    assert (RT/'frontend_complete.json').exists(), 'Complete frontend structure checks first'
    resources.ROOT,resources.RUNTIME=ROOT,RT
    runner.ROOT,runner.PAPER,runner.RUNTIME=ROOT,PAPER,RT
    runner.EXECUTION_LOCK=PAPER/'backend_execution_lock_v2.json'
    with (RT/'backend.lock').open('a') as local,open('/tmp/aquafe_classical_expansion_backend_advisory.lock','a') as shared:
        for f in (local,shared):fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        plan=[]
        for w in json.loads((PAPER/'input_manifest.json').read_text())['windows']:
            slug=w['run_slug'];receipt=json.loads((RT/'frontend'/slug/'receipt.json').read_text())
            assert receipt['input_structural_pass'] and not receipt['baseline_mismatch'], receipt
            same=receipt['C_R_different_feature_frames']==0
            for arm in ('B','C','R'):
                for rep in range(1,4):
                    plan.append(dict(run_slug=slug,arm=arm,repeat=rep,mapped_to='C' if same and arm=='R' else arm))
        path=RT/'backend_plan.json'
        if path.exists():assert json.loads(path.read_text())==plan
        else:save(path,plan)
        for row in plan:
            if row['mapped_to']!=row['arm']:
                # Local evaluator alias only; backend_plan explicitly records
                # that no R replay was performed for identical full inputs.
                alias=RT/'backend'/row['run_slug']/row['arm']
                if not alias.exists():alias.symlink_to(row['mapped_to'],target_is_directory=True)
                continue
            runner.run(row['run_slug'],row['arm'],row['repeat'])
        print('FIXED_MATRIX_COMPLETE',sum(p['arm']==p['mapped_to'] for p in plan),flush=True)

if __name__=='__main__':main()
