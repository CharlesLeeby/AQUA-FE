#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "usage: $0 DATASET_DIR TIMES_FILE CONFIG FULL_SEEDS DROP_SEEDS OUTPUT_ROOT TAG FIRST_REPEAT LAST_REPEAT" >&2
  exit 2
fi

DATASET_DIR="$(realpath "$1")"
TIMES_FILE="$(realpath "$2")"
CONFIG="$(realpath "$3")"
FULL_SEEDS="$(realpath "$4")"
DROP_SEEDS="$(realpath "$5")"
OUTPUT_ROOT="$(realpath -m "$6")"
TAG="$7"
FIRST_REPEAT="$8"
LAST_REPEAT="$9"
RUNNER_PATH="$(realpath "$0")"

ORB_ROOT="${ORB_ROOT:-/home/ma/SLAM/orb_slam3_seed_ws/src/ORB_SLAM3-seeded}"
BINARY="$ORB_ROOT/Examples_old/Monocular/mono_euroc_old"
VOCABULARY="$ORB_ROOT/Vocabulary/ORBvoc.txt"
SEED_AUDIT_ENABLED="${ORB_SLAM3_ENABLE_SEED_AUDIT:-0}"
SEED_AUDIT_MAX_EVENTS="${ORB_SLAM3_SEED_AUDIT_MAX_EVENTS:-65536}"
LINEAGE_BRIDGE_ENABLED="${ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE:-0}"
LINEAGE_MIN_QUALITY="${ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY:-0.0}"
LINEAGE_MAX_PROJECTION_ERROR_PX="${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX:-4.0}"
LINEAGE_MAX_DESCRIPTOR_DISTANCE="${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE:-100}"
LINEAGE_CULL_GRACE_KEYFRAMES="${ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES:-0}"
LINEAGE_MAX_ASSISTED_MATCHES="${ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES:-0}"
LINEAGE_NATIVE_BIRTH_ONLY="${ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY:-0}"
LINEAGE_QUARANTINE_ON_OUTLIER="${ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER:-0}"
LINEAGE_TERMINAL_QUARANTINE="${ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE:-0}"
LINEAGE_QUARANTINE_ENFORCE="${ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE:-$LINEAGE_QUARANTINE_ON_OUTLIER}"
LINEAGE_PRE_KF_OUTLIER_PURGE="${ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE:-0}"
LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE="${ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE:-$LINEAGE_PRE_KF_OUTLIER_PURGE}"
CPU_AFFINITY="${ORB_SLAM3_CPU_AFFINITY:-}"
SYNCHRONIZE_LOCAL_MAPPING="${ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING:-0}"
LOCAL_MAPPING_IDLE_TIMEOUT_SEC="${ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC:-60}"
SYNCHRONIZE_LOOP_CLOSING="${ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING:-0}"
LOOP_CLOSING_IDLE_TIMEOUT_SEC="${ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC:-60}"
DETERMINISTIC_BACKGROUND_GATE="${ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE:-0}"
DISABLE_ASLR="${ORB_SLAM3_DISABLE_ASLR:-0}"
EXPORT_ONLINE_TRAJECTORY="${ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY:-0}"
MACHINE_ARCH="$(uname -m)"

if [[ "$SEED_AUDIT_ENABLED" != "0" && "$SEED_AUDIT_ENABLED" != "1" ]]; then
  echo "ORB_SLAM3_ENABLE_SEED_AUDIT must be 0 or 1" >&2
  exit 2
fi
if [[ ! "$SEED_AUDIT_MAX_EVENTS" =~ ^[0-9]+$ || "$SEED_AUDIT_MAX_EVENTS" -lt 1024 ]]; then
  echo "ORB_SLAM3_SEED_AUDIT_MAX_EVENTS must be an integer >= 1024" >&2
  exit 2
