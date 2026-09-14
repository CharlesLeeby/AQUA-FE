# Native timestamp identity clarification — before any local VIO

Registered 2026-09-15 before the first local repeat, while the unchanged complete
Bus KLT export is running. This adds no matching tolerance or estimator change.

The installed frozen source uses `feature_callback: header.stamp.toSec()` into
`inputFeature(double)`, stores that double in `Headers[]`, then `pubKeyframe`
constructs `ros::Time(Headers[WINDOW_SIZE-2])` for both pose and points. Thus raw
integer nanoseconds are not necessarily the same integers on the publication.
`ros::TimeBase::fromSec` uses rounded fractional nanoseconds; Python genpy uses
truncation and is not a substitute for this C++ conversion.

We reproduce the deterministic forward conversion, using **captured original
feature headers**, and require a unique exact match from each native pose/point
header to that set. Only that original image timestamp is looked up. Missing
identities or collisions fail; no nearest-image search or tolerance is added.
The archive keeps original and published timestamps in `header_identity.csv`;
the unchanged native published timestamp remains the keyframe/graph timestamp.
Pixels, local poses, 3D points and observations are not changed or synthesized.

Independent check: the installed ROS C++ time library was used in the small
[time probe](../../scripts/tests/loop_ros_time_conversion_probe.cpp), without
running VINS. All **7338/7338** complete Bus image timestamps exactly match the
Python forward conversion; **7300** differ from their raw integer value, maximum
absolute difference **119ns**, **0 collisions**. This validates representation
identity, not geometric correctness. The prior exact-raw-integer archive join
would have failed; it had not processed a real archive or produced results.

Archive tests now10/10, candidate8/8 and independent/evo evaluator6/6: total24/24.
Evaluation tests explicitly reject reflection/degenerate alignment, retain the
70% full reference denominator, and do not bridge missing seconds for1s RPE.
No original protocol threshold, model or sequence changed.

Separately, a small read-only reference/IMU consistency check may compare the
two explicit orientation directions, using fixed supplied camera/IMU calibration
and td, no fitted bias/offset/scale and no local/learned outcomes. This is a
reference-field audit, not selection of whichever system error is smaller;
consistency alone is not automatic certification of a world/camera convention.
