#!/usr/bin/env python3
"""Fail-closed one-shot supervisor for the frozen A10 v4 backend recovery.

Only the repository's default lock is accepted. Mutating actions share one
/mnt-backed flock. A durable claim precedes Popen, and every catchable failure
after a claim is converted to a terminal receipt after process-group cleanup.
SIGKILL, host loss, and permanent storage failure remain unrecoverable.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import ctypes
from datetime import datetime
import errno
import fcntl
import hashlib
import ipaddress
import io
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import time
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).absolute().parents[1]
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery")
V3_EXP_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery"
)
DEFAULT_LOCK = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v4_backend_recovery_execution_lock.json"
GLOBAL_FLOCK = EXP_ROOT / ".supervisor.flock"
CLAIM_NAME = "process_start_claim.json"
RECEIPT_NAME = "formal_run_receipt_v4.json"
LOG_NAME = "supervisor_process.log"
SCHEMA = "aqua-fe-a10-samehistory-finalonline-supervisor-v4"
LOCK_SCHEMA = "aqua-fe-a10-samehistory-finalonline-v4-execution-lock-v1"

ITEM_ORDER = (
    "vanilla_origin_native_image_context",
    "klt_external_feature_context",
    "aquafe_external_feature_context",
)
KINDS = {
    "vanilla_origin_native_image_context": "backend_replay",
    "klt_external_feature_context": "backend_replay",
    "aquafe_external_feature_context": "backend_replay",
}
ISOLATION_POLICIES = {
    item_id: "loopback_only_network_namespace" for item_id in ITEM_ORDER
}
DEPENDENCIES = {
    item_id: () for item_id in ITEM_ORDER
}
BACKENDS = frozenset(ITEM_ORDER)
V3_PENDING_BACKEND_GUARDS = {
    "external_klt_finalonline_backbone": {
        "output_dir": V3_EXP_ROOT / "backends/external_klt_finalonline_backbone",
        "claim_path": V3_EXP_ROOT / (
            "backends/external_klt_finalonline_backbone/process_start_claim.json"
        ),
        "receipt_path": V3_EXP_ROOT / (
            "backends/external_klt_finalonline_backbone/formal_run_receipt_v3.json"
        ),
    },
    "aquafe_finalonline_xfeat_lineage": {
        "output_dir": V3_EXP_ROOT / "backends/aquafe_finalonline_xfeat_lineage",
        "claim_path": V3_EXP_ROOT / (
            "backends/aquafe_finalonline_xfeat_lineage/process_start_claim.json"
        ),
        "receipt_path": V3_EXP_ROOT / (
            "backends/aquafe_finalonline_xfeat_lineage/formal_run_receipt_v3.json"
        ),
    },
}
V3_PENDING_REQUIRED_ABSENCE_PHASES = (
    "lock_build",
    "lock_verification",
    "before_claim",
    "after_claim_before_popen",
    "postflight",
)
CATKIN_MARKERS = {
    "ros_catkin_marker": Path("/opt/ros/noetic/.catkin"),
    "vins_catkin_marker": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/.catkin"),
    "dave_catkin_marker": Path("/home/ma/dave_ws/devel/.catkin"),
    "uuv_catkin_marker": Path("/home/ma/uuv_ws/devel/.catkin"),
}
ROS_PROFILE_DIR = Path("/opt/ros/noetic/etc/catkin/profile.d")
ROS_HOOK_NAMES = (
    "05.catkin_make.bash",
    "05.catkin_make_isolated.bash",
    "1.ros_distro.sh",
    "1.ros_etc_dir.sh",
    "1.ros_package_path.sh",
    "1.ros_python_version.sh",
    "1.ros_version.sh",
    "10.rosbuild.sh",
    "10.roslaunch.sh",
    "15.rosbash.bash",
    "15.rosbash.fish",
    "15.rosbash.tcsh",
    "15.rosbash.zsh",
    "20.transform.bash",
    "99.roslisp.sh",
)
ABSENT_WORKSPACE_PROFILE_DIRS = (
    Path("/home/ma/SLAM/VINS-Fusion-origin/devel/etc/catkin/profile.d"),
    Path("/home/ma/dave_ws/devel/etc/catkin/profile.d"),
    Path("/home/ma/uuv_ws/devel/etc/catkin/profile.d"),
)
PYTHON3_SYMLINK = Path("/usr/bin/python3")
PYTHON3_SYMLINK_TARGET = "python3.8"
EXPECTED_EXTERNAL_INPUT_BINDINGS = {
    "vanilla_origin_native_image_context": {
        "raw_bag": {
            "identity_key": "raw_bag",
            "source_receipt_identity_key": "raw_audit",
            "source_item_id": "v1_raw_audit",
        },
    },
    "klt_external_feature_context": {
        "feature_bag": {
            "identity_key": "v3_klt_features_bag",
            "source_receipt_identity_key": "v3_klt_receipt",
            "source_item_id": "klt_input_adoption",
        },
        "frontend_metrics": {
            "identity_key": "v3_klt_frontend_metrics",
            "source_receipt_identity_key": "v3_klt_receipt",
            "source_item_id": "klt_input_adoption",
        },
    },
    "aquafe_external_feature_context": {
        "feature_bag": {
            "identity_key": "v3_aquafe_full_merged_bag",
            "source_receipt_identity_key": "v3_aquafe_receipt",
            "source_item_id": "aquafe_build",
        },
    },
}
OUTPUT_DIRS = {
    "vanilla_origin_native_image_context": EXP_ROOT / "backends/vanilla_origin_native_image_context",
    "klt_external_feature_context": EXP_ROOT / "backends/klt_external_feature_context",
    "aquafe_external_feature_context": EXP_ROOT / "backends/aquafe_external_feature_context",
}
WORKSPACE_LINKS = {
    "vanilla_origin_native_image_context": ROOT / "logs/aqualoc_archaeo_vins/origin_klt_every1_systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_score2400_2800_vanilla_origin",
    "klt_external_feature_context": ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_score2400_2800_external_klt",
    "aquafe_external_feature_context": ROOT / "logs/aqualoc_archaeo_vins/external_hybrid_xfeat_every2_systemfair_a10_finalonline_v4_backend_recovery_feed0000_2800_score2400_2800_aquafe_finalonline_xfeat_lineage",
}
WORKSPACE_LOGS_LINK = ROOT / "logs"
WORKSPACE_REAL_LOGS_ROOT = Path("/mnt/data/AQUA-FE_WS/logs")
WORKSPACE_LOGICAL_LINK_PARENT = WORKSPACE_LOGS_LINK / "aqualoc_archaeo_vins"
WORKSPACE_REAL_LINK_PARENT = WORKSPACE_REAL_LOGS_ROOT / "aqualoc_archaeo_vins"
FORBIDDEN_WORKSPACE = "/home/ma/SLAM/VINS-Fusion_3-15-WS"
EXPECTED_VINS_ENV = {
    "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
    "VINS_NODE_BIN": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
    "RUN_VINS": "1",
    "WAIT_FOR_VINS_SUBSCRIBERS": "1",
    "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
    "VINS_MULTIPLE_THREAD": "1",
    "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
    "VINS_TD": "-0.053694112369382575",
    "VINS_ESTIMATE_TD": "0",
    "VINS_MAX_SOLVER_TIME": "0.04",
    "VINS_MAX_NUM_ITERATIONS": "8",
    "PLAY_RATE": "1.0",
    "ROSBAG_PLAY_DELAY": "3",
    "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
    "POST_PLAY_SLEEP": "8",
}
POINTCLOUD_CHANNELS = (
    "id", "camera_id", "p_u", "p_v", "velocity_x", "velocity_y", "gx", "gy", "gz",
    "quality", "sigma", "source_code", "is_learned",
)
# Set only after the final item/policy contract is stable.  The digest excludes
# file identities, so pinning this value does not create a supervisor/lock hash
# cycle.
EXPECTED_CONTRACT_SHA256 = "02259ba807aaec0d3f1c65d2d729a6f93e0468915b5e5e0248ec787de25b6b8a"
CHECK_TYPES = frozenset(
    {
        "rosbag_topic", "rosbag_timeline_equal", "rosbag_feature_extension",
        "csv_rows", "file_sha256", "text_contains", "network_namespace_manifest",
        "replay_manifest", "ape_kv",
        "rosbag_topic_equal",
        "vins_trajectory",
    }
)
ROS_NAMES = frozenset(
    {
        "roscore", "rosmaster", "roslaunch", "rosout", "vins_node",
        "feature_tracker", "loop_fusion_node", "pose_graph", "hfnet_slam",
        "hfnet_slam_node", "mono_tum",
    }
)
FORMAL_ROS_PORTS = frozenset({11981})
OFFLINE_AMBIENT_ROS_ROLES = frozenset(
    {"roscore", "rosmaster", "rosout", "vins_node", "rosbag_play"}
)
LEARNED_PROCESS_MARKERS = (
    "hfnet_slam", "mono_tum", "xfeat_seed_sidecar", "lightglue",
    "superpoint", "loftr", "droid_slam", "droid-slam", "dpvo",
)
TERM_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class ContractError(RuntimeError):
    pass


class SupervisorInterruption(BaseException):
    def __init__(self, signum: int):
        super().__init__(f"signal={signum}:{signal.Signals(signum).name}")
        self.signum = signum


def now_local() -> str:
    return datetime.now().astimezone().isoformat()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def compact_json_sha256(value: Any) -> str:
    data = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()
    return hashlib.sha256(data).hexdigest()


def current_namespace_identity(kind: str) -> str:
    if kind not in {"net", "user"}:
        raise ContractError(f"NAMESPACE_KIND_INVALID:{kind}")
    try:
        value = os.readlink(f"/proc/self/ns/{kind}")
    except OSError as error:
        raise ContractError(f"NAMESPACE_READLINK_FAILED:{kind}:{error.errno}") from error
    if re.fullmatch(rf"{kind}:\[[0-9]+\]", value) is None:
        raise ContractError(f"NAMESPACE_IDENTITY_INVALID:{kind}:{value}")
    return value


def finite_float(value: Any, context: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ContractError(f"NONNUMERIC:{context}:{value!r}") from error
    if not math.isfinite(parsed):
        raise ContractError(f"NONFINITE:{context}:{value!r}")
    return parsed


def exact_integer(value: Any, context: str, *, tolerance: float = 1e-6) -> int:
    parsed = finite_float(value, context)
    rounded = round(parsed)
    if abs(parsed - rounded) > tolerance:
        raise ContractError(f"NONINTEGRAL:{context}:{value!r}")
    return int(rounded)


def safe_text(value: Any, context: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise ContractError(f"TEXT_INVALID:{context}")
    if "\0" in value:
        raise ContractError(f"NUL_FORBIDDEN:{context}")
    if FORBIDDEN_WORKSPACE in value:
        raise ContractError(f"FORBIDDEN_WORKSPACE_REFERENCE:{context}")
    return value


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def parse_json(data: bytes, path: Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise ContractError(f"NONFINITE_JSON_CONSTANT:{path}:{value}")

    try:
        value = json.loads(
            data.decode(), object_pairs_hook=unique_object, parse_constant=reject_constant
        )
    except ContractError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"UNREADABLE_JSON:{path}:{type(error).__name__}") from error
    if not isinstance(value, dict):
        raise ContractError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value


def absolute(raw: str | Path) -> Path:
    path = Path(raw)
    return (path if path.is_absolute() else ROOT / path).absolute()


def no_symlink_components(path: Path, *, missing_leaf_ok: bool = False) -> None:
    path = path.absolute()
    current = Path(path.parts[0])
    for index, part in enumerate(path.parts[1:], start=1):
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if missing_leaf_ok and index == len(path.parts) - 1:
                return
            raise ContractError(f"MISSING_PATH_COMPONENT:{current}")
        if stat.S_ISLNK(mode):
            raise ContractError(f"SYMLINK_PATH_COMPONENT:{current}")


def read_all(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            return b"".join(chunks)
        chunks.append(block)


def snapshot(path: Path, *, with_data: bool = False) -> tuple[dict[str, Any], bytes | None]:
    path = path.absolute()
    no_symlink_components(path)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ContractError(f"OPEN_REGULAR_FAILED:{path}:{error.errno}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ContractError(f"NOT_REGULAR_FILE:{path}")
        data = read_all(descriptor)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, key) != getattr(after, key) for key in fields):
            raise ContractError(f"FILE_CHANGED_WHILE_HASHING:{path}")
        result = {
            "path": str(path), "size_bytes": before.st_size,
            "sha256": hashlib.sha256(data).hexdigest(), "device": before.st_dev,
            "inode": before.st_ino, "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
        }
        return result, data if with_data else None
    finally:
        os.close(descriptor)


def public(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("path", "size_bytes", "sha256")}


def same_snapshot(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    fields = ("path", "size_bytes", "sha256", "device", "inode", "mtime_ns", "ctime_ns")
    return all(left.get(key) == right.get(key) for key in fields)


def verify_identity(name: str, claim: Mapping[str, Any]) -> dict[str, Any]:
    if set(claim) != {"path", "size_bytes", "sha256"}:
        raise ContractError(f"IDENTITY_FIELDS_INVALID:{name}")
    path_text, size, digest = claim.get("path"), claim.get("size_bytes"), claim.get("sha256")
    if not isinstance(path_text, str) or not path_text:
        raise ContractError(f"IDENTITY_PATH_INVALID:{name}")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ContractError(f"IDENTITY_SIZE_INVALID:{name}")
    if not isinstance(digest, str) or len(digest) != 64 or any(
        char not in "0123456789abcdef" for char in digest
    ):
        raise ContractError(f"IDENTITY_HASH_INVALID:{name}")
    actual, _ = snapshot(absolute(path_text))
    if actual["size_bytes"] != size or actual["sha256"] != digest:
        raise ContractError(f"IDENTITY_MISMATCH:{name}:{path_text}")
    return actual


def contained(path: Path, root: Path) -> bool:
    try:
        path.absolute().relative_to(root.absolute())
        return True
    except ValueError:
        return False


def output_dir(item: Mapping[str, Any]) -> Path:
    raw = item.get("output_dir")
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        raise ContractError("ITEM_OUTPUT_DIR_INVALID")
    path = Path(raw).absolute()
    if path == EXP_ROOT or not contained(path, EXP_ROOT):
        raise ContractError(f"ITEM_OUTPUT_DIR_ESCAPE:{path}")
    return path


def output_paths(item: Mapping[str, Any]) -> list[Path]:
    base = output_dir(item)
    values = item.get("expected_outputs")
    if not isinstance(values, list) or not values:
        raise ContractError("EXPECTED_OUTPUTS_EMPTY")
    result: list[Path] = []
    seen: set[str] = set()
    for raw in values:
        if not isinstance(raw, str) or not raw:
            raise ContractError("EXPECTED_OUTPUT_INVALID")
        rel = Path(raw)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ContractError(f"EXPECTED_OUTPUT_UNSAFE:{raw}")
        if str(rel) in seen:
            raise ContractError(f"EXPECTED_OUTPUT_DUPLICATE:{raw}")
        seen.add(str(rel))
        path = (base / rel).absolute()
        if not contained(path, base):
            raise ContractError(f"EXPECTED_OUTPUT_ESCAPE:{raw}")
        result.append(path)
    return result


def command(item: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    argv, environment = item.get("argv"), item.get("env", {})
    if not isinstance(argv, list) or not argv:
        raise ContractError("ITEM_ARGV_INVALID")
    argv = [safe_text(value, f"argv[{index}]") for index, value in enumerate(argv)]
    if not Path(argv[0]).is_absolute():
        raise ContractError("ARGV0_NOT_ABSOLUTE")
    if not isinstance(environment, dict):
        raise ContractError("ITEM_ENV_INVALID")
    checked_environment: dict[str, str] = {}
    for raw_key, raw_value in environment.items():
        key = safe_text(raw_key, "env-key")
        if "=" in key:
            raise ContractError(f"ITEM_ENV_KEY_EQUALS:{key!r}")
        checked_environment[key] = safe_text(raw_value, f"env[{key}]", allow_empty=True)
    text = " ".join(argv).lower()
    if "hfnet" in text or "mono_tum" in text:
        raise ContractError("HFNET_RERUN_FORBIDDEN")
    contract = item.get("command_contract")
    if not isinstance(contract, dict) or set(contract) != {"cwd", "argv_sha256", "env_sha256"}:
        raise ContractError("COMMAND_CONTRACT_FIELDS_INVALID")
    if contract.get("cwd") != str(ROOT):
        raise ContractError("COMMAND_CONTRACT_CWD_INVALID")
    if contract.get("argv_sha256") != compact_json_sha256(argv):
        raise ContractError("COMMAND_ARGV_DIGEST_MISMATCH")
    if contract.get("env_sha256") != compact_json_sha256(checked_environment):
        raise ContractError("COMMAND_ENV_DIGEST_MISMATCH")
    return list(argv), checked_environment


def string_list(value: Any, context: str, *, nonempty: bool = True) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise ContractError(f"STRING_LIST_INVALID:{context}")
    result = [safe_text(item, f"{context}[{index}]") for index, item in enumerate(value)]
    if len(set(result)) != len(result):
        raise ContractError(f"STRING_LIST_DUPLICATE:{context}")
    return result


def nonnegative_integer(value: Any, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContractError(f"NONNEGATIVE_INTEGER_INVALID:{context}")
    return value


def validate_pointcloud_declaration(contract: Any, context: str) -> None:
    if not isinstance(contract, dict):
        raise ContractError(f"POINTCLOUD_CONTRACT_NOT_OBJECT:{context}")
    allowed = {
        "channel_names", "exact_points", "allowed_source_codes", "all_is_learned",
        "maximum_id_exclusive", "minimum_id_inclusive", "quality_min", "quality_max",
        "sigma_from_quality", "exact_topic_counts",
        "ros_message_type", "ros_md5", "header_frame_id", "header_seq",
        "recorded_stamp_equals_header_stamp", "minimum_points", "maximum_points",
        "all_point_and_channel_values_finite", "integer_valued_channels",
        "integer_tolerance", "unique_ids_within_message", "constant_channels",
        "point_z_exact", "half_open_channel_ranges", "source_contract",
    }
    if set(contract) - allowed or "channel_names" not in contract:
        raise ContractError(f"POINTCLOUD_CONTRACT_FIELDS:{context}")
    names = string_list(contract["channel_names"], f"{context}.channel_names")
    if tuple(names) != POINTCLOUD_CHANNELS:
        raise ContractError(f"POINTCLOUD_CHANNEL_SCHEMA:{context}")
    required_fixed = {
        "ros_message_type", "ros_md5", "header_frame_id", "header_seq",
        "recorded_stamp_equals_header_stamp", "all_point_and_channel_values_finite",
        "integer_valued_channels", "integer_tolerance", "unique_ids_within_message",
        "constant_channels", "point_z_exact", "half_open_channel_ranges",
        "quality_min", "quality_max", "sigma_from_quality", "exact_topic_counts",
    }
    if not required_fixed <= set(contract):
        raise ContractError(f"POINTCLOUD_REQUIRED_FIELDS:{context}:{sorted(required_fixed-set(contract))}")
    if ("exact_points" in contract) == (
        "minimum_points" in contract or "maximum_points" in contract
    ):
        raise ContractError(f"POINTCLOUD_CARDINALITY_DECLARATION:{context}")
    if ("minimum_points" in contract) != ("maximum_points" in contract):
        raise ContractError(f"POINTCLOUD_CARDINALITY_RANGE_INCOMPLETE:{context}")
    for key in (
        "exact_points", "minimum_points", "maximum_points", "maximum_id_exclusive",
        "minimum_id_inclusive", "header_seq",
    ):
        if key in contract:
            nonnegative_integer(contract[key], f"{context}.{key}")
    if "minimum_points" in contract and contract["minimum_points"] > contract["maximum_points"]:
        raise ContractError(f"POINTCLOUD_CARDINALITY_RANGE_INVALID:{context}")
    safe_text(contract["ros_message_type"], f"{context}.ros_message_type")
    md5 = safe_text(contract["ros_md5"], f"{context}.ros_md5")
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise ContractError(f"POINTCLOUD_MD5_INVALID:{context}")
    safe_text(contract["header_frame_id"], f"{context}.header_frame_id", allow_empty=True)
    for flag in (
        "recorded_stamp_equals_header_stamp", "all_point_and_channel_values_finite",
        "unique_ids_within_message", "sigma_from_quality",
    ):
        if contract.get(flag) is not True:
            raise ContractError(f"POINTCLOUD_REQUIRED_TRUE:{context}:{flag}")
    integer_channels = string_list(
        contract["integer_valued_channels"], f"{context}.integer_valued_channels"
    )
    if integer_channels != ["id", "camera_id", "source_code", "is_learned"]:
        raise ContractError(f"POINTCLOUD_INTEGER_CHANNELS_INVALID:{context}")
    if finite_float(contract["integer_tolerance"], f"{context}.integer_tolerance") != 1e-6:
        raise ContractError(f"POINTCLOUD_INTEGER_TOLERANCE_INVALID:{context}")
    constants = contract["constant_channels"]
    if not isinstance(constants, dict) or not constants or not set(constants) <= set(names):
        raise ContractError(f"POINTCLOUD_CONSTANT_CHANNELS_INVALID:{context}")
    for key, value in constants.items():
        finite_float(value, f"{context}.constant_channels.{key}")
    finite_float(contract["point_z_exact"], f"{context}.point_z_exact")
    ranges = contract["half_open_channel_ranges"]
    if not isinstance(ranges, dict) or not ranges or not set(ranges) <= set(names):
        raise ContractError(f"POINTCLOUD_RANGES_INVALID:{context}")
    for key, interval in ranges.items():
        if not isinstance(interval, list) or len(interval) != 2:
            raise ContractError(f"POINTCLOUD_RANGE_SHAPE:{context}:{key}")
        low = finite_float(interval[0], f"{context}.{key}.low")
        high = finite_float(interval[1], f"{context}.{key}.high")
        if not low < high:
            raise ContractError(f"POINTCLOUD_RANGE_ORDER:{context}:{key}")
    if "allowed_source_codes" in contract:
        sources = contract["allowed_source_codes"]
        if not isinstance(sources, list) or not sources:
            raise ContractError(f"POINTCLOUD_SOURCE_CODES_INVALID:{context}")
        parsed = [nonnegative_integer(value, f"{context}.allowed_source_codes") for value in sources]
        if len(set(parsed)) != len(parsed):
            raise ContractError(f"POINTCLOUD_SOURCE_CODES_DUPLICATE:{context}")
    if "all_is_learned" in contract and contract["all_is_learned"] not in {0, 1}:
        raise ContractError(f"POINTCLOUD_LEARNED_FLAG_INVALID:{context}")
    source_contract = contract.get("source_contract")
    if not isinstance(source_contract, dict) or not source_contract:
        raise ContractError(f"POINTCLOUD_SOURCE_CONTRACT_MISSING:{context}")
    for raw_source, specification in source_contract.items():
        if not re.fullmatch(r"[0-9]+", str(raw_source)) or not isinstance(specification, dict):
            raise ContractError(f"POINTCLOUD_SOURCE_CONTRACT_INVALID:{context}:{raw_source}")
        if set(specification) not in (
            {"is_learned", "id_min_inclusive"},
            {"is_learned", "id_min_inclusive", "id_max_exclusive"},
        ):
            raise ContractError(f"POINTCLOUD_SOURCE_CONTRACT_FIELDS:{context}:{raw_source}")
        if specification["is_learned"] not in {0, 1}:
            raise ContractError(f"POINTCLOUD_SOURCE_LEARNED_INVALID:{context}:{raw_source}")
        minimum = nonnegative_integer(
            specification["id_min_inclusive"], f"{context}.source.{raw_source}.min"
        )
        if "id_max_exclusive" in specification:
            maximum = nonnegative_integer(
                specification["id_max_exclusive"], f"{context}.source.{raw_source}.max"
            )
            if maximum <= minimum:
                raise ContractError(f"POINTCLOUD_SOURCE_ID_RANGE:{context}:{raw_source}")
    if "allowed_source_codes" in contract and set(map(str, contract["allowed_source_codes"])) != set(source_contract):
        raise ContractError(f"POINTCLOUD_SOURCE_CONTRACT_SET:{context}")
    for key in ("quality_min", "quality_max"):
        if key in contract:
            finite_float(contract[key], f"{context}.{key}")
    if "quality_min" in contract and "quality_max" in contract:
        if float(contract["quality_min"]) > float(contract["quality_max"]):
            raise ContractError(f"POINTCLOUD_QUALITY_RANGE_INVALID:{context}")
    if "sigma_from_quality" in contract and contract["sigma_from_quality"] is not True:
        raise ContractError(f"POINTCLOUD_SIGMA_FLAG_INVALID:{context}")
    if "exact_topic_counts" in contract:
        counts = contract["exact_topic_counts"]
        if not isinstance(counts, dict) or not counts:
            raise ContractError(f"EXACT_TOPIC_COUNTS_INVALID:{context}")
        for topic, count in counts.items():
            if not safe_text(topic, f"{context}.topic").startswith("/"):
                raise ContractError(f"TOPIC_NAME_INVALID:{context}:{topic}")
            nonnegative_integer(count, f"{context}.count")


def validate_semantic_declaration(check: Mapping[str, Any], context: str) -> None:
    kind = check.get("type")
    if not isinstance(kind, str) or kind not in CHECK_TYPES:
        raise ContractError(f"SEMANTIC_TYPE_INVALID:{context}:{kind}")
    path = safe_text(check.get("path"), f"{context}.path")
    rel = Path(path)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise ContractError(f"SEMANTIC_PATH_UNSAFE:{context}:{path}")
    schemas: dict[str, tuple[set[str], set[str]]] = {
        "rosbag_topic": (
            {"type", "path", "topic", "count"},
            {"first_stamp_ns", "last_stamp_ns", "pointcloud_contract"},
        ),
        "rosbag_timeline_equal": (
            {"type", "path", "topic", "other_path"}, set(),
        ),
        "rosbag_topic_equal": (
            {"type", "path", "topic", "other_path", "count"}, set(),
        ),
        "rosbag_feature_extension": (
            {"type", "path", "base_path", "topic", "count"}, set(),
        ),
        "csv_rows": (
            {
                "type", "path", "count", "required_columns", "exact_column_count",
                "exact_header_sha256", "finite_numeric_columns",
                "nullable_numeric_columns", "integer_columns", "enum_columns",
                "histogram_columns", "integer_list_columns", "token_set_columns",
                "strictly_increasing_columns",
            },
            {
                "arithmetic_columns", "constant_columns", "maximum_columns", "minimum_columns",
                "nondecreasing_columns", "sum_columns", "frame_binding",
            },
        ),
        "file_sha256": ({"type", "path", "sha256"}, set()),
        "text_contains": ({"type", "path", "required_text"}, {"forbidden_text"}),
        "network_namespace_manifest": (
            {
                "type", "path", "expected_host_network_namespace",
                "expected_host_user_namespace", "formal_port",
                "backend_argv_sha256",
            },
            set(),
        ),
        "replay_manifest": ({"type", "path", "values"}, set()),
        "ape_kv": (
            {"type", "path", "required_keys", "integer_keys", "exact_keys"}, set(),
        ),
        "vins_trajectory": ({"type", "path", "min_rows"}, set()),
    }
    required, optional = schemas[str(kind)]
    if not required <= set(check) or set(check) - required - optional:
        raise ContractError(f"SEMANTIC_FIELDS_INVALID:{context}:{kind}:{sorted(check)}")
    if kind.startswith("rosbag"):
        topic = safe_text(check.get("topic"), f"{context}.topic")
        if not topic.startswith("/"):
            raise ContractError(f"TOPIC_NAME_INVALID:{context}:{topic}")
    if kind in {"rosbag_topic", "rosbag_topic_equal", "rosbag_feature_extension", "csv_rows"}:
        nonnegative_integer(check.get("count"), f"{context}.count")
    if kind == "rosbag_topic":
        for key in ("first_stamp_ns", "last_stamp_ns"):
            if key in check:
                nonnegative_integer(check[key], f"{context}.{key}")
        if "pointcloud_contract" in check:
            validate_pointcloud_declaration(check["pointcloud_contract"], context)
    if kind in {"rosbag_timeline_equal", "rosbag_topic_equal"}:
        other = Path(safe_text(check.get("other_path"), f"{context}.other_path"))
        if not other.is_absolute():
            raise ContractError(f"BAG_OTHER_PATH_INVALID:{context}")
    if kind == "rosbag_feature_extension":
        other = Path(safe_text(check.get("base_path"), f"{context}.base_path"))
        if not other.is_absolute():
            raise ContractError(f"FEATURE_EXTENSION_BASE_INVALID:{context}")
    if kind == "csv_rows":
        required_columns = string_list(check["required_columns"], f"{context}.required_columns")
        column_set = set(required_columns)
        if check["exact_column_count"] != len(required_columns):
            raise ContractError(f"CSV_EXACT_COLUMN_SCHEMA_SIZE:{context}")
        role_lists: dict[str, list[str]] = {}
        for list_key in (
            "nondecreasing_columns", "strictly_increasing_columns", "sum_columns",
            "finite_numeric_columns", "nullable_numeric_columns", "integer_columns",
        ):
            if list_key in check:
                values = string_list(check[list_key], f"{context}.{list_key}", nonempty=False)
                if not set(values) <= column_set:
                    raise ContractError(f"CSV_COLUMN_NOT_REQUIRED:{context}:{list_key}")
                role_lists[list_key] = values
        for map_key in (
            "arithmetic_columns", "constant_columns", "maximum_columns", "minimum_columns",
            "enum_columns", "histogram_columns", "integer_list_columns", "token_set_columns",
        ):
            values = check.get(map_key, {})
            if not isinstance(values, dict) or not set(values) <= column_set:
                raise ContractError(f"CSV_MAP_INVALID:{context}:{map_key}")
        base_roles = {
            "finite_numeric": set(role_lists["finite_numeric_columns"]),
            "nullable_numeric": set(role_lists["nullable_numeric_columns"]),
            "enum": set(check["enum_columns"]),
            "histogram": set(check["histogram_columns"]),
            "integer_list": set(check["integer_list_columns"]),
            "token_set": set(check["token_set_columns"]),
        }
        role_names = list(base_roles)
        for left_index, left_name in enumerate(role_names):
            for right_name in role_names[left_index + 1:]:
                overlap = base_roles[left_name] & base_roles[right_name]
                if overlap:
                    raise ContractError(
                        f"CSV_BASE_ROLE_OVERLAP:{context}:{left_name}:{right_name}:{sorted(overlap)}"
                    )
        governed = set().union(*base_roles.values())
        if governed != column_set:
            raise ContractError(
                f"CSV_UNGOVERNED_COLUMNS:{context}:"
                f"missing={sorted(column_set-governed)}:extra={sorted(governed-column_set)}"
            )
        finite_columns = base_roles["finite_numeric"]
        numeric_constraint_columns = (
            set(check.get("arithmetic_columns", {}))
            | set(check.get("maximum_columns", {}))
            | set(check.get("minimum_columns", {}))
            | set(role_lists.get("nondecreasing_columns", []))
            | set(role_lists["strictly_increasing_columns"])
            | set(role_lists.get("sum_columns", []))
            | set(role_lists["integer_columns"])
        )
        if not numeric_constraint_columns <= finite_columns:
            raise ContractError(
                f"CSV_FINITE_CONSTRAINT_ROLE_INVALID:{context}:"
                f"{sorted(numeric_constraint_columns-finite_columns)}"
            )
        for name, specification in check.get("arithmetic_columns", {}).items():
            if not isinstance(specification, dict) or set(specification) != {"start", "step"}:
                raise ContractError(f"CSV_ARITHMETIC_SPEC_INVALID:{context}:{name}")
            if any(isinstance(specification[key], bool) or not isinstance(specification[key], int) for key in specification):
                raise ContractError(f"CSV_ARITHMETIC_VALUE_INVALID:{context}:{name}")
        for map_key in ("maximum_columns", "minimum_columns"):
            for name, value in check.get(map_key, {}).items():
                finite_float(value, f"{context}.{map_key}.{name}")
        if nonnegative_integer(check["exact_column_count"], f"{context}.exact_column_count") < 1:
            raise ContractError(f"CSV_EXACT_COLUMN_COUNT_INVALID:{context}")
        digest = check["exact_header_sha256"]
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"CSV_HEADER_SHA256_INVALID:{context}")
        for name, allowed_values in check["enum_columns"].items():
            string_list(allowed_values, f"{context}.enum_columns.{name}")
        for name, specification in check["histogram_columns"].items():
            if not isinstance(specification, dict) or set(specification) not in (
                {"allowed_keys", "sum_equals_column"},
                {"allowed_keys", "sum_equals_column", "equals_column"},
            ):
                raise ContractError(f"CSV_HISTOGRAM_SPEC_INVALID:{context}:{name}")
            string_list(
                specification["allowed_keys"], f"{context}.histogram.{name}.allowed_keys"
            )
            target = safe_text(
                specification["sum_equals_column"], f"{context}.histogram.{name}.sum"
            )
            if target not in finite_columns:
                raise ContractError(f"CSV_HISTOGRAM_SUM_TARGET_INVALID:{context}:{name}")
            equal_target = specification.get("equals_column")
            if equal_target is not None and (
                safe_text(equal_target, f"{context}.histogram.{name}.equals")
                not in check["histogram_columns"] or equal_target == name
            ):
                raise ContractError(f"CSV_HISTOGRAM_EQUAL_TARGET_INVALID:{context}:{name}")
        for name, specification in check["integer_list_columns"].items():
            required_keys = {
                "separator", "allow_empty", "minimum_inclusive", "maximum_exclusive", "unique"
            }
            if not isinstance(specification, dict) or set(specification) != required_keys:
                raise ContractError(f"CSV_INTEGER_LIST_SPEC_INVALID:{context}:{name}")
            separator = safe_text(
                specification["separator"], f"{context}.integer_list.{name}.separator"
            )
            if (
                len(separator) != 1
                or not isinstance(specification["allow_empty"], bool)
                or not isinstance(specification["unique"], bool)
            ):
                raise ContractError(f"CSV_INTEGER_LIST_FLAGS_INVALID:{context}:{name}")
            minimum = nonnegative_integer(
                specification["minimum_inclusive"], f"{context}.integer_list.{name}.min"
            )
            maximum = nonnegative_integer(
                specification["maximum_exclusive"], f"{context}.integer_list.{name}.max"
            )
            if maximum <= minimum:
                raise ContractError(f"CSV_INTEGER_LIST_RANGE_INVALID:{context}:{name}")
        for name, specification in check["token_set_columns"].items():
            required_keys = {
                "separator", "allow_empty", "allowed_tokens", "unique", "singleton_tokens"
            }
            if not isinstance(specification, dict) or set(specification) != required_keys:
                raise ContractError(f"CSV_TOKEN_SET_SPEC_INVALID:{context}:{name}")
            separator = safe_text(
                specification["separator"], f"{context}.token_set.{name}.separator"
            )
            allowed = string_list(
                specification["allowed_tokens"], f"{context}.token_set.{name}.allowed"
            )
            singletons = string_list(
                specification["singleton_tokens"],
                f"{context}.token_set.{name}.singletons", nonempty=False,
            )
            if (
                len(separator) != 1
                or not isinstance(specification["allow_empty"], bool)
                or not isinstance(specification["unique"], bool)
                or not set(singletons) <= set(allowed)
            ):
                raise ContractError(f"CSV_TOKEN_SET_FLAGS_INVALID:{context}:{name}")
        frame_binding = check.get("frame_binding")
        if frame_binding is not None:
            expected_binding_keys = {
                "frame_index_column", "selector_frame_index_column", "stamp_column",
                "selector_stamp_column", "value_column", "stamp_format",
            }
            if not isinstance(frame_binding, dict) or set(frame_binding) != expected_binding_keys:
                raise ContractError(f"CSV_FRAME_BINDING_SPEC_INVALID:{context}")
            if frame_binding.get("stamp_format") != "ros_to_sec_float_repr":
                raise ContractError(f"CSV_FRAME_BINDING_FORMAT_INVALID:{context}")
            binding_columns = {
                safe_text(value, f"{context}.frame_binding.{key}")
                for key, value in frame_binding.items() if key != "stamp_format"
            }
            if len(binding_columns) != 5 or not binding_columns <= finite_columns:
                raise ContractError(f"CSV_FRAME_BINDING_COLUMNS_INVALID:{context}")
            if not {
                frame_binding["frame_index_column"],
                frame_binding["selector_frame_index_column"],
                frame_binding["value_column"],
            } <= set(role_lists["integer_columns"]):
                raise ContractError(f"CSV_FRAME_BINDING_INTEGER_COLUMNS_INVALID:{context}")
    if kind == "file_sha256":
        digest = check.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ContractError(f"FILE_SHA256_INVALID:{context}")
    if kind == "text_contains":
        string_list(check["required_text"], f"{context}.required_text")
        if "forbidden_text" in check:
            string_list(check["forbidden_text"], f"{context}.forbidden_text", nonempty=False)
    if kind == "network_namespace_manifest":
        for namespace_kind, key in (
            ("net", "expected_host_network_namespace"),
            ("user", "expected_host_user_namespace"),
        ):
            value = safe_text(check[key], f"{context}.{key}")
            if re.fullmatch(rf"{namespace_kind}:\[[0-9]+\]", value) is None:
                raise ContractError(f"NETNS_EXPECTED_HOST_IDENTITY:{context}:{key}")
        port = nonnegative_integer(check["formal_port"], f"{context}.formal_port")
        if not 1024 <= port <= 65535:
            raise ContractError(f"NETNS_FORMAL_PORT_INVALID:{context}:{port}")
        digest = check["backend_argv_sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ContractError(f"NETNS_BACKEND_ARGV_SHA256_INVALID:{context}")
    if kind == "replay_manifest":
        values = check.get("values")
        if not isinstance(values, dict) or not values:
            raise ContractError(f"MANIFEST_VALUES_INVALID:{context}")
        for key, value in values.items():
            safe_text(key, f"{context}.manifest-key")
            safe_text(value, f"{context}.manifest-value", allow_empty=True)
    if kind == "ape_kv":
        required_keys = string_list(check["required_keys"], f"{context}.required_keys")
        integer_keys = string_list(check["integer_keys"], f"{context}.integer_keys", nonempty=False)
        if not set(integer_keys) <= set(required_keys) or check.get("exact_keys") is not True:
            raise ContractError(f"APE_KEY_CONTRACT_INVALID:{context}")
    if kind == "vins_trajectory":
        if nonnegative_integer(check.get("min_rows"), f"{context}.min_rows") < 2:
            raise ContractError(f"TRAJECTORY_MIN_ROWS_INVALID:{context}")


def archival_output_paths(item: Mapping[str, Any]) -> dict[str, str]:
    values = item.get("archival_outputs")
    if not isinstance(values, dict):
        raise ContractError("ARCHIVAL_OUTPUTS_INVALID")
    result: dict[str, str] = {}
    for raw, reason in values.items():
        path = safe_text(raw, "archival-output")
        rel = Path(path)
        if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
            raise ContractError(f"ARCHIVAL_OUTPUT_UNSAFE:{path}")
        result[path] = safe_text(reason, f"archival-reason:{path}")
    return result


def identity_path_map(verified: Mapping[str, Mapping[str, Any]]) -> dict[Path, Mapping[str, Any]]:
    return {Path(value["path"]).absolute(): value for value in verified.values()}


def require_pinned_file(
    path: Path, verified: Mapping[str, Mapping[str, Any]], context: str
) -> None:
    path = path.absolute()
    actual, _data = snapshot(path)
    expected = identity_path_map(verified).get(path)
    if expected is None or not same_snapshot(actual, expected):
        raise ContractError(f"UNPINNED_FILE:{context}:{path}")


def contract_payload(lock: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "policy": lock.get("policy"),
        "score_usability": lock.get("score_usability"),
        "common_support": lock.get("common_support"),
        "external_inputs": lock.get("external_inputs"),
        "recovery_provenance": lock.get("recovery_provenance"),
        "items": lock.get("items"),
    }


def validate_items(lock: Mapping[str, Any], verified: Mapping[str, Mapping[str, Any]]) -> None:
    items, policy = lock.get("items"), lock.get("policy")
    if not isinstance(items, dict) or tuple(items) != ITEM_ORDER:
        raise ContractError("ITEM_SET_OR_JSON_ORDER_MISMATCH")
    if not isinstance(policy, dict) or tuple(policy.get("item_order", ())) != ITEM_ORDER:
        raise ContractError("ITEM_ORDER_MISMATCH")
    if policy.get("require_prior_items_terminal_before_next_launch") not in {None, False}:
        raise ContractError("PRIOR_ITEM_PSEUDODEPENDENCY_FORBIDDEN")
    generated_paths = {
        path.absolute()
        for other in items.values()
        if isinstance(other, dict)
        for path in output_paths(other)
    }
    ports: list[int] = []
    ros_homes: list[str] = []
    ros_log_dirs: list[str] = []
    for index, item_id in enumerate(ITEM_ORDER):
        item = items[item_id]
        if not isinstance(item, dict) or item.get("kind") != KINDS[item_id]:
            raise ContractError(f"ITEM_KIND_MISMATCH:{item_id}")
        if item.get("isolation_policy") != ISOLATION_POLICIES[item_id]:
            raise ContractError(f"ITEM_ISOLATION_POLICY_MISMATCH:{item_id}")
        deps = item.get("dependencies")
        if not isinstance(deps, list) or tuple(deps) != DEPENDENCIES[item_id]:
            raise ContractError(f"DEPENDENCIES_MISMATCH:{item_id}")
        if len(set(deps)) != len(deps) or any(ITEM_ORDER.index(dep) >= index for dep in deps):
            raise ContractError(f"DEPENDENCY_ORDER_INVALID:{item_id}")
        timeout = item.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 86400:
            raise ContractError(f"TIMEOUT_INVALID:{item_id}")
        base = output_dir(item)
        if base != OUTPUT_DIRS[item_id]:
            raise ContractError(f"OUTPUT_DIR_MISMATCH:{item_id}")
        if item.get("output_tree_policy") != "REQUIRE_EMPTY_BEFORE_CLAIM":
            raise ContractError(f"OUTPUT_TREE_POLICY_MISMATCH:{item_id}")
        link_raw = item.get("workspace_link")
        if not isinstance(link_raw, str) or not Path(link_raw).is_absolute():
            raise ContractError(f"WORKSPACE_LINK_INVALID:{item_id}")
        if any(part in {"", ".", ".."} for part in Path(link_raw).parts):
            raise ContractError(f"WORKSPACE_LINK_DOT_COMPONENT:{item_id}")
        link = Path(link_raw).absolute()
        if link != WORKSPACE_LINKS[item_id]:
            raise ContractError(f"WORKSPACE_LINK_EXACT_MISMATCH:{item_id}:{link}")
        logs_root = (ROOT / "logs").resolve(strict=True)
        if not contained(link.parent.resolve(strict=True), logs_root):
            raise ContractError(f"WORKSPACE_LINK_PARENT_ESCAPE:{item_id}")
        argv, env = command(item)
        host_namespace = policy.get("host_namespace_identity")
        if not isinstance(host_namespace, dict) or set(host_namespace) != {"network", "user"}:
            raise ContractError("HOST_NAMESPACE_POLICY_INVALID")
        expected_prefix = [
            "/usr/bin/unshare", "--user", "--map-root-user", "--net",
            "/usr/bin/python3.8",
            str(ROOT / "scripts/enter_samehistory_backend_netns_v4.py"),
            "--output-dir", str(base),
            "--formal-port", "11981",
            "--host-network-namespace", str(host_namespace["network"]),
            "--host-user-namespace", str(host_namespace["user"]),
            "--", "/usr/bin/bash",
            str(ROOT / "scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh"),
        ]
        if argv[:len(expected_prefix)] != expected_prefix:
            raise ContractError(f"NETNS_ARGV_PREFIX_MISMATCH:{item_id}")
        science_argv = argv[len(expected_prefix):]
        expected_science_argv = (
            ["origin", "10", "0", "2800", "klt", "1"]
            if item_id == "vanilla_origin_native_image_context"
            else [
                "external", "10", "0", "2800",
                "klt" if item_id == "klt_external_feature_context" else "hybrid_xfeat",
                "2",
            ]
        )
        if science_argv != expected_science_argv:
            raise ContractError(f"BACKEND_SCIENCE_ARGV_MISMATCH:{item_id}")
        authority_keys = string_list(
            item.get("authority_identity_keys"), f"{item_id}.authority_identity_keys"
        )
        if any(key not in verified for key in authority_keys):
            raise ContractError(f"ITEM_AUTHORITY_KEY_UNKNOWN:{item_id}")
        external_bindings = item.get("external_input_bindings")
        expected_external_bindings = EXPECTED_EXTERNAL_INPUT_BINDINGS[item_id]
        if external_bindings != expected_external_bindings:
            raise ContractError(f"EXTERNAL_INPUT_BINDINGS_MISMATCH:{item_id}")
        for binding_name, specification in expected_external_bindings.items():
            for identity_key in (
                specification["identity_key"],
                specification["source_receipt_identity_key"],
            ):
                if identity_key not in verified or identity_key not in authority_keys:
                    raise ContractError(
                        f"EXTERNAL_INPUT_AUTHORITY_NOT_BOUND:{item_id}:{binding_name}:{identity_key}"
                    )
        dependency_artifacts = item.get("dependency_artifacts")
        if not isinstance(dependency_artifacts, dict):
            raise ContractError(f"DEPENDENCY_ARTIFACTS_INVALID:{item_id}")
        declared_dependency_paths: set[Path] = set()
        for binding_name, specification in dependency_artifacts.items():
            safe_text(binding_name, f"{item_id}.dependency-binding")
            if not isinstance(specification, dict) or set(specification) != {"dependency", "relative_path"}:
                raise ContractError(f"DEPENDENCY_ARTIFACT_SPEC_INVALID:{item_id}:{binding_name}")
            dependency_id = specification.get("dependency")
            relative = safe_text(
                specification.get("relative_path"), f"{item_id}.dependency-relative"
            )
            if dependency_id not in DEPENDENCIES[item_id]:
                raise ContractError(f"DEPENDENCY_ARTIFACT_FALSE_DEP:{item_id}:{binding_name}")
            dependency_item = items[str(dependency_id)]
            dependency_outputs = {
                str(path.relative_to(output_dir(dependency_item))): path
                for path in output_paths(dependency_item)
            }
            if relative not in dependency_outputs:
                raise ContractError(f"DEPENDENCY_ARTIFACT_OUTPUT_UNKNOWN:{item_id}:{relative}")
            declared_dependency_paths.add(dependency_outputs[relative].absolute())
        require_pinned_file(Path(argv[0]), verified, f"{item_id}:argv0")
        executable_name = Path(argv[0]).name
        if executable_name == "bash":
            if len(argv) < 2 or not Path(argv[1]).is_absolute():
                raise ContractError(f"BASH_SCRIPT_INVALID:{item_id}")
            require_pinned_file(Path(argv[1]), verified, f"{item_id}:bash-script")
        if "-m" in argv:
            module_index = argv.index("-m") + 1
            if module_index >= len(argv):
                raise ContractError(f"PYTHON_MODULE_MISSING:{item_id}")
            module_path = ROOT / (argv[module_index].replace(".", "/") + ".py")
            require_pinned_file(module_path, verified, f"{item_id}:python-module")
        for origin, value in [
            *((f"argv[{position}]", value) for position, value in enumerate(argv)),
            *((f"env[{key}]", value) for key, value in env.items()),
        ]:
            candidate = Path(value)
            if not candidate.is_absolute():
                continue
            if candidate.absolute() in generated_paths:
                if (
                    not contained(candidate.absolute(), base)
                    and candidate.absolute() not in declared_dependency_paths
                ):
                    raise ContractError(f"UNBOUND_GENERATED_INPUT:{item_id}:{origin}:{candidate}")
                continue
            try:
                mode = candidate.lstat().st_mode
            except FileNotFoundError:
                continue
            if stat.S_ISREG(mode):
                require_pinned_file(candidate, verified, f"{item_id}:{origin}")
        output_rel = {str(path.relative_to(base)) for path in output_paths(item)}
        archival = archival_output_paths(item)
        if not set(archival) <= output_rel:
            raise ContractError(f"ARCHIVAL_OUTPUT_NOT_EXPECTED:{item_id}")
        checks = item.get("semantic_checks")
        if not isinstance(checks, list) or not checks:
            raise ContractError(f"SEMANTIC_CHECKS_EMPTY:{item_id}")
        checked_paths: set[str] = set()
        for check_index, check in enumerate(checks):
            if not isinstance(check, dict) or check.get("path") not in output_rel:
                raise ContractError(f"SEMANTIC_CHECK_INVALID:{item_id}")
            validate_semantic_declaration(check, f"{item_id}[{check_index}]")
            authority_reference = check.get("other_path", check.get("base_path"))
            if authority_reference is not None:
                reference = Path(str(authority_reference)).absolute()
                if reference in generated_paths:
                    if reference not in declared_dependency_paths:
                        raise ContractError(
                            f"SEMANTIC_REFERENCE_NOT_DECLARED_DEPENDENCY:{item_id}:{reference}"
                        )
                else:
                    require_pinned_file(
                        reference, verified, f"{item_id}:semantic-reference:{check_index}"
                    )
            checked_paths.add(str(check["path"]))
        if checked_paths & set(archival):
            raise ContractError(f"OUTPUT_BOTH_CHECKED_AND_ARCHIVAL:{item_id}")
        if checked_paths | set(archival) != output_rel:
            missing = sorted(output_rel - checked_paths - set(archival))
            raise ContractError(f"OUTPUT_WITHOUT_CONTRACT:{item_id}:{missing}")
        signatures = {(str(row["type"]), str(row["path"]), str(row.get("topic", ""))) for row in checks}
        config_name = (
            "vins_aqualoc_archaeo_origin.yaml"
            if item_id == "vanilla_origin_native_image_context"
            else "vins_aqualoc_archaeo_external.yaml"
        )
        required_signatures: set[tuple[str, str, str]] = {
            ("vins_trajectory", "vins_output/vio.csv", ""),
            ("file_sha256", config_name, ""),
            ("file_sha256", "aqualoc_archaeo10_pinhole.yaml", ""),
            ("replay_manifest", "replay_manifest.txt", ""),
            ("ape_kv", "ape.txt", ""),
            ("network_namespace_manifest", "network_namespace_manifest.json", ""),
        }
        if not required_signatures <= signatures:
            raise ContractError(f"ITEM_REQUIRED_CHECK_MISSING:{item_id}:{sorted(required_signatures-signatures)}")
        if item_id in BACKENDS:
            for key, expected in EXPECTED_VINS_ENV.items():
                if env.get(key) != expected:
                    raise ContractError(f"VINS_ENV_PROTOCOL_MISMATCH:{item_id}:{key}")
            try:
                port = int(env.get("PORT", ""))
            except ValueError as error:
                raise ContractError(f"PORT_INVALID:{item_id}") from error
            if not 1024 <= port <= 65535:
                raise ContractError(f"PORT_RANGE:{item_id}")
            ports.append(port)
            expected_runtime_root = EXP_ROOT / "runtime" / item_id
            expected_ros_home = str(expected_runtime_root / "ros_home")
            expected_ros_log = str(expected_runtime_root / "ros_log")
            if env.get("ROS_HOME") != expected_ros_home or env.get("ROS_LOG_DIR") != expected_ros_log:
                raise ContractError(f"PER_ITEM_ROS_RUNTIME_DIR_MISMATCH:{item_id}")
            ros_homes.append(expected_ros_home)
            ros_log_dirs.append(expected_ros_log)
            raw_identity = verified.get("raw_bag")
            if raw_identity is None or env.get("RAW_BAG") != raw_identity.get("path"):
                raise ContractError(f"RAW_BAG_BINDING_MISMATCH:{item_id}")
            if item_id == "vanilla_origin_native_image_context":
                if "FEATURE_BAG_OVERRIDE" in env:
                    raise ContractError("VANILLA_FEATURE_OVERRIDE_FORBIDDEN")
            else:
                binding = expected_external_bindings["feature_bag"]
                expected_feature = verified[binding["identity_key"]]["path"]
                if env.get("FEATURE_BAG_OVERRIDE") != expected_feature:
                    raise ContractError(f"FEATURE_BAG_BINDING_MISMATCH:{item_id}")
    if len(ports) != len(ITEM_ORDER) or set(ports) != set(FORMAL_ROS_PORTS):
        raise ContractError(f"FORMAL_ROS_PORT_SET_MISMATCH:{sorted(ports)}")
    if len(set(ros_homes)) != len(ITEM_ORDER) or len(set(ros_log_dirs)) != len(ITEM_ORDER):
        raise ContractError("PER_ITEM_ROS_RUNTIME_DIRS_NOT_DISTINCT")

    required_static_paths = {
        ROOT / "scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh",
        ROOT / "scripts/enter_samehistory_backend_netns_v4.py",
        ROOT / "scripts/record_vins_env.sh",
        ROOT / "scripts/wait_for_ros_subscribers.py",
        ROOT / "scripts/evaluate_vins_sim_ape.py",
        ROOT / "scripts/analyze_samehistory_system_a10_finalonline_v4_backend_recovery.py",
        Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
    }
    for path in required_static_paths:
        require_pinned_file(path, verified, "required-static-authority")
    rosout_identity = verified.get("rosout_node")
    if (
        rosout_identity is None
        or Path(str(rosout_identity.get("path", ""))).absolute()
        != Path("/opt/ros/noetic/lib/rosout/rosout")
    ):
        raise ContractError("ROSOUT_NODE_IDENTITY_KEY_MISSING_OR_WRONG")


def pinned_json(
    key: str, verified: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    identity = verified.get(key)
    if identity is None:
        raise ContractError(f"PINNED_JSON_IDENTITY_MISSING:{key}")
    path = Path(str(identity["path"]))
    actual, payload = snapshot(path, with_data=True)
    if not same_snapshot(actual, identity):
        raise ContractError(f"PINNED_JSON_CHANGED:{key}")
    assert payload is not None
    return parse_json(payload, path)


def validate_accepted_v3_source(
    receipt_key: str, source_item_id: str, artifact_identity_keys: Sequence[str],
    verified: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    receipt = pinned_json(receipt_key, verified)
    terminal = receipt.get("terminal_process")
    artifact = receipt.get("artifact_contract")
    execution = receipt.get("execution_integrity")
    if (
        receipt.get("schema_version")
        != "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
        or receipt.get("item_id") != source_item_id
        or receipt.get("status") != "TERMINAL_PROCESS_RC0"
        or receipt.get("overall_disposition") != "ACCEPTED"
        or not isinstance(terminal, dict)
        or terminal.get("status") != "TERMINAL_PROCESS_RC0"
        or terminal.get("raw_return_code") != 0
        or terminal.get("timed_out") is not False
        or not isinstance(artifact, dict) or artifact.get("status") != "PASS"
        or not isinstance(execution, dict) or execution.get("status") != "PASS"
    ):
        raise ContractError(f"V3_SOURCE_RECEIPT_NOT_ACCEPTED:{receipt_key}")
    v3_lock = verified.get("v3_execution_lock")
    if v3_lock is None or receipt.get("execution_lock") != public(v3_lock):
        raise ContractError(f"V3_SOURCE_LOCK_BINDING:{receipt_key}")
    output_map = artifact.get("outputs")
    if not isinstance(output_map, dict):
        raise ContractError(f"V3_SOURCE_OUTPUT_MAP:{receipt_key}")
    checked_outputs: dict[str, Any] = {}
    for artifact_key in artifact_identity_keys:
        identity = verified.get(artifact_key)
        if identity is None:
            raise ContractError(f"V3_SOURCE_ARTIFACT_IDENTITY_MISSING:{artifact_key}")
        recorded = output_map.get(str(identity["path"]))
        if not isinstance(recorded, dict) or not same_snapshot(identity, recorded):
            raise ContractError(
                f"V3_SOURCE_ARTIFACT_RECEIPT_BINDING:{receipt_key}:{artifact_key}"
            )
        checked_outputs[artifact_key] = public(identity)
    return {
        "receipt": public(verified[receipt_key]),
        "source_item_id": source_item_id,
        "outputs": checked_outputs,
        "status": "ACCEPTED_SOURCE_VALIDATED",
    }


def validate_external_source_provenance(
    lock: Mapping[str, Any], verified: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    v3_lock = pinned_json("v3_execution_lock", verified)
    v3_items = v3_lock.get("items")
    if not isinstance(v3_items, dict):
        raise ContractError("V3_EXECUTION_LOCK_ITEMS_INVALID")
    for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
        item = v3_items.get(item_id)
        if (
            not isinstance(item, dict)
            or item.get("output_dir") != str(paths["output_dir"])
        ):
            raise ContractError(f"V3_PENDING_OUTPUT_DIR_BINDING:{item_id}")
    raw_audit = pinned_json("raw_audit", verified)
    raw_identity = verified.get("raw_bag")
    raw_record = raw_audit.get("raw_bag") if isinstance(raw_audit, dict) else None
    if (
        raw_audit.get("schema_version") != "aqua-fe-a10-samehistory-raw-audit-v1"
        or raw_audit.get("status") != "PASS"
        or raw_identity is None or not isinstance(raw_record, dict)
        or any(raw_record.get(key) != raw_identity.get(key) for key in ("path", "size_bytes", "sha256"))
        or raw_audit.get("source_range", {}).get("camera_indices_inclusive") != [0, 2800]
        or raw_audit.get("score_range", {}).get("camera_indices_inclusive") != [2400, 2800]
    ):
        raise ContractError("RAW_AUDIT_BINDING_INVALID")
    klt = validate_accepted_v3_source(
        "v3_klt_receipt", "klt_input_adoption",
        (
            "v3_klt_features_bag", "v3_klt_frontend_metrics",
            "v3_klt_camera_yaml", "v3_klt_adoption_manifest",
        ),
        verified,
    )
    aqua = validate_accepted_v3_source(
        "v3_aquafe_receipt", "aquafe_build",
        (
            "v3_aquafe_full_merged_bag", "v3_aquafe_sidecar_bag",
            "v3_aquafe_stats_csv",
        ),
        verified,
    )
    failed = pinned_json("v3_vanilla_failed_receipt", verified)
    failed_terminal = failed.get("terminal_process")
    if (
        failed.get("schema_version")
        != "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
        or failed.get("item_id") != "vanilla_origin_native_image_context"
        or failed.get("status") != "TERMINAL_PROCESS_FAILED"
        or failed.get("overall_disposition") != "PROCESS_FAILED"
        or not isinstance(failed_terminal, dict)
        or failed_terminal.get("raw_return_code") != -9
        or failed_terminal.get("timed_out") is not True
        or failed.get("artifact_contract", {}).get("status") != "FAIL"
        or failed.get("execution_integrity", {}).get("status") != "FAIL"
    ):
        raise ContractError("V3_VANILLA_FAILED_BOUNDARY_INVALID")
    consumed_identity_keys = {
        specification["identity_key"]
        for bindings in EXPECTED_EXTERNAL_INPUT_BINDINGS.values()
        for specification in bindings.values()
    }
    failed_output_paths = set(failed.get("artifact_contract", {}).get("outputs", {}))
    if any(
        str(verified[key]["path"]) in failed_output_paths for key in consumed_identity_keys
    ):
        raise ContractError("V3_FAILED_VANILLA_OUTPUT_CONSUMED")
    external_inputs = lock.get("external_inputs")
    if not isinstance(external_inputs, dict) or set(external_inputs) != {
        "raw_v1", "klt_v3_accepted", "aquafe_v3_accepted"
    }:
        raise ContractError("EXTERNAL_INPUTS_DECLARATION_INVALID")
    return {
        "raw_v1": {"audit": public(verified["raw_audit"]), "raw_bag": public(raw_identity)},
        "klt_v3_accepted": klt,
        "aquafe_v3_accepted": aqua,
        "v3_vanilla_failed_retained_not_consumed": public(
            verified["v3_vanilla_failed_receipt"]
        ),
    }


def v3_pending_allowance_guard_contract() -> dict[str, Any]:
    return {
        "required_state": "CLAIM_AND_RECEIPT_ABSENT",
        "required_absence_phases": list(V3_PENDING_REQUIRED_ABSENCE_PHASES),
        "items": {
            item_id: {
                role: str(path)
                for role, path in paths.items()
            }
            for item_id, paths in V3_PENDING_BACKEND_GUARDS.items()
        },
    }


def catkin_setup_dynamic_input_contract() -> dict[str, Any]:
    return {
        "catkin_marker_identity_keys": list(CATKIN_MARKERS),
        "ros_profile_directory": str(ROS_PROFILE_DIR),
        "ros_profile_exact_entries": [
            {
                "name": name,
                "identity_key": f"ros_environment_hook_{index:02d}",
            }
            for index, name in enumerate(ROS_HOOK_NAMES)
        ],
        "workspace_profile_directories_required_absent": [
            str(path) for path in ABSENT_WORKSPACE_PROFILE_DIRS
        ],
        "python3_symlink": {
            "path": str(PYTHON3_SYMLINK),
            "required_target": PYTHON3_SYMLINK_TARGET,
            "canonical_identity_key": "python3_8",
        },
    }


def validate_catkin_setup_dynamic_inputs(
    lock: Mapping[str, Any], verified: Mapping[str, Mapping[str, Any]], *, phase: str,
) -> None:
    phase = safe_text(phase, "catkin-setup-phase")
    if phase not in {
        "lock_verification", "before_claim", "after_claim_before_popen", "postflight"
    }:
        raise ContractError(f"CATKIN_SETUP_PHASE_INVALID:{phase}")
    policy = lock.get("policy")
    if (
        not isinstance(policy, dict)
        or policy.get("catkin_setup_dynamic_inputs")
        != catkin_setup_dynamic_input_contract()
    ):
        raise ContractError(f"CATKIN_SETUP_CONTRACT_INVALID:{phase}")
    for key, path in CATKIN_MARKERS.items():
        frozen = verified.get(key)
        if frozen is None or frozen.get("path") != str(path):
            raise ContractError(f"CATKIN_MARKER_IDENTITY_INVALID:{phase}:{key}")
    try:
        no_symlink_components(ROS_PROFILE_DIR)
        descriptor = os.open(
            ROS_PROFILE_DIR,
            os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0),
        )
    except OSError as error:
        raise ContractError(f"ROS_PROFILE_DIR_INVALID:{phase}:{error}") from error
    try:
        observed_names = tuple(sorted(os.listdir(descriptor)))
        if observed_names != ROS_HOOK_NAMES:
            raise ContractError(f"ROS_PROFILE_MEMBERSHIP_DRIFT:{phase}")
        for index, name in enumerate(observed_names):
            observed = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if not stat.S_ISREG(observed.st_mode):
                raise ContractError(f"ROS_PROFILE_ENTRY_NOT_REGULAR:{phase}:{name}")
            key = f"ros_environment_hook_{index:02d}"
            frozen = verified.get(key)
            if frozen is None or frozen.get("path") != str(ROS_PROFILE_DIR / name):
                raise ContractError(f"ROS_PROFILE_IDENTITY_BINDING:{phase}:{name}")
    finally:
        os.close(descriptor)
    for path in ABSENT_WORKSPACE_PROFILE_DIRS:
        try:
            os.lstat(path)
        except FileNotFoundError:
            continue
        raise ContractError(f"WORKSPACE_PROFILE_DIR_APPEARED:{phase}:{path}")
    try:
        link_stat = os.lstat(PYTHON3_SYMLINK)
    except OSError as error:
        raise ContractError(f"PYTHON3_SYMLINK_INVALID:{phase}:{error}") from error
    python_identity = verified.get("python3_8")
    if (
        not stat.S_ISLNK(link_stat.st_mode)
        or os.readlink(PYTHON3_SYMLINK) != PYTHON3_SYMLINK_TARGET
        or PYTHON3_SYMLINK.resolve(strict=True) != Path("/usr/bin/python3.8")
        or python_identity is None
        or python_identity.get("path") != "/usr/bin/python3.8"
    ):
        raise ContractError(f"PYTHON3_SYMLINK_DRIFT:{phase}")


def validate_v3_pending_allowance_guard_contract(
    lock: Mapping[str, Any],
) -> None:
    recovery = lock.get("recovery_provenance")
    if not isinstance(recovery, dict):
        raise ContractError("RECOVERY_PROVENANCE_INVALID")
    if recovery.get("unconsumed_v3_backend_items") != list(
        V3_PENDING_BACKEND_GUARDS
    ):
        raise ContractError("V3_PENDING_BACKEND_ITEM_DECLARATION_INVALID")
    if recovery.get("v3_pending_backend_allowance_guard") != (
        v3_pending_allowance_guard_contract()
    ):
        raise ContractError("V3_PENDING_BACKEND_GUARD_CONTRACT_INVALID")


def validate_v3_pending_guard_evidence(
    value: Any, *, phase: str,
) -> dict[str, Any]:
    expected_top = {
        "status", "phase", "required_state", "checked_at_local", "items"
    }
    if not isinstance(value, dict) or set(value) != expected_top:
        raise ContractError(f"V3_PENDING_GUARD_EVIDENCE_SCHEMA:{phase}")
    if (
        value.get("status") != "PASS"
        or value.get("phase") != phase
        or value.get("required_state") != "CLAIM_AND_RECEIPT_ABSENT"
    ):
        raise ContractError(f"V3_PENDING_GUARD_EVIDENCE_STATUS:{phase}")
    safe_text(value.get("checked_at_local"), f"v3-pending-checked-at:{phase}")
    items = value.get("items")
    if not isinstance(items, dict) or set(items) != set(V3_PENDING_BACKEND_GUARDS):
        raise ContractError(f"V3_PENDING_GUARD_EVIDENCE_ITEMS:{phase}")
    expected_item_keys = {
        "output_dir", "claim_path", "claim_present",
        "receipt_path", "receipt_present",
    }
    for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
        row = items.get(item_id)
        if not isinstance(row, dict) or set(row) != expected_item_keys:
            raise ContractError(
                f"V3_PENDING_GUARD_EVIDENCE_ITEM_SCHEMA:{phase}:{item_id}"
            )
        for role in ("output_dir", "claim_path", "receipt_path"):
            if row.get(role) != str(paths[role]):
                raise ContractError(
                    f"V3_PENDING_GUARD_EVIDENCE_PATH:{phase}:{item_id}:{role}"
                )
        if row.get("claim_present") is not False or row.get(
            "receipt_present"
        ) is not False:
            raise ContractError(
                f"V3_PENDING_GUARD_EVIDENCE_PRESENT:{phase}:{item_id}"
            )
    return dict(value)


def audit_v3_pending_backend_allowances(
    lock: Mapping[str, Any], *, phase: str,
) -> dict[str, Any]:
    validate_v3_pending_allowance_guard_contract(lock)
    phase = safe_text(phase, "v3-pending-guard-phase")
    if phase not in set(V3_PENDING_REQUIRED_ABSENCE_PHASES) - {"lock_build"}:
        raise ContractError(f"V3_PENDING_BACKEND_GUARD_PHASE_INVALID:{phase}")
    evidence: dict[str, Any] = {}
    present: list[str] = []
    for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
        output_dir = paths["output_dir"]
        try:
            no_symlink_components(output_dir)
            descriptor = os.open(
                output_dir,
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0),
            )
        except FileNotFoundError as error:
            raise ContractError(
                f"V3_PENDING_BACKEND_OUTPUT_DIR_MISSING:{phase}:"
                f"{item_id}:{output_dir}"
            ) from error
        except OSError as error:
            raise ContractError(
                f"V3_PENDING_BACKEND_OUTPUT_DIR_INVALID:{phase}:"
                f"{item_id}:{output_dir}:{error}"
            ) from error
        item_evidence: dict[str, Any] = {"output_dir": str(output_dir)}
        try:
            observed = os.fstat(descriptor)
            if not stat.S_ISDIR(observed.st_mode):
                raise ContractError(
                    f"V3_PENDING_BACKEND_OUTPUT_DIR_INVALID:{phase}:"
                    f"{item_id}:{output_dir}"
                )
            for role in ("claim_path", "receipt_path"):
                path = paths[role]
                if path.parent != output_dir:
                    raise ContractError(
                        f"V3_PENDING_BACKEND_LEAF_PARENT_INVALID:{item_id}:{path}"
                    )
                try:
                    os.stat(path.name, dir_fd=descriptor, follow_symlinks=False)
                    path_present = True
                except FileNotFoundError:
                    path_present = False
                item_evidence[role] = str(path)
                item_evidence[role.replace("_path", "_present")] = path_present
                if path_present:
                    present.append(f"{item_id}:{role}:{path}")
        finally:
            os.close(descriptor)
        evidence[item_id] = item_evidence
    if present:
        raise ContractError(
            f"V3_PENDING_BACKEND_ALLOWANCE_CONSUMED:{phase}:"
            + ",".join(present)
        )
    result = {
        "status": "PASS",
        "phase": phase,
        "required_state": "CLAIM_AND_RECEIPT_ABSENT",
        "checked_at_local": now_local(),
        "items": evidence,
    }
    return validate_v3_pending_guard_evidence(result, phase=phase)


def verify_lock(path: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    if path.absolute() != DEFAULT_LOCK.absolute():
        raise ContractError(f"NONDEFAULT_LOCK_FORBIDDEN:{path}")
    lock_snapshot, data = snapshot(path, with_data=True)
    assert data is not None
    lock = parse_json(data, path)
    if lock.get("schema_version") != LOCK_SCHEMA or lock.get("status") != "FROZEN_BEFORE_SCORED_RUNS":
        raise ContractError("LOCK_SCHEMA_OR_STATUS_INVALID")
    policy = lock.get("policy")
    if not isinstance(policy, dict) or policy.get("global_flock_path") != str(GLOBAL_FLOCK):
        raise ContractError("LOCK_POLICY_OR_FLOCK_INVALID")
    base_env = policy.get("base_environment")
    if not isinstance(base_env, dict) or not base_env:
        raise ContractError("BASE_ENV_INVALID")
    for raw_key, raw_value in base_env.items():
        key = safe_text(raw_key, "base-env-key")
        if "=" in key:
            raise ContractError(f"BASE_ENV_KEY_EQUALS:{key!r}")
        safe_text(raw_value, f"base-env[{key}]", allow_empty=True)
    if policy.get("cwd") != str(ROOT) or policy.get("large_artifact_root") != str(EXP_ROOT):
        raise ContractError("LOCK_ROOT_POLICY_INVALID")
    host_namespace = policy.get("host_namespace_identity")
    if not isinstance(host_namespace, dict) or set(host_namespace) != {"network", "user"}:
        raise ContractError("HOST_NAMESPACE_POLICY_INVALID")
    if (
        host_namespace.get("network") != current_namespace_identity("net")
        or host_namespace.get("user") != current_namespace_identity("user")
    ):
        raise ContractError("SUPERVISOR_HOST_NAMESPACE_CHANGED")
    score = lock.get("score_usability")
    required_score_keys = {
        "score_start_ns", "score_end_ns", "nominal_backend_output_rate_hz",
        "minimum_score_temporal_span_coverage", "maximum_score_output_gap_s",
        "maximum_score_failure_mentions", "maximum_score_restart_or_reset_events",
    }
    score_policy_values = {
        "crop_interval": "inclusive",
        "require_initialization_before_or_within_score_window": True,
        "unresolved_score_log_event_attribution_is_failure": True,
        "score_failure_is_usability_fail_not_terminal_process_failure": True,
    }
    if (
        not isinstance(score, dict)
        or set(score) != required_score_keys | set(score_policy_values)
        or any(score.get(key) != value for key, value in score_policy_values.items())
    ):
        raise ContractError("SCORE_USABILITY_SCHEMA_INVALID")
    start = nonnegative_integer(score["score_start_ns"], "score_start_ns")
    end = nonnegative_integer(score["score_end_ns"], "score_end_ns")
    if (start, end) != (1542888916043622160, 1542888936039921424) or end <= start:
        raise ContractError("SCORE_WINDOW_MISMATCH")
    if finite_float(score["minimum_score_temporal_span_coverage"], "score_coverage") != 0.70:
        raise ContractError("SCORE_COVERAGE_GATE_MISMATCH")
    if finite_float(score["maximum_score_output_gap_s"], "score_gap") != 0.50:
        raise ContractError("SCORE_GAP_GATE_MISMATCH")
    if score["maximum_score_failure_mentions"] != 0 or score["maximum_score_restart_or_reset_events"] != 0:
        raise ContractError("SCORE_EVENT_GATE_MISMATCH")
    if score["nominal_backend_output_rate_hz"] != 10:
        raise ContractError("SCORE_RATE_MISMATCH")
    common = lock.get("common_support")
    if not isinstance(common, dict) or common != {
        "denominator_reference_rows": 21,
        "minimum_common_rows": 15,
        "minimum_common_coverage": 0.70,
        "minimum_descriptive_rpe_pairs": 10,
        "formal_ape_minimum_poses": 30,
        "formal_ape_gate_open": False,
    }:
        raise ContractError("COMMON_SUPPORT_CONTRACT_MISMATCH")
    protocol = lock.get("protocol")
    identities = lock.get("identities")
    if not isinstance(protocol, dict) or not isinstance(identities, dict) or not identities:
        raise ContractError("LOCK_IDENTITIES_MISSING")
    verified: dict[str, dict[str, Any]] = {"protocol": verify_identity("protocol", protocol)}
    for name, claim in identities.items():
        if not isinstance(claim, dict):
            raise ContractError(f"IDENTITY_CLAIM_INVALID:{name}")
        verified[str(name)] = verify_identity(str(name), claim)
    own = verified.get("supervisor")
    if own is None or Path(own["path"]).absolute() != Path(__file__).absolute():
        raise ContractError("SUPERVISOR_NOT_PINNED")
    builder = verified.get("lock_builder")
    if builder is None or Path(builder["path"]).absolute() != ROOT / "scripts/build_samehistory_system_a10_finalonline_v4_backend_recovery_execution_lock.py":
        raise ContractError("LOCK_BUILDER_NOT_PINNED")
    if any(FORBIDDEN_WORKSPACE in str(value.get("path", "")) for value in verified.values()):
        raise ContractError("FORBIDDEN_WORKSPACE_IDENTITY")
    validate_catkin_setup_dynamic_inputs(
        lock, verified, phase="lock_verification"
    )
    validate_v3_pending_allowance_guard_contract(lock)
    audit_v3_pending_backend_allowances(lock, phase="lock_verification")
    validate_external_source_provenance(lock, verified)
    validate_items(lock, verified)
    actual_contract_digest = compact_json_sha256(contract_payload(lock))
    if not re.fullmatch(r"[0-9a-f]{64}", EXPECTED_CONTRACT_SHA256):
        raise ContractError("SUPERVISOR_CONTRACT_DIGEST_NOT_FROZEN")
    if actual_contract_digest != EXPECTED_CONTRACT_SHA256:
        raise ContractError(f"LOCK_CONTRACT_DIGEST_MISMATCH:{actual_contract_digest}")
    return lock, verified, lock_snapshot


def authority_equal(
    before: Mapping[str, Mapping[str, Any]], before_lock: Mapping[str, Any],
    after: Mapping[str, Mapping[str, Any]], after_lock: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    differences: list[str] = []
    if not same_snapshot(before_lock, after_lock):
        differences.append("execution_lock")
    if set(before) != set(after):
        differences.append("identity_key_set")
    for name in sorted(set(before) & set(after)):
        if not same_snapshot(before[name], after[name]):
            differences.append(name)
    return not differences, differences


@contextmanager
def blocked_signals() -> Iterator[None]:
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, TERM_SIGNALS)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


@contextmanager
def interruption_handlers() -> Iterator[list[int]]:
    previous: dict[int, Any] = {}
    pending: list[int] = []

    def handler(signum: int, _frame: Any) -> None:
        pending.append(signum)

    for signum in TERM_SIGNALS:
        previous[signum] = signal.getsignal(signum)
        signal.signal(signum, handler)
    try:
        yield pending
    finally:
        with blocked_signals():
            for signum, old in previous.items():
                signal.signal(signum, old)


def raise_pending_interruption(pending: Sequence[int]) -> None:
    if pending:
        raise SupervisorInterruption(int(pending[0]))


def fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_publish(
    path: Path, payload: Mapping[str, Any], *, propagate_interruption_after_commit: bool = False
) -> str:
    """Temp+fsync+hard-link publication; never exposes a partial final file."""
    path = path.absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    no_symlink_components(path.parent)
    data = canonical_json(payload)
    temp = path.parent / f".{path.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    payload_fsynced = False
    hard_link_created = False
    link_directory_fsynced = False
    try:
        with blocked_signals():
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(temp, flags, 0o600)
            try:
                offset = 0
                while offset < len(data):
                    written = os.write(descriptor, data[offset:])
                    if written <= 0:
                        raise OSError("zero-length write")
                    offset += written
                os.fchmod(descriptor, 0o444)
                os.fsync(descriptor)
                payload_fsynced = True
            finally:
                os.close(descriptor)
            try:
                os.link(temp, path, follow_symlinks=False)
                hard_link_created = True
                fsync_dir(path.parent)
                link_directory_fsynced = True
            except FileExistsError:
                _existing, existing_data = snapshot(path, with_data=True)
                if existing_data != data:
                    raise ContractError(f"ATOMIC_PUBLISH_COLLISION:{path}")
                fsync_dir(path.parent)
                link_directory_fsynced = True
                return "ALREADY_IDENTICAL"
            finally:
                try:
                    temp.unlink()
                    fsync_dir(path.parent)
                except FileNotFoundError:
                    pass
        return "PUBLISHED"
    except BaseException as publication_error:
        # If link publication completed before an fsync/unmask interruption,
        # the complete matching final file is authoritative and Popen must
        # never be retried merely because the caller missed the return edge.
        committed = False
        try:
            _final, final_data = snapshot(path, with_data=True)
            committed = bool(
                final_data == data
                and payload_fsynced
                and link_directory_fsynced
                and (hard_link_created or path.exists())
            )
        except BaseException:
            committed = False
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        if committed:
            if propagate_interruption_after_commit and isinstance(
                publication_error, SupervisorInterruption
            ):
                raise publication_error
            return "PUBLISHED_POSTLINK_RECOVERED"
        raise


@contextmanager
def global_mutex() -> Iterator[dict[str, Any]]:
    GLOBAL_FLOCK.parent.mkdir(parents=True, exist_ok=True)
    no_symlink_components(GLOBAL_FLOCK.parent)
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(GLOBAL_FLOCK, flags, 0o644)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError("GLOBAL_FLOCK_NOT_REGULAR")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ContractError("ANOTHER_SUPERVISOR_HOLDS_GLOBAL_FLOCK") from error
        yield {"path": str(GLOBAL_FLOCK), "device": info.st_dev, "inode": info.st_ino, "pid": os.getpid()}
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def directory_identity(descriptor: int) -> tuple[int, int]:
    info = os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):
        raise ContractError("WORKSPACE_PARENT_FD_NOT_DIRECTORY")
    return int(info.st_dev), int(info.st_ino)


def open_directory_path_nofollow(path: Path) -> int:
    """Walk an absolute directory path with openat and O_NOFOLLOW per component."""
    path = path.absolute()
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise ContractError(f"DIRECTORY_PATH_UNSAFE:{path}")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open("/", flags)
    try:
        for part in path.parts[1:]:
            next_descriptor = os.open(part, flags, dir_fd=descriptor)
            previous_descriptor = descriptor
            descriptor = next_descriptor
            os.close(previous_descriptor)
        directory_identity(descriptor)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def validate_workspace_parent_mapping(real_parent_descriptor: int) -> None:
    """Bind the governed logical logs mapping to one already-open real inode."""
    try:
        link_info = WORKSPACE_LOGS_LINK.lstat()
    except FileNotFoundError as error:
        raise ContractError("WORKSPACE_LOGS_LINK_MISSING") from error
    if not stat.S_ISLNK(link_info.st_mode):
        raise ContractError("WORKSPACE_LOGS_LINK_NOT_SYMLINK")
    try:
        raw_target = os.readlink(WORKSPACE_LOGS_LINK)
    except OSError as error:
        raise ContractError(f"WORKSPACE_LOGS_READLINK_FAILED:{error.errno}") from error
    if raw_target != str(WORKSPACE_REAL_LOGS_ROOT):
        raise ContractError(f"WORKSPACE_LOGS_TARGET_MISMATCH:{raw_target}")

    descriptors: list[int] = []
    try:
        try:
            descriptors.append(open_directory_path_nofollow(WORKSPACE_REAL_LINK_PARENT))
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptors.append(os.open(WORKSPACE_LOGICAL_LINK_PARENT, flags))
        except OSError as error:
            raise ContractError(
                f"WORKSPACE_PARENT_OPEN_FAILED:{error.filename}:{error.errno}"
            ) from error
        expected = directory_identity(real_parent_descriptor)
        if any(directory_identity(descriptor) != expected for descriptor in descriptors):
            raise ContractError("WORKSPACE_LOGICAL_REAL_PARENT_IDENTITY_MISMATCH")
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


@contextmanager
def governed_workspace_parent() -> Iterator[int]:
    """Open and retain the exact real workspace-link parent across leaf I/O."""
    try:
        descriptor = open_directory_path_nofollow(WORKSPACE_REAL_LINK_PARENT)
    except OSError as error:
        raise ContractError(
            f"WORKSPACE_REAL_PARENT_OPEN_FAILED:{WORKSPACE_REAL_LINK_PARENT}:{error.errno}"
        ) from error
    try:
        validate_workspace_parent_mapping(descriptor)
        yield descriptor
        validate_workspace_parent_mapping(descriptor)
    finally:
        os.close(descriptor)


def prepare_layout(lock: Mapping[str, Any]) -> None:
    for item in lock["items"].values():
        base = output_dir(item)
        base.parent.mkdir(parents=True, exist_ok=True)
        no_symlink_components(base.parent)
        if base.exists() or base.is_symlink():
            no_symlink_components(base)
            if not base.is_dir():
                raise ContractError(f"OUTPUT_DIR_NOT_DIRECTORY:{base}")
        else:
            base.mkdir(mode=0o755)
            fsync_dir(base.parent)
        _argv, declared_env = command(item)
        for key in ("ROS_HOME", "ROS_LOG_DIR"):
            runtime_path = Path(str(declared_env[key])).absolute()
            if not contained(runtime_path, EXP_ROOT / "runtime"):
                raise ContractError(f"ROS_RUNTIME_PATH_ESCAPE:{key}:{runtime_path}")
            runtime_path.mkdir(parents=True, exist_ok=True)
            no_symlink_components(runtime_path)
        link = Path(str(item["workspace_link"])).absolute()
        if link.parent != WORKSPACE_LOGICAL_LINK_PARENT.absolute():
            raise ContractError(f"WORKSPACE_LINK_LOGICAL_PARENT_MISMATCH:{link}")
        name = link.name
        if not name or name in {".", ".."} or "/" in name or "\0" in name:
            raise ContractError(f"WORKSPACE_LINK_BASENAME_INVALID:{link}")
        with governed_workspace_parent() as parent_descriptor:
            try:
                leaf_info = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.symlink(
                        str(base), name, target_is_directory=True,
                        dir_fd=parent_descriptor,
                    )
                except FileExistsError:
                    leaf_info = os.stat(
                        name, dir_fd=parent_descriptor, follow_symlinks=False
                    )
                else:
                    leaf_info = os.stat(
                        name, dir_fd=parent_descriptor, follow_symlinks=False
                    )
            if not stat.S_ISLNK(leaf_info.st_mode):
                raise ContractError(f"WORKSPACE_LINK_COLLISION:{link}")
            try:
                target = os.readlink(name, dir_fd=parent_descriptor)
            except OSError as error:
                raise ContractError(
                    f"WORKSPACE_LINK_READLINK_FAILED:{link}:{error.errno}"
                ) from error
            if target != str(base):
                raise ContractError(f"WORKSPACE_LINK_TARGET_MISMATCH:{link}:{target}")
            leaf_identity = (
                int(leaf_info.st_dev), int(leaf_info.st_ino), int(leaf_info.st_mode)
            )
            os.fsync(parent_descriptor)
            final_leaf_info = os.stat(
                name, dir_fd=parent_descriptor, follow_symlinks=False
            )
            final_leaf_identity = (
                int(final_leaf_info.st_dev), int(final_leaf_info.st_ino),
                int(final_leaf_info.st_mode),
            )
            if final_leaf_identity != leaf_identity or not stat.S_ISLNK(final_leaf_info.st_mode):
                raise ContractError(f"WORKSPACE_LINK_CHANGED_DURING_PREPARE:{link}")
            if os.readlink(name, dir_fd=parent_descriptor) != str(base):
                raise ContractError(f"WORKSPACE_LINK_TARGET_CHANGED_DURING_PREPARE:{link}")


def read_stream(descriptor: int, context: str, *, maximum_bytes: int = 64 * 1024 * 1024) -> bytes:
    """Read a procfs stream without seeking and with an evidence-size ceiling."""
    chunks: list[bytes] = []
    size = 0
    while True:
        try:
            block = os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - size))
        except OSError as error:
            raise ContractError(f"PROC_READ_FAILED:{context}:{error.errno}") from error
        if not block:
            return b"".join(chunks)
        chunks.append(block)
        size += len(block)
        if size > maximum_bytes:
            raise ContractError(f"PROC_EVIDENCE_TOO_LARGE:{context}:{size}")


def read_proc_at(
    parent_descriptor: int, name: str, context: str, *, maximum_bytes: int = 16 * 1024 * 1024
) -> bytes:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=parent_descriptor)
    except OSError as error:
        raise ContractError(f"PROC_OPEN_FAILED:{context}:{error.errno}") from error
    try:
        return read_stream(descriptor, context, maximum_bytes=maximum_bytes)
    finally:
        os.close(descriptor)


def parse_proc_stat(data: bytes, expected_pid: int, context: str) -> dict[str, Any]:
    try:
        text = data.decode("ascii")
    except UnicodeError as error:
        raise ContractError(f"PROC_STAT_NONASCII:{context}") from error
    prefix, separator, suffix = text.rstrip("\n").rpartition(")")
    if separator != ")" or not prefix.startswith(f"{expected_pid} ("):
        raise ContractError(f"PROC_STAT_FORMAT:{context}")
    fields = suffix.split()
    if len(fields) < 20:
        raise ContractError(f"PROC_STAT_SHORT:{context}:{len(fields)}")
    try:
        result = {
            "pid": expected_pid, "state": fields[0], "ppid": int(fields[1]),
            "pgrp": int(fields[2]), "session": int(fields[3]),
            "start_ticks": int(fields[19]),
        }
    except (TypeError, ValueError, IndexError) as error:
        raise ContractError(f"PROC_STAT_VALUE:{context}") from error
    if result["state"] in {"Z", "X", "x"} or result["start_ticks"] <= 0:
        raise ContractError(f"PROC_NOT_LIVE:{context}:{result['state']}")
    return result


def proc_argv(pid: int) -> list[str] | None:
    try:
        data = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    return [part.decode(errors="replace") for part in data.split(b"\0") if part]


def proc_scan_identity(pid: int) -> dict[str, Any] | None:
    proc_path = Path("/proc") / str(pid)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(proc_path, flags)
    except (FileNotFoundError, ProcessLookupError, PermissionError, OSError):
        return None
    try:
        before = parse_proc_stat(read_proc_at(descriptor, "stat", f"{pid}:scan-before"), pid, str(pid))
        after = parse_proc_stat(read_proc_at(descriptor, "stat", f"{pid}:scan-after"), pid, str(pid))
        return before if before == after else None
    except ContractError:
        return None
    finally:
        os.close(descriptor)


def stable_proc_presence_after_failure(pid: int) -> dict[str, Any] | None:
    """Return a stable current identity, or None only after an exact absent open."""
    proc_path = Path("/proc") / str(pid)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    last_error: BaseException | None = None
    for attempt in (1, 2):
        try:
            descriptor = os.open(proc_path, flags)
        except OSError as error:
            if error.errno in {errno.ENOENT, errno.ESRCH}:
                return None
            raise ContractError(
                f"PROC_PRESENCE_RECHECK_OPEN_FAILED:{pid}:{attempt}:{error.errno}"
            ) from error
        try:
            try:
                before = parse_proc_stat(
                    read_proc_at(descriptor, "stat", f"{pid}:presence-{attempt}-before"),
                    pid, str(pid),
                )
                after = parse_proc_stat(
                    read_proc_at(descriptor, "stat", f"{pid}:presence-{attempt}-after"),
                    pid, str(pid),
                )
            except ContractError as error:
                last_error = error
                continue
            if before == after:
                return before
            last_error = ContractError(f"PROC_PRESENCE_IDENTITY_CHANGED:{pid}:{attempt}")
        finally:
            os.close(descriptor)
    raise ContractError(
        f"PROC_PRESENCE_RECHECK_UNSTABLE:{pid}:{type(last_error).__name__}:{last_error}"
    )


def parse_nul_argv(data: bytes, pid: int) -> list[str]:
    if not data or not data.endswith(b"\0"):
        raise ContractError(f"ROSOUT_CMDLINE_NOT_NUL_TERMINATED:{pid}")
    raw_values = data[:-1].split(b"\0")
    if any(not value for value in raw_values):
        raise ContractError(f"ROSOUT_CMDLINE_EMPTY_ARGUMENT:{pid}")
    try:
        return [value.decode("utf-8") for value in raw_values]
    except UnicodeError as error:
        raise ContractError(f"ROSOUT_CMDLINE_NONUTF8:{pid}") from error


def parse_nul_environment(data: bytes, pid: int) -> dict[bytes, bytes]:
    if not data or not data.endswith(b"\0"):
        raise ContractError(f"ROSOUT_ENVIRON_NOT_NUL_TERMINATED:{pid}")
    result: dict[bytes, bytes] = {}
    for record in data[:-1].split(b"\0"):
        key, separator, value = record.partition(b"=")
        if separator != b"=" or not key or b"\0" in key or key in result:
            raise ContractError(f"ROSOUT_ENVIRON_RECORD_INVALID:{pid}")
        result[key] = value
    return result


def required_environment_text(
    environment: Mapping[bytes, bytes], name: str, pid: int, *, allow_missing: bool = False
) -> str | None:
    raw = environment.get(name.encode())
    if raw is None:
        if allow_missing:
            return None
        raise ContractError(f"ROSOUT_ENVIRON_KEY_MISSING:{pid}:{name}")
    try:
        return raw.decode("utf-8")
    except UnicodeError as error:
        raise ContractError(f"ROSOUT_ENVIRON_VALUE_NONUTF8:{pid}:{name}") from error


def absolute_environment_path(value: str, pid: int, context: str) -> Path:
    path = Path(value)
    if not value or not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContractError(f"ROSOUT_PATH_INVALID:{pid}:{context}:{value!r}")
    return path.absolute()


def formal_output_roots() -> tuple[Path, ...]:
    roots = {EXP_ROOT.absolute(), *(path.absolute() for path in OUTPUT_DIRS.values())}
    roots.update(path.absolute() for path in WORKSPACE_LINKS.values())
    roots.update((WORKSPACE_REAL_LINK_PARENT / path.name).absolute() for path in WORKSPACE_LINKS.values())
    resolved: set[Path] = set()
    for root in roots:
        try:
            resolved.add(root.resolve(strict=False))
        except (OSError, RuntimeError) as error:
            raise ContractError(f"FORMAL_OUTPUT_ROOT_RESOLVE_FAILED:{root}:{error}") from error
    return tuple(sorted(roots | resolved, key=str))


def reject_path_in_formal_output(path: Path, pid: int, context: str) -> None:
    candidates = {path.absolute()}
    try:
        candidates.add(path.resolve(strict=False))
    except (OSError, RuntimeError) as error:
        raise ContractError(f"ROSOUT_PATH_RESOLVE_FAILED:{pid}:{context}:{path}:{error}") from error
    for candidate in candidates:
        for root in formal_output_roots():
            if contained(candidate, root):
                raise ContractError(
                    f"ROSOUT_PATH_ENTERS_FORMAL_OUTPUT:{pid}:{context}:{candidate}:{root}"
                )


def master_endpoint_evidence(uri: str, pid: int) -> dict[str, Any]:
    try:
        parsed = urlsplit(uri)
        host = parsed.hostname
        port = parsed.port
    except ValueError as error:
        raise ContractError(f"ROSOUT_MASTER_URI_INVALID:{pid}:{uri!r}") from error
    if (
        parsed.scheme != "http" or not host or port is None
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        or not 1 <= port <= 65535
    ):
        raise ContractError(f"ROSOUT_MASTER_URI_INVALID:{pid}:{uri!r}")
    if port in FORMAL_ROS_PORTS:
        raise ContractError(f"ROSOUT_MASTER_USES_FORMAL_PORT:{pid}:{port}")
    try:
        address_rows = socket.getaddrinfo(host, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as error:
        raise ContractError(f"ROSOUT_MASTER_RESOLUTION_FAILED:{pid}:{host}:{error.errno}") from error
    endpoints: dict[tuple[int, str], tuple[Any, ...]] = {}
    for family, socktype, protocol, _canonname, sockaddr in address_rows:
        if socktype != socket.SOCK_STREAM or family not in {socket.AF_INET, socket.AF_INET6}:
            continue
        address = str(sockaddr[0])
        try:
            loopback = ipaddress.ip_address(address).is_loopback
        except ValueError as error:
            raise ContractError(f"ROSOUT_MASTER_ADDRESS_INVALID:{pid}:{address}") from error
        if not loopback:
            raise ContractError(f"ROSOUT_MASTER_NOT_LOOPBACK:{pid}:{address}")
        endpoints[(family, address)] = tuple(sockaddr)
    if not endpoints:
        raise ContractError(f"ROSOUT_MASTER_NO_LOOPBACK_ADDRESS:{pid}:{host}")
    probes: list[dict[str, Any]] = []
    for (family, address), sockaddr in sorted(endpoints.items(), key=lambda row: (row[0][0], row[0][1])):
        probe = socket.socket(family, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.20)
            result = probe.connect_ex(sockaddr)
        except OSError as error:
            result = int(error.errno or -1)
        finally:
            probe.close()
        probes.append({
            "family": "AF_INET6" if family == socket.AF_INET6 else "AF_INET",
            "address": address, "port": port, "connect_errno": result,
            "connect_error": errno.errorcode.get(result, "UNKNOWN"),
        })
        # On a loopback address a truly absent listener rejects immediately.
        # Timeouts and all other ambiguous outcomes fail closed.
        if result != errno.ECONNREFUSED:
            raise ContractError(
                f"ROSOUT_MASTER_ENDPOINT_NOT_PROVEN_UNREACHABLE:{pid}:{address}:{port}:{result}"
            )
    return {
        "uri": uri, "hostname": host, "port": port,
        "resolved_addresses": [
            {"family": row["family"], "address": row["address"]} for row in probes
        ],
        "unreachable_probes": probes,
    }


TCP_STATES = {
    "01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV",
    "04": "FIN_WAIT1", "05": "FIN_WAIT2", "06": "TIME_WAIT",
    "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK",
    "0A": "LISTEN", "0B": "CLOSING", "0C": "NEW_SYN_RECV",
}
FORBIDDEN_TCP_STATES = frozenset({"01", "02", "03", "0C"})


def network_namespace_identity(proc_descriptor: int, pid: int, context: str) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        namespace_descriptor = os.open("ns", flags, dir_fd=proc_descriptor)
    except OSError as error:
        raise ContractError(f"ROSOUT_NETNS_DIR_OPEN_FAILED:{pid}:{context}:{error.errno}") from error
    try:
        try:
            target = os.readlink("net", dir_fd=namespace_descriptor)
            info = os.stat("net", dir_fd=namespace_descriptor, follow_symlinks=True)
        except OSError as error:
            raise ContractError(f"ROSOUT_NETNS_READ_FAILED:{pid}:{context}:{error.errno}") from error
        if not re.fullmatch(r"net:\[\d+\]", target):
            raise ContractError(f"ROSOUT_NETNS_TARGET_INVALID:{pid}:{context}:{target!r}")
        return {"target": target, "device": info.st_dev, "inode": info.st_ino}
    finally:
        os.close(namespace_descriptor)


def matching_network_namespace(proc_descriptor: int, pid: int) -> dict[str, Any]:
    target = network_namespace_identity(proc_descriptor, pid, "target")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        self_descriptor = os.open(Path("/proc") / str(os.getpid()), flags)
    except OSError as error:
        raise ContractError(f"SUPERVISOR_PROC_SELF_OPEN_FAILED:{pid}:{error.errno}") from error
    try:
        supervisor = network_namespace_identity(self_descriptor, os.getpid(), "supervisor")
    finally:
        os.close(self_descriptor)
    if target != supervisor:
        raise ContractError(
            f"ROSOUT_NETWORK_NAMESPACE_MISMATCH:{pid}:target={target}:supervisor={supervisor}"
        )
    return target


def socket_inode_set(proc_descriptor: int, pid: int) -> set[int]:
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd_descriptor = os.open("fd", flags, dir_fd=proc_descriptor)
    except OSError as error:
        raise ContractError(f"ROSOUT_FD_DIR_OPEN_FAILED:{pid}:{error.errno}") from error
    try:
        result: set[int] = set()
        for name in os.listdir(fd_descriptor):
            if not name.isdigit():
                raise ContractError(f"ROSOUT_FD_NAME_INVALID:{pid}:{name!r}")
            try:
                target = os.readlink(name, dir_fd=fd_descriptor)
            except FileNotFoundError:
                continue
            except OSError as error:
                raise ContractError(f"ROSOUT_FD_READLINK_FAILED:{pid}:{name}:{error.errno}") from error
            match = re.fullmatch(r"socket:\[(\d+)\]", target)
            if match:
                result.add(int(match.group(1)))
        return result
    finally:
        os.close(fd_descriptor)


def network_port(encoded: str, pid: int, context: str) -> int:
    try:
        _address, port = encoded.rsplit(":", 1)
        value = int(port, 16)
    except (ValueError, IndexError) as error:
        raise ContractError(f"ROSOUT_SOCKET_ADDRESS_INVALID:{pid}:{context}:{encoded}") from error
    if not 0 <= value <= 65535:
        raise ContractError(f"ROSOUT_SOCKET_PORT_INVALID:{pid}:{context}:{value}")
    return value


def socket_table_rows(
    net_descriptor: int, pid: int, socket_inodes: set[int], pass_number: int
) -> list[dict[str, Any]]:
    entries: dict[int, dict[str, Any]] = {}
    for protocol in ("tcp", "tcp6", "udp", "udp6"):
        data = read_proc_at(
            net_descriptor, protocol, f"{pid}:net:{protocol}:pass{pass_number}"
        )
        try:
            lines = data.decode("ascii").splitlines()
        except UnicodeError as error:
            raise ContractError(f"ROSOUT_NET_NONASCII:{pid}:{protocol}:pass{pass_number}") from error
        if not lines or "local_address" not in lines[0]:
            raise ContractError(f"ROSOUT_NET_HEADER_INVALID:{pid}:{protocol}:pass{pass_number}")
        for line_number, line in enumerate(lines[1:], start=2):
            fields = line.split()
            if len(fields) < 10:
                raise ContractError(
                    f"ROSOUT_NET_ROW_SHORT:{pid}:{protocol}:{pass_number}:{line_number}"
                )
            try:
                inode = int(fields[9])
            except ValueError as error:
                raise ContractError(
                    f"ROSOUT_NET_INODE_INVALID:{pid}:{protocol}:{pass_number}:{line_number}"
                ) from error
            if inode not in socket_inodes:
                continue
            local_port = network_port(fields[1], pid, f"{protocol}:local")
            remote_port = network_port(fields[2], pid, f"{protocol}:remote")
            state_code = fields[3].upper()
            if protocol.startswith("tcp") and state_code in FORBIDDEN_TCP_STATES:
                raise ContractError(
                    f"ROSOUT_SOCKET_CONNECTED_OR_SYN:{pid}:{protocol}:{inode}:"
                    f"{TCP_STATES.get(state_code, state_code)}:pass{pass_number}"
                )
            if local_port in FORMAL_ROS_PORTS or remote_port in FORMAL_ROS_PORTS:
                raise ContractError(
                    f"ROSOUT_SOCKET_USES_FORMAL_PORT:{pid}:{protocol}:{inode}:"
                    f"{local_port}:{remote_port}:pass{pass_number}"
                )
            if inode in entries:
                raise ContractError(f"ROSOUT_SOCKET_DUPLICATE_TABLE_ROW:{pid}:{inode}")
            entries[inode] = {
                "inode": inode, "protocol": protocol,
                "state_code": state_code,
                "state": TCP_STATES.get(state_code, state_code),
                "local_port": local_port, "remote_port": remote_port,
            }
    unix_data = read_proc_at(net_descriptor, "unix", f"{pid}:net:unix:pass{pass_number}")
    try:
        unix_lines = unix_data.decode("ascii").splitlines()
    except UnicodeError as error:
        raise ContractError(f"ROSOUT_NET_NONASCII:{pid}:unix:pass{pass_number}") from error
    if not unix_lines or "Inode" not in unix_lines[0]:
        raise ContractError(f"ROSOUT_NET_HEADER_INVALID:{pid}:unix:pass{pass_number}")
    for line_number, line in enumerate(unix_lines[1:], start=2):
        fields = line.split()
        if len(fields) < 7:
            raise ContractError(
                f"ROSOUT_NET_ROW_SHORT:{pid}:unix:{pass_number}:{line_number}"
            )
        try:
            inode = int(fields[6])
        except ValueError as error:
            raise ContractError(
                f"ROSOUT_NET_INODE_INVALID:{pid}:unix:{pass_number}:{line_number}"
            ) from error
        if inode not in socket_inodes:
            continue
        if inode in entries:
            raise ContractError(f"ROSOUT_SOCKET_DUPLICATE_TABLE_ROW:{pid}:{inode}")
        entries[inode] = {
            "inode": inode, "protocol": "unix", "state_code": fields[5],
            "state": fields[5], "local_port": None, "remote_port": None,
        }
    if set(entries) != socket_inodes:
        raise ContractError(
            f"ROSOUT_SOCKET_UNACCOUNTED:{pid}:pass{pass_number}:"
            f"missing={sorted(socket_inodes-set(entries))}:"
            f"extra={sorted(set(entries)-socket_inodes)}"
        )
    return sorted(entries.values(), key=lambda row: (row["inode"], row["protocol"]))


def socket_evidence(proc_descriptor: int, pid: int) -> dict[str, Any]:
    before = socket_inode_set(proc_descriptor, pid)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        net_descriptor = os.open("net", flags, dir_fd=proc_descriptor)
    except OSError as error:
        raise ContractError(f"ROSOUT_NET_DIR_OPEN_FAILED:{pid}:{error.errno}") from error
    try:
        first_rows = socket_table_rows(net_descriptor, pid, before, 1)
        middle = socket_inode_set(proc_descriptor, pid)
        if before != middle:
            raise ContractError(
                f"ROSOUT_SOCKET_SET_CHANGED_AFTER_FIRST_TABLE:{pid}:"
                f"before={sorted(before)}:middle={sorted(middle)}"
            )
        second_rows = socket_table_rows(net_descriptor, pid, middle, 2)
    finally:
        os.close(net_descriptor)
    after = socket_inode_set(proc_descriptor, pid)
    if before != middle or middle != after:
        raise ContractError(
            f"ROSOUT_SOCKET_SET_CHANGED_DURING_INSPECTION:{pid}:"
            f"before={sorted(before)}:middle={sorted(middle)}:after={sorted(after)}"
        )
    if first_rows != second_rows:
        raise ContractError(
            f"ROSOUT_SOCKET_TABLE_CHANGED_DURING_INSPECTION:{pid}:"
            f"first={compact_json_sha256(first_rows)}:second={compact_json_sha256(second_rows)}"
        )
    return {
        "count": len(first_rows), "sha256": compact_json_sha256(first_rows),
        "validated_table_passes": 2, "entries": first_rows,
    }


def running_executable_evidence(
    proc_descriptor: int, pid: int, expected: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        link_target = os.readlink("exe", dir_fd=proc_descriptor)
    except OSError as error:
        raise ContractError(f"ROSOUT_EXE_READLINK_FAILED:{pid}:{error.errno}") from error
    expected_path = str(expected.get("path", ""))
    if link_target != expected_path:
        raise ContractError(f"ROSOUT_EXE_PATH_MISMATCH:{pid}:{link_target}:{expected_path}")
    try:
        descriptor = os.open("exe", os.O_RDONLY | os.O_CLOEXEC, dir_fd=proc_descriptor)
    except OSError as error:
        raise ContractError(f"ROSOUT_EXE_OPEN_FAILED:{pid}:{error.errno}") from error
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ContractError(f"ROSOUT_EXE_NOT_REGULAR:{pid}")
        data = read_all(descriptor)
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in fields):
            raise ContractError(f"ROSOUT_EXE_CHANGED_WHILE_HASHING:{pid}")
        result = {
            "path": link_target, "size_bytes": before.st_size,
            "sha256": hashlib.sha256(data).hexdigest(), "device": before.st_dev,
            "inode": before.st_ino, "mtime_ns": before.st_mtime_ns,
            "ctime_ns": before.st_ctime_ns,
        }
        for key in ("path", "size_bytes", "sha256", "device", "inode", "mtime_ns", "ctime_ns"):
            if result[key] != expected.get(key):
                raise ContractError(f"ROSOUT_RUNNING_EXE_IDENTITY_MISMATCH:{pid}:{key}")
        return result
    finally:
        os.close(descriptor)


def inspect_masterless_rosout(
    pid: int, expected_executable: Mapping[str, Any]
) -> dict[str, Any]:
    proc_path = Path("/proc") / str(pid)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    try:
        proc_descriptor = os.open(proc_path, flags)
    except OSError as error:
        raise ContractError(f"ROSOUT_PROC_OPEN_FAILED:{pid}:{error.errno}") from error
    identity_before: dict[str, Any] | None = None
    try:
        proc_info = os.fstat(proc_descriptor)
        if proc_info.st_uid != os.getuid():
            raise ContractError(f"ROSOUT_UID_MISMATCH:{pid}:{proc_info.st_uid}:{os.getuid()}")
        identity_before = parse_proc_stat(
            read_proc_at(proc_descriptor, "stat", f"{pid}:stat-before"), pid, str(pid)
        )
        executable = running_executable_evidence(proc_descriptor, pid, expected_executable)
        cmdline_raw = read_proc_at(proc_descriptor, "cmdline", f"{pid}:cmdline")
        argv = parse_nul_argv(cmdline_raw, pid)
        if len(argv) != 3 or argv[0] != executable["path"] or argv.count("__name:=rosout") != 1:
            raise ContractError(f"ROSOUT_ARGV_NOT_EXACT_STANDALONE:{pid}:{argv!r}")
        log_tokens = [value for value in argv if value.startswith("__log:=")]
        if len(log_tokens) != 1:
            raise ContractError(f"ROSOUT_LOG_REMAP_INVALID:{pid}:{argv!r}")
        log_path = absolute_environment_path(log_tokens[0].split(":=", 1)[1], pid, "__log")
        environ_raw = read_proc_at(proc_descriptor, "environ", f"{pid}:environ")
        environment = parse_nul_environment(environ_raw, pid)
        master_uri = required_environment_text(environment, "ROS_MASTER_URI", pid)
        assert master_uri is not None
        network_namespace = matching_network_namespace(proc_descriptor, pid)
        master_before = master_endpoint_evidence(master_uri, pid)
        home = required_environment_text(environment, "HOME", pid)
        assert home is not None
        home_path = absolute_environment_path(home, pid, "HOME")
        ros_home_env = required_environment_text(environment, "ROS_HOME", pid, allow_missing=True)
        ros_log_dir_env = required_environment_text(environment, "ROS_LOG_DIR", pid, allow_missing=True)
        ros_home = (
            absolute_environment_path(ros_home_env, pid, "ROS_HOME")
            if ros_home_env not in {None, ""} else (home_path / ".ros").absolute()
        )
        ros_log_dir = (
            absolute_environment_path(ros_log_dir_env, pid, "ROS_LOG_DIR")
            if ros_log_dir_env not in {None, ""} else (ros_home / "log").absolute()
        )
        try:
            cwd_text = os.readlink("cwd", dir_fd=proc_descriptor)
        except OSError as error:
            raise ContractError(f"ROSOUT_CWD_READLINK_FAILED:{pid}:{error.errno}") from error
        cwd = absolute_environment_path(cwd_text, pid, "cwd")
        for context, path in (
            ("cwd", cwd), ("ROS_HOME", ros_home), ("ROS_LOG_DIR", ros_log_dir),
            ("__log", log_path),
        ):
            reject_path_in_formal_output(path, pid, context)
        sockets = socket_evidence(proc_descriptor, pid)
        executable_after = running_executable_evidence(
            proc_descriptor, pid, expected_executable
        )
        cmdline_raw_after = read_proc_at(
            proc_descriptor, "cmdline", f"{pid}:cmdline-after"
        )
        environ_raw_after = read_proc_at(
            proc_descriptor, "environ", f"{pid}:environ-after"
        )
        try:
            cwd_text_after = os.readlink("cwd", dir_fd=proc_descriptor)
        except OSError as error:
            raise ContractError(f"ROSOUT_CWD_REREAD_FAILED:{pid}:{error.errno}") from error
        network_namespace_probe_before = matching_network_namespace(proc_descriptor, pid)
        master_after = master_endpoint_evidence(master_uri, pid)
        network_namespace_after = matching_network_namespace(proc_descriptor, pid)
        identity_after = parse_proc_stat(
            read_proc_at(proc_descriptor, "stat", f"{pid}:stat-after"), pid, str(pid)
        )
        proc_info_after = os.fstat(proc_descriptor)
        master_stable_fields = ("uri", "hostname", "port", "resolved_addresses")
        if (
            identity_before != identity_after
            or (proc_info.st_dev, proc_info.st_ino, proc_info.st_uid)
            != (proc_info_after.st_dev, proc_info_after.st_ino, proc_info_after.st_uid)
            or executable != executable_after
            or cmdline_raw != cmdline_raw_after
            or environ_raw != environ_raw_after
            or cwd_text != cwd_text_after
            or network_namespace != network_namespace_probe_before
            or network_namespace != network_namespace_after
            or any(master_before[key] != master_after[key] for key in master_stable_fields)
        ):
            raise ContractError(f"ROSOUT_IDENTITY_CHANGED_DURING_INSPECTION:{pid}")
        master = {
            key: master_before[key] for key in ("uri", "hostname", "port", "resolved_addresses")
        }
        master["unreachable_probes_before"] = master_before["unreachable_probes"]
        master["unreachable_probes_after"] = master_after["unreachable_probes"]
        evidence: dict[str, Any] = {
            **identity_before, "uid": proc_info.st_uid,
            "procfs_device": proc_info.st_dev, "procfs_inode": proc_info.st_ino,
            "network_namespace": network_namespace, "executable": executable,
            "argv": argv, "argv_sha256": hashlib.sha256(cmdline_raw).hexdigest(),
            "environment_sha256": hashlib.sha256(environ_raw).hexdigest(),
            "ros_master_uri": master_uri, "master_endpoint": master,
            "ros_home_environment": ros_home_env,
            "effective_ros_home": str(ros_home),
            "ros_log_dir_environment": ros_log_dir_env,
            "effective_ros_log_dir": str(ros_log_dir),
            "cwd": str(cwd), "log_path": str(log_path), "sockets": sockets,
        }
        binding = {
            key: evidence[key] for key in (
                "pid", "start_ticks", "uid", "ppid", "pgrp", "session",
                "procfs_device", "procfs_inode", "network_namespace", "executable",
                "argv_sha256", "environment_sha256", "ros_master_uri",
                "ros_home_environment", "effective_ros_home",
                "ros_log_dir_environment", "effective_ros_log_dir", "cwd", "log_path",
            )
        }
        binding["resolved_master_addresses"] = master["resolved_addresses"]
        evidence["binding"] = binding
        evidence["binding_sha256"] = compact_json_sha256(binding)
        return evidence
    except ContractError as error:
        if identity_before is not None and rosout_error_is_explicit_disappearance_io(error):
            # The caller may treat a later exact absence as benign only when
            # this very inspection had already bound the frozen start time.
            error.rosout_inspected_start_ticks = int(identity_before["start_ticks"])
        raise
    finally:
        os.close(proc_descriptor)


def rosout_candidate(pid: int, argv: Sequence[str] | None) -> bool:
    if argv and any(Path(value).name.lower() == "rosout" for value in argv):
        return True
    proc = Path("/proc") / str(pid)
    try:
        if (proc / "comm").read_text().strip().lower() == "rosout":
            return True
    except (OSError, UnicodeError):
        pass
    try:
        target = os.readlink(proc / "exe")
    except OSError:
        return False
    if target.endswith(" (deleted)"):
        target = target[:-10]
    return Path(target).name.lower() == "rosout"


ROSOUT_DISAPPEARANCE_IO_PREFIXES = (
    "ROSOUT_PROC_OPEN_FAILED:", "PROC_OPEN_FAILED:", "PROC_READ_FAILED:",
    "ROSOUT_EXE_READLINK_FAILED:", "ROSOUT_EXE_OPEN_FAILED:",
    "ROSOUT_CWD_READLINK_FAILED:", "ROSOUT_CWD_REREAD_FAILED:",
    "ROSOUT_FD_DIR_OPEN_FAILED:", "ROSOUT_FD_READLINK_FAILED:",
    "ROSOUT_NET_DIR_OPEN_FAILED:", "ROSOUT_NETNS_DIR_OPEN_FAILED:",
    "ROSOUT_NETNS_READ_FAILED:",
)


def rosout_error_is_explicit_disappearance_io(error: ContractError) -> bool:
    """Allow disappearance only for a target-proc I/O ENOENT/ESRCH, never policy rejection."""
    text = str(error)
    if not text.startswith(ROSOUT_DISAPPEARANCE_IO_PREFIXES):
        return False
    try:
        error_number = int(text.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        return False
    return error_number in {errno.ENOENT, errno.ESRCH}


def rosout_baseline_record(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pid": int(evidence["pid"]), "start_ticks": int(evidence["start_ticks"]),
        "binding_sha256": str(evidence["binding_sha256"]),
        "binding": dict(evidence["binding"]),
    }


def validate_rosout_baseline(value: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, row in enumerate(value):
        if not isinstance(row, Mapping) or set(row) != {
            "pid", "start_ticks", "binding_sha256", "binding"
        }:
            raise ContractError(f"ROSOUT_BASELINE_SCHEMA:{index}")
        pid, start_ticks, digest, binding = (
            row["pid"], row["start_ticks"], row["binding_sha256"], row["binding"]
        )
        if (
            isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 or pid in seen
            or isinstance(start_ticks, bool) or not isinstance(start_ticks, int) or start_ticks <= 0
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or not isinstance(binding, Mapping) or compact_json_sha256(binding) != digest
            or binding.get("pid") != pid or binding.get("start_ticks") != start_ticks
        ):
            raise ContractError(f"ROSOUT_BASELINE_VALUE:{index}")
        seen.add(pid)
        result.append({
            "pid": pid, "start_ticks": start_ticks, "binding_sha256": digest,
            "binding": dict(binding),
        })
    return sorted(result, key=lambda row: row["pid"])


def reconcile_rosout_exemptions(
    qualified: Sequence[Mapping[str, Any]], inspection_failures: Sequence[Mapping[str, Any]],
    observed_starts: Mapping[int, int], baseline: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    failures = [dict(row) for row in inspection_failures]
    current = sorted((dict(row) for row in qualified), key=lambda row: int(row["pid"]))
    if baseline is None:
        baseline_rows = [rosout_baseline_record(row) for row in current]
        allowed = current
        disappeared: list[dict[str, Any]] = []
    else:
        baseline_rows = validate_rosout_baseline(baseline)
        by_pid = {int(row["pid"]): row for row in baseline_rows}
        allowed = []
        qualified_pids: set[int] = set()
        for row in current:
            pid = int(row["pid"])
            qualified_pids.add(pid)
            expected = by_pid.get(pid)
            if expected is None:
                failures.append({
                    "pid": pid, "ppid": int(row.get("ppid", -1)), "argv": row.get("argv", []),
                    "reason": "NEW_ROSOUT_NOT_IN_BEFORE_CLAIM_BASELINE",
                })
            elif (
                int(row["start_ticks"]) != int(expected["start_ticks"])
                or row.get("binding_sha256") != expected.get("binding_sha256")
            ):
                failures.append({
                    "pid": pid, "ppid": int(row.get("ppid", -1)), "argv": row.get("argv", []),
                    "reason": "BASELINE_ROSOUT_IDENTITY_OR_ENVIRONMENT_CHANGED",
                    "expected_start_ticks": expected["start_ticks"],
                    "actual_start_ticks": row.get("start_ticks"),
                    "expected_binding_sha256": expected["binding_sha256"],
                    "actual_binding_sha256": row.get("binding_sha256"),
                })
            else:
                allowed.append(row)
        failed_pids = {int(row.get("pid", -1)) for row in failures}
        disappeared = []
        for expected in baseline_rows:
            pid = int(expected["pid"])
            if pid in qualified_pids:
                continue
            observed = observed_starts.get(pid)
            if observed is None:
                disappeared.append({
                    "pid": pid, "start_ticks": expected["start_ticks"],
                    "binding_sha256": expected["binding_sha256"],
                })
            elif observed != expected["start_ticks"]:
                failures.append({
                    "pid": pid, "ppid": -1, "argv": [],
                    "reason": "EXEMPTED_ROSOUT_PID_REUSED",
                    "expected_start_ticks": expected["start_ticks"],
                    "actual_start_ticks": observed,
                })
            elif pid not in failed_pids:
                failures.append({
                    "pid": pid, "ppid": -1, "argv": [],
                    "reason": "BASELINE_ROSOUT_PRESENT_BUT_NOT_QUALIFIED",
                    "expected_start_ticks": expected["start_ticks"],
                })
    return {
        "forbidden_processes": sorted(failures, key=lambda row: (int(row.get("pid", -1)), str(row.get("reason", "")))),
        "exempted_masterless_rosout": allowed,
        "disappeared_exempted_masterless_rosout": disappeared,
        "masterless_rosout_baseline": baseline_rows,
        "masterless_rosout_baseline_sha256": compact_json_sha256(baseline_rows),
    }


def forbidden_command(argv: Sequence[str]) -> bool:
    names = [Path(value).name.lower() for value in argv]
    if any(name in ROS_NAMES for name in names):
        return True
    for index, name in enumerate(names):
        if name in {"rosbag", "rosbag.py"} and "play" in argv[index + 1:]:
            return True
    text = " ".join(argv).lower()
    return any(marker in text for marker in LEARNED_PROCESS_MARKERS)


def ambient_ros_role(argv: Sequence[str]) -> str | None:
    """Return the narrow ROS role eligible for offline postflight recording."""
    names = [Path(value).name.lower() for value in argv]
    for role in ("roscore", "rosmaster", "rosout", "vins_node"):
        if role in names:
            return role
    for index, name in enumerate(names):
        if name in {"rosbag", "rosbag.py"} and "play" in argv[index + 1:]:
            return "rosbag_play"
    return None


def offline_ambient_decision(row: Mapping[str, Any]) -> tuple[bool, str]:
    """Classify one strict-isolation hit under the recovery-only offline policy."""
    argv_value = row.get("argv")
    if (
        not isinstance(argv_value, list)
        or not all(isinstance(value, str) and value for value in argv_value)
    ):
        return False, "ARGV_NOT_A_NONEMPTY_STRING_LIST"
    role = ambient_ros_role(argv_value)
    if role not in OFFLINE_AMBIENT_ROS_ROLES:
        return False, "ROLE_NOT_ALLOWED_FOR_OFFLINE_AMBIENT_RECORDING"
    reason = str(row.get("reason", ""))
    allowed_reason = reason == "FORBIDDEN_ROS_OR_REPLAY_PROCESS" or (
        role == "rosout"
        and (
            reason == "NEW_ROSOUT_NOT_IN_BEFORE_CLAIM_BASELINE"
            or reason.startswith("ROSOUT_EXEMPTION_REJECTED:")
        )
    )
    if not allowed_reason:
        return False, "ISOLATION_REASON_NOT_ELIGIBLE"
    evidence_text = json.dumps(row, sort_keys=True, separators=(",", ":")).lower()
    if any(
        root.lower() in evidence_text
        for root in ("/home/ma/aqua-fe_ws", "/mnt/data/aqua-fe_ws")
    ):
        return False, "AQUA_FE_PATH_PRESENT"
    if any(
        re.search(rf"(?<![0-9]){port}(?![0-9])", evidence_text)
        for port in FORMAL_ROS_PORTS
    ):
        return False, "FORMAL_ROS_PORT_PRESENT"
    if any(marker in evidence_text for marker in LEARNED_PROCESS_MARKERS):
        return False, "LEARNED_PROCESS_PRESENT"
    accepted = dict(row)
    accepted["ambient_role"] = role
    return True, "UNRELATED_EXTERNAL_ROS_RECORDED_AS_AMBIENT"


def classify_postflight_processes(
    policy: str, hits: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Partition observed hits without weakening either launch-time check."""
    if policy == "strict_global_ros":
        return [], [dict(row) for row in hits]
    if policy != "offline_artifact_only":
        raise ContractError(f"UNKNOWN_ISOLATION_POLICY:{policy}")
    ambient: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    for raw_row in hits:
        row = dict(raw_row)
        allowed, decision = offline_ambient_decision(row)
        row["offline_policy_decision"] = decision
        (ambient if allowed else blocking).append(row)
    return ambient, blocking


