#!/usr/bin/env bash
set -euo pipefail

# CIRS Girona Cala Viuda VINS wrapper.
#
# Usage:
#   RUN_VINS=0 bash scripts/run_cirs_caves_vins_eval.sh external START_OFFSET DURATION METHOD EVERY_N

MODE="${1:-external}"
START_OFFSET="${2:-0.0}"
DURATION="${3:-20.0}"
METHOD="${4:-hybrid_xfeat}"
EVERY_N="${5:-2}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
CIRS_ROOT="${CIRS_ROOT:-/mnt/data/AQUA-FE_WS/datasets/full_downloads/cirs_caves}"
SENSOR_ZIP="${SENSOR_ZIP:-$CIRS_ROOT/full_dataset.zip}"
CAMERA_BAG="${CAMERA_BAG:-}"
FRAMES_ZIP="${FRAMES_ZIP:-$CIRS_ROOT/undistorted_frames.zip}"
if [[ ! -f "$FRAMES_ZIP" ]]; then
  FRAMES_ZIP="$CIRS_ROOT/frames.zip"
fi
TIMESTAMPS="${TIMESTAMPS:-$CIRS_ROOT/undistorted_frames_timestamps.txt}"
if [[ ! -s "$TIMESTAMPS" ]]; then
  TIMESTAMPS="$CIRS_ROOT/frames_timestamps.txt"
fi
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml}"

IMAGE_TOPIC="${IMAGE_TOPIC:-/cirs/camera/image_mono}"
CAMERA_IMAGE_TOPIC_IN="${CAMERA_IMAGE_TOPIC_IN:-/camera/image_raw}"
CAMERA_INFO_TOPIC_IN="${CAMERA_INFO_TOPIC_IN:-/camera/camera_info}"
IMU_TOPIC="${IMU_TOPIC:-/cirs/imu_xsens}"
GT_TOPIC="${GT_TOPIC:-/cirs/odometry_gt}"
IMAGE_FRAME_ID="${IMAGE_FRAME_ID:-cirs_camera}"
IMU_FRAME_ID="${IMU_FRAME_ID:-cirs_imu}"

if [[ -z "${IMAGE_NAME_TEMPLATE:-}" ]]; then
  case "$(basename "$FRAMES_ZIP")" in
    undistorted*) IMAGE_NAME_TEMPLATE="frame_ud_{index:06d}.png" ;;
    *) IMAGE_NAME_TEMPLATE="frame_{index:06d}.png" ;;
  esac
fi

TAG="${TAG:-cirs_s${START_OFFSET}_d${DURATION}}"
RUN_DIR="${RUN_DIR:-$ROOT/logs/cirs_caves_vins/${MODE}_${METHOD}_every${EVERY_N}_${TAG}}"
RAW_BAG="${RAW_BAG:-$RUN_DIR/raw_segment.bag}"
METADATA_JSON="${METADATA_JSON:-$RUN_DIR/raw_segment_meta.json}"
CAMERA_CONFIG="$RUN_DIR/cirs_cam0_pinhole.yaml"
VINS_CONFIG="$RUN_DIR/vins_cirs_${MODE}.yaml"
FEATURE_BAG="$RUN_DIR/features.bag"
FEATURE_BAG_OVERRIDE="${FEATURE_BAG_OVERRIDE:-}"
if [[ -n "$FEATURE_BAG_OVERRIDE" ]]; then
  FEATURE_BAG="$FEATURE_BAG_OVERRIDE"
fi
METRICS_CSV="$RUN_DIR/frontend_metrics.csv"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"

