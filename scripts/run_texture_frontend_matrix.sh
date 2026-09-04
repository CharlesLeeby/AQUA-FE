#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_ROOT="${OUT_ROOT:-$ROOT/logs/paper_texture_matrix}"
mkdir -p "$OUT_ROOT"

run_eval() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"
  local method_label="$6"
  local method="$7"
  local config="$8"
  local preprocess="$9"
  local semidense="${10:-none}"

  local out_csv="$OUT_ROOT/${dataset}_${start}_${end}_${method_label}.csv"
  if [[ -f "$out_csv" && "${FORCE:-0}" != "1" ]]; then
    echo "skip existing $out_csv"
    return 0
  fi
  echo "run $dataset $start-$end $method_label"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "$input" \
    --output-csv "$out_csv" \
    --method "$method" \
    --config "$config" \
    --preprocess "$preprocess" \
    --start-index "$start" \
    --end-index "$end" \
    --semidense-fallback-method "$semidense" \
    ${prefix:+--image-prefix "$prefix"}
}

run_dataset() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"

  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "klt" "klt" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "none"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "klt_adaptive_clahe" "klt" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "normal_safe_sp_lg" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_normal_safe_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "full_sp_lg_loftr" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" "adaptive_clahe" "loftr"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "full_xfeat_loftr" "hybrid_xfeat" "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" "adaptive_clahe" "loftr"
}

run_dataset "aqualoc_h07_normal" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  "harbor_images_sequence_07" 0 50

run_dataset "aqualoc_h07_lowtex" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  "harbor_images_sequence_07" 1660 1710

run_dataset "aqualoc_h06_lowcontrast" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz" \
  "harbor_images_sequence_06" 2280 2330

run_dataset "aqualoc_a06_planar_lowtex" \
  "$ROOT/datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz" \
  "images_sequence_6" 2210 2260

run_dataset "afrl_fr_lowcoverage" \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" \
  "" 5 55

run_dataset "afrl_fl_degraded" \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" \
  "" 80 130

python3 "$ROOT/scripts/summarize_texture_frontend_matrix.py" \
  --input-dir "$OUT_ROOT" \
  --output-csv "$OUT_ROOT/texture_matrix_summary.csv" \
  --output-md "$OUT_ROOT/texture_matrix_summary.md"
