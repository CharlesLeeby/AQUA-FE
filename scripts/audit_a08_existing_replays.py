#!/usr/bin/env python3
"""Read-only, fixed-roster A08 engineering audit; never launches a replay."""
import argparse
import csv
import hashlib
import io
import itertools
import json
import math
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload')
SLUG = 'a08_2700_3600'
OUT = ROOT / 'papers/frontend_a08_replay_identity_audit_v1'
REFS = {'additive': '49c02471716e8ac960e35dd9dd44ef6fbb1428c6',
        'utility': '90646d6a12f0cdde257ff5b7efa3166daa32dc12',
        'quality': '6ddca8e5f3a0fb2a64f50bf6e5427d8b7c59986f'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


HASHES = {}


def file_sha(path):
    key = str(Path(path).resolve())
    if key not in HASHES:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(4 * 1024 * 1024), b''):
                h.update(block)
        HASHES[key] = h.hexdigest()
    return HASHES[key]


def blob(ref, path):
    return subprocess.check_output(['git', 'show', ref + ':' + path], cwd=ROOT)


def locked_path(path, owner):
    p = Path(path)
    return p if p.is_absolute() else owner / p


def config_contract(text):
    # Same explicit exclusions as the frozen runner. All other bytes retained.
    return re.sub(r'^(output_path|cam0_calib):.*$', r'\1: <runtime-path>', text, flags=re.M)


def solver_header_ns(text):
    # The CSV prints %.9f from Headers double; VIO prints its double*1e9.
    # This is not nearest-neighbor matching. Assert full timestamp vector equality.
    return str(int(round(float(text) * 1e9)))


def angle(a, b):
    if a == b or a == [-v for v in b]:
        return 0.0
    na, nb = math.sqrt(sum(v*v for v in a)), math.sqrt(sum(v*v for v in b))
    return 2 * math.acos(min(1., abs(sum(x*y for x, y in zip(a, b)) / (na*nb))))


def first(values, predicate):
    return next((i for i, v in enumerate(values) if predicate(v)), None)


def parse_trace(path):
    solvers, features, received = [], [], hashlib.sha256()
    recv_count, recv_frames, recv_last = 0, 0, None
    current, eligible, residual = None, [], []
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            r = line.rstrip('\n').split(',')
            if r[0] == 'received':
                received.update(line.encode())
                recv_count += int(r[3])
                if r[1] != recv_last:
                    recv_frames += 1
                    recv_last = r[1]
            elif r[0] in ('eligible', 'residual'):
                if current is None:
                    current = r[1]
                assert current == r[1], 'Mixed solver-frame records'
                (eligible if r[0] == 'eligible' else residual).append(r[2:])
            elif r[0] == 'solver':
                assert current in (None, r[1])
                solvers.append(dict(timestamp=r[1], header_ns=solver_header_ns(r[1]),
                    duration_s=float(r[2]), budget_s=float(r[3]), entries=int(r[4]),
                    termination=int(r[5]), trace_line=lineno))
                features.append((eligible, residual))
                current, eligible, residual = None, [], []
            else:
                raise ValueError('Unknown audit row: ' + r[0])
    assert not eligible and not residual
    return dict(solvers=solvers, topology=features, received_sha256=received.hexdigest(),
                received_observations=recv_count, received_frames=recv_frames)


def read_poses(path):
    rows = list(csv.reader(path.open()))
    stamps = [r[0] for r in rows]
    assert all(re.fullmatch(r'[0-9]+', t) for t in stamps)
    assert len(set(stamps)) == len(stamps)
    values = [[float(v) for v in r[1:11]] for r in rows]
    assert all(math.isfinite(v) for r in values for v in r)
    return stamps, values


def log_events(path):
    text = path.read_text(errors='replace')
    patterns = ('Initialization finish!', 'visual structure and IMU', 'misalign',
                'gyroscope bias initial calibration', 'IMU excitation', 'failure detection', 'reset')
    events = [{'line': i, 'text': s} for i, s in enumerate(text.splitlines(), 1)
              if any(p in s for p in patterns)]
    return events


def roster():
    a = json.loads(blob(REFS['additive'], 'papers/frontend_additive_budget_v1/source_and_backend_lock.json'))
    source = next(w for w in a['windows'] if w['run_slug'] == SLUG)
    rows = []
    for group, family, section, repeats, ref, lockpath in [
        ('additive', 'frontend_additive_budget_v1', 'backend', (1,2,3), REFS['additive'],
         'papers/frontend_additive_budget_v1/backend_execution_lock_v2.json'),
        ('utility_frozen', 'frontend_observation_utility_audit_v1', 'aa/frozen/backend', (1,), REFS['utility'],
         'papers/frontend_observation_utility_audit_v1/execution_frozen_lock.json'),
        ('utility_diagnostic', 'frontend_observation_utility_audit_v1', 'aa/diagnostic/backend', (1,), REFS['utility'],
         'papers/frontend_observation_utility_audit_v1/execution_diagnostic_lock.json'),
        ('quality', 'frontend_source_neutral_quality_v1', 'backend', (1,2,3), REFS['quality'], None)]:
        if lockpath:
            raw = blob(ref, lockpath)
        else:
            raw = (RUNTIME / family / 'contract/backend_execution_lock.json').read_bytes()
            published = json.loads(blob(ref, 'papers/frontend_source_neutral_quality_v1/run_plan.json'))
            assert json.loads(raw) == published['backend_execution_lock']
        for repeat in repeats:
            owner = Path('/home/ma/AQUA-FE_WS_' + {
                'additive':'additive_budget_v1','utility_frozen':'observation_utility_v1',
                'utility_diagnostic':'observation_utility_v1','quality':'source_neutral_quality_v1'}[group])
            rows.append(dict(run_id=group+'_r'+str(repeat), evidence_commit=ref,
                             run_dir=str(RUNTIME/family/section/SLUG/'B'/('repeat'+str(repeat))),
                             owner=owner, lock=json.loads(raw), lock_sha256=digest(raw)))
    return source, rows


