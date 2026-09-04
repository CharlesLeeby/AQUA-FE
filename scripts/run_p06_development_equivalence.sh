#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
OUT="${OUT:-$ROOT/papers/ieee_sensors_journal_experiments/p06/development_equivalence/aqualoc_a06_2210_2460}"
CONFIG="$ROOT/uw_frontend/configs/klt_frontend.yaml"
CAMERA="$OUT/aqualoc_archaeo06_pinhole.yaml"
DIRECT="$OUT/direct_metrics.csv"
ROS_METRICS="$OUT/ros_metrics.csv"
ROS_FEATURES="$OUT/ros_features.bag"

mkdir -p "$OUT"
cd "$ROOT"

if [[ ! -s "$DIRECT" ]]; then
  python3 -m uw_frontend.evaluation.run_frontend_eval \
    --input datasets/aqualoc/samples/archaeo_sequence_06_raw_data.tar.gz \
    --image-prefix images_sequence_6 \
    --output-csv "$DIRECT" \
    --method klt \
    --config "$CONFIG" \
    --preprocess adaptive_clahe \
    --every-n 1 \
    --start-index 2210 \
    --end-index 2460
fi

if [[ ! -s "$ROS_METRICS" || ! -s "$ROS_FEATURES" ]]; then
  source /opt/ros/noetic/setup.bash
  python3 -m uw_frontend.ros.export_vins_features \
    --bag datasets/aqualoc/rosbags/archaeo06_2210_2460.bag \
    --image-topic /camera/image_raw \
    --camera-config "$CAMERA" \
    --output-bag "$ROS_FEATURES" \
    --config "$CONFIG" \
    --method klt \
    --semidense-fallback-method none \
    --every-n 1 \
    --frame-offset 0 \
    --export-max-features 350 \
    --export-min-age 0 \
    --preprocess adaptive_clahe \
    --timestamp-source header \
    --max-header-stamp-delta 0.25 \
    --invalid-header-policy skip \
    --metrics-csv "$ROS_METRICS"
fi

python3 scripts/audit_p06_screening_equivalence.py \
  --direct-csv "$DIRECT" \
  --ros-csv "$ROS_METRICS" \
  --output-csv "$OUT/frame_equivalence_audit.csv" \
  --output-json "$OUT/equivalence_audit.json" \
  --tolerance 1e-12
