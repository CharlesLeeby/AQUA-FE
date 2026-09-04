#!/usr/bin/env bash
set -euo pipefail

ROOT="${ROOT:-/home/ma/AQUA-FE_WS}"
RESULT_ROOT="$ROOT/papers/frontend_same_backend_comparison"
CUDA_ENV_BIN="/mnt/data/AQUA-FE_WS/envs/aquafe_cuda/bin"
TASK_TMP="/mnt/data/AQUA-FE_WS/tmp/frontend_same_backend_comparison_v1"
REPEAT_COUNT=3
EVERY_N=2
PORT_BASE="${PORT_BASE:-24700}"
RUN_ONLY_WINDOW="${RUN_ONLY_WINDOW:-}"
RUN_ONLY_ARM="${RUN_ONLY_ARM:-}"

check_hash() {
  local expected="$1" path="$2" actual
  actual="$(sha256sum "$path" | awk '{print $1}')"
  if [[ "$actual" != "$expected" ]]; then
    echo "frozen input hash mismatch: $path expected=$expected actual=$actual" >&2
    exit 65
  fi
}

check_frozen_inputs() {
  check_hash e5f7edbf84e8f3ce277a91ff01a86cba2fb5ef7255de5a04644bdfb247ef67ee "$RESULT_ROOT/windows.csv"
  check_hash cd25847aecf86e1c86121aadb7dc8c3bc1d068b34fe0c34561e295a67f1c3633 "$RESULT_ROOT/arms.csv"
  check_hash 5d1bce2f329bbd1afbb7e8cee41ce54a6d2411cf79ed0bc6a31c5ebafcfbfd11 "$RESULT_ROOT/contract.json"
  check_hash e3ff7a2b4dc6f0d822eecdfa49c74575f529324df975ba84f1eb2bc108300999 "$RESULT_ROOT/preregistration.md"
  check_hash dd8fab5441f2ebf65a78e78642fe387e8c8e0a7893892b1ce31275498289dde8 "$RESULT_ROOT/runtime_weight_lock.json"
  check_hash 68453b035037d04087dbad3e512c602b4ef6967b2a8cf6d14e34a14750f2312d "$ROOT/uw_frontend/ros/export_vins_features.py"
  check_hash 6f89d861cc002dfaf0eaf5f1294b0dbcfab9fe268c5dc0d09082f79811000bf3 "$ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
  check_hash 8b2db28e5a5c1cc4dfd8ce365d44bdc618e6ec2c4a70db4ea2549b73a965b106 "$ROOT/scripts/run_learned_seedchain_eval.sh"
  check_hash f4407a4dfe808f6d9f5c7b23ad1ad66cd06d58e87257fb9d6b355153c71a2df3 "$ROOT/scripts/learned_seedchain_env.sh"
  check_hash 9da109074d559875434bc82e43febd7acf1e60c027f11bae31023e6d08198a9b "$ROOT/scripts/run_aqualoc_archaeo_vins_eval.sh"
  check_hash a8cf19217dcdd358e73a6ec1293319868142d301a63db9f2a67208f01d7a6e48 "$ROOT/scripts/run_aqualoc_real_vins_eval.sh"
  check_hash d393cd133adaf43c9633a984ba073bcab3bb0494fe2473746abcb5f73327297a "$ROOT/scripts/run_ntnu_vins_eval.sh"
  check_hash 52b6708629640ca883673b5d5c097c4ddad37d8048b33f09c8ca0d69db12c40e /home/ma/.cache/torch/hub/checkpoints/superpoint_v1.pth
  check_hash 6ff7040d0a497fc6639337946d7538dae07428c18f77a067a0b5a960e7cc551a /home/ma/.cache/torch/hub/checkpoints/superpoint_lightglue_v0-1_arxiv.pth
  check_hash 0f5187fd7bedd26c7fe6acc9685444493a165a35ecc087b33c2db3627f3ea10b "$ROOT/external_tools/accelerated_features/weights/xfeat.pt"
  check_hash 9e44331a4208670575b12dc4a7f2c06d884ea77b3277d42aa1977128954b943a "$ROOT/uw_frontend/matchers/lightglue_adapter.py"
  check_hash dcb75b9cad1985c5e7a537c512d4318d47fbcc99df75b39a513de60e027c039f "$ROOT/external_tools/LightGlue/lightglue/lightglue.py"
  check_hash 23e8a26137b44f37e9a319313822c5b38d9c55796e756202eb46d64f1979d2b0 "$ROOT/external_tools/LightGlue/lightglue/superpoint.py"
  check_hash 8090ad7246b7acba62183577d108f62b41c87fe04f52c66f5d897315481e91ee "$ROOT/uw_frontend/matchers/xfeat_adapter.py"
  check_hash 385ccd31d095b0d4176b04e982088b85321b11ade4324f83b097ee6524f2a6e7 "$ROOT/external_tools/accelerated_features/modules/xfeat.py"
  check_hash 4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278 /home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node
  check_hash 373a598c7ce591b4fe97ced9b3ee1de5bbf0322c105a54afcb03a91b810f71e8 /home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so
}

