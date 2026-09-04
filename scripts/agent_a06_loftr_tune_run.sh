#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_ROOT="${OUT_ROOT:-$ROOT/logs/agent_a06_loftr_tune}"
mkdir -p "$OUT_ROOT"

INPUT="$ROOT/datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz"
PREFIX="images_sequence_6"

run_eval() {
  local window_label="$1"
  local start="$2"
  local end="$3"
  local method_label="$4"
  local method="$5"
  local config="$6"
  local semidense="${7:-none}"
  local out_csv="$OUT_ROOT/a06_${window_label}_${start}_${end}_${method_label}.csv"
  if [[ -f "$out_csv" && "${FORCE:-0}" != "1" ]]; then
    echo "skip existing $out_csv"
    return 0
  fi
  echo "run $window_label $start-$end $method_label"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "$INPUT" \
    --image-prefix "$PREFIX" \
    --config "$config" \
    --method "$method" \
    --preprocess adaptive_clahe \
    --start-index "$start" \
    --end-index "$end" \
    --semidense-fallback-method "$semidense" \
    --output-csv "$out_csv"
}

run_baselines() {
  local window_label="$1"
  local start="$2"
  local end="$3"
  run_eval "$window_label" "$start" "$end" \
    "klt_adaptive_clahe" "klt" "$ROOT/uw_frontend/configs/klt_frontend.yaml"
  run_eval "$window_label" "$start" "$end" \
    "normal_safe_sp_lg" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_normal_safe_frontend.yaml"
  run_eval "$window_label" "$start" "$end" \
    "full_sp_lg_loftr" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" "loftr"
}

run_variants() {
  local window_label="$1"
  local start="$2"
  local end="$3"
  run_eval "$window_label" "$start" "$end" \
    "tuned_strict_accept" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/experiments/a06_loftr_residual_neutral_strict_accept.yaml" "loftr"
  run_eval "$window_label" "$start" "$end" \
    "tuned_low_count" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/experiments/a06_loftr_residual_neutral_low_count.yaml" "loftr"
  run_eval "$window_label" "$start" "$end" \
    "tuned_quality" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/experiments/a06_loftr_residual_neutral_quality.yaml" "loftr"
}

run_baselines "planar_long" 2210 2460
run_variants "planar_long" 2210 2460

if [[ "${RUN_LONGER:-0}" == "1" ]]; then
  run_baselines "planar_longer" 2210 2700
  run_variants "planar_longer" 2210 2700
fi

python3 "$ROOT/scripts/agent_a06_loftr_tune_summary.py" \
  --input-dir "$OUT_ROOT" \
  --output-csv "$OUT_ROOT/a06_loftr_tune_summary.csv" \
  --output-md "$OUT_ROOT/a06_loftr_tune_summary.md"
