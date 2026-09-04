# Fair-stability prospective control supersession v12

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V12 ESTIMATOR START**  
Parent protocol: `papers/fair_stability_positive_roster_protocol_v1.md`  
Runtime addendum: `papers/fair_stability_runtime_exclusivity_addendum_v12.md`

## Authority, identity, and scientific invariance

The sole formal v12 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v12`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v12`, and the backend id
is `DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V12`.  V12 schemas end in `-v12`; its
backend freeze is under
`vins_dev_nativeq_schedfix_runtimeexcl_v12/backend_freeze.json`.

V12 is a new experiment containing all 120 planned coordinates.  It starts at
planned ordinal 1 and is not a continuation, repair, completion, or retry of
v11.  No terminal count, attempt index, submission index, cache state, or
completion state carries forward.

Relative to the frozen v11 scientific design, v12 changes only the watchdog
state reached after a legal terminal-transition candidate while the exact
`Popen` remains live, plus versioned identity, fresh-root provenance, and
predecessor-exclusion declarations.  The bounded pending-reap correction is
defined below and in the v12 runtime addendum.  It does not alter an estimator
process, estimator input, resource definition, target or maximum interval,
algorithm classification, or scientific estimand.

The following quantities remain exactly invariant:

- ten preregistered windows, four arms, and three repeats, for `10 x 4 x 3 =
  120` planned coordinates;
- the same two HFNet budgets, native open-loop configuration, loop closure
  disabled, frozen VINS arms, and cold-start comparison boundary;
- the same coordinate order and shared randomization seed;
- estimator binaries, linked libraries, model, estimator configurations,
  image and IMU sources, admitted timestamps, replay schedules, time offsets,
  feature parameters, and per-arm explicit environments;
- the same 1800 s estimator budget and 2400 s external systemd disaster bound;
- the same initialization, support, clean-success, partial, reset,
  reinitialization, solver-risk, and failure thresholds;
- the same runtime resource definitions, ToDesk rule, exact-identity ownership
  model, target sampling intervals (`0.20 s` proc and `0.75 s` GPU), and
  maximum start gaps (`0.25 s` proc and `1.0 s` GPU);
- an empty retry allowlist, one preregistered attempt per coordinate, and no
  replacement attempt; and
- the independent statistical unit, primary endpoint, primary and secondary
  contrasts, complete-matrix disclosure boundary, and frozen inference.

The correction therefore cannot be described as tuning, an algorithm patch,
an estimator retry policy, a timeout change, a sampling relaxation, or a new
scientific arm.

## Ordered provenance and predecessor exclusion

The complete predecessor provenance is retained at its original
workspace-relative paths:

1. `papers/fair_stability_v1_runtime_contamination_report_20260829.md`;
2. `papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`;
3. `papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`;
4. `papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`;
5. `papers/fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`;
6. `papers/fair_stability_v6_final_gate_timing_abandonment_report_20260829_v7.md`;
7. `papers/fair_stability_v7_teardown_snapshot_abandonment_report_20260830_v8.md`;
8. `papers/fair_stability_v8_historical_no_start_revalidation_abandonment_report_20260830_v9.md`;
   and
9. `papers/fair_stability_v9_runtime_monitor_termination_race_abandonment_report_20260830_v10.md`;
10. `papers/fair_stability_v10_proc_tail_closure_abandonment_report_20260830_v11.md`;
   and
11. `papers/fair_stability_v11_watchdog_pending_reap_abandonment_report_20260830_v12.md`.

The frozen v11 control documents
`papers/fair_stability_control_supersession_v11.md` and
`papers/fair_stability_runtime_exclusivity_addendum_v11.md` remain historical
control provenance.  They provide no execution authority in v12; every path,
schema, executable, receipt, and identity used by v12 must be bound by the
fresh v12 control/backend freeze.

