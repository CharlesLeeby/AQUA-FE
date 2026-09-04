#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

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
EXPERIMENT_ID="${EXPERIMENT_ID:?EXPERIMENT_ID is required}"
[[ "$EXPERIMENT_ID" == "fair-stability-positive-roster-openloop-runtimeexcl-v12" ]] || {
  echo "unexpected experiment namespace" >&2
  exit 2
}
PLAY_RATE="${PLAY_RATE:-1.0}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT="${WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT:-20}"

VINS_CONFIG="$RUN_DIR/vins_runtime_config.yaml"
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
cp -- "$SOURCE_CAMERA_CONFIG" "$CAMERA_CONFIG"
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

# Bind the camera YAML that the estimator will actually resolve beside the
# generated VINS YAML, rather than proving only its frozen source.
SOURCE_CAMERA_CONFIG_SIZE_BYTES="$(stat -c '%s' -- "$SOURCE_CAMERA_CONFIG")"
SOURCE_CAMERA_CONFIG_SHA256="$(sha256sum -- "$SOURCE_CAMERA_CONFIG")"
SOURCE_CAMERA_CONFIG_SHA256="${SOURCE_CAMERA_CONFIG_SHA256%% *}"
CAMERA_CONFIG_SIZE_BYTES="$(stat -c '%s' -- "$CAMERA_CONFIG")"
CAMERA_CONFIG_SHA256="$(sha256sum -- "$CAMERA_CONFIG")"
CAMERA_CONFIG_SHA256="${CAMERA_CONFIG_SHA256%% *}"
[[ "$SOURCE_CAMERA_CONFIG_SIZE_BYTES" == "$CAMERA_CONFIG_SIZE_BYTES" ]]
[[ "$SOURCE_CAMERA_CONFIG_SHA256" == "$CAMERA_CONFIG_SHA256" ]]
cmp -s -- "$SOURCE_CAMERA_CONFIG" "$CAMERA_CONFIG"

export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost
export ROS_DISTRO="${ROS_DISTRO:-noetic}"
export ROS_VERSION="${ROS_VERSION:-1}"
export ROS_PYTHON_VERSION="${ROS_PYTHON_VERSION:-3}"
source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

proc_start_ticks() {
  awk '{print $22}' "/proc/$1/stat" 2>/dev/null || true
}

proc_state() {
  awk '{print $3}' "/proc/$1/stat" 2>/dev/null || true
}

proc_pgid() {
  ps -o pgid= -p "$1" 2>/dev/null | tr -d '[:space:]'
}

proc_executable() {
  readlink "/proc/$1/exe" 2>/dev/null || true
}

exact_live_pid() {
  local pid="$1" start="$2" executable="$3" pgid="$4" state
  state="$(proc_state "$pid")"
  [[ -n "$state" && "$state" != Z* \
    && "$(proc_start_ticks "$pid")" == "$start" \
    && "$(proc_executable "$pid")" == "$executable" \
    && "$(proc_pgid "$pid")" == "$pgid" ]]
}

WAIT_RC=0
WAIT_REAPED=0
WAIT_FORCED_KILL=0
wait_after_signal() {
  local pid="$1" start="$2" executable="$3" pgid="$4" deadline
  deadline=$((SECONDS + 15))
  WAIT_FORCED_KILL=0
  while exact_live_pid "$pid" "$start" "$executable" "$pgid" && (( SECONDS < deadline )); do
    sleep 0.1
  done
  if exact_live_pid "$pid" "$start" "$executable" "$pgid"; then
    kill -KILL "$pid" 2>/dev/null || true
    WAIT_FORCED_KILL=1
  fi
  set +e
  wait "$pid"
  WAIT_RC=$?
  set -e
  WAIT_REAPED=1
}

