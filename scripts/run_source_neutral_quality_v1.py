#!/usr/bin/env python3
"""Small frozen-input experiment using the original additive binary and runner."""
import argparse
import copy
import csv
import fcntl
import json
import os
import re
import subprocess
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from convert_source_neutral_quality_v1 import ROOT, PAPER, OLD, SOURCE, RUNTIME, SLUGS, sha, save
import run_additive_budget_backend as leaf

CONTRACT = RUNTIME / 'contract'
ARMS = ['B', 'L-original', 'L-neutral']


def motion(path):
    if not path.exists() or not path.stat().st_size:
        return dict(finite=False, poses=0, excursion_m=None)
    with path.open() as stream:
        values = np.array([[float(x) for x in line.split(',')[:8]] for line in stream])
    finite = bool(np.isfinite(values).all())
    return dict(finite=finite, poses=len(values),
                excursion_m=float(np.max(np.linalg.norm(values[:, 1:4] - values[0, 1:4], axis=1))) if finite else None)


def verify_environment(lock):
    for p, h in lock['files'].items():
        assert sha(p) == h, p
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(Path(lock['library']).parent) + ':' + env.get('LD_LIBRARY_PATH', '')
    ldd = subprocess.check_output(['ldd', lock['binary']], env=env, text=True)
    assert 'not found' not in ldd
    dependencies = {}
    for line in ldd.splitlines():
        m = re.search(r'=> (/\S+)', line)
        if m:
            p = str(Path(m.group(1)).resolve())
            dependencies[p] = sha(p)
            assert dependencies[p] in lock['files'].values(), 'Unfrozen dynamic dependency: ' + p
    assert dependencies[str(Path(lock['library']).resolve())] == sha(lock['library'])
    return dependencies


def prepare():
    original = json.loads((OLD / 'source_and_backend_lock.json').read_text())
    windows = [next(w for w in original['windows'] if w['run_slug'] == slug) for slug in SLUGS]
    lock = json.loads((OLD / 'backend_execution_lock_v2.json').read_text())
    dependencies = verify_environment(lock)
    lock.update(ros_port=12691, task='source-neutral-quality-v1', new_AA_required=False)
    for name in ['convert_source_neutral_quality_v1.py', 'run_source_neutral_quality_v1.py',
                 'report_source_neutral_quality_v1.py']:
        path = ROOT / 'scripts' / name
        lock['files'][str(path)] = sha(path)
    receipts, limits = [], {}
    for w in windows:
        slug = w['run_slug']
        receipt = json.loads((RUNTIME / 'frontend' / slug / 'receipt.json').read_text())
        assert receipt['input_only_quality_sigma_changed'] and receipt['original_mapping_reproduced_exactly']
        receipts.append(receipt)
        oldcap = json.loads((OLD / 'capacity' / (slug + '.json')).read_text())
        capacity = {'arms': {}}
        for arm in ARMS:
            capacity['arms'][arm] = copy.deepcopy(oldcap['arms']['B' if arm == 'B' else 'L-all'])
            capacity['arms'][arm].update(feature_bag=receipt['arms'][arm]['feature_bag'],
                                         feature_bag_sha256=receipt['arms'][arm]['sha256'])
        save(CONTRACT / 'capacity' / (slug + '.json'), capacity)
        historic = [motion(SOURCE / 'backend' / slug / 'B' / f'repeat{r}' / 'vins_output/vio.csv')['excursion_m'] for r in [1, 2, 3]]
        limits[slug] = 10 * max(1., *historic)
    order = [(slug, 'B', r) for slug in SLUGS for r in [1, 2, 3]]
    for slug in SLUGS:
        for r in [1, 2, 3]:
            for arm in (['L-neutral', 'L-original'] if r == 2 else ['L-original', 'L-neutral']):
                order.append((slug, arm, r))
    save(CONTRACT / 'source_and_backend_lock.json', {'windows': windows})
    save(CONTRACT / 'backend_execution_lock.json', lock)
    plan = dict(task='source-neutral-quality-v1', stage='development', windows=windows,
                order=order, planned_replays=18, baseline_replays_included=6,
                catastrophic_excursion_limit_m=limits, exact_dynamic_dependencies=dependencies,
                backend_execution_lock=lock, frontend_receipts=receipts,
                maximum_additional_engineering_verifications=3,
                extension_replays_authorized_only_after_promising_result=36)
    save(PAPER / 'run_plan.json', plan)
    print('PLAN_FROZEN', '18 replays; baseline excursion guard', limits, flush=True)


