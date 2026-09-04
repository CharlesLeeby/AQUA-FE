# A09 same-history warm-start v1 backend protocol

Status: `DRAFT_SCAFFOLD_NO_EXECUTION_LOCK_NO_BACKEND_LAUNCH`

Date: 2026-08-26 (Asia/Shanghai)

## Purpose and evidence boundary

This draft defines three one-shot VINS-family backend replays over the frozen
AQUALOC archaeology A09 feed `0..4400`, with source frames `4000..4400`
reserved for descriptive scoring:

1. `vanilla_origin_native_image_context`;
2. `klt_external_feature_context`; and
3. `aquafe_external_feature_context`.

Creating this draft and the two scaffold scripts does not create an execution
lock, claim a backend launch allowance, start ROS/VINS, or read an unfinished
frontend artifact.  The lock builder late-binds both frontend authorities only
after their canonical directories are non-symlink directories and their
immutable, version-specific authorities pass independent rehashing.  KLT uses
its v1 receipt plus a separate execution-strength addendum; AQUA-FE uses its
v2 execution lock, claim, receipt, post-commit outputs, execution-integrity
record, and strict artifact audit.

The comparison is development-only.  ToDesk and ordinary desktop work may
remain active under the user's explicit waiver, but CPU, memory, scheduler,
and disk I/O are not machine exclusive.  Runtime or throughput claims are
forbidden.  Concurrent frontend, ROS replay, SLAM/VIO, or learned-model work
remains launch-blocking.

The scored interval contains only 21 native COLMAP/depth-scale proxy poses.
The 30-pose formal APE gate is therefore closed by construction.  A later
common-support result is descriptive only and cannot establish a winner,
ranking, significance result, held-out claim, or primary-paper result.

## Late-bound frontend gate

The backend execution lock may be built only when all of the following hold:

- `/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/frontends/klt_export`
  is a canonical real directory, not a temporary symlink;
- its `formal_run_receipt_v1.json` reports the accepted KLT stage and binds
  `features.bag`, `frontend_metrics.csv`, the camera YAML, its command,
  environment, producer inputs, and complete artifact audit;
- `papers/a09_samehistory_warmstart_v1_klt_execution_strength_addendum.json`
  exists and independently binds the KLT receipt, claim, and four science
  outputs (including the supervisor log) by exact path, size, and SHA-256;
- the addendum schema is
  `aqua-fe-a09-samehistory-warmstart-klt-execution-strength-addendum-v1`;
  producer status `PASS_POSTHOC_KLT_EXECUTION_STRENGTH_AUDIT` (or the later
  synonymous narrowed/external-verification status) is normalized by this
  contract to `PASS_KLT_EXECUTION_STRENGTH_NARROWED_AND_EXTERNALLY_VERIFIED`
  only after its six bindings and external rehash independently pass;
- the addendum explicitly narrows its evidence to a post-hoc empty-process
  snapshot.  Neither it nor the old receipt's
  `process_group_waited_to_terminal` field is treated as continuous owned-tree
  proof, exactly-once proof, or runtime evidence;
- the corresponding `aquafe_finalonline` is the canonical AQUA-v2 directory,
  with `process_start_claim_v2.json` and `formal_run_receipt_v2.json` under
  schema `aqua-fe-a09-samehistory-warmstart-aquafe-supervisor-v2`;
- the AQUA-v2 receipt reports `PASS_AQUAFE_V2_ACCEPTED`, binds the exact
  `a09_samehistory_warmstart_v2_aquafe_execution_lock.json`, has one RC0 child
  and empty original group and owned descendants, and records `PASS`
  `execution_integrity` plus `PASS_STRICT_AQUAFE_ARTIFACT_AUDIT`;
- its `outputs_postcommit` map exactly binds `full_merged.bag`, `sidecar.bag`,
  `stats.csv`, its v2 claim, and `supervisor_process.log`; the current
  canonical files must independently rehash equal;
- the KLT-v1 receipt input maps remain byte-identical before and after its
  stage, while AQUA-v2 reports `authority_before_after_equal=true` and binds
  every lock identity again;
- absolute KLT-v1 input keys are rebound at their exact absolute path.  Its one
  historical relative key,
  `scripts/run_a09_samehistory_warmstart_v1_frontends.py`, is resolved strictly
  as `ROOT/key`; the lock preserves both recorded key and resolved path and
  rejects `..`, textual aliases, symlink components, or workspace escape;
