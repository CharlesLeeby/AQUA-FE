#!/usr/bin/env bash
set -euo pipefail

DATASET="${1:-raw}"
DURATION="${2:-40}"

ROOT="/home/ma/AQUA-FE_WS"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
IMAGE_TOPIC="/wall_climber/camerafront/camera_image"
IMU_TOPIC="/wall_climber/imu"
GT_TOPIC="/ground_truth/state"
CAMERA_CONFIG="$ROOT/logs/vins_origin/sim_cam0_pinhole.yaml"
CAMERA_CONFIG_NAME="$(basename "$CAMERA_CONFIG")"

case "$DATASET" in
  straight)
    BAG="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_straight.bag"
    PORT=11331
    ;;
  realistic)
    BAG="/home/ma/Dataset/my_dave_bot_bags/realistic_auto_20260403_233741.bag"
    PORT=11332
    ;;
  raw)
    BAG="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_simdata_raw.bag"
    PORT=11333
    ;;
  *)
    echo "usage: $0 [straight|realistic|raw] [duration_seconds]" >&2
    exit 2
    ;;
esac

RUN_DIR="$ROOT/logs/vins_origin_datasets/${DATASET}_${DURATION}s"
VINS_CONFIG="$RUN_DIR/vins_origin.yaml"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"

cat > "$VINS_CONFIG" <<EOF
%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "$IMU_TOPIC"
image0_topic: "$IMAGE_TOPIC"
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
rosbag play "$BAG" --clock --duration="$DURATION" --quiet
sleep 8

python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
  --vins-csv "$VINS_OUTPUT/vio.csv" \
  --bag "$BAG" \
  --gt-topic "$GT_TOPIC" | tee "$APE_REPORT"

echo "run_dir=$RUN_DIR"
echo "bag=$BAG"
echo "vins_csv=$VINS_OUTPUT/vio.csv"
