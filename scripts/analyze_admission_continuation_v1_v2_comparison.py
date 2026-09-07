#!/usr/bin/env python3
"""Reassociate v2/current/KLT on one grid; never splice earlier scalar scores."""
from __future__ import annotations

import csv
import json
from pathlib import Path
import subprocess
import sys
from statistics import median

import finalize_frontend_coverage_monotone_router_v2_backend as common
import run_frontend_admission_continuation_v1 as run

V2 = run.ROOT / 'papers/frontend_coverage_monotone_router_v2'
V2_RUNTIME = run.RUNTIME.parent / 'frontend_coverage_monotone_router_v2'


def verify(row, directory):
    receipt = common.parse_receipt(directory / 'replay_receipt.txt')
    for key in ('window_id', 'run_slug', 'cell_id', 'repeat', 'feature_bag_sha256',
                'canonical_config_sha256', 'vins_node_sha256', 'vins_lib_sha256'):
        if str(receipt.get(key)) != str(row[key]):
            raise RuntimeError(f'Receipt mismatch: {directory} {key}')
    vio = directory / 'vins_output/vio.csv'
    if common.sha256(vio) != receipt['vio_csv_sha256']:
        raise RuntimeError(f'Trajectory mismatch: {vio}')
    return vio


def main():
    if not (run.PAPER / 'backend_decision.json').is_file():
        raise RuntimeError('Complete the frozen primary reduction first')
    target = run.PAPER / 'v2_common_comparison.csv'
    if target.exists():
        raise RuntimeError('Refusing to overwrite completed v2 comparison')
    current = common.read_csv(run.PAPER / 'backend_replay_plan.csv')
    old = common.read_csv(V2 / 'backend_smoke_plan.csv')
    old_front = {(r['run_slug'], r['arm']): r for r in common.read_csv(V2 / 'frontend_audit.csv')}
    repeats = common.read_csv(run.PAPER / 'backend_results_repeats.csv')
    front = common.read_csv(run.PAPER / 'frontend_audit.csv')
    primary = {(r['run_slug'], r['arm']): r for r in common.read_csv(run.PAPER / 'development_outcomes.csv')}
    rows = []
    for item in front:
        if item['arm'] == 'klt':
            continue
        slug, arm = item['run_slug'], item['arm']
        v2_arm = arm.replace('continuation_', 'router_')
        old_input = old_front[(slug, v2_arm)]['feature_bag_sha256']
        identity = dict(current_feature_bag_sha256=item['feature_bag_sha256'],
                        v2_feature_bag_sha256=old_input,
                        byte_identical_frontend_to_v2=item['feature_bag_sha256'] == old_input)
        if primary[(slug, arm)]['outcome'] == 'FAIL':
            rows.append(dict(window_id=item['window_id'], arm=arm, status='NOT_EVALUABLE_PRIMARY_SUPPORT', independent_replays=0, **identity))
            continue
        new_cell = arm if int(item['admitted_sidecars']) else 'klt'
        old_cell = v2_arm if any(r['run_slug'] == slug and r['cell_id'] == v2_arm for r in old) else 'klt'
        if old_cell == 'klt' and old_front[(slug, v2_arm)]['byte_identical_to_klt'] != 'True':
            raise RuntimeError('Missing v2 replay is not an exact zero-action mapping')
        if any(r['run_slug'] == slug and r['cell_id'] in {new_cell, 'klt'} and r['repeat_status'] != 'PASS' for r in repeats):
            rows.append(dict(window_id=item['window_id'], arm=arm, status='NOT_EVALUABLE_BACKEND_FAIL', independent_replays=0, **identity))
            continue
        if new_cell == old_cell == 'klt':
            if item['byte_identical_to_klt'] != 'True':
                raise RuntimeError('Zero-action mapping is not byte identical')
            rows.append(dict(window_id=item['window_id'], arm=arm, status='EXACT_KLT_MAPPING_NO_ACTION',
                             independent_replays=0, **identity))
            continue
        output = run.PAPER / 'v2_common_support' / f'{slug}__{arm}'
        if output.exists():
            raise RuntimeError(f'Existing comparison must be inspected, not overwritten: {output}')
        baseline = next(r for r in current if r['run_slug'] == slug and r['cell_id'] == 'klt')
        command = [sys.executable, str(common.EVALUATOR), '--reference-bag', baseline['feature_bag'],
                   '--reference-topic', common.topic_for(item['window_id']), '--evaluation-rate-hz', '1',
                   '--max-reference-gap-s', '2.5', '--max-estimate-gap-s', '0.25',
                   '--output-dir', str(output), '--run-evo']
        for role, plan, cell in [('klt', current, 'klt'), ('current', current, new_cell), ('v2', old, old_cell)]:
            for repeat in range(1, 4):
                row = next(r for r in plan if r['run_slug'] == slug and r['cell_id'] == cell and int(r['repeat']) == repeat)
                directory = Path(row['replay_dir']) if 'replay_dir' in row else V2_RUNTIME / 'backend_replays' / slug / cell / f'repeat{repeat}'
                vio = verify(row, directory)
                if row['canonical_config_sha256'] != baseline['canonical_config_sha256']:
                    raise RuntimeError('Cross-version YAML identity mismatch')
                name = f'{role}_r{repeat}'
                command += ['--arm', f'{name}={vio}', '--arm-config', f"{name}={row['canonical_config']}"]
        result = subprocess.run(command, cwd=run.ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output.mkdir(parents=True, exist_ok=True)
        (output / 'evaluator.log').write_text(result.stdout)
        summary_path = output / 'common_support_summary.json'
        support = json.loads(summary_path.read_text())['support'] if result.returncode == 0 and summary_path.exists() else {}
        valid = bool(support.get('ape_valid') and support.get('rpe_valid'))
        result_row = dict(window_id=item['window_id'], arm=arm,
                         status='PASS' if valid else 'NOT_EVALUABLE', independent_replays=0,
                         matched_count=support.get('matched_count', ''),
                         common_span_s=support.get('common_span_s', ''),
                         common_coverage=support.get('common_coverage', ''),
                         rpe_pairs=support.get('rpe_pairs', ''),
                         metrics_path=str((output / 'common_support_metrics.csv').relative_to(run.PAPER)),
                         return_code=result.returncode, **identity)
        if valid:
            metrics = common.read_csv(output / 'common_support_metrics.csv')
            for role in ('klt', 'current', 'v2'):
                group = [r for r in metrics if r['arm'].startswith(role + '_r')]
                if len(group) != 3:
                    raise RuntimeError('Expected all three technical repeats')
                for name in ('fixed_se3_ape_rmse_m', 'fixed_se3_rpe_rmse_m', 'sim3_scale', 'sim3_ape_rmse_m', 'sim3_rpe_rmse_m'):
                    values = [float(r[name]) for r in group]
                    result_row[role + '_' + name + '_median'] = median(values)
                    result_row[role + '_' + name + '_range'] = f'{min(values):.9g}..{max(values):.9g}'
        rows.append(result_row)
    common.write_csv(target, rows)
    print(json.dumps(rows, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
