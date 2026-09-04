# Underwater Frontend Research Prototype

This package is the frontend-only track for the quality-guided hybrid
underwater VO/VIO study. It now contains the classical baselines and the
quality-aware hybrid frontend: `GFTT + KLT` carries normal frames, relaxed LK
and ORB recover recently lost tracks, and XFeat, SuperPoint+LightGlue, or LoFTR
can be invoked by the underwater degradation scheduler.

## Run AQUALOC Harbor Sequence 07

The reader can stream PNG frames directly from the `.tar.gz` archive without
extracting it.

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/klt_frontend.yaml \
  --method klt \
  --max-frames 120 \
  --output-csv logs/aqualoc_harbor07_klt_frontend.csv \
  --save-viz-dir logs/aqualoc_harbor07_viz \
  --save-viz-every 30
```

Run the first KLT/ORB comparison:

```bash
MAX_FRAMES=120 bash scripts/run_aqualoc_frontend_compare.sh
```

Summarize arbitrary frontend CSVs:

```bash
python3 -m uw_frontend.evaluation.summarize_results \
  logs/aqualoc_harbor07_klt_frontend_smoke.csv \
  logs/aqualoc_harbor07_orb_frontend_smoke.csv \
  --output-md logs/aqualoc_harbor07_frontend_compare_summary.md
```

Scan a sequence to find candidate degraded segments before running the full
frontend:

```bash
python3 -m uw_frontend.evaluation.scan_sequence_quality \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --every-n 5 \
  --output-csv logs/aqualoc_harbor07_quality_scan.csv
```

Evaluate a candidate degraded window:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/klt_frontend.yaml \
  --method klt \
  --start-index 720 \
  --end-index 900 \
  --output-csv logs/aqualoc_harbor07_720_900_klt.csv
```

Run the quality-aware hybrid frontend with XFeat recovery:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/klt_frontend.yaml \
  --method hybrid_xfeat \
  --start-index 1660 \
  --end-index 1950 \
  --output-csv logs/aqualoc_harbor07_1660_1950_hybrid_xfeat_qaware.csv
```

Select degraded windows from a scan and run a three-method comparison:

```bash
python3 -m uw_frontend.evaluation.select_degraded_windows \
  --quality-csv logs/aqualoc_harbor07_quality_scan_every10.csv \
  --output-csv logs/aqualoc_harbor07_degraded_windows.csv \
  --min-run 3 \
  --pad 30

START_INDEX=720 END_INDEX=900 TAG=720_900 bash scripts/run_aqualoc_window_compare.sh
```

## Metrics

The CSV includes:

- feature count, added/dropped tracks, track age
- grid coverage
- KLT forward-backward error
- patch NCC
- per-feature quality summary and its residual-weighting proxy
  `sigma_i = sigma_base / sqrt(q_i + eps)`
- underwater image quality terms: texture, blur, exposure, contrast,
  illumination nonuniformity, local contrast/backscatter proxy,
  highlight-shadow ratio, flat-region ratio, grid texture, underwater score,
  and degradation score
- Fundamental/Homography RANSAC inlier ratios
- epipolar and homography residuals
- actual tracker mode/recovery reason plus post-recovery scheduler mode/reason
- geometry mode: `normal`, `degraded_texture`, `planar_near_wall`, or
  `severe_low_texture`
- per-frame runtime

## Paper-Facing Frontend Variants

Two validated configurations are useful for the current paper claims:

- `uw_frontend/configs/continuity_optimized_frontend.yaml`: the frontend output
  used for the continuity claim. KLT keeps long tracks, XFeat handles learned
  recovery/initialization, candidate geometry filtering remains active, and
  classical LK/ORB recovery is allowed to rescue sudden dropout after
  per-candidate filtering.
- `uw_frontend/configs/backend_strict_frontend.yaml` with
  `--measurement-selection`: the backend-ready output used for geometry claims.
  It applies information-aware measurement scoring, post-validation, and refill
  to export a smaller but more geometrically consistent feature set.

Validated compact-window reports:

- continuity and geometry vs baselines:
  `logs/opt_eval/final_relax_v4/final_relax_v4_winloss.md`
- current conservative default:
  `logs/opt_eval/final_compact_v3/final_winloss.md`
- backend strict output:
  `logs/opt_eval/backend_strict_v2/backend_strict_v2_report.md`

Run the continuity-optimized frontend on the compact AFRL-FL window:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/afrl/samples/cemetery_fl_every5_800 \
  --config uw_frontend/configs/continuity_optimized_frontend.yaml \
  --method hybrid_xfeat \
  --start-index 80 \
  --end-index 130 \
  --enable-temporal-health-gate \
  --enable-geometry-safe-recovery \
  --output-csv logs/afrl_fl_080_130_continuity_optimized.csv
```

