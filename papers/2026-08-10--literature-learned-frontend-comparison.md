# Local learned-frontend interface diagnostics on A02:0005, with frozen normal-window screening

Date: 2026-08-10; frozen follow-up updated 2026-08-11  
Status: completed local interface diagnostics and ablations; **not an external published-system comparison**. No parameter tuning or repeat-until-success.

> Scope correction (2026-08-11): the arms in this report are project-built, literature-motivated integrations. They do not reproduce an author-released SLAM/VIO system and must not occupy the paper's published-method baseline rows. Direct SP-LG, temporal-MAGSAC, SuperPoint-birth+KLT, and XFeat-birth+KLT remain useful causal diagnostics or controlled ablations only. The external comparison track is now restricted to formally published systems with an official implementation, starting with SuperVINS 1.0; see [published learned-SLAM baseline selection](2026-08-11--published-learned-slam-baseline-selection.md).

## Diagnostic summary

The failed legacy XFeat arm was first replaced with two learned frontends whose treatment of learned features is materially closer to published visual-inertial systems:

1. **Direct SP-LG persistent (paper-style Hamesse comparator):** SuperPoint detection/description, adjacent-frame LightGlue matching, and propagated feature IDs sent directly to the fixed VINS-Fusion external-feature backend.
2. **Local Direct SP-LG + DL-VINS-Factory-style temporal MAGSAC:** the same local direct SuperPoint-LightGlue frontend, with normalized-plane Essential-matrix `USAC_MAGSAC` filtering before ID propagation, using the temporal-geometry parameters and fail-open policy of DL-VINS-Factory. This is not a full DL-VINS-Factory reproduction.
3. **AQUA-FE SuperPoint-birth + raw-frame KLT carrier:** detector-only SuperPoint supplies new points, while the frozen B1 KLT/FB/NCC carrier exclusively owns persistent IDs. This is a project-specific, component-aligned learned-keypoint-plus-LK comparator, not a pure SP+LK or code-exact DL-VINS-Factory reproduction.
4. **AQUA-FE XFeat-birth + frozen raw-frame KLT carrier v1:** XFeat supplies score-ranked births and the same frozen carrier exclusively owns persistent IDs. This arm was preregistered before any real XFeat model load or image inference and is DL-VINS-Factory component-aligned, not an official reproduction or an XFeat-paper temporal baseline.

Both direct-replacement arms passed their export contracts and initialized VINS on the prespecified full A02:0005 window, but both diverged catastrophically. The learned-assisted KLT carrier then passed a separately preregistered physical-track gate and produced a common-support-valid finite endpoint: APE/RPE `0.7235/0.0735 m`, versus `0.3700/0.0367 m` for B1-constq on the same mask. It is therefore usable as an internal diagnostic/ablation arm, although about two times worse than the classical control on this one window; it is not a published-method baseline.

No all-window expansion was started. The unchanged carrier and frozen gates were next applied to the prespecified H07 mechanism case and the prespecified 45 s normal-texture A07:0001 window; only camera-model dispatch was added for H07. Both stopped at the frontend gate, before VINS. The A02 result therefore remains a one-window usability result, not a cross-window or general performance claim.

The subsequent XFeat-birth arm also passed its A02 prefix and full audits, initialized in its single allowed replay, and produced a valid strict-G0 endpoint. On that arm's common mask, XFeat-birth achieved APE/RPE `0.1673/0.0302 m`, compared with `0.3740/0.0380 m` for B1-constq. This is a prespecified single-window result, not evidence of general superiority: the unchanged XFeat method then failed five frozen physical gates on the A07 prefix, triggering the registered stop before A07 full export, VINS, or G0.

## Literature boundary

### Direct SP-LG comparator

