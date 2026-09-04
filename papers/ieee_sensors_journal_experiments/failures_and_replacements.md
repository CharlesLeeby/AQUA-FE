# Failures and Replacements

This file is the append-only human-readable index for failed run attempts and their replacements. Preserve every original run and its evidence. Append one record for each failure; append a follow-up record when a replacement is created or resolved.

## Record Template

```text
### <failure_id> - <observed_at RFC3339>

- Original run ID:
- Stage:
- Failure class:
- Frozen taxonomy version:
- Detection evidence:
- Original run directory:
- Original terminal status:
- Replacement decision: NONE / PLANNED / CREATED
- Replacement run ID:
- Replacement reason:
- Approval basis:
- Related ledger event IDs:
- Resolution status: OPEN / RESOLVED / ACCEPTED_AS_RESULT
- Notes:
```

## Records

No failure records at governance bootstrap.

### p06-a06-equivalence-attempt01 - 2026-08-04T18:03:20+08:00

- Original run ID: `isj-winsel-v2_P06_aqualoc-A06_2210-2460_EQUIV_f0_b00_20260804T100300Z`
- Stage: `P06`
- Failure class: `NONZERO_EXIT` during development integration; not an algorithmic replay
- Frozen taxonomy version: `isj-failure-taxonomy-v1`
- Detection evidence: `attempt01_failure.md` and preserved partial CSV/bag files
- Original run directory: `papers/ieee_sensors_journal_experiments/p06/development_equivalence/aqualoc_a06_2210_2460`
- Original terminal status: `FAILED`
- Replacement decision: `CREATED`
- Replacement run ID: `isj-winsel-v2_P06_aqualoc-A06_2210-2460_EQUIV_f0_b00_20260804T100808Z`
- Replacement reason: repair unsupported default-quality keyword names without changing metric or reliability semantics
- Approval basis: development-only contract repair before any confirmatory screening
- Related ledger event IDs: `ledger-20260804T180320+0800-p06-equivalence-failure01`, `ledger-20260804T184433+0800-p06-window-v2-freeze`
- Resolution status: `RESOLVED`
- Notes: Replacement paired 251 frames and produced zero absolute difference on all four required screening metrics. No learned or VINS outcome was read.

### p06-afrl-cave-gennie-screening-attempt01 - 2026-08-04T21:55:59+08:00

- Original run ID: `isj-winsel-v2_P06_afrl-cave_gennie_0-709.601295_B1SCREEN_f0_b00_20260804T134549Z`
- Stage: `P06`
- Failure class: `INFRASTRUCTURE_DISK_CAPACITY_PREFLIGHT`; not an algorithmic replay
- Frozen taxonomy version: `isj-failure-taxonomy-v1`
- Detection evidence: `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/cave_gennie/attempt01_failure.md`
- Original run directory: `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/cave_gennie`
- Original terminal status: `FAILED`
- Replacement decision: `PLANNED`
- Replacement run ID: pending direct compressed-image adapter equivalence audit
- Replacement reason: the wrapper materialized a projected approximately 30 GB uncompressed short bag on a filesystem with approximately 12 GB available
- Approval basis: outcome-blind infrastructure repair; scientific score, KLT config, pixels, timestamps, and selection rules must remain unchanged
- Related ledger event IDs: `ledger-20260804T215559+0800-p06-afrl-disk-failure01`
- Resolution status: `OPEN`
- Notes: The closed partial bag was 11,992,547,328 bytes with SHA-256 `cb19e23654579d16ce75df54203674bb966540f566aba23818f43fd08fef5924`; no metrics or learned/VINS outcome were produced.

### p06-afrl-cave-gennie-screening-attempt02 - 2026-08-05T00:11:21+08:00

