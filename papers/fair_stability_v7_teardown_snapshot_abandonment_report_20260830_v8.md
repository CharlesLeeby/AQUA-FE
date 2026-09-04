# Fair-stability v7 teardown-snapshot abandonment report

Date: 2026-08-30 (Asia/Shanghai)  
Status: **V7 PERMANENTLY ABANDONED; NO RESULT IMPORT INTO V8**

## Scope and decision

The formal v7 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v7`.
It was frozen prospectively for 120 planned coordinates, one attempt per
coordinate and no replacement attempts. Planned ordinals 1--5 produced
pipeline-valid terminal results. Planned ordinal 6,
`a07_10800_11200 / hfnet_openloop_675 / repeat_001 / attempt_001`, produced
`PIPELINE_INVALID` with
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`. The first systemd submission and
its adoption evidence were sealed, but no ordinal-6 terminal receipt exists.
No ordinal 7--120 estimator was started.

In accordance with the frozen zero-retry contract, v7 is permanently
abandoned. Its five terminal observations and the ordinal-6 diagnostic result
must not enter any denominator, confidence interval, hypothesis test, figure,
table, or system ranking. Ordinal 6 must not be reclassified in place, and no
v7 attempt 2, second submission, replacement, replenishment, or continuation
is authorized.

## Observed failure chain

HFNet processed the admitted A07 stream without a successful initialization.
Its stdout reached the ordered zero-keyframe shutdown/save sequence:

1. `Shutdown`;
2. the exact target trajectory-save line;
3. one atlas map; and
4. `Map 0 has 0 KFs`.

The process then printed an uncaught `std::system_error` with
`what(): Invalid argument` and exited by SIGABRT. The exact child was reaped
with return code `-6`; its supervised process group became empty; the
independent runtime resource monitor remained proven and reported no intrusion
or cleanup action.

During that exit, the watchdog's non-atomic `/proc` observation retained the
same sole PID, Linux start ticks, PGID, and session recorded at launch, while
the executable link and command line had already become empty. The process
state field from an earlier read in the same composite observation was still
`R`. V7 accepted this empty-identity teardown shape only when the sampled
state was exactly `Z`. It therefore treated the observation as an identity
mismatch and failed closed before it could record the immediately following
exact `Popen.wait()` reap.

This is a supervision-classification defect, not evidence of a foreign
process, PID reuse, resource intrusion, or altered estimator input. It does
not make the underlying HFNet behavior a v7 algorithm observation: the frozen
v7 rules correctly force `PIPELINE_INVALID` and abandonment.

## Underlying estimator behavior

The zero-keyframe failure is not repaired or hidden. In the frozen HFNet-SLAM
stack, the native EuRoC trajectory-save path can reach map selection with no
map containing a keyframe and then continue into an invalid map access. The
observed uncaught mutex-related `std::system_error` is consistent with that
native zero-keyframe save defect. Independent historical executions of the
same A07 admitted timestamp stream also reached zero keyframes followed by an
abnormal save/termination path. The scientifically relevant upstream event is
that the native open-loop system failed to initialize over the complete
window; once supervision is proven, that remains an algorithm-level system
failure rather than an exclusion from the denominator.

## V8 correction boundary

V8 may change only the teardown observation and its evidence validation:

- an empty executable/command-line observation is only a teardown candidate,
  never a live identity proof and never authority to signal;
- the sole leader's PID, start ticks, PGID, and session must still equal the
  launch receipt, with no extra member, scan/read error, non-empty wrong
  identity, or stable-identity drift;
- acceptance requires the same supervised `Popen` child to be immediately or
  boundedly reaped, with the return code bound to the watchdog, runtime
  monitor, and result receipts, followed by an empty ownership domain;
- a child that remains live, any contradictory evidence, or any unproven reap
  remains pipeline-invalid and fail-closed; and
- no estimator binary, library, model, input, configuration, feature budget,
  timeout, success threshold, roster, repeat count, or statistical method is
  changed.

V8 is a fresh experiment, not a continuation. It must create a new namespace,
new manifests, new generated runtime inputs and cache copies, 120 new
`attempt_index=1` cells, new receipts, and a new summary, starting from planned
ordinal 1. All v1--v7 result-import fields must be false. The estimator stack
and authoritative upstream data may be reused only after fresh byte and
semantic validation.

## Reporting boundary

The v7 partial run is retained solely as an auditable control-development
failure. No claim that one method is more stable than another follows from
v7. Any later stability statement must use a complete, pipeline-valid v8
matrix and retain the original outcome-selected-roster and system-comparison
limitations.
