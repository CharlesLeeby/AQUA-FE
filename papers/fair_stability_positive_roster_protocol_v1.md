# Fair cold-start stability comparison on the historical positive roster v1

Status: **PROSPECTIVE DEVELOPMENT PROTOCOL; NO RESULT CLAIM YET**  
Frozen: 2026-08-29, before any run in the new namespace
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v1`.

## Question and population

This experiment asks whether the historical Learned+KLT system is more
reliably runnable than an external learned-feature system after removing the
known history, cadence, and loop-closing confounds.  The population is the ten
July-14 windows on which the frozen historical Learned+KLT arm had lower APE
than pure KLT.  The roster is intentionally outcome-selected.  Results answer
only a diagnostic question on these ten difficult positive windows; they are
not an unbiased dataset-wide stability rate.

The exact roster and input identities are in
`papers/fair_stability_positive_roster_v1.csv`.  No window may be added,
removed, replaced, or shortened after a result is observed.

## Arms

1. `learned_klt_vins`: the frozen July Learned+KLT feature bag, replayed into
   one identity-frozen VINS-Fusion backend.
2. `pure_klt_vins`: the frozen July pure-KLT feature bag, replayed into the
   identical VINS-Fusion backend, configuration, and replay schedule.
3. `hfnet_openloop_675`: stock HFNet-SLAM nominal feature budget 675, with
   `loopClosing: 0` and the VINS-matched camera cadence.
4. `hfnet_openloop_350`: budget-matched sensitivity with nominal steady-state
   budget 350.  This is not a strict 350-feature cap: the stock monocular-
   inertial initializer may request five times `Extractor.nFeatures`.  The
   source is not modified to hide this behavior.

The 675 arm is the system-native external baseline; the 350 arm diagnoses
feature-budget sensitivity.  HFNet-SLAM remains a learned HFNet frontend plus
a classical keyframe/optimization backend.  It is not described as a learned
estimator backend.

The VINS backend identity must be frozen before its first new replay.  If the
July/August frozen backend cannot be recovered exactly, both VINS arms use one
new isolated development identity and historical trajectories are not mixed
with the new repetitions.  Such runs test the frozen frontends under the new
common backend and must not be relabeled as the final paper system.

## Matched input and state

- Every replicate is a fresh process and cold-starts at the first admitted
  image.  No system receives earlier visual history or a saved map.
- AQUALOC and NTNU admit exactly the historical VINS image phase: source image
  indices `1,3,5,...`.  This is approximately 10 Hz.  CIRS admits every source
  image at its native approximately 5 Hz; images are never duplicated or
  interpolated to manufacture 10 Hz.
- HFNet camera timestamps must map bijectively and monotonically to the
  feature-bag camera timestamps within 256 ns.  The complete timestamp lists,
  not merely counts or start/end times, are hashed before launch.
- Dataset-specific calibration, camera/IMU clock shift, and physical IMU
  source remain fixed.  Format-specific crops need not be byte-identical, but
  real predecessor and successor IMU samples must bracket the first and last
  admitted camera timestamps.
- HFNet is generated from a frozen base configuration with only four audited
  substitutions: run-local model path, integer camera fps, nominal feature
  budget, and `loopClosing: 1 -> 0`.  The base file is never edited.
- Every HFNet replicate receives an independent writable copy of the same
  frozen TensorRT cache seed.  Cache rewriting is expected output and is
  recorded pre/post; the ONNX model must remain unchanged.

## Repeats and ordering

There are three planned replicates for every case and arm.  A replicate is not
a retry.  The run order is frozen before outcomes using balanced interleaving
across cases, arms, and repeat blocks.  Only one estimator process runs at a
time.  A GPU/ROS/compiler/exporter conflict prevents launch rather than
turning resource contention into an algorithm failure.

The complete planned matrix is 10 cases x 4 arms x 3 replicates = 120 runs.
The already completed one-off HFNet runs and the mclab1 loop-off diagnostic
are context only and do not count toward these repetitions.

## Terminal classification

`PIPELINE_INVALID` is excluded from the algorithm denominator and replenished
under the same frozen cell only when a preflight or execution receipt proves
an external experimental fault: input/config/hash mismatch, output collision,
ROS namespace conflict, disk/permission failure, unavailable GPU/driver,
background-resource OOM, operator interruption, or the Learned+KLT outer
guard replacing the requested arm with an independent KLT export.  The
invalid receipt is retained.  An internal method-selected safe fallback is a
valid system behavior, not a pipeline fault.

`ALGORITHM_FAILURE` remains in the denominator after a clean preflight when
the estimator crashes, aborts, times out, never initializes, produces an
empty/nonfinite/nonmonotonic trajectory, initializes after more than 10 s,
has trajectory coverage below 0.50, or reports an internal optimizer/map
failure.  Coverage from 0.50 through below 0.70 is `PARTIAL_NON_SUCCESS` and
also remains a non-success.

A `SUCCESS` requires all of the following:

- one estimator launch, clean exit, and confirmed child reap;
- a finite, strictly time-monotonic trajectory;
- a successful initialization no later than 10 s after the first admitted
  camera timestamp;
- total and longest-contiguous trajectory coverage each at least 0.70 of the
  admitted camera timestamps;
- at least one valid keyframe/output state; and
- no unresolved reset, reinitialization, or solver-risk event inside the
  accepted longest-contiguous support interval.

A `CLEAN_SUCCESS` is a success with no reset/reboot/solver-risk event anywhere
in the window.  Accuracy is `NA` for every non-success; it is never encoded as
zero.

## Analysis and claims

For each case-arm cell report successes/3, clean successes/3, all failure
modes, median initialization latency, and median coverage.  At least two valid
replicates are required for a numeric median.  Also report whether any of the
three runs crashed, reset, reinitialized, or raised solver risk.  Repetitions
are nested within a window and are not independent dataset samples.

Accuracy, if evaluated later, uses only a preregistered joint-support mask;
failed runs remain in the stability denominator.  Runtime and real-time claims
are forbidden when ToDesk or other non-isolated desktop work is present.

Allowed conclusion: one arm had a higher clean cold-start success rate on this
fixed outcome-selected roster under the frozen open-loop protocol.  Forbidden
conclusions: dataset-wide superiority, learned-frontend causal superiority,
or paper-final-system superiority.  A general stability claim additionally
requires a separate result-blind/held-out roster.