## Geometry-Aware Reliability Frontend

The current paper-oriented variant is configured in
`uw_frontend/configs/quality_geometry_frontend.yaml`. It adds two pieces on top
of the grid-balanced hybrid frontend:

- geometry-mode scheduling, which separates degraded texture, planar/near-wall,
  and severe low-texture cases;
- calibrated feature reliability, where `q_i` is learned from future track
  survival and then mapped to visual residual sigma.

Generate per-feature pseudo-labels:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/quality_geometry_frontend.yaml \
  --method hybrid_xfeat \
  --start-index 1660 \
  --end-index 1950 \
  --output-csv logs/qgeo_train/aqualoc_harbor07_metrics.csv \
  --reliability-log-csv logs/qgeo_train/aqualoc_harbor07_reliability.csv
```

Train the lightweight calibrator:

```bash
python3 -m uw_frontend.evaluation.train_reliability_calibrator \
  --input-csv logs/qgeo_train/aqualoc_harbor07_reliability.csv \
  --input-csv logs/qgeo_train/aqualoc_harbor06_reliability.csv \
  --input-csv logs/qgeo_train/aqualoc_archaeo06_reliability.csv \
  --output-json logs/qgeo_train/reliability_calibrator_blend1.json \
  --report-md logs/qgeo_train/reliability_calibrator_blend1_report.md \
  --blend 1.0
```

Run calibrated evaluation:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/quality_geometry_frontend.yaml \
  --method hybrid_xfeat \
  --start-index 1660 \
  --end-index 1950 \
  --output-csv logs/qgeo_eval/aqualoc_harbor07_1660_1950_qgeo_calib.csv \
  --reliability-model logs/qgeo_train/reliability_calibrator_blend1.json
```

Evaluate the calibrator on held-out reliability logs:

```bash
python3 -m uw_frontend.evaluation.evaluate_reliability_calibrator \
  --model-json logs/qgeo_train/reliability_calibrator_blend1.json \
  --input-csv logs/qgeo_train/afrl_fl_reliability.csv \
  --input-csv logs/qgeo_train/afrl_fr_reliability.csv \
  --report-md logs/qgeo_eval/reliability_heldout_afrl_report.md
```

For source-specific feature confidence, train exact source models and pass the
track source names at evaluation time:

```bash
python3 -m uw_frontend.evaluation.train_reliability_calibrator \
  --input-csv logs/qgeo_train/aqualoc_harbor07_reliability.csv \
  --input-csv logs/qgeo_train/aqualoc_harbor06_reliability.csv \
  --input-csv logs/qgeo_train/aqualoc_archaeo06_reliability.csv \
  --input-csv logs/qgeo_train/afrl_fl_reliability.csv \
  --output-json logs/source_calib_eval/reliability_calibrator_exact_source.json \
  --report-md logs/source_calib_eval/reliability_calibrator_exact_source_report.md \
  --source-specific \
  --source-grouping exact \
  --min-source-rows 400 \
  --blend 1.0
```

The exact-source model is the recommended `q_i` model for backend weighting.
On held-out AFRL-FR reliability labels it reduced calibrated Brier from `0.2029`
to `0.1751` compared with the earlier coarse source model. Use
`--track-log-csv` to export per-feature `q_i` and visual sigma:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz \
  --image-prefix images_sequence_6 \
  --config uw_frontend/configs/stress_semidense_fallback.yaml \
  --method hybrid_xfeat \
  --semidense-fallback-method xfeat_star \
  --start-index 2210 \
  --end-index 2220 \
  --output-csv logs/backend_export_eval/smoke_metrics.csv \
  --track-log-csv logs/backend_export_eval/smoke_tracks_q_sigma.csv \
  --reliability-model logs/source_calib_eval/reliability_calibrator_exact_source.json