other_exporters() {
  ps -eo pid=,comm=,args= | awk '$2 ~ /^python/ && /uw_frontend\.ros\.export_vins_features/ && $0 !~ /fsbcv1_/ { print }'
}

window_spec() {
  case "$1" in
    a02_4500_6300) printf '%s\n' 'aqualoc_archaeo|2|4500|6300|1' ;;
    a09_4000_4400) printf '%s\n' 'aqualoc_archaeo|9|4000|4400|2' ;;
    a09_6000_6800) printf '%s\n' 'aqualoc_archaeo|9|6000|6800|3' ;;
    a10_2400_2800) printf '%s\n' 'aqualoc_archaeo|10|2400|2800|4' ;;
    a10_4800_5200) printf '%s\n' 'aqualoc_archaeo|10|4800|5200|5' ;;
    h07_1660_1720) printf '%s\n' 'aqualoc_real|h07|1660|1720|6' ;;
    mclab1_s60_d15) printf '%s\n' 'ntnu|mclab_1|60|15|7' ;;
    *) echo "unknown preregistered window: $1" >&2; return 2 ;;
  esac
}

arm_spec() {
  case "$1" in
    klt) printf '%s\n' 'klt|xfeat|1' ;;
    splg) printf '%s\n' 'hybrid_superpoint_lightglue|all_learned|2' ;;
    xfeat_seed) printf '%s\n' 'hybrid_xfeat|xfeat|3' ;;
    *) echo "unknown preregistered arm: $1" >&2; return 2 ;;
  esac
}

run_root_for_family() {
  case "$1" in
    aqualoc_archaeo) printf '%s\n' "$ROOT/logs/aqualoc_archaeo_vins" ;;
    aqualoc_real) printf '%s\n' "$ROOT/logs/aqualoc_real_vins" ;;
    ntnu) printf '%s\n' "$ROOT/logs/ntnu_vins" ;;
    *) return 2 ;;
  esac
}

write_cell_receipt() {
  local run_dir="$1" window_id="$2" arm_id="$3" repeat="$4" method="$5" seed_target="$6" feature_bag="$7" rc="$8"
  /usr/bin/python3 - "$run_dir" "$window_id" "$arm_id" "$repeat" "$method" "$seed_target" "$feature_bag" "$rc" <<'PY'
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
feature_bag = Path(sys.argv[7])

def identity(path: Path):
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"path": str(path.resolve()), "size_bytes": path.stat().st_size, "sha256": digest.hexdigest()}

