# Strict analysis report

## Analysis question

Does churn-guard v3 remove the known `a06_s000_d045` regression while preserving
the two already frozen positive feature inputs under the same backend?

## Evidence hierarchy

1. Whole-bag SHA-256 equality determines which frozen backend experiment is
   applicable to each v3 output.
2. Frontend diagnostics verify the causal routing variable and invariant gates.
3. Fixed-scale proper SE(3) APE/RPE on common support are primary outcomes.
4. Sim(3) scale is diagnostic for scale collapse, not an accuracy replacement.

The v3 mapping is exact: A06 start and H07 map to KLT; A09 and A06 +45 s map to
v1 persistence replacement. Backend binary and normalized-config hashes match
the paired KLT arm in every window/repeat.

## Main findings

- The failed v2 input was bimodal: 2/3 runs had APE about 254.5 m and scale
  0.0154, while one had APE 1.60 m. Runability alone did not reveal this failure.
- V2 deleted three future-persistent A06-start births (10, 8, 23 frames) for a
  three-frame XFeat chain.
- V3 observes only the current population: A06 start closes at 1.43% birth
  reserve, whereas the two positive windows arm at 27.43% and 21.71%.
- Exact-input reuse yields no change on the repaired/anchor windows and retains
  both historical gains: A09 -99.94% APE and A06 +45 s -17.44% APE versus KLT.

## Statistical scope

The analysis is descriptive. There are four known-outcome development windows,
and the three backend replays per input are repeated executions, not independent
experimental units. A paired hypothesis test would be misleading at this n and
with two exact-equality cells. Medians and complete repeat ranges are reported.

## Threats to validity

- Threshold selection used the same known windows; no near-boundary or held-out
  estimate is available.
- COLMAP/proxy is not independent ground truth.
- Exact-input reuse proves the backend outcome for the bag, but does not measure
  future code/hardware scheduling changes.
- A high birth reserve is a population proxy for churn; it does not predict the
  lifetime of an individual newborn.

## Decision

Accept v3 as the current development repair and reject v2. Do not yet label v3
as universally no-harm. Freeze the profile, then evaluate new preregistered
windows with emphasis on reserve ratios around 0.10.
