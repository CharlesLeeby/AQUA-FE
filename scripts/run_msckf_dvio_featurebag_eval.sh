#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 FEATURE_BAG RUN_DIR ROLE" >&2
  exit 2
fi

FEATURE_BAG="$(realpath "$1")"
RUN_DIR="$(realpath -m "$2")"
ROLE="$3"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
MSCKF_WS="${MSCKF_WS:-/home/ma/SLAM/msckf_dvio_aquafe_ws}"
MSCKF_SOURCE="${MSCKF_SOURCE:-/home/ma/SLAM/msckf_dvio_aquafe_src}"
CONFIG_DIR="${CONFIG_DIR:-$ROOT/configs/msckf_dvio/aqualoc}"
IMU_TOPIC="${IMU_TOPIC:-/rtimulib_node/imu}"
FEATURE_TOPIC="${FEATURE_TOPIC:-/feature_tracker/feature}"
GT_TOPIC="${GT_TOPIC:-/aqualoc/colmap_gt}"
ODOM_TOPIC="${ODOM_TOPIC:-/odom}"
PLAY_RATE="${PLAY_RATE:-0.25}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-3}"
PLAY_TIMEOUT="${PLAY_TIMEOUT:-180}"
INIT_IMU_SAMPLES="${INIT_IMU_SAMPLES:-50}"
MSCKF_INIT_MODE="${MSCKF_INIT_MODE:-gt_calibrated}"
MSCKF_INIT_BIAS_JSON="${MSCKF_INIT_BIAS_JSON:-}"
MSCKF_CAMERA_NOISE="${MSCKF_CAMERA_NOISE:-}"
MSCKF_LINEAGE_SHADOW_ENABLED="${MSCKF_LINEAGE_SHADOW_ENABLED:-false}"
MSCKF_LINEAGE_SHADOW_PATH="${MSCKF_LINEAGE_SHADOW_PATH:-$RUN_DIR/lineage_shadow.csv}"
MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS="${MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS:-0}"
MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES="${MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES:-0}"

if [[ ! -f "$FEATURE_BAG" ]]; then
  echo "missing feature bag: $FEATURE_BAG" >&2
  exit 2
fi
for config in system.yaml prior.yaml image.yaml; do
  if [[ ! -f "$CONFIG_DIR/$config" ]]; then
    echo "missing config: $CONFIG_DIR/$config" >&2
    exit 2
  fi
done
if [[ ! -f "$MSCKF_WS/devel/setup.bash" ]]; then
  echo "missing MSCKF workspace build: $MSCKF_WS/devel/setup.bash" >&2
  exit 2
fi

mkdir -p "$RUN_DIR"
rm -f "$RUN_DIR/trajectory.bag" "$RUN_DIR/trajectory.bag.active" \
  "$RUN_DIR/estimator.csv" "$RUN_DIR/groundtruth.tum" "$RUN_DIR/metrics.txt"

INIT_ARGS=(
  --bag "$FEATURE_BAG"
  --imu-topic "$IMU_TOPIC"
  --gt-topic "$GT_TOPIC"
  --samples "$INIT_IMU_SAMPLES"
  --mode "$MSCKF_INIT_MODE"
  --prior-yaml "$CONFIG_DIR/prior.yaml"
  --output-json "$RUN_DIR/init.json"
  --output-yaml "$RUN_DIR/init.yaml"
)
if [[ -n "$MSCKF_INIT_BIAS_JSON" ]]; then
  INIT_ARGS+=(--bias-json "$MSCKF_INIT_BIAS_JSON")
fi
python3 "$ROOT/scripts/derive_msckf_imu_init.py" \
  "${INIT_ARGS[@]}" \
  > "$RUN_DIR/init.stdout.json"

cp "$CONFIG_DIR/system.yaml" "$RUN_DIR/system.yaml"
cp "$CONFIG_DIR/prior.yaml" "$RUN_DIR/prior.yaml"
cp "$CONFIG_DIR/image.yaml" "$RUN_DIR/image.yaml"
if [[ -n "$MSCKF_CAMERA_NOISE" ]]; then
  python3 - "$RUN_DIR/prior.yaml" "$MSCKF_CAMERA_NOISE" <<'PY'