The method is based on Hamesse et al., *Practical Deep Feature-Based Visual-Inertial Odometry* (ICPRAM 2024), DOI [10.5220/0012320200003654](https://doi.org/10.5220/0012320200003654). The paper describes cached SuperPoint features, adjacent-frame LightGlue matching, and ID propagation/new-ID creation with confidence or top-M filtering.

The authors' [LightGlue-VINS-Mono repository](https://github.com/charleshamesse/LightGlue-VINS-Mono) is currently empty. Therefore the local arm is reported as **paper-style**, not as a code-exact reproduction. The paper uses confidence gates `0.9/0.95` or top-M values `300/400/500` (with a broader 200–1000 sweep); the local arm instead uses LightGlue filter `0.1`, top 350, NCC `>=0.35`, association radius `0.25`, and `continuity_first_v2` ID propagation.

### DL-VINS-Factory-style temporal MAGSAC comparator

The second comparator follows Lim, Chong, and Ling, *DL-VINS-Factory* ([arXiv:2607.01757](https://arxiv.org/abs/2607.01757)) and the [official repository](https://github.com/limshoonkit/DL-VINS-Factory-ROS2), fixed at commit `436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6`. The relevant tracker is unchanged relative to the paper-release commit `d563365423625e5607f09615543bf08adb69219f`.

Only its temporal MAGSAC stage is reproduced here. The official system uses FP16 TensorRT SuperPoint-LightGlue, cap 256, and matcher threshold 0.2; the local producer uses the cvg/PyTorch LightGlue implementation, 2,048 keypoints, filter 0.1, `continuity_first_v2`, and post-association cap 350. The official frozen configuration is [mono_superpoint_lightglue.yaml, lines 25–39](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/blob/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6/DL-VINS/src/dl_vins/config/euroc/mono_superpoint_lightglue.yaml#L25-L39).

The frozen frontend contract is:

- adjacent-frame SuperPoint-LightGlue matches;
- normalization to the camera plane;
- Essential matrix via `cv::USAC_MAGSAC`;
- threshold `1 / focal_length`, probability `0.999`, maximum 200 iterations;
- fewer than 8 matches, invalid mask, or inlier ratio below 0.5: keep all matches;
- otherwise retain only the MAGSAC inliers;
- no NCC and no `recoverPose` in this arm.

Primary code: [feature_tracker.cpp, lines 2037–2114](https://github.com/limshoonkit/DL-VINS-Factory-ROS2/blob/436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6/DL-VINS/src/dl_vins/src/feature/feature_tracker.cpp#L2037-L2114).

One difference is disclosed: the official code does not catch an exception thrown by `findEssentialMat`; the local helper treats that exceptional path as fail-open. No exception occurred in the 450-frame final run, so this difference did not affect the measured endpoint.

## Fixed experiment

- Dataset/window: AQUALOC archaeology A02:0005, full 45 s window.
- Sampling: every second image, frame offset 1; 450 feature frames.
- Backend: the same VINS-Fusion-origin binary and configuration for all replay arms.
- Backend parameters: `max_cnt=150`, single-threaded, solver time 0.04 s, 8 iterations, fixed calibration and `td=-0.053694112369382575`.
- Learned arms and fairness control: constant backend `quality=1`, `sigma=1`.
- Feature export: exactly 350 observations per frame.
- Evaluation: one replay per valid final bag; one 1 Hz common-support G0 evaluation with identical interpolation and validity gates.

The B1-constq control is byte-identical to the native B1 feature stream in record/header stamps, coordinates, IDs, velocities, geometry channels, and source labels. Only `quality` and `sigma` are changed to 1. This isolates learned-feature behavior from the constant-q interface used by all learned comparison arms. A single B1-vs-B1-constq replay difference is not interpreted causally because VINS replay is not deterministic.

### Learned-assisted carrier boundary

The usable comparison arm follows the learned-keypoint-plus-LK carrier family represented by SupSLAM and DL-VINS-Factory, but deliberately reuses the frozen AQUA-FE B1 carrier to preserve a single integration difference. SuperPoint provides only score-ordered births; it never propagates or revives an ID. Every raw frame executes KLT, while only raw frames `1,3,...,899` are published.

Frozen carrier parameters are B1's cap `350`, birth spacing `18 px`, border `8 px`, LK `21x21`/level `3`/`30` iterations/`0.01`, FB `<=1 px`, and NCC `>=0.65` with radius `5`. SuperPoint uses the frozen cvg weights, 2,048 candidates, resize 1,024, and original detector scores. Adaptive CLAHE is unchanged from B1. These differ from DL-VINS-Factory's cap 256/min-distance 15/FB 0.5 configuration, so the arm is not reported as an exact reproduction.

Before VINS, both the 100-frame prefix and the full 450-frame bag had to pass independently implemented gates for schedule and IMU/GT identity, normalized coordinates and velocity, birth rate, episode lifetime, lag-10 common IDs, spatial thinning, grid occupancy, pixel second difference, and adjacent-frame Essential inliers. No threshold was changed after seeing either result.

### XFeat-birth carrier boundary

DL-VINS-Factory's official repository at commit `436e7aa0e3195cbea955eb6a1ff5cf0c1b715ed6` contains distinct `mono_xfeat_lk.yaml` and `mono_xfeat_lightglue.yaml` configurations. Its paper and implementation therefore provide a genuine learned-keypoint-plus-LK precedent for treating XFeat as a proposal source rather than forcing pairwise matcher occurrences to act as long-lived VINS landmarks.

The local arm is deliberately narrower and is reported as **component-aligned**, not code-exact. It uses the pinned VerLab PyTorch XFeat checkout at commit `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`, calls `detectAndCompute(..., top_k=2048)`, consumes keypoints and scores, and discards the computed descriptors. It does not call a descriptor matcher, XFeat-star, LighterGlue, or a learned-ID propagation path. Births then enter the same frozen AQUA-FE raw-frame KLT/FB/NCC carrier used for the SuperPoint-birth comparison.

The XFeat arm was frozen before any real model load or image inference in [its preregistration](2026-08-11--xfeat-lk-comparison-preregistration.md), SHA-256 `ad571ca867ff29d144f9bf98ac8d8e8d9bb2e1ba1c5cfab33f7345df606662a5`. Its method values are XFeat threshold `0.05`, NMS kernel `5`, proposal budget `2048`, the same adaptive-CLAHE preprocessing and carrier cap/spacing/LK/FB/NCC settings, and fixed `quality=sigma=1`, `source_code=20`, `is_learned=1`. The one permitted A02 raw-index-0 loading/inference smoke passed without a matcher call; its canonical receipt has SHA-256 `4dad9d9e7c3b94dc240c24027f26d4cbaa8626e33369630639e9d2061260416d`. No method value or audit threshold changed afterward.

## Export contract

| Arm | Final feature bag SHA-256 | Frames x points | Persistence/geometry result |
|---|---|---:|---|
| B1 native | `7b9cbc6b4fcfa2640a12f0f42aa99d4610b1ab43fed39027f06a6fa2928ec9f9` | 450 x 350 | classical persistent control |
| B1-constq | `683e9dcf9f2ef470d2e68fd746b84b5d509bbb10650c62206417c258597fcf38` | 450 x 350 | exact non-q field match to B1 |
| Direct SP-LG | `57b3148173f2eee38345111018a48539e0228b160caabc7dd50883ad20b1dd36` | 450 x 350 | checker PASS; long4 min/median/max 250/289.5/320 |
| Local SP-LG + DL-VINS-style MAGSAC | `d20e84b9b466a1e08cb856bed03cb03f51ecbb026ced32d348c4962ec847f177` | 450 x 350 | checker PASS; long4 min/median/max 152/242/281 |
| SP-birth + raw-frame KLT carrier | `e77662cd3f253201f8aa1eed92c8d6a3b2242fd2fb2611ece14eafc28488019a` | 450 x 350 | independent full audit PASS; birth median 2.29%, lifetime median 14, lag-10 median 291 |
| XFeat-birth + frozen raw-frame KLT carrier | `9116184984a0043fd84e44f1adb733c4dbdf6456fc43b55c8ac7f9bf81d4802f` | 450 x 350 | method-specific full audit PASS; birth median 1.71%, lifetime median 25, lag-10 median 295 |

All six final bags contain 450 feature messages, 9,091 IMU messages, and 46 GT messages. Feature header and record stamps match the B1 control exactly, frame by frame.

For the final MAGSAC run, all 450 frames executed `filter_inliers` with reason `magsac_inlier_mask_applied`. Median candidates/inliers/inlier ratio were `1397 / 1245.5 / 0.877138`; the inlier-ratio range was `0.779730–0.928865`. Its lag-10 persistence gate passed with count/parallax/pose pairs `440/203/183` out of 440 evaluated pairs.

For the final learned-assisted carrier, all preregistered full-window gates passed: birth-rate median/p90 `2.29%/4.29%`, episode lifetime median `14` frames, short-episode fraction `24.61%`, lag-10 common-ID median/p10 `291/264`, deterministic 20 px thinning median/p10 `302/291`, occupied 8x6 cells median/p10 `42/39`, pixel second-difference median `0.2219 px`, and Essential@0.3 inlier median/p10 `94.96%/90.71%`. The full audit also verified all 9,091 IMU and 46 GT messages by ordered serialized-payload hash.

The XFeat-birth prefix and full artifacts independently passed the same frozen method-specific contract. For the 450-frame full bag, birth-rate median/p90 were `1.71%/3.43%`, episode lifetime median was `25` frames, short-episode fraction was `17.03%`, lag-10 common-ID median/p10 were `295/263`, deterministic 20 px thinning median/p10 were `290/263`, occupied 8x6 cells median/p10 were `37/34`, pixel second-difference median was `0.2133 px`, and Essential@0.3 inlier median/p10 were `97.08%/94.20%`. The contract additionally verified exactly 350 observations per frame and exact ordered identity of all 9,137 non-feature messages.

## VINS and common-support results

| Arm | Init | VIO rows | Linear-solver failures | G0 APE RMSE (m) | G0 RPE RMSE (m) |
|---|---:|---:|---:|---:|---:|
| B1-constq | 1 | 438 | 0 | **0.377598** | **0.037630** |
| Direct SP-LG | 1 | 433 | 10 | 2077.008126 | 212.272799 |
| Local SP-LG + DL-VINS-style MAGSAC | 1 | 436 | 14 | 1959.523105 | 208.490709 |

Both canonical comparisons use the same support: grid 45, matched 43, common coverage `0.955556`, common span 42 s, one segment, 42 RPE pairs, with both APE and RPE validity true. Thus the large errors are not caused by an empty trajectory, insufficient support, or an invalid mask.

Canonical evidence:

- [B1-constq vs Direct SP-LG](litcmp_a02_0005_common_support/b1_constq_vs_splg_direct_r1/common_support_summary.json), SHA-256 `916e8b0f88be291613c58e830449c0cb3caeb510da0c09651dea944802dfc568`.
- [B1-constq vs local SP-LG + DL-VINS-style MAGSAC](litcmp_a02_0005_common_support/b1_constq_vs_dlvins_splg_magsac_r1/common_support_summary.json), SHA-256 `c5428905a2a4d4e59f217777e04aae3d10093777f8bac6a6d5d86508041f4a03`.
- [B1 native vs B1-constq](litcmp_a02_0005_common_support/b1_vs_b1_constq_r2/common_support_summary.json), SHA-256 `78870a81bc612a12fcddddb41b8764a26325648787b4c0b393f2aa1a22e92651`.

### Usable learned-assisted comparison

| Arm | Init | VIO rows | Solver warnings | G0 APE RMSE (m) | G0 RPE RMSE (m) |
|---|---:|---:|---:|---:|---:|
| B1-constq | 1 | 438 | 0 | **0.369983** | **0.036717** |
| SP-birth + raw-frame KLT carrier | 1 | 411 | 17 pre-init / 0 post-init | 0.723511 | 0.073542 |

This comparison uses grid 45, matched 41, common coverage `0.911111`, common span 40 s, one segment, and 40 RPE pairs; both APE and RPE are valid. The new arm is worse than B1 but is no longer an invalid or divergent endpoint. Its 17 dense-Cholesky warnings all occur before `Initialization finish!`; it has no restart, tracking-lost, or insufficient-feature event afterward.

Canonical evidence: [B1-constq vs SP-birth + raw-frame KLT carrier](litcmp_a02_0005_common_support/b1_constq_vs_spbirth_rawlkcarrier_v1_r1/common_support_summary.json), SHA-256 `e2a134732f31297f532230c1fef18a3ac783733dd35c3b0b2fa925299d9d6105`.

### Preregistered XFeat-birth comparison

| Arm | Init | VIO rows | Solver warnings | G0 APE RMSE (m) | G0 RPE RMSE (m) |
|---|---:|---:|---:|---:|---:|
| B1-constq | 1 | 438 | 0 | 0.374031 | 0.037971 |
| XFeat-birth + frozen raw-frame KLT carrier | 1 | 422 | 9 pre-init / 0 post-init | **0.167255** | **0.030191** |

This separately preregistered comparison uses grid 45, matched 42, common coverage `0.933333`, common span 41 s, one segment, and 41 RPE pairs; both APE and RPE are valid. Relative to B1-constq on this exact mask, the XFeat-birth arm's APE and RPE RMSE are lower by about `55.3%` and `20.5%`. This is not uniform dominance: its maximum RPE is `0.151561 m`, versus `0.071924 m` for B1-constq. All 422 trajectory rows are finite and strictly time ordered. The nine dense-Cholesky warnings occur before the sole `Initialization finish!` marker; no solver warning, restart, tracking-lost event, or failure-detection event occurs after initialization.

This is evidence of a usable and favorable endpoint on one development-exposed A02 window, not a cross-window superiority claim; one replay per arm also provides no variance estimate or significance test. Canonical evidence: [B1-constq vs XFeat-birth + frozen raw-frame KLT carrier](litcmp_a02_0005_common_support/b1_constq_vs_xfeatbirth_rawlkcarrier_v1_r1/common_support_summary.json), SHA-256 `8d7ecce0f9a8c213eeec161c528990882e4934ddeb7add61ac84a22dcb20d36a`. The corresponding `common_support_metrics.csv`, `common_grid_audit.csv`, and `evo_crosscheck.json` have SHA-256 `42b329136074699f6e3914943716310f3cc3ef73c36dd1a2952bc6c8f20fe9dd`, `6fafca197d72892fc1e69845dce734f5f75a48fc17f39dcd9fc27534d528c24e`, and `1758f1ad72301a57fe584cf35a4105bb0e279860302c7d5958a37fef126afe3a`.

## Frozen follow-up screens

The SuperPoint-birth A02 result was followed by two screens using that revision's frozen carrier and gate definitions. Neither result was used to alter a threshold or rerun a scientific arm. The later XFeat revision used a separate preregistration and reached only its mandated A07 prefix before STOP.

### H07:1660–1720 export-only negative screen

H07 is the historical normal-texture mechanism case, but its exact window contains only 61 raw images and 30 every-second-image publications, spanning about 3 s. It cannot satisfy the frozen common-support requirement of at least 10 s and is therefore not a formal VINS/G0 comparison window.

The completed export is retained as a negative transport and frontend screen. Kannala-Brandt camera handling itself passed: 713 non-feature messages were byte-exact, maximum normalized-coordinate error was `6.55e-8`, and maximum velocity error was `4.56e-8`. The May22 reference has 11 channels whereas the current contract has 13, producing 30 expected `CHANNEL_SCHEMA_CHANGED` violations. That infrastructure mismatch does not explain the physical failure: birth-rate median/p90 were `21.01%/34.09%`, episode lifetime median was `1` frame, the fraction of episodes no longer than two frames was `72.70%`, lag-10 common IDs median/p10 were `98.5/74`, 20 px thinning counts were `186.5/167.6`, pixel second difference was `0.5236 px`, and Essential@0.3 inlier median/p10 were `86.73%/81.28%`. Only grid occupancy passed.

Thus H07 is **STOP**: it is not rerun with a newer reference schema and is not sent to VINS. The producer manifest's `formal_eligible=true` denotes only that a complete, non-prefix bag was produced; it does not override the independent audit failure.

- H07 feature bag SHA-256: `b5d28e83ca9305206268fcb04a2e8707c2e978f1b86e4e134dca19cbad818d11`.
- H07 manifest SHA-256: `9c1d63047e3b49c44d8532b1c39edb5645da1aee917ae1a55b1a8d9309d4da99`.
- H07 audit SHA-256: `8c76f87285904072432f80c74f7c0463b0ef8f2deaef91efaa90337db7b9f023`.

### A07:0001 prespecified 10 s normal-texture stop screen

A07:0001 was labeled `normal / STRICT_NORMAL` in the frozen P07 assignment before this comparator was created. It is nevertheless a development-exposed sequence with previously observed B1 outcomes, so this is a prespecified current-method compatibility validation, not fresh held-out evidence.

The 45 s source window contains 901 images, 8,968 IMU messages, and 46 GT messages. The 450-frame B1 schedule matches raw indices `1,3,...,899` exactly. To keep the backend-visible quality interface fair, the existing B1 bag was deterministically materialized to `quality=1` and `sigma=1` for all 157,500 source-1/source-2 observations. The independent q-only audit verified that every point, ID, coordinate, velocity, non-quality channel, timestamp, channel order, and all 9,014 non-feature payloads remained exact. The VINS backend reads `quality`; it does not consume `sigma`, `source_code`, or `is_learned`.

The same frozen carrier then produced the preregistered 100-frame prefix: 35,000 observations, exactly 350 per frame, with the full schedule/channel/normalized-coordinate/velocity and 2,048 prefix non-feature records passing. Six frozen physical gates failed:

| Gate | Observed | Frozen requirement |
|---|---:|---:|
| birth rate, median | `6.57%` | `<=5%` |
| episode lifetime, median | `3` frames | `>=10` |
| episode fraction `<=2` frames | `47.23%` | `<=45%` |
| lag-10 common IDs, median | `237.5` | `>=250` |
| lag-10 common IDs, p10 | `213.9` | `>=220` |
| Essential@0.3 inlier ratio, median | `89.35%` | `>90%` |

The remaining frozen gates passed: birth-rate p90 `10.0%`, Essential p10 `85.32%`, 20 px thinning median/p10 `308/286`, occupied-grid median/p10 `47/45.9`, and second difference `0.2473 px`. Because the result is a valid physical-gate failure rather than an infrastructure error, A07 is **STOP**: no full export, no B1/comparator replay, and no G0 evaluation were run.

- A07 B1-constq bag SHA-256: `2d2a0573497f710ce090c2b040b6bee3d1b858848d0a95bda0057bbdfaac40c4`.
- A07 B1-constq audit SHA-256: `d55e502398a6b9e4fef01eea18921b517eb8b51733fb26b7ebddda5d4f99fc42`.
- A07 prefix bag SHA-256: `a07373152f1c418ec65812354f62f4151654e2e963d45a657c0ab88aba64f5ec`.
- A07 prefix manifest SHA-256: `9d351c8d4c70e6d8cd6e034f3ea45f1401efcb6323f70103b59f86f3d113b510`.
- A07 prefix audit SHA-256: `a944772ebb355d27b96e57745ebfeb5d3319014bb3d5863aad06a0fe59f2aadf`.

### XFeat-birth A07:0001 preregistered stop screen

The XFeat-birth revision had a separate, fully closed execution order: A07 could be reached only after valid A02 prefix, full, replay, and G0 results, and any A07 prefix failure mandated STOP. Its one 100-frame prefix preserved the full structural contract: exactly 350 observations per frame, exact schedule and non-feature prefix, fixed XFeat method identity/source code, and valid normalized coordinates and velocities.

Five physical gates nevertheless failed:

| Gate | Observed | Frozen requirement |
|---|---:|---:|
| birth rate, median | `6.00%` | `<=5%` |
| episode lifetime, median | `4` frames | `>=10` |
| lag-10 common IDs, median | `241` | `>=250` |
| lag-10 common IDs, p10 | `204.9` | `>=220` |
| Essential@0.3 inlier ratio, p10 | `84.881%` | `>85%` |

The remaining gates passed: birth-rate p90 `9.77%`, episodes no longer than two frames `43.00%`, Essential median `91.30%`, 20 px thinning median/p10 `275/262`, occupied-grid median/p10 `42/39`, and second difference `0.2347 px`. This is a valid preregistered negative screen, not an infrastructure failure. Consequently, no XFeat A07 full export, B1-constq replay, XFeat replay, or A07 G0 directory was created.

- XFeat A07 prefix bag SHA-256: `50556fa75437c45b7c4e19ba080291ea8128bb119c7bcf957c60dde0fb6a47cb`.
- XFeat A07 prefix manifest SHA-256: `d9bcd4519e0d187dd1dba1447bf8d349ae120e76213cfb4bf944c05d74cff424`.
- XFeat A07 prefix audit SHA-256: `d88ef07f5388fa07c06877d253624e28a1530e26daefb71dd39e6fafcfecb9b8`.

## Interpretation

The learned arms solve the original comparator's syntactic persistence problem well enough to initialize: they produce dense, long-lived IDs and nonempty trajectories. That does not establish that a propagated numeric ID denotes the same physical landmark through time.

The direct arm has no multi-view geometric validation. The MAGSAC arm performs strong two-view filtering and reports high per-frame inlier ratios, but a sequence of locally valid two-view correspondences can still form an incorrect long-term landmark chain. MAGSAC slightly lowers the endpoint errors relative to Direct SP-LG, but the result remains unusable and has more linear-solver failures. It is not a scientific recovery.

This experiment does not show that SuperPoint, LightGlue, or the cited papers are generally ineffective. It shows that, under this fixed underwater A02 window, calibration, sampling, and VINS backend, direct learned-match replacement remains incompatible with the backend's persistent-landmark assumption even after literature-style two-view MAGSAC filtering.

The learned-assisted carrier isolates what changed that conclusion. SuperPoint detections are still the learned frontend input, but numeric landmark identity is no longer inherited from pairwise LightGlue occurrences. KLT carries each surviving landmark through every raw frame, and score-ordered SuperPoint detections only replenish spatially empty locations. That reduces median birth rate from the failed carrier diagnostic's roughly 15% to 2.29%, raises lag-10 common IDs to 291, and yields a finite, common-support-valid trajectory. The result supports the interface hypothesis: learned proposals can be compared fairly when the VINS-facing temporal contract is supplied explicitly. It does not show a performance gain over KLT; on A02, B1 remains substantially better.

The detector-isolated XFeat arm strengthens that interface conclusion while also showing that learned proposal choice matters. With the carrier, sampling, backend, cap, quality channel, and audit fixed, replacing SuperPoint births with XFeat births produced longer-lived A02 tracks and a lower APE/RPE endpoint than B1-constq on the registered common mask. Because A07 then failed five fixed gates before VINS, the correct conclusion is narrow: XFeat-birth is a favorable A02 internal ablation, not a published-method baseline or a generally superior underwater frontend.

The frozen follow-up also limits both carrier results. The SuperPoint-birth policy did not maintain its preregistered lifecycle and two-view margins on either the short H07 mechanism case or its 10 s A07 normal-texture prefix. The independently frozen XFeat-birth policy likewise failed its A07 prefix. These failures are not reasons to tune either carrier against A07. A02 remains the only finite VINS/G0 endpoint for each learned-birth method; H07 remains a contract-invalid diagnostic, while the two A07 prefixes are valid STOP outcomes.

## Excluded attempts

The following are not scientific endpoints and are not counted as repeats:

- B1-constq export `r1`: infrastructure shell; valid export is `r2`.
- B1-constq replay `r1`: zero-frame deadlock caused by `rosbag --wait-for-subscribers` on an unsubscribed GT topic; valid replay is `r2`.
- Direct SP-LG full export `r1`: partial 24,624-byte bag; valid export is `r2`.
- Direct and MAGSAC 10 s runs: diagnostic probes only, not full endpoints.
- MAGSAC short `r1`: environment failure before real frames; short `r2` is only a probe.
- Earlier XFeat seed-chain and pairwise-occurrence exports: different diagnostic arms with different temporal contracts; they are not the preregistered XFeat-birth carrier reported here.
- SP-LG occurrence-preserving coordinate adapter: it passed local smoothness gates but retained the upstream short-lived IDs and produced G0 APE/RPE `1006.75/116.37 m`; it is diagnostic, not the usable carrier reported above.
- First SP-birth producer invocation: import-path infrastructure failure before reading a bag or loading the model; no directory or artifact was created and it is not a scientific attempt.
- Legacy replay `ape.txt` files: diagnostic only; all formal endpoint values above come from common-support G0.

## Next scientific step

Do not expand Direct SP-LG, the DL-VINS-style temporal-MAGSAC arm, the current SuperPoint-birth arm, or this XFeat-birth revision, and do not relax the frontend or backend thresholds to rescue them. Both learned-birth carriers are usable on A02 but failed their required A07 prefix screens, so their planned broad expansions are closed. The next main comparison must run an author-released implementation of a formally published learned-front-end SLAM/VIO system; a local reconstruction from detector and matcher components is not an acceptable substitute. Existing A02/H07/A07 artifacts remain in the evidence set as diagnostics and ablations, including all negative screens and STOP outcomes.

## Reproducibility snapshot

- Direct config: `uw_frontend/configs/experiments/literature_splg_direct_persistent_v1.yaml`, SHA-256 `8128308ce4f0b83b2f6199efdb25fae9fda10a5c920505660f4f7f4fbadc44ea`.
- Temporal-MAGSAC config: `uw_frontend/configs/experiments/literature_splg_direct_dl_vins_magsac_v1.yaml`, SHA-256 `73d8fe914c5b89dcf426388862d1a52eb01f4b77c28664f01babf949063af0d4`.
- Pairwise tracker: `uw_frontend/tracking/pairwise_matcher_tracker.py`, SHA-256 `c2796382afdf79f4ab6c06615390749a6a91e5d8b7cf1f239209ea51e47500c6`.
- Temporal-MAGSAC helper: `uw_frontend/geometry/dl_vins_magsac.py`, SHA-256 `d3c70b0c1f83f589380db82172b448ade485c101ed10102744f8a8d32487e128`.
- LightGlue adapter: `uw_frontend/matchers/lightglue_adapter.py`, SHA-256 `9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a`; the vendored cvg/LightGlue content matches commit `eb42fee2d71449efb0aa5c10549752b5d75384d8`.
- Exporter: `uw_frontend/ros/export_vins_features.py`, SHA-256 `567ccc74989d7fb4ddcb38ac558fecea33033139a0b0db98e61124c6bac5a00d`.
- Verification: 35 system-Python tests passed with one expected real-USAC skip under OpenCV 4.2; 14 isolated-venv tests passed under OpenCV 4.10, including the real `USAC_MAGSAC` synthetic test.
- A02-generating SP-birth producer: `scripts/export_superpoint_lk_carrier_v1.py` at SHA-256 `f8868308d2982e20a09763bf33ab2b89487941bfd713bd9a8242daee2d418060`.
- A02-generating independent auditor: SHA-256 `b790d02f502b730998873d860a3ac7bfe38b0ec4898ddab7ada6e196deee94fb`.
- A02-generating producer/auditor tests: SHA-256 `66c0ef16e1ebbc0b397f90ebd49a86b551748a257f9ebe82bab4b3c342a30b15` / `cdd5f31c1c698286364e56eef91df427956e72f48e09d15aa0837a8b6b2d5dc2`; 27/27 combined system tests and 11/11 isolated OpenCV 4.10 auditor tests passed.
- Current pinhole-plus-Kannala producer/auditor used for H07/A07 screening: SHA-256 `d29d45195e9beb5849cb5012199e40f45b540806caa80fb5deed0b7d9ac5521f` / `284e8d892f12b0bf9b0bfc1f2619082993c42adf64657d6b67c0170283ce5d8d`.
- Current producer/auditor tests: SHA-256 `8570a6e91b7ede7163047a4ffc74e2ff80cc10052a82fb1c64edd822a61f21f6` / `304cd444f798cb7b85a1f04f3af1a67b7dd28a8c8c0ec6089dd0b294ab9a2fa2`; 29/29 combined system tests and 12/12 isolated OpenCV 4.10 auditor tests passed. The old pinhole branch was unchanged; the new Kannala branch maps camodocal `k2...k5` positionally to OpenCV fisheye `D[0...3]`.
- Full producer manifest: `logs/aqualoc_archaeo_vins/external_superpoint_lk_every2_litcmp_a02_0005_full_spbirth_rawlkcarrier_v1_r1/export_manifest.json`, SHA-256 `2e56d7013955332f816622196e70d364e3fc6e39108a687e2d081006d2170f8d`.
- Full independent audit: same run directory `audit.json`, SHA-256 `eb54cd35dec22f60fce844b762b81581e19b251943e055ae25b3ab339a3892ec`.
- XFeat preregistration and single-image smoke receipt: `papers/2026-08-11--xfeat-lk-comparison-preregistration.md` / `papers/2026-08-11--xfeat-lk-single-image-smoke.json`, SHA-256 `ad571ca867ff29d144f9bf98ac8d8e8d9bb2e1ba1c5cfab33f7345df606662a5` / `4dad9d9e7c3b94dc240c24027f26d4cbaa8626e33369630639e9d2061260416d`.
- XFeat producer/auditor: `scripts/export_xfeat_lk_carrier_v1.py` / `scripts/audit_xfeat_lk_carrier_v1.py`, SHA-256 `d7b6a698b784e0cee1c432308eb6f7546251503f0b47f4eeed9651b8fe401aba` / `89998cacb929b00de08eb93cc21e36e7b64434a59acb3fc1b332f16822608935`; algorithm-config SHA-256 `98a8e674f19bfdc2e965a8ea5f27254d837da7f7f4d1254fcbeaa01665c7c1a8`.
- XFeat upstream/model: commit `e92685f57f8318b18725c5c8c0bd28c7fe188d9a`; `weights/xfeat.pt` SHA-256 `0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b`. The complete five-file upstream closure and all eight local implementation/test hashes are frozen in the preregistration.
- XFeat A02 prefix bag/manifest/audit: SHA-256 `a88776327e2252c71950913be1ef8fde4aaca2484c3093fc1a28a0733a84fddd` / `c0a9e9685f851c6ee8a9c5ce75660fab0a77f1a3579c09eed1ee530ea4c816f7` / `c25b5f5164b77f58d9352451bf5907126de4e091f0ad7cda63838c7c96283372`.
- XFeat A02 full bag/manifest/audit: SHA-256 `9116184984a0043fd84e44f1adb733c4dbdf6456fc43b55c8ac7f9bf81d4802f` / `823b277a232e39b83c1c44d1bbc81930c08cfcb24d7cd862ba3705a9eae5b395` / `bd2a1460cb3ae2034eced3524690d0c1711a2a7522aa9d1109e0ef70311b029b`.
- XFeat A02 VINS replay evidence: `vio.csv` / `vins.log` / `ape.txt` SHA-256 `3e0de1d3a63672e7b39037451eb0c52ee6a384d814cdc78c243112c1aaf80140` / `53c1997682ebb2156598142ba62ff8e1fb63ab8d53e068c326a9cf536d7265fd` / `dbd4fba9b4a036baadf09d1370c2016e753182d9bfe7728d44ea5243c9a02b43`. The replay manifest itself records the play-bag path but not its hash or complete CLI; the bag's frozen SHA/size/mtime were therefore independently checked before and after the sole replay and were unchanged.
- XFeat A02 G0 inputs are the frozen B1-constq trajectory `logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_0005_full_b1_constq_vins_r2/vins_output/vio.csv`, SHA-256 `c85bce4238d12e7b1edb754828f1746ffc07656d5ef295e352d03b352d93dd61`, and the XFeat trajectory above. Their configs have SHA-256 `7e1286a9375dc26478e5592c3d16b956b197f792b25af33040c7d6daed6a92cb` / `37fc958a68679448b72ca84f53b8643845a2a2536c2dd59531d65dd8fb86d69b` and are identical after removing only `output_path`. The G0 package does not embed these input hashes or the full command, so this report explicitly binds them together with the preregistered evaluator/parameters rather than claiming a self-contained package.
- XFeat A07 prefix bag/manifest/audit: SHA-256 `50556fa75437c45b7c4e19ba080291ea8128bb119c7bcf957c60dde0fb6a47cb` / `d9bcd4519e0d187dd1dba1447bf8d349ae120e76213cfb4bf944c05d74cff424` / `d88ef07f5388fa07c06877d253624e28a1530e26daefb71dd39e6fafcfecb9b8`; all four registered A07 downstream paths remained absent after STOP.
