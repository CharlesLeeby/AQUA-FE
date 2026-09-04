# Round 3 NTNU quality-partition correction v2

Date: 2026-08-05
Status: `FROZEN_ADDITIVE_MECHANISM_CORRECTION`
Applies to:

- `2026-08-04--learned-specificity--r03--ntnu-quality-contract.md`
- `2026-08-05--round3-ntnu-evidence-correction-v1.md`

This correction preserves every earlier bag, replay, report, and method lock.
It does not remove the global-q negative result. It resolves its attribution,
removes a replay-configuration ambiguity, and adds a fail-closed execution
contract for future runs.

## 1. Question resolved

The earlier comparison changed approximately 105,000 quality values at once.
It therefore could not distinguish an XFeat-quality failure from a classical
carrier-quality failure. The new factorial holds the complete learned-active
geometry fixed and separately rewrites:

- source 1: KLT-born and KLT-propagated observations;
- source 2: GFTT replenishment birth observations;
- sources 1+2 jointly, while all eight XFeat/source-20 observations retain
  native q.

All three rewritten bags contain 6,300 messages (6,000 IMU and 300 feature
messages). Fail-closed audits require identical topology, byte-identical
non-feature payloads, identical feature headers/points, and equality of every
channel except the predeclared `quality` and `sigma` entries.

## 2. Matched replay result

The native arm was rerun three times with `max_cnt=350`, eliminating the
otherwise inert but formally unmatched `max_cnt=180` field in the original
native replay. All 15 rows use the same single-threaded VINS configuration,
initialize successfully, and have zero linear-solver failures.

The shared G0 support contains 285 poses, 275 one-second RPE pairs, a 28.4 s
span, and 94.6844% coverage. APE and RPE are valid. Values are medians with the
full technical-replay range; scientific `n` remains one development event.

| Classical quality partition | APE RMSE (m) | 1 s RPE RMSE (m) |
|---|---:|---:|
| native source 1, native source 2 | 0.120227 [0.118893, 0.120227] | 0.048943 [0.048363, 0.048943] |
| source 1 q=1 only | 0.111325 [0.111302, 0.112379] | 0.066336 [0.066332, 0.066714] |
| source 2 birth q=1 only | 0.401773 [0.401773, 249.328487] | 0.127408 [0.127408, 33.394720] |
| sources 1+2 q=1, XFeat native | 55.153743 [55.153743, 55.153743] | 10.318418 [10.318418, 10.318418] |

The sources-1+2-q1/XFeat-native trajectories are byte-identical to all three
global-q1 trajectories (`vio.csv` SHA-256
`86cf4eb0997b1d4e2bc2d766676ba154a7981bc340106a776686df63ff636ffe`).
Thus the eight XFeat q values are not required to reproduce the divergence.

The source-2-only arm has two stable technical replays and one severe
trajectory-error branch. It is still numerically evaluable under the frozen
failure taxonomy, so it must not be relabelled a formal hard failure or hidden
by the median. The joint classical-q1 arm produces the high-error branch in
all three technical replays.

## 3. Birth-quality mechanism

The native bag contains 21,424 source-2 observations. Lineage reconstruction
shows that every source-2 observation is the unique first observation of its
track. Of those tracks, 5,182 continue as source 1 and 16,242 remain
singletons. Source 2 is therefore a direct GFTT-birth intervention in this bag,
not a rewrite of the complete GFTT lifetime.

The pinned VINS consumer:

1. clips named `quality` to `[0.05,1]`;
2. requires at least four observations before adding visual factors;
3. uses `min(first_observation_q,current_q)` for temporal factors in both
   optimization and marginalization;
4. multiplies residuals and Jacobians by `sqrt(q)`;
5. does not consume the exported `sigma` channel.

In a static full-bag diagnostic, 3,046 GFTT-born tracks have at least four
observations. Changing their birth q to one increases the residual scale for
22,226 of 34,565 lineage-pair opportunities. These are explanatory lineage
counts, not counts of repeated Ceres residual evaluations in the sliding
window.

## 4. Correct scientific interpretation

The global-q1 trajectory is a real negative result under a counterfactual
quality contract. It is not a learned-q counterexample and does not establish
that XFeat geometry is intrinsically harmful. With learned-active geometry
fixed, this factorial independently demonstrates a classical birth/propagation
quality by VINS-consumer interaction. The broader
geometry-quality-backend crossover is supported only when this result is
combined with the earlier learned-versus-drop 2x2 matrix.

Allowed wording:

> On the NTNU development event, the global-q1 divergence was reproduced by
> changing only classical carrier quality while keeping XFeat quality native.
> GFTT birth-q removal exposed a severe technical branch, and removing both
> classical birth and propagation weighting produced a reproducible high-error
> trajectory.

Forbidden wording:

- learned is generally stable or generally superior to KLT/GFTT;
- GFTT is generally unsafe;
- native q guarantees no divergence;
- one severe branch in three technical repeats is a 33% population risk;
- this selected development event is held-out or confirmatory evidence.

## 5. Operational resolution

Future formal execution uses the versioned guarded v4 entrypoint. The frozen
backend contract pins the named quality channel, quality clipping, anchor/current
minimum, factor scaling, semantic source files, exact VINS binary, exporter,
frontend config, and runtime `vins_safe/floor=0.8/alpha=0.65` mapping with all
source scales equal to one.

Any missing or mismatched contract evidence rejects learned execution. The
fallback is a fresh independent KLT export with constant q=1, labelled
`KLT_BACKEND_CONTRACT_FALLBACK`. It is an operational abstention, cannot be
derived by dropping learned observations from a proposed bag, and cannot enter
the proposed/no-harm numerator. Reused feature bags additionally require a
bag-SHA-bound quality attestation.

The current v3 backend source, binary, exporter, and config match the new
contract, so there is no evidence that the earlier native-q runs used a
different backend. The guard supplies missing enforcement for future runs; it
does not retroactively turn development evidence into confirmation.

## 6. Evidence index

- Strict analysis:
  `ntnu_q_partition_20260805/analysis-output/analysis-report.md`.
- Statistics and replay identities:
  `ntnu_q_partition_20260805/analysis-output/stats-appendix.md` and
  `replay-input-manifest.csv`.
- Figures:
  `ntnu_q_partition_20260805/analysis-output/figures/`.
- Matched G0 summary:
  `/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/g0_all_replays_max350/common_support_summary.json`,
  SHA-256 `cf0e8d9be6b9ec8af0cd17581729e239945b6f221493defd778251e988a88be8`.
- Source-partition bag audits:
  `/mnt/data/AQUA-FE_WS/validation_20260805/ntnu_s83_d30_q_partition_factorial/`.
- Frozen backend contract:
  `backend_quality_contract_v1.json`, contract hash
  `39eaea6d26e6f5a881ef2b17b898cbda75c7aba8087ce447fe897e2fe0bdfce0`.
- Guarded entrypoint:
  `scripts/run_isj_nativeq_contract_guarded_v4.sh`.
- Reused-bag attestation tool:
  `scripts/attest_nativeq_feature_bag.py`.

## 7. Paper-value decision

The counterexample no longer supports rejecting the learned component because
its apparent learned-q attribution was false. It does support a stronger and
more defensible systems contribution: backend quality consumption is part of
the method contract, birth reliability has persistent optimizer influence,
and contract mismatches must fail closed.

This remains insufficient for a learned-superiority claim. The learned method
is still only a restricted candidate justified for held-out multi-sequence
testing; A03 remains a classical-positive counterexample and the confirmatory
sequence-level matrix remains the decision gate.