def loopback_host_ambient_record(row: Mapping[str, Any]) -> tuple[dict[str, Any] | None, str]:
    """Return the exact inherited host binding eligible beside an isolated netns.

    Only host-side rosmaster/rosout processes may be inherited.  Active roscore,
    VINS, rosbag playback, and learned jobs remain blocking.  The child backend
    cannot communicate with these inherited processes because its accepted
    artifact contract proves a fresh loopback-only network namespace.
    """
    argv_value = row.get("argv")
    if (
        not isinstance(argv_value, list)
        or not argv_value
        or not all(isinstance(value, str) and value for value in argv_value)
    ):
        return None, "ARGV_NOT_A_NONEMPTY_STRING_LIST"
    role = ambient_ros_role(argv_value)
    if role not in {"rosmaster", "rosout"}:
        return None, "ONLY_ROSMASTER_OR_ROSOUT_MAY_BE_INHERITED"
    pid, start_ticks = row.get("pid"), row.get("start_ticks")
    if (
        isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0
        or isinstance(start_ticks, bool) or not isinstance(start_ticks, int)
        or start_ticks <= 0
    ):
        return None, "PROCESS_IDENTITY_NOT_STABLE"
    evidence_text = json.dumps(row, sort_keys=True, separators=(",", ":")).lower()
    if any(
        root in evidence_text for root in (
            "/home/ma/aqua-fe_ws", "/mnt/data/aqua-fe_ws",
            FORBIDDEN_WORKSPACE.lower(),
        )
    ):
        return None, "GOVERNED_OR_FORBIDDEN_PATH_PRESENT"
    if any(
        re.search(rf"(?<![0-9]){port}(?![0-9])", evidence_text)
        for port in FORMAL_ROS_PORTS
    ):
        return None, "FORMAL_NETNS_PORT_PRESENT_ON_HOST"
    if any(marker in evidence_text for marker in LEARNED_PROCESS_MARKERS):
        return None, "LEARNED_PROCESS_PRESENT"
    return {
        "pid": pid,
        "start_ticks": start_ticks,
        "role": role,
        "argv": list(argv_value),
        "argv_sha256": compact_json_sha256(list(argv_value)),
    }, "EXACT_INHERITED_HOST_ROS_BINDING"


