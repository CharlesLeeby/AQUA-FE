#!/usr/bin/env bash
set -euo pipefail

# CIRS XFeat profile arbitration prototype.
#
# The goal is to keep one reproducible entry point for the XFeat-positive
# regimes discovered so far, with a conservative KLT fallback:
#   1. oldcontract_microburst: full KLT/GFTT backbone, warmup=8, no mirror.
#   2. mirror_densecap: mirror KLT backbone plus dense-start cap=5.
#   3. klt_safe_fallback: no learned injection when the probe lacks an early
#      learned-contribution signature.
#
# The wrapper first exports an oldcontract+densecap probe for the full window.
# If the first eligible XFeat burst hits the dense-start signature, it re-runs
# export with mirror_densecap.  Otherwise it keeps oldcontract_microburst only
# when the XFeat burst is early and substantial; weak/late/no-XFeat probes fall
# back to a KLT-safe feature bag.
#
# Usage:
#   RUN_VINS=0 bash scripts/run_cirs_xfeat_arbitrated_eval.sh START DURATION [EVERY_N]
#   RUN_VINS=1 bash scripts/run_cirs_xfeat_arbitrated_eval.sh 575 30 1

START_OFFSET="${1:?usage: run_cirs_xfeat_arbitrated_eval.sh START_OFFSET DURATION [EVERY_N]}"
DURATION="${2:?usage: run_cirs_xfeat_arbitrated_eval.sh START_OFFSET DURATION [EVERY_N]}"
EVERY_N="${3:-1}"

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
METHOD="${METHOD:-hybrid_xfeat}"
MODE="${MODE:-external}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-$ROOT/uw_frontend/configs/experiments/cirs_xfeat_seedchain_klt_probe.yaml}"
TAG_BASE="${TAG_BASE:-jun25_xfeat_arbitrated_s${START_OFFSET}_d${DURATION}}"
DO_VINS="${RUN_VINS:-0}"
FORCE_EXPORT="${FORCE_EXPORT:-0}"
FORCE_RAW="${FORCE_RAW:-0}"
PORT="${PORT:-13480}"

ARBITRATION_MAX_SELECTED_FRAME="${ARBITRATION_MAX_SELECTED_FRAME:-15}"
ARBITRATION_MIN_DENSE_CAP_HITS="${ARBITRATION_MIN_DENSE_CAP_HITS:-1}"
ARBITRATION_DENSE_CAP_REASON="${ARBITRATION_DENSE_CAP_REASON:-dense_start_cap}"
ARBITRATION_ENABLE_KLT_SAFE_FALLBACK="${ARBITRATION_ENABLE_KLT_SAFE_FALLBACK:-1}"
ARBITRATION_OLDCONTRACT_MAX_FIRST_XFEAT_FRAME="${ARBITRATION_OLDCONTRACT_MAX_FIRST_XFEAT_FRAME:-12}"
ARBITRATION_OLDCONTRACT_MIN_CANDIDATE_SUM="${ARBITRATION_OLDCONTRACT_MIN_CANDIDATE_SUM:-15}"
ARBITRATION_OLDCONTRACT_MIN_XFEAT_SUM="${ARBITRATION_OLDCONTRACT_MIN_XFEAT_SUM:-20}"

COMMON_ENV=(
  FRONTEND_CONFIG="$FRONTEND_CONFIG"
  LEARNED_EXPORT_BENEFIT_GATE=0
  LEARNED_EXPORT_ONLINE_SEED_GATE=1
  LEARNED_EXPORT_ONLINE_SEED_SOURCES=xfeat
  LEARNED_EXPORT_ONLINE_SEED_MAX_OBSERVATIONS=50
  LEARNED_EXPORT_ONLINE_SEED_MAX_PER_FRAME=0
  LEARNED_EXPORT_ONLINE_SEED_MICROBURST_GATE=1
  LEARNED_EXPORT_ONLINE_SEED_MICROBURST_FRAMES=3
  LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_FRAMES=12
  LEARNED_EXPORT_ONLINE_SEED_MICROBURST_EXTEND_MIN_INITIAL_OBSERVATIONS=20
  LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MAX_OBSERVATIONS=5
  LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_TRACKS=218
  LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_CLASSICAL_GRID=0.98
  LEARNED_EXPORT_ONLINE_SEED_DENSE_START_MIN_FRAME_CANDIDATES=8
)

