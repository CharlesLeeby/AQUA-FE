# Fair-stability runtime-exclusivity addendum v11

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V11 ESTIMATOR START**.

Ordered normative bundle, using workspace-relative paths (later items refine
earlier items without rewriting them):

1. `papers/fair_stability_positive_roster_protocol_v1.md`;
2. `papers/fair_stability_vins_supervised_shutdown_addendum_v1.md`;
3. `papers/fair_stability_control_supersession_v11.md`; and
4. `papers/fair_stability_runtime_exclusivity_addendum_v11.md` (this file).

The required ordered provenance bundle is:

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
   and
10. `papers/fair_stability_v10_proc_tail_closure_abandonment_report_20260830_v11.md`.

Every v11 input manifest and backend/control freeze must bind the complete
normative and provenance bundles by absolute path, byte size, and SHA-256.
The frozen v10 control documents remain historical development provenance but
provide no v11 execution authority.

## V11 scope and non-import contract

The output namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v11`.
The experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v11`; the backend id is
`DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V11`; all new schemas and control identities
are versioned v11.

V11 is a fresh full-120 experiment beginning at ordinal 1.  It does not resume
v10 after its aggregate six-terminal fail-stop boundary.  No v10 scientific
outcome or generated artifact is eligible for reuse.  This includes every v10
manifest, generated runtime input, backend or attempt freeze, attempt tree,
prepared cache, dispatch/start/launch artifact, systemd/ordinal receipt, log,
trajectory, monitor/watchdog/lifecycle receipt, summary, or derived value.
No file under the v10 formal root may be imported by copy, link, reflink,
rename, cache lookup, or identity substitution.

The original authoritative roster, source feature bags, raw images, binaries,
libraries, model, configurations, and shared seed may be used only as upstream
sources after fresh validation.  V11 regenerates and freezes its own runtime
inputs and cache.  Each input manifest, backend freeze, attempt matrix, and
summary must contain all ten Boolean result-import assignments
`v1_results_imported=false` through `v10_results_imported=false`, the retained
v9 runtime non-reuse declarations, and these exact v10 runtime-reuse
declarations:

```text
v9_results_imported=false
v9_runtime_namespace_read=false
v9_attempts_reused=false
v9_cache_reused=false
v10_results_imported=false
v10_runtime_namespace_read=false
v10_attempts_reused=false
v10_cache_reused=false
```

`v10_runtime_namespace_read=false` prohibits every v11 freeze, preparation,
execution, adoption, and summary process from reading below the formal v10
runtime root; only the frozen `papers/` provenance reports may carry historical
facts.  `v10_attempts_reused=false` excludes every v10 attempt manifest, tree,
state, submission, and result.  `v10_cache_reused=false` excludes every v10 cache
file, directory, identity, link, and cache-hit decision.  An omitted, true,
duplicated, or non-Boolean declaration fails closed.

Apart from versioned identity, fresh-root provenance, predecessor exclusion,
and the closing-sample correction below, all v10 controls are retained.  The
scientific ten-window, four-arm, three-repeat design; coordinate order; two
HFNet budgets; open-loop setting; estimator inputs and parameters; clocks;
feature budgets; success/partial thresholds; 1800 s estimator limit; resource
definitions and sampling limits; retry policy; estimand; statistical unit;
and analysis are invariant.

## Submit-only systemd user-service supervision

Every formal ordinal is submitted by the frozen v11 supervisor as one unique
transient user service.  The public actions remain:

- `submit`, which submits one exact ordinal/attempt and returns after systemd
  accepts the unit;
- `poll`, which is read-only;
- `adopt`, which validates the complete stopped-unit chain; and
- `authorize-resubmit`, which may authorize only the same unconsumed attempt
  after one of the two proven no-estimator-start outcomes.

The frozen internal service entry and service post commands are not operator
shortcuts.  Direct ordinal-controller mutation, an outer multi-ordinal loop,
automatic submission, and automatic resubmission are forbidden.

