# AFRL Gennie ORB-SLAM3 v23 strict analysis

## Analysis question

Does the frozen final-online XFeat lineage remain reachable after transfer to native-rate ORB-SLAM3 on AFRL Cave Gennie `s0,d20`, does the lineage bridge materially change the seeded trajectory, and is the v23 pre-keyframe purge action exercised without dataset-specific tuning?

Evidence record: `ER-20260731-afrl-gennie-v23-01`. The independent evidence unit is one fixed AFRL window. The four runs per role are deterministic runtime replications, not four independent windows.

## QA result

- All 20 role-by-repeat runs are present, `status=ok`, instrumentation-complete, conservation-valid, non-overflowing, and have non-empty reconstructed and online trajectories.
- All runs use the frozen v23 binary `cebeeedb862a469f9b4928fc0712fd0fd93766d4a4b5faa09e7de5a0f19083fc`, library `05a7b3cc8aa7aaefec38ce995de9fbf808662c051f1ce1f0f35925f2e6093af8`, runner `6ffedc001ae51b6b80a391c4dad3a6cbd917037968a1e94e582f98e78a4c4c77`, CPU 2, both background barriers, deterministic background gate, disabled ASLR, `q>=0.9`, 4 px projection, Hamming 100, and audit capacity 131072.
- Output is 343/389 poses (coverage 0.881748) with first output delay 2.334285 s, zero map resets, and zero relocalizations in every arm.
- Evaluation associates 50/60 GT poses at `max_time_diff=0.06 s`. A 20-associated-pose RPE spans 2.536-8.792 s (median 5.019 s), so it is not a fixed one-second RPE.

## Exact results

Positive relative percentages indicate higher error (harm); negative values indicate lower error.

| Trajectory | Role | APE RMSE, mean +/- SD (m) | RPE RMSE, mean +/- SD (m) | APE vs native | RPE vs native |
|---|---|---:|---:|---:|---:|
| reconstructed | Native ORB | 0.003422 +/- 0.000000 | 0.004244 +/- 0.000000 | +0.000% | +0.000% |
| reconstructed | Empty drop | 0.003338 +/- 0.000169 | 0.004299 +/- 0.000110 | -2.469% | +1.290% |
| reconstructed | Seeds, bridge off | 0.006299 +/- 0.000000 | 0.010923 +/- 0.000000 | +84.074% | +157.375% |
| reconstructed | Seeds, unbounded | 0.003316 +/- 0.000000 | 0.004485 +/- 0.000000 | -3.098% | +5.679% |
| reconstructed | Seeds, v23 | 0.003316 +/- 0.000000 | 0.004485 +/- 0.000000 | -3.098% | +5.679% |
| online | Native ORB | 0.004508 +/- 0.000000 | 0.005793 +/- 0.000000 | +0.000% | +0.000% |
| online | Empty drop | 0.004570 +/- 0.000124 | 0.006006 +/- 0.000425 | +1.375% | +3.673% |
| online | Seeds, bridge off | 0.006949 +/- 0.000000 | 0.011471 +/- 0.000000 | +54.148% | +98.015% |
| online | Seeds, unbounded | 0.004481 +/- 0.000000 | 0.006067 +/- 0.000000 | -0.599% | +4.730% |
| online | Seeds, v23 | 0.004481 +/- 0.000000 | 0.006067 +/- 0.000000 | -0.599% | +4.730% |

## Key findings

1. **Reachability passes.** All 54 observations are accepted post-initialization in every seeded role. One lineage forms a MapPoint; 42 accepted observations attach to it. Bridge-on arms consume 37 assisted matches and increase keyframe observations from 23 (bridge off) to 27.
2. **The bridge rescues a harmful seed-only path.** Bridge-off changes reconstructed APE/RPE by +84.074%/+157.375% and online APE/RPE by +54.148%/+98.015% versus native ORB. Bridge-on returns the trajectory close to native.
3. **Accuracy is mixed, not a positive transfer.** Frozen v23 changes reconstructed APE/RPE by -3.098%/+5.679% and online APE/RPE by -0.599%/+4.730%. APE is slightly lower while RPE is higher. Reconstructed RPE exceeds the +5% diagnostic harm limit; online RPE remains just inside it.
4. **v23 guard action is null.** Each bridge-on run performs 214 pre-KF scans, but assisted outliers observed/purged are 0/0. `full` and `full_unbounded` are byte-identical for both trajectory kinds in all four repeats. This window cannot support a v23 purge-benefit claim.
5. **One empty-drop runtime anomaly remains visible.** Drop r1 differs from native and contains 57 keyframes, while native and drop r2-r4 contain 56; drop r2-r4 have reconstructed parity `[False, True, True, True]` and online parity `[False, True, True, True]`. All drop runs load zero observations. This is a residual keyframe-insertion bifurcation, not learned-seed action or a systematic empty-file effect. Native ORB is therefore the primary stable control; no row is discarded.

## Decision

- **Keep:** cross-dataset post-init reachability and lineage-bridge consumption on AFRL.
- **Keep, bounded:** the bridge prevents the large degradation of seed-only/bridge-off injection on this window.
- **Do not promote:** a trajectory-accuracy win, a strict reconstructed no-harm result, or a v23 purge-mechanism generalization claim.
- **Stop repeating this window:** four deterministic repeats already establish the branch behavior. The next useful low-texture candidate must naturally produce post-init assisted outliers under the frozen contract; thresholds and dose remain frozen.

## Claim candidates

- Claim: The final-online XFeat lineage is reachable and consumed by ORB-SLAM3 on AFRL Gennie.
  - Source evidence: `ER-20260731-afrl-gennie-v23-01`; 54/54 post-init observations, one MapPoint lineage, 37 assisted matches in every bridge-on run.
  - Allowed wording: "The frozen lineage transferred to AFRL and participated in ORB tracking."
  - Forbidden stronger wording: "v23 improved AFRL trajectory accuracy."
  - Uncertainty: one fixed low-texture window with sparse COLMAP GT.
  - Next check: a second natural post-init window with nonzero assisted outliers.
  - Decision: keep.

- Claim: The lineage bridge mitigates the harm of direct seed-only injection on this AFRL window.
  - Source evidence: `ER-20260731-afrl-gennie-v23-01`; bridge-off is consistently degraded, while bridge-on is close to native and consumes 37 assisted matches.
  - Allowed wording: "On this window, persistent lineage assistance was necessary to avoid the large bridge-off degradation."
  - Forbidden stronger wording: "The bridge is universally beneficial across datasets."
  - Uncertainty: the experiment isolates the bridge contract but not every internal map-lifecycle cause.
  - Next check: reproduce the bridge-off/bridge-on contrast on an independent window.
  - Decision: keep, bounded.

- Claim: v23 purge generalizes to AFRL.
  - Source evidence: `ER-20260731-afrl-gennie-v23-01`; zero assisted outliers and zero purges, with exact `full`/`full_unbounded` parity.
  - Allowed wording: "v23 remained dormant on AFRL Gennie despite successful lineage reachability."
  - Forbidden stronger wording: "v23 guard action improved or protected the AFRL trajectory."
  - Uncertainty: no action opportunity occurred.
  - Next check: a frozen-contract window with naturally occurring assisted outliers.
  - Decision: discard as a positive claim.