scan_group_residuals() {
  local proc_path pid stat_line stat_tail state ppid pgid entry
  DESCENDANT_RESIDUALS=""
  DESCENDANT_RESIDUAL_COUNT=0
  for proc_path in /proc/[0-9]*; do
    [[ -r "$proc_path/stat" ]] || continue
    IFS= read -r stat_line < "$proc_path/stat" || continue
    pid="${proc_path#/proc/}"
    [[ "$pid" == "$WRAPPER_PID" ]] && continue
    stat_tail="${stat_line##*) }"
    [[ "$stat_tail" != "$stat_line" ]] || continue
    read -r state ppid pgid _ <<< "$stat_tail" || continue
    [[ "$pgid" == "$WRAPPER_PGID" ]] || continue
    entry="${pid}:${state}"
    if [[ -n "$DESCENDANT_RESIDUALS" ]]; then
      DESCENDANT_RESIDUALS+=",${entry}"
    else
      DESCENDANT_RESIDUALS="$entry"
    fi
    ((DESCENDANT_RESIDUAL_COUNT += 1))
  done
}

WRAPPER_PID="$$"
WRAPPER_START_TICKS="$(proc_start_ticks "$WRAPPER_PID")"
WRAPPER_PGID="$(proc_pgid "$WRAPPER_PID")"
ROSCORE_PID=""
ROSCORE_PID_RECORDED=""
ROSCORE_START_TICKS=""
ROSCORE_EXECUTABLE=""
ROSCORE_COMMAND=""
ROSCORE_PGID=""
ROSCORE_END_START_TICKS=""
ROSCORE_END_EXECUTABLE=""
ROSCORE_END_PGID=""
ROSCORE_IDENTITY_MATCH=0
ROSCORE_KILL_RC=999
ROSCORE_WAIT_RC=999
ROSCORE_REAPED=0
ROSCORE_FORCED_KILL=0
VINS_PID=""
VINS_PID_RECORDED=""
VINS_START_TICKS=""
VINS_EXECUTABLE_EXPECTED="$VINS_WS/devel/lib/vins/vins_node"
VINS_EXECUTABLE_OBSERVED=""
VINS_COMMAND_OBSERVED=""
VINS_PGID_START=""
VINS_SIGNAL_SENT=0
VINS_WAIT_RC=999
VINS_REAPED=0
VINS_FORCED_KILL=0
VINS_EARLY_EXIT=0
ROSBAG_PID=""
ROSBAG_START_TICKS=""
ROSBAG_RC=999
ROSBAG_REAPED=0
BAG_END_VINS_ALIVE=0
BAG_END_VINS_STATE=""
BAG_END_VINS_START_TICKS=""
BAG_END_VINS_EXECUTABLE=""
BAG_END_VINS_PGID=""
BAG_END_VINS_IDENTITY_MATCH=0
OUTPUT_NONEMPTY=0
DESCENDANT_RESIDUALS=""
DESCENDANT_RESIDUAL_COUNT=0
LAUNCH_CHECKPOINT="PRESTART"
LIFECYCLE_WRITTEN=0

