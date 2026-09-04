# HFNet-v6 A09 warm-start runability rescue protocol v1

Status: **FROZEN DESIGN ONLY — DEVELOPMENT ONLY — PRE-MATERIALIZATION BLOCKED — NO EXECUTION AUTHORITY**

This document freezes one additive A09 runability-rescue design. It authorizes
neither canonical input materialization nor process launch, retry, trajectory
evaluation, or publication of an accuracy/system-ranking claim. Materializing
or running later requires separate explicit authority after every stated gate
has passed.

## Frozen question and scientific role

Can the unchanged external HFNet-SLAM monocular-inertial system remain usable
on the already selected AQUALOC archaeology-sequence-9 positive window when it
receives the sequence's natural preceding history instead of being cold-started
inside that window?

This is a secondary, development-only runability replication. A09 `4000..4400`
was selected from prior AQUA-FE-versus-KLT development results, and the A10
natural-history rescue is already known to pass. A09 is therefore neither held
out nor confirmatory and cannot establish an accuracy ranking.

## Frozen feed and score bounds

| Item | Frozen value |
|---|---:|
| Sequence | AQUALOC `archaeology_sequence_9` |
| Continuous HFNet feed | source camera frames `0..4400`, inclusive |
| Unscored warm-start prefix | source camera frames `0..3999`, inclusive |
| Scored positive window | source camera frames `4000..4400`, inclusive |
| Feed camera count | `4401` |
| Warm-start camera count | `4000` |
| Score camera count | `401` |
| Feed timestamp bounds | `1542888746071008208..1542888966034698672` ns |
| Prefix last timestamp | `1542888945988866768` ns |
| Score timestamp bounds | `1542888946038630384..1542888966034698672` ns |
| Feed first-to-last span | `219.963690464` s |
| Prefix first-to-last span | `199.917858560` s |
| Score first-to-last span | `19.996068288` s |
| Frame `3999` to `4000` gap | `0.049763616` s |

The estimator must be started exactly once at source frame `0`. The same map
and inertial state must cross the `3999 -> 4000` boundary. There may be prefix
resets, but no restart, map reload, manual reset, parameter change, or score
boundary reinitialization is permitted.

## Frozen source, synchronization, and configuration

Canonical image and IMU authority:

`/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz`

- Archive size: `1722658380` bytes; SHA-256:
  `4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901`;
  gzip footer CRC-32/ISIZE: `b2f3021d` / `1742161920`.
- Camera CSV `raw_data/img_sequence_9.csv`: `251738` bytes, SHA-256
  `29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a`,
  CRC-32 `6ab5e1f7`, with `6992` source camera rows.
- IMU CSV `raw_data/imu_sequence_9.csv`: `7806649` bytes, SHA-256
  `9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3`,
  CRC-32 `cc6033a9`, with `69861` source IMU rows.
- Canonical PNG members under `raw_data/images_sequence_9/` are the image
  authority. The decoded 401-frame ROS bag is selection evidence only and may
  not be concatenated with another bag or substituted for the PNG containers.
- Apply the frozen archaeology clock transform `output_ns = raw_ns + 53694112`.
  Synthetic, duplicated, interpolated, or extrapolated IMU rows are forbidden.
- Select zero-based raw IMU data-row indices `5..43964`, inclusive: exactly
  `43960` rows. Raw first/second/penultimate/last timestamps are
  `1542888746014492144`, `1542888746019782672`,
  `1542888965978469456`, and `1542888965983692976` ns. Their shifted values
  are `1542888746068186256`, `1542888746073476784`,
  `1542888966032163568`, and `1542888966037387088` ns.
- The shifted rows strictly bracket both feed endpoints:
  `1542888746068186256 < 1542888746071008208 < 1542888746073476784`
  and
  `1542888966032163568 < 1542888966034698672 < 1542888966037387088`.
  No camera or IMU synchronization trim is needed.

Reuse byte-for-byte:

`configs/published_baselines/hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml`

Its frozen identity is `2037` bytes and SHA-256
`37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6`.
No detector threshold, feature budget, image rate, calibration, IMU noise,
model, runtime library, or backend setting may be tuned for this rescue.

## Hard pre-materialization blocker

The canonical `0..4400` payload does not exist at freeze time. Before any
production materialization, a read-only derivation must stream the pinned
archive and deterministically generate target bytes without publishing the
canonical namespace. It must derive and freeze all of the following:

1. total bytes of the selected `4401` PNG files;
2. source-member and renamed-output image inventory SHA-256/CRC-32 values;
3. size/SHA-256/CRC-32 for `cam0_times.txt`;
4. size/SHA-256/CRC-32 for `mav0/cam0/data.csv`;
5. size/SHA-256/CRC-32 for shifted `mav0/imu0/data.csv`; and
6. SHA-256/CRC-32 for the complete payload excluding its manifest.

Every value must be embedded in the reviewed production contract before the
first canonical write. Materializing first and backfilling observed values is
forbidden. Until then, status remains
`FROZEN_DESIGN_ONLY_PRE_MATERIALIZATION_BLOCKED`.