payload = {
    "schema_version": "aqua-fe-fsbc-cell-v1",
    "completed_at": datetime.now(timezone.utc).isoformat(),
    "window_id": sys.argv[2],
    "arm_id": sys.argv[3],
    "repeat": int(sys.argv[4]),
    "method": sys.argv[5],
    "seed_target": sys.argv[6],
    "exit_code": int(sys.argv[8]),
    "feature_bag": identity(feature_bag),
    "vio_csv": identity(run_dir / "vins_output/vio.csv"),
    "vins_log": identity(run_dir / "vins.log"),
    "frontend_metrics": identity(run_dir / "frontend_metrics.csv"),
    "status": "ATTEMPT_COMPLETE",
}
(run_dir / "fsbc_cell_complete.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

run_cell() {
  local window_id="$1" arm_id="$2" repeat="$3"
  local ws as family p1 p2 p3 window_order method seed_target arm_order tag port run_root run_dir feature_bag
  local -a args common_env repeat_env
  local rc=0

  ws="$(window_spec "$window_id")"
  IFS='|' read -r family p1 p2 p3 window_order <<< "$ws"
  as="$(arm_spec "$arm_id")"
  IFS='|' read -r method seed_target arm_order <<< "$as"
  tag="fsbcv1_${window_id}_${arm_id}_r${repeat}"
  port="$((PORT_BASE + window_order * 20 + arm_order * 4 + repeat))"
  run_root="$(run_root_for_family "$family")"
  run_dir="$run_root/external_${method}_every${EVERY_N}_${tag}"
  feature_bag="$run_root/external_${method}_every${EVERY_N}_fsbcv1_${window_id}_${arm_id}_r1/features.bag"

  if [[ -f "$run_dir/fsbc_cell_complete.json" ]]; then
    echo "resume completed cell: $window_id $arm_id r$repeat"
    return 0
  fi

  check_frozen_inputs
  if [[ -n "$(other_exporters)" && "${ALLOW_UNRELATED_EXPORTERS:-0}" != "1" ]]; then
    echo "refusing contaminated launch; unrelated frontend exporters are active:" >&2
    other_exporters >&2
    return 75
  fi
  if [[ -n "$(other_exporters)" ]]; then
    echo "warning: unrelated CPU exporter active; timing/efficiency is censored" >&2
  fi

  case "$family" in
    aqualoc_archaeo) args=(aqualoc_archaeo "$p1" "$p2" "$p3" "$method" "$EVERY_N") ;;
    aqualoc_real) args=(aqualoc_real "$p1" "$p2" "$p3" "$method" "$EVERY_N") ;;
    ntnu) args=(ntnu "$p1" "$p2" "$p3" "$method" "$EVERY_N") ;;
  esac

  common_env=(
    "ROOT=$ROOT" "PATH=$CUDA_ENV_BIN:$PATH" "PYTHONDONTWRITEBYTECODE=1" "TORCH_HOME=/home/ma/.cache/torch"
    "TMPDIR=$TASK_TMP" "CUDA_VISIBLE_DEVICES=0" "CUDA_DEVICE_ORDER=PCI_BUS_ID"
    "ROS_DISTRO=noetic" "ROS_VERSION=1" "ROS_PYTHON_VERSION=3"
    "ROS_ROOT=/opt/ros/noetic/share/ros" "ROS_ETC_DIR=/opt/ros/noetic/etc"
    "ROS_MASTER_URI=http://localhost:$port" "ROS_HOSTNAME=localhost" "ROS_PACKAGE_PATH=/opt/ros/noetic/share"
    "OMP_NUM_THREADS=1" "MKL_NUM_THREADS=1" "OPENBLAS_NUM_THREADS=1" "NUMEXPR_NUM_THREADS=1"
    "TAG=$tag" "PORT=$port" "RUN_VINS=1" "AQUAFE_SEEDCHAIN_PROFILE=lineage_early_seed_scan"
    "FRONTEND_CONFIG=$ROOT/uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
    "MEASUREMENT_SELECTION=0" "EXPORT_MAX_FEATURES=350" "VINS_SAFE_SOURCE_SELECTION=0"
    "FRAME_OFFSET=1" "PROCESS_SKIPPED_FRAMES=1" "PREPROCESS=adaptive_clahe"
    "SEMIDENSE_FALLBACK_METHOD=none" "FORMAL_THREE_LAYER_EXPORT=0"
    "BACKEND_QUALITY_MODE=vins_safe" "BACKEND_QUALITY_ALPHA=0.65" "BACKEND_QUALITY_FLOOR=0.80"
    "VINS_MULTIPLE_THREAD=0" "VINS_ESTIMATE_TD=0" "PLAY_RATE=1.0" "POST_PLAY_SLEEP=8"
    "WAIT_FOR_VINS_SUBSCRIBERS=1" "ROSBAG_WAIT_FOR_SUBSCRIBERS=0"
    "LEARNED_EXPORT_ONLINE_SEED_SOURCES=$seed_target"
  )

  if [[ "$repeat" -eq 1 ]]; then
    repeat_env=("FORCE_EXPORT=1" "EXPORT_FEATURES=1" "FORCE_RAW=0")
  else
    if [[ ! -s "$feature_bag" ]]; then
      echo "missing immutable r1 feature bag: $feature_bag" >&2
      return 66
    fi
    repeat_env=("FORCE_EXPORT=0" "EXPORT_FEATURES=0" "FORCE_RAW=0" "FEATURE_BAG_OVERRIDE=$feature_bag")
  fi

  mkdir -p "$run_dir" "$TASK_TMP"
  {
    printf 'window_id=%s\narm_id=%s\nrepeat=%s\nmethod=%s\nseed_target=%s\nport=%s\n' \
      "$window_id" "$arm_id" "$repeat" "$method" "$seed_target" "$port"
    printf 'command=env [frozen contract] bash %q' "$ROOT/scripts/run_learned_seedchain_eval.sh"
    printf ' %q' "${args[@]}"
    printf '\n'
  } > "$run_dir/fsbc_command.txt"

  echo "start cell: $window_id $arm_id r$repeat method=$method port=$port"
  set +e
  env -i HOME="$HOME" USER="${USER:-ma}" LOGNAME="${LOGNAME:-ma}" SHELL=/bin/bash LANG="${LANG:-C.UTF-8}" TERM="${TERM:-dumb}" \
    "${common_env[@]}" "${repeat_env[@]}" \
    /usr/bin/bash "$ROOT/scripts/run_learned_seedchain_eval.sh" "${args[@]}" \
    > "$run_dir/fsbc_console.log" 2>&1
  rc=$?
  set -e
  printf '%s\n' "$rc" > "$run_dir/fsbc_exit_code.txt"
  write_cell_receipt "$run_dir" "$window_id" "$arm_id" "$repeat" "$method" "$seed_target" "$feature_bag" "$rc"
  echo "finish cell: $window_id $arm_id r$repeat rc=$rc"
}

mkdir -p "$RESULT_ROOT" "$TASK_TMP"
check_frozen_inputs

windows=(a02_4500_6300 a09_4000_4400 a09_6000_6800 a10_2400_2800 a10_4800_5200 h07_1660_1720 mclab1_s60_d15)
arms=(klt splg xfeat_seed)

for window_id in "${windows[@]}"; do
  if [[ -n "$RUN_ONLY_WINDOW" && "$RUN_ONLY_WINDOW" != "$window_id" ]]; then continue; fi
  for arm_id in "${arms[@]}"; do
    if [[ -n "$RUN_ONLY_ARM" && "$RUN_ONLY_ARM" != "$arm_id" ]]; then continue; fi
    for repeat in $(seq 1 "$REPEAT_COUNT"); do
      run_cell "$window_id" "$arm_id" "$repeat"
    done
  done
done

echo "all selected comparison cells attempted"
