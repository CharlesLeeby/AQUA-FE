#!/usr/bin/env python3
"""One-shot A09 warm-history VINS backend supervisor.

The A09 contract is local to this file and its late-bound execution lock.  The
well-tested A10 v4 supervisor is loaded only after its frozen hash is checked,
and is used as a safety library for durable publication, subreaper ownership,
and escaped-descendant cleanup.  Importing this module is inert.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
from types import ModuleType
from typing import Any, Iterator, Mapping, Sequence


ROOT = Path("/home/ma/AQUA-FE_WS")
EXP_ROOT = Path("/mnt/data/AQUA-FE_WS/experiments/a09_samehistory_system_warmstart_v1")
DEFAULT_LOCK = ROOT / "papers/a09_samehistory_warmstart_v1_backend_execution_lock.json"
BUILDER_PATH = ROOT / "scripts/build_a09_samehistory_warmstart_v1_backend_execution_lock.py"
SAFETY_BASE_PATH = ROOT / "scripts/run_samehistory_system_a10_finalonline_v4_backend_recovery.py"
BUILDER_EXPECTED = (
    62_819,
    "f734c4b7b404f3f3d7c2f5d406823e0307e85f53547ae890f4a17b4768d6c090",
)
SAFETY_BASE_EXPECTED = (
    253_456,
    "4ac06b942a38f0074df6d2193d17d634673bc360865cee752f5732241224c277",
)

ITEM_ORDER = (
    "vanilla_origin_native_image_context",
    "klt_external_feature_context",
    "aquafe_external_feature_context",
)
CLAIM_NAME = "process_start_claim.json"
RECEIPT_NAME = "formal_run_receipt_v1.json"
LOG_NAME = "supervisor_process.log"
RECEIPT_SCHEMA = "aqua-fe-a09-samehistory-warmstart-backend-supervisor-v1"
WORKSPACE_REAL_PARENT = Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins")
AUTHORIZATION_TOKENS = {
    "vanilla_origin_native_image_context": (
        "A09_WARMSTART_V1_RUN_VANILLA_ORIGIN_NATIVE_IMAGE_CONTEXT_EXACTLY_ONCE"
    ),
    "klt_external_feature_context": (
        "A09_WARMSTART_V1_RUN_KLT_EXTERNAL_FEATURE_CONTEXT_EXACTLY_ONCE"
    ),
    "aquafe_external_feature_context": (
        "A09_WARMSTART_V1_RUN_AQUAFE_EXTERNAL_FEATURE_CONTEXT_EXACTLY_ONCE"
    ),
}
TERM_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)

APE_KEYS = (
    "matched",
    "duration_s",
    "max_timestamp_error_s",
    "se3_ape_rmse_m",
    "se3_ape_median_m",
    "se3_ape_max_m",
    "rpe_delta_s",
    "rpe_pairs",
    "rpe_trans_rmse_m",
    "rpe_trans_median_m",
    "rpe_trans_max_m",
    "output_poses",
    "output_duration_s",
    "expected_duration_s",
    "output_coverage_ratio",
    "first_output_delay_s",
    "last_output_drop_s",
    "median_output_dt_s",
    "max_output_gap_s",
    "large_output_gap_count",
    "init_success",
    "tracking_lost_count_proxy",
    "log_linear_solver_failures",
    "log_failure_mentions",
    "log_restart_mentions",
    "log_waiting_mentions",
)
APE_INTEGER_KEYS = {
    "matched",
    "rpe_pairs",
    "output_poses",
    "large_output_gap_count",
    "init_success",
    "tracking_lost_count_proxy",
    "log_linear_solver_failures",
    "log_failure_mentions",
    "log_restart_mentions",
    "log_waiting_mentions",
}


class BackendError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BackendError(code)


def now_local() -> str:
    return datetime.now().astimezone().isoformat()


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


def regular_file(path: Path, context: str) -> None:
    require(path.exists() and not path.is_symlink(), f"NOT_REGULAR:{context}:{path}")
    require(stat.S_ISREG(path.lstat().st_mode), f"NOT_REGULAR:{context}:{path}")


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


def check_bootstrap_identity(path: Path, expected: tuple[int, str], label: str) -> None:
    actual = identity(path)
    require(
        (actual["size_bytes"], actual["sha256"]) == expected,
        f"BOOTSTRAP_IDENTITY_DRIFT:{label}",
    )


def load_module(path: Path, name: str) -> ModuleType:
    specification = importlib.util.spec_from_file_location(name, path)
    require(specification is not None and specification.loader is not None, f"MODULE_SPEC:{path}")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


_CONTRACT: ModuleType | None = None
_SAFETY: ModuleType | None = None


def contract_module() -> ModuleType:
    global _CONTRACT
    if _CONTRACT is None:
        check_bootstrap_identity(BUILDER_PATH, BUILDER_EXPECTED, "builder")
        _CONTRACT = load_module(BUILDER_PATH, "a09_backend_lock_contract_v1")
    return _CONTRACT


def safety_module() -> ModuleType:
    global _SAFETY
    if _SAFETY is None:
        check_bootstrap_identity(SAFETY_BASE_PATH, SAFETY_BASE_EXPECTED, "a10-v4-safety-base")
        _SAFETY = load_module(SAFETY_BASE_PATH, "a09_imported_a10_v4_safety_base")
    return _SAFETY


def stable_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.absolute()
    regular_file(path, "json")
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    require(
        all(getattr(before, key) == getattr(after, key) for key in fields),
        f"JSON_CHANGED_DURING_READ:{path}",
    )
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendError(f"JSON_INVALID:{path}:{type(error).__name__}:{error}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{path}")
    return value, {
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def verify_authority(lock_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = contract_module()
    lock, lock_identity = stable_json(lock_path)
    require(lock.get("schema_version") == contract.SCHEMA, "LOCK_SCHEMA")
    require(lock.get("status") == "FROZEN_BEFORE_BACKEND_LAUNCH", "LOCK_STATUS")
    host_net = contract.current_namespace("net")
    host_user = contract.current_namespace("user")
    expected_policy = contract.expected_policy(host_net, host_user)
    expected_items = contract.build_items(host_net, host_user)
    require(lock.get("policy") == expected_policy, "LOCK_POLICY_DRIFT")
    require(lock.get("items") == expected_items, "LOCK_ITEMS_DRIFT")
    expected_scope = {
        "development_only": True,
        "machine_exclusive_cpu_scheduling": False,
        "formal_paper_accuracy_evidence_permitted": False,
        "formal_ape_gate": "CLOSED_BY_CONSTRUCTION",
    }
    require(lock.get("evidence_scope") == expected_scope, "LOCK_EVIDENCE_SCOPE")
    actual_frontends = {
        "klt": contract.load_frontend_authority("klt"),
        "aquafe": contract.load_frontend_authority("aquafe"),
    }
    require(lock.get("frontend_authorities") == actual_frontends, "FRONTEND_AUTHORITY_CHANGED")
    actual_identities = contract.collect_static_identities()
    require(lock.get("identities") == actual_identities, "STATIC_AUTHORITY_CHANGED")
    expected_contract = contract.contract_sha256(
        expected_policy, expected_items, actual_identities, actual_frontends
    )
    require(lock.get("contract_sha256") == expected_contract, "LOCK_CONTRACT_DIGEST")
    require(isinstance(lock.get("created_at_local"), str), "LOCK_CREATED_AT")
    return lock, lock_identity


def contained(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((str(path.absolute()), str(root.absolute()))) == str(root.absolute())
    except ValueError:
        return False


def canonical_directory(path: Path, context: str) -> None:
    require(path.exists() and not path.is_symlink(), f"DIRECTORY_NOT_CANONICAL:{context}:{path}")
    require(path.is_dir(), f"DIRECTORY_NOT_CANONICAL:{context}:{path}")
    require(path.resolve(strict=True) == path.absolute(), f"DIRECTORY_RESOLVE:{context}:{path}")


def prepare_layout(lock: Mapping[str, Any]) -> None:
    contract = contract_module()
    logs_link = ROOT / "logs"
    require(logs_link.is_symlink(), "WORKSPACE_LOGS_NOT_SYMLINK")
    require(os.readlink(logs_link) == "/mnt/data/AQUA-FE_WS/logs", "WORKSPACE_LOGS_TARGET")
    real_parent = Path("/mnt/data/AQUA-FE_WS/logs/aqualoc_archaeo_vins")
    canonical_directory(real_parent, "workspace-real-parent")
    (EXP_ROOT / "backends").mkdir(parents=True, exist_ok=True)
    (EXP_ROOT / "runtime").mkdir(parents=True, exist_ok=True)
    canonical_directory(EXP_ROOT / "backends", "backends-root")
    canonical_directory(EXP_ROOT / "runtime", "runtime-root")
    for item_id in ITEM_ORDER:
        item = lock["items"][item_id]
        output = Path(item["output_dir"]).absolute()
        require(contained(output, EXP_ROOT / "backends"), f"OUTPUT_ESCAPE:{item_id}")
        if output.exists() or output.is_symlink():
            canonical_directory(output, f"output:{item_id}")
        else:
            output.mkdir(mode=0o755)
            canonical_directory(output, f"output:{item_id}")
        environment = item["env"]
        for key in ("ROS_HOME", "ROS_LOG_DIR"):
            runtime = Path(environment[key]).absolute()
            require(contained(runtime, EXP_ROOT / "runtime" / item_id), f"RUNTIME_ESCAPE:{item_id}:{key}")
            runtime.mkdir(parents=True, exist_ok=True)
            canonical_directory(runtime, f"runtime:{item_id}:{key}")
        logical = Path(item["workspace_link"]).absolute()
        expected_logical_parent = ROOT / "logs/aqualoc_archaeo_vins"
        require(logical.parent == expected_logical_parent, f"WORKSPACE_PARENT:{item_id}")
        physical = real_parent / logical.name
        if physical.exists() or physical.is_symlink():
            require(physical.is_symlink(), f"WORKSPACE_LINK_COLLISION:{item_id}")
            require(os.readlink(physical) == str(output), f"WORKSPACE_LINK_TARGET:{item_id}")
        else:
            os.symlink(str(output), physical, target_is_directory=True)
        require(logical.is_symlink() and logical.resolve(strict=True) == output, f"WORKSPACE_LINK_INVALID:{item_id}")


def prelaunch_empty(item: Mapping[str, Any]) -> None:
    output = Path(item["output_dir"]).absolute()
    canonical_directory(output, "prelaunch-output")
    entries = sorted(entry.name for entry in output.iterdir())
    require(not entries, f"OUTPUT_NOT_EMPTY:{entries}")
    for key in ("ROS_HOME", "ROS_LOG_DIR"):
        path = Path(item["env"][key]).absolute()
        canonical_directory(path, f"prelaunch-{key}")
        runtime_entries = sorted(entry.name for entry in path.iterdir())
        require(not runtime_entries, f"RUNTIME_NOT_EMPTY:{key}:{runtime_entries}")


def effective_environment(lock: Mapping[str, Any], item: Mapping[str, Any]) -> dict[str, str]:
    base = dict(lock["policy"]["base_environment"])
    declared = dict(item["env"])
    require(not (set(base) & set(declared)), "ITEM_ENV_SHADOWS_BASE")
    require("PWD" not in base and "PWD" not in declared, "PWD_MUST_BE_SUPERVISOR_OWNED")
    result = {**base, **declared, "PWD": str(ROOT)}
    require(all(isinstance(k, str) and isinstance(v, str) for k, v in result.items()), "ENV_NOT_TEXT")
    require(all("\x00" not in k + v and "=" not in k for k, v in result.items()), "ENV_INVALID_TOKEN")
    return result


def proc_argv(pid: int) -> list[str] | None:
    try:
        data = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    if not data:
        return None
    try:
        return [token.decode("utf-8", errors="strict") for token in data.rstrip(b"\0").split(b"\0")]
    except UnicodeDecodeError:
        return [token.decode("utf-8", errors="replace") for token in data.rstrip(b"\0").split(b"\0")]


def proc_start_ticks(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        close = text.rfind(")")
        fields = text[close + 2 :].split()
        return int(fields[19])
    except (FileNotFoundError, PermissionError, OSError, ValueError, IndexError):
        return None


def forbidden_role(argv: Sequence[str]) -> str | None:
    names = [Path(token).name.lower() for token in argv]
    for role in ("roscore", "rosmaster", "vins_node"):
        if role in names:
            return role
    for index, name in enumerate(names):
        if name in {"rosbag", "rosbag.py"} and "play" in argv[index + 1 :]:
            return "rosbag_play"
    text = " ".join(argv).lower()
    if "run_a09_samehistory_warmstart_v1_frontends.py" in text:
        return "a09_frontend_supervisor"
    if (
        "run_a09_samehistory_warmstart_v2_aquafe.py" in text
        or "build_a09_samehistory_warmstart_v2_aquafe_lock.py" in text
    ):
        return "a09_aquafe_v2_producer"
    for marker in (
        "hfnet_slam", "mono_tum", "xfeat_seed_sidecar", "causal_lineage",
        "lightglue",
        "superpoint", "loftr", "droid_slam", "droid-slam", "dpvo",
    ):
        if marker in text:
            return f"learned:{marker}"
    return None


def ambient_role(argv: Sequence[str]) -> str | None:
    names = [Path(token).name.lower() for token in argv]
    if "rosout" in names:
        return "ambient_standalone_rosout"
    text = " ".join(argv).lower()
    if "todesk" in text:
        return "ambient_todesk"
    return None


def forbidden_processes() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        ticks_before = proc_start_ticks(pid)
        argv = proc_argv(pid)
        ticks_after = proc_start_ticks(pid)
        if not argv or ticks_before is None or ticks_before != ticks_after:
            continue
        role = forbidden_role(argv)
        if role is None:
            continue
        result.append(
            {
                "pid": pid,
                "start_ticks": ticks_after,
                "role": role,
                "argv": argv,
                "argv_sha256": compact_sha256(argv),
            }
        )
    return sorted(result, key=lambda row: (int(row["pid"]), str(row["role"])))


def ambient_processes() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == os.getpid():
            continue
        ticks_before = proc_start_ticks(pid)
        argv = proc_argv(pid)
        ticks_after = proc_start_ticks(pid)
        if not argv or ticks_before is None or ticks_before != ticks_after:
            continue
        role = ambient_role(argv)
        if role is None:
            continue
        result.append(
            {
                "pid": pid,
                "start_ticks": ticks_after,
                "role": role,
                "argv_sha256": compact_sha256(argv),
            }
        )
    return sorted(result, key=lambda row: (int(row["pid"]), str(row["role"])))


def quiescence(phase: str) -> dict[str, Any]:
    hits = forbidden_processes()
    ambient = ambient_processes()
    return {
        "phase": phase,
        "status": "PASS" if not hits else "FAIL",
        "blocking_processes": hits,
        "nonblocking_ambient_processes": ambient,
        "nonblocking_ambient_processes_sha256": compact_sha256(ambient),
        "ambient_process_identity_may_change_between_audits": True,
        "runtime_or_throughput_claim_permitted": False,
    }


class DualFlock:
    def __init__(self, frontend: Path, backend: Path):
        self.frontend = frontend
        self.backend = backend
        self.descriptors: list[int] = []

    def __enter__(self) -> "DualFlock":
        regular_file(self.frontend, "frontend-flock")
        self.backend.parent.mkdir(parents=True, exist_ok=True)
        front_fd = os.open(self.frontend, os.O_RDWR | os.O_CLOEXEC)
        back_fd = os.open(
            self.backend,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        self.descriptors = [front_fd, back_fd]
        try:
            for descriptor in self.descriptors:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.__exit__(None, None, None)
            raise BackendError("CONCURRENT_FRONTEND_OR_BACKEND_STAGE") from error
        return self

    def __exit__(self, _type: Any, _value: Any, _traceback: Any) -> None:
        for descriptor in reversed(self.descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        self.descriptors = []


def safe_output(path: Path, base: Path) -> dict[str, Any]:
    require(contained(path, base), f"OUTPUT_ESCAPE:{path}")
    value = identity(path)
    require(value["size_bytes"] > 0, f"OUTPUT_EMPTY:{path}")
    return value


def workspace_guard(
    item: Mapping[str, Any], phase: str,
    expected: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    logical = Path(item["workspace_link"]).absolute()
    output = Path(item["output_dir"]).absolute()
    require(logical.parent == ROOT / "logs/aqualoc_archaeo_vins", "WORKSPACE_GUARD_PARENT")
    physical = WORKSPACE_REAL_PARENT / logical.name
    logical_info = logical.lstat()
    physical_info = physical.lstat()
    require(stat.S_ISLNK(logical_info.st_mode), f"WORKSPACE_GUARD_NOT_SYMLINK:{phase}")
    require(stat.S_ISLNK(physical_info.st_mode), f"WORKSPACE_PHYSICAL_NOT_SYMLINK:{phase}")
    require(
        (logical_info.st_dev, logical_info.st_ino)
        == (physical_info.st_dev, physical_info.st_ino),
        f"WORKSPACE_LOGICAL_PHYSICAL_INODE:{phase}",
    )
    target = os.readlink(logical)
    physical_target = os.readlink(physical)
    require(target == physical_target == str(output), f"WORKSPACE_GUARD_TARGET:{phase}")
    require(logical.resolve(strict=True) == output, f"WORKSPACE_GUARD_RESOLVE:{phase}")
    output_info = output.lstat()
    require(stat.S_ISDIR(output_info.st_mode), f"WORKSPACE_OUTPUT_NOT_REAL_DIRECTORY:{phase}")
    require(not output.is_symlink(), f"WORKSPACE_OUTPUT_IS_SYMLINK:{phase}")
    result = {
        "phase": phase,
        "logical_path": str(logical),
        "physical_path": str(physical),
        "target": target,
        "symlink_device": int(logical_info.st_dev),
        "symlink_inode": int(logical_info.st_ino),
        "output_path": str(output),
        "output_device": int(output_info.st_dev),
        "output_inode": int(output_info.st_ino),
    }
    if expected is not None:
        for key in (
            "logical_path", "physical_path", "target", "symlink_device",
            "symlink_inode", "output_path", "output_device", "output_inode",
        ):
            require(result[key] == expected.get(key), f"WORKSPACE_GUARD_CHANGED:{phase}:{key}")
    return result


def audit_output_tree(
    item: Mapping[str, Any], *, receipt_allowed: bool = False,
    require_all_expected: bool = True,
) -> dict[str, Any]:
    base = Path(item["output_dir"]).absolute()
    expected = {(base / rel).absolute() for rel in item["expected_outputs"]}
    allowed_files = expected | {base / CLAIM_NAME, base / LOG_NAME}
    if receipt_allowed:
        allowed_files.add(base / RECEIPT_NAME)
    allowed_directories = {base, base / "vins_output"}
    seen_files: set[Path] = set()
    seen_directories: set[Path] = {base}
    for raw_root, dirnames, filenames in os.walk(base, topdown=True, followlinks=False):
        root = Path(raw_root).absolute()
        for name in dirnames:
            path = root / name
            require(path in allowed_directories and not path.is_symlink(), f"UNEXPECTED_DIRECTORY:{path}")
            seen_directories.add(path)
        for name in filenames:
            path = root / name
            require(path in allowed_files and not path.is_symlink(), f"UNEXPECTED_FILE:{path}")
            require(stat.S_ISREG(path.lstat().st_mode), f"OUTPUT_NOT_REGULAR:{path}")
            seen_files.add(path)
    missing = sorted(str(path) for path in expected - seen_files)
    if require_all_expected:
        require(not missing, f"EXPECTED_OUTPUT_MISSING:{missing}")
    return {
        "seen_files": sorted(str(path) for path in seen_files),
        "seen_directories": sorted(str(path) for path in seen_directories),
        "missing_expected_files": missing,
    }


def storage_permission_semantics(lock: Mapping[str, Any]) -> dict[str, Any]:
    contract = contract_module()
    value = lock.get("policy", {}).get("storage_permission_semantics")
    require(isinstance(value, dict), "STORAGE_PERMISSION_SEMANTICS_MISSING")
    contract.validate_storage_permission_semantics(value)
    return dict(value)


def observed_mode_allowed(semantics: Mapping[str, Any], observed_mode: int) -> bool:
    try:
        expected = int(str(semantics.get("observed_mode")), 8)
    except (TypeError, ValueError):
        return False
    return bool(
        semantics.get("filesystem_type") == "fuseblk"
        and semantics.get("statfs_magic_hex") == "0x65735546"
        and semantics.get("requested_mode") == "0444"
        and semantics.get("observed_mode") == "0755"
        and semantics.get("posix_readonly_enforced") is False
        and semantics.get("permission_bits_are_integrity_basis") is False
        and observed_mode == expected
    )


def validate_projected_mode(
    path: Path, semantics: Mapping[str, Any], context: str,
) -> str:
    path = path.absolute()
    info = path.lstat()
    require(
        contained(path, Path(str(semantics["storage_root"])))
        and stat.S_ISREG(info.st_mode)
        and not path.is_symlink()
        and int(info.st_dev) == semantics["storage_device"],
        f"PROJECTED_MODE_STORAGE_BINDING:{context}",
    )
    observed = stat.S_IMODE(info.st_mode)
    require(observed_mode_allowed(semantics, observed), f"PROJECTED_MODE:{context}:{observed:04o}")
    return f"{observed:04o}"


def seal_regular_file(path: Path, semantics: Mapping[str, Any]) -> str:
    before = path.lstat()
    require(
        stat.S_ISREG(before.st_mode) and not path.is_symlink() and before.st_nlink == 1,
        f"SEAL_NOT_PRIVATE_REGULAR:{path}",
    )
    descriptor = os.open(
        path,
        os.O_RDWR | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        require(
            stat.S_ISREG(opened.st_mode)
            and (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
            f"SEAL_INODE_CHANGED:{path}",
        )
        requested_mode = int(str(semantics["requested_mode"]), 8)
        os.fchmod(descriptor, requested_mode)
        os.fsync(descriptor)
        sealed = os.fstat(descriptor)
        require(
            (sealed.st_dev, sealed.st_ino, sealed.st_size)
            == (before.st_dev, before.st_ino, before.st_size),
            f"SEAL_IDENTITY_CHANGED:{path}",
        )
        require(
            observed_mode_allowed(semantics, stat.S_IMODE(sealed.st_mode)),
            f"SEAL_PROJECTED_MODE:{path}:{stat.S_IMODE(sealed.st_mode):04o}",
        )
        return f"{stat.S_IMODE(sealed.st_mode):04o}"
    finally:
        os.close(descriptor)


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def sealed_file_snapshot(
    path: Path, semantics: Mapping[str, Any],
) -> dict[str, Any]:
    snapshot = identity(path)
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode), f"SEALED_NOT_REGULAR:{path}")
    observed_mode = validate_projected_mode(path, semantics, f"science:{path}")
    return {
        **snapshot,
        "requested_mode": semantics["requested_mode"],
        "observed_mode": observed_mode,
        "posix_readonly_enforced": False,
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "link_count": int(info.st_nlink),
    }


def science_paths(item: Mapping[str, Any]) -> list[Path]:
    base = Path(item["output_dir"]).absolute()
    return sorted(
        {(base / rel).absolute() for rel in item["expected_outputs"]} | {base / LOG_NAME},
        key=str,
    )


def seal_science_tree(
    item: Mapping[str, Any], semantics: Mapping[str, Any],
) -> dict[str, Any]:
    """Seal the namespace adapter's canonical real directory in place."""
    base = Path(item["output_dir"]).absolute()
    pre_tree = audit_output_tree(
        item, receipt_allowed=False, require_all_expected=False,
    )
    snapshots: dict[str, Any] = {}
    missing_science: list[str] = []
    for path in science_paths(item):
        if not path.exists() or path.is_symlink():
            missing_science.append(str(path))
            continue
        require(stat.S_ISREG(path.lstat().st_mode), f"SCIENCE_NOT_REGULAR:{path}")
        observed_mode = seal_regular_file(path, semantics)
        snapshot = sealed_file_snapshot(path, semantics)
        require(snapshot["observed_mode"] == observed_mode, f"SCIENCE_MODE_UNSTABLE:{path}")
        snapshots[str(path)] = snapshot
    for directory in sorted(
        {base, *(path.parent for path in science_paths(item) if path.parent != base)},
        key=lambda value: len(value.parts), reverse=True,
    ):
        if directory.exists():
            fsync_directory(directory)
    return {
        "status": "PASS" if not missing_science else "FAIL",
        "storage_mode": "SEALED_IN_PLACE_CANONICAL_REAL_OUTPUT",
        "namespace_adapter_requires_canonical_real_output": True,
        "storage_permission_semantics": dict(semantics),
        "requested_mode": semantics["requested_mode"],
        "observed_mode": semantics["observed_mode"],
        "posix_readonly_enforced": False,
        "permission_bits_are_integrity_basis": False,
        "fchmod_and_fsync_completed_for_present_science_files": True,
        "integrity_basis": semantics["integrity_basis"],
        "pre_receipt_exact_tree": pre_tree,
        "science_snapshot_before_receipt": snapshots,
        "missing_science_files": missing_science,
    }