Each unit name binds exact ordinal, `attempt_index=1`, a gap-free monotonically
new submission index, and a nonce, and is never reused.  The service remains a
user `Type=exec`, `Transient=yes`, `Restart=no` unit with
`KillMode=control-group`, `KillSignal=SIGTERM`, `SendSIGKILL=yes`,
`RuntimeMaxSec=2400`, `TimeoutStopSec=120`, `RemainAfterExit=no`, and
`UMask=0077`.  Stdout and stderr are separate and append-only.  Scope units,
`nohup`, tmux, `--wait`, `--pipe`, and `--collect` are forbidden.  The systemd
deadline is an infrastructure disaster bound and does not change the 1800 s
algorithm timeout.

The fixed receipt-bound control environment still includes the exact ROS
Noetic Python path
`PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages` and
`PYTHONNOUSERSITE=1`.  Submit and service-entry import probes must pass under
the exact fixed subset.  The supervisor constructs user-manager client calls
with `XDG_RUNTIME_DIR=/run/user/1000` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`.  These are
control-plane selectors, not estimator inputs.  Estimator children retain
their existing explicit arm-specific environments.

The immutable submission claim, service start receipt, controller execution
receipt, `ExecStopPost` terminal receipt, adoption claim, ordinal terminal
receipt where applicable, and final adoption receipt form one identity-bound
chain.  Terminal result, pipeline-invalid, resource-no-start, and dispatch-
blocked-no-start are disjoint adoption branches.  The inner runner's actual
return code remains receipt-bound to `SUCCESS -> 0` and every other admissible
terminal status or `PIPELINE_INVALID -> 3`.  A signal or exception after result
publication is fail-stop rather than an admissible result.

For an algorithm terminal, the final adoption receipt freezes the exact
immediate successor, and validation uses the successor's immutable first-
submission pre-state once it exists.  A pipeline-invalid result may complete
its immutable systemd evidence chain but has a null ordinal terminal receipt
and immediately enters `PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`.

### Submission-local no-start history

The only admissible pre-estimator outcomes remain
`RESOURCE_BLOCKED_NO_START` and
`PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START`.  Each exact submission embeds
an immutable `no_start_provenance` object with v11 schema inside its
`systemd_execution_receipt.json`.  It binds the claim, start receipt, unit,
InvocationID through the surrounding chain, nonce, ordinal, attempt and
submission indices, controller return code 75, pre/post state, and cutoff
proof that no estimator start or result occurred.  The resource branch also
binds `ready=false`, check return code 2, the complete resource receipt, and no
dispatch.  The dispatch-blocked branch binds its exact dispatch execution but
no result identity or return-code binding.

Current no-start validation checks the shared attempt root through that
submission.  Historical validation checks an earlier no-start against its own
immutable submission cutoff and attributes every later shared artifact only
to a strictly later complete submission chain.  A later result cannot
retroactively alter an earlier no-start; an earlier no-start cannot bypass a
later terminal's own dispatch, result, ordinal, or adoption requirements.
Submission directories, claims, authorizations, one-time consumption markers,
and dispatch indices remain gap-free and identity-bound.

After a completely adopted no-start, the only possible manual command is the
v11 supervisor's `authorize-resubmit` for that exact prior submission
directory.  It revalidates the stopped unit/InvocationID, performs and records
the fixed-environment reset, requires a fresh exact `ready=true` resource gate
with return code 0, and publishes one authorization for the strictly next
submission of the same ordinal and `attempt_index=1`.  `submit` consumes that
authorization atomically before publishing the predicted next claim.
Authorization never submits.  A stale, replayed, deleted, orphaned, malformed,
or partly consumed chain fails closed.

This no-start mechanism is not an estimator retry.  No resubmission is
authorized after estimator start, pipeline invalidity, timeout/signal,
manager loss, or any supervision failure.  Attempt index 2 remains forbidden.

The host still has `Linger=no`.  Submit and start receipts bind the current
user-manager/session state.  Loss of the last active login session may stop
the manager; if it does, v11 is abandoned and no retry follows.

## HFNet zero-keyframe post-Shutdown watchdog

The watchdog is identical for both HFNet budgets, all ten windows, and all
three repeats.  Its target polling interval is 0.20 s, phase/gate maximum is
0.25 s, and confirmation requires 30 continuous seconds of the exact ordered
`Shutdown`/target-save/positive-atlas/all-zero-keyframe signature with absent
trajectory files and no complete or partial end-of-saving output.

Before a complete candidate exists, an ordinary longer poll is retained but
does not by itself invalidate the attempt.  During confirmation it resets the
candidate window without signaling or adding a code.  Only after one clean
30 s window may the one-shot atomic signal gate run its two exact identity
proofs.  Both proofs and the final gate interval must be no greater than 0.25
s.  The watchdog may attempt exactly one SIGTERM to the exact revalidated
process group and never an individual signal or SIGKILL.  It adds no grace to
the original 1800 s budget.

The v6 exact-child exit/reap correction and v7 teardown-snapshot correction
remain binding.  Every passive, signalled, or unproven outcome binds exact
launch identity, proof ordering, final child return code, final empty group,
and cross-checks that return code with the result and independent runtime
monitor.  A proven signal remains the algorithm code
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG`; any identity, timing, parser,
receipt, or failed-signal uncertainty remains the pipeline code
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  The HFNet executable, libraries,
model, configuration, and native shutdown behavior remain untouched.

