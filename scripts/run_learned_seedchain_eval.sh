#!/usr/bin/env bash
set -euo pipefail

# Cross-dataset entry point for the low-texture XFeat seed-chain profile.
#
# Default behavior is export-only with FORCE_EXPORT=1 so candidate windows are
# checked against the current source tree before spending time on VINS replay.
#
# Examples:
#   bash scripts/run_learned_seedchain_eval.sh ntnu fjord_1 85 10
#   bash scripts/run_learned_seedchain_eval.sh cirs 575 30
#   bash scripts/run_learned_seedchain_eval.sh aqualoc_real h07 1660 1740
#   bash scripts/run_learned_seedchain_eval.sh aqualoc_archaeo 6 2210 2460
#   bash scripts/run_learned_seedchain_eval.sh afrl 70 30

usage() {
  cat >&2 <<'EOF'
usage:
  run_learned_seedchain_eval.sh ntnu DATASET START_S DURATION_S [METHOD] [EVERY_N]
  run_learned_seedchain_eval.sh cirs START_S DURATION_S [METHOD] [EVERY_N]
  run_learned_seedchain_eval.sh aqualoc_real HARBOR_SEQ START_INDEX END_INDEX [METHOD] [EVERY_N]
  run_learned_seedchain_eval.sh aqualoc_archaeo SEQ START_INDEX END_INDEX [METHOD] [EVERY_N]
  run_learned_seedchain_eval.sh afrl [fr|cave] START_S DURATION_S [METHOD] [EVERY_N]

Environment:
  RUN_VINS=0 by default. Set RUN_VINS=1 for replay after export behavior is sane.
  FORCE_EXPORT=1 by default. Set FORCE_EXPORT=0 to reuse an existing feature bag.
  AQUAFE_SEEDCHAIN_PROFILE=lineage_early_seed_noharm_v4 by default outside CIRS.
  This conservative independent-mirror profile never evicts KLT to admit
  learned sidecars. Historical contribution scans must name their old profile.
EOF
}

if [[ $# -lt 1 ]]; then
  usage
  exit 2
fi

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
DATASET_FAMILY="$1"
shift

export ROOT
export RUN_VINS="${RUN_VINS:-0}"
export FORCE_EXPORT="${FORCE_EXPORT:-1}"
export METHOD_DEFAULT="${METHOD_DEFAULT:-hybrid_xfeat}"

if [[ -z "${AQUAFE_SEEDCHAIN_PROFILE+x}" ]]; then
  if [[ "$DATASET_FAMILY" == "cirs" ]]; then
    export AQUAFE_SEEDCHAIN_PROFILE="cirs_dense_start"
  else
    export AQUAFE_SEEDCHAIN_PROFILE="lineage_early_seed_noharm_v4"
  fi
fi

source "$ROOT/scripts/learned_seedchain_env.sh"

slugify() {
  printf "%s" "$1" | tr '/:,' '___'
}

normalize_harbor_seq() {
  local seq="$1"
  seq="${seq#h}"
  seq="${seq#H}"
  printf "%d" "$((10#$seq))"
}

case "$DATASET_FAMILY" in
  ntnu)
    if [[ $# -lt 3 ]]; then usage; exit 2; fi
    DATASET="$1"; START="$2"; DURATION="$3"
    METHOD="${4:-$METHOD_DEFAULT}"
    EVERY_N="${5:-2}"
    TAG="${TAG:-jul01_seedchain_ntnu_$(slugify "$DATASET")_s${START}_d${DURATION}}"
    export TAG
    bash "$ROOT/scripts/run_ntnu_vins_eval.sh" external "$DATASET" "$START" "$DURATION" "$METHOD" "$EVERY_N"
    ;;
  cirs)
    if [[ $# -lt 2 ]]; then usage; exit 2; fi
    START="$1"; DURATION="$2"
    METHOD="${3:-$METHOD_DEFAULT}"
    EVERY_N="${4:-1}"
    TAG="${TAG:-jul01_seedchain_cirs_s${START}_d${DURATION}}"
    export TAG
    bash "$ROOT/scripts/run_cirs_caves_vins_eval.sh" external "$START" "$DURATION" "$METHOD" "$EVERY_N"
    ;;
  aqualoc_real)
    if [[ $# -lt 3 ]]; then usage; exit 2; fi
    HARBOR_SEQ="$(normalize_harbor_seq "$1")"
    START="$2"; END="$3"
    METHOD="${4:-$METHOD_DEFAULT}"
    EVERY_N="${5:-2}"
    TAG="${TAG:-jul01_seedchain_aqualoc_h$(printf "%02d" "$HARBOR_SEQ")_${START}_${END}}"
    export HARBOR_SEQ TAG
    bash "$ROOT/scripts/run_aqualoc_real_vins_eval.sh" external "$START" "$END" "$METHOD" "$EVERY_N"
    ;;
  aqualoc_archaeo|aqualoc)
    if [[ $# -lt 3 ]]; then usage; exit 2; fi
    SEQ="$1"; START="$2"; END="$3"
    METHOD="${4:-$METHOD_DEFAULT}"
    EVERY_N="${5:-2}"
    TAG="${TAG:-jul01_seedchain_aqualoc_archaeo$(printf "%02d" "$((10#$SEQ))")_${START}_${END}}"
    export TAG
    bash "$ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh" external "$SEQ" "$START" "$END" "$METHOD" "$EVERY_N"
    ;;
  afrl)
    if [[ "${1:-}" == "fr" || "${1:-}" == "cave" ]]; then
      shift
    fi
    if [[ $# -lt 2 ]]; then usage; exit 2; fi
    START="$1"; DURATION="$2"
    METHOD="${3:-$METHOD_DEFAULT}"
    EVERY_N="${4:-2}"
    TAG="${TAG:-jul01_seedchain_afrl_s${START}_d${DURATION}}"
    export TAG
    bash "$ROOT/scripts/run_afrl_cave_vins_eval.sh" external "$METHOD" "$START" "$DURATION" "$EVERY_N"
    ;;
  *)
    echo "unsupported dataset family: $DATASET_FAMILY" >&2
    usage
    exit 2
    ;;
esac
