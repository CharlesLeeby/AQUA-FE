#!/usr/bin/env python3
"""Audit all protected-slot matched-GFTT controls."""

from __future__ import annotations

from pathlib import Path

import audit_frontend_coverage_monotone_router_v2_actions as action_common
import audit_frontend_coverage_monotone_router_v2_matched_controls as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"


def main() -> int:
    base.PAPER = PAPER
    base.bag_inventory = action_common.bag_inventory
    base.sha256 = action_common.sha256
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
