---
type: results-report
date: 2026-08-04
experiment_line: learned-specificity
round: 3
purpose: ntnu-quality-contract
status: active
source_artifacts:
  - learned_specificity_20260803/analysis-output/analysis-report.md
  - learned_specificity_20260803/analysis-output/stats-appendix.md
  - learned_specificity_20260803/analysis-output/figure-catalog.md
  - learned_specificity_20260803/analysis-output/ntnu-replay-summary.csv
  - learned_specificity_20260803/analysis-output/ntnu-prefix-summary.csv
linked_experiments:
  - ../2026-08-03--aqua-fe--honest-incremental-experiment-plan.md
  - ../2026-07-30--aqua-fe--ieee-sensors-journal-experiment-closure-plan.md
linked_results:
  - learned_specificity_20260803/analysis-output/analysis-report.md
---

# Learned Specificity / Round 3 / NTNU Quality Contract / 2026-08-04

## 1. Executive Summary

This round reconstructed the historical active NTNU Fjord1 `s83` XFeat
microburst, extended it from 10 s to 30 s, and compared learned, same-dose
retrospective GFTT, exact drop, and KLT under one G0 common-support contract.
It also separated global constant-q sensitivity from the quality assigned only
to the eight learned observations.

Under the historical native `vins_safe` quality contract, learned is a valid
event-level positive: median 1 s RPE is `0.038135 m` versus `0.065728 m` for
KLT and `0.091582 m` for same-ID GFTT. Learned is 42.0% lower than KLT and
58.4% lower than GFTT on the frozen technical-replay median. Exact drop enters
two poor trajectory branches with median `5.113238 m`. All arms initialize and
report zero solver failures.

The earlier apparent 30 s learned failure was caused by replacing the complete
quality interface with global q=1, not by learned geometry alone. Changing only
the eight XFeat observations to q=1 leaves RPE at `0.038135 m`, while global
q=1 gives `10.599716 m`. The decision is therefore to retain and freeze the
native-q learned candidate for held-out testing. This one event does not support
a learned-superiority paper claim; A03 remains a valid classical-positive
counterexample.

## 2. Experiment Identity and Decision Context

This is Round 3 of the `learned-specificity` development line. Round 2 showed
that retrospective GFTT strongly beats learned in A03, so the remaining
decision was whether a historical learned-positive event survives a longer,
strictly evaluated window and a matched classical geometry control.

The NTNU window is development-only and appears in the history-exclusion
manifest. It cannot enter the held-out denominator. Its role is method identity
and claim-boundary selection before formal screening.

## 3. Setup and Evaluation Protocol

- Dataset/window: NTNU Harsh Fjord1, absolute start approximately
  `1700604859.677 s`, duration 30 s.
- Historical method: early XFeat proposal, KLT probation, frozen microburst
  admission, 350-feature cap, and native `vins_safe` backend q mapping with
  floor 0.8 and blend alpha 0.65.
- Learned dose: eight observations, IDs 662-664, feature frames 2-4. Learned q
  ranges from `0.865082` to `0.891024`.
- Reconstruction audit: the first 100 feature messages and all interleaved IMU
  messages are byte-for-byte identical to the frozen 10 s positive bag.
- Arms: native-q learned, same-ID/same-slot/same-dose retrospective GFTT, exact
  learned-lineage drop, and independently exported KLT.
- Sensitivity arms: the same learned bag with only source-code 20 changed to
  q=1; and the earlier global-q1 four-arm matrix.
- Replays: three serial, single-threaded VINS-Fusion-origin replays per arm.
  Replays measure technical stability and do not increase scientific n.
- Primary metric: 1 s translational RPE RMSE, lower is better. One 27-arm G0
  mask gives 269 common poses, 259 pairs, 26.8 s span, and 0.893688 coverage;
  both APE and RPE pass. Evo cross-check differences are below 1e-6 m.

The online same-pipeline GFTT proposer produced 136 candidates and 36
confirmations but exported zero observations under the frozen early-supply
gate. It is a zero-action supply result. The plotted GFTT arm is a retrospective
geometry replacement and is not an online detector-isolation causal control.

## 4. Main Findings

### Native quality four-arm result

| Arm | r1 RPE (m) | r2 RPE (m) | r3 RPE (m) | Median (m) |
| --- | ---: | ---: | ---: | ---: |
| Learned | 0.038135 | 0.038135 | 0.038135 | 0.038135 |
| KLT | 0.065728 | 0.065728 | 0.065728 | 0.065728 |
| GFTT same ID | 0.091582 | 0.091582 | 0.091582 | 0.091582 |
| Exact drop | 5.113238 | 12.101863 | 5.113238 | 5.113238 |

Native learned is lower than all comparators in this one event. The exact-drop
contrast is especially strong but unstable: deleting only eight early learned
observations changes the optimizer basin without triggering an explicit solver
failure. This supports event-level backend relevance, not a calibrated causal
effect size for a population.

### Quality sensitivity

| Learned geometry condition | RPE median (m) | Changed observations |
| --- | ---: | ---: |
| Native `vins_safe` q | 0.038135 | 0 |
| XFeat-only q=1 | 0.038135 | 8 |
| Global q=1 | 10.599716 | about 105,000 |

XFeat-only q=1 is effectively unchanged. The global-q1 failure therefore
cannot show that learned observations require downweighting. It shows that the
VINS trajectory is highly sensitive to replacing the complete reliability
interface, including every classical observation.