def reconcile_loopback_host_ambient(
    hits: Sequence[Mapping[str, Any]], baseline: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    blocking: list[dict[str, Any]] = []
    for raw in hits:
        row = dict(raw)
        record, decision = loopback_host_ambient_record(row)
        row["loopback_host_policy_decision"] = decision
        if record is None:
            blocking.append(row)
        else:
            accepted.append({"evidence": row, "binding": record})
    accepted.sort(key=lambda value: int(value["binding"]["pid"]))
    current_bindings = [dict(value["binding"]) for value in accepted]
    if baseline is None:
        baseline_rows = current_bindings
        disappeared: list[dict[str, Any]] = []
    else:
        if not isinstance(baseline, Sequence) or isinstance(baseline, (str, bytes)):
            raise ContractError("HOST_AMBIENT_BASELINE_INVALID")
        baseline_rows = [dict(row) for row in baseline]
        for index, row in enumerate(baseline_rows):
            if set(row) != {"pid", "start_ticks", "role", "argv", "argv_sha256"}:
                raise ContractError(f"HOST_AMBIENT_BASELINE_SCHEMA:{index}")
            canonical, decision = loopback_host_ambient_record({
                **row, "reason": "FORBIDDEN_ROS_OR_REPLAY_PROCESS",
            })
            if canonical != row or decision != "EXACT_INHERITED_HOST_ROS_BINDING":
                raise ContractError(f"HOST_AMBIENT_BASELINE_VALUE:{index}")
        expected = {
            (int(row["pid"]), int(row["start_ticks"])): row for row in baseline_rows
        }
        current = {
            (int(row["pid"]), int(row["start_ticks"])): row for row in current_bindings
        }
        for identity, row in current.items():
            if expected.get(identity) != row:
                evidence = next(
                    value["evidence"] for value in accepted
                    if (value["binding"]["pid"], value["binding"]["start_ticks"]) == identity
                )
                evidence["loopback_host_policy_decision"] = (
                    "NEW_OR_CHANGED_HOST_ROS_NOT_IN_BEFORE_CLAIM_BASELINE"
                )
                blocking.append(evidence)
        disappeared = [
            row for identity, row in expected.items() if identity not in current
        ]
    return {
        "ambient_nonblocking_processes": [value["evidence"] for value in accepted],
        "blocking_processes": sorted(
            blocking, key=lambda row: (int(row.get("pid", -1)), str(row.get("reason", "")))
        ),
        "host_ambient_baseline": baseline_rows,
        "host_ambient_baseline_sha256": compact_json_sha256(baseline_rows),
        "disappeared_host_ambient": disappeared,
    }


def process_isolation_snapshot(
    expected_rosout_executable: Mapping[str, Any],
    rosout_baseline: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    baseline_rows = None if rosout_baseline is None else validate_rosout_baseline(rosout_baseline)
    baseline_pids = set() if baseline_rows is None else {int(row["pid"]) for row in baseline_rows}
    baseline_start_by_pid = (
        {} if baseline_rows is None
        else {int(row["pid"]): int(row["start_ticks"]) for row in baseline_rows}
    )
    try:
        pids = sorted(
            int(entry.name) for entry in Path("/proc").iterdir()
            if entry.name.isdigit() and int(entry.name) != os.getpid()
        )
    except OSError as error:
        raise ContractError(f"PROC_ENUMERATION_FAILED:{error.errno}") from error
    observed: dict[int, dict[str, Any]] = {}
    for pid in pids:
        identity = proc_scan_identity(pid)
        if identity is not None:
            observed[pid] = identity
    qualified: list[dict[str, Any]] = []
    rosout_failures: list[dict[str, Any]] = []
    generic_hits: list[dict[str, Any]] = []
    for pid in pids:
        argv = proc_argv(pid)
        must_inspect = pid in baseline_pids or rosout_candidate(pid, argv)
        if must_inspect:
            try:
                qualified.append(inspect_masterless_rosout(pid, expected_rosout_executable))
            except ContractError as error:
                explicit_disappearance_io = rosout_error_is_explicit_disappearance_io(error)
                initially_observed_start = observed.get(pid, {}).get("start_ticks")
                try:
                    identity_after_failure = stable_proc_presence_after_failure(pid)
                except ContractError as presence_error:
                    identity = observed.get(pid, {})
                    rosout_failures.append({
                        "pid": pid, "ppid": int(identity.get("ppid", -1)),
                        "argv": argv or [],
                        "reason": (
                            f"ROSOUT_EXEMPTION_REJECTED:{type(error).__name__}:{error};"
                            f"PRESENCE_RECHECK_FAILED:{type(presence_error).__name__}:"
                            f"{presence_error}"
                        ),
                    })
                    continue
                if identity_after_failure is None:
                    observed.pop(pid, None)
                    if (
                        explicit_disappearance_io
                        and pid in baseline_pids
                        and initially_observed_start == baseline_start_by_pid[pid]
                        and getattr(error, "rosout_inspected_start_ticks", None)
                        == baseline_start_by_pid[pid]
                    ):
                        # Only an explicit target-/proc ENOENT/ESRCH followed by
                        # an exact absent re-open proves benign disappearance,
                        # and only for a member already frozen before claim.
                        continue
                    identity = {}
                else:
                    observed[pid] = identity_after_failure
                    identity = identity_after_failure
                rosout_failures.append({
                    "pid": pid, "ppid": int(identity.get("ppid", -1)), "argv": argv or [],
                    "reason": f"ROSOUT_EXEMPTION_REJECTED:{type(error).__name__}:{error}",
                })
            continue
        if argv and forbidden_command(argv):
            identity = observed.get(pid, {})
            generic_hits.append({
                "pid": pid, "ppid": int(identity.get("ppid", -1)), "argv": argv,
                "reason": "FORBIDDEN_ROS_OR_REPLAY_PROCESS",
            })
    # Close the initial-/proc-enumeration gap for every baseline PID that did
    # not produce qualified evidence.  This catches a PID that was absent at
    # enumeration but reused before reconciliation, while still allowing an
    # originally inspected baseline rosout that has truly disappeared.
    if baseline_rows is not None:
        qualified_pids = {int(row["pid"]) for row in qualified}
        for baseline_row in baseline_rows:
            pid = int(baseline_row["pid"])
            if pid in qualified_pids:
                continue
            try:
                final_identity = stable_proc_presence_after_failure(pid)
            except ContractError as error:
                rosout_failures.append({
                    "pid": pid, "ppid": int(observed.get(pid, {}).get("ppid", -1)),
                    "argv": proc_argv(pid) or [],
                    "reason": f"BASELINE_ROSOUT_FINAL_PRESENCE_RECHECK_FAILED:{error}",
                })
                continue
            if final_identity is None:
                observed.pop(pid, None)
            else:
                observed[pid] = final_identity
    reconciled = reconcile_rosout_exemptions(
        qualified, rosout_failures,
        {pid: int(row["start_ticks"]) for pid, row in observed.items()}, baseline_rows,
    )
    reconciled["forbidden_processes"] = sorted(
        generic_hits + reconciled["forbidden_processes"],
        key=lambda row: (int(row.get("pid", -1)), str(row.get("reason", ""))),
    )
    for row in reconciled["forbidden_processes"]:
        identity = observed.get(int(row.get("pid", -1)))
        if identity is not None:
            row["start_ticks"] = int(identity["start_ticks"])
    return reconciled


def check_port(port: int) -> None:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
    except OSError as error:
        raise ContractError(f"ROS_PORT_UNAVAILABLE:{port}:{error.errno}") from error
    finally:
        listener.close()


def quiescence_snapshot(
    item: Mapping[str, Any], expected_rosout_executable: Mapping[str, Any],
    rosout_baseline: Sequence[Mapping[str, Any]] | None = None,
    host_ambient_baseline: Sequence[Mapping[str, Any]] | None = None, *, phase: str,
) -> dict[str, Any]:
    isolation = process_isolation_snapshot(expected_rosout_executable, rosout_baseline)
    _argv, env = command(item)
    port: int | None = None
    port_error: str | None = None
    policy = safe_text(item.get("isolation_policy"), "quiescence.isolation_policy")
    # PORT lives inside the fresh network namespace for v4; a same-numbered
    # listener in the host namespace is neither reachable nor relevant.
    if "PORT" in env and policy != "loopback_only_network_namespace":
        port = int(env["PORT"])
        try:
            check_port(port)
        except ContractError as error:
            port_error = f"{type(error).__name__}:{error}"
    elif "PORT" in env:
        port = int(env["PORT"])
    hits = list(isolation["forbidden_processes"])
    ambient: list[dict[str, Any]] = []
    disappeared_ambient: list[dict[str, Any]] = []
    ambient_baseline_rows: list[dict[str, Any]] = []
    ambient_baseline_sha256 = compact_json_sha256([])
    if policy == "loopback_only_network_namespace":
        reconciled = reconcile_loopback_host_ambient(hits, host_ambient_baseline)
        hits = reconciled["blocking_processes"]
        ambient = reconciled["ambient_nonblocking_processes"]
        disappeared_ambient = reconciled["disappeared_host_ambient"]
        ambient_baseline_rows = reconciled["host_ambient_baseline"]
        ambient_baseline_sha256 = reconciled["host_ambient_baseline_sha256"]
    return {
        "status": "PASS" if not hits and port_error is None else "FAIL",
        "checked_at_local": now_local(), "phase": phase,
        "isolation_policy": policy,
        "forbidden_processes": hits, "port": port,
        "declared_port_error": port_error,
        "ambient_nonblocking_processes": ambient,
        "disappeared_host_ambient": disappeared_ambient,
        "host_ambient_baseline": ambient_baseline_rows,
        "host_ambient_baseline_sha256": ambient_baseline_sha256,
        "exempted_masterless_rosout": isolation["exempted_masterless_rosout"],
        "disappeared_exempted_masterless_rosout": isolation[
            "disappeared_exempted_masterless_rosout"
        ],
        "masterless_rosout_baseline": isolation["masterless_rosout_baseline"],
        "masterless_rosout_baseline_sha256": isolation[
            "masterless_rosout_baseline_sha256"
        ],
    }


def enforce_quiescence(result: Mapping[str, Any]) -> None:
    hits = result.get("forbidden_processes")
    if not isinstance(hits, list):
        raise ContractError("QUIESCENCE_SNAPSHOT_HITS_INVALID")
    if hits:
        detail = ";".join(
            f"{row.get('pid')}:{row.get('reason', '')}:{' '.join(row.get('argv', []))}"
            for row in hits if isinstance(row, Mapping)
        )
        raise ContractError(f"EXTERNAL_PROCESS_NOT_QUIESCENT:{detail}")
    port_error = result.get("declared_port_error")
    if port_error is not None:
        raise ContractError(f"DECLARED_ROS_PORT_NOT_QUIESCENT:{port_error}")
    if result.get("status") != "PASS":
        raise ContractError("QUIESCENCE_SNAPSHOT_NOT_PASS")


def check_quiescence(
    item: Mapping[str, Any], expected_rosout_executable: Mapping[str, Any],
    rosout_baseline: Sequence[Mapping[str, Any]] | None = None,
    host_ambient_baseline: Sequence[Mapping[str, Any]] | None = None, *, phase: str,
) -> dict[str, Any]:
    result = quiescence_snapshot(
        item, expected_rosout_executable, rosout_baseline,
        host_ambient_baseline, phase=phase
    )
    enforce_quiescence(result)
    return result


def group_members(pgid: int) -> list[int]:
    result: list[int] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            tail = (entry / "stat").read_text().split(")", 1)[1].split()
            if int(tail[2]) == pgid:
                result.append(int(entry.name))
        except (FileNotFoundError, PermissionError, ValueError, IndexError):
            pass
    return sorted(result)


def process_table() -> dict[int, dict[str, int | str]]:
    result: dict[int, dict[str, int | str]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            tail = (entry / "stat").read_text().split(")", 1)[1].split()
            if len(tail) < 20:
                continue
            pid = int(entry.name)
            result[pid] = {
                "pid": pid, "state": tail[0], "ppid": int(tail[1]),
                "pgrp": int(tail[2]), "session": int(tail[3]),
                "start_ticks": int(tail[19]),
            }
        except (FileNotFoundError, PermissionError, ProcessLookupError, ValueError, IndexError):
            continue
    return result


def process_identity(pid: int, table: Mapping[int, Mapping[str, Any]] | None = None) -> tuple[int, int] | None:
    row = (table or process_table()).get(pid)
    if row is None:
        return None
    return pid, int(row["start_ticks"])


def direct_child_identities(parent_pid: int) -> set[tuple[int, int]]:
    table = process_table()
    return {
        (pid, int(row["start_ticks"]))
        for pid, row in table.items() if int(row["ppid"]) == parent_pid
    }


def discover_owned_processes(
    leader: tuple[int, int], baseline_children: set[tuple[int, int]],
    known: set[tuple[int, int]],
) -> tuple[dict[int, dict[str, int | str]], set[tuple[int, int]]]:
    """Track the original tree plus descendants reparented to this subreaper."""
    table = process_table()
    alive_known = {
        identity for identity in known
        if identity[0] in table and int(table[identity[0]]["start_ticks"]) == identity[1]
    }
    owned_pids = {pid for pid, _start in alive_known}
    if leader[0] in table and int(table[leader[0]]["start_ticks"]) == leader[1]:
        owned_pids.add(leader[0])
    for pid, row in table.items():
        identity = (pid, int(row["start_ticks"]))
        if int(row["ppid"]) == os.getpid() and identity not in baseline_children:
            owned_pids.add(pid)
    changed = True
    while changed:
        changed = False
        for pid, row in table.items():
            if pid not in owned_pids and int(row["ppid"]) in owned_pids:
                owned_pids.add(pid)
                changed = True
    discovered = {(pid, int(table[pid]["start_ticks"])) for pid in owned_pids if pid in table}
    return table, alive_known | discovered


def reap_direct_children(exclude: set[int]) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    table = process_table()
    for pid, row in table.items():
        if int(row["ppid"]) != os.getpid() or pid in exclude:
            continue
        try:
            waited_pid, wait_status = os.waitpid(pid, os.WNOHANG)
        except (ChildProcessError, ProcessLookupError):
            continue
        if waited_pid:
            result.append({"pid": waited_pid, "wait_status": wait_status})
    return result


def signal_owned(
    pgid: int, owned: set[tuple[int, int]], signum: int,
    audit: dict[str, Any], label: str,
) -> None:
    try:
        os.killpg(pgid, signum)
        audit[f"{label}_group_sent"] = True
    except ProcessLookupError:
        pass
    table = process_table()
    sent: list[int] = []
    for pid, start_ticks in sorted(owned):
        row = table.get(pid)
        if row is None or int(row["start_ticks"]) != start_ticks or pid == os.getpid():
            continue
        try:
            os.kill(pid, signum)
            sent.append(pid)
        except ProcessLookupError:
            pass
    audit[f"{label}_pids"] = sorted(set(audit.get(f"{label}_pids", [])) | set(sent))


def wait_owned_empty(
    process: subprocess.Popen[bytes], pgid: int, leader: tuple[int, int],
    baseline_children: set[tuple[int, int]], known: set[tuple[int, int]],
    seconds: float | None, audit: dict[str, Any],
) -> tuple[bool, set[tuple[int, int]]]:
    deadline = None if seconds is None else time.monotonic() + seconds
    while True:
        process.poll()
        audit["adopted_reaped"].extend(
            reap_direct_children({process.pid} | {pid for pid, _ticks in baseline_children})
        )
        _table, known = discover_owned_processes(leader, baseline_children, known)
        group = group_members(pgid)
        audit["last_group_members"] = group
        audit["last_owned_identities"] = [
            {"pid": pid, "start_ticks": ticks} for pid, ticks in sorted(known)
        ]
        if not known and not group and process.returncode is not None:
            return True, known
        if deadline is not None and time.monotonic() >= deadline:
            return False, known
        time.sleep(0.1)


def drain_owned_processes(
    process: subprocess.Popen[bytes], pgid: int, leader: tuple[int, int],
    baseline_children: set[tuple[int, int]], *, normal_exit: bool,
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "pgid": pgid, "leader_identity": {"pid": leader[0], "start_ticks": leader[1]},
        "normal_exit_path": normal_exit, "baseline_child_identities": [
            {"pid": pid, "start_ticks": ticks} for pid, ticks in sorted(baseline_children)
        ],
        "term_group_sent": False, "term_pids": [], "kill_group_sent": False,
        "kill_pids": [], "adopted_reaped": [], "last_group_members": [],
        "last_owned_identities": [],
    }
    _table, known = discover_owned_processes(leader, baseline_children, {leader})
    audit["owned_before_cleanup"] = [
        {"pid": pid, "start_ticks": ticks} for pid, ticks in sorted(known)
    ]
    empty, known = wait_owned_empty(
        process, pgid, leader, baseline_children, known,
        5.0 if normal_exit else 0.0, audit,
    )
    if not empty:
        signal_owned(pgid, known, signal.SIGTERM, audit, "term")
        empty, known = wait_owned_empty(
            process, pgid, leader, baseline_children, known, 20.0, audit,
        )
    if not empty:
        signal_owned(pgid, known, signal.SIGKILL, audit, "kill")
        empty, known = wait_owned_empty(
            process, pgid, leader, baseline_children, known, 20.0, audit,
        )
    # SIGKILL can be delayed while a process is in uninterruptible kernel I/O.
    # Keep the global flock and continue draining rather than returning while an
    # owned process is alive.
    while not empty:
        signal_owned(pgid, known, signal.SIGKILL, audit, "kill")
        empty, known = wait_owned_empty(
            process, pgid, leader, baseline_children, known, 1.0, audit,
        )
    process.poll()
    if process.returncode is None:
        process.wait()
    audit["adopted_reaped"].extend(
        reap_direct_children({pid for pid, _ticks in baseline_children})
    )
    final_table, final_owned = discover_owned_processes(leader, baseline_children, known)
    final_group = group_members(pgid)
    audit.update(
        leader_reaped=process.returncode is not None,
        process_group_empty=not final_group,
        owned_descendants_empty=not final_owned,
        last_group_members=final_group,
        last_owned_identities=[
            {"pid": pid, "start_ticks": ticks} for pid, ticks in sorted(final_owned)
        ],
        final_process_table_rows=len(final_table),
    )
    return audit


def enable_subreaper() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise ContractError(f"SUBREAPER_FAILED:{ctypes.get_errno()}")


def safe_output(path: Path, base: Path) -> dict[str, Any]:
    if not contained(path, base):
        raise ContractError(f"OUTPUT_ESCAPE:{path}")
    no_symlink_components(path)
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ContractError(f"OUTPUT_NOT_REGULAR:{path}")
    value, _ = snapshot(path)
    if value["size_bytes"] <= 0:
        raise ContractError(f"OUTPUT_EMPTY:{path}")
    return value


def validate_output_tree(item: Mapping[str, Any], *, receipt_may_exist: bool = False) -> dict[str, Any]:
    base = output_dir(item)
    expected = {path.absolute() for path in output_paths(item)}
    allowed_files = expected | {base / CLAIM_NAME, base / LOG_NAME}
    if receipt_may_exist:
        allowed_files.add(base / RECEIPT_NAME)
    allowed_directories = {base}
    for path in allowed_files:
        parent = path.parent
        while parent != base:
            allowed_directories.add(parent)
            parent = parent.parent
    seen_files: set[Path] = set()
    seen_directories: set[Path] = {base}
    for root_raw, directory_names, file_names in os.walk(base, topdown=True, followlinks=False):
        root = Path(root_raw).absolute()
        no_symlink_components(root)
        for name in list(directory_names):
            path = root / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode) or path not in allowed_directories:
                raise ContractError(f"UNEXPECTED_OUTPUT_DIRECTORY:{path}")
            seen_directories.add(path)
        for name in file_names:
            path = root / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISREG(mode) or path not in allowed_files:
                raise ContractError(f"UNEXPECTED_OUTPUT_FILE:{path}")
            seen_files.add(path)
    return {
        "seen_files": sorted(str(path) for path in seen_files),
        "seen_directories": sorted(str(path) for path in seen_directories),
    }


def bag_stamps(path: Path, topic: str) -> list[int]:
    try:
        import rosbag  # type: ignore
    except ImportError as error:
        raise ContractError("ROSBAG_IMPORT_FAILED") from error
    result: list[int] = []
    try:
        with rosbag.Bag(str(path), "r") as bag:
            for _topic, message, recorded in bag.read_messages(topics=[topic]):
                stamp = message.header.stamp if hasattr(message, "header") else recorded
                result.append(int(stamp.to_nsec()))
    except BaseException as error:
        raise ContractError(f"ROSBAG_READ_FAILED:{path}:{type(error).__name__}:{error}") from error
    return result


def serialized_ros_message(message: Any) -> bytes:
    stream = io.BytesIO()
    try:
        message.serialize(stream)
    except BaseException as error:
        raise ContractError(f"ROS_MESSAGE_SERIALIZE_FAILED:{type(error).__name__}:{error}") from error
    return stream.getvalue()


def validate_rosbag_topic_equal(
    left_path: Path, right_path: Path, topic: str, expected_count: int
) -> dict[str, Any]:
    """Compare record timestamp, ROS schema and serialized payload row by row."""
    import rosbag  # type: ignore

    count = 0
    digest = hashlib.sha256()
    with rosbag.Bag(str(left_path), "r") as left_bag, rosbag.Bag(str(right_path), "r") as right_bag:
        left_iter = left_bag.read_messages(topics=[topic])
        right_iter = right_bag.read_messages(topics=[topic])
        while True:
            try:
                left_row = next(left_iter)
            except StopIteration:
                left_row = None
            try:
                right_row = next(right_iter)
            except StopIteration:
                right_row = None
            if left_row is None or right_row is None:
                if left_row is not None or right_row is not None:
                    raise ContractError(f"ROSBAG_TOPIC_EQUAL_COUNT_DIFFERS:{left_path}:{right_path}:{topic}")
                break
            left_topic, left_message, left_recorded = left_row
            right_topic, right_message, right_recorded = right_row
            count += 1
            left_payload = serialized_ros_message(left_message)
            right_payload = serialized_ros_message(right_message)
            if (
                left_topic != topic or right_topic != topic
                or left_recorded.to_nsec() != right_recorded.to_nsec()
                or getattr(left_message, "_type", None) != getattr(right_message, "_type", None)
                or getattr(left_message, "_md5sum", None) != getattr(right_message, "_md5sum", None)
                or left_payload != right_payload
            ):
                raise ContractError(f"ROSBAG_TOPIC_PAYLOAD_DIFFERS:{topic}:{count}")
            digest.update(int(left_recorded.to_nsec()).to_bytes(8, "big", signed=False))
            digest.update(len(left_payload).to_bytes(8, "big", signed=False))
            digest.update(left_payload)
    if count != expected_count:
        raise ContractError(f"ROSBAG_TOPIC_EQUAL_COUNT:{topic}:{count}:{expected_count}")
    return {"count": count, "stream_sha256": digest.hexdigest()}


def channel_map(message: Any) -> dict[str, Sequence[float]]:
    result = {str(channel.name): channel.values for channel in message.channels}
    if len(result) != len(message.channels):
        raise ContractError("POINTCLOUD_DUPLICATE_CHANNEL")
    return result


def validate_pointcloud_contract(path: Path, topic: str, declaration: Mapping[str, Any]) -> dict[str, Any]:
    import rosbag  # type: ignore

    expected_names = declaration.get("channel_names")
    if not isinstance(expected_names, list) or not all(isinstance(value, str) for value in expected_names):
        raise ContractError("POINTCLOUD_CHANNEL_CONTRACT_INVALID")
    exact_points = declaration.get("exact_points")
    allowed_sources = {int(value) for value in declaration.get("allowed_source_codes", [])}
    total_points = 0
    messages = 0
    with rosbag.Bag(str(path), "r") as bag:
        topic_info = bag.get_type_and_topic_info().topics
        exact_counts = declaration.get("exact_topic_counts")
        if exact_counts is not None:
            if not isinstance(exact_counts, dict):
                raise ContractError("EXACT_TOPIC_COUNTS_INVALID")
            actual_counts = {name: int(info.message_count) for name, info in topic_info.items()}
            expected_counts = {str(name): int(count) for name, count in exact_counts.items()}
            if actual_counts != expected_counts:
                raise ContractError(f"BAG_TOPIC_COUNTS_MISMATCH:{path}:{actual_counts}:{expected_counts}")
        for read_topic, message, recorded in bag.read_messages(topics=[topic]):
            messages += 1
            if (
                read_topic != topic
                or getattr(message, "_type", None) != declaration["ros_message_type"]
                or getattr(message, "_md5sum", None) != declaration["ros_md5"]
                or message.header.frame_id != declaration["header_frame_id"]
                or int(message.header.seq) != int(declaration["header_seq"])
                or recorded.to_nsec() != message.header.stamp.to_nsec()
            ):
                raise ContractError(f"POINTCLOUD_ROS_HEADER_CONTRACT:{path}:{messages}")
            points = len(message.points)
            total_points += points
            if exact_points is not None and points != int(exact_points):
                raise ContractError(f"POINTCLOUD_POINT_COUNT:{path}:{messages}:{points}")
            if declaration.get("minimum_points") is not None and points < int(declaration["minimum_points"]):
                raise ContractError(f"POINTCLOUD_POINT_COUNT_MIN:{path}:{messages}:{points}")
            if declaration.get("maximum_points") is not None and points > int(declaration["maximum_points"]):
                raise ContractError(f"POINTCLOUD_POINT_COUNT_MAX:{path}:{messages}:{points}")
            names = [str(channel.name) for channel in message.channels]
            if names != expected_names:
                raise ContractError(f"POINTCLOUD_CHANNEL_ORDER:{path}:{messages}")
            channels = channel_map(message)
            if any(len(values) != points for values in channels.values()):
                raise ContractError(f"POINTCLOUD_CHANNEL_LENGTH:{path}:{messages}")
            for point_index, point in enumerate(message.points):
                for coordinate in (point.x, point.y, point.z):
                    finite_float(coordinate, f"pointcloud:{messages}:point:{point_index}")
                if abs(float(point.z) - float(declaration["point_z_exact"])) > 1e-6:
                    raise ContractError(f"POINTCLOUD_POINT_Z:{path}:{messages}:{point_index}")
            for name, values in channels.items():
                for point_index, value in enumerate(values):
                    finite_float(value, f"pointcloud:{messages}:{name}:{point_index}")
            sources = [
                exact_integer(value, f"pointcloud:{messages}:source_code:{index}")
                for index, value in enumerate(channels["source_code"])
            ]
            learned = [
                exact_integer(value, f"pointcloud:{messages}:is_learned:{index}")
                for index, value in enumerate(channels["is_learned"])
            ]
            ids = [
                exact_integer(value, f"pointcloud:{messages}:id:{index}")
                for index, value in enumerate(channels["id"])
            ]
            camera_ids = [
                exact_integer(value, f"pointcloud:{messages}:camera_id:{index}")
                for index, value in enumerate(channels["camera_id"])
            ]
            if len(ids) != len(set(ids)):
                raise ContractError(f"POINTCLOUD_DUPLICATE_FEATURE_ID:{path}:{messages}")
            if any(value < 0 for value in ids) or any(value != 0 for value in camera_ids):
                raise ContractError(f"POINTCLOUD_ID_OR_CAMERA_RANGE:{path}:{messages}")
            if any(value not in {0, 1} for value in learned):
                raise ContractError(f"POINTCLOUD_LEARNED_FLAG_DOMAIN:{path}:{messages}")
            if any(not 0.0 <= float(value) <= 1.0 for value in channels["quality"]):
                raise ContractError(f"POINTCLOUD_QUALITY_DOMAIN:{path}:{messages}")
            if any(float(value) <= 0.0 for value in channels["sigma"]):
                raise ContractError(f"POINTCLOUD_SIGMA_NONPOSITIVE:{path}:{messages}")
            for name, expected_value in declaration["constant_channels"].items():
                if any(abs(float(value) - float(expected_value)) > 1e-6 for value in channels[name]):
                    raise ContractError(f"POINTCLOUD_CONSTANT_CHANNEL:{path}:{messages}:{name}")
            for name, interval in declaration["half_open_channel_ranges"].items():
                low, high = float(interval[0]), float(interval[1])
                if any(not low <= float(value) < high for value in channels[name]):
                    raise ContractError(f"POINTCLOUD_HALF_OPEN_RANGE:{path}:{messages}:{name}")
            if allowed_sources and any(value not in allowed_sources for value in sources):
                raise ContractError(f"POINTCLOUD_SOURCE_CODE:{path}:{messages}")
            source_contract = declaration["source_contract"]
            for point_index, (feature_id, source, learned_value) in enumerate(zip(ids, sources, learned)):
                specification = source_contract.get(str(source))
                if specification is None or learned_value != int(specification["is_learned"]):
                    raise ContractError(f"POINTCLOUD_SOURCE_LEARNED_CONTRACT:{path}:{messages}:{point_index}")
                if feature_id < int(specification["id_min_inclusive"]):
                    raise ContractError(f"POINTCLOUD_SOURCE_ID_MIN:{path}:{messages}:{point_index}")
                if "id_max_exclusive" in specification and feature_id >= int(specification["id_max_exclusive"]):
                    raise ContractError(f"POINTCLOUD_SOURCE_ID_MAX:{path}:{messages}:{point_index}")
            if declaration.get("all_is_learned") is not None and any(
                value != int(declaration["all_is_learned"]) for value in learned
            ):
                raise ContractError(f"POINTCLOUD_LEARNED_FLAG:{path}:{messages}")
            maximum_id = declaration.get("maximum_id_exclusive")
            if maximum_id is not None and any(value >= int(maximum_id) for value in ids):
                raise ContractError(f"POINTCLOUD_ID_RANGE:{path}:{messages}")
            minimum_id = declaration.get("minimum_id_inclusive")
            if minimum_id is not None and any(value < int(minimum_id) for value in ids):
                raise ContractError(f"POINTCLOUD_ID_MIN:{path}:{messages}")
            quality_min = declaration.get("quality_min")
            quality_max = declaration.get("quality_max")
            if quality_min is not None and any(value < float(quality_min) - 1e-6 for value in channels["quality"]):
                raise ContractError(f"POINTCLOUD_QUALITY_MIN:{path}:{messages}")
            if quality_max is not None and any(value > float(quality_max) + 1e-6 for value in channels["quality"]):
                raise ContractError(f"POINTCLOUD_QUALITY_MAX:{path}:{messages}")
            if declaration.get("sigma_from_quality") is True:
                for quality, sigma_value in zip(channels["quality"], channels["sigma"]):
                    expected_sigma = 1.0 / math.sqrt(max(0.05, float(quality)))
                    if abs(float(sigma_value) - expected_sigma) > 2e-6:
                        raise ContractError(f"POINTCLOUD_SIGMA_CONTRACT:{path}:{messages}")
    return {"messages": messages, "total_points": total_points}


def validate_feature_extension(
    full_path: Path, base_path: Path, topic: str, expected_count: int
) -> dict[str, Any]:
    """Require byte-semantic KLT prefixes and at most one stable learned lineage."""
    import rosbag  # type: ignore

    added_observations = 0
    affected_frames = 0
    learned_ids: set[int] = set()
    frame_bindings: list[dict[str, Any]] = []
    count = 0
    with rosbag.Bag(str(base_path), "r") as base_bag, rosbag.Bag(str(full_path), "r") as full_bag:
        base_iter = base_bag.read_messages(topics=[topic])
        full_iter = full_bag.read_messages(topics=[topic])
        while True:
            try:
                base_row = next(base_iter)
            except StopIteration:
                base_row = None
            try:
                full_row = next(full_iter)
            except StopIteration:
                full_row = None
            if base_row is None or full_row is None:
                if base_row is not None or full_row is not None:
                    raise ContractError("FEATURE_EXTENSION_MESSAGE_COUNT_DIFFERS")
                break
            base_topic, base, base_recorded = base_row
            full_topic, full, full_recorded = full_row
            count += 1
            if (
                base_topic != topic or full_topic != topic
                or base.header != full.header or base_recorded != full_recorded
                or getattr(base, "_type", None) != getattr(full, "_type", None)
                or getattr(base, "_md5sum", None) != getattr(full, "_md5sum", None)
            ):
                raise ContractError(f"FEATURE_EXTENSION_TIMESTAMP:{count}")
            base_names = [channel.name for channel in base.channels]
            full_names = [channel.name for channel in full.channels]
            if base_names != full_names:
                raise ContractError(f"FEATURE_EXTENSION_CHANNELS:{count}")
            base_channels, full_channels = channel_map(base), channel_map(full)
            base_count, full_count = len(base.points), len(full.points)
            if full_count < base_count or full_count - base_count > 1:
                raise ContractError(f"FEATURE_EXTENSION_CARDINALITY:{count}")
            for index in range(base_count):
                if base.points[index] != full.points[index]:
                    raise ContractError(f"FEATURE_EXTENSION_POINT_PREFIX:{count}:{index}")
            for name in base_names:
                if tuple(base_channels[name]) != tuple(full_channels[name][:base_count]):
                    raise ContractError(f"FEATURE_EXTENSION_CHANNEL_PREFIX:{count}:{name}")
            added = full_count - base_count
            frame_bindings.append({
                "frame_index": count - 1,
                # The producer writes the Python float returned by
                # Time.to_sec() through csv.DictWriter.  Reproduce that exact
                # spelling so a numerically-near but different CSV stamp cannot
                # be substituted after the bags are built.
                "stamp": str(float(full.header.stamp.to_sec())),
                "injected_observations": added,
            })
            if added:
                affected_frames += 1
                added_observations += added
                index = full_count - 1
                learned_id = exact_integer(full_channels["id"][index], f"feature-extension:id:{count}")
                learned_ids.add(learned_id)
                if (
                    learned_id < 10_000_000
                    or exact_integer(full_channels["source_code"][index], f"feature-extension:source:{count}") != 20
                    or exact_integer(full_channels["is_learned"][index], f"feature-extension:learned:{count}") != 1
                ):
                    raise ContractError(f"FEATURE_EXTENSION_LEARNED_CONTRACT:{count}")
    if count != expected_count or len(learned_ids) > 1:
        raise ContractError(f"FEATURE_EXTENSION_GLOBAL_CONTRACT:{count}:{learned_ids}")
    return {
        "messages": count, "added_observations": added_observations,
        "affected_frames": affected_frames, "learned_remapped_ids": sorted(learned_ids),
        "frame_binding_sha256": compact_json_sha256(frame_bindings),
    }


def semantic_check(item: Mapping[str, Any], check: Mapping[str, Any]) -> dict[str, Any]:
    base = output_dir(item)
    path = base / str(check["path"])
    kind = str(check["type"])
    if kind == "rosbag_topic":
        topic = str(check.get("topic", ""))
        stamps = bag_stamps(path, topic)
        expected = int(check.get("count", -1))
        if len(stamps) != expected:
            raise ContractError(f"BAG_COUNT:{path}:{len(stamps)}:{expected}")
        if any(right <= left for left, right in zip(stamps, stamps[1:])):
            raise ContractError(f"BAG_TIMELINE_NOT_STRICT:{path}")
        first, last = check.get("first_stamp_ns"), check.get("last_stamp_ns")
        if first is not None and (not stamps or stamps[0] != int(first)):
            raise ContractError(f"BAG_FIRST_STAMP:{path}")
        if last is not None and (not stamps or stamps[-1] != int(last)):
            raise ContractError(f"BAG_LAST_STAMP:{path}")
        pointcloud_result = None
        if check.get("pointcloud_contract") is not None:
            contract = check["pointcloud_contract"]
            if not isinstance(contract, dict):
                raise ContractError("POINTCLOUD_CONTRACT_NOT_OBJECT")
            pointcloud_result = validate_pointcloud_contract(path, topic, contract)
        return {
            "type": kind, "path": str(path), "topic": topic, "count": len(stamps),
            "first_stamp_ns": stamps[0] if stamps else None,
            "last_stamp_ns": stamps[-1] if stamps else None,
            "pointcloud_contract": pointcloud_result, "status": "PASS",
        }
    if kind == "rosbag_timeline_equal":
        topic = str(check.get("topic", ""))
        other_raw = check.get("other_path")
        if not isinstance(other_raw, str) or not Path(other_raw).is_absolute():
            raise ContractError("BAG_OTHER_PATH_INVALID")
        other = Path(other_raw).absolute()
        left, right = bag_stamps(path, topic), bag_stamps(other, topic)
        if left != right:
            raise ContractError(f"BAG_TIMELINE_DIFFERS:{path}:{other}")
        return {"type": kind, "path": str(path), "other_path": str(other), "count": len(left), "status": "PASS"}
    if kind == "rosbag_topic_equal":
        other_raw = check.get("other_path")
        if not isinstance(other_raw, str) or not Path(other_raw).is_absolute():
            raise ContractError("BAG_OTHER_PATH_INVALID")
        topic = str(check["topic"])
        result = validate_rosbag_topic_equal(
            path, Path(other_raw).absolute(), topic, int(check["count"])
        )
        return {
            "type": kind, "path": str(path), "other_path": other_raw,
            "topic": topic, **result, "status": "PASS",
        }
    if kind == "rosbag_feature_extension":
        base_raw = check.get("base_path")
        if not isinstance(base_raw, str) or not Path(base_raw).is_absolute():
            raise ContractError("FEATURE_EXTENSION_BASE_INVALID")
        result = validate_feature_extension(
            path, Path(base_raw).absolute(), str(check.get("topic", "")),
            int(check.get("count", -1)),
        )
        return {"type": kind, "path": str(path), "base_path": base_raw, **result, "status": "PASS"}
    if kind == "csv_rows":
        required = check.get("required_columns")
        if not isinstance(required, list) or not all(isinstance(value, str) for value in required):
            raise ContractError("CSV_REQUIRED_COLUMNS_INVALID")
        with path.open("rb") as header_stream:
            header_bytes = header_stream.readline().rstrip(b"\r\n")
        expected_header_digest = check.get("exact_header_sha256")
        if expected_header_digest is not None and hashlib.sha256(header_bytes).hexdigest() != expected_header_digest:
            raise ContractError(f"CSV_HEADER_SHA256_MISMATCH:{path}")
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            if (
                reader.fieldnames is None
                or len(reader.fieldnames) != len(set(reader.fieldnames))
                or reader.fieldnames != required
            ):
                raise ContractError(f"CSV_COLUMNS:{path}")
            rows = list(reader)
        if check.get("exact_column_count") is not None and len(reader.fieldnames or []) != int(check["exact_column_count"]):
            raise ContractError(f"CSV_EXACT_COLUMN_COUNT:{path}:{len(reader.fieldnames or [])}")
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ContractError(f"CSV_ROW_WIDTH_MISMATCH:{path}")
        expected = int(check.get("count", -1))
        if len(rows) != expected:
            raise ContractError(f"CSV_COUNT:{path}:{len(rows)}:{expected}")
        arithmetic = check.get("arithmetic_columns", {})
        max_values = check.get("maximum_columns", {})
        min_values = check.get("minimum_columns", {})
        nondecreasing = check.get("nondecreasing_columns", [])
        strictly_increasing = check.get("strictly_increasing_columns", [])
        sum_columns = check.get("sum_columns", [])
        finite_columns = set(check.get("finite_numeric_columns", []))
        nullable_columns = set(check.get("nullable_numeric_columns", []))
        integer_columns = set(check.get("integer_columns", []))
        numeric_values: dict[str, list[float]] = {}
        for name in sorted(finite_columns):
            try:
                values: list[float] = []
                for row_index, row in enumerate(rows, start=2):
                    raw = row[name]
                    if raw != raw.strip():
                        raise ContractError(
                            f"CSV_NUMERIC_WHITESPACE:{path}:{row_index}:{name}"
                        )
                    values.append(finite_float(raw, f"csv:{path}:{row_index}:{name}"))
                numeric_values[name] = values
            except KeyError as error:
                raise ContractError(f"CSV_NUMERIC_COLUMN_MISSING:{path}:{name}") from error
        nullable_nan_counts: dict[str, int] = {}
        for name in sorted(nullable_columns):
            nan_count = 0
            for row_index, row in enumerate(rows, start=2):
                raw = row[name]
                if raw == "nan":
                    nan_count += 1
                    continue
                if raw != raw.strip():
                    raise ContractError(
                        f"CSV_NULLABLE_WHITESPACE:{path}:{row_index}:{name}"
                    )
                finite_float(raw, f"csv-nullable:{path}:{row_index}:{name}")
            nullable_nan_counts[name] = nan_count
        for name in integer_columns:
            for row_index, row in enumerate(rows, start=2):
                raw = row[name]
                if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", raw):
                    raise ContractError(f"CSV_INTEGER_GRAMMAR:{path}:{row_index}:{name}:{raw!r}")
                exact_integer(raw, f"csv:{path}:{row_index}:{name}")
        if not isinstance(arithmetic, dict):
            raise ContractError("CSV_ARITHMETIC_COLUMNS_INVALID")
        for name, specification in arithmetic.items():
            if not isinstance(specification, dict):
                raise ContractError("CSV_ARITHMETIC_SPEC_INVALID")
            start, step = int(specification["start"]), int(specification["step"])
            values = [
                exact_integer(row[str(name)], f"csv:{path}:{index}:{name}")
                for index, row in enumerate(rows, start=2)
            ]
            if values != [start + step * index for index in range(len(rows))]:
                raise ContractError(f"CSV_ARITHMETIC_MISMATCH:{path}:{name}")
        constants = check.get("constant_columns", {})
        if not isinstance(constants, dict):
            raise ContractError("CSV_CONSTANT_COLUMNS_INVALID")
        for name, expected_value in constants.items():
            if any(row.get(str(name)) != str(expected_value) for row in rows):
                raise ContractError(f"CSV_CONSTANT_MISMATCH:{path}:{name}")
        enum_columns = check.get("enum_columns", {})
        if not isinstance(enum_columns, dict):
            raise ContractError("CSV_ENUM_COLUMNS_INVALID")
        for name, allowed_values in enum_columns.items():
            allowed = set(allowed_values)
            for row_index, row in enumerate(rows, start=2):
                if row[name] not in allowed:
                    raise ContractError(
                        f"CSV_ENUM_MISMATCH:{path}:{row_index}:{name}:{row[name]!r}"
                    )
        histogram_columns = check.get("histogram_columns", {})
        if not isinstance(histogram_columns, dict):
            raise ContractError("CSV_HISTOGRAM_COLUMNS_INVALID")
        parsed_histograms: dict[str, list[dict[str, int]]] = {}
        for name, specification in histogram_columns.items():
            allowed_keys = set(specification["allowed_keys"])
            parsed_rows: list[dict[str, int]] = []
            for row_index, row in enumerate(rows, start=2):
                raw = row[name]
                if not raw:
                    raise ContractError(f"CSV_HISTOGRAM_EMPTY:{path}:{row_index}:{name}")
                histogram: dict[str, int] = {}
                key_order: list[str] = []
                for entry in raw.split(";"):
                    if entry.count(":") != 1:
                        raise ContractError(
                            f"CSV_HISTOGRAM_GRAMMAR:{path}:{row_index}:{name}:{raw!r}"
                        )
                    key, raw_count = entry.split(":", 1)
                    if (
                        key not in allowed_keys
                        or key in histogram
                        or not re.fullmatch(r"[1-9][0-9]*", raw_count)
                    ):
                        raise ContractError(
                            f"CSV_HISTOGRAM_ENTRY:{path}:{row_index}:{name}:{entry!r}"
                        )
                    histogram[key] = int(raw_count)
                    key_order.append(key)
                if key_order != [
                    key for key in specification["allowed_keys"] if key in histogram
                ]:
                    raise ContractError(
                        f"CSV_HISTOGRAM_KEY_ORDER:{path}:{row_index}:{name}:{raw!r}"
                    )
                target_name = specification["sum_equals_column"]
                target = exact_integer(
                    row[target_name], f"csv-histogram-target:{path}:{row_index}:{target_name}"
                )
                if sum(histogram.values()) != target:
                    raise ContractError(
                        f"CSV_HISTOGRAM_SUM:{path}:{row_index}:{name}:"
                        f"{sum(histogram.values())}:{target}"
                    )
                parsed_rows.append(histogram)
            parsed_histograms[name] = parsed_rows
        for name, specification in histogram_columns.items():
            equal_target = specification.get("equals_column")
            if equal_target is not None and parsed_histograms[name] != parsed_histograms[equal_target]:
                raise ContractError(f"CSV_HISTOGRAM_EQUALITY:{path}:{name}:{equal_target}")
        integer_list_columns = check.get("integer_list_columns", {})
        if not isinstance(integer_list_columns, dict):
            raise ContractError("CSV_INTEGER_LIST_COLUMNS_INVALID")
        for name, specification in integer_list_columns.items():
            separator = specification["separator"]
            minimum = int(specification["minimum_inclusive"])
            maximum = int(specification["maximum_exclusive"])
            for row_index, row in enumerate(rows, start=2):
                raw = row[name]
                if raw == "":
                    if specification["allow_empty"]:
                        continue
                    raise ContractError(f"CSV_INTEGER_LIST_EMPTY:{path}:{row_index}:{name}")
                fields = raw.split(separator)
                if any(not re.fullmatch(r"(?:0|[1-9][0-9]*)", value) for value in fields):
                    raise ContractError(
                        f"CSV_INTEGER_LIST_GRAMMAR:{path}:{row_index}:{name}:{raw!r}"
                    )
                values = [int(value) for value in fields]
                if any(value < minimum or value >= maximum for value in values):
                    raise ContractError(f"CSV_INTEGER_LIST_RANGE:{path}:{row_index}:{name}")
                if specification["unique"] and len(values) != len(set(values)):
                    raise ContractError(f"CSV_INTEGER_LIST_DUPLICATE:{path}:{row_index}:{name}")
        token_set_columns = check.get("token_set_columns", {})
        if not isinstance(token_set_columns, dict):
            raise ContractError("CSV_TOKEN_SET_COLUMNS_INVALID")
        for name, specification in token_set_columns.items():
            separator = specification["separator"]
            allowed = set(specification["allowed_tokens"])
            singleton_tokens = set(specification["singleton_tokens"])
            for row_index, row in enumerate(rows, start=2):
                raw = row[name]
                if raw == "":
                    if specification["allow_empty"]:
                        continue
                    raise ContractError(f"CSV_TOKEN_SET_EMPTY:{path}:{row_index}:{name}")
                tokens = raw.split(separator)
                if any(not token or token not in allowed for token in tokens):
                    raise ContractError(
                        f"CSV_TOKEN_SET_GRAMMAR:{path}:{row_index}:{name}:{raw!r}"
                    )
                if specification["unique"] and len(tokens) != len(set(tokens)):
                    raise ContractError(f"CSV_TOKEN_SET_DUPLICATE:{path}:{row_index}:{name}")
                if singleton_tokens.intersection(tokens) and len(tokens) != 1:
                    raise ContractError(f"CSV_TOKEN_SET_SINGLETON:{path}:{row_index}:{name}")
        if not isinstance(max_values, dict):
            raise ContractError("CSV_MAXIMUM_COLUMNS_INVALID")
        for name, maximum in max_values.items():
            if any(value > float(maximum) for value in numeric_values[name]):
                raise ContractError(f"CSV_MAXIMUM_MISMATCH:{path}:{name}")
        if not isinstance(min_values, dict):
            raise ContractError("CSV_MINIMUM_COLUMNS_INVALID")
        for name, minimum in min_values.items():
            if any(value < float(minimum) for value in numeric_values[name]):
                raise ContractError(f"CSV_MINIMUM_MISMATCH:{path}:{name}")
        if not isinstance(nondecreasing, list) or not all(isinstance(name, str) for name in nondecreasing):
            raise ContractError("CSV_NONDECREASING_COLUMNS_INVALID")
        for name in nondecreasing:
            values = numeric_values[name]
            if any(right < left for left, right in zip(values, values[1:])):
                raise ContractError(f"CSV_NONDECREASING_MISMATCH:{path}:{name}")
        if not isinstance(strictly_increasing, list) or not all(
            isinstance(name, str) for name in strictly_increasing
        ):
            raise ContractError("CSV_STRICTLY_INCREASING_COLUMNS_INVALID")
        for name in strictly_increasing:
            values = numeric_values[name]
            if any(right <= left for left, right in zip(values, values[1:])):
                raise ContractError(f"CSV_STRICTLY_INCREASING_MISMATCH:{path}:{name}")
        sums: dict[str, int] = {}
        if not isinstance(sum_columns, list) or not all(isinstance(name, str) for name in sum_columns):
            raise ContractError("CSV_SUM_COLUMNS_INVALID")
        for name in sum_columns:
            sums[name] = sum(
                exact_integer(row[name], f"csv:{path}:{index}:{name}")
                for index, row in enumerate(rows, start=2)
            )
        frame_binding_sha256 = None
        frame_binding = check.get("frame_binding")
        if frame_binding is not None:
            frame_name = frame_binding["frame_index_column"]
            selector_frame_name = frame_binding["selector_frame_index_column"]
            stamp_name = frame_binding["stamp_column"]
            selector_stamp_name = frame_binding["selector_stamp_column"]
            value_name = frame_binding["value_column"]
            bindings: list[dict[str, Any]] = []
            for row_index, row in enumerate(rows, start=2):
                frame_index = exact_integer(
                    row[frame_name], f"csv-frame-binding:{path}:{row_index}:{frame_name}"
                )
                selector_frame_index = exact_integer(
                    row[selector_frame_name],
                    f"csv-frame-binding:{path}:{row_index}:{selector_frame_name}",
                )
                if frame_index != selector_frame_index:
                    raise ContractError(f"CSV_FRAME_INDEX_BINDING:{path}:{row_index}")
                if row[stamp_name] != row[selector_stamp_name]:
                    raise ContractError(f"CSV_STAMP_BINDING:{path}:{row_index}")
                bindings.append({
                    "frame_index": frame_index,
                    "stamp": row[stamp_name],
                    "injected_observations": exact_integer(
                        row[value_name], f"csv-frame-binding:{path}:{row_index}:{value_name}"
                    ),
                })
            frame_binding_sha256 = compact_json_sha256(bindings)
        return {
            "type": kind, "path": str(path), "rows": len(rows),
            "governed_columns": len(required), "column_sums": sums,
            "nullable_nan_counts": nullable_nan_counts,
            "frame_binding_sha256": frame_binding_sha256, "status": "PASS",
        }
    if kind == "file_sha256":
        actual = safe_output(path, base)
        if actual["sha256"] != check.get("sha256"):
            raise ContractError(f"FILE_SHA256_MISMATCH:{path}")
        return {"type": kind, "path": str(path), "identity": actual, "status": "PASS"}
    if kind == "text_contains":
        text = path.read_text(encoding="utf-8", errors="strict")
        required_text = check.get("required_text")
        forbidden_text = check.get("forbidden_text", [])
        if not isinstance(required_text, list) or not all(isinstance(value, str) for value in required_text):
            raise ContractError("TEXT_REQUIRED_INVALID")
        if not isinstance(forbidden_text, list) or not all(isinstance(value, str) for value in forbidden_text):
            raise ContractError("TEXT_FORBIDDEN_INVALID")
        stripped_lines = {line.strip() for line in text.splitlines()}
        missing = [value for value in required_text if value.strip() not in stripped_lines]
        present = [value for value in forbidden_text if value in text]
        if missing or present:
            raise ContractError(f"TEXT_CONTRACT:{path}:missing={missing}:forbidden={present}")
        return {"type": kind, "path": str(path), "required_count": len(required_text), "status": "PASS"}
    if kind == "network_namespace_manifest":
        manifest_snapshot, payload = snapshot(path, with_data=True)
        assert payload is not None
        value = parse_json(payload, path)
        expected_keys = {
            "schema_version", "status", "isolation_scope",
            "machine_exclusive_cpu_scheduling", "uid_inside", "gid_inside",
            "self_network_namespace", "host_network_namespace",
            "self_user_namespace", "host_user_namespace", "interfaces",
            "loopback_operstate", "initial_tcp_listeners", "formal_bind_address",
            "formal_bind_port", "backend_argv_sha256",
        }
        if set(value) != expected_keys:
            raise ContractError(
                f"NETNS_MANIFEST_KEY_SET:{path}:"
                f"missing={sorted(expected_keys-set(value))}:"
                f"extra={sorted(set(value)-expected_keys)}"
            )
        expected_host_net = check["expected_host_network_namespace"]
        expected_host_user = check["expected_host_user_namespace"]
        self_net, self_user = value.get("self_network_namespace"), value.get("self_user_namespace")
        if (
            value.get("schema_version") != "aqua-fe-a10-samehistory-backend-netns-v4"
            or value.get("status") != "PASS"
            or value.get("isolation_scope") != "NETWORK_NAMESPACE_LOOPBACK_ONLY"
            or value.get("machine_exclusive_cpu_scheduling") is not False
            or value.get("uid_inside") != 0 or value.get("gid_inside") != 0
            or value.get("host_network_namespace") != expected_host_net
            or value.get("host_user_namespace") != expected_host_user
            or not isinstance(self_net, str)
            or re.fullmatch(r"net:\[[0-9]+\]", self_net) is None
            or self_net == expected_host_net
            or not isinstance(self_user, str)
            or re.fullmatch(r"user:\[[0-9]+\]", self_user) is None
            or self_user == expected_host_user
            or value.get("interfaces") != ["lo"]
            or value.get("loopback_operstate") not in {"unknown", "up"}
            or value.get("initial_tcp_listeners") != []
            or value.get("formal_bind_address") != "127.0.0.1"
            or value.get("formal_bind_port") != check["formal_port"]
            or value.get("backend_argv_sha256") != check["backend_argv_sha256"]
        ):
            raise ContractError(f"NETNS_MANIFEST_CONTRACT:{path}:{value}")
        return {
            "type": kind, "path": str(path), "identity": public(manifest_snapshot),
            "self_network_namespace": self_net, "self_user_namespace": self_user,
            "host_network_namespace": expected_host_net,
            "host_user_namespace": expected_host_user,
            "formal_bind_port": value["formal_bind_port"],
            "machine_exclusive_cpu_scheduling": False, "status": "PASS",
        }
    if kind == "ape_kv":
        values: dict[str, int | float] = {}
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        if not lines:
            raise ContractError(f"APE_EMPTY:{path}")
        for line_number, line in enumerate(lines, start=1):
            if not line or line.count("=") != 1:
                raise ContractError(f"APE_LINE_INVALID:{path}:{line_number}")
            key, raw_value = line.split("=", 1)
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) or key in values:
                raise ContractError(f"APE_KEY_INVALID_OR_DUPLICATE:{path}:{line_number}:{key}")
            values[key] = finite_float(raw_value, f"ape:{path}:{line_number}:{key}")
        required_keys = set(check["required_keys"])
        if set(values) != required_keys:
            raise ContractError(
                f"APE_KEY_SET_MISMATCH:{path}:missing={sorted(required_keys-set(values))}:"
                f"extra={sorted(set(values)-required_keys)}"
            )
        for key in check["integer_keys"]:
            values[key] = exact_integer(values[key], f"ape:{path}:{key}")
        return {"type": kind, "path": str(path), "values": values, "status": "PASS"}
    if kind == "replay_manifest":
        values: dict[str, str] = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in line:
                raise ContractError(f"MANIFEST_LINE_INVALID:{path}")
            key, value = line.split("=", 1)
            if key in values:
                raise ContractError(f"MANIFEST_DUPLICATE_KEY:{path}:{key}")
            values[key] = value
        expected_values = check.get("values")
        if not isinstance(expected_values, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in expected_values.items()
        ):
            raise ContractError("MANIFEST_EXPECTED_VALUES_INVALID")
        if values != expected_values:
            raise ContractError(f"MANIFEST_VALUES_MISMATCH:{path}:{values}")
        return {"type": kind, "path": str(path), "values": values, "status": "PASS"}
    if kind == "vins_trajectory":
        stamps: list[int] = []
        with path.open(encoding="utf-8", newline="") as stream:
            for line_number, raw_fields in enumerate(csv.reader(stream), start=1):
                fields = list(raw_fields)
                if len(fields) == 12 and fields[-1] == "":
                    fields.pop()
                if len(fields) != 11:
                    raise ContractError(f"TRAJECTORY_COLUMN_COUNT:{path}:{line_number}:{len(fields)}")
                if not re.fullmatch(r"[0-9]+", fields[0]):
                    raise ContractError(f"TRAJECTORY_TIMESTAMP_PARSE:{path}:{line_number}")
                stamps.append(int(fields[0]))
                values = [
                    finite_float(value, f"trajectory:{path}:{line_number}:{column}")
                    for column, value in enumerate(fields[1:], start=1)
                ]
                quaternion_norm = math.sqrt(sum(value * value for value in values[3:7]))
                if not 0.95 <= quaternion_norm <= 1.05:
                    raise ContractError(
                        f"TRAJECTORY_QUATERNION_NORM:{path}:{line_number}:{quaternion_norm}"
                    )
        if len(stamps) < int(check.get("min_rows", 2)):
            raise ContractError(f"TRAJECTORY_TOO_SHORT:{path}:{len(stamps)}")
        if any(right <= left for left, right in zip(stamps, stamps[1:])):
            raise ContractError(f"TRAJECTORY_NOT_STRICT:{path}")
        return {
            "type": kind, "path": str(path), "rows": len(stamps),
            "first_stamp_ns": stamps[0], "last_stamp_ns": stamps[-1], "status": "PASS",
        }
    raise ContractError(f"UNKNOWN_SEMANTIC_CHECK:{kind}")


def audit_outputs(item: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    base = output_dir(item)
    identities: dict[str, Any] = {}
    issues: list[str] = []
    checks: list[dict[str, Any]] = []
    try:
        checks.append({"type": "output_tree", **validate_output_tree(item), "status": "PASS"})
    except BaseException as error:
        issues.append(f"{type(error).__name__}:{error}")
    for path in output_paths(item):
        try:
            identities[str(path)] = safe_output(path, base)
        except BaseException as error:
            issues.append(f"{type(error).__name__}:{error}")
    if not issues:
        for declaration in item["semantic_checks"]:
            try:
                checks.append(semantic_check(item, declaration))
            except BaseException as error:
                issues.append(f"{type(error).__name__}:{error}")
    if not issues and item.get("kind") == "learned_sidecar_build":
        extension = next((row for row in checks if row.get("type") == "rosbag_feature_extension"), None)
        stats = next((row for row in checks if row.get("type") == "csv_rows"), None)
        if not isinstance(extension, dict) or not isinstance(stats, dict):
            issues.append("LEARNED_BUILD_CROSSCHECK_MISSING")
        else:
            injected = stats.get("column_sums", {}).get("selector_injected_observations")
            if injected != extension.get("added_observations"):
                issues.append(
                    f"LEARNED_BUILD_INJECTION_SUM_MISMATCH:{injected}:{extension.get('added_observations')}"
                )
            if stats.get("rows") != extension.get("messages"):
                issues.append(
                    f"LEARNED_BUILD_FRAME_COUNT_MISMATCH:"
                    f"{stats.get('rows')}:{extension.get('messages')}"
                )
            if (
                stats.get("frame_binding_sha256") is None
                or stats.get("frame_binding_sha256") != extension.get("frame_binding_sha256")
            ):
                issues.append(
                    f"LEARNED_BUILD_FRAME_BINDING_MISMATCH:"
                    f"{stats.get('frame_binding_sha256')}:"
                    f"{extension.get('frame_binding_sha256')}"
                )
    return identities, checks, issues


def strict_trajectory_stamps(path: Path) -> list[int]:
    stamps: list[int] = []
    with path.open(encoding="utf-8", newline="") as stream:
        for line_number, raw_fields in enumerate(csv.reader(stream), start=1):
            fields = list(raw_fields)
            if len(fields) == 12 and fields[-1] == "":
                fields.pop()
            if len(fields) != 11 or not re.fullmatch(r"[0-9]+", fields[0]):
                raise ContractError(f"SCORE_TRAJECTORY_ROW_INVALID:{path}:{line_number}")
            stamps.append(int(fields[0]))
            numeric = [
                finite_float(value, f"score-trajectory:{line_number}:{column}")
                for column, value in enumerate(fields[1:], start=1)
            ]
            norm = math.sqrt(sum(value * value for value in numeric[3:7]))
            if not 0.95 <= norm <= 1.05:
                raise ContractError(f"SCORE_TRAJECTORY_QUATERNION:{path}:{line_number}")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise ContractError(f"SCORE_TRAJECTORY_NOT_STRICT:{path}")
    return stamps


def parse_score_log_events(path: Path, start_ns: int, end_ns: int) -> dict[str, Any]:
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    ros_sim = re.compile(r"\[[^\],]+,\s*([0-9]+(?:\.[0-9]+)?)\]")
    plain_time = re.compile(r"\btime:\s*([0-9]+(?:\.[0-9]+)?)")
    failure_pattern = re.compile(
        r"linear solver failure|\bfail(?:ed|ure)?\b|\bfatal\b.*\btrack|"
        r"\btracking\s+(?:is\s+)?lost\b",
        re.IGNORECASE,
    )
    restart_pattern = re.compile(
        r"clear\s*state|\b(?:restart(?:ed|ing)?|reset(?:ting)?|reboot)\b",
        re.IGNORECASE,
    )
    init_pattern = re.compile(r"initialization finish", re.IGNORECASE)
    def seconds_to_ns(raw: str) -> int:
        whole, dot, fractional = raw.partition(".")
        fraction = (fractional + "000000000")[:9] if dot else "000000000"
        return int(whole) * 1_000_000_000 + int(fraction)

    parsed_lines: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), start=1
    ):
        line = ansi.sub("", raw_line)
        direct = ros_sim.search(line) or plain_time.search(line)
        parsed_lines.append({
            "line": line_number, "text": line,
            "sim_stamp_ns": seconds_to_ns(direct.group(1)) if direct is not None else None,
        })

    previous: list[int | None] = []
    latest: int | None = None
    for row in parsed_lines:
        if row["sim_stamp_ns"] is not None:
            latest = int(row["sim_stamp_ns"])
        previous.append(latest)
    following: list[int | None] = [None] * len(parsed_lines)
    latest = None
    for index in range(len(parsed_lines) - 1, -1, -1):
        if parsed_lines[index]["sim_stamp_ns"] is not None:
            latest = int(parsed_lines[index]["sim_stamp_ns"])
        following[index] = latest

    def segment(stamp: int) -> str:
        if stamp < start_ns:
            return "PREFIX"
        if stamp <= end_ns:
            return "SCORE"
        return "POST_SCORE"

    events: list[dict[str, Any]] = []
    initialization_events: list[dict[str, Any]] = []
    for index, row in enumerate(parsed_lines):
        line_number, line = int(row["line"]), str(row["text"])
        exact_stamp = row["sim_stamp_ns"]
        if exact_stamp is not None:
            attribution = segment(int(exact_stamp))
        else:
            contextual_segments = {
                segment(stamp) for stamp in (previous[index], following[index]) if stamp is not None
            }
            attribution = next(iter(contextual_segments)) if len(contextual_segments) == 1 else "UNRESOLVED"
        categories: list[str] = []
        if failure_pattern.search(line):
            categories.append("failure")
        if restart_pattern.search(line):
            categories.append("restart_or_reset")
        if init_pattern.search(line):
            initialization_events.append({
                "line": line_number, "sim_stamp_ns": exact_stamp,
                "attribution": attribution,
                "within_or_before_score_end": attribution in {"PREFIX", "SCORE"},
            })
        if categories:
            events.append({
                "line": line_number, "categories": categories,
                "sim_stamp_ns": exact_stamp, "score_attribution": attribution,
                "text_sha256": hashlib.sha256(line.encode()).hexdigest(),
            })
    score_events = [event for event in events if event["score_attribution"] == "SCORE"]
    unresolved = [event for event in events if event["score_attribution"] == "UNRESOLVED"]
    return {
        "events": events,
        "score_failure_events": sum("failure" in event["categories"] for event in score_events),
        "score_restart_or_reset_events": sum(
            "restart_or_reset" in event["categories"] for event in score_events
        ),
        "unresolved_event_count": len(unresolved),
        "initialization_events": initialization_events,
    }


