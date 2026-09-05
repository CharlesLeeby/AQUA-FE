# Delayed newborn-slot router v3: development result

Experiment: `EXP-20260905-008`  
Scientific role: outcome-known six-window development test; not held-out.

## Result

The frozen decision is **NO_EXPANSION**. The full denominator is six physical windows, 12 learned arm-windows, and seven action-positive arm-windows. Repeated solver replays are technical repeats, not independent samples. All 42 new replays and all 12 identity-reused KLT replays initialized and passed the coverage gate; all seven all-nine common supports passed.

| Window | Arm | Action | Outcome | APE change vs KLT | RPE change vs KLT |
|---|---|---:|---|---:|---:|
| a09_6000_6800 | router_xfeat | True | WIN | -0.00% | -0.01% |
| a09_6000_6800 | router_splg | True | WIN | -0.00% | -0.01% |
| a02_0_900 | router_xfeat | True | WIN | -1.11% | -0.34% |
| a02_0_900 | router_splg | True | WIN | -0.45% | -0.13% |
| afrl_bus_s180_d045 | router_xfeat | True | MIXED | +4.84% | -5.55% |
| afrl_bus_s180_d045 | router_splg | True | WIN | -9.35% | -2.54% |
| a08_2700_3600 | router_xfeat | False | TIE | +0.00% | +0.00% |
| a08_2700_3600 | router_splg | False | TIE | +0.00% | +0.00% |
| afrl_cemetery_s135_d045 | router_xfeat | True | WIN | -1.72% | -1.77% |
| afrl_cemetery_s135_d045 | router_splg | False | TIE | +0.00% | +0.00% |
| h07_0_1000 | router_xfeat | False | TIE | +0.00% | +0.00% |
| h07_0_1000 | router_splg | False | TIE | +0.00% | +0.00% |

The six formal `WIN` labels include changes as small as 0.003%; they indicate
direction only and are not six practically meaningful positive windows. The
registered v2 A09 scale rescue disappeared: KLT, delayed XFeat, and delayed
SP+LG all remain in the same divergent regime (fixed-SE(3) APE approximately
1242 m, fitted scale approximately 0.001474). Neither A09 nor Bus retained a
joint APE/RPE improvement of at least 10%, which is the failed expansion gate.

## Primary absolute metrics

Medians across three technical repeats are shown below. Units are metres;
Sim(3) scale is diagnostic and is not used to make the primary decision.

| Window / arm | fixed-SE(3) APE | fixed-SE(3) RPE | Sim(3) scale |
|---|---:|---:|---:|
| A09 / KLT | 1242.140002 | 150.846817 | 0.001474 |
| A09 / delayed XFeat | 1242.106809 | 150.838407 | 0.001474 |
| A09 / delayed SP+LG | 1242.098781 | 150.838783 | 0.001474 |
| A02 / KLT | 0.141317 | 0.022697 | 0.898634 |
| A02 / delayed XFeat | 0.139741 | 0.022620 | 0.899927 |
| A02 / delayed SP+LG | 0.140679 | 0.022667 | 0.899152 |
| Bus / KLT | 0.060109 | 0.037218 | 0.956106 |
| Bus / delayed XFeat | 0.063018 | 0.035154 | 0.949511 |
| Bus / delayed SP+LG | 0.054487 | 0.036274 | 0.967653 |
| Cemetery / KLT | 0.533576 | 0.065177 | 1.252467 |
| Cemetery / delayed XFeat | 0.524416 | 0.064020 | 1.247086 |

The A02 catastrophic v2 regression is eliminated on this development window:
both delayed learned arms are within 1.2% of KLT and improve both primary
metrics. This does not establish general no-harm. Bus XFeat is `MIXED`
(APE +4.84%, RPE -5.55%); Bus SP+LG improves APE by 9.35% and RPE by 2.54%.
The new matched controls show that source necessity remains unresolved: A09
and Cemetery differ from matched GFTT by less than 0.5% on both primary
metrics; Bus SP+LG has the same median as its matched control; A02 learned is
better than its matched control, but this is not a retained A09/Bus rescue.

## Validity boundary

Frames 0--31 are byte-identical to KLT, and actions are restricted to frames 32--36. The method still replaces age-1 GFTT observations; it is not a natural-empty-slot or guaranteed no-harm method. Every action-positive cell is evaluated with a newly built same-ID/frame/dose matched-GFTT control on one all-nine common support. Proxy agreement is not independent ground-truth error.

The first nine wrapper attempts had no receipts because the wrapper checked a path different from the frozen YAML `output_path`; they were quarantined and are excluded. The repair changed only output collection, not feature bags, YAML, VINS, metrics, or method behavior.

## Decision criteria

- `no_active_fail`: `True`
- `no_active_metric_regression_over_10_percent`: `True`
- `a09_or_bus_joint_improvement_at_least_10_percent`: `False`
- `active_wins_exceed_losses_plus_mixed`: `True`
- `matched_structural_audits_pass`: `True`
- `all_active_common_supports_pass`: `True`

## Files

See `backend_results_repeats.csv`, `runability.csv`, `accuracy.csv`, `backend_comparisons.csv`, `development_outcomes.csv`, `backend_config_audit.csv`, `backend_decision.json`, and the frozen `preregistration.md`.
