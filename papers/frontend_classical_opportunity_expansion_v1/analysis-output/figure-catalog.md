# Figure catalog

## figure-01-repeat-ranges.png / .svg

- Purpose: show full technical-repeat ranges for both primary accuracy and the guardrail across every activated window.
- Source: case_registry.csv and backend_results.csv, validated against exact per-repeat values before plotting.
- Caption: paired B/C medians with min–max bars, three technical repeats per arm; log metre axes; * denotes severe regression; absent invalid metrics are not zero.
- Key observation: read every outcome and range from the exact numeric table; the robust subset is determined by its registered condition.
- Interpretation: stable separation, guardrail conflict and instability identify distinct mechanism cases; they do not yield a population confidence interval.
- QA: verify labels, log scale, full denominator, no clipped ranges, and missing-case labels.

## figure-02-case-context.png / .svg

- Purpose: compare dose/lifetime and initialization timing descriptors with old A02/Bus controls.
- Source: case_registry.csv and old_positive_comparison_reference.csv, each with its own frozen common support.
- Caption: left published observations versus median APE C-B (symlog); right lifetime in published observations versus reference-relative first-pose delay C-B. Hollow diamonds are old outcome-known controls. No regression fit or causal inference.
- Key observation: use labeled cases to contrast positive, neutral and negative sets, including cases with different initialization timing.
- Interpretation: motivates case-specific utility/risk analysis, not a dose threshold or admission rule.
- QA: old controls remain outside new counts, lifetime units are observations, initialization clocks are not mixed, and unplottable cases remain in the registry.

## Unplottable cases

- coe1_a05_00000_00900: NOT_EVALUABLE; matched_count=27 < frozen minimum 30. Accuracy absent by contract, not deleted.

## Rendered evidence review — 2026-09-08

Figure 1: A04/A07/H02 meet the registered robust subset; A04 is a baseline-numerical-anomaly rescue, whereas H02 starts from a moderate-error baseline. A06 does not beat the frozen range threshold and H03 must retain its two inaccurate C repeats alongside one accurate repeat. A05 is retained without accuracy because 27 common poses < 30.

Figure 2: high dose includes both A04 gain and A01/A03 losses; positive cases have different first-pose delay directions. Dose, lifetime and delay are descriptive context, not demonstrated causal utility. Old A02/Bus are excluded from new counts. H01/H04/H05 share the same right-panel coordinate and a grouped annotation; no measurement was jittered. A05 appears only in the timing panel.

QA completed by rendering both PNGs: full denominator, log/symlog axes, full min–max ranges, invalid-case label, units and old-control distinction checked. Overlapping draft annotations were repositioned with leader lines; original bundle and layout-revision receipt remain in runtime/reporting_drafts. No numerical input or classification changed.
