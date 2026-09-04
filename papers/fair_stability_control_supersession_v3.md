# Fair-stability prospective control supersession v3

Status: **DRAFT CONTROLS ONLY — NOT FROZEN, NOT PREPARED, NOT EXECUTED**.

This note prospectively supersedes the v2 execution, lifecycle, automatic
replacement, and terminal-classification controls.  It does not change the
ten-window roster, image/IMU/feature-bag inputs, four arms, three planned
repeats, loop-off requirement, camera cadence, 256 ns association tolerance,
0.50/0.70 coverage thresholds, or 120 planned cells.

The v3 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v3`,
the experiment id is
`fair-stability-positive-roster-openloop-runtimeexcl-v3`, and the prospective
backend id is `DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V3`.  All v3 schemas end in
`-v3`; the VINS backend/control freeze, if later authorized, belongs under
`vins_dev_nativeq_schedfix_runtimeexcl_v3/backend_freeze.json`.

## Why v2 is superseded

V2 planned ordinal 1 completed estimator execution but its lifecycle wrapper
reported four residual descendants.  The wrapper had created exactly four
observer processes itself: a command-substitution subshell and the
`ps | awk | paste` residual-scan pipeline.  The otherwise clean lifecycle was
therefore labelled `SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN`.  The immutable
evidence and non-claim boundary are recorded in
`fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`.

The v2 controller also classified lifecycle, monitor, identity, configuration,
model, and control drift as automatically replaceable pipeline faults.  A
persistent controller defect could consequently consume successive ports
instead of halting.  V3 makes automatic replacement an explicit, narrow,
pre-registered exception.

## V3 control changes

- `run_fair_stability_vins_replay_child_v3.sh` scans `/proc/[0-9]*/stat` with
  Bash builtins in the current shell and directly updates
  `DESCENDANT_RESIDUALS` and `DESCENDANT_RESIDUAL_COUNT`.  Its residual scan
  starts no `ps`, `awk`, `paste`, or command-substitution process.
- Automatic same-cell replacement is allowed only for
  `MIDRUN_EXTERNAL_RESOURCE_INTRUSION`.
- `SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN`,
  `RUNTIME_RESOURCE_MONITOR_UNPROVEN`, estimator identity failures, tag or
  configuration/model/control drift, post-run reverification failures, and
  every code outside the explicit allowlist halt the controller and require
  manual experiment abandonment/review.  They are never auto-adjudicated as
  external faults.
- A pre-start resource block creates no estimator start and consumes no
  replacement attempt.
- Each planned cell pre-registers at most two replacement attempts, three
  total attempts.  Attempt index 4 is invalid in the common state machine and
  in both runners.
- Repetition of any previously accepted pipeline code in the same planned
  cell halts immediately; it cannot generate another replacement.
- The immutable attempt-matrix freeze, if later authorized, records the
  automatic allowlist and both attempt limits globally and per cell.
- VINS port validation completes before creation of an attempt directory, so
  an invalid/exhausted port cannot leave an empty prepared-attempt path.
- The ordinal dispatcher, runner, common state, runtime monitor, summary,
  tests, documents, result schemas, experiment root, and backend identity are
  mutually rebound to v3.

## Provenance binding

Any future v3 input manifest and backend/control freeze must bind, by absolute
path, byte size, and SHA-256, both:

1. `fair_stability_v1_runtime_contamination_report_20260829.md`; and
2. `fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md`.

No v1 or v2 experiment/case/attempt manifest, timing cache, dispatch/start/
result receipt, invalid-attempt receipt, or summary may be copied into v3.
Shared source inputs and backend binaries may be reused only after fresh
identity verification.

This remains a prospective development comparison on an outcome-selected
roster.  It is not a P07 backend reproduction and cannot support a
dataset-wide, causal learned-frontend, runtime, or paper-final-system
superiority claim.
