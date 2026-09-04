# A10 same-history v4 backend-recovery comparison

Status: `FROZEN_BEFORE_SCORED_RUNS`

Date: 2026-08-24 (Asia/Shanghai)

## Purpose and evidence boundary

This protocol opens three new backend attempts on the previously selected
AQUALOC archaeology A10 development-positive window. It does not regenerate a
frontend and does not continue any v3 backend attempt. The three v4 systems
are:

1. `vanilla_origin_native_image_context`;
2. `klt_external_feature_context`; and
3. `aquafe_external_feature_context`.

The v4 comparison is a backend-runner recovery and a same-window descriptive
check. It is permanently labelled
`PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY`. A fresh user/network namespace
provides a loopback-only ROS network boundary for each backend, but CPU, memory,
disk I/O, and scheduler time are not machine exclusive. Consequently, even a
fully accepted v4 run is not primary paper evidence and cannot support a
winner, ranking, significance claim, or claim of machine-exclusive timing.

This protocol is separate from the sealed A06/H07 comparison and from A10 v1,
v2, and v3. It must not change or relabel any prior receipt.

## Frozen prior-attempt state

The following history is part of the v4 interpretation contract.

- A10 v1 remains an infrastructure failure before the KLT child could read an
  image.
- A10 v2 remains `EXECUTION_INTEGRITY_FAILED` with
  `POSTFLIGHT_PROCESS_PRESENT`; its artifact `PASS` does not make the attempt
  successful.
- v3 `klt_input_adoption` is an accepted byte-preserving adoption of the sole
  predeclared v2 KLT payload. Its accepted receipt is
  `d1db99bbaaa1d3f07584858b863f6f1610dab5e96222537ce63dd1bf00637af0`
  (93,722 bytes).
- v3 `aquafe_build` is an accepted deterministic learned-sidecar build from
  that adopted KLT payload. Its accepted receipt is
  `f17287d343c721a2fa9f7906de6e1c4c27a440704f3f2eec02ada70f398d93fa`
  (98,125 bytes).
- The v3 `vanilla_origin_native_image_context` attempt remains failed. Its
  immutable receipt is
  `49a0acb06211407a05ced876b6a2299a6f52efe8da9fb9d13cc0371519512049`
  (100,879 bytes), with terminal timeout, raw return code `-9`, artifact
  `FAIL`, execution integrity `FAIL`, and overall disposition
  `PROCESS_FAILED`. v4 does not rerun or repair that attempt; it creates a new
  v4 attempt with a new output tree and receipt.
- The v3 external-KLT and AQUA-FE backend attempts remain unclaimed and
  `NOT_STARTED`. Their v3 launch allowances are not consumed. v4 must not run
  them, depend on a v3 backend receipt, or import a partial v3 backend output.

The v4 execution lock and analyzer must independently verify this prior state.
A changed source receipt, a newly created v3 KLT/AQUA backend claim or receipt,
or any v4 input binding to a v3 backend output closes the v4 evidence gate.
The lock freezes the exact two v3 pending-backend output directories and their
four `process_start_claim.json`/`formal_run_receipt_v3.json` leaf paths. Those
four leaves must remain absent at lock build, every lock verification,
immediately before each v4 claim, after that claim and immediately before its
only `Popen`, and again at postflight. Each phase is recorded fail-closed in the
v4 claim or receipt; any leaf type, including a dangling symlink, counts as
present.

## Frozen external frontend authorities

No frontend process runs in v4. The accepted v3 frontend artifacts are frozen
external inputs, not v4 dependencies that may be regenerated or selected after
seeing a trajectory.

| Authority | bytes | SHA-256 |
|---|---:|---|
| v3 KLT `features.bag` | 42,576,500 | `34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f` |
| v3 KLT `frontend_metrics.csv` | 1,003,812 | `ef86317bdb97b272955fe07de8f090c7e2313e4193028d974ecd7e4853030a99` |
| v3 KLT camera YAML | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| v3 KLT `adoption_manifest.json` | 3,620 | `e28de66d047c98db55669838491a3457c802e311eb10394f7f0030a52f7bd07b` |
| v3 AQUA-FE `full_merged.bag` | 42,580,404 | `7b739e0c717ae41c11b07e364e48331d4a34c7786082cdd98bf53e8f58e03754` |
| v3 AQUA-FE `sidecar.bag` | 575,687 | `82e773c5dd0a4a4b451e5a7d9e3803cc18193ad87c7686a777cdced3fbb09497` |
| v3 AQUA-FE `stats.csv` | 350,112 | `cfecc933567e0e62503532f0077ca19a64304994ba57c683a6e6bd0c3bc04da5` |