def compare(a, b):
    assert a['stamps'] == b['stamps'], 'Different pose support: no ordinal comparison'
    assert [s['timestamp'] for s in a['trace']['solvers']] == [s['timestamp'] for s in b['trace']['solvers']]
    dp = [math.sqrt(sum((x-y)**2 for x,y in zip(p[:3],q[:3]))) for p,q in zip(a['poses'],b['poses'])]
    dq = [angle(p[3:7],q[3:7]) for p,q in zip(a['poses'],b['poses'])]
    ix = first(dp, lambda x: x > 0)
    gate = first(list(zip(dp,dq)), lambda x: x[0] > 1e-5 or x[1] > 1e-5)
    sa, sb = a['trace']['solvers'], b['trace']['solvers']
    it = first(list(zip(sa,sb)), lambda s: s[0]['entries'] != s[1]['entries'])
    topo = first(list(zip(a['trace']['topology'],b['trace']['topology'])), lambda t: t[0] != t[1])
    budget = first(list(zip(sa,sb)), lambda s: s[0]['budget_s'] != s[1]['budget_s'])
    row = dict(anchor=a['run_id'], other=b['run_id'], same_frozen_binary=b['same_frozen_binary'],
        exact_pose_timestamps=True, received_records_equal=a['trace']['received_sha256']==b['trace']['received_sha256'],
        poses=len(dp), max_direct_position_delta_m=max(dp), max_direct_orientation_delta_rad=max(dq),
        first_position_difference_pose_1based='' if ix is None else ix+1,
        first_old_AA_tolerance_exceedance_pose_1based='' if gate is None else gate+1,
        first_iteration_count_difference_pose_1based='' if it is None else it+1,
        first_topology_difference_pose_1based='' if topo is None else topo+1,
        first_solver_budget_difference_pose_1based='' if budget is None else budget+1,
        old_AA_tolerance_pass=max(dp)<=1e-5 and max(dq)<=1e-5)
    if it is not None:
        row.update(first_iteration_header_ns=a['stamps'][it], anchor_entries=sa[it]['entries'],
                   other_entries=sb[it]['entries'], anchor_duration_s=sa[it]['duration_s'],
                   other_duration_s=sb[it]['duration_s'], anchor_budget_s=sa[it]['budget_s'],
                   other_budget_s=sb[it]['budget_s'],
                   anchor_termination=sa[it]['termination'], other_termination=sb[it]['termination'],
                   prefix_topology_equal=topo is None or topo>it,
                   anchor_trace_line=sa[it]['trace_line'], other_trace_line=sb[it]['trace_line'])
    events=[]
    for idx in sorted({i for i in (ix,gate,it,topo,budget) if i is not None}):
        events.append(dict(anchor=a['run_id'],other=b['run_id'],pose_1based=idx+1,header_ns=a['stamps'][idx],
             sensor_seconds_after_first=(int(a['stamps'][idx])-int(a['stamps'][0]))/1e9,
             position_delta_m=dp[idx],orientation_delta_rad=dq[idx],
             anchor_solver=sa[idx],other_solver=sb[idx],topology_equal=a['trace']['topology'][idx]==b['trace']['topology'][idx]))
    return row, events