- Original run ID: `isj-winsel-v2_P06_afrl-cave_gennie_0-709.601295_B1SCREEN_DIRECT_f0_b00_20260804T153031Z`
- Stage: `P06`
- Failure class: `PREREGISTERED_REFERENCE_SUPPORT_EXCLUSION`; intentional SIGINT after eligibility resolution, not an algorithmic or infrastructure failure
- Frozen taxonomy version: `isj-failure-taxonomy-v1` plus `isj-p06-reference-sequence-exclusion-v1`
- Detection evidence: `papers/ieee_sensors_journal_experiments/p06/reference_window_support_audit_v2.csv` and `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/cave_gennie/reference_exclusion.json`
- Original run directory: `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/cave_gennie/attempt02`
- Original terminal status: runner `FAILED` after SIGINT; governance `STOPPED_REFERENCE_INELIGIBLE`
- Replacement decision: `NONE`
- Replacement run ID: not applicable
- Replacement reason: all 15 fixed windows fail the frozen G0 reference-only coverage gate, so no reference-bearing confirmatory window can be selected
- Approval basis: window-selection v2 already requires reference support; v2 support/capacity audit was frozen before score or stratum selection
- Related ledger event IDs: `ledger-20260804T215559+0800-p06-afrl-disk-failure01`; reference-exclusion ledger event follows this record
- Resolution status: `ACCEPTED_AS_RESULT`
- Notes: Direct adapter operation remained valid. Partial metrics contain 1224 contiguous frames; the closed 27,762,223-byte feature bag SHA-256 was `579d6f70860c842a64f00d0ff9d59a9864a956d60e5e3878982d92539aaa6b15` and was deleted after registration. No learned/VINS outcome was read.

### p06-afrl-bus-outside-calibration-attempt-default - 2026-08-05T03:07:22+08:00

- Original run ID: `isj-winsel-v2_P06_afrl-bus-outside_0-584.88264_B1SCREEN_DIRECT_f0_b00_20260804T161324Z`
- Stage: `P06`
- Failure class: `INFRASTRUCTURE_CALIBRATION_CONTRACT`; not an algorithmic replay
- Frozen taxonomy version: `isj-failure-taxonomy-v1` plus `isj-p06-afrl-calibration-correction-v1`
- Detection evidence: `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/bus_outside/calibration_invalid_attempt_v1.json`
- Original run directory: `papers/ieee_sensors_journal_experiments/p06/screening_runs/afrl/bus_outside`
- Original terminal status: `FAILED`; governance status `STOPPED_CALIBRATION_INVALID`
- Replacement decision: `CREATED`
- Replacement run ID: `isj-winsel-v2_P06_afrl-bus-outside_0-584.88264_B1SCREEN_DIRECT_V3_f0_b00_20260805T031727Z`
- Replacement reason: use raw-bag-matched `camchain_bus_outside.yaml` through the versioned v3 wrapper while preserving the frozen P02 manifest and v2 runner.
- Approval basis: outcome-blind input-contract repair; the old partial metrics and feature bag are not scientific results.
- Related ledger event IDs: `ledger-20260805T031727+0800-p06-afrl-calibration-correction`
- Resolution status: `OPEN`
- Notes: The old attempt processed 5718 metric rows with the cave calibration and is excluded. Corrected attempt02 must pass CameraInfo/hash validation before it can enter the P06 terminal count.

### p04-a03-actual-v3-attempt01 - 2026-08-06T01:00:22+08:00

- Original run ID: `p04_actualv3_a03_5000_5900_attempt01_20260806`
- Stage: `P04`
- Failure class: `INFRASTRUCTURE_CALLER_TIMEOUT`; export-only development diagnostic, not an algorithmic replay
- Frozen taxonomy version: `isj-failure-taxonomy-v1`
- Detection evidence: only the 357-byte camera YAML was created before the caller terminated the process; no feature bag or metrics file exists
- Original run directory: `logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_p04_actualv3_a03_5000_5900_attempt01_20260806_probe_oldcontract_densecap`
- Original terminal status: `FAILED_INFRASTRUCTURE_PARTIAL`
- Replacement decision: `CREATED`
- Replacement run ID: `p04_actualv3_a03_5000_5900_attempt01b_20260806`
- Replacement reason: rerun the identical guarded export command without the erroneous one-second caller timeout
- Approval basis: export-only infrastructure replacement before any VINS/APE/RPE/trajectory outcome
- Related ledger event IDs: `ledger-20260806T025221+0800-p04-route-closeout`
- Resolution status: `RESOLVED`
- Notes: The replacement completed 450 frames, selected the zero-action KLT fallback, and is audited in `p04/a03_5000_5900_actual_v3_attempt01b_export_audit_v1.json`. The partial directory and guard decision remain preserved.

