# A08 HFNet versus KLT-only common-support analysis v4

Status: **additive candidate only; R02 terminal identity bound; static design
freeze absent; backend-v4 authorities not yet frozen; no v4 lock or accuracy**.

This protocol never edits or replaces a frozen v2/v3 authority or interrupts
the active v3 R02 supervisor.  It is the predeclared analysis amendment for the
case in which R02 naturally terminates with execution integrity `PASS` but is
not accepted because the overlay cleanup blocks while waiting for a VINS
process that masks `SIGTERM`.

## 1. Five planned slots, two permanent infrastructure NAs

The KLT population remains exactly

```text
KLT_R01, KLT_R02, KLT_R03, KLT_R04, KLT_R05
```

R01 retains the frozen disposition

```text
NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT
```

and failure code
`ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9`.

If and only if the natural v3 terminal receipt passes all gates below, R02 has
the exact disposition

```text
NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT
```

and failure code
`OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS`.

R01 and R02 permanently consume their original indices.  Neither is rerun,
replaced, renumbered, counted as valid, or admitted to the joint mask or KLT
median.  R02 differs from R01: its bag replay, trajectory, diagnostic APE, and
manifests may be complete, but its one-shot transaction did not satisfy the
runtime/lifecycle acceptance contract.  Complete artifacts are therefore
retained and identity-bound as failure evidence, never promoted to an accepted
trajectory.

Backend v4 executes only R03--R05.  Thus planned count is five, executable v4
count is three, and maximum valid count is three.  Only a deeply audited v4
receipt with `PASS_BACKEND_REPLAY_ACCEPTED` contributes a trajectory.  The KLT
summary uses every valid R03--R05 repeat; best-run selection and replacement
are forbidden.

XFeat remains
`NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED`, with no accepted frontend
receipt, backend run, trajectory, accuracy, or learned-contribution claim.

## 2. R02 terminal evidence gate

The natural R02 receipt is exactly 12840 bytes with SHA-256
`022dd34eff25edf3e012ae6ea81d691c20351525d3fee964121366779d69bf2d`.
No inferred path or reconstructed receipt is accepted.

The R02 audit then requires all of the following:

- frozen backend-v3 execution lock identity and deep `prior_receipt` audit;
- terminal status `FAILED_BACKEND_REPLAY_NO_REPLACEMENT`;
- one consumed launch, zero retries, and no replacement;
- execution integrity `PASS`, clear irreversible latch, stable claim and
  workspace, and all owned processes drained;
- `runtime.timed_out=true` and `raw_return_code=-9`;
- base backend `prior_receipt` audit `PASS`, while the stricter v3 wrapper audit
  must fail with exactly
  `PRIOR_STABLE_FD_OWNER_REPLAY_BINDING:KLT_R02`;
- artifact contract `FAIL` with exactly one issue: the replay manifest lacks
  the seven post-return provenance fields `accepted_feature_bag`,
  `accepted_feature_bag_sha256`, `accepted_feature_bag_size_bytes`,
  `sealed_fd_owner_pid`, `sealed_play_bag`, `stable_owner_fd_guard`, and
  `strict_replay_only_fd_guard`;
- that manifest failure is retained, not repaired: the v3 guard could append
  those fields only after the overlay returned, but blocked cleanup prevented
  return before the supervisor timeout;
- evidence-tree integrity remains true, integrity issues remain empty, and
  every expected output identity is present and live;
- complete `world_T_body` trajectory with exactly 2319 rows;
- backend usability, stable-owner guard, and isolated network manifest are
  `PASS`; replay-manifest semantic status is the exact expected legacy-schema
  `FAIL` above;
- exact process-log and artifact hashes recorded in the additive freeze.

These checks establish complete replay followed by lifecycle failure while
truthfully retaining the legacy-manifest failure.  They do not accept the R02
trajectory or use its diagnostic APE as common-support accuracy.

## 3. Numerical protocol inherited without change

Analysis v4 identity-pins the frozen analysis-v3 runner, which in turn
identity-pins the v2 numerical/transaction engine.  The following remain
unchanged:

- 33 exact integer-nanosecond evaluation timestamps;
- 1 Hz reference/evaluation grid and 10 Hz estimate source;
- 2.5 s reference and 0.25 s estimate interpolation-gap limits;
- zero time offsets and the same full-precision `body_T_cam0` for every arm;
- proper fixed-scale SE(3), never Sim(3) or scale fitting;
- one joint mask equal to reference AND HFNet AND every accepted R03--R05 arm;
- at least 30 APE poses over 10 s, fixed denominator 33, common coverage at
  least 0.70, and at least ten 1 s RPE pairs;
