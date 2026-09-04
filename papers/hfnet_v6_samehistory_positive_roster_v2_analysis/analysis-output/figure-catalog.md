# Figure catalog

## Figure 1 — Frozen roster runability coverage

- Filename: `figures/figure-01-runability-coverage.{pdf,svg,png}`
- Purpose: show which exact historical windows produced enough continuous HFNet trajectory to enter accuracy analysis.
- Data source: ten immutable `run_result.json` receipts plus per-case adjudication receipts.
- Plotted variables: contiguous trajectory coverage per window; dashed line is the preregistered 70% gate.
- Sample size: 10 outcome-selected windows, one run each.
- Error bars: none; each bar is a deterministic single-run coverage value, not a sample mean.
- Caption requirements: state exactly-once cold start, 70% gate, FAIL=accuracy NA, and outcome-selected roster.
- Key observation: only mclab1 crosses the gate; A09 and mclab2 retain fragments but remain below it; all other windows have zero usable coverage.
- Interpretation: external-baseline accuracy is available for one window only. The figure is a runability audit, not a population success-rate estimate.
- Decision changed: do not average failures with the one valid result; design a prospective unscreened roster before making robustness claims.

## Figure 2 — mclab1 common-support APE/RPE

- Filename: `figures/figure-02-mclab1-common-support-errors.{pdf,svg,png}`
- Purpose: compare HFNet-SLAM, Learned+KLT, and KLT on the sole accuracy-authorized window.
- Data source: formal accuracy v2 result and independent evo crosscheck; the reference is a disclosed non-independent proxy.
- Plotted variables: translation APE RMSE and exact-1-s translation RPE RMSE in metres; lower is better.
- Common support: 139 poses, 129 RPE pairs, 13.8 s, 92.67% grid coverage.
- Sample size: one outcome-selected window, one run per method trajectory.
- Error bars: none because no repeat/seed distribution exists; bars are exact point estimates.
- Caption requirements: name mclab1 s60/d15, common support, proxy-reference role, independent fixed-scale SE(3) alignment, metric direction, n=1 boundary, and no inferential test.
- Key observation: HFNet-SLAM has the lowest point estimate for both metrics; Learned+KLT remains better than KLT.
- Interpretation: the external learned-feature SLAM system has lower point estimates on this window, but one window cannot establish general superiority.
- Decision changed: retain HFNet-SLAM as a strong system-level baseline and expand prospective coverage before manuscript-level ranking.

## Accessibility and export QA

- Okabe–Ito-compatible colors plus hatch patterns provide redundant encoding.
- Bar axes start at zero.
- Vector PDF/SVG and 600-DPI PNG are exported.
- Figures use English labels to avoid font substitution in the manuscript toolchain.