write_lifecycle() {
  [[ "$LIFECYCLE_WRITTEN" == "0" && ! -e "$LIFECYCLE" ]] || return 0
  scan_group_residuals
  {
    printf 'schema_version=aqua-fe-fair-stability-vins-child-lifecycle-v12\n'
    printf 'experiment_id=%s\n' "$EXPERIMENT_ID"
    printf 'tag=%s\n' "$TAG"
    printf 'launch_checkpoint=%s\n' "$LAUNCH_CHECKPOINT"
    printf 'wrapper_pid=%s\n' "$WRAPPER_PID"
    printf 'wrapper_start_ticks=%s\n' "$WRAPPER_START_TICKS"
    printf 'wrapper_pgid=%s\n' "$WRAPPER_PGID"
    printf 'roscore_pid=%s\n' "$ROSCORE_PID_RECORDED"
    printf 'roscore_start_ticks=%s\n' "$ROSCORE_START_TICKS"
    printf 'roscore_executable=%s\n' "$ROSCORE_EXECUTABLE"
    printf 'roscore_command=%s\n' "$ROSCORE_COMMAND"
    printf 'roscore_pgid=%s\n' "$ROSCORE_PGID"
    printf 'roscore_end_start_ticks=%s\n' "$ROSCORE_END_START_TICKS"
    printf 'roscore_end_executable=%s\n' "$ROSCORE_END_EXECUTABLE"
    printf 'roscore_end_pgid=%s\n' "$ROSCORE_END_PGID"
    printf 'roscore_identity_match=%s\n' "$ROSCORE_IDENTITY_MATCH"
    printf 'vins_pid=%s\n' "$VINS_PID_RECORDED"
    printf 'vins_start_ticks=%s\n' "$VINS_START_TICKS"
    printf 'vins_pgid_start=%s\n' "$VINS_PGID_START"
    printf 'vins_executable_expected=%s\n' "$VINS_EXECUTABLE_EXPECTED"
    printf 'vins_executable_observed=%s\n' "$VINS_EXECUTABLE_OBSERVED"
    printf 'vins_command_observed=%s\n' "$VINS_COMMAND_OBSERVED"
    printf 'rosbag_pid=%s\n' "$ROSBAG_PID"
    printf 'rosbag_start_ticks=%s\n' "$ROSBAG_START_TICKS"
    printf 'rosbag_returncode=%s\n' "$ROSBAG_RC"
    printf 'rosbag_reaped=%s\n' "$ROSBAG_REAPED"
    printf 'bag_end_vins_alive=%s\n' "$BAG_END_VINS_ALIVE"
    printf 'bag_end_vins_state=%s\n' "$BAG_END_VINS_STATE"
    printf 'bag_end_vins_start_ticks=%s\n' "$BAG_END_VINS_START_TICKS"
    printf 'bag_end_vins_executable=%s\n' "$BAG_END_VINS_EXECUTABLE"
    printf 'bag_end_vins_pgid=%s\n' "$BAG_END_VINS_PGID"
    printf 'bag_end_vins_identity_match=%s\n' "$BAG_END_VINS_IDENTITY_MATCH"
    printf 'output_nonempty=%s\n' "$OUTPUT_NONEMPTY"
    printf 'vins_signal_sent=%s\n' "$VINS_SIGNAL_SENT"
    printf 'vins_wait_returncode=%s\n' "$VINS_WAIT_RC"
    printf 'vins_reaped=%s\n' "$VINS_REAPED"
    printf 'vins_forced_kill=%s\n' "$VINS_FORCED_KILL"
    printf 'vins_early_exit=%s\n' "$VINS_EARLY_EXIT"
    printf 'roscore_kill_returncode=%s\n' "$ROSCORE_KILL_RC"
    printf 'roscore_wait_returncode=%s\n' "$ROSCORE_WAIT_RC"
    printf 'roscore_reaped=%s\n' "$ROSCORE_REAPED"
    printf 'roscore_forced_kill=%s\n' "$ROSCORE_FORCED_KILL"
    printf 'expected_vins_wait_returncode=143\n'
    printf 'descendant_residual_count=%s\n' "$DESCENDANT_RESIDUAL_COUNT"
    printf 'descendant_residual_pids=%s\n' "$DESCENDANT_RESIDUALS"
  } > "$LIFECYCLE"
  LIFECYCLE_WRITTEN=1
}

cleanup() {
  local original_rc=$?
  trap - EXIT TERM INT
  set +e
  if [[ -n "$ROSBAG_PID" && "$ROSBAG_REAPED" == "0" ]]; then
    kill -TERM "$ROSBAG_PID" 2>/dev/null || true
    wait "$ROSBAG_PID" 2>/dev/null
    ROSBAG_RC=$?
    ROSBAG_REAPED=1
  fi
  if [[ -n "$VINS_PID" && "$VINS_REAPED" == "0" ]]; then
    if exact_live_pid "$VINS_PID" "$VINS_START_TICKS" "$VINS_EXECUTABLE_EXPECTED" "$VINS_PGID_START"; then
      kill -TERM "$VINS_PID" 2>/dev/null || true
      VINS_SIGNAL_SENT=15
    else
      VINS_EARLY_EXIT=1
    fi
    wait_after_signal "$VINS_PID" "$VINS_START_TICKS" "$VINS_EXECUTABLE_EXPECTED" "$VINS_PGID_START"
    VINS_WAIT_RC="$WAIT_RC"
    VINS_REAPED="$WAIT_REAPED"
    VINS_FORCED_KILL="$WAIT_FORCED_KILL"
  fi
  if [[ -n "$ROSCORE_PID" && "$ROSCORE_REAPED" == "0" ]]; then
    if exact_live_pid "$ROSCORE_PID" "$ROSCORE_START_TICKS" "$ROSCORE_EXECUTABLE" "$ROSCORE_PGID"; then
      kill -TERM "$ROSCORE_PID" 2>/dev/null
      ROSCORE_KILL_RC=$?
    fi
    wait_after_signal "$ROSCORE_PID" "$ROSCORE_START_TICKS" "$ROSCORE_EXECUTABLE" "$ROSCORE_PGID"
    ROSCORE_WAIT_RC="$WAIT_RC"
    ROSCORE_REAPED="$WAIT_REAPED"
    ROSCORE_FORCED_KILL="$WAIT_FORCED_KILL"
  fi
  write_lifecycle
  exit "$original_rc"
}
trap 'exit 143' TERM
trap 'exit 130' INT
trap cleanup EXIT