fi
if [[ "$LINEAGE_BRIDGE_ENABLED" != "0" && "$LINEAGE_BRIDGE_ENABLED" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE must be 0 or 1" >&2
  exit 2
fi
if [[ ! "$LINEAGE_CULL_GRACE_KEYFRAMES" =~ ^[0-9]+$ || "$LINEAGE_CULL_GRACE_KEYFRAMES" -gt 100 ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES must be an integer in [0, 100]" >&2
  exit 2
fi
if [[ ! "$LINEAGE_MAX_ASSISTED_MATCHES" =~ ^[0-9]+$ ||
      "$LINEAGE_MAX_ASSISTED_MATCHES" -gt 100000 ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES must be an integer in [0, 100000]" >&2
  exit 2
fi
if [[ "$LINEAGE_NATIVE_BIRTH_ONLY" != "0" && "$LINEAGE_NATIVE_BIRTH_ONLY" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_QUARANTINE_ON_OUTLIER" != "0" &&
      "$LINEAGE_QUARANTINE_ON_OUTLIER" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_TERMINAL_QUARANTINE" != "0" &&
      "$LINEAGE_TERMINAL_QUARANTINE" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_TERMINAL_QUARANTINE" == "1" &&
      "$LINEAGE_QUARANTINE_ON_OUTLIER" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE requires ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER=1" >&2
  exit 2
fi
if [[ "$LINEAGE_QUARANTINE_ENFORCE" != "0" &&
      "$LINEAGE_QUARANTINE_ENFORCE" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_QUARANTINE_ENFORCE" == "1" &&
      "$LINEAGE_QUARANTINE_ON_OUTLIER" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE requires ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER=1" >&2
  exit 2
fi
if [[ "$LINEAGE_PRE_KF_OUTLIER_PURGE" != "0" &&
      "$LINEAGE_PRE_KF_OUTLIER_PURGE" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE" != "0" &&
      "$LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE must be 0 or 1" >&2
  exit 2
fi
if [[ "$LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE" == "1" &&
      "$LINEAGE_PRE_KF_OUTLIER_PURGE" != "1" ]]; then
  echo "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE requires ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE=1" >&2
  exit 2
fi
if [[ -n "$CPU_AFFINITY" ]]; then
  if [[ ! "$CPU_AFFINITY" =~ ^[0-9]+$ ]]; then
    echo "ORB_SLAM3_CPU_AFFINITY must be a single non-negative CPU index" >&2
    exit 2
  fi
  if ! command -v taskset >/dev/null 2>&1; then
    echo "ORB_SLAM3_CPU_AFFINITY requires taskset" >&2
    exit 2
  fi
  if ! taskset -c "$CPU_AFFINITY" true >/dev/null 2>&1; then
    echo "ORB_SLAM3_CPU_AFFINITY is unavailable: $CPU_AFFINITY" >&2
    exit 2
  fi
fi
if [[ "$SYNCHRONIZE_LOCAL_MAPPING" != "0" && "$SYNCHRONIZE_LOCAL_MAPPING" != "1" ]]; then
  echo "ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING must be 0 or 1" >&2
  exit 2
fi
if [[ "$SYNCHRONIZE_LOOP_CLOSING" != "0" && "$SYNCHRONIZE_LOOP_CLOSING" != "1" ]]; then
  echo "ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING must be 0 or 1" >&2
  exit 2
fi
if [[ "$SYNCHRONIZE_LOOP_CLOSING" == "1" && "$SYNCHRONIZE_LOCAL_MAPPING" != "1" ]]; then
  echo "ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING requires ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING=1" >&2
  exit 2
fi
if [[ "$DETERMINISTIC_BACKGROUND_GATE" != "0" && "$DETERMINISTIC_BACKGROUND_GATE" != "1" ]]; then
  echo "ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE must be 0 or 1" >&2
  exit 2
fi
if [[ "$DETERMINISTIC_BACKGROUND_GATE" == "1" &&
      ( "$SYNCHRONIZE_LOCAL_MAPPING" != "1" || "$SYNCHRONIZE_LOOP_CLOSING" != "1" ) ]]; then
  echo "ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE requires both background synchronization barriers" >&2
  exit 2
fi
if [[ "$DISABLE_ASLR" != "0" && "$DISABLE_ASLR" != "1" ]]; then
  echo "ORB_SLAM3_DISABLE_ASLR must be 0 or 1" >&2
  exit 2
fi
if [[ "$EXPORT_ONLINE_TRAJECTORY" != "0" && "$EXPORT_ONLINE_TRAJECTORY" != "1" ]]; then
  echo "ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY must be 0 or 1" >&2
  exit 2
fi
if [[ "$DISABLE_ASLR" == "1" ]]; then
  if ! command -v setarch >/dev/null 2>&1; then
    echo "ORB_SLAM3_DISABLE_ASLR requires setarch" >&2
    exit 2
  fi
  if ! setarch "$MACHINE_ARCH" -R true >/dev/null 2>&1; then
    echo "ORB_SLAM3_DISABLE_ASLR is unavailable for architecture $MACHINE_ARCH" >&2
    exit 2
  fi
fi
python3 - "$LINEAGE_MIN_QUALITY" "$LINEAGE_MAX_PROJECTION_ERROR_PX" \
  "$LINEAGE_MAX_DESCRIPTOR_DISTANCE" "$LOCAL_MAPPING_IDLE_TIMEOUT_SEC" \
  "$LOOP_CLOSING_IDLE_TIMEOUT_SEC" <<'PY'
import math
import sys

try:
    min_quality = float(sys.argv[1])
    max_projection_error = float(sys.argv[2])
    max_descriptor_distance = int(sys.argv[3])
    local_mapping_idle_timeout = float(sys.argv[4])
    loop_closing_idle_timeout = float(sys.argv[5])
except ValueError as exc:
    raise SystemExit(f"invalid ORB lineage bridge parameter: {exc}")
if not math.isfinite(min_quality) or not 0.0 <= min_quality <= 1.0:
    raise SystemExit("ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY must be in [0, 1]")
if not math.isfinite(max_projection_error) or not 0.1 <= max_projection_error <= 100.0:
    raise SystemExit(
        "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX must be in [0.1, 100]"
    )
if not 0 <= max_descriptor_distance <= 100:
    raise SystemExit(
        "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE must be in [0, 100]"
    )
if not math.isfinite(local_mapping_idle_timeout) or not 0.1 <= local_mapping_idle_timeout <= 600.0:
    raise SystemExit(
        "ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC must be in [0.1, 600]"
    )
if not math.isfinite(loop_closing_idle_timeout) or not 0.1 <= loop_closing_idle_timeout <= 600.0:
    raise SystemExit(
        "ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC must be in [0.1, 600]"
    )
PY

for required in "$BINARY" "$VOCABULARY" "$CONFIG" "$TIMES_FILE" "$FULL_SEEDS" "$DROP_SEEDS"; do
  if [[ ! -e "$required" ]]; then
    echo "missing required input: $required" >&2
    exit 2
  fi
done

ldd_output="$(ldd "$BINARY" 2>&1 || true)"
ldd_library_path="$({ printf '%s\n' "$ldd_output" | awk '
  $1 == "libORB_SLAM3.so" && $2 == "=>" {
    if ($3 == "not") print "__NOT_FOUND__";
    else print $3;
    exit;
  }
  $1 ~ /(^|\/)libORB_SLAM3[.]so$/ { print $1; exit; }
'; } || true)"
library_override="${ORB_SLAM3_LIBRARY_PATH:-}"
if [[ "$ldd_library_path" == "__NOT_FOUND__" ]]; then
  echo "ldd could not resolve libORB_SLAM3.so for $BINARY" >&2
  exit 2
fi
if [[ -n "$ldd_library_path" ]]; then
  if [[ ! -f "$ldd_library_path" ]]; then
    echo "ldd resolved missing libORB_SLAM3.so: $ldd_library_path" >&2
    exit 2
  fi
  LIBORB_SLAM3_PATH="$(realpath "$ldd_library_path")"
  LIBORB_SLAM3_RESOLUTION="ldd"
  if [[ -n "$library_override" ]]; then
    if [[ ! -f "$library_override" ]]; then
      echo "ORB_SLAM3_LIBRARY_PATH is not a file: $library_override" >&2
      exit 2
    fi
    override_path="$(realpath "$library_override")"
    if [[ "$override_path" != "$LIBORB_SLAM3_PATH" ]]; then
      echo "ORB_SLAM3_LIBRARY_PATH disagrees with ldd: override=$override_path ldd=$LIBORB_SLAM3_PATH" >&2
      exit 2
    fi
  fi
elif [[ -n "$library_override" ]]; then
  binary_magic="$(od -An -tx1 -N4 "$BINARY" | tr -d '[:space:]')"
  if [[ "$binary_magic" == "7f454c46" ]]; then
    echo "refusing ORB_SLAM3_LIBRARY_PATH fallback for ELF binary without an ldd-resolved libORB_SLAM3.so: $BINARY" >&2
    exit 2
  fi
  if [[ ! -f "$library_override" ]]; then
    echo "ORB_SLAM3_LIBRARY_PATH is not a file: $library_override" >&2
    exit 2
  fi
  LIBORB_SLAM3_PATH="$(realpath "$library_override")"
  LIBORB_SLAM3_RESOLUTION="override"
else
  echo "ldd did not report libORB_SLAM3.so for $BINARY; set ORB_SLAM3_LIBRARY_PATH only for an explicit non-ELF test fixture" >&2
  exit 2
fi
LIBORB_SLAM3_SHA256="$(sha256sum "$LIBORB_SLAM3_PATH" | awk '{print $1}')"

EXTERNAL_SEED_AUDIT_SOURCE="$ORB_ROOT/src/ExternalSeedAudit.cc"
EXTERNAL_SEED_AUDIT_SOURCE_SHA256=""
if [[ -f "$EXTERNAL_SEED_AUDIT_SOURCE" ]]; then
  EXTERNAL_SEED_AUDIT_SOURCE="$(realpath "$EXTERNAL_SEED_AUDIT_SOURCE")"
  EXTERNAL_SEED_AUDIT_SOURCE_SHA256="$(sha256sum "$EXTERNAL_SEED_AUDIT_SOURCE" | awk '{print $1}')"
else
  EXTERNAL_SEED_AUDIT_SOURCE=""
fi

MECHANISM_SOURCE_PATHS=(
  "Examples_old/Monocular/mono_euroc.cc"
  "include/ExternalSeedAudit.h"
  "include/Frame.h"
  "include/KeyFrame.h"
  "include/LocalMapping.h"
  "include/LoopClosing.h"
  "include/MapPoint.h"
  "include/Optimizer.h"
  "include/ORBextractor.h"
  "include/ORBmatcher.h"
  "include/System.h"
  "include/Tracking.h"
  "src/ExternalSeedAudit.cc"
  "src/Frame.cc"
  "src/KeyFrame.cc"
  "src/LocalMapping.cc"
  "src/LoopClosing.cc"
  "src/MapPoint.cc"
  "src/Optimizer.cc"
  "src/ORBextractor.cc"
  "src/ORBmatcher.cc"
  "src/System.cc"
  "src/Tracking.cc"
)

VOCABULARY_SHA256="$(sha256sum "$VOCABULARY" | awk '{print $1}')"
RUNNER_SHA256="$(sha256sum "$RUNNER_PATH" | awk '{print $1}')"

mkdir -p "$OUTPUT_ROOT"
RUNTIME_ALIAS_ROOT="$(dirname "$OUTPUT_ROOT")/.$(basename "$OUTPUT_ROOT").runtime"
mkdir -p "$RUNTIME_ALIAS_ROOT"
read -r -a roles <<< "${ORB_SLAM3_ROLE_ORDER:-orb_only drop full}"
if [[ ${#roles[@]} -lt 3 || ${#roles[@]} -gt 6 ]]; then
  echo "ORB_SLAM3_ROLE_ORDER must contain orb_only, drop, full, and optional full_bridge_off/full_lineage_no_grace/full_unbounded exactly once" >&2
  exit 2
fi
for role in "${roles[@]}"; do
  if [[ "$role" != "orb_only" && "$role" != "drop" && "$role" != "full" &&
        "$role" != "full_bridge_off" && "$role" != "full_lineage_no_grace" &&
        "$role" != "full_unbounded" ]]; then
    echo "invalid ORB_SLAM3_ROLE_ORDER role: $role" >&2
    exit 2
  fi
done
for required_role in orb_only drop full; do
  matches=0
  for role in "${roles[@]}"; do
    if [[ "$role" == "$required_role" ]]; then
      matches=$((matches + 1))
    fi
  done
  if [[ $matches -ne 1 ]]; then
    echo "ORB_SLAM3_ROLE_ORDER must contain orb_only, drop, and full exactly once" >&2
    exit 2
  fi
done
for optional_role in full_bridge_off full_lineage_no_grace full_unbounded; do
  matches=0
  for role in "${roles[@]}"; do
    if [[ "$role" == "$optional_role" ]]; then
      matches=$((matches + 1))
    fi
  done
  if [[ $matches -gt 1 ]]; then
    echo "ORB_SLAM3_ROLE_ORDER contains duplicate optional role: $optional_role" >&2
    exit 2
  fi
  if [[ $matches -eq 1 && "$LINEAGE_BRIDGE_ENABLED" != "1" ]]; then
    echo "$optional_role requires ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE=1" >&2
    exit 2
  fi
  if [[ "$optional_role" == "full_lineage_no_grace" && $matches -eq 1 &&
        "$LINEAGE_CULL_GRACE_KEYFRAMES" -eq 0 ]]; then
    echo "full_lineage_no_grace requires ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES > 0" >&2
    exit 2
  fi
  if [[ "$optional_role" == "full_unbounded" && $matches -eq 1 &&
        "$LINEAGE_MAX_ASSISTED_MATCHES" -eq 0 && "$LINEAGE_NATIVE_BIRTH_ONLY" -eq 0 &&
        "$LINEAGE_QUARANTINE_ON_OUTLIER" -eq 0 &&
        "$LINEAGE_PRE_KF_OUTLIER_PURGE" -eq 0 ]]; then
    echo "full_unbounded requires an enabled lineage dose, native-birth, quarantine, or pre-KF purge ablation" >&2
    exit 2
  fi
done

for repeat in $(seq "$FIRST_REPEAT" "$LAST_REPEAT"); do
  for role in "${roles[@]}"; do
    run_dir="$OUTPUT_ROOT/${role}_r${repeat}"
    if [[ -e "$run_dir" && ! -d "$run_dir" ]]; then
      echo "refusing existing non-directory run path: $run_dir" >&2
      exit 2
    fi
    if [[ -d "$run_dir" ]]; then
      first_entry="$(find "$run_dir" -mindepth 1 -maxdepth 1 -print -quit)"
      if [[ -n "$first_entry" ]]; then
        echo "refusing non-empty run directory: $run_dir" >&2
        exit 2
      fi
    fi
  done
done

validate_seed_audit() {
  local audit_dir="$1"
  local artifact
  for artifact in seed_events.csv seed_mappoint_summary.csv seed_lineages.csv seed_summary.json; do
    if [[ ! -f "$audit_dir/$artifact" ]]; then
      echo "missing seed audit artifact: $audit_dir/$artifact" >&2
      return 1
    fi
  done
  python3 - "$audit_dir/seed_summary.json" "$audit_dir" <<'PY'
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
expected_directory = Path(sys.argv[2]).resolve()
try:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    raise SystemExit(f"invalid seed audit summary {summary_path}: {exc}")
if not isinstance(summary, dict):
    raise SystemExit(f"seed audit summary is not a JSON object: {summary_path}")
if summary.get("complete") is not True:
    raise SystemExit(f"seed audit summary is incomplete: {summary_path}")
output_directory = summary.get("output_directory")
if not isinstance(output_directory, str) or not output_directory:
    raise SystemExit(f"seed audit summary has invalid output_directory: {summary_path}")
if Path(output_directory).resolve() != expected_directory:
    raise SystemExit(
        "seed audit output_directory mismatch: "
        f"json={Path(output_directory).resolve()} expected={expected_directory}"
    )
PY
}

audit_env_unsets=(
  -u ORB_SLAM3_SEED_AUDIT_DIR
  -u ORB_SLAM3_ENABLE_SEED_AUDIT
  -u ORB_SLAM3_SEED_AUDIT_MAX_EVENTS
  -u ORB_SLAM3_EXTERNAL_SEED_AUDIT_DIR
  -u ORB_SLAM3_EXTERNAL_SEED_AUDIT
  -u ORB_SLAM3_EXTERNAL_SEED_AUDIT_MAX_EVENTS
  -u ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE
  -u ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY
  -u ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX
  -u ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE
  -u ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES
  -u ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES
  -u ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY
  -u ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER
  -u ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE
  -u ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE
  -u ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE
  -u ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE
  -u ORB_SLAM3_CPU_AFFINITY
  -u ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING
  -u ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC
  -u ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING
  -u ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC
  -u ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE
  -u ORB_SLAM3_DISABLE_ASLR
  -u ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY
)

for repeat in $(seq "$FIRST_REPEAT" "$LAST_REPEAT"); do
  role_slot=0
  for role in "${roles[@]}"; do
    role_slot=$((role_slot + 1))
    run_dir="$OUTPUT_ROOT/${role}_r${repeat}"
    mkdir -p "$run_dir"
    trajectory_name="${TAG}_${role}_r${repeat}"
    runtime_alias="$RUNTIME_ALIAS_ROOT/repeat_$(printf '%06d' "$repeat")_slot_$(printf '%02d' "$role_slot")"
    runtime_trajectory_name="runtime_repeat_$(printf '%06d' "$repeat")"
    if [[ -e "$runtime_alias" || -L "$runtime_alias" ]]; then
      echo "refusing existing runtime alias: $runtime_alias" >&2
      exit 2
    fi
    ln -s "$run_dir" "$runtime_alias"
    online_trajectory_file=""
    if [[ "$EXPORT_ONLINE_TRAJECTORY" == "1" ]]; then
      online_trajectory_file="$run_dir/online_f_${trajectory_name}.txt"
    fi
    if [[ "$role" == "full" || "$role" == "full_bridge_off" ||
          "$role" == "full_lineage_no_grace" || "$role" == "full_unbounded" ]]; then
      seed_file="$FULL_SEEDS"
    elif [[ "$role" == "drop" ]]; then
      seed_file="$DROP_SEEDS"
    else
      seed_file=""
    fi
    role_lineage_bridge_enabled="$LINEAGE_BRIDGE_ENABLED"
    role_lineage_cull_grace_keyframes="$LINEAGE_CULL_GRACE_KEYFRAMES"
    role_lineage_max_assisted_matches="$LINEAGE_MAX_ASSISTED_MATCHES"
    role_lineage_native_birth_only="$LINEAGE_NATIVE_BIRTH_ONLY"
    role_lineage_quarantine_on_outlier="$LINEAGE_QUARANTINE_ON_OUTLIER"
    role_lineage_terminal_quarantine="$LINEAGE_TERMINAL_QUARANTINE"
    role_lineage_quarantine_enforce="$LINEAGE_QUARANTINE_ENFORCE"
    role_lineage_pre_kf_outlier_purge="$LINEAGE_PRE_KF_OUTLIER_PURGE"
    role_lineage_pre_kf_outlier_purge_enforce="$LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE"
    if [[ "$role" == "full_bridge_off" ]]; then
      role_lineage_bridge_enabled=0
      role_lineage_cull_grace_keyframes=0
      role_lineage_max_assisted_matches=0
      role_lineage_native_birth_only=0
      role_lineage_quarantine_on_outlier=0
      role_lineage_terminal_quarantine=0
      role_lineage_quarantine_enforce=0
      role_lineage_pre_kf_outlier_purge=0
      role_lineage_pre_kf_outlier_purge_enforce=0
    elif [[ "$role" == "full_lineage_no_grace" ]]; then
      role_lineage_cull_grace_keyframes=0
    elif [[ "$role" == "full_unbounded" ]]; then
      role_lineage_max_assisted_matches=0
      role_lineage_native_birth_only=0
      role_lineage_quarantine_enforce=0
      role_lineage_pre_kf_outlier_purge_enforce=0
    elif [[ "$role" == "orb_only" || "$role" == "drop" ]]; then
      role_lineage_max_assisted_matches=0
      role_lineage_native_birth_only=0
      role_lineage_quarantine_on_outlier=0
      role_lineage_terminal_quarantine=0
      role_lineage_quarantine_enforce=0
      role_lineage_pre_kf_outlier_purge=0
      role_lineage_pre_kf_outlier_purge_enforce=0
    fi
    seed_audit_dir=""
    runtime_seed_audit_dir=""
    if [[ "$SEED_AUDIT_ENABLED" == "1" ]]; then
      seed_audit_dir="$run_dir/instrumentation"
      runtime_seed_audit_dir="$runtime_alias/instrumentation"
      mkdir -p "$seed_audit_dir"
    fi

    provenance_dir="$run_dir/provenance"
    mkdir -p "$provenance_dir/runtime" "$provenance_dir/inputs" \
      "$provenance_dir/sources"
    cp -- "$BINARY" "$provenance_dir/runtime/mono_euroc_old"
    cp -- "$LIBORB_SLAM3_PATH" "$provenance_dir/runtime/libORB_SLAM3.so"
    cp -- "$RUNNER_PATH" "$provenance_dir/runtime/run_orbslam3_seeded_triplet.sh"
    cp -- "$CONFIG" "$provenance_dir/inputs/config.yaml"
    cp -- "$TIMES_FILE" "$provenance_dir/inputs/times.txt"
    if [[ -n "$seed_file" ]]; then
      cp -- "$seed_file" "$provenance_dir/inputs/seeds.txt"
    fi
    for relative_source in "${MECHANISM_SOURCE_PATHS[@]}"; do
      source_path="$ORB_ROOT/$relative_source"
      if [[ ! -f "$source_path" ]]; then
        continue
      fi
      snapshot_path="$provenance_dir/sources/$relative_source"
      mkdir -p "$(dirname "$snapshot_path")"
      cp -- "$source_path" "$snapshot_path"
    done
    provenance_manifest="$provenance_dir/snapshot_sha256.txt"
    (
      cd "$provenance_dir"
      find . -type f ! -name snapshot_sha256.txt -print0 \
        | sort -z \
        | xargs -0 sha256sum
    ) > "$provenance_manifest"
    provenance_manifest_sha256="$(sha256sum "$provenance_manifest" | awk '{print $1}')"
    if [[ "$(sha256sum "$provenance_dir/runtime/mono_euroc_old" | awk '{print $1}')" != \
          "$(sha256sum "$BINARY" | awk '{print $1}')" ||
          "$(sha256sum "$provenance_dir/runtime/libORB_SLAM3.so" | awk '{print $1}')" != \
          "$LIBORB_SLAM3_SHA256" ]]; then
      echo "runtime provenance copy hash mismatch: $provenance_dir" >&2
      exit 2
    fi
    find "$provenance_dir" -type f -exec chmod 0444 '{}' ';'

    {
      echo "dataset_dir=$DATASET_DIR"
      echo "times_file=$TIMES_FILE"
      echo "config=$CONFIG"
      echo "binary=$BINARY"
      echo "tag=$TAG"
      echo "repeat=$repeat"
      echo "role=$role"
      echo "role_order=${roles[*]}"
      echo "seed_file=$seed_file"
      echo "seed_phase=${ORB_SLAM3_SEED_PHASE:-all}"
      echo "seed_min_ok_frames=${ORB_SLAM3_SEED_MIN_OK_FRAMES:-0}"
      echo "seed_audit_enabled=$SEED_AUDIT_ENABLED"
      echo "seed_audit_dir=$seed_audit_dir"
      echo "runtime_seed_audit_dir=$runtime_seed_audit_dir"
      echo "seed_audit_max_events=$SEED_AUDIT_MAX_EVENTS"
      echo "external_lineage_bridge_enabled=$role_lineage_bridge_enabled"
      echo "external_lineage_bridge_requested=$LINEAGE_BRIDGE_ENABLED"
      echo "external_lineage_min_quality=$LINEAGE_MIN_QUALITY"
      echo "external_lineage_max_projection_error_px=$LINEAGE_MAX_PROJECTION_ERROR_PX"
      echo "external_lineage_max_descriptor_distance=$LINEAGE_MAX_DESCRIPTOR_DISTANCE"
      echo "external_lineage_cull_grace_keyframes=$role_lineage_cull_grace_keyframes"
      echo "external_lineage_cull_grace_requested=$LINEAGE_CULL_GRACE_KEYFRAMES"
      echo "external_lineage_max_assisted_matches=$role_lineage_max_assisted_matches"
      echo "external_lineage_max_assisted_matches_requested=$LINEAGE_MAX_ASSISTED_MATCHES"
      echo "external_lineage_native_birth_only=$role_lineage_native_birth_only"
      echo "external_lineage_native_birth_only_requested=$LINEAGE_NATIVE_BIRTH_ONLY"
      echo "external_lineage_quarantine_on_outlier=$role_lineage_quarantine_on_outlier"
      echo "external_lineage_quarantine_on_outlier_requested=$LINEAGE_QUARANTINE_ON_OUTLIER"
      echo "external_lineage_terminal_quarantine=$role_lineage_terminal_quarantine"
      echo "external_lineage_terminal_quarantine_requested=$LINEAGE_TERMINAL_QUARANTINE"
      echo "external_lineage_quarantine_enforce=$role_lineage_quarantine_enforce"
      echo "external_lineage_quarantine_enforce_requested=$LINEAGE_QUARANTINE_ENFORCE"
      echo "external_lineage_pre_kf_outlier_purge=$role_lineage_pre_kf_outlier_purge"
      echo "external_lineage_pre_kf_outlier_purge_requested=$LINEAGE_PRE_KF_OUTLIER_PURGE"
      echo "external_lineage_pre_kf_outlier_purge_enforce=$role_lineage_pre_kf_outlier_purge_enforce"
      echo "external_lineage_pre_kf_outlier_purge_enforce_requested=$LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE"
      echo "cpu_affinity=$CPU_AFFINITY"
      if [[ -n "$CPU_AFFINITY" ]]; then
        echo "scheduler_mode=single_cpu"
      else
        echo "scheduler_mode=default"
      fi
      echo "synchronize_local_mapping=$SYNCHRONIZE_LOCAL_MAPPING"
      echo "local_mapping_idle_timeout_sec=$LOCAL_MAPPING_IDLE_TIMEOUT_SEC"
      echo "synchronize_loop_closing=$SYNCHRONIZE_LOOP_CLOSING"
      echo "loop_closing_idle_timeout_sec=$LOOP_CLOSING_IDLE_TIMEOUT_SEC"
      echo "deterministic_background_gate=$DETERMINISTIC_BACKGROUND_GATE"
      echo "disable_aslr=$DISABLE_ASLR"
      echo "export_online_trajectory=$EXPORT_ONLINE_TRAJECTORY"
      echo "online_trajectory_file=$online_trajectory_file"
      echo "runtime_alias=$runtime_alias"
      echo "runtime_trajectory_name=$runtime_trajectory_name"
      echo "machine_arch=$MACHINE_ARCH"
      echo "binary_sha256=$(sha256sum "$BINARY" | awk '{print $1}')"
      echo "liborbslam3_path=$LIBORB_SLAM3_PATH"
      echo "liborbslam3_sha256=$LIBORB_SLAM3_SHA256"
      echo "liborbslam3_resolution=$LIBORB_SLAM3_RESOLUTION"
      echo "external_seed_audit_source_path=$EXTERNAL_SEED_AUDIT_SOURCE"
      echo "external_seed_audit_source_sha256=$EXTERNAL_SEED_AUDIT_SOURCE_SHA256"
      echo "vocabulary_sha256=$VOCABULARY_SHA256"
      echo "runner_sha256=$RUNNER_SHA256"
      echo "provenance_dir=$provenance_dir"
      echo "provenance_manifest=$provenance_manifest"
      echo "provenance_manifest_sha256=$provenance_manifest_sha256"
      echo "config_sha256=$(sha256sum "$CONFIG" | awk '{print $1}')"
      echo "times_sha256=$(sha256sum "$TIMES_FILE" | awk '{print $1}')"
      if [[ -n "$seed_file" ]]; then
        echo "seed_sha256=$(sha256sum "$seed_file" | awk '{print $1}')"
      else
        echo "seed_sha256="
      fi
    } > "$run_dir/run_manifest.txt"

    run_env=("ORB_SLAM3_USE_VIEWER=0")
    run_env+=(
      "ORB_SLAM3_EXTERNAL_LINEAGE_BRIDGE=$role_lineage_bridge_enabled"
      "ORB_SLAM3_EXTERNAL_LINEAGE_MIN_QUALITY=$LINEAGE_MIN_QUALITY"
      "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_PROJECTION_ERROR_PX=$LINEAGE_MAX_PROJECTION_ERROR_PX"
      "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_DESCRIPTOR_DISTANCE=$LINEAGE_MAX_DESCRIPTOR_DISTANCE"
      "ORB_SLAM3_EXTERNAL_LINEAGE_CULL_GRACE_KEYFRAMES=$role_lineage_cull_grace_keyframes"
      "ORB_SLAM3_EXTERNAL_LINEAGE_MAX_ASSISTED_MATCHES=$role_lineage_max_assisted_matches"
      "ORB_SLAM3_EXTERNAL_LINEAGE_NATIVE_BIRTH_ONLY=$role_lineage_native_birth_only"
      "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ON_OUTLIER=$role_lineage_quarantine_on_outlier"
      "ORB_SLAM3_EXTERNAL_LINEAGE_TERMINAL_QUARANTINE=$role_lineage_terminal_quarantine"
      "ORB_SLAM3_EXTERNAL_LINEAGE_QUARANTINE_ENFORCE=$role_lineage_quarantine_enforce"
      "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE=$role_lineage_pre_kf_outlier_purge"
      "ORB_SLAM3_EXTERNAL_LINEAGE_PRE_KF_OUTLIER_PURGE_ENFORCE=$role_lineage_pre_kf_outlier_purge_enforce"
      "ORB_SLAM3_SYNCHRONIZE_LOCAL_MAPPING=$SYNCHRONIZE_LOCAL_MAPPING"
      "ORB_SLAM3_LOCAL_MAPPING_IDLE_TIMEOUT_SEC=$LOCAL_MAPPING_IDLE_TIMEOUT_SEC"
      "ORB_SLAM3_SYNCHRONIZE_LOOP_CLOSING=$SYNCHRONIZE_LOOP_CLOSING"
      "ORB_SLAM3_LOOP_CLOSING_IDLE_TIMEOUT_SEC=$LOOP_CLOSING_IDLE_TIMEOUT_SEC"
      "ORB_SLAM3_DETERMINISTIC_BACKGROUND_GATE=$DETERMINISTIC_BACKGROUND_GATE"
      "ORB_SLAM3_EXPORT_ONLINE_TRAJECTORY=$EXPORT_ONLINE_TRAJECTORY"
    )
    if [[ "$SEED_AUDIT_ENABLED" == "1" ]]; then
      run_env+=(
        "ORB_SLAM3_SEED_AUDIT_DIR=$runtime_seed_audit_dir"
        "ORB_SLAM3_ENABLE_SEED_AUDIT=1"
        "ORB_SLAM3_SEED_AUDIT_MAX_EVENTS=$SEED_AUDIT_MAX_EVENTS"
      )
    fi

    seed_env=(-u ORB_SLAM3_EXTERNAL_SEEDS)
    if [[ -n "$seed_file" ]]; then
      seed_env+=("ORB_SLAM3_EXTERNAL_SEEDS=$seed_file")
    fi

    (
      cd "$runtime_alias"
      run_command=(
        "$BINARY" "$VOCABULARY" "$CONFIG" "$DATASET_DIR" "$TIMES_FILE"
        "$runtime_trajectory_name"
      )
      if [[ -n "$CPU_AFFINITY" ]]; then
        run_command=(taskset -c "$CPU_AFFINITY" "${run_command[@]}")
      fi
      if [[ "$DISABLE_ASLR" == "1" ]]; then
        run_command=(
          setarch "$MACHINE_ARCH" -R sh -c
          'printf "runtime_personality=%s\n" "$(cat /proc/self/personality)"; exec "$@"'
          sh "${run_command[@]}"
        )
      fi
      env "${audit_env_unsets[@]}" "${seed_env[@]}" "${run_env[@]}" \
        "${run_command[@]}" > orbslam3_run.log 2>&1
    )
    for trajectory_prefix in f_ kf_ online_f_; do
      runtime_trajectory_file="$run_dir/${trajectory_prefix}${runtime_trajectory_name}.txt"
      final_trajectory_file="$run_dir/${trajectory_prefix}${trajectory_name}.txt"
      if [[ -e "$runtime_trajectory_file" ]]; then
        mv -- "$runtime_trajectory_file" "$final_trajectory_file"
      fi
    done
    if [[ "$SEED_AUDIT_ENABLED" == "1" ]]; then
      validate_seed_audit "$seed_audit_dir"
    fi
    if [[ "$EXPORT_ONLINE_TRAJECTORY" == "1" && ! -s "$online_trajectory_file" ]]; then
      echo "missing or empty online trajectory: $online_trajectory_file" >&2
      exit 1
    fi
    echo "completed role=$role repeat=$repeat run_dir=$run_dir"
  done
done