PREPARE_BAG="${PREPARE_BAG:-1}"
FORCE_RAW="${FORCE_RAW:-0}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
EXPORT_FEATURES="${EXPORT_FEATURES:-1}"
RUN_VINS="${RUN_VINS:-1}"
PREPROCESS="${PREPROCESS:-adaptive_clahe}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-180}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
FRAME_OFFSET="${FRAME_OFFSET:-0}"
PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}"
FORMAL_THREE_LAYER_EXPORT="${FORMAL_THREE_LAYER_EXPORT:-1}"
SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-loftr}"
BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}"
BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.65}"
BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-0.80}"
VINS_SAFE_SOURCE_SELECTION="${VINS_SAFE_SOURCE_SELECTION:-1}"
VINS_SAFE_WARMUP_FRAMES="${VINS_SAFE_WARMUP_FRAMES:-20}"
VINS_SAFE_MAX_LEARNED="${VINS_SAFE_MAX_LEARNED:-8}"
VINS_SAFE_MAX_RECOVERED="${VINS_SAFE_MAX_RECOVERED:-16}"
VINS_SAFE_MIN_LEARNED_AGE="${VINS_SAFE_MIN_LEARNED_AGE:-2}"
FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE="${FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE:-0}"
FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK="${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-0}"
FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS="${FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS:-0}"
FORMAL_EXPORT_LEGACY_LOFTR_RESCUE="${FORMAL_EXPORT_LEGACY_LOFTR_RESCUE:-0}"
FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR="${FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR:-0}"
EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-0}"
FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET="${FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET:-0}"
FINAL_MIRROR_PERSISTENCE_REPLACEMENT="${FINAL_MIRROR_PERSISTENCE_REPLACEMENT:-0}"
FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME="${FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME:-4}"
FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE="${FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE:-2}"
FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN="${FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN:-0}"
FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO="${FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO:-0.0}"
LEARNED_EXPORT_LOFTR_PLANAR_RESCUE="${LEARNED_EXPORT_LOFTR_PLANAR_RESCUE:-1}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT:-6}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES:-3}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID:-0.92}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX:-1.2}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT:-0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY:-48}"
LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX:-}"
LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX:-}"
LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT="${LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT:-0}"
LEARNED_EXPORT_GEOMETRY_GATE="${LEARNED_EXPORT_GEOMETRY_GATE:-0}"
LEARNED_EXPORT_REQUIRE_CONFIRMED="${LEARNED_EXPORT_REQUIRE_CONFIRMED:-0}"
LEARNED_EXPORT_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_MIN_CLASSICAL_TRACKS:-300}"
LEARNED_EXPORT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_MIN_CLASSICAL_GRID:-0.84}"
LEARNED_EXPORT_MIN_AGE="${LEARNED_EXPORT_MIN_AGE:-5}"
LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.20}"
LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.58}"
LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-0.90}"
LEARNED_EXPORT_BENEFIT_GATE="${LEARNED_EXPORT_BENEFIT_GATE:-1}"
LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.041}"
LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}"
LEARNED_EXPORT_MIN_NEW_CELL_RATIO="${LEARNED_EXPORT_MIN_NEW_CELL_RATIO:-0.30}"
LEARNED_EXPORT_MAX_PER_NEW_CELL="${LEARNED_EXPORT_MAX_PER_NEW_CELL:-1}"
LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX:-0.0}"
LEARNED_EXPORT_BENEFIT_LOFTR_ONLY="${LEARNED_EXPORT_BENEFIT_LOFTR_ONLY:-0}"
LEARNED_EXPORT_BENEFIT_ALL_SOURCES="${LEARNED_EXPORT_BENEFIT_ALL_SOURCES:-0}"
LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_ONLINE_SEED_GATE="${LEARNED_EXPORT_ONLINE_SEED_GATE:-0}"
LEARNED_EXPORT_ONLINE_SEED_SOURCES="${LEARNED_EXPORT_ONLINE_SEED_SOURCES:-non_loftr}"
LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES:-0}"
LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME:-0}"
LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME:-0}"
LEARNED_EXPORT_ONLINE_SEED_MIN_AGE="${LEARNED_EXPORT_ONLINE_SEED_MIN_AGE:-1}"
LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY="${LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY:-0.10}"
LEARNED_EXPORT_ONLINE_SEED_MIN_NCC="${LEARNED_EXPORT_ONLINE_SEED_MIN_NCC:-0.42}"
LEARNED_EXPORT_ONLINE_SEED_MAX_FB="${LEARNED_EXPORT_ONLINE_SEED_MAX_FB:-1.20}"
LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED="${LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED:-1}"
LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH="${LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH:-0}"
LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE="${LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE:-id}"
LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_CELLS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_CELLS:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_BBOX_AREA_RATIO="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_BBOX_AREA_RATIO:-0.0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_ROWS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_ROWS:-6}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_COLS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_COLS:-6}"
LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS:-0}"
LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID:-1.0}"
LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_MAX_RESTARTS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_MAX_RESTARTS:-0}"
LEARNED_EXPORT_ONLINE_SEED_MICROBURST_RESTART_COOLDOWN_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_RESTART_COOLDOWN_FRAMES:-8}"
LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION:-0}"
LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MIN_AGE="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MIN_AGE:-8}"
LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_PER_FRAME:-2}"
LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_OBSERVATIONS:-20}"
LEARNED_EXPORT_ONLINE_SEED_LINEAGE_SEPARATE_BUDGET="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_SEPARATE_BUDGET:-0}"
LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION="${LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION:-0}"
LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES="${LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_GATE="${LEARNED_EXPORT_VISIBLE_TRACK_GATE:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES:-3}"
LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP="${LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP:-1}"
LEARNED_EXPORT_VISIBLE_TRACK_MAX_MEAN_STEP_PX="${LEARNED_EXPORT_VISIBLE_TRACK_MAX_MEAN_STEP_PX:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_PER_FRAME="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_PER_FRAME:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MOTION_DEGRADED_ONLY="${LEARNED_EXPORT_VISIBLE_TRACK_MOTION_DEGRADED_ONLY:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MOTION_MIN_FRAME="${LEARNED_EXPORT_VISIBLE_TRACK_MOTION_MIN_FRAME:-0}"
LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_COUNT_MIN_CLASSICAL_GRID:-0}"
LEARNED_EXPORT_WEAK_CELL_RESCUE="${LEARNED_EXPORT_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_WEAK_CELL_MAX_COUNT:-2}"
LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES:-5}"
LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY:-8}"
LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX:-3.0}"
LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID:-0.82}"
LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS:-0}"
LEARNED_EXPORT_MATURE_CELL_RESCUE="${LEARNED_EXPORT_MATURE_CELL_RESCUE:-0}"
LEARNED_EXPORT_MATURE_CELL_MAX_COUNT="${LEARNED_EXPORT_MATURE_CELL_MAX_COUNT:-6}"
LEARNED_EXPORT_MATURE_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_MATURE_CELL_MIN_CANDIDATES:-4}"
LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_AGE="${LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_AGE:-10.0}"
LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MATURE_CELL_MIN_CLASSICAL_MOTION_PX:-3.0}"
LEARNED_EXPORT_MATURE_CELL_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_MATURE_CELL_MAX_CLASSICAL_GRID:-0.84}"
LEARNED_EXPORT_MATURE_CELL_MAX_PER_CELL="${LEARNED_EXPORT_MATURE_CELL_MAX_PER_CELL:-2}"
LEARNED_EXPORT_MATURE_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_MATURE_CELL_MAX_OCCUPANCY:-8}"

