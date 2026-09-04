#!/usr/bin/env bash
set -euo pipefail

# Compare the frozen pure-KLT external-feature arm against VINS-Fusion's
# built-in image tracker on all nine MIMIR-UW low-texture windows selected by
# isj-window-selection-v2. Existing raw/KLT bags from the learned-positive
# search are reused byte-for-byte. Missing bags are exported with the same
# frozen v31 KLT profile. Backend runs use the same raw bag, calibration,
# timestamps, VINS tree, and deterministic initialization seed.

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
LOG_ROOT="${LOG_ROOT:-$ROOT/logs/mimir_uw_vins}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
TAG_PREFIX="${TAG_PREFIX:-mimir_klt_vs_original_v1}"
INPUT_PREFIX="${INPUT_PREFIX:-mimir_klt_vs_original_v1}"
# Optional output prefix for a fresh KLT export while still reusing the frozen
# raw bags resolved by INPUT_PREFIX/existing positive-search tags. This is used
# by the MIMIR rate-1 correction so cached rate-2 feature bags cannot be
# mistaken for the corrected baseline.
RATE1_FEATURE_PREFIX="${RATE1_FEATURE_PREFIX:-}"
PORT_BASE="${PORT_BASE:-13400}"
MAX_EXPORT_JOBS="${MAX_EXPORT_JOBS:-2}"
MAX_PAIR_JOBS="${MAX_PAIR_JOBS:-3}"
RANSAC_SEED="${VINS_INITIAL_RANSAC_SEED:-0}"

cd "$ROOT"

# environment|track|start|duration|existing positive-search tag base
WINDOWS=(
  "OceanFloor|track0_dark|45|45|mimir_positive_v31_oceanfloor_track0_dark_s45_d45_r2"
  "SandPipe|track0_dark|45|45|mimir_positive_v31_sandpipe_track0_dark_s45_d45_r1"
  "OceanFloor|track1_light|135|45|mimir_positive_v31_oceanfloor_track1_light_s135_d45_r1"
  "OceanFloor|track1_light|90|45|mimir_positive_v31_oceanfloor_track1_light_s90_d45_r1"
  "OceanFloor|track0_light|45|45|mimir_positive_v31_oceanfloor_track0_light_s45_d45_r1"
  "SandPipe|track0_light|45|45|"
  "SeaFloor|track0|0|45|"
  "SeaFloor|track2|0|45|"
  "SeaFloor|track1|45|45|"
)

safe_name() {
  local environment="$1" track="$2" start="$3" duration="$4"
  local safe_environment="${environment,,}"
  local safe_track="${track,,}"
  safe_environment="${safe_environment//[^a-z0-9]/_}"
  safe_track="${safe_track//[^a-z0-9]/_}"
  printf '%s_%s_s%s_d%s' "$safe_environment" "$safe_track" "${start//./p}" "${duration//./p}"
}

resolve_inputs() {
  local environment="$1" track="$2" start="$3" duration="$4" existing="$5"
  local stem base raw_bag feature_bag
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  if [[ -n "$existing" ]]; then
    base="$LOG_ROOT/$existing"
    raw_bag="${base}_shared/mimir_raw.bag"
    feature_bag="${base}_klt/features.bag"
  else
    base="$LOG_ROOT/${INPUT_PREFIX}_${stem}"
    raw_bag="${base}_shared/mimir_raw.bag"
    feature_bag="${base}_klt_export/features.bag"
  fi
  if [[ -n "$RATE1_FEATURE_PREFIX" ]]; then
    feature_bag="$LOG_ROOT/${RATE1_FEATURE_PREFIX}_${stem}_klt_export/features.bag"
  fi
  printf '%s|%s' "$raw_bag" "$feature_bag"
}

prepare_missing_window() {
  local row="$1"
  local environment track start duration existing inputs raw_bag feature_bag stem tag
  IFS='|' read -r environment track start duration existing <<< "$row"
  inputs="$(resolve_inputs "$environment" "$track" "$start" "$duration" "$existing")"
  IFS='|' read -r raw_bag feature_bag <<< "$inputs"
  if [[ -s "$raw_bag" && -s "$feature_bag" ]]; then
    echo "reuse environment=$environment track=$track start=$start raw=$raw_bag feature=$feature_bag"
    return 0
  fi
  if [[ -n "$existing" && ! -s "$raw_bag" ]]; then
    echo "missing expected cached raw input: raw=$raw_bag" >&2
    return 2
  fi
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  tag="${RATE1_FEATURE_PREFIX:-$TAG_PREFIX}_${stem}_klt_export"
  RAW_BAG="$raw_bag" TAG="$tag" RUN_VINS=0 \
    bash scripts/run_paper_sidecar_profiles.sh \
      mimir_uw_klt_v31 "$environment" "$track" "$start" "$duration"
}

