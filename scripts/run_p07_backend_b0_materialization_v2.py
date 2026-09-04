#!/usr/bin/env python3
"""Fail-closed transaction core for P07 B0-v2 input materialization.

The default CLI is a read-only preflight.  This module never starts ROS/VINS,
never reads a trajectory outcome, and never overwrites or name-unlinks a stage.
The current formal-lock builder does not yet bind this runtime and its tests, so
the CLI deliberately keeps ``--execute`` blocked.  The transaction primitives
are complete and fixture-testable so a later, source-bound lock can adopt them
without changing their on-disk protocol.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
from datetime import datetime
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from scripts import build_p07_backend_b0_materialization_lock_v2 as formal_lock
    from scripts import p07_backend_actual_consumed_core_v2 as actual
    from scripts import p07_backend_b0_plan_v2 as b0
    from scripts import p07_backend_formal_io_v1 as formal_io
    from scripts import p07_ntnu_window_fanout_v1 as ntnu_fanout
except ModuleNotFoundError:  # direct ``python scripts/...`` execution
    import build_p07_backend_b0_materialization_lock_v2 as formal_lock  # type: ignore
    import p07_backend_actual_consumed_core_v2 as actual  # type: ignore
    import p07_backend_b0_plan_v2 as b0  # type: ignore
    import p07_backend_formal_io_v1 as formal_io  # type: ignore
    import p07_ntnu_window_fanout_v1 as ntnu_fanout  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
P07_RELATIVE = formal_lock.P07_RELATIVE
FORMAL_LOCK_RELATIVE = formal_lock.OUTPUT_RELATIVE
RUNTIME_RELATIVE = "scripts/run_p07_backend_b0_materialization_v2.py"
TEST_RELATIVE = "scripts/tests/test_p07_backend_b0_materialization_v2.py"
LEGACY_INSPECTOR_RELATIVE = "scripts/run_p07_backend_b0_materialization_v1.py"

INTENT_RELATIVE = P07_RELATIVE + "/backend_b0_materialization_intent_v2.json"
NTNU_STAGE_RECEIPT_RELATIVE = (
    P07_RELATIVE + "/backend_b0_ntnu_stage_receipt_v2.json"
)
RECEIPT_RELATIVE = P07_RELATIVE + "/backend_b0_materialization_receipt_v2.json"
PLAY_INPUTS_RELATIVE = P07_RELATIVE + "/backend_b0_play_inputs_v2.json"
RESOLVED_ACTUAL_RELATIVE = (
    P07_RELATIVE + "/backend_actual_consumed_resolved_v2.json"
)
CLOSEOUT_RELATIVE = P07_RELATIVE + "/backend_b0_materialization_closeout_v2.json"

INTENT_SCHEMA = "isj-p07-backend-b0-materialization-intent-v2"
INTENT_HASH_FIELD = "materialization_intent_v2_hash"
NTNU_STAGE_RECEIPT_SCHEMA = "isj-p07-backend-b0-ntnu-stage-receipt-v2"
NTNU_STAGE_RECEIPT_HASH_FIELD = "ntnu_stage_receipt_v2_hash"
RECEIPT_SCHEMA = "isj-p07-backend-b0-materialization-receipt-v2"
RECEIPT_HASH_FIELD = "materialization_receipt_v2_hash"
PLAY_INPUTS_SCHEMA = "isj-p07-backend-b0-play-inputs-v2"
PLAY_INPUTS_HASH_FIELD = "b0_play_inputs_v2_hash"
RESOLVED_ACTUAL_SCHEMA = "isj-p07-backend-actual-consumed-resolved-v2"
RESOLVED_ACTUAL_HASH_FIELD = "actual_consumed_resolved_v2_hash"
CLOSEOUT_SCHEMA = "isj-p07-backend-b0-materialization-closeout-v2"
CLOSEOUT_HASH_FIELD = "materialization_closeout_v2_hash"

STATUS_BLOCKED = "BLOCKED_NOT_IMPLEMENTED_PENDING_FORMAL_RUNTIME_SOURCE_BINDING"
OUTCOME_BOUNDARY = "B0_INPUT_MATERIALIZATION_ONLY_NO_ROS_VINS_APE_RPE_TRAJECTORY"
ACTION_FLOCK = Path("/tmp/aquafe_p07_backend_b0_materialization_v2.lock")
CLI_EXECUTION_IMPLEMENTED = False

EXECUTION_REQUIRED_SOURCE_PATHS = tuple(
    sorted(
        set(formal_lock.SOURCE_PATHS)
        | {RUNTIME_RELATIVE, TEST_RELATIVE, LEGACY_INSPECTOR_RELATIVE}
    )
)
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_PROC_BLOCKLIST = (
    "roscore",
    "rosbag play",
    "vins_node",
    "run_p07_backend_b0_materialization_v1.py --execute",
    "run_p07_backend_b0_materialization_adopted_v1.py --execute",
)
_RENAME_NOREPLACE = 1
_AT_FDCWD = -100
_LIBC = ctypes.CDLL(None, use_errno=True)


class B0MaterializationV2Error(RuntimeError):
    """Structured fail-closed runtime error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details)

    def block(self) -> Dict[str, Any]:
        return {
            "status": "BLOCKED",
            "code": self.code,
            "message": str(self),
            "details": _clone(self.details),
            "run_vins": False,
            "trajectory_outcome_read": False,
        }


class SimulatedCrash(BaseException):
    """Test-only crash boundary; intentionally bypasses ordinary exception cleanup."""


def canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise B0MaterializationV2Error(
            "NON_CANONICAL_JSON", "value is not finite canonical JSON"
        ) from error


def _clone(value: Any) -> Any:
    return json.loads(canonical_json(value))


def document_hash(payload: Mapping[str, Any], field: str) -> str:
    clone = _clone(payload)
    clone[field] = ""
    return hashlib.sha256(canonical_json(clone).encode("utf-8")).hexdigest()


def _finish(payload: Dict[str, Any], field: str) -> Dict[str, Any]:
    payload[field] = ""
    payload[field] = document_hash(payload, field)
    return payload


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise B0MaterializationV2Error("INVALID_SHA256", label + " SHA-256 drift")
    return value