/usr/bin/python3 /opt/ros/noetic/bin/roscore -p "$PORT" \
  > "$RUN_DIR/roscore.log" 2>&1 &
ROSCORE_PID=$!
ROSCORE_PID_RECORDED="$ROSCORE_PID"
LAUNCH_CHECKPOINT="ROSCORE_STARTED"
for _ in {1..100}; do
  ROSCORE_START_TICKS="$(proc_start_ticks "$ROSCORE_PID")"
  ROSCORE_EXECUTABLE="$(proc_executable "$ROSCORE_PID")"
  ROSCORE_COMMAND="$(tr '\0' ' ' < "/proc/$ROSCORE_PID/cmdline" 2>/dev/null || true)"
  ROSCORE_PGID="$(proc_pgid "$ROSCORE_PID")"
  [[ -n "$ROSCORE_START_TICKS" && -n "$ROSCORE_EXECUTABLE" \
    && "$ROSCORE_COMMAND" == *roscore* \
    && "$ROSCORE_PGID" == "$WRAPPER_PGID" ]] && break
  sleep 0.02
done
[[ -n "$ROSCORE_START_TICKS" && -n "$ROSCORE_EXECUTABLE" ]]
[[ "$ROSCORE_PGID" == "$WRAPPER_PGID" ]]
sleep 3
rosparam set /use_sim_time true
bash "$ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"

# Recheck at the final pre-launch boundary, after environment recording.
SOURCE_CAMERA_CONFIG_SIZE_BYTES="$(stat -c '%s' -- "$SOURCE_CAMERA_CONFIG")"
SOURCE_CAMERA_CONFIG_SHA256="$(sha256sum -- "$SOURCE_CAMERA_CONFIG")"
SOURCE_CAMERA_CONFIG_SHA256="${SOURCE_CAMERA_CONFIG_SHA256%% *}"
CAMERA_CONFIG_SIZE_BYTES="$(stat -c '%s' -- "$CAMERA_CONFIG")"
CAMERA_CONFIG_SHA256="$(sha256sum -- "$CAMERA_CONFIG")"
CAMERA_CONFIG_SHA256="${CAMERA_CONFIG_SHA256%% *}"
[[ "$SOURCE_CAMERA_CONFIG_SIZE_BYTES" == "$CAMERA_CONFIG_SIZE_BYTES" ]]
[[ "$SOURCE_CAMERA_CONFIG_SHA256" == "$CAMERA_CONFIG_SHA256" ]]
cmp -s -- "$SOURCE_CAMERA_CONFIG" "$CAMERA_CONFIG"

"$VINS_EXECUTABLE_EXPECTED" "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
VINS_PID=$!
VINS_PID_RECORDED="$VINS_PID"
LAUNCH_CHECKPOINT="VINS_STARTED"
for _ in {1..100}; do
  VINS_START_TICKS="$(proc_start_ticks "$VINS_PID")"
  VINS_EXECUTABLE_OBSERVED="$(proc_executable "$VINS_PID")"
  VINS_PGID_START="$(proc_pgid "$VINS_PID")"
  [[ "$VINS_EXECUTABLE_OBSERVED" == "$VINS_EXECUTABLE_EXPECTED" \
    && "$VINS_PGID_START" == "$WRAPPER_PGID" ]] && break
  sleep 0.02