VINS_MULTIPLE_THREAD="${VINS_MULTIPLE_THREAD:-0}"
VINS_MAX_CNT="${VINS_MAX_CNT:-180}"
VINS_MIN_DIST="${VINS_MIN_DIST:-18}"
VINS_FREQ="${VINS_FREQ:-10}"
VINS_F_THRESHOLD="${VINS_F_THRESHOLD:-1.0}"
VINS_EQUALIZE="${VINS_EQUALIZE:-1}"
VINS_KEYFRAME_PARALLAX="${VINS_KEYFRAME_PARALLAX:-10.0}"
VINS_MAX_SOLVER_TIME="${VINS_MAX_SOLVER_TIME:-0.04}"
VINS_MAX_NUM_ITERATIONS="${VINS_MAX_NUM_ITERATIONS:-8}"
ESTIMATE_EXTRINSIC="${ESTIMATE_EXTRINSIC:-1}"
BODY_T_CAM0_DATA="${BODY_T_CAM0_DATA:-0.0, 0.0, -1.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0}"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
ROSBAG_WAIT_FOR_SUBSCRIBERS="${ROSBAG_WAIT_FOR_SUBSCRIBERS:-0}"
PORT="${PORT:-13280}"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"
source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ ! -f "$SENSOR_ZIP" ]]; then
  echo "missing SENSOR_ZIP: $SENSOR_ZIP" >&2
  exit 2
