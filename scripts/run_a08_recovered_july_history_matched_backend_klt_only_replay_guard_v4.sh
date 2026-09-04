#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

# Additive v4 replay-only guard: v3 stable-owner FD semantics plus one
# identity-pinned, bounded VINS lifecycle wrapper.  No exporter is reachable.

if [[ "$#" -ne 6 ]]; then
  echo "usage: $0 DATASET SEQ START END METHOD EVERY_N" >&2
  exit 64
fi

DATASET="$1"
SEQ="$2"
START="$3"
END="$4"
METHOD="$5"
EVERY_N="$6"

: "${A08_STRICT_REPLAY_ONLY_GUARD:?missing replay-only authorization}"
: "${A08_KLT_ONLY_REMAINING_REPLAYS_V4:?missing KLT-only v4 authorization}"
: "${A08_ITEM_ID:?missing item identity}"
: "${A08_ITEM_OUTPUT_DIR:?missing item output directory}"
: "${A08_WORKSPACE_LINK:?missing workspace link}"
: "${A08_OVERLAY_BACKEND_SHELL:?missing frozen overlay backend shell}"
: "${A08_ACCEPTED_FRONTEND_RECEIPT:?missing accepted KLT receipt binding}"
: "${A08_PRIOR_R01_DISPOSITION:?missing consumed R01 disposition}"
: "${A08_PRIOR_R02_DISPOSITION:?missing consumed R02 disposition}"
: "${A08_XFEAT_TERMINAL_DISPOSITION:?missing terminal XFeat disposition}"
: "${FEATURE_BAG_OVERRIDE:?missing accepted feature bag}"
: "${A08_FEATURE_BAG_SIZE_BYTES:?missing feature bag size}"
: "${A08_FEATURE_BAG_SHA256:?missing feature bag hash}"
: "${A08_FRONTEND_METRICS:?missing accepted frontend metrics}"
: "${A08_FRONTEND_METRICS_SIZE_BYTES:?missing frontend metrics size}"
: "${A08_FRONTEND_METRICS_SHA256:?missing frontend metrics hash}"
: "${A08_FRONTEND_CAMERA_CONFIG:?missing accepted camera config}"
: "${A08_FRONTEND_CAMERA_SIZE_BYTES:?missing camera config size}"
: "${A08_FRONTEND_CAMERA_SHA256:?missing camera config hash}"
: "${A08_RAW_BAG_SIZE_BYTES:?missing raw bag size}"
: "${A08_RAW_BAG_SHA256:?missing raw bag hash}"
: "${A08_RAW_TAR_SIZE_BYTES:?missing raw archive size}"
: "${A08_RAW_TAR_SHA256:?missing raw archive hash}"
: "${A08_GT_SIZE_BYTES:?missing ground-truth size}"
: "${A08_GT_SHA256:?missing ground-truth hash}"
: "${A08_VINS_LIFECYCLE_WRAPPER_V4:?missing lifecycle authorization}"
: "${A08_VINS_LIFECYCLE_WRAPPER_PATH:?missing lifecycle wrapper path}"
: "${A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES:?missing lifecycle wrapper size}"
: "${A08_VINS_LIFECYCLE_WRAPPER_SHA256:?missing lifecycle wrapper hash}"
: "${A08_REAL_VINS_NODE_BIN:?missing real VINS path}"
: "${A08_REAL_VINS_SIZE_BYTES:?missing real VINS size}"
: "${A08_REAL_VINS_SHA256:?missing real VINS hash}"
: "${A08_VINS_LIFECYCLE_START_MANIFEST:?missing lifecycle start manifest}"
: "${A08_VINS_LIFECYCLE_TERMINAL_MANIFEST:?missing lifecycle terminal manifest}"
: "${A08_UNBLOCKED_OVERLAY_EXEC_V4:?missing unblocked-overlay authorization}"
: "${A08_SIGNAL_MASK_LAUNCHER_PATH:?missing signal-mask launcher path}"
: "${A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES:?missing signal-mask launcher size}"
: "${A08_SIGNAL_MASK_LAUNCHER_SHA256:?missing signal-mask launcher hash}"
: "${A08_SIGNAL_MASK_MANIFEST:?missing signal-mask manifest}"
: "${A08_DELEGATED_BASH_PATH:?missing delegated Bash path}"
: "${A08_DELEGATED_BASH_SIZE_BYTES:?missing delegated Bash size}"
: "${A08_DELEGATED_BASH_SHA256:?missing delegated Bash hash}"
: "${A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES:?missing overlay shell size}"
: "${A08_OVERLAY_BACKEND_SHELL_SHA256:?missing overlay shell hash}"
: "${A08_PYTHON38_PATH:?missing Python 3.8 path}"
: "${A08_PYTHON38_SIZE_BYTES:?missing Python 3.8 size}"
: "${A08_PYTHON38_SHA256:?missing Python 3.8 hash}"
: "${A08_XFEAT_BACKEND_LAUNCHED_COUNT:?missing XFeat launch count}"
: "${A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED:?missing claim boundary}"

