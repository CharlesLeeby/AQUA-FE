#!/usr/bin/env python3
"""Apply the causal guard to all twelve existing proposed streams, no retracking."""
from collections import Counter
import csv
import itertools
import json
from pathlib import Path
import shutil
import sys

import rosbag

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uw_frontend.ros.classical_observation_guard import ClassicalObservationGuard, message_bytes
from run_a02_initialization_trace import PAPER, ROOT, RUNTIME, VINS, rows, sha
import run_frontend_admission_continuation_v1 as previous

TOPIC = '/feature_tracker/feature'


def guard_bags(baseline, proposed, directory):
    """Stream paired present-time messages; never inspect future observations."""
    if directory.exists():
        raise RuntimeError(f'Preserve existing output: {directory}')
    directory.mkdir(parents=True)
    stream_path = directory / 'guarded_stream.bag'
    guard = ClassicalObservationGuard()
    counts = Counter()
    first = None
    with rosbag.Bag(str(baseline)) as b, rosbag.Bag(str(proposed)) as p, \
            rosbag.Bag(str(stream_path), 'w') as output:
        for left, right in itertools.zip_longest(b.read_messages(), p.read_messages()):
            if left is None or right is None:
                raise ValueError('Unequal message count')
            bt, bm, bs = left
            pt, pm, ps = right
            if (bt, bs.to_nsec()) != (pt, ps.to_nsec()):
                raise ValueError('Message order/record time mismatch')
            counts['messages'] += 1
            bb, pb = message_bytes(bm), message_bytes(pm)
            selected = bm
            if bt == TOPIC:
                counts['feature_frames'] += 1
                if any(v != 0 for c in bm.channels if c.name == 'is_learned' for v in c.values):
                    raise ValueError('Baseline includes learned observations')
                selected, reason = guard.select(bm, pm)
                if reason not in ('preserved_baseline',) and not reason.startswith('latched:'):
                    first = dict(frame=counts['feature_frames'] - 1, stamp_ns=str(bm.header.stamp.to_nsec()), reason=reason)
                counts['proposed_different_frames'] += int(bb != pb)
                counts['guarded_different_frames'] += int(bb != message_bytes(selected))
                counts['published_learned_observations'] += sum(int(v != 0) for c in selected.channels if c.name == 'is_learned' for v in c.values)
                if len(selected.points) > 350:
                    raise ValueError('Guard exceeded original cap')
            elif bb != pb:
                raise ValueError('Non-feature message modified')
            output.write(bt, selected, bs)
    # Verify the complete written stream, including message clocks and IMU.
    identical = True
    with rosbag.Bag(str(baseline)) as b, rosbag.Bag(str(stream_path)) as o:
        for left, right in itertools.zip_longest(b.read_messages(), o.read_messages()):
            if left is None or right is None:
                raise ValueError('Output message count changed')
            bt, bm, bs = left
            ot, om, os = right
            if (bt, bs.to_nsec()) != (ot, os.to_nsec()):
                raise ValueError('Output time axis changed')
            identical &= message_bytes(bm) == message_bytes(om)
    if identical != (counts['guarded_different_frames'] == 0):
        raise ValueError('Written stream disagrees with causal guard')
    final = directory / 'features.bag'
    shutil.copyfile(baseline if identical else stream_path, final)
    if identical and sha(final) != sha(baseline):
        raise ValueError('Exact-KLT container copy failed')
    return dict(**counts, first_fault=first, exact_klt=identical, feature_bag=str(final),
                feature_bag_sha256=sha(final), stream_sha256=sha(stream_path))


