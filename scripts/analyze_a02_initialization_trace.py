#!/usr/bin/env python3
"""Reduce all six logging-only runs, retaining old results on a common grid."""
import csv
from decimal import Decimal
import json
from pathlib import Path
import re
from statistics import median
import subprocess
import sys

from run_a02_initialization_trace import PAPER, ROOT, rows, sha


def write_csv(path, values):
    fields = list(dict.fromkeys(key for row in values for key in row))
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def parse_trace(text, gravity=9.81):
    events = []
    for lineno, line in enumerate(text.splitlines(), 1):
        stamp = re.search(r'\[(\d+\.\d+), (\d+\.\d+)\]: (.*)', line)
        if stamp:
            events.append((Decimal(stamp[1]), lineno, stamp[2], stamp[3]))
    attempts, init = [], []
    for _, lineno, ros_clock, message in sorted(events):
        match = re.search(r'initial alignment: (linear|refined) scale ([-+\d.eE]+) gravity_norm ([-+\d.eE]+)', message)
        if match:
            kind, scale, norm = match[1], float(match[2]), float(match[3])
            if kind == 'linear':
                near = abs(scale) <= .0000005 or abs(abs(norm - gravity) - .5) <= .0000005
                reason = ('Unknown_print_rounding' if near else 'negative_linear_scale' if scale < 0
                          else 'gravity_norm_outside_gate' if abs(norm - gravity) > .5 else 'linear_gate_pass')
                attempts.append(dict(attempt=len(attempts) + 1, linear_scale=scale, gravity_norm=norm,
                    gravity_deviation=abs(norm - gravity), linear_condition=reason,
                    linear_log_line=lineno, linear_ros_clock_s=ros_clock, refined_scale='Unknown',
                    outcome='Unknown'))
            else:
                assert attempts, 'Refinement without a linear attempt'
                attempts[-1].update(refined_scale=scale, refined_gravity_norm=norm, refined_log_line=lineno)
        elif 'misalign visual structure with IMU' in message:
            assert attempts
            attempts[-1].update(outcome='REJECT', decision_log_line=lineno)
        elif 'Initialization finish!' in message:
            assert attempts
            attempts[-1].update(outcome='ACCEPT', decision_log_line=lineno)
            init.append(ros_clock)
    return attempts, init


