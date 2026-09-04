# A10/A09 lifecycle-rearmed fresh paired VINS backend v1 protocol

Status: frozen before any backend child governed by this protocol is started.

## Scope and claim boundary

This protocol covers the two remaining members of the three-window AQUALOC
KLT-positive development roster after the already completed A06 run:

1. A10 natural history `0..2800`, historical score window `2400..2800`;
2. A09 natural history `0..4400`, historical score window `4000..4400`.

The frontend method is
`AQUAFE_XFEAT_LIFECYCLE_REARMED_DIAGNOSTIC_V1`.  It is a new diagnostic method,
not the original frozen final-online system.  Each window is independently
action-gated.  A strictly positive learned-observation count in the exact
historical score window authorizes a fresh paired VINS replay.  A zero count is
retained as a terminal skipped-window result; it does not authorize a backend,
parameter change, retry, crop, or alternate score interval.

Passing the backend contract establishes only same-backend runability and creates
trajectories eligible for the separately frozen evaluator.  Runtime, real-time,
statistical-significance, system-ranking, general-superiority, and confirmatory
claims are forbidden.  The roster and lifecycle policy are development exposed.

## Fixed execution order

Windows and arms are processed in the following non-metric-sorted order:

1. A10 KLT on ROS master port `12091`;
2. A10 lifecycle-rearmed AQUA-FE on port `12092`;
3. A09 KLT on port `12093`;
4. A09 lifecycle-rearmed AQUA-FE on port `12094`.

Within an action-positive window, KLT must terminate and pass structural checks
before AQUA-FE starts.  Each arm is one `Popen`, one complete `rosbag play`, and
zero retries.  A retained failure stops the later arm in the same pair but does not
erase an already accepted arm or prevent the independent later window from being
attempted.  Ambient ToDesk and unrelated VINS workloads are allowed under the
user's development waiver; therefore wall time is provenance only and cannot be
compared.

## Static feature and backend inputs

| Sequence/input | Bytes | SHA-256 |
|---|---:|---|
| A10 external-KLT `features.bag` | 42576500 | `34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f` |
| A10 pinhole calibration | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| A10 external VINS source YAML | 1005 | `46db57acf32b1a8f70cfbe67656b7f8544fd7c761e9f79e3c1832e1cce959370` |
| A09 external-KLT `features.bag` | 66859585 | `cce64be73ddd545ad469e42adddf9cf8f9592f8316adda69399ec27d0b71494f` |
| A09 pinhole calibration | 357 | `045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5` |
| A09 external VINS source YAML | 986 | `b928b31af629bddd9ff677953c185778a2172a0f946fce71bfa1e08b5d879178` |
| replay-only wrapper | 3960 | `1579a330f1db02a964a87d57ade14dc7809306f69e60c83a0d59c969f718d1e3` |
| VINS-Fusion `vins_node` | 13104360 | `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278` |

The lifecycle-rearmed bag is intentionally bound after its frontend-only run, not
predicted here.  Before a backend starts, the controller must bind the exact bag,
frontend terminal receipt, and lifecycle stage receipt; require a positive exact
score-window action gate, backend permission, no earlier backend start, and exact
KLT recovery after deleting learned observations.  All claimed inputs are hashed
again after each replay.

## Fixed replay contract

- Wrapper: `scripts/run_existing_featurebag_vins_replay_only_v1.sh`; it starts no
  accuracy evaluator.
- VINS workspace: `/home/ma/SLAM/VINS-Fusion-origin`.
- IMU topic: `/rtimulib_node/imu`.
- `PLAY_RATE=1.0`, `ROSBAG_PLAY_DELAY=3`, `POST_PLAY_SLEEP=8`.
- Subscriber wait enabled with a 20 s timeout.
- Per-process BLAS/OpenMP thread variables are fixed to 2.
- The source VINS YAML is copied independently into each arm; only `output_path`
  changes.  Normalizing that single field must recover the pinned source YAML and
  produce identical normalized YAMLs for the two arms in a window.
- The copied camera YAML is byte-identical to the pinned calibration.
- No `ape.txt`, evo call, common-support evaluator, or other accuracy process is
  started during trajectory generation.

## Structural acceptance

For every started arm:

- the child return code is zero and inputs are unchanged;
- exactly one `Initialization finish!` marker is present;
- `vio.csv` is finite, strictly timestamp-increasing, has at least 1000 poses and
  100 s span, contains no gap over 0.25 s, starts before the predeclared primary
  evaluation suffix, and ends within 0.25 s of the raw endpoint;
- no failure-detection, tracking-lost, restart, reset, or linear-solver-failure
  marker occurs after initialization;
- replay manifest paths bind the correct feature bag and final output directory;
- the isolated ROS port is released after the child exits.

## Predeclared later evaluation intervals

The primary controlled layer is fresh KLT versus fresh lifecycle-AQUA.  Its suffix
start is selected from raw timestamps only as the latest camera source index that
satisfies both exact duration `>=30.0 s` and native GT count `>=30`.  This rule does
not inspect learned action, trajectory support, or accuracy:

| Sequence | Source indices (inclusive) | Epoch ns (inclusive) | Duration | Native GT |
|---|---|---|---:|---:|
| A10 | `2199..2800` | `1542888905994706672..1542888936039921424` | 30.045214752 s | 31 |
| A09 | `3799..4400` | `1542888935990218544..1542888966034698672` | 30.044480128 s | 31 |

The descriptive context layer is a four-arm comparison on the exact historical
score interval: existing Vanilla, fresh KLT, fresh lifecycle-AQUA, and existing
natural-history HFNet.  A10 uses `1542888916043622160..1542888936039921424`
(`2400..2800`); A09 uses
`1542888946038630384..1542888966034698672` (`4000..4400`).  Both contain only
about 20 s support, so the preregistered 30-pose APE gate is expected to be closed;
gate-closed APE numbers are diagnostic only.  Valid fixed 1 s RPE remains
descriptive if its support gate opens.  The detailed masks, alignments, gates, and
output rules are frozen in the separate evaluation protocol before evaluation.

## Additive output policy

The new root is
`/mnt/data/AQUA-FE_WS/experiments/positive_klt_windows_lifecycle_rearmed_backend_v1`.
The controller never deletes, adopts, or overwrites an accepted, staging, failed,
or terminal path.  Failures and zero-action skips remain visible.  The existing A06
backend and evaluation artifacts are referenced later but are never copied over or
modified by this runner.
