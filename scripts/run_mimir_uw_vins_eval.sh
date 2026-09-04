#!/usr/bin/env bash
set -euo pipefail

# MIMIR-UW monocular frontend + external-feature VINS-Fusion runner.
#
# Usage:
#   bash scripts/run_mimir_uw_vins_eval.sh METHOD ENVIRONMENT TRACK START_OFFSET DURATION EVERY_N
#
# Example:
#   bash scripts/run_mimir_uw_vins_eval.sh klt SeaFloor track0 0 20 1

METHOD="${1:-klt}"
ENVIRONMENT="${2:-SeaFloor}"
TRACK="${3:-track0}"
START_OFFSET="${4:-0.0}"
DURATION="${5:-20.0}"
EVERY_N="${6:-1}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
MIMIR_ROOT="${MIMIR_ROOT:-/mnt/data/AQUA-FE_WS/datasets/mimir_uw/slam_subset}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
SEQUENCE_DIR="${SEQUENCE_DIR:-$MIMIR_ROOT/$ENVIRONMENT/$TRACK}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml}"

IMAGE_TOPIC="${IMAGE_TOPIC:-/camera/image_raw}"
IMAGE1_TOPIC="${IMAGE1_TOPIC:-/camera1/image_raw}"
IMU_TOPIC="${IMU_TOPIC:-/imu0}"
GT_TOPIC="${GT_TOPIC:-/mimir/ground_truth}"
FEATURE_TOPIC="${FEATURE_TOPIC:-/feature_tracker/feature}"
SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-none}"
PREPROCESS="${PREPROCESS:-adaptive_clahe}"

SAFE_START="${START_OFFSET//./p}"
SAFE_DURATION="${DURATION//./p}"
TAG="${TAG:-mimir_${ENVIRONMENT}_${TRACK}_${METHOD}_s${SAFE_START}_d${SAFE_DURATION}_e${EVERY_N}}"
RUN_DIR="${RUN_DIR:-$ROOT/logs/mimir_uw_vins/$TAG}"
RAW_BAG="${RAW_BAG:-$RUN_DIR/mimir_raw.bag}"
EXTRA_PLAY_BAG="${EXTRA_PLAY_BAG:-}"
CAMERA_CONFIG="${CAMERA_CONFIG:-$RUN_DIR/mimir_cam0_pinhole.yaml}"
CAMERA1_CONFIG="${CAMERA1_CONFIG:-$RUN_DIR/mimir_cam1_pinhole.yaml}"
VINS_CONFIG="${VINS_CONFIG:-$RUN_DIR/vins_mimir_external.yaml}"
FEATURE_BAG="${FEATURE_BAG:-$RUN_DIR/features.bag}"
VINS_OUTPUT="${VINS_OUTPUT:-$RUN_DIR/vins_output}"
VINS_LOG="${VINS_LOG:-$RUN_DIR/vins.log}"
APE_REPORT="${APE_REPORT:-$RUN_DIR/ape.txt}"

PREPARE_BAG="${PREPARE_BAG:-1}"
FORCE_RAW="${FORCE_RAW:-0}"
EXPORT_FEATURES="${EXPORT_FEATURES:-1}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
RUN_VINS="${RUN_VINS:-1}"
VINS_INPUT_MODE="${VINS_INPUT_MODE:-features}"
VINS_STEREO="${VINS_STEREO:-0}"
VINS_USE_IMU="${VINS_USE_IMU:-1}"
PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}"
# Keep the full persistent KLT backbone for VINS initialization. The optional
# geometry selector is useful for later ablations but can shorten MIMIR tracks
# below VINS-Fusion's >20-correspondence initialization gate.
MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-0}"
EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}"
EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}"
FRAME_OFFSET="${FRAME_OFFSET:-0}"

