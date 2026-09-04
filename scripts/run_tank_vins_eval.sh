#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-external}"
METHOD="${2:-klt}"
EVERY_N="${3:-2}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
RAW_BAG="${RAW_BAG:-$ROOT/datasets/full_downloads/tank/short_test/short_test.bag}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/klt_frontend.yaml}"

IMAGE_TOPIC="${IMAGE_TOPIC:-/camera/left/image_dehazed/compressed}"
IMU_TOPIC="${IMU_TOPIC:-/imu/data}"
GT_TOPIC="${GT_TOPIC:-/apriltag_slam/GT}"

TAG="${TAG:-tank_short}"
RUN_DIR="${RUN_DIR:-$ROOT/logs/tank_vins/${MODE}_${METHOD}_every${EVERY_N}_${TAG}}"
CAMERA_CONFIG="$RUN_DIR/tank_left_pinhole.yaml"
VINS_CONFIG="$RUN_DIR/vins_tank_${MODE}.yaml"
FEATURE_BAG="$RUN_DIR/features.bag"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"

PREPROCESS="${PREPROCESS:-adaptive_clahe}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
EXPORT_FEATURES="${EXPORT_FEATURES:-1}"
RUN_VINS="${RUN_VINS:-1}"
PORT="${PORT:-11470}"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
ROSBAG_WAIT_FOR_SUBSCRIBERS="${ROSBAG_WAIT_FOR_SUBSCRIBERS:-0}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}"
FORMAL_THREE_LAYER_EXPORT="${FORMAL_THREE_LAYER_EXPORT:-0}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-150}"
MEASUREMENT_SELECTION_MAX_FEATURES="${MEASUREMENT_SELECTION_MAX_FEATURES:-}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
FRAME_OFFSET="${FRAME_OFFSET:-1}"
SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-none}"
SELECTION_WARMUP_FRAMES="${SELECTION_WARMUP_FRAMES:-0}"
EXPORT_MIN_LEARNED_AGE="${EXPORT_MIN_LEARNED_AGE:-0}"
FEATURE_BAG_OVERRIDE="${FEATURE_BAG_OVERRIDE:-}"
if [[ -n "$FEATURE_BAG_OVERRIDE" ]]; then
  FEATURE_BAG="$FEATURE_BAG_OVERRIDE"
fi

BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}"
BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-0.80}"
BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.85}"
BACKEND_LEARNED_QUALITY_SCALE="${BACKEND_LEARNED_QUALITY_SCALE:-1.0}"
BACKEND_SP_LG_QUALITY_SCALE="${BACKEND_SP_LG_QUALITY_SCALE:-1.0}"
BACKEND_XFEAT_QUALITY_SCALE="${BACKEND_XFEAT_QUALITY_SCALE:-1.0}"
BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-1.0}"
BACKEND_LEARNED_QUALITY_CONST="${BACKEND_LEARNED_QUALITY_CONST:-}"
BACKEND_SP_LG_QUALITY_CONST="${BACKEND_SP_LG_QUALITY_CONST:-}"
BACKEND_XFEAT_QUALITY_CONST="${BACKEND_XFEAT_QUALITY_CONST:-}"
BACKEND_LOFTR_QUALITY_CONST="${BACKEND_LOFTR_QUALITY_CONST:-}"
RAW_QUALITY_TO_BACKEND="${RAW_QUALITY_TO_BACKEND:-0}"
CONSTANT_QUALITY_TO_BACKEND="${CONSTANT_QUALITY_TO_BACKEND:-0}"
VINS_SAFE_SOURCE_SELECTION="${VINS_SAFE_SOURCE_SELECTION:-1}"
VINS_SAFE_WARMUP_FRAMES="${VINS_SAFE_WARMUP_FRAMES:-20}"
VINS_SAFE_MAX_TOTAL="${VINS_SAFE_MAX_TOTAL:-}"
VINS_SAFE_MAX_LEARNED="${VINS_SAFE_MAX_LEARNED:-24}"
VINS_SAFE_MAX_RECOVERED="${VINS_SAFE_MAX_RECOVERED:-16}"
VINS_SAFE_MIN_LEARNED_AGE="${VINS_SAFE_MIN_LEARNED_AGE:-3}"
VINS_SAFE_EXACT_CAP_SELECTION="${VINS_SAFE_EXACT_CAP_SELECTION:-0}"
VINS_SAFE_CLASSICAL_PREFER_KLT="${VINS_SAFE_CLASSICAL_PREFER_KLT:-0}"
VINS_SAFE_CLASSICAL_PREFER_QUALITY="${VINS_SAFE_CLASSICAL_PREFER_QUALITY:-0}"
VINS_SAFE_SIDECAR_LOW_CAP_TOTAL="${VINS_SAFE_SIDECAR_LOW_CAP_TOTAL:-}"
VINS_SAFE_LOW_CAP_HOLD_FRAMES="${VINS_SAFE_LOW_CAP_HOLD_FRAMES:-0}"
EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-0}"
FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE="${FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE:-0}"
FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK="${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-0}"
FORMAL_EXPORT_LEGACY_LOFTR_RESCUE="${FORMAL_EXPORT_LEGACY_LOFTR_RESCUE:-0}"
FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS="${FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS:-0}"
FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR="${FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR:-0}"
MIRROR_MEASUREMENT_SELECTION_POLICY="${MIRROR_MEASUREMENT_SELECTION_POLICY:-baseline}"
INIT_PARALLAX_GATE="${INIT_PARALLAX_GATE:-0}"
INIT_PARALLAX_PROBE_FRAMES="${INIT_PARALLAX_PROBE_FRAMES:-5}"
INIT_PARALLAX_THRESHOLD_PX="${INIT_PARALLAX_THRESHOLD_PX:-7.0}"
INIT_PARALLAX_SKIP_FEATURE_FRAMES="${INIT_PARALLAX_SKIP_FEATURE_FRAMES:-0}"
INIT_PARALLAX_ADAPTIVE_SKIP="${INIT_PARALLAX_ADAPTIVE_SKIP:-0}"
INIT_PARALLAX_ADAPTIVE_SKIP_FRAMES="${INIT_PARALLAX_ADAPTIVE_SKIP_FRAMES:-4}"
INIT_PARALLAX_ADAPTIVE_MIN_PX="${INIT_PARALLAX_ADAPTIVE_MIN_PX:-3.0}"
INIT_PARALLAX_ADAPTIVE_MAX_PX="${INIT_PARALLAX_ADAPTIVE_MAX_PX:-7.0}"
VINS_INIT_KLT_ONLY_FRAMES="${VINS_INIT_KLT_ONLY_FRAMES:-0}"
INIT_LOFTR_SIDECAR_RESCUE="${INIT_LOFTR_SIDECAR_RESCUE:-0}"
INIT_LOFTR_SIDECAR_MAX_COUNT="${INIT_LOFTR_SIDECAR_MAX_COUNT:-6}"
LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES="${LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES:-8}"

