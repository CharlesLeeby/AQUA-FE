#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
RUN_DIR="${1:?usage: $0 RUN_DIR FEATURE_BAG PORT}"
FEATURE_BAG="${2:?usage: $0 RUN_DIR FEATURE_BAG PORT}"
PORT="${3:?usage: $0 RUN_DIR FEATURE_BAG PORT}"

GT_TOPIC="/aqualoc/colmap_gt"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"
CAMERA_CONFIG="$RUN_DIR/aqualoc_harbor07_kannala.yaml"
VINS_CONFIG="$RUN_DIR/vins_external_features.yaml"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ ! -f "$CAMERA_CONFIG" ]]; then
  cp "$ROOT/logs/agent_qi_vins/h07_1660_1950_q/aqualoc_harbor07_kannala.yaml" "$CAMERA_CONFIG"
fi

cat > "$VINS_CONFIG" <<EOF
%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "/rtimulib_node/imu"
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

{
  echo "run_dir=$RUN_DIR"
  echo "play_bag=$FEATURE_BAG"
  echo "feature_bag=$FEATURE_BAG"
  echo "vins_config=$VINS_CONFIG"
  echo "vins_csv=$VINS_OUTPUT/vio.csv"
} | tee "$RUN_DIR/replay_manifest.txt"