- the AQUA-v2 receipt's claim identity is allowed exactly one historical path
  rewrite: `.aquafe_finalonline.stage_v2/process_start_claim_v2.json` to the
  canonical `aquafe_finalonline/process_start_claim_v2.json`.  Size and SHA-256
  must be unchanged, `outputs_postcommit` must bind the canonical path, and the
  recorded stage device/inode must equal the committed canonical directory;
- every receipt-bound producer/config/checkpoint and output still matches its
  recorded size and SHA-256; and
- the existing frontend flock can be acquired non-blockingly.

The lock builder records the two accepted frontend authorities dynamically.
The AQUA-v2 producer lock's complete identity map—including runner, builder,
protocol, KLT addendum, model/config code, and dependencies—is rehashed and
carried into the backend contract.  KLT producer inputs are likewise rebound
from its v1 before/after maps.  It never substitutes the earlier A09
`4000..4400` cold-start bags.

## Frozen feed and ingestion contexts

- Continuous camera feed: source frames `0..4400`, inclusive.
- Scored source window: `4000..4400`, inclusive.
- Score timestamps, inclusive:
  `[1542888946038630384,1542888966034698672]` ns.
- Raw topics/counts: camera/IMU/proxy-GT = `4401/44025/213`.
- Method-native feature grid: source frames `1,3,...,4399`, 2200 messages.
- Method-native score subset: `4001,4003,...,4399`, 200 messages.

The Vanilla arm plays the canonical raw bag.  Its VINS configuration subscribes
to `/camera/image_raw`, and its subscriber gate covers the raw image and IMU
topics.  The raw camera, IMU, and GT topics are replayed.

The two external arms do not replay raw images.  Their VINS image topic is
`/unused/image`; the selected `FEATURE_BAG_OVERRIDE` is replayed and carries
`/feature_tracker/feature`, IMU, and GT.  The KLT arm uses the accepted KLT
`features.bag`; the AQUA-FE arm uses the accepted causal `full_merged.bag`.
No `ROSBAG_PLAY_TOPICS` filter is set.

Each arm also freezes explicit causal lineage.  Vanilla points to the raw-v1
materialization; KLT points to `frontend_authorities.klt`; AQUA-FE points to
`frontend_authorities.aquafe`, whose lineage includes the AQUA-v2 execution
lock, claim, receipt, and four accepted science outputs.  The same lineage is
copied into the immutable backend claim and receipt.

All arms use the same pinned local quality-capable VINS-origin backend and the
same relevant settings:

```text
VINS_MULTIPLE_THREAD=1
WAIT_FOR_VINS_SUBSCRIBERS=1
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT=20
AQUALOC_BODY_T_CAM0_MODE=imu_cam
VINS_TD=-0.053694112369382575
VINS_ESTIMATE_TD=0
VINS_MAX_SOLVER_TIME=0.04
VINS_MAX_NUM_ITERATIONS=8
PLAY_RATE=1.0
ROSBAG_PLAY_DELAY=3
ROSBAG_WAIT_FOR_SUBSCRIBERS=0
POST_PLAY_SLEEP=8
BACKEND_REPLAY_ONLY=0
```

`BACKEND_REPLAY_ONLY=0` is intentional: the existing dedicated runner's
strict `1` branch requires a separate sealed `/proc/self/fd` interpreter
contract.  Regeneration is prevented by frozen input existence/identity,
`FORCE_RAW=0`, `FORCE_EXPORT=0`, and exact external bag overrides.

## Commands and run directories

Each backend is entered through the pinned A10 v4 loopback namespace adapter:

```text
/usr/bin/unshare --user --map-root-user --net
  /usr/bin/python3.8
  scripts/enter_samehistory_backend_netns_v4.py
  --output-dir <canonical-arm-output>
  --formal-port 11981
  --host-network-namespace <lock-frozen-host-net>
  --host-user-namespace <lock-frozen-host-user>
  --
  /usr/bin/bash scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh
  <mode> 9 0 4400 <method> <every-n>
```

The arm-specific inner arguments are `origin/klt/1`, `external/klt/2`, and
`external/hybrid_xfeat/2`.  The exact argv, declared environment, effective
environment, host namespaces, command digests, output directories, runtime
directories, and logical run links are generated by the builder and frozen in
the execution lock.

