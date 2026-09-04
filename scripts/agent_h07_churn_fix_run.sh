#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_DIR="$ROOT/logs/agent_h07_churn_fix"
INPUT="$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz"
PREFIX="harbor_images_sequence_07"
START=1740
END=1820

mkdir -p "$OUT_DIR"

run_eval() {
  local label="$1"
  local method="$2"
  local config="$3"
  local semidense="${4:-none}"
  local out_csv="$OUT_DIR/h07_${START}_${END}_${label}.csv"

  if [[ -f "$out_csv" && "${FORCE:-0}" != "1" ]]; then
    echo "skip existing $out_csv"
    return 0
  fi

  echo "run $label"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "$INPUT" \
    --image-prefix "$PREFIX" \
    --output-csv "$out_csv" \
    --method "$method" \
    --config "$config" \
    --preprocess adaptive_clahe \
    --start-index "$START" \
    --end-index "$END" \
    --semidense-fallback-method "$semidense"
}

run_eval \
  "klt_adaptive_clahe" \
  "klt" \
  "$ROOT/uw_frontend/configs/klt_frontend.yaml"

run_eval \
  "default_full_sp_lg_loftr" \
  "hybrid_superpoint_lightglue" \
  "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" \
  "loftr"

run_eval \
  "churn_residual_neutral_sp_lg_loftr" \
  "hybrid_superpoint_lightglue" \
  "$ROOT/uw_frontend/configs/experiments/h07_churn_residual_neutral.yaml" \
  "loftr"

python3 "$ROOT/scripts/agent_h07_churn_fix_report.py" \
  --input-dir "$OUT_DIR" \
  --output-md "$OUT_DIR/churn_fix_report.md"