No v1--v11 result or generated experiment artifact is imported into v12.  In
particular, v11's eight terminal observations and ordinal-009 diagnostic
evidence are excluded together with every v11 manifest, generated runtime
input, prepared attempt tree, HFNet cache, claim, log, trajectory, lifecycle
or watchdog artifact, runtime-monitor receipt, systemd/ordinal receipt,
summary, and derived value.  Nothing below the v11 formal root may be copied, hard-linked,
reflinked, renamed, or treated as a v12 prepared/cache hit.

Authoritative upstream roster definitions, source feature bags, raw images,
original estimator binaries/libraries/model/configurations, and the shared
seed may be reused only as upstream sources after fresh v12 validation.  V12
must regenerate and freshly freeze its own input manifest, runtime image/IMU
materialization, backend/control identities, per-attempt runtime inputs,
prepared cache, 120 attempt manifests, attempt matrix, submission trees,
receipts, and summary.

Every v12 input manifest, backend freeze, attempt matrix, and progress/final
summary must contain all eleven exact result-import declarations plus the
three exact v9, v10, and v11 runtime-reuse declaration sets retained for
provenance:

```text
v1_results_imported=false
v2_results_imported=false
v3_results_imported=false
v4_results_imported=false
v5_results_imported=false
v6_results_imported=false
v7_results_imported=false
v8_results_imported=false
v9_results_imported=false
v9_runtime_namespace_read=false
v9_attempts_reused=false
v9_cache_reused=false
v10_results_imported=false
v10_runtime_namespace_read=false
v10_attempts_reused=false
v10_cache_reused=false
v11_results_imported=false
v11_runtime_namespace_read=false
v11_attempts_reused=false
v11_cache_reused=false
```

`v11_runtime_namespace_read=false` means no v12 freeze, preparation,
execution, adoption, or summary process reads any path below the formal v11
runtime root; historical provenance is taken only from the frozen `papers/`
reports.  `v11_attempts_reused=false` forbids reuse of a v11 attempt manifest,
attempt tree, attempt/submission state, or result.  `v11_cache_reused=false`
forbids a v11 cache file, directory, identity, link, or cache-hit decision.
The retained v9 and v10 declarations have the same literal meaning for those
namespaces. Any missing, true, duplicated, or differently typed declaration
fails the freeze or validation closed.

## Sole control correction: bounded passive pending-reap state

V11 was correctly stopped because a legal terminal-transition candidate was
converted to unproven at the next `0.20 s` target-grid observation, although
the same `Popen` was proven reaped with empty ownership no later than
`0.227639547 s` after the candidate snapshot, inside the already-frozen
inclusive `0.25 s` maximum final-gate duration. There was no
watchdog signal, external intrusion, resource-monitor failure, or systemd
failure. V12 corrects only that watchdog state transition.

When the unchanged teardown predicate proves a legal terminal-transition
candidate and the same `Popen.poll()` is still `None`, the watchdog enters an
explicit `PENDING_REAP` state. Its immutable anchor is the monotonic time at
which candidate proof completed. Its deadline is the earlier of the global
estimator deadline and anchor plus the unchanged `0.25 s` maximum. The
watchdog sends no signal while pending and does not replace that deadline with
the `0.20 s` target cadence.

Only exit and reap of the exact same `Popen` at or before the inclusive
deadline can establish passive exit. The receipt must bind the anchor,
deadline, actual passive wait observations, exact child poll/reap identity,
return code, and final adjudication. A child still live after the inclusive
deadline, a wrong nonempty group, PID/start-tick reuse, identity drift outside
the frozen teardown predicate, a probe error, or an unproven timing/reap chain
fails closed as `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`. This state creates
no retry and does not suppress an algorithm failure: a self-abort reaped
inside the proven window retains its raw nonzero return code for the unchanged
algorithm classification.

### Retained closing ownership recheck

The v11 closing-sample correction is retained without change. The runtime
monitor has one lock-protected termination state with exactly three monotonic
phases: `OPEN`, `CLOSE_PENDING`, and `CLOSED`.  The same lock protects this
state, the stop-new-reservations decision, and the complete set of active
proc/GPU probe reservations.

