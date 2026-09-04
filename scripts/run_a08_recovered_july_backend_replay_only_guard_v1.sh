#!/usr/bin/env bash
set -euo pipefail
set -o noclobber

# A08 backend-only guard.  It opens and verifies every upstream file before
# delegating to the frozen recovered-July shell, then exposes only inherited
# /proc/self/fd handles.  Consequently the delegated shell cannot reconstruct
# a missing raw bag or export a missing feature bag back into accepted evidence.

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
: "${A08_ITEM_ID:?missing item identity}"
: "${A08_ITEM_OUTPUT_DIR:?missing item output directory}"
: "${A08_WORKSPACE_LINK:?missing workspace link}"
: "${A08_OVERLAY_BACKEND_SHELL:?missing frozen overlay backend shell}"
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

if [[ "$A08_STRICT_REPLAY_ONLY_GUARD" != "1" || "$RUN_VINS" != "1" || \
      "$FORCE_RAW" != "0" || "$FORCE_EXPORT" != "0" || \
      "$EXPORT_FEATURES" != "0" || "$BACKEND_REPLAY_ONLY" != "0" || \
      "$VINS_MULTIPLE_THREAD" != "0" || "$PORT" != "11981" ]]; then
  echo "A08 backend-only policy mismatch" >&2
  exit 65
fi
if [[ "$DATASET" != "aqualoc_archaeo" || "$SEQ" != "8" || \
      "$START" != "0" || "$END" != "4660" || "$EVERY_N" != "2" ]]; then
  echo "A08 replay history mismatch" >&2
  exit 65
fi
case "$METHOD" in
  klt|hybrid_xfeat) ;;
  *) echo "A08 replay method mismatch" >&2; exit 65 ;;
esac
if [[ ! -d "$A08_ITEM_OUTPUT_DIR" || -L "$A08_ITEM_OUTPUT_DIR" || \
      ! -L "$A08_WORKSPACE_LINK" || \
      "$(/usr/bin/readlink -f -- "$A08_WORKSPACE_LINK")" != "$A08_ITEM_OUTPUT_DIR" ]]; then
  echo "A08 evidence workspace binding mismatch" >&2
  exit 65
fi
if [[ ! -f "$A08_OVERLAY_BACKEND_SHELL" || -L "$A08_OVERLAY_BACKEND_SHELL" ]]; then
  echo "A08 frozen overlay backend shell unavailable" >&2
  exit 65
fi

verify_fd() {
  local fd_path="$1"
  local expected_size="$2"
  local expected_sha="$3"
  local label="$4"
  local observed_size observed_sha
  observed_size="$(/usr/bin/stat -Lc '%s' -- "$fd_path")"
  observed_sha="$(/usr/bin/sha256sum -- "$fd_path")"
  observed_sha="${observed_sha%% *}"
  if [[ "$observed_size" != "$expected_size" || "$observed_sha" != "$expected_sha" ]]; then
    echo "A08 sealed input identity mismatch: $label" >&2
    exit 65
  fi
}

ACCEPTED_FEATURE_BAG="$FEATURE_BAG_OVERRIDE"
ACCEPTED_RAW_BAG="$RAW_BAG"
ACCEPTED_RAW_TAR="$RAW_TAR"
ACCEPTED_GT="$GT_TXT"

# Fixed descriptors are intentionally inherited by every descendant.  A name
# disappearing after this point cannot redirect replay to another inode.
exec 6<"$ACCEPTED_GT"
exec 7<"$ACCEPTED_RAW_BAG"
exec 8<"$ACCEPTED_RAW_TAR"
exec 9<"$ACCEPTED_FEATURE_BAG"
exec 10<"$A08_FRONTEND_METRICS"
exec 11<"$A08_FRONTEND_CAMERA_CONFIG"

METRICS_COPY="$A08_WORKSPACE_LINK/frontend_metrics.csv"
if [[ -e "$METRICS_COPY" || -L "$METRICS_COPY" ]]; then
  echo "A08 frontend metrics destination already exists" >&2
  exit 73
