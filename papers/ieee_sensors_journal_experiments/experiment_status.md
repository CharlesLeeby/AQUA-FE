# IEEE Sensors Journal Experiment Status

- Governance schema: `isj-governance-v2`
- Last updated: `2026-08-06T21:38:00+08:00`
- Current stage: `P07` frontend export execution
- Current stage status: `IN_PROGRESS`
- Next runnable stage: `P07_QUEUE_INDEX_4_B1_GENERALIZED_EXECUTOR_AUDITOR_FREEZE`
- Route note: the July QG candidate remains archived and non-canonical; the
  native-q v3 identity is frozen in final method lock `1d032e4d...`; P04 closed
  with H2 explicitly not applicable; P06/G3 passed after two preserved
  outcome-blind REVISE attempts and a full-reference v4 manifest. P07 adapter
  and 60-job export queue are frozen and dry-run validated. Split-role audit
  corrected the reporting identity to exact-history-excluded windows: 19/20
  are inside development-exposed sequences, H03 is the only sequence-unseen
  window, and no external-held-out window is present. The A02 queue indices
  1-3 (B1/M/P) are terminal COMPLETED under no-clobber audits; P selected the
  valid zero-action `klt_safe_fallback`, was byte-identical to B1, and resolved
  D slot 4 as `NOT_APPLICABLE` before any trajectory outcome access.

## Gate Status

| Gate | Status | Owner / agent | Start time | End time | PASS evidence | Blocking reason |
|---|---|---|---|---|---|---|
| G0 | PASS | Codex `/root` | 2026-07-31T16:48:17+08:00 | 2026-07-31T17:34:01+08:00 | 24 tests；13-arm evo cross-check PASS；`evaluator_protocol_v1.md`；machine decision `HISTORICAL_SIGNAL_REVIEW` |  |
| G1 | PASS | Codex `/root` | 2026-07-31T17:35:13+08:00 | 2026-08-01T13:43:00+08:00 | `isj-window-selection-v1`; 822 history rows; 28 eligible reference sequences; 73/73 checksum PASS; 53 capped candidate slots across 18 sequences/4 domains; P02 bundle validator PASS |  |
| G2 | PASS | Codex `/root` | 2026-08-01T13:49:33+08:00 | 2026-08-06T02:52:21+08:00 | Native-q v3 scientific identity retained; v5 narrowed route lock `fe3a91c3...`; exact backend-consumer contracts for P and M |  |
| G3 | PASS | Codex `/root` | 2026-08-06T02:52:21+08:00 | 2026-08-06T03:23:26+08:00 | Final v4 manifest 10+10/15 sequences/4 domains; 20/20 full reference support; method lock `1d032e4d...`; 100-row narrowed arm order; final freeze validation PASS |  |
| G4 | IN_PROGRESS | Codex `/root` | 2026-08-06T03:23:26+08:00 |  | Adapter lock `8db890ed...`; queue lock `23095fff...`; 60/60 dry-run PASS; RPE analysis lock PASS; A02 B1/M/P completed (3/60 exports); A02 D=`NOT_APPLICABLE` (1/20 slots terminal); trajectory outcomes unread | Extend locked no-clobber executors/auditors beyond the A02 smoke, beginning with queue index 4 B1; then complete the remaining 57 exports and 19 D resolutions |
| G5 | NOT_STARTED | UNASSIGNED |  |  |  |  |
| G6 | NOT_STARTED | UNASSIGNED |  |  |  |  |

## Stage Status

