# Fair-stability prospective control supersession v9

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V9 ESTIMATOR START**  
Parent protocol: `papers/fair_stability_positive_roster_protocol_v1.md`  
Runtime addendum: `papers/fair_stability_runtime_exclusivity_addendum_v9.md`

## Identity and scientific invariance

The v9 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v9`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v9`, and the backend id is
`DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V9`.  V9 schemas end in `-v9`; the backend
freeze is under
`vins_dev_nativeq_schedfix_runtimeexcl_v9/backend_freeze.json`.

V9 changes only the binding of historical supervision evidence,
submission-local `no_start_provenance`, versioned provenance and identity,
control-plane transport, and the progress-summary disclosure gate.
The ten windows, four arms, two HFNet feature budgets, three
repeats, 120-coordinate order, estimator binaries and libraries, model,
configs, image/IMU inputs, replay schedules, time offsets, feature parameters,
success/partial thresholds, 1800 s estimator budget, statistical unit,
primary endpoint, contrast, and inference are unchanged.  The retained
safety rule is that the retry allowlist is empty: every pipeline-invalid
attempt stops v9 for manual review, and no replacement attempt is authorized.

Until all 120 preregistered coordinates have validated terminal receipts, any
v9 progress summary may disclose only process-state counts that are not grouped
by `arm`, `case_id`/window, or repeat (including the planned total, terminal
total, and `schedule_state_counts`) plus design and provenance fields that
contain no experimental outcome.  It must set `analysis_authorized=false` and
`outcome_details_withheld_until_all_120_terminal=true`; `rows`,
`case_arm_cells`, `arms`, `window_level_analysis.window_arm_scores`,
`window_level_analysis.arm_estimates`, and
`window_level_analysis.contrasts` must all be `null`.  It must not disclose or
permit derivation of run-, arm-, or window-grouped status, clean success,
failure mode, coverage, initialization, reset/reinitialization/solver risk,
win/loss, or effect statistics.  Process-state counts must not be used for a
stability conclusion or system ranking.  This gate may be released, and the
frozen analysis authorized, only after all 120 coordinates are terminal and
each of the 40 case--arm cells contains exactly three terminal repeats.

The complete predecessor provenance is retained under its original
workspace-relative paths:

- `papers/fair_stability_v1_runtime_contamination_report_20260829.md`;
- `papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`;
- `papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`;
- `papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`;
- `papers/fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`;
  and
- `papers/fair_stability_v6_final_gate_timing_abandonment_report_20260829_v7.md`;
  and
- `papers/fair_stability_v7_teardown_snapshot_abandonment_report_20260830_v8.md`; and
- `papers/fair_stability_v8_historical_no_start_revalidation_abandonment_report_20260830_v9.md`.

No v1, v2, v3, v4, v5, v6, v7, or v8 result, manifest, generated runtime input,
attempt cache, claim, log, receipt, or summary is imported into v9.  The input
manifest, backend freeze, attempt matrix, and summary must each contain all eight
exact assignments: `v1_results_imported=false`,
`v2_results_imported=false`, `v3_results_imported=false`,
`v4_results_imported=false`, `v5_results_imported=false`,
`v6_results_imported=false`, `v7_results_imported=false`, and
`v8_results_imported=false`.

## Mandatory systemd user transient service

Every formal mutating `run-next` is launched through the frozen
`run_fair_stability_systemd_supervisor_v9.py`.  Direct controller execution is
rejected before mutation.  The supervisor provides only:

- `submit`: submit one exact ordinal/attempt and return after systemd accepts
  the service;
- `poll`: read-only observation;
- `adopt`: validate the complete stopped-unit chain and publish adoption; and
- frozen internal `service-entry` and `service-post` commands.

Each unit name contains exact ordinal, attempt index, monotonically new
submission index, and a nonce; a name is never reused.  The immutable
submission claim binds the exact pre-submit state and attempt root.  A second
submission is forbidden until the prior submission has a valid final adoption
receipt.

The transient service contract is:

- user service, `Type=exec`, `Transient=yes`, `Restart=no`;
- `KillMode=control-group`, `KillSignal=SIGTERM`, `SendSIGKILL=yes`;
- `RuntimeMaxSec=2400s`, strictly later than the unchanged runner budget;
- `TimeoutStopSec=120s`, `RemainAfterExit=no`, `UMask=0077`;
- separate append-only stdout/stderr paths;
- fixed, receipt-bound minimum environment subset, including the exact ROS Noetic Python path
  `PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages`, disabled user-site
  loading via `PYTHONNOUSERSITE=1`, and absolute control argv; and