The logical run leaves are:

```text
origin_klt_every1_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_vanilla_origin
external_klt_every2_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_external_klt
external_hybrid_xfeat_every2_systemfair_a09_warmstart_v1_feed0000_4400_score4000_4400_aquafe_finalonline_xfeat_lineage
```

Large outputs and ROS runtime logs remain below the A09 experiment root on
`/mnt/data`.  Each logical workspace leaf is a frozen symlink to one canonical,
non-symlink backend attempt directory.  Backend directories are not promoted
from frontend-style symlink staging because the namespace adapter explicitly
requires a canonical real `--output-dir`.  This constraint selects the
sealed-in-place commit mode described below.

## Storage permission semantics

The effective leaf mount at `/mnt/data` is fail-closed from
`/proc/self/mountinfo` (the covering `autofs` entry is not mistaken for the
leaf) and independently checked with `statfs`: filesystem `fuseblk`, magic
`0x65735546`.  This mount projects regular files as mode `0755`.  A successful
`fchmod(0444)` does not change that observed projection, so POSIX read-only
enforcement is explicitly `false` and permission bits are not an integrity
basis.

The KLT, AQUA-FE, backend attempt, claim, log, and receipt paths are on this
same frozen storage device.  Observed `0755` must not be interpreted as an
instruction to execute bags, trajectories, CSV files, logs, claims, receipts,
or any other science artifact; it is only a FUSE permission projection.  Any
filesystem type, statfs magic, device, requested mode, or observed mode other
than the frozen values fails authority verification.

## Isolation, ownership, and cleanup

Both the existing frontend flock and a backend flock are held for every
backend attempt.  The three arms execute serially.  Each arm receives one
launch allowance, a 900 s timeout, and zero automatic or result-informed
retry.

The item order is executable policy, not documentation.  Before an item may
claim, every earlier item must have a currently valid `ACCEPTED` receipt whose
lock, claim, terminal cleanup, four acceptance layers, sealed science snapshot,
workspace inode, and exact tree all independently revalidate.  Every later
item must have neither claim nor receipt and its prepared output directory must
remain empty.  The checks repeat after claim, immediately before `Popen`, and
postflight.  A retained failed/unusable receipt or a claim without receipt
permanently blocks all later items in this protocol version; it never triggers
a retry or permits a skip.

Before claim and again after claim immediately before `Popen`, the supervisor
requires the absence of active roscore, rosmaster, VINS, rosbag play, either
the A09-v1 frontend producer or A09 AQUA-v2 producer, XFeat sidecar or causal
lineage node, HFNet, LightGlue, SuperPoint, LoFTR, DROID-SLAM, or DPVO
processes.  Long-lived unrelated standalone host `rosout` processes and
ToDesk are allowed under the development waiver because every backend uses a
fresh loopback-only user/network namespace.  They are recorded at each audit
as stable `(pid,start_ticks,role,argv_sha256)` observations and an aggregate
digest; their populations need not be identical before and after.  This waiver
does not permit a runtime or throughput claim.  A fresh namespace must contain
only an enabled loopback interface, no initial TCP listener, and a bindable
`127.0.0.1:11981` endpoint.

The outer child starts in a new session.  Because the dedicated shell starts
roscore and VINS with additional `setsid` calls, process-group cleanup alone
is insufficient.  The supervisor first hash-verifies and then imports the A10
v4 safety implementation, enables `PR_SET_CHILD_SUBREAPER`, records the direct
child baseline and `(pid,start_ticks)` identities, discovers escaped or
reparented descendants, performs bounded TERM/KILL cleanup, and reaps adopted
children.  A terminal receipt cannot pass execution integrity unless:

```text
leader_reaped=true
process_group_empty=true
owned_descendants_empty=true
```

The supervisor never signals a process that is not proven to belong to the
attempt.  Postflight repeats both the frozen-authority audit and the forbidden
process audit.

## Claim, receipt, and acceptance

Each canonical arm directory is empty before claim.  The control files are:

```text
process_start_claim.json
supervisor_process.log
formal_run_receipt_v1.json
```

The immutable claim is durably published with exclusive hard-link semantics
before the only `Popen`.  Once visible, the launch allowance is consumed.  A
claim without a terminal receipt blocks reuse of that attempt and requires a
new protocol version rather than an implicit retry.

