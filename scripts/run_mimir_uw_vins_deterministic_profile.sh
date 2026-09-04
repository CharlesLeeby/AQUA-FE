#!/usr/bin/env bash
set -euo pipefail

# Deterministic comparison profile for MIMIR-UW replay.
#
# The ordinary real-time VINS profile stops Ceres by wall-clock time. Under
# concurrent CPU load, nominally identical 0.04 s replays changed APE by more
# than 2 m. A generous time ceiling plus a fixed iteration cap makes the
# solver stop by iteration count instead, while single-thread numerical
# libraries remove another avoidable source of scheduling variability.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export VINS_MAX_SOLVER_TIME="${VINS_MAX_SOLVER_TIME:-10}"
export VINS_MAX_NUM_ITERATIONS="${VINS_MAX_NUM_ITERATIONS:-8}"
export VINS_INITIAL_SFM_MAX_SOLVER_TIME="${VINS_INITIAL_SFM_MAX_SOLVER_TIME:-10}"
export VINS_INITIAL_SFM_MAX_NUM_ITERATIONS="${VINS_INITIAL_SFM_MAX_NUM_ITERATIONS:-50}"
export VINS_INITIAL_RANSAC_SEED="${VINS_INITIAL_RANSAC_SEED:-0}"

exec bash "$SCRIPT_DIR/run_mimir_uw_vins_health_profile.sh" "$@"
