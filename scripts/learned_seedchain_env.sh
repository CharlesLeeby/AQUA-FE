#!/usr/bin/env bash
# Shared XFeat seed-chain profile for low-texture cross-dataset probes.
#
# Source this file before a dataset runner. It preserves caller overrides while
# filling in the CIRS-validated defaults:
#   XFeat seed -> LK/KLT confirmation -> KLT state append -> source provenance
#   -> online seed microburst/dense-start export gate.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "source this file from a runner, for example:" >&2
  echo "  source scripts/learned_seedchain_env.sh" >&2
  exit 2
fi

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
AQUAFE_SEEDCHAIN_PROFILE="${AQUAFE_SEEDCHAIN_PROFILE:-lineage_early_seed_noharm_v4}"

case "$AQUAFE_SEEDCHAIN_PROFILE" in
  lineage_safe_dense_start|generic_dense_start|lineage_relaxed_scan|lineage_init_safe_scan|lineage_early_seed_scan|lineage_early_seed_lineage_scan|lineage_early_seed_noharm_v4|lineage_early_seed_persistence_replace_v1|lineage_early_seed_singlechain_v2|lineage_early_seed_churn_guard_v3|lineage_early_seed_geometry_router_v1|lineage_early_seed_coverage_monotone_v2|lineage_delayed_newborn_slot_v3)
    export FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml}"
    ;;
  cirs_dense_start)
    export FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/low_texture_lineage_safe_dense_start_frontend.yaml}"
    ;;
  *)
    echo "unknown AQUAFE_SEEDCHAIN_PROFILE=$AQUAFE_SEEDCHAIN_PROFILE" >&2
    return 2
    ;;
esac

