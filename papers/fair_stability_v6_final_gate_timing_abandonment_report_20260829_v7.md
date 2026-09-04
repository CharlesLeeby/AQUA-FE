# Fair-stability v6 final-gate timing abandonment report

Date: 2026-08-29 (Asia/Shanghai)  
Experiment: `fair-stability-positive-roster-openloop-runtimeexcl-v6`  
Formal root: `/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v6`

## Decision

The complete v6 experiment is permanently abandoned at planned ordinal 20.
No v6 result may be adopted now, reclassified, imported into, pooled with, or
used to fill a cell of v7.  The terminal receipts for ordinals 1--19 and every
ordinal-20 artifact remain diagnostic/audit evidence only.  No further v6
`submit`, `adopt`, `run-next`, estimator execution, adjudication, or same-cell
replacement is authorized.

No manual or ad hoc adoption claim, adoption receipt, pipeline-invalid
adjudication receipt, ordinal terminal receipt, or replacement authorization
may be created for ordinal 20.  In particular, submission 002 must remain
unadopted: its permanent-HALT result is the evidence that v6 cannot continue,
not an unfinished transition that may be completed later.

## Trigger at ordinal 20

Ordinal 20 was `fjord1_s83_d10 / hfnet_openloop_350 / repeat_001 /
attempt_001`.  The first systemd submission started the estimator.  After the
unchanged 1800 s estimator budget, the attempt published
`status=PIPELINE_INVALID` with the pipeline code
`ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`.  The estimator timed out, received
the runner's ordinary timeout SIGTERM, returned `-15`, was reaped, and left an
empty process group.

The watchdog targeted a 0.20 s polling interval and v6 treated 0.25 s as its
maximum.  It recorded a maximum interval of
`0.285977402003482` s and the monitoring error
`FINAL_SIGNAL_GATE:WATCHDOG_POLL_WINDOW_EXCEEDED_BEFORE_SIGNAL`.  Estimator
stdout contains the complete ordered `Shutdown`, target-save, one-map, and
zero-keyframe signature.  The watchdog reached its pre-signal path but the
late final-gate interval disabled the action.  It attempted no signal, sent no
SIGTERM, and recorded `monitor_proven=false`; after the failed gate, its final
outcome retained `last_confirmed_signature=null` and a null signature
first-observed time.  Those null final-state fields cannot be used to erase
the stdout signature or to claim that the mandatory 30 s/action proof
succeeded.  The receipt contains 9000 samples.

The independent runtime resource monitor remained proven, detected no
external intrusion, and recorded no pipeline-failure reason.  The invalidation
therefore came from the frozen v6 watchdog/control timing contract, not from
ToDesk, another external process, GPU contention, or an estimator-identity
drift.

## Root cause

V6 coupled the ordinary sampling timeline to the pre-signal timing check and
then cleared the candidate-specific signature state after that check failed.
Consequently the receipt proves neither an eligible signal nor a clean passive
no-trigger outcome: it exposes the final-gate error while retaining no
admissible first/final confirmation chain.  This is a control-evidence timing
failure.  The watchdog correctly failed closed under the frozen v6 contract,
but that contract and implementation cannot support completion of a fair
120-cell comparison and cannot be changed in place after 19 terminal cells.

The ordinal-20 result also contains the diagnostic algorithm codes
`ESTIMATOR_TIMEOUT`, `TRAJECTORY_INVALID`,
`TRAJECTORY_COVERAGE_BELOW_50_PERCENT`,
`NO_VALID_KEYFRAME_TRAJECTORY`, `FINAL_ATLAS_EMPTY_OR_UNPARSEABLE`, and
`NO_SUCCESSFUL_INITIALIZATION`.  They are not admissible algorithm outcomes:
the mandatory watchdog evidence failed closed before the ordinal could become
terminal.  They may not be counted as an HFNet failure or used in any
stability comparison.

## Two-submission stop chain

Submission 001 used unit
`aqua-fe-fair-stability-v6-o020-a001-s001-9f79332d2a09.service` and
InvocationID `e67285beacf84f27ace1408c09cbe404`.  Its claim time was
`2026-08-29T14:33:47.584977+00:00`, its service started at
`2026-08-29T14:33:49.516431+00:00`, and the controller returned 0 with
`PIPELINE_INVALID_REQUIRES_ADJUDICATION`.  Its submission, start, execution,
terminal, adoption-claim, and adoption-receipt chain is complete.  The
adoption receipt records `estimator_retry_authorized=false` and no ordinal
terminal receipt.

Submission 002 used unit
`aqua-fe-fair-stability-v6-o020-a001-s002-8bac5f2b4848.service` and
InvocationID `c7c0edd8f38d48da930081a41eae73e7`.  Its claim time was
`2026-08-29T15:05:15.187742+00:00`, its service started at
`2026-08-29T15:05:17.161478+00:00`, and it deliberately started no estimator.
It revalidated the persistent/control failure and returned 1 with the exact
controller error:

