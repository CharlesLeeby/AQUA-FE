# AQUA-FE ORB-SLAM3 v23 AFRL Cemetery-FR evidence addendum R11

Date: 2026-08-07

## Decision

AFRL Cemetery-FR `s230,d30` is a new independent cross-dataset
mechanism/action-positive and repeatwise-strict window under the unchanged
frozen protocol. Frozen v23 improves all four reconstructed/online APE/RPE
metrics against native ORB, bridge-off, and unbounded controls.

| Window | Formal | Frozen action | Determinism | Trajectory level |
| --- | --- | --- | --- | --- |
| AFRL Cemetery-FR `s230,d30` | `20/20` status `ok`; `576/576` provenance entries | 47/47 post-init; 1 MP lineage, 18 MPs, 19 matches, 3 natural outliers, `1/1` purge | one counter and reconstructed/online/KF hash per role across four repeats | native `4/4`; bridge-off `4/4`; unbounded `4/4`; repeatwise strict |

Repeat 4 swaps `full` and `full_unbounded`. All five roles reproduce their
counter signatures and reconstructed, online, and keyframe hashes across all
four repeats.

## Metrics

Evaluation uses a `0.06 s` association threshold and an RPE delta of 20
associated poses.

| Role | Reconstructed APE / RPE | Online APE / RPE |
| --- | --- | --- |
| Native ORB | `0.027909 / 0.026643` | `0.028288 / 0.027274` |
| Bridge off | `0.027300 / 0.026296` | `0.027598 / 0.026930` |
| Unbounded | `0.028166 / 0.026486` | `0.028601 / 0.027125` |
| Frozen v23 | `0.026594 / 0.026165` | `0.026894 / 0.026772` |

Frozen v23 improves reconstructed APE/RPE by `4.712% / 1.794%` and online
APE/RPE by `4.928% / 1.841%` relative to native ORB.

## Fresh source contract

The clean half-resolution cam1 front-right rebuild contains 278 feature frames
and 87,839 native observations, with zero historical learned or high-ID
observations. The frozen 9afc sidecar triggers three times, and the unchanged
`n3,d14,min8,ignore0,rearm0` selector exports 3 IDs, 43 frames, and 47
observations. Seed/image timestamp error is 0 ns; no seed is non-finite or out
of bounds.

All 47 accepted observations are post-init. Bridge-off creates 8 related MPs
without assisted matches. Unbounded consumes 20 assisted matches and observes
3 natural outliers but does not enforce the purge (`1/0`). Frozen v23 consumes
19 assisted matches, observes the same 3 natural outliers, and executes the
required purge (`1/1`).

## Updated denominator

- mechanism/action-positive: `18`
- project strict: `6`
- all-control repeatwise strict: `3`
- operational degraded/low-grid: `11/18`
- operational degraded/low-grid among project strict: `4/6`
- sparse base-KLT: `0/18`

The validated bundle is:

`papers/orb_v23_afrl_cemetery_fr_r11_20260807/analysis-output`