LEARNED_EXPORT_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_MIN_CLASSICAL_TRACKS:-300}"
LEARNED_EXPORT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_MIN_CLASSICAL_GRID:-0.84}"
LEARNED_EXPORT_MIN_AGE="${LEARNED_EXPORT_MIN_AGE:-5}"
LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.20}"
LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.58}"
LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-0.90}"
LEARNED_EXPORT_LOFTR_MIN_QUALITY="${LEARNED_EXPORT_LOFTR_MIN_QUALITY:-}"
LEARNED_EXPORT_LOFTR_MIN_AGE="${LEARNED_EXPORT_LOFTR_MIN_AGE:-}"
LEARNED_EXPORT_LOFTR_MIN_NCC="${LEARNED_EXPORT_LOFTR_MIN_NCC:-}"
LEARNED_EXPORT_LOFTR_MAX_FB="${LEARNED_EXPORT_LOFTR_MAX_FB:-}"
LEARNED_EXPORT_MIN_CLASSICAL_AGE="${LEARNED_EXPORT_MIN_CLASSICAL_AGE:-0.0}"
LEARNED_EXPORT_BENEFIT_GATE="${LEARNED_EXPORT_BENEFIT_GATE:-0}"
LEARNED_EXPORT_BENEFIT_ALL_SOURCES="${LEARNED_EXPORT_BENEFIT_ALL_SOURCES:-0}"
LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_TEMPORAL_BURST_GATE="${LEARNED_EXPORT_TEMPORAL_BURST_GATE:-0}"
LEARNED_EXPORT_BURST_WINDOW="${LEARNED_EXPORT_BURST_WINDOW:-12}"
LEARNED_EXPORT_BURST_MIN_RECENT_FRAMES="${LEARNED_EXPORT_BURST_MIN_RECENT_FRAMES:-1}"
LEARNED_EXPORT_BURST_LATE_START_FRAME="${LEARNED_EXPORT_BURST_LATE_START_FRAME:-80}"
LEARNED_EXPORT_BURST_MIN_SIDECARS="${LEARNED_EXPORT_BURST_MIN_SIDECARS:-3}"
LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT="${LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT:-0}"
LEARNED_EXPORT_ALLOW_ISOLATED_NON_LOFTR_SIDECARS="${LEARNED_EXPORT_ALLOW_ISOLATED_NON_LOFTR_SIDECARS:-0}"
LEARNED_EXPORT_ISOLATED_NON_LOFTR_MAX_COUNT="${LEARNED_EXPORT_ISOLATED_NON_LOFTR_MAX_COUNT:-2}"
LEARNED_EXPORT_VISIBLE_TRACK_GATE="${LEARNED_EXPORT_VISIBLE_TRACK_GATE:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES:-3}"
LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP="${LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP:-1}"
LEARNED_EXPORT_VISIBLE_TRACK_MAX_MEAN_STEP_PX="${LEARNED_EXPORT_VISIBLE_TRACK_MAX_MEAN_STEP_PX:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_PER_FRAME="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_PER_FRAME:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MOTION_DEGRADED_ONLY="${LEARNED_EXPORT_VISIBLE_TRACK_MOTION_DEGRADED_ONLY:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MOTION_MIN_FRAME="${LEARNED_EXPORT_VISIBLE_TRACK_MOTION_MIN_FRAME:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_MIN_CLASSICAL_GRID:-0}"
LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION="${LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION:-0}"
LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES="${LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES:-0}"
LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.041}"
LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}"
LEARNED_EXPORT_MIN_NEW_CELL_RATIO="${LEARNED_EXPORT_MIN_NEW_CELL_RATIO:-0.30}"
LEARNED_EXPORT_MAX_PER_NEW_CELL="${LEARNED_EXPORT_MAX_PER_NEW_CELL:-1}"
LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_GEOMETRY_GATE="${LEARNED_EXPORT_GEOMETRY_GATE:-0}"
LEARNED_EXPORT_REQUIRE_CONFIRMED="${LEARNED_EXPORT_REQUIRE_CONFIRMED:-0}"
LEARNED_EXPORT_MAX_EPIPOLAR_ERROR="${LEARNED_EXPORT_MAX_EPIPOLAR_ERROR:-1.20}"
LEARNED_EXPORT_MAX_ESSENTIAL_ERROR="${LEARNED_EXPORT_MAX_ESSENTIAL_ERROR:-0.006}"
LEARNED_EXPORT_MAX_HOMOGRAPHY_ERROR="${LEARNED_EXPORT_MAX_HOMOGRAPHY_ERROR:-2.80}"
LEARNED_EXPORT_RESIDUAL_MAX_RATIO="${LEARNED_EXPORT_RESIDUAL_MAX_RATIO:-1.05}"
LEARNED_EXPORT_RESIDUAL_MAX_EPIPOLAR_ABS="${LEARNED_EXPORT_RESIDUAL_MAX_EPIPOLAR_ABS:-0.03}"
LEARNED_EXPORT_RESIDUAL_MAX_ESSENTIAL_ABS="${LEARNED_EXPORT_RESIDUAL_MAX_ESSENTIAL_ABS:-0.0015}"
LEARNED_EXPORT_RESIDUAL_MAX_HOMOGRAPHY_ABS="${LEARNED_EXPORT_RESIDUAL_MAX_HOMOGRAPHY_ABS:-0.12}"
LEARNED_EXPORT_GEOMETRY_MIN_REFERENCE_TRACKS="${LEARNED_EXPORT_GEOMETRY_MIN_REFERENCE_TRACKS:-16}"
LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY="${LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY:-0}"
LEARNED_EXPORT_LOFTR_PLANAR_RESCUE="${LEARNED_EXPORT_LOFTR_PLANAR_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT:-3}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES:-3}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID:-0.92}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX:-2.0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT:-0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY:-48}"
LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX:-}"
LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX:-}"
LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT="${LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT:-0}"
LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES="${LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES:-0}"
LEARNED_EXPORT_WEAK_CELL_RESCUE="${LEARNED_EXPORT_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_WEAK_CELL_MAX_COUNT:-2}"
LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES:-5}"
LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY:-8}"
LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX:-3.0}"
LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID:-0.82}"
LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE="${LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE:-0}"
LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE:-26}"
LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX:-10.5}"
LEARNED_EXPORT_MATURE_CELL_RESCUE="${LEARNED_EXPORT_MATURE_CELL_RESCUE:-0}"
LEARNED_EXPORT_MATURE_CELL_MAX_COUNT="${LEARNED_EXPORT_MATURE_CELL_MAX_COUNT:-6}"
LEARNED_EXPORT_MATURE_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_MATURE_CELL_MIN_CANDIDATES:-4}"
LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_AGE="${LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_AGE:-10.0}"
LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_MOTION_PX:-3.0}"
LEARNED_EXPORT_MATURE_CELL_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_MATURE_CELL_MAX_CLASSICAL_GRID:-0.84}"
LEARNED_EXPORT_MATURE_CELL_MAX_PER_CELL="${LEARNED_EXPORT_MATURE_CELL_MAX_PER_CELL:-2}"
LEARNED_EXPORT_MATURE_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_MATURE_CELL_MAX_OCCUPANCY:-8}"
LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX:-0.0}"

