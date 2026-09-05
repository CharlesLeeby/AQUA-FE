#!/usr/bin/env python3
"""Run the frozen delayed-newborn-slot v3 frontend development matrix."""

from __future__ import annotations

from pathlib import Path

import run_frontend_geometry_maturity_router_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_delayed_newborn_slot_v3"
)


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return base.SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"dnr3_{window['run_slug']}_{arm['arm']}"
    )


def main() -> int:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = RUNTIME / "shadow_root"
    base.REGISTRATION = {
        PAPER / "preregistration.md": (
            "08515063cd998faa79343b7e839f7d5275a61b7454f558376a730ae94f8d8e91"
        ),
        PAPER / "development_windows.csv": (
            "375469dcc1fb49e179196f682c62b2fca6a81704ce6e51dc1e13e30adaa98323"
        ),
        PAPER / "arms.csv": (
            "b203b219378810c3e07d307af91470ce9b1b34abb767916473ce7cee84476a37"
        ),
    }
    base.RUN_LABEL = "dnr3"
    base.CELL_SCHEMA = "aqua-fe-delayed-newborn-slot-v3-cell-v1"
    base.METHOD_LOCK_FILENAME = "method_lock.json"
    base.run_dir = run_dir
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
