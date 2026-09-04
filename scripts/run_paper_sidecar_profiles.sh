#!/usr/bin/env bash
set -euo pipefail

# Reproducible paper-facing profiles for the underwater learned-sidecar frontend.
#
# The intent is to keep one clear experimental contract:
#   - KLT/GFTT is the VINS-visible backbone.
#   - XFeat may enter only as a small, repeated, new-cell coverage sidecar.
#   - LoFTR may enter only as an extreme low-texture / planar sidecar.
#   - Normal/high-support windows should export zero learned observations.
#
# Examples:
#   scripts/run_paper_sidecar_profiles.sh ntnu_probe_xfeat
#   scripts/run_paper_sidecar_profiles.sh ntnu_vins_xfeat_pair fjord_1 0 30
#   scripts/run_paper_sidecar_profiles.sh aqualoc_a06_loftr_pair 2210 2460
#   scripts/run_paper_sidecar_profiles.sh aqualoc_harbor_loftr_v31_pair 4 2000 2360
#   scripts/run_paper_sidecar_profiles.sh h07_noharm_pair 1660 1950

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
cd "$ROOT"

TASK="${1:-ntnu_probe_xfeat}"
shift || true

KLT_CONFIG="${KLT_CONFIG:-$ROOT/uw_frontend/configs/klt_frontend.yaml}"
SAFE_CONFIG="${SAFE_CONFIG:-$ROOT/uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml}"
LOFTR_CONFIG="${LOFTR_CONFIG:-$ROOT/uw_frontend/configs/experiments/loftr_extreme_only_frontend.yaml}"
LOFTR_POSITIVE_CONFIG="${LOFTR_POSITIVE_CONFIG:-$ROOT/uw_frontend/configs/experiments/formal_loftr_positive_vins_frontend.yaml}"
LOFTR_V31_REPRO_CONFIG="${LOFTR_V31_REPRO_CONFIG:-$ROOT/uw_frontend/configs/experiments/formal_loftr_v31_repro_frontend.yaml}"
LOFTR_MIRROR_CONFIG="${LOFTR_MIRROR_CONFIG:-$ROOT/uw_frontend/configs/experiments/formal_loftr_mirror_contribution_v33_frontend.yaml}"

COMMON_THREADS=(
  OMP_NUM_THREADS=2
  MKL_NUM_THREADS=2
  OPENBLAS_NUM_THREADS=2
)

