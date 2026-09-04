# A08 recovered-July KLT-only final remaining backend replays v4

Status: **additive lifecycle-infrastructure amendment; execution lock absent;
no v4 backend item started**.

This amendment preserves the consumed v2 `KLT_R01` and v3 `KLT_R02` launches,
modifies no frozen v2/v3 authority, and permits neither launch to be rerun or
replaced.  It defines only the three still-unconsumed repeat indices
`KLT_R03`, `KLT_R04`, and `KLT_R05`.

## 1. Consumed-repeat boundary

The five originally declared KLT outcomes remain the population:

```text
KLT_R01 = NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT
KLT_R02 = NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT
KLT_R03 = predeclared v4 item
KLT_R04 = predeclared v4 item
KLT_R05 = predeclared v4 item
```

The R01 failure code remains
`ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9`.  The R02 failure code
is
`OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS`.

R02 completed feature-bag playback, trajectory generation, diagnostic APE/RPE,
and replay-manifest publication before the frozen overlay entered its EXIT
cleanup.  That cleanup sends SIGTERM to the real VINS PID and performs an
unbounded `wait` before it touches roscore.  Read-only process evidence showed
SIGTERM pending and masked in the real VINS process while the overlay slept in
`do_wait`.  The source of that mask is the supervisor's launch-time
`blocked_signals()` scope: HUP, INT, and TERM were inherited through guard,
overlay, roscore, and VINS.  The v3 one-shot supervisor therefore reached its
own 900-second timeout naturally and published its terminal receipt.  Nothing
in v4 interrupted, repaired, adopted, or scored R02.

