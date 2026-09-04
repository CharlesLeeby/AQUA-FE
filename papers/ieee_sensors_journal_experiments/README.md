# IEEE Sensors Journal Experiment Governance

This directory is the governance and paper-evidence control plane for the AQUA-FE IEEE Sensors Journal experiment program. It stores registries, frozen protocols, audit tables, and derived paper artifacts. Executable source remains in `uw_frontend/` and `scripts/`; raw and run-scale outputs remain in their registered data or `logs/` locations.

## Governance Files

- `experiment_status.md`: current gate/stage snapshot. This is the only bootstrap file designed for in-place status updates.
- `run_registry.csv`: append-only v2 event stream for physical experiment attempts.
- `run_registry_v1.csv`: immutable pre-v3 header snapshot; do not append new events.
- `arm_applicability.csv`: append-only conditional-control resolution stream.
- `execution_ledger.jsonl`: append-only stage, decision, failure, replacement, and freeze ledger; every line is one complete JSON object.
- `failures_and_replacements.md`: append-only human-readable failure and replacement index.
- `README.md`: governance schema and operating rules.

Schema version: `isj-governance-v2`. The non-destructive migration is documented in `governance_schema_migration_v1_to_v2.md`.

## P02 And P06 Window Governance

P02 declares the project-local schemas `isj-data-eligibility-v1`, `isj-reference-audit-v1`, `isj-input-reference-checksum-v1`, and `isj-window-selection-v1`. They are versioned P02 contracts, not retroactively claimed as pre-existing governance schemas.

- `history_exclusion_manifest.csv`: exact prior windows that remain development-only.
- `data_eligibility_manifest.csv`: role, integrity, reference, calibration, synchronization, license, and eligibility decisions.
- `reference_audit.csv`: per-sequence reference provenance, rate, coverage, frame/scale, evaluator gaps, and digest.
- `window_selection_protocol.md`: frozen KLT/image-only score, thresholds, percentiles, fixed-window rules, tie-breaks, replacement rules, and P06 commands.
- `window_selection_protocol_v2.md`: current P06 screening identity after
  direct/ROS equivalence repair; scientific score and selection rules are
  unchanged from v1.
- `p02/input_reference_checksums.csv`: input/reference/calibration SHA-256 identities.
- `p02/p02_freeze_hashes.sha256`: hashes of the complete P02 contract bundle.
- `p06/b1_screening_code_hashes_v2.sha256`: current direct/ROS/selector code
  identities.
- `p06/development_calibration_v2.json` and
  `p06/development_score_audit_v2.csv`: exact seven-fixture recalibration and
  `RETAIN_V1_THRESHOLDS` decision.
- `p06/afrl_calibration_correction_v1.json`: non-destructive per-sequence AFRL
  calibration correction. The frozen P02 manifest and v2 runner remain
  preserved; `bus_outside` and `cemetery` screening must use
  `scripts/run_p06_ros_screening_v3.py` so raw-bag CameraInfo is checked before
  export and the dedicated camchain is recorded in the run audit.
- `p06/afrl_calibration_correction_v1.sha256` and
  `p06/screening_runner_hashes_v3.sha256`: frozen correction evidence and v3
  wrapper identities. Calibration-invalid partial attempts are infrastructure
  evidence only and never enter the screening denominator.

P04 v4 development controls are kept separate from the frozen v3 candidate:
`scripts/p04_nativeq_arm_replayer_v4.py` consumes normalized master events and
emits a distance/grid P/C/B2 interface with `B_active=8`. That admission is not
the frozen v3 early-seed/microburst arbitration and remains interface
infrastructure rather than selected-method evidence. The binding decision is
`p04/implementation_decision_v3.md`; the machine route contract and human
amendment are `p04/nativeq_v3_route_contract_v1.json` and
`p04/nativeq_v3_route_addendum_v1.md`.