PLAY_RATE="${PLAY_RATE:-1.0}"
ROSBAG_PLAY_DELAY="${ROSBAG_PLAY_DELAY:-2}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-2}"
DRAIN_STABLE_S="${DRAIN_STABLE_S:-4}"
DRAIN_TIMEOUT_S="${DRAIN_TIMEOUT_S:-120}"
WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT="${WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT:-30}"
PORT="${PORT:-13140}"
TIME_OFFSET="${TIME_OFFSET:-0.0}"
CAMERA_AXIS_MODE="${CAMERA_AXIS_MODE:-opencv-optical}"

# MIMIR-UW is synthetic and its IMU is generated with essentially zero sensor
# bias.  Leaving the bias states unconstrained lets a short/noisy visual
# initialization explain orientation errors as large BA/BG values, which then
# leaks gravity into horizontal acceleration.  The test VINS fork understands
# these optional priors; an unmodified upstream binary simply ignores them.
MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR="${MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR:-1}"
if [[ "$MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR" == "1" ]]; then
  export VINS_SYNTHETIC_ACC_BIAS_SIGMA="${VINS_SYNTHETIC_ACC_BIAS_SIGMA:-0.01}"
  export VINS_SYNTHETIC_GYR_BIAS_SIGMA="${VINS_SYNTHETIC_GYR_BIAS_SIGMA:-0.001}"
  # Repropagation after resetting the initializer bias remains available as a
  # diagnostic, but cross-window tests showed that enabling it by default
  # helps one sequence and harms another.  Keep the validated global default
  # off; the nonlinear zero-bias prior itself remains enabled.
  export VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT="${VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT:-0}"
fi
export VINS_INITIAL_DIAGNOSTICS="${VINS_INITIAL_DIAGNOSTICS:-1}"
export VINS_STATE_DIAGNOSTICS="${VINS_STATE_DIAGNOSTICS:-1}"

mkdir -p "$RUN_DIR" "$VINS_OUTPUT"

if [[ "$VINS_INPUT_MODE" != "features" && "$VINS_INPUT_MODE" != "images" ]]; then
  echo "VINS_INPUT_MODE must be 'features' or 'images': $VINS_INPUT_MODE" >&2
  exit 2
fi
# In feature mode, VINS_STEREO=1 expects each feature message to contain
# same-ID camera_id=0/1 observations. The MIMIR stereo-LK augmentation script
# materializes that contract without requiring raw-image subscriptions.
if [[ "$VINS_USE_IMU" != "0" && "$VINS_USE_IMU" != "1" ]]; then
  echo "VINS_USE_IMU must be 0 or 1: $VINS_USE_IMU" >&2
  exit 2
fi
VINS_IMAGE_TOPIC="/unused/image"
if [[ "$VINS_INPUT_MODE" == "images" ]]; then
  VINS_IMAGE_TOPIC="$IMAGE_TOPIC"
fi

source /opt/ros/noetic/setup.bash
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ ! -d "$SEQUENCE_DIR" ]]; then
  echo "missing MIMIR sequence directory: $SEQUENCE_DIR" >&2
  exit 2
fi
if [[ ! -f "$FRONTEND_CONFIG" ]]; then
  echo "missing frontend config: $FRONTEND_CONFIG" >&2
  exit 2
fi

if [[ "$FORCE_RAW" == "1" ]]; then
  rm -f "$RAW_BAG" "$RAW_BAG.manifest.json"
fi
if [[ "$PREPARE_BAG" == "1" && ! -f "$RAW_BAG" ]]; then
  BAG_ARGS=(
    --sequence-dir "$SEQUENCE_DIR"
    --output-bag "$RAW_BAG"
    --start-offset "$START_OFFSET"
    --duration "$DURATION"
    --image-topic "$IMAGE_TOPIC"
    --imu-topic "$IMU_TOPIC"
    --gt-topic "$GT_TOPIC"
  )
  if [[ "$VINS_STEREO" == "1" ]]; then
    BAG_ARGS+=(--image1-topic "$IMAGE1_TOPIC")
  fi
  "$PYTHON_BIN" -m uw_frontend.datasets.mimir_uw_to_rosbag "${BAG_ARGS[@]}"
