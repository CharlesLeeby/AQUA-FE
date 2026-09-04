# Fixed-backend frontend comparison: preregistration

Registered 2026-08-30 12:53:26 +08:00, before any formal run for this experiment ID.

This table is a frontend-isolation comparison: all arms use one frozen `VINS-Fusion-origin` backend and differ only in frontend `method`/source identity. It occupies the same design space as SuperVINS- and XFeat-VINS-style frontend comparisons. HFNet-SLAM uses a keyframe/local-BA backend and is outside this table; it may be mentioned only as a separate reference, with no whole-system accuracy claim against it.

## Primary roster

The seven windows are fixed in [windows.csv](windows.csv): `a02_4500_6300`, `a09_4000_4400`, `a09_6000_6800`, `a10_2400_2800`, `a10_4800_5200`, `h07_1660_1720`, and `mclab1_s60_d15`. No window may be added, removed, or shortened after observing arm outcomes. A missing dataset or infrastructure failure remains in the runability ledger and is not replaced by a favorable window.

The primary arms are fixed in [arms.csv](arms.csv): KLT, SP+LG, and XFeat-seed. LoFTR is optional and excluded from the primary denominator unless a separate supplemental protocol is registered before its execution.

## Frozen fairness contract

All three arms use the same exporter process, image phase (`every_n=2`, `frame_offset=1`), image and IMU boundaries, preprocessing, feature budget 350, VINS YAML generation path, `vins_node`, `libvins_lib.so`, sliding-window parameters, quality mapping, and replay/evaluation code. The fixed environment includes `MEASUREMENT_SELECTION=0`, `VINS_SAFE_SOURCE_SELECTION=0`, `FORCE_EXPORT=1`, `RUN_VINS=1`, `VINS_MULTIPLE_THREAD=0`, and the `lineage_early_seed_scan` seed-chain contract. No gate, threshold, source-selection, quality, window, or backend parameter may be changed per arm or after outcomes are seen.

Each arm/window is exported once and the resulting immutable feature bag is replayed through VINS three times. This preserves identical frontend observations and sampling phase across repeats while measuring initialization/solver-path sensitivity. The feature-bag hash must be identical for the three repeats.

## Runability and accuracy gates

Runability is the primary endpoint. An arm/window is `PASS` only if all three repeats initialize and each reaches at least 70% temporal coverage. A failure is classified as configuration/infrastructure, cold-start/no initialization, insufficient excitation, early termination, or coverage failure; it remains in the table.

Accuracy is evaluated only for windows where all nine trajectories (three arms times three repeats) pass. A single common-pose intersection and common 1 s RPE grid is formed across all nine trajectories. Each trajectory receives its own fixed-scale proper SE(3) alignment. Sim(3), scale fitting, post-outcome trimming, and different pose grids are forbidden. The in-repo evaluator is cross-checked with `evo`; discrepancies are reported rather than silently resolved. Repeats are summarized by median and full range; the scientific unit for cross-method inference is the window, not the repeat.

Reference trajectories are COLMAP or dataset baseline proxies. Metrics are explicitly “agreement with proxy,” not independent-GT absolute error.

## XFeat source-lineage disclosure

The requested config is verified exactly: `low_texture_xfeat_seedchain_frontend.yaml` has SHA-256 `6f89d861...00bf3` and is the config named by `P_legacy_nativeq_xfeat_seedchain_v3`. The earlier P contract also pinned exporter SHA-256 `7ed31890...eae7cf`, but those exact bytes are no longer present; the live exporter is `68453b03...f2312d`. Therefore this experiment pins the live exporter once and uses it for every arm. It will be described as a fresh execution of the P seed-chain config on the common current exporter, not as byte-exact replay of the earlier P execution tree. Historical KLT fallbacks and July Learned+KLT trajectories are forbidden substitutes.

The complete machine-readable contract, including full hashes and exact thresholds, is [contract.json](contract.json).