### Prefix stability

| Prefix | Learned median RPE (m) | KLT median RPE (m) | GFTT median RPE (m) | RPE support |
| --- | ---: | ---: | ---: | --- |
| 10 s | 0.056822 | 0.126004 | 0.172674 | 60 pairs, valid |
| 20 s | 0.038578 | 0.079930 | 0.108472 | 160 pairs, valid |
| 30 s | 0.038135 | 0.065728 | 0.091582 | 259 pairs, valid |

The native method remains learned-positive at every nested prefix. There is no
native-q short-positive/long-negative reversal.

## 5. Statistical Validation

No t-test, Wilcoxon test, p-value, bootstrap population interval, or sign test
is reported. Scientific n is one development event. The three replay outcomes
support a median reducer and expose technical branches; they do not provide
independent degrees of freedom.

The learned, KLT, and GFTT native-q trajectories are highly repeatable. Exact
drop has two distinct technical branches, both poor, and the full range remains
visible. Every replay initializes and has zero recorded linear-solver failures,
showing why trajectory error and solver logs must both remain in the contract.

## 6. Figure-by-Figure Interpretation

### Figure 3: NTNU quality interaction

Panel (a) exists to compare the four native-q arms without hiding the drop
branches. The reader should notice that learned is consistently below KLT and
retrospective GFTT, while deleting the eight observations is catastrophic in
this event. This changes the decision from “learned was defeated” to “retain
learned as a viable frozen candidate.”

Panel (b) exists to localize the global-q1 failure. XFeat-only q=1 overlaps the
native result, whereas global q=1 is more than two orders of magnitude worse.
The supported interpretation is a whole-interface/backend interaction, not a
learned-specific weighting mechanism.

## 7. Failure Cases / Negative Results / Limitations

- Global q=1 produces a reproducible catastrophic learned trajectory, but it
  changes all observations and is not a fair main-method contract.
- Exact drop occupies two poor optimizer branches despite zero solver failures.
- Online GFTT has zero admitted supply. Retrospective GFTT can compare geometry
  at equal dose but cannot establish online learned-versus-classical causality.
- GFTT initial matches are 19.64-68.59 px from learned locations and are chosen
  using full-interval survival and proximity.
- NTNU baseline is a four-camera+IMU pseudo-reference rather than independent
  external ground truth.
- This is a selected development event, scientific n=1, on VINS only.
- A03 remains a valid classical-positive event, so proposer-source effects are
  heterogeneous and no general learned superiority claim is allowed.

## 8. What Changed Our Belief

The evidence no longer supports the claim that classical controls have
invalidated all learned work. A03 proves that learned is not uniformly best;
NTNU proves that learned is not uniformly irrelevant. Together they support an
event-dependent gated-measurement hypothesis and justify keeping a learned
candidate in the formal matrix.

The evidence also changes the interpretation of q. Native reliability is part
of the frozen system contract, but the NTNU learned benefit is not caused by
lower learned q: assigning q=1 only to XFeat does not remove the benefit.

## 9. Next Actions

1. Freeze the historical native-q learned microburst as a development method
   candidate; do not tune it on further held-out outcomes.
2. Run P05 modern learned baseline M under the same native reliability and
   budget contract.
3. Execute P06 KLT/image-only screening, freeze the held-out manifest, then run
   the proposed/KLT/M matrix with sequence-level RPE and normal-window no-harm.
4. Keep A03 and global-q1 as mandatory negative/interaction ablations.
5. Do not resume QG as a headline; only revisit it after the non-QG confirmatory
   matrix is complete.

## 10. Artifact and Reproducibility Index

- Machine rows: `learned_specificity_20260803/analysis-output/ntnu-replay-summary.csv`
  and `ntnu-prefix-summary.csv`.
- Figure: `learned_specificity_20260803/analysis-output/figures/figure-03-ntnu-quality-interaction.{png,pdf}`.
- Joint G0 summary:
  `/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_common_support_nativeq_constq_xfeatq1_all/common_support_summary.json`,
  SHA-256 `11ca3675d851b9fd19178c9e83e4c5ff58e1bf4fb055202c62a6971677d07044`.
- Reconstruction audit:
  `/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_s83_d30_contract/nativeq_reconstruction_audit.json`,
  SHA-256 `ede5fb25d7f15eee5edb0b739d0c0f8c598beeec4cb9cf1bac7279cb8e3ad07e`.
- Learned/KLT bags: SHA-256
  `6a0d38686f823c273dea3fc23495de5f10e3c6b52ad4c43f84f287585434102f` /
  `51fc54e1fae5476a3525610865606433d5ae182a142c333c360c892d70c48ff5`.
- GFTT/drop/XFeat-q1 bags: SHA-256
  `05476264c6df1919f89dc9f9aece34d4e08acd1b78e6260d4ec2b9642bd957d9` /
  `1ff7dd3e153c32dc5f8f746a6f50a678c3456790962ac35bb2f8bbe4bbb096d4` /
  `bc01d208ee56a3b76b417c5a86ff11e0d55fdc84e26465abf3af292def4cb860`.
- Replay directories:
  `/home/ma/AQUA-FE_WS/logs/ntnu_vins/*validation_20260804_ntnu_fjord1_s83_d30_nativeq*_r{1,2,3}`.
- Analysis generator: `scripts/build_learned_specificity_analysis.py`.
- No Obsidian write-back was attempted; this repository has no bound Obsidian
  project knowledge base contract.
