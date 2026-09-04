# HFNet-v6 accuracy cache-adjudication supersession v2

Status: **POST-A05 VALIDATOR-INCIDENT DESIGN FREEZE; NO ACCURACY METRICS**

This document does not edit, replace, or reinterpret the outcome-blind
accuracy prestart seal v1.  That seal remains the immutable authority for the
ten-case roster, historical trajectories, integer-nanosecond grids, frame
bridges, support gates, fixed-scale proper-SE(3) metrics, and independent evo
cross-check.  This amendment supplies only a fail-closed interface between an
independent runability adjudicator and a new accuracy controller.

## Incident boundary

The first v2 case, A05, was claimed exactly once and is terminal.  Its official
HFNet log reached the end of the camera window, reset the active map three
times, and reported a final atlas containing one map with zero keyframes.
There is no trajectory or keyframe trajectory.  A05 therefore remains a
runability failure, has accuracy `NA`, remains in the ten-case denominator,
and may never be retried or replaced.

The same attempt also exposed a validator defect.  The run-local TensorRT
timing cache is copied from the frozen shared seed before launch, then is
officially rewritten while TensorRT builds the run-local engines.  The v2
runner correctly freezes the shared seed, ONNX model, binary, library, inputs,
and pre-launch run-local seed, but its post-audit incorrectly requires the
derived run-local timing cache to retain the seed digest.  Consequently an
otherwise scientifically passing run can contain only
`FROZEN_CONTRACT_DRIFT` and `POST_AUDIT_INCOMPLETE` with the sole post-audit
error `FROZEN_CONTRACT_POST_AUDIT:ContractError:DERIVED_FILE_DRIFT:local_cache`.

## Independent adjudication

The cache adjudicator is frozen before any of the remaining nine cases starts.
For every remaining case it publishes a prestart receipt before the estimator
claim and at most one terminal adjudication receipt after the canonical raw
runability receipt.  Publication is no-replace.  A terminal receipt may
normalize the effective status to `PASS` only when all of the following hold:

- the raw status is the canonical terminal `FAIL` and the raw failure-code set
  is exactly the two validator codes above;
- the sole raw post-audit error is exactly the local-cache error above;
- clean execution, one `Popen`, child reap, no retry, and the permanent claim
  contract are independently verified;
- the prepared manifest, case specification, inputs, shared cache, ONNX,
  runtime configuration, v2 runner, claims, and logs are identity-verified;
- the run-local cache began from the frozen seed and only its isolated derived
  post identity is allowed to differ;
- trajectory, keyframe, coverage, contiguous support, initialization, final
  atlas, and reset-boundary gates are independently reparsed and all pass.

The runner is supervised by the frozen zero-keyframe watchdog.  An accuracy
pass requires its canonical receipt to say
`PASSIVE_RUNNER_EXIT_WITHOUT_WATCHDOG_SIGNAL`, with the runner reaped, no
monitoring error, no signal attempt, no delivered signal, and exact pins to
the raw result and watchdog implementation.  A confirmed zero-keyframe
intervention or watchdog supervision error can never be promoted.

Any other raw failure remains `FAIL`.  In particular, execution failure,
missing or invalid trajectory, insufficient support, an empty atlas, or an
unresolved reset can never be promoted.  No support coordinate, APE, RPE,
evo result, winner, or ranking is computed by adjudication.

## Accuracy-controller delta

The published accuracy supersession v2 is a delta-only seal.  It identity-pins
the immutable parent seal v1, unchanged evaluator v1, base controller core,
active controller v2, independent cache adjudicator, zero-keyframe watchdog,
the cache-governance addendum, watchdog protocol, this protocol, A05's
terminal evidence, and the nine still-pristine prepared attempts.  It
introduces new canonical cache-adjudication, execution-lock, and
accuracy-analysis namespaces.  The old v1 namespaces remain unused.

For an effective pass, the v2 execution lock pins both the immutable raw
runability receipt and the independent adjudication receipt.  `freeze-lock`,
`check`, and `run` revalidate the delta seal, raw receipt, adjudication receipt,
prestart receipt, code identities, and all ordinary scientific inputs.  Those
files join the same pre-metric and pre-publication TOCTOU ledger used for the
trajectory, historical inputs, frame contract, and evo environment.  The
unchanged evaluator v1 is invoked only after the v2 controller has issued this
stronger authorization boundary.

Merely copying the adjudicator identity into a fabricated `PASS` JSON is not
sufficient.  At every controller boundary, the exact pinned adjudicator's
read-only published-receipt API reparses the raw artifacts and requires the
published receipt, apart from its validated publication timestamp and global
lock evidence, to equal a fresh canonical recomputation.  The delta builder
also holds the roster's exclusive `.gpu_serial.lock` across two identical
pristine-state builds and the no-replace publication (or dry-run output).

The delta seal is explicitly post-A05 and pre-remaining-nine.  It does not
claim that no HFNet outcome was seen.  It retains the original outcome-blind
metric design without changing any threshold, population, transform, or
numeric method.
