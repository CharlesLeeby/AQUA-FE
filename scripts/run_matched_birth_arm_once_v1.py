#!/usr/bin/env python3
"""Launch exactly one frozen matched detector-birth producer process.

This is an additive supervision boundary for the matched XFeat/GFTT birth
experiment.  It deliberately does not import either producer.  A permanent
start receipt is claimed before semantic command validation, and a distinct
return-code receipt is claimed only after the one child process has ended.
Neither receipt is ever removed or replaced.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence


WORKING_DIRECTORY = Path("/home/ma/AQUA-FE_WS")
PYTHON_EXECUTABLE = "/usr/bin/python3.8"
PYCACHE_PREFIX = Path(
    "/tmp/aqua-fe-a02-matched-birth-rawlk-empty-pycache-v1"
)

ARM_ENTRYPOINTS = {
    "XFEAT_BIRTH_RAWLK_MATCHED_V1": (
        "scripts.export_matched_xfeat_birth_rawlk_v1"
    ),
    "GFTT_BIRTH_RAWLK_MATCHED_V1": (
        "scripts.export_matched_gftt_birth_rawlk_v1"
    ),
}

FROZEN_ENVIRONMENT = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "SHELL": "/bin/bash",
    "PATH": (
        "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:"
        "/usr/sbin:/usr/bin:/sbin:/bin"
    ),
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONPATH": (
        "/home/ma/AQUA-FE_WS:"
        "/home/ma/.local/lib/python3.8/site-packages:"
        "/opt/ros/noetic/lib/python3/dist-packages"
    ),
    "PYTHONNOUSERSITE": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPYCACHEPREFIX": str(PYCACHE_PREFIX),
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "CUDA_VISIBLE_DEVICES": "",
    "LD_LIBRARY_PATH": (
        "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:"
        "/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu"
    ),
}

COMMAND_CONTRACT_SCHEMA = "aqua-fe-matched-birth-sealed-command-v1"
START_RECEIPT_SCHEMA = "aqua-fe-matched-birth-launch-start-receipt-v2"
RC_RECEIPT_SCHEMA = "aqua-fe-matched-birth-launch-rc-receipt-v2"

PRODUCER_OPTION_ORDER = (
    "--source-feature-bag",
    "--raw-image-bag",
    "--camera-yaml",
    "--output-bag",
    "--image-topic",
    "--feature-topic",
    "--manifest-json",
    "--diagnostics-csv",
    "--legacy-manifest-json",
    "--work-directory",
    "--attempt-json",
)
PATH_OPTIONS = {
    "--source-feature-bag",
    "--raw-image-bag",
    "--camera-yaml",
    "--output-bag",
    "--manifest-json",
    "--diagnostics-csv",
    "--legacy-manifest-json",
    "--work-directory",
    "--attempt-json",
}
INPUT_FILE_OPTIONS = {
    "--source-feature-bag",
    "--raw-image-bag",
    "--camera-yaml",
}
ABSENT_OUTPUT_OPTIONS = PATH_OPTIONS - INPUT_FILE_OPTIONS
OPTIONAL_LIMIT = "--max-published-frames"

EXPECTED_SUPERVISION = {
    "argv_is_list": True,
    "cwd_is_exact": True,
    "environment_built_from_scratch": True,
    "no_deletion": True,
    "no_retry": True,
    "process_start_count": 1,
    "pycache_prefix_absent_pre_post": True,
    "shell": False,
    "timeout": None,
}

RC_USAGE = 64
RC_LAUNCH_FAILURE = 70
RC_NO_CLOBBER = 73
RC_CONTRACT_REJECTED = 78
RC_POSTCONDITION_FAILED = 86
MAX_CONTRACT_BYTES = 1024 * 1024


class LauncherContractError(RuntimeError):
    """Raised when a requested launch differs from the frozen contract."""


@dataclass
class _RunState:
    stage: str = "start_receipt_reserved"
    launch_attempt_count: int = 0
    producer_process_start_count: int = 0
    child_pid: int | None = None
    producer_return_code: int | None = None
    natural_end_observed: bool = False
    actual_argv: list[str] | None = None
    actual_environment: dict[str, str] | None = None
    actual_cwd: str | None = None
    arm_id: str | None = None
    contract_identity: Mapping[str, object] | None = None


class _StrictArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise LauncherContractError(f"argument contract rejected: {message}")

    def exit(self, status: int = 0, message: str | None = None) -> None:
        """Never let a mixed ``--help`` escape after start was consumed."""

        detail = (message or "argument parser requested exit").strip()
        raise LauncherContractError(
            f"argument contract requested parser exit status {status}: {detail}"
        )


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_json_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's bool/int equality coercion."""

    try:
        return _canonical_bytes(left) == _canonical_bytes(right)
    except (TypeError, ValueError):
        return False


