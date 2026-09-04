#!/usr/bin/env bash
set -euo pipefail

python3 -m uw_frontend.evaluation.run_frontend_eval \
  --input datasets/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz \
  --image-prefix harbor_images_sequence_07 \
  --config uw_frontend/configs/klt_frontend.yaml \
  --method "${METHOD:-klt}" \
  --max-frames "${MAX_FRAMES:-60}" \
  --output-csv "logs/aqualoc_harbor07_${METHOD:-klt}_frontend_smoke.csv" \
  --save-viz-dir "logs/aqualoc_harbor07_${METHOD:-klt}_viz" \
  --save-viz-every 20
