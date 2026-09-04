#!/usr/bin/env bash
set -euo pipefail

# Independent KLT abstention for a rejected P05 M contract. This path never
# reuses the XFeat bag and never counts as the modern learned baseline.

SCRIPT_ROOT="$(readlink -f "$(dirname "${BASH_SOURCE[0]}")/..")"
ROOT="${ROOT:-$SCRIPT_ROOT}"
if [[ "${AQUAFE_P05_TEST_HOOKS:-0}" == "1" ]]; then
  GENERIC_FALLBACK="${AQUAFE_P05_GENERIC_FALLBACK_RUNNER:-$SCRIPT_ROOT/scripts/run_isj_classical_contract_fallback_v4.sh}"
else
  GENERIC_FALLBACK="$SCRIPT_ROOT/scripts/run_isj_classical_contract_fallback_v4.sh"
fi
family="${1:?usage: run_p05_classical_contract_fallback_v2.sh DATASET_FAMILY ...}"

unset FEATURE_BAG_OVERRIDE P05_QUALITY_CONTRACT_ATTESTATION QUALITY_CONTRACT_ATTESTATION
export P05_GUARD_RESULT_LABEL=KLT_BACKEND_CONTRACT_FALLBACK_P05_M_REJECTED
export COUNTS_AS_MODERN_BASELINE=0
export TAG="isj_p05_M_REJECTED_KLT_$(date -u +%Y%m%dT%H%M%SZ)_$$"

case "$family" in
  ntnu)
    dataset="${2:?missing NTNU sequence}"
    start="${3:?missing start seconds}"
    duration="${4:?missing duration seconds}"
    every_n="${5:-2}"
    fallback_args=(ntnu "$dataset" "$start" "$duration" p05_m_rejected "$every_n")
    ;;
  aqualoc_archaeology|aqualoc_archaeo)
    sequence="${2:?missing AQUALOC archaeology sequence}"
    start="${3:?missing start index}"
    end="${4:?missing end index}"
    every_n="${5:-2}"
    fallback_args=(aqualoc_archaeology "$sequence" "$start" "$end" p05_m_rejected "$every_n")
    ;;
  aqualoc_harbor|aqualoc_real)
    sequence="${2:?missing AQUALOC harbor sequence}"
    start="${3:?missing start index}"
    end="${4:?missing end index}"
    every_n="${5:-2}"
    fallback_args=(aqualoc_real "$sequence" "$start" "$end" p05_m_rejected "$every_n")
    ;;
  afrl)
    dataset="${2:?missing AFRL sequence}"
    start="${3:?missing start seconds}"
    duration="${4:?missing duration seconds}"
    every_n="${5:-2}"
    fallback_args=(afrl_dataset "$dataset" "$start" "$duration" p05_m_rejected "$every_n")
    ;;
  *)
    echo "unsupported P05 family for independent KLT fallback: $family" >&2
    exit 2
    ;;
esac

echo "result_label=$P05_GUARD_RESULT_LABEL" >&2
echo "counts_as_modern_baseline=0" >&2
echo "fallback_source=fresh_independent_KLT_never_P05_bag" >&2
exec bash "$GENERIC_FALLBACK" "${fallback_args[@]}"
