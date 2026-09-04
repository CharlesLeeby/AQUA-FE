# Fair-stability runtime-exclusivity addendum v6

Status: **PROSPECTIVE; MUST BE FROZEN BEFORE THE FIRST V6 ESTIMATOR START**.

Ordered normative bundle (later items refine earlier items without rewriting
them):

1. `fair_stability_positive_roster_protocol_v1.md`;
2. `fair_stability_vins_supervised_shutdown_addendum_v1.md`;
3. `fair_stability_control_supersession_v6.md`; and
4. this runtime-exclusivity addendum.

The required provenance bundle additionally contains:

1. `fair_stability_v1_runtime_contamination_report_20260829.md`; and
2. `fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`;
   and
3. `fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md`;
   and
4. `fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md`;
   and
5. `fair_stability_v5_watchdog_exit_race_abandonment_report_20260829_v6.md`.

Any future v6 input manifest and backend/control freeze must bind all nine files
by absolute path, byte size, and SHA-256.

This addendum prospectively sets the output namespace to
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v6`
and adds the following runtime-exclusivity and durable-supervision contract.
The roster, 120 planned
cells, admitted timestamps, arm definitions, thresholds, and reporting
boundaries remain unchanged.  No v1, v2, v3, v4, or v5 result is imported; v6, if later
authorized and frozen, begins at planned ordinal 1.

## Submit-only systemd user-service supervision

Every formal ordinal is claimed and submitted by the frozen v6 systemd
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

Terminal algorithm evidence becomes admissible only after a two-phase external
adoption: an immutable adoption claim first authorizes the ordinal terminal
receipt, then a final adoption receipt binds that terminal receipt back to the
submission, start, execution, and `ExecStopPost` chain.  A missing, malformed,
symlinked, identity-drifted, invocation-mismatched, timed-out, or signal-killed
chain is a fail-stop infrastructure failure.  It cannot become an algorithm
failure, a replacement attempt, a terminal ordinal, or a summary row.

The controller also records the inner arm runner's actual process return code
after the exclusive `run_result.json` publication.  That execution receipt
binds the result identity and status to the frozen return-code mapping
`SUCCESS -> 0` and every other admissible terminal or `PIPELINE_INVALID`
status `-> 3`.  Common state validation and the systemd adoption chain both
re-read this binding.  Thus a signal or exception after result publication but
before runner exit cannot turn the already-written file into an admissible
result.  SIGTERM and SIGINT remain fail-stop handlers through postprocessing
and result publication; no deferred postprocessing signal is admissible.
When a prior result is `PIPELINE_INVALID`, its systemd adoption and any
allowlisted adjudication/preparation occur in two different submissions.  The
second, no-estimator submission must revalidate the first result's runner-exit
binding and complete prior adoption chain, bind the newly published invalid
receipt, and prove the transition to exactly the next READY attempt.  It is
not incorrectly required to claim that it dispatched the already-finished
runner, and a missing or forged prior adoption still fails closed.
The pre-start runner check has its own process-exit binding: `ready=true`
requires return code 0, while a structurally valid `ready=false` requires
return code 2.  Any other pairing--including a signal after flushing
`ready=true`--is non-retryable and cannot reach the dispatch claim or estimator
start.

The current host has `Linger=no`; this is explicitly disclosed rather than
silently treated as durable across logout.  Formal preflight therefore requires
the user manager to be running and at least one active login session, and pins
`State`, `Sessions`, and `Linger` in the submission/start receipts.  Exit of the
last session may stop the manager.  If that occurs, v6 is permanently
abandoned; no automatic continuation or retry is authorized.

## HFNet zero-keyframe post-Shutdown watchdog

All HFNet budgets, windows, repeats, and replacement attempts use one frozen
watchdog contract.  The runner samples at a 0.20 s target interval with a
0.25 s maximum and requires 30 continuous seconds of: one ordered and exact
`Shutdown`/target-save sequence; one positive atlas-count line; exactly `N`
unique map rows covering IDs `0..N-1`, all with zero keyframes; no complete or
partial end-of-saving line; no partial stdout tail; and absence (including no
dangling symlink) of both target trajectory files.

Every confirming sample revalidates the unchanged HFNet leader PID, start
ticks, executable, argv, PGID, session, and complete process-group membership.
The sampled Linux state is retained in every member receipt but excluded from
the stable-member projection because a live process may move normally among
`R`, `S`, and `D`.  A live proof itself cannot contain state `Z`.  The final
gate repeats the stable proof twice, then may send one SIGTERM to the exact
PGID.  An atomic gate-entry latch makes the complete proof/signal path
one-shot even under concurrent callers.  The watchdog cannot send SIGKILL or
individual PID signals.  Failure to exit continues under the original 1800 s
total timeout; no grace is added.
The independent watchdog receipt is mandatory and bound into `run_result` and
pipeline evidence.  A proven signal is the algorithm code
`CONFIRMED_ZERO_KF_POST_SHUTDOWN_SAVE_HANG`; any unproven watchdog chain is the
non-retryable pipeline code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.
Because Linux has no atomic pidfd group signal, the residual interval between
the second exact proof and `killpg` is disclosed as a platform limitation.

V6 additionally closes the v5 exit-observation race without relaxing live
identity checks.  Exact-group snapshots are purely observational and never
call `Popen.poll()` themselves; the caller performs the before/after polls.
A snapshot with any scan/read/member error, changed stable identity, or
non-empty wrong executable/argv fails closed immediately.  Only two narrow
terminal-transition shapes may be held until the next already-scheduled
sample: (1) the same sole leader in explicit Linux state `Z`, with executable
and cmdline empty; or (2) the exact group disappears without scan/read error
between the caller polls, including disappearance during the immutable
recheck.  Shape (2) additionally requires the global process scan to contain
no record with the frozen numeric leader PID; a visible PID with changed start
ticks, PGID, session, or non-empty identity is identity drift, never absence.
If that exact Popen child is reaped immediately after the proof or
before the next sample, the receipt records a passive-exit adjudication, the
watchdog sends no signal, and the normal estimator return code remains an
algorithm outcome.  If it is still live, the original proof errors become the
non-retryable watchdog pipeline code.

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
and does not consume a replacement attempt.  From immediately after the
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
reused numeric PID.  A newly seen descendant is admitted only after an atomic
re-read proves both its exact child identity and its exact currently owned
parent identity and parent link.  GPU observations can confirm an already
owned exact identity but can never create ownership from a numeric PID or
PGID.  A GPU row whose `/proc` identity is unreadable or changes start ticks
during the two-read identity check is external and makes the probe unproven
even when its numeric PID belonged to an earlier owned identity; only an
error-free absent `/proc` record may be classified as a stale owned GPU row.
Ownership-set reads and updates are serialized.  Cleanup may signal the
whole process group only while the exact frozen leader identity remains the
unique live leader after recheck; otherwise it can signal only individually
rechecked exact owned identities.  A reused numeric PID or PGID is never a
cleanup target.  PID, start ticks, PGID, executable, and a command-line SHA-256
are recorded for every readable offender.  Probe timestamps, maximum sampling
gaps, errors, and pre/post samples are retained in
`runtime_resource_monitor.json`.  Runtime measurements remain ineligible for
performance claims.

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

## Classification and replacement

An observed external conflicting process or GPU compute application adds
`MIDRUN_EXTERNAL_RESOURCE_INTRUSION`, makes the attempt `PIPELINE_INVALID`, and
is the only code eligible for automatic same-cell replacement.

A proc/GPU probe error or sampling-gap violation adds
`RUNTIME_RESOURCE_MONITOR_UNPROVEN`; it halts the controller for manual
experiment abandonment/review.  The same HALT rule applies to supervised
shutdown/lifecycle failures, estimator identity failures, tag/configuration/
model/control drift, post-run reverification failures, and any unlisted code.
No automatic invalid-attempt receipt or replacement is created for those
persistent/control faults.

At most two additional attempts are pre-registered for each planned cell.
Attempt index 4 is forbidden.  Any pipeline code repeated within a cell halts
immediately even if that code is normally eligible.  The attempt-matrix freeze
must record the allowlist and limits before the first estimator start.

Algorithm failures observed in an externally contaminated attempt are
diagnostic only and excluded from the algorithm denominator.  This exception
does not convert lifecycle/control failures into external faults.

## Cross-arm IMU clock and support freeze

The HFNet runtime input must be regenerated inside the v6 frozen namespace
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
in v6 because it is a window-specific recovery setting.  The v6 VINS runtime
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

## Frozen estimand and statistical unit

The primary endpoint is `CLEAN_SUCCESS`.  A terminal `SUCCESS` that is not
clean and every terminal non-success count as zero; an adjudicated
`PIPELINE_INVALID` attempt is replaced within the same planned cell and is not
a replicate.  No final inference is authorized until all 120 planned cells
have terminal receipts.

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
