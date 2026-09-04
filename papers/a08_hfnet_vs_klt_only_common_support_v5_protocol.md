# A08 HFNet versus KLT-only common-support analysis v5

Status: **additive candidate only; R03 terminal evidence bound; canonical v5
design freeze, backend lock, dynamic analysis lock, and accuracy all absent**.

This protocol is the predeclared analysis amendment after three distinct
backend infrastructure failures. It does not edit, repair, relabel, rerun, or
replace any frozen v2, v3, or v4 item.

## 1. Fixed five-repeat population

The original KLT population remains, in order:

```text
KLT_R01, KLT_R02, KLT_R03, KLT_R04, KLT_R05
```

The first three indices are permanently consumed:

```text
KLT_R01 = NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT
KLT_R02 = NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT
KLT_R03 = NA_BACKEND_INFRASTRUCTURE_RUNTIME_ENV_AUDIT_CONTRACT_MISMATCH_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT
```

Their failure codes are respectively:

```text
ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9
OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS
LOCKED_ITEM_ENV_OMITTED_OVERLAY_ROS_HOSTNAME_LOCALHOST_LIFECYCLE_AUDIT_MISMATCH
```

Each consumes its original slot, counts neither as valid nor as a scientific
failure, and permits no replay, replacement, renumbering, or best-run
selection. Backend v5 may execute only `KLT_R04` and `KLT_R05`; hence planned
count is five, executable count is two, and maximum valid count is two. The KLT
summary is the coordinate-wise median over every valid R04/R05 receipt, even
when only one is valid.

All five XFeat slots remain
`NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED`. No accepted XFeat frontend
receipt, backend launch, trajectory, joint-mask membership, or learning
contribution claim is permitted.

## 2. Exact R03 forensic boundary

The frozen R03 receipt is 16673 bytes with SHA-256
`8c40956b037acf078a820c0f3fb870d9607818bcd5bdd4a649e6df969a2bdf10`.
It is bound to the 100210-byte backend-v4 execution lock with SHA-256
`e28d61cf17116bc0fade98bf84f0a88f48831bbff442096abf877ef7226e15da`
and to the 25864-byte analysis-v4 design freeze with SHA-256
`2320b6c904fd10c6d2afa435aa771b750d641c50e62ee6f2511fade077e6cd34`.

The receipt is truthfully retained as
`FAILED_BACKEND_REPLAY_NO_REPLACEMENT`. Its one supervisor process exited
normally with raw return code zero, did not time out, drained all owned
processes, completed replay, emitted 2319 `world_T_body` poses, and passed
backend usability, replay-manifest, stable-owner guard, network namespace,
signal-mask, shutdown-stage, and wrapper-signal audits.

It nevertheless has execution integrity `FAIL`, with the exact irreversible
latch
`ARTIFACT_INTEGRITY:VINS_LIFECYCLE_MANIFEST_CONTRACT`. Its artifact contract
has the sole issue
`VINS_LIFECYCLE_GATE:LIFECYCLE_NOT_ACCEPTED,start:environment` and integrity
issue `VINS_LIFECYCLE_MANIFEST_CONTRACT`. The locked item environment omitted
`ROS_HOSTNAME`, whereas the delegated overlay supplied
`ROS_HOSTNAME=localhost` to the wrapper. The lifecycle auditor therefore
compared two differently scoped but otherwise matching environments. This is
an infrastructure audit-contract mismatch, not evidence that the complete
trajectory is scientifically bad.

The only permitted v5 scientific-environment amendment is to add the already
observed overlay value `ROS_HOSTNAME=localhost` to each locked R04/R05 item.
All other scientific, signal-mask, and lifecycle values remain unchanged, and
v5 reuses the exact frozen v4 lifecycle wrapper and signal-mask launcher.

