# Figure catalog

## Figure 1: `figures/figure-01-screening-action-funnel.pdf`

- Purpose: show why five windows entered the queue but only three entered formal APE/RPE evaluation.
- Data source: `screening_summary.csv`, full-arm smoke counters.
- Caption requirements: bars are raw per-window counts; no uncertainty bars are appropriate for a
  single smoke run; post-init and action stages are not independent samples.
- Key observation: A09 reaches matches but has zero outliers/purges; A07 has action but fails the
  pure-post-init gate; A08/A10/A02 pass action screening.
- Interpretation: the mechanism screen prevents trajectory metrics from selecting the next window.
- Caveat: smoke counts are not formal trajectory results.

## Figure 2: `figures/figure-02-formal-four-metric-comparison.pdf`

- Purpose: compare all five formal roles across reconstructed/online APE/RPE for each eligible window.
- Data source: `case_summary.csv`; bars are means and error bars are sample SD across four deterministic repeats; dots are all repeats.
- Key observation: A02 full is below native, drop, and unbounded in every panel; A08 and A10 show mixed panels.
- Interpretation: A02 is the only strict four-metric positive in the screened set.
- Caveat: four repeats are reproducibility checks, not independent windows.

## Figure 3: `figures/figure-03-relative-change.pdf`

- Purpose: resolve full-branch changes relative to native and unbounded controls.
- Data source: `paired_effects.csv`; error bars are sample SD across deterministic repeats.
- Key observation: A02 is negative (improvement) against both controls in all four metrics; A10 improves against unbounded but not native.
- Interpretation: the unbounded contrast identifies purge-related rescue, while native remains the strict accuracy control.
- Caveat: the dashed +5% line is a diagnostic boundary, not a significance threshold.

## Figure 4: `figures/figure-04-formal-action-stability.pdf`

- Purpose: separate bridge consumption, natural outlier production, and enforced purge action.
- Data source: formal `seed_summary.json` files; bars are raw counts from repeat 1, verified stable across repeats for the full arm.
- Key observation: A02 changes purge from 0 in unbounded to 3 in v23 with the same 7 matches/3 total and pre-KF outliers.
- Interpretation: A02 directly exercises the intended v23 causal action chain.
- Caveat: action counts do not by themselves establish trajectory benefit.