import math
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
noise = float(sys.argv[2])
if not math.isfinite(noise) or noise <= 0.0:
    raise SystemExit("MSCKF_CAMERA_NOISE must be finite and positive")
data = yaml.safe_load(path.read_text(encoding="utf-8"))
data["CAM0"]["noise"] = noise
path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="ascii")
PY
fi

if [[ -z "${ROS_MASTER_PORT:-}" ]]; then
  ROS_MASTER_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
fi
export ROS_MASTER_URI="http://127.0.0.1:${ROS_MASTER_PORT}"
export ROS_IP="127.0.0.1"
unset ROS_HOSTNAME || true

CORE_PID=""
NODE_PID=""
RECORD_PID=""

stop_pid() {
  local signal="$1"
  local pid="$2"
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "-$signal" "$pid" 2>/dev/null || true
  fi
}

cleanup() {
  set +e
  stop_pid INT "$RECORD_PID"
  sleep 1
  stop_pid TERM "$NODE_PID"
  stop_pid INT "$CORE_PID"
  sleep 1
  stop_pid KILL "$RECORD_PID"
  stop_pid KILL "$NODE_PID"
  stop_pid KILL "$CORE_PID"
  [[ -n "$RECORD_PID" ]] && wait "$RECORD_PID" 2>/dev/null
  [[ -n "$NODE_PID" ]] && wait "$NODE_PID" 2>/dev/null
  [[ -n "$CORE_PID" ]] && wait "$CORE_PID" 2>/dev/null
}
trap cleanup EXIT INT TERM

source /opt/ros/noetic/setup.bash
source "$MSCKF_WS/devel/setup.bash"

roscore -p "$ROS_MASTER_PORT" > "$RUN_DIR/roscore.log" 2>&1 &
CORE_PID=$!
for _ in $(seq 1 100); do
  if rosparam list >/dev/null 2>&1; then
    break
  fi
  sleep 0.1
done
if ! rosparam list >/dev/null 2>&1; then
  echo "ROS master did not start" >&2
  exit 1
fi

rosparam set /use_sim_time true
rosparam load "$RUN_DIR/system.yaml" /MSCKF_DVIO_Node
rosparam load "$RUN_DIR/prior.yaml" /MSCKF_DVIO_Node
rosparam load "$RUN_DIR/init.yaml" /MSCKF_DVIO_Node
rosparam load "$RUN_DIR/image.yaml" /MSCKF_DVIO_Node

if [[ ! "$MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS" =~ ^[0-9]+$ ]] || \
   [[ "$MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS" == "1" ]]; then
  echo "MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS must be 0 or at least 2" >&2
  exit 2
fi
rosparam set \
  /MSCKF_DVIO_Node/MSCKF/learned_lineage_max_update_observations \
  "$MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS"
if [[ ! "$MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES" =~ ^[0-9]+$ ]]; then
  echo "MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES must be non-negative" >&2
  exit 2
fi
rosparam set /MSCKF_DVIO_Node/MSCKF/lineage_rearm_max_gap_frames \
  "$MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES"

case "${MSCKF_LINEAGE_SHADOW_ENABLED,,}" in
  1|true|yes)
    MSCKF_LINEAGE_SHADOW_ENABLED=true
    mkdir -p "$(dirname "$MSCKF_LINEAGE_SHADOW_PATH")"
    rm -f "$MSCKF_LINEAGE_SHADOW_PATH"
    rosparam set /MSCKF_DVIO_Node/MSCKF/lineage_shadow_enabled true
    rosparam set /MSCKF_DVIO_Node/MSCKF/lineage_shadow_path "$MSCKF_LINEAGE_SHADOW_PATH"
    ;;
  0|false|no)
    MSCKF_LINEAGE_SHADOW_ENABLED=false
    rosparam set /MSCKF_DVIO_Node/MSCKF/lineage_shadow_enabled false
    ;;
  *)
    echo "invalid MSCKF_LINEAGE_SHADOW_ENABLED: $MSCKF_LINEAGE_SHADOW_ENABLED" >&2
    exit 2
    ;;
esac