done
VINS_COMMAND_OBSERVED="$(tr '\0' ' ' < "/proc/$VINS_PID/cmdline")"
[[ -n "$VINS_START_TICKS" ]]
[[ "$VINS_EXECUTABLE_OBSERVED" == "$VINS_EXECUTABLE_EXPECTED" ]]
[[ "$VINS_PGID_START" == "$WRAPPER_PGID" ]]
{
  printf 'schema_version=aqua-fe-fair-stability-vins-child-start-v12\n'
  printf 'experiment_id=%s\n' "$EXPERIMENT_ID"
  printf 'tag=%s\n' "$TAG"
  printf 'wrapper_pid=%s\n' "$WRAPPER_PID"
  printf 'wrapper_start_ticks=%s\n' "$WRAPPER_START_TICKS"
  printf 'wrapper_pgid=%s\n' "$WRAPPER_PGID"
  printf 'roscore_pid=%s\n' "$ROSCORE_PID_RECORDED"
  printf 'roscore_start_ticks=%s\n' "$ROSCORE_START_TICKS"
  printf 'roscore_executable=%s\n' "$ROSCORE_EXECUTABLE"
  printf 'roscore_command=%s\n' "$ROSCORE_COMMAND"
  printf 'roscore_pgid=%s\n' "$ROSCORE_PGID"
  printf 'vins_pid=%s\n' "$VINS_PID_RECORDED"
  printf 'vins_start_ticks=%s\n' "$VINS_START_TICKS"
  printf 'vins_pgid_start=%s\n' "$VINS_PGID_START"
  printf 'vins_executable_expected=%s\n' "$VINS_EXECUTABLE_EXPECTED"
  printf 'vins_executable_observed=%s\n' "$VINS_EXECUTABLE_OBSERVED"
  printf 'vins_command_observed=%s\n' "$VINS_COMMAND_OBSERVED"
  printf 'source_camera_config=%s\n' "$SOURCE_CAMERA_CONFIG"
  printf 'runtime_camera_config=%s\n' "$CAMERA_CONFIG"
  printf 'runtime_camera_config_size_bytes=%s\n' "$CAMERA_CONFIG_SIZE_BYTES"
  printf 'runtime_camera_config_sha256=%s\n' "$CAMERA_CONFIG_SHA256"
  printf 'runtime_camera_config_matches_source=1\n'
  printf 'ros_master_uri=%s\n' "$ROS_MASTER_URI"
} > "$START_RECEIPT"
sleep 4

/usr/bin/python3 "$ROOT/scripts/wait_for_ros_subscribers.py" \
  /feature_tracker/feature "$IMU_TOPIC" \
  --timeout "$WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT"
LAUNCH_CHECKPOINT="SUBSCRIBERS_READY"

rosbag play "$FEATURE_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet &
ROSBAG_PID=$!
ROSBAG_START_TICKS="$(proc_start_ticks "$ROSBAG_PID")"
LAUNCH_CHECKPOINT="ROSBAG_STARTED"
set +e
wait "$ROSBAG_PID"
ROSBAG_RC=$?
set -e
ROSBAG_REAPED=1
LAUNCH_CHECKPOINT="BAG_ENDED"
sleep "$POST_PLAY_SLEEP"

BAG_END_VINS_STATE="$(proc_state "$VINS_PID")"
BAG_END_VINS_START_TICKS="$(proc_start_ticks "$VINS_PID")"
BAG_END_VINS_EXECUTABLE="$(proc_executable "$VINS_PID")"
BAG_END_VINS_PGID="$(proc_pgid "$VINS_PID")"
if [[ "$BAG_END_VINS_START_TICKS" == "$VINS_START_TICKS" \
  && "$BAG_END_VINS_EXECUTABLE" == "$VINS_EXECUTABLE_EXPECTED" \
  && "$BAG_END_VINS_PGID" == "$VINS_PGID_START" ]]; then
  BAG_END_VINS_IDENTITY_MATCH=1
