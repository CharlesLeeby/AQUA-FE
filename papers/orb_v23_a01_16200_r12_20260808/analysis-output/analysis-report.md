# ORB-SLAM3 v23 AQUALOC A01 16200-17100 evidence closure R12

Date: 2026-08-08

## Decision

AQUALOC A01 `16200-17100` is a new independent mechanism/action-positive
window, but the complete deterministic formal grid is not project strict.
The full-vs-native comparison improves `2/4` metrics;
retain it only in the mechanism/action roster and exclude it from strict
and no-harm denominators.

No selector, bridge, dose, phase, binary, library, runner, camera, or
evaluator threshold was changed after observing the outcome.

## Frozen validation

All `20/20` formal runs have status `ok`. Each role has one counter,
lineage-phase/action, reconstructed, online, and keyframe signature across
four repeats. R1-R4 all use the frozen `orb_only drop full_bridge_off
full_unbounded full` order. All 20 snapshot
manifests and all `576/576` entries pass SHA-256 verification.

Classification: `action_positive_metric_mixed_non_strict`. Evaluation uses a `0.06 s`
association threshold and 1-associated-pose RPE.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 150/153 | 2 / 5 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 150/153 | 2 / 8 | 104 | 9 | 6 / 0 | 287 |
| Frozen v23 | 150/153 | 2 / 8 | 103 | 8 | 6 / 6 | 288 |

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.007187 / 0.009467` | `0.007355 / 0.010022` |
| Empty drop | `0.007187 / 0.009467` | `0.007355 / 0.010022` |
| Bridge off | `0.006850 / 0.009440` | `0.006939 / 0.009871` |
| Unbounded | `0.006677 / 0.009522` | `0.006766 / 0.009794` |
| Frozen v23 | `0.006984 / 0.009804` | `0.006855 / 0.010145` |

Frozen v23 change versus native (positive is better):

- reconstructed APE/RPE: `2.825% / -3.560%`
- online APE/RPE: `6.798% / -1.227%`
- improved metrics: native `2/4`; drop `2/4`; bridge-off `1/4`; unbounded `0/4`

## Discovery smoke and phase gate

The completed three-arm smoke passes `3/3` runs and all `86` snapshot entries.
Its full role attempts all 153 seed observations post-init, accepts 150,
creates 2 MapPoint lineages / 8 distinct MapPoints, consumes 103 assisted
matches, observes 8 natural outliers, and purges 6/6 pre-KF outliers.
The formal grid is independently required to remain pure post-init and
action-positive in every repeat; smoke evidence is not substituted for it.

## Frozen source and exact-drop contract

The clean rebuild contains 450 feature frames and
157500 native observations, with zero historical
learned observations removed from the base. Coordinates, exported images,
and both camera files use the 968x608 AQUALOC archaeology contract.

The frozen sidecar triggers 3 times at frames
[157, 169, 181] and proposes 130
candidates. The selector exports 3 IDs over
78 frames and 153 observations
with 0 ns maximum timestamp error.
No exported seed is non-finite or out of bounds.

The independent exact whole-lineage audit passes byte-for-byte payload,
timestamp, message-topology, non-feature, and learned-lineage removal checks:
153 learned observations from 3 lineages are removed and all 157500 native
observations remain in the drop control.

## Texture and denominator

Tracks min/mean/max are `350 / 350.000 / 350`;
grid min/mean/max are `0.500000 / 0.597654 / 0.750000`;
`450/450` frames are at or below `0.80`.

- mechanism/action-positive: `19`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/low-grid: `12/19`
- operational low-grid among project strict: `4/6`
- sparse base-KLT positives: `0/19`

## Claim boundary

- Count A01 `16200-17100` once as development evidence.
- Do not call it trajectory-positive, no-harm, project strict, or all-control strict.
- It is not an untouched confirmatory window.

Formal root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260808/aqualoc_a01_16200_17100/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`
Smoke root: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260808/aqualoc_a01_16200_17100/smoke_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_threearm_h100_q09`
Exact-drop audit: `/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260808/aqualoc_a01_16200_17100/audit_exact_drop/selector_whole_lineage_audit.json`
