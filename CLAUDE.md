# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this workspace is

`AQUA-FE_WS` is the **frontend-only** research workspace for a paper on a quality-guided underwater VO/VIO frontend. The Python package `uw_frontend/` is the research code; `scripts/` contains the experiment runners and report generators; `papers/frontend_baseline_protocol.md` defines the paper's baseline/proposed/ablation taxonomy and acceptance criteria; `logs/`, `datasets/`, and `external_tools/` are symlinks into `/mnt/data/AQUA-FE_WS/`.

The closed-loop VINS-Fusion backend lives in a **separate** workspace at `/home/ma/SLAM/VINS-Fusion_3-15-WS` (see user memory). This workspace produces feature bags / config YAMLs that are consumed by that backend; do not assume VINS-Fusion source is editable from here.

This directory is not a standalone git repo — `git rev-parse --show-toplevel` returns `/`. The git status seen at session start reflects the host filesystem, not project state.

## Running things

The package has no `setup.py` / `pyproject.toml`. Always invoke from the workspace root so `uw_frontend` is importable:

```bash
cd /home/ma/AQUA-FE_WS
python3 -m uw_frontend.evaluation.run_frontend_eval --input ... --config uw_frontend/configs/<name>.yaml --method <method> --output-csv logs/...
```

`uw_frontend/README.md` has canonical command recipes for the standard sequences (AQUALOC Harbor07 / Archaeo06, AFRL-FL/FR). Use those exact forms rather than improvising flags.

End-to-end VINS scripts (`scripts/run_*_vins_eval.sh`) `source /opt/ros/noetic/setup.bash` and then `source $VINS_WS/devel/setup.bash` (default `VINS_WS=/home/ma/SLAM/VINS-Fusion-origin`). They drive `rosbag play` + `rosrun vins vins_node` and evaluate APE/RPE with `evo`. Required external inputs (raw bag, COLMAP GT txt, camchain, IMU yaml) live under `datasets/full_downloads/`.

Tests: there is no pytest suite. Validation is empirical — frontend metrics CSVs + summary markdown under `logs/<experiment>/`.

## Architecture

The evaluation pipeline composes one tracker, one scheduler, and (optionally) one or two learned matchers per frame:

1. **Image source** — `uw_frontend/datasets/image_sequence.py` streams frames from a directory, tar/tar.gz, or rosbag-exported folder. All entrypoints consume `ImageSequence`.

2. **Tracker** — one of:
   - `KltTracker` (GFTT + KLT + forward-backward + patch NCC, persistent track ids)
   - `OrbTracker` (ORB + Hamming match, persistent ids)
   - `PairwiseMatcherTracker` (wraps any `BaseMatcher` with approximate persistent ids)
   - `HybridKltOrbTracker` — **the only tracker used in paper-facing variants.** KLT is always the backbone; relaxed-LK, ORB, and an optional `learned_matcher` (XFeat / SP+LG / LoFTR) are *recovery layers* gated by the scheduler. An optional `semidense_fallback_matcher` fills sparse grid cells.

3. **Scheduler** — `uw_frontend/scheduler/hybrid_scheduler.py` (`HybridScheduler` / `SchedulerConfig`). Reads `ImageQuality`, `GridStats`, `GeometryStats`, and `TrackerDiagnostics`; emits a `SchedulerDecision` with a `geometry_mode` ∈ {`normal`, `degraded_texture`, `planar_near_wall`, `severe_low_texture`}. The tracker reads this to decide whether and *which* recovery layer to invoke.

4. **Reliability calibrator** — `uw_frontend/quality/feature_confidence.py`. `ReliabilityCalibrator` is trained offline from per-feature `RELIABILITY_FEATURE_NAMES` (in `uw_frontend/quality/reliability_features.py`) against future-survival labels. At eval time it maps features to `q_i`, and `quality_to_sigma` produces a visual-residual `sigma_i = sigma_base / sqrt(q_i + eps)` that the backend can consume.

5. **Measurement selection** — `uw_frontend/evaluation/measurement_selection.py` (`select_backend_measurements`) is the optional backend-ready post-filter: it scores by geometry + quality, then exports a smaller, more geometrically consistent set. Enabled by `--measurement-selection` or `measurement_selection.enabled` in the config.

6. **Metrics + outputs** — `uw_frontend/evaluation/frontend_metrics.py` emits the per-frame row schema documented in `uw_frontend/README.md` ("Metrics"). Optional sidecar CSVs:
   - `--reliability-log-csv` — per-feature features+labels for training the calibrator
   - `--track-log-csv` — per-frame per-track export with `q_i` / `visual_sigma` for backend integration
   - `--save-viz-dir` — overlay images every N frames

7. **VINS export path** — `uw_frontend/ros/export_vins_features.py` (large, ~4k lines). Runs the same frontend stack but emits a rosbag of `sensor_msgs/PointCloud` features compatible with VINS-Fusion's external-feature interface. The export gate enforces the paper's "KLT-backbone, learned sidecar" policy. **Do not edit the export logic to make a metric pass** — the gates encode prior negative results (see `configs/README_recommended.md`).

### Config system

YAML configs in `uw_frontend/configs/*.yaml` set per-component dataclass fields (`klt`, `orb`, `hybrid`, `pairwise`, `xfeat`, `lightglue`, `loftr`, `grid`, `scheduler`, `measurement_selection`). `load_config` in `run_frontend_eval.py` supports `extends: [parent.yaml, ...]` for layered configs. CLI flags like `--enable-temporal-health-gate`, `--enable-homography-recovery`, `--enable-geometry-safe-recovery` override the matching `HybridConfig` field.

`uw_frontend/configs/ablations/` and `uw_frontend/configs/experiments/` hold per-experiment variants — see `uw_frontend/configs/README_recommended.md` for which configs are paper-default vs. probes-only. Treat that file as authoritative for default selection.

### Method naming convention

A method name like `hybrid_xfeat_star` means: hybrid (KLT backbone + relaxed-LK/ORB recovery) **with** XFeat-star as the learned recovery/initialization layer. `xfeat_star` alone is the pairwise-only baseline (no temporal carrier). Pairwise-only baselines are for matching-quality comparison, not for closed-loop VIO.

## Paper-specific conventions

- The paper has two claims and they require **different evidence**: a normal-texture no-harm claim (AQUALOC Harbor07-style windows) and a low-texture/planar improvement claim (AQUALOC Archaeo06, AFRL-FL/FR, UVVID, Tank). See `papers/frontend_baseline_protocol.md` for the dataset/window split and acceptance criteria. AQUALOC Harbor07 alone is **not** evidence for the low-texture claim.
- "Baseline", "proposed variant", and "ablation" are distinct table categories. Do not promote an ablation into the baseline table.
- LoFTR is treated as an **extreme-only planar low-texture sparse-cell refiller**, not a general matcher. Default profiles gate it hard; broad LoFTR replacement / flooding has been validated as harmful and rejected (see `configs/README_recommended.md` "LoFTR Export Safety Notes"). Don't reintroduce it as a default without new evidence.
- Outputs land under `logs/<experiment>/`. Summary reports are markdown next to the CSVs and are the canonical "did it work" artifacts — when reporting on a run, point at the report MD, not raw CSV rows.

## User context

User is an underwater SLAM researcher writing the paper for which this is the frontend half. Replies in Chinese, wants decisive honest advice, paper-oriented framing.
