#!/usr/bin/env python3
"""Late-bound ten-item A08 VINS replay supervisor.

Importing this module is inert.  ``preflight`` and ``audit`` are read-only.
No backend can start until both accepted frontend receipts have been bound into
a separately published final execution lock.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, Mapping, Optional, Sequence


WORKSPACE = Path("/home/ma/AQUA-FE_WS")
EXPERIMENT = Path("/mnt/data/AQUA-FE_WS/experiments/a08_history_matched_controls_v1")
OVERLAY = EXPERIMENT / "recovered_july_core_overlay_v1"
OVERLAY_RUN_ROOT = OVERLAY / "logs/aqualoc_archaeo_vins"
FRONTEND_ROOT = EXPERIMENT / "frontends_v1"
BACKEND_ROOT = EXPERIMENT / "backend_replays_v1"
RUNTIME_ROOT = EXPERIMENT / "runtime/backend_replays_v1"
PROTOCOL = WORKSPACE / "papers/a08_recovered_july_history_matched_backend_replays_v1_protocol.md"
DEFAULT_LOCK = WORKSPACE / "papers/a08_recovered_july_history_matched_backend_replays_v1_execution_lock.json"

KLT_RECEIPT = FRONTEND_ROOT / "klt_attempt002_export_receipt_v1.json"
XFEAT_RECEIPT = FRONTEND_ROOT / "xfeat_attempt002_export_receipt_v1.json"
DEFAULT_RECEIPTS = {"klt": KLT_RECEIPT, "xfeat": XFEAT_RECEIPT}

RAW_BAG = EXPERIMENT / "raw/archaeo08_0000_4660.bag"
SOURCE_ARCHIVE = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_sequence_8_raw_data.tar.gz"
)
GROUND_TRUTH = Path(
    "/mnt/data/AQUA-FE_WS/datasets/full_downloads/aqualoc/"
    "Archaeological_site_sequences/archaeo_groundtruth_files/"
    "new_archaeo_colmap_traj_sequence_08.txt"
)
FRONTEND_RECEIPT_GROUND_TRUTH_PATH = WORKSPACE / (
    "datasets/full_downloads/aqualoc/Archaeological_site_sequences/"
    "archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_08.txt"
)
OVERLAY_MANIFEST = OVERLAY / "execution_tree_manifest_v1.json"
OVERLAY_RECEIPT = OVERLAY / "overlay_materialization_receipt_v1.json"
FRONTEND_CONFIG = OVERLAY / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"
BACKEND_SHELL = OVERLAY / "scripts/run_learned_seedchain_eval.sh"
REPLAY_ONLY_GUARD = WORKSPACE / "scripts/run_a08_recovered_july_backend_replay_only_guard_v1.sh"
ARCHAEO_SHELL = OVERLAY / "scripts/run_aqualoc_archaeo_vins_eval.sh"
LEARNED_ENV = OVERLAY / "scripts/learned_seedchain_env.sh"
RECORD_ENV = OVERLAY / "scripts/record_vins_env.sh"
WAIT_SUBSCRIBERS = OVERLAY / "scripts/wait_for_ros_subscribers.py"
LOCAL_APE = OVERLAY / "scripts/evaluate_vins_sim_ape.py"
NETNS_ENTRY = WORKSPACE / "scripts/enter_samehistory_backend_netns_v4.py"
SAFETY_BASE = WORKSPACE / "scripts/run_samehistory_system_a10_finalonline_v4_backend_recovery.py"
VINS_BINARY = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node")
ROS_SETUP = Path("/opt/ros/noetic/setup.bash")
VINS_SETUP = Path("/home/ma/SLAM/VINS-Fusion-origin/devel/setup.bash")

UNSHARE = Path("/usr/bin/unshare")
PYTHON38 = Path("/usr/bin/python3.8")
BASH = Path("/usr/bin/bash")
FORMAL_PORT = 11981
TIMEOUT_SECONDS = 900
FEATURE_TOPIC = "/feature_tracker/feature"
CAMERA_TOPIC = "/camera/image_raw"
IMU_TOPIC = "/rtimulib_node/imu"
GT_TOPIC = "/aqualoc/colmap_gt"

RAW_BAG_EXPECTED = (
    1_242_450_892,
    "9f7d21f7fe45f12f72c7e922be39e9b48601006f14254a5355992aab17ee16c2",
)
SOURCE_ARCHIVE_EXPECTED = (
    2_316_571_070,
    "b45e4f6dbf852ff8d7e5c9386e3df2db4daa84d1841f1eafb01a4637d2fe9153",
)
GROUND_TRUTH_EXPECTED = (
    54_593,
    "519d27750efd7e53c27a2bc3ff35bc9cf5c9fd2b888184eefea284bcfe8f2b6c",
)

ITEM_ORDER = tuple(
    item
    for repeat in range(1, 6)
    for item in (f"KLT_R{repeat:02d}", f"XFEAT_R{repeat:02d}")
)
CLAIM_NAME = "process_start_claim_v1.json"
RECEIPT_NAME = "formal_run_receipt_v1.json"
LOG_NAME = "supervisor_process.log"
LOCK_SCHEMA = "aqua-fe-a08-recovered-july-backend-execution-lock-v1"
RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-backend-replay-receipt-v1"
FRONTEND_RECEIPT_SCHEMA = "aqua-fe-a08-recovered-july-natural-history-frontend-receipt-v1"
LOCK_STATUS = "FROZEN_AFTER_BOTH_ACCEPTED_FRONTENDS_BEFORE_BACKEND_LAUNCH"
BUILD_LOCK_TOKEN = "A08_BUILD_FINAL_BACKEND_LOCK_AFTER_BOTH_ACCEPTED_FRONTEND_RECEIPTS"
AUTHORIZATION_TOKENS = {
    item: f"A08_BACKEND_REPLAY_V1_RUN_{item}_EXACTLY_ONCE" for item in ITEM_ORDER
}

# This module is imported only by the mutating run-item path.  Pinning prevents
# an unreviewed safety implementation from gaining process-control authority.
SAFETY_BASE_EXPECTED = (
    253_456,
    "4ac06b942a38f0074df6d2193d17d634673bc360865cee752f5732241224c277",
)

BASE_ENVIRONMENT = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "SHELL": "/bin/bash",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "TZ": "UTC",
    "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "CMAKE_PREFIX_PATH": "/home/ma/dave_ws/devel:/home/ma/uuv_ws/devel:/opt/ros/noetic",
    "LD_LIBRARY_PATH": "/home/ma/dave_ws/devel/lib:/home/ma/uuv_ws/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
    "PKG_CONFIG_PATH": "/home/ma/dave_ws/devel/lib/pkgconfig:/home/ma/uuv_ws/devel/lib/pkgconfig:/opt/ros/noetic/lib/pkgconfig:/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig",
    "PYTHONPATH": "/home/ma/dave_ws/devel/lib/python3/dist-packages:/home/ma/uuv_ws/devel/lib/python3/dist-packages:/opt/ros/noetic/lib/python3/dist-packages",
    "ROS_DISTRO": "noetic",
    "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
    "ROS_PACKAGE_PATH": "/home/ma/dave_ws/src:/home/ma/uuv_ws/src:/opt/ros/noetic/share",
    "ROS_PYTHON_VERSION": "3",
    "ROS_ROOT": "/opt/ros/noetic/share/ros",
    "ROS_VERSION": "1",
    "ROS_MASTER_URI": "http://localhost:11981",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
}

COMMON_BACKEND_ENVIRONMENT = {
    "ROOT": str(OVERLAY),
    "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
    "AQUALOC_ROOT": str(SOURCE_ARCHIVE.parent),
    "RAW_TAR": str(SOURCE_ARCHIVE),
    "GT_TXT": str(GROUND_TRUTH),
    "RAW_BAG": str(RAW_BAG),
    "FRONTEND_CONFIG": str(FRONTEND_CONFIG),
    "AQUAFE_SEEDCHAIN_PROFILE": "lineage_early_seed_scan",
    "RUN_VINS": "1",
    "FORCE_RAW": "0",
    "FORCE_EXPORT": "0",
    "EXPORT_FEATURES": "0",
    "VINS_NODE_BIN": str(VINS_BINARY),
    "WAIT_FOR_VINS_SUBSCRIBERS": "1",
    "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
    "VINS_MULTIPLE_THREAD": "0",
    "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
    "VINS_TD": "-0.053694112369382575",
    "VINS_ESTIMATE_TD": "0",
    "VINS_MAX_SOLVER_TIME": "0.04",
    "VINS_MAX_NUM_ITERATIONS": "8",
    "PLAY_RATE": "1.0",
    "ROSBAG_PLAY_DELAY": "3",
    "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
    "POST_PLAY_SLEEP": "8",
    "BACKEND_REPLAY_ONLY": "0",
    "A08_STRICT_REPLAY_ONLY_GUARD": "1",
    "PORT": str(FORMAL_PORT),
}

EXPECTED_OUTPUTS = (
    "vins_output/vio.csv",
    "vins.log",
    "ape.txt",
    "replay_manifest.txt",
    "vins_aqualoc_archaeo_external.yaml",
    "aqualoc_archaeo08_pinhole.yaml",
    "vins_env_manifest.txt",
    "roscore.log",
    "network_namespace_manifest.json",
    "replay_only_guard_manifest.json",
    "frontend_metrics.csv",
)


class BackendProtocolError(RuntimeError):
    """A frozen A08 backend contract was not satisfied."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BackendProtocolError(code)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def compact_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> None:
    path = path.absolute()
    require(path.exists() and not path.is_symlink(), f"NOT_REGULAR:{label}:{path}")
    require(stat.S_ISREG(path.lstat().st_mode), f"NOT_REGULAR:{label}:{path}")
    require(path.resolve(strict=True) == path, f"SYMLINK_COMPONENT:{label}:{path}")


def identity(path: Path) -> dict[str, Any]:
    path = path.absolute()
    regular_file(path, "identity")
    before = path.stat()
    digest = sha256_file(path)
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        all(getattr(before, key) == getattr(after, key) for key in fields),
        f"FILE_CHANGED_DURING_HASH:{path}",
    )
    return {"path": str(path), "size_bytes": after.st_size, "sha256": digest}