Frozen v3 cannot identify a strict shared-carrier C control after learned
tracks feed back into tracker state. The final route therefore requires
`B0/B1/P_legacy/M`, retires C and B2, and retains only conditional
whole-lineage `D_legacy`. H2 is explicitly
`NOT_APPLICABLE_CARRIER_FEEDBACK`, not PASS. The NTNU P-to-D audit proves exact
whole-lineage deletion while preserving every other serialized message and
observation; D is interpreted only as a direct backend exposure effect on the
learned-conditioned carrier.

P02 does not own `dataset_manifest.csv`, `window_selection_audit.csv`, `dataset_checksum_manifest.txt`, or `arm_order.csv`. P06 creates those only after the method hash and export-only contract probes are frozen. Rebuild and validate P02 with:

```bash
python3 scripts/build_p02_audit.py --hash-local-inputs
python3 scripts/validate_p02_bundle.py --write-freeze-hashes
```

## Final P06 selection

The first guarded v2 final-selection attempt is preserved in the canonical
`dataset_manifest.csv`, `window_selection_audit.csv`, and
`p06/screening_progress.json`; it is `REVISE` because the absolute low rule
left only four sequence-capped candidates. It must not be used as the final
manifest.

The outcome-blind v3 quota repair is also preserved and marked `REVISE` by its
independent final reference validator. Eight of its selected windows did not
have 100% evaluator-grid reference support.

The final PASS artifacts are versioned explicitly:

- `dataset_manifest_v4.csv` and `window_selection_audit_v4.csv`;
- `p06/screening_progress_v4.json`;
- `p06/final_artifact_validation_v4.json`;
- `dataset_checksum_manifest.txt` and `arm_order.csv`;
- `environment_manifest_nativeq_v5_final.txt`;
- `method_lock.json` and `protocol_v1_nativeq_v3.md`;
- `p06/final_freeze_v1.sha256` and
  `p06/final_freeze_validation_v1.json`.

The final manifest contains 10 degraded/low and 10 normal windows across 15
sequences and four domains. All 20 evaluator grids have full reference
support. The low/degraded set contains three `ABSOLUTE_LOW` and seven
`RELATIVE_Q80_FALLBACK` windows; tier counts are a mandatory reporting item.
The 100-row arm order assigns four required arms plus one conditional D slot
per window. C and B2 have no rows.

## P07 pre-outcome execution governance

The binding P07-P11 closeout plan is
`p07/p07_to_p11_execution_plan_v1.md`; it supersedes the P07-P11 portions of
the July 30 execution prompts without changing the frozen method, windows, arm
order, or evaluator. The machine lock is
`p07/preoutcome_analysis_lock_v1.json` and freezes common-support exact 1 s
translation RPE RMSE as the primary metric before any P07 outcome access.

The final manifest's `SEQUENCE_HELD_OUT...` field is preserved as a frozen
selection artifact but superseded for reporting by
`p07/split_role_audit_v1.csv/json`. Nineteen selected windows are exact-history
excluded intervals within development-exposed sequences; only H03 is
sequence-unseen, it is normal texture, and the matrix has no external-held-out
window. The allowed identity is therefore an outcome-blind,
exact-history-excluded multi-sequence window matrix, not sequence-held-out
low-texture or external cross-domain validation.

P07 uses this phase order:

1. allocate canonical export run IDs and append 20 pending D slots;
2. complete and attest all 60 B1/P/M frontend exports with `RUN_VINS=0`;
3. resolve all D slots and exact-drop-audit every applicable D before reading
   any trajectory metric;
4. freeze a backend queue with 240 required replays plus three per applicable
   D window;
5. execute one VINS-origin replay at a time, then evaluate and reduce under the
   frozen RPE contract.

An invalid/missing P parent resolves D as
`UNRESOLVABLE_PARENT_FAILURE` with D `BLOCKED`; it is never rewritten as zero
accepted lineages. Formal queue execution is no-clobber, records exact command,
guard decision, logs and hashes, and requires a storage-capacity preflight.
Infrastructure replacements use a new run ID and attempt tag while preserving
the original attempt.

## Native-Q Legacy Route And P05

The July QG method candidate remains in `method_lock_candidate.json` as a
non-canonical development record. The honest incremental route uses separate,
versioned artifacts and does not rewrite that file:

