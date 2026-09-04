# A08 recovered-July frontend attempt-002 infrastructure amendment v1

Date: 2026-08-28 (Asia/Shanghai)

This amendment is additive.  It does not erase, replace, or relabel frontend
attempt 001.

## Terminal status of attempt 001

The single KLT supervisor process for attempt 001 was started once and exited
with return code 1 before the exporter was invoked.  The only log line is:

```text
/opt/ros/noetic/etc/catkin/profile.d/1.ros_distro.sh: line 3: ROS_DISTRO: unbound variable
```

The attempt-001 run directory is empty: it contains no `features.bag`, metrics,
camera configuration, VINS output, APE, or RPE.  The terminal evidence is:

- process-start claim: 123,991 bytes, SHA-256
  `d87c9e33a508003a76939d04e132cb293a383ffb77bf9ae7cefe423ebdb6b22d`;
- supervisor log: 91 bytes, SHA-256
  `86545b23ad558c32d40807734e556cac85727a62f69640198be653b738f93d22`;
- failure receipt: 837 bytes, SHA-256
  `6801f0db2b5cb409648588a0dc01dc31c383732699ecc645a61c174d0e249e37`.

Attempt 001 is therefore a terminal pre-export infrastructure failure, not a
KLT outcome and not a zero-accuracy result.

## Root cause and the sole correction

The dataset runner is frozen with `set -u` and sources the ROS Noetic and
VINS-Fusion setup scripts.  The newly sealed process environment correctly
removed the ambient desktop shell, but it did not seed the canonical ROS
variables that ROS's generated environment hooks dereference before assigning
defaults.  The earlier environment probe sourced the same scripts without
`set -u`, so it did not expose this launcher defect.

Attempt 002 may add only the two bootstrap values that the generated hooks
dereference before assigning their own defaults: `ROS_DISTRO=noetic` and
`ROS_MASTER_URI=http://localhost:11311`.  A clean-environment differential
probe confirmed that the complete environment after sourcing ROS and VINS is
otherwise byte-for-byte identical (apart from shell bookkeeping) to the
non-`set -u` source chain.  Attempt 002 preflight must run the full
learned-profile -> ROS -> VINS setup chain under `set -euo pipefail`, verify
the CUDA interpreter and isolated exporter import, and hash the resulting
setup/underlay closure.

No raw input, timestamp, image range, every-N setting, camera model, frontend
configuration, July exporter, XFeat checkpoint, KLT/XFeat method parameter,
arbitration rule, output audit, VINS setting, support window, or evaluation
rule may change.  Frames 4000 and 4500 remain unrearmed.  Attempt 002 uses new
tags and new exclusive claim/log/receipt paths; attempt-001 evidence remains
immutable and is itself a fixed input to attempt 002.

This correction is authorized because it is fixed entirely from a deterministic
pre-export launcher error and uses no feature, trajectory, APE, or RPE outcome.
It must be reported as an additive infrastructure recovery, never as an
automatic retry or as evidence that attempt 001 passed.
