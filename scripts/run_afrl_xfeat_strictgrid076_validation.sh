#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
cd "$ROOT"

COMMON_ENV=(
  OMP_NUM_THREADS=2
  MKL_NUM_THREADS=2
  OPENBLAS_NUM_THREADS=2
  RAW_BAG="$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag"
  GT_TXT="$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/cemetery.txt"
  CAMCHAIN="$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_cemetery.yaml"
  IMAGE_SCALE=0.5
  FRONTEND_CONFIG="$ROOT/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml"
  FORMAL_THREE_LAYER_EXPORT=0
  SEMIDENSE_FALLBACK_METHOD=none
  INIT_PARALLAX_GATE=1
  VINS_INIT_KLT_ONLY_FRAMES=20
  LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES=8
  LEARNED_EXPORT_DEGRADATION_GATE=1
  LEARNED_EXPORT_MIN_CLASSICAL_TRACKS=300
  LEARNED_EXPORT_MIN_CLASSICAL_GRID=0.76
  LEARNED_EXPORT_MIN_AGE=2
  LEARNED_EXPORT_MIN_QUALITY=0.08
  LEARNED_EXPORT_MIN_NCC=0.45
  LEARNED_EXPORT_MAX_FB=1.20
  LEARNED_EXPORT_GEOMETRY_GATE=1
  LEARNED_EXPORT_REQUIRE_CONFIRMED=1
  LEARNED_EXPORT_MAX_EPIPOLAR_ERROR=1.2
  LEARNED_EXPORT_MAX_HOMOGRAPHY_ERROR=2.8
  LEARNED_EXPORT_RESIDUAL_MAX_RATIO=1.05
  LEARNED_EXPORT_BENEFIT_GATE=1
  LEARNED_EXPORT_BENEFIT_ALL_SOURCES=1
  LEARNED_EXPORT_MIN_GRID_GAIN=0.0
  LEARNED_EXPORT_MIN_NEW_CELLS=1
  LEARNED_EXPORT_MIN_NEW_CELL_RATIO=0.10
  LEARNED_EXPORT_MAX_PER_NEW_CELL=1
  LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX=2.0
  LEARNED_EXPORT_WEAK_CELL_RESCUE=1
  LEARNED_EXPORT_WEAK_CELL_MAX_COUNT=4
  LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES=1
  LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY=12
  LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX=2.0
  LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID=0.76
  VINS_SAFE_SOURCE_SELECTION=1
  VINS_SAFE_WARMUP_FRAMES=20
  VINS_SAFE_MAX_LEARNED=8
  VINS_SAFE_MIN_LEARNED_AGE=2
  EXPORT_CLASSICAL_MIRROR_BACKBONE=1
  POST_PLAY_SLEEP=8
)

run_klt() {
  local cam_key="$1"
  local topic="$2"
  local start="$3"
  local duration="$4"
  local tag="$5"
  local port="$6"
  env \
    OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    RAW_BAG="$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag" \
    GT_TXT="$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/cemetery.txt" \
    CAMCHAIN="$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_cemetery.yaml" \
    CAMERA_KEY="$cam_key" SRC_IMAGE_TOPIC="$topic" IMAGE_SCALE=0.5 \
    FRONTEND_CONFIG="$ROOT/uw_frontend/configs/klt_frontend.yaml" \
    FORMAL_THREE_LAYER_EXPORT=0 SEMIDENSE_FALLBACK_METHOD=none \
    FORCE_EXPORT=1 TAG="$tag" PORT="$port" POST_PLAY_SLEEP=8 \
    ./scripts/run_afrl_cave_vins_eval.sh external klt "$start" "$duration" 3
}

run_xfeat() {
  local cam_key="$1"
  local topic="$2"
  local start="$3"
  local duration="$4"
  local tag="$5"
  local port="$6"
  env "${COMMON_ENV[@]}" \
    CAMERA_KEY="$cam_key" SRC_IMAGE_TOPIC="$topic" \
    FORCE_EXPORT=1 TAG="$tag" PORT="$port" \
    ./scripts/run_afrl_cave_vins_eval.sh external hybrid_xfeat "$start" "$duration" 3
}

run_klt cam0 /cam_fl/image_raw/compressed 80 30 may19_afrl_fl_80_110_klt_baseline 11960
run_xfeat cam0 /cam_fl/image_raw/compressed 80 30 may19_afrl_fl_80_110_xfeat_strictgrid076 11961
run_klt cam0 /cam_fl/image_raw/compressed 110 30 may19_afrl_fl_110_140_klt_baseline 11962
run_xfeat cam0 /cam_fl/image_raw/compressed 110 30 may19_afrl_fl_110_140_xfeat_strictgrid076 11963
run_klt cam1 /cam_fr/image_raw/compressed 80 30 may19_afrl_fr_80_110_klt_baseline 11964
run_xfeat cam1 /cam_fr/image_raw/compressed 80 30 may19_afrl_fr_80_110_xfeat_strictgrid076 11965

python3 scripts/summarize_run_evidence.py \
  --runs \
  logs/afrl_cave_v31/external_klt_every3_may19_afrl_fl_80_110_klt_baseline \
  logs/afrl_cave_v31/external_hybrid_xfeat_every3_may19_afrl_fl_80_110_xfeat_strictgrid076 \
  logs/afrl_cave_v31/external_klt_every3_may19_afrl_fl_110_140_klt_baseline \
  logs/afrl_cave_v31/external_hybrid_xfeat_every3_may19_afrl_fl_110_140_xfeat_strictgrid076 \
  logs/afrl_cave_v31/external_klt_every3_may19_afrl_fr_80_110_klt_baseline \
  logs/afrl_cave_v31/external_hybrid_xfeat_every3_may19_afrl_fr_80_110_xfeat_strictgrid076 \
  --output-csv logs/may19_afrl_xfeat_strictgrid076_validation.csv
