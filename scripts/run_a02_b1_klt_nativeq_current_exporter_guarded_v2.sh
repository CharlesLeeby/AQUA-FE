#!/usr/bin/env bash
set -euo pipefail

# High-level post-STOP B1 repair.  It changes no exporter, tracker, or backend.

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
CONTRACT="$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/backend_quality_contract_b1_current_exporter_v2.json"
CHECKER="$SCRIPT_ROOT/scripts/check_b1_klt_nativeq_current_exporter_contract_v2.py"
RUNNER="$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh"
VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
EXPECTED_TAG=litcmp_a02_4500_6300_preroll_b1_native_r1
EXPECTED_RAW_BAG="$SCRIPT_ROOT/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
EXPECTED_RAW_MANIFEST="${EXPECTED_RAW_BAG}.manifest.json"
EXPECTED_RUN_DIR="$SCRIPT_ROOT/logs/aqualoc_archaeo_vins/external_klt_every2_${EXPECTED_TAG}"

if [[ "$#" -ne 5 || "$1" != "aqualoc_archaeology" || "$2" != "A02" || \
      "$3" != "4500" || "$4" != "6300" || "$5" != "2" ]]; then
  echo "B1 v2 accepts only: aqualoc_archaeology A02 4500 6300 2" >&2
  exit 64
fi
if [[ "${TAG:-$EXPECTED_TAG}" != "$EXPECTED_TAG" || "${RUN_VINS:-0}" != "0" || \
      "${FORCE_RAW:-0}" != "0" || "${FORCE_EXPORT:-0}" != "0" ]]; then
  echo "B1 v2 invocation environment violates the frozen no-retry settings" >&2
  exit 64
fi
DECISION_DIR="${AQUAFE_B1_V2_DECISION_DIR:?missing AQUAFE_B1_V2_DECISION_DIR}"
EXPECTED_DECISION_DIR="$SCRIPT_ROOT/logs/backend_contract_decisions/b1/$EXPECTED_TAG"
if [[ "$(readlink -m "$DECISION_DIR")" != "$EXPECTED_DECISION_DIR" ]]; then
  echo "B1 v2 decision directory is not the frozen unique path" >&2
  exit 64
fi
if [[ ! -f "$EXPECTED_RAW_BAG" || ! -f "$EXPECTED_RAW_MANIFEST" ]]; then
  echo "B1 v2 canonical materialized input pair is missing" >&2
  exit 66
fi
if [[ -e "$EXPECTED_RUN_DIR" || -L "$EXPECTED_RUN_DIR" ]]; then
  echo "B1 v2 no-clobber run directory already exists" >&2
  exit 73
fi
if ! mkdir -- "$DECISION_DIR"; then
  echo "B1 v2 exclusive decision directory already exists" >&2
  exit 73
fi
decision="$DECISION_DIR/b1_current_exporter_v2_decision.json"

set +e
python3 "$CHECKER" --contract "$CONTRACT" --decision-json "$decision"
checker_rc=$?
set -e
mapfile -t decision_entries < <(find "$DECISION_DIR" -mindepth 1 -maxdepth 1 -printf '%f\n' | LC_ALL=C sort)
if [[ "${#decision_entries[@]}" -ne 1 || \
      "${decision_entries[0]}" != "b1_current_exporter_v2_decision.json" ]]; then
  echo "B1 v2 decision directory is not single-writer canonical" >&2
  exit 74
fi
if [[ "$checker_rc" -ne 0 ]]; then
  exit 42
fi

export ROOT="$SCRIPT_ROOT" VINS_WS
export FRONTEND_CONFIG="$SCRIPT_ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
export PREPROCESS=adaptive_clahe PROCESS_SKIPPED_FRAMES=1
export MEASUREMENT_SELECTION=0 FORMAL_THREE_LAYER_EXPORT=0 VINS_SAFE_SOURCE_SELECTION=0
export EXPORT_MAX_FEATURES=350 VINS_MAX_CNT=350 SEMIDENSE_FALLBACK_METHOD=none
export BACKEND_QUALITY_MODE=vins_safe BACKEND_QUALITY_ALPHA=0.65 BACKEND_QUALITY_FLOOR=0.80
export RAW_QUALITY_TO_BACKEND=0 CONSTANT_QUALITY_TO_BACKEND=0
export BACKEND_LEARNED_QUALITY_SCALE=1.0 BACKEND_SP_LG_QUALITY_SCALE=1.0
export BACKEND_XFEAT_QUALITY_SCALE=1.0 BACKEND_LOFTR_QUALITY_SCALE=1.0
export BACKEND_LEARNED_QUALITY_CONST= BACKEND_SP_LG_QUALITY_CONST=
export BACKEND_XFEAT_QUALITY_CONST= BACKEND_LOFTR_QUALITY_CONST=
export VINS_MULTIPLE_THREAD=0 RUN_VINS=0 FORCE_RAW=0 FORCE_EXPORT=0 EXPORT_FEATURES=1
export FRAME_OFFSET=1 TAG="$EXPECTED_TAG" P07_RESULT_LABEL=B1_KLT_NATIVEQ_CURRENT_EXPORTER_V2

if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'arm=B1_klt_nativeq_current_exporter_v2\ncontract_decision=%s\ncommand=' "$decision"
  printf '%q ' bash "$RUNNER" external 2 4500 6300 klt 2
  printf '\n'
  exit 0
fi
exec bash "$RUNNER" external 2 4500 6300 klt 2