VINS_MULTIPLE_THREAD="${VINS_MULTIPLE_THREAD:-0}"
VINS_MAX_CNT="${VINS_MAX_CNT:-150}"
VINS_MIN_DIST="${VINS_MIN_DIST:-20}"
VINS_FREQ="${VINS_FREQ:-20}"
VINS_F_THRESHOLD="${VINS_F_THRESHOLD:-1.0}"
VINS_EQUALIZE="${VINS_EQUALIZE:-1}"
VINS_KEYFRAME_PARALLAX="${VINS_KEYFRAME_PARALLAX:-10.0}"
VINS_MAX_SOLVER_TIME="${VINS_MAX_SOLVER_TIME:-0.04}"
VINS_MAX_NUM_ITERATIONS="${VINS_MAX_NUM_ITERATIONS:-8}"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ ! -f "$RAW_BAG" ]]; then
  echo "missing RAW_BAG: $RAW_BAG" >&2
  exit 2
fi

python3 - "$CAMERA_CONFIG" "$VINS_CONFIG" "$VINS_OUTPUT" "$MODE" \
  "$IMU_TOPIC" "$VINS_MULTIPLE_THREAD" "$VINS_MAX_CNT" "$VINS_MIN_DIST" \
  "$VINS_FREQ" "$VINS_F_THRESHOLD" "$VINS_EQUALIZE" "$VINS_KEYFRAME_PARALLAX" \
  "$VINS_MAX_SOLVER_TIME" "$VINS_MAX_NUM_ITERATIONS" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