def _timestamp(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise B0MaterializationV2Error("INVALID_TIMESTAMP", label + " is absent")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise B0MaterializationV2Error(
            "INVALID_TIMESTAMP", label + " is not ISO-8601"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise B0MaterializationV2Error(
            "INVALID_TIMESTAMP", label + " must be timezone-aware"
        )
    return value


def _safe_relative(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise B0MaterializationV2Error("UNSAFE_PATH", label + " is not text")
    pure = PurePosixPath(value)
    if (
        not value
        or "\x00" in value
        or pure.is_absolute()
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise B0MaterializationV2Error("UNSAFE_PATH", label + " path is unsafe")
    return value


def _portable_record(relative: str, sha256: str, size_bytes: int) -> Dict[str, Any]:
    return {
        "path": _safe_relative(relative, "record"),
        "sha256": _sha(sha256, "record"),
        "size_bytes": int(size_bytes),
    }


def _record_for_bytes(relative: str, content: bytes) -> Dict[str, Any]:
    return _portable_record(
        relative, hashlib.sha256(content).hexdigest(), len(content)
    )


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (canonical_json(payload) + "\n").encode("utf-8")


def _identity(info: os.stat_result) -> Dict[str, int]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(info.st_mode),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _same_inode(info: os.stat_result, expected: Mapping[str, Any]) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and int(info.st_dev) == int(expected["device"])
        and int(info.st_ino) == int(expected["inode"])
    )


def _sha256_fd(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        chunk = os.pread(descriptor, 1024 * 1024, offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _open_parent(root: Path, relative: str) -> Tuple[int, str, Path]:
    safe = _safe_relative(relative, "workspace")
    parts = PurePosixPath(safe).parts
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    try:
        descriptor = os.open(os.fspath(root.absolute()), flags)
    except OSError as error:
        raise B0MaterializationV2Error(
            "ROOT_UNSAFE", "workspace root is not a direct directory"
        ) from error
    try:
        for component in parts[:-1]:
            next_fd = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
    except OSError as error:
        os.close(descriptor)
        raise B0MaterializationV2Error(
            "PARENT_UNSAFE", "workspace parent is absent, symlinked, or non-directory",
            path=safe,
        ) from error
    return descriptor, parts[-1], root.absolute() / safe


def _open_readonly(root: Path, relative: str) -> Tuple[int, int, str, Path]:
    parent_fd, name, path = _open_parent(root, relative)
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd
        )
    except BaseException:
        os.close(parent_fd)
        raise
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        os.close(parent_fd)
        raise B0MaterializationV2Error(
            "NOT_REGULAR", "bound input is not a direct regular file", path=relative
        )
    return descriptor, parent_fd, name, path


def _path_state(parent_fd: int, name: str) -> Tuple[str, Optional[os.stat_result]]:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return "ABSENT", None
    if stat.S_ISREG(info.st_mode):
        return "FILE", info
    return "OTHER", info


def _rename_noreplace_at(
    source_dir_fd: int,
    source_name: str,
    destination_dir_fd: int,
    destination_name: str,
) -> None:
    renameat2 = getattr(_LIBC, "renameat2", None)
    if renameat2 is None:
        raise B0MaterializationV2Error(
            "RENAMEAT2_UNAVAILABLE", "renameat2(RENAME_NOREPLACE) is unavailable"
        )
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    result = renameat2(
        source_dir_fd,
        os.fsencode(source_name),
        destination_dir_fd,
        os.fsencode(destination_name),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        number = ctypes.get_errno()
        if number == errno.EEXIST:
            raise FileExistsError(number, os.strerror(number), destination_name)
        raise OSError(number, os.strerror(number), destination_name)


def deterministic_stage_relative(
    target_relative: str, window_id: str, lock_hash: str
) -> str:
    target = PurePosixPath(_safe_relative(target_relative, "target"))
    lock_prefix = _sha(lock_hash, "lock")[:16]
    window_prefix = hashlib.sha256(window_id.encode("utf-8")).hexdigest()[:16]
    name = ".%s.aqua-fe-b0-v2-stage-%s-%s" % (
        target.name,
        lock_prefix,
        window_prefix,
    )
    return str(target.parent / name)


def deterministic_preserved_relative(
    target_relative: str, window_id: str, lock_hash: str
) -> str:
    target = PurePosixPath(_safe_relative(target_relative, "target"))
    lock_prefix = _sha(lock_hash, "lock")[:16]
    window_prefix = hashlib.sha256(window_id.encode("utf-8")).hexdigest()[:16]
    name = ".%s.aqua-fe-preserved-%s-%s" % (
        target.name,
        lock_prefix,
        window_prefix,
    )
    return str(target.parent / name)


@dataclass
class RetainedStage:
    window_id: str
    target_relative: str
    stage_relative: str
    preserved_relative: str
    parent_fd: int
    stage_name: str
    final_name: str
    preserved_name: str
    descriptor: int
    create_identity: Dict[str, int]
    published: bool = False
    preserved: bool = False
    closed: bool = False

    @property
    def proc_path(self) -> Path:
        return Path("/proc/self/fd/%d" % self.descriptor)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        os.close(self.descriptor)
        os.close(self.parent_fd)


def create_retained_stage(
    root: Path, target_relative: str, window_id: str, lock_hash: str
) -> RetainedStage:
    stage_relative = deterministic_stage_relative(target_relative, window_id, lock_hash)
    preserved_relative = deterministic_preserved_relative(
        target_relative, window_id, lock_hash
    )
    stage_parent = str(PurePosixPath(stage_relative).parent)
    target_parent = str(PurePosixPath(target_relative).parent)
    if stage_parent != target_parent:
        raise B0MaterializationV2Error(
            "CROSS_DIRECTORY_STAGE", "stage is not in the final target directory"
        )
    parent_fd, stage_name, _path = _open_parent(root, stage_relative)
    final_name = PurePosixPath(target_relative).name
    preserved_name = PurePosixPath(preserved_relative).name
    for name, label in ((final_name, "final"), (preserved_name, "preserved")):
        state, _info = _path_state(parent_fd, name)
        if state == "OTHER":
            os.close(parent_fd)
            raise B0MaterializationV2Error(
                "TARGET_TYPE_COLLISION", label + " path is not a direct regular file"
            )
    try:
        descriptor = os.open(
            stage_name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_EXCL
            | os.O_NOFOLLOW
            | os.O_CLOEXEC,
            0o600,
            dir_fd=parent_fd,
        )
    except BaseException:
        os.close(parent_fd)
        raise
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        os.close(descriptor)
        os.close(parent_fd)
        raise B0MaterializationV2Error(
            "STAGE_NOT_REGULAR", "exclusive stage is not a regular file"
        )
    return RetainedStage(
        window_id=window_id,
        target_relative=target_relative,
        stage_relative=stage_relative,
        preserved_relative=preserved_relative,
        parent_fd=parent_fd,
        stage_name=stage_name,
        final_name=final_name,
        preserved_name=preserved_name,
        descriptor=descriptor,
        create_identity=_identity(info),
    )


def _assert_stage_path_owned(stage: RetainedStage) -> os.stat_result:
    state, info = _path_state(stage.parent_fd, stage.stage_name)
    if state != "FILE" or info is None or not _same_inode(info, stage.create_identity):
        raise B0MaterializationV2Error(
            "STAGE_PATH_IDENTITY_DRIFT",
            "stage pathname no longer names the retained inode",
            stage=stage.stage_relative,
            retained_identity=_identity(os.fstat(stage.descriptor)),
        )
    if not _same_inode(os.fstat(stage.descriptor), stage.create_identity):
        raise B0MaterializationV2Error(
            "RETAINED_STAGE_IDENTITY_DRIFT", "retained stage descriptor changed inode"
        )
    return info


def preserve_stage(
    stage: RetainedStage,
    *,
    reason: str,
    renamer: Callable[[int, str, int, str], None] = _rename_noreplace_at,
) -> Dict[str, Any]:
    _assert_stage_path_owned(stage)
    state, _info = _path_state(stage.parent_fd, stage.preserved_name)
    if state != "ABSENT":
        raise B0MaterializationV2Error(
            "PRESERVED_STAGE_COLLISION",
            "deterministic preserved stage already exists",
            stage=stage.stage_relative,
            preserved=stage.preserved_relative,
            reason=reason,
        )
    renamer(stage.parent_fd, stage.stage_name, stage.parent_fd, stage.preserved_name)
    os.fsync(stage.parent_fd)
    state, info = _path_state(stage.parent_fd, stage.preserved_name)
    if state != "FILE" or info is None or not _same_inode(info, stage.create_identity):
        raise B0MaterializationV2Error(
            "PRESERVATION_IDENTITY_DRIFT", "preserved stage inode differs"
        )
    stage.stage_name = stage.preserved_name
    stage.stage_relative = stage.preserved_relative
    stage.preserved = True
    return {
        "status": "PRESERVED",
        "path": stage.preserved_relative,
        "reason": reason,
        "identity": _identity(os.fstat(stage.descriptor)),
    }


def _verify_descriptor_record(
    descriptor: int, expected_sha256: Optional[str], expected_size: Optional[int]
) -> Dict[str, Any]:
    before = _identity(os.fstat(descriptor))
    digest = _sha256_fd(descriptor)
    after = _identity(os.fstat(descriptor))
    if before != after:
        raise B0MaterializationV2Error(
            "DESCRIPTOR_CHANGED_DURING_HASH", "retained descriptor changed during hash"
        )
    if expected_sha256 is not None and digest != expected_sha256:
        raise B0MaterializationV2Error(
            "STAGE_SHA256_DRIFT", "stage content SHA-256 differs"
        )
    if expected_size is not None and after["size_bytes"] != int(expected_size):
        raise B0MaterializationV2Error(
            "STAGE_SIZE_DRIFT", "stage size differs"
        )
    return {"sha256": digest, "size_bytes": after["size_bytes"], "identity": after}


def _clean_converter_environment() -> Dict[str, str]:
    allowed = (
        "PATH",
        "PYTHONPATH",
        "LD_LIBRARY_PATH",
        "ROS_PACKAGE_PATH",
        "HOME",
        "LANG",
        "LC_ALL",
    )
    environment = {key: os.environ[key] for key in allowed if key in os.environ}
    environment.update(
        {
            "RUN_VINS": "0",
            "RUN_EVALUATION": "0",
            "EXPORT_FEATURES": "0",
            "FORCE_EXPORT": "0",
        }
    )
    return environment


def _converter_argv(
    recipe: Mapping[str, Any], output_proc: str, replacements: Mapping[str, str]
) -> List[str]:
    template = recipe.get("converter_argv_template")
    if not isinstance(template, list) or template.count("{OUTPUT}") != 1:
        raise B0MaterializationV2Error(
            "CONVERTER_TEMPLATE_DRIFT", "converter output token coverage differs"
        )
    argv = [
        output_proc if value == "{OUTPUT}" else replacements.get(str(value), str(value))
        for value in template
    ]
    if argv[:3] != [
        "python3",
        "-m",
        "uw_frontend.datasets.aqualoc_raw_to_rosbag",
    ]:
        raise B0MaterializationV2Error(
            "CONVERTER_NOT_ALLOWLISTED", "converter entrypoint differs"
        )
    if recipe["window_id"] == "aqualoc_archaeology:A04:0002":
        try:
            raw_root = argv[argv.index("--raw-root") + 1]
        except (ValueError, IndexError) as error:
            raise B0MaterializationV2Error(
                "A04_LAYOUT_DRIFT", "A04 converter lacks raw-root"
            ) from error
        if raw_root != ".":
            raise B0MaterializationV2Error(
                "A04_LAYOUT_DRIFT", "A04 converter raw-root must be dot"
            )
    return argv


def _open_verified_input(
    root: Path, relative: str, expected_sha256: str, expected_size: int
) -> Tuple[int, int]:
    descriptor, parent_fd, _name, _path = _open_readonly(root, relative)
    try:
        record = _verify_descriptor_record(descriptor, expected_sha256, expected_size)
        if record["identity"]["size_bytes"] <= 0:
            raise B0MaterializationV2Error(
                "EMPTY_INPUT", "materialization input is empty", path=relative
            )
    except BaseException:
        os.close(descriptor)
        os.close(parent_fd)
        raise
    return descriptor, parent_fd


def _copy_stream(source_fd: int, destination_fd: int) -> None:
    offset = 0
    while True:
        chunk = os.pread(source_fd, 1024 * 1024, offset)
        if not chunk:
            break
        view = memoryview(chunk)
        while view:
            written = os.write(destination_fd, view)
            if written <= 0:
                raise B0MaterializationV2Error(
                    "COPY_SHORT_WRITE", "AFRL stream copy made no progress"
                )
            view = view[written:]
        offset += len(chunk)


def _default_bag_inspector(path: Path, recipe: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        from scripts import run_p07_backend_b0_materialization_v1 as legacy_runtime
    except ModuleNotFoundError:
        import run_p07_backend_b0_materialization_v1 as legacy_runtime  # type: ignore
    return legacy_runtime.inspect_rosbag(path, recipe)


def _inspect_retained_legacy_stage(
    stage: RetainedStage,
    recipe: Mapping[str, Any],
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]],
) -> Dict[str, Any]:
    _assert_stage_path_owned(stage)
    os.fsync(stage.descriptor)
    record = _verify_descriptor_record(
        stage.descriptor,
        str(recipe["expected_sha256"]),
        int(recipe["expected_size_bytes"]),
    )
    before = _identity(os.fstat(stage.descriptor))
    bag = _clone(bag_inspector(stage.proc_path, recipe))
    after = _identity(os.fstat(stage.descriptor))
    if before != after:
        raise B0MaterializationV2Error(
            "STAGE_CHANGED_DURING_BAG_INSPECTION",
            "retained stage changed during bag inspection",
        )
    if bag.get("trajectory_values_interpreted") is not False:
        raise B0MaterializationV2Error(
            "TRAJECTORY_BOUNDARY_VIOLATION", "bag inspector interpreted trajectory values"
        )
    return {
        "window_id": recipe["window_id"],
        "target_path": recipe["target_path"],
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
        "stage_identity": record["identity"],
        "bag_integrity": bag,
        "held_out_trajectory_outcome_read": False,
    }


def _inspect_final_record(
    root: Path,
    relative: str,
    *,
    expected_sha256: str,
    expected_size: int,
    recipe: Optional[Mapping[str, Any]] = None,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]] = _default_bag_inspector,
) -> Dict[str, Any]:
    descriptor, parent_fd, _name, _path = _open_readonly(root, relative)
    try:
        record = _verify_descriptor_record(
            descriptor, expected_sha256, int(expected_size)
        )
        bag = None
        if recipe is not None:
            before = _identity(os.fstat(descriptor))
            bag = _clone(bag_inspector(Path("/proc/self/fd/%d" % descriptor), recipe))
            if before != _identity(os.fstat(descriptor)):
                raise B0MaterializationV2Error(
                    "FINAL_CHANGED_DURING_INSPECTION",
                    "final target changed during retained-FD inspection",
                )
        return {
            "path": relative,
            "sha256": record["sha256"],
            "size_bytes": record["size_bytes"],
            "identity": record["identity"],
            "bag_integrity": bag,
        }
    finally:
        os.close(descriptor)
        os.close(parent_fd)


def publish_retained_stage(
    stage: RetainedStage,
    *,
    expected_sha256: str,
    expected_size: int,
    root: Path,
    recipe: Optional[Mapping[str, Any]] = None,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]] = _default_bag_inspector,
    renamer: Callable[[int, str, int, str], None] = _rename_noreplace_at,
    preserve_on_collision: bool = True,
) -> Dict[str, Any]:
    _assert_stage_path_owned(stage)
    try:
        renamer(stage.parent_fd, stage.stage_name, stage.parent_fd, stage.final_name)
    except FileExistsError:
        try:
            winner = _inspect_final_record(
                root,
                stage.target_relative,
                expected_sha256=expected_sha256,
                expected_size=expected_size,
                recipe=recipe,
                bag_inspector=bag_inspector,
            )
        except BaseException as winner_error:
            preserved = None
            if preserve_on_collision:
                preserved = preserve_stage(
                    stage, reason="NONEXACT_CONCURRENT_WINNER", renamer=renamer
                )
            raise B0MaterializationV2Error(
                "FINAL_COLLISION_NOT_EXACT",
                "concurrent final winner is absent or not exact",
                preserved=preserved,
            ) from winner_error
        preserved = None
        if preserve_on_collision:
            preserved = preserve_stage(
                stage, reason="EXACT_CONCURRENT_WINNER", renamer=renamer
            )
        else:
            raise B0MaterializationV2Error(
                "EXACT_WINNER_WITH_RETAINED_STAGE",
                "exact concurrent winner leaves a receipt-bound stage in place",
                stage=stage.stage_relative,
            )
        return {
            "action": "EXACT_CONCURRENT_WINNER",
            "final": winner,
            "preserved_stage": preserved,
        }
    os.fsync(stage.parent_fd)
    state, final_info = _path_state(stage.parent_fd, stage.final_name)
    if state != "FILE" or final_info is None or not _same_inode(
        final_info, stage.create_identity
    ):
        raise B0MaterializationV2Error(
            "FINAL_PUBLICATION_IDENTITY_DRIFT",
            "rename-no-replace final does not name retained stage inode",
        )
    retained = _verify_descriptor_record(
        stage.descriptor, expected_sha256, expected_size
    )
    stage.published = True
    return {
        "action": "RENAMED_NOREPLACE",
        "final": {
            "path": stage.target_relative,
            "sha256": retained["sha256"],
            "size_bytes": retained["size_bytes"],
            "identity": retained["identity"],
            "bag_integrity": None,
        },
        "preserved_stage": None,
    }