## Continuous intrusion monitor

Every attempt must first pass the unchanged resource gate.  From immediately
after the single supervised `Popen` until the v11 close handshake completes,
the trusted monitor samples:

1. `/proc` at a 0.20 s target and no greater than 0.25 s between probe starts
   for forbidden estimator, ROS, rosbag, frontend-exporter, or compiler
   processes; and
2. `nvidia-smi` at a 0.75 s target and no greater than 1.0 s between probe
   starts for external GPU compute applications.

Every real probe start must lie inside the final coverage interval and starts
within a stream must be strictly increasing.  Pre-coverage, after-end,
out-of-order, empty-stream, error-bearing, or over-gap evidence cannot prove
coverage.  There is no ToDesk name exemption: an ordinary display/remote
process may remain open, but a ToDesk GPU compute application is external.

Ownership remains keyed by exact `(PID, Linux start ticks)`.  A new descendant
is admitted only after a fresh exact live-parent/child ancestry recheck from a
currently owned identity.  Stable-scan children that exit during recheck may
enter known history only under the retained narrow proof; they never become
active by numeric identity alone.  GPU rows may confirm an already owned
identity but cannot create ownership.  An unreadable, reused, or start-tick-
drifting GPU PID is external/unproven under the retained rules.  Cleanup may
signal a group only while the unique frozen leader identity is revalidated;
numeric PID or PGID reuse is never a cleanup target.

### Atomic reservation and evidence-bearing coverage closure

V11 retains v10's corrected atomic reservation handshake.  Its sole new
change addresses the v10 tail-proof defect: the mandatory final ownership
scan is now published as evidence instead of being invisible between the last
ordinary proc sample and coverage end.

The normative monitor state is:

```text
OPEN --request close after exact reap + ownership-empty proof--> CLOSE_PENDING
CLOSE_PENDING --all prior reservations settled + closing proc sample proves empty--> CLOSED
```

There is no reverse transition.  `coverage_end_monotonic_ns` is null in
`OPEN` and `CLOSE_PENDING` and is written exactly once during the transition
to `CLOSED`.  The lock protects the state, stop-new-reservations flag, active
reservation map, sample append/consumption, and close evidence.

After its cadence wait returns and before executing a probe body, each stream
must acquire the lock.  If state is not `OPEN`, it exits without a probe.  If
state is `OPEN`, it creates one opaque internal active reservation binding the
stream and sequence.  Only then may it release the lock, capture the distinct
real probe-start time, and invoke the probe.  It remains active until the
complete normal or exception sample is appended and the reservation is
consumed under the same lock.

