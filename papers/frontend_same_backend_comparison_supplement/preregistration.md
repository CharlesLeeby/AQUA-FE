# AQUA-FE fixed-backend long-window supplement: preregistration

Registered 2026-09-02 18:11:29 +08:00, before any frontend or VINS outcome from this supplement was inspected. The frozen candidate roster is [candidate_windows.csv](candidate_windows.csv); its contemporaneous checksum is recorded in [preregistration.sha256](preregistration.sha256).

This is a **frontend-isolation comparison**: KLT, SP+LG, and XFeat-seed are replayed through one frozen `VINS-Fusion-origin` backend. It lies in the SuperVINS/XFeat-VINS frontend design space. HFNet-SLAM has a keyframe/local-BA backend, is outside this table, and may appear only as a separate reference; no whole-system accuracy claim against HFNet-SLAM is permitted.

The endpoint is closed-loop convergence/runability and proxy-scale observability, not centimetre-level localization. COLMAP/dataset trajectories are proxies, so APE/RPE mean agreement with proxy rather than independent-GT absolute error.

## Outcome-blind window enumeration

The scientific window is a nonoverlapping physical time interval, not a camera stream. A 45 s window length and 45 s stride are fixed because a half-open 45 s interval has at least 40 samples on the 1 Hz proxy grid while retaining margin above the unchanged 30-pose/10 s accuracy gate.

1. For every named low-texture/planar source, anchor the lattice at the first usable image stamp and enumerate half-open intervals `[45k,45(k+1))` seconds. Keep every complete interval with at least 40 supported 1 Hz proxy grid points. Do not replace or shift a failed interval.
2. AQUALOC Archaeo06 has one locally continuous 100 s source assembled from the five contiguous, boundary-overlapping `0_400` through `1600_2000` bags. Deduplicate equal header stamps, then enumerate all complete 45 s intervals: `[0,45)` and `[45,90)`. The 10 s tail is recorded as ineligible and is not a replacement pool.
3. AFRL cemetery is synchronized stereo. To prevent double-counting one physical interval as two scientific windows, assign even lattice indices to front-left (`FL`, `cam0`) and odd indices to front-right (`FR`, `cam1`). Enumerate all complete intervals through `[360,405)`; the incomplete `[405,450)` interval is ineligible. The input/reference audit then excludes `[360,405)` because only 35 of its 46 nominal 1 Hz grid points have proxy support, below the predeclared 40-point margin. The excluded interval remains in both ledgers. The camera assignment and exclusion depend only on timestamps/reference availability, not method outcomes.
4. Add exactly one no-harm anchor: the earliest complete Harbor07 segment, `[0,50)` seconds (`harbor07_0_1000.bag`). It is an anchor, not part of the low-texture lattice and is not replaceable.
5. No texture score, learned-feature result, VINS initialization result, APE, or RPE was used to define this roster. Prior input/reference audits are used only for image counts, timestamp mapping, and proxy availability.

There are 12 enumerated intervals: 2 Archaeo06, 9 AFRL cemetery (5 FL, 4 FR), and 1 Harbor07 anchor. Eleven are metadata-eligible for the frontend prescreen; AFRL `[360,405)` is retained as `INELIGIBLE_PROXY_SUPPORT`. Every interval remains in `runability.csv`, including metadata, preprocessing, infrastructure, identical-bag, or runability failures.

## Frozen arms and frontend contract

The primary arms are exactly:

- `klt`: `method=klt`;
- `splg`: `method=hybrid_superpoint_lightglue`;
- `xfeat_seed`: `method=hybrid_xfeat`, frozen config `P_legacy_nativeq_xfeat_seedchain_v3` (`low_texture_xfeat_seedchain_frontend.yaml`, SHA-256 `6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3`).

All use the same live exporter bytes, SHA-256 `fdb624f24d97fe032c1cdcf0600dd07b370e498f32806ac6eba25467d8020c04`. Historical July Learned+KLT output or a renamed KLT fallback is forbidden. The only arm-dependent fields are frontend method/source identity and the corresponding learned frontend computation.

