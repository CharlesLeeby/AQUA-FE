#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
OUT="${OUT:-$ROOT/logs/conformal_calibration/c3_alpha_repeats_20260614}"
PORT_BASE="${PORT_BASE:-14200}"
REPEATS="${REPEATS:-2 3}"
ALPHAS="${ALPHAS:-070 080 085 090 095 099}"

A06_SOURCE_RUN="${A06_SOURCE_RUN:-$ROOT/logs/conformal_calibration/alpha_scan_a06/a085_vins}"
A06_SOURCE_CONFIG="${A06_SOURCE_CONFIG:-$A06_SOURCE_RUN/vins_aqualoc_archaeo_external.yaml}"
A06_SOURCE_CAMERA="${A06_SOURCE_CAMERA:-$A06_SOURCE_RUN/aqualoc_archaeo06_pinhole.yaml}"

mkdir -p "$OUT"
PORT="$PORT_BASE"

next_port() {
  PORT=$((PORT + 1))
  echo "$PORT"
}

run_h07() {
  local alpha_tag=$1
  local repeat=$2
  local bag="$ROOT/logs/conformal_calibration/alpha_scan_h07/a${alpha_tag}/features.bag"
  local run_dir="$OUT/h07_a${alpha_tag}_r${repeat}"
  local port
  port=$(next_port)
  echo "[$(date +%H:%M:%S)] H07 alpha=$alpha_tag repeat=$repeat port=$port"
  bash "$ROOT/scripts/fourpoint_run_vins_existing_feature_bag.sh" "$run_dir" "$bag" "$port" \
    > "$run_dir.launch.log" 2>&1
}

run_a06() {
  local alpha_tag=$1
  local repeat=$2
  local bag="$ROOT/logs/conformal_calibration/alpha_scan_a06/a${alpha_tag}/features.bag"
  local run_dir="$OUT/a06_a${alpha_tag}_r${repeat}"
  local port
  port=$(next_port)
  echo "[$(date +%H:%M:%S)] A06 alpha=$alpha_tag repeat=$repeat port=$port"
  SOURCE_CONFIG="$A06_SOURCE_CONFIG" \
  SOURCE_CAMERA_CONFIG="$A06_SOURCE_CAMERA" \
  RUN_DIR="$run_dir" PORT="$port" \
  bash "$ROOT/scripts/run_existing_featurebag_vins_eval.sh" "$A06_SOURCE_RUN" "$bag" "a06_a${alpha_tag}_r${repeat}" /aqualoc/colmap_gt \
    > "$run_dir.launch.log" 2>&1
}

for repeat in $REPEATS; do
  for alpha_tag in $ALPHAS; do
    run_a06 "$alpha_tag" "$repeat"
  done
done

for repeat in $REPEATS; do
  for alpha_tag in $ALPHAS; do
    run_h07 "$alpha_tag" "$repeat"
  done
done

echo "[$(date +%H:%M:%S)] C3 alpha repeats done: $OUT"