run_complete() {
  local run_dir="$1"
  [[ -s "$run_dir/ape.txt" ]] && return 0
  [[ -f "$run_dir/vins_output/vio.csv" ]] \
    && rg -q "empty VINS trajectory" "$run_dir/runner_stdout.log" 2>/dev/null
}

run_backend_arm() {
  local mode="$1" environment="$2" track="$3" start="$4" duration="$5"
  local raw_bag="$6" feature_bag="$7" port="$8" stem="$9"
  local tag run_dir status
  tag="${TAG_PREFIX}_${stem}_${mode}_vins_seed${RANSAC_SEED}"
  run_dir="$LOG_ROOT/$tag"
  mkdir -p "$run_dir"
  {
    echo "comparison_mode=$mode"
    echo "environment=$environment"
    echo "track=$track"
    echo "start_offset=$start"
    echo "duration=$duration"
    echo "raw_bag=$raw_bag"
    echo "feature_bag=$feature_bag"
    echo "vins_input_mode=$([[ "$mode" == "klt" ]] && echo features || echo images)"
    echo "vins_workspace=$VINS_WS"
    echo "vins_initial_ransac_seed=$RANSAC_SEED"
    echo "ros_port=$port"
  } > "$run_dir/comparison_arm_manifest.txt"
  if run_complete "$run_dir"; then
    echo "reuse backend=$mode run_dir=$run_dir"
    return 0
  fi

  set +e
  if [[ "$mode" == "klt" ]]; then
    VINS_INITIAL_RANSAC_SEED="$RANSAC_SEED" \
      PREPARE_BAG=0 EXPORT_FEATURES=0 RUN_VINS=1 VINS_INPUT_MODE=features \
      VINS_WS="$VINS_WS" RAW_BAG="$raw_bag" FEATURE_BAG="$feature_bag" \
      TAG="$tag" PORT="$port" \
      bash scripts/run_mimir_uw_vins_eval.sh \
        klt "$environment" "$track" "$start" "$duration" "${MIMIR_EVERY_N:-1}" \
        > "$run_dir/runner_stdout.log" 2>&1
  else
    VINS_INITIAL_RANSAC_SEED="$RANSAC_SEED" \
      PREPARE_BAG=0 EXPORT_FEATURES=0 RUN_VINS=1 VINS_INPUT_MODE=images \
      VINS_WS="$VINS_WS" RAW_BAG="$raw_bag" \
      TAG="$tag" PORT="$port" \
      bash scripts/run_mimir_uw_vins_eval.sh \
        klt "$environment" "$track" "$start" "$duration" "${MIMIR_EVERY_N:-1}" \
        > "$run_dir/runner_stdout.log" 2>&1
  fi
  status=$?
  set -e
  printf '%s\n' "$status" > "$run_dir/runner_exit_status.txt"
  echo "finished backend=$mode status=$status run_dir=$run_dir"
  return 0
}

run_pair() {
  local index="$1" row="$2"
  local environment track start duration existing inputs raw_bag feature_bag stem
  local klt_port original_port klt_pid original_pid
  IFS='|' read -r environment track start duration existing <<< "$row"
  inputs="$(resolve_inputs "$environment" "$track" "$start" "$duration" "$existing")"
  IFS='|' read -r raw_bag feature_bag <<< "$inputs"
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  klt_port=$((PORT_BASE + index * 2))
  original_port=$((klt_port + 1))
  run_backend_arm klt "$environment" "$track" "$start" "$duration" \
    "$raw_bag" "$feature_bag" "$klt_port" "$stem" &
  klt_pid=$!
  run_backend_arm original "$environment" "$track" "$start" "$duration" \
    "$raw_bag" "$feature_bag" "$original_port" "$stem" &
  original_pid=$!
  wait "$klt_pid"
  wait "$original_pid"
}

wait_for_slot() {
  local max_jobs="$1"
  while (( $(jobs -pr | wc -l) >= max_jobs )); do
    wait -n
  done
}

echo "phase=prepare windows=${#WINDOWS[@]} max_jobs=$MAX_EXPORT_JOBS"
for row in "${WINDOWS[@]}"; do
  wait_for_slot "$MAX_EXPORT_JOBS"
  prepare_missing_window "$row" &
done
wait

echo "phase=backend_pairs windows=${#WINDOWS[@]} max_jobs=$MAX_PAIR_JOBS seed=$RANSAC_SEED"
for index in "${!WINDOWS[@]}"; do
  wait_for_slot "$MAX_PAIR_JOBS"
  run_pair "$index" "${WINDOWS[$index]}" &
done
wait

echo "completed tag_prefix=$TAG_PREFIX"
