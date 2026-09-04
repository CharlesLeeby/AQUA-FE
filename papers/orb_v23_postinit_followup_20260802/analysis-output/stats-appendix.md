# Statistical appendix

## Design

- Five unique mechanism-positive windows are listed in `window_roster.csv`.
- The independent unit is one fixed image interval; selector variants are not independent units.
- mclab1 and mclab2 each have a five-arm x four-repeat formal matrix (`20` runs per selector).
- Repeats are deterministic reproductions, not independent samples.
- APE/RPE are translational RMSE after the frozen evaluator alignment; lower is better.
- RPE uses `delta=1` frame and `max_time_diff=0.06 s`.

## Descriptive full-branch values

`formal_summary.csv` reports the full and control means. Percentages are unstandardized paired
branch changes: negative means lower error. They are not population effect sizes.

| Window | Trajectory | Full APE/RPE (m) | Native/drop APE/RPE (m) | Full vs native/drop (%) | Full vs unbounded (%) |
|---|---|---:|---:|---:|---:|
| A10 `2400-2800` | reconstructed | 0.011993 / 0.016178 | 0.014089 / 0.017840 | -14.877 / -9.316 | -14.952 / -17.905 (aggregate) |
| A10 `2400-2800` | online | 0.023529 / 0.019948 | 0.029865 / 0.034533 | -21.215 / -42.235 | -27.868 / -27.723 (aggregate) |
| A02 `2800-3200` | reconstructed | 0.023321 / 0.021781 | 0.077687 / 0.037684 | -69.981 / -42.201 | -74.299 / -46.039 |
| A02 `2800-3200` | online | 0.022080 / 0.018213 | 0.066472 / 0.032750 | -66.783 / -44.388 | -71.308 / -44.832 |
| A08 `4500-4660` | reconstructed | 0.124809 / 0.240456 | 0.183661 / 0.332345 | -32.044 / -27.649 | -6.133 / -1.747 |
| A08 `4500-4660` | online | 0.180265 / 0.321966 | 0.120957 / 0.308958 | +49.032 / +4.210 | +1.735 / -0.531 |
| NTNU mclab2 `s110,d10` | reconstructed | 0.100976 / 0.069453 | 0.112179 / 0.065230 | -9.987 / +6.474 | +1.666 / +0.373 |
| NTNU mclab2 `s110,d10` | online | 0.128611 / 0.070706 | 0.112747 / 0.066187 | +14.070 / +6.828 | -2.514 / +0.167 |
| NTNU mclab1 `s60,d15` | reconstructed | 0.018007 / 0.062446 | 0.018122 / 0.062520 | -0.635 / -0.118 | -4.305 / -0.054 |
| NTNU mclab1 `s60,d15` | online | 0.035048 / 0.062985 | 0.052752 / 0.063240 | -33.561 / -0.403 | -14.638 / -0.128 |

## Directional decisions

- Project-promoted strict trajectory positives: `3/5` mechanism-positive windows (A10, A02,
  mclab1); A10's unbounded comparison is `3/4` repeatwise.
- Stricter all-control repeatwise audit: `2/5` (A02, mclab1).
- Action-positive but metric-mixed: A08 and mclab2.
- Operational degraded/low-grid among all mechanism positives: `2/5`; sparse-base-KLT low
  texture: `0/5`.

No confidence interval, p-value, Wilcoxon test, or standardized effect size is reported. Such a
calculation would treat deterministic repeats as independent observations and would be
pseudoreplication.
