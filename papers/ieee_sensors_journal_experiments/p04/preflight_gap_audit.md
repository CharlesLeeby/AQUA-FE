# P04 C_legacy preflight gap audit

Date: 2026-08-04
Status: `IN_PROGRESS_PREFLIGHT_ONLY`
Protocol candidate: `isj-nativeq-legacy-candidate-v3`
Outcome boundary: development export-only; no P06 window, learned held-out
outcome, VINS trajectory, APE, or RPE may be read.

## Existing evidence

The development evidence establishes heterogeneous proposer outcomes but does
not close the online classical-control contract:

- A03 `5000-5900` is a valid classical-positive backend event, but its GFTT
  lineage was selected retrospectively using full-interval survival/proximity.
- NTNU Fjord1 `s83,d30` is learned-positive for native-q 1 s RPE, while the
  previously attempted online GFTT arm was zero-action under that frozen gate.
- Those two results reject universal learned superiority and universal
  classical superiority. Neither is an online detector-isolation causal test.

Candidate v3 therefore reserves
`C_legacy_independent_classical_v3` as conditional, but does not yet provide a
P04 PASS artifact or a final runnable arm entrypoint.

## Code audit

The deterministic independent proposer exists at
`uw_frontend/tracking/classical_proposer.py` with frozen GFTT identity,
parameters, stable ordering, and an independent ID range. The P03 master-stream
exporter also maintains independent learned and classical pools.

`scripts/run_ntnu_cqg_classical.py` is not sufficient as the final P04 v3
control. It is an older development adapter that reconstructs the base stream
from a learned feature bag, uses the earlier sidecar/shadow-node path, and does
not register the full candidate-v3 trigger, correctness, native-q, attempt, and
determinism contract. Its outputs may remain development diagnostics only.

## Required P04 contract probe

Before final `method_lock.json` and G3 PASS, a new versioned export-only probe
must demonstrate all of the following on history-excluded development data:

1. learned and classical proposers receive the same raw frames, preprocessing,
   trigger decisions, KLT carrier, probation horizon, F/H eligibility,
   termination rule, maximum budget, exporter, sampling, and native-q mapping;
2. the classical candidate pool is generated independently and never derived
   from, masked by, ranked against, or selected using the learned pool;
3. learned and classical export commands are deterministic across two fresh
   physical attempts, with byte/hash equality or an explicitly normalized
   deterministic audit;
4. trigger opportunity, proposal supply, eligible lineage count, accepted
   lineage count, realized dose, grid position, lifetime, and observation count
   are reported without forcing equal realized counts;
5. a zero-action classical result is retained as a supply result and marks the
   source-attribution contrast ineligible rather than being replaced after
   seeing a backend outcome;
6. no backend replay is started by P04.

## Gate decision

P04 remains `IN_PROGRESS` after this preflight. P06 outcome-blind screening may
continue because it uses only KLT/image-quality metrics, but final arm order,
final method lock, and G3 must fail closed until this export-only control audit
passes. The B2 decision recorded in
`environment_manifest_nativeq_v3_addendum.txt` is a separate G3 blocker.
