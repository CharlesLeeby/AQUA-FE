#!/usr/bin/env bash
set -eo pipefail

# Persistent non-interactive environment for the frozen backend batch.
source /opt/ros/noetic/setup.bash
set -u
exec /usr/bin/python3 \
  /home/ma/AQUA-FE_WS/scripts/run_frontend_same_backend_confirmatory_v3_backend.py
