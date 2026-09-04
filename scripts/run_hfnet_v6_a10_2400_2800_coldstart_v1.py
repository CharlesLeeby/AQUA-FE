#!/usr/bin/env python3
"""One-shot HFNet-SLAM run on the canonical A10 2400..2800 cold-start input.

This thin controller reuses the already exercised A06 one-shot supervisor but
binds every mutable path and timestamp to the independently audited A10 input.
It also freezes a zero-keyframe save-hang watchdog: after the official entry
prints ``Map 0 has 0 KFs`` during post-Shutdown trajectory saving, the attempt
is terminated and sealed as a failure instead of waiting for the outer limit.
"""

from __future__ import annotations

import argparse
import bisect
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_hfnet_v6_a06_2210_2460_coldstart_v1 as base


RUNNER = Path(__file__).resolve()
INPUT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a10_2400_2800_coldstart"
)
INPUT_MANIFEST = INPUT_ROOT / "materialization_manifest.json"
INPUT_AUDIT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_positive_windows_v1/"
    "a10_2400_2800_coldstart.audit.json"
)
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a10_2400_2800_coldstart/attempt_001"
)
SOURCE_FIRST = 2400
SOURCE_LAST = 2800
CAMERA_COUNT = 401
FIRST_NS = 1542888916043622160
LAST_NS = 1542888936039921424
TIMES_SIZE = 8020
TIMES_SHA256 = "7ae37ffc7b7a8802f7a67f541fb8883bd9ed708fe74323b9262e3c73828deced"
INPUT_PAYLOAD_SHA256 = "ba1400536382aed9e69e64e514dd3770f1cdb20d42215251576ded3789c29d46"
INPUT_MANIFEST_SHA256 = "147aad7267dee7b7d74231f8916f6d744903b64e7e9007f400be3b515a3008d4"
INPUT_AUDIT_SHA256 = "b068ab8b953be9105e2d9f1feb42b256c2251c353029abaf33bfc7a9bc563bcf"
AUTHORIZATION_TOKEN = "HFNET_V6_A10_2400_2800_COLDSTART_ATTEMPT_001_START_EXACTLY_ONCE"
SCHEMA = "aqua-fe-hfnet-v6-a10-2400-2800-coldstart-result-v1"
TIMEOUT_SECONDS = 300
_BASE_ATOMIC_JSON = base.atomic_json
_ORIGINAL_POPEN = base.subprocess.Popen
_ACTIVE_WATCHDOG: dict[str, object] | None = None
_CHILD_READY: threading.Event | None = None


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_2400_2800.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_input_authority() -> dict[str, Any]:
    if not INPUT_MANIFEST.is_file() or INPUT_MANIFEST.is_symlink():
        raise base.ContractError("A10_INPUT_MANIFEST_MISSING")
    if _sha256(INPUT_MANIFEST) != INPUT_MANIFEST_SHA256:
        raise base.ContractError("A10_INPUT_MANIFEST_IDENTITY_MISMATCH")
    if not INPUT_AUDIT.is_file() or INPUT_AUDIT.is_symlink():
        raise base.ContractError("A10_INDEPENDENT_AUDIT_RECEIPT_MISSING")
    if _sha256(INPUT_AUDIT) != INPUT_AUDIT_SHA256:
        raise base.ContractError("A10_INDEPENDENT_AUDIT_IDENTITY_MISMATCH")
    manifest = json.loads(INPUT_MANIFEST.read_text(encoding="utf-8"))
    audit = json.loads(INPUT_AUDIT.read_text(encoding="utf-8"))
    selection = manifest.get("selection", {})
    payload = manifest.get("payload_identity_excluding_manifest", {})
    if (
        manifest.get("status") != "PASS_PREPARATION_ONLY"
        or selection.get("sequence_id") != "A10"
        or selection.get("camera_indices_inclusive") != [SOURCE_FIRST, SOURCE_LAST]
        or selection.get("cold_start") is not True
        or payload.get("sha256") != INPUT_PAYLOAD_SHA256
    ):
        raise base.ContractError("A10_INPUT_MANIFEST_CONTRACT_MISMATCH")
    independent = audit.get("independent_audit", {})
    audited_manifest = independent.get("manifest", {})
    if (
        audit.get("status") != "PASS_MATERIALIZED_AND_INDEPENDENTLY_AUDITED_PREPARATION_ONLY"
        or independent.get("status") != "PASS_PREPARATION_ONLY_INDEPENDENT_AUDIT"
        or independent.get("payload_identity_excluding_manifest", {}).get("sha256") != INPUT_PAYLOAD_SHA256
        or audit.get("materialization", {}).get("payload_identity_excluding_manifest", {}).get("sha256") != INPUT_PAYLOAD_SHA256
        or audited_manifest.get("sha256") != INPUT_MANIFEST_SHA256
        or audited_manifest.get("size_bytes") != INPUT_MANIFEST.stat().st_size
    ):
        raise base.ContractError("A10_AUDIT_TO_MANIFEST_BINDING_MISMATCH")
    expected_files: set[str] = {"materialization_manifest.json"}
    camera_files = manifest.get("camera", {}).get("files", [])
    if len(camera_files) != CAMERA_COUNT:
        raise base.ContractError("A10_MANIFEST_CAMERA_FILE_COUNT_MISMATCH")
    for row in camera_files:
        relative = row.get("path")
        if not isinstance(relative, str):
            raise base.ContractError("A10_MANIFEST_CAMERA_PATH_INVALID")
        expected_files.add(relative)
        observed = base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise base.ContractError(f"A10_CAMERA_FILE_DRIFT:{relative}")
    generated = manifest.get("generated_files", {})
    generated_paths = {
        "cam0_times": "cam0_times.txt",
        "cam0_data_csv": "mav0/cam0/data.csv",
        "imu0_data_csv": "mav0/imu0/data.csv",
    }
    for key, relative in generated_paths.items():
        row = generated.get(key, {})
        expected_files.add(relative)
        observed = base.identity(INPUT_ROOT / relative)
        if observed["size_bytes"] != row.get("size_bytes") or observed["sha256"] != row.get("sha256"):
            raise base.ContractError(f"A10_GENERATED_FILE_DRIFT:{relative}")
    observed_files = {
        path.relative_to(INPUT_ROOT).as_posix()
        for path in INPUT_ROOT.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if observed_files != expected_files or any(path.is_symlink() for path in INPUT_ROOT.rglob("*")):
        raise base.ContractError("A10_INPUT_FILE_SET_OR_SYMLINK_DRIFT")
    return manifest


def selected_timestamps() -> list[int]:
    validate_input_authority()
    time_path = INPUT_ROOT / "cam0_times.txt"
    if time_path.stat().st_size != TIMES_SIZE or _sha256(time_path) != TIMES_SHA256:
        raise base.ContractError("A10_TIMES_IDENTITY_MISMATCH")
    try:
        stamps = [int(row) for row in time_path.read_text(encoding="ascii").splitlines()]
    except ValueError as error:
        raise base.ContractError("A10_TIMESTAMPS_NOT_INTEGER") from error
    if len(stamps) != CAMERA_COUNT or stamps[0] != FIRST_NS or stamps[-1] != LAST_NS:
        raise base.ContractError("A10_TIMESTAMP_BOUNDARY_MISMATCH")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise base.ContractError("A10_TIMESTAMPS_NOT_STRICT")
    return stamps


def configure_base() -> None:
    base.RUNNER = RUNNER
    base.SOURCE_ROOT = INPUT_ROOT
    base.FULL_TIMES = INPUT_ROOT / "cam0_times.txt"
    base.IMU_CSV = INPUT_ROOT / "mav0/imu0/data.csv"
    base.IMAGE_ROOT = INPUT_ROOT / "mav0/cam0/data"
    base.ATTEMPT = ATTEMPT
    base.SOURCE_FIRST = SOURCE_FIRST
    base.SOURCE_LAST = SOURCE_LAST
    base.CAMERA_COUNT = CAMERA_COUNT
    base.AUTHORIZATION_TOKEN = AUTHORIZATION_TOKEN
    base.SCHEMA = SCHEMA
    base.TIMEOUT_SECONDS = TIMEOUT_SECONDS
    base.selected_timestamps = selected_timestamps
    base.parse_trajectory = parse_trajectory
    base.attempt_paths = paths
    base.atomic_json = profile_atomic_json


def profile_atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    """Finalize profile labels before the sole atomic publication."""
    if path == paths()["prepared"] and isinstance(value, dict):
        value["schema_version"] = "aqua-fe-hfnet-v6-a10-2400-2800-coldstart-prepared-v1"
        value["scientific_role"] = "DEVELOPMENT_ONLY_EXTERNAL_LEARNED_WHOLE_SYSTEM_ON_A10_LEARNED_ACTIVE_POSITIVE_WINDOW"
        value["selection"] = {
            "sequence": "AQUALOC archaeology_sequence_10",
            "source_frame_indices_inclusive": [SOURCE_FIRST, SOURCE_LAST],
            "camera_count": CAMERA_COUNT,
            "camera_header_ns_inclusive": [FIRST_NS, LAST_NS],
            "span_seconds": (LAST_NS - FIRST_NS) / 1e9,
            "history": "cold_start_at_source_frame_2400; no frame before 2400 passed to HFNet",
            "development_result_conditioned_selection": True,
            "prior_project_result": "AQUA-FE active final-online beat KLT in 5/5 development replays with 97 injected observations",
        }
        value["input_authority"] = {
            "materialization_manifest": base.identity(INPUT_MANIFEST),
            "independent_audit_receipt": base.identity(INPUT_AUDIT),
            "payload_sha256_excluding_manifest": INPUT_PAYLOAD_SHA256,
        }
    elif path == paths()["claim"] and isinstance(value, dict):
        value = dict(value)
        value["schema_version"] = "aqua-fe-hfnet-v6-a10-2400-2800-coldstart-claim-v1"
    elif path == paths()["result"] and isinstance(value, dict):
        value["schema_version"] = SCHEMA
        value["watchdog"] = dict(_ACTIVE_WATCHDOG or {"triggered": False})
        if _ACTIVE_WATCHDOG and _ACTIVE_WATCHDOG.get("triggered") is True:
            value["status"] = "FAIL_EXPLORATORY_COLDSTART_ZERO_KEYFRAMES"
            value["failure_code"] = _ACTIVE_WATCHDOG.get("failure_code")
            value["execution"]["termination"] = "FROZEN_ALL_MAPS_ZERO_KEYFRAME_SAVE_HANG_WATCHDOG_SIGTERM"
    _BASE_ATOMIC_JSON(path, value, exclusive=exclusive)


def parse_trajectory(path: Path, stamps: list[int]) -> dict[str, object]:
    audit: dict[str, object] = {"exists": path.is_file(), "pose_count": 0, "valid": False, "errors": []}
    if not path.is_file():
        audit["errors"] = ["MISSING"]
        return audit
    rows = [line.split() for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    pose_stamps: list[int] = []
    for index, fields in enumerate(rows):
        if len(fields) != 8:
            audit["errors"].append(f"ROW_{index}_FIELD_COUNT")
            continue
        try:
            stamp_decimal = Decimal(fields[0])
            pose = [float(value) for value in fields[1:]]
        except (InvalidOperation, ValueError):
            audit["errors"].append(f"ROW_{index}_PARSE")
            continue
        if not stamp_decimal.is_finite() or stamp_decimal != stamp_decimal.to_integral_value():
            audit["errors"].append(f"ROW_{index}_TIMESTAMP_NOT_INTEGER_NS")
            continue
        if not all(math.isfinite(value) for value in pose):
            audit["errors"].append(f"ROW_{index}_NONFINITE")
            continue
        norm = math.sqrt(sum(value * value for value in pose[3:7]))
        if not 0.99 <= norm <= 1.01:
            audit["errors"].append(f"ROW_{index}_QUATERNION_NORM")
            continue
        pose_stamps.append(int(stamp_decimal))
    strict = all(right > left for left, right in zip(pose_stamps, pose_stamps[1:]))
    associated: list[int | None] = []
    errors_ns: list[int] = []
    for value in pose_stamps:
        insertion = bisect.bisect_left(stamps, value)
        candidates = [item for item in (insertion - 1, insertion) if 0 <= item < len(stamps)]
        if not candidates:
            associated.append(None)
            continue
        nearest = min(candidates, key=lambda item: abs(stamps[item] - value))
        error = abs(stamps[nearest] - value)
        associated.append(nearest if error <= 256 else None)
        errors_ns.append(error)
    unique = all(item is not None for item in associated) and len(set(associated)) == len(associated)
    valid_indices = [int(item) for item in associated if item is not None]
    longest = run = 0
    previous: int | None = None
    for item in valid_indices:
        run = run + 1 if previous is not None and item == previous + 1 else 1
        longest = max(longest, run)
        previous = item
    audit.update({
        "identity": base.identity(path), "pose_count": len(pose_stamps),
        "strictly_increasing_timestamps": strict,
        "unique_camera_associations_within_256ns": unique,
        "association_max_abs_error_ns": max(errors_ns) if errors_ns else None,
        "first_relative_index": valid_indices[0] if valid_indices else None,
        "last_relative_index": valid_indices[-1] if valid_indices else None,
        "coverage_fraction": len(valid_indices) / CAMERA_COUNT,
        "longest_contiguous_count": longest,
        "longest_contiguous_fraction": longest / CAMERA_COUNT,
        "valid": bool(not audit["errors"] and strict and unique),
    })
    return audit


def prepare() -> dict[str, Any]:
    configure_base()
    validate_input_authority()
    return base.prepare()


def check() -> dict[str, object]:
    configure_base()
    value = base.check(require_unclaimed=True)
    value["schema_version"] = "aqua-fe-hfnet-v6-a10-2400-2800-coldstart-check-v1"
    return value


def bound_popen(*args: object, **kwargs: object):
    process = _ORIGINAL_POPEN(*args, **kwargs)
    argv = args[0] if args else kwargs.get("args")
    exact_child = (
        isinstance(argv, (list, tuple))
        and len(argv) == 5
        and str(argv[0]) == str(base.BINARY)
        and str(argv[2]) == str(paths()["result_dir"]) + "/"
        and str(argv[3]) == str(INPUT_ROOT)
        and str(argv[4]) == str(paths()["subset_times"])
    )
    if exact_child:
        if _ACTIVE_WATCHDOG is not None:
            _ACTIVE_WATCHDOG["pid"] = process.pid
        if _CHILD_READY is not None:
            _CHILD_READY.set()
    return process


def run_with_watchdog(token: str) -> dict[str, object]:
    global _ACTIVE_WATCHDOG, _CHILD_READY
    configure_base()
    watchdog: dict[str, object] = {"triggered": False, "failure_code": None, "pid": None}
    _ACTIVE_WATCHDOG = watchdog
    _CHILD_READY = threading.Event()
    stop = threading.Event()

    def monitor() -> None:
        assert _CHILD_READY is not None
        if not _CHILD_READY.wait(TIMEOUT_SECONDS):
            return
        while not stop.wait(0.25):
            pid_value = watchdog.get("pid")
            if not isinstance(pid_value, int) or not paths()["stdout"].is_file():
                continue
            try:
                payload = paths()["stdout"].read_bytes()
            except OSError:
                continue
            text = payload.decode("utf-8", "replace")
            saving = text.rfind("Saving trajectory to ")
            if saving < 0:
                continue
            tail = text[saving:]
            atlas_rows = list(re.finditer(r"There are (\d+) maps in (?:the )?atlas", tail))
            if not atlas_rows:
                continue
            atlas = atlas_rows[-1]
            map_counts = [int(value) for value in re.findall(r"Map \d+ has (\d+) KFs", tail[atlas.end():])]
            expected_maps = int(atlas.group(1))
            if len(map_counts) < expected_maps or any(value > 0 for value in map_counts[:expected_maps]):
                continue
            pid = pid_value
            watchdog.update({
                "triggered": True,
                "failure_code": "ALL_MAPS_ZERO_KEYFRAME_OFFICIAL_SAVE_HANG_WATCHDOG",
                "pid": pid,
                "triggered_at_utc": base.now_utc(),
            })
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return

    thread = threading.Thread(target=monitor, name="hfnet-zero-kf-watchdog", daemon=True)
    thread.start()
    base.subprocess.Popen = bound_popen
    try:
        result = base.run(token)
    finally:
        base.subprocess.Popen = _ORIGINAL_POPEN
        stop.set()
        thread.join(timeout=2)
    _ACTIVE_WATCHDOG = None
    _CHILD_READY = None
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "check", "run"))
    parser.add_argument("--authorization-token", default="")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            value = prepare()
        elif args.action == "check":
            value = check()
        else:
            value = run_with_watchdog(args.authorization_token)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        if args.action == "check":
            return 0 if value.get("ready") is True else 2
        if args.action == "run":
            return 0 if str(value.get("status", "")).startswith("PASS_") else 2
        return 0
    except Exception as error:
        print(json.dumps({"status": "FAIL_CLOSED", "error": f"{type(error).__name__}:{error}"}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
