#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
RAW_BAG="${RAW_BAG:-$ROOT/datasets/aqualoc/rosbags/harbor07_1660_1950.bag}"
OUT_ROOT="${OUT_ROOT:-$ROOT/logs/agent_qi_backend_calibration}"

IMAGE_TOPIC="${IMAGE_TOPIC:-/camera/image_raw}"
IMU_TOPIC="${IMU_TOPIC:-/rtimulib_node/imu}"
GT_TOPIC="${GT_TOPIC:-/aqualoc/colmap_gt}"
FEATURE_TOPIC="${FEATURE_TOPIC:-/feature_tracker/feature}"

METHOD="${METHOD:-klt}"
EVERY_N="${EVERY_N:-2}"
DURATION="${DURATION:-10.0}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
FRAME_OFFSET="${FRAME_OFFSET:-1}"
PREPROCESS="${PREPROCESS:-adaptive_clahe}"
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-0}"
SCHEDULES="${SCHEDULES:-constq raw blend0.5 blend0.7 blend0.85 clamp0.6 clamp0.8}"
PORT_BASE="${PORT_BASE:-11451}"
KEEP_BAGS="${KEEP_BAGS:-0}"
RUN_VINS="${RUN_VINS:-0}"

SOURCE_DIR="$OUT_ROOT/h07_1660_1950_source"
SOURCE_BAG="$SOURCE_DIR/features_raw_source.bag"
SOURCE_METRICS="$SOURCE_DIR/frontend_metrics.csv"
SOURCE_CAMERA="$SOURCE_DIR/aqualoc_harbor07_kannala.yaml"

if [[ ! -f "$RAW_BAG" ]]; then
  echo "missing input bag: $RAW_BAG" >&2
  exit 1
fi

mkdir -p "$SOURCE_DIR"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

write_camera_config() {
  local path="$1"
  cat > "$path" <<'EOF'
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
}

write_vins_config() {
  local path="$1"
  local camera_config="$2"
  local vins_output="$3"
  cat > "$path" <<EOF
%YAML:1.0

imu: 1
num_of_cam: 1
multiple_thread: 1

imu_topic: "$IMU_TOPIC"
image0_topic: "/unused/image"
image1_topic: ""
output_path: "$vins_output"

image_width: 640
image_height: 512
cam0_calib: "$(basename "$camera_config")"

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
}

port_is_busy() {
  local port="$1"
  ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${port}$"
}

next_free_port() {
  local port="$1"
  while port_is_busy "$port"; do
    port=$((port + 1))
  done
  echo "$port"
}

export_source_bag() {
  write_camera_config "$SOURCE_CAMERA"
  if [[ -f "$SOURCE_BAG" ]]; then
    echo "reusing source feature bag: $SOURCE_BAG"
    return
  fi
  local selection_flag=()
  if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
    selection_flag=(--measurement-selection)
  fi
  echo "exporting raw-q source feature bag: $SOURCE_BAG"
  python3 -m uw_frontend.ros.export_vins_features \
    --bag "$RAW_BAG" \
    --image-topic "$IMAGE_TOPIC" \
    --camera-config "$SOURCE_CAMERA" \
    --output-bag "$SOURCE_BAG" \
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
    --metrics-csv "$SOURCE_METRICS" \
    --process-skipped-frames \
    --raw-quality-to-backend \
    "${selection_flag[@]}"
}

run_schedule() {
  local schedule="$1"
  local index="$2"
  local run_dir="$OUT_ROOT/h07_1660_1950_${schedule}"
  local feature_bag="$run_dir/features_${schedule}.bag"
  local camera_config="$run_dir/aqualoc_harbor07_kannala.yaml"
  local vins_config="$run_dir/vins_external_features.yaml"
  local vins_output="$run_dir/vins_output"
  local vins_log="$run_dir/vins.log"
  local ape_report="$run_dir/ape.txt"
  local eval_err="$run_dir/eval.err"
  local port

  mkdir -p "$run_dir" "$vins_output"
  write_camera_config "$camera_config"
  write_vins_config "$vins_config" "$camera_config" "$vins_output"

  python3 "$ROOT/scripts/agent_qi_calibration_rewrite_bag.py" \
    --input-bag "$SOURCE_BAG" \
    --output-bag "$feature_bag" \
    --schedule "$schedule" \
    --feature-topic "$FEATURE_TOPIC" \
    --stats-csv "$run_dir/bag_stats.csv"

  rm -f "$vins_output/vio.csv" "$vins_log" "$ape_report" "$eval_err"
  if [[ "$RUN_VINS" != "1" ]]; then
    echo "RUN_VINS=0, skipping VINS for $schedule"
    rm -f "$feature_bag"
    return
  fi

  port="$(next_free_port "$((PORT_BASE + index))")"
  echo "running VINS for $schedule on ROS port $port"
  export ROS_MASTER_URI="http://localhost:$port"
  export ROS_HOSTNAME=localhost

  roscore -p "$port" > "$run_dir/roscore.log" 2>&1 &
  local roscore_pid=$!
  local vins_pid=""
  cleanup_schedule() {
    if [[ -n "${vins_pid:-}" ]]; then
      kill "$vins_pid" 2>/dev/null || true
      wait "$vins_pid" 2>/dev/null || true
    fi
    kill "$roscore_pid" 2>/dev/null || true
    wait "$roscore_pid" 2>/dev/null || true
  }
  trap cleanup_schedule RETURN

  sleep 3
  rosparam set /use_sim_time true
  rosrun vins vins_node "$vins_config" > "$vins_log" 2>&1 &
  vins_pid=$!
  sleep 4
  rosbag play "$feature_bag" --clock --quiet
  sleep 8

  if ! python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
    --vins-csv "$vins_output/vio.csv" \
    --bag "$feature_bag" \
    --gt-topic "$GT_TOPIC" \
    --vins-log "$vins_log" > "$ape_report" 2> "$eval_err"; then
    {
      echo "evaluation_failed=1"
      echo "evaluation_error=$(tr '\n' ' ' < "$eval_err")"
    } >> "$ape_report"
  fi

  if [[ "$KEEP_BAGS" != "1" ]]; then
    rm -f "$feature_bag"
  fi
}

export_source_bag

idx=0
for schedule in $SCHEDULES; do
  run_schedule "$schedule" "$idx"
  idx=$((idx + 1))
done

python3 "$ROOT/scripts/agent_qi_calibration_report.py" --out-dir "$OUT_ROOT"

if [[ "$KEEP_BAGS" != "1" ]]; then
  rm -f "$SOURCE_BAG"
fi

echo "calibration artifacts: $OUT_ROOT"
