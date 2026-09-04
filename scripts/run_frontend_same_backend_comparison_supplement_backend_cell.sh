#!/usr/bin/env bash
set -euo pipefail

# One serial replay cell for the preregistered long-window supplement.  The
# canonical YAML is deliberately read in place: every arm/repeat of a window
# therefore consumes the same bytes and writes through one fixed scratch path.

WINDOW_ID="${1:?window id}"
ARM="${2:?arm}"
REPEAT="${3:?repeat}"
FEATURE_BAG="${4:?feature bag}"
CANONICAL_CONFIG="${5:?canonical config}"
SCRATCH_DIR="${6:?scratch dir}"
RUN_DIR="${7:?run dir}"
PORT="${8:?ROS port}"

ROOT="/home/ma/AQUA-FE_WS"
RUNTIME_ROOT="$ROOT/artifacts/frontend_same_backend_comparison_supplement"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
VINS_NODE="$VINS_WS/devel/lib/vins/vins_node"

case "$SCRATCH_DIR" in
  "$RUNTIME_ROOT"/scratch/"$WINDOW_ID") ;;
  *) echo "unsafe scratch path: $SCRATCH_DIR" >&2; exit 64 ;;
esac
case "$RUN_DIR" in
  "$RUNTIME_ROOT"/replays/"$WINDOW_ID"/"$ARM"/repeat"$REPEAT") ;;
  *) echo "unsafe run path: $RUN_DIR" >&2; exit 64 ;;
esac

[[ -s "$FEATURE_BAG" ]] || { echo "missing feature bag: $FEATURE_BAG" >&2; exit 66; }
[[ -s "$CANONICAL_CONFIG" ]] || { echo "missing canonical config: $CANONICAL_CONFIG" >&2; exit 66; }
[[ -x "$VINS_NODE" ]] || { echo "missing VINS node: $VINS_NODE" >&2; exit 66; }
if [[ -s "$RUN_DIR/replay_receipt.txt" ]]; then
  echo "resume backend $WINDOW_ID $ARM repeat$REPEAT"
  exit 0
fi
[[ ! -e "$RUN_DIR" ]] || { echo "unreceipted run directory: $RUN_DIR" >&2; exit 65; }

mkdir -p "$RUN_DIR" "$SCRATCH_DIR"
find "$SCRATCH_DIR" -mindepth 1 -delete
mkdir -p "$SCRATCH_DIR/vins_output"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost
IMU_TOPIC="$(sed -n 's/^imu_topic:[[:space:]]*"\([^"]*\)".*/\1/p' "$CANONICAL_CONFIG")"
[[ -n "$IMU_TOPIC" ]] || { echo "could not parse imu_topic from $CANONICAL_CONFIG" >&2; exit 65; }

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

roscore -p "$PORT" > "$RUN_DIR/roscore.log" 2>&1 &
ROSCORE_PID=$!
sleep 3
rosparam set /use_sim_time true
bash "$ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"
"$VINS_NODE" "$CANONICAL_CONFIG" > "$RUN_DIR/vins.log" 2>&1 &
VINS_PID=$!
sleep 4
/usr/bin/python3 "$ROOT/scripts/wait_for_ros_subscribers.py" \
  /feature_tracker/feature "$IMU_TOPIC" --timeout 20
rosbag play "$FEATURE_BAG" --clock --rate 1.0 --delay 3 --quiet \
  > "$RUN_DIR/rosbag_play.log" 2>&1
sleep 8

kill -0 "$VINS_PID"
[[ -s "$SCRATCH_DIR/vins_output/vio.csv" ]] || {
  echo "VINS produced no trajectory" >&2
  exit 3
}
mkdir -p "$RUN_DIR/vins_output"
cp "$SCRATCH_DIR/vins_output/vio.csv" "$RUN_DIR/vins_output/vio.csv"

{
  printf 'schema_version=aqua-fe-fsbcsupp-backend-cell-v1\n'
  printf 'window_id=%s\n' "$WINDOW_ID"
  printf 'arm=%s\n' "$ARM"
  printf 'repeat=%s\n' "$REPEAT"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag_sha256=%s\n' "$(sha256sum "$FEATURE_BAG" | awk '{print $1}')"
  printf 'canonical_config=%s\n' "$CANONICAL_CONFIG"
  printf 'canonical_config_sha256=%s\n' "$(sha256sum "$CANONICAL_CONFIG" | awk '{print $1}')"
  printf 'vins_node=%s\n' "$VINS_NODE"
  printf 'vins_node_sha256=%s\n' "$(sha256sum "$VINS_NODE" | awk '{print $1}')"
  printf 'vio_csv=%s\n' "$RUN_DIR/vins_output/vio.csv"
  printf 'vio_csv_sha256=%s\n' "$(sha256sum "$RUN_DIR/vins_output/vio.csv" | awk '{print $1}')"
} > "$RUN_DIR/replay_receipt.txt"
echo "finish backend $WINDOW_ID $ARM repeat$REPEAT"