case "$AQUAFE_SEEDCHAIN_PROFILE" in
  lineage_safe_dense_start|generic_dense_start|lineage_relaxed_scan|lineage_init_safe_scan|lineage_early_seed_scan|lineage_early_seed_lineage_scan|lineage_early_seed_noharm_v4|lineage_early_seed_persistence_replace_v1|lineage_early_seed_singlechain_v2|lineage_early_seed_churn_guard_v3|lineage_early_seed_geometry_router_v1|lineage_early_seed_coverage_monotone_v2|lineage_delayed_newborn_slot_v3|cirs_dense_start)
    seedchain_warmup_default=8
    seedchain_max_per_frame_default=0
    seedchain_microburst_min_initial_default=20
    seedchain_dense_tracks_default=218
    seedchain_dense_grid_default=0.98
    seedchain_dense_candidates_default=8
    seedchain_sparse_start_candidates_default=0
    seedchain_sparse_start_tracks_default=0
    seedchain_sparse_start_grid_default=0.0
    seedchain_start_min_grid_default=0.0
    seedchain_start_min_grid_tracks_default=0
    seedchain_start_gftt_ratio_default=0.0
    seedchain_start_gftt_ratio_tracks_default=0
    seedchain_start_gftt_ratio_grid_default=0.0
    seedchain_normal_start_motion_default=0.0
    seedchain_normal_start_candidates_default=0
    seedchain_normal_start_max_candidates_default=0
    seedchain_normal_start_tracks_default=0
    seedchain_normal_start_grid_default=0.0
    seedchain_gftt_ratio_default=0.0
    seedchain_gftt_ratio_tracks_default=0
    seedchain_gftt_ratio_grid_default=0.0
    seedchain_refill_rejected_default=0
    seedchain_mirror_only_after_reject_default=0
    seedchain_microburst_restarts_default=0
    seedchain_lineage_continuation_default=0
    seedchain_lineage_min_age_default=8
    seedchain_lineage_max_per_frame_default=2
    seedchain_lineage_max_observations_default=20
    seedchain_export_classical_mirror_default=0
    seedchain_preserve_classical_budget_default=0
    seedchain_persistence_replacement_default=0
    seedchain_persistence_single_chain_default=0
    seedchain_persistence_min_gftt_ratio_default=0.0
    seedchain_persistence_source_router_default=0
    seedchain_persistence_allow_all_non_loftr_default=0
    seedchain_persistence_same_grid_cell_default=0
    seedchain_persistence_coverage_monotone_default=0
    seedchain_persistence_max_per_frame_default=0
    seedchain_persistence_max_selected_frame_default=4
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_relaxed_scan" ]]; then
      # Screening-only profile for windows where confirmed XFeat exists but the
      # CIRS dense-start signature is too strict. Keep confirmation and quality
      # gates; only relax the microburst extension so candidate windows are not
      # prematurely classified as zero-learned.
      seedchain_microburst_min_initial_default=6
      seedchain_dense_tracks_default=0
      seedchain_dense_grid_default=1.0
      seedchain_dense_candidates_default=0
      seedchain_microburst_restarts_default=3
      seedchain_lineage_continuation_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_init_safe_scan" ]]; then
      # Same relaxed search behavior, but delay learned observations until
      # after the fragile VINS initialization phase.
      seedchain_warmup_default=20
      seedchain_max_per_frame_default=4
      seedchain_microburst_min_initial_default=6
      seedchain_dense_tracks_default=0
      seedchain_dense_grid_default=1.0
      seedchain_dense_candidates_default=0
      seedchain_microburst_restarts_default=3
      seedchain_lineage_continuation_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_scan" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_noharm_v4" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_persistence_replace_v1" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_singlechain_v2" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_churn_guard_v3" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_geometry_router_v1" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_coverage_monotone_v2" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_delayed_newborn_slot_v3" ]]; then
      # Cross-dataset positive-search profile for windows where a small,
      # confirmed early XFeat burst helps VINS initialization. Keep the strict
      # dense-start/microburst contract, but do not suppress frames 0-7.
      seedchain_warmup_default=0
      seedchain_sparse_start_candidates_default=3
      seedchain_sparse_start_tracks_default=300
      seedchain_sparse_start_grid_default=0.75
      seedchain_start_min_grid_default=0.75
      seedchain_start_min_grid_tracks_default=300
      seedchain_start_gftt_ratio_default=0.23
      seedchain_start_gftt_ratio_tracks_default=300
      seedchain_start_gftt_ratio_grid_default=0.75
      seedchain_normal_start_motion_default=5.0
      seedchain_normal_start_candidates_default=5
      seedchain_normal_start_max_candidates_default=8
      seedchain_normal_start_tracks_default=300
      seedchain_normal_start_grid_default=0.75
      seedchain_gftt_ratio_default=0.65
      seedchain_gftt_ratio_tracks_default=300
      seedchain_gftt_ratio_grid_default=0.90
      seedchain_refill_rejected_default=1
      seedchain_mirror_only_after_reject_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_noharm_v4" ]]; then
      # Structural no-harm repair: retain the independent KLT mirror first and
      # admit learned sidecars only into vacant capacity below the frozen cap.
      seedchain_export_classical_mirror_default=1
      seedchain_preserve_classical_budget_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_persistence_replace_v1" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_singlechain_v2" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_churn_guard_v3" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_geometry_router_v1" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_coverage_monotone_v2" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_delayed_newborn_slot_v3" ]]; then
      # Experimental contribution line. Keep the independent KLT mirror, but
      # allow only preregistered early confirmed-XFeat -> same-frame-GFTT
      # birth swaps with a strict raw-age advantage. This is not no-harm v4.
      seedchain_export_classical_mirror_default=1
      seedchain_preserve_classical_budget_default=0
      seedchain_persistence_replacement_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_singlechain_v2" ]]; then
      # Bound the contribution to one identity-stable XFeat seed chain. Once
      # committed, the startup arbitration cannot switch to another sidecar.
      seedchain_persistence_single_chain_default=1
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_churn_guard_v3" ]]; then
      # Arm the v1 birth-for-birth path only when the first eligible frame has
      # a substantial classical-newborn reserve; otherwise fail closed to KLT.
      seedchain_persistence_min_gftt_ratio_default=0.10
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_geometry_router_v1" ]]; then
      # Development-only structural router. Preserve the independent mirror;
      # admit confirmed non-LoFTR learned lineages only by an early, same-cell
      # age-advantaged GFTT-birth swap, capped at six changes per frame.
      seedchain_persistence_min_gftt_ratio_default=0.10
      seedchain_persistence_source_router_default=1
      seedchain_persistence_allow_all_non_loftr_default=1
      seedchain_persistence_same_grid_cell_default=1
      seedchain_persistence_max_per_frame_default=6
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_coverage_monotone_v2" || "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_delayed_newborn_slot_v3" ]]; then
      # Development-only v2: retain early/age-1/source/cap protection, but
      # replace the global churn ratio and exact-cell victim rule with a
      # per-exchange occupied-grid monotonicity invariant.
      seedchain_persistence_min_gftt_ratio_default=0.0
      seedchain_persistence_source_router_default=1
      seedchain_persistence_allow_all_non_loftr_default=1
      seedchain_persistence_same_grid_cell_default=0
      seedchain_persistence_coverage_monotone_default=1
      seedchain_persistence_max_per_frame_default=6
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_delayed_newborn_slot_v3" ]]; then
      # The only v3 mechanism change is timing: keep the v2 gate/router
      # unchanged, but protect selected feature frames 0--31 and move the
      # five-frame newborn-exchange interval from 0--4 to 32--36.
      seedchain_warmup_default=32
      seedchain_persistence_max_selected_frame_default=36
    fi
    if [[ "$AQUAFE_SEEDCHAIN_PROFILE" == "lineage_early_seed_lineage_scan" ]]; then
      # Experimental variant of lineage_early_seed_scan: keep the same compact
      # early XFeat seed, then allow a tiny budget of mature KLT-confirmed
      # XFeat-provenance tracks to continue. This probes whether the current
      # positives are limited by too few learned-seeded observations without
      # returning to pairwise/late learned injection.
      seedchain_warmup_default=0
      seedchain_lineage_continuation_default=1
      seedchain_lineage_min_age_default=5
      seedchain_lineage_max_per_frame_default=2
      seedchain_lineage_max_observations_default=12
    fi

    export SEMIDENSE_FALLBACK_METHOD="${SEMIDENSE_FALLBACK_METHOD:-none}"
    export MEASUREMENT_SELECTION="${MEASUREMENT_SELECTION:-0}"
    export FORMAL_THREE_LAYER_EXPORT="${FORMAL_THREE_LAYER_EXPORT:-0}"
    export VINS_SAFE_SOURCE_SELECTION="${VINS_SAFE_SOURCE_SELECTION:-0}"
    export EXPORT_MAX_FEATURES="${EXPORT_MAX_FEATURES:-350}"
    export LEARNED_EXPORT_BENEFIT_GATE="${LEARNED_EXPORT_BENEFIT_GATE:-0}"
    export EXPORT_CLASSICAL_MIRROR_BACKBONE="${EXPORT_CLASSICAL_MIRROR_BACKBONE:-$seedchain_export_classical_mirror_default}"
    export FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET="${FINAL_MIRROR_PRESERVE_CLASSICAL_BUDGET:-$seedchain_preserve_classical_budget_default}"
    export FINAL_MIRROR_PERSISTENCE_REPLACEMENT="${FINAL_MIRROR_PERSISTENCE_REPLACEMENT:-$seedchain_persistence_replacement_default}"
    export FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME="${FINAL_MIRROR_PERSISTENCE_MAX_SELECTED_FRAME:-$seedchain_persistence_max_selected_frame_default}"
    export FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE="${FINAL_MIRROR_PERSISTENCE_MIN_AGE_ADVANTAGE:-2}"
    export FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN="${FINAL_MIRROR_PERSISTENCE_SINGLE_CHAIN:-$seedchain_persistence_single_chain_default}"
    export FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO="${FINAL_MIRROR_PERSISTENCE_MIN_GFTT_RATIO:-$seedchain_persistence_min_gftt_ratio_default}"
    export FINAL_MIRROR_PERSISTENCE_SOURCE_ROUTER="${FINAL_MIRROR_PERSISTENCE_SOURCE_ROUTER:-$seedchain_persistence_source_router_default}"
    export FINAL_MIRROR_PERSISTENCE_ALLOW_ALL_NON_LOFTR="${FINAL_MIRROR_PERSISTENCE_ALLOW_ALL_NON_LOFTR:-$seedchain_persistence_allow_all_non_loftr_default}"
    export FINAL_MIRROR_PERSISTENCE_SAME_GRID_CELL="${FINAL_MIRROR_PERSISTENCE_SAME_GRID_CELL:-$seedchain_persistence_same_grid_cell_default}"
    export FINAL_MIRROR_PERSISTENCE_COVERAGE_MONOTONE="${FINAL_MIRROR_PERSISTENCE_COVERAGE_MONOTONE:-$seedchain_persistence_coverage_monotone_default}"
    export FINAL_MIRROR_PERSISTENCE_GRID_ROWS="${FINAL_MIRROR_PERSISTENCE_GRID_ROWS:-4}"
    export FINAL_MIRROR_PERSISTENCE_GRID_COLS="${FINAL_MIRROR_PERSISTENCE_GRID_COLS:-6}"
    export FINAL_MIRROR_PERSISTENCE_MAX_PER_FRAME="${FINAL_MIRROR_PERSISTENCE_MAX_PER_FRAME:-$seedchain_persistence_max_per_frame_default}"

    export LEARNED_EXPORT_ONLINE_SEED_GATE="${LEARNED_EXPORT_ONLINE_SEED_GATE:-1}"
    export LEARNED_EXPORT_ONLINE_SEED_SOURCES="${LEARNED_EXPORT_ONLINE_SEED_SOURCES:-xfeat}"
    export LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES:-$seedchain_warmup_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS:-50}"
    export LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME:-$seedchain_max_per_frame_default}"
    export LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME:-0}"
    export LEARNED_EXPORT_ONLINE_SEED_MIN_AGE="${LEARNED_EXPORT_ONLINE_SEED_MIN_AGE:-1}"
    export LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY="${LEARNED_EXPORT_ONLINE_SEED_MIN_QUALITY:-0.10}"
    export LEARNED_EXPORT_ONLINE_SEED_MIN_NCC="${LEARNED_EXPORT_ONLINE_SEED_MIN_NCC:-0.42}"
    export LEARNED_EXPORT_ONLINE_SEED_MAX_FB="${LEARNED_EXPORT_ONLINE_SEED_MAX_FB:-1.20}"
    export LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED="${LEARNED_EXPORT_ONLINE_SEED_REQUIRE_CONFIRMED:-1}"
    export LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH="${LEARNED_EXPORT_ONLINE_SEED_REQUIRE_FRESH:-0}"
    export LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE="${LEARNED_EXPORT_ONLINE_SEED_FRESH_SCOPE:-id}"
    export LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_FRESH_HOLD_FRAMES:-0}"

    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE:-1}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES:-3}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES:-12}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS:-$seedchain_microburst_min_initial_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_CELLS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_CELLS:-0}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_BBOX_AREA_RATIO="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_BBOX_AREA_RATIO:-0.0}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_ROWS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_ROWS:-6}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_COLS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_GRID_COLS:-6}"

    export LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS:-5}"
    export LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS:-$seedchain_dense_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID:-$seedchain_dense_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES="${LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES:-$seedchain_dense_candidates_default}"
    export LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_FRAME_CANDIDATES="${LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_FRAME_CANDIDATES:-$seedchain_sparse_start_candidates_default}"
    export LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_CLASSICAL_TRACKS:-$seedchain_sparse_start_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_SPARSE_START_MIN_CLASSICAL_GRID:-$seedchain_sparse_start_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_START_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_START_MIN_CLASSICAL_GRID:-$seedchain_start_min_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_START_MIN_CLASSICAL_GRID_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_START_MIN_CLASSICAL_GRID_TRACKS:-$seedchain_start_min_grid_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MAX_START_CLASSICAL_GFTT_RATIO="${LEARNED_EXPORT_ONLINE_SEED_MAX_START_CLASSICAL_GFTT_RATIO:-$seedchain_start_gftt_ratio_default}"
    export LEARNED_EXPORT_ONLINE_SEED_START_GFTT_RATIO_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_START_GFTT_RATIO_MIN_CLASSICAL_TRACKS:-$seedchain_start_gftt_ratio_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_START_GFTT_RATIO_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_START_GFTT_RATIO_MIN_CLASSICAL_GRID:-$seedchain_start_gftt_ratio_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MAX_MOTION_PX="${LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MAX_MOTION_PX:-$seedchain_normal_start_motion_default}"
    export LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_FRAME_CANDIDATES="${LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_FRAME_CANDIDATES:-$seedchain_normal_start_candidates_default}"
    export LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MAX_FRAME_CANDIDATES="${LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MAX_FRAME_CANDIDATES:-$seedchain_normal_start_max_candidates_default}"
    export LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_CLASSICAL_TRACKS:-$seedchain_normal_start_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_NORMAL_START_MIN_CLASSICAL_GRID:-$seedchain_normal_start_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MAX_CLASSICAL_GFTT_RATIO="${LEARNED_EXPORT_ONLINE_SEED_MAX_CLASSICAL_GFTT_RATIO:-$seedchain_gftt_ratio_default}"
    export LEARNED_EXPORT_ONLINE_SEED_GFTT_RATIO_MIN_CLASSICAL_TRACKS="${LEARNED_EXPORT_ONLINE_SEED_GFTT_RATIO_MIN_CLASSICAL_TRACKS:-$seedchain_gftt_ratio_tracks_default}"
    export LEARNED_EXPORT_ONLINE_SEED_GFTT_RATIO_MIN_CLASSICAL_GRID="${LEARNED_EXPORT_ONLINE_SEED_GFTT_RATIO_MIN_CLASSICAL_GRID:-$seedchain_gftt_ratio_grid_default}"
    export LEARNED_EXPORT_ONLINE_SEED_REFILL_REJECTED_WITH_MIRROR="${LEARNED_EXPORT_ONLINE_SEED_REFILL_REJECTED_WITH_MIRROR:-$seedchain_refill_rejected_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MIRROR_ONLY_AFTER_REJECT="${LEARNED_EXPORT_ONLINE_SEED_MIRROR_ONLY_AFTER_REJECT:-$seedchain_mirror_only_after_reject_default}"

    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_MAX_RESTARTS="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_MAX_RESTARTS:-$seedchain_microburst_restarts_default}"
    export LEARNED_EXPORT_ONLINE_SEED_MICROBURST_RESTART_COOLDOWN_FRAMES="${LEARNED_EXPORT_ONLINE_SEED_MICROBURST_RESTART_COOLDOWN_FRAMES:-8}"
    export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_CONTINUATION:-$seedchain_lineage_continuation_default}"
    export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MIN_AGE="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MIN_AGE:-$seedchain_lineage_min_age_default}"
    export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_PER_FRAME="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_PER_FRAME:-$seedchain_lineage_max_per_frame_default}"
    export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_OBSERVATIONS="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_MAX_OBSERVATIONS:-$seedchain_lineage_max_observations_default}"
    export LEARNED_EXPORT_ONLINE_SEED_LINEAGE_SEPARATE_BUDGET="${LEARNED_EXPORT_ONLINE_SEED_LINEAGE_SEPARATE_BUDGET:-0}"
    ;;
esac
