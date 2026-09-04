#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
cd "$ROOT"

EVERY_N="${EVERY_N:-2}"
RUN_VINS="${RUN_VINS:-0}"
FORCE_EXPORT="${FORCE_EXPORT:-1}"
FORCE_RAW="${FORCE_RAW:-1}"
PREPARE_BAG="${PREPARE_BAG:-1}"
TAG_PREFIX="${TAG_PREFIX:-may29_xfeat_adaptive_support_v11}"
RUN_WINDOWS="${RUN_WINDOWS:-fr25_45 fr70_100 fr80_110}"
RUN_VARIANTS="${RUN_VARIANTS:-xfeat}"

# Low-texture support contribution profile:
# - keep the KLT mirror backbone and source-channel audit;
# - allow a larger XFeat sidecar only when the KLT backbone is degraded and
#   there is enough visual motion/parallax for VINS to benefit from new support;
# - leave LoFTR disabled here so this script isolates the XFeat sidecar effect.
# This is intentionally not the paper-safe default profile. It is the
# low-texture contribution profile used to show when learned support helps.
COMMON_ENV=(
  OMP_NUM_THREADS=2
  MKL_NUM_THREADS=2
  OPENBLAS_NUM_THREADS=2
  RUN_VINS="$RUN_VINS"
  FORCE_EXPORT="$FORCE_EXPORT"
  FORCE_RAW="$FORCE_RAW"
  PREPARE_BAG="$PREPARE_BAG"
  RAW_BAG="$ROOT/datasets/full_downloads/afrl_hf/ros1_bags/cemetery.bag"
  GT_TXT="$ROOT/datasets/full_downloads/afrl_hf/colmap_groundtruth/cemetery.txt"
  CAMCHAIN="$ROOT/datasets/full_downloads/afrl_hf/camera_imu_parameters/camchain_cemetery.yaml"
  CAMERA_KEY=cam1
  SRC_IMAGE_TOPIC=/cam_fr/image_raw/compressed
  IMAGE_SCALE=0.5
  FRONTEND_CONFIG="$ROOT/uw_frontend/configs/experiments/low_texture_active_xfeat_sidecar.yaml"
  SEMIDENSE_FALLBACK_METHOD=none
  PREPROCESS=adaptive_clahe
  BACKEND_QUALITY_FLOOR=none
  # XFeat sidecars are useful support observations in low-texture windows, but
  # they should enter VINS as soft constraints rather than KLT-equivalent points.
  BACKEND_XFEAT_QUALITY_CONST="${BACKEND_XFEAT_QUALITY_CONST:-0.30}"
  BACKEND_XFEAT_RISK_QUALITY_SCHEDULER="${BACKEND_XFEAT_RISK_QUALITY_SCHEDULER:-1}"
  BACKEND_XFEAT_RISK_QUALITY_CONST="${BACKEND_XFEAT_RISK_QUALITY_CONST:-0.20}"
  BACKEND_XFEAT_RISK_PROBATION_QUALITY_CONST="${BACKEND_XFEAT_RISK_PROBATION_QUALITY_CONST:-0.80}"
  BACKEND_XFEAT_RISK_PROBATION_QUALITY_REQUIRES_LOW_PARALLAX="${BACKEND_XFEAT_RISK_PROBATION_QUALITY_REQUIRES_LOW_PARALLAX:-1}"
  BACKEND_XFEAT_RISK_PROBATION_LEARNED_FRAMES="${BACKEND_XFEAT_RISK_PROBATION_LEARNED_FRAMES:-44}"
  BACKEND_XFEAT_RISK_LATCH_GFTT_TOTAL="${BACKEND_XFEAT_RISK_LATCH_GFTT_TOTAL:-30}"
  FORMAL_THREE_LAYER_EXPORT=1
  FORMAL_EXPORT_ADAPTIVE_MIRROR_FALLBACK=1
  # Contribution profile: keep the degraded/sparse sidecar frames visible so
  # the learned support mechanism can be measured.  The proposed_safe profile
  # keeps the default full-mirror post-sidecar refill for no-harm validation.
  FORMAL_EXPORT_DISABLE_POST_SIDECAR_MIRROR_REFILL=1
  FORMAL_EXPORT_MOTION_ADAPTIVE_POST_SIDECAR_REFILL="${FORMAL_EXPORT_MOTION_ADAPTIVE_POST_SIDECAR_REFILL:-1}"
  FORMAL_EXPORT_MOTION_ADAPTIVE_REFILL_MAX_MOTION_PX="${FORMAL_EXPORT_MOTION_ADAPTIVE_REFILL_MAX_MOTION_PX:-9.0}"
  FORMAL_EXPORT_MOTION_ADAPTIVE_REFILL_HOLD_FRAMES="${FORMAL_EXPORT_MOTION_ADAPTIVE_REFILL_HOLD_FRAMES:-8}"
  FORMAL_EXPORT_ALLOW_SPARSE_BACKBONE=1
  FORMAL_EXPORT_LOW_TEXTURE_ACTIVE_SIDECAR=1
  EXPORT_CLASSICAL_MIRROR_BACKBONE=1
  PRESERVE_SIDECARS_THROUGH_SELECTION=1
  EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-180}"
  MEASUREMENT_SELECTION_MAX_FEATURES="${MEASUREMENT_SELECTION_MAX_FEATURES:-180}"
  VINS_SAFE_MAX_TOTAL="${VINS_SAFE_MAX_TOTAL:-180}"
  VINS_SAFE_WARMUP_FRAMES=20
  VINS_SAFE_MAX_LEARNED=18
  VINS_SAFE_MIN_LEARNED_AGE=1
  VINS_SAFE_PRESERVE_CLASSICAL_BUDGET="${VINS_SAFE_PRESERVE_CLASSICAL_BUDGET:-1}"
  VINS_INIT_KLT_ONLY_FRAMES="${VINS_INIT_KLT_ONLY_FRAMES:-20}"
  LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES="${LOW_PARALLAX_LEARNED_HOLDOFF_FRAMES:-0}"
  LEARNED_EXPORT_BENEFIT_ALL_SOURCES=1
  LEARNED_EXPORT_MIN_CLASSICAL_TRACKS=300
  LEARNED_EXPORT_MIN_CLASSICAL_GRID=0.78
  LEARNED_EXPORT_MIN_AGE=1
  LEARNED_EXPORT_MIN_QUALITY="${LEARNED_EXPORT_MIN_QUALITY:-0.05}"
  LEARNED_EXPORT_MIN_NCC="${LEARNED_EXPORT_MIN_NCC:-0.35}"
  LEARNED_EXPORT_MAX_FB="${LEARNED_EXPORT_MAX_FB:-1.50}"
  LEARNED_EXPORT_NON_LOFTR_REQUIRES_DEGRADED_MODE="${LEARNED_EXPORT_NON_LOFTR_REQUIRES_DEGRADED_MODE:-0}"
  LEARNED_EXPORT_MIN_GRID_GAIN="${LEARNED_EXPORT_MIN_GRID_GAIN:-0.0}"
  LEARNED_EXPORT_MIN_NEW_CELLS="${LEARNED_EXPORT_MIN_NEW_CELLS:-1}"
  LEARNED_EXPORT_MIN_NEW_CELL_RATIO="${LEARNED_EXPORT_MIN_NEW_CELL_RATIO:-0.05}"
  LEARNED_EXPORT_MAX_PER_NEW_CELL="${LEARNED_EXPORT_MAX_PER_NEW_CELL:-2}"
  LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_MIN_CLASSICAL_MOTION_PX:-0.0}"
  LEARNED_EXPORT_COVERAGE_GAIN_MAX_CLASSICAL_TRACKS=0
  LEARNED_EXPORT_WEAK_CELL_RESCUE="${LEARNED_EXPORT_WEAK_CELL_RESCUE:-1}"
  LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE="${LEARNED_EXPORT_NON_LOFTR_WEAK_CELL_RESCUE:-1}"
  LEARNED_EXPORT_WEAK_CELL_MAX_COUNT="${LEARNED_EXPORT_WEAK_CELL_MAX_COUNT:-10}"
  LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES="${LEARNED_EXPORT_WEAK_CELL_MIN_CANDIDATES:-2}"
  LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY="${LEARNED_EXPORT_WEAK_CELL_MAX_OCCUPANCY:-12}"
  LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_WEAK_CELL_MIN_CLASSICAL_MOTION_PX:-0.0}"
  LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_GRID=0.82
  LEARNED_EXPORT_WEAK_CELL_MAX_CLASSICAL_TRACKS=0
  LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE="${LEARNED_EXPORT_COVERAGE_SEEDED_CONTINUATION_GATE:-1}"
  LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_AGE:-26}"
  LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX="${LEARNED_EXPORT_CONTINUATION_MAX_CLASSICAL_MOTION_PX:-10.5}"
  LEARNED_EXPORT_VISIBLE_TRACK_GATE=1
  LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES="${LEARNED_EXPORT_VISIBLE_TRACK_MIN_FRAMES:-1}"
  LEARNED_EXPORT_VISIBLE_TRACK_MAX_GAP=2
  LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES="${LEARNED_EXPORT_FRESH_CONFIRMATION_HOLD_FRAMES:-4}"
  # FR85-like failures come from a short low-grid seed that immediately turns
  # into a healthy-looking XFeat burst. Veto only that risky transition; keep
  # longer low-grid support bursts such as FR80/FR90 and pure healthy support
  # bursts such as FR110 available for contribution tests.
  LEARNED_EXPORT_SHORT_LOWGRID_SEED_SUPPRESSION="${LEARNED_EXPORT_SHORT_LOWGRID_SEED_SUPPRESSION:-1}"
  LEARNED_EXPORT_SHORT_LOWGRID_SEED_MIN_FRAMES="${LEARNED_EXPORT_SHORT_LOWGRID_SEED_MIN_FRAMES:-3}"
  LEARNED_EXPORT_SHORT_LOWGRID_SEED_MAX_GAP="${LEARNED_EXPORT_SHORT_LOWGRID_SEED_MAX_GAP:-2}"
  LEARNED_EXPORT_SHORT_LOWGRID_SEED_MAX_LOWGRID_FRAMES="${LEARNED_EXPORT_SHORT_LOWGRID_SEED_MAX_LOWGRID_FRAMES:-10}"
  LEARNED_EXPORT_SHORT_LOWGRID_LONG_TAIL_CONSUMES_BUDGET="${LEARNED_EXPORT_SHORT_LOWGRID_LONG_TAIL_CONSUMES_BUDGET:-1}"
  # Bound each low-grid learned support burst to its seed-confirmed phase.
  # Early low-grid bursts are allowed immediately but capped at 8 seed frames;
  # later bursts wait until 5 frames and cap at 10.  This preserves the
  # useful refill pulse while suppressing FR85/FR90-style long-tail churn.
  LEARNED_EXPORT_LOWGRID_SEED_WINDOW_GATE="${LEARNED_EXPORT_LOWGRID_SEED_WINDOW_GATE:-1}"
  LEARNED_EXPORT_LOWGRID_SEED_EARLY_MAX_START_FRAME="${LEARNED_EXPORT_LOWGRID_SEED_EARLY_MAX_START_FRAME:-40}"
  LEARNED_EXPORT_LOWGRID_SEED_EARLY_MIN_FRAME="${LEARNED_EXPORT_LOWGRID_SEED_EARLY_MIN_FRAME:-1}"
  LEARNED_EXPORT_LOWGRID_SEED_EARLY_MAX_FRAME="${LEARNED_EXPORT_LOWGRID_SEED_EARLY_MAX_FRAME:-8}"
  LEARNED_EXPORT_LOWGRID_SEED_LATE_MIN_FRAME="${LEARNED_EXPORT_LOWGRID_SEED_LATE_MIN_FRAME:-5}"
  LEARNED_EXPORT_LOWGRID_SEED_LATE_MAX_FRAME="${LEARNED_EXPORT_LOWGRID_SEED_LATE_MAX_FRAME:-10}"
  # Held-out seed candidates also consume the sidecar dose budget, preventing
  # the learned support dose from drifting into later healthy frames.
  LEARNED_EXPORT_LOWGRID_SEED_WINDOW_CONSUMES_BUDGET="${LEARNED_EXPORT_LOWGRID_SEED_WINDOW_CONSUMES_BUDGET:-1}"
  # When KLT already has a mature, reasonably covered track set, XFeat support
  # is kept as a frontend candidate but not injected into VINS.  This repairs
  # FR85-like cases where confirmed XFeat sidecars are geometrically valid yet
  # slightly perturb the estimator, while preserving low-texture positives.
  LEARNED_EXPORT_STALE_HEALTHY_UNCONFIRMED_SUPPRESSION="${LEARNED_EXPORT_STALE_HEALTHY_UNCONFIRMED_SUPPRESSION:-1}"
  LEARNED_EXPORT_STALE_HEALTHY_WINDOW="${LEARNED_EXPORT_STALE_HEALTHY_WINDOW:-12}"
  LEARNED_EXPORT_STALE_HEALTHY_MIN_FRAMES="${LEARNED_EXPORT_STALE_HEALTHY_MIN_FRAMES:-1}"
  LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_TRACKS:-0}"
  LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_GRID:-0.58}"
  LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_AGE="${LEARNED_EXPORT_STALE_HEALTHY_MIN_CLASSICAL_AGE:-20.0}"
  LEARNED_EXPORT_STALE_HEALTHY_MAX_USED_OBSERVATIONS="${LEARNED_EXPORT_STALE_HEALTHY_MAX_USED_OBSERVATIONS:-0}"
  # Keep learned support as a small sidecar dose.  On FR90-like windows,
  # excessive XFeat observations after the first support burst can perturb VINS;
  # an 80-observation budget kept the positive early support while avoiding the
  # late-burst regression.
  LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_SIDECAR_MAX_OBSERVATIONS:-40}"
  LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS="${LEARNED_EXPORT_LOW_PARALLAX_SIDECAR_MAX_OBSERVATIONS:-40}"
)

