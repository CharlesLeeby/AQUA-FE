#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
CASE_ID="${1:?usage: run_frozen_frontend_threeway_case.sh CASE_ID}"
OUT_ROOT="${OUT_ROOT:-/mnt/data/AQUA-FE_WS/frozen_frontend_eval_20260714}"
RESUME="${RESUME:-1}"

check_hash() {
  local expected="$1"
  local path="$2"
  local actual
  actual="$(sha256sum "$ROOT/$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "frozen hash mismatch: $path expected=$expected actual=$actual" >&2
    exit 3
  fi
}

check_hash 82bd47f019a423fc3e8f92bf533c06556dd1eb9b2d20c49ba8ff09e435744fb0 scripts/run_xfeat_seedchain_arbitrated_eval.sh
check_hash 8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106 scripts/run_learned_seedchain_eval.sh
check_hash de78c8258f32bcea4c04d4d4fffa9fa8ac82abffbf896a1c73ba28b694702f67 uw_frontend/ros/export_vins_features.py
check_hash 4500894ee15f4515881de6322e5780ce7f2381b2a1ce7fba4bd3d958e11264ce uw_frontend/configs/experiments/paper_vins_safe_learned_sidecar.yaml
check_hash 745d8c5c07cbc8fb65e307221f744e5c4b44b3f93618c4ca68754a7060430e0d scripts/filter_feature_bag_by_channel.py
check_hash ef68c19a0af6c06598bb473f57c581a7bb874b68cdccc95f4c85905bb9219d33 scripts/evaluate_vins_sim_ape.py
check_hash b994676b9e845c68427d01c8d80b1a4492ed2dedd25a770918cff61b0fea4ff4 scripts/evaluate_vins_tum.py

if [[ ! -d /home/ma/SLAM/VINS-Fusion-origin ]]; then
  echo "missing frozen VINS workspace: /home/ma/SLAM/VINS-Fusion-origin" >&2
  exit 3
fi

PROFILE="lineage_early_seed_scan"
EVERY_N=2
RUN_ROOT=""
GT_KIND="sim"
GT_TOPIC="/aqualoc/colmap_gt"
CASE_INDEX=0
RUN_ARGS=()
EXTRA_ENV=()

case "$CASE_ID" in
  a02_2800_3200) CASE_INDEX=1; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 2 2800 3200) ;;
  a05_3300_3700) CASE_INDEX=2; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 5 3300 3700) ;;
  a07_10800_11200)
    CASE_INDEX=3; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 7 10800 11200)
    EXTRA_ENV+=(ARBITRATION_DEGRADED_MATURE_DENSE_RECOVERY=1 VINS_TD=-0.033694112369382575 VINS_ESTIMATE_TD=0 PLAY_RATE=1.0 WAIT_FOR_VINS_SUBSCRIBERS=1)
    ;;
  a08_4500_4660)
    CASE_INDEX=4; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 8 4500 4660)
    EXTRA_ENV+=(LEARNED_EXPORT_ONLINE_SEED_POST_QUALITY_CAP_PER_FRAME=2)
    ;;
  a09_6000_6200) CASE_INDEX=5; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 9 6000 6200) ;;
  fjord1_s83_d10)
    CASE_INDEX=6; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu fjord_1 83 10); GT_KIND=tum
    ;;
  mclab1_s60_d15)
    CASE_INDEX=7; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu mclab_1 60 15); GT_KIND=tum
    ;;
  cirs_s575_d30)
    CASE_INDEX=8; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 575 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  cirs_s900_d30)
    CASE_INDEX=9; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 900 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  a09_5000_5400) CASE_INDEX=10; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 9 5000 5400) ;;
  a02_7600_8000) CASE_INDEX=11; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 2 7600 8000) ;;
  mclab2_s110_d10)
    CASE_INDEX=12; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu mclab_2 110 10); GT_KIND=tum
    ;;
  h02_2400_2800)
    CASE_INDEX=13; RUN_ROOT="$ROOT/logs/aqualoc_real_vins"; RUN_ARGS=(aqualoc_real 2 2400 2800)
    ;;
  a09_4000_4400) CASE_INDEX=14; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 9 4000 4400) ;;
  a02_8600_9000) CASE_INDEX=15; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 2 8600 9000) ;;
  a08_4480_4680) CASE_INDEX=16; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 8 4480 4680) ;;
  fjord5_s110_d10)
    CASE_INDEX=17; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu fjord_5 110 10); GT_KIND=tum
    ;;
  cirs_s450_d30)
    CASE_INDEX=18; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 450 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  cirs_s840_d30)
    CASE_INDEX=19; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 840 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  cirs_s960_d30)
    CASE_INDEX=20; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 960 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  afrl_fr70_100)
    echo "AFRL FR70-100 has no raw bag; use the documented existing-bag replay instead." >&2
    exit 4
    ;;
  *) echo "unknown case: $CASE_ID" >&2; exit 2 ;;
