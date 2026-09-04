# P06 A06 Development Equivalence Attempt 01

- Status: `FAILED_INFRASTRUCTURE_CODE_PATH`
- Scope: development-only direct/ROS screening equivalence probe
- Direct input: AQUALOC A06 frames `2210-2460`
- ROS input: `datasets/aqualoc/rosbags/archaeo06_2210_2460.bag`
- Learned/VINS outcome read: no

The ROS exporter stopped on its first feature frame before an equivalence
decision. `_backend_reliability(mode="default")` called
`_apply_backend_sidecar_quality_scale()` with the unsupported keyword
`learned_quality_const` instead of the helper's frozen keyword
`learned_const` (and the analogous source-specific names). The direct task was
running concurrently and was terminated without a complete CSV when the
orchestrated attempt failed.

Preserved partial artifacts:

- `attempt01_direct_metrics_partial.csv`
- `attempt01_ros_metrics_partial.csv`
- `attempt01_ros_features_partial.bag`

This attempt has no scientific result and is not counted as a replay. The
parameter-name regression was repaired without changing backend reliability
semantics, covered by a unit test, and the same development probe was rerun as
Attempt 02.
