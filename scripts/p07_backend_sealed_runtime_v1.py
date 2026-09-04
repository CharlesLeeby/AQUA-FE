#!/usr/bin/env python3
"""Execute one P07 Python entrypoint from an inherited sealed runtime bundle.

This bootstrap intentionally has no project-local imports.  The serial
controller executes this file through its sealed memfd and supplies an exact
JSON manifest of the remaining sealed modules.  A private meta-path finder
serves only those modules; an unknown ``scripts.*`` import therefore fails
closed instead of falling back to the mutable workspace.
"""

from __future__ import annotations

import fcntl
import hashlib
import importlib.abc
import importlib.util
import json
import os
import stat
import sys
import types
from typing import Any


ENVIRONMENT_KEY = "AQUAFE_P07_SEALED_RUNTIME_V1"
SCHEMA = "isj-p07-backend-sealed-runtime-v1"
REQUIRED_SEALS = (
    fcntl.F_SEAL_WRITE
    | fcntl.F_SEAL_GROW
    | fcntl.F_SEAL_SHRINK
    | fcntl.F_SEAL_SEAL
)


class SealedRuntimeError(RuntimeError):
    """The inherited source bundle is absent, mutable, or inconsistent."""


def _hash_fd(fd: int, size: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not chunk:
            raise SealedRuntimeError("short read from sealed runtime fd")
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _load_manifest() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    raw = os.environ.get(ENVIRONMENT_KEY)
    if not raw:
        raise SealedRuntimeError("sealed runtime manifest is absent")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SealedRuntimeError("sealed runtime manifest is invalid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "execution_lock_sha256",
        "entries",
    }:
        raise SealedRuntimeError("sealed runtime manifest shape differs")
    if payload.get("schema_version") != SCHEMA:
        raise SealedRuntimeError("sealed runtime manifest schema differs")
    lock_hash = payload.get("execution_lock_sha256")
    if (
        not isinstance(lock_hash, str)
        or len(lock_hash) != 64
        or any(char not in "0123456789abcdef" for char in lock_hash)
    ):
        raise SealedRuntimeError("sealed runtime execution-lock hash is invalid")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise SealedRuntimeError("sealed runtime manifest has no entries")
    by_role: dict[str, dict[str, Any]] = {}
    by_module: dict[str, dict[str, Any]] = {}
    required = {
        "role",
        "path",
        "sha256",
        "size_bytes",
        "fd",
        "module",
        "memfd_name",
    }
    for raw_entry in entries:
        if not isinstance(raw_entry, dict) or set(raw_entry) != required:
            raise SealedRuntimeError("sealed runtime entry shape differs")
        entry = dict(raw_entry)
        role = entry.get("role")
        path = entry.get("path")
        digest = entry.get("sha256")
        size = entry.get("size_bytes")
        fd = entry.get("fd")
        module = entry.get("module")
        memfd_name = entry.get("memfd_name")
        if (
            not isinstance(role, str)
            or not role
            or role in by_role
            or not isinstance(path, str)
            or not path
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(char not in "0123456789abcdef" for char in digest)
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or isinstance(fd, bool)
            or not isinstance(fd, int)
            or fd < 3
            or (module is not None and (not isinstance(module, str) or not module.startswith("scripts.")))
            or not isinstance(memfd_name, str)
            or not memfd_name.startswith("aquafe_p07_")
        ):
            raise SealedRuntimeError("sealed runtime entry value is invalid")
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise SealedRuntimeError(f"sealed runtime fd identity differs: {role}")
        if fcntl.fcntl(fd, fcntl.F_GET_SEALS) != REQUIRED_SEALS:
            raise SealedRuntimeError(f"runtime fd is not fully sealed: {role}")
        if _hash_fd(fd, size) != digest:
            raise SealedRuntimeError(f"sealed runtime fd hash differs: {role}")
        by_role[role] = entry
        if module is not None:
            if module in by_module:
                raise SealedRuntimeError(f"duplicate sealed Python module: {module}")
            by_module[module] = entry
    return by_role, by_module


class _Loader(importlib.abc.Loader):
    def __init__(self, entry: dict[str, Any]):
        self.entry = entry

    def create_module(self, spec: Any) -> None:
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        fd = int(self.entry["fd"])
        size = int(self.entry["size_bytes"])
        source = bytearray()
        offset = 0
        while offset < size:
            chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
            if not chunk:
                raise SealedRuntimeError("short read while loading sealed source")
            source.extend(chunk)
            offset += len(chunk)
        filename = str(self.entry["path"])
        module.__file__ = filename
        exec(compile(bytes(source), filename, "exec"), module.__dict__)


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, modules: dict[str, dict[str, Any]]):
        self.modules = modules

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> Any:
        entry = self.modules.get(fullname)
        if entry is None:
            return None
        loader = _Loader(entry)
        return importlib.util.spec_from_loader(
            fullname,
            loader,
            origin=str(entry["path"]),
        )


def main() -> int:
    if len(sys.argv) < 2:
        raise SealedRuntimeError("missing sealed target module")
    _roles, modules = _load_manifest()
    target = sys.argv[1]
    if target not in modules:
        raise SealedRuntimeError(f"target is not in sealed runtime: {target}")

    package = types.ModuleType("scripts")
    package.__package__ = "scripts"
    package.__path__ = []  # type: ignore[attr-defined]
    package.__file__ = "<sealed-runtime-package>"
    sys.modules["scripts"] = package
    sys.meta_path.insert(0, _Finder(modules))

    module = __import__(target, fromlist=["main"])
    entrypoint = getattr(module, "main", None)
    if not callable(entrypoint):
        raise SealedRuntimeError(f"sealed target lacks main(): {target}")
    sys.argv = [str(modules[target]["path"]), *sys.argv[2:]]
    result = entrypoint()
    return int(result) if result is not None else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SealedRuntimeError as error:
        print(f"P07_SEALED_RUNTIME_FAIL_CLOSED: {error}", file=sys.stderr)
        raise SystemExit(64)