EXPECTED_RECEIPT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/frontends_v1/klt_attempt002_export_receipt_v1.json"
EXPECTED_BAG="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins/external_klt_every2_a08_recoveredjuly_hist0000_4660_klt_export_attempt002_rosseed_v1/features.bag"
EXPECTED_OUTPUT_ROOT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/backend_klt_only_remaining_replays_v4"
EXPECTED_WORKSPACE_ROOT="/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1/recovered_july_core_overlay_v1/logs/aqualoc_archaeo_vins"
EXPECTED_WRAPPER="/home/ma/AQUA-FE_WS/scripts/run_a08_vins_node_lifecycle_wrapper_v4.py"
EXPECTED_LAUNCHER="/home/ma/AQUA-FE_WS/scripts/run_a08_unblocked_overlay_exec_v4.py"
EXPECTED_REAL_VINS="/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"
EXPECTED_BASH="/usr/bin/bash"
EXPECTED_PYTHON38="/usr/bin/python3.8"

if [[ "$A08_STRICT_REPLAY_ONLY_GUARD" != "1" || \
      "$A08_KLT_ONLY_REMAINING_REPLAYS_V4" != "1" || \
      "$RUN_VINS" != "1" || "$FORCE_RAW" != "0" || \
      "$FORCE_EXPORT" != "0" || "$EXPORT_FEATURES" != "0" || \
      "$BACKEND_REPLAY_ONLY" != "0" || "$VINS_MULTIPLE_THREAD" != "0" || \
      "$PORT" != "11981" || "$A08_XFEAT_BACKEND_LAUNCHED_COUNT" != "0" || \
      "$A08_LEARNING_CONTRIBUTION_CLAIM_PERMITTED" != "0" ]]; then
  echo "A08 KLT-only v4 replay policy mismatch" >&2
  exit 65
fi
if [[ "$A08_PRIOR_R01_DISPOSITION" != \
      "NA_BACKEND_INFRASTRUCTURE_FD_INHERITANCE_FAILURE_NO_REPLAY_NO_REPLACEMENT" || \
      "$A08_PRIOR_R02_DISPOSITION" != \
      "NA_BACKEND_INFRASTRUCTURE_VINS_SIGTERM_CLEANUP_TIMEOUT_AFTER_COMPLETE_REPLAY_NO_REPLACEMENT" || \
      "$A08_XFEAT_TERMINAL_DISPOSITION" != \
      "NA_FRONTEND_STRUCTURAL_GATE_FAILED_NOT_LAUNCHED" ]]; then
  echo "A08 KLT-only v4 scientific boundary mismatch" >&2
  exit 65
fi
if [[ "$DATASET" != "aqualoc_archaeo" || "$SEQ" != "8" || \
      "$START" != "0" || "$END" != "4660" || "$EVERY_N" != "2" || \
      "$METHOD" != "klt" ]]; then
  echo "A08 KLT-only v4 history or method mismatch" >&2
  exit 65
fi
if [[ ! "$A08_ITEM_ID" =~ ^KLT_R0[3-5]$ ]]; then
  echo "A08 KLT-only v4 item mismatch" >&2
  exit 65
fi
REPEAT="${A08_ITEM_ID#KLT_R}"
EXPECTED_TAG="a08_recoveredjuly_hist0000_4660_backend_klt_only_r${REPEAT}_v4"
EXPECTED_OUTPUT="${EXPECTED_OUTPUT_ROOT}/${A08_ITEM_ID}"
EXPECTED_WORKSPACE="${EXPECTED_WORKSPACE_ROOT}/external_klt_every2_${EXPECTED_TAG}"
if [[ "$A08_ITEM_OUTPUT_DIR" != "$EXPECTED_OUTPUT" || \
      "$A08_WORKSPACE_LINK" != "$EXPECTED_WORKSPACE" || \
      "$TAG" != "$EXPECTED_TAG" ]]; then
  echo "A08 KLT-only v4 output namespace mismatch" >&2
  exit 65
