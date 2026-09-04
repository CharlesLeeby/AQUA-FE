#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_ROOT="${OUT_ROOT:-$ROOT/logs/agent_loftr_noharm}"
mkdir -p "$OUT_ROOT"

KLT_CFG="$ROOT/uw_frontend/configs/klt_frontend.yaml"
NORMAL_CFG="$ROOT/uw_frontend/configs/paper_normal_safe_frontend.yaml"
FULL_CFG="$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml"
TUNED_CFG="$ROOT/uw_frontend/configs/experiments/a06_loftr_residual_neutral_quality.yaml"

run_eval() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"
  local label="$6"
  local method="$7"
  local config="$8"
  local semidense="${9:-none}"
  local out_csv="$OUT_ROOT/${dataset}_${start}_${end}_${label}.csv"

  if [[ -f "$out_csv" && "${FORCE:-0}" != "1" ]]; then
    echo "skip existing $out_csv"
    return 0
  fi

  echo "run $dataset $start-$end $label"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "$input" \
    --output-csv "$out_csv" \
    --method "$method" \
    --config "$config" \
    --preprocess adaptive_clahe \
    --start-index "$start" \
    --end-index "$end" \
    --semidense-fallback-method "$semidense" \
    ${prefix:+--image-prefix "$prefix"}
}

run_tuned_quality() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "a06_tuned_quality_sp_lg_loftr" \
    "hybrid_superpoint_lightglue" \
    "$TUNED_CFG" \
    "loftr"
}

# Existing texture-breadth CSVs cover H07 normal/lowtex, H06 lowcontrast, and
# AFRL-FL for KLT, normal-safe SP+LG, and current full SP+LG+LoFTR. Keep the
# default runner compact: only the two most informative missing tuned probes.
run_tuned_quality "aqualoc_h07_lowtex_extreme" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  "harbor_images_sequence_07" 1740 1820
run_tuned_quality "afrl_fl_degraded_extreme" \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" \
  "" 240 320

if [[ "${RUN_EXTRA:-0}" == "1" ]]; then
  run_tuned_quality "aqualoc_h07_normal_mid" \
    "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
    "harbor_images_sequence_07" 0 100
  run_tuned_quality "aqualoc_h06_lowcontrast" \
    "$ROOT/datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz" \
    "harbor_images_sequence_06" 2360 2440
fi

python3 "$ROOT/scripts/agent_loftr_noharm_summary.py" \
  --output-dir "$OUT_ROOT"
