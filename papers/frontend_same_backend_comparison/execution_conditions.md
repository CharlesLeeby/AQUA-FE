# Execution conditions addendum

Recorded before the first successful formal cell.

The shared workstation runs an independent `/mnt/data/Dataset_pool` CPU-export scheduler. It automatically restarted work after an initial quiescence period, so demanding globally idle storage would starve this preregistered experiment indefinitely. Formal cells may therefore coexist with one unrelated CPU exporter.

This does not change any arm, window, sampling, feature-budget, backend, replay, or evaluation parameter. It does invalidate wall-clock efficiency comparisons because arms execute serially under time-varying I/O load. Runtime/throughput is consequently censored and will not support a method claim. Any explicit CUDA/OOM, storage, ROS-drop, or timeout failure is classified as infrastructure and isolated from algorithmic runability.
