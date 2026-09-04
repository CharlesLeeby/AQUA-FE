# ORB-SLAM3 v23 AFRL Cemetery-FR evidence closure R11

Date: 2026-08-07

## Decision

AFRL Cemetery-FR `s230,d30` is a new independent cross-dataset
repeatwise-strict action and trajectory-positive window. Frozen v23
improves reconstructed and online APE/RPE against native ORB, empty
drop, bridge-off, and unbounded controls in all comparisons.

No selector, bridge, dose, phase, binary, library, runner, camera, or
evaluator threshold was changed.

## Frozen validation

All `20/20` formal runs have status `ok`. Each role has one counter
signature and one reconstructed, online, and keyframe SHA-256 across four
repeats. Repeat 4 swaps `full` and `full_unbounded`. All 20 snapshot
manifests and all `576/576` entries pass SHA-256 verification.

Classification: `repeatwise_strict`. Evaluation uses a `0.06 s`
association threshold and 20-associated-pose RPE.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 47/47 | 1 / 8 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 47/47 | 1 / 17 | 20 | 3 | 1 / 0 | 272 |
| Frozen v23 | 47/47 | 1 / 18 | 19 | 3 | 1 / 1 | 272 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.027909 / 0.026643` | `0.028288 / 0.027274` |
| Empty drop | `0.027909 / 0.026643` | `0.028288 / 0.027274` |
| Bridge off | `0.027300 / 0.026296` | `0.027598 / 0.026930` |
| Unbounded | `0.028166 / 0.026486` | `0.028601 / 0.027125` |
| Frozen v23 | `0.026594 / 0.026165` | `0.026894 / 0.026772` |

Frozen v23 change versus native (positive is better):

- reconstructed APE/RPE: `4.712% / 1.794%`
- online APE/RPE: `4.928% / 1.841%`
- improved metrics: native `4/4`; bridge-off `4/4`; unbounded `4/4`

## Fresh source contract

The clean rebuild contains 278 feature frames
and 87839 native observations. It removes
0 observations: there is no
historical learned lineage in the base. All feature coordinates are from
the cam1 front-right 800x600 contract.

The frozen sidecar runs 3 triggers at frames
[16, 28, 45] and proposes 150
candidates. The frozen selector exports 3 IDs,
43 frames, and 47
observations with 0 ns maximum
timestamp error. No exported seed is non-finite or out of bounds.

## Texture and denominator

Tracks min/mean/max are `243 / 315.968 / 350`;
grid min/mean/max are `0.583333 / 0.723921 / 0.833333`;
`254/278` frames are at or below `0.80`.

- mechanism/action-positive: `18`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/low-grid: `11/18`
- operational low-grid among project strict: `4/6`
- sparse base-KLT positives: `0/18`

## Claim boundary

- Count AFRL Cemetery-FR `s230,d30` once as development evidence.
- It is project strict and all-control repeatwise strict under this frozen grid.
- It is cross-dataset development evidence, not untouched confirmation.
- The generic KLT camera filename says cam0, but its parameters and all
  ORB inputs are the cam1 front-right half-resolution calibration.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260807/afrl_cemetery_fr_s230_d30/formal_n3_d14_min8_ignore0_clean_halfres_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`