def evaluate_score_usability(
    lock: Mapping[str, Any], item: Mapping[str, Any], semantic_results: Sequence[Mapping[str, Any]],
    artifact_issues: Sequence[str],
) -> dict[str, Any]:
    if item.get("kind") != "backend_replay":
        return {"status": "NOT_APPLICABLE", "failure_codes": []}
    policy = lock["score_usability"]
    start_ns, end_ns = int(policy["score_start_ns"]), int(policy["score_end_ns"])
    failures: list[str] = []
    result: dict[str, Any] = {
        "score_start_ns": start_ns, "score_end_ns": end_ns,
        "crop_interval": "inclusive", "failure_codes": failures,
    }
    if artifact_issues:
        failures.append("ARTIFACT_CONTRACT_NOT_PASS")
    try:
        trajectory_check = next(
            check for check in item["semantic_checks"] if check.get("type") == "vins_trajectory"
        )
        trajectory_path = output_dir(item) / str(trajectory_check["path"])
        all_stamps = strict_trajectory_stamps(trajectory_path)
        score_stamps = [stamp for stamp in all_stamps if start_ns <= stamp <= end_ns]
        result["full_trajectory_rows"] = len(all_stamps)
        result["score_trajectory_rows"] = len(score_stamps)
        if len(score_stamps) < 2:
            failures.append("INSUFFICIENT_SCORE_TRAJECTORY_ROWS")
            coverage = 0.0
            maximum_gap: float | None = None
            first_stamp = last_stamp = None
        else:
            first_stamp, last_stamp = score_stamps[0], score_stamps[-1]
            coverage = (last_stamp - first_stamp) / (end_ns - start_ns)
            gaps_ns = [right - left for left, right in zip(score_stamps, score_stamps[1:])]
            maximum_gap = max(gaps_ns) / 1e9
        result.update(
            score_first_stamp_ns=first_stamp, score_last_stamp_ns=last_stamp,
            score_temporal_span_coverage=coverage, maximum_score_output_gap_s=maximum_gap,
        )
        if coverage < float(policy["minimum_score_temporal_span_coverage"]):
            failures.append("SCORE_TEMPORAL_SPAN_COVERAGE_BELOW_GATE")
        if maximum_gap is None or maximum_gap > float(policy["maximum_score_output_gap_s"]):
            failures.append("SCORE_OUTPUT_GAP_ABOVE_GATE")
    except BaseException as error:
        failures.append(f"SCORE_TRAJECTORY_AUDIT_ERROR:{type(error).__name__}:{error}")

    ape = next((row for row in semantic_results if row.get("type") == "ape_kv"), None)
    ape_init_success = None
    if isinstance(ape, Mapping) and isinstance(ape.get("values"), Mapping):
        ape_init_success = ape["values"].get("init_success")
    result["ape_init_success"] = ape_init_success
    if ape_init_success != 1:
        failures.append("APE_INITIALIZATION_NOT_SUCCESSFUL")
    try:
        log_result = parse_score_log_events(output_dir(item) / "vins.log", start_ns, end_ns)
        result["log_event_audit"] = log_result
        initialized_in_time = any(
            event.get("within_or_before_score_end") is True
            for event in log_result["initialization_events"]
        )
        result["initialization_before_or_within_score_end"] = initialized_in_time
        if not initialized_in_time:
            failures.append("NO_INITIALIZATION_EVENT_BEFORE_SCORE_END")
        if log_result["score_failure_events"] > int(policy["maximum_score_failure_mentions"]):
            failures.append("SCORE_FAILURE_EVENT_GATE_EXCEEDED")
        if log_result["score_restart_or_reset_events"] > int(
            policy["maximum_score_restart_or_reset_events"]
        ):
            failures.append("SCORE_RESTART_RESET_GATE_EXCEEDED")
        if log_result["unresolved_event_count"]:
            failures.append("UNRESOLVED_LOG_EVENT_ATTRIBUTION")
    except BaseException as error:
        failures.append(f"SCORE_LOG_AUDIT_ERROR:{type(error).__name__}:{error}")
    result["failure_codes"] = failures
    result["status"] = "PASS" if not failures else "FAIL"
    return result


