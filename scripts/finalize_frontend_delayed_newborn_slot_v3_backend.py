#!/usr/bin/env python3
"""Reduce EXP-20260905-008 and apply its frozen development decision."""

from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import finalize_frontend_coverage_monotone_router_v2_backend as base
import run_frontend_delayed_newborn_slot_v3_backend as runner


ROOT = Path("/home/ma/AQUA-FE_WS")
PAPER = ROOT / "papers/frontend_delayed_newborn_slot_v3"
RUNTIME = Path(
    "/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_delayed_newborn_slot_v3"
)
PLAN = PAPER / "backend_replay_plan.csv"
V2_PAPER = ROOT / "papers/frontend_coverage_monotone_router_v2"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def configure_base() -> None:
    base.PAPER = PAPER
    base.RUNTIME = RUNTIME
    base.REPLAYS = RUNTIME / "backend_replays"
    base.PLAN = PLAN
    base.LOCK = PAPER / "backend_execution_lock.json"
    base.EXPECTED_PLAN_ROWS = 54


def build_runability(backend: list[dict[str, object]]) -> list[dict[str, object]]:
    by_cell = {(str(row["run_slug"]), str(row["cell_id"])): row for row in backend}
    v2_by_cell = {
        (row["run_slug"], row["cell_id"]): row
        for row in read_csv(V2_PAPER / "backend_results.csv")
    }
    front = read_csv(PAPER / "frontend_audit.csv")
    output: list[dict[str, object]] = []
    for row in front:
        slug, arm = row["run_slug"], row["arm"]
        action = arm != "klt" and int(row["kept_sidecars"]) > 0
        exact = arm != "klt" and row["byte_identical_to_klt"] == "True"
        if (slug, "klt") in by_cell:
            mapped = by_cell[(slug, arm if action else "klt")]
        else:
            if action or (arm != "klt" and not exact):
                raise RuntimeError(f"unplanned action cell: {slug}:{arm}")
            mapped = v2_by_cell[(slug, "klt")]
        output.append({
            "window_id": row["window_id"], "run_slug": slug, "arm": arm,
            "role": "frontend_primary", "frontend_action": action,
            "feature_bag_sha256": row["feature_bag_sha256"],
            "backend_execution": (
                "INDEPENDENT_NEW_V3_REPLAY" if action else
                "REUSED_EXACT_KLT_INPUT_AND_FROZEN_V2_REPLAY"
            ),
            "mapped_backend_cell": arm if action else "klt",
            "independent_replays": 3 if action else 0,
            "mapped_replays": 0 if action else 3,
            "backend_repeats_pass": mapped["backend_repeats_pass"],
            "arm_window_status": mapped["arm_window_status"],
            "init_repeats": mapped["init_repeats"],
            "pose_count_median": mapped["pose_count_median"],
            "pose_count_range": mapped["pose_count_range"],
            "coverage_median": mapped["coverage_median"],
            "coverage_range": mapped["coverage_range"],
            "accuracy_role": "EVALUATE_IF_COMMON_SUPPORT" if action else "EXACT_TIE_NO_ACTION",
        })
    for match in read_csv(PAPER / "matched_control_audit.csv"):
        cell_id = f"matched_gftt_for_{match['arm']}"
        mapped = by_cell[(match["run_slug"], cell_id)]
        output.append({
            "window_id": mapped["window_id"], "run_slug": match["run_slug"],
            "arm": cell_id, "role": "matched_classical_attribution_control",
            "frontend_action": True, "feature_bag_sha256": mapped["feature_bag_sha256"],
            "backend_execution": "INDEPENDENT_NEW_V3_REPLAY", "mapped_backend_cell": cell_id,
            "independent_replays": 3, "mapped_replays": 0,
            "backend_repeats_pass": mapped["backend_repeats_pass"],
            "arm_window_status": mapped["arm_window_status"],
            "init_repeats": mapped["init_repeats"],
            "pose_count_median": mapped["pose_count_median"],
            "pose_count_range": mapped["pose_count_range"],
            "coverage_median": mapped["coverage_median"],
            "coverage_range": mapped["coverage_range"],
            "accuracy_role": "EVALUATE_WITH_CORRESPONDING_LEARNED_ARM",
        })
    write_csv(PAPER / "runability.csv", output)
    return output


