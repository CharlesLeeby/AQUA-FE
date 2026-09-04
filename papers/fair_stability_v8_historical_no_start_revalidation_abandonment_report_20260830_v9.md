# Fair-stability v8 historical no-start revalidation abandonment report

Date: 2026-08-30 (Asia/Shanghai)  
Status: **V8 PERMANENTLY ABANDONED; NO RESULT IMPORT INTO V9**

## Scope and disclosure boundary

The formal v8 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v8`.
It was frozen prospectively for 120 planned coordinates.  Exactly one planned
coordinate has a validated terminal receipt.  Analysis remains unauthorized:
`planned=120`, `terminal=1`, `analysis_authorized=false`, and all coordinate-
and result-level details are withheld.  This report intentionally does not
identify any experimental coordinate or terminal algorithm outcome.

## Audited lifecycle facts

Submission 001 was a legal `RESOURCE_BLOCKED_NO_START`.  The resource check
returned the frozen not-ready code, no dispatch claim or estimator start claim
was created, no estimator was launched, and the preregistered attempt was not
consumed.  Its systemd execution, terminal, adoption-claim, and final-adoption
receipts form a valid no-start supervision chain.

After resources were made sufficient, submission 002 manually resubmitted the
same preregistered attempt.  It produced the experiment's sole validated
terminal coordinate, and its submission, start, execution, systemd terminal,
ordinal terminal, adoption-claim, and final-adoption receipts are valid.  No
`attempt_index=2` or replacement attempt was created.

## Abandonment cause

The abandonment is caused by a supervision-history validation defect, not by
the no-start event and not by a disclosed algorithm outcome.  V8 stored the
resource-block proof under submission 001 but later revalidated that historical
proof against the mutable shared attempt root.  Once submission 002 legitimately
published `run_result.json` in that shared root, the validator incorrectly
cross-bound the later result to the earlier no-start submission.  The resulting
false inconsistency prevented submission 003 even though submission 001's
no-start proof and submission 002's terminal proof were individually valid.

The proper historical question is whether submission 001 had started an
estimator at its immutable proof cutoff.  A result produced by a strictly later
submission cannot retroactively change that fact.  V8 did not encode this
submission-local cutoff strongly enough, so continuation under the frozen v8
controls would require changing the validator after a terminal observation.
That is not authorized.

## Permanent decision and evidence handling

V8 is permanently abandoned.  It will not be restored, resumed, repaired in
place, reclassified, or continued.  Its terminal observation, no-start chain,
manifests, generated runtime inputs, caches, claims, logs, receipts, and summary
must not be imported into v9.  They must not enter any denominator, table,
figure, interval, hypothesis test, stability ranking, tuning decision, window
selection, or parameter choice.  They remain control-development provenance
only.

The v8 content tree has been SHA-256/hash-audited for later integrity checking,
but it has not been physically made read-only or otherwise sealed by filesystem
permissions.  This report is deliberately stored outside the formal v8 root in
the workspace `papers/` tree; it does not mutate or purport to seal the v8
namespace.

## V9 correction boundary

V9 is a new prospective experiment with a fresh namespace, experiment id,
backend id, schemas, manifests, generated runtime inputs, attempt matrix,
submission trees, receipts, and summary.  It begins before any v9 estimator
start and imports no v1--v8 result-bearing artifact.

V9 changes only historical supervision-source binding and related control
provenance.  Every no-start proof is submission-local.  A historical no-start
is validated against its immutable submission cutoff, while any later shared
attempt result must be attributed only to its own strictly later submission.
A terminal result must still satisfy its complete terminal branch and cannot
use no-start provenance to bypass dispatch, execution, result, ordinal, or
adoption validation.  The scientific 10-window, 4-arm, 3-repeat design,
schedule, inputs, binaries, model, configurations, budgets, timeouts,
thresholds, estimand, and statistical analysis remain unchanged from the
frozen scientific 10 x 4 x 3 design.