`ControllerError:PERSISTENT_OR_CONTROL_PIPELINE_FAILURE_HALT_MANUAL_ABANDONMENT_REQUIRED:['ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN']`

Its submission, start, execution, and terminal receipts exist, but no adoption
claim or adoption receipt exists.  There is also no ordinal-20 terminal
receipt, pipeline-invalid adjudication receipt, or authorized replacement
attempt.  This is the prospectively required permanent HALT for a
non-allowlisted control failure.

## Pinned evidence

The frozen v6 experiment anchors are:

- `experiment_manifest.json`: size 114832, SHA-256
  `6ad9be866d8cd43f2d9a433c37930074aeef7a8b37d2e07ec9665d1a84128d81`;
- `planned_schedule.json`: size 12957, SHA-256
  `8fdb07f404bc4a24a3866dc1acd6cf8a20b9c960b84d6a9e430299852bc655e8`;
- `attempt_matrix_freeze_v6.json`: size 88757, SHA-256
  `7f3db7e541f9f49495185330b7dfaa1cfda35a935d1752483e1a22b71eb2d4ae`;
  and
- `vins_dev_nativeq_schedfix_runtimeexcl_v6/backend_freeze.json`: size 191039, SHA-256
  `17c801aaecb5dfaf55f8ec42ef9de70c9271675993e26a95654a8e7c961ba5c6`.

The ordinal-20 attempt-root evidence below is under
`hfnet_openloop_350/fjord1_s83_d10/repeat_001`:

- `attempt_manifest.json`: size 5641, SHA-256
  `19825b07fa44557642e9093f897ba366a2a3b12976488e9a630df4d79bee2a7c`;
- `ordinal_dispatch_claim.json`: size 1623, SHA-256
  `3c72816e7f276fdc88e38ebb6607e755547874937863c6f8a78a2b8bb23ecc98`;
- `start_claim.json`: size 5100, SHA-256
  `07a9539e539b5761012e27cbdc03618c8302afcb589afc99cb29102797756596`;
- `launch_receipt.json`: size 1921, SHA-256
  `9a3f880804dcaf84ac35502fca19cf6f5a1559cd6d26e30d02df352aef48b4fd`;
- `run_result.json`: size 8673, SHA-256
  `8782fffedd5ac8609b8c641180e9fd3fe5bf722ee0833d172629921781ec172c`;
- `zero_kf_post_shutdown_watchdog.json`: size 5776, SHA-256
  `0aed2dfc64f1918daad0ae43b55c6c38381251f534ad78c0cae40620cf7a7dab`;
- `runtime_resource_monitor.json`: size 11925910, SHA-256
  `c8fdff7c395e5b5ab822fb50479c7ce35b05181e2b6cf11b39b7baf1425c6f8e`;
- `headless.stdout.log`: size 2767, SHA-256
  `16e07e7b0fe1c3adc40dbdb46bd4bc101a1696f034663c0ff93dcc2388ca7a6c`;
- `headless.stderr.log`: size 6192, SHA-256
  `44d7cf725f059327e3ffcee15c47b32782f47cb0c41305589efc267f57ffbf78`;
  and
- `controller_dispatch_execution_001.json`: size 2305, SHA-256
  `19cfa3f60ec2631b946a94d47586cab3e67206397e2896bfb57168709275e4e2`.

Submission 001 is pinned under
`systemd_supervision/ordinal_020/submission_001` by:

- `submission_claim.json`: size 8049, SHA-256
  `db9ff106255321c12d29ae5328a2203b47d2cbf9ec3457265ed4be40ecf2e8be`;
- `submission_receipt.json`: size 2962, SHA-256
  `3e8fb90db4748efa890322e874639c4bb78d7d446dd65fa5527efcd1a5227f9a`;
- `systemd_start_receipt.json`: size 6685, SHA-256
  `0f79825c934ab14d51d39f134695d608556d4600ee2db6013dde1c1ffb6ad7a0`;
- `systemd_execution_receipt.json`: size 30895, SHA-256
  `133ba1d6acd7afcd9df61754c8b9244f5eb1423c0b5ae113ace38a79c82aac69`;
- `systemd_terminal_receipt.json`: size 5407, SHA-256
  `cdb7ba298b4d9d5ae8207cbf8674599d3858cdc6def1ba6597da229a973b252e`;
- `systemd_adoption_claim.json`: size 12323, SHA-256
  `1d2473f9b8e4b6594baa5c15f2fca2331d1ba36c85b35b68bc8f624a82ea6784`;
