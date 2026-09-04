# Research Question Card: expanding action-positive window coverage

Date: 2026-09-04  
Status: `EXPLORATORY_DIRECTION_ONLY`  
Relation to frozen experiments: this note does not modify or supersede
`frontend_same_backend_confirmatory_v3` or any earlier preregistration.

## Research Question Card

Question: Can a frontend-only, geometry-risk-triggered and source-routed
sidecar increase the proportion of outcome-blind windows that improve over KLT,
while preserving the protected KLT stream when inactive?

Type: exploratory / applied

Hypothesis / Inference: The current XFeat churn guard has high protection but
low opportunity recall because GFTT birth reserve measures population churn,
not monocular scale observability. A trigger based on persistent-cell support,
rotation-compensated or non-homographic parallax/bearing diversity, and
candidate incremental geometry could identify numerically full but
geometrically weak KLT windows. Routing a small, source-specific sidecar from
XFeat, SP+LG, or restricted planar LoFTR may cover more failure regimes than a
single XFeat seed rule.

Why it matters: In the 12-window outcome-blind frontend matrix, XFeat-v3 acts
in only 1/12 windows. Even perfect performance in that one active window would
cap attributable positive coverage at 8.3%. A publishable selective-rescue
claim needs both exact inactive fallback and enough outcome-blind active
windows to estimate whether action is usually beneficial.

## Current evidence

Confirmed fact:

- `frontend_same_backend_confirmatory_v3/frontend_runability.csv` contains 12
  PASS frontend cells per arm. XFeat-v3 publishes two learned observations in
  one AFRL Bus window and is byte-identical to KLT in the other 11 windows.
- In the same frozen window roster, SP+LG publishes learned observations in
  8/12 windows (357 observations total). Backend outcomes are Not evaluated.
- Churn-guard v3 retained two known-window gains and closed to exact KLT on the
  known harmful A06 startup and H07 anchor. This is development evidence only.
- Direct transfer of the External-KLT temporal-collapse gate missed both known
  positives and selected the known harmful A06 startup. Temporal-count collapse
  is therefore the wrong trigger family for this mechanism.
- The prior QG marginal-support ranker did not outperform heuristic or random
  selection on the tested real candidate pools. It failed as a candidate
  ranker and must not be relabelled as this proposed opportunity detector.
- Prior A06 evidence shows a restricted planar LoFTR sidecar can help in one
  extreme window, while flooding and generic LoFTR use were harmful or null.

Missing evidence:

- Three-repeat same-backend outcomes for the current 12-window KLT/SP+LG/XFeat
  matrix.
- A frontend-only observability statistic that separates scale-risk windows
  from the harmful low-birth A06 startup without using trajectory outcomes at
  inference time.
- Outcome-blind active windows from multiple sequences after a new rule is
  frozen.
- A matched dense/classical candidate control establishing whether learned
  source is needed for any added coverage.

What would support it:

1. Existing SP+LG-active windows yield multiple valid common-support wins under
   the already frozen backend contract, showing that source/candidate supply
   can increase opportunity coverage without backend changes.
2. On development controls, an interpretable geometry-risk detector identifies
   both retained positives, rejects the harmful A06 startup and H07 anchor, and
   admits candidates only when persistent-cell or parallax/bearing support
   measurably increases.
3. After freezing, all active windows in a new non-overlapping roster are run;
   at least three action-positive wins occur across at least two sequences,
   with no added initialization failure or catastrophic regression. Exact
   numeric acceptance thresholds must be preregistered before those outcomes.

What would falsify it:

- SP+LG action in the existing matrix does not translate into valid trajectory
  gains, indicating that more learned observations alone do not solve the
  bottleneck.
- Geometry-risk signals cannot distinguish known positive and harmful startup
  regimes without result-informed per-sequence thresholds.
- The frozen rule increases action frequency but action-window win rate is not
  better than chance or introduces severe scale/runability regressions.
- A matched classical candidate pool equals or exceeds the learned-source
  result, falsifying learned-specific benefit even if the system mechanism
  remains useful.

Minimal next action: Complete and analyze the already-preregistered 12-window
same-backend matrix before changing any frontend. It provides an immediate
source-supply test because SP+LG is active in 8/12 windows while XFeat-v3 is
active in 1/12. Do not tune v3 from these outcomes. If a new method is needed,
create a separate development version, use an export-only geometry opportunity
audit first, and reserve new untouched windows for confirmation.

Decision: `RUN_EXISTING_EXPERIMENT_FIRST`; keep the geometry-risk source router
as the leading next development hypothesis.

## Candidate mechanism boundary

The proposed direction is an opportunity detector and conservative source
router, not a revival of the failed QG measurement-set optimizer:

1. Protected KLT remains the exported backbone.
2. The inactive path remains byte-identical to KLT.
3. KLT risk is assessed from persistent spatial support and motion geometry,
   rather than total feature count alone.
4. Learned candidates remain hidden through probation and must add spatial or
   bearing/parallax support before admission.
5. At most one source and a very small number of observations are admitted per
   frame; broad replacement and flooding remain prohibited.
6. XFeat targets early persistent seed repair, SP+LG is a moderate-degradation
   candidate source, and LoFTR remains restricted to severe planar low texture.
7. A dense/classical candidate arm is mandatory to test learned specificity.

