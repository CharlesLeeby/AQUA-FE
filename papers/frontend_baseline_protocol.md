# Quality-Guided Underwater Frontend: Baseline Protocol

Date: 2026-05-11

## Target Claim

The experiment should support two separate claims:

1. In normal-texture underwater imagery, the proposed frontend should not be
   worse than a strong `KLT + adaptive CLAHE` baseline.
2. In low-texture / low-coverage / near-planar underwater imagery, the proposed
   quality-guided hybrid frontend should outperform `KLT + adaptive CLAHE`.

This means AQUALOC Harbor07 is only a VINS integration / sanity dataset unless
the selected window is explicitly low-texture. It should not be the only proof
for the low-texture claim.

## External Baselines

These are independent methods or standard frontends. They should appear in the
main comparison table as real baselines.

| ID | Method | Role |
|---|---|---|
| B1 | VINS-Fusion original frontend | System-level classical VIO baseline. |
| B2 | `GFTT/Shi-Tomasi + KLT` | Minimal classical tracking baseline. |
| B3 | `GFTT/Shi-Tomasi + KLT + fixed CLAHE` | Strong classical enhancement baseline, if fixed parameters are used. |
| B4 | `ORB` | Classical keypoint baseline for SLAM literature comparison. |
| B5 | `SuperPoint + LightGlue` pairwise | Learned sparse matching baseline. |
| B6 | `XFeat` pairwise | Lightweight learned feature baseline. |
| B7 | `LoFTR` pairwise | Dense/semidense matching baseline; report as matching/fallback, not long-term tracking. |

`KLT + adaptive CLAHE` can be used as a strong reference target in engineering
discussion, but if the adaptive trigger uses our quality logic, it should be
reported as an internal control or ablation rather than as an external baseline.

## Proposed Variants

Only these should be treated as proposed methods in the main paper.

| ID | Method | Intended conclusion |
|---|---|---|
| P1 | `KLT-preserving learned sidecar` | Normal texture: should be no worse than B2/B3. |
| P2 | `Quality-guided three-layer hybrid` | Low texture: should beat B2 by triggering learned recovery or planar semidense refill. |
| P3 | `P2 + backend q_i/sigma_i` | Closed-loop version; include only if it improves or is at least neutral. |

## Ablations

These belong in an ablation table, not the main baseline table.

| ID | Ablation | Question |
|---|---|---|
| A1 | No adaptive CLAHE | Is preprocessing necessary? |
| A2 | Fixed CLAHE vs adaptive CLAHE | Is quality-aware preprocessing useful? |
| A3 | KLT + adaptive CLAHE | Strong internal control; can the full hybrid beat it in low texture? |
| A4 | KLT + adaptive CLAHE + selection | Does backend-safe selection alone explain the gain? |
| A5 | P2 without quality scheduler | Is the scheduler more than simple concatenation? |
| A6 | P2 without learned sidecar | How much comes from classical recovery only? |
| A7 | P2 without LoFTR / semidense planar refill | Is the planar low-texture fallback useful? |
| A8 | Constant backend quality `q_i=1` | Does backend quality weighting help? |
| A9 | Raw q vs calibrated q | Does calibration make q_i safer for VINS? |

## Dataset Split

### Normal / Moderate Texture

Use these to prove "not worse than KLT + adaptive CLAHE".

| Dataset/window | Current status | Use |
|---|---|---|
| AQUALOC Harbor07 `0-1000` | Local ROS bag with IMU + COLMAP GT | Full VINS APE/RPE, long-sequence stability. |
| AQUALOC Harbor07 `1660-1950` | Local ROS bag with IMU + COLMAP GT | Full VINS sanity window; not the main low-texture proof. |

### Low Texture / Low Coverage / Near-Planar

Use these to prove the learned/semidense modules matter.

| Dataset/window | Current status | Use |
|---|---|---|
| AQUALOC Archaeo06 `2210-2260`, `2210-2460` | Local raw tar, frontend logs exist | Planar low-texture frontend proof; convert to VINS only if usable GT is prepared. |
| AFRL-FR `005-055`, `005-410` | Local image samples, frontend logs exist | Low-coverage proof; SP+LG/XFeat sidecar should improve grid coverage. |
| AFRL-FL `080-130`, `080-319` | Local image samples, frontend logs exist | Degraded low-texture proof; use for frontend robustness. |
| AQUALOC Harbor06 `2280-2330`, `2280-2490` | Local raw tar, frontend logs exist | Extra low-texture/front-end validation. |
| Tank textureless wall | Not currently local | Best future end-to-end low-texture/near-wall dataset if downloaded. |

## Acceptance Criteria

### Normal Texture

Against B2 (`KLT + adaptive CLAHE`):

- APE/RPE no worse by more than 5%, or absolute APE difference below 1 cm on
  short windows.
- `init_success` equal to B2.
- `tracking_lost_count_proxy` no larger than B2.
- Frontend dropout and track age no worse in a statistically meaningful way.

### Low Texture

Against B2 (`KLT + adaptive CLAHE`), the proposed P2 should improve at least two
of:

- Higher grid coverage.
- Longer median/mean track age.
- Lower dropout ratio.
- Equal or better epipolar/homography residual.
- Higher inlier ratio.
- Better APE/RPE if an end-to-end VINS/GT bag is available.

Runtime is reported but not the primary criterion because slow underwater robots
can tolerate lower frontend FPS.

## Reporting Rule

Do not claim "cross-dataset end-to-end better than KLT" until at least one more
real underwater IMU-camera dataset with GT is run through VINS. Until then,
write:

> End-to-end VINS stability is verified on AQUALOC Harbor07, while cross-dataset
> low-texture robustness is supported by frontend metrics on AQUALOC Archaeo06
> and AFRL image sequences.
