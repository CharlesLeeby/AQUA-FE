# Figure catalog

## Figure 1: `figures/figure-01-five-arm-absolute-metrics.pdf`

- Purpose: show the complete five-arm reconstructed/online APE/RPE comparison without truncated axes.
- Data source: `case_summary.csv`, 4 runtime replications per role on one fixed window.
- Caption requirements: bars are means, error bars are sample SD, dots are all replications, lower is better, and repeats are not independent windows.
- Key observation: bridge-off is consistently degraded; bridge-on unbounded and v23 return close to native ORB.
- Interpretation: persistent lineage assistance changes the harmful seed-only path, but the final trajectory remains a mixed APE/RPE result.
- Caveat: the sparse GT supplies only 50 associated poses.

## Figure 2: `figures/figure-02-near-baseline-relative-change.pdf`

- Purpose: resolve near-baseline effects hidden by the large bridge-off errors and show the +5% diagnostic harm line.
- Data source: `paired_effects.csv`; each role is compared with native ORB from the same repeat.
- Caption requirements: positive values mean harm, bars are mean relative change, error bars are sample SD, dots are all four runtime replications, and +5% is a diagnostic boundary rather than a significance threshold.
- Key observation: v23 slightly lowers APE but raises RPE; reconstructed RPE is +5.679% and online RPE is +4.730%.
- Interpretation: this window is not a dual-metric accuracy positive; online remains within the 5% boundary while reconstructed does not.
- Caveat: drop r1 is the only non-parity empty-control run and is retained.

## Figure 3: `figures/figure-03-reachability-and-action-counts.pdf`

- Purpose: separate seed reachability, lineage bridge consumption, and v23 purge action.
- Data source: each role's frozen `instrumentation/seed_summary.json`; counts are identical across repeats, so r1 values represent all four.
- Caption requirements: bridge-off/unbounded/v23 are shown; accepted observations, MapPoint reachability, keyframe observations, assisted matches, scans, outliers, and purges are raw per-run counts.
- Key observation: bridge-on consumes 37 assisted matches and performs 214 scans, but observes and purges zero assisted outliers.
- Interpretation: the bridge is active, while the v23 guard is dormant and unidentifiable on this window.
- Caveat: scan count is an opportunity check, not evidence of a guard intervention.
