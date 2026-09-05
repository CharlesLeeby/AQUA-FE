#!/usr/bin/env python3
"""Reduce the coverage-monotone router v2 export-only development matrix."""

from __future__ import annotations

import json
from pathlib import Path

import analyze_frontend_geometry_maturity_router_v1 as base


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/"
    "frontend_coverage_monotone_router_v2"
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
        f"gmrv2_{window['run_slug']}_{arm['arm']}"
    )


def reduce_cell(
    window: dict[str, str], arm: dict[str, str], klt_sha: str
) -> dict[str, object]:
    row = base.reduce_cell(window, arm, klt_sha)
    metrics_path = run_dir(window, arm) / "frontend_metrics.csv"
    if not metrics_path.is_file():
        row.update(
            {
                "coverage_monotone_active": False,
                "coverage_monotone_suppressed": 0,
                "grid_action_min_delta": -999,
                "cross_cell_replacements": 0,
                "donor_cell_min_remaining": -999,
                "global_ratio_active_frames": 0,
            }
        )
        return row
    metrics = base.read_csv(metrics_path)
    action_rows = [
        item
        for item in metrics
        if base.number(item, "final_mirror_kept_sidecars") > 0
    ]
    replacement_rows = [
        item
        for item in metrics
        if base.number(item, "final_mirror_persistence_replaced_gftt") > 0
    ]
    row.update(
        {
            "coverage_monotone_active": all(
                base.number(
                    item,
                    "final_mirror_persistence_coverage_monotone_active",
                )
                > 0
                for item in metrics
            ),
            "coverage_monotone_suppressed": int(
                sum(
                    base.number(
                        item,
                        "final_mirror_persistence_coverage_monotone_suppressed",
                    )
                    for item in metrics
                )
            ),
            "grid_action_min_delta": int(
                min(
                    (
                        base.number(
                            item,
                            "final_mirror_persistence_grid_cell_delta",
                        )
                        for item in action_rows
                    ),
                    default=0,
                )
            ),
            "cross_cell_replacements": int(
                sum(
                    base.number(
                        item,
                        "final_mirror_persistence_cross_cell_replacements",
                    )
                    for item in metrics
                )
            ),
            "donor_cell_min_remaining": int(
                min(
                    (
                        base.number(
                            item,
                            "final_mirror_persistence_donor_cell_min_remaining",
                            -999,
                        )
                        for item in replacement_rows
                    ),
                    default=-1,
                )
            ),
            "global_ratio_active_frames": int(
                sum(
                    base.number(
                        item,
                        "final_mirror_persistence_churn_guard_active",
                    )
                    > 0
                    for item in metrics
                )
            ),
        }
    )
    return row


