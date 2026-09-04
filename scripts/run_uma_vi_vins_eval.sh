#!/usr/bin/env bash
set -euo pipefail

# UMA-VI sample VINS wrapper.
#
# Usage:
#   RUN_VINS=0 bash scripts/run_uma_vi_vins_eval.sh METHOD START_OFFSET DURATION EVERY_N
#
# METHOD is any export_vins_features method, e.g. klt, hybrid_xfeat,
# hybrid_superpoint_lightglue. The wrapper prepares a compact ROS bag from the
# UMA-VI sample, exports VINS external features, and optionally replays VINS.

METHOD="${1:-klt}"
START_OFFSET="${2:-0.0}"
DURATION="${3:-30.0}"
EVERY_N="${4:-2}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
UMA_ROOT="${UMA_ROOT:-/mnt/data/AQUA-FE_WS/datasets/full_downloads/uma_vi}"
SEQUENCE_DIR="${SEQUENCE_DIR:-$UMA_ROOT/sample/sample}"
CAMCHAIN="${CAMCHAIN:-$UMA_ROOT/calibration_files/camchain-imu-ueye.yaml}"
IMU_YAML="${IMU_YAML:-$UMA_ROOT/calibration_files/imu-xsens.yaml}"
CAMERA_KEY="${CAMERA_KEY:-cam0}"
CAMERA_FOLDER="${CAMERA_FOLDER:-cam2}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml}"

IMAGE_TOPIC="${IMAGE_TOPIC:-/camera/image_raw}"
IMU_TOPIC="${IMU_TOPIC:-/imu0/data}"
GT_TOPIC="${GT_TOPIC:-/uma/gt}"
SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-loftr}"
PREPROCESS="${PREPROCESS:-adaptive_clahe}"

TAG="${TAG:-uma_${METHOD}_s${START_OFFSET}_d${DURATION}_e${EVERY_N}}"
RUN_DIR="${RUN_DIR:-$ROOT/logs/uma_vi_vins/${TAG}}"
SHORT_BAG="${SHORT_BAG:-$RUN_DIR/uma_short.bag}"
CAMERA_CONFIG="${CAMERA_CONFIG:-$RUN_DIR/uma_cam0_pinhole.yaml}"
VINS_CONFIG="${VINS_CONFIG:-$RUN_DIR/vins_uma_external.yaml}"
FEATURE_BAG="${FEATURE_BAG:-$RUN_DIR/features.bag}"
VINS_OUTPUT="${VINS_OUTPUT:-$RUN_DIR/vins_output}"
VINS_LOG="${VINS_LOG:-$RUN_DIR/vins.log}"
APE_REPORT="${APE_REPORT:-$RUN_DIR/ape.txt}"

PREPARE_BAG="${PREPARE_BAG:-1}"
FORCE_RAW="${FORCE_RAW:-0}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
EXPORT_FEATURES="${EXPORT_FEATURES:-1}"
RUN_VINS="${RUN_VINS:-1}"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
PORT="${PORT:-13040}"

EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}"
PRESERVE_SIDECARS_THROUGH_SELECTION="${PRESERVE_SIDECARS_THROUGH_SELECTION:-0}"

FORMAL_THREE_LAYER_EXPORT="${FORMAL_THREE_LAYER_EXPORT:-0}"
FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE="${FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE:-0}"
FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK="${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-0}"
FORMAL_EXPORT_DISABLE_POST_SIDECAR_MIRROR_REFILL="${FORMAL_EXPORT_DISABLE_POST_SIDECAR_MIRROR_REFILL:-0}"
FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR="${FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR:-0}"
LEARNED_EXPORT_LOFTR_SOURCE_MEMORY="${LEARNED_EXPORT_LOFTR_SOURCE_MEMORY:-0}"
LEARNED_EXPORT_DEGRADATION_GATE="${LEARNED_EXPORT_DEGRADATION_GATE:-0}"
LEARNED_EXPORT_BENEFIT_GATE="${LEARNED_EXPORT_BENEFIT_GATE:-0}"
LEARNED_EXPORT_BENEFIT_ALL_SOURCES="${LEARNED_EXPORT_BENEFIT_ALL_SOURCES:-0}"
LEARNED_EXPORT_GEOMETRY_GATE="${LEARNED_EXPORT_GEOMETRY_GATE:-0}"
LEARNED_EXPORT_REQUIRE_CONFIRMED="${LEARNED_EXPORT_REQUIRE_CONFIRMED:-0}"
LEARNED_EXPORT_WEAK_CELL_RESCUE="${LEARNED_EXPORT_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_PLANAR_RESCUE="${LEARNED_EXPORT_LOFTR_PLANAR_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE:-0}"
LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY="${LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY:-0}"