def validate_klt_reuse(slug, digest):
    source = previous.PAPER
    records = [r for r in rows(source / 'backend_results_repeats.csv') if r['run_slug'] == slug and r['cell_id'] == 'klt']
    manifest = [r for r in rows(source / 'backend_replay_plan.csv') if r['run_slug'] == slug and r['cell_id'] == 'klt']
    assert len(records) == len(manifest) == 3
    audit = []
    for r, m in zip(records, manifest):
        assert r['repeat'] == m['repeat'] and r['feature_bag_sha256'] == digest
        assert sha(r['feature_bag']) == digest
        saved = dict(line.split('=', 1) for line in Path(r['replay_receipt']).read_text().splitlines() if '=' in line)
        for key in ('feature_bag_sha256', 'canonical_config_sha256', 'vins_node_sha256', 'vins_lib_sha256'):
            assert saved[key] == m[key]
        for key in ('canonical_config', 'camera_config'):
            assert sha(m[key]) == m[key + '_sha256']
        assert sha(VINS / 'devel/lib/vins/vins_node') == m['vins_node_sha256']
        assert sha(VINS / 'devel/lib/libvins_lib.so') == m['vins_lib_sha256']
        assert sha(r['vio_csv']) == saved['vio_csv_sha256'] == r['vio_csv_sha256']
        env_path = Path(r['replay_receipt']).parent / 'vins_env_manifest.txt'
        env = dict(line.split('=', 1) for line in env_path.read_text().splitlines() if '=' in line)
        assert not any(v for k, v in env.items() if k.startswith('VINS_INITIAL_'))
        assert r['repeat_status'] == 'PASS'
        audit.append(dict(repeat=r['repeat'], vio_csv=r['vio_csv'], vio_csv_sha256=r['vio_csv_sha256'],
                          config_sha256=m['canonical_config_sha256'], camera_sha256=m['camera_config_sha256'],
                          receipt_sha256=sha(r['replay_receipt']), env_sha256=sha(env_path)))
    return audit


def main():
    previous.configure()  # path resolution only; no frontend or replay invocation
    roster = []
    for window in rows(previous.PAPER / 'development_windows.csv'):
        arms = rows(previous.PAPER / 'arms.csv')
        baseline_dir = previous.run_dir(window, arms[0])
        b_receipt = json.loads((baseline_dir / 'frontend_receipt.json').read_text())
        baseline = baseline_dir / 'features.bag'
        assert sha(baseline) == b_receipt['feature_bag_sha256']
        for arm in arms[1:]:
            proposed_dir = previous.run_dir(window, arm)
            proposed = proposed_dir / 'features.bag'
            p_receipt = json.loads((proposed_dir / 'frontend_receipt.json').read_text())
            assert sha(proposed) == p_receipt['feature_bag_sha256']
            roster.append(dict(window=window['run_slug'], arm=arm['arm'], baseline=str(baseline),
                baseline_sha256=b_receipt['feature_bag_sha256'], proposed=str(proposed),
                proposed_sha256=p_receipt['feature_bag_sha256']))
    lock = dict(roster=roster, files={str(p.relative_to(ROOT)): sha(p) for p in (
        PAPER / 'repair_contract.md', Path(__file__).resolve(), ROOT / 'uw_frontend/ros/classical_observation_guard.py',
        ROOT / 'tests/test_classical_observation_guard.py')})
    with (PAPER / 'repair_lock.json').open('x') as f:
        json.dump(lock, f, indent=2, sort_keys=True)
    results = []
    for r in roster:
        if shutil.disk_usage(RUNTIME).free < 8589934592:
            raise RuntimeError('Runtime disk floor reached; preserve partial matrix')
        directory = RUNTIME / 'guard_validation' / r['window'] / r['arm']
        print('guard', r['window'], r['arm'], flush=True)
        result = guard_bags(Path(r['baseline']), Path(r['proposed']), directory)
        reuse = validate_klt_reuse(r['window'], r['baseline_sha256']) if result['exact_klt'] else []
        payload = dict(input=r, result=result, mapped_backend_receipts=reuse, repair_lock_sha256=sha(PAPER / 'repair_lock.json'))
        with (directory / 'receipt.json').open('x') as f:
            json.dump(payload, f, indent=2, sort_keys=True)
        results.append(dict(window=r['window'], arm=r['arm'], **result,
            mapped_replays=len(reuse), independent_replays=0,
            outcome='TIE' if reuse else 'NOT_EVALUATED',
            status='SAFE_FALLBACK_ONLY' if reuse else 'ACTION_REMAINS_NOT_EVALUATED'))
    with (PAPER / 'guard_results.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in results for k in r)))
        writer.writeheader()
        writer.writerows(results)
    print(json.dumps(dict(arm_windows=len(results), physical_windows=6,
        outcomes=dict(Counter(r['outcome'] for r in results)),
        action_windows=sum(r['published_learned_observations'] > 0 for r in results)), indent=2))


if __name__ == '__main__':
    main()