fi
if [[ -n "$BAG_END_VINS_STATE" && "$BAG_END_VINS_STATE" != Z* ]]; then
  BAG_END_VINS_ALIVE=1
fi
[[ -s "$VINS_OUTPUT/vio.csv" ]] && OUTPUT_NONEMPTY=1

if [[ "$BAG_END_VINS_ALIVE" == "1" && "$BAG_END_VINS_IDENTITY_MATCH" == "1" ]]; then
  kill -TERM "$VINS_PID"
  VINS_SIGNAL_SENT=15
else
  VINS_EARLY_EXIT=1
fi
wait_after_signal "$VINS_PID" "$VINS_START_TICKS" "$VINS_EXECUTABLE_EXPECTED" "$VINS_PGID_START"
VINS_WAIT_RC="$WAIT_RC"
VINS_REAPED="$WAIT_REAPED"
VINS_FORCED_KILL="$WAIT_FORCED_KILL"
VINS_PID=""
LAUNCH_CHECKPOINT="VINS_REAPED"

ROSCORE_END_START_TICKS="$(proc_start_ticks "$ROSCORE_PID")"
ROSCORE_END_EXECUTABLE="$(proc_executable "$ROSCORE_PID")"
ROSCORE_END_PGID="$(proc_pgid "$ROSCORE_PID")"
if [[ "$ROSCORE_END_START_TICKS" == "$ROSCORE_START_TICKS" \
  && "$ROSCORE_END_EXECUTABLE" == "$ROSCORE_EXECUTABLE" \
  && "$ROSCORE_END_PGID" == "$ROSCORE_PGID" ]]; then
  ROSCORE_IDENTITY_MATCH=1
  set +e
  kill -TERM "$ROSCORE_PID"
  ROSCORE_KILL_RC=$?
  set -e
fi
wait_after_signal "$ROSCORE_PID" "$ROSCORE_START_TICKS" "$ROSCORE_EXECUTABLE" "$ROSCORE_PGID"
ROSCORE_WAIT_RC="$WAIT_RC"
ROSCORE_REAPED="$WAIT_REAPED"
ROSCORE_FORCED_KILL="$WAIT_FORCED_KILL"
ROSCORE_PID=""
LAUNCH_CHECKPOINT="ROSCORE_REAPED"

for _ in {1..30}; do
  scan_group_residuals
  (( DESCENDANT_RESIDUAL_COUNT == 0 )) && break
  sleep 0.1
done
LAUNCH_CHECKPOINT="COMPLETE"
write_lifecycle

[[ "$ROSBAG_RC" == "0" && "$ROSBAG_REAPED" == "1" ]]
[[ "$BAG_END_VINS_ALIVE" == "1" && "$BAG_END_VINS_IDENTITY_MATCH" == "1" ]]
[[ "$OUTPUT_NONEMPTY" == "1" ]]
[[ "$VINS_SIGNAL_SENT" == "15" && "$VINS_WAIT_RC" == "143" ]]
[[ "$VINS_REAPED" == "1" && "$VINS_FORCED_KILL" == "0" ]]
[[ "$ROSCORE_IDENTITY_MATCH" == "1" && "$ROSCORE_KILL_RC" == "0" ]]
[[ "$ROSCORE_REAPED" == "1" && "$ROSCORE_FORCED_KILL" == "0" ]]
[[ "$DESCENDANT_RESIDUAL_COUNT" == "0" ]]

{
  printf 'schema_version=aqua-fe-fair-stability-vins-replay-manifest-v12\n'
  printf 'experiment_id=%s\n' "$EXPERIMENT_ID"
  printf 'run_dir=%s\n' "$RUN_DIR"
  printf 'play_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'vins_config=%s\n' "$VINS_CONFIG"
  printf 'vins_csv=%s\n' "$VINS_OUTPUT/vio.csv"
  printf 'tag=%s\n' "$TAG"
  printf 'accuracy_evaluator_started=0\n'
  printf 'shutdown_contract=EXPECTED_BAG_END_SIGTERM_REAP_V12\n'
} > "$RUN_DIR/replay_manifest.txt"
