---
type: results-report
date: 2026-08-02
experiment_line: orb-v23-postinit-followup
round: 2
purpose: transfer-summary
status: complete
source_artifacts:
  - analysis-output/analysis-report.md
  - analysis-output/stats-appendix.md
  - analysis-output/figure-catalog.md
  - analysis-output/window_roster.csv
  - analysis-output/formal_summary.csv
  - analysis-output/texture_denominator.csv
  - analysis-output/provenance.json
linked_experiments:
  - ../orb_v23_postinit_action_search_20260731/2026-08-01--orb-v23-postinit-action-search--handoff.md
linked_results:
  - ../2026-07-31--aqua-fe--r01--project-progress-addendum.md
---

# ORB-v23 post-init follow-up / Round 02 / transfer-summary / 2026-08-02

> The workspace is not bound to an Obsidian knowledge base. This report is a local paper artifact;
> no Obsidian write-back was attempted.

## Executive Summary

The follow-up adds two independent NTNU image windows to the ORB-v23 mechanism search. The unique
mechanism-positive roster now contains five windows. Two are operationally degraded/low-grid
(`2/5 = 40%`), but none is a sparse base-KLT low-texture window under the stricter feature-count
definition. NTNU mclab1 `s60,d15` is a new repeatwise strict trajectory positive. NTNU mclab2
`s110,d10` is action-positive but metric-mixed.

An audit also records a label caveat: the old roster calls A10 `2400-2800` strict under the
project's primary native/drop rule, while its source formal report records `3/4` repeatwise
dominance against the unbounded shadow. This report keeps the project denominator at `3` strict
windows (`1/3` operationally degraded) and additionally reports the stricter all-control audit:
`2` windows (`1/2` degraded).

## Experiment Identity and Decision Context

The search was intended to test whether a post-init MapPoint and natural assisted-outlier/purge
chain transfers beyond AQUALOC without changing the frozen binary, thresholds, selector contract,
or runtime schedule. The primary decision is whether another selector variant should be run. The
answer is no: both NTNU intervals have already been answered by complete formal matrices, and
selector variants are not new independent windows.

## Setup and Evaluation Protocol

The frozen contract uses q >= 0.9, 4 px projection, Hamming 100, pre-KF purge only in `full`, CPU2,
dual background barriers, deterministic gate, ASLR off, audit capacity 131072, online export,
four repeats, and a role-order swap in repeat 4. APE/RPE use the frozen evaluator with
`max_time_diff=0.06 s` and RPE delta 1 frame. See `analysis-output/provenance.json`.

## Main Findings

1. mclab1 n3: `39/39` post-init observations, 3 MapPoint lineages, 7 assisted matches, 2
   assisted outliers, and `1/1` purge in every full repeat; `64/64` directional checks pass.
2. mclab2 n3: `108/108` post-init observations, 3 MapPoint lineages, and stable `45/16/8`
   matches/outliers/purges; reconstructed APE improves but RPE worsens, and both online metrics
   worsen against native/drop.
3. A02 remains the operationally degraded strict positive; A08 remains action-positive but
   online-mixed; A10 remains a stable project strict positive with one alternate unbounded branch.

## Statistical Validation

There is one independent interval per window. Four repeats are deterministic reproducibility
checks, so no inferential test or confidence interval is reported. Directional checks are the
pre-specified decision rule; the exact counts and descriptive means are in the machine-readable
tables.

## Figure-by-Figure Interpretation

No new plotted figure is needed for this registry. Table 1 (`window_roster.csv`) establishes the
window-level action and texture denominator; Table 2 (`formal_summary.csv`) separates action from
trajectory outcome; Table 3 (`texture_denominator.csv`) prevents the operational low-texture label
from being confused with sparse base KLT.

## Failure Cases / Negative Results / Limitations

- Action is not sufficient for a trajectory positive: A08 and mclab2 show stable purge action but
  mixed or adverse trajectory metrics.
- A10's unbounded r2 alternate map branch prevents a fully repeatwise all-control label, while
  the project primary-control label remains strict.
- The search queue is mechanism-selected; these fractions are descriptive and cannot estimate
  deployment success probability.
- Operational degraded/low-grid is not evidence of genuinely sparse base KLT; all five windows
  remain near the 350-feature cap or are saturated.

## What Changed Our Belief

The main update is that v23 action and strict trajectory benefit can reproduce on a second NTNU
window (mclab1), while a nearby NTNU action-positive window (mclab2) does not yield a dual-metric
gain. This strengthens the claim that post-init state reachability and purge action are necessary
but not sufficient for accuracy improvement. It weakens any claim that the mechanism is specifically
or generally a sparse-low-texture solution.

## Next Actions

- Stop mclab1/mclab2 rearm and selector-variant runs.
- Promote mclab1 as the new independent NTNU strict ORB case.
- Retain mclab2, A08, A10, fjord3/fjord4, AFRL, and UVVID as graded boundary evidence.
- In manuscript-facing text, report both the project strict count (`3`) and the stricter all-control
  audit count (`2`); do not collapse them.

## Artifact and Reproducibility Index

- Strict analysis: `analysis-output/analysis-report.md`
- Statistics: `analysis-output/stats-appendix.md`
- Machine-readable roster: `analysis-output/window_roster.csv`, `selector_robustness.csv`,
  `formal_summary.csv`, `texture_denominator.csv`
- Provenance: `analysis-output/provenance.json`
- Primary logs: `../../logs/orb_v23_mclab1_action_search_20260802.md`,
  `../../logs/orb_v23_mclab2_action_search_20260802.md`,
  `../../logs/orb_v23_postinit_search_20260802_final.md`