fi
if [[ "$A08_ACCEPTED_FRONTEND_RECEIPT" != "$EXPECTED_RECEIPT" || \
      "$FEATURE_BAG_OVERRIDE" != "$EXPECTED_BAG" ]]; then
  echo "A08 KLT-only v4 accepted-input mismatch" >&2
  exit 65
fi
case "$FEATURE_BAG_OVERRIDE" in
  *hybrid_xfeat*|*probe*|*fallback*|*klt_safe_fallback*)
    echo "A08 KLT-only v4 forbidden XFeat/fallback input" >&2
    exit 65
    ;;
esac
if [[ "$A08_VINS_LIFECYCLE_WRAPPER_V4" != "1" || \
      "$VINS_NODE_BIN" != "$EXPECTED_WRAPPER" || \
      "$A08_VINS_LIFECYCLE_WRAPPER_PATH" != "$EXPECTED_WRAPPER" || \
      "$A08_REAL_VINS_NODE_BIN" != "$EXPECTED_REAL_VINS" ]]; then
  echo "A08 KLT-only v4 lifecycle executable mismatch" >&2
  exit 65
fi
if [[ "$A08_UNBLOCKED_OVERLAY_EXEC_V4" != "1" || \
      "$A08_SIGNAL_MASK_LAUNCHER_PATH" != "$EXPECTED_LAUNCHER" || \
      "$A08_DELEGATED_BASH_PATH" != "$EXPECTED_BASH" || \
      "$A08_PYTHON38_PATH" != "$EXPECTED_PYTHON38" ]]; then
  echo "A08 KLT-only v4 signal-mask launcher mismatch" >&2
  exit 65
fi
if [[ "$A08_VINS_LIFECYCLE_START_MANIFEST" != \
      "$EXPECTED_OUTPUT/vins_lifecycle_start_manifest_v4.json" || \
      "$A08_VINS_LIFECYCLE_TERMINAL_MANIFEST" != \
      "$EXPECTED_OUTPUT/vins_lifecycle_terminal_manifest_v4.json" ]]; then
  echo "A08 KLT-only v4 lifecycle manifest path mismatch" >&2
  exit 65
fi
if [[ "$A08_SIGNAL_MASK_MANIFEST" != \
      "$EXPECTED_OUTPUT/overlay_signal_mask_manifest_v4.json" ]]; then
  echo "A08 KLT-only v4 signal-mask manifest path mismatch" >&2
  exit 65
fi
if [[ ! -d "$A08_ITEM_OUTPUT_DIR" || -L "$A08_ITEM_OUTPUT_DIR" || \
      ! -L "$A08_WORKSPACE_LINK" || \
      "$(/usr/bin/readlink -f -- "$A08_WORKSPACE_LINK")" != \
      "$A08_ITEM_OUTPUT_DIR" ]]; then
  echo "A08 KLT-only v4 evidence workspace binding mismatch" >&2
  exit 65
fi
if [[ ! -f "$A08_OVERLAY_BACKEND_SHELL" || \
      -L "$A08_OVERLAY_BACKEND_SHELL" ]]; then
  echo "A08 frozen overlay backend shell unavailable" >&2
  exit 65
fi

verify_path() {
  local path="$1"
  local expected_size="$2"
  local expected_sha="$3"
  local label="$4"
  local observed_size observed_sha
  observed_size="$(/usr/bin/stat -Lc '%s' -- "$path")"
  observed_sha="$(/usr/bin/sha256sum -- "$path")"
  observed_sha="${observed_sha%% *}"
  if [[ "$observed_size" != "$expected_size" || \
        "$observed_sha" != "$expected_sha" ]]; then
    echo "A08 identity mismatch: $label" >&2
    exit 65
  fi
}

verify_path "$EXPECTED_WRAPPER" "$A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES" \
  "$A08_VINS_LIFECYCLE_WRAPPER_SHA256" lifecycle_wrapper