fi
if [[ -n "$CAMERA_BAG" && ! -f "$CAMERA_BAG" ]]; then
  echo "missing CAMERA_BAG: $CAMERA_BAG" >&2
  exit 2
fi
if [[ -z "$CAMERA_BAG" && ! -f "$FRAMES_ZIP" ]]; then
  echo "missing FRAMES_ZIP: $FRAMES_ZIP" >&2
  exit 2
fi
if [[ -z "$CAMERA_BAG" && ! -s "$TIMESTAMPS" ]]; then
  echo "missing/nonempty TIMESTAMPS: $TIMESTAMPS" >&2
  exit 2
fi

if [[ "$PREPARE_BAG" == "1" && ( "$FORCE_RAW" == "1" || ! -f "$RAW_BAG" ) ]]; then
  if [[ -n "$CAMERA_BAG" ]]; then
    python3 -m uw_frontend.datasets.cirs_caves_to_rosbag \
      --camera-bag "$CAMERA_BAG" \
      --camera-image-topic-in "$CAMERA_IMAGE_TOPIC_IN" \
      --camera-info-topic-in "$CAMERA_INFO_TOPIC_IN" \
      --sensor-zip "$SENSOR_ZIP" \
      --output-bag "$RAW_BAG" \
      --metadata-json "$METADATA_JSON" \
      --start-offset "$START_OFFSET" \
      --duration "$DURATION" \
      --image-topic "$IMAGE_TOPIC" \
      --imu-topic "$IMU_TOPIC" \
      --gt-topic "$GT_TOPIC" \
      --image-frame-id "$IMAGE_FRAME_ID" \
      --imu-frame-id "$IMU_FRAME_ID"
  else
    python3 -m uw_frontend.datasets.cirs_caves_to_rosbag \
    --frames "$FRAMES_ZIP" \
    --timestamps "$TIMESTAMPS" \
    --sensor-zip "$SENSOR_ZIP" \
    --output-bag "$RAW_BAG" \
    --metadata-json "$METADATA_JSON" \
    --start-offset "$START_OFFSET" \
    --duration "$DURATION" \
    --image-name-template "$IMAGE_NAME_TEMPLATE" \
    --image-topic "$IMAGE_TOPIC" \
    --imu-topic "$IMU_TOPIC" \
    --gt-topic "$GT_TOPIC" \
    --image-frame-id "$IMAGE_FRAME_ID" \
    --imu-frame-id "$IMU_FRAME_ID"
  fi
fi

read -r IMAGE_WIDTH IMAGE_HEIGHT FX_DEFAULT FY_DEFAULT CX_DEFAULT CY_DEFAULT K1_DEFAULT K2_DEFAULT P1_DEFAULT P2_DEFAULT <<< "$(
  python3 - "$METADATA_JSON" <<'PY'
import json
import sys
from pathlib import Path

meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
w = int(meta["image_width"])
h = int(meta["image_height"])
info = meta.get("camera_info") or {}
K = info.get("K") or []
D = info.get("D") or []
if len(K) >= 9 and K[0] > 0 and K[4] > 0:
    fx, fy, cx, cy = float(K[0]), float(K[4]), float(K[2]), float(K[5])
else:
    f = 0.80 * max(w, h)
    fx = fy = f
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
k1 = float(D[0]) if len(D) > 0 else 0.0
k2 = float(D[1]) if len(D) > 1 else 0.0
p1 = float(D[2]) if len(D) > 2 else 0.0
p2 = float(D[3]) if len(D) > 3 else 0.0
print(w, h, fx, fy, cx, cy, k1, k2, p1, p2)
PY
)"
PROJ_FX="${PROJ_FX:-$FX_DEFAULT}"
PROJ_FY="${PROJ_FY:-$FY_DEFAULT}"
PROJ_CX="${PROJ_CX:-$CX_DEFAULT}"
PROJ_CY="${PROJ_CY:-$CY_DEFAULT}"
DIST_K1="${DIST_K1:-$K1_DEFAULT}"
DIST_K2="${DIST_K2:-$K2_DEFAULT}"
DIST_P1="${DIST_P1:-$P1_DEFAULT}"
DIST_P2="${DIST_P2:-$P2_DEFAULT}"

