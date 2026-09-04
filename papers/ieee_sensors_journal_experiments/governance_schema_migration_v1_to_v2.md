# Governance Schema Migration v1 to v2

- Migration time: `2026-07-31T21:00:57+08:00`
- Trigger: IEEE Sensors Journal execution contract `v3`
- Source schema: `isj-governance-v1`
- Target schema: `isj-governance-v2`
- Source registry rows: header only; no physical run events required row conversion

## Preservation

The original registry is preserved byte-for-byte as `run_registry_v1.csv` with SHA-256:

```text
f30eed120fe60f0f9913526349359a2187d237b55a6c60bd5ab5f6f3f3adfd9e
```

Existing ledger lines remain unchanged. The canonical `run_registry.csv` now uses the v2 header before any P02+ run rows are appended.

## Field Mapping

- All v1 columns remain present.
- `algorithm_hard_failure` is retained as a deprecated compatibility field; new writers use `replay_hard_failure` and `window_arm_hard_failure`.
- Added conditional-arm fields: `arm_applicability`, `applicability_rule`, `accepted_lineage_count`, `active`, and `selection_active`.
- Added deterministic audit field: `frame_chain_hash`.
- Added replay reducer fields: `replay_evaluable`, `replay_hard_failure`, `window_arm_hard_failure`, `any_repeat_hard_failure`, and `window_arm_solver_risk`.
- Added `arm_applicability.csv` as an append-only resolution stream. P06 appends `PENDING_APPLICABILITY`; P07 appends `APPLICABLE` or `NOT_APPLICABLE` after proposed export and before trajectory metrics are read.

## Validation Contract

- Parse both registries with Python `csv.DictReader`.
- Parse every ledger line as one JSON object and require unique `event_id` values.
- Require the canonical registry to contain every v3 field.
- Require `arm_applicability.csv` to contain the frozen 15-column schema.
