# Persistence churn-guard v3: known-window repair

## Bottom line

The bad replacement path is repaired on the locked development set. Churn-
guard v3 closes to byte-identical KLT on the unstable `a06_s000_d045` startup,
retains byte-identical historical v1 inputs on both positive windows, and stays
byte-identical KLT on h07. Thus it removes the observed regression without
discarding the two observed gains.

This is **known-outcome development evidence (n=4), not held-out proof of a
universal no-harm guarantee**. The 10% boundary has not been tested near its
decision margin. All trajectory errors are agreement with a COLMAP/proxy
trajectory, not independent absolute ground truth.

## What was wrong

The v1 bad window was not merely harmed by too many learned points. Single-chain
v2 proved that even three early swaps could trigger the wrong-scale basin in
2/3 identical-input replays. Those three deleted GFTT births subsequently lived
10, 8 and 23 frames, versus three frames for the XFeat replacement. The
per-track exporter could not know this future persistence at birth.

The observable distinction is population churn. At the first eligible frame,
the bad window had only 5/350 new GFTT tracks (1.43%); a09 had 96/350 (27.43%)
and a06 +45 s had 76/350 (21.71%). In the bad window, scarce births frequently
became mature backbone tracks; in the positive windows, 67--83% of births were
singletons and fewer than 7% lived at least ten frames.

## Repair

Profile: `lineage_early_seed_churn_guard_v3`.

At the first startup frame with an otherwise eligible confirmed XFeat and a
GFTT birth, the exporter measures `GFTT births / cap-limited mirror count`.
It arms the unchanged v1 replacement path iff that ratio is at least 0.10;
otherwise it latches closed through the startup horizon and publishes the
independent KLT mirror. The decision is causal and made from the current frame.
The threshold, horizon, age advantage, 350 budget and all backend settings were
fixed in [preregistration.md](preregistration.md) before v3 output generation.

## Byte-level frontend validation

| window | decision | reserve | XFeat published | exact target | result |
|---|---|---:|---:|---|---|
| a06_s000_d045 | CLOSE_TO_KLT | 5/350 = 1.43% | 0 | KLT | PASS |
| a09_6000_6800 | ARM_V1 | 96/350 = 27.43% | 3 | historical v1 | PASS |
| a06_s045_d045 | ARM_V1 | 76/350 = 21.71% | 12 | historical v1 | PASS |
| h07_s000_d050 | NO_ELIGIBLE_EVENT | n/a | 0 | KLT | PASS |

All four bags have the expected 450/400/450/500 feature messages, identical KLT
timestamps, maximum 350 observations, no learned output after selected frame 4,
and no source=`klt` victim. “Exact” means whole-bag SHA-256 equality, including
IMU/proxy messages and all feature channels.

## Same-backend outcome

Because every v3 bag is byte-identical to a frozen input that already has three
replays, results below are exact-input reuse, not newly selected backend runs.
Primary metrics are median [min--max] under independent fixed-scale proper SE(3)
alignment, common 1 Hz poses and 1 s translation RPE. Sim(3) is diagnostic and
is never substituted silently.

| window | arm | poses | fixed APE RMSE (m) | fixed RPE RMSE (m) | Sim(3) scale |
|---|---|---:|---:|---:|---:|
| a06_s000_d045 | KLT | 40 | 2.643 [2.520--3.025] | 0.339 [0.319--0.351] | 1.856 [1.496--2.230] |
|  | churn-guard v3 | 40 | **2.643 [2.520--3.025]** | **0.339 [0.319--0.351]** | 1.856 [1.496--2.230] |
| a09_6000_6800 | KLT | 38 | 1234.132 [1230.939--1296.254] | 150.056 [149.679--156.965] | 0.00148 [0.00141--0.00149] |
|  | churn-guard v3 | 38 | **0.733 [0.731--0.733]** | **0.0735 [0.0734--0.0736]** | 0.753 [0.753--0.754] |
| a06_s045_d045 | KLT | 42 | 0.258 [0.258--0.258] | 0.0311 [0.0310--0.0311] | 0.825 [0.825--0.825] |
|  | churn-guard v3 | 42 | **0.213 [0.213--0.213]** | **0.0250 [0.0250--0.0250]** | 0.854 [0.854--0.854] |
| h07_s000_d050 | KLT | 48 | 1.230 [1.221--1.323] | 0.220 [0.211--0.257] | 0.740 [0.722--0.741] |
|  | churn-guard v3 | 48 | **1.230 [1.221--1.323]** | **0.220 [0.211--0.257]** | 0.740 [0.722--0.741] |

Relative to KLT, fixed-scale APE/RPE change is 0% on the repaired bad window,
-99.94%/-99.95% on a09, -17.44%/-19.55% on a06 +45 s, and 0% on h07.
All 8 arm-window cells pass the unchanged 3/3 runability gate.

## Interpretation and claim boundary

The supported causal statement is narrow: on these locked windows, scarce GFTT
birth reserve identifies the regime where newborn replacement can delete future
backbone tracks and destabilize scale initialization; failing closed removes
that input perturbation, while high-churn routing retains the two historical
beneficial inputs. The result supports a **churn-conditioned arbitration
mechanism**, not “XFeat always beats KLT” and not a global no-harm theorem.

Before paper-level generalization, the 0.10 rule needs frozen evaluation on new
windows, especially cases near 10%, with the same three-repeat backend contract.
Repeats here quantify backend instability but are not independent datasets, so
no inferential p-values are reported.

## Reproducibility pointers

- [frontend_validation.csv](frontend_validation.csv)
- [churn_guard_decisions.csv](churn_guard_decisions.csv)
- [birth_lifetime_evidence.csv](birth_lifetime_evidence.csv)
- [runability.csv](runability.csv)
- [accuracy.csv](accuracy.csv) and [accuracy_repeats.csv](accuracy_repeats.csv)
- [backend_config_audit.csv](backend_config_audit.csv)
- [decisions.csv](decisions.csv)
- [analysis-output/analysis-report.md](analysis-output/analysis-report.md)
- `artifacts.sha256` (generated last, after all files are frozen)

