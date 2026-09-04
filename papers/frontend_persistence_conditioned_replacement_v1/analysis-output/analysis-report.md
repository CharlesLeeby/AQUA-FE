# Analysis report

## Question

Does the preregistered persistence-conditioned replacement retain historical XFeat startup wins while avoiding the known mature-KLT eviction failures under a frozen VINS-Fusion backend?

## Unit of inference

The scientific unit is a window (`n=4` known-outcome development/regression windows), not a backend replay. Three replays measure initialization sensitivity and report median/range; they are not treated as independent samples.

## Findings

- Runability: KLT and the new line both passed all `12/12` replay gates. All four windows passed the locked common-support gate.
- Direction: `2 WIN`, `1 REGRESSION`, `1 NO_HARM_INPUT` under the preregistered labels.
- Positive preservation: a09 and a06_s045 improved both fixed-scale APE and RPE relative to KLT.
- Safety: h07 was exact-input no-harm; a06_s000 rejected universal no-harm because two of three replays scale-diverged.
- Mechanism: a09 required only the three early XFeat observations, while a06_s000 showed that current-frame GFTT provenance is not a sufficient proxy for future churn.

No population-level significance test is reported: the four windows were selected as known mechanism/regression cases, and n is too small and non-random for a defensible generalization test.

Primary source: [../report.md](../report.md). Machine-readable results: [../accuracy.csv](../accuracy.csv) and [../accuracy_repeats.csv](../accuracy_repeats.csv).