def received(path):
    out = Counter()
    if path.exists():
        for row in csv.reader(path.open()):
            if row[0] == 'received':
                out[int(row[2])] += int(row[3])
    return out


def run():
    plan = json.loads((PAPER / 'run_plan.json').read_text())
    leaf.PAPER, leaf.RUNTIME = CONTRACT, RUNTIME
    leaf.EXECUTION_LOCK = CONTRACT / 'backend_execution_lock.json'
    source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    with (RUNTIME / 'backend.lock').open('a') as mutex:
        fcntl.flock(mutex, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (RUNTIME / 'stopped.json').exists():
            raise RuntimeError('Experiment already stopped; no automatic rerun')
        for slug, arm, repeat in plan['order']:
            target = RUNTIME / 'backend' / slug / arm / f'repeat{repeat}'
            if (target / 'task_check.json').exists():
                continue
            wait_start = time.monotonic()
            while leaf.other_replays():
                print('WAITING_RESOURCE', slug, arm, repeat, flush=True)
                if time.monotonic() - wait_start > 600:
                    raise RuntimeError('Resource unavailable for 10 minutes; no run launched')
                time.sleep(30)
            dependencies = verify_environment(plan['backend_execution_lock'])
            for w in plan['windows']:
                if w['run_slug'] == slug:
                    for name in ['backend_config_source', 'camera']:
                        assert sha(w[name]) == w[name + '_sha256']
            started = datetime.now(timezone.utc).isoformat()
            leaf.run(slug, arm, repeat)
            receipt = json.loads((target / 'receipt.json').read_text())
            state = motion(target / 'vins_output/vio.csv')
            expected = SOURCE / 'backend' / slug / ('B' if arm == 'B' else 'L-all') / 'repeat1/backend_use.csv'
            complete = received(target / 'backend_use.csv') == received(expected)
            anomaly = (not state['finite'] or not complete or receipt['status'] != 'COMPLETE' or
                       state['excursion_m'] > plan['catastrophic_excursion_limit_m'][slug])
            check = dict(run_slug=slug, arm=arm, repeat=repeat, source_commit=source_commit,
                         exact_started_at=started, ended_at=datetime.now(timezone.utc).isoformat(),
                         received_per_ID_complete=complete, raw_motion=state, severe_anomaly=anomaly,
                         excursion_limit_m=plan['catastrophic_excursion_limit_m'][slug],
                         status='SEVERE_ANOMALY' if anomaly else 'PASS')
            save(target / 'task_check.json', check)
            print('RUN_CHECK', slug, arm, repeat, check['status'], state, flush=True)
            if anomaly and arm == 'B':
                # Exactly one direct check. No speculative fixes or repeat selection.
                post = dict(other_replays=leaf.other_replays(), dependency_identity='PASS',
                            original_binary_unchanged=True, exact_math_config_unchanged=True,
                            input_hash_pass=sha(receipt['feature_bag']) == receipt['feature_bag_sha256'],
                            engineering_cause='Unknown', additional_verifications=0)
                verify_environment(plan['backend_execution_lock'])
                save(RUNTIME / 'stopped.json', dict(status='EVALUATION_BLOCKED', failed_run=check,
                     direct_check=post, reason='Severe fresh B anomaly without a demonstrated engineering correction'))
                print('EVALUATION_BLOCKED: retained baseline anomaly; no accuracy claim', flush=True)
                return
    print('DEVELOPMENT_MATRIX_COMPLETE', len(plan['order']), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'run'])
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else run()