- no scope, `nohup`, tmux, `--wait`, `--pipe`, or `--collect`.

The unit entry verifies the live unit properties, InvocationID, MainPID, exact
cgroup membership, frozen controller/supervisor identities, and exact
ordinal/attempt before invoking the controller.  It publishes a start receipt
first.  Host and service-entry preflights must prove that `/usr/bin/python3`
imports `rosbag` from that exact path under the fixed subset; both the claim
and start receipt bind that subset byte-for-byte.  Other user-manager
variables are outside this subset, while estimator children retain their
already frozen explicit per-arm environments.  `ExecStopPost` is
an explicit argv, not a shell command or `%n`
specifier, and publishes the terminal tuple while the successful transient
unit is still queryable.  Post-hoc `systemctl show` is not sufficient because a
successful transient unit may unload immediately.
The supervisor itself pins `XDG_RUNTIME_DIR=/run/user/1000` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` for all user-manager
client calls.  These are control-plane connection values, not estimator
inputs, and prevent ambient-shell differences from imitating manager loss.

The adoption chain is two phase.  `adopt` first publishes an adoption claim;
for a terminal algorithm result the ordinal controller then publishes its
terminal receipt bound to that claim; finally the supervisor publishes an
adoption receipt bound to both.  The claim and final receipt have exact field
sets, ordered UTC timestamps, `timeout_or_signal_observed=false`, and
`estimator_retry_authorized=false`.  The outcome closure is disjoint:
terminal requires controller return code 0, the exact submission-local
dispatch/result, `TERMINAL_UNADOPTED`, and a non-null ordinal receipt;
pipeline-invalid requires return code 0, the exact result, the zero-retry
fail-stop state, and a null ordinal receipt; either no-start requires return
code 75, unchanged `READY`, and a null ordinal receipt.  No other controller
outcome is adoptable.

For a terminal, the final receipt freezes the expected immediate successor:
the next scheduled coordinate in `READY`/`NEEDS_PREPARATION`, or `COMPLETE`
after ordinal 120.  The supervisor writes the final receipt and immediately
recomputes the successor.  Historical validation uses the next ordinal's
immutable `submission_001` pre-state once that submission exists, so future
progress cannot retroactively invalidate an earlier successor snapshot.
Common state and summaries accept a terminal cell only when this complete
chain remains identity-valid.  A pipeline-invalid result may retain the first
submission's systemd adoption evidence, but it immediately enters the
non-submittable zero-retry fail-stop state.

### Submission-local no-start proof

V9 corrects the historical revalidation of either of the only two admissible
pre-estimator outcomes: `RESOURCE_BLOCKED_NO_START` and
`PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START`.  The proof is the immutable
`no_start_provenance` object embedded in that exact submission's
`systemd_execution_receipt.json`; it is not a separate file.  The object has
schema `aqua-fe-fair-stability-systemd-no-start-provenance-v9`.  The execution
receipt is in turn identity-bound by the terminal receipt, adoption claim, and
adoption receipt, so the proof remains submission-local through the complete
systemd chain.

Both branches bind the exact submission claim and start receipt, unit,
InvocationID (through the surrounding execution chain), nonce, ordinal,
attempt index, submission index, controller return code 75, pre- and
post-controller ordinal states, and cutoff observations proving that neither
`start_claim.json` nor `run_result.json` existed and that no estimator-start
authority was present.  In the resource branch, the proof additionally binds
the complete resource-gate receipt, check return code 2, `ready=false`, and
the absence of a dispatch execution.  In the pre-start dispatch branch, it
instead binds this submission's immutable `controller_dispatch_execution_NNN`
identity; that receipt must contain no result identity, status, parse error,
or result/return-code binding.  A no-start submission does not consume the
preregistered attempt and does not enter an algorithm denominator.

Validation has exactly two mutually exclusive branches:

1. **Current no-start branch.**  If no later submission has been accepted for
   the coordinate, the immutable submission-local proof must validate and the
   shared attempt root must still match the complete accepted submission
   history through that submission.  A resource no-start owns no dispatch
   execution of its own; the shared root may retain only the gap-free dispatch
   claim/execution/stdout/stderr artifacts uniquely bound to earlier accepted
   pre-start no-start submissions.  A pre-start dispatch no-start additionally
   owns its exact next such dispatch.  Neither case permits start, result, or
   runtime evidence without a strictly later result-producing submission.
2. **Historical no-start branch.**  If a strictly later submission has been
   accepted for the same ordinal and attempt, the earlier proof is validated
   only against its own submission-local identities and cutoff snapshots.  A
   later shared-attempt `run_result.json` or other later-submission artifact is
   neither required to be absent nor eligible to be bound into the earlier
   proof.  Every such later artifact must instead be attributable to one
   strictly later, identity-valid submission chain.  Dispatch-execution and
   stdout/stderr indices must be gap-free; orphaned claims, executions, logs,
   start/results, or runtime artifacts fail closed.

All submissions for one coordinate form a gap-free sequence beginning at
`submission_001`.  Directory index, claim index, ordinal, attempt, attempt
root, and the ordinal/attempt/submission fields encoded in the unit name must
agree.  Every later submission must bind the one authorization produced for
that exact next index; deletion of the later submission chain while leaving
shared start/result artifacts therefore fails historical validation.

The following invariants are strict.  A resource no-start proof is invalid if
its own submission reached dispatch.  Either kind is invalid if its own
submission reached estimator start, if any bound identity or return-code pair
drifts, or if a purported later artifact cannot be assigned to a strictly
later submission.  Later results can never revise, erase, or invalidate a
previously complete historical no-start proof merely by appearing in the
shared attempt root.  Conversely, an algorithm terminal can never use a
historical or current no-start branch to bypass its own dispatch-execution
receipt, result identity, ordinal terminal receipt, or full systemd adoption
chain.  A terminal submission must validate solely through the terminal-result
branch for that exact submission.  Every non-no-start outcome must carry an
explicitly null `no_start_provenance` object.

After either proven no-start, continuation is a manual control action.  The
operator must invoke exactly:

```text
/usr/bin/python3 /home/ma/AQUA-FE_WS/scripts/run_fair_stability_systemd_supervisor_v9.py authorize-resubmit --submission-dir <absolute-prior-submission-dir>
```

The command first revalidates the complete final no-start adoption and the
exact stopped unit/InvocationID; executes the exact fixed-environment
`systemctl --user reset-failed UNIT`; accepts either the same inactive unit or
an explicitly unloaded/not-found unit afterward; then, before any new
`systemd-run`, executes the coordinate's runner `check`.  The check must return
code 0 and a complete 20-field `ready=true` resource gate whose raw GPU stdout,
parsed compute rows, attempt manifest, and VINS port (or HFNet null port) are
internally consistent.

Only then is
`resubmit_authorization_for_submission_NNN.json` published in the prior
submission directory.  It binds the ordered UTC observations, reset command
and logs, full resource gate, unchanged `READY` state, same ordinal and
`attempt_index=1`, and the strictly next submission index.  The later
`submit` command, while holding the submit lock, revalidates all earlier
adoptions, re-reads the current state/preflight/context, and rejects an absent,
tampered, stale, or already consumed authorization.  It constructs the exact
new submission claim bytes in memory and predicts their path/size/hash, then
atomically publishes
`resubmit_authorization_consumption_for_submission_NNN.json` in the prior
submission directory before creating the new submission directory or claim.
This exact-field consumption marker binds the authorization identity, prior
claim, predicted new-claim identity, new directory/unit/index, ordinal,
`attempt_index=1`, attempt root, and an ordered UTC consumption time.  The
marker is strictly re-read; only then are the exact predicted claim bytes
published and both objects re-read.  `systemd-run` is unreachable until all of
these checks pass.

Every submission after index 1 requires exactly one such marker in the
immediately prior directory.  A missing, extra, malformed, or identity-drifting
marker fails history validation; a marker with no successor directory is an
auditable consumed ticket and also fails closed.  Thus deleting only the later
resource-no-start directory cannot make its authorization reusable, and
deleting only the marker cannot leave the later claim valid.  If execution
fails after marker publication--including claim publication failure or a
`systemd-run` exception--the marker and any directory/claim already published
are never cleaned up: the authorization remains consumed and the experiment is
fail-stop.

This is a filesystem evidence contract, not an external anti-rollback ledger.
It closes deletion or tampering of either side while the other retained v9
evidence remains.  It does not claim detection if an actor able to rewrite the
experiment root coordinates deletion of the marker, successor directory, and
all causally later evidence; that stronger threat model requires a privileged
append-only or remote monotonic authority outside this tree.  Authorization
never calls `submit`; there is no automatic resubmission or retry.  This narrow
authority does not authorize attempt 2, replacement of an estimator run, or
continuation after any pipeline-invalid, estimator-started-without-result, or
supervision failure.

For every published result, the controller additionally writes an immutable
dispatch-execution receipt only after the inner arm runner exits.  It binds the
exact result identity, result status, actual runner return code, and the frozen
mapping `SUCCESS -> 0`, all other admissible terminal statuses and
`PIPELINE_INVALID -> 3`.  Both common ordinal validation and the systemd chain
re-read the receipt and require the controller's returned identity and code to
match.  A runner signal/exception after `run_result.json` publication is
therefore fail-stop rather than an adoptable result.  Both arm runners keep
SIGTERM/SIGINT fail-stop handling active through postprocessing and exclusive
result publication; the result contract permits only an empty deferred-signal
list.

The retry allowlist is empty.  A `PIPELINE_INVALID` result completes only the
first submission's immutable execution/adoption evidence, then enters
`PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`.  The supervisor rejects that state as
non-submittable; the controller and common receipt validator reject any
invalid-attempt adjudication or second-submission transition.  Attempt index 2
is invalid for every coordinate.

Before any dispatch claim, the runner resource-check JSON is bound to its
process exit: `ready=true` is accepted only with return code 0, and a valid
`ready=false` only with return code 2.  A mismatched or signal-derived return
code is a non-retryable controller failure and cannot start an estimator, even
if stdout already contains `ready=true`.

Systemd timeout, signal termination, missing/malformed entry/post/adoption
receipt, cgroup/property/InvocationID drift, a unit terminal without
`run_result.json`, or loss of the user manager is a non-retryable supervision
failure.  It is never an estimator timeout or algorithm failure and requires
abandonment of the entire v9 experiment.

## User-manager session limitation

The host currently has a running user manager and active login sessions but
`Linger=no`.  This does not block an authorized run while an active session is
present.  Both submit and service entry record `State`, `Sessions`, and
`Linger`.  Exiting the final login session may stop the user manager, including
its service and possibly `ExecStopPost`; if that occurs, v9 is fail-stop and
must be abandoned.  It never authorizes a retry.

## HFNet post-Shutdown zero-keyframe watchdog

The frozen runner enables this watchdog identically for both HFNet budgets,
all ten windows and all three repeats.  V9 has no replacement attempts.  It may
send exactly one SIGTERM to the exact estimator PGID only after one complete
and unambiguous ordered `Shutdown` and exact target trajectory-save line, one
positive atlas-count line, exactly that many unique map IDs covering
`0..N-1`, and zero keyframes in every map.  The target trajectory and
keyframe trajectory must both remain absent and non-symlink, the target
end-of-saving line and every partial stdout tail must remain absent, and the
entire signature must be continuously confirmed for at least 30 s.

At every sample during those 30 s, and twice again immediately before the
signal, the frozen resource monitor revalidates PID, Linux start ticks,
executable, exact argv, PGID, session ID, and every current process-group
member.  Member receipts retain Linux process state, but the stable identity
projection excludes ordinary `R`/`S`/`D` state changes; a live proof cannot
contain `Z`.  Only `pid == pgid == session` is eligible.  An atomic gate-entry
latch covers the whole final proof path, so concurrent calls cannot exceed one
`killpg(exact_pgid, SIGTERM)` attempt.  The watchdog never sends an individual
signal or SIGKILL.  If SIGTERM is ignored, normal waiting continues within the
same unchanged 1800 s total budget, after which the pre-existing timeout
cleanup may act.  Linux provides no atomic pidfd operation for a process
group, so a small final revalidation-to-`killpg` race remains an explicitly
disclosed platform limitation; double proof and the live session leader are
the frozen mitigation.

Every started HFNet attempt publishes
`zero_kf_post_shutdown_watchdog.json`.  A proven signal adds
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG` as an algorithm failure and never
authorizes a retry.  Missing, malformed, drifted, parser-error,
identity-unproven, final-signal-gate timing, or failed-signal evidence adds the
non-retryable pipeline code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  An
ordinary pre-candidate poll gap or a confirmation-phase gap is governed by the
phase rules below and is not, by itself, this pipeline code.  The watchdog does
not change tracking, estimator inputs, the 1800 s budget, or any success
threshold.