rosrun msckf_dvio dvio_node __name:=MSCKF_DVIO_Node \
  > "$RUN_DIR/estimator.log" 2>&1 &
NODE_PID=$!

subscribers_ready=0
for _ in $(seq 1 200); do
  imu_subscribers="$(rostopic info "$IMU_TOPIC" 2>/dev/null | sed -n '/Subscribers:/,$p' || true)"
  feature_subscribers="$(rostopic info "$FEATURE_TOPIC" 2>/dev/null | sed -n '/Subscribers:/,$p' || true)"
  if [[ "$imu_subscribers" == *MSCKF_DVIO_Node* ]] && \
     [[ "$feature_subscribers" == *MSCKF_DVIO_Node* ]]; then
    subscribers_ready=1
    break
  fi
  if ! kill -0 "$NODE_PID" 2>/dev/null; then
    echo "MSCKF-DVIO exited before subscribing" >&2
    exit 1
  fi
  sleep 0.1
done
if [[ "$subscribers_ready" != "1" ]]; then
  echo "MSCKF-DVIO subscribers were not ready" >&2
  exit 1
fi

rosbag record --buffsize=0 -O "$RUN_DIR/trajectory.bag" "$ODOM_TOPIC" \
  __name:="msckf_record_${ROLE//[^A-Za-z0-9_]/_}" \
  > "$RUN_DIR/record.log" 2>&1 &
RECORD_PID=$!
sleep 1

set +e
timeout --signal=INT --kill-after=10 "$PLAY_TIMEOUT" \
  rosbag play --clock --rate "$PLAY_RATE" "$FEATURE_BAG" \
  --topics "$IMU_TOPIC" "$FEATURE_TOPIC" \
  > "$RUN_DIR/play.log" 2>&1
PLAY_STATUS=$?
set -e
if [[ "$PLAY_STATUS" -ne 0 ]]; then
  echo "rosbag play failed with status $PLAY_STATUS" >&2
  exit "$PLAY_STATUS"
fi
sleep "$POST_PLAY_SLEEP"

stop_pid INT "$RECORD_PID"
wait "$RECORD_PID" 2>/dev/null || true
RECORD_PID=""
stop_pid TERM "$NODE_PID"
wait "$NODE_PID" 2>/dev/null || true
NODE_PID=""
stop_pid INT "$CORE_PID"
wait "$CORE_PID" 2>/dev/null || true
CORE_PID=""
trap - EXIT INT TERM

if [[ ! -s "$RUN_DIR/trajectory.bag" ]]; then
  echo "MSCKF-DVIO did not produce a trajectory bag" >&2
  exit 1
fi
if [[ "$MSCKF_LINEAGE_SHADOW_ENABLED" == "true" && ! -s "$MSCKF_LINEAGE_SHADOW_PATH" ]]; then
  echo "MSCKF lineage shadow was enabled but no CSV was produced" >&2
  exit 1
fi
if [[ "$MSCKF_LINEAGE_SHADOW_ENABLED" == "true" && ! -s "${MSCKF_LINEAGE_SHADOW_PATH}.stages.csv" ]]; then
  echo "MSCKF lineage stage shadow was enabled but no CSV was produced" >&2
  exit 1
fi

python3 "$ROOT/scripts/export_ros_odom_vins_csv.py" \
  --bag "$RUN_DIR/trajectory.bag" \
  --topic "$ODOM_TOPIC" \
  --output "$RUN_DIR/estimator.csv"
python3 "$ROOT/scripts/export_ros_odom_tum.py" \
  --bag "$FEATURE_BAG" \
  --topic "$GT_TOPIC" \
  --output "$RUN_DIR/groundtruth.tum"
python3 "$ROOT/scripts/evaluate_vins_tum.py" \
  --vins-csv "$RUN_DIR/estimator.csv" \
  --gt-tum "$RUN_DIR/groundtruth.tum" \
  --vins-log "$RUN_DIR/estimator.log" \
  --output-dir "$RUN_DIR/evaluation" \
  --rpe-delta-s 1.0 \
  --max-match-dt 0.6 \
  --gap-threshold-s 0.3 \
  --init-timeout-s 8.0 \
  --min-init-poses 10 \
  --min-coverage-ratio 0.50 \
  --write-tum \
  --run-evo \
  > "$RUN_DIR/metrics.txt"

