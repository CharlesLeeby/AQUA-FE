# P07 execution adapter addendum v1

Date: 2026-08-06  
Status: `FROZEN_FOR_FRONTEND_EXPORT_QUEUE`  
Adapter lock: `8db890ed77885e3359e29ec8d22edb7c9ef07d422ef1e4254b0ee01a2be494be`  
Final method lock: `1d032e4d43b2a647626b40cef906144dcceab523126bfee3b345b05b4efb578d`

This addendum supplies explicit execution provenance for B0 and B1. It does
not change the final scientific method, window manifest, quality mapping,
feature budget, arm order, or evaluator.

## Entrypoints

- B0: `scripts/run_isj_b0_native_vins_guarded_v1.sh`;
- B1: `scripts/run_isj_b1_klt_nativeq_guarded_v1.sh`;
- P: `scripts/run_isj_nativeq_contract_guarded_v4.sh`;
- M: `scripts/run_p05_modern_xfeat_baseline_guarded_v2.sh`;
- D audit: `scripts/audit_whole_lineage_exact_drop_v1.py`.

B0 verifies the exact VINS-origin source and binary identity before entering a
dataset runner in native mode. B1 verifies the same consumer plus the frozen
external exporter/config and native-q mapping before a fresh KLT export or an
attested bag replay. A contract mismatch rejects the requested arm and cannot
be relabelled as a valid result.

The standard family API uses seconds for NTNU/AFRL and frame indices for
AQUALOC. AQUALOC frame bounds are `round(relative_seconds * 20)`. All final
windows were dry-run through the four dataset-family mappings without starting
VINS. Formal exports and replays must use the exact commands frozen in the P07
queue artifacts.

Outcome boundary:
`EXECUTION_ADAPTER_ONLY_NO_HELD_OUT_FRONTEND_OR_TRAJECTORY_OUTCOME`.
