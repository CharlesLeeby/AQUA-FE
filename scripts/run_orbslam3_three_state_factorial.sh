#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "usage: $0 DATASET_DIR TIMES_FILE CONFIG FULL_SEEDS DROP_SEEDS OUTPUT_ROOT TAG PREAUDIT_ORB_ROOT CURRENT_ORB_ROOT" >&2
  exit 2
fi

DATASET_DIR="$1"
TIMES_FILE="$2"
CONFIG="$3"
FULL_SEEDS="$4"
DROP_SEEDS="$5"
OUTPUT_ROOT="$(realpath -m "$6")"
TAG="$7"
PREAUDIT_ORB_ROOT="$(realpath "$8")"
CURRENT_ORB_ROOT="$(realpath "$9")"
TRIPLET_RUNNER="${TRIPLET_RUNNER:-$(realpath "$(dirname "$0")/run_orbslam3_seeded_triplet.sh")}" 

for root in "$PREAUDIT_ORB_ROOT" "$CURRENT_ORB_ROOT"; do
  if [[ ! -x "$root/Examples_old/Monocular/mono_euroc_old" ]]; then
    echo "missing ORB executable under $root" >&2
    exit 2
  fi
done
if [[ ! -x "$TRIPLET_RUNNER" ]]; then
  echo "triplet runner is not executable: $TRIPLET_RUNNER" >&2
  exit 2
fi

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

states=(preaudit_reconstructed current_audit_off current_audit_on)
for state in "${states[@]}"; do
  mkdir -p "$OUTPUT_ROOT/$state"
done

SCHEDULE="$OUTPUT_ROOT/three_state_schedule.csv"
printf 'repeat,role_order,state_order\n' > "$SCHEDULE"

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
state_orders=(
  "preaudit_reconstructed current_audit_off current_audit_on"
  "current_audit_off current_audit_on preaudit_reconstructed"
  "current_audit_on preaudit_reconstructed current_audit_off"
  "preaudit_reconstructed current_audit_on current_audit_off"
  "current_audit_off preaudit_reconstructed current_audit_on"
  "current_audit_on current_audit_off preaudit_reconstructed"
  "preaudit_reconstructed current_audit_off current_audit_on"
  "current_audit_off current_audit_on preaudit_reconstructed"
)

for repeat in $(seq 1 8); do
  role_order="${role_orders[$((repeat - 1))]}"
  state_order="${state_orders[$((repeat - 1))]}"
  printf '%d,"%s","%s"\n' "$repeat" "$role_order" "$state_order" >> "$SCHEDULE"

  read -r -a ordered_states <<< "$state_order"
  for state in "${ordered_states[@]}"; do
    case "$state" in
      preaudit_reconstructed)
        orb_root="$PREAUDIT_ORB_ROOT"
        audit_enabled=0
        ;;
      current_audit_off)
        orb_root="$CURRENT_ORB_ROOT"
        audit_enabled=0
        ;;
      current_audit_on)
        orb_root="$CURRENT_ORB_ROOT"
        audit_enabled=1
        ;;
      *)
        echo "invalid state: $state" >&2
        exit 2
        ;;
    esac

    ORB_ROOT="$orb_root" \
    ORB_SLAM3_ENABLE_SEED_AUDIT="$audit_enabled" \
    ORB_SLAM3_SEED_PHASE=all \
    ORB_SLAM3_SEED_MIN_OK_FRAMES=0 \
    ORB_SLAM3_ROLE_ORDER="$role_order" \
      bash "$TRIPLET_RUNNER" \
        "$DATASET_DIR" "$TIMES_FILE" "$CONFIG" "$FULL_SEEDS" "$DROP_SEEDS" \
        "$OUTPUT_ROOT/$state" "${TAG}_${state}" "$repeat" "$repeat"
  done
done

echo "completed three-state factorial output_root=$OUTPUT_ROOT schedule=$SCHEDULE"