The target polling interval remains 0.20 s and the fixed maximum remains
0.25 s, but 0.25 s is not a global lifetime eligibility rule.  Before an exact
complete trigger candidate exists, a longer interval is recorded without
permanently invalidating the attempt.  During the 30 s confirmation phase,
only intervals no greater than 0.25 s count toward continuous proof; a longer
interval resets the candidate-specific 30 s window and clears its first/final
proof state.  It sends no signal and adds no pipeline code by itself.  A fresh
clean 30 s window may start while the unchanged 1800 s estimator budget
remains.  If no complete exact trigger is ever observed, or candidates appear
but no clean confirmation window completes before ordinary termination, the
watchdog must publish a proven no-trigger/unconfirmed/passive outcome; an
ordinary estimator timeout or return code remains eligible for algorithm
classification.

Only after one uninterrupted 30 s confirmation may the final signal gate be
entered.  The two exact identity proofs and the interval immediately before
`killpg` must each be no greater than 0.25 s and monotonically ordered.  A
longer interval in that gate disables the signal and creates
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`; no fallback signal is permitted.
Gate timing starts from a newly recorded monotonic gate-entry baseline after
confirmation; neither the lifetime maximum nor the timestamp of an earlier
ordinary sample may be substituted for a gate-local interval.  The receipt
retains both lifetime diagnostics and the separate phase/gate timings.  The
signal remains exactly one SIGTERM to the revalidated exact process group.

V9 retains the v6 fail-closed distinction between a live identity mismatch
and the same supervised `Popen` child crossing its Linux exit/reap boundary,
and adds the v7 teardown-snapshot correction.  Snapshot collection is
observational and never calls `Popen.poll()`.  A sole frozen leader with
unchanged PID, start ticks, PGID, and session but empty executable/cmdline is
only a teardown candidate; its sampled Linux state is retained but cannot
prove exit because the composite `/proc` read is not atomic.  Alternatively,
the exact group may disappear without any scan/read error between the
caller's polls (including during immutable recheck) while the global scan also
contains no record with the frozen numeric leader PID.  A globally visible
leader with changed start ticks, PGID, session, or non-empty identity is drift
and cannot use the disappearance path.  Neither shape authorizes a signal.
Only an immediate or bounded exact reap of the same supervised `Popen` child
produces a receipt-bound passive exit with launch identity, return code,
ordering, and final-empty ownership proof.  Still alive, an unknown reap, any
non-empty wrong identity, PID reuse, PGID/session drift, an extra member, or
any scan/read/member discrepancy remains an unproven pipeline chain.

Every proven, unsignalled natural child reap also receives an ordinary/passive
adjudication, so the chain cannot be made acceptable by deleting the special
race record.  Phase-specific validation requires the prior exact-group
snapshot and every applicable first/final/transition proof, exact field sets,
and monotonic ordering.  It cross-checks the child return code against both
`run_result.raw_returncode` and the independently pinned runtime-monitor
return code, while also binding the launch identity and final empty-group
state.  All passive, signalled, and failed/unproven watchdog outcomes repeat
that final child return code at both receipt levels.  The same rule covers exit
between final proofs or before `killpg`.  A failed signal-delivery call remains
recorded as the sole attempted action with `signal_sent=false` and forces an
unproven pipeline outcome; it cannot be erased as no action.  Poll-gap
accounting includes every passive return.  The HFNet binary, library, model,
configuration, and its zero-keyframe shutdown defect are not patched.

Runtime cleanup ownership is exact-identity based.  New descendants require a
fresh exact parent/child lineage recheck; GPU process rows cannot create
ownership; an unreadable `/proc` identity makes a GPU row external and the
probe unproven even if its numeric PID was formerly owned.  A start-tick change
between the two `/proc` identity reads is treated the same way, not as benign
absence.  Proc/GPU probe starts must all lie within the supervision coverage
interval and be strictly increasing; an after-end or out-of-order sample never
proves coverage.  Ownership-set access is locked, and a group signal is allowed
only while the unique frozen leader identity is revalidated live.  Numeric PID
or PGID reuse can neither create ownership nor become a cleanup target.

## Freeze and execution order

Before the first estimator start: run pure tests and a temporary-root
no-estimator chain; verify the formal v9 root is absent; then run fresh
`freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix`.  No frozen v1--v8 manifest, generated runtime input, attempt,
receipt, cache, or outcome may be copied into that namespace.  The matrix must
contain 120 fresh attempt manifests and zero dispatch/start/result/terminal
receipts, all eight predecessor-import claims must be exactly false, and status
must be ordinal 1 READY.

Thereafter use one `submit` per unit, poll without mutation, and adopt only
after the `ExecStopPost` terminal receipt.  V9 begins at ordinal 1.  No outer
multi-ordinal loop with a cumulative deadline is permitted.
