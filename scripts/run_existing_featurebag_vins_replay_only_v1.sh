#!/usr/bin/env bash
set -euo pipefail

# Replay one already-exported feature bag through VINS-Fusion without invoking any
# accuracy evaluator. The caller must provide a new RUN_DIR and isolated ROS port.

SOURCE_RUN_DIR="${1:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"
FEATURE_BAG="${2:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"
TAG="${3:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
IMU_TOPIC="${IMU_TOPIC:-/rtimulib_node/imu}"
RUN_DIR="${RUN_DIR:?RUN_DIR must name a new supervised output directory}"
SOURCE_CONFIG="${SOURCE_CONFIG:?SOURCE_CONFIG is required}"
SOURCE_CAMERA_CONFIG="${SOURCE_CAMERA_CONFIG:?SOURCE_CAMERA_CONFIG is required}"
VINS_CONFIG="$RUN_DIR/$(basename "$SOURCE_CONFIG")"
CAMERA_CONFIG="$RUN_DIR/$(basename "$SOURCE_CAMERA_CONFIG")"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
WAIT_FOR_VINS_SUBSCRIBERS="${WAIT_FOR_VINS_SUBSCRIBERS:-1}"
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT="${WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT:-20}"
PORT="${PORT:?PORT is required}"

[[ -d "$SOURCE_RUN_DIR" ]] || { echo "missing SOURCE_RUN_DIR: $SOURCE_RUN_DIR" >&2; exit 2; }
[[ -f "$FEATURE_BAG" ]] || { echo "missing FEATURE_BAG: $FEATURE_BAG" >&2; exit 2; }
[[ -f "$SOURCE_CONFIG" ]] || { echo "missing SOURCE_CONFIG: $SOURCE_CONFIG" >&2; exit 2; }
[[ -f "$SOURCE_CAMERA_CONFIG" ]] || {
  echo "missing SOURCE_CAMERA_CONFIG: $SOURCE_CAMERA_CONFIG" >&2
  exit 2
}
[[ ! -e "$VINS_CONFIG" && ! -e "$CAMERA_CONFIG" && ! -e "$VINS_OUTPUT" && ! -e "$VINS_LOG" ]] || {
  echo "refusing existing replay output in $RUN_DIR" >&2
  exit 2
}

mkdir -p "$VINS_OUTPUT"
cp "$SOURCE_CAMERA_CONFIG" "$CAMERA_CONFIG"
python3 - "$SOURCE_CONFIG" "$VINS_CONFIG" "$VINS_OUTPUT" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
output = Path(sys.argv[3])
text = source.read_text(encoding="utf-8")
replacement = f'output_path: "{output}"'
if not re.search(r'^output_path:\s*".*"$', text, flags=re.MULTILINE):
    raise SystemExit("source config has no unique output_path")
text, count = re.subn(
    r'^output_path:\s*".*"$', replacement, text, flags=re.MULTILINE
)
if count != 1:
    raise SystemExit(f"source config output_path count is {count}")
target.write_text(text, encoding="utf-8")
PY

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
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

if [[ "$WAIT_FOR_VINS_SUBSCRIBERS" == "1" ]]; then
  python3 "$ROOT/scripts/wait_for_ros_subscribers.py" \
    /feature_tracker/feature "$IMU_TOPIC" \
    --timeout "$WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT"
fi

rosbag play "$FEATURE_BAG" \
  --clock \
  --rate "$PLAY_RATE" \
  --delay "$ROSBAG_PLAY_DELAY" \
  --quiet
sleep "$POST_PLAY_SLEEP"

kill -0 "$VINS_PID"
[[ -s "$VINS_OUTPUT/vio.csv" ]] || {
  echo "VINS produced no trajectory" >&2
  exit 3
}

{
  printf 'run_dir=%s\n' "$RUN_DIR"
  printf 'play_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'vins_config=%s\n' "$VINS_CONFIG"
  printf 'vins_csv=%s\n' "$VINS_OUTPUT/vio.csv"
  printf 'tag=%s\n' "$TAG"
  printf 'accuracy_evaluator_started=0\n'
} > "$RUN_DIR/replay_manifest.txt"