fi
/usr/bin/cp -- /proc/self/fd/10 "$METRICS_COPY"
verify_fd "$METRICS_COPY" "$A08_FRONTEND_METRICS_SIZE_BYTES" "$A08_FRONTEND_METRICS_SHA256" frontend_metrics_copy

GUARD_MANIFEST="$A08_WORKSPACE_LINK/replay_only_guard_manifest.json"
/usr/bin/python3.8 -I - "$GUARD_MANIFEST" "$METHOD" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import sys

target = Path(sys.argv[1])
method = sys.argv[2]

def bound_input(label, path_key, size_key, sha_key, fd):
    expected_size = int(os.environ[size_key])
    expected_sha = os.environ[sha_key]
    observed = os.fstat(fd)
    if observed.st_size != expected_size:
        raise SystemExit("guard fstat size changed: " + label)
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        block = os.read(fd, 8 * 1024 * 1024)
        if not block:
            break
        digest.update(block)
    os.lseek(fd, 0, os.SEEK_SET)
    if digest.hexdigest() != expected_sha:
        raise SystemExit("guard fd hash changed: " + label)
    return {
        "accepted_path": os.environ[path_key],
        "size_bytes": expected_size,
        "sha256": expected_sha,
        "sealed_fd": fd,
        "sealed_path": "/proc/self/fd/" + str(fd),
        "device": int(observed.st_dev),
        "inode": int(observed.st_ino),
    }

payload = {
    "schema_version": "aqua-fe-a08-replay-only-fd-guard-v1",
    "status": "PASS_BEFORE_DELEGATED_BACKEND",
    "item_id": os.environ["A08_ITEM_ID"],
    "history": {
        "dataset": "aqualoc_archaeo",
        "sequence": 8,
        "start_source_index": 0,
        "end_source_index": 4660,
        "every_n": 2,
        "method": method,
    },
    "output_dir": os.environ["A08_ITEM_OUTPUT_DIR"],
    "workspace_link": os.environ["A08_WORKSPACE_LINK"],
    "delegated_backend_shell": os.environ["A08_OVERLAY_BACKEND_SHELL"],
    "policy": {
        "frontend_export_permitted": False,
        "raw_reconstruction_permitted": False,
        "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
        "delegated_data_environment_values_are_inherited_fds": True,
        "all_delegated_data_paths_are_inherited_fds": True,
        "published_before_delegated_backend": True,
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
            "frontend_metrics", "A08_FRONTEND_METRICS", "A08_FRONTEND_METRICS_SIZE_BYTES",
            "A08_FRONTEND_METRICS_SHA256", 10
        ),
        "camera_config": bound_input(
            "camera_config", "A08_FRONTEND_CAMERA_CONFIG", "A08_FRONTEND_CAMERA_SIZE_BYTES",
            "A08_FRONTEND_CAMERA_SHA256", 11
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

export RAW_BAG=/proc/self/fd/7
export RAW_TAR=/proc/self/fd/8
export GT_TXT=/proc/self/fd/6
export FEATURE_BAG_OVERRIDE=/proc/self/fd/9
export A08_FRONTEND_METRICS=/proc/self/fd/10
export A08_FRONTEND_CAMERA_CONFIG=/proc/self/fd/11

set +e
/usr/bin/bash "$A08_OVERLAY_BACKEND_SHELL" "$DATASET" "$SEQ" "$START" "$END" "$METHOD" "$EVERY_N"
BACKEND_RETURN_CODE="$?"
set -e

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
  printf 'sealed_play_bag=/proc/self/fd/9\n'
  printf 'strict_replay_only_fd_guard=1\n'
  printf 'delegated_backend_return_code=%s\n' "$BACKEND_RETURN_CODE"
} >> "$REPLAY_MANIFEST"
exit "$BACKEND_RETURN_CODE"