LEARNED_EXPORT_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_MIN_CLASSICAL_TRACKS:-300}"
LEARNED_EXPORT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_MIN_CLASSICAL_GRID:-0.84}"
LEARNED_EXPORT_MIN_AGE="${LEARNED_EXPORT_MIN_AGE:-5}"
LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.20}"
LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.58}"
LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-0.90}"
LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.041}"
LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}"
LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX:-0.0}"
LEARNED_EXPORT_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_WEAK_CELL_MAX_COUNT:-2}"
LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES:-5}"
LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY:-8}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT:-6}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES:-3}"
LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID:-0.92}"
LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX:-1.2}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT:-6}"
LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY:-48}"
LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS:-0}"

BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}"
BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.65}"
BACKEND_LEARNED_QUALITY_SCALE="${BACKEND_LEARNED_QUALITY_SCALE:-1.0}"
BACKEND_SP_LG_QUALITY_SCALE="${BACKEND_SP_LG_QUALITY_SCALE:-1.0}"
BACKEND_XFEAT_QUALITY_SCALE="${BACKEND_XFEAT_QUALITY_SCALE:-1.0}"
BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-1.0}"
VINS_SAFE_SOURCE_SELECTION="${VINS_SAFE_SOURCE_SELECTION:-1}"
VINS_SAFE_WARMUP_FRAMES="${VINS_SAFE_WARMUP_FRAMES:-20}"
VINS_SAFE_MAX_LEARNED="${VINS_SAFE_MAX_LEARNED:-24}"
VINS_SAFE_MAX_RECOVERED="${VINS_SAFE_MAX_RECOVERED:-16}"
VINS_SAFE_MIN_LEARNED_AGE="${VINS_SAFE_MIN_LEARNED_AGE:-3}"

VINS_MULTIPLE_THREAD="${VINS_MULTIPLE_THREAD:-0}"
VINS_MAX_CNT="${VINS_MAX_CNT:-150}"
VINS_MIN_DIST="${VINS_MIN_DIST:-20}"
VINS_FREQ="${VINS_FREQ:-10}"
VINS_F_THRESHOLD="${VINS_F_THRESHOLD:-1.0}"
VINS_EQUALIZE="${VINS_EQUALIZE:-1}"
VINS_KEYFRAME_PARALLAX="${VINS_KEYFRAME_PARALLAX:-10.0}"
VINS_MAX_SOLVER_TIME="${VINS_MAX_SOLVER_TIME:-0.04}"
VINS_MAX_NUM_ITERATIONS="${VINS_MAX_NUM_ITERATIONS:-8}"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ ! -d "$SEQUENCE_DIR" ]]; then
  echo "missing SEQUENCE_DIR: $SEQUENCE_DIR" >&2
  exit 2
fi
if [[ ! -f "$CAMCHAIN" ]]; then
  echo "missing CAMCHAIN: $CAMCHAIN" >&2
  exit 2
fi
if [[ ! -f "$IMU_YAML" ]]; then
  echo "missing IMU_YAML: $IMU_YAML" >&2
  exit 2
fi

if [[ "$FORCE_RAW" == "1" ]]; then
  rm -f "$SHORT_BAG"
fi
if [[ "$PREPARE_BAG" == "1" && ! -f "$SHORT_BAG" ]]; then
  python3 -m uw_frontend.datasets.uma_vi_to_rosbag \
    --sequence-dir "$SEQUENCE_DIR" \
    --camera "$CAMERA_FOLDER" \
    --output-bag "$SHORT_BAG" \
    --start-offset "$START_OFFSET" \
    --duration "$DURATION" \
    --image-topic "$IMAGE_TOPIC" \
    --imu-topic "$IMU_TOPIC" \
    --gt-topic "$GT_TOPIC"
