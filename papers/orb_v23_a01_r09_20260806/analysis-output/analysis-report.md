# ORB-SLAM3 v23 A01 evidence closure R09

Date: 2026-08-06

## Decision

AQUALOC A01 `6800-7200` is a new independent mechanism/action-positive
window. It is operational low-grid, but it is native-negative in all four
reconstructed and online APE/RPE comparisons. It is neither project strict
nor all-control strict, and it must not be presented as no-harm evidence.

AQUALOC A03 `3200-3600` completed a formal matrix but is a
formal-nondeterministic No-Go. It is recorded below and excluded from the
roster and every positive denominator.

No selector threshold, seed row, q gate, projection gate, descriptor gate,
dose, ORB binary, library, runner, or phase rule was changed.

## Frozen validation

All 20 A01 formal runs completed with status `ok`. Each role has one action
counter signature and one reconstructed, online, and keyframe trajectory
hash across four repeats. Repeat 4 swaps `full` and `full_unbounded`.
All 20 A01 provenance manifests and all `576/576` listed SHA-256 entries
pass. The resulting roster contains 16 unique fixed intervals.

## A01_6800_7200

Classification: `action_positive_metric_negative_native_negative_non_strict`. RPE is 1-associated-pose with
a `0.06 s` association threshold.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 230/232 | 3 / 6 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 230/232 | 3 / 9 | 139 | 5 | 3 / 0 | 156 |
| Frozen v23 | 230/232 | 3 / 4 | 158 | 6 | 2 / 2 | 155 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.010066 / 0.013734` | `0.009706 / 0.011732` |
| Empty drop | `0.010066 / 0.013734` | `0.009706 / 0.011732` |
| Bridge off | `0.008787 / 0.010980` | `0.011200 / 0.013450` |
| Unbounded | `0.007506 / 0.009508` | `0.010939 / 0.013885` |
| Frozen v23 | `0.010865 / 0.014287` | `0.015537 / 0.014772` |

v23 change versus native (positive is better):

- reconstructed APE/RPE: `-7.938% / -4.027%`
- online APE/RPE: `-60.076% / -25.912%`
- improved metrics: `0/4`; bridge-off `0/4`; unbounded `0/4`

Texture: operational degraded/low-grid; tracks min/mean/max
`326 / 337.040 / 350`;
grid min/mean/max `0.638889 / 0.744306 / 0.833333`;
`177/200` frames are at or below `0.80`.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260806/aqualoc_a01_6800_7200/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

## A03_3200_3600 No-Go

A03 is pure post-init and completes the action chain, but the frozen `full`
role splits into two repeat modes while all four controls remain deterministic:

| Repeats | MP lineages / MPs | Matches | Outliers | Purge | Reconstructed APE / RPE | Online APE / RPE |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| r1/r2 | 3 / 22 | 56 | 17 | 9/9 | `0.009282 / 0.012957` | `0.011838 / 0.013305` |
| r3/r4 | 2 / 33 | 57 | 15 | 10/10 | `0.008764 / 0.011985` | `0.010269 / 0.012511` |

The full-role counter, reconstructed, online, keyframe, and metric signature
counts are all `2`; every other role has `1`. r3 already uses the standard
role order and matches swapped-order r4, so the split is not an r4 order
effect. Its 20 manifests and `576/576` entries pass, which isolates the
failure to formal repeat determinism rather than incomplete provenance.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260806/aqualoc_a03_3200_3600/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

## Updated denominator

- mechanism/action-positive: `16`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `9/16`
- operational low-grid among project strict: `3/5`
- sparse base-KLT positives: `0/16`

## Claim boundary

- Count A01 once as development-only action/mechanism evidence.
- Do not claim A01 as trajectory-positive, no-harm, project strict, or all-control strict.
- Keep A03 out of the roster and all positive denominators.
- Neither result is untouched confirmatory evidence.
