#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_DIR="$ROOT/logs/agent_h07_churn_v2"
INPUT="$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz"
PREFIX="harbor_images_sequence_07"

mkdir -p "$OUT_DIR"

run_eval() {
  local window="$1"
  local start="$2"
  local end="$3"
  local label="$4"
  local method="$5"
  local config="$6"
  local semidense="${7:-none}"
  local out_csv="$OUT_DIR/h07_${window}_${label}.csv"

  if [[ -f "$out_csv" && "${FORCE:-0}" != "1" ]]; then
    echo "skip existing $out_csv"
    return 0
  fi

  echo "run $window $label"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "$INPUT" \
    --image-prefix "$PREFIX" \
    --output-csv "$out_csv" \
    --method "$method" \
    --config "$config" \
    --preprocess adaptive_clahe \
    --start-index "$start" \
    --end-index "$end" \
    --semidense-fallback-method "$semidense"
}

run_window() {
  local window="$1"
  local start="$2"
  local end="$3"

  run_eval "$window" "$start" "$end" \
    "klt_adaptive_clahe" \
    "klt" \
    "$ROOT/uw_frontend/configs/klt_frontend.yaml"

  run_eval "$window" "$start" "$end" \
    "default_full_sp_lg_loftr" \
    "hybrid_superpoint_lightglue" \
    "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" \
    "loftr"

  run_eval "$window" "$start" "$end" \
    "churn_v2_precision_sp_lg_loftr" \
    "hybrid_superpoint_lightglue" \
    "$ROOT/uw_frontend/configs/experiments/h07_churn_v2_precision.yaml" \
    "loftr"
}

run_window "1740_1820" 1740 1820
run_window "normal_0_100" 0 100

python3 "$ROOT/scripts/agent_h07_churn_v2_report.py" \
  --input-dir "$OUT_DIR" \
  --output-md "$OUT_DIR/h07_churn_v2_report.md"