fi

python3 - "$CAMCHAIN" "$IMU_YAML" "$CAMERA_CONFIG" "$VINS_CONFIG" "$VINS_OUTPUT" \
  "$IMAGE_TOPIC" "$IMU_TOPIC" "$CAMERA_KEY" "$VINS_MULTIPLE_THREAD" "$VINS_MAX_CNT" \
  "$VINS_MIN_DIST" "$VINS_FREQ" "$VINS_F_THRESHOLD" "$VINS_EQUALIZE" \
  "$VINS_KEYFRAME_PARALLAX" "$VINS_MAX_SOLVER_TIME" "$VINS_MAX_NUM_ITERATIONS" <<'PY'
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import yaml

camchain_path = Path(sys.argv[1])
imu_yaml_path = Path(sys.argv[2])
camera_config = Path(sys.argv[3])
vins_config = Path(sys.argv[4])
vins_output = Path(sys.argv[5])
image_topic = sys.argv[6]
imu_topic = sys.argv[7]
camera_key = sys.argv[8]
multiple_thread = int(sys.argv[9])
max_cnt = int(sys.argv[10])
min_dist = int(sys.argv[11])
freq = int(sys.argv[12])
f_threshold = float(sys.argv[13])
equalize = int(sys.argv[14])
keyframe_parallax = float(sys.argv[15])
max_solver_time = float(sys.argv[16])
max_num_iterations = int(sys.argv[17])

camchain = yaml.safe_load(camchain_path.read_text(encoding="utf-8"))
imu_cfg = yaml.safe_load(imu_yaml_path.read_text(encoding="utf-8"))
cam = camchain[camera_key]
fx, fy, cx, cy = [float(v) for v in cam["intrinsics"]]
k1, k2, p1, p2 = [float(v) for v in cam["distortion_coeffs"][:4]]
width, height = [int(v) for v in cam["resolution"]]
t_cam_imu = np.asarray(cam["T_cam_imu"], dtype=float)
t_imu_cam = np.linalg.inv(t_cam_imu)
td = float(cam.get("timeshift_cam_imu", 0.0))
acc_n = float(imu_cfg.get("accelerometer_noise_density", 0.02))
acc_w = float(imu_cfg.get("accelerometer_random_walk", 0.001))
gyr_n = float(imu_cfg.get("gyroscope_noise_density", 0.001))
gyr_w = float(imu_cfg.get("gyroscope_random_walk", 0.00005))

camera_config.write_text(
    "%YAML:1.0\n"
    "---\n"
    "model_type: PINHOLE\n"
    "camera_name: uma_cam\n"
    f"image_width: {width}\n"
    f"image_height: {height}\n"
    "distortion_parameters:\n"
    f"   k1: {k1:.17g}\n"
    f"   k2: {k2:.17g}\n"
    f"   p1: {p1:.17g}\n"
    f"   p2: {p2:.17g}\n"
    "projection_parameters:\n"
    f"   fx: {fx:.17g}\n"
    f"   fy: {fy:.17g}\n"
    f"   cx: {cx:.17g}\n"
    f"   cy: {cy:.17g}\n",
    encoding="utf-8",
)

flat = ",\n           ".join(", ".join(f"{float(v):.17g}" for v in row) for row in t_imu_cam)
vins_output.mkdir(parents=True, exist_ok=True)
vins_config.write_text(
    "%YAML:1.0\n\n"
    "imu: 1\n"
    "num_of_cam: 1\n"
    f"multiple_thread: {multiple_thread}\n\n"
    f"imu_topic: \"{imu_topic}\"\n"
    "image0_topic: \"/unused/image\"\n"
    "image1_topic: \"\"\n"
    f"output_path: \"{vins_output}\"\n\n"
    f"image_width: {width}\n"
    f"image_height: {height}\n"
    f"cam0_calib: \"{camera_config.name}\"\n\n"
    "estimate_extrinsic: 0\n"
    "body_T_cam0: !!opencv-matrix\n"
    "   rows: 4\n"
    "   cols: 4\n"
    "   dt: d\n"
    f"   data: [{flat}]\n\n"
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
    f"acc_n: {acc_n:.17g}\n"
    f"gyr_n: {gyr_n:.17g}\n"
    f"acc_w: {acc_w:.17g}\n"
    f"gyr_w: {gyr_w:.17g}\n"
    "g_norm: 9.8100\n\n"
    f"td: {td:.17g}\n"
    "estimate_td: 0\n"
    "rolling_shutter: 0\n",
    encoding="utf-8",
)
print(f"camera_config={camera_config}")
print(f"vins_config={vins_config}")
PY

