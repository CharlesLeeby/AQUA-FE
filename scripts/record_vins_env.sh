#!/usr/bin/env bash
set -euo pipefail

OUT="${1:?usage: record_vins_env.sh OUT_FILE [VINS_WS]}"
VINS_WS_ARG="${2:-${VINS_WS:-}}"

{
  echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "hostname=$(hostname)"
  echo "pwd=$(pwd)"
  echo "VINS_WS=$VINS_WS_ARG"
  echo "ROS_MASTER_URI=${ROS_MASTER_URI:-}"
  echo "CMAKE_PREFIX_PATH=${CMAKE_PREFIX_PATH:-}"
  echo "ROS_PACKAGE_PATH=${ROS_PACKAGE_PATH:-}"
  echo "LD_LIBRARY_PATH=${LD_LIBRARY_PATH:-}"
  echo "PYTHONPATH=${PYTHONPATH:-}"
  for KEY in \
    PATH ROS_DISTRO PYTHONNOUSERSITE PYTHONHASHSEED CATKIN_SETUP_UTIL_ARGS ROOT AQUALOC_ROOT \
    RAW_TAR RAW_ROOT GT_TXT RAW_BAG FEATURE_BAG_OVERRIDE FRONTEND_CONFIG \
    BACKEND_REPLAY_ONLY RUN_VINS FORCE_RAW FORCE_EXPORT EXPORT_FEATURES \
    VINS_MULTIPLE_THREAD VINS_TD VINS_ESTIMATE_TD VINS_MAX_SOLVER_TIME \
    VINS_MAX_NUM_ITERATIONS VINS_MAX_CNT VINS_MIN_DIST VINS_FREQ \
    VINS_KEYFRAME_PARALLAX VINS_F_THRESHOLD \
    VINS_SYNTHETIC_ACC_BIAS_SIGMA \
    VINS_SYNTHETIC_GYR_BIAS_SIGMA VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT \
    VINS_INITIAL_DIAGNOSTICS VINS_STATE_DIAGNOSTICS \
    VINS_INITIAL_MIN_SCALE VINS_INITIAL_MAX_SCALE \
    VINS_INITIAL_RANSAC_SEED VINS_INITIAL_SFM_MAX_SOLVER_TIME \
    VINS_INITIAL_SFM_MAX_NUM_ITERATIONS OMP_NUM_THREADS OPENBLAS_NUM_THREADS \
    VINS_INITIAL_MAX_GYRO_BIAS_DELTA VINS_INITIAL_ROLLBACK_ON_FAILURE \
    VINS_INITIAL_SKIP_GYRO_BIAS_CALIBRATION \
    VINS_ENABLE_FAILURE_DETECTION VINS_FAILURE_MAX_SPEED \
    AQUALOC_BODY_T_CAM0_MODE PLAY_RATE DRAIN_STABLE_S DRAIN_TIMEOUT_S \
    POST_PLAY_SLEEP ROSBAG_PLAY_DELAY ROSBAG_WAIT_FOR_SUBSCRIBERS \
    ROSBAG_PLAY_TOPICS WAIT_FOR_VINS_SUBSCRIBERS \
    WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT PORT TAG
  do
    printf '%s=%s\n' "$KEY" "${!KEY-}"
  done
  if command -v rospack >/dev/null 2>&1; then
    VINS_PKG="$(rospack find vins 2>/dev/null || true)"
    echo "rospack_find_vins=$VINS_PKG"
    CANDIDATES=()
    if [[ -n "$VINS_WS_ARG" ]]; then
      CANDIDATES+=("$VINS_WS_ARG/devel/lib/vins/vins_node")
    fi
    if [[ -n "$VINS_PKG" ]]; then
      CANDIDATES+=("$(realpath "$VINS_PKG/../../../devel/lib/vins/vins_node" 2>/dev/null || true)")
    fi
    FOUND_BIN=""
    for VINS_BIN in "${CANDIDATES[@]}"; do
      if [[ -n "$VINS_BIN" && -x "$VINS_BIN" ]]; then
        FOUND_BIN="$VINS_BIN"
        break
      fi
    done
    if [[ -n "$FOUND_BIN" ]]; then
      echo "vins_binary=$FOUND_BIN"
      stat -c "vins_binary_stat=%n %s bytes mtime=%y" "$FOUND_BIN"
      md5sum "$FOUND_BIN" | sed 's/^/vins_binary_md5=/'
    else
      printf "vins_binary_missing_candidates="
      printf "%s;" "${CANDIDATES[@]}"
      printf "\n"
    fi
  else
    echo "rospack_missing=1"
  fi
} > "$OUT"
