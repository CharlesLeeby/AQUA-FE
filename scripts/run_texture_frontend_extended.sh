#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/ma/AQUA-FE_WS"
OUT_ROOT="${OUT_ROOT:-$ROOT/logs/paper_texture_extended}"
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

run_main_window() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"

  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "klt_adaptive_clahe" "klt" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "normal_safe_sp_lg" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_normal_safe_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "full_sp_lg_loftr" "hybrid_superpoint_lightglue" "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" "adaptive_clahe" "loftr"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "full_xfeat_loftr" "hybrid_xfeat" "$ROOT/uw_frontend/configs/paper_full_quality_hybrid_frontend.yaml" "adaptive_clahe" "loftr"
}

run_learned_probe() {
  local dataset="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"

  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "xfeat" "xfeat" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "superpoint_lightglue" "superpoint_lightglue" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "adaptive_clahe"
  run_eval "$dataset" "$input" "$prefix" "$start" "$end" \
    "loftr" "loftr" "$ROOT/uw_frontend/configs/klt_frontend.yaml" "adaptive_clahe"
}

# Normal / moderate texture sanity: the learned sidecar should stay quiet.
run_main_window "aqualoc_h07_normal_long" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  "harbor_images_sequence_07" 0 300

# AQUALOC low-texture / planar-ish windows.
run_main_window "aqualoc_h07_lowtex_long" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  "harbor_images_sequence_07" 1660 1950
run_main_window "aqualoc_h06_lowcontrast_long" \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz" \
  "harbor_images_sequence_06" 2280 2490
run_main_window "aqualoc_a06_planar_lowtex_long" \
  "$ROOT/datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz" \
  "images_sequence_6" 2210 2460

# AFRL windows: low coverage/degraded subsequences from the local extracted samples.
run_main_window "afrl_fl_degraded_long" \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" \
  "" 80 319
run_main_window "afrl_fl_extreme_flat" \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" \
  "" 220 320
run_main_window "afrl_fr_lowcoverage_long" \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" \
  "" 5 410
run_main_window "afrl_fr_extreme_flat_a" \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" \
  "" 180 240
run_main_window "afrl_fr_extreme_flat_b" \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" \
  "" 540 640

# Pure learned probes on representative low-texture short windows. These are
# external baselines, not the main system, so keep them short enough to rerun.
run_learned_probe "probe_aqualoc_a06_planar_lowtex" \
  "$ROOT/datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz" \
  "images_sequence_6" 2210 2260
run_learned_probe "probe_afrl_fl_extreme_flat" \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" \
  "" 240 300
run_learned_probe "probe_afrl_fr_extreme_flat" \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" \
  "" 190 240

python3 "$ROOT/scripts/summarize_texture_frontend_matrix.py" \
  --input-dir "$OUT_ROOT" \
  --output-csv "$OUT_ROOT/texture_extended_summary.csv" \
  --output-md "$OUT_ROOT/texture_extended_summary.md"

