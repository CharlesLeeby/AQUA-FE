# ORB-SLAM3 v23 NTNU fjord1 evidence closure R10

Date: 2026-08-06

## Decision

NTNU fjord1 `s30,d30` is a new independent cross-dataset
mechanism/action-positive window. The frozen full role consumes natural
assisted outliers and performs an enforced pre-KF purge. It is
operational low-grid, but native-negative in all four reconstructed and
online APE/RPE comparisons. It is non-strict development evidence, not
trajectory-positive or no-harm evidence.

No selector, bridge, dose, phase, binary, library, runner, or evaluator
threshold was changed.

## Frozen validation

All `20/20` formal runs have status `ok`. Each role has one counter
signature and one reconstructed, online, and keyframe SHA-256 across four
repeats. Repeat 4 swaps `full` and `full_unbounded`. All 20 snapshot
manifests and all `576/576` listed entries pass independent SHA-256
verification.

Classification: `action_positive_metric_negative_native_negative_non_strict`. Evaluation uses a `0.02 s`
association threshold and 20-associated-pose RPE.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 138/138 | 3 / 3 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 138/138 | 3 / 8 | 46 | 4 | 2 / 0 | 227 |
| Frozen v23 | 138/138 | 3 / 7 | 48 | 4 | 2 / 2 | 261 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.120599 / 1.198337` | `0.124421 / 1.200945` |
| Empty drop | `0.120599 / 1.198337` | `0.124421 / 1.200945` |
| Bridge off | `0.474275 / 1.227865` | `0.466971 / 1.235574` |
| Unbounded | `0.348437 / 1.154795` | `0.348267 / 1.160630` |
| Frozen v23 | `0.139763 / 1.216581` | `0.152764 / 1.216834` |

v23 change versus native (positive is better):

- reconstructed APE/RPE: `-15.891% / -1.522%`
- online APE/RPE: `-22.780% / -1.323%`
- improved metrics: native `0/4`; bridge-off `4/4`; unbounded `2/4`

## Legacy source contract

The valid clean rebuild removes 15 old
high-ID learned observations from 8
frames and keeps 50348 native
observations. The earlier source-code-only clean directory is invalid and
is not used by this bundle.

The normalized selector bag contains 300
feature frames, 50486 observations, and
138 learned observations.
It adds 208 `source_code` and
208 `is_learned` channels. Removing
those added channels yields the same 6300-message
canonical SHA-256 `7cd79f97918957be564b426733946f8d719311c6e19143a4772dae1e245b8829` before and after
normalization.

Seed export is 3 IDs, 92 frames,
and 138 observations with
0 ns maximum timestamp error.
No seed is non-finite or out of bounds, and every accepted seed is
post-init in formal instrumentation.

## Texture and denominator

Tracks min/mean/max are `95 / 167.827 / 180`;
grid min/mean/max are `0.277778 / 0.553241 / 0.916667`;
`265/300` frames are at or below `0.80`.

- mechanism/action-positive: `17`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `10/17`
- operational low-grid among project strict: `3/5`
- sparse base-KLT positives: `0/17`

## Claim boundary

- Count NTNU fjord1 `s30,d30` once as development-only action evidence.
- Do not call it trajectory-positive, no-harm, project strict, or all-control strict.
- Do not use the invalid non-legacy-ID clean directory as evidence.
- This is cross-dataset development evidence, not untouched confirmation.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260806/ntnu_fjord1_s30_d30/formal_n3_d14_min8_ignore0_clean_legacyid_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`
