#!/usr/bin/env bash
set -euo pipefail

# Independent KLT fallback for a failed native-q backend contract guard.
# This is an operational abstention and never a proposed-arm result.

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
family="${1:?usage: run_isj_classical_contract_fallback_v4.sh DATASET_FAMILY ...}"

resolve_manifest_path() {
  local dataset_family="$1"
  local sequence="$2"
  local field="$3"
  python3 - "$ROOT/papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv" \
    "$dataset_family" "$sequence" "$field" <<'PY'
import csv
import sys

path, family, sequence, field = sys.argv[1:]
with open(path, newline="", encoding="utf-8") as handle:
    rows = [
        row for row in csv.DictReader(handle)
        if row["dataset_family"] == family and row["sequence"] == sequence
    ]
if len(rows) != 1:
    raise SystemExit(f"expected one eligibility row for {family}/{sequence}, found {len(rows)}")
value = rows[0].get(field, "")
if not value:
    raise SystemExit(f"missing {field} for {family}/{sequence}")
print(value)
PY
}

resolve_camera_topic() {
  local camchain="$1"
  local camera_key="$2"
  python3 - "$camchain" "$camera_key" <<'PY'
import sys
import yaml

path, camera_key = sys.argv[1:]
data = yaml.safe_load(open(path, encoding="utf-8"))
print(data[camera_key]["rostopic"])
PY
}

export ROOT
export FRONTEND_CONFIG="$ROOT/uw_frontend/configs/klt_frontend.yaml"
export PREPROCESS=adaptive_clahe
export PROCESS_SKIPPED_FRAMES=1
export METHOD_DEFAULT=klt
export SEMIDENSE_FALLBACK_METHOD=none
export BACKEND_QUALITY_MODE=const
export BACKEND_QUALITY_ALPHA=0.65
export BACKEND_QUALITY_FLOOR=
export RAW_QUALITY_TO_BACKEND=0
export CONSTANT_QUALITY_TO_BACKEND=1
export BACKEND_LEARNED_QUALITY_SCALE=1.0
export BACKEND_SP_LG_QUALITY_SCALE=1.0
export BACKEND_XFEAT_QUALITY_SCALE=1.0
export BACKEND_LOFTR_QUALITY_SCALE=1.0
export BACKEND_LEARNED_QUALITY_CONST=
export BACKEND_SP_LG_QUALITY_CONST=
export BACKEND_XFEAT_QUALITY_CONST=
export BACKEND_LOFTR_QUALITY_CONST=
export LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS=0
export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION=0
export LEARNED_EXPORT_LOFTR=0
export VINS_MULTIPLE_THREAD=0
export FORCE_EXPORT=1
unset FEATURE_BAG_OVERRIDE QUALITY_CONTRACT_ATTESTATION

fallback_args=()
case "$family" in
  ntnu)
    dataset="${2:?missing NTNU dataset}"
    start="${3:?missing start seconds}"
    duration="${4:?missing duration seconds}"
    every_n="${6:-2}"
    fallback_args=(ntnu "$dataset" "$start" "$duration" klt "$every_n")
    ;;
  cirs)
    start="${2:?missing start seconds}"
    duration="${3:?missing duration seconds}"
    every_n="${5:-1}"
    fallback_args=(cirs "$start" "$duration" klt "$every_n")
    ;;
  aqualoc_archaeo|aqualoc_archaeology|aqualoc)
    sequence="${2:?missing AQUALOC archaeology sequence}"
    start="${3:?missing start index}"
    end="${4:?missing end index}"
    every_n="${6:-2}"
    seq_int=$((10#$sequence))
    seq_pad="$(printf '%02d' "$seq_int")"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" reference_path)"
    fallback_args=(aqualoc_archaeo "$sequence" "$start" "$end" klt "$every_n")
    ;;
  aqualoc_real)
    sequence="${2:?missing AQUALOC harbor sequence}"
    start="${3:?missing start index}"
    end="${4:?missing end index}"
    every_n="${6:-2}"
    seq_int=$((10#${sequence#H}))
    seq_pad="$(printf '%02d' "$seq_int")"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" reference_path)"
    fallback_args=(aqualoc_real "$sequence" "$start" "$end" klt "$every_n")
    ;;
  afrl_dataset)
    dataset="${2:?missing AFRL dataset}"
    start="${3:?missing start seconds}"
    duration="${4:?missing duration seconds}"
    every_n="${6:-2}"
    afrl_root="$ROOT/datasets/full_downloads/afrl_hf"
    export RAW_BAG="$ROOT/$(resolve_manifest_path afrl "$dataset" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path afrl "$dataset" reference_path)"
    export CAMCHAIN="$afrl_root/camera_imu_parameters/camchain_${dataset}.yaml"
    export IMU_YAML="$afrl_root/camera_imu_parameters/imu.yaml"
    export CAMERA_KEY=cam0
    export SRC_IMAGE_TOPIC="$(resolve_camera_topic "$CAMCHAIN" "$CAMERA_KEY")"
    export IMAGE_SCALE=0.5
    fallback_args=(afrl "$start" "$duration" klt "$every_n")
    ;;
  afrl)
    offset=2
    if [[ "${2:-}" == "fr" || "${2:-}" == "cave" ]]; then
      offset=3
    fi
    start="${!offset:?missing AFRL start seconds}"
    duration_index=$((offset + 1))
    method_index=$((offset + 2))
    every_index=$((offset + 3))
    duration="${!duration_index:?missing AFRL duration seconds}"
    every_n="${!every_index:-2}"
    fallback_args=(afrl "$start" "$duration" klt "$every_n")
    ;;
  *)
    echo "unsupported dataset family for contract fallback: $family" >&2
    exit 2
    ;;
esac

for path in "$FRONTEND_CONFIG" "${RAW_TAR:-}" "${RAW_BAG:-}" "${GT_TXT:-}"; do
  [[ -z "$path" || -f "$path" ]] || { echo "missing required fallback file: $path" >&2; exit 3; }
done

export TAG="${TAG:-isj_v4_KLT_BACKEND_CONTRACT_FALLBACK_$(date -u +%Y%m%dT%H%M%SZ)}"
if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'result_label=KLT_BACKEND_CONTRACT_FALLBACK\n'
  printf 'counts_as_proposed_result=0\n'
  printf 'runner=%s\n' "$ROOT/scripts/run_learned_seedchain_eval.sh"
  printf 'frontend_config=%s\n' "$FRONTEND_CONFIG"
  printf 'backend_quality=const\n'
  printf 'argv='; printf '%q ' "${fallback_args[@]}"; printf '\n'
  exit 0
fi

exec bash "${AQUAFE_FALLBACK_DISPATCH_RUNNER:-$ROOT/scripts/run_learned_seedchain_eval.sh}" \
  "${fallback_args[@]}"
