#!/usr/bin/env bash
set -euo pipefail

WINDOW_ID="${1:?window id}"
RUN_SLUG="${2:?run slug}"
REPEAT="${3:?repeat}"
FEATURE_BAG="${4:?feature bag}"
CANONICAL_CONFIG="${5:?canonical config}"
SCRATCH_DIR="${6:?scratch dir}"
RUN_DIR="${7:?run dir}"
PORT="${8:?ROS port}"

ROOT="/home/ma/AQUA-FE_WS"
RUNTIME_ROOT="/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_v2_positive_delete_diagnostic"
V2_RUNTIME="/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_coverage_monotone_router_v2"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
VINS_NODE="$VINS_WS/devel/lib/vins/vins_node"
VINS_LIB="$VINS_WS/devel/lib/libvins_lib.so"
ROOT_FLOOR=$((2 * 1024 * 1024 * 1024))
OFFLOAD_FLOOR=$((8 * 1024 * 1024 * 1024))

case "$RUN_SLUG" in
  a09_6000_6800|afrl_bus_s180_d045) ;;
  *) echo "unexpected run slug: $RUN_SLUG" >&2; exit 64 ;;
esac
case "$SCRATCH_DIR" in
  "$V2_RUNTIME"/backend_scratch/"$RUN_SLUG") ;;
  *) echo "unsafe scratch path: $SCRATCH_DIR" >&2; exit 64 ;;
esac
case "$RUN_DIR" in
  "$RUNTIME_ROOT"/backend_replays/"$RUN_SLUG"/donor_delete_only/repeat"$REPEAT") ;;
  *) echo "unsafe run path: $RUN_DIR" >&2; exit 64 ;;
esac

root_free="$(df -B1 --output=avail / | tail -n1 | tr -d ' ')"
offload_free="$(df -B1 --output=avail /media/ma/Data | tail -n1 | tr -d ' ')"
(( root_free >= ROOT_FLOOR )) || { echo "root disk floor failed" >&2; exit 73; }
(( offload_free >= OFFLOAD_FLOOR )) || { echo "offload disk floor failed" >&2; exit 73; }
[[ -s "$FEATURE_BAG" && -s "$CANONICAL_CONFIG" && -x "$VINS_NODE" && -s "$VINS_LIB" ]] || exit 66

if [[ -s "$RUN_DIR/replay_receipt.txt" ]]; then
  [[ "$(sed -n 's/^feature_bag_sha256=//p' "$RUN_DIR/replay_receipt.txt")" == "$(sha256sum "$FEATURE_BAG" | awk '{print $1}')" ]] || exit 65
  [[ "$(sed -n 's/^canonical_config_sha256=//p' "$RUN_DIR/replay_receipt.txt")" == "$(sha256sum "$CANONICAL_CONFIG" | awk '{print $1}')" ]] || exit 65
  [[ "$(sed -n 's/^vio_csv_sha256=//p' "$RUN_DIR/replay_receipt.txt")" == "$(sha256sum "$RUN_DIR/vins_output/vio.csv" | awk '{print $1}')" ]] || exit 65
  echo "resume positive-delete $RUN_SLUG repeat$REPEAT"
  exit 0
fi
[[ ! -e "$RUN_DIR" ]] || { echo "unreceipted run directory: $RUN_DIR" >&2; exit 65; }

mkdir -p "$RUN_DIR" "$SCRATCH_DIR"
PRESERVE_DIR="$RUNTIME_ROOT/scratch_preservation/$RUN_SLUG/before_repeat$REPEAT"
[[ ! -e "$PRESERVE_DIR" ]] || { echo "scratch preservation target exists: $PRESERVE_DIR" >&2; exit 65; }
mkdir -p "$PRESERVE_DIR"
while IFS= read -r -d '' item; do
  mv "$item" "$PRESERVE_DIR/"
done < <(find "$SCRATCH_DIR" -mindepth 1 -maxdepth 1 -print0)
mkdir -p "$SCRATCH_DIR/vins_output"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"
export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost
export ROS_HOME="$RUNTIME_ROOT/ros_home_backend"
export ROS_LOG_DIR="$RUNTIME_ROOT/ros_logs_backend"
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR"

IMU_TOPIC="$(sed -n 's/^imu_topic:[[:space:]]*"\([^"]*\)".*/\1/p' "$CANONICAL_CONFIG")"
[[ -n "$IMU_TOPIC" ]] || { echo "could not parse imu_topic" >&2; exit 65; }

ROSCORE_PID=""
VINS_PID=""
cleanup() {
  if [[ -n "$VINS_PID" ]]; then kill "$VINS_PID" 2>/dev/null || true; wait "$VINS_PID" 2>/dev/null || true; fi
  if [[ -n "$ROSCORE_PID" ]]; then kill "$ROSCORE_PID" 2>/dev/null || true; wait "$ROSCORE_PID" 2>/dev/null || true; fi
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
[[ -s "$SCRATCH_DIR/vins_output/vio.csv" ]] || { echo "VINS produced no trajectory" >&2; exit 3; }
mkdir -p "$RUN_DIR/vins_output"
cp "$SCRATCH_DIR/vins_output/vio.csv" "$RUN_DIR/vins_output/vio.csv"

{
  printf 'schema_version=aqua-fe-v2-positive-delete-backend-cell-v1\n'
  printf 'window_id=%s\n' "$WINDOW_ID"
  printf 'run_slug=%s\n' "$RUN_SLUG"
  printf 'cell_id=donor_delete_only\n'
  printf 'repeat=%s\n' "$REPEAT"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag_sha256=%s\n' "$(sha256sum "$FEATURE_BAG" | awk '{print $1}')"
  printf 'canonical_config=%s\n' "$CANONICAL_CONFIG"
  printf 'canonical_config_sha256=%s\n' "$(sha256sum "$CANONICAL_CONFIG" | awk '{print $1}')"
  printf 'vins_node=%s\n' "$VINS_NODE"
  printf 'vins_node_sha256=%s\n' "$(sha256sum "$VINS_NODE" | awk '{print $1}')"
  printf 'vins_lib=%s\n' "$VINS_LIB"
  printf 'vins_lib_sha256=%s\n' "$(sha256sum "$VINS_LIB" | awk '{print $1}')"
  printf 'vio_csv=%s\n' "$RUN_DIR/vins_output/vio.csv"
  printf 'vio_csv_sha256=%s\n' "$(sha256sum "$RUN_DIR/vins_output/vio.csv" | awk '{print $1}')"
  printf 'scratch_preserved_at=%s\n' "$PRESERVE_DIR"
  printf 'root_free_bytes_pre=%s\n' "$root_free"
  printf 'offload_free_bytes_pre=%s\n' "$offload_free"
} > "$RUN_DIR/replay_receipt.txt"

echo "finish positive-delete $RUN_SLUG repeat$REPEAT"
