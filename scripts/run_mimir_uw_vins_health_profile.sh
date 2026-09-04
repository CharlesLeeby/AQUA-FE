#!/usr/bin/env bash
set -euo pipefail

# Fail-safe profile for the synthetic MIMIR-UW monocular+IMU replay.
#
# This profile does not make an unobservable/low-texture window metrically
# correct.  It constrains the known zero IMU biases, rejects implausible
# initialization states, and stops a solution whose speed begins to diverge.
# The underlying runner arguments are passed through unchanged:
#   METHOD ENVIRONMENT TRACK START_OFFSET DURATION EVERY_N

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export CAMERA_AXIS_MODE="${CAMERA_AXIS_MODE:-opencv-optical}"
export VINS_INITIAL_RANSAC_SEED="${VINS_INITIAL_RANSAC_SEED:-0}"
export VINS_MAX_SOLVER_TIME="${VINS_MAX_SOLVER_TIME:-0.04}"
export VINS_MAX_NUM_ITERATIONS="${VINS_MAX_NUM_ITERATIONS:-8}"

# MIMIR's simulated IMU has essentially zero bias.  The test VINS fork uses
# these opt-in priors; the protected production backend is not modified.
export MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR="${MIMIR_ENABLE_SYNTHETIC_BIAS_PRIOR:-1}"
export VINS_SYNTHETIC_ACC_BIAS_SIGMA="${VINS_SYNTHETIC_ACC_BIAS_SIGMA:-0.01}"
export VINS_SYNTHETIC_GYR_BIAS_SIGMA="${VINS_SYNTHETIC_GYR_BIAS_SIGMA:-0.001}"
export VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT="${VINS_SYNTHETIC_RESET_BIASES_AFTER_ALIGNMENT:-1}"

export VINS_INITIAL_MIN_SCALE="${VINS_INITIAL_MIN_SCALE:-0.02}"
export VINS_INITIAL_MAX_GYRO_BIAS_DELTA="${VINS_INITIAL_MAX_GYRO_BIAS_DELTA:-0.10}"
export VINS_INITIAL_ROLLBACK_ON_FAILURE="${VINS_INITIAL_ROLLBACK_ON_FAILURE:-0}"

# The bad SeaFloor windows exhibit a 2.3--2.7 m/s^2 near-constant trajectory
# error acceleration and quickly exceed the dataset's observed vehicle speed.
export VINS_ENABLE_FAILURE_DETECTION="${VINS_ENABLE_FAILURE_DETECTION:-1}"
export VINS_FAILURE_MAX_SPEED="${VINS_FAILURE_MAX_SPEED:-10}"

exec bash "$SCRIPT_DIR/run_mimir_uw_vins_eval.sh" "$@"