paper_xfeat_env() {
  env "${COMMON_THREADS[@]}" \
    FRONTEND_CONFIG="$SAFE_CONFIG" \
    PREPROCESS="${PREPROCESS:-adaptive_clahe}" \
    FORCE_EXPORT=1 \
    FORMAL_THREE_LAYER_EXPORT="${FORMAL_THREE_LAYER_EXPORT:-1}" \
    SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-none}" \
    PROCESS_SKIPPED_FRAMES="${PROCESS_SKIPPED_FRAMES:-1}" \
    MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}" \
    FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK="${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-1}" \
    FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE="${FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE:-1}" \
    INIT_PARALLAX_GATE="${INIT_PARALLAX_GATE:-1}" \
    INIT_PARALLAX_ADAPTIVE_SKIP="${INIT_PARALLAX_ADAPTIVE_SKIP:-0}" \
    EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-180}" \
    MEASUREMENT_SELECTION_MAX_FEATURES="${MEASUREMENT_SELECTION_MAX_FEATURES:-180}" \
    VINS_SAFE_MAX_TOTAL="${VINS_SAFE_MAX_TOTAL:-180}" \
    EXPORT_MIN_AGE="${EXPORT_MIN_AGE:-2}" \
    BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}" \
    BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.65}" \
    BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-0.80}" \
    BACKEND_LEARNED_QUALITY_SCALE="${BACKEND_LEARNED_QUALITY_SCALE:-1.0}" \
    BACKEND_SP_LG_QUALITY_SCALE="${BACKEND_SP_LG_QUALITY_SCALE:-1.0}" \
    BACKEND_XFEAT_QUALITY_SCALE="${BACKEND_XFEAT_QUALITY_SCALE:-1.0}" \
    BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-1.0}" \
    VINS_SAFE_SOURCE_SELECTION="${VINS_SAFE_SOURCE_SELECTION:-1}" \
    VINS_SAFE_WARMUP_FRAMES="${VINS_SAFE_WARMUP_FRAMES:-120}" \
    VINS_INIT_KLT_ONLY_FRAMES="${VINS_INIT_KLT_ONLY_FRAMES:-120}" \
    VINS_SAFE_MAX_LEARNED="${VINS_SAFE_MAX_LEARNED:-8}" \
    VINS_SAFE_MAX_RECOVERED="${VINS_SAFE_MAX_RECOVERED:-16}" \
    VINS_SAFE_MIN_LEARNED_AGE="${VINS_SAFE_MIN_LEARNED_AGE:-2}" \
    EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-1}" \
    MIRROR_MEASUREMENT_SELECTION_POLICY="${MIRROR_MEASUREMENT_SELECTION_POLICY:-baseline}" \
    LEARNED_EXPORT_DEGRADATION_GATE="${LEARNED_EXPORT_DEGRADATION_GATE:-1}" \
    LEARNED_EXPORT_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_MIN_CLASSICAL_TRACKS:-300}" \
    LEARNED_EXPORT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_MIN_CLASSICAL_GRID:-0.76}" \
    LEARNED_EXPORT_MIN_AGE="${LEARNED_EXPORT_MIN_AGE:-2}" \
    LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.08}" \
    LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.45}" \
    LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-1.20}" \
    LEARNED_EXPORT_GEOMETRY_GATE="${LEARNED_EXPORT_GEOMETRY_GATE:-1}" \
    LEARNED_EXPORT_REQUIRE_CONFIRMED="${LEARNED_EXPORT_REQUIRE_CONFIRMED:-1}" \
    LEARNED_EXPORT_BENEFIT_GATE="${LEARNED_EXPORT_BENEFIT_GATE:-1}" \
    LEARNED_EXPORT_BENEFIT_ALL_SOURCES="${LEARNED_EXPORT_BENEFIT_ALL_SOURCES:-1}" \
    LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-12}" \
    LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.0}" \
    LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}" \
    LEARNED_EXPORT_MIN_NEW_CELL_RATIO="${LEARNED_EXPORT_MIN_NEW_CELL_RATIO:-0.10}" \
    LEARNED_EXPORT_MAX_PER_NEW_CELL="${LEARNED_EXPORT_MAX_PER_NEW_CELL:-1}" \
    LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS:-220}" \
    LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX:-0.0}" \
    LEARNED_EXPORT_MIN_CLASSICAL_AGE="${LEARNED_EXPORT_MIN_CLASSICAL_AGE:-0.0}" \
    LEARNED_EXPORT_WEAK_CELL_RESCUE="${LEARNED_EXPORT_WEAK_CELL_RESCUE:-1}" \
    LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE:-0}" \
    LEARNED_EXPORT_NON_LOFTR_REQUIRES_DEGRADED_MODE="${LEARNED_EXPORT_NON_LOFTR_REQUIRES_DEGRADED_MODE:-0}" \
    LEARNED_EXPORT_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_WEAK_CELL_MAX_COUNT:-4}" \
    LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES:-5}" \
    LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY:-8}" \
    LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX:-3.0}" \
    LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID:-0.76}" \
    LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS:-220}" \
    LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE="${LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE:-1}" \
    LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE:-26}" \
    LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX:-10.5}" \
    LEARNED_EXPORT_ALLOW_ISOLATED_NON_LOFTR_SIDECARS="${LEARNED_EXPORT_ALLOW_ISOLATED_NON_LOFTR_SIDECARS:-0}" \
    LEARNED_EXPORT_ISOLATED_NON_LOFTR_MAX_COUNT="${LEARNED_EXPORT_ISOLATED_NON_LOFTR_MAX_COUNT:-2}" \
    LEARNED_EXPORT_VISIBLE_TRACK_GATE="${LEARNED_EXPORT_VISIBLE_TRACK_GATE:-1}" \
    LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES:-2}" \
    LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP="${LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP:-1}" \
    LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION="${LEARNED_EXPORT_REQUIRE_FRESH_NON_LOFTR_CONFIRMATION:-1}" \
    LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES="${LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES:-0}" \
    "$@"
}

paper_loftr_env() {
  env "${COMMON_THREADS[@]}" \
    FRONTEND_CONFIG="$LOFTR_CONFIG" \
    PREPROCESS=adaptive_clahe \
    FORCE_EXPORT=1 \
    FORMAL_THREE_LAYER_EXPORT=1 \
    SEMIDENSE_FALLBACK_METHOD=loftr \
    PROCESS_SKIPPED_FRAMES=1 \
    MEASUREMENT_SELECTION=0 \
    EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}" \
    EXPORT_MIN_AGE=2 \
    BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}" \
    BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.65}" \
    BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-none}" \
    BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-0.60}" \
    VINS_SAFE_SOURCE_SELECTION=1 \
    VINS_SAFE_WARMUP_FRAMES=20 \
    VINS_SAFE_MAX_LEARNED=24 \
    VINS_SAFE_MAX_RECOVERED=16 \
    VINS_SAFE_MIN_LEARNED_AGE=3 \
    INIT_LOFTR_SIDECAR_RESCUE="${INIT_LOFTR_SIDECAR_RESCUE:-1}" \
    INIT_LOFTR_SIDECAR_MAX_COUNT="${INIT_LOFTR_SIDECAR_MAX_COUNT:-6}" \
    LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES=8 \
    LEARNED_EXPORT_DEGRADATION_GATE=1 \
    LEARNED_EXPORT_MIN_CLASSICAL_TRACKS=300 \
    LEARNED_EXPORT_MIN_CLASSICAL_GRID=0.84 \
    LEARNED_EXPORT_MIN_AGE=5 \
    LEARNED_EXPORT_MIN_QUALITY=0.20 \
    LEARNED_EXPORT_MIN_NCC=0.58 \
    LEARNED_EXPORT_MAX_FB=0.90 \
    LEARNED_EXPORT_GEOMETRY_GATE=1 \
    LEARNED_EXPORT_REQUIRE_CONFIRMED=1 \
    LEARNED_EXPORT_BENEFIT_GATE=1 \
    LEARNED_EXPORT_LOFTR_PLANAR_RESCUE=1 \
    LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT=6 \
    LEARNED_EXPORT_LOFTR_PLANAR_MAX_CLASSICAL_GRID=0.92 \
    "$@"
}