def _path_lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _canonical_absolute_path(value: str | os.PathLike[str], label: str) -> Path:
    raw = os.fspath(value)
    if not raw or "\x00" in raw:
        raise LauncherContractError(f"{label} is empty or contains NUL")
    path = Path(raw)
    if not path.is_absolute():
        raise LauncherContractError(f"{label} must be absolute: {raw!r}")
    normalized = os.path.normpath(raw)
    if normalized != raw:
        raise LauncherContractError(
            f"{label} must be lexically canonical: {raw!r} != {normalized!r}"
        )
    return path


def _assert_no_symlink_components(path: Path, label: str) -> None:
    """Reject symlinks in every currently existing path component."""

    path = _canonical_absolute_path(path, label)
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        if not _path_lexists(current):
            continue
        observed = os.lstat(current)
        if stat.S_ISLNK(observed.st_mode):
            raise LauncherContractError(
                f"{label} contains symlink component: {current}"
            )


def _assert_existing_directory(path: Path, label: str) -> os.stat_result:
    _assert_no_symlink_components(path, label)
    try:
        observed = os.lstat(path)
    except FileNotFoundError as error:
        raise LauncherContractError(f"{label} does not exist: {path}") from error
    if not stat.S_ISDIR(observed.st_mode):
        raise LauncherContractError(f"{label} is not a directory: {path}")
    return observed


def _assert_safe_parent(path: Path, label: str) -> os.stat_result:
    parent = path.parent
    return _assert_existing_directory(parent, f"{label} parent")


def _assert_regular_single_link(path: Path, label: str) -> os.stat_result:
    _assert_no_symlink_components(path, label)
    try:
        observed = os.lstat(path)
    except FileNotFoundError as error:
        raise LauncherContractError(f"{label} does not exist: {path}") from error
    if not stat.S_ISREG(observed.st_mode):
        raise LauncherContractError(f"{label} is not a regular file: {path}")
    if int(observed.st_nlink) != 1:
        raise LauncherContractError(
            f"{label} hard-link count must be one: {path}: {observed.st_nlink}"
        )
    return observed


