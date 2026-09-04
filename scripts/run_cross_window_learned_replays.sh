#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
cd "$ROOT"

REPEATS="${REPEATS:-3}"
START_PORT="${START_PORT:-11480}"
TAG_PREFIX="${TAG_PREFIX:-crossv36}"
POST_PLAY_SLEEP="${POST_PLAY_SLEEP:-5}"
PLAY_RATE="${PLAY_RATE:-1.0}"

run_one() {
  local seq="$1"
  local start="$2"
  local end="$3"
  local method="$4"
  local feature_bag="$5"
  local tag="$6"
  local port="$7"

  echo "=== $tag ==="
  FEATURE_BAG_OVERRIDE="$feature_bag" \
  TAG="$tag" \
  PORT="$port" \
  PLAY_RATE="$PLAY_RATE" \
  POST_PLAY_SLEEP="$POST_PLAY_SLEEP" \
  ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" "$method" 2
}

for rep in $(seq 1 "$REPEATS"); do
  run_one 8 4520 4680 klt \
    "$ROOT/logs/aqualoc_archaeo_vins/external_klt_every2_formal3_klt_a08_4520_4680/features.bag" \
    "${TAG_PREFIX}_a08_4520_4680_klt_rep${rep}" "$((START_PORT + rep))"
  run_one 8 4520 4680 hybrid_superpoint_lightglue \
    "$ROOT/logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_formal_loftr_positive_a08_4520_4680/features.bag" \
    "${TAG_PREFIX}_a08_4520_4680_formal_loftr_rep${rep}" "$((START_PORT + 100 + rep))"
done

for rep in $(seq 1 "$REPEATS"); do
  run_one 9 5920 6060 klt \
    "$ROOT/logs/aqualoc_archaeo_vins/external_klt_every2_slamgate_v24_a09_5920_6060_klt_denseinit/features.bag" \
    "${TAG_PREFIX}_a09_5920_6060_klt_rep${rep}" "$((START_PORT + 200 + rep))"
  run_one 9 5920 6060 hybrid_superpoint_lightglue \
    "$ROOT/logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_slamgate_v24_a09_5920_6060_proposed_denseinit_loftr6/features.bag" \
    "${TAG_PREFIX}_a09_5920_6060_loftr_rep${rep}" "$((START_PORT + 300 + rep))"
done

python3 scripts/summarize_run_evidence.py \
  --runs \
  logs/aqualoc_archaeo_vins/external_klt_every2_${TAG_PREFIX}_a08_4520_4680_klt_rep* \
  logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_${TAG_PREFIX}_a08_4520_4680_formal_loftr_rep* \
  logs/aqualoc_archaeo_vins/external_klt_every2_${TAG_PREFIX}_a09_5920_6060_klt_rep* \
  logs/aqualoc_archaeo_vins/external_hybrid_superpoint_lightglue_every2_${TAG_PREFIX}_a09_5920_6060_loftr_rep* \
  --output-csv "logs/${TAG_PREFIX}_a08_a09_evidence.csv"

python3 scripts/make_cross_window_learned_report.py \
  --tag-prefix "$TAG_PREFIX" \
  --output-md "logs/${TAG_PREFIX}_learned_sidecar_validation.md" \
  --output-csv "logs/${TAG_PREFIX}_learned_sidecar_validation.csv"