{
  printf 'role=%s\n' "$ROLE"
  printf 'feature_bag=%s\n' "$FEATURE_BAG"
  printf 'feature_bag_sha256=%s\n' "$(sha256sum "$FEATURE_BAG" | awk '{print $1}')"
  printf 'msckf_source=%s\n' "$MSCKF_SOURCE"
  printf 'msckf_commit=%s\n' "$(git -C "$MSCKF_SOURCE" rev-parse HEAD)"
  printf 'msckf_dirty=%s\n' "$(test -n "$(git -C "$MSCKF_SOURCE" status --short)" && echo 1 || echo 0)"
  printf 'msckf_source_tree_sha256=%s\n' "$(
    find "$MSCKF_SOURCE" -path "$MSCKF_SOURCE/.git" -prune -o -type f -print0 |
      sort -z |
      xargs -0 sha256sum |
      sha256sum |
      awk '{print $1}'
  )"
  printf 'runner_sha256=%s\n' "$(sha256sum "$ROOT/scripts/run_msckf_dvio_featurebag_eval.sh" | awk '{print $1}')"
  printf 'system_config_sha256=%s\n' "$(sha256sum "$RUN_DIR/system.yaml" | awk '{print $1}')"
  printf 'prior_config_sha256=%s\n' "$(sha256sum "$RUN_DIR/prior.yaml" | awk '{print $1}')"
  printf 'image_config_sha256=%s\n' "$(sha256sum "$RUN_DIR/image.yaml" | awk '{print $1}')"
  printf 'init_sha256=%s\n' "$(sha256sum "$RUN_DIR/init.yaml" | awk '{print $1}')"
  printf 'trajectory_bag_sha256=%s\n' "$(sha256sum "$RUN_DIR/trajectory.bag" | awk '{print $1}')"
  printf 'estimator_csv_sha256=%s\n' "$(sha256sum "$RUN_DIR/estimator.csv" | awk '{print $1}')"
  printf 'metrics_sha256=%s\n' "$(sha256sum "$RUN_DIR/metrics.txt" | awk '{print $1}')"
  printf 'play_rate=%s\n' "$PLAY_RATE"
  printf 'initialization_mode=%s\n' "$MSCKF_INIT_MODE"
  printf 'camera_noise_override=%s\n' "$MSCKF_CAMERA_NOISE"
  printf 'lineage_shadow_enabled=%s\n' "$MSCKF_LINEAGE_SHADOW_ENABLED"
  printf 'lineage_shadow_path=%s\n' "$MSCKF_LINEAGE_SHADOW_PATH"
  printf 'learned_lineage_max_update_observations=%s\n' \
    "$MSCKF_LEARNED_LINEAGE_MAX_UPDATE_OBSERVATIONS"
  printf 'lineage_rearm_max_gap_frames=%s\n' \
    "$MSCKF_LINEAGE_REARM_MAX_GAP_FRAMES"
  if [[ "$MSCKF_LINEAGE_SHADOW_ENABLED" == "true" ]]; then
    printf 'lineage_shadow_sha256=%s\n' "$(sha256sum "$MSCKF_LINEAGE_SHADOW_PATH" | awk '{print $1}')"
    printf 'lineage_shadow_stage_path=%s\n' "${MSCKF_LINEAGE_SHADOW_PATH}.stages.csv"
    printf 'lineage_shadow_stage_sha256=%s\n' "$(sha256sum "${MSCKF_LINEAGE_SHADOW_PATH}.stages.csv" | awk '{print $1}')"
  fi
  printf 'initialization_bias_json=%s\n' "$MSCKF_INIT_BIAS_JSON"
  if [[ -n "$MSCKF_INIT_BIAS_JSON" ]]; then
    printf 'initialization_bias_json_sha256=%s\n' "$(sha256sum "$MSCKF_INIT_BIAS_JSON" | awk '{print $1}')"
  fi
  printf 'ros_master_port=%s\n' "$ROS_MASTER_PORT"
} > "$RUN_DIR/run_manifest.txt"

cat "$RUN_DIR/metrics.txt"