esac

mkdir -p "$OUT_ROOT/bags/$CASE_ID" "$OUT_ROOT/status" "$OUT_ROOT/logs"
TAG_BASE="jul14frozen3way_${CASE_ID}"
FULL_TAG="${TAG_BASE}_full"
DROP_TAG="${TAG_BASE}_drop_lineage"
KLT_TAG="${TAG_BASE}_klt"
PORT_BASE="${PORT_BASE:-$((15100 + CASE_INDEX * 10))}"
COMMON_ENV=(
  TMPDIR=/mnt/data/AQUA-FE_WS/tmp
  VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
  VINS_MULTIPLE_THREAD=0
  AQUAFE_SEEDCHAIN_PROFILE="$PROFILE"
)

find_run_by_tag() {
  local tag="$1"
  find "$RUN_ROOT" -maxdepth 1 -type d -name "*_${tag}" -print | sort | tail -1
}

run_full() {
  local existing
  local rc=0
  existing="$(find_run_by_tag "$FULL_TAG")"
  if [[ "$RESUME" == "1" && -n "$existing" && -f "$OUT_ROOT/status/$CASE_ID.full_attempted" ]]; then
    echo "reuse full VINS: $existing"
    return
  fi
  env "${COMMON_ENV[@]}" "${EXTRA_ENV[@]}" \
    TAG_BASE="$TAG_BASE" ARBITRATION_VINS_TAG="$FULL_TAG" \
    PORT="$PORT_BASE" RUN_VINS=1 FORCE_EXPORT=1 FORCE_RAW=0 \
    bash "$ROOT/scripts/run_xfeat_seedchain_arbitrated_eval.sh" \
    "${RUN_ARGS[@]}" hybrid_xfeat "$EVERY_N" || rc=$?
  printf '%s\n' "$rc" > "$OUT_ROOT/status/$CASE_ID.full_exit_code"
  touch "$OUT_ROOT/status/$CASE_ID.full_attempted"
}

find_final_run() {
  local summary
  summary="$(find "$RUN_ROOT" -maxdepth 2 -path "*${TAG_BASE}*" -name arbitration_summary.txt -print | sort | tail -1)"
  if [[ -z "$summary" ]]; then
    echo "missing arbitration summary for $CASE_ID" >&2
    exit 5
  fi
  sed -n 's/^final_run=//p' "$summary" | tail -1
}

run_drop() {
  local final_run="$1"
  local drop_dir="$OUT_ROOT/bags/$CASE_ID"
  local drop_bag="$drop_dir/features_drop_whole_lineage.bag"
  local drop_stats="$drop_dir/drop_whole_lineage_stats.csv"
  local existing
  local rc=0
  if [[ ! -s "$drop_bag" || "$RESUME" != "1" ]]; then
    python3 "$ROOT/scripts/filter_feature_bag_by_channel.py" \
      --input-bag "$final_run/features.bag" \
      --output-bag "$drop_bag" \
      --stats-csv "$drop_stats" \
      --drop-learned-track-lineage
  fi
  existing="$(find_run_by_tag "$DROP_TAG")"
  if [[ "$RESUME" == "1" && -n "$existing" && -f "$OUT_ROOT/status/$CASE_ID.drop_attempted" ]]; then
    echo "reuse drop VINS: $existing"
    return
  fi
  env "${COMMON_ENV[@]}" "${EXTRA_ENV[@]}" \
    TAG="$DROP_TAG" PORT="$((PORT_BASE + 1))" RUN_VINS=1 FORCE_EXPORT=0 EXPORT_FEATURES=0 \
    FEATURE_BAG_OVERRIDE="$drop_bag" \
    bash "$ROOT/scripts/run_learned_seedchain_eval.sh" \
    "${RUN_ARGS[@]}" hybrid_xfeat "$EVERY_N" || rc=$?
  printf '%s\n' "$rc" > "$OUT_ROOT/status/$CASE_ID.drop_exit_code"
  touch "$OUT_ROOT/status/$CASE_ID.drop_attempted"
}

run_klt() {
  local existing
  local rc=0
  existing="$(find_run_by_tag "$KLT_TAG")"
  if [[ "$RESUME" == "1" && -n "$existing" && -f "$OUT_ROOT/status/$CASE_ID.klt_attempted" ]]; then
    echo "reuse KLT VINS: $existing"
    return
  fi
  env "${COMMON_ENV[@]}" "${EXTRA_ENV[@]}" \
    TAG="$KLT_TAG" PORT="$((PORT_BASE + 2))" RUN_VINS=1 FORCE_EXPORT=1 FORCE_RAW=0 \
    bash "$ROOT/scripts/run_learned_seedchain_eval.sh" \
    "${RUN_ARGS[@]}" klt "$EVERY_N" || rc=$?
  printf '%s\n' "$rc" > "$OUT_ROOT/status/$CASE_ID.klt_exit_code"
  touch "$OUT_ROOT/status/$CASE_ID.klt_attempted"
}