def validate_science_snapshot(
    snapshot: Mapping[str, Any], semantics: Mapping[str, Any],
) -> dict[str, Any]:
    current: dict[str, Any] = {}
    for raw_path, expected in sorted(snapshot.items()):
        path = Path(raw_path)
        actual = sealed_file_snapshot(path, semantics)
        require(actual == expected, f"SCIENCE_FINGERPRINT_CHANGED:{path}")
        require(
            actual["observed_mode"] == semantics["observed_mode"],
            f"SCIENCE_PROJECTED_MODE_CHANGED:{path}",
        )
        current[raw_path] = actual
    return current


def parse_manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        require("=" in line, f"MANIFEST_LINE:{path}:{line_number}")
        key, value = line.split("=", 1)
        require(key and key not in result, f"MANIFEST_KEY:{path}:{line_number}")
        result[key] = value
    return result


def parse_ape(path: Path) -> dict[str, float | int]:
    raw = parse_manifest(path)
    require(set(raw) == set(APE_KEYS), f"APE_KEY_SET:{sorted(raw)}")
    result: dict[str, float | int] = {}
    for key in APE_KEYS:
        try:
            value = float(raw[key])
        except ValueError as error:
            raise BackendError(f"APE_VALUE:{key}:{raw[key]}") from error
        require(math.isfinite(value), f"APE_NONFINITE:{key}")
        if key in APE_INTEGER_KEYS:
            rounded = round(value)
            require(abs(value - rounded) <= 1e-6, f"APE_NOT_INTEGER:{key}:{value}")
            result[key] = int(rounded)
        else:
            result[key] = value
    return result


