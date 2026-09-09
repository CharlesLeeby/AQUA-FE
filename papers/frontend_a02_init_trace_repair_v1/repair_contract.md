# Classical-observation preservation guard v1 — bounded safety repair

Frozen: 2026-09-09, after all six diagnostic replay receipts and before guard
implementation/testing. This is an independent safety boundary, not a new
learned method or a revision of EXP-20260906-012's failed expansion decision.

## Evidence and single change

Registered deletion alone harms A02. All three new KLT traces accept the eighth
alignment attempt, all three deletion traces the fourth. Rejections have negative
linear scale, not out-of-tolerance gravity. The original independent KLT output
is the protected contract; a track's age is not an exemption from protection.

Implement one final-message guard: every baseline (ID, camera) observation,
including a birth, must remain with bit-identical coordinates/channel values
and retained order. Header/channel schema and message clocks must match. Total
count remains <=350. Deletion, alteration, reordering, malformed observations,
or cap violation triggers current-frame KLT fallback and latches KLT fallback
for the rest of the run. The latch uses current/past data only, not future
lifetimes, baseline initialization time, proxy errors or sequence identity.

An otherwise valid additive proposal in genuinely unused baseline capacity is
not changed. This does NOT establish that added observations cannot harm VINS.
The guard protects against the identified destructive operation, not arbitrary
backend regression. No candidate source/threshold/geometry, first-admission
horizon, backend code/YAML/parameters or budget is changed.

This restores the existing no-deletion safety principle, not a novel solution
to increase positive-window rate. It is an explicit separate entrypoint around
already frozen proposed outputs; original exporters/results remain available
for research and are not silently rewritten. The current default noharm_v4
already requests mirror preservation; it is not renamed as a new result.

## Fixed validation and stopping

Test the guard on synthetic messages (identity, birth deletion, field mutation,
camera/ID, order, cap, genuine free capacity, header/schema, latched fallback).
Then process the existing six development windows in their original order,
XFeat and SP+LG per window: twelve paired-input guard evaluations, not twelve
new frontend tracking runs. All frame/non-feature/timestamp checks remain in
the denominator. Use exact original bags and verify input receipts/hashes.
The first A09 pair is the export-only functional probe and counts toward twelve.

Write separate guarded output bags. If every returned serialized message is
identical to KLT, store an exact byte copy of that KLT bag and explicitly map
to its original three identity-valid backend results. This final byte-copy
optimization changes only the container, never the causal per-frame decision.
No duplicate KLT replay and no new matched control for an exact-zero-action bag.
Check bag/YAML/camera/node/library/environment/trajectory receipts before mapping.

If any guarded bag retains actual additions, record ACTION_REMAINS_NOT_EVALUATED:
no no-harm conclusion or baseline reuse for that cell; an independently frozen
matched-control/backend test would be required. No automatic extra variant.
This safety-repair validation is not a win-seeking experiment. Report every
gain sacrificed relative to the unguarded version and do not promote all-TIE
fallback as a successful learned method. No new-window extension.

Success for this repair means the identified destructive observations cannot
reach the guarded output. Retaining A09/Bus benefit is a separate measured
question, not presumed. If the result is KLT equality, stop at SAFE_FALLBACK_ONLY.