paper_loftr_v31_env() {
  # Reproduction profile for the validated A06 low-texture / planar LoFTR
  # sidecar evidence. This intentionally keeps the KLT-visible backbone sparse
  # enough for the low-texture degeneracy gate to fire, then allows only small
  # confirmed LoFTR bursts through the VINS-safe export path.
  env "${COMMON_THREADS[@]}" \
    FRONTEND_CONFIG="$LOFTR_V31_REPRO_CONFIG" \
    PREPROCESS=adaptive_clahe \
    FORCE_EXPORT=1 \
    FORMAL_THREE_LAYER_EXPORT=1 \
    FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE="${FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE:-0}" \
    FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK="${FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK:-1}" \
    FORMAL_EXPORT_LEGACY_LOFTR_RESCUE="${FORMAL_EXPORT_LEGACY_LOFTR_RESCUE:-0}" \
    FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS="${FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS:-0}" \
    PROCESS_SKIPPED_FRAMES=1 \
    FRAME_OFFSET="${FRAME_OFFSET:-1}" \
    MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-1}" \
    EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}" \
    MEASUREMENT_SELECTION_MAX_FEATURES="${MEASUREMENT_SELECTION_MAX_FEATURES:-220}" \
    EXPORT_MIN_AGE=2 \
    BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}" \
    BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-0.80}" \
    BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.85}" \
    BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-1.0}" \
    VINS_SAFE_SOURCE_SELECTION=1 \
    VINS_SAFE_WARMUP_FRAMES=20 \
    VINS_SAFE_MAX_LEARNED=24 \
    VINS_SAFE_MAX_RECOVERED=16 \
    INIT_PARALLAX_GATE=1 \
    INIT_PARALLAX_THRESHOLD_PX=7.0 \
    INIT_PARALLAX_ADAPTIVE_SKIP="${INIT_PARALLAX_ADAPTIVE_SKIP:-1}" \
    INIT_PARALLAX_ADAPTIVE_SKIP_FRAMES="${INIT_PARALLAX_ADAPTIVE_SKIP_FRAMES:-4}" \
    INIT_PARALLAX_ADAPTIVE_MIN_PX="${INIT_PARALLAX_ADAPTIVE_MIN_PX:-3.0}" \
    INIT_PARALLAX_ADAPTIVE_MAX_PX="${INIT_PARALLAX_ADAPTIVE_MAX_PX:-7.0}" \
    INIT_LOFTR_SIDECAR_RESCUE="${INIT_LOFTR_SIDECAR_RESCUE:-1}" \
    INIT_LOFTR_SIDECAR_MAX_COUNT="${INIT_LOFTR_SIDECAR_MAX_COUNT:-6}" \
    LEARNED_EXPORT_DEGRADATION_GATE=1 \
    LEARNED_EXPORT_BENEFIT_GATE=1 \
    LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-10}" \
    LEARNED_EXPORT_GEOMETRY_GATE=1 \
    LEARNED_EXPORT_LOFTR_PLANAR_RESCUE=1 \
    LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT:-6}" \
    LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX:-1.2}" \
    LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE=1 \
    LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT:-6}" \
    LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS:-220}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX:-}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX:-3.7}" \
    LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT="${LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT:-0}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES="${LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES:-0}" \
    LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT="${LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT:-1}" \
    EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-0}" \
    MIRROR_MEASUREMENT_SELECTION_POLICY="${MIRROR_MEASUREMENT_SELECTION_POLICY:-baseline}" \
    "$@"
}