def validate_namespace_manifest(
    path: Path, item: Mapping[str, Any], lock: Mapping[str, Any]
) -> dict[str, Any]:
    value, file_identity = stable_json(path)
    host = lock["policy"]["host_namespace_identity"]
    require(value.get("schema_version") == "aqua-fe-a10-samehistory-backend-netns-v4", "NETNS_SCHEMA")
    require(value.get("status") == "PASS", "NETNS_STATUS")
    require(value.get("isolation_scope") == "NETWORK_NAMESPACE_LOOPBACK_ONLY", "NETNS_SCOPE")
    require(value.get("machine_exclusive_cpu_scheduling") is False, "NETNS_EXCLUSIVITY")
    require(value.get("uid_inside") == 0 and value.get("gid_inside") == 0, "NETNS_ROOT_MAP")
    require(value.get("host_network_namespace") == host["network"], "NETNS_HOST_NET")
    require(value.get("host_user_namespace") == host["user"], "NETNS_HOST_USER")
    require(value.get("self_network_namespace") != host["network"], "NETNS_NOT_DISTINCT_NET")
    require(value.get("self_user_namespace") != host["user"], "NETNS_NOT_DISTINCT_USER")
    require(value.get("interfaces") == ["lo"], "NETNS_INTERFACES")
    require(value.get("initial_tcp_listeners") == [], "NETNS_INITIAL_LISTENERS")
    require(value.get("formal_bind_address") == "127.0.0.1", "NETNS_BIND_ADDRESS")
    require(value.get("formal_bind_port") == 11981, "NETNS_BIND_PORT")
    require(
        value.get("backend_argv_sha256") == item["inner_backend_argv_sha256"],
        "NETNS_BACKEND_ARGV_DIGEST",
    )
    return {"status": "PASS", "identity": file_identity, "manifest": value}