def csv_text(rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    f=io.StringIO();w=csv.DictWriter(f,fieldnames=keys,lineterminator='\n');w.writeheader();w.writerows(rows)
    return f.getvalue()


def audit():
    source, entries=roster()
    records, identities, drift, provenance = [], [], [], []
    baseline_math = config_contract(Path(source['backend_config_source']).read_text())
    for name in ('baseline_bag','camera','backend_config_source'):
        expected=source['baseline_sha256' if name=='baseline_bag' else name+'_sha256']
        assert file_sha(source[name]) == expected, name
    for e in entries:
        path=Path(e['run_dir']);raw=(path/'receipt.json').read_bytes();r=json.loads(raw);lock=e['lock']
        assert r['status']=='COMPLETE' and r['arm']=='B'
        assert r['backend_lock_sha256']==e['lock_sha256']
        assert r['canonical_source_sha256']==source['backend_config_source_sha256']
        assert r['feature_bag_sha256']==source['baseline_sha256']==file_sha(r['feature_bag'])
        assert r['binary_sha256']==lock['files'][lock['binary']]==file_sha(lock['binary'])
        artifact_checks=0
        for p,h in r['artifacts'].items():
            assert file_sha(p)==h, 'Original artifact drift: '+p
            artifact_checks+=1
        for p,h in lock['files'].items():
            resolved=locked_path(p,e['owner'])
            actual=file_sha(resolved) if resolved.exists() else 'MISSING'
            if actual!=h: drift.append(dict(run_id=e['run_id'],path=p,resolved_path=str(resolved),expected=h,actual=actual))
        cfg=(path/'vins.yaml').read_text()
        assert config_contract(cfg)==baseline_math
        camera=re.search(r'^cam0_calib:\s*"([^"]+)"',cfg,re.M).group(1)
        assert file_sha(camera)==source['camera_sha256']
        ts,poses=read_poses(path/'vins_output/vio.csv');trace=parse_trace(path/'backend_use.csv')
        assert ts==[s['header_ns'] for s in trace['solvers']], 'Solver/pose header identity mismatch'
        events=log_events(path/'vins.log')
        same=r['binary_sha256']==entries[0]['lock']['files'][entries[0]['lock']['binary']]
        rec=dict(e,stamps=ts,poses=poses,trace=trace,same_frozen_binary=same)
        records.append(rec)
        identities.append(dict(run_id=e['run_id'],evidence_commit=e['evidence_commit'],run_dir=e['run_dir'],
            receipt_sha256=digest(raw),receipt_artifacts_verified=artifact_checks,
            lock_sha256=e['lock_sha256'],lock_files_checked=len(lock['files']),
            lock_file_drift_count=sum(x['run_id']==e['run_id'] for x in drift),
            feature_bag_sha256=r['feature_bag_sha256'],binary_sha256=r['binary_sha256'],
            library_sha256=file_sha(lock['library']),same_frozen_binary=same,
            config_sha256=r['config_sha256'],math_config_sha256=digest(baseline_math.encode()),
            camera_sha256=file_sha(camera),ros_port=lock['ros_port'],play_rate=lock['play_rate'],
            drain_seconds=lock['drain_seconds'],solver_yaml_seconds=0.04,solver_yaml_iterations=8,
            receipt_emitted_at=r['started_at'],receipt_wall_s=r['wall_s'],
            received_sha256=trace['received_sha256'],received_frames=trace['received_frames'],
            received_observations=trace['received_observations'],poses=len(poses),first_header_ns=ts[0],last_header_ns=ts[-1],
            max_raw_position_norm_m=max(math.sqrt(sum(v*v for v in p[:3])) for p in poses),
            first_pose_csv=json.dumps(poses[0]),solver_calls=len(trace['solvers']),
            solver_at_or_above_time_budget=sum(s['duration_s']>=s['budget_s'] for s in trace['solvers']),
            actual_historical_loaded_maps='Unknown',actual_historical_full_environment='Unknown',
            actual_IMU_delivery_sequence='Unknown',exact_solver_stop_reason='Unknown'))
        provenance.append(dict(run_id=e['run_id'],events=events,commands=r['commands'],
            source_lock_bytes_sha256=e['lock_sha256'],
            note='receipt.started_at is emitted after completion in frozen runner, not start time'))
    pairs,events=[],[]
    for a,b in itertools.combinations([r for r in records if r['same_frozen_binary']],2):
        pair,ev=compare(a,b);pairs.append(pair)
        if a is records[0]:events+=ev
    diag=next(r for r in records if not r['same_frozen_binary'])
    diagnostic_pair,diagnostic_events=compare(records[0],diag)
    return dict(identity=identities,pairs=pairs,events=events,diagnostic_reference=dict(pair=diagnostic_pair,events=diagnostic_events),
                lock_drift=drift,provenance=provenance,
                source_identity={k:v for k,v in source.items() if k in ['baseline_bag','baseline_sha256','camera','camera_sha256','backend_config_source','backend_config_source_sha256']},
                audit_script_sha256=file_sha(__file__),scope_sha256=file_sha(OUT/'audit_scope.md'))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=OUT);args=parser.parse_args()
    outputs=['identity.csv','pairwise_direct_differences.csv','first_fork_events.json','audit_receipt.json']
    assert all(not (args.output/p).exists() for p in outputs), 'Refuse to overwrite completed audit'
    result=audit()
    artifacts={'identity.csv':csv_text(result.pop('identity')),
               'pairwise_direct_differences.csv':csv_text(result.pop('pairs')),
               'first_fork_events.json':json.dumps(result.pop('events'),indent=2)+'\n'}
    result['derived_sha256']={p:digest(data.encode()) for p,data in artifacts.items()}
    artifacts['audit_receipt.json']=json.dumps(result,indent=2)+'\n'
    args.output.mkdir(parents=True,exist_ok=True)
    for name,text in artifacts.items():
        with (args.output/name).open('x') as f:f.write(text)
    print(json.dumps(dict(status='COMPLETE',existing_records=8,same_binary_pairs=21,
          lock_file_drifts=len(result['lock_drift']),new_replays=0,output=str(args.output))))


if __name__=='__main__':
    main()