paper_loftr_mirror_env() {
  # Final proposed-safe profile for paper-facing VINS runs:
  # preserve the KLT/GFTT mirror backbone, then add only tiny confirmed LoFTR
  # sidecars when low-coverage/low-texture gates and F/E/H residual checks pass.
  env "${COMMON_THREADS[@]}" \
    FRONTEND_CONFIG="$LOFTR_MIRROR_CONFIG" \
    PREPROCESS=adaptive_clahe \
    FORCE_EXPORT=1 \
    FORMAL_THREE_LAYER_EXPORT=1 \
    FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE=1 \
    FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK=1 \
    EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-1}" \
    MIRROR_MEASUREMENT_SELECTION_POLICY="${MIRROR_MEASUREMENT_SELECTION_POLICY:-baseline}" \
    FORMAL_EXPORT_LEGACY_LOFTR_RESCUE=1 \
    FORMAL_EXPORT_ALLOW_LOW_PARALLAX_SIDECARS=1 \
    FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR=1 \
    SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-loftr}" \
    PROCESS_SKIPPED_FRAMES=1 \
    FRAME_OFFSET="${FRAME_OFFSET:-1}" \
    MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-0}" \
    EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}" \
    EXPORT_MIN_AGE=2 \
    BACKEND_QUALITY_MODE="${BACKEND_QUALITY_MODE:-vins_safe}" \
    BACKEND_QUALITY_FLOOR="${BACKEND_QUALITY_FLOOR:-none}" \
    BACKEND_QUALITY_ALPHA="${BACKEND_QUALITY_ALPHA:-0.65}" \
    BACKEND_LOFTR_QUALITY_SCALE="${BACKEND_LOFTR_QUALITY_SCALE:-1.0}" \
    VINS_SAFE_SOURCE_SELECTION=1 \
    VINS_SAFE_WARMUP_FRAMES="${VINS_SAFE_WARMUP_FRAMES:-20}" \
    VINS_SAFE_MAX_LEARNED="${VINS_SAFE_MAX_LEARNED:-24}" \
    VINS_SAFE_MAX_RECOVERED="${VINS_SAFE_MAX_RECOVERED:-16}" \
    VINS_SAFE_MIN_LEARNED_AGE="${VINS_SAFE_MIN_LEARNED_AGE:-3}" \
    VINS_SAFE_PRESERVE_CLASSICAL_BUDGET="${VINS_SAFE_PRESERVE_CLASSICAL_BUDGET:-1}" \
    INIT_PARALLAX_GATE=1 \
    INIT_PARALLAX_THRESHOLD_PX="${INIT_PARALLAX_THRESHOLD_PX:-7.0}" \
    INIT_PARALLAX_ADAPTIVE_SKIP="${INIT_PARALLAX_ADAPTIVE_SKIP:-0}" \
    INIT_LOFTR_SIDECAR_RESCUE="${INIT_LOFTR_SIDECAR_RESCUE:-1}" \
    INIT_LOFTR_SIDECAR_MAX_COUNT="${INIT_LOFTR_SIDECAR_MAX_COUNT:-6}" \
    LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES="${LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES:-8}" \
    LEARNED_EXPORT_DEGRADATION_GATE=1 \
    LEARNED_EXPORT_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_MIN_CLASSICAL_TRACKS:-300}" \
    LEARNED_EXPORT_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_MIN_CLASSICAL_GRID:-0.84}" \
    LEARNED_EXPORT_MIN_AGE="${LEARNED_EXPORT_MIN_AGE:-5}" \
    LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.20}" \
    LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.58}" \
    LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-0.90}" \
    LEARNED_EXPORT_LOFTR_MIN_QUALITY="${LEARNED_EXPORT_LOFTR_MIN_QUALITY:-0.05}" \
    LEARNED_EXPORT_LOFTR_MIN_NCC="${LEARNED_EXPORT_LOFTR_MIN_NCC:-0.40}" \
    LEARNED_EXPORT_LOFTR_MAX_FB="${LEARNED_EXPORT_LOFTR_MAX_FB:-1.20}" \
    LEARNED_EXPORT_BENEFIT_GATE=1 \
    LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.041}" \
    LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}" \
    LEARNED_EXPORT_MIN_NEW_CELL_RATIO="${LEARNED_EXPORT_MIN_NEW_CELL_RATIO:-0.30}" \
    LEARNED_EXPORT_MAX_PER_NEW_CELL="${LEARNED_EXPORT_MAX_PER_NEW_CELL:-1}" \
    LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-12}" \
    LEARNED_EXPORT_LOFTR_PLANAR_RESCUE=1 \
    LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT="${LEARNED_EXPORT_LOFTR_PLANAR_MAX_COUNT:-6}" \
    LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_PLANAR_MIN_CLASSICAL_MOTION_PX:-1.2}" \
    LEARNED_EXPORT_LOFTR_WEAK_CELL_RESCUE=1 \
    LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_LOFTR_WEAK_CELL_MAX_COUNT:-6}" \
    LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS="${LEARNED_EXPORT_LOFTR_RESCUE_MAX_CLASSICAL_TRACKS:-220}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_INIT_PARALLAX_PX:-2.5}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_LOFTR_SUPPORT_MAX_CLASSICAL_MOTION_PX:-3.7}" \
    LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT="${LEARNED_EXPORT_LOFTR_MIN_EXPORT_COUNT:-6}" \
    LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES="${LEARNED_EXPORT_LOFTR_SUPPORT_COOLDOWN_FRAMES:-60}" \
    LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT="${LEARNED_EXPORT_ALLOW_EARLY_LOFTR_SUPPORT:-1}" \
    LEARNED_EXPORT_GEOMETRY_GATE=1 \
    LEARNED_EXPORT_REQUIRE_CONFIRMED=1 \
    "$@"
}

