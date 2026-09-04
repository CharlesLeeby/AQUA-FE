#!/usr/bin/env python3
"""Fail-closed analysis of the three A10 v4 backend-recovery attempts.

This program never starts ROS, VINS, a frontend, XFeat, HFNet, or a GPU job.
It audits the frozen v3 frontend authorities and the three immutable v4
backend receipts.  Only after all three attempts independently satisfy child
RC0, artifact PASS, execution-integrity PASS, and score-usability PASS may the
frozen CPU-only common-support evaluator run.

The score window has 21 native reference poses and a 20-sample uniform grid,
so the preregistered 30-pose formal APE gate is closed by construction.  Any
released metric is descriptive secondary/debug evidence.  The script never
sorts systems by error, names a winner, runs significance tests, or imputes a
failed system as zero.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import csv
import ctypes
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import errno
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).absolute().parents[1]
EXP = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v4_backend_recovery")
V3_EXP = Path("/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v3_recovery")
DEFAULT_OUTPUT = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v4_backend_recovery_analysis"
EXECUTION_LOCK = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v4_backend_recovery_execution_lock.json"
PROTOCOL = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v4_backend_recovery_protocol.md"
SUPERVISOR = ROOT / "scripts/run_samehistory_system_a10_finalonline_v4_backend_recovery.py"
NETNS_ENTRY = ROOT / "scripts/enter_samehistory_backend_netns_v4.py"
BACKEND_RUNNER = ROOT / "scripts/run_aqualoc_archaeo_vins_eval_v4_backend_recovery.sh"
EVALUATOR = ROOT / "scripts/evaluate_vins_common_support.py"
EVALUATOR_CORE = ROOT / "scripts/trajectory_eval_core.py"
PYTHON38 = Path("/usr/bin/python3.8")

ANALYSIS_SCHEMA = "aqua-fe-a10-samehistory-finalonline-v4-analysis-v1"
SUPERVISOR_SCHEMA = "aqua-fe-a10-samehistory-finalonline-supervisor-v4"
LOCK_SCHEMA = "aqua-fe-a10-samehistory-finalonline-v4-execution-lock-v1"
V3_SUPERVISOR_SCHEMA = "aqua-fe-a10-samehistory-finalonline-supervisor-v3"
NETNS_SCHEMA = "aqua-fe-a10-samehistory-backend-netns-v4"
RECEIPT_NAME = "formal_run_receipt_v4.json"
CLAIM_NAME = "process_start_claim.json"
LOG_NAME = "supervisor_process.log"
EVIDENCE_SCOPE = "PIPELINE_DEBUG_AND_SECONDARY_SENSITIVITY_ONLY"

ITEM_ORDER = (
    "vanilla_origin_native_image_context",
    "klt_external_feature_context",
    "aquafe_external_feature_context",
)
EVALUATOR_NAMES = {
    "vanilla_origin_native_image_context": "VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT",
    "klt_external_feature_context": "KLT_EXTERNAL_FEATURE_CONTEXT",
    "aquafe_external_feature_context": "AQUAFE_EXTERNAL_FEATURE_CONTEXT",
}
ITEM_DIRS = {
    item_id: EXP / "backends" / item_id for item_id in ITEM_ORDER
}
RECEIPTS = {
    item_id: ITEM_DIRS[item_id] / RECEIPT_NAME for item_id in ITEM_ORDER
}

SCORE_START_NS = 1_542_888_916_043_622_160
SCORE_END_NS = 1_542_888_936_039_921_424
SCORE_DURATION_NS = SCORE_END_NS - SCORE_START_NS
SCORE_SOURCE_RANGE = (2400, 2800)
FEED_SOURCE_RANGE = (0, 2800)
REFERENCE_ROWS = 21
UNIFORM_GRID_COUNT = 20
MIN_COMMON_ROWS = 15
MIN_SCORE_SPAN_FRACTION = 0.70
MAX_SCORE_GAP_NS = 500_000_000
MIN_RPE_PAIRS = 10
FORMAL_APE_MIN_POSES = 30

RAW_BAG = Path(
    "/mnt/data/AQUA-FE_WS/experiments/a10_samehistory_system_v1/raw/"
    "archaeo10_0000_2800.bag"
)
V3_LOCK = ROOT / "papers/samehistory_system_comparison_a10_finalonline_v3_recovery_execution_lock.json"
V3_KLT_DIR = V3_EXP / "frontends/klt_input_adoption"
V3_AQUA_DIR = V3_EXP / "frontends/aquafe_finalonline"
V3_KLT_RECEIPT = V3_KLT_DIR / "formal_run_receipt_v3.json"
V3_AQUA_RECEIPT = V3_AQUA_DIR / "formal_run_receipt_v3.json"
V3_VANILLA_RECEIPT = (
    V3_EXP / "backends/vanilla_origin_native_image_context/formal_run_receipt_v3.json"
)
V3_KLT_PENDING_DIR = V3_EXP / "backends/external_klt_finalonline_backbone"
V3_AQUA_PENDING_DIR = V3_EXP / "backends/aquafe_finalonline_xfeat_lineage"
V3_PENDING_BACKEND_GUARDS = {
    "external_klt_finalonline_backbone": {
        "output_dir": V3_KLT_PENDING_DIR,
        "claim_path": V3_KLT_PENDING_DIR / CLAIM_NAME,
        "receipt_path": V3_KLT_PENDING_DIR / "formal_run_receipt_v3.json",
    },
    "aquafe_finalonline_xfeat_lineage": {
        "output_dir": V3_AQUA_PENDING_DIR,
        "claim_path": V3_AQUA_PENDING_DIR / CLAIM_NAME,
        "receipt_path": V3_AQUA_PENDING_DIR / "formal_run_receipt_v3.json",
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

V3_KLT_FEATURES = V3_KLT_DIR / "features.bag"
V3_KLT_METRICS = V3_KLT_DIR / "frontend_metrics.csv"
V3_KLT_CAMERA = V3_KLT_DIR / "aqualoc_archaeo10_pinhole.yaml"
V3_KLT_MANIFEST = V3_KLT_DIR / "adoption_manifest.json"
V3_AQUA_FULL = V3_AQUA_DIR / "full_merged.bag"
V3_AQUA_SIDECAR = V3_AQUA_DIR / "sidecar.bag"
V3_AQUA_STATS = V3_AQUA_DIR / "stats.csv"

KNOWN_IDENTITIES: Mapping[Path, Mapping[str, Any]] = {
    RAW_BAG: {
        "size_bytes": 765_976_943,
        "sha256": "49864715ec19005daa3492fa043fe87204fb6f8cc802b6b98cba55a8ab4fe87e",
    },
    V3_LOCK: {
        "size_bytes": 144_118,
        "sha256": "b9cf114cc8fa183fc1127b1d7987e20bdabeed60a46f3ed17b178e3a8fa1352d",
    },
    V3_KLT_RECEIPT: {
        "size_bytes": 93_722,
        "sha256": "d1db99bbaaa1d3f07584858b863f6f1610dab5e96222537ce63dd1bf00637af0",
    },
    V3_AQUA_RECEIPT: {
        "size_bytes": 98_125,
        "sha256": "f17287d343c721a2fa9f7906de6e1c4c27a440704f3f2eec02ada70f398d93fa",
    },
    V3_VANILLA_RECEIPT: {
        "size_bytes": 100_879,
        "sha256": "49a0acb06211407a05ced876b6a2299a6f52efe8da9fb9d13cc0371519512049",
    },
    V3_KLT_FEATURES: {
        "size_bytes": 42_576_500,
        "sha256": "34e7ea87dd5706c58e666341776107570cc3351794b92da541f7eb8ec0d04b1f",
    },
    V3_KLT_METRICS: {
        "size_bytes": 1_003_812,
        "sha256": "ef86317bdb97b272955fe07de8f090c7e2313e4193028d974ecd7e4853030a99",
    },
    V3_KLT_CAMERA: {
        "size_bytes": 357,
        "sha256": "045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5",
    },
    V3_KLT_MANIFEST: {
        "size_bytes": 3_620,
        "sha256": "e28de66d047c98db55669838491a3457c802e311eb10394f7f0030a52f7bd07b",
    },
    V3_AQUA_FULL: {
        "size_bytes": 42_580_404,
        "sha256": "7b739e0c717ae41c11b07e364e48331d4a34c7786082cdd98bf53e8f58e03754",
    },
    V3_AQUA_SIDECAR: {
        "size_bytes": 575_687,
        "sha256": "82e773c5dd0a4a4b451e5a7d9e3803cc18193ad87c7686a777cdced3fbb09497",
    },
    V3_AQUA_STATS: {
        "size_bytes": 350_112,
        "sha256": "cfecc933567e0e62503532f0077ca19a64304994ba57c683a6e6bd0c3bc04da5",
    },
}

MANDATORY_LOCK_PATHS = (
    Path(__file__).absolute(),
    PROTOCOL,
    SUPERVISOR,
    NETNS_ENTRY,
    BACKEND_RUNNER,
    EVALUATOR,
    EVALUATOR_CORE,
    PYTHON38,
    RAW_BAG,
    V3_LOCK,
    V3_KLT_RECEIPT,
    V3_AQUA_RECEIPT,
    V3_VANILLA_RECEIPT,
    V3_KLT_FEATURES,
    V3_KLT_METRICS,
    V3_KLT_CAMERA,
    V3_KLT_MANIFEST,
    V3_AQUA_FULL,
    V3_AQUA_SIDECAR,
    V3_AQUA_STATS,
    *CATKIN_MARKERS.values(),
    *(ROS_PROFILE_DIR / name for name in ROS_HOOK_NAMES),
)


class EvidenceError(RuntimeError):
    """A fail-closed evidence or schema violation."""


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


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"DUPLICATE_JSON_KEY:{key}")
        result[key] = value
    return result


def no_symlink_components(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.parts[0])
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as error:
            raise EvidenceError(f"PATH_MISSING:{current}") from error
        if stat.S_ISLNK(mode):
            raise EvidenceError(f"SYMLINK_FORBIDDEN:{current}")


def snapshot(path: Path, *, with_data: bool = False) -> tuple[dict[str, Any], Optional[bytes]]:
    absolute = path.absolute()
    no_symlink_components(absolute)
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(absolute, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise EvidenceError(f"NOT_REGULAR_FILE:{absolute}")
        digest = hashlib.sha256()
        chunks: list[bytes] = []
        while True:
            block = os.read(descriptor, 1024 * 1024)
            if not block:
                break
            digest.update(block)
            if with_data:
                chunks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, key) != getattr(after, key) for key in stable_fields):
        raise EvidenceError(f"FILE_CHANGED_DURING_READ:{absolute}")
    value = {
        "path": str(absolute),
        "size_bytes": before.st_size,
        "sha256": digest.hexdigest(),
        "device": before.st_dev,
        "inode": before.st_ino,
        "mtime_ns": before.st_mtime_ns,
        "ctime_ns": before.st_ctime_ns,
    }
    return value, b"".join(chunks) if with_data else None


def identity(path: Path) -> dict[str, Any]:
    return snapshot(path)[0]


def read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    file_identity, data = snapshot(path, with_data=True)
    assert data is not None

    def reject_constant(value: str) -> None:
        raise EvidenceError(f"NONFINITE_JSON_CONSTANT:{path}:{value}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except EvidenceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise EvidenceError(f"JSON_READ_FAILED:{path}:{type(error).__name__}:{error}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON_ROOT_NOT_OBJECT:{path}")
    return value, file_identity


def identity_claim_matches(claim: object, actual: Mapping[str, Any]) -> bool:
    if not isinstance(claim, Mapping):
        return False
    required = {"path", "size_bytes", "sha256"}
    if not required.issubset(claim):
        return False
    known = {"path", "size_bytes", "sha256", "device", "inode", "mtime_ns", "ctime_ns"}
    if any(key not in known for key in claim):
        return False
    return all(claim.get(key) == actual.get(key) for key in claim)


def verify_known_identity(path: Path) -> dict[str, Any]:
    actual = identity(path)
    expected = KNOWN_IDENTITIES[path]
    if any(actual.get(key) != expected.get(key) for key in ("size_bytes", "sha256")):
        raise EvidenceError(f"KNOWN_IDENTITY_DRIFT:{path}")
    return actual


def clean_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): clean_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise EvidenceError("NONFINITE_VALUE_FOR_JSON")
    return value


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise EvidenceError(f"NOT_FINITE_NUMBER:{label}")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise EvidenceError(f"NOT_FINITE_NUMBER:{label}") from error
    if not math.isfinite(parsed):
        raise EvidenceError(f"NOT_FINITE_NUMBER:{label}")
    return parsed


def exact_integer(value: Any, label: str) -> int:
    parsed = finite_number(value, label)
    rounded = round(parsed)
    if abs(parsed - rounded) > 1e-9:
        raise EvidenceError(f"NOT_EXACT_INTEGER:{label}")
    return int(rounded)


def recursively_collect_strings(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        result.append(value)
    elif isinstance(value, Mapping):
        for item in value.values():
            result.extend(recursively_collect_strings(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(recursively_collect_strings(item))
    return result


def required_output_paths(item: Mapping[str, Any], base: Path) -> tuple[Path, ...]:
    raw = item.get("expected_outputs")
    if not isinstance(raw, list) or not raw:
        raise EvidenceError("EXPECTED_OUTPUTS_MISSING")
    result: list[Path] = []
    seen: set[str] = set()
    for value in raw:
        if not isinstance(value, str) or not value:
            raise EvidenceError("EXPECTED_OUTPUT_INVALID")
        relative = Path(value)
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise EvidenceError(f"EXPECTED_OUTPUT_UNSAFE:{value}")
        normalized = relative.as_posix()
        if normalized in seen:
            raise EvidenceError(f"EXPECTED_OUTPUT_DUPLICATE:{value}")
        seen.add(normalized)
        path = (base / relative).absolute()
        try:
            path.relative_to(base.absolute())
        except ValueError as error:
            raise EvidenceError(f"EXPECTED_OUTPUT_ESCAPE:{value}") from error
        result.append(path)
    return tuple(result)


def parse_netns_argv(item_id: str, item: Mapping[str, Any]) -> dict[str, Any]:
    argv = item.get("argv")
    env = item.get("env")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and v for v in argv):
        raise EvidenceError(f"LOCK_ARGV_INVALID:{item_id}")
    if not isinstance(env, Mapping) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in env.items()
    ):
        raise EvidenceError(f"LOCK_ENV_INVALID:{item_id}")
    if argv[0] != "/usr/bin/unshare" or argv[1:4] != ["--user", "--map-root-user", "--net"]:
        raise EvidenceError(f"LOCK_UNSHARE_PREFIX_INVALID:{item_id}")
    if str(NETNS_ENTRY) not in argv:
        raise EvidenceError(f"LOCK_NETNS_ENTRY_MISSING:{item_id}")
    entry_index = argv.index(str(NETNS_ENTRY))
    if entry_index < 4 or argv[entry_index - 1] != str(PYTHON38):
        raise EvidenceError(f"LOCK_NETNS_PYTHON_INVALID:{item_id}")
    try:
        separator = argv.index("--", entry_index + 1)
    except ValueError as error:
        raise EvidenceError(f"LOCK_NETNS_BACKEND_SEPARATOR_MISSING:{item_id}") from error
    inner = argv[separator + 1 :]
    if not inner or inner[:2] != ["/usr/bin/bash", str(BACKEND_RUNNER)]:
        raise EvidenceError(f"LOCK_INNER_BACKEND_INVALID:{item_id}")

    def option(name: str) -> str:
        positions = [index for index, value in enumerate(argv[:separator]) if value == name]
        if len(positions) != 1 or positions[0] + 1 >= separator:
            raise EvidenceError(f"LOCK_NETNS_OPTION_INVALID:{item_id}:{name}")
        return argv[positions[0] + 1]

    output = option("--output-dir")
    port_raw = option("--formal-port")
    host_net = option("--host-network-namespace")
    host_user = option("--host-user-namespace")
    if output != str(ITEM_DIRS[item_id]):
        raise EvidenceError(f"LOCK_NETNS_OUTPUT_DIR_DRIFT:{item_id}")
    if re.fullmatch(r"net:\[[0-9]+\]", host_net) is None:
        raise EvidenceError(f"LOCK_HOST_NETNS_INVALID:{item_id}")
    if re.fullmatch(r"user:\[[0-9]+\]", host_user) is None:
        raise EvidenceError(f"LOCK_HOST_USERNS_INVALID:{item_id}")
    try:
        port = int(port_raw, 10)
    except ValueError as error:
        raise EvidenceError(f"LOCK_FORMAL_PORT_INVALID:{item_id}") from error
    if not 1024 <= port <= 65535 or env.get("PORT") != str(port):
        raise EvidenceError(f"LOCK_FORMAL_PORT_ENV_MISMATCH:{item_id}")
    backend_hash = hashlib.sha256(
        json.dumps(inner, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {
        "argv": list(argv),
        "env": dict(env),
        "inner_backend": inner,
        "backend_argv_sha256": backend_hash,
        "formal_port": port,
        "host_network_namespace": host_net,
        "host_user_namespace": host_user,
    }


def inspect_lock() -> tuple[Optional[dict[str, Any]], dict[str, Any]]:
    if not EXECUTION_LOCK.exists() and not EXECUTION_LOCK.is_symlink():
        return None, {
            "state": "PENDING_MISSING_EXECUTION_LOCK",
            "path": str(EXECUTION_LOCK),
            "errors": [],
        }
    errors: list[str] = []
    lock: Optional[dict[str, Any]] = None
    lock_identity: Optional[dict[str, Any]] = None
    verified: dict[str, dict[str, Any]] = {}
    parsed_netns: dict[str, dict[str, Any]] = {}
    try:
        lock, lock_identity = read_json(EXECUTION_LOCK)
        if lock.get("schema_version") != LOCK_SCHEMA:
            errors.append("LOCK_SCHEMA_DRIFT")
        if lock.get("status") != "FROZEN_BEFORE_SCORED_RUNS":
            errors.append("LOCK_NOT_FROZEN_BEFORE_SCORED_RUNS")
        policy = lock.get("policy")
        if not isinstance(policy, Mapping):
            errors.append("LOCK_POLICY_MISSING")
            policy = {}
        if policy.get("item_order") != list(ITEM_ORDER):
            errors.append("LOCK_ITEM_ORDER_DRIFT")
        if policy.get("large_artifact_root") != str(EXP):
            errors.append("LOCK_ARTIFACT_ROOT_DRIFT")
        if policy.get("catkin_setup_dynamic_inputs") != (
            catkin_setup_dynamic_input_contract()
        ):
            errors.append("LOCK_CATKIN_SETUP_DYNAMIC_INPUT_CONTRACT_DRIFT")
        score_expected = {
            "score_start_ns": SCORE_START_NS,
            "score_end_ns": SCORE_END_NS,
            "crop_interval": "inclusive",
            "nominal_backend_output_rate_hz": 10,
            "minimum_score_temporal_span_coverage": 0.70,
            "maximum_score_output_gap_s": 0.50,
            "require_initialization_before_or_within_score_window": True,
            "maximum_score_failure_mentions": 0,
            "maximum_score_restart_or_reset_events": 0,
            "unresolved_score_log_event_attribution_is_failure": True,
            "score_failure_is_usability_fail_not_terminal_process_failure": True,
        }
        if lock.get("score_usability") != score_expected:
            errors.append("LOCK_SCORE_USABILITY_DRIFT")
        common_expected = {
            "denominator_reference_rows": REFERENCE_ROWS,
            "minimum_common_rows": MIN_COMMON_ROWS,
            "minimum_common_coverage": 0.70,
            "minimum_descriptive_rpe_pairs": MIN_RPE_PAIRS,
            "formal_ape_minimum_poses": FORMAL_APE_MIN_POSES,
            "formal_ape_gate_open": False,
        }
        if lock.get("common_support") != common_expected:
            errors.append("LOCK_COMMON_SUPPORT_DRIFT")
        recovery = lock.get("recovery_provenance")
        if not isinstance(recovery, Mapping):
            errors.append("LOCK_RECOVERY_PROVENANCE_MISSING")
        else:
            if recovery.get("unconsumed_v3_backend_items") != list(
                V3_PENDING_BACKEND_GUARDS
            ):
                errors.append("LOCK_V3_PENDING_BACKEND_ITEMS_DRIFT")
            if recovery.get("v3_pending_backend_allowance_guard") != (
                v3_pending_allowance_guard_contract()
            ):
                errors.append("LOCK_V3_PENDING_ALLOWANCE_GUARD_DRIFT")

        protocol_claim = lock.get("protocol")
        try:
            protocol_actual = identity(PROTOCOL)
            if not identity_claim_matches(protocol_claim, protocol_actual):
                errors.append("LOCK_PROTOCOL_IDENTITY_DRIFT")
            else:
                verified["protocol"] = protocol_actual
        except (EvidenceError, OSError) as error:
            errors.append(f"LOCK_PROTOCOL_READ_FAILED:{error}")

        claims = lock.get("identities")
        if not isinstance(claims, Mapping) or not claims:
            errors.append("LOCK_IDENTITIES_MISSING")
            claims = {}
        for name, claim in claims.items():
            if not isinstance(name, str) or not isinstance(claim, Mapping):
                errors.append(f"LOCK_IDENTITY_CLAIM_INVALID:{name}")
                continue
            raw_path = claim.get("path")
            if not isinstance(raw_path, str) or not Path(raw_path).is_absolute():
                errors.append(f"LOCK_IDENTITY_PATH_INVALID:{name}")
                continue
            try:
                actual = identity(Path(raw_path))
            except (EvidenceError, OSError) as error:
                errors.append(f"LOCK_IDENTITY_READ_FAILED:{name}:{error}")
                continue
            if not identity_claim_matches(claim, actual):
                errors.append(f"LOCK_IDENTITY_DRIFT:{name}")
                continue
            verified[name] = actual
        verified_paths = {Path(value["path"]).absolute() for value in verified.values()}
        for path in MANDATORY_LOCK_PATHS:
            if path.absolute() not in verified_paths:
                errors.append(f"LOCK_MANDATORY_IDENTITY_MISSING:{path}")
        try:
            no_symlink_components(ROS_PROFILE_DIR)
            observed_names = tuple(sorted(path.name for path in ROS_PROFILE_DIR.iterdir()))
            if observed_names != ROS_HOOK_NAMES:
                errors.append("ROS_PROFILE_DIRECTORY_MEMBERSHIP_DRIFT")
            for index, name in enumerate(observed_names):
                path = ROS_PROFILE_DIR / name
                if not stat.S_ISREG(path.lstat().st_mode):
                    errors.append(f"ROS_PROFILE_ENTRY_NOT_REGULAR:{name}")
                key = f"ros_environment_hook_{index:02d}"
                value = verified.get(key)
                if not isinstance(value, Mapping) or value.get("path") != str(path):
                    errors.append(f"ROS_PROFILE_IDENTITY_BINDING_DRIFT:{name}")
        except (EvidenceError, OSError) as error:
            errors.append(f"ROS_PROFILE_DIRECTORY_AUDIT_FAILED:{error}")
        for path in ABSENT_WORKSPACE_PROFILE_DIRS:
            try:
                os.lstat(path)
            except FileNotFoundError:
                continue
            errors.append(f"WORKSPACE_PROFILE_DIRECTORY_APPEARED:{path}")
        try:
            python3_identity = verified.get("python3_8")
            if (
                not stat.S_ISLNK(os.lstat(PYTHON3_SYMLINK).st_mode)
                or os.readlink(PYTHON3_SYMLINK) != PYTHON3_SYMLINK_TARGET
                or PYTHON3_SYMLINK.resolve(strict=True) != Path("/usr/bin/python3.8")
                or not isinstance(python3_identity, Mapping)
                or python3_identity.get("path") != "/usr/bin/python3.8"
            ):
                errors.append("PYTHON3_SYMLINK_DRIFT")
        except OSError as error:
            errors.append(f"PYTHON3_SYMLINK_AUDIT_FAILED:{error}")

        items = lock.get("items")
        if not isinstance(items, Mapping) or list(items) != list(ITEM_ORDER):
            errors.append("LOCK_ITEM_SET_OR_JSON_ORDER_DRIFT")
            items = {}
        forbidden_v3_backend_roots = (
            str(V3_KLT_PENDING_DIR),
            str(V3_AQUA_PENDING_DIR),
            str(V3_EXP / "backends/vanilla_origin_native_image_context/vins_output"),
        )
        for item_id in ITEM_ORDER:
            item = items.get(item_id)
            if not isinstance(item, Mapping):
                errors.append(f"LOCK_ITEM_MISSING:{item_id}")
                continue
            if item.get("kind") != "backend_replay":
                errors.append(f"LOCK_ITEM_KIND_DRIFT:{item_id}")
            if item.get("dependencies") != []:
                errors.append(f"LOCK_V4_DEPENDENCIES_NOT_EMPTY:{item_id}")
            if item.get("isolation_policy") != "loopback_only_network_namespace":
                errors.append(f"LOCK_ISOLATION_POLICY_DRIFT:{item_id}")
            if item.get("output_dir") != str(ITEM_DIRS[item_id]):
                errors.append(f"LOCK_OUTPUT_DIR_DRIFT:{item_id}")
            if item.get("output_tree_policy") != "REQUIRE_EMPTY_BEFORE_CLAIM":
                errors.append(f"LOCK_OUTPUT_TREE_POLICY_DRIFT:{item_id}")
            try:
                outputs = required_output_paths(item, ITEM_DIRS[item_id])
                required_names = {
                    "vins_output/vio.csv",
                    "vins.log",
                    "ape.txt",
                    "replay_manifest.txt",
                    "vins_env_manifest.txt",
                    "roscore.log",
                    "aqualoc_archaeo10_pinhole.yaml",
                    "network_namespace_manifest.json",
                    (
                        "vins_aqualoc_archaeo_origin.yaml"
                        if item_id == "vanilla_origin_native_image_context"
                        else "vins_aqualoc_archaeo_external.yaml"
                    ),
                }
                output_names = {str(path.relative_to(ITEM_DIRS[item_id])) for path in outputs}
                missing = sorted(required_names - output_names)
                if missing:
                    errors.append(f"LOCK_REQUIRED_OUTPUTS_MISSING:{item_id}:{missing}")
            except EvidenceError as error:
                errors.append(f"LOCK_EXPECTED_OUTPUTS_INVALID:{item_id}:{error}")
            try:
                parsed_netns[item_id] = parse_netns_argv(item_id, item)
            except EvidenceError as error:
                errors.append(str(error))
            env = item.get("env")
            if isinstance(env, Mapping):
                expected_override: Optional[str]
                if item_id == "vanilla_origin_native_image_context":
                    expected_override = None
                elif item_id == "klt_external_feature_context":
                    expected_override = str(V3_KLT_FEATURES)
                else:
                    expected_override = str(V3_AQUA_FULL)
                actual_override = env.get("FEATURE_BAG_OVERRIDE")
                if actual_override != expected_override:
                    errors.append(f"LOCK_FEATURE_INPUT_BINDING_DRIFT:{item_id}")
                if env.get("RAW_BAG") not in {None, str(RAW_BAG)}:
                    errors.append(f"LOCK_RAW_BAG_BINDING_DRIFT:{item_id}")
            strings = recursively_collect_strings(item)
            for root in forbidden_v3_backend_roots:
                if any(value.startswith(root) for value in strings):
                    errors.append(f"LOCK_FORBIDDEN_V3_BACKEND_INPUT:{item_id}:{root}")
        if len(parsed_netns) == len(ITEM_ORDER) and any(
            audit.get("formal_port") != 11981 for audit in parsed_netns.values()
        ):
            errors.append("LOCK_FORMAL_PORT_NOT_FROZEN_11981")
    except (EvidenceError, OSError, UnicodeError) as error:
        errors.append(f"LOCK_READ_FAILED:{type(error).__name__}:{error}")
    state = "PASS" if lock is not None and not errors else "INVALID"
    return (lock if state == "PASS" else None), {
        "state": state,
        "path": str(EXECUTION_LOCK),
        "identity": lock_identity,
        "verified_identities": verified,
        "parsed_network_namespace_contracts": parsed_netns,
        "errors": errors,
    }


def accepted_v3_frontend_receipt(
    path: Path,
    item_id: str,
    kind: str,
    expected_outputs: Sequence[Path],
) -> dict[str, Any]:
    receipt, receipt_identity = read_json(path)
    errors: list[str] = []
    expected_top = {
        "schema_version": V3_SUPERVISOR_SCHEMA,
        "item_id": item_id,
        "kind": kind,
        "status": "TERMINAL_PROCESS_RC0",
        "launch_allowance_consumed": True,
        "overall_disposition": "ACCEPTED",
    }
    for key, expected in expected_top.items():
        if receipt.get(key) != expected:
            errors.append(f"V3_RECEIPT_FIELD_DRIFT:{item_id}:{key}")
    terminal = receipt.get("terminal_process")
    if not isinstance(terminal, Mapping) or any(
        (
            terminal.get("popen_invocation_count") != 1,
            terminal.get("child_started") is not True,
            terminal.get("raw_return_code") != 0,
            terminal.get("timed_out") is not False,
            terminal.get("status") != "TERMINAL_PROCESS_RC0",
        )
    ):
        errors.append(f"V3_TERMINAL_NOT_RC0:{item_id}")
    group = terminal.get("process_group") if isinstance(terminal, Mapping) else None
    if not isinstance(group, Mapping) or any(
        group.get(key) is not True
        for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")
    ):
        errors.append(f"V3_PROCESS_GROUP_NOT_DRAINED:{item_id}")
    artifact = receipt.get("artifact_contract")
    outputs = artifact.get("outputs") if isinstance(artifact, Mapping) else None
    if not isinstance(artifact, Mapping) or artifact.get("status") != "PASS" or artifact.get("issues") != []:
        errors.append(f"V3_ARTIFACT_NOT_PASS:{item_id}")
    expected_set = {str(path.absolute()) for path in expected_outputs}
    if not isinstance(outputs, Mapping) or set(outputs) != expected_set:
        errors.append(f"V3_OUTPUT_SET_DRIFT:{item_id}")
    else:
        for raw_path, claim in outputs.items():
            try:
                actual = identity(Path(raw_path))
            except (EvidenceError, OSError) as error:
                errors.append(f"V3_OUTPUT_READ_FAILED:{item_id}:{raw_path}:{error}")
                continue
            if not identity_claim_matches(claim, actual):
                errors.append(f"V3_OUTPUT_IDENTITY_DRIFT:{item_id}:{raw_path}")
    execution = receipt.get("execution_integrity")
    if not isinstance(execution, Mapping) or execution.get("status") != "PASS" or execution.get("supervisor_error") is not None:
        errors.append(f"V3_EXECUTION_NOT_PASS:{item_id}")
    else:
        for field in ("authority_before_popen", "authority_post", "quiescence_after_claim", "postflight", "dependency_bindings_post"):
            value = execution.get(field)
            if not isinstance(value, Mapping) or value.get("status") != "PASS":
                errors.append(f"V3_EXECUTION_SUBCHECK_NOT_PASS:{item_id}:{field}")
    if receipt.get("score_usability") != {"status": "NOT_APPLICABLE", "failure_codes": []}:
        errors.append(f"V3_FRONTEND_SCORE_LAYER_DRIFT:{item_id}")
    lock_claim = receipt.get("execution_lock")
    try:
        if not identity_claim_matches(lock_claim, identity(V3_LOCK)):
            errors.append(f"V3_RECEIPT_LOCK_BINDING_DRIFT:{item_id}")
    except (EvidenceError, OSError) as error:
        errors.append(f"V3_LOCK_READ_FAILED:{item_id}:{error}")
    return {
        "state": "PASS" if not errors else "INVALID",
        "item_id": item_id,
        "identity": receipt_identity,
        "errors": errors,
    }


def audit_v3_sources(lock_audit: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    identities: dict[str, dict[str, Any]] = {}
    for path in KNOWN_IDENTITIES:
        try:
            identities[str(path)] = verify_known_identity(path)
        except (EvidenceError, OSError) as error:
            errors.append(str(error))
    klt_receipt: dict[str, Any]
    aqua_receipt: dict[str, Any]
    try:
        klt_receipt = accepted_v3_frontend_receipt(
            V3_KLT_RECEIPT,
            "klt_input_adoption",
            "sealed_input_adoption",
            (V3_KLT_FEATURES, V3_KLT_METRICS, V3_KLT_CAMERA, V3_KLT_MANIFEST),
        )
        errors.extend(klt_receipt["errors"])
    except (EvidenceError, OSError) as error:
        klt_receipt = {"state": "INVALID", "errors": [str(error)]}
        errors.append(f"V3_KLT_RECEIPT_AUDIT_FAILED:{error}")
    try:
        aqua_receipt = accepted_v3_frontend_receipt(
            V3_AQUA_RECEIPT,
            "aquafe_build",
            "learned_sidecar_build",
            (V3_AQUA_FULL, V3_AQUA_SIDECAR, V3_AQUA_STATS),
        )
        errors.extend(aqua_receipt["errors"])
    except (EvidenceError, OSError) as error:
        aqua_receipt = {"state": "INVALID", "errors": [str(error)]}
        errors.append(f"V3_AQUA_RECEIPT_AUDIT_FAILED:{error}")

    vanilla_audit: dict[str, Any] = {"state": "INVALID"}
    try:
        vanilla, vanilla_identity = read_json(V3_VANILLA_RECEIPT)
        terminal = vanilla.get("terminal_process")
        artifact = vanilla.get("artifact_contract")
        execution = vanilla.get("execution_integrity")
        expected = bool(
            vanilla.get("schema_version") == V3_SUPERVISOR_SCHEMA
            and vanilla.get("item_id") == "vanilla_origin_native_image_context"
            and vanilla.get("status") == "TERMINAL_PROCESS_FAILED"
            and vanilla.get("overall_disposition") == "PROCESS_FAILED"
            and vanilla.get("launch_allowance_consumed") is True
            and isinstance(terminal, Mapping)
            and terminal.get("popen_invocation_count") == 1
            and terminal.get("raw_return_code") == -9
            and terminal.get("timed_out") is True
            and isinstance(artifact, Mapping)
            and artifact.get("status") == "FAIL"
            and isinstance(execution, Mapping)
            and execution.get("status") == "FAIL"
            and execution.get("supervisor_error") == "POSTFLIGHT_PROCESS_PRESENT"
        )
        if not expected:
            errors.append("V3_VANILLA_FAILED_ATTEMPT_STATE_DRIFT")
        vanilla_audit = {
            "state": "PASS_RETAINED_FAILED_ATTEMPT" if expected else "INVALID",
            "identity": vanilla_identity,
            "terminal_status": terminal.get("status") if isinstance(terminal, Mapping) else None,
            "raw_return_code": terminal.get("raw_return_code") if isinstance(terminal, Mapping) else None,
            "timed_out": terminal.get("timed_out") if isinstance(terminal, Mapping) else None,
            "artifact_contract_status": artifact.get("status") if isinstance(artifact, Mapping) else None,
            "execution_integrity_status": execution.get("status") if isinstance(execution, Mapping) else None,
            "supervisor_error": execution.get("supervisor_error") if isinstance(execution, Mapping) else None,
            "overall_disposition": vanilla.get("overall_disposition"),
            "rerun_by_v4": False,
        }
    except (EvidenceError, OSError) as error:
        errors.append(f"V3_VANILLA_RECEIPT_AUDIT_FAILED:{error}")

    pending_paths = {
        "v3_klt_backend_claim": V3_KLT_PENDING_DIR / CLAIM_NAME,
        "v3_klt_backend_receipt": V3_KLT_PENDING_DIR / "formal_run_receipt_v3.json",
        "v3_aquafe_backend_claim": V3_AQUA_PENDING_DIR / CLAIM_NAME,
        "v3_aquafe_backend_receipt": V3_AQUA_PENDING_DIR / "formal_run_receipt_v3.json",
    }
    pending_presence = {
        name: path.exists() or path.is_symlink() for name, path in pending_paths.items()
    }
    if any(pending_presence.values()):
        errors.append("V3_PENDING_BACKEND_LAUNCH_ALLOWANCE_WAS_CONSUMED")
    try:
        v3_lock_value, _v3_lock_identity = read_json(V3_LOCK)
        v3_items = v3_lock_value.get("items")
        if not isinstance(v3_items, Mapping):
            errors.append("V3_LOCK_ITEM_MAP_INVALID")
        else:
            for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
                item = v3_items.get(item_id)
                if (
                    not isinstance(item, Mapping)
                    or item.get("output_dir") != str(paths["output_dir"])
                ):
                    errors.append(f"V3_PENDING_OUTPUT_DIR_BINDING_DRIFT:{item_id}")
    except (EvidenceError, OSError) as error:
        errors.append(f"V3_PENDING_OUTPUT_DIR_BINDING_READ_FAILED:{error}")

    lock_bound = False
    if lock_audit.get("state") == "PASS":
        verified = lock_audit.get("verified_identities")
        if isinstance(verified, Mapping):
            locked_paths = {
                Path(str(value.get("path"))).absolute()
                for value in verified.values()
                if isinstance(value, Mapping) and isinstance(value.get("path"), str)
            }
            required = {path.absolute() for path in KNOWN_IDENTITIES}
            lock_bound = required.issubset(locked_paths)
        if not lock_bound:
            errors.append("V4_LOCK_DOES_NOT_BIND_ALL_V3_AUTHORITIES")
    state = "PASS" if not errors and lock_audit.get("state") == "PASS" else (
        "PASS_SOURCES_LOCK_PENDING"
        if not errors and lock_audit.get("state") == "PENDING_MISSING_EXECUTION_LOCK"
        else "INVALID"
    )
    return {
        "state": state,
        "evidence_scope": EVIDENCE_SCOPE,
        "paper_primary_evidence_permitted": False,
        "v3_klt_frontend_receipt": klt_receipt,
        "v3_aquafe_frontend_receipt": aqua_receipt,
        "v3_vanilla_failed_attempt": vanilla_audit,
        "v3_klt_and_aquafe_backend_attempts_not_started": not any(pending_presence.values()),
        "v3_pending_backend_path_presence": pending_presence,
        "v4_lock_binds_all_known_sources": lock_bound,
        "known_source_identities": identities,
        "errors": list(dict.fromkeys(errors)),
        "interpretation": (
            "v4 uses only accepted v3 frontend artifacts as frozen external inputs; "
            "it neither repairs the failed v3 Vanilla attempt nor consumes the two "
            "unstarted v3 backend attempts."
        ),
    }


INTEGER_NS = re.compile(r"[0-9]+")


def parse_integer_ns(raw: str) -> int:
    text = raw.strip()
    if INTEGER_NS.fullmatch(text) is None:
        raise ValueError("timestamp is not an integer nanosecond value")
    return int(text)


def decimal_seconds_to_ns(raw: str) -> int:
    try:
        value = Decimal(raw) * Decimal("1000000000")
    except InvalidOperation as error:
        raise ValueError("invalid decimal seconds") from error
    if not value.is_finite():
        raise ValueError("non-finite decimal seconds")
    rounded = value.to_integral_value(rounding=ROUND_HALF_EVEN)
    if abs(value - rounded) > Decimal("0.5"):
        raise ValueError("timestamp cannot be represented as integer nanoseconds")
    return int(rounded)


def audit_trajectory(path: Path) -> dict[str, Any]:
    if not path.exists() and not path.is_symlink():
        return {"state": "MISSING", "path": str(path), "valid": False, "errors": ["TRAJECTORY_MISSING"]}
    errors: list[str] = []
    stamps: list[int] = []
    malformed = 0
    nonfinite = 0
    invalid_quaternion = 0
    try:
        file_identity = identity(path)
        with path.open(newline="", encoding="utf-8", errors="strict") as handle:
            for row in csv.reader(handle):
                fields = list(row)
                if len(fields) == 12 and fields[-1] == "":
                    fields.pop()
                if len(fields) != 11:
                    malformed += 1
                    continue
                try:
                    stamp = parse_integer_ns(fields[0])
                    numeric = [float(value) for value in fields[1:]]
                except ValueError:
                    malformed += 1
                    continue
                if not all(math.isfinite(value) for value in numeric):
                    nonfinite += 1
                    continue
                quaternion = numeric[3:7]
                norm = math.sqrt(sum(value * value for value in quaternion))
                if not 0.95 <= norm <= 1.05:
                    invalid_quaternion += 1
                    continue
                stamps.append(stamp)
    except (EvidenceError, OSError, UnicodeError) as error:
        return {
            "state": "INVALID",
            "path": str(path),
            "valid": False,
            "errors": [f"TRAJECTORY_READ_ERROR:{type(error).__name__}:{error}"],
        }
    if malformed:
        errors.append(f"MALFORMED_ROWS:{malformed}")
    if nonfinite:
        errors.append(f"NONFINITE_ROWS:{nonfinite}")
    if invalid_quaternion:
        errors.append(f"INVALID_QUATERNION_NORM_ROWS:{invalid_quaternion}")
    if not stamps:
        errors.append("NO_VALID_POSES")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        errors.append("TIMESTAMPS_NOT_STRICTLY_INCREASING")
    score = [stamp for stamp in stamps if SCORE_START_NS <= stamp <= SCORE_END_NS]
    span_ns = score[-1] - score[0] if len(score) >= 2 else 0
    gaps = [right - left for left, right in zip(score, score[1:])]
    return {
        "state": "VALID" if not errors else "INVALID",
        "path": str(path),
        "identity": file_identity,
        "valid": not errors,
        "errors": errors,
        "pose_count": len(stamps) + malformed + nonfinite + invalid_quaternion,
        "valid_pose_count": len(stamps),
        "first_timestamp_ns": stamps[0] if stamps else None,
        "last_timestamp_ns": stamps[-1] if stamps else None,
        "strictly_increasing": bool(stamps) and not any(
            right <= left for left, right in zip(stamps, stamps[1:])
        ),
        "score_pose_count": len(score),
        "score_first_timestamp_ns": score[0] if score else None,
        "score_last_timestamp_ns": score[-1] if score else None,
        "score_temporal_span_s": span_ns / 1e9,
        "score_temporal_span_fraction": span_ns / SCORE_DURATION_NS,
        "score_max_adjacent_gap_s": max(gaps) / 1e9 if gaps else None,
    }


def parse_score_log_events(path: Path) -> dict[str, Any]:
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

    parsed: list[dict[str, Any]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8", errors="strict").splitlines(), 1
    ):
        line = ansi.sub("", raw_line)
        direct = ros_sim.search(line) or plain_time.search(line)
        parsed.append({
            "line": line_number,
            "text": line,
            "sim_stamp_ns": seconds_to_ns(direct.group(1)) if direct is not None else None,
        })
    previous: list[Optional[int]] = []
    latest: Optional[int] = None
    for row in parsed:
        if row["sim_stamp_ns"] is not None:
            latest = int(row["sim_stamp_ns"])
        previous.append(latest)
    following: list[Optional[int]] = [None] * len(parsed)
    latest = None
    for index in range(len(parsed) - 1, -1, -1):
        if parsed[index]["sim_stamp_ns"] is not None:
            latest = int(parsed[index]["sim_stamp_ns"])
        following[index] = latest

    def segment(stamp: int) -> str:
        if stamp < SCORE_START_NS:
            return "PREFIX"
        if stamp <= SCORE_END_NS:
            return "SCORE"
        return "POST_SCORE"

    events: list[dict[str, Any]] = []
    init_events: list[dict[str, Any]] = []
    for index, row in enumerate(parsed):
        stamp = row["sim_stamp_ns"]
        if stamp is not None:
            attribution = segment(int(stamp))
        else:
            segments = {
                segment(value)
                for value in (previous[index], following[index])
                if value is not None
            }
            attribution = next(iter(segments)) if len(segments) == 1 else "UNRESOLVED"
        text = str(row["text"])
        categories: list[str] = []
        if failure_pattern.search(text):
            categories.append("failure")
        if restart_pattern.search(text):
            categories.append("restart_or_reset")
        if init_pattern.search(text):
            init_events.append({
                "line": int(row["line"]),
                "sim_stamp_ns": stamp,
                "attribution": attribution,
                "within_or_before_score_end": attribution in {"PREFIX", "SCORE"},
            })
        if categories:
            events.append({
                "line": int(row["line"]),
                "categories": categories,
                "sim_stamp_ns": stamp,
                "score_attribution": attribution,
                "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
    score_events = [event for event in events if event["score_attribution"] == "SCORE"]
    return {
        "events": events,
        "score_failure_events": sum("failure" in event["categories"] for event in score_events),
        "score_restart_or_reset_events": sum(
            "restart_or_reset" in event["categories"] for event in score_events
        ),
        "unresolved_event_count": sum(
            event["score_attribution"] == "UNRESOLVED" for event in events
        ),
        "initialization_events": init_events,
    }


def audit_vins_log(path: Path) -> dict[str, Any]:
    try:
        file_identity = identity(path)
        core = parse_score_log_events(path)
        return {
            "state": "READ",
            "path": str(path),
            "identity": file_identity,
            "receipt_log_event_audit": core,
            "errors": [],
        }
    except (EvidenceError, OSError, UnicodeError, ValueError) as error:
        return {
            "state": "INVALID",
            "path": str(path),
            "errors": [f"VINS_LOG_READ_ERROR:{type(error).__name__}:{error}"],
        }


def parse_ape_values(path: Path) -> dict[str, int | float]:
    values: dict[str, int | float] = {}
    lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    if not lines:
        raise EvidenceError(f"APE_EMPTY:{path}")
    for line_number, line in enumerate(lines, 1):
        if not line or line.count("=") != 1:
            raise EvidenceError(f"APE_LINE_INVALID:{path}:{line_number}")
        key, raw = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", key) is None or key in values:
            raise EvidenceError(f"APE_KEY_INVALID_OR_DUPLICATE:{path}:{line_number}")
        try:
            value = float(raw)
        except ValueError as error:
            raise EvidenceError(f"APE_VALUE_INVALID:{path}:{line_number}") from error
        if not math.isfinite(value):
            raise EvidenceError(f"APE_VALUE_NONFINITE:{path}:{line_number}")
        values[key] = value
    if "init_success" not in values:
        raise EvidenceError(f"APE_INIT_SUCCESS_MISSING:{path}")
    values["init_success"] = exact_integer(values["init_success"], "ape.init_success")
    return values


def reaudit_score_usability(
    trajectory: Mapping[str, Any], log: Mapping[str, Any], ape_init_success: Any
) -> dict[str, Any]:
    failures: list[str] = []
    score_rows = exact_integer(trajectory.get("score_pose_count"), "score_pose_count")
    coverage = finite_number(
        trajectory.get("score_temporal_span_fraction"), "score_temporal_span_fraction"
    )
    maximum_gap_raw = trajectory.get("score_max_adjacent_gap_s")
    maximum_gap = (
        finite_number(maximum_gap_raw, "score_max_adjacent_gap_s")
        if maximum_gap_raw is not None
        else None
    )
    result: dict[str, Any] = {
        "score_start_ns": SCORE_START_NS,
        "score_end_ns": SCORE_END_NS,
        "crop_interval": "inclusive",
        "failure_codes": failures,
        "full_trajectory_rows": exact_integer(
            trajectory.get("valid_pose_count"), "valid_pose_count"
        ),
        "score_trajectory_rows": score_rows,
        "score_first_stamp_ns": trajectory.get("score_first_timestamp_ns"),
        "score_last_stamp_ns": trajectory.get("score_last_timestamp_ns"),
        "score_temporal_span_coverage": coverage,
        "maximum_score_output_gap_s": maximum_gap,
    }
    if score_rows < 2:
        failures.append("INSUFFICIENT_SCORE_TRAJECTORY_ROWS")
    if coverage < MIN_SCORE_SPAN_FRACTION:
        failures.append("SCORE_TEMPORAL_SPAN_COVERAGE_BELOW_GATE")
    if maximum_gap is None or maximum_gap > MAX_SCORE_GAP_NS / 1e9:
        failures.append("SCORE_OUTPUT_GAP_ABOVE_GATE")
    result["ape_init_success"] = ape_init_success
    if ape_init_success != 1:
        failures.append("APE_INITIALIZATION_NOT_SUCCESSFUL")
    core = log.get("receipt_log_event_audit")
    if not isinstance(core, Mapping):
        raise EvidenceError("VINS_LOG_CORE_AUDIT_MISSING")
    core_value = clean_json(dict(core))
    result["log_event_audit"] = core_value
    initialized = any(
        isinstance(event, Mapping) and event.get("within_or_before_score_end") is True
        for event in core_value.get("initialization_events", [])
    )
    result["initialization_before_or_within_score_end"] = initialized
    if not initialized:
        failures.append("NO_INITIALIZATION_EVENT_BEFORE_SCORE_END")
    if exact_integer(core_value.get("score_failure_events"), "score_failure_events") > 0:
        failures.append("SCORE_FAILURE_EVENT_GATE_EXCEEDED")
    if exact_integer(
        core_value.get("score_restart_or_reset_events"), "score_restart_or_reset_events"
    ) > 0:
        failures.append("SCORE_RESTART_RESET_GATE_EXCEEDED")
    if exact_integer(core_value.get("unresolved_event_count"), "unresolved_event_count"):
        failures.append("UNRESOLVED_LOG_EVENT_ATTRIBUTION")
    result["failure_codes"] = failures
    result["status"] = "PASS" if not failures else "FAIL"
    return result


def audit_namespace_manifest(item_id: str, lock_audit: Mapping[str, Any]) -> dict[str, Any]:
    path = ITEM_DIRS[item_id] / "network_namespace_manifest.json"
    errors: list[str] = []
    try:
        value, file_identity = read_json(path)
    except (EvidenceError, OSError) as error:
        return {"state": "INVALID", "path": str(path), "errors": [str(error)]}
    expected_keys = {
        "schema_version", "status", "isolation_scope",
        "machine_exclusive_cpu_scheduling", "uid_inside", "gid_inside",
        "self_network_namespace", "host_network_namespace",
        "self_user_namespace", "host_user_namespace", "interfaces",
        "loopback_operstate", "initial_tcp_listeners", "formal_bind_address",
        "formal_bind_port", "backend_argv_sha256",
    }
    if set(value) != expected_keys:
        errors.append("NETNS_MANIFEST_FIELD_SET_DRIFT")
    expected_values = {
        "schema_version": NETNS_SCHEMA,
        "status": "PASS",
        "isolation_scope": "NETWORK_NAMESPACE_LOOPBACK_ONLY",
        "machine_exclusive_cpu_scheduling": False,
        "uid_inside": 0,
        "gid_inside": 0,
        "interfaces": ["lo"],
        "initial_tcp_listeners": [],
        "formal_bind_address": "127.0.0.1",
    }
    for key, expected in expected_values.items():
        if value.get(key) != expected:
            errors.append(f"NETNS_MANIFEST_VALUE_DRIFT:{key}")
    if value.get("loopback_operstate") not in {"unknown", "up"}:
        errors.append("NETNS_LOOPBACK_NOT_UP")
    self_net, host_net = value.get("self_network_namespace"), value.get("host_network_namespace")
    self_user, host_user = value.get("self_user_namespace"), value.get("host_user_namespace")
    if re.fullmatch(r"net:\[[0-9]+\]", str(self_net)) is None or self_net == host_net:
        errors.append("NETNS_NETWORK_NAMESPACE_NOT_DISTINCT")
    if re.fullmatch(r"user:\[[0-9]+\]", str(self_user)) is None or self_user == host_user:
        errors.append("NETNS_USER_NAMESPACE_NOT_DISTINCT")
    contracts = lock_audit.get("parsed_network_namespace_contracts")
    contract = contracts.get(item_id) if isinstance(contracts, Mapping) else None
    if not isinstance(contract, Mapping):
        errors.append("NETNS_FROZEN_CONTRACT_MISSING")
    else:
        comparisons = {
            "formal_bind_port": contract.get("formal_port"),
            "host_network_namespace": contract.get("host_network_namespace"),
            "host_user_namespace": contract.get("host_user_namespace"),
            "backend_argv_sha256": contract.get("backend_argv_sha256"),
        }
        for key, expected in comparisons.items():
            if value.get(key) != expected:
                errors.append(f"NETNS_FROZEN_BINDING_DRIFT:{key}")
    return {
        "state": "PASS" if not errors else "INVALID",
        "path": str(path),
        "identity": file_identity,
        "manifest": value,
        "errors": errors,
        "network_isolated": not errors,
        "machine_exclusive_cpu_scheduling": False,
    }


def execution_bad_statuses(value: Any, prefix: str = "execution") -> list[str]:
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            current = f"{prefix}.{key}"
            if key == "status" and item in {"FAIL", "INVALID", "ERROR"}:
                errors.append(f"EXECUTION_NESTED_BAD_STATUS:{current}:{item}")
            errors.extend(execution_bad_statuses(item, current))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(execution_bad_statuses(item, f"{prefix}[{index}]"))
    return errors


def audit_v3_pending_guard_evidence(value: Any, phase: str) -> list[str]:
    errors: list[str] = []
    expected_top = {
        "status", "phase", "required_state", "checked_at_local", "items"
    }
    if not isinstance(value, Mapping):
        return [f"V3_PENDING_GUARD_NOT_OBJECT:{phase}"]
    if set(value) != expected_top:
        errors.append(f"V3_PENDING_GUARD_FIELD_SET_DRIFT:{phase}")
    if value.get("status") != "PASS":
        errors.append(f"V3_PENDING_GUARD_NOT_PASS:{phase}")
    if value.get("phase") != phase:
        errors.append(f"V3_PENDING_GUARD_PHASE_DRIFT:{phase}")
    if value.get("required_state") != "CLAIM_AND_RECEIPT_ABSENT":
        errors.append(f"V3_PENDING_GUARD_REQUIRED_STATE_DRIFT:{phase}")
    if not isinstance(value.get("checked_at_local"), str) or not value.get(
        "checked_at_local"
    ):
        errors.append(f"V3_PENDING_GUARD_TIMESTAMP_INVALID:{phase}")
    items = value.get("items")
    if not isinstance(items, Mapping) or set(items) != set(
        V3_PENDING_BACKEND_GUARDS
    ):
        errors.append(f"V3_PENDING_GUARD_ITEM_SET_DRIFT:{phase}")
        return errors
    expected_item_keys = {
        "output_dir", "claim_path", "claim_present",
        "receipt_path", "receipt_present",
    }
    for item_id, paths in V3_PENDING_BACKEND_GUARDS.items():
        row = items.get(item_id)
        if not isinstance(row, Mapping) or set(row) != expected_item_keys:
            errors.append(f"V3_PENDING_GUARD_ITEM_FIELDS_DRIFT:{phase}:{item_id}")
            continue
        for role in ("output_dir", "claim_path", "receipt_path"):
            if row.get(role) != str(paths[role]):
                errors.append(
                    f"V3_PENDING_GUARD_PATH_DRIFT:{phase}:{item_id}:{role}"
                )
        if row.get("claim_present") is not False:
            errors.append(f"V3_PENDING_GUARD_CLAIM_PRESENT:{phase}:{item_id}")
        if row.get("receipt_present") is not False:
            errors.append(f"V3_PENDING_GUARD_RECEIPT_PRESENT:{phase}:{item_id}")
    return errors


def audit_receipt(
    item_id: str,
    lock: Optional[Mapping[str, Any]],
    lock_audit: Mapping[str, Any],
) -> dict[str, Any]:
    base = ITEM_DIRS[item_id]
    receipt_path = RECEIPTS[item_id]
    claim_path = base / CLAIM_NAME
    log_path = base / LOG_NAME
    receipt_exists = receipt_path.exists() or receipt_path.is_symlink()
    claim_exists = claim_path.exists() or claim_path.is_symlink()
    if not receipt_exists:
        return {
            "state": "PENDING_CLAIMED_WITHOUT_RECEIPT" if claim_exists else "PENDING_NOT_STARTED",
            "item_id": item_id,
            "path": str(receipt_path),
            "successful": False,
            "errors": [],
        }
    errors: list[str] = []
    try:
        receipt, receipt_identity = read_json(receipt_path)
    except (EvidenceError, OSError) as error:
        return {
            "state": "INVALID_RECEIPT",
            "item_id": item_id,
            "path": str(receipt_path),
            "successful": False,
            "errors": [str(error)],
        }
    if lock is None or lock_audit.get("state") != "PASS":
        errors.append("RECEIPT_PRESENT_WITHOUT_VALID_V4_LOCK")
        item: Mapping[str, Any] = {}
    else:
        raw_item = lock.get("items", {}).get(item_id)
        item = raw_item if isinstance(raw_item, Mapping) else {}
    expected_top = {
        "schema_version": SUPERVISOR_SCHEMA,
        "item_id": item_id,
        "kind": "backend_replay",
        "launch_allowance_consumed": True,
    }
    for key, expected in expected_top.items():
        if receipt.get(key) != expected:
            errors.append(f"RECEIPT_FIELD_DRIFT:{key}")
    lock_identity = lock_audit.get("identity")
    if not identity_claim_matches(receipt.get("execution_lock"), lock_identity or {}):
        errors.append("RECEIPT_EXECUTION_LOCK_BINDING_DRIFT")
    try:
        claim, claim_identity = read_json(claim_path)
    except (EvidenceError, OSError) as error:
        claim, claim_identity = {}, None
        errors.append(f"CLAIM_INVALID_OR_MISSING:{error}")
    if claim_identity is not None and not identity_claim_matches(receipt.get("claim"), claim_identity):
        errors.append("RECEIPT_CLAIM_IDENTITY_DRIFT")
    if claim:
        claim_expected = {
            "schema_version": SUPERVISOR_SCHEMA,
            "item_id": item_id,
            "launch_allowance_consumed": True,
            "popen_invocation_count_at_claim": 0,
            "retry_count": 0,
        }
        for key, expected in claim_expected.items():
            if claim.get(key) != expected:
                errors.append(f"CLAIM_FIELD_DRIFT:{key}")
        if not identity_claim_matches(claim.get("execution_lock"), lock_identity or {}):
            errors.append("CLAIM_EXECUTION_LOCK_BINDING_DRIFT")
        if item and claim.get("argv") != item.get("argv"):
            errors.append("CLAIM_ARGV_DRIFT")
        errors.extend(
            audit_v3_pending_guard_evidence(
                claim.get("v3_pending_allowance_guard"), "before_claim"
            )
        )
    try:
        process_log_identity = identity(log_path)
        if process_log_identity["size_bytes"] <= 0:
            errors.append("SUPERVISOR_PROCESS_LOG_EMPTY")
        if not identity_claim_matches(receipt.get("process_log"), process_log_identity):
            errors.append("RECEIPT_PROCESS_LOG_IDENTITY_DRIFT")
    except (EvidenceError, OSError) as error:
        process_log_identity = None
        errors.append(f"SUPERVISOR_PROCESS_LOG_INVALID:{error}")

    terminal = receipt.get("terminal_process")
    terminal_rc0 = bool(
        isinstance(terminal, Mapping)
        and terminal.get("status") == "TERMINAL_PROCESS_RC0"
        and terminal.get("popen_invocation_count") == 1
        and terminal.get("child_started") is True
        and terminal.get("raw_return_code") == 0
        and terminal.get("timed_out") is False
        and receipt.get("status") == "TERMINAL_PROCESS_RC0"
    )
    if not terminal_rc0:
        errors.append("TERMINAL_PROCESS_NOT_RC0")
    group = terminal.get("process_group") if isinstance(terminal, Mapping) else None
    group_drained = bool(
        isinstance(group, Mapping)
        and group.get("leader_reaped") is True
        and group.get("process_group_empty") is True
        and group.get("owned_descendants_empty") is True
        and group.get("last_group_members") in (None, [])
        and group.get("last_owned_identities") in (None, [])
    )
    if not group_drained:
        errors.append("PROCESS_GROUP_NOT_DRAINED")

    artifact = receipt.get("artifact_contract")
    artifact_pass = bool(
        isinstance(artifact, Mapping)
        and artifact.get("status") == "PASS"
        and artifact.get("issues") == []
    )
    if not artifact_pass:
        errors.append("ARTIFACT_CONTRACT_NOT_PASS")
    recorded_outputs = artifact.get("outputs") if isinstance(artifact, Mapping) else None
    expected_outputs: tuple[Path, ...] = ()
    if item:
        try:
            expected_outputs = required_output_paths(item, base)
        except EvidenceError as error:
            errors.append(f"LOCK_EXPECTED_OUTPUTS_INVALID:{error}")
    expected_set = {str(path) for path in expected_outputs}
    if not isinstance(recorded_outputs, Mapping) or set(recorded_outputs) != expected_set:
        errors.append("RECEIPT_ARTIFACT_OUTPUT_SET_DRIFT")
    else:
        for raw_path, claim_value in recorded_outputs.items():
            try:
                actual = identity(Path(raw_path))
            except (EvidenceError, OSError) as error:
                errors.append(f"ARTIFACT_OUTPUT_READ_FAILED:{raw_path}:{error}")
                continue
            if actual["size_bytes"] <= 0:
                errors.append(f"ARTIFACT_OUTPUT_EMPTY:{raw_path}")
            if not identity_claim_matches(claim_value, actual):
                errors.append(f"ARTIFACT_OUTPUT_IDENTITY_DRIFT:{raw_path}")
    semantic = artifact.get("semantic_checks") if isinstance(artifact, Mapping) else None
    if not isinstance(semantic, list) or not semantic:
        errors.append("SEMANTIC_CHECKS_MISSING")
    elif any(not isinstance(row, Mapping) or row.get("status") != "PASS" for row in semantic):
        errors.append("SEMANTIC_CHECK_NOT_PASS")

    if expected_outputs:
        allowed_files = expected_set | {str(claim_path), str(receipt_path), str(log_path)}
        seen_files: set[str] = set()
        try:
            for path in base.rglob("*"):
                observed = path.lstat()
                if stat.S_ISLNK(observed.st_mode):
                    errors.append(f"OUTPUT_TREE_SYMLINK_FORBIDDEN:{path}")
                elif stat.S_ISREG(observed.st_mode):
                    seen_files.add(str(path.absolute()))
                elif not stat.S_ISDIR(observed.st_mode):
                    errors.append(f"OUTPUT_TREE_NONREGULAR:{path}")
            if seen_files != allowed_files:
                errors.append(
                    "OUTPUT_TREE_FILE_SET_DRIFT:"
                    f"missing={sorted(allowed_files-seen_files)}:extra={sorted(seen_files-allowed_files)}"
                )
        except OSError as error:
            errors.append(f"OUTPUT_TREE_READ_FAILED:{error}")

    execution = receipt.get("execution_integrity")
    execution_pass = bool(
        isinstance(execution, Mapping)
        and execution.get("status") == "PASS"
        and execution.get("supervisor_error") is None
    )
    if not execution_pass:
        errors.append("EXECUTION_INTEGRITY_NOT_PASS")
    if isinstance(execution, Mapping):
        errors.extend(execution_bad_statuses(execution))
        for field in ("authority_before_popen", "authority_post", "quiescence_after_claim", "postflight", "dependency_bindings_post"):
            section = execution.get(field)
            if not isinstance(section, Mapping) or section.get("status") != "PASS":
                errors.append(f"EXECUTION_REQUIRED_SUBCHECK_NOT_PASS:{field}")
        guard_fields = {
            "v3_pending_allowance_before_claim": "before_claim",
            "v3_pending_allowance_before_popen": "after_claim_before_popen",
            "v3_pending_allowance_postflight": "postflight",
        }
        for field, phase in guard_fields.items():
            errors.extend(
                audit_v3_pending_guard_evidence(execution.get(field), phase)
            )
        if claim and execution.get("v3_pending_allowance_before_claim") != (
            claim.get("v3_pending_allowance_guard")
        ):
            errors.append("EXECUTION_CLAIM_V3_PENDING_GUARD_BINDING_DRIFT")
        if execution.get("dependency_bindings_before") != {}:
            errors.append("EXECUTION_V4_DEPENDENCIES_BEFORE_NOT_EMPTY")
        if execution.get("dependency_bindings_post") != {"status": "PASS", "bindings": {}}:
            errors.append("EXECUTION_V4_DEPENDENCIES_POST_DRIFT")
        if lock is not None and item:
            base_environment = lock.get("policy", {}).get("base_environment")
            declared = item.get("env")
            if isinstance(base_environment, Mapping) and isinstance(declared, Mapping):
                expected_environment = dict(base_environment)
                if "PWD" in expected_environment or "PWD" in declared or set(expected_environment) & set(declared):
                    errors.append("LOCK_ENVIRONMENT_OVERLAP_INVALID")
                else:
                    expected_environment.update(declared)
                    expected_environment["PWD"] = str(ROOT)
                    if execution.get("effective_environment") != expected_environment:
                        errors.append("EXECUTION_EFFECTIVE_ENVIRONMENT_DRIFT")

    namespace_audit = audit_namespace_manifest(item_id, lock_audit)
    if namespace_audit.get("state") != "PASS":
        errors.extend(f"NAMESPACE:{value}" for value in namespace_audit.get("errors", []))

    trajectory = audit_trajectory(base / "vins_output/vio.csv")
    log = audit_vins_log(base / "vins.log")
    try:
        ape = parse_ape_values(base / "ape.txt")
    except (EvidenceError, OSError, UnicodeError) as error:
        ape = {}
        errors.append(f"APE_AUDIT_INVALID:{error}")
    score_reaudit: Optional[dict[str, Any]] = None
    if not trajectory.get("valid"):
        errors.append("TRAJECTORY_NOT_VALID")
    if log.get("state") != "READ":
        errors.append("VINS_LOG_NOT_VALID")
    if trajectory.get("valid") and log.get("state") == "READ" and ape:
        try:
            score_reaudit = reaudit_score_usability(trajectory, log, ape.get("init_success"))
        except EvidenceError as error:
            errors.append(f"SCORE_REAUDIT_FAILED:{error}")
    receipt_score = receipt.get("score_usability")
    score_pass = bool(
        isinstance(receipt_score, Mapping)
        and receipt_score.get("status") == "PASS"
        and score_reaudit is not None
        and dict(receipt_score) == score_reaudit
        and score_reaudit.get("status") == "PASS"
    )
    if not score_pass:
        errors.append("SCORE_USABILITY_NOT_EXACT_PASS")

    if not terminal_rc0:
        expected_disposition = "PROCESS_FAILED"
    elif not execution_pass:
        expected_disposition = "EXECUTION_INTEGRITY_FAILED"
    elif not artifact_pass:
        expected_disposition = "ARTIFACT_CONTRACT_FAILED"
    elif not isinstance(receipt_score, Mapping) or receipt_score.get("status") != "PASS":
        expected_disposition = "RETAINED_UNUSABLE_SCORE"
    else:
        expected_disposition = "ACCEPTED"
    if receipt.get("overall_disposition") != expected_disposition:
        errors.append(
            "RECEIPT_OVERALL_DISPOSITION_DRIFT:"
            f"{receipt.get('overall_disposition')}!={expected_disposition}"
        )

    accepted = bool(
        terminal_rc0
        and group_drained
        and artifact_pass
        and execution_pass
        and score_pass
        and namespace_audit.get("state") == "PASS"
        and not errors
        and receipt.get("overall_disposition") == "ACCEPTED"
    )
    state = "ACCEPTED" if accepted else (
        "TERMINAL_FAILED" if receipt.get("launch_allowance_consumed") is True else "INVALID_RECEIPT"
    )
    return {
        "state": state,
        "item_id": item_id,
        "path": str(receipt_path),
        "identity": receipt_identity,
        "claim_identity": claim_identity,
        "process_log_identity": process_log_identity,
        "successful": accepted,
        "terminal_process_rc0": terminal_rc0,
        "raw_return_code": terminal.get("raw_return_code") if isinstance(terminal, Mapping) else None,
        "timed_out": terminal.get("timed_out") if isinstance(terminal, Mapping) else None,
        "artifact_contract_status": artifact.get("status") if isinstance(artifact, Mapping) else None,
        "execution_integrity_status": execution.get("status") if isinstance(execution, Mapping) else None,
        "score_usability_status": receipt_score.get("status") if isinstance(receipt_score, Mapping) else None,
        "overall_disposition": receipt.get("overall_disposition"),
        "namespace_isolation": namespace_audit,
        "trajectory": {key: value for key, value in trajectory.items() if key != "stamps_ns"},
        "ape_values": ape,
        "score_usability_reaudit": score_reaudit,
        "errors": list(dict.fromkeys(errors)),
    }


def verify_reference_rows() -> dict[str, Any]:
    raw_identity = verify_known_identity(RAW_BAG)
    try:
        import rosbag
    except ImportError as error:
        raise EvidenceError("ROSBAG_PYTHON_UNAVAILABLE") from error
    stamps: list[int] = []
    try:
        with rosbag.Bag(str(RAW_BAG)) as bag:
            for _, message, _ in bag.read_messages(topics=["/aqualoc/colmap_gt"]):
                if not hasattr(message, "header"):
                    continue
                stamp = int(message.header.stamp.to_nsec())
                if SCORE_START_NS <= stamp <= SCORE_END_NS:
                    stamps.append(stamp)
    except Exception as error:
        raise EvidenceError(f"REFERENCE_BAG_READ_FAILED:{type(error).__name__}:{error}") from error
    if len(stamps) != REFERENCE_ROWS:
        raise EvidenceError(f"REFERENCE_ROW_COUNT_DRIFT:{len(stamps)}!={REFERENCE_ROWS}")
    if stamps[0] != SCORE_START_NS or stamps[-1] != SCORE_END_NS:
        raise EvidenceError("REFERENCE_SCORE_ENDPOINT_DRIFT")
    if any(right <= left for left, right in zip(stamps, stamps[1:])):
        raise EvidenceError("REFERENCE_TIMESTAMPS_NOT_STRICT")
    return {
        "identity": raw_identity,
        "topic": "/aqualoc/colmap_gt",
        "score_row_count": len(stamps),
        "score_first_timestamp_ns": stamps[0],
        "score_last_timestamp_ns": stamps[-1],
        "fixed_common_coverage_denominator": REFERENCE_ROWS,
    }


def decimal_seconds(stamp_ns: int) -> str:
    return format(Decimal(stamp_ns) / Decimal("1000000000"), "f")


def build_evaluator_command(output_dir: Path) -> list[str]:
    command = [
        str(PYTHON38), str(EVALUATOR),
        "--reference-bag", str(RAW_BAG),
        "--reference-topic", "/aqualoc/colmap_gt",
    ]
    for item_id in ITEM_ORDER:
        command.extend([
            "--arm",
            f"{EVALUATOR_NAMES[item_id]}={ITEM_DIRS[item_id] / 'vins_output/vio.csv'}",
        ])
    for item_id in ITEM_ORDER:
        config = (
            ITEM_DIRS[item_id] / "vins_aqualoc_archaeo_origin.yaml"
            if item_id == "vanilla_origin_native_image_context"
            else ITEM_DIRS[item_id] / "vins_aqualoc_archaeo_external.yaml"
        )
        command.extend(["--arm-config", f"{EVALUATOR_NAMES[item_id]}={config}"])
    command.extend([
        "--nominal-reference-rate-hz", "1.0",
        "--nominal-estimate-rate-hz", "10.0",
        "--evaluation-rate-hz", "1.0",
        "--max-reference-gap-s", "2.5",
        "--max-estimate-gap-s", "0.25",
        "--window-start-s", decimal_seconds(SCORE_START_NS),
        "--window-end-s", decimal_seconds(SCORE_END_NS),
        "--rpe-delta-s", "1.0",
        "--min-ape-poses", str(FORMAL_APE_MIN_POSES),
        "--min-ape-span-s", "10.0",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", str(MIN_RPE_PAIRS),
        "--contrast-name", "SAMEHISTORY_SYSTEM_A10_V4_BACKEND_RECOVERY_SCORE_2400_2800",
        "--output-dir", str(output_dir),
    ])
    return command


def common_input_manifest(
    lock_audit: Mapping[str, Any],
    receipt_audits: Mapping[str, Mapping[str, Any]],
    reference: Mapping[str, Any],
) -> dict[str, Any]:
    files: dict[str, Any] = {
        "execution_lock": lock_audit["identity"],
        "protocol": identity(PROTOCOL),
        "analyzer": identity(Path(__file__)),
        "evaluator": identity(EVALUATOR),
        "evaluator_core": identity(EVALUATOR_CORE),
        "python3_8": identity(PYTHON38),
        "raw_bag": reference["identity"],
    }
    for item_id in ITEM_ORDER:
        audit = receipt_audits[item_id]
        files[f"{item_id}_receipt"] = audit["identity"]
        base = ITEM_DIRS[item_id]
        files[f"{item_id}_trajectory"] = identity(base / "vins_output/vio.csv")
        files[f"{item_id}_config"] = identity(
            base / (
                "vins_aqualoc_archaeo_origin.yaml"
                if item_id == "vanilla_origin_native_image_context"
                else "vins_aqualoc_archaeo_external.yaml"
            )
        )
    return {
        "schema_version": "aqua-fe-a10-v4-common-support-input-manifest-v1",
        "files": files,
        "arm_order": list(ITEM_ORDER),
        "score": {
            "source_indices_inclusive": list(SCORE_SOURCE_RANGE),
            "start_ns": SCORE_START_NS,
            "end_ns": SCORE_END_NS,
            "native_reference_rows": REFERENCE_ROWS,
            "uniform_grid_count": UNIFORM_GRID_COUNT,
        },
        "protocol": {
            "evaluation_rate_hz": 1.0,
            "max_reference_gap_s": 2.5,
            "max_estimate_gap_s": 0.25,
            "rpe_delta_s": 1.0,
            "minimum_common_rows": MIN_COMMON_ROWS,
            "minimum_uniform_common_coverage": 0.70,
            "minimum_conservative_fixed_denominator_index": 0.70,
            "minimum_descriptive_rpe_pairs": MIN_RPE_PAIRS,
            "formal_ape_minimum_poses": FORMAL_APE_MIN_POSES,
            "formal_ape_gate_open": False,
        },
    }


def verify_frozen_inputs_unchanged(
    manifest: Mapping[str, Any],
    lock_audit: Mapping[str, Any],
    receipt_audits: Mapping[str, Mapping[str, Any]],
) -> None:
    if not identity_claim_matches(lock_audit.get("identity"), identity(EXECUTION_LOCK)):
        raise EvidenceError("EXECUTION_LOCK_CHANGED_DURING_ANALYSIS")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise EvidenceError("COMMON_INPUT_MANIFEST_FILES_MISSING")
    for label, claim in files.items():
        if not isinstance(claim, Mapping) or not isinstance(claim.get("path"), str):
            raise EvidenceError(f"COMMON_INPUT_CLAIM_INVALID:{label}")
        if not identity_claim_matches(claim, identity(Path(str(claim["path"])))):
            raise EvidenceError(f"COMMON_INPUT_CHANGED:{label}")
    for item_id in ITEM_ORDER:
        if not identity_claim_matches(
            receipt_audits[item_id].get("identity"), identity(RECEIPTS[item_id])
        ):
            raise EvidenceError(f"RECEIPT_CHANGED_DURING_ANALYSIS:{item_id}")


def adjudicate_common_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if set(summary) != {"protocol", "support", "reference", "arms"}:
        errors.append("COMMON_SUMMARY_TOP_LEVEL_SCHEMA_DRIFT")
    protocol = summary.get("protocol")
    support = summary.get("support")
    arms = summary.get("arms")
    if not isinstance(protocol, Mapping):
        errors.append("COMMON_PROTOCOL_MISSING")
        protocol = {}
    protocol_expected = {
        "contrast_name": "SAMEHISTORY_SYSTEM_A10_V4_BACKEND_RECOVERY_SCORE_2400_2800",
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
    }
    for key, expected in protocol_expected.items():
        if protocol.get(key) != expected:
            errors.append(f"COMMON_PROTOCOL_DRIFT:{key}")
    for key, expected in (
        ("window_start_s", SCORE_START_NS / 1e9),
        ("window_end_s", SCORE_END_NS / 1e9),
    ):
        try:
            if abs(finite_number(protocol.get(key), key) - expected) > 1e-6:
                errors.append(f"COMMON_PROTOCOL_DRIFT:{key}")
        except EvidenceError:
            errors.append(f"COMMON_PROTOCOL_INVALID:{key}")
    if not isinstance(support, Mapping):
        errors.append("COMMON_SUPPORT_MISSING")
        support = {}
    expected_support_keys = {
        "grid_count", "matched_count", "common_span_s", "common_coverage",
        "segment_count", "rpe_pairs", "ape_valid", "rpe_valid",
        "window_duration_s",
    }
    if set(support) != expected_support_keys:
        errors.append("COMMON_SUPPORT_FIELD_SET_DRIFT")
    try:
        grid = exact_integer(support.get("grid_count"), "support.grid_count")
        matched = exact_integer(support.get("matched_count"), "support.matched_count")
        rpe_pairs = exact_integer(support.get("rpe_pairs"), "support.rpe_pairs")
        coverage = finite_number(support.get("common_coverage"), "support.common_coverage")
    except EvidenceError as error:
        grid, matched, rpe_pairs, coverage = -1, -1, -1, -1.0
        errors.append(str(error))
    if grid != UNIFORM_GRID_COUNT:
        errors.append("UNIFORM_GRID_COUNT_NOT_20")
    if not 0 <= matched <= grid:
        errors.append("COMMON_MATCHED_COUNT_OUT_OF_RANGE")
    if grid > 0 and abs(coverage - matched / grid) > 1e-12:
        errors.append("UNIFORM_COMMON_COVERAGE_INCONSISTENT")
    conservative = matched / REFERENCE_ROWS if matched >= 0 else -1.0
    common_gate = bool(
        matched >= MIN_COMMON_ROWS
        and coverage >= 0.70
        and conservative >= 0.70
    )
    rpe_gate = rpe_pairs >= MIN_RPE_PAIRS
    if support.get("ape_valid") is not False:
        errors.append("FORMAL_APE_GATE_UNEXPECTEDLY_OPEN")
    if support.get("rpe_valid") is not rpe_gate:
        errors.append("DESCRIPTIVE_RPE_GATE_FLAG_DRIFT")
    if not isinstance(arms, Mapping) or set(arms) != {EVALUATOR_NAMES[item] for item in ITEM_ORDER}:
        # The frozen evaluator serializes JSON with sort_keys=True, so JSON
        # object order is intentionally ignored here.  Reports are rebuilt in
        # ITEM_ORDER and never metric-sorted.
        errors.append("COMMON_ARM_SET_DRIFT")
        arms = {}
    descriptive: dict[str, Any] = {}
    for item_id in ITEM_ORDER:
        name = EVALUATOR_NAMES[item_id]
        metrics = arms.get(name)
        if not isinstance(metrics, Mapping):
            errors.append(f"COMMON_ARM_MISSING:{item_id}")
            continue
        try:
            if exact_integer(metrics.get("matched_count"), f"{item_id}.matched_count") != matched:
                errors.append(f"COMMON_ARM_MATCHED_COUNT_DRIFT:{item_id}")
            if exact_integer(metrics.get("rpe_pairs"), f"{item_id}.rpe_pairs") != rpe_pairs:
                errors.append(f"COMMON_ARM_RPE_PAIR_COUNT_DRIFT:{item_id}")
        except EvidenceError as error:
            errors.append(str(error))
        values: dict[str, Any] = {}
        for key in (
            "ape_rmse_m", "ape_median_m", "ape_max_m",
            "rpe_rmse_m", "rpe_median_m", "rpe_max_m",
        ):
            raw = metrics.get(key)
            if raw is None:
                values[key] = None
            else:
                try:
                    parsed = finite_number(raw, f"{item_id}.{key}")
                    if parsed < 0:
                        errors.append(f"COMMON_METRIC_NEGATIVE:{item_id}:{key}")
                    values[key] = parsed
                except EvidenceError as error:
                    errors.append(str(error))
                    values[key] = None
        descriptive[item_id] = values
    release = bool(not errors and common_gate)
    if release and not rpe_gate:
        for values in descriptive.values():
            for key in ("rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
                values[key] = None
    return {
        "state": "DESCRIPTIVE_RESULTS_AVAILABLE" if release else (
            "COMMON_SUPPORT_GATE_FAILED" if not errors else "INVALID_COMMON_SUPPORT"
        ),
        "uniform_grid_count": grid,
        "uniform_common_matched_count": matched,
        "uniform_common_coverage": coverage,
        "conservative_fixed_denominator_index": conservative,
        "uniform_exact_1s_rpe_pairs": rpe_pairs,
        "common_support_gate_pass": common_gate,
        "descriptive_rpe_gate_pass": rpe_gate,
        "formal_ape_gate_open": False,
        "formal_winner_permitted": False,
        "metrics_released": release,
        "descriptive_proxy_metrics_fixed_order": descriptive if release else {},
        "errors": errors,
    }


def run_common_support(
    staging: Path,
    lock_audit: Mapping[str, Any],
    receipt_audits: Mapping[str, Mapping[str, Any]],
    *,
    enabled: bool,
) -> tuple[Optional[dict[str, Any]], dict[str, Any], Optional[dict[str, Any]]]:
    if not enabled:
        return None, {"state": "READY_BUT_EVALUATOR_DISABLED"}, None
    reference = verify_reference_rows()
    common_dir = staging / "common_support"
    common_dir.mkdir()
    manifest = common_input_manifest(lock_audit, receipt_audits, reference)
    manifest_path = common_dir / "a10_v4_evaluator_input_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    command = build_evaluator_command(common_dir)
    try:
        process = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=180,
        )
        process_receipt = {
            "schema_version": "aqua-fe-a10-v4-common-support-process-receipt-v1",
            "command": command,
            "raw_return_code": process.returncode,
            "timed_out": False,
            "stdout": process.stdout,
        }
    except subprocess.TimeoutExpired as error:
        process_receipt = {
            "schema_version": "aqua-fe-a10-v4-common-support-process-receipt-v1",
            "command": command,
            "raw_return_code": None,
            "timed_out": True,
            "stdout": (error.stdout or "") if isinstance(error.stdout, str) else "",
        }
    (common_dir / "evaluator_process_receipt.json").write_text(
        json.dumps(process_receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    verify_frozen_inputs_unchanged(manifest, lock_audit, receipt_audits)
    if process_receipt["raw_return_code"] != 0 or process_receipt["timed_out"] is not False:
        return None, {
            "state": "EVALUATOR_PROCESS_FAILED",
            "input_manifest": manifest,
            "process_receipt": process_receipt,
        }, reference
    summary_path = common_dir / "common_support_summary.json"
    summary, summary_identity = read_json(summary_path)
    adjudication = adjudicate_common_summary(summary)
    required_files = {
        "a10_v4_evaluator_input_manifest.json",
        "evaluator_process_receipt.json",
        "common_support_summary.json",
        "common_grid_audit.csv",
        "common_support_metrics.csv",
    }
    actual_files = {
        path.name for path in common_dir.iterdir()
        if path.is_file() and not path.is_symlink()
    }
    if actual_files != required_files:
        adjudication["errors"].append(
            f"COMMON_RESULT_FILE_SET_DRIFT:{sorted(actual_files)}"
        )
        adjudication["state"] = "INVALID_COMMON_SUPPORT"
        adjudication["metrics_released"] = False
        adjudication["descriptive_proxy_metrics_fixed_order"] = {}
    return summary, {
        "state": "PASS" if adjudication["state"] == "DESCRIPTIVE_RESULTS_AVAILABLE" else adjudication["state"],
        "input_manifest": manifest,
        "process_receipt": process_receipt,
        "summary_identity": summary_identity,
        "adjudication": adjudication,
    }, reference


def build_system_rows(
    receipt_audits: Mapping[str, Mapping[str, Any]],
    accuracy: Mapping[str, Any],
) -> list[dict[str, Any]]:
    metrics = accuracy.get("descriptive_proxy_metrics_fixed_order")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    rows: list[dict[str, Any]] = []
    for item_id in ITEM_ORDER:
        audit = receipt_audits[item_id]
        trajectory = audit.get("trajectory")
        trajectory = trajectory if isinstance(trajectory, Mapping) else {}
        metric = metrics.get(item_id)
        metric = metric if isinstance(metric, Mapping) else {}
        rows.append({
            "method": item_id,
            "attempt_state": audit.get("state"),
            "accepted": audit.get("successful") is True,
            "raw_return_code": audit.get("raw_return_code"),
            "artifact_contract_status": audit.get("artifact_contract_status"),
            "execution_integrity_status": audit.get("execution_integrity_status"),
            "score_usability_status": audit.get("score_usability_status"),
            "score_pose_count": trajectory.get("score_pose_count"),
            "score_temporal_span_fraction": trajectory.get("score_temporal_span_fraction"),
            "score_max_adjacent_gap_s": trajectory.get("score_max_adjacent_gap_s"),
            "ape_proxy_rmse_m": metric.get("ape_rmse_m"),
            "ape_proxy_median_m": metric.get("ape_median_m"),
            "ape_proxy_max_m": metric.get("ape_max_m"),
            "rpe_descriptive_rmse_m": metric.get("rpe_rmse_m"),
            "rpe_descriptive_median_m": metric.get("rpe_median_m"),
            "rpe_descriptive_max_m": metric.get("rpe_max_m"),
            "error_codes": list(audit.get("errors") or []),
        })
    return rows


def build_bundle(staging: Path, *, run_evaluator: bool) -> dict[str, Any]:
    lock, lock_audit = inspect_lock()
    sources = audit_v3_sources(lock_audit)
    receipts = {
        item_id: audit_receipt(item_id, lock, lock_audit) for item_id in ITEM_ORDER
    }
    all_accepted = all(receipts[item_id].get("successful") is True for item_id in ITEM_ORDER)
    readiness_errors: list[str] = []
    if lock_audit.get("state") != "PASS":
        readiness_errors.append(f"LOCK_NOT_PASS:{lock_audit.get('state')}")
    if sources.get("state") != "PASS":
        readiness_errors.append(f"SOURCE_PROVENANCE_NOT_PASS:{sources.get('state')}")
    for item_id in ITEM_ORDER:
        if not receipts[item_id].get("successful"):
            readiness_errors.append(f"BACKEND_NOT_ACCEPTED:{item_id}:{receipts[item_id].get('state')}")

    summary: Optional[dict[str, Any]] = None
    reference: Optional[dict[str, Any]] = None
    if not readiness_errors:
        summary, common_audit, reference = run_common_support(
            staging, lock_audit, receipts, enabled=run_evaluator
        )
    else:
        common_audit = {
            "state": "WITHHELD_PREREQUISITES_NOT_PASS",
            "withholding_reasons": readiness_errors,
        }
    adjudication = common_audit.get("adjudication")
    if not isinstance(adjudication, Mapping):
        adjudication = {
            "state": common_audit.get("state"),
            "uniform_grid_count": UNIFORM_GRID_COUNT,
            "uniform_common_matched_count": None,
            "uniform_common_coverage": None,
            "conservative_fixed_denominator_index": None,
            "uniform_exact_1s_rpe_pairs": None,
            "common_support_gate_pass": False,
            "descriptive_rpe_gate_pass": False,
            "formal_ape_gate_open": False,
            "formal_winner_permitted": False,
            "metrics_released": False,
            "descriptive_proxy_metrics_fixed_order": {},
            "errors": [],
        }
    if readiness_errors:
        analysis_state = (
            "PENDING"
            if all(receipts[item]["state"].startswith("PENDING") for item in ITEM_ORDER)
            and lock_audit.get("state") in {"PASS", "PENDING_MISSING_EXECUTION_LOCK"}
            and sources.get("state") in {"PASS", "PASS_SOURCES_LOCK_PENDING"}
            else "PREREQUISITES_FAILED_OR_INCOMPLETE"
        )
    elif common_audit.get("state") == "READY_BUT_EVALUATOR_DISABLED":
        analysis_state = "READY_FOR_CPU_COMMON_SUPPORT_EVALUATOR"
    elif adjudication.get("state") == "DESCRIPTIVE_RESULTS_AVAILABLE":
        analysis_state = "DESCRIPTIVE_RESULTS_AVAILABLE_SECONDARY_ONLY"
    else:
        analysis_state = "COMMON_SUPPORT_NOT_ACCEPTED"
    accuracy = dict(adjudication)
    rows = build_system_rows(receipts, accuracy)
    return {
        "schema_version": ANALYSIS_SCHEMA,
        "analysis_state": analysis_state,
        "evidence_scope": EVIDENCE_SCOPE,
        "paper_primary_evidence_permitted": False,
        "machine_exclusive_cpu_scheduling": False,
        "network_isolation_scope": "NETWORK_NAMESPACE_LOOPBACK_ONLY",
        "protocol": identity(PROTOCOL),
        "execution_lock": lock_audit,
        "v3_source_provenance": sources,
        "receipt_audits": receipts,
        "all_three_v4_backends_accepted": all_accepted,
        "readiness_errors": readiness_errors,
        "reference_audit": reference,
        "common_support_audit": common_audit,
        "common_support_summary": summary,
        "accuracy": accuracy,
        "systems": rows,
        "interpretation_policy": {
            "fixed_arm_order": list(ITEM_ORDER),
            "score_source_indices_inclusive": list(SCORE_SOURCE_RANGE),
            "feed_source_indices_inclusive": list(FEED_SOURCE_RANGE),
            "formal_ape_gate_open": False,
            "formal_winner_permitted": False,
            "ranking_permitted": False,
            "significance_testing_permitted": False,
            "failure_as_zero_permitted": False,
            "cross_window_mean_permitted": False,
            "required_disclosures": [
                "v4 is a new backend attempt family; the failed v3 Vanilla attempt is retained and not rerun.",
                "The v3 KLT/AQUA backend launch allowances remain unconsumed; only accepted v3 frontend artifacts are inputs.",
                "Loopback-only network namespaces isolate ROS networking but do not provide machine-exclusive CPU scheduling.",
                "The formal APE gate is closed because 21 native reference poses and 20 uniform samples are below the frozen 30-pose minimum.",
                "Any released APE is a descriptive aligned proxy; any released RPE is descriptive only.",
                "No winner, rank, significance statement, or failure-as-zero comparison is permitted.",
            ],
        },
    }


def write_rows_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    fields = [
        "method", "attempt_state", "accepted", "raw_return_code",
        "artifact_contract_status", "execution_integrity_status",
        "score_usability_status", "score_pose_count",
        "score_temporal_span_fraction", "score_max_adjacent_gap_s",
        "ape_proxy_rmse_m", "ape_proxy_median_m", "ape_proxy_max_m",
        "rpe_descriptive_rmse_m", "rpe_descriptive_median_m",
        "rpe_descriptive_max_m", "error_codes",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            output = {key: row.get(key) for key in fields}
            output["accepted"] = int(bool(output["accepted"]))
            output["error_codes"] = ";".join(row.get("error_codes") or [])
            writer.writerow(output)


def format_number(value: Any, digits: int = 6) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else "n/a"


def write_report(path: Path, bundle: Mapping[str, Any]) -> None:
    lines = [
        "# A10 v4 backend-recovery analysis",
        "",
        f"Analysis state: `{bundle.get('analysis_state')}`.",
        "",
        f"Evidence scope: `{bundle.get('evidence_scope')}`. Primary-paper evidence permitted: `false`.",
        "",
        "Each backend ran in a fresh loopback-only network namespace. CPU, memory, I/O, and scheduler time were not machine exclusive.",
        "",
        "## Prior-attempt provenance",
        "",
        "The failed v3 Vanilla receipt remains `PROCESS_FAILED` and was not rerun. The v3 KLT/AQUA backend attempts remain unstarted; v4 uses only the accepted v3 KLT-adoption and AQUA-FE-build artifacts as frozen external inputs.",
        "",
        f"Source audit state: `{bundle.get('v3_source_provenance', {}).get('state')}`.",
        "",
        "## Backend acceptance and score usability",
        "",
        "| System | Attempt | child RC | artifact | execution | score | score poses | span | max gap (s) |",
        "|---|---|---:|---|---|---|---:|---:|---:|",
    ]
    for row in bundle.get("systems", []):
        lines.append(
            f"| `{row.get('method')}` | {row.get('attempt_state')} | "
            f"{row.get('raw_return_code') if row.get('raw_return_code') is not None else 'n/a'} | "
            f"{row.get('artifact_contract_status') or 'n/a'} | "
            f"{row.get('execution_integrity_status') or 'n/a'} | "
            f"{row.get('score_usability_status') or 'n/a'} | "
            f"{row.get('score_pose_count') if row.get('score_pose_count') is not None else 'n/a'} | "
            f"{format_number(row.get('score_temporal_span_fraction'), 3)} | "
            f"{format_number(row.get('score_max_adjacent_gap_s'), 3)} |"
        )
    accuracy = bundle.get("accuracy")
    accuracy = accuracy if isinstance(accuracy, Mapping) else {}
    lines.extend([
        "",
        "## Common support and descriptive accuracy",
        "",
        f"Common-support state: `{accuracy.get('state')}`.",
        "",
        f"Formal APE gate open: `{accuracy.get('formal_ape_gate_open')}`; winner permitted: `{accuracy.get('formal_winner_permitted')}`.",
        "",
        f"Uniform grid: `{accuracy.get('uniform_grid_count')}`; common matched: `{accuracy.get('uniform_common_matched_count')}`; matched/20: `{accuracy.get('uniform_common_coverage')}`; matched/21 conservative index: `{accuracy.get('conservative_fixed_denominator_index')}`; exact 1 s RPE pairs: `{accuracy.get('uniform_exact_1s_rpe_pairs')}`.",
    ])
    if accuracy.get("metrics_released") is True:
        lines.extend([
            "",
            "The APE columns below are aligned proxy diagnostics, not formal APE. RPE is descriptive only. Fixed preregistered arm order is preserved.",
            "",
            "| System | APE proxy RMSE | APE proxy median | APE proxy max | RPE RMSE | RPE median | RPE max |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ])
        for row in bundle.get("systems", []):
            lines.append(
                f"| `{row.get('method')}` | {format_number(row.get('ape_proxy_rmse_m'))} | "
                f"{format_number(row.get('ape_proxy_median_m'))} | {format_number(row.get('ape_proxy_max_m'))} | "
                f"{format_number(row.get('rpe_descriptive_rmse_m'))} | {format_number(row.get('rpe_descriptive_median_m'))} | "
                f"{format_number(row.get('rpe_descriptive_max_m'))} |"
            )
    else:
        lines.extend(["", "Descriptive metrics are withheld because their preregistered prerequisites are not all satisfied."])
    lines.extend(["", "## Mandatory disclosures", ""])
    policy = bundle.get("interpretation_policy")
    if isinstance(policy, Mapping):
        for disclosure in policy.get("required_disclosures", []):
            lines.append(f"- {disclosure}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_tree(root: Path) -> None:
    directories: list[Path] = []
    for current_raw, directory_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current = Path(current_raw)
        directories.append(current)
        for name in directory_names:
            path = current / name
            if path.is_symlink() or not path.is_dir():
                raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_DIRECTORY:{path}")
        for name in file_names:
            path = current / name
            observed = path.lstat()
            if not stat.S_ISREG(observed.st_mode):
                raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_FILE:{path}")
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    for directory in reversed(directories):
        fsync_directory(directory)


@contextmanager
def blocked_termination_signals():
    blocked = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, blocked)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def rename_directory_noreplace(source: Path, destination: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise EvidenceError("RENAMEAT2_NOREPLACE_UNAVAILABLE")
    renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if result != 0:
        value = ctypes.get_errno()
        if value == errno.EEXIST:
            raise EvidenceError(f"ANALYSIS_OUTPUT_ALREADY_EXISTS:{destination}")
        raise EvidenceError(f"ANALYSIS_OUTPUT_NOREPLACE_RENAME_FAILED:{os.strerror(value)}")


def relative_file_claims(root: Path, *, excluded: set[str]) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        observed = path.lstat()
        if stat.S_ISLNK(observed.st_mode):
            raise EvidenceError(f"ANALYSIS_OUTPUT_SYMLINK_FORBIDDEN:{path}")
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode):
            raise EvidenceError(f"ANALYSIS_OUTPUT_NONREGULAR_FORBIDDEN:{path}")
        if relative in excluded:
            continue
        actual = identity(path)
        claims[relative] = {
            "size_bytes": actual["size_bytes"],
            "sha256": actual["sha256"],
        }
    return claims


def analysis_output_manifest(staging: Path, logical_output: Path, run_evaluator: bool) -> dict[str, Any]:
    return {
        "schema_version": "aqua-fe-a10-v4-analysis-output-manifest-v1",
        "status": "COMPLETE_ATOMIC_ANALYSIS_OUTPUT",
        "logical_output_dir": str(logical_output),
        "evaluator_enabled": run_evaluator,
        "producer_analyzer": identity(Path(__file__)),
        "files": relative_file_claims(staging, excluded={"analysis_output_manifest.json"}),
    }


def verify_existing_output(output_dir: Path, run_evaluator: bool) -> dict[str, Any]:
    if output_dir.is_symlink() or not output_dir.is_dir():
        raise EvidenceError(f"EXISTING_OUTPUT_NOT_DIRECTORY:{output_dir}")
    manifest, _manifest_identity = read_json(output_dir / "analysis_output_manifest.json")
    if (
        manifest.get("schema_version") != "aqua-fe-a10-v4-analysis-output-manifest-v1"
        or manifest.get("status") != "COMPLETE_ATOMIC_ANALYSIS_OUTPUT"
        or manifest.get("logical_output_dir") != str(output_dir)
        or manifest.get("evaluator_enabled") is not run_evaluator
        or not identity_claim_matches(manifest.get("producer_analyzer"), identity(Path(__file__)))
    ):
        raise EvidenceError("EXISTING_OUTPUT_MANIFEST_DRIFT")
    actual = relative_file_claims(output_dir, excluded={"analysis_output_manifest.json"})
    if manifest.get("files") != actual:
        raise EvidenceError("EXISTING_OUTPUT_FILE_IDENTITY_DRIFT")
    bundle, _ = read_json(output_dir / "samehistory_system_a10_v4_analysis_bundle.json")
    return bundle


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--no-evaluator",
        action="store_true",
        help="audit source/receipt readiness without invoking the frozen CPU evaluator",
    )
    args = parser.parse_args(argv)
    output_dir = args.output_dir.absolute()
    run_evaluator = not args.no_evaluator
    if output_dir.exists() or output_dir.is_symlink():
        try:
            bundle = verify_existing_output(output_dir, run_evaluator)
        except Exception as error:
            print(f"analysis_error={type(error).__name__}:{error}", file=sys.stderr)
            return 2
        print(f"bundle={output_dir / 'samehistory_system_a10_v4_analysis_bundle.json'}")
        print("output_reused=1")
        print(f"analysis_state={bundle.get('analysis_state')}")
        print("formal_ape_gate_open=0")
        print("winner_permitted=0")
        return 0
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.staging.", dir=str(output_dir.parent)))
    try:
        bundle = build_bundle(staging, run_evaluator=run_evaluator)
        bundle_path = staging / "samehistory_system_a10_v4_analysis_bundle.json"
        bundle_path.write_text(
            json.dumps(clean_json(bundle), indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        write_rows_csv(staging / "samehistory_system_a10_v4_rows.csv", bundle["systems"])
        write_report(staging / "samehistory_system_a10_v4_analysis_report.md", bundle)
        manifest = analysis_output_manifest(staging, output_dir, run_evaluator)
        (staging / "analysis_output_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        fsync_tree(staging)
        with blocked_termination_signals():
            rename_directory_noreplace(staging, output_dir)
            fsync_directory(output_dir.parent)
    except Exception as error:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        print(f"analysis_error={type(error).__name__}:{error}", file=sys.stderr)
        return 2
    print(f"bundle={output_dir / 'samehistory_system_a10_v4_analysis_bundle.json'}")
    print(f"analysis_state={bundle.get('analysis_state')}")
    print("formal_ape_gate_open=0")
    print("winner_permitted=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
