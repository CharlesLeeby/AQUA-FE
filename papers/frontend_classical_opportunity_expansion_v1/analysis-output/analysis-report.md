# Classical opportunity expansion — strict descriptive analysis

Status: COMPLETE. Question: does frozen C-all improve fresh complete KLT outside the six development windows under the preregistered fixed-backend contract?

Confirmed fact. Executed denominator: 12 physical windows; 72 technical replay attempts. PRACTICAL_GAIN=3, PRACTICAL_LOSS=2, SMALL_OR_UNCERTAIN=6, FAIL=0, NOT_EVALUABLE=1.
ROBUST_PRACTICAL_GAIN=3; severe regression=2; practical-positive sequences=['A04', 'A07', 'H02'].
Registered decision: **ADDITIVE_OPPORTUNITY_NOT_GENERALIZED**. Expansion status: **EXPANSION_STOPPED_AFTER_BATCH_A**.

The unit is a physical window, not a solver repeat. Fixed start/stride, shared sensor families, proxy reference, broader project exposure and the conditional second stage limit transfer claims. No population natural-positive-rate estimate is made.

| Window | Class / tier | B APE min/median/max (m) | C APE min/median/max (m) | B RPE min/median/max (m) | C RPE min/median/max (m) | APE delta (m) | RPE delta (m) |
|---|---|---|---|---|---|---|---|
| coe1_a01_00000_00900 | PRACTICAL_LOSS / NONE | 0.114753 / 0.155037 / 0.155037 | 0.510393 / 0.554981 / 0.658114 | 0.0159967 / 0.0206574 / 0.0206574 | 0.0645996 / 0.0701269 / 0.0832833 | 0.399944 | 0.0494695 |
| coe1_a03_00000_00900 | PRACTICAL_LOSS / NONE | 0.854467 / 0.858028 / 0.861665 | 2781.32 / 2854.46 / 2867.04 | 0.0786331 / 0.0789517 / 0.0792161 | 270.936 / 277.287 / 278.489 | 2853.61 | 277.208 |
| coe1_a04_00000_00900 | PRACTICAL_GAIN / ROBUST_PRACTICAL_GAIN | 743.154 / 743.154 / 837.552 | 0.113788 / 0.113799 / 0.113804 | 90.4247 / 90.4247 / 102.934 | 0.13763 / 0.137633 / 0.137635 | -743.04 | -90.2871 |
| coe1_a05_00000_00900 | NOT_EVALUABLE / NONE | Not evaluated. / Not evaluated. / Not evaluated. | Not evaluated. / Not evaluated. / Not evaluated. | Not evaluated. / Not evaluated. / Not evaluated. | Not evaluated. / Not evaluated. / Not evaluated. | Not evaluated. | Not evaluated. |
| coe1_a06_00000_00900 | SMALL_OR_UNCERTAIN / DIRECTIONAL_GAIN | 2.05039 / 151.786 / 183.492 | 0.948918 / 0.950726 / 0.970376 | 0.342113 / 19.1366 / 22.9411 | 0.184863 / 0.187006 / 0.187112 | -150.835 | -18.9496 |
| coe1_a07_00000_00900 | PRACTICAL_GAIN / ROBUST_PRACTICAL_GAIN | 3.04255 / 3.04441 / 3.05375 | 0.173395 / 0.173396 / 0.173401 | 0.681968 / 0.682203 / 0.682984 | 0.106702 / 0.106705 / 0.106705 | -2.87102 | -0.575498 |
| coe1_a10_00000_00900 | SMALL_OR_UNCERTAIN / DIRECTIONAL_GAIN | 0.0598424 / 0.0600755 / 0.0604784 | 0.05649 / 0.0566184 / 0.0566204 | 0.0522365 / 0.0522425 / 0.0522506 | 0.0536714 / 0.053691 / 0.0536917 | -0.00345709 | 0.00144848 |
| coe1_h01_00000_00900 | SMALL_OR_UNCERTAIN / NONE | 0.0707647 / 0.0707647 / 0.070898 | 0.0712008 / 0.0715236 / 0.0715518 | 0.00997389 / 0.00997393 / 0.0100755 | 0.00993253 / 0.0101087 / 0.0101448 | 0.000758894 | 0.000134727 |
| coe1_h02_00000_00900 | PRACTICAL_GAIN / ROBUST_PRACTICAL_GAIN | 0.103418 / 0.109392 / 0.110284 | 0.0293568 / 0.0294124 / 0.0294126 | 0.0347265 / 0.0362121 / 0.0363649 | 0.00768505 / 0.00768786 / 0.00768837 | -0.0799794 | -0.0285242 |
| coe1_h03_00000_00900 | SMALL_OR_UNCERTAIN / DIRECTIONAL_GAIN | 848.004 / 848.216 / 848.385 | 0.0714668 / 837.927 / 838.009 | 91.9908 / 92.0195 / 92.0376 | 0.0415473 / 90.966 / 90.9726 | -10.2891 | -1.0535 |
| coe1_h04_00000_00900 | SMALL_OR_UNCERTAIN / NONE | 0.168903 / 0.168906 / 0.168929 | 0.171104 / 0.171106 / 0.171399 | 0.0245472 / 0.0245551 / 0.024588 | 0.0246312 / 0.0246319 / 0.0247846 | 0.00219966 | 7.6803e-05 |
| coe1_h05_00000_00900 | SMALL_OR_UNCERTAIN / NONE | 0.218332 / 0.218333 / 0.218334 | 0.218612 / 0.218613 / 0.218617 | 0.0247828 / 0.0247828 / 0.0247831 | 0.024876 / 0.0248772 / 0.0248777 | 0.000279191 | 9.43979e-05 |

