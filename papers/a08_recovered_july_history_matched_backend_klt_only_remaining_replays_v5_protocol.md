# A08 history-matched KLT backend remaining-replay protocol v5

Status: candidate protocol. It becomes immutable when the analysis-v5 static
design freeze is published; the later backend-v5 execution lock binds that
already-frozen identity again. No v5 backend process may start before both
authorities exist.

## 1. Purpose and scientific boundary

This additive protocol governs only `KLT_R04` and `KLT_R05` in the original
five-repeat A08 KLT control. The declared population remains five repeats:
`KLT_R01` through `KLT_R05`. The first three slots are permanently consumed
infrastructure NAs and are never retried or replaced. Consequently, the
maximum possible number of valid KLT repeats is two.

This protocol does not change the sequence, time interval, image cadence,
KLT frontend, accepted KLT feature bag, camera calibration, IMU data, ground
truth, backend binary, VINS configuration, support-mask rule, accuracy
evaluator, or aggregation rule. It does not create an accuracy claim. Accuracy
remains hidden until both v5 items have terminal receipts and a separate
dynamic analysis lock has been published.

The learned XFeat arm remains the frozen structural frontend failure and its
backend accuracy remains `NA`. No learned-frontend contribution claim is
permitted from this campaign.

## 2. Consumed repeat slots

The following dispositions are terminal, count as zero valid repeats, and
permit neither rerun nor replacement:

- `KLT_R01`:
  `NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT`;
  failure code
  `ROSBAG_PYTHON_SUBPROCESS_CLOSE_FDS_DROPPED_SEALED_FD9`.
- `KLT_R02`:
  `NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT`;
  failure code
  `OVERLAY_CLEANUP_WAIT_BLOCKED_ON_SIGTERM_MASKED_VINS_PROCESS`.
- `KLT_R03`:
  `NA_BACKEND_INFRASTRUCTURE_RUNTIME_ENV_AUDIT_CONTRACT_MISMATCH_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT`;
  failure code
  `LOCKED_ITEM_ENV_OMITTED_OVERLAY_ROS_HOSTNAME_LOCALHOST_LIFECYCLE_AUDIT_MISMATCH`.

The frozen v4 R03 receipt is retained only as exclusion, provenance, and
failure-diagnosis evidence. Its complete 2319-row trajectory and diagnostic
APE are identity-bound but are not admitted to common-support accuracy. The
frozen v4 base artifact reconstruction passes, while both the base and strict
prior-receipt audits fail exactly with
`PRIOR_EXECUTION_INTEGRITY:KLT_R03`. That expected failure is not repaired by
rewriting or replacing any v4 artifact.

## 3. Sole v5 environment amendment

For `KLT_R04` and `KLT_R05`, the locked selected environment contains the one
additional key-value pair:

```text
ROS_HOSTNAME=localhost
```

This is not an outcome-driven tuning change. The frozen inner overlay shell
already exports this exact value before launching VINS; v4 omitted it only
from the item environment against which the lifecycle manifest was audited.
All other selected scientific, signal, lifecycle, input, command, and numeric
values must equal the frozen v4 values after the normal item-id, repeat-index,
tag, output, runtime, workspace, and protocol-version substitutions.

The frozen v4 lifecycle wrapper
`scripts/run_a08_vins_node_lifecycle_wrapper_v4.py` and signal-mask launcher
`scripts/run_a08_unblocked_overlay_exec_v4.py` are reused byte-for-byte. The
v5 replay guard is new only to bind the v5 root, item, lock, and claim.

## 4. Frozen nested-shell process authority

The launcher-to-wrapper relationship is a fixed two-shell chain, not a direct
parent-child edge:

1. the frozen outer seedchain shell delegates at its exact line 103 to
   `run_aqualoc_archaeo_vins_eval.sh`;
2. the frozen inner archaeology shell exports `ROS_HOSTNAME=localhost` at its
   exact line 925;
3. that inner shell launches the identity-bound lifecycle wrapper through the
   substituted `VINS_NODE_BIN` at its exact line 948.

The execution audit therefore requires the sealed-FD stable owner to equal the
single supervisor runtime PID; requires valid, distinct launcher and wrapper
parent PIDs; requires wrapper and real VINS child to share the supervisor
process group and session; and requires the owned group and descendants to be
drained. It must not assert that the wrapper is a direct child of the outer
launcher. The identities of both shell files and all three exact lines are
part of the lock authority.

