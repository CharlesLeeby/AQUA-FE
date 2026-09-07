# Finalization sequence — experiment method unchanged

Use only after the active controller has exited and decision.json status is COMPLETE.
The Batch A controller owns current tables until then. Do not run a second controller
or finalize a partial matrix. As of the A03 checkpoint, two severe regressions already
make the frozen Batch B gate false; still complete every executable Batch A slot.

From the isolated worktree, source ROS Noetic and use the registered Python 3.8 environment:

```bash
source /opt/ros/noetic/setup.bash
export PYTHONPATH=.:$PYTHONPATH
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/audit_classical_opportunity_final.py
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/complete_classical_opportunity_case_fields.py
/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python scripts/build_classical_opportunity_analysis_bundle.py
```

The audit acquires the controller lock without waiting, verifies existing artifact
identities/configuration/receipts/common support/evo/classification, and exports small
receipt JSON files. It never starts a replay. Hash mismatches block final publication
and remain inspectable. No old backend, inputs or frozen experiment source is edited.

The case supplement preserves exact window classification/tier/severe fields. It adds
published lifetime in seconds separately from observation counts, initialization clocks,
reference/image spans, broader history, and the already preregistered C single-repeat
severe-margin flags. A legacy raw_reference_span_s field was populated from the roster
image span; explicit reference_span_s and raw_image_span_s disambiguate it.

The bundle is descriptive: physical windows are the case units, three replays only
measure technical variation. It includes actual PNG/SVG figures, complete ranges,
mean/SD as secondary technical descriptors, raw/relative median differences, and explicit
reasons not to report population confidence intervals or significance. Review rendered
figures and the exact numeric table before composing the final Chinese report.md.

Preserve checkpoint_batch_A and any failed outputs. Review final first-page answers to
all eleven user questions, including exact denominator, heldout scope, old A02/Bus
comparison, severe cases, inactive Batch B, and the sole observation-utility/risk handoff.
Append required work/experiment/research/project logs, update the independent handoff,
commit/push scoped small artifacts and read back the remote commit and files.
No Obsidian write-back is part of the requested delivery.