The v4 preflight must reopen the exact R01 and R02 authorities.  For R02 it
requires the v3 base terminal-receipt reconstruction to pass, receipt status
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT`, execution integrity `PASS`, timeout
true, raw return code `-9`, and the exact complete trajectory/APE/replay
artifacts.  It also binds the expected failure of the stricter v3 wrapper audit
as `PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:KLT_R02`.  The receipt's artifact
contract is `FAIL`, not `PASS`: because the frozen overlay never returned from
cleanup, the v3 guard never reached its post-return append of seven provenance
keys.  The replay manifest therefore has the exact seven-key missing set while
evidence-tree integrity, backend usability, and the 2319-pose trajectory are
complete.  No R02 artifact is admitted as a formal result.  Every v3 R03--R05
path must remain absent.  Until the terminal R02 receipt exists and satisfies
all of these gates, v4 remains `WAITING`.

R01 and R02 both count toward the planned population but not the valid count.
They have no v4 authorization token.  The maximum possible valid KLT count is
three, and every final table must report all five dispositions and the valid
count explicitly.  No best-repeat selection is permitted.

## 2. Minimal signal and lifecycle repair

The stable-owner Bash remains the sole supervisor child and continues holding
FDs 6--11.  Its direct delegated child is the identity-pinned
`scripts/run_a08_unblocked_overlay_exec_v4.py`, with fixed interpreter
`/usr/bin/python3.8`.  The launcher confirms its parent is the stable-FD owner,
records the inherited mask, unblocks HUP/INT/TERM, atomically publishes
`overlay_signal_mask_manifest_v4.json`, and `execve`s `/usr/bin/bash` with the
unchanged frozen overlay shell and exact six arguments.  The launcher PID thus
becomes the overlay PID; overlay, roscore, and the VINS wrapper inherit the
unblocked control signals.  This is required because wrapping only VINS would
leave the subsequent frozen `kill roscore; wait roscore` exposed to the same
inherited-mask hang.

The frozen recovered-July overlay remains byte-identical.  The second repair
changes its locked `VINS_NODE_BIN` value from the real binary to:

`scripts/run_a08_vins_node_lifecycle_wrapper_v4.py`.

The wrapper verifies its own identity, the exact real VINS binary identity,
the generated configuration binding, item/output/workspace identities, and
the single real VINS argument before it starts one real child.  The real child
receives the same config argument, inherited working directory, ROS endpoint,
and frozen scientific VINS/thread environment.  There is no restart path.

The wrapper explicitly unblocks SIGTERM and SIGINT in itself.  When the frozen
overlay sends TERM to the wrapper after replay and evaluation, the wrapper
uses this strictly bounded sequence:

```text
SIGINT to real VINS; wait at most 1.0 s
SIGTERM to real VINS if still alive; wait at most 0.5 s
SIGKILL to real VINS if still alive; reap within at most 2.0 s
```

Thus the total shutdown bound is 3.5 seconds.  The wrapper exits successfully
only after the real child is reaped, allowing the unchanged overlay to proceed
to its existing roscore cleanup.  A natural VINS exit before overlay TERM, a
second launch, a missing manifest, or failure to reap is a backend/artifact
failure, not a retry trigger.

Before replay, the wrapper atomically publishes
`vins_lifecycle_start_manifest_v4.json`, binding wrapper/child PIDs, child start
ticks, process group/session, wrapper and real-binary identities, config,
argv, working directory, selected scientific environment, and the escalation
policy.  Before it exits, it atomically publishes
`vins_lifecycle_terminal_manifest_v4.json`, binding the start manifest,
received signal, every escalation stage, child return code, and confirmed
reap.  Both manifests belong to the closed evidence tree and must pass semantic
audit.  The wrapper PID must be the overlay-launched VINS PID; the child PID
must match both manifests and the one real-child launch.

## 3. Independent v4 campaign

The additive authorities are:

- this protocol;
- `scripts/run_a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v4.py`;
- `scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v4.sh`;
- `scripts/run_a08_vins_node_lifecycle_wrapper_v4.py`;
- `scripts/run_a08_unblocked_overlay_exec_v4.py`;
- `scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v4.py`;
- `papers/a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v4_execution_lock.json`;
- output root
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_remaining_replays_v4`;
- runtime root
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/runtime/backend_klt_only_remaining_replays_v4`.

The only executable order is:

```text
KLT_R03, KLT_R04, KLT_R05
```

Every item has a new v4 output, runtime, ROS home/log, tag, workspace symlink,
user namespace, and loopback-only network namespace.  It retains the accepted
KLT attempt002 input, source indices 0--4660, every 2, stable-owner FD replay,
formal internal port 11981, `VINS_MULTIPLE_THREAD=0`, and single-thread
BLAS/OpenMP settings.

The terminal receipt is `formal_run_receipt_v4.json`, schema
`aqua-fe-a08-recovered-july-backend-klt-only-remaining-receipt-v4`.  Each item
has one claim before one supervisor `Popen`, no retry, no replacement, and no
renumbering.  Scientific failure may permit the next predeclared item only when
execution integrity remains `PASS`; an integrity failure blocks the campaign.
The single canonical lock path is the path listed above; preflight, lock build,
verification, and execution reject every alternate `--lock` path, preventing a
second authority from being published.

## 4. Analysis-before-backend order gate

Before a backend-v4 execution lock can be built, the additive static analysis
freeze must exist at:

`papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json`.

Its schema is
`aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v4`, and its status
is
`FROZEN_AFTER_R01_R02_INFRASTRUCTURE_FAILURES_BEFORE_R03_R05_BACKEND_AND_ACCURACY`.

The backend runner must semantically verify that the freeze identity-binds the
v4 protocol, runner, guard, lifecycle wrapper, signal-mask launcher, fixed
Python 3.8 interpreter, real VINS binary, process-free tests, the v3 analysis
freeze, v3 execution lock, and exact R02 terminal receipt.  It must
freeze planned count 5, v4 order R03--R05, maximum valid count 3, both consumed
NA dispositions, zero v4 launches, and no accuracy computation.  The future
backend execution lock then binds the observed freeze path, size, and SHA-256;
the freeze digest itself is not hard-coded into the runner.

## 5. Non-formal lifecycle probe

An isolated `/tmp` tree probe first blocked HUP/INT/TERM in a dummy
supervisor-like owner.  The real launcher observed all three inherited blocks,
removed them, and exec'd a non-ROS dummy overlay.  Both the real VINS wrapper
and a signal-responsive dummy roscore reported no inherited control-signal
blocks.  The wrapper's non-ROS child deliberately masked SIGINT and SIGTERM;
the wrapper launched it once, received TERM, executed
SIGINT--SIGTERM--SIGKILL, reaped it, and allowed the dummy overlay to clean up
its roscore child.  The complete tree returned zero in 1.667 seconds.  This
probe validates signal/lifecycle control only and produces no trajectory or
accuracy evidence.

Creating and testing these additive files does not build a v4 lock or launch
ROS, VINS, an exporter, HFNet, or a formal backend item.
