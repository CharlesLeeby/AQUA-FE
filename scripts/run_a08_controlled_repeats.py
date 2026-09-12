#!/usr/bin/env python3
"""Three bounded KLT repeats; call immutable old runner with external telemetry."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT/'papers/frontend_a08_controlled_repeats_v1'
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a08_controlled_repeats_v1')
OWNER = Path('/home/ma/AQUA-FE_WS_additive_budget_v1')
OLDP = OWNER/'papers/frontend_additive_budget_v1'
OLD_RUN = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_additive_budget_v1')
REF = '49c02471716e8ac960e35dd9dd44ef6fbb1428c6'
SLUG = 'a08_2700_3600'
LOCK = PAPER/'execution_lock.json'
CPUS = {2, 3, 8, 9}


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(2**20), b''): h.update(b)
    return h.hexdigest()


def save(p, value):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f: json.dump(value, f, indent=2, sort_keys=True); f.write('\n')


def resource_state():
    return dict(at=now(), root_free=shutil.disk_usage(ROOT).free,
        runtime_free=shutil.disk_usage(RUNTIME.parent).free,
        available_memory=next(int(l.split()[1])*1024 for l in Path('/proc/meminfo').read_text().splitlines()
                              if l.startswith('MemAvailable:')), loadavg=os.getloadavg())


def resource_ok(s):
    return s['root_free'] >= 2*2**30 and s['runtime_free'] >= 8*2**30 and s['available_memory'] >= 4*2**30


def preflight():
    s = resource_state()
    if not resource_ok(s): raise RuntimeError('RESOURCE_LIMIT '+json.dumps(s))
    return s


def public_env(raw):
    allowed = {'PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
               'OPENBLAS_NUM_THREADS', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR'}
    env = dict(x.split('=', 1) for x in raw.decode(errors='replace').split('\0') if '=' in x)
    return {k: v for k, v in env.items() if k in allowed or k.startswith(('ROS_', 'VINS_', 'AQUAFE_'))}


def load_legacy():
    # Import has no experiment side effects; modules use -B to avoid old-workspace writes.
    sys.path.insert(0, str(OWNER/'scripts'))
    import run_additive_budget_backend as legacy
    legacy.ROOT, legacy.PAPER, legacy.RUNTIME = ROOT, PAPER, RUNTIME
    legacy.EXECUTION_LOCK, legacy.resource_check = LOCK, preflight
    return legacy


def freeze():
    pre = preflight()
    if LOCK.exists() or RUNTIME.exists(): raise RuntimeError('Refuse existing freeze/runtime')
    paths = ['scripts/run_additive_budget_backend.py', 'scripts/run_additive_budget_v1.py',
             'scripts/wait_for_ros_subscribers.py',
             'papers/frontend_additive_budget_v1/source_and_backend_lock.json',
             'papers/frontend_additive_budget_v1/backend_execution_lock_v2.json',
             'papers/frontend_additive_budget_v1/capacity/'+SLUG+'.json']
    for rel in paths:
        assert (OWNER/rel).read_bytes() == subprocess.check_output(['git', 'show', REF+':'+rel], cwd=ROOT), rel
    assert sha(ROOT/'scripts/wait_for_ros_subscribers.py') == sha(OWNER/'scripts/wait_for_ros_subscribers.py')
    original = json.loads((OLDP/'backend_execution_lock_v2.json').read_text())
    w = next(w for w in json.loads((OLDP/'source_and_backend_lock.json').read_text())['windows'] if w['run_slug']==SLUG)
    front = json.loads((OLD_RUN/'frontend'/SLUG/'receipt.json').read_text())
    cap = json.loads((OLDP/'capacity'/f'{SLUG}.json').read_text())
    assert front['arms']['B']['sha256'] == cap['arms']['B']['feature_bag_sha256'] == w['baseline_sha256']
    for key, hkey in [('baseline_bag','baseline_sha256'),('camera','camera_sha256'),
                      ('backend_config_source','backend_config_source_sha256')]:
        assert sha(w[key]) == w[hkey], 'Frozen source identity drift '+key
    files = dict(original['files'])
    for p in [*(OWNER/r for r in paths), Path(w['baseline_bag']), Path(w['camera']), Path(w['backend_config_source']),
              Path(__file__), ROOT/'scripts/audit_a08_existing_replays.py', ROOT/'tests/test_a08_controlled_repeats.py',
              ROOT/'scripts/wait_for_ros_subscribers.py', PAPER/'preregistration.md']:
        files[str(p)] = sha(p)
    for p,h in files.items():
        assert sha(p) == h, 'Locked dependency drift '+p
    save(PAPER/'source_and_backend_lock.json', {'windows':[w], 'source_evidence_commit':REF})
    save(PAPER/'capacity'/f'{SLUG}.json', dict(run_slug=SLUG, arms={'B':cap['arms']['B']}))
    save(RUNTIME/'frontend'/SLUG/'receipt.json', {'arms':{'B':front['arms']['B']}, 'reference_only':True})
    (RUNTIME/'tmp').mkdir()
    for p in [PAPER/'source_and_backend_lock.json', PAPER/'capacity'/f'{SLUG}.json', RUNTIME/'frontend'/SLUG/'receipt.json']:
        files[str(p)] = sha(p)
    original.update(files=files, frozen_at=now(), ros_port=12701, repeats=3,
        order=[{'window':SLUG, 'arm':'B', 'repeat':r} for r in (1,2,3)],
        cpu_affinity=sorted(CPUS), resource_pre=pre, source_evidence_commit=REF,
        wrapper_identity='main@f6f8feec66c2faf1f59cdb67c1e817028a3bccaf + files SHA',
        original_execution_lock_sha256=sha(OLDP/'backend_execution_lock_v2.json'))
    save(LOCK, original)
    print('FROZEN', LOCK, flush=True)


def observe(proc, target, stop, identity, samples, errors):
    try:
        if stop.wait(1): return
        base = Path(f'/proc/{proc.pid}')
        identity.update(at=now(), pid=proc.pid, executable=os.readlink(base/'exe'),
            environment=public_env((base/'environ').read_bytes()),
            environment_bytes_sha256=hashlib.sha256((base/'environ').read_bytes()).hexdigest(),
            command=(base/'cmdline').read_bytes().decode().replace('\0', ' ').strip(),
            maps=(base/'maps').read_text(), stat=(base/'stat').read_text())
        while not stop.is_set() and proc.poll() is None:
            sample = resource_state()
            text = (base/'status').read_text()
            sample.update(affinity=sorted(os.sched_getaffinity(proc.pid)),
                status=[l for l in text.splitlines() if l.startswith(('VmRSS:', 'Threads:', 'Cpus_allowed_list:'))],
                cpu_stat=Path('/proc/stat').read_text().splitlines()[:13])
            samples.append(sample)
            if not resource_ok(sample):
                errors.append('RESOURCE_LIMIT '+json.dumps(sample))
                os.killpg(proc.pid, signal.SIGINT)
                break
            if stop.wait(5): break
    except Exception as exc:
        errors.append(type(exc).__name__+': '+str(exc))


class ObservedSubprocess:
    """Proxy only in legacy module; never patch the shared subprocess module."""
    def __init__(self, binary, target):
        self.binary, self.target = binary, target
        self.stop = threading.Event()
        self.thread = None
        self.identity, self.samples, self.errors, self.starts = {}, [], [], []

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def Popen(self, command, **kwargs):
        at = now()
        p = subprocess.Popen(command, **kwargs)
        self.starts.append(dict(at=at, pid=p.pid, command=command))
        if command[0] == self.binary:
            self.thread = threading.Thread(target=observe,
                args=(p,self.target,self.stop,self.identity,self.samples,self.errors), daemon=True)
            self.thread.start()
        return p

    def finish(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=6)


def run_all():
    lock = json.loads(LOCK.read_text())
    legacy = load_legacy()
    os.sched_setaffinity(0, CPUS)
    with (RUNTIME/'backend.lock').open('a') as f:
        fcntl.flock(f, fcntl.LOCK_EX|fcntl.LOCK_NB)
        for repeat in (1,2,3):
            target = RUNTIME/'backend'/SLUG/'B'/f'repeat{repeat}'
            if target.exists():
                receipt = json.loads((target/'receipt.json').read_text())
                telemetry = json.loads((target/'telemetry_receipt.json').read_text())
                assert all(sha(p)==h for p,h in receipt['artifacts'].items())
                assert telemetry['execution_lock_sha256']==sha(LOCK)
                print('EXISTING_RETAINED',repeat,receipt['status'],flush=True)
                if receipt['status']=='RESOURCE_LIMIT' or any('RESOURCE_LIMIT' in s for s in telemetry['errors']): break
                continue
            preflight()
            proxy = ObservedSubprocess(lock['binary'],target)
            legacy.subprocess = proxy
            started = now()
            try:
                legacy.run(SLUG,'B',repeat)
            finally:
                proxy.finish()
            mapped = {}
            for line in proxy.identity.pop('maps','').splitlines():
                fields = line.split(maxsplit=5)
                if len(fields)==6 and fields[5].startswith('/'):
                    p = Path(fields[5])
                    if p.is_file(): mapped[str(p)] = sha(p)
            receipt = json.loads((target/'receipt.json').read_text())
            save(target/'telemetry_receipt.json',dict(started_at=started, ended_at=now(),
                process_starts=proxy.starts, actual_node=proxy.identity, loaded_files=mapped,
                samples=proxy.samples, errors=proxy.errors, execution_lock_sha256=sha(LOCK),
                runner_receipt_sha256=sha(target/'receipt.json')))
            print('TELEMETRY', repeat, len(proxy.samples), proxy.errors, flush=True)
            if receipt['status']=='RESOURCE_LIMIT' or any('RESOURCE_LIMIT' in s for s in proxy.errors): break


def analyze():
    sys.path.insert(0,str(ROOT/'scripts'))
    import audit_a08_existing_replays as audit
    lock = json.loads(LOCK.read_text())
    records, rows, telemetry_rows = [], [], []
    anchor_dir = OLD_RUN/'backend'/SLUG/'B/repeat1'
    for label,path in [('historical_anchor',anchor_dir)]+[(f'new_r{r}',RUNTIME/'backend'/SLUG/'B'/f'repeat{r}') for r in (1,2,3)]:
        if not (path/'receipt.json').exists():
            rows.append(dict(run_id=label,status='NOT_STARTED_RESOURCE_OR_BLOCKED',run_dir=str(path))); continue
        rec = json.loads((path/'receipt.json').read_text())
        assert all(sha(p)==h for p,h in rec['artifacts'].items()), 'Receipt artifact drift'
        assert rec['feature_bag_sha256']==lock['files'][rec['feature_bag']]
        assert rec['binary_sha256']==lock['files'][lock['binary']]
        w = json.loads((PAPER/'source_and_backend_lock.json').read_text())['windows'][0]
        assert audit.config_contract((path/'vins.yaml').read_text())==audit.config_contract(Path(w['backend_config_source']).read_text())
        row = dict(run_id=label,status=rec['status'],run_dir=str(path),receipt_sha256=sha(path/'receipt.json'),
                   poses=0,init_log_count=0,actual_process_identity='Unknown',wall_s=rec['wall_s'])
        if (path/'telemetry_receipt.json').exists():
            t = json.loads((path/'telemetry_receipt.json').read_text())
            assert t['runner_receipt_sha256']==sha(path/'receipt.json')
            expected = {p:h for p,h in lock['files'].items() if p in t['loaded_files']}
            matched = all(t['loaded_files'].get(p)==lock['files'][p] for p in [lock['binary'],lock['library']])
            matched = matched and all(t['loaded_files'][p]==h for p,h in expected.items())
            matched = matched and bool(t['samples']) and all(s['affinity']==sorted(CPUS) for s in t['samples'])
            env = t['actual_node'].get('environment',{})
            matched = matched and all(env.get(k)=='1' for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'])
            row.update(actual_process_identity='PASS' if matched and not t['errors'] else 'INCOMPLETE_OR_MISMATCH',
                telemetry_sha256=sha(path/'telemetry_receipt.json'),load1_min=min(s['loadavg'][0] for s in t['samples']) if t['samples'] else None,
                load1_max=max(s['loadavg'][0] for s in t['samples']) if t['samples'] else None)
            telemetry_rows.append(dict(run_id=label,started_at=t['started_at'],ended_at=t['ended_at'],
                loaded_files=t['loaded_files'],actual_node=t['actual_node'],errors=t['errors'],samples_count=len(t['samples'])))
        vio = path/'vins_output/vio.csv'
        if vio.is_file() and vio.stat().st_size and (path/'backend_use.csv').exists():
            stamps, poses = audit.read_poses(vio); trace = audit.parse_trace(path/'backend_use.csv')
            exact = stamps == [s['header_ns'] for s in trace['solvers']]
            received_times = []
            with (path/'backend_use.csv').open() as f:
                for line in f:
                    if line.startswith('received,'): received_times.append(float(line.split(',')[1]))
            span = (int(stamps[-1])-int(stamps[0]))/1e9
            row.update(poses=len(poses),first_header_ns=stamps[0],last_header_ns=stamps[-1],output_span_s=span,
                input_feature_span_s=received_times[-1]-received_times[0],coverage_span=span/(received_times[-1]-received_times[0]),
                received_frames=trace['received_frames'],received_observations=trace['received_observations'],
                received_sha256=trace['received_sha256'],solver_pose_headers_exact=exact,
                max_raw_position_norm_m=max(math.sqrt(sum(v*v for v in p[:3])) for p in poses),
                solver_calls=len(trace['solvers']),iteration_entries_min=min(s['entries'] for s in trace['solvers']),
                iteration_entries_max=max(s['entries'] for s in trace['solvers']),
                solver_at_or_above_budget=sum(s['duration_s']>=s['budget_s'] for s in trace['solvers']),
                init_log_count=(path/'vins.log').read_text(errors='replace').count('Initialization finish!'))
            if exact: records.append(dict(run_id=label,stamps=stamps,poses=poses,trace=trace,same_frozen_binary=True))
        rows.append(row)
    pairs,events=[],[]
    for a,b in itertools.combinations(records,2):
        try:
            row,ev=audit.compare(a,b);row['status']='COMPARABLE';events.extend(ev)
        except AssertionError:
            row=dict(anchor=a['run_id'],other=b['run_id'],status='NOT_COMPARABLE')
        pairs.append(row)
    newrows=[r for r in rows if r['run_id'].startswith('new_')]
    npairs=[p for p in pairs if p['anchor'].startswith('new_')]
    complete=sum(r['status']=='COMPLETE' for r in newrows)
    valid=complete==3 and all(r['actual_process_identity']=='PASS' for r in newrows)
    decision='PARTIAL_OR_IDENTITY_INCOMPLETE'
    if valid:
        decision='NOT_COMPARABLE'
        if len(npairs)==3 and all(p['status']=='COMPARABLE' for p in npairs):
            decision='LIMITED_REPEAT_AGREEMENT' if all(p['old_AA_tolerance_pass'] for p in npairs) else 'ORIGINAL_BUDGET_VARIATION_PERSISTS'
    for name,content in [('replay_results.csv',audit.csv_text(rows)),('pairwise.csv',audit.csv_text(pairs))]:
        with (PAPER/name).open('x') as f:f.write(content)
    save(PAPER/'events.json',events)
    save(PAPER/'process_identity.json',telemetry_rows)
    save(PAPER/'decision.json',dict(status=decision,completed_new_replays=complete,planned_new_replays=3,
        actual_new_replays=sum('receipt_sha256' in r for r in newrows),physical_windows=1,
        new_physical_windows=0,new_frontend_runs=0,new_algorithm_versions=0,backend_changed=False,
        new_new_comparable_pairs=sum(p['status']=='COMPARABLE' for p in npairs),
        new_new_strict_AA_pass_pairs=sum(p.get('old_AA_tolerance_pass',False) for p in npairs),
        APE_RPE='Not evaluated.',time_budget_causal_sufficiency='Not evaluated.',
        loaded_environment_checks=valid,prior_stops_unchanged=True,expansion=False))
    print(json.dumps({'decision':decision,'complete':complete}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['freeze','run','analyze'])
    args=parser.parse_args()
    {'freeze':freeze,'run':run_all,'analyze':analyze}[args.action]()