def _write_all(descriptor: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        written = os.write(descriptor, payload[offset:])
        if written <= 0:
            raise OSError("exclusive receipt write made no progress")
        offset += written


def _write_exclusive_receipt(path: Path, payload: Mapping[str, object]) -> None:
    """Create one immutable canonical receipt without replace or cleanup."""

    path = _canonical_absolute_path(path, "receipt path")
    parent_stat = _assert_safe_parent(path, "receipt path")
    encoded = _canonical_bytes(payload)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags, 0o444)
    created_identity: tuple[int, int] | None = None
    try:
        os.fchmod(descriptor, 0o444)
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o444
            or int(opened.st_nlink) != 1
        ):
            raise OSError("exclusive receipt descriptor contract failed")
        created_identity = (int(opened.st_dev), int(opened.st_ino))
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
        after_write = os.fstat(descriptor)
        if (
            (int(after_write.st_dev), int(after_write.st_ino))
            != created_identity
            or int(after_write.st_nlink) != 1
            or stat.S_IMODE(after_write.st_mode) != 0o444
            or int(after_write.st_size) != len(encoded)
        ):
            raise OSError("exclusive receipt descriptor drift after write")
    finally:
        os.close(descriptor)

    visible = os.lstat(path)
    if (
        created_identity is None
        or (int(visible.st_dev), int(visible.st_ino)) != created_identity
        or not stat.S_ISREG(visible.st_mode)
        or stat.S_IMODE(visible.st_mode) != 0o444
        or int(visible.st_nlink) != 1
        or path.is_symlink()
    ):
        raise OSError("exclusive receipt path identity drift")
    if path.read_bytes() != encoded:
        raise OSError("exclusive receipt bytes changed after publication")
    parent_after = os.lstat(path.parent)
    if (
        int(parent_after.st_dev),
        int(parent_after.st_ino),
    ) != (int(parent_stat.st_dev), int(parent_stat.st_ino)):
        raise OSError("exclusive receipt parent identity drift")
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    parent_descriptor = os.open(os.fspath(path.parent), directory_flags)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def _read_fd_all(descriptor: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = os.read(descriptor, 64 * 1024)
        if not block:
            break
        total += len(block)
        if total > MAX_CONTRACT_BYTES:
            raise LauncherContractError("command contract exceeds size limit")
        chunks.append(block)
    return b"".join(chunks)


def _reject_duplicate_json_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LauncherContractError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise LauncherContractError(f"non-finite JSON constant rejected: {value}")


def _load_canonical_contract(path: Path) -> tuple[dict[str, Any], dict[str, object]]:
    path = _canonical_absolute_path(path, "command contract")
    expected_stat = _assert_regular_single_link(path, "command contract")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(os.fspath(path), flags)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or int(opened.st_nlink) != 1
            or (int(opened.st_dev), int(opened.st_ino))
            != (int(expected_stat.st_dev), int(expected_stat.st_ino))
        ):
            raise LauncherContractError("command contract identity changed while opening")
        payload = _read_fd_all(descriptor)
    finally:
        os.close(descriptor)
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LauncherContractError(f"command contract JSON unreadable: {error}") from error
    if not isinstance(value, dict):
        raise LauncherContractError("command contract root must be an object")
    if payload != _canonical_bytes(value):
        raise LauncherContractError("command contract is not canonical JSON")
    visible = os.lstat(path)
    if (
        (int(visible.st_dev), int(visible.st_ino))
        != (int(opened.st_dev), int(opened.st_ino))
        or int(visible.st_nlink) != 1
        or not stat.S_ISREG(visible.st_mode)
    ):
        raise LauncherContractError("command contract path changed while reading")
    return value, {
        "path": str(path),
        "sha256": _sha256_bytes(payload),
        "size_bytes": len(payload),
    }


