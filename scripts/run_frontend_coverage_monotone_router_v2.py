#!/usr/bin/env python3
"""Run the preregistered coverage-monotone router v2 frontend matrix."""

from __future__ import annotations

from pathlib import Path

import run_frontend_geometry_maturity_router_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
)


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return base.SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"gmrv2_{window['run_slug']}_{arm['arm']}"
    )


def main() -> int:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = RUNTIME / "shadow_root"
    base.REGISTRATION = {
        PAPER / "preregistration.md": (
            "b2d01fd63d1347b48b04a8c7d6f81602c4e6021fd5e1e37db6a94213dd78ffeb"
        ),
        PAPER / "development_windows.csv": (
            "8fb87b023f525da6610ced4fa591916399b4750c01f1d96177ca47e04cde9915"
        ),
        PAPER / "arms.csv": (
            "795e4737af8b8d932f18a6921348c1205eccc07dcf27c3462218b69f8eada57c"
        ),
    }
    base.RUN_LABEL = "gmrv2"
    base.CELL_SCHEMA = "aqua-fe-coverage-monotone-router-v2-cell-v1"
    base.METHOD_LOCK_FILENAME = "method_lock_recovery1.json"
    base.run_dir = run_dir
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
