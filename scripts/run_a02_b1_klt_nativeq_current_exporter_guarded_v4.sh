#!/usr/bin/env bash
set -euo pipefail

# Project-side execution repair for the frozen v3 scientific contract.  The
# v3 checker/contract and original exporter/runner remain byte unchanged; this
# wrapper only supplies the ROS variables required by the runner's nounset
# setup path and seals the catkin underlay to Noetic + VINS-Fusion-origin.

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
CONTRACT="$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/backend_quality_contract_b1_current_exporter_v3.json"
CHECKER="$SCRIPT_ROOT/scripts/check_b1_klt_nativeq_current_exporter_contract_v3.py"
RUNNER="$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh"
VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
EXPECTED_TAG=litcmp_a02_4500_6300_preroll_b1_native_r1
RAW_BAG_FIXED="$SCRIPT_ROOT/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
RAW_MANIFEST_FIXED="${RAW_BAG_FIXED}.manifest.json"
RAW_TAR_FIXED="$SCRIPT_ROOT/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"
GT_FIXED="$SCRIPT_ROOT/datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"
RUN_DIR_FIXED="$SCRIPT_ROOT/logs/aqualoc_archaeo_vins/external_klt_every2_${EXPECTED_TAG}"
DECISION_DIR_FIXED="$(readlink -m "$SCRIPT_ROOT/logs/backend_contract_decisions/b1/$EXPECTED_TAG")"
PYCACHE_PREFIX=/tmp/aqua-fe-a02-long-eval-empty-pycache-v1

if [[ "$#" -ne 5 || "$1" != "aqualoc_archaeology" || "$2" != "A02" || \
      "$3" != "4500" || "$4" != "6300" || "$5" != "2" ]]; then
  echo "B1 v4 execution repair accepts only: aqualoc_archaeology A02 4500 6300 2" >&2
  exit 64
fi
if [[ "${TAG:-$EXPECTED_TAG}" != "$EXPECTED_TAG" || "${RUN_VINS:-0}" != "0" || \
      "${FORCE_RAW:-0}" != "0" || "${FORCE_EXPORT:-0}" != "0" ]]; then
  echo "B1 v4 invocation environment violates frozen controls" >&2
  exit 64
fi
DECISION_DIR="${AQUAFE_B1_V4_DECISION_DIR:?missing AQUAFE_B1_V4_DECISION_DIR}"
if [[ "$(readlink -m "$DECISION_DIR")" != "$DECISION_DIR_FIXED" ]]; then
  echo "B1 v4 decision directory is not the frozen unique path" >&2
  exit 64
fi
for required in "$RAW_BAG_FIXED" "$RAW_MANIFEST_FIXED" "$RAW_TAR_FIXED" "$GT_FIXED"; do
  [[ -f "$required" && ! -L "$required" ]] || {
    echo "B1 v4 canonical input missing: $required" >&2
    exit 66
  }
done
if [[ -e "$RUN_DIR_FIXED" || -L "$RUN_DIR_FIXED" ]]; then
  echo "B1 v4 no-clobber run directory already exists" >&2
  exit 73
fi
if [[ -e "$PYCACHE_PREFIX" || -L "$PYCACHE_PREFIX" ]]; then
  echo "B1 v4 frozen Python cache prefix is not absent" >&2
  exit 74
fi
mkdir -- "$DECISION_DIR" || {
  echo "B1 v4 exclusive decision directory exists" >&2
  exit 73
}
decision="$DECISION_DIR/b1_current_exporter_v3_decision.json"

base_env=(
  env -i
  HOME=/home/ma USER=ma LOGNAME=ma SHELL=/bin/bash
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
  LANG=C.UTF-8 LC_ALL=C.UTF-8
  ROS_DISTRO=noetic ROS_MASTER_URI=http://localhost:11341
  CMAKE_PREFIX_PATH=/home/ma/SLAM/VINS-Fusion-origin/devel
  CATKIN_SETUP_UTIL_ARGS=--local\ --extend
  PYTHONNOUSERSITE=1 PYTHONHASHSEED=0
  PYTHONDONTWRITEBYTECODE=1
  PYTHONPYCACHEPREFIX="$PYCACHE_PREFIX"
)
set +e
"${base_env[@]}" /usr/bin/python3 "$CHECKER" \
  --contract "$CONTRACT" --decision-json "$decision"
checker_rc=$?
set -e
mapfile -t entries < <(find "$DECISION_DIR" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
if [[ "${#entries[@]}" -ne 1 || "${entries[0]}" != "b1_current_exporter_v3_decision.json" ]]; then
  echo "B1 v4 decision directory is not canonical single-writer evidence" >&2
  exit 74
fi
[[ "$checker_rc" -eq 0 ]] || exit 42

runner_env=(
  "${base_env[@]}"
  ROOT="$SCRIPT_ROOT" VINS_WS="$VINS_WS"
  RAW_BAG="$RAW_BAG_FIXED" RAW_TAR="$RAW_TAR_FIXED" GT_TXT="$GT_FIXED"
  FEATURE_BAG_OVERRIDE= EXPORT_START_OFFSET= EXPORT_DURATION=
  FRONTEND_CONFIG="$SCRIPT_ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
  PREPROCESS=adaptive_clahe PROCESS_SKIPPED_FRAMES=1 FRAME_OFFSET=1
  MEASUREMENT_SELECTION=0 FORMAL_THREE_LAYER_EXPORT=0 VINS_SAFE_SOURCE_SELECTION=0
  EXPORT_MAX_FEATURES=350 EXPORT_MIN_AGE=2 ZERO_VELOCITY=0
  VINS_MAX_CNT=350 SEMIDENSE_FALLBACK_METHOD=none
  BACKEND_QUALITY_MODE=vins_safe BACKEND_QUALITY_ALPHA=0.65 BACKEND_QUALITY_FLOOR=0.80
  RAW_QUALITY_TO_BACKEND=0 CONSTANT_QUALITY_TO_BACKEND=0
  BACKEND_LEARNED_QUALITY_SCALE=1.0 BACKEND_SP_LG_QUALITY_SCALE=1.0
  BACKEND_XFEAT_QUALITY_SCALE=1.0 BACKEND_LOFTR_QUALITY_SCALE=1.0
  BACKEND_LEARNED_QUALITY_CONST= BACKEND_SP_LG_QUALITY_CONST=
  BACKEND_XFEAT_QUALITY_CONST= BACKEND_LOFTR_QUALITY_CONST=
  VINS_MULTIPLE_THREAD=0 RUN_VINS=0 FORCE_RAW=0 FORCE_EXPORT=0 EXPORT_FEATURES=1
  PORT=11341 TAG="$EXPECTED_TAG" P07_RESULT_LABEL=B1_KLT_NATIVEQ_CURRENT_EXPORTER_V3
)
if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'arm=B1_klt_nativeq_current_exporter_v3_via_execution_repair_v4\n'
  printf 'contract_decision=%s\nenvironment_policy=env-i-noetic-origin-only\ncommand=' "$decision"
  printf '%q ' "${runner_env[@]}" /bin/bash --noprofile --norc "$RUNNER" external 2 4500 6300 klt 2
  printf '\n'
  exit 0
fi
exec "${runner_env[@]}" /bin/bash --noprofile --norc "$RUNNER" external 2 4500 6300 klt 2
