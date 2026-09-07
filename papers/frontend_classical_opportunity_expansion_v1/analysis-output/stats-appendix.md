# Statistical appendix

- Primary contrast: C-all minus B in fixed-scale proper SE(3) APE RMSE; strict 1 s translational RPE is the frozen guardrail. Lower is better.
- Physical-window count: 12; technical attempts: 72; repeats intended per arm per executable window: 3.
- Full case classes: PRACTICAL_GAIN=3, PRACTICAL_LOSS=2, SMALL_OR_UNCERTAIN=6, FAIL=0, NOT_EVALUABLE=1.
- Descriptives: exact_numeric_summary.csv gives all valid per-arm min/median/max and supplementary mean/sample SD. Mean/SD describe technical dispersion and do not replace the median decision.
- Effect sizes: raw median C-B difference (metres) and percentage relative to B per valid window. No scale-aligned primary score, pooled heterogeneous error score or standardized population effect is substituted.
- Intervals: full observed min–max technical ranges; not 95% confidence intervals. Population CI is Not evaluated. because deterministic selection, technical repeats and adaptive batch inclusion do not justify independent sampling assumptions.
- Significance tests: Not evaluated. No t-test, rank test or solver-repeat bootstrap is used to manufacture sample size. Normality testing on three technical repeats is not informative for population inference.
- Multiplicity: one frozen B/C contrast per window and one frozen batch/final rule. Counts describe that complete denominator, not multiplicity-adjusted population discoveries. No post-hoc threshold or subset search.
- Missing evidence: FAIL/NOT_EVALUABLE retained without unmatched APE/RPE. Exact reasons are in window_outcomes.csv; frozen inactive B windows remain NOT_ACTIVATED.
- Proxy and timing: COLMAP is not independent GT. Sensor first-pose delay, reference-relative delay and logged ROS initialization clock are distinct measurements. Candidate residual blocks may reuse observations across optimization calls.
- Reproducibility: provenance.json pins all numerical inputs; common_support outputs retain the evaluator and evo checks; case_supplement_receipt.json verifies labels were not changed.