def effective_environment(lock: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, str]:
    result = dict(lock["policy"]["base_environment"])
    _argv, declared = command(item)
    if "PWD" in result or "PWD" in declared:
        raise ContractError("PWD_MUST_BE_SUPERVISOR_OWNED")
    overlap = set(result) & set(declared)
    if overlap:
        raise ContractError(f"ITEM_ENV_SHADOWS_BASE:{','.join(sorted(overlap))}")
    result.update(declared)
    result["PWD"] = str(ROOT)
    return result


def prelaunch_output_tree_empty(item: Mapping[str, Any]) -> None:
    base = output_dir(item)
    no_symlink_components(base)
    if not base.is_dir():
        raise ContractError(f"OUTPUT_DIR_NOT_DIRECTORY:{base}")
    entries = sorted(entry.name for entry in base.iterdir())
    if entries:
        raise ContractError(f"OUTPUT_TREE_NOT_EMPTY:{base}:{entries}")
    _argv, declared_env = command(item)
    for key in ("ROS_HOME", "ROS_LOG_DIR"):
        runtime_path = Path(declared_env[key]).absolute()
        no_symlink_components(runtime_path)
        runtime_entries = sorted(entry.name for entry in runtime_path.iterdir())
        if runtime_entries:
            raise ContractError(
                f"ROS_RUNTIME_TREE_NOT_EMPTY:{key}:{runtime_path}:{runtime_entries}"
            )


