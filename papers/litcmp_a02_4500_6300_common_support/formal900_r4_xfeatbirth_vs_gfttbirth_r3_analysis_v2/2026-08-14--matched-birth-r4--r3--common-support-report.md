# A02 matched-birth r4 frozen common-support report (r3)

The sealed formal result is `PASS_STRICT_FULL_REFERENCE_COMMON_SUPPORT`. This document transcribes the sealed r3 summary and CSV; it does not open trajectories or recompute APE/RPE.

| Arm | APE RMSE (m) | APE median (m) | RPE RMSE (m) | RPE median (m) | Common poses | RPE pairs |
|---|---:|---:|---:|---:|---:|---:|
| GFTT birth raw-LK | 1.042693077 | 0.5630787772 | 0.2290266468 | 0.09218042378 | 84 | 83 |
| XFeat birth raw-LK | 0.7413695192 | 0.6751966454 | 0.04237870155 | 0.03245161485 | 84 | 83 |

Common support is 84/90 (0.9333333333), spanning 83 s in 1 segment, with 83 one-second RPE pairs.

For descriptive presentation only, the sealed point estimates give an APE RMSE reduction of 0.3013235574 m (28.8986%) and an RPE RMSE reduction of 0.1866479453 m (81.4962%) for XFeat-birth relative to GFTT-birth on this one frozen window.

## Claim boundary

- This is post-result exploratory evidence; it was not outcome-blind or confirmatory.
- `n=1` frozen A02 window and one underlying VINS replay per arm. The two evaluator roles are a deterministic consistency check, not independent samples.
- No significance test, confidence interval, cross-window/dataset generalization, whole-SLAM superiority, or standalone detector superiority is claimed.
- The reference is image-derived COLMAP, not independent external ground truth.
- Runner-local APE outputs were visible before freeze; this report uses only the sealed common-support result.
