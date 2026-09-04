# A09 same-history warm-start comparison v1

Status: `FROZEN_SCAFFOLD_BEFORE_ANY_A09_PROJECT_WARMHISTORY_WRITE`

Date: 2026-08-26 (Asia/Shanghai)

## Purpose and evidence boundary

This protocol prepares a boundary-matched AQUALOC archaeology A09 comparison
over one continuous feed.  Source frames `0..4400` are consumed in order and
only source frames `4000..4400` are scored.  The four systems are:

1. `vanilla_origin_native_image_context`;
2. `external_klt_finalonline_backbone`;
3. `aquafe_finalonline_xfeat_lineage`; and
4. the already sealed `hfnet_slam_warmstart` result.

The first three systems do not yet have A09 `0..4400` inputs or trajectories.
Creating this protocol and its runner does not start any process and does not
authorize an implicit run.  The runner requires a stage-specific explicit
authorization token before its only implemented mutating stage can start.

This is a development-selected, non-confirmatory diagnostic.  ToDesk and
ordinary interactive desktop processes may remain active under the user's
explicit machine-exclusivity waiver.  Concurrent ROS replay, SLAM/VIO,
feature-export, or learned-model work remains forbidden because it can corrupt
execution ownership and resource interpretation.  Runtime is not a paper
endpoint and no machine-exclusive timing claim is permitted.

The score interval contains only 21 native COLMAP/depth-scale proxy poses and
at most 20 anchored 1 Hz evaluation samples.  Therefore the 30-pose formal APE
gate is closed by construction.  Any eventual APE/RPE values are descriptive
only; no winner, ranking, significance, held-out, or primary-paper claim is
authorized by this protocol.

## Frozen feed and score support

- Dataset: AQUALOC archaeology sequence A09.
- Continuous camera feed: source frames `0..4400`, inclusive, 4401 images.
- Unscored prefix: source frames `0..3999`.
- Scored window: source frames `4000..4400`, inclusive, 401 images.
- Feed camera header interval:
  `[1542888746071008208, 1542888966034698672]` ns.
- Score camera header interval:
  `[1542888946038630384, 1542888966034698672]` ns.
- Score duration: `19.996068288` s.
- Native reference: `/aqualoc/colmap_gt` written at the corresponding camera
  header timestamps from the frozen updated A09 trajectory.
- Native reference support in `0..4400`: 213 poses.  The missing 20-frame-grid
  indices are `1860,1880,1900,1920,1940,3460,3480,3540`.
- Native reference support in `4000..4400`: exactly 21 poses at
  `4000,4020,...,4400`.
- External project systems use the method-native odd-frame grid
  `1,3,...,4399` (2200 messages); the score subset is
  `4001,4003,...,4399` (200 messages).

VINS-family runs must use the same project settings as the A10 same-history
contract: `VINS_MULTIPLE_THREAD=1`, `WAIT_FOR_VINS_SUBSCRIBERS=1`,
`AQUALOC_BODY_T_CAM0_MODE=imu_cam`,
`VINS_TD=-0.053694112369382575`, `VINS_ESTIMATE_TD=0`,
`VINS_MAX_SOLVER_TIME=0.04`, `VINS_MAX_NUM_ITERATIONS=8`, and
`PLAY_RATE=1.0`.  The native-image arm is the project's local
quality-capable VINS-origin checkout, not a claim of a pristine upstream
binary.

## Causal frontend boundary

The existing A09 `4000..4400` cold-start artifacts are selection evidence
only.  In particular, these frozen cold artifacts must never be prepended,
appended, timestamp-shifted, ID-remapped, or spliced into the warm-history
payload:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| short raw bag | 98,167,227 | `ddc41e776b12bdf5f22a043a5862eba049d1c1494a2ab500ac2bf7893b5d9c54` |
| short KLT `features.bag` | 6,136,127 | `e7315db3efddd2884d06bbf9120008e59eea747da1a0c0d8436cfe309e9c9fa7` |
| short AQUA-FE `full_merged.bag` | 6,138,047 | `39d5e8fda1425ee92d41ced36df27848419bd0571e68b157e29106ea7efef653` |
| short `sidecar.bag` | 143,223 | `bad2d0cfc540037a035fffd4880871b5b247267b3bf320cfb472ba886d7d37a5` |
| short `stats.csv` | 49,651 | `e6458055a6d7d6aea67e000a9e411d9bd2150aea965e0cc150b9dda53d1576a1` |

