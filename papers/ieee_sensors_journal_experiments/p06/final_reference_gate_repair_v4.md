# P06 final reference-gate repair v4

Date: 2026-08-06  
Status: `FROZEN_BEFORE_LEARNED_OR_TRAJECTORY_OUTCOME`  
Protocol: `isj-window-selection-v4-full-reference`  
Base score/quota protocol: `isj-window-selection-v3-quota-repair`

## Trigger

The v3 quota repair produced 10 degraded and 10 normal windows, but the
independently frozen final-artifact validator rejected eight selected windows
because their final evaluator grids were not fully supported by reference
samples. Screening used the G0 numeric-validity gate (`>=30` supported poses,
`>=70%` coverage, `>=10 s` span); the final protocol separately requires every
selected grid point to be reference-supported.

The rejected v3 attempt is preserved:

- `window_selection_audit_v3.csv` SHA-256
  `f668bd34119c2920d9b82c84f73e72478ead9d5132ecad23abc8516569a84430`;
- `dataset_manifest_v3.csv` SHA-256
  `4c52267a8b96e4c5eb9d8cd8577dd813e49f7798b8d360fc96c2ea13aa719f7b`;
- `p06/screening_progress_v3.json` SHA-256
  `fb2c54ca76f16aaa168ef96a09966f2f1fe4f2134f30a4e4e54330a9882ecec1`;
- `p06/final_artifact_validation_v3.json` SHA-256
  `d97bc230d646b873b2628cff9c739845788a703cd5ee11c8d9b230f8d9132e84`.

The full reference-support table was frozen before final selection:
`p06/reference_window_support_audit_v2.csv` SHA-256
`9a81acea50be6890d29cd533a1566e4e3b783393961e640f8e99131bdd069a0b`.
No learned/proposed export, VINS trajectory, APE, or RPE was read.

## Frozen repair

The only change is gate order:

1. Start from the immutable v2 156-window KLT/image audit.
2. Apply history exclusion and the v3 low/normal score rules unchanged.
3. Require `supported_grid_count == grid_count` and `coverage == 1.0` using the
   frozen reference-support table.
4. Apply the unchanged two-per-sequence cap after this full-support gate.
5. Run the unchanged v3 10+10 rank/diversity solver.

This prevents a reference-incomplete high-ranked window from consuming a
sequence slot that could otherwise be filled by a fully supported window. It
does not refit scores, Q20/Q80, `tau_low`, `tau_normal`, tiers, target counts,
or diversity requirements.

The final manifest must retain the v3 tier labels and record full-reference
support per selected window. If the v4 solver is infeasible, P06 remains
`REVISE`; no further selection adaptation is allowed.