### p06-final-selection-attempt01 - 2026-08-06T02:54:00+08:00

- Original run ID: `isj-window-selection-v2_P06_final-selection_attempt01_20260806`
- Stage: `P06/G3`
- Failure class: `SCIENTIFIC_QUOTA_INFEASIBLE`; outcome-blind selection REVISE, not an algorithm or infrastructure failure
- Frozen taxonomy version: `isj-window-selection-v2` plus `isj-p06-global-quota-v1`
- Detection evidence: `p06/screening_progress.json` records four sequence-capped low candidates, 13 normal candidates, and zero feasible 10+10 joint selection
- Original run directory: canonical attempt01 artifacts `window_selection_audit.csv`, `dataset_manifest.csv`, and `p06/screening_progress.json`
- Original terminal status: `REVISE`
- Replacement decision: `CREATED`
- Replacement run ID: `isj-window-selection-v3_P06_final-selection_attempt02_20260806`
- Replacement reason: the frozen absolute low threshold retained only five eligible low windows from two sequences after history/reference gates, below the preregistered diversity minimum
- Approval basis: versioned outcome-blind quota repair using only frozen KLT/image scores, existing Q80/Q20, and existing `tau_normal`; no learned or trajectory outcome was read
- Related ledger event IDs: `ledger-20260806T030205+0800-p06-selection-attempt01-revise`
- Resolution status: `OPEN`
- Notes: Attempt01 files and hashes remain unchanged. The v3 repair must preserve the 10+10 target, tier-label relative fallback windows, and stop without further tuning if infeasible.

### p06-final-selection-attempt02 - 2026-08-06T03:06:53+08:00

- Original run ID: `isj-window-selection-v3_P06_final-selection_attempt02_20260806`
- Stage: `P06/G3`
- Failure class: `FINAL_REFERENCE_GRID_INCOMPLETE`; outcome-blind validation REVISE
- Frozen taxonomy version: `isj-p06-final-artifact-validation-v1` applied to `isj-window-selection-v3-quota-repair`
- Detection evidence: `p06/final_artifact_validation_v3.json` lists eight selected windows without 100% final evaluator-grid reference support
- Original run directory: versioned attempt02 artifacts `window_selection_audit_v3.csv`, `dataset_manifest_v3.csv`, and `p06/screening_progress_v3.json`
- Original terminal status: selection `PASS`, final artifact validation `REVISE`
- Replacement decision: `CREATED`
- Replacement run ID: `isj-window-selection-v4_P06_final-selection_attempt03_20260806`
- Replacement reason: apply the already-frozen 100% final reference-grid gate before the per-sequence cap, then rerun the unchanged v3 score/tier/quota solver
- Approval basis: reference-only gate-order repair using `reference_window_support_audit_v2.csv`; no learned or trajectory outcome was read
- Related ledger event IDs: `ledger-20260806T030851+0800-p06-selection-attempt02-reference-revise`
- Resolution status: `OPEN`
- Notes: The score formula, Q20/Q80, thresholds, tier rule, target counts, and diversity constraints are unchanged. Attempt02 artifacts remain immutable.

### p06-final-selection-revise-resolution - 2026-08-06T03:23:26+08:00