def materialize_legacy_unit(
    root: Path,
    lock_payload: Mapping[str, Any],
    unit: Mapping[str, Any],
    *,
    timeout_s: int,
    bag_inspector: Callable[[Path, Mapping[str, Any]], Mapping[str, Any]] = _default_bag_inspector,
    subprocess_runner: Callable[..., Any] = subprocess.run,
    renamer: Callable[[int, str, int, str], None] = _rename_noreplace_at,
) -> Dict[str, Any]:
    if unit.get("kind") != "LEGACY_EXACT_SINGLE_TARGET":
        raise B0MaterializationV2Error(
            "UNIT_KIND_DRIFT", "legacy materialization unit kind differs"
        )
    window_id = str(unit["window_ids"][0])
    entries = {
        str(entry["window_id"]): entry for entry in lock_payload["b0_core_plan"]["entries"]
    }
    entry = entries.get(window_id)
    if entry is None or entry["dataset_family"] == "ntnu":
        raise B0MaterializationV2Error(
            "UNIT_WINDOW_DRIFT", "legacy materialization unit window differs"
        )
    recipe = entry["materialization"]["v1_recipe"]
    target_relative = str(recipe["target_path"])
    expected_sha = str(recipe["expected_sha256"])
    expected_size = int(recipe["expected_size_bytes"])

    parent_fd, final_name, _target = _open_parent(root, target_relative)
    try:
        state, _info = _path_state(parent_fd, final_name)
    finally:
        os.close(parent_fd)
    if state == "FILE":
        existing = _inspect_final_record(
            root,
            target_relative,
            expected_sha256=expected_sha,
            expected_size=expected_size,
            recipe=recipe,
            bag_inspector=bag_inspector,
        )
        return {
            "window_id": window_id,
            "target_path": target_relative,
            "action": "EXACT_RESUME",
            "record": {key: existing[key] for key in ("path", "sha256", "size_bytes")},
            "bag_integrity": existing["bag_integrity"],
            "preserved_stage": None,
            "run_vins": False,
        }
    if state != "ABSENT":
        raise B0MaterializationV2Error(
            "FINAL_TYPE_COLLISION", "legacy final is not absent or a direct file"
        )

    stage = create_retained_stage(
        root, target_relative, window_id, lock_payload[formal_lock.SELF_HASH_FIELD]
    )
    input_descriptors: List[Tuple[int, int]] = []
    completed = None
    try:
        source_size = int(
            recipe["source_path_identity"]["resolved_target_identity"]["size_bytes"]
        )
        source = _open_verified_input(
            root,
            str(recipe["source_raw_path"]),
            str(recipe["source_raw_sha256"]),
            source_size,
        )
        input_descriptors.append(source)
        if recipe["disposition"] == "EXACT_COPY_REQUIRED_OR_RECONCILE":
            _copy_stream(source[0], stage.descriptor)
        else:
            records = {
                str(item["path"]): item
                for item in lock_payload["legacy_recipe_authority"]["input_artifacts"]
            }
            replacements = {
                str(recipe["source_raw_path"]): "/proc/self/fd/%d" % source[0]
            }
            template = recipe["converter_argv_template"]
            if "--gt-txt" in template:
                reference = str(template[template.index("--gt-txt") + 1])
                expected = records.get(reference)
                if expected is None:
                    raise B0MaterializationV2Error(
                        "REFERENCE_NOT_BOUND", "converter reference is not authority-bound"
                    )
                reference_fds = _open_verified_input(
                    root,
                    reference,
                    str(expected["sha256"]),
                    int(expected["size_bytes"]),
                )
                input_descriptors.append(reference_fds)
                replacements[reference] = "/proc/self/fd/%d" % reference_fds[0]
            argv = _converter_argv(recipe, str(stage.proc_path), replacements)
            pass_fds = tuple([stage.descriptor] + [item[0] for item in input_descriptors])
            completed = subprocess_runner(
                argv,
                cwd=root,
                env=_clean_converter_environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=int(timeout_s),
                check=False,
                close_fds=True,
                pass_fds=pass_fds,
            )
            if int(completed.returncode) != 0:
                raise B0MaterializationV2Error(
                    "CONVERTER_FAILED",
                    "AQUALOC converter failed",
                    returncode=int(completed.returncode),
                )
        observation = _inspect_retained_legacy_stage(
            stage, recipe, bag_inspector
        )
        publication = publish_retained_stage(
            stage,
            expected_sha256=expected_sha,
            expected_size=expected_size,
            root=root,
            recipe=recipe,
            bag_inspector=bag_inspector,
            renamer=renamer,
        )
        output = getattr(completed, "stdout", b"") or b""
        return {
            "window_id": window_id,
            "target_path": target_relative,
            "action": publication["action"],
            "record": {
                "path": target_relative,
                "sha256": observation["sha256"],
                "size_bytes": observation["size_bytes"],
            },
            "bag_integrity": observation["bag_integrity"],
            "preserved_stage": publication["preserved_stage"],
            "converter_stdout_sha256": hashlib.sha256(output).hexdigest(),
            "converter_stdout_size_bytes": len(output),
            "run_vins": False,
        }
    except BaseException as error:
        if isinstance(error, SimulatedCrash):
            raise
        if not stage.published and not stage.preserved:
            try:
                preserved = preserve_stage(
                    stage, reason=getattr(error, "code", type(error).__name__), renamer=renamer
                )
                if isinstance(error, B0MaterializationV2Error):
                    error.details.setdefault("preserved_stage", preserved)
            except BaseException as preserve_error:
                if isinstance(error, B0MaterializationV2Error):
                    error.details.setdefault("preservation_error", repr(preserve_error))
        raise
    finally:
        for descriptor, parent in input_descriptors:
            os.close(descriptor)
            os.close(parent)
        stage.close()