protected_klt_env() {
  env "${COMMON_THREADS[@]}" \
    FRONTEND_CONFIG="$SAFE_CONFIG" \
    PREPROCESS=adaptive_clahe \
    FORCE_EXPORT=1 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    SEMIDENSE_FALLBACK_METHOD=none \
    PROCESS_SKIPPED_FRAMES=1 \
    MEASUREMENT_SELECTION=1 \
    EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-180}" \
    EXPORT_MIN_AGE=2 \
    BACKEND_QUALITY_MODE=vins_safe \
    BACKEND_QUALITY_ALPHA=0.65 \
    BACKEND_QUALITY_FLOOR=0.80 \
    VINS_SAFE_SOURCE_SELECTION=1 \
    VINS_SAFE_WARMUP_FRAMES=20 \
    VINS_SAFE_MAX_LEARNED=8 \
    VINS_SAFE_MAX_RECOVERED=16 \
    VINS_SAFE_MIN_LEARNED_AGE=2 \
    EXPORT_CLASSICAL_MIRROR_BACKBONE=1 \
    MIRROR_MEASUREMENT_SELECTION_POLICY=baseline \
    LEARNED_EXPORT_DEGRADATION_GATE=1 \
    LEARNED_EXPORT_MIN_CLASSICAL_TRACKS=300 \
    LEARNED_EXPORT_MIN_CLASSICAL_GRID=0.76 \
    LEARNED_EXPORT_BENEFIT_GATE=1 \
    LEARNED_EXPORT_BENEFIT_ALL_SOURCES=1 \
    LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS=220 \
    "$@"
}

