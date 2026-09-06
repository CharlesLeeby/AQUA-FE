#!/usr/bin/env python3
"""Run the frozen protected pre-refill slot v1 frontend development matrix."""

from __future__ import annotations

import argparse
from pathlib import Path

import run_frontend_geometry_maturity_router_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_protected_prefill_slot_v1"
)


def run_dir(window: dict[str, str], arm: dict[str, str]) -> Path:
    log_family = {
        "aqualoc_archaeology": "aqualoc_archaeo_vins",
        "aqualoc_harbor": "aqualoc_real_vins",
        "afrl": "afrl_cave_v31",
    }[window["family"]]
    return base.SHADOW / "logs" / log_family / (
        f"external_{arm['method']}_every{window['every_n']}_"
        f"ppsv1_{window['run_slug']}_{arm['arm']}"
    )


def configure() -> None:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = RUNTIME / "shadow_root"
    base.REGISTRATION = {
        PAPER / "preregistration.md": (
            "0c4055031ad5d5400bd4b52c2bae932357b142b569b75b2af359791b4ea22a82"
        ),
        PAPER / "development_windows.csv": (
            "375469dcc1fb49e179196f682c62b2fca6a81704ce6e51dc1e13e30adaa98323"
        ),
        PAPER / "arms.csv": (
            "c79064806baa5c02a06de7c5adf107a5ae565e1b8e7be4470b0ab8491c6502b4"
        ),
    }
    base.RUN_LABEL = "ppsv1"
    base.CELL_SCHEMA = "aqua-fe-protected-prefill-slot-v1-cell-v1"
    base.METHOD_LOCK_FILENAME = "method_lock.json"
    base.run_dir = run_dir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--probe-cell",
        help="Run only RUN_SLUG:ARM after all frozen identity checks.",
    )
    args = parser.parse_args()
    configure()
    if not args.probe_cell:
        return base.main()

    method_lock = base.verify_registration_and_method()
    base.prepare_shadow()
    try:
        run_slug, arm_name = args.probe_cell.split(":", 1)
    except ValueError as exc:
        raise SystemExit("--probe-cell must be RUN_SLUG:ARM") from exc
    windows = [
        row
        for row in base.read_csv(PAPER / "development_windows.csv")
        if row["run_slug"] == run_slug
    ]
    arms = [
        row
        for row in base.read_csv(PAPER / "arms.csv")
        if row["arm"] == arm_name
    ]
    if len(windows) != 1 or len(arms) != 1:
        raise SystemExit(f"unknown frozen probe cell: {args.probe_cell}")
    base.run_cell(windows[0], arms[0], method_lock)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
