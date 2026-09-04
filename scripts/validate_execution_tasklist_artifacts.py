#!/usr/bin/env python3
"""Validate the execution-tasklist deliverables and their evidence boundaries."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "papers/tasklist_artifact_validation.json"


def rows(path: str) -> list[dict[str, str]]:
    target = ROOT / path
    if not target.is_file() or target.stat().st_size == 0:
        raise ValueError(f"missing or empty artifact: {path}")
    with target.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        data = list(reader)
    if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError(f"invalid CSV header: {path}")
    if any(None in row for row in data):
        raise ValueError(f"ragged CSV: {path}")
    return data


def check(condition: bool, label: str, issues: list[str]) -> None:
    if not condition:
        issues.append(label)


def registry_state(issues: list[str]) -> dict[str, dict[str, str]]:
    registry = rows("papers/ieee_sensors_journal_experiments/run_registry.csv")
    chains: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in registry:
        chains[row["run_id"]].append(row)
    for run_id, chain in chains.items():
        for index, row in enumerate(chain):
            expected_event = f"{run_id}_e{index:02d}"
            expected_parent = "" if index == 0 else chain[index - 1]["registry_event_id"]
            check(
                row["registry_event_id"] == expected_event,
                f"registry_event_chain_noncontiguous:{run_id}",
                issues,
            )
            check(
                row["supersedes_event_id"] == expected_parent,
                f"registry_supersession_invalid:{run_id}",
                issues,
            )
    return {run_id: chain[-1] for run_id, chain in chains.items()}


def execution_lock_hash(payload: dict[str, object]) -> str:
    clone = dict(payload)
    clone.pop("execution_lock_hash", None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    issues: list[str] = []
    inventory = rows("papers/heldout_inventory.csv")
    heldout = rows("papers/heldout_results.csv")
    e3 = rows("papers/e3_dualmetric_summary.csv")
    modern = rows("papers/modern_baseline_M_results.csv")
    replay = rows("papers/replay_stability.csv")
    classical = rows("papers/cqg_classical_control.csv")
    persistence = rows("papers/persistence_churn_diagnostic.csv")
    normal = rows("papers/normal_noharm.csv")
    queue = rows(
        "papers/ieee_sensors_journal_experiments/p07/frontend_export_queue_v1.csv"
    )
    allocations = rows(
        "papers/ieee_sensors_journal_experiments/p07/frontend_run_allocation_v1.csv"
    )
    manifest = rows(
        "papers/ieee_sensors_journal_experiments/dataset_manifest_v4.csv"
    )
    applicability = rows(
        "papers/ieee_sensors_journal_experiments/arm_applicability.csv"
    )
    latest = registry_state(issues)

    check(len(inventory) == 4, "heldout_inventory_not_four_candidates", issues)
    check(
        not any(row["heldout_class"] == "EXTERNAL_HELD_OUT" for row in inventory),
        "external_heldout_invented",
        issues,
    )
    check(len(heldout) == 20, "p07_window_ledger_not_20", issues)
    check(
        not any(row["external_held_out"] == "true" for row in heldout),
        "p07_window_misreported_external",
        issues,
    )
    check(len(e3) == 63, "e3_not_21x3", issues)
    check(len({row["case_id"] for row in e3}) == 21, "e3_case_count_not_21", issues)
    check(
        {row["arm"] for row in e3} == {"full", "drop", "klt"},
        "e3_arm_set_invalid",
        issues,
    )
    check(
        len({row["case_id"] for row in e3 if row["official_fresh_20"] == "1"}) == 20,
        "e3_fresh_denominator_not_20",
        issues,
    )
    check(
        len([row for row in modern if row["scope"] == "P07_OUTCOME_BLIND_CONFIRMATORY_MATRIX"])
        == 20,
        "modern_baseline_p07_rows_not_20",
        issues,
    )
    check(len(replay) >= 1, "replay_stability_empty", issues)
    check(
        all(row["replay_count"] == "3" for row in replay),
        "replay_group_not_three",
        issues,
    )
    check(
        {row["lower_arm"] for row in classical if row["rpe_valid"] == "true"}
        >= {"learned", "gftt"},
        "classical_mixed_direction_missing",
        issues,
    )
    check(
        {row["domain"] for row in persistence} == {"AQUALOC", "NTNU", "CIRS"},
        "persistence_domain_set_invalid",
        issues,
    )
    check(
        {row["lineage_class"] for row in persistence}
        == {"klt_born", "learned_born_anchor"},
        "persistence_lineage_classes_invalid",
        issues,
    )
    check(
        any(row["texture_role"] == "known_normal_zero_action" for row in normal),
        "known_normal_zero_action_missing",
        issues,
    )
    check(
        any(row["texture_role"] == "development_active_normal_profile" for row in normal),
        "active_normal_missing",
        issues,
    )

    # These ledgers are snapshots of append-only state. A schema-only PASS is
    # unsafe if a snapshot lags the canonical registry or applicability stream.
    allocation_by_index = {row["queue_index"]: row for row in allocations}
    check(len(allocation_by_index) == 60, "p07_allocation_index_not_unique", issues)
    heldout_by_window = {row["window_id"]: row for row in heldout}
    modern_p07 = {
        row["window_id"]: row
        for row in modern
        if row["scope"] == "P07_OUTCOME_BLIND_CONFIRMATORY_MATRIX"
    }
    check(len(heldout_by_window) == len(heldout), "heldout_window_id_not_unique", issues)
    check(len(modern_p07) == 20, "modern_p07_window_id_not_unique", issues)
    expected_windows = {row["window_id"] for row in manifest}
    check(set(heldout_by_window) == expected_windows, "heldout_manifest_identity_drift", issues)
    check(set(modern_p07) == expected_windows, "modern_manifest_identity_drift", issues)

    arm_status_by_window: dict[str, dict[str, str]] = defaultdict(dict)
    p_lineage_by_window: dict[str, str] = {}
    export_status: Counter[str] = Counter()
    arm_completed: Counter[str] = Counter()
    for queue_row in queue:
        allocation = allocation_by_index.get(queue_row["queue_index"])
        if allocation is None or allocation["run_id"] not in latest:
            issues.append(f"missing_registry_allocation:{queue_row['queue_index']}")
            continue
        current = latest[allocation["run_id"]]
        arm = queue_row["arm"]
        status = current["status"]
        export_status[status] += 1
        arm_status_by_window[queue_row["window_id"]][arm] = status
        if status == "COMPLETED":
            arm_completed[arm] += 1
        if arm == "P_legacy_nativeq_xfeat_seedchain_v3":
            p_lineage_by_window[queue_row["window_id"]] = current[
                "accepted_lineage_count"
            ]
        attempt = (
            ROOT
            / "papers/ieee_sensors_journal_experiments/p07/frontend_attempts"
            / f"queue_{int(queue_row['queue_index']):03d}_{queue_row['tag']}"
        )
        if status == "PLANNED":
            check(
                not attempt.exists(),
                f"p07_planned_attempt_collision:{queue_row['queue_index']}",
                issues,
            )
        if status == "COMPLETED":
            check(attempt.is_dir(), f"p07_completed_attempt_missing:{queue_row['queue_index']}", issues)
            audit_candidates = [attempt / "audit_v3.json", attempt / "audit_v2.json"]
            audits = [path for path in audit_candidates if path.is_file()]
            check(
                len(audits) == 1,
                f"p07_completed_audit_identity_invalid:{queue_row['queue_index']}",
                issues,
            )
            if len(audits) == 1:
                audit = json.loads(audits[0].read_text(encoding="utf-8"))
                check(
                    audit.get("status") == "PASS",
                    f"p07_completed_audit_not_pass:{queue_row['queue_index']}",
                    issues,
                )
            output_manifest = ROOT / current["output_hash_manifest"]
            check(
                output_manifest.is_file(),
                f"p07_completed_output_manifest_missing:{queue_row['queue_index']}",
                issues,
            )

    field_by_arm = {
        "B1_klt_nativeq_v3": "b1_frontend_status",
        "P_legacy_nativeq_xfeat_seedchain_v3": "p_frontend_status",
        "M_xfeat_pairwise_nativeq_v1": "m_frontend_status",
    }
    terminal_d_count = 0
    manifest_by_window = {row["window_id"]: row for row in manifest}
    for window_id in sorted(expected_windows):
        selected = manifest_by_window[window_id]
        states = arm_status_by_window.get(window_id, {})
        ledger = heldout_by_window.get(window_id)
        if ledger is None:
            continue
        for arm, field in field_by_arm.items():
            check(
                ledger[field] == states.get(arm, ""),
                f"heldout_registry_status_drift:{window_id}:{arm}",
                issues,
            )
        check(
            ledger["p_accepted_lineage_count"] == p_lineage_by_window.get(window_id, ""),
            f"heldout_p_lineage_drift:{window_id}",
            issues,
        )
        d_matches = [
            row
            for row in applicability
            if row["protocol_version"] == "isj-nativeq-v3-confirmatory-protocol-v1"
            and row["method_profile"] == "P_legacy_nativeq_xfeat_seedchain_v3"
            and row["dataset_family"] == selected["dataset_family"]
            and row["sequence"] == selected["sequence"]
            and float(row["window_start"]) == float(selected["window_start_s"])
            and float(row["window_end"]) == float(selected["window_end_s"])
            and row["proposed_arm"] == "P_legacy_nativeq_xfeat_seedchain_v3"
            and row["drop_arm"] == "D_legacy_exact_lineage_drop_v3"
        ]
        pending = [row for row in d_matches if row["resolution"] == "PENDING_APPLICABILITY"]
        terminal = [row for row in d_matches if row["resolution"] != "PENDING_APPLICABILITY"]
        check(len(pending) == 1, f"d_pending_identity_invalid:{window_id}", issues)
        check(len(terminal) <= 1, f"d_terminal_identity_invalid:{window_id}", issues)
        expected_d = terminal[-1]["resolution"] if terminal else "PENDING_APPLICABILITY"
        terminal_d_count += int(bool(terminal))
        check(
            ledger["d_resolution"] == expected_d,
            f"heldout_d_resolution_drift:{window_id}",
            issues,
        )
        expected_terminal = int(
            len(states) == 3
            and all(status == "COMPLETED" for status in states.values())
            and bool(terminal)
        )
        check(
            ledger["frontend_triplet_terminal"] == str(expected_terminal),
            f"heldout_terminal_flag_drift:{window_id}",
            issues,
        )
        expected_ledger_status = (
            "FRONTEND_TERMINAL_TRAJECTORY_SEALED"
            if expected_terminal
            else "P07_FRONTEND_IN_PROGRESS"
        )
        check(
            ledger["status"] == expected_ledger_status,
            f"heldout_scientific_status_drift:{window_id}",
            issues,
        )
        modern_row = modern_p07.get(window_id)
        if modern_row is not None:
            check(
                modern_row["frontend_status"]
                == states.get("M_xfeat_pairwise_nativeq_v1", ""),
                f"modern_registry_status_drift:{window_id}",
                issues,
            )

    execution_lock_path = (
        ROOT
        / "papers/ieee_sensors_journal_experiments/p07/frontend_execution_lock_v3.json"
    )
    check(execution_lock_path.is_file(), "p07_generalized_execution_lock_missing", issues)
    if execution_lock_path.is_file():
        execution_lock = json.loads(execution_lock_path.read_text(encoding="utf-8"))
        check(
            execution_lock.get("schema_version")
            == "isj-p07-frontend-execution-lock-v3",
            "p07_generalized_execution_lock_schema_invalid",
            issues,
        )
        check(
            execution_lock.get("execution_lock_hash")
            == execution_lock_hash(execution_lock),
            "p07_generalized_execution_lock_hash_invalid",
            issues,
        )

    for artifact in (
        "papers/heldout_selection_protocol.md",
        "papers/e3_sequence_aggregate.md",
        "papers/claim_evidence_audit.md",
        "papers/persistence_churn_diagnostic.png",
        "papers/persistence_churn_diagnostic.pdf",
    ):
        check(
            (ROOT / artifact).is_file() and (ROOT / artifact).stat().st_size > 0,
            f"missing_or_empty:{artifact}",
            issues,
        )
    claim_text = (ROOT / "papers/claim_evidence_audit.md").read_text(encoding="utf-8")
    check("REVISE_EXPERIMENTS_INCOMPLETE" in claim_text, "claim_audit_overpromoted", issues)
    check("external-held-out" in claim_text, "claim_audit_external_boundary_missing", issues)
    claim_status = re.search(
        r"P07 frontend exports: (\d+)/60 completed, (\d+) running, "
        r"(\d+) planned, (\d+) failed\. Arm completion B1/P/M = "
        r"(\d+)/(\d+)/(\d+)\. D slots terminal: (\d+)/20\.",
        claim_text,
    )
    check(claim_status is not None, "claim_audit_live_status_missing", issues)
    if claim_status is not None:
        observed = tuple(int(value) for value in claim_status.groups())
        expected = (
            export_status["COMPLETED"],
            export_status["RUNNING"],
            export_status["PLANNED"],
            export_status["FAILED"],
            arm_completed["B1_klt_nativeq_v3"],
            arm_completed["P_legacy_nativeq_xfeat_seedchain_v3"],
            arm_completed["M_xfeat_pairwise_nativeq_v1"],
            terminal_d_count,
        )
        check(observed == expected, "claim_audit_registry_status_drift", issues)

    payload = {
        "schema_version": "aqua-fe-tasklist-artifact-validation-v2",
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "counts": {
            "heldout_candidates": len(inventory),
            "p07_windows": len(heldout),
            "e3_arms": len(e3),
            "modern_baseline_rows": len(modern),
            "three_replay_groups": len(replay),
            "classical_control_rows": len(classical),
            "persistence_rows": len(persistence),
            "normal_noharm_rows": len(normal),
            "p07_frontend_completed": export_status["COMPLETED"],
            "p07_d_terminal": terminal_d_count,
        },
        "scientific_boundary": "DELIVERABLE_SCHEMA_PASS_DOES_NOT_OVERRIDE_P07_PENDING_STATUS",
    }
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, OUTPUT)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
