#!/usr/bin/env bash
set -euo pipefail
FEATURE_BAG="${1:?bag}"
CONFIG="${2:?canonical yaml}"
RUN_DIR="${3:?new run directory}"
TASK_ROOT=/home/ma/AQUA-FE_WS
TRACE_ROOT=/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_a02_init_trace_repair_v1
VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
SCRATCH=/media/ma/Data/AQUA-FE_WS_storage_offload/frontend_coverage_monotone_router_v2/backend_scratch/a02_0_900
case "$RUN_DIR" in
  "$TRACE_ROOT"/klt/repeat[123]|"$TRACE_ROOT"/donor_delete_only/repeat[123]) ;;
  *) exit 64 ;;
esac
[[ ! -e "$RUN_DIR" ]] || exit 65
(( $(df -B1 --output=avail / | tail -1) >= 2147483648 )) || exit 73
(( $(df -B1 --output=avail /media/ma/Data | tail -1) >= 8589934592 )) || exit 73
[[ -s "$FEATURE_BAG" && -s "$CONFIG" ]] || exit 66
DECLARED="$(sed -n 's/^output_path:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG")"
[[ "$DECLARED" == "$SCRATCH/vins_output" ]] || exit 64
# All runs are serial and owned. Never change the canonical output_path.
if pgrep -x vins_node >/dev/null; then echo 'An existing VINS process is active; stop safely.' >&2; exit 73; fi
mkdir -p "$RUN_DIR"
if [[ -e "$SCRATCH" ]]; then
  [[ ! -L "$SCRATCH" ]] || exit 64
  mv -- "$SCRATCH" "$RUN_DIR/prior_canonical_scratch"
fi
mkdir -p "$DECLARED"
source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"
export PYTHONPATH="$TASK_ROOT:${PYTHONPATH:-}"
export ROS_MASTER_URI=http://localhost:11983
export ROS_HOSTNAME=localhost
export ROS_HOME="$TRACE_ROOT/ros_home"
export ROS_LOG_DIR="$TRACE_ROOT/ros_logs"
export VINS_INITIAL_DIAGNOSTICS=1
mkdir -p "$ROS_HOME" "$ROS_LOG_DIR"
IMU_TOPIC="$(sed -n 's/^imu_topic:[[:space:]]*"\([^"]*\)".*/\1/p' "$CONFIG")"
[[ -n "$IMU_TOPIC" ]] || exit 65
CORE_PID=""
NODE_PID=""
cleanup() {
  if [[ -n "$NODE_PID" ]]; then kill "$NODE_PID" 2>/dev/null || true; wait "$NODE_PID" 2>/dev/null || true; fi
  if [[ -n "$CORE_PID" ]]; then kill "$CORE_PID" 2>/dev/null || true; wait "$CORE_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
roscore -p 11983 > "$RUN_DIR/roscore.log" 2>&1 &
CORE_PID=$!
sleep 3
rosparam set /use_sim_time true
bash "$TASK_ROOT/scripts/record_vins_env.sh" "$RUN_DIR/vins_env_manifest.txt" "$VINS_WS"
"$VINS_WS/devel/lib/vins/vins_node" "$CONFIG" > "$RUN_DIR/vins.log" 2>&1 &
NODE_PID=$!
sleep 4
/usr/bin/python3 "$TASK_ROOT/scripts/wait_for_ros_subscribers.py" /feature_tracker/feature "$IMU_TOPIC" --timeout 20
rosbag play "$FEATURE_BAG" --clock --rate 1.0 --delay 3 --quiet > "$RUN_DIR/rosbag_play.log" 2>&1
sleep 8
kill -0 "$NODE_PID"
mkdir -p "$RUN_DIR/vins_output"
if [[ -f "$DECLARED/vio.csv" ]]; then cp "$DECLARED/vio.csv" "$RUN_DIR/vins_output/vio.csv"; fi
[[ -s "$RUN_DIR/vins_output/vio.csv" ]] || exit 3
