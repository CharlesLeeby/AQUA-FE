#!/usr/bin/env python3
"""Audit all newly generated v3 matched-GFTT controls."""

from __future__ import annotations

from pathlib import Path

import audit_frontend_coverage_monotone_router_v2_actions as action_base
import audit_frontend_coverage_monotone_router_v2_matched_controls as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"


def main() -> int:
    base.PAPER = PAPER
    base.bag_inventory = action_base.bag_inventory
    base.sha256 = action_base.sha256
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
