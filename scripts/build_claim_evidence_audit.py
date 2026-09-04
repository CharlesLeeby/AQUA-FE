#!/usr/bin/env python3
"""Generate the task-list claim/evidence audit from current machine artifacts."""

from __future__ import annotations

import csv
import os
from collections import Counter, defaultdict
from pathlib import Path

try:
    from scripts import build_e3_dualmetric_summary as e3
    from scripts import build_p07_preoutcome_governance_v1 as governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import build_e3_dualmetric_summary as e3  # type: ignore
    import build_p07_preoutcome_governance_v1 as governance  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "papers/claim_evidence_audit.md"
DELIVERABLES = (
    "papers/heldout_inventory.csv",
    "papers/heldout_selection_protocol.md",
    "papers/heldout_results.csv",
    "papers/e3_dualmetric_summary.csv",
    "papers/e3_sequence_aggregate.md",
    "papers/modern_baseline_M_results.csv",
    "papers/replay_stability.csv",
    "papers/cqg_classical_control.csv",
    "papers/persistence_churn_diagnostic.csv",
    "papers/normal_noharm.csv",
)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def registry_snapshot() -> dict[str, dict[str, str]]:
    rows = read_csv(
        ROOT / "papers/ieee_sensors_journal_experiments/run_registry.csv"
    )
    chains: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        chains[row["run_id"]].append(row)
    for run_id, chain in chains.items():
        for index, row in enumerate(chain):
            expected_event = f"{run_id}_e{index:02d}"
            expected_parent = "" if index == 0 else chain[index - 1]["registry_event_id"]
            if row["registry_event_id"] != expected_event:
                raise ValueError(f"non-contiguous registry chain: {run_id}")
            if row["supersedes_event_id"] != expected_parent:
                raise ValueError(f"invalid registry supersession: {run_id}")
    return {run_id: chain[-1] for run_id, chain in chains.items()}


def p07_status(
    latest_by_run: dict[str, dict[str, str]],
) -> tuple[Counter[str], Counter[str], int]:
    export_status: Counter[str] = Counter()
    arm_completed: Counter[str] = Counter()
    for allocation in governance.read_csv(governance.ALLOCATION_CSV):
        latest = latest_by_run[allocation["run_id"]]
        export_status[latest["status"]] += 1
        if latest["status"] == "COMPLETED":
            arm_completed[allocation["arm"]] += 1
    d_rows = governance.read_csv(governance.BUNDLE / "arm_applicability.csv")
    d_terminal = sum(row["resolution"] != "PENDING_APPLICABILITY" for row in d_rows)
    return export_status, arm_completed, d_terminal


def ledger_drift_counts(
    latest_by_run: dict[str, dict[str, str]],
) -> tuple[int, int]:
    allocations = {
        row["queue_index"]: row
        for row in governance.read_csv(governance.ALLOCATION_CSV)
    }
    heldout = {
        row["window_id"]: row
        for row in read_csv(ROOT / "papers/heldout_results.csv")
    }
    modern = {
        row["window_id"]: row
        for row in read_csv(ROOT / "papers/modern_baseline_M_results.csv")
        if row["scope"] == "P07_OUTCOME_BLIND_CONFIRMATORY_MATRIX"
    }
    heldout_drift = 0
    modern_drift = 0
    status_field = {
        governance.B1: "b1_frontend_status",
        governance.P_ARM: "p_frontend_status",
        governance.M_ARM: "m_frontend_status",
    }
    for queue_row in governance.read_csv(governance.EXPORT_QUEUE):
        latest = latest_by_run[allocations[queue_row["queue_index"]]["run_id"]]
        window_id = queue_row["window_id"]
        if heldout.get(window_id, {}).get(status_field[queue_row["arm"]]) != latest[
            "status"
        ]:
            heldout_drift += 1
        if (
            queue_row["arm"] == governance.M_ARM
            and modern.get(window_id, {}).get("frontend_status") != latest["status"]
        ):
            modern_drift += 1
    return heldout_drift, modern_drift


def planned_attempt_collisions(
    latest_by_run: dict[str, dict[str, str]],
) -> list[int]:
    allocations = {
        row["queue_index"]: row
        for row in governance.read_csv(governance.ALLOCATION_CSV)
    }
    collisions: list[int] = []
    for queue_row in governance.read_csv(governance.EXPORT_QUEUE):
        latest = latest_by_run[allocations[queue_row["queue_index"]]["run_id"]]
        index = int(queue_row["queue_index"])
        attempt = (
            governance.P07
            / "frontend_attempts"
            / f"queue_{index:03d}_{queue_row['tag']}"
        )
        if latest["status"] == "PLANNED" and attempt.exists():
            collisions.append(index)
    return collisions


