# AQUA-FE claim-evidence audit

Generated from the 2026-08-06 execution-tasklist and current append-only governance artifacts.

## Current decision

**REVISE_EXPERIMENTS_INCOMPLETE**.

P07 frontend exports: 21/60 completed, 0 running, 39 planned, 0 failed. Arm completion B1/P/M = 7/7/7. D slots terminal: 7/20. Generalized frontend lock present: true. Backend queue present: false.
Snapshot drift against canonical streams: heldout ledger fields=0, modern-M ledger rows=0.
PLANNED allocations with an existing no-clobber attempt directory: [].

## Claim audit

| Claim | Decision | Evidence | Boundary |
| --- | --- | --- | --- |
| External held-out generalization | **reject for current paper** | T1 eligible external domains: 0/4 | FLSea not staged; UVVID/CIRS lack independently auditable GT and are development-exposed; UMA sample lacks GT. The P06 matrix is exact-history-excluded, not external-held-out. |
| Historical multi-sequence RPE improvement | **development-only, uncertain** | G0 sequence W/L/T/X = 7/1/1/2; exact sign p=0.0703; bootstrap CI [0.0, 39.1]% | CI includes zero and the July matrix is historically selected; it cannot replace P07. |
| Learned proposer is generally superior to classical | **reject** | 3 valid event comparisons include learned-positive A06/NTNU and classical-positive A03 | Retrospective GFTT controls are attribution controls, not online randomized C-QG. |
| Modern learned baseline is covered | **integration pass, trajectory pending** | P07 M frontend completion 7/20 plus five P05 fairness probes | No P07 M trajectory or three-replay reducer may be reported yet. |
| Replay stability | **development partial** | 14 complete three-repeat development window-arm groups | Technical repeats are not independent; P07 requires every window-arm and a frozen bag hash. |
| Lineage persistence is cross-domain heterogeneous | **supported diagnostically** | Cross-domain KLT medians [7.0, 1.0, 1.0] frames; anchor medians [6.5, 3.0, 5.0] frames | AQUALOC is a counterexample to a universal anchor advantage; do not claim every anchor lasts 30-97 frames or always outlives KLT. |
| Operational normal no-harm | **development supported, confirmatory pending** | 1 known-normal exact fallback, 1 active-normal development case, and 9 historical zero-action controls; 1 P07 low-texture fallback excluded from the normal count | Only the explicit normal cases support this row; the ten outcome-blind P06 normal windows have no backend outcomes yet. |
| q_i has a backend interface and frontend reliability meaning | **keep narrowly** | Frozen native-q consumer and NTNU quality-partition audit | Do not claim calibrated trajectory gain from changing q on a handful of clean sidecar observations. |

## Deliverable audit

| Artifact | Present | Scientific status |
| --- | --- | --- |
| `papers/heldout_inventory.csv` | true | GENERATED |
| `papers/heldout_selection_protocol.md` | true | GENERATED |
| `papers/heldout_results.csv` | true | PARTIAL/PENDING P07 |
| `papers/e3_dualmetric_summary.csv` | true | GENERATED |
| `papers/e3_sequence_aggregate.md` | true | GENERATED |
| `papers/modern_baseline_M_results.csv` | true | PARTIAL/PENDING P07 |
| `papers/replay_stability.csv` | true | PARTIAL/PENDING P07 |
| `papers/cqg_classical_control.csv` | true | GENERATED |
| `papers/persistence_churn_diagnostic.csv` | true | GENERATED |
| `papers/normal_noharm.csv` | true | PARTIAL/PENDING P07 |

## Remaining submission gates

1. Complete and audit all 60 P07 frontend exports in frozen queue order.
2. Resolve all 20 D slots under a frozen exact-lineage contract.
3. Freeze and execute the 240 + 3k serial backend replay queue (k = D-applicable windows), then run G0 and the three-replay reducer.
4. Populate confirmatory M, low-texture effectiveness, normal no-harm, solver-risk, runtime and resource tables.
5. Keep the paper identity at outcome-blind exact-history-excluded multi-sequence VINS-primary; external-held-out remains unavailable.