def main() -> int:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.SHADOW = SHADOW
    base.run_dir = run_dir
    windows = base.read_csv(PAPER / "development_windows.csv")
    arms = base.read_csv(PAPER / "arms.csv")
    output_rows: list[dict[str, object]] = []
    for window in windows:
        klt_arm = next(arm for arm in arms if arm["arm"] == "klt")
        receipt_path = run_dir(window, klt_arm) / "frontend_receipt.json"
        klt_sha = ""
        if receipt_path.is_file():
            klt_sha = json.loads(receipt_path.read_text(encoding="utf-8")).get(
                "feature_bag_sha256", ""
            )
        for arm in arms:
            output_rows.append(reduce_cell(window, arm, klt_sha))
    base.write_csv(PAPER / "frontend_audit.csv", output_rows)

    learned_rows = [row for row in output_rows if row["arm"] != "klt"]
    safety_checks = {
        "all_cells_integrity": all(row["integrity_pass"] for row in output_rows),
        "coverage_router_active": all(
            bool(row["coverage_monotone_active"]) for row in learned_rows
        ),
        "global_ratio_disabled": all(
            int(row["global_ratio_active_frames"]) == 0 for row in learned_rows
        ),
        "no_tracked_klt_or_old_gftt_removed": all(
            int(row["max_replaced_gftt_age"]) in (-1, 1)
            for row in learned_rows
        ),
        "age_advantage": all(
            int(row["min_actual_age_advantage"]) == -1
            or int(row["min_actual_age_advantage"]) >= 2
            for row in learned_rows
        ),
        "donor_cell_retained": all(
            int(row["replacement_count"]) == 0
            or int(row["donor_cell_min_remaining"]) >= 1
            for row in learned_rows
        ),
        "grid_occupancy_monotone": all(
            int(row["grid_action_min_delta"]) >= 0 for row in learned_rows
        ),
        "per_frame_cap": all(
            int(row["max_sidecars_per_frame"]) <= 6 for row in learned_rows
        ),
        "zero_action_exact_klt": all(
            int(row["kept_sidecars"]) > 0 or bool(row["byte_identical_to_klt"])
            for row in learned_rows
        ),
        "harm_controls_zero_action": all(
            int(row["kept_sidecars"]) == 0
            for row in learned_rows
            if row["role"] in {"harm_control", "stability_control", "noharm_anchor"}
        ),
    }
    opportunity_slugs = {
        str(row["run_slug"])
        for row in learned_rows
        if row["role"] in {"rescue_control", "opportunity_control"}
        and int(row["kept_sidecars"]) > 0
    }
    opportunity_checks = {
        "at_least_two_action_windows": len(opportunity_slugs) >= 2,
        "at_least_one_multiframe_lineage": any(
            int(row["max_lineage_observations"]) >= 2 for row in learned_rows
        ),
    }
    active_rows = [row for row in learned_rows if int(row["kept_sidecars"]) > 0]
    matched_paths = [
        PAPER / "matched_controls" / str(row["run_slug"]) / str(row["arm"])
        / "stats.json"
        for row in active_rows
    ]
    matched_complete = bool(active_rows) and all(path.is_file() for path in matched_paths)
    safety_pass = all(safety_checks.values())
    opportunity_pass = all(opportunity_checks.values())
    if not safety_pass:
        decision = "REJECT_SAFETY"
    elif not opportunity_pass:
        decision = "SAFE_NULL"
    elif not matched_complete:
        decision = "PENDING_MATCHED_CONTROL"
    else:
        decision = "EXPORT_ONLY_GO"
    matched_status = (
        "NOT_REQUIRED_AFTER_STOP"
        if decision in {"REJECT_SAFETY", "SAFE_NULL"}
        else ("COMPLETE" if matched_complete else "PENDING")
    )
    summary = {
        "schema_version": "aqua-fe-coverage-monotone-router-v2-analysis-v1",
        "cells_expected": len(windows) * len(arms),
        "cells_present": sum(row["cell_status"] != "MISSING" for row in output_rows),
        "active_arm_windows": len(active_rows),
        "action_opportunity_windows": sorted(opportunity_slugs),
        "safety_checks": safety_checks,
        "opportunity_checks": opportunity_checks,
        "matched_control_complete": matched_complete,
        "matched_control_status": matched_status,
        "matched_control_expected": [str(path) for path in matched_paths],
        "decision": decision,
    }
    (PAPER / "decision.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# Coverage-monotone router v2: export-only development result",
        "",
        "Date: 2026-09-05",
        "",
        f"Decision: `{decision}`.",
        "",
        "Outcome-known development controls only; not confirmatory evidence.",
        "",
        "## Matrix",
        "",
        f"- Complete cells: {summary['cells_present']}/{summary['cells_expected']}.",
        f"- Action-positive learned arm-windows: {len(active_rows)}.",
        f"- Action-positive opportunity windows: {', '.join(sorted(opportunity_slugs)) or 'none'}.",
        "",
        "## Frozen checks",
        "",
    ]
    for key, value in {**safety_checks, **opportunity_checks}.items():
        lines.append(f"- `{key}`: {'PASS' if value else 'FAIL'}")
    lines += [
        f"- `matched_control_status`: `{matched_status}`",
        "",
        "## Evidence boundary",
        "",
        "No backend result is interpreted here. Matched classical and backend work require the frozen preceding gates.",
    ]
    (PAPER / "export_only_report.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
