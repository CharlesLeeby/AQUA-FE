#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

# Governed backend-only launcher.  This script consumes an already prepared
# raw-window bag (origin) or a kernel read-only sealed feature bag (external).
# It neither prepares/exports frontend data nor evaluates trajectory quality.

if [[ "$#" -ne 6 ]]; then
  echo "usage: $0 FAMILY MODE PLAY_BAG RUN_DIR VINS_CONFIG PORT" >&2
  exit 64
fi

FAMILY="$1"
MODE="$2"
PLAY_BAG="$3"
RUN_DIR="$4"
VINS_CONFIG="$5"
PORT="$6"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
PLAY_RATE="${PLAY_RATE:-1.0}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-3}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-8}"
ROSBAG_WAIT_FOR_SUBSCRIBERS="${ROSBAG_WAIT_FOR_SUBSCRIBERS:-0}"
PLAY_START="${PLAY_START:-}"
PLAY_DURATION="${PLAY_DURATION:-}"
PLAY_TOPICS="${PLAY_TOPICS:-}"
ROSCORE_WAIT_S="${ROSCORE_WAIT_S:-3}"
VINS_WAIT_S="${VINS_WAIT_S:-4}"
: "${AQUAFE_P07_VINS_BINARY:?missing sealed VINS binary}"
: "${AQUAFE_P07_VINS_LIB:?missing sealed VINS shared library}"
: "${AQUAFE_P07_CAMERA_MODELS_LIB:?missing sealed camera-models library}"
: "${AQUAFE_P07_VINS_BINARY_SHA256:?missing sealed VINS binary hash}"
: "${AQUAFE_P07_VINS_LIB_SHA256:?missing sealed VINS library hash}"
: "${AQUAFE_P07_CAMERA_MODELS_LIB_SHA256:?missing sealed camera-models hash}"
: "${AQUAFE_P07_PYTHON_INTERPRETER:?missing sealed Python interpreter}"
: "${AQUAFE_P07_ROSCORE:?missing absolute roscore authority}"
: "${AQUAFE_P07_ROSPARAM:?missing absolute rosparam authority}"
: "${AQUAFE_P07_ROSBAG:?missing absolute rosbag authority}"

case "$FAMILY" in
  ntnu|aqualoc_archaeology|aqualoc_harbor|afrl) ;;
  *) echo "unsupported P07 family: $FAMILY" >&2; exit 64 ;;
esac
case "$MODE" in
  external|origin) ;;
  *) echo "unsupported P07 mode: $MODE" >&2; exit 64 ;;
esac
if [[ ! "$PORT" =~ ^[0-9]+$ ]] || (( PORT < 1024 || PORT > 65535 )); then
  echo "invalid ROS port: $PORT" >&2
  exit 64
fi
if [[ "$ROOT" != "/home/ma/AQUA-FE_WS" ]]; then
  echo "P07 replay requires the frozen workspace root" >&2
  exit 65
fi
if [[ "$VINS_WS" != "/home/ma/SLAM/VINS-Fusion-origin" ]]; then
  echo "P07 replay requires the frozen origin VINS workspace" >&2
  exit 65
fi
if [[ "${AQUAFE_P07_FROZEN_ROS_ENV:-0}" != "1" || \
      "${PATH:-}" != "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" || \
      "${PYTHONPATH:-}" != "/opt/ros/noetic/lib/python3/dist-packages" || \
      "${ROS_ROOT:-}" != "/opt/ros/noetic/share/ros" || \
      "${ROS_PACKAGE_PATH:-}" != "/opt/ros/noetic/share" ]]; then
  echo "P07 replay lacks the frozen minimal ROS environment" >&2
  exit 65