- six finite nonnegative primary metrics and segmented evo tolerance `1e-5` m;
- all formal HFNet/KLT metrics become NA if any population, support, evo, or
  execution-integrity gate fails;
- a single analysis allowance, no retry, post-authority integrity recheck, and
  atomic no-replace terminal publication.

The coordinate-wise KLT median is over all valid R03--R05 repeats only.
Technical repeats are not independent samples.

## 4. Static design freeze before backend v4

The one-shot static authority is

`papers/a08_hfnet_vs_klt_only_common_support_v4_design_freeze.json`, with schema
`aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v4` and status
`FROZEN_AFTER_R01_R02_INFRASTRUCTURE_FAILURES_BEFORE_R03_R05_BACKEND_AND_ACCURACY`.

It may be published only after R02 passes the exact terminal gate and while all
backend-v4 lock, output, runtime, workspace, and R03--R05 receipt paths are
absent.  Every unused backend-v3 R03--R05 output, runtime, and workspace path
must also remain absent.  Frozen v2/v3 dynamic analysis lock, claim, and output
paths remain absent.

The freeze binds:

- analysis-v4 protocol, runner, tests, and the inherited numerical stack;
- frozen analysis-v3 protocol, runner, tests, and canonical design freeze;
- frozen backend-v3 protocol, runner, guard, tests, execution lock, and exact
  R02 terminal receipt;
- backend-v4 protocol, runner, replay guard, signal-mask launcher, VINS
  lifecycle wrapper, tests, Python 3.8 executable, and real frozen VINS binary;
- exact R01 and R02 evidence blocks, including every complete-but-unaccepted
  R02 artifact identity;
- accepted KLT frontend, terminal XFeat exclusion, sealed support, and evo
  authority;
- the planned-five/executable-three/maximum-valid-three population contract.

The claim boundary truthfully records that R02 diagnostic artifacts already
exist and were opened only for identity/lineage exclusion.  The field
`ape_or_rpe_computed_for_v4=false` means analysis v4 computed no common-support
accuracy; it does not
deny the already existing R02 diagnostic APE.  No backend-v4 lock, backend-v4
item, ROS/VINS process, dynamic analysis lock, or analysis-v4 metric exists at
freeze time.

`freeze_sha256` is the compact canonical SHA-256 after removing only that
field.  Creating or testing candidate source files does not publish it.

## 5. Backend-v4 and final analysis order

The v3 supervisor blocks `SIGHUP`, `SIGINT`, and `SIGTERM` around `Popen`; the
guard, overlay, roscore, and VINS descendants inherit that mask.  A VINS-only
wrapper would therefore leave later overlay cleanup vulnerable when it waits
for roscore.  Backend v4 identity-binds a signal-mask launcher that first
unblocks all three signals, then `execve`s the frozen overlay while the stable
owner Bash guard remains alive and retains the accepted FDs.  It separately
identity-binds a lifecycle wrapper that converts the overlay's VINS termination
request into `SIGINT`, waits a short bounded grace interval, then uses
`SIGKILL` if necessary and reaps the process.  Python 3.8 and the actual VINS
binary identities are frozen as part of the same chain.  This infrastructure
correction does not authorize R02 replay.  Backend-v4 executable order is
exactly R03, R04, R05, with one supervisor launch per item and no retry or
replacement.

The backend-v4 execution lock must semantically audit and identity-bind the
analysis-v4 static freeze before any item starts.  Only after its lock and all
three terminal receipts exist can the dynamic analysis-v4 lock be built.
Building that lock binds identities and dispositions only; it cannot load
trajectories or compute accuracy.

The one-shot analysis can begin only after the dynamic lock.  It forms the
joint mask from HFNet and accepted R03--R05 trajectories, runs the unchanged
primary/evo checks, and reports all ten original KLT/XFeat slots.  R01 and R02
remain explicit infrastructure NA rows in JSON and CSV regardless of their
artifact contents.

## 6. Candidate-only boundary

Until backend-v4 authorities are stable and the candidate passes independent
review, only source editing, Python compilation, process-free tests,
path/identity inspection, and read-only preflight are permitted.  It is
forbidden to repair the frozen R02 manifest, publish the v4 static freeze,
build either v4 lock, start a v4 backend item, or compute analysis-v4 APE/RPE.
