#!/usr/bin/env bash
set -euo pipefail

# Versioned fail-closed entrypoint for P05/P07 M. The v1 scientific baseline
# remains unchanged; this wrapper binds it to the frozen producer/consumer.

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
ROOT="${ROOT:-$SCRIPT_ROOT}"
if [[ "${AQUAFE_P05_TEST_HOOKS:-0}" == "1" ]]; then
  CONTRACT="${AQUAFE_P05_BACKEND_CONTRACT:-$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json}"
  CHECKER="${AQUAFE_P05_CONTRACT_CHECKER:-$SCRIPT_ROOT/scripts/check_p05_xfeat_backend_contract_v1.py}"
  P05_RUNNER="${AQUAFE_P05_RUNNER:-$SCRIPT_ROOT/scripts/run_p05_modern_xfeat_baseline.sh}"
  FALLBACK_RUNNER="${AQUAFE_P05_FALLBACK_RUNNER:-$SCRIPT_ROOT/scripts/run_p05_classical_contract_fallback_v2.sh}"
else
  CONTRACT="$SCRIPT_ROOT/papers/ieee_sensors_journal_experiments/p05/backend_consumer_contract_xfeat_v1.json"
  CHECKER="$SCRIPT_ROOT/scripts/check_p05_xfeat_backend_contract_v1.py"
  P05_RUNNER="$SCRIPT_ROOT/scripts/run_p05_modern_xfeat_baseline.sh"
  FALLBACK_RUNNER="$SCRIPT_ROOT/scripts/run_p05_classical_contract_fallback_v2.sh"
fi
DECISION_DIR="${AQUAFE_P05_DECISION_DIR:-$SCRIPT_ROOT/logs/backend_contract_decisions/p05}"

family="${1:?usage: run_p05_modern_xfeat_baseline_guarded_v2.sh DATASET_FAMILY ...}"
case "$family" in
  ntnu|aqualoc_archaeology|aqualoc_archaeo|aqualoc_harbor|aqualoc_real)
    frame_offset=1
    ;;
  afrl)
    frame_offset=0
    ;;
  *)
    frame_offset=-1
    ;;
esac
every_n="${5:-2}"

mkdir -p "$DECISION_DIR"
decision="$DECISION_DIR/p05_xfeat_guard_$(date -u +%Y%m%dT%H%M%SZ)_$$_decision.json"

# Freeze the values that the unchanged v1 runner passes to the exporter and
# backend. FORCE_EXPORT=1 prevents un-attested implicit reuse by run directory.
export VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
export FRONTEND_CONFIG="$SCRIPT_ROOT/uw_frontend/configs/experiments/isj_p05_xfeat_pairwise_nativeq.yaml"
export P05_METHOD=xfeat
export PREPROCESS=adaptive_clahe
export PROCESS_SKIPPED_FRAMES=1
export MEASUREMENT_SELECTION=0
export FORMAL_THREE_LAYER_EXPORT=0
export VINS_SAFE_SOURCE_SELECTION=0
export EXPORT_MAX_FEATURES=350
export VINS_MAX_CNT=350
export SEMIDENSE_FALLBACK_METHOD=none
export BACKEND_QUALITY_MODE=vins_safe
export BACKEND_QUALITY_ALPHA=0.65
export BACKEND_QUALITY_FLOOR=0.80
export RAW_QUALITY_TO_BACKEND=0
export CONSTANT_QUALITY_TO_BACKEND=0
export BACKEND_LEARNED_QUALITY_SCALE=1.0
export BACKEND_SP_LG_QUALITY_SCALE=1.0
export BACKEND_XFEAT_QUALITY_SCALE=1.0
export BACKEND_LOFTR_QUALITY_SCALE=1.0
export BACKEND_LEARNED_QUALITY_CONST=
export BACKEND_SP_LG_QUALITY_CONST=
export BACKEND_XFEAT_QUALITY_CONST=
export BACKEND_LOFTR_QUALITY_CONST=
export VINS_MULTIPLE_THREAD=0
export RUN_VINS="${RUN_VINS:-0}"
export FORCE_EXPORT=1
export EXPORT_FEATURES=1

checker_args=(
  --contract "$CONTRACT"
  --workspace-root "$ROOT"
  --vins-workspace "$VINS_WS"
  --backend-root "$VINS_WS/src/VINS-Fusion-master"
  --binary "$VINS_WS/devel/lib/vins/vins_node"
  --exporter "$SCRIPT_ROOT/uw_frontend/ros/export_vins_features.py"
  --frontend-config "$FRONTEND_CONFIG"
  --family "$family"
  --every-n "$every_n"
  --frame-offset "$frame_offset"
  --run-vins "$RUN_VINS"
  --decision-json "$decision"
)
if [[ -n "${FEATURE_BAG_OVERRIDE:-}" ]]; then
  attestation="${P05_QUALITY_CONTRACT_ATTESTATION:-${QUALITY_CONTRACT_ATTESTATION:-${FEATURE_BAG_OVERRIDE}.p05-xfeat-contract.json}}"
  checker_args+=(
    --feature-bag "$FEATURE_BAG_OVERRIDE"
    --bag-attestation "$attestation"
  )
fi

set +e
python3 "$CHECKER" "${checker_args[@]}"
guard_rc=$?
set -e

if [[ "$guard_rc" -eq 0 ]]; then
  echo "P05 XFeat backend contract PASS; decision=$decision"
  if [[ "${AQUAFE_P05_GUARD_ONLY:-0}" == "1" ]]; then
    exit 0
  fi
  export P05_GUARD_RESULT_LABEL=M_XFEAT_PAIRWISE_NATIVEQ_V1
  export COUNTS_AS_MODERN_BASELINE=1
  exec bash "$P05_RUNNER" "$@"
fi

echo "P05 XFeat contract rejected M (rc=$guard_rc); decision=$decision" >&2
echo "M is not executed and this request cannot count as the modern baseline" >&2
if [[ "${AQUAFE_P05_GUARD_ONLY:-0}" == "1" ]]; then
  exit 42
fi
if [[ "${AQUAFE_P05_ON_MISMATCH:-fallback}" == "reject" ]]; then
  exit 42
fi
if [[ "${AQUAFE_P05_ON_MISMATCH:-fallback}" != "fallback" ]]; then
  echo "invalid AQUAFE_P05_ON_MISMATCH; expected fallback or reject" >&2
  exit 42
fi

# The fallback receives neither the reused learned bag nor its attestation.
unset FEATURE_BAG_OVERRIDE P05_QUALITY_CONTRACT_ATTESTATION QUALITY_CONTRACT_ATTESTATION
export P05_GUARD_RESULT_LABEL=KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED
export COUNTS_AS_MODERN_BASELINE=0
exec bash "$FALLBACK_RUNNER" "$@"
