#!/usr/bin/env python3
"""Read only: summarize all A02 logs in the three existing frozen manifests.

Writes CSV to stdout, never launches replay or modifies an input/output file.
ROS wall time orders events because stdout/stderr can be buffered differently.
Counts are logged events, not a reconstructed complete initialization history.
"""
import argparse
import csv
import hashlib
import re
import sys
from decimal import Decimal
from pathlib import Path


PAPER = Path('papers')
PLANS = (
    ('v2', 'frontend_coverage_monotone_router_v2', 'backend_smoke_plan.csv'),
    ('continuation', 'frontend_admission_continuation_v1', 'backend_replay_plan.csv'),
    ('delete', 'frontend_coverage_monotone_router_v2_donor_delete_diagnostic', 'replay_plan.csv'),
)
MESSAGES = {
    'parallax_rejection': 'Not enough features or parallax; Move device around',
    'alignment_rejection': 'misalign visual structure with IMU',
    'gyro_calibration': 'gyroscope bias initial calibration',
    'low_excitation_warning': 'IMU excitation not enouth!',
    'initialization': 'Initialization finish!',
    'reboot': 'system reboot!',
    'linear_scale_diagnostic': 'initial alignment: linear scale',
}
CLOCK = re.compile(r'\[\s*([0-9.]+),\s*([0-9.]+)\]:\s*(.*)')
ANSI = re.compile(r'\x1b\[[0-9;]*m')


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def key_values(path):
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)


def events(log):
    result = []
    for number, line in enumerate(log.splitlines(), 1):
        match = CLOCK.search(ANSI.sub('', line))
        if match:
            wall, ros, message = match.groups()
            for kind, token in MESSAGES.items():
                if token in message:
                    result.append((Decimal(wall), Decimal(ros), number, kind))
    return sorted(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, default=Path(
        '/media/ma/Data/AQUA-FE_WS_storage_offload'))
    args = parser.parse_args()
    timing = read_csv(PAPER / 'frontend_admission_continuation_v1/backend_environment_audit.csv')
    starts = {int(r['first_feature_timestamp_ns']) for r in timing
              if r['run_slug'] == 'a02_0_900'}
    assert len(starts) == 1, 'Ambiguous frozen first-feature timestamp'
    start_ns = starts.pop()
    rows, seen = [], set()
    for version, experiment, filename in PLANS:
        plan = PAPER / experiment / filename
        for item in read_csv(plan):
            if item['run_slug'] != 'a02_0_900':
                continue
            recorded = item.get('replay_dir', '')
            directory = (Path(recorded) if recorded else
                         args.runtime_root / experiment / 'backend_replays' /
                         item['run_slug'] / item['cell_id'] / ('repeat' + item['repeat']))
            # Exact reused KLT directories occur in both manifests: count once.
            directory = directory.resolve()
            if directory in seen:
                continue
            seen.add(directory)
            log, vio, env = [directory / name for name in (
                'vins.log', 'vins_output/vio.csv', 'vins_env_manifest.txt')]
            found = events(log.read_text(errors='strict'))
            init = [event for event in found if event[3] == 'initialization']
            assert len(init) == 1, f'Expected one recorded initialization: {directory}'
            prefix = [event for event in found if event[0] <= init[0][0]]
            with vio.open() as stream:
                first_vio_ns = int(next(line for line in stream if line.strip()).split(',')[0])
            vio_hash = sha256(vio)
            receipt_path = directory / 'replay_receipt.txt'
            receipt = key_values(receipt_path)
            for key in ('run_slug', 'cell_id', 'repeat', 'feature_bag_sha256',
                        'canonical_config_sha256', 'vins_node_sha256', 'vins_lib_sha256'):
                assert receipt.get(key) == item[key], f'Receipt mismatch {key}: {directory}'
            assert receipt.get('vio_csv_sha256') == vio_hash, f'Trajectory changed: {directory}'
            environment = key_values(env)
            row = dict(
                window='a02_0_900', version=version, cell_id=item['cell_id'],
                repeat=item['repeat'], new_replays=0, source_manifest=str(plan),
                source_manifest_sha256=sha256(plan), receipt_identity_status='PASS',
                receipt_sha256=sha256(receipt_path),
                replay_directory=str(directory), log_sha256=sha256(log),
                vio_sha256=vio_hash, environment_sha256=sha256(env),
                feature_bag_sha256=item['feature_bag_sha256'],
                canonical_config_sha256=item['canonical_config_sha256'],
                first_feature_timestamp_ns=start_ns, first_vio_timestamp_ns=first_vio_ns,
                first_vio_delay_s=str(Decimal(first_vio_ns - start_ns) / Decimal(10**9)),
                initialization_ros_time_s=str(init[0][1]),
                initialization_ros_delay_s=str(init[0][1] - Decimal(start_ns) / Decimal(10**9)),
                initialization_log_line=init[0][2],
                initialization_count=len(init),
                reboot_log_count=sum(e[3] == 'reboot' for e in found),
                linear_scale_diagnostic_count=sum(e[3] == 'linear_scale_diagnostic' for e in found),
            )
            for key in ('VINS_INITIAL_MIN_SCALE', 'VINS_INITIAL_MAX_SCALE',
                        'VINS_INITIAL_MAX_GYRO_BIAS_DELTA', 'VINS_INITIAL_ROLLBACK_ON_FAILURE',
                        'VINS_INITIAL_DIAGNOSTICS'):
                row[key + '_recorded'] = environment.get(key, 'Unknown: not recorded')
            for kind in ('parallax_rejection', 'alignment_rejection',
                         'gyro_calibration', 'low_excitation_warning'):
                matching = [e for e in prefix if e[3] == kind]
                row[kind + '_count'] = len(matching)
                row[kind + '_log_lines'] = ';'.join(str(e[2]) for e in matching)
            row['unlogged_rejection_subcause'] = 'Unknown'
            rows.append(row)
    assert len(rows) == 30, f'Unexpected existing replay denominator: {len(rows)}'
    expected = {
        ('v2', cell) for cell in ('klt', 'router_xfeat', 'router_splg',
                                  'matched_gftt_for_router_xfeat', 'matched_gftt_for_router_splg')
    } | {
        ('continuation', cell) for cell in ('continuation_xfeat', 'continuation_splg',
            'matched_gftt_for_continuation_xfeat', 'matched_gftt_for_continuation_splg')
    } | {('delete', 'donor_delete_only')}
    assert {(r['version'], r['cell_id']) for r in rows} == expected
    for version, cell in expected:
        assert {r['repeat'] for r in rows if (r['version'], r['cell_id']) == (version, cell)} == {'1', '2', '3'}
    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)


if __name__ == '__main__':
    main()
