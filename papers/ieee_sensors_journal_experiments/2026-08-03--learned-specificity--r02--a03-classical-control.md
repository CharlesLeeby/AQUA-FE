---
type: results-report
date: 2026-08-03
experiment_line: learned-specificity
round: 2
purpose: a03-classical-control
status: active
source_artifacts:
  - learned_specificity_20260803/analysis-output/analysis-report.md
  - learned_specificity_20260803/analysis-output/stats-appendix.md
  - learned_specificity_20260803/analysis-output/figure-catalog.md
  - learned_specificity_20260803/analysis-output/comparison-summary.csv
  - learned_specificity_20260803/analysis-output/a03-replay-summary.csv
linked_experiments:
  - ../2026-08-03--aqua-fe--honest-incremental-experiment-plan.md
  - ../2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md
linked_results:
  - learned_specificity_20260803/analysis-output/analysis-report.md
---

# Learned Specificity / Round 2 / A03 Classical Control / 2026-08-03

## 1. Executive Summary

This round tested whether the A03 learned XFeat/KLT lineage changed the VINS
backend relative to a same-ID, same-slot, same-dose retrospective GFTT+LK
replacement. The comparison used a continuous 44.99 s KLT master stream,
three serial VINS-Fusion-origin replays per arm, and the G0 common-support
evaluator.

The A03 event is a valid classical-positive counterexample: median 1 s
translation RPE RMSE was `0.078869 m` for learned and `0.020439 m` for GFTT,
so GFTT was 74.1% lower. GFTT had zero linear-solver failures in all three
replays; learned had failures in all three. This weakens any learned-specific
or learned-superiority headline.

The result does not show that classical online proposal is generally superior.
The GFTT control was selected retrospectively using full-interval survival and
proximity to the learned location. The next decision-critical experiment is a
historical active NTNU Fjord1 `s83,d10` reconstruction with both proposers
active under one online pipeline.

## 2. Experiment Identity and Decision Context

This is Round 2 of the `learned-specificity` development line. It was run to
resolve whether the earlier A06/A08 learned-positive directions could be
interpreted as source-specific backend value, or whether a classical proposer
could supply comparable persistent measurements. The August 3 honest
incremental plan retired QG as a headline path; this round supplies the first
valid A03 counterexample needed to keep that retirement evidence-based.

The window is development-only. It overlaps historical candidate material and
must not be included as held-out confirmatory evidence.

## 3. Setup and Evaluation Protocol

- Dataset/window: AQUALOC archaeology A03, `5000-5900`.
- Master stream: continuous KLT export with 450 feature frames, 40 reference
  poses, and 9092 IMU messages over 44.993 s. Its first 200 frames exactly
  match the frozen `5000-5400` KLT stream.
- Arms: learned XFeat/KLT lineage, retrospective same-ID/same-slot GFTT+LK
  replacement, and KLT/exact learned-lineage drop.
- Matched target: ID `10000000`, frames 10-38, 29 observations; initial GFTT
  distance was 8.951 px. The control used the same dose, timestamps, IDs,
  observation slots, quality, and sigma.
- Replays: three serial replays per arm. Replays are technical repeats, not
  independent scientific units.
- Primary metric: 1 s translational RPE RMSE under G0 common support, lower is
  better. The common support contains 32 poses, 31 RPE pairs, 31 s span, and
  `common_coverage=0.711111`; both APE and RPE pass the frozen validity gates.
- Secondary diagnostics: APE RMSE, output coverage, first-output delay,
  initialization, linear-solver failures, and failure mentions.

## 4. Main Findings

The replay-level RPE values were:

| Arm | r1 (m) | r2 (m) | r3 (m) | Median (m) |
| --- | ---: | ---: | ---: | ---: |
| Learned | 0.078869 | 0.078867 | 0.083620 | 0.078869 |
| GFTT same ID | 0.020421 | 0.020440 | 0.020439 | 0.020439 |
| KLT / exact drop | 0.078769 | 0.078769 | 60.482959 | 0.078769 |

GFTT is 74.1% lower than learned on the frozen median reducer. The learned
median is essentially the KLT median, while the control is both lower-error
and more repeatable. Strict APE medians are 0.671341 m (learned), 0.144138 m
(GFTT), and 0.670397 m (KLT/drop).