- `method_lock_nativeq_legacy_candidate_v2.json`: preserved pre-equivalence
  native-q candidate, superseded only because its exporter hash changed.
- `method_lock_nativeq_legacy_candidate_v3.json`: current non-QG native-q
  scientific frontend candidate used for P06 outcome-blind screening; it is
  preserved and is not the final `method_lock.json`.
- `method_lock_nativeq_legacy_candidate_v4.json`: additive guarded-execution
  candidate over v3. It does not change frontend selection; it binds the exact
  VINS quality consumer and routes any mismatch to a separately labelled fresh
  KLT fallback that cannot count as a proposed result.
- `method_lock_nativeq_legacy_candidate_v5.json`: narrowed route lock after P04
  closeout. It preserves the v3 scientific identity, removes stale C/B2 slots,
  binds conditional D and the P05 consumer guard, and is ready for the guarded
  P06 final selection. It is still not the final `method_lock.json`.
- `method_lock.json`: final P07-bound lock after the full-reference v4 window
  freeze. Its method-lock hash is
  `1d032e4d43b2a647626b40cef906144dcceab523126bfee3b345b05b4efb578d`.
- `backend_quality_contract_v1.json`: frozen named-quality, clipping,
  anchor/current minimum, `sqrt(q)` factor scaling, source/binary hash, and
  runtime native-q contract. Reused bags require a contract- and SHA-bound
  attestation.
- `2026-08-05--round3-ntnu-quality-partition-correction-v2.md`: additive
  attribution correction for the global-q divergence. The strict analysis,
  replay identities, and figures are under
  `ntnu_q_partition_20260805/analysis-output/`.
- `p05/learned_baseline_fairness.md`: controlled official-XFeat sparse
  pairwise same-backend baseline contract and limitations.
- `p05/fairness_audit.csv` and `p05/fairness_audit.json`: machine audit for
  feature schema, time, coordinate, budget, q, sensor-copy, and deterministic
  export checks.
- `learned_specificity_20260803/round3_ntnu_sha256_manifest.txt`: centralized
  Round 3 development evidence manifest.

The v3 scientific identity entrypoint remains
`scripts/run_isj_nativeq_legacy_candidate.sh`; future execution must enter via
`scripts/run_isj_nativeq_contract_guarded_v4.sh`. The guarded wrapper freezes
all quality mapping values before any learned probe and uses
`scripts/run_isj_classical_contract_fallback_v4.sh` on mismatch. The modern
baseline scientific runner remains `scripts/run_p05_modern_xfeat_baseline.sh`,
but formal execution must enter through
`scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh`. Its P05-specific contract
binds the pairwise XFeat producer, config chain, model, dataset runners, native-q
consumer, and reused-bag attestation; mismatch cannot count as M.
Window-selection v2 is rebuilt with
`scripts/run_p06_development_equivalence.sh` and
`scripts/run_p06_development_calibration_v2.sh`. P06 owns the final method lock
and outcome-blind window manifest.

## Append-Only Rules

1. Keep the CSV header and every existing registry row unchanged. A run lifecycle transition appends a new row with the same `run_id`, a new `registry_event_id`, and `supersedes_event_id` pointing to the immediately preceding event for that run.
2. A replacement is a new physical attempt with a new `run_id`; set `replacement_for` to the original run ID. The original terminal row, directory, logs, and failure evidence remain intact.
3. Append one self-contained JSON object per line to `execution_ledger.jsonl`. Corrections are new events that reference the superseded event in their summary/evidence; existing lines are not edited or removed.
4. Append failure records below `## Records` in `failures_and_replacements.md`. Preserve negative, failed, timed-out, and infrastructure-affected attempts.
5. `experiment_status.md` is a derived dashboard and may be updated in place. A stage may be marked `PASS` only when its evidence paths and validation are recorded in the ledger.
6. Frozen protocol, method, evaluator, dataset, environment, and arm-order artifacts receive a new version when their scientific contract changes. Existing versions remain available.
7. P06 appends conditional D/C slots as `PENDING_APPLICABILITY`. P07 appends the resolution only after the frozen proposed export and before any trajectory metric is read; earlier rows are not edited.

