#!/usr/bin/env bash
set -euo pipefail

# Minimal, space-conscious downloader for the underwater VIO/SLAM study.
# Default target is well below 6 GB. Large downloads are opt-in.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="${ROOT_DIR}/datasets"
AQUALOC_TOKEN="79b03788f29148ca84e5"
AQUALOC_BASE="https://seafile.lirmm.fr/d/${AQUALOC_TOKEN}/files/"
MAX_GB="${MAX_GB:-6}"

mkdir -p \
  "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_calibration_files" \
  "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_groundtruth_files" \
  "${DATA_DIR}/aqualoc/samples" \
  "${DATA_DIR}/tank" \
  "${DATA_DIR}/ntnu" \
  "${DATA_DIR}/afrl" \
  "${DATA_DIR}/uvvid" \
  "${DATA_DIR}/flsea_vi"

download_aqualoc_file() {
  local remote_path="$1"
  local output_path="$2"
  wget -c -T 60 -t 10 --progress=dot:giga \
    -O "${output_path}" \
    "${AQUALOC_BASE}?p=${remote_path}&dl=1"
}

usage() {
  cat <<EOF
Usage: $0 [metadata|aqualoc-small|check-space|large-help]

metadata       Download only small pages/metadata/calibration/GT files.
aqualoc-small  Download AQUALOC Harbor sequence 07 raw tar.gz (~341 MiB).
check-space    Print local disk usage.
large-help     Print commands for larger datasets; does not download them.

Environment:
  MAX_GB=${MAX_GB}  Soft cap used for reporting. The script never deletes files.
EOF
}

case "${1:-metadata}" in
  metadata)
    wget -T 45 -t 2 -O "${DATA_DIR}/aqualoc/index.html" "https://www.lirmm.fr/aqualoc/" || true
    wget -T 45 -t 2 -O "${DATA_DIR}/aqualoc/seafile_index.html" "https://seafile.lirmm.fr/d/${AQUALOC_TOKEN}/" || true
    python3 "${ROOT_DIR}/scripts/seafile_list.py" --token "${AQUALOC_TOKEN}" --max-depth 3 --json > "${DATA_DIR}/aqualoc/seafile_tree.json"
    python3 "${ROOT_DIR}/scripts/seafile_list.py" --token "${AQUALOC_TOKEN}" --max-depth 3 > "${DATA_DIR}/aqualoc/seafile_tree.txt"
    download_aqualoc_file "/README.md" "${DATA_DIR}/aqualoc/README.md"
    download_aqualoc_file "/Harbor_sites_sequences/harbor_calibration_files/harbor_camera_calib.yaml" "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_calibration_files/harbor_camera_calib.yaml"
    download_aqualoc_file "/Harbor_sites_sequences/harbor_calibration_files/harbor_imu_camera_calib.yaml" "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_calibration_files/harbor_imu_camera_calib.yaml"
    download_aqualoc_file "/Harbor_sites_sequences/harbor_calibration_files/harbor_imu_noises.yaml" "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_calibration_files/harbor_imu_noises.yaml"
    download_aqualoc_file "/Harbor_sites_sequences/harbor_groundtruth_files/new_harbor_colmap_traj_sequence_07.txt" "${DATA_DIR}/aqualoc/metadata/Harbor_sites_sequences/harbor_groundtruth_files/new_harbor_colmap_traj_sequence_07.txt"
    wget -T 45 -t 2 -O "${DATA_DIR}/tank/index.html" "https://senseroboticslab.github.io/underwater-tank-dataset/" || true
    wget -T 45 -t 2 -O "${DATA_DIR}/tank/download.html" "https://senseroboticslab.github.io/underwater-tank-dataset/download/" || true
    wget -T 45 -t 2 -O "${DATA_DIR}/flsea_vi/kaggle_page.html" "https://www.kaggle.com/datasets/viseaonlab/flsea-vi" || true
    ;;
  aqualoc-small)
    download_aqualoc_file "/Harbor_sites_sequences/harbor_sequence_07_raw_data.tar.gz" "${DATA_DIR}/aqualoc/samples/harbor_sequence_07_raw_data.tar.gz"
    ;;
  check-space)
    du -sh "${DATA_DIR}" "${ROOT_DIR}/external_tools" 2>/dev/null || true
    df -h "${ROOT_DIR}"
    ;;
  large-help)
    cat <<'EOF'
Large downloads intentionally not run by default:

# AQUALOC, next-smallest raw sequences:
bash scripts/download_underwater_minimal.sh aqualoc-small
# Other AQUALOC examples can be downloaded by editing remote path in the script.

# AFRL via HuggingFace (smallest ROS1 bag is still ~2.36 GB; full repo 26.9 GB):
# huggingface-cli download afrl-uw/stereo-vi-underwater-dataset \
#   ros1_bags/cemetery.bag camera_imu_parameters colmap_groundtruth \
#   --repo-type dataset --local-dir datasets/afrl

# NTNU via HuggingFace (smallest published subset trajectory is >12 GB):
# huggingface-cli download ntnu-arl/underwater-datasets calibrations \
#   --repo-type dataset --local-dir datasets/ntnu

# UVVID is ~9.96 GB on data.dtu.dk, above the 6 GB cap.

# FLSea VI is ~92.35 GB on Kaggle, above the 6 GB cap and requires Kaggle auth:
# kaggle datasets download -d viseaonlab/flsea-vi -p datasets/flsea_vi

# Tank Dataset requires the official request form; store links under datasets/tank
# after approval, then download one sequence at a time.
EOF
    ;;
  *)
    usage
    exit 2
    ;;
esac

