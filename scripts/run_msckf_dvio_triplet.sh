#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "usage: $0 CASE_BAG_ROOT OUTPUT_ROOT [ROUNDS]" >&2
  exit 2
fi

CASE_BAG_ROOT="$(realpath "$1")"
OUTPUT_ROOT="$(realpath -m "$2")"
ROUNDS="${3:-5}"
ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
PLAY_RATE="${PLAY_RATE:-0.5}"

if [[ "$ROUNDS" -lt 1 || "$ROUNDS" -gt 20 ]]; then
  echo "ROUNDS must be between 1 and 20" >&2
  exit 2
fi
for role in full drop klt; do
  if [[ ! -f "$CASE_BAG_ROOT/$role/features_msckf.bag" ]]; then
    echo "missing $role bag under $CASE_BAG_ROOT" >&2
    exit 2
  fi
done
mkdir -p "$OUTPUT_ROOT"

orders=(
  "full drop klt"
  "drop klt full"
  "klt full drop"
  "full klt drop"
  "klt drop full"
  "drop full klt"
)

{
  printf 'case_bag_root=%s\n' "$CASE_BAG_ROOT"
  printf 'rounds=%s\n' "$ROUNDS"
  printf 'play_rate=%s\n' "$PLAY_RATE"
  printf 'camera_noise=%s\n' "${MSCKF_CAMERA_NOISE:-}"
  printf 'bias_json=%s\n' "${MSCKF_INIT_BIAS_JSON:-}"
  printf 'runner_sha256=%s\n' "$(sha256sum "$ROOT/scripts/run_msckf_dvio_featurebag_eval.sh" | awk '{print $1}')"
} > "$OUTPUT_ROOT/protocol_manifest.txt"

for round in $(seq 1 "$ROUNDS"); do
  order="${orders[$(((round - 1) % ${#orders[@]}))]}"
  for role in $order; do
    run_dir="$OUTPUT_ROOT/round_$(printf '%02d' "$round")_${role}"
    if [[ -s "$run_dir/metrics.txt" ]]; then
      echo "skip completed round=$round role=$role run_dir=$run_dir"
      continue
    fi
    echo "start round=$round role=$role order='$order'"
    PLAY_RATE="$PLAY_RATE" \
      "$ROOT/scripts/run_msckf_dvio_featurebag_eval.sh" \
      "$CASE_BAG_ROOT/$role/features_msckf.bag" \
      "$run_dir" \
      "$role"
    python3 "$ROOT/scripts/summarize_msckf_dvio_triplet.py" \
      --run-root "$OUTPUT_ROOT" \
      --rounds "$ROUNDS" \
      --output-csv "$OUTPUT_ROOT/runs.csv" \
      --output-report "$OUTPUT_ROOT/report.md" \
      > "$OUTPUT_ROOT/summary_latest.log"
  done
done

python3 "$ROOT/scripts/summarize_msckf_dvio_triplet.py" \
  --run-root "$OUTPUT_ROOT" \
  --rounds "$ROUNDS" \
  --output-csv "$OUTPUT_ROOT/runs.csv" \
  --output-report "$OUTPUT_ROOT/report.md"