def stable_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.absolute()
    regular_file(path, "json")
    before = path.stat()
    raw = path.read_bytes()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        all(getattr(before, key) == getattr(after, key) for key in fields),
        f"JSON_CHANGED_DURING_READ:{path}",
    )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendProtocolError(f"INVALID_JSON:{path}:{type(error).__name__}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{path}")
    return value, {
        "path": str(path), "size_bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def normalized_absolute(value: Any, label: str) -> Path:
    require(isinstance(value, str) and value and "\x00" not in value, f"PATH_TYPE:{label}")
    path = Path(value)
    require(path.is_absolute() and os.path.normpath(value) == value, f"PATH_NORMALIZATION:{label}")
    return path


def contained(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        return True
    except ValueError:
        return False


def validate_identity_claim(claim: Any, label: str) -> dict[str, Any]:
    require(isinstance(claim, dict), f"IDENTITY_TYPE:{label}")
    require(set(claim) == {"path", "size_bytes", "sha256"}, f"IDENTITY_KEYS:{label}")
    path = normalized_absolute(claim.get("path"), label)
    size = claim.get("size_bytes")
    digest = claim.get("sha256")
    require(isinstance(size, int) and size >= 0, f"IDENTITY_SIZE:{label}")
    require(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
            f"IDENTITY_SHA256:{label}")
    actual = identity(path)
    require(actual == claim, f"IDENTITY_DRIFT:{label}:{path}")
    return actual


def receipt_presence(
    receipt_paths: Mapping[str, Path] = DEFAULT_RECEIPTS,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for stage in ("klt", "xfeat"):
        path = Path(receipt_paths[stage]).absolute()
        if not path.exists() and not path.is_symlink():
            result[stage] = {"path": str(path), "state": "MISSING"}
        elif path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
            result[stage] = {"path": str(path), "state": "INVALID_KIND"}
        else:
            result[stage] = {"path": str(path), "state": "PRESENT_REGULAR"}
    return result


def load_frontend_binding(stage: str, receipt_path: Path, run_root: Path) -> dict[str, Any]:
    require(stage in {"klt", "xfeat"}, f"FRONTEND_STAGE:{stage}")
    receipt, receipt_identity = stable_json(receipt_path)
    require(receipt.get("schema_version") == FRONTEND_RECEIPT_SCHEMA,
            f"FRONTEND_RECEIPT_SCHEMA:{stage}")
    require(receipt.get("status") == "PASS_FRONTEND_EXPORT_ACCEPTED",
            f"FRONTEND_RECEIPT_STATUS:{stage}")
    require(receipt.get("stage") == stage, f"FRONTEND_RECEIPT_STAGE:{stage}")
    terminal = receipt.get("terminal_process")
    require(isinstance(terminal, dict), f"FRONTEND_TERMINAL:{stage}")
    single_popen_proven = bool(
        terminal.get("single_supervisor_popen") is True
        or (
            terminal.get("original_single_supervisor_popen") is True
            and terminal.get("additional_exporter_popen_count") == 0
        )
    )
    require(single_popen_proven, f"FRONTEND_SINGLE_POPEN:{stage}")
    if terminal.get("single_supervisor_popen") is True:
        require(terminal.get("return_code") == 0, f"FRONTEND_TERMINAL_RC:{stage}")
    else:
        continuation = receipt.get("supervisor_continuation_recovery")
        require(
            terminal.get("return_code_observed_by_original_supervisor") is False
            and terminal.get("successful_shell_completion_sentinel_observed") is True
            and terminal.get("success_inferred_under_set_euo_pipefail") is True
            and isinstance(continuation, dict)
            and continuation.get("classification")
            == "SAME_EXPORTER_ARTIFACT_AUDIT_AFTER_TOOL_WALL_TIMEOUT"
            and continuation.get("exporter_restarted") is False
            and continuation.get("exporter_invocation_count") == 1
            and continuation.get("additional_exporter_popen_count") == 0
            and continuation.get("audit_only") is True
            and continuation.get("no_vins_or_accuracy") is True,
            f"FRONTEND_CONTINUATION_AUTHORITY:{stage}",
        )
    require(terminal.get("automatic_retry_count") == 0,
            f"FRONTEND_AUTOMATIC_RETRY:{stage}")
    boundary = receipt.get("claim_boundary")
    require(isinstance(boundary, dict), f"FRONTEND_BOUNDARY:{stage}")
    require(boundary.get("export_only") is True, f"FRONTEND_NOT_EXPORT_ONLY:{stage}")
    require(boundary.get("vins_or_slam_executed") is False,
            f"FRONTEND_VINS_EXECUTED:{stage}")
    require(receipt.get("inputs_before") == receipt.get("inputs_after"),
            f"FRONTEND_INPUTS_CHANGED:{stage}")
    input_claims = receipt.get("inputs_before")
    require(isinstance(input_claims, dict), f"FRONTEND_INPUT_CLAIMS:{stage}")
    expected_upstream_claims = {
        str(RAW_BAG): RAW_BAG_EXPECTED,
        str(SOURCE_ARCHIVE): SOURCE_ARCHIVE_EXPECTED,
        str(FRONTEND_RECEIPT_GROUND_TRUTH_PATH): GROUND_TRUTH_EXPECTED,
    }
    for input_path, expected_identity in expected_upstream_claims.items():
        claim = input_claims.get(input_path)
        require(
            isinstance(claim, dict)
            and claim.get("path") == input_path
            and claim.get("size_bytes") == expected_identity[0]
            and claim.get("sha256") == expected_identity[1],
            f"FRONTEND_UPSTREAM_INPUT_BINDING:{stage}:{input_path}",
        )

    raw_contract = receipt.get("raw_contract")
    require(isinstance(raw_contract, dict), f"FRONTEND_RAW_CONTRACT:{stage}")
    require(raw_contract.get("counts") == {
        CAMERA_TOPIC: 4_661, IMU_TOPIC: 46_631, GT_TOPIC: 226,
    }, f"FRONTEND_RAW_COUNTS:{stage}")
    feature_stamps = raw_contract.get("feature_stamps")
    require(
        isinstance(feature_stamps, list)
        and len(feature_stamps) == 2_330
        and all(isinstance(value, int) and value >= 0 for value in feature_stamps)
        and all(right > left for left, right in zip(feature_stamps, feature_stamps[1:])),
        f"FRONTEND_RAW_FEATURE_STAMPS:{stage}",
    )
    raw_streams = raw_contract.get("copied_stream_sha256")
    require(
        isinstance(raw_streams, dict)
        and set(raw_streams) == {IMU_TOPIC, GT_TOPIC}
        and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                for value in raw_streams.values()),
        f"FRONTEND_RAW_STREAMS:{stage}",
    )

    artifact = receipt.get("artifact_audit")
    require(isinstance(artifact, dict), f"FRONTEND_ARTIFACT:{stage}")
    if stage == "xfeat":
        require(artifact.get("status") == "PASS_XFEAT_METHOD_NATIVE_PROBE_AND_FINAL_EXPORT_AUDIT",
                "XFEAT_TOPLEVEL_AUDIT_STATUS")
        artifact = artifact.get("final")
        require(isinstance(artifact, dict), "XFEAT_FINAL_AUDIT")
    require(artifact.get("status") == f"PASS_{stage.upper()}_EXPORT_AUDIT",
            f"FRONTEND_AUDIT_STATUS:{stage}")
    require(artifact.get("topic_counts") == {
        FEATURE_TOPIC: 2_330, IMU_TOPIC: 46_631, GT_TOPIC: 226,
    }, f"FRONTEND_BAG_TOPIC_COUNTS:{stage}")
    require(artifact.get("feature_messages") == 2_330,
            f"FRONTEND_BAG_FEATURE_COUNT:{stage}")
    require(
        artifact.get("feature_first_ns") == feature_stamps[0]
        and artifact.get("feature_last_ns") == feature_stamps[-1],
        f"FRONTEND_BAG_FEATURE_SUPPORT:{stage}",
    )
    require(
        artifact.get("copied_stream_sha256") == raw_streams,
        f"FRONTEND_BAG_COPIED_HISTORY:{stage}",
    )
    outputs = artifact.get("outputs")
    require(isinstance(outputs, dict) and set(outputs) == {
        "features_bag", "frontend_metrics", "camera_config"
    }, f"FRONTEND_OUTPUT_KEYS:{stage}")
    validated = {
        key: validate_identity_claim(outputs[key], f"{stage}:{key}")
        for key in ("features_bag", "frontend_metrics", "camera_config")
    }
    run_dir = normalized_absolute(artifact.get("run_dir"), f"{stage}:run_dir")
    require(contained(run_dir, run_root) and run_dir.parent == run_root.absolute(),
            f"FRONTEND_RUN_ROOT:{stage}")
    require(run_dir.resolve(strict=True) == run_dir, f"FRONTEND_RUN_SYMLINK:{stage}")
    require(Path(validated["features_bag"]["path"]) == run_dir / "features.bag",
            f"FRONTEND_BAG_BINDING:{stage}")
    require(Path(validated["frontend_metrics"]["path"]) == run_dir / "frontend_metrics.csv",
            f"FRONTEND_METRICS_BINDING:{stage}")
    require(Path(validated["camera_config"]["path"]) == run_dir / "aqualoc_archaeo08_pinhole.yaml",
            f"FRONTEND_CAMERA_BINDING:{stage}")
    return {
        "stage": stage,
        "receipt": receipt_identity,
        "run_dir": str(run_dir),
        "audit_status": artifact["status"],
        "history_contract": {
            "raw_contract_sha256": compact_sha256(raw_contract),
            "raw_counts": raw_contract["counts"],
            "feature_message_count": len(feature_stamps),
            "feature_first_ns": feature_stamps[0],
            "feature_last_ns": feature_stamps[-1],
            "copied_stream_sha256": raw_streams,
        },
        "_raw_contract": raw_contract,
        "_input_claims": input_claims,
        **validated,
    }


def resolve_frontend_bindings(
    receipt_paths: Mapping[str, Path] = DEFAULT_RECEIPTS,
    run_root: Path = OVERLAY_RUN_ROOT,
) -> dict[str, Any]:
    presence = receipt_presence(receipt_paths)
    require(
        all(row["state"] == "PRESENT_REGULAR" for row in presence.values()),
        "BOTH_ACCEPTED_FRONTEND_RECEIPTS_REQUIRED",
    )
    bindings = {
        stage: load_frontend_binding(stage, Path(receipt_paths[stage]), run_root.absolute())
        for stage in ("klt", "xfeat")
    }
    require(
        bindings["klt"]["_raw_contract"] == bindings["xfeat"]["_raw_contract"],
        "FRONTEND_HISTORY_RAW_CONTRACT_MISMATCH",
    )
    require(
        bindings["xfeat"]["_input_claims"].get(str(Path(receipt_paths["klt"]).absolute()))
        == bindings["klt"]["receipt"],
        "XFEAT_HISTORY_DOES_NOT_BIND_ACCEPTED_KLT_RECEIPT",
    )
    require(
        Path(bindings["klt"]["features_bag"]["path"])
        != Path(bindings["xfeat"]["features_bag"]["path"]),
        "FRONTEND_BAG_PATHS_MUST_DIFFER",
    )
    require(
        (bindings["klt"]["camera_config"]["size_bytes"],
         bindings["klt"]["camera_config"]["sha256"])
        == (bindings["xfeat"]["camera_config"]["size_bytes"],
            bindings["xfeat"]["camera_config"]["sha256"]),
        "FRONTEND_CAMERA_CONTENT_MISMATCH",
    )
    for value in bindings.values():
        value.pop("_raw_contract")
        value.pop("_input_claims")
    return bindings


def current_namespace(kind: str) -> str:
    require(kind in {"net", "user"}, f"NAMESPACE_KIND:{kind}")
    value = os.readlink(f"/proc/self/ns/{kind}")
    require(re.fullmatch(rf"{kind}:\[[0-9]+\]", value) is not None,
            f"NAMESPACE_VALUE:{kind}:{value}")
    return value


def arm_spec(item_id: str) -> dict[str, Any]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    arm = "klt" if item_id.startswith("KLT_") else "xfeat"
    repeat = int(item_id[-2:])
    method = "klt" if arm == "klt" else "hybrid_xfeat"
    tag = f"a08_recoveredjuly_hist0000_4660_backend_{arm}_r{repeat:02d}_v1"
    return {
        "arm": arm, "repeat_index": repeat, "method": method, "tag": tag,
        "run_leaf": f"external_{method}_every2_{tag}",
    }


def item_environment(item_id: str, bindings: Mapping[str, Any]) -> dict[str, str]:
    spec = arm_spec(item_id)
    environment = dict(BASE_ENVIRONMENT)
    environment.update(COMMON_BACKEND_ENVIRONMENT)
    environment.update({
        "TAG": spec["tag"],
        "ROS_HOME": str(RUNTIME_ROOT / item_id / "ros_home"),
        "ROS_LOG_DIR": str(RUNTIME_ROOT / item_id / "ros_log"),
        "FEATURE_BAG_OVERRIDE": str(bindings[spec["arm"]]["features_bag"]["path"]),
        "A08_FEATURE_BAG_SIZE_BYTES": str(bindings[spec["arm"]]["features_bag"]["size_bytes"]),
        "A08_FEATURE_BAG_SHA256": str(bindings[spec["arm"]]["features_bag"]["sha256"]),
        "A08_FRONTEND_METRICS": str(bindings[spec["arm"]]["frontend_metrics"]["path"]),
        "A08_FRONTEND_METRICS_SIZE_BYTES": str(bindings[spec["arm"]]["frontend_metrics"]["size_bytes"]),
        "A08_FRONTEND_METRICS_SHA256": str(bindings[spec["arm"]]["frontend_metrics"]["sha256"]),
        "A08_FRONTEND_CAMERA_CONFIG": str(bindings[spec["arm"]]["camera_config"]["path"]),
        "A08_FRONTEND_CAMERA_SIZE_BYTES": str(bindings[spec["arm"]]["camera_config"]["size_bytes"]),
        "A08_FRONTEND_CAMERA_SHA256": str(bindings[spec["arm"]]["camera_config"]["sha256"]),
        "A08_RAW_BAG_SIZE_BYTES": str(RAW_BAG_EXPECTED[0]),
        "A08_RAW_BAG_SHA256": RAW_BAG_EXPECTED[1],
        "A08_RAW_TAR_SIZE_BYTES": str(SOURCE_ARCHIVE_EXPECTED[0]),
        "A08_RAW_TAR_SHA256": SOURCE_ARCHIVE_EXPECTED[1],
        "A08_GT_SIZE_BYTES": str(GROUND_TRUTH_EXPECTED[0]),
        "A08_GT_SHA256": GROUND_TRUTH_EXPECTED[1],
        "A08_ITEM_OUTPUT_DIR": str(BACKEND_ROOT / item_id),
        "A08_ITEM_ID": item_id,
        "A08_WORKSPACE_LINK": str(OVERLAY_RUN_ROOT / spec["run_leaf"]),
        "A08_OVERLAY_BACKEND_SHELL": str(BACKEND_SHELL),
    })
    return environment


def build_items(
    bindings: Mapping[str, Any], host_net: str, host_user: str,
) -> dict[str, Any]:
    require(re.fullmatch(r"net:\[[0-9]+\]", host_net) is not None, "HOST_NETNS")
    require(re.fullmatch(r"user:\[[0-9]+\]", host_user) is not None, "HOST_USERNS")
    result: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        output_dir = BACKEND_ROOT / item_id
        workspace_link = OVERLAY_RUN_ROOT / spec["run_leaf"]
        inner = [
            str(BASH), str(REPLAY_ONLY_GUARD), "aqualoc_archaeo", "8", "0", "4660",
            spec["method"], "2",
        ]
        argv = [
            str(UNSHARE), "--user", "--map-root-user", "--net",
            str(PYTHON38), str(NETNS_ENTRY),
            "--output-dir", str(output_dir),
            "--formal-port", str(FORMAL_PORT),
            "--host-network-namespace", host_net,
            "--host-user-namespace", host_user,
            "--", *inner,
        ]
        environment = item_environment(item_id, bindings)
        result[item_id] = {
            "item_id": item_id,
            "arm": spec["arm"],
            "repeat_index": spec["repeat_index"],
            "method": spec["method"],
            "output_dir": str(output_dir),
            "workspace_link": str(workspace_link),
            "argv": argv,
            "inner_backend_argv_sha256": compact_sha256(inner),
            "host_network_namespace": host_net,
            "host_user_namespace": host_user,
            "env": environment,
            "cwd": str(OVERLAY),
            "timeout_seconds": TIMEOUT_SECONDS,
            "expected_outputs": list(EXPECTED_OUTPUTS),
            "input_binding": bindings[spec["arm"]],
            "command_sha256": compact_sha256({"argv": argv, "env": environment}),
        }
    return result


def static_identity_paths() -> dict[str, Path]:
    paths = {
        "runner": Path(__file__).resolve(),
        "protocol": PROTOCOL,
        "raw_bag": RAW_BAG,
        "source_archive": SOURCE_ARCHIVE,
        "ground_truth": GROUND_TRUTH,
        "overlay_manifest": OVERLAY_MANIFEST,
        "overlay_receipt": OVERLAY_RECEIPT,
        "frontend_config": FRONTEND_CONFIG,
        "backend_shell": BACKEND_SHELL,
        "replay_only_guard": REPLAY_ONLY_GUARD,
        "archaeo_shell": ARCHAEO_SHELL,
        "learned_environment": LEARNED_ENV,
        "record_vins_environment": RECORD_ENV,
        "wait_for_subscribers": WAIT_SUBSCRIBERS,
        "local_ape_diagnostic": LOCAL_APE,
        "network_namespace_entry": NETNS_ENTRY,
        "process_safety_base": SAFETY_BASE,
        "vins_binary": VINS_BINARY,
        "ros_setup": ROS_SETUP,
        "vins_setup": VINS_SETUP,
        "unshare": UNSHARE,
        "python38": PYTHON38,
        "bash": BASH,
        "ip": Path("/usr/bin/ip"),
        "cp": Path("/usr/bin/cp"),
        "readlink": Path("/usr/bin/readlink"),
        "sha256sum": Path("/usr/bin/sha256sum"),
        "stat": Path("/usr/bin/stat"),
    }
    # setup.bash is not the whole catkin authority: it sources setup.sh, which
    # executes _setup_util.py and then every profile hook found on the frozen
    # CMAKE_PREFIX_PATH.  Include that transitive source set in the final lock.
    catkin_prefixes = (
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel"),
        Path("/home/ma/dave_ws/devel"),
        Path("/home/ma/uuv_ws/devel"),
        Path("/opt/ros/noetic"),
    )
    for index, prefix in enumerate(catkin_prefixes):
        paths[f"catkin_marker_{index}"] = prefix / ".catkin"
    for label, prefix in (
        ("vins", catkin_prefixes[0]), ("ros", catkin_prefixes[3]),
    ):
        paths[f"{label}_setup_sh"] = prefix / "setup.sh"
        paths[f"{label}_setup_util"] = prefix / "_setup_util.py"
    for index, prefix in enumerate(catkin_prefixes):
        profile = prefix / "etc/catkin/profile.d"
        if not profile.exists() and not profile.is_symlink():
            continue
        require(profile.is_dir() and not profile.is_symlink(),
                f"CATKIN_PROFILE_DIRECTORY:{profile}")
        for child in sorted(profile.iterdir(), key=lambda value: value.name):
            require(child.is_file() and not child.is_symlink(),
                    f"CATKIN_PROFILE_ENTRY:{child}")
            paths[f"catkin_profile_{index}_{child.name}"] = child
    return paths


def collect_static_identities() -> dict[str, Any]:
    values = {name: identity(path) for name, path in static_identity_paths().items()}
    require(
        (values["process_safety_base"]["size_bytes"],
         values["process_safety_base"]["sha256"]) == SAFETY_BASE_EXPECTED,
        "SAFETY_BASE_BOOTSTRAP_DRIFT",
    )
    for label, expected in (
        ("raw_bag", RAW_BAG_EXPECTED),
        ("source_archive", SOURCE_ARCHIVE_EXPECTED),
        ("ground_truth", GROUND_TRUTH_EXPECTED),
    ):
        require(
            (values[label]["size_bytes"], values[label]["sha256"]) == expected,
            f"FROZEN_HISTORY_INPUT_DRIFT:{label}",
        )
    return values


def contract_core(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str,
) -> dict[str, Any]:
    items = build_items(bindings, host_net, host_user)
    return {
        "schema_version": LOCK_SCHEMA,
        "status": LOCK_STATUS,
        "campaign": "A08_RECOVERED_JULY_HISTORY_MATCHED_BACKEND_REPLAYS_V1",
        "item_order": list(ITEM_ORDER),
        "policy": {
            "repeat_count_per_arm": 5,
            "fixed_interleaving": True,
            "single_supervisor_popen_per_item": True,
            "automatic_retry_count": 0,
            "replacement_repeat_permitted": False,
            "terminal_result_failure_does_not_block_later_items": True,
            "execution_integrity_failure_blocks_later_items": True,
            "vins_multiple_thread": 0,
            "fresh_user_and_network_namespace_per_item": True,
            "formal_internal_ros_port": FORMAL_PORT,
            "ambient_desktop_allowed": True,
            "runtime_or_throughput_claim_permitted": False,
            "common_support_score_interval_source_indices": [4000, 4660],
        },
        "host_namespace": {"network": host_net, "user": host_user},
        "frontend_bindings": dict(bindings),
        "static_identities": dict(static_identities),
        "items": items,
    }


def build_lock_payload(
    bindings: Mapping[str, Any], static_identities: Mapping[str, Any],
    host_net: str, host_user: str, created_at_utc: str,
) -> dict[str, Any]:
    core = contract_core(bindings, static_identities, host_net, host_user)
    payload = {**core, "created_at_utc": created_at_utc}
    payload["contract_sha256"] = compact_sha256(payload)
    return payload


def expected_lock_from_current_authority(bindings: Mapping[str, Any], created: str) -> dict[str, Any]:
    return build_lock_payload(
        bindings, collect_static_identities(), current_namespace("net"),
        current_namespace("user"), created,
    )


def verify_lock(lock_path: Path, bindings: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    lock, lock_identity = stable_json(lock_path)
    created = lock.get("created_at_utc")
    require(isinstance(created, str) and created, "LOCK_CREATED_AT")
    expected = expected_lock_from_current_authority(bindings, created)
    require(lock == expected, "EXECUTION_LOCK_AUTHORITY_DRIFT")
    return lock, lock_identity


def preflight_readonly(
    lock_path: Path = DEFAULT_LOCK,
    receipt_paths: Mapping[str, Path] = DEFAULT_RECEIPTS,
    run_root: Path = OVERLAY_RUN_ROOT,
) -> dict[str, Any]:
    presence = receipt_presence(receipt_paths)
    missing = [stage for stage, row in presence.items() if row["state"] == "MISSING"]
    invalid = [stage for stage, row in presence.items() if row["state"] == "INVALID_KIND"]
    if missing or invalid:
        premature_lock = lock_path.exists() or lock_path.is_symlink()
        status = "WAITING_FOR_BOTH_ACCEPTED_FRONTEND_RECEIPTS"
        if invalid:
            status = "BLOCKED_INVALID_FRONTEND_RECEIPT_KIND"
        elif premature_lock:
            status = "BLOCKED_PREMATURE_LOCK_WITHOUT_BOTH_FRONTEND_RECEIPTS"
        return {
            "status": status,
            "receipt_presence": presence,
            "missing": missing,
            "invalid": invalid,
            "dynamic_artifacts_opened": False,
            "static_hashing_performed": False,
            "lock_path": str(lock_path.absolute()),
            "lock_present": premature_lock,
            "item_order": list(ITEM_ORDER),
            "read_only": True,
        }
    try:
        bindings = resolve_frontend_bindings(receipt_paths, run_root)
        if not lock_path.exists() and not lock_path.is_symlink():
            require_campaign_unstarted()
            static_identities = collect_static_identities()
            core = contract_core(
                bindings, static_identities, current_namespace("net"), current_namespace("user")
            )
            return {
                "status": "READY_TO_BUILD_FINAL_EXECUTION_LOCK",
                "receipt_presence": presence,
                "frontend_bindings": bindings,
                "candidate_core_sha256": compact_sha256(core),
                "lock_path": str(lock_path.absolute()),
                "lock_present": False,
                "item_order": list(ITEM_ORDER),
                "read_only": True,
            }
        lock, lock_identity = verify_lock(lock_path, bindings)
        return {
            "status": "PASS_LOCKED_READY_FOR_AUTHORIZED_ITEM",
            "receipt_presence": presence,
            "frontend_bindings": bindings,
            "lock": lock_identity,
            "contract_sha256": lock["contract_sha256"],
            "item_order": list(ITEM_ORDER),
            "read_only": True,
        }
    except (BackendProtocolError, OSError, ValueError) as error:
        return {
            "status": "BLOCKED_PREFLIGHT",
            "receipt_presence": presence,
            "error": f"{type(error).__name__}:{error}",
            "lock_path": str(lock_path.absolute()),
            "item_order": list(ITEM_ORDER),
            "read_only": True,
        }


def inspect_item_readonly(item_id: str) -> dict[str, Any]:
    spec = arm_spec(item_id)
    output = BACKEND_ROOT / item_id
    workspace = OVERLAY_RUN_ROOT / spec["run_leaf"]
    runtime = RUNTIME_ROOT / item_id
    claim = output / CLAIM_NAME
    receipt = output / RECEIPT_NAME
    row: dict[str, Any] = {
        "item_id": item_id, "output_dir": str(output),
        "workspace_link": str(workspace), "state": "NOT_STARTED",
    }
    if output.is_symlink() or (output.exists() and not output.is_dir()):
        row["state"] = "INVALID_OUTPUT_KIND"
    elif receipt.exists() or receipt.is_symlink():
        try:
            value, receipt_id = stable_json(receipt)
            integrity = value.get("execution_integrity")
            control_valid = bool(
                value.get("schema_version") == RECEIPT_SCHEMA
                and value.get("item_id") == item_id
                and value.get("status") in {
                    "PASS_BACKEND_REPLAY_ACCEPTED",
                    "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
                }
                and value.get("launch_allowance_consumed") is True
                and value.get("retry_count") == 0
                and value.get("replacement_permitted") is False
                and isinstance(integrity, dict)
                and integrity.get("status") in {"PASS", "FAIL"}
            )
            require(control_valid, f"TERMINAL_RECEIPT_CONTROL:{item_id}")
            row.update({
                "state": "TERMINAL_RECEIPT",
                "receipt": receipt_id,
                "disposition": value.get("status"),
                "integrity": integrity.get("status"),
            })
        except (BackendProtocolError, OSError, ValueError) as error:
            row.update({"state": "INVALID_RECEIPT", "error": f"{type(error).__name__}:{error}"})
    elif claim.exists() or claim.is_symlink():
        row["state"] = "CLAIMED_WITHOUT_TERMINAL_RECEIPT"
    elif output.exists():
        try:
            row["state"] = "EMPTY_UNCLAIMED_OUTPUT" if not any(output.iterdir()) else "UNCONTROLLED_OUTPUT"
        except OSError as error:
            row.update({"state": "UNREADABLE_OUTPUT", "error": str(error)})
    if workspace.exists() or workspace.is_symlink():
        if workspace.is_symlink():
            row["workspace_observed"] = {"kind": "symlink", "target": os.readlink(workspace)}
        else:
            row["workspace_observed"] = {"kind": "non_symlink"}
        if row["state"] == "NOT_STARTED":
            row["state"] = "DIRTY_WORKSPACE"
    else:
        row["workspace_observed"] = {"kind": "absent"}
    if runtime.exists() or runtime.is_symlink():
        if runtime.is_symlink():
            row["runtime_observed"] = {
                "kind": "symlink", "target": os.readlink(runtime),
            }
        elif runtime.is_dir():
            row["runtime_observed"] = {"kind": "directory"}
        else:
            row["runtime_observed"] = {"kind": "non_directory"}
        if row["state"] == "NOT_STARTED":
            row["state"] = "DIRTY_RUNTIME"
    else:
        row["runtime_observed"] = {"kind": "absent"}
    return row


def audit_readonly(
    lock_path: Path = DEFAULT_LOCK,
    receipt_paths: Mapping[str, Path] = DEFAULT_RECEIPTS,
) -> dict[str, Any]:
    presence = receipt_presence(receipt_paths)
    lock_present = lock_path.exists() or lock_path.is_symlink()
    lock_audit: dict[str, Any] = {
        "path": str(lock_path.absolute()),
        "state": "PRESENT" if lock_present else "ABSENT",
        "authority": "NOT_CHECKED_LOCK_ABSENT" if not lock_present else "NOT_CHECKED",
    }
    verified_lock: Optional[dict[str, Any]] = None
    verified_lock_identity: Optional[dict[str, Any]] = None
    if lock_present:
        if all(row["state"] == "PRESENT_REGULAR" for row in presence.values()):
            try:
                bindings = resolve_frontend_bindings(receipt_paths)
                lock, lock_identity = verify_lock(lock_path, bindings)
                verified_lock = lock
                verified_lock_identity = lock_identity
                lock_audit.update({
                    "authority": "PASS",
                    "identity": lock_identity,
                    "contract_sha256": lock["contract_sha256"],
                })
            except (BackendProtocolError, OSError, ValueError) as error:
                lock_audit.update({
                    "authority": "FAIL",
                    "error": f"{type(error).__name__}:{error}",
                })
        else:
            lock_audit["authority"] = "BLOCKED_FRONTEND_RECEIPTS_UNAVAILABLE"
    rows = [inspect_item_readonly(item) for item in ITEM_ORDER]
    if verified_lock is not None and verified_lock_identity is not None:
        for row in rows:
            if row["state"] != "TERMINAL_RECEIPT":
                continue
            try:
                prior_receipt(
                    verified_lock_identity,
                    verified_lock["items"][row["item_id"]],
                )
                row["deep_terminal_evidence_audit"] = "PASS"
            except (BackendProtocolError, OSError, ValueError) as error:
                row.update({
                    "state": "INVALID_TERMINAL_EVIDENCE",
                    "deep_terminal_evidence_audit": "FAIL",
                    "error": f"{type(error).__name__}:{error}",
                })
    blocked_by: Optional[str] = None
    next_item: Optional[str] = None
    for row in rows:
        if row["state"] == "TERMINAL_RECEIPT" and row.get("integrity") == "PASS":
            continue
        if row["state"] == "NOT_STARTED" and blocked_by is None:
            next_item = row["item_id"]
        else:
            blocked_by = row["item_id"]
        break
    next_item_block_reason: Optional[str] = None
    if lock_audit.get("authority") != "PASS":
        next_item = None
        next_item_block_reason = f"LOCK_AUTHORITY:{lock_audit.get('authority')}"
    elif blocked_by is not None:
        next_item_block_reason = f"PRIOR_ITEM:{blocked_by}"
    return {
        "status": "READ_ONLY_AUDIT",
        "read_only": True,
        "receipt_presence": presence,
        "lock": lock_audit,
        "item_order": list(ITEM_ORDER),
        "items": rows,
        "next_item_if_lock_and_authorization_pass": next_item,
        "next_item_block_reason": next_item_block_reason,
        "blocked_by_integrity_or_incomplete_item": blocked_by,
    }


def require_campaign_unstarted() -> None:
    for item_id in ITEM_ORDER:
        spec = arm_spec(item_id)
        paths = {
            "output": BACKEND_ROOT / item_id,
            "workspace": OVERLAY_RUN_ROOT / spec["run_leaf"],
            "runtime": RUNTIME_ROOT / item_id,
        }
        for label, path in paths.items():
            require(
                not path.exists() and not path.is_symlink(),
                f"CAMPAIGN_ALREADY_TOUCHED:{item_id}:{label}:{path}",
            )


def safety_module() -> ModuleType:
    actual = identity(SAFETY_BASE)
    require((actual["size_bytes"], actual["sha256"]) == SAFETY_BASE_EXPECTED,
            "SAFETY_BASE_BOOTSTRAP_DRIFT")
    specification = importlib.util.spec_from_file_location("a08_backend_a10_safety", SAFETY_BASE)
    require(specification is not None and specification.loader is not None, "SAFETY_MODULE_SPEC")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def prior_receipt(lock_identity: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, Any]:
    output = Path(str(item["output_dir"]))
    receipt_path = output / RECEIPT_NAME
    receipt, _ = stable_json(receipt_path)
    require(receipt.get("schema_version") == RECEIPT_SCHEMA,
            f"PRIOR_RECEIPT_SCHEMA:{item['item_id']}")
    require(receipt.get("item_id") == item["item_id"],
            f"PRIOR_RECEIPT_ITEM:{item['item_id']}")
    require(receipt.get("execution_lock") == lock_identity,
            f"PRIOR_RECEIPT_LOCK:{item['item_id']}")
    require(receipt.get("launch_allowance_consumed") is True,
            f"PRIOR_ALLOWANCE:{item['item_id']}")
    require(receipt.get("retry_count") == 0 and receipt.get("replacement_permitted") is False,
            f"PRIOR_RETRY_POLICY:{item['item_id']}")
    integrity = receipt.get("execution_integrity")
    require(isinstance(integrity, dict) and integrity.get("status") == "PASS",
            f"PRIOR_EXECUTION_INTEGRITY:{item['item_id']}")
    require(
        receipt.get("integrity_fault_latch") == []
        and integrity.get("irreversible_fault_latch_clear") is True,
        f"PRIOR_INTEGRITY_LATCH:{item['item_id']}",
    )
    require(
        integrity.get("authority_post") == {"status": "PASS", "lock": lock_identity}
        and integrity.get("claim_stable") is True
        and integrity.get("workspace_binding_stable") is True
        and integrity.get("owned_processes_drained") is True
        and integrity.get("artifact_integrity_issues") == [],
        f"PRIOR_EXECUTION_INTEGRITY_DETAILS:{item['item_id']}",
    )
    require(receipt.get("status") in {
        "PASS_BACKEND_REPLAY_ACCEPTED", "FAILED_BACKEND_REPLAY_NO_REPLACEMENT"
    }, f"PRIOR_DISPOSITION:{item['item_id']}")
    claim = receipt.get("claim")
    require(isinstance(claim, dict), f"PRIOR_CLAIM_IDENTITY:{item['item_id']}")
    require(
        Path(str(claim.get("path", ""))) == output / CLAIM_NAME
        and validate_identity_claim(claim, f"prior:{item['item_id']}:claim") == claim,
        f"PRIOR_CLAIM_BINDING:{item['item_id']}",
    )
    claim_value, _ = stable_json(output / CLAIM_NAME)
    require(
        claim_value.get("schema_version")
        == "aqua-fe-a08-recovered-july-backend-process-start-claim-v1"
        and claim_value.get("status")
        == "CLAIMED_ALLOWANCE_CONSUMED_NO_RETRY_NO_REPLACEMENT"
        and claim_value.get("item_id") == item["item_id"]
        and claim_value.get("execution_lock") == lock_identity
        and claim_value.get("command_sha256") == item["command_sha256"]
        and claim_value.get("argv") == item["argv"]
        and claim_value.get("effective_environment") == item["env"]
        and claim_value.get("input_binding") == item["input_binding"]
        and claim_value.get("popen_invocation_count_at_claim") == 0
        and claim_value.get("automatic_retry_count") == 0
        and claim_value.get("replacement_permitted") is False,
        f"PRIOR_CLAIM_CONTRACT:{item['item_id']}",
    )
    runtime = receipt.get("runtime")
    process_group = runtime.get("process_group") if isinstance(runtime, dict) else None
    require(
        isinstance(runtime, dict)
        and runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and isinstance(process_group, dict)
        and process_group.get("leader_reaped") is True
        and process_group.get("process_group_empty") is True
        and process_group.get("owned_descendants_empty") is True,
        f"PRIOR_RUNTIME_CONTRACT:{item['item_id']}",
    )
    process_log = receipt.get("process_log")
    require(isinstance(process_log, dict), f"PRIOR_PROCESS_LOG:{item['item_id']}")
    require(
        Path(str(process_log.get("path", ""))) == output / LOG_NAME
        and validate_identity_claim(process_log, f"prior:{item['item_id']}:log") == process_log,
        f"PRIOR_PROCESS_LOG_BINDING:{item['item_id']}",
    )
    artifact = receipt.get("artifact_contract")
    require(isinstance(artifact, dict), f"PRIOR_ARTIFACT_CONTRACT:{item['item_id']}")
    require(
        artifact.get("evidence_tree_integrity") is True
        and artifact.get("integrity_issues") == [],
        f"PRIOR_ARTIFACT_INTEGRITY:{item['item_id']}",
    )
    recorded_outputs = artifact.get("outputs")
    require(isinstance(recorded_outputs, dict), f"PRIOR_ARTIFACT_OUTPUTS:{item['item_id']}")
    recorded_files = {CLAIM_NAME, RECEIPT_NAME}
    recorded_files.add(LOG_NAME)
    for relative, recorded in recorded_outputs.items():
        require(
            isinstance(relative, str) and relative in item["expected_outputs"],
            f"PRIOR_OUTPUT_KEY:{item['item_id']}:{relative}",
        )
        expected_path = output / relative
        require(
            isinstance(recorded, dict)
            and Path(str(recorded.get("path", ""))) == expected_path
            and validate_identity_claim(recorded, f"prior:{item['item_id']}:{relative}") == recorded,
            f"PRIOR_OUTPUT_BINDING:{item['item_id']}:{relative}",
        )
        recorded_files.add(relative)
    boundary_manifests = {
        "network_namespace_manifest.json", "replay_only_guard_manifest.json",
    }
    require(
        boundary_manifests <= set(recorded_outputs),
        f"PRIOR_BOUNDARY_MANIFESTS:{item['item_id']}",
    )
    require(
        namespace_manifest_audit(
            output / "network_namespace_manifest.json", item
        )["status"] == "PASS",
        f"PRIOR_NAMESPACE_MANIFEST:{item['item_id']}",
    )
    require(
        replay_guard_manifest_audit(
            output / "replay_only_guard_manifest.json", item
        )["status"] == "PASS",
        f"PRIOR_REPLAY_GUARD_MANIFEST:{item['item_id']}",
    )
    current_artifact = artifact_audit(item)
    require(
        current_artifact.get("outputs") == recorded_outputs
        and current_artifact.get("evidence_tree_integrity") is True
        and current_artifact.get("integrity_issues") == [],
        f"PRIOR_ARTIFACT_REAUDIT:{item['item_id']}",
    )
    if receipt.get("status") == "PASS_BACKEND_REPLAY_ACCEPTED":
        require(
            current_artifact.get("status") == "PASS",
            f"PRIOR_ACCEPTED_RESULT_REAUDIT:{item['item_id']}",
        )
    evidence_tree = evidence_relative_tree(output)
    require(
        set(evidence_tree["files"]) == recorded_files,
        f"PRIOR_EVIDENCE_TREE_CHANGED:{item['item_id']}",
    )
    require(
        set(evidence_tree["directories"]) <= {"vins_output"},
        f"PRIOR_EVIDENCE_DIRECTORIES_CHANGED:{item['item_id']}",
    )
    require(workspace_ok(item), f"PRIOR_WORKSPACE_BINDING:{item['item_id']}")
    return receipt


def enforce_sequence(lock: Mapping[str, Any], lock_identity: Mapping[str, Any], item_id: str) -> None:
    require(lock.get("item_order") == list(ITEM_ORDER), "LOCK_ITEM_ORDER")
    index = ITEM_ORDER.index(item_id)
    for prior_id in ITEM_ORDER[:index]:
        prior_receipt(lock_identity, lock["items"][prior_id])
    for later_id in ITEM_ORDER[index + 1:]:
        later = lock["items"][later_id]
        output = Path(later["output_dir"])
        workspace = Path(later["workspace_link"])
        runtime = RUNTIME_ROOT / later_id
        require(not output.exists() and not output.is_symlink(), f"LATER_OUTPUT_PRESENT:{later_id}")
        require(not workspace.exists() and not workspace.is_symlink(), f"LATER_WORKSPACE_PRESENT:{later_id}")
        require(not runtime.exists() and not runtime.is_symlink(), f"LATER_RUNTIME_PRESENT:{later_id}")
    target = lock["items"][item_id]
    output = Path(target["output_dir"])
    workspace = Path(target["workspace_link"])
    runtime = RUNTIME_ROOT / item_id
    require(not output.exists() and not output.is_symlink(), f"TARGET_ALREADY_CONSUMED:{item_id}")
    require(not workspace.exists() and not workspace.is_symlink(), f"TARGET_WORKSPACE_PRESENT:{item_id}")
    require(not runtime.exists() and not runtime.is_symlink(), f"TARGET_RUNTIME_PRESENT:{item_id}")


def trajectory_audit(path: Path) -> dict[str, Any]:
    rows = 0
    first: Optional[int] = None
    last: Optional[int] = None
    previous: Optional[int] = None
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip().rstrip(",")
        if not line:
            continue
        fields = [field.strip() for field in line.split(",")]
        require(len(fields) == 11, f"VIO_FIELD_COUNT:{line_number}:{len(fields)}")
        require(re.fullmatch(r"[0-9]+", fields[0]) is not None,
                f"VIO_TIMESTAMP_NOT_INTEGER_NS:{line_number}")
        timestamp = int(fields[0])
        try:
            values = [float(field) for field in fields[1:]]
        except ValueError as error:
            raise BackendProtocolError(f"VIO_NONNUMERIC:{line_number}") from error
        require(all(math.isfinite(value) for value in values), f"VIO_NONFINITE:{line_number}")
        require(previous is None or timestamp > previous, f"VIO_TIMESTAMP_ORDER:{line_number}")
        quaternion_norm = math.sqrt(sum(value * value for value in values[3:7]))
        require(0.5 <= quaternion_norm <= 1.5, f"VIO_QUATERNION_NORM:{line_number}")
        first = timestamp if first is None else first
        last = timestamp
        previous = timestamp
        rows += 1
    require(rows > 0 and first is not None and last is not None, "VIO_EMPTY")
    return {
        "convention": "world_T_body",
        "rows": rows,
        "timestamp_unit": "nanoseconds",
        "first_timestamp_ns": first,
        "last_timestamp_ns": last,
        "duration_s": (last - first) / 1_000_000_000.0,
    }


def ape_usability_audit(
    path: Path, expected_history_duration_s: Optional[float] = None,
) -> dict[str, Any]:
    values: dict[str, float] = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        require(line.count("=") == 1, f"APE_KV_LAYOUT:{line_number}")
        key, raw_value = line.split("=", 1)
        require(key and key not in values, f"APE_KV_KEY:{line_number}:{key}")
        try:
            value = float(raw_value)
        except ValueError as error:
            raise BackendProtocolError(f"APE_KV_VALUE:{line_number}:{key}") from error
        require(math.isfinite(value), f"APE_KV_NONFINITE:{line_number}:{key}")
        values[key] = value
    required = {
        "matched", "rpe_pairs", "output_poses", "output_duration_s",
        "expected_duration_s", "output_coverage_ratio", "max_output_gap_s",
        "init_success", "log_linear_solver_failures", "log_failure_mentions",
        "log_restart_mentions",
    }
    require(required <= set(values), f"APE_KV_MISSING:{sorted(required - set(values))}")
    checks = {
        "init_success": values["init_success"] == 1,
        "minimum_matched_poses": values["matched"] >= 30,
        "minimum_output_poses": values["output_poses"] >= 30,
        "minimum_rpe_pairs": values["rpe_pairs"] >= 10,
        "minimum_output_duration_s": values["output_duration_s"] >= 10.0,
        "minimum_output_coverage_ratio": values["output_coverage_ratio"] >= 0.70,
        "maximum_output_gap_s": values["max_output_gap_s"] <= 0.50,
        "no_linear_solver_failures": values["log_linear_solver_failures"] == 0,
        "no_failure_mentions": values["log_failure_mentions"] == 0,
        "no_restart_mentions": values["log_restart_mentions"] == 0,
    }
    if expected_history_duration_s is not None:
        checks["expected_duration_matches_bound_history"] = (
            abs(values["expected_duration_s"] - expected_history_duration_s) <= 1.0
        )
        checks["minimum_bound_history_output_duration"] = (
            values["output_duration_s"] >= 0.70 * expected_history_duration_s
        )
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_codes": failures,
        "values": {key: values[key] for key in sorted(required)},
        "diagnostic_only_not_common_support_ranking": True,
    }


def namespace_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    value, manifest_identity = stable_json(path)
    checks = {
        "schema": value.get("schema_version") == "aqua-fe-a10-samehistory-backend-netns-v4",
        "status": value.get("status") == "PASS",
        "isolation_scope": value.get("isolation_scope") == "NETWORK_NAMESPACE_LOOPBACK_ONLY",
        "not_machine_exclusive": value.get("machine_exclusive_cpu_scheduling") is False,
        "user_namespace_root": value.get("uid_inside") == 0 and value.get("gid_inside") == 0,
        "host_network_namespace": value.get("host_network_namespace") == item["host_network_namespace"],
        "host_user_namespace": value.get("host_user_namespace") == item["host_user_namespace"],
        "fresh_network_namespace": (
            isinstance(value.get("self_network_namespace"), str)
            and re.fullmatch(r"net:\[[0-9]+\]", value["self_network_namespace"]) is not None
            and value.get("self_network_namespace") != value.get("host_network_namespace")
        ),
        "fresh_user_namespace": (
            isinstance(value.get("self_user_namespace"), str)
            and re.fullmatch(r"user:\[[0-9]+\]", value["self_user_namespace"]) is not None
            and value.get("self_user_namespace") != value.get("host_user_namespace")
        ),
        "loopback_only": value.get("interfaces") == ["lo"],
        "no_initial_listeners": value.get("initial_tcp_listeners") == [],
        "formal_bind": (
            value.get("formal_bind_address") == "127.0.0.1"
            and value.get("formal_bind_port") == FORMAL_PORT
        ),
        "inner_backend_argv": (
            value.get("backend_argv_sha256") == item["inner_backend_argv_sha256"]
        ),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_codes": failures,
        "identity": manifest_identity,
    }


def replay_guard_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    value, manifest_identity = stable_json(path)
    expected_inputs = {
        "ground_truth": (
            item["env"]["GT_TXT"], int(item["env"]["A08_GT_SIZE_BYTES"]),
            item["env"]["A08_GT_SHA256"], 6,
        ),
        "raw_bag": (
            item["env"]["RAW_BAG"], int(item["env"]["A08_RAW_BAG_SIZE_BYTES"]),
            item["env"]["A08_RAW_BAG_SHA256"], 7,
        ),
        "raw_archive": (
            item["env"]["RAW_TAR"], int(item["env"]["A08_RAW_TAR_SIZE_BYTES"]),
            item["env"]["A08_RAW_TAR_SHA256"], 8,
        ),
        "feature_bag": (
            item["env"]["FEATURE_BAG_OVERRIDE"],
            int(item["env"]["A08_FEATURE_BAG_SIZE_BYTES"]),
            item["env"]["A08_FEATURE_BAG_SHA256"], 9,
        ),
        "frontend_metrics": (
            item["env"]["A08_FRONTEND_METRICS"],
            int(item["env"]["A08_FRONTEND_METRICS_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_METRICS_SHA256"], 10,
        ),
        "camera_config": (
            item["env"]["A08_FRONTEND_CAMERA_CONFIG"],
            int(item["env"]["A08_FRONTEND_CAMERA_SIZE_BYTES"]),
            item["env"]["A08_FRONTEND_CAMERA_SHA256"], 11,
        ),
    }
    observed_inputs = value.get("bound_inputs")
    input_checks: dict[str, bool] = {}
    for label, expected in expected_inputs.items():
        row = observed_inputs.get(label) if isinstance(observed_inputs, dict) else None
        input_checks[label] = bool(
            isinstance(row, dict)
            and row.get("accepted_path") == expected[0]
            and row.get("size_bytes") == expected[1]
            and row.get("sha256") == expected[2]
            and row.get("sealed_fd") == expected[3]
            and row.get("sealed_path") == f"/proc/self/fd/{expected[3]}"
            and isinstance(row.get("device"), int)
            and isinstance(row.get("inode"), int)
        )
    checks = {
        "schema": value.get("schema_version") == "aqua-fe-a08-replay-only-fd-guard-v1",
        "status": value.get("status") == "PASS_BEFORE_DELEGATED_BACKEND",
        "item_id": value.get("item_id") == item["item_id"],
        "output_dir": value.get("output_dir") == item["output_dir"],
        "workspace_link": value.get("workspace_link") == item["workspace_link"],
        "delegated_shell": value.get("delegated_backend_shell") == str(BACKEND_SHELL),
        "history": value.get("history") == {
            "dataset": "aqualoc_archaeo", "sequence": 8,
            "start_source_index": 0, "end_source_index": 4660,
            "every_n": 2, "method": item["method"],
        },
        "policy": value.get("policy") == {
            "frontend_export_permitted": False,
            "raw_reconstruction_permitted": False,
            "accepted_frontend_paths_passed_as_delegated_data_arguments": False,
            "delegated_data_environment_values_are_inherited_fds": True,
            "all_delegated_data_paths_are_inherited_fds": True,
            "published_before_delegated_backend": True,
        },
        **{f"bound_input:{label}": passed for label, passed in input_checks.items()},
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {
        "status": "PASS" if not failures else "FAIL",
        "checks": checks,
        "failure_codes": failures,
        "identity": manifest_identity,
    }


def replay_manifest_audit(path: Path, item: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, str] = {}
    for line_number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line:
            continue
        require(line.count("=") == 1, f"REPLAY_MANIFEST_LAYOUT:{line_number}")
        key, value = line.split("=", 1)
        require(key and key not in values, f"REPLAY_MANIFEST_KEY:{line_number}:{key}")
        values[key] = value
    expected = {
        "play_bag": "/proc/self/fd/9",
        "raw_bag": "/proc/self/fd/7",
        "accepted_feature_bag": item["env"]["FEATURE_BAG_OVERRIDE"],
        "accepted_feature_bag_size_bytes": item["env"]["A08_FEATURE_BAG_SIZE_BYTES"],
        "accepted_feature_bag_sha256": item["env"]["A08_FEATURE_BAG_SHA256"],
        "sealed_play_bag": "/proc/self/fd/9",
        "strict_replay_only_fd_guard": "1",
        "run_dir": item["workspace_link"],
    }
    missing = sorted(set(expected) - set(values))
    conflicts = sorted(
        key for key, expected_value in expected.items()
        if key in values and values[key] != expected_value
    )
    return {
        "status": "PASS" if not missing and not conflicts else "FAIL",
        "missing_keys": missing,
        "conflicting_keys": conflicts,
        "explicit_lineage_conflict": bool(conflicts),
        "values": values,
    }


def evidence_relative_tree(output: Path) -> dict[str, list[str]]:
    output = output.absolute()
    require(output.is_dir() and not output.is_symlink(), f"EVIDENCE_OUTPUT_KIND:{output}")
    result: list[str] = []
    directory_result: list[str] = []
    for root_raw, directories, files in os.walk(output, topdown=True, followlinks=False):
        root = Path(root_raw)
        for name in directories:
            path = root / name
            require(not path.is_symlink() and path.is_dir(), f"EVIDENCE_DIRECTORY_KIND:{path}")
            directory_result.append(str(path.relative_to(output)))
        for name in files:
            path = root / name
            require(not path.is_symlink() and stat.S_ISREG(path.lstat().st_mode),
                    f"EVIDENCE_FILE_KIND:{path}")
            result.append(str(path.relative_to(output)))
    return {"files": sorted(result), "directories": sorted(directory_result)}


def evidence_relative_files(output: Path) -> list[str]:
    return evidence_relative_tree(output)["files"]


def artifact_audit(item: Mapping[str, Any]) -> dict[str, Any]:
    output = Path(item["output_dir"])
    outputs: dict[str, Any] = {}
    issues: list[str] = []
    integrity_issues: list[str] = []
    for relative in item["expected_outputs"]:
        path = output / relative
        try:
            outputs[relative] = identity(path)
        except (BackendProtocolError, OSError, ValueError) as error:
            issues.append(f"{relative}:{type(error).__name__}:{error}")
    for boundary_manifest in (
        "network_namespace_manifest.json", "replay_only_guard_manifest.json"
    ):
        if boundary_manifest not in outputs:
            integrity_issues.append(f"MISSING_BOUNDARY_MANIFEST:{boundary_manifest}")
    semantic: dict[str, Any] = {}
    try:
        semantic["supervisor_process_log"] = identity(output / LOG_NAME)
    except (BackendProtocolError, OSError, ValueError) as error:
        issues.append(f"{LOG_NAME}:{type(error).__name__}:{error}")
        integrity_issues.append("SUPERVISOR_PROCESS_LOG_CONTRACT")
    if "vins_output/vio.csv" in outputs:
        try:
            semantic["trajectory"] = trajectory_audit(output / "vins_output/vio.csv")
        except (BackendProtocolError, OSError, UnicodeError) as error:
            issues.append(f"trajectory:{type(error).__name__}:{error}")
    if "ape.txt" in outputs:
        try:
            history = item["input_binding"]["history_contract"]
            history_duration_s = (
                int(history["feature_last_ns"]) - int(history["feature_first_ns"])
            ) / 1_000_000_000.0
            ape_gate = ape_usability_audit(
                output / "ape.txt", expected_history_duration_s=history_duration_s
            )
            ape_gate["bound_history_duration_s"] = history_duration_s
            semantic["backend_usability"] = ape_gate
            if ape_gate["status"] != "PASS":
                issues.append("BACKEND_USABILITY_GATE:" + ",".join(ape_gate["failure_codes"]))
        except (BackendProtocolError, OSError, UnicodeError) as error:
            issues.append(f"backend_usability:{type(error).__name__}:{error}")
    if "network_namespace_manifest.json" in outputs:
        try:
            namespace_gate = namespace_manifest_audit(
                output / "network_namespace_manifest.json", item
            )
            semantic["network_namespace"] = namespace_gate
            if namespace_gate["status"] != "PASS":
                issues.append("NETWORK_NAMESPACE_GATE:" + ",".join(namespace_gate["failure_codes"]))
                integrity_issues.append("NETWORK_NAMESPACE_CONTRACT")
        except (BackendProtocolError, OSError, UnicodeError) as error:
            issues.append(f"network_namespace:{type(error).__name__}:{error}")
            integrity_issues.append("NETWORK_NAMESPACE_CONTRACT")
    if "replay_only_guard_manifest.json" in outputs:
        try:
            guard_gate = replay_guard_manifest_audit(
                output / "replay_only_guard_manifest.json", item
            )
            semantic["replay_only_guard"] = guard_gate
            if guard_gate["status"] != "PASS":
                issues.append("REPLAY_ONLY_GUARD_GATE:" + ",".join(guard_gate["failure_codes"]))
                integrity_issues.append("REPLAY_ONLY_GUARD_CONTRACT")
        except (BackendProtocolError, OSError, UnicodeError) as error:
            issues.append(f"replay_only_guard:{type(error).__name__}:{error}")
            integrity_issues.append("REPLAY_ONLY_GUARD_CONTRACT")
    config_path = output / "vins_aqualoc_archaeo_external.yaml"
    if "vins_aqualoc_archaeo_external.yaml" in outputs:
        try:
            text = config_path.read_text(encoding="utf-8")
            require(re.search(r"(?m)^multiple_thread:\s*0\s*$", text) is not None,
                    "GENERATED_CONFIG_MULTIPLE_THREAD")
            require(re.search(r"(?m)^estimate_td:\s*0\s*$", text) is not None,
                    "GENERATED_CONFIG_ESTIMATE_TD")
            require(re.search(r"(?m)^td:\s*-0\.053694112369382575\s*$", text) is not None,
                    "GENERATED_CONFIG_TD")
            required_lines = {
                'image0_topic: "/unused/image"',
                f'output_path: "{item["workspace_link"]}/vins_output"',
                "estimate_extrinsic: 0",
                "max_solver_time: 0.04",
                "max_num_iterations: 8",
                "loop_closure: 0",
            }
            config_lines = {line.strip() for line in text.splitlines()}
            require(required_lines <= config_lines, "GENERATED_CONFIG_FIXED_LINES")
            body_match = re.search(
                r"body_T_cam0:\s*!!opencv-matrix.*?data:\s*\[([^\]]+)\]",
                text,
                flags=re.DOTALL,
            )
            require(body_match is not None, "GENERATED_CONFIG_BODY_T_CAM0_BLOCK")
            body_values = [float(value.strip()) for value in body_match.group(1).split(",")]
            expected_body_values = [
                -0.99937221, -0.03437489, -0.00857581, -0.01928963,
                0.00901561, -0.01265975, -0.99987922, -0.17514254,
                0.03426217, -0.99932882, 0.01296171, -0.02679520,
                0.0, 0.0, 0.0, 1.0,
            ]
            require(body_values == expected_body_values, "GENERATED_CONFIG_BODY_T_CAM0_VALUES")
            semantic["generated_config"] = {
                "multiple_thread": 0, "estimate_td": 0,
                "td": -0.053694112369382575,
                "trajectory_convention": "world_T_body",
                "body_T_cam0_mode": "imu_cam",
            }
        except (BackendProtocolError, OSError, UnicodeError) as error:
            issues.append(f"generated_config:{type(error).__name__}:{error}")
            integrity_issues.append("GENERATED_VINS_CONFIG_CONTRACT")
    replay_path = output / "replay_manifest.txt"
    if "replay_manifest.txt" in outputs:
        try:
            replay_gate = replay_manifest_audit(replay_path, item)
            semantic["replay_manifest"] = replay_gate
            if replay_gate["status"] != "PASS":
                issues.append(
                    "REPLAY_MANIFEST_GATE:missing="
                    + ",".join(replay_gate["missing_keys"])
                    + ";conflicting=" + ",".join(replay_gate["conflicting_keys"])
                )
                if replay_gate["explicit_lineage_conflict"]:
                    integrity_issues.append("REPLAY_ONLY_MANIFEST_CONTRACT")
        except (BackendProtocolError, OSError, UnicodeError, ValueError) as error:
            issues.append(f"replay_manifest:{type(error).__name__}:{error}")
    metrics = outputs.get("frontend_metrics.csv")
    upstream_metrics = item["input_binding"]["frontend_metrics"]
    if metrics is not None and (
        metrics["size_bytes"], metrics["sha256"]
    ) != (upstream_metrics["size_bytes"], upstream_metrics["sha256"]):
        issues.append("FRONTEND_METRICS_COPY_MISMATCH")
        integrity_issues.append("FRONTEND_METRICS_BINDING")
    camera = outputs.get("aqualoc_archaeo08_pinhole.yaml")
    upstream_camera = item["input_binding"]["camera_config"]
    if camera is not None and (
        camera["size_bytes"], camera["sha256"]
    ) != (upstream_camera["size_bytes"], upstream_camera["sha256"]):
        issues.append("CAMERA_CONFIG_CONTENT_MISMATCH")
        integrity_issues.append("CAMERA_CONFIG_BINDING")
    tree_integrity = True
    try:
        evidence_tree = evidence_relative_tree(output)
        observed_files = set(evidence_tree["files"])
        allowed_files = set(item["expected_outputs"]) | {
            CLAIM_NAME, LOG_NAME, RECEIPT_NAME,
        }
        unexpected = sorted(observed_files - allowed_files)
        if unexpected:
            tree_integrity = False
            issues.append("UNEXPECTED_EVIDENCE_FILES:" + ",".join(unexpected))
            integrity_issues.append("EVIDENCE_TREE_CLOSURE")
        unexpected_directories = sorted(
            set(evidence_tree["directories"]) - {"vins_output"}
        )
        if unexpected_directories:
            tree_integrity = False
            issues.append(
                "UNEXPECTED_EVIDENCE_DIRECTORIES:" + ",".join(unexpected_directories)
            )
            integrity_issues.append("EVIDENCE_TREE_CLOSURE")
    except (BackendProtocolError, OSError, ValueError) as error:
        tree_integrity = False
        issues.append(f"EVIDENCE_TREE:{type(error).__name__}:{error}")
        integrity_issues.append("EVIDENCE_TREE_KIND")
    return {
        "status": "PASS" if not issues else "FAIL",
        "issues": issues,
        "outputs": outputs,
        "semantic_checks": semantic,
        "evidence_tree_integrity": tree_integrity,
        "integrity_issues": sorted(set(integrity_issues)),
    }


def workspace_ok(item: Mapping[str, Any]) -> bool:
    workspace = Path(item["workspace_link"])
    return workspace.is_symlink() and os.readlink(workspace) == item["output_dir"]


def integrity_passes(
    integrity_faults: Sequence[str], authority_post: Mapping[str, Any],
    claim_stable: bool, workspace_stable: bool,
    evidence_tree_integrity: bool, process_group: Mapping[str, Any],
) -> bool:
    return bool(
        not integrity_faults
        and authority_post.get("status") == "PASS"
        and claim_stable
        and workspace_stable
        and evidence_tree_integrity
        and process_group.get("leader_reaped") is True
        and process_group.get("process_group_empty") is True
        and process_group.get("owned_descendants_empty") is True
    )


def finalized_integrity_fault_latch(
    existing: Sequence[str], authority_post: Mapping[str, Any],
    claim_stable: bool, workspace_stable: bool,
    evidence_tree_integrity: bool, process_group: Mapping[str, Any],
    artifact_integrity_issues: Sequence[str], process_log_stable: bool,
) -> list[str]:
    faults = list(existing)

    def latch(code: str) -> None:
        if code not in faults:
            faults.append(code)

    if authority_post.get("status") != "PASS":
        latch("POST_AUTHORITY_FAILURE")
    if not claim_stable:
        latch("CLAIM_NOT_STABLE_AT_RECEIPT")
    if not workspace_stable:
        latch("WORKSPACE_NOT_STABLE_AT_RECEIPT")
    if not evidence_tree_integrity:
        latch("EVIDENCE_TREE_NOT_STABLE_AT_RECEIPT")
    if not process_log_stable:
        latch("SUPERVISOR_PROCESS_LOG_MISSING_OR_UNSTABLE")
    for issue in artifact_integrity_issues:
        latch(f"ARTIFACT_INTEGRITY:{issue}")
    if not (
        process_group.get("leader_reaped") is True
        and process_group.get("process_group_empty") is True
        and process_group.get("owned_descendants_empty") is True
    ):
        latch("OWNED_PROCESS_CLEANUP_INCOMPLETE")
    return faults


def execute_item(
    lock_path: Path, item_id: str, authorization_token: str,
) -> tuple[int, dict[str, Any]]:
    require(item_id in ITEM_ORDER, f"ITEM_ID:{item_id}")
    require(authorization_token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN")
    bindings = resolve_frontend_bindings()
    lock, lock_identity = verify_lock(lock_path, bindings)
    enforce_sequence(lock, lock_identity, item_id)
    item = lock["items"][item_id]
    require(item["env"].get("VINS_MULTIPLE_THREAD") == "0", "VINS_MULTIPLE_THREAD_POLICY")
    require(item["env"].get("PORT") == str(FORMAL_PORT), "FORMAL_PORT_POLICY")

    safety = safety_module()
    safety.enable_subreaper()
    output = Path(item["output_dir"])
    workspace = Path(item["workspace_link"])
    output.parent.mkdir(parents=True, exist_ok=True)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    claim_path = output / CLAIM_NAME
    receipt_path = output / RECEIPT_NAME
    log_path = output / LOG_NAME
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    runtime: dict[str, Any] = {
        "popen_invocation_count": 0, "child_started": False, "pid": None,
        "raw_return_code": None, "timed_out": False,
        "process_group": {
            "leader_reaped": True, "process_group_empty": True,
            "owned_descendants_empty": True,
        },
    }
    errors: list[str] = []
    integrity_faults: list[str] = []
    authority_post: dict[str, Any] = {"status": "NOT_RUN"}
    claim_identity: Optional[dict[str, Any]] = None
    artifact: dict[str, Any] = {"status": "FAIL", "issues": ["NOT_RUN"]}
    process: Optional[subprocess.Popen[bytes]] = None
    baseline_children: set[tuple[int, int]] = set()
    pgid: Optional[int] = None
    leader = (0, 0)

    claim = {
        "schema_version": "aqua-fe-a08-recovered-july-backend-process-start-claim-v1",
        "status": "CLAIMED_ALLOWANCE_CONSUMED_NO_RETRY_NO_REPLACEMENT",
        "item_id": item_id,
        "started_at_utc": started,
        "execution_lock": lock_identity,
        "command_sha256": item["command_sha256"],
        "argv": item["argv"],
        "effective_environment": item["env"],
        "input_binding": item["input_binding"],
        "popen_invocation_count_at_claim": 0,
        "automatic_retry_count": 0,
        "replacement_permitted": False,
    }

    with safety.interruption_handlers() as pending_signals:
        try:
            try:
                safety.atomic_publish(claim_path, claim, propagate_interruption_after_commit=False)
                claim_identity = identity(claim_path)
            except BaseException:
                integrity_faults.append("CLAIM_PUBLICATION_OR_IDENTITY_FAILED")
                raise
            try:
                os.symlink(item["output_dir"], workspace)
                require(workspace_ok(item), "WORKSPACE_LINK_AFTER_CLAIM")
            except BaseException:
                integrity_faults.append("WORKSPACE_BINDING_FAILED_AFTER_CLAIM")
                raise
            try:
                lock_again, identity_again = verify_lock(lock_path, resolve_frontend_bindings())
                require(lock_again == lock and identity_again == lock_identity,
                        "AUTHORITY_CHANGED_BEFORE_POPEN")
            except BaseException:
                integrity_faults.append("AUTHORITY_FAILED_BEFORE_POPEN")
                raise
            try:
                require(identity(claim_path) == claim_identity, "CLAIM_CHANGED_BEFORE_POPEN")
                require(workspace_ok(item), "WORKSPACE_CHANGED_BEFORE_POPEN")
            except BaseException:
                integrity_faults.append("CLAIM_OR_WORKSPACE_CHANGED_BEFORE_POPEN")
                raise
            if pending_signals:
                raise BackendProtocolError(f"INTERRUPTED_BEFORE_POPEN:{pending_signals}")
            with log_path.open("xb") as log_stream:
                with safety.blocked_signals():
                    baseline_children = set(safety.direct_child_identities(os.getpid()))
                    runtime["popen_invocation_count"] = 1
                    process = subprocess.Popen(
                        list(item["argv"]), cwd=item["cwd"], env=dict(item["env"]),
                        stdout=log_stream, stderr=subprocess.STDOUT,
                        start_new_session=True, close_fds=True,
                    )
                    runtime.update({"child_started": True, "pid": process.pid})
                    pgid = process.pid
                    observed_leader = safety.process_identity(process.pid)
                    leader = observed_leader if observed_leader is not None else (process.pid, -1)
                    runtime["process_group"] = {
                        "pgid": pgid, "leader_identity": {
                            "pid": leader[0], "start_ticks": leader[1],
                        },
                        "leader_reaped": False, "process_group_empty": False,
                        "owned_descendants_empty": False,
                    }
                deadline = time.monotonic() + int(item["timeout_seconds"])
                while True:
                    if pending_signals:
                        errors.append(f"TERMINATION_SIGNALS:{pending_signals}")
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        runtime["timed_out"] = True
                        break
                    try:
                        runtime["raw_return_code"] = process.wait(timeout=min(0.25, remaining))
                        break
                    except subprocess.TimeoutExpired:
                        continue
        except BaseException as error:
            errors.append(f"{type(error).__name__}:{error}")
        finally:
            if process is not None and pgid is not None:
                try:
                    with safety.blocked_signals():
                        group = safety.drain_owned_processes(
                            process, pgid, leader, baseline_children,
                            normal_exit=bool(
                                runtime.get("raw_return_code") == 0
                                and runtime.get("timed_out") is False and not errors
                            ),
                        )
                    runtime["process_group"] = group
                    runtime["raw_return_code"] = process.returncode
                except BaseException as error:
                    errors.append(f"PROCESS_CLEANUP:{type(error).__name__}:{error}")
            try:
                post_lock, post_identity = verify_lock(lock_path, resolve_frontend_bindings())
                authority_post = {
                    "status": "PASS" if post_lock == lock and post_identity == lock_identity else "FAIL",
                    "lock": post_identity,
                }
            except BaseException as error:
                authority_post = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
            try:
                artifact = artifact_audit(item)
            except BaseException as error:
                artifact = {"status": "FAIL", "issues": [f"{type(error).__name__}:{error}"]}

        group = runtime.get("process_group", {})
        claim_stable = False
        try:
            claim_stable = claim_identity is not None and identity(claim_path) == claim_identity
        except BaseException:
            claim_stable = False
        try:
            workspace_stable = workspace_ok(item)
        except BaseException:
            workspace_stable = False
        process_log_identity: Optional[dict[str, Any]] = None
        try:
            process_log_identity = identity(log_path)
        except BaseException:
            process_log_identity = None
        integrity_faults = finalized_integrity_fault_latch(
            integrity_faults,
            authority_post,
            claim_stable,
            workspace_stable,
            artifact.get("evidence_tree_integrity") is True,
            group,
            artifact.get("integrity_issues", []),
            process_log_identity is not None,
        )
        integrity_ok = integrity_passes(
            integrity_faults,
            authority_post,
            claim_stable,
            workspace_stable,
            artifact.get("evidence_tree_integrity") is True,
            group,
        )
        if artifact.get("integrity_issues"):
            integrity_ok = False
        result_ok = bool(
            integrity_ok
            and runtime.get("popen_invocation_count") == 1
            and runtime.get("raw_return_code") == 0
            and runtime.get("timed_out") is False
            and not errors
            and artifact.get("status") == "PASS"
        )
        receipt = {
            "schema_version": RECEIPT_SCHEMA,
            "status": "PASS_BACKEND_REPLAY_ACCEPTED" if result_ok else "FAILED_BACKEND_REPLAY_NO_REPLACEMENT",
            "item_id": item_id,
            "arm": item["arm"],
            "repeat_index": item["repeat_index"],
            "started_at_utc": started,
            "ended_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "launch_allowance_consumed": True,
            "retry_count": 0,
            "replacement_permitted": False,
            "later_predeclared_items_may_continue_if_integrity_passes": True,
            "execution_lock": lock_identity,
            "claim": claim_identity,
            "process_log": process_log_identity,
            "runtime": runtime,
            "supervisor_errors": errors,
            "integrity_fault_latch": integrity_faults,
            "artifact_contract": artifact,
            "execution_integrity": {
                "status": "PASS" if integrity_ok else "FAIL",
                "irreversible_fault_latch_clear": not integrity_faults,
                "authority_post": authority_post,
                "claim_stable": claim_stable,
                "workspace_binding_stable": workspace_stable,
                "owned_processes_drained": bool(
                    group.get("leader_reaped") is True
                    and group.get("process_group_empty") is True
                    and group.get("owned_descendants_empty") is True
                ),
                "artifact_integrity_issues": artifact.get("integrity_issues", []),
            },
            "trajectory_convention": "world_T_body",
            "diagnostic_ape_is_not_common_support_ranking": True,
        }
        safety.atomic_publish(receipt_path, receipt, propagate_interruption_after_commit=False)
    return (0 if receipt["status"] == "PASS_BACKEND_REPLAY_ACCEPTED" else 3), receipt


def build_lock(lock_path: Path, authorization_token: str) -> dict[str, Any]:
    require(authorization_token == BUILD_LOCK_TOKEN, "BUILD_LOCK_AUTHORIZATION_TOKEN")
    require(not lock_path.exists() and not lock_path.is_symlink(), "LOCK_ALREADY_EXISTS")
    bindings = resolve_frontend_bindings()
    require_campaign_unstarted()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = expected_lock_from_current_authority(bindings, created)
    safety = safety_module()
    safety.atomic_publish(lock_path, payload, propagate_interruption_after_commit=True)
    return {"status": "FINAL_EXECUTION_LOCK_PUBLISHED", "lock": identity(lock_path)}


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("preflight")
    commands.add_parser("audit")
    build = commands.add_parser("build-lock")
    build.add_argument("--authorization-token", required=True)
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    run.add_argument("--authorization-token", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    lock_path = args.lock.absolute()
    if args.command == "preflight":
        result = preflight_readonly(lock_path)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"].startswith("PASS_") or result["status"].startswith("READY_") else 2
    if args.command == "audit":
        print(json.dumps(audit_readonly(lock_path), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    try:
        if args.command == "build-lock":
            result = build_lock(lock_path, args.authorization_token)
            code = 0
        else:
            code, result = execute_item(lock_path, args.item_id, args.authorization_token)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return code
    except (OSError, ValueError, RuntimeError) as error:
        print(f"A08_BACKEND_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
