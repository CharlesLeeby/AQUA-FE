#!/usr/bin/env python3
"""Inventory compact evidence and local run identities without deleting failures."""
import csv
from pathlib import Path

import run_frontend_admission_continuation_v1 as run
import finalize_frontend_coverage_monotone_router_v2_backend as common


def logical(path):
    for root, prefix in [(run.PAPER, 'paper:'), (run.RUNTIME, 'continuation_runtime:'),
                         (run.RUNTIME.parent / 'frontend_coverage_monotone_router_v2', 'v2_runtime:'),
                         (run.ROOT, 'repo:')]:
        try:
            return prefix + str(path.relative_to(root))
        except ValueError:
            pass
    return str(path)


def main():
    target = run.PAPER / 'artifacts.sha256'
    if target.exists():
        raise RuntimeError('Refusing to overwrite completed artifact manifest')
    paths = set()
    for name in ['preregistration.md', 'development_windows.csv', 'arms.csv', 'method_lock.json',
                 'probe_audit.json', 'probe_lineage_events.csv', 'frontend_audit.csv', 'action_audit.csv',
                 'decision.json', 'matched_control_plan.json', 'matched_control_plan.lock.json',
                 'matched_control_audit.csv', 'backend_replay_plan.csv', 'backend_execution_lock.json',
                 'backend_results_repeats.csv', 'backend_results.csv', 'runability.csv',
                 'common_support_status.csv', 'accuracy.csv', 'accuracy_repeats.csv',
                 'backend_comparisons.csv', 'development_outcomes.csv', 'backend_config_audit.csv',
                 'backend_decision.json', 'backend_environment_audit.csv', 'lineage_diagnostic.csv', 'v2_common_comparison.csv', 'report.md']:
        paths.add(run.PAPER / name)
    for name in ['run_aquafe_v2_bounded_continuation.py', 'analyze_admission_continuation_v1_lineages.py',
                 'analyze_admission_continuation_v1_v2_comparison.py', 'analyze_admission_continuation_v1_environment.py',
                 'build_admission_continuation_v1_manifest.py']:
        paths.add(run.ROOT / 'scripts' / name)
    for path in (run.RUNTIME / 'shadow_root/logs').glob('*/*/frontend_receipt.json'):
        paths.add(path)
        paths.update(path.parent / name for name in ['features.bag', 'frontend_metrics.csv', 'lifecycle_events.csv', 'lifecycle_frames.csv'])
    plan = run.PAPER / 'backend_replay_plan.csv'
    if plan.exists():
        for row in common.read_csv(plan):
            paths.update(Path(row[name]) for name in ['feature_bag', 'canonical_config', 'camera_config'])
            replay = Path(row['replay_dir'])
            paths.update(replay / name for name in ['replay_receipt.txt', 'vins_output/vio.csv', 'vins.log', 'vins_env_manifest.txt'])
    for family in ['common_support', 'v2_common_support']:
        for directory in (run.PAPER / family).glob('*'):
            paths.update(directory / name for name in ['common_support_summary.json', 'common_support_metrics.csv', 'evo_crosscheck.json'])
    for path in (run.PAPER / 'matched_controls').glob('*/*/*.json'):
        paths.add(path)
    paths.update(path for path in (run.PAPER / 'backend_config_snapshots').rglob('*') if path.is_file())
    paths.add(run.RUNTIME / 'bounded_execution/release_lock.json')
    rows = []
    with target.open('x') as stream:
        for path in sorted(paths, key=logical):
            exists = path.is_file()
            digest = common.sha256(path) if exists else ''
            rows.append(dict(path=logical(path), status='PRESENT' if exists else 'MISSING_NOT_FABRICATED', sha256=digest))
            if exists:
                stream.write(f'{digest}  {logical(path)}\n')
    common.write_csv(run.PAPER / 'artifact_inventory.csv', rows)
    print('PRESENT', sum(r['status']=='PRESENT' for r in rows), 'MISSING', sum(r['status']!='PRESENT' for r in rows))


if __name__ == '__main__':
    main()