def score_usability(
    lock: Mapping[str, Any], item: Mapping[str, Any], ape: Mapping[str, Any]
) -> dict[str, Any]:
    safety = safety_module()
    policy = lock["policy"]["score_usability"]
    start_ns = int(policy["score_start_ns"])
    end_ns = int(policy["score_end_ns"])
    trajectory = Path(item["output_dir"]) / "vins_output/vio.csv"
    stamps = safety.strict_trajectory_stamps(trajectory)
    require(len(stamps) >= 2, "TRAJECTORY_ROWS_BELOW_MINIMUM")
    score_stamps = [stamp for stamp in stamps if start_ns <= stamp <= end_ns]
    failures: list[str] = []
    if len(score_stamps) < int(policy["minimum_score_trajectory_rows"]):
        failures.append("INSUFFICIENT_SCORE_TRAJECTORY_ROWS")
        first = last = None
        coverage = 0.0
        maximum_gap = None
    else:
        first, last = score_stamps[0], score_stamps[-1]
        coverage = (last - first) / (end_ns - start_ns)
        maximum_gap = max(
            right - left for left, right in zip(score_stamps, score_stamps[1:])
        ) / 1e9
    if coverage < float(policy["minimum_score_temporal_span_coverage"]):
        failures.append("SCORE_TEMPORAL_SPAN_COVERAGE_BELOW_GATE")
    if maximum_gap is None or maximum_gap > float(policy["maximum_score_output_gap_s"]):
        failures.append("SCORE_OUTPUT_GAP_ABOVE_GATE")
    if ape.get("init_success") != 1:
        failures.append("APE_INITIALIZATION_NOT_SUCCESSFUL")
    log_audit = safety.parse_score_log_events(
        Path(item["output_dir"]) / "vins.log", start_ns, end_ns
    )
    initialized = any(
        row.get("within_or_before_score_end") is True
        for row in log_audit["initialization_events"]
    )
    if not initialized:
        failures.append("NO_INITIALIZATION_EVENT_BEFORE_SCORE_END")
    if log_audit["score_failure_events"] > int(policy["maximum_score_failure_mentions"]):
        failures.append("SCORE_FAILURE_EVENT_GATE_EXCEEDED")
    if log_audit["score_restart_or_reset_events"] > int(
        policy["maximum_score_restart_or_reset_events"]
    ):
        failures.append("SCORE_RESTART_RESET_GATE_EXCEEDED")
    if log_audit["unresolved_event_count"]:
        failures.append("UNRESOLVED_LOG_EVENT_ATTRIBUTION")
    return {
        "status": "PASS" if not failures else "FAIL",
        "failure_codes": failures,
        "score_start_ns": start_ns,
        "score_end_ns": end_ns,
        "crop_interval": "inclusive",
        "full_trajectory_rows": len(stamps),
        "score_trajectory_rows": len(score_stamps),
        "score_first_stamp_ns": first,
        "score_last_stamp_ns": last,
        "score_temporal_span_coverage": coverage,
        "maximum_score_output_gap_s": maximum_gap,
        "ape_init_success": ape.get("init_success"),
        "initialization_before_or_within_score_end": initialized,
        "log_event_audit": log_audit,
    }