The control also used less output delay (4.249 s versus 7.249 s) and higher
coverage (0.904412 versus 0.837736) in the recorded replay artifacts. These
are descriptive because the control is retrospective and the event is one
scientific unit.

## 5. Statistical Validation

No inferential test or population confidence interval is reported. The
scientific unit count is one A03 event; the three replays quantify runtime
stability only. The median reducer is predeclared for the A03 comparison because
the KLT/drop arm has one catastrophic replay, and all replay rows remain visible.

The strict support contract passes: 32 common poses, 31 one-second pairs, 31 s
span, and 0.711111 common coverage. The comparison is therefore valid as an
event-level descriptive RPE result, not as evidence of a general proposer
population effect.

## 6. Figure-by-Figure Interpretation

### Figure 2: A03 classical control

Panel (a) plots every technical replay on a logarithmic RPE axis. It makes the
stable GFTT result, the learned/KLT similarity, and the KLT r3 divergence
visible without compressing them into one favorable average. Panel (b) shows
the corresponding linear-solver failure counts and explicitly annotates the
three zero-failure GFTT replays.

The figure supports a classical-positive A03 event and a method-freezing
decision against learned-specific superiority. It does not support an online
classical superiority claim because the GFTT candidates were chosen with
full-interval information.

## 7. Failure Cases / Negative Results / Limitations

- Learned is not uniformly beneficial: it loses to the matched GFTT control in
  this valid event.
- KLT/drop has one catastrophic replay (`60.482959 m` RPE RMSE), so a mean-only
  summary would hide a relevant stability failure.
- Learned has solver failures in all three replays; GFTT has none. Failure
  counts are backend diagnostics, not independent statistical outcomes.
- The GFTT lineage is a retrospective survival/proximity match, not an online
  causal C-QG control. It cannot isolate detector quality under equal online
  admission opportunity.
- A03 is development-only and scientific `n=1`; it cannot establish
  cross-sequence generalization.

## 8. What Changed Our Belief

The round weakens the hypothesis that learned seeds are necessary or generally
superior. It does not support the opposite blanket claim that learned has no
backend value: A06 remains a valid learned-positive event, and A08 retains a
descriptive learned-positive direction under an ID-preserving control with
invalid strict support.

The supported position is heterogeneous and event-specific: persistent gated
measurements can matter to VINS, but proposer identity is not yet a frozen
contribution. QG remains a development component rather than a paper headline.

## 9. Next Actions

1. Reconstruct the historical active NTNU Fjord1 `s83,d10` profile. Verify that
   learned and GFTT both produce nonzero action under the same trigger, KLT,
   gate, admission, and dose contract before any replay.
2. Run learned, GFTT, KLT, and exact-drop NTNU bags three times serially; apply
   G0 common-support RPE and the same technical-repeat reducer.
3. Freeze the non-QG method identity only after the NTNU direction is known.
4. Keep A03 in the negative-result and claim-evidence audit, not in held-out
   sequence-level inference.

## 10. Artifact and Reproducibility Index

- Strict analysis: `learned_specificity_20260803/analysis-output/analysis-report.md`.
- Statistics: `learned_specificity_20260803/analysis-output/stats-appendix.md`.
- Machine rows: `replay-metrics.csv`, `a03-replay-summary.csv`, and
  `comparison-summary.csv` in the same analysis directory.
- Figure: `learned_specificity_20260803/analysis-output/figures/figure-02-a03-classical-control.png`
  and `.pdf`.
- G0 summary:
  `/mnt/data/AQUA-FE_WS/validation_20260803/a03_5000_5900_common_support_all/common_support_summary.json`.
- Master bag:
  `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_klt_every2_validation_20260803_a03_5000_5900_klt_base/features.bag`.
- Replay directories:
  `/home/ma/AQUA-FE_WS/logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_validation_20260803_a03_5000_5900_{learned,gftt,klt}_r{1,2,3}`.
- Learned master and exact-drop bag SHA-256:
  `cd2509418ef58aa08ff9a30e7f3d60b4190b02b58ac3290916298b71138f2648`.
- Analysis generator: `scripts/build_learned_specificity_analysis.py`.
- No Obsidian write-back was attempted; this repository has no bound Obsidian
  project knowledge base contract.
