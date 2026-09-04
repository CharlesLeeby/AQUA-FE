#!/usr/bin/env bash
set -euo pipefail

START_INDEX="${START_INDEX:?set START_INDEX}"
END_INDEX="${END_INDEX:?set END_INDEX}"
TAG="${TAG:-${START_INDEX}_${END_INDEX}}"
INPUT="${INPUT:-datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz}"
PREFIX="${PREFIX:-harbor_images_sequence_07}"
CONFIG="${CONFIG:-uw_frontend/configs/klt_frontend.yaml}"

for METHOD in klt orb hybrid; do
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "${INPUT}" \
    --image-prefix "${PREFIX}" \
    --config "${CONFIG}" \
    --method "${METHOD}" \
    --start-index "${START_INDEX}" \
    --end-index "${END_INDEX}" \
    --output-csv "logs/aqualoc_harbor07_${TAG}_${METHOD}.csv" \
    --save-viz-dir "logs/aqualoc_harbor07_${TAG}_${METHOD}_viz" \
    --save-viz-every 30
done

python3 -m uw_frontend.evaluation.summarize_results \
  "logs/aqualoc_harbor07_${TAG}_klt.csv" \
  "logs/aqualoc_harbor07_${TAG}_orb.csv" \
  "logs/aqualoc_harbor07_${TAG}_hybrid.csv" \
  --output-csv "logs/aqualoc_harbor07_${TAG}_compare_summary.csv" \
  --output-md "logs/aqualoc_harbor07_${TAG}_compare_summary.md"

