#!/usr/bin/env bash
set -euo pipefail

SOURCE_RUN_DIR="${1:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"
FEATURE_BAG="${2:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"
TAG="${3:?usage: $0 SOURCE_RUN_DIR FEATURE_BAG TAG}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:?VINS_WS is required}"
IMU_TOPIC="${IMU_TOPIC:?IMU_TOPIC is required}"
RUN_DIR="${RUN_DIR:?RUN_DIR is required}"
SOURCE_CONFIG="${SOURCE_CONFIG:?SOURCE_CONFIG is required}"
SOURCE_CAMERA_CONFIG="${SOURCE_CAMERA_CONFIG:?SOURCE_CAMERA_CONFIG is required}"
PORT="${PORT:?PORT is required}"
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT="${WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT:-20}"

VINS_CONFIG="$RUN_DIR/$(basename "$SOURCE_CONFIG")"
CAMERA_CONFIG="$RUN_DIR/$(basename "$SOURCE_CAMERA_CONFIG")"
VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
LIFECYCLE="$RUN_DIR/child_lifecycle.txt"
START_RECEIPT="$RUN_DIR/child_start_receipt.txt"

[[ -d "$SOURCE_RUN_DIR" ]] || { echo "missing source run" >&2; exit 2; }
[[ -f "$FEATURE_BAG" && -f "$SOURCE_CONFIG" && -f "$SOURCE_CAMERA_CONFIG" ]] || {
  echo "missing frozen input" >&2
  exit 2
}
[[ ! -e "$VINS_CONFIG" && ! -e "$CAMERA_CONFIG" && ! -e "$VINS_OUTPUT" && ! -e "$VINS_LOG" && ! -e "$LIFECYCLE" && ! -e "$START_RECEIPT" ]] || {
  echo "refusing existing replay output" >&2
  exit 2
}

mkdir -p "$VINS_OUTPUT"
cp "$SOURCE_CAMERA_CONFIG" "$CAMERA_CONFIG"
/usr/bin/python3 - "$SOURCE_CONFIG" "$VINS_CONFIG" "$VINS_OUTPUT" <<'PY'
from pathlib import Path
import re
import sys

source, target, output = map(Path, sys.argv[1:])
text = source.read_text(encoding="utf-8")
text, count = re.subn(
    r'^output_path:\s*".*"$',
    f'output_path: "{output}"',
    text,
    flags=re.MULTILINE,
)
if count != 1:
    raise SystemExit(f"source config output_path count is {count}")
target.write_text(text, encoding="utf-8")
PY

export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost
export ROS_DISTRO="${ROS_DISTRO:-noetic}"
export ROS_VERSION="${ROS_VERSION:-1}"
export ROS_PYTHON_VERSION="${ROS_PYTHON_VERSION:-3}"
source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