case "$TASK" in
  ntnu_probe_xfeat)
    # Export-only screen. Full VINS is launched only after a window exports
    # nonzero learned observations with acceptable gate diagnostics.
    WINDOWS_TEXT="${WINDOWS:-fjord_1:0:30 fjord_1:30:30 fjord_1:60:30 fjord_1:120:30 fjord_4:0:30 fjord_4:30:30 mclab_1:0:30 mclab_1:60:30}"
    read -r -a WINDOW_ITEMS <<< "$WINDOWS_TEXT"
    for item in "${WINDOW_ITEMS[@]}"; do
      IFS=: read -r dataset start duration <<< "$item"
      tag="paperprobe_${dataset}_s${start}_d${duration}_xfeat"
      paper_xfeat_env \
        RUN_VINS=0 \
        TAG="$tag" \
        ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_xfeat 2
    done
    ;;

  ntnu_vins_xfeat_pair)
    dataset="${1:-fjord_1}"
    start="${2:-0}"
    duration="${3:-30}"
    tag_base="${TAG_BASE:-paperpair_${dataset}_s${start}_d${duration}}"
    protected_klt_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_protected_klt" \
      PORT="${PORT_KLT:-11631}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" klt 2
    paper_xfeat_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_hybrid_xfeat" \
      PORT="${PORT_XFEAT:-11632}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_xfeat 2
    ;;

  ntnu_vins_xfeat_proposed)
    dataset="${1:-fjord_1}"
    start="${2:-0}"
    duration="${3:-30}"
    tag="${TAG:-paperprop_${dataset}_s${start}_d${duration}_hybrid_xfeat}"
    paper_xfeat_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11633}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_xfeat 2
    ;;

  h07_noharm_pair)
    start="${1:-1660}"
    end="${2:-1950}"
    tag_base="${TAG_BASE:-paperpair_h07_${start}_${end}}"
    protected_klt_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_protected_klt" \
      PORT="${PORT_KLT:-11641}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" klt 2
    paper_xfeat_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_hybrid_xfeat" \
      PORT="${PORT_XFEAT:-11642}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_xfeat 2
    ;;

  aqualoc_a06_loftr_pair)
    start="${1:-2210}"
    end="${2:-2460}"
    tag_base="${TAG_BASE:-paperpair_a06_${start}_${end}}"
    paper_loftr_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_protected_klt" \
      PORT="${PORT_KLT:-11651}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" klt 2
    paper_loftr_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_hybrid_loftr" \
      PORT="${PORT_LOFTR:-11652}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_a06_loftr_v31_pair)
    start="${1:-2210}"
    end="${2:-2460}"
    tag_base="${TAG_BASE:-paper_v31_a06_${start}_${end}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11661}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" klt 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11662}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" hybrid_superpoint_lightglue 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11663}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_a06_loftr_v31_proposed)
    start="${1:-2210}"
    end="${2:-2460}"
    tag="${TAG:-paper_v31_a06_${start}_${end}_loftr}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11664}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_a06_loftr_v31_klt)
    start="${1:-2210}"
    end="${2:-2460}"
    tag="${TAG:-paper_v31_a06_${start}_${end}_klt}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11665}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" klt 2
    ;;

  aqualoc_archaeo_loftr_v31_pair)
    seq="${1:-6}"
    start="${2:-2210}"
    end="${3:-2460}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag_base="${TAG_BASE:-paper_v31_a${seq_pad}_${start}_${end}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11681}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" klt 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11682}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11683}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_archaeo_loftr_v31_proposed)
    seq="${1:-6}"
    start="${2:-2210}"
    end="${3:-2460}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag="${TAG:-paper_v31_a${seq_pad}_${start}_${end}_loftr}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11683}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_archaeo_loftr_mirror_pair)
    seq="${1:-9}"
    start="${2:-5800}"
    end="${3:-6200}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag_base="${TAG_BASE:-paper_mirror_a${seq_pad}_${start}_${end}}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11701}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" klt 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr_mirror" \
      PORT="${PORT_NOLOFTR:-11702}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr_mirror" \
      PORT="${PORT_LOFTR:-11703}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_archaeo_loftr_mirror_proposed)
    seq="${1:-9}"
    start="${2:-5800}"
    end="${3:-6200}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag="${TAG:-paper_mirror_a${seq_pad}_${start}_${end}_loftr}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11703}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_archaeo_loftr_mirror_klt)
    # Single-arm classical control for a same-exporter ablation.  This keeps
    # the v33 mirror profile and backend settings identical to the proposed
    # arm while disabling the learned fallback and exporting KLT/GFTT only.
    seq="${1:-6}"
    start="${2:-2210}"
    end="${3:-2460}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag="${TAG:-paper_mirror_a${seq_pad}_${start}_${end}_klt}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11724}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external "$seq" "$start" "$end" klt 2
    ;;

  ntnu_loftr_mirror_pair)
    dataset="${1:-fjord_4}"
    start="${2:-30}"
    duration="${3:-20}"
    tag_base="${TAG_BASE:-paper_mirror_${dataset}_s${start}_d${duration}}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11711}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" klt 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr_mirror" \
      PORT="${PORT_NOLOFTR:-11712}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr_mirror" \
      PORT="${PORT_LOFTR:-11713}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    ;;

  ntnu_loftr_v31_pair)
    dataset="${1:-fjord_6}"
    start="${2:-45}"
    duration="${3:-45}"
    tag_base="${TAG_BASE:-paper_v31_${dataset}_s${start}_d${duration}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11811}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" klt 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11812}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11813}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    ;;

  ntnu_loftr_v31_proposed)
    dataset="${1:-fjord_6}"
    start="${2:-45}"
    duration="${3:-45}"
    tag="${TAG:-paper_v31_${dataset}_s${start}_d${duration}_loftr}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11813}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    ;;

  ntnu_loftr_mirror_proposed)
    dataset="${1:-fjord_4}"
    start="${2:-30}"
    duration="${3:-20}"
    tag="${TAG:-paper_mirror_${dataset}_s${start}_d${duration}_loftr}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11713}" \
      ./scripts/run_ntnu_vins_eval.sh external "$dataset" "$start" "$duration" hybrid_superpoint_lightglue 2
    ;;

  tank_loftr_mirror_pair)
    tag_base="${TAG_BASE:-paper_mirror_tank_short}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11731}" \
      ./scripts/run_tank_vins_eval.sh external klt 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr_mirror" \
      PORT="${PORT_NOLOFTR:-11732}" \
      ./scripts/run_tank_vins_eval.sh external hybrid_superpoint_lightglue 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr_mirror" \
      PORT="${PORT_LOFTR:-11733}" \
      ./scripts/run_tank_vins_eval.sh external hybrid_superpoint_lightglue 2
    ;;

  tank_loftr_mirror_proposed)
    tag="${TAG:-paper_mirror_tank_short_loftr}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11733}" \
      ./scripts/run_tank_vins_eval.sh external hybrid_superpoint_lightglue 2
    ;;

  afrl_loftr_mirror_pair)
    dataset="${1:-cemetery}"
    start="${2:-0}"
    duration="${3:-20}"
    tag_base="${TAG_BASE:-paper_mirror_afrl_${dataset}_s${start}_d${duration}}"
    afrl_bag="${RAW_BAG:-$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/${dataset}.bag}"
    afrl_gt="${GT_TXT:-$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/${dataset}.txt}"
    afrl_camchain="${CAMCHAIN:-$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_${dataset}.yaml}"
    paper_loftr_mirror_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11741}" \
      ./scripts/run_afrl_cave_vins_eval.sh external klt "$start" "$duration" 2
    paper_loftr_mirror_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr_mirror" \
      PORT="${PORT_NOLOFTR:-11742}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    paper_loftr_mirror_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr_mirror" \
      PORT="${PORT_LOFTR:-11743}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    ;;

  afrl_loftr_v31_pair)
    dataset="${1:-bus_outside}"
    start="${2:-45}"
    duration="${3:-45}"
    tag_base="${TAG_BASE:-paper_v31_afrl_${dataset}_s${start}_d${duration}}"
    afrl_bag="${RAW_BAG:-$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/${dataset}.bag}"
    afrl_gt="${GT_TXT:-$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/${dataset}.txt}"
    afrl_camchain="${CAMCHAIN:-$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_${dataset}.yaml}"
    paper_loftr_v31_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11841}" \
      ./scripts/run_afrl_cave_vins_eval.sh external klt "$start" "$duration" 2
    paper_loftr_v31_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11842}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    paper_loftr_v31_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11843}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    ;;

  afrl_loftr_v31_proposed)
    dataset="${1:-bus_outside}"
    start="${2:-45}"
    duration="${3:-45}"
    tag="${TAG:-paper_v31_afrl_${dataset}_s${start}_d${duration}_loftr}"
    afrl_bag="${RAW_BAG:-$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/${dataset}.bag}"
    afrl_gt="${GT_TXT:-$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/${dataset}.txt}"
    afrl_camchain="${CAMCHAIN:-$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_${dataset}.yaml}"
    paper_loftr_v31_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11843}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    ;;

  afrl_loftr_mirror_proposed)
    dataset="${1:-cemetery}"
    start="${2:-0}"
    duration="${3:-20}"
    tag="${TAG:-paper_mirror_afrl_${dataset}_s${start}_d${duration}_loftr}"
    afrl_bag="${RAW_BAG:-$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/${dataset}.bag}"
    afrl_gt="${GT_TXT:-$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/${dataset}.txt}"
    afrl_camchain="${CAMCHAIN:-$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_${dataset}.yaml}"
    paper_loftr_mirror_env \
      RAW_BAG="$afrl_bag" \
      GT_TXT="$afrl_gt" \
      CAMCHAIN="$afrl_camchain" \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11743}" \
      ./scripts/run_afrl_cave_vins_eval.sh external hybrid_superpoint_lightglue "$start" "$duration" 2
    ;;

  h07_loftr_v31_noharm_pair)
    start="${1:-1660}"
    end="${2:-1950}"
    tag_base="${TAG_BASE:-paper_v31_h07_${start}_${end}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11671}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" klt 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11672}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  h07_loftr_mirror_pair)
    start="${1:-1660}"
    end="${2:-1950}"
    tag_base="${TAG_BASE:-paper_mirror_h07_${start}_${end}}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11721}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" klt 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_noloftr_mirror" \
      PORT="${PORT_NOLOFTR:-11722}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="${tag_base}_loftr_mirror" \
      PORT="${PORT_LOFTR:-11723}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  h07_loftr_mirror_proposed)
    start="${1:-1660}"
    end="${2:-1950}"
    tag="${TAG:-paper_mirror_h07_${start}_${end}_loftr}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11723}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  h07_loftr_mirror_klt)
    # Single-arm classical control corresponding to the H07 v33 proposed arm.
    start="${1:-1660}"
    end="${2:-1950}"
    tag="${TAG:-paper_mirror_h07_${start}_${end}_klt}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11725}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" klt 2
    ;;

  aqualoc_harbor_loftr_v31_pair)
    seq="${1:-4}"
    start="${2:-2000}"
    end="${3:-2360}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag_base="${TAG_BASE:-paper_v31_h${seq_pad}_${start}_${end}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      HARBOR_SEQ="$seq" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11691}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" klt 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-1}" \
      HARBOR_SEQ="$seq" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11692}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      HARBOR_SEQ="$seq" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11693}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_harbor_loftr_v31_proposed)
    seq="${1:-4}"
    start="${2:-2000}"
    end="${3:-2360}"
    seq_pad="$(printf "%02d" "$((10#$seq))")"
    tag="${TAG:-paper_v31_h${seq_pad}_${start}_${end}_loftr}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-1}" \
      HARBOR_SEQ="$seq" \
      TAG="$tag" \
      PORT="${PORT:-11693}" \
      ./scripts/run_aqualoc_real_vins_eval.sh external "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  aqualoc_a06_loftr_proposed)
    start="${1:-2210}"
    end="${2:-2460}"
    tag="${TAG:-paperprop_a06_${start}_${end}_hybrid_loftr}"
    paper_loftr_env \
      RUN_VINS="${RUN_VINS:-1}" \
      TAG="$tag" \
      PORT="${PORT:-11653}" \
      ./scripts/run_aqualoc_archaeo_vins_eval.sh external 6 "$start" "$end" hybrid_superpoint_lightglue 2
    ;;

  mimir_uw_loftr_v31_pair)
    # Cross-dataset positive search using the same frozen A06 contribution
    # profile: KLT, learned without LoFTR, and learned with LoFTR.  The three
    # arms share one exact-timestamp raw bag so only frontend outputs differ.
    environment="${1:-SandPipe}"
    track="${2:-track0_dark}"
    start="${3:-0}"
    duration="${4:-45}"
    safe_environment="${environment,,}"
    safe_environment="${safe_environment//[^a-z0-9]/_}"
    safe_track="${track,,}"
    safe_track="${safe_track//[^a-z0-9]/_}"
    safe_start="${start//./p}"
    safe_duration="${duration//./p}"
    tag_base="${TAG_BASE:-mimir_positive_v31_${safe_environment}_${safe_track}_s${safe_start}_d${safe_duration}}"
    shared_raw="${RAW_BAG:-$ROOT/logs/mimir_uw_vins/${tag_base}_shared/mimir_raw.bag}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-0}" \
      RAW_BAG="$shared_raw" \
      TAG="${tag_base}_klt" \
      PORT="${PORT_KLT:-11861}" \
      bash ./scripts/run_mimir_uw_vins_eval.sh klt "$environment" "$track" "$start" "$duration" 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-0}" \
      RAW_BAG="$shared_raw" \
      TAG="${tag_base}_noloftr" \
      PORT="${PORT_NOLOFTR:-11862}" \
      bash ./scripts/run_mimir_uw_vins_eval.sh hybrid_superpoint_lightglue "$environment" "$track" "$start" "$duration" 2
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=loftr \
      RUN_VINS="${RUN_VINS:-0}" \
      RAW_BAG="$shared_raw" \
      TAG="${tag_base}_loftr" \
      PORT="${PORT_LOFTR:-11863}" \
      bash ./scripts/run_mimir_uw_vins_eval.sh hybrid_superpoint_lightglue "$environment" "$track" "$start" "$duration" 2
    ;;

  mimir_uw_klt_v31)
    # KLT-only arm of the frozen A06-v31 contribution profile for MIMIR-UW.
    # This is intentionally separate from the three-arm learned search so a
    # large baseline sweep does not spend GPU time on unused learned arms.
    environment="${1:-SeaFloor}"
    track="${2:-track0}"
    start="${3:-0}"
    duration="${4:-45}"
    safe_environment="${environment,,}"
    safe_environment="${safe_environment//[^a-z0-9]/_}"
    safe_track="${track,,}"
    safe_track="${safe_track//[^a-z0-9]/_}"
    safe_start="${start//./p}"
    safe_duration="${duration//./p}"
    tag="${TAG:-mimir_klt_v31_${safe_environment}_${safe_track}_s${safe_start}_d${safe_duration}}"
    paper_loftr_v31_env \
      SEMIDENSE_FALLBACK_METHOD=none \
      RUN_VINS="${RUN_VINS:-0}" \
      TAG="$tag" \
      PORT="${PORT:-11871}" \
      bash ./scripts/run_mimir_uw_vins_eval.sh klt "$environment" "$track" "$start" "$duration" "${MIMIR_EVERY_N:-1}"
    ;;

  mimir_uw_loftr_mirror_proposed)
    # Final AQUA-FE proposed_safe arm for MIMIR-UW: full KLT mirror backbone
    # plus strictly gated SP-LightGlue/LoFTR sidecars.
    environment="${1:-SeaFloor}"
    track="${2:-track0}"
    start="${3:-0}"
    duration="${4:-45}"
    safe_environment="${environment,,}"
    safe_environment="${safe_environment//[^a-z0-9]/_}"
    safe_track="${track,,}"
    safe_track="${safe_track//[^a-z0-9]/_}"
    safe_start="${start//./p}"
    safe_duration="${duration//./p}"
    tag="${TAG:-mimir_proposed_safe_${safe_environment}_${safe_track}_s${safe_start}_d${safe_duration}}"
    paper_loftr_mirror_env \
      SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-loftr}" \
      INIT_PARALLAX_ADAPTIVE_SKIP="${INIT_PARALLAX_ADAPTIVE_SKIP:-1}" \
      RUN_VINS="${RUN_VINS:-0}" \
      TAG="$tag" \
      PORT="${PORT:-11872}" \
      bash ./scripts/run_mimir_uw_vins_eval.sh \
        "${MIMIR_OURS_METHOD:-hybrid_superpoint_lightglue}" "$environment" "$track" "$start" "$duration" "${MIMIR_EVERY_N:-1}"
    ;;

  *)
    echo "unknown task: $TASK" >&2
    exit 2
    ;;
esac
