#!/usr/bin/env python3
"""One-shot HFNet-SLAM cold-start run on AQUALOC A06 frames 2210..2460.

The immutable 0..2460 materialized input is reused, but the official EuRoC
entry receives an attempt-local 251-line timestamp file.  Therefore HFNet has
no map, bias, keyframe, or loop-closing history before source frame 2210.

This is development-only system runability evidence.  It neither evaluates
accuracy nor authorizes a retry after a process-start claim has been created.
"""

from __future__ import annotations

import argparse
import bisect
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
SOURCE_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/datasets/hfnet_v6_a06_exact_window_v1/"
    "aqualoc_archaeology_a06_0000_2460"
)
FULL_TIMES = SOURCE_ROOT / "cam0_times.txt"
IMU_CSV = SOURCE_ROOT / "mav0/imu0/data.csv"
IMAGE_ROOT = SOURCE_ROOT / "mav0/cam0/data"
BASE_CONFIG = ROOT / "configs/published_baselines/hfnet_slam_aqualoc_a06_0000_2460_exact_window_v1.yaml"
BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
OFFICIAL_LIBRARY = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so")
SHARED_MODEL = Path("/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx")
SHARED_CACHE = Path("/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache")
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/positive_windows/"
    "a06_2210_2460_coldstart/attempt_001"
)

SOURCE_FIRST = 2210
SOURCE_LAST = 2460
CAMERA_COUNT = SOURCE_LAST - SOURCE_FIRST + 1
TIMEOUT_SECONDS = 900
MIN_GPU_FREE_MIB = 3072
AUTHORIZATION_TOKEN = "HFNET_V6_A06_2210_2460_COLDSTART_ATTEMPT_001_START_EXACTLY_ONCE"
SCHEMA = "aqua-fe-hfnet-v6-a06-2210-2460-coldstart-result-v1"

EXPECTED = {
    "full_times": (49220, "7b81913749fe5b296aae4280531e6e26cda3349791e7331befdb72eb6de7f861"),
    "base_config": (2037, "37ec8f0f274818b3a8f952a535d9be87dae0f8d0436ce05503381791ace69db6"),
    "binary": (118280, "4d17eecc74ec8f4bcbe4381d579d2bb48160cf63f6dc948f7857d92e681affeb"),
    "official_library": (4807712, "a56dfd1b48dee4af5be4e55b076d32eac2cf8fb463da8ab943b690377f193717"),
    "onnx": (132238602, "354a23f9c28b75ea9056a8eb5586e3b13191426521fd3f5556e5bfd670fc39b5"),
    "cache_seed": (853319, "6798ef896e4f503d4d81827a81fc9dad99d40c5e10352abbe974ed309bd0c0e7"),
}


class ContractError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def atomic_json(path: Path, value: object, exclusive: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = canonical_json(value)
    if exclusive:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o444)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def require_expected(path: Path, key: str) -> dict[str, object]:
    value = identity(path)
    size, digest = EXPECTED[key]
    if value["size_bytes"] != size or value["sha256"] != digest:
        raise ContractError(f"IDENTITY_MISMATCH:{key}:{path}")
    return value


def selected_timestamps() -> list[int]:
    require_expected(FULL_TIMES, "full_times")
    rows = FULL_TIMES.read_text(encoding="ascii").splitlines()
    if len(rows) != 2461:
        raise ContractError("FULL_TIMESTAMP_COUNT_MISMATCH")
    try:
        stamps = [int(row) for row in rows]
    except ValueError as error:
        raise ContractError("FULL_TIMESTAMPS_NOT_INTEGER") from error
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError("FULL_TIMESTAMPS_NOT_STRICT")
    subset = stamps[SOURCE_FIRST : SOURCE_LAST + 1]
    if len(subset) != CAMERA_COUNT:
        raise ContractError("SUBSET_TIMESTAMP_COUNT_MISMATCH")
    if subset[0] != 1542883422269233600 or subset[-1] != 1542883434765650624:
        raise ContractError("SUBSET_TIMESTAMP_BOUNDARY_MISMATCH")
    return subset


def subset_payload(stamps: Iterable[int]) -> bytes:
    return ("\n".join(str(value) for value in stamps) + "\n").encode("ascii")


def input_inventory(stamps: list[int]) -> dict[str, object]:
    digest = hashlib.sha256()
    total = 0
    for stamp in stamps:
        path = IMAGE_ROOT / f"{stamp}.png"
        item = identity(path)
        relative = f"mav0/cam0/data/{stamp}.png"
        record = f"{relative}\0{item['size_bytes']}\0{item['sha256']}\n".encode("ascii")
        digest.update(record)
        total += int(item["size_bytes"])
    return {
        "camera_count": len(stamps),
        "selected_image_total_bytes": total,
        "selected_image_inventory_sha256": digest.hexdigest(),
        "imu_csv": identity(IMU_CSV),
        "full_times": identity(FULL_TIMES),
    }


