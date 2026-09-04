#!/usr/bin/env bash
set -euo pipefail

# Controlled same-backend XFeat baseline for P05/P07.
#
# Usage:
#   RUN_VINS=0 scripts/run_p05_modern_xfeat_baseline.sh ntnu fjord_1 83 10 [every_n]
#   RUN_VINS=0 scripts/run_p05_modern_xfeat_baseline.sh aqualoc_archaeology 6 2210 2460 [every_n]
#   RUN_VINS=0 scripts/run_p05_modern_xfeat_baseline.sh aqualoc_harbor 7 1660 1720 [every_n]
#   RUN_VINS=0 scripts/run_p05_modern_xfeat_baseline.sh afrl cemetery 0 20 [every_n]

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
FAMILY="${1:?missing dataset family}"
shift

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
export FRONTEND_CONFIG="$ROOT/uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"
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
export RUN_VINS="${RUN_VINS:-0}"
export FORCE_EXPORT="${FORCE_EXPORT:-1}"
export EXPORT_FEATURES=1

method=xfeat
runner=()
runner_args=()

case "$FAMILY" in
  ntnu)
    dataset="${1:?missing NTNU sequence}"
    start="${2:?missing start seconds}"
    duration="${3:?missing duration seconds}"
    every_n="${4:-2}"
    export FRAME_OFFSET=1
    export TAG="${TAG:-isj_p05_m_${dataset}_s${start}_d${duration}}"
    runner=(bash "$ROOT/scripts/run_ntnu_vins_eval.sh")
    runner_args=(external "$dataset" "$start" "$duration" "$method" "$every_n")
    ;;
  aqualoc_archaeology|aqualoc_archaeo)
    sequence="${1:?missing AQUALOC archaeology sequence}"
    start="${2:?missing start index}"
    end="${3:?missing end index}"
    every_n="${4:-2}"
    seq_int=$((10#$sequence))
    seq_pad="$(printf '%02d' "$seq_int")"
    export FRAME_OFFSET=1
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_archaeology "A${seq_pad}" reference_path)"
    export TAG="${TAG:-isj_p05_m_a${seq_pad}_${start}_${end}}"
    runner=(bash "$ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh")
    runner_args=(external "$seq_int" "$start" "$end" "$method" "$every_n")
    ;;
  aqualoc_harbor|aqualoc_real)
    sequence="${1:?missing AQUALOC harbor sequence}"
    start="${2:?missing start index}"
    end="${3:?missing end index}"
    every_n="${4:-2}"
    seq_int=$((10#${sequence#H}))
    seq_pad="$(printf '%02d' "$seq_int")"
    export FRAME_OFFSET=1
    export HARBOR_SEQ="$seq_int"
    export RAW_TAR="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path aqualoc_harbor "H${seq_pad}" reference_path)"
    export TAG="${TAG:-isj_p05_m_h${seq_pad}_${start}_${end}}"
    runner=(bash "$ROOT/scripts/run_aqualoc_real_vins_eval.sh")
    runner_args=(external "$start" "$end" "$method" "$every_n")
    ;;
  afrl)
    dataset="${1:?missing AFRL sequence}"
    start="${2:?missing start seconds}"
    duration="${3:?missing duration seconds}"
    every_n="${4:-2}"
    afrl_root="$ROOT/datasets/full_downloads/afrl_hf"
    export FRAME_OFFSET=0
    export RAW_BAG="$ROOT/$(resolve_manifest_path afrl "$dataset" raw_input_path)"
    export GT_TXT="$ROOT/$(resolve_manifest_path afrl "$dataset" reference_path)"
    export CAMCHAIN="$afrl_root/camera_imu_parameters/camchain_${dataset}.yaml"
    export IMU_YAML="$afrl_root/camera_imu_parameters/imu.yaml"
    export CAMERA_KEY=cam0
    export SRC_IMAGE_TOPIC="$(resolve_camera_topic "$CAMCHAIN" "$CAMERA_KEY")"
    export IMAGE_SCALE=0.5
    export TAG="${TAG:-isj_p05_m_${dataset}_s${start}_d${duration}}"
    runner=(bash "$ROOT/scripts/run_afrl_cave_vins_eval.sh")
    runner_args=(external "$method" "$start" "$duration" "$every_n")
    ;;
  *)
    echo "unsupported P05 primary family: $FAMILY" >&2
    exit 2
    ;;
esac

for path in "$FRONTEND_CONFIG"; do
  [[ -f "$path" ]] || { echo "missing required file: $path" >&2; exit 3; }
done
if [[ -n "${RAW_TAR:-}" ]]; then
  [[ -f "$RAW_TAR" ]] || { echo "missing raw archive: $RAW_TAR" >&2; exit 3; }
fi
if [[ -n "${RAW_BAG:-}" ]]; then
  [[ -f "$RAW_BAG" ]] || { echo "missing raw bag: $RAW_BAG" >&2; exit 3; }
fi
if [[ -n "${GT_TXT:-}" ]]; then
  [[ -f "$GT_TXT" ]] || { echo "missing reference: $GT_TXT" >&2; exit 3; }
fi
if [[ -n "${CAMCHAIN:-}" ]]; then
  [[ -f "$CAMCHAIN" ]] || { echo "missing camera calibration: $CAMCHAIN" >&2; exit 3; }
fi
if [[ -n "${IMU_YAML:-}" ]]; then
  [[ -f "$IMU_YAML" ]] || { echo "missing IMU calibration: $IMU_YAML" >&2; exit 3; }
fi

if [[ "${AQUAFE_DRY_RUN:-0}" == "1" ]]; then
  printf 'method_profile=isj-p05-xfeat-pairwise-nativeq-v1\n'
  printf 'frontend_config=%s\n' "$FRONTEND_CONFIG"
  printf 'backend_quality=%s,floor=%s,alpha=%s\n' \
    "$BACKEND_QUALITY_MODE" "$BACKEND_QUALITY_FLOOR" "$BACKEND_QUALITY_ALPHA"
  printf 'feature_cap=%s\n' "$EXPORT_MAX_FEATURES"
  printf 'frame_offset=%s\n' "$FRAME_OFFSET"
  if [[ "$FAMILY" == "afrl" ]]; then
    printf 'source_image_topic=%s\n' "$SRC_IMAGE_TOPIC"
    printf 'camera_key=%s\n' "$CAMERA_KEY"
    printf 'image_scale=%s\n' "$IMAGE_SCALE"
  fi
  printf 'command='; printf '%q ' "${runner[@]}" "${runner_args[@]}"; printf '\n'
  exit 0
fi

exec "${runner[@]}" "${runner_args[@]}"
