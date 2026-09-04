#!/usr/bin/env bash
set -euo pipefail

# Frozen B0 native VINS-origin adapter. Standard family API:
#   ntnu DATASET START_S DURATION_S [EVERY_N]
#   aqualoc_archaeology SEQUENCE START_FRAME END_FRAME [EVERY_N]
#   aqualoc_harbor SEQUENCE START_FRAME END_FRAME [EVERY_N]
#   afrl DATASET START_S DURATION_S [EVERY_N]

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
ROOT="${ROOT:-$SCRIPT_ROOT}"
if [[ "${BACKEND_REPLAY_ONLY:-0}" == "1" ]]; then
  if [[ "$ROOT" != "/home/ma/AQUA-FE_WS" ]]; then
    echo "sealed B0 wrapper requires the frozen ROOT" >&2
    exit 65
  fi
  SCRIPT_ROOT="$ROOT"
  : "${AQUAFE_P07_PYTHON_INTERPRETER:?missing sealed Python interpreter}"
  : "${AQUAFE_P07_SEALED_BOOTSTRAP:?missing sealed runtime bootstrap}"
  : "${AQUAFE_P07_B0_CHECKER_MODULE:?missing sealed B0 checker module}"
  : "${AQUAFE_P07_NATIVEQ_CONTRACT:?missing sealed native-q contract}"
  : "${AQUAFE_P07_RUNNER_NTNU:?missing sealed NTNU runner}"
  : "${AQUAFE_P07_RUNNER_AQUALOC_ARCHAEOLOGY:?missing sealed archaeology runner}"
  : "${AQUAFE_P07_RUNNER_AQUALOC_HARBOR:?missing sealed harbor runner}"
  : "${AQUAFE_P07_RUNNER_AFRL:?missing sealed AFRL runner}"
fi
VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
CONTRACT="${AQUAFE_P07_NATIVEQ_CONTRACT:-$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json}"
CHECKER="$SCRIPT_ROOT/scripts/check_b0_vins_origin_identity_v1.py"
if [[ "${AQUAFE_P07_TEST_HOOKS:-0}" == "1" ]]; then
  CHECKER="${AQUAFE_B0_CHECKER:-$CHECKER}"
fi
DECISION_DIR="${AQUAFE_B0_DECISION_DIR:-$SCRIPT_ROOT/logs/backend_contract_decisions/b0}"
mkdir -p "$DECISION_DIR"
decision="$DECISION_DIR/b0_guard_$(date -u +%Y%m%dT%H%M%SZ)_$$_decision.json"

python_interpreter="${AQUAFE_P07_PYTHON_INTERPRETER:-python3}"
checker_command=("$python_interpreter" "$CHECKER")
if [[ "${BACKEND_REPLAY_ONLY:-0}" == "1" ]]; then
  checker_command=(
    "$AQUAFE_P07_PYTHON_INTERPRETER" -I "$AQUAFE_P07_SEALED_BOOTSTRAP"
    "$AQUAFE_P07_B0_CHECKER_MODULE"
  )
fi
"${checker_command[@]}" \
  --contract "$CONTRACT" \
  --vins-workspace "$VINS_WS" \
  --backend-root "$VINS_WS/src/VINS-Fusion-master" \
  --binary "${AQUAFE_P07_VINS_BINARY:-$VINS_WS/devel/lib/vins/vins_node}" \
  --binary-authority-path "$VINS_WS/devel/lib/vins/vins_node" \
  --decision-json "$decision" || exit 42

resolve_manifest_path() {
  "$python_interpreter" - "$ROOT/papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv" "$1" "$2" "$3" <<'PY'
import csv,sys
path,family,sequence,field=sys.argv[1:]
rows=[r for r in csv.DictReader(open(path,newline="",encoding="utf-8")) if r["dataset_family"]==family and r["sequence"]==sequence]
if len(rows)!=1 or not rows[0].get(field): raise SystemExit(f"missing {field} for {family}/{sequence}")
print(rows[0][field])
PY
}

resolve_camera_topic() {
  "$python_interpreter" - "$1" <<'PY'
import sys,yaml
print(yaml.safe_load(open(sys.argv[1],encoding="utf-8"))["cam0"]["rostopic"])
PY
}

family="${1:?missing dataset family}"
shift
runner=()
runner_args=()
export ROOT VINS_WS
export VINS_MULTIPLE_THREAD=0
export RUN_VINS="${RUN_VINS:-1}"
export EXPORT_FEATURES=0
export FORCE_EXPORT=0
export P07_RESULT_LABEL=B0_NATIVE_VINS_ORIGIN_V1