Before either monitor thread starts any proc or GPU probe, it must acquire
that lock and do exactly one of the following:

1. if the state is not `OPEN`, leave without starting a probe; or
2. create one opaque internal active reservation for the exact stream and next
   sequence, then release the lock and immediately capture the real
   probe-start timestamp before invoking the probe body.

The reservation is active from its in-lock publication until its exact sample
or exact exception sample is appended and the reservation is consumed under
the same lock.  The real probe-start timestamp, not the earlier reservation
timestamp, remains authoritative for the unchanged sampling-gap contract.
Stalling after reservation cannot create grace: it may still violate the
unchanged maximum start gap and fail closed.

Once the supervised child has been reaped and the exact owned process domain
is empty, the closing path acquires the same lock and transitions `OPEN ->
CLOSE_PENDING`.  That transition prevents every new reservation and sets the
thread stop condition.  If a reservation is already active, coverage remains
open while that exact reserved probe resolves.  No later probe may be
reserved.  Only after all active reservations have been consumed and both
sampling loops are incapable of creating another ordinary reservation may the
closing path run its single dedicated proc ownership recheck.  That recheck
captures truthful actual start and finish timestamps, is published as the
final proc sample with the next gap-free sequence and role
`coverage_close_ownership_recheck`, and must independently prove the owned
domain empty.  Only after publication may the path record coverage end and
transition `CLOSE_PENDING -> CLOSED`.

Every reserved probe must resolve to exactly one matching, gap-free sample.
A missing, duplicate, mismatched, out-of-order, exception-lost, or orphaned
reservation; a monitor thread that does not stop within the retained join
bound; an attempt to reserve after `CLOSE_PENDING`; or any probe whose real
start falls outside the final coverage interval makes the monitor unproven
and the coordinate `PIPELINE_INVALID`.  No timestamp may be moved, clamped,
dropped, or relabelled to repair the receipt.

The reservation map and `OPEN -> CLOSE_PENDING -> CLOSED` transitions are
internal state of the exactly frozen monitor producer.  V12 does not add a
per-sample reservation/token identifier, reservation timestamp, consumption
timestamp, or reservation-event log to the receipt schema.  The producer's
frozen path/size/SHA-256 identity, deterministic interleaving tests, and the
receipt's externally checkable timing invariants are sufficient.  Each sample
must retain its truthful actual probe-start and probe-finish timestamps, and
the common validator must require both timestamps to lie inside the inclusive
coverage interval with start no later than finish.  Existing sequence,
strict-start ordering, maximum-gap, error, and coverage checks remain binding.
An exception sample still publishes truthful times and the exception, consumes
its internal reservation, and makes the monitor unproven under the unchanged
error rule.

This retained monitor changes neither ordinary sampling cadence nor
observation content. It includes the v11 evidence-bearing closing proc sample,
not a new grace period, retry, cleanup target, resource exemption, or
estimator-lifetime extension. An ordinary probe already reserved before close may finish;
after close becomes pending, no new ordinary proc/GPU reservation may begin.
The dedicated closing recheck itself remains subject to the unchanged proc
tail limit: if its actual start to coverage end exceeds `0.25 s`, or its
exception, ordering, ownership, or publication chain is unproven, the monitor
fails closed.

## Retained durable supervision and zero-retry policy

Every formal mutating `run-next` is launched through the frozen v12 systemd
user-service supervisor.  Direct controller execution is rejected before
mutation.  The only public actions remain `submit`, read-only `poll`, `adopt`,
and the manual no-start `authorize-resubmit`; internal service entry/post
actions remain frozen.  Each submission has a unique unit name binding exact
ordinal, attempt index 1, monotonically new submission index, and nonce.

