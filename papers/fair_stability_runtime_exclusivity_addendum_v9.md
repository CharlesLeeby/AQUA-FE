# Fair-stability runtime-exclusivity addendum v9

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V9 ESTIMATOR START**.

Ordered normative bundle, using workspace-relative paths (later items refine
earlier items without rewriting them):

1. `papers/fair_stability_positive_roster_protocol_v1.md`;
2. `papers/fair_stability_vins_supervised_shutdown_addendum_v1.md`;
3. `papers/fair_stability_control_supersession_v9.md`; and
4. `papers/fair_stability_runtime_exclusivity_addendum_v9.md` (this file).

The required provenance bundle additionally contains:

1. `papers/fair_stability_v1_runtime_contamination_report_20260829.md`; and
2. `papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`;
   and
3. `papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`;
   and
4. `papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`;
   and
5. `papers/fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`;
   and
6. `papers/fair_stability_v6_final_gate_timing_abandonment_report_20260829_v7.md`;
   and
7. `papers/fair_stability_v7_teardown_snapshot_abandonment_report_20260830_v8.md`; and
8. `papers/fair_stability_v8_historical_no_start_revalidation_abandonment_report_20260830_v9.md`.

Any future v9 input manifest and backend/control freeze must bind the complete
ordered normative and provenance bundle
by absolute path, byte size, and SHA-256.