## 5. Static order gate

Before the backend-v5 lock can be built, the analysis-v5 static design freeze
must be published at
`papers/a08_hfnet_vs_klt_only_common_support_v5_design_freeze.json` with schema
`aqua-fe-a08-hfnet-vs-klt-only-common-support-design-freeze-v5` and status
`FROZEN_AFTER_R01_R02_R03_INFRASTRUCTURE_FAILURES_BEFORE_R04_R05_BACKEND_AND_ACCURACY`.

That freeze must bind the final backend-v5 protocol, runner, guard, tests,
reused lifecycle wrapper and signal launcher, Python 3.8 executable, real VINS
binary, frozen v4 authorities, frozen v4 execution lock, frozen R03 terminal
receipt, analysis-v5 protocol/runner/tests, support material, frontend
authorities, evaluator, and prior R01--R03 dispositions. Its claim boundary
must state that no backend-v5 lock, backend-v5 item, ROS/VINS process,
analysis-v5 lock, or v5 APE/RPE result existed at freeze time.

The backend validator recomputes the freeze digest, checks these live file
identities, reconstructs the R03 exclusion evidence, and checks the unique
`ROS_HOSTNAME` amendment before allowing a backend lock.

## 6. Execution authority and one-shot rule

The canonical backend authority is:

- protocol:
  `papers/a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v5_protocol.md`;
- runner:
  `scripts/run_a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v5.py`;
- guard:
  `scripts/run_a08_recovered_july_history_matched_backend_klt_only_replay_guard_v5.sh`;
- process-free tests:
  `scripts/tests/test_run_a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v5.py`;
- execution lock:
  `papers/a08_recovered_july_history_matched_backend_klt_only_remaining_replays_v5_execution_lock.json`;
- output root:
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_remaining_replays_v5`;
- runtime root:
  `/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/runtime/backend_klt_only_remaining_replays_v5`.

The only executable order is `KLT_R04`, then `KLT_R05`. Each item receives one
authorization token, one launch allowance, and exactly one supervisor
`Popen`. Automatic retries are zero. Replacement repeats are forbidden. A
terminal scientific/backend failure consumes that item but does not suppress
the later item. An execution-integrity failure blocks all later items because
the authority itself can no longer be trusted.

The runner accepts only the canonical lock path. Import, preflight, audit, and
lock construction are process-free. Lock construction is permitted only when
the v5 output root, runtime root, and both v5 workspaces are absent and the old
v4 R04/R05 locations remain untouched.

## 7. Terminal artifact contract

Each v5 item retains the frozen v4 expected-output set, including the replay
guard manifest, replay manifest, trajectory, backend-usability metrics,
diagnostic APE, lifecycle start and terminal manifests, and signal-mask
manifest. Acceptance requires all inherited v4 integrity and semantic gates,
plus:

- signal-mask audit `PASS` with no inherited HUP/INT/TERM block;
- lifecycle manifest contract integrity `true`;
- the locked selected environment exactly equals the lifecycle start
  environment, including `ROS_HOSTNAME=localhost`;
- the corrected nested two-shell lineage audit `PASS`;
- owned processes drained and no unowned replacement or retry.

Every item produces exactly one immutable terminal receipt regardless of
pass/fail. A failed item is reported under its predeclared failure rule and is
not repaired, selected away, or silently omitted.

## 8. Analysis boundary after both terminals

Only after terminal receipts for both `KLT_R04` and `KLT_R05` exist may the
analysis-v5 dynamic execution lock be built. Only v5 receipts accepted by the
full backend contract can enter the frozen common-support evaluator. R01,
R02, and R03 always remain infrastructure NAs. The KLT aggregate is the
coordinate-wise median over all valid R04/R05 repeats and must report the
valid count, with no best-repeat selection. If neither v5 repeat is valid, KLT
accuracy is `NA`; if one is valid, the median equals that one declared valid
repeat; if both are valid, both are used.

No accuracy number, comparative winner, or learned-frontend benefit may be
reported from diagnostic artifacts or before the dynamic analysis receipt is
accepted.
