# Statistical appendix

## Design and unit of analysis

- Dataset/window: AFRL Cave Gennie `s0,d20`, native 20 Hz export, 389 images.
- Roles: native ORB, empty drop, seeds with bridge off, seeds with unbounded purge enforcement, and frozen v23.
- Runtime replications: four per role, with r4 swapping `full` and `full_unbounded` order.
- Independent evidence unit: one window (`n=1 window`). Runtime repeats quantify branch reproducibility only.
- Metrics: Sim(3)-aligned translational APE RMSE and 20-associated-pose translational RPE RMSE; lower is better.

## Descriptive statistics

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

The table reports mean +/- sample SD across four runtime replications. Zero SD means the metric was identical to six decimal places; trajectory hash parity is reported separately.

## Paired window effects

- Frozen v23 vs native, reconstructed: APE -3.097604%, RPE +5.678605%.
- Frozen v23 vs native, online: APE -0.598935%, RPE +4.729846%.
- Bridge off vs native, reconstructed: APE +84.073641%, RPE +157.375118%.
- Bridge off vs native, online: APE +54.148181%, RPE +98.014846%.

These are unstandardized relative effects for one window, not population effect sizes.

## Inferential-statistics decision

No t-test, Wilcoxon test, confidence interval, standardized effect size, or multiple-comparison correction is reported. The four repeats share the same images, GT, seeds, binary, and deterministic scheduler; treating them as independent samples would be pseudoreplication. Cross-window inference requires additional independent windows.

## Reproducibility and anomaly audit

- Native ORB, bridge-off, unbounded, and v23 each have one unique trajectory hash per trajectory kind across four repeats.
- `full` and `full_unbounded` are same-repeat byte-identical in 8/8 reconstructed/online comparisons.
- Drop/native parity is reconstructed `[False, True, True, True]` and online `[False, True, True, True]`. Native keyframe counts are `[56, 56, 56, 56]`; drop counts are `[57, 56, 56, 56]`. The r1 empty-drop deviation is retained in all means/SDs and blocks a claim of universal empty-control parity.
- Instrumentation is complete in 20/20 runs, with zero event or related-MapPoint overflow.

## GT association boundary

- GT poses available: 60.
- Estimated poses per run: 343.
- Associated poses at `0.06 s`: 50.
- Association absolute time error: 0.000249/0.000252/0.000253 s (min/median/max).
- RPE pairs: 30.
- Physical duration of a 20-associated-pose delta: 2.536364/5.018663/8.791941 s (min/median/max).

The RPE label must remain "20-associated-pose RPE"; it must not be described as one-second or 20-image-frame RPE.
