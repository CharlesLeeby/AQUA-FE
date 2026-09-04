# A08 recovered-July KLT-only remaining backend replays v3

Status: **additive infrastructure amendment; execution lock absent; no v3
backend item started**.

This amendment exists because the already consumed v2 `KLT_R01` launch exposed
one infrastructure defect after its replay-only guard had successfully
published its sealed-input manifest.  It never changes or deletes a v2 file,
never interrupts that launch, and never authorizes a rerun or replacement of
`KLT_R01`.

## 1. Exact v2 incident boundary

The v2 launch remains the sole launch for repeat index 1.  It must reach its
own terminal receipt naturally.  Only after that receipt passes the frozen v2
deep audit may a v3 lock classify it as

```text
KLT_R01 = NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT
```

The classification additionally requires the frozen supervisor log to contain
both `Opening /proc/self/fd/9` and
`Error opening file: /proc/self/fd/9`, with no accepted backend result.  v2
`KLT_R02` through `KLT_R05` must still be completely absent.  A missing,
incomplete, integrity-failed, or semantically different R01 receipt blocks the
v3 lock rather than being repaired or inferred.

The exact infrastructure failure code is
`ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9`.  The R01 receipt,
supervisor log, zero-byte `vins_output/vio.csv`, and zero-byte `ape.txt` are all
identity-bound; both empty outputs must remain rejected by the frozen v2
artifact audit.

R01 consumes one of the original five declared repeat indices.  It is never
rerun, renumbered, or replaced.  The final report must show all five declared
outcomes, report R01 as `NA`, report the valid count explicitly, and summarize
only valid results from R02--R05.  At most four valid KLT repeats can result
from this amendment.

## 2. Root cause and process-free evidence

ROS Noetic uses this two-stage `rosbag play` chain:

```text
/opt/ros/noetic/bin/rosbag
  -> rosbag.rosbag_main.play_cmd
  -> subprocess.Popen([/opt/ros/noetic/lib/rosbag/play, ...])
```

The local `rosbag_main.py` invokes `subprocess.Popen(cmd)` without `pass_fds`.
Python 3 closes non-standard descriptors by default on POSIX.  Therefore the
C++ player interprets `/proc/self/fd/9` relative to itself after descriptor 9
has been closed.  The guard still owns the accepted inode, but the C++ player
cannot reach it through its own `/proc/self` directory.

An isolated, non-formal probe used a fresh user namespace, a fresh loopback-only
network namespace, port 12082, a temporary ROS home under `/tmp`, no VINS, and
the accepted bag opened read-only on descriptor 9 by a stable parent Bash
process.  Its exact qualitative result was:

```text
/proc/self/fd/9              -> FATAL Error opening file
/proc/<stable-owner>/fd/9    -> Opening ...; No messages on probe topic; exit
```

Both invocations returned shell status zero.  Thus the ROS Python wrapper also
does not propagate the C++ player's failure code; formal acceptance must remain
artifact- and log-gated.  A simpler Python-to-subprocess negative/positive
probe independently showed the child lacked `/proc/self/fd/9` while
`/proc/<stable-owner>/fd/9` reopened the exact source inode.

The v3 lock binds the local ROS Python entry, `rosbag_main.py`, and C++ player
identities.  These probes are infrastructure validation only: they produce no
trajectory or accuracy evidence and do not consume a formal repeat.

## 3. Additive stable-owner FD guard

The new guard is:

`scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v3.sh`.

It retains read-only descriptors 6--11 in one stable Bash owner for the entire
delegated backend call.  It verifies every accepted identity from the opened
descriptors, records the owner PID, and passes only paths of the form
`/proc/<owner-pid>/fd/<n>` to the recovered-July shell.  The owner remains
alive while every descendant reopens those paths.  No PID namespace is
created, so the same numeric owner PID is visible to the ROS Python wrapper,
C++ player, and evaluator.  The owner PID is also the one-shot supervisor
process PID and is checked in the terminal deep audit.

The guard manifest is published and fsynced before delegation.  It records the
accepted pathname, size, SHA-256, device, inode, descriptor number, owner PID,
and stable owner path for all six inputs.  Before delegation, every stable
owner path is reopened and reverified.  Child-relative `/proc/self/fd/*` data
paths are forbidden.  The accepted feature path is never writable, raw
reconstruction and frontend export remain disabled, and no exporter command
exists in the guard.

## 4. Independent v3 campaign

The v3 authorities are:

- this protocol;
- `scripts/run_a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v3.py`;
- the v3 stable-owner guard above;
- `papers/a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v3_execution_lock.json`;
- output root
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_remaining_replays_v3`;
- runtime root
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/runtime/backend_klt_only_remaining_replays_v3`.

The executable order is exactly:

```text
KLT_R02, KLT_R03, KLT_R04, KLT_R05
```

Each has a new v3 output, runtime, ROS home/log, tag, workspace symlink, user
namespace, and loopback-only network namespace.  Backend and history settings
remain the frozen v2 values: accepted KLT attempt002 input, source indices
0--4660, every 2, `VINS_MULTIPLE_THREAD=0`, formal internal port 11981, and
single-thread BLAS/OpenMP settings.

The lock token is
`A08_BUILD_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V3_LOCK_AFTER_R01_INFRA_FAILURE`.
Item tokens are
`A08_KLT_ONLY_REMAINING_BACKEND_REPLAYS_V3_RUN_KLT_R02_EXACTLY_ONCE` through
`...R05...`.  Each claim is consumed before the sole supervisor `Popen`.
There is no automatic retry, replacement, result-dependent rerun, or fallback.

## 5. Lock and acceptance gates

Building the v3 lock is forbidden until all of these independently pass:

1. the accepted KLT frontend and terminal XFeat exclusion authorities still
   pass the frozen v2 validation;
2. the v2 execution lock and all code/protocol authorities retain exact
   identity;
3. v2 R01 has a stable terminal failure receipt with execution integrity
   `PASS`, the exact FD-scope failure signature, and no accepted result;
4. all v2 R02--R05 paths are absent;
5. all v3 output, runtime, and workspace paths are absent;
6. the ROS entry, dispatch source, C++ player, v3 runner, guard, and this
   amendment are regular identity-bound files.

There is one additional order gate.  Before the backend v3 execution lock can
be built, the additive analysis-v3 static design freeze
`papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json` must be
published.  The backend runner does not hard-code that future file's digest;
it opens and semantically audits the freeze, verifies that it identity-binds
this v3 protocol, runner, guard, process-free tests, the exact v2 R01 receipt
and v2 execution lock, the five-repeat planned population, and R01's exact NA
disposition.  The resulting backend execution lock then binds the design
freeze's observed path, size, and SHA-256.  This prevents R02 accuracy from
being generated before its population and analysis rules are frozen.

For a v3 item, success still requires the full frozen backend usability gates,
not merely return code zero.  The stable-owner guard and replay manifests must
agree on owner PID and `/proc/<owner>/fd/9`; the owner must equal the receipt's
sole supervisor PID.  An authority or evidence-integrity failure latches and
blocks later items.  A scientific/backend failure is
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT`; a later predeclared item may continue
only when execution integrity remains `PASS`.

Creating these additive files and running their process-free tests neither
builds the lock nor launches ROS, VINS, an exporter, HFNet, or a formal backend
item.