fi
if [[ "$AQUAFE_P07_PYTHON_INTERPRETER" != /proc/self/fd/* || \
      ! -f "$AQUAFE_P07_PYTHON_INTERPRETER" || \
      "$AQUAFE_P07_ROSCORE" != "/opt/ros/noetic/bin/roscore" || \
      "$AQUAFE_P07_ROSPARAM" != "/opt/ros/noetic/bin/rosparam" || \
      "$AQUAFE_P07_ROSBAG" != "/opt/ros/noetic/bin/rosbag" ]]; then
  echo "P07 replay ROS/Python executable authority differs" >&2
  exit 65
fi
for ROS_EXECUTABLE in "$AQUAFE_P07_ROSCORE" "$AQUAFE_P07_ROSPARAM" "$AQUAFE_P07_ROSBAG"; do
  if [[ ! -f "$ROS_EXECUTABLE" || -L "$ROS_EXECUTABLE" || ! -x "$ROS_EXECUTABLE" ]]; then
    echo "P07 replay root-owned ROS executable is unavailable" >&2
    exit 65
  fi
done
if [[ ! -d "$RUN_DIR" || -L "$RUN_DIR" || "$RUN_DIR" != "$ROOT"/logs/* ]]; then
  echo "run directory must be an existing plain directory below ROOT/logs" >&2
  exit 65
fi
if [[ ! "$VINS_CONFIG" =~ ^/proc/self/fd/[0-9]+$ || ! -f "$VINS_CONFIG" ]]; then
  echo "VINS config must be the adapter's sealed fd" >&2
  exit 65
fi
if [[ ! -r "$PLAY_BAG" || ! -f "$PLAY_BAG" ]]; then
  echo "missing readable prepared play bag" >&2
  exit 65
fi
if [[ ! "$PLAY_BAG" =~ ^/proc/self/fd/[0-9]+$ ]]; then
  echo "all P07 replay bags require the adapter's sealed fd lease" >&2
  exit 65
fi
for SEALED_PATH in \
  "$AQUAFE_P07_VINS_BINARY" \
  "$AQUAFE_P07_VINS_LIB" \
  "$AQUAFE_P07_CAMERA_MODELS_LIB"; do
  if [[ ! "$SEALED_PATH" =~ ^/proc/self/fd/[0-9]+$ || ! -f "$SEALED_PATH" ]]; then
    echo "missing sealed VINS runtime fd: $SEALED_PATH" >&2
    exit 65
  fi
done
if [[ "$(sha256sum "$AQUAFE_P07_VINS_BINARY" | awk '{print $1}')" != "$AQUAFE_P07_VINS_BINARY_SHA256" ]] || \
   [[ "$(sha256sum "$AQUAFE_P07_VINS_LIB" | awk '{print $1}')" != "$AQUAFE_P07_VINS_LIB_SHA256" ]] || \
   [[ "$(sha256sum "$AQUAFE_P07_CAMERA_MODELS_LIB" | awk '{print $1}')" != "$AQUAFE_P07_CAMERA_MODELS_LIB_SHA256" ]]; then
  echo "sealed VINS runtime hash mismatch" >&2
  exit 65
fi

VINS_OUTPUT="$RUN_DIR/vins_output"
VINS_LOG="$RUN_DIR/vins.log"
ROSCORE_LOG="$RUN_DIR/roscore.log"
ENV_MANIFEST="$RUN_DIR/vins_env_manifest.txt"
BACKEND_MANIFEST="$RUN_DIR/backend_replay_manifest.txt"
if [[ ! -d "$VINS_OUTPUT" || -L "$VINS_OUTPUT" ]]; then
  echo "missing prepared plain VINS output directory" >&2
  exit 65
fi
for OUTPUT in "$VINS_LOG" "$ROSCORE_LOG" "$ENV_MANIFEST" "$BACKEND_MANIFEST" "$VINS_OUTPUT/vio.csv"; do
  if [[ -e "$OUTPUT" || -L "$OUTPUT" ]]; then
    echo "backend no-clobber collision: $OUTPUT" >&2
    exit 73
  fi
done

if ! grep -Fqx 'multiple_thread: 0' "$VINS_CONFIG"; then
  echo "VINS config is not frozen single-thread mode" >&2
  exit 65
fi
if ! grep -Fqx "output_path: \"$VINS_OUTPUT\"" "$VINS_CONFIG"; then
  echo "VINS config output path does not bind RUN_DIR" >&2
  exit 65
fi
if [[ "$MODE" == "external" ]] && ! grep -Fqx 'image0_topic: "/unused/image"' "$VINS_CONFIG"; then
  echo "external VINS config does not disable native image input" >&2
  exit 65
fi

export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost

ROSCORE_PID=""
VINS_PID=""
ROSBAG_PID=""
cleanup() {
  local pid
  for pid in "${ROSBAG_PID:-}" "${VINS_PID:-}" "${ROSCORE_PID:-}"; do
    if [[ -n "$pid" ]]; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
on_signal() {
  local signal_code="$1"
  trap - EXIT INT TERM HUP
  cleanup
  exit "$signal_code"
}
trap cleanup EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM
trap 'on_signal 129' HUP

"$AQUAFE_P07_PYTHON_INTERPRETER" "$AQUAFE_P07_ROSCORE" -p "$PORT" > "$ROSCORE_LOG" 2>&1 &
ROSCORE_PID=$!
sleep "$ROSCORE_WAIT_S"
if ! kill -0 "$ROSCORE_PID" 2>/dev/null; then
  echo "governed roscore exited during startup" >&2
  exit 70
fi
"$AQUAFE_P07_PYTHON_INTERPRETER" "$AQUAFE_P07_ROSPARAM" set /use_sim_time true

{
  echo "schema_version=isj-p07-backend-replay-environment-v1"
  echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "family=$FAMILY"
  echo "mode=$MODE"
  echo "VINS_WS=$VINS_WS"
  echo "ROS_MASTER_URI=$ROS_MASTER_URI"
  echo "vins_config=$VINS_CONFIG"
} > "$ENV_MANIFEST"

LD_PRELOAD="$AQUAFE_P07_CAMERA_MODELS_LIB:$AQUAFE_P07_VINS_LIB" \
  "$AQUAFE_P07_VINS_BINARY" "$VINS_CONFIG" > "$VINS_LOG" 2>&1 &
VINS_PID=$!
sleep "$VINS_WAIT_S"
if ! kill -0 "$VINS_PID" 2>/dev/null; then
  echo "governed vins_node exited during startup" >&2
  exit 70
fi
VINS_EXE_LINK="$(readlink "/proc/$VINS_PID/exe")"
if [[ "$VINS_EXE_LINK" != *"memfd:aquafe_p07_vins_binary"* ]] || \
   [[ "$(sha256sum "/proc/$VINS_PID/exe" | awk '{print $1}')" != "$AQUAFE_P07_VINS_BINARY_SHA256" ]]; then
  echo "running VINS PID executable is not the sealed binary" >&2
  exit 70
fi
if ! grep -Fq 'memfd:aquafe_p07_vins_shared_library' "/proc/$VINS_PID/maps" || \
   ! grep -Fq 'memfd:aquafe_p07_camera_models_shared_library' "/proc/$VINS_PID/maps"; then
  echo "running VINS PID maps do not contain both sealed project libraries" >&2
  exit 70
fi

PLAY_ARGS=("$PLAY_BAG" --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet)
if [[ -n "$PLAY_START" ]]; then
  PLAY_ARGS+=(--start "$PLAY_START")
fi
if [[ -n "$PLAY_DURATION" ]]; then
  PLAY_ARGS+=(--duration "$PLAY_DURATION")
fi
if [[ -n "$PLAY_TOPICS" ]]; then
  read -r -a TOPIC_ARGS <<< "$PLAY_TOPICS"
  for TOPIC in "${TOPIC_ARGS[@]}"; do
    if [[ "$TOPIC" != /* ]]; then
      echo "invalid replay topic: $TOPIC" >&2
      exit 64
    fi
  done
  PLAY_ARGS+=(--topics "${TOPIC_ARGS[@]}")
fi
if [[ "$ROSBAG_WAIT_FOR_SUBSCRIBERS" == "1" ]]; then
  PLAY_ARGS+=(--wait-for-subscribers)
elif [[ "$ROSBAG_WAIT_FOR_SUBSCRIBERS" != "0" ]]; then
  echo "ROSBAG_WAIT_FOR_SUBSCRIBERS must be 0 or 1" >&2
  exit 64
fi

"$AQUAFE_P07_PYTHON_INTERPRETER" "$AQUAFE_P07_ROSBAG" play "${PLAY_ARGS[@]}" &
ROSBAG_PID=$!
set +e
wait "$ROSBAG_PID"
ROSBAG_RC=$?
set -e
ROSBAG_PID=""
sleep "$POST_PLAY_SLEEP"

VINS_ALIVE=false
if kill -0 "$VINS_PID" 2>/dev/null; then
  VINS_ALIVE=true
fi
{
  echo "schema_version=isj-p07-backend-replay-manifest-v1"
  echo "family=$FAMILY"
  echo "mode=$MODE"
  echo "run_dir=$RUN_DIR"
  echo "play_bag=$PLAY_BAG"
  echo "vins_config=$VINS_CONFIG"
  echo "vins_exe_link=$VINS_EXE_LINK"
  echo "vins_binary_sha256=$AQUAFE_P07_VINS_BINARY_SHA256"
  echo "vins_lib_sha256=$AQUAFE_P07_VINS_LIB_SHA256"
  echo "camera_models_lib_sha256=$AQUAFE_P07_CAMERA_MODELS_LIB_SHA256"
  echo "vins_output=$VINS_OUTPUT"
  echo "vins_log=$VINS_LOG"
  echo "roscore_log=$ROSCORE_LOG"
  echo "rosbag_exit_code=$ROSBAG_RC"
  echo "vins_alive_after_replay=$VINS_ALIVE"
  echo "numeric_evaluation=DISABLED_SEPARATE_G0"
} > "$BACKEND_MANIFEST"

if (( ROSBAG_RC != 0 )); then
  exit "$ROSBAG_RC"
fi
if [[ "$VINS_ALIVE" != "true" ]]; then
  exit 70
fi
exit 0