strict_eval() {
  local run_dir="$1"
  local out="$run_dir/ape_strict_dt0p6.txt"
  local manifest="$run_dir/replay_manifest.txt"
  local play_bag gt_tum
  if [[ ! -s "$run_dir/vins_output/vio.csv" ]]; then
    printf 'evaluation_error=empty_vins_trajectory\n' > "$out"
    return
  fi
  if [[ "$GT_KIND" == "tum" ]]; then
    gt_tum="$(sed -n 's/^gt_tum=//p' "$manifest" | tail -1)"
    local expected_times expected_start expected_end
    expected_times="$(python3 - "$run_dir/vins_output/vio.csv" "$run_dir/ape.txt" <<'PY'
import sys
from pathlib import Path

root = Path('/home/ma/AQUA-FE_WS')
sys.path.insert(0, str(root / 'scripts'))
from evaluate_vins_sim_ape import load_vins

values = {}
for line in Path(sys.argv[2]).read_text(encoding='utf-8').splitlines():
    if '=' in line:
        key, value = line.split('=', 1)
        values[key] = value
vins = load_vins(Path(sys.argv[1]))
if not vins:
    raise SystemExit('empty VINS trajectory')
start = vins[0][0] - float(values['first_output_delay_s'])
end = start + float(values['expected_duration_s'])
print(f"{start:.9f} {end:.9f}")
PY
)"
    expected_start="$(awk '{print $1}' <<< "$expected_times")"
    expected_end="$(awk '{print $2}' <<< "$expected_times")"
    if ! python3 "$ROOT/scripts/evaluate_vins_tum.py" \
      --vins-csv "$run_dir/vins_output/vio.csv" \
      --gt-tum "$gt_tum" \
      --vins-log "$run_dir/vins.log" \
      --expected-start "$expected_start" --expected-end "$expected_end" \
      --rpe-delta-s 1.0 --max-match-dt 0.6 > "$out" 2>&1; then
      printf '\nevaluation_error=strict_evaluator_failed\n' >> "$out"
    fi
  else
    play_bag="$(sed -n 's/^play_bag=//p' "$manifest" | tail -1)"
    if ! python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
      --vins-csv "$run_dir/vins_output/vio.csv" \
      --bag "$play_bag" --gt-topic "$GT_TOPIC" \
      --vins-log "$run_dir/vins.log" \
      --rpe-delta-s 1.0 --max-match-dt 0.6 > "$out" 2>&1; then
      printf '\nevaluation_error=strict_evaluator_failed\n' >> "$out"
    fi
  fi
}

run_full
FINAL_RUN="$(find_final_run)"
FULL_RUN="$(find_run_by_tag "$FULL_TAG")"
if [[ -z "$FULL_RUN" || ! -d "$FULL_RUN" || ! -s "$FINAL_RUN/features.bag" ]]; then
  echo "missing full artifacts for $CASE_ID" >&2
  exit 5
fi
run_drop "$FINAL_RUN"
run_klt
DROP_RUN="$(find_run_by_tag "$DROP_TAG")"
KLT_RUN="$(find_run_by_tag "$KLT_TAG")"
if [[ -z "$DROP_RUN" || ! -d "$DROP_RUN" || -z "$KLT_RUN" || ! -d "$KLT_RUN" ]]; then
  echo "missing drop or KLT run directory for $CASE_ID" >&2
  exit 5
fi

strict_eval "$FULL_RUN"
strict_eval "$DROP_RUN"
strict_eval "$KLT_RUN"

{
  echo "case_id=$CASE_ID"
  echo "tag_base=$TAG_BASE"
  echo "profile=$(sed -n 's/^profile=//p' "$FINAL_RUN/arbitration_summary.txt" | tail -1)"
  echo "final_export_run=$FINAL_RUN"
  echo "full_run=$FULL_RUN"
  echo "drop_run=$DROP_RUN"
  echo "klt_run=$KLT_RUN"
  echo "full_bag_sha256=$(sha256sum "$FINAL_RUN/features.bag" | awk '{print $1}')"
  echo "drop_bag_sha256=$(sha256sum "$OUT_ROOT/bags/$CASE_ID/features_drop_whole_lineage.bag" | awk '{print $1}')"
  echo "klt_bag_sha256=$(sha256sum "$KLT_RUN/features.bag" | awk '{print $1}')"
} > "$OUT_ROOT/status/$CASE_ID.env"

echo "completed $CASE_ID"
cat "$OUT_ROOT/status/$CASE_ID.env"