ROSCORE_PID=""
VINS_PID=""
cleanup() {
  if [[ -n "$VINS_PID" ]]; then
    if kill -0 "$VINS_PID" 2>/dev/null; then
      kill -KILL "$VINS_PID" 2>/dev/null || true
    fi
    wait "$VINS_PID" 2>/dev/null || true
  fi
  if [[ -n "$ROSCORE_PID" ]]; then
    if kill -0 "$ROSCORE_PID" 2>/dev/null; then
      kill -TERM "$ROSCORE_PID" 2>/dev/null || true
    fi
    wait "$ROSCORE_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

roscore -p "$PORT" > "$RUN_DIR/roscore.log" 2>&1 &
ROSCORE_PID=$!
ROSCORE_PID_RECORDED="$ROSCORE_PID"
ROSCORE_PGID="$(ps -o pgid= -p "$ROSCORE_PID" | tr -d '[:space:]')"
sleep 3
rosparam set /use_sim_time true
bash "$ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"
VINS_EXECUTABLE_EXPECTED="$VINS_WS/devel/lib/vins/vins_node"
"$VINS_EXECUTABLE_EXPECTED" "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
VINS_PID=$!
VINS_PID_RECORDED="$VINS_PID"
VINS_START_TICKS="$(awk '{print $22}' "/proc/$VINS_PID/stat")"
VINS_EXECUTABLE_OBSERVED="$(readlink "/proc/$VINS_PID/exe")"
VINS_COMMAND_OBSERVED="$(tr '\0' ' ' < "/proc/$VINS_PID/cmdline")"
VINS_PGID_START="$(ps -o pgid= -p "$VINS_PID" | tr -d '[:space:]')"
[[ "$VINS_EXECUTABLE_OBSERVED" == "$VINS_EXECUTABLE_EXPECTED" ]]
{
  printf 'schema_version=aqua-fe-fair-stability-vins-child-start-v1\n'
  printf 'tag=%s\n' "$TAG"
  printf 'roscore_pid=%s\n' "$ROSCORE_PID_RECORDED"
  printf 'roscore_pgid=%s\n' "$ROSCORE_PGID"
  printf 'vins_pid=%s\n' "$VINS_PID_RECORDED"
  printf 'vins_start_ticks=%s\n' "$VINS_START_TICKS"
  printf 'vins_pgid_start=%s\n' "$VINS_PGID_START"
  printf 'vins_executable_expected=%s\n' "$VINS_EXECUTABLE_EXPECTED"
  printf 'vins_executable_observed=%s\n' "$VINS_EXECUTABLE_OBSERVED"
  printf 'vins_command_observed=%s\n' "$VINS_COMMAND_OBSERVED"
  printf 'ros_master_uri=%s\n' "$ROS_MASTER_URI"
} > "$START_RECEIPT"
sleep 4

/usr/bin/python3 "$ROOT/scripts/wait_for_ros_subscribers.py" \
  /feature_tracker/feature "$IMU_TOPIC" \
  --timeout "$WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT"

set +e
rosbag play "$FEATURE_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet &
ROSBAG_PID=$!
ROSBAG_START_TICKS="$(awk '{print $22}' "/proc/$ROSBAG_PID/stat")"
wait "$ROSBAG_PID"
ROSBAG_RC=$?
set -e
sleep "$POST_PLAY_SLEEP"

BAG_END_VINS_ALIVE=0
BAG_END_VINS_STATE="$(ps -o stat= -p "$VINS_PID" 2>/dev/null | awk '{print $1}')"
BAG_END_VINS_START_TICKS="$(awk '{print $22}' "/proc/$VINS_PID/stat" 2>/dev/null || true)"
BAG_END_VINS_EXECUTABLE="$(readlink "/proc/$VINS_PID/exe" 2>/dev/null || true)"
BAG_END_VINS_PGID="$(ps -o pgid= -p "$VINS_PID" 2>/dev/null | tr -d '[:space:]')"
BAG_END_VINS_IDENTITY_MATCH=0
if [[ "$BAG_END_VINS_START_TICKS" == "$VINS_START_TICKS" && "$BAG_END_VINS_EXECUTABLE" == "$VINS_EXECUTABLE_EXPECTED" && "$BAG_END_VINS_PGID" == "$VINS_PGID_START" ]]; then
  BAG_END_VINS_IDENTITY_MATCH=1
fi
if [[ -n "$BAG_END_VINS_STATE" && "$BAG_END_VINS_STATE" != Z* ]]; then
  BAG_END_VINS_ALIVE=1
fi
OUTPUT_NONEMPTY=0
if [[ -s "$VINS_OUTPUT/vio.csv" ]]; then
  OUTPUT_NONEMPTY=1
fi

VINS_SIGNAL_SENT=0
VINS_WAIT_RC=0
VINS_EARLY_EXIT=0
if [[ "$BAG_END_VINS_ALIVE" == "1" ]]; then
  kill -TERM "$VINS_PID"
  VINS_SIGNAL_SENT=15
  set +e
  wait "$VINS_PID"
  VINS_WAIT_RC=$?
  set -e
else
  VINS_EARLY_EXIT=1
  set +e
  wait "$VINS_PID"
  VINS_WAIT_RC=$?
  set -e
fi
VINS_PID=""

set +e
kill -TERM "$ROSCORE_PID" 2>/dev/null
ROSCORE_KILL_RC=$?
wait "$ROSCORE_PID"
ROSCORE_WAIT_RC=$?
set -e
ROSCORE_PID=""

{
  printf 'schema_version=aqua-fe-fair-stability-vins-child-lifecycle-v1\n'
  printf 'tag=%s\n' "$TAG"
  printf 'roscore_pid=%s\n' "$ROSCORE_PID_RECORDED"
  printf 'roscore_pgid=%s\n' "$ROSCORE_PGID"
  printf 'vins_pid=%s\n' "$VINS_PID_RECORDED"
  printf 'vins_start_ticks=%s\n' "$VINS_START_TICKS"
  printf 'vins_pgid_start=%s\n' "$VINS_PGID_START"
  printf 'vins_executable_expected=%s\n' "$VINS_EXECUTABLE_EXPECTED"
  printf 'vins_executable_observed=%s\n' "$VINS_EXECUTABLE_OBSERVED"
  printf 'vins_command_observed=%s\n' "$VINS_COMMAND_OBSERVED"
  printf 'rosbag_pid=%s\n' "$ROSBAG_PID"
  printf 'rosbag_start_ticks=%s\n' "$ROSBAG_START_TICKS"
  printf 'rosbag_returncode=%s\n' "$ROSBAG_RC"
  printf 'bag_end_vins_alive=%s\n' "$BAG_END_VINS_ALIVE"
  printf 'bag_end_vins_state=%s\n' "$BAG_END_VINS_STATE"
  printf 'bag_end_vins_start_ticks=%s\n' "$BAG_END_VINS_START_TICKS"
  printf 'bag_end_vins_executable=%s\n' "$BAG_END_VINS_EXECUTABLE"
  printf 'bag_end_vins_pgid=%s\n' "$BAG_END_VINS_PGID"
  printf 'bag_end_vins_identity_match=%s\n' "$BAG_END_VINS_IDENTITY_MATCH"
  printf 'output_nonempty=%s\n' "$OUTPUT_NONEMPTY"
  printf 'vins_signal_sent=%s\n' "$VINS_SIGNAL_SENT"
  printf 'vins_wait_returncode=%s\n' "$VINS_WAIT_RC"
  printf 'vins_early_exit=%s\n' "$VINS_EARLY_EXIT"
  printf 'roscore_kill_returncode=%s\n' "$ROSCORE_KILL_RC"
  printf 'roscore_wait_returncode=%s\n' "$ROSCORE_WAIT_RC"
  printf 'expected_vins_wait_returncode=143\n'
  printf 'descendant_residual_check=DELEGATED_TO_PARENT_PROCESS_GROUP\n'
} > "$LIFECYCLE"

[[ "$ROSBAG_RC" == "0" ]]
[[ "$BAG_END_VINS_ALIVE" == "1" ]]
[[ "$BAG_END_VINS_IDENTITY_MATCH" == "1" ]]
[[ "$OUTPUT_NONEMPTY" == "1" ]]
[[ "$VINS_SIGNAL_SENT" == "15" ]]
[[ "$VINS_WAIT_RC" == "143" ]]

{
  printf 'run_dir=%s\n' "$RUN_DIR"
  printf 'play_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'vins_config=%s\n' "$VINS_CONFIG"
  printf 'vins_csv=%s\n' "$VINS_OUTPUT/vio.csv"
  printf 'tag=%s\n' "$TAG"
  printf 'accuracy_evaluator_started=0\n'
  printf 'shutdown_contract=EXPECTED_BAG_END_SIGTERM_REAP\n'
} > "$RUN_DIR/replay_manifest.txt"