The seed-chain/runtime contract is frozen exactly as in the parent experiment: `MEASUREMENT_SELECTION=0`, `EXPORT_MAX_FEATURES=350`, `VINS_SAFE_SOURCE_SELECTION=0`, `every_n=2`, `frame_offset=1`, `FORCE_EXPORT=1`, `RUN_VINS=1`, `VINS_MULTIPLE_THREAD=0`, `PROCESS_SKIPPED_FRAMES=1`, preprocessing `adaptive_clahe`, backend quality mode `vins_safe`, quality floor `0.8`, quality alpha `0.65`, and profile `lineage_early_seed_scan`. Image indices, image/IMU bounds, timestamp origin, feature budget, source selection, quality mapping, thresholds, gates, and sampling phase are common. No value may be tuned by arm/window or changed after outcomes.

## Stage-2 frontend prescreen

The prescreen is a pre-registered runability gate, not result-based window selection. Export all three feature bags for every candidate before VINS scoring. For an arm/window, frontend coverage is

`number of scheduled every_n=2 feature epochs containing a nonempty /feature_tracker/feature message / number of scheduled image epochs`.

An arm is frontend-runable iff coverage is at least 70%, the bag contains IMU through the same two boundaries, and the bag passes the frozen 350-feature/message and timestamp audits. A window survives to VINS replay only if all three arms are frontend-runable. Every failure stays in `runability.csv` with a classified reason; no replacement window is introduced.

If all three feature bags for a window have identical SHA-256 bytes, that window is excluded from frontend attribution following the `a02` precedent and marked `EXCLUDED_IDENTICAL_FEATURE_BAGS`, not counted as a frontend result. Pairwise identity is also reported, but the mandatory exclusion is the all-three byte-identical case stated in the task.

## Frozen VINS replay and gates

Each surviving arm/window feature bag is immutable and replayed three times; its SHA-256 must be identical across the three replay manifests. No backend rebuild is allowed. The pinned backend is:

- `vins_node`: `4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278`;
- `libvins_lib.so`: `373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8`.

For each window, one canonical VINS YAML with one fixed scratch `output_path` is reused byte-for-byte by all arms and repeats, which execute serially; each finished `vio.csv` and `vins.log` is copied into its immutable arm/repeat directory before the scratch path is cleared. Camera calibration is likewise byte-identical within a window. `backend_config_audit.csv` records exact SHA-256 equality, not normalized equality.

The unchanged gate sentence from the parent preregistration is:

> Runability is the primary endpoint. An arm/window is `PASS` only if all three repeats initialize and each reaches at least 70% temporal coverage. A failure is classified as configuration/infrastructure, cold-start/no initialization, insufficient excitation, early termination, or coverage failure; it remains in the table.

The numeric common-support gate is unchanged: at least 30 common poses, at least 10 s common span, at least 70% common temporal coverage, at least 10 common 1 s RPE pairs, and all nine trajectories (three arms by three repeats) must pass. If any arm/repeat fails, the window does not enter the accuracy denominator but remains in runability reporting.

## Accuracy, alignment, and reporting

For each admitted window, form one pose intersection and one 1 s RPE grid shared by all nine trajectories. Repeats are summarized by median and full range; the independent scientific unit is the window, not the repeat.

Two explicitly labeled alignment columns are mandatory on the identical common support:

1. **Primary fixed-scale proper SE(3):** independent rigid alignment per trajectory; no scale fitting.
2. **Secondary Sim(3) diagnostic:** independent similarity alignment per trajectory, with fitted scale reported for every repeat. It diagnoses whether a large fixed-scale error is dominated by scale unobservability and cannot rescue runability/common-support admission or silently replace the primary metric.

APE and 1 s RPE are computed by the in-repository common-support evaluator and independently cross-checked with `evo`. Any discrepancy is reported. `accuracy.csv` includes every and only common-support-admitted window; no post-outcome trimming, different per-arm grids, or silent scale fitting is allowed.

## Storage and artifact discipline

At registration, `/mnt/data` has only 2.8 GiB free and reports 100% use, while `/home/ma/AQUA-FE_WS` has 25 GiB free. New artifacts therefore remain under this workspace and never use `/mnt/data`. Before each export/replay batch, free space and the pinned binary/exporter hashes are rechecked. Final delivery includes feature-bag, `vio.csv`, and `vins.log` paths plus SHA-256 in `artifacts.sha256`.