run_window_xfeat() {
  local start="$1"
  local duration="$2"
  local label="$3"
  env "${COMMON_ENV[@]}" \
    TAG="${TAG_PREFIX}_${label}_export" \
    bash scripts/run_afrl_cave_vins_eval.sh external hybrid_xfeat "$start" "$duration" "$EVERY_N"
}

run_window_klt() {
  local start="$1"
  local duration="$2"
  local label="$3"
  env "${COMMON_ENV[@]}" \
    TAG="${TAG_PREFIX}_${label}_protected_klt" \
    bash scripts/run_afrl_cave_vins_eval.sh external klt "$start" "$duration" "$EVERY_N"
}

add_run_paths() {
  local label="$1"
  case "$RUN_VARIANTS" in
    xfeat)
      RUNS+=("logs/afrl_cave_v31/external_hybrid_xfeat_every${EVERY_N}_${TAG_PREFIX}_${label}_export")
      ;;
    klt)
      RUNS+=("logs/afrl_cave_v31/external_klt_every${EVERY_N}_${TAG_PREFIX}_${label}_protected_klt")
      ;;
    pair|paired|both)
      RUNS+=("logs/afrl_cave_v31/external_klt_every${EVERY_N}_${TAG_PREFIX}_${label}_protected_klt")
      RUNS+=("logs/afrl_cave_v31/external_hybrid_xfeat_every${EVERY_N}_${TAG_PREFIX}_${label}_export")
      ;;
    *)
      echo "unknown RUN_VARIANTS: $RUN_VARIANTS (use xfeat, klt, or pair)" >&2
      exit 2
      ;;
  esac
}