fi
if [[ ! -f "$RAW_BAG" ]]; then
  echo "missing prepared MIMIR bag: $RAW_BAG" >&2
  exit 2
fi

VINS_CONFIG_ARGS=(
  --sequence-dir "$SEQUENCE_DIR"
  --camera-config "$CAMERA_CONFIG"
  --vins-config "$VINS_CONFIG"
  --output-path "$VINS_OUTPUT"
  --imu-topic "$IMU_TOPIC"
  --image-topic "$VINS_IMAGE_TOPIC"
  --camera-axis-mode "$CAMERA_AXIS_MODE"
  --use-imu "$VINS_USE_IMU"
  --td "$TIME_OFFSET"
)
if [[ "$VINS_STEREO" == "1" ]]; then
  VINS_CONFIG_ARGS+=(
    --camera1-config "$CAMERA1_CONFIG"
    --image1-topic "$IMAGE1_TOPIC"
  )
fi
append_vins_config_value() {
  local variable_name="$1" flag="$2" value
  value="${!variable_name:-}"
  if [[ -n "$value" ]]; then
    VINS_CONFIG_ARGS+=("$flag" "$value")
  fi
}
append_vins_config_value VINS_MAX_SOLVER_TIME --max-solver-time
append_vins_config_value VINS_MAX_NUM_ITERATIONS --max-num-iterations
append_vins_config_value VINS_MAX_CNT --max-cnt
append_vins_config_value VINS_MIN_DIST --min-dist
append_vins_config_value VINS_FREQ --freq
append_vins_config_value VINS_KEYFRAME_PARALLAX --keyframe-parallax
append_vins_config_value VINS_F_THRESHOLD --f-threshold
append_vins_config_value VINS_ACC_N --acc-n
append_vins_config_value VINS_GYR_N --gyr-n
append_vins_config_value VINS_ACC_W --acc-w
append_vins_config_value VINS_GYR_W --gyr-w
append_vins_config_value VINS_G_NORM --g-norm
"$PYTHON_BIN" -m uw_frontend.datasets.mimir_uw_vins_config "${VINS_CONFIG_ARGS[@]}"

if [[ "$FORCE_EXPORT" == "1" ]]; then
  rm -f "$FEATURE_BAG" "$RUN_DIR/frontend_metrics.csv"
