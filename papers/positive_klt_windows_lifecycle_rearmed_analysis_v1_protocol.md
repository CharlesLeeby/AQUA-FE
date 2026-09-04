# Positive-KLT-window lifecycle-rearmed strict analysis v1

Status: frozen for controller review before the sole formal analysis run.  This
protocol summarizes already completed artifacts; it starts no frontend, backend,
trajectory evaluator, or hyperparameter search.

## Fixed analysis question and roster

The primary question is descriptive: on the three previously selected AQUALOC
windows in which the historical KLT comparison was positive, how did fresh
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1` change APE RMSE and RPE RMSE relative
to a fresh external-KLT arm under the same VINS-Fusion backend contract?

The fixed, non-metric-sorted display order is A06, A10, A09.  These are the complete
three-window KLT-positive roster used by the lifecycle-rearmed/HFNet natural-history
comparison, not the larger and methodologically different ORB-SLAM3 mechanism-window
roster.  Roster inclusion is outcome-selected and all three windows are
development-exposed.  No later window may be added to, removed from, or reordered in
this v1 analysis after inspecting the lifecycle-rearmed trajectory metrics.

## Unit of analysis and claim boundary

- The primary controlled pair is fresh external KLT versus fresh lifecycle-rearmed
  AQUA-FE, with one realized trajectory per arm per window.
- A window is one descriptive paired unit (`n = 1 trajectory/arm/window`); there are
  three selected window-level pairs in the roster.
- The 1 Hz common-support grid poses and RPE pairs are within-trajectory evaluation
  samples.  They are not independent repeats, seeds, or analysis units and must not
  be used to inflate `n`.
- Per-window effects are `AQUA - KLT` in metres and
  `100 * (AQUA - KLT) / KLT` in percent.  RMSE is lower-is-better, so a negative
  delta denotes improvement.
- The bundle may report the exact per-window effects, both-metric win count, and the
  macro mean plus sample SD and median/range of the three relative deltas.  These
  summaries describe only this selected roster; the sample SD is heterogeneity
  across the three selected windows, not uncertainty of a population estimate.
- Confidence intervals, p-values, hypothesis tests, standardized population effect
  sizes, significance language, general superiority, robustness, confirmatory
  claims, and treating grid points as independent `n` are forbidden.
- A learned-action score gate is a necessary attribution gate: a zero-action output
  cannot support a learned-action accuracy comparison.  Nonzero action is not a
  sufficient condition for accuracy improvement, as the A10 result must be retained.

## Exact pinned inputs

Only the following six JSON artifacts may supply numbers.  The runner must hash and
validate every artifact before and after report generation and fail closed on any
mismatch.

| Window | Role | Bytes | SHA-256 | Path |
|---|---|---:|---|---|
| A06 | primary evaluation terminal receipt | 23217 | `45e0476cc9a913737b6e1531cb9eb77fbec6892d5c4a524abd0b22968075853d` | `/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_fourarm_common_support_v1/terminal_analysis_receipt_v1.json` |
| A06 | frontend action terminal receipt | 2644 | `4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705` | `/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_natural_history_v1/terminal_probe_receipt_v1.json` |
| A10 | primary-pair adjudication | 1944 | `2735f48090ee5c786f322ff68a3c0f87b8a4e270a7a9a67800a831eb2c0319d5` | `/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_evaluation_v1/a10/primary_pair/adjudication_v1.json` |
| A10 | frontend action terminal receipt | 2482 | `252bf9cda368aa052134b94aff5dd1d0349d0ee8b466c1b4860a05186364a619` | `/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1/a10/terminal_probe_receipt_v1.json` |
| A09 | primary-pair adjudication | 1943 | `1dccd654ba29f3474551935b459bbf47db61ec1693fbf647142eeda5e5c4f605` | `/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_evaluation_v1/a09/primary_pair/adjudication_v1.json` |
| A09 | frontend action terminal receipt | 2608 | `7eda30a0c6316b67d8976e460138785d4078adbf862b0f0595e3e092a6c6cb8c` | `/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_v1/a09/terminal_probe_receipt_v1.json` |

Required evaluation statuses are `PASS_FIXED_COMMON_SUPPORT_GATES` for A06 and
`PASS_PRIMARY_APE_RPE_GATES` for A10/A09.  Each support record must authorize both
APE and RPE, contain one segment, at least 30 matched common poses, and at least 10
RPE pairs.  Every claim boundary must forbid statistical inference and ranking or
superiority.  Required action status is `PASS_SCORE_ACTION_GATE_FRONTEND_ONLY`, with
method ID `AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1` and a passed nonzero action
gate.

The frozen score-window carrier denominators are 125 for A06 and 200 each for A10
and A09.  The action numerators must be read from the receipts and equal 107, 184,
and 182, respectively.  Action density is numerator divided by this carrier-message
denominator; it is not a success probability or an independent sample statistic.

## Required outputs and figures

The fixed output directory is:

`/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_analysis_v1/analysis-output`

It must contain at least:

- `window_metrics.csv`;
- `aggregate_summary.json`;
- `analysis-report.md`;
- `stats-appendix.md`;
- `figure-catalog.md`;
- `figures/figure-01-primary-relative-change.pdf`;
- `figures/figure-02-action-density.pdf`.

Figure 1 plots per-window APE and RPE relative deltas with a zero reference line;
negative means lower RMSE.  Figure 2 plots score-window action density with exact
numerator/denominator labels.  Both use colorblind-safe colors plus hatch/marker
redundancy and vector PDF output.  Neither figure may contain error bars: every bar
is one realized window-level paired effect or one deterministic receipt ratio, and
there are no repeated runs from which an uncertainty bar can be estimated.  The
catalog and captions must state this explicitly.

The analysis report must retain the A10 degradation, report exactly two of three
windows with decreases in both primary metrics, report all three action-positive,
and include claim candidates in the `Claim / Source evidence / Allowed wording /
Forbidden stronger wording / Uncertainty / Next check / Decision` template.

## Exactly-once and additive publication

The controller has read-only `preflight` and mutating `run` modes.  Formal `run`
requires both the final root and fixed staging root to be absent, writes a start
claim before analysis generation, and permits one analysis process with zero retry.
All outputs are first written under the previously absent fixed staging root
`.positive_klt_windows_lifecycle_rearmed_analysis_v1.stage_v1`; after schema,
numerical, figure, receipt, and input-stability checks pass, the entire root is
atomically renamed to the final root.  Existing final, staging, or retained failure
paths cause a fail-closed stop.  No prior experiment artifact is modified, copied
over, deleted, or adopted.

