---
type: heldout-selection-protocol
date: 2026-08-06
project: AQUA-FE
status: FROZEN_SELECTION_COMPLETED_EXTERNAL_HELDOUT_UNAVAILABLE
---

# Held-out selection protocol and evidence boundary

## Frozen identities

- Final method lock: `1d032e4d43b2a647626b40cef906144dcceab523126bfee3b345b05b4efb578d` (`papers/ieee_sensors_journal_experiments/method_lock.json`).
- Final outcome-blind window manifest: `papers/ieee_sensors_journal_experiments/dataset_manifest_v4.csv`, 20 windows, 10 low/degraded and 10 normal, 15 sequences and four data domains.
- Window selector and screening identities: `papers/ieee_sensors_journal_experiments/p06/final_freeze_v1.sha256` and `p06/b1_screening_code_hashes_v2.sha256`.
- Frontend queue lock: `23095fffe3474d3c85fd809c94b0bf4cd0094aa8bbc083b65dd1a4cc950144eb`.
- Analysis lock: `207f2654fe0dd660205298c63a389ea894461b8224c596cd5537b28cfc2d0835`.

## Outcome-blind selection rule

Candidate windows are fixed 45 s intervals scored only from KLT and image-quality measurements. The frozen score uses KLT grid coverage, dropout/churn and flat/degraded image evidence; learned-feature, VINS, APE and RPE outcomes are excluded. The final quota contains three `ABSOLUTE_LOW`, seven `RELATIVE_Q80_FALLBACK`, and ten `STRICT_NORMAL` windows. Ties and replacements follow the frozen P06 global-quota and full-reference-support rules. All selected evaluator grids require 100% reference support before frontend export.

The execution order remains: B1/P/M frontend export with `RUN_VINS=0`; resolve D applicability from learned-born lineage count; freeze the backend replay queue; only then execute and read trajectory outcomes. Zero-action P requires a byte-identical B1 feature bag. Positive D requires an exact whole-lineage deletion audit.

## Held-out identity correction

The additive split audit (`p07/split_role_audit_v1.csv`) supersedes the broad held-out label in the frozen manifest for reporting. Nineteen windows are exact-history-excluded intervals inside development-exposed sequences. H03 is the only sequence-unseen window and is normal texture. There is no sequence-unseen low/degraded window and no external-held-out window.

The four T1 external candidates do not repair this gap:

- FLSea-VI is not staged beyond metadata.
- UVVID Orientkaj has no independent metric trajectory contract and is development-exposed.
- The local UMA-VI sample has no independent trajectory reference and is too short for three windows.
- CIRS has unresolved calibration/reference provenance and is development-exposed.

Therefore the frozen 20-window matrix may be described only as an **outcome-blind, exact-history-excluded multi-sequence matrix**. It must not be described as external-held-out or sequence-held-out low-texture validation. The maximum submission disposition without a newly staged, independently frozen supplement is `CONDITIONAL_MULTI_SEQUENCE_VINS_PRIMARY`.
