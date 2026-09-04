#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-q}" # q | constq

ROOT="/home/ma/AQUA-FE_WS"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
RAW_BAG="$ROOT/datasets/aqualoc/rosbags/harbor07_1660_1950.bag"
OUT_ROOT="$ROOT/logs/agent_qi_vins"
RUN_DIR="$OUT_ROOT/h07_1660_1950_${MODE}"

IMAGE_TOPIC="/camera/image_raw"
IMU_TOPIC="/rtimulib_node/imu"
GT_TOPIC="/aqualoc/colmap_gt"

METHOD="${METHOD:-klt}"
EVERY_N="${EVERY_N:-2}"
DURATION="${DURATION:-10.0}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-150}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
FRAME_OFFSET="${FRAME_OFFSET:-1}"
PREPROCESS="${PREPROCESS:-none}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}"
if [[ -z "${PORT:-}" ]]; then
  PORT="11341"
  if [[ "$MODE" == "constq" ]]; then
    PORT="11342"
  fi
fi

FEATURE_BAG="$RUN_DIR/features.bag"
METRICS_CSV="$RUN_DIR/frontend_metrics.csv"
CAMERA_CONFIG="$RUN_DIR/aqualoc_harbor07_kannala.yaml"
VINS_CONFIG="$RUN_DIR/vins_external_features.yaml"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"

case "$MODE" in
  q|constq) ;;
  *)
    echo "usage: $0 [q|constq]" >&2
    exit 2
    ;;
esac

if [[ ! -f "$RAW_BAG" ]]; then
  echo "missing input bag: $RAW_BAG" >&2
  exit 1
fi

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

cat > "$CAMERA_CONFIG" <<'EOF'
%YAML:1.0
---
model_type: KANNALA_BRANDT
camera_name: aqualoc_harbor07
image_width: 640
image_height: 512
projection_parameters:
   k2: -0.06125568297136998
   k3: -0.003796743395135256
   k4: 0.027326634771204592
   k5: -0.030296403142887066
   mu: 413.32595366566017
   mv: 413.70198739483686
   u0: 305.9507483284928
   v0: 259.4439948946375
EOF

QUALITY_FLAG=()
if [[ "$MODE" == "constq" ]]; then
  QUALITY_FLAG=(--constant-quality-to-backend)
fi

if [[ ! -f "$FEATURE_BAG" ]]; then
  SELECTION_FLAG=()
  if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
    SELECTION_FLAG=(--measurement-selection)
  fi
  python3 -m uw_frontend.ros.export_vins_features \
    --bag "$RAW_BAG" \
    --image-topic "$IMAGE_TOPIC" \
    --camera-config "$CAMERA_CONFIG" \
    --output-bag "$FEATURE_BAG" \
    --config "$ROOT/uw_frontend/configs/backend_strict_frontend.yaml" \
    --method "$METHOD" \
    --duration "$DURATION" \
    --every-n "$EVERY_N" \
    --frame-offset "$FRAME_OFFSET" \
    --export-max-features "$EXPORT_MAX_FEATURES" \
    --export-min-age "$EXPORT_MIN_AGE" \
    --preprocess "$PREPROCESS" \
    --timestamp-source header \
    --max-header-stamp-delta 0.25 \
    --invalid-header-policy skip \
    --copy-topic "$IMU_TOPIC" \
    --copy-topic "$GT_TOPIC" \
    --metrics-csv "$METRICS_CSV" \
    --process-skipped-frames \
    "${SELECTION_FLAG[@]}" \
    "${QUALITY_FLAG[@]}"
fi

cat > "$VINS_CONFIG" <<EOF
%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "$IMU_TOPIC"
image0_topic: "/unused/image"
image1_topic: ""
output_path: "$VINS_OUTPUT"

image_width: 640
image_height: 512
cam0_calib: "$(basename "$CAMERA_CONFIG")"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ -0.99978035,  0.0169654,   0.01230552, -0.01719238,
            0.01210101, -0.01210461,  0.99985351,  0.14944769,
            0.01711187,  0.9997828,   0.01189665, -0.01915984,
            0.0,         0.0,         0.0,         1.0 ]

max_cnt: 150
min_dist: 20
freq: 10
F_threshold: 1.0
show_track: 0
flow_back: 1
equalize: 1

max_solver_time: 0.04
max_num_iterations: 8
keyframe_parallax: 10.0

acc_n: 0.02
gyr_n: 0.001
acc_w: 0.001
gyr_w: 0.00005
g_norm: 9.8100

loop_closure: 0
td: -0.0403806549886
estimate_td: 0
rolling_shutter: 0
EOF

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
rosrun vins vins_node "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
VINS_PID=$!
sleep 4
rosbag play "$FEATURE_BAG" --clock --quiet
sleep 8

python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
  --vins-csv "$VINS_OUTPUT/vio.csv" \
  --bag "$FEATURE_BAG" \
  --gt-topic "$GT_TOPIC" \
  --vins-log "$VINS_LOG" | tee "$APE_REPORT"

echo "run_dir=$RUN_DIR"
echo "feature_bag=$FEATURE_BAG"
echo "vins_csv=$VINS_OUTPUT/vio.csv"
