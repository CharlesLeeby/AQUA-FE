#!/usr/bin/python3
"""Run paired July Learned+KLT/KLT bags on one frozen development VINS backend.

This is deliberately not a P07 backend reproduction: the complete P07 dynamic
runtime could not be recovered.  Both VINS arms use the same prospective
DEV_NATIVEQ_SCHEDFIX_V1 identity so their cold-start stability remains paired.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping, Sequence
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from fair_stability_ordinal_common_v1 import (
    authorize as authorize_ordinal,
    verify_dispatch_claim,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
PROTOCOL = ROOT / "papers/fair_stability_positive_roster_protocol_v1.md"
SHUTDOWN_ADDENDUM = ROOT / "papers/fair_stability_vins_supervised_shutdown_addendum_v1.md"
ROSTER = ROOT / "papers/fair_stability_positive_roster_v1.csv"
HISTORICAL_RESULTS = (
    ROOT
    / "papers/frozen_frontend_eval_20260714/positive_regression_results_20260717.csv"
)
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v1"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_v1"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
REPLAY_WRAPPER = ROOT / "scripts/run_fair_stability_vins_replay_child_v1.sh"
RECORD_ENV = ROOT / "scripts/record_vins_env.sh"
WAIT_SUBSCRIBERS = ROOT / "scripts/wait_for_ros_subscribers.py"
ORDINAL_COMMON = ROOT / "scripts/fair_stability_ordinal_common_v1.py"
ORDINAL_CONTROLLER = ROOT / "scripts/run_fair_stability_next_v1.py"
HFNET_RUNNER = ROOT / "scripts/run_fair_stability_hfnet_openloop_v1.py"
CONTROL_TESTS = ROOT / "scripts/test_fair_stability_controls_v1.py"
UNIFIED_SUMMARY = ROOT / "scripts/summarize_fair_stability_v1.py"
CONTROL_SUPERSESSION = ROOT / "papers/fair_stability_control_supersession_v2.md"
HFNET_BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
HFNET_LIBRARY = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so")
HFNET_LD_LIBRARY_PATH = ":".join(
    [
        "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib",
        "/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/Thirdparty/g2o/lib",
        "/home/ma/SLAM/aqua_deps/install/lib",
        "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/lib/x86_64-linux-gnu",
        "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.6/targets/x86_64-linux/lib",
        "/home/ma/opt/hfnet_cuda116_trt851_r1/usr/local/cuda-11.8/targets/x86_64-linux/lib",
    ]
)

EXPECTED_PROTOCOL_SHA256 = "ab057022d47e4e90e81c639c84a5444000c67cca3aab10316a554b3e3beecd09"
EXPECTED_ROSTER_SHA256 = "63715003fde3374a96fd045917e1e718a8b3473723ba1afc50e2d48693d87e3c"
EXPECTED_HISTORICAL_RESULTS_SHA256 = "0f48af044f061d0e4013bd23ad54b427c95eca00332e014279d7555f78036341"
EXPECTED_SHUTDOWN_ADDENDUM_SHA256 = "34f9ac4b0ed5ecc7dab9f6dd8219fd2527a19ef7a4ef74b9b8aa50bc72e0117a"

VINS_WS = Path("/mnt/data/AQUA-FE_WS/tmp/mimir_current_schedfix_ws")
VINS_NODE = VINS_WS / "devel/lib/vins/vins_node"
VINS_LIBRARY = VINS_WS / "devel/lib/libvins_lib.so"
CAMERA_LIBRARY = Path(
    "/mnt/data/AQUA-FE_WS/tmp/mimir_upstream_vins_sparse_ws/devel/lib/libcamera_models.so"
)
VINS_SOURCE = VINS_WS / "src/vins_estimator"
CAMERA_SOURCE = Path(
    "/mnt/data/AQUA-FE_WS/tmp/mimir_upstream_vins_sparse_ws/src/VINS-Fusion/camera_models"
)
EXPECTED_BACKEND = {
    "vins_node": (13_104_368, "0965be87ef6f0ebf13d9618886aba11894dc504decc3b56773758078d0f90813"),
    "libvins_lib": (165_204_992, "c4692313f35050e64df8a37f9ef400337cdbc19ddfddda8790870f2c83428704"),
    "libcamera_models": (2_970_640, "e631b9f50435e8ed752a422d81ee1ee0c6509ea5bb34549d504050ea669032d9"),
    "estimator_cpp": (57_903, "e4c2500328e96d3aaca85bfa5cd42af48b01e7fdf9b9c0c7d8d25e1164334c4c"),
}
EXPECTED_CONTROLS = {
    REPLAY_WRAPPER: "726666490963a97671f28e4cc0eeab85be4ea67d480eb143a7b8ddaa71043882",
    RECORD_ENV: "27f711a69503729464e0dd71e497eb0f5fbc336911f87220bbefcd7263ef6729",
    WAIT_SUBSCRIBERS: "5b1c98907651122439aa4d31bd90fea7fcc44a5a35557ceda5131f9c3d84eaa5",
    ORDINAL_COMMON: "c0090b488222e5a5e22552c73d4a35dc80301fceae5c5ec014d51d3cac3f14a3",
    ORDINAL_CONTROLLER: "f6140dc5a154766874d80556837edd24869024e2fa491d6a9ddcfd55be95e432",
    HFNET_RUNNER: "d75df51fb2fea308a68be32ecdc4ed42fc84d28691fe7e46113f82637ba06e87",
    CONTROL_TESTS: "a3d43e106fab7f7819ee4012e5d0a1dcea54a9b6cefc4a4c3d539173079321b6",
    UNIFIED_SUMMARY: "826f32d55671a8ac56cce319a04e7785788510378ccb03996c69f0a6d7e9bd1e",
    CONTROL_SUPERSESSION: "19db817008cd5df08094dd9c70033fee2121c7011d6a3d274ad8acc429418408",
}

CASE_ORDER = [
    "a05_3300_3700", "a07_10800_11200", "a08_4500_4660",
    "a09_6000_6200", "fjord1_s83_d10", "mclab1_s60_d15",
    "cirs_s575_d30", "cirs_s900_d30", "a02_7600_8000",
    "mclab2_s110_d10",
]
ARMS = ("learned_klt_vins", "pure_klt_vins")
REPEATS = (1, 2, 3)
ASSOCIATION_TOLERANCE_NS = 256
MIN_PARTIAL_COVERAGE = 0.50
MIN_SUCCESS_COVERAGE = 0.70
MAX_INIT_LATENCY_SECONDS = 10.0
TIMEOUT_SECONDS = 1800
MIN_MNT_FREE_BYTES = 5 * 1024**3
MIN_ROOT_FREE_BYTES = 512 * 1024**2


class ContractError(RuntimeError):
    pass


class SupervisorInterrupted(RuntimeError):
    pass


def raise_supervisor_interrupt(signum: int, _frame: object) -> None:
    raise SupervisorInterrupted(f"received signal {signum}")


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def identity(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"MISSING_OR_SYMLINK_FILE:{path}")
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def require_identity(path: Path, size: int, digest: str, label: str) -> dict[str, object]:
    actual = identity(path)
    if actual["size_bytes"] != size or actual["sha256"] != digest:
        raise ContractError(f"IDENTITY_MISMATCH:{label}:{path}")
    return actual


def write_exclusive(path: Path, payload: bytes, mode: int = 0o444) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def read_csv_rows(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return {row[key]: row for row in csv.DictReader(stream)}


def verify_common_inputs() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]], dict[str, Any]]:
    require_identity(PROTOCOL, PROTOCOL.stat().st_size, EXPECTED_PROTOCOL_SHA256, "protocol")
    require_identity(
        SHUTDOWN_ADDENDUM,
        SHUTDOWN_ADDENDUM.stat().st_size,
        EXPECTED_SHUTDOWN_ADDENDUM_SHA256,
        "shutdown_addendum",
    )
    require_identity(ROSTER, ROSTER.stat().st_size, EXPECTED_ROSTER_SHA256, "roster")
    require_identity(
        HISTORICAL_RESULTS,
        HISTORICAL_RESULTS.stat().st_size,
        EXPECTED_HISTORICAL_RESULTS_SHA256,
        "historical_results",
    )
    roster = read_csv_rows(ROSTER, "case_id")
    historical = read_csv_rows(HISTORICAL_RESULTS, "case_id")
    if list(roster) != CASE_ORDER or any(case_id not in historical for case_id in CASE_ORDER):
        raise ContractError("CASE_TABLE_MISMATCH")
    experiment_path = EXPERIMENT_ROOT / "experiment_manifest.json"
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    if experiment["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256 or experiment["roster"]["sha256"] != EXPECTED_ROSTER_SHA256:
        raise ContractError("PARENT_EXPERIMENT_PIN_MISMATCH")
    if len(json.loads((EXPERIMENT_ROOT / "planned_schedule.json").read_text())) != 120:
        raise ContractError("PLANNED_SCHEDULE_SIZE_MISMATCH")
    return roster, historical, experiment


def tree_identity(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise ContractError(f"SOURCE_TREE_INVALID:{root}")
    files = sorted(
        path for path in root.rglob("*")
        if path.is_file() and not path.is_symlink() and ".git" not in path.relative_to(root).parts
    )
    digest = hashlib.sha256()
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        item_sha = sha256_file(path)
        size = path.stat().st_size
        total += size
        digest.update(f"{relative}\0{size}\0{item_sha}\n".encode("ascii"))
    return {
        "path": str(root),
        "file_count": len(files),
        "total_bytes": total,
        "tree_sha256": digest.hexdigest(),
        "excludes": [".git", "symlinks"],
    }


def sourced_command(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash", "--noprofile", "--norc", "-c",
            f"source /opt/ros/noetic/setup.bash; source {VINS_WS}/devel/setup.bash; {command}",
        ],
        env={
            "HOME": "/home/ma",
            "USER": "ma",
            "LOGNAME": "ma",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C",
            "LC_ALL": "C",
            "ROS_DISTRO": "noetic",
            "ROS_VERSION": "1",
            "ROS_PYTHON_VERSION": "3",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def parse_ldd_closure(
    result: subprocess.CompletedProcess[str], label: str
) -> dict[str, object]:
    if result.returncode != 0 or "not found" in result.stdout:
        raise ContractError(f"LDD_FAILED:{label}:{result.stderr.strip()}:{result.stdout}")
    paths: set[Path] = set()
    for line in result.stdout.splitlines():
        match = re.search(r"=>\s+(/\S+)\s+\(", line)
        if match:
            paths.add(Path(match.group(1)))
            continue
        match = re.match(r"\s*(/\S+)\s+\(", line)
        if match:
            paths.add(Path(match.group(1)))
    files: list[dict[str, object]] = []
    seen_resolved: set[Path] = set()
    for ldd_path in sorted(paths, key=str):
        try:
            resolved = ldd_path.resolve(strict=True)
        except OSError as error:
            raise ContractError(f"LDD_RESOLUTION_FAILED:{ldd_path}:{error}") from error
        if resolved in seen_resolved:
            continue
        seen_resolved.add(resolved)
        item = identity(resolved)
        item["ldd_path"] = str(ldd_path)
        files.append(item)
    return {
        "label": label, "ldd_stdout": result.stdout,
        "resolved_file_count": len(files), "resolved_files": files,
    }


def vins_ldd_closure() -> dict[str, object]:
    return parse_ldd_closure(sourced_command(f"ldd {VINS_NODE}"), "vins_node")


def hfnet_ldd_closure() -> dict[str, object]:
    result = subprocess.run(
        ["ldd", str(HFNET_BINARY)],
        env={
            "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C", "LC_ALL": "C", "LD_LIBRARY_PATH": HFNET_LD_LIBRARY_PATH,
        },
        check=False, capture_output=True, text=True, timeout=30,
    )
    return parse_ldd_closure(result, "hfnet_headless")


def source_case_paths(historical_row: Mapping[str, str]) -> tuple[Path, Path, Path]:
    source_run = Path(historical_row["full_run"])
    if source_run.is_symlink() or not source_run.is_dir():
        raise ContractError(f"SOURCE_RUN_INVALID:{source_run}")
    configs = list(source_run.glob("vins_*_external.yaml"))
    cameras = [path for path in source_run.glob("*.yaml") if path not in configs]
    if len(configs) != 1 or len(cameras) != 1:
        raise ContractError(f"SOURCE_CONFIG_DISCOVERY_FAILED:{source_run}")
    return source_run, configs[0], cameras[0]


def parse_imu_topic(config: Path) -> str:
    text = config.read_text(encoding="utf-8")
    match = re.search(r'^imu_topic:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match or len(re.findall(r"^imu_topic:", text, re.MULTILINE)) != 1:
        raise ContractError(f"IMU_TOPIC_PARSE_FAILED:{config}")
    if len(re.findall(r"^output_path:", text, re.MULTILINE)) != 1:
        raise ContractError(f"OUTPUT_PATH_PARSE_FAILED:{config}")
    if not re.search(r"^multiple_thread:\s*0\s*$", text, re.MULTILINE):
        raise ContractError(f"MULTIPLE_THREAD_NOT_ZERO:{config}")
    if not re.search(r"^loop_closure:\s*0\s*$", text, re.MULTILINE):
        raise ContractError(f"LOOP_CLOSURE_NOT_ZERO:{config}")
    return match.group(1)


def freeze_backend() -> dict[str, object]:
    if BACKEND_FREEZE.exists() or BACKEND_FREEZE.is_symlink():
        raise ContractError(f"BACKEND_FREEZE_EXISTS:{BACKEND_FREEZE}")
    roster, historical, experiment = verify_common_inputs()
    backend = {
        "vins_node": require_identity(VINS_NODE, *EXPECTED_BACKEND["vins_node"], "vins_node"),
        "libvins_lib": require_identity(VINS_LIBRARY, *EXPECTED_BACKEND["libvins_lib"], "libvins_lib"),
        "libcamera_models": require_identity(CAMERA_LIBRARY, *EXPECTED_BACKEND["libcamera_models"], "libcamera_models"),
        "estimator_cpp": require_identity(
            VINS_SOURCE / "src/estimator/estimator.cpp",
            *EXPECTED_BACKEND["estimator_cpp"],
            "estimator_cpp",
        ),
        "vins_source_tree": tree_identity(VINS_SOURCE),
        "camera_source_tree": tree_identity(CAMERA_SOURCE),
        "vins_ldd_closure": vins_ldd_closure(),
    }
    for label, path, stack_key in (
        ("hfnet_binary", HFNET_BINARY, "binary"),
        ("hfnet_official_library", HFNET_LIBRARY, "official_library"),
    ):
        observed = identity(path)
        expected = experiment["stack"][stack_key]
        if (observed["size_bytes"], observed["sha256"]) != (
            expected["size_bytes"], expected["sha256"]
        ):
            raise ContractError(f"HFNET_PARENT_STACK_DRIFT:{label}")
        backend[label] = observed
    backend["hfnet_ldd_closure"] = hfnet_ldd_closure()
    build_id = subprocess.run(
        ["readelf", "-n", str(VINS_NODE)], check=False, capture_output=True, text=True, timeout=20
    )
    match = re.search(r"Build ID:\s*([0-9a-f]+)", build_id.stdout)
    if build_id.returncode != 0 or not match:
        raise ContractError("BUILD_ID_READ_FAILED")
    backend["vins_node_build_id"] = match.group(1)
    controls: dict[str, object] = {}
    for path, digest in EXPECTED_CONTROLS.items():
        controls[path.name] = require_identity(path, path.stat().st_size, digest, path.name)
    cases: dict[str, object] = {}
    for case_id in CASE_ORDER:
        source_run, config, camera = source_case_paths(historical[case_id])
        case_manifest = experiment["cases"][case_id]
        if case_manifest["learned_klt_bag"]["sha256"] != roster[case_id]["learned_klt_sha256"]:
            raise ContractError(f"LEARNED_BAG_PARENT_PIN:{case_id}")
        if case_manifest["pure_klt_bag"]["sha256"] != roster[case_id]["klt_sha256"]:
            raise ContractError(f"KLT_BAG_PARENT_PIN:{case_id}")
        cases[case_id] = {
            "source_run": str(source_run),
            "source_config": identity(config),
            "source_camera_config": identity(camera),
            "imu_topic": parse_imu_topic(config),
            "selected_times": case_manifest["selected_times_file"],
            "learned_klt_bag": case_manifest["learned_klt_bag"],
            "pure_klt_bag": case_manifest["pure_klt_bag"],
        }
    toolchain: dict[str, object] = {}
    for label, argv in (
        ("gxx", ["g++", "--version"]),
        ("cmake", ["cmake", "--version"]),
        ("rosversion", ["rosversion", "-d"]),
    ):
        command = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=20)
        toolchain[label] = {"argv": argv, "returncode": command.returncode, "stdout": command.stdout, "stderr": command.stderr}
    freeze = {
        "schema_version": "aqua-fe-dev-nativeq-schedfix-backend-freeze-v1",
        "status": "FROZEN_BEFORE_NEW_VINS_REPLAY",
        "frozen_at_utc": now_utc(),
        "backend_id": "DEV_NATIVEQ_SCHEDFIX_V1",
        "identity_boundary": {
            "p07_backend_reproduction": False,
            "p07_dynamic_runtime_recovered": False,
            "frozen_frontend_bags_plus_prospective_backend_replay": True,
            "same_backend_for_both_vins_arms": True,
        },
        "protocol": identity(PROTOCOL),
        "shutdown_addendum": identity(SHUTDOWN_ADDENDUM),
        "roster": identity(ROSTER),
        "historical_results": identity(HISTORICAL_RESULTS),
        "parent_experiment_manifest": identity(EXPERIMENT_ROOT / "experiment_manifest.json"),
        "planned_schedule": identity(EXPERIMENT_ROOT / "planned_schedule.json"),
        "backend": backend,
        "controls": controls,
        "runner": identity(RUNNER),
        "toolchain_observation": toolchain,
        "cases": cases,
        "claims": {"estimator_started": False, "accuracy_evaluated": False, "paper_final_system": False},
    }
    write_exclusive(BACKEND_FREEZE, canonical_json(freeze))
    return freeze


def load_freeze() -> dict[str, Any]:
    verify_common_inputs()
    freeze = json.loads(BACKEND_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("backend_id") != "DEV_NATIVEQ_SCHEDFIX_V1":
        raise ContractError("BACKEND_ID_MISMATCH")
    frozen_runner = freeze.get("runner")
    current_runner = identity(RUNNER)
    if not isinstance(frozen_runner, dict) or (
        current_runner["size_bytes"], current_runner["sha256"]
    ) != (frozen_runner.get("size_bytes"), frozen_runner.get("sha256")):
        raise ContractError("VINS_RUNNER_DRIFT")
    require_identity(VINS_NODE, *EXPECTED_BACKEND["vins_node"], "vins_node")
    require_identity(VINS_LIBRARY, *EXPECTED_BACKEND["libvins_lib"], "libvins_lib")
    require_identity(CAMERA_LIBRARY, *EXPECTED_BACKEND["libcamera_models"], "libcamera_models")
    for path, digest in EXPECTED_CONTROLS.items():
        require_identity(path, path.stat().st_size, digest, path.name)
    if tree_identity(VINS_SOURCE)["tree_sha256"] != freeze["backend"]["vins_source_tree"]["tree_sha256"]:
        raise ContractError("VINS_SOURCE_TREE_DRIFT")
    if tree_identity(CAMERA_SOURCE)["tree_sha256"] != freeze["backend"]["camera_source_tree"]["tree_sha256"]:
        raise ContractError("CAMERA_SOURCE_TREE_DRIFT")
    for label, current_ldd, frozen_ldd in (
        (
            "VINS", vins_ldd_closure(),
            freeze["backend"]["vins_ldd_closure"],
        ),
        (
            "HFNET", hfnet_ldd_closure(),
            freeze["backend"]["hfnet_ldd_closure"],
        ),
    ):
        current_ldd_ids = [
            (item["path"], item["size_bytes"], item["sha256"])
            for item in current_ldd["resolved_files"]
        ]
        frozen_ldd_ids = [
            (item["path"], item["size_bytes"], item["sha256"])
            for item in frozen_ldd["resolved_files"]
        ]
        if current_ldd_ids != frozen_ldd_ids:
            raise ContractError(f"{label}_LDD_CLOSURE_DRIFT")
    for key, path in (
        ("hfnet_binary", HFNET_BINARY),
        ("hfnet_official_library", HFNET_LIBRARY),
    ):
        observed = identity(path)
        expected = freeze["backend"][key]
        if (observed["size_bytes"], observed["sha256"]) != (
            expected["size_bytes"], expected["sha256"]
        ):
            raise ContractError(f"{key.upper()}_DRIFT")
    for item in freeze["cases"].values():
        for key in ("source_config", "source_camera_config", "selected_times", "learned_klt_bag", "pure_klt_bag"):
            expected = item[key]
            actual = identity(Path(expected["path"]))
            if (actual["size_bytes"], actual["sha256"]) != (expected["size_bytes"], expected["sha256"]):
                raise ContractError(f"FROZEN_CASE_INPUT_DRIFT:{expected['path']}")
    return freeze


def attempt_root(case_id: str, arm: str, repeat: int, attempt_index: int = 1) -> Path:
    base = VINS_ROOT / "attempts" / case_id / arm / f"repeat_{repeat:03d}"
    if attempt_index < 1:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    return base if attempt_index == 1 else base.with_name(
        f"{base.name}__replenishment_{attempt_index:03d}"
    )


def port_for(case_id: str, arm: str, repeat: int, attempt_index: int) -> int:
    port = 26000 + repeat * 100 + CASE_ORDER.index(case_id) * 4 + ARMS.index(arm) + (attempt_index - 1) * 1000
    if port > 65000:
        raise ContractError("ATTEMPT_PORT_EXHAUSTED")
    return port


def prepare_attempt(case_id: str, arm: str, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    freeze = load_freeze()
    if case_id not in CASE_ORDER or arm not in ARMS or repeat not in REPEATS:
        raise ContractError("ATTEMPT_COORDINATE_INVALID")
    if attempt_index < 1:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    if attempt_index > 1:
        previous = attempt_root(case_id, arm, repeat, attempt_index - 1) / "run_result.json"
        if not previous.is_file() or json.loads(previous.read_text(encoding="utf-8")).get("status") != "PIPELINE_INVALID":
            raise ContractError("REPLENISHMENT_REQUIRES_PREVIOUS_PIPELINE_INVALID")
    root = attempt_root(case_id, arm, repeat, attempt_index)
    root.mkdir(parents=True, exist_ok=False)
    case = freeze["cases"][case_id]
    bag_key = "learned_klt_bag" if arm == "learned_klt_vins" else "pure_klt_bag"
    tag = f"fair_stability_{case_id}_{arm}_repeat_{repeat:03d}"
    attempt = {
        "schema_version": "aqua-fe-fair-stability-vins-attempt-v1",
        "status": "PREPARED_NOT_STARTED",
        "prepared_at_utc": now_utc(),
        "backend_id": "DEV_NATIVEQ_SCHEDFIX_V1",
        "backend_freeze": identity(BACKEND_FREEZE),
        "case_id": case_id,
        "arm": arm,
        "repeat": repeat,
        "planned_repeat": repeat,
        "attempt_index": attempt_index,
        "replenishes_invalid_attempt": attempt_index - 1 if attempt_index > 1 else None,
        "attempt_root": str(root),
        "source_run": case["source_run"],
        "source_config": case["source_config"],
        "source_camera_config": case["source_camera_config"],
        "feature_bag": case[bag_key],
        "selected_times": case["selected_times"],
        "imu_topic": case["imu_topic"],
        "port": port_for(case_id, arm, repeat, attempt_index),
        "tag": tag,
        "launch": {
            "argv": ["bash", str(REPLAY_WRAPPER), str(case["source_run"]), str(case[bag_key]["path"]), tag],
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "claims": {
            "fresh_process": True,
            "cold_start": True,
            "same_backend_as_paired_arm": True,
            "repeat_is_not_retry": True,
            "pipeline_invalid_replenishment_is_not_a_replicate": attempt_index > 1,
            "p07_backend_reproduction": False,
        },
    }
    write_exclusive(root / "attempt_manifest.json", canonical_json(attempt))
    return attempt


def prepare_all() -> list[dict[str, object]]:
    load_freeze()
    prepared: list[dict[str, object]] = []
    schedule = json.loads((EXPERIMENT_ROOT / "planned_schedule.json").read_text(encoding="utf-8"))
    for cell in schedule:
        arm = str(cell["arm"])
        if arm not in ARMS:
            continue
        root = attempt_root(str(cell["case_id"]), arm, int(cell["repeat"]))
        if not root.exists():
            prepared.append(prepare_attempt(str(cell["case_id"]), arm, int(cell["repeat"])))
    return prepared


def process_record(pid: int) -> dict[str, object]:
    root = Path("/proc") / str(pid)
    try:
        executable = os.readlink(root / "exe")
    except OSError:
        executable = ""
    try:
        comm = (root / "comm").read_text(errors="replace").strip()
    except OSError:
        comm = ""
    try:
        tokens = [part.decode(errors="replace") for part in (root / "cmdline").read_bytes().split(b"\0") if part]
    except OSError:
        tokens = []
    return {"pid": pid, "executable": executable, "comm": comm, "tokens": tokens, "command": " ".join(tokens)}


def resource_gate(port: int) -> dict[str, object]:
    errors: list[str] = []
    conflicts: list[dict[str, object]] = []
    forbidden_names = {
        "mono_inertial_euroc_headless_v3", "mono_inertial_euroc", "vins_node",
        "roscore", "rosmaster", "roslaunch", "rosbag", "cc1plus", "cmake", "make", "ninja",
    }
    forbidden_fragments = ("uw_frontend.ros.export_vins_features", "catkin build", "catkin_make")
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        record = process_record(int(entry.name))
        names = {Path(str(record["executable"])).name.lower(), str(record["comm"]).lower()}
        names.update(Path(str(value)).name.lower() for value in record["tokens"])
        if names & forbidden_names or any(fragment in str(record["command"]) for fragment in forbidden_fragments):
            conflicts.append(record)
    if conflicts:
        errors.append("CONFLICTING_ESTIMATOR_EXPORTER_ROS_OR_COMPILER_PROCESS")
    compute = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory", "--format=csv,noheader,nounits"],
        check=False, capture_output=True, text=True, timeout=10,
    )
    competing = [line.strip() for line in compute.stdout.splitlines() if line.strip() and "todesk" not in line.lower()]
    if compute.returncode != 0:
        errors.append("GPU_COMPUTE_QUERY_FAILED")
    elif competing:
        errors.append("COMPETING_GPU_COMPUTE_APPLICATION")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            errors.append("ROS_PORT_UNAVAILABLE")
    free_bytes = shutil.disk_usage(EXPERIMENT_ROOT).free
    if free_bytes < MIN_MNT_FREE_BYTES:
        errors.append("MNT_FREE_SPACE_BELOW_5_GIB")
    root_free_bytes = shutil.disk_usage(ROOT).free
    if root_free_bytes < MIN_ROOT_FREE_BYTES:
        errors.append("ROOT_FREE_SPACE_BELOW_512_MIB")
    return {
        "checked_at_utc": now_utc(), "ready": not errors, "errors": errors,
        "conflicting_processes": conflicts, "competing_compute_applications": competing,
        "port": port, "port_available": "ROS_PORT_UNAVAILABLE" not in errors,
        "mnt_free_bytes": free_bytes, "runtime_claim_allowed": False,
        "root_free_bytes": root_free_bytes,
    }


def verify_attempt(
    case_id: str,
    arm: str,
    repeat: int,
    unstarted: bool,
    attempt_index: int = 1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = load_freeze()
    root = attempt_root(case_id, arm, repeat, attempt_index)
    attempt = json.loads((root / "attempt_manifest.json").read_text(encoding="utf-8"))
    if (
        attempt.get("case_id"), attempt.get("arm"), attempt.get("repeat"),
        attempt.get("attempt_index"),
    ) != (case_id, arm, repeat, attempt_index):
        raise ContractError("ATTEMPT_COORDINATE_MISMATCH")
    for key in ("source_config", "source_camera_config", "feature_bag", "selected_times"):
        expected = attempt[key]
        actual = identity(Path(expected["path"]))
        if (actual["size_bytes"], actual["sha256"]) != (expected["size_bytes"], expected["sha256"]):
            raise ContractError(f"ATTEMPT_INPUT_DRIFT:{expected['path']}")
    expected_freeze = attempt["backend_freeze"]
    actual_freeze = identity(BACKEND_FREEZE)
    if (actual_freeze["size_bytes"], actual_freeze["sha256"]) != (
        expected_freeze["size_bytes"], expected_freeze["sha256"]
    ):
        raise ContractError("BACKEND_FREEZE_DRIFT")
    if unstarted and any((root / name).exists() for name in ("start_claim.json", "run_result.json", "vins_output", "vins.log")):
        raise ContractError("ATTEMPT_ALREADY_STARTED_OR_TERMINAL")
    return freeze, attempt


def read_ns_lines(path: Path) -> list[int]:
    values = [int(line) for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    if not values or any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"TIMESTAMP_LIST_INVALID:{path}")
    return values


def parse_vio(path: Path, stamps: Sequence[int]) -> dict[str, object]:
    result: dict[str, object] = {"exists": path.is_file(), "valid": False, "pose_count": 0, "errors": []}
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    associated: list[int] = []
    used: set[int] = set()
    previous_stamp = previous_index = None
    nonempty_rows = 0
    with path.open(newline="", encoding="ascii") as stream:
        for row_number, row in enumerate(csv.reader(stream), 1):
            if not row:
                continue
            nonempty_rows += 1
            try:
                stamp = int(row[0])
                numeric_tokens = row[1:]
                while numeric_tokens and numeric_tokens[-1] == "":
                    numeric_tokens.pop()
                if len(numeric_tokens) < 7 or any(value == "" for value in numeric_tokens):
                    raise ValueError("short or internal empty field")
                numeric_values = [float(value) for value in numeric_tokens]
                pose = numeric_values[:7]
            except (ValueError, IndexError):
                result["errors"].append(f"ROW_{row_number}_PARSE")
                continue
            if not all(math.isfinite(value) for value in numeric_values):
                result["errors"].append(f"ROW_{row_number}_NONFINITE_OR_SHORT")
                continue
            if abs(math.sqrt(sum(value * value for value in pose[3:7])) - 1.0) > 1e-3:
                result["errors"].append(f"ROW_{row_number}_QUATERNION_NORM")
                continue
            if previous_stamp is not None and stamp <= previous_stamp:
                result["errors"].append(f"ROW_{row_number}_TIMESTAMP_NOT_STRICT")
                continue
            previous_stamp = stamp
            lower = bisect.bisect_left(stamps, stamp - ASSOCIATION_TOLERANCE_NS)
            upper = bisect.bisect_right(stamps, stamp + ASSOCIATION_TOLERANCE_NS)
            if upper - lower != 1 or lower in used or (previous_index is not None and lower <= previous_index):
                result["errors"].append(f"ROW_{row_number}_ASSOCIATION_NOT_UNIQUE_OR_STRICT")
                continue
            used.add(lower)
            associated.append(lower)
            previous_index = lower
    longest = current = 0
    longest_start = longest_end = current_start = previous = None
    for index in associated:
        if previous is not None and index == previous + 1:
            current += 1
        else:
            current = 1
            current_start = index
        if current > longest:
            longest, longest_start, longest_end = current, current_start, index
        previous = index
    result.update(
        {
            "valid": bool(nonempty_rows and associated) and not result["errors"],
            "nonempty_row_count": nonempty_rows,
            "pose_count": len(associated),
            "first_relative_index": associated[0] if associated else None,
            "last_relative_index": associated[-1] if associated else None,
            "coverage_fraction": len(associated) / len(stamps),
            "longest_contiguous_count": longest,
            "longest_contiguous_fraction": longest / len(stamps),
            "longest_contiguous_relative_indices_inclusive": [longest_start, longest_end] if longest_start is not None else None,
            "identity": identity(path),
        }
    )
    return result


def ros_sim_time(line: str) -> float | None:
    match = re.search(r"\[[^,\]]+,\s*([0-9]+(?:\.[0-9]+)?)\]", line)
    return float(match.group(1)) if match else None


def log_events(lines: Sequence[str], pattern: re.Pattern[str]) -> list[dict[str, object]]:
    return [
        {
            "line_index": index,
            "sim_time_seconds": ros_sim_time(line),
            "line_sha256": hashlib.sha256(line.encode("utf-8", errors="replace")).hexdigest(),
        }
        for index, line in enumerate(lines)
        if pattern.search(line)
    ]


def events_in_support(
    events: Sequence[Mapping[str, object]], support_seconds: tuple[float, float] | None
) -> list[dict[str, object]]:
    if support_seconds is None:
        return []
    start, end = support_seconds
    return [
        dict(event)
        for event in events
        if event.get("sim_time_seconds") is not None
        and start - 1e-6 <= float(event["sim_time_seconds"]) <= end + 1e-6
    ]


def parse_vins_log(
    path: Path,
    first_camera_ns: int,
    support_seconds: tuple[float, float] | None,
) -> dict[str, object]:
    if not path.is_file():
        return {"valid": False, "errors": ["VINS_LOG_MISSING"]}
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    initialization = log_events(lines, re.compile(r"Initialization finish!"))
    first_init_index = int(initialization[0]["line_index"]) if initialization else None
    solver = log_events(
        lines,
        re.compile(
            r"linear solver failure|failed to compute a step|"
            r"cholesky.*(?:fail|error)|marginali[sz]ation.*(?:fail|error)",
            re.IGNORECASE,
        ),
    )
    failure_detection = log_events(lines, re.compile(r"failure detection", re.IGNORECASE))
    reboot_or_reset = log_events(
        lines,
        re.compile(
            r"reboot|reset(?:ting)?(?: the)? estimator|reseting(?: the)? estimator|"
            r"restart(?:ing)?(?: the)? estimator|clear(?:ing)? (?:the )?state",
            re.IGNORECASE,
        ),
    )
    nonfinite = log_events(
        lines,
        re.compile(r"(?<![A-Za-z])(?:[-+]?nan|[-+]?inf(?:inity)?)(?![A-Za-z])", re.IGNORECASE),
    )
    solver_preinit = [
        event for event in solver
        if first_init_index is None or int(event["line_index"]) < first_init_index
    ]
    solver_postinit = [
        event for event in solver
        if first_init_index is not None and int(event["line_index"]) > first_init_index
    ]
    reset_preinit = [
        event for event in reboot_or_reset
        if first_init_index is None or int(event["line_index"]) < first_init_index
    ]
    reset_postinit = [
        event for event in reboot_or_reset
        if first_init_index is not None and int(event["line_index"]) > first_init_index
    ]
    first_init_time = initialization[0].get("sim_time_seconds") if initialization else None
    init_latency = (
        float(first_init_time) - first_camera_ns / 1e9
        if first_init_time is not None
        else None
    )
    reinitialization = initialization[1:]
    solver_support = events_in_support(solver_postinit, support_seconds)
    reset_support = events_in_support(reset_postinit, support_seconds)
    reinit_support = events_in_support(reinitialization, support_seconds)
    return {
        "valid": True,
        "initialization_count": len(initialization),
        "initialization_time_parse_count": sum(
            event.get("sim_time_seconds") is not None for event in initialization
        ),
        "initialization_sim_times_seconds": [
            event.get("sim_time_seconds") for event in initialization
        ],
        "initialization_latency_seconds": init_latency,
        "reinitialization_count": len(reinitialization),
        "reinitialization_in_support_count": len(reinit_support),
        "reinitialization_unresolved_postinit_count": sum(
            event.get("sim_time_seconds") is None for event in reinitialization
        ),
        "solver_risk_count": len(solver),
        "solver_risk_preinit_count": len(solver_preinit),
        "solver_risk_postinit_count": len(solver_postinit),
        "solver_risk_in_support_count": len(solver_support),
        "solver_risk_unresolved_postinit_count": sum(
            event.get("sim_time_seconds") is None for event in solver_postinit
        ),
        "failure_detection_count": len(failure_detection),
        "reboot_or_reset_count": len(reboot_or_reset),
        "reboot_or_reset_preinit_count": len(reset_preinit),
        "reboot_or_reset_postinit_count": len(reset_postinit),
        "reboot_or_reset_in_support_count": len(reset_support),
        "reboot_or_reset_unresolved_postinit_count": sum(
            event.get("sim_time_seconds") is None for event in reset_postinit
        ),
        "nonfinite_log_event_count": len(nonfinite),
        "not_enough_features_or_parallax_count": sum("Not enough features or parallax" in line for line in lines),
        "accepted_support_sim_seconds_inclusive": list(support_seconds) if support_seconds else None,
        "event_receipts": {
            "initialization": initialization,
            "solver_risk": solver,
            "failure_detection": failure_detection,
            "reboot_or_reset": reboot_or_reset,
            "nonfinite": nonfinite,
        },
        "identity": identity(path),
    }


def parse_key_value_receipt(path: Path) -> tuple[dict[str, str], list[str]]:
    if not path.is_file():
        return {}, [f"MISSING:{path.name}"]
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "=" not in line:
            errors.append(f"ROW_{line_number}_FORMAT")
            continue
        key, value = line.split("=", 1)
        if key in values:
            errors.append(f"ROW_{line_number}_DUPLICATE_KEY")
            continue
        values[key] = value
    return values, errors


def parse_child_start(
    path: Path,
    expected_executable: Path,
    expected_config: Path,
    expected_pgid: int,
) -> dict[str, object]:
    values, errors = parse_key_value_receipt(path)
    expected = {
        "schema_version": "aqua-fe-fair-stability-vins-child-start-v1",
        "vins_executable_expected": str(expected_executable),
        "vins_executable_observed": str(expected_executable),
        "vins_pgid_start": str(expected_pgid),
        "roscore_pgid": str(expected_pgid),
    }
    for key, value in expected.items():
        if values.get(key) != value:
            errors.append(f"VALUE_MISMATCH:{key}:{values.get(key)}:{value}")
    for key in ("roscore_pid", "vins_pid", "vins_start_ticks"):
        if not values.get(key, "").isdigit() or int(values[key]) <= 0:
            errors.append(f"INVALID_POSITIVE_INTEGER:{key}:{values.get(key)}")
    command = values.get("vins_command_observed", "").split()
    if command[:2] != [str(expected_executable), str(expected_config)]:
        errors.append("VINS_COMMAND_MISMATCH")
    return {
        "valid": not errors,
        "errors": errors,
        "values": values,
        "identity": identity(path) if path.is_file() else None,
    }


def parse_child_lifecycle(path: Path, start: Mapping[str, object]) -> dict[str, object]:
    values, errors = parse_key_value_receipt(path)
    expected = {
        "schema_version": "aqua-fe-fair-stability-vins-child-lifecycle-v1",
        "rosbag_returncode": "0",
        "bag_end_vins_alive": "1",
        "output_nonempty": "1",
        "vins_signal_sent": "15",
        "vins_wait_returncode": "143",
        "vins_early_exit": "0",
        "bag_end_vins_identity_match": "1",
        "expected_vins_wait_returncode": "143",
        "roscore_kill_returncode": "0",
        "descendant_residual_check": "DELEGATED_TO_PARENT_PROCESS_GROUP",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            errors.append(f"VALUE_MISMATCH:{key}:{values.get(key)}:{value}")
    if values.get("roscore_wait_returncode") not in {"0", "143"}:
        errors.append(f"ROSCORE_WAIT_UNEXPECTED:{values.get('roscore_wait_returncode')}")
    start_values = start.get("values", {}) if isinstance(start, Mapping) else {}
    if isinstance(start_values, Mapping):
        for key in (
            "roscore_pid", "roscore_pgid", "vins_pid", "vins_start_ticks",
            "vins_pgid_start", "vins_executable_expected", "vins_executable_observed",
            "vins_command_observed",
        ):
            if values.get(key) != start_values.get(key):
                errors.append(f"START_LIFECYCLE_MISMATCH:{key}")
        for start_key, end_key in (
            ("vins_start_ticks", "bag_end_vins_start_ticks"),
            ("vins_pgid_start", "bag_end_vins_pgid"),
            ("vins_executable_expected", "bag_end_vins_executable"),
        ):
            if start_values.get(start_key) != values.get(end_key):
                errors.append(f"BAG_END_IDENTITY_MISMATCH:{end_key}")
    return {
        "valid": not errors,
        "errors": errors,
        "values": values,
        "identity": identity(path) if path.is_file() else None,
    }


def terminate(process: subprocess.Popen[bytes]) -> tuple[int | None, bool]:
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
        try:
            return process.wait(timeout=15), True
        except subprocess.TimeoutExpired:
            continue
    return process.poll(), process.poll() is not None


def reap_process_group(pgid: int) -> bool:
    """Return True when the supervised process group is already empty."""
    for _ in range(10):
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        time.sleep(0.2)
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pgid, signal_value)
        except ProcessLookupError:
            return False
        time.sleep(1.0)
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
    return False


def residual_attempt_processes(attempt: Mapping[str, Any], pgid: int | None) -> list[dict[str, object]]:
    root_needle = str(attempt["attempt_root"])
    config_needle = str(Path(root_needle) / Path(str(attempt["source_config"]["path"])).name)
    master_needle = f"ROS_MASTER_URI=http://localhost:{attempt['port']}"
    residuals: list[dict[str, object]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        pid = int(entry.name)
        record = process_record(pid)
        try:
            observed_pgid = os.getpgid(pid)
        except OSError:
            observed_pgid = None
        try:
            environment = (entry / "environ").read_bytes().decode("utf-8", errors="replace")
        except OSError:
            environment = ""
        command = str(record["command"])
        if (
            (pgid is not None and observed_pgid == pgid)
            or root_needle in command
            or config_needle in command
            or master_needle in environment
        ):
            record["pgid"] = observed_pgid
            residuals.append(record)
    return residuals


def runtime_environment(attempt: Mapping[str, Any], root: Path) -> dict[str, str]:
    tmp = root / "runtime_temp"
    tmp.mkdir(parents=True, exist_ok=True)
    ros_log = tmp / "ros_log"
    xdg_cache = tmp / "xdg_cache"
    ros_log.mkdir(parents=True, exist_ok=True)
    xdg_cache.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": "/home/ma", "USER": "ma", "LANG": "C", "LC_ALL": "C",
        "ROS_DISTRO": "noetic", "ROS_VERSION": "1", "ROS_PYTHON_VERSION": "3",
        "ROS_MASTER_URI": f"http://localhost:{attempt['port']}", "ROS_HOSTNAME": "localhost",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(tmp),
        "ROS_HOME": str(tmp / "ros_home"), "ROS_LOG_DIR": str(ros_log),
        "XDG_CACHE_HOME": str(xdg_cache),
        "ROOT": str(ROOT), "VINS_WS": str(VINS_WS),
        "IMU_TOPIC": str(attempt["imu_topic"]), "RUN_DIR": str(root),
        "SOURCE_CONFIG": str(attempt["source_config"]["path"]),
        "SOURCE_CAMERA_CONFIG": str(attempt["source_camera_config"]["path"]),
        "PORT": str(attempt["port"]), "PLAY_RATE": "1.0", "POST_PLAY_SLEEP": "8",
        "ROSBAG_PLAY_DELAY": "3", "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
    }


def run_attempt(case_id: str, arm: str, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    freeze, attempt = verify_attempt(case_id, arm, repeat, True, attempt_index)
    root = attempt_root(case_id, arm, repeat, attempt_index)
    lock_path = EXPERIMENT_ROOT / ".gpu_serial.lock"
    lock_path.touch(exist_ok=True)
    with lock_path.open("r+b") as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        ordinal_state = authorize_ordinal(
            EXPERIMENT_ROOT, case_id, arm, repeat, attempt_index
        )
        dispatch = verify_dispatch_claim(
            EXPERIMENT_ROOT, root, case_id, arm, repeat, attempt_index
        )
        gate = resource_gate(int(attempt["port"]))
        if gate["ready"] is not True:
            raise ContractError(f"RESOURCE_GATE_BLOCKED:{gate['errors']}")
        verify_attempt(case_id, arm, repeat, True, attempt_index)
        claim = {
            "schema_version": "aqua-fe-fair-stability-vins-start-claim-v1",
            "claimed_at_utc": now_utc(), "case_id": case_id, "arm": arm,
            "repeat": repeat, "backend_freeze": identity(BACKEND_FREEZE),
            "attempt_index": attempt_index,
            "planned_ordinal": int(ordinal_state["cell"]["ordinal"]),
            "ordinal_state_before_start": ordinal_state,
            "ordinal_dispatch": dispatch,
            "attempt_manifest": identity(root / "attempt_manifest.json"),
            "resource_gate": gate, "runner": identity(RUNNER),
        }
        write_exclusive(root / "start_claim.json", canonical_json(claim))
        stdout_path = root / "supervisor.stdout.log"
        stderr_path = root / "supervisor.stderr.log"
        started = now_utc()
        start_monotonic = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        returncode: int | None = None
        reaped = False
        timed_out = False
        supervisor_error = None
        deferred_postprocess_signals: list[int] = []

        def defer_postprocess_signal(signum: int, _frame: object) -> None:
            deferred_postprocess_signals.append(signum)

        previous_handlers = {
            value: signal.getsignal(value) for value in (signal.SIGTERM, signal.SIGINT)
        }
        for value in previous_handlers:
            signal.signal(value, raise_supervisor_interrupt)
        try:
            with stdout_path.open("xb") as stdout, stderr_path.open("xb") as stderr:
                process = subprocess.Popen(
                    attempt["launch"]["argv"], cwd=str(root),
                    env=runtime_environment(attempt, root), stdout=stdout, stderr=stderr,
                    start_new_session=True,
                )
                try:
                    returncode = process.wait(timeout=TIMEOUT_SECONDS)
                    reaped = True
                except subprocess.TimeoutExpired:
                    timed_out = True
                    returncode, reaped = terminate(process)
        except BaseException as error:
            supervisor_error = f"{type(error).__name__}:{error}"
            if process is not None and not reaped:
                returncode, reaped = terminate(process)
        finally:
            for value in previous_handlers:
                signal.signal(value, defer_postprocess_signal)
        execution = {
            "started_at_utc": started, "ended_at_utc": now_utc(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "raw_returncode": returncode, "timed_out": timed_out,
            "child_reaped": reaped, "supervisor_error": supervisor_error,
            "supervisor_popen_invocations": 1 if process is not None else 0,
            "postprocess_signals_deferred": deferred_postprocess_signals,
        }
        process_group_clean = True if process is None else reap_process_group(process.pid)
        execution["supervised_process_group_empty_after_wait"] = process_group_clean
        residuals = residual_attempt_processes(attempt, process.pid if process is not None else None)
        execution["residual_attempt_processes"] = residuals
        stamps = read_ns_lines(Path(attempt["selected_times"]["path"]))
        trajectory = parse_vio(root / "vins_output/vio.csv", stamps)
        support_indices = trajectory.get("longest_contiguous_relative_indices_inclusive")
        support_seconds: tuple[float, float] | None = None
        if (
            isinstance(support_indices, list)
            and len(support_indices) == 2
            and all(isinstance(value, int) for value in support_indices)
        ):
            support_seconds = (
                stamps[int(support_indices[0])] / 1e9,
                stamps[int(support_indices[1])] / 1e9,
            )
        log = parse_vins_log(root / "vins.log", stamps[0], support_seconds)
        expected_config = root / Path(str(attempt["source_config"]["path"])).name
        start = parse_child_start(
            root / "child_start_receipt.txt",
            VINS_NODE,
            expected_config,
            process.pid if process is not None else -1,
        )
        lifecycle = parse_child_lifecycle(root / "child_lifecycle.txt", start)
        init_latency = log.get("initialization_latency_seconds")
        pipeline_failures: list[str] = []
        algorithm_failures: list[str] = []
        if process is None or supervisor_error is not None or not reaped:
            pipeline_failures.append("SUPERVISOR_LAUNCH_OR_REAP_FAILED")
        if timed_out:
            algorithm_failures.append("ESTIMATOR_OR_REPLAY_TIMEOUT")
        if not process_group_clean or residuals:
            algorithm_failures.append("SUPERVISED_DESCENDANT_RESIDUAL")
        if start.get("valid") is not True:
            pipeline_failures.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        lifecycle_values = lifecycle.get("values", {})
        if lifecycle.get("valid") is not True:
            if isinstance(lifecycle_values, Mapping) and lifecycle_values.get("vins_early_exit") == "1":
                algorithm_failures.append("ESTIMATOR_EXITED_BEFORE_BAG_END")
            elif isinstance(lifecycle_values, Mapping) and lifecycle_values.get("rosbag_returncode") not in (None, "0"):
                pipeline_failures.append("ROSBAG_PLAY_NONZERO")
            else:
                pipeline_failures.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        if returncode != 0 and not timed_out and lifecycle.get("valid") is True:
            pipeline_failures.append("WRAPPER_NONZERO_DESPITE_VALID_LIFECYCLE")
        if trajectory.get("valid") is not True:
            algorithm_failures.append("TRAJECTORY_INVALID")
        coverage = float(trajectory.get("coverage_fraction", 0.0))
        contiguous = float(trajectory.get("longest_contiguous_fraction", 0.0))
        if coverage < MIN_PARTIAL_COVERAGE or contiguous < MIN_PARTIAL_COVERAGE:
            algorithm_failures.append("TRAJECTORY_COVERAGE_BELOW_50_PERCENT")
        elif coverage < MIN_SUCCESS_COVERAGE or contiguous < MIN_SUCCESS_COVERAGE:
            algorithm_failures.append("PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT")
        if log.get("valid") is not True:
            algorithm_failures.append("VINS_LOG_MISSING_OR_INVALID")
        initialization_count = int(log.get("initialization_count", 0))
        if initialization_count == 0 or init_latency is None:
            algorithm_failures.append("NO_PROVEN_SUCCESSFUL_INITIALIZATION")
        elif float(init_latency) < 0:
            algorithm_failures.append("NEGATIVE_INITIALIZATION_LATENCY")
        elif float(init_latency) > MAX_INIT_LATENCY_SECONDS:
            algorithm_failures.append("INITIALIZATION_AFTER_10_SECONDS")
        if int(log.get("initialization_time_parse_count", 0)) != initialization_count:
            algorithm_failures.append("INITIALIZATION_SIM_TIME_UNPARSEABLE")
        if (
            int(log.get("reinitialization_in_support_count", 0))
            or int(log.get("reinitialization_unresolved_postinit_count", 0))
        ):
            algorithm_failures.append("REINITIALIZATION_WITHIN_OR_UNRESOLVED_SUPPORT")
        if int(log.get("failure_detection_count", 0)):
            algorithm_failures.append("FAILURE_DETECTION_EVENT")
        if int(log.get("nonfinite_log_event_count", 0)):
            algorithm_failures.append("NONFINITE_EVENT_IN_ESTIMATOR_LOG")
        if (
            int(log.get("reboot_or_reset_in_support_count", 0))
            or int(log.get("reboot_or_reset_unresolved_postinit_count", 0))
        ):
            algorithm_failures.append("RESET_OR_RESTART_WITHIN_OR_UNRESOLVED_AFTER_INITIALIZATION")
        if (
            int(log.get("solver_risk_in_support_count", 0))
            or int(log.get("solver_risk_unresolved_postinit_count", 0))
        ):
            algorithm_failures.append("SOLVER_RISK_WITHIN_OR_UNRESOLVED_AFTER_INITIALIZATION")

        integrity: dict[str, object] = {}
        expected_post = {
            "vins_node": (VINS_NODE, EXPECTED_BACKEND["vins_node"]),
            "libvins_lib": (VINS_LIBRARY, EXPECTED_BACKEND["libvins_lib"]),
            "libcamera_models": (CAMERA_LIBRARY, EXPECTED_BACKEND["libcamera_models"]),
            "source_config": (
                Path(attempt["source_config"]["path"]),
                (attempt["source_config"]["size_bytes"], attempt["source_config"]["sha256"]),
            ),
            "source_camera_config": (
                Path(attempt["source_camera_config"]["path"]),
                (attempt["source_camera_config"]["size_bytes"], attempt["source_camera_config"]["sha256"]),
            ),
            "feature_bag": (
                Path(attempt["feature_bag"]["path"]),
                (attempt["feature_bag"]["size_bytes"], attempt["feature_bag"]["sha256"]),
            ),
            "selected_times": (
                Path(attempt["selected_times"]["path"]),
                (attempt["selected_times"]["size_bytes"], attempt["selected_times"]["sha256"]),
            ),
        }
        for key, (path, expected) in expected_post.items():
            try:
                observed = identity(path)
                integrity[key] = observed
                if (observed["size_bytes"], observed["sha256"]) != tuple(expected):
                    pipeline_failures.append(f"POSTRUN_IDENTITY_DRIFT:{key}")
            except BaseException as error:
                integrity[key] = {"error": f"{type(error).__name__}:{error}"}
                pipeline_failures.append(f"POSTRUN_IDENTITY_UNREADABLE:{key}")
        integrity["controls_post"] = {}
        for path, digest in EXPECTED_CONTROLS.items():
            try:
                observed = identity(path)
                integrity["controls_post"][path.name] = observed
                if observed["sha256"] != digest:
                    pipeline_failures.append(f"POSTRUN_CONTROL_DRIFT:{path.name}")
            except BaseException as error:
                integrity["controls_post"][path.name] = {"error": f"{type(error).__name__}:{error}"}
                pipeline_failures.append(f"POSTRUN_CONTROL_UNREADABLE:{path.name}")
        try:
            load_freeze()
            integrity["full_backend_freeze_reverification"] = "PASS"
        except BaseException as error:
            integrity["full_backend_freeze_reverification"] = f"FAIL:{type(error).__name__}:{error}"
            pipeline_failures.append("POSTRUN_FULL_BACKEND_FREEZE_REVERIFICATION_FAILED")

        pipeline_failures = list(dict.fromkeys(pipeline_failures))
        algorithm_failures = list(dict.fromkeys(algorithm_failures))
        if pipeline_failures:
            status = "PIPELINE_INVALID"
        elif not algorithm_failures:
            status = "SUCCESS"
        elif algorithm_failures == ["PARTIAL_TRAJECTORY_COVERAGE_BELOW_70_PERCENT"]:
            status = "PARTIAL_NON_SUCCESS"
        else:
            status = "ALGORITHM_FAILURE"
        failures = pipeline_failures + algorithm_failures
        clean_success = (
            status == "SUCCESS"
            and initialization_count == 1
            and int(log.get("reinitialization_count", 0)) == 0
            and int(log.get("solver_risk_count", 0)) == 0
            and int(log.get("reboot_or_reset_count", 0)) == 0
            and int(log.get("failure_detection_count", 0)) == 0
            and int(log.get("nonfinite_log_event_count", 0)) == 0
        )
        result = {
            "schema_version": "aqua-fe-fair-stability-vins-result-v1",
            "status": status, "clean_success": clean_success,
            "case_id": case_id, "arm": arm, "repeat": repeat,
            "attempt_index": attempt_index,
            "backend_id": "DEV_NATIVEQ_SCHEDFIX_V1", "failure_codes": failures,
            "pipeline_failure_codes": pipeline_failures,
            "algorithm_failure_codes": algorithm_failures,
            "execution": execution, "trajectory": trajectory, "log": log,
            "child_start": start,
            "child_lifecycle": lifecycle,
            "initialization_latency_seconds": init_latency,
            "integrity": integrity,
            "claim_boundary": {
                "p07_backend_reproduction": False,
                "frozen_frontend_bag_plus_prospective_backend_replay": True,
                "paper_final_system": False, "accuracy_evaluated": False,
                "runtime_claim_allowed": False, "failed_accuracy_is_na": True,
            },
        }
        write_exclusive(root / "run_result.json", canonical_json(result))
        for value, handler in previous_handlers.items():
            signal.signal(value, handler)
        return result


def summary() -> dict[str, object]:
    load_freeze()
    rows: list[dict[str, object]] = []
    for case_id in CASE_ORDER:
        for arm in ARMS:
            for repeat in REPEATS:
                path = attempt_root(case_id, arm, repeat) / "run_result.json"
                if path.is_file():
                    value = json.loads(path.read_text(encoding="utf-8"))
                    rows.append(
                        {
                            "case_id": case_id, "arm": arm, "repeat": repeat,
                            "status": value["status"], "clean_success": value["clean_success"],
                            "failure_codes": value["failure_codes"],
                            "coverage": value["trajectory"].get("coverage_fraction"),
                            "contiguous_coverage": value["trajectory"].get("longest_contiguous_fraction"),
                            "initialization_latency_seconds": value.get("initialization_latency_seconds"),
                            "solver_risk_count": value["log"].get("solver_risk_count"),
                        }
                    )
    aggregate = {
        arm: {
            "completed": sum(row["arm"] == arm for row in rows),
            "successes": sum(row["arm"] == arm and row["status"] == "SUCCESS" for row in rows),
            "clean_successes": sum(row["arm"] == arm and bool(row["clean_success"]) for row in rows),
            "planned": len(CASE_ORDER) * len(REPEATS),
        }
        for arm in ARMS
    }
    report = {
        "schema_version": "aqua-fe-fair-stability-vins-progress-summary-v1",
        "generated_at_utc": now_utc(), "rows": rows, "aggregate": aggregate,
        "claim_boundary": "DEV_NATIVEQ_SCHEDFIX_V1_NOT_P07_REPRODUCTION_NO_SYSTEM_RANKING",
    }
    target = VINS_ROOT / "progress_summary.json"
    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    temporary.write_bytes(canonical_json(report))
    os.replace(temporary, target)
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze-backend")
    sub.add_parser("verify-freeze")
    sub.add_parser("prepare-all")
    for name in ("prepare", "check", "run"):
        child = sub.add_parser(name)
        child.add_argument("--case", required=True, choices=CASE_ORDER)
        child.add_argument("--arm", required=True, choices=ARMS)
        child.add_argument("--repeat", required=True, type=int, choices=REPEATS)
        child.add_argument("--attempt-index", type=int, default=1)
    gate = sub.add_parser("resource-check")
    gate.add_argument("--port", type=int, default=26100)
    sub.add_parser("summary")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "freeze-backend":
            result = freeze_backend()
        elif args.command == "verify-freeze":
            load_freeze()
            result = {
                "status": "VERIFIED",
                "backend_freeze": identity(BACKEND_FREEZE),
            }
        elif args.command == "prepare-all":
            result = {"prepared_count": len(prepare_all())}
        elif args.command == "prepare":
            result = prepare_attempt(args.case, args.arm, args.repeat, args.attempt_index)
        elif args.command == "check":
            _, attempt = verify_attempt(
                args.case, args.arm, args.repeat, True, args.attempt_index
            )
            gate = resource_gate(int(attempt["port"]))
            result = {"attempt": attempt, "resource_gate": gate, "ready": gate["ready"]}
        elif args.command == "run":
            result = run_attempt(args.case, args.arm, args.repeat, args.attempt_index)
        elif args.command == "resource-check":
            result = resource_gate(args.port)
        elif args.command == "summary":
            result = summary()
        else:  # pragma: no cover
            raise ContractError("UNKNOWN_COMMAND")
        print(json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True))
        if args.command in ("check", "resource-check") and result.get("ready") is not True:
            return 2
        if args.command == "run" and result.get("status") != "SUCCESS":
            return 3
        return 0
    except BaseException as error:
        print(f"{type(error).__name__}:{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
