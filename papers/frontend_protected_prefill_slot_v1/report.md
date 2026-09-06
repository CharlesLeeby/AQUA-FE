# Protected pre-refill slot v1: development result

Experiment: `EXP-20260906-009`  
Date: 2026-09-06  
Scientific role: outcome-known six-window mechanism-development test; not held-out validation.

## Result

The frozen decision is **`NO_EXPANSION`**. Protecting every carried KLT/GFTT
observation is not sufficient for backend no-harm: changing only eight
same-frame newborn GFTT observations still sends A02 to the wrong scale branch.
The method retains the strong A09/XFeat convergence event, but loses the prior
Bus rescue and produces two severe A02 losses. It therefore does not justify a
12-window extension or a superiority claim over KLT or modern learned
frontends.

The full denominator is six physical windows and 12 learned arm-windows. Four
arm-windows have actual action: **1 WIN / 1 TIE / 2 LOSS / 0 FAIL**. Including
the eight byte-identical zero-action mappings gives **1 WIN / 9 TIE / 2 LOSS /
0 FAIL**. Solver repeats are technical repeats, not independent samples.

## What changed

The v2 candidate source, gates, frames 0--4, upstream reservation budget, cap
350, and lack of continuation are unchanged. The sole mechanism change is
final admission: every carried independent-mirror observation is retained;
confirmed candidates use capacity that KLT would otherwise fill with same-frame
age-1 GFTT births. This is an explicit newborn opportunity cost, not free
capacity and not an intrinsically no-harm construction.

Frontend audit: 18/18 cells and 9/9 structural checks PASS. The four active
cells publish 21 observations from 14 lineages while omitting exactly 21 age-1
GFTT observations; carried-observation mismatches are zero. The other 8/12
learned arm-windows are byte-identical to fresh KLT. Four newly generated
same-ID/frame/dose matched-GFTT controls pass all structural checks.

## Fixed-scale result and scale diagnostic

Values are three-repeat medians on one all-nine common support per active cell.
Proper fixed-scale SE(3) APE and strict 1 s RPE are primary; fitted Sim(3) scale
is diagnostic only.

| Window / arm | Added / omitted | KLT APE / RPE (m) | Learned APE / RPE (m) | Matched APE / RPE (m) | Sim(3) scale K / L / C | Outcome |
|---|---:|---:|---:|---:|---:|---|
| A09 / XFeat | 3 / 3 | 1242.140 / 150.847 | 0.733 / 0.0736 | 1.082 / 0.1169 | 0.00147 / 0.753 / 0.673 | WIN |
| A02 / XFeat | 8 / 8 | 0.141 / 0.0227 | 1.094 / 0.1046 | 1.094 / 0.1046 | 0.899 / 0.509 / 0.509 | LOSS |
| A02 / SP+LG | 8 / 8 | 0.141 / 0.0227 | 1.130 / 0.1043 | 1.134 / 0.1048 | 0.899 / 0.501 / 0.500 | LOSS |
| Bus / XFeat | 2 / 2 | 0.0601 / 0.0372 | 0.0601 / 0.0372 | 0.0601 / 0.0372 | 0.956 / 0.956 / 0.956 | TIE |

Repeat ranges and Sim(3) APE/RPE are in `accuracy.csv` and
`accuracy_repeats.csv`. All four common supports PASS with 38--42 common poses,
37--41 s, 93.3%--95.0% common coverage, and 37--41 RPE pairs. Independent evo
cross-check discrepancies are below `5e-7` m.

## Mechanism interpretation

- **A09:** XFeat retains the v2 convergence result despite a different omitted
  newborn set. It also beats the same-dose matched GFTT by 32.31% APE and
  37.10% RPE under fixed scale. This is evidence that the XFeat observation
  content contributes in this one development window. It is not dataset-wide
  superiority.
- **A02:** both learned and matched controls are almost identical (within
  0.5%), and both estimate scale near 0.50 instead of KLT's 0.899. Protecting
  all mature/carried tracks therefore does not remove the startup risk; the
  selection of newborn observations alone can flip scale convergence.
- **Bus:** the two single-frame candidates and their matched replacements are
  backend-inert in this construction: trajectories and all reported metrics
  are exactly equal to KLT. The v2 Bus win is not retained, showing that its
  effect depended on the prior newborn/donor intervention, not on the two
  isolated candidate observations alone.

Compared with v2, candidate IDs, frames, and dose are unchanged. A02/SP+LG's
entire feature bag is byte-identical to v2; A02/XFeat shares seven of eight
omitted newborn observations; A09 and Bus use different omitted-newborn sets.
The compact comparison is in `v2_vs_prefill_mechanism.csv`.

## Runability and frozen decision

All 24 new backend replays and all 18 identity-reused KLT replay rows PASS
receipt, initialization, and coverage checks. All six backend YAML/camera and
VINS binary/library identity audits PASS. One unreceipted Bus matched repeat was
interrupted by the interactive turn, preserved under
`frontend_protected_prefill_slot_v1/quarantine/user_interrupted_20260906T140948+0800/`,
and excluded; its fresh rerun is receipt-bound and included.

Frozen criteria:

- `no_active_fail`: PASS
- `no_active_metric_regression_over_10_percent`: **FAIL**
- `a09_or_bus_joint_improvement_at_least_10_percent`: PASS (A09)
- `active_wins_exceed_losses_plus_mixed`: **FAIL**
- `matched_structural_audits_pass`: PASS
- `all_active_common_supports_pass`: PASS

Per the preregistration, no second slot budget, newborn ordering, or timing
variant is allowed under this experiment. The 12-window extension is not
started.

## Evidence boundary and files

The COLMAP/proxy trajectory measures agreement with a proxy, not independent
ground-truth absolute error. The giant A09 fixed-scale error and the A02
regression are best read as scale-convergence outcomes, not centimetre-level
accuracy claims. Per-feature residual use by the locked backend remains
`Unknown`.

Primary files: `preregistration.md`, `method_lock.json`, `frontend_audit.csv`,
`action_audit.csv`, `matched_control_audit.csv`, `backend_replay_plan.csv`,
`backend_results_repeats.csv`, `runability.csv`, `common_support_status.csv`,
`accuracy.csv`, `backend_comparisons.csv`, `development_outcomes.csv`,
`backend_config_audit.csv`, `backend_decision.json`, and `artifacts.sha256`.