```

The exported track logs can be evaluated without a full VIO backend using the
geometry reliability proxy:

```bash
python3 -m uw_frontend.evaluation.evaluate_track_geometry_reliability \
  --track-log A06_exactq:logs/geometry_reliability_eval/a06_exactq_tracks.csv \
  --track-log A06_xfeat_star_postval:logs/geometry_reliability_eval/a06_xfeat_star_postval_tracks.csv \
  --output-prefix logs/geometry_reliability_eval/postval_geometry_reliability \
  --bins 10
```

This recomputes per-frame Fundamental/Homography RANSAC from exported tracks,
labels each feature as a geometric inlier/outlier, and reports quality-bin
inlier rates and residuals. The current results are in
`logs/geometry_reliability_eval/q_geometry_reliability_report.md` and
`logs/geometry_reliability_eval/postval_geometry_reliability_report.md`.

## Semi-Dense Sparse-Cell Fallback

`uw_frontend/configs/quality_geometry_semidense_fallback.yaml` enables an
optional second matcher for filling uncovered grid cells. The primary learned
matcher can stay sparse XFeat, while the fallback can be XFeat-star or LoFTR:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/afrl/samples/cemetery_fr_every5_800 \
  --config uw_frontend/configs/quality_geometry_semidense_fallback.yaml \
  --method hybrid_xfeat \
  --semidense-fallback-method xfeat_star \
  --start-index 5 \
  --end-index 410 \
  --output-csv logs/semidense_eval/afrl_cemetery_fr_xfeat_star_fallback.csv \
  --reliability-model logs/qgeo_train/reliability_calibrator_blend1.json
```

For stress testing sparse-feature insufficiency, use
`uw_frontend/configs/stress_semidense_fallback.yaml`, which lowers the sparse
frontend capacity and gives the fallback room to fill missing cells:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz \
  --image-prefix images_sequence_6 \
  --config uw_frontend/configs/stress_semidense_fallback.yaml \
  --method hybrid_xfeat \
  --semidense-fallback-method loftr \
  --start-index 2210 \
  --end-index 2310 \
  --output-csv logs/semidense_eval/stress_archaeo06_loftr_2210_2310.csv \
  --reliability-model logs/qgeo_train/reliability_calibrator_blend1.json
```

The current summary is in
`logs/semidense_eval/semidense_fallback_summary.md`.

The gated version logs `semidense_acceptance` in every output CSV. LoFTR is
restricted to planar/severe low-texture sparse-cell recovery, while XFeat-star
is the preferred general semi-dense fallback. The current gated summary is in
`logs/gated_eval/gated_fallback_source_calibration_summary.md`.

The default semi-dense configs now also run candidate-level post-validation
before a fallback point is accepted. Each proposed point must pass quality,
patch NCC, forward-backward error, sparse-cell need, and reference
Fundamental/Homography residual checks; the batch is then accepted only if it
improves grid coverage without degrading geometry. The aligned post-validation
results are in `logs/postval_eval/postval_semidense_table.md`. Current decision:
keep XFeat-star + post-validation as the recommended general sparse-cell
fallback, and keep LoFTR as a restricted planar/extreme-low-texture补点器 rather
than a general fallback.

Temporal track-health gating is implemented behind
`--enable-temporal-health-gate`. It is currently kept as an ablation option, not
as a default: on the tested AFRL-FR/AQUALOC-A06 windows it only slightly reduced
dropout on AFRL-FR and did not improve grid coverage.

## Homography Recovery and Final Ablations

Planar or near-wall recovery is implemented as an optional module behind
`--enable-homography-recovery`. When the geometry scheduler detects
`planar_near_wall`, the frontend estimates a frame-to-frame Homography from
stable tracks, warps recently lost tracks into the current frame, and accepts
them only after patch NCC, forward-backward, Homography residual, distance, and
feature-quality checks:

```bash
python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz \
  --image-prefix images_sequence_6 \
  --config uw_frontend/configs/quality_geometry_frontend.yaml \
  --method hybrid_xfeat \
  --start-index 2210 \
  --end-index 2310 \
  --output-csv logs/planar_eval/a06_homography_recovery.csv \
  --track-log-csv logs/planar_eval/a06_homography_recovery_tracks.csv \
  --reliability-model logs/source_calib_eval/reliability_calibrator_exact_source.json \
  --enable-homography-recovery
