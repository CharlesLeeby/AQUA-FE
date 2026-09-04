# AQUA-FE ORB-SLAM3 v23 CIRS s480 evidence addendum R13

Date: 2026-08-08

## Decision

CIRS Cala-Viuda `s480,d30` is the twentieth independent frozen-protocol
mechanism/action-positive window. It is also the first rostered positive whose
current-B1 base KLT is clearly sparse below the 350-feature cap in every frame.

It is not a trajectory-accuracy positive. The only trajectory reference is the
**official CIRS odometry trajectory proxy; non-independent**, so all APE/RPE
values are descriptive proxy alignment and are excluded from project-strict,
all-control-strict, no-harm, held-out-accuracy, and metric-accuracy claims.

| Window | Formal | Frozen action | Determinism | Evidence level |
| --- | --- | --- | --- | --- |
| CIRS Cala-Viuda `s480,d30` | `20/20` status `ok`; `576/576` runner-time provenance entries | 11/11 post-init attempts, 9 accepted; 1 MP lineage, 2 MPs, 5 matches, 1 natural outlier, `1/1` purge | one action/counter, reconstructed/online/KF, and instrumentation-CSV hash per role across four repeats | action-positive; proxy-descriptive non-strict; sparse-base-KLT |

## Frozen action separation

All four repeats use `orb_only drop full_bridge_off full_unbounded full`.
Bridge-off forms one related MapPoint but consumes no assisted match.
Unbounded forms two MapPoints, consumes five assisted matches, observes one
natural assisted outlier, and records `1/0` pre-KF observed/purged. Frozen full
reproduces the same two MapPoints, five matches, and one outlier, then executes
the required `1/1` purge. Every seeded attempt is post-init, all conservation,
token, pointer, and atlas checks pass, and no audit buffer overflows.

## Descriptive odometry-proxy alignment

The predeclared main evaluation uses `max_time_diff=0.06 s` and RPE delta five
associated poses. Supports differ by role: native/drop associate 43 poses,
bridge-off 57, and unbounded/full 62. Each role reuses 15 stair-step proxy
samples, so the supports are neither common nor independent.

| Role | Reconstructed proxy APE / RPE | Online proxy APE / RPE |
| --- | --- | --- |
| Native ORB / empty drop | `0.076711 / 0.209753` | `0.080708 / 0.224813` |
| Bridge off | `0.267733 / 0.258690` | `0.237531 / 0.249860` |
| Unbounded | `0.061647 / 0.381904` | `0.071195 / 0.387560` |
| Frozen v23 | `0.108877 / 0.389324` | `0.102521 / 0.394057` |

Frozen full improves `0/4` descriptive metrics versus native/drop, `2/4`
versus bridge-off, and `0/4` versus unbounded. The predeclared delta-one
associated-pose sensitivity gives the same directional counts, but is not a
one-second metric and is retained only as a stair-step-proxy limitation check.

## Source, texture, and provenance boundary

The fresh current-B1/native-q replay is byte-identical to the discovery base:
149 frames, 33,977 native observations, zero learned/high-ID contamination,
and SHA-256 `8a68544c4aec11b5d8253436cdae62504076e68b9633419e51d220786206db4d`.
The exact whole-lineage audit removes all three selected lineages and all 11
observations while preserving every native observation and non-feature message.

Base tracks are 212--252 (median 227, mean 228.034), with 149/149 frames below
the 350-feature cap. Grid coverage is nevertheless 1.0 in every frame. This is
operational low-base-track/identity-churn and sparse-base evidence, not a
low-grid example. The sidecar child config snapshot retains an inherited-config
caveat; the R13 provenance table closes it by anchoring the complete seven-file
inheritance chain by exact path and SHA-256.

## Updated denominator

- mechanism/action-positive: `20`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/planar/low-grid OR-category: `13/20`
- operational category among project strict: `4/6`
- sparse base-KLT positives: `1/20`

The validated bundle is:

`papers/orb_v23_cirs_s480_r13_20260808/analysis-output`