def audit_outputs(
    lock: Mapping[str, Any], item_id: str, item: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    base = Path(item["output_dir"]).absolute()
    tree = audit_output_tree(item)
    outputs = {
        str(base / rel): safe_output(base / rel, base) for rel in item["expected_outputs"]
    }
    checks: list[dict[str, Any]] = [{"type": "output_tree", "status": "PASS", **tree}]
    generated = item["generated_config"]
    generated_identity = outputs[str(base / generated["path"])]
    require(
        generated_identity["size_bytes"] == generated["size_bytes"]
        and generated_identity["sha256"] == generated["sha256"],
        "GENERATED_VINS_CONFIG_DRIFT",
    )
    checks.append({"type": "generated_vins_config", "status": "PASS", "identity": generated_identity})
    camera = item["camera_config"]
    camera_identity = outputs[str(base / camera["path"])]
    require(
        camera_identity["size_bytes"] == camera["size_bytes"]
        and camera_identity["sha256"] == camera["sha256"],
        "CAMERA_CONFIG_DRIFT",
    )
    checks.append({"type": "camera_config", "status": "PASS", "identity": camera_identity})
    replay = parse_manifest(base / "replay_manifest.txt")
    require(replay == item["replay_contract"], "REPLAY_MANIFEST_DRIFT")
    checks.append({"type": "replay_manifest", "status": "PASS", "values": replay})
    namespace = validate_namespace_manifest(base / "network_namespace_manifest.json", item, lock)
    checks.append({"type": "network_namespace_manifest", **namespace})
    ape = parse_ape(base / "ape.txt")
    checks.append({"type": "ape_kv", "status": "PASS", "values": ape})
    score = score_usability(lock, item, ape)
    if item_id == "klt_external_feature_context":
        expected_metrics = lock["frontend_authorities"]["klt"]["artifacts"][
            "frontend_metrics.csv"
        ]
        actual_metrics = outputs[str(base / "frontend_metrics.csv")]
        require(
            actual_metrics["size_bytes"] == expected_metrics["size_bytes"]
            and actual_metrics["sha256"] == expected_metrics["sha256"],
            "KLT_FRONTEND_METRICS_COPY_DRIFT",
        )
        checks.append({"type": "frontend_metrics_copy", "status": "PASS", "identity": actual_metrics})
    return outputs, checks, score


def terminal_layer(runtime: Mapping[str, Any], timeout: int) -> dict[str, Any]:
    rc0 = bool(
        runtime.get("popen_invocation_count") == 1
        and runtime.get("child_started") is True
        and runtime.get("raw_return_code") == 0
        and runtime.get("timed_out") is False
    )
    return {
        "status": "TERMINAL_PROCESS_RC0" if rc0 else "TERMINAL_PROCESS_FAILED",
        "popen_invocation_count": runtime.get("popen_invocation_count", 0),
        "child_started": runtime.get("child_started", False),
        "pid": runtime.get("pid"),
        "pgid": runtime.get("pgid"),
        "leader_identity": runtime.get("leader_identity"),
        "raw_return_code": runtime.get("raw_return_code"),
        "timed_out": runtime.get("timed_out", False),
        "timeout_seconds": timeout,
        "process_group": runtime.get("process_group"),
    }


def disposition(receipt: Mapping[str, Any]) -> str:
    terminal = receipt["terminal_process"]
    artifact = receipt["artifact_contract"]
    execution = receipt["execution_integrity"]
    score = receipt["score_usability"]
    if (
        terminal["status"] == "TERMINAL_PROCESS_RC0"
        and artifact["status"] == "PASS"
        and execution["status"] == "PASS"
        and score["status"] == "PASS"
    ):
        return "ACCEPTED"
    if terminal["status"] != "TERMINAL_PROCESS_RC0":
        return "PROCESS_FAILED"
    if execution["status"] != "PASS":
        return "EXECUTION_INTEGRITY_FAILED"
    if artifact["status"] != "PASS":
        return "ARTIFACT_CONTRACT_FAILED"
    if score["status"] != "PASS":
        return "RETAINED_UNUSABLE_SCORE"
    return "FAILED_UNCLASSIFIED"


def validate_existing_accepted_receipt(
    lock: Mapping[str, Any], lock_identity: Mapping[str, Any], item_id: str,
) -> dict[str, Any]:
    item = lock["items"][item_id]
    semantics = storage_permission_semantics(lock)
    output = Path(item["output_dir"]).absolute()
    receipt_path = output / RECEIPT_NAME
    claim_path = output / CLAIM_NAME
    receipt, receipt_identity = stable_json(receipt_path)
    require(
        receipt.get("schema_version") == RECEIPT_SCHEMA
        and receipt.get("item_id") == item_id
        and receipt.get("kind") == "backend_replay"
        and receipt.get("launch_allowance_consumed") is True
        and receipt.get("overall_disposition") == "ACCEPTED",
        f"PRIOR_RECEIPT_NOT_ACCEPTED:{item_id}",
    )
    require(receipt.get("execution_lock") == lock_identity, f"PRIOR_RECEIPT_LOCK:{item_id}")
    claim, claim_identity = stable_json(claim_path)
    require(
        claim.get("schema_version") == RECEIPT_SCHEMA
        and claim.get("item_id") == item_id
        and claim.get("status") == "CLAIMED_BEFORE_SINGLE_POPEN"
        and claim.get("launch_allowance_consumed") is True,
        f"PRIOR_CLAIM_INVALID:{item_id}",
    )
    require(claim.get("execution_lock") == lock_identity, f"PRIOR_CLAIM_LOCK:{item_id}")
    require(
        claim.get("storage_permission_semantics") == semantics
        and claim.get("claim_requested_mode") == "0444"
        and claim.get("claim_observed_mode_policy") == "0755",
        f"PRIOR_CLAIM_STORAGE_SEMANTICS:{item_id}",
    )
    require(receipt.get("claim") == claim_identity, f"PRIOR_RECEIPT_CLAIM:{item_id}")
    validate_projected_mode(claim_path, semantics, f"prior-claim:{item_id}")
    terminal = receipt.get("terminal_process")
    group = terminal.get("process_group") if isinstance(terminal, dict) else None
    require(
        isinstance(terminal, dict)
        and terminal.get("status") == "TERMINAL_PROCESS_RC0"
        and terminal.get("popen_invocation_count") == 1
        and terminal.get("child_started") is True
        and terminal.get("raw_return_code") == 0
        and terminal.get("timed_out") is False
        and isinstance(group, dict)
        and all(
            group.get(key) is True
            for key in ("leader_reaped", "process_group_empty", "owned_descendants_empty")
        ),
        f"PRIOR_TERMINAL_INVALID:{item_id}",
    )
    require(
        receipt.get("artifact_contract", {}).get("status") == "PASS"
        and receipt.get("score_usability", {}).get("status") == "PASS"
        and receipt.get("execution_integrity", {}).get("status") == "PASS",
        f"PRIOR_ACCEPTANCE_LAYER_INVALID:{item_id}",
    )
    require(receipt.get("causal_lineage") == item["causal_lineage"], f"PRIOR_CAUSAL_LINEAGE:{item_id}")
    seal = receipt.get("sealed_in_place_invariant")
    require(
        isinstance(seal, dict)
        and seal.get("status") == "PASS"
        and seal.get("storage_mode") == "SEALED_IN_PLACE_CANONICAL_REAL_OUTPUT"
        and seal.get("namespace_adapter_requires_canonical_real_output") is True
        and seal.get("storage_permission_semantics") == semantics
        and seal.get("requested_mode") == "0444"
        and seal.get("observed_mode") == "0755"
        and seal.get("posix_readonly_enforced") is False
        and seal.get("permission_bits_are_integrity_basis") is False
        and seal.get("fchmod_and_fsync_completed_for_present_science_files") is True
        and seal.get("integrity_basis") == semantics["integrity_basis"]
        and seal.get("receipt_atomic_publication_required") is True
        and seal.get("claim_observed_mode") == "0755"
        and seal.get("receipt_requested_mode") == "0444"
        and seal.get("receipt_observed_mode") == "0755"
        and seal.get("receipt_posix_readonly_enforced") is False
        and seal.get("post_receipt_exact_tree_directory_fsync_and_rehash_required") is True,
        f"PRIOR_SEAL_CONTRACT:{item_id}",
    )
    require(seal.get("missing_science_files") == [], f"PRIOR_SEAL_MISSING:{item_id}")
    guards = seal.get("workspace_guards")
    require(
        isinstance(guards, dict)
        and set(guards) == {"before_claim", "after_claim", "before_popen", "postflight"},
        f"PRIOR_WORKSPACE_GUARD_SET:{item_id}",
    )
    initial_guard = guards["before_claim"]
    for phase, recorded in guards.items():
        require(isinstance(recorded, dict), f"PRIOR_WORKSPACE_GUARD:{item_id}:{phase}")
        for key in (
            "logical_path", "physical_path", "target", "symlink_device",
            "symlink_inode", "output_path", "output_device", "output_inode",
        ):
            require(
                recorded.get(key) == initial_guard.get(key),
                f"PRIOR_WORKSPACE_GUARD_DRIFT:{item_id}:{phase}:{key}",
            )
    workspace_guard(item, "prior_item_independent_validation", initial_guard)
    tree = audit_output_tree(item, receipt_allowed=True, require_all_expected=True)
    require(
        tree["seen_files"] == seal.get("post_receipt_exact_files"),
        f"PRIOR_POST_RECEIPT_TREE:{item_id}",
    )
    require(
        tree["seen_directories"] == seal.get("post_receipt_exact_directories"),
        f"PRIOR_POST_RECEIPT_DIRECTORIES:{item_id}",
    )
    science = seal.get("science_snapshot_before_receipt")
    expected_science = {str(path) for path in science_paths(item)}
    require(
        isinstance(science, dict) and set(science) == expected_science,
        f"PRIOR_SCIENCE_SNAPSHOT:{item_id}",
    )
    require(
        seal.get("science_snapshot_sha256") == compact_sha256(science),
        f"PRIOR_SCIENCE_SNAPSHOT_DIGEST:{item_id}",
    )
    expected_final_files = sorted(
        expected_science | {str(output / CLAIM_NAME), str(receipt_path)}
    )
    require(
        seal.get("post_receipt_exact_files") == expected_final_files,
        f"PRIOR_DECLARED_FINAL_FILE_SET:{item_id}",
    )
    validate_science_snapshot(science, semantics)
    artifact_outputs = receipt["artifact_contract"].get("outputs")
    require(
        isinstance(artifact_outputs, dict)
        and set(artifact_outputs)
        == {str((output / relative).absolute()) for relative in item["expected_outputs"]},
        f"PRIOR_ARTIFACT_OUTPUTS:{item_id}",
    )
    for relative in item["expected_outputs"]:
        raw_path = str((output / relative).absolute())
        expected = science[raw_path]
        recorded = artifact_outputs.get(raw_path)
        require(
            isinstance(recorded, dict)
            and all(recorded.get(key) == expected[key] for key in ("path", "size_bytes", "sha256")),
            f"PRIOR_ARTIFACT_OUTPUT_BINDING:{item_id}:{relative}",
        )
    log_expected = science[str(output / LOG_NAME)]
    require(
        isinstance(receipt.get("process_log"), dict)
        and all(
            receipt["process_log"].get(key) == log_expected[key]
            for key in ("path", "size_bytes", "sha256")
        ),
        f"PRIOR_PROCESS_LOG_BINDING:{item_id}",
    )
    validate_projected_mode(receipt_path, semantics, f"prior-receipt:{item_id}")
    return {
        "item_id": item_id,
        "status": "PASS_INDEPENDENT_ACCEPTED_RECEIPT_REVALIDATION",
        "receipt": receipt_identity,
        "science_snapshot_sha256": compact_sha256(science),
    }


def enforce_item_order(
    lock: Mapping[str, Any], lock_identity: Mapping[str, Any], item_id: str,
    phase: str, expected_claim_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    require(set(lock["items"]) == set(ITEM_ORDER), "ITEM_ORDER_LOCK_KEYS")
    require(lock["policy"].get("item_order") == list(ITEM_ORDER), "ITEM_ORDER_POLICY")
    index = ITEM_ORDER.index(item_id)
    prior: list[dict[str, Any]] = []
    for prior_id in ITEM_ORDER[:index]:
        prior.append(validate_existing_accepted_receipt(lock, lock_identity, prior_id))
    target_output = Path(lock["items"][item_id]["output_dir"]).absolute()
    target_claim = target_output / CLAIM_NAME
    target_receipt = target_output / RECEIPT_NAME
    if phase == "before_claim":
        require(
            not target_claim.exists() and not target_claim.is_symlink()
            and not target_receipt.exists() and not target_receipt.is_symlink(),
            f"TARGET_ALREADY_CONSUMED:{item_id}",
        )
    else:
        require(phase in {"after_claim", "before_popen", "postflight"}, f"ITEM_ORDER_PHASE:{phase}")
        actual_claim = identity(target_claim)
        if expected_claim_identity is not None:
            require(actual_claim == expected_claim_identity, f"TARGET_CLAIM_CHANGED:{phase}")
        require(
            not target_receipt.exists() and not target_receipt.is_symlink(),
            f"TARGET_PREMATURE_RECEIPT:{phase}",
        )
    later: list[dict[str, Any]] = []
    for later_id in ITEM_ORDER[index + 1 :]:
        later_output = Path(lock["items"][later_id]["output_dir"]).absolute()
        later_claim = later_output / CLAIM_NAME
        later_receipt = later_output / RECEIPT_NAME
        require(
            not later_claim.exists() and not later_claim.is_symlink()
            and not later_receipt.exists() and not later_receipt.is_symlink(),
            f"LATER_ITEM_CONTROL_ARTIFACT_PRESENT:{later_id}",
        )
        if later_output.exists() and not later_output.is_symlink():
            require(not any(later_output.iterdir()), f"LATER_ITEM_OUTPUT_NOT_EMPTY:{later_id}")
        later.append({"item_id": later_id, "status": "UNCLAIMED_AND_EMPTY"})
    return {
        "phase": phase,
        "status": "PASS_STRICT_SERIAL_ITEM_ORDER",
        "prior_items": prior,
        "current_item": item_id,
        "later_items": later,
        "failure_of_any_prior_item_blocks_launch": True,
    }


def add_error(existing: str | None, error: BaseException | str) -> str:
    value = error if isinstance(error, str) else f"{type(error).__name__}:{error}"
    return value if existing is None else f"{existing};{value}"


def execute_claimed(
    lock_path: Path,
    lock: Mapping[str, Any],
    lock_identity: Mapping[str, Any],
    item_id: str,
    item: Mapping[str, Any],
    claim_path: Path,
    receipt_path: Path,
    log_path: Path,
    started_at: str,
    quiescence_before: Mapping[str, Any],
    workspace_before_claim: Mapping[str, Any],
    workspace_after_claim: Mapping[str, Any],
    order_after_claim: Mapping[str, Any],
    inherited_pending_signals: Sequence[int],
) -> tuple[int, dict[str, Any]]:
    safety = safety_module()
    semantics = storage_permission_semantics(lock)
    timeout = int(item["timeout_seconds"])
    environment = effective_environment(lock, item)
    argv = list(item["argv"])
    runtime: dict[str, Any] = {
        "popen_invocation_count": 0,
        "child_started": False,
        "pid": None,
        "pgid": None,
        "leader_identity": None,
        "raw_return_code": None,
        "timed_out": False,
        "process_group": {
            "pgid": None,
            "leader_reaped": True,
            "process_group_empty": True,
            "owned_descendants_empty": True,
        },
    }
    process: subprocess.Popen[bytes] | None = None
    pgid: int | None = None
    baseline_children: set[tuple[int, int]] = set()
    supervisor_error: str | None = None
    authority_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    authority_post: dict[str, Any] = {"status": "NOT_RUN"}
    quiescence_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    quiescence_post: dict[str, Any] = {"status": "NOT_RUN"}
    workspace_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    workspace_postflight: dict[str, Any] = {"status": "NOT_RUN"}
    order_before_popen: dict[str, Any] = {"status": "NOT_RUN"}
    order_postflight: dict[str, Any] = {"status": "NOT_RUN"}
    started_monotonic = time.monotonic()

    with safety.interruption_handlers() as pending_signals:
        pending_signals.extend(int(value) for value in inherited_pending_signals)
        try:
            safety.raise_pending_interruption(pending_signals)
            lock_again, identity_again = verify_authority(lock_path)
            authority_before_popen = {
                "status": (
                    "PASS" if lock_again == lock and identity_again == lock_identity else "FAIL"
                ),
                "lock": identity_again,
            }
            require(authority_before_popen["status"] == "PASS", "AUTHORITY_CHANGED_BEFORE_POPEN")
            claim_identity_before_popen = identity(claim_path)
            order_before_popen = enforce_item_order(
                lock, lock_identity, item_id, "before_popen", claim_identity_before_popen,
            )
            workspace_before_popen = workspace_guard(
                item, "before_popen", workspace_before_claim,
            )
            quiescence_before_popen = quiescence("after_claim_before_popen")
            require(quiescence_before_popen["status"] == "PASS", "PROCESS_PRESENT_BEFORE_POPEN")
            safety.raise_pending_interruption(pending_signals)
            with log_path.open("xb") as log_stream:
                with safety.blocked_signals():
                    baseline_children = set(safety.direct_child_identities(os.getpid()))
                    runtime["popen_invocation_count"] = 1
                    process = subprocess.Popen(
                        argv,
                        cwd=ROOT,
                        env=environment,
                        stdout=log_stream,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                        close_fds=True,
                    )
                    runtime["child_started"] = True
                    runtime["pid"] = process.pid
                    pgid = process.pid
                    runtime["pgid"] = pgid
                    leader = safety.process_identity(process.pid)
                    if leader is None:
                        leader = (process.pid, -1)
                    runtime["leader_identity"] = {
                        "pid": leader[0], "start_ticks": leader[1]
                    }
                    runtime["process_group"] = {
                        "pgid": pgid,
                        "leader_reaped": False,
                        "process_group_empty": False,
                        "owned_descendants_empty": False,
                    }
                deadline = time.monotonic() + timeout
                while True:
                    safety.raise_pending_interruption(pending_signals)
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
                with safety.blocked_signals():
                    normal = bool(
                        runtime.get("raw_return_code") == 0
                        and runtime.get("timed_out") is False
                        and supervisor_error is None
                    )
                    while True:
                        try:
                            leader_row = runtime["leader_identity"]
                            group = safety.drain_owned_processes(
                                process,
                                pgid,
                                (int(leader_row["pid"]), int(leader_row["start_ticks"])),
                                baseline_children,
                                normal_exit=normal,
                            )
                            group["cleanup_retry_errors"] = cleanup_errors
                            runtime["process_group"] = group
                            runtime["raw_return_code"] = process.returncode
                            break
                        except BaseException as cleanup_error:
                            cleanup_errors.append(
                                f"{type(cleanup_error).__name__}:{cleanup_error}"
                            )
                            normal = False
                            time.sleep(0.1)
                group = runtime["process_group"]
                if group.get("term_group_sent") and runtime.get("raw_return_code") == 0:
                    supervisor_error = add_error(supervisor_error, "NORMAL_RC_LEFT_ORIGINAL_PROCESS_GROUP")
                for key, code in (
                    ("leader_reaped", "LEADER_NOT_REAPED"),
                    ("process_group_empty", "PROCESS_GROUP_NOT_EMPTY"),
                    ("owned_descendants_empty", "OWNED_DESCENDANTS_NOT_EMPTY"),
                ):
                    if group.get(key) is not True:
                        supervisor_error = add_error(supervisor_error, code)
            if pending_signals:
                names = ",".join(signal.Signals(value).name for value in pending_signals)
                supervisor_error = add_error(supervisor_error, f"TERMINATION_SIGNALS:{names}")

    # The caller's outer interruption handler remains installed.  Block the
    # terminal signals before it is restored so final audits and durable
    # receipt publication have no unguarded signal edge.
    finalization_previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, TERM_SIGNALS)

    outputs: dict[str, Any] = {}
    semantic_checks: list[dict[str, Any]] = []
    artifact_issues: list[str] = []
    score: dict[str, Any] = {"status": "FAIL", "failure_codes": ["OUTPUT_AUDIT_NOT_RUN"]}
    try:
        outputs, semantic_checks, score = audit_outputs(lock, item_id, item)
    except BaseException as error:
        artifact_issues.append(f"{type(error).__name__}:{error}")
        score = {"status": "FAIL", "failure_codes": ["ARTIFACT_CONTRACT_NOT_PASS"]}
    try:
        lock_after, identity_after = verify_authority(lock_path)
        authority_post = {
            "status": "PASS" if lock_after == lock and identity_after == lock_identity else "FAIL",
            "lock": identity_after,
        }
        if authority_post["status"] != "PASS":
            supervisor_error = add_error(supervisor_error, "AUTHORITY_CHANGED_DURING_RUN")
    except BaseException as error:
        authority_post = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
        supervisor_error = add_error(supervisor_error, "AUTHORITY_POSTCHECK_FAILED")
    try:
        quiescence_post = quiescence("postflight")
        if quiescence_post["status"] != "PASS":
            supervisor_error = add_error(supervisor_error, "POSTFLIGHT_PROCESS_PRESENT")
    except BaseException as error:
        quiescence_post = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
        supervisor_error = add_error(supervisor_error, "POSTFLIGHT_PROCESS_AUDIT_FAILED")
    try:
        claim_identity_postflight = identity(claim_path)
        order_postflight = enforce_item_order(
            lock, lock_identity, item_id, "postflight", claim_identity_postflight,
        )
    except BaseException as error:
        order_postflight = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
        supervisor_error = add_error(supervisor_error, "POSTFLIGHT_ITEM_ORDER_FAILED")
    try:
        workspace_postflight = workspace_guard(
            item, "postflight", workspace_before_claim,
        )
    except BaseException as error:
        workspace_postflight = {"status": "FAIL", "error": f"{type(error).__name__}:{error}"}
        supervisor_error = add_error(supervisor_error, "POSTFLIGHT_WORKSPACE_GUARD_FAILED")
    if inherited_pending_signals:
        names = ",".join(signal.Signals(int(value)).name for value in inherited_pending_signals)
        marker = f"TERMINATION_SIGNALS:{names}"
        if marker not in (supervisor_error or ""):
            supervisor_error = add_error(supervisor_error, marker)

    seal = seal_science_tree(item, semantics)
    if seal["status"] != "PASS":
        artifact_issues.append(
            "SEALED_IN_PLACE_MISSING_SCIENCE:" + ",".join(seal["missing_science_files"])
        )
        score = {"status": "FAIL", "failure_codes": ["SEALED_IN_PLACE_INCOMPLETE"]}

    terminal = terminal_layer(runtime, timeout)
    artifact = {
        "status": "PASS" if not artifact_issues else "FAIL",
        "outputs": outputs,
        "semantic_checks": semantic_checks,
        "issues": artifact_issues,
    }
    group = terminal["process_group"] or {}
    execution_ok = bool(
        supervisor_error is None
        and authority_before_popen.get("status") == "PASS"
        and authority_post.get("status") == "PASS"
        and quiescence_before.get("status") == "PASS"
        and quiescence_before_popen.get("status") == "PASS"
        and quiescence_post.get("status") == "PASS"
        and order_after_claim.get("status") == "PASS_STRICT_SERIAL_ITEM_ORDER"
        and order_before_popen.get("status") == "PASS_STRICT_SERIAL_ITEM_ORDER"
        and order_postflight.get("status") == "PASS_STRICT_SERIAL_ITEM_ORDER"
        and seal.get("status") == "PASS"
        and workspace_after_claim.get("output_inode") == workspace_before_claim.get("output_inode")
        and workspace_before_popen.get("output_inode") == workspace_before_claim.get("output_inode")
        and workspace_postflight.get("output_inode") == workspace_before_claim.get("output_inode")
        and group.get("leader_reaped") is True
        and group.get("process_group_empty") is True
        and group.get("owned_descendants_empty") is True
    )
    execution = {
        "status": "PASS" if execution_ok else "FAIL",
        "supervisor_error": supervisor_error,
        "effective_environment": environment,
        "authority_before_popen": authority_before_popen,
        "authority_post": authority_post,
        "quiescence_before_claim": dict(quiescence_before),
        "quiescence_after_claim_before_popen": quiescence_before_popen,
        "quiescence_postflight": quiescence_post,
        "item_order_after_claim": dict(order_after_claim),
        "item_order_before_popen": order_before_popen,
        "item_order_postflight": order_postflight,
        "ambient_desktop_allowed_by_user_development_waiver": True,
        "machine_exclusive_cpu_scheduling": False,
        "runtime_or_throughput_claim_permitted": False,
    }
    claim_identity = identity(claim_path)
    claim_observed_mode = validate_projected_mode(
        claim_path, semantics, f"current-claim:{item_id}",
    )
    process_log = (
        identity(log_path) if str(log_path) in seal["science_snapshot_before_receipt"] else None
    )
    post_receipt_exact_files = sorted(
        [*seal["pre_receipt_exact_tree"]["seen_files"], str(receipt_path)]
    )
    sealed_in_place_invariant = {
        **seal,
        "workspace_guards": {
            "before_claim": dict(workspace_before_claim),
            "after_claim": dict(workspace_after_claim),
            "before_popen": workspace_before_popen,
            "postflight": workspace_postflight,
        },
        "receipt_atomic_publication_required": True,
        "claim_observed_mode": claim_observed_mode,
        "receipt_requested_mode": semantics["requested_mode"],
        "receipt_observed_mode": semantics["observed_mode"],
        "receipt_posix_readonly_enforced": False,
        "post_receipt_exact_tree_directory_fsync_and_rehash_required": True,
        "post_receipt_exact_files": post_receipt_exact_files,
        "post_receipt_exact_directories": seal["pre_receipt_exact_tree"]["seen_directories"],
        "science_snapshot_sha256": compact_sha256(
            seal["science_snapshot_before_receipt"]
        ),
    }
    receipt: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "item_id": item_id,
        "kind": "backend_replay",
        "status": terminal["status"],
        "started_at_local": started_at,
        "ended_at_local": now_local(),
        "wall_time_seconds": time.monotonic() - started_monotonic,
        "launch_allowance_consumed": True,
        "execution_lock": dict(lock_identity),
        "claim": claim_identity,
        "process_log": process_log,
        "terminal_process": terminal,
        "artifact_contract": artifact,
        "score_usability": score,
        "execution_integrity": execution,
        "causal_lineage": item["causal_lineage"],
        "sealed_in_place_invariant": sealed_in_place_invariant,
    }
    receipt["overall_disposition"] = disposition(receipt)
    publication = safety.atomic_publish(receipt_path, receipt)
    require(
        publication in {"PUBLISHED", "PUBLISHED_POSTLINK_RECOVERED"},
        f"RECEIPT_PUBLICATION:{publication}",
    )
    for directory in (
        Path(item["output_dir"]).absolute() / "vins_output",
        Path(item["output_dir"]).absolute(),
    ):
        if directory.exists():
            fsync_directory(directory)
    final_tree = audit_output_tree(
        item,
        receipt_allowed=True,
        require_all_expected=(seal["status"] == "PASS"),
    )
    require(
        final_tree["seen_files"] == post_receipt_exact_files,
        "POST_RECEIPT_EXACT_TREE_CHANGED",
    )
    require(
        final_tree["seen_directories"]
        == sealed_in_place_invariant["post_receipt_exact_directories"],
        "POST_RECEIPT_EXACT_DIRECTORIES_CHANGED",
    )
    final_science = validate_science_snapshot(
        seal["science_snapshot_before_receipt"], semantics,
    )
    require(
        compact_sha256(final_science) == sealed_in_place_invariant["science_snapshot_sha256"],
        "POST_RECEIPT_SCIENCE_SNAPSHOT_DIGEST",
    )
    workspace_guard(item, "post_receipt", workspace_before_claim)
    receipt_after, receipt_identity_after = stable_json(receipt_path)
    require(receipt_after == receipt, "POST_RECEIPT_BYTES_CHANGED")
    validate_projected_mode(receipt_path, semantics, f"current-receipt:{item_id}")
    require(receipt_identity_after == identity(receipt_path), "POST_RECEIPT_IDENTITY_UNSTABLE")
    result = (0 if receipt["overall_disposition"] == "ACCEPTED" else 1), receipt
    signal.pthread_sigmask(signal.SIG_SETMASK, finalization_previous_mask)
    return result


