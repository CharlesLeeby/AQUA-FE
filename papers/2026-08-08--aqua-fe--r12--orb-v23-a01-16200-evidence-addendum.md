# AQUA-FE ORB-SLAM3 v23 AQUALOC A01 evidence addendum R12

Date: 2026-08-08

## Decision

AQUALOC A01 `16200-17100` is a new independent mechanism/action-positive
window under the unchanged frozen protocol. It is not trajectory strict: full
improves two of four reconstructed/online APE/RPE metrics versus native ORB,
and therefore remains development-only action evidence.

| Window | Formal | Frozen action | Determinism | Trajectory level |
| --- | --- | --- | --- | --- |
| AQUALOC A01 `16200-17100` | `20/20` status `ok`; `576/576` formal provenance entries | 153/153 post-init attempts, 150 accepted; 2 MP lineages, 8 MPs, 103 matches, 8 natural outliers, `6/6` purge | one counter/action and reconstructed/online/KF hash per role across four repeats | native `2/4`; bridge-off `1/4`; unbounded `0/4`; metric-mixed non-strict |

R1-R4 all use the frozen `orb_only drop full_bridge_off full_unbounded full`
order. The five roles reproduce their counters, instrumentation CSVs, and
three trajectory hashes in every repeat. All conservation, token, pointer, and
atlas checks pass, with zero event or MapPoint audit overflow.

## Metrics

Evaluation uses a `0.06 s` association threshold and an RPE delta of one
associated pose, matching the prior A01 evaluation contract.

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.007187 / 0.009467` | `0.007355 / 0.010022` |
| Empty drop | `0.007187 / 0.009467` | `0.007355 / 0.010022` |
| Bridge off | `0.006850 / 0.009440` | `0.006939 / 0.009871` |
| Unbounded | `0.006677 / 0.009522` | `0.006766 / 0.009794` |
| Frozen v23 | `0.006984 / 0.009804` | `0.006855 / 0.010145` |

Relative to native, frozen v23 changes reconstructed APE/RPE by
`+2.825% / -3.560%` and online APE/RPE by `+6.798% / -1.227%`, where positive
means lower error. This is action-positive but neither no-harm nor project
strict.

All 40 evaluated trajectories use the same temporal support: 45 of the 46
approximately 1 Hz GT poses are associated, yielding 44 RPE pairs. The maximum
image/GT time difference is `0.050701 s`, leaving `0.009299 s` below the frozen
association threshold. The sparse GT supports the fixed-window comparison but
should not be presented as dense trajectory evidence.

## Fresh source and action contract

The clean rebuild contains 450 feature frames and 157,500 native observations,
with zero historical learned observations. The frozen 9afc sidecar triggers at
frames 157, 169, and 181. The unchanged `n3,d14,min8,ignore0,rearm0` selector
exports 3 IDs, 78 frames, and 153 observations. Seed/image timestamp error is
0 ns; all seed coordinates are finite and within the 968x608 image contract.

The exact whole-lineage audit removes all 153 selected observations from all
three lineages and preserves every native observation and non-feature message
byte-for-byte. Every formal seeded role attempts all 153 observations after
ORB initialization and accepts 150; the three rejects are the expected 19 px
extractor-border rejections.

Bridge-off forms 5 related MPs without assisted matches. Unbounded forms 8
MPs, consumes 104 matches, observes 9 natural outliers, and records `6/0`
observed/purged. Frozen v23 forms 8 MPs, consumes 103 matches, observes 8
natural outliers, and executes the required `6/6` pre-KF purge.

## Updated denominator

- mechanism/action-positive: `19`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/low-grid: `12/19`
- operational degraded/low-grid among project strict: `4/6`
- sparse base-KLT: `0/19`

The validated bundle is:

`papers/orb_v23_a01_16200_r12_20260808/analysis-output`
