# Statistical Appendix

## Estimand and Direction

The primary estimand is the paired difference in 1 s translational RPE RMSE
(classical minus learned, in metres), where positive values favour learned.
All metrics are lower-is-better.

## Descriptive Results

| Comparison | Evaluator | Scientific units | Technical replays | Learned mean +/- SD (m) | Classical mean +/- SD (m) | Arm-mean reduction | Validity |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| A06 learned vs frame-6 replacement | G0 common support | 1 | 1 | 0.021522 | 0.063065 | 65.9% | RPE valid, APE invalid |
| A08 learned vs same-ID GFTT | legacy evaluator | 1 | 3 | 0.113347 +/- 0.000017 | 0.137348 +/- 0.002356 | 17.5% | invalid support |
| A08 learned vs same-ID GFTT | G0 common support | 1 | 3 | 0.099330 +/- 0.000030 | 0.120675 +/- 0.000885 | 17.7% | invalid support |
| A03 learned vs same-ID GFTT | G0 common support | 1 | 3 | median 0.078869 | median 0.020439 | GFTT lower by 74.1% | APE and RPE valid |
| NTNU native-q learned vs KLT | G0 common support | 1 | 3 | median 0.038135 | median 0.065728 | learned lower by 42.0% | APE and RPE valid |
| NTNU native-q learned vs same-ID GFTT | G0 common support | 1 | 3 | median 0.038135 | median 0.091582 | learned lower by 58.4% | APE and RPE valid |
| NTNU native-q learned vs exact drop | G0 common support | 1 | 3 | median 0.038135 | median 5.113238 | learned lower by 99.3% | APE and RPE valid; drop unstable |
| NTNU native-q vs XFeat-only q=1 | G0 common support | 1 | 3 | median 0.038135 | median 0.038135 | negligible | source-specific sensitivity arm |
| NTNU native-q vs global q=1 learned | G0 common support | 1 | 3 | median 0.038135 | median 10.599716 | native lower by 99.6% | global interaction ablation |

The A08 and A03 replay distributions describe runtime repeatability for fixed
input bags. They are not population uncertainty and must not be reported as
`n=3` independent experiments. A03 uses the frozen median reducer because KLT
has one catastrophic replay; all replay rows and the any-of-three solver-risk
status remain visible.

The NTNU rows follow the same rule: one development event, three technical
replays. The exact-drop arm has two optimizer branches, so the median and full
min/max range are retained instead of a population confidence interval. The
XFeat-only-q1 and global-q1 rows are sensitivity ablations, not additional
independent methods or events.

## Inferential Tests

No t-test, Wilcoxon test, confidence interval, or p-value is used for the main
claim. The scientific unit count is one event each for A03, A06, and A08;
technical replay rows do not provide independent degrees of freedom. A sign
count across three selected development events is underpowered and not a valid
population test.

No multiple-comparison correction is required because no inferential family is
claimed. The machine comparison table records `inferential_test=not_run`.

## Validity and Failure Accounting

- A06 G0: 22 common poses, 21 RPE pairs, 21 s common span; RPE valid, APE
  invalid because the 30-pose APE gate is not met.
- A08 G0: 6 common poses, 5 RPE pairs, 5 s common span; both RPE and APE
  invalid.
- A08 legacy: 68 estimate matches but only 7 unique reference assignments;
  one reference timestamp is reused up to 15 times. Legacy values are retained
  only as directional diagnostics.
- All six A08 preserve-ID replays initialized successfully, had zero solver
  failures, and had identical coverage (`0.837535`).
- A03 G0: 32 common poses, 31 RPE pairs, 31 s common span, common coverage
  `0.711111`; both APE and RPE are valid.
- A03 GFTT: RPE median `0.020439 m`, sample SD across technical replays
  `0.000010 m`, output coverage `0.904412`, and zero solver failures in 3/3.
- A03 learned: RPE median `0.078869 m`, sample SD `0.002744 m`, output coverage
  `0.837736`, and solver failures in 3/3.
- A03 KLT/exact drop: RPE median `0.078769 m`; one replay diverges to
  `60.482959 m` strict RPE and any-of-three solver risk is true.
- NTNU joint G0 mask: 269 common poses, 259 exact 1 s RPE pairs, 26.8 s span,
  common coverage `0.893688`; both APE and RPE are valid. Evo primary/evo
  absolute differences are below `1e-6 m` for every arm.
- NTNU native-q learned: RPE median `0.038135 m`, technical range
  `1.23e-8 m`, initialization 3/3, zero solver failures 3/3.
- NTNU native-q KLT: RPE median `0.065728 m`, identical across 3/3 replays,
  initialization 3/3, zero solver failures 3/3.
- NTNU native-q same-ID GFTT: RPE median `0.091582 m`, technical range
  `1.32e-9 m`, initialization 3/3, zero solver failures 3/3. It is a
  retrospective full-interval survival/proximity match, not an online arm.
- NTNU native-q exact drop: RPE `5.113238/12.101863/5.113238 m`; all runs
  initialize and report zero solver failures, but occupy two poor trajectory
  branches. Failure counts therefore do not substitute for trajectory error.
- NTNU global q=1 learned: RPE median `10.599716 m`. XFeat-only q=1:
  `0.038135 m`. The global-q result changes all observations and cannot be
  assigned to the eight learned observations.
- Native-q 10/20/30 s prefix diagnostics remain learned-positive. Learned
  medians are `0.056822/0.038578/0.038135 m` versus KLT
  `0.126004/0.079930/0.065728 m`. These are nested diagnostics within one
  event, not three independent units.

## Provenance

Machine rows are in `replay-metrics.csv`, `a03-replay-summary.csv`,
`ntnu-replay-summary.csv`, `ntnu-prefix-summary.csv`, and
`comparison-summary.csv`. Probe status is in `probe-summary.csv`. Raw source
paths, replay manifests, bag hashes and G0 summaries are listed in the parent
report.