```

Current decision: keep Homography recovery as a near-wall/planar ablation and
enable it for Tank/UVVID-style wall experiments, but do not make it a universal
default. The AQUALOC-A06 planar window showed lower dropout and lower median
epipolar error, while AFRL-FR barely triggered the module. Results are in
`logs/planar_eval/homography_recovery_table.md` and
`logs/planar_eval/homography_recovery_geometry_report.md`.

The current component ablation table is in
`logs/component_ablation/a06_component_ablation_table.md`. It separates KLT,
quality triggers, learned recovery, exact-source reliability calibration,
semi-dense post-validation, and Homography recovery. The strongest paper-facing
effect remains the quality-guided hybrid recovery: on AQUALOC-A06, dropout drops
from `24.35` to about `8.40`, and median track age rises from `22` to `45`.

The current local multi-window validation table is in
`logs/local_multirun/local_multirun_exactq_table.md`. It covers AQUALOC Harbor
07, AQUALOC Harbor 06, AQUALOC Archaeo 06, AFRL Cemetery FL, and AFRL Cemetery
FR using the locally available public-data samples. The unified summary of these
remaining points is in `logs/remaining_four_points_summary.md`.

## Current Baselines

- `klt`: Good Features to Track detection with KLT optical flow, forward-backward
  filtering, patch NCC, and persistent track ids.
- `orb`: ORB detection and Hamming matching with persistent ids across
  consecutive descriptor matches.
- `hybrid`: KLT as the normal-frame carrier with relaxed LK and ORB recovery
  triggered by track count, grid coverage, forward-backward health, or
  underwater degradation cues.
- `xfeat`, `xfeat_star`, `superpoint_lightglue`, `loftr`: frame-to-frame
  learned matcher baselines with approximate persistent ids.
- `hybrid_xfeat`, `hybrid_xfeat_star`, `hybrid_superpoint_lightglue`,
  `hybrid_loftr`: quality-aware hybrid variants. In degraded frames, the
  scheduler can try the learned matcher before relaxed LK; otherwise KLT
  remains the carrier.

## Learned Matcher Hooks

The matcher adapters are present but lazy-loaded:

```bash
python3 -m uw_frontend.matchers.check_matchers
```

The current workspace has CPU Torch, Kornia, XFeat, LightGlue, and LoFTR weights
available. The OpenCV-only baselines still do not depend on them.

## Online adaptive dense-KLT pool

The dense KLT stream can run as a hidden candidate pool while the original
VINS feature stream remains the normal input.  Start the candidate producer
from the AQUA-FE workspace:

```bash
python3 -m uw_frontend.ros.dense_klt_candidate_node \
  --camera-config /home/ma/SLAM/VINS-Fusion_3-15-WS/src/config/uwrobot_real/front_cam_20260710_underwater_pinhole.yaml \
  --config uw_frontend/configs/klt_frontend.yaml
```

Remap the original VINS feature-tracker output to
`/feature_tracker/base`, then run the conservative merger:

```bash
python3 -m uw_frontend.ros.adaptive_klt_candidate_pool_node ros
```

The merger publishes `/feature_tracker/feature` for the estimator.  Its default
policy waits 30 seconds, requires three consecutive frames with overlap below
80 and fewer than 40 mature tracks, and also requires weak DVL support.  It
admits at most one new candidate per frame, eight candidates total, within the
existing 180-feature backend cap.  Decisions are published as JSON on
`/aqua_fe/adaptive_klt_decision`.