- Original run ID: `isj-window-selection-v2_P06_final-selection_attempt01_20260806`; `isj-window-selection-v3_P06_final-selection_attempt02_20260806`
- Stage: `P06/G3`
- Failure class: resolution record for prior scientific REVISE attempts
- Frozen taxonomy version: `isj-window-selection-v4-full-reference`
- Detection evidence: `p06/final_artifact_validation_v4.json` and `p06/final_freeze_validation_v1.json`
- Original run directory: preserved canonical attempt01 and versioned attempt02 artifacts
- Original terminal status: both remain `REVISE`
- Replacement decision: `CREATED`
- Replacement run ID: `isj-window-selection-v4_P06_final-selection_attempt03_20260806`
- Replacement reason: outcome-blind Q80 quota repair plus preregistered full-reference gate before the sequence cap
- Approval basis: no learned/proposed/VINS/APE/RPE outcome was read; all adaptations and failed manifests remain versioned
- Related ledger event IDs: `ledger-20260806T032327+0800-p06-g3-final-freeze-pass`
- Resolution status: `RESOLVED`
- Notes: Attempt03 passes 10+10, 15 sequences, four domains, 20/20 full reference support, byte-identical deterministic rebuild, and final freeze validation with zero issues.

### p07-queue001-b1-auditor-v1 - 2026-08-06T17:14:15+08:00

- Original run ID: `isj-nativeq-v3_P07_aqualoc_archaeology-A02_4500-5400_B1_f0_b00_20260806T084500Z`
- Stage: `P07_FRONTEND_EXPORT`
- Failure class: `AUDITOR_PATH_DISPLAY_IMPLEMENTATION`
- Detection evidence: the v1 auditor traceback in `p07/frontend_attempts/queue_001_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01/audit.log`
- Original run directory: `logs/aqualoc_archaeo_vins/external_klt_every2_isj_p07_aqualoc_archaeology_a02_0005_b1_attempt01`
- Original terminal status: registry `e02 FAILED` after the physical exporter and native-q attestation both returned PASS
- Replacement decision: `NO_PHYSICAL_RERUN_READ_ONLY_AUDIT_CORRECTION`
- Replacement run ID: none; registry `e03` corrects the same preserved physical attempt
- Replacement reason: v1 resolved the workspace `logs` symlink to `/mnt/data` and then rejected it only while rendering a path relative to `/home/ma/AQUA-FE_WS`
- Approval basis: `b1_auditor_correction_lock_v2.json`; v2 changes only display-path normalization and retains all data, schema, native-q, topic, metrics, and no-trajectory checks
- Related ledger event IDs: `ledger-20260806T172000+0800-p07-b1-auditor-v2-correction-lock`; `ledger-20260806T172500+0800-p07-b1-smoke-pass`
- Resolution status: `RESOLVED`
- Notes: No frontend process was rerun and no bag or metrics file was overwritten. The preserved v2 audit passes 450 frames, 157500 observations, zero learned observations, 14/14 output hashes, and no trajectory artifacts.

### p07-queue007-v3-adapter-prestart - 2026-08-07T03:25:34+08:00

- Original run ID: `isj-nativeq-v3_P07_aqualoc_harbor-H05_1800-2700_P_f0_b00_20260806T084500Z`
- Stage: `P07_FRONTEND_EXPORT`
- Failure class: `PRESTART_EXECUTOR_ENVIRONMENT_ADAPTER_RECURSION`
- Detection evidence: `p07/frontend_prestart_failures/queue_007_isj_p07_aqualoc_harbor_h05_0002_p_attempt01_v3_adapter_recursion/preexecution_failure.json`
- Original run directory: none; only command, input manifest, and capacity preflight were staged
- Original terminal status: registry remains `PLANNED`; no `RUNNING` event was appended
- Replacement decision: `NO_PHYSICAL_REPLACEMENT_ADAPTER_CORRECTION`
- Replacement run ID: none; the immutable queue allocation remains unstarted
- Replacement reason: capture the unpatched base environment function before installing the generalized adapter
- Approval basis: implementation-only v4 correction; frozen command, run ID, tag, data, method, arm, and outcome boundary are unchanged
- Related ledger event IDs: `ledger-20260807T032534+0800-p07-v3-adapter-prestart-failure`
- Resolution status: `RESOLVED`
- Notes: No ROS process, frontend exporter, target run directory, feature bag, learned outcome, VINS, APE, RPE, or trajectory artifact was created or read.
