# A08 HFNet versus KLT-only common-support analysis v3

Status: **additive analysis amendment drafted; static design freeze absent;
backend-v3 execution lock absent; no v3 accuracy computed**.

This protocol is additive.  It never modifies, replaces, or reinterprets the
frozen analysis-v2 protocol, runner, tests, design freeze, backend-v2 lock, or
the consumed `KLT_R01` terminal evidence.  It exists because the sole v2 R01
launch ended with execution integrity `PASS` but no replay and no accepted
trajectory after `/proc/self/fd/9` was closed across the ROS Python-to-C++
process boundary.

## 1. Fixed population and dispositions

The planned KLT population remains exactly five declared repeats:

```text
KLT_R01, KLT_R02, KLT_R03, KLT_R04, KLT_R05
```

R01 is permanently assigned the exact disposition

```text
NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT
```

It is not a valid repeat, not a scientific/backend result failure, and never
enters the joint mask.  Its supervisor launch consumed the R01 allowance, but
the bag replay did not start.  It is never rerun, replaced, renumbered, or
silently removed from the planned denominator.

The independent backend-v3 executable population is exactly R02--R05.  Only a
terminal `PASS_BACKEND_REPLAY_ACCEPTED` among those four can count as valid or
provide a trajectory.  A terminal scientific/backend failure remains NA and
is not replaced.  An execution-integrity failure blocks the campaign and the
analysis authority.  Therefore the maximum possible valid KLT count is four.
Every report must show planned count 5, valid count, failed/NA count, the exact
R01 disposition, and all original five KLT plus five XFeat slots.

XFeat remains excluded with the exact disposition

```text
NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED
```

No accepted XFeat receipt exists, no XFeat backend item was launched, and no
XFeat accuracy, learned-contribution claim, joint-mask membership, fallback
trajectory, or fabricated replacement is permitted.

## 2. Frozen numerical protocol inherited unchanged

The v3 runner identity-pins and imports the frozen analysis-v2 engine.  It does
not fork or relax the numerical protocol:

- the evaluation grid contains exactly 33 integer-nanosecond timestamps;
- reference, HFNet, and every accepted KLT repeat use the same 1 Hz grid;
- reference interpolation gap is at most 2.5 s and estimate interpolation gap
  is at most 0.25 s;
- all time offsets are zero;
- the same full-precision `body_T_cam0` extrinsic is applied to every arm;
- alignment is proper fixed-scale SE(3), never Sim(3) or scale fitting;
- one joint validity mask is `reference AND HFNet AND every accepted KLT
  repeat`; R01, failed R02--R05, and XFeat are excluded before it is formed;
- APE needs at least 30 poses spanning at least 10 s;
- common coverage uses the fixed denominator 33 and must be at least 0.70;
- 1 s RPE needs at least 10 valid pairs;
- all six primary metrics must be finite and nonnegative;
- the segmented `evo` cross-check has absolute tolerance `1e-5` m;
- any population, support, evo, or execution-integrity gate failure makes all
  formal HFNet/KLT metrics NA.

When gates pass, KLT is summarized by the coordinate-wise median over **all**
valid accepted R02--R05 repeats.  Best-run selection, outcome-dependent
selection, replacement, and treating technical repeats as independent samples
are forbidden.

## 3. Static design freeze before backend v3

The static authority is

`papers/a08_hfnet_vs_klt_only_common_support_v3_design_freeze.json`.

It has schema
`aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v3` and status
`FROZEN_AFTER_R01_INFRASTRUCTURE_FAILURE_BEFORE_R02_R05_BACKEND_AND_ACCURACY`.
It may be published exactly once only after the v2 R01 receipt passes deep
audit, and only while all backend-v3 lock, output, runtime, workspace, and
R02--R05 receipt paths remain absent.  The frozen v2 dynamic analysis lock,
claim, and output and the earlier legacy campaign must remain absent.
Every old backend-v2 `KLT_R02`--`KLT_R05` output, runtime, and workspace path
must also remain absent; the freeze records all twelve observations and its
live audit requires the recorded values to be `ABSENT`.

The freeze binds current identities for the analysis-v3 protocol, runner, and
tests; the frozen analysis-v2 authorities and numerical stack; and, under the
following exact keys required by the backend-v3 order gate:

```text
backend_v3_protocol
backend_v3_runner
backend_v3_guard
backend_v3_process_free_tests
v2_r01_terminal_receipt
v2_execution_lock
```

Its `prior_r01` block binds the exact receipt and v2 lock, records deep terminal
audit `PASS`, empty VIO, empty `ape.txt`, no accepted artifact, and no rerun or
replacement.  It records the infrastructure cause as
`ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9`; that code is evidence
classification, never an accuracy result.  Its
design contract fixes the five-item planned order, the four-item v3 executable
order, maximum valid count four, and R01 exclusion.  Its claim boundary records
that no backend-v3 execution lock or item exists, no v3 ROS/VINS process was
started, and no APE or RPE was computed.  `freeze_sha256` is the canonical
compact SHA-256 of the payload after removing only that field.

Creating the protocol, runner, and tests does not itself publish this freeze.
Publication must wait until all four backend-v3 candidate files and their
process-free tests are stable and independently reviewed.

## 4. Backend-v3 and dynamic-lock order

The backend-v3 build-lock transition independently audits the static design
freeze before it can publish its own execution lock.  It then runs only
R02--R05 with one authorization token and one supervisor allowance per item.

The analysis-v3 dynamic lock is

`papers/a08_hfnet_vs_klt_only_common_support_v3_execution_lock.json`.

It cannot be built until the backend-v3 execution lock and all four R02--R05
terminal receipts are regular files and pass their backend authority's deep
audit.  The lock binds the static freeze, R01 evidence, four backend terminal
receipts, every accepted trajectory identity, frontend exclusion, support
inputs, numeric code, and evo authority.  Building it reads identities and
terminal dispositions only: it does not load trajectories, form a mask, or
compute accuracy.

The dynamic lock reports the planned count of five and valid count from R02--
R05 only.  Its creation token is

```text
A08_BUILD_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V3_LOCK_AFTER_FOUR_TERMINALS_BEFORE_ACCURACY
```

## 5. One-shot analysis and integrity latch

Only the canonical dynamic lock can authorize the one-shot analysis token

```text
A08_RUN_HFNET_VS_KLT_ONLY_COMMON_SUPPORT_V3_EXACTLY_ONCE_NO_RETRY
```

The claim is atomically published before any trajectory is opened for
accuracy.  There is no automatic retry or replacement analysis.  Staging,
numeric evaluation, evo, post-authority verification, artifact identity
capture, and no-replace terminal publication remain inside the frozen v2
transaction boundary.  Any post-claim error is terminalized with formal values
NA; uncommitted partial evidence cannot become a formal result.

The read-only terminal audit recomputes the primary result from the locked
inputs, validates the integer-nanosecond grid and CSVs, rechecks evo, rebinds
the ten-slot population, and verifies the post-authority and claim-stability
integrity latch.  R01 must remain infrastructure NA in both JSON and the repeat
table.  A result is interpretable only together with its terminal receipt.

## 6. Current non-execution boundary

At this drafting stage it is permitted to run Python compilation,
process-free unit tests, identity inspection, and read-only preflight.  It is
forbidden to publish the static design freeze before backend-v3 candidate
identities are stable, build either v3 lock, invoke ROS/VINS/HFNet, or compute
APE/RPE.  No file from either frozen v2 campaign may be edited or deleted.