def build_outcomes(
    comparisons: list[dict[str, object]],
    front: list[dict[str, str]],
) -> list[dict[str, object]]:
    by_active = {(str(row["run_slug"]), str(row["learned_arm"])): row for row in comparisons}
    rows: list[dict[str, object]] = []
    for item in front:
        if item["arm"] == "klt":
            continue
        action = int(item["kept_sidecars"]) > 0
        if not action:
            rows.append({
                "window_id": item["window_id"], "run_slug": item["run_slug"],
                "arm": item["arm"], "action": False, "outcome": "TIE",
                "common_support_status": "MAPPED_BYTE_IDENTICAL_KLT",
                "ape_percent_change": 0.0, "rpe_percent_change": 0.0,
                "notes": "No independent replay; exact input identity maps to KLT.",
            })
            continue
        comp = by_active[(item["run_slug"], item["arm"])]
        support = str(comp["common_support_status"])
        if support != "PASS":
            outcome = "FAIL"
        else:
            ape = float(comp["learned_vs_klt_ape_percent_change"])
            rpe = float(comp["learned_vs_klt_rpe_percent_change"])
            outcome = "WIN" if ape < 0 and rpe < 0 else "LOSS" if ape > 0 and rpe > 0 else "MIXED"
        rows.append({
            "window_id": item["window_id"], "run_slug": item["run_slug"],
            "arm": item["arm"], "action": True, "outcome": outcome,
            "common_support_status": support,
            "ape_percent_change": comp.get("learned_vs_klt_ape_percent_change", ""),
            "rpe_percent_change": comp.get("learned_vs_klt_rpe_percent_change", ""),
            "notes": comp.get("failure_reason", ""),
        })
    write_csv(PAPER / "development_outcomes.csv", rows)
    return rows


def write_config_audit(plan: list[dict[str, str]]) -> None:
    rows: list[dict[str, object]] = []
    for slug in sorted({row["run_slug"] for row in plan}):
        cells = [row for row in plan if row["run_slug"] == slug]
        configs = {row["canonical_config_sha256"] for row in cells}
        cameras = {row["camera_config_sha256"] for row in cells}
        nodes = {row["vins_node_sha256"] for row in cells}
        libs = {row["vins_lib_sha256"] for row in cells}
        rows.append({
            "run_slug": slug, "plan_rows": len(cells),
            "unique_backend_config_hashes": len(configs),
            "unique_camera_config_hashes": len(cameras),
            "unique_vins_node_hashes": len(nodes), "unique_vins_lib_hashes": len(libs),
            "status": "PASS" if all(len(values) == 1 for values in (configs, cameras, nodes, libs)) else "FAIL",
            "canonical_config_sha256": next(iter(configs)),
            "camera_config_sha256": next(iter(cameras)),
            "vins_node_sha256": next(iter(nodes)), "vins_lib_sha256": next(iter(libs)),
        })
    write_csv(PAPER / "backend_config_audit.csv", rows)


