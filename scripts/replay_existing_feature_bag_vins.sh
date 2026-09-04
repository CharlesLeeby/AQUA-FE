#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
RUN_DIR="${1:?usage: replay_existing_feature_bag_vins.sh RUN_DIR FEATURE_BAG BASE_VINS_CONFIG BASE_CAMERA_CONFIG GT_TOPIC [PORT]}"
FEATURE_BAG="${2:?missing feature bag}"
BASE_VINS_CONFIG="${3:?missing base VINS config}"
BASE_CAMERA_CONFIG="${4:?missing base camera config}"
GT_TOPIC="${5:?missing GT topic}"
PORT="${6:-15400}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"

if [[ "$VINS_WS" != "/home/ma/SLAM/VINS-Fusion-origin" ]]; then
  echo "refusing non-frozen VINS workspace: $VINS_WS" >&2
  exit 3
fi
for path in "$FEATURE_BAG" "$BASE_VINS_CONFIG" "$BASE_CAMERA_CONFIG"; do
  if [[ ! -s "$path" ]]; then
    echo "missing replay input: $path" >&2
    exit 2
  fi
done

mkdir -p "$RUN_DIR/vins_output"
CAMERA_CONFIG="$RUN_DIR/$(basename "$BASE_CAMERA_CONFIG")"
VINS_CONFIG="$RUN_DIR/vins_replay_external.yaml"
VINS_LOG="$RUN_DIR/vins.log"
ROSCORE_LOG="$RUN_DIR/roscore.log"
cp "$BASE_CAMERA_CONFIG" "$CAMERA_CONFIG"
sed \
  -e 's/^multiple_thread:.*/multiple_thread: 0/' \
  -e "s|^output_path:.*|output_path: \"$RUN_DIR/vins_output\"|" \
  -e "s|^cam0_calib:.*|cam0_calib: \"$(basename "$CAMERA_CONFIG")\"|" \
  "$BASE_VINS_CONFIG" > "$VINS_CONFIG"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost

ROSCORE_PID=""
VINS_PID=""
cleanup() {
  if [[ -n "$VINS_PID" ]]; then
    kill "$VINS_PID" 2>/dev/null || true
    wait "$VINS_PID" 2>/dev/null || true
  fi
  if [[ -n "$ROSCORE_PID" ]]; then
    kill "$ROSCORE_PID" 2>/dev/null || true
    wait "$ROSCORE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

roscore -p "$PORT" > "$ROSCORE_LOG" 2>&1 &
ROSCORE_PID=$!
sleep 3
rosparam set /use_sim_time true
bash "$ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"
rosrun vins vins_node "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
VINS_PID=$!
sleep 4
rosbag play "$FEATURE_BAG" --clock --rate 1.0 --delay 3 --quiet
sleep "$POST_PLAY_SLEEP"
cleanup
VINS_PID=""
ROSCORE_PID=""

VIO_CSV="$RUN_DIR/vins_output/vio.csv"
if [[ -s "$VIO_CSV" ]]; then
  python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
    --vins-csv "$VIO_CSV" \
    --bag "$FEATURE_BAG" --gt-topic "$GT_TOPIC" \
    --vins-log "$VINS_LOG" \
    --rpe-delta-s 1.0 --max-match-dt 0.6 \
    > "$RUN_DIR/ape_strict_dt0p6.txt"
else
  printf 'evaluation_error=empty_vins_trajectory\n' > "$RUN_DIR/ape_strict_dt0p6.txt"
fi
cp "$RUN_DIR/ape_strict_dt0p6.txt" "$RUN_DIR/ape.txt"

{
  echo "run_dir=$RUN_DIR"
  echo "play_bag=$FEATURE_BAG"
  echo "gt_topic=$GT_TOPIC"
  echo "vins_config=$VINS_CONFIG"
  echo "vins_csv=$VIO_CSV"
  echo "provenance=existing_feature_bag_replay"
} > "$RUN_DIR/replay_manifest.txt"

cat "$RUN_DIR/ape_strict_dt0p6.txt"