def runner_identity() -> dict[str, object]:
    return identity(RUNNER)


def attempt_paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_2210_2460.txt",
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


def prepare() -> dict[str, object]:
    paths = attempt_paths()
    if ATTEMPT.exists():
        raise ContractError(f"ATTEMPT_NAMESPACE_ALREADY_EXISTS:{ATTEMPT}")
    stamps = selected_timestamps()
    pins = {
        "base_config": require_expected(BASE_CONFIG, "base_config"),
        "binary": require_expected(BINARY, "binary"),
        "official_library": require_expected(OFFICIAL_LIBRARY, "official_library"),
        "shared_onnx": require_expected(SHARED_MODEL, "onnx"),
        "shared_cache_seed": require_expected(SHARED_CACHE, "cache_seed"),
        "runner": runner_identity(),
    }
    inventory = input_inventory(stamps)
    ATTEMPT.mkdir(parents=True, exist_ok=False)
    paths["result_dir"].mkdir()
    paths["local_model"].parent.mkdir(parents=True)
    paths["subset_times"].write_bytes(subset_payload(stamps))
    shutil.copy2(SHARED_MODEL, paths["local_model"])
    shutil.copy2(SHARED_CACHE, paths["local_cache"])
    source = BASE_CONFIG.read_text(encoding="utf-8")
    old = 'Extractor.modelPath: "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"'
    new = f'Extractor.modelPath: "{paths["local_model"].parent}/"'
    if source.count(old) != 1:
        raise ContractError("BASE_CONFIG_MODEL_PATH_LINE_MISMATCH")
    paths["runtime_config"].write_text(source.replace(old, new), encoding="utf-8")
    manifest = {
        "schema_version": "aqua-fe-hfnet-v6-a06-2210-2460-coldstart-prepared-v1",
        "status": "PREPARED_NOT_STARTED",
        "prepared_at_utc": now_utc(),
        "scientific_role": "DEVELOPMENT_ONLY_EXTERNAL_LEARNED_WHOLE_SYSTEM_ON_PRIOR_KLT_POSITIVE_WINDOW",
        "claim_boundary": {"accuracy_evaluated": False, "superiority_claimed": False, "retry_permitted": False},
        "selection": {
            "sequence": "AQUALOC archaeology_sequence_06",
            "source_frame_indices_inclusive": [SOURCE_FIRST, SOURCE_LAST],
            "camera_count": CAMERA_COUNT,
            "camera_header_ns_inclusive": [stamps[0], stamps[-1]],
            "span_seconds": (stamps[-1] - stamps[0]) / 1e9,
            "history": "cold_start_at_source_frame_2210; no frame before 2210 passed to HFNet",
        },
        "input_inventory": inventory,
        "pins": pins,
        "derived": {
            "subset_times": identity(paths["subset_times"]),
            "runtime_config": identity(paths["runtime_config"]),
            "local_onnx": require_expected(paths["local_model"], "onnx"),
            "local_cache_pre": require_expected(paths["local_cache"], "cache_seed"),
        },
        "launch": {
            "argv": [str(BINARY), str(paths["runtime_config"]), str(paths["result_dir"]) + "/", str(SOURCE_ROOT), str(paths["subset_times"])],
            "timeout_seconds": TIMEOUT_SECONDS,
            "maximum_popen_invocations": 1,
            "authorization_token": AUTHORIZATION_TOKEN,
        },
    }
    atomic_json(paths["prepared"], manifest)
    return manifest


def load_prepared() -> dict[str, Any]:
    paths = attempt_paths()
    if not paths["prepared"].is_file():
        raise ContractError("PREPARED_MANIFEST_MISSING")
    value = json.loads(paths["prepared"].read_text(encoding="utf-8"))
    if value.get("status") != "PREPARED_NOT_STARTED":
        raise ContractError("PREPARED_MANIFEST_STATUS_INVALID")
    return value