run_window() {
  local start="$1"
  local duration="$2"
  local label="$3"
  case "$RUN_VARIANTS" in
    xfeat)
      run_window_xfeat "$start" "$duration" "$label"
      ;;
    klt)
      run_window_klt "$start" "$duration" "$label"
      ;;
    pair|paired|both)
      run_window_klt "$start" "$duration" "$label"
      run_window_xfeat "$start" "$duration" "$label"
      ;;
    *)
      echo "unknown RUN_VARIANTS: $RUN_VARIANTS (use xfeat, klt, or pair)" >&2
      exit 2
      ;;
  esac
  add_run_paths "$label"
}

RUNS=()
for window in $RUN_WINDOWS; do
  case "$window" in
    fr25_45)
      run_window 25 20 fr25_45
      ;;
    fr70_100)
      run_window 70 30 fr70_100
      ;;
    fr80_110)
      run_window 80 30 fr80_110
      ;;
    fr50_80)
      run_window 50 30 fr50_80
      ;;
    fr60_90)
      run_window 60 30 fr60_90
      ;;
    fr90_120)
      run_window 90 30 fr90_120
      ;;
    fr100_130)
      run_window 100 30 fr100_130
      ;;
    fr110_140)
      run_window 110 30 fr110_140
      ;;
    *)
      if [[ "$window" =~ ^fr([0-9]+)_([0-9]+)$ ]]; then
        start="${BASH_REMATCH[1]}"
        end="${BASH_REMATCH[2]}"
        if (( end <= start )); then
          echo "invalid RUN_WINDOWS entry: $window" >&2
          exit 2
        fi
        run_window "$start" "$((end - start))" "$window"
      else
        echo "unknown RUN_WINDOWS entry: $window" >&2
        exit 2
      fi
      ;;
  esac
done

python3 scripts/summarize_run_evidence.py \
  --runs "${RUNS[@]}" \
  --output-csv "logs/${TAG_PREFIX}_export_summary.csv"