def receipt_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_snapshot, data = snapshot(path, with_data=True)
    assert data is not None
    return parse_json(data, path), receipt_snapshot


def validate_dependency(
    lock: Mapping[str, Any], lock_snapshot: Mapping[str, Any], dependency_id: str
) -> dict[str, Any]:
    dependency = lock["items"][dependency_id]
    base = output_dir(dependency)
    receipt, _receipt_snapshot = receipt_json(base / RECEIPT_NAME)
    required = {"schema_version": SCHEMA, "item_id": dependency_id, "launch_allowance_consumed": True}
    for key, expected in required.items():
        if receipt.get(key) != expected:
            raise ContractError(f"DEPENDENCY_RECEIPT_FIELD:{dependency_id}:{key}")
    terminal = receipt.get("terminal_process")
    artifact = receipt.get("artifact_contract")
    execution = receipt.get("execution_integrity")
    if not isinstance(terminal, dict) or (
        terminal.get("status") != "TERMINAL_PROCESS_RC0"
        or terminal.get("popen_invocation_count") != 1
        or terminal.get("child_started") is not True
        or terminal.get("raw_return_code") != 0
        or terminal.get("timed_out") is not False
    ):
        raise ContractError(f"DEPENDENCY_TERMINAL_PROCESS:{dependency_id}")
    if not isinstance(artifact, dict) or artifact.get("status") != "PASS":
        raise ContractError(f"DEPENDENCY_ARTIFACT_CONTRACT:{dependency_id}")
    if not isinstance(execution, dict) or execution.get("status") != "PASS":
        raise ContractError(f"DEPENDENCY_EXECUTION_INTEGRITY:{dependency_id}")
    group = terminal.get("process_group")
    if (
        not isinstance(group, dict) or not group.get("leader_reaped")
        or not group.get("process_group_empty") or not group.get("owned_descendants_empty")
    ):
        raise ContractError(f"DEPENDENCY_GROUP_NOT_DRAINED:{dependency_id}")
    if receipt.get("execution_lock") != public(lock_snapshot):
        raise ContractError(f"DEPENDENCY_LOCK_BINDING:{dependency_id}")
    claim_path = base / CLAIM_NAME
    claim_snapshot, claim_data = snapshot(claim_path, with_data=True)
    assert claim_data is not None
    claim = parse_json(claim_data, claim_path)
    argv, _env = command(dependency)
    if (
        receipt.get("claim") != public(claim_snapshot)
        or claim.get("schema_version") != SCHEMA
        or claim.get("item_id") != dependency_id
        or claim.get("execution_lock") != public(lock_snapshot)
        or claim.get("argv") != argv
        or claim.get("effective_environment") != effective_environment(lock, dependency)
        or claim.get("launch_allowance_consumed") is not True
    ):
        raise ContractError(f"DEPENDENCY_CLAIM_BINDING:{dependency_id}")
    recorded_outputs = artifact.get("outputs")
    if not isinstance(recorded_outputs, dict):
        raise ContractError(f"DEPENDENCY_OUTPUT_MAP:{dependency_id}")
    for path in output_paths(dependency):
        actual = safe_output(path, base)
        if recorded_outputs.get(str(path)) != actual:
            raise ContractError(f"DEPENDENCY_OUTPUT_CHANGED:{dependency_id}:{path}")
    return {
        "dependency_id": dependency_id,
        "receipt": _receipt_snapshot,
        "claim": claim_snapshot,
        "outputs": {str(path): safe_output(path, base) for path in output_paths(dependency)},
    }


