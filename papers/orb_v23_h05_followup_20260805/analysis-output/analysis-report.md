# ORB-SLAM3 v23 H05 clean follow-up

Date: 2026-08-05

## Decision

AQUALOC H05 `900-1240` is a new independent frozen-v23
mechanism/action-positive window. It counts once in the deduplicated roster.
Its trajectory is negative against native/drop in all four primary metrics and
mixed against the unbounded shadow, so it is not project strict or all-control
strict.

The clean selector is `n3,d14,min8,ignore0,no-rearm`. No seed row, selector
threshold, quality gate, projection gate, descriptor gate, dose, ORB source,
binary, library, or runner was changed.

## Frozen contract and determinism

- binary SHA-256: `cebeeedb...83fc`
- library SHA-256: `05a7b3cc...9af8`
- runner SHA-256: `6ffedc00...4c77`
- bridge gate `q >= 0.9`, projection `4 px`, Hamming `100`
- seed phase `all`, minimum consecutive OK frames `0`
- CPU2, LocalMapping and LoopClosing barriers, deterministic background gate,
  ASLR disabled, audit capacity 131072, online trajectory export enabled
- APE/RPE: Sim(3)-aligned translation, association `0.02 s`, RPE delta `20`

All 20 formal runs completed with status `ok`. Per-role action counters and
reconstructed, online, and keyframe trajectory hashes are identical across
four repeats. Repeat 4 swapped `full` and `full_unbounded`.

All 20 provenance manifests pass the role-aware contract. The four seedless
`orb_only` snapshots have 28 entries, the 16 seeded snapshots have 29, and all
`576/576` listed artifacts exist and match their SHA-256. The 28 common paths
are identical across every run and there are only the expected native, drop,
and full-family content groups.

## Formal action

| Role | Post-init accepted | MapPoint lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 87/89 | 3 / 6 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 87/89 | 3 / 10 | 59 | 5 | 3 / 0 | 155 |
| Frozen v23 | 87/89 | 3 / 11 | 59 | 6 | 4 / 4 | 157 |

All 89 attempted observations occur post-initialization. Two are rejected at
the extractor border and 87 are accepted. Conservation, token, pointer, atlas,
and overflow checks all pass.

## Formal metrics

All roles output 162 poses from 170 input frames, for 95.294% coverage.

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.032597 / 0.103104` | `0.032572 / 0.101241` |
| Empty drop | `0.032597 / 0.103104` | `0.032572 / 0.101241` |
| Bridge off | `0.034599 / 0.103852` | `0.033102 / 0.100275` |
| Unbounded | `0.032796 / 0.100179` | `0.037236 / 0.111311` |
| Frozen v23 | `0.032611 / 0.103520` | `0.037962 / 0.113613` |

Relative to native/drop, v23 changes reconstructed APE/RPE by
`+0.043% / +0.403%` and online APE/RPE by `+16.548% / +12.220%`.
All four primary metrics worsen.

Relative to unbounded, reconstructed APE improves by `0.564%`, while
reconstructed RPE and online APE/RPE worsen by
`3.335% / 1.950% / 2.068%`. The correct classification is action-positive,
metric-mixed with a native-negative primary result.

## Texture classification

The 170-frame clean frontend has base KLT min/mean/max
`254 / 347.153 / 350`. Grid coverage min/mean/max is
`0.694444 / 0.848203 / 0.944444`, with only `14/170` frames at or below
`0.80`.

This window is normal/mixed under the current operational roster definition.
It is neither operational low-grid nor sparse base-KLT. The accepted seed
quality minimum is `0.893812239`; one accepted observation is below `0.9`,
while the frozen bridge match gate remains unchanged.

## Updated denominator

- mechanism/action-positive: `12`
- project strict: `4`
- all-control repeatwise strict: `2`
- operational degraded/low-grid among all positives: `6/12 = 50%`
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/12`

## Claim boundary

- Count H05 `900-1240` once as an independent action-positive window.
- Keep the deterministic MapPoint, assisted-match, outlier, and purge action.
- Do not claim trajectory improvement, project-strict status, operational
  low-grid behavior, or sparse base-KLT behavior.
- Keep H07 `720-900` as a clean selector action-null screen and UVVID
  OrientKaj `s160,d20` as a post-init no-MapPoint screen.

The formal root is:

`/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260805/aqualoc_h05_900_1240/formal_n3_d14_min8_ignore0_clean_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09`
