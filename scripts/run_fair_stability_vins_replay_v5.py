#!/usr/bin/python3
"""Run paired July Learned+KLT/KLT bags under the runtime-exclusive v5 protocol.

This is deliberately not a P07 backend reproduction: the complete P07 dynamic
runtime could not be recovered.  Both VINS arms use the same prospective
DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5 identity so stability remains paired.
"""

from __future__ import annotations

import argparse
import bisect
import csv
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from fair_stability_ordinal_common_v5 import (
    EXPERIMENT_ID,
    MAX_ATTEMPTS_PER_CELL,
    MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
    authorize as authorize_ordinal,
    load_schedule,
    next_state as ordinal_next_state,
    strict_json_equal,
    verify_dispatch_claim,
)
from fair_stability_runtime_resource_monitor_v5 import (
    RuntimeResourceMonitor,
    resource_gate,
)


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).resolve()
PROTOCOL = ROOT / "papers/fair_stability_positive_roster_protocol_v1.md"
SHUTDOWN_ADDENDUM = ROOT / "papers/fair_stability_vins_supervised_shutdown_addendum_v1.md"
RUNTIME_ADDENDUM = ROOT / "papers/fair_stability_runtime_exclusivity_addendum_v5.md"
V1_CONTAMINATION_REPORT = (
    ROOT / "papers/fair_stability_v1_runtime_contamination_report_20260829.md"
)
V2_LIFECYCLE_CONTAMINATION_REPORT = (
    ROOT
    / "papers/fair_stability_v2_lifecycle_false_positive_contamination_report_20260829_v3.md"
)
ROSTER = ROOT / "papers/fair_stability_positive_roster_v1.csv"
HISTORICAL_RESULTS = (
    ROOT
    / "papers/frozen_frontend_eval_20260714/positive_regression_results_20260717.csv"
)
HISTORICAL_MANIFEST = ROOT / "papers/frozen_frontend_eval_20260714/manifest.csv"
EXPERIMENT_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/fair_stability_positive_roster_openloop_v5"
)
VINS_ROOT = EXPERIMENT_ROOT / "vins_dev_nativeq_schedfix_runtimeexcl_v5"
BACKEND_FREEZE = VINS_ROOT / "backend_freeze.json"
REPLAY_WRAPPER = ROOT / "scripts/run_fair_stability_vins_replay_child_v5.sh"
RECORD_ENV = ROOT / "scripts/record_vins_env.sh"
WAIT_SUBSCRIBERS = ROOT / "scripts/wait_for_ros_subscribers.py"
RUNTIME_MONITOR = ROOT / "scripts/fair_stability_runtime_resource_monitor_v5.py"
ORDINAL_COMMON = ROOT / "scripts/fair_stability_ordinal_common_v5.py"
ORDINAL_CONTROLLER = ROOT / "scripts/run_fair_stability_next_v5.py"
HFNET_RUNNER = ROOT / "scripts/run_fair_stability_hfnet_openloop_v5.py"
CONTROL_TESTS = ROOT / "scripts/test_fair_stability_controls_v5.py"
UNIFIED_SUMMARY = ROOT / "scripts/summarize_fair_stability_v5.py"
SYSTEMD_SUPERVISOR = ROOT / "scripts/run_fair_stability_systemd_supervisor_v5.py"
CONTROL_SUPERSESSION = ROOT / "papers/fair_stability_control_supersession_v5.md"
V3_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v3_outer_batch_timeout_abandonment_report_20260829_v4.md"
)
V4_ABANDONMENT_REPORT = (
    ROOT
    / "papers/fair_stability_v4_ros_python_environment_abandonment_report_20260829_v5.md"
)
HFNET_BINARY = ROOT / "build/published_baselines/hfnet_slam_headless_entry_v3/mono_inertial_euroc_headless_v3"
HFNET_LIBRARY = Path("/home/ma/SLAM/HFNet-SLAM-paper-2023-build-r1/lib/libHFNet_SLAM.so")
HFNET_SHARED_ONNX = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.onnx"
)
HFNET_SHARED_CACHE = Path(
    "/home/ma/SLAM/HFNet-SLAM-runtime-model-a02-r1/HFNet-RT/HF-Net.cache"
)
HFNET_RUNTIME_SEED_ONNX = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.onnx"
HFNET_RUNTIME_SEED_CACHE = EXPERIMENT_ROOT / "runtime_seed/HFNet-RT/HF-Net.cache"
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
EXPECTED_HISTORICAL_MANIFEST_SHA256 = "fc3f53fc6a83587522ae87d3d0d84191f73863a22a920ef70a4418aaacf7a760"
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
CONTROL_PATHS = (
    REPLAY_WRAPPER,
    RECORD_ENV,
    WAIT_SUBSCRIBERS,
    RUNTIME_MONITOR,
    ORDINAL_COMMON,
    ORDINAL_CONTROLLER,
    HFNET_RUNNER,
    CONTROL_TESTS,
    UNIFIED_SUMMARY,
    SYSTEMD_SUPERVISOR,
    RUNTIME_ADDENDUM,
    V1_CONTAMINATION_REPORT,
    V2_LIFECYCLE_CONTAMINATION_REPORT,
    CONTROL_SUPERSESSION,
    V3_ABANDONMENT_REPORT,
    V4_ABANDONMENT_REPORT,
    SHUTDOWN_ADDENDUM,
)

CASE_ORDER = [
    "a05_3300_3700", "a07_10800_11200", "a08_4500_4660",
    "a09_6000_6200", "fjord1_s83_d10", "mclab1_s60_d15",
    "cirs_s575_d30", "cirs_s900_d30", "a02_7600_8000",
    "mclab2_s110_d10",
]
CANONICAL_TD_SECONDS = {
    "aqualoc_archaeology": "-0.053694112369382575",
    "ntnu": "0.0017656238182069367",
    "cirs": "0.0",
}
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


def supervised_shutdown_failure_codes(
    process_group_clean: bool, residuals: Sequence[object] = ()
) -> list[str]:
    return (
        []
        if process_group_clean and not residuals
        else ["SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN"]
    )


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def systemd_start_authority(ordinal_state: Mapping[str, Any]) -> dict[str, object]:
    """Verify this runner is inside the exact frozen transient-service cgroup."""

    raw = os.environ.get("FAIR_STABILITY_SYSTEMD_START_RECEIPT", "")
    invocation_id = os.environ.get("INVOCATION_ID", "")
    if not raw or not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
        raise ContractError("SYSTEMD_START_AUTHORITY_REQUIRED")
    path = Path(raw)
    supervision_root = EXPERIMENT_ROOT / "systemd_supervision"
    try:
        path.relative_to(supervision_root)
    except ValueError as error:
        raise ContractError("SYSTEMD_START_RECEIPT_OUTSIDE_SUPERVISION_ROOT") from error
    candidate = supervision_root
    if candidate.is_symlink():
        raise ContractError("SYSTEMD_SUPERVISION_ROOT_SYMLINK")
    for part in path.relative_to(supervision_root).parts:
        candidate /= part
        if candidate.is_symlink():
            raise ContractError(f"SYSTEMD_START_RECEIPT_SYMLINK:{candidate}")
    receipt_identity = identity(path)
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if (
        receipt.get("schema_version")
        != "aqua-fe-fair-stability-systemd-start-receipt-v5"
        or receipt.get("experiment_id") != EXPERIMENT_ID
        or receipt.get("invocation_id") != invocation_id
    ):
        raise ContractError("SYSTEMD_START_RECEIPT_HEADER_INVALID")
    claim_identity = receipt.get("submission_claim")
    if not isinstance(claim_identity, Mapping):
        raise ContractError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_MISSING")
    claim_path = Path(str(claim_identity.get("path", "")))
    if claim_path.parent != path.parent or not strict_json_equal(
        claim_identity, identity(claim_path)
    ):
        raise ContractError("SYSTEMD_SUBMISSION_CLAIM_IDENTITY_DRIFT")
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    if (
        claim.get("schema_version")
        != "aqua-fe-fair-stability-systemd-submission-v5"
        or claim.get("experiment_id") != EXPERIMENT_ID
        or not strict_json_equal(claim.get("ordinal_state_before_submit"), ordinal_state)
    ):
        raise ContractError("SYSTEMD_SUBMISSION_ORDINAL_OR_ATTEMPT_DRIFT")
    verified = receipt.get("verified_unit")
    if not isinstance(verified, Mapping):
        raise ContractError("SYSTEMD_VERIFIED_UNIT_MISSING")
    control_group = str(verified.get("control_group", ""))
    cgroups = [
        line.split(":", 2)[2]
        for line in Path("/proc/self/cgroup").read_text(encoding="ascii").splitlines()
        if line.count(":") >= 2
    ]
    if not control_group or control_group not in cgroups:
        raise ContractError("RUNNER_OUTSIDE_FROZEN_SYSTEMD_CONTROL_GROUP")
    return receipt_identity


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


