# Window Selection V2 Development Calibration Report

- Protocol candidate: `isj-window-selection-v2`
- Status: `PASS`
- Threshold decision: `RETAIN_V1_THRESHOLDS`
- `tau_low`: `0.17`
- `tau_normal`: `0.10`
- Held-out learned/P/VINS outcome read: no

## Why V2 Exists

The P02 v1 B1 manifest froze earlier hashes of
`run_frontend_eval.py` and `export_vins_features.py`. Both files later changed,
so the v1 protocol cannot be reused for P06 by assertion. V2 preserves all
scientific score, threshold, percentile, fixed-window, tie-break, history
exclusion, and replacement rules, but registers the current code identities
and repeats development calibration.

## Direct/ROS Equivalence

The AQUALOC A06 `2210-2460` development probe paired 251 direct-runner frames
with 251 ROS-adapter frames. Direct indices `2210-2460` and ROS indices
`0-250` match after a constant offset. Maximum absolute differences were:

| Metric | Maximum absolute difference |
|---|---:|
| `grid_coverage` | 0.0 |
| `dropout_ratio` | 0.0 |
| `flat_region_ratio` | 0.0 |
| `degradation_score` | 0.0 |

The first attempt failed before an equivalence decision because of a default
backend-quality keyword regression. Its partial outputs and failure note are
preserved. The repaired path has a focused unit test and does not change the
four screening metric definitions.

## Full Development Recalibration

All seven v1 fixtures were recomputed into a new P06 directory. Comparing the
four required fields row by row against the v1 inputs produced exact equality
for every frame of every fixture. Recomputed type-7 scores and classifications
also match exactly:

| Fixture | Rows | Score | Stratum |
|---|---:|---:|---|
| AQUALOC A06 `2210-2460` | 251 | 0.177161287227 | low |
| AQUALOC H06 `2280-2490` | 211 | 0.076382044320 | normal |
| AQUALOC H07 `1660-1720` | 61 | 0.156381628816 | unclassified |
| AFRL cemetery FR `005-410` | 406 | 0.249415113423 | low |
| AFRL cemetery FL `080-319` | 240 | 0.191931795535 | low |
| Tank short `000-299` | 300 | 0.030627337628 | normal |
| UVVID cannon `000-179` | 180 | 0.311139586848 | low |

Whole-file CSV hashes differ because non-screening columns such as
`runtime_ms` are not deterministic. The outcome-blind selector reads only the
four audited metrics, frame identity, and timing; those values are exact.

## Machine Evidence

- `development_equivalence/aqualoc_a06_2210_2460/equivalence_audit.json`
- `development_equivalence/aqualoc_a06_2210_2460/frame_equivalence_audit.csv`
- `development_score_audit_v2.csv`
- `development_calibration_v2.json`
- `development_calibration_v2/*/metrics.csv`

This report authorizes freezing `isj-window-selection-v2`. It does not itself
authorize learned or VINS evaluation on the confirmatory candidate pool.
