#!/usr/bin/env python3
"""Use the existing matched builder for the newly frozen lifecycle schedule."""
import run_frontend_admission_continuation_v1 as run
import run_frontend_protected_prefill_slot_v1_matched_controls as base

if __name__ == "__main__":
    run.configure()
    base.PAPER, base.RUNTIME, base.SHADOW = run.PAPER, run.RUNTIME, run.RUNTIME / "shadow_root"
    base.run_dir = run.run_dir
    raise SystemExit(base.main())