fi
if [[ "$EXPORT_FEATURES" == "1" && ! -f "$FEATURE_BAG" ]]; then
  EXPORT_ARGS=(
    --bag "$RAW_BAG"
    --image-topic "$IMAGE_TOPIC"
    --camera-config "$CAMERA_CONFIG"
    --output-bag "$FEATURE_BAG"
    --config "$FRONTEND_CONFIG"
    --method "$METHOD"
    --semidense-fallback-method "$SEMIDENSE_FALLBACK_METHOD"
    --feature-topic "$FEATURE_TOPIC"
    --every-n "$EVERY_N"
    --frame-offset "$FRAME_OFFSET"
    --export-max-features "$EXPORT_MAX_FEATURES"
    --export-min-age "$EXPORT_MIN_AGE"
    --preprocess "$PREPROCESS"
    --timestamp-source header
    --max-header-stamp-delta 0.25
    --invalid-header-policy skip
    --copy-topic "$IMU_TOPIC"
    --copy-topic "$GT_TOPIC"
    --metrics-csv "$RUN_DIR/frontend_metrics.csv"
  )
  if [[ "$PROCESS_SKIPPED_FRAMES" == "1" ]]; then
    EXPORT_ARGS+=(--process-skipped-frames)
  fi
  if [[ "$MEASUREMENT_SELECTION" == "1" ]]; then
    EXPORT_ARGS+=(--measurement-selection)
  fi

  # Dataset runners must translate paper-profile environment variables into
  # exporter CLI arguments.  Without this bridge, the MIMIR profile name says
  # proposed_safe while the exporter silently runs its generic defaults.
  append_export_flag_from_env() {
    local variable_name="$1" flag="$2" value
    value="${!variable_name:-}"
    if [[ "$value" == "1" ]]; then
      EXPORT_ARGS+=("$flag")
    fi
  }
  append_export_value_from_env() {
    local variable_name="$1" flag="$2" value
    value="${!variable_name:-}"
    if [[ -n "$value" && "$value" != "none" ]]; then
      EXPORT_ARGS+=("$flag" "$value")
    fi
  }

  append_export_flag_from_env FORMAL_THREE_LAYER_EXPORT --formal-three-layer-export
  append_export_flag_from_env FORMAL_EXPORT_PRESERVE_INPUT_BACKBONE --formal-export-preserve-input-backbone
  append_export_flag_from_env FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE --formal-export-allow-sparse-backbone
  append_export_flag_from_env FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK --formal-export-adaptive-mirror-fallback
  append_export_flag_from_env EXPORT_CLASSICAL_MIRROR_BACKBONE --export-classical-mirror-backbone
  append_export_flag_from_env FORMAL_EXPORT_LEGACY_LOFTR_RESCUE --formal-export-legacy-loftr-rescue
  append_export_flag_from_env FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS --formal-export-allow-low-parallax-sidecars
  append_export_flag_from_env FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR --formal-export-low-texture-active-sidecar
  append_export_value_from_env MIRROR_MEASUREMENT_SELECTION_POLICY --mirror-measurement-selection-policy
  # Preserve the high-ID learned lineage after a confirmed LoFTR seed is
  # handed to the ordinary LK carrier. Other dataset runners already expose
  # this exporter contract; without the bridge MIMIR silently drops back to a
  # classical ID as soon as the source label changes from loftr_confirmed.
  append_export_flag_from_env LEARNED_EXPORT_LOFTR_SOURCE_MEMORY --learned-export-loftr-source-memory

  append_export_value_from_env BACKEND_QUALITY_MODE --backend-quality-mode
  append_export_value_from_env BACKEND_QUALITY_FLOOR --backend-quality-floor
  append_export_value_from_env BACKEND_QUALITY_ALPHA --backend-quality-alpha
  append_export_value_from_env BACKEND_LOFTR_QUALITY_SCALE --backend-loftr-quality-scale

  append_export_flag_from_env VINS_SAFE_SOURCE_SELECTION --vins-safe-source-selection
  append_export_value_from_env VINS_SAFE_WARMUP_FRAMES --vins-safe-warmup-frames
  append_export_value_from_env VINS_SAFE_MAX_TOTAL --vins-safe-max-total
  append_export_value_from_env VINS_SAFE_MAX_LEARNED --vins-safe-max-learned
  append_export_value_from_env VINS_SAFE_MAX_RECOVERED --vins-safe-max-recovered
  append_export_value_from_env VINS_SAFE_MIN_LEARNED_AGE --vins-safe-min-learned-age
  append_export_flag_from_env VINS_SAFE_PRESERVE_CLASSICAL_BUDGET --vins-safe-preserve-classical-budget
  append_export_value_from_env VINS_INIT_KLT_ONLY_FRAMES --vins-init-klt-only-frames

  append_export_flag_from_env INIT_PARALLAX_GATE --init-parallax-gate
  append_export_value_from_env INIT_PARALLAX_THRESHOLD_PX --init-parallax-threshold-px
  append_export_value_from_env INIT_PARALLAX_SKIP_FEATURE_FRAMES --init-parallax-skip-feature-frames
  append_export_flag_from_env INIT_PARALLAX_ADAPTIVE_SKIP --init-parallax-adaptive-skip
  append_export_flag_from_env INIT_LOFTR_SIDECAR_RESCUE --init-loftr-sidecar-rescue
  append_export_value_from_env INIT_LOFTR_SIDECAR_MAX_COUNT --init-loftr-sidecar-max-count
  append_export_value_from_env LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES --low-parallax-learned-holdoff-frames

  append_export_flag_from_env LEARNED_EXPORT_DEGRADATION_GATE --learned-export-degradation-gate
  append_export_value_from_env LEARNED_EXPORT_MIN_CLASSICAL_TRACKS --learned-export-min-classical-tracks
  append_export_value_from_env LEARNED_EXPORT_MIN_CLASSICAL_GRID --learned-export-min-classical-grid
  append_export_value_from_env LEARNED_EXPORT_MIN_AGE --learned-export-min-age
  append_export_value_from_env LEARNED_EXPORT_MIN_QUALITY --learned-export-min-quality
  append_export_value_from_env LEARNED_EXPORT_MIN_NCC --learned-export-min-ncc
  append_export_value_from_env LEARNED_EXPORT_MAX_FB --learned-export-max-fb
  append_export_value_from_env LEARNED_EXPORT_LOFTR_MIN_QUALITY --learned-export-loftr-min-quality
  append_export_value_from_env LEARNED_EXPORT_LOFTR_MIN_NCC --learned-export-loftr-min-ncc
  append_export_value_from_env LEARNED_EXPORT_LOFTR_MAX_FB --learned-export-loftr-max-fb

  append_export_flag_from_env LEARNED_EXPORT_BENEFIT_GATE --learned-export-benefit-gate
  append_export_value_from_env LEARNED_EXPORT_MIN_GRID_GAIN --learned-export-min-grid-gain
  append_export_value_from_env LEARNED_EXPORT_MIN_NEW_CELLS --learned-export-min-new-cells
  append_export_value_from_env LEARNED_EXPORT_MIN_NEW_CELL_RATIO --learned-export-min-new-cell-ratio
  append_export_value_from_env LEARNED_EXPORT_MAX_PER_NEW_CELL --learned-export-max-per-new-cell
  append_export_value_from_env LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS --learned-export-sidecar-max-observations

  append_export_flag_from_env LEARNED_EXPORT_LOFTR_PLANAR_RESCUE --learned-export-loftr-planar-rescue
  append_export_value_from_env LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT --learned-export-loftr-planar-max-count
  append_export_value_from_env LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX --learned-export-loftr-planar-min-classical-motion-px
  append_export_flag_from_env LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE --learned-export-loftr-weak-cell-rescue
  append_export_value_from_env LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT --learned-export-loftr-weak-cell-max-count
  append_export_value_from_env LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS --learned-export-loftr-rescue-max-classical-tracks
  append_export_value_from_env LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX --learned-export-loftr-support-max-init-parallax-px
  append_export_value_from_env LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX --learned-export-loftr-support-max-classical-motion-px
  append_export_value_from_env LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT --learned-export-loftr-min-export-count
  append_export_value_from_env LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES --learned-export-loftr-support-cooldown-frames
  append_export_flag_from_env LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT --learned-export-allow-early-loftr-support
  append_export_flag_from_env LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_GATE --learned-export-loftr-seeded-continuation-gate
  append_export_value_from_env LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_MAX_GAP --learned-export-loftr-seeded-continuation-max-gap
  append_export_value_from_env EXPORT_MAX_FRAMES --max-frames

  append_export_flag_from_env LEARNED_EXPORT_GEOMETRY_GATE --learned-export-geometry-gate
  append_export_flag_from_env LEARNED_EXPORT_REQUIRE_CONFIRMED --learned-export-require-confirmed
  "$PYTHON_BIN" -m uw_frontend.ros.export_vins_features "${EXPORT_ARGS[@]}"
