# ORB-SLAM3 v23 continued positive search R08

Date: 2026-08-06

## Decision

Three independent clean windows passed the complete post-init action chain.
AFRL Cemetery FR `25-45 s` and AQUALOC A08 `0-400` are stable
action-positive no-harm cases but remain native-negative. AQUALOC A02
`5600-6000` is a new project-strict window because v23 improves native/drop
in reconstructed and online APE/RPE. It is not all-control strict because
bridge-off is better in all four metrics and unbounded is better in three.

No selector threshold, seed row, q gate, projection gate, descriptor gate,
dose, ORB binary, library, runner, or phase rule was changed.

## Frozen validation

All 60 formal runs completed with status `ok`. Each role's action counters
and reconstructed, online, and keyframe trajectories are identical across
four repeats. Repeat 4 swaps `full` and `full_unbounded` in every window.
All 60 provenance manifests and all `1728/1728` listed SHA-256 entries pass.

## AFRL_Cemetery_FR_25_45

Classification: `action_positive_metric_mixed_native_negative_noharm`. RPE is 20-associated-pose with
a `0.06 s` association threshold.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 16/17 | 1 / 1 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 16/17 | 2 / 3 | 4 | 2 | 1 / 0 | 189 |
| Frozen v23 | 16/17 | 2 / 4 | 4 | 2 | 1 / 1 | 189 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.010614 / 0.018547` | `0.010146 / 0.018635` |
| Empty drop | `0.010614 / 0.018547` | `0.010146 / 0.018635` |
| Bridge off | `0.010984 / 0.018775` | `0.010486 / 0.018728` |
| Unbounded | `0.011032 / 0.018764` | `0.010533 / 0.018760` |
| Frozen v23 | `0.010811 / 0.018728` | `0.010280 / 0.018766` |

v23 improvement percentages (positive is better):

- versus native: reconstructed APE/RPE `-1.856% / -0.976%`; online `-1.321% / -0.703%`
- versus bridge-off: `3/4` metrics improve
- versus unbounded: `3/4` metrics improve

Texture: operational degraded/low-grid; tracks min/mean/max
`171 / 176.646 / 180`;
grid min/mean/max `0.583333 / 0.669705 / 0.777778`;
`192/192` frames are at or below `0.80`.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260805/afrl_cemetery_fr25_45/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

## A08_0_400

Classification: `action_positive_metric_mixed_native_negative_noharm`. RPE is 1-associated-pose with
a `0.06 s` association threshold.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 156/157 | 1 / 4 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 156/157 | 2 / 4 | 59 | 2 | 1 / 0 | 159 |
| Frozen v23 | 156/157 | 2 / 4 | 59 | 2 | 1 / 1 | 153 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.029018 / 0.045807` | `0.031087 / 0.048405` |
| Empty drop | `0.029018 / 0.045807` | `0.031087 / 0.048405` |
| Bridge off | `0.029125 / 0.046289` | `0.031371 / 0.048702` |
| Unbounded | `0.029188 / 0.046235` | `0.031264 / 0.048744` |
| Frozen v23 | `0.029108 / 0.045962` | `0.031192 / 0.048752` |

v23 improvement percentages (positive is better):

- versus native: reconstructed APE/RPE `-0.310% / -0.338%`; online `-0.338% / -0.717%`
- versus bridge-off: `3/4` metrics improve
- versus unbounded: `3/4` metrics improve

Texture: normal/mixed; tracks min/mean/max
`323 / 336.725 / 350`;
grid min/mean/max `0.722222 / 0.828750 / 0.944444`;
`22/200` frames are at or below `0.80`.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260805/aqualoc_a08_0_400/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

## A02_5600_6000

Classification: `project_strict_bridge_off_and_unbounded_caveat`. RPE is 1-associated-pose with
a `0.06 s` association threshold.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 271/271 | 3 / 10 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 271/271 | 3 / 14 | 176 | 6 | 1 / 0 | 125 |
| Frozen v23 | 271/271 | 3 / 16 | 174 | 6 | 1 / 1 | 129 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.008264 / 0.009367` | `0.014779 / 0.012218` |
| Empty drop | `0.008264 / 0.009367` | `0.014779 / 0.012218` |
| Bridge off | `0.006037 / 0.005894` | `0.008314 / 0.008353` |
| Unbounded | `0.006720 / 0.007739` | `0.010772 / 0.009444` |
| Frozen v23 | `0.006570 / 0.008516` | `0.011935 / 0.009749` |

v23 improvement percentages (positive is better):

- versus native: reconstructed APE/RPE `20.499% / 9.085%`; online `19.244% / 20.208%`
- versus bridge-off: `0/4` metrics improve
- versus unbounded: `1/4` metrics improve

Texture: operational degraded/low-grid; tracks min/mean/max
`322 / 331.270 / 350`;
grid min/mean/max `0.611111 / 0.768750 / 0.888889`;
`133/200` frames are at or below `0.80`.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260806/aqualoc_a02_5600_6000/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`

## Updated denominator

- mechanism/action-positive: `15`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `8/15`
- operational low-grid among project strict: `3/5`
- sparse base-KLT positives: `0/15`

## Claim boundary

- Count each of the three windows once; all are independent and development-only.
- Add A02 `5600-6000` to project-strict evidence with explicit bridge-off and unbounded caveats.
- Count AFRL FR `25-45 s` and A08 `0-400` as mechanism/action-positive no-harm windows, not trajectory-improvement windows.
- Do not call any of the three all-control strict or untouched confirmatory.
- None uses a deliberately sparse base-KLT profile.
