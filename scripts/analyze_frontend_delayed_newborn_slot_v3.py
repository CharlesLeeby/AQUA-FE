#!/usr/bin/env python3
"""Reduce the frozen v3 frontend matrix using its preregistered gates."""

from __future__ import annotations

import json
from pathlib import Path

import analyze_frontend_coverage_monotone_router_v2 as v2


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


def truth(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def main() -> int:
    v2.PAPER = PAPER
    v2.RUNTIME = RUNTIME
    v2.SHADOW = SHADOW
    v2.run_dir = run_dir
    v2.main()

    rows = v2.base.read_csv(PAPER / "frontend_audit.csv")
    learned = [row for row in rows if row["arm"] != "klt"]
    actions = v2.base.read_csv(PAPER / "action_audit.csv")
    real_actions = [
        row for row in actions
        if int(float(row.get("promoted_observations", "0") or 0)) > 0
    ]
    startup = v2.base.read_csv(PAPER / "startup_protection_audit.csv")
    safety = {
        "all_cells_integrity": all(truth(row["integrity_pass"]) for row in rows),
        "startup_frames_0_31_exact_klt": all(row["status"] == "PASS" for row in startup),
        "actions_only_frames_32_36": all(
            32 <= int(float(row["selected_feature_index"])) <= 36
            for row in real_actions
        ),
        "no_tracked_klt_or_old_gftt_removed": all(
            int(float(row["max_replaced_gftt_age"])) in (-1, 1)
            for row in learned
        ),
        "age_advantage_at_least_2": all(
            int(float(row["min_actual_age_advantage"])) == -1
            or int(float(row["min_actual_age_advantage"])) >= 2
            for row in learned
        ),
        "donor_cell_retained": all(
            int(float(row["replacement_count"])) == 0
            or int(float(row["donor_cell_min_remaining"])) >= 1
            for row in learned
        ),
        "grid_occupancy_monotone": all(
            int(float(row["grid_action_min_delta"])) >= 0 for row in learned
        ),
        "per_frame_cap_6": all(
            int(float(row["max_sidecars_per_frame"])) <= 6 for row in learned
        ),
        "zero_action_exact_klt": all(
            int(float(row["kept_sidecars"])) > 0
            or truth(row["byte_identical_to_klt"])
            for row in learned
        ),
    }
    active = [row for row in learned if int(float(row["kept_sidecars"])) > 0]
    matched_expected = [
        PAPER / "matched_controls" / row["run_slug"] / row["arm"] / "stats.json"
        for row in active
    ]
    matched_complete = bool(active) and all(path.is_file() for path in matched_expected)
    if not all(safety.values()):
        decision = "REJECT_FRONTEND"
    elif not active:
        decision = "SAFE_NULL"
    elif not matched_complete:
        decision = "PENDING_MATCHED_CONTROL"
    else:
        decision = "FRONTEND_GO"
    summary = {
        "schema_version": "aqua-fe-delayed-newborn-slot-v3-frontend-v1",
        "experiment_id": "EXP-20260905-008",
        "cells_expected": 18,
        "cells_present": sum(row["cell_status"] != "MISSING" for row in rows),
        "active_arm_windows": len(active),
        "active_cells": [f"{row['run_slug']}:{row['arm']}" for row in active],
        "safety_checks": safety,
        "matched_control_complete": matched_complete,
        "matched_control_expected": [str(path) for path in matched_expected],
        "decision": decision,
    }
    (PAPER / "decision.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Delayed newborn-slot router v3: frontend result",
        "",
        "Date: 2026-09-05",
        "",
        f"Decision: `{decision}`.",
        "",
        "Outcome-known development controls only; backend is Not evaluated here.",
        "",
        f"- Complete cells: {summary['cells_present']}/18.",
        f"- Action-positive learned arm-windows: {len(active)}.",
        f"- Active cells: {', '.join(summary['active_cells']) or 'none'}.",
        "",
        "## Frozen frontend checks",
        "",
    ]
    for key, value in safety.items():
        lines.append(f"- `{key}`: {'PASS' if value else 'FAIL'}")
    lines += [
        "",
        f"- `matched_control_complete`: {matched_complete}",
        "",
        "No action count or proxy quantity is interpreted as backend success.",
    ]
    (PAPER / "export_only_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if decision in {"PENDING_MATCHED_CONTROL", "FRONTEND_GO"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
