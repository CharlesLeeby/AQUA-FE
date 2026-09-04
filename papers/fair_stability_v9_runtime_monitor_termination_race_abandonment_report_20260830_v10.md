# Fair-stability v9 runtime-monitor termination-race abandonment report

Date: 2026-08-30 (Asia/Shanghai)  
Status: **V9 PERMANENTLY ABANDONED; NO V9 RESULT OR ARTIFACT IMPORT INTO V10**

## Scope and disclosure boundary

The formal v9 namespace is
`/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v9`.
It was prospectively frozen for 120 planned coordinates.  At the fail-stop
boundary, the validated aggregate process-state count was exactly 27 terminal
coordinates (`terminal_replicates=27`); ordinal 028 was in
`PIPELINE_INVALID_FAIL_STOP_ZERO_RETRY`, and the other 92 coordinates remained
`READY`.  The frozen analysis gate was never released:
`analysis_authorized=false`,
`outcome_details_withheld_until_all_120_terminal=true`, and all row-, arm-,
case--arm-, window-, and contrast-level result objects remained null.

This report discloses only the aggregate progress count and the control-layer
cause needed to preserve experiment provenance.  It does not identify ordinal
028's case, arm, repeat, trajectory metrics, clean-success status, or any of
the 27 terminal algorithm outcomes.  No incomplete-v9 process count or
control-failure fact may be used to rank systems or infer stability.

## Audited ordinal-028 facts

Ordinal 028 started its estimator under the frozen v9 supervision chain and
produced nonempty estimator output.  The supervised child was reaped, its
process group and known owned-descendant domain were empty, the runner's raw
return code was zero, and `algorithm_failure_codes` was empty.  The runtime
receipt reported:

- `intrusion_detected=false`;
- empty proc and GPU intrusion occurrence lists;
- no monitor probe errors;
- a proven proc sampling stream;
- no GPU start-gap violation and no GPU tail-coverage-gap violation; but
- one GPU `sample_start_contract_violations` entry, labelled
  `probe_start_outside_coverage_interval`, for GPU sample sequence 70.

The relevant monotonic timestamps are exact:

- coverage end: `666277640226102 ns`;
- GPU sequence-70 probe start: `666277640293494 ns`; and
- difference: `67,392 ns = 67.392 us` after the recorded coverage end.

Consequently, the otherwise clean GPU stream could not prove the frozen rule
that every probe start lie inside the supervision coverage interval.  The
runtime receipt therefore set `monitor_proven=false`,
`pipeline_valid=false`, and the sole pipeline reason
`RUNTIME_RESOURCE_MONITOR_UNPROVEN`.  The controller correctly classified the
coordinate as `PIPELINE_INVALID` and entered the preregistered zero-retry
fail-stop state.

This is not evidence of an algorithm failure, external resource intrusion,
GPU contention, estimator crash, or scientific-arm instability.  In
particular, the 67.392 us value is the lateness of a control-plane probe-start
timestamp relative to the monitor's recorded end; it is not an observed
duration of foreign compute and not an estimator performance measurement.

## Control-race diagnosis

The frozen v9 monitor serialized ownership state but did not atomically bind
the decision to start the next scheduled GPU probe to the decision to close
the coverage interval.  Its GPU loop could finish waiting and become committed
in practice to the next probe without first publishing an in-lock reservation.
During the small interval before that probe captured its start timestamp, the
proc/finalization path could prove the owned process domain empty, write the
coverage-end timestamp, and set the stop event.  The already-advancing GPU
iteration could then begin and append its sample after that end.

The ordinal-028 timestamps instantiate exactly the prohibited ordering:

```text
GPU wait released / no reservation exists
    -> ownership-empty path commits coverage end
    -> 67.392 us later GPU sequence 70 records probe start
```

The monitor correctly failed closed when validating the resulting receipt.
The defect is the missing atomic reservation/coverage-close handshake, not a
defect in the frozen proc/GPU interval limits, resource definitions,
ownership model, estimator, input, scientific threshold, or classification
rule.

## Permanent abandonment decision

