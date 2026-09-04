# Fair-stability prospective control supersession v2

Status: **FROZEN BEFORE THE FIRST ESTIMATOR START IN THE NEW NAMESPACE**.

This note supersedes only the execution and terminal-classification controls
recorded by the original HFNet input-freeze manifest.  It does not change the
ten-window roster, any image/IMU/feature-bag input, the four arms, the three
planned repeats, the loop-off requirement, the camera cadence, the 256 ns
association tolerance, the 0.50/0.70 coverage thresholds, or the frozen
120-cell schedule.

The supersession was required by a pre-run red-team audit.  The original
controller prepared attempts in schedule order but did not prevent a caller
from launching a later cell, did not retain a replenishment chain for an
externally invalid attempt, did not fully distinguish pipeline faults from
algorithm failures, and parsed too narrow a set of reset/reinitialization and
solver-risk events.  No `start_claim.json` or `run_result.json` existed when
these issues were corrected.

The v2 controls add:

- a single fail-closed ordinal dispatcher and per-run dispatch token;
- immutable terminal receipts for `SUCCESS`, `PARTIAL_NON_SUCCESS`, and
  `ALGORITHM_FAILURE`;
- same-cell `attempt_index` replenishment only after an adjudicated external
  `PIPELINE_INVALID`, without changing the planned repeat count;
- exact child identity, natural/supervised exit, reap, and residual-process
  checks;
- complete count-based trajectory and keyframe validation;
- broader reset, reinitialization, tracking/solver-risk, and nonfinite-event
  parsing;
- pre/post frozen-input, model, configuration, binary, source-tree, and
  dynamic-library-closure verification; and
- receipt-validated per-case/per-arm progress summaries.

The authoritative identities of the revised controls are written by
`run_fair_stability_vins_replay_v1.py freeze-backend` into
`vins_dev_nativeq_schedfix_v1/backend_freeze.json`.  That freeze must exist
and pass identity verification before the ordinal dispatcher may launch the
first estimator.  The original input-freeze manifest is retained unchanged
as provenance; its runner identity is historical and is not silently
rewritten.

This remains a prospective development comparison on an outcome-selected
roster.  It is not a P07 backend reproduction and cannot support a
dataset-wide, causal learned-frontend, runtime, or paper-final-system
superiority claim.