The warm KLT exporter must update state over all source images `0..4400` and
publish only its fixed odd-frame grid.  The XFeat seed-to-KLT lineage state
machine must then consume that same warm KLT payload from its first published
message.  A lineage selected in the prefix consumes the global one-lineage
budget.  The warm score window is not required to reproduce the cold-start
window's 30 injected observations.  Prefix and score-window learned action
must be audited and reported separately.

## Frozen raw-materialization inputs

The first implemented stage is `materialize_raw`.  Its frozen inputs are:

| Authority | Bytes | SHA-256 |
|---|---:|---|
| A09 raw-data archive | 1,722,658,380 | `4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901` |
| updated A09 COLMAP proxy | 45,197 | `b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17` |
| raw converter | 8,310 | `b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec` |
| sealed HFNet input manifest | 2,895,623 | `fb54d28425a0eeea3ec7dec42ff2f433cac0a6303da96a0be1265b841fb36c8d` |
| sealed feed camera-time list | 88,020 | `c8b9bb58e1692ae570cfc855e2069bda734110c2866004093c8eefa4293f16a8` |
| `/opt/ros/noetic/setup.bash` | 260 | `42e35f97c20127488ca0b80af92e9711e37a5cadcd381e5a8b7968dba58864a9` |
| `/opt/ros/noetic/_setup_util.py` | 13,309 | `f5f341fd88d5624f8969fb7a8e40218794cbca5a0ec6bc7f3a18e5ff9d2e11cf` |
| `/usr/bin/python3.8` | 5,490,456 | `298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06` |
| `/usr/bin/bash` | 1,183,448 | `025cf78cd9d276019e916b97b0decd10cacb14902db8eb9f28233019babfb331` |

The manifest independently binds archive members
`raw_data/img_sequence_9.csv` (251,738 bytes,
`29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a`)
and `raw_data/imu_sequence_9.csv` (7,806,649 bytes,
`9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3`).

The exact converter argument contract is:

```text
/usr/bin/python3.8 -m uw_frontend.datasets.aqualoc_raw_to_rosbag
  --input <frozen A09 raw-data archive>
  --output-bag <claim-specific same-filesystem staging bag>
  --sequence-name archaeo_sequence_9
  --raw-root raw_data
  --image-dir images_sequence_9
  --image-csv img_sequence_9.csv
  --imu-csv imu_sequence_9.csv
  --gt-txt <frozen updated A09 COLMAP proxy>
  --start-index 0 --end-index 4400
  --image-topic /camera/image_raw
  --imu-topic /rtimulib_node/imu
  --gt-topic /aqualoc/colmap_gt
  --camera-frame-id aqualoc_camera
  --imu-frame-id aqualoc_imu
  --gt-frame-id aqualoc_world
  --imu-margin-s 0.25
```

The line breaks above are documentary; the runner records the exact argv.
The command runs from `/home/ma/AQUA-FE_WS` after sourcing only the frozen ROS
Noetic setup.  `PYTHONDONTWRITEBYTECODE=1`, `PYTHONHASHSEED=0`, and a minimal
declared environment are used.  No ROS master is started.

## Raw output ownership and semantic audit

