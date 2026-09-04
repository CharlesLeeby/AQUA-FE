#!/usr/bin/env bash
set -euo pipefail

# Export-only gate ladder for CIRS XFeat seed diagnostics.
#
# The goal is to separate three failure modes:
#   1) learned matcher proposes too few candidates,
#   2) LK/KLT confirmation kills most proposed seeds,
#   3) backend export gates are too strict.
#
# Usage:
#   CIRS_WINDOWS="900:30 750:30" bash scripts/run_cirs_xfeat_gate_ladder.sh

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
RUNNER="$ROOT/scripts/run_cirs_caves_vins_eval.sh"
OUT_CSV="${OUT_CSV:-$ROOT/logs/jun24_cirs_xfeat_gate_ladder_summary.csv}"
CIRS_WINDOWS="${CIRS_WINDOWS:-900:30 750:30 840:30 960:30}"

BASE_CONFIG="$ROOT/uw_frontend/configs/experiments/cirs_identity_churn_xfeat_probe.yaml"
AGE3_CONFIG="$ROOT/uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml"
AGE5_CONFIG="$ROOT/uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe_age5.yaml"

run_stage() {
  local start="$1"
  local duration="$2"
  local stage="$3"
  shift 3

  echo "[gate-ladder] window=s${start},d${duration} stage=${stage}"
  env \
    RUN_VINS=0 \
    FORCE_EXPORT=1 \
    PREPARE_BAG=1 \
    METHOD=hybrid_xfeat \
    TAG="jun24_ladder_${stage}_s${start}_d${duration}" \
    "$@" \
    bash "$RUNNER" external "$start" "$duration" hybrid_xfeat 1
}

for spec in $CIRS_WINDOWS; do
  start="${spec%%:*}"
  duration="${spec##*:}"

  # Stage 0: loose diagnostic. Keep the tracker active but make export gates
  # permissive enough to expose pre-gate and candidate counts in metrics.
  run_stage "$start" "$duration" "seed_raw" \
    FRONTEND_CONFIG="$BASE_CONFIG" \
    VINS_SAFE_SOURCE_SELECTION=0 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    LEARNED_EXPORT_BENEFIT_GATE=0 \
    LEARNED_EXPORT_ONLINE_SEED_GATE=0 \
    LEARNED_EXPORT_MIN_AGE=1 \
    LEARNED_EXPORT_MIN_QUALITY=0.05 \
    LEARNED_EXPORT_MIN_NCC=0.25 \
    LEARNED_EXPORT_MAX_FB=3.0

  # Stage 1: two-frame confirmation, still without online freshness/warmup.
  run_stage "$start" "$duration" "seed_confirm2" \
    FRONTEND_CONFIG="$BASE_CONFIG" \
    VINS_SAFE_SOURCE_SELECTION=0 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    LEARNED_EXPORT_BENEFIT_GATE=0 \
    LEARNED_EXPORT_ONLINE_SEED_GATE=0 \
    LEARNED_EXPORT_MIN_AGE=2 \
    LEARNED_EXPORT_MIN_QUALITY=0.10 \
    LEARNED_EXPORT_MIN_NCC=0.42 \
    LEARNED_EXPORT_MAX_FB=1.20

  # Stage 2: three-frame KLT/LK confirmation.
  run_stage "$start" "$duration" "seed_age3" \
    FRONTEND_CONFIG="$AGE3_CONFIG" \
    VINS_SAFE_SOURCE_SELECTION=0 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    LEARNED_EXPORT_BENEFIT_GATE=0 \
    LEARNED_EXPORT_ONLINE_SEED_GATE=0 \
    LEARNED_EXPORT_MIN_AGE=3 \
    LEARNED_EXPORT_MIN_QUALITY=0.10 \
    LEARNED_EXPORT_MIN_NCC=0.42 \
    LEARNED_EXPORT_MAX_FB=1.20

  # Stage 3: five-frame KLT/LK confirmation.
  run_stage "$start" "$duration" "seed_age5" \
    FRONTEND_CONFIG="$AGE5_CONFIG" \
    VINS_SAFE_SOURCE_SELECTION=0 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    LEARNED_EXPORT_BENEFIT_GATE=0 \
    LEARNED_EXPORT_ONLINE_SEED_GATE=0 \
    LEARNED_EXPORT_MIN_AGE=5 \
    LEARNED_EXPORT_MIN_QUALITY=0.10 \
    LEARNED_EXPORT_MIN_NCC=0.42 \
    LEARNED_EXPORT_MAX_FB=1.20

  # Stage 4: final-style online safety gate from the current best CIRS probe.
  run_stage "$start" "$duration" "online_w8_framefresh5_cap20" \
    FRONTEND_CONFIG="$AGE3_CONFIG" \
    VINS_SAFE_SOURCE_SELECTION=1 \
    VINS_SAFE_WARMUP_FRAMES=0 \
    VINS_SAFE_MIN_LEARNED_AGE=1 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    LEARNED_EXPORT_BENEFIT_GATE=0 \
    LEARNED_EXPORT_ONLINE_SEED_GATE=1 \
    LEARNED_EXPORT_ONLINE_SEED_SOURCES=xfeat \
    LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES=8 \
    LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS=20 \
    LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME=4 \
    LEARNED_EXPORT_ONLINE_SEED_MIN_AGE=1 \
    LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY=0.10 \
    LEARNED_EXPORT_ONLINE_SEED_MIN_NCC=0.42 \
    LEARNED_EXPORT_ONLINE_SEED_MAX_FB=1.20 \
    LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED=1 \
    LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH=1 \
    LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE=frame \
    LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES=5
done

python3 "$ROOT/scripts/summarize_cirs_xfeat_gate_ladder.py" \
  --logs-root "$ROOT/logs/cirs_caves_vins" \
  --output-csv "$OUT_CSV"

echo "[gate-ladder] summary=$OUT_CSV"
