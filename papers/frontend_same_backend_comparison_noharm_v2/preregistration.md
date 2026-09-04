# Same-backend frontend comparison: no-harm v2 preregistration

Registered 2026-09-01 21:10:30 +08:00, before any formal `noharm_v2` run.

## Purpose

This is the new formal epoch after repairing the final export-stage no-harm contract. It compares KLT, SP+LG, and the current XFeat seed chain on one exact `VINS-Fusion-origin` backend. Only `method` and the matching frontend source configuration differ. LoFTR remains outside the primary roster.

The eight 30–50 s windows in [windows.csv](windows.csv) are copied unchanged from the earlier pre-registered long-window roster. They were chosen from historical nonempty `vio.csv` evidence, not from noharm-v2 outcomes, and cannot be replaced after execution begins.

## Frozen epoch

- Backend: `vins_node` SHA-256 `4e91d8ac...5f5f4278`; `libvins_lib.so` SHA-256 `373a598c...810f71e8`.
- Exporter: repaired final-mirror no-harm SHA-256 `fdb624f2...0c04`.
- Frontend config: `P_legacy_nativeq_xfeat_seedchain_v3` file SHA-256 `6f89d861...00bf3`.
- Shared contract: `MEASUREMENT_SELECTION=0`, `EXPORT_MAX_FEATURES=350`, `VINS_SAFE_SOURCE_SELECTION=0`, `every_n=2`, `frame_offset=1`, `FORCE_EXPORT=1`, `RUN_VINS=1`, `VINS_MULTIPLE_THREAD=0`, `VINS_ESTIMATE_TD=0`.

The repaired exporter is a new frontend implementation epoch. Its results must not be pooled with or used to relabel the previous main/supplemental trajectories.

## Gates

Runability is primary. A window/arm passes only when all three repeats initialize and each reaches at least 70% temporal coverage. Any failed repeat remains in the runability denominator.

Accuracy is evaluated only when all nine trajectories pass. It uses one all-nine common support, at least 30 common poses, at least 10 s span, at least 70% common coverage, and at least ten exact 1 s RPE pairs. Every trajectory receives an independent fixed-scale proper SE(3) alignment. Sim(3), scale fitting, post-outcome trimming, per-arm grids, and post-outcome window replacement are forbidden. evo cross-check is required.

References are COLMAP or dataset baseline proxies. Reported APE/RPE therefore measure proxy agreement, not independent-GT absolute error.

## No-harm interpretation

The implementation-level invariant applies when zero learned observations survive the complete export path: the backend feature message must equal the independent KLT mirror. When sidecars survive, they replace an equal number of classical tracks under the hard 350-point cap; trajectory non-inferiority in those frames is an empirical question resolved by this batch, not assumed by the implementation.
