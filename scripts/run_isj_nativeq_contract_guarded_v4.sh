#!/usr/bin/env bash
set -euo pipefail

# Versioned guarded entrypoint. It preserves v3 scientific method identity and
# adds runtime enforcement of the quality-consumer contract.

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
CONTRACT="${AQUAFE_BACKEND_QUALITY_CONTRACT:-$ROOT/papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json}"
CHECKER="${AQUAFE_CONTRACT_CHECKER:-$ROOT/scripts/check_nativeq_backend_contract.py}"
PROPOSED_RUNNER="${AQUAFE_PROPOSED_RUNNER:-$ROOT/scripts/run_isj_nativeq_legacy_candidate.sh}"
FALLBACK_RUNNER="${AQUAFE_FALLBACK_RUNNER:-$ROOT/scripts/run_isj_classical_contract_fallback_v4.sh}"
DECISION_DIR="${AQUAFE_DECISION_DIR:-$ROOT/logs/backend_contract_decisions}"
mkdir -p "$DECISION_DIR"
decision="$DECISION_DIR/nativeq_guard_$(date -u +%Y%m%dT%H%M%SZ)_$$_decision.json"

# Do not preserve caller overrides for a frozen formal arm.
export BACKEND_QUALITY_MODE=vins_safe
export BACKEND_QUALITY_FLOOR=0.80
export BACKEND_QUALITY_ALPHA=0.65
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

checker_args=(
  --contract "$CONTRACT"
  --decision-json "$decision"
)
if [[ -n "${FEATURE_BAG_OVERRIDE:-}" ]]; then
  attestation="${QUALITY_CONTRACT_ATTESTATION:-${FEATURE_BAG_OVERRIDE}.quality-contract.json}"
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
  echo "native-q backend contract PASS; decision=$decision"
  if [[ "${AQUAFE_GUARD_ONLY:-0}" == "1" ]]; then
    exit 0
  fi
  exec bash "$PROPOSED_RUNNER" "$@"
fi

echo "native-q backend contract rejected learned execution (rc=$guard_rc); decision=$decision" >&2
echo "running an independent KLT contract fallback; it is not a proposed-arm result" >&2
if [[ "${AQUAFE_GUARD_ONLY:-0}" == "1" ]]; then
  exit 42
fi
exec bash "$FALLBACK_RUNNER" "$@"
