# Fair-stability prospective control supersession v7

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V7 ESTIMATOR START**  
Parent protocol: `papers/fair_stability_positive_roster_protocol_v1.md`  
Runtime addendum: `papers/fair_stability_runtime_exclusivity_addendum_v7.md`

## Identity and scientific invariance

The v7 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v7`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v7`, and the backend id is
`DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V7`.  V7 schemas end in `-v7`; the backend
freeze is under
`vins_dev_nativeq_schedfix_runtimeexcl_v7/backend_freeze.json`.

V7 changes only execution supervision, lifecycle evidence, and versioned
provenance.  The ten windows, four arms, two HFNet feature budgets, three
repeats, 120-coordinate order, estimator binaries and libraries, model,
configs, image/IMU inputs, replay schedules, time offsets, feature parameters,
success/partial thresholds, 1800 s estimator budget, statistical unit,
primary endpoint, contrast, and inference are unchanged.  The one prospective
safety change is that the retry allowlist is empty: every pipeline-invalid
attempt stops v7 for manual review, and no replacement attempt is authorized.

The complete predecessor provenance is retained under its original
workspace-relative paths:

- `papers/fair_stability_v1_runtime_contamination_report_20260829.md`;
- `papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`;
- `papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`;
- `papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`;
- `papers/fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`;
  and
- `papers/fair_stability_v6_final_gate_timing_abandonment_report_20260829_v7.md`.

No v1, v2, v3, v4, v5, or v6 result, manifest, generated runtime input,
attempt cache, claim, log, receipt, or summary is imported into v7.  The input
manifest, backend freeze, attempt matrix, and summary must each contain all six
exact assignments: `v1_results_imported=false`,
`v2_results_imported=false`, `v3_results_imported=false`,
`v4_results_imported=false`, `v5_results_imported=false`, and
`v6_results_imported=false`.

## Mandatory systemd user transient service

Every formal mutating `run-next` is launched through the frozen
`run_fair_stability_systemd_supervisor_v7.py`.  Direct controller execution is
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

The adoption chain is two phase.  `adopt` first publishes an adoption claim;
for a terminal algorithm result the ordinal controller then publishes its
terminal receipt bound to that claim; finally the supervisor publishes an
adoption receipt bound to both.  Common state and summaries accept a terminal
cell only when the complete chain remains present and identity-valid.  A
pipeline-invalid result may retain the first submission's systemd adoption
evidence, but it immediately enters the non-submittable zero-retry fail-stop
state.

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
abandonment of the entire v7 experiment.

## User-manager session limitation

The host currently has a running user manager and active login sessions but
`Linger=no`.  This does not block an authorized run while an active session is
present.  Both submit and service entry record `State`, `Sessions`, and
`Linger`.  Exiting the final login session may stop the user manager, including
its service and possibly `ExecStopPost`; if that occurs, v7 is fail-stop and
must be abandoned.  It never authorizes a retry.

## HFNet post-Shutdown zero-keyframe watchdog

The frozen runner enables this watchdog identically for both HFNet budgets,
all ten windows and all three repeats.  V7 has no replacement attempts.  It may
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

V7 retains the v6 fail-closed distinction between a live identity mismatch
and the same supervised Popen child crossing its Linux exit/reap boundary.
Snapshot collection is observational and never calls
`Popen.poll()`.  Either the sole frozen leader must be explicitly `Z` with
empty executable/cmdline, or the exact group must disappear without any
scan/read error between the caller's polls (including during immutable
recheck) while the global scan also contains no record with the frozen numeric
leader PID.  A globally visible leader with changed start ticks, PGID,
session, or non-empty identity is drift and cannot use the disappearance
path.  Reap immediately after that proof or before the next scheduled
sample produces a receipt-bound passive-exit adjudication with no signal
attempt; still alive, any non-empty wrong identity, or any additional
scan/read/member discrepancy remains an unproven pipeline chain.

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
no-estimator chain; verify the formal v7 root is absent; then run fresh
`freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix`.  No frozen v1--v6 manifest, generated runtime input, attempt,
receipt, cache, or outcome may be copied into that namespace.  The matrix must
contain 120 fresh attempt manifests and zero dispatch/start/result/terminal
receipts, all six predecessor-import claims must be exactly false, and status
must be ordinal 1 READY.

Thereafter use one `submit` per unit, poll without mutation, and adopt only
after the `ExecStopPost` terminal receipt.  V7 begins at ordinal 1.  No outer
multi-ordinal loop with a cumulative deadline is permitted.
