#!/usr/bin/env python3
"""Receipt-resumable execution of EXP-012; no search, retuning or expansion."""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path('/home/ma/AQUA-FE_WS')
PAPER = ROOT / 'papers/frontend_admission_continuation_v1'
RUNTIME = Path('/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_admission_continuation_v1')
CONTROL = RUNTIME / 'bounded_execution'
PYTHON = '/usr/bin/python3'
STAGES = [
    ('frontend', 'run_frontend_admission_continuation_v1.py', None),
    ('frontend_audit', 'audit_frontend_admission_continuation_v1.py', 'frontend_audit.csv'),
    ('matched_freeze', 'freeze_frontend_admission_continuation_v1_matched_plan.py', 'matched_control_plan.lock.json'),
    ('matched_build', 'run_frontend_admission_continuation_v1_matched_controls.py', None),
    ('matched_audit', 'audit_frontend_admission_continuation_v1_matched_controls.py', 'matched_control_audit.csv'),
    ('backend_freeze', 'freeze_frontend_admission_continuation_v1_backend_plan.py', 'backend_execution_lock.json'),
    ('backend', 'run_frontend_admission_continuation_v1_backend.py', None),
    ('backend_reduce', 'finalize_frontend_admission_continuation_v1_backend.py', 'backend_decision.json'),
]


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)


def status(stage, state, **extra):
    receipts = list((RUNTIME / 'shadow_root/logs').glob('*/*/frontend_receipt.json'))
    progress = dict(experiment_id='EXP-20260906-012', updated_at=datetime.now().astimezone().isoformat(),
                    controller_pid=os.getpid(), stage=stage, status=state,
                    frontend_receipts_present=len(receipts), frontend_expected=18, **extra)
    write_json(CONTROL / 'progress.json', progress)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--freeze-release', action='store_true')
    args = parser.parse_args()
    CONTROL.mkdir(parents=True, exist_ok=True)
    release_path = CONTROL / 'release_lock.json'
    if args.freeze_release:
        if release_path.exists():
            raise RuntimeError('Refusing to overwrite controller release lock')
        paths = {ROOT / 'scripts' / script for _, script, _ in STAGES}
        paths |= {Path(__file__).resolve(), PAPER / 'method_lock.json', PAPER / 'preregistration.md'}
        paths |= {ROOT / 'scripts' / name for name in (
            'run_frontend_geometry_maturity_router_v1.py', 'run_frontend_protected_prefill_slot_v1_matched_controls.py',
            'run_frontend_coverage_monotone_router_v2_matched_controls.py',
            'audit_frontend_protected_prefill_slot_v1_matched_controls.py',
            'audit_frontend_coverage_monotone_router_v2_matched_controls.py',
            'run_frontend_admission_continuation_v1_backend_cell.sh', 'build_gftt_matched_lineage_control.py',
            'finalize_frontend_coverage_monotone_router_v2_backend.py', 'evaluate_vins_common_support_dual_scale.py')}
        write_json(release_path, dict(frozen_at=datetime.now().astimezone().isoformat(),
                                     files=[dict(path=str(p), sha256=sha(p)) for p in sorted(paths)]))
        print('RELEASE_FROZEN', release_path, flush=True)
        return 0
    with (CONTROL / 'controller.flock').open('a') as guard:
        fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release = json.loads(release_path.read_text())
        for item in release['files']:
            if sha(Path(item['path'])) != item['sha256']:
                raise RuntimeError(f"Release identity drift: {item['path']}")
        # Existing method runner additionally checks the full frozen source/input closure.
        for stage, script, completed_marker in STAGES:
            if completed_marker and (PAPER / completed_marker).exists():
                print('PRESERVE_EXISTING_STAGE', stage, flush=True)
                continue
            if stage == 'matched_freeze':
                decision = json.loads((PAPER / 'decision.json').read_text())
                if decision['decision'] != 'FRONTEND_GO':
                    status(stage, 'FROZEN_STOP', decision=decision['decision'])
                    return 0
            log_path = CONTROL / f'{stage}.log'
            with log_path.open('a') as output:
                print('START_STAGE', stage, flush=True)
                command = [PYTHON, str(ROOT / 'scripts' / script)]
                process = subprocess.Popen(command, cwd=ROOT, stdout=output, stderr=subprocess.STDOUT)
                while process.poll() is None:
                    status(stage, 'RUNNING', child_pid=process.pid, stage_log=str(log_path))
                    time.sleep(20)
                code = process.returncode
            print('FINISH_STAGE', stage, 'rc', code, flush=True)
            if code:
                status(stage, 'STOPPED_STAGE_ERROR', return_code=code, stage_log=str(log_path))
                return code
        decision = json.loads((PAPER / 'backend_decision.json').read_text())
        status('complete', 'FROZEN_STOP', decision=decision['decision'],
               next_step='Review and publish complete evidence; no automatic new-window or second-variant execution.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