case "$family" in
  ntnu)
    dataset="${1:?missing dataset}"; start="${2:?missing start}"; duration="${3:?missing duration}"; every_n="${4:-2}"
    export TAG="${TAG:-isj_p07_b0_${dataset}_s${start}_d${duration}}"
    runner=(bash "${AQUAFE_P07_RUNNER_NTNU:-$SCRIPT_ROOT/scripts/run_ntnu_vins_eval.sh}")
    runner_args=(origin "$dataset" "$start" "$duration" klt "$every_n")
    ;;
  aqualoc_archaeology)
    sequence="${1:?missing sequence}"; start="${2:?missing start}"; end="${3:?missing end}"; every_n="${4:-2}"
    seq_int=$((10#${sequence#A})); seq_pad="$(printf '%02d' "$seq_int")"
    if [[ "${BACKEND_REPLAY_ONLY:-0}" == "1" ]]; then
      : "${RAW_TAR:?formal B0 archaeology RAW_TAR must be pre-resolved}"
      : "${GT_TXT:?formal B0 archaeology GT_TXT must be pre-resolved}"
    else
      export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" raw_input_path)"
      export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" reference_path)"
    fi
    export TAG="${TAG:-isj_p07_b0_a${seq_pad}_${start}_${end}}"
    runner=(bash "${AQUAFE_P07_RUNNER_AQUALOC_ARCHAEOLOGY:-$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh}")
    runner_args=(origin "$seq_int" "$start" "$end" klt "$every_n")
    ;;
  aqualoc_harbor)
    sequence="${1:?missing sequence}"; start="${2:?missing start}"; end="${3:?missing end}"; every_n="${4:-2}"
    seq_int=$((10#${sequence#H})); seq_pad="$(printf '%02d' "$seq_int")"
    export HARBOR_SEQ="$seq_int"
    if [[ "${BACKEND_REPLAY_ONLY:-0}" == "1" ]]; then
      : "${RAW_TAR:?formal B0 harbor RAW_TAR must be pre-resolved}"
      : "${GT_TXT:?formal B0 harbor GT_TXT must be pre-resolved}"
    else
      export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" raw_input_path)"
      export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" reference_path)"
    fi
    export TAG="${TAG:-isj_p07_b0_h${seq_pad}_${start}_${end}}"
    runner=(bash "${AQUAFE_P07_RUNNER_AQUALOC_HARBOR:-$SCRIPT_ROOT/scripts/run_aqualoc_real_vins_eval.sh}")
    runner_args=(origin "$start" "$end" klt "$every_n")
    ;;
  afrl)
    dataset="${1:?missing dataset}"; start="${2:?missing start}"; duration="${3:?missing duration}"; every_n="${4:-2}"
    base="$ROOT/datasets/full_downloads/afrl_hf"
    if [[ "${BACKEND_REPLAY_ONLY:-0}" == "1" ]]; then
      : "${SHORT_BAG:?formal B0 AFRL SHORT_BAG must be sealed}"
      if [[ "$SHORT_BAG" != /proc/self/fd/* || "${PREPARE_BAG:-}" != "0" ]]; then
        echo "formal B0 AFRL input is not a sealed pre-materialized bag" >&2
        exit 66
      fi
      : "${GT_TXT:?formal B0 AFRL GT_TXT must be pre-resolved}"
      : "${CAMCHAIN:?formal B0 AFRL CAMCHAIN must be pre-resolved}"
      : "${IMU_YAML:?formal B0 AFRL IMU_YAML must be pre-resolved}"
      : "${SRC_IMAGE_TOPIC:?formal B0 AFRL camera topic must be pre-resolved}"
    else
      export RAW_BAG="$ROOT/$(resolve_manifest_path afrl "$dataset" raw_input_path)"
      export GT_TXT="$ROOT/$(resolve_manifest_path afrl "$dataset" reference_path)"
      export CAMCHAIN="$base/camera_imu_parameters/camchain_${dataset}.yaml"
      export IMU_YAML="$base/camera_imu_parameters/imu.yaml"
      export SRC_IMAGE_TOPIC="$(resolve_camera_topic "$CAMCHAIN")"
    fi
    export CAMERA_KEY=cam0 IMAGE_SCALE=0.5
    export TAG="${TAG:-isj_p07_b0_${dataset}_s${start}_d${duration}}"
    runner=(bash "${AQUAFE_P07_RUNNER_AFRL:-$SCRIPT_ROOT/scripts/run_afrl_cave_vins_eval.sh}")
    runner_args=(origin klt "$start" "$duration" "$every_n")
    ;;
  *) echo "unsupported B0 family: $family" >&2; exit 2 ;;
esac

if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'arm=B0_native_vins_origin_v1\nidentity_decision=%s\ncommand=' "$decision"
  printf '%q ' "${runner[@]}" "${runner_args[@]}"
  printf '\n'
  exit 0
fi
exec "${runner[@]}" "${runner_args[@]}"
