#!/usr/bin/env python3
"""One audited input-alignment correction after an invalid source attempt.

Never modifies the original frozen runner. The only execution overlay requires
the already frozen raw frame stride/offset when associating a B output. Tracking
still consumes every raw image. No candidate or backend outcome is inspected.
"""
import hashlib
import fcntl
import json
from pathlib import Path
from run_additive_budget_v1 import ROOT, PAPER, RUNTIME, sha, save, verify


def main():
    lock=verify()
    recovery=json.loads((PAPER/'cemetery_recovery_lock.json').read_text())
    for p,h in recovery['files'].items():
        assert sha(ROOT/p)==h,p
    original=ROOT/'scripts/run_additive_budget_v1.py'
    source=original.read_text()
    old='            if ns not in by_stamp:continue\n'
    new='            if ns not in by_stamp or not generate:continue\n'
    assert source.count(old)==1
    corrected=source.replace(old,new)
    assert hashlib.sha256(corrected.encode()).hexdigest()==recovery['overlaid_runner_sha256']
    namespace={'__file__':str(original),'__name__':'additive_cemetery_alignment_recovery'}
    exec(compile(corrected,str(original)+'[frozen-frame-index-overlay]','exec'),namespace)
    with (RUNTIME/'frontend.lock').open('a') as handle:
        print('WAITING_FOR_OWN_FRONTEND_LOCK',flush=True)
        fcntl.flock(handle,fcntl.LOCK_EX)
        namespace['frontend']('afrl_cemetery_s135_d045')
    root=RUNTIME/'frontend/afrl_cemetery_s135_d045'
    save(root/'recovery_execution.json',dict(recovery_lock_sha256=sha(PAPER/'cemetery_recovery_lock.json'),
        original_runner_sha256=sha(original),overlaid_runner_sha256=recovery['overlaid_runner_sha256'],
        resulting_frontend_receipt_sha256=sha(root/'receipt.json'),
        invalid_attempt=recovery['invalid_attempt'],valid_source_streams_per_source=1,
        source_generation_attempts_per_source=2,
        boundary='one invalid first attempt retained; no duplicate inference for L6/L-all; frame-index association repair only'))


if __name__=='__main__':
    main()
