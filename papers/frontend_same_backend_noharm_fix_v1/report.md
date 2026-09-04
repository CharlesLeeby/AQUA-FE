# XFeat seed-chain final-mirror no-harm fix v1

## Scope

This is a development validation artifact, not a replacement for the frozen
same-backend comparison. Existing experiment bags and tables were not changed.
Because the exporter source hash changed, paper-level APE/RPE claims require a
new preregistered backend/frontend epoch and full three-repeat replay.

The fix implements two publication-time invariants for configurations with an
independent KLT mirror:

1. If no learned/recovered sidecar survives all gates, publish the KLT mirror
   verbatim, including ids, ordering, coordinates, ages, quality, and velocity.
2. If sidecars survive, remap them to a stable disjoint id namespace, replace
   the same number of deterministically ranked mirror tracks, and enforce the
   final `EXPORT_MAX_FEATURES` cap after every gate and persistence step.

The hybrid tracker's private seed state is retained for learned contribution,
but it is no longer authoritative for the classical portion of the published
PointCloud.

## Code changes

- `uw_frontend/ros/export_vins_features.py`
  - added `_finalize_mirror_sidecar_export` as the single final publication
    boundary;
  - added a separate persistent high-id namespace for sidecars;
  - added runtime duplicate-id and feature-cap assertions;
  - added final-mirror diagnostics to `frontend_metrics.csv`;
  - disables learned-triggered classical quality hold effects on a zero-sidecar
    rollback frame.
- `tests/test_final_mirror_noharm_contract.py`
  - exact zero-sidecar mirror restoration;
  - stable collision-free sidecar ids;
  - strict cap with accepted sidecars.

## Verification

### Unit tests

`/usr/bin/python3 -m unittest discover -s tests -p 'test_*.py'`

- 115 tests passed.
- No failures or skips were reported.

### Zero-sidecar real-bag regression

Window: NTNU `fjord_5`, start 60 s, duration 3 s, `every_n=2`.

- KLT: 30 feature messages, all 350 points.
- XFeat-seed: 24 candidates, 17 LK/KLT-confirmed observations, 0 final XFeat
  observations.
- Final mirror rollback: 30/30 XFeat frames.
- KLT and XFeat feature-topic semantic SHA-256:
  `b9ee3252ac258a3e8a5b0dca1f9543ae1810a4c0873b050a432601ed9adc2741`.
- KLT and XFeat complete `features.bag` SHA-256:
  `378458d71e4f91f81e236961501b4fe7680370ac09c5920718b066442052824c`.
- IMU semantic SHA-256 for both arms:
  `2e4747f6a6fe611b040b3811748b26881999a2b5857c82b178838b1678743130`
  over 600 messages.

This directly covers the old counterexample where confirmed-but-rejected XFeat
seeds caused the published count to fall from 350 to 343.

Run directories:

- `logs/ntnu_vins/external_klt_every2_noharmfix_v1_fjord5_s60_d3_klt`
- `logs/ntnu_vins/external_hybrid_xfeat_every2_noharmfix_v1_fjord5_s60_d3_xfeat`

### Accepted-sidecar real-bag regression

Window: AQUALOC archaeology sequence 07, frames 900–930, `every_n=2`.

- 15 feature messages.
- 15 candidates and 12 LK/KLT-confirmed observations.
- 50 final XFeat observations across five frames.
- Every message contains exactly 350 points.
- Every message has 350 unique ids.
- Accepted learned ids are stable in the `10,000,000+` sidecar namespace.
- Each accepted sidecar replaces one mirror KLT observation; no frame exceeds
  the frozen budget.

Run directory:

- `logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_noharmfix_v1_a07_900_930_xfeat`

## Remaining claim boundary

The strong fallback invariant is now verified for the reproduced zero-sidecar
failure path. This does not mathematically guarantee that an accepted learned
sidecar can never worsen trajectory accuracy. Accepted-sidecar non-inferiority
remains an empirical question and must be tested with preregistered equivalence
margins, fixed backend, common support, and three repeats per window.