def run_item(lock_path: Path, item_id: str, token: str) -> tuple[int, dict[str, Any]]:
    require(token == AUTHORIZATION_TOKENS[item_id], "AUTHORIZATION_TOKEN_MISMATCH")
    contract = contract_module()
    safety = safety_module()
    with DualFlock(contract.FRONTEND_FLOCK, contract.BACKEND_FLOCK):
        lock, lock_identity = verify_authority(lock_path)
        prepare_layout(lock)
        item = lock["items"][item_id]
        semantics = storage_permission_semantics(lock)
        output = Path(item["output_dir"]).absolute()
        claim_path = output / CLAIM_NAME
        receipt_path = output / RECEIPT_NAME
        log_path = output / LOG_NAME
        order_before = enforce_item_order(
            lock, lock_identity, item_id, "before_claim",
        )
        for path in (claim_path, receipt_path, log_path):
            require(not path.exists() and not path.is_symlink(), f"ONE_SHOT_ARTIFACT_EXISTS:{path}")
        prelaunch_empty(item)
        workspace_before = workspace_guard(item, "before_claim")
        before = quiescence("before_claim")
        require(before["status"] == "PASS", "PROCESS_PRESENT_BEFORE_CLAIM")
        environment = effective_environment(lock, item)
        started_at = now_local()
        claim = {
            "schema_version": RECEIPT_SCHEMA,
            "item_id": item_id,
            "status": "CLAIMED_BEFORE_SINGLE_POPEN",
            "started_at_local": started_at,
            "launch_allowance_consumed": True,
            "popen_invocation_count_at_claim": 0,
            "retry_count": 0,
            "execution_lock": dict(lock_identity),
            "contract_sha256": lock["contract_sha256"],
            "argv": item["argv"],
            "effective_environment": environment,
            "input_binding": item["input_binding"],
            "causal_lineage": item["causal_lineage"],
            "frontend_authorities": lock["frontend_authorities"],
            "quiescence_before_claim": before,
            "item_order_before_claim": order_before,
            "workspace_guard_before_claim": workspace_before,
            "storage_permission_semantics": semantics,
            "claim_requested_mode": semantics["requested_mode"],
            "claim_observed_mode_policy": semantics["observed_mode"],
            "development_only": True,
            "machine_exclusive_cpu_scheduling": False,
        }
        safety.enable_subreaper()
        # Keep one handler installed from before durable claim publication
        # through receipt publication.  execute_claimed installs a nested
        # handler while it owns the child and also observes this outer list.
        with safety.interruption_handlers() as claim_pending_signals:
            safety.atomic_publish(
                claim_path, claim, propagate_interruption_after_commit=True
            )
            claim_identity_after = identity(claim_path)
            validate_projected_mode(
                claim_path, semantics, f"after-claim:{item_id}",
            )
            workspace_after = workspace_guard(
                item, "after_claim", workspace_before,
            )
            order_after = enforce_item_order(
                lock, lock_identity, item_id, "after_claim", claim_identity_after,
            )
            return execute_claimed(
                lock_path,
                lock,
                lock_identity,
                item_id,
                item,
                claim_path,
                receipt_path,
                log_path,
                started_at,
                before,
                workspace_before,
                workspace_after,
                order_after,
                claim_pending_signals,
            )


