# Fair-stability v11 watchdog pending-reap abandonment report

Date: 2026-08-30 (Asia/Shanghai)  
Status: **V11 PERMANENTLY ABANDONED; NO V11 RESULT OR RUNTIME ARTIFACT IMPORT INTO V12**

## Scope and disclosure boundary

The sole formal v11 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v11`.
It was prospectively frozen for 120 coordinates. Exactly eight ordinals had
validated terminal receipts when ordinal 009 entered the preregistered
`PIPELINE_INVALID` zero-retry fail-stop branch. Ordinal 010 was never
submitted. The complete-matrix analysis gate was never released.

This report identifies only the aggregate terminal count and the
control-layer defect required for provenance. It does not disclose ordinal
009's arm, case, repeat, trajectory, keyframe count, clean-success value, or
any outcome of the first eight terminal coordinates. No partial-v11 fact may
be used to rank systems or infer scientific stability.

## Audited ordinal-009 facts

The estimator was admitted by the frozen prestart resource gate and launched
once under the frozen systemd and exact-process-identity chain. The child
later terminated itself with raw return code `-6` (`SIGABRT`). Its final
stderr records an uncaught `std::system_error` whose message is
`Invalid argument`. The watchdog did not send `SIGTERM` or `SIGKILL`, systemd
did not terminate the controller, the child was reaped, and the supervised
ownership domain was empty at coverage close.

The frozen runtime-resource monitor was fully proven and did not cause the
failure. Its proc stream contained 176 gap-free samples. The dedicated
closing sample was sequence 175, took `0.048846471 s`, independently proved
the owned domain empty, and left a proc tail gap of `0.048890862 s`. The
maximum proc coverage gap was `0.200114645 s`, below the unchanged `0.25 s`
maximum. The maximum GPU coverage gap was `0.756476354 s`, below the
unchanged `1.0 s` maximum. Both contracts were proven, all probe errors and
observed proc/GPU intrusions were empty, and the receipt set
`monitor_proven=true`, `pipeline_valid=true`.

The first control failure was instead
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`. At the relevant watchdog sample,
the exact supervised leader still had the frozen PID, Linux start ticks,
PGID, and session and was the sole group member. During its terminal
transition `/proc` exposed state `R` but no executable and an empty command
line. The frozen teardown-candidate predicate therefore recognized a legal
terminal-transition candidate, but the v11 loop did not retain that candidate
through the full allowed final-gate interval. It immediately converted the
still-live `Popen` state at the next target-grid observation into
`EXACT_GROUP_UNPROVEN:EXACT_GROUP_LEADER_IDENTITY_OR_ARGV_MISMATCH`.

The candidate snapshot was recorded at monotonic time
`674621563172678 ns`. The independently evidenced closing ownership scan
began at `674621790812225 ns`, after that same `Popen` had been reaped and its
ownership domain was empty. The elapsed interval was `0.227639547 s`: longer
than the `0.20 s` target cadence but shorter than the frozen inclusive
`0.25 s` maximum final-gate duration. Thus the available evidence proves a
valid terminal transition inside the frozen maximum, while the v11 state
machine failed closed before allowing that maximum to elapse.

The immutable result correctly remained `PIPELINE_INVALID`, because the
frozen v11 validator could not retroactively reinterpret its own watchdog
receipt. The systemd evidence transaction completed normally and then entered
`PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`. There was no timeout, supervisor
error, residual attempt process, external resource intrusion, OOM, disk-I/O
error, no-space event, NVIDIA Xid, missing unit receipt, or authorized stop
request. Because the watchdog proof was unproven under the frozen v11 code,
neither the child self-abort nor any other algorithm field from this
coordinate is admissible scientific data in v11.

## Control-defect diagnosis

V11 retained two distinct frozen timing quantities: a `0.20 s` target poll
interval and an inclusive `0.25 s` maximum final-gate duration. A legal
terminal-transition candidate followed by a still-live `Popen` should have
entered a passive, signal-free pending-reap state until the earlier of the
global estimator deadline or candidate-anchor plus `0.25 s`. Instead, the
loop's next scheduled observation followed the `0.20 s` target grid and then
treated a still-live child as permanently unproven. In ordinal 009 the same
child was already reaped and its ownership domain empty no later than
`0.227639547 s` after the candidate snapshot. This proven upper bound was
within the already-frozen maximum but outside that prematurely effective
target-grid window.