OLD_PROBE_TAG="${TAG_BASE}_probe_oldcontract_densecap"
OLD_PROBE_RUN="$ROOT/logs/cirs_caves_vins/${MODE}_${METHOD}_every${EVERY_N}_${OLD_PROBE_TAG}"

env "${COMMON_ENV[@]}" \
  TAG="$OLD_PROBE_TAG" \
  RUN_VINS=0 \
  FORCE_EXPORT="$FORCE_EXPORT" \
  FORCE_RAW="$FORCE_RAW" \
  MEASUREMENT_SELECTION=0 \
  FORMAL_THREE_LAYER_EXPORT=0 \
  VINS_SAFE_SOURCE_SELECTION=0 \
  EXPORT_CLASSICAL_MIRROR_BACKBONE=0 \
  LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES=8 \
  bash "$ROOT/scripts/run_cirs_caves_vins_eval.sh" "$MODE" "$START_OFFSET" "$DURATION" "$METHOD" "$EVERY_N"

DECISION="$(
  python3 - "$OLD_PROBE_RUN/frontend_metrics.csv" \
    "$ARBITRATION_MAX_SELECTED_FRAME" \
    "$ARBITRATION_MIN_DENSE_CAP_HITS" \
    "$ARBITRATION_DENSE_CAP_REASON" \
    "$ARBITRATION_ENABLE_KLT_SAFE_FALLBACK" \
    "$ARBITRATION_OLDCONTRACT_MAX_FIRST_XFEAT_FRAME" \
    "$ARBITRATION_OLDCONTRACT_MIN_CANDIDATE_SUM" \
    "$ARBITRATION_OLDCONTRACT_MIN_XFEAT_SUM" <<'PY'
import csv
import sys
from pathlib import Path

metrics = Path(sys.argv[1])
max_selected = int(float(sys.argv[2]))
min_hits = int(float(sys.argv[3]))
needle = str(sys.argv[4])
enable_fallback = str(sys.argv[5]).strip().lower() not in {"0", "false", "no"}
max_first_xfeat = int(float(sys.argv[6]))
min_candidate_sum = int(float(sys.argv[7]))
min_xfeat_sum = int(float(sys.argv[8]))

hits = 0
hit_rows = []
xfeat_total = 0
xfeat_frames = 0
first_xfeat = None
last_xfeat = None
candidate_sum_on_xfeat_frames = 0
confirmed_sum_on_xfeat_frames = 0
pre_basic_sum_on_xfeat_frames = 0
if metrics.exists():
    with metrics.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                selected = int(float(row.get("selected_feature_index") or -1))
            except ValueError:
                selected = -1
            try:
                xfeat_count = int(float(row.get("exported_xfeat_features") or 0))
            except ValueError:
                xfeat_count = 0
            if xfeat_count > 0:
                xfeat_total += xfeat_count
                xfeat_frames += 1
                first_xfeat = selected if first_xfeat is None else min(first_xfeat, selected)
                last_xfeat = selected if last_xfeat is None else max(last_xfeat, selected)
                try:
                    candidate_sum_on_xfeat_frames += int(
                        float(row.get("learned_candidate_count") or 0)
                    )
                except ValueError:
                    pass
                try:
                    confirmed_sum_on_xfeat_frames += int(
                        float(row.get("learned_confirmed_count") or 0)
                    )
                except ValueError:
                    pass
                try:
                    pre_basic_sum_on_xfeat_frames += int(
                        float(row.get("pre_gate_non_loftr_basic_ok") or 0)
                    )
                except ValueError:
                    pass
            if selected > max_selected:
                continue
            reason = row.get("learned_export_benefit_reason") or ""
            if needle in reason:
                hits += 1
                hit_rows.append(
                    f"sf={selected}:x={row.get('exported_xfeat_features')}:"
                    f"classical={row.get('classical_track_count')}:"
                    f"grid={row.get('classical_grid_coverage')}:"
                    f"reason={reason}"
                )

first_xfeat_for_rule = 10**9 if first_xfeat is None else first_xfeat
early_oldcontract_signature = (
    first_xfeat_for_rule <= max_first_xfeat
    and (
        candidate_sum_on_xfeat_frames >= min_candidate_sum
        or xfeat_total >= min_xfeat_sum
    )
)
if hits >= min_hits:
    profile = "mirror_densecap"