if [[ "$FORCE_EXPORT" == "1" ]]; then
  rm -f "$FEATURE_BAG"
fi
if [[ "$EXPORT_FEATURES" == "1" && ! -f "$FEATURE_BAG" ]]; then
  EXPORT_ARGS=(
    --bag "$SHORT_BAG"
    --image-topic "$IMAGE_TOPIC"
    --camera-config "$CAMERA_CONFIG"
    --output-bag "$FEATURE_BAG"
    --config "$FRONTEND_CONFIG"
    --method "$METHOD"
    --semidense-fallback-method "$SEMIDENSE_FALLBACK_METHOD"
    --every-n "$EVERY_N"
    --export-max-features "$EXPORT_MAX_FEATURES"
    --export-min-age "$EXPORT_MIN_AGE"
    --preprocess "$PREPROCESS"
    --timestamp-source header
    --max-header-stamp-delta 0.25
    --invalid-header-policy skip
    --copy-topic "$IMU_TOPIC"
    --copy-topic "$GT_TOPIC"
    --metrics-csv "$RUN_DIR/frontend_metrics.csv"
  )
  if [[ "$PROCESS_SKIPPED_FRAMES" == "1" ]]; then
    EXPORT_ARGS+=(--process-skipped-frames)
  fi
  if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
    EXPORT_ARGS+=(--measurement-selection)
  fi
  if [[ "$PRESERVE_SIDECARS_THROUGH_SELECTION" == "1" ]]; then
    EXPORT_ARGS+=(--preserve-sidecars-through-selection)
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
  if [[ "$FORMAL_EXPORT_DISABLE_POST_SIDECAR_MIRROR_REFILL" == "1" ]]; then
    EXPORT_ARGS+=(--formal-export-disable-post-sidecar-mirror-refill)
  fi
  if [[ "$FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR" == "1" ]]; then
    EXPORT_ARGS+=(--formal-export-low-texture-active-sidecar)
  fi
  if [[ "$LEARNED_EXPORT_LOFTR_SOURCE_MEMORY" == "1" ]]; then
    EXPORT_ARGS+=(--learned-export-loftr-source-memory)
  fi
  if [[ "$LEARNED_EXPORT_DEGRADATION_GATE" == "1" ]]; then
    EXPORT_ARGS+=(
      --learned-export-degradation-gate
      --learned-export-min-classical-tracks "$LEARNED_EXPORT_MIN_CLASSICAL_TRACKS"
      --learned-export-min-classical-grid "$LEARNED_EXPORT_MIN_CLASSICAL_GRID"
      --learned-export-min-age "$LEARNED_EXPORT_MIN_AGE"
      --learned-export-min-quality "$LEARNED_EXPORT_MIN_QUALITY"
      --learned-export-min-ncc "$LEARNED_EXPORT_MIN_NCC"
      --learned-export-max-fb "$LEARNED_EXPORT_MAX_FB"
    )
  fi
  if [[ "$LEARNED_EXPORT_BENEFIT_GATE" == "1" ]]; then
    EXPORT_ARGS+=(
      --learned-export-benefit-gate
      --learned-export-min-grid-gain "$LEARNED_EXPORT_MIN_GRID_GAIN"
      --learned-export-min-new-cells "$LEARNED_EXPORT_MIN_NEW_CELLS"
      --learned-export-min-classical-motion-px "$LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX"
    )
  fi
  if [[ "$LEARNED_EXPORT_BENEFIT_ALL_SOURCES" == "1" ]]; then
    EXPORT_ARGS+=(--learned-export-benefit-all-sources)
  fi
  if [[ "$LEARNED_EXPORT_WEAK_CELL_RESCUE" == "1" ]]; then
    EXPORT_ARGS+=(
      --learned-export-weak-cell-rescue
      --learned-export-weak-cell-max-count "$LEARNED_EXPORT_WEAK_CELL_MAX_COUNT"
      --learned-export-weak-cell-min-candidates "$LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES"
      --learned-export-weak-cell-max-occupancy "$LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY"
    )
  fi
  if [[ "$LEARNED_EXPORT_LOFTR_PLANAR_RESCUE" == "1" ]]; then
    EXPORT_ARGS+=(
      --learned-export-loftr-planar-rescue
      --learned-export-loftr-planar-max-count "$LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT"
      --learned-export-loftr-planar-min-candidates "$LEARNED_EXPORT_LOFTR_PLANAR_MIN_CANDIDATES"
      --learned-export-loftr-planar-max-classical-grid "$LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID"
      --learned-export-loftr-planar-min-classical-motion-px "$LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX"
    )
  fi
  if [[ "$LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE" == "1" ]]; then
    EXPORT_ARGS+=(
      --learned-export-loftr-weak-cell-rescue
      --learned-export-loftr-weak-cell-max-count "$LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT"
      --learned-export-loftr-weak-cell-max-occupancy "$LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_OCCUPANCY"
      --learned-export-loftr-rescue-max-classical-tracks "$LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS"
    )
  fi
  if [[ "$LEARNED_EXPORT_GEOMETRY_GATE" == "1" ]]; then
    EXPORT_ARGS+=(--learned-export-geometry-gate)
  fi
  if [[ "$LEARNED_EXPORT_REQUIRE_CONFIRMED" == "1" ]]; then
    EXPORT_ARGS+=(--learned-export-require-confirmed)
  fi
  if [[ "$LEARNED_EXPORT_LOFTR_REQUIRES_HOMOGRAPHY" == "1" ]]; then
    EXPORT_ARGS+=(--learned-export-loftr-requires-homography)
  fi
  EXPORT_ARGS+=(
    --backend-quality-mode "$BACKEND_QUALITY_MODE"
    --backend-quality-alpha "$BACKEND_QUALITY_ALPHA"
    --backend-learned-quality-scale "$BACKEND_LEARNED_QUALITY_SCALE"
    --backend-sp-lg-quality-scale "$BACKEND_SP_LG_QUALITY_SCALE"
    --backend-xfeat-quality-scale "$BACKEND_XFEAT_QUALITY_SCALE"
    --backend-loftr-quality-scale "$BACKEND_LOFTR_QUALITY_SCALE"
  )
  if [[ "$VINS_SAFE_SOURCE_SELECTION" == "1" ]]; then
    EXPORT_ARGS+=(
      --vins-safe-source-selection
      --vins-safe-warmup-frames "$VINS_SAFE_WARMUP_FRAMES"
      --vins-safe-max-learned "$VINS_SAFE_MAX_LEARNED"
      --vins-safe-max-recovered "$VINS_SAFE_MAX_RECOVERED"
      --vins-safe-min-learned-age "$VINS_SAFE_MIN_LEARNED_AGE"
    )
  fi
  python3 -m uw_frontend.ros.export_vins_features "${EXPORT_ARGS[@]}"
fi

if [[ "$RUN_VINS" == "1" ]]; then
  rm -f "$VINS_OUTPUT/vio.csv" "$VINS_LOG" "$APE_REPORT"
  source "$VINS_WS/devel/setup.bash"
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

  rosbag play "$FEATURE_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet
  sleep "$POST_PLAY_SLEEP"

  python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
    --vins-csv "$VINS_OUTPUT/vio.csv" \
    --bag "$FEATURE_BAG" \
    --gt-topic "$GT_TOPIC" \
    --vins-log "$VINS_LOG" | tee "$APE_REPORT"
fi

{
  echo "run_dir=$RUN_DIR"
  echo "short_bag=$SHORT_BAG"
  echo "feature_bag=$FEATURE_BAG"
  echo "camera_config=$CAMERA_CONFIG"
  echo "vins_config=$VINS_CONFIG"
  echo "method=$METHOD"
  echo "start_offset=$START_OFFSET"
  echo "duration=$DURATION"
  echo "every_n=$EVERY_N"
} | tee "$RUN_DIR/replay_manifest.txt"
