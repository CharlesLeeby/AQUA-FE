# Fair-stability prospective control supersession v6

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V6 ESTIMATOR START**  
Parent protocol: `fair_stability_positive_roster_protocol_v1.md`  
Runtime addendum: `fair_stability_runtime_exclusivity_addendum_v6.md`

## Identity and scientific invariance

The v6 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v6`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v6`, and the backend id is
`DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V6`.  V6 schemas end in `-v6`; the backend
freeze is under
`vins_dev_nativeq_schedfix_runtimeexcl_v6/backend_freeze.json`.

V6 changes only execution supervision, lifecycle evidence, and versioned
provenance.  The ten windows, four arms, two HFNet feature budgets, three
repeats, 120-coordinate order, estimator binaries and libraries, model,
configs, image/IMU inputs, replay schedules, time offsets, feature parameters,
success/partial thresholds, 1800 s estimator budget, retry allowlist,
statistical unit, primary endpoint, contrast, and inference are unchanged.

The v3 experiment is permanently abandoned under
`fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`.
The v4 experiment is permanently abandoned under
`fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`.
The v5 experiment is permanently abandoned under
`fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`.
No v1, v2, v3, v4, or v5 result, manifest, generated runtime input, attempt cache,
claim, log, receipt, or summary is imported into v6.  All five
`v1_results_imported`, `v2_results_imported`, `v3_results_imported`, and
`v4_results_imported`, and `v5_results_imported` claims
must be exactly false in the input manifest, backend freeze, attempt matrix,
and summary.

## Mandatory systemd user transient service

Every formal mutating `run-next` is launched through the frozen
`run_fair_stability_systemd_supervisor_v6.py`.  Direct controller execution is
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
pipeline-invalid adjudication likewise requires the preceding systemd adoption
receipt.

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

An allowlisted `PIPELINE_INVALID` result and its adjudication are deliberately
two systemd submissions.  The second submission starts from
`PIPELINE_INVALID_UNADJUDICATED`, starts no estimator, revalidates the prior
result's inner runner-exit receipt and complete prior systemd adoption, binds
the new invalid-attempt receipt, and must end with the immediately following
attempt READY.  It does not masquerade as the submission that originally
dispatched the runner; a missing or drifted prior adoption blocks the
transition.

Before any dispatch claim, the runner resource-check JSON is bound to its
process exit: `ready=true` is accepted only with return code 0, and a valid
`ready=false` only with return code 2.  A mismatched or signal-derived return
code is a non-retryable controller failure and cannot start an estimator, even
if stdout already contains `ready=true`.

Systemd timeout, signal termination, missing/malformed entry/post/adoption
receipt, cgroup/property/InvocationID drift, a unit terminal without
`run_result.json`, or loss of the user manager is a non-retryable supervision
failure.  It is never an estimator timeout or algorithm failure and requires
abandonment of the entire v6 experiment.

## User-manager session limitation

The host currently has a running user manager and active login sessions but
`Linger=no`.  This does not block an authorized run while an active session is
present.  Both submit and service entry record `State`, `Sessions`, and
`Linger`.  Exiting the final login session may stop the user manager, including
its service and possibly `ExecStopPost`; if that occurs, v6 is fail-stop and
must be abandoned.  It never authorizes a retry.

## HFNet post-Shutdown zero-keyframe watchdog

The frozen runner enables this watchdog identically for both HFNet budgets,
all ten windows, all three repeats, and every replacement attempt.  It may
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
authorizes a retry.  Missing, malformed, drifted, delayed-poll, parser-error,
identity-unproven, or failed-signal evidence adds the non-retryable pipeline
code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  The watchdog does not change
tracking, estimator inputs, the 1800 s budget, or any success threshold.

The only v6 watchdog correction is a fail-closed distinction between a live
identity mismatch and the same supervised Popen child crossing its Linux
exit/reap boundary.  Snapshot collection is observational and never calls
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
no-estimator chain; verify the formal v6 root is absent; then run fresh
`freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix`.  The matrix must contain 120 attempt manifests and zero
dispatch/start/result/terminal receipts, and status must be ordinal 1 READY.

Thereafter use one `submit` per unit, poll without mutation, and adopt only
after the `ExecStopPost` terminal receipt.  V6 begins at ordinal 1.  No outer
multi-ordinal loop with a cumulative deadline is permitted.