## Additive namespaces and immutable evidence

Future artifacts, if separately authorized, must use new no-clobber paths:

- input:
  `/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/a09_0000_4400_score_4000_4400_warmstart`;
- independent audit receipt: the sibling path ending in `.audit.json`; and
- attempt:
  `/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a09_0000_4400_score_4000_4400_warmstart/attempt_001`.

Do not modify, replace, or rerun the consumed A09 cold-start attempt. Its
terminal `run_result.json` is `4536` bytes, SHA-256
`e6a0ef87e456dc99552b04b5ae00c016bd83302c8c979c57c2c7a5288b988f05`,
with status `FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES`. It started one child,
performed no retry, attempted initialization at cold-feed-relative frame IDs
`0`, `187`, and `276`, reset for insufficient motion, and ended with one atlas
map containing zero keyframes.

The A10 warm-start attempt and all of its inputs/controllers/results are also
immutable evidence and must not be edited or rerun. Code may be reused only by
an additive, byte-pinned fork with its provenance recorded.

## Gates before any later launch

The following order is mandatory:

1. derive all unknown payload pins read-only and freeze them;
2. add a no-launch materializer and tests using manifest-last, no-clobber
   publication plus an independent exact-tree audit;
3. obtain independent review and separate authority for exactly one canonical
   materialize-and-audit action;
4. freeze the committed manifest and independent receipt identities;
5. add and test a new A09-specific one-shot runner, byte-pinning every inherited
   controller and all selector/protocol/materializer inputs;
6. prepare/check a fresh `attempt_001` without launching; and
7. obtain a separate exact authorization token for one HFNet child process.

The future runner must use a `600` s timeout, exactly one `Popen`, no retry,
exclusive/no-clobber stdout, stderr, claim, crop, and terminal JSON artifacts,
and must seal a descriptive terminal failure after the process claim if any
exception occurs. This protocol grants none of those authorities.

## Frozen runability adjudication

`PASS_DEVELOPMENT_RUNABILITY_RESCUE` is permitted only if every condition below
passes:

- the sole child exits with code `0`, is reaped before post-audit, and has no
  timeout, watchdog intervention, retry, or supervisor error;
- the official trajectory and keyframe outputs are regular non-symlink files;
  every row is strict, increasing, finite, has a unit quaternion within
  `1e-3`, and maps deterministically to one unused canonical camera timestamp
  with at most `256` ns error;
- score support is exactly one pose for each source frame `4000..4400`, in
  order: `401/401`, contiguous, with no duplicate or missing source index;
- source frame `3999` immediately precedes source frame `4000` in the same
  selected final trajectory, proving continuity across the score boundary;
- at least one valid keyframe maps inside `4000..4400`;
- at least one initialization occurs before source frame `4000`, no
  `Init frame id >= 4000` occurs, every reset boundary is parseable, and no
  reset has a post-reset `mnFirstFrameId >= 4000` or otherwise overlaps the
  score window;
- the official save completes and the final atlas is exactly parseable and
  contains at least one keyframe; and
- the audited input, configuration, controller, runtime binary/library/model,
  and shared cache authority remain unchanged; only the isolated attempt-local
  cache may change under its frozen contract.

Only after all gates pass may the runner exclusively publish
`result/trajectory_score_4000_4400.txt` from those exact 401 rows and then seal
the terminal PASS JSON. Any gate failure must produce a descriptive terminal
FAIL, no score crop may be relabeled as usable, and accuracy must remain false.

## Accuracy and comparison boundary

- This protocol never authorizes APE/RPE or a winner claim. Runability must
  pass first, and a later accuracy protocol would require its own freeze.
- The A09 native proxy reference has only `21` one-hertz rows; the corrected
  common support currently has `16` matched poses, below the project's
  `30`-pose formal APE gate.
- Existing AQUA-FE/KLT A09 rows cold-start at source frame `4000`, whereas this
  HFNet design receives about `200` s of prior history at native rate. Those
  rows are not a fair head-to-head system comparison.
- A fair later comparison requires all arms to receive the same continuous
  `0..4400` history and be scored only on `4000..4400`, with method-native
  processing rates and reference support disclosed.

## Why freeze the natural-start attempt

The A09 cold-start evidence points to insufficient motion for initialization,
not a source or launcher failure. Natural preceding motion therefore targets
the observed algorithmic failure. The completed A10 analogue shows that this
history policy can carry an initialized HFNet map through all `401` score
frames, but it does not predict A09 success. Starting at canonical frame `0`
also avoids selecting a shorter prefix after inspecting outcomes; the shortest
sufficient A09 prefix is unknown and is not a tuning variable in this protocol.

## Authority boundary

Permitted now: read-only review of this selector/protocol and later additive
implementation planning.

Not permitted now: payload publication, canonical materialization, audit
receipt publication, GPU allocation, HFNet/ROS/VINS/detector/evaluator launch,
attempt preparation, retry, trajectory scoring, mutation of prior evidence, or
any paper claim. Only a later, separate and explicit authority may advance one
named stage.