![Per-window complete repeat ranges](figures/figure-01-repeat-ranges.png)

Figure 1 preserves the active denominator and displays min/median/max of three technical repeats per arm. Classification remains the frozen rule, including its repeat-range and RPE conditions; visual direction alone is insufficient. Log axes display different error magnitudes without normalizing away failures. No confidence intervals are implied.

![Case context](figures/figure-02-case-context.png)

Figure 2 places candidate dose and lifetime beside set-level accuracy and initialization differences. Old A02/Bus use their own six-trajectory supports and remain development controls. These descriptors can identify mechanism cases, but do not establish candidate utility or an initialization-mediated causal explanation.

## Claim candidates

- Claim: the registered fixed-C decision within this roster is ADDITIVE_OPPORTUNITY_NOT_GENERALIZED.
  - Source evidence: decision.json, case_registry.csv, backend_results.csv and own-support common_support summaries, pinned in provenance.json.
  - Allowed wording: report exact counts and limits within this prospective comparison outside six development windows.
  - Forbidden stronger wording: population efficacy, independent GT, globally unseen data, C-all as final AQUA-FE innovation.
  - Uncertainty: broader generalization, causal mechanisms and per-feature utility are Unknown.
  - Next check: observation-utility / risk mechanism analysis using retained cases; no automatic C-all tuning.
  - Decision: keep within preregistered scope.

- Claim: retained cases provide set-level examples for mechanism research.
  - Source evidence: positive_cases.csv, neutral_cases.csv, negative_cases.csv, failure_cases.csv and candidate_lifecycle.csv.
  - Allowed wording: whole candidate-set outcome conditional on this cold-start input and fixed evaluation contract.
  - Forbidden stronger wording: each candidate in a positive/negative window is useful/harmful.
  - Uncertainty: candidate-specific causal labels are Not evaluated.
  - Next check: separate mechanism research; preserve all failures and old conclusions.
  - Decision: keep as a case registry, not a feature-label dataset.

## Rendered evidence review — 2026-09-08

Figure 1: A04/A07/H02 meet the registered robust subset; A04 is a baseline-numerical-anomaly rescue, whereas H02 starts from a moderate-error baseline. A06 does not beat the frozen range threshold and H03 must retain its two inaccurate C repeats alongside one accurate repeat. A05 is retained without accuracy because 27 common poses < 30.

Figure 2: high dose includes both A04 gain and A01/A03 losses; positive cases have different first-pose delay directions. Dose, lifetime and delay are descriptive context, not demonstrated causal utility. Old A02/Bus are excluded from new counts. H01/H04/H05 share the same right-panel coordinate and a grouped annotation; no measurement was jittered. A05 appears only in the timing panel.

QA completed by rendering both PNGs: full denominator, log/symlog axes, full min–max ranges, invalid-case label, units and old-control distinction checked. Overlapping draft annotations were repositioned with leader lines; original bundle and layout-revision receipt remain in runtime/reporting_drafts. No numerical input or classification changed.