def open_regular_lock(path: Path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ContractError(f"LOCK_PATH_INVALID:{path}")
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    return os.fdopen(descriptor, "r+b")


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
    require_identity(
        HISTORICAL_MANIFEST,
        HISTORICAL_MANIFEST.stat().st_size,
        EXPECTED_HISTORICAL_MANIFEST_SHA256,
        "historical_manifest",
    )
    roster = read_csv_rows(ROSTER, "case_id")
    historical = read_csv_rows(HISTORICAL_RESULTS, "case_id")
    if list(roster) != CASE_ORDER or any(case_id not in historical for case_id in CASE_ORDER):
        raise ContractError("CASE_TABLE_MISMATCH")
    experiment_path = EXPERIMENT_ROOT / "experiment_manifest.json"
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    protocol_claim = experiment.get("protocol")
    roster_claim = experiment.get("roster")
    claims = experiment.get("claims")
    execution_controls = experiment.get("execution_controls")
    if (
        experiment.get("schema_version")
        != "aqua-fe-fair-stability-hfnet-input-freeze-v5"
        or experiment.get("status") != "FROZEN_INPUTS_NO_ESTIMATOR_STARTED"
        or experiment.get("experiment_id") != EXPERIMENT_ID
        or not isinstance(protocol_claim, Mapping)
        or protocol_claim.get("sha256") != EXPECTED_PROTOCOL_SHA256
        or not isinstance(roster_claim, Mapping)
        or roster_claim.get("sha256") != EXPECTED_ROSTER_SHA256
        or not isinstance(claims, Mapping)
        or claims.get("v1_results_imported") is not False
        or claims.get("v2_results_imported") is not False
        or claims.get("v3_results_imported") is not False
        or claims.get("v4_results_imported") is not False
        or claims.get("cross_arm_imu_semantics_exact_before_clock_normalization")
        is not True
        or claims.get("cross_vins_arm_replay_schedule_exact") is not True
        or claims.get("dataset_canonical_td_shared_across_windows") is not True
        or claims.get("available_imu_samples_and_camera_cutoff_matched") is not True
        or claims.get("identical_native_backend_imu_consumption_claimed") is not False
    ):
        raise ContractError("PARENT_EXPERIMENT_PIN_MISMATCH")
    if (
        not identity_matches(experiment.get("runner"), identity(HFNET_RUNNER))
        or not isinstance(execution_controls, Mapping)
        or not identity_matches(
            execution_controls.get("ordinal_common"), identity(ORDINAL_COMMON)
        )
        or not identity_matches(
            execution_controls.get("runtime_resource_monitor"),
            identity(RUNTIME_MONITOR),
        )
        or not identity_matches(
            execution_controls.get("systemd_supervisor"),
            identity(SYSTEMD_SUPERVISOR),
        )
    ):
        raise ContractError("PARENT_EXPERIMENT_CONTROL_DRIFT")
    parent_documents = experiment.get("control_documents")
    expected_parent_documents = {
        "runtime_exclusivity_addendum": RUNTIME_ADDENDUM,
        "v1_runtime_contamination_report": V1_CONTAMINATION_REPORT,
        "v2_lifecycle_false_positive_contamination_report": (
            V2_LIFECYCLE_CONTAMINATION_REPORT
        ),
        "control_supersession": CONTROL_SUPERSESSION,
        "v3_outer_batch_timeout_abandonment_report": V3_ABANDONMENT_REPORT,
        "v4_ros_python_environment_abandonment_report": V4_ABANDONMENT_REPORT,
        "shutdown_addendum": SHUTDOWN_ADDENDUM,
    }
    if not isinstance(parent_documents, Mapping) or set(parent_documents) != set(
        expected_parent_documents
    ):
        raise ContractError("PARENT_EXPERIMENT_CONTROL_DOCUMENT_SET_DRIFT")
    for label, path in expected_parent_documents.items():
        if not identity_matches(parent_documents.get(label), identity(path)):
            raise ContractError(f"PARENT_EXPERIMENT_CONTROL_DOCUMENT_DRIFT:{label}")
    for key, path in (
        ("historical_results", HISTORICAL_RESULTS),
        ("historical_manifest", HISTORICAL_MANIFEST),
    ):
        if not identity_matches(experiment.get(key), identity(path)):
            raise ContractError(f"PARENT_EXPERIMENT_PROVENANCE_DRIFT:{key}")
    for key, path in (
        ("binary", HFNET_BINARY),
        ("official_library", HFNET_LIBRARY),
        ("shared_onnx", HFNET_SHARED_ONNX),
        ("shared_cache_seed", HFNET_SHARED_CACHE),
    ):
        if not identity_matches(experiment.get("stack", {}).get(key), identity(path)):
            raise ContractError(f"PARENT_EXPERIMENT_STACK_DRIFT:{key}")
    for key, path in (
        ("onnx", HFNET_RUNTIME_SEED_ONNX),
        ("cache", HFNET_RUNTIME_SEED_CACHE),
    ):
        if not identity_matches(
            experiment.get("runtime_seed", {}).get(key), identity(path)
        ):
            raise ContractError(f"PARENT_EXPERIMENT_RUNTIME_SEED_DRIFT:{key}")
    if not identity_matches(
        experiment.get("planned_schedule"),
        identity(EXPERIMENT_ROOT / "planned_schedule.json"),
    ):
        raise ContractError("PARENT_EXPERIMENT_SCHEDULE_DRIFT")
    cases = experiment.get("cases")
    if (
        not isinstance(cases, Mapping)
        or len(cases) != len(CASE_ORDER)
        or set(cases) != set(CASE_ORDER)
    ):
        raise ContractError("PARENT_EXPERIMENT_CASE_SET_MISMATCH")
    for case_id in CASE_ORDER:
        case = cases[case_id]
        if not isinstance(case, Mapping):
            raise ContractError(f"PARENT_EXPERIMENT_CASE_INVALID:{case_id}")
        case_path = EXPERIMENT_ROOT / "input_freeze" / case_id / "case_manifest.json"
        if json.loads(case_path.read_text(encoding="utf-8")) != case:
            raise ContractError(f"PARENT_EXPERIMENT_CASE_MANIFEST_DRIFT:{case_id}")
        for key, path in (
            (
                "selected_times_file",
                EXPERIMENT_ROOT
                / "input_freeze"
                / case_id
                / "cam0_times_vins_matched.txt",
            ),
            ("learned_klt_bag", Path(str(case["learned_klt_bag"]["path"]))),
            ("pure_klt_bag", Path(str(case["pure_klt_bag"]["path"]))),
            ("source_vins_config", Path(str(case["source_vins_config"]["path"]))),
            ("imu", Path(str(case["imu"]["path"]))),
        ):
            if not identity_matches(case.get(key), identity(path)):
                raise ContractError(f"PARENT_EXPERIMENT_CASE_INPUT_DRIFT:{case_id}:{key}")
        canonical_td = CANONICAL_TD_SECONDS[str(case["dataset"])]
        cross_imu = case.get("cross_vins_arm_imu")
        if (
            case.get("canonical_dataset_td_seconds") != canonical_td
            or not isinstance(cross_imu, Mapping)
            or cross_imu.get("exact_semantic_equality") is not True
            or case.get("native_backend_input_semantics", {}).get(
                "identical_estimator_ingress_or_preroll_consumption_claimed"
            ) is not False
        ):
            raise ContractError(f"PARENT_EXPERIMENT_IMU_CONTRACT_DRIFT:{case_id}")
    if len(load_schedule(EXPERIMENT_ROOT)) != 120:
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


def parse_vins_time_contract(config: Path) -> dict[str, str]:
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
    td_matches = re.findall(r"^td:\s*([^\s#]+)\s*$", text, re.MULTILINE)
    if len(td_matches) != 1 or not re.search(
        r"^estimate_td:\s*0\s*$", text, re.MULTILINE
    ):
        raise ContractError(f"TD_CONTRACT_PARSE_FAILED:{config}")
    try:
        td = Decimal(td_matches[0])
    except InvalidOperation as error:
        raise ContractError(f"TD_DECIMAL_INVALID:{config}") from error
    if not td.is_finite():
        raise ContractError(f"TD_NONFINITE:{config}")
    return {"imu_topic": match.group(1), "source_td_seconds": str(td)}


def parse_imu_topic(config: Path) -> str:
    return parse_vins_time_contract(config)["imu_topic"]


def canonical_vins_config(
    source: Path, dataset: str
) -> tuple[bytes, dict[str, object]]:
    contract = parse_vins_time_contract(source)
    canonical_td = CANONICAL_TD_SECONDS[dataset]
    text = source.read_text(encoding="utf-8")
    patched, count = re.subn(
        r"^td:\s*[^\s#]+\s*$",
        f"td: {canonical_td}",
        text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ContractError(f"CANONICAL_TD_PATCH_COUNT:{source}:{count}")
    receipt = {
        "only_prelaunch_substitution": "dataset_canonical_td",
        "source_td_seconds": contract["source_td_seconds"],
        "canonical_td_seconds": canonical_td,
        "td_changed": Decimal(contract["source_td_seconds"]) != Decimal(canonical_td),
        "imu_topic": contract["imu_topic"],
    }
    return patched.encode("utf-8"), receipt


def runtime_vins_config_payload(template: Path, output: Path) -> bytes:
    text = template.read_text(encoding="utf-8")
    patched, count = re.subn(
        r'^output_path:\s*".*"$',
        f'output_path: "{output}"',
        text,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise ContractError(f"RUNTIME_OUTPUT_PATH_PATCH_COUNT:{template}:{count}")
    return patched.encode("utf-8")


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
    controls = {path.name: identity(path) for path in CONTROL_PATHS}
    cases: dict[str, object] = {}
    for case_id in CASE_ORDER:
        source_run, config, camera = source_case_paths(historical[case_id])
        case_manifest = experiment["cases"][case_id]
        dataset = str(case_manifest["dataset"])
        config_identity = identity(config)
        if case_manifest.get("source_vins_config") != config_identity:
            raise ContractError(f"SOURCE_CONFIG_PARENT_PIN:{case_id}")
        if case_manifest["learned_klt_bag"]["sha256"] != roster[case_id]["learned_klt_sha256"]:
            raise ContractError(f"LEARNED_BAG_PARENT_PIN:{case_id}")
        if case_manifest["pure_klt_bag"]["sha256"] != roster[case_id]["klt_sha256"]:
            raise ContractError(f"KLT_BAG_PARENT_PIN:{case_id}")
        config_payload, td_patch = canonical_vins_config(config, dataset)
        if (
            case_manifest.get("canonical_dataset_td_seconds")
            != td_patch["canonical_td_seconds"]
            or case_manifest.get("imu_topic") != td_patch["imu_topic"]
        ):
            raise ContractError(f"CANONICAL_TD_PARENT_PIN:{case_id}")
        cases[case_id] = {
            "dataset": dataset,
            "source_run": str(source_run),
            "source_config": config_identity,
            "source_camera_config": identity(camera),
            "imu_topic": str(td_patch["imu_topic"]),
            "canonical_td_patch": td_patch,
            "runtime_config_template_expected": {
                "size_bytes": len(config_payload),
                "sha256": hashlib.sha256(config_payload).hexdigest(),
            },
            "matched_hfnet_imu": case_manifest["imu"],
            "cross_vins_arm_imu": case_manifest["cross_vins_arm_imu"],
            "cross_vins_arm_replay_schedule": case_manifest[
                "cross_vins_arm_replay_schedule"
            ],
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
        "schema_version": "aqua-fe-dev-nativeq-schedfix-runtimeexcl-backend-freeze-v5",
        "experiment_id": EXPERIMENT_ID,
        "status": "FROZEN_BEFORE_NEW_VINS_REPLAY",
        "frozen_at_utc": now_utc(),
        "backend_id": "DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5",
        "identity_boundary": {
            "p07_backend_reproduction": False,
            "p07_dynamic_runtime_recovered": False,
            "frozen_frontend_bags_plus_prospective_backend_replay": True,
            "same_backend_for_both_vins_arms": True,
        },
        "protocol": identity(PROTOCOL),
        "shutdown_addendum": identity(SHUTDOWN_ADDENDUM),
        "runtime_exclusivity_addendum": identity(RUNTIME_ADDENDUM),
        "v1_runtime_contamination_report": identity(V1_CONTAMINATION_REPORT),
        "v2_lifecycle_false_positive_contamination_report": identity(
            V2_LIFECYCLE_CONTAMINATION_REPORT
        ),
        "control_supersession": identity(CONTROL_SUPERSESSION),
        "v3_abandonment_report": identity(V3_ABANDONMENT_REPORT),
        "v4_abandonment_report": identity(V4_ABANDONMENT_REPORT),
        "roster": identity(ROSTER),
        "historical_results": identity(HISTORICAL_RESULTS),
        "historical_manifest": identity(HISTORICAL_MANIFEST),
        "parent_experiment_manifest": identity(EXPERIMENT_ROOT / "experiment_manifest.json"),
        "planned_schedule": identity(EXPERIMENT_ROOT / "planned_schedule.json"),
        "backend": backend,
        "controls": controls,
        "runner": identity(RUNNER),
        "toolchain_observation": toolchain,
        "cases": cases,
        "claims": {
            "estimator_started": False,
            "accuracy_evaluated": False,
            "paper_final_system": False,
            "dataset_canonical_td_shared_across_windows": True,
            "a07_historical_recovery_td_reused": False,
            "available_cross_arm_imu_samples_and_clock_matched": True,
            "identical_native_backend_imu_consumption_claimed": False,
            "v1_results_imported": False,
            "v2_results_imported": False,
            "v3_results_imported": False,
            "v4_results_imported": False,
        },
    }
    write_exclusive(BACKEND_FREEZE, canonical_json(freeze))
    return freeze


def identity_matches(observed: object, expected: object) -> bool:
    if not isinstance(observed, Mapping) or not isinstance(expected, Mapping):
        return False
    keys = ("path", "size_bytes", "sha256")
    return all(observed.get(key) == expected.get(key) for key in keys)


def load_freeze() -> dict[str, Any]:
    verify_common_inputs()
    freeze = json.loads(BACKEND_FREEZE.read_text(encoding="utf-8"))
    if (
        freeze.get("schema_version")
        != "aqua-fe-dev-nativeq-schedfix-runtimeexcl-backend-freeze-v5"
        or freeze.get("experiment_id") != EXPERIMENT_ID
        or freeze.get("backend_id") != "DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5"
        or freeze.get("status") != "FROZEN_BEFORE_NEW_VINS_REPLAY"
    ):
        raise ContractError("BACKEND_FREEZE_HEADER_MISMATCH")
    claims = freeze.get("claims")
    if (
        not isinstance(claims, Mapping)
        or claims.get("estimator_started") is not False
        or claims.get("dataset_canonical_td_shared_across_windows") is not True
        or claims.get("a07_historical_recovery_td_reused") is not False
        or claims.get("available_cross_arm_imu_samples_and_clock_matched") is not True
        or claims.get("identical_native_backend_imu_consumption_claimed") is not False
        or claims.get("v1_results_imported") is not False
        or claims.get("v2_results_imported") is not False
        or claims.get("v3_results_imported") is not False
        or claims.get("v4_results_imported") is not False
    ):
        raise ContractError("BACKEND_FREEZE_CLAIMS_MISMATCH")
    if not identity_matches(identity(RUNNER), freeze.get("runner")):
        raise ContractError("VINS_RUNNER_DRIFT")

    frozen_controls = freeze.get("controls")
    if not isinstance(frozen_controls, Mapping) or set(frozen_controls) != {
        path.name for path in CONTROL_PATHS
    }:
        raise ContractError("FROZEN_CONTROL_SET_MISMATCH")
    for path in CONTROL_PATHS:
        if not identity_matches(identity(path), frozen_controls.get(path.name)):
            raise ContractError(f"FROZEN_CONTROL_DRIFT:{path.name}")

    for key, path in (
        ("protocol", PROTOCOL),
        ("shutdown_addendum", SHUTDOWN_ADDENDUM),
        ("runtime_exclusivity_addendum", RUNTIME_ADDENDUM),
        ("v1_runtime_contamination_report", V1_CONTAMINATION_REPORT),
        (
            "v2_lifecycle_false_positive_contamination_report",
            V2_LIFECYCLE_CONTAMINATION_REPORT,
        ),
        ("control_supersession", CONTROL_SUPERSESSION),
        ("v3_abandonment_report", V3_ABANDONMENT_REPORT),
        ("v4_abandonment_report", V4_ABANDONMENT_REPORT),
        ("roster", ROSTER),
        ("historical_results", HISTORICAL_RESULTS),
        ("historical_manifest", HISTORICAL_MANIFEST),
        ("parent_experiment_manifest", EXPERIMENT_ROOT / "experiment_manifest.json"),
        ("planned_schedule", EXPERIMENT_ROOT / "planned_schedule.json"),
    ):
        if not identity_matches(identity(path), freeze.get(key)):
            raise ContractError(f"FROZEN_COMMON_INPUT_DRIFT:{key}")

    for key, path in (
        ("vins_node", VINS_NODE),
        ("libvins_lib", VINS_LIBRARY),
        ("libcamera_models", CAMERA_LIBRARY),
        ("estimator_cpp", VINS_SOURCE / "src/estimator/estimator.cpp"),
    ):
        observed = require_identity(path, *EXPECTED_BACKEND[key], key)
        if not identity_matches(observed, freeze["backend"].get(key)):
            raise ContractError(f"FROZEN_BACKEND_IDENTITY_DRIFT:{key}")
    if tree_identity(VINS_SOURCE)["tree_sha256"] != freeze["backend"]["vins_source_tree"]["tree_sha256"]:
        raise ContractError("VINS_SOURCE_TREE_DRIFT")
    if tree_identity(CAMERA_SOURCE)["tree_sha256"] != freeze["backend"]["camera_source_tree"]["tree_sha256"]:
        raise ContractError("CAMERA_SOURCE_TREE_DRIFT")
    for label, current_ldd, frozen_ldd in (
        ("VINS", vins_ldd_closure(), freeze["backend"]["vins_ldd_closure"]),
        ("HFNET", hfnet_ldd_closure(), freeze["backend"]["hfnet_ldd_closure"]),
    ):
        current_ids = [
            (item["path"], item["size_bytes"], item["sha256"])
            for item in current_ldd["resolved_files"]
        ]
        frozen_ids = [
            (item["path"], item["size_bytes"], item["sha256"])
            for item in frozen_ldd["resolved_files"]
        ]
        if current_ids != frozen_ids:
            raise ContractError(f"{label}_LDD_CLOSURE_DRIFT")
    for key, path in (
        ("hfnet_binary", HFNET_BINARY),
        ("hfnet_official_library", HFNET_LIBRARY),
    ):
        if not identity_matches(identity(path), freeze["backend"].get(key)):
            raise ContractError(f"{key.upper()}_DRIFT")
    for case_id, item in freeze["cases"].items():
        if case_id not in CASE_ORDER:
            raise ContractError(f"FROZEN_CASE_UNKNOWN:{case_id}")
        for key in (
            "source_config", "source_camera_config", "selected_times",
            "learned_klt_bag", "pure_klt_bag", "matched_hfnet_imu",
        ):
            expected = item[key]
            if not identity_matches(identity(Path(expected["path"])), expected):
                raise ContractError(f"FROZEN_CASE_INPUT_DRIFT:{expected['path']}")
        payload, patch = canonical_vins_config(
            Path(str(item["source_config"]["path"])), str(item["dataset"])
        )
        if (
            item.get("canonical_td_patch") != patch
            or item.get("runtime_config_template_expected")
            != {
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            or item.get("imu_topic") != patch["imu_topic"]
            or item.get("cross_vins_arm_imu", {}).get("exact_semantic_equality")
            is not True
            or item.get("cross_vins_arm_replay_schedule", {}).get(
                "exact_feature_imu_header_record_interleaving"
            )
            is not True
        ):
            raise ContractError(f"FROZEN_CASE_CANONICAL_TD_OR_IMU_DRIFT:{case_id}")
    if set(freeze["cases"]) != set(CASE_ORDER):
        raise ContractError("FROZEN_CASE_SET_MISMATCH")
    return freeze


def attempt_root(case_id: str, arm: str, repeat: int, attempt_index: int = 1) -> Path:
    base = VINS_ROOT / "attempts" / case_id / arm / f"repeat_{repeat:03d}"
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    return base if attempt_index == 1 else base.with_name(
        f"{base.name}__replenishment_{attempt_index:03d}"
    )


def port_for(case_id: str, arm: str, repeat: int, attempt_index: int) -> int:
    port = (
        26000 + repeat * 100 + CASE_ORDER.index(case_id) * 4
        + ARMS.index(arm) + (attempt_index - 1) * 1000
    )
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    if port > 65000:
        raise ContractError("ATTEMPT_PORT_EXHAUSTED")
    return port


def prepare_attempt(
    case_id: str,
    arm: str,
    repeat: int,
    attempt_index: int = 1,
    *,
    _verified_freeze: Mapping[str, Any] | None = None,
) -> dict[str, object]:
    freeze = load_freeze() if _verified_freeze is None else _verified_freeze
    if case_id not in CASE_ORDER or arm not in ARMS or repeat not in REPEATS:
        raise ContractError("ATTEMPT_COORDINATE_INVALID")
    if attempt_index < 1 or attempt_index > MAX_ATTEMPTS_PER_CELL:
        raise ContractError("ATTEMPT_INDEX_INVALID")
    root = attempt_root(case_id, arm, repeat, attempt_index)
    if attempt_index > 1:
        state = ordinal_next_state(EXPERIMENT_ROOT)
        state_cell = state.get("cell")
        if (
            state.get("state") != "NEEDS_PREPARATION"
            or not isinstance(state_cell, Mapping)
            or not strict_json_equal(
                [
                    state_cell.get("case_id"),
                    state_cell.get("arm"),
                    state_cell.get("repeat"),
                    state.get("attempt_index"),
                    state.get("attempt_root"),
                ],
                [case_id, arm, repeat, attempt_index, str(root)],
            )
        ):
            raise ContractError("REPLENISHMENT_NOT_AUTHORIZED_BY_ORDINAL_STATE")
    port = port_for(case_id, arm, repeat, attempt_index)
    root.mkdir(parents=True, exist_ok=False)
    case = freeze["cases"][case_id]
    config_payload, td_patch = canonical_vins_config(
        Path(str(case["source_config"]["path"])), str(case["dataset"])
    )
    if (
        td_patch != case["canonical_td_patch"]
        or len(config_payload) != case["runtime_config_template_expected"]["size_bytes"]
        or hashlib.sha256(config_payload).hexdigest()
        != case["runtime_config_template_expected"]["sha256"]
    ):
        raise ContractError("RUNTIME_CONFIG_TEMPLATE_EXPECTATION_DRIFT")
    runtime_config_template = root / "vins_runtime_template.yaml"
    write_exclusive(runtime_config_template, config_payload)
    bag_key = "learned_klt_bag" if arm == "learned_klt_vins" else "pure_klt_bag"
    tag = (
        f"fair_stability_runtimeexcl_v5_{case_id}_{arm}_"
        f"repeat_{repeat:03d}_attempt_{attempt_index:03d}"
    )
    attempt = {
        "schema_version": "aqua-fe-fair-stability-vins-attempt-v5",
        "experiment_id": EXPERIMENT_ID,
        "status": "PREPARED_NOT_STARTED",
        "prepared_at_utc": now_utc(),
        "backend_id": "DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5",
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
        "runtime_config_template": identity(runtime_config_template),
        "canonical_td_patch": td_patch,
        "source_camera_config": case["source_camera_config"],
        "feature_bag": case[bag_key],
        "selected_times": case["selected_times"],
        "imu_topic": case["imu_topic"],
        "port": port,
        "maximum_replacement_attempts": MAX_REPLACEMENT_ATTEMPTS_PER_CELL,
        "maximum_total_attempts": MAX_ATTEMPTS_PER_CELL,
        "tag": tag,
        "launch": {
            "argv": [
                "bash", str(REPLAY_WRAPPER), str(case["source_run"]),
                str(case[bag_key]["path"]), tag,
            ],
            "timeout_seconds": TIMEOUT_SECONDS,
        },
        "claims": {
            "fresh_process": True,
            "cold_start": True,
            "same_backend_as_paired_arm": True,
            "same_dataset_canonical_td_as_hfnet": True,
            "a07_historical_recovery_td_reused": False,
            "repeat_is_not_retry": True,
            "pipeline_invalid_replenishment_is_not_a_replicate": attempt_index > 1,
            "p07_backend_reproduction": False,
            "runtime_exclusivity_required": True,
        },
    }
    write_exclusive(root / "attempt_manifest.json", canonical_json(attempt))
    return attempt


def prepare_all() -> list[dict[str, object]]:
    freeze = load_freeze()
    prepared: list[dict[str, object]] = []
    schedule = json.loads(
        (EXPERIMENT_ROOT / "planned_schedule.json").read_text(encoding="utf-8")
    )
    for cell in schedule:
        arm = str(cell["arm"])
        if arm not in ARMS:
            continue
        root = attempt_root(str(cell["case_id"]), arm, int(cell["repeat"]))
        if not root.exists():
            prepared.append(
                prepare_attempt(
                    str(cell["case_id"]),
                    arm,
                    int(cell["repeat"]),
                    _verified_freeze=freeze,
                )
            )
    return prepared


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
    expected_tag = (
        f"fair_stability_runtimeexcl_v5_{case_id}_{arm}_"
        f"repeat_{repeat:03d}_attempt_{attempt_index:03d}"
    )
    if (
        attempt.get("schema_version") != "aqua-fe-fair-stability-vins-attempt-v5"
        or attempt.get("experiment_id") != EXPERIMENT_ID
        or attempt.get("backend_id") != "DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5"
        or attempt.get("tag") != expected_tag
        or (
            attempt.get("case_id"), attempt.get("arm"), attempt.get("repeat"),
            attempt.get("attempt_index"),
        ) != (case_id, arm, repeat, attempt_index)
    ):
        raise ContractError("ATTEMPT_HEADER_OR_COORDINATE_MISMATCH")
    expected_argv = [
        "bash", str(REPLAY_WRAPPER), str(attempt["source_run"]),
        str(attempt["feature_bag"]["path"]), str(attempt["tag"]),
    ]
    if attempt.get("launch", {}).get("argv") != expected_argv:
        raise ContractError("ATTEMPT_LAUNCH_ARGV_DRIFT")
    for key in (
        "source_config",
        "runtime_config_template",
        "source_camera_config",
        "feature_bag",
        "selected_times",
    ):
        expected = attempt[key]
        if not identity_matches(identity(Path(expected["path"])), expected):
            raise ContractError(f"ATTEMPT_INPUT_DRIFT:{expected['path']}")
    template_payload, td_patch = canonical_vins_config(
        Path(str(attempt["source_config"]["path"])),
        str(freeze["cases"][case_id]["dataset"]),
    )
    if (
        attempt.get("canonical_td_patch") != td_patch
        or attempt["runtime_config_template"]["size_bytes"] != len(template_payload)
        or attempt["runtime_config_template"]["sha256"]
        != hashlib.sha256(template_payload).hexdigest()
    ):
        raise ContractError("ATTEMPT_CANONICAL_TD_TEMPLATE_DRIFT")
    if not identity_matches(identity(BACKEND_FREEZE), attempt.get("backend_freeze")):
        raise ContractError("BACKEND_FREEZE_DRIFT")
    if unstarted and any(
        (root / name).exists()
        for name in (
            "start_claim.json", "run_result.json", "runtime_resource_monitor.json",
            "vins_output", "vins.log",
        )
    ):
        raise ContractError("ATTEMPT_ALREADY_STARTED_OR_TERMINAL")
    return freeze, attempt


def read_ns_lines(path: Path) -> list[int]:
    values = [
        int(line) for line in path.read_text(encoding="ascii").splitlines()
        if line.strip()
    ]
    if not values or any(right <= left for left, right in zip(values, values[1:])):
        raise ContractError(f"TIMESTAMP_LIST_INVALID:{path}")
    return values


def parse_vio(path: Path, stamps: Sequence[int]) -> dict[str, object]:
    result: dict[str, object] = {
        "exists": path.is_file(), "valid": False, "pose_count": 0, "errors": [],
    }
    if not path.is_file():
        result["errors"] = ["MISSING"]
        return result
    associated: list[int] = []
    used: set[int] = set()
    previous_stamp: int | None = None
    previous_index: int | None = None
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
            if (
                upper - lower != 1 or lower in used
                or (previous_index is not None and lower <= previous_index)
            ):
                result["errors"].append(
                    f"ROW_{row_number}_ASSOCIATION_NOT_UNIQUE_OR_STRICT"
                )
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
            "longest_contiguous_relative_indices_inclusive": (
                [longest_start, longest_end] if longest_start is not None else None
            ),
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
            "line_sha256": hashlib.sha256(
                line.encode("utf-8", errors="replace")
            ).hexdigest(),
        }
        for index, line in enumerate(lines)
        if pattern.search(line)
    ]


def events_in_support(
    events: Sequence[Mapping[str, object]],
    support_seconds: tuple[float, float] | None,
) -> list[dict[str, object]]:
    if support_seconds is None:
        return []
    start, end = support_seconds
    return [
        dict(event) for event in events
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
        re.compile(
            r"(?<![A-Za-z])(?:[-+]?nan|[-+]?inf(?:inity)?)(?![A-Za-z])",
            re.IGNORECASE,
        ),
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
        if first_init_time is not None else None
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
        "not_enough_features_or_parallax_count": sum(
            "Not enough features or parallax" in line for line in lines
        ),
        "accepted_support_sim_seconds_inclusive": (
            list(support_seconds) if support_seconds else None
        ),
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
    expected_camera_config: Path,
    expected_camera_identity: Mapping[str, object],
    expected_pgid: int,
) -> dict[str, object]:
    values, errors = parse_key_value_receipt(path)
    expected = {
        "schema_version": "aqua-fe-fair-stability-vins-child-start-v5",
        "experiment_id": EXPERIMENT_ID,
        "vins_executable_expected": str(expected_executable),
        "vins_executable_observed": str(expected_executable),
        "vins_pgid_start": str(expected_pgid),
        "roscore_pgid": str(expected_pgid),
        "wrapper_pid": str(expected_pgid),
        "wrapper_pgid": str(expected_pgid),
        "source_camera_config": str(expected_camera_identity["path"]),
        "runtime_camera_config": str(expected_camera_config),
        "runtime_camera_config_size_bytes": str(
            expected_camera_identity["size_bytes"]
        ),
        "runtime_camera_config_sha256": str(expected_camera_identity["sha256"]),
        "runtime_camera_config_matches_source": "1",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            errors.append(f"VALUE_MISMATCH:{key}:{values.get(key)}:{value}")
    for key in (
        "wrapper_start_ticks", "roscore_pid", "roscore_start_ticks",
        "vins_pid", "vins_start_ticks",
    ):
        if not values.get(key, "").isdigit() or int(values[key]) <= 0:
            errors.append(f"INVALID_POSITIVE_INTEGER:{key}:{values.get(key)}")
    if not values.get("roscore_executable", "").startswith("/"):
        errors.append("ROSCORE_EXECUTABLE_INVALID")
    if "roscore" not in values.get("roscore_command", ""):
        errors.append("ROSCORE_COMMAND_MISMATCH")
    command = values.get("vins_command_observed", "").split()
    if command[:2] != [str(expected_executable), str(expected_config)]:
        errors.append("VINS_COMMAND_MISMATCH")
    return {
        "valid": not errors,
        "errors": errors,
        "values": values,
        "identity": identity(path) if path.is_file() else None,
    }


def parse_child_lifecycle(
    path: Path, start: Mapping[str, object]
) -> dict[str, object]:
    values, errors = parse_key_value_receipt(path)
    expected = {
        "schema_version": "aqua-fe-fair-stability-vins-child-lifecycle-v5",
        "experiment_id": EXPERIMENT_ID,
        "launch_checkpoint": "COMPLETE",
        "rosbag_returncode": "0",
        "rosbag_reaped": "1",
        "bag_end_vins_alive": "1",
        "output_nonempty": "1",
        "vins_signal_sent": "15",
        "vins_wait_returncode": "143",
        "vins_reaped": "1",
        "vins_forced_kill": "0",
        "vins_early_exit": "0",
        "bag_end_vins_identity_match": "1",
        "expected_vins_wait_returncode": "143",
        "roscore_identity_match": "1",
        "roscore_kill_returncode": "0",
        "roscore_reaped": "1",
        "roscore_forced_kill": "0",
        "descendant_residual_count": "0",
    }
    for key, value in expected.items():
        if values.get(key) != value:
            errors.append(f"VALUE_MISMATCH:{key}:{values.get(key)}:{value}")
    if values.get("roscore_wait_returncode") not in {"0", "143"}:
        errors.append(f"ROSCORE_WAIT_UNEXPECTED:{values.get('roscore_wait_returncode')}")
    start_values = start.get("values", {}) if isinstance(start, Mapping) else {}
    if isinstance(start_values, Mapping):
        for key in (
            "tag", "wrapper_pid", "wrapper_start_ticks", "wrapper_pgid",
            "roscore_pid", "roscore_start_ticks", "roscore_executable",
            "roscore_command", "roscore_pgid",
            "vins_pid", "vins_start_ticks", "vins_pgid_start",
            "vins_executable_expected", "vins_executable_observed",
            "vins_command_observed",
        ):
            if values.get(key) != start_values.get(key):
                errors.append(f"START_LIFECYCLE_MISMATCH:{key}")
        for start_key, end_key in (
            ("vins_start_ticks", "bag_end_vins_start_ticks"),
            ("vins_pgid_start", "bag_end_vins_pgid"),
            ("vins_executable_expected", "bag_end_vins_executable"),
            ("roscore_start_ticks", "roscore_end_start_ticks"),
            ("roscore_pgid", "roscore_end_pgid"),
        ):
            if start_values.get(start_key) != values.get(end_key):
                errors.append(f"END_IDENTITY_MISMATCH:{end_key}")
    return {
        "valid": not errors,
        "errors": errors,
        "values": values,
        "identity": identity(path) if path.is_file() else None,
    }


def classify_child_lifecycle(
    start: Mapping[str, object],
    lifecycle: Mapping[str, object],
    attempt_tag: str,
    timed_out: bool,
) -> tuple[list[str], list[str]]:
    """Separate estimator outcomes from genuine supervision-integrity faults."""
    pipeline: list[str] = []
    algorithm: list[str] = []
    start_values = start.get("values", {})
    if (
        not isinstance(start_values, Mapping)
        or start_values.get("tag") != attempt_tag
    ):
        pipeline.append("ATTEMPT_TAG_BINDING_UNPROVEN")
    if timed_out:
        return pipeline, algorithm

    lifecycle_values = lifecycle.get("values", {})
    if (
        not isinstance(lifecycle_values, Mapping)
        or lifecycle_values.get("tag") != attempt_tag
    ):
        pipeline.append("ATTEMPT_TAG_BINDING_UNPROVEN")
    if lifecycle.get("valid") is True:
        return pipeline, algorithm
    if not isinstance(lifecycle_values, Mapping):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        return pipeline, algorithm

    early_exit = lifecycle_values.get("vins_early_exit") == "1"
    rosbag_nonzero = lifecycle_values.get("rosbag_returncode") not in (None, "0")
    output_empty = lifecycle_values.get("output_nonempty") == "0"
    if early_exit:
        algorithm.append("ESTIMATOR_EXITED_BEFORE_BAG_END")
    if rosbag_nonzero:
        pipeline.append("ROSBAG_PLAY_NONZERO")
    errors = lifecycle.get("errors", [])
    if not isinstance(errors, list) or any(not isinstance(error, str) for error in errors):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
        return pipeline, algorithm
    allowed_value_mismatch_keys: set[str] = set()
    allowed_end_identity_keys: set[str] = set()
    if output_empty:
        allowed_value_mismatch_keys.add("output_nonempty")
    if rosbag_nonzero:
        allowed_value_mismatch_keys.add("rosbag_returncode")
    if early_exit:
        allowed_value_mismatch_keys.update(
            {
                "bag_end_vins_alive",
                "output_nonempty",
                "vins_signal_sent",
                "vins_wait_returncode",
                "vins_early_exit",
                "bag_end_vins_identity_match",
            }
        )
        allowed_end_identity_keys.update(
            {
                "bag_end_vins_start_ticks",
                "bag_end_vins_pgid",
                "bag_end_vins_executable",
            }
        )

    def expected_algorithm_consequence(error: str) -> bool:
        if error.startswith("VALUE_MISMATCH:"):
            parts = error.split(":", 2)
            return len(parts) >= 2 and parts[1] in allowed_value_mismatch_keys
        if error.startswith("END_IDENTITY_MISMATCH:"):
            return error.split(":", 1)[1] in allowed_end_identity_keys
        return False

    remaining_errors = [
        error for error in errors if not expected_algorithm_consequence(error)
    ]
    if remaining_errors or not (early_exit or rosbag_nonzero or output_empty):
        pipeline.append("SUPERVISED_SHUTDOWN_CONTRACT_UNPROVEN")
    return pipeline, algorithm


def process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def emergency_terminate_unmonitored_process_group(
    process: subprocess.Popen[bytes],
) -> tuple[int | None, bool, bool]:
    """Fail-safe cleanup only when monitor construction itself failed."""
    try:
        owned_pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        owned_pgid = None
    if owned_pgid not in (None, process.pid):
        raise ContractError(
            f"UNMONITORED_PROCESS_GROUP_IDENTITY_MISMATCH:{owned_pgid}:{process.pid}"
        )
    returncode = process.poll()
    reaped = returncode is not None
    for signal_value in (signal.SIGTERM, signal.SIGKILL):
        if owned_pgid == process.pid and process_group_exists(process.pid):
            try:
                os.killpg(process.pid, signal_value)
            except ProcessLookupError:
                pass
        elif process.poll() is None:
            process.send_signal(signal_value)
        try:
            returncode = process.wait(timeout=10.0)
            reaped = True
        except subprocess.TimeoutExpired:
            returncode = process.poll()
            reaped = returncode is not None
        deadline = time.monotonic() + 10.0
        while process_group_exists(process.pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        if reaped and not process_group_exists(process.pid):
            return returncode, True, True
    return returncode, reaped, not process_group_exists(process.pid)


def write_unproven_monitor_receipt(
    path: Path,
    process: subprocess.Popen[bytes] | None,
    errors: Sequence[str],
) -> dict[str, Any]:
    if path.is_file() and not path.is_symlink():
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ContractError("EXISTING_RUNTIME_MONITOR_RECEIPT_NOT_OBJECT")
        return value
    receipt: dict[str, Any] = {
        "schema_version": "aqua-fe-fair-stability-runtime-resource-monitor-v5",
        "experiment_id": EXPERIMENT_ID,
        "finalized_at_utc": now_utc(),
        "supervised_pid": process.pid if process is not None else None,
        "intrusion_detected": False,
        "monitor_proven": False,
        "monitor_errors": list(errors) or ["RUNTIME_MONITOR_UNAVAILABLE"],
        "pipeline_failure_reasons": ["RUNTIME_RESOURCE_MONITOR_UNPROVEN"],
        "all_intrusions": [],
        "fallback_receipt": True,
    }
    write_exclusive(path, canonical_json(receipt))
    return receipt


def runtime_environment(attempt: Mapping[str, Any], root: Path) -> dict[str, str]:
    tmp = root / "runtime_temp"
    tmp.mkdir(parents=True, exist_ok=True)
    ros_log = tmp / "ros_log"
    xdg_cache = tmp / "xdg_cache"
    ros_log.mkdir(parents=True, exist_ok=True)
    xdg_cache.mkdir(parents=True, exist_ok=True)
    return {
        "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma", "SHELL": "/bin/bash",
        "LANG": "C", "LC_ALL": "C",
        "ROS_DISTRO": "noetic", "ROS_VERSION": "1", "ROS_PYTHON_VERSION": "3",
        "ROS_MASTER_URI": f"http://localhost:{attempt['port']}", "ROS_HOSTNAME": "localhost",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(tmp),
        "ROS_HOME": str(tmp / "ros_home"), "ROS_LOG_DIR": str(ros_log),
        "XDG_CACHE_HOME": str(xdg_cache),
        "ROOT": str(ROOT), "VINS_WS": str(VINS_WS),
        "EXPERIMENT_ID": EXPERIMENT_ID,
        "IMU_TOPIC": str(attempt["imu_topic"]), "RUN_DIR": str(root),
        "SOURCE_CONFIG": str(attempt["runtime_config_template"]["path"]),
        "SOURCE_CAMERA_CONFIG": str(attempt["source_camera_config"]["path"]),
        "PORT": str(attempt["port"]), "PLAY_RATE": "1.0", "POST_PLAY_SLEEP": "8",
        "ROSBAG_PLAY_DELAY": "3", "WAIT_FOR_VINS_SUBSCRIBERS": "1",
        "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
    }


def run_attempt(case_id: str, arm: str, repeat: int, attempt_index: int = 1) -> dict[str, object]:
    freeze, attempt = verify_attempt(case_id, arm, repeat, True, attempt_index)
    root = attempt_root(case_id, arm, repeat, attempt_index)
    lock_path = EXPERIMENT_ROOT / ".gpu_serial.lock"
    with open_regular_lock(lock_path) as lock_stream:
        fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
        ordinal_state = authorize_ordinal(
            EXPERIMENT_ROOT, case_id, arm, repeat, attempt_index
        )
        dispatch = verify_dispatch_claim(
            EXPERIMENT_ROOT, root, case_id, arm, repeat, attempt_index
        )
        gate = resource_gate(
            port=int(attempt["port"]),
            experiment_root=EXPERIMENT_ROOT,
            workspace_root=ROOT,
        )
        if gate["ready"] is not True:
            raise ContractError(f"RESOURCE_GATE_BLOCKED:{gate['errors']}")
        verify_attempt(case_id, arm, repeat, True, attempt_index)
        systemd_authority = systemd_start_authority(ordinal_state)
        claim = {
            "schema_version": "aqua-fe-fair-stability-vins-start-claim-v5",
            "experiment_id": EXPERIMENT_ID,
            "claimed_at_utc": now_utc(), "case_id": case_id, "arm": arm,
            "repeat": repeat, "backend_freeze": identity(BACKEND_FREEZE),
            "tag": attempt["tag"],
            "attempt_index": attempt_index,
            "planned_ordinal": int(ordinal_state["cell"]["ordinal"]),
            "ordinal_state_before_start": ordinal_state,
            "ordinal_dispatch": dispatch,
            "attempt_manifest": identity(root / "attempt_manifest.json"),
            "resource_gate": gate, "runner": identity(RUNNER),
            "systemd_start_receipt": systemd_authority,
        }
        write_exclusive(root / "start_claim.json", canonical_json(claim))
        stdout_path = root / "supervisor.stdout.log"
        stderr_path = root / "supervisor.stderr.log"
        started = now_utc()
        start_monotonic = time.monotonic()
        process: subprocess.Popen[bytes] | None = None
        monitor: RuntimeResourceMonitor | None = None
        monitor_receipt: dict[str, Any] = {}
        monitor_errors: list[str] = []
        returncode: int | None = None
        reaped = False
        timed_out = False
        process_group_clean = False
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
                monitor = RuntimeResourceMonitor(
                    process,
                    root / "runtime_resource_monitor.json",
                    supervisor_pid=os.getpid(),
                )
                try:
                    returncode, reaped, timed_out = monitor.wait(TIMEOUT_SECONDS)
                    if timed_out:
                        returncode, reaped = monitor.terminate()
                except subprocess.TimeoutExpired:
                    timed_out = True
                    returncode, reaped = monitor.terminate()
        except BaseException as error:
            supervisor_error = f"{type(error).__name__}:{error}"
            if monitor is not None and not reaped:
                try:
                    returncode, reaped = monitor.terminate()
                except BaseException as terminate_error:
                    monitor_errors.append(
                        f"TERMINATE:{type(terminate_error).__name__}:{terminate_error}"
                    )
            elif process is not None and not reaped:
                try:
                    returncode, reaped, process_group_clean = (
                        emergency_terminate_unmonitored_process_group(process)
                    )
                except BaseException as terminate_error:
                    monitor_errors.append(
                        "EMERGENCY_UNMONITORED_TERMINATE:"
                        f"{type(terminate_error).__name__}:{terminate_error}"
                    )
        finally:
            if monitor is not None:
                try:
                    process_group_clean = monitor.reap_process_group()
                except BaseException as reap_error:
                    monitor_errors.append(
                        f"REAP_GROUP:{type(reap_error).__name__}:{reap_error}"
                    )
                try:
                    monitor_receipt = monitor.finalize()
                except BaseException as finalize_error:
                    monitor_errors.append(
                        f"FINALIZE:{type(finalize_error).__name__}:{finalize_error}"
                    )
            elif process is None:
                process_group_clean = True
            if not monitor_receipt:
                try:
                    monitor_receipt = write_unproven_monitor_receipt(
                        root / "runtime_resource_monitor.json",
                        process,
                        monitor_errors
                        + ["RUNTIME_MONITOR_NOT_SUCCESSFULLY_FINALIZED"],
                    )
                except BaseException as receipt_error:
                    monitor_errors.append(
                        "FALLBACK_RECEIPT:"
                        f"{type(receipt_error).__name__}:{receipt_error}"
                    )
            for value in previous_handlers:
                signal.signal(value, defer_postprocess_signal)
        monitor_path = root / "runtime_resource_monitor.json"
        monitor_identity: dict[str, object] | None = None
        if monitor_path.is_file() and not monitor_path.is_symlink():
            monitor_identity = identity(monitor_path)
        execution = {
            "started_at_utc": started, "ended_at_utc": now_utc(),
            "duration_seconds": time.monotonic() - start_monotonic,
            "raw_returncode": returncode, "timed_out": timed_out,
            "child_reaped": reaped, "supervisor_error": supervisor_error,
            "supervisor_popen_invocations": 1 if process is not None else 0,
            "postprocess_signals_deferred": deferred_postprocess_signals,
            "runtime_resource_monitor_errors": monitor_errors,
            "runtime_resource_monitor": monitor_identity,
            "supervised_process_group_empty_after_wait": process_group_clean,
        }
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
        expected_config = root / "vins_runtime_config.yaml"
        expected_camera_config = root / Path(
            str(attempt["source_camera_config"]["path"])
        ).name
        start = parse_child_start(
            root / "child_start_receipt.txt",
            VINS_NODE,
            expected_config,
            expected_camera_config,
            attempt["source_camera_config"],
            process.pid if process is not None else -1,
        )
        lifecycle = parse_child_lifecycle(root / "child_lifecycle.txt", start)
        init_latency = log.get("initialization_latency_seconds")
        pipeline_failures: list[str] = []
        algorithm_failures: list[str] = []
        try:
            expected_runtime_config = runtime_vins_config_payload(
                Path(str(attempt["runtime_config_template"]["path"])),
                root / "vins_output",
            )
            if expected_config.read_bytes() != expected_runtime_config:
                pipeline_failures.append("RUNTIME_VINS_CONFIG_DRIFT")
        except BaseException:
            pipeline_failures.append("RUNTIME_VINS_CONFIG_UNREADABLE")
        monitor_reason_codes = [
            str(value)
            for value in monitor_receipt.get("pipeline_failure_reasons", [])
        ]
        if (
            monitor_receipt.get("intrusion_detected") is True
            or "MIDRUN_EXTERNAL_RESOURCE_INTRUSION" in monitor_reason_codes
        ):
            pipeline_failures.append("MIDRUN_EXTERNAL_RESOURCE_INTRUSION")
        if (
            monitor_receipt.get("schema_version")
            != "aqua-fe-fair-stability-runtime-resource-monitor-v5"
            or monitor_receipt.get("experiment_id") != EXPERIMENT_ID
            or monitor_receipt.get("monitor_proven") is not True
            or monitor_identity is None
            or bool(monitor_errors)
            or "RUNTIME_RESOURCE_MONITOR_UNPROVEN" in monitor_reason_codes
        ):
            pipeline_failures.append("RUNTIME_RESOURCE_MONITOR_UNPROVEN")
        if process is None or supervisor_error is not None or not reaped:
            pipeline_failures.append("SUPERVISOR_LAUNCH_OR_REAP_FAILED")
        if timed_out:
            algorithm_failures.append("ESTIMATOR_OR_REPLAY_TIMEOUT")
        pipeline_failures.extend(
            supervised_shutdown_failure_codes(process_group_clean)
        )
        if start.get("valid") is not True:
            pipeline_failures.append("ESTIMATOR_START_IDENTITY_UNPROVEN")
        lifecycle_pipeline, lifecycle_algorithm = classify_child_lifecycle(
            start, lifecycle, str(attempt["tag"]), timed_out
        )
        pipeline_failures.extend(lifecycle_pipeline)
        algorithm_failures.extend(lifecycle_algorithm)
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
        integrity["runtime_resource_monitor"] = monitor_identity
        expected_post = {
            "vins_node": (VINS_NODE, EXPECTED_BACKEND["vins_node"]),
            "libvins_lib": (VINS_LIBRARY, EXPECTED_BACKEND["libvins_lib"]),
            "libcamera_models": (CAMERA_LIBRARY, EXPECTED_BACKEND["libcamera_models"]),
            "source_config": (
                Path(attempt["source_config"]["path"]),
                (attempt["source_config"]["size_bytes"], attempt["source_config"]["sha256"]),
            ),
            "runtime_config_template": (
                Path(attempt["runtime_config_template"]["path"]),
                (
                    attempt["runtime_config_template"]["size_bytes"],
                    attempt["runtime_config_template"]["sha256"],
                ),
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
        try:
            integrity["runtime_vins_config"] = identity(expected_config)
        except BaseException as error:
            integrity["runtime_vins_config"] = {
                "error": f"{type(error).__name__}:{error}"
            }
        try:
            runtime_camera_identity = identity(expected_camera_config)
            integrity["runtime_camera_config"] = runtime_camera_identity
            if (
                runtime_camera_identity["size_bytes"],
                runtime_camera_identity["sha256"],
            ) != (
                attempt["source_camera_config"]["size_bytes"],
                attempt["source_camera_config"]["sha256"],
            ):
                pipeline_failures.append("RUNTIME_CAMERA_CONFIG_DRIFT")
        except BaseException as error:
            integrity["runtime_camera_config"] = {
                "error": f"{type(error).__name__}:{error}"
            }
            pipeline_failures.append("RUNTIME_CAMERA_CONFIG_UNREADABLE")
        integrity["controls_post"] = {}
        frozen_controls = freeze.get("controls", {})
        for path in CONTROL_PATHS:
            try:
                observed = identity(path)
                integrity["controls_post"][path.name] = observed
                if not identity_matches(observed, frozen_controls.get(path.name)):
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
            "schema_version": "aqua-fe-fair-stability-vins-result-v5",
            "experiment_id": EXPERIMENT_ID,
            "status": status, "clean_success": clean_success,
            "case_id": case_id, "arm": arm, "repeat": repeat,
            "attempt_index": attempt_index,
            "tag": attempt["tag"],
            "backend_id": "DEV_NATIVEQ_SCHEDFIX_RUNTIMEEXCL_V5",
            "failure_codes": failures,
            "pipeline_failure_codes": pipeline_failures,
            "algorithm_failure_codes": algorithm_failures,
            "execution": execution, "trajectory": trajectory, "log": log,
            "child_start": start,
            "child_lifecycle": lifecycle,
            "runtime_resource_monitor": {
                "identity": monitor_identity,
                "intrusion_detected": monitor_receipt.get("intrusion_detected"),
                "monitor_proven": monitor_receipt.get("monitor_proven"),
                "pipeline_failure_reasons": monitor_receipt.get(
                    "pipeline_failure_reasons", []
                ),
            },
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
    """Use the receipt-validated state machine, including replacement attempts."""
    from summarize_fair_stability_v5 import summarize as summarize_receipts

    return summarize_receipts()


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
            gate = resource_gate(
                port=int(attempt["port"]),
                experiment_root=EXPERIMENT_ROOT,
                workspace_root=ROOT,
            )
            result = {"attempt": attempt, "resource_gate": gate, "ready": gate["ready"]}
        elif args.command == "run":
            result = run_attempt(args.case, args.arm, args.repeat, args.attempt_index)
        elif args.command == "resource-check":
            result = resource_gate(
                port=args.port,
                experiment_root=EXPERIMENT_ROOT,
                workspace_root=ROOT,
            )
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
