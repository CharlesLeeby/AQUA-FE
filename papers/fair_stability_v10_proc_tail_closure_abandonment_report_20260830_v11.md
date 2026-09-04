# Fair-stability v10 proc-tail closure abandonment report

Date: 2026-08-30 (Asia/Shanghai)  
Status: **V10 PERMANENTLY ABANDONED; NO V10 RESULT OR RUNTIME ARTIFACT IMPORT INTO V11**

## Scope and disclosure boundary

The sole formal v10 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v10`.
It was prospectively frozen for 120 coordinates.  Exactly six ordinals had
validated terminal receipts when ordinal 007 entered the preregistered
`PIPELINE_INVALID` zero-retry fail-stop branch.  Ordinal 008 was never
submitted.  The complete-matrix analysis gate was never released.

This report identifies only the aggregate completion count and the
control-layer defect needed for provenance.  It does not disclose ordinal
007's arm, case, repeat, trajectory, keyframe count, clean-success value, or
any outcome of the first six terminal coordinates.  No partial-v10 fact may
be used to rank systems or infer scientific stability.

## Audited ordinal-007 facts

The estimator was admitted by the frozen prestart resource gate, launched
once, and reaped under the frozen systemd and exact-process-identity chain.
The supervised ownership domain was empty at coverage close.  The proc and
GPU monitor receipts contained gap-free sequences with truthful start and
finish timestamps inside the recorded coverage interval.  There were no
probe errors and no observed external proc or GPU resource intrusion.

The GPU sampling contract was proven.  The proc stream had no ordinary
start-gap, ordering, timestamp, or probe-error violation.  Its only failed
condition was the terminal coverage gap:

- frozen proc maximum start gap: `0.25 s`;
- last proc probe start to coverage end: `0.341625403 s`;
- excess: `0.091625403 s`;
- maximum ordinary proc start gap: `0.200414966 s`;
- last proc probe duration: `0.171992770 s`; and
- last proc probe finish to coverage end: `0.169632633 s`.

The receipt therefore correctly set `sampling_contract.proc.proven=false`,
`monitor_proven=false`, `pipeline_valid=false`, and the sole pipeline reason
`RUNTIME_RESOURCE_MONITOR_UNPROVEN`.  The runner returned the frozen
pipeline-invalid code.  The controller and systemd evidence transaction
completed normally, then entered
`PIPELINE_INVALID_FAIL_STOP_MANUAL_REVIEW_ZERO_RETRY`; consequently the
ordinal terminal receipt is intentionally null.  This is not a missing
systemd/adoption receipt and not a successful experiment result.

The child raw return code was `-15`, but the signal came from the frozen
watchdog after exact leader and process-group identity checks.  The child was
reaped, the group was empty, there was no residual attempt process, timeout,
supervisor error, OOM, disk-I/O error, no-space event, NVIDIA Xid, or external
resource intrusion.  Because the runtime monitor was unproven, no algorithm
classification from this coordinate is admissible.

## Control-defect diagnosis

V10 correctly prevented a probe from starting after coverage close and
correctly waited for every active reservation to resolve.  It then performed
a mandatory fresh ownership scan before committing the coverage end.  That
fresh scan was part of the proof of closure but was not published as a proc
sample.  The unchanged tail-gap validator consequently measured from the
start of the preceding ordinary proc sample across both that sample's body
and the unpublished closing scan.

For ordinal 007 the two valid operations took about `0.172 s` and `0.170 s`,
respectively.  Their combined `0.341625403 s` exceeded the `0.25 s` tail
limit even though the closing scan itself continuously observed the
supposedly uncovered interval.  The monitor correctly failed closed against
its frozen schema; the defect is that the closing observation was not
represented in the sampling evidence.

This diagnosis does not justify changing timestamps, deleting a sample,
raising the threshold, adopting ordinal 007, or treating its process outcome
as scientific data.  It identifies a prospective producer/schema correction
for a new namespace only.

## Permanent abandonment and exclusion

V10 is permanently abandoned.  It must not be modified, resumed, repaired,
continued from ordinal 007 or 008, reclassified, or selectively completed.
Ordinal 007 receives no retry or replacement.  The first six terminal
observations and every v10 generated file are excluded from every v11
denominator, statistic, table, figure, interval, hypothesis test, stability
ranking, cache, or completion count.

V11 must start from planned ordinal 1 with 120 freshly generated attempt
trees and receipts.  It may reuse only authoritative upstream data,
preregistered roster definitions, frozen estimator binaries/libraries/model,
configurations, and the shared schedule seed after fresh validation.  It may
not read the v10 runtime namespace during freeze, preparation, execution,
adoption, or summarization.

## Evidence identities

- ordinal-007 systemd execution receipt: size `31431`, SHA-256
  `566bc4f5583cf168e406a985e6c3c35a3c00cc0043deffbf4f3829f60d0c03bc`;
- ordinal-007 systemd terminal receipt: size `5573`, SHA-256
  `8f1c083b7b10a0860aa5397b9f5c00fd9ca195bb4632a3e4607bde9b433b3809`;
- ordinal-007 systemd adoption claim: size `12486`, SHA-256
  `7b50c098e078b60c8c40eb77d6129b77fbfee9a2d99d48dfb6bccf641c02a359`;
- ordinal-007 systemd adoption receipt: size `12657`, SHA-256
  `8a5e7c0793330368163baa09d151f05242723e43c229897760e2e655b2ca2665`;
- runtime-resource-monitor receipt bound by that chain: size `571760`,
  SHA-256
  `f546049b2a661b44d8953ed93b0ce948723f62cb047a02792a5a41aa63df2562`;
- run-result receipt bound by that chain: size `8795`, SHA-256
  `af468ae245edfb4252bc5edcd2735e6f08bb90cec4aa333e3467c6452bdf1de8`;
- frozen v10 control supersession: size `18387`, SHA-256
  `dc1fe9dfffe541c9b1dc31acf6ddd4b413c150f8cb0319d250d63bd716b13646`;
  and
- frozen v10 runtime addendum: size `22257`, SHA-256
  `b594cdfdf58fd88f2da4455915f1c1284d0d217bc81da4cfaa4afbdab4506e82`.

## V11 correction boundary

V11 changes only the closing-monitor evidence model.  After ordinary active
reservations settle in `CLOSE_PENDING`, the mandatory fresh ownership scan
is published as one dedicated closing proc sample with its truthful actual
start and finish timestamps.  Coverage end is committed only after that
sample is published and the exact ownership domain is independently shown
empty.  No ordinary proc or GPU reservation may begin after
`CLOSE_PENDING`.

The proc target (`0.20 s`) and maximum (`0.25 s`), GPU target (`0.75 s`) and
maximum (`1.0 s`), all estimator inputs and parameters, the ten-window by
four-arm by three-repeat schedule, timeouts, watchdog, classifications,
zero-retry rule, complete-matrix disclosure gate, and statistical analysis
remain unchanged.  A closing scan whose own start-to-coverage-end gap exceeds
`0.25 s`, or whose timestamp, ownership, publication, exception, or ordering
chain is unproven, still makes the coordinate `PIPELINE_INVALID`.