## Status Values

Gate/stage status in `experiment_status.md`:

- `NOT_STARTED`: no stage work has started.
- `IN_PROGRESS`: work is active under the listed owner/agent.
- `PASS`: completion criteria have inspectable evidence.
- `REVISE`: the scientific or implementation contract requires another candidate version.
- `WAITING`: progress is paused on a declared dependency without changing the frozen contract.
- `NOT_APPLICABLE`: a retired or route-specific stage has no work under the
  final frozen method; the disposition and evidence remain visible.

Run status in `run_registry.csv`:

- `PLANNED`: an immutable run identity and inputs have been allocated.
- `RUNNING`: the process has started and is associated with a unique run directory.
- `WAITING`: execution is queued or paused on an infrastructure dependency.
- `COMPLETED`: the attempt finished and required outputs were registered.
- `FAILED`: the attempt reached a terminal algorithm or infrastructure failure.
- `BLOCKED`: the attempt could not start or finish under the registered contract.
- `NOT_APPLICABLE`: the preregistered arm does not apply, such as D/C-QG when P has no accepted lineage.

Conditional-arm status in `arm_applicability.csv`:

- `PENDING_APPLICABILITY`: slot frozen before proposed export.
- `APPLICABLE`: frozen proposed export has `accepted_lineage_count > 0`.
- `NOT_APPLICABLE`: frozen proposed export has `accepted_lineage_count = 0`.
- `UNRESOLVABLE_PARENT_FAILURE`: the proposed parent has no valid audited
  export, so accepted-lineage count is unknown and the conditional arm is
  registered `BLOCKED`.

Boolean fields use lowercase `true` or `false`; an empty value means not yet measured or not applicable and must be explained by status/notes. `full_coverage` and `queue_drop_rate` are fractions in `[0,1]`. Timestamps use RFC 3339 with an explicit UTC offset.

## Run Identity

Use this sortable form for each physical attempt:

```text
<protocol>_<stage>_<dataset>-<sequence>_<start>-<end>_<arm>_f<frontend-seed>_b<backend-replay>_<YYYYMMDDTHHMMSSZ>
```

Example:

```text
isj-v1_P07_aqualoc-archaeo10_2400-2800_P_f20260730_b01_20260820T031500Z
```

Allowed characters are ASCII letters, digits, `.`, `_`, and `-`. Normalize names before allocation and never reuse a `run_id`. Use backend replay `b00` for an export-only attempt. Historical heuristic runs use arm `H_legacy`; confirmation runs use `H_confirmatory`.

Each `registry_event_id` is unique and uses `<run_id>_eNN`, starting at `e00`. `supersedes_event_id` is empty only for the first event of a run. Consumers reconstruct current state by following the non-branching supersession chain, not by editing earlier rows.

## Path and Hash Rules

- Use workspace-relative POSIX paths for artifacts inside `/home/ma/AQUA-FE_WS`; use canonical absolute paths for external workspaces or data.
- `run_dir` identifies one physical attempt and is never reused.
- `command_file` stores the exact executed command and environment invocation.
- `input_hash_manifest` and `output_hash_manifest` point to machine-readable SHA-256 manifests.
- `candidate_pool_hash`, `frame_chain_hash`, and `selection_hash` remain empty for arms where the concepts do not apply; document that in `notes`.
- Backend build, run, and write operations use `/home/ma/SLAM/VINS-Fusion-origin`. `/home/ma/SLAM/VINS-Fusion_3-15-WS` is historical reference only.

## Replay Reducer

- Each applicable `window x arm` has three algorithmic replay slots.
- At least two evaluable replays are required for a numeric window-arm median; otherwise set `window_arm_hard_failure=true`.
- Preserve `any_repeat_hard_failure` separately.
- Set `window_arm_solver_risk=true` when any of the three algorithmic replays has a frozen solver-risk signature.
- Evidence-backed infrastructure replacements do not consume an algorithmic replay slot.

## Validation

Validate after every append using standard-library parsers. The P00 completion event in `execution_ledger.jsonl` records the parser checks and their results.