camera_config = Path(sys.argv[1])
vins_config = Path(sys.argv[2])
vins_output = Path(sys.argv[3])
mode = sys.argv[4]
imu_topic = sys.argv[5]
multiple_thread = int(sys.argv[6])
max_cnt = int(sys.argv[7])
min_dist = int(sys.argv[8])
freq = int(sys.argv[9])
f_threshold = float(sys.argv[10])
equalize = int(sys.argv[11])
keyframe_parallax = float(sys.argv[12])
max_solver_time = float(sys.argv[13])
max_num_iterations = int(sys.argv[14])

camera_config.parent.mkdir(parents=True, exist_ok=True)
vins_output.mkdir(parents=True, exist_ok=True)
camera_config.write_text(
    "%YAML:1.0\n"
    "---\n"
    "model_type: PINHOLE\n"
    "camera_name: tank_left\n"
    "image_width: 612\n"
    "image_height: 512\n"
    "distortion_parameters:\n"
    "   k1: 0.0\n"
    "   k2: 0.0\n"
    "   p1: 0.0\n"
    "   p2: 0.0\n"
    "projection_parameters:\n"
    "   fx: 655.0\n"
    "   fy: 655.0\n"
    "   cx: 306.0\n"
    "   cy: 256.0\n",
    encoding="utf-8",
)

body_t_cam = [
    -0.0165, -0.0175, -0.9997, -0.211687435,
    -0.0106,  0.9998, -0.0173, -0.097259169,
     0.9998,  0.0103, -0.0167, -0.056238089,
     0.0,     0.0,     0.0,     1.0,
]
data = ", ".join(f"{v:.12g}" for v in body_t_cam)
vins_image_topic = "/unused/image" if mode == "external" else "/camera/left/image_dehazed"
vins_config.write_text(
    "%YAML:1.0\n\n"
    "imu: 1\n"
    "num_of_cam: 1\n"
    f"multiple_thread: {multiple_thread}\n\n"
    f"imu_topic: \"{imu_topic}\"\n"
    f"image0_topic: \"{vins_image_topic}\"\n"
    "image1_topic: \"\"\n"
    f"output_path: \"{vins_output}\"\n\n"
    "image_width: 612\n"
    "image_height: 512\n"
    f"cam0_calib: \"{camera_config.name}\"\n\n"
    "estimate_extrinsic: 0\n"
    "body_T_cam0: !!opencv-matrix\n"
    "   rows: 4\n"
    "   cols: 4\n"
    "   dt: d\n"
    f"   data: [{data}]\n\n"
    f"max_cnt: {max_cnt}\n"
    f"min_dist: {min_dist}\n"
    f"freq: {freq}\n"
    f"F_threshold: {f_threshold:.17g}\n"
    "show_track: 0\n"
    "flow_back: 1\n"
    f"equalize: {equalize}\n\n"
    f"max_solver_time: {max_solver_time:.17g}\n"
    f"max_num_iterations: {max_num_iterations}\n"
    f"keyframe_parallax: {keyframe_parallax:.17g}\n\n"
    "acc_n: 0.02\n"
    "gyr_n: 0.001\n"
    "acc_w: 0.001\n"
    "gyr_w: 0.00005\n"
    "g_norm: 9.8100\n\n"
    "loop_closure: 0\n"
    "td: 0.0\n"
    "estimate_td: 0\n"
    "rolling_shutter: 0\n",
    encoding="utf-8",
)
print(f"camera_config={camera_config}")
print(f"vins_config={vins_config}")
PY

