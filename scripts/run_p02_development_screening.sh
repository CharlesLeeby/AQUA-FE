#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
OUT="${OUT:-$ROOT/papers/ieee_sensors_journal_experiments/p02/development_screening}"
CONFIG="$ROOT/uw_frontend/configs/klt_frontend.yaml"
RUNNER=(python3 -m uw_frontend.evaluation.run_frontend_eval)

mkdir -p "$OUT"
cd "$ROOT"

run_archive_case() {
  local case_id="$1"
  local input="$2"
  local prefix="$3"
  local start="$4"
  local end="$5"
  mkdir -p "$OUT/$case_id"
  if [[ -s "$OUT/$case_id/metrics.csv" ]]; then
    printf 'reuse %s\n' "$OUT/$case_id/metrics.csv"
    return
  fi
  "${RUNNER[@]}" \
    --input "$input" \
    --image-prefix "$prefix" \
    --output-csv "$OUT/$case_id/metrics.csv" \
    --method klt \
    --config "$CONFIG" \
    --preprocess adaptive_clahe \
    --every-n 1 \
    --start-index "$start" \
    --end-index "$end"
}

run_directory_case() {
  local case_id="$1"
  local input="$2"
  local start="$3"
  local end="$4"
  mkdir -p "$OUT/$case_id"
  if [[ -s "$OUT/$case_id/metrics.csv" ]]; then
    printf 'reuse %s\n' "$OUT/$case_id/metrics.csv"
    return
  fi
  "${RUNNER[@]}" \
    --input "$input" \
    --output-csv "$OUT/$case_id/metrics.csv" \
    --method klt \
    --config "$CONFIG" \
    --preprocess adaptive_clahe \
    --every-n 1 \
    --start-index "$start" \
    --end-index "$end"
}

run_archive_case \
  aqualoc_a06_2210_2460 \
  "$ROOT/datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz" \
  images_sequence_6 2210 2460
run_archive_case \
  aqualoc_h06_2280_2490 \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_06_raw_data.tar.gz" \
  harbor_images_sequence_06 2280 2490
run_archive_case \
  aqualoc_h07_1660_1720 \
  "$ROOT/datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz" \
  harbor_images_sequence_07 1660 1720
run_directory_case \
  afrl_cemetery_fr_005_410 \
  "$ROOT/datasets/afrl/samples/cemetery_fr_every5_800" 5 410
run_directory_case \
  afrl_cemetery_fl_080_319 \
  "$ROOT/datasets/afrl/samples/cemetery_fl_every5_800" 80 319
run_directory_case \
  tank_short_000_299 \
  "$ROOT/datasets/prepared_new/tank_short_left" 0 299
run_directory_case \
  uvvid_cannon_000_179 \
  "$ROOT/datasets/prepared_new/uvvid_cannon_bottom" 0 179

printf 'P02_DEVELOPMENT_SCREENING_COMPLETE\n'