V9 is permanently abandoned.  It must not be repaired, resumed, reclassified,
continued from ordinal 028 or 029, or completed in place.  The empty retry
allowlist remains binding: ordinal 028 receives no replacement or second
attempt.  Changing the monitor after 27 terminal observations and continuing
the same namespace would mix control regimes inside one planned matrix and is
not authorized.

All v9 outcomes and all files generated for or by v9 are permanently excluded
from v10 scientific use.  This exclusion includes the 27 terminal
observations; ordinal 028 diagnostic output; input and experiment manifests;
generated IMU/image/runtime inputs; backend, control, and attempt freezes;
prepared attempt trees and HFNet caches; dispatch/start/launch claims;
systemd submission, execution, terminal, adoption, and ordinal receipts;
logs, trajectories, runtime-monitor/watchdog/lifecycle artifacts; summaries;
and any derived statistic.  None may enter a v10 denominator, table, figure,
interval, hypothesis test, stability ranking, tuning decision, window
selection, parameter choice, cache, or completion count.

The v9 tree remains retained only as historical control-development
provenance.  This report is stored outside the formal v9 root and does not
mutate, repair, or claim to seal that root.

## Evidence identities

The following retained identities anchor this diagnosis without disclosing a
case or arm:

- aggregate v9 progress summary: size `2797` bytes, SHA-256
  `986b2203a6e60667eb0da34a86df87a3c219e19b2f449a221cea6c4921ccce63`;
- ordinal-028 systemd execution receipt: size `57433` bytes, SHA-256
  `52de26d2a0a52cfafb68e6ea45c66ef8cf55b70ef131ddec7695b91b1739013f`;
- ordinal-028 systemd terminal receipt: size `5557` bytes, SHA-256
  `07aaee82165ccd6676a4918076141bac04ff6d2ed7b02dc6b3f6d63e51d1f25a`;
- ordinal-028 systemd adoption claim: size `25282` bytes, SHA-256
  `cac4335464e2c4d50488f561d9e5079b4e3eeb4c1deb35b2e0a16045909581d5`;
- ordinal-028 systemd adoption receipt: size `25409` bytes, SHA-256
  `050d67491250a23ae73f5a161d8f05ee69fbb91389204387f9f46af30b354cf0`;
- runtime-resource-monitor receipt bound inside that execution chain: size
  `437231` bytes, SHA-256
  `354b6169b5f72af76b3c40fbc90eb471cf0b36f2c92a2b03214a70154432294b`;
  and
- run result bound inside that execution chain: size `20541` bytes, SHA-256
  `d49d11eee1a1f6a20b6bfb8d385fed0b23802ce5ce6f8515ef3bf28a70523955`.

The frozen v9 control documents were
`papers/fair_stability_control_supersession_v9.md` (size `25894`, SHA-256
`d8630f643b0af36381b4c0a8be7d3c4e6f12ef5f8449cc093e13ef7f3ef43f4f`)
and `papers/fair_stability_runtime_exclusivity_addendum_v9.md` (size `35991`,
SHA-256
`30ea679e49099956520f312d12958cb1847e1c23472d00731df6cb235997ac05`).

## V10 correction boundary

V10 must be a fresh, prospective 120-coordinate experiment rooted at ordinal
1.  It imports no v9 outcome, generated artifact, prepared attempt, or cache.
Its only substantive control correction is an atomic probe-start reservation
and coverage-close handshake: a proc or GPU probe must reserve its start under
the same lock that commits coverage termination; coverage cannot close while
a reservation is active; once closure is pending, no new reservation may be
issued; and every reservation must resolve to exactly one published probe or
a fail-closed monitor error before the end timestamp is committed.

The ten-window, four-arm, three-repeat scientific design and all
estimator-facing quantities remain unchanged.  Versioned identities, a fresh
namespace, and inclusion of this report in provenance are administrative
consequences of abandonment, not scientific changes.  V10 must retain the
same complete-matrix disclosure rule: no partial scientific result may be
released before all 120 fresh v10 coordinates have validated terminal
receipts and all 40 case--arm cells contain exactly three terminal repeats.