def resource_gate() -> dict[str, object]:
    memory = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True, timeout=10,
    )
    compute = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True, timeout=10,
    )
    errors: list[str] = []
    free_mib: int | None = None
    if memory.returncode != 0 or len([x for x in memory.stdout.splitlines() if x.strip()]) != 1:
        errors.append("GPU_MEMORY_QUERY_INVALID")
    else:
        try:
            _, _, free_mib = [int(x.strip()) for x in memory.stdout.strip().split(",")]
        except ValueError:
            errors.append("GPU_MEMORY_ROW_INVALID")
    applications = [x.strip() for x in compute.stdout.splitlines() if x.strip()]
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_QUERY_INVALID")
    if applications:
        errors.append("GPU_COMPUTE_APPLICATION_PRESENT")
    if free_mib is None or free_mib < MIN_GPU_FREE_MIB:
        errors.append("GPU_FREE_MEMORY_BELOW_MINIMUM")
    conflicting_executables: list[dict[str, object]] = []
    forbidden = {
        "mono_inertial_euroc_headless_v3", "mono_inertial_euroc",
        "stereo_inertial_euroc", "vins_node", "roscore",
    }
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            executable = Path(os.readlink(entry / "exe")).name
        except OSError:
            continue
        if executable in forbidden:
            conflicting_executables.append({"pid": int(entry.name), "executable": executable})
    if conflicting_executables:
        errors.append("CONFLICTING_SLAM_OR_ROS_PROCESS_PRESENT")
    return {
        "ready": not errors, "errors": errors, "free_mib": free_mib,
        "minimum_free_mib": MIN_GPU_FREE_MIB, "compute_applications": applications,
        "conflicting_executables": conflicting_executables,
    }


def check(require_unclaimed: bool = True) -> dict[str, object]:
    paths = attempt_paths()
    manifest = load_prepared()
    errors: list[str] = []
    try:
        if manifest["pins"]["runner"] != runner_identity():
            errors.append("RUNNER_DRIFT")
        require_expected(BASE_CONFIG, "base_config")
        require_expected(BINARY, "binary")
        require_expected(OFFICIAL_LIBRARY, "official_library")
        require_expected(SHARED_MODEL, "onnx")
        require_expected(SHARED_CACHE, "cache_seed")
        require_expected(paths["local_model"], "onnx")
        require_expected(paths["local_cache"], "cache_seed")
        if manifest["derived"]["subset_times"] != identity(paths["subset_times"]):
            errors.append("SUBSET_TIMES_DRIFT")
        if manifest["derived"]["runtime_config"] != identity(paths["runtime_config"]):
            errors.append("RUNTIME_CONFIG_DRIFT")
        if manifest["input_inventory"] != input_inventory(selected_timestamps()):
            errors.append("SELECTED_INPUT_DRIFT")
    except (ContractError, KeyError, OSError) as error:
        errors.append(str(error))
    if require_unclaimed and paths["claim"].exists():
        errors.append("PROCESS_START_ALREADY_CLAIMED_NO_RETRY")
    if paths["result"].exists():
        errors.append("RUN_RESULT_ALREADY_EXISTS_TERMINAL")
    if any(paths["result_dir"].iterdir()):
        errors.append("RESULT_DIRECTORY_NOT_EMPTY")
    resource = resource_gate()
    errors.extend(str(item) for item in resource["errors"])
    return {"schema_version": "aqua-fe-hfnet-v6-a06-2210-2460-coldstart-check-v1", "ready": not errors, "errors": errors, "resource_gate": resource, "checked_at_utc": now_utc()}


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
            stamp = int(fields[0])
            pose = [float(value) for value in fields[1:]]
        except ValueError:
            audit["errors"].append(f"ROW_{index}_PARSE")
            continue
        if not all(math.isfinite(value) for value in pose):
            audit["errors"].append(f"ROW_{index}_NONFINITE")
        pose_stamps.append(stamp)
    strict = all(right > left for left, right in zip(pose_stamps, pose_stamps[1:]))
    associated: list[int | None] = []
    association_errors_ns: list[int] = []
    for value in pose_stamps:
        insertion = bisect.bisect_left(stamps, value)
        candidates = [candidate for candidate in (insertion - 1, insertion) if 0 <= candidate < len(stamps)]
        if not candidates:
            associated.append(None)
            continue
        nearest = min(candidates, key=lambda candidate: abs(stamps[candidate] - value))
        error_ns = abs(stamps[nearest] - value)
        associated.append(nearest if error_ns <= 256 else None)
        association_errors_ns.append(error_ns)
    unique = all(value is not None for value in associated) and len(set(associated)) == len(associated)
    valid_indices = [int(value) for value in associated if value is not None]
    longest = 0
    run = 0
    previous = None
    for value in valid_indices:
        run = run + 1 if previous is not None and value == previous + 1 else 1
        longest = max(longest, run)
        previous = value
    audit.update({
        "identity": identity(path), "pose_count": len(pose_stamps), "strictly_increasing_timestamps": strict,
        "unique_camera_associations_within_256ns": unique,
        "association_max_abs_error_ns": max(association_errors_ns) if association_errors_ns else None,
        "first_relative_index": valid_indices[0] if valid_indices else None,
        "last_relative_index": valid_indices[-1] if valid_indices else None, "coverage_fraction": len(valid_indices) / CAMERA_COUNT,
        "longest_contiguous_count": longest, "longest_contiguous_fraction": longest / CAMERA_COUNT,
        "valid": bool(not audit["errors"] and strict and unique),
    })
    return audit


