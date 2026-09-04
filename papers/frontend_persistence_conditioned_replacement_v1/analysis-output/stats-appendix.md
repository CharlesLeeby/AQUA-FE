# Statistical appendix

## Descriptive estimands

For each window and arm, the reported estimand is the median of three identical-input backend replays. The interval is the full minimum–maximum range. APE uses independent fixed-scale proper SE(3) alignment; RPE uses the same common 1 Hz grid with a 1 s delta.

| window | APE change vs KLT | RPE change vs KLT | label |
|---|---:|---:|---|
| a09_6000_6800 | -99.941% | -99.951% | WIN |
| a06_s045_d045 | -17.440% | -19.546% | WIN |
| a06_s000_d045 | +4843.782% | +4567.139% | REGRESSION |
| h07_s000_d050 | 0% | 0% | NO_HARM_INPUT |

The extreme a09 ratios reflect KLT scale divergence, not centimetre-level absolute-GT accuracy. The extreme a06_s000 median reflects two scale-diverged replays and one KLT-like replay; the full range is therefore essential.

## Cross-check

`evo_ape` and segmented `evo_rpe` independently cross-checked both fixed-scale and Sim(3) calculations. Across all cells and metrics the maximum absolute discrepancy was below `5.0e-7 m`.

## Excluded inference

No t-test, Wilcoxon test, confidence interval over replays, or claim of population superiority is valid here. Replays share one input and window, and the development windows were selected from known historical behaviors.
