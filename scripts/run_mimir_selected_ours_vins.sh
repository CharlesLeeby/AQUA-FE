#!/usr/bin/env bash
set -euo pipefail

# Export and replay the final AQUA-FE proposed_safe frontend on the same nine
# MIMIR-UW windows used by the deterministic KLT-vs-original comparison.

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
LOG_ROOT="${LOG_ROOT:-$ROOT/logs/mimir_uw_vins}"
VINS_WS="${VINS_WS:-/home/ma/SLAM/VINS-Fusion-origin}"
BASELINE_PREFIX="${BASELINE_PREFIX:-mimir_klt_vs_original_v1}"
TAG_PREFIX="${TAG_PREFIX:-mimir_threeway_v1}"
EXPORT_PREFIX="${EXPORT_PREFIX:-$TAG_PREFIX}"
PORT_BASE="${PORT_BASE:-13500}"
MAX_EXPORT_JOBS="${MAX_EXPORT_JOBS:-2}"
MAX_VINS_JOBS="${MAX_VINS_JOBS:-3}"
RANSAC_SEED="${VINS_INITIAL_RANSAC_SEED:-0}"
PYTHON_BIN="${PYTHON_BIN:-/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin/python3}"
# Optional formal-comparison controls.  When FROZEN_KLT_INIT_PREFIX is set,
# AQUA-FE copies only the *predeclared feature-frame skip count* from the
# corresponding pure-KLT export.  It does not read KLT backend performance.
# This keeps the backend initialization timestamps identical even though the
# hybrid tracker's private parallax probe can differ from its published mirror
# KLT backbone. WINDOW_REGEX allows a bounded repair run without recomputing
# already valid windows.
FROZEN_KLT_INIT_PREFIX="${FROZEN_KLT_INIT_PREFIX:-}"
WINDOW_REGEX="${WINDOW_REGEX:-}"

cd "$ROOT"

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
  local safe_environment="${environment,,}" safe_track="${track,,}"
  safe_environment="${safe_environment//[^a-z0-9]/_}"
  safe_track="${safe_track//[^a-z0-9]/_}"
  printf '%s_%s_s%s_d%s' "$safe_environment" "$safe_track" "${start//./p}" "${duration//./p}"
}

resolve_raw_bag() {
  local environment="$1" track="$2" start="$3" duration="$4" existing="$5"
  local stem base
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  if [[ -n "$existing" ]]; then
    base="$LOG_ROOT/$existing"
  else
    base="$LOG_ROOT/${BASELINE_PREFIX}_${stem}"
  fi
  printf '%s' "${base}_shared/mimir_raw.bag"
}

window_enabled() {
  local row="$1" environment track start duration existing stem
  IFS='|' read -r environment track start duration existing <<< "$row"
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  [[ -z "$WINDOW_REGEX" || "$stem" =~ $WINDOW_REGEX ]]
}

frozen_klt_init_skip() {
  local stem="$1" metrics
  [[ -n "$FROZEN_KLT_INIT_PREFIX" ]] || { printf '%s' ""; return 0; }
  metrics="$LOG_ROOT/${FROZEN_KLT_INIT_PREFIX}_${stem}_klt_export/frontend_metrics.csv"
  [[ -s "$metrics" ]] || {
    echo "missing frozen KLT initialization receipt: $metrics" >&2
    return 2
  }
  "$PYTHON_BIN" - "$metrics" <<'PY'
import csv
import sys

with open(sys.argv[1], newline="", encoding="utf-8") as handle:
    rows = csv.DictReader(handle)
    skipped = 0
    for row in rows:
        if row.get("init_parallax_skipped_feature") != "1":
            break
        skipped += 1
print(skipped)
PY
}

export_complete() {
  local run_dir="$1"
  [[ -s "$run_dir/features.bag" && -s "$run_dir/frontend_metrics.csv" ]] || return 1
  (( $(wc -l < "$run_dir/frontend_metrics.csv") > 200 )) || return 1
  source /opt/ros/noetic/setup.bash
  rosbag info "$run_dir/features.bag" >/dev/null 2>&1
}