cat > "$CAMERA_CONFIG" <<EOF
%YAML:1.0
---
model_type: PINHOLE
camera_name: cirs_cala_viuda_cam0
image_width: $IMAGE_WIDTH
image_height: $IMAGE_HEIGHT
distortion_parameters:
   k1: $DIST_K1
   k2: $DIST_K2
   p1: $DIST_P1
   p2: $DIST_P2
projection_parameters:
   fx: $PROJ_FX
   fy: $PROJ_FY
   cx: $PROJ_CX
   cy: $PROJ_CY
EOF

VINS_IMAGE_TOPIC="/unused/image"
if [[ "$MODE" == "origin" ]]; then
  VINS_IMAGE_TOPIC="$IMAGE_TOPIC"
fi

cat > "$VINS_CONFIG" <<EOF
%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: $VINS_MULTIPLE_THREAD

imu_topic: "$IMU_TOPIC"
image0_topic: "$VINS_IMAGE_TOPIC"
image1_topic: ""
output_path: "$VINS_OUTPUT"

image_width: $IMAGE_WIDTH
image_height: $IMAGE_HEIGHT
cam0_calib: "$(basename "$CAMERA_CONFIG")"

estimate_extrinsic: $ESTIMATE_EXTRINSIC
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ $BODY_T_CAM0_DATA ]

max_cnt: $VINS_MAX_CNT
min_dist: $VINS_MIN_DIST
freq: $VINS_FREQ
F_threshold: $VINS_F_THRESHOLD
show_track: 0
flow_back: 1
equalize: $VINS_EQUALIZE

max_solver_time: $VINS_MAX_SOLVER_TIME
max_num_iterations: $VINS_MAX_NUM_ITERATIONS
keyframe_parallax: $VINS_KEYFRAME_PARALLAX

acc_n: 0.08
gyr_n: 0.004
acc_w: 0.004
gyr_w: 0.0004
g_norm: 9.8100

loop_closure: 0
td: 0.0
estimate_td: 0
rolling_shutter: 0
EOF

