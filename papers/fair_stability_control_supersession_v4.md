# Fair-stability prospective control supersession v4

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V4 ESTIMATOR START**  
Parent protocol: `fair_stability_positive_roster_protocol_v1.md`  
Runtime addendum: `fair_stability_runtime_exclusivity_addendum_v4.md`

## Identity and scientific invariance

The v4 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v4`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v4`, and the backend id is
`DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V4`.  V4 schemas end in `-v4`; the backend
freeze is under
`vins_dev_nativeq_schedfix_runtimeexcl_v4/backend_freeze.json`.

V4 changes only execution supervision, lifecycle evidence, and versioned
provenance.  The ten windows, four arms, two HFNet feature budgets, three
repeats, 120-coordinate order, estimator binaries and libraries, model,
configs, image/IMU inputs, replay schedules, time offsets, feature parameters,
success/partial thresholds, 1800 s estimator budget, retry allowlist,
statistical unit, primary endpoint, contrast, and inference are unchanged.

The v3 experiment is permanently abandoned under
`fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`.
No v1, v2, or v3 result, manifest, generated runtime input, attempt cache,
claim, log, receipt, or summary is imported into v4.  All three
`v1_results_imported`, `v2_results_imported`, and `v3_results_imported` claims
must be exactly false in the input manifest, backend freeze, attempt matrix,
and summary.

## Mandatory systemd user transient service

Every formal mutating `run-next` is launched through the frozen
`run_fair_stability_systemd_supervisor_v4.py`.  Direct controller execution is
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
- fixed minimum environment and absolute control argv; and
- no scope, `nohup`, tmux, `--wait`, `--pipe`, or `--collect`.

The unit entry verifies the live unit properties, InvocationID, MainPID, exact
cgroup membership, frozen controller/supervisor identities, and exact
ordinal/attempt before invoking the controller.  It publishes a start receipt
first.  `ExecStopPost` is an explicit argv, not a shell command or `%n`
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

Systemd timeout, signal termination, missing/malformed entry/post/adoption
receipt, cgroup/property/InvocationID drift, a unit terminal without
`run_result.json`, or loss of the user manager is a non-retryable supervision
failure.  It is never an estimator timeout or algorithm failure and requires
abandonment of the entire v4 experiment.

## User-manager session limitation

The host currently has a running user manager and active login sessions but
`Linger=no`.  This does not block an authorized run while an active session is
present.  Both submit and service entry record `State`, `Sessions`, and
`Linger`.  Exiting the final login session may stop the user manager, including
its service and possibly `ExecStopPost`; if that occurs, v4 is fail-stop and
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
member.  Only `pid == pgid == session` is eligible.  The watchdog calls
`killpg(exact_pgid, SIGTERM)` once; it never sends an individual signal or
SIGKILL.  If SIGTERM is ignored, normal waiting continues within the same
unchanged 1800 s total budget, after which the pre-existing timeout cleanup
may act.  Linux provides no atomic pidfd operation for a process group, so a
small final revalidation-to-`killpg` race remains an explicitly disclosed
platform limitation; double proof and the live session leader are the frozen
mitigation.

Every started HFNet attempt publishes
`zero_kf_post_shutdown_watchdog.json`.  A proven signal adds
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG` as an algorithm failure and never
authorizes a retry.  Missing, malformed, drifted, delayed-poll, parser-error,
identity-unproven, or failed-signal evidence adds the non-retryable pipeline
code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  The watchdog does not change
tracking, estimator inputs, the 1800 s budget, or any success threshold.

## Freeze and execution order

Before the first estimator start: run pure tests and a temporary-root
no-estimator chain; verify the formal v4 root is absent; then run fresh
`freeze-inputs`, `freeze-backend`, both `prepare-all` passes, and
`freeze-matrix`.  The matrix must contain 120 attempt manifests and zero
dispatch/start/result/terminal receipts, and status must be ordinal 1 READY.

Thereafter use one `submit` per unit, poll without mutation, and adopt only
after the `ExecStopPost` terminal receipt.  V4 begins at ordinal 1.  No outer
multi-ordinal loop with a cumulative deadline is permitted.