verify_path "$EXPECTED_LAUNCHER" "$A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES" \
  "$A08_SIGNAL_MASK_LAUNCHER_SHA256" signal_mask_launcher
verify_path "$EXPECTED_REAL_VINS" "$A08_REAL_VINS_SIZE_BYTES" \
  "$A08_REAL_VINS_SHA256" real_vins_binary
verify_path "$EXPECTED_BASH" "$A08_DELEGATED_BASH_SIZE_BYTES" \
  "$A08_DELEGATED_BASH_SHA256" delegated_bash
verify_path "$EXPECTED_PYTHON38" "$A08_PYTHON38_SIZE_BYTES" \
  "$A08_PYTHON38_SHA256" python38
verify_path "$A08_OVERLAY_BACKEND_SHELL" \
  "$A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES" \
  "$A08_OVERLAY_BACKEND_SHELL_SHA256" frozen_overlay_backend_shell

ACCEPTED_FEATURE_BAG="$FEATURE_BAG_OVERRIDE"
ACCEPTED_RAW_BAG="$RAW_BAG"
ACCEPTED_RAW_TAR="$RAW_TAR"
ACCEPTED_GT="$GT_TXT"
ACCEPTED_METRICS="$A08_FRONTEND_METRICS"
ACCEPTED_CAMERA="$A08_FRONTEND_CAMERA_CONFIG"

exec 6<"$ACCEPTED_GT"
exec 7<"$ACCEPTED_RAW_BAG"
exec 8<"$ACCEPTED_RAW_TAR"
exec 9<"$ACCEPTED_FEATURE_BAG"
exec 10<"$ACCEPTED_METRICS"
exec 11<"$ACCEPTED_CAMERA"

export A08_SEALED_FD_OWNER_PID="$BASHPID"
OWNER_PREFIX="/proc/${A08_SEALED_FD_OWNER_PID}/fd"

METRICS_COPY="$A08_WORKSPACE_LINK/frontend_metrics.csv"
if [[ -e "$METRICS_COPY" || -L "$METRICS_COPY" ]]; then
  echo "A08 frontend metrics destination already exists" >&2
  exit 73
fi
/usr/bin/cp -- "${OWNER_PREFIX}/10" "$METRICS_COPY"
verify_path "$METRICS_COPY" "$A08_FRONTEND_METRICS_SIZE_BYTES" \
  "$A08_FRONTEND_METRICS_SHA256" frontend_metrics_copy

GUARD_MANIFEST="$A08_WORKSPACE_LINK/replay_only_guard_manifest.json"
/usr/bin/python3.8 -I - "$GUARD_MANIFEST" "$METHOD" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

target = Path(sys.argv[1])
method = sys.argv[2]
owner_pid = int(os.environ["A08_SEALED_FD_OWNER_PID"])
if owner_pid != os.getppid() or owner_pid <= 1:
    raise SystemExit("stable FD owner is not the manifest writer parent")

def digest_fd(fd):
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, 8 * 1024 * 1024)
        if not block:
            break
        digest.update(block)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()

