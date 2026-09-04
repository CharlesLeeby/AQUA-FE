# HFNet-v6 same-history experiment on the July-14 historical positives

Status: prospective protocol.  It supersedes no existing freeze and does not
reinterpret any prior natural-history HFNet attempt.

## Question and method boundary

Run the external HFNet-SLAM learned-feature visual-inertial system on every
historical window where the frozen learned-plus-KLT arm beat pure KLT in APE.
The historical full/drop/KLT estimators cold-started at the first sample of
each selected window.  The external system must therefore receive exactly the
same window and no earlier camera history.  Natural-history HFNet results are
runability side evidence only and are excluded from this comparison.

HFNet-SLAM uses a published learned HFNet feature extractor with a classical
geometric/inertial SLAM backend.  It is an external learned-feature system,
not a narrow end-to-end learned estimator backend.

## Frozen outcome-selected roster

| Case | Historical role | Exact cold-start window |
|---|---|---:|
| A05 | main positive | camera 3300--3700, 401 frames |
| A07 | main positive | camera 10800--11200, 401 frames |
| A08 | main positive | camera 4500--4660, 161 frames |
| A09 | main positive | camera 6000--6200, 201 frames |
| NTNU fjord_1 | main positive | bag record-time [83 s, 93 s) |
| NTNU mclab_1 | main positive | bag record-time [60 s, 75 s) |
| CIRS Cala Viuda | main positive | bag record-time [575 s, 605 s) |
| CIRS Cala Viuda | main positive | bag record-time [900 s, 930 s) |
| A02 | secondary positive | camera 7600--8000, 401 frames |
| NTNU mclab_2 | secondary positive | bag record-time [110 s, 120 s) |

A09 5000--5400 is the known historical counterexample and is not in the
positive denominator.  A08 6800--7200 is a later additive result and is not in
the frozen July-14 ten-positive archive.

## Prospective execution contract

- Each case uses one canonical independent namespace and identity-pins its
  input manifest, independent preparation-audit receipt, dataset-specific
  camera/IMU configuration, and ten-case roster lock.  A normalized audit
  binding cross-checks the exact case, paths, frame count and header boundary,
  whole-window score interval, cold-start history, and official-reader IMU
  bracket.  The runner verifies these dependencies before preparation,
  immediately before process start, and again after process termination.
- Window selection for second-based datasets uses bag record time, matching
  the historical runner; the realized camera header boundary is recorded.
- A permanent per-case process-start claim outside the attempt directory is
  published atomically with no-replace semantics before the only HFNet
  `Popen`.  The roster lock fixes each case to one `attempt_001` namespace, so
  changing an attempt path cannot authorize a retry.  There is no retry and no
  replacement window after either pass or failure.
- Cases run under one roster-wide nonblocking execution lock held from the
  resource check through child reap and terminal receipt publication.  ToDesk
  may remain open under the user's explicit development waiver.  GPU identity,
  driver, utilization, and memory are recorded; the former 3072 MiB
  free-memory rule is not a method requirement and is not a hard gate here.
  Competing CUDA work and HFNet/VINS/ROS estimator processes remain forbidden;
  the waiver covers only an exactly recognized ToDesk executable.  A different
  GPU or cloud host requires a separately validated runtime cache/stack freeze.
- A runability PASS requires a clean child exit and reap, unchanged inputs,
  frozen preparation dependencies, and model; valid trajectory and keyframe
  output; at least 70% total and longest-contiguous camera support; one
  successful initialization; a nonempty final atlas; and no active-map reset
  or reinitialization inside that explicitly recorded longest contiguous
  support interval.  Tied longest intervals resolve to the earliest interval.
  The stock log does not expose a reset frame directly: a reset is accepted as
  early only when its next successful `Init frame id` is no later than the
  accepted support start.  Every other reset, including one without a later
  initialization, is conservatively unresolved and fails runability.  Proven
  early cold-start initialization failures are retained and reported, but do
  not by themselves invalidate later continuous support.
- A failed or unsupported case has accuracy `NA`, never zero.  Runability
  failures and claimed attempts with supervisor exceptions are retained in the
  ten-window denominator and are not retried.  A terminal FAIL receipt must be
  emitted after any claimed attempt, and the run command returns nonzero for
  FAIL.

## Dataset-specific adaptations

- AQUALOC uses the published 968x608 pinhole/radtan camera model, fixed
  camera--IMU transform, 200 Hz IMU settings, and the already frozen
  +53,694,112 ns IMU-to-camera-clock shift.
- NTNU uses the common underwater Kannala--Brandt8 calibration and fixed
  camera--IMU transform.  The historical record-time crop is authoritative;
  the IMU timestamps are shifted by the prospectively audited value required
  by HFNet's reader, which has no `td` parameter.
- CIRS uses the supplied camera calibration and the published common vehicle
  body frame.  The dataset's body-to-MTi and body-to-camera offsets derive
  `T_imu_cam`; 5 Hz camera and approximately 10 Hz IMU rates must not inherit
  AQUALOC's 20/200 Hz values.  Any assumed rather than calibrated IMU noise
  values are labeled explicitly.

## Accuracy gate

Only runability-PASS cases enter accuracy analysis.  HFNet, learned-plus-KLT,
and pure KLT are evaluated on one intersection of timestamps with fixed-scale
proper SE(3), no fitted time offset, at least 30 common poses, at least 10 s
common span, at least 70% score coverage, and at least ten exact one-second RPE
pairs.  An independent evo calculation must agree.  Until that gate passes,
no APE/RPE winner, ranking, significance, or superiority claim is authorized.

All reference trajectories are labeled honestly: AQUALOC COLMAP, NTNU
ReAqROVIO, and CIRS odometry are non-independent proxy references, not external
sensor ground truth.
