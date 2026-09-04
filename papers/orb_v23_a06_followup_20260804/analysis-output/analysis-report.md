# ORB-SLAM3 v23 A06 raw/final-online follow-up

Date: 2026-08-04

## Decision

AQUALOC A06 `2210-2460` is a new independent frozen-v23
mechanism/action-positive window. It is trajectory metric-mixed, not project
strict.

The strict `n3/d14/min8/ignore0` selector exported 183 observations from three
lineages. All 183 were accepted post-initialization. In every formal v23 run,
the lineages formed 25 distinct MapPoints, consumed 143 assisted matches,
observed 22 assisted outliers, and purged 20/20 pre-keyframe assisted outliers.

All 20 formal runs completed with status `ok`. Per-role counters and both
trajectory hashes were identical across four repeats. Repeat 4 swapped `full`
and `full_unbounded`. No audit overflow or conservation failure occurred.

## Frozen contract

- binary SHA-256: `cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc`
- library SHA-256: `05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8`
- runner SHA-256: `6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77`
- runtime bridge gate `q >= 0.9`, projection gate `4 px`, Hamming gate `100`
- seed phase `all`, minimum consecutive OK frames `0`
- CPU2, LocalMapping and LoopClosing barriers, deterministic background gate,
  ASLR disabled, audit capacity 131072, online trajectory export enabled
- pre-KF purge enabled and enforced only in `full`
- APE/RPE: Sim(3)-aligned translation, max association difference `0.06 s`,
  RPE delta `1` frame

The seed-file audit found a minimum quality of `0.899140537`, with 2/183 rows
slightly below 0.9. The frozen runtime bridge threshold remained 0.9; no
threshold or ORB source was changed.

## Screening results

| Candidate | Phase and reachability | v23 action | Decision |
| --- | --- | --- | --- |
| UVVID OrientKaj `s250,d20` | 12/12 pre-init, no MapPoint, no trajectory | none | exclude |
| AFRL Cemetery FR `s80,d30` | 10/10 post-init, one MapPoint, 3 matches | 1 outlier but `0/0` pre-KF purge | reachability only |
| AFRL Cave `s150,d20` | 29/29 pre-init, no MapPoint, no trajectory | none | exclude |
| AQUALOC A06 `2210-2460` | 183/183 post-init, 3 lineages, 25 MapPoints | 143 matches, 22 outliers, `20/20` purge | promote |

Exact machine-readable rows are in `screening_summary.csv`.

## Formal action

| Role | Post-init accepted | MapPoint lineages / distinct MPs | Assisted matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 183 | 2 / 9 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 183 | 3 / 14 | 138 | 20 | 19 / 0 | 113 |
| Frozen v23 | 183 | 3 / 25 | 143 | 22 | 20 / 20 | 115 |

These counters were identical in all four repeats. Native ORB and empty drop
were byte-identical for reconstructed and online trajectories.

## Formal metrics

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.009800 / 0.013746` | `0.014449 / 0.018187` |
| Empty drop | `0.009800 / 0.013746` | `0.014449 / 0.018187` |
| Bridge off | `0.009507 / 0.013672` | `0.011975 / 0.014648` |
| Unbounded | `0.009654 / 0.014682` | `0.013831 / 0.018390` |
| Frozen v23 | `0.010214 / 0.014281` | `0.011009 / 0.016500` |

Relative to native/drop, v23 worsens reconstructed APE/RPE by
`4.224% / 3.892%`, while improving online APE/RPE by
`23.808% / 9.276%`. Relative to unbounded, v23 worsens reconstructed APE by
`5.801%`, improves reconstructed RPE by `2.731%`, and improves online APE/RPE
by `20.403% / 10.277%`.

Against bridge-off, v23 improves only online APE. The result is therefore
action-positive and metric-mixed. It is not project strict or all-control
strict. The retained A06 segment has only 13 GT messages, so these trajectory
numbers are descriptive and must not carry a stronger standalone accuracy
claim.

## Texture classification

The retained selector statistics and fresh-KLT metrics match frame by frame.

- base KLT tracks: `350/350` in all 125 frames
- selector 6x6 base-grid coverage: min `0.722222`, mean `0.807778`
- low base grid (`<= 0.80`): `51/125 = 40.8%`
- image degradation trigger condition: `125/125`
- low base tracks (`<= 300`): `0/125`

A06 is operational degraded/low-grid, but it is not sparse base-KLT. The
sparse-base positive count therefore remains zero.

## Updated denominator

The deduplicated roster now contains nine mechanism/action-positive windows.

- mechanism/action-positive: `9`
- project strict: `4`
- all-control repeatwise strict: `2`
- operational degraded/low-grid among all positives: `4/9 = 44.4%`
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/9`

The four operational degraded/low-grid positives are A02, A08, H07
`1480-1640`, and A06 `2210-2460`.

## Claim boundary

- Keep: A06 as an independent post-init ORB-v23 action-positive example.
- Keep: deterministic purge action and the strong online-trajectory contrast.
- Do not claim: reconstructed trajectory improvement or project-strict status.
- Do not call A06 sparse KLT; it is saturated-count but degraded/low-grid.
- Do not use this single sparse-GT window as a load-bearing accuracy result.

No ORB source, v23 threshold, binary, library, or runner was changed.