def main() -> int:
    runner.verify_lock()
    configure_base()
    plan = read_csv(PLAN)
    if len(plan) != 54:
        raise RuntimeError("v3 backend plan row count drift")
    repeats = base.collect_backend_repeats(plan)
    backend = base.aggregate_backend(repeats)
    runability = build_runability(backend)
    comparisons_spec = base.active_comparisons()
    statuses = base.evaluate_common_support(comparisons_spec, backend)
    accuracy_repeats, accuracy = base.collect_accuracy(statuses)
    comparisons = base.build_comparisons(statuses, accuracy)
    front = read_csv(PAPER / "frontend_audit.csv")
    outcomes = build_outcomes(comparisons, front)
    write_config_audit(plan)

    active = [row for row in outcomes if row["action"] is True]
    counts = Counter(str(row["outcome"]) for row in active)
    no_fail = counts["FAIL"] == 0
    no_over_10 = all(
        float(row["ape_percent_change"]) <= 10.0
        and float(row["rpe_percent_change"]) <= 10.0
        for row in active if row["outcome"] != "FAIL"
    ) and no_fail
    rescue = any(
        row["run_slug"] in {"a09_6000_6800", "afrl_bus_s180_d045"}
        and row["outcome"] == "WIN"
        and float(row["ape_percent_change"]) <= -10.0
        and float(row["rpe_percent_change"]) <= -10.0
        for row in active
    )
    wins_dominate = counts["WIN"] > counts["LOSS"] + counts["MIXED"]
    matched_structural = all(row["status"] == "PASS" for row in read_csv(PAPER / "matched_control_audit.csv"))
    matched_support = all(row["status"] == "PASS" for row in statuses)
    expand = no_fail and no_over_10 and rescue and wins_dominate and matched_structural and matched_support
    decision = {
        "schema_version": "aqua-fe-delayed-newborn-slot-v3-development-decision-v1",
        "experiment_id": "EXP-20260905-008",
        "decided_at": datetime.now(timezone.utc).astimezone().isoformat(),
        "decision": "EXPAND_12_WINDOWS" if expand else "NO_EXPANSION",
        "active_arm_windows": len(active), "zero_action_arm_windows": 12 - len(active),
        "active_outcomes": dict(sorted(counts.items())),
        "full_learned_arm_window_denominator": 12,
        "criteria": {
            "no_active_fail": no_fail,
            "no_active_metric_regression_over_10_percent": no_over_10,
            "a09_or_bus_joint_improvement_at_least_10_percent": rescue,
            "active_wins_exceed_losses_plus_mixed": wins_dominate,
            "matched_structural_audits_pass": matched_structural,
            "all_active_common_supports_pass": matched_support,
        },
        "next_step": (
            "Freeze and enumerate the preregistered 12-window validation set."
            if expand else
            "Do not expand or try a second horizon; report delayed intervention as unsupported on this development set."
        ),
    }
    (PAPER / "backend_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    report = [
        "# Delayed newborn-slot router v3: development result", "",
        "Experiment: `EXP-20260905-008`  ",
        "Scientific role: outcome-known six-window development test; not held-out.", "",
        "## Result", "",
        f"The frozen decision is **{decision['decision']}**. The full denominator is six physical windows, 12 learned arm-windows, and seven action-positive arm-windows. Repeated solver replays are technical repeats, not independent samples.", "",
        "| Window | Arm | Action | Outcome | APE change vs KLT | RPE change vs KLT |", "|---|---|---:|---|---:|---:|",
    ]
    for row in outcomes:
        ape = "—" if row["ape_percent_change"] == "" else f"{float(row['ape_percent_change']):+.2f}%"
        rpe = "—" if row["rpe_percent_change"] == "" else f"{float(row['rpe_percent_change']):+.2f}%"
        report.append(f"| {row['run_slug']} | {row['arm']} | {row['action']} | {row['outcome']} | {ape} | {rpe} |")
    report += [
        "", "## Validity boundary", "",
        "Frames 0--31 are byte-identical to KLT, and actions are restricted to frames 32--36. The method still replaces age-1 GFTT observations; it is not a natural-empty-slot or guaranteed no-harm method. Every action-positive cell is evaluated with a newly built same-ID/frame/dose matched-GFTT control on one all-nine common support. Proxy agreement is not independent ground-truth error.", "",
        "The first nine wrapper attempts had no receipts because the wrapper checked a path different from the frozen YAML `output_path`; they were quarantined and are excluded. The repair changed only output collection, not feature bags, YAML, VINS, metrics, or method behavior.", "",
        "## Decision criteria", "",
    ]
    report += [f"- `{key}`: `{value}`" for key, value in decision["criteria"].items()]
    report += ["", "## Files", "", "See `backend_results_repeats.csv`, `runability.csv`, `accuracy.csv`, `backend_comparisons.csv`, `development_outcomes.csv`, `backend_config_audit.csv`, `backend_decision.json`, and the frozen `preregistration.md`.", ""]
    (PAPER / "report.md").write_text("\n".join(report), encoding="utf-8")
    print(json.dumps({
        "backend_plan_rows": len(plan), "new_replays": 42, "reused_klt_replays": 12,
        "runability_rows": len(runability), "common_supports": len(statuses),
        "common_support_pass": sum(row["status"] == "PASS" for row in statuses),
        "accuracy_rows": len(accuracy), "accuracy_repeat_rows": len(accuracy_repeats),
        "active_outcomes": dict(counts), "decision": decision["decision"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
