#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 || $# -gt 8 ]]; then
  echo "usage: $0 BASE_BAG SIDECAR_BAG OUTPUT_DIR MAX_LINEAGES [MIN_DISTANCE_PX] [IGNORE_ZERO_BASE_SPEEDS] [MIN_OBSERVATIONS] [REARM_ABSENT_FRAMES]" >&2
  exit 2
fi

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
BASE_BAG="$(realpath "$1")"
SIDECAR_BAG="$(realpath "$2")"
OUTPUT_DIR="$(realpath -m "$3")"
MAX_LINEAGES="$4"
MIN_DISTANCE_PX="${5:-20}"
IGNORE_ZERO_BASE_SPEEDS="${6:-0}"
MIN_OBSERVATIONS="${7:-5}"
REARM_ABSENT_FRAMES="${8:-0}"

if [[ ! -f "$BASE_BAG" || ! -f "$SIDECAR_BAG" ]]; then
  echo "missing base or sidecar bag" >&2
  exit 2
fi
if [[ "$MAX_LINEAGES" -lt 1 || "$MIN_OBSERVATIONS" -lt 1 ]]; then
  echo "MAX_LINEAGES and MIN_OBSERVATIONS must be positive" >&2
  exit 2
fi
if [[ "$REARM_ABSENT_FRAMES" -lt 0 ]]; then
  echo "REARM_ABSENT_FRAMES cannot be negative" >&2
  exit 2
fi
if [[ "$IGNORE_ZERO_BASE_SPEEDS" != "0" && "$IGNORE_ZERO_BASE_SPEEDS" != "1" ]]; then
  echo "IGNORE_ZERO_BASE_SPEEDS must be 0 or 1" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"
DROP_BAG="$OUTPUT_DIR/drop_whole_lineage.bag"
DROP_STATS="$OUTPUT_DIR/drop_whole_lineage_stats.csv"
FULL_BAG="$OUTPUT_DIR/full_merged.bag"
FULL_STATS="$OUTPUT_DIR/lineage_selection.csv"

python3 "$ROOT/scripts/filter_feature_bag_by_channel.py" \
  --input-bag "$BASE_BAG" \
  --output-bag "$DROP_BAG" \
  --stats-csv "$DROP_STATS" \
  --drop-learned-track-lineage

SHADOW_ARGS=(
  bag
  --base-topic /feature_tracker/feature
  --sidecar-topic /feature_tracker/sidecar
  --source-code 20
  --min-observations "$MIN_OBSERVATIONS"
  --rank-observations 5
  --min-distance-px "$MIN_DISTANCE_PX"
  --min-motion-ratio 0.6
  --max-motion-ratio 1.5
  --max-lineages "$MAX_LINEAGES"
  --remap-id-base 10000000
  --base-bag "$DROP_BAG"
  --sidecar-bag "$SIDECAR_BAG"
  --output-bag "$FULL_BAG"
  --stats-csv "$FULL_STATS"
  --match-tolerance 0.02
)
if [[ "$IGNORE_ZERO_BASE_SPEEDS" == "1" ]]; then
  SHADOW_ARGS+=(--ignore-zero-base-speeds)
fi
if [[ "$REARM_ABSENT_FRAMES" -gt 0 ]]; then
  SHADOW_ARGS+=(--rearm-absent-frames "$REARM_ABSENT_FRAMES")
fi
python3 "$ROOT/uw_frontend/ros/causal_lineage_shadow_node.py" "${SHADOW_ARGS[@]}"

{
  printf 'base_bag=%s\n' "$BASE_BAG"
  printf 'sidecar_bag=%s\n' "$SIDECAR_BAG"
  printf 'drop_bag=%s\n' "$DROP_BAG"
  printf 'full_bag=%s\n' "$FULL_BAG"
  printf 'max_lineages=%s\n' "$MAX_LINEAGES"
  printf 'min_distance_px=%s\n' "$MIN_DISTANCE_PX"
  printf 'ignore_zero_base_speeds=%s\n' "$IGNORE_ZERO_BASE_SPEEDS"
  printf 'min_observations=%s\n' "$MIN_OBSERVATIONS"
  printf 'rearm_absent_frames=%s\n' "$REARM_ABSENT_FRAMES"
  printf 'drop_bag_sha256=%s\n' "$(sha256sum "$DROP_BAG" | awk '{print $1}')"
  printf 'full_bag_sha256=%s\n' "$(sha256sum "$FULL_BAG" | awk '{print $1}')"
} > "$OUTPUT_DIR/manifest.txt"

cat "$OUTPUT_DIR/manifest.txt"