The transient service remains `Type=exec`, `Transient=yes`, `Restart=no`,
`KillMode=control-group`, `KillSignal=SIGTERM`, `SendSIGKILL=yes`,
`RuntimeMaxSec=2400`, `TimeoutStopSec=120`, `RemainAfterExit=no`, and
`UMask=0077`, with separate append-only stdout/stderr.  Scope units, `nohup`,
tmux, `--wait`, `--pipe`, and `--collect` remain forbidden.  The fixed control
environment still includes
`PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages` and
`PYTHONNOUSERSITE=1`; the supervisor still pins
`XDG_RUNTIME_DIR=/run/user/1000` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` for user-manager client
calls.  Estimator-child environments remain the frozen arm-specific values.

The start, execution, `ExecStopPost`, two-phase adoption, ordinal terminal,
successor, and immutable identity chains remain mandatory.  The fixed
runner-status map remains `SUCCESS -> 0` and every other admissible terminal
status or `PIPELINE_INVALID -> 3`.  A systemd timeout, signal, user-manager
loss, malformed/missing receipt, cgroup/property/InvocationID drift,
post-publication runner exception, or terminal unit without a valid result is
a non-retryable supervision failure, never an algorithm outcome.

The two submission-local no-start branches remain exactly
`RESOURCE_BLOCKED_NO_START` and
`PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START`.  Their immutable v12
`no_start_provenance` remains bound inside the exact submission execution
receipt and is validated against its submission-local cutoff.  A valid
no-start does not consume attempt 1 and permits only a manual, identity-bound,
same-attempt next-submission authorization/consumption chain.  A later result
cannot retroactively invalidate an earlier no-start, and an earlier no-start
cannot satisfy any later terminal-result requirement.  Authorization never
submits automatically.

The retry allowlist is empty.  `PIPELINE_INVALID` completes only its immutable
systemd evidence chain and then enters
`PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`; it has no ordinal terminal receipt,
attempt 2, replacement, resubmission authority, or same-namespace
continuation.  Every other unlisted pipeline/control failure also abandons
v12 rather than selecting a cleaner run.

The disclosed host limitation remains `Linger=no`.  Formal submission
requires the user manager and an active login session, with `State`,
`Sessions`, and `Linger` receipt-bound.  Loss of the final session/user manager
is a v12 fail-stop abandonment event and never a retry.

## Corrected watchdog and retained ownership and estimator boundaries

The HFNet post-`Shutdown` zero-keyframe watchdog changes only by adding the
bounded `PENDING_REAP` state defined above. It retains the same 0.20 s target,
inclusive 0.25 s confirmation/gate maximum, exact 30 s continuous signature,
one-shot atomic gate, exact leader/process-group identity proofs, and at most
one SIGTERM to the exact PGID. It never sends an individual signal or SIGKILL,
and sends no signal while pending reap. A proven signal remains
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG`; an unproven chain remains
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  The v6 exit/reap distinction and
v7 teardown-snapshot correction remain binding. A proven passive self-exit
retains its exact return code and is never rewritten as watchdog success or
failure. The HFNet binary, model,
libraries, configuration, and native shutdown behavior are not patched.

Runtime ownership remains keyed by exact `(PID, Linux start ticks)` ancestry
first observed while owned.  GPU rows cannot create ownership.  PID/PGID reuse,
unreadable or drifting identity, an unowned supervised-group member, probe
error, start-gap violation, or sampling-contract violation fails closed.
Ordinary ToDesk display processes may remain, but a ToDesk GPU compute row is
external compute with no name-based exemption.  Monitoring remains sampled
exclusion, not a kernel exec trace, and runtime measurements remain ineligible
for performance claims.

The VINS supervised shutdown/lifecycle contract, Bash-builtin residual scan,
camera-calibration copy/hash check, cross-arm IMU equality, dataset-level
camera/IMU offsets, binary64 cutoff proof, and inclusive accepted-support
boundary remain unchanged.  The offsets remain AQUALOC
`-0.053694112369382575 s`, NTNU `0.0017656238182069367 s`, and CIRS `0.0 s`;
the historical window-specific A07 recovery value remains forbidden.

