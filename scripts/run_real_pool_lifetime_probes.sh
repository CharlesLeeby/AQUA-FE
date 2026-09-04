#!/usr/bin/env bash
set -euo pipefail

root=/home/ma/AQUA-FE_WS
output_root=/home/ma/real_pool_frontend_lifetime_diag/probes
bag_root=/mnt/data/Dataset_pool/ros1_bags
config="$root/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
camera=/mnt/data/Dataset_pool/aqua_fe_real_pool_vins/front_cam_20260415_pinhole.yaml

run_probe() {
  local sequence="$1"
  local start="$2"
  local mode="$3"
  local profile="probe_s${start}_${mode}"
  local process_args=()
  if [[ "$mode" == processall ]]; then
    process_args+=(--process-skipped-frames)
  fi
  PYTHONDONTWRITEBYTECODE=1 python3 "$root/scripts/diagnose_real_pool_frontend_lifetime.py" \
    --bag "$bag_root/full_slam_20260608_${sequence}_cam_imu_dvl_imgshift_m085375.bag" \
    --sequence "$sequence" \
    --profile "$profile" \
    --image-topic /cam0/image_raw \
    --config "$config" \
    --camera-config "$camera" \
    --method klt \
    --preprocess none \
    --every-n 2 \
    --frame-offset 0 \
    --start-raw-index "$start" \
    --max-raw-frames 200 \
    --output-dir "$output_root/${sequence}_s${start}_${mode}" \
    "${process_args[@]}"
}

for spec in "171342 1000" "171342 2200" "171944 800" "171944 1700" "172529 3000" "172529 6500"; do
  read -r sequence start <<<"$spec"
  run_probe "$sequence" "$start" baseline
  run_probe "$sequence" "$start" processall
done
