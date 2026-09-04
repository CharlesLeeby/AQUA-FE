#!/usr/bin/env bash
set -euo pipefail

cd /home/ma/AQUA-FE_WS
python3 scripts/agent_trajectory_validation_recompute.py --write-tum "$@"
