#!/usr/bin/env python3
"""Shared fail-closed primitives for the P07 serial backend replay pipeline.

This module deliberately contains no ROS/VINS launch side effect.  It validates
frozen queue rows and locks, provides an advisory global execution lock, and
holds reused feature bags through read-only file descriptors so a backend
replay never receives the mutable source pathname.
"""

from __future__ import annotations

import ast
import csv
import fcntl
import hashlib
import io
import json
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

try:
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_g0_governance_v1 as g0_governance
except ModuleNotFoundError:  # Direct ``python3 scripts/...`` execution.
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_g0_governance_v1 as g0_governance  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "papers/ieee_sensors_journal_experiments"
P07 = BUNDLE / "p07"
DEFAULT_QUEUE = P07 / "backend_replay_queue_v1.csv"
DEFAULT_ALLOCATION = P07 / "backend_run_allocation_v1.csv"
DEFAULT_QUEUE_LOCK = P07 / "backend_queue_lock_v1.json"
DEFAULT_EXECUTION_LOCK = P07 / "backend_replay_execution_lock_v1.json"
DEFAULT_EXECUTION_LOCK_RELATIVE = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_replay_execution_lock_v1.json"
)
DEFAULT_REGISTRY = BUNDLE / "run_registry.csv"
DEFAULT_ATTEMPT_ROOT = P07 / "backend_attempts"
DEFAULT_GLOBAL_FLOCK = Path("/tmp/aquafe_p07_backend_replay_v1.lock")
FROZEN_LOGS_ROOT = Path("/mnt/data/AQUA-FE_WS/logs")

QUEUE_SCHEMA = "isj-p07-backend-replay-queue-v1"
ALLOCATION_SCHEMA = "isj-p07-backend-run-allocation-v1"
QUEUE_LOCK_SCHEMA = "isj-p07-backend-queue-lock-v1"
QUEUE_LOCK_STATUS = "FROZEN_BACKEND_QUEUE_AWAITING_EXECUTION_LOCK"
EXECUTION_LOCK_SCHEMA = "isj-p07-backend-replay-execution-lock-v1"
EXECUTION_LOCK_STATUS = "FROZEN_READY_FOR_SERIAL_BACKEND_REPLAY"
EXECUTION_OUTCOME_BOUNDARY = (
    "SERIAL_BACKEND_REPLAY_AUTHORIZED_TRAJECTORY_UNREAD_AT_FREEZE"
)
EXECUTION_LOCK_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "frozen_at",
        "formalization_adoption",
        "formalization_review_evidence",
        "b0_formalization_adoption",
        "backend_queue_lock_hash",
        "queue_sha256",
        "allocation_sha256",
        "queue_lock_sha256",
        "validation_sha256",
        "registration_sha256",
        "queue_items",
        "execution_order",
        "allowed_entrypoint",
        "executor",
        "adapter",
        "auditor",
        "runtime_implementation_bindings",
        "external_runtime_bindings",
        "global_flock_path",
        "serialization",
        "adapter_policy",
        "data_identity_policy",
        "data_identity_snapshot",
        "b0_play_inputs",
        "g0_pre_replay_authority",
        "infrastructure_replacement",
        "capacity_gate",
        "method_lock_hash",
        "artifacts",
        "mutable_registry_prefix",
        "trajectory_outcome_read_at_freeze",
        "outcome_boundary",
        "execution_lock_hash",
    }
)
CAPACITY_GATE_KEYS = frozenset(
    {
        "policy",
        "margin_numerator",
        "margin_denominator",
        "reserve_bytes",
        "minimum_governance_free_bytes",
        "estimated_total_output_bytes",
        "required_output_free_bytes",
        "observed_output_free_bytes_at_freeze",
        "observed_governance_free_bytes_at_freeze",
        "output_filesystem_path",
        "governance_filesystem_path",
        "recompute_before_each_job",
        "insufficient_action",
    }
)
DATA_IDENTITY_SCHEMA = "isj-p07-backend-data-identity-snapshot-v1"
DATA_IDENTITY_STATUS = "VERIFIED_AT_EXECUTION_LOCK_FREEZE"
B0_PLAY_INPUTS_SCHEMA = "isj-p07-backend-b0-play-inputs-v1"
B0_PLAY_INPUTS_STATUS = "FROZEN_READY_FOR_B0_REPLAY"
DATA_IDENTITY_SELF_HASH = "data_identity_snapshot_hash"
B0_PLAY_INPUTS_SELF_HASH = "b0_play_inputs_hash"
B0_MATERIALIZATION_LOCK_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_lock_v1.json"
)
B0_MATERIALIZATION_INTENT_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_intent_v1.json"
)
B0_MATERIALIZATION_RECEIPT_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_materialization_receipt_v1.json"
)
B0_PLAY_INPUTS_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/backend_b0_play_inputs_v1.json"
)
FORMALIZATION_ADOPTION_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_adoption_v1.json"
)
FORMALIZATION_REVIEW_EVIDENCE_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_formalization_review_evidence_lock_v1.json"
)
B0_ADOPTION_PRELOCK_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_formalization_adoption_prelock_v1.json"
)
B0_ADOPTION_ACTION_INTENT_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_formalization_adoption_action_intent_v1.json"
)
B0_ADOPTION_CLOSEOUT_PATH = (
    "papers/ieee_sensors_journal_experiments/p07/"
    "backend_b0_formalization_adoption_closeout_v1.json"
)
B0_OUTCOME_BOUNDARY = "B0_INPUT_PREPARATION_ONLY_NO_VINS_APE_RPE_TRAJECTORY"
MIN_ABSOLUTE_ROS_EPOCH_NS = 100_000_000 * 1_000_000_000
MAX_ROS1_TIME_NS = (2**32 - 1) * 1_000_000_000 + 999_999_999

RUNTIME_IMPLEMENTATION_BINDING_PATHS = {
    "sealed_runtime_bootstrap": "scripts/p07_backend_sealed_runtime_v1.py",
    "job_entrypoint": "scripts/run_p07_backend_replay_job_v1.py",
    "adapter": "scripts/run_p07_backend_replay_adapter_v1.py",
    "auditor": "scripts/audit_p07_backend_replay_v1.py",
    "failure_collector": "scripts/collect_p07_backend_failure_v1.py",
    "input_checker": "scripts/check_p07_backend_replay_input_v1.py",
    "common": "scripts/p07_backend_replay_common_v1.py",
    "serial_controller": "scripts/run_p07_backend_serial_queue_v1.py",
    # Exact transitive Python closure reached by controller -> job imports.
    "formal_io": "scripts/p07_backend_formal_io_v1.py",
    "g0_governance": "scripts/p07_g0_governance_v1.py",
    "backend_evaluation": "scripts/p07_backend_evaluation_v1.py",
    "frontend_provenance": "scripts/p07_backend_frontend_provenance_v1.py",
    "g0_publisher": "scripts/p07_g0_publisher_v1.py",
    "g0_reference_contract_builder": "scripts/build_p07_g0_reference_contracts_v1.py",
    "legacy_d_compatibility_builder": (
        "scripts/build_p07_backend_legacy_d_compatibility_lock_v1.py"
    ),
    "evaluator_epoch_correction_builder": (
        "scripts/build_p07_evaluator_epoch_ns_correction_lock_v1.py"
    ),
    "queue_builder": "scripts/build_p07_backend_replay_queue_v1.py",
    "queue_validator": "scripts/validate_p07_backend_replay_queue_v1.py",
    "allocation_registration": "scripts/register_p07_backend_allocations_v1.py",
    "replacement_contract_builder": (
        "scripts/build_p07_backend_replacement_contract_v1.py"
    ),
    "replacement_allocator": "scripts/allocate_p07_backend_replacement_v1.py",
    "formalization_incident_governance": (
        "scripts/build_p07_backend_formalization_incident_v1.py"
    ),
    "formalization_adoption_governance": (
        "scripts/build_p07_backend_formalization_adoption_v1.py"
    ),
    "formalization_review_evidence_governance": (
        "scripts/build_p07_backend_formalization_review_evidence_v1.py"
    ),
    "b0_formalization_adoption_bridge": (
        "scripts/build_p07_backend_b0_formalization_adoption_bridge_v1.py"
    ),
    "b0_materialization_plan_builder": (
        "scripts/build_p07_backend_b0_materialization_lock_v1.py"
    ),
    "b0_materialization_executor": (
        "scripts/run_p07_backend_b0_materialization_v1.py"
    ),
    "direct_runner_ntnu": "scripts/run_ntnu_vins_eval.sh",
    "direct_runner_aqualoc_archaeology": "scripts/run_aqualoc_archaeo_vins_eval.sh",
    "direct_runner_aqualoc_harbor": "scripts/run_aqualoc_real_vins_eval.sh",
    "direct_runner_afrl": "scripts/run_afrl_cave_vins_eval.sh",
    "b0_guard_wrapper": "scripts/run_isj_b0_native_vins_guarded_v1.sh",
    "b0_identity_checker": "scripts/check_b0_vins_origin_identity_v1.py",
    "replay_only_runner": "scripts/run_p07_backend_replay_only_v1.sh",
    "config_helper": "scripts/prepare_p07_backend_replay_config_v1.py",
    "nativeq_contract_builder": "scripts/build_nativeq_backend_contract.py",
    "nativeq_contract_document": (
        "papers/ieee_sensors_journal_experiments/backend_quality_contract_v1.json"
    ),
    "xfeat_contract_document": (
        "papers/ieee_sensors_journal_experiments/p05/"
        "backend_consumer_contract_xfeat_v1.json"
    ),
    "nativeq_contract_checker": "scripts/check_nativeq_backend_contract.py",
    "xfeat_contract_checker": "scripts/check_p05_xfeat_backend_contract_v1.py",
}

SEALED_RUNTIME_SCHEMA = "isj-p07-backend-sealed-runtime-v1"
SEALED_RUNTIME_ENVIRONMENT_KEY = "AQUAFE_P07_SEALED_RUNTIME_V1"
SEALED_EXECUTION_LOCK_HASH_KEY = "AQUAFE_P07_EXECUTION_LOCK_SHA256"
SEALED_RUNTIME_BOOTSTRAP_ROLE = "sealed_runtime_bootstrap"

B0_ARM = "B0_native_vins_origin_v1"
B1_ARM = "B1_klt_nativeq_v3"
P_ARM = "P_legacy_nativeq_xfeat_seedchain_v3"
M_ARM = "M_xfeat_pairwise_nativeq_v1"
D_ARM = "D_legacy_exact_lineage_drop_v3"
ALL_ARMS = frozenset({B0_ARM, B1_ARM, P_ARM, M_ARM, D_ARM})
FEATURE_BAG_ARMS = frozenset({B1_ARM, P_ARM, M_ARM, D_ARM})
NATIVEQ_ARMS = frozenset({B1_ARM, P_ARM, D_ARM})

VINS_ORIGIN = Path("/home/ma/SLAM/VINS-Fusion-origin")
FORBIDDEN_VINS_WORKSPACE = Path("/home/ma/SLAM/VINS-Fusion_3-15-WS")
# The execution lock binds the interpreter that replaces every historical
# ``python3`` lookup in the formal controller -> job chain.  Use the canonical
# system interpreter explicitly instead of deriving authority from whichever
# interpreter happened to import this module.
PYTHON_INTERPRETER = Path("/usr/bin/python3.8")
EXTERNAL_RUNTIME_BINDING_PATHS = {
    "python_interpreter": PYTHON_INTERPRETER,
    "vins_binary": VINS_ORIGIN / "devel/lib/vins/vins_node",
    "vins_shared_library": VINS_ORIGIN / "devel/lib/libvins_lib.so",
    "camera_models_shared_library": (
        VINS_ORIGIN / "devel/lib/libcamera_models.so"
    ),
}