This is a watchdog state-machine defect, not evidence for extending an
estimator timeout, changing the `0.25 s` maximum, relaxing exact identity,
retrying the coordinate, or repairing its receipt. It also does not erase the
underlying self-abort: if the same self-abort recurs under a prospectively
corrected watchdog and the complete control chain is proven, it must be
classified by the unchanged algorithm-failure rules.

## Permanent abandonment and exclusion

V11 is permanently abandoned. It must not be modified, resumed, repaired,
continued from ordinal 009 or 010, reclassified, or selectively completed.
Ordinal 009 receives no retry or replacement. The first eight terminal
observations and every v11 generated file are excluded from every v12
denominator, statistic, table, figure, interval, hypothesis test, stability
ranking, cache, or completion count.

V12 must start from planned ordinal 1 with 120 freshly generated attempt
trees and receipts. It may reuse only authoritative upstream data,
preregistered roster definitions, frozen estimator binaries/libraries/model,
configurations, and the shared schedule seed after fresh validation. It may
not read the v11 runtime namespace during freeze, preparation, execution,
adoption, or summarization.

## Evidence identities

- ordinal-009 systemd execution receipt: size `32437`, SHA-256
  `17daf5c4bcfe6a2cc1280fbbeeb64945d9f153eb3e1eca133b26bf8b16aa6ea9`;
- ordinal-009 systemd terminal receipt: size `5573`, SHA-256
  `cc78a9aa9cd5518f8a70087362597f3f59a08f2fd43e672fd6ce25b54806dc44`;
- ordinal-009 systemd adoption claim: size `12972`, SHA-256
  `b5c9fa68ddf750e202f32a906daa41f8ff23be2abddc61f016ae3d43c0ae6031`;
- ordinal-009 systemd adoption receipt: size `13145`, SHA-256
  `61e48269f3f4968f7e559c4b460dc42d6a1fce5c64bf9e275dbc2cb1c779a75b`;
- runtime-resource-monitor receipt bound by that chain: size `265979`,
  SHA-256
  `deba59967548efda088d0bb45aa113650a44527b23a9fb8bbfed41632dbe93bb`;
- zero-keyframe watchdog receipt bound by that chain: size `6226`, SHA-256
  `109ea45803bbd8dbd2a2646834599a50cacc865e66880813a26e22377e39559a`;
- run-result receipt bound by that chain: size `9225`, SHA-256
  `053d768b256907125eb9e03c0bb7cab3e9a2880e97ab56b8304b4405b8a75825`;
- estimator stderr identity bound by that chain: size `6109`, SHA-256
  `149601975aaf0911428f511b8f61f2594111cf66b4d91e23cefa575fc1dac894`;
- frozen v11 control supersession: size `19535`, SHA-256
  `fb413079592ecc36b1b7aaf9fd675ed3130423b0337140758feddc499dab9682`;
  and
- frozen v11 runtime addendum: size `23622`, SHA-256
  `b78706cba449d8fe17bf095147302e248b000687132a4f9ff5e545172784bcb0`.

The operator-private submit and adopt stdout copies have sizes `3271` and
`13145` and SHA-256 identities
`9bcfc4db64633cf192cd7e5e2cdab576e49c37e4faba7ec2d77b0d21a5713314`
and
`61e48269f3f4968f7e559c4b460dc42d6a1fce5c64bf9e275dbc2cb1c779a75b`,
respectively. They are retained as private control evidence and are not v12
inputs.

## V12 correction boundary

V12 changes only the watchdog handling of a legal terminal-transition
candidate whose exact `Popen` has not yet reported exit. Candidate proof
completion creates an explicit `PENDING_REAP` state with an immutable anchor
and a deadline equal to the earlier of the global estimator deadline and the
anchor plus the unchanged inclusive `0.25 s` maximum. The watchdog sends no
signal in this state. It accepts only exit and reap of the same `Popen` within
that deadline, followed by the unchanged empty-ownership proof. A still-live
child at the deadline, a wrong nonempty group, PID/start-tick reuse, identity
drift outside the narrowly frozen teardown predicate, a probe error, or an
unproven timing/reap chain still fails closed.

The `0.20 s` target and `0.25 s` maximum, 30 s zero-keyframe signature,
one-shot signal gate, estimator timeout, all estimator inputs and parameters,
the ten-window by four-arm by three-repeat schedule, runtime monitor,
classifications, zero-retry rule, complete-matrix disclosure gate, and
statistical analysis remain unchanged.
