# Fair-stability v4 ROS Python environment abandonment report

Date: 2026-08-29 (Asia/Shanghai)

## Decision

The formal runtime-exclusive v4 experiment is permanently abandoned.  No v4
result may be imported into a later inferential matrix.  The two adopted VINS
cells at ordinals 1 and 2 remain diagnostic artifacts only.  Ordinal 3 is a
pipeline failure, not an HFNet algorithm failure, and no later v4 ordinal may
be submitted.

## Trigger and evidence

The first HFNet cell was ordinal 3,
`a05_3300_3700 / hfnet_openloop_675 / repeat_001`.  Its transient systemd unit
entered successfully, but the HFNet runner stopped before an estimator launch
or start claim.  The controller stderr is exactly:

`ControllerError:RUNNER_STDOUT_NOT_JSON:rc=1:stderr=ContractError:ROSBAG_IMPORT_FAILED_USE_USR_BIN_PYTHON3`

The immutable evidence identities are:

- submission claim: `c3d084b861031b8df728435912500d5effc2d5c60c8e9b664db07f65a83d016b`
- systemd start receipt: `3f986d4e037f25007540d1ecefb89d6a56067546d3e00f77319749d9a5292d02`
- systemd execution receipt: `06bec0069441647998141a407c128f9e548cdfe9a216df046e0b329143112ce4`
- systemd terminal receipt: `1f20eeb6f866c9ee4c69fad25d858be69a852b19c109f30391f56a1629eb83d0`
- controller stderr: `1948eff3dd903ccd1dee38f2f0455388f5825d7c457cc3984e6399d33800772d`

The ordinal remained `READY`.  Its prospectively prepared
`attempt_manifest.json` existed before submission, but no
`ordinal_dispatch_claim.json`, `start_claim.json`, `launch_receipt.json`, or
`run_result.json` was created, and the systemd cgroup was empty after
termination.  Therefore this event contains no evidence about HFNet stability.

## Root cause

The v4 systemd contract deliberately supplied a minimal deterministic
environment, but omitted ROS Noetic's Python package directory.  Under that
exact environment, `/usr/bin/python3` cannot import `rosbag`.  Adding only
`PYTHONPATH=/opt/ros/noetic/lib/python3/dist-packages` makes the import succeed.
The direct v3 launches inherited a shell environment that contained the ROS
path, which is why this defect did not appear there.

## Prospective v5 correction

V5 must remain a fresh namespace and must hard-code and receipt-bind the single
ROS Python path above in the transient service environment.  Its tests must
prove both that the frozen minimal environment can import `rosbag` and that the
path appears identically in the submission claim and `systemd-run` argv.  V5
must state `v1_results_imported=false`, `v2_results_imported=false`,
`v3_results_imported=false`, and `v4_results_imported=false` in every parent,
backend-freeze, and attempt-matrix gate before any estimator start.

No stability, accuracy, runtime, or superiority claim is made from v4.
