# HFNet-v6 A10 warm-start runability rescue protocol v1

Status: **FROZEN DESIGN ONLY — DEVELOPMENT ONLY — NO EXECUTION AUTHORITY**

This document fixes one runability-rescue design. It does not authorize input
materialization, process launch, retry, accuracy evaluation, or publication of
a system-comparison claim. A separate, explicit execution authority and a
fresh no-clobber attempt record are required before any process may start.

## Frozen question and role

Can the unchanged external HFNet-SLAM monocular-inertial system remain usable
on the already selected AQUALOC archaeology-sequence-10 positive window when
it receives the sequence's preceding history, instead of being cold-started
inside that window?

This is a development-only **runability rescue**, not an accuracy comparison.
The positive window was selected from prior AQUA-FE-versus-KLT results, so the
selection is result-conditioned.

## Frozen input and scoring bounds

| Item | Frozen value |
|---|---|
| Sequence | AQUALOC `archaeology_sequence_10` |
| Continuous HFNet feed | source camera frames `0..2800`, inclusive |
| Unscored warm-start prefix | source camera frames `0..2399`, inclusive |
| Scored positive window | source camera frames `2400..2800`, inclusive |
| Feed camera count | `2801` |
| Warm-start camera count | `2400` |
| Score camera count | `401` |
| Feed timestamp bounds | `1542888796062978800..1542888936039921424` ns |
| Prefix last timestamp | `1542888915993158416` ns |
| Score timestamp bounds | `1542888916043622160..1542888936039921424` ns |
| Feed span | `139.976942624` s |
| Prefix span | `119.930179616` s |
| Score span | `19.996299264` s |

The estimator must be started once at source frame 0 and must carry the same
map and inertial state across frame 2400. It must not reset, reload a map,
reinitialize, or restart at the score boundary.

## Frozen source and IMU contract

Canonical source archive:

`/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_10_raw_data.tar.gz`

- Size: `3761302356` bytes.
- SHA-256: `e8bde74e147236c15fe70d0385c618a75b2fc6e18e6f369dc12e355b49faceee`.
- Camera images must be copied from canonical PNG tar members; short ROS bags
  must not be concatenated or substituted as the image authority.
- Use the already frozen archaeology clock policy: add `53694112` ns to raw
  IMU timestamps because the HFNet-SLAM reader has no `td` field.
- With strict two-sided camera bracketing, select raw IMU row indices
  `28..28003`, inclusive: exactly `27976` rows.
- The first, second, penultimate, and last shifted IMU timestamps must be
  `1542888796058306992`, `1542888796063392976`,
  `1542888936037078064`, and `1542888936042109776` ns, respectively.
- Camera and shifted IMU timestamps must each be strictly increasing; the
  first and last camera timestamps must each be strictly bracketed by IMU.

Reuse the byte-identical published archaeology configuration at
`configs/published_baselines/hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml`.
No detector threshold, feature budget, image rate, camera/IMU calibration,
noise setting, model, runtime library, or backend parameter may be tuned for
this rescue.

At freeze time, only the 401-frame A10 cold-start HFNet input is materialized.
A canonical `0..2800` HFNet input has not yet been materialized or audited.

## Pre-execution gates

All gates below must pass before a later authority may permit launch:

1. A no-clobber `0..2800` materialization and independent audit reproduce all
   frozen counts, bounds, source pins, PNG identities, and IMU brackets.
2. The unchanged HFNet-v6 binary, runtime, ONNX/cache policy, configuration,
   and launcher are byte-pinned before start.
3. The attempt directory is fresh, the GPU is idle, and no HFNet/SLAM process
   from another attempt is alive.
4. A future execution record permits exactly one process invocation, no
   automatic retry, and no post-start parameter change.

This protocol itself satisfies none of those gates and grants no launch
permission.

## Frozen runability adjudication

After an independently authorized run, score only source frames `2400..2800`
using the frozen camera-index mapping. Warm-start rows must not enter score
coverage or accuracy support.

`PASS_DEVELOPMENT_RUNABILITY_RESCUE` requires all of the following:

- one valid finite frame pose for every one of the 401 scored camera frames;
- one continuous scored trajectory span, with no missing scored index;
- at least one valid keyframe and a non-empty surviving map;
- no active-map reset, inertial reinitialization, relocalized stitched segment,
  crash, timeout, or official-save hang inside the scored window; and
- unchanged audited input and pinned runtime artifacts after execution.

Any missing scored pose, score-window reset, empty final map, malformed output,
or watchdog termination is a runability failure. Partial trajectories may be
reported descriptively but must not be stitched, selectively cropped further,
or relabeled as a pass.

## Accuracy and comparison gates

- Do not compute or report an HFNet-versus-AQUA-FE/KLT accuracy ranking unless
  the runability gate passes first.
- Any later development metric must crop to the exact 401-frame score window,
  use one frozen association rule and one common reference support, and exclude
  the warm-start prefix from metric fitting and reporting.
- The currently available native proxy reference has only 21 one-hertz rows,
  below the project's 30-row formal-accuracy gate. Therefore formal APE/RPE and
  superiority claims remain closed even if runability passes.
- Existing AQUA-FE/KLT A10 results are exact-window cold starts at a different
  frontend rate, whereas this HFNet design receives about 120 seconds of prior
  history at its native 20 Hz rate. It is not a fair head-to-head system row.
- A fair later system comparison requires AQUA-FE and KLT to receive the same
  continuous `0..2800` history and to be scored only on `2400..2800`, with
  method-native rates explicitly disclosed.

## Why this is the first rescue

The A10 cold-start run formed four visual maps with 159--207 points and reached
`Imu initialized` four times, but each map was reset for `Not enough motion`.
Thus preceding motion history addresses the observed algorithmic failure rather
than an infrastructure failure. Independently, the A06 analogue succeeded with
continuous feed `0..2460` and exact score `2210..2460`, producing frame poses
for all 251 scored frames after its exact-window cold start had failed.

A10 is preferred to A09 for this first rescue because it is the stronger prior
development positive (97 injected observations and 5/5 paired APE/RPE wins),
has a shorter natural-history prefix, and contains an earlier A10 `400..800`
region in which the project VINS baseline initialized in 5/5 recorded runs.
That different-backend evidence does not prove an HFNet minimum prefix. The
true shortest HFNet prefix is therefore unknown; choosing a later start before
this natural-start attempt would introduce an additional result-conditioned
hyperparameter.

## Authority boundary

Permitted by this document: read-only review and implementation planning.

Not permitted by this document: materialization, GPU allocation, detector or
SLAM launch, retry, trajectory evaluation, mutation of prior attempts, or any
paper claim. Only a separate explicit authority can enable those actions.
