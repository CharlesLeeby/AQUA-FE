# ORB-SLAM3 v23 CIRS s480,d30 evidence closure R13

Date: 2026-08-08

## Decision

CIRS Cala-Viuda `s480,d30` is a new independent pure-post-init
mechanism/action-positive cross-dataset window.  It is the first rostered
action-positive whose current-B1 base KLT is clearly sparse below the
350-feature cap in every frame.

The evaluation reference is `official CIRS odometry trajectory proxy; non-independent` from `/cirs/odometry_gt`.
It is not independent ground truth.  All APE/RPE values below are
descriptive proxy alignment only; they do not support metric accuracy,
trajectory-positive, no-harm, project-strict, or all-control-strict claims.

No selector, bridge, dose, phase, binary, library, runner, camera,
reference, association, or RPE-delta threshold was changed after outcome.

## Frozen formal validation

All `20/20` formal runs have status `ok`. R1-R4 use the same frozen
`orb_only drop full_bridge_off full_unbounded full` order. Each role has one complete counter/action,
reconstructed, online, and keyframe signature across four repeats.
All 20 provenance manifests and all `576/576`
listed entries pass SHA-256 verification; all conservation, token,
MapPoint-pointer, atlas, and overflow checks pass.

| Role | Post-init accepted | MP lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 9/11 | 1 / 1 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 9/11 | 1 / 2 | 5 | 1 | 1 / 0 | 63 |
| Frozen v23 | 9/11 | 1 / 2 | 5 | 1 | 1 / 1 | 80 |

The full arm exactly reproduces the discovery-smoke action signature in
all four repeats: 11/11 attempts are post-init, 9 are accepted, one
lineage forms two MapPoints, five assisted matches are consumed, one
natural assisted outlier is observed, and enforced purge removes 1/1.

## Descriptive odometry-proxy alignment

Association is `0.06 s`; RPE delta is
`5` associated poses. Reference independence is `false`.

The role support sets are not common: native/drop have 43 associated
poses, bridge-off has 57, and unbounded/full have 62. evo 1.31.1
matches each shorter-trajectory timestamp to its nearest proxy timestamp
and permits proxy-sample reuse. Every role has 15 reused (also adjacent)
proxy associations. Thus even role-to-role descriptive comparisons mix
different supports and duplicated proxy samples.

| Role | Associated / unique proxy | Reused | |dt| max (s) | delta5 pairs | delta5 physical span min / median / max (s) |
| --- | ---: | ---: | ---: | ---: | --- |
| Native / drop | 43 / 28 | 15 | 0.049901 | 38 | 0.000000 / 0.961507 / 1.071162 |
| Bridge off | 57 / 42 | 15 | 0.049901 | 52 | 0.000000 / 0.964772 / 1.071162 |
| Unbounded / full | 62 / 47 | 15 | 0.049843 | 57 | 0.000000 / 0.953336 / 1.455634 |

| Role | Reconstructed proxy APE / RPE | Online proxy APE / RPE |
| --- | --- | --- |
| Native ORB | `0.076711 / 0.209753` | `0.080708 / 0.224813` |
| Empty drop | `0.076711 / 0.209753` | `0.080708 / 0.224813` |
| Bridge off | `0.267733 / 0.258690` | `0.237531 / 0.249860` |
| Unbounded | `0.061647 / 0.381904` | `0.071195 / 0.387560` |
| Frozen v23 | `0.108877 / 0.389324` | `0.102521 / 0.394057` |

Descriptive full-arm improvement counts are
native `0/4`, drop `0/4`,
bridge-off `2/4`, and unbounded
`0/4`. These counts are not entered into
any strict or metric-accuracy denominator.

The predeclared delta1 associated-pose sensitivity is not a 1-second
metric. Its physical spans are irregular (median about 0.163-0.200 s,
minimum 0 because of proxy reuse), and it uses the same role-dependent
supports. It changes only the RPE delta; APE is identical to delta5.

| Role | Reconstructed delta1 proxy RPE | Online delta1 proxy RPE |
| --- | ---: | ---: |
| Native / drop | 0.061071 | 0.072369 |
| Bridge off | 0.071060 | 0.069333 |
| Unbounded | 0.092469 | 0.094319 |
| Frozen v23 | 0.092826 | 0.094411 |

## Frozen source and exact-drop contract

The freshly rebuilt current-B1 bag is byte-identical to the frozen base
(`8a68544c4aec11b5d8253436cdae62504076e68b9633419e51d220786206db4d`): 149 frames, 33,977 native observations, zero
learned/high-ID contamination, and a passing native-q/B1 guard contract.
The frozen sidecar triggers at frames 8, 20, and 32 for
`low_base_tracks+identity_churn`, producing 150 candidates and 754
sidecar observations. The unchanged selector exports three IDs, 11
observations over nine frames, with zero timestamp error and finite q>=0.9.

The independent exact whole-lineage audit passes byte-for-byte feature
payload, timestamps, message topology, non-feature messages, and lineage
removal. It removes lineage lengths 1/1/9 (11 observations total) while
retaining all 33,977 native observations in the drop control.

The PREP provenance stores a snapshot of the child CIRS config but does
not flatten its inherited parents. This bundle therefore anchors the full
seven-file live inheritance chain by exact path and SHA-256 in
`provenance.csv`; that distinction is retained as a provenance caveat.

## Texture and denominator

Current-B1 tracks min/median/mean/max are `212 / 227 / 228.033557 / 252`;
all `149/149` frames are below the 350-feature cap. Grid coverage is
`1.0` in all 149 frames, so this is explicitly high-grid, not low-grid.
Dropout median/mean/max are `0.448413 / 0.463998 / 0.995690`;
degradation mean/max are `0.192734 / 0.235207`.
The operational category is entered because of low base-track count plus
identity churn, not because of low grid coverage.

- mechanism/action-positive: `20`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/planar/low-grid OR-category: `13/20`
- operational category among project strict: `4/6`
- sparse base-KLT positives: `1/20`

## Claim boundary

- Count CIRS `s480,d30` once as development mechanism/action evidence.
- Count it once as sparse-base-KLT and operational degraded/identity-churn evidence.
- Do not call its high-grid texture low-grid.
- Do not count proxy APE/RPE toward project-strict, all-control-strict,
  no-harm, held-out accuracy, or metric-accuracy evidence.
- The window is not untouched confirmatory evidence.

Formal root: `/home/ma/AQUA-FE_WS/.orbslam3_seeded_cirs_s480_d30_20260808/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`
Smoke root: `/home/ma/AQUA-FE_WS/.orbslam3_seeded_cirs_s480_d30_20260808/smoke_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_threearm_h100_q09`
Exact-drop audit: `/home/ma/AQUA-FE_WS/.orbslam3_seeded_cirs_s480_d30_20260808/audit_exact_drop/selector_whole_lineage_audit.json`
Reference file: `/home/ma/AQUA-FE_WS/.orbslam3_validation_cirs_s480_d30_20260808/dataset/groundtruth_tum.txt`
