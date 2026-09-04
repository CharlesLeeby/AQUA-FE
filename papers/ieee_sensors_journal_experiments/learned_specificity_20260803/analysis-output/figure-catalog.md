# Figure Catalog

## Figure 1

- Filename: `figures/figure-01-matched-control-rpe.png` and
  `figures/figure-01-matched-control-rpe.pdf`
- Purpose: show the strongest valid A06 event-level contrast and the repeated
  A08 direction after same-ID control construction.
- Data source: `replay-metrics.csv` and the two G0 JSON summaries under
  `/mnt/data/AQUA-FE_WS/validation_20260803/`.
- Panel (a): A06 1 s RPE RMSE for learned, same-frame classical replacement,
  KLT, and frame-29 learned removal. The 21 common-support pairs are valid for
  RPE; APE is not valid.
- Panel (b): three A08 learned-to-same-ID-GFTT technical replay links. The five
  common-support pairs are explicitly descriptive only and scientific n=1.
- Error bars: none; points/lines are individual technical replay values, not
  confidence intervals.
- Interpretation: learned is lower in the A06 event and in every A08 technical
  replay, while the figure does not support a population or superiority claim.
- Decision implication: retain the learned branch as a backend-relevant
  hypothesis, but stop the QG/headline promotion until independent windows and
  canonical contracts are complete.
- Caveat: the A08 control is retrospective, full-interval-survival-conditioned,
  and proximity-matched; it is not an online randomized C-QG arm.

## Figure 2

- Filename: `figures/figure-02-a03-classical-control.png` and
  `figures/figure-02-a03-classical-control.pdf`
- Purpose: show the A03 valid classical-positive result and backend stability
  across all technical replays without hiding the KLT catastrophic run.
- Data source: `a03-replay-summary.csv` and
  `/mnt/data/AQUA-FE_WS/validation_20260803/a03_5000_5900_common_support_all/common_support_summary.json`.
- Panel (a): strict 1 s RPE RMSE for learned, same-ID GFTT, and KLT/exact drop;
  the logarithmic axis exposes both the stable GFTT result and KLT r3 divergence.
- Panel (b): linear solver failure counts per replay. Zero-height GFTT bars are
  annotated with `0`.
- Error bars: none; each point/bar is a technical replay, not an independent
  experimental unit or confidence interval.
- Interpretation: in this one valid development event, retrospective GFTT is
  lower-error and more stable than the learned lineage at the same published
  dose, while learned is approximately equal to the KLT median.
- Decision implication: do not freeze a learned-specific paper claim; run the
  historical active NTNU same-pipeline control next.
- Caveat: scientific n=1; the GFTT candidate is selected with full-interval
  survival and learned-location proximity, so this is not an online proposer
  superiority result.

## Figure 3

- Filename: `figures/figure-03-ntnu-quality-interaction.png` and
  `figures/figure-03-ntnu-quality-interaction.pdf`.
- Purpose: show the valid NTNU learned-positive event under the historical
  native quality contract and separate source-specific q sensitivity from the
  invalid stronger interpretation of the global-q1 failure.
- Data source: `ntnu-replay-summary.csv` and
  `/mnt/data/AQUA-FE_WS/validation_20260804/ntnu_fjord1_s83_d30_common_support_nativeq_constq_xfeatq1_all/common_support_summary.json`.
- Panel (a): native-q strict 1 s RPE RMSE for learned, same-ID retrospective
  GFTT, exact drop, and independently exported KLT. The logarithmic axis keeps
  the two poor exact-drop branches visible. All points share 269 common poses
  and 259 exact 1 s pairs.
- Panel (b): identical learned geometry under native q, XFeat-only q=1, and
  global q=1. Points are technical replays; horizontal bars are medians. No
  error bar or interval is shown.
- Error bars: none. Three points are technical replay outcomes for one event,
  not independent samples or confidence intervals.
- Interpretation: native-q learned is lower than KLT and retrospective GFTT in
  this event. XFeat-only q=1 is indistinguishable from native learned, whereas
  global q=1 diverges; the global failure is therefore a complete reliability-
  interface interaction, not evidence that learned observations require lower q.
- Decision implication: retain a learned-seeded native-q method candidate for
  held-out testing, keep global q=1 as a backend sensitivity ablation, and do
  not promote learned superiority before sequence-level confirmatory evidence.
- Caveat: scientific n=1 and development-selected. Online GFTT has zero supply;
  the plotted GFTT geometry replacement is retrospective, full-interval-
  survival-conditioned, and not an online detector-isolation causal arm.