- `systemd_adoption_receipt.json`: size 12493, SHA-256
  `ddb052d8b7c49e8a939863ff8892214946455e08e32ab0bd09fff80b36db4d44`;
  and
- `controller.stdout.log`: size 18445, SHA-256
  `8ce6839930976724b5011baf7fe22b2a9059961570706484ac17cdbc338e4f6b`;
  and
- `controller.stderr.log`: size 0, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

Submission 002 is pinned under
`systemd_supervision/ordinal_020/submission_002` by:

- `submission_claim.json`: size 17821, SHA-256
  `7b2d72a2a34edc75789da5658191a1c21cb02304ffdb78f4e325455d5c5a3d97`;
- `submission_receipt.json`: size 2963, SHA-256
  `9c71e7c2fcc18c724e4157345f470aa29181409749871aba64adc54fa2626bfd`;
- `systemd_start_receipt.json`: size 6686, SHA-256
  `8441eac37ae991dbe9da961684b28ceb5199d54bf1215abddf892c9c00d1ff89`;
- `systemd_execution_receipt.json`: size 11641, SHA-256
  `d27f14ca5cd389776b1e76c5c022002d982a9b1fe0ca04d77b7361dfb48c9036`;
- `systemd_terminal_receipt.json`: size 5416, SHA-256
  `13d0d78a15f5dc5de7d83397e6620a5507ef66475a4653b7f50f23e2dcbe4dfd`;
  and
- `controller.stdout.log`: size 0, SHA-256
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`;
  and
- `controller.stderr.log`: size 132, SHA-256
  `46078e14cc662925dac28d3167fb613fe5e2e47c1e96db7e11daee9c6f2b44fa`.

The ordered ordinal-terminal inventory contains exactly 19 receipts.  Using
the sorted records `name\0size\0sha256\n`, its SHA-256 is
`232e9b5fa4cad08e09a5a67e513a0a20ca904a6835a05871aae38666aa4b63b0`.

## Statistical and provenance consequences

No v6 ordinal, including the 19 previously terminal ordinals, may enter a
primary or secondary endpoint, denominator, p-value, bootstrap interval,
summary, table, figure, or system ranking.  The six ordinal-20 diagnostic
algorithm codes likewise provide no evidence that HFNet is less stable.
Partial v6 outcomes may be cited only to explain the control failure and the
need for a successor protocol.

V7 must be a fresh 120-cell experiment beginning at ordinal 1 under one frozen
control implementation.  It must not copy or import any v6 formal result,
generated runtime input, attempt manifest, matrix, attempt cache, claim, log,
receipt, or summary.  The authoritative upstream roster, source bags, raw
images, configurations, binaries, libraries, models, and shared randomization
seed may be reused only after fresh v7 validation; v7 must regenerate and
freeze its own runtime inputs, manifests, backend freeze, attempts, matrix,
and summary.  Every v7 input manifest, backend freeze, attempt matrix, and
summary must state all six of
`v1_results_imported=false`, `v2_results_imported=false`,
`v3_results_imported=false`, `v4_results_imported=false`,
`v5_results_imported=false`, and `v6_results_imported=false`.

## Required v7 control correction

The 0.20 s watchdog target and fixed 0.25 s maximum remain unchanged, but the
maximum is phase-scoped rather than a lifetime eligibility rule:

1. Before an exact complete trigger candidate exists, a late ordinary poll is
   recorded but does not permanently invalidate the attempt.
2. During the 30 s continuous-confirmation phase, only intervals no greater
   than 0.25 s count.  A longer interval resets that candidate's confirmation
   window and clears its first/final proof state; it sends no signal and does
   not by itself add a pipeline code.  A fresh clean 30 s confirmation may
   begin while the unchanged 1800 s budget remains.
3. Only after a complete uninterrupted 30 s confirmation enters the final
   signal gate do both exact identity proofs and the immediately pre-`killpg`
   interval have to remain no greater than 0.25 s and monotonic.  A violation
   there disables the signal and produces the non-retryable pipeline code
   `ZERO_KF_POST_SHUTDOWN_WATCHDOG_UNPROVEN`; no fallback signal is allowed.
   Gate timing begins from a newly recorded monotonic baseline after
   confirmation.  A lifetime maximum or earlier ordinary-sample timestamp is
   diagnostic only and cannot be reused as the gate-local interval.

If no complete trigger is ever observed, or candidates appear but no clean
confirmation completes before ordinary termination, the watchdog must publish
a proven no-trigger/unconfirmed/passive outcome.  An ordinary phase-0 or
confirmation-phase poll gap alone must not erase the estimator's normal
return-code or timeout classification.  The correction
changes only control observation and final signal eligibility.  It does not
change any estimator binary, model, input, parameter, threshold, feature
budget, retry rule, or the 1800 s estimator budget, and it does not
retroactively repair or reclassify v6.