def publish_exact_bytes(
    root: Path,
    relative: str,
    content: bytes,
    *,
    event_hook: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    relative = _safe_relative(relative, "artifact")
    if formal_io.destination_exists(root, relative):
        existing, _identity_value = formal_io.read_direct_bytes(root, relative)
        if existing != content:
            raise B0MaterializationV2Error(
                "ARTIFACT_COLLISION_NOT_EXACT",
                "existing artifact bytes differ",
                path=relative,
            )
        if event_hook is not None:
            event_hook("exact_resume", relative)
        return _record_for_bytes(relative, content)
    try:
        record = formal_io.publish_bytes_no_clobber(root, relative, content)
    except FileExistsError:
        existing, _identity_value = formal_io.read_direct_bytes(root, relative)
        if existing != content:
            raise B0MaterializationV2Error(
                "ARTIFACT_RACE_NOT_EXACT", "artifact race winner differs", path=relative
            )
        record = _record_for_bytes(relative, content)
    if record != _record_for_bytes(relative, content):
        raise B0MaterializationV2Error(
            "ARTIFACT_RECORD_DRIFT", "published artifact record differs", path=relative
        )
    if event_hook is not None:
        event_hook("published", relative)
    return record


def publish_exact_json(
    root: Path,
    relative: str,
    payload: Mapping[str, Any],
    *,
    event_hook: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    return publish_exact_bytes(
        root, relative, _json_bytes(payload), event_hook=event_hook
    )


def load_exact_json(root: Path, relative: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        content, _identity_value = formal_io.read_direct_bytes(root, relative)
        value = json.loads(content)
    except (OSError, ValueError, TypeError) as error:
        raise B0MaterializationV2Error(
            "ARTIFACT_READ_FAILED", "cannot load exact JSON artifact", path=relative
        ) from error
    if not isinstance(value, dict):
        raise B0MaterializationV2Error(
            "ARTIFACT_SCHEMA_DRIFT", "JSON artifact is not an object", path=relative
        )
    return value, _record_for_bytes(relative, content)


def _runtime_source_records(root: Path) -> List[Dict[str, Any]]:
    records = []
    for relative in (RUNTIME_RELATIVE, TEST_RELATIVE, LEGACY_INSPECTOR_RELATIVE):
        content, _identity_value = formal_io.read_direct_bytes(root, relative)
        records.append(_record_for_bytes(relative, content))
    return sorted(records, key=lambda item: item["path"])


def _formal_lock_record(root: Path, content: bytes) -> Dict[str, Any]:
    return _record_for_bytes(FORMAL_LOCK_RELATIVE, content)


def load_and_validate_formal_lock(
    *, root: Path = ROOT, require_runtime_sources: bool = True
) -> Tuple[Dict[str, Any], Dict[str, Any], Mapping[str, Any]]:
    try:
        content, _identity_value = formal_io.read_direct_bytes(root, FORMAL_LOCK_RELATIVE)
        payload = json.loads(content)
    except (OSError, ValueError, TypeError) as error:
        raise B0MaterializationV2Error(
            "FORMAL_LOCK_ABSENT_OR_INVALID", "formal B0-v2 lock is unavailable"
        ) from error
    if not isinstance(payload, dict):
        raise B0MaterializationV2Error(
            "FORMAL_LOCK_SCHEMA_DRIFT", "formal B0-v2 lock is not an object"
        )
    queue = b0.load_live_queue_authority(root=root)
    try:
        formal_lock.validate_lock_payload(
            payload,
            frozen_queue_authority=queue,
            external_legacy_authority=payload["legacy_recipe_authority"],
            external_adoption_binding=payload["formalization_adoption"],
            external_review_evidence_binding=payload["formalization_review_evidence"],
            external_hf_correction_binding=payload["hf_checksum_semantics_correction"],
            external_source_bindings=payload["source_bindings"],
            root=root,
            verify_sources=True,
            verify_live_authorities=True,
        )
    except Exception as error:
        raise B0MaterializationV2Error(
            "FORMAL_LOCK_VALIDATION_FAILED", "formal B0-v2 lock validation failed"
        ) from error
    if require_runtime_sources:
        bound = {str(item["path"]): item for item in payload["source_bindings"]}
        missing = [path for path in EXECUTION_REQUIRED_SOURCE_PATHS if path not in bound]
        if missing:
            raise B0MaterializationV2Error(
                "RUNTIME_SOURCES_NOT_FORMALLY_BOUND",
                "formal lock does not bind the execution implementation closure",
                missing=missing,
            )
        for observed in _runtime_source_records(root):
            if bound.get(observed["path"]) != observed:
                raise B0MaterializationV2Error(
                    "RUNTIME_SOURCE_IDENTITY_DRIFT",
                    "runtime source differs from formal lock",
                    path=observed["path"],
                )
    return payload, _formal_lock_record(root, content), queue


def _assert_run_vins_zero(environment: Mapping[str, str] = os.environ) -> None:
    if environment.get("RUN_VINS", "0") != "0":
        raise B0MaterializationV2Error(
            "RUN_VINS_NOT_ZERO", "RUN_VINS must be exactly zero"
        )


def _live_process_conflicts(proc_root: Path = Path("/proc")) -> List[Dict[str, Any]]:
    conflicts = []
    own = os.getpid()
    try:
        entries = list(proc_root.iterdir())
    except OSError as error:
        raise B0MaterializationV2Error(
            "PROC_UNAVAILABLE", "cannot inspect process quiescence"
        ) from error
    for entry in entries:
        if not entry.name.isdigit() or int(entry.name) == own:
            continue
        try:
            content = (entry / "cmdline").read_bytes()
        except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
            continue
        command = content.replace(b"\x00", b" ").decode("utf-8", "replace").strip()
        if any(token in command for token in _PROC_BLOCKLIST):
            conflicts.append({"pid": int(entry.name), "command": command})
    return conflicts


def _check_capacity(lock_payload: Mapping[str, Any], root: Path) -> Dict[str, int]:
    required = int(lock_payload["capacity"]["required_free_bytes"])
    free = int(shutil.disk_usage(root).free)
    if free < required:
        raise B0MaterializationV2Error(
            "CAPACITY_GATE_FAILED",
            "free space is below formal materialization bound",
            required_free_bytes=required,
            observed_free_bytes=free,
        )
    return {"required_free_bytes": required, "observed_free_bytes": free}


def _stage_relatives(lock_payload: Mapping[str, Any]) -> List[str]:
    lock_hash = str(lock_payload[formal_lock.SELF_HASH_FIELD])
    result = []
    for entry in lock_payload["b0_core_plan"]["entries"]:
        result.append(
            deterministic_stage_relative(
                str(entry["target"]["path"]), str(entry["window_id"]), lock_hash
            )
        )
    return result


def _check_orphan_stages(root: Path, lock_payload: Mapping[str, Any]) -> None:
    receipt_exists = formal_io.destination_exists(root, NTNU_STAGE_RECEIPT_RELATIVE)
    ntnu_windows = {
        str(entry["window_id"])
        for entry in lock_payload["b0_core_plan"]["entries"]
        if entry["dataset_family"] == "ntnu"
    }
    for entry in lock_payload["b0_core_plan"]["entries"]:
        stage_relative = deterministic_stage_relative(
            str(entry["target"]["path"]),
            str(entry["window_id"]),
            str(lock_payload[formal_lock.SELF_HASH_FIELD]),
        )
        parent_fd, name, _path = _open_parent(root, stage_relative)
        try:
            state, _info = _path_state(parent_fd, name)
        finally:
            os.close(parent_fd)
        if state == "OTHER":
            raise B0MaterializationV2Error(
                "STAGE_TYPE_COLLISION", "deterministic stage is not a direct file"
            )
        if state == "FILE" and (
            str(entry["window_id"]) not in ntnu_windows or not receipt_exists
        ):
            raise B0MaterializationV2Error(
                "ORPHAN_STAGE_WITHOUT_RECEIPT",
                "deterministic stage exists without an exact resumable receipt",
                path=stage_relative,
            )


def build_intent_payload(
    lock_payload: Mapping[str, Any],
    lock_record: Mapping[str, Any],
    *,
    started_at: str,
    runtime_sources: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    return _finish(
        {
            "schema_version": INTENT_SCHEMA,
            "status": "DURABLE_NO_CLOBBER_INTENT_BEFORE_ANY_STAGE",
            "started_at": _timestamp(started_at, "started_at"),
            "formal_lock": _clone(lock_record),
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "runtime_sources": sorted(_clone(runtime_sources), key=lambda item: item["path"]),
            "policy": {
                "deterministic_stage_names": True,
                "exclusive_nofollow_stage_create": True,
                "retained_stage_descriptors": True,
                "renameat2_noreplace_only": True,
                "name_based_stage_unlink_forbidden": True,
                "failed_stage_preserve_or_leave_in_place": True,
                "ntnu_stage_receipt_before_final_rename": True,
                "closeout_commit_last": True,
                "run_vins": False,
            },
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        INTENT_HASH_FIELD,
    )


def validate_intent_payload(
    payload: Mapping[str, Any],
    lock_payload: Mapping[str, Any],
    lock_record: Mapping[str, Any],
    *,
    started_at: str,
    runtime_sources: Sequence[Mapping[str, Any]],
) -> str:
    expected = build_intent_payload(
        lock_payload,
        lock_record,
        started_at=started_at,
        runtime_sources=runtime_sources,
    )
    if _clone(payload) != expected:
        raise B0MaterializationV2Error(
            "INTENT_DRIFT", "durable materialization intent differs"
        )
    return str(expected[INTENT_HASH_FIELD])


def ensure_durable_intent(
    root: Path,
    lock_payload: Mapping[str, Any],
    lock_record: Mapping[str, Any],
    *,
    started_at: str,
    runtime_sources: Sequence[Mapping[str, Any]],
    event_hook: Optional[Callable[[str, str], None]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    intent = build_intent_payload(
        lock_payload,
        lock_record,
        started_at=started_at,
        runtime_sources=runtime_sources,
    )
    record = publish_exact_json(
        root, INTENT_RELATIVE, intent, event_hook=event_hook
    )
    loaded, loaded_record = load_exact_json(root, INTENT_RELATIVE)
    validate_intent_payload(
        loaded,
        lock_payload,
        lock_record,
        started_at=started_at,
        runtime_sources=runtime_sources,
    )
    if loaded_record != record:
        raise B0MaterializationV2Error(
            "INTENT_RECORD_DRIFT", "durable intent record differs after publication"
        )
    return loaded, loaded_record


def _validate_ntnu_fanout_against_lock(
    fanout_receipt: Mapping[str, Any], group: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    if (
        fanout_receipt.get("reader_traversal_count") != 1
        or fanout_receipt.get("final_paths_published") is not False
        or fanout_receipt.get("ros_or_vins_started") is not False
        or fanout_receipt.get("held_out_trajectory_outcome_read") is not False
    ):
        raise B0MaterializationV2Error(
            "NTNU_FANOUT_POLICY_DRIFT", "fanout receipt violates runtime boundary"
        )
    expected = {str(item["window_id"]): item for item in group["windows"]}
    observations = fanout_receipt.get("observations")
    if not isinstance(observations, list) or len(observations) != 3:
        raise B0MaterializationV2Error(
            "NTNU_FANOUT_COVERAGE_DRIFT", "fanout receipt does not contain three windows"
        )
    normalized = []
    for observation in observations:
        window_id = str(observation.get("window_id"))
        contract = expected.get(window_id)
        if contract is None:
            raise B0MaterializationV2Error(
                "NTNU_FANOUT_WINDOW_DRIFT", "fanout emitted an unknown window"
            )
        expected_output = contract["expected_output"]
        camera = str(expected_output["camera_topic"])
        bag = observation.get("bag_integrity")
        if (
            observation.get("topic_counts") != expected_output["topic_counts"]
            or not isinstance(bag, Mapping)
            or bag.get("header_stamp_ranges_ns", {}).get(camera)
            != expected_output["camera_header_evaluation_bounds_ns"]
            or bag.get("trajectory_values_interpreted") is not False
        ):
            raise B0MaterializationV2Error(
                "NTNU_FANOUT_SCIENCE_DRIFT", "fanout observation differs from frozen contract"
            )
        normalized.append(_clone(observation))
    if {item["window_id"] for item in normalized} != set(expected):
        raise B0MaterializationV2Error(
            "NTNU_FANOUT_COVERAGE_DRIFT", "fanout window coverage differs"
        )
    return sorted(normalized, key=lambda item: item["window_id"])


def build_ntnu_stage_receipt(
    lock_payload: Mapping[str, Any],
    intent: Mapping[str, Any],
    fanout_receipt: Mapping[str, Any],
    group: Mapping[str, Any],
) -> Dict[str, Any]:
    observations = _validate_ntnu_fanout_against_lock(fanout_receipt, group)
    return _finish(
        {
            "schema_version": NTNU_STAGE_RECEIPT_SCHEMA,
            "status": "EXACT_THREE_STAGES_DURABLE_BEFORE_ANY_FINAL_RENAME",
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "materialization_intent_hash": intent[INTENT_HASH_FIELD],
            "fanout_receipt": _clone(fanout_receipt),
            "stage_observations": observations,
            "reader_traversal_count": 1,
            "final_rename_count_at_receipt": 0,
            "run_vins": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        NTNU_STAGE_RECEIPT_HASH_FIELD,
    )


def validate_ntnu_stage_receipt(
    payload: Mapping[str, Any],
    lock_payload: Mapping[str, Any],
    intent: Mapping[str, Any],
    group: Mapping[str, Any],
) -> str:
    fanout_receipt = payload.get("fanout_receipt") if isinstance(payload, Mapping) else None
    if not isinstance(fanout_receipt, Mapping):
        raise B0MaterializationV2Error(
            "NTNU_STAGE_RECEIPT_DRIFT", "stage receipt lacks fanout receipt"
        )
    expected = build_ntnu_stage_receipt(
        lock_payload, intent, fanout_receipt, group
    )
    if _clone(payload) != expected:
        raise B0MaterializationV2Error(
            "NTNU_STAGE_RECEIPT_DRIFT", "NTNU stage receipt differs"
        )
    return str(expected[NTNU_STAGE_RECEIPT_HASH_FIELD])


def _ntnu_group(lock_payload: Mapping[str, Any]) -> Mapping[str, Any]:
    groups = [
        item
        for item in lock_payload["materialization_units"]
        if item["kind"] == "NTNU_SINGLE_TRAVERSAL_THREE_WINDOW_FANOUT"
    ]
    if len(groups) != 1:
        raise B0MaterializationV2Error(
            "NTNU_GROUP_DRIFT", "formal lock does not contain one NTNU group"
        )
    return groups[0]


def _stage_exists(root: Path, relative: str) -> bool:
    parent_fd, name, _path = _open_parent(root, relative)
    try:
        state, _info = _path_state(parent_fd, name)
    finally:
        os.close(parent_fd)
    if state == "OTHER":
        raise B0MaterializationV2Error(
            "STAGE_TYPE_COLLISION", "stage path is not a direct regular file"
        )
    return state == "FILE"


def _retained_existing_stage(
    root: Path,
    target_relative: str,
    stage_relative: str,
    window_id: str,
    lock_hash: str,
) -> RetainedStage:
    expected = deterministic_stage_relative(target_relative, window_id, lock_hash)
    if stage_relative != expected:
        raise B0MaterializationV2Error(
            "STAGE_NAME_DRIFT", "receipt stage path is not deterministic"
        )
    descriptor, parent_fd, name, _path = _open_readonly(root, stage_relative)
    info = os.fstat(descriptor)
    return RetainedStage(
        window_id=window_id,
        target_relative=target_relative,
        stage_relative=stage_relative,
        preserved_relative=deterministic_preserved_relative(
            target_relative, window_id, lock_hash
        ),
        parent_fd=parent_fd,
        stage_name=name,
        final_name=PurePosixPath(target_relative).name,
        preserved_name=PurePosixPath(
            deterministic_preserved_relative(target_relative, window_id, lock_hash)
        ).name,
        descriptor=descriptor,
        create_identity=_identity(info),
    )


def materialize_ntnu_group(
    root: Path,
    lock_payload: Mapping[str, Any],
    intent: Mapping[str, Any],
    *,
    fanout_callable: Callable[..., Mapping[str, Any]] = ntnu_fanout.materialize_ntnu_windows,
    renamer: Callable[[int, str, int, str], None] = _rename_noreplace_at,
    event_hook: Optional[Callable[[str, str], None]] = None,
    crash_hook: Optional[Callable[[str, Optional[str]], None]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    group = _ntnu_group(lock_payload)
    lock_hash = str(lock_payload[formal_lock.SELF_HASH_FIELD])
    target_by_window = {
        str(item["window_id"]): str(item["target_path"]) for item in group["windows"]
    }
    stage_by_window = {
        window_id: deterministic_stage_relative(target, window_id, lock_hash)
        for window_id, target in target_by_window.items()
    }
    receipt_exists = formal_io.destination_exists(root, NTNU_STAGE_RECEIPT_RELATIVE)
    if receipt_exists:
        stage_receipt, stage_receipt_record = load_exact_json(
            root, NTNU_STAGE_RECEIPT_RELATIVE
        )
        validate_ntnu_stage_receipt(stage_receipt, lock_payload, intent, group)
    else:
        orphans = [path for path in stage_by_window.values() if _stage_exists(root, path)]
        if orphans:
            raise B0MaterializationV2Error(
                "ORPHAN_STAGE_WITHOUT_RECEIPT",
                "NTNU deterministic stages exist without a durable receipt",
                paths=orphans,
            )
        effective = {
            str(item["path"]): item for item in lock_payload["effective_checksum_records"]
        }
        source_contract = effective.get(str(group["source_path"]))
        if source_contract is None:
            raise B0MaterializationV2Error(
                "NTNU_SOURCE_NOT_BOUND", "NTNU source lacks effective content authority"
            )
        source_fd, source_parent = _open_verified_input(
            root,
            str(group["source_path"]),
            str(source_contract["effective_content_sha256"]),
            int(source_contract["size_bytes"]),
        )
        try:
            windows = [
                ntnu_fanout.RecordWindow(
                    str(item["window_id"]),
                    int(item["selection"]["start_offset_ns"]),
                    int(item["selection"]["end_offset_ns"]),
                )
                for item in group["windows"]
            ]
            fanout_paths = {
                window_id: root.absolute() / relative
                for window_id, relative in stage_by_window.items()
            }
            fanout_receipt = _clone(fanout_callable(
                "/proc/self/fd/%d" % source_fd,
                windows,
                fanout_paths,
                topics=(b0.NTNU_CAMERA_TOPIC, b0.NTNU_IMU_TOPIC),
            ))
            for observation in fanout_receipt.get("observations", []):
                window_id = str(observation.get("window_id"))
                expected_absolute = os.path.abspath(
                    os.fspath(fanout_paths.get(window_id, root / "__unknown__"))
                )
                if os.path.abspath(str(observation.get("staged_path", ""))) != expected_absolute:
                    raise B0MaterializationV2Error(
                        "NTNU_STAGE_PATH_DRIFT",
                        "fanout did not return the exact caller-owned stage path",
                    )
                observation["staged_path"] = stage_by_window[window_id]
        finally:
            os.close(source_fd)
            os.close(source_parent)
        stage_receipt = build_ntnu_stage_receipt(
            lock_payload, intent, fanout_receipt, group
        )
        stage_receipt_record = publish_exact_json(
            root,
            NTNU_STAGE_RECEIPT_RELATIVE,
            stage_receipt,
            event_hook=event_hook,
        )
        if crash_hook is not None:
            crash_hook("after_stage_receipt", None)

    observations_by_window = {
        str(item["window_id"]): item for item in stage_receipt["stage_observations"]
    }
    results = []
    for window_id in sorted(target_by_window):
        target = target_by_window[window_id]
        expected = observations_by_window[window_id]
        stage_relative = str(expected["staged_path"])
        if stage_relative != stage_by_window[window_id]:
            raise B0MaterializationV2Error(
                "NTNU_STAGE_PATH_DRIFT", "fanout stage path differs from deterministic path"
            )
        final_parent, final_name, _path = _open_parent(root, target)
        try:
            final_state, _final_info = _path_state(final_parent, final_name)
        finally:
            os.close(final_parent)
        stage_present = _stage_exists(root, stage_relative)
        if final_state == "FILE" and not stage_present:
            final = _inspect_final_record(
                root,
                target,
                expected_sha256=str(expected["sha256"]),
                expected_size=int(expected["size_bytes"]),
            )
            action = "EXACT_CRASH_RESUME"
        elif final_state == "ABSENT" and stage_present:
            stage = _retained_existing_stage(
                root, target, stage_relative, window_id, lock_hash
            )
            try:
                identity = expected["stage_file_identity"]
                if not _same_inode(os.fstat(stage.descriptor), identity):
                    raise B0MaterializationV2Error(
                        "NTNU_STAGE_IDENTITY_DRIFT", "NTNU stage inode differs from receipt"
                    )
                _verify_descriptor_record(
                    stage.descriptor,
                    str(expected["sha256"]),
                    int(expected["size_bytes"]),
                )
                publication = publish_retained_stage(
                    stage,
                    expected_sha256=str(expected["sha256"]),
                    expected_size=int(expected["size_bytes"]),
                    root=root,
                    renamer=renamer,
                    preserve_on_collision=False,
                )
                final = publication["final"]
                action = publication["action"]
            finally:
                stage.close()
        else:
            raise B0MaterializationV2Error(
                "NTNU_PARTIAL_STATE_NOT_RESUMABLE",
                "NTNU final/stage state is not an exact crash-resume state",
                window_id=window_id,
                final_state=final_state,
                stage_present=stage_present,
            )
        results.append(
            {
                "window_id": window_id,
                "target_path": target,
                "action": action,
                "record": {
                    "path": target,
                    "sha256": final["sha256"],
                    "size_bytes": final["size_bytes"],
                },
                "bag_integrity": expected["bag_integrity"],
                "preserved_stage": None,
                "run_vins": False,
            }
        )
        if crash_hook is not None:
            crash_hook("after_final_rename", window_id)
    return results, stage_receipt, stage_receipt_record


def build_materialization_receipt(
    lock_payload: Mapping[str, Any],
    intent: Mapping[str, Any],
    intent_record: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    *,
    completed_at: str,
    ntnu_stage_receipt_record: Mapping[str, Any],
) -> Dict[str, Any]:
    ordered = sorted(_clone(observations), key=lambda item: item["window_id"])
    if len(ordered) != 20 or len({item["window_id"] for item in ordered}) != 20:
        raise B0MaterializationV2Error(
            "MATERIALIZATION_COVERAGE_DRIFT", "receipt requires exactly twenty windows"
        )
    return _finish(
        {
            "schema_version": RECEIPT_SCHEMA,
            "status": "ALL_20_B0_INPUTS_EXACT_MATERIALIZATION_ONLY",
            "completed_at": _timestamp(completed_at, "completed_at"),
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "materialization_intent": _clone(intent_record),
            "materialization_intent_hash": intent[INTENT_HASH_FIELD],
            "ntnu_stage_receipt": _clone(ntnu_stage_receipt_record),
            "observations": ordered,
            "window_count": 20,
            "run_vins": False,
            "ros_replay_started": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        RECEIPT_HASH_FIELD,
    )


def build_play_inputs_payload(
    lock_payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_record: Mapping[str, Any],
) -> Dict[str, Any]:
    records = {
        str(item["window_id"]): _clone(item["record"])
        for item in receipt["observations"]
    }
    entries = []
    for entry in lock_payload["b0_core_plan"]["entries"]:
        window_id = str(entry["window_id"])
        record = records[window_id]
        if record["path"] != entry["target"]["path"]:
            raise B0MaterializationV2Error(
                "PLAY_INPUT_PATH_DRIFT", "receipt path differs from core target"
            )
        entries.append(
            {
                "window_id": window_id,
                "dataset_family": entry["dataset_family"],
                "path": record["path"],
                "sha256": record["sha256"],
                "size_bytes": record["size_bytes"],
            }
        )
    return _finish(
        {
            "schema_version": PLAY_INPUTS_SCHEMA,
            "status": "B0_PLAY_INPUT_IDENTITIES_ONLY_NO_REPLAY_AUTHORITY",
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "materialization_receipt": _clone(receipt_record),
            "materialization_receipt_hash": receipt[RECEIPT_HASH_FIELD],
            "entries": sorted(entries, key=lambda item: item["window_id"]),
            "queue_bindings": _clone(lock_payload["b0_core_plan"]["preparation_mappings"]),
            "window_count": 20,
            "queue_binding_count": 240,
            "backend_replay_authorized": False,
            "run_vins": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        PLAY_INPUTS_HASH_FIELD,
    )


def _resolve_actual_core(
    lock_payload: Mapping[str, Any], receipt: Mapping[str, Any]
) -> Dict[str, Any]:
    pre = _clone(lock_payload["actual_consumed_pre_materialization_core"])
    observations = {
        str(item["record"]["path"]): item["record"] for item in receipt["observations"]
    }
    objects = {
        str(item["content_object_id"]): item for item in pre["content_objects"]
    }
    resolved_count = 0
    for location in pre["path_locations"]:
        if location["content_object_id"] is not None:
            continue
        record = observations.get(str(location["path"]))
        if record is None:
            raise B0MaterializationV2Error(
                "UNRESOLVED_LOCATION_MISSING", "unresolved location lacks final observation"
            )
        digest = str(record["sha256"])
        object_id = actual._content_object_id(str(location["content_type"]), digest)
        location["content_object_id"] = object_id
        location["sha256"] = digest
        location["size_bytes"] = int(record["size_bytes"])
        location["identity_status"] = "EXACT_POST_MATERIALIZATION_SHA256"
        objects.setdefault(
            object_id,
            {
                "content_object_id": object_id,
                "content_type": location["content_type"],
                "sha256": digest,
            },
        )
        resolved_count += 1
    if resolved_count != 3:
        raise B0MaterializationV2Error(
            "UNRESOLVED_LOCATION_COUNT_DRIFT", "exactly three NTNU locations must resolve"
        )
    pre["content_objects"] = sorted(
        objects.values(), key=lambda item: item["content_object_id"]
    )
    pre["content_object_count"] = len(pre["content_objects"])
    pre["unresolved_content_location_count"] = 0
    pre.pop(actual.SELF_HASH_FIELD, None)
    return pre


def build_resolved_actual_payload(
    lock_payload: Mapping[str, Any],
    receipt: Mapping[str, Any],
    receipt_record: Mapping[str, Any],
) -> Dict[str, Any]:
    resolved = _resolve_actual_core(lock_payload, receipt)
    return _finish(
        {
            "schema_version": RESOLVED_ACTUAL_SCHEMA,
            "status": "ALL_ACTUAL_CONSUMED_PATHS_CONTENT_RESOLVED_NO_EXECUTION_AUTHORITY",
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "materialization_receipt": _clone(receipt_record),
            "materialization_receipt_hash": receipt[RECEIPT_HASH_FIELD],
            "resolved_actual_consumed_core": resolved,
            "counts": {
                "content_object_count": resolved["content_object_count"],
                "path_location_count": resolved["path_location_count"],
                "cell_count": resolved["cell_count"],
                "queue_binding_count": resolved["queue_binding_count"],
                "unresolved_content_location_count": 0,
            },
            "execution_authorized": False,
            "run_vins": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        RESOLVED_ACTUAL_HASH_FIELD,
    )


def build_closeout_payload(
    lock_payload: Mapping[str, Any],
    *,
    committed_at: str,
    receipt_record: Mapping[str, Any],
    play_record: Mapping[str, Any],
    resolved_record: Mapping[str, Any],
) -> Dict[str, Any]:
    return _finish(
        {
            "schema_version": CLOSEOUT_SCHEMA,
            "status": "COMMITTED_LAST_ALL_20_EXACT_MATERIALIZATION_ONLY",
            "committed_at": _timestamp(committed_at, "committed_at"),
            "formal_lock_self_hash": lock_payload[formal_lock.SELF_HASH_FIELD],
            "materialization_receipt": _clone(receipt_record),
            "play_inputs": _clone(play_record),
            "resolved_actual_consumed": _clone(resolved_record),
            "commit_order": [
                RECEIPT_RELATIVE,
                PLAY_INPUTS_RELATIVE,
                RESOLVED_ACTUAL_RELATIVE,
                CLOSEOUT_RELATIVE,
            ],
            "backend_replay_authorized": False,
            "run_vins": False,
            "held_out_trajectory_outcome_read": False,
            "outcome_boundary": OUTCOME_BOUNDARY,
        },
        CLOSEOUT_HASH_FIELD,
    )


def execute_transaction_core(
    lock_payload: Mapping[str, Any],
    lock_record: Mapping[str, Any],
    *,
    started_at: str,
    completed_at: str,
    committed_at: str,
    root: Path = ROOT,
    timeout_s: int = 3600,
    runtime_sources: Optional[Sequence[Mapping[str, Any]]] = None,
    legacy_materializer: Callable[..., Mapping[str, Any]] = materialize_legacy_unit,
    ntnu_materializer: Callable[..., Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]] = materialize_ntnu_group,
    event_hook: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    _assert_run_vins_zero()
    if lock_payload.get("policy", {}).get("run_vins") is not False:
        raise B0MaterializationV2Error(
            "LOCK_RUN_VINS_POLICY_DRIFT", "formal lock does not force RUN_VINS=0"
        )
    sources = list(runtime_sources or _runtime_source_records(root))
    intent, intent_record = ensure_durable_intent(
        root,
        lock_payload,
        lock_record,
        started_at=started_at,
        runtime_sources=sources,
        event_hook=event_hook,
    )
    if event_hook is not None:
        event_hook("intent_durable", INTENT_RELATIVE)

    observations = []
    legacy_units = [
        unit
        for unit in lock_payload["materialization_units"]
        if unit["kind"] == "LEGACY_EXACT_SINGLE_TARGET"
    ]
    for unit in legacy_units:
        observations.append(
            _clone(
                legacy_materializer(
                    root,
                    lock_payload,
                    unit,
                    timeout_s=timeout_s,
                )
            )
        )
    ntnu_observations, _stage_receipt, stage_receipt_record = ntnu_materializer(
        root, lock_payload, intent
    )
    observations.extend(_clone(ntnu_observations))
    receipt = build_materialization_receipt(
        lock_payload,
        intent,
        intent_record,
        observations,
        completed_at=completed_at,
        ntnu_stage_receipt_record=stage_receipt_record,
    )
    receipt_record = publish_exact_json(
        root, RECEIPT_RELATIVE, receipt, event_hook=event_hook
    )
    play = build_play_inputs_payload(lock_payload, receipt, receipt_record)
    play_record = publish_exact_json(
        root, PLAY_INPUTS_RELATIVE, play, event_hook=event_hook
    )
    resolved = build_resolved_actual_payload(lock_payload, receipt, receipt_record)
    resolved_record = publish_exact_json(
        root, RESOLVED_ACTUAL_RELATIVE, resolved, event_hook=event_hook
    )
    closeout = build_closeout_payload(
        lock_payload,
        committed_at=committed_at,
        receipt_record=receipt_record,
        play_record=play_record,
        resolved_record=resolved_record,
    )
    closeout_record = publish_exact_json(
        root, CLOSEOUT_RELATIVE, closeout, event_hook=event_hook
    )
    return {
        "status": closeout["status"],
        "closeout": closeout,
        "closeout_record": closeout_record,
        "run_vins": False,
        "trajectory_outcome_read": False,
    }


def preflight(*, root: Path = ROOT) -> Dict[str, Any]:
    _assert_run_vins_zero()
    payload, record, _queue = load_and_validate_formal_lock(root=root)
    conflicts = _live_process_conflicts()
    if conflicts:
        raise B0MaterializationV2Error(
            "PROCESS_QUIESCENCE_GATE_FAILED",
            "ROS/VINS or conflicting materializer processes are live",
            conflicts=conflicts,
        )
    capacity = _check_capacity(payload, root)
    _check_orphan_stages(root, payload)
    return {
        "status": "READY_FOR_EXPLICIT_MATERIALIZATION_ONLY",
        "formal_lock": record,
        "formal_lock_self_hash": payload[formal_lock.SELF_HASH_FIELD],
        "capacity": capacity,
        "process_conflicts": [],
        "run_vins": False,
        "backend_replay_authorized": False,
        "trajectory_outcome_read": False,
    }


def preflight_report(*, root: Path = ROOT) -> Dict[str, Any]:
    try:
        report = preflight(root=root)
    except B0MaterializationV2Error as error:
        report = error.block()
    if not CLI_EXECUTION_IMPLEMENTED:
        report = {
            **report,
            "status": STATUS_BLOCKED,
            "execute_available": False,
            "required_formal_source_bindings": list(EXECUTION_REQUIRED_SOURCE_PATHS),
        }
    return report


def execute_cli_blocked(*, root: Path = ROOT) -> Dict[str, Any]:
    report = preflight_report(root=root)
    raise B0MaterializationV2Error(
        "CLI_EXECUTION_NOT_FORMALLY_SOURCE_BOUND",
        "--execute remains blocked until a formal lock binds this runtime/test closure",
        preflight=report,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--preflight", action="store_true")
    actions.add_argument("--execute", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    if not args.execute:
        print(json.dumps(preflight_report(root=args.root), indent=2, sort_keys=True))
        return 0
    try:
        execute_cli_blocked(root=args.root)
    except B0MaterializationV2Error as error:
        print(json.dumps(error.block(), indent=2, sort_keys=True))
        return 2
    return 2


__all__ = [
    "B0MaterializationV2Error",
    "CLI_EXECUTION_IMPLEMENTED",
    "CLOSEOUT_RELATIVE",
    "INTENT_RELATIVE",
    "NTNU_STAGE_RECEIPT_RELATIVE",
    "PLAY_INPUTS_RELATIVE",
    "RECEIPT_RELATIVE",
    "RESOLVED_ACTUAL_RELATIVE",
    "RetainedStage",
    "SimulatedCrash",
    "build_closeout_payload",
    "build_intent_payload",
    "build_materialization_receipt",
    "build_ntnu_stage_receipt",
    "build_play_inputs_payload",
    "build_resolved_actual_payload",
    "canonical_json",
    "create_retained_stage",
    "deterministic_preserved_relative",
    "deterministic_stage_relative",
    "document_hash",
    "ensure_durable_intent",
    "execute_transaction_core",
    "load_and_validate_formal_lock",
    "main",
    "materialize_legacy_unit",
    "materialize_ntnu_group",
    "preflight",
    "preflight_report",
    "preserve_stage",
    "publish_exact_bytes",
    "publish_exact_json",
    "publish_retained_stage",
    "validate_intent_payload",
    "validate_ntnu_stage_receipt",
]


if __name__ == "__main__":
    raise SystemExit(main())
