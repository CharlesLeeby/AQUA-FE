# Figure catalog

## figure-01-trajectory-xy.svg

- Purpose: show the XY geometry of the COLMAP proxy and the fixed-scale/diagnostic aligned estimates.
- Data source: `grid_metrics.csv`.
- Reader should notice: whether fixed-scale geometry follows the reference and how much the diagnostic scale fit changes it.
- Belief update: geometric visualization only; it does not create another experimental replicate.
- Caveat: XY projection hides Z error and the reference is image-derived.

## figure-02-errors-over-time.svg

- Purpose: show temporal concentration of translation APE and exact-1 s RPE.
- Data source: `grid_metrics.csv` and `rpe_pairs.csv`.
- Reader should notice: whether error is localized or sustained across the frozen score interval.
- Belief update: descriptive localization only; adjacent points and RPE pairs overlap.
- Caveat: no confidence band or inferential annotation is valid for this single dependent trajectory.
