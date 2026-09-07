#!/usr/bin/env python3
"""Check recorded estimator environment and executable lookup against reused KLT."""
import json
import re
import shutil
from pathlib import Path

import rosbag

import run_frontend_admission_continuation_v1 as run
import finalize_frontend_coverage_monotone_router_v2_backend as common


def main():
    target = run.PAPER / 'backend_environment_audit.csv'
    if target.exists():
        raise RuntimeError('Refusing to overwrite completed environment audit')
    plan = common.read_csv(run.PAPER / 'backend_replay_plan.csv')
    baselines = {(r['run_slug'], r['repeat']): r for r in plan if r['cell_id'] == 'klt'}
    rows = []
    feature_start = {}
    # These are the estimator/library/numeric settings recorded by the existing
    # recorder. Run paths, timestamps and the private ROS port are not identities.
    numeric = {'LD_LIBRARY_PATH', 'CMAKE_PREFIX_PATH', 'ROS_PACKAGE_PATH',
               'PYTHONPATH', 'ROS_DISTRO', 'PYTHONHASHSEED', 'PYTHONNOUSERSITE',
               'OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS'}
    for row in plan:
        baseline = baselines[(row['run_slug'], row['repeat'])]
        reference_path = Path(baseline['replay_dir']) / 'vins_env_manifest.txt'
        current_path = Path(row['replay_dir']) / 'vins_env_manifest.txt'
        item = dict(run_slug=row['run_slug'], cell_id=row['cell_id'], repeat=row['repeat'],
                    execution=row['execution'], reference_manifest=str(reference_path),
                    current_manifest=str(current_path))
        if row['run_slug'] not in feature_start:
            with rosbag.Bag(baseline['feature_bag']) as bag:
                first = next(bag.read_messages(topics=['/feature_tracker/feature']))
                feature_start[row['run_slug']] = first.message.header.stamp.to_nsec()
        start_ns = feature_start[row['run_slug']]
        log = Path(row['replay_dir']) / 'vins.log'
        text = log.read_text(errors='replace') if log.is_file() else ''
        init = re.findall(r'\[\s*([0-9.]+),\s*([0-9.]+)\]: Initialization finish!', text)
        vio = Path(row['replay_dir']) / 'vins_output/vio.csv'
        with vio.open() if vio.is_file() else open('/dev/null') as stream:
            first_vio = next((line.strip().split(',')[0] for line in stream if line.strip()), '')
        item.update(first_feature_timestamp_ns=start_ns, initialization_log_count=len(init),
                    first_initialization_ros_time_s=init[0][1] if init else 'Unknown',
                    initialization_log_delay_s=float(init[0][1])-start_ns/1e9 if init else 'Unknown',
                    first_vio_timestamp_ns=first_vio or 'Unknown',
                    first_vio_delay_s=(int(first_vio)-start_ns)/1e9 if first_vio else 'Unknown',
                    timing_boundary='Initialization log uses replay ROS clock; first VIO pose uses sensor timestamp. Neither is a per-ID residual receipt.')
        if not reference_path.is_file() or not current_path.is_file():
            rows.append(dict(item, status='NOT_EVALUATED_MISSING_MANIFEST'))
            continue
        old, new = common.parse_receipt(reference_path), common.parse_receipt(current_path)
        keys = sorted({k for k in old if k.startswith('VINS_')} | numeric)
        differences = {k: [old.get(k, ''), new.get(k, '')] for k in keys
                       if old.get(k, '') != new.get(k, '')}
        executable_lookup = {name: [shutil.which(name, path=old.get('PATH', '')),
                                   shutil.which(name, path=new.get('PATH', ''))]
                             for name in ('rosbag', 'roscore', 'python3')}
        lookup_ok = all(a and a == b for a, b in executable_lookup.values())
        rows.append(dict(item, status='PASS' if not differences and lookup_ok else 'FAIL',
                         semantic_keys=len(keys), semantic_differences_json=json.dumps(differences),
                         executable_lookup_json=json.dumps(executable_lookup),
                         reference_manifest_sha256=common.sha256(reference_path),
                         current_manifest_sha256=common.sha256(current_path),
                         boundary='Recorded settings and present executable lookup; not a claim that transient PATH text or ROS port is byte-identical.'))
    common.write_csv(target, rows)
    print(json.dumps({status: sum(r['status'] == status for r in rows)
                      for status in sorted({r['status'] for r in rows})}))


if __name__ == '__main__':
    main()
