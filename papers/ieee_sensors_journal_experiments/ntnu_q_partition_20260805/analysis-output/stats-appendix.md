# Statistical appendix

## Unit and reducer

- Primary metric: G0 common-support 1 s translation RPE RMSE; lower is better.
- Secondary metric: G0 common-support APE RMSE; lower is better.
- Scientific unit: one NTNU development event (`n=1`).
- Technical repeats: three serial single-threaded VINS replays per arm.
- Numeric reducer: median of the three evaluable technical repeats; full min-max range is retained.
- Failure reducer: all 15 replays are evaluable on this contrast. The high-error GFTT-birth replay is not reclassified as a formal hard failure because it initialized, retained valid support, and had no frozen solver-failure signature.

## Descriptive statistics

| Classical q partition | APE median [min, max] (m) | 1 s RPE median [min, max] (m) |
|---|---:|---:|
| Native classical q | 0.120227 [0.118893, 0.120227] | 0.048943 [0.048363, 0.048943] |
| Source 1 / propagated q=1 | 0.111325 [0.111302, 0.112379] | 0.066336 [0.066332, 0.066714] |
| GFTT birth / source 2 q=1 | 0.401773 [0.401773, 249.328487] | 0.127408 [0.127408, 33.394720] |
| Classical sources 1+2 q=1; XFeat native | 55.153743 [55.153743, 55.153743] | 10.318418 [10.318418, 10.318418] |

The individual replay rows are in `replay-metrics.csv`; medians and ranges are
in `factorial-summary.csv`. These repeats estimate numerical branch behavior
only. Mean +/- SD, replay-level confidence intervals, t-tests, Wilcoxon tests,
and p-values would incorrectly treat technical repeats as independent and are
therefore omitted.

## Comparability checks

- Shared support: 285/301 grid poses, 275 RPE pairs, 28.400 s span.
- Bag topology: three audits PASS with 6,300 messages, 300 feature frames, and 6,000 raw-byte-equal non-feature messages each.
- Replay identity: every `vio.csv`, VINS YAML, played bag, initialization flag, and solver-failure count is recorded in `replay-input-manifest.csv`.
- Configuration equality: all 15 replay YAMLs agree on the frozen estimator fields, including `max_cnt=350` and `multiple_thread=0`.
- Changed fields: only predeclared source partitions in `quality` and `sigma`.
- Geometry and all other feature channels: equal by fail-closed audit.
- Evo independent implementation check: maximum absolute metric discrepancy 4.973e-07 m.

## Inferential blocker

There is one selected development event and no independent sequence-level
replication. No inferential test or population uncertainty interval is valid.
The held-out confirmatory matrix must use sequence as the independent unit.

## Mechanism-count caveat

The lineage counts in `lineage-audit.json` describe full-bag track histories.
They are not counts of residual blocks evaluated repeatedly inside each VINS
sliding-window optimization.
