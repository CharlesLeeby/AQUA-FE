#!/usr/bin/env bash
set -euo pipefail

# Frozen B1 KLT/native-q adapter with the same standard family API as B0.

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
ROOT="${ROOT:-$SCRIPT_ROOT}"
VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
CONTRACT="$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
CHECKER="$SCRIPT_ROOT/scripts/check_b1_klt_nativeq_contract_v1.py"
if [[ "${AQUAFE_P07_TEST_HOOKS:-0}" == "1" ]]; then
  CHECKER="${AQUAFE_B1_CHECKER:-$CHECKER}"
fi
DECISION_DIR="${AQUAFE_B1_DECISION_DIR:-$SCRIPT_ROOT/logs/backend_contract_decisions/b1}"
mkdir -p "$DECISION_DIR"
decision="$DECISION_DIR/b1_guard_$(date -u +%Y%m%dT%H%M%SZ)_$$_decision.json"

export ROOT VINS_WS
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
export VINS_MULTIPLE_THREAD=0 RUN_VINS="${RUN_VINS:-0}" FORCE_EXPORT="${FORCE_EXPORT:-1}" EXPORT_FEATURES=1
export P07_RESULT_LABEL=B1_KLT_NATIVEQ_V3

checker_args=(--contract "$CONTRACT" --backend-root "$VINS_WS/src/VINS-Fusion-master" --binary "$VINS_WS/devel/lib/vins/vins_node" --exporter "$SCRIPT_ROOT/uw_frontend/ros/export_vins_features.py" --frontend-config "$FRONTEND_CONFIG" --decision-json "$decision")
if [[ -n "${FEATURE_BAG_OVERRIDE:-}" ]]; then
  attestation="${QUALITY_CONTRACT_ATTESTATION:-${FEATURE_BAG_OVERRIDE}.quality-contract.json}"
  checker_args+=(--feature-bag "$FEATURE_BAG_OVERRIDE" --bag-attestation "$attestation")
fi
python3 "$CHECKER" "${checker_args[@]}" || exit 42

resolve_manifest_path() {
  python3 - "$ROOT/papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv" "$1" "$2" "$3" <<'PY'
import csv,sys
path,family,sequence,field=sys.argv[1:]
rows=[r for r in csv.DictReader(open(path,newline="",encoding="utf-8")) if r["dataset_family"]==family and r["sequence"]==sequence]
if len(rows)!=1 or not rows[0].get(field): raise SystemExit(f"missing {field} for {family}/{sequence}")
print(rows[0][field])
PY
}

resolve_camera_topic() {
  python3 - "$1" <<'PY'
import sys,yaml
print(yaml.safe_load(open(sys.argv[1],encoding="utf-8"))["cam0"]["rostopic"])
PY
}

family="${1:?missing dataset family}"
shift
runner=()
runner_args=()
case "$family" in
  ntnu)
    dataset="${1:?missing dataset}"; start="${2:?missing start}"; duration="${3:?missing duration}"; every_n="${4:-2}"
    export FRAME_OFFSET=1 TAG="${TAG:-isj_p07_b1_${dataset}_s${start}_d${duration}}"
    runner=(bash "$SCRIPT_ROOT/scripts/run_ntnu_vins_eval.sh")
    runner_args=(external "$dataset" "$start" "$duration" klt "$every_n")
    ;;
  aqualoc_archaeology)
    sequence="${1:?missing sequence}"; start="${2:?missing start}"; end="${3:?missing end}"; every_n="${4:-2}"
    seq_int=$((10#${sequence#A})); seq_pad="$(printf '%02d' "$seq_int")"
    export FRAME_OFFSET=1 RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" reference_path)"
    export TAG="${TAG:-isj_p07_b1_a${seq_pad}_${start}_${end}}"
    runner=(bash "$SCRIPT_ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh")
    runner_args=(external "$seq_int" "$start" "$end" klt "$every_n")
    ;;
  aqualoc_harbor)
    sequence="${1:?missing sequence}"; start="${2:?missing start}"; end="${3:?missing end}"; every_n="${4:-2}"
    seq_int=$((10#${sequence#H})); seq_pad="$(printf '%02d' "$seq_int")"
    export FRAME_OFFSET=1 HARBOR_SEQ="$seq_int"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" reference_path)"
    export TAG="${TAG:-isj_p07_b1_h${seq_pad}_${start}_${end}}"
    runner=(bash "$SCRIPT_ROOT/scripts/run_aqualoc_real_vins_eval.sh")
    runner_args=(external "$start" "$end" klt "$every_n")
    ;;
  afrl)
    dataset="${1:?missing dataset}"; start="${2:?missing start}"; duration="${3:?missing duration}"; every_n="${4:-2}"
    base="$ROOT/datasets/full_downloads/afrl_hf"
    export FRAME_OFFSET=0 RAW_BAG="$ROOT/$(resolve_manifest_path afrl "$dataset" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path afrl "$dataset" reference_path)"
    export CAMCHAIN="$base/camera_imu_parameters/camchain_${dataset}.yaml" IMU_YAML="$base/camera_imu_parameters/imu.yaml"
    export CAMERA_KEY=cam0 SRC_IMAGE_TOPIC="$(resolve_camera_topic "$CAMCHAIN")" IMAGE_SCALE=0.5
    export TAG="${TAG:-isj_p07_b1_${dataset}_s${start}_d${duration}}"
    runner=(bash "$SCRIPT_ROOT/scripts/run_afrl_cave_vins_eval.sh")
    runner_args=(external klt "$start" "$duration" "$every_n")
    ;;
  *) echo "unsupported B1 family: $family" >&2; exit 2 ;;
esac

if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'arm=B1_klt_nativeq_v3\ncontract_decision=%s\ncommand=' "$decision"
  printf '%q ' "${runner[@]}" "${runner_args[@]}"
  printf '\n'
  exit 0
fi
exec "${runner[@]}" "${runner_args[@]}"
