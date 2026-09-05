#!/usr/bin/env python3
"""Materialize all seven frozen v3 matched-GFTT controls."""

from __future__ import annotations

from pathlib import Path

import run_frontend_coverage_monotone_router_v2_matched_controls as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_delayed_newborn_slot_v3"
)
SHADOW = RUNTIME / "shadow_root"


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"dnr3_{window['run_slug']}_{arm['arm']}"
    )


def main() -> int:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = SHADOW
    base.PLAN = PAPER / "matched_control_plan.json"
    base.EXPECTED_PLAN_SHA256 = (
        "342c5b25537fe0e4952430a62506db560124391a454cf4e958bc732d0951bdfa"
    )
    base.BUILDER_SHA256_OVERRIDE = (
        "7dd75c8ffc6e9ec47231d8de4904ddde0c54451f200f0b22ac03490b74dc0b46"
    )
    base.SPARSE_SCHEDULE_CELLS = {
        ("afrl_cemetery_s135_d045", "router_xfeat")
    }
    base.REUSE_COMPLETED = True
    base.run_dir = run_dir
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