def main():
    # Check chronological reduction despite mixed stdout/stderr file order.
    test = ('[ INFO] [2.0, 9.0]: misalign visual structure with IMU\n'
            '[ WARN] [1.0, 8.0]: initial alignment: linear scale -0.1 gravity_norm 9.8\n')
    assert parse_trace(test)[0][0]['linear_condition'] == 'negative_linear_scale'
    assert parse_trace(test)[0][0]['outcome'] == 'REJECT'
    manifest_path = PAPER / 'replay_manifest.json'
    manifest = json.loads(manifest_path.read_text())
    summaries, attempts, arms = [], [], []
    old = rows(ROOT / 'papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/backend_results_repeats.csv')
    old = [r for r in old if r['role'] in ('klt', 'donor_delete')]
    reference_span = float(old[0]['reference_span_s'])
    for item in manifest['runs']:
        run = Path(item['run_dir'])
        receipt = json.loads((run / 'receipt.json').read_text())
        assert receipt['input'] == item and receipt['manifest_sha256'] == sha(manifest_path)
        for path, expected in receipt['artifacts'].items():
            assert sha(run / path) == expected
        log = (run / 'vins.log').read_text()
        trace, init = parse_trace(log)
        attempts.extend(dict(arm=item['arm'], repeat=item['repeat'], **r) for r in trace)
        vio = run / 'vins_output/vio.csv'
        poses = rows_without_header(vio) if vio.exists() else []
        start = str(poses[0][0]) if poses else 'Unknown'
        span = float((Decimal(poses[-1][0]) - Decimal(poses[0][0])) / Decimal(10**9)) if poses else 0
        prev_role = 'klt' if item['arm'] == 'klt' else 'donor_delete'
        prev = next(r for r in old if r['role'] == prev_role and int(r['repeat']) == item['repeat'])
        assert sha(prev['vio_csv']) == prev['vio_csv_sha256']
        previous_log = Path(prev['vins_log']).read_text()
        prior_init_time = rows_without_header(Path(prev['vio_csv']))[0][0]
        env = (run / 'vins_env_manifest.txt').read_text()
        env_dict = dict(line.split('=', 1) for line in env.splitlines() if '=' in line)
        assert env_dict['VINS_INITIAL_DIAGNOSTICS'] == '1'
        assert not any(v for k, v in env_dict.items() if k.startswith('VINS_INITIAL_') and k != 'VINS_INITIAL_DIAGNOSTICS')
        summaries.append(dict(arm=item['arm'], repeat=item['repeat'], diagnostic_status=receipt['status'],
            linear_attempts=len(trace), rejected=sum(r['outcome'] == 'REJECT' for r in trace),
            accepted=sum(r['outcome'] == 'ACCEPT' for r in trace),
            accepted_linear_scale=trace[-1]['linear_scale'] if init else 'Unknown',
            accepted_refined_scale=trace[-1]['refined_scale'] if init else 'Unknown',
            first_vio_header_ns=start, first_vio_matches_old=start == prior_init_time,
            rejection_count_matches_old=sum(r['outcome'] == 'REJECT' for r in trace) == previous_log.count('misalign visual structure with IMU'),
            pose_count=len(poses), trajectory_span_s=span, coverage=span / reference_span,
            runability='PASS' if len(init) == 1 and poses and span / reference_span >= .7 else 'FAIL',
            vio_csv=str(vio), vins_log=str(run / 'vins.log'), receipt=str(run / 'receipt.json')))
        arms.append((f"trace_{item['arm']}_r{item['repeat']}", str(vio)))
    write_csv(PAPER / 'initialization_attempts.csv', attempts)
    write_csv(PAPER / 'replay_results.csv', summaries)
    for row in old:
        arms.append((f"old_{row['role']}_r{row['repeat']}", row['vio_csv']))
    output = PAPER / 'common_support'
    assert not output.exists(), 'Preserve previous evaluation'
    command = [sys.executable, str(ROOT / 'scripts/evaluate_vins_common_support_dual_scale.py'),
        '--reference-bag', manifest['runs'][0]['feature_bag'], '--reference-topic', '/aqualoc/colmap_gt',
        '--evaluation-rate-hz', '1', '--max-reference-gap-s', '2.5', '--max-estimate-gap-s', '.25',
        '--output-dir', str(output), '--run-evo']
    for name, vio in arms:
        command += ['--arm', f'{name}={vio}', '--arm-config', f"{name}={manifest['runs'][0]['canonical_config']}"]
    if all(r['runability'] == 'PASS' for r in summaries):
        process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output.mkdir(exist_ok=True)
        with (output / 'evaluator.log').open('x') as f:
            f.write(json.dumps(command) + '\n' + process.stdout)
        if process.returncode:
            raise RuntimeError('Evaluator failed, logs preserved')
        metrics = rows(output / 'common_support_metrics.csv')
        aggregates = []
        for group in ('trace_klt', 'trace_donor_delete_only', 'old_klt', 'old_donor_delete'):
            values = [r for r in metrics if r['arm'].startswith(group + '_r')]
            assert len(values) == 3
            record = dict(group=group, repeats=3)
            for key in ('fixed_se3_ape_rmse_m', 'fixed_se3_rpe_rmse_m', 'sim3_ape_rmse_m', 'sim3_rpe_rmse_m', 'sim3_scale'):
                v = [float(r[key]) for r in values]
                record.update({key + '_median': median(v), key + '_min': min(v), key + '_max': max(v)})
            aggregates.append(record)
        write_csv(PAPER / 'accuracy.csv', aggregates)
    print(json.dumps(summaries, indent=2))


def rows_without_header(path):
    with path.open(newline='') as f:
        return list(csv.reader(f))


if __name__ == '__main__':
    main()
