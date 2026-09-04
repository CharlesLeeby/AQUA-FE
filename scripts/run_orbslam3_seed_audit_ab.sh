#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 7 ]]; then
  echo "usage: $0 DATASET_DIR TIMES_FILE CONFIG FULL_SEEDS DROP_SEEDS OUTPUT_ROOT TAG" >&2
  exit 2
fi

DATASET_DIR="$1"
TIMES_FILE="$2"
CONFIG="$3"
FULL_SEEDS="$4"
DROP_SEEDS="$5"
OUTPUT_ROOT="$(realpath -m "$6")"
TAG="$7"
TRIPLET_RUNNER="$(realpath "$(dirname "$0")/run_orbslam3_seeded_triplet.sh")"

if [[ -e "$OUTPUT_ROOT" && ! -d "$OUTPUT_ROOT" ]]; then
  echo "refusing existing non-directory output path: $OUTPUT_ROOT" >&2
  exit 2
fi
if [[ -d "$OUTPUT_ROOT" ]]; then
  first_entry="$(find "$OUTPUT_ROOT" -mindepth 1 -maxdepth 1 -print -quit)"
  if [[ -n "$first_entry" ]]; then
    echo "refusing non-empty output root: $OUTPUT_ROOT" >&2
    exit 2
  fi
fi

mkdir -p "$OUTPUT_ROOT/audit_on" "$OUTPUT_ROOT/audit_off"
SCHEDULE="$OUTPUT_ROOT/audit_ab_schedule.csv"
printf 'repeat,role_order,first_state,second_state\n' > "$SCHEDULE"

role_orders=(
  "orb_only drop full"
  "orb_only full drop"
  "drop orb_only full"
  "drop full orb_only"
  "full orb_only drop"
  "full drop orb_only"
  "orb_only drop full"
  "full drop orb_only"
)

for repeat in $(seq 1 8); do
  role_order="${role_orders[$((repeat - 1))]}"
  if (( repeat % 2 == 1 )); then
    states=(on off)
  else
    states=(off on)
  fi
  printf '%d,"%s",%s,%s\n' \
    "$repeat" "$role_order" "${states[0]}" "${states[1]}" >> "$SCHEDULE"

  for state in "${states[@]}"; do
    if [[ "$state" == "on" ]]; then
      audit_enabled=1
    else
      audit_enabled=0
    fi
    ORB_SLAM3_ENABLE_SEED_AUDIT="$audit_enabled" \
    ORB_SLAM3_ROLE_ORDER="$role_order" \
      bash "$TRIPLET_RUNNER" \
        "$DATASET_DIR" "$TIMES_FILE" "$CONFIG" "$FULL_SEEDS" "$DROP_SEEDS" \
        "$OUTPUT_ROOT/audit_$state" "${TAG}_audit_${state}" "$repeat" "$repeat"
  done
done

echo "completed audit A/B regression output_root=$OUTPUT_ROOT schedule=$SCHEDULE"