def validate_dependencies(
    lock: Mapping[str, Any], lock_snapshot: Mapping[str, Any], item_id: str
) -> dict[str, Any]:
    return {
        dependency_id: validate_dependency(lock, lock_snapshot, dependency_id)
        for dependency_id in DEPENDENCIES[item_id]
    }


def add_error(existing: str | None, error: BaseException | str) -> str:
    text = error if isinstance(error, str) else f"{type(error).__name__}:{error}"
    return text if existing is None else f"{existing};{text}"


def terminal_process_layer(runtime: Mapping[str, Any], timeout: int) -> dict[str, Any]:
    raw_rc0 = bool(
        runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and runtime.get("raw_return_code") == 0
        and runtime.get("timed_out") is False
    )
    return {
        "status": "TERMINAL_PROCESS_RC0" if raw_rc0 else "TERMINAL_PROCESS_FAILED",
        "popen_invocation_count": runtime.get("popen_invocation_count", 0),
        "child_started": runtime.get("child_started", False),
        "pid": runtime.get("pid"), "pgid": runtime.get("pgid"),
        "leader_identity": runtime.get("leader_identity"),
        "raw_return_code": runtime.get("raw_return_code"),
        "timed_out": runtime.get("timed_out", False),
        "timeout_seconds": timeout,
        "process_group": runtime.get("process_group", {
            "pgid": None, "leader_reaped": True, "process_group_empty": True,
            "owned_descendants_empty": True,
        }),
    }


def receipt_is_accepted(receipt: Mapping[str, Any]) -> bool:
    terminal = receipt.get("terminal_process")
    artifact = receipt.get("artifact_contract")
    execution = receipt.get("execution_integrity")
    score = receipt.get("score_usability")
    accepted_layers = bool(
        isinstance(terminal, Mapping) and terminal.get("status") == "TERMINAL_PROCESS_RC0"
        and isinstance(artifact, Mapping) and artifact.get("status") == "PASS"
        and isinstance(execution, Mapping) and execution.get("status") == "PASS"
        and isinstance(score, Mapping) and score.get("status") in {"PASS", "NOT_APPLICABLE"}
    )
    if not accepted_layers or not isinstance(execution, Mapping):
        return False
    try:
        for field, phase in (
            ("v3_pending_allowance_before_claim", "before_claim"),
            ("v3_pending_allowance_before_popen", "after_claim_before_popen"),
            ("v3_pending_allowance_postflight", "postflight"),
        ):
            validate_v3_pending_guard_evidence(execution.get(field), phase=phase)
    except ContractError:
        return False
    return True


def receipt_disposition(receipt: Mapping[str, Any]) -> str:
    if receipt_is_accepted(receipt):
        return "ACCEPTED"
    terminal = receipt.get("terminal_process", {})
    execution = receipt.get("execution_integrity", {})
    artifact = receipt.get("artifact_contract", {})
    score = receipt.get("score_usability", {})
    if terminal.get("status") != "TERMINAL_PROCESS_RC0":
        return "PROCESS_FAILED"
    if execution.get("status") != "PASS":
        return "EXECUTION_INTEGRITY_FAILED"
    if artifact.get("status") != "PASS":
        return "ARTIFACT_CONTRACT_FAILED"
    if score.get("status") == "FAIL":
        return "RETAINED_UNUSABLE_SCORE"
    return "FAILED_UNCLASSIFIED"


def minimal_receipt(
    item_id: str, item: Mapping[str, Any], started_at: str,
    lock_snapshot: Mapping[str, Any], claim_path: Path,
    error: BaseException | str, runtime: Mapping[str, Any],
) -> dict[str, Any]:
    claim_identity: dict[str, Any] | None = None
    claim_rosout_exemption: dict[str, Any] = {"status": "UNAVAILABLE"}
    claim_host_ambient_exemption: dict[str, Any] = {"status": "UNAVAILABLE"}
    claim_external_sources: dict[str, Any] = {"status": "UNAVAILABLE"}
    claim_v3_pending_guard: dict[str, Any] = {"status": "UNAVAILABLE"}
    try:
        claim_snapshot, claim_data = snapshot(claim_path, with_data=True)
        claim_identity = public(claim_snapshot)
        assert claim_data is not None
        claim_value = parse_json(claim_data, claim_path)
        rosout_value = claim_value.get("masterless_rosout_exemption")
        host_value = claim_value.get("loopback_host_ambient_exemption")
        external_value = claim_value.get("external_source_bindings")
        v3_pending_value = claim_value.get("v3_pending_allowance_guard")
        if isinstance(rosout_value, dict):
            claim_rosout_exemption = dict(rosout_value)
        if isinstance(host_value, dict):
            claim_host_ambient_exemption = dict(host_value)
        if isinstance(external_value, dict):
            claim_external_sources = dict(external_value)
        if isinstance(v3_pending_value, dict):
            claim_v3_pending_guard = dict(v3_pending_value)
    except BaseException:
        pass
    terminal = terminal_process_layer(runtime, int(item["timeout_seconds"]))
    group = terminal["process_group"]
    if terminal["child_started"] and (
        not isinstance(group, Mapping)
        or group.get("leader_reaped") is not True
        or group.get("process_group_empty") is not True
        or group.get("owned_descendants_empty") is not True
    ):
        raise ContractError("REFUSE_FALSE_MINIMAL_RECEIPT_WITH_LIVE_CHILD")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA, "item_id": item_id, "kind": item.get("kind"),
        "status": terminal["status"], "started_at_local": started_at,
        "ended_at_local": now_local(), "launch_allowance_consumed": True,
        "execution_lock": public(lock_snapshot), "claim": claim_identity,
        "terminal_process": terminal,
        "artifact_contract": {
            "status": "FAIL", "outputs": {}, "semantic_checks": [],
            "issues": ["FINALIZER_FAILURE"],
        },
        "score_usability": {
            "status": "NOT_APPLICABLE" if item.get("kind") != "backend_replay" else "FAIL",
            "failure_codes": [] if item.get("kind") != "backend_replay" else ["FINALIZER_FAILURE"],
        },
        "execution_integrity": {
            "status": "FAIL", "supervisor_error": add_error(None, error),
            "authority_before_popen": {"status": "NOT_RUN"},
            "authority_post": {"status": "FAIL", "differences": ["FINALIZER_FAILURE"]},
            "dependency_bindings_before": {}, "dependency_bindings_post": {"status": "NOT_RUN"},
            "external_sources_before_claim": claim_external_sources,
            "external_sources_before_popen": {"status": "NOT_RUN"},
            "external_sources_post": {"status": "NOT_RUN"},
            "v3_pending_allowance_before_claim": claim_v3_pending_guard,
            "v3_pending_allowance_before_popen": {"status": "NOT_RUN"},
            "v3_pending_allowance_postflight": {"status": "NOT_RUN"},
            "masterless_rosout_exemption": {
                "before_claim": claim_rosout_exemption,
                "after_claim_before_popen": {"status": "UNAVAILABLE"},
                "postflight": {"status": "NOT_RUN"},
            },
            "loopback_host_ambient_exemption": {
                "before_claim": claim_host_ambient_exemption,
                "after_claim_before_popen": {"status": "UNAVAILABLE"},
                "postflight": {"status": "NOT_RUN"},
            },
            "postflight": {"status": "NOT_RUN"},
        },
    }
    receipt["overall_disposition"] = receipt_disposition(receipt)
    return receipt


