#!/usr/bin/env python3
"""Materialize all frozen protected-slot matched-GFTT controls."""

from __future__ import annotations

import json
from pathlib import Path

import run_frontend_coverage_monotone_router_v2_matched_controls as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_protected_prefill_slot_v1"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_protected_prefill_slot_v1"
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
        f"ppsv1_{window['run_slug']}_{arm['arm']}"
    )


def main() -> int:
    lock_path = PAPER / "matched_control_plan.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    plan_path = PAPER / "matched_control_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = SHADOW
    base.PLAN = plan_path
    base.EXPECTED_PLAN_SHA256 = str(lock["matched_control_plan_sha256"])
    base.BUILDER_SHA256_OVERRIDE = None
    base.SPARSE_SCHEDULE_CELLS = {
        (str(cell["run_slug"]), str(cell["arm"]))
        for cell in plan["cells"]
        if bool(cell.get("allow_sparse_target_schedule", False))
    }
    base.REUSE_COMPLETED = True
    base.run_dir = run_dir
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