export_ours() {
  local row="$1"
  local environment track start duration existing stem raw_bag tag run_dir frozen_skip
  IFS='|' read -r environment track start duration existing <<< "$row"
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  raw_bag="$(resolve_raw_bag "$environment" "$track" "$start" "$duration" "$existing")"
  tag="${EXPORT_PREFIX}_${stem}_ours_export"
  run_dir="$LOG_ROOT/$tag"
  if export_complete "$run_dir"; then
    echo "reuse export run_dir=$run_dir"
    return 0
  fi
  [[ -s "$raw_bag" ]] || { echo "missing raw bag: $raw_bag" >&2; return 2; }
  frozen_skip="$(frozen_klt_init_skip "$stem")"
  local -a init_schedule_env=()
  if [[ -n "$frozen_skip" ]]; then
    init_schedule_env=(
      INIT_PARALLAX_ADAPTIVE_SKIP=0
      INIT_PARALLAX_SKIP_FEATURE_FRAMES="$frozen_skip"
    )
    echo "frozen KLT init schedule stem=$stem skip_feature_frames=$frozen_skip"
  fi
  env "${init_schedule_env[@]}" \
    PYTHON_BIN="$PYTHON_BIN" RAW_BAG="$raw_bag" TAG="$tag" RUN_VINS=0 \
    MIMIR_OURS_METHOD=hybrid_superpoint_lightglue \
    LOFTR_MIRROR_CONFIG="$ROOT/uw_frontend/configs/experiments/mimir_loftr_klt_persistent_sidecar_frontend.yaml" \
    MIMIR_EVERY_N=1 \
    FRAME_OFFSET=0 MEASUREMENT_SELECTION=1 \
    FORMAL_EXPORT_PRESERVE_INPUT_BACKBONE=1 \
    EXPORT_CLASSICAL_MIRROR_BACKBONE=1 \
    MIRROR_MEASUREMENT_SELECTION_POLICY=baseline \
    VINS_SAFE_WARMUP_FRAMES=360 \
    VINS_SAFE_PRESERVE_CLASSICAL_BUDGET=1 \
    LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS=144 \
    LEARNED_EXPORT_MIN_GRID_GAIN=0 \
    LEARNED_EXPORT_MIN_NEW_CELLS=0 \
    LEARNED_EXPORT_MIN_NEW_CELL_RATIO=0 \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX=10 \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX=25 \
    LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT=1 \
    LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES=0 \
    LEARNED_EXPORT_LOFTR_SOURCE_MEMORY=0 \
    LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_GATE=1 \
    LEARNED_EXPORT_LOFTR_SEEDED_CONTINUATION_MAX_GAP=1 \
    bash scripts/run_paper_sidecar_profiles.sh \
      mimir_uw_loftr_mirror_proposed "$environment" "$track" "$start" "$duration"
}

run_complete() {
  local run_dir="$1"
  [[ -s "$run_dir/ape.txt" ]] && return 0
  [[ -f "$run_dir/vins_output/vio.csv" ]] \
    && rg -q "empty VINS trajectory" "$run_dir/runner_stdout.log" 2>/dev/null
}

run_ours_vins() {
  local index="$1" row="$2"
  local environment track start duration existing stem raw_bag feature_bag tag run_dir port status
  IFS='|' read -r environment track start duration existing <<< "$row"
  stem="$(safe_name "$environment" "$track" "$start" "$duration")"
  raw_bag="$(resolve_raw_bag "$environment" "$track" "$start" "$duration" "$existing")"
  feature_bag="$LOG_ROOT/${EXPORT_PREFIX}_${stem}_ours_export/features.bag"
  tag="${TAG_PREFIX}_${stem}_ours_vins_seed${RANSAC_SEED}"
  run_dir="$LOG_ROOT/$tag"
  port=$((PORT_BASE + index))
  mkdir -p "$run_dir"
  {
    echo "comparison_mode=ours_proposed_safe"
    echo "profile=paper_loftr_mirror_env"
    echo "environment=$environment"
    echo "track=$track"
    echo "start_offset=$start"
    echo "duration=$duration"
    echo "raw_bag=$raw_bag"
    echo "feature_bag=$feature_bag"
    echo "vins_input_mode=features"
    echo "vins_workspace=$VINS_WS"
    echo "vins_initial_ransac_seed=$RANSAC_SEED"
    echo "ros_port=$port"
  } > "$run_dir/comparison_arm_manifest.txt"
  if run_complete "$run_dir"; then
    echo "reuse backend run_dir=$run_dir"
    return 0
  fi
  set +e
  PYTHON_BIN="$PYTHON_BIN" VINS_INITIAL_RANSAC_SEED="$RANSAC_SEED" \
    PREPARE_BAG=0 EXPORT_FEATURES=0 RUN_VINS=1 VINS_INPUT_MODE=features \
    VINS_WS="$VINS_WS" RAW_BAG="$raw_bag" FEATURE_BAG="$feature_bag" \
    TAG="$tag" PORT="$port" \
    bash scripts/run_mimir_uw_vins_eval.sh \
      hybrid_superpoint_lightglue "$environment" "$track" "$start" "$duration" 1 \
      > "$run_dir/runner_stdout.log" 2>&1
  status=$?
  set -e
  printf '%s\n' "$status" > "$run_dir/runner_exit_status.txt"
  echo "finished backend=ours status=$status run_dir=$run_dir"
  return 0
}

wait_for_slot() {
  local max_jobs="$1"
  while (( $(jobs -pr | wc -l) >= max_jobs )); do
    wait -n
  done
}

echo "phase=ours_export windows=${#WINDOWS[@]} max_jobs=$MAX_EXPORT_JOBS"
for row in "${WINDOWS[@]}"; do
  window_enabled "$row" || continue
  wait_for_slot "$MAX_EXPORT_JOBS"
  export_ours "$row" &
done
wait

echo "phase=ours_vins windows=${#WINDOWS[@]} max_jobs=$MAX_VINS_JOBS seed=$RANSAC_SEED"
for index in "${!WINDOWS[@]}"; do
  window_enabled "${WINDOWS[$index]}" || continue
  wait_for_slot "$MAX_VINS_JOBS"
  run_ours_vins "$index" "${WINDOWS[$index]}" &
done
wait

echo "completed tag_prefix=$TAG_PREFIX export_prefix=$EXPORT_PREFIX"