An ownership-empty path acquires that same lock.  If still `OPEN`, it changes
state to `CLOSE_PENDING`, records the close request, prevents every subsequent
reservation, and wakes/stops both cadence waits.  It must not commit end while
any reservation is active.  Already reserved probes may finish and publish;
they do not authorize a successor probe.  After the final reservation is
consumed and both loops are unable to reserve again, the monitor starts one
dedicated closing proc ownership recheck.  It captures truthful actual start
and finish timestamps, publishes the row as the final proc sample with the
next gap-free sequence and
`probe_role="coverage_close_ownership_recheck"`, and proves the exact
reaped/empty ownership fact.  Only after that publication is the end time
recorded and state changed to `CLOSED`.

The authoritative sampling times remain the truthful real probe start and
finish.  An internal reservation does not backdate a delayed probe and does
not excuse a start-gap violation.  The active-reservation map and state
transitions are implementation state of the exactly frozen producer; the
receipt schema does not gain per-sample token IDs, reservation timestamps,
consumption timestamps, active-token snapshots, or a reservation-transition
event log.  Correctness is bound by the producer's frozen path/size/SHA-256
identity and deterministic interleaving tests, together with receipt
invariants visible to the common validator.

For each stream, that validator must retain the existing gap-free sequence,
strictly increasing start, maximum-start-gap, error, and coverage checks.  It
must additionally require every sample's actual start and actual finish to
lie inside the inclusive coverage interval and require start no later than
finish.  Proc evidence must contain exactly one closing-role sample, it must
be the last proc row, and no ordinary proc or GPU row may start after close is
pending.  Because `CLOSE_PENDING` blocks new ordinary reservations and
coverage end is deferred until every active token and the closing row have
published, those receipt invariants plus the frozen producer identity are
sufficient; the validator need not reconstruct or log the internal token map.

If a probe raises, its exact exception sample must still be appended and its
reservation consumed, and the retained probe-error rule makes the monitor
unproven.  If a reserved probe or thread fails to settle within the retained
join/finalization bound, full finalization must abort without fabricating a
coverage end.  The runner then records the retained minimal fail-closed
runtime-monitor fallback, including the finalize error; that fallback has no
coverage interval and necessarily makes the coordinate `PIPELINE_INVALID`.
It need not expose the internal token identity.  Deleting, clamping,
backdating, or moving a post-end sample is forbidden.

The v11 correction adds exactly one closing proc evidence row, not a grace
interval, retry, cleanup target, exemption, or estimator-lifetime extension.
Its start-to-coverage-end tail is checked against the unchanged `0.25 s` proc
maximum.  A slow, missing, duplicated, misordered, exception-bearing, or
ownership-unproven closing row fails the monitor closed.  Ordinary sampling
limits, intrusion definitions, ownership, cleanup, and classifications are
unchanged.  A clean receipt still supports only sampled non-observation at
the declared cadence, not a kernel exec-event trace, and runtime measurements
remain ineligible for performance claims.

Deterministic prefreeze tests must force at least these interleavings:

1. the GPU wait releases, its reservation is held, and proc discovers empty;
2. proc requests close while a GPU reservation is active;
3. close becomes pending immediately before a would-be proc/GPU reservation;
4. a reserved probe throws before normal publication;
5. a reserved probe stalls long enough to violate its unchanged start gap; and
6. two concurrent close callers observe the same single monotonic state chain;
7. a slow preceding proc probe plus a valid closing scan would exceed the old
   invisible-scan tail but passes only after the closing row is published;
8. the closing scan itself exceeds `0.25 s`; and
9. the closing scan raises or fails to prove ownership empty.

The tests must prove that cases 1--2 settle before one end timestamp, case 3
starts no ordinary probe, cases 4--5 and 8--9 fail closed, case 6 writes one
end and one closing row, case 7 retains truthful times and passes only when
the unchanged gap contract is satisfied, and no admissible trace contains a
real sample start or finish after coverage end.

## Child lifecycle, classification, and fail-stop

The VINS child wrapper's post-reap residual scan remains Bash-builtin and
process-free; a non-wrapper supervised-group member remains a lifecycle
failure.  Exact camera calibration, process executable/argv, tags, models,
configs, controls, and post-run identities remain reverified.