elif enable_fallback and not early_oldcontract_signature:
    profile = "klt_safe_fallback"
else:
    profile = "oldcontract_microburst"
print(profile)
print(f"dense_cap_hits={hits}")
print(f"probe_xfeat_total={xfeat_total}")
print(f"probe_xfeat_frames={xfeat_frames}")
print(f"probe_first_xfeat_frame={first_xfeat if first_xfeat is not None else 'none'}")
print(f"probe_last_xfeat_frame={last_xfeat if last_xfeat is not None else 'none'}")
print(f"probe_candidate_sum_on_xfeat_frames={candidate_sum_on_xfeat_frames}")
print(f"probe_confirmed_sum_on_xfeat_frames={confirmed_sum_on_xfeat_frames}")
print(f"probe_pre_basic_sum_on_xfeat_frames={pre_basic_sum_on_xfeat_frames}")
print(f"oldcontract_signature={1 if early_oldcontract_signature else 0}")
for item in hit_rows[:6]:
    print(item)
PY
)"

PROFILE="$(printf '%s\n' "$DECISION" | sed -n '1p')"
DENSE_HITS="$(printf '%s\n' "$DECISION" | sed -n '2p')"

if [[ "$PROFILE" == "mirror_densecap" ]]; then
  FINAL_TAG="${TAG_BASE}_mirror_densecap"
  FINAL_RUN="$ROOT/logs/cirs_caves_vins/${MODE}_${METHOD}_every${EVERY_N}_${FINAL_TAG}"
  env "${COMMON_ENV[@]}" \
    TAG="$FINAL_TAG" \
    RUN_VINS=0 \
    FORCE_EXPORT="$FORCE_EXPORT" \
    FORCE_RAW="$FORCE_RAW" \
    MEASUREMENT_SELECTION=0 \
    FORMAL_THREE_LAYER_EXPORT=0 \
    VINS_SAFE_SOURCE_SELECTION=0 \
    EXPORT_CLASSICAL_MIRROR_BACKBONE=1 \
    LEARNED_EXPORT_ONLINE_SEED_WARMUP_FRAMES=0 \
    bash "$ROOT/scripts/run_cirs_caves_vins_eval.sh" "$MODE" "$START_OFFSET" "$DURATION" "$METHOD" "$EVERY_N"
elif [[ "$PROFILE" == "klt_safe_fallback" ]]; then
  FINAL_TAG="${TAG_BASE}_klt_safe_fallback"
  FINAL_METHOD="${KLT_FALLBACK_METHOD:-klt}"
  FINAL_RUN="$ROOT/logs/cirs_caves_vins/${MODE}_${FINAL_METHOD}_every${EVERY_N}_${FINAL_TAG}"
  TAG="$FINAL_TAG" \
    RUN_VINS=0 \
    FORCE_EXPORT="$FORCE_EXPORT" \
    FORCE_RAW="$FORCE_RAW" \
    bash "$ROOT/scripts/run_cirs_caves_vins_eval.sh" "$MODE" "$START_OFFSET" "$DURATION" "$FINAL_METHOD" "$EVERY_N"
else
  FINAL_TAG="$OLD_PROBE_TAG"
  FINAL_RUN="$OLD_PROBE_RUN"
fi

SUMMARY_PATH="$FINAL_RUN/arbitration_summary.txt"
{
  echo "profile=$PROFILE"
  echo "$DENSE_HITS"
  echo "probe_run=$OLD_PROBE_RUN"
  echo "final_run=$FINAL_RUN"
  echo "feature_bag=$FINAL_RUN/features.bag"
  printf '%s\n' "$DECISION" | sed -n '3,30p'
} | tee "$SUMMARY_PATH"

if [[ "$DO_VINS" == "1" ]]; then
  VINS_TAG="existing_${TAG_BASE}_${PROFILE}"
  SOURCE_CONFIG="$FINAL_RUN/vins_cirs_${MODE}.yaml" \
  SOURCE_CAMERA_CONFIG="$FINAL_RUN/cirs_cam0_pinhole.yaml" \
  IMU_TOPIC=/cirs/imu_xsens \
  PORT="$PORT" \
  bash "$ROOT/scripts/run_existing_featurebag_vins_eval.sh" \
    "$FINAL_RUN" "$FINAL_RUN/features.bag" "$VINS_TAG" /cirs/odometry_gt
fi
