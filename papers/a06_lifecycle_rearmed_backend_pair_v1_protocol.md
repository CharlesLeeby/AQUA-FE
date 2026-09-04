# A06 lifecycle-rearmed paired VINS backend v1 protocol

Status: frozen after the frontend-only action gate passed and before either paired
VINS child is started.

## Purpose and method identity

The accepted frontend probe
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1` consumed uninterrupted A06 history
from source frame 0 and injected 107 learned observations in the exact historical
action-positive window `2210..2460`. Its terminal receipt status is
`PASS_SCORE_ACTION_GATE_FRONTEND_ONLY`; deletion of all learned observations exactly
recovers the external-KLT carrier across 25,999 ordered ROS messages.

This protocol authorizes one paired development replay to answer whether that
nonzero-action feature bag is consumable by the same VINS-Fusion backend as its KLT
carrier. It does not rename the lifecycle-rearmed diagnostic as the original frozen
final-online method. Runtime, real-time, general superiority, statistical
significance, and cross-window robustness claims remain forbidden.

## Frozen paired arms and order

Both arms replay the same A06 feed `0..2460`, IMU stream, GT proxy stream, camera
calibration, VINS binary, VINS configuration, playback rate, and subscriber wait.
The fixed order is never metric-sorted:

1. `KLT_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1`
   - feature bag: the frozen external-KLT carrier;
   - ROS master port `11966`.
2. `AQUAFE_LIFECYCLE_REARMED_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1`
   - feature bag: the accepted lifecycle-rearmed `full_merged.bag`;
   - ROS master port `11967`.

Each arm is one `Popen`, one complete `rosbag play`, and zero retries. The KLT arm
must terminate and pass structural output checks before the AQUA-FE arm starts.
Ports are isolated from any ambient ROS workload. Ambient ToDesk and unrelated VINS
workloads are permitted by the user's development waiver, so wall time is recorded
only as execution provenance and cannot be compared.

## Frozen inputs

| Input | Bytes | SHA-256 |
|---|---:|---|
| external-KLT `features.bag` | 37403698 | `0779bb8a71e4d81ddf02ba933b7428e548534ab580fd4483754f08e26e9bbeb6` |
| lifecycle-rearmed `full_merged.bag` | 37457074 | `e3594e6da04ed3644fa1e075ee2bd30ca1add3d8d9d244d0debc8b07c64e1bf1` |
| lifecycle frontend terminal receipt | 2644 | `4dd554b066bb67112c792f2e1c5c83a9a57601c941cfc56f6e7094161e33b705` |
| lifecycle frontend stage receipt | 13629 | `4a9a77ccce52673cfc8843cb1de20cb297deaef099e65c6d02e61534ef6ef69a` |
| A06 external VINS config | 976 | `e3b0ef0badfbe4392b3c29f59b1dd0a4d6c5260b528bf7380dc0b17ac4de19d0` |
| A06 pinhole camera config | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| replay-only wrapper | 3960 | `1579a330f1db02a964a87d57ade14dc7809306f69e60c83a0d59c969f718d1e3` |
| VINS-Fusion `vins_node` | 13104360 | `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278` |

The frontend terminal receipt must still report gate value 107, backend permission
true, and no backend previously started by that runner. Both feature bags and all
static inputs are re-hashed before and after each replay.

## Fixed replay contract

- Runner: `scripts/run_existing_featurebag_vins_replay_only_v1.sh`; it starts no
  accuracy evaluator.
- VINS workspace: `/home/ma/SLAM/VINS-Fusion-origin`.
- IMU topic: `/rtimulib_node/imu`.
- GT proxy topic: `/aqualoc/colmap_gt`.
- `PLAY_RATE=1.0`, `ROSBAG_PLAY_DELAY=3`, `POST_PLAY_SLEEP=8`.
- `WAIT_FOR_VINS_SUBSCRIBERS=1`, timeout 20 s.
- The source VINS YAML is copied independently into each arm and only its
  `output_path` is rewritten. After replacing that path with a token, the two runtime
  YAML files must be byte-identical to the frozen source and to each other.
- Camera YAML copies must be byte-identical to the frozen calibration.
- Trajectory generation and accuracy evaluation are separated: no `ape.txt`, evo,
  common-support evaluator, or other error metric is produced by either replay.

## Backend acceptance checks

For each arm:

- child return code is zero and the claimed feature bag is unchanged;
- exactly one `Initialization finish!` marker is present;
- `vio.csv` is finite and strictly timestamp-increasing, has at least 1000 poses and
  at least 100 s span, starts before the predeclared evaluation window, and ends no
  more than 0.25 s before the A06 raw endpoint;
- no `failure detection`, `tracking lost`, or restart marker is present after
  initialization;
- replay manifest binds the correct feature bag and output path;
- ROS master and VINS descendants are reaped at terminal return.

Passing these checks means only that the paired trajectories are eligible for the
separately fixed common-support evaluator.

## Predeclared four-arm common-support evaluation

No accuracy value is inspected until both paired arms pass. The later evaluator uses
this fixed order:

1. existing `VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT` A06 trajectory;
2. fresh `KLT_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1` trajectory;
3. fresh `AQUAFE_LIFECYCLE_REARMED_EXTERNAL_FEATURE_CONTEXT_FRESH_PAIR_V1`
   trajectory;
4. existing `HFNET_SLAM_NATURAL_HISTORY` A06 canonical trajectory.

The exact inclusive window is raw source `1860..2460`, timestamps
`1542883404.763902848..1542883434.765650624` seconds. It was selected without
learned-action or error values as the shortest A06 suffix with at least 30 native GT
messages and at least 30 existing four-arm common 1 Hz points. The historical
action-positive subwindow `2210..2460` is fully contained within it.

Fixed evaluator rules:

- reference `/aqualoc/colmap_gt`, no time offsets;
- uniform 1 Hz grid anchored at the exact start (31 nominal points);
- maximum reference interpolation bracket 2.5 s and estimate bracket 0.25 s;
- one independent proper rigid SE(3) per arm with scale fixed to 1;
- no Sim(3), fitted scale/time offset, snapping, extrapolation, or result-informed
  mask/alignment;
- one joint intersection mask shared by all four arms;
- APE gate: at least 30 joint poses and 10 s;
- RPE: aligned-global-frame positional delta at exactly 1 s, at least 10 joint pairs;
- common coverage at least 0.70; evo 1.31.1 cross-check tolerance `1e-5 m`.

Expected support is 30/31 if the fresh VINS endpoints follow the already observed
non-extrapolation boundary. This is a support expectation, not a frozen metric value.
If support or either metric gate closes, the corresponding values remain explicitly
gate-closed diagnostics.

The output root is
`/mnt/data/AQUA-FE_WS/experiments/a06_lifecycle_rearmed_backend_pair_v1`.
Existing output, staging, or failure paths cause a fail-closed stop; no directory is
deleted, adopted, or overwritten.