def runtime_environment() -> dict[str, str]:
    return {
        "CUDA_VISIBLE_DEVICES": "0", "HOME": "/home/ma", "USER": "ma", "LANG": "C", "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LD_LIBRARY_PATH": ":".join([
            "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib",
            "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Thirdparty/g2o/lib",
            "/home/ma/SLAM/aqua_deps/install/lib",
            "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/lib/x86_64-linux-gnu",
            "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.6/targets/x86_64-linux/lib",
            "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.8/targets/x86_64-linux/lib",
        ]),
    }


def run(token: str) -> dict[str, object]:
    if token != AUTHORIZATION_TOKEN:
        raise ContractError("AUTHORIZATION_TOKEN_MISMATCH")
    paths = attempt_paths()
    prepared = load_prepared()
    precheck = check(require_unclaimed=True)
    if not precheck["ready"]:
        raise ContractError("PRESTART_CHECK_FAILED:" + ";".join(precheck["errors"]))
    claim = {
        "schema_version": "aqua-fe-hfnet-v6-a06-2210-2460-coldstart-claim-v1", "status": "O_EXCL_CLAIM_BEFORE_ONLY_POPEN",
        "claimed_at_utc": now_utc(), "authorization_token": token, "maximum_popen_invocations": 1, "retry": False,
        "prepared_manifest": identity(paths["prepared"]), "runner": runner_identity(), "argv": prepared["launch"]["argv"],
    }
    atomic_json(paths["claim"], claim, exclusive=True)
    started = now_utc()
    start_monotonic = time.monotonic()
    timed_out = False
    termination: str | None = None
    return_code: int | None = None
    supervisor_error: str | None = None
    with paths["stdout"].open("wb") as stdout, paths["stderr"].open("wb") as stderr:
        process = subprocess.Popen(prepared["launch"]["argv"], cwd=str(ATTEMPT), env=runtime_environment(), stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            return_code = process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            timed_out = True
            termination = "SIGTERM_THEN_SIGKILL_IF_NEEDED"
            os.killpg(process.pid, signal.SIGTERM)
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                return_code = process.wait(timeout=10)
        except Exception as error:  # terminal after claim; never retry
            supervisor_error = f"{type(error).__name__}:{error}"
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                return_code = process.wait(timeout=10)
    duration = time.monotonic() - start_monotonic
    stamps = selected_timestamps()
    trajectory = parse_trajectory(paths["result_dir"] / "trajectory.txt", stamps)
    keyframes = parse_trajectory(paths["result_dir"] / "trajectory_keyframe.txt", stamps)
    input_post = input_inventory(stamps)
    input_unchanged = input_post == prepared["input_inventory"]
    onnx_unchanged = require_expected(paths["local_model"], "onnx") == prepared["derived"]["local_onnx"]
    execution_ok = return_code == 0 and not timed_out and supervisor_error is None
    usability_ok = bool(
        execution_ok and input_unchanged and onnx_unchanged and trajectory.get("valid")
        and trajectory.get("coverage_fraction", 0.0) >= 0.70
        and trajectory.get("longest_contiguous_fraction", 0.0) >= 0.70
        and keyframes.get("valid") and keyframes.get("pose_count", 0) >= 1
    )
    result = {
        "schema_version": SCHEMA,
        "status": "PASS_EXPLORATORY_COLDSTART_USABILITY" if usability_ok else "FAIL_EXPLORATORY_COLDSTART_USABILITY",
        "scientific_role": prepared["scientific_role"], "errors": [],
        "execution": {
            "started_at_utc": started, "ended_at_utc": now_utc(), "duration_seconds": duration,
            "raw_returncode": return_code, "timed_out": timed_out, "termination": termination,
            "supervisor_error": supervisor_error, "popen_invocations": 1, "retry_performed": False, "retry_permitted": False,
        },
        "selection": prepared["selection"],
        "support": {"trajectory": trajectory, "keyframes": keyframes},
        "integrity": {
            "selected_input_unchanged": input_unchanged, "local_onnx_unchanged": onnx_unchanged,
            "input_post": input_post, "local_cache_post": identity(paths["local_cache"]),
        },
        "pins": {"prepared_manifest": identity(paths["prepared"]), "process_start_claim": identity(paths["claim"]), "runner": runner_identity(), "stdout": identity(paths["stdout"]), "stderr": identity(paths["stderr"])},
        "claim_boundary": {"accuracy_evaluated": False, "superiority_claimed": False, "formal_paper_claim_authorized": False, "development_only": True},
        "terminal_contract": {"retry_after_pass_or_fail": False, "attempt_consumed": True},
    }
    atomic_json(paths["result"], result, exclusive=True)
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
            value = check(require_unclaimed=True)
        else:
            value = run(args.authorization_token)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
        return 0 if value.get("ready", True) else 2
    except (ContractError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "error": f"{type(error).__name__}:{error}"}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