def e3_summary() -> dict[str, object]:
    rows = e3.load_g0_rows(e3.grouped_input())
    comparisons = e3.comparisons(rows, fresh_only=True)
    sequences = e3.sequence_aggregate(comparisons, "klt")
    wins = sum(row["sequence_outcome"] == "WIN" for row in sequences)
    losses = sum(row["sequence_outcome"] == "LOSS" for row in sequences)
    ties = sum(row["sequence_outcome"] == "TIE" for row in sequences)
    excluded = sum(str(row["sequence_outcome"]).startswith("EXCLUDED") for row in sequences)
    low, high = e3.bootstrap_ci(sequences)
    return {
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "excluded": excluded,
        "p": e3.exact_sign_test(wins, losses),
        "ci_low": low,
        "ci_high": high,
    }


def main() -> int:
    latest_by_run = registry_snapshot()
    export_status, arm_completed, d_terminal = p07_status(latest_by_run)
    e3_result = e3_summary()
    inventory = read_csv(ROOT / "papers/heldout_inventory.csv")
    eligible_external = sum(row["heldout_class"] == "EXTERNAL_HELD_OUT" for row in inventory)
    replay_groups = read_csv(ROOT / "papers/replay_stability.csv")
    classical = read_csv(ROOT / "papers/cqg_classical_control.csv")
    persistence = read_csv(ROOT / "papers/persistence_churn_diagnostic.csv")
    normal = read_csv(ROOT / "papers/normal_noharm.csv")
    klt_medians = [
        float(row["lifetime_median_frames"])
        for row in persistence
        if row["lineage_class"] == "klt_born"
    ]
    anchor_medians = [
        float(row["lifetime_median_frames"])
        for row in persistence
        if row["lineage_class"] == "learned_born_anchor"
    ]
    historical_fallbacks = sum(
        row["byte_identical_fallback"] == "1"
        and row["texture_role"] == "historical_zero_action_control"
        for row in normal
    )
    known_normal_fallbacks = sum(
        row["byte_identical_fallback"] == "1"
        and row["texture_role"] == "known_normal_zero_action"
        for row in normal
    )
    p07_low_fallbacks = sum(
        row["byte_identical_fallback"] == "1"
        and row["texture_role"] == "confirmatory_low_zero_action_not_normal"
        for row in normal
    )
    active_normal_cases = sum(
        row["texture_role"] == "development_active_normal_profile" for row in normal
    )
    valid_classical = [row for row in classical if row["rpe_valid"] == "true"]
    heldout_drift, modern_drift = ledger_drift_counts(latest_by_run)
    attempt_collisions = planned_attempt_collisions(latest_by_run)
    execution_lock_exists = (
        ROOT
        / "papers/ieee_sensors_journal_experiments/p07/frontend_execution_lock_v3.json"
    ).is_file()
    backend_queue_exists = (
        ROOT / "papers/ieee_sensors_journal_experiments/p07/backend_replay_queue_v1.csv"
    ).is_file()
    # Mere backend queue existence is not G4/G5/G6 completion. CONDITIONAL can
    # only be decided after replay, analysis, and clean reproduction closeout.
    disposition = "REVISE_EXPERIMENTS_INCOMPLETE"

    lines = [
        "# AQUA-FE claim-evidence audit",
        "",
        "Generated from the 2026-08-06 execution-tasklist and current append-only governance artifacts.",
        "",
        "## Current decision",
        "",
        f"**{disposition}**.",
        "",
        (
            f"P07 frontend exports: {export_status['COMPLETED']}/60 completed, "
            f"{export_status['RUNNING']} running, {export_status['PLANNED']} planned, "
            f"{export_status['FAILED']} failed. Arm completion B1/P/M = "
            f"{arm_completed[governance.B1]}/{arm_completed[governance.P_ARM]}/"
            f"{arm_completed[governance.M_ARM]}. D slots terminal: {d_terminal}/20. "
            f"Generalized frontend lock present: {str(execution_lock_exists).lower()}. "
            f"Backend queue present: {str(backend_queue_exists).lower()}."
        ),
        (
            f"Snapshot drift against canonical streams: heldout ledger fields={heldout_drift}, "
            f"modern-M ledger rows={modern_drift}."
        ),
        f"PLANNED allocations with an existing no-clobber attempt directory: {attempt_collisions}.",
        "",
        "## Claim audit",
        "",
        "| Claim | Decision | Evidence | Boundary |",
        "| --- | --- | --- | --- |",
        (
            "| External held-out generalization | **reject for current paper** | "
            f"T1 eligible external domains: {eligible_external}/4 | FLSea not staged; "
            "UVVID/CIRS lack independently auditable GT and are development-exposed; "
            "UMA sample lacks GT. The P06 matrix is exact-history-excluded, not external-held-out. |"
        ),
        (
            "| Historical multi-sequence RPE improvement | **development-only, uncertain** | "
            f"G0 sequence W/L/T/X = {e3_result['wins']}/{e3_result['losses']}/"
            f"{e3_result['ties']}/{e3_result['excluded']}; exact sign p="
            f"{e3_result['p']:.4f}; bootstrap CI "
            f"[{100 * e3_result['ci_low']:.1f}, {100 * e3_result['ci_high']:.1f}]% | "
            "CI includes zero and the July matrix is historically selected; it cannot replace P07. |"
        ),
        (
            "| Learned proposer is generally superior to classical | **reject** | "
            f"{len(valid_classical)} valid event comparisons include learned-positive A06/NTNU "
            "and classical-positive A03 | Retrospective GFTT controls are attribution controls, "
            "not online randomized C-QG. |"
        ),
        (
            "| Modern learned baseline is covered | **integration pass, trajectory pending** | "
            f"P07 M frontend completion {arm_completed[governance.M_ARM]}/20 plus five P05 "
            "fairness probes | No P07 M trajectory or three-replay reducer may be reported yet. |"
        ),
        (
            "| Replay stability | **development partial** | "
            f"{len(replay_groups)} complete three-repeat development window-arm groups | "
            "Technical repeats are not independent; P07 requires every window-arm and a frozen bag hash. |"
        ),
        (
            "| Lineage persistence is cross-domain heterogeneous | **supported diagnostically** | "
            f"Cross-domain KLT medians {klt_medians} frames; anchor medians {anchor_medians} frames | "
            "AQUALOC is a counterexample to a universal anchor advantage; do not claim every "
            "anchor lasts 30-97 frames or always outlives KLT. |"
        ),
        (
            "| Operational normal no-harm | **development supported, confirmatory pending** | "
            f"{known_normal_fallbacks} known-normal exact fallback, {active_normal_cases} "
            f"active-normal development case, and {historical_fallbacks} historical zero-action "
            f"controls; {p07_low_fallbacks} P07 low-texture fallback excluded from the normal count | "
            "Only the explicit normal cases support this row; the ten outcome-blind P06 normal "
            "windows have no backend outcomes yet. |"
        ),
        (
            "| q_i has a backend interface and frontend reliability meaning | **keep narrowly** | "
            "Frozen native-q consumer and NTNU quality-partition audit | Do not claim calibrated "
            "trajectory gain from changing q on a handful of clean sidecar observations. |"
        ),
        "",
        "## Deliverable audit",
        "",
        "| Artifact | Present | Scientific status |",
        "| --- | --- | --- |",
    ]
    partial = {
        "papers/heldout_results.csv",
        "papers/modern_baseline_M_results.csv",
        "papers/replay_stability.csv",
        "papers/normal_noharm.csv",
    }
    for item in DELIVERABLES:
        present = (ROOT / item).is_file()
        status = "PARTIAL/PENDING P07" if item in partial else "GENERATED"
        lines.append(f"| `{item}` | {str(present).lower()} | {status if present else 'MISSING'} |")
    lines.extend(
        [
            "",
            "## Remaining submission gates",
            "",
            "1. Complete and audit all 60 P07 frontend exports in frozen queue order.",
            "2. Resolve all 20 D slots under a frozen exact-lineage contract.",
            "3. Freeze and execute the 240 + 3k serial backend replay queue (k = D-applicable windows), then run G0 and the three-replay reducer.",
            "4. Populate confirmatory M, low-texture effectiveness, normal no-harm, solver-risk, runtime and resource tables.",
            "5. Keep the paper identity at outcome-blind exact-history-excluded multi-sequence VINS-primary; external-held-out remains unavailable.",
            "",
        ]
    )
    temporary = OUTPUT.with_name(f"{OUTPUT.name}.partial.{os.getpid()}")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    os.replace(temporary, OUTPUT)
    print(f"CLAIM_EVIDENCE_AUDIT_COMPLETE disposition={disposition}")
    print(f"output={OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
