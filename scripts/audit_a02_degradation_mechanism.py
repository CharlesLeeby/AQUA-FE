#!/usr/bin/env python3
"""Bounded existing-input diagnostic; no frontend or VIO/BA/IMU solver replay.

Builds only a diagnostic driver in a new temporary directory and calls two
unchanged library components through the first successful relative-pose step.
Existing input bags, VINS sources/binaries and frozen results are read only.
All scientific output is JSON on stdout; no experiment artifact is overwritten.
"""
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile


LIB = Path('/home/ma/SLAM/VINS-Fusion-origin/devel/lib')
SOURCE = Path('/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator/src')
PAPER = Path('papers/frontend_admission_continuation_v1')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path):
    with path.open(newline='') as stream:
        return list(csv.DictReader(stream))


def main():
    assert sha(LIB / 'libvins_lib.so') == '373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8'
    assert sha(SOURCE / 'estimator/feature_manager.h') == '87aa9951d7779b22fef66ee2c71345c8bf2482f327179347ff4c46479fb2ad00'
    b = next(r for r in read_csv(Path('papers/frontend_coverage_monotone_router_v2/backend_smoke_plan.csv'))
             if r['run_slug'] == 'a02_0_900' and r['cell_id'] == 'klt')
    d = read_csv(Path('papers/frontend_coverage_monotone_router_v2_donor_delete_diagnostic/replay_plan.csv'))[0]
    for row in (b, d):
        for key in ('feature_bag', 'canonical_config'):
            assert sha(Path(row[key])) == row[key + '_sha256'], key
    assert b['canonical_config_sha256'] == d['canonical_config_sha256']
    # Refuse an ambient solver override rather than silently changing it.
    assert not any(k.startswith('VINS_INITIAL_') for k in os.environ), 'Ambient initialization override'
    build = Path(tempfile.mkdtemp(prefix='a02_init_input_audit_'))
    flags = shlex.split(subprocess.check_output(
        ['pkg-config', '--cflags', '--libs', 'roscpp', 'rosbag', 'opencv4', 'jsoncpp'], text=True))
    command = ['g++', '-O2', '-std=c++14', 'scripts/audit_a02_initialization_inputs.cpp',
               '-I' + str(SOURCE), '-I/usr/include/eigen3', '-L' + str(LIB),
               '-Wl,-rpath,' + str(LIB), '-lvins_lib', *flags, '-o', str(build / 'audit')]
    subprocess.run(command, check=True)

    def inspect(left, right):
        return json.loads(subprocess.check_output(
            [str(build / 'audit'), left, right, b['canonical_config']], text=True))

    control = inspect(b['feature_bag'], b['feature_bag'])
    assert control['sfm_input_differences'] == [] and control['sfm_feature_order_equal']
    assert control['relative_coordinates_equal_in_order']
    assert control['relative_rotation_frobenius_difference'] == control['relative_translation_difference'] == 0
    result = inspect(b['feature_bag'], d['feature_bag'])
    assert inspect(b['feature_bag'], d['feature_bag']) == result, 'Non-deterministic diagnostic'
    result['validation'] = {'same_input_control': 'PASS', 'repeated_reduction_exact': 'PASS',
                            'new_vio_replays': 0, 'new_frontend_runs': 0, 'physical_windows': 1}
    result['driver_build_command'] = command
    result['driver_binary_sha256'] = sha(build / 'audit')
    result['source_identity'] = {str(p): sha(p) for p in (
        Path('scripts/audit_a02_initialization_inputs.cpp'), Path(__file__),
        LIB / 'libvins_lib.so', SOURCE / 'estimator/feature_manager.h',
        SOURCE / 'estimator/feature_manager.cpp', SOURCE / 'estimator/estimator.cpp',
        SOURCE / 'initial/solve_5pts.cpp', SOURCE / 'initial/initial_sfm.cpp',
        SOURCE / 'initial/initial_aligment.cpp')}
    result['inputs'] = {label: {key: row[key] for key in (
        'feature_bag', 'feature_bag_sha256', 'canonical_config', 'canonical_config_sha256')}
        for label, row in (('klt', b), ('delete', d))}
    # The following are sums of printed delta_bg, not measured true biases or
    # final optimized biases. The locked code updates Bgs before alignment and
    # only rolls a failed update back when an explicit option is nonzero.
    result['logged_bias_delta_sums'] = []
    for row in read_csv(PAPER / 'a02_initialization_log_audit.csv'):
        log = (Path(row['replay_directory']) / 'vins.log').read_text()
        assert hashlib.sha256(log.encode()).hexdigest() == row['log_sha256']
        vectors = [list(map(float, match)) for match in re.findall(
            r'gyroscope bias initial calibration\s+([-+\deE.]+)\s+([-+\deE.]+)\s+([-+\deE.]+)', log)]
        result['logged_bias_delta_sums'].append(dict(
            version=row['version'], cell_id=row['cell_id'], repeat=row['repeat'],
            log_sha256=row['log_sha256'], delta_count=len(vectors),
            sum_rad_s=[sum(v[i] for v in vectors) for i in range(3)],
            boundary='Printed-delta sum under recorded no-rollback path; not final optimized or true bias'))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