| Stage | Status | Owner / agent | Start time | End time | PASS evidence | Blocking reason |
|---|---|---|---|---|---|---|
| P00 | PASS | Codex `/root/p00_bootstrap` | 2026-07-31T16:42:23+08:00 | 2026-07-31T16:44:30+08:00 | Original v1 bootstrap PASS; v3 contract migration to `isj-governance-v2` recorded in `governance_schema_migration_v1_to_v2.md` |  |
| P01 | PASS | Codex `/root` + `/root/p01_evaluator_audit` | 2026-07-31T16:48:17+08:00 | 2026-07-31T17:34:01+08:00 | `run_g0_evaluator_validation.sh` clean rebuild；24 tests；A10/A09/A06/NTNU/H07；13-arm evo PASS |  |
| P02 | PASS | Codex `/root` | 2026-07-31T17:35:13+08:00 | 2026-08-01T13:43:00+08:00 | `p02/p02_freeze_hashes.sha256`; `p02_validation_report.txt`; frozen history/eligibility/reference/window contracts; `MULTI_SEQUENCE_CANDIDATE` |  |
| P03 | PASS | Codex `/root` | 2026-08-01T13:49:33+08:00 | 2026-08-06T03:23:26+08:00 | Native-q v3 identity `19b0e475...`; narrowed v5 route lock `fe3a91c3...`; final method lock `1d032e4d...`; P04/P05 contracts PASS |  |
| P03A | NOT_APPLICABLE | Codex `/root` |  | 2026-08-06T02:52:21+08:00 | July QG-headline route archived; narrowed native-q v3/v5 route and final method lock retained |  |
| P03B | NOT_APPLICABLE | Codex `/root` |  | 2026-08-06T02:52:21+08:00 | QG canonical migration not part of final native-q v3 route |  |
| P04 | PASS | Codex `/root` | 2026-08-04T23:45:38+08:00 | 2026-08-06T02:52:21+08:00 | `PASS_WITH_H2_NOT_APPLICABLE_CARRIER_FEEDBACK`; identifiability audit; exact whole-lineage D audit; actual-v3 A03 zero-action audit; route contract `b8d67305...` |  |
| P05 | PASS | Codex `/root` | 2026-08-04T16:57:00+08:00 | 2026-08-06T02:52:21+08:00 | 5 export-only probes PASS; deterministic NTNU export; P05-specific backend contract `4e31a9a2...`; fresh and reused-bag guard-only PASS | Trajectory comparison is intentionally deferred to P07 after P06 manifest freeze |
| P06 | PASS | Codex `/root` | 2026-08-04T18:03:20+08:00 | 2026-08-06T03:23:26+08:00 | 18/18 screening terminal; attempt01 quota REVISE and attempt02 reference REVISE preserved; v4 final 10+10 manifest; 41 input checksums; arm order; protocol; final freeze validation 0 issues |  |
| P07 | IN_PROGRESS | Codex `/root` | 2026-08-06T03:23:26+08:00 |  | Frozen adapters/queue/analysis; A02 B1 450 frames/157500 observations PASS; M 450/144058 all-XFeat observations PASS; P zero-action 450/157500 PASS and byte-identical to B1; D slot 4 terminal `NOT_APPLICABLE`; registry latest states 3 COMPLETED + 57 PLANNED | Freeze the generalized queue-index-4+ executor/auditor contract while preserving the A02 smoke locks; continue queue order with no VINS until all frontend exports and D slots are terminal |
| P08 | NOT_STARTED | UNASSIGNED |  |  |  |  |
| P09 | NOT_STARTED | UNASSIGNED |  |  |  |  |
| P10 | NOT_STARTED | UNASSIGNED |  |  |  |  |
| P11 | NOT_STARTED | UNASSIGNED |  |  |  |  |

## P07 Live Progress

- Frontend exports: `3/60 COMPLETED`, `57/60 PLANNED`, no latest RUNNING or
  FAILED export state. The preserved B1 e02 auditor failure remains in its
  chain and is superseded only by the locked read-only e03 correction.
- D applicability: A02 slot 4 is terminal `NOT_APPLICABLE`; 19 slots remain
  unresolved. The original 20 pending rows remain as append-only provenance.
- Outcome boundary: held-out frontend outcomes have been read for A02;
  trajectory, APE, and RPE outcomes remain unread.
- Next queue item: index 4, A01 `16200-17100`, arm `B1_klt_nativeq_v3`.

## Status Vocabulary

Stage and gate status values are `NOT_STARTED`, `IN_PROGRESS`, `PASS`, `REVISE`, and `WAITING`. A `PASS` entry includes a directly inspectable artifact or validation record. Detailed run lifecycle values are defined in `README.md` and recorded in `run_registry.csv`.