def existing_terminal_receipt(
    receipt_path: Path, item_id: str, lock_snapshot: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    receipt, _identity = receipt_json(receipt_path)
    terminal = receipt.get("terminal_process")
    artifact = receipt.get("artifact_contract")
    execution = receipt.get("execution_integrity")
    score = receipt.get("score_usability")
    if (
        receipt.get("schema_version") != SCHEMA
        or receipt.get("item_id") != item_id
        or receipt.get("execution_lock") != public(lock_snapshot)
        or receipt.get("status") not in {"TERMINAL_PROCESS_RC0", "TERMINAL_PROCESS_FAILED"}
        or receipt.get("launch_allowance_consumed") is not True
        or not isinstance(terminal, dict)
        or not isinstance(artifact, dict)
        or not isinstance(execution, dict)
        or not isinstance(score, dict)
        or receipt.get("status") != terminal.get("status")
        or terminal.get("status") not in {"TERMINAL_PROCESS_RC0", "TERMINAL_PROCESS_FAILED"}
        or artifact.get("status") not in {"PASS", "FAIL"}
        or execution.get("status") not in {"PASS", "FAIL"}
        or score.get("status") not in {"PASS", "FAIL", "NOT_APPLICABLE"}
        or receipt.get("overall_disposition") != receipt_disposition(receipt)
    ):
        raise ContractError(f"EXISTING_TERMINAL_RECEIPT_INVALID:{receipt_path}")
    claim_path = receipt_path.parent / CLAIM_NAME
    claim_snapshot, claim_data = snapshot(claim_path, with_data=True)
    if receipt.get("claim") != public(claim_snapshot):
        raise ContractError(f"EXISTING_TERMINAL_RECEIPT_CLAIM_MISMATCH:{receipt_path}")
    assert claim_data is not None
    claim_value = parse_json(claim_data, claim_path)
    claim_v3_pending_guard = validate_v3_pending_guard_evidence(
        claim_value.get("v3_pending_allowance_guard"), phase="before_claim"
    )
    receipt_exemption = execution.get("masterless_rosout_exemption")
    receipt_host_exemption = execution.get("loopback_host_ambient_exemption")
    if (
        not isinstance(receipt_exemption, Mapping)
        or receipt_exemption.get("before_claim")
        != claim_value.get("masterless_rosout_exemption")
        or not isinstance(receipt_host_exemption, Mapping)
        or receipt_host_exemption.get("before_claim")
        != claim_value.get("loopback_host_ambient_exemption")
    ):
        raise ContractError(f"EXISTING_TERMINAL_RECEIPT_ROSOUT_EVIDENCE_MISMATCH:{receipt_path}")
    if execution.get("external_sources_before_claim") != claim_value.get(
        "external_source_bindings"
    ):
        raise ContractError(
            f"EXISTING_TERMINAL_RECEIPT_EXTERNAL_SOURCE_MISMATCH:{receipt_path}"
        )
    if execution.get("v3_pending_allowance_before_claim") != (
        claim_v3_pending_guard
    ):
        raise ContractError(
            f"EXISTING_TERMINAL_RECEIPT_V3_PENDING_CLAIM_MISMATCH:{receipt_path}"
        )
    if execution.get("status") == "PASS":
        for field, phase in (
            ("v3_pending_allowance_before_claim", "before_claim"),
            ("v3_pending_allowance_before_popen", "after_claim_before_popen"),
            ("v3_pending_allowance_postflight", "postflight"),
        ):
            validate_v3_pending_guard_evidence(execution.get(field), phase=phase)
    if terminal.get("child_started"):
        group = terminal.get("process_group")
        if not isinstance(group, dict) or any(
            group.get(key) is not True
            for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")
        ):
            raise ContractError(f"EXISTING_TERMINAL_RECEIPT_GROUP_INVALID:{receipt_path}")
    return receipt


def recover_existing_terminal_receipt_durably(
    receipt_path: Path, item_id: str, lock_snapshot: Mapping[str, Any]
) -> dict[str, Any] | None:
    """Validate and durably commit a complete receipt left by a failed return edge.

    A hard link can be visible even when the first parent-directory fsync raises.
    Such a receipt is reusable only after the exact regular file and its parent
    directory have both been fsynced and its identity and semantics are unchanged.
    """
    if not receipt_path.exists() and not receipt_path.is_symlink():
        return None
    receipt_path = receipt_path.absolute()
    before, _before_data = snapshot(receipt_path, with_data=True)
    receipt = existing_terminal_receipt(receipt_path, item_id, lock_snapshot)
    after_validation, _ = snapshot(receipt_path)
    if not same_snapshot(before, after_validation):
        raise ContractError(f"RECEIPT_CHANGED_DURING_RECOVERY_VALIDATION:{receipt_path}")
    with blocked_signals():
        no_symlink_components(receipt_path)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(receipt_path, flags)
        try:
            descriptor_before = os.fstat(descriptor)
            if not stat.S_ISREG(descriptor_before.st_mode):
                raise ContractError(f"RECOVERY_RECEIPT_NOT_REGULAR:{receipt_path}")
            descriptor_data = read_all(descriptor)
            descriptor_after_read = os.fstat(descriptor)
            stat_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            if any(
                getattr(descriptor_before, name) != getattr(descriptor_after_read, name)
                for name in stat_fields
            ):
                raise ContractError(f"RECOVERY_RECEIPT_CHANGED_WHILE_READING:{receipt_path}")
            if (
                descriptor_before.st_dev != before["device"]
                or descriptor_before.st_ino != before["inode"]
                or descriptor_before.st_size != before["size_bytes"]
                or descriptor_before.st_mtime_ns != before["mtime_ns"]
                or descriptor_before.st_ctime_ns != before["ctime_ns"]
                or hashlib.sha256(descriptor_data).hexdigest() != before["sha256"]
            ):
                raise ContractError(f"RECOVERY_RECEIPT_IDENTITY_MISMATCH:{receipt_path}")
            os.fsync(descriptor)
            descriptor_after_fsync = os.fstat(descriptor)
            if any(
                getattr(descriptor_before, name) != getattr(descriptor_after_fsync, name)
                for name in stat_fields
            ):
                raise ContractError(f"RECOVERY_RECEIPT_CHANGED_DURING_FSYNC:{receipt_path}")
        finally:
            os.close(descriptor)
        fsync_dir(receipt_path.parent)
    after_durability, _ = snapshot(receipt_path)
    if not same_snapshot(before, after_durability):
        raise ContractError(f"RECOVERY_RECEIPT_CHANGED_AFTER_FSYNC:{receipt_path}")
    recovered = existing_terminal_receipt(receipt_path, item_id, lock_snapshot)
    after_revalidation, _ = snapshot(receipt_path)
    if recovered != receipt or not same_snapshot(before, after_revalidation):
        raise ContractError(f"RECOVERY_RECEIPT_CHANGED_DURING_REVALIDATION:{receipt_path}")
    return recovered


def emit_receipt(receipt: Mapping[str, Any]) -> None:
    try:
        print(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False))
    except (BrokenPipeError, OSError):
        # The immutable receipt is authoritative; a closed stdout must not
        # rewrite it into a contradictory fallback receipt.
        pass


def finish_claimed(
    lock_path: Path, lock: Mapping[str, Any],
    verified_pre: Mapping[str, Mapping[str, Any]], lock_pre: Mapping[str, Any],
    item_id: str, item: Mapping[str, Any], claim_path: Path,
    receipt_path: Path, log_path: Path, started_at: str,
    dependency_bindings_pre: Mapping[str, Any], runtime: dict[str, Any],
    pending_signals: list[int], rosout_baseline_pre: Sequence[Mapping[str, Any]],
    rosout_exemption_before_claim: Mapping[str, Any],
    host_ambient_baseline_pre: Sequence[Mapping[str, Any]],
    host_ambient_exemption_before_claim: Mapping[str, Any],
    external_sources_pre: Mapping[str, Any],
    v3_pending_before_claim: Mapping[str, Any],
) -> int:
    started_monotonic = time.monotonic()
    argv, _declared = command(item)
    environment = effective_environment(lock, item)
    timeout = int(item["timeout_seconds"])
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    supervisor_error: str | None = None
    group_audit: dict[str, Any] = {
        "pgid": None, "leader_reaped": True, "process_group_empty": True,
        "owned_descendants_empty": True,
    }
    authority_before: dict[str, Any] = {"status": "NOT_RUN", "differences": []}
    authority_post: dict[str, Any] = {"status": "NOT_RUN", "differences": []}
    quiescence_after: dict[str, Any] | None = None
    postflight: dict[str, Any] = {"status": "NOT_RUN"}
    dependency_post: dict[str, Any] = {"status": "NOT_RUN"}
    external_sources_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    external_sources_post: dict[str, Any] = {"status": "NOT_RUN"}
    v3_pending_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    v3_pending_postflight: dict[str, Any] = {"status": "NOT_RUN"}
    outputs: dict[str, Any] = {}
    semantic_results: list[dict[str, Any]] = []
    output_issues: list[str] = []

    try:
        raise_pending_interruption(pending_signals)
        _lock_again, verified_again, lock_again = verify_lock(lock_path)
        ok, differences = authority_equal(verified_pre, lock_pre, verified_again, lock_again)
        authority_before = {
            "status": "PASS" if ok else "FAIL", "differences": differences,
            "checked_at_local": now_local(),
        }
        if not ok:
            raise ContractError(f"AUTHORITY_CHANGED_BEFORE_POPEN:{','.join(differences)}")
        dependency_again = validate_dependencies(lock, lock_pre, item_id)
        if dependency_again != dependency_bindings_pre:
            raise ContractError("DEPENDENCY_BINDING_CHANGED_BEFORE_POPEN")
        external_again = validate_external_source_provenance(lock, verified_again)
        external_sources_before_popen = {
            "status": "PASS" if external_again == external_sources_pre else "FAIL",
            "bindings": external_again,
        }
        if external_again != external_sources_pre:
            raise ContractError("EXTERNAL_SOURCE_CHANGED_BEFORE_POPEN")
        quiescence_after = quiescence_snapshot(
            item, verified_again["rosout_node"], rosout_baseline_pre,
            host_ambient_baseline_pre,
            phase="after_claim_before_popen",
        )
        enforce_quiescence(quiescence_after)
        v3_pending_before_popen = audit_v3_pending_backend_allowances(
            lock, phase="after_claim_before_popen"
        )
        validate_catkin_setup_dynamic_inputs(
            lock, verified_again, phase="after_claim_before_popen"
        )
        raise_pending_interruption(pending_signals)
        with log_path.open("xb") as log_stream:
            # Pending TERM/HUP/INT is delivered only after process and PGID are stored.
            with blocked_signals():
                runtime["baseline_children"] = sorted(
                    direct_child_identities(os.getpid())
                )
                runtime["popen_invocation_count"] += 1
                process = subprocess.Popen(
                    argv, cwd=ROOT, env=environment, stdout=log_stream,
                    stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
                )
                runtime["child_started"] = True
                runtime["pid"] = process.pid
                pgid = process.pid
                runtime["pgid"] = pgid
                runtime["process_group"] = {
                    "pgid": pgid, "leader_reaped": False,
                    "process_group_empty": False, "owned_descendants_empty": False,
                }
                leader_identity = process_identity(process.pid)
                if leader_identity is None:
                    leader_identity = (process.pid, -1)
                runtime["leader_identity"] = {
                    "pid": leader_identity[0], "start_ticks": leader_identity[1]
                }
            deadline = time.monotonic() + timeout
            while True:
                raise_pending_interruption(pending_signals)
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
        supervisor_error = add_error(supervisor_error, error)
    finally:
        if process is not None and pgid is not None:
            cleanup_errors: list[str] = []
            try:
                # A second TERM/HUP/INT remains pending until the leader, its
                # original process group, and any escaped/reparented descendants
                # have all been drained. Every cleanup exception forces a retry.
                with blocked_signals():
                    normal = (
                        runtime.get("raw_return_code") == 0
                        and runtime.get("timed_out") is False
                        and supervisor_error is None
                    )
                    while True:
                        try:
                            leader_row = runtime.get("leader_identity") or {
                                "pid": process.pid, "start_ticks": -1
                            }
                            group_audit = drain_owned_processes(
                                process, pgid,
                                (int(leader_row["pid"]), int(leader_row["start_ticks"])),
                                set(tuple(value) for value in runtime.get("baseline_children", [])),
                                normal_exit=normal,
                            )
                            break
                        except BaseException as cleanup_error:
                            cleanup_errors.append(
                                f"{type(cleanup_error).__name__}:{cleanup_error}"
                            )
                            normal = False
                            time.sleep(0.1)
                    group_audit["cleanup_retry_errors"] = cleanup_errors
                    runtime["raw_return_code"] = process.returncode
                    runtime["process_group"] = group_audit
            except BaseException as error:
                # This includes delivery of a signal that was pending during the
                # completed drain. The child state is already durable in runtime.
                supervisor_error = add_error(
                    supervisor_error, f"POST_CLEANUP_SIGNAL_OR_ERROR:{type(error).__name__}:{error}"
                )
            if group_audit.get("term_group_sent") and runtime.get("raw_return_code") == 0:
                supervisor_error = add_error(supervisor_error, "NORMAL_RC_LEFT_OWNED_PROCESS")
            if not group_audit.get("process_group_empty"):
                supervisor_error = add_error(supervisor_error, "PROCESS_GROUP_NOT_EMPTY")
            if not group_audit.get("owned_descendants_empty"):
                supervisor_error = add_error(supervisor_error, "OWNED_DESCENDANTS_NOT_EMPTY")
            if not group_audit.get("leader_reaped"):
                supervisor_error = add_error(supervisor_error, "LEADER_NOT_REAPED")
        if pending_signals:
            names = ",".join(signal.Signals(value).name for value in pending_signals)
            supervisor_error = add_error(supervisor_error, f"TERMINATION_SIGNALS:{names}")
        try:
            outputs, semantic_results, output_issues = audit_outputs(item)
        except BaseException as error:
            output_issues = [f"OUTPUT_AUDIT:{type(error).__name__}:{error}"]
        try:
            dependency_after = validate_dependencies(lock, lock_pre, item_id)
            dependency_ok = dependency_after == dependency_bindings_pre
            dependency_post = {
                "status": "PASS" if dependency_ok else "FAIL",
                "bindings": dependency_after,
            }
            if not dependency_ok:
                supervisor_error = add_error(supervisor_error, "DEPENDENCY_CHANGED_DURING_RUN")
        except BaseException as error:
            dependency_post = {
                "status": "FAIL", "error": f"{type(error).__name__}:{error}",
            }
            supervisor_error = add_error(supervisor_error, "DEPENDENCY_POSTCHECK_FAILED")
        try:
            _post_lock_value, verified_after, lock_after = verify_lock(lock_path)
            ok, differences = authority_equal(verified_pre, lock_pre, verified_after, lock_after)
            authority_post = {
                "status": "PASS" if ok else "FAIL", "differences": differences,
                "checked_at_local": now_local(),
            }
            if not ok:
                supervisor_error = add_error(supervisor_error, "AUTHORITY_CHANGED_DURING_RUN")
            external_after = validate_external_source_provenance(lock, verified_after)
            external_sources_post = {
                "status": "PASS" if external_after == external_sources_pre else "FAIL",
                "bindings": external_after,
            }
            if external_after != external_sources_pre:
                supervisor_error = add_error(
                    supervisor_error, "EXTERNAL_SOURCE_CHANGED_DURING_RUN"
                )
        except BaseException as error:
            authority_post = {
                "status": "FAIL", "differences": [f"{type(error).__name__}:{error}"],
                "checked_at_local": now_local(),
            }
            supervisor_error = add_error(supervisor_error, "AUTHORITY_POSTCHECK_FAILED")
            external_sources_post = {
                "status": "FAIL", "error": f"{type(error).__name__}:{error}",
            }
        try:
            isolation = process_isolation_snapshot(
                verified_pre["rosout_node"], rosout_baseline_pre
            )
            observed_hits = isolation["forbidden_processes"]
            isolation_policy = safe_text(
                item.get("isolation_policy"), f"{item_id}.isolation_policy"
            )
            if isolation_policy == "loopback_only_network_namespace":
                host_reconciliation = reconcile_loopback_host_ambient(
                    observed_hits, host_ambient_baseline_pre
                )
                ambient_hits = host_reconciliation["ambient_nonblocking_processes"]
                blocking_hits = host_reconciliation["blocking_processes"]
            else:
                host_reconciliation = {
                    "host_ambient_baseline": [],
                    "host_ambient_baseline_sha256": compact_json_sha256([]),
                    "disappeared_host_ambient": [],
                }
                ambient_hits, blocking_hits = classify_postflight_processes(
                    isolation_policy, observed_hits
                )
            port_error: str | None = None
            _post_argv, declared_env = command(item)
            if (
                "PORT" in declared_env
                and isolation_policy != "loopback_only_network_namespace"
            ):
                try:
                    check_port(int(declared_env["PORT"]))
                except BaseException as error:
                    port_error = f"{type(error).__name__}:{error}"
            postflight = {
                "status": "PASS" if not blocking_hits and port_error is None else "FAIL",
                "checked_at_local": now_local(),
                "isolation_policy": isolation_policy,
                "observed_isolation_hits": observed_hits,
                "ambient_nonblocking_processes": ambient_hits,
                "blocking_processes": blocking_hits,
                "forbidden_processes": blocking_hits,
                "declared_port_error": port_error,
                "host_ambient_baseline": host_reconciliation[
                    "host_ambient_baseline"
                ],
                "host_ambient_baseline_sha256": host_reconciliation[
                    "host_ambient_baseline_sha256"
                ],
                "disappeared_host_ambient": host_reconciliation[
                    "disappeared_host_ambient"
                ],
                "exempted_masterless_rosout": isolation[
                    "exempted_masterless_rosout"
                ],
                "disappeared_exempted_masterless_rosout": isolation[
                    "disappeared_exempted_masterless_rosout"
                ],
                "masterless_rosout_baseline": isolation[
                    "masterless_rosout_baseline"
                ],
                "masterless_rosout_baseline_sha256": isolation[
                    "masterless_rosout_baseline_sha256"
                ],
            }
            if blocking_hits or port_error is not None:
                supervisor_error = add_error(supervisor_error, "POSTFLIGHT_PROCESS_PRESENT")
        except BaseException as error:
            postflight = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
            supervisor_error = add_error(supervisor_error, "POSTFLIGHT_CHECK_FAILED")

    try:
        v3_pending_postflight = audit_v3_pending_backend_allowances(
            lock, phase="postflight"
        )
    except BaseException as error:
        v3_pending_postflight = {
            "status": "FAIL", "error": f"{type(error).__name__}:{error}",
        }
        supervisor_error = add_error(
            supervisor_error, "V3_PENDING_BACKEND_POSTFLIGHT_FAILED"
        )
    try:
        validate_catkin_setup_dynamic_inputs(
            lock, verified_pre, phase="postflight"
        )
    except BaseException as error:
        supervisor_error = add_error(
            supervisor_error,
            f"CATKIN_SETUP_POSTFLIGHT_FAILED:{type(error).__name__}:{error}",
        )
    if pending_signals and "TERMINATION_SIGNALS:" not in (supervisor_error or ""):
        names = ",".join(signal.Signals(value).name for value in pending_signals)
        supervisor_error = add_error(supervisor_error, f"TERMINATION_SIGNALS:{names}")
    terminal = terminal_process_layer(runtime, timeout)
    artifact = {
        "status": "PASS" if not output_issues else "FAIL",
        "outputs": outputs, "semantic_checks": semantic_results,
        "issues": output_issues,
    }
    score = evaluate_score_usability(lock, item, semantic_results, output_issues)
    execution_pass = bool(
        supervisor_error is None
        and group_audit.get("leader_reaped") is True
        and group_audit.get("process_group_empty") is True
        and group_audit.get("owned_descendants_empty") is True
        and authority_before.get("status") == "PASS"
        and authority_post.get("status") == "PASS"
        and dependency_post.get("status") == "PASS"
        and external_sources_before_popen.get("status") == "PASS"
        and external_sources_post.get("status") == "PASS"
        and v3_pending_before_claim.get("status") == "PASS"
        and v3_pending_before_popen.get("status") == "PASS"
        and v3_pending_postflight.get("status") == "PASS"
        and postflight.get("status") == "PASS"
    )
    execution = {
        "status": "PASS" if execution_pass else "FAIL",
        "supervisor_error": supervisor_error,
        "effective_environment": environment,
        "quiescence_after_claim": quiescence_after,
        "authority_before_popen": authority_before,
        "authority_post": authority_post,
        "dependency_bindings_before": dependency_bindings_pre,
        "dependency_bindings_post": dependency_post,
        "external_sources_before_claim": dict(external_sources_pre),
        "external_sources_before_popen": external_sources_before_popen,
        "external_sources_post": external_sources_post,
        "v3_pending_allowance_before_claim": dict(v3_pending_before_claim),
        "v3_pending_allowance_before_popen": v3_pending_before_popen,
        "v3_pending_allowance_postflight": v3_pending_postflight,
        "masterless_rosout_exemption": {
            "before_claim": dict(rosout_exemption_before_claim),
            "after_claim_before_popen": quiescence_after,
            "postflight": postflight,
        },
        "loopback_host_ambient_exemption": {
            "before_claim": dict(host_ambient_exemption_before_claim),
            "after_claim_before_popen": quiescence_after,
            "postflight": postflight,
        },
        "postflight": postflight,
    }
    try:
        final_claim_snapshot, final_claim_data = snapshot(claim_path, with_data=True)
        assert final_claim_data is not None
        final_claim = parse_json(final_claim_data, claim_path)
        if final_claim.get("masterless_rosout_exemption") != dict(
            rosout_exemption_before_claim
        ):
            raise ContractError("CLAIM_ROSOUT_EXEMPTION_CHANGED_DURING_RUN")
        claim_host = final_claim.get("loopback_host_ambient_exemption")
        if claim_host != dict(host_ambient_exemption_before_claim):
            raise ContractError("CLAIM_HOST_AMBIENT_EXEMPTION_CHANGED_DURING_RUN")
        if final_claim.get("external_source_bindings") != dict(external_sources_pre):
            raise ContractError("CLAIM_EXTERNAL_SOURCE_BINDING_CHANGED_DURING_RUN")
        if final_claim.get("v3_pending_allowance_guard") != dict(
            v3_pending_before_claim
        ):
            raise ContractError("CLAIM_V3_PENDING_ALLOWANCE_GUARD_CHANGED_DURING_RUN")
        receipt = {
            "schema_version": SCHEMA, "item_id": item_id, "kind": item.get("kind"),
            "status": terminal["status"],
            "started_at_local": started_at, "ended_at_local": now_local(),
            "wall_time_seconds": time.monotonic() - started_monotonic,
            "launch_allowance_consumed": True,
            "execution_lock": public(lock_pre), "claim": public(final_claim_snapshot),
            "process_log": public(snapshot(log_path)[0]) if log_path.exists() else None,
            "terminal_process": terminal, "artifact_contract": artifact,
            "score_usability": score, "execution_integrity": execution,
        }
        receipt["overall_disposition"] = receipt_disposition(receipt)
        atomic_publish(receipt_path, receipt)
    except BaseException as rich_error:
        existing = recover_existing_terminal_receipt_durably(receipt_path, item_id, lock_pre)
        if existing is not None:
            emit_receipt(existing)
            return 0 if receipt_is_accepted(existing) else 1
        receipt = minimal_receipt(
            item_id, item, started_at, lock_pre, claim_path, rich_error, runtime
        )
        try:
            atomic_publish(receipt_path, receipt)
        except BaseException as fallback_error:
            existing = recover_existing_terminal_receipt_durably(receipt_path, item_id, lock_pre)
            if existing is not None:
                emit_receipt(existing)
                return 0 if receipt_is_accepted(existing) else 1
            print(
                f"FATAL_CLAIMED_WITHOUT_RECEIPT:{item_id}:"
                f"rich={type(rich_error).__name__}:{rich_error}:"
                f"fallback={type(fallback_error).__name__}:{fallback_error}",
                file=sys.stderr,
            )
            return 3
    emit_receipt(receipt)
    return 0 if receipt_is_accepted(receipt) else 1


def run_item(
    lock_path: Path, lock: Mapping[str, Any], verified: Mapping[str, Mapping[str, Any]],
    lock_snapshot: Mapping[str, Any], item_id: str,
) -> int:
    item = lock["items"].get(item_id)
    if not isinstance(item, dict):
        raise ContractError(f"UNKNOWN_ITEM:{item_id}")
    prepare_layout(lock)
    dependency_bindings = validate_dependencies(lock, lock_snapshot, item_id)
    external_sources = validate_external_source_provenance(lock, verified)
    base = output_dir(item)
    claim_path, receipt_path, log_path = base / CLAIM_NAME, base / RECEIPT_NAME, base / LOG_NAME
    for path in (claim_path, receipt_path, log_path):
        if path.exists() or path.is_symlink():
            raise ContractError(f"ONE_SHOT_ARTIFACT_EXISTS:{path}")
    prelaunch_output_tree_empty(item)
    before_claim = check_quiescence(
        item, verified["rosout_node"], phase="before_claim"
    )
    rosout_baseline = before_claim["masterless_rosout_baseline"]
    rosout_exemption_before_claim = {
        "baseline": rosout_baseline,
        "baseline_sha256": before_claim["masterless_rosout_baseline_sha256"],
        "exempted_evidence": before_claim["exempted_masterless_rosout"],
    }
    host_ambient_baseline = before_claim["host_ambient_baseline"]
    host_ambient_exemption_before_claim = {
        "baseline": host_ambient_baseline,
        "baseline_sha256": before_claim["host_ambient_baseline_sha256"],
        "exempted_evidence": before_claim["ambient_nonblocking_processes"],
    }
    argv, _declared = command(item)
    environment = effective_environment(lock, item)
    started_at = now_local()
    runtime: dict[str, Any] = {
        "popen_invocation_count": 0, "child_started": False,
        "pid": None, "pgid": None, "leader_identity": None,
        "raw_return_code": None, "timed_out": False,
        "baseline_children": [],
        "process_group": {
            "pgid": None, "leader_reaped": True, "process_group_empty": True,
            "owned_descendants_empty": True,
        },
    }
    claim = {
        "schema_version": SCHEMA, "item_id": item_id, "started_at_local": started_at,
        "launch_allowance_consumed": True, "popen_invocation_count_at_claim": 0,
        "retry_count": 0, "execution_lock": public(lock_snapshot),
        "authority_pre": {name: public(value) for name, value in verified.items()},
        "argv": argv, "effective_environment": environment,
        "quiescence_before_claim": before_claim,
        "masterless_rosout_exemption": rosout_exemption_before_claim,
        "loopback_host_ambient_exemption": host_ambient_exemption_before_claim,
        "dependency_bindings": dependency_bindings,
        "external_source_bindings": external_sources,
    }
    with interruption_handlers() as pending_signals:
        try:
            raise_pending_interruption(pending_signals)
            v3_pending_before_claim = audit_v3_pending_backend_allowances(
                lock, phase="before_claim"
            )
            validate_catkin_setup_dynamic_inputs(
                lock, verified, phase="before_claim"
            )
            claim["v3_pending_allowance_guard"] = v3_pending_before_claim
            atomic_publish(
                claim_path, claim, propagate_interruption_after_commit=True
            )
            raise_pending_interruption(pending_signals)
            return finish_claimed(
                lock_path, lock, verified, lock_snapshot, item_id, item,
                claim_path, receipt_path, log_path, started_at,
                dependency_bindings, runtime, pending_signals, rosout_baseline,
                rosout_exemption_before_claim, host_ambient_baseline,
                host_ambient_exemption_before_claim,
                external_sources,
                v3_pending_before_claim,
            )
        except BaseException as error:
            existing = recover_existing_terminal_receipt_durably(
                receipt_path, item_id, lock_snapshot
            )
            if existing is not None:
                emit_receipt(existing)
                return 0 if receipt_is_accepted(existing) else 1
            # No visible claim means the launch allowance was not consumed.
            if not claim_path.exists() and not claim_path.is_symlink():
                raise
            receipt = minimal_receipt(
                item_id, item, started_at, lock_snapshot, claim_path, error, runtime
            )
            try:
                atomic_publish(receipt_path, receipt)
            except BaseException as publish_error:
                existing = recover_existing_terminal_receipt_durably(
                    receipt_path, item_id, lock_snapshot
                )
                if existing is not None:
                    emit_receipt(existing)
                    return 0 if receipt_is_accepted(existing) else 1
                print(
                    f"FATAL_CLAIMED_WITHOUT_RECEIPT:{item_id}:outer={type(error).__name__}:{error}:"
                    f"publish={type(publish_error).__name__}:{publish_error}", file=sys.stderr,
                )
                return 3
            emit_receipt(receipt)
            return 1


def status_rows(lock: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item_id, item in lock["items"].items():
        base = output_dir(item)
        receipt_path, claim_path = base / RECEIPT_NAME, base / CLAIM_NAME
        status_value = "NOT_STARTED"
        if receipt_path.exists() or receipt_path.is_symlink():
            try:
                receipt, _receipt_snapshot = receipt_json(receipt_path)
                status_value = str(receipt.get("status", "UNKNOWN"))
            except BaseException as error:
                status_value = f"INVALID_RECEIPT:{type(error).__name__}:{error}"
        elif claim_path.exists() or claim_path.is_symlink():
            status_value = "CLAIMED_WITHOUT_RECEIPT"
        result.append({
            "item_id": item_id, "kind": item.get("kind"),
            "output_dir": str(base), "status": status_value,
        })
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("check")
    commands.add_parser("prepare")
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    commands.add_parser("status")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock_path = args.lock.absolute()
    try:
        enable_subreaper()
        if args.action in {"prepare", "run-item"}:
            with global_mutex() as mutex:
                lock, verified, lock_snapshot = verify_lock(lock_path)
                if args.action == "prepare":
                    prepare_layout(lock)
                    print(json.dumps({
                        "status": "PREPARED", "mutex": mutex, "items": status_rows(lock),
                    }, indent=2, sort_keys=True))
                    return 0
                return run_item(lock_path, lock, verified, lock_snapshot, args.item_id)
        lock, verified, lock_snapshot = verify_lock(lock_path)
        if args.action == "check":
            print(json.dumps({
                "status": "PASS", "execution_lock": public(lock_snapshot),
                "verified": {name: public(value) for name, value in verified.items()},
            }, indent=2, sort_keys=True))
            return 0
        if args.action == "status":
            print(json.dumps(status_rows(lock), indent=2, sort_keys=True))
            return 0
        raise ContractError(f"UNKNOWN_ACTION:{args.action}")
    except ContractError as error:
        print(f"CONTRACT_ERROR:{error}", file=sys.stderr)
        return 2
    except BaseException as error:
        print(f"SUPERVISOR_FATAL:{type(error).__name__}:{error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
