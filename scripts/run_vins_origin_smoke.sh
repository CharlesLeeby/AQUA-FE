#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-sim}"
ROOT="/home/ma/AQUA-FE_WS"
VINS_WS="/home/ma/SLAM/VINS-Fusion-origin"
LOG_ROOT="$ROOT/logs/vins_origin"

source /opt/ros/noetic/setup.bash
source "$VINS_WS/devel/setup.bash"

case "$MODE" in
  sim)
    PORT=11316
    CONFIG="$LOG_ROOT/uwrobot_sim_pure_vins.yaml"
    BAG="/home/ma/Dataset/uwrobot_sim/switch/uwrobot_40s.bag"
    OUT="$LOG_ROOT/sim_pure_vins_output"
    LOG="$LOG_ROOT/sim_pure_vins_full40.log"
    ;;
  real)
    PORT=11315
    CONFIG="$LOG_ROOT/real_front_cam_pure_vins.yaml"
    BAG="/home/ma/Dataset/uwrobot_real/front_cam_imu_20260403_162355_ros1_noetic_imgshift_m085.bag"
    OUT="$LOG_ROOT/real_front_cam_output"
    LOG="$LOG_ROOT/real_front_cam_smoke.log"
    ;;
  *)
    echo "usage: $0 [sim|real]" >&2
    exit 2
    ;;
esac

mkdir -p "$OUT"
rm -f "$OUT/vio.csv" "$LOG"

export ROS_MASTER_URI="http://localhost:$PORT"
export ROS_HOSTNAME=localhost

roscore -p "$PORT" > "$LOG_ROOT/roscore_$PORT.log" 2>&1 &
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
rosrun vins vins_node "$CONFIG" > "$LOG" 2>&1 &
VINS_PID=$!
sleep 4
rosbag play "$BAG" --clock --quiet
sleep 8

LINES=0
if [[ -f "$OUT/vio.csv" ]]; then
  LINES=$(wc -l < "$OUT/vio.csv")
fi
echo "mode=$MODE"
echo "vio_csv=$OUT/vio.csv"
echo "vio_lines=$LINES"
tail -5 "$OUT/vio.csv" 2>/dev/null || true
