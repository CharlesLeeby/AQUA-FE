#!/usr/bin/env python3
"""One-shot A09 HFNet warm-start run with non-isolated GPU resources.

This controller is a deliberately separate, development-only namespace for a
single HFNet-SLAM execution while ToDesk and/or VINS may be using the GPU.  It
reuses the immutable A09 0..4400 materialization and the frozen HFNet runtime
stack, but it is not a substitute for the resource-isolated attempt.  Accuracy,
ranking, superiority, and formal paper claims are explicitly unauthorized.

Preparation and execution are no-clobber.  A process-start claim is committed
with O_EXCL semantics before the only possible HFNet Popen, and a claimed
attempt is terminal after either success or failure.  There is no retry path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import (  # noqa: E402
    run_hfnet_v6_a09_0000_4400_score_4000_4400_warmstart_v1 as formal,
)


base = formal.inherited.profile.base
RUNNER = Path(__file__).resolve()
FORMAL_WARM_RUNNER = Path(formal.__file__).resolve()
FORMAL_WARM_RUNNER_SIZE = 69666
FORMAL_WARM_RUNNER_SHA256 = (
    "21981cc560458fd7d47d1d5b8d752a3ad208f499475e0721dd9f758b008a9093"
)

INPUT_ROOT = formal.INPUT_ROOT
INPUT_MANIFEST = formal.INPUT_MANIFEST
INPUT_AUDIT = formal.INPUT_AUDIT
INPUT_PAYLOAD_SHA256 = formal.INPUT_PAYLOAD_SHA256
ATTEMPT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/corun/"
    "a09_0000_4400_score_4000_4400_todesk_corun_development_only/attempt_001"
)

FEED_FIRST = formal.FEED_FIRST
FEED_LAST = formal.FEED_LAST
FEED_COUNT = formal.FEED_COUNT
SCORE_FIRST = formal.SCORE_FIRST
SCORE_LAST = formal.SCORE_LAST
SCORE_COUNT = formal.SCORE_COUNT
TIMEOUT_SECONDS = 600

# The helper accepts an explicit threshold for unit testing and future profiles,
# while this experiment freezes the prepared and launch contract at 2800 MiB.
MIN_GPU_FREE_MIB = 2800
AUTHORIZATION_TOKEN = (
    "HFNET_V6_A09_0000_4400_SCORE_4000_4400_"
    "TODESK_CORUN_DEVELOPMENT_ONLY_ATTEMPT_001_START_EXACTLY_ONCE"
)
SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-"
    "todesk-corun-development-only-result-v1"
)
PREPARED_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-"
    "todesk-corun-development-only-prepared-v1"
)
CLAIM_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-"
    "todesk-corun-development-only-claim-v1"
)
CHECK_SCHEMA = (
    "aqua-fe-hfnet-v6-a09-0000-4400-score-4000-4400-"
    "todesk-corun-development-only-check-v1"
)
SCIENTIFIC_ROLE = (
    "TODESK_CORUN_DEVELOPMENT_ONLY_HFNET_WARMSTART_RUNABILITY_"
    "ON_PRIOR_KLT_POSITIVE_WINDOW"
)

BASE_CONFIG = base.BASE_CONFIG
BINARY = base.BINARY
OFFICIAL_LIBRARY = base.OFFICIAL_LIBRARY
SHARED_MODEL = base.SHARED_MODEL
SHARED_CACHE = base.SHARED_CACHE

RESOURCE_POLICY = {
    "resource_isolation": False,
    "todesk_corun": True,
    "minimum_prestart_free_gpu_mib": MIN_GPU_FREE_MIB,
    "nonbaseline_compute_apps_permitted": True,
    "todesk_compute_app_permitted": True,
    "vins_node_compute_app_permitted": True,
    "hfnet_or_orb_or_learned_baseline_process_permitted": False,
}
CLAIM_BOUNDARY = {
    "development_only": True,
    "accuracy_evaluated": False,
    "accuracy_claim_authorized": False,
    "ranking_authorized": False,
    "superiority_claimed": False,
    "formal_paper_claim_authorized": False,
    "fair_head_to_head": False,
    "retry_permitted": False,
}

_ORIGINAL_POPEN = subprocess.Popen
_POPEN_INVOCATIONS = 0
_CLAIM_CREATED_THIS_PROCESS = False
_ACTIVE_CHILD: Any = None


class ContractError(RuntimeError):
    """Fail-closed experiment contract error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"NOT_REGULAR_NONSYMLINK_FILE:{path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _publish_bytes_exclusive_atomic(path: Path, payload: bytes) -> None:
    """Publish complete bytes without replacing an existing terminal artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.pending.", dir=str(path.parent)
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o444)
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _publish_json_exclusive_atomic(path: Path, value: object) -> None:
    _publish_bytes_exclusive_atomic(path, _canonical_json(value))


def paths() -> dict[str, Path]:
    return {
        "subset_times": ATTEMPT / "cam0_times_0000_4400.txt",
        "runtime_config": ATTEMPT / "runtime_config_model_path_only.yaml",
        "local_model": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.onnx",
        "local_cache": ATTEMPT / "run_local_model/HFNet-RT/HF-Net.cache",
        "prepared": ATTEMPT / "prepared_manifest.json",
        "claim": ATTEMPT / "process_start_claim.json",
        "result": ATTEMPT / "run_result.json",
        "stdout": ATTEMPT / "headless.stdout.log",
        "stderr": ATTEMPT / "headless.stderr.log",
        "result_dir": ATTEMPT / "result",
        "score_trajectory": ATTEMPT / "result/trajectory_score_4000_4400.txt",
    }


def validate_code_authority() -> dict[str, Any]:
    formal.validate_code_authority()
    if (
        FORMAL_WARM_RUNNER.is_symlink()
        or not FORMAL_WARM_RUNNER.is_file()
        or FORMAL_WARM_RUNNER.stat().st_size != FORMAL_WARM_RUNNER_SIZE
        or _sha256(FORMAL_WARM_RUNNER) != FORMAL_WARM_RUNNER_SHA256
    ):
        raise ContractError("FORMAL_WARM_RUNNER_IDENTITY_MISMATCH")
    return {
        "formal_resource_isolated_warm_runner": _identity(FORMAL_WARM_RUNNER),
        "frozen_runtime_stack": {
            "base_config": base.require_expected(BASE_CONFIG, "base_config"),
            "binary": base.require_expected(BINARY, "binary"),
            "official_library": base.require_expected(
                OFFICIAL_LIBRARY, "official_library"
            ),
            "shared_onnx": base.require_expected(SHARED_MODEL, "onnx"),
            "shared_cache_seed": base.require_expected(SHARED_CACHE, "cache_seed"),
        },
    }


def validate_input_authority() -> dict[str, Any]:
    """Reuse the canonical, independently audited A09 warm input validator."""
    return formal.validate_input_authority()


def selected_timestamps() -> list[int]:
    return formal.selected_timestamps()


def _expected_selection() -> dict[str, Any]:
    value = dict(formal._expected_prepared_selection())
    value["execution_profile"] = "TODESK_CORUN_DEVELOPMENT_ONLY"
    value["resource_isolation"] = False
    return value


def _expected_comparison_boundary() -> dict[str, Any]:
    return {
        "runability_only": True,
        "accuracy_gate_open": False,
        "ranking_authorized": False,
        "reason": (
            "This attempt permits concurrent nonbaseline GPU applications and "
            "therefore cannot support accuracy or ranking claims."
        ),
    }


def _expected_argv() -> list[str]:
    return [
        str(BINARY),
        str(paths()["runtime_config"]),
        str(paths()["result_dir"]) + "/",
        str(INPUT_ROOT),
        str(paths()["subset_times"]),
    ]


def _expected_input_authority() -> dict[str, object]:
    return {
        "materialization_manifest": _identity(INPUT_MANIFEST),
        "independent_audit_receipt": _identity(INPUT_AUDIT),
        "payload_sha256_excluding_manifest": INPUT_PAYLOAD_SHA256,
    }


def prepare() -> dict[str, Any]:
    """Materialize the fresh co-run attempt; this function does not launch HFNet."""
    if ATTEMPT.exists() or ATTEMPT.is_symlink():
        raise ContractError(f"ATTEMPT_NAMESPACE_ALREADY_EXISTS:{ATTEMPT}")
    validate_input_authority()
    validate_code_authority()
    stamps = selected_timestamps()
    if len(stamps) != FEED_COUNT:
        raise ContractError("TIMESTAMP_COUNT_MISMATCH")

    ATTEMPT.mkdir(parents=True, exist_ok=False)
    paths()["result_dir"].mkdir()
    paths()["local_model"].parent.mkdir(parents=True)
    paths()["subset_times"].write_bytes(
        ("\n".join(str(value) for value in stamps) + "\n").encode("ascii")
    )
    shutil.copy2(SHARED_MODEL, paths()["local_model"])
    shutil.copy2(SHARED_CACHE, paths()["local_cache"])

    source = BASE_CONFIG.read_text(encoding="utf-8")
    old = (
        'Extractor.modelPath: '
        '"/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/"'
    )
    replacement = f'Extractor.modelPath: "{paths()["local_model"].parent}/"'
    if source.count(old) != 1:
        raise ContractError("BASE_CONFIG_MODEL_PATH_LINE_MISMATCH")
    paths()["runtime_config"].write_text(
        source.replace(old, replacement), encoding="utf-8"
    )

    manifest: dict[str, Any] = {
        "schema_version": PREPARED_SCHEMA,
        "status": "PREPARED_NOT_STARTED",
        "prepared_at_utc": base.now_utc(),
        "scientific_role": SCIENTIFIC_ROLE,
        "selection": _expected_selection(),
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "resource_policy": dict(RESOURCE_POLICY),
        "comparison_boundary": _expected_comparison_boundary(),
        "input_authority": _expected_input_authority(),
        "controller_authority": validate_code_authority(),
        "pins": {
            "runner": _identity(RUNNER),
            "subset_times": _identity(paths()["subset_times"]),
            "runtime_config": _identity(paths()["runtime_config"]),
            "local_onnx": base.require_expected(paths()["local_model"], "onnx"),
            "local_cache_seed": base.require_expected(
                paths()["local_cache"], "cache_seed"
            ),
        },
        "launch": {
            "argv": _expected_argv(),
            "timeout_seconds": TIMEOUT_SECONDS,
            "maximum_popen_invocations": 1,
            "authorization_token": AUTHORIZATION_TOKEN,
            "minimum_prestart_free_gpu_mib": MIN_GPU_FREE_MIB,
        },
    }
    _publish_json_exclusive_atomic(paths()["prepared"], manifest)
    return manifest


def load_prepared() -> dict[str, Any]:
    path = paths()["prepared"]
    if path.is_symlink() or not path.is_file():
        raise ContractError("PREPARED_MANIFEST_MISSING_OR_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    _validate_prepared(value)
    return value


def _validate_prepared(value: Mapping[str, Any]) -> None:
    launch = value.get("launch", {})
    pins = value.get("pins", {})
    if (
        value.get("schema_version") != PREPARED_SCHEMA
        or value.get("status") != "PREPARED_NOT_STARTED"
        or value.get("scientific_role") != SCIENTIFIC_ROLE
        or value.get("selection") != _expected_selection()
        or value.get("claim_boundary") != CLAIM_BOUNDARY
        or value.get("resource_policy") != RESOURCE_POLICY
        or value.get("comparison_boundary") != _expected_comparison_boundary()
        or value.get("input_authority") != _expected_input_authority()
        or value.get("controller_authority") != validate_code_authority()
        or pins.get("runner") != _identity(RUNNER)
        or pins.get("subset_times") != _identity(paths()["subset_times"])
        or pins.get("runtime_config") != _identity(paths()["runtime_config"])
        or pins.get("local_onnx")
        != base.require_expected(paths()["local_model"], "onnx")
        or pins.get("local_cache_seed")
        != base.require_expected(paths()["local_cache"], "cache_seed")
        or launch.get("argv") != _expected_argv()
        or launch.get("timeout_seconds") != TIMEOUT_SECONDS
        or launch.get("maximum_popen_invocations") != 1
        or launch.get("authorization_token") != AUTHORIZATION_TOKEN
        or launch.get("minimum_prestart_free_gpu_mib") != MIN_GPU_FREE_MIB
    ):
        raise ContractError("PREPARED_LAUNCH_CONTRACT_MISMATCH")


def _baseline_reason(name: str) -> str | None:
    """Classify only HFNet/ORB and other learned-baseline process names."""
    normalized = Path(name.strip()).name.lower().replace(" ", "_")
    exact = {
        "mono_inertial_euroc_headless_v3",
        "mono_inertial_euroc",
        "stereo_inertial_euroc",
    }
    if normalized in exact or "hfnet_slam" in normalized or normalized.startswith("run_hfnet_"):
        return "HFNET_PROCESS"
    if any(token in normalized for token in ("orb_slam", "orb-slam", "orbslam")):
        return "ORB_SLAM_PROCESS"
    if any(
        token in normalized
        for token in (
            "droid_slam",
            "droid-slam",
            "dpvo",
            "lightglue",
            "superpoint",
            "loftr",
            "xfeat",
        )
    ):
        return "LEARNED_BASELINE_PROCESS"
    return None


def _ancestor_pids(pid: int) -> set[int]:
    ancestors = {pid}
    current = pid
    while current > 1:
        try:
            fields = (Path("/proc") / str(current) / "stat").read_text(
                encoding="ascii", errors="replace"
            ).split()
            parent = int(fields[3])
        except (OSError, ValueError, IndexError):
            break
        if parent in ancestors or parent <= 0:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def scan_forbidden_processes(proc_root: Path = Path("/proc")) -> list[dict[str, object]]:
    """Reject competing learned-system jobs while allowing ToDesk and VINS."""
    conflicts: list[dict[str, object]] = []
    ignored = _ancestor_pids(os.getpid()) if proc_root == Path("/proc") else {os.getpid()}
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        raise ContractError(f"PROC_SCAN_FAILED:{error}") from error
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in ignored:
            continue
        executable = ""
        arguments: list[str] = []
        try:
            executable = Path(os.readlink(entry / "exe")).name
        except OSError:
            pass
        try:
            arguments = [
                item.decode("utf-8", "replace")
                for item in (entry / "cmdline").read_bytes().split(b"\0")
                if item
            ]
        except OSError:
            pass
        reason = _baseline_reason(executable)
        matched = executable
        if reason is None:
            for argument in arguments[1:]:
                candidate = Path(argument).name
                reason = _baseline_reason(candidate)
                if reason is not None:
                    matched = candidate
                    break
        if reason is not None:
            conflicts.append(
                {
                    "pid": pid,
                    "reason": reason,
                    "matched_name": matched,
                    "executable": executable,
                }
            )
    return sorted(conflicts, key=lambda row: int(row["pid"]))


def _parse_compute_rows(payload: str) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for line_number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            continue
        fields = [item.strip() for item in raw.split(",")]
        if len(fields) != 3:
            errors.append(f"GPU_COMPUTE_ROW_{line_number}_INVALID")
            continue
        try:
            pid = int(fields[0])
            used_mib = int(fields[2])
        except ValueError:
            errors.append(f"GPU_COMPUTE_ROW_{line_number}_INVALID")
            continue
        rows.append(
            {
                "pid": pid,
                "process_name": fields[1],
                "used_memory_mib": used_mib,
                "forbidden_reason": _baseline_reason(fields[1]),
            }
        )
    return rows, errors


def resource_gate(minimum_free_mib: int = MIN_GPU_FREE_MIB) -> dict[str, Any]:
    """Permit nonbaseline co-users, but reject learned-baseline contention."""
    if not isinstance(minimum_free_mib, int) or minimum_free_mib <= 0:
        raise ContractError("MINIMUM_FREE_MIB_INVALID")
    memory = subprocess.run(
        [
            "nvidia-smi",
            "--query-gpu=memory.total,memory.used,memory.free",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    compute = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name,used_memory",
            "--format=csv,noheader,nounits",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    errors: list[str] = []
    total_mib: int | None = None
    used_mib: int | None = None
    free_mib: int | None = None
    memory_rows = [row for row in memory.stdout.splitlines() if row.strip()]
    if memory.returncode != 0 or len(memory_rows) != 1:
        errors.append("GPU_MEMORY_QUERY_INVALID")
    else:
        try:
            total_mib, used_mib, free_mib = [
                int(item.strip()) for item in memory_rows[0].split(",")
            ]
        except (ValueError, TypeError):
            errors.append("GPU_MEMORY_ROW_INVALID")
    compute_rows, compute_errors = _parse_compute_rows(compute.stdout)
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_QUERY_INVALID")
    errors.extend(compute_errors)
    forbidden_compute = [
        row for row in compute_rows if row.get("forbidden_reason") is not None
    ]
    allowed_compute = [
        row for row in compute_rows if row.get("forbidden_reason") is None
    ]
    if forbidden_compute:
        errors.append("FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_COMPUTE_APP_PRESENT")
    if free_mib is None or free_mib < minimum_free_mib:
        errors.append("GPU_FREE_MEMORY_BELOW_CORUN_MINIMUM")
    try:
        forbidden_processes = scan_forbidden_processes()
    except ContractError as error:
        forbidden_processes = []
        errors.append(str(error))
    if forbidden_processes:
        errors.append("FORBIDDEN_HFNET_OR_ORB_OR_LEARNED_PROCESS_PRESENT")
    errors = list(dict.fromkeys(errors))
    return {
        "ready": not errors,
        "errors": errors,
        "resource_isolation": False,
        "todesk_corun": True,
        "gpu_memory": {
            "total_mib": total_mib,
            "used_mib": used_mib,
            "free_mib": free_mib,
            "minimum_free_mib": minimum_free_mib,
        },
        "allowed_compute_applications": allowed_compute,
        "forbidden_compute_applications": forbidden_compute,
        "forbidden_baseline_processes": forbidden_processes,
    }


def check(*, require_unclaimed: bool = True) -> dict[str, Any]:
    errors: list[str] = []
    prepared: dict[str, Any] | None = None
    try:
        prepared = load_prepared()
        validate_input_authority()
    except (ContractError, formal.inherited.profile.base.ContractError, OSError, KeyError) as error:
        errors.append(f"AUTHORITY_OR_PREPARED_INVALID:{type(error).__name__}:{error}")
    path_map = paths()
    if require_unclaimed and (path_map["claim"].exists() or path_map["claim"].is_symlink()):
        errors.append("PROCESS_START_ALREADY_CLAIMED_NO_RETRY")
    if path_map["result"].exists() or path_map["result"].is_symlink():
        errors.append("RUN_RESULT_ALREADY_EXISTS_TERMINAL")
    try:
        if any(path_map["result_dir"].iterdir()):
            errors.append("RESULT_DIRECTORY_NOT_EMPTY")
    except OSError as error:
        errors.append(f"RESULT_DIRECTORY_INVALID:{error}")
    for label in ("stdout", "stderr", "score_trajectory"):
        if path_map[label].exists() or path_map[label].is_symlink():
            errors.append(f"PREEXISTING_NO_CLOBBER_ARTIFACT:{label}")
    try:
        resource = resource_gate(MIN_GPU_FREE_MIB)
    except (OSError, subprocess.SubprocessError, ContractError) as error:
        resource = {
            "ready": False,
            "errors": [f"RESOURCE_GATE_EXCEPTION:{type(error).__name__}:{error}"],
            "resource_isolation": False,
            "todesk_corun": True,
        }
    errors.extend(str(item) for item in resource.get("errors", []))
    errors = list(dict.fromkeys(errors))
    return {
        "schema_version": CHECK_SCHEMA,
        "ready": not errors,
        "errors": errors,
        "checked_at_utc": base.now_utc(),
        "prepared_loaded": prepared is not None,
        "resource_policy": dict(RESOURCE_POLICY),
        "resource_gate": resource,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }


def _spawn_exact(argv: Sequence[str], **kwargs: Any) -> Any:
    global _POPEN_INVOCATIONS
    expected_keys = {"cwd", "env", "stdout", "stderr", "start_new_session"}
    contract_ok = (
        list(argv) == _expected_argv()
        and set(kwargs) == expected_keys
        and kwargs.get("cwd") == str(ATTEMPT)
        and kwargs.get("env") == base.runtime_environment()
        and getattr(kwargs.get("stdout"), "name", None) == str(paths()["stdout"])
        and getattr(kwargs.get("stderr"), "name", None) == str(paths()["stderr"])
        and kwargs.get("start_new_session") is True
        and _POPEN_INVOCATIONS == 0
        and paths()["claim"].is_file()
        and not paths()["claim"].is_symlink()
    )
    if not contract_ok:
        raise ContractError("ONLY_POPEN_EXACT_LAUNCH_CONTRACT_MISMATCH")
    _POPEN_INVOCATIONS += 1
    return _ORIGINAL_POPEN(list(argv), **kwargs)


def _terminate_and_reap(process: Any) -> tuple[int | None, str, bool]:
    if process is None:
        return None, "NO_CHILD_OBJECT", True
    if process.poll() is not None:
        return process.returncode, "ALREADY_EXITED", True
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        return process.wait(timeout=10), "SIGTERM", True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        while process.poll() is None:
            try:
                return process.wait(timeout=10), "SIGTERM_THEN_SIGKILL", True
            except subprocess.TimeoutExpired:
                continue
        return process.returncode, "SIGTERM_THEN_SIGKILL", True


def _start_zero_kf_watchdog(process: Any) -> tuple[threading.Event, threading.Thread, dict[str, Any]]:
    stop = threading.Event()
    state: dict[str, Any] = {
        "triggered": False,
        "failure_code": None,
        "pid": getattr(process, "pid", None),
        "monitor_scope": "EXACT_CHILD_LIFETIME_ONLY",
    }

    def monitor() -> None:
        while not stop.wait(0.25):
            if process.poll() is not None:
                return
            try:
                payload = paths()["stdout"].read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                continue
            saving = payload.rfind("Saving trajectory to ")
            if saving < 0:
                continue
            tail = payload[saving:]
            atlas_rows = list(
                re.finditer(r"There are (\d+) maps in (?:the )?atlas", tail)
            )
            if not atlas_rows:
                continue
            atlas = atlas_rows[-1]
            counts = [
                int(item)
                for item in re.findall(
                    r"Map \d+ has (\d+) KFs", tail[atlas.end() :]
                )
            ]
            expected = int(atlas.group(1))
            if len(counts) < expected or any(item > 0 for item in counts[:expected]):
                continue
            state.update(
                {
                    "triggered": True,
                    "failure_code": "ALL_MAPS_ZERO_KEYFRAME_OFFICIAL_SAVE_HANG_WATCHDOG",
                    "triggered_at_utc": base.now_utc(),
                }
            )
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return

    thread = threading.Thread(
        target=monitor,
        name="hfnet-todesk-corun-zero-kf-watchdog",
        daemon=True,
    )
    thread.start()
    return stop, thread, state


def _pose_support(stamps: Sequence[int]) -> tuple[dict[str, Any], dict[str, Any]]:
    trajectory = formal._parse_pose_rows(paths()["result_dir"] / "trajectory.txt", stamps)
    keyframes = formal._parse_pose_rows(
        paths()["result_dir"] / "trajectory_keyframe.txt", stamps
    )
    return trajectory, keyframes


def _adjudicate(
    execution: Mapping[str, Any], stamps: Sequence[int]
) -> tuple[dict[str, Any], list[str]]:
    trajectory, keyframes = _pose_support(stamps)
    trajectory_rows = trajectory.get("rows", [])
    keyframe_rows = keyframes.get("rows", [])
    score_rows = [
        row
        for row in trajectory_rows
        if SCORE_FIRST <= int(row["camera_index"]) <= SCORE_LAST
    ]
    score_indices = [int(row["camera_index"]) for row in score_rows]
    expected_indices = list(range(SCORE_FIRST, SCORE_LAST + 1))
    all_indices = [int(row["camera_index"]) for row in trajectory_rows]
    try:
        boundary = all_indices.index(SCORE_FIRST)
    except ValueError:
        boundary = -1
    boundary_continuous = (
        boundary > 0 and all_indices[boundary - 1] == SCORE_FIRST - 1
    )
    score_keyframes = [
        row
        for row in keyframe_rows
        if SCORE_FIRST <= int(row["camera_index"]) <= SCORE_LAST
    ]
    log = formal._atlas_and_resets(paths()["stdout"])
    failures: list[str] = []
    if (
        execution.get("raw_returncode") != 0
        or execution.get("timed_out") is not False
        or execution.get("supervisor_error") is not None
        or execution.get("child_reaped_before_post_audit") is not True
    ):
        failures.append("EXECUTION_NOT_CLEAN")
    if trajectory.get("valid") is not True:
        failures.append("TRAJECTORY_INVALID")
    if score_indices != expected_indices:
        failures.append("SCORE_TRAJECTORY_NOT_401_OF_401_CONTIGUOUS")
    if not boundary_continuous:
        failures.append("PREROLL_TO_SCORE_BOUNDARY_NOT_CONTINUOUS")
    if keyframes.get("valid") is not True or not score_keyframes:
        failures.append("NO_VALID_SCORE_KEYFRAME")
    if log.get("valid") is not True or log.get("final_atlas_nonempty") is not True:
        failures.append("FINAL_ATLAS_EMPTY_OR_UNPARSEABLE")
    if log.get("pre_score_initialized") is not True:
        failures.append("NO_INITIALIZED_MAP_CARRIED_INTO_SCORE_WINDOW")
    if log.get("score_window_init_frame_ids"):
        failures.append("SCORE_WINDOW_REINITIALIZATION")
    if log.get("score_window_reset_events"):
        failures.append("SCORE_WINDOW_ACTIVE_MAP_RESET")
    if log.get("reset_parse_complete") is not True:
        failures.append("ACTIVE_MAP_RESET_BOUNDARY_UNRESOLVED")

    crop_identity: dict[str, object] | None = None
    if not failures:
        payload = ("\n".join(str(row["line"]) for row in score_rows) + "\n").encode(
            "ascii"
        )
        try:
            _publish_bytes_exclusive_atomic(paths()["score_trajectory"], payload)
            crop_identity = _identity(paths()["score_trajectory"])
        except Exception as error:
            failures.append(
                f"SCORE_TRAJECTORY_CROP_PUBLICATION_FAILED:{type(error).__name__}:{error}"
            )
    adjudication = {
        "passed": not failures,
        "failure_codes": failures,
        "feed": {
            "indices_inclusive": [FEED_FIRST, FEED_LAST],
            "camera_count": FEED_COUNT,
        },
        "score": {
            "indices_inclusive": [SCORE_FIRST, SCORE_LAST],
            "camera_count": SCORE_COUNT,
            "pose_count": len(score_rows),
            "keyframe_count": len(score_keyframes),
            "exact_401_of_401_contiguous": score_indices == expected_indices,
            "preroll_to_score_boundary_continuous": boundary_continuous,
            "trajectory_crop": crop_identity,
        },
        "full_trajectory": formal._public_pose_audit(trajectory),
        "keyframes": formal._public_pose_audit(keyframes),
        "runtime_log": log,
        "claim_boundary": dict(CLAIM_BOUNDARY),
    }
    return adjudication, failures


def _terminal_value(
    *,
    prepared: Mapping[str, Any],
    precheck: Mapping[str, Any],
    execution: Mapping[str, Any],
    watchdog: Mapping[str, Any],
    errors: Sequence[str],
) -> dict[str, Any]:
    failure_codes: list[str] = []
    adjudication: dict[str, Any]
    try:
        stamps = selected_timestamps()
        adjudication, failure_codes = _adjudicate(execution, stamps)
    except Exception as error:
        failure_codes = ["POSTRUN_ADJUDICATION_EXCEPTION"]
        adjudication = {
            "passed": False,
            "failure_codes": list(failure_codes),
            "error": f"{type(error).__name__}:{error}",
            "claim_boundary": dict(CLAIM_BOUNDARY),
        }
    if watchdog.get("triggered") is True:
        failure_codes.append(
            str(
                watchdog.get("failure_code")
                or "ALL_MAPS_ZERO_KEYFRAME_OFFICIAL_SAVE_HANG_WATCHDOG"
            )
        )
    if execution.get("popen_invocations") != 1:
        failure_codes.append("HFNET_POPEN_INVOCATION_COUNT_NOT_ONE")
    if execution.get("raw_returncode") not in (0,):
        failure_codes.append("HFNET_PROCESS_NONZERO_OR_MISSING_RETURN")
    if execution.get("timed_out") is True:
        failure_codes.append("HFNET_EXECUTION_TIMEOUT")
    if execution.get("supervisor_error") is not None:
        failure_codes.append("SUPERVISOR_EXCEPTION")
    failure_codes = list(dict.fromkeys(failure_codes))
    passed = adjudication.get("passed") is True and not failure_codes
    return {
        "schema_version": SCHEMA,
        "status": (
            "PASS_TODESK_CORUN_DEVELOPMENT_ONLY_RUNABILITY"
            if passed
            else "FAIL_TODESK_CORUN_DEVELOPMENT_ONLY_RUNABILITY"
        ),
        "scientific_role": SCIENTIFIC_ROLE,
        "errors": list(errors),
        "failure_codes": failure_codes,
        "execution": dict(execution),
        "selection": prepared.get("selection", _expected_selection()),
        "score_adjudication": adjudication,
        "watchdog": dict(watchdog),
        "resource_context": {
            "resource_isolation": False,
            "todesk_corun": True,
            "prestart_gate": precheck.get("resource_gate"),
            "accuracy_authorized": False,
            "ranking_authorized": False,
        },
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "pins": {
            "runner": _identity(RUNNER),
            "prepared_manifest": _identity(paths()["prepared"]),
            "process_start_claim": _identity(paths()["claim"]),
        },
        "terminal_contract": {
            "retry_after_pass_or_fail": False,
            "attempt_consumed": True,
            "terminal_json_o_excl": True,
        },
    }


def _minimal_terminal_failure(error: BaseException) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "status": "FAIL_TODESK_CORUN_DEVELOPMENT_ONLY_RUNABILITY",
        "scientific_role": SCIENTIFIC_ROLE,
        "errors": [f"{type(error).__name__}:{error}"],
        "failure_codes": ["UNCAUGHT_POSTCLAIM_EXCEPTION"],
        "execution": {
            "raw_returncode": None,
            "timed_out": False,
            "supervisor_error": f"{type(error).__name__}:{error}",
            "popen_invocations": _POPEN_INVOCATIONS,
            "retry_performed": False,
            "retry_permitted": False,
        },
        "resource_context": {
            "resource_isolation": False,
            "todesk_corun": True,
            "accuracy_authorized": False,
            "ranking_authorized": False,
        },
        "claim_boundary": dict(CLAIM_BOUNDARY),
        "terminal_contract": {
            "retry_after_pass_or_fail": False,
            "attempt_consumed": True,
            "terminal_json_o_excl": True,
        },
    }


def _run_once_impl(token: str) -> dict[str, Any]:
    global _ACTIVE_CHILD, _CLAIM_CREATED_THIS_PROCESS
    if token != AUTHORIZATION_TOKEN:
        raise ContractError("AUTHORIZATION_TOKEN_MISMATCH")
    prepared = load_prepared()
    precheck = check(require_unclaimed=True)
    if precheck.get("ready") is not True:
        raise ContractError(
            "PRESTART_CHECK_FAILED:"
            + ";".join(str(item) for item in precheck.get("errors", []))
        )
    if _POPEN_INVOCATIONS != 0:
        raise ContractError("HFNET_POPEN_COUNTER_NOT_ZERO_BEFORE_CLAIM")
    for label in ("claim", "result", "stdout", "stderr", "score_trajectory"):
        artifact = paths()[label]
        if artifact.exists() or artifact.is_symlink():
            raise ContractError(f"PREEXISTING_NO_CLOBBER_ARTIFACT:{label}")

    claim = {
        "schema_version": CLAIM_SCHEMA,
        "status": "O_EXCL_CLAIM_BEFORE_ONLY_HFNET_POPEN",
        "claimed_at_utc": base.now_utc(),
        "authorization_token": token,
        "maximum_hfnet_elf_starts": 1,
        "retry": False,
        "resource_isolation": False,
        "todesk_corun": True,
        "accuracy_authorized": False,
        "ranking_authorized": False,
        "prepared_manifest": _identity(paths()["prepared"]),
        "runner": _identity(RUNNER),
        "argv": prepared["launch"]["argv"],
        "prestart_resource_gate": precheck["resource_gate"],
    }
    try:
        _publish_json_exclusive_atomic(paths()["claim"], claim)
        _CLAIM_CREATED_THIS_PROCESS = True
    except BaseException:
        try:
            committed = (
                paths()["claim"].is_file()
                and not paths()["claim"].is_symlink()
                and paths()["claim"].read_bytes() == _canonical_json(claim)
            )
        except Exception:
            committed = False
        if committed:
            _CLAIM_CREATED_THIS_PROCESS = True
        raise

    started = base.now_utc()
    started_monotonic = time.monotonic()
    raw_returncode: int | None = None
    timed_out = False
    termination: str | None = None
    supervisor_error: str | None = None
    child_reaped = True
    watchdog: dict[str, Any] = {"triggered": False, "failure_code": None}
    stop: threading.Event | None = None
    thread: threading.Thread | None = None
    process: Any = None
    errors: list[str] = []
    try:
        with paths()["stdout"].open("xb") as stdout, paths()["stderr"].open("xb") as stderr:
            process = _spawn_exact(
                prepared["launch"]["argv"],
                cwd=str(ATTEMPT),
                env=base.runtime_environment(),
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            _ACTIVE_CHILD = process
            stop, thread, watchdog = _start_zero_kf_watchdog(process)
            try:
                raw_returncode = process.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                timed_out = True
                raw_returncode, termination, child_reaped = _terminate_and_reap(process)
            except BaseException as error:
                supervisor_error = f"{type(error).__name__}:{error}"
                raw_returncode, termination, child_reaped = _terminate_and_reap(process)
    except BaseException as error:
        supervisor_error = f"{type(error).__name__}:{error}"
        errors.append(supervisor_error)
        if process is not None and process.poll() is None:
            raw_returncode, termination, child_reaped = _terminate_and_reap(process)
    finally:
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join()
        if process is not None and process.poll() is None:
            raw_returncode, termination, child_reaped = _terminate_and_reap(process)
        _ACTIVE_CHILD = None

    execution = {
        "started_at_utc": started,
        "ended_at_utc": base.now_utc(),
        "duration_seconds": time.monotonic() - started_monotonic,
        "raw_returncode": raw_returncode,
        "timed_out": timed_out,
        "termination": termination,
        "supervisor_error": supervisor_error,
        "popen_invocations": _POPEN_INVOCATIONS,
        "retry_performed": False,
        "retry_permitted": False,
        "child_reaped_before_post_audit": child_reaped,
    }
    value = _terminal_value(
        prepared=prepared,
        precheck=precheck,
        execution=execution,
        watchdog=watchdog,
        errors=errors,
    )
    _publish_json_exclusive_atomic(paths()["result"], value)
    return value


def run_once(token: str) -> dict[str, Any]:
    """After this process creates the claim, every observable exit is terminal."""
    try:
        return _run_once_impl(token)
    except BaseException as error:
        if not _CLAIM_CREATED_THIS_PROCESS:
            raise
        process = _ACTIVE_CHILD
        if process is not None and process.poll() is None:
            _terminate_and_reap(process)
        if paths()["result"].exists() or paths()["result"].is_symlink():
            raise ContractError(
                f"POSTCLAIM_EXCEPTION_AFTER_TERMINAL_CREATE:{type(error).__name__}:{error}"
            ) from error
        fallback = _minimal_terminal_failure(error)
        _publish_json_exclusive_atomic(paths()["result"], fallback)
        return fallback


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "check", "run"))
    parser.add_argument("--authorization-token", default="")
    arguments = parser.parse_args()
    try:
        if arguments.action == "prepare":
            value = prepare()
        elif arguments.action == "check":
            value = check()
        else:
            value = run_once(arguments.authorization_token)
        print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))
        if arguments.action == "check":
            return 0 if value.get("ready") is True else 2
        if arguments.action == "run":
            return 0 if str(value.get("status", "")).startswith("PASS_") else 1
        return 0
    except Exception as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