The final raw authority is fixed to:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1/raw/archaeo09_0000_4400.bag`

The stage has one launch allowance and zero automatic or result-informed
retry.  A durable `process_start_claim.json` is published with `O_EXCL` before
the only converter `Popen`.  The converter writes to a claim-specific private
staging directory.  The final path is published by a same-filesystem atomic
hard link, which fails if any file, directory, symlink, or dangling symlink
already occupies the final path.  The runner never passes the final path to
the converter's truncating `rosbag.Bag(..., "w")` call.

An immutable terminal receipt is required after every catchable post-claim
outcome.  A claim without a receipt is a consumed, ambiguous attempt and
blocks further launch.  A child return code of zero is not acceptance unless
the complete raw semantic audit passes.  Partial staging artifacts remain
identified as failed evidence; they never become the final authority.

The raw audit requires exactly three topics and 48,639 total messages:

| Topic | Type | Count |
|---|---|---:|
| `/camera/image_raw` | `sensor_msgs/Image` | 4,401 |
| `/rtimulib_node/imu` | `sensor_msgs/Imu` | 44,025 |
| `/aqualoc/colmap_gt` | `nav_msgs/Odometry` | 213 |

It additionally requires BZ2 chunk compression; exact camera timestamps and
mono8 `968x608` payloads; exact IMU timestamps and six measurement values;
exact GT timestamps, frames, child frame, positions, and xyzw quaternions;
strict timestamp ordering; header/bag-time equality; and these frozen stream
digests (big-endian packed numeric audit representation):

- camera timestamp digest:
  `992f1236dabe3a8e1f6fac7ee3d038fe5c56d49b769708460f5754c3d602649f`;
- camera `(stamp,width,height,decoded mono8 bytes)` digest:
  `4a31268757a440691fe94aaaae61d57652881aaed88efed154a83ac7a88cc1dc`;
- IMU timestamp digest:
  `c6b9bd7c120f208e37c518361d8eba7cb7cf6de45beb2f8ef5b0b9ff47ed10df`;
- IMU `(stamp,gyro xyz,accel xyz)` digest:
  `87d174546d583b22eda6c738ff9c1193020f01fe44191c3760caf0e5e26ba364`;
- GT `(stamp,position xyz,quaternion xyzw)` digest:
  `5d462fecfdc764252a7144f5fe3982b7d18d4c9598d699458b9e54146b4ff46c`.

The IMU interval is
`[1542888745989326256,1542888966282492752]` ns.  These are raw IMU
timestamps selected by the converter's fixed 0.25 s margin; the HFNet adapter
uses a different but already disclosed shifted-reader bracket.

## Stage-state scaffold

All large outputs must remain below
`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1`.
The root filesystem must not receive large artifacts or ROS logs.

| Stage | Dependencies | Scaffold state |
|---|---|---|
| `materialize_raw` | none | implemented, token-gated, not executed |
| `klt_export` | accepted `materialize_raw` | interface only; launch forbidden |
| `aquafe_build` | accepted `klt_export` | interface only; launch forbidden |
| `vanilla_backend` | accepted `materialize_raw` | interface only; launch forbidden |
| `klt_backend` | accepted `klt_export` | interface only; launch forbidden |
| `aquafe_backend` | accepted `aquafe_build` | interface only; launch forbidden |
| `hfnet_bridge` | sealed HFNet result | interface only; write forbidden |
| `common_support` | all accepted trajectories and bridge | interface only; launch forbidden |

The future KLT science command must preserve the A10 same-history v2 KLT
contract with only the sequence, feed range, output paths, and tag changed:
`run_paper_sidecar_profiles.sh aqualoc_archaeo_loftr_mirror_klt 9 0 4400`,
`RUN_VINS=0`, `MEASUREMENT_SELECTION=0`, `EXPORT_MAX_FEATURES=350`,
`PROCESS_SKIPPED_FRAMES=1`, and source-aware backend quality metadata.  The
future AQUA build must use the frozen causal XFeat seed-sidecar command over
the newly accepted raw and KLT bags.  No backend stage may be enabled until
its complete command, VINS executable/config identities, cleanup contract,
score-usability contract, and output receipt schema are frozen in a later
protocol amendment.

## Future evaluation boundary

The already sealed HFNet terminal result remains immutable at:

`/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/a09_0000_4400_score_4000_4400_warmstart/attempt_001/run_result.json`

It is 23,846 bytes with SHA-256
`a0b03e41ac96c8e07d63325fdfc67d5292fc0c6c4b2debb3c6a40817a1d62fa7`.
Its score crop is 44,912 bytes with SHA-256
`4037e48ad1cdeace41ec8fbd4470debad275237934ccf0b734a670089bfec935`.
The future bridge may only change delimiters, quaternion column order, and
integral timestamp spelling.  Evaluation-only source-row timestamp
canonicalization is permitted only after proving 401 ordered rows, unchanged
pose tokens, `max_abs_delta_ns=112`, and the complete signed-difference
histogram.  No fitted offset, interpolation, resampling, scale correction, or
pose modification is allowed.

The future evaluator is
`scripts/evaluate_vins_common_support_epoch_v2.py`, using a fixed 1 Hz common
grid, 2.5 s maximum reference bracket, 0.25 s maximum estimate bracket, exact
1 s translation RPE, fixed-scale SE(3) alignment, and no Sim(3) scale fitting.

## Scaffold commands

Read-only state and exact preflight:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/run_samehistory_system_a09_warmstart_v1.py status
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/run_samehistory_system_a09_warmstart_v1.py preflight \
  --stage materialize_raw
```

The mutating command exists for a later explicitly authorized turn but is not
run by this protocol-freeze task:

```bash
PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3.8 \
  scripts/run_samehistory_system_a09_warmstart_v1.py run \
  --stage materialize_raw \
  --authorization-token A09_WARMSTART_V1_MATERIALIZE_RAW_EXACTLY_ONCE
```
