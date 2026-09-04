#!/usr/bin/env bash
set -euo pipefail

START_INDEX="${START_INDEX:-1660}"
END_INDEX="${END_INDEX:-1950}"
TAG="${TAG:-${START_INDEX}_${END_INDEX}_learned}"
INPUT="${INPUT:-datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz}"
PREFIX="${PREFIX:-harbor_images_sequence_07}"
CONFIG="${CONFIG:-uw_frontend/configs/klt_frontend.yaml}"
METHODS="${METHODS:-klt hybrid xfeat hybrid_xfeat superpoint_lightglue hybrid_superpoint_lightglue loftr hybrid_loftr}"

csvs=()
for METHOD in ${METHODS}; do
  out_csv="logs/aqualoc_harbor07_${TAG}_${METHOD}.csv"
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input "${INPUT}" \
    --image-prefix "${PREFIX}" \
    --config "${CONFIG}" \
    --method "${METHOD}" \
    --start-index "${START_INDEX}" \
    --end-index "${END_INDEX}" \
    --output-csv "${out_csv}"
  csvs+=("${out_csv}")
done

python3 -m uw_frontend.evaluation.summarize_results \
  "${csvs[@]}" \
  --output-csv "logs/aqualoc_harbor07_${TAG}_compare_summary.csv" \
  --output-md "logs/aqualoc_harbor07_${TAG}_compare_summary.md"