## Fresh-v12 freeze and execution gate

Before the first formal v12 estimator start:

1. freeze the complete v12 normative/provenance document bundle by absolute
   path, byte size, and SHA-256;
2. pass pure tests, including deterministic interleavings where a proc/GPU
   probe reserves immediately before closure, closure begins with a
   reservation active, a probe raises after reservation, and a thread stalls
   between reservation and real start; plus a slow preceding proc probe, a
   dedicated closing sample, a slow closing scan, an exception in the closing
   scan, and two concurrent close callers; and watchdog pending-reap cases at
   `0.227 s`, exactly the inclusive `0.25 s` boundary, beyond `0.25 s`, wrong
   nonempty ownership, PID/start-tick reuse, and both periodic and final-gate
   entry paths;
3. pass a temporary-root, no-estimator shadow systemd chain;
4. prove the formal v12 root absent;
5. run fresh v12 `freeze-inputs`, `freeze-backend`, both `prepare-all` passes,
   and `freeze-matrix`, in that order; and
6. revalidate all eleven predecessor-import declarations and the v9, v10,
   and v11 runtime non-reuse declaration sets, and the complete fresh tree before
   authorizing ordinal 1.

The matrix must contain exactly 120 fresh attempt manifests, one allowed
attempt per coordinate, an empty retry allowlist, and no dispatch claim, start
claim, launch receipt, result, runtime monitor, watchdog/lifecycle artifact,
ordinal terminal receipt, or systemd submission receipt.  Every prepared
attempt/cache tree must be newly produced in v12 from its validated upstream
source and match its exact arm-specific allowlist.  The only admissible initial
state is ordinal 1 `READY`.

Thereafter, submit one exact unit at a time, use polling only for observation,
and adopt only after the immutable `ExecStopPost` terminal chain exists.  No
outer multi-ordinal loop with a cumulative deadline is permitted.

## Complete-matrix disclosure and frozen analysis

No partial v12 scientific result may be disclosed before all 120 fresh
coordinates have validated terminal receipts and every one of the 40
case--arm cells contains exactly three terminal repeats.  Before that boundary,
a progress summary may expose only ungrouped process-state counts (such as
planned total, terminal total, and `schedule_state_counts`) and design or
provenance fields that contain no experimental outcome.  It must set:

```text
analysis_authorized=false
outcome_details_withheld_until_all_120_terminal=true
rows=null
case_arm_cells=null
arms=null
window_level_analysis.window_arm_scores=null
window_level_analysis.arm_estimates=null
window_level_analysis.contrasts=null
```

It must not disclose or permit derivation of run-, arm-, case/window-, repeat-,
or failure-mode-grouped status; clean success; coverage; initialization;
reset/reinitialization/solver risk; trajectory accuracy; win/loss; or effect
statistics.  Ungrouped process-state counts cannot support a stability
conclusion or system ranking.  A pipeline-invalid v12 stops before completion
and does not relax this disclosure gate.

After the complete boundary only, the independent unit remains the ten
`case_id` windows; repeats remain nested within window and arm.  With
`c_wa` clean successes out of three and `q_wa=c_wa/3`, the sole primary
contrast remains `learned_klt_vins - hfnet_openloop_675` and
`Delta=mean_w(q_w,learned-q_w,hfnet675)`.  The two-sided primary diagnostic
still enumerates all `2^10=1024` whole-window label exchanges, and the 95%
interval remains the exact multinomial-weighted paired-window cluster
bootstrap over `C(19,9)=92,378` count vectors.  The two fixed secondary
contrasts and Holm gate remain unchanged.

The outcome-selected-roster and system-level claim boundaries remain
unchanged.  V12 cannot establish a learned-frontend causal effect, an
end-to-end compute-cost advantage, a current paper-final-system result, or a
dataset-wide generalization claim.
