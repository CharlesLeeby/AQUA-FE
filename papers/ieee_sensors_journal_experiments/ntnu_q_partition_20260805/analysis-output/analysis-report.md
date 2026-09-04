# NTNU quality-partition analysis

Date: 2026-08-05
Status: `DEVELOPMENT_ONLY_STRICT_ANALYSIS`
Scientific unit: one selected NTNU `fjord1_s83_d30` event
Technical repeats: three serial single-threaded replays per arm

## Analysis question

Does the constant-q divergence arise from the eight XFeat observations, or
from changing the quality contract of the classical carrier while learned
geometry is held fixed?

All four factorial cells use the same learned-active feature geometry. Only
the declared `quality` and `sigma` entries differ. The shared G0 mask contains
285 poses and 275 one-second
RPE pairs, with 0.946844 coverage. APE and RPE
are both valid.

## Exact result

| Classical q partition | APE median [min, max] (m) | 1 s RPE median [min, max] (m) |
|---|---:|---:|
| Native classical q | 0.120227 [0.118893, 0.120227] | 0.048943 [0.048363, 0.048943] |
| Source 1 / propagated q=1 | 0.111325 [0.111302, 0.112379] | 0.066336 [0.066332, 0.066714] |
| GFTT birth / source 2 q=1 | 0.401773 [0.401773, 249.328487] | 0.127408 [0.127408, 33.394720] |
| Classical sources 1+2 q=1; XFeat native | 55.153743 [55.153743, 55.153743] | 10.318418 [10.318418, 10.318418] |

Relative to native classical q, the technical-replay median RPE is
35.5% higher when source 1 alone is set to q=1,
160.3% higher when only GFTT birth observations are set
to q=1, and 20982.5% higher when both classical
partitions are set to q=1. The GFTT-birth arm also has a visible third-replay
branch at 33.394720 m; its median alone must
not hide that branch.

The classical-q1/XFeat-native arm and the earlier global-q1 arm have exactly
the same APE/RPE values in all three replays. Thus changing the eight XFeat q
values is not needed to reproduce this divergence.

## Mechanism audit

The frozen native bag contains 21,424
source-2 observations. Every one is the unique first observation of its track;
5,182 tracks later continue as
source 1 and 16,242 are singletons. This
makes the source-2 arm a direct birth-observation intervention rather than a
generic GFTT lifetime rewrite.

VINS accepts tracks with at least four observations and weights each temporal
factor by `sqrt(min(first_q, current_q))`. In the static full-bag lineage
diagnostic, 3,046
GFTT-born tracks meet the four-observation threshold. Setting birth q to one
would increase residual scale for
22,226
of 34,565 lineage-pair
opportunities. This count explains how a one-message birth intervention can
persist, but it is not a count of runtime Ceres evaluations.

## What the counterexample now means

The divergence remains a real negative result under the counterfactual global
constant-q sensitivity contract, which is not the candidate's main contract.
It is not evidence that learned geometry is intrinsically
harmful: the same geometry is stable under native q, source-1-only q=1 is
stable in all three repeats, and the divergence is reproduced without changing
XFeat q. This matrix independently supports a `classical birth/propagation
quality x this VINS consumer` interaction while learned-active geometry is
fixed. Only when combined with the earlier learned-versus-drop crossover may
the broader result be described as a geometry-quality-backend interaction.

This resolves the attribution ambiguity, not the population-level method
question. One development event cannot establish learned superiority,
multi-sequence robustness, or a probability of divergence.

## Claim Candidates

- Claim:
  - Source evidence: fail-closed bag audits, 15-arm G0 evaluation, lineage audit, and VINS source contract.
  - Allowed wording: "On the NTNU development event, global q=1 divergence was reproduced by changing only classical quality; XFeat q was not the cause."
  - Forbidden stronger wording: "The learned method cannot diverge" or "native q guarantees stability."
  - Uncertainty: one selected event, one backend, three non-independent technical repeats.
  - Next check: preserve native-q and the contract guard in the held-out multi-sequence matrix.
  - Decision: keep

- Claim:
  - Source evidence: source-2 lineage identity plus VINS `min(first_q,current_q)` and `sqrt(q)` implementation.
  - Allowed wording: "Birth quality can cap the later influence of surviving classical replenishment tracks."
  - Forbidden stronger wording: "GFTT is generally unsafe" or "birth q is the only stability mechanism."
  - Uncertainty: source-2-only has one severe error branch, while deterministic divergence requires both classical partitions at q=1.
  - Next check: report this as a quality-interface ablation, not a tuned method result.
  - Decision: keep

## Artifact validity

- Three source-partition audits: PASS; all 6,000 non-feature messages are raw-byte equal per bag.
- Replay configuration: all 15 rows use `max_cnt=350` and `multiple_thread=0`.
- Replay health: all 15 rows initialize and have zero linear-solver failures.
- Common support: APE valid and RPE valid.
- Evo cross-check maximum absolute discrepancy: 4.973e-07 m (<1e-6 m).
- Scientific n: 1. No p-value, confidence interval, or population effect size is reported.