Because the namespace adapter requires the real canonical directory at its
frozen `--output-dir`, backend science artifacts are sealed in place.  The
logical workspace symlink's exact target, symlink device/inode, and canonical
output directory device/inode are captured before claim and rechecked after
claim, immediately before `Popen`, and postflight.  After process-tree cleanup
and semantic audit, every present expected output and
`supervisor_process.log` receives a descriptor-level `fchmod(0444)` request
and file fsync.  The required observed mode remains `0755` under the frozen
FUSE semantics.  Each file is then fingerprinted by path, size, SHA-256,
requested mode, observed mode, device, inode, and link count.  Directories are
fsynced and a pre-receipt exact-tree snapshot is recorded.

Receipt publication uses a temporary regular file, an `fchmod(0444)` request,
file fsync, exclusive no-replace hard link, and parent-directory fsync; its
required observed FUSE mode is `0755`.  It is the last mutation.
After publication the supervisor repeats the exact recursive tree audit,
fsyncs nested and arm directories, rehashes every science fingerprint against
the pre-receipt snapshot, rechecks the workspace guard, and reopens the receipt
to prove stable canonical bytes.  The receipt records this entire
sealed-in-place invariant and the exact post-receipt file set.  A later item
independently repeats the same checks on each prior receipt.

The receipt records `requested_mode=0444`, `observed_mode=0755`,
`posix_readonly_enforced=false`, and the actual integrity basis: no-replace
hard-link publication, fsync, exact inode/size/SHA-256 binding, exact tree, and
post-receipt full rehash.  It never claims that mode `0444` was enforced by
this filesystem.

Acceptance requires all four independent layers:

1. exactly one child start, no timeout, raw return code 0, leader reaped, empty
   original process group, and no owned descendant;
2. exact output tree and complete artifact contract `PASS`;
3. frozen inputs/code/config/environment, namespace, cleanup, and postflight
   execution integrity `PASS`; and
4. score usability `PASS`.

A real process return code is never rewritten by an artifact or score failure.
Independent failed arms remain visible and are never imputed as zero error.

## Artifact and score gates

Every arm requires nonempty regular files for its VINS trajectory, VINS log,
legacy APE health audit, replay manifest, generated VINS configuration, A09
camera configuration, VINS environment manifest, roscore provenance, and
network namespace manifest.  KLT additionally requires a byte-identical copy
of its frozen `frontend_metrics.csv`.  Unexpected recursive output entries or
symlinks fail the artifact contract.

The generated A09 camera YAML is fixed at 357 bytes with SHA-256
`045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5`.
The exact generated VINS YAML sizes and hashes are embedded in the lock-builder
contract and depend on the frozen logical run paths.

Every trajectory row must contain the strict VINS 11-field finite-pose
contract, a strictly increasing integer-nanosecond timestamp, and a quaternion
norm in `[0.95,1.05]`.  Within the fixed score interval the trajectory must:

- contain at least two rows;
- span at least 70% of the score duration;
- have no adjacent output gap greater than 0.50 s;
- have `init_success=1` in the pinned legacy health audit;
- initialize before or within the score interval; and
- have zero score-attributed failure, reset/restart, or unresolved failure/reset
  events.

The legacy APE file is a backend-health artifact, not the manuscript-facing
common-support result.  The later evaluator remains
`evaluate_vins_common_support_epoch_v2.py` with fixed-scale SE(3) and no Sim(3).
The lock binds that epoch wrapper, the base evaluator it imports
(`evaluate_vins_common_support.py`), and its shared trajectory core
(`trajectory_eval_core.py`) as three separate static identities; freezing only
the wrapper is not treated as complete evaluator authority.

## Scaffold commands

Read-only lock state, which does not inspect frontends while the lock is absent:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/build_a09_samehistory_warmstart_v1_backend_execution_lock.py status

PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/run_a09_samehistory_warmstart_v1_backends.py status
```

Late-bound preflight and lock creation are reserved for a later authorized turn
after both frontends finish:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/build_a09_samehistory_warmstart_v1_backend_execution_lock.py preflight

PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/build_a09_samehistory_warmstart_v1_backend_execution_lock.py build \
  --authorization-token A09_WARMSTART_V1_BUILD_BACKEND_LOCK_EXACTLY_ONCE
```

Backend launch commands require separate arm-specific, exactly-once tokens
embedded in the supervisor.  They are intentionally not invoked by this
scaffold task.