An external conflict adds `MIDRUN_EXTERNAL_RESOURCE_INTRUSION`; any probe
error, gap, reservation inconsistency, or coverage proof failure adds
`RUNTIME_RESOURCE_MONITOR_UNPROVEN`.  Either produces `PIPELINE_INVALID`,
halts v11, and authorizes no replacement.  The same applies to every
supervision, lifecycle, estimator-identity, configuration/model/control, or
post-run integrity fault.  Algorithm observations in an invalid coordinate
are diagnostic only and never enter a denominator.

Exactly one attempt is preregistered for each coordinate.  The matrix has an
empty retry allowlist, zero replacements, and attempt index 1 only.  A second
attempt or a control change after any v11 estimator starts requires abandoning
v11 and defining a newly versioned prospective experiment.

## Retained cross-arm time/support controls

The HFNet runtime IMU stream must be regenerated inside v11 from the paired
historical source feature bags after proving exact equality of IMU topics,
types, header and record timestamps, six values, feature timestamps, and
merged replay ordering.  Selected images are freshly linked/materialized from
the authoritative raw source, never from the v9 or v10 runtime root.

The unchanged dataset-level offsets are:

- AQUALOC Archaeology: `td = -0.053694112369382575 s`;
- NTNU: `td = 0.0017656238182069367 s`; and
- CIRS: `td = 0.0 s`.

The A07 window-specific recovery offset remains forbidden.  Decimal
round-half-even generation, exact six-value round trip, strict first/last
image bracketing, native binary64 cutoff/predecessor equality, source camera
calibration copy/hash, and per-arm post-run checks remain unchanged.  Native
HFNet and VINS initialization/pre-roll behavior remains part of the system-
level comparison.

Accepted longest-contiguous trajectory support remains inclusive at both
ends.  A reset, solver-risk event, or reinitialization whose next
initialization frame equals the first accepted support frame is inside support
and prevents `SUCCESS`.

## Fresh-v11 freeze gate

Before the first estimator start, pure tests and a temporary-root no-estimator
shadow chain must pass, the formal v11 root must be proven absent, and fresh
v11 `freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix` must run in that order.  The freeze must bind these documents
and the entire ten-report provenance bundle.

The resulting matrix must contain exactly 120 fresh attempt manifests and
zero dispatch/start/launch/result/runtime/terminal/systemd artifacts.  Every
prepared attempt/cache tree must match its exact v11 allowlist and originate
from freshly validated upstream sources, with no v9 or v10 cache or
prepared-tree identity.  All ten predecessor-import declarations and all
v9/v10 runtime non-reuse declarations must be exactly false.
The initial state must be ordinal 1 `READY`.

Thereafter, one unit is submitted at a time; polling is read-only; adoption
waits for `ExecStopPost`; no cumulative outer deadline or multi-ordinal batch
is authorized.

## Frozen estimand and total disclosure embargo

The primary endpoint remains `CLEAN_SUCCESS`.  A terminal `SUCCESS` that is
not clean and every terminal non-success count as zero.  A
`PIPELINE_INVALID` result instead invalidates completion of v11 and is neither
an algorithm zero nor replaceable.

Until all 120 fresh v11 coordinates have validated terminal receipts and all
40 case--arm cells have exactly three terminal repeats, scientific disclosure
is forbidden.  A progress summary may contain only ungrouped process-state
counts and non-outcome design/provenance fields.  It must set
`analysis_authorized=false`,
`outcome_details_withheld_until_all_120_terminal=true`, and keep `rows`,
`case_arm_cells`, `arms`, and all window scores, arm estimates, and contrasts
null.  It may not expose or permit derivation of any run-, arm-, window-,
repeat-, outcome-, failure-, coverage-, initialization-, reset-, trajectory-,
or effect-level result.  Counts cannot support a system ranking.

Only after the complete boundary does the frozen ten-window paired analysis
run.  Repeats remain nested; the primary contrast remains
`learned_klt_vins - hfnet_openloop_675`; the `2^10` whole-window label exchange,
exact multinomial-weighted paired-window bootstrap, fixed secondary contrasts,
Holm gate, and claim limitations remain unchanged.  No v1--v10 outcome enters
any denominator, p-value, interval, table, figure, tuning choice, or stability
conclusion.
