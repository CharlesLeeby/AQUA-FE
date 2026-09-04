#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
CASE_ID="${1:?usage: run_frozen_positive_replay_regression.sh CASE_ID}"
OUT_ROOT="${OUT_ROOT:-/mnt/data/AQUA-FE_WS/frozen_positive_replay_20260717}"
RESUME="${RESUME:-1}"
RESULTS_LONG="$ROOT/papers/frozen_frontend_eval_20260714/analysis-output/results_long.csv"

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

PROFILE="lineage_early_seed_scan"
EVERY_N=2
RUN_ROOT=""
GT_KIND="sim"
GT_TOPIC="/aqualoc/colmap_gt"
CASE_INDEX=0
RUN_ARGS=()
EXTRA_ENV=()

case "$CASE_ID" in
  a05_3300_3700) CASE_INDEX=1; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 5 3300 3700) ;;
  a07_10800_11200)
    CASE_INDEX=2; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 7 10800 11200)
    EXTRA_ENV+=(ARBITRATION_DEGRADED_MATURE_DENSE_RECOVERY=1 VINS_TD=-0.033694112369382575 VINS_ESTIMATE_TD=0)
    ;;
  a08_4500_4660) CASE_INDEX=3; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 8 4500 4660) ;;
  a09_6000_6200) CASE_INDEX=4; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 9 6000 6200) ;;
  fjord1_s83_d10)
    CASE_INDEX=5; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu fjord_1 83 10); GT_KIND=tum
    ;;
  mclab1_s60_d15)
    CASE_INDEX=6; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu mclab_1 60 15); GT_KIND=tum
    ;;
  cirs_s575_d30)
    CASE_INDEX=7; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 575 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  cirs_s900_d30)
    CASE_INDEX=8; RUN_ROOT="$ROOT/logs/cirs_caves_vins"; RUN_ARGS=(cirs 900 30); EVERY_N=1; PROFILE=cirs_dense_start; GT_TOPIC=/cirs/odometry_gt
    ;;
  a09_5000_5400) CASE_INDEX=9; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 9 5000 5400) ;;
  a02_7600_8000) CASE_INDEX=10; RUN_ROOT="$ROOT/logs/aqualoc_archaeo_vins"; RUN_ARGS=(aqualoc_archaeo 2 7600 8000) ;;
  mclab2_s110_d10)
    CASE_INDEX=11; RUN_ROOT="$ROOT/logs/ntnu_vins"; RUN_ARGS=(ntnu mclab_2 110 10); GT_KIND=tum
    ;;
  *) echo "unsupported frozen learned-active case: $CASE_ID" >&2; exit 2 ;;
esac

mkdir -p "$OUT_ROOT/logs" "$OUT_ROOT/status" "$OUT_ROOT/manifests"
PORT_BASE="${PORT_BASE:-$((17100 + CASE_INDEX * 10))}"
TAG_SUFFIX="${TAG_SUFFIX:-}"
TAG_BASE="jul17positive_replay_${CASE_ID}"
if [[ -n "$TAG_SUFFIX" ]]; then
  TAG_BASE="${TAG_BASE}_${TAG_SUFFIX}"
fi
COMMON_ENV=(
  TMPDIR=/mnt/data/AQUA-FE_WS/tmp
  VINS_WS=/home/ma/SLAM/VINS-Fusion-origin
  VINS_MULTIPLE_THREAD=0
  PLAY_RATE=1.0
  WAIT_FOR_VINS_SUBSCRIBERS=1
  ROSBAG_WAIT_FOR_SUBSCRIBERS=0
  AQUAFE_SEEDCHAIN_PROFILE="$PROFILE"
)

lookup_field() {
  local arm="$1"
  local field="$2"
  python3 - "$RESULTS_LONG" "$CASE_ID" "$arm" "$field" <<'PY'
import csv
import sys

path, case_id, arm, field = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    rows = [
        row for row in csv.DictReader(handle)
        if row["case_id"] == case_id and row["arm"] == arm
    ]
if len(rows) != 1:
    raise SystemExit(f"expected one row for {case_id}/{arm}, found {len(rows)}")
print(rows[0][field])
PY
}

source_bag() {
  local arm="$1"
  local source_run manifest bag expected actual
  source_run="$(lookup_field "$arm" run_dir)"
  manifest="$source_run/replay_manifest.txt"
  bag=""
  if [[ -f "$manifest" ]]; then
    bag="$(sed -n 's/^play_bag=//p' "$manifest" | tail -1)"
  fi
  if [[ -z "$bag" ]]; then
    bag="$source_run/features.bag"
  fi
  expected="$(lookup_field "$arm" bag_sha256)"
  actual="$(sha256sum "$bag" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "bag hash mismatch: $CASE_ID/$arm expected=$expected actual=$actual bag=$bag" >&2
    exit 3
  fi
  printf '%s\n' "$bag"
}