if [[ "$MODE" == "external" ]]; then
  if [[ "$FORCE_EXPORT" == "1" ]]; then
    rm -f "$FEATURE_BAG"
  fi
  if [[ "$EXPORT_FEATURES" == "1" && ! -f "$FEATURE_BAG" ]]; then
    EXPORT_ARGS=(
      --bag "$RAW_BAG"
      --image-topic "$IMAGE_TOPIC"
      --camera-config "$CAMERA_CONFIG"
      --output-bag "$FEATURE_BAG"
      --config "$FRONTEND_CONFIG"
      --method "$METHOD"
      --semidense-fallback-method "$SEMIDENSE_FALLBACK_METHOD"
      --every-n "$EVERY_N"
      --frame-offset "$FRAME_OFFSET"
      --export-max-features "$EXPORT_MAX_FEATURES"
      --export-min-age "$EXPORT_MIN_AGE"
      --preprocess "$PREPROCESS"
      --selection-warmup-frames "$SELECTION_WARMUP_FRAMES"
      --export-min-learned-age "$EXPORT_MIN_LEARNED_AGE"
      --timestamp-source header
      --max-header-stamp-delta 0.25
      --invalid-header-policy skip
      --copy-topic "$IMU_TOPIC"
      --copy-topic "$GT_TOPIC"
      --metrics-csv "$RUN_DIR/frontend_metrics.csv"
    )
    if [[ -n "$MEASUREMENT_SELECTION_MAX_FEATURES" ]]; then
      EXPORT_ARGS+=(--measurement-selection-max-features "$MEASUREMENT_SELECTION_MAX_FEATURES")
    fi
    if [[ "$PROCESS_SKIPPED_FRAMES" == "1" ]]; then
      EXPORT_ARGS+=(--process-skipped-frames)
    fi
    if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
      EXPORT_ARGS+=(--measurement-selection)
    fi
    if [[ "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(--formal-three-layer-export)
    fi
    if [[ "$FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-allow-sparse-backbone)
    fi
    if [[ "$FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-adaptive-mirror-fallback)
    fi
    if [[ "$FORMAL_EXPORT_LEGACY_LOFTR_RESCUE" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-legacy-loftr-rescue)
    fi
    if [[ "$FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-allow-low-parallax-sidecars)
    fi
    if [[ "$FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-low-texture-active-sidecar)
    fi
    if [[ -n "$BACKEND_QUALITY_MODE" ]]; then
      EXPORT_ARGS+=(--backend-quality-mode "$BACKEND_QUALITY_MODE")
    fi
    if [[ -n "$BACKEND_QUALITY_ALPHA" ]]; then
      EXPORT_ARGS+=(--backend-quality-alpha "$BACKEND_QUALITY_ALPHA")
    fi
    if [[ -n "$BACKEND_QUALITY_FLOOR" && "$BACKEND_QUALITY_FLOOR" != "none" ]]; then
      EXPORT_ARGS+=(--backend-quality-floor "$BACKEND_QUALITY_FLOOR")
    fi
    EXPORT_ARGS+=(
      --backend-learned-quality-scale "$BACKEND_LEARNED_QUALITY_SCALE"
      --backend-sp-lg-quality-scale "$BACKEND_SP_LG_QUALITY_SCALE"
      --backend-xfeat-quality-scale "$BACKEND_XFEAT_QUALITY_SCALE"
      --backend-loftr-quality-scale "$BACKEND_LOFTR_QUALITY_SCALE"
    )
    if [[ -n "$BACKEND_LEARNED_QUALITY_CONST" ]]; then
      EXPORT_ARGS+=(--backend-learned-quality-const "$BACKEND_LEARNED_QUALITY_CONST")
    fi
    if [[ -n "$BACKEND_SP_LG_QUALITY_CONST" ]]; then
      EXPORT_ARGS+=(--backend-sp-lg-quality-const "$BACKEND_SP_LG_QUALITY_CONST")
    fi
    if [[ -n "$BACKEND_XFEAT_QUALITY_CONST" ]]; then
      EXPORT_ARGS+=(--backend-xfeat-quality-const "$BACKEND_XFEAT_QUALITY_CONST")
    fi
    if [[ -n "$BACKEND_LOFTR_QUALITY_CONST" ]]; then
      EXPORT_ARGS+=(--backend-loftr-quality-const "$BACKEND_LOFTR_QUALITY_CONST")
    fi
    if [[ "$RAW_QUALITY_TO_BACKEND" == "1" ]]; then
      EXPORT_ARGS+=(--raw-quality-to-backend)
    fi
    if [[ "$CONSTANT_QUALITY_TO_BACKEND" == "1" ]]; then
      EXPORT_ARGS+=(--constant-quality-to-backend)
    fi
    if [[ "$VINS_SAFE_SOURCE_SELECTION" == "1" ]]; then
      EXPORT_ARGS+=(
        --vins-safe-source-selection
        --vins-safe-warmup-frames "$VINS_SAFE_WARMUP_FRAMES"
        --vins-safe-max-learned "$VINS_SAFE_MAX_LEARNED"
        --vins-safe-max-recovered "$VINS_SAFE_MAX_RECOVERED"
        --vins-safe-min-learned-age "$VINS_SAFE_MIN_LEARNED_AGE"
      )
      if [[ "$VINS_SAFE_CLASSICAL_PREFER_QUALITY" == "1" ]]; then
        EXPORT_ARGS+=(--vins-safe-classical-prefer-quality)
      fi
      if [[ "$VINS_SAFE_CLASSICAL_PREFER_KLT" == "1" ]]; then
        EXPORT_ARGS+=(--vins-safe-classical-prefer-klt)
      fi
      if [[ "$VINS_SAFE_EXACT_CAP_SELECTION" == "1" ]]; then
        EXPORT_ARGS+=(--vins-safe-exact-cap-selection)
      fi
      if [[ -n "$VINS_SAFE_MAX_TOTAL" ]]; then
        EXPORT_ARGS+=(--vins-safe-max-total "$VINS_SAFE_MAX_TOTAL")
      fi
      if [[ -n "$VINS_SAFE_SIDECAR_LOW_CAP_TOTAL" ]]; then
        EXPORT_ARGS+=(--vins-safe-sidecar-low-cap-total "$VINS_SAFE_SIDECAR_LOW_CAP_TOTAL")
      fi
      if [[ "$VINS_SAFE_LOW_CAP_HOLD_FRAMES" != "0" ]]; then
        EXPORT_ARGS+=(--vins-safe-low-cap-hold-frames "$VINS_SAFE_LOW_CAP_HOLD_FRAMES")
      fi
    fi
    if [[ "$INIT_PARALLAX_GATE" == "1" ]]; then
      EXPORT_ARGS+=(
        --init-parallax-gate
        --init-parallax-probe-frames "$INIT_PARALLAX_PROBE_FRAMES"
        --init-parallax-threshold-px "$INIT_PARALLAX_THRESHOLD_PX"
        --init-parallax-skip-feature-frames "$INIT_PARALLAX_SKIP_FEATURE_FRAMES"
      )
      if [[ "$INIT_PARALLAX_ADAPTIVE_SKIP" == "1" ]]; then
        EXPORT_ARGS+=(
          --init-parallax-adaptive-skip
          --init-parallax-adaptive-skip-frames "$INIT_PARALLAX_ADAPTIVE_SKIP_FRAMES"
          --init-parallax-adaptive-min-px "$INIT_PARALLAX_ADAPTIVE_MIN_PX"
          --init-parallax-adaptive-max-px "$INIT_PARALLAX_ADAPTIVE_MAX_PX"
        )
      fi
    fi
    if [[ "$VINS_INIT_KLT_ONLY_FRAMES" != "0" ]]; then
      EXPORT_ARGS+=(--vins-init-klt-only-frames "$VINS_INIT_KLT_ONLY_FRAMES")
    fi
    if [[ "$INIT_LOFTR_SIDECAR_RESCUE" == "1" ]]; then
      EXPORT_ARGS+=(
        --init-loftr-sidecar-rescue
        --init-loftr-sidecar-max-count "$INIT_LOFTR_SIDECAR_MAX_COUNT"
      )
    fi
    EXPORT_ARGS+=(--low-parallax-learned-holdoff-frames "$LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES")
    if [[ "$LEARNED_EXPORT_GEOMETRY_GATE" == "1" || "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-degradation-gate
        --learned-export-min-classical-tracks "$LEARNED_EXPORT_MIN_CLASSICAL_TRACKS"
        --learned-export-min-classical-grid "$LEARNED_EXPORT_MIN_CLASSICAL_GRID"
        --learned-export-min-age "$LEARNED_EXPORT_MIN_AGE"
        --learned-export-min-quality "$LEARNED_EXPORT_MIN_QUALITY"
        --learned-export-min-ncc "$LEARNED_EXPORT_MIN_NCC"
        --learned-export-max-fb "$LEARNED_EXPORT_MAX_FB"
        --learned-export-min-classical-age "$LEARNED_EXPORT_MIN_CLASSICAL_AGE"
      )
      if [[ -n "$LEARNED_EXPORT_LOFTR_MIN_QUALITY" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-min-quality "$LEARNED_EXPORT_LOFTR_MIN_QUALITY")
      fi
      if [[ -n "$LEARNED_EXPORT_LOFTR_MIN_AGE" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-min-age "$LEARNED_EXPORT_LOFTR_MIN_AGE")
      fi
      if [[ -n "$LEARNED_EXPORT_LOFTR_MIN_NCC" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-min-ncc "$LEARNED_EXPORT_LOFTR_MIN_NCC")
      fi
      if [[ -n "$LEARNED_EXPORT_LOFTR_MAX_FB" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-max-fb "$LEARNED_EXPORT_LOFTR_MAX_FB")
      fi
    fi
    if [[ "$LEARNED_EXPORT_BENEFIT_GATE" == "1" || "$LEARNED_EXPORT_BENEFIT_ALL_SOURCES" == "1" || "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-benefit-gate
        --learned-export-min-grid-gain "$LEARNED_EXPORT_MIN_GRID_GAIN"
        --learned-export-min-new-cells "$LEARNED_EXPORT_MIN_NEW_CELLS"
        --learned-export-min-new-cell-ratio "$LEARNED_EXPORT_MIN_NEW_CELL_RATIO"
        --learned-export-max-per-new-cell "$LEARNED_EXPORT_MAX_PER_NEW_CELL"
        --learned-export-coverage-gain-max-classical-tracks "$LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS"
        --learned-export-min-classical-motion-px "$LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX"
        --learned-export-sidecar-max-observations "$LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS"
        --learned-export-low-parallax-sidecar-max-observations "$LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS"
      )
      if [[ "$LEARNED_EXPORT_BENEFIT_ALL_SOURCES" == "1" ]]; then
        EXPORT_ARGS+=(--learned-export-benefit-all-sources)
      fi
      if [[ "$LEARNED_EXPORT_WEAK_CELL_RESCUE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-weak-cell-rescue
          --learned-export-weak-cell-max-count "$LEARNED_EXPORT_WEAK_CELL_MAX_COUNT"
          --learned-export-weak-cell-min-candidates "$LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES"
          --learned-export-weak-cell-max-occupancy "$LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY"
          --learned-export-weak-cell-min-classical-motion-px "$LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX"
          --learned-export-weak-cell-max-classical-grid "$LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID"
          --learned-export-weak-cell-max-classical-tracks "$LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS"
        )
      fi
      if [[ "$LEARNED_EXPORT_MATURE_CELL_RESCUE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-mature-cell-rescue
          --learned-export-mature-cell-max-count "$LEARNED_EXPORT_MATURE_CELL_MAX_COUNT"
          --learned-export-mature-cell-min-candidates "$LEARNED_EXPORT_MATURE_CELL_MIN_CANDIDATES"
          --learned-export-mature-cell-min-classical-age "$LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_AGE"
          --learned-export-mature-cell-min-classical-motion-px "$LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_MOTION_PX"
          --learned-export-mature-cell-max-classical-grid "$LEARNED_EXPORT_MATURE_CELL_MAX_CLASSICAL_GRID"
          --learned-export-mature-cell-max-per-cell "$LEARNED_EXPORT_MATURE_CELL_MAX_PER_CELL"
          --learned-export-mature-cell-max-occupancy "$LEARNED_EXPORT_MATURE_CELL_MAX_OCCUPANCY"
        )
      fi
      if [[ "$LEARNED_EXPORT_LOFTR_PLANAR_RESCUE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-loftr-planar-rescue
          --learned-export-loftr-planar-max-count "$LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT"
          --learned-export-loftr-planar-min-candidates "$LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES"
          --learned-export-loftr-planar-max-classical-grid "$LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID"
          --learned-export-loftr-planar-min-classical-motion-px "$LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX"
          --learned-export-loftr-rescue-max-classical-tracks "$LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS"
        )
      fi
      if [[ "$LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-loftr-weak-cell-rescue
          --learned-export-loftr-weak-cell-max-count "$LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT"
          --learned-export-loftr-weak-cell-max-occupancy "$LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY"
          --learned-export-loftr-rescue-max-classical-tracks "$LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS"
        )
        if [[ -n "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX" ]]; then
          EXPORT_ARGS+=(
            --learned-export-loftr-support-max-init-parallax-px \
            "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX"
          )
        fi
        if [[ -n "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX" ]]; then
          EXPORT_ARGS+=(
            --learned-export-loftr-support-max-classical-motion-px \
            "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX"
          )
        fi
      fi
      if [[ "$LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-coverage-seeded-continuation-gate
          --learned-export-continuation-max-classical-age "$LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE"
          --learned-export-continuation-max-classical-motion-px "$LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX"
        )
      fi
      if [[ "$LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT" != "0" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-min-export-count "$LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT")
      fi
      if [[ "$LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES" != "0" ]]; then
        EXPORT_ARGS+=(
          --learned-export-loftr-support-cooldown-frames \
          "$LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES"
        )
      fi
    fi
    if [[ "$LEARNED_EXPORT_GEOMETRY_GATE" == "1" || "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-geometry-gate
        --learned-export-max-epipolar-error "$LEARNED_EXPORT_MAX_EPIPOLAR_ERROR"
        --learned-export-max-essential-error "$LEARNED_EXPORT_MAX_ESSENTIAL_ERROR"
        --learned-export-max-homography-error "$LEARNED_EXPORT_MAX_HOMOGRAPHY_ERROR"
        --learned-export-residual-max-ratio "$LEARNED_EXPORT_RESIDUAL_MAX_RATIO"
        --learned-export-residual-max-epipolar-abs "$LEARNED_EXPORT_RESIDUAL_MAX_EPIPOLAR_ABS"
        --learned-export-residual-max-essential-abs "$LEARNED_EXPORT_RESIDUAL_MAX_ESSENTIAL_ABS"
        --learned-export-residual-max-homography-abs "$LEARNED_EXPORT_RESIDUAL_MAX_HOMOGRAPHY_ABS"
        --learned-export-geometry-min-reference-tracks "$LEARNED_EXPORT_GEOMETRY_MIN_REFERENCE_TRACKS"
      )
    fi
    if [[ "$LEARNED_EXPORT_REQUIRE_CONFIRMED" == "1" || "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-require-confirmed)
    fi
    if [[ "$LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-loftr-requires-homography)
    fi
    if [[ "$LEARNED_EXPORT_TEMPORAL_BURST_GATE" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-temporal-burst-gate
        --learned-export-burst-window "$LEARNED_EXPORT_BURST_WINDOW"
        --learned-export-burst-min-recent-frames "$LEARNED_EXPORT_BURST_MIN_RECENT_FRAMES"
        --learned-export-burst-late-start-frame "$LEARNED_EXPORT_BURST_LATE_START_FRAME"
        --learned-export-burst-min-sidecars "$LEARNED_EXPORT_BURST_MIN_SIDECARS"
      )
    fi
    if [[ "$LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-allow-early-loftr-support)
    fi
    if [[ "$LEARNED_EXPORT_ALLOW_ISOLATED_NON_LOFTR_SIDECARS" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-allow-isolated-non-loftr-sidecars
        --learned-export-isolated-non-loftr-max-count "$LEARNED_EXPORT_ISOLATED_NON_LOFTR_MAX_COUNT"
      )
    fi
    if [[ "$LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-require-fresh-non-loftr-confirmation
        --learned-export-fresh-confirmation-hold-frames "$LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES"
      )
    fi
    if [[ "$LEARNED_EXPORT_VISIBLE_TRACK_GATE" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-visible-track-gate
        --learned-export-visible-track-min-frames "$LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES"
        --learned-export-visible-track-max-gap "$LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP"
        --learned-export-visible-track-max-mean-step-px "$LEARNED_EXPORT_VISIBLE_TRACK_MAX_MEAN_STEP_PX"
        --learned-export-visible-track-min-count-per-frame "$LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_PER_FRAME"
        --learned-export-visible-track-motion-min-frame "$LEARNED_EXPORT_VISIBLE_TRACK_MOTION_MIN_FRAME"
        --learned-export-visible-track-min-count-min-classical-grid "$LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_MIN_CLASSICAL_GRID"
      )
      if [[ "$LEARNED_EXPORT_VISIBLE_TRACK_MOTION_DEGRADED_ONLY" == "1" ]]; then
        EXPORT_ARGS+=(--learned-export-visible-track-motion-degraded-only)
      fi
    fi
    if [[ "$EXPORT_CLASSICAL_MIRROR_BACKBONE" == "1" ]]; then
      EXPORT_ARGS+=(--export-classical-mirror-backbone)
    fi
    EXPORT_ARGS+=(--mirror-measurement-selection-policy "$MIRROR_MEASUREMENT_SELECTION_POLICY")
    python3 -m uw_frontend.ros.export_vins_features "${EXPORT_ARGS[@]}"
  fi
fi

if [[ "$MODE" == "external" && -n "$FEATURE_BAG_OVERRIDE" ]]; then
  SOURCE_METRICS="$(dirname "$FEATURE_BAG_OVERRIDE")/frontend_metrics.csv"
  if [[ -f "$SOURCE_METRICS" && ! -f "$RUN_DIR/frontend_metrics.csv" ]]; then
    cp "$SOURCE_METRICS" "$RUN_DIR/frontend_metrics.csv"
  fi
fi

PLAY_BAG="$RAW_BAG"
if [[ "$MODE" == "external" ]]; then
  PLAY_BAG="$FEATURE_BAG"
fi

if [[ "$RUN_VINS" == "1" ]]; then
  source "$VINS_WS/devel/setup.bash"
  rm -f "$VINS_OUTPUT/vio.csv" "$VINS_LOG" "$APE_REPORT"

  export ROS_MASTER_URI="http://localhost:$PORT"
  export ROS_HOSTNAME=localhost
  roscore -p "$PORT" > "$RUN_DIR/roscore.log" 2>&1 &
  ROSCORE_PID=$!
  VINS_PID=""
  cleanup() {
    if [[ -n "${VINS_PID:-}" ]]; then
      kill "$VINS_PID" 2>/dev/null || true
      wait "$VINS_PID" 2>/dev/null || true
    fi
    kill "$ROSCORE_PID" 2>/dev/null || true
    wait "$ROSCORE_PID" 2>/dev/null || true
  }
  trap cleanup EXIT

  sleep 3
  rosparam set /use_sim_time true
  bash "$ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"
  rosrun vins vins_node "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
  VINS_PID=$!
  sleep 4
  PLAY_ARGS=("$PLAY_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet)
  if [[ "$ROSBAG_WAIT_FOR_SUBSCRIBERS" == "1" ]]; then
    PLAY_ARGS+=(--wait-for-subscribers)
  fi
  rosbag play "${PLAY_ARGS[@]}"
  sleep "$POST_PLAY_SLEEP"

  python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
    --vins-csv "$VINS_OUTPUT/vio.csv" \
    --bag "$PLAY_BAG" \
    --gt-topic "$GT_TOPIC" \
    --vins-log "$VINS_LOG" | tee "$APE_REPORT"
fi

{
  echo "run_dir=$RUN_DIR"
  echo "play_bag=$PLAY_BAG"
  echo "feature_bag=$FEATURE_BAG"
} | tee "$RUN_DIR/replay_manifest.txt"
