# Fair-stability runtime-exclusivity addendum v2

Ordered normative bundle (later items refine earlier items without rewriting
them):

1. `fair_stability_positive_roster_protocol_v1.md`;
2. `fair_stability_vins_supervised_shutdown_addendum_v1.md`;
3. `fair_stability_control_supersession_v2.md`; and
4. this runtime-exclusivity addendum.

`fair_stability_v1_runtime_contamination_report_20260829.md` is the provenance
record explaining why v1 was superseded.  The v2 input manifest and backend
freeze must bind all five files by absolute path, byte size, and SHA-256.

This addendum supersedes the parent's output namespace with
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v2`
and adds a prospective runtime-exclusivity contract.  The roster, 120-cell
schedule, admitted timestamps, arm definitions, thresholds, and reporting
boundaries are unchanged.

No v1 experiment manifest, case manifest, attempt manifest, timing cache,
dispatch/start/result receipt, or summary may be copied into v2.  The shared
roster, source data, model, configurations, and backend binaries may be reused
only after fresh identity verification.  The backend and controls are rebound
under v2; the algorithmic backend itself is not claimed to reproduce P07.

## Continuous intrusion monitor

Every attempt must pass the existing pre-start resource gate.  From immediately
after the single supervised `Popen` until that process has been reaped, the
runner also samples:

1. `/proc` at intervals no greater than 0.25 s for external estimator, ROS,
   rosbag, frontend-exporter, or compiler processes; and
2. `nvidia-smi` at intervals no greater than 1.0 s for external GPU compute
   applications.

Only the exact supervised root identity, its process group, and descendants
whose ancestry was first observed while owned by that root are excluded.
Ownership is keyed by `(PID, Linux start ticks)` and never inherited by a
reused numeric PID; this also lets a proven child remain owned if it later
changes process group.  PID, start ticks, PGID, executable, and a command-line
SHA-256 are recorded for every offending process when readable. Probe timestamps,
maximum observed sampling gaps, probe errors, and pre/post samples are retained
in `runtime_resource_monitor.json`.  Runtime measurements remain ineligible for
performance claims.

Ordinary ToDesk display/remote-control processes may remain open.  There is no
name-based ToDesk exemption: if any ToDesk process appears in the GPU compute
application query, it is external compute and invalidates that attempt.

This is a sampled exclusion contract, not a kernel exec-event trace.  A clean
receipt supports the statement that no conflict was observed at the specified
sampling cadence; it does not prove that an arbitrarily short process entirely
between two samples never existed.

## Classification

Any external conflicting process or GPU compute application observed between
launch and reap adds `MIDRUN_EXTERNAL_RESOURCE_INTRUSION` and makes the attempt
`PIPELINE_INVALID`, regardless of its apparent algorithm outcome.  A monitor
probe error or a proc/GPU sampling-gap violation adds
`RUNTIME_RESOURCE_MONITOR_UNPROVEN` and is also `PIPELINE_INVALID`.

The immutable invalid-attempt receipt is retained and the same planned cell is
replenished under the normal ordinal controller.  Algorithm failures observed
in a contaminated attempt are diagnostic only and are excluded from the
algorithm denominator.  No v1 result is imported; v2 restarts at ordinal 1.
