# VINS initialization-state interface audit

Experiment ID: `EXP-20260906-010`

Date: 2026-09-06

Scientific role: read-only interface and causal-feasibility audit; no new
frontend or backend experiment was run.

## Result

**Confirmed fact:** the locked VINS-Fusion backend does not publish an explicit
`initialized` Boolean/status topic or service. It does expose an implicit,
real-time one-way initialization edge: with the unchanged default node name and
private node handle, the first message on `/vins_estimator/odometry` can only be
published after the internal `solver_flag` has changed from `INITIAL` to
`NON_LINEAR`.

**Decision: `DO_NOT_IMPLEMENT_POST_INIT_VARIANT`.** The interface is technically
observable, but it does not support the intended next improvement strongly
enough to justify another development variant:

1. the current AQUA-FE workflow completes a feature bag before VINS replay, so
   it cannot causally consume a backend event;
2. the event exists only after initialization, so it cannot change the initial
   scale branch that produced the retained A09 rescue;
3. the already completed delayed-v3 development experiment kept all frames
   0--31 byte-identical to KLT, acted only after every development baseline had
   initialized, and failed its frozen expansion gate; A09 remained in the KLT
   divergent branch.

Building a live feedback router would therefore be a new execution architecture,
not a small switch in the existing offline exporter. An exact post-init trigger
could be useful for a future post-initialization tracking question, but it is not
evidence-backed as the next route for learned-assisted initialization or the
current more-positive-windows goal.

## Code-path evidence

- `Estimator::solver_flag` is set to `NON_LINEAR` only after
  `initialStructure()`, `optimization()`, and `updateLatestStates()` succeed;
  the log marker follows the assignment (`estimator.cpp:458--477`).
- `processMeasurements()` calls `pubOdometry()` only after `processImage()`
  returns. `pubOdometry()` publishes only when `solver_flag == NON_LINEAR`
  (`visualization.cpp:124--144`).
- Publishers use `ros::NodeHandle n("~")`; under the unchanged node name
  `vins_estimator`, the private `odometry` topic resolves to
  `/vins_estimator/odometry` (`rosNodeTest.cpp:235--266`,
  `visualization.cpp:34--38`).
- `/vins_estimator/imu_propagate` is also gated by `NON_LINEAR`, but it is sent
  from a subsequent IMU callback, so it is not the earliest edge
  (`estimator.cpp:205--216`).
- Internal failure detection and `/vins_restart` can return the estimator to
  `INITIAL`, but no matching `initialized=false` message is published. A simple
  permanent latch would therefore be unsafe across resets.

Three existing replay examples corroborate the source path: each log contains
`Initialization finish!` and the corresponding `vio.csv` begins only through
the same `pubOdometry()` function. The first output header time can lag the ROS
clock at the initialization log because the estimator processes buffered
features; reception latency itself was not recorded.

| Existing replay | init log ROS/bag time (s) | first `vio.csv` header (s) | clock minus header (s) |
|---|---:|---:|---:|
| A09 protected XFeat repeat 1 | 1542889047.417109 | 1542889047.271771 | 0.145338 |
| A02 protected XFeat repeat 1 | 1542828794.013621 | 1542828793.786839 | 0.226782 |
| Bus protected XFeat repeat 1 | 1494876662.469670 | 1494876662.027668 | 0.442001 |

This corroboration does not claim that the ROS output topic itself was recorded;
it establishes that the guarded publisher/file-output code path executed.
Exact transport latency and reset behavior in a new live router remain **Not
evaluated**.

## Identity

Read-only source SHA-256:

- `estimator.cpp`: `ea75d3f074f6c8780fff3353dc1628e94d265e63be13672caed4bdd64dd3572e`
- `rosNodeTest.cpp`: `6606e607df624f7411fcc513e94a42e98b671b8be33a6a4b17052f9ebc99db3a`
- `visualization.cpp`: `a1da39a9c7aba660d4aa7d5d10728e8c08d2699e50670b415e44ce052dd8039e`
- locked `vins_node`: `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278`
- locked `libvins_lib.so`: `373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8`

The external backend source and binaries were not modified.

## Evidence boundary

- **Confirmed fact:** an implicit post-init ROS edge exists.
- **Confirmed fact:** no explicit initialized status interface exists in this
  node, and the current offline exporter cannot consume the edge.
- **Inference:** an online router could gate only subsequent observations, not
  repair the initialization decision that generated the edge.
- **Not evaluated:** whether a newly engineered live router improves any
  post-initialization tracking metric.

The unique decision is to stop this replacement/admission development line
rather than create another slot, horizon, or online-routing variant from the
same outcome-known six windows.
