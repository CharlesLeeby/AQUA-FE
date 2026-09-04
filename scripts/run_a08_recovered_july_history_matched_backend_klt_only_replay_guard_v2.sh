#!/usr/bin/env bash
set -euo pipefail

# Campaign-specific fail-closed wrapper.  The inherited v1 FD guard remains the
# execution mechanism, but this wrapper makes the v2 diversion incapable of
# selecting the failed XFeat arm or its byte-identical KLT fallback directory.

if [[ "$#" -ne 6 ]]; then
  echo "usage: $0 DATASET SEQ START END METHOD EVERY_N" >&2
  exit 64
fi

DATASET="$1"
SEQ="$2"
START="$3"
END="$4"
METHOD="$5"
EVERY_N="$6"

: "${A08_KLT_ONLY_REPLAYS_V2:?missing KLT-only v2 authorization marker}"
: "${A08_ITEM_ID:?missing item identity}"
: "${A08_ITEM_OUTPUT_DIR:?missing item output directory}"
: "${A08_WORKSPACE_LINK:?missing workspace link}"
: "${A08_ACCEPTED_FRONTEND_RECEIPT:?missing accepted KLT receipt binding}"
: "${A08_XFEAT_TERMINAL_DISPOSITION:?missing terminal XFeat disposition}"
: "${A08_XFEAT_BACKEND_LAUNCHED_COUNT:?missing XFeat backend launch count}"
: "${A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED:?missing contribution boundary}"
: "${FEATURE_BAG_OVERRIDE:?missing accepted KLT feature bag}"

EXPECTED_RECEIPT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/frontends_v1/klt_attempt002_export_receipt_v1.json"
EXPECTED_BAG="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins/external_klt_every2_a08_recoveredjuly_hist0000_4660_klt_export_attempt002_rosseed_v1/features.bag"
EXPECTED_OUTPUT_ROOT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_replays_v2"
EXPECTED_WORKSPACE_ROOT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
BASE_GUARD="/home/ma/AQUA-FE_WS/scripts/run_a08_recovered_july_backend_replay_only_guard_v1.sh"

if [[ "$A08_KLT_ONLY_REPLAYS_V2" != "1" || \
      "$A08_XFEAT_TERMINAL_DISPOSITION" != "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED" || \
      "$A08_XFEAT_BACKEND_LAUNCHED_COUNT" != "0" || \
      "$A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED" != "0" ]]; then
  echo "A08 KLT-only v2 scientific-boundary mismatch" >&2
  exit 65
fi
if [[ "$DATASET" != "aqualoc_archaeo" || "$SEQ" != "8" || \
      "$START" != "0" || "$END" != "4660" || "$EVERY_N" != "2" || \
      "$METHOD" != "klt" ]]; then
  echo "A08 KLT-only v2 history or method mismatch" >&2
  exit 65
fi
if [[ ! "$A08_ITEM_ID" =~ ^KLT_R0[1-5]$ ]]; then
  echo "A08 KLT-only v2 item mismatch" >&2
  exit 65
fi
REPEAT="${A08_ITEM_ID#KLT_R}"
EXPECTED_TAG="a08_recoveredjuly_hist0000_4660_backend_klt_only_r${REPEAT}_v2"
EXPECTED_OUTPUT="${EXPECTED_OUTPUT_ROOT}/${A08_ITEM_ID}"
EXPECTED_WORKSPACE="${EXPECTED_WORKSPACE_ROOT}/external_klt_every2_${EXPECTED_TAG}"
if [[ "$A08_ITEM_OUTPUT_DIR" != "$EXPECTED_OUTPUT" || \
      "$A08_WORKSPACE_LINK" != "$EXPECTED_WORKSPACE" || \
      "$TAG" != "$EXPECTED_TAG" ]]; then
  echo "A08 KLT-only v2 output namespace mismatch" >&2
  exit 65
fi
if [[ "$A08_ACCEPTED_FRONTEND_RECEIPT" != "$EXPECTED_RECEIPT" || \
      "$FEATURE_BAG_OVERRIDE" != "$EXPECTED_BAG" ]]; then
  echo "A08 KLT-only v2 accepted-input mismatch" >&2
  exit 65
fi
case "$FEATURE_BAG_OVERRIDE" in
  *hybrid_xfeat*|*probe*|*fallback*|*klt_safe_fallback*)
    echo "A08 KLT-only v2 forbidden XFeat/fallback input" >&2
    exit 65
    ;;
esac
if [[ ! -f "$BASE_GUARD" || -L "$BASE_GUARD" ]]; then
  echo "A08 base FD replay guard unavailable" >&2
  exit 65
fi

exec /usr/bin/bash "$BASE_GUARD" "$DATASET" "$SEQ" "$START" "$END" "$METHOD" "$EVERY_N"