# Formal runners never source catkin setup files.  The job supplies this
# minimal, deterministic ROS1 environment directly; it deliberately excludes
# chained user workspaces such as dave_ws/uuv_ws and VINS devel setup hooks.
FROZEN_ROS_ENVIRONMENT = {
    "PATH": (
        "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "PYTHONPATH": "/opt/ros/noetic/lib/python3/dist-packages",
    "ROS_DISTRO": "noetic",
    "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
    "ROS_MASTER_URI": "http://localhost:11311",
    "ROS_PACKAGE_PATH": "/opt/ros/noetic/share",
    "ROS_PYTHON_VERSION": "3",
    "ROS_ROOT": "/opt/ros/noetic/share/ros",
    "ROS_VERSION": "1",
}
FROZEN_ROS_EXECUTABLES = {
    "roscore": "/opt/ros/noetic/bin/roscore",
    "rosparam": "/opt/ros/noetic/bin/rosparam",
    "rosbag": "/opt/ros/noetic/bin/rosbag",
}


def validate_frozen_ros_platform() -> None:
    """Require the minimal ROS platform authority to remain root-owned/plain."""

    required_paths = {
        *FROZEN_ROS_EXECUTABLES.values(),
        FROZEN_ROS_ENVIRONMENT["ROS_ETC_DIR"],
        FROZEN_ROS_ENVIRONMENT["ROS_ROOT"],
        FROZEN_ROS_ENVIRONMENT["ROS_PACKAGE_PATH"],
        FROZEN_ROS_ENVIRONMENT["PYTHONPATH"],
    }
    for raw in sorted(required_paths):
        path = Path(raw)
        try:
            info = os.stat(path, follow_symlinks=False)
            resolved = path.resolve(strict=True)
        except OSError as error:
            raise BackendReplayViolation(
                f"frozen ROS platform path is unavailable: {path}"
            ) from error
        if (
            resolved != path
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise BackendReplayViolation(
                f"frozen ROS platform path is not root-owned/canonical: {path}"
            )
        if path.as_posix() in FROZEN_ROS_EXECUTABLES.values():
            if not stat.S_ISREG(info.st_mode) or not info.st_mode & 0o111:
                raise BackendReplayViolation(
                    f"frozen ROS executable semantics differ: {path}"
                )
        elif not stat.S_ISDIR(info.st_mode):
            raise BackendReplayViolation(
                f"frozen ROS platform directory semantics differ: {path}"
            )

EXPECTED_RUNNER_MODE = {
    B0_ARM: "origin",
    B1_ARM: "external",
    P_ARM: "external",
    M_ARM: "external",
    D_ARM: "external",
}
EXPECTED_RUNNER_METHOD = {
    B0_ARM: "klt",
    B1_ARM: "klt",
    P_ARM: "klt",
    M_ARM: "xfeat",
    D_ARM: "klt",
}

REQUIRED_QUEUE_FIELDS = frozenset(
    {
        "schema_version",
        "queue_index",
        "run_id",
        "window_id",
        "dataset_family",
        "sequence",
        "arm",
        "replay_index",
        "algorithmic_slot",
        "feature_bag",
        "feature_bag_sha256",
        "attestation_path",
        "attestation_sha256",
        "input_audit_path",
        "input_audit_sha256",
        "source_run_id",
        "source_provenance_kind",
        "source_provenance_hash",
        "replay_argv_json",
        "replay_argv_sha256",
        "expected_run_dir",
        "expected_attempt_dir",
        "runner_start",
        "runner_end_or_duration",
        "runner_unit",
        "runner_mode",
        "runner_method",
        "runner_every_n",
        "runner_tag",
        "estimated_output_bytes",
        "status",
        "method_lock_hash",
        "outcome_boundary",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SAFE_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
_FORBIDDEN_REPLAY_TOKENS = (
    "run_paper_sidecar_profiles",
    "run_isj_nativeq_contract_guarded",
    "run_p05_modern_xfeat_baseline_guarded",
    "run_isj_b1_klt_nativeq_guarded",
    "run_p07_frontend",
    "export_vins_features",
    "frontend_export",
)


class BackendReplayViolation(RuntimeError):
    """A frozen replay or safety invariant was not satisfied."""


class LockBusy(BackendReplayViolation):
    """Another P07 backend replay currently owns the global lock."""


class CapacityWaiting(BackendReplayViolation):
    """Capacity is insufficient; the job remains untouched and waiting."""


class InfrastructureWaiting(BackendReplayViolation):
    """A pre-launch infrastructure dependency is temporarily unavailable."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_open_regular(path: Path) -> tuple[str, os.stat_result]:
    """Hash one final regular inode without following a last-component link.

    The caller resolves and freezes the lexical symlink chain separately.  The
    final target is opened with ``O_NOFOLLOW`` and its identity is checked again
    after hashing so a publisher cannot freeze a path through a rename race.
    """

    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise BackendReplayViolation(f"cannot safely open frozen input target: {path}") from error
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise BackendReplayViolation(f"frozen input target is not regular: {path}")
        digest = hashlib.sha256()
        offset = 0
        while offset < before.st_size:
            chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
            if not chunk:
                raise BackendReplayViolation(f"short read while hashing frozen input: {path}")
            digest.update(chunk)
            offset += len(chunk)
        after = os.fstat(fd)
        identity_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
        if any(getattr(before, field) != getattr(after, field) for field in identity_fields):
            raise BackendReplayViolation(f"frozen input changed while hashing: {path}")
        return digest.hexdigest(), after
    finally:
        os.close(fd)


def canonical_json_hash(payload: Mapping[str, Any], self_field: str) -> str:
    clone = dict(payload)
    clone.pop(self_field, None)
    encoded = json.dumps(
        clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256_bytes(encoded)


def parse_canonical_json_object(content: bytes, *, label: str) -> dict[str, Any]:
    """Decode one exact pretty-canonical JSON object and reject duplicate keys."""

    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise BackendReplayViolation(f"duplicate JSON key in {label}: {key}")
            value[key] = item
        return value

    try:
        payload = json.loads(
            content.decode("utf-8"), object_pairs_hook=reject_duplicates
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendReplayViolation(f"invalid {label} JSON") from error
    if not isinstance(payload, dict):
        raise BackendReplayViolation(f"{label} is not a JSON object")
    expected = (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")
    if content != expected:
        raise BackendReplayViolation(f"{label} JSON is not canonical")
    return payload


def validate_absolute_ros_epoch_window(
    start_ns: object, end_ns: object, *, label: str
) -> tuple[int, int]:
    """Reject relative, coerced, boolean, and out-of-range ROS1 timestamps."""

    if type(start_ns) is not int or type(end_ns) is not int:
        raise BackendReplayViolation(f"{label} timestamps must be exact integers")
    if (
        start_ns < MIN_ABSOLUTE_ROS_EPOCH_NS
        or end_ns <= start_ns
        or end_ns > MAX_ROS1_TIME_NS
    ):
        raise BackendReplayViolation(
            f"{label} is not an absolute in-range ROS epoch-ns interval"
        )
    return start_ns, end_ns


def lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _has_parent_reference(raw: str) -> bool:
    return ".." in Path(raw).parts


def workspace_path(root: Path, raw: str, *, label: str, must_exist: bool = True) -> Path:
    if not raw or "\x00" in raw or _has_parent_reference(raw):
        raise BackendReplayViolation(f"invalid {label} path: {raw!r}")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = lexical_absolute(candidate)
    if os.fspath(FORBIDDEN_VINS_WORKSPACE) in os.fspath(candidate):
        raise BackendReplayViolation(f"{label} names forbidden VINS workspace")
    if must_exist and not candidate.is_file():
        raise BackendReplayViolation(f"missing regular {label}: {candidate}")
    return candidate


def read_direct_workspace_bytes(
    root: Path, raw: str, *, label: str
) -> tuple[Path, bytes, dict[str, int]]:
    """Read a repository-relative control artifact without following any symlink."""

    pure = PurePosixPath(raw)
    if (
        not raw
        or "\x00" in raw
        or pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
    ):
        raise BackendReplayViolation(f"invalid direct {label} path: {raw!r}")
    try:
        content, identity = formal_io.read_direct_bytes(root, pure.as_posix())
    except (OSError, ValueError, formal_io.FormalIOError) as error:
        raise BackendReplayViolation(
            f"cannot read direct {label}: {pure.as_posix()}"
        ) from error
    return lexical_absolute(root.joinpath(*pure.parts)), content, identity


def read_locked_artifact_bytes(
    root: Path, record: Mapping[str, Any], *, label: str = "locked artifact"
) -> tuple[Path, bytes]:
    """Read and verify an immutable artifact in one no-follow operation."""

    try:
        raw = str(record["path"])
        size = int(record["size_bytes"])
        expected_hash = str(record["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise BackendReplayViolation(f"invalid {label} record") from error
    if size < 0 or not _SHA256_RE.fullmatch(expected_hash):
        raise BackendReplayViolation(f"invalid {label} SHA-256/size")
    path, content, _identity = read_direct_workspace_bytes(root, raw, label=label)
    if len(content) != size or sha256_bytes(content) != expected_hash:
        raise BackendReplayViolation(f"{label} drift: {path}")
    return path, content


def output_path(root: Path, raw: str, *, label: str) -> Path:
    if not raw or "\x00" in raw or _has_parent_reference(raw):
        raise BackendReplayViolation(f"invalid {label} path: {raw!r}")
    path = Path(raw)
    root = lexical_absolute(root)
    if path.is_absolute():
        path = lexical_absolute(path)
        root_prefix = os.fspath(root) + os.sep
        if not os.fspath(path).startswith(root_prefix):
            raise BackendReplayViolation(f"{label} is outside the workspace: {path}")
    else:
        if path.parts[0] not in {"logs", "papers"}:
            raise BackendReplayViolation(
                f"{label} must be rooted under logs/ or papers/: {raw!r}"
            )
        path = lexical_absolute(root / path)
    if os.fspath(FORBIDDEN_VINS_WORKSPACE) in os.fspath(path):
        raise BackendReplayViolation(f"{label} names forbidden VINS workspace")
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise BackendReplayViolation(f"{label} is outside the workspace") from error
    if not relative.parts or relative.parts[0] not in {"logs", "papers"}:
        raise BackendReplayViolation(f"{label} has an invalid workspace root")
    base = root / relative.parts[0]
    if base.exists() or base.is_symlink():
        base_info = os.lstat(base)
        if relative.parts[0] == "papers" and stat.S_ISLNK(base_info.st_mode):
            raise BackendReplayViolation("papers output root must not be a symlink")
        if not (stat.S_ISDIR(base_info.st_mode) or stat.S_ISLNK(base_info.st_mode)):
            raise BackendReplayViolation(f"{label} output root is not a directory")
        if (
            root == lexical_absolute(ROOT)
            and relative.parts[0] == "logs"
            and base.resolve() != FROZEN_LOGS_ROOT
        ):
            raise BackendReplayViolation(
                f"logs output root differs from frozen target: {base.resolve()}"
            )
    current = base
    for component in relative.parts[1:-1]:
        current /= component
        if not current.exists() and not current.is_symlink():
            break
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise BackendReplayViolation(
                f"{label} has a non-directory or symlink ancestor: {current}"
            )
    return path


def display_path(root: Path, path: Path) -> str:
    path = lexical_absolute(path)
    try:
        return path.relative_to(lexical_absolute(root)).as_posix()
    except ValueError:
        return os.fspath(path)


def _stat_identity(info: os.stat_result) -> dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "owner_uid": int(info.st_uid),
    }


def _lexical_components(root: Path, path: Path) -> list[Path]:
    root = lexical_absolute(root)
    path = lexical_absolute(path)
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise BackendReplayViolation(
            f"frozen data input must be lexically inside the workspace: {path}"
        ) from error
    current = root
    result: list[Path] = []
    for part in relative.parts:
        current /= part
        result.append(current)
    return result


def capture_canonical_input_identity(
    root: Path,
    raw: str,
    *,
    expected_sha256: str,
    verify_sha256: bool,
) -> dict[str, Any]:
    """Capture a workspace path, every symlink component, and its final inode.

    Canonical dataset links are permitted only when every link component and
    the final resolved target are frozen.  Unrecorded link traversal is thereby
    impossible at replay time.  This helper reads no trajectory semantics.
    """

    if not _SHA256_RE.fullmatch(expected_sha256):
        raise BackendReplayViolation("invalid expected frozen-input SHA-256")
    path = workspace_path(root, raw, label="data-identity input")
    symlinks: list[dict[str, Any]] = []
    for component in _lexical_components(root, path):
        try:
            info = os.lstat(component)
        except OSError as error:
            raise BackendReplayViolation(
                f"missing lexical component in frozen data input: {component}"
            ) from error
        if stat.S_ISLNK(info.st_mode):
            symlinks.append(
                {
                    "path": display_path(root, component),
                    "link_target": os.readlink(component),
                    "lstat_identity": _stat_identity(info),
                }
            )
    try:
        target = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise BackendReplayViolation(f"cannot resolve frozen data input: {raw}") from error
    if target.is_symlink():
        raise BackendReplayViolation("resolved frozen data target unexpectedly remains a link")
    observed_hash: str | None = None
    if verify_sha256:
        observed_hash, target_info = _sha256_open_regular(target)
        if observed_hash != expected_sha256:
            raise BackendReplayViolation(f"frozen data input SHA-256 mismatch: {raw}")
    else:
        try:
            target_info = os.stat(target, follow_symlinks=False)
        except OSError as error:
            raise BackendReplayViolation(f"missing frozen data target: {target}") from error
        if not stat.S_ISREG(target_info.st_mode):
            raise BackendReplayViolation(f"frozen data target is not regular: {target}")
    return {
        "path": display_path(root, path),
        "path_kind": (
            "CANONICAL_SYMLINK_TARGET" if symlinks else "PLAIN_REGULAR_FILE"
        ),
        "symlink_components": symlinks,
        "resolved_target_path": os.fspath(target),
        "resolved_target_identity": _stat_identity(target_info),
        "expected_sha256": expected_sha256,
        "sha256_verified": verify_sha256,
        "observed_sha256": observed_hash,
    }


def _identity_comparison_view(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: record.get(key)
        for key in (
            "path",
            "path_kind",
            "symlink_components",
            "resolved_target_path",
            "resolved_target_identity",
            "expected_sha256",
        )
    }


def validate_canonical_input_identity_shape(record: Mapping[str, Any]) -> None:
    if (
        record.get("path_kind")
        not in {"PLAIN_REGULAR_FILE", "CANONICAL_SYMLINK_TARGET"}
        or not isinstance(record.get("path"), str)
        or not isinstance(record.get("resolved_target_path"), str)
        or not _SHA256_RE.fullmatch(str(record.get("expected_sha256", "")))
        or not isinstance(record.get("symlink_components"), list)
        or not isinstance(record.get("resolved_target_identity"), dict)
    ):
        raise BackendReplayViolation("invalid canonical frozen-input identity record")
    components = record["symlink_components"]
    if record["path_kind"] == "PLAIN_REGULAR_FILE" and components:
        raise BackendReplayViolation("plain frozen-input record contains symlink components")
    if record["path_kind"] == "CANONICAL_SYMLINK_TARGET" and not components:
        raise BackendReplayViolation("canonical-link record lacks symlink components")
    previous = ""
    seen: set[str] = set()
    for component in components:
        if not isinstance(component, dict):
            raise BackendReplayViolation("invalid frozen symlink component")
        raw_path = component.get("path")
        identity = component.get("lstat_identity")
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or raw_path in seen
            or not isinstance(component.get("link_target"), str)
            or not isinstance(identity, dict)
            or any(
                not isinstance(identity.get(key), int)
                for key in (
                    "device",
                    "inode",
                    "mode",
                    "size_bytes",
                    "mtime_ns",
                    "owner_uid",
                )
            )
        ):
            raise BackendReplayViolation("malformed frozen symlink component")
        if previous and not raw_path.startswith(previous.rstrip("/") + "/"):
            raise BackendReplayViolation("frozen symlink components are not an ancestor chain")
        previous = raw_path
        seen.add(raw_path)
    target_identity = record["resolved_target_identity"]
    if any(
        not isinstance(target_identity.get(key), int)
        for key in (
            "device",
            "inode",
            "mode",
            "size_bytes",
            "mtime_ns",
            "owner_uid",
        )
    ) or not stat.S_ISREG(int(target_identity["mode"])):
        raise BackendReplayViolation("invalid frozen resolved-target identity")


def revalidate_canonical_input_identity(
    root: Path,
    record: Mapping[str, Any],
    *,
    verify_sha256: bool,
) -> dict[str, Any]:
    validate_canonical_input_identity_shape(record)
    observed = capture_canonical_input_identity(
        root,
        str(record["path"]),
        expected_sha256=str(record["expected_sha256"]),
        verify_sha256=verify_sha256,
    )
    if _identity_comparison_view(observed) != _identity_comparison_view(record):
        raise BackendReplayViolation(
            f"frozen data path/link/target identity drift: {record.get('path')}"
        )
    return observed


def parse_csv_bytes(
    content: bytes, *, label: str
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BackendReplayViolation(f"invalid UTF-8 CSV: {label}") from error
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = list(reader.fieldnames or [])
    rows = list(reader)
    if not fields or len(fields) != len(set(fields)) or any(None in row for row in rows):
        raise BackendReplayViolation(f"invalid or ragged CSV: {label}")
    return fields, rows


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    return parse_csv_bytes(path.read_bytes(), label=os.fspath(path))


def indexed_row(path: Path, index: int) -> dict[str, str]:
    _fields, rows = read_csv(path)
    matches = [row for row in rows if row.get("queue_index") == str(index)]
    if len(matches) != 1:
        raise BackendReplayViolation(
            f"expected exactly one queue_index={index} row in {path}, got {len(matches)}"
        )
    return matches[0]


def parse_replay_argv(row: Mapping[str, str]) -> list[str]:
    raw = row.get("replay_argv_json", "")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BackendReplayViolation(f"invalid replay_argv_json: {error}") from error
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or "\x00" in item for item in value)
    ):
        raise BackendReplayViolation("replay_argv_json must be a non-empty string array")
    expected_hash = row.get("replay_argv_sha256", "")
    if not _SHA256_RE.fullmatch(expected_hash) or sha256_bytes(raw.encode("utf-8")) != expected_hash:
        raise BackendReplayViolation("replay argv hash mismatch")
    joined = "\n".join(value).lower()
    if any(token in joined for token in _FORBIDDEN_REPLAY_TOKENS):
        raise BackendReplayViolation("replay argv references a forbidden export/frontend wrapper")
    expected = [
        "python3",
        "scripts/run_p07_backend_replay_job_v1.py",
        "--queue-index",
        row["queue_index"],
        "--execution-lock",
        DEFAULT_EXECUTION_LOCK_RELATIVE,
    ]
    if value != expected:
        raise BackendReplayViolation(
            "formal replay argv must be the exact governed job invocation"
        )
    return value


def validate_queue_row(row: Mapping[str, str]) -> None:
    missing = REQUIRED_QUEUE_FIELDS.difference(row)
    if missing:
        raise BackendReplayViolation(f"backend queue row missing fields: {sorted(missing)}")
    if row["schema_version"] != QUEUE_SCHEMA:
        raise BackendReplayViolation(f"unexpected backend queue schema: {row['schema_version']}")
    try:
        queue_index = int(row["queue_index"])
        replay_index = int(row["replay_index"])
        every_n = int(row["runner_every_n"])
        estimated = int(row["estimated_output_bytes"])
    except ValueError as error:
        raise BackendReplayViolation("non-integer backend queue identity field") from error
    if queue_index < 1 or replay_index not in (1, 2, 3) or every_n != 2 or estimated <= 0:
        raise BackendReplayViolation("invalid queue index, replay index, stride, or estimate")
    if row["algorithmic_slot"] != f"b{replay_index:02d}":
        raise BackendReplayViolation("replay_index/algorithmic_slot mismatch")
    if not row["run_id"] or not row["window_id"]:
        raise BackendReplayViolation("empty run_id or window_id")
    if (
        not row["source_run_id"]
        or not row["source_provenance_kind"]
        or not _SHA256_RE.fullmatch(row["source_provenance_hash"])
    ):
        raise BackendReplayViolation("queue row lacks frozen source provenance")
    arm = row["arm"]
    if arm not in ALL_ARMS:
        raise BackendReplayViolation(f"unrecognized backend arm: {arm}")
    if row["status"] != "PLANNED":
        raise BackendReplayViolation("frozen queue row is not PLANNED")
    if row["runner_mode"] != EXPECTED_RUNNER_MODE[arm]:
        raise BackendReplayViolation("arm/runner_mode mismatch")
    if row["runner_method"] != EXPECTED_RUNNER_METHOD[arm]:
        raise BackendReplayViolation("arm/runner_method mismatch")
    if not _SAFE_TAG_RE.fullmatch(row["runner_tag"]):
        raise BackendReplayViolation("unsafe or empty runner_tag")
    try:
        float(row["runner_start"])
        float(row["runner_end_or_duration"])
    except ValueError as error:
        raise BackendReplayViolation("invalid runner interval") from error
    if row["runner_unit"] not in {"frame", "second"}:
        raise BackendReplayViolation("runner_unit must be frame or second")
    if not _SHA256_RE.fullmatch(row["method_lock_hash"]):
        raise BackendReplayViolation("invalid method lock hash")
    for field in (
        "environment_manifest_sha256",
        "evaluator_protocol_sha256",
        "evaluator_implementation_sha256",
        "failure_taxonomy_sha256",
    ):
        if field in row and not _SHA256_RE.fullmatch(row[field]):
            raise BackendReplayViolation(f"invalid {field}")
    if row.get("capacity_policy") != "REMAINING_ESTIMATE_X1P2_PLUS_2GIB_RESERVE":
        raise BackendReplayViolation("backend queue capacity policy mismatch")
    if row["outcome_boundary"] != "BACKEND_QUEUE_FROZEN_BEFORE_P07_TRAJECTORY_OUTCOME":
        raise BackendReplayViolation("backend queue outcome boundary mismatch")
    if (
        not row["expected_run_dir"]
        or not row["expected_attempt_dir"]
        or _has_parent_reference(row["expected_run_dir"])
        or _has_parent_reference(row["expected_attempt_dir"])
        or row["expected_run_dir"] == row["expected_attempt_dir"]
    ):
        raise BackendReplayViolation("run and attempt directories must differ")

    bag_fields = (
        "feature_bag",
        "feature_bag_sha256",
        "attestation_path",
        "attestation_sha256",
        "input_audit_path",
        "input_audit_sha256",
    )
    values = [row[field] for field in bag_fields]
    if arm == B0_ARM:
        if any(values):
            raise BackendReplayViolation("B0 must not bind a reused feature bag or audit")
        if (
            row["source_run_id"] != f"B0_NATIVE_DATA:{row['window_id']}"
            or row["source_provenance_kind"] != "B0_NATIVE_DATA_IDENTITY_V1"
        ):
            raise BackendReplayViolation("B0 row lacks exact native-data provenance")
    else:
        if not all(values):
            raise BackendReplayViolation(f"{arm} lacks a complete bag/attestation/audit binding")
        for field in ("feature_bag_sha256", "attestation_sha256", "input_audit_sha256"):
            if not _SHA256_RE.fullmatch(row[field]):
                raise BackendReplayViolation(f"invalid {field}")
    parse_replay_argv(row)


def validate_allocation(row: Mapping[str, str], allocation: Mapping[str, str]) -> None:
    if allocation.get("schema_version") != ALLOCATION_SCHEMA:
        raise BackendReplayViolation("unexpected backend allocation schema")
    exact = (
        "queue_index",
        "run_id",
        "window_id",
        "dataset_family",
        "sequence",
        "arm",
        "replay_index",
        "algorithmic_slot",
        "feature_bag",
        "feature_bag_sha256",
        "attestation_path",
        "attestation_sha256",
        "expected_run_dir",
        "expected_attempt_dir",
        "method_lock_hash",
        "source_run_id",
        "source_provenance_kind",
        "source_provenance_hash",
    )
    differences = {
        key: {"queue": row.get(key), "allocation": allocation.get(key)}
        for key in exact
        if row.get(key) != allocation.get(key)
    }
    if differences:
        raise BackendReplayViolation(f"queue/allocation mismatch: {differences}")
    if allocation.get("status") != "PLANNED":
        raise BackendReplayViolation("backend allocation is not PLANNED")


def _validate_artifact_record(
    root: Path, record: Mapping[str, Any], *, label: str = "locked artifact"
) -> Path:
    path, _content = read_locked_artifact_bytes(root, record, label=label)
    return path


def _validate_artifact_records(root: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(records, list) or not records:
        raise BackendReplayViolation("execution lock has no frozen artifact records")
    seen: set[Path] = set()
    for record in records:
        if not isinstance(record, dict):
            raise BackendReplayViolation("invalid locked artifact record")
        path = _validate_artifact_record(root, record)
        if path in seen:
            raise BackendReplayViolation(f"duplicate locked artifact record: {path}")
        seen.add(path)


def _validate_external_runtime_bindings(payload: Mapping[str, Any]) -> None:
    bindings = payload.get("external_runtime_bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(
        EXTERNAL_RUNTIME_BINDING_PATHS
    ):
        raise BackendReplayViolation("execution lock external runtime binding set differs")
    for role, expected_path in EXTERNAL_RUNTIME_BINDING_PATHS.items():
        expected_path = Path(os.path.abspath(os.fspath(expected_path)))
        try:
            resolved_path = expected_path.resolve(strict=True)
        except OSError as error:
            raise BackendReplayViolation(
                f"cannot resolve external runtime: {role}"
            ) from error
        if resolved_path != expected_path:
            raise BackendReplayViolation(
                f"external runtime path is not canonical: {role}"
            )
        record = bindings.get(role)
        if not isinstance(record, dict) or set(record) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise BackendReplayViolation(f"invalid external runtime record: {role}")
        if record.get("path") != os.fspath(expected_path):
            raise BackendReplayViolation(f"external runtime path differs: {role}")
        expected_hash = str(record.get("sha256", ""))
        size = record.get("size_bytes")
        if (
            not _SHA256_RE.fullmatch(expected_hash)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise BackendReplayViolation(f"invalid external runtime hash/size: {role}")
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(expected_path, flags)
            try:
                info = os.fstat(fd)
                observed = _hash_fd(fd, info.st_size)
                header = os.pread(fd, 20, 0)
            finally:
                os.close(fd)
        except OSError as error:
            raise BackendReplayViolation(f"cannot open external runtime: {role}") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != size
            or observed != expected_hash
        ):
            raise BackendReplayViolation(f"external runtime artifact drift: {role}")
        if (
            len(header) < 18
            or header[:4] != b"\x7fELF"
            or header[4] not in {1, 2}
            or header[5] not in {1, 2}
        ):
            raise BackendReplayViolation(
                f"external runtime ELF semantics differ: {role}"
            )
        byteorder = "little" if header[5] == 1 else "big"
        elf_type = int.from_bytes(header[16:18], byteorder)
        if role in {"python_interpreter", "vins_binary"}:
            if elf_type not in {2, 3} or not info.st_mode & 0o111:
                raise BackendReplayViolation(
                    f"external runtime executable semantics differ: {role}"
                )
        elif elf_type != 3:
            raise BackendReplayViolation(
                f"external runtime shared-library semantics differ: {role}"
            )


def validate_runtime_import_closure(
    root: Path, bindings: Mapping[str, Mapping[str, Any]]
) -> None:
    """Require every resolvable project import to be another exact binding."""

    bound_paths = {str(record.get("path", "")) for record in bindings.values()}
    missing: set[str] = set()
    for role, record in bindings.items():
        relative = str(record.get("path", ""))
        if not relative.startswith("scripts/") or not relative.endswith(".py"):
            continue
        _path, content = read_locked_artifact_bytes(
            root, record, label=f"runtime closure source {role}"
        )
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError as error:
            raise BackendReplayViolation(
                f"runtime closure source is invalid Python: {relative}"
            ) from error
        candidates: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "scripts":
                    candidates.update(
                        f"scripts/{alias.name.replace('.', '/')}.py"
                        for alias in node.names
                    )
                elif node.module.startswith("scripts."):
                    candidates.add(node.module.replace(".", "/") + ".py")
            elif isinstance(node, ast.Import):
                candidates.update(
                    alias.name.replace(".", "/") + ".py"
                    for alias in node.names
                    if alias.name.startswith("scripts.")
                )
        for candidate in candidates:
            if (root / candidate).is_file() and candidate not in bound_paths:
                missing.add(candidate)
    if missing:
        raise BackendReplayViolation(
            f"runtime transitive import closure is incomplete: {sorted(missing)}"
        )


def _validate_prefix_snapshot(
    root: Path, prefix: Mapping[str, Any], *, label: str
) -> Path:
    try:
        raw = str(prefix["path"])
        size = int(prefix["size_bytes"])
        expected_hash = str(prefix["sha256"])
    except (KeyError, TypeError, ValueError) as error:
        raise BackendReplayViolation(f"invalid {label} snapshot") from error
    if size < 0 or not _SHA256_RE.fullmatch(expected_hash):
        raise BackendReplayViolation(f"invalid {label} size or SHA-256")
    path, content, _identity = read_direct_workspace_bytes(root, raw, label=label)
    if len(content) < size or sha256_bytes(content[:size]) != expected_hash:
        raise BackendReplayViolation(f"append-only {label} drift")
    return path


def validate_data_identity_snapshot_shape(
    snapshot: Mapping[str, Any],
    queue_rows: Sequence[Mapping[str, str]] | None = None,
) -> None:
    if (
        snapshot.get("schema_version") != DATA_IDENTITY_SCHEMA
        or snapshot.get("status") != DATA_IDENTITY_STATUS
        or snapshot.get(DATA_IDENTITY_SELF_HASH)
        != canonical_json_hash(snapshot, DATA_IDENTITY_SELF_HASH)
    ):
        raise BackendReplayViolation(
            "data-identity snapshot schema, status, or self-hash mismatch"
        )
    manifests = snapshot.get("manifest_records")
    entries = snapshot.get("entries")
    bindings = snapshot.get("dataset_bindings")
    verification = snapshot.get("verification")
    if (
        not isinstance(manifests, list)
        or len(manifests) != 3
        or not isinstance(entries, list)
        or not entries
        or not isinstance(bindings, list)
        or not bindings
        or not isinstance(verification, dict)
    ):
        raise BackendReplayViolation("data-identity snapshot is incomplete")
    manifest_paths = [
        str(item.get("path", "")) if isinstance(item, dict) else ""
        for item in manifests
    ]
    if sorted(manifest_paths) != sorted(
        [
            "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
            "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
            "papers/ieee_sensors_journal_experiments/reference_audit.csv",
        ]
    ):
        raise BackendReplayViolation("data-identity manifest record set differs")
    for record in manifests:
        if (
            not isinstance(record, dict)
            or not _SHA256_RE.fullmatch(str(record.get("sha256", "")))
            or not isinstance(record.get("size_bytes"), int)
            or int(record["size_bytes"]) < 0
        ):
            raise BackendReplayViolation("invalid data-identity manifest record")
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackendReplayViolation("invalid data-identity entry")
        validate_canonical_input_identity_shape(entry)
        raw_path = str(entry["path"])
        if raw_path in seen_paths:
            raise BackendReplayViolation("duplicate data-identity path")
        seen_paths.add(raw_path)
        if (
            not isinstance(entry.get("kinds"), list)
            or not entry["kinds"]
            or not set(entry["kinds"]).issubset({"raw", "reference", "calibration"})
            or not isinstance(entry.get("datasets"), list)
            or not entry["datasets"]
            or entry.get("sha256_verified_at_freeze") is not True
        ):
            raise BackendReplayViolation("data-identity entry provenance is incomplete")
    binding_keys: set[tuple[str, str]] = set()
    bound_paths: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise BackendReplayViolation("invalid data-identity dataset binding")
        key = (
            str(binding.get("dataset_family", "")),
            str(binding.get("sequence", "")),
        )
        calibrations = binding.get("calibration_paths")
        if (
            not all(key)
            or key in binding_keys
            or not isinstance(binding.get("raw_input_path"), str)
            or not isinstance(binding.get("reference_path"), str)
            or not isinstance(calibrations, list)
        ):
            raise BackendReplayViolation("malformed data-identity dataset binding")
        binding_keys.add(key)
        bound_paths.update(
            [str(binding["raw_input_path"]), str(binding["reference_path"])]
        )
        bound_paths.update(str(item) for item in calibrations)
    if bound_paths != seen_paths:
        raise BackendReplayViolation("data-identity binding/entry path coverage mismatch")
    if queue_rows is not None:
        expected_keys = {
            (row["dataset_family"], row["sequence"]) for row in queue_rows
        }
        if binding_keys != expected_keys:
            raise BackendReplayViolation("data-identity queue dataset coverage mismatch")
    if any(
        verification.get(key) is not True
        for key in (
            "full_sha256_once_at_execution_lock_freeze",
            "stat_identity_before_each_replay",
            "manifest_files_rehashed_before_each_replay",
            "symlink_chain_before_each_replay",
        )
    ) or verification.get("trajectory_values_interpreted") is not False:
        raise BackendReplayViolation("data-identity verification policy drift")


def revalidate_data_identity_snapshot(
    root: Path,
    snapshot: Mapping[str, Any],
    *,
    phase: str,
) -> dict[str, Any]:
    """Revalidate manifests plus path/link/target identity without outcome reads."""

    if not phase or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", phase):
        raise BackendReplayViolation("invalid data-identity revalidation phase")
    validate_data_identity_snapshot_shape(snapshot)
    manifest_results: list[dict[str, Any]] = []
    for record in snapshot["manifest_records"]:
        path = _validate_artifact_record(root, record, label="data-identity manifest")
        manifest_results.append(
            {
                "path": display_path(root, path),
                "sha256": str(record["sha256"]),
                "size_bytes": int(record["size_bytes"]),
            }
        )
    entry_results: list[dict[str, Any]] = []
    for entry in snapshot["entries"]:
        observed = revalidate_canonical_input_identity(
            root, entry, verify_sha256=False
        )
        entry_results.append(
            {
                "path": observed["path"],
                "path_kind": observed["path_kind"],
                "resolved_target_path": observed["resolved_target_path"],
                "resolved_target_identity": observed["resolved_target_identity"],
                "expected_sha256": observed["expected_sha256"],
                "symlink_components": observed["symlink_components"],
                "content_rehashed": False,
            }
        )
    return {
        "schema_version": "isj-p07-backend-data-identity-runtime-check-v1",
        "status": "PASS",
        "phase": phase,
        "data_identity_snapshot_hash": snapshot[DATA_IDENTITY_SELF_HASH],
        "manifest_records": manifest_results,
        "entries": entry_results,
        "trajectory_values_read": False,
        "content_values_interpreted": False,
    }


def validate_b0_play_inputs_shape(
    payload: Mapping[str, Any], queue_rows: Sequence[Mapping[str, str]]
) -> None:
    if (
        payload.get("schema_version") != B0_PLAY_INPUTS_SCHEMA
        or payload.get("status") != B0_PLAY_INPUTS_STATUS
        or payload.get(B0_PLAY_INPUTS_SELF_HASH)
        != canonical_json_hash(payload, B0_PLAY_INPUTS_SELF_HASH)
    ):
        raise BackendReplayViolation(
            "B0 play-input contract schema, status, or self-hash mismatch"
        )
    entries = payload.get("entries")
    bindings = payload.get("queue_bindings")
    policy = payload.get("policy")
    receipt_record = payload.get("materialization_receipt")
    if not isinstance(entries, list) or not isinstance(bindings, list):
        raise BackendReplayViolation("B0 play-input contract is incomplete")
    if (
        not _SHA256_RE.fullmatch(
            str(payload.get("materialization_lock_hash", ""))
        )
        or not _SHA256_RE.fullmatch(
            str(payload.get("materialization_intent_hash", ""))
        )
        or not _SHA256_RE.fullmatch(
            str(payload.get("materialization_receipt_hash", ""))
        )
        or not isinstance(receipt_record, dict)
        or receipt_record.get("path") != B0_MATERIALIZATION_RECEIPT_PATH
        or not _SHA256_RE.fullmatch(str(receipt_record.get("sha256", "")))
        or not isinstance(receipt_record.get("size_bytes"), int)
        or int(receipt_record["size_bytes"]) < 0
        or payload.get("held_out_trajectory_outcome_read") is not False
        or payload.get("outcome_boundary") != B0_OUTCOME_BOUNDARY
    ):
        raise BackendReplayViolation(
            "B0 play-input materialization authority is incomplete"
        )
    if not isinstance(policy, dict) or any(
        policy.get(key) is not True
        for key in (
            "all_b0_queue_rows_bound",
            "full_sha256_before_and_after_each_replay",
            "path_link_target_identity_before_and_after_each_replay",
            "preparation_must_not_create_or_replace_play_input",
            "derived_inputs_materialized_before_execution_lock",
        )
    ) or policy.get("trajectory_values_interpreted") is not False:
        raise BackendReplayViolation("B0 play-input policy drift")
    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackendReplayViolation("invalid B0 play-input entry")
        play_input_id = entry.get("play_input_id")
        identity = entry.get("path_identity")
        derivation = entry.get("derivation")
        evaluation_window = entry.get("evaluation_window")
        if (
            not isinstance(play_input_id, str)
            or not _SHA256_RE.fullmatch(play_input_id)
            or play_input_id in by_id
            or not isinstance(identity, dict)
            or not isinstance(derivation, dict)
            or not isinstance(evaluation_window, dict)
            or not _SHA256_RE.fullmatch(
                str(entry.get("source_provenance_hash", ""))
            )
        ):
            raise BackendReplayViolation("malformed B0 play-input entry")
        validate_canonical_input_identity_shape(identity)
        if identity.get("expected_sha256") != entry.get("expected_sha256"):
            raise BackendReplayViolation("B0 play-input identity/SHA binding mismatch")
        if (
            derivation.get("kind")
            not in {"DIRECT_RAW_WINDOW_PLAYBACK", "PREMATERIALIZED_WINDOW_BAG"}
            or not isinstance(derivation.get("source_raw_path"), str)
            or not _SHA256_RE.fullmatch(
                str(derivation.get("source_raw_sha256", ""))
            )
            or not _SHA256_RE.fullmatch(str(derivation.get("derivation_hash", "")))
        ):
            raise BackendReplayViolation("B0 play-input derivation is incomplete")
        try:
            window_start_raw = evaluation_window["start_ros_time_ns"]
            window_end_raw = evaluation_window["end_ros_time_ns"]
        except KeyError as error:
            raise BackendReplayViolation("B0 absolute evaluation window is invalid") from error
        window_start_ns, window_end_ns = validate_absolute_ros_epoch_window(
            window_start_raw,
            window_end_raw,
            label="B0 evaluation window",
        )
        evidence = evaluation_window.get("derivation_evidence")
        if (
            not isinstance(evaluation_window.get("camera_topic"), str)
            or not str(evaluation_window["camera_topic"]).startswith("/")
            or evaluation_window.get("stamp_source")
            != "sensor_msgs/Image.header.stamp"
            or evaluation_window.get("boundary_rule")
            != "FIRST_INCLUDED_CAMERA_STAMP_TO_LAST_INCLUDED_CAMERA_STAMP_INCLUSIVE"
            or not isinstance(evidence, dict)
            or not _SHA256_RE.fullmatch(str(evidence.get("sha256", "")))
            or not isinstance(evidence.get("path"), str)
            or not isinstance(evidence.get("size_bytes"), int)
        ):
            raise BackendReplayViolation(
                "B0 play-input absolute evaluation-window provenance is incomplete"
            )
        by_id[play_input_id] = entry
    expected_rows = {
        (int(row["queue_index"]), row["run_id"]): row
        for row in queue_rows
        if row.get("arm") == B0_ARM
    }
    observed_rows: dict[tuple[int, str], Mapping[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, dict):
            raise BackendReplayViolation("invalid B0 queue binding")
        try:
            key = (int(binding["queue_index"]), str(binding["run_id"]))
        except (KeyError, TypeError, ValueError) as error:
            raise BackendReplayViolation("malformed B0 queue binding") from error
        if key in observed_rows or binding.get("play_input_id") not in by_id:
            raise BackendReplayViolation("duplicate or dangling B0 queue binding")
        if (
            binding.get("source_run_id")
            != f"B0_NATIVE_DATA:{binding.get('window_id')}"
            or binding.get("source_provenance_kind")
            != "B0_NATIVE_DATA_IDENTITY_V1"
            or not _SHA256_RE.fullmatch(
                str(binding.get("source_provenance_hash", ""))
            )
        ):
            raise BackendReplayViolation("B0 queue binding lacks native-data provenance")
        observed_rows[key] = binding
    if set(observed_rows) != set(expected_rows):
        raise BackendReplayViolation("B0 play-input queue coverage mismatch")
    for key, row in expected_rows.items():
        binding = observed_rows[key]
        entry = by_id[str(binding["play_input_id"])]
        exact = {
            "window_id": row["window_id"],
            "dataset_family": row["dataset_family"],
            "sequence": row["sequence"],
            "runner_start": row["runner_start"],
            "runner_end_or_duration": row["runner_end_or_duration"],
            "runner_unit": row["runner_unit"],
        }
        if any(binding.get(field) != value for field, value in exact.items()) or any(
            entry.get(field) != value for field, value in exact.items()
        ):
            raise BackendReplayViolation("B0 play-input queue/window binding drift")
        if (
            row.get("source_run_id") != binding.get("source_run_id")
            or row.get("source_provenance_kind")
            != binding.get("source_provenance_kind")
            or row.get("source_provenance_hash")
            != binding.get("source_provenance_hash")
            or entry.get("source_provenance_hash")
            != binding.get("source_provenance_hash")
        ):
            raise BackendReplayViolation("B0 queue/native-data provenance hash drift")


def frozen_b0_play_input_for_row(
    execution_lock: Mapping[str, Any], row: Mapping[str, str]
) -> Mapping[str, Any]:
    if row.get("arm") != B0_ARM:
        raise BackendReplayViolation("only B0 may select a frozen B0 play input")
    payload = execution_lock.get("b0_play_inputs")
    if not isinstance(payload, dict):
        raise BackendReplayViolation("execution lock lacks B0 play-input contract")
    bindings = [
        item
        for item in payload.get("queue_bindings", [])
        if isinstance(item, dict)
        and item.get("queue_index") == int(row["queue_index"])
    ]
    if len(bindings) != 1:
        raise BackendReplayViolation("B0 row lacks one frozen play-input binding")
    entries = [
        item
        for item in payload.get("entries", [])
        if isinstance(item, dict)
        and item.get("play_input_id") == bindings[0].get("play_input_id")
    ]
    if len(entries) != 1:
        raise BackendReplayViolation("B0 play-input binding is dangling or ambiguous")
    exact = {
        "window_id": row["window_id"],
        "dataset_family": row["dataset_family"],
        "sequence": row["sequence"],
        "runner_start": row["runner_start"],
        "runner_end_or_duration": row["runner_end_or_duration"],
        "runner_unit": row["runner_unit"],
    }
    if any(bindings[0].get(key) != value for key, value in exact.items()) or any(
        entries[0].get(key) != value for key, value in exact.items()
    ):
        raise BackendReplayViolation("B0 effective row differs from frozen play input")
    return entries[0]


def revalidate_b0_play_input(
    root: Path,
    execution_lock: Mapping[str, Any],
    row: Mapping[str, str],
    *,
    phase: str,
    verify_sha256: bool = True,
) -> dict[str, Any]:
    entry = frozen_b0_play_input_for_row(execution_lock, row)
    identity = entry.get("path_identity")
    if not isinstance(identity, dict):
        raise BackendReplayViolation("B0 play-input path identity is absent")
    observed = revalidate_canonical_input_identity(
        root, identity, verify_sha256=verify_sha256
    )
    evaluation_window = entry.get("evaluation_window")
    if not isinstance(evaluation_window, dict) or not isinstance(
        evaluation_window.get("derivation_evidence"), dict
    ):
        raise BackendReplayViolation("B0 evaluation-window evidence is absent")
    evidence_path = _validate_artifact_record(
        root,
        evaluation_window["derivation_evidence"],
        label="B0 absolute-window derivation evidence",
    )
    return {
        "schema_version": "isj-p07-backend-b0-play-input-runtime-check-v1",
        "status": "PASS",
        "phase": phase,
        "queue_index": int(row["queue_index"]),
        "run_id": row["run_id"],
        "play_input_id": entry["play_input_id"],
        "path_identity": observed,
        "derivation_hash": entry["derivation"]["derivation_hash"],
        "source_provenance_hash": entry["source_provenance_hash"],
        "evaluation_window": {
            **dict(evaluation_window),
            "derivation_evidence": {
                **dict(evaluation_window["derivation_evidence"]),
                "path": display_path(root, evidence_path),
            },
        },
        "trajectory_values_read": False,
        "content_values_interpreted": False,
        "content_sha256_reverified": verify_sha256,
    }


def validate_queue_lock(root: Path, path: Path) -> dict[str, Any]:
    _direct_path, content, _identity = read_direct_workspace_bytes(
        root, display_path(root, path), label="backend queue lock"
    )
    payload = parse_canonical_json_object(content, label="backend queue lock")
    if (
        payload.get("schema_version") != QUEUE_LOCK_SCHEMA
        or payload.get("status") != QUEUE_LOCK_STATUS
        or payload.get("backend_queue_lock_hash")
        != canonical_json_hash(payload, "backend_queue_lock_hash")
    ):
        raise BackendReplayViolation("backend queue lock schema, status, or hash mismatch")
    _validate_artifact_records(root, payload.get("artifacts", []))

    prefix = payload.get("mutable_registry_prefix")
    if not isinstance(prefix, dict):
        raise BackendReplayViolation("queue lock lacks registry prefix snapshot")
    _validate_prefix_snapshot(root, prefix, label="registry prefix")
    return payload


def _validate_queue_source_evidence(
    queue_lock: Mapping[str, Any], queue_rows: Sequence[Mapping[str, str]]
) -> None:
    raw_evidence = queue_lock.get("source_evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise BackendReplayViolation("backend queue lock lacks source evidence")
    by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in raw_evidence:
        if not isinstance(item, dict):
            raise BackendReplayViolation("invalid queue-lock source evidence")
        key = (str(item.get("window_id", "")), str(item.get("arm", "")))
        provenance = item.get("source_provenance")
        if (
            not all(key)
            or key in by_key
            or not isinstance(provenance, dict)
            or item.get("source_provenance_hash")
            != sha256_bytes(
                json.dumps(
                    provenance,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
        ):
            raise BackendReplayViolation("queue-lock source provenance hash drift")
        by_key[key] = item
    expected_keys = {(row["window_id"], row["arm"]) for row in queue_rows}
    if set(by_key) != expected_keys:
        raise BackendReplayViolation("queue-lock source-evidence coverage mismatch")
    for row in queue_rows:
        item = by_key[(row["window_id"], row["arm"])]
        for field in (
            "source_run_id",
            "source_provenance_kind",
            "source_provenance_hash",
            "feature_bag",
            "feature_bag_sha256",
            "attestation_path",
            "attestation_sha256",
            "input_audit_path",
            "input_audit_sha256",
        ):
            if str(item.get(field, "")) != row[field]:
                raise BackendReplayViolation(
                    f"queue-lock source evidence differs from queue field {field}"
                )


def validate_execution_lock(
    root: Path,
    path: Path,
    *,
    queue_path: Path,
    allocation_path: Path,
) -> dict[str, Any]:
    control_contents: dict[str, bytes] = {}
    for control_path, label in (
        (path, "execution lock"),
        (queue_path, "backend queue"),
        (allocation_path, "backend allocation"),
    ):
        _direct, content, _identity = read_direct_workspace_bytes(
            root, display_path(root, control_path), label=label
        )
        control_contents[label] = content
    payload = parse_canonical_json_object(
        control_contents["execution lock"], label="backend execution lock"
    )
    if (
        set(payload) != EXECUTION_LOCK_KEYS
        or payload.get("schema_version") != EXECUTION_LOCK_SCHEMA
        or payload.get("status") != EXECUTION_LOCK_STATUS
        or payload.get("execution_lock_hash")
        != canonical_json_hash(payload, "execution_lock_hash")
        or payload.get("trajectory_outcome_read_at_freeze") is not False
        or payload.get("outcome_boundary") != EXECUTION_OUTCOME_BOUNDARY
    ):
        raise BackendReplayViolation(
            "backend execution lock keys/schema/status/hash/outcome boundary mismatch"
        )
    _validate_artifact_records(root, payload.get("artifacts", []))

    bindings = payload.get("queue_bindings", payload)
    expected_queue_hash = bindings.get("backend_replay_queue_sha256") or bindings.get(
        "queue_sha256"
    )
    expected_allocation_hash = bindings.get("backend_run_allocation_sha256") or bindings.get(
        "allocation_sha256"
    )
    if expected_queue_hash != sha256_bytes(control_contents["backend queue"]):
        raise BackendReplayViolation("execution lock queue hash mismatch")
    if expected_allocation_hash != sha256_bytes(
        control_contents["backend allocation"]
    ):
        raise BackendReplayViolation("execution lock allocation hash mismatch")

    queue_fields, queue_rows = parse_csv_bytes(
        control_contents["backend queue"], label="backend queue"
    )
    _allocation_fields, allocation_rows = parse_csv_bytes(
        control_contents["backend allocation"], label="backend allocation"
    )
    if REQUIRED_QUEUE_FIELDS.difference(queue_fields):
        raise BackendReplayViolation("execution lock queue has an incomplete header")
    queue_by_index: dict[str, dict[str, str]] = {}
    for row in queue_rows:
        validate_queue_row(row)
        if row["queue_index"] in queue_by_index:
            raise BackendReplayViolation("execution lock queue indices are not unique")
        queue_by_index[row["queue_index"]] = row
    allocation_by_index: dict[str, dict[str, str]] = {}
    for allocation in allocation_rows:
        index = allocation.get("queue_index", "")
        if not index or index in allocation_by_index:
            raise BackendReplayViolation("execution lock allocation indices are invalid")
        allocation_by_index[index] = allocation
    if set(allocation_by_index) != set(queue_by_index):
        raise BackendReplayViolation("execution lock queue/allocation index sets differ")
    for index, row in queue_by_index.items():
        validate_allocation(row, allocation_by_index[index])

    artifact_records = payload.get("artifacts")
    if not isinstance(artifact_records, list):
        raise BackendReplayViolation("execution lock lacks artifact records")
    artifacts_by_path = {
        str(record.get("path")): record
        for record in artifact_records
        if isinstance(record, dict)
    }
    if len(artifacts_by_path) != len(artifact_records):
        raise BackendReplayViolation(
            "execution lock artifact paths are duplicate or malformed"
        )
    formalization_adoption = payload.get("formalization_adoption")
    try:
        from scripts import build_p07_backend_formalization_adoption_v1 as adoption_validator
        from scripts import build_p07_backend_b0_formalization_adoption_bridge_v1 as b0_bridge_validator
        from scripts import build_p07_backend_formalization_review_evidence_v1 as review_evidence_validator
    except ModuleNotFoundError:
        import build_p07_backend_formalization_adoption_v1 as adoption_validator  # type: ignore
        import build_p07_backend_b0_formalization_adoption_bridge_v1 as b0_bridge_validator  # type: ignore
        import build_p07_backend_formalization_review_evidence_v1 as review_evidence_validator  # type: ignore
    try:
        adoption_validator.validate_adoption_authority_binding(
            formalization_adoption, root=root
        )
    except adoption_validator.AdoptionError as error:
        raise BackendReplayViolation(
            "execution lock formalization-adoption authority drift"
        ) from error
    formalization_review_evidence = payload.get("formalization_review_evidence")
    try:
        review_evidence_validator.validate_review_evidence_authority_binding(
            formalization_review_evidence, root=root
        )
    except review_evidence_validator.ReviewEvidenceError as error:
        raise BackendReplayViolation(
            "execution lock formalization-review-evidence authority drift"
        ) from error
    b0_adoption = payload.get("b0_formalization_adoption")
    if not isinstance(b0_adoption, dict) or set(b0_adoption) != {
        "pre_materialization_lock",
        "materialization_action_intent",
        "post_materialization_closeout",
    }:
        raise BackendReplayViolation("execution lock lacks the two-stage B0 adoption bridge")

    def locked_json(relative: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
        record = artifacts_by_path.get(relative)
        if not isinstance(record, dict):
            raise BackendReplayViolation(f"execution lock lacks {label} artifact")
        _path, content = read_locked_artifact_bytes(root, record, label=label)
        value = parse_canonical_json_object(content, label=label)
        return value, record

    b0_prelock, b0_prelock_record = locked_json(
        B0_ADOPTION_PRELOCK_PATH, "B0 adoption prelock"
    )
    b0_action, b0_action_record = locked_json(
        B0_ADOPTION_ACTION_INTENT_PATH, "B0 adoption action intent"
    )
    b0_closeout, b0_closeout_record = locked_json(
        B0_ADOPTION_CLOSEOUT_PATH, "B0 adoption closeout"
    )
    try:
        b0_bridge_validator.validate_prelock_payload(
            b0_prelock, root=root, verify_files=False
        )
        b0_bridge_validator.validate_action_intent_payload(
            b0_action, root=root, verify_files=False
        )
        b0_bridge_validator.validate_closeout_payload(
            b0_closeout, root=root, verify_files=False
        )
    except b0_bridge_validator.B0AdoptionBridgeError as error:
        raise BackendReplayViolation(f"B0 adoption bridge drift: {error}") from error
    expected_prelock_binding = {
        **b0_prelock_record,
        b0_bridge_validator.PRELOCK_HASH: b0_prelock[
            b0_bridge_validator.PRELOCK_HASH
        ],
    }
    expected_closeout_binding = {
        **b0_closeout_record,
        b0_bridge_validator.CLOSEOUT_HASH: b0_closeout[
            b0_bridge_validator.CLOSEOUT_HASH
        ],
    }
    expected_action_binding = {
        **b0_action_record,
        b0_bridge_validator.ACTION_INTENT_HASH: b0_action[
            b0_bridge_validator.ACTION_INTENT_HASH
        ],
    }
    if (
        b0_adoption.get("pre_materialization_lock") != expected_prelock_binding
        or b0_adoption.get("materialization_action_intent")
        != expected_action_binding
        or b0_adoption.get("post_materialization_closeout")
        != expected_closeout_binding
        or b0_prelock.get("formalization_adoption") != formalization_adoption
        or b0_closeout.get("formalization_adoption") != formalization_adoption
        or b0_prelock.get("formalization_review_evidence")
        != formalization_review_evidence
        or b0_closeout.get("formalization_review_evidence")
        != formalization_review_evidence
        or b0_action.get("formalization_adoption") != formalization_adoption
        or b0_action.get("formalization_review_evidence")
        != formalization_review_evidence
        or b0_action.get("pre_materialization_lock")
        != expected_prelock_binding
        or b0_closeout.get("pre_materialization_lock")
        != expected_prelock_binding
        or b0_closeout.get("materialization_action_intent")
        != expected_action_binding
    ):
        raise BackendReplayViolation(
            "execution lock B0 bridge/adoption transitive binding drift"
        )
    runtime_bindings = payload.get("runtime_implementation_bindings")
    if not isinstance(runtime_bindings, dict) or set(runtime_bindings) != set(
        RUNTIME_IMPLEMENTATION_BINDING_PATHS
    ):
        raise BackendReplayViolation(
            "execution lock runtime implementation role set differs"
        )
    for role, expected_path in RUNTIME_IMPLEMENTATION_BINDING_PATHS.items():
        record = runtime_bindings.get(role)
        artifact_record = artifacts_by_path.get(expected_path)
        if (
            not isinstance(record, dict)
            or not isinstance(artifact_record, dict)
            or record != artifact_record
            or record.get("path") != expected_path
        ):
            raise BackendReplayViolation(
                f"execution lock runtime implementation binding differs: {role}"
            )
        _validate_artifact_record(
            root, record, label=f"runtime implementation {role}"
        )
    validate_runtime_import_closure(root, runtime_bindings)
    _validate_external_runtime_bindings(payload)
    for dedicated, role in (
        (payload.get("allowed_entrypoint"), "job_entrypoint"),
        (payload.get("executor"), "job_entrypoint"),
        (payload.get("adapter"), "adapter"),
        (payload.get("auditor"), "auditor"),
    ):
        if dedicated != runtime_bindings[role]:
            raise BackendReplayViolation(
                f"execution lock dedicated {role} record differs from runtime binding"
            )
    queue_lock_records = [
        record
        for record in artifact_records
        if isinstance(record, dict)
        and record.get("path")
        == "papers/ieee_sensors_journal_experiments/p07/backend_queue_lock_v1.json"
    ]
    if len(queue_lock_records) != 1:
        raise BackendReplayViolation("execution lock lacks one backend queue-lock record")
    queue_lock_path = _validate_artifact_record(
        root, queue_lock_records[0], label="backend queue lock"
    )
    queue_lock = validate_queue_lock(root, queue_lock_path)
    _validate_queue_source_evidence(queue_lock, queue_rows)
    if payload.get("backend_queue_lock_hash") != queue_lock.get(
        "backend_queue_lock_hash"
    ):
        raise BackendReplayViolation("execution/queue-lock self-hash binding drift")

    snapshot = payload.get("data_identity_snapshot")
    if not isinstance(snapshot, dict):
        raise BackendReplayViolation("execution lock lacks data-identity snapshot")
    validate_data_identity_snapshot_shape(snapshot, queue_rows)
    b0_play_inputs = payload.get("b0_play_inputs")
    if not isinstance(b0_play_inputs, dict):
        raise BackendReplayViolation("execution lock lacks frozen B0 play inputs")
    validate_b0_play_inputs_shape(b0_play_inputs, queue_rows)
    g0_authority = payload.get(g0_governance.EXECUTION_LOCK_BINDING_KEY)
    if not isinstance(g0_authority, dict):
        raise BackendReplayViolation("execution lock lacks pre-replay G0 authority")
    try:
        g0_authority_hash = g0_governance.validate_execution_authority_binding(
            g0_authority, root=root
        )
    except g0_governance.G0GovernanceError as error:
        raise BackendReplayViolation(
            f"execution lock G0 authority is invalid: {error}"
        ) from error
    if g0_authority.get("g0_execution_authority_hash") != g0_authority_hash:
        raise BackendReplayViolation("execution lock G0 authority self-hash drift")

    expected_order = [
        {
            "queue_index": int(row["queue_index"]),
            "run_id": row["run_id"],
            "window_id": row["window_id"],
            "arm": row["arm"],
            "replay_index": int(row["replay_index"]),
            "algorithmic_slot": row["algorithmic_slot"],
            "feature_bag_sha256": row["feature_bag_sha256"],
            "attestation_sha256": row["attestation_sha256"],
            "input_audit_sha256": row["input_audit_sha256"],
            "source_run_id": row["source_run_id"],
            "source_provenance_kind": row["source_provenance_kind"],
            "source_provenance_hash": row["source_provenance_hash"],
            "expected_run_dir": row["expected_run_dir"],
            "expected_attempt_dir": row["expected_attempt_dir"],
        }
        for row in queue_rows
    ]
    if payload.get("queue_items") != len(queue_rows):
        raise BackendReplayViolation("execution lock queue item count mismatch")
    if payload.get("execution_order") != expected_order:
        raise BackendReplayViolation("execution lock order/item bindings differ from queue")

    prefix = payload.get("mutable_registry_prefix")
    if not isinstance(prefix, dict):
        raise BackendReplayViolation("execution lock lacks registry prefix snapshot")
    _validate_prefix_snapshot(root, prefix, label="registry prefix")

    capacity = payload.get("capacity_gate")
    if not isinstance(capacity, dict) or set(capacity) != CAPACITY_GATE_KEYS:
        raise BackendReplayViolation("execution lock capacity gate key set differs")
    integer_capacity_fields = (
        "margin_numerator",
        "margin_denominator",
        "reserve_bytes",
        "minimum_governance_free_bytes",
        "estimated_total_output_bytes",
        "required_output_free_bytes",
        "observed_output_free_bytes_at_freeze",
        "observed_governance_free_bytes_at_freeze",
    )
    if any(type(capacity.get(field)) is not int for field in integer_capacity_fields):
        raise BackendReplayViolation("execution lock capacity values must be exact integers")
    estimated_total = sum(int(row["estimated_output_bytes"]) for row in queue_rows)
    required_output = (estimated_total * 6 + 4) // 5 + 2 * 1024**3
    if (
        capacity["policy"] != "REMAINING_ESTIMATE_X1P2_PLUS_2GIB_RESERVE"
        or capacity["margin_numerator"] != 6
        or capacity["margin_denominator"] != 5
        or capacity["reserve_bytes"] != 2 * 1024**3
        or capacity["minimum_governance_free_bytes"] != 512 * 1024**2
        or capacity["estimated_total_output_bytes"] != estimated_total
        or capacity["required_output_free_bytes"] != required_output
        or capacity["observed_output_free_bytes_at_freeze"] < required_output
        or capacity["observed_governance_free_bytes_at_freeze"] < 512 * 1024**2
        or capacity["output_filesystem_path"] != "logs"
        or capacity["governance_filesystem_path"]
        != "papers/ieee_sensors_journal_experiments/p07"
        or capacity["recompute_before_each_job"] is not True
        or capacity["insufficient_action"] != "WAITING"
    ):
        raise BackendReplayViolation("capacity gate differs from the frozen fail-closed policy")

    flock_path = Path(str(payload.get("global_flock_path", DEFAULT_GLOBAL_FLOCK)))
    if flock_path != DEFAULT_GLOBAL_FLOCK:
        raise BackendReplayViolation("unexpected global backend replay flock path")
    policy = payload.get("adapter_policy")
    if not isinstance(policy, dict) or any(
        policy.get(key) is not True
        for key in (
            "job_is_only_entrypoint",
            "adapter_direct_cli_forbidden",
            "b0_external_feature_bag_forbidden",
            "feature_arms_require_readonly_fd_override",
            "feature_arms_require_sealed_memfd_copy",
            "controller_job_and_transitive_modules_require_sealed_memfd",
            "unknown_scripts_import_workspace_fallback_forbidden",
            "b0_play_input_requires_sealed_memfd_copy",
            "attestation_and_input_audit_require_sealed_memfd_copy",
            "vins_and_camera_configs_require_sealed_memfd_consumption",
            "vins_binary_and_project_libraries_require_sealed_memfd",
            "vins_pid_exe_and_maps_identity_check_required",
            "aqualoc_afrl_dynamic_cache_conversion_forbidden",
            "formal_setup_path_source_forbidden",
            "minimal_ros_environment_is_job_constructed",
            "ros_cli_absolute_paths_required",
            "preparation_runners_run_vins_zero_only",
            "replay_only_runner_is_only_ros_replay_path",
            "evaluation_during_replay_forbidden",
            "ape_rpe_during_replay_forbidden",
            "data_identity_check_before_launch_required",
            "shell_export_wrapper_forbidden",
            "frontend_export_wrapper_forbidden",
            "input_sha256_before_and_after_required",
            "attestation_sha256_before_and_after_required",
            "delete_or_replace_input_forbidden",
            "target_no_clobber",
        )
    ):
        raise BackendReplayViolation("execution lock adapter safety policy is incomplete")
    if policy.get("allowed_vins_workspace") != os.fspath(VINS_ORIGIN):
        raise BackendReplayViolation("execution lock permits a non-origin VINS workspace")
    if policy.get("forbidden_workspace") != os.fspath(FORBIDDEN_VINS_WORKSPACE):
        raise BackendReplayViolation("execution lock forbidden-workspace binding drift")
    if (
        policy.get("replay_only_runner")
        != "scripts/run_p07_backend_replay_only_v1.sh"
        or policy.get("replay_only_config_helper")
        != "scripts/prepare_p07_backend_replay_config_v1.py"
    ):
        raise BackendReplayViolation("execution lock replay-only path drift")
    entrypoint = payload.get("allowed_entrypoint")
    if not isinstance(entrypoint, dict) or Path(str(entrypoint.get("path", ""))).name != (
        "run_p07_backend_replay_job_v1.py"
    ):
        raise BackendReplayViolation("execution lock does not make the job the sole entrypoint")
    entrypoint_path = _validate_artifact_record(
        root, entrypoint, label="allowed entrypoint"
    )
    if entrypoint_path != lexical_absolute(
        root / "scripts/run_p07_backend_replay_job_v1.py"
    ):
        raise BackendReplayViolation("execution lock allowed entrypoint path mismatch")
    required_environment = policy.get("required_environment")
    expected_environment = {
        "preparation": {
            "RUN_VINS": "0",
            "FORCE_EXPORT": "0",
            "EXPORT_FEATURES": "0",
            "RUN_EVALUATION": "0",
        },
        "replay_only": {"VINS_MULTIPLE_THREAD": "0"},
        "formal_ros": dict(FROZEN_ROS_ENVIRONMENT),
        "ros_executables": dict(FROZEN_ROS_EXECUTABLES),
    }
    if required_environment != expected_environment:
        raise BackendReplayViolation("execution lock required environment is incomplete")
    data_identity = payload.get("data_identity_policy")
    if (
        not isinstance(data_identity, dict)
        or data_identity.get("data_eligibility_manifest")
        != "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv"
        or data_identity.get("dataset_checksum_manifest")
        != "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt"
        or data_identity.get("reference_audit")
        != "papers/ieee_sensors_journal_experiments/reference_audit.csv"
        or any(
            data_identity.get(key) is not True
            for key in (
                "unique_family_sequence_row_required",
                "raw_input_identity_and_checksum_required",
                "reference_identity_and_checksum_required",
                "calibration_identity_and_checksum_required",
                "check_before_each_replay",
            )
        )
        or data_identity.get("trajectory_values_read_by_identity_check") is not False
    ):
        raise BackendReplayViolation("execution lock data-identity policy is incomplete")
    replacement = payload.get("infrastructure_replacement")
    if (
        not isinstance(replacement, dict)
        or replacement.get("schema_version")
        != "isj-p07-backend-replacement-contract-v1"
        or replacement.get("status")
        != "FROZEN_READY_FOR_INFRASTRUCTURE_REPLACEMENT_ALLOCATION"
        or replacement.get("replacement_lock_schema")
        != "isj-p07-backend-infrastructure-replacement-lock-v1"
        or replacement.get("replacement_lock_status")
        != "FROZEN_PLANNED_INFRASTRUCTURE_REPLACEMENT"
        or replacement.get("replacement_lock_directory")
        != "papers/ieee_sensors_journal_experiments/p07/backend_replacements"
        or replacement.get("allocation_index_schema")
        != "isj-p07-backend-replacement-allocation-v1"
        or replacement.get("allocation_index_path")
        != (
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_replacement_allocation_v1.csv"
        )
        or replacement.get("allowed_effective_row_overrides")
        != ["run_id", "runner_tag", "expected_run_dir", "expected_attempt_dir"]
        or replacement.get("replacement_job_flag") != "--replacement-lock"
        or any(
            replacement.get(key) is not True
            for key in (
                "new_unique_planned_e00_required",
                "replacement_for_immediately_failed_run_id",
                "algorithmic_slot_preserved",
            )
        )
        or not _SHA256_RE.fullmatch(
            str(replacement.get("replacement_contract_hash", ""))
        )
    ):
        raise BackendReplayViolation(
            "execution lock infrastructure-replacement policy is incomplete"
        )
    replacement_record = replacement.get("contract")
    if not isinstance(replacement_record, dict):
        raise BackendReplayViolation("execution lock lacks replacement-contract record")
    replacement_path = _validate_artifact_record(
        root, replacement_record, label="replacement contract"
    )
    if replacement_path != lexical_absolute(
        root
        / "papers/ieee_sensors_journal_experiments/p07/"
        "backend_replacement_contract_v1.json"
    ):
        raise BackendReplayViolation("execution lock replacement-contract path mismatch")
    _replacement_path, replacement_content = read_locked_artifact_bytes(
        root, replacement_record, label="replacement contract"
    )
    replacement_payload = parse_canonical_json_object(
        replacement_content, label="replacement contract"
    )
    if (
        not isinstance(replacement_payload, dict)
        or replacement_payload.get("schema_version")
        != "isj-p07-backend-replacement-contract-v1"
        or replacement_payload.get("status")
        != "FROZEN_READY_FOR_INFRASTRUCTURE_REPLACEMENT_ALLOCATION"
        or replacement_payload.get("replacement_contract_hash")
        != canonical_json_hash(replacement_payload, "replacement_contract_hash")
        or replacement_payload.get("formalization_adoption")
        != formalization_adoption
        or replacement_payload.get("formalization_review_evidence")
        != formalization_review_evidence
        or replacement.get("formalization_review_evidence")
        != formalization_review_evidence
        or replacement.get("replacement_contract_hash")
        != replacement_payload.get("replacement_contract_hash")
    ):
        raise BackendReplayViolation(
            "execution lock replacement/adoption authority chain drift"
        )
    critical_artifacts = {
        "scripts/run_p07_backend_replay_only_v1.sh",
        "scripts/prepare_p07_backend_replay_config_v1.py",
        "papers/ieee_sensors_journal_experiments/data_eligibility_manifest.csv",
        "papers/ieee_sensors_journal_experiments/dataset_checksum_manifest.txt",
        "papers/ieee_sensors_journal_experiments/reference_audit.csv",
        (
            "papers/ieee_sensors_journal_experiments/p07/"
            "backend_replacement_contract_v1.json"
        ),
        "scripts/build_p07_backend_replacement_contract_v1.py",
        "scripts/allocate_p07_backend_replacement_v1.py",
        FORMALIZATION_ADOPTION_PATH,
        FORMALIZATION_REVIEW_EVIDENCE_PATH,
        B0_ADOPTION_PRELOCK_PATH,
        B0_ADOPTION_ACTION_INTENT_PATH,
        B0_ADOPTION_CLOSEOUT_PATH,
        *RUNTIME_IMPLEMENTATION_BINDING_PATHS.values(),
    }
    if critical_artifacts.difference(artifacts_by_path):
        raise BackendReplayViolation("execution lock omits critical replay artifacts")
    g0_lock_record = g0_authority.get("evaluation_lock")
    if not isinstance(g0_lock_record, dict):
        raise BackendReplayViolation("G0 authority lacks evaluation-lock record")
    locked_g0_artifact = artifacts_by_path.get(str(g0_lock_record.get("path")))
    if not isinstance(locked_g0_artifact, dict) or any(
        locked_g0_artifact.get(key) != g0_lock_record.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise BackendReplayViolation(
            "execution artifacts do not bind the G0 evaluation lock"
        )
    b0_artifact_paths = (
        B0_MATERIALIZATION_LOCK_PATH,
        B0_MATERIALIZATION_INTENT_PATH,
        B0_MATERIALIZATION_RECEIPT_PATH,
        B0_PLAY_INPUTS_PATH,
    )
    if any(path not in artifacts_by_path for path in b0_artifact_paths):
        raise BackendReplayViolation(
            "execution lock omits B0 plan/intent/receipt/final artifacts"
        )

    def b0_json(relative: str, label: str) -> dict[str, Any]:
        record = artifacts_by_path[relative]
        _path, content = read_locked_artifact_bytes(root, record, label=label)
        return parse_canonical_json_object(content, label=label)

    b0_plan = b0_json(B0_MATERIALIZATION_LOCK_PATH, "B0 materialization lock")
    b0_intent = b0_json(B0_MATERIALIZATION_INTENT_PATH, "B0 materialization intent")
    b0_receipt = b0_json(
        B0_MATERIALIZATION_RECEIPT_PATH, "B0 materialization receipt"
    )
    b0_final = b0_json(B0_PLAY_INPUTS_PATH, "B0 play-input final")
    plan_hash = b0_plan.get("materialization_lock_hash")
    intent_hash = b0_intent.get("materialization_intent_hash")
    receipt_hash = b0_receipt.get("materialization_receipt_hash")
    if (
        b0_plan.get("schema_version")
        != "isj-p07-backend-b0-materialization-lock-v1"
        or b0_plan.get("status")
        != "FROZEN_READY_FOR_EXPLICIT_B0_MATERIALIZATION"
        or plan_hash != canonical_json_hash(b0_plan, "materialization_lock_hash")
        or b0_intent.get("schema_version")
        != "isj-p07-backend-b0-materialization-intent-v1"
        or b0_intent.get("status") != "FROZEN_BEFORE_FIRST_B0_TARGET_MUTATION"
        or intent_hash
        != canonical_json_hash(b0_intent, "materialization_intent_hash")
        or b0_intent.get("materialization_lock_hash") != plan_hash
        or b0_receipt.get("schema_version")
        != "isj-p07-backend-b0-materialization-receipt-v1"
        or b0_receipt.get("status")
        != "PASS_ALL_B0_INPUTS_EXACT_AND_OUTCOME_BLIND"
        or receipt_hash
        != canonical_json_hash(b0_receipt, "materialization_receipt_hash")
        or b0_receipt.get("materialization_lock_hash") != plan_hash
        or b0_receipt.get("materialization_intent_hash") != intent_hash
        or b0_final != b0_play_inputs
        or b0_play_inputs.get("materialization_lock_hash") != plan_hash
        or b0_play_inputs.get("materialization_intent_hash") != intent_hash
        or b0_play_inputs.get("materialization_receipt_hash") != receipt_hash
    ):
        raise BackendReplayViolation(
            "B0 plan/intent/receipt/final authority chain drift"
        )
    bridge_expected_refs = {
        "b0_materialization_plan": {
            **artifacts_by_path[B0_MATERIALIZATION_LOCK_PATH],
            "materialization_lock_hash": plan_hash,
        },
        "b0_materialization_intent": {
            **artifacts_by_path[B0_MATERIALIZATION_INTENT_PATH],
            "materialization_intent_hash": intent_hash,
        },
        "b0_materialization_receipt": {
            **artifacts_by_path[B0_MATERIALIZATION_RECEIPT_PATH],
            "materialization_receipt_hash": receipt_hash,
        },
        "b0_play_inputs": {
            **artifacts_by_path[B0_PLAY_INPUTS_PATH],
            B0_PLAY_INPUTS_SELF_HASH: b0_final.get(B0_PLAY_INPUTS_SELF_HASH),
        },
    }
    for field, expected in bridge_expected_refs.items():
        if b0_closeout.get(field) != expected:
            raise BackendReplayViolation(
                f"execution lock B0 adoption closeout {field} drift"
            )
    for field, relative in (
        ("materialization_lock", B0_MATERIALIZATION_LOCK_PATH),
        ("materialization_intent", B0_MATERIALIZATION_INTENT_PATH),
    ):
        bound = b0_receipt.get(field)
        artifact = artifacts_by_path[relative]
        if not isinstance(bound, dict) or any(
            bound.get(key) != artifact.get(key)
            for key in ("path", "sha256", "size_bytes")
        ):
            raise BackendReplayViolation(f"B0 receipt {field} artifact drift")
    final_receipt = b0_play_inputs.get("materialization_receipt")
    receipt_artifact = artifacts_by_path[B0_MATERIALIZATION_RECEIPT_PATH]
    if not isinstance(final_receipt, dict) or any(
        final_receipt.get(key) != receipt_artifact.get(key)
        for key in ("path", "sha256", "size_bytes")
    ):
        raise BackendReplayViolation("B0 final receipt artifact drift")
    if artifacts_by_path.get(str(replacement_record.get("path"))) != replacement_record:
        raise BackendReplayViolation("replacement contract record differs from artifacts")
    serialization = payload.get("serialization")
    if not isinstance(serialization, dict) or any(
        serialization.get(key) is not True
        for key in (
            "one_ros_vins_rosbag_group_at_a_time",
            "queue_order_mandatory",
            "three_replays_per_arm_are_consecutive",
        )
    ):
        raise BackendReplayViolation("execution lock serialization policy is incomplete")
    return payload


@contextmanager
def global_execution_lock(path: Path = DEFAULT_GLOBAL_FLOCK) -> Iterator[int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        raise BackendReplayViolation(
            f"cannot safely open global backend replay lock: {path}"
        ) from error
    try:
        info = os.fstat(fd)
        path_info = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(path_info.st_mode)
            or info.st_dev != path_info.st_dev
            or info.st_ino != path_info.st_ino
            or info.st_uid != os.geteuid()
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) & 0o077
        ):
            raise BackendReplayViolation(
                f"unsafe global backend replay lock identity: {path}"
            )
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise LockBusy(f"global P07 backend replay lock is busy: {path}") from error
        os.ftruncate(fd, 0)
        os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(fd)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def validate_inherited_lock(fd: int, path: Path = DEFAULT_GLOBAL_FLOCK) -> None:
    try:
        inherited = os.fstat(fd)
    except OSError as error:
        raise BackendReplayViolation("invalid inherited global-lock descriptor") from error
    if not stat.S_ISREG(inherited.st_mode):
        raise BackendReplayViolation("inherited global-lock descriptor is not a regular file")
    proc_target = Path(f"/proc/self/fd/{fd}").resolve()
    if proc_target != path.resolve():
        raise BackendReplayViolation("inherited descriptor does not name the frozen flock")
    probe = os.open(path, os.O_RDWR | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        else:
            fcntl.flock(probe, fcntl.LOCK_UN)
            raise BackendReplayViolation("inherited global-lock descriptor is not locked")
    finally:
        os.close(probe)


def write_text_exclusive(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    for directory in (path.parent, path.parent.parent):
        directory_fd = os.open(directory, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


def write_json_exclusive(path: Path, payload: Mapping[str, Any]) -> None:
    write_text_exclusive(
        path,
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
    )


def append_hash_chain_jsonl(path: Path, event: Mapping[str, Any]) -> dict[str, Any]:
    """Append one fsync'd, self-hashed event under an exclusive file lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    created = not os.path.lexists(path)
    flags = os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise BackendReplayViolation("attempt-state journal is not a regular file")
    with os.fdopen(fd, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            existing: list[dict[str, Any]] = []
            for number, line in enumerate(handle, 1):
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BackendReplayViolation(
                        f"malformed attempt-state journal line {number}"
                    ) from error
                if not isinstance(item, dict):
                    raise BackendReplayViolation("attempt-state event is not an object")
                existing.append(item)
            validate_hash_chain_events(existing)
            row = dict(event)
            row["event_index"] = len(existing) + 1
            row["previous_event_hash"] = (
                "" if not existing else str(existing[-1]["event_hash"])
            )
            row.pop("event_hash", None)
            row["event_hash"] = canonical_json_hash(row, "event_hash")
            handle.seek(0, os.SEEK_END)
            handle.write(
                json.dumps(
                    row, sort_keys=True, separators=(",", ":"), ensure_ascii=True
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
            if created:
                flags = os.O_RDONLY | os.O_CLOEXEC
                if hasattr(os, "O_DIRECTORY"):
                    flags |= os.O_DIRECTORY
                if hasattr(os, "O_NOFOLLOW"):
                    flags |= os.O_NOFOLLOW
                for directory in (path.parent, path.parent.parent):
                    directory_fd = os.open(directory, flags)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            return row
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def validate_hash_chain_events(events: Sequence[Mapping[str, Any]]) -> None:
    previous = ""
    for index, event in enumerate(events, 1):
        if (
            event.get("event_index") != index
            or event.get("previous_event_hash") != previous
            or event.get("event_hash") != canonical_json_hash(event, "event_hash")
        ):
            raise BackendReplayViolation("attempt-state journal hash chain drift")
        previous = str(event["event_hash"])


def read_hash_chain_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    if path.is_symlink() or not path.is_file():
        raise BackendReplayViolation("attempt-state journal is not a plain file")
    events: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            item = json.loads(line)
        except json.JSONDecodeError as error:
            raise BackendReplayViolation(
                f"malformed attempt-state journal line {number}"
            ) from error
        if not isinstance(item, dict):
            raise BackendReplayViolation("attempt-state event is not an object")
        events.append(item)
    validate_hash_chain_events(events)
    return events


def analyze_attempt_state_events(
    events: Sequence[Mapping[str, Any]], *, queue_index: int, run_id: str
) -> dict[str, Any]:
    """Validate the durable attempt journal and summarize crash boundaries."""

    allowed_states = {
        "ATTEMPT_DIRECTORIES_CLAIMED",
        "REGISTRY_RUNNING",
        "ADAPTER_CALL_PENDING",
        "ADAPTER_ENTERED",
        "PROCESS_LAUNCH_PENDING",
        "PROCESS_LAUNCH_FAILED",
        "PROCESS_STARTED",
        "PROCESS_EXITED",
        "ADAPTER_RETURNED",
        "ORPHAN_RECONCILE_STARTED",
        "ORPHAN_RECONCILE_DECISION_FROZEN",
    }
    pending: set[tuple[str, str]] = set()
    launch_failed: set[tuple[str, str]] = set()
    started: dict[tuple[str, str], Mapping[str, Any]] = {}
    exited: set[tuple[str, str]] = set()
    boundary = False
    for event in events:
        state = event.get("state")
        phase = event.get("phase")
        crossed = event.get("replay_boundary_may_be_crossed")
        if (
            event.get("queue_index") != queue_index
            or event.get("run_id") != run_id
            or state not in allowed_states
            or not isinstance(phase, str)
            or not isinstance(crossed, bool)
        ):
            raise BackendReplayViolation("attempt-state event identity/schema drift")
        boundary = boundary or crossed
        if state not in {
            "PROCESS_LAUNCH_PENDING",
            "PROCESS_LAUNCH_FAILED",
            "PROCESS_STARTED",
            "PROCESS_EXITED",
        }:
            continue
        argv_hash = event.get("argv_sha256")
        if not isinstance(argv_hash, str) or not _SHA256_RE.fullmatch(argv_hash):
            raise BackendReplayViolation(
                "process-state event lacks frozen argv identity"
            )
        key = (phase, argv_hash)
        if crossed is not (phase == "REPLAY_ONLY"):
            raise BackendReplayViolation("process-state replay-boundary marker drift")
        if state == "PROCESS_LAUNCH_PENDING":
            if key in pending:
                raise BackendReplayViolation("duplicate process-launch pending state")
            pending.add(key)
        elif state == "PROCESS_LAUNCH_FAILED":
            if key not in pending or key in launch_failed or key in started:
                raise BackendReplayViolation("process-launch failure binding drift")
            if not isinstance(event.get("error_type"), str):
                raise BackendReplayViolation("process-launch failure lacks error type")
            launch_failed.add(key)
        elif state == "PROCESS_STARTED":
            identity = event.get("process_identity")
            if (
                key not in pending
                or key in launch_failed
                or key in started
                or not isinstance(identity, dict)
                or set(identity) != {"pid", "starttime_ticks", "cmdline_sha256"}
                or not isinstance(identity.get("pid"), int)
                or int(identity["pid"]) <= 0
                or not isinstance(identity.get("starttime_ticks"), int)
                or int(identity["starttime_ticks"]) <= 0
                or not isinstance(identity.get("cmdline_sha256"), str)
                or not _SHA256_RE.fullmatch(identity["cmdline_sha256"])
            ):
                raise BackendReplayViolation("process-start state binding drift")
            started[key] = identity
        else:
            if key not in started or key in exited:
                raise BackendReplayViolation(
                    "process-exit state lacks one matching start"
                )
            if not isinstance(event.get("returncode"), int) or not isinstance(
                event.get("timed_out"), bool
            ):
                raise BackendReplayViolation("process-exit result is malformed")
            exited.add(key)
    live = [
        dict(identity)
        for key, identity in started.items()
        if key not in exited and same_process_alive(identity)
    ]
    return {
        "boundary_may_have_been_crossed": boundary,
        "unpaired_launch_pending": sorted(
            pending.difference(started).difference(launch_failed)
        ),
        "active_processes": live,
    }


def process_identity(pid: int) -> dict[str, Any]:
    if pid <= 0:
        raise BackendReplayViolation("invalid process id")
    proc = Path(f"/proc/{pid}")
    try:
        stat_fields = (proc / "stat").read_text(encoding="utf-8").split()
        starttime = int(stat_fields[21])
        command = (proc / "cmdline").read_bytes()
    except (OSError, ValueError, IndexError) as error:
        raise BackendReplayViolation(f"cannot capture process identity pid={pid}") from error
    return {
        "pid": pid,
        "starttime_ticks": starttime,
        "cmdline_sha256": sha256_bytes(command),
    }


def same_process_alive(identity: Mapping[str, Any]) -> bool:
    try:
        observed = process_identity(int(identity["pid"]))
    except (BackendReplayViolation, KeyError, TypeError, ValueError):
        return False
    return observed == dict(identity)


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int
    ctime_ns: int


@dataclass(frozen=True)
class DirectoryLease:
    path: str
    device: int
    inode: int
    mode: int
    owner_uid: int


def snapshot_owned_directory(path: Path, *, require_empty: bool) -> DirectoryLease:
    path = lexical_absolute(path)
    info = os.stat(path, follow_symlinks=False)
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
    ):
        raise BackendReplayViolation(f"unsafe preclaimed backend directory: {path}")
    if require_empty and any(path.iterdir()):
        raise BackendReplayViolation(f"preclaimed backend directory is not empty: {path}")
    return DirectoryLease(
        path=os.fspath(path),
        device=info.st_dev,
        inode=info.st_ino,
        mode=stat.S_IMODE(info.st_mode),
        owner_uid=info.st_uid,
    )


def verify_directory_lease(
    before: DirectoryLease, *, require_empty: bool = False
) -> DirectoryLease:
    after = snapshot_owned_directory(Path(before.path), require_empty=require_empty)
    if after != before:
        raise BackendReplayViolation(
            f"preclaimed backend directory identity changed: {before.path}"
        )
    return after


def snapshot_regular_file(path: Path) -> FileSnapshot:
    path = lexical_absolute(path)
    info = os.stat(path, follow_symlinks=False)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise BackendReplayViolation(f"not a regular immutable input: {path}")
    return FileSnapshot(
        path=os.fspath(path),
        sha256=sha256(path),
        size_bytes=info.st_size,
        device=info.st_dev,
        inode=info.st_ino,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
    )


def verify_regular_file_snapshot(before: FileSnapshot) -> FileSnapshot:
    after = snapshot_regular_file(Path(before.path))
    if after != before:
        raise BackendReplayViolation(f"immutable input changed during replay: {before.path}")
    return after


def _hash_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise BackendReplayViolation("short read while hashing locked feature-bag fd")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _required_memfd_seals() -> int:
    required = (
        "F_ADD_SEALS",
        "F_GET_SEALS",
        "F_SEAL_SEAL",
        "F_SEAL_SHRINK",
        "F_SEAL_GROW",
        "F_SEAL_WRITE",
    )
    if not hasattr(os, "memfd_create") or not hasattr(os, "MFD_ALLOW_SEALING"):
        raise BackendReplayViolation("kernel/Python lacks sealed-memfd protection")
    if any(not hasattr(fcntl, name) for name in required):
        raise BackendReplayViolation("kernel/Python lacks sealed-memfd protection")
    return (
        fcntl.F_SEAL_WRITE
        | fcntl.F_SEAL_GROW
        | fcntl.F_SEAL_SHRINK
        | fcntl.F_SEAL_SEAL
    )


def _available_memory_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                fields = line.split()
                if len(fields) == 3 and fields[2] == "kB":
                    return int(fields[1]) * 1024
    except (OSError, ValueError):
        pass
    raise BackendReplayViolation("cannot establish RAM capacity for sealed input")


def _check_memfd_capacity(size_bytes: int, *, label: str) -> None:
    # Keep a fixed 1 GiB process/ROS reserve and never consume more than half
    # of currently available memory for one anonymous immutable copy.
    available = _available_memory_bytes()
    reserve = 1024**3
    if size_bytes <= 0 or size_bytes + reserve > available or size_bytes * 2 > available:
        raise BackendReplayViolation(
            f"insufficient RAM for sealed {label}: size={size_bytes} available={available}"
        )


def _create_sealed_memfd(name: str, content: bytes, *, label: str) -> int:
    seals = _required_memfd_seals()
    _check_memfd_capacity(len(content), label=label)
    flags = os.MFD_ALLOW_SEALING
    if hasattr(os, "MFD_CLOEXEC"):
        flags |= os.MFD_CLOEXEC
    fd = os.memfd_create(name, flags)
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise BackendReplayViolation(f"short write to sealed {label}")
            view = view[written:]
        if _hash_fd(fd, len(content)) != sha256_bytes(content):
            raise BackendReplayViolation(f"sealed {label} copy hash mismatch")
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, seals)
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) != seals:
            raise BackendReplayViolation(f"sealed {label} seal set is incomplete")
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except Exception:
        os.close(fd)
        raise


def _safe_memfd_name(role: str) -> str:
    token = re.sub(r"[^A-Za-z0-9_]+", "_", role).strip("_")
    if not token:
        raise BackendReplayViolation("empty sealed runtime role")
    return f"aquafe_p07_{token}"[:240]


class SealedBytesLease:
    """Hold immutable anonymous bytes through a fully sealed inherited fd."""

    def __init__(self, content: bytes, *, role: str, label: str):
        if not isinstance(content, bytes) or not content:
            raise BackendReplayViolation(f"sealed {label} content is empty")
        self.content = content
        self.role = role
        self.label = label
        self.memfd_name = _safe_memfd_name(role)
        self.sha256 = sha256_bytes(content)
        self.size_bytes = len(content)
        self.fd: int | None = None

    def __enter__(self) -> "SealedBytesLease":
        self.fd = _create_sealed_memfd(
            self.memfd_name, self.content, label=self.label
        )
        return self

    @property
    def proc_path(self) -> str:
        if self.fd is None:
            raise BackendReplayViolation(f"sealed {self.label} lease is not open")
        return f"/proc/self/fd/{self.fd}"

    def verify_sealed(self) -> None:
        if self.fd is None:
            raise BackendReplayViolation(f"sealed {self.label} lease is not open")
        info = os.fstat(self.fd)
        if (
            info.st_size != self.size_bytes
            or _hash_fd(self.fd, info.st_size) != self.sha256
            or fcntl.fcntl(self.fd, fcntl.F_GET_SEALS) != _required_memfd_seals()
        ):
            raise BackendReplayViolation(f"sealed {self.label} changed during use")

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class SealedFileLease:
    """Snapshot one hash-bound file into sealed bytes and retain its source fd."""

    def __init__(
        self,
        path: Path,
        expected_sha256: str,
        *,
        role: str,
        label: str,
        expected_size_bytes: int | None = None,
    ):
        self.path = lexical_absolute(path)
        self.expected_sha256 = expected_sha256
        self.expected_size_bytes = expected_size_bytes
        self.role = role
        self.label = label
        self.memfd_name = _safe_memfd_name(role)
        self.source_fd: int | None = None
        self.fd: int | None = None
        self.before: FileSnapshot | None = None

    def __enter__(self) -> "SealedFileLease":
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self.source_fd = os.open(self.path, flags)
            info = os.fstat(self.source_fd)
            if not stat.S_ISREG(info.st_mode):
                raise BackendReplayViolation(f"{self.label} is not a regular file")
            if (
                self.expected_size_bytes is not None
                and info.st_size != self.expected_size_bytes
            ):
                raise BackendReplayViolation(f"{self.label} size differs before use")
            _check_memfd_capacity(info.st_size, label=self.label)
            content = bytearray()
            offset = 0
            while offset < info.st_size:
                chunk = os.pread(
                    self.source_fd, min(1024 * 1024, info.st_size - offset), offset
                )
                if not chunk:
                    raise BackendReplayViolation(
                        f"short read while snapshotting {self.label}"
                    )
                content.extend(chunk)
                offset += len(chunk)
            observed_hash = sha256_bytes(bytes(content))
            if observed_hash != self.expected_sha256:
                raise BackendReplayViolation(f"{self.label} hash differs before use")
            self.before = FileSnapshot(
                path=os.fspath(self.path),
                sha256=observed_hash,
                size_bytes=info.st_size,
                device=info.st_dev,
                inode=info.st_ino,
                mtime_ns=info.st_mtime_ns,
                ctime_ns=info.st_ctime_ns,
            )
            self.fd = _create_sealed_memfd(
                self.memfd_name, bytes(content), label=self.label
            )
            return self
        except Exception:
            self.close()
            raise

    @property
    def proc_path(self) -> str:
        if self.fd is None:
            raise BackendReplayViolation(f"sealed {self.label} lease is not open")
        return f"/proc/self/fd/{self.fd}"

    def verify_unchanged(self) -> FileSnapshot:
        if self.source_fd is None or self.fd is None or self.before is None:
            raise BackendReplayViolation(f"sealed {self.label} lease is not open")
        sealed = os.fstat(self.fd)
        if (
            sealed.st_size != self.before.size_bytes
            or _hash_fd(self.fd, sealed.st_size) != self.before.sha256
            or fcntl.fcntl(self.fd, fcntl.F_GET_SEALS) != _required_memfd_seals()
        ):
            raise BackendReplayViolation(f"sealed consumer {self.label} changed")
        source = os.fstat(self.source_fd)
        source_snapshot = FileSnapshot(
            path=os.fspath(self.path),
            sha256=_hash_fd(self.source_fd, source.st_size),
            size_bytes=source.st_size,
            device=source.st_dev,
            inode=source.st_ino,
            mtime_ns=source.st_mtime_ns,
            ctime_ns=source.st_ctime_ns,
        )
        try:
            path_info = os.stat(self.path, follow_symlinks=False)
        except FileNotFoundError as error:
            raise BackendReplayViolation(f"{self.label} pathname disappeared") from error
        if (
            source_snapshot != self.before
            or stat.S_ISLNK(path_info.st_mode)
            or not stat.S_ISREG(path_info.st_mode)
            or path_info.st_dev != self.before.device
            or path_info.st_ino != self.before.inode
            or path_info.st_size != self.before.size_bytes
            or path_info.st_mtime_ns != self.before.mtime_ns
            or path_info.st_ctime_ns != self.before.ctime_ns
            or sha256(self.path) != self.before.sha256
        ):
            raise BackendReplayViolation(f"{self.label} identity or hash changed")
        return source_snapshot

    def snapshot_dict(self) -> dict[str, Any]:
        if self.before is None:
            raise BackendReplayViolation(f"sealed {self.label} lease is not open")
        return asdict(self.before)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.source_fd is not None:
            os.close(self.source_fd)
            self.source_fd = None

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def _runtime_module_name(relative: str) -> str | None:
    pure = PurePosixPath(relative)
    if len(pure.parts) >= 2 and pure.parts[0] == "scripts" and pure.suffix == ".py":
        return ".".join((*pure.parts[:-1], pure.stem))
    return None


@dataclass(frozen=True)
class RuntimeConsumptionContext:
    entries: Mapping[str, Mapping[str, Any]]
    execution_lock_sha256: str

    @property
    def pass_fds(self) -> tuple[int, ...]:
        return tuple(sorted(int(item["fd"]) for item in self.entries.values()))

    def proc_path(self, role: str) -> str:
        try:
            return f"/proc/self/fd/{int(self.entries[role]['fd'])}"
        except (KeyError, TypeError, ValueError) as error:
            raise BackendReplayViolation(f"sealed runtime role is absent: {role}") from error

    def python_argv(self, role: str, arguments: Sequence[str]) -> list[str]:
        module = self.entries.get(role, {}).get("module")
        if not isinstance(module, str):
            raise BackendReplayViolation(f"sealed runtime role is not Python: {role}")
        return [
            self.proc_path("python_interpreter"),
            "-I",
            self.proc_path(SEALED_RUNTIME_BOOTSTRAP_ROLE),
            module,
            *[str(value) for value in arguments],
        ]

    def shell_argv(self, role: str, arguments: Sequence[str]) -> list[str]:
        if self.entries.get(role, {}).get("module") is not None:
            raise BackendReplayViolation(f"sealed runtime role is not shell: {role}")
        return ["bash", self.proc_path(role), *[str(value) for value in arguments]]

    def environment(self) -> dict[str, str]:
        payload = {
            "schema_version": SEALED_RUNTIME_SCHEMA,
            "execution_lock_sha256": self.execution_lock_sha256,
            "entries": [dict(self.entries[role]) for role in sorted(self.entries)],
        }
        return {
            SEALED_RUNTIME_ENVIRONMENT_KEY: json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
            ),
            SEALED_EXECUTION_LOCK_HASH_KEY: self.execution_lock_sha256,
        }


def sanitized_child_environment(
    *, extra: Mapping[str, str] | None = None
) -> dict[str, str]:
    """Return the shared non-inheriting child environment without authority."""

    environment = {
        "HOME": "/home/ma",
        "USER": "ma",
        "LOGNAME": "ma",
        "SHELL": "/bin/bash",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if extra is not None:
        forbidden = {
            key
            for key in extra
            if key in {"PYTHONPATH", "PYTHONHOME"}
            or key.startswith("LD_")
            or key in {
                SEALED_RUNTIME_ENVIRONMENT_KEY,
                SEALED_EXECUTION_LOCK_HASH_KEY,
            }
        }
        if forbidden:
            raise BackendReplayViolation(
                f"sealed runtime environment contains forbidden overrides: {sorted(forbidden)}"
            )
        environment.update({str(key): str(value) for key, value in extra.items()})
    return environment


def sealed_runtime_environment(
    context: RuntimeConsumptionContext,
    *,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return the sanitized environment plus exact sealed-runtime authority."""

    environment = sanitized_child_environment(extra=extra)
    environment.update(context.environment())
    return environment


def _runtime_binding_records(
    execution_lock: Mapping[str, Any],
) -> dict[str, Mapping[str, Any]]:
    runtime = execution_lock.get("runtime_implementation_bindings")
    external = execution_lock.get("external_runtime_bindings")
    if not isinstance(runtime, Mapping) or set(runtime) != set(
        RUNTIME_IMPLEMENTATION_BINDING_PATHS
    ):
        raise BackendReplayViolation("execution lock runtime binding set differs")
    if not isinstance(external, Mapping) or set(external) != set(
        EXTERNAL_RUNTIME_BINDING_PATHS
    ):
        raise BackendReplayViolation("execution lock external runtime binding set differs")
    return {
        **{str(role): record for role, record in runtime.items()},
        **{str(role): record for role, record in external.items()},
    }


def validate_sealed_runtime_context(
    execution_lock: Mapping[str, Any],
    *,
    execution_lock_sha256: str,
    environment: Mapping[str, str] | None = None,
) -> RuntimeConsumptionContext:
    environment = os.environ if environment is None else environment
    raw = environment.get(SEALED_RUNTIME_ENVIRONMENT_KEY)
    if not raw:
        raise BackendReplayViolation("sealed runtime manifest is absent")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise BackendReplayViolation("sealed runtime manifest is invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "execution_lock_sha256",
        "entries",
    }:
        raise BackendReplayViolation("sealed runtime manifest shape differs")
    if (
        payload.get("schema_version") != SEALED_RUNTIME_SCHEMA
        or payload.get("execution_lock_sha256") != execution_lock_sha256
        or environment.get(SEALED_EXECUTION_LOCK_HASH_KEY) != execution_lock_sha256
    ):
        raise BackendReplayViolation("sealed runtime execution-lock binding differs")
    records = _runtime_binding_records(execution_lock)
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list):
        raise BackendReplayViolation("sealed runtime entries are absent")
    entries: dict[str, Mapping[str, Any]] = {}
    required_keys = {
        "role",
        "path",
        "sha256",
        "size_bytes",
        "fd",
        "module",
        "memfd_name",
    }
    for raw_entry in raw_entries:
        if not isinstance(raw_entry, Mapping) or set(raw_entry) != required_keys:
            raise BackendReplayViolation("sealed runtime entry shape differs")
        role = str(raw_entry.get("role", ""))
        if not role or role in entries or role not in records:
            raise BackendReplayViolation("sealed runtime role coverage differs")
        record = records[role]
        expected_path = str(record.get("path", ""))
        expected_module = (
            _runtime_module_name(expected_path)
            if role in RUNTIME_IMPLEMENTATION_BINDING_PATHS
            else None
        )
        fd = raw_entry.get("fd")
        if (
            raw_entry.get("path") != expected_path
            or raw_entry.get("sha256") != record.get("sha256")
            or raw_entry.get("size_bytes") != record.get("size_bytes")
            or raw_entry.get("module") != expected_module
            or raw_entry.get("memfd_name") != _safe_memfd_name(role)
            or isinstance(fd, bool)
            or not isinstance(fd, int)
            or fd < 3
        ):
            raise BackendReplayViolation(f"sealed runtime entry differs: {role}")
        try:
            info = os.fstat(fd)
        except OSError as error:
            raise BackendReplayViolation(f"sealed runtime fd is closed: {role}") from error
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size != int(record["size_bytes"])
            or _hash_fd(fd, info.st_size) != record.get("sha256")
            or fcntl.fcntl(fd, fcntl.F_GET_SEALS) != _required_memfd_seals()
        ):
            raise BackendReplayViolation(f"sealed runtime fd differs: {role}")
        entries[role] = dict(raw_entry)
    if set(entries) != set(records):
        raise BackendReplayViolation("sealed runtime role coverage differs")
    return RuntimeConsumptionContext(entries, execution_lock_sha256)


class SealedRuntimeBundle:
    """Create the one execution-lock-bound runtime snapshot used by a job."""

    def __init__(
        self,
        root: Path,
        execution_lock: Mapping[str, Any],
        *,
        execution_lock_sha256: str,
    ):
        self.root = lexical_absolute(root)
        self.execution_lock = execution_lock
        self.execution_lock_sha256 = execution_lock_sha256
        self.leases: dict[str, SealedFileLease] = {}
        self.context: RuntimeConsumptionContext | None = None

    def __enter__(self) -> RuntimeConsumptionContext:
        records = _runtime_binding_records(self.execution_lock)
        try:
            for role in sorted(records):
                record = records[role]
                raw_path = str(record.get("path", ""))
                path = (
                    self.root / raw_path
                    if role in RUNTIME_IMPLEMENTATION_BINDING_PATHS
                    else Path(raw_path)
                )
                lease = SealedFileLease(
                    path,
                    str(record.get("sha256", "")),
                    role=role,
                    label=f"runtime {role}",
                    expected_size_bytes=int(record.get("size_bytes", -1)),
                )
                lease.__enter__()
                self.leases[role] = lease
            entries: dict[str, Mapping[str, Any]] = {}
            for role, lease in self.leases.items():
                record = records[role]
                if lease.fd is None:
                    raise BackendReplayViolation("sealed runtime lease lost its fd")
                path = str(record["path"])
                entries[role] = {
                    "role": role,
                    "path": path,
                    "sha256": record["sha256"],
                    "size_bytes": record["size_bytes"],
                    "fd": lease.fd,
                    "module": (
                        _runtime_module_name(path)
                        if role in RUNTIME_IMPLEMENTATION_BINDING_PATHS
                        else None
                    ),
                    "memfd_name": lease.memfd_name,
                }
            context = RuntimeConsumptionContext(entries, self.execution_lock_sha256)
            # Reuse the public validator so producer and consumer accept exactly
            # the same manifest semantics.
            self.context = validate_sealed_runtime_context(
                self.execution_lock,
                execution_lock_sha256=self.execution_lock_sha256,
                environment=context.environment(),
            )
            return self.context
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        first_error: Exception | None = None
        for role in reversed(sorted(self.leases)):
            lease = self.leases[role]
            try:
                lease.verify_unchanged()
            except Exception as error:
                if first_error is None:
                    first_error = error
            finally:
                lease.close()
        self.leases.clear()
        self.context = None
        if first_error is not None:
            raise first_error

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class ReadOnlyFeatureBag:
    """Lease an immutable sealed copy while preserving the frozen source bag.

    A plain ``/proc/self/fd/N`` path backed by an ``O_RDONLY`` source descriptor
    is not sufficient: Linux permits another process to reopen that procfs path
    with write access to the underlying inode.  The consumer therefore receives
    a byte-exact anonymous memfd protected by write/grow/shrink seals.  The
    source descriptor remains open separately and its pathname, identity, and
    SHA-256 are revalidated after replay.
    """

    def __init__(self, path: Path, expected_sha256: str):
        self.path = lexical_absolute(path)
        self.expected_sha256 = expected_sha256
        self.source_fd: int | None = None
        self.fd: int | None = None
        self.before: FileSnapshot | None = None

    def __enter__(self) -> "ReadOnlyFeatureBag":
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self.source_fd = os.open(self.path, flags)
            info = os.fstat(self.source_fd)
            if not stat.S_ISREG(info.st_mode):
                raise BackendReplayViolation("feature bag is not a regular file")
            observed_hash = _hash_fd(self.source_fd, info.st_size)
            if observed_hash != self.expected_sha256:
                raise BackendReplayViolation(
                    "feature bag hash differs before backend replay"
                )
            self.before = FileSnapshot(
                path=os.fspath(self.path),
                sha256=observed_hash,
                size_bytes=info.st_size,
                device=info.st_dev,
                inode=info.st_ino,
                mtime_ns=info.st_mtime_ns,
                ctime_ns=info.st_ctime_ns,
            )
            required = (
                "memfd_create",
                "MFD_ALLOW_SEALING",
            )
            if any(not hasattr(os, name) for name in required) or any(
                not hasattr(fcntl, name)
                for name in (
                    "F_ADD_SEALS",
                    "F_GET_SEALS",
                    "F_SEAL_SEAL",
                    "F_SEAL_SHRINK",
                    "F_SEAL_GROW",
                    "F_SEAL_WRITE",
                )
            ):
                raise BackendReplayViolation(
                    "kernel/Python lacks sealed-memfd input protection"
                )
            memfd_flags = os.MFD_ALLOW_SEALING
            if hasattr(os, "MFD_CLOEXEC"):
                memfd_flags |= os.MFD_CLOEXEC
            self.fd = os.memfd_create("aquafe_p07_frozen_feature_bag", memfd_flags)
            offset = 0
            while offset < info.st_size:
                chunk = os.pread(
                    self.source_fd, min(1024 * 1024, info.st_size - offset), offset
                )
                if not chunk:
                    raise BackendReplayViolation(
                        "short read while copying frozen bag into sealed memfd"
                    )
                view = memoryview(chunk)
                while view:
                    written = os.write(self.fd, view)
                    if written <= 0:
                        raise BackendReplayViolation(
                            "short write while copying frozen bag into sealed memfd"
                        )
                    view = view[written:]
                offset += len(chunk)
            if _hash_fd(self.fd, info.st_size) != observed_hash:
                raise BackendReplayViolation("sealed feature-bag copy hash mismatch")
            seals = (
                fcntl.F_SEAL_WRITE
                | fcntl.F_SEAL_GROW
                | fcntl.F_SEAL_SHRINK
                | fcntl.F_SEAL_SEAL
            )
            fcntl.fcntl(self.fd, fcntl.F_ADD_SEALS, seals)
            if fcntl.fcntl(self.fd, fcntl.F_GET_SEALS) != seals:
                raise BackendReplayViolation("feature-bag memfd seal set is incomplete")
            os.lseek(self.fd, 0, os.SEEK_SET)
            return self
        except Exception:
            self.close()
            raise

    @property
    def proc_path(self) -> str:
        if self.fd is None:
            raise BackendReplayViolation("feature-bag lease is not open")
        return f"/proc/self/fd/{self.fd}"

    def verify_unchanged(self) -> FileSnapshot:
        if self.source_fd is None or self.fd is None or self.before is None:
            raise BackendReplayViolation("feature-bag lease is not open")
        fd_info = os.fstat(self.source_fd)
        fd_hash = _hash_fd(self.source_fd, fd_info.st_size)
        sealed_info = os.fstat(self.fd)
        sealed_hash = _hash_fd(self.fd, sealed_info.st_size)
        required_seals = (
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL
        )
        if (
            sealed_info.st_size != self.before.size_bytes
            or sealed_hash != self.before.sha256
            or fcntl.fcntl(self.fd, fcntl.F_GET_SEALS) != required_seals
        ):
            raise BackendReplayViolation(
                "sealed consumer feature bag changed during replay"
            )
        try:
            path_info = os.stat(self.path, follow_symlinks=False)
        except FileNotFoundError as error:
            raise BackendReplayViolation("feature bag pathname disappeared during replay") from error
        if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(path_info.st_mode):
            raise BackendReplayViolation("feature bag pathname type changed during replay")
        after = FileSnapshot(
            path=os.fspath(self.path),
            sha256=fd_hash,
            size_bytes=fd_info.st_size,
            device=fd_info.st_dev,
            inode=fd_info.st_ino,
            mtime_ns=fd_info.st_mtime_ns,
            ctime_ns=fd_info.st_ctime_ns,
        )
        if (
            after != self.before
            or path_info.st_dev != self.before.device
            or path_info.st_ino != self.before.inode
            or path_info.st_size != self.before.size_bytes
            or path_info.st_mtime_ns != self.before.mtime_ns
            or path_info.st_ctime_ns != self.before.ctime_ns
            or sha256(self.path) != self.before.sha256
        ):
            raise BackendReplayViolation("feature bag identity or SHA changed during replay")
        return after

    def snapshot_dict(self) -> dict[str, Any]:
        if self.before is None:
            raise BackendReplayViolation("feature-bag lease is not open")
        return asdict(self.before)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.source_fd is not None:
            os.close(self.source_fd)
            self.source_fd = None

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()
