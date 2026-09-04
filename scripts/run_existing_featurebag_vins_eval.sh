#!/usr/bin/env bash
set -euo pipefail

# Replay an already exported VINS feature bag against VINS-Fusion.
#
# This is useful for env-locked reproduction when the original raw dataset is
# unavailable or expensive to scan, but the generated feature bag already
# contains IMU and GT topics.

SOURCE_RUN_DIR="${1:?usage: run_existing_featurebag_vins_eval.sh SOURCE_RUN_DIR FEATURE_BAG TAG [GT_TOPIC]}"
FEATURE_BAG="${2:?usage: run_existing_featurebag_vins_eval.sh SOURCE_RUN_DIR FEATURE_BAG TAG [GT_TOPIC]}"
TAG="${3:?usage: run_existing_featurebag_vins_eval.sh SOURCE_RUN_DIR FEATURE_BAG TAG [GT_TOPIC]}"
GT_TOPIC="${4:-/afrl/colmap_gt}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
IMU_TOPIC="${IMU_TOPIC:-/rtimulib_node/imu}"
RUN_DIR="${RUN_DIR:-$ROOT/logs/existing_featurebag_vins/$TAG}"
SOURCE_CONFIG="${SOURCE_CONFIG:-$SOURCE_RUN_DIR/vins_afrl_cave_external.yaml}"
SOURCE_CAMERA_CONFIG="${SOURCE_CAMERA_CONFIG:-$SOURCE_RUN_DIR/afrl_cave_cam0_pinhole.yaml}"
VINS_CONFIG="$RUN_DIR/$(basename "$SOURCE_CONFIG")"
CAMERA_CONFIG="$RUN_DIR/$(basename "$SOURCE_CAMERA_CONFIG")"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
APE_REPORT="$RUN_DIR/ape.txt"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
ROSBAG_WAIT_FOR_SUBSCRIBERS="${ROSBAG_WAIT_FOR_SUBSCRIBERS:-0}"
WAIT_FOR_VINS_SUBSCRIBERS="${WAIT_FOR_VINS_SUBSCRIBERS:-0}"
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT="${WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT:-20}"
PORT="${PORT:-12980}"

if [[ ! -d "$SOURCE_RUN_DIR" ]]; then
  echo "missing SOURCE_RUN_DIR: $SOURCE_RUN_DIR" >&2
  exit 2
fi
if [[ ! -f "$FEATURE_BAG" ]]; then
  echo "missing FEATURE_BAG: $FEATURE_BAG" >&2
  exit 2
fi
if [[ ! -f "$SOURCE_CONFIG" ]]; then
  echo "missing SOURCE_CONFIG: $SOURCE_CONFIG" >&2
  exit 2
fi
if [[ ! -f "$SOURCE_CAMERA_CONFIG" ]]; then
  echo "missing SOURCE_CAMERA_CONFIG: $SOURCE_CAMERA_CONFIG" >&2
  exit 2
fi

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"
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
if re.search(r'^output_path:\s*".*"$', text, flags=re.MULTILINE):
    text = re.sub(r'^output_path:\s*".*"$', replacement, text, flags=re.MULTILINE)
else:
    text += "\n" + replacement + "\n"
target.write_text(text, encoding="utf-8")
PY

SOURCE_METRICS="$SOURCE_RUN_DIR/frontend_metrics.csv"
if [[ -f "$SOURCE_METRICS" ]]; then
  cp "$SOURCE_METRICS" "$RUN_DIR/frontend_metrics.csv"
fi

rm -f "$VINS_OUTPUT/vio.csv" "$VINS_LOG" "$APE_REPORT"

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

PLAY_ARGS=("$FEATURE_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet)
if [[ "$ROSBAG_WAIT_FOR_SUBSCRIBERS" == "1" ]]; then
  PLAY_ARGS+=(--wait-for-subscribers)
fi
rosbag play "${PLAY_ARGS[@]}"
sleep "$POST_PLAY_SLEEP"

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