This addendum prospectively sets the output namespace to
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v9`
and adds the following runtime-exclusivity and durable-supervision contract.
Relative to the final v8 documents, v9 changes only historical supervision
source binding, submission-local `no_start_provenance`, v8 provenance and
versioned identity, control-plane transport, and progress disclosure.  The
scientific design and every estimator-facing quantity are unchanged.
The roster, 120 planned cells, admitted timestamps, arm definitions,
thresholds, and reporting boundaries remain unchanged; the progress-summary
gate below enforces the existing complete-matrix analysis boundary and does
not change the estimand.  V9, if later authorized and frozen, begins at planned
ordinal 1.  No v1, v2, v3, v4, v5,
v6, v7, or v8 result, manifest, generated runtime input, attempt cache, claim, log,
receipt, or summary is imported.  Every v9 input manifest, backend
freeze, attempt matrix, and summary must contain
`v1_results_imported=false`, `v2_results_imported=false`,
`v3_results_imported=false`, `v4_results_imported=false`,
`v5_results_imported=false`, `v6_results_imported=false`,
`v7_results_imported=false`, and `v8_results_imported=false`.

## Submit-only systemd user-service supervision

Every formal ordinal is claimed and submitted by the frozen v9 systemd
supervisor as one uniquely named transient user service.  The service is
`Type=exec`, `KillMode=control-group`, `SendSIGKILL=yes`, `Restart=no`,
`RemainAfterExit=no`, and `UMask=0077`.  It has `RuntimeMaxSec=2400` and
`TimeoutStopSec=120`, while each unchanged runner timeout remains 1800 s.
The later systemd deadline is an infrastructure disaster bound, not an
algorithm timeout.  `nohup`, `tmux`, scope units, `--wait`, `--pipe`, and
`--collect` are forbidden, and stdout and stderr are retained separately.

Submission returns after `systemd-run` accepts the unit.  The user manager,
not the calling Codex process, owns the service.  The frozen entry wrapper
records the exact unit, invocation ID, main-process identity, cgroup, service
properties, active-session snapshot, immutable submission claim, frozen
controls, and controller argv before it invokes the ordinal controller.
`ExecStopPost` records the service result and exit tuple while the transient
unit still exists.  Because a successful transient unit may unload
immediately, post-run adoption may not infer terminal state from a later
`systemctl show` alone.

The service overrides and receipt-binds an exact fixed environment subset,
including
`PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages` and
`PYTHONNOUSERSITE=1`.  This retained control correction exposes the installed ROS Noetic Python packages to
`/usr/bin/python3` and does not change any estimator, model, input, or
parameter.  The latter prevents unpinned user-site packages and
`usercustomize` from entering the Python control and validation process used
for either arm; it does not claim to suppress the operating system's
`sitecustomize`.  Submit and service-entry preflights
execute an import probe under
that fixed subset, and the submission/start receipts plus
`systemd-run --setenv` argv must bind identical values.  A failed probe or any
fixed-subset drift is a pre-estimator, non-retryable control failure.  Other
systemd user-manager variables are not claimed to be absent; each estimator is
still launched with its pre-existing explicit per-arm runtime environment.
The supervisor constructs its own user-bus client environment from the fixed
runtime path `/run/user/1000`: `XDG_RUNTIME_DIR=/run/user/1000` and
`DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus`.  These two values are
control-plane transport selectors, not estimator parameters.  Pinning them
prevents an ambient shell or an otherwise clean `env -i` invocation from
creating a false user-manager-loss preflight while leaving the frozen service
environment and both estimator arms unchanged.

Terminal algorithm evidence becomes admissible only after a two-phase external
adoption: an immutable adoption claim first authorizes the ordinal terminal
receipt, then a final adoption receipt binds that terminal receipt back to the
submission, start, execution, and `ExecStopPost` chain.  A missing, malformed,
symlinked, identity-drifted, invocation-mismatched, timed-out, or signal-killed
chain is a fail-stop infrastructure failure.  It cannot become an algorithm
failure, authorize a replacement, become a terminal ordinal, or enter a
summary row.

The controller also records the inner arm runner's actual process return code
after the exclusive `run_result.json` publication.  That execution receipt
binds the result identity and status to the frozen return-code mapping
`SUCCESS -> 0` and every other admissible terminal or `PIPELINE_INVALID`
status `-> 3`.  Common state validation and the systemd adoption chain both
re-read this binding.  Thus a signal or exception after result publication but
before runner exit cannot turn the already-written file into an admissible
result.  SIGTERM and SIGINT remain fail-stop handlers through postprocessing
and result publication; no deferred postprocessing signal is admissible.
When a result is `PIPELINE_INVALID`, its first systemd submission may finish
the immutable execution/adoption evidence chain, but v9 then enters
`PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`.  That state is not submittable.  No
invalid-attempt receipt, second adjudication submission, next attempt, or
same-namespace continuation is authorized.
The pre-start runner check has its own process-exit binding: `ready=true`
requires return code 0, while a structurally valid `ready=false` requires
return code 2.  Any other pairing--including a signal after flushing
`ready=true`--is non-retryable and cannot reach the dispatch claim or estimator
start.

### Submission-local no-start provenance and revalidation

For the only two admissible pre-estimator outcomes,
`RESOURCE_BLOCKED_NO_START` and
`PRESTART_DISPATCH_BLOCKED_NO_ESTIMATOR_START`, the service-entry/controller
chain publishes an immutable `no_start_provenance` object inside that exact
submission's `systemd_execution_receipt.json`; no separate provenance file is
created.  Its schema is
`aqua-fe-fair-stability-systemd-no-start-provenance-v9`.  The surrounding
execution receipt is identity-bound by the systemd terminal receipt, adoption
claim, and adoption receipt.

Both branches bind the submission claim and start receipt; exact unit,
InvocationID through the surrounding chain, nonce, ordinal, attempt index, and
submission index; controller return code 75; pre- and post-controller ordinal
states; and cutoff observations proving that `start_claim.json` and
`run_result.json` were absent and no estimator-start authority existed.  The
resource branch additionally binds the complete resource-gate receipt,
`ready=false`, resource-check return code 2, and no dispatch execution.  The
pre-start dispatch branch instead binds the immutable execution receipt for
this submission's dispatch; that receipt must bind the dispatch claim while
containing no result identity, status, parse error, or result/return-code
binding.  A complete adoption chain is required before any manual resubmission
can be considered.  Neither outcome consumes `attempt_index=1`, creates an
algorithm observation, nor authorizes attempt 2.

The validator has exactly two no-start branches.  In the **current branch**,
there is no accepted later submission and the shared attempt tree must still
equal the complete accepted submission history through the current no-start.
A resource no-start owns no dispatch of its own but may retain gap-free
dispatch claim/execution/stdout/stderr artifacts uniquely bound to earlier
accepted pre-start no-start submissions; a pre-start no-start additionally owns
its exact next dispatch.  Neither case permits start, result, or runtime
evidence without a strictly later result-producing submission.  In the
**historical branch**, a strictly
later accepted submission exists for the same ordinal and attempt; the earlier
no-start is revalidated exclusively from its immutable submission-local chain
and cutoff.  A `run_result.json` or other shared-attempt artifact produced by
that later submission is expected to be outside the earlier cutoff and must
not be rebound across submissions.  It is admissible only when attributable
to that exact later submission.  Orphaned or index-gapped dispatch claims,
executions, logs, start/results, or runtime artifacts are invalid.

The complete history is also structural evidence.  Submission directories
must be gap-free from index 1; each directory, claim, unit name, ordinal,
attempt index, and shared attempt root must agree.  Each index after 1 must
bind the one authorization for that exact next index.  Thus an orphaned
start/result left after deletion of its later submission chain is invalid, not
a historical no-start continuation.

These branches cannot be mixed.  A resource proof is rejected if its own
submission reached dispatch; either proof is rejected if its own submission
reached estimator start, if it binds any later result, if a later artifact
lacks a unique later-submission attribution, or if any identity, hash, return
code, ordering, or absence snapshot drifts.  The appearance of a later,
correctly attributed result cannot retroactively alter a valid earlier
no-start proof.  Conversely, terminal-result validation is always
submission-local and must establish its own dispatch, execution receipt,
exclusive result publication, ordinal terminal receipt, and complete systemd
adoption chain.  Neither no-start branch may satisfy, replace, or bypass any
terminal requirement.  Every other controller outcome must carry an
explicitly null `no_start_provenance` object.

The only authorization command after either proven no-start is:

```text
/usr/bin/python3 /home/ma/AQUA-FE_WS/scripts/run_fair_stability_systemd_supervisor_v9.py authorize-resubmit --submission-dir <absolute-prior-submission-dir>
```

It requires the latest finalized no-start chain, validates the exact stopped
unit and InvocationID, records the exact fixed-control-environment
`systemctl --user reset-failed UNIT`, and accepts a verified inactive unit or
an explicitly unloaded/not-found unit after reset.  It then runs the exact arm
`check` command before any new `systemd-run`.  Return code 0, the complete
20-field `ready=true` gate, raw/parsed GPU agreement, the frozen attempt
manifest, and the arm-specific port contract must all hold.  The immutable
`resubmit_authorization_for_submission_NNN.json` binds these ordered UTC
events and authorizes only the same ordinal, same `attempt_index=1`, and exact
next submission index.

`submit` consumes that identity once while holding the same lock used to
revalidate pending history and re-read state, host preflight, and frozen
context.  It rejects a missing, stale, replayed, or altered authorization,
constructs the exact new claim bytes and predicted identity in memory, and
atomically publishes the prior-directory
`resubmit_authorization_consumption_for_submission_NNN.json` before the new
directory or claim.  This exact-field marker binds the authorization, both
submission coordinates, the prior and predicted-new claim identities, new
unit/directory/index, ordinal, `attempt_index=1`, attempt root, and UTC consume
time.  Only after a strict marker re-read does `submit` publish the exact claim
bytes, re-read both identities, and permit `systemd-run`.

History requires one marker for every index after 1 and no orphan marker.  A
missing/tampered marker with a retained later claim, or a retained marker after
deletion of the later resource-no-start directory, is fail-stop.  Any exception
after marker publication leaves all evidence in place and permanently consumes
the ticket; no cleanup path can restore submit authority.  This prevents the
single-sided deletion/replay attacks represented inside the retained v9 tree.
It is not a claim against coordinated rollback of the marker, successor, and
all later evidence by an actor able to rewrite that whole tree; such a threat
requires an external privileged append-only or remote monotonic ledger.
Authorization itself never submits.  No controller, poll, adopt, or
resource-gate command may auto-resubmit.  A failed adoption, reset, identity
check, resource revalidation, or post-consumption submit is fail-stop.  This
does not relax the empty retry allowlist and does not authorize resubmission
after estimator start, pipeline invalidity, or any supervision failure.

Adoption is outcome-specific.  A normal terminal must bind its own
dispatch/result, return code 0, `TERMINAL_UNADOPTED`, and non-null ordinal
receipt.  Pipeline-invalid must bind its own result and zero-retry state with a
null ordinal receipt.  No-start must return 75, preserve `READY`, and keep the
ordinal receipt null.  Exact claim/final field sets, UTC ordering, and false
timeout/retry flags are revalidated.  For a terminal, the final receipt stores
the exact immediate successor (next scheduled coordinate or `COMPLETE`), and
the supervisor recomputes it after publication.  Once the next ordinal has a
submission, historical revalidation uses its immutable `submission_001`
pre-state, so later completion cannot rewrite the prior successor snapshot.

The current host has `Linger=no`; this is explicitly disclosed rather than
silently treated as durable across logout.  Formal preflight therefore requires
the user manager to be running and at least one active login session, and pins
`State`, `Sessions`, and `Linger` in the submission/start receipts.  Exit of the
last session may stop the manager.  If that occurs, v9 is permanently
abandoned; no automatic continuation or retry is authorized.

## HFNet zero-keyframe post-Shutdown watchdog

All HFNet budgets, windows, and repeats use one frozen watchdog contract; v9
has no replacement attempts.  The runner samples at a 0.20 s target interval with a
fixed 0.25 s maximum and requires 30 continuous seconds of: one ordered and exact
`Shutdown`/target-save sequence; one positive atlas-count line; exactly `N`
unique map rows covering IDs `0..N-1`, all with zero keyframes; no complete or
partial end-of-saving line; no partial stdout tail; and absence (including no
dangling symlink) of both target trajectory files.

The 0.25 s bound is phase-scoped, not a global lifetime eligibility rule.
Before the complete exact signature first becomes a trigger candidate, a late
ordinary poll is retained in the receipt but does not invalidate the attempt.
During the 30 s confirmation phase, only intervals no greater than 0.25 s
count toward continuous proof.  A longer interval resets that candidate's
confirmation window and clears its candidate-specific first/final proof
state; no signal may be sent from the interrupted window, and the gap alone
adds no pipeline code.  A new clean 30 s window may begin while the unchanged
1800 s budget remains.  If no exact complete candidate is ever observed, or
candidates appear but no uninterrupted confirmation completes before ordinary
termination, the watchdog publishes a proven no-trigger/unconfirmed/passive
outcome, and an ordinary estimator timeout or return code remains eligible for
algorithm classification.

Every confirming sample revalidates the unchanged HFNet leader PID, start
ticks, executable, argv, PGID, session, and complete process-group membership.
The sampled Linux state is retained in every member receipt but excluded from
the stable-member projection because a live process may move normally among
`R`, `S`, and `D`.  A live proof itself cannot contain state `Z`.  The final
gate exists only after a complete uninterrupted 30 s confirmation.  It
repeats the stable proof twice, then may send one SIGTERM to the exact PGID.
Both proofs and the interval immediately before `killpg` must be monotonically
ordered and no greater than 0.25 s.  A violation inside this final gate
disables the signal and records the non-retryable pipeline code
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`; no fallback signal is permitted.  An
exact monotonic gate-entry baseline is created only after confirmation; the
lifetime maximum and the timestamp of an earlier ordinary sample remain
diagnostics and cannot substitute for a gate-local interval.  The receipt
binds the lifetime maximum and the distinct confirmation/gate timings.  An
atomic gate-entry latch makes the complete proof/signal path one-shot even
under concurrent callers.  The watchdog cannot send SIGKILL or individual PID
signals.  Failure to exit continues under the original 1800 s total timeout;
no grace is added.
The independent watchdog receipt is mandatory and bound into `run_result` and
pipeline evidence.  A proven signal is the algorithm code
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG`; any unproven watchdog chain is the
non-retryable pipeline code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.
Because Linux has no atomic pidfd group signal, the residual interval between
the second exact proof and `killpg` is disclosed as a platform limitation.

V9 retains the v6 correction for the v5 exit-observation race and the
phase-scoped final-gate timing correction required by the v6 abandonment
report.  It adds the teardown-snapshot correction required by the v7
abandonment report without relaxing live identity checks.  Exact-group
snapshots are purely observational and never call `Popen.poll()` themselves;
the caller performs the before/after polls.  A snapshot with any
scan/read/member error, changed stable identity, or non-empty wrong
executable/argv fails closed immediately.  Only two narrow
terminal-transition shapes may be held until the next already-scheduled
sample: (1) the same sole leader with executable and cmdline empty, unchanged
PID, start ticks, PGID, and session, and no other member or observation error;
or (2) the exact group disappears without scan/read error between the caller
polls, including disappearance during the immutable recheck.  Shape (2)
additionally requires the global process scan to contain no record with the
frozen numeric leader PID; a visible PID with changed start ticks, PGID,
session, or non-empty identity is identity drift, never absence.

For shape (1), the sampled state is retained but is not treated as an atomic
exit fact: `stat`, `exe`, and `cmdline` can straddle address-space teardown.
Neither shape is a live proof or signal authority.  If that exact `Popen`
child is reaped immediately after the proof or before the next bounded sample,
the receipt records the frozen launch identity, exact-child reap source,
return code, ordering, and passive-exit adjudication; the watchdog sends no
signal, and the normal estimator return code remains an algorithm outcome.  If
it remains live at the next boundary, cannot be reaped exactly, or contradicts
the candidate, the chain fails closed.  A return code alone never repairs
wrong non-empty identity, PID/start-tick reuse, PGID or session drift, an extra
member, or any scan/read/recheck error.

Every proven, unsignalled, naturally reaped HFNet child--including an ordinary
exit outside a terminal transition--must carry a passive/ordinary exit
adjudication.  It binds the exact phase, adjudication time, prior exact-group
snapshot, child return code, and all phase-required first/final/transition
proofs.  Common validation enforces exact key sets and monotonic proof order,
requires the prior snapshot to equal the outcome snapshot, and checks the
return code three ways against `run_result` and the independently pinned
runtime-monitor receipt.  Every watchdog branch--passive exit, proven signal,
or unproven/failed signal--also binds that same final child return code in both
its top-level and outcome records.  Deleting the passive chain, deleting a
phase proof, or changing only coordinated watchdog/result return codes
therefore fails closed.  Poll-gap accounting is updated before every passive
return.  The same rule applies between the two final proofs and immediately
before `killpg`; the signal-attempt flag is set only when `killpg` is actually
attempted.  A failed `killpg` delivery remains an immutable attempted action
with `signal_sent=false` and makes the watchdog unproven; it is never cleared
or relabelled as no action.  This adds no grace and changes no estimator
binary, including the published HFNet zero-keyframe shutdown bug.

## Continuous intrusion monitor

Every attempt must pass the pre-start resource gate.  A resource block before
start creates no `start_claim.json`, does not enter an algorithm denominator,
and cannot authorize a substitute attempt or attempt index.  It permits only
the manual same-attempt resubmission chain defined above.  From immediately after the
single supervised `Popen` until that process has been reaped, the runner
samples:

1. `/proc` at intervals no greater than 0.25 s for external estimator, ROS,
   rosbag, frontend-exporter, or compiler processes; and
2. `nvidia-smi` at intervals no greater than 1.0 s for external GPU compute
   applications.

For both streams, every recorded probe start must lie inside the exact
supervision coverage interval and probe starts must be strictly increasing.
A probe first started after coverage ended, a pre-coverage sample, an
out-of-order sample, or a stream with no in-coverage sample cannot prove
runtime coverage even if its nominal interval is below the maximum.

Only the exact supervised root identity, its process group, and descendants
whose ancestry was first observed while owned by that root are excluded.
Ownership is keyed by `(PID, Linux start ticks)` and is never inherited by a
reused numeric PID.  A newly seen live descendant is admitted only after an
atomic re-read proves both its exact child identity and its exact currently
owned parent identity and parent link.  A direct child that was captured by
the monitor's stable two-stat scan but exits before child re-read may enter
known history, never the active-owned set, only after an exact live-parent
recheck; the receipt records
`STABLE_SCAN_CHILD_EXITED_AFTER_PARENT_RECHECK`.  A short-lived intermediate
child whose still-live descendant cannot be proven is conservatively
unowned, making that sample unproven rather than silently extending ancestry.
GPU observations can confirm an already owned exact identity but can never
create ownership from a numeric PID or PGID.  A GPU row whose `/proc` identity
is unreadable or changes start ticks during the two-read identity check is
external and makes the probe unproven even when its numeric PID belonged to an
earlier owned identity; only an error-free absent `/proc` record may be
classified as a stale owned GPU row.
Ownership-set reads and updates are serialized.  Cleanup may signal the
whole process group only while the exact frozen leader identity remains the
unique live leader after recheck; otherwise it can signal only individually
rechecked exact owned identities.  A reused numeric PID or PGID is never a
cleanup target.  PID, start ticks, PGID, executable, and a command-line SHA-256
are recorded for every readable offender.  Probe timestamps, maximum sampling
gaps, errors, and pre/post samples are retained in
`runtime_resource_monitor.json`.  Runtime measurements remain ineligible for
performance claims.

The proc receipt is a selective projection produced by the frozen trusted
monitor: it retains owned identities, supervised-group members, forbidden
processes, errors, and the full-scan process count, but not every unrelated
`/proc` row.  The controller independently verifies projection shape,
ownership lineage, classification, error consistency, and that the count is
at least the number of represented PIDs.  Unlike the GPU query, whose complete
stdout is retained and reparsed, the proc receipt cannot independently prove
that the historical enumeration omitted no unrelated row.  A clean proc
receipt therefore means that the frozen monitor reported no conflict at the
sampled instants, not that the controller reconstructed the whole historical
process table.

Ordinary ToDesk display/remote-control processes may remain open.  There is no
name-based ToDesk exemption: a ToDesk process observed as a GPU compute
application is external compute and invalidates that attempt.

This is sampled exclusion, not a kernel exec-event trace.  A clean receipt
supports only that no conflict was observed at the specified cadence.

## Child lifecycle residual scan

After VINS, rosbag, and roscore are reaped, the VINS child wrapper scans
`/proc/[0-9]*/stat` using Bash builtins in its current process.  It directly
updates `DESCENDANT_RESIDUALS` and `DESCENDANT_RESIDUAL_COUNT`; the scan must
not start `ps`, `awk`, `paste`, a command-substitution subshell, or any other
observer process.  A real non-wrapper member of the supervised process group
remains a lifecycle failure and is recorded by PID and state.

## Classification and fail-stop policy

An observed external conflicting process or GPU compute application adds
`MIDRUN_EXTERNAL_RESOURCE_INTRUSION` and makes the attempt
`PIPELINE_INVALID`.  It halts the ordinal controller for manual review; it is
not eligible for automatic same-cell replacement.  This removes selective
replacement as a possible source of arm-dependent stability bias.

A proc/GPU probe error or sampling-gap violation adds
`RUNTIME_RESOURCE_MONITOR_UNPROVEN`; it halts the controller for manual
experiment abandonment/review.  The same HALT rule applies to supervised
shutdown/lifecycle failures, estimator identity failures, tag/configuration/
model/control drift, post-run reverification failures, and any unlisted code.
No automatic invalid-attempt receipt or replacement is created for any v9
pipeline fault.

Exactly one attempt is pre-registered for each planned coordinate.  Attempt
index 2 is forbidden.  The attempt-matrix freeze must record an empty retry
allowlist, zero replacement attempts, and one total attempt per coordinate
before the first estimator start.  A replacement would require abandonment of
this namespace and a newly versioned prospective protocol.

Algorithm observations in a pipeline-invalid attempt are diagnostic only and
cannot enter the algorithm denominator.  The stopped experiment cannot resume
by silently substituting a cleaner run.

## Cross-arm IMU clock and support freeze

The HFNet runtime input must be regenerated inside the v9 frozen namespace
from the IMU stream contained in the two historical feature bags.  For every
case, the Learned+KLT and pure-KLT bags must have exactly the same IMU topic,
message type, header timestamps, rosbag record timestamps, and six floating-
point gyro/acceleration values.  Any difference aborts the freeze.
The two bags must also have the same feature header timestamps, feature record
timestamps, and exact feature/IMU merged rosbag replay ordering; feature
payload values may differ by arm as intended.

One dataset-level camera/IMU offset is fixed before execution:

- AQUALOC Archaeology: `td = -0.053694112369382575 s`;
- NTNU: `td = 0.0017656238182069367 s`;
- CIRS: `td = 0.0 s`.

These values are shared by every window in a dataset.  In particular, the
historical A07 recovery-profile value `-0.033694112369382575 s` is forbidden
in v9 because it is a window-specific recovery setting.  The v9 VINS runtime
template changes only `output_path` and, where necessary, `td`; all other
source configuration bytes and both VINS arms remain paired.

For HFNet, each IMU CSV timestamp is
`round_half_even(bag_header_ns - td * 1e9)`.  Decimal arithmetic is required,
the sub-nanosecond rounding residual is recorded, all six values must round-
trip exactly, and the resulting series must strictly bracket the first and
last admitted image.  Selected images are hard-linked without modification.
The frozen receipt records both source bags, the generated CSV, and an ordered
semantic digest.  This equalizes the available physical IMU samples and clock
convention; it does not claim identical internal consumption.  HFNet and VINS
retain their native initialization/pre-roll semantics, which are part of this
system-level comparison.

The cutoff proof reproduces native binary64 behavior rather than relying only
on an ideal integer-clock model: ROS `sec + nsec*1e-9` and VINS's strict
`imu_time < camera_time + td` are compared against the EuRoC reader's
`stod(ns)/1e9` and inclusive `shifted_imu_time <= camera_time`.  Every admitted
camera must select the same predecessor index, and the minimum distance from a
native cutoff to an IMU timestamp is recorded.  An equality-boundary mismatch
aborts the freeze.

For each VINS attempt, the child copies the frozen camera calibration beside
the generated runtime VINS YAML.  Its byte size and SHA-256 must equal the
frozen source immediately before estimator launch, must be bound in the child
start receipt, and must still match in post-run integrity checks.

## Inclusive accepted-support boundary

The accepted longest-contiguous trajectory support is closed at both ends.
A reset, solver-risk event, or reinitialization whose next initialization
frame equals the first accepted support frame is inside support and prevents
`SUCCESS`.  Only an event proven to finish strictly before that frame may be
classified as early.

## Fresh-v9 freeze gate

V9 is a new 120-cell experiment, not a continuation of any predecessor.  The
authoritative roster, source bags, raw images, estimator configurations,
binaries, libraries, models, and shared randomization seed may be reused as
upstream sources only after fresh v9 validation.  V9 must regenerate its own
runtime inputs, input manifest, backend/control freeze, 120 attempt manifests,
attempt matrix, receipts, and summary.  No generated or outcome-bearing v1--v8
artifact may be copied into the v9 formal root.

Before the first estimator starts, pure tests and a temporary-root
no-estimator shadow chain must pass, the formal v9 root must be proven absent,
and fresh `freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix` must complete in that order.  The frozen matrix must contain
exactly 120 fresh attempt manifests, no dispatch claim, start claim, launch
receipt, result, ordinal terminal receipt, or systemd submission receipt, and
all eight predecessor-import fields must be exactly false.  Each attempt root
must match the exact arm-specific prepare-tree allowlist, including an empty
HFNet result directory and the original frozen HFNet cache identity; any extra
log, trajectory, lifecycle, watchdog, controller, launch, or runtime artifact
blocks the matrix freeze.  The only admissible initial state is planned
ordinal 1 `READY`.

## Frozen estimand and statistical unit

The primary endpoint is `CLEAN_SUCCESS`.  A terminal `SUCCESS` that is not
clean and every terminal non-success count as zero.  A `PIPELINE_INVALID`
result halts and invalidates completion of the v9 namespace; it is neither an
algorithm zero nor replaceable.  No final inference is authorized until all
120 fresh v9 planned cells have terminal receipts.  No partial v1--v8 outcome may enter any
denominator, p-value, bootstrap interval, summary, table, figure, or system
ranking.

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

The independent unit is the ten `case_id` windows.  The three repeats are
nested within a window and arm.  For window `w` and arm `a`, let `c_wa` be the
number of clean successes out of three and `q_wa = c_wa / 3`.  The sole primary
contrast is `learned_klt_vins - hfnet_openloop_675`, with
`Delta = mean_w(q_w,learned - q_w,hfnet675)`.

The primary two-sided p-value enumerates all `2^10 = 1024` whole-window label
exchanges, using integer differences `c_w,learned - c_w,hfnet675` and counting
ties in the tail.  This is a paired sign-flip diagnostic under the sharp null
that the complete three-repeat arm blocks are exchangeable within each case
and that the ten case blocks are independent.  Algorithm labels were not
randomly assigned; the test is not an unconditional exact test of a zero mean
effect under arbitrary heterogeneous effects.  A small p-value rejects only
that sharp block-exchangeability null.  The 95% interval is the percentile interval from the exact
multinomial-weighted paired-window cluster bootstrap: all
`C(19,9) = 92,378` ten-out-of-ten window count vectors, weights
`10! / (10^10 * product(n_w!))`, and the left-continuous inverse empirical CDF
at 0.025 and 0.975.  This is a diagnostic interval for the fixed,
outcome-selected roster, not a dataset-population guarantee.

Two secondary clean-success contrasts are fixed: Learned+KLT versus pure KLT,
and HFNet-675 versus HFNet-350.  They are confirmatory only if the primary
two-sided p-value is below 0.05, after which their two p-values use Holm
correction.  Otherwise they remain descriptive.  No other metric receives an
unregistered p-value.  “Higher stability” additionally requires positive
`Delta`, primary p below 0.05, and a bootstrap lower bound above zero;
failure to meet these criteria is not evidence of equivalence.

The comparison boundary is the cold-start runnability of frozen historical
feature streams replayed through one prospective VINS backend versus native
online open-loop HFNet-SLAM.  It is not an end-to-end compute-cost comparison,
a learned-frontend causal test, a current paper-final-system result, or a
dataset-wide generalization claim.
