# P04 native-q control implementation decision v2

Date: 2026-08-06
Status: `REVISE_IMPLEMENTATION_ACTUAL_V3_PARITY_REQUIRED`
Scientific method retained: `isj-nativeq-legacy-candidate-v3`
Execution guard retained: `isj-nativeq-legacy-candidate-v4-guarded-execution`
Outcome boundary: `FRONTEND_EXPORT_ONLY_NO_VINS_APE_RPE_TRAJECTORY`

## Decision

P04 will instrument the actual frozen native-q v3 learned-seed path. It will
not promote the existing distance/grid v4 pure replayer to the selected
scientific method.

The current v4 replayer is useful interface infrastructure: it proves
fail-closed raw-quality/publication adaptation, independent learned/classical
pools, source-neutral native-q mapping, bounded replay, and exact whole-lineage
drop. It does not implement the v3
`frozen_lineage_early_seed_scan_arbitration`, and it assumes an explicit
`B_active=8` contract absent from v3. Its H07 artifacts therefore remain
interface diagnostics only.

## Required implementation identity

The formal common producer must preserve all of the following from the frozen
v3 method and its environment addendum:

- adaptive CLAHE;
- `every_n=2`, `frame_offset=1`, with skipped frames processed according to
  the frozen runner contract;
- the v3 health trigger, XFeat proposal, LK/KLT probation, correctness,
  termination, and `lineage_early_seed_scan` arbitration rules;
- maximum external-feature budget 350;
- native `vins_safe` quality mapping with floor 0.80 and alpha 0.65;
- the exact publication timestamp, pixel coordinate space, feature ID, source,
  raw frontend quality, and published backend q for every observation.

The same physical attempt must also generate a GFTT pool from the same raw
frames. That pool is independent of learned proposals and may depend only on
the frozen K0 exclusion mask and its own live classical lineages. C_legacy
must consume the same trigger, carrier, correctness, v3 admission branch,
budget, publication, and source-neutral candidate quality role as P_legacy.

## Superseded clauses

This decision applies the August 3 honest incremental route to P04:

- native-q replaces the July constant-q legacy clause;
- P04 is frontend export-only and must not start VINS or read APE/RPE;
- minimal VINS smoke is deferred to the guarded G3/P07 execution path;
- C_legacy is an outcome-blind attribution control, not a randomized or
  unconditional causal control;
- replay count is technical repeat count and never scientific sample size.

The July matching calipers remain the H2 balance target. Matching is performed
after independent pool admission and before any trajectory metric is read. It
may mark a contrast ineligible, but it may not promote, reorder, replace, or
rescue a rejected classical lineage.

## Required fresh probes

Two fresh physical attempts are required for each development-only case:

1. AQUALOC archaeology A03 `[5000,5900)`, every 2 frames, offset 1.
2. NTNU `fjord_1`, `[83 s,113 s)`, camera topic
   `/alphasense_driver_ros/cam0`, every 2 frames, offset 1.

Each attempt must emit compact streaming artifacts for the common context,
both candidate pools, v3 P/C decisions, raw-quality evidence, publication
evidence, lineage lifecycle, exact drop, normalized digests, and input/code
hashes. Attempt 2 must reread the raw source and rerun the producer; replaying
attempt 1's normalized stream is not a physical repeat.

Classical zero action is retained as a supply result and resolves H2 as
`INELIGIBLE_SUPPLY_ZERO`; it is never replaced after observing a backend
outcome.

## PASS boundary

P04 remains `IN_PROGRESS` until a fail-closed validator establishes:

- actual-v3 trigger/admission/sampling/publication parity;
- independent learned and classical pools;
- complete raw-quality and publication coverage with no defaults;
- deterministic normalized and arm-chain hashes across the two attempts;
- exact whole-lineage drop at observation level;
- frozen matching objective, dose/budget balance, and explicit unmatched
  disposition;
- absence of VINS, APE, RPE, or trajectory inputs and outputs.

Only after that PASS may the P04/P05 hashes be merged into the final method
lock and the P06 guarded final builder be invoked once.
