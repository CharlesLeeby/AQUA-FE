# Fair-stability v5 watchdog exit-race abandonment record

Date: 2026-08-29  
Experiment: `fair-stability-positive-roster-openloop-runtimeexcl-v5`  
Formal root: `/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v5`

## Decision

The complete v5 experiment is permanently abandoned after planned ordinal 6.
No v5 result may be imported into, pooled with, or used to fill a cell of v6.
Ordinals 1--5 and the ordinal-6 artifacts remain diagnostic/audit evidence only.
No further v5 estimator submission or same-cell replacement is authorized.

## Trigger

Ordinal 6 was `a07_10800_11200 / hfnet_openloop_675 / repeat_001 /
attempt_001`.  The estimator produced no initialization and no keyframes, then
printed the ordered zero-keyframe shutdown/save signature and terminated itself
with SIGABRT (`raw_returncode=-6`) after throwing `std::system_error` with
`what(): Invalid argument`.  The estimator was reaped and its process group was
empty afterward.

Read-only source inspection additionally located the baseline shutdown bug:
`System.cc` declares `Map* pBiggerMap` without initialization, assigns it only
when a map has more than zero keyframes, and later dereferences it even when all
maps have zero keyframes.  This is a defect of the frozen published-baseline
stack and is intentionally not patched in the successor experiment; a crash
there remains a legitimate system-stability outcome.

The frozen zero-keyframe watchdog sampled the exact leader during the narrow
exit transition.  PID, start ticks, PGID, and session still matched, while
`/proc` exposed neither an executable nor argv.  The v5 implementation treated
that exiting-leader snapshot as
`EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH`, which produced the pipeline
code `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  It sent no signal.

This is a supervision/control race: the underlying HFNet nonzero exit is real
algorithm evidence, but v5 cannot admit it because the mandatory watchdog
proof is fail-closed.  The runtime resource monitor was proven, detected no
external estimator/ROS/GPU-compute intrusion, and reported no probe error.
Thus ToDesk or other external resource use did not cause the invalidation.

## Frozen-rule consequence

The v5 replacement allowlist contains only
`MIDRUN_EXTERNAL_RESOURCE_INTRUSION`.  The observed watchdog code is explicitly
non-retryable, and the watchdog receipt records `retry_permitted=false`.
Accordingly, this attempt cannot be reclassified, retried, or manually counted
as an HFNet algorithm failure inside v5.  The systemd submission/start/
execution/terminal/adoption chain was completed only to seal the evidence; the
adoption receipt records `estimator_retry_authorized=false` and no ordinal
terminal receipt.

## Pinned evidence

- Attempt-matrix freeze: size 88723, SHA-256
  `d511bf06fd8506b4a1851ee148aa30e68d072307d80e69ae3ca0818e19ce17a9`.
- Ordinal-6 `run_result.json`: size 8697, SHA-256
  `6280c19d71c8acc917b7f5bdc55b804506cfb8de67cc16d1e43ffc80d4070c0b`.
- Watchdog receipt: size 5586, SHA-256
  `5fed449ab9d349dd1dc8166e6f4ac5540be51a4e10d8fc25ca9a6be067d5c5ad`.
- Runtime resource monitor: size 322107, SHA-256
  `c47c694c7478d3c56b1cb2647d9dc5f615ab823a154420c7859d0e4b440e2ed5`.
- HFNet stdout: size 2810, SHA-256
  `41bd1763e31dcdee6709a61a59e20f90c67b7b7fad2746115cb119d11fc24e81`.
- HFNet stderr: size 6121, SHA-256
  `d54c5b427dd490e41719e6fd10bba057af6ba1e5071825b7af7d29b2e8ab9d9c`.
- Systemd execution receipt: size 30626, SHA-256
  `8cef95227358218065eaa1122bd61a8adf878b8d728311181db6cc8931418de5`.
- Systemd terminal receipt: size 5407, SHA-256
  `0bf1d0b2f698bac29faafe01aa9ec730549515e5154e31131aba18dd4b6dbd52`.
- Systemd adoption receipt: size 12519, SHA-256
  `6150cdd5a524d7df7a43320a3941c192e643d4bed7dd2d0141530232a6dc3f5b`.

## Required successor behavior

v6 must preserve all estimators, models, inputs, thresholds, open-loop settings,
schedule, statistical analysis, runtime-exclusion rules, and systemd authority.
Its only operational correction is to distinguish a confirmed estimator exit
that races with exact-group observation from identity drift of a still-live
leader.  A naturally or abnormally exited-and-reaped estimator receives the
normal algorithm return-code classification without a watchdog signal; a live
leader whose identity or argv is unproven remains a non-retryable pipeline
failure.  The fix requires explicit positive and negative race tests before a
fresh v6 freeze.
