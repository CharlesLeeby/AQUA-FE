#!/usr/bin/env bash
set -euo pipefail

# Frozen non-QG proposed-method entry for the honest incremental ISJ route.
# Usage follows run_xfeat_seedchain_arbitrated_eval.sh, for example:
#   RUN_VINS=0 scripts/run_isj_nativeq_legacy_candidate.sh ntnu fjord_1 83 10 hybrid_xfeat 2
#   RUN_VINS=0 scripts/run_isj_nativeq_legacy_candidate.sh aqualoc_archaeo 6 2210 2460 hybrid_xfeat 2

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
forward_args=("$@")

resolve_manifest_path() {
  local family="$1"
  local sequence="$2"
  local field="$3"
  python3 - "$ROOT/papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv" \
    "$family" "$sequence" "$field" <<'PY'
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
export AQUAFE_SEEDCHAIN_PROFILE=lineage_early_seed_scan
export FRONTEND_CONFIG="$ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
export PREPROCESS=adaptive_clahe
export PROCESS_SKIPPED_FRAMES=1
export MEASUREMENT_SELECTION=0
export FORMAL_THREE_LAYER_EXPORT=0
export VINS_SAFE_SOURCE_SELECTION=0
export EXPORT_MAX_FEATURES=350
export VINS_MAX_CNT=350
export SEMIDENSE_FALLBACK_METHOD=none
export BACKEND_QUALITY_MODE=vins_safe
export BACKEND_QUALITY_ALPHA=0.65
export BACKEND_QUALITY_FLOOR=0.80
export RAW_QUALITY_TO_BACKEND=0
export CONSTANT_QUALITY_TO_BACKEND=0
export BACKEND_LEARNED_QUALITY_CONST=
export BACKEND_SP_LG_QUALITY_CONST=
export BACKEND_XFEAT_QUALITY_CONST=
export BACKEND_LOFTR_QUALITY_CONST=
export VINS_MULTIPLE_THREAD=0

case "${1:-}" in
  aqualoc_archaeo|aqualoc_archaeology|aqualoc)
    sequence="${2:?missing AQUALOC archaeology sequence}"
    seq_int=$((10#$sequence))
    seq_pad="$(printf '%02d' "$seq_int")"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" reference_path)"
    if [[ "${1:-}" == "aqualoc_archaeology" ]]; then
      forward_args=(aqualoc_archaeo "${forward_args[@]:1}")
    fi
    ;;
  aqualoc_real)
    sequence="${2:?missing AQUALOC harbor sequence}"
    seq_int=$((10#${sequence#H}))
    seq_pad="$(printf '%02d' "$seq_int")"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" reference_path)"
    ;;
  afrl_dataset)
    dataset="${2:?missing AFRL sequence}"
    start="${3:?missing start seconds}"
    duration="${4:?missing duration seconds}"
    method="${5:-hybrid_xfeat}"
    every_n="${6:-2}"
    afrl_root="$ROOT/datasets/full_downloads/afrl_hf"
    export RAW_BAG="$ROOT/$(resolve_manifest_path afrl "$dataset" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path afrl "$dataset" reference_path)"
    export CAMCHAIN="$afrl_root/camera_imu_parameters/camchain_${dataset}.yaml"
    export IMU_YAML="$afrl_root/camera_imu_parameters/imu.yaml"
    export CAMERA_KEY=cam0
    export SRC_IMAGE_TOPIC="$(resolve_camera_topic "$CAMCHAIN" "$CAMERA_KEY")"
    export IMAGE_SCALE=0.5
    export TAG_BASE="${TAG_BASE:-isj_nativeq_${dataset}_s${start}_d${duration}}"
    forward_args=(afrl "$start" "$duration" "$method" "$every_n")
    ;;
esac

for path in "$FRONTEND_CONFIG" "${RAW_TAR:-}" "${RAW_BAG:-}" "${GT_TXT:-}"; do
  [[ -z "$path" || -f "$path" ]] || { echo "missing required file: $path" >&2; exit 3; }
done

if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'runner=%s\n' "$ROOT/scripts/run_xfeat_seedchain_arbitrated_eval.sh"
  printf 'method_profile=isj-nativeq-xfeat-seedchain-legacy-v2\n'
  printf 'seedchain_profile=%s\n' "$AQUAFE_SEEDCHAIN_PROFILE"
  printf 'frontend_config=%s\n' "$FRONTEND_CONFIG"
  printf 'backend_quality=%s,floor=%s,alpha=%s\n' \
    "$BACKEND_QUALITY_MODE" "$BACKEND_QUALITY_FLOOR" "$BACKEND_QUALITY_ALPHA"
  printf 'feature_cap=%s\n' "$EXPORT_MAX_FEATURES"
  printf 'argv='; printf '%q ' "${forward_args[@]}"; printf '\n'
  exit 0
fi

exec bash "$ROOT/scripts/run_xfeat_seedchain_arbitrated_eval.sh" "${forward_args[@]}"
