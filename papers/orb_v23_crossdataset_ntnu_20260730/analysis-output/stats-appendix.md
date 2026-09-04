# Statistical appendix

## Units and validity

- Low-texture sample: one fixed NTNU window, four deterministic repeats per role.
- Normal-texture sample: one fixed non-overlapping NTNU window, four deterministic repeats per role.
- Repeats are paired runtime replications, not independent datasets. No t-test, Wilcoxon test, or population-level p-value is valid here.
- Exact byte equality and deterministic role-order checks are the primary robustness evidence.

## Low-texture final-online descriptive statistics

| Metric | Native mean +/- SD | v23 mean +/- SD | Mean relative improvement |
| --- | ---: | ---: | ---: |
| Reconstructed APE | `0.017459 +/- 0.000000` | `0.016996 +/- 0.000294` | `2.653%` |
| Reconstructed RPE | `0.239246 +/- 0.000000` | `0.239094 +/- 0.000459` | `0.063%` |
| Online APE | `0.029706 +/- 0.000000` | `0.033367 +/- 0.000112` | `-12.324%` |
| Online RPE | `0.232416 +/- 0.000000` | `0.234119 +/- 0.000349` | `-0.733%` |

Per-repeat v23 candidate:

| Repeat | Reconstructed APE/RPE | Online APE/RPE | Four-metric 5% no-harm |
| --- | ---: | ---: | --- |
| 1 | 0.017143/0.238865 | 0.033311/0.234293 | fail |
| 2 | 0.017143/0.238865 | 0.033311/0.234293 | fail |
| 3 | 0.017143/0.238865 | 0.033311/0.234293 | fail |
| 4 | 0.016554/0.239783 | 0.033535/0.233595 | fail |

- No-harm result: `0/4`.
- Candidate SD reflects two alternate role/batch branches, not measurement uncertainty about a population mean.
- All four native and exact-drop trajectories are byte-identical; candidate r1-r3 are byte-identical and r4 differs after role swap.

## Normal-texture exact result

| Kind | APE/RPE in all 12 arms | Poses / coverage | Resets / relocalizations | Byte parity |
| --- | ---: | ---: | ---: | --- |
| Reconstructed | `0.316160/0.218529` | `390 / 0.9774436090` | `0/0` | all roles and repeats identical |
| Online | `0.318803/0.218009` | `390 / 0.9774436090` | `0/0` | all roles and repeats identical |

- v23 scans: `240` per candidate repeat.
- Learned/assisted/outlier/purge actions: `0/0/0/0` in all repeats.
- Instrumentation: complete, conservation valid, zero event or MapPoint overflow in all 12 arms.
- This is an exact equality result; mean/SD, CI, and null-hypothesis tests add no information because all differences are exactly zero.

## Diagnostic boundary

| Role | Reconstructed APE/RPE | Online APE/RPE | Assisted matches | Assisted outliers | Pre-KF purged |
| --- | ---: | ---: | ---: | ---: | ---: |
| Unbounded | `0.025914/0.237747` | `0.038184/0.231176` | 19 | 1 | 0 |
| v23 | `0.023451/0.238427` | `0.033644/0.234253` | 15 | 3 | 1 |

The event streams first differ at event index 500, before the first candidate assisted-outlier event at index 531; no paired causal effect size is reported.
