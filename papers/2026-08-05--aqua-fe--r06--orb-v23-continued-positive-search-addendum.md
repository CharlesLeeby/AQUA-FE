# ORB-v23 continued positive search addendum

Date: 2026-08-05

## Decision

NTNU fjord1 `s85,d10` is a new independent frozen-v23 mechanism/action-positive
window. It counts once in the deduplicated roster. The formal trajectory result
is metric-mixed, so it does not increase the project-strict or all-control
strict counts.

No ORB source, binary, library, runner, seed row, selector threshold, quality
gate, projection gate, descriptor gate, or dose was changed. The selector was
`n3,d14,min8,ignore0,no-rearm`; the bridge gate remained `q >= 0.9`, projection
`4 px`, and Hamming `100`. Runs used CPU2, synchronized LocalMapping and
LoopClosing, the deterministic background gate, disabled ASLR, audit capacity
131072, and online trajectory export.

## Formal evidence

The complete 20-run index is:

`/mnt/data/AQUA-FE_WS/orbslam3_seeded_validation/postinit_candidate_search_20260804/ntnu_fjord1_s85_d10/formal_n3_d14_min8_ignore0_v23_lineagefirst_lateenforce_dualgateack_equalruntime_singlecpu2_noaslr_fivearm_h100_q09_complete_index`

Repeats 1-3 used `orb_only drop full_bridge_off full_unbounded full`; repeat 4
swapped the last two roles. All roles were byte-deterministic across four
repeats for reconstructed, online, and keyframe trajectories. All 20 runs have
complete instrumentation; all 576/576 provenance snapshot entries match their
SHA-256. Conservation, token, pointer, and atlas checks pass, and both overflow
counters are zero.

An initial formal attempt accidentally used the legacy `orb_slam3_seed_ws`
default binary and stopped at native trajectory validation. That directory was
preserved and excluded. A later one-hour outer-tool timeout left only an
incomplete `orb_only_r3`; it was also preserved and excluded. The complete
index links only the 20 valid lineage-workspace runs, whose binary/library
SHA-256 values are `cebeeedb...83fc` and `05a7b3cc...9af8`.

## Frozen action

Per repeat, `full` records:

- 27/27 accepted observations, all post-init and zero pre-init;
- 3/3 MapPoint lineages, 7 distinct MapPoints;
- 15 consumed assisted matches;
- 2 natural assisted outliers;
- 2 pre-KF outliers observed and 2/2 purged;
- 191 pre-KF scans.

`full_unbounded` records the same 27/27 post-init input, 15 consumed matches and
2 assisted outliers, but zero purges. `full_bridge_off` forms 3 MapPoints but
has zero consumed assisted matches. This establishes the frozen action chain.

## Formal metrics

APE/RPE use Sim(3)-aligned translation, maximum association difference
`0.02 s`, and RPE delta 20 frames. Every value below is identical in all four
repeats.

| Role | Reconstructed APE / RPE | Online APE / RPE | Coverage |
| --- | --- | --- | --- |
| Native ORB | `0.033400 / 0.792825` | `0.036169 / 0.795685` | 98.5% |
| Empty drop | `0.033400 / 0.792825` | `0.036169 / 0.795685` | 98.5% |
| Bridge off | `0.031415 / 0.672026` | `0.046097 / 0.673841` | 96.5% |
| Unbounded | `0.179619 / 0.778771` | `0.182037 / 0.779695` | 98.5% |
| Frozen v23 | `0.082683 / 0.796338` | `0.054591 / 0.796250` | 98.5% |

Relative to unbounded, v23 strongly improves reconstructed and online APE but
slightly worsens both RPE values. Relative to native/drop it worsens all four
metrics. The correct level is mechanism/action-positive and metric-mixed, not
project strict.

## Texture classification

The 100-frame frontend action window has base KLT 350 in every frame. Grid
coverage is min/mean/max `0.666667/0.748611/0.833333`; 92/100 frames are at or
below 0.80. The window is therefore operational low-grid, but not sparse
base-KLT.

## Additional frozen screens

The following independent windows were rebuilt with the same clean
`ignore0,no-rearm` flow and stopped before formal when the preregistered action
chain failed:

| Window | Frozen smoke result | Decision |
| --- | --- | --- |
| AQUALOC H01 `3200-3600` | 90/91 post-init; 4 MPs; 71 matches; `0/0` outlier/purge | action-null |
| NTNU fjord1 `s0,d30` | 6 pre-init + 47 post-init; 3 MPs; 27 matches; `0/0` | mixed-phase |
| NTNU mclab2 `s60,d10` | 7/7 post-init; 1 MP; 0 consumed matches; `0/0` | bridge action absent |
| AQUALOC H04 `800-1200` | 66/69 post-init; 10 MPs; 12 matches; `0/0` | action-null |
| AQUALOC H04 `1600-2000` | 59/62 post-init; 6 MPs; 38 matches; `0/0` | action-null |

NTNU fjord3 `s36,d10` produced 3 selector lineages and 126 observations, but
its official baseline trajectory does not overlap the 36-second raw segment.
It was retained as an action-only asset and not replayed under the formal
trajectory contract. H04 `2000-2360` lacked its raw image bag and was not
rebuilt from historical sidecar output.

## Updated denominator

- mechanism/action-positive: `11`
- project strict: `4`
- all-control repeatwise strict: `2`
- operational degraded/low-grid among all positives: `6/11 = 54.5%`
- operational degraded/low-grid among project strict: `2/4 = 50%`
- sparse base-KLT positives: `0/11`

The search remains mechanism-selected. These fractions describe the frozen
positive roster and do not estimate deployment success probability.