if [[ "$MODE" == "external" ]]; then
  if [[ "$FORCE_EXPORT" == "1" && -z "$FEATURE_BAG_OVERRIDE" ]]; then
    rm -f "$FEATURE_BAG"
  fi
  if [[ "$EXPORT_FEATURES" == "1" && -z "$FEATURE_BAG_OVERRIDE" && ! -f "$FEATURE_BAG" ]]; then
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
      --copy-topic "$IMU_TOPIC"
      --copy-topic "$GT_TOPIC"
      --metrics-csv "$METRICS_CSV"
      --backend-quality-mode "$BACKEND_QUALITY_MODE"
      --backend-quality-alpha "$BACKEND_QUALITY_ALPHA"
      --backend-quality-floor "$BACKEND_QUALITY_FLOOR"
    )
    if [[ "$PROCESS_SKIPPED_FRAMES" == "1" ]]; then
      EXPORT_ARGS+=(--process-skipped-frames)
    fi
    if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
      EXPORT_ARGS+=(--measurement-selection)
    fi
    if [[ "$FORMAL_THREE_LAYER_EXPORT" == "1" ]]; then
      EXPORT_ARGS+=(--formal-three-layer-export)
    fi
    if [[ "$VINS_SAFE_SOURCE_SELECTION" == "1" ]]; then
      EXPORT_ARGS+=(
        --vins-safe-source-selection
        --vins-safe-warmup-frames "$VINS_SAFE_WARMUP_FRAMES"
        --vins-safe-max-learned "$VINS_SAFE_MAX_LEARNED"
        --vins-safe-max-recovered "$VINS_SAFE_MAX_RECOVERED"
        --vins-safe-min-learned-age "$VINS_SAFE_MIN_LEARNED_AGE"
      )
    fi
    if [[ "$FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-allow-sparse-backbone)
    fi
    if [[ "$FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-adaptive-mirror-fallback)
    fi
    if [[ "$FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-allow-low-parallax-sidecars)
    fi
    if [[ "$FORMAL_EXPORT_LEGACY_LOFTR_RESCUE" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-legacy-loftr-rescue)
    fi
    if [[ "$FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR" == "1" ]]; then
      EXPORT_ARGS+=(--formal-export-low-texture-active-sidecar)
    fi
    if [[ "$EXPORT_CLASSICAL_MIRROR_BACKBONE" == "1" ]]; then
      EXPORT_ARGS+=(--export-classical-mirror-backbone)
    fi
    if [[ "$FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET" == "1" ]]; then
      EXPORT_ARGS+=(--final-mirror-preserve-classical-budget)
    fi
    if [[ "$FINAL_MIRROR_PERSISTENCE_REPLACEMENT" == "1" ]]; then
      EXPORT_ARGS+=(
        --final-mirror-persistence-replacement
        --final-mirror-persistence-max-selected-frame "$FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME"
        --final-mirror-persistence-min-age-advantage "$FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE"
        --final-mirror-persistence-min-gftt-ratio "$FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO"
      )
    fi
    if [[ "$FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN" == "1" ]]; then
      EXPORT_ARGS+=(--final-mirror-persistence-single-chain)
    fi
    EXPORT_ARGS+=(
      --learned-export-degradation-gate
      --learned-export-min-classical-tracks "$LEARNED_EXPORT_MIN_CLASSICAL_TRACKS"
      --learned-export-min-classical-grid "$LEARNED_EXPORT_MIN_CLASSICAL_GRID"
      --learned-export-min-age "$LEARNED_EXPORT_MIN_AGE"
      --learned-export-min-quality "$LEARNED_EXPORT_MIN_QUALITY"
      --learned-export-min-ncc "$LEARNED_EXPORT_MIN_NCC"
      --learned-export-max-fb "$LEARNED_EXPORT_MAX_FB"
      --learned-export-min-grid-gain "$LEARNED_EXPORT_MIN_GRID_GAIN"
      --learned-export-min-new-cells "$LEARNED_EXPORT_MIN_NEW_CELLS"
      --learned-export-min-new-cell-ratio "$LEARNED_EXPORT_MIN_NEW_CELL_RATIO"
      --learned-export-max-per-new-cell "$LEARNED_EXPORT_MAX_PER_NEW_CELL"
      --learned-export-coverage-gain-max-classical-tracks "$LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS"
      --learned-export-sidecar-max-observations "$LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS"
      --learned-export-low-parallax-sidecar-max-observations "$LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS"
      --learned-export-min-classical-motion-px "$LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX"
      --learned-export-geometry-gate
      --learned-export-require-confirmed
    )
    if [[ "$LEARNED_EXPORT_BENEFIT_GATE" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-benefit-gate)
    fi
    if [[ "$LEARNED_EXPORT_BENEFIT_LOFTR_ONLY" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-benefit-loftr-only)
    fi
    if [[ "$LEARNED_EXPORT_BENEFIT_ALL_SOURCES" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-benefit-all-sources)
    fi
    if [[ "$LEARNED_EXPORT_ONLINE_SEED_GATE" == "1" ]]; then
      EXPORT_ARGS+=(
        --learned-export-online-seed-gate
        --learned-export-online-seed-sources "$LEARNED_EXPORT_ONLINE_SEED_SOURCES"
        --learned-export-online-seed-warmup-frames "$LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES"
        --learned-export-online-seed-max-observations "$LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS"
        --learned-export-online-seed-max-per-frame "$LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME"
        --learned-export-online-seed-post-quality-cap-per-frame "$LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME"
        --learned-export-online-seed-min-age "$LEARNED_EXPORT_ONLINE_SEED_MIN_AGE"
        --learned-export-online-seed-min-quality "$LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY"
        --learned-export-online-seed-min-ncc "$LEARNED_EXPORT_ONLINE_SEED_MIN_NCC"
        --learned-export-online-seed-max-fb "$LEARNED_EXPORT_ONLINE_SEED_MAX_FB"
      )
      if [[ "$LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED" == "1" ]]; then
        EXPORT_ARGS+=(--learned-export-online-seed-require-confirmed)
      fi
      if [[ "$LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-online-seed-require-fresh
          --learned-export-online-seed-fresh-scope "$LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE"
          --learned-export-online-seed-fresh-hold-frames "$LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES"
        )
      fi
      if [[ "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-online-seed-microburst-gate
          --learned-export-online-seed-microburst-frames "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES"
          --learned-export-online-seed-microburst-extend-frames "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES"
          --learned-export-online-seed-microburst-extend-min-initial-observations "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS"
          --learned-export-online-seed-microburst-extend-min-initial-cells "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_CELLS"
          --learned-export-online-seed-microburst-extend-min-bbox-area-ratio "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_BBOX_AREA_RATIO"
          --learned-export-online-seed-microburst-extend-grid-rows "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_ROWS"
          --learned-export-online-seed-microburst-extend-grid-cols "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_COLS"
          --learned-export-online-seed-microburst-max-restarts "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_MAX_RESTARTS"
          --learned-export-online-seed-microburst-restart-cooldown-frames "$LEARNED_EXPORT_ONLINE_SEED_MICROBURST_RESTART_COOLDOWN_FRAMES"
          --learned-export-online-seed-dense-start-max-observations "$LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS"
          --learned-export-online-seed-dense-start-min-classical-tracks "$LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS"
          --learned-export-online-seed-dense-start-min-classical-grid "$LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID"
          --learned-export-online-seed-dense-start-min-frame-candidates "$LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES"
        )
      fi
      if [[ "$LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION" == "1" ]]; then
        EXPORT_ARGS+=(
          --learned-export-online-seed-lineage-continuation
          --learned-export-online-seed-lineage-min-age "$LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MIN_AGE"
          --learned-export-online-seed-lineage-max-per-frame "$LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_PER_FRAME"
          --learned-export-online-seed-lineage-max-observations "$LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_OBSERVATIONS"
        )
        if [[ "$LEARNED_EXPORT_ONLINE_SEED_LINEAGE_SEPARATE_BUDGET" == "1" ]]; then
          EXPORT_ARGS+=(--learned-export-online-seed-lineage-separate-budget)
        fi
      fi
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
      if [[ "$LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE" == "1" ]]; then
        EXPORT_ARGS+=(--learned-export-non-loftr-weak-cell-rescue)
      fi
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
        EXPORT_ARGS+=(--learned-export-loftr-support-max-init-parallax-px "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX")
      fi
      if [[ -n "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX" ]]; then
        EXPORT_ARGS+=(--learned-export-loftr-support-max-classical-motion-px "$LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX")
      fi
    fi
    if [[ "$LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT" == "1" ]]; then
      EXPORT_ARGS+=(--learned-export-allow-early-loftr-support)
    fi
    python3 -m uw_frontend.ros.export_vins_features "${EXPORT_ARGS[@]}"
  fi
fi

if [[ "$MODE" == "external" && -n "$FEATURE_BAG_OVERRIDE" ]]; then
  if [[ ! -f "$FEATURE_BAG" ]]; then
    echo "feature bag override does not exist: $FEATURE_BAG" >&2
    exit 2
  fi
  SOURCE_METRICS="$(dirname "$FEATURE_BAG")/frontend_metrics.csv"
  if [[ -f "$SOURCE_METRICS" && ! -f "$METRICS_CSV" ]]; then
    cp "$SOURCE_METRICS" "$METRICS_CSV"
  fi
fi

if [[ "$RUN_VINS" != "1" ]]; then
  echo "run_dir=$RUN_DIR"
  exit 0
fi

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

if [[ "$MODE" == "external" ]]; then
  PLAY_BAG="$FEATURE_BAG"
else
  PLAY_BAG="$RAW_BAG"
fi
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

{
  echo "run_dir=$RUN_DIR"
  echo "raw_bag=$RAW_BAG"
  echo "play_bag=$PLAY_BAG"
  echo "feature_bag=$FEATURE_BAG"
  echo "metadata_json=$METADATA_JSON"
  echo "vins_config=$VINS_CONFIG"
  echo "vins_csv=$VINS_OUTPUT/vio.csv"
} | tee "$RUN_DIR/replay_manifest.txt"