The frozen base artifact auditor must pass, and the frozen v4 artifact auditor
must reconstruct the receipt artifact contract exactly. Both the v4 base
prior-receipt path and strict prior-receipt path must fail with the exact
expected code `PRIOR_EXECUTION_INTEGRITY:KLT_R03`. All 14
output identities, the claim, and the supervisor log are re-opened and bound.
The complete trajectory and diagnostic APE remain evidence of replay
completion only: `trajectory_admitted=false`, and neither may enter the joint
mask, median, ranking, or formal common-support metrics.

## 3. Frozen numerical rules

Analysis v5 inherits the frozen v4/v3 evaluator without changing numerical
semantics:

- 33 exact integer-nanosecond evaluation timestamps;
- `world_T_body` trajectories with deterministic quaternion normalization and
  sign canonicalization;
- one proper fixed-scale SE(3) transform fitted once on HFNet support;
- no Sim(3), scale fitting, per-arm alignment, interpolation, or nearest-time
  substitution;
- one joint mask equal to reference AND HFNet AND every accepted R04/R05 arm;
- at least 30 APE poses over 10 seconds, fixed denominator 33, and at least 70
  percent common coverage;
- six finite nonnegative primary APE/RPE metrics and segmented evo tolerance
  `1e-5` m;
- RPE translation over the frozen one-second interval rule;
- coordinate-wise median over all valid R04/R05 repeats;
- one analysis allowance, no retry, and atomic no-replace publication.

Any formal gate or evidence-integrity failure forces all HFNet and KLT formal
metrics to `NA`. Raw diagnostics cannot substitute for formal results.

## 4. Static design freeze before backend v5

The canonical authority is
`papers/a08_hfnet_vs_klt_only_common_support_v5_design_freeze.json`, schema
`aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v5`, status
`FROZEN_AFTER_R01_R02_R03_INFRASTRUCTURE_FAILURES_BEFORE_R04_R05_BACKEND_AND_ACCURACY`.

It may be published only while every backend-v5 lock, output, runtime,
workspace, R04 receipt, and R05 receipt path is absent. Frozen backend-v4
R04/R05 output, runtime, and workspace paths must also remain absent. Frozen
analysis-v4 dynamic lock, claim, and output paths must remain absent.

The freeze identity-binds:

- frozen analysis-v4 protocol, runner, tests, and design freeze;
- frozen backend-v4 protocol, runner, guard, lifecycle wrapper, signal-mask
  launcher, tests, execution lock, and exact R03 terminal receipt;
- backend-v5 protocol, runner, guard, process-free tests, Python 3.8, real VINS
  binary, and the intentionally reused frozen v4 wrapper and launcher;
- exact R01, R02, and R03 dispositions and evidence, including all 14 complete
  but unaccepted R03 artifact identities;
- the sole v5 environment amendment `ROS_HOSTNAME=localhost`, with every other
  scientific/signal/lifecycle value unchanged;
- accepted KLT frontend, terminal XFeat exclusion, sealed support, evo
  authority, numerical contract, and planned-five/executable-two population.

The claim boundary records zero backend-v5 launches and
`ape_or_rpe_computed_for_v5=false`. That v5-specific flag does not deny the
already existing diagnostic APE from R03. `freeze_sha256` is the compact
canonical SHA-256 after removing only that field.

## 5. Backend and dynamic-lock order

Backend v5 must semantically audit and identity-bind the static analysis-v5
freeze before building its execution lock. Its executable order is exactly R04
then R05, with one supervisor launch per item and no retry or replacement.
Only after the backend-v5 lock and both terminal receipts exist may the dynamic
analysis-v5 lock be built. Dynamic-lock construction binds identities and
semantically audits terminal evidence, but performs no APE/RPE or
common-support evaluation and computes no accuracy.

The one-shot analysis may start only after that dynamic lock. It forms the
joint mask from HFNet and accepted R04/R05 trajectories, runs the unchanged
primary/evo checks, and reports all ten original KLT/XFeat slots.

Creating or testing these candidate files is process-free. It does not
authorize publication of either lock or freeze, backend launch, ROS/VINS,
HFNet, exporter, APE/RPE, or mutation of frozen evidence.