def _file_identity(path: Path) -> dict[str, object]:
    observed = _assert_regular_single_link(path, "identity file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = os.lstat(path)
    if (
        int(after.st_dev),
        int(after.st_ino),
    ) != (int(observed.st_dev), int(observed.st_ino)):
        raise LauncherContractError(f"identity file changed while hashing: {path}")
    return {
        "path": str(path),
        "sha256": digest.hexdigest(),
        "size_bytes": int(observed.st_size),
    }


def _launcher_process_observation() -> dict[str, object]:
    """Capture the fresh launcher boundary independently of child claims."""

    command_line_payload = Path("/proc/self/cmdline").read_bytes()
    command_line = [
        os.fsdecode(item)
        for item in command_line_payload.split(b"\0")
        if item
    ]
    executable = Path("/proc/self/exe").resolve(strict=True)
    source = Path(__file__).resolve(strict=True)
    return {
        "process_command_line": command_line,
        "working_directory": os.getcwd(),
        "environment": dict(os.environ),
        "sys_executable": str(Path(sys.executable).resolve(strict=True)),
        "proc_executable": _file_identity(executable),
        "launcher_source": _file_identity(source),
    }


def _option_mapping_from_tail(tail: Sequence[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    cursor = 0
    for expected_option in PRODUCER_OPTION_ORDER:
        if cursor + 1 >= len(tail) or tail[cursor] != expected_option:
            observed = tail[cursor] if cursor < len(tail) else None
            raise LauncherContractError(
                "producer argv option order drift: "
                f"expected {expected_option!r}, observed {observed!r}"
            )
        value = tail[cursor + 1]
        if not isinstance(value, str) or not value or "\x00" in value:
            raise LauncherContractError(f"invalid value for {expected_option}")
        values[expected_option] = value
        cursor += 2
    if cursor < len(tail):
        if (
            cursor + 2 != len(tail)
            or tail[cursor] != OPTIONAL_LIMIT
            or not isinstance(tail[cursor + 1], str)
        ):
            raise LauncherContractError("unexpected or duplicate producer argv suffix")
        try:
            limit = int(tail[cursor + 1])
        except ValueError as error:
            raise LauncherContractError("max-published-frames must be an integer") from error
        if limit <= 0 or str(limit) != tail[cursor + 1]:
            raise LauncherContractError(
                "max-published-frames must be a canonical positive integer"
            )
        values[OPTIONAL_LIMIT] = str(limit)
        cursor += 2
    if cursor != len(tail):
        raise LauncherContractError("producer argv was not consumed exactly")
    return values


def _build_producer_argv(arm_id: str, values: Mapping[str, str]) -> list[str]:
    if arm_id not in ARM_ENTRYPOINTS:
        raise LauncherContractError(f"unknown matched arm: {arm_id!r}")
    if set(values) not in (
        set(PRODUCER_OPTION_ORDER),
        set(PRODUCER_OPTION_ORDER) | {OPTIONAL_LIMIT},
    ):
        raise LauncherContractError("producer option set differs from frozen schema")
    argv = [
        PYTHON_EXECUTABLE,
        "-B",
        "-m",
        ARM_ENTRYPOINTS[arm_id],
    ]
    for option in PRODUCER_OPTION_ORDER:
        argv.extend((option, values[option]))
    if OPTIONAL_LIMIT in values:
        argv.extend((OPTIONAL_LIMIT, values[OPTIONAL_LIMIT]))
    return argv


def build_command_contract(
    arm_id: str,
    producer_values: Mapping[str, str],
    *,
    start_receipt: Path,
    rc_receipt: Path,
) -> dict[str, object]:
    """Build the only accepted command-contract shape."""

    return {
        "schema_version": COMMAND_CONTRACT_SCHEMA,
        "arm_id": arm_id,
        "argv": _build_producer_argv(arm_id, producer_values),
        "environment": dict(FROZEN_ENVIRONMENT),
        "working_directory": str(WORKING_DIRECTORY),
        "start_receipt": str(start_receipt),
        "rc_receipt": str(rc_receipt),
        "supervision": dict(EXPECTED_SUPERVISION),
    }


def _validate_exact_contract(
    contract: Mapping[str, Any],
    *,
    requested_start_receipt: Path,
    requested_rc_receipt: Path,
) -> tuple[str, dict[str, str], list[str]]:
    exact_keys = {
        "schema_version",
        "arm_id",
        "argv",
        "environment",
        "working_directory",
        "start_receipt",
        "rc_receipt",
        "supervision",
    }
    if set(contract) != exact_keys:
        raise LauncherContractError(
            f"command contract keys drift: {sorted(contract)}"
        )
    if contract["schema_version"] != COMMAND_CONTRACT_SCHEMA:
        raise LauncherContractError("command contract schema drift")
    arm_id = contract["arm_id"]
    if not isinstance(arm_id, str) or arm_id not in ARM_ENTRYPOINTS:
        raise LauncherContractError("command contract arm is not allowlisted")
    if contract["working_directory"] != str(WORKING_DIRECTORY):
        raise LauncherContractError("command contract working directory drift")
    if not _strict_json_equal(contract["environment"], FROZEN_ENVIRONMENT):
        raise LauncherContractError("command contract environment drift")
    if not _strict_json_equal(contract["supervision"], EXPECTED_SUPERVISION):
        raise LauncherContractError("command contract supervision drift")
    if contract["start_receipt"] != str(requested_start_receipt):
        raise LauncherContractError("command contract start receipt mismatch")
    if contract["rc_receipt"] != str(requested_rc_receipt):
        raise LauncherContractError("command contract RC receipt mismatch")
    argv = contract["argv"]
    if (
        not isinstance(argv, list)
        or any(not isinstance(value, str) for value in argv)
        or len(argv) < 4
    ):
        raise LauncherContractError("command contract argv must be a string list")
    expected_prefix = [PYTHON_EXECUTABLE, "-B", "-m", ARM_ENTRYPOINTS[arm_id]]
    if argv[:4] != expected_prefix:
        raise LauncherContractError("python/module entrypoint is not the frozen allowlist")
    producer_values = _option_mapping_from_tail(argv[4:])
    rebuilt = _build_producer_argv(arm_id, producer_values)
    if argv != rebuilt:
        raise LauncherContractError("producer argv does not round-trip exactly")
    expected = build_command_contract(
        arm_id,
        producer_values,
        start_receipt=requested_start_receipt,
        rc_receipt=requested_rc_receipt,
    )
    if not _strict_json_equal(dict(contract), expected):
        raise LauncherContractError("command contract differs from exact reconstruction")
    return arm_id, producer_values, rebuilt


def _absent_alias_key(path: Path, label: str) -> tuple[int, int, str]:
    parent_stat = _assert_safe_parent(path, label)
    return (int(parent_stat.st_dev), int(parent_stat.st_ino), path.name)


def _validate_paths(
    values: Mapping[str, str],
    *,
    start_receipt: Path,
    rc_receipt: Path,
    contract_path: Path | None,
) -> None:
    paths = {
        option: _canonical_absolute_path(values[option], option)
        for option in PATH_OPTIONS
    }
    start_receipt = _canonical_absolute_path(start_receipt, "start receipt")
    rc_receipt = _canonical_absolute_path(rc_receipt, "RC receipt")
    all_lexical = list(paths.values()) + [start_receipt, rc_receipt]
    if contract_path is not None:
        all_lexical.append(contract_path)
    if len({str(path) for path in all_lexical}) != len(all_lexical):
        raise LauncherContractError("duplicate lexical path in launch contract")

    existing_inode_roles: dict[tuple[int, int], str] = {}
    for option in sorted(INPUT_FILE_OPTIONS):
        path = paths[option]
        observed = _assert_regular_single_link(path, option)
        key = (int(observed.st_dev), int(observed.st_ino))
        if key in existing_inode_roles:
            raise LauncherContractError(
                f"existing input inode alias: {existing_inode_roles[key]} and {option}"
            )
        existing_inode_roles[key] = option
    start_stat = _assert_regular_single_link(start_receipt, "start receipt")
    start_key = (int(start_stat.st_dev), int(start_stat.st_ino))
    if start_key in existing_inode_roles:
        raise LauncherContractError("start receipt aliases an existing input")
    existing_inode_roles[start_key] = "start receipt"
    if contract_path is not None:
        contract_stat = _assert_regular_single_link(contract_path, "command contract")
        contract_key = (int(contract_stat.st_dev), int(contract_stat.st_ino))
        if contract_key in existing_inode_roles:
            raise LauncherContractError("command contract aliases another launch path")
        existing_inode_roles[contract_key] = "command contract"

    absent_paths = {
        option: paths[option] for option in sorted(ABSENT_OUTPUT_OPTIONS)
    }
    absent_paths["RC receipt"] = rc_receipt
    absent_aliases: dict[tuple[int, int, str], str] = {}
    for label, path in absent_paths.items():
        _assert_no_symlink_components(path, label)
        if _path_lexists(path):
            raise LauncherContractError(f"reserved output already exists: {label}: {path}")
        key = _absent_alias_key(path, label)
        if key in absent_aliases:
            raise LauncherContractError(
                f"absent output alias: {absent_aliases[key]} and {label}"
            )
        absent_aliases[key] = label

    if values["--image-topic"] != "/camera/image_raw":
        raise LauncherContractError("image topic differs from frozen A02 contract")
    if values["--feature-topic"] != "/feature_tracker/feature":
        raise LauncherContractError("feature topic differs from frozen backend contract")


def _assert_pycache_absent(stage: str) -> None:
    if _path_lexists(PYCACHE_PREFIX):
        raise LauncherContractError(
            f"shared pycache prefix is present at {stage}: {PYCACHE_PREFIX}"
        )


def _scan_option_occurrences(argv: Sequence[str]) -> None:
    known = {
        "--start-receipt",
        "--rc-receipt",
        "--command-contract-json",
        "--arm",
        *PRODUCER_OPTION_ORDER,
        OPTIONAL_LIMIT,
    }
    counts = {option: 0 for option in known}
    for token in argv:
        if token.startswith("--") and "=" in token:
            raise LauncherContractError("equals-form options are forbidden")
        if token in counts:
            counts[token] += 1
    duplicates = sorted(option for option, count in counts.items() if count > 1)
    if duplicates:
        raise LauncherContractError(f"duplicate command-line options: {duplicates}")


def _first_option_value(argv: Sequence[str], option: str) -> str:
    try:
        index = argv.index(option)
    except ValueError as error:
        raise LauncherContractError(f"required pre-receipt option missing: {option}") from error
    if index + 1 >= len(argv) or argv[index + 1].startswith("--"):
        raise LauncherContractError(f"required pre-receipt option has no value: {option}")
    return argv[index + 1]


def _reserve_start_receipt(raw_argv: Sequence[str]) -> tuple[Path, Path]:
    """Claim the irreversible start name before semantic command validation."""

    start_receipt = _canonical_absolute_path(
        _first_option_value(raw_argv, "--start-receipt"), "start receipt"
    )
    rc_receipt = _canonical_absolute_path(
        _first_option_value(raw_argv, "--rc-receipt"), "RC receipt"
    )
    if str(start_receipt) == str(rc_receipt):
        raise LauncherContractError("start and RC receipts must be distinct")
    payload = {
        "schema_version": START_RECEIPT_SCHEMA,
        "status": "START_NAMESPACE_CONSUMED_PREVALIDATION",
        "attempt_count": 1,
        "launcher_parent_pid": int(os.getpid()),
        "launcher_process_start_count": 1,
        "reserved_producer_process_start_count": 1,
        "producer_process_started_at_receipt": False,
        "no_retry": True,
        "no_deletion": True,
        "requested_launcher_argv": list(raw_argv),
        "requested_start_receipt": str(start_receipt),
        "requested_rc_receipt": str(rc_receipt),
        "launcher_invocation": _launcher_process_observation(),
        "receipt_created_unix_time_ns": int(time.time_ns()),
    }
    _write_exclusive_receipt(start_receipt, payload)
    return start_receipt, rc_receipt


def build_parser() -> argparse.ArgumentParser:
    parser = _StrictArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--start-receipt", required=True)
    parser.add_argument("--rc-receipt", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--command-contract-json")
    source.add_argument("--arm", choices=tuple(ARM_ENTRYPOINTS))
    for option in PRODUCER_OPTION_ORDER:
        parser.add_argument(option)
    parser.add_argument(OPTIONAL_LIMIT)
    return parser


def _values_from_explicit_args(args: argparse.Namespace) -> dict[str, str]:
    values: dict[str, str] = {}
    for option in PRODUCER_OPTION_ORDER:
        attribute = option[2:].replace("-", "_")
        value = getattr(args, attribute)
        if value is None:
            raise LauncherContractError(
                f"explicit launch is missing producer option: {option}"
            )
        values[option] = value
    if args.max_published_frames is not None:
        try:
            parsed = int(args.max_published_frames)
        except ValueError as error:
            raise LauncherContractError(
                "max-published-frames must be an integer"
            ) from error
        if parsed <= 0 or str(parsed) != args.max_published_frames:
            raise LauncherContractError(
                "max-published-frames must be a canonical positive integer"
            )
        values[OPTIONAL_LIMIT] = str(parsed)
    return values


def _reject_explicit_options_in_contract_mode(args: argparse.Namespace) -> None:
    supplied = []
    for option in PRODUCER_OPTION_ORDER:
        attribute = option[2:].replace("-", "_")
        if getattr(args, attribute) is not None:
            supplied.append(option)
    if args.max_published_frames is not None:
        supplied.append(OPTIONAL_LIMIT)
    if supplied:
        raise LauncherContractError(
            f"contract mode forbids explicit producer options: {supplied}"
        )


def _normalize_child_return_code(returncode: int) -> int:
    if returncode < 0:
        return min(255, 128 + (-returncode))
    return int(returncode) & 0xFF


def _wait_for_natural_end(process: subprocess.Popen) -> int:
    """Wait without timeout or signals; retry only an interrupted syscall."""

    while True:
        try:
            return int(process.wait())
        except InterruptedError:
            continue


def _run_validated_contract(
    *,
    arm_id: str,
    producer_argv: list[str],
    producer_values: Mapping[str, str],
    start_receipt: Path,
    rc_receipt: Path,
    contract_path: Path | None,
    contract_identity: Mapping[str, object] | None,
    state: _RunState,
) -> int:
    state.stage = "runtime_and_path_validation"
    state.arm_id = arm_id
    state.contract_identity = contract_identity
    _assert_existing_directory(WORKING_DIRECTORY, "working directory")
    if str(WORKING_DIRECTORY.resolve(strict=True)) != str(WORKING_DIRECTORY):
        raise LauncherContractError("working directory is not its canonical real path")
    _validate_paths(
        producer_values,
        start_receipt=start_receipt,
        rc_receipt=rc_receipt,
        contract_path=contract_path,
    )
    _assert_regular_single_link(Path(PYTHON_EXECUTABLE), "python executable")
    _assert_pycache_absent("pre-launch")

    actual_environment = dict(FROZEN_ENVIRONMENT)
    actual_argv = list(producer_argv)
    actual_cwd = str(WORKING_DIRECTORY)
    state.actual_environment = actual_environment
    state.actual_argv = actual_argv
    state.actual_cwd = actual_cwd
    launch_started_ns = time.time_ns()
    # This is the only producer-start call site.  It is intentionally not in a
    # loop and has no fallback or retry path.
    state.stage = "producer_popen"
    state.launch_attempt_count = 1
    process = subprocess.Popen(
        actual_argv,
        cwd=actual_cwd,
        env=actual_environment,
        shell=False,
        close_fds=True,
        start_new_session=False,
    )
    state.producer_process_start_count = 1
    child_pid = int(process.pid)
    state.child_pid = child_pid
    if child_pid <= 0:
        raise OSError(f"producer returned invalid pid: {child_pid}")
    state.stage = "producer_wait"
    producer_returncode = _wait_for_natural_end(process)
    state.producer_return_code = producer_returncode
    state.natural_end_observed = True
    ended_ns = time.time_ns()

    pycache_absent_post = not _path_lexists(PYCACHE_PREFIX)
    terminated_by_signal = producer_returncode < 0
    signal_number = -producer_returncode if terminated_by_signal else None
    rc_payload = {
        "schema_version": RC_RECEIPT_SCHEMA,
        "status": (
            "PROCESS_ENDED"
            if pycache_absent_post
            else "PROCESS_ENDED_PYCACHE_POSTCONDITION_FAILED"
        ),
        "arm_id": arm_id,
        "start_receipt": _file_identity(start_receipt),
        "command_contract": (
            dict(contract_identity) if contract_identity is not None else None
        ),
        "actual_execution": {
            "argv": actual_argv,
            "environment": actual_environment,
            "working_directory": actual_cwd,
            "shell": False,
        },
        "producer_process": {
            "pid": child_pid,
            "launch_attempt_count": 1,
            "process_start_count": 1,
            "producer_return_code": producer_returncode,
            "natural_end_observed": True,
            "exited_normally": not terminated_by_signal,
            "terminated_by_signal": terminated_by_signal,
            "signal_number": signal_number,
            "supervisor_sent_signal": False,
            "timed_out": False,
            "timeout_seconds": None,
            "retry_performed": False,
        },
        "pycache_contract": {
            "prefix": str(PYCACHE_PREFIX),
            "absent_pre": True,
            "absent_post": pycache_absent_post,
            "deleted_by_launcher": False,
        },
        "timing": {
            "child_launch_unix_time_ns": int(launch_started_ns),
            "child_end_unix_time_ns": int(ended_ns),
        },
        "launcher": {
            "parent_pid": int(os.getpid()),
            "source": _file_identity(Path(__file__).resolve(strict=True)),
            "no_retry": True,
            "no_deletion": True,
        },
    }
    state.stage = "natural_end_receipt_publication"
    _write_exclusive_receipt(rc_receipt, rc_payload)
    state.stage = "complete"
    if not pycache_absent_post:
        return RC_POSTCONDITION_FAILED
    return _normalize_child_return_code(producer_returncode)


def _seal_terminal_failure(
    *,
    state: _RunState,
    start_receipt: Path,
    rc_receipt: Path,
    error: Exception,
) -> None:
    """Seal a truthful terminal record after this invocation owns start."""

    if state.producer_process_start_count == 0:
        status = "TERMINAL_PRESTART_FAILURE"
    elif state.natural_end_observed:
        status = "TERMINAL_POST_END_SUPERVISION_FAILURE"
    else:
        status = "SUPERVISION_FAILURE_PROCESS_END_UNCONFIRMED_GLOBAL_STOP"
    returncode = state.producer_return_code
    terminated_by_signal = returncode is not None and returncode < 0
    payload = {
        "schema_version": RC_RECEIPT_SCHEMA,
        "status": status,
        "arm_id": state.arm_id,
        "start_receipt": _file_identity(start_receipt),
        "command_contract": (
            dict(state.contract_identity)
            if state.contract_identity is not None
            else None
        ),
        "failure": {
            "stage": state.stage,
            "error_type": type(error).__name__,
            "error": str(error),
        },
        "requested_execution": {
            "argv": state.actual_argv,
            "environment": state.actual_environment,
            "working_directory": state.actual_cwd,
            "shell": False,
        },
        "actual_execution": (
            {
                "argv": state.actual_argv,
                "environment": state.actual_environment,
                "working_directory": state.actual_cwd,
                "shell": False,
            }
            if state.producer_process_start_count == 1
            else None
        ),
        "producer_process": {
            "pid": state.child_pid,
            "launch_attempt_count": state.launch_attempt_count,
            "process_start_count": state.producer_process_start_count,
            "producer_return_code": returncode,
            "natural_end_observed": state.natural_end_observed,
            "exited_normally": (
                returncode is not None and returncode >= 0
            ),
            "terminated_by_signal": terminated_by_signal,
            "signal_number": -returncode if terminated_by_signal else None,
            "supervisor_sent_signal": False,
            "timed_out": False,
            "timeout_seconds": None,
            "retry_performed": False,
            "terminal_state_confirmed": state.natural_end_observed,
            "authorizes_followup": False,
        },
        "pycache_contract": {
            "prefix": str(PYCACHE_PREFIX),
            "absent_when_failure_sealed": not _path_lexists(PYCACHE_PREFIX),
            "deleted_by_launcher": False,
        },
        "launcher": {
            "parent_pid": int(os.getpid()),
            "source": _file_identity(Path(__file__).resolve(strict=True)),
            "no_retry": True,
            "no_deletion": True,
        },
        "receipt_created_unix_time_ns": int(time.time_ns()),
    }
    _write_exclusive_receipt(rc_receipt, payload)


def run(raw_argv: Sequence[str]) -> int:
    """Reserve, validate, launch once, and seal the natural return code."""

    start_receipt, rc_receipt = _reserve_start_receipt(raw_argv)
    state = _RunState()
    try:
        state.stage = "command_line_validation"
        _scan_option_occurrences(raw_argv)
        args = build_parser().parse_args(list(raw_argv))
        if (
            Path(args.start_receipt) != start_receipt
            or Path(args.rc_receipt) != rc_receipt
        ):
            raise LauncherContractError(
                "pre-reserved receipt paths changed during parse"
            )

        contract_path: Path | None = None
        contract_identity: Mapping[str, object] | None = None
        if args.command_contract_json is not None:
            _reject_explicit_options_in_contract_mode(args)
            contract_path = _canonical_absolute_path(
                args.command_contract_json, "command contract"
            )
            state.stage = "command_contract_load"
            contract, contract_identity = _load_canonical_contract(contract_path)
            state.contract_identity = contract_identity
        else:
            assert args.arm is not None
            values = _values_from_explicit_args(args)
            contract = build_command_contract(
                args.arm,
                values,
                start_receipt=start_receipt,
                rc_receipt=rc_receipt,
            )
        state.stage = "command_contract_validation"
        arm_id, producer_values, producer_argv = _validate_exact_contract(
            contract,
            requested_start_receipt=start_receipt,
            requested_rc_receipt=rc_receipt,
        )
        state.arm_id = arm_id
        return _run_validated_contract(
            arm_id=arm_id,
            producer_argv=producer_argv,
            producer_values=producer_values,
            start_receipt=start_receipt,
            rc_receipt=rc_receipt,
            contract_path=contract_path,
            contract_identity=contract_identity,
            state=state,
        )
    except Exception as error:
        _seal_terminal_failure(
            state=state,
            start_receipt=start_receipt,
            rc_receipt=rc_receipt,
            error=error,
        )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv in (["-h"], ["--help"]):
        build_parser().print_help()
        return 0
    try:
        return run(raw_argv)
    except FileExistsError as error:
        sys.stderr.write(f"matched sealed launcher no-clobber rejection: {error}\n")
        return RC_NO_CLOBBER
    except LauncherContractError as error:
        sys.stderr.write(f"matched sealed launcher contract rejection: {error}\n")
        return RC_CONTRACT_REJECTED
    except (OSError, ValueError) as error:
        sys.stderr.write(f"matched sealed launcher execution failure: {error}\n")
        return RC_LAUNCH_FAILURE
    except Exception as error:
        sys.stderr.write(
            "matched sealed launcher unexpected fail-closed error: "
            f"{type(error).__name__}: {error}\n"
        )
        return RC_LAUNCH_FAILURE


if __name__ == "__main__":
    raise SystemExit(main())
