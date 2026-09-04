# ORB-SLAM3 v23 A02 phase-aligned follow-up

Date: 2026-08-04

## Decision

AQUALOC A02 `8520-9000` is a new fixed-interval frozen-v23
mechanism/action-positive window. It is a phase-aligned extension of the
excluded mixed-phase `8600-9000` precursor and counts once for this time
cluster. Its trajectory result is metric-mixed, not project strict.

The expanded input adds 40 unseeded 10 Hz native frames before the exact
193-frame `8600-9000` suffix. The 375 seed rows, their timestamps, qualities,
selector, and SHA-256 remain unchanged. All 375 observations were accepted
post-initialization.

## Frozen contract and determinism

- binary SHA-256: `cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc`
- library SHA-256: `05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8`
- runner SHA-256: `6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77`
- bridge gate `q >= 0.9`, projection `4 px`, Hamming `100`
- seed phase `all`, minimum consecutive OK frames `0`
- CPU2, LocalMapping and LoopClosing barriers, deterministic background gate,
  ASLR disabled, audit capacity 131072, online trajectory export enabled
- pre-KF purge enabled and enforced only in `full`
- APE/RPE: Sim(3)-aligned translation, association `0.06 s`, RPE delta `1`

All 20 formal runs completed with status `ok`. Per-role action counters and
both trajectory hashes were identical across four repeats. Repeat 4 swapped
`full` and `full_unbounded`. No overflow or conservation failure occurred.

All 20 provenance manifests passed their role-aware contract: four native
`orb_only` snapshots contain 28 entries because their seed path and seed hash
are empty, while the 16 seeded snapshots contain 29 entries. All `576/576`
listed artifacts exist and match their SHA-256; the 28 common frozen paths are
identical across every run, and the manifests form only the three expected
native, drop, and full-family content groups.

## Formal action

| Role | Post-init | MapPoint lineages / MPs | Matches | Outliers | pre-KF observed / purged | Scans |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Bridge off | 375 | 2 / 8 | 0 | 0 | 0 / 0 | 0 |
| Unbounded | 375 | 2 / 7 | 310 | 23 | 10 / 0 | 132 |
| Frozen v23 | 375 | 2 / 8 | 279 | 22 | 10 / 10 | 124 |

## Formal metrics

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.162413 / 0.184785` | `0.279371 / 0.234389` |
| Empty drop | `0.162413 / 0.184785` | `0.279371 / 0.234389` |
| Bridge off | `0.171900 / 0.184517` | `0.175239 / 0.189370` |
| Unbounded | `0.171565 / 0.183344` | `0.192874 / 0.194156` |
| Frozen v23 | `0.168237 / 0.182726` | `0.180404 / 0.192418` |

Relative to native/drop, v23 changes reconstructed APE/RPE by
`+3.586% / -1.114%`
and online APE/RPE by
`-35.425% / -17.907%`.
Relative to unbounded, all four v23 metrics improve:
`-1.940% / -0.337%`
reconstructed and
`-6.465% / -0.895%`
online.

Reconstructed APE still worsens relative to native, so the classification is
action-positive and metric-mixed. It is not project strict or all-control
strict.

## Texture classification

The 193-frame action region has base KLT `350/350` in every frame, grid
coverage min/mean `0.638889/0.709557`, and
`189/193` frames at grid `<= 0.80`. Even treating all 40 unseeded prefix
frames as non-low, the full-window lower bound is `189/233 = 81.1%`.

The window is operational degraded/low-grid, but not sparse base-KLT in the
action region.

## Updated denominator

- mechanism/action-positive: `10`
- project strict: `4`
- all-control repeatwise strict: `2`
- operational degraded/low-grid among all positives: `5/10 = 50%`
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/10`

## Claim boundary

- Count `8520-9000` once; do not also count the overlapping excluded
  `8600-9000` precursor.
- Keep the deterministic purge action and online improvement.
- Do not claim reconstructed APE improvement, project-strict status, or sparse
  base-KLT behavior.
- Treat the 40-frame prefix as phase alignment for the fixed interval, not as
  a selector, threshold, seed, or v23 change.

No ORB source, v23 threshold, binary, library, runner, seed row, or selector
parameter was changed.
