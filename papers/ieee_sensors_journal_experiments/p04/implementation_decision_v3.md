# P04 native-q control implementation decision v3

Date: 2026-08-06
Status: `CONTROL_ROUTE_RETIRED_EXACT_DROP_CLOSEOUT_PENDING`
Supersedes: `p04/implementation_decision_v2.md`
Scientific method retained: `isj-nativeq-legacy-candidate-v3`
Execution guard retained: `isj-nativeq-legacy-candidate-v4-guarded-execution`
Machine audit: `p04/v3_control_identifiability_v1.json`
Outcome boundary: `FROZEN_SOURCE_ONLY_NO_BAG_VINS_APE_RPE_TRAJECTORY`

## Structural finding

The frozen native-q v3 implementation cannot support the strict common-K0
P/C control required by the July H2 contract.

The actual v3 path is `run_isj_nativeq_legacy_candidate.sh` through
`run_xfeat_seedchain_arbitrated_eval.sh` and the dataset runner into
`export_vins_features.py` / `HybridKltOrbTracker`. It does not use the older
`xfeat_seed_sidecar_node` / `CausalLineageShadow` path.

After learned probation, `HybridKltOrbTracker` appends confirmed learned tracks
to its internal KLT state. The next frame tracks, replenishes, masks new GFTT
births, and allocates IDs from that mutated state. Replacing XFeat with GFTT
therefore no longer guarantees the same future carrier, birth mask, health
trigger, or proposal opportunity. A numerical divergence need not occur in
every window for the strict shared-carrier contract to fail. Filtering learned
observations from a final bag cannot reconstruct the missing counterfactual K0.

The machine validator binds this conclusion to the frozen v3 source hashes and
also proves that the existing strict v4 replayer is a different method:
distance/grid admission with a new `B_active=8` contract rather than v3's
early-seed/microburst arbitration.

## Decision

The project retains the frozen v3 scientific method and narrows the paper
claim. It does not introduce a post-screening common-carrier v5 method merely
to rescue H2.

- `H2_CONTROL_CONTRACT=NOT_APPLICABLE_CARRIER_FEEDBACK`.
- `C_legacy` is retired from the confirmatory matrix.
- `B2` is retired as a scope decision because the frozen v3 artifacts do not
  expose a selector-independent pre-admission learned stream. Transparent new
  instrumentation could recover such an ablation, but it is not required for
  this route and the paper will not claim a clean admission-only effect.
- `D_legacy` remains conditional on proposed activity because exact removal
  from one already-published P bag preserves the non-dropped stream and can be
  audited observation by observation. It estimates only the direct backend
  exposure effect of published learned-born lineages while holding the
  learned-conditioned carrier fixed; it is not a counterfactual removal of the
  complete learned frontend.
- Main confirmatory arms are `B0`, `B1`, `P_legacy`, and `M`.

This is not an H2 PASS. It is a protocol-level `NOT_APPLICABLE` decision caused
by the selected method's state feedback. The final protocol and paper must
show this disposition explicitly rather than omit a failed control silently.

## Development classical evidence

The A03 classical-positive and NTNU mixed/zero-supply results remain mandatory
development diagnostics. They establish that learned is not uniformly better
and that proposal-source conclusions are heterogeneous. They are not promoted
to randomized, matched, online causal controls and do not enter the held-out
confirmatory denominator.

No fresh A03/NTNU P/C common-producer attempts can cure the structural issue
without changing the method. Existing and new actual-v3 export-only attempts
may be retained as deterministic parity diagnostics only.

## Remaining P04 closeout work

P04 stays `IN_PROGRESS` until all of the following are complete:

1. the identifiability validator and focused regression suite are frozen;
2. actual-v3 whole-lineage drop is validated on development export artifacts,
   including every removed observation and unchanged non-dropped observation;
3. a route-specific protocol addendum removes C/B2 from required P06/P07 slots
   and freezes `D_legacy` applicability before trajectory metrics are read;
4. P05 receives the same fail-closed backend consumer guard used by P;
5. the final method lock records the narrowed claim and the explicit
   `NOT_APPLICABLE` control decision.

Only then may P04 close as
`PASS_WITH_H2_NOT_APPLICABLE_CARRIER_FEEDBACK`, G3 be evaluated, and the P06
guarded final builder run exactly once.
