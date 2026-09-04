#!/usr/bin/env python3
"""Hash-bound child bootstrap and actual-runtime receipt for formal G0.

This module has no workspace-local imports.  Formal execution supplies the
wrapper, evaluator base, evaluator core, Python interpreter, and this file as
fully sealed inherited memfds.  The wrapper is loaded only from its procfd and
the evaluator writes into a retained directory fd.  After the evaluator has
returned, this bootstrap inventories the runtime that was *actually loaded*
and exclusively writes ``runtime_receipt.json`` into that same retained
directory.

Generated ROS ``genpy`` modules are deliberately identified by their source
bytes and message contracts, never by their random temporary path or module
name.  Persistent files are opened with ``O_NOFOLLOW`` and hashed from a held
fd, with pathname identity rechecked around the read.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import types
from typing import Any, Iterable, Mapping


SCHEMA_VERSION = "aquafe-formal-g0-actual-runtime-receipt-v3"
RECEIPT_FILENAME = "runtime_receipt.json"
SELF_HASH_FIELD = "runtime_receipt_hash"
WRAPPER_ENV = "AQUAFE_FORMAL_G0_WRAPPER_FD"
BASE_ENV = "AQUAFE_FORMAL_G0_BASE_FD"
CORE_ENV = "AQUAFE_FORMAL_G0_CORE_FD"
OUTPUT_ENV = "AQUAFE_FORMAL_G0_ROLE_OUTPUT_FD"
ROLE_ENV = "AQUAFE_FORMAL_G0_ROLE"
WRAPPER_BASE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_BASE"
WRAPPER_CORE_ENV = "AQUAFE_P07_SEALED_EVALUATOR_CORE"
PROBE_ARGUMENT = "--runtime-probe"
_PROC_FD_RE = re.compile(r"/proc/self/fd/([0-9]+)")
_GENPY_SOURCE_RE = re.compile(r"/tmp/genpy_[^/]+/[^/]+\.pyc?")
_HASH_RE = re.compile(r"[0-9a-f]{64}")
_MD5_RE = re.compile(r"[0-9a-f]{32}")
_MAP_PERMISSION_RE = re.compile(r"[r-][w-][x-][ps]")
_HEX_RE = re.compile(r"[0-9a-f]+")
_DEVICE_RE = re.compile(r"[0-9a-f]+:[0-9a-f]+")
_STAT_KEYS = {
    "device",
    "inode",
    "mode",
    "link_count",
    "uid",
    "gid",
    "mtime_ns",
    "ctime_ns",
}
_FILE_IDENTITY_KEYS = {
    "lexical_path",
    "resolved_path",
    "symlink",
    "size_bytes",
    "sha256",
    "stat",
}
_MODULE_PATH_FIELDS = ("module_file", "spec_origin", "module_cached")
_MODULE_PATH_SENTINELS = {
    "module_file": frozenset(),
    "spec_origin": frozenset({"built-in", "frozen"}),
    "module_cached": frozenset(),
}
_IGNORED_PYTHON_ENVIRONMENT_OPTIONS = [
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONHASHSEED",
    "PYTHONNOUSERSITE",
]
_COMMON_ENVIRONMENT_KEYS = {
    "HOME",
    "USER",
    "LOGNAME",
    "SHELL",
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONHASHSEED",
    "PYTHONNOUSERSITE",
    "PYTHONDONTWRITEBYTECODE",
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    ROLE_ENV,
    WRAPPER_ENV,
    BASE_ENV,
    CORE_ENV,
    WRAPPER_BASE_ENV,
    WRAPPER_CORE_ENV,
}
_TARGET_SIGNAL_NUMBERS = (("SIGHUP", 1), ("SIGINT", 2), ("SIGTERM", 15))
_TARGET_SIGNAL_QUERY = "pthread_sigmask(SIG_BLOCK,EMPTY_SET)_NO_STATE_CHANGE"
_REQUIRED_SEALS = (
    fcntl.F_SEAL_WRITE
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_SEAL
)


class FormalG0RuntimeError(RuntimeError):
    """The formal child runtime or receipt contract is not closed."""


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the one receipt encoding (pretty, sorted, newline terminated)."""

    return (
        json.dumps(
            dict(value),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _receipt_hash(value: Mapping[str, Any]) -> str:
    clone = dict(value)
    clone.pop(SELF_HASH_FIELD, None)
    return _sha256_bytes(canonical_json_bytes(clone))


def _sealed_memfd(name: str, content: bytes, *, executable: bool = False) -> int:
    """Create one fully sealed anonymous source/executable for freeze probing."""

    required = ("memfd_create", "MFD_ALLOW_SEALING", "MFD_CLOEXEC")
    if any(not hasattr(os, item) for item in required):
        raise FormalG0RuntimeError("platform lacks sealed memfd support")
    fd = os.memfd_create(name, os.MFD_ALLOW_SEALING | os.MFD_CLOEXEC)
    try:
        _write_all(fd, content)
        if executable:
            os.fchmod(fd, 0o500)
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(fd, fcntl.F_ADD_SEALS, _REQUIRED_SEALS)
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) != _REQUIRED_SEALS:
            raise FormalG0RuntimeError("new probe memfd seal set differs")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_fd(fd: int, size: int) -> bytes:
    content = bytearray()
    offset = 0
    while offset < size:
        block = os.pread(fd, min(4 * 1024 * 1024, size - offset), offset)
        if not block:
            raise FormalG0RuntimeError("short read from held runtime file")
        content.extend(block)
        offset += len(block)
    return bytes(content)


def _read_process_argv() -> list[str]:
    """Read the kernel-visible argv so ``-I -B`` is receipt evidence."""

    fd = os.open(
        "/proc/self/cmdline",
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
    finally:
        os.close(fd)
    content = b"".join(chunks)
    if not content or not content.endswith(b"\0"):
        raise FormalG0RuntimeError("kernel process argv is absent or unterminated")
    raw = content[:-1].split(b"\0")
    if not raw or any(not item for item in raw):
        raise FormalG0RuntimeError("kernel process argv contains an empty item")
    try:
        return [item.decode("utf-8", "strict") for item in raw]
    except UnicodeDecodeError as error:
        raise FormalG0RuntimeError("kernel process argv is not UTF-8") from error


def _stat_record(info: os.stat_result) -> dict[str, Any]:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "mode": int(stat.S_IMODE(info.st_mode)),
        "link_count": int(info.st_nlink),
        "uid": int(info.st_uid),
        "gid": int(info.st_gid),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _regular_fd_identity(fd: int) -> dict[str, Any]:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise FormalG0RuntimeError("runtime identity target is not a regular file")
    content = _read_fd(fd, int(before.st_size))
    after = os.fstat(fd)
    if (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise FormalG0RuntimeError("held runtime file changed while hashing")
    return {
        "size_bytes": int(before.st_size),
        "sha256": _sha256_bytes(content),
        "stat": _stat_record(before),
    }


def _path_lstat_key(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def persistent_file_identity(raw_path: str) -> dict[str, Any]:
    """Hash one persistent file through a no-follow fd and recheck its name."""

    if not isinstance(raw_path, str) or not raw_path.startswith("/"):
        raise FormalG0RuntimeError("persistent runtime path must be absolute")
    lexical = os.path.normpath(raw_path)
    if lexical != raw_path or lexical.startswith("/proc/"):
        raise FormalG0RuntimeError("persistent runtime path is non-canonical")
    before_lexical = os.lstat(lexical)
    symlink: dict[str, Any] | None = None
    opened = lexical
    if stat.S_ISLNK(before_lexical.st_mode):
        link_text = os.readlink(lexical)
        symlink = {
            "target": link_text,
            "target_sha256": _sha256_bytes(os.fsencode(link_text)),
            "stat": _stat_record(before_lexical),
        }
        opened = os.path.realpath(lexical)
        if not opened.startswith("/") or not os.path.exists(opened):
            raise FormalG0RuntimeError("persistent runtime symlink target is absent")
    elif not stat.S_ISREG(before_lexical.st_mode):
        raise FormalG0RuntimeError("persistent runtime path is not regular or symlink")
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(opened, flags)
    try:
        identity = _regular_fd_identity(fd)
        held = os.fstat(fd)
        opened_after = os.lstat(opened)
        lexical_after = os.lstat(lexical)
        if _path_lstat_key(lexical_after) != _path_lstat_key(before_lexical):
            raise FormalG0RuntimeError("persistent runtime pathname changed")
        if symlink is not None and os.readlink(lexical) != symlink["target"]:
            raise FormalG0RuntimeError("persistent runtime symlink changed")
        if (
            not stat.S_ISREG(opened_after.st_mode)
            or int(opened_after.st_dev) != int(held.st_dev)
            or int(opened_after.st_ino) != int(held.st_ino)
        ):
            raise FormalG0RuntimeError("persistent runtime target pathname changed")
    finally:
        os.close(fd)
    return {
        "lexical_path": lexical,
        "resolved_path": opened,
        "symlink": symlink,
        **identity,
    }


def _procfd_number(value: str, label: str) -> int:
    match = _PROC_FD_RE.fullmatch(value or "")
    if match is None:
        raise FormalG0RuntimeError(f"{label} must be an exact /proc/self/fd/N")
    fd = int(match.group(1))
    if fd < 3:
        raise FormalG0RuntimeError(f"{label} fd is reserved")
    return fd


def sealed_source_identity(value: str, label: str) -> dict[str, Any]:
    fd = _procfd_number(value, label)
    identity = _regular_fd_identity(fd)
    try:
        seals = int(fcntl.fcntl(fd, fcntl.F_GET_SEALS))
    except OSError as error:
        raise FormalG0RuntimeError(f"{label} is not a sealable memfd") from error
    if seals != _REQUIRED_SEALS:
        raise FormalG0RuntimeError(f"{label} memfd is not fully sealed")
    return {
        "locator": value,
        "seals": seals,
        **identity,
    }


def _generated_message_contracts(module: types.ModuleType) -> list[dict[str, str]]:
    rows: set[tuple[str, str, str]] = set()
    for value in vars(module).values():
        message_type = getattr(value, "_type", None)
        md5sum = getattr(value, "_md5sum", None)
        full_text = getattr(value, "_full_text", None)
        if all(isinstance(item, str) for item in (message_type, md5sum, full_text)):
            rows.add((message_type, md5sum, full_text))
    return [
        {
            "message_type": message_type,
            "md5sum": md5sum,
            "full_text": full_text,
            "full_text_sha256": _sha256_bytes(full_text.encode("utf-8")),
        }
        for message_type, md5sum, full_text in sorted(rows)
    ]


def _generated_module_identity(module: types.ModuleType, source: str) -> dict[str, Any]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    before = os.lstat(source)
    if not stat.S_ISREG(before.st_mode):
        raise FormalG0RuntimeError("generated genpy source is not a regular file")
    fd = os.open(source, flags)
    try:
        identity = _regular_fd_identity(fd)
        after = os.lstat(source)
        if _path_lstat_key(before) != _path_lstat_key(after):
            raise FormalG0RuntimeError("generated genpy source changed")
    finally:
        os.close(fd)
    contracts = _generated_message_contracts(module)
    if not contracts:
        raise FormalG0RuntimeError("generated genpy module lacks message contracts")
    return {
        "module_python_type": (
            f"{type(module).__module__}.{type(module).__qualname__}"
        ),
        "source_size_bytes": identity["size_bytes"],
        "source_sha256": identity["sha256"],
        "message_contracts": contracts,
    }


def _candidate_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    if _PROC_FD_RE.fullmatch(value) is not None:
        return None
    normalized = os.path.normpath(value)
    if normalized != value or value.startswith("/proc/"):
        raise FormalG0RuntimeError(f"absolute module path is non-canonical: {value}")
    try:
        info = os.lstat(value)
    except OSError as error:
        raise FormalG0RuntimeError(
            f"absolute module path is unavailable: {value}"
        ) from error
    if stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        return value
    raise FormalG0RuntimeError(f"absolute module path is not a file: {value}")


def _module_path_kind(field: str, value: object) -> str:
    if field not in _MODULE_PATH_SENTINELS:
        raise FormalG0RuntimeError("unknown module path field")
    if value is None:
        return "absent"
    if not isinstance(value, str) or not value:
        raise FormalG0RuntimeError(f"module {field} is not a nonempty string")
    if value in _MODULE_PATH_SENTINELS[field]:
        return "sentinel"
    if not value.startswith("/"):
        raise FormalG0RuntimeError(
            f"module {field} uses a non-authoritative relative value: {value}"
        )
    if _PROC_FD_RE.fullmatch(value) is not None:
        return "sealed_procfd"
    _candidate_path(value)
    return "persistent"


def _capture_modules(
    sealed_sources: Mapping[str, Mapping[str, Any]],
    *,
    modules: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    persistent: list[dict[str, Any]] = []
    generated_by_hash: dict[str, dict[str, Any]] = {}
    identity_cache: dict[str, dict[str, Any]] = {}
    sealed_by_locator: dict[str, str] = {}
    for role, record in sealed_sources.items():
        locator = record.get("locator")
        if (
            not isinstance(role, str)
            or not role
            or not isinstance(locator, str)
            or _PROC_FD_RE.fullmatch(locator) is None
            or locator in sealed_by_locator
        ):
            raise FormalG0RuntimeError("sealed module-source authority is malformed")
        sealed_by_locator[locator] = role
    module_table = sys.modules if modules is None else modules
    for sys_key, module in sorted(list(module_table.items())):
        if not isinstance(module, types.ModuleType):
            continue
        spec = getattr(module, "__spec__", None)
        raw_fields = {
            "module_file": getattr(module, "__file__", None),
            "spec_origin": getattr(spec, "origin", None),
            "module_cached": getattr(module, "__cached__", None),
        }
        generated_sources = sorted(
            {
                value
                for value in raw_fields.values()
                if isinstance(value, str) and _GENPY_SOURCE_RE.fullmatch(value)
            }
        )
        if generated_sources:
            if len(generated_sources) != 1:
                raise FormalG0RuntimeError("genpy module has ambiguous generated source")
            row = _generated_module_identity(module, generated_sources[0])
            key = str(row["source_sha256"])
            prior = generated_by_hash.get(key)
            if prior is not None and prior != row:
                raise FormalG0RuntimeError("genpy content hash has conflicting contracts")
            generated_by_hash[key] = row
            continue
        identities: dict[str, dict[str, Any]] = {}
        sealed_bindings: dict[str, str] = {}
        for field, value in raw_fields.items():
            kind = _module_path_kind(field, value)
            if kind == "sealed_procfd":
                assert isinstance(value, str)
                sealed_role = sealed_by_locator.get(value)
                if sealed_role is None:
                    raise FormalG0RuntimeError(
                        f"module uses an unknown procfd source: {sys_key}:{field}"
                    )
                sealed_bindings[field] = sealed_role
                continue
            if kind != "persistent":
                continue
            assert isinstance(value, str)
            path = value
            if path not in identity_cache:
                identity_cache[path] = persistent_file_identity(path)
            identities[field] = identity_cache[path]
        if not identities and not sealed_bindings:
            continue
        persistent.append(
            {
                "sys_modules_key": sys_key,
                "module_name": getattr(module, "__name__", None),
                "module_python_type": (
                    f"{type(module).__module__}.{type(module).__qualname__}"
                ),
                "module_file": raw_fields["module_file"],
                "spec_origin": raw_fields["spec_origin"],
                "module_cached": raw_fields["module_cached"],
                "file_identities": identities,
                "sealed_source_bindings": sealed_bindings,
            }
        )
    return persistent, [generated_by_hash[key] for key in sorted(generated_by_hash)]


def _read_proc_maps() -> str:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open("/proc/self/maps", flags)
    try:
        chunks: list[bytes] = []
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            chunks.append(block)
    finally:
        os.close(fd)
    return b"".join(chunks).decode("utf-8", "strict")


def _device_pair(raw: str, label: str) -> tuple[int, int]:
    if not isinstance(raw, str) or _DEVICE_RE.fullmatch(raw.lower()) is None:
        raise FormalG0RuntimeError(f"{label} device is malformed")
    major, minor = raw.lower().split(":", 1)
    return int(major, 16), int(minor, 16)


def _mapping_identity_key(device: str, inode: int) -> tuple[int, int, int]:
    major, minor = _device_pair(device, "mapped")
    return major, minor, inode


def capture_persistent_maps(
    text: str | None = None,
    *,
    sealed_sources: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Canonicalize persistent and registered sealed ``/proc/self/maps`` rows."""

    rows: list[dict[str, Any]] = []
    sealed_rows: list[dict[str, Any]] = []
    files: dict[str, dict[str, Any]] = {}
    sealed_sources = {} if sealed_sources is None else sealed_sources
    sealed_by_identity: dict[tuple[int, int, int], tuple[str, Mapping[str, Any]]] = {}
    for role, record in sealed_sources.items():
        source_stat = record.get("stat")
        if not isinstance(role, str) or not role or not isinstance(source_stat, Mapping):
            raise FormalG0RuntimeError("sealed mapping authority is malformed")
        device = source_stat.get("device")
        inode = source_stat.get("inode")
        if (
            isinstance(device, bool)
            or not isinstance(device, int)
            or device < 0
            or isinstance(inode, bool)
            or not isinstance(inode, int)
            or inode <= 0
        ):
            raise FormalG0RuntimeError("sealed mapping stat authority is malformed")
        key = (os.major(device), os.minor(device), inode)
        if key in sealed_by_identity:
            raise FormalG0RuntimeError("sealed mapping identities are not unique")
        sealed_by_identity[key] = (role, record)
    for line in (text if text is not None else _read_proc_maps()).splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6:
            continue
        _address, permissions, offset, device, inode, path = parts
        if not path.startswith("/"):
            continue
        if path.startswith("/memfd:"):
            if re.fullmatch(r"/memfd:[^/\n]+ \(deleted\)", path) is None:
                raise FormalG0RuntimeError("memfd map path shape differs")
            try:
                inode_int = int(inode)
            except ValueError as error:
                raise FormalG0RuntimeError("memfd map inode is malformed") from error
            authority = sealed_by_identity.get(
                _mapping_identity_key(device.lower(), inode_int)
            )
            if authority is None:
                raise FormalG0RuntimeError("mapped memfd is not a registered sealed source")
            role, record = authority
            sealed_rows.append(
                {
                    "permissions": permissions,
                    "offset_hex": offset.lower(),
                    "device": device.lower(),
                    "inode": inode_int,
                    "sealed_source_role": role,
                    "file_sha256": record.get("sha256"),
                    "file_size_bytes": record.get("size_bytes"),
                }
            )
            continue
        if path.endswith(" (deleted)"):
            raise FormalG0RuntimeError("persistent mapped file was deleted")
        candidate = _candidate_path(path)
        if candidate is None:
            if path.startswith("/proc/"):
                continue
            raise FormalG0RuntimeError(f"persistent mapped path is unavailable: {path}")
        if candidate not in files:
            files[candidate] = persistent_file_identity(candidate)
        rows.append(
            {
                "permissions": permissions,
                "offset_hex": offset.lower(),
                "device": device.lower(),
                "inode": int(inode),
                "file_sha256": files[candidate]["sha256"],
                "file_size_bytes": files[candidate]["size_bytes"],
                "lexical_path": candidate,
            }
        )
    rows.sort(
        key=lambda row: (
            row["lexical_path"],
            row["offset_hex"],
            row["permissions"],
            row["device"],
            row["inode"],
        )
    )
    # Address ranges are ASLR-only and intentionally absent.  Collapse any
    # rows that become byte-identical after removing their address range.
    unique_rows = {
        json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ): row
        for row in rows
    }
    rows = sorted(
        unique_rows.values(),
        key=lambda row: (
            row["lexical_path"],
            row["offset_hex"],
            row["permissions"],
            row["device"],
            row["inode"],
        ),
    )
    sealed_unique = {
        json.dumps(
            row,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ): row
        for row in sealed_rows
    }
    sealed_rows = sorted(
        sealed_unique.values(),
        key=lambda row: (
            row["sealed_source_role"],
            row["offset_hex"],
            row["permissions"],
            row["device"],
            row["inode"],
        ),
    )
    return {
        "files": [files[key] for key in sorted(files)],
        "rows": rows,
        "sealed_rows": sealed_rows,
    }


def _is_elf_file(identity: Mapping[str, Any]) -> bool:
    path = identity.get("resolved_path")
    if not isinstance(path, str):
        raise FormalG0RuntimeError("mapped-file identity lacks resolved path")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        magic = os.pread(fd, 4, 0)
        if (
            int(info.st_size) != identity.get("size_bytes")
            or _sha256_bytes(_read_fd(fd, int(info.st_size))) != identity.get("sha256")
        ):
            raise FormalG0RuntimeError("mapped ELF candidate changed")
        return magic == b"\x7fELF"
    finally:
        os.close(fd)


def _native_loaded_elf_closure(
    maps: Mapping[str, Any], sealed_sources: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Return persistent ELF plus all registered sealed mapped identities."""

    files = maps.get("files")
    sealed_rows = maps.get("sealed_rows")
    if not isinstance(files, list) or not isinstance(sealed_rows, list):
        raise FormalG0RuntimeError("mapped file closure is malformed")
    result = [
        {"mapping_kind": "PERSISTENT_ELF", "file": dict(row)}
        for row in files
        if isinstance(row, Mapping) and _is_elf_file(row)
    ]
    mapped_roles = sorted(
        {
            str(row.get("sealed_source_role"))
            for row in sealed_rows
            if isinstance(row, Mapping)
        }
    )
    for role in mapped_roles:
        record = sealed_sources.get(role)
        if not isinstance(record, Mapping):
            raise FormalG0RuntimeError("sealed native mapping lacks source authority")
        result.append(
            {
                "mapping_kind": "SEALED_MAPPED_FILE",
                "sealed_source_role": role,
                "sha256": record.get("sha256"),
                "size_bytes": record.get("size_bytes"),
            }
        )
    return result


def _version_value(module_name: str, attribute: str = "__version__") -> Any:
    module = sys.modules.get(module_name)
    if module is None:
        return None
    value = getattr(module, attribute, None)
    return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)


def _safe_role(role: str) -> str:
    if role not in {"primary", "verification", "runtime_probe"}:
        raise FormalG0RuntimeError("formal G0 role is invalid")
    return role


def _assert_live_python_isolation(initial_argv: list[str]) -> list[str]:
    """Require that the kernel and effective CPython flags prove ``-I -B``."""

    process_argv = _read_process_argv()
    expected = [sys.executable, "-I", "-B", *initial_argv]
    if process_argv != expected:
        raise FormalG0RuntimeError(
            "formal G0 kernel argv must be exact sealed-python -I -B bootstrap"
        )
    exact_flags = {
        "isolated": int(sys.flags.isolated),
        "ignore_environment": int(sys.flags.ignore_environment),
        "no_user_site": int(sys.flags.no_user_site),
        "dont_write_bytecode": int(sys.flags.dont_write_bytecode),
        "hash_randomization": int(sys.flags.hash_randomization),
    }
    if exact_flags != {
        "isolated": 1,
        "ignore_environment": 1,
        "no_user_site": 1,
        "dont_write_bytecode": 1,
        "hash_randomization": 1,
    }:
        raise FormalG0RuntimeError(
            f"formal G0 effective Python flags differ: {exact_flags}"
        )
    return process_argv


def _target_signal_contract() -> list[dict[str, object]]:
    """Return the exact child-target signal set and platform numbers."""

    rows: list[dict[str, object]] = []
    for name, expected_number in _TARGET_SIGNAL_NUMBERS:
        value = getattr(signal, name, None)
        if (
            value is None
            or isinstance(value, bool)
            or not isinstance(value, int)
            or int(value) != expected_number
        ):
            raise FormalG0RuntimeError(f"formal G0 target signal is unavailable: {name}")
        rows.append({"name": name, "number": expected_number})
    if len({row["number"] for row in rows}) != len(rows):
        raise FormalG0RuntimeError("formal G0 target signal numbers are ambiguous")
    return rows


def _validate_target_signal_mask(value: object) -> dict[str, Any]:
    """Require SIGHUP/SIGINT/SIGTERM to be unblocked in the child."""

    expected = {
        "query": _TARGET_SIGNAL_QUERY,
        "target_signals": _target_signal_contract(),
        "blocked_target_signals": [],
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise FormalG0RuntimeError("formal G0 child target signal mask differs")
    return dict(value)


def _capture_target_signal_mask() -> dict[str, Any]:
    """Read the current mask with an empty SIG_BLOCK set, which is a no-op."""

    if not callable(getattr(signal, "pthread_sigmask", None)):
        raise FormalG0RuntimeError("platform lacks pthread_sigmask signal audit")
    try:
        current = signal.pthread_sigmask(signal.SIG_BLOCK, set())
    except BaseException as error:
        raise FormalG0RuntimeError("cannot read formal G0 child signal mask") from error
    if not isinstance(current, set):
        raise FormalG0RuntimeError("formal G0 child signal mask result differs")
    targets = _target_signal_contract()
    blocked_numbers = {int(item) for item in current}
    captured = {
        "query": _TARGET_SIGNAL_QUERY,
        "target_signals": targets,
        "blocked_target_signals": [
            dict(row) for row in targets if int(row["number"]) in blocked_numbers
        ],
    }
    return _validate_target_signal_mask(captured)


def capture_runtime_snapshot(
    role: str,
    *,
    evaluator_called: bool = False,
    evaluator_rc: int | None = None,
    initial_argv: Iterable[str] | None = None,
    initial_environment: Mapping[str, str] | None = None,
    evaluator_error: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Capture and self-hash the actual loaded runtime without timestamps."""

    role = _safe_role(role)
    if evaluator_called != isinstance(evaluator_rc, int):
        raise FormalG0RuntimeError("evaluator called/return-code contract differs")
    argv = list(sys.argv if initial_argv is None else initial_argv)
    if not argv or not all(isinstance(item, str) and item for item in argv):
        raise FormalG0RuntimeError("formal G0 sys.argv is malformed")
    process_argv = _assert_live_python_isolation(argv)
    environment = dict(os.environ if initial_environment is None else initial_environment)
    sealed_values = {
        "python_interpreter": sys.executable,
        "bootstrap": argv[0] if argv else "",
        "wrapper": environment.get(WRAPPER_ENV, ""),
        "evaluator_base": environment.get(BASE_ENV, ""),
        "evaluator_core": environment.get(CORE_ENV, ""),
    }
    sealed_sources = {
        label: sealed_source_identity(value, label)
        for label, value in sealed_values.items()
    }
    persistent_modules, generated_modules = _capture_modules(sealed_sources)
    persistent_maps = capture_persistent_maps(sealed_sources=sealed_sources)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "ACTUAL_RUNTIME_CAPTURED",
        "role": role,
        "evaluator_called": evaluator_called,
        "evaluator_rc": evaluator_rc,
        "evaluator_error": dict(evaluator_error) if evaluator_error else None,
        "isolated_python": {
            "isolated_flag": int(sys.flags.isolated),
            "ignore_environment_flag": int(sys.flags.ignore_environment),
            "no_user_site_flag": int(sys.flags.no_user_site),
            "dont_write_bytecode_flag": int(sys.flags.dont_write_bytecode),
            "hash_randomization_flag": int(sys.flags.hash_randomization),
            "bytecode_policy": (
                "DISABLED_BY_COMMAND_LINE_-B;"
                "PYTHONDONTWRITEBYTECODE_ENV_IGNORED_BY_-I"
            ),
            "hash_seed_policy": (
                "RANDOMIZED_BY_CPYTHON;PYTHONHASHSEED_ENV_IGNORED_BY_-I"
            ),
            "ignored_python_environment_options": list(
                _IGNORED_PYTHON_ENVIRONMENT_OPTIONS
            ),
        },
        "execution": {
            "sys_argv": argv,
            "process_argv": process_argv,
            "environment": {key: environment[key] for key in sorted(environment)},
            "target_signal_mask": _capture_target_signal_mask(),
        },
        "sealed_sources": sealed_sources,
        "versions": {
            "python": sys.version,
            "python_version_info": list(sys.version_info[:5]),
            "python_hexversion": int(sys.hexversion),
            "numpy": _version_value("numpy"),
            "opencv": _version_value("cv2"),
            "rosbag": _version_value("rosbag"),
            "genpy": _version_value("genpy"),
        },
        "persistent_modules": persistent_modules,
        "generated_genpy_modules": generated_modules,
        "persistent_proc_maps": persistent_maps,
        "native_loaded_elf_closure": _native_loaded_elf_closure(
            persistent_maps, sealed_sources
        ),
        SELF_HASH_FIELD: "",
    }
    payload[SELF_HASH_FIELD] = _receipt_hash(payload)
    return payload


def _exact_int(
    value: object, label: str, *, minimum: int = 0, maximum: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise FormalG0RuntimeError(f"{label} is not a valid integer")
    if maximum is not None and value > maximum:
        raise FormalG0RuntimeError(f"{label} exceeds its valid range")
    return value


def _validate_stat_record(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _STAT_KEYS:
        raise FormalG0RuntimeError(f"{label} stat field set differs")
    record = dict(value)
    for key in _STAT_KEYS:
        _exact_int(
            record[key],
            f"{label} stat {key}",
            maximum=0o7777 if key == "mode" else None,
        )
    return record


def _validate_file_identity(
    value: object,
    label: str,
    *,
    live_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _FILE_IDENTITY_KEYS:
        raise FormalG0RuntimeError(f"{label} file identity field set differs")
    record = dict(value)
    lexical = record.get("lexical_path")
    resolved = record.get("resolved_path")
    if (
        not isinstance(lexical, str)
        or not lexical.startswith("/")
        or os.path.normpath(lexical) != lexical
        or lexical.startswith("/proc/")
        or not isinstance(resolved, str)
        or not resolved.startswith("/")
        or os.path.normpath(resolved) != resolved
        or resolved.startswith("/proc/")
    ):
        raise FormalG0RuntimeError(f"{label} file paths are non-canonical")
    _exact_int(record.get("size_bytes"), f"{label} size")
    if _HASH_RE.fullmatch(str(record.get("sha256", ""))) is None:
        raise FormalG0RuntimeError(f"{label} sha256 is invalid")
    _validate_stat_record(record.get("stat"), label)
    symlink = record.get("symlink")
    if symlink is None:
        if resolved != lexical:
            raise FormalG0RuntimeError(f"{label} non-symlink resolved path differs")
    else:
        if not isinstance(symlink, Mapping) or set(symlink) != {
            "target", "target_sha256", "stat"
        }:
            raise FormalG0RuntimeError(f"{label} symlink record differs")
        target = symlink.get("target")
        if not isinstance(target, str) or not target:
            raise FormalG0RuntimeError(f"{label} symlink target is invalid")
        if symlink.get("target_sha256") != _sha256_bytes(os.fsencode(target)):
            raise FormalG0RuntimeError(f"{label} symlink target hash differs")
        _validate_stat_record(symlink.get("stat"), f"{label} symlink")
    observed = live_cache.get(lexical)
    if observed is None:
        observed = persistent_file_identity(lexical)
        live_cache[lexical] = observed
    if observed != record:
        raise FormalG0RuntimeError(f"{label} live file identity differs")
    return record


def _validate_sealed_sources(value: object) -> dict[str, Any]:
    roles = {
        "python_interpreter",
        "bootstrap",
        "wrapper",
        "evaluator_base",
        "evaluator_core",
    }
    if not isinstance(value, Mapping) or set(value) != roles:
        raise FormalG0RuntimeError("runtime receipt sealed-source set differs")
    result: dict[str, Any] = {}
    locators: set[str] = set()
    for role in sorted(roles):
        raw = value[role]
        if not isinstance(raw, Mapping) or set(raw) != {
            "locator", "seals", "size_bytes", "sha256", "stat"
        }:
            raise FormalG0RuntimeError(f"sealed source field set differs: {role}")
        record = dict(raw)
        locator = record.get("locator")
        if not isinstance(locator, str) or _PROC_FD_RE.fullmatch(locator) is None:
            raise FormalG0RuntimeError(f"sealed source locator differs: {role}")
        if locator in locators:
            raise FormalG0RuntimeError("sealed source locators are not unique")
        locators.add(locator)
        if record.get("seals") != _REQUIRED_SEALS:
            raise FormalG0RuntimeError(f"sealed source seals differ: {role}")
        _exact_int(record.get("size_bytes"), f"sealed source size {role}", minimum=1)
        if _HASH_RE.fullmatch(str(record.get("sha256", ""))) is None:
            raise FormalG0RuntimeError(f"sealed source hash differs: {role}")
        _validate_stat_record(record.get("stat"), f"sealed source {role}")
        result[role] = record
    return result


def _validate_versions(value: object) -> dict[str, Any]:
    keys = {
        "python",
        "python_version_info",
        "python_hexversion",
        "numpy",
        "opencv",
        "rosbag",
        "genpy",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise FormalG0RuntimeError("runtime version field set differs")
    result = dict(value)
    for key in ("python", "numpy", "opencv"):
        if not isinstance(result[key], str) or not result[key]:
            raise FormalG0RuntimeError(f"runtime version is absent: {key}")
    for key in ("rosbag", "genpy"):
        if result[key] is not None and (
            not isinstance(result[key], str) or not result[key]
        ):
            raise FormalG0RuntimeError(f"runtime optional version differs: {key}")
    version_info = result.get("python_version_info")
    if (
        not isinstance(version_info, list)
        or len(version_info) != 5
        or any(
            isinstance(version_info[index], bool)
            or not isinstance(version_info[index], int)
            for index in (0, 1, 2, 4)
        )
        or version_info[0] != 3
        or not isinstance(version_info[3], str)
        or version_info[3] not in {"alpha", "beta", "candidate", "final"}
    ):
        raise FormalG0RuntimeError("runtime Python version_info differs")
    _exact_int(result.get("python_hexversion"), "runtime Python hexversion", minimum=1)
    return result


def _validate_isolated_python(value: object) -> dict[str, Any]:
    expected = {
        "isolated_flag": 1,
        "ignore_environment_flag": 1,
        "no_user_site_flag": 1,
        "dont_write_bytecode_flag": 1,
        "hash_randomization_flag": 1,
        "bytecode_policy": (
            "DISABLED_BY_COMMAND_LINE_-B;"
            "PYTHONDONTWRITEBYTECODE_ENV_IGNORED_BY_-I"
        ),
        "hash_seed_policy": (
            "RANDOMIZED_BY_CPYTHON;PYTHONHASHSEED_ENV_IGNORED_BY_-I"
        ),
        "ignored_python_environment_options": list(
            _IGNORED_PYTHON_ENVIRONMENT_OPTIONS
        ),
    }
    if not isinstance(value, Mapping) or dict(value) != expected:
        raise FormalG0RuntimeError("effective isolated-Python contract differs")
    return dict(value)


def _validate_environment(
    value: object, role: str, sealed: Mapping[str, Mapping[str, Any]]
) -> dict[str, str]:
    expected_keys = set(_COMMON_ENVIRONMENT_KEYS)
    if role != "runtime_probe":
        expected_keys.add(OUTPUT_ENV)
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise FormalG0RuntimeError("runtime environment key set differs")
    environment = dict(value)
    if any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in environment.items()
    ):
        raise FormalG0RuntimeError("runtime environment value type differs")
    exact = {
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
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        ROLE_ENV: role,
    }
    for key, expected in exact.items():
        if environment.get(key) != expected:
            raise FormalG0RuntimeError(f"runtime environment differs: {key}")
    bindings = {
        WRAPPER_ENV: "wrapper",
        BASE_ENV: "evaluator_base",
        CORE_ENV: "evaluator_core",
        WRAPPER_BASE_ENV: "evaluator_base",
        WRAPPER_CORE_ENV: "evaluator_core",
    }
    for key, sealed_role in bindings.items():
        if environment.get(key) != sealed[sealed_role]["locator"]:
            raise FormalG0RuntimeError(f"runtime environment binding differs: {key}")
    if role != "runtime_probe" and _PROC_FD_RE.fullmatch(
        environment.get(OUTPUT_ENV, "")
    ) is None:
        raise FormalG0RuntimeError("runtime role output locator differs")
    return environment


def _one_option(argv: list[str], option: str) -> str:
    indices = [index for index, item in enumerate(argv) if item == option]
    if len(indices) != 1 or indices[0] + 1 >= len(argv):
        raise FormalG0RuntimeError(f"runtime argv option differs: {option}")
    return argv[indices[0] + 1]


def _validate_execution(
    value: object,
    role: str,
    sealed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "sys_argv", "process_argv", "environment", "target_signal_mask"
    }:
        raise FormalG0RuntimeError("runtime execution field set differs")
    execution = dict(value)
    sys_argv = execution.get("sys_argv")
    process_argv = execution.get("process_argv")
    if (
        not isinstance(sys_argv, list)
        or not sys_argv
        or not all(isinstance(item, str) and item for item in sys_argv)
        or not isinstance(process_argv, list)
        or not all(isinstance(item, str) and item for item in process_argv)
    ):
        raise FormalG0RuntimeError("runtime argv list differs")
    if sys_argv[0] != sealed["bootstrap"]["locator"] or process_argv != [
        sealed["python_interpreter"]["locator"], "-I", "-B", *sys_argv
    ]:
        raise FormalG0RuntimeError("runtime kernel/sys argv cross-binding differs")
    environment = _validate_environment(execution.get("environment"), role, sealed)
    _validate_target_signal_mask(execution.get("target_signal_mask"))
    if role == "runtime_probe":
        if (
            len(sys_argv) != 4
            or sys_argv[1] != PROBE_ARGUMENT
            or _PROC_FD_RE.fullmatch(sys_argv[2]) is None
            or not sys_argv[3].startswith("/")
        ):
            raise FormalG0RuntimeError("runtime probe argv differs")
    else:
        if PROBE_ARGUMENT in sys_argv:
            raise FormalG0RuntimeError("evaluator role argv contains probe mode")
        if _PROC_FD_RE.fullmatch(_one_option(sys_argv, "--reference-bag")) is None:
            raise FormalG0RuntimeError("evaluator reference bag argv differs")
        if not _one_option(sys_argv, "--reference-topic").startswith("/"):
            raise FormalG0RuntimeError("evaluator reference topic argv differs")
        if _one_option(sys_argv, "--output-dir") != environment[OUTPUT_ENV]:
            raise FormalG0RuntimeError("evaluator output argv/environment differs")
    return execution


def _validate_modules(
    value: object,
    sealed: Mapping[str, Mapping[str, Any]],
    live_cache: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise FormalG0RuntimeError("persistent module closure is not a list")
    rows: list[dict[str, Any]] = []
    sealed_by_locator = {
        str(record["locator"]): role for role, record in sealed.items()
    }
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != {
            "sys_modules_key",
            "module_name",
            "module_python_type",
            "module_file",
            "spec_origin",
            "module_cached",
            "file_identities",
            "sealed_source_bindings",
        }:
            raise FormalG0RuntimeError(f"persistent module row field set differs: {index}")
        row = dict(raw)
        for key in ("sys_modules_key", "module_name", "module_python_type"):
            if not isinstance(row[key], str) or not row[key]:
                raise FormalG0RuntimeError(f"persistent module text differs: {index}:{key}")
        identities = row.get("file_identities")
        bindings = row.get("sealed_source_bindings")
        if not isinstance(identities, Mapping) or not isinstance(bindings, Mapping):
            raise FormalG0RuntimeError(f"persistent module identities malformed: {index}")
        if not identities and not bindings:
            raise FormalG0RuntimeError(f"persistent module identities absent: {index}")
        expected_identity_fields: set[str] = set()
        expected_binding_fields: dict[str, str] = {}
        for field in _MODULE_PATH_FIELDS:
            path = row[field]
            kind = _module_path_kind(field, path)
            if kind == "persistent":
                expected_identity_fields.add(field)
            elif kind == "sealed_procfd":
                assert isinstance(path, str)
                sealed_role = sealed_by_locator.get(path)
                if sealed_role is None:
                    raise FormalG0RuntimeError(
                        f"persistent module procfd is not sealed: {index}:{field}"
                    )
                expected_binding_fields[field] = sealed_role
        if set(identities) != expected_identity_fields:
            raise FormalG0RuntimeError(f"persistent module identity keys differ: {index}")
        if dict(bindings) != expected_binding_fields:
            raise FormalG0RuntimeError(
                f"persistent module sealed bindings differ: {index}"
            )
        for field in sorted(expected_identity_fields):
            identity = _validate_file_identity(
                identities[field],
                f"persistent module {index} {field}",
                live_cache=live_cache,
            )
            if identity["lexical_path"] != row[field]:
                raise FormalG0RuntimeError(
                    f"persistent module identity path differs: {index}:{field}"
                )
        rows.append(row)
    keys = [row["sys_modules_key"] for row in rows]
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise FormalG0RuntimeError("persistent module ordering/uniqueness differs")
    return rows


def _validate_generated_modules(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise FormalG0RuntimeError("generated genpy closure is not a list")
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping) or set(raw) != {
            "module_python_type",
            "source_size_bytes",
            "source_sha256",
            "message_contracts",
        }:
            raise FormalG0RuntimeError(f"generated genpy row field set differs: {index}")
        row = dict(raw)
        if not isinstance(row["module_python_type"], str) or not row["module_python_type"]:
            raise FormalG0RuntimeError(f"generated genpy type differs: {index}")
        _exact_int(row["source_size_bytes"], f"generated genpy size {index}", minimum=1)
        if _HASH_RE.fullmatch(str(row["source_sha256"])) is None:
            raise FormalG0RuntimeError(f"generated genpy hash differs: {index}")
        contracts = row.get("message_contracts")
        if not isinstance(contracts, list) or not contracts:
            raise FormalG0RuntimeError(f"generated genpy contracts absent: {index}")
        canonical_contracts: list[tuple[str, str, str]] = []
        for contract_index, contract in enumerate(contracts):
            if not isinstance(contract, Mapping) or set(contract) != {
                "message_type", "md5sum", "full_text", "full_text_sha256"
            }:
                raise FormalG0RuntimeError(
                    f"generated message contract fields differ: {index}:{contract_index}"
                )
            message_type = contract.get("message_type")
            md5sum = contract.get("md5sum")
            full_text = contract.get("full_text")
            if (
                not isinstance(message_type, str)
                or not message_type
                or not isinstance(md5sum, str)
                or _MD5_RE.fullmatch(md5sum) is None
                or not isinstance(full_text, str)
                or contract.get("full_text_sha256")
                != _sha256_bytes(full_text.encode("utf-8"))
            ):
                raise FormalG0RuntimeError(
                    f"generated message contract value differs: {index}:{contract_index}"
                )
            canonical_contracts.append((message_type, md5sum, full_text))
        if canonical_contracts != sorted(canonical_contracts) or len(
            canonical_contracts
        ) != len(set(canonical_contracts)):
            raise FormalG0RuntimeError(
                f"generated message contract ordering differs: {index}"
            )
        rows.append(row)
    hashes = [row["source_sha256"] for row in rows]
    if hashes != sorted(hashes) or len(hashes) != len(set(hashes)):
        raise FormalG0RuntimeError("generated genpy ordering/uniqueness differs")
    # No random module name or /tmp/genpy path is an authority leaf.
    encoded = canonical_json_bytes({"rows": rows}).decode("utf-8")
    if "/tmp/genpy_" in encoded:
        raise FormalG0RuntimeError("generated genpy receipt leaked a random path")
    return rows


def _validate_maps(
    value: object,
    live_cache: dict[str, dict[str, Any]],
    sealed: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "files", "rows", "sealed_rows"
    }:
        raise FormalG0RuntimeError("persistent map field set differs")
    files_raw = value.get("files")
    rows_raw = value.get("rows")
    sealed_rows_raw = value.get("sealed_rows")
    if (
        not isinstance(files_raw, list)
        or not isinstance(rows_raw, list)
        or not isinstance(sealed_rows_raw, list)
    ):
        raise FormalG0RuntimeError("persistent map closure is malformed")
    files = [
        _validate_file_identity(
            raw, f"mapped file {index}", live_cache=live_cache
        )
        for index, raw in enumerate(files_raw)
    ]
    paths = [record["lexical_path"] for record in files]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise FormalG0RuntimeError("mapped file ordering/uniqueness differs")
    by_path = {record["lexical_path"]: record for record in files}
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(rows_raw):
        if not isinstance(raw, Mapping) or set(raw) != {
            "permissions",
            "offset_hex",
            "device",
            "inode",
            "file_sha256",
            "file_size_bytes",
            "lexical_path",
        }:
            raise FormalG0RuntimeError(f"mapped row field set differs: {index}")
        row = dict(raw)
        if (
            not isinstance(row["permissions"], str)
            or _MAP_PERMISSION_RE.fullmatch(row["permissions"]) is None
            or not isinstance(row["offset_hex"], str)
            or _HEX_RE.fullmatch(row["offset_hex"]) is None
            or not isinstance(row["device"], str)
            or _DEVICE_RE.fullmatch(row["device"]) is None
            or not isinstance(row["lexical_path"], str)
        ):
            raise FormalG0RuntimeError(f"mapped row lexical value differs: {index}")
        _exact_int(row["inode"], f"mapped row inode {index}", minimum=1)
        _exact_int(row["file_size_bytes"], f"mapped row size {index}")
        record = by_path.get(row["lexical_path"])
        if record is None:
            raise FormalG0RuntimeError(f"mapped row lacks file identity: {index}")
        expected_device = (
            os.major(record["stat"]["device"]),
            os.minor(record["stat"]["device"]),
        )
        if (
            row["file_sha256"] != record["sha256"]
            or row["file_size_bytes"] != record["size_bytes"]
            or row["inode"] != record["stat"]["inode"]
            or _device_pair(row["device"], f"mapped row {index}")
            != expected_device
        ):
            raise FormalG0RuntimeError(f"mapped row/file cross-binding differs: {index}")
        rows.append(row)
    ordering = lambda row: (
        row["lexical_path"],
        row["offset_hex"],
        row["permissions"],
        row["device"],
        row["inode"],
    )
    encoded_rows = [canonical_json_bytes(row) for row in rows]
    if rows != sorted(rows, key=ordering) or len(encoded_rows) != len(set(encoded_rows)):
        raise FormalG0RuntimeError("mapped row ordering/uniqueness differs")
    sealed_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(sealed_rows_raw):
        if not isinstance(raw, Mapping) or set(raw) != {
            "permissions",
            "offset_hex",
            "device",
            "inode",
            "sealed_source_role",
            "file_sha256",
            "file_size_bytes",
        }:
            raise FormalG0RuntimeError(f"sealed mapped row fields differ: {index}")
        row = dict(raw)
        role = row.get("sealed_source_role")
        record = sealed.get(str(role)) if isinstance(role, str) else None
        if (
            not isinstance(row.get("permissions"), str)
            or _MAP_PERMISSION_RE.fullmatch(str(row["permissions"])) is None
            or not isinstance(row.get("offset_hex"), str)
            or _HEX_RE.fullmatch(str(row["offset_hex"])) is None
            or not isinstance(row.get("device"), str)
            or _DEVICE_RE.fullmatch(str(row["device"])) is None
            or not isinstance(record, Mapping)
        ):
            raise FormalG0RuntimeError(f"sealed mapped row value differs: {index}")
        inode = _exact_int(
            row.get("inode"), f"sealed mapped row inode {index}", minimum=1
        )
        _exact_int(
            row.get("file_size_bytes"),
            f"sealed mapped row size {index}",
            minimum=1,
        )
        source_stat = record["stat"]
        if (
            row.get("file_sha256") != record["sha256"]
            or row.get("file_size_bytes") != record["size_bytes"]
            or inode != source_stat["inode"]
            or _device_pair(str(row["device"]), f"sealed mapped row {index}")
            != (
                os.major(source_stat["device"]),
                os.minor(source_stat["device"]),
            )
        ):
            raise FormalG0RuntimeError(
                f"sealed mapped row/source cross-binding differs: {index}"
            )
        sealed_rows.append(row)
    sealed_ordering = lambda row: (
        row["sealed_source_role"],
        row["offset_hex"],
        row["permissions"],
        row["device"],
        row["inode"],
    )
    encoded_sealed = [canonical_json_bytes(row) for row in sealed_rows]
    if sealed_rows != sorted(sealed_rows, key=sealed_ordering) or len(
        encoded_sealed
    ) != len(set(encoded_sealed)):
        raise FormalG0RuntimeError("sealed mapped row ordering/uniqueness differs")
    return {"files": files, "rows": rows, "sealed_rows": sealed_rows}


def validate_runtime_receipt(
    payload: Mapping[str, Any], *, expected_role: str | None = None
) -> dict[str, Any]:
    """Deep, fail-closed validation for child, governor, and POST checks."""

    if not isinstance(payload, Mapping):
        raise FormalG0RuntimeError("runtime receipt is not a mapping")
    value = dict(payload)
    required = {
        "schema_version",
        "status",
        "role",
        "evaluator_called",
        "evaluator_rc",
        "evaluator_error",
        "isolated_python",
        "execution",
        "sealed_sources",
        "versions",
        "persistent_modules",
        "generated_genpy_modules",
        "persistent_proc_maps",
        "native_loaded_elf_closure",
        SELF_HASH_FIELD,
    }
    if set(value) != required:
        raise FormalG0RuntimeError("runtime receipt field set differs")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status") != "ACTUAL_RUNTIME_CAPTURED"
    ):
        raise FormalG0RuntimeError("runtime receipt schema/status differs")
    role = _safe_role(value.get("role"))
    if expected_role is not None and role != expected_role:
        raise FormalG0RuntimeError("runtime receipt role differs")
    called = value.get("evaluator_called")
    rc = value.get("evaluator_rc")
    error = value.get("evaluator_error")
    if role == "runtime_probe":
        if called is not False or rc is not None or error is not None:
            raise FormalG0RuntimeError("runtime probe evaluator outcome differs")
    else:
        if called is not True or isinstance(rc, bool) or not isinstance(rc, int):
            raise FormalG0RuntimeError("runtime role evaluator outcome differs")
        if error is not None:
            if (
                not isinstance(error, Mapping)
                or set(error) != {"class", "message"}
                or not all(isinstance(item, str) and item for item in error.values())
                or rc == 0
            ):
                raise FormalG0RuntimeError("runtime role evaluator error differs")
    digest = value.get(SELF_HASH_FIELD)
    if (
        not isinstance(digest, str)
        or _HASH_RE.fullmatch(digest) is None
        or digest != _receipt_hash(value)
    ):
        raise FormalG0RuntimeError("runtime receipt self-hash differs")
    _validate_isolated_python(value.get("isolated_python"))
    sealed = _validate_sealed_sources(value.get("sealed_sources"))
    _validate_execution(value.get("execution"), role, sealed)
    _validate_versions(value.get("versions"))
    live_cache: dict[str, dict[str, Any]] = {}
    _validate_modules(value.get("persistent_modules"), sealed, live_cache)
    _validate_generated_modules(value.get("generated_genpy_modules"))
    maps = _validate_maps(value.get("persistent_proc_maps"), live_cache, sealed)
    native = value.get("native_loaded_elf_closure")
    if not isinstance(native, list) or native != _native_loaded_elf_closure(
        maps, sealed
    ):
        raise FormalG0RuntimeError("native loaded ELF closure is not exact")
    return value


def _stable_source_bytes(path: Path, label: str) -> bytes:
    lexical = os.fspath(Path(path))
    if not os.path.isabs(lexical) or os.path.normpath(lexical) != lexical:
        raise FormalG0RuntimeError(f"{label} path is not canonical absolute")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lexical, flags)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise FormalG0RuntimeError(f"{label} is not a regular file")
        content = _read_fd(fd, int(before.st_size))
        after = os.fstat(fd)
        named = os.lstat(lexical)
        if (
            _path_lstat_key(before) != _path_lstat_key(after)
            or not stat.S_ISREG(named.st_mode)
            or int(named.st_dev) != int(before.st_dev)
            or int(named.st_ino) != int(before.st_ino)
        ):
            raise FormalG0RuntimeError(f"{label} changed while snapshotting")
        return content
    finally:
        os.close(fd)


def _semantic_sealed_sources(value: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, Any] = {}
    for label in sorted(value):
        record = value[label]
        if not isinstance(record, Mapping):
            raise FormalG0RuntimeError("sealed source semantic record is malformed")
        rows[label] = {
            "seals": record.get("seals"),
            "size_bytes": record.get("size_bytes"),
            "sha256": record.get("sha256"),
        }
    return rows


def _runtime_closure_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Scientific runtime leaves common to probe and full evaluation roles."""

    return {
        "isolated_python": dict(value["isolated_python"]),
        "sealed_sources": _semantic_sealed_sources(value["sealed_sources"]),
        "versions": dict(value["versions"]),
        "persistent_modules": list(value["persistent_modules"]),
        "generated_genpy_modules": list(value["generated_genpy_modules"]),
        "persistent_proc_maps": dict(value["persistent_proc_maps"]),
        "native_loaded_elf_closure": list(value["native_loaded_elf_closure"]),
    }


def runtime_semantic_identity(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only role name and its retained output-directory locator.

    Every scientific/input/code procfd, sealed-source stat leaf, module, map,
    and version remains exact.  This intentionally does not use a generic
    procfd regex replacement.
    """

    validated = validate_runtime_receipt(value)
    if validated["role"] not in {"primary", "verification"}:
        raise FormalG0RuntimeError("semantic role comparison requires evaluator role")
    clone = json.loads(canonical_json_bytes(validated))
    clone.pop(SELF_HASH_FIELD)
    clone["role"] = "${ROLE}"
    execution = clone["execution"]
    environment = execution["environment"]
    output_locator = environment[OUTPUT_ENV]
    environment[ROLE_ENV] = "${ROLE}"
    environment[OUTPUT_ENV] = "${ROLE_OUTPUT_DIRFD}"
    for field in ("sys_argv", "process_argv"):
        argv = execution[field]
        indices = [index for index, item in enumerate(argv) if item == "--output-dir"]
        if len(indices) != 1 or indices[0] + 1 >= len(argv):
            raise FormalG0RuntimeError("semantic argv output option differs")
        if argv[indices[0] + 1] != output_locator:
            raise FormalG0RuntimeError("semantic argv output locator differs")
        argv[indices[0] + 1] = "${ROLE_OUTPUT_DIRFD}"
    return clone


def validate_freeze_runtime_static(value: Mapping[str, Any]) -> dict[str, Any]:
    """Process-free validation of a stored representative closure probe."""

    validated = validate_runtime_receipt(value, expected_role="runtime_probe")
    if validated.get("evaluator_called") is not False or validated.get("evaluator_rc") is not None:
        raise FormalG0RuntimeError("freeze runtime probe executed evaluator")
    if validated.get("evaluator_error") is not None:
        raise FormalG0RuntimeError("freeze runtime probe has an error outcome")
    if not validated["persistent_modules"] or not validated["persistent_proc_maps"]["rows"]:
        raise FormalG0RuntimeError("freeze probe runtime closure is empty")
    if not validated["generated_genpy_modules"]:
        raise FormalG0RuntimeError("freeze probe did not trigger generated ROS messages")
    if not validated["native_loaded_elf_closure"]:
        raise FormalG0RuntimeError("freeze probe native runtime closure is empty")
    return validated


def _rows_by_unique_key(
    rows: object, key: str, label: str
) -> dict[str, Mapping[str, Any]]:
    if not isinstance(rows, list):
        raise FormalG0RuntimeError(f"{label} is not a list")
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get(key), str):
            raise FormalG0RuntimeError(f"{label} row key is malformed")
        item_key = str(row[key])
        if item_key in result:
            raise FormalG0RuntimeError(f"{label} key is duplicated")
        result[item_key] = row
    return result


def _probe_module_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize only registered sealed procfd locators across probe/run."""

    clone = json.loads(canonical_json_bytes(row))
    bindings = clone.get("sealed_source_bindings")
    if not isinstance(bindings, Mapping):
        raise FormalG0RuntimeError("probe module sealed bindings are malformed")
    for field, role in bindings.items():
        if field not in _MODULE_PATH_FIELDS or not isinstance(role, str):
            raise FormalG0RuntimeError("probe module sealed binding differs")
        clone[field] = f"${{SEALED_SOURCE:{role}}}"
    return clone


def _probe_sealed_map_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """Remove only memfd-allocation device/inode from freeze-probe rows."""

    clone = dict(row)
    clone.pop("device", None)
    clone.pop("inode", None)
    return clone


def _assert_expected_closure_subset(
    actual: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    """Bind probe-observed leaves while permitting workload-only additions."""

    for key in ("isolated_python", "sealed_sources", "versions"):
        if _runtime_closure_identity(actual)[key] != _runtime_closure_identity(expected)[key]:
            raise FormalG0RuntimeError(f"actual evaluator runtime {key} differs")
    expected_modules = _rows_by_unique_key(
        expected["persistent_modules"], "sys_modules_key", "expected persistent modules"
    )
    actual_modules = _rows_by_unique_key(
        actual["persistent_modules"], "sys_modules_key", "actual persistent modules"
    )
    for key, row in expected_modules.items():
        actual_row = actual_modules.get(key)
        if actual_row is None or _probe_module_identity(actual_row) != _probe_module_identity(row):
            raise FormalG0RuntimeError(f"actual evaluator module differs: {key}")
    expected_generated = _rows_by_unique_key(
        expected["generated_genpy_modules"],
        "source_sha256",
        "expected generated genpy modules",
    )
    actual_generated = _rows_by_unique_key(
        actual["generated_genpy_modules"],
        "source_sha256",
        "actual generated genpy modules",
    )
    for key, row in expected_generated.items():
        if actual_generated.get(key) != row:
            raise FormalG0RuntimeError(
                f"actual evaluator generated ROS module differs: {key}"
            )
    expected_maps = expected["persistent_proc_maps"]
    actual_maps = actual["persistent_proc_maps"]
    if not isinstance(expected_maps, Mapping) or not isinstance(actual_maps, Mapping):
        raise FormalG0RuntimeError("runtime mapped closure is malformed")
    expected_files = _rows_by_unique_key(
        expected_maps.get("files"), "lexical_path", "expected mapped files"
    )
    actual_files = _rows_by_unique_key(
        actual_maps.get("files"), "lexical_path", "actual mapped files"
    )
    for key, row in expected_files.items():
        if actual_files.get(key) != row:
            raise FormalG0RuntimeError(f"actual mapped file differs: {key}")
    expected_rows = {
        canonical_json_bytes(dict(row))
        for row in expected_maps.get("rows", [])
        if isinstance(row, Mapping)
    }
    actual_rows = {
        canonical_json_bytes(dict(row))
        for row in actual_maps.get("rows", [])
        if isinstance(row, Mapping)
    }
    if len(expected_rows) != len(expected_maps.get("rows", [])) or len(actual_rows) != len(actual_maps.get("rows", [])):
        raise FormalG0RuntimeError("runtime mapped rows are malformed or duplicated")
    if not expected_rows.issubset(actual_rows):
        raise FormalG0RuntimeError("actual mapped rows lack frozen probe closure")
    expected_sealed_rows = {
        canonical_json_bytes(_probe_sealed_map_identity(row))
        for row in expected_maps.get("sealed_rows", [])
        if isinstance(row, Mapping)
    }
    actual_sealed_rows = {
        canonical_json_bytes(_probe_sealed_map_identity(row))
        for row in actual_maps.get("sealed_rows", [])
        if isinstance(row, Mapping)
    }
    if len(expected_sealed_rows) != len(expected_maps.get("sealed_rows", [])) or len(
        actual_sealed_rows
    ) != len(actual_maps.get("sealed_rows", [])):
        raise FormalG0RuntimeError("runtime sealed mapped rows are malformed or duplicated")
    if not expected_sealed_rows.issubset(actual_sealed_rows):
        raise FormalG0RuntimeError("actual sealed mappings lack frozen probe closure")
    expected_native = {
        canonical_json_bytes(dict(row))
        for row in expected["native_loaded_elf_closure"]
        if isinstance(row, Mapping)
    }
    actual_native = {
        canonical_json_bytes(dict(row))
        for row in actual["native_loaded_elf_closure"]
        if isinstance(row, Mapping)
    }
    if len(expected_native) != len(expected["native_loaded_elf_closure"]) or len(
        actual_native
    ) != len(actual["native_loaded_elf_closure"]):
        raise FormalG0RuntimeError("native loaded closure is malformed or duplicated")
    if not expected_native.issubset(actual_native):
        raise FormalG0RuntimeError("actual native closure lacks frozen probe closure")


def validate_runtime_receipt_static(
    value: Mapping[str, Any],
    *,
    role: str,
    expected_closure: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one role and bind its actual closure to the frozen probe."""

    expected = validate_freeze_runtime_static(expected_closure)
    actual = validate_runtime_receipt(value, expected_role=role)
    if actual.get("evaluator_called") is not True or actual.get("evaluator_rc") != 0:
        raise FormalG0RuntimeError("formal evaluator role did not return zero")
    if actual.get("evaluator_error") is not None:
        raise FormalG0RuntimeError("formal evaluator role recorded an exception")
    _assert_expected_closure_subset(actual, expected)
    return actual


def capture_freeze_runtime(
    *,
    root: Path,
    python: Path,
    wrapper: Path,
    base: Path,
    core: Path,
    reference_bag: Path,
    reference_topic: str,
    environment_template: Mapping[str, str],
) -> dict[str, Any]:
    """Run the sole representative, non-evaluator closure probe for freeze."""

    del root  # All supplied paths are required to be canonical absolute below.
    if not isinstance(reference_topic, str) or not reference_topic.startswith("/"):
        raise FormalG0RuntimeError("freeze-probe reference topic is invalid")
    source_paths = {
        "python": Path(python),
        "bootstrap": Path(__file__),
        "wrapper": Path(wrapper),
        "base": Path(base),
        "core": Path(core),
    }
    contents = {
        label: _stable_source_bytes(path, f"freeze-probe {label}")
        for label, path in source_paths.items()
    }
    leases: list[int] = []
    bag_fd = -1
    try:
        for label in ("python", "bootstrap", "wrapper", "base", "core"):
            leases.append(
                _sealed_memfd(
                    f"aquafe_formal_g0_probe_{label}",
                    contents[label],
                    executable=label == "python",
                )
            )
        python_fd, bootstrap_fd, wrapper_fd, base_fd, core_fd = leases
        bag_path = os.fspath(Path(reference_bag))
        if not os.path.isabs(bag_path) or os.path.normpath(bag_path) != bag_path:
            raise FormalG0RuntimeError("freeze-probe bag path is non-canonical")
        bag_fd = os.open(
            bag_path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        bag_before = os.fstat(bag_fd)
        if not stat.S_ISREG(bag_before.st_mode):
            raise FormalG0RuntimeError("freeze-probe bag is not regular")
        mapping = {
            "${EPOCH_WRAPPER_PROCFD}": f"/proc/self/fd/{wrapper_fd}",
            "${EVALUATOR_BASE_PROCFD}": f"/proc/self/fd/{base_fd}",
            "${TRAJECTORY_CORE_PROCFD}": f"/proc/self/fd/{core_fd}",
            "${ROLE_OUTPUT_DIRFD}": "${PROBE_NO_OUTPUT}",
        }
        environment: dict[str, str] = {}
        for key, raw in environment_template.items():
            rendered = str(raw)
            for placeholder, actual in mapping.items():
                rendered = rendered.replace(placeholder, actual)
            environment[str(key)] = rendered
        environment[ROLE_ENV] = "runtime_probe"
        environment.pop(OUTPUT_ENV, None)
        process = subprocess.run(
            [
                f"/proc/self/fd/{python_fd}",
                "-I",
                "-B",
                f"/proc/self/fd/{bootstrap_fd}",
                PROBE_ARGUMENT,
                f"/proc/self/fd/{bag_fd}",
                reference_topic,
            ],
            check=False,
            cwd="/",
            env=environment,
            pass_fds=tuple([*leases, bag_fd]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        bag_after = os.fstat(bag_fd)
        bag_named = os.lstat(bag_path)
        if (
            _path_lstat_key(bag_before) != _path_lstat_key(bag_after)
            or not stat.S_ISREG(bag_named.st_mode)
            or int(bag_named.st_dev) != int(bag_before.st_dev)
            or int(bag_named.st_ino) != int(bag_before.st_ino)
        ):
            raise FormalG0RuntimeError("freeze-probe bag changed during probe")
        if process.returncode != 0:
            detail = process.stderr.decode("utf-8", "replace")[-2000:]
            raise FormalG0RuntimeError(
                f"freeze runtime probe failed rc={process.returncode}: {detail}"
            )
        try:
            payload = json.loads(process.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FormalG0RuntimeError("freeze runtime probe returned invalid JSON") from error
        return validate_freeze_runtime_static(payload)
    finally:
        if bag_fd >= 0:
            os.close(bag_fd)
        for descriptor in leases:
            os.close(descriptor)


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise FormalG0RuntimeError("short write of runtime receipt")
        view = view[written:]


def write_runtime_receipt_exclusive(directory_fd: int, payload: Mapping[str, Any]) -> None:
    """Write the fixed receipt name by openat/O_EXCL under a held directory."""

    info = os.fstat(directory_fd)
    if not stat.S_ISDIR(info.st_mode):
        raise FormalG0RuntimeError("role output fd is not a directory")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(RECEIPT_FILENAME, flags, 0o600, dir_fd=directory_fd)
    try:
        _write_all(fd, canonical_json_bytes(payload))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.fsync(directory_fd)


def _load_wrapper(proc_path: str) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("formal_g0_epoch_wrapper", proc_path)
    spec = importlib.util.spec_from_loader("formal_g0_epoch_wrapper", loader)
    if spec is None:
        raise FormalG0RuntimeError("cannot construct sealed wrapper spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    loader.exec_module(module)
    return module


def _error_record(error: BaseException) -> dict[str, str]:
    return {
        "class": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error),
    }


def main() -> int:
    initial_argv = list(sys.argv)
    initial_environment = dict(os.environ)
    if not initial_argv:
        raise FormalG0RuntimeError("formal G0 bootstrap argv is absent")
    # Check effective flags and the kernel-visible command line before any
    # supplied wrapper/base/core source byte is executed.
    _assert_live_python_isolation(initial_argv)
    role = initial_environment.get(ROLE_ENV, "")
    probe = len(initial_argv) == 4 and initial_argv[1] == PROBE_ARGUMENT
    if probe:
        role = "runtime_probe"
    else:
        _safe_role(role)
    wrapper_path = initial_environment.get(WRAPPER_ENV, "")
    base_path = initial_environment.get(BASE_ENV, "")
    core_path = initial_environment.get(CORE_ENV, "")
    # Validate all sealed sources before executing any supplied source bytes.
    sealed_source_identity(sys.executable, "python_interpreter")
    sealed_source_identity(initial_argv[0], "bootstrap")
    sealed_source_identity(wrapper_path, "wrapper")
    sealed_source_identity(base_path, "evaluator_base")
    sealed_source_identity(core_path, "evaluator_core")
    os.environ[WRAPPER_BASE_ENV] = base_path
    os.environ[WRAPPER_CORE_ENV] = core_path
    wrapper = _load_wrapper(wrapper_path)
    if probe:
        cv2 = __import__("cv2")
        numpy = __import__("numpy")
        rosbag = __import__("rosbag")
        bag_path = initial_argv[2]
        reference_topic = initial_argv[3]
        _procfd_number(bag_path, "runtime-probe reference bag")
        if not reference_topic.startswith("/"):
            raise FormalG0RuntimeError("runtime-probe reference topic is invalid")
        # Trigger the lazy native numerical and ROS message-generation closure
        # reached by the formal evaluator.  Reading exactly one bound reference
        # message is sufficient because every row on this topic has one type.
        numpy.linalg.svd(numpy.eye(3, dtype=float))
        cv2.setNumThreads(1)
        with rosbag.Bag(bag_path) as bag:
            first = next(bag.read_messages(topics=[reference_topic]), None)
        if first is None:
            raise FormalG0RuntimeError("runtime-probe reference topic is empty")
        receipt = capture_runtime_snapshot(
            role,
            evaluator_called=False,
            evaluator_rc=None,
            initial_argv=initial_argv,
            initial_environment=initial_environment,
        )
        sys.stdout.buffer.write(canonical_json_bytes(receipt))
        return 0
    output_fd = _procfd_number(initial_environment.get(OUTPUT_ENV, ""), "role output")
    entrypoint = getattr(wrapper, "main", None)
    if not callable(entrypoint):
        raise FormalG0RuntimeError("sealed epoch wrapper lacks main()")
    sys.argv = [wrapper_path, *initial_argv[1:]]
    evaluator_error: dict[str, str] | None = None
    try:
        raw_rc = entrypoint()
        evaluator_rc = int(raw_rc) if raw_rc is not None else 0
    except SystemExit as error:
        evaluator_rc = int(error.code) if isinstance(error.code, int) else 1
        evaluator_error = _error_record(error)
    except KeyboardInterrupt as error:
        evaluator_rc = 130
        evaluator_error = _error_record(error)
    except BaseException as error:
        evaluator_rc = 70
        evaluator_error = _error_record(error)
    finally:
        sys.argv = initial_argv
    receipt = capture_runtime_snapshot(
        role,
        evaluator_called=True,
        evaluator_rc=evaluator_rc,
        initial_argv=initial_argv,
        initial_environment=initial_environment,
        evaluator_error=evaluator_error,
    )
    validate_runtime_receipt(receipt, expected_role=role)
    write_runtime_receipt_exclusive(output_fd, receipt)
    if evaluator_error is not None:
        sys.stderr.write(
            f"FORMAL_G0_EVALUATOR_ERROR: {evaluator_error['class']}: "
            f"{evaluator_error['message']}\n"
        )
    return evaluator_rc


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FormalG0RuntimeError as error:
        sys.stderr.write(f"FORMAL_G0_RUNTIME_FAIL_CLOSED: {error}\n")
        raise SystemExit(74)
