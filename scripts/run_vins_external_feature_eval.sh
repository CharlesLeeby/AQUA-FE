#!/usr/bin/env bash
set -euo pipefail

DATASET="${1:-raw}"
DURATION="${2:-40}"
METHOD="${3:-hybrid_xfeat}"
EVERY_N="${4:-2}"

ROOT="/home/ma/AQUA-FE_WS"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"

FRAME_OFFSET="${FRAME_OFFSET:-1}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/backend_strict_frontend.yaml}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-150}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
MAX_HEADER_STAMP_DELTA="${MAX_HEADER_STAMP_DELTA:-0.25}"
TIMESTAMP_SOURCE="${TIMESTAMP_SOURCE:-header}"
INVALID_HEADER_POLICY="${INVALID_HEADER_POLICY:-skip}"
PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}"
ZERO_VELOCITY="${ZERO_VELOCITY:-0}"

IMAGE_TOPIC="/wall_climber/camerafront/camera_image"
IMU_TOPIC="/wall_climber/imu"
GT_TOPIC="/ground_truth/state"
CAMERA_CONFIG="$ROOT/logs/vins_origin/sim_cam0_pinhole.yaml"
CAMERA_CONFIG_DIR="$(dirname "$CAMERA_CONFIG")"
CAMERA_CONFIG_NAME="$(basename "$CAMERA_CONFIG")"

case "$DATASET" in
  straight)
    BAG="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_straight.bag"
    PORT=11321
    ;;
  realistic)
    BAG="/home/ma/Dataset/my_dave_bot_bags/realistic_auto_20260403_233741.bag"
    PORT=11322
    ;;
  raw)
    BAG="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_simdata_raw.bag"
    PORT=11323
    ;;
  *)
    echo "usage: $0 [straight|realistic|raw] [duration_seconds] [method]" >&2
    exit 2
    ;;
esac

TAG="${TAG:-backend_ready}"
RUN_DIR="$ROOT/logs/vins_external/${DATASET}_${METHOD}_${DURATION}s_every${EVERY_N}_off${FRAME_OFFSET}_${TAG}"
FEATURE_BAG="$RUN_DIR/features.bag"
METRICS_CSV="$RUN_DIR/frontend_metrics.csv"
VINS_CONFIG="$RUN_DIR/vins_external_features.yaml"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"

if [[ ! -f "$FEATURE_BAG" ]]; then
  python3 -m uw_frontend.ros.export_vins_features \
    --bag "$BAG" \
    --image-topic "$IMAGE_TOPIC" \
    --camera-config "$CAMERA_CONFIG" \
    --output-bag "$FEATURE_BAG" \
    --config "$FRONTEND_CONFIG" \
    --method "$METHOD" \
    --duration "$DURATION" \
    --every-n "$EVERY_N" \
    --frame-offset "$FRAME_OFFSET" \
    --max-header-stamp-delta "$MAX_HEADER_STAMP_DELTA" \
    --timestamp-source "$TIMESTAMP_SOURCE" \
    --invalid-header-policy "$INVALID_HEADER_POLICY" \
    --export-max-features "$EXPORT_MAX_FEATURES" \
    --export-min-age "$EXPORT_MIN_AGE" \
    --copy-topic "$IMU_TOPIC" \
    --copy-topic "$GT_TOPIC" \
    --metrics-csv "$METRICS_CSV" \
    $([[ "$PROCESS_SKIPPED_FRAMES" == "1" ]] && printf '%s' '--process-skipped-frames') \
    $([[ "$MEASUREMENT_SELECTION" == "1" ]] && printf '%s' '--measurement-selection') \
    $([[ "$ZERO_VELOCITY" == "1" ]] && printf '%s' '--zero-velocity')
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

image_width: 768
image_height: 492
cam0_calib: "$CAMERA_CONFIG_NAME"

estimate_extrinsic: 0
body_T_cam0: !!opencv-matrix
   rows: 4
   cols: 4
   dt: d
   data: [ 0.0, -0.34202014, 0.93969262, 0.3,
          -1.0,  0.0,         0.0,         0.0,
           0.0, -0.93969262, -0.34202014, 0.25,
           0.0,  0.0,         0.0,         1.0 ]

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

acc_n: 0.1
gyr_n: 0.01
acc_w: 0.002
gyr_w: 2.0e-5
g_norm: 9.8000

td: 0.0
estimate_td: 0
rolling_shutter: 0
EOF

cp "$CAMERA_CONFIG" "$RUN_DIR/$CAMERA_CONFIG_NAME"

rm -f "$VINS_OUTPUT/vio.csv" "$VINS_LOG"

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
  --gt-topic "$GT_TOPIC" | tee "$APE_REPORT"

echo "run_dir=$RUN_DIR"
echo "feature_bag=$FEATURE_BAG"
echo "vins_csv=$VINS_OUTPUT/vio.csv"