fi
if [[ "$VINS_INPUT_MODE" == "features" && ! -f "$FEATURE_BAG" ]]; then
  echo "missing exported MIMIR feature bag: $FEATURE_BAG" >&2
  exit 2
fi

if [[ "$RUN_VINS" == "1" ]]; then
  rm -f "$VINS_OUTPUT/vio.csv" "$VINS_LOG" "$APE_REPORT"
  source "$VINS_WS/devel/setup.bash"
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
  if [[ "$VINS_INPUT_MODE" == "images" ]]; then
    PLAY_BAG="$RAW_BAG"
    VINS_SENSOR_TOPICS=("$IMAGE_TOPIC")
    if [[ "$VINS_STEREO" == "1" ]]; then
      VINS_SENSOR_TOPICS+=("$IMAGE1_TOPIC")
    fi
  else
    PLAY_BAG="$FEATURE_BAG"
    VINS_SENSOR_TOPICS=("$FEATURE_TOPIC")
  fi
  PLAY_BAGS=("$PLAY_BAG")
  if [[ -n "$EXTRA_PLAY_BAG" ]]; then
    if [[ ! -f "$EXTRA_PLAY_BAG" ]]; then
      echo "missing extra replay bag: $EXTRA_PLAY_BAG" >&2
      exit 2
    fi
    PLAY_BAGS+=("$EXTRA_PLAY_BAG")
  fi
  if [[ "$VINS_USE_IMU" == "1" ]]; then
    VINS_SENSOR_TOPICS+=("$IMU_TOPIC")
  fi
  "$PYTHON_BIN" "$ROOT/scripts/wait_for_ros_subscribers.py" \
    "${VINS_SENSOR_TOPICS[@]}" \
    --timeout "$WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT"

  rosbag play "${PLAY_BAGS[@]}" \
    --clock --rate "$PLAY_RATE" --delay "$ROSBAG_PLAY_DELAY" --quiet
  "$PYTHON_BIN" "$ROOT/scripts/wait_for_vins_drain.py" \
    --pid "$VINS_PID" \
    --file "$VINS_LOG" \
    --file "$VINS_OUTPUT/vio.csv" \
    --min-wait-s "$POST_PLAY_SLEEP" \
    --stable-s "$DRAIN_STABLE_S" \
    --timeout-s "$DRAIN_TIMEOUT_S"

  EVALUATOR_ARGS=(
    --vins-csv "$VINS_OUTPUT/vio.csv"
    --bag "$PLAY_BAG"
    --gt-topic "$GT_TOPIC"
    --vins-log "$VINS_LOG"
  )
  if [[ -n "${EVAL_SCORE_START_OFFSET_S:-}" ]]; then
    EVALUATOR_ARGS+=(--score-start-offset-s "$EVAL_SCORE_START_OFFSET_S")
  fi
  if [[ -n "${EVAL_SCORE_DURATION_S:-}" ]]; then
    EVALUATOR_ARGS+=(--score-duration-s "$EVAL_SCORE_DURATION_S")
  fi
  "$PYTHON_BIN" "$ROOT/scripts/evaluate_vins_sim_ape.py" \
    "${EVALUATOR_ARGS[@]}" | tee "$APE_REPORT"