def status(lock_path: Path) -> dict[str, Any]:
    if not lock_path.exists() and not lock_path.is_symlink():
        return {"status": "LOCK_ABSENT", "lock_path": str(lock_path), "items": []}
    lock, lock_identity = stable_json(lock_path)
    rows: list[dict[str, Any]] = []
    items = lock.get("items") if isinstance(lock.get("items"), dict) else {}
    for item_id in ITEM_ORDER:
        item = items.get(item_id, {}) if isinstance(items, dict) else {}
        output_raw = item.get("output_dir")
        output = Path(output_raw) if isinstance(output_raw, str) else EXP_ROOT / "backends" / item_id
        receipt = output / RECEIPT_NAME
        claim = output / CLAIM_NAME
        if receipt.exists() or receipt.is_symlink():
            try:
                value, _ = stable_json(receipt)
                state = str(value.get("overall_disposition", value.get("status", "UNKNOWN")))
            except BaseException as error:
                state = f"INVALID_RECEIPT:{type(error).__name__}:{error}"
        elif claim.exists() or claim.is_symlink():
            state = "CLAIMED_WITHOUT_RECEIPT"
        else:
            state = "NOT_STARTED"
        rows.append({"item_id": item_id, "output_dir": str(output), "status": state})
    return {"status": "LOCK_PRESENT", "lock": lock_identity, "items": rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("check")
    commands.add_parser("prepare")
    run = commands.add_parser("run-item")
    run.add_argument("item_id", choices=ITEM_ORDER)
    run.add_argument("--authorization-token", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    lock_path = args.lock.absolute()
    if args.command == "status":
        print(json.dumps(status(lock_path), indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    if args.command == "check":
        lock, lock_identity = verify_authority(lock_path)
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "lock": lock_identity,
                    "contract_sha256": lock["contract_sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    contract = contract_module()
    if args.command == "prepare":
        with DualFlock(contract.FRONTEND_FLOCK, contract.BACKEND_FLOCK):
            lock, lock_identity = verify_authority(lock_path)
            prepare_layout(lock)
        print(json.dumps({"status": "PREPARED", "lock": lock_identity}, indent=2))
        return 0
    return_code, receipt = run_item(
        lock_path, args.item_id, args.authorization_token
    )
    print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False))
    return return_code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (BackendError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f"A09_BACKEND_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
        raise SystemExit(2)
