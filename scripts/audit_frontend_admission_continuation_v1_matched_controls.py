#!/usr/bin/env python3
"""Audit all new matched controls with the unchanged v2 identity checks."""
import run_frontend_admission_continuation_v1 as run
import audit_frontend_protected_prefill_slot_v1_matched_controls as base

if __name__ == "__main__":
    base.PAPER = run.PAPER
    raise SystemExit(base.main())