fi

{
  echo "run_dir=$RUN_DIR"
  echo "sequence_dir=$SEQUENCE_DIR"
  echo "raw_bag=$RAW_BAG"
  echo "extra_play_bag=${EXTRA_PLAY_BAG:-none}"
  echo "feature_bag=$FEATURE_BAG"
  echo "camera_config=$CAMERA_CONFIG"
  echo "camera1_config=${CAMERA1_CONFIG:-disabled}"
  echo "vins_config=$VINS_CONFIG"
  echo "method=$METHOD"
  echo "environment=$ENVIRONMENT"
  echo "track=$TRACK"
  echo "start_offset=$START_OFFSET"
  echo "duration=$DURATION"
  echo "every_n=$EVERY_N"
  echo "frame_offset=$FRAME_OFFSET"
  echo "formal_three_layer_export=${FORMAL_THREE_LAYER_EXPORT:-0}"
  echo "formal_export_preserve_input_backbone=${FORMAL_EXPORT_PRESERVE_INPUT_BACKBONE:-0}"
  echo "export_classical_mirror_backbone=${EXPORT_CLASSICAL_MIRROR_BACKBONE:-0}"
  echo "formal_export_adaptive_mirror_fallback=${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-0}"
  echo "learned_export_loftr_source_memory=${LEARNED_EXPORT_LOFTR_SOURCE_MEMORY:-0}"
  echo "learned_export_loftr_seeded_continuation_gate=${LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_GATE:-0}"
  echo "learned_export_loftr_seeded_continuation_max_gap=${LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_MAX_GAP:-1}"
  echo "export_max_frames=${EXPORT_MAX_FRAMES:-full}"
  echo "vins_init_klt_only_frames=${VINS_INIT_KLT_ONLY_FRAMES:-0}"
  echo "init_parallax_skip_feature_frames=${INIT_PARALLAX_SKIP_FEATURE_FRAMES:-0}"
  echo "init_parallax_adaptive_skip=${INIT_PARALLAX_ADAPTIVE_SKIP:-0}"
  echo "vins_safe_preserve_classical_budget=${VINS_SAFE_PRESERVE_CLASSICAL_BUDGET:-0}"
  echo "run_vins=$RUN_VINS"
  echo "vins_input_mode=$VINS_INPUT_MODE"
  echo "vins_stereo=$VINS_STEREO"
  echo "vins_use_imu=$VINS_USE_IMU"
  echo "time_offset=$TIME_OFFSET"
  echo "camera_axis_mode=$CAMERA_AXIS_MODE"
  echo "eval_score_start_offset_s=${EVAL_SCORE_START_OFFSET_S:-0}"
  echo "eval_score_duration_s=${EVAL_SCORE_DURATION_S:-full}"
  echo "vins_acc_n=${VINS_ACC_N:-official_default}"
  echo "vins_gyr_n=${VINS_GYR_N:-official_default}"
  echo "vins_acc_w=${VINS_ACC_W:-official_default}"
  echo "vins_gyr_w=${VINS_GYR_W:-official_default}"
  echo "vins_g_norm=${VINS_G_NORM:-9.81}"
  echo "mimir_enable_synthetic_bias_prior=$MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR"
  echo "vins_synthetic_acc_bias_sigma=${VINS_SYNTHETIC_ACC_BIAS_SIGMA:-disabled}"
  echo "vins_synthetic_gyr_bias_sigma=${VINS_SYNTHETIC_GYR_BIAS_SIGMA:-disabled}"
  echo "vins_synthetic_reset_biases_after_alignment=${VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT:-disabled}"
  echo "vins_initial_min_scale=${VINS_INITIAL_MIN_SCALE:-disabled}"
  echo "vins_initial_max_scale=${VINS_INITIAL_MAX_SCALE:-disabled}"
  echo "vins_initial_ransac_seed=${VINS_INITIAL_RANSAC_SEED:-unset}"
  echo "vins_initial_max_gyro_bias_delta=${VINS_INITIAL_MAX_GYRO_BIAS_DELTA:-disabled}"
  echo "vins_initial_rollback_on_failure=${VINS_INITIAL_ROLLBACK_ON_FAILURE:-disabled}"
  echo "vins_initial_skip_gyro_bias_calibration=${VINS_INITIAL_SKIP_GYRO_BIAS_CALIBRATION:-disabled}"
  echo "vins_enable_failure_detection=${VINS_ENABLE_FAILURE_DETECTION:-disabled}"
  echo "vins_failure_max_speed=${VINS_FAILURE_MAX_SPEED:-disabled}"
  echo "vins_drain_stable_s=$DRAIN_STABLE_S"
  echo "vins_drain_timeout_s=$DRAIN_TIMEOUT_S"
} | tee "$RUN_DIR/replay_manifest.txt"
