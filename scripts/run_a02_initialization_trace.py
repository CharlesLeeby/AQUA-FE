#!/usr/bin/env python3
"""Six existing-input logging-only replays; frozen backend remains unchanged."""
import csv
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess

ROOT = Path('/home/ma/AQUA-FE_WS')
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a02_init_trace_repair_v1')
PAPER = ROOT / 'papers/frontend_a02_init_trace_repair_v1'
VINS = Path('/home/ma/SLAM/VINS-Fusion-origin')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def rows(path):
    with Path(path).open(newline='') as f:
        return list(csv.DictReader(f))


def main():
    assert subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT, text=True).strip() == str(ROOT)
    assert not any(k.startswith('VINS_INITIAL_') for k in os.environ), 'Ambient initialization override'
    baseline = next(r for r in rows(ROOT / 'papers/frontend_coverage_monotone_router_v2/backend_smoke_plan.csv')
                    if r['run_slug'] == 'a02_0_900' and r['cell_id'] == 'klt')
    deleted = rows(ROOT / 'papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/replay_plan.csv')[0]
    assert baseline['canonical_config_sha256'] == deleted['canonical_config_sha256']
    for r in (baseline, deleted):
        for key in ('feature_bag', 'canonical_config', 'camera_config'):
            assert sha(r[key]) == r[key + '_sha256'], key
        assert sha(VINS / 'devel/lib/vins/vins_node') == r['vins_node_sha256']
        assert sha(VINS / 'devel/lib/libvins_lib.so') == r['vins_lib_sha256']
    manifest = []
    for repeat in (1, 2, 3):
        for arm, source in (('klt', baseline), ('donor_delete_only', deleted)):
            item = {k: source[k] for k in ('feature_bag', 'feature_bag_sha256', 'canonical_config',
                    'canonical_config_sha256', 'camera_config', 'camera_config_sha256',
                    'vins_node_sha256', 'vins_lib_sha256')}
            item.update(arm=arm, repeat=repeat, run_dir=str(RUNTIME / arm / f'repeat{repeat}'))
            manifest.append(item)
    frozen = json.dumps(dict(schema='aqua-fe-a02-init-trace-v1', diagnostic_env={'VINS_INITIAL_DIAGNOSTICS': '1'},
        preregistration_sha256=sha(PAPER / 'preregistration.md'),
        runner_sha256=sha(__file__), cell_script_sha256=sha(ROOT / 'scripts/run_a02_initialization_trace_cell.sh'),
        runs=manifest), indent=2, sort_keys=True) + '\n'
    path = PAPER / 'replay_manifest.json'
    if path.exists():
        assert path.read_text() == frozen, 'Frozen manifest mismatch'
    else:
        with path.open('x') as f:
            f.write(frozen)
    for item in manifest:
        run = Path(item['run_dir'])
        receipt = run / 'receipt.json'
        if receipt.exists():
            saved = json.loads(receipt.read_text())
            assert saved['input'] == item
            assert saved['manifest_sha256'] == sha(path)
            for artifact, expected in saved['artifacts'].items():
                assert sha(run / artifact) == expected, artifact
            print('reuse diagnostic', item['arm'], item['repeat'], saved['status'], flush=True)
            continue
        assert not run.exists(), f'Unreceipted run preserved, refusing overwrite: {run}'
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 11983))
        print('start diagnostic', item['arm'], item['repeat'], flush=True)
        result = subprocess.run(['bash', str(ROOT / 'scripts/run_a02_initialization_trace_cell.sh'),
            item['feature_bag'], item['canonical_config'], str(run)], cwd=ROOT)
        artifacts = {str(p.relative_to(run)): sha(p) for p in run.rglob('*') if p.is_file()
                     and 'prior_canonical_scratch' not in p.parts}
        saved = dict(input=item, manifest_sha256=sha(path), exit_code=result.returncode,
                     status='COMPLETE' if result.returncode == 0 else 'FAIL', artifacts=artifacts)
        with receipt.open('x') as f:
            json.dump(saved, f, indent=2, sort_keys=True)
        print('finish diagnostic', item['arm'], item['repeat'], saved['status'], flush=True)
        # Scientific failure stays in the six-unit roster. Resource/integrity failure stops.
        if result.returncode in (64, 65, 66, 73):
            raise RuntimeError(f'Safety precondition failed: {result.returncode}')
    assert sha(VINS / 'devel/lib/vins/vins_node') == baseline['vins_node_sha256']
    assert sha(VINS / 'devel/lib/libvins_lib.so') == baseline['vins_lib_sha256']


if __name__ == '__main__':
    main()