The accepted AQUA-FE build contains 61 injected observations on 61 affected
method-native feature frames and one remapped learned ID (`10000000`). Those
counts describe the frozen frontend input; v4 must not tune or rebuild it.

The three frozen backend input bindings are:

- vanilla: the byte-pinned A10 raw bag from v1;
- external KLT: the v3 adopted `features.bag`; and
- AQUA-FE: the v3 `full_merged.bag`.

The v4 lock must pin the raw bag, the v3 execution lock, both accepted v3
frontend receipts, all seven frontend artifacts above, the failed v3 Vanilla
receipt, the v4 protocol, supervisor, analyzer, namespace entry, dedicated
backend runner, common-support evaluator, evaluator core, executables,
configuration authorities, and every other source used by a backend.
Because the sourced catkin setup utilities discover workspaces and hooks at
runtime, the lock also pins all four chained `.catkin` markers, the exact 15-file
ROS `profile.d` membership and file identities, the required absence of the
three workspace-local `profile.d` directories, and the `/usr/bin/python3` link
to the pinned `python3.8` interpreter. These dynamic setup inputs are checked at
lock verification, immediately before claim, immediately before `Popen`, and
at postflight.

## Frozen systems

`vanilla_origin_native_image_context` uses the pinned VINS-origin native-image
path in the project's local quality-capable checkout. It is a native-image
context control, not a claim of a pristine upstream binary.

`klt_external_feature_context` replays the frozen v3 adopted KLT/GFTT feature
bag through the same VINS-origin backend.

`aquafe_external_feature_context` replays the frozen v3 AQUA-FE
`full_merged.bag`, which is the same KLT payload plus the causal final-online
XFeat-lineage additions. It uses stock XFeat lineage artifacts generated in
v3; it is not a newly trained underwater model and it is not the older
SuperPoint/LightGlue+LoFTR `proposed_safe` arm.

All three attempts use the same pinned VINS executable and the same relevant
backend settings, including `VINS_MULTIPLE_THREAD=1`,
`WAIT_FOR_VINS_SUBSCRIBERS=1`, `AQUALOC_BODY_T_CAM0_MODE=imu_cam`,
`VINS_TD=-0.053694112369382575`, `VINS_ESTIMATE_TD=0`,
`VINS_MAX_SOLVER_TIME=0.04`, `VINS_MAX_NUM_ITERATIONS=8`, and
`PLAY_RATE=1.0`. Native-image and external-feature ingestion remain different
system contexts and must be disclosed as such.

## Feed and score window

- Dataset: AQUALOC archaeology sequence A10.
- Continuous history: source frames `0..2800`, inclusive.
- Unscored prefix: source frames `0..2399`.
- Fixed scored window: source frames `2400..2800`, inclusive.
- Score timestamps, inclusive:
  `[1542888916043622160, 1542888936039921424]` ns.
- Score duration: 19.996299264 s.
- Native reference: `/aqualoc/colmap_gt` from the pinned raw bag.
- Native reference poses in the score interval: 21.

The external-feature systems publish the method-native odd-frame grid
`1,3,...,2799`; their score subset is `2401,2403,...,2799` (200 messages).
The native-image control consumes the raw image history. These rate and
ingestion differences are properties of the frozen systems, not quantities to
be hidden or retrospectively equalized.

## v4 execution and isolation contract

Large artifacts live under
`/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery`.
Each arm has one new v4 process-launch allowance and zero result-informed
retry. A durable v4 claim precedes the only `Popen`; after a claim, every
catchable exit is committed as an immutable terminal v4 receipt. A failed arm
is retained as failure and is never replaced by a different input, counted as
zero error, or resumed under the same attempt.

Each backend is launched through a lock-pinned
`unshare --user --map-root-user --net` entry. Before executing the backend, the
entry must establish all of the following and publish
`network_namespace_manifest.json` with `O_EXCL` semantics:

- the child user and network namespace identities differ from the frozen host
  namespace identities;
- the only interface is an enabled loopback interface;
- both initial TCP listener tables are empty;
- the item-specific formal ROS port is bindable on `127.0.0.1`;
- the manifest status is `PASS` and its backend-argv digest matches the frozen
  inner command; and
- `machine_exclusive_cpu_scheduling` is explicitly `false`.

The isolation policy is `loopback_only_network_namespace`. Host-network ROS
masters and nodes cannot communicate with the backend namespace, but host
processes may still compete for CPU, RAM, and I/O. Active host-side VINS,
rosbag, roscore, or learned-model work still blocks launch under the frozen host
audit. Only the exact before-claim-baselined orphan `rosmaster`/`rosout` identities may
be recorded as ambient host evidence when the v4 supervisor proves they are
outside the AQUA-FE/v4 paths and unreachable across the namespace boundary.
Any namespace drift, unexpected host process, surviving supervised descendant,
authority change, source-binding change, v3 pending-allowance guard failure, or
postflight violation fails execution integrity.

The dedicated v4 runner must terminate and reap the VINS and roscore process
groups with bounded escalation. A numerically complete trajectory is not an
accepted attempt if the child hangs, cleanup fails, an artifact is missing, or
execution integrity fails.

## Terminal acceptance rule

The analyzer treats a backend as accepted only when the immutable v4 receipt
and an independent readback jointly establish all four conditions:

1. the child started exactly once, was reaped, did not time out, and returned
   raw code 0 (`TERMINAL_PROCESS_RC0`);
2. the complete output tree and all semantic checks pass the artifact contract;
3. execution integrity is `PASS`, including frozen authority/source bindings,
   namespace isolation, bounded cleanup, and postflight; and
4. score usability is `PASS` and exactly matches an independent trajectory,
   log-event, and initialization re-audit.

Partial files, a process return code without a terminal receipt, or any subset
of these four conditions is not acceptance. Each arm remains individually
visible as `PENDING`, `FAILED`, `INVALID`, or `ACCEPTED`; one failure never
becomes another arm's zero-valued result.

## Score-usability gate

Every VINS CSV must satisfy the exact 11-column finite-pose contract with
strictly increasing integer-nanosecond timestamps and valid quaternion norms.
Within the fixed score interval it must:

- contain at least two trajectory rows;
- span at least 70% of the score duration;
- have no adjacent output gap greater than 0.50 s;
- initialize before or within the score interval;
- have `init_success=1` in the pinned legacy APE audit; and
- contain zero attributed solver/tracking failures, restarts, active-map
  resets, or unresolved failure/reset events.

The receipt score layer must equal the independent analyzer re-audit exactly.
Score-usability failure does not rewrite an authentic process return code.

## Common-support analysis

The common-support evaluator may run only after all three new v4 receipts are
accepted and all frozen source/lock/namespace audits pass. It uses one common
1 Hz grid over the fixed score interval with:

- 20 anchored uniform-grid samples;
- maximum reference interpolation bracket 2.5 s;
- maximum estimate interpolation bracket 0.25 s;
- 1 s translation RPE;
- minimum common support of at least 15 jointly supported samples,
  `matched/20 >= 0.70`, and the conservative index `matched/21 >= 0.70`;
- minimum descriptive RPE support of 10 exact 1 s pairs; and
- a formal APE minimum of 30 poses and 10 s.

The score interval has only 21 native reference poses and the uniform grid has
only 20 samples. Therefore the formal APE gate is closed by construction.
Aligned APE values, if the descriptive common-support checks pass, are proxy
diagnostics only. RPE values are descriptive only and are released only with
at least 10 exact 1 s common pairs. The analyzer must preserve the fixed arm
order above and must not sort by an error metric.

Required output names include `uniform_grid_count=20`,
`uniform_common_matched_count`,
`uniform_common_coverage=matched/20`, and
`conservative_fixed_denominator_index=matched/21`. The last value is an index
against the fixed native-reference count; it is not a claim that the numerator
contains native reference rows.

No overall winner, best-system label, ranking, significance test,
failure-as-zero imputation, cross-window mean, or primary-paper claim is
permitted. Any table must state the v4 isolation limitation and the closed APE
gate next to the descriptive values.
