# AQUA-FE ORB-SLAM3 v23 NTNU fjord1 evidence addendum R10

Date: 2026-08-06

## Decision

NTNU fjord1 `s30,d30` is a new independent cross-dataset
mechanism/action-positive window under the unchanged frozen protocol. It is
operational degraded/low-grid and native-negative, so it is development-only,
non-strict evidence rather than a trajectory-positive or no-harm result.

| Window | Formal | Frozen action | Determinism | Trajectory level |
| --- | --- | --- | --- | --- |
| NTNU fjord1 `s30,d30` | `20/20` status `ok`; `576/576` provenance entries | 138/138 post-init; 3 lineages, 7 MPs, 48 matches, 4 natural outliers, `2/2` purge | one counter and reconstructed/online/KF hash per role across four repeats | native `0/4`; bridge-off `4/4`; unbounded `2/4`; native-negative, non-strict |

Repeat 4 swaps `full` and `full_unbounded`. All five roles reproduce their
counter signatures and reconstructed, online, and keyframe hashes across all
four repeats.

## Metrics

Evaluation uses a `0.02 s` association threshold and an RPE delta of 20
associated poses.

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.120599 / 1.198337` | `0.124421 / 1.200945` |
| Bridge off | `0.474275 / 1.227865` | `0.466971 / 1.235574` |
| Unbounded | `0.348437 / 1.154795` | `0.348267 / 1.160630` |
| Frozen v23 | `0.139763 / 1.216581` | `0.152764 / 1.216834` |

## Legacy source contract

The valid clean rebuild uses legacy feature IDs in addition to source
channels. It removes 15 historical learned observations from 8 frames and
keeps 50,348 native observations. The earlier source-code-only clean directory
is invalid and is not used by the R10 bundle.

Source normalization adds 208 `source_code` and 208 `is_learned` channels.
After removing those added channels, the original and normalized bags contain
the same 6,300 canonical messages with SHA-256
`7cd79f97918957be564b426733946f8d719311c6e19143a4772dae1e245b8829`.
Seed export contains 3 IDs, 92 frames, and 138 observations with 0 ns maximum
timestamp error.

## Updated denominator

- mechanism/action-positive: `17`
- project strict: `5`
- all-control repeatwise strict: `2`
- operational degraded/low-grid: `10/17`
- operational degraded/low-grid among project strict: `3/5`
- sparse base-KLT: `0/17`

The validated bundle is:

`papers/orb_v23_ntnu_fjord1_r10_20260806/analysis-output`