def bound_input(label, path_key, size_key, sha_key, fd):
    expected_size = int(os.environ[size_key])
    expected_sha = os.environ[sha_key]
    observed = os.fstat(fd)
    owner_path = f"/proc/{owner_pid}/fd/{fd}"
    owner_descriptor = os.open(owner_path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        owner_observed = os.fstat(owner_descriptor)
    finally:
        os.close(owner_descriptor)
    if observed.st_size != expected_size or digest_fd(fd) != expected_sha:
        raise SystemExit("guard descriptor identity changed: " + label)
    if (
        owner_observed.st_size != expected_size
        or owner_observed.st_dev != observed.st_dev
        or owner_observed.st_ino != observed.st_ino
    ):
        raise SystemExit("stable owner path identity changed: " + label)
    return {
        "accepted_path": os.environ[path_key],
        "size_bytes": expected_size,
        "sha256": expected_sha,
        "sealed_fd": fd,
        "sealed_fd_owner_pid": owner_pid,
        "sealed_path": owner_path,
        "device": int(observed.st_dev),
        "inode": int(observed.st_ino),
        "stable_owner_path_verified_before_delegate": True,
    }

payload = {
    "schema_version": "aqua-fe-a08-replay-only-stable-owner-fd-guard-v4",
    "status": "PASS_BEFORE_DELEGATED_BACKEND",
    "item_id": os.environ["A08_ITEM_ID"],
    "history": {
        "dataset": "aqualoc_archaeo", "sequence": 8,
        "start_source_index": 0, "end_source_index": 4660,
        "every_n": 2, "method": method,
    },
    "output_dir": os.environ["A08_ITEM_OUTPUT_DIR"],
    "workspace_link": os.environ["A08_WORKSPACE_LINK"],
    "delegated_backend_shell": os.environ["A08_OVERLAY_BACKEND_SHELL"],
    "sealed_fd_owner_pid": owner_pid,
    "policy": {
        "frontend_export_permitted": False,
        "raw_reconstruction_permitted": False,
        "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
        "delegated_data_environment_values_are_stable_owner_fd_paths": True,
        "all_delegated_data_paths_are_stable_owner_fd_paths": True,
        "child_self_fd_paths_forbidden": True,
        "owner_remains_alive_during_delegated_backend": True,
        "published_before_delegated_backend": True,
        "bounded_vins_lifecycle_wrapper_required": True,
    },
    "prior_dispositions": {
        "KLT_R01": os.environ["A08_PRIOR_R01_DISPOSITION"],
        "KLT_R02": os.environ["A08_PRIOR_R02_DISPOSITION"],
    },
    "vins_lifecycle": {
        "wrapper": {
            "path": os.environ["A08_VINS_LIFECYCLE_WRAPPER_PATH"],
            "size_bytes": int(os.environ["A08_VINS_LIFECYCLE_WRAPPER_SIZE_BYTES"]),
            "sha256": os.environ["A08_VINS_LIFECYCLE_WRAPPER_SHA256"],
        },
        "real_vins_binary": {
            "path": os.environ["A08_REAL_VINS_NODE_BIN"],
            "size_bytes": int(os.environ["A08_REAL_VINS_SIZE_BYTES"]),
            "sha256": os.environ["A08_REAL_VINS_SHA256"],
        },
        "start_manifest": os.environ["A08_VINS_LIFECYCLE_START_MANIFEST"],
        "terminal_manifest": os.environ["A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"],
        "real_child_launch_count": 1,
        "automatic_restart_count": 0,
        "maximum_shutdown_seconds": 3.5,
    },
    "signal_mask_launcher": {
        "launcher": {
            "path": os.environ["A08_SIGNAL_MASK_LAUNCHER_PATH"],
            "size_bytes": int(os.environ["A08_SIGNAL_MASK_LAUNCHER_SIZE_BYTES"]),
            "sha256": os.environ["A08_SIGNAL_MASK_LAUNCHER_SHA256"],
        },
        "python38": {
            "path": os.environ["A08_PYTHON38_PATH"],
            "size_bytes": int(os.environ["A08_PYTHON38_SIZE_BYTES"]),
            "sha256": os.environ["A08_PYTHON38_SHA256"],
        },
        "delegated_bash": {
            "path": os.environ["A08_DELEGATED_BASH_PATH"],
            "size_bytes": int(os.environ["A08_DELEGATED_BASH_SIZE_BYTES"]),
            "sha256": os.environ["A08_DELEGATED_BASH_SHA256"],
        },
        "frozen_overlay_shell": {
            "path": os.environ["A08_OVERLAY_BACKEND_SHELL"],
            "size_bytes": int(os.environ["A08_OVERLAY_BACKEND_SHELL_SIZE_BYTES"]),
            "sha256": os.environ["A08_OVERLAY_BACKEND_SHELL_SHA256"],
        },
        "manifest": os.environ["A08_SIGNAL_MASK_MANIFEST"],
        "unblocked_before_overlay_exec": [1, 2, 15],
        "exec_replaces_launcher_process": True,
    },
    "bound_inputs": {
        "ground_truth": bound_input(
            "ground_truth", "GT_TXT", "A08_GT_SIZE_BYTES", "A08_GT_SHA256", 6
        ),
        "raw_bag": bound_input(
            "raw_bag", "RAW_BAG", "A08_RAW_BAG_SIZE_BYTES", "A08_RAW_BAG_SHA256", 7
        ),
        "raw_archive": bound_input(
            "raw_archive", "RAW_TAR", "A08_RAW_TAR_SIZE_BYTES", "A08_RAW_TAR_SHA256", 8
        ),
        "feature_bag": bound_input(
            "feature_bag", "FEATURE_BAG_OVERRIDE", "A08_FEATURE_BAG_SIZE_BYTES",
            "A08_FEATURE_BAG_SHA256", 9
        ),
        "frontend_metrics": bound_input(
            "frontend_metrics", "A08_FRONTEND_METRICS",
            "A08_FRONTEND_METRICS_SIZE_BYTES", "A08_FRONTEND_METRICS_SHA256", 10
        ),
        "camera_config": bound_input(
            "camera_config", "A08_FRONTEND_CAMERA_CONFIG",
            "A08_FRONTEND_CAMERA_SIZE_BYTES", "A08_FRONTEND_CAMERA_SHA256", 11
        ),
    },
}
data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
descriptor = os.open(str(target), flags, 0o444)
try:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RuntimeError("guard manifest write made no progress")
        view = view[written:]
    os.fsync(descriptor)
finally:
    os.close(descriptor)
directory = os.open(str(target.parent), os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
PY

export RAW_BAG="${OWNER_PREFIX}/7"
export RAW_TAR="${OWNER_PREFIX}/8"
export GT_TXT="${OWNER_PREFIX}/6"
export FEATURE_BAG_OVERRIDE="${OWNER_PREFIX}/9"
export A08_FRONTEND_METRICS="${OWNER_PREFIX}/10"
export A08_FRONTEND_CAMERA_CONFIG="${OWNER_PREFIX}/11"

set +e
"$A08_PYTHON38_PATH" "$A08_SIGNAL_MASK_LAUNCHER_PATH" \
  "$DATASET" "$SEQ" "$START" "$END" "$METHOD" "$EVERY_N"
BACKEND_RETURN_CODE="$?"
set -e

if [[ ! -f "$A08_VINS_LIFECYCLE_START_MANIFEST" || \
      -L "$A08_VINS_LIFECYCLE_START_MANIFEST" || \
      ! -f "$A08_VINS_LIFECYCLE_TERMINAL_MANIFEST" || \
      -L "$A08_VINS_LIFECYCLE_TERMINAL_MANIFEST" ]]; then
  echo "A08 v4 lifecycle manifest missing after backend" >&2
  exit 70
fi
if [[ ! -f "$A08_SIGNAL_MASK_MANIFEST" || \
      -L "$A08_SIGNAL_MASK_MANIFEST" ]]; then
  echo "A08 v4 signal-mask manifest missing after backend" >&2
  exit 70
fi

REPLAY_MANIFEST="$A08_WORKSPACE_LINK/replay_manifest.txt"
if [[ ! -f "$REPLAY_MANIFEST" || -L "$REPLAY_MANIFEST" ]]; then
  if [[ "$BACKEND_RETURN_CODE" -ne 0 ]]; then
    exit "$BACKEND_RETURN_CODE"
  fi
  echo "A08 replay manifest missing after backend" >&2
  exit 70
fi
{
  printf 'accepted_feature_bag=%s\n' "$ACCEPTED_FEATURE_BAG"
  printf 'accepted_feature_bag_size_bytes=%s\n' "$A08_FEATURE_BAG_SIZE_BYTES"
  printf 'accepted_feature_bag_sha256=%s\n' "$A08_FEATURE_BAG_SHA256"
  printf 'sealed_play_bag=%s\n' "${OWNER_PREFIX}/9"
  printf 'sealed_fd_owner_pid=%s\n' "$A08_SEALED_FD_OWNER_PID"
  printf 'stable_owner_fd_guard=1\n'
  printf 'bounded_vins_lifecycle_wrapper_v4=1\n'
  printf 'unblocked_overlay_exec_v4=1\n'
  printf 'overlay_signal_mask_manifest=%s\n' "$A08_SIGNAL_MASK_MANIFEST"
  printf 'vins_lifecycle_start_manifest=%s\n' "$A08_VINS_LIFECYCLE_START_MANIFEST"
  printf 'vins_lifecycle_terminal_manifest=%s\n' "$A08_VINS_LIFECYCLE_TERMINAL_MANIFEST"
  printf 'strict_replay_only_fd_guard=1\n'
  printf 'delegated_backend_return_code=%s\n' "$BACKEND_RETURN_CODE"
} >> "$REPLAY_MANIFEST"
exit "$BACKEND_RETURN_CODE"