find_run_by_tag() {
  local tag="$1"
  find "$RUN_ROOT" -maxdepth 1 -type d -name "*_${tag}" -print | sort | tail -1
}

run_arm() {
  local arm="$1"
  local bag method tag port run_dir log rc=0
  bag="$(source_bag "$arm")"
  method=hybrid_xfeat
  if [[ "$arm" == "klt" ]]; then
    method=klt
  fi
  tag="${TAG_BASE}_${arm}"
  port="$((PORT_BASE + 1))"
  if [[ "$arm" == "drop" ]]; then port="$((PORT_BASE + 2))"; fi
  if [[ "$arm" == "klt" ]]; then port="$((PORT_BASE + 3))"; fi
  run_dir="$(find_run_by_tag "$tag")"
  if [[ "$RESUME" == "1" && -n "$run_dir" && -s "$run_dir/vins_output/vio.csv" && -s "$run_dir/ape_strict_dt0p6.txt" ]]; then
    echo "reuse $CASE_ID/$arm: $run_dir"
    return
  fi
  log="$OUT_ROOT/logs/${CASE_ID}.${arm}.log"
  env "${COMMON_ENV[@]}" "${EXTRA_ENV[@]}" \
    TAG="$tag" PORT="$port" RUN_VINS=1 FORCE_EXPORT=0 EXPORT_FEATURES=0 \
    FEATURE_BAG_OVERRIDE="$bag" \
    bash "$ROOT/scripts/run_learned_seedchain_eval.sh" \
    "${RUN_ARGS[@]}" "$method" "$EVERY_N" > "$log" 2>&1 || rc=$?
  printf '%s\n' "$rc" > "$OUT_ROOT/status/${CASE_ID}.${arm}.exit_code"
  if [[ "$rc" != "0" ]]; then
    echo "replay failed: $CASE_ID/$arm rc=$rc log=$log" >&2
    exit "$rc"
  fi
}

strict_eval() {
  local arm="$1"
  local tag="${TAG_BASE}_${arm}"
  local run_dir out manifest play_bag gt_tum expected_times expected_start expected_end
  run_dir="$(find_run_by_tag "$tag")"
  out="$run_dir/ape_strict_dt0p6.txt"
  manifest="$run_dir/replay_manifest.txt"
  if [[ ! -s "$run_dir/vins_output/vio.csv" ]]; then
    printf 'evaluation_error=empty_vins_trajectory\n' > "$out"
    return
  fi
  if [[ "$GT_KIND" == "tum" ]]; then
    gt_tum="$(sed -n 's/^gt_tum=//p' "$manifest" | tail -1)"
    expected_times="$(python3 - "$run_dir/vins_output/vio.csv" "$run_dir/ape.txt" <<'PY'
import sys
from pathlib import Path

root = Path("/home/ma/AQUA-FE_WS")
sys.path.insert(0, str(root / "scripts"))
from evaluate_vins_sim_ape import load_vins

values = {}
for line in Path(sys.argv[2]).read_text(encoding="utf-8").splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        values[key] = value
vins = load_vins(Path(sys.argv[1]))
if not vins:
    raise SystemExit("empty VINS trajectory")
start = vins[0][0] - float(values["first_output_delay_s"])
end = start + float(values["expected_duration_s"])
print(f"{start:.9f} {end:.9f}")
PY
)"
    expected_start="$(awk '{print $1}' <<< "$expected_times")"
    expected_end="$(awk '{print $2}' <<< "$expected_times")"
    python3 "$ROOT/scripts/evaluate_vins_tum.py" \
      --vins-csv "$run_dir/vins_output/vio.csv" --gt-tum "$gt_tum" \
      --vins-log "$run_dir/vins.log" --expected-start "$expected_start" \
      --expected-end "$expected_end" --rpe-delta-s 1.0 --max-match-dt 0.6 \
      > "$out"
  else
    play_bag="$(sed -n 's/^play_bag=//p' "$manifest" | tail -1)"
    python3 "$ROOT/scripts/evaluate_vins_sim_ape.py" \
      --vins-csv "$run_dir/vins_output/vio.csv" --bag "$play_bag" \
      --gt-topic "$GT_TOPIC" --vins-log "$run_dir/vins.log" \
      --rpe-delta-s 1.0 --max-match-dt 0.6 > "$out"
  fi
}

for arm in full drop klt; do
  run_arm "$arm"
  strict_eval "$arm"
done

{
  echo "case_id=$CASE_ID"
  for arm in full drop klt; do
    echo "${arm}_run=$(find_run_by_tag "${TAG_BASE}_${arm}")"
    echo "${arm}_source_bag=$(source_bag "$arm")"
  done
} > "$OUT_ROOT/manifests/${CASE_ID}.txt"

echo "completed $CASE_ID"
