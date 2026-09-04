#!/usr/bin/env bash
set -eo pipefail

# Minimal non-interactive environment for the persistent user service.  This
# changes no experiment option; it only exposes ROS Noetic's Python modules.
source /opt/ros/noetic/setup.bash
set -u
exec /usr/bin/python3 \
  /home/ma/AQUA-FE_WS/scripts/run_frontend_same_backend_confirmatory_v3_batch.py
