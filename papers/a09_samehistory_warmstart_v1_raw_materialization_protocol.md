# A09 same-history warm-start v1 raw materialization protocol

Status: frozen before execution; development-only infrastructure stage.

## Purpose

Materialize one canonical AQUALOC archaeology sequence 09 ROS bag containing
source camera indices `0..4400` inclusive. This is the required common natural
history for later Vanilla, External KLT and AQUA-FE VINS runs scored only on
`4000..4400` and compared with the already completed HFNet-SLAM warm-history
run.

This stage produces no trajectory and computes no accuracy. It must not start
ROS master, VINS, a frontend, HFNet or a learned model.

## Why a new bag is required

The existing `archaeo09_4000_4400.bag` is a cold-start score-window crop. It
cannot be concatenated with a prefix because feature IDs, KLT state and the
single learned-lineage budget are causal history. No `0..4400` raw bag,
full-history KLT feature bag or full-history AQUA-FE merged bag existed when
this protocol was frozen.

## Frozen source identities

- Source archive:
  `/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_9_raw_data.tar.gz`,
  1,722,658,380 bytes, SHA-256
  `4d20237571928067cfe4dbb813224cfd2277270c424a6ef97ef50d2933da2901`.
- Archive camera CSV member: `raw_data/img_sequence_9.csv`, 251,738 bytes,
  SHA-256
  `29dc7cc3e67df003081070c6191107c8d8d6b5183fc62df965bd0fe5b685d03a`.
- Archive IMU CSV member: `raw_data/imu_sequence_9.csv`, 7,806,649 bytes,
  SHA-256
  `9334097f6311c5fcfe15dae581b18f479dbe9377f78da0b2ba08f4e5a36c83b3`.
- Image member prefix: `raw_data/images_sequence_9/`.
- COLMAP/depth-scale proxy file:
  `datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_09.txt`,
  45,197 bytes, SHA-256
  `b732a68ec354cb66d36b1a9f708d614c70e884d4c167f8940f9601cfce69ac17`.
- Converter: `uw_frontend/datasets/aqualoc_raw_to_rosbag.py`, 8,310 bytes,
  SHA-256
  `b0c4b7ce7f3e29dcb18cb1604190cc8690cae370fc222246c8dfeb4fc79ffbec`.

The source inventory must contain exactly 6,992 camera rows and 69,861 IMU
rows. Full-source camera timestamp endpoints must be
`1542888746071008208..1542889095563440368` ns. Source frame 4000 must be
`1542888946038630384` ns and source frame 4400 must be
`1542888966034698672` ns.

## Frozen conversion

- Camera indices: `0..4400`, inclusive (`4401` images).
- IMU selection: raw timestamps from 0.25 s before the first selected camera to
  0.25 s after the last selected camera. No timestamp shift is applied in the
  bag; downstream VINS uses its frozen `td=-0.053694112369382575` convention.
- Proxy GT: 213 available messages in `0..4400`, each bound to the exact
  corresponding camera header. The nominal 20-frame grid is missing source
  indices `1860,1880,1900,1920,1940,3460,3480,3540`; the score window
  `4000..4400` remains complete with 21 proxy rows.
- Image topic: `/camera/image_raw`, `sensor_msgs/Image`, mono8, `968x608`, frame
  `aqualoc_camera`.
- IMU topic: `/rtimulib_node/imu`, `sensor_msgs/Imu`, frame `aqualoc_imu`.
- GT topic: `/aqualoc/colmap_gt`, `nav_msgs/Odometry`, frame
  `aqualoc_world`, child `aqualoc_camera`.
- Compression: rosbag BZ2 as implemented by the pinned converter.

All output messages must have `header.stamp == bag record time`. Camera times
must be strictly increasing. Every available GT time must equal its pinned
source-index camera time. Every image payload is audited for mono8 encoding,
dimensions, step and byte length.

## Output and failure semantics

The entire experiment root must be absent before execution:

`/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1`

The runner writes to a sibling staging directory and atomically renames it only
after converter RC0 and complete bag audit. On any exception the staging tree
is removed; existing artifacts are never overwritten.

Committed files for this stage are:

- `raw/archaeo09_0000_4400.bag`;
- `raw/raw_materialization_receipt_v1.json`.

The receipt must pin the source, protocol, runner, converter, derived counts,
exact command, process return code, output bag identity and independent bag
audit. It must state that no frontend/backend/trajectory/accuracy result exists.

At least 8,000,000,000 free bytes on `/mnt/data` are required at preflight.
ToDesk and other desktop processes are permitted under the user's explicit
development-only local-policy waiver because this stage is deterministic data
conversion, not a runtime benchmark. This waiver does not change any later
scientific or receipt gate.

## Frozen runner

The only runner is
`scripts/materialize_a09_samehistory_warmstart_v1_raw.py`, 15,806 bytes,
SHA-256
`9a858c52760616eaf73d5497e77a5c1c12b75466e39040d19bd845810aaa7693`.
