# P06 reference-support gate supplement v1

Date: 2026-08-05
Parent protocols: `isj-window-selection-v2`, `isj-evaluator-v1`
Status: `FROZEN_BEFORE_FINAL_SCORE_SELECTION`

## Contract interpretation

Window-selection v2 requires 45 s of input/reference support and rejects a
declared reference-support failure. Evaluator v1 defines reference validity on
its frozen grid: exact samples or interpolation with bracket gap no greater
than `2.5 / nominal_reference_rate_hz`. It permits disjoint valid segments and
requires at least 30 reference poses, at least 70% window coverage, and at
least 10 s span for APE-valid support. RPE later uses exact one-second pairs
within those segments.

The first support preflight incorrectly interpreted the requirement as 100%
grid coverage. It is preserved in `reference_window_support_audit.csv` and
`reference_window_support_summary.json` as an over-strict integration probe,
not as the selection decision. The versioned v2 audit applies the frozen G0
reference-only thresholds without changing dataset rates or gap limits.

## Outcome-blind audit

The audit used only registered reference timestamps, first image timestamps,
fixed 45 s window indices, evaluation rates, and gap limits. It did not inspect
KLT scores or strata and did not read learned, proposed-arm, VINS, APE, or RPE
outcomes.

Across the 18 P02 candidate sequences, 148 of 171 gross fixed windows satisfy
the reference-only gate. After union with frozen history exclusion, the
corrected capacity is 17 sequences, four data domains, and 49 sequence-capped
candidate slots. This remains above the 20-window quota requirement.

`cave_gennie` is the only sequence with zero supported windows: all 15 fixed
windows have reference-grid coverage below 0.70 under the frozen AFRL 5 Hz
evaluation and 0.5 s reference-gap limit. Its observed COLMAP reference is
approximately 2.14 Hz with 628 of 1518 consecutive gaps above 0.5 s. Changing
AFRL's frozen evaluator rate/gap after observing this would be post-hoc and is
forbidden.

## Decision

1. Exclude all `cave_gennie` windows from the reference-bearing final selection
   before any score/stratum ranking.
2. Stop the active full-sequence cave screening as
   `STOPPED_REFERENCE_INELIGIBLE`; retain and hash its partial infrastructure
   artifacts, but do not treat it as a scientific screening result or replace
   it based on scores.
3. Continue `bus_outside` and `cemetery`; only their v2 reference-supported
   windows are eligible for percentile calculation and final quota.
4. Apply the same support mask before per-sequence percentiles for all data.
5. Report the original registered denominator (18), the reference-eligible
   screening denominator (17), and the full 23-window support-failure count.

This decision corrects an omitted enforcement of an already frozen eligibility
rule. It does not alter the proposed method, window score, thresholds, history
exclusion, sequence cap, global quota, or statistical estimator.
