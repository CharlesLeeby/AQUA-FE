#!/usr/bin/env python3
"""Write-once, post-result exploratory G0 evaluation for the frozen r4 pair.

This controller never launches a detector or VINS.  ``write-freeze`` is the
only action allowed to perform the representative runtime-closure probe.
``run`` starts exactly two evaluator roles (primary and verification), once
each and without retry.  ``seal-post`` and every check action are process-free.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import copy
import csv
from decimal import Decimal, localcontext, ROUND_HALF_EVEN
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import threading
from typing import Any, Mapping, Sequence

_OUTER_CARRIER_SOURCE = """import hashlib,os,re,stat,sys
p=sys.argv[1]
h=sys.argv[2]
a=sys.argv[3:]
if len(sys.argv)!=5 or a[0]!='--action' or a[1] not in {'preview-contract','write-freeze','check-start','run','seal-post','check-post'} or re.fullmatch(r'[0-9a-f]{64}',h) is None or not os.path.isabs(p) or os.path.normpath(p)!=p or os.path.realpath(p)!=p:
 raise RuntimeError('formal G0 carrier arguments differ')
f=os.open(p,os.O_RDONLY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0))
try:
 before=os.fstat(f)
 if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:
  raise RuntimeError('formal G0 carrier source is not a direct regular file')
 chunks=[]
 offset=0
 while offset<before.st_size:
  chunk=os.pread(f,min(1048576,before.st_size-offset),offset)
  if not chunk:
   raise RuntimeError('formal G0 carrier source short read')
  chunks.append(chunk)
  offset+=len(chunk)
 data=b''.join(chunks)
 after=os.fstat(f)
 named=os.lstat(p)
 key=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_nlink,x.st_uid,x.st_gid,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
 if key(before)!=key(after) or key(before)!=key(named) or hashlib.sha256(data).hexdigest()!=h:
  raise RuntimeError('formal G0 carrier source identity/hash differs')
 code=compile(data,p,'exec',dont_inherit=True)
 binding={'fd':f,'source_bytes':data,'stat_identity':key(before),'sha256':h,'code':code,'carrier_source':sys.argv[0]}
 namespace=globals()
 namespace.update({'__name__':'__main__','__file__':p,'__package__':None,'__spec__':None,'__loader__':None,'__cached__':None,'_AQUAFE_G0_OUTER_BINDING':binding})
 sys.argv=[p,*a]
 exec(code,namespace,namespace)
finally:
 os.close(f)
"""
_OUTER_CARRIER_BINDING = globals().get("_AQUAFE_G0_OUTER_BINDING")
_OUTER_LIVE_MAIN_CODE = sys._getframe(0).f_code
_OUTER_PYTHON = "/usr/bin/python3.8"
_OUTER_SCRIPT = "/home/ma/AQUA-FE_WS/scripts/govern_matched_birth_r4_vins_g0_v1.py"
_OUTER_ROOT = "/home/ma/AQUA-FE_WS"
_OUTER_PYCACHE_PREFIX = "/dev/null/aqua-fe-a02-formal-g0-pycache-denied-v1"
_OUTER_ACTIONS = {
    "preview-contract", "write-freeze", "check-start", "run", "seal-post",
    "check-post",
}
_OUTER_ENVIRONMENT = {
    "HOME": "/home/ma",
    "USER": "ma",
    "LOGNAME": "ma",
    "SHELL": "/bin/bash",
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    # -I deliberately ignores these three.  They remain exact audit leaves;
    # effective isolation/bytecode/hash behavior is bound by kernel argv and
    # sys.flags below, not by claiming these strings control CPython.
    "PYTHONHASHSEED": "0",
    "PYTHONNOUSERSITE": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_OUTER_FLAGS = {
    "debug": 0, "inspect": 0, "interactive": 0, "optimize": 0,
    "dont_write_bytecode": 1, "no_user_site": 1, "no_site": 0,
    "ignore_environment": 1, "verbose": 0, "bytes_warning": 0,
    "quiet": 0, "hash_randomization": 1, "isolated": 1,
    "dev_mode": False, "utf8_mode": 0,
}
_OUTER_GUARD_ACTIVE = False
_OUTER_DEV_NULL_BOUND: tuple[int, ...] | None = None


def _outer_stat_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_uid, value.st_gid, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )


def _validate_outer_carrier_binding() -> str:
    binding = _OUTER_CARRIER_BINDING
    if not isinstance(binding, Mapping) or set(binding) != {
        "fd", "source_bytes", "stat_identity", "sha256", "code", "carrier_source"
    }:
        raise RuntimeError("formal G0 outer carrier binding is absent")
    descriptor = binding.get("fd")
    source_bytes = binding.get("source_bytes")
    digest = binding.get("sha256")
    bound_identity = binding.get("stat_identity")
    if (
        isinstance(descriptor, bool)
        or not isinstance(descriptor, int)
        or descriptor < 3
        or not isinstance(source_bytes, bytes)
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not isinstance(bound_identity, tuple)
        or len(bound_identity) != 9
        or binding.get("code") is not _OUTER_LIVE_MAIN_CODE
        or binding.get("carrier_source") != "-c"
        or hashlib.sha256(source_bytes).hexdigest() != digest
    ):
        raise RuntimeError("formal G0 outer carrier binding shape/hash differs")
    descriptor_stat = os.fstat(descriptor)
    named_stat = os.lstat(_OUTER_SCRIPT)
    if (
        _outer_stat_identity(descriptor_stat) != bound_identity
        or _outer_stat_identity(named_stat) != bound_identity
        or not stat.S_ISREG(named_stat.st_mode)
        or named_stat.st_nlink != 1
        or os.path.realpath(_OUTER_SCRIPT) != _OUTER_SCRIPT
    ):
        raise RuntimeError("formal G0 outer carrier source identity drifted")
    chunks: list[bytes] = []
    offset = 0
    while offset < descriptor_stat.st_size:
        chunk = os.pread(
            descriptor, min(1024 * 1024, descriptor_stat.st_size - offset), offset
        )
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    if b"".join(chunks) != source_bytes:
        raise RuntimeError("formal G0 outer carrier held source bytes drifted")
    return digest


def _outer_dev_null_identity() -> tuple[int, ...]:
    value = os.lstat("/dev/null")
    if (
        not stat.S_ISCHR(value.st_mode)
        or value.st_uid != 0
        or value.st_gid != 0
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o666
        or os.path.realpath("/dev/null") != "/dev/null"
    ):
        raise RuntimeError("outer structural pycache denial device differs")
    return (
        value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_uid, value.st_gid, value.st_rdev,
    )


def _kernel_argv_preimport() -> list[str]:
    descriptor = os.open(
        "/proc/self/cmdline",
        os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    content = b"".join(chunks)
    if not content.endswith(b"\0"):
        raise RuntimeError("outer kernel argv is absent or unterminated")
    try:
        result = [item.decode("utf-8", "strict") for item in content[:-1].split(b"\0")]
    except UnicodeDecodeError as error:
        raise RuntimeError("outer kernel argv is not UTF-8") from error
    if not result or any(not item for item in result):
        raise RuntimeError("outer kernel argv contains an empty item")
    return result


def _outer_formal_command(action: str, governor_sha256: str) -> list[str]:
    """Return the only authorized formal carrier argv for frozen source bytes."""

    if action not in _OUTER_ACTIONS or re.fullmatch(r"[0-9a-f]{64}", governor_sha256) is None:
        raise RuntimeError("outer formal command action/hash differs")
    return [
        _OUTER_PYTHON, "-I", "-B", "-c", _OUTER_CARRIER_SOURCE,
        _OUTER_SCRIPT, governor_sha256, "--action", action,
    ]


def _preimport_outer_guard() -> None:
    """Bind the governance carrier before importing any workspace module."""

    global _OUTER_GUARD_ACTIVE, _OUTER_DEV_NULL_BOUND
    if _OUTER_GUARD_ACTIVE:
        raise RuntimeError("outer governance guard was entered twice")
    if len(sys.argv) != 3 or sys.argv[1] != "--action" or sys.argv[2] not in _OUTER_ACTIONS:
        raise RuntimeError("outer governance argv must be exact script --action ACTION")
    governor_sha256 = _validate_outer_carrier_binding()
    expected_kernel = [
        _OUTER_PYTHON, "-I", "-B", "-c", _OUTER_CARRIER_SOURCE,
        _OUTER_SCRIPT, governor_sha256, *sys.argv[1:],
    ]
    flags = {
        "debug": int(sys.flags.debug),
        "inspect": int(sys.flags.inspect),
        "interactive": int(sys.flags.interactive),
        "optimize": int(sys.flags.optimize),
        "dont_write_bytecode": int(sys.flags.dont_write_bytecode),
        "no_user_site": int(sys.flags.no_user_site),
        "no_site": int(sys.flags.no_site),
        "ignore_environment": int(sys.flags.ignore_environment),
        "verbose": int(sys.flags.verbose),
        "bytes_warning": int(sys.flags.bytes_warning),
        "quiet": int(sys.flags.quiet),
        "hash_randomization": int(sys.flags.hash_randomization),
        "isolated": int(sys.flags.isolated),
        "dev_mode": bool(sys.flags.dev_mode),
        "utf8_mode": int(sys.flags.utf8_mode),
    }
    def workspace_bound(value: object) -> bool:
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        return value.startswith(f"{_OUTER_ROOT}/") or os.path.realpath(value).startswith(
            f"{_OUTER_ROOT}/"
        )

    preloaded_workspace = []
    for name, module in tuple(sys.modules.items()):
        values = (
            getattr(module, "__file__", None),
            getattr(getattr(module, "__spec__", None), "origin", None),
        )
        module_path = getattr(module, "__path__", ())
        if name != "__main__" and (
            any(workspace_bound(value) for value in values)
            or any(workspace_bound(value) for value in module_path or ())
        ):
            preloaded_workspace.append(name)
    if (
        sys.executable != _OUTER_PYTHON
        or os.readlink("/proc/self/exe") != _OUTER_PYTHON
        or os.fspath(Path(__file__).absolute()) != _OUTER_SCRIPT
        or os.path.realpath(__file__) != _OUTER_SCRIPT
        or globals().get("__loader__") is not None
        or globals().get("__spec__") is not None
        or globals().get("__cached__") is not None
        or os.getcwd() != _OUTER_ROOT
        or os.path.realpath(os.getcwd()) != _OUTER_ROOT
        or _kernel_argv_preimport() != expected_kernel
        or flags != _OUTER_FLAGS
        or dict(os.environ) != _OUTER_ENVIRONMENT
        or sys.pycache_prefix is not None
        or os.path.lexists(_OUTER_PYCACHE_PREFIX)
        or preloaded_workspace
    ):
        raise RuntimeError("outer governance carrier/environment authority differs")
    _OUTER_DEV_NULL_BOUND = _outer_dev_null_identity()
    sys.pycache_prefix = _OUTER_PYCACHE_PREFIX
    if sys.pycache_prefix != _OUTER_PYCACHE_PREFIX or os.path.lexists(_OUTER_PYCACHE_PREFIX):
        raise RuntimeError("outer empty pycache prefix could not be established")
    _OUTER_GUARD_ACTIVE = True


if __name__ == "__main__":
    try:
        _preimport_outer_guard()
    except BaseException as _outer_error:
        print(
            f"OUTER_INVOCATION_ERROR:{type(_outer_error).__name__}:{_outer_error}",
            file=sys.stderr,
        )
        raise SystemExit(2)


class _OuterBoundSourceLoader(importlib.machinery.SourceFileLoader):
    """Load one workspace module only from source bytes retained in an open fd."""

    def __init__(self, fullname: str, path: str) -> None:
        super().__init__(fullname, path)
        self._descriptor = -1
        self._source_bytes = b""
        self._bound_stat: tuple[int, ...] | None = None
        self._bound_sha256 = ""
        self._loaded_module: object | None = None
        self._load_count = 0
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise RuntimeError(f"outer workspace source is not regular: {fullname}")
            chunks: list[bytes] = []
            offset = 0
            while offset < before.st_size:
                chunk = os.pread(descriptor, min(1 << 20, before.st_size - offset), offset)
                if not chunk:
                    break
                chunks.append(chunk)
                offset += len(chunk)
            source_bytes = b"".join(chunks)
            after = os.fstat(descriptor)
            bound_stat = self._stat_identity(after)
            if (
                self._stat_identity(before) != bound_stat
                or len(source_bytes) != after.st_size
                or os.path.realpath(path) != path
            ):
                raise RuntimeError(f"outer workspace source changed while binding: {fullname}")
            self._descriptor = descriptor
            self._source_bytes = source_bytes
            self._bound_stat = bound_stat
            self._bound_sha256 = hashlib.sha256(source_bytes).hexdigest()
        except BaseException:
            os.close(descriptor)
            raise

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, ...]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_uid,
            value.st_gid,
            value.st_size,
            value.st_mtime_ns,
            value.st_ctime_ns,
        )

    @property
    def bound_record(self) -> dict[str, object]:
        return {
            "path": self.path,
            "sha256": self._bound_sha256,
            "size_bytes": len(self._source_bytes),
        }

    def get_data(self, path: str) -> bytes:
        if os.path.abspath(path) != self.path:
            raise OSError(f"outer bound loader refuses non-source data: {path}")
        return self._source_bytes

    def get_code(self, fullname: str) -> object:
        if fullname != self.name:
            raise ImportError(f"outer bound loader name differs: {fullname}")
        return self.source_to_code(self._source_bytes, self.path)

    def exec_module(self, module: object) -> None:
        if self._loaded_module is not None or self._load_count != 0:
            raise ImportError(f"outer bound workspace module reload denied: {self.name}")
        self._loaded_module = module
        self._load_count = 1
        code = self.get_code(self.name)
        exec(code, module.__dict__)  # type: ignore[attr-defined]

    def validate(self, *, require_loaded: bool = True) -> None:
        if self._descriptor < 0 or self._bound_stat is None:
            raise RuntimeError(f"outer workspace source hold is closed: {self.name}")
        descriptor_stat = os.fstat(self._descriptor)
        path_stat = os.lstat(self.path)
        if (
            self._stat_identity(descriptor_stat) != self._bound_stat
            or self._stat_identity(path_stat) != self._bound_stat
            or not stat.S_ISREG(path_stat.st_mode)
            or os.path.realpath(self.path) != self.path
        ):
            raise RuntimeError(f"outer workspace source identity drifted: {self.name}")
        content = b""
        offset = 0
        while offset < descriptor_stat.st_size:
            chunk = os.pread(
                self._descriptor,
                min(1 << 20, descriptor_stat.st_size - offset),
                offset,
            )
            if not chunk:
                break
            content += chunk
            offset += len(chunk)
        if (
            len(content) != len(self._source_bytes)
            or hashlib.sha256(content).hexdigest() != self._bound_sha256
            or content != self._source_bytes
        ):
            raise RuntimeError(f"outer workspace source bytes drifted: {self.name}")
        if require_loaded and (self._load_count != 1 or self._loaded_module is None):
            raise RuntimeError(f"outer workspace source was not loaded exactly once: {self.name}")

    def close(self) -> None:
        if self._descriptor >= 0:
            descriptor = self._descriptor
            self._descriptor = -1
            os.close(descriptor)


class _OuterRejectWorkspaceLoader:
    def create_module(self, spec: object) -> None:
        return None

    def exec_module(self, module: object) -> None:
        name = getattr(module, "__name__", "<unknown>")
        raise ImportError(f"unbound outer workspace module denied: {name}")


class _OuterWorkspaceFinder:
    def __init__(
        self,
        sources: Mapping[str, str],
        scripts_path: str,
        main_path: str,
    ) -> None:
        self.scripts_path = scripts_path
        self.main_loader: _OuterBoundSourceLoader | None = None
        self.loaders: dict[str, _OuterBoundSourceLoader] = {}
        try:
            self.main_loader = _OuterBoundSourceLoader("__main__", main_path)
            if self.main_loader.get_code("__main__") != _OUTER_LIVE_MAIN_CODE:
                raise RuntimeError("outer live main code differs from bound source bytes")
            for name, path in sources.items():
                self.loaders[name] = _OuterBoundSourceLoader(name, path)
        except BaseException:
            self.close()
            raise

    def find_spec(
        self,
        fullname: str,
        path: object = None,
        target: object = None,
    ) -> object:
        if fullname == "scripts":
            spec = importlib.machinery.ModuleSpec(fullname, loader=None, is_package=True)
            spec.submodule_search_locations = [self.scripts_path]
            return spec
        loader = self.loaders.get(fullname)
        if loader is not None:
            return importlib.util.spec_from_loader(
                fullname,
                loader,
                origin=loader.path,
                is_package=False,
            )
        if fullname.startswith("scripts."):
            return importlib.util.spec_from_loader(
                fullname,
                _OuterRejectWorkspaceLoader(),
                origin="outer-workspace-denied",
            )
        return None

    def validate(self) -> None:
        if self.main_loader is None:
            raise RuntimeError("outer main source hold is absent")
        self.main_loader.validate(require_loaded=False)
        if self.main_loader.get_code("__main__") != _OUTER_LIVE_MAIN_CODE:
            raise RuntimeError("outer live main code differs from retained source bytes")
        for name, loader in self.loaders.items():
            loader.validate()
            if sys.modules.get(name) is not loader._loaded_module:
                raise RuntimeError(f"outer workspace module object differs: {name}")

    def close(self) -> None:
        if self.main_loader is not None:
            self.main_loader.close()
        for loader in self.loaders.values():
            loader.close()


_OUTER_WORKSPACE_FINDER: _OuterWorkspaceFinder | None = None
_OUTER_WORKSPACE_SOURCES = {
    name: f"{_OUTER_ROOT}/scripts/{leaf}"
    for name, leaf in (
        ("scripts.formal_g0_child_bootstrap_v1", "formal_g0_child_bootstrap_v1.py"),
        ("scripts.p07_backend_evaluation_v1", "p07_backend_evaluation_v1.py"),
        ("scripts.p07_backend_formal_io_v1", "p07_backend_formal_io_v1.py"),
        ("scripts.p07_backend_replay_common_v1", "p07_backend_replay_common_v1.py"),
        ("scripts.p07_g0_governance_v1", "p07_g0_governance_v1.py"),
        ("scripts.p07_g0_publisher_v1", "p07_g0_publisher_v1.py"),
        ("scripts.run_p07_g0_evaluation_v1", "run_p07_g0_evaluation_v1.py"),
    )
}


def _install_outer_workspace_finder() -> None:
    global _OUTER_WORKSPACE_FINDER
    if not _OUTER_GUARD_ACTIVE:
        return
    if _OUTER_WORKSPACE_FINDER is not None:
        raise RuntimeError("outer workspace finder was installed twice")
    finder = _OuterWorkspaceFinder(
        _OUTER_WORKSPACE_SOURCES,
        f"{_OUTER_ROOT}/scripts",
        _OUTER_SCRIPT,
    )
    sys.meta_path.insert(0, finder)
    _OUTER_WORKSPACE_FINDER = finder


ROOT = Path(_OUTER_ROOT) if _OUTER_GUARD_ACTIVE else Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if _OUTER_GUARD_ACTIVE:
    try:
        _install_outer_workspace_finder()
    except BaseException as _outer_error:
        print(
            f"OUTER_INVOCATION_ERROR:{type(_outer_error).__name__}:{_outer_error}",
            file=sys.stderr,
        )
        raise SystemExit(2)

from scripts import formal_g0_child_bootstrap_v1 as bootstrap
from scripts import p07_backend_replay_common_v1 as backend
from scripts import p07_g0_governance_v1 as p07gov
from scripts import p07_g0_publisher_v1 as publisher
from scripts import run_p07_g0_evaluation_v1 as p07runner

if publisher.gov is not p07gov:
    raise RuntimeError("P07 publisher/governance module identity differs")


def _validate_outer_workspace_module_closure() -> None:
    """Reject pyc, alternate loaders, unbound code, or retained-source drift."""

    if not _OUTER_GUARD_ACTIVE:
        return
    finder = _OUTER_WORKSPACE_FINDER
    if finder is None or not sys.meta_path or sys.meta_path[0] is not finder:
        raise RuntimeError("outer workspace finder authority differs")
    finder.validate()
    expected = {
        "__main__": Path(_OUTER_SCRIPT),
        "scripts.formal_g0_child_bootstrap_v1": ROOT / "scripts/formal_g0_child_bootstrap_v1.py",
        "scripts.p07_backend_evaluation_v1": ROOT / "scripts/p07_backend_evaluation_v1.py",
        "scripts.p07_backend_formal_io_v1": ROOT / "scripts/p07_backend_formal_io_v1.py",
        "scripts.p07_backend_replay_common_v1": ROOT / "scripts/p07_backend_replay_common_v1.py",
        "scripts.p07_g0_governance_v1": ROOT / "scripts/p07_g0_governance_v1.py",
        "scripts.p07_g0_publisher_v1": ROOT / "scripts/p07_g0_publisher_v1.py",
        "scripts.run_p07_g0_evaluation_v1": ROOT / "scripts/run_p07_g0_evaluation_v1.py",
    }
    def workspace_bound(value: object) -> bool:
        if not isinstance(value, str) or not value.startswith("/"):
            return False
        return value.startswith(f"{_OUTER_ROOT}/") or os.path.realpath(value).startswith(
            f"{_OUTER_ROOT}/"
        )

    observed: dict[str, str] = {}
    for name, module in tuple(sys.modules.items()):
        if module is None:
            continue
        module_file = getattr(module, "__file__", None)
        spec = getattr(module, "__spec__", None)
        origin = getattr(spec, "origin", None) if spec is not None else None
        module_path = getattr(module, "__path__", ())
        workspace_values = [value for value in (module_file, origin) if workspace_bound(value)]
        workspace_paths = [value for value in (module_path or ()) if workspace_bound(value)]
        if not workspace_values and not workspace_paths:
            continue
        if name == "scripts":
            # The namespace carrier is checked exactly after all source modules.
            continue
        if name not in expected:
            raise RuntimeError(f"unbound workspace module loaded: {name}")
        source = os.fspath(expected[name])
        if (
            module_file != source
            or os.path.realpath(module_file) != source
            or (name != "__main__" and origin != source)
            or (name != "__main__" and os.path.realpath(origin) != source)
            or workspace_paths
        ):
            raise RuntimeError(f"workspace module source/origin differs: {name}")
        if name == "__main__" and spec is not None:
            raise RuntimeError("direct governor unexpectedly has an import spec")
        loader = getattr(module, "__loader__", None)
        if name == "__main__":
            if (
                loader is not None
                or spec is not None
                or _OUTER_CARRIER_BINDING is None
                or _OUTER_CARRIER_BINDING.get("code") is not _OUTER_LIVE_MAIN_CODE
            ):
                raise RuntimeError(f"workspace module loader differs: {name}")
        else:
            bound_loader = finder.loaders.get(name)
            bound_record = bound_loader.bound_record if bound_loader is not None else None
            live_record = publisher.direct_file_record_bound_input_rooted(
                ROOT, Path(source), label=f"outer loaded workspace source {name}"
            )
            if (
                type(loader) is not _OuterBoundSourceLoader
                or loader is not bound_loader
                or getattr(spec, "loader", None) is not bound_loader
                or bound_loader._loaded_module is not module
                or bound_record
                != {
                    "path": source,
                    "sha256": hashlib.sha256(bound_loader._source_bytes).hexdigest(),
                    "size_bytes": len(bound_loader._source_bytes),
                }
                or live_record.get("sha256") != bound_record["sha256"]
                or live_record.get("size_bytes") != bound_record["size_bytes"]
            ):
                raise RuntimeError(f"workspace module bound loader differs: {name}")
        cached = getattr(module, "__cached__", None)
        expected_cached = (
            None if name == "__main__" else importlib.util.cache_from_source(source)
        )
        if cached != expected_cached or (
            isinstance(cached, str) and os.path.lexists(cached)
        ):
            raise RuntimeError(f"workspace module pyc authority differs: {name}")
        observed[name] = source
    if observed != {name: os.fspath(path) for name, path in expected.items()}:
        raise RuntimeError("workspace module closure differs")
    main_record = finder.main_loader.bound_record if finder.main_loader is not None else None
    live_main = publisher.direct_file_record_bound_input_rooted(
        ROOT, Path(_OUTER_SCRIPT), label="outer loaded governor source"
    )
    if (
        not isinstance(main_record, Mapping)
        or not isinstance(_OUTER_CARRIER_BINDING, Mapping)
        or _OUTER_CARRIER_BINDING.get("sha256") != main_record.get("sha256")
        or _OUTER_CARRIER_BINDING.get("source_bytes")
        != finder.main_loader._source_bytes
        or live_main.get("sha256") != main_record.get("sha256")
        or live_main.get("size_bytes") != main_record.get("size_bytes")
    ):
        raise RuntimeError("outer loaded governor source binding differs")
    package = sys.modules.get("scripts")
    package_spec = getattr(package, "__spec__", None)
    locations = getattr(package_spec, "submodule_search_locations", None)
    if (
        package is None
        or getattr(package, "__file__", None) is not None
        or getattr(package_spec, "origin", None) is not None
        or list(locations or []) != [os.fspath(ROOT / "scripts")]
        or [os.path.realpath(value) for value in (locations or [])]
        != [os.fspath(ROOT / "scripts")]
        or f"{type(getattr(package, '__loader__', None)).__module__}."
        f"{type(getattr(package, '__loader__', None)).__qualname__}"
        != "_frozen_importlib_external._NamespaceLoader"
    ):
        raise RuntimeError("scripts namespace carrier differs")


def _outer_post_action_guard() -> None:
    if not _OUTER_GUARD_ACTIVE:
        return
    governor_sha256 = _validate_outer_carrier_binding()
    _validate_outer_workspace_module_closure()
    expected_kernel = [
        _OUTER_PYTHON, "-I", "-B", "-c", _OUTER_CARRIER_SOURCE,
        _OUTER_SCRIPT, governor_sha256, *sys.argv[1:],
    ]
    flags = {
        "debug": int(sys.flags.debug),
        "inspect": int(sys.flags.inspect),
        "interactive": int(sys.flags.interactive),
        "optimize": int(sys.flags.optimize),
        "dont_write_bytecode": int(sys.flags.dont_write_bytecode),
        "no_user_site": int(sys.flags.no_user_site),
        "no_site": int(sys.flags.no_site),
        "ignore_environment": int(sys.flags.ignore_environment),
        "verbose": int(sys.flags.verbose),
        "bytes_warning": int(sys.flags.bytes_warning),
        "quiet": int(sys.flags.quiet),
        "hash_randomization": int(sys.flags.hash_randomization),
        "isolated": int(sys.flags.isolated),
        "dev_mode": bool(sys.flags.dev_mode),
        "utf8_mode": int(sys.flags.utf8_mode),
    }
    if (
        sys.pycache_prefix != _OUTER_PYCACHE_PREFIX
        or os.path.lexists(_OUTER_PYCACHE_PREFIX)
        or _OUTER_DEV_NULL_BOUND is None
        or _outer_dev_null_identity() != _OUTER_DEV_NULL_BOUND
        or dict(os.environ) != _OUTER_ENVIRONMENT
        or len(sys.argv) != 3
        or sys.argv[0] != _OUTER_SCRIPT
        or sys.argv[1] != "--action"
        or sys.argv[2] not in _OUTER_ACTIONS
        or os.getcwd() != _OUTER_ROOT
        or os.path.realpath(os.getcwd()) != _OUTER_ROOT
        or sys.executable != _OUTER_PYTHON
        or os.readlink("/proc/self/exe") != _OUTER_PYTHON
        or os.fspath(Path(__file__).absolute()) != _OUTER_SCRIPT
        or os.path.realpath(__file__) != _OUTER_SCRIPT
        or globals().get("__loader__") is not None
        or globals().get("__spec__") is not None
        or globals().get("__cached__") is not None
        or _kernel_argv_preimport() != expected_kernel
        or flags != _OUTER_FLAGS
    ):
        raise RuntimeError("outer governance carrier drifted during action")


class GovernanceError(RuntimeError):
    pass


FREEZE_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-freeze-v2"
BOUND_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-bound-summary-v2"
PROCESS_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-process-role-v2"
LAUNCH_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-launch-intent-v1"
PROBE_LAUNCH_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-launch-intent-v1"
PROBE_FAILURE_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-failure-receipt-v1"
POST_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-post-seal-v2"
FREEZE_STATUS = "FROZEN_POST_RESULT_EXPLORATORY_FORMAL900_FULL_REFERENCE_G0"
POST_PASS = "PASS_STRICT_FULL_REFERENCE_COMMON_SUPPORT"
POST_FAIL = "FAIL_STRICT_FULL_REFERENCE_COMMON_SUPPORT"
OUTCOME_BOUNDARY = {
    "runner_local_ape_results_visible_before_freeze": True,
    "outcome_blind": False,
    "confirmatory": False,
    "statistical_significance": False,
    "cross_window_generalization": False,
    "whole_slam_superiority": False,
    "reference_is_image_derived_colmap_not_independent_ground_truth": True,
}
PUBLICATION_TECHNICAL_BOUNDARY = (
    "G0_RETAINED_PUBLICATION_FOR_POST_RESULT_EXPLORATORY_EVALUATION;"
    "NO_CLAIM_OF_PRE_OUTCOME_BLINDNESS"
)
P07_NATIVE_OUTCOME_BOUNDARY = (
    "G0_GOVERNANCE_ONLY_NO_UNBOUND_TRAJECTORY_APE_RPE_RESULT_ACCESS"
)
if p07gov.OUTCOME_BOUNDARY != P07_NATIVE_OUTCOME_BOUNDARY:
    raise RuntimeError("P07 native outcome-boundary constant drifted")
_PUBLICATION_SCOPE_OWNER: int | None = None
_PUBLICATION_SCOPE_DEPTH = 0
_PUBLICATION_SCOPE_GUARD = threading.Lock()

FREEZE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v1.json"
POST = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v1.json"
OUTPUT = ROOT / "papers/litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r1"
PROBE_INTENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v1.json"
PROBE_FAILURE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v1.json"
CORRECTED_SEAL = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_modefix_continuation_seal_v1.json"
RAW_BAG = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
REFERENCE_BAG_MANIFEST = ROOT / "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag.manifest.json"
CONFIG = ROOT / "configs/published_baselines/hfnet_aqualoc_a02_body_T_cam0_v1.yaml"
CONFIG_SEALED_AUTHORITY = ROOT / "papers/litcmp_a02_4500_6300_common_support/b1_constq_vs_xfeatbirth_adopted_v2_5_r1/evaluator_process_receipt_v2_5.json"
XFEAT_VIO = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_matchedbirth_formal900_r4_xfeat_vins_r1/vins_output/vio.csv"
GFTT_VIO = ROOT / "logs/aqualoc_archaeo_vins/external_klt_every2_litcmp_a02_4500_6300_preroll_matchedbirth_formal900_r4_gftt_vins_r1/vins_output/vio.csv"
XFEAT_RUN = XFEAT_VIO.parents[1]
GFTT_RUN = GFTT_VIO.parents[1]
XFEAT_FEATURE_BAG = ROOT / "experiments/matched_birth_a02_4500_6300_formal900_r4/xfeat_r4/features.bag"
GFTT_FEATURE_BAG = ROOT / "experiments/matched_birth_a02_4500_6300_formal900_r4/gftt_r4/features.bag"
EPOCH_LOCK = ROOT / "papers/ieee_sensors_journal_experiments/p07/evaluator_epoch_ns_correction_lock_v1.json"
PROTOCOL_DOC = ROOT / "papers/ieee_sensors_journal_experiments/evaluator_protocol_v1.md"
PYTHON = Path("/usr/bin/python3.8")

BOOTSTRAP = ROOT / "scripts/formal_g0_child_bootstrap_v1.py"
WRAPPER = ROOT / "scripts/evaluate_vins_common_support_epoch_v2.py"
BASE = ROOT / "scripts/evaluate_vins_common_support.py"
CORE = ROOT / "scripts/trajectory_eval_core.py"
HELPERS = {
    "governor": Path(__file__).resolve(),
    "child_bootstrap": BOOTSTRAP,
    "backend": ROOT / "scripts/p07_backend_replay_common_v1.py",
    "formal_io": ROOT / "scripts/p07_backend_formal_io_v1.py",
    "p07_governance": ROOT / "scripts/p07_g0_governance_v1.py",
    "backend_evaluation": ROOT / "scripts/p07_backend_evaluation_v1.py",
    "publisher": ROOT / "scripts/p07_g0_publisher_v1.py",
    "runner": ROOT / "scripts/run_p07_g0_evaluation_v1.py",
    "epoch_wrapper": WRAPPER,
    "evaluator_base": BASE,
    "trajectory_core": CORE,
    "vins_runner": ROOT / "scripts/run_aqualoc_archaeo_vins_eval.sh",
}
INPUTS = {
    "corrected_seal": CORRECTED_SEAL,
    "reference_bag": RAW_BAG,
    "reference_bag_manifest": REFERENCE_BAG_MANIFEST,
    "config": CONFIG,
    "config_sealed_authority": CONFIG_SEALED_AUTHORITY,
    "gftt_vio": GFTT_VIO,
    "xfeat_vio": XFEAT_VIO,
    "epoch_lock": EPOCH_LOCK,
    "protocol_doc": PROTOCOL_DOC,
    "xfeat_feature_bag": XFEAT_FEATURE_BAG,
    "gftt_feature_bag": GFTT_FEATURE_BAG,
}
# Only these four scientific files are opened by the evaluator.  The remaining
# INPUTS are retained authority/evidence records and are revalidated from their
# held workspace identities; copying the raw/feature bags and provenance corpus
# into execution memfds would both misstate consumption and needlessly duplicate
# hundreds of megabytes.
EXECUTION_INPUT_KEYS = ("reference_bag", "config", "gftt_vio", "xfeat_vio")
for _arm_name, _run in (("xfeat", XFEAT_RUN), ("gftt", GFTT_RUN)):
    for _leaf in (
        "replay_manifest.txt",
        "vins_env_manifest.txt",
        "aqualoc_archaeo02_pinhole.yaml",
        "vins_aqualoc_archaeo_external.yaml",
        "vins.log",
    ):
        INPUTS[f"{_arm_name}_{_leaf.replace('.', '_')}"] = _run / _leaf
ARMS = {"GFTTBIRTH_RAWLK": GFTT_VIO, "XFEATBIRTH_RAWLK": XFEAT_VIO}
REFERENCE_TOPIC = "/aqualoc/colmap_gt"
WINDOW_START = "1542829016.700435392"
WINDOW_END = "1542829106.687510592"
WINDOW_START_NS = 1_542_829_016_700_435_392
WINDOW_END_NS = 1_542_829_106_687_510_592
EXPECTED_GRID_COUNT = 90
CONTRAST = "A02_4500_6300_MATCHED_BIRTH_FORMAL900_R4_XFEAT_VS_GFTT_FULL_REFERENCE"
ROLE_NAMES = ("primary", "verification")
EVALUATOR_FILES = (
    "common_support_summary.json",
    "common_support_metrics.csv",
    "common_grid_audit.csv",
)
RUNTIME_RECEIPT_NAME = "runtime_receipt.json"
ROLE_FILES = EVALUATOR_FILES + (RUNTIME_RECEIPT_NAME,)
PROCESS_TIMEOUT_SECONDS = 1800
PROCESS_CLEANUP_TIMEOUT_SECONDS = 10
RUNTIME_PROBE_TIMEOUT_SECONDS = 120
EPOCH_LOCK_FILE_SHA256 = "03602c71b5f7b90f28100786d7193fba3bfddcb6ebe802a5e631913a95e7c1dd"
EPOCH_LOCK_SELF_HASH = "f0485ff55f6700f1b201da9e3b9cc1859686b559b58ca4a05792838b18a4bcde"
CORRECTED_SEAL_SHA256 = "c727cb8cccddcae107db78f55fdeb12f16931ca56e89000398b8249b43ae4ab9"
CORRECTED_SEAL_SIZE = 613_756
CORRECTED_SEAL_MODE = 0o444
CORRECTED_SEAL_UID = 1000
RAW_BAG_MOUNT_ALIAS = "/mnt/data/AQUA-FE_WS/datasets/aqualoc/rosbags/archaeo02_4500_6300.bag"
RAW_BAG_SHA256 = "eebd45439e76c461e58a2a1d6321f3fcb82dbcf57ea4093929548c9620e63a83"
RAW_BAG_SIZE = 449_056_538
REFERENCE_BAG_MANIFEST_SHA256 = "41667ae9fd00dc6baf261cb2c519642b0ff9c2123ba154421780bc41bcf4de8e"
REFERENCE_BAG_MANIFEST_SIZE = 4_502
CONFIG_SHA256 = "a76c728b31d47c3a87f54c465fb581007ed2da2b7d7d84df81dbde93e9a886c1"
CONFIG_SIZE = 415
CONFIG_SEALED_AUTHORITY_SHA256 = "5637e2ad33e3bfaf00ffff9b8f18d7a5a609f826f60eaa824cf9f92f49618778"
CONFIG_SEALED_AUTHORITY_SIZE = 1_702
XFEAT_FEATURE_SHA256 = "13d0daf45e81560506cc44927318d91821ffc40564ded4529ce1466ed70700c0"
GFTT_FEATURE_SHA256 = "c1d4986dc15ef6bd9bf17a9a1506fd8bea053bdc466026445de99f9d827bed3d"
BOOTSTRAP_SHA256 = "331d687f6249a3b7a87898237c542948beb456f8942f59531fa6f63875faeeb5"
BOOTSTRAP_SIZE = 80_068
VINS_PROVENANCE_AUTHORITY = {
    "xfeat": {
        "vio_csv": ("2fe7106f112480af71b13a5c17fe8ff521cc76566a656308c3b172e2c08fdca9", 89_021),
        "replay_manifest_txt": ("fcf65c5c9c968cbbeb22d21f1e00ad94b7431251445cfeeb5708f8daa1d6c3f3", 488),
        "vins_env_manifest_txt": ("c8c67ed581bde7233a0992c276353569b12b6aa4a3ccc5a35cce3f747e986664", 2_255),
        "aqualoc_archaeo02_pinhole_yaml": ("045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5", 357),
        "vins_aqualoc_archaeo_external_yaml": ("74b1e41d3c3f476a6cbe48eaef36b8d0e78ade5f35a5d0a2cb5871cbcb3c644b", 985),
        "vins_log": ("887118b7758c585fece892d5130560c1e4cf9a00f9ee31cc50df1f14cf4ee8f8", 89_793),
    },
    "gftt": {
        "vio_csv": ("7a9bb96b0e9a1cc42f1bad0395d3bff5cc0fe33e723a7be571ed2c314c211d74", 89_819),
        "replay_manifest_txt": ("ae2f075a73d3503ede40beca10f0d1c3fea6700d165be94dbf572a3bf3b60957", 485),
        "vins_env_manifest_txt": ("ff5c1f85327969a7f05037dd52245813e9db04c5e5f300199d2060077d497d8b", 2_253),
        "aqualoc_archaeo02_pinhole_yaml": ("045505013a5dbfb629bad8d3463bbbdacad965ebdcf3c590598121bd884e50a5", 357),
        "vins_aqualoc_archaeo_external_yaml": ("1b5af6e7ebf3fa95db7242b435409326f2b24f4b2e125c8182e9ff0a4ec34e35", 984),
        "vins_log": ("a4afa663b1d73dadb5898a1bc93696859877d208b2d51f5209570f941a156a08", 98_543),
    },
}
VINS_EXTERNAL_RUNTIME = {
    "vins_binary": {
        "path": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node"),
        "sha256": "4e91d8ac0735163fb6617e18d64ae0de91cc903d036f0e568a29bd3e5f5f4278",
    },
    "vins_library": {
        "path": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libvins_lib.so"),
        "sha256": "c1080aefdfd0eb3f011d491041c773649917a77923b97e24503bd90136bab467",
    },
    "camera_models_library": {
        "path": Path("/home/ma/SLAM/VINS-Fusion-origin/devel/lib/libcamera_models.so"),
        "sha256": "6d7b261f12791b693f95aebea6a762a97bc3501f1f1f3c94a6af6e50f2e6690d",
    },
}


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return p07gov.canonical_json_bytes(value)


def _self_hash(value: Mapping[str, Any], field: str) -> str:
    return p07gov.canonical_json_hash(value, field)


JOB_ID = "matched_birth_r4_vins_g0_v1"


def _contract_authority(
    input_records: Mapping[str, Any],
    helper_records: Mapping[str, Any],
    python_record: Mapping[str, Any],
    vins_runtime_records: Mapping[str, Any],
) -> dict[str, str]:
    plan_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-plan-contract-v1",
        "contrast": CONTRAST,
        "roles": list(ROLE_NAMES),
        "protocol": _protocol(),
        "outcome_boundary": OUTCOME_BOUNDARY,
        "publication_technical_boundary": PUBLICATION_TECHNICAL_BOUNDARY,
    }
    plan_hash = hashlib.sha256(_canonical_json_bytes(plan_contract)).hexdigest()
    backend_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-backend-contract-v1",
        "helper_code_closure": dict(helper_records),
        "python_interpreter": dict(python_record),
        "vins_external_runtime": dict(vins_runtime_records),
        "authorized_environment_templates": {
            role: _environment_template(role) for role in ROLE_NAMES
        },
    }
    backend_hash = hashlib.sha256(_canonical_json_bytes(backend_contract)).hexdigest()
    job_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-job-contract-v1",
        "job_id": JOB_ID,
        "plan_hash": plan_hash,
        "backend_execution_lock_hash": backend_hash,
        "evaluation_lock_hash": EPOCH_LOCK_SELF_HASH,
        "input_records": dict(input_records),
        "authorized_role_argv": {
            role: canonical_role_argv(role) for role in ROLE_NAMES
        },
        "destination": os.fspath(OUTPUT),
    }
    job_hash = hashlib.sha256(_canonical_json_bytes(job_contract)).hexdigest()
    return {
        "job_id": JOB_ID,
        "job_hash": job_hash,
        "plan_hash": plan_hash,
        "evaluation_lock_hash": EPOCH_LOCK_SELF_HASH,
        "backend_execution_lock_hash": backend_hash,
        "evaluation_disposition": "EVALUATE_NUMERIC",
    }


def publication_paths(job_hash: str) -> tuple[Path, Path, Path]:
    return publisher.publication_paths(OUTPUT, job_hash=job_hash)


@contextmanager
def _post_result_publication_semantics():
    """Scope P07 retained-publication machinery to this truthful boundary."""

    global _PUBLICATION_SCOPE_DEPTH, _PUBLICATION_SCOPE_OWNER
    owner = threading.get_ident()
    with _PUBLICATION_SCOPE_GUARD:
        previous = p07gov.OUTCOME_BOUNDARY
        prior_depth = _PUBLICATION_SCOPE_DEPTH
        if prior_depth:
            if (
                _PUBLICATION_SCOPE_OWNER != owner
                or previous != PUBLICATION_TECHNICAL_BOUNDARY
            ):
                raise GovernanceError("publication-boundary nested owner/state differs")
            _PUBLICATION_SCOPE_DEPTH = prior_depth + 1
            nested = True
        else:
            if previous != P07_NATIVE_OUTCOME_BOUNDARY or _PUBLICATION_SCOPE_OWNER is not None:
                raise GovernanceError("publication-boundary entry state differs")
            _PUBLICATION_SCOPE_OWNER = owner
            _PUBLICATION_SCOPE_DEPTH = 1
            p07gov.OUTCOME_BOUNDARY = PUBLICATION_TECHNICAL_BOUNDARY
            nested = False
    if nested:
        try:
            yield
        finally:
            with _PUBLICATION_SCOPE_GUARD:
                mismatch = (
                    _PUBLICATION_SCOPE_OWNER != owner
                    or _PUBLICATION_SCOPE_DEPTH != prior_depth + 1
                    or p07gov.OUTCOME_BOUNDARY != PUBLICATION_TECHNICAL_BOUNDARY
                )
                _PUBLICATION_SCOPE_OWNER = owner
                _PUBLICATION_SCOPE_DEPTH = prior_depth
                p07gov.OUTCOME_BOUNDARY = PUBLICATION_TECHNICAL_BOUNDARY
            if mismatch:
                raise GovernanceError("nested publication boundary was mutated")
        return
    try:
        yield
    finally:
        with _PUBLICATION_SCOPE_GUARD:
            mismatch = (
                _PUBLICATION_SCOPE_OWNER != owner
                or _PUBLICATION_SCOPE_DEPTH != 1
                or p07gov.OUTCOME_BOUNDARY != PUBLICATION_TECHNICAL_BOUNDARY
            )
            _PUBLICATION_SCOPE_DEPTH = 0
            _PUBLICATION_SCOPE_OWNER = None
            p07gov.OUTCOME_BOUNDARY = previous
            restored = p07gov.OUTCOME_BOUNDARY == P07_NATIVE_OUTCOME_BOUNDARY
        if mismatch:
            raise GovernanceError("publication-boundary scope depth/owner differs")
        if not restored:
            raise GovernanceError("publication-boundary restoration failed")


def _workspace_record(path: Path, label: str) -> dict[str, object]:
    return publisher.direct_file_record_bound_input_rooted(ROOT, path, label=label)


def _external_record(path: Path, label: str) -> dict[str, object]:
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise GovernanceError(f"{label} is not a direct regular file")
        digest = hashlib.sha256()
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        reachable = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if (
            size != before.st_size
            or any(getattr(before, key) != getattr(after, key) for key in fields)
            or any(getattr(before, key) != getattr(reachable, key) for key in fields)
            or stat.S_ISLNK(reachable.st_mode)
        ):
            raise GovernanceError(f"{label} short read")
        return {"path": os.fspath(path), "sha256": digest.hexdigest(), "size_bytes": size}
    finally:
        os.close(descriptor)


def _load_json_static(path: Path, label: str) -> dict[str, Any]:
    raw = publisher.read_bytes_bound_input_rooted(ROOT, path, label=label)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GovernanceError(f"{label} is invalid JSON") from error
    if not isinstance(value, dict):
        raise GovernanceError(f"{label} is not a JSON object")
    return value


def _render_canonical_json(value: Mapping[str, Any]) -> bytes:
    """Render the exact on-disk JSON form used by the P07 publisher."""

    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise GovernanceError("short write while retaining governed JSON")
        remaining = remaining[written:]


def _stable_leaf_token(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_gid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _validate_held_json_leaf_at(
    parent_fd: int,
    name: str,
    leaf_fd: int,
    identity: os.stat_result,
    expected: bytes,
    *,
    label: str,
) -> None:
    opened = os.fstat(leaf_fd)
    try:
        reachable = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError as error:
        raise GovernanceError(f"{label} retained path disappeared") from error
    if (
        not stat.S_ISREG(opened.st_mode)
        or opened.st_nlink != 1
        or _stable_leaf_token(opened) != _stable_leaf_token(identity)
        or _stable_leaf_token(reachable) != _stable_leaf_token(identity)
        or os.pread(leaf_fd, len(expected) + 1, 0) != expected
    ):
        raise GovernanceError(f"{label} retained canonical leaf drifted")


@contextmanager
def _hold_existing_leaf_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
    expected_identity: os.stat_result | None = None,
):
    """Open one existing direct leaf once and retain its exact bytes/inode."""

    if not name or "/" in name or name in {".", ".."}:
        raise GovernanceError(f"unsafe {label} retained name")
    leaf_fd = -1
    try:
        leaf_fd = os.open(
            name,
            os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )
        identity = os.fstat(leaf_fd)
        if not stat.S_ISREG(identity.st_mode) or identity.st_nlink != 1:
            raise GovernanceError(f"{label} is not a direct single-link file")
        if (
            expected_identity is not None
            and _stable_leaf_token(identity)
            != _stable_leaf_token(expected_identity)
        ):
            raise GovernanceError(f"{label} differs from transactional staged inode")
        chunks: list[bytes] = []
        offset = 0
        while offset < identity.st_size:
            chunk = os.pread(
                leaf_fd, min(1024 * 1024, identity.st_size - offset), offset
            )
            if not chunk:
                raise GovernanceError(f"{label} retained file short read")
            chunks.append(chunk)
            offset += len(chunk)
        content = b"".join(chunks)

        def validate() -> None:
            _validate_held_json_leaf_at(
                parent_fd, name, leaf_fd, identity, content, label=label
            )

        validate()
        yield content, validate
        validate()
    finally:
        if leaf_fd >= 0:
            os.close(leaf_fd)


@contextmanager
def _hold_existing_canonical_json_rooted(
    root: Path,
    path: Path,
    expected_value: Mapping[str, Any],
    *,
    label: str,
    expected_identity: os.stat_result | None = None,
):
    """Retain a pre-existing JSON inode and require exact canonical bytes."""

    parent_fd = -1
    try:
        parent_fd, name, _absolute, parent_parts, parent_identity = (
            publisher._open_parent(root, path, create=False, label=label)
        )
        with _hold_existing_leaf_at(
            parent_fd,
            name,
            label=label,
            expected_identity=expected_identity,
        ) as (content, leaf_validator):
            expected = _render_canonical_json(expected_value)
            if content != expected:
                raise GovernanceError(f"{label} canonical bytes differ")
            observed = p07gov._json_object_bytes(content, label=label)
            if not _typed_tree_equal(observed, dict(expected_value)):
                raise GovernanceError(f"{label} object differs")

            def validate() -> None:
                leaf_validator()
                publisher._assert_parent_reachable(
                    root, parent_parts, parent_identity, label=label
                )

            validate()
            yield validate
            validate()
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


@contextmanager
def _write_held_canonical_json_at(
    parent_fd: int,
    name: str,
    value: Mapping[str, Any],
    *,
    label: str,
):
    """O_EXCL-write JSON and retain that same inode until the caller exits."""

    if not name or "/" in name or name in {".", ".."}:
        raise GovernanceError(f"unsafe {label} retained name")
    expected = _render_canonical_json(value)
    leaf_fd = -1
    try:
        leaf_fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            0o644,
            dir_fd=parent_fd,
        )
        _write_all(leaf_fd, expected)
        os.fsync(leaf_fd)
        identity = os.fstat(leaf_fd)
        os.fsync(parent_fd)

        def validate() -> None:
            _validate_held_json_leaf_at(
                parent_fd, name, leaf_fd, identity, expected, label=label
            )
            observed = p07gov._json_object_bytes(expected, label=label)
            if not _typed_tree_equal(observed, dict(value)):
                raise GovernanceError(f"{label} canonical object differs")

        validate()
        record = {
            "path": name,
            "sha256": hashlib.sha256(expected).hexdigest(),
            "size_bytes": len(expected),
        }
        yield validate, record
        validate()
    finally:
        if leaf_fd >= 0:
            os.close(leaf_fd)


@contextmanager
def _write_held_canonical_json_rooted(
    root: Path,
    path: Path,
    value: Mapping[str, Any],
    *,
    label: str,
):
    """Rooted variant whose parent and new O_EXCL leaf stay held together."""

    parent_fd = -1
    try:
        parent_fd, name, absolute, parent_parts, parent_identity = (
            publisher._open_parent(root, path, create=False, label=label)
        )
        with _write_held_canonical_json_at(
            parent_fd, name, value, label=label
        ) as (leaf_validator, _relative_record):
            expected = _render_canonical_json(value)

            def validate() -> None:
                if (
                    os.fstat(parent_fd).st_dev != parent_identity.st_dev
                    or os.fstat(parent_fd).st_ino != parent_identity.st_ino
                ):
                    raise GovernanceError(f"{label} retained parent drifted")
                leaf_validator()
                publisher._assert_parent_reachable(
                    root, parent_parts, parent_identity, label=label
                )

            validate()
            record = {
                "path": p07gov.display_path(root, absolute),
                "sha256": hashlib.sha256(expected).hexdigest(),
                "size_bytes": len(expected),
            }
            yield validate, record
            validate()
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


@contextmanager
def _create_retained_child_directory(
    parent_fd: int, name: str, *, label: str
):
    """Create then retain under the trusted same-UID workspace-owner boundary.

    Linux does not provide a mkdir-and-return-fd primitive.  The unavoidable
    mkdirat/openat birth window is therefore not claimed atomic; after the
    immediate O_NOFOLLOW open, both parent and child identities stay retained.
    """

    if not name or "/" in name or name in {".", ".."}:
        raise GovernanceError(f"unsafe {label} directory name")
    descriptor = -1
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        os.fsync(parent_fd)
        descriptor = os.open(name, publisher._directory_flags(), dir_fd=parent_fd)
        opened = os.fstat(descriptor)
        created = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(created.st_mode)
            or stat.S_ISLNK(created.st_mode)
            or created.st_dev != opened.st_dev
            or created.st_ino != opened.st_ino
            or opened.st_uid != os.getuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
            or os.listdir(descriptor)
        ):
            raise GovernanceError(f"{label} create/retain identity differs")

        retained_name = name

        def validate(visible_name: str | None = None) -> None:
            nonlocal retained_name
            candidate = retained_name if visible_name is None else visible_name
            if not candidate or "/" in candidate or candidate in {".", ".."}:
                raise GovernanceError(f"unsafe relocated {label} directory name")
            held = os.fstat(descriptor)
            reachable = os.stat(
                candidate, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISDIR(held.st_mode)
                or held.st_dev != opened.st_dev
                or held.st_ino != opened.st_ino
                or reachable.st_dev != opened.st_dev
                or reachable.st_ino != opened.st_ino
                or not stat.S_ISDIR(reachable.st_mode)
                or stat.S_ISLNK(reachable.st_mode)
                or held.st_uid != os.getuid()
            ):
                raise GovernanceError(f"{label} retained directory drifted")
            retained_name = candidate

        validate(name)
        yield descriptor, validate
        os.fsync(descriptor)
        validate()
    finally:
        if descriptor >= 0:
            os.close(descriptor)


@contextmanager
def _create_retained_workspace_directory(
    root: Path,
    path: Path,
    *,
    label: str,
    relocated_to: Path | None = None,
):
    """Create a top-level workspace directory and retain its first opened FD."""

    parent_fd = -1
    try:
        parent_fd, name, _absolute, parent_parts, parent_identity = (
            publisher._open_parent(root, path, create=False, label=label)
        )
        with _create_retained_child_directory(
            parent_fd, name, label=label
        ) as (descriptor, relative_validator):
            visible_path = path

            def validate_at(candidate: Path | None = None) -> None:
                nonlocal visible_path
                target = visible_path if candidate is None else candidate
                if (
                    os.fstat(parent_fd).st_dev != parent_identity.st_dev
                    or os.fstat(parent_fd).st_ino != parent_identity.st_ino
                ):
                    raise GovernanceError(f"{label} retained parent drifted")
                if target == path:
                    relative_validator(name)
                    publisher._assert_parent_reachable(
                        root, parent_parts, parent_identity, label=label
                    )
                else:
                    if (
                        relocated_to is None
                        or target != relocated_to
                        or target.parent != path.parent
                    ):
                        raise GovernanceError(
                            f"{label} unexpected relocation target"
                        )
                    publisher.assert_retained_workspace_directory(
                        root, target, descriptor, label=f"{label} relocated"
                    )
                    relative_validator(target.name)
                visible_path = target

            validate_at(path)
            yield descriptor, validate_at
            os.fsync(descriptor)
            validate_at()
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _protocol() -> dict[str, object]:
    return {
        "contrast_name": CONTRAST,
        "reference": f"{RAW_BAG}:{REFERENCE_TOPIC}",
        "window_start_decimal": WINDOW_START,
        "window_end_decimal": WINDOW_END,
        "window_start_ns": WINDOW_START_NS,
        "window_end_ns": WINDOW_END_NS,
        "evaluation_rate_hz": 1,
        "nominal_reference_rate_hz": 1,
        "nominal_estimate_rate_hz": 10,
        "max_reference_gap_s": "2.5",
        "max_estimate_gap_s": "0.25",
        "rpe_delta_s": 1,
        "min_ape_poses": 30,
        "min_ape_span_s": 10,
        "min_common_coverage": "0.70",
        "min_rpe_pairs": 10,
        "expected_uniform_grid_count": EXPECTED_GRID_COUNT,
        "body_to_camera_applied": True,
        "run_evo": False,
    }


def _evaluator_tail(paths: Mapping[str, str], output: str) -> list[str]:
    result = [
        "--reference-bag", paths["reference_bag"],
        "--reference-topic", REFERENCE_TOPIC,
    ]
    for label, key in (("GFTTBIRTH_RAWLK", "gftt_vio"), ("XFEATBIRTH_RAWLK", "xfeat_vio")):
        result.extend(("--arm", f"{label}={paths[key]}", "--arm-config", f"{label}={paths['config']}"))
    result.extend((
        "--nominal-reference-rate-hz", "1",
        "--nominal-estimate-rate-hz", "10",
        "--evaluation-rate-hz", "1",
        "--max-reference-gap-s", "2.5",
        "--max-estimate-gap-s", "0.25",
        "--window-start-s", WINDOW_START,
        "--window-end-s", WINDOW_END,
        "--rpe-delta-s", "1",
        "--min-ape-poses", "30",
        "--min-ape-span-s", "10",
        "--min-common-coverage", "0.70",
        "--min-rpe-pairs", "10",
        "--contrast-name", CONTRAST,
        "--output-dir", output,
    ))
    return result


def canonical_role_argv(role: str) -> list[str]:
    if role not in ROLE_NAMES:
        raise GovernanceError("invalid evaluator role")
    paths = {key: os.fspath(path) for key, path in INPUTS.items()}
    return [os.fspath(PYTHON), "-I", "-B", os.fspath(BOOTSTRAP), *_evaluator_tail(paths, os.fspath(OUTPUT / role))]


def _environment_template(role: str) -> dict[str, str]:
    if role not in ROLE_NAMES:
        raise GovernanceError("invalid evaluator role")
    extra = {
        "OPENBLAS_NUM_THREADS": "1",
        "OMP_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "AQUAFE_FORMAL_G0_ROLE": role,
        "AQUAFE_FORMAL_G0_WRAPPER_FD": "${EPOCH_WRAPPER_PROCFD}",
        "AQUAFE_FORMAL_G0_BASE_FD": "${EVALUATOR_BASE_PROCFD}",
        "AQUAFE_FORMAL_G0_CORE_FD": "${TRAJECTORY_CORE_PROCFD}",
        "AQUAFE_FORMAL_G0_ROLE_OUTPUT_FD": "${ROLE_OUTPUT_DIRFD}",
        "AQUAFE_P07_SEALED_EVALUATOR_BASE": "${EVALUATOR_BASE_PROCFD}",
        "AQUAFE_P07_SEALED_EVALUATOR_CORE": "${TRAJECTORY_CORE_PROCFD}",
    }
    try:
        return backend.sanitized_child_environment(extra=extra)
    except backend.BackendReplayViolation as error:
        raise GovernanceError(f"cannot build sanitized evaluator environment: {error}") from error


def _materialize_strings(values: Sequence[str], mapping: Mapping[str, str]) -> list[str]:
    result: list[str] = []
    for original in values:
        value = original
        for canonical, actual in sorted(mapping.items(), key=lambda item: -len(item[0])):
            value = value.replace(canonical, actual)
        result.append(value)
    return result


def _materialize_environment(template: Mapping[str, str], mapping: Mapping[str, str]) -> dict[str, str]:
    return {key: _materialize_strings([value], mapping)[0] for key, value in template.items()}


def _validate_scientific_input_authority(corrected_seal: Mapping[str, Any]) -> None:
    """Bind the evaluator's bag/config bytes to pre-existing sealed evidence."""

    raw_record = _workspace_record(RAW_BAG, "canonical raw reference bag")
    if raw_record.get("sha256") != RAW_BAG_SHA256 or raw_record.get("size_bytes") != RAW_BAG_SIZE:
        raise GovernanceError("canonical raw reference bag hard authority differs")
    config_record = _workspace_record(CONFIG, "common-support body-to-camera config")
    if config_record.get("sha256") != CONFIG_SHA256 or config_record.get("size_bytes") != CONFIG_SIZE:
        raise GovernanceError("common-support config hard authority differs")

    delegated = corrected_seal.get("delegated_formal_v2_result")
    sealed_inputs = delegated.get("inputs") if isinstance(delegated, Mapping) else None
    sealed_raw = sealed_inputs.get("raw_image_bag") if isinstance(sealed_inputs, Mapping) else None
    expected_raw_alias = {
        "path": RAW_BAG_MOUNT_ALIAS,
        "sha256": RAW_BAG_SHA256,
        "size_bytes": RAW_BAG_SIZE,
    }
    if sealed_raw != expected_raw_alias:
        raise GovernanceError("corrected seal raw-bag mount alias authority differs")
    inventory = corrected_seal.get("held_r4_and_locked_input_inventory")
    if not isinstance(inventory, list) or not any(
        isinstance(item, Mapping)
        and item.get("path") == RAW_BAG_MOUNT_ALIAS
        and item.get("sha256") == RAW_BAG_SHA256
        and item.get("size_bytes") == RAW_BAG_SIZE
        for item in inventory
    ):
        raise GovernanceError("corrected seal retained raw-bag alias is absent")

    manifest_record = _workspace_record(REFERENCE_BAG_MANIFEST, "canonical raw-bag manifest")
    if (
        manifest_record.get("sha256") != REFERENCE_BAG_MANIFEST_SHA256
        or manifest_record.get("size_bytes") != REFERENCE_BAG_MANIFEST_SIZE
    ):
        raise GovernanceError("canonical raw-bag manifest hard authority differs")
    manifest = _load_json_static(REFERENCE_BAG_MANIFEST, "canonical raw-bag manifest")
    output = manifest.get("output")
    checks = manifest.get("checks")
    if (
        manifest.get("schema_version") != "aqua-fe-aqualoc-canonical-raw-window-bag-manifest-v1"
        or manifest.get("status") != "PASS"
        or not isinstance(checks, Mapping)
        or checks.get("gt_count_and_schedule_exact") is not True
        or checks.get("record_header_stamps_exact") is not True
        or not isinstance(output, Mapping)
        or output.get("path") != RAW_BAG_MOUNT_ALIAS
        or output.get("sha256") != RAW_BAG_SHA256
        or output.get("size_bytes") != RAW_BAG_SIZE
        or output.get("record_stamp_equals_header") is not True
        or output.get("strictly_increasing_by_topic") is not True
    ):
        raise GovernanceError("canonical raw-bag manifest identity differs")
    topic_counts = output.get("topic_counts")
    topic_first = output.get("topic_first_header_ns")
    topic_last = output.get("topic_last_header_ns")
    if (
        not isinstance(topic_counts, Mapping)
        or topic_counts.get(REFERENCE_TOPIC) != 91
        or not isinstance(topic_first, Mapping)
        or topic_first.get(REFERENCE_TOPIC) != WINDOW_START_NS
        or not isinstance(topic_last, Mapping)
        or topic_last.get(REFERENCE_TOPIC) != WINDOW_END_NS
    ):
        raise GovernanceError("canonical reference topic/count/endpoints differ")

    authority_record = _workspace_record(CONFIG_SEALED_AUTHORITY, "sealed config authority")
    if (
        authority_record.get("sha256") != CONFIG_SEALED_AUTHORITY_SHA256
        or authority_record.get("size_bytes") != CONFIG_SEALED_AUTHORITY_SIZE
    ):
        raise GovernanceError("sealed config-authority file differs")
    config_authority = _load_json_static(CONFIG_SEALED_AUTHORITY, "sealed config authority")
    if (
        config_authority.get("schema_version") != "aqua-fe-a02-two-arm-evaluator-process-receipt-v2-5"
        or config_authority.get("status") != "PASS_PROCESS_RC0"
        or config_authority.get("return_code") != 0
        or config_authority.get("config") != {
            "path": os.fspath(CONFIG),
            "sha256": CONFIG_SHA256,
            "size_bytes": CONFIG_SIZE,
        }
    ):
        raise GovernanceError("sealed config authority does not cross-bind config")


def _static_authority_check() -> None:
    if _OUTER_GUARD_ACTIVE:
        _validate_outer_workspace_module_closure()
        loaded_sha256 = _validate_outer_carrier_binding()
        loaded_record = _workspace_record(Path(_OUTER_SCRIPT), "loaded G0 governor")
        if (
            loaded_record.get("sha256") != loaded_sha256
            or loaded_record.get("size_bytes")
            != len(_OUTER_CARRIER_BINDING["source_bytes"])
        ):
            raise GovernanceError("loaded governor bytes differ from helper authority")
    bootstrap_record = _workspace_record(BOOTSTRAP, "formal G0 child bootstrap")
    if bootstrap_record.get("sha256") != BOOTSTRAP_SHA256 or bootstrap_record.get("size_bytes") != BOOTSTRAP_SIZE:
        raise GovernanceError("formal G0 child bootstrap authority differs")
    seal = _load_json_static(CORRECTED_SEAL, "corrected r4 seal")
    seal_record = _workspace_record(CORRECTED_SEAL, "corrected r4 seal")
    if (
        seal_record.get("sha256") != CORRECTED_SEAL_SHA256
        or seal_record.get("size_bytes") != CORRECTED_SEAL_SIZE
        or seal.get("schema_version") != "aqua-fe-detector-birth-rawlk-matched-pair-formal-r4-modefix-continuation-audit-v1"
        or seal.get("status") != "PASS"
        or seal.get("pass") is not True
    ):
        raise GovernanceError("corrected r4 authority is not strict PASS")
    seal_stat = os.stat(CORRECTED_SEAL, follow_symlinks=False)
    if (
        stat.S_IMODE(seal_stat.st_mode) != CORRECTED_SEAL_MODE
        or seal_stat.st_uid != CORRECTED_SEAL_UID
        or seal_stat.st_nlink != 1
        or not stat.S_ISREG(seal_stat.st_mode)
    ):
        raise GovernanceError("corrected r4 seal filesystem identity differs")
    _validate_scientific_input_authority(seal)
    epoch = _load_json_static(EPOCH_LOCK, "epoch-v2 lock")
    epoch_hash = p07gov.validate_self_hash(
        epoch, "epoch_ns_correction_lock_hash", label="epoch-v2 lock"
    )
    if (
        _workspace_record(EPOCH_LOCK, "epoch-v2 lock")["sha256"]
        != EPOCH_LOCK_FILE_SHA256
        or epoch_hash != EPOCH_LOCK_SELF_HASH
    ):
        raise GovernanceError("epoch-v2 lock file/self-hash authority differs")
    implementation = epoch.get("corrected_implementation_binding")
    files = implementation.get("files") if isinstance(implementation, Mapping) else None
    if not isinstance(files, list):
        raise GovernanceError("epoch-v2 implementation binding is absent")
    expected_files = {
        str(record.get("path")): dict(record)
        for record in files
        if isinstance(record, Mapping)
    }
    for path in (BASE, CORE, WRAPPER):
        relative = path.relative_to(ROOT).as_posix()
        observed = _workspace_record(path, f"epoch-v2 implementation {relative}")
        if expected_files.get(relative) != observed:
            raise GovernanceError(f"epoch-v2 implementation drift: {relative}")
    protocol_binding = epoch.get("protocol_binding")
    if not isinstance(protocol_binding, Mapping) or dict(protocol_binding) != {
        "parent_sha256": _workspace_record(PROTOCOL_DOC, "evaluator protocol")["sha256"],
        "path": PROTOCOL_DOC.relative_to(ROOT).as_posix(),
        "protocol_identity": "isj-evaluator-v1",
        "sha256": _workspace_record(PROTOCOL_DOC, "evaluator protocol")["sha256"],
        "size_bytes": _workspace_record(PROTOCOL_DOC, "evaluator protocol")["size_bytes"],
        "unchanged": True,
    }:
        raise GovernanceError("epoch-v2 protocol binding differs")
    _validate_vins_provenance(seal)


def _parse_key_value_lines(content: bytes, label: str) -> dict[str, str]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise GovernanceError(f"{label} is not UTF-8") from error
    result: dict[str, str] = {}
    for line in lines:
        if not line:
            continue
        if "=" not in line:
            raise GovernanceError(f"{label} contains a non-key-value line")
        key, value = line.split("=", 1)
        if not key or key in result:
            raise GovernanceError(f"{label} key set is ambiguous")
        result[key] = value
    return result


def _vins_external_runtime_records() -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for role, authority in VINS_EXTERNAL_RUNTIME.items():
        record = _external_record(authority["path"], f"VINS runtime {role}")
        if record["sha256"] != authority["sha256"]:
            raise GovernanceError(f"VINS external runtime differs: {role}")
        result[role] = record
    return result


def _validate_vins_provenance(corrected_seal: Mapping[str, Any]) -> None:
    inventory = corrected_seal.get("held_r4_and_locked_input_inventory")
    if not isinstance(inventory, list):
        raise GovernanceError("corrected seal held inventory is absent")
    frozen = {
        str(item.get("path")): item
        for item in inventory
        if isinstance(item, Mapping) and item.get("kind") == "regular"
    }
    expected_features = {
        "xfeat": (XFEAT_FEATURE_BAG, XFEAT_FEATURE_SHA256),
        "gftt": (GFTT_FEATURE_BAG, GFTT_FEATURE_SHA256),
    }
    delegated = corrected_seal.get("delegated_formal_v2_result")
    post_run = delegated.get("post_run_outcome_seal") if isinstance(delegated, Mapping) else None
    sealed_arms = post_run.get("arms") if isinstance(post_run, Mapping) else None
    if not isinstance(sealed_arms, Mapping):
        raise GovernanceError("corrected seal delegated arm authority is absent")
    for arm, (feature_bag, expected_sha) in expected_features.items():
        frozen_record = frozen.get(os.fspath(feature_bag))
        live = _workspace_record(feature_bag, f"{arm} feature bag")
        if (
            not isinstance(frozen_record, Mapping)
            or frozen_record.get("sha256") != expected_sha
            or frozen_record.get("size_bytes") != live.get("size_bytes")
            or live.get("sha256") != expected_sha
        ):
            raise GovernanceError(f"{arm} feature bag does not cross-bind corrected seal")
        sealed_label = (
            "XFEAT_BIRTH_RAWLK_MATCHED_V1" if arm == "xfeat"
            else "GFTT_BIRTH_RAWLK_MATCHED_V1"
        )
        arm_binding = sealed_arms.get(sealed_label)
        feature_binding = arm_binding.get("feature_bag") if isinstance(arm_binding, Mapping) else None
        if not isinstance(feature_binding, Mapping) or dict(feature_binding) != {
            "path": os.fspath(feature_bag),
            "sha256": live["sha256"],
            "size_bytes": live["size_bytes"],
        }:
            raise GovernanceError(f"{arm} delegated feature-bag authority differs")
    for arm, run, trajectory, feature_bag, port in (
        ("xfeat", XFEAT_RUN, XFEAT_VIO, XFEAT_FEATURE_BAG, "11541"),
        ("gftt", GFTT_RUN, GFTT_VIO, GFTT_FEATURE_BAG, "11542"),
    ):
        authority = VINS_PROVENANCE_AUTHORITY[arm]
        bound_paths = {
            "vio_csv": trajectory,
            "replay_manifest_txt": run / "replay_manifest.txt",
            "vins_env_manifest_txt": run / "vins_env_manifest.txt",
            "aqualoc_archaeo02_pinhole_yaml": run / "aqualoc_archaeo02_pinhole.yaml",
            "vins_aqualoc_archaeo_external_yaml": run / "vins_aqualoc_archaeo_external.yaml",
            "vins_log": run / "vins.log",
        }
        if set(authority) != set(bound_paths):
            raise GovernanceError(f"{arm} VINS provenance authority closure differs")
        for role, path in bound_paths.items():
            expected_hash, expected_size = authority[role]
            record = _workspace_record(path, f"{arm} VINS provenance {role}")
            if (
                record.get("sha256") != expected_hash
                or record.get("size_bytes") != expected_size
            ):
                raise GovernanceError(f"{arm} VINS provenance hard identity differs: {role}")
        replay = _parse_key_value_lines(
            publisher.read_bytes_bound_input_rooted(
                ROOT, run / "replay_manifest.txt", label=f"{arm} replay manifest"
            ),
            f"{arm} replay manifest",
        )
        expected_replay = {
            "run_dir": os.fspath(run),
            "raw_bag": os.fspath(RAW_BAG),
            "play_bag": os.fspath(feature_bag),
            "vins_csv": os.fspath(trajectory),
        }
        if replay != expected_replay:
            raise GovernanceError(f"{arm} replay manifest mapping differs")
        environment = _parse_key_value_lines(
            publisher.read_bytes_bound_input_rooted(
                ROOT, run / "vins_env_manifest.txt", label=f"{arm} VINS env"
            ),
            f"{arm} VINS env",
        )
        expected_environment = {
            "timestamp_utc": "2026-08-13T07:37:54Z" if arm == "xfeat" else "2026-08-13T07:40:32Z",
            "hostname": "qiu",
            "pwd": os.fspath(ROOT),
            "VINS_WS": "/home/ma/SLAM/VINS-Fusion-origin",
            "ROS_MASTER_URI": f"http://localhost:{port}",
            "CMAKE_PREFIX_PATH": "/opt/ros/noetic:/home/ma/SLAM/VINS-Fusion-origin/devel",
            "ROS_PACKAGE_PATH": "/opt/ros/noetic/share:/home/ma/SLAM/VINS-Fusion-origin/src",
            "LD_LIBRARY_PATH": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib:/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu",
            "PYTHONPATH": "/opt/ros/noetic/lib/python3/dist-packages",
            "PATH": "/opt/ros/noetic/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "ROS_DISTRO": "noetic",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "CATKIN_SETUP_UTIL_ARGS": "--local --extend",
            "ROOT": os.fspath(ROOT),
            "AQUALOC_ROOT": os.fspath(ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences"),
            "RAW_TAR": os.fspath(ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_sequence_2_raw_data.tar.gz"),
            "RAW_ROOT": "raw_data",
            "GT_TXT": os.fspath(ROOT / "datasets/full_downloads/aqualoc/Archaeological_site_sequences/archaeo_groundtruth_files/new_archaeo_colmap_traj_sequence_02.txt"),
            "RAW_BAG": os.fspath(RAW_BAG),
            "FEATURE_BAG_OVERRIDE": os.fspath(feature_bag),
            "FRONTEND_CONFIG": os.fspath(ROOT / "uw_frontend/configs/experiments/low_texture_xfeat_seedchain_frontend.yaml"),
            "BACKEND_REPLAY_ONLY": "0",
            "RUN_VINS": "1",
            "FORCE_RAW": "0",
            "FORCE_EXPORT": "0",
            "EXPORT_FEATURES": "0",
            "VINS_MULTIPLE_THREAD": "0",
            "VINS_TD": "-0.053694112369382575",
            "VINS_ESTIMATE_TD": "0",
            "VINS_MAX_SOLVER_TIME": "0.04",
            "VINS_MAX_NUM_ITERATIONS": "8",
            "AQUALOC_BODY_T_CAM0_MODE": "imu_cam",
            "PLAY_RATE": "1.0",
            "POST_PLAY_SLEEP": "8",
            "ROSBAG_PLAY_DELAY": "3",
            "ROSBAG_WAIT_FOR_SUBSCRIBERS": "0",
            "ROSBAG_PLAY_TOPICS": "",
            "WAIT_FOR_VINS_SUBSCRIBERS": "0",
            "WAIT_FOR_VINS_SUBSCRIBERS_TIMEOUT": "20",
            "PORT": port,
            "TAG": f"litcmp_a02_4500_6300_preroll_matchedbirth_formal900_r4_{arm}_vins_r1",
            "rospack_find_vins": "/home/ma/SLAM/VINS-Fusion-origin/src/VINS-Fusion-master/vins_estimator",
            "vins_binary": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
            "vins_binary_stat": "/home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node 13104360 bytes mtime=2026-07-12 01:29:21.068006369 +0800",
            "vins_binary_md5": "7739ae5fe158681765cea3983b8e55bb  /home/ma/SLAM/VINS-Fusion-origin/devel/lib/vins/vins_node",
        }
        if environment != expected_environment:
            raise GovernanceError(f"{arm} VINS environment exact key/value closure differs")
        if replay["run_dir"] != os.fspath(run):
            raise GovernanceError(f"{arm} run directory authority differs")
        log = publisher.read_bytes_bound_input_rooted(
            ROOT, run / "vins.log", label=f"{arm} VINS log"
        )
        marker = b"Initialization finish!"
        if log.count(marker) != 1:
            raise GovernanceError(f"{arm} VINS initialization evidence differs")
        post = log.split(marker, 1)[1]
        for forbidden in (b"Linear solver failure", b"tracking lost", b"reboot", b"restart"):
            if forbidden.lower() in post.lower():
                raise GovernanceError(f"{arm} post-initialization failure evidence differs")
        yaml_text = publisher.read_bytes_bound_input_rooted(
            ROOT,
            run / "vins_aqualoc_archaeo_external.yaml",
            label=f"{arm} VINS effective config",
        ).decode("utf-8")
        for exact_line in (
            "multiple_thread: 0",
            f'output_path: "{run}/vins_output"',
            "max_solver_time: 0.04",
            "max_num_iterations: 8",
            "td: -0.053694112369382575",
            "estimate_td: 0",
        ):
            if yaml_text.splitlines().count(exact_line) != 1:
                raise GovernanceError(f"{arm} effective config differs: {exact_line}")
    runner = _workspace_record(HELPERS["vins_runner"], "VINS runner")
    if runner["sha256"] != "c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc":
        raise GovernanceError("VINS runner authority differs")
    _vins_external_runtime_records()


_SPAWN_SIGNAL_NAMES = ("SIGHUP", "SIGINT", "SIGTERM")


def _spawn_signal_policy() -> dict[str, Any]:
    return {
        "api": "signal.signal_handlers_with_masked_install_restore_transitions",
        "guarded_signals": list(_SPAWN_SIGNAL_NAMES),
        "require_initially_unblocked": True,
        "required_prior_handlers": {
            "SIGHUP": "SIG_DFL",
            "SIGINT": "signal.default_int_handler",
            "SIGTERM": "SIG_DFL",
        },
        "spawn_mask_must_be_empty": True,
        "restore_only_after_child_reaped": True,
    }


def _spawn_target_signals() -> set[signal.Signals]:
    return {signal.Signals(getattr(signal, name)) for name in _SPAWN_SIGNAL_NAMES}


def _spawn_target_signal_names(values: object) -> list[str]:
    try:
        observed = {signal.Signals(int(item)) for item in values}  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise GovernanceError("spawn signal-mask result is malformed") from error
    targets = _spawn_target_signals()
    return [
        name for name in _SPAWN_SIGNAL_NAMES
        if signal.Signals(getattr(signal, name)) in observed & targets
    ]


def _signal_handler_identity(value: object) -> str:
    if value is signal.SIG_DFL:
        return "SIG_DFL"
    if value is signal.default_int_handler:
        return "signal.default_int_handler"
    if value is signal.SIG_IGN:
        return "SIG_IGN"
    return f"{type(value).__module__}.{type(value).__qualname__}"


class _SpawnTerminationSignal(BaseException):
    def __init__(self, signal_name: str) -> None:
        super().__init__(f"received {signal_name} while child was owned")
        self.signal_name = signal_name


def _validate_spawn_signal_guard(
    value: object, *, process_started: bool, success: bool
) -> dict[str, Any]:
    expected_keys = {
        "policy", "prior_target_mask", "prior_handlers",
        "install_transition_mask_applied", "handlers_installed_before_popen",
        "spawn_target_mask", "pid_captured_while_handlers_installed",
        "received_signals", "cleanup_mode_before_restore",
        "child_reaped_before_restore", "restore_transition_mask_applied",
        "handlers_restored", "post_restore_target_mask",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise GovernanceError("spawn signal guard field set differs")
    received = value.get("received_signals")
    if (
        value.get("policy") != _spawn_signal_policy()
        or value.get("prior_target_mask") != []
        or value.get("prior_handlers") != _spawn_signal_policy()["required_prior_handlers"]
        or value.get("install_transition_mask_applied") is not True
        or value.get("handlers_installed_before_popen") is not True
        or value.get("spawn_target_mask") != []
        or type(value.get("pid_captured_while_handlers_installed")) is not bool
        or (success and value.get("pid_captured_while_handlers_installed") is not True)
        or (
            not process_started
            and value.get("pid_captured_while_handlers_installed") is not False
        )
        or not isinstance(received, list)
        or any(item not in _SPAWN_SIGNAL_NAMES for item in received)
        or value.get("cleanup_mode_before_restore") is not True
        or value.get("child_reaped_before_restore") is not True
        or value.get("restore_transition_mask_applied") is not True
        or value.get("handlers_restored") is not True
        or value.get("post_restore_target_mask") != []
        or (success and received != [])
    ):
        raise GovernanceError("spawn signal guard authority differs")
    return dict(value)


class _SpawnSignalGuard:
    """Own termination signals until a returned child is synchronously reaped."""

    def __init__(self) -> None:
        self.targets = _spawn_target_signals()
        self.previous_mask: set[signal.Signals] | None = None
        self.previous_handlers: dict[signal.Signals, object] = {}
        self.received: list[str] = []
        self.process: Any = None
        self.pid: int | None = None
        self.process_owned = False
        self.cleanup_mode = False
        self.handlers_installed = False
        self.handlers_restored = False
        self.install_mask_applied = False
        self.restore_mask_applied = False
        self.spawn_mask: list[str] = []
        self.post_restore_mask: list[str] = []

    def _handler(self, signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        if name not in self.received:
            self.received.append(name)
            self.received.sort(key=_SPAWN_SIGNAL_NAMES.index)
        if self.process_owned and not self.cleanup_mode:
            # Switch to record-only before raising so cleanup cannot be
            # re-entered by a second termination signal.
            self.cleanup_mode = True
            raise _SpawnTerminationSignal(name)

    def install(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            raise GovernanceError("spawn signal guard requires the main thread")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, self.targets)
        self.install_mask_applied = True
        self.previous_mask = set(previous_mask)
        try:
            if _spawn_target_signal_names(previous_mask):
                raise GovernanceError("spawn termination signals were already blocked")
            expected = _spawn_signal_policy()["required_prior_handlers"]
            for target in self.targets:
                prior = signal.getsignal(target)
                name = signal.Signals(target).name
                if _signal_handler_identity(prior) != expected[name]:
                    raise GovernanceError(f"spawn prior handler differs: {name}")
                self.previous_handlers[target] = prior
            for target in self.targets:
                signal.signal(target, self._handler)
            self.handlers_installed = True
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        self.spawn_mask = _spawn_target_signal_names(
            signal.pthread_sigmask(signal.SIG_BLOCK, set())
        )
        if self.spawn_mask:
            raise GovernanceError("spawn target signals remained blocked after handler install")

    def spawn(self, argv: Sequence[str], **kwargs: Any) -> tuple[Any, int]:
        if not self.handlers_installed:
            self.install()
        self.process = subprocess.Popen(tuple(argv), **kwargs)
        self.pid = int(self.process.pid)
        if self.pid <= 0:
            raise GovernanceError("spawned child PID is not positive")
        self.process_owned = True
        if self.received:
            self.cleanup_mode = True
            raise _SpawnTerminationSignal(self.received[0])
        return self.process, self.pid

    def begin_cleanup(self) -> None:
        self.cleanup_mode = True

    def finish(self, *, child_reaped: bool) -> dict[str, Any]:
        self.cleanup_mode = True
        if self.process is not None and not child_reaped:
            raise GovernanceError("cannot restore spawn handlers before child reap")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, self.targets)
        self.restore_mask_applied = True
        try:
            if _spawn_target_signal_names(previous_mask):
                raise GovernanceError("spawn termination mask drifted before handler restore")
            # Unblock while our cleanup-only handlers are still installed.
            # A signal arriving in the masked transition is therefore
            # delivered to the recorder, never to a restored default action.
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            for target in self.targets:
                prior = self.previous_handlers.get(target)
                if prior is None:
                    raise GovernanceError("spawn prior handler record is incomplete")
                signal.signal(target, prior)
            self.handlers_restored = True
        except BaseException:
            # Do not leave the transition mask installed on an error path.
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            raise
        self.post_restore_mask = _spawn_target_signal_names(
            signal.pthread_sigmask(signal.SIG_BLOCK, set())
        )
        audit = {
            "policy": _spawn_signal_policy(),
            "prior_target_mask": _spawn_target_signal_names(self.previous_mask or set()),
            "prior_handlers": {
                signal.Signals(target).name: _signal_handler_identity(handler)
                for target, handler in sorted(
                    self.previous_handlers.items(), key=lambda item: int(item[0])
                )
            },
            "install_transition_mask_applied": self.install_mask_applied,
            "handlers_installed_before_popen": self.handlers_installed,
            "spawn_target_mask": self.spawn_mask,
            "pid_captured_while_handlers_installed": self.process_owned,
            "received_signals": list(self.received),
            "cleanup_mode_before_restore": self.cleanup_mode,
            "child_reaped_before_restore": child_reaped,
            "restore_transition_mask_applied": self.restore_mask_applied,
            "handlers_restored": self.handlers_restored,
            "post_restore_target_mask": self.post_restore_mask,
        }
        return audit


def _probe_launch_intent_payload(
    *,
    command: Sequence[str],
    environment: Mapping[str, str],
    pass_fds: Sequence[int],
    timeout: object,
    canonical_argv: Sequence[str],
    source_records: Mapping[str, Mapping[str, Any]],
    intent_path: Path,
    failure_path: Path,
) -> dict[str, Any]:
    if timeout != RUNTIME_PROBE_TIMEOUT_SECONDS:
        raise GovernanceError("runtime probe timeout differs before launch intent")
    payload: dict[str, Any] = {
        "schema_version": PROBE_LAUNCH_SCHEMA,
        "status": "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY",
        "attempt_count": 1,
        "authorized_process_start_count": 1,
        "no_retry_after_pending_evidence": True,
        "timeout_seconds": RUNTIME_PROBE_TIMEOUT_SECONDS,
        "authorized_canonical_argv": list(canonical_argv),
        "actual_procfd_argv": list(command),
        "actual_environment": dict(environment),
        "actual_environment_sha256": hashlib.sha256(
            _canonical_json_bytes(dict(environment))
        ).hexdigest(),
        "pass_fd_numbers": sorted(int(item) for item in pass_fds),
        "spawn_signal_policy": _spawn_signal_policy(),
        "probe_source": {key: dict(value) for key, value in source_records.items()},
        "intent_path": os.fspath(intent_path),
        "failure_path": os.fspath(failure_path),
        "probe_launch_intent_hash": "0" * 64,
    }
    payload["probe_launch_intent_hash"] = p07gov.canonical_json_hash(
        payload, "probe_launch_intent_hash"
    )
    return payload


def _validate_probe_launch_intent(
    value: object,
    *,
    canonical_argv: Sequence[str] | None = None,
    source_records: Mapping[str, Mapping[str, Any]] | None = None,
    intent_path: Path = PROBE_INTENT,
    failure_path: Path = PROBE_FAILURE,
) -> dict[str, Any]:
    expected_keys = {
        "schema_version", "status", "attempt_count",
        "authorized_process_start_count", "no_retry_after_pending_evidence",
        "timeout_seconds", "authorized_canonical_argv", "actual_procfd_argv",
        "actual_environment", "actual_environment_sha256", "pass_fd_numbers",
        "spawn_signal_policy", "probe_source",
        "intent_path", "failure_path", "probe_launch_intent_hash",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise GovernanceError("runtime probe launch intent field set differs")
    p07gov.validate_self_hash(
        value, "probe_launch_intent_hash", label="runtime probe launch intent"
    )
    if (
        value.get("schema_version") != PROBE_LAUNCH_SCHEMA
        or value.get("status") != "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY"
        or value.get("attempt_count") != 1
        or value.get("authorized_process_start_count") != 1
        or value.get("no_retry_after_pending_evidence") is not True
        or value.get("timeout_seconds") != RUNTIME_PROBE_TIMEOUT_SECONDS
        or value.get("intent_path") != os.fspath(intent_path)
        or value.get("failure_path") != os.fspath(failure_path)
        or re.fullmatch(r"[0-9a-f]{64}", str(value.get("actual_environment_sha256"))) is None
        or not isinstance(value.get("actual_environment"), Mapping)
        or hashlib.sha256(
            _canonical_json_bytes(dict(value.get("actual_environment", {})))
        ).hexdigest() != value.get("actual_environment_sha256")
        or not isinstance(value.get("actual_procfd_argv"), list)
        or not isinstance(value.get("pass_fd_numbers"), list)
        or value.get("pass_fd_numbers") != sorted(set(value["pass_fd_numbers"]))
        or any(not isinstance(item, int) or item <= 0 for item in value["pass_fd_numbers"])
        or value.get("spawn_signal_policy") != _spawn_signal_policy()
        or not isinstance(value.get("probe_source"), Mapping)
    ):
        raise GovernanceError("runtime probe launch intent authority differs")
    if canonical_argv is not None and value.get("authorized_canonical_argv") != list(canonical_argv):
        raise GovernanceError("runtime probe launch intent canonical argv differs")
    if canonical_argv is not None and list(canonical_argv) == [
        os.fspath(PYTHON), "-I", "-B", os.fspath(BOOTSTRAP),
        bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
    ]:
        actual = value["actual_procfd_argv"]
        if (
            len(actual) != len(canonical_argv)
            or actual[1:3] != ["-I", "-B"]
            or actual[4] != bootstrap.PROBE_ARGUMENT
            or actual[6] != REFERENCE_TOPIC
            or any(
                re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", str(actual[index])) is None
                for index in (0, 3, 5)
            )
            or not {
                int(str(actual[index]).rsplit("/", 1)[1]) for index in (0, 3, 5)
            }.issubset(set(value["pass_fd_numbers"]))
        ):
            raise GovernanceError("runtime probe launch intent procfd argv differs")
    if source_records is not None and value.get("probe_source") != {
        key: dict(record) for key, record in source_records.items()
    }:
        raise GovernanceError("runtime probe launch intent source binding differs")
    return dict(value)


def _probe_failure_payload(
    intent: Mapping[str, Any],
    *,
    pid: int | None,
    process_started: bool,
    timed_out: bool,
    return_code: int | None,
    classification: str,
    wait_error: BaseException | None,
    cleanup_errors: Sequence[Mapping[str, str]],
    child_reaped: bool,
    spawn_signal_guard: Mapping[str, Any],
    stdout: bytes,
    stderr: bytes,
) -> dict[str, Any]:
    termination_signal = -return_code if isinstance(return_code, int) and return_code < 0 else None
    payload: dict[str, Any] = {
        "schema_version": PROBE_FAILURE_SCHEMA,
        "status": "TERMINAL_RUNTIME_PROBE_FAILURE_NO_RETRY",
        "attempt_count": 1,
        "process_start_count": 1 if process_started else 0,
        "no_retry": True,
        "pid": pid,
        "timeout_seconds": RUNTIME_PROBE_TIMEOUT_SECONDS,
        "timed_out": timed_out,
        "return_code": return_code,
        "termination_signal": termination_signal,
        "classification": classification,
        "wait_error": _exception_identity(wait_error) if wait_error is not None else None,
        "cleanup_errors": [dict(item) for item in cleanup_errors],
        "child_reaped": child_reaped,
        "spawn_signal_guard": dict(spawn_signal_guard),
        "stdout": _stream_receipt(stdout),
        "stderr": _stream_receipt(stderr),
        "probe_launch_intent_hash": intent["probe_launch_intent_hash"],
        "probe_failure_receipt_hash": "0" * 64,
    }
    payload["probe_failure_receipt_hash"] = p07gov.canonical_json_hash(
        payload, "probe_failure_receipt_hash"
    )
    return payload


def _validate_probe_failure_receipt(value: object, intent: Mapping[str, Any]) -> dict[str, Any]:
    expected_keys = {
        "schema_version", "status", "attempt_count", "process_start_count",
        "no_retry", "pid", "timeout_seconds", "timed_out", "return_code",
        "termination_signal", "classification", "wait_error", "cleanup_errors",
        "child_reaped", "spawn_signal_guard", "stdout", "stderr",
        "probe_launch_intent_hash",
        "probe_failure_receipt_hash",
    }
    if not isinstance(value, Mapping) or set(value) != expected_keys:
        raise GovernanceError("runtime probe failure receipt field set differs")
    p07gov.validate_self_hash(
        value, "probe_failure_receipt_hash", label="runtime probe failure receipt"
    )
    if (
        value.get("schema_version") != PROBE_FAILURE_SCHEMA
        or value.get("status") != "TERMINAL_RUNTIME_PROBE_FAILURE_NO_RETRY"
        or value.get("attempt_count") != 1
        or value.get("process_start_count") not in (0, 1)
        or value.get("no_retry") is not True
        or value.get("timeout_seconds") != RUNTIME_PROBE_TIMEOUT_SECONDS
        or value.get("classification") == "EXITED_RC0"
        or value.get("probe_launch_intent_hash") != intent.get("probe_launch_intent_hash")
        or value.get("child_reaped") is not True
        or not isinstance(value.get("cleanup_errors"), list)
    ):
        raise GovernanceError("runtime probe failure receipt is not terminal/reaped")
    _validate_spawn_signal_guard(
        value.get("spawn_signal_guard"),
        process_started=value.get("process_start_count") == 1,
        success=False,
    )
    return dict(value)


def _wait_status_return_code(status: int) -> int:
    if os.WIFEXITED(status):
        return os.WEXITSTATUS(status)
    if os.WIFSIGNALED(status):
        return -os.WTERMSIG(status)
    raise GovernanceError("runtime probe waitpid returned a nonterminal status")


def _cleanup_probe_child(
    process: Any,
    pid: int | None,
    wait_error: BaseException,
    stdout: bytes,
    stderr: bytes,
) -> tuple[bytes, bytes, int | None, list[dict[str, str]], bool]:
    """TERM, escalate to KILL, and synchronously reap after any wait failure."""

    cleanup_errors: list[dict[str, str]] = []
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    except BaseException as error:
        cleanup_errors.append(_exception_identity(error))
        try:
            if pid is None:
                raise GovernanceError("spawned child PID unavailable for SIGTERM fallback")
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except BaseException as signal_error:
            cleanup_errors.append(_exception_identity(signal_error))
    try:
        out, err = process.communicate(timeout=PROCESS_CLEANUP_TIMEOUT_SECONDS)
        if isinstance(out, bytes):
            stdout = out
        if isinstance(err, bytes):
            stderr = err
    except BaseException as error:
        cleanup_errors.append(_exception_identity(error))
    return_code = getattr(process, "returncode", None)
    if return_code is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        except BaseException as error:
            cleanup_errors.append(_exception_identity(error))
            try:
                if pid is None:
                    raise GovernanceError("spawned child PID unavailable for SIGKILL fallback")
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except BaseException as signal_error:
                cleanup_errors.append(_exception_identity(signal_error))
        try:
            out, err = process.communicate(timeout=PROCESS_CLEANUP_TIMEOUT_SECONDS)
            if isinstance(out, bytes):
                stdout = out
            if isinstance(err, bytes):
                stderr = err
        except BaseException as error:
            cleanup_errors.append(_exception_identity(error))
        return_code = getattr(process, "returncode", None)
    if return_code is None:
        try:
            if pid is None:
                raise GovernanceError("spawned child PID unavailable for final SIGKILL")
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except BaseException as error:
            cleanup_errors.append(_exception_identity(error))
        try:
            if pid is None:
                raise GovernanceError("spawned child PID unavailable for waitpid")
            waited_pid, status = os.waitpid(pid, 0)
            if waited_pid != pid:
                raise GovernanceError("runtime probe reaped a different child")
            return_code = _wait_status_return_code(status)
            try:
                process.returncode = return_code
            except BaseException:
                pass
        except ChildProcessError:
            return_code = getattr(process, "returncode", None)
        except BaseException as error:
            cleanup_errors.append(_exception_identity(error))
    child_reaped = isinstance(return_code, int)
    if not child_reaped:
        cleanup_errors.append({
            "class": "UNREAPED_RUNTIME_PROBE_CHILD",
            "message": f"pid {pid} remained unreaped after SIGKILL",
        })
    return stdout, stderr, return_code, cleanup_errors, child_reaped


class _OneRunProbeCapture:
    """Subprocess facade with a durable O_EXCL one-attempt namespace."""

    PIPE = subprocess.PIPE

    def __init__(
        self,
        *,
        stack: ExitStack,
        canonical_argv: Sequence[str],
        source_records: Mapping[str, Mapping[str, Any]],
        intent_path: Path | None = None,
        failure_path: Path | None = None,
    ) -> None:
        self.stack = stack
        self.canonical_argv = list(canonical_argv)
        self.source_records = {key: dict(value) for key, value in source_records.items()}
        self.intent_path = PROBE_INTENT if intent_path is None else intent_path
        self.failure_path = PROBE_FAILURE if failure_path is None else failure_path
        self.calls = 0
        self.observed: dict[str, Any] | None = None
        self.intent: dict[str, Any] | None = None
        self.intent_record: dict[str, Any] | None = None
        self.intent_validator: Any = None

    def _persist_intent(
        self, command: Sequence[str], environment: Mapping[str, str],
        pass_fds: Sequence[int], timeout: object,
    ) -> dict[str, Any]:
        if os.path.lexists(self.intent_path) or os.path.lexists(self.failure_path):
            if not os.path.lexists(self.intent_path):
                raise GovernanceError(
                    "runtime probe failure exists without its launch intent; no retry"
                )
            prior_intent = _load_json_static(
                self.intent_path, "existing runtime probe launch intent"
            )
            _validate_probe_launch_intent(
                prior_intent,
                canonical_argv=self.canonical_argv,
                source_records=self.source_records,
                intent_path=self.intent_path,
                failure_path=self.failure_path,
            )
            if os.path.lexists(self.failure_path):
                prior_failure = _load_json_static(
                    self.failure_path, "existing runtime probe failure receipt"
                )
                _validate_probe_failure_receipt(prior_failure, prior_intent)
            raise GovernanceError("runtime probe terminal namespace already consumed; no retry")
        intent = _probe_launch_intent_payload(
            command=command, environment=environment, pass_fds=pass_fds,
            timeout=timeout, canonical_argv=self.canonical_argv,
            source_records=self.source_records, intent_path=self.intent_path,
            failure_path=self.failure_path,
        )
        _validate_probe_launch_intent(
            intent,
            canonical_argv=self.canonical_argv,
            source_records=self.source_records,
            intent_path=self.intent_path,
            failure_path=self.failure_path,
        )
        self.intent_validator, self.intent_record = self.stack.enter_context(
            _write_held_canonical_json_rooted(
                ROOT,
                self.intent_path,
                intent,
                label="runtime probe launch intent",
            )
        )
        self.intent_validator()
        if _load_json_static(
            self.intent_path, "runtime probe launch intent"
        ) != intent:
            raise GovernanceError("runtime probe launch intent live object differs")
        self.intent = intent
        return intent

    def _persist_failure(self, payload: Mapping[str, Any]) -> None:
        if self.intent is None or self.intent_validator is None:
            raise GovernanceError("runtime probe failure lacks retained launch intent")
        self.intent_validator()
        _validate_probe_failure_receipt(payload, self.intent)
        failure_validator, _failure_record = self.stack.enter_context(
            _write_held_canonical_json_rooted(
                ROOT,
                self.failure_path,
                payload,
                label="runtime probe failure receipt",
            )
        )
        observed = _load_json_static(self.failure_path, "runtime probe failure receipt")
        if observed != payload:
            raise GovernanceError("runtime probe failure live object differs")
        _validate_probe_failure_receipt(observed, self.intent)
        failure_validator()
        self.intent_validator()

    def run(self, command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
        self.calls += 1
        if self.calls != 1:
            raise GovernanceError("runtime probe attempted more than one process")
        timeout = kwargs.pop("timeout")
        check = kwargs.pop("check")
        if (
            check is not False
            or set(kwargs) != {"cwd", "env", "pass_fds", "stdout", "stderr"}
            or kwargs.get("cwd") != "/"
            or kwargs.get("stdout") != subprocess.PIPE
            or kwargs.get("stderr") != subprocess.PIPE
            or not isinstance(kwargs.get("env"), Mapping)
            or not isinstance(kwargs.get("pass_fds"), tuple)
        ):
            raise GovernanceError("runtime probe subprocess contract differs")
        environment = dict(kwargs["env"])
        pass_fds = tuple(kwargs["pass_fds"])
        intent = self._persist_intent(command, environment, pass_fds, timeout)
        process: Any = None
        pid: int | None = None
        stdout = b""
        stderr = b""
        wait_error: BaseException | None = None
        timed_out = False
        cleanup_errors: list[dict[str, str]] = []
        child_reaped = True
        spawn_signal_guard: dict[str, Any]
        guard = _SpawnSignalGuard()
        spawn_stage = "SPAWN"
        try:
            process, pid = guard.spawn(
                command, stdin=subprocess.DEVNULL, **kwargs
            )
            spawn_stage = "WAIT"
            stdout, stderr = process.communicate(timeout=timeout)
            guard.begin_cleanup()
        except subprocess.TimeoutExpired as error:
            guard.begin_cleanup()
            process = guard.process
            pid = guard.pid
            wait_error = error
            timed_out = True
        except BaseException as error:
            guard.begin_cleanup()
            process = guard.process
            pid = guard.pid
            wait_error = error
        if guard.received and wait_error is None:
            wait_error = _SpawnTerminationSignal(guard.received[0])
        if process is None:
            spawn_signal_guard = guard.finish(child_reaped=True)
            failure = _probe_failure_payload(
                intent, pid=None, process_started=False, timed_out=False,
                return_code=None, classification="PROCESS_START_ERROR",
                wait_error=wait_error, cleanup_errors=[], child_reaped=True,
                spawn_signal_guard=spawn_signal_guard,
                stdout=b"", stderr=b"",
            )
            self._persist_failure(failure)
            raise GovernanceError("runtime probe process failed to start; terminal no-retry evidence written") from wait_error
        return_code = getattr(process, "returncode", None)
        if wait_error is not None:
            partial_stdout = getattr(wait_error, "output", None)
            partial_stderr = getattr(wait_error, "stderr", None)
            if isinstance(partial_stdout, bytes):
                stdout = partial_stdout
            if isinstance(partial_stderr, bytes):
                stderr = partial_stderr
            guard.begin_cleanup()
            stdout, stderr, return_code, cleanup_errors, child_reaped = _cleanup_probe_child(
                process, pid, wait_error, stdout, stderr
            )
        elif not isinstance(return_code, int):
            wait_error = GovernanceError("runtime probe communicate returned without reaping child")
            guard.begin_cleanup()
            stdout, stderr, return_code, cleanup_errors, child_reaped = _cleanup_probe_child(
                process, pid, wait_error, stdout, stderr
            )
        spawn_signal_guard = guard.finish(child_reaped=child_reaped)
        if spawn_signal_guard["received_signals"] and wait_error is None:
            wait_error = _SpawnTerminationSignal(
                str(spawn_signal_guard["received_signals"][0])
            )
        if wait_error is not None or return_code != 0 or cleanup_errors or not child_reaped:
            classification = (
                "SPAWN_WINDOW_ERROR_TERMINATED" if spawn_stage == "SPAWN" else
                "TIMEOUT_TERMINATED" if timed_out else
                "WAIT_ERROR_TERMINATED" if wait_error is not None else
                "TERMINATED_BY_SIGNAL" if isinstance(return_code, int) and return_code < 0 else
                "EXITED_NONZERO"
            )
            failure = _probe_failure_payload(
                intent, pid=pid, process_started=True, timed_out=timed_out,
                return_code=return_code, classification=classification,
                wait_error=wait_error, cleanup_errors=cleanup_errors,
                child_reaped=child_reaped,
                spawn_signal_guard=spawn_signal_guard,
                stdout=stdout, stderr=stderr,
            )
            self._persist_failure(failure)
            raise GovernanceError(
                "runtime probe failed after launch; terminal no-retry evidence written"
            ) from wait_error
        self.intent_validator()
        self.observed = {
            "pid": pid,
            "argv": list(command),
            "environment": environment,
            "pass_fds": list(pass_fds),
            "timeout_seconds": timeout,
            "timed_out": False,
            "return_code": return_code,
            "stdout": stdout,
            "stderr": stderr,
            "spawn_signal_guard": spawn_signal_guard,
        }
        return subprocess.CompletedProcess(command, int(return_code), stdout, stderr)


def _capture_runtime_closure(stack: ExitStack) -> dict[str, Any]:
    """The sole processful freeze-time capture entrypoint.

    The bootstrap owns the representative child probe so its schema and the
    per-role runtime receipts share one code authority.  No validator calls
    this function.
    """
    records = {
        "python": _external_record(PYTHON, "runtime-probe Python"),
        "bootstrap": _workspace_record(BOOTSTRAP, "runtime-probe bootstrap"),
        "wrapper": _workspace_record(WRAPPER, "runtime-probe wrapper"),
        "base": _workspace_record(BASE, "runtime-probe base"),
        "core": _workspace_record(CORE, "runtime-probe core"),
        "reference_bag": _workspace_record(RAW_BAG, "runtime-probe reference bag"),
    }
    canonical_probe_argv = [
        os.fspath(PYTHON), "-I", "-B", os.fspath(BOOTSTRAP),
        bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
    ]
    capture = _OneRunProbeCapture(
        stack=stack,
        canonical_argv=canonical_probe_argv,
        source_records=records,
    )
    original_subprocess = bootstrap.subprocess
    if original_subprocess is not subprocess:
        raise GovernanceError("bootstrap subprocess module identity differs")
    bootstrap.subprocess = capture  # type: ignore[assignment]
    try:
        try:
            runtime_receipt = bootstrap.capture_freeze_runtime(
                root=ROOT,
                python=PYTHON,
                wrapper=WRAPPER,
                base=BASE,
                core=CORE,
                reference_bag=RAW_BAG,
                reference_topic=REFERENCE_TOPIC,
                environment_template=_environment_template("primary"),
            )
        except BaseException as error:
            # A child may exit RC0 yet return malformed/unacceptable receipt
            # bytes.  The already-durable pending intent still forbids retry;
            # add terminal evidence for that post-wait validation failure.
            if (
                capture.intent is not None
                and capture.observed is not None
                and not os.path.lexists(capture.failure_path)
            ):
                observed = capture.observed
                failure = _probe_failure_payload(
                    capture.intent,
                    pid=int(observed["pid"]),
                    process_started=True,
                    timed_out=False,
                    return_code=int(observed["return_code"]),
                    classification="POST_WAIT_RECEIPT_VALIDATION_ERROR",
                    wait_error=error,
                    cleanup_errors=[],
                    child_reaped=True,
                    spawn_signal_guard=observed["spawn_signal_guard"],
                    stdout=observed["stdout"],
                    stderr=observed["stderr"],
                )
                capture._persist_failure(failure)
            raise
    finally:
        if bootstrap.subprocess is not capture:
            raise GovernanceError("bootstrap subprocess capture owner changed")
        bootstrap.subprocess = original_subprocess
    if capture.calls != 1 or capture.observed is None:
        raise GovernanceError("representative runtime probe process count differs")
    if capture.intent is None or capture.intent_record is None or capture.intent_validator is None:
        raise GovernanceError("representative runtime probe lacks retained launch intent")
    capture.intent_validator()
    observed = capture.observed
    if observed["timed_out"] or observed["return_code"] != 0:
        raise GovernanceError("representative runtime probe did not exit RC0")
    bootstrap.validate_freeze_runtime_static(runtime_receipt)
    sealed_sources = runtime_receipt.get("sealed_sources")
    if not isinstance(sealed_sources, Mapping):
        raise GovernanceError("representative runtime probe sealed sources differ")
    probe_aliases = {
        os.fspath(PYTHON): observed["argv"][0],
        os.fspath(BOOTSTRAP): observed["argv"][3],
        os.fspath(RAW_BAG): observed["argv"][5],
        "${EPOCH_WRAPPER_PROCFD}": sealed_sources["wrapper"]["locator"],
        "${EVALUATOR_BASE_PROCFD}": sealed_sources["evaluator_base"]["locator"],
        "${TRAJECTORY_CORE_PROCFD}": sealed_sources["evaluator_core"]["locator"],
    }
    probe_record_roles = {
        os.fspath(PYTHON): "python",
        os.fspath(BOOTSTRAP): "bootstrap",
        os.fspath(RAW_BAG): "reference_bag",
        "${EPOCH_WRAPPER_PROCFD}": "wrapper",
        "${EVALUATOR_BASE_PROCFD}": "base",
        "${TRAJECTORY_CORE_PROCFD}": "core",
    }
    probe_binding_records = {
        canonical: {
            "kind": "SEALED_PROBE_FILE" if canonical != os.fspath(RAW_BAG)
            else "HELD_REFERENCE_BAG",
            "locator": probe_aliases[canonical],
            "record": dict(records[source_role]),
        }
        for canonical, source_role in probe_record_roles.items()
    }
    expected_probe_fds = sorted(
        int(locator.rsplit("/", 1)[1]) for locator in probe_aliases.values()
    )
    if sorted(observed["pass_fds"]) != expected_probe_fds:
        raise GovernanceError("runtime probe Popen pass_fds differ from sealed locators")
    value = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-expected-runtime-closure-v1",
        "status": "CAPTURED_BY_ONE_SEALED_REPRESENTATIVE_CHILD",
        "claim_scope": "EXPECTED_BASELINE_ONLY;ACTUAL_ROLE_CLOSURE_IS_RECEIPTED_SEPARATELY",
        "probe_source": records,
        "probe_launch_intent": capture.intent,
        "probe_launch_intent_record": capture.intent_record,
        "probe_process": {
            "pid": observed["pid"],
            "process_started_before_wait": True,
            "attempt_count": 1,
            "process_start_count": 1,
            "no_retry": True,
            "timeout_seconds": observed["timeout_seconds"],
            "timed_out": False,
            "return_code": 0,
            "termination_signal": None,
            "classification": "EXITED_RC0",
            "authorized_canonical_argv": canonical_probe_argv,
            "actual_procfd_argv": observed["argv"],
            "actual_procfd_aliases": probe_aliases,
            "actual_procfd_binding_records": probe_binding_records,
            "pass_fd_locators": sorted(set(probe_aliases.values())),
            "pass_fd_numbers": expected_probe_fds,
            "environment_sha256": hashlib.sha256(
                _canonical_json_bytes(observed["environment"])
            ).hexdigest(),
            "spawn_signal_guard": observed["spawn_signal_guard"],
            "stdout": _stream_receipt(observed["stdout"]),
            "stderr": _stream_receipt(observed["stderr"]),
        },
        "runtime_receipt": runtime_receipt,
    }
    value["expected_runtime_closure_hash"] = p07gov.canonical_json_hash(value)
    return value


def _persistent_records(receipt: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result: list[Mapping[str, Any]] = []
    modules = receipt.get("persistent_modules")
    if not isinstance(modules, list):
        raise GovernanceError("runtime persistent_modules is malformed")
    for module in modules:
        identities = module.get("file_identities") if isinstance(module, Mapping) else None
        if not isinstance(identities, Mapping):
            raise GovernanceError("runtime module file identities are malformed")
        for record in identities.values():
            if not isinstance(record, Mapping):
                raise GovernanceError("runtime module file record is malformed")
            result.append(record)
    maps = receipt.get("persistent_proc_maps")
    files = maps.get("files") if isinstance(maps, Mapping) else None
    if not isinstance(files, list):
        raise GovernanceError("runtime mapped-file closure is malformed")
    for record in files:
        if not isinstance(record, Mapping):
            raise GovernanceError("runtime mapped-file record is malformed")
        result.append(record)
    return result


def _validate_persistent_runtime_files(receipt: Mapping[str, Any]) -> None:
    by_path: dict[str, Mapping[str, Any]] = {}
    for record in _persistent_records(receipt):
        path = record.get("lexical_path")
        if not isinstance(path, str):
            raise GovernanceError("persistent runtime record lacks lexical path")
        previous = by_path.setdefault(path, record)
        if previous != record:
            raise GovernanceError(f"persistent runtime path has conflicting identities: {path}")
    for path, record in by_path.items():
        if bootstrap.persistent_file_identity(path) != record:
            raise GovernanceError(f"persistent runtime file drifted: {path}")


class _HeldPersistentRuntimeFile:
    """Hold both a persistent lexical leaf and its resolved regular inode."""

    def __init__(self, record: Mapping[str, Any], label: str):
        self.record = dict(record)
        self.label = label
        self.lexical_fd = -1
        self.resolved_fd = -1
        self.lexical_stat: os.stat_result | None = None
        self.resolved_stat: os.stat_result | None = None

    @staticmethod
    def _stable_stat(value: os.stat_result) -> tuple[int, ...]:
        return (
            int(value.st_dev), int(value.st_ino), int(value.st_mode),
            int(value.st_nlink), int(value.st_uid), int(value.st_gid),
            int(value.st_size), int(value.st_mtime_ns), int(value.st_ctime_ns),
        )

    @staticmethod
    def _hash_fd(descriptor: int, size: int) -> str:
        digest = hashlib.sha256()
        offset = 0
        while offset < size:
            chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
            if not chunk:
                raise GovernanceError("short held persistent-runtime read")
            digest.update(chunk)
            offset += len(chunk)
        return digest.hexdigest()

    def __enter__(self) -> "_HeldPersistentRuntimeFile":
        lexical = str(self.record["lexical_path"])
        resolved = str(self.record["resolved_path"])
        if bootstrap.persistent_file_identity(lexical) != self.record:
            raise GovernanceError(f"{self.label} differs before retained hold")
        lexical_flags = os.O_CLOEXEC | getattr(os, "O_PATH", os.O_RDONLY)
        lexical_flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            self.lexical_fd = os.open(lexical, lexical_flags)
            self.resolved_fd = os.open(
                resolved, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            )
            self.lexical_stat = os.fstat(self.lexical_fd)
            self.resolved_stat = os.fstat(self.resolved_fd)
            self.validate()
            return self
        except BaseException:
            self._close_best_effort()
            raise

    def _close_best_effort(self) -> None:
        for field in ("resolved_fd", "lexical_fd"):
            descriptor = int(getattr(self, field))
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
                setattr(self, field, -1)

    def validate(self) -> None:
        if (
            self.lexical_fd < 0 or self.resolved_fd < 0
            or self.lexical_stat is None or self.resolved_stat is None
        ):
            raise GovernanceError(f"{self.label} retained hold is closed")
        lexical = str(self.record["lexical_path"])
        if (
            self._stable_stat(os.fstat(self.lexical_fd))
            != self._stable_stat(self.lexical_stat)
            or self._stable_stat(os.fstat(self.resolved_fd))
            != self._stable_stat(self.resolved_stat)
            or int(self.resolved_stat.st_size) != int(self.record["size_bytes"])
            or self._hash_fd(self.resolved_fd, int(self.resolved_stat.st_size))
            != self.record["sha256"]
            or bootstrap.persistent_file_identity(lexical) != self.record
        ):
            raise GovernanceError(f"{self.label} drifted across retained hold")

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        try:
            self.validate()
        finally:
            self._close_best_effort()


def _retained_runtime_file_holds(
    stack: ExitStack, receipt: Mapping[str, Any], *, label: str
) -> list[_HeldPersistentRuntimeFile]:
    records = list(_persistent_records(receipt))
    native = receipt.get("native_loaded_elf_closure")
    if not isinstance(native, list):
        raise GovernanceError("runtime native ELF closure is malformed")
    for item in native:
        if not isinstance(item, Mapping):
            raise GovernanceError("runtime native ELF hold row is malformed")
        kind = item.get("mapping_kind")
        if kind == "PERSISTENT_ELF":
            record = item.get("file")
            if not isinstance(record, Mapping):
                raise GovernanceError("runtime persistent ELF file hold is malformed")
            records.append(record)
        elif kind != "SEALED_MAPPED_FILE":
            raise GovernanceError("runtime native ELF hold kind differs")
    by_path: dict[str, Mapping[str, Any]] = {}
    for record in records:
        lexical = record.get("lexical_path")
        if not isinstance(lexical, str):
            raise GovernanceError("runtime persistent hold lacks lexical path")
        prior = by_path.setdefault(lexical, record)
        if prior != record:
            raise GovernanceError(f"runtime persistent hold conflicts: {lexical}")
    return [
        stack.enter_context(
            _HeldPersistentRuntimeFile(record, f"{label} {lexical}")
        )
        for lexical, record in sorted(by_path.items())
    ]


def _validate_runtime_file_holds(
    holds: Sequence[_HeldPersistentRuntimeFile],
) -> None:
    for hold in holds:
        hold.validate()


def _sealed_content_identity(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sealed = receipt.get("sealed_sources")
    if not isinstance(sealed, Mapping):
        raise GovernanceError("runtime sealed-source closure is malformed")
    result: dict[str, dict[str, Any]] = {}
    for role, record in sealed.items():
        if not isinstance(record, Mapping):
            raise GovernanceError(f"runtime sealed-source record malformed: {role}")
        result[str(role)] = {
            "sha256": record.get("sha256"),
            "size_bytes": record.get("size_bytes"),
            "seals": record.get("seals"),
        }
    return result


def _validate_freeze_runtime_static(value: object, freeze: Mapping[str, Any] | None = None) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "status",
        "claim_scope",
        "probe_source",
        "probe_launch_intent",
        "probe_launch_intent_record",
        "probe_process",
        "runtime_receipt",
        "expected_runtime_closure_hash",
    }:
        raise GovernanceError("expected runtime closure field set differs")
    if (
        value.get("schema_version") != "aqua-fe-matched-birth-r4-g0-expected-runtime-closure-v1"
        or value.get("status") != "CAPTURED_BY_ONE_SEALED_REPRESENTATIVE_CHILD"
        or value.get("claim_scope") != "EXPECTED_BASELINE_ONLY;ACTUAL_ROLE_CLOSURE_IS_RECEIPTED_SEPARATELY"
        or value.get("expected_runtime_closure_hash") != p07gov.canonical_json_hash(
            value, "expected_runtime_closure_hash"
        )
    ):
        raise GovernanceError("expected runtime closure authority differs")
    receipt = value.get("runtime_receipt")
    bootstrap.validate_freeze_runtime_static(receipt)
    process = value.get("probe_process")
    expected_process_keys = {
        "pid", "process_started_before_wait", "attempt_count",
        "process_start_count", "no_retry", "timeout_seconds", "timed_out",
        "return_code", "termination_signal", "classification",
        "authorized_canonical_argv", "actual_procfd_argv",
        "actual_procfd_aliases", "actual_procfd_binding_records",
        "pass_fd_locators", "pass_fd_numbers",
        "environment_sha256", "spawn_signal_guard", "stdout", "stderr",
    }
    if not isinstance(process, Mapping) or set(process) != expected_process_keys:
        raise GovernanceError("runtime probe process receipt is malformed")
    for key, expected in (
        ("process_started_before_wait", True),
        ("attempt_count", 1),
        ("process_start_count", 1),
        ("no_retry", True),
        ("timeout_seconds", RUNTIME_PROBE_TIMEOUT_SECONDS),
        ("timed_out", False),
        ("return_code", 0),
        ("termination_signal", None),
        ("classification", "EXITED_RC0"),
    ):
        if process.get(key) != expected:
            raise GovernanceError(f"runtime probe process {key} differs")
    if not isinstance(process.get("pid"), int) or int(process["pid"]) <= 0:
        raise GovernanceError("runtime probe PID differs")
    _validate_spawn_signal_guard(
        process.get("spawn_signal_guard"), process_started=True, success=True
    )
    canonical_argv = [
        os.fspath(PYTHON), "-I", "-B", os.fspath(BOOTSTRAP),
        bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
    ]
    expected_probe_source = {
        "python": _external_record(PYTHON, "runtime-probe Python"),
        "bootstrap": _workspace_record(BOOTSTRAP, "runtime-probe bootstrap"),
        "wrapper": _workspace_record(WRAPPER, "runtime-probe wrapper"),
        "base": _workspace_record(BASE, "runtime-probe base"),
        "core": _workspace_record(CORE, "runtime-probe core"),
        "reference_bag": _workspace_record(RAW_BAG, "runtime-probe reference bag"),
    }
    intent = _validate_probe_launch_intent(
        value.get("probe_launch_intent"),
        canonical_argv=canonical_argv,
        source_records=expected_probe_source,
    )
    intent_record = value.get("probe_launch_intent_record")
    if (
        not isinstance(intent_record, Mapping)
        or dict(intent_record) != _workspace_record(PROBE_INTENT, "runtime probe launch intent")
    ):
        raise GovernanceError("runtime probe launch intent live record differs")
    actual_argv = process.get("actual_procfd_argv")
    if process.get("authorized_canonical_argv") != canonical_argv:
        raise GovernanceError("runtime probe canonical argv differs")
    if (
        not isinstance(actual_argv, list)
        or len(actual_argv) != len(canonical_argv)
        or actual_argv[1:3] != ["-I", "-B"]
        or actual_argv[4] != bootstrap.PROBE_ARGUMENT
        or actual_argv[6] != REFERENCE_TOPIC
        or any(
            re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", str(actual_argv[index])) is None
            for index in (0, 3, 5)
        )
    ):
        raise GovernanceError("runtime probe actual procfd argv differs")
    aliases = process.get("actual_procfd_aliases")
    expected_alias_keys = {
        os.fspath(PYTHON), os.fspath(BOOTSTRAP), os.fspath(RAW_BAG),
        "${EPOCH_WRAPPER_PROCFD}", "${EVALUATOR_BASE_PROCFD}",
        "${TRAJECTORY_CORE_PROCFD}",
    }
    if (
        not isinstance(aliases, Mapping)
        or set(aliases) != expected_alias_keys
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", item) is None
            for item in aliases.values()
        )
        or _materialize_strings(canonical_argv, aliases) != actual_argv
        or process.get("pass_fd_locators") != sorted(set(aliases.values()))
        or process.get("pass_fd_numbers") != sorted(
            int(str(locator).rsplit("/", 1)[1]) for locator in aliases.values()
        )
    ):
        raise GovernanceError("runtime probe procfd alias/pass-fd closure differs")
    p07gov.require_hash(process.get("environment_sha256"), "runtime probe environment")
    for stream in ("stdout", "stderr"):
        stream_record = process.get(stream)
        if not isinstance(stream_record, Mapping) or set(stream_record) != {"sha256", "size_bytes"}:
            raise GovernanceError(f"runtime probe {stream} receipt differs")
        p07gov.require_hash(stream_record.get("sha256"), f"runtime probe {stream}")
        if not isinstance(stream_record.get("size_bytes"), int) or stream_record["size_bytes"] < 0:
            raise GovernanceError(f"runtime probe {stream} size differs")
    encoded = bootstrap.canonical_json_bytes(receipt)
    if process.get("stdout") != _stream_receipt(encoded):
        raise GovernanceError("runtime probe stdout binding differs")
    if process.get("stderr") != _stream_receipt(b""):
        raise GovernanceError("runtime probe emitted stderr")
    execution = receipt.get("execution") if isinstance(receipt, Mapping) else None
    if (
        not isinstance(execution, Mapping)
        or set(execution) != {
            "sys_argv", "process_argv", "environment", "target_signal_mask"
        }
        or execution.get("process_argv") != actual_argv
        or execution.get("sys_argv") != actual_argv[3:]
    ):
        raise GovernanceError("runtime probe process/runtime argv binding differs")
    runtime_environment = execution.get("environment")
    sealed_sources = receipt.get("sealed_sources") if isinstance(receipt, Mapping) else None
    if not isinstance(runtime_environment, Mapping) or not isinstance(sealed_sources, Mapping):
        raise GovernanceError("runtime probe execution/sealed source binding is malformed")
    locators = {
        name: record.get("locator") if isinstance(record, Mapping) else None
        for name, record in sealed_sources.items()
    }
    expected_locators = {
        "python_interpreter": actual_argv[0],
        "bootstrap": actual_argv[3],
    }
    for name, expected_locator in expected_locators.items():
        if locators.get(name) != expected_locator:
            raise GovernanceError(f"runtime probe sealed locator differs: {name}")
    probe_mapping = {
        "${EPOCH_WRAPPER_PROCFD}": str(locators.get("wrapper")),
        "${EVALUATOR_BASE_PROCFD}": str(locators.get("evaluator_base")),
        "${TRAJECTORY_CORE_PROCFD}": str(locators.get("evaluator_core")),
        "${ROLE_OUTPUT_DIRFD}": "${PROBE_NO_OUTPUT}",
    }
    expected_environment = _materialize_environment(
        _environment_template("primary"), probe_mapping
    )
    expected_environment[bootstrap.ROLE_ENV] = "runtime_probe"
    expected_environment.pop(bootstrap.OUTPUT_ENV, None)
    if dict(runtime_environment) != expected_environment:
        raise GovernanceError("runtime probe exact environment differs")
    if hashlib.sha256(_canonical_json_bytes(dict(runtime_environment))).hexdigest() != process.get(
        "environment_sha256"
    ):
        raise GovernanceError("runtime probe environment hash binding differs")
    if (
        intent.get("actual_procfd_argv") != actual_argv
        or intent.get("actual_environment") != runtime_environment
        or intent.get("actual_environment_sha256") != process.get("environment_sha256")
        or intent.get("pass_fd_numbers") != process.get("pass_fd_numbers")
    ):
        raise GovernanceError("runtime probe process differs from durable launch intent")
    if value.get("probe_source") != expected_probe_source:
        raise GovernanceError("runtime probe source closure differs")
    binding_roles = {
        os.fspath(PYTHON): "python",
        os.fspath(BOOTSTRAP): "bootstrap",
        os.fspath(RAW_BAG): "reference_bag",
        "${EPOCH_WRAPPER_PROCFD}": "wrapper",
        "${EVALUATOR_BASE_PROCFD}": "base",
        "${TRAJECTORY_CORE_PROCFD}": "core",
    }
    expected_binding_records = {
        canonical: {
            "kind": "SEALED_PROBE_FILE" if canonical != os.fspath(RAW_BAG)
            else "HELD_REFERENCE_BAG",
            "locator": aliases[canonical],
            "record": dict(expected_probe_source[source_role]),
        }
        for canonical, source_role in binding_roles.items()
    }
    if process.get("actual_procfd_binding_records") != expected_binding_records:
        raise GovernanceError("runtime probe procfd content binding differs")
    _validate_persistent_runtime_files(receipt)
    if freeze is not None:
        expected = {
            "python_interpreter": freeze["python_interpreter"],
            "bootstrap": freeze["helper_code_closure"]["child_bootstrap"],
            "wrapper": freeze["helper_code_closure"]["epoch_wrapper"],
            "evaluator_base": freeze["helper_code_closure"]["evaluator_base"],
            "evaluator_core": freeze["helper_code_closure"]["trajectory_core"],
        }
        observed = _sealed_content_identity(receipt)
        for role, record in expected.items():
            if observed[role]["sha256"] != record["sha256"] or observed[role]["size_bytes"] != record["size_bytes"]:
                raise GovernanceError(f"runtime probe sealed source differs: {role}")


def build_freeze(runtime_closure: Mapping[str, Any]) -> dict[str, Any]:
    _static_authority_check()
    helper_records = {role: _workspace_record(path, f"helper {role}") for role, path in HELPERS.items()}
    input_records = {role: _workspace_record(path, f"input {role}") for role, path in INPUTS.items()}
    python_record = _external_record(PYTHON, "python interpreter")
    vins_runtime_records = _vins_external_runtime_records()
    authority = _contract_authority(
        input_records, helper_records, python_record, vins_runtime_records
    )
    staging, intent_path, closeout_path = publication_paths(authority["job_hash"])
    payload: dict[str, Any] = {
        "schema_version": FREEZE_SCHEMA,
        "status": FREEZE_STATUS,
        "scientific_role": "POST_RESULT_EXPLORATORY_MATCHED_DETECTOR_BIRTH_SOURCE_CONTROL",
        "outcome_boundary": dict(OUTCOME_BOUNDARY),
        "protocol": _protocol(),
        "formal900_carrier": {
            "raw_frames": 1800,
            "published_frames": 900,
            "raw_reference_rows": 91,
            "raw_reference_first_ns": WINDOW_START_NS,
            "raw_reference_last_ns": WINDOW_END_NS,
            "legacy_46_row_proxy_used": False,
        },
        "input_records": input_records,
        "helper_code_closure": helper_records,
        "python_interpreter": python_record,
        "vins_external_runtime": vins_runtime_records,
        "expected_runtime_closure": dict(runtime_closure),
        "runtime_claim_scope": "FREEZE_PROBE_IS_EXPECTED_CLOSURE;EACH_ROLE_WRITES_ACTUAL_RUNTIME_RECEIPT",
        "execution_contract": {
            "role_order": list(ROLE_NAMES),
            "process_start_count_by_role": {role: 1 for role in ROLE_NAMES},
            "attempt_count_by_role": {role: 1 for role in ROLE_NAMES},
            "no_retry": True,
            "fixed_timeout_seconds": PROCESS_TIMEOUT_SECONDS,
            "stdout_stderr_receipt": "SHA256_AND_SIZE_ONLY",
            "post_process_start_count": 0,
            "detector_or_vins_process_start_count": 0,
            "evo_process_start_count": 0,
            "same_scientific_and_code_leases_for_both_roles": True,
            "role_dirfds_held_through_three_outputs_comparison_and_result_seal": True,
            "birth_atomic": False,
            "active_same_uid_race_out_of_scope": True,
            "atomic_publication": "renameat2(RENAME_NOREPLACE)",
        },
        "authorized_role_argv": {role: canonical_role_argv(role) for role in ROLE_NAMES},
        "authorized_environment_templates": {role: _environment_template(role) for role in ROLE_NAMES},
        "publication_authority": authority,
        "publication_technical_boundary": PUBLICATION_TECHNICAL_BOUNDARY,
        "reserved_paths": {
            "destination": os.fspath(OUTPUT),
            "staging": os.fspath(staging),
            "intent": os.fspath(intent_path),
            "closeout": os.fspath(closeout_path),
            "post": os.fspath(POST),
            "probe_intent": os.fspath(PROBE_INTENT),
            "probe_failure": os.fspath(PROBE_FAILURE),
        },
        "freeze_hash": "0" * 64,
    }
    payload["freeze_hash"] = _self_hash(payload, "freeze_hash")
    return payload


def _validate_record(record: Mapping[str, Any], path: Path, label: str) -> None:
    observed = _workspace_record(path, label)
    if dict(record) != observed:
        raise GovernanceError(f"{label} live record differs")


def validate_freeze_static(*, require_fresh_outputs: bool) -> dict[str, Any]:
    _static_authority_check()
    freeze = _load_json_static(FREEZE, "G0 freeze")
    expected_keys = {
        "schema_version", "status", "scientific_role", "outcome_boundary",
        "protocol", "formal900_carrier", "input_records",
        "helper_code_closure", "python_interpreter", "vins_external_runtime",
        "expected_runtime_closure",
        "runtime_claim_scope", "execution_contract", "authorized_role_argv",
        "authorized_environment_templates", "publication_authority",
        "publication_technical_boundary", "reserved_paths", "freeze_hash",
    }
    if set(freeze) != expected_keys:
        raise GovernanceError("G0 freeze top-level key set differs")
    if freeze.get("schema_version") != FREEZE_SCHEMA or freeze.get("status") != FREEZE_STATUS:
        raise GovernanceError("G0 freeze schema/status differs")
    p07gov.validate_self_hash(freeze, "freeze_hash", label="G0 freeze")
    if freeze.get("outcome_boundary") != OUTCOME_BOUNDARY:
        raise GovernanceError("G0 freeze outcome boundary differs")
    if freeze.get("protocol") != _protocol():
        raise GovernanceError("G0 freeze protocol differs")
    if freeze.get("scientific_role") != "POST_RESULT_EXPLORATORY_MATCHED_DETECTOR_BIRTH_SOURCE_CONTROL":
        raise GovernanceError("G0 freeze scientific role differs")
    if freeze.get("runtime_claim_scope") != "FREEZE_PROBE_IS_EXPECTED_CLOSURE;EACH_ROLE_WRITES_ACTUAL_RUNTIME_RECEIPT":
        raise GovernanceError("G0 freeze runtime claim scope differs")
    expected_carrier = {
        "raw_frames": 1800,
        "published_frames": 900,
        "raw_reference_rows": 91,
        "raw_reference_first_ns": WINDOW_START_NS,
        "raw_reference_last_ns": WINDOW_END_NS,
        "legacy_46_row_proxy_used": False,
    }
    if freeze.get("formal900_carrier") != expected_carrier:
        raise GovernanceError("G0 freeze formal900 carrier differs")
    expected_execution = {
        "role_order": list(ROLE_NAMES),
        "process_start_count_by_role": {role: 1 for role in ROLE_NAMES},
        "attempt_count_by_role": {role: 1 for role in ROLE_NAMES},
        "no_retry": True,
        "fixed_timeout_seconds": PROCESS_TIMEOUT_SECONDS,
        "stdout_stderr_receipt": "SHA256_AND_SIZE_ONLY",
        "post_process_start_count": 0,
        "detector_or_vins_process_start_count": 0,
        "evo_process_start_count": 0,
        "same_scientific_and_code_leases_for_both_roles": True,
        "role_dirfds_held_through_three_outputs_comparison_and_result_seal": True,
        "birth_atomic": False,
        "active_same_uid_race_out_of_scope": True,
        "atomic_publication": "renameat2(RENAME_NOREPLACE)",
    }
    if freeze.get("execution_contract") != expected_execution:
        raise GovernanceError("G0 freeze execution contract differs")
    if freeze.get("authorized_role_argv") != {role: canonical_role_argv(role) for role in ROLE_NAMES}:
        raise GovernanceError("G0 freeze authorized argv differs")
    if freeze.get("authorized_environment_templates") != {role: _environment_template(role) for role in ROLE_NAMES}:
        raise GovernanceError("G0 freeze environment template differs")
    input_records = freeze.get("input_records")
    helper_records = freeze.get("helper_code_closure")
    if not isinstance(input_records, Mapping) or set(input_records) != set(INPUTS):
        raise GovernanceError("G0 input-record closure differs")
    if not isinstance(helper_records, Mapping) or set(helper_records) != set(HELPERS):
        raise GovernanceError("G0 helper-code closure differs")
    if not isinstance(freeze.get("python_interpreter"), Mapping):
        raise GovernanceError("Python interpreter binding is malformed")
    if freeze.get("vins_external_runtime") != _vins_external_runtime_records():
        raise GovernanceError("frozen VINS external runtime differs")
    expected_publication = _contract_authority(
        input_records,
        helper_records,
        freeze["python_interpreter"],
        freeze["vins_external_runtime"],
    )
    if freeze.get("publication_authority") != expected_publication:
        raise GovernanceError("G0 publication authority differs")
    if freeze.get("publication_technical_boundary") != PUBLICATION_TECHNICAL_BOUNDARY:
        raise GovernanceError("G0 publication technical boundary differs")
    staging, intent_path, closeout_path = publication_paths(expected_publication["job_hash"])
    expected_reserved = {
        "destination": os.fspath(OUTPUT),
        "staging": os.fspath(staging),
        "intent": os.fspath(intent_path),
        "closeout": os.fspath(closeout_path),
        "post": os.fspath(POST),
        "probe_intent": os.fspath(PROBE_INTENT),
        "probe_failure": os.fspath(PROBE_FAILURE),
    }
    if freeze.get("reserved_paths") != expected_reserved:
        raise GovernanceError("G0 reserved path authority differs")
    if os.path.lexists(PROBE_FAILURE):
        raise GovernanceError("runtime probe failure namespace contradicts successful freeze")
    for role, path in INPUTS.items():
        if not isinstance(input_records[role], Mapping):
            raise GovernanceError(f"input record malformed: {role}")
        _validate_record(input_records[role], path, f"input {role}")
    for role, path in HELPERS.items():
        if not isinstance(helper_records[role], Mapping):
            raise GovernanceError(f"helper record malformed: {role}")
        _validate_record(helper_records[role], path, f"helper {role}")
    if freeze.get("python_interpreter") != _external_record(PYTHON, "python interpreter"):
        raise GovernanceError("Python interpreter binding differs")
    _validate_freeze_runtime_static(freeze.get("expected_runtime_closure"), freeze)
    if require_fresh_outputs:
        reserved = freeze.get("reserved_paths")
        if not isinstance(reserved, Mapping):
            raise GovernanceError("reserved path binding malformed")
        for label, raw in reserved.items():
            path = Path(str(raw))
            if label == "post" or label in {"destination", "staging", "intent", "closeout"}:
                if os.path.lexists(path):
                    raise GovernanceError(f"reserved namespace already contains evidence: {label}")
    return freeze


def _build_intent(freeze: Mapping[str, Any]) -> dict[str, Any]:
    authority = freeze["publication_authority"]
    assert isinstance(authority, Mapping)
    with _post_result_publication_semantics():
        return publisher.build_publication_intent(
            root=ROOT,
            job_id=str(authority["job_id"]),
            job_hash=str(authority["job_hash"]),
            plan_hash=str(authority["plan_hash"]),
            evaluation_lock_hash=str(authority["evaluation_lock_hash"]),
            backend_execution_lock_hash=str(authority["backend_execution_lock_hash"]),
            g0_execution_authority_hash=str(freeze["freeze_hash"]),
            evaluation_disposition=str(authority["evaluation_disposition"]),
            output_dir=OUTPUT,
        )


def _load_exact_intent(freeze: Mapping[str, Any]) -> dict[str, Any]:
    authority = freeze["publication_authority"]
    _staging, path, _closeout = publication_paths(str(authority["job_hash"]))
    observed = publisher.read_json_direct_rooted(ROOT, path, label="publication intent")
    with _post_result_publication_semantics():
        publisher.validate_publication_intent(observed, root=ROOT)
    if not _typed_tree_equal(observed, _build_intent(freeze)):
        raise GovernanceError("publication intent differs from freeze")
    return observed


@contextmanager
def _held_exact_json_authority(
    path: Path, expected: Mapping[str, Any], *, label: str
):
    """Hold one canonical JSON inode whose exact object is already trusted."""

    content = publisher.read_bytes_bound_input_rooted(ROOT, path, label=label)
    observed = p07gov._json_object_bytes(content, label=label)
    if not _typed_tree_equal(observed, dict(expected)):
        raise GovernanceError(f"{label} bytes differ from initial validated object")
    with publisher.retained_bound_input_validator(
        ROOT, path, content, label=label
    ) as validator:
        validator()
        yield validator
        validator()


def _sealed_execution_inputs(stack: ExitStack, freeze: Mapping[str, Any]) -> tuple[dict[str, str], list[int], backend.SealedFileLease]:
    proc: dict[str, str] = {}
    fds: list[int] = []
    for role in EXECUTION_INPUT_KEYS:
        path, descriptor = stack.enter_context(
            p07runner.sealed_bound_input(ROOT, freeze["input_records"][role], label=f"scientific input {role}")
        )
        proc[role] = path
        fds.append(descriptor)
    for role in ("child_bootstrap", "epoch_wrapper", "evaluator_base", "trajectory_core"):
        path, descriptor = stack.enter_context(
            p07runner.sealed_bound_input(ROOT, freeze["helper_code_closure"][role], label=f"runtime code {role}")
        )
        proc[role] = path
        fds.append(descriptor)
    py = freeze["python_interpreter"]
    lease = backend.SealedFileLease(
        PYTHON,
        str(py["sha256"]),
        role="python_interpreter",
        label="frozen G0 Python interpreter",
        expected_size_bytes=int(py["size_bytes"]),
    )
    try:
        stack.enter_context(lease)
    except backend.BackendReplayViolation as error:
        raise GovernanceError(f"cannot acquire Python lease: {error}") from error
    if lease.fd is None:
        raise GovernanceError("Python lease has no descriptor")
    fds.append(lease.fd)
    return proc, fds, lease


def _retained_workspace_record_validators(
    stack: ExitStack,
    records: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> list[Any]:
    validators: list[Any] = []
    for role in sorted(records):
        record = records[role]
        path = Path(str(record["path"]))
        if not path.is_absolute():
            path = ROOT / path
        content = publisher.read_bytes_bound_input_rooted(
            ROOT, path, label=f"{label} {role} retained bytes"
        )
        if _stream_receipt(content) != {
            "sha256": record["sha256"], "size_bytes": record["size_bytes"]
        }:
            raise GovernanceError(f"{label} {role} retained record differs")
        validator = stack.enter_context(
            publisher.retained_bound_input_validator(
                ROOT, path, content, label=f"{label} {role}"
            )
        )
        validators.append(validator)
    return validators


def _retained_external_record_validators(
    stack: ExitStack,
    records: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> list[backend.SealedFileLease]:
    leases: list[backend.SealedFileLease] = []
    for role in sorted(records):
        record = records[role]
        lease = backend.SealedFileLease(
            Path(str(record["path"])),
            str(record["sha256"]),
            role=f"g0_{label}_{role}",
            label=f"{label} {role}",
            expected_size_bytes=int(record["size_bytes"]),
        )
        stack.enter_context(lease)
        leases.append(lease)
    return leases


def _validate_retained_authority(
    workspace_validators: Sequence[Any],
    external_leases: Sequence[backend.SealedFileLease],
) -> None:
    for validator in workspace_validators:
        validator()
    for lease in external_leases:
        lease.verify_unchanged()


def _actual_role_contract(
    role: str,
    proc: Mapping[str, str],
    python_lease: backend.SealedFileLease,
    role_fd: int,
) -> tuple[list[str], dict[str, str], dict[str, str]]:
    mapping = {
        os.fspath(PYTHON): python_lease.proc_path,
        os.fspath(BOOTSTRAP): proc["child_bootstrap"],
        os.fspath(RAW_BAG): proc["reference_bag"],
        os.fspath(CONFIG): proc["config"],
        os.fspath(GFTT_VIO): proc["gftt_vio"],
        os.fspath(XFEAT_VIO): proc["xfeat_vio"],
        os.fspath(OUTPUT / role): f"/proc/self/fd/{role_fd}",
        "${EPOCH_WRAPPER_PROCFD}": proc["epoch_wrapper"],
        "${EVALUATOR_BASE_PROCFD}": proc["evaluator_base"],
        "${TRAJECTORY_CORE_PROCFD}": proc["trajectory_core"],
        "${ROLE_OUTPUT_DIRFD}": f"/proc/self/fd/{role_fd}",
    }
    canonical = canonical_role_argv(role)
    actual = _materialize_strings(canonical, mapping)
    environment = _materialize_environment(_environment_template(role), mapping)
    if actual[0] != python_lease.proc_path or actual[1:3] != ["-I", "-B"] or actual[3] != proc["child_bootstrap"]:
        raise GovernanceError("actual role argv prefix is not sealed Python -I -B bootstrap")
    if "/home/ma/.local" in environment.get("PATH", ""):
        raise GovernanceError("user-local PATH is forbidden")
    return actual, environment, mapping


def _stream_receipt(content: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}


def _procfd_binding_records(
    role: str,
    aliases: Mapping[str, str],
    freeze: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    file_records = {
        os.fspath(PYTHON): freeze["python_interpreter"],
        os.fspath(BOOTSTRAP): freeze["helper_code_closure"]["child_bootstrap"],
        os.fspath(RAW_BAG): freeze["input_records"]["reference_bag"],
        os.fspath(CONFIG): freeze["input_records"]["config"],
        os.fspath(GFTT_VIO): freeze["input_records"]["gftt_vio"],
        os.fspath(XFEAT_VIO): freeze["input_records"]["xfeat_vio"],
        "${EPOCH_WRAPPER_PROCFD}": freeze["helper_code_closure"]["epoch_wrapper"],
        "${EVALUATOR_BASE_PROCFD}": freeze["helper_code_closure"]["evaluator_base"],
        "${TRAJECTORY_CORE_PROCFD}": freeze["helper_code_closure"]["trajectory_core"],
    }
    if set(aliases) != set(file_records) | {
        os.fspath(OUTPUT / role), "${ROLE_OUTPUT_DIRFD}"
    }:
        raise GovernanceError(f"{role} procfd alias closure differs")
    result = {
        canonical: {
            "kind": "SEALED_REGULAR_FILE",
            "locator": aliases[canonical],
            "record": dict(record),
        }
        for canonical, record in file_records.items()
    }
    role_directory = {
        "kind": "RETAINED_ROLE_OUTPUT_DIRECTORY",
        "locator": aliases["${ROLE_OUTPUT_DIRFD}"],
        "role": role,
        "canonical_path": os.fspath(OUTPUT / role),
    }
    result[os.fspath(OUTPUT / role)] = dict(role_directory)
    result["${ROLE_OUTPUT_DIRFD}"] = dict(role_directory)
    return result


def _procfd_numbers(aliases: Mapping[str, str], *, label: str) -> list[int]:
    numbers: set[int] = set()
    for locator in aliases.values():
        match = re.fullmatch(r"/proc/self/fd/([1-9][0-9]*)", str(locator))
        if match is None:
            raise GovernanceError(f"{label} contains a non-procfd locator")
        numbers.add(int(match.group(1)))
    return sorted(numbers)


def _launch_role(
    role: str,
    argv: Sequence[str],
    environment: Mapping[str, str],
    pass_fds: Sequence[int],
    freeze: Mapping[str, Any],
    procfd_aliases: Mapping[str, str],
    launch_intent_hash: str,
) -> dict[str, Any]:
    if role not in ROLE_NAMES:
        raise GovernanceError("process role differs")
    canonical = freeze["authorized_role_argv"][role]
    if list(argv) != _materialize_strings(canonical, procfd_aliases):
        raise GovernanceError(f"{role} process argv differs before Popen")
    expected_environment = _materialize_environment(
        freeze["authorized_environment_templates"][role], procfd_aliases
    )
    if dict(environment) != expected_environment:
        raise GovernanceError(f"{role} process environment differs before Popen")
    p07gov.require_hash(launch_intent_hash, f"{role} launch intent")
    expected_pass_fds = _procfd_numbers(
        procfd_aliases, label=f"{role} process aliases"
    )
    if sorted(set(pass_fds)) != expected_pass_fds or len(pass_fds) != len(
        set(pass_fds)
    ):
        raise GovernanceError(f"{role} process pass_fds differ from exact procfd closure")
    process: subprocess.Popen[bytes] | None = None
    pid: int | None = None
    process_started = False
    wait_error: BaseException | None = None
    cleanup_errors: list[dict[str, str]] = []
    stdout = b""
    stderr = b""
    timed_out = False
    spawn_window_error = False
    spawn_signal_guard: dict[str, Any]
    guard = _SpawnSignalGuard()
    spawn_stage = "SPAWN"
    try:
        process, pid = guard.spawn(
            argv,
            cwd=ROOT,
            env=dict(environment),
            pass_fds=tuple(expected_pass_fds),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        process_started = True
        spawn_stage = "WAIT"
        stdout, stderr = process.communicate(timeout=PROCESS_TIMEOUT_SECONDS)
        guard.begin_cleanup()
    except subprocess.TimeoutExpired as error:
        guard.begin_cleanup()
        process = guard.process
        pid = guard.pid
        process_started = process is not None
        timed_out = True
        wait_error = error
    except BaseException as error:
        guard.begin_cleanup()
        process = guard.process
        pid = guard.pid
        wait_error = error
        process_started = process is not None
        spawn_window_error = process_started and spawn_stage == "SPAWN"
    if guard.received and wait_error is None:
        wait_error = _SpawnTerminationSignal(guard.received[0])
    if process is not None and wait_error is not None:
        partial_stdout = getattr(wait_error, "output", None)
        partial_stderr = getattr(wait_error, "stderr", None)
        if isinstance(partial_stdout, bytes):
            stdout = partial_stdout
        if isinstance(partial_stderr, bytes):
            stderr = partial_stderr
        guard.begin_cleanup()
        stdout, stderr, return_code, cleanup_errors, _child_reaped = _cleanup_probe_child(
            process, pid, wait_error, stdout, stderr
        )
    else:
        return_code = process.returncode if process is not None else None
    if process_started and return_code is None:
        cleanup_errors.append({
            "class": "UNREAPED_CHILD",
            "message": "child return code absent after mandatory cleanup",
        })
    child_reaped = not process_started or return_code is not None
    spawn_signal_guard = guard.finish(child_reaped=child_reaped)
    if spawn_signal_guard["received_signals"] and wait_error is None:
        wait_error = _SpawnTerminationSignal(
            str(spawn_signal_guard["received_signals"][0])
        )
    termination_signal = (
        -return_code if isinstance(return_code, int) and return_code < 0 else None
    )
    classification = (
        "PROCESS_START_ERROR" if not process_started else
        "SPAWN_WINDOW_ERROR_TERMINATED" if spawn_window_error else
        "TIMEOUT_TERMINATED" if timed_out else
        "WAIT_ERROR_TERMINATED" if wait_error is not None else
        "TERMINATED_BY_SIGNAL" if termination_signal is not None else
        "EXITED_RC0" if return_code == 0 else
        "EXITED_NONZERO"
    )
    receipt: dict[str, Any] = {
        "schema_version": PROCESS_SCHEMA,
        "status": "COMPLETED_RC0" if classification == "EXITED_RC0" else "PROCESS_FAILURE_EVIDENCE",
        "role": role,
        "pid": pid,
        "process_started_before_wait": process_started,
        "attempt_count": 1,
        "process_start_count": 1 if process_started else 0,
        "no_retry": True,
        "timeout_seconds": PROCESS_TIMEOUT_SECONDS,
        "timed_out": timed_out,
        "return_code": return_code,
        "termination_signal": termination_signal,
        "classification": classification,
        "wait_error": _exception_identity(wait_error) if wait_error is not None else None,
        "cleanup_errors": cleanup_errors,
        "child_reaped": not process_started or return_code is not None,
        "spawn_signal_guard": spawn_signal_guard,
        "stdout": _stream_receipt(stdout),
        "stderr": _stream_receipt(stderr),
        "authorized_canonical_argv": list(freeze["authorized_role_argv"][role]),
        "actual_procfd_argv": list(argv),
        "actual_procfd_aliases": dict(procfd_aliases),
        "actual_procfd_binding_records": _procfd_binding_records(
            role, procfd_aliases, freeze
        ),
        "pass_fd_numbers": expected_pass_fds,
        "authorized_environment_template": dict(freeze["authorized_environment_templates"][role]),
        "actual_environment_sha256": hashlib.sha256(_canonical_json_bytes(dict(environment))).hexdigest(),
        "freeze_hash": freeze["freeze_hash"],
        "launch_intent_hash": launch_intent_hash,
    }
    receipt["process_receipt_hash"] = p07gov.canonical_json_hash(receipt)
    return receipt


def _exception_identity(error: BaseException) -> dict[str, str]:
    return {
        "class": f"{type(error).__module__}.{type(error).__qualname__}",
        "message": str(error)[:2000],
    }


def _write_failed_process_receipt(
    stack: ExitStack, staging_fd: int, role: str, receipt: Mapping[str, Any]
) -> None:
    if (
        role not in ROLE_NAMES
        or receipt.get("role") != role
        or receipt.get("status") != "PROCESS_FAILURE_EVIDENCE"
        or receipt.get("classification") == "EXITED_RC0"
        or receipt.get("attempt_count") != 1
        or receipt.get("no_retry") is not True
        or receipt.get("child_reaped") is not True
    ):
        raise GovernanceError(f"{role} failed process evidence is not terminal/reaped")
    p07gov.validate_self_hash(
        receipt, "process_receipt_hash", label=f"{role} failed process receipt"
    )
    _validate_spawn_signal_guard(
        receipt.get("spawn_signal_guard"),
        process_started=receipt.get("process_start_count") == 1,
        success=False,
    )
    validator, _record = stack.enter_context(
        _write_held_canonical_json_at(
            staging_fd,
            f"{role}_failed_process_receipt.json",
            receipt,
            label=f"{role} failed process receipt",
        )
    )
    validator()


def _launch_intent(
    role: str,
    argv: Sequence[str],
    environment: Mapping[str, str],
    procfd_aliases: Mapping[str, str],
    freeze: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": LAUNCH_SCHEMA,
        "status": "DURABLE_PROCESS_LAUNCH_PENDING_NO_RETRY",
        "role": role,
        "attempt_count": 1,
        "authorized_process_start_count": 1,
        "no_retry_after_pending_evidence": True,
        "timeout_seconds": PROCESS_TIMEOUT_SECONDS,
        "freeze_hash": freeze["freeze_hash"],
        "authorized_canonical_argv": list(freeze["authorized_role_argv"][role]),
        "actual_procfd_argv": list(argv),
        "actual_procfd_aliases": dict(procfd_aliases),
        "actual_procfd_binding_records": _procfd_binding_records(
            role, procfd_aliases, freeze
        ),
        "pass_fd_numbers": _procfd_numbers(
            procfd_aliases, label=f"{role} launch aliases"
        ),
        "spawn_signal_policy": _spawn_signal_policy(),
        "authorized_environment_template": dict(
            freeze["authorized_environment_templates"][role]
        ),
        "actual_environment_sha256": hashlib.sha256(
            _canonical_json_bytes(dict(environment))
        ).hexdigest(),
        "launch_intent_hash": "0" * 64,
    }
    payload["launch_intent_hash"] = p07gov.canonical_json_hash(
        payload, "launch_intent_hash"
    )
    return payload


def _read_direct_at(directory_fd: int, name: str, label: str) -> bytes:
    if not name or "/" in name or name in {".", ".."}:
        raise GovernanceError(f"unsafe {label} name")
    flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(name, flags, dir_fd=directory_fd)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise GovernanceError(f"{label} is not a direct single-link file")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        reachable = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink")
        if any(getattr(before, key) != getattr(after, key) or getattr(before, key) != getattr(reachable, key) for key in fields):
            raise GovernanceError(f"{label} changed during retained read")
        if len(content) != before.st_size:
            raise GovernanceError(f"{label} short read")
        return content
    finally:
        os.close(descriptor)


def _role_payload(role_fd: int, role: str) -> dict[str, bytes]:
    names = sorted(os.listdir(role_fd))
    if names != sorted(ROLE_FILES):
        raise GovernanceError(f"{role} output closure differs: {names}")
    return {name: _read_direct_at(role_fd, name, f"{role} {name}") for name in ROLE_FILES}


_PROCFD_REFERENCE_RE = re.compile(r"(?P<fd>/proc/self/fd/[1-9][0-9]*):(?P<topic>/aqualoc/colmap_gt)\Z")


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant: {value}")


def _typed_tree_equal(observed: Any, expected: Any) -> bool:
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(observed) == set(expected) and all(
            _typed_tree_equal(observed[key], value) for key, value in expected.items()
        )
    if isinstance(expected, list):
        return len(observed) == len(expected) and all(
            _typed_tree_equal(left, right) for left, right in zip(observed, expected)
        )
    return observed == expected


def _require_exact_keys(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise GovernanceError(f"{label} key set differs")
    return value


def _require_int(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise GovernanceError(f"{label} is not an exact nonnegative integer")
    return value


def _require_float(value: Any, label: str, *, minimum: float = 0.0) -> float:
    if type(value) is not float or not math.isfinite(value) or value < minimum:
        raise GovernanceError(f"{label} is not an exact finite float")
    return value


def _validate_sample_audit(value: Any, label: str, *, reference: bool) -> None:
    audit = _require_exact_keys(
        value,
        {"raw_count", "finite_count", "unique_count", "duplicate_count", "rejected_nonfinite_count"},
        f"{label} audit",
    )
    counts = {key: _require_int(audit[key], f"{label} audit {key}") for key in audit}
    if counts["finite_count"] + counts["rejected_nonfinite_count"] != counts["raw_count"]:
        raise GovernanceError(f"{label} audit finite/raw relation differs")
    if counts["unique_count"] + counts["duplicate_count"] != counts["finite_count"]:
        raise GovernanceError(f"{label} audit unique/duplicate relation differs")
    if reference and counts != {
        "raw_count": 91,
        "finite_count": 91,
        "unique_count": 91,
        "duplicate_count": 0,
        "rejected_nonfinite_count": 0,
    }:
        raise GovernanceError("summary reference audit does not bind 91-row authority")


def _validate_rejection_histogram(
    value: Any, label: str, *, valid_grid_count: int
) -> None:
    if not isinstance(value, Mapping) or not value:
        raise GovernanceError(f"{label} rejection histogram is malformed")
    allowed = {"NO_SAMPLES", "OUT_OF_RANGE", "EXACT", "GAP_EXCEEDED", "INTERPOLATED"}
    if not set(value).issubset(allowed):
        raise GovernanceError(f"{label} rejection histogram has an unknown reason")
    counts = {
        reason: _require_int(count, f"{label} rejection count {reason}")
        for reason, count in value.items()
    }
    if sum(counts.values()) != EXPECTED_GRID_COUNT:
        raise GovernanceError(f"{label} rejection histogram does not cover the exact grid")
    if counts.get("EXACT", 0) + counts.get("INTERPOLATED", 0) != valid_grid_count:
        raise GovernanceError(
            f"{label} rejection histogram valid reasons differ from valid_grid_count"
        )


def _binary80_parse_decimal(text: str) -> Decimal:
    """Model NumPy/x87 ``longdouble(str)`` for the frozen positive epochs.

    The evaluator parses these epoch strings into the platform's 64-bit
    significand binary80 type before doing grid/duration arithmetic.  Rounding
    the exact decimal to its magnitude-dependent binary80 quantum reproduces
    that path without first collapsing either endpoint to binary64.
    """

    try:
        exact = Decimal(text)
    except Exception as error:
        raise GovernanceError("frozen binary80 decimal is malformed") from error
    if not exact.is_finite() or exact <= 0:
        raise GovernanceError("frozen binary80 decimal is outside the positive authority")
    integral = int(exact)
    exponent = integral.bit_length() - 1
    with localcontext() as context:
        context.prec = 96
        context.rounding = ROUND_HALF_EVEN
        quantum = Decimal(2) ** (exponent - 63)
        return (exact / quantum).to_integral_value(rounding=ROUND_HALF_EVEN) * quantum


def _evaluator_window_duration_s() -> float:
    # Subtraction is exact under Sterbenz after the two binary80 parses.
    return float(
        _binary80_parse_decimal(WINDOW_END)
        - _binary80_parse_decimal(WINDOW_START)
    )


def _evaluator_grid_timestamp_text(index: int) -> str:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < EXPECTED_GRID_COUNT:
        raise GovernanceError("common-grid audit index differs")
    # Frozen evaluation rate is exactly 1 Hz, so the evaluator's binary80
    # start + arange(index)/rate path is start + the exact integer index.
    stamp = _binary80_parse_decimal(WINDOW_START) + Decimal(index)
    return format(float(stamp), ".17g")


def _evaluator_grid_span_s(first_index: int, last_index: int) -> float:
    if (
        isinstance(first_index, bool)
        or isinstance(last_index, bool)
        or not isinstance(first_index, int)
        or not isinstance(last_index, int)
        or not 0 <= first_index <= last_index < EXPECTED_GRID_COUNT
    ):
        raise GovernanceError("common-grid span indices differ")
    start = _binary80_parse_decimal(WINDOW_START)
    # Match core's binary80 stamp subtraction and delay the binary64 cast
    # until after subtraction, just as the frozen evaluator does.
    first_stamp = start + Decimal(first_index)
    last_stamp = start + Decimal(last_index)
    return float(last_stamp - first_stamp)


def _expected_summary_protocol() -> dict[str, Any]:
    return {
        "contrast_name": CONTRAST,
        "reference": f"{RAW_BAG}:{REFERENCE_TOPIC}",
        "evaluation_rate_hz": 1.0,
        "nominal_reference_rate_hz": 1.0,
        "nominal_estimate_rate_hz": 10.0,
        "window_start_s": float(_binary80_parse_decimal(WINDOW_START)),
        "window_end_s": float(_binary80_parse_decimal(WINDOW_END)),
        "max_reference_gap_s": 2.5,
        "max_estimate_gap_s": 0.25,
        "rpe_delta_s": 1.0,
        "body_to_camera_applied": True,
        "rpe_semantics": "aligned_global_frame_positional_delta",
        "reference_time_offset_s": 0.0,
        "arm_time_offsets_s": {name: 0.0 for name in ARMS},
    }


_TRAJECTORY_SCALAR_KEYS = {
    "bracket_gap_max_s", "bracket_gap_p50_s", "bracket_gap_p95_s",
    "legacy_max_reference_reuse", "legacy_pair_count",
    "legacy_timestamp_error_max_s", "legacy_timestamp_error_p95_s",
    "legacy_unique_assignment_error_max_s", "legacy_unique_assignment_error_p95_s",
    "legacy_unique_assignment_pair_count", "legacy_unique_reference_used",
    "matched_count", "rpe_pairs", "ape_rmse_m", "ape_median_m", "ape_max_m",
    "rpe_rmse_m", "rpe_median_m", "rpe_max_m", "valid_grid_count",
}


def _validate_summary_semantics(summary: Mapping[str, Any]) -> None:
    _require_exact_keys(summary, {"protocol", "support", "reference", "arms"}, "common-support summary")
    if not _typed_tree_equal(summary["protocol"], _expected_summary_protocol()):
        raise GovernanceError("common-support summary protocol differs from exact evaluator contract")

    support = _require_exact_keys(
        summary["support"],
        {"grid_count", "matched_count", "common_span_s", "common_coverage", "segment_count", "rpe_pairs", "ape_valid", "rpe_valid", "window_duration_s"},
        "common-support summary support",
    )
    grid_count = _require_int(support["grid_count"], "support grid_count")
    matched_count = _require_int(support["matched_count"], "support matched_count")
    common_span = _require_float(support["common_span_s"], "support common_span_s")
    coverage = _require_float(support["common_coverage"], "support common_coverage")
    segment_count = _require_int(support["segment_count"], "support segment_count")
    rpe_pairs = _require_int(support["rpe_pairs"], "support rpe_pairs")
    duration = _require_float(support["window_duration_s"], "support window_duration_s")
    if type(support["ape_valid"]) is not bool or type(support["rpe_valid"]) is not bool:
        raise GovernanceError("support validity flags are not exact booleans")
    expected_duration = _evaluator_window_duration_s()
    if (
        grid_count != EXPECTED_GRID_COUNT
        or matched_count > grid_count
        or coverage != matched_count / grid_count
        or common_span > duration
        or duration != expected_duration
        or segment_count > matched_count
        or rpe_pairs > matched_count
    ):
        raise GovernanceError("common-support support arithmetic differs")
    expected_ape_valid = matched_count >= 30 and common_span >= 10.0 and coverage >= 0.70
    expected_rpe_valid = rpe_pairs >= 10
    if (
        support["ape_valid"] is not expected_ape_valid
        or support["rpe_valid"] is not expected_rpe_valid
        or support["ape_valid"] is not True
        or support["rpe_valid"] is not True
    ):
        raise GovernanceError("common-support output is not strict APE/RPE support PASS")

    reference = _require_exact_keys(
        summary["reference"],
        {"audit", "rejection_histogram", "bracket_gap_max_s", "bracket_gap_p50_s", "bracket_gap_p95_s", "valid_grid_count"},
        "summary reference",
    )
    _validate_sample_audit(reference["audit"], "summary reference", reference=True)
    reference_valid_grid_count = _require_int(
        reference["valid_grid_count"], "summary reference valid_grid_count"
    )
    _validate_rejection_histogram(
        reference["rejection_histogram"],
        "summary reference",
        valid_grid_count=reference_valid_grid_count,
    )
    for key in ("bracket_gap_max_s", "bracket_gap_p50_s", "bracket_gap_p95_s"):
        _require_float(reference[key], f"summary reference {key}")
    if reference_valid_grid_count != grid_count:
        raise GovernanceError("summary reference does not cover the exact 90-row grid")

    arms = _require_exact_keys(summary["arms"], set(ARMS), "summary arms")
    arm_expected_keys = {"audit", "rejection_histogram", *_TRAJECTORY_SCALAR_KEYS}
    for name in ARMS:
        arm = _require_exact_keys(arms[name], arm_expected_keys, f"summary arm {name}")
        _validate_sample_audit(arm["audit"], f"summary arm {name}", reference=False)
        integer_keys = {
            "legacy_max_reference_reuse", "legacy_pair_count",
            "legacy_unique_assignment_pair_count", "legacy_unique_reference_used",
            "matched_count", "rpe_pairs", "valid_grid_count",
        }
        for key in integer_keys:
            _require_int(arm[key], f"summary arm {name} {key}")
        _validate_rejection_histogram(
            arm["rejection_histogram"],
            f"summary arm {name}",
            valid_grid_count=arm["valid_grid_count"],
        )
        for key in _TRAJECTORY_SCALAR_KEYS - integer_keys:
            _require_float(arm[key], f"summary arm {name} {key}")
        if (
            arm["matched_count"] != matched_count
            or arm["rpe_pairs"] != rpe_pairs
            or not matched_count <= arm["valid_grid_count"] <= grid_count
            or arm["legacy_unique_reference_used"] > 91
            or arm["legacy_unique_assignment_pair_count"] > 91
        ):
            raise GovernanceError(f"summary arm {name} support relation differs")


def _normalized_summary(content: bytes, expected_reference_procfd: str | None = None) -> dict[str, Any]:
    try:
        value = json.loads(content, parse_constant=_reject_json_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise GovernanceError("common-support summary is invalid JSON") from error
    if not isinstance(value, dict) or not isinstance(value.get("protocol"), dict):
        raise GovernanceError("common-support summary protocol is absent")
    result = copy.deepcopy(value)
    reference = result["protocol"].get("reference")
    if not isinstance(reference, str):
        raise GovernanceError("summary reference identity is absent")
    match = _PROCFD_REFERENCE_RE.fullmatch(reference)
    if match is None:
        raise GovernanceError("summary reference is not exact procfd:topic")
    if expected_reference_procfd is not None and match.group("fd") != expected_reference_procfd:
        raise GovernanceError("summary reference procfd differs from retained bag lease")
    result["protocol"]["reference"] = f"{RAW_BAG}:{REFERENCE_TOPIC}"
    _validate_summary_semantics(result)
    return result


def _decode_csv(content: bytes, label: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = content.decode("utf-8", "strict")
    except UnicodeDecodeError as error:
        raise GovernanceError(f"{label} is not UTF-8") from error
    if not text.endswith("\r\n") or "\x00" in text:
        raise GovernanceError(f"{label} does not use the exact evaluator CSV framing")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
        rows = list(reader)
    except csv.Error as error:
        raise GovernanceError(f"{label} is malformed CSV") from error
    header = reader.fieldnames
    if header is None or len(header) != len(set(header)) or any(None in row for row in rows):
        raise GovernanceError(f"{label} CSV header/row width is ambiguous")
    return header, rows


def _validate_metrics_csv(summary: Mapping[str, Any], content: bytes) -> None:
    header, rows = _decode_csv(content, "common-support metrics")
    expected_header = sorted({"arm", *_TRAJECTORY_SCALAR_KEYS})
    if header != expected_header or len(rows) != len(ARMS):
        raise GovernanceError("common-support metrics CSV closure differs")
    observed_names: list[str] = []
    arms = summary["arms"]
    for row in rows:
        name = row["arm"]
        if name not in ARMS or name in observed_names:
            raise GovernanceError("common-support metrics CSV arm order/set differs")
        observed_names.append(name)
        for key in _TRAJECTORY_SCALAR_KEYS:
            if row[key] != str(arms[name][key]):
                raise GovernanceError(f"common-support metrics CSV/JSON mismatch: {name}.{key}")
    if observed_names != list(ARMS):
        raise GovernanceError("common-support metrics CSV arm order differs")


def _validate_grid_csv(summary: Mapping[str, Any], content: bytes) -> None:
    header, rows = _decode_csv(content, "common-grid audit")
    arm_columns = [f"{name}_valid" for name in ARMS]
    expected_header = ["timestamp", "reference_valid", *arm_columns, "common_valid", "segment_id"]
    if header != expected_header or len(rows) != EXPECTED_GRID_COUNT:
        raise GovernanceError("common-grid audit exact header/count differs")
    valid_counts = {name: 0 for name in ARMS}
    reference_valid_count = 0
    common_count = 0
    rpe_pairs = 0
    current_segment = -1
    previous_common_index: int | None = None
    first_common_index: int | None = None
    last_common_index: int | None = None
    for index, row in enumerate(rows):
        expected_stamp = _evaluator_grid_timestamp_text(index)
        if row["timestamp"] != expected_stamp:
            raise GovernanceError("common-grid audit timestamp grid differs")
        flag_values = [row["reference_valid"], *(row[column] for column in arm_columns), row["common_valid"]]
        if any(value not in {"0", "1"} for value in flag_values):
            raise GovernanceError("common-grid audit validity flag is not exact binary CSV")
        reference_valid = int(row["reference_valid"])
        arm_valid = {name: int(row[f"{name}_valid"]) for name in ARMS}
        common_valid = int(row["common_valid"])
        if common_valid != int(reference_valid == 1 and all(arm_valid.values())):
            raise GovernanceError("common-grid audit common mask is not the exact intersection")
        reference_valid_count += reference_valid
        for name, valid in arm_valid.items():
            valid_counts[name] += valid
        if common_valid:
            if previous_common_index is None or index - previous_common_index > 1:
                current_segment += 1
            expected_segment = current_segment
            if previous_common_index is not None and index - previous_common_index == 1:
                rpe_pairs += 1
            if first_common_index is None:
                first_common_index = index
            previous_common_index = index
            last_common_index = index
            common_count += 1
        else:
            expected_segment = -1
        if row["segment_id"] != str(expected_segment):
            raise GovernanceError("common-grid audit segment identity differs")
    support = summary["support"]
    expected_common_span = (
        _evaluator_grid_span_s(first_common_index, last_common_index)
        if first_common_index is not None
        and last_common_index is not None
        and common_count >= 2
        else 0.0
    )
    if (
        reference_valid_count != summary["reference"]["valid_grid_count"]
        or common_count != support["matched_count"]
        or support["common_span_s"] != expected_common_span
        or rpe_pairs != support["rpe_pairs"]
        or current_segment + 1 != support["segment_count"]
        or any(valid_counts[name] != summary["arms"][name]["valid_grid_count"] for name in ARMS)
    ):
        raise GovernanceError("common-grid CSV/JSON support semantics differ")


def _validate_runtime_receipt(content: bytes, role: str, freeze: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GovernanceError(f"{role} runtime receipt is invalid JSON") from error
    if not isinstance(value, dict):
        raise GovernanceError(f"{role} runtime receipt is not an object")
    bootstrap.validate_runtime_receipt_static(
        value,
        role=role,
        expected_closure=freeze["expected_runtime_closure"]["runtime_receipt"],
    )
    _validate_persistent_runtime_files(value)
    expected_receipt = freeze["expected_runtime_closure"]["runtime_receipt"]
    expected_sealed = _sealed_content_identity(expected_receipt)
    observed_sealed = _sealed_content_identity(value)
    if expected_sealed != observed_sealed:
        raise GovernanceError(f"{role} sealed runtime source content differs from freeze probe")
    return value


def _runtime_semantic_identity(value: Mapping[str, Any]) -> object:
    return bootstrap.runtime_semantic_identity(value)


def _validate_runtime_process_binding(
    runtime: Mapping[str, Any], process: Mapping[str, Any], role: str
) -> None:
    aliases = process["actual_procfd_aliases"]
    execution = runtime.get("execution")
    if not isinstance(execution, Mapping):
        raise GovernanceError(f"{role} runtime execution receipt is malformed")
    process_argv = process.get("actual_procfd_argv")
    if (
        set(execution) != {
            "sys_argv", "process_argv", "environment", "target_signal_mask"
        }
        or not isinstance(process_argv, list)
        or execution.get("process_argv") != process_argv
        or execution.get("sys_argv") != process_argv[3:]
    ):
        raise GovernanceError(f"{role} runtime/process argv binding differs")
    environment = execution.get("environment")
    if not isinstance(environment, Mapping):
        raise GovernanceError(f"{role} runtime environment is malformed")
    expected_environment = _materialize_environment(
        process["authorized_environment_template"], aliases
    )
    if dict(environment) != expected_environment:
        raise GovernanceError(f"{role} runtime environment differs from exact materialization")
    if hashlib.sha256(_canonical_json_bytes(dict(environment))).hexdigest() != process.get(
        "actual_environment_sha256"
    ):
        raise GovernanceError(f"{role} runtime/process environment hash differs")
    sealed = runtime.get("sealed_sources")
    if not isinstance(sealed, Mapping):
        raise GovernanceError(f"{role} sealed runtime sources are malformed")
    expected_locators = {
        "python_interpreter": aliases[os.fspath(PYTHON)],
        "bootstrap": aliases[os.fspath(BOOTSTRAP)],
        "wrapper": aliases["${EPOCH_WRAPPER_PROCFD}"],
        "evaluator_base": aliases["${EVALUATOR_BASE_PROCFD}"],
        "evaluator_core": aliases["${TRAJECTORY_CORE_PROCFD}"],
    }
    for name, locator in expected_locators.items():
        record = sealed.get(name)
        if not isinstance(record, Mapping) or record.get("locator") != locator:
            raise GovernanceError(f"{role} sealed source locator differs: {name}")


def _compare_roles(payloads: Mapping[str, Mapping[str, bytes]], proc_reference: str | None, freeze: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    primary = payloads["primary"]
    verification = payloads["verification"]
    normalized = {
        role: _normalized_summary(payloads[role]["common_support_summary.json"], proc_reference)
        for role in ROLE_NAMES
    }
    if normalized["primary"] != normalized["verification"]:
        raise GovernanceError("primary/verification summaries differ after typed reference normalization")
    for name in ("common_support_metrics.csv", "common_grid_audit.csv"):
        if primary[name] != verification[name]:
            raise GovernanceError(f"primary/verification {name} bytes differ")
    _validate_metrics_csv(normalized["primary"], primary["common_support_metrics.csv"])
    _validate_grid_csv(normalized["primary"], primary["common_grid_audit.csv"])
    runtime = {role: _validate_runtime_receipt(payloads[role][RUNTIME_RECEIPT_NAME], role, freeze) for role in ROLE_NAMES}
    if _runtime_semantic_identity(runtime["primary"]) != _runtime_semantic_identity(runtime["verification"]):
        raise GovernanceError("primary/verification actual runtime closure differs")
    artifacts = {
        role: {name: _stream_receipt(payloads[role][name]) for name in ROLE_FILES}
        for role in ROLE_NAMES
    }
    comparison = {
        "typed_normalization": f"protocol.reference ${{procfd}}:{REFERENCE_TOPIC} -> {RAW_BAG}:{REFERENCE_TOPIC}",
        "all_other_summary_leaves_exact": True,
        "summary_protocol_support_strict": True,
        "metrics_csv_bytes_exact": True,
        "metrics_csv_json_semantics_exact": True,
        "grid_csv_bytes_exact": True,
        "grid_csv_json_semantics_exact": True,
        "runtime_semantic_closure_exact": True,
        "normalized_summary_sha256": hashlib.sha256(_canonical_json_bytes(normalized["primary"])).hexdigest(),
        "artifact_records": artifacts,
    }
    return normalized["primary"], comparison


def _bound_summary(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    processes: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
    comparison: Mapping[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": BOUND_SCHEMA,
        "status": "COMPLETED_PRIMARY_AND_VERIFICATION_RC0",
        "freeze": _workspace_record(FREEZE, "freeze"),
        "freeze_hash": freeze["freeze_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "role_order": list(ROLE_NAMES),
        "role_processes": [dict(value) for value in processes],
        "comparison": dict(comparison),
        "normalized_summary": dict(summary),
        "outcome_boundary": dict(OUTCOME_BOUNDARY),
        "bound_summary_hash": "0" * 64,
    }
    payload["bound_summary_hash"] = _self_hash(payload, "bound_summary_hash")
    return payload


def _run_evaluation_scoped() -> int:
    freeze = validate_freeze_static(require_fresh_outputs=True)
    with _held_exact_json_authority(
        FREEZE, freeze, label="held run freeze authority"
    ) as freeze_validator:
        freeze_validator()
        if validate_freeze_static(require_fresh_outputs=False) != freeze:
            raise GovernanceError("held run freeze semantic identity drifted")
        intent = _build_intent(freeze)
        intent_path = Path(str(intent["intent_path_absolute"]))
        with _write_held_canonical_json_rooted(
            ROOT, intent_path, intent, label="held run publication intent"
        ) as (intent_validator, _intent_record):
            intent_validator()
            if _load_exact_intent(freeze) != intent:
                raise GovernanceError(
                    "held run publication intent semantic identity differs"
                )
            result = _run_evaluation_with_held_intent(
                freeze, intent, freeze_validator, intent_validator
            )
            freeze_validator()
            if validate_freeze_static(require_fresh_outputs=False) != freeze:
                raise GovernanceError("held run freeze changed before return")
            intent_validator()
            if _load_exact_intent(freeze) != intent:
                raise GovernanceError("held run publication intent changed before return")
            return result


def _run_evaluation_with_held_intent(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    freeze_validator: Any,
    intent_validator: Any,
) -> int:
    staging = Path(str(intent["staging_absolute"]))
    closeout_path = Path(str(intent["closeout_path_absolute"]))

    def validate_intent() -> None:
        intent_validator()
        if _load_exact_intent(freeze) != intent:
            raise GovernanceError("held run publication intent changed")

    def validate_freeze() -> None:
        freeze_validator()
        if validate_freeze_static(require_fresh_outputs=False) != freeze:
            raise GovernanceError("held run freeze semantic identity drifted")

    validate_freeze()
    validate_intent()
    with _create_retained_workspace_directory(
        ROOT,
        staging,
        label="G0 staging",
        relocated_to=OUTPUT,
    ) as (staging_fd, staging_validator):
        with ExitStack() as leases:
            validate_intent()
            nonexecution = {
                role: freeze["input_records"][role]
                for role in sorted(set(INPUTS) - set(EXECUTION_INPUT_KEYS))
            }
            authority_validators = _retained_workspace_record_validators(
                leases, nonexecution, label="held run provenance"
            )
            external_leases = _retained_external_record_validators(
                leases, freeze["vins_external_runtime"], label="held_run_vins"
            )
            runtime_holds = _retained_runtime_file_holds(
                leases,
                freeze["expected_runtime_closure"]["runtime_receipt"],
                label="held run frozen runtime",
            )
            proc, shared_fds, python_lease = _sealed_execution_inputs(leases, freeze)
            role_fds: dict[str, int] = {}
            role_validators: dict[str, Any] = {}
            leaf_validators: list[Any] = []
            processes: list[dict[str, Any]] = []
            payloads: dict[str, dict[str, bytes]] = {}

            def validate_barrier(*, published: bool = False) -> None:
                _validate_outer_workspace_module_closure()
                validate_freeze()
                validate_intent()
                staging_validator(OUTPUT if published else staging)
                for validator in role_validators.values():
                    validator()
                for validator in leaf_validators:
                    validator()
                python_lease.verify_unchanged()
                _validate_retained_authority(
                    authority_validators, external_leases
                )
                _validate_runtime_file_holds(runtime_holds)

            for role in ROLE_NAMES:
                role_fd, role_validator = leases.enter_context(
                    _create_retained_child_directory(
                        staging_fd, role, label=f"G0 staging {role}"
                    )
                )
                role_fds[role] = role_fd
                role_validators[role] = role_validator
                argv, environment, mapping = _actual_role_contract(
                    role, proc, python_lease, role_fd
                )
                launch = _launch_intent(
                    role, argv, environment, mapping, freeze
                )
                launch_validator, _launch_record = leases.enter_context(
                    _write_held_canonical_json_at(
                        staging_fd,
                        f"{role}_launch_intent.json",
                        launch,
                        label=f"{role} durable launch intent",
                    )
                )
                leaf_validators.append(launch_validator)
                validate_barrier()
                receipt = _launch_role(
                    role,
                    argv,
                    environment,
                    [*shared_fds, role_fd],
                    freeze,
                    mapping,
                    str(launch["launch_intent_hash"]),
                )
                python_lease.verify_unchanged()
                processes.append(receipt)
                if receipt["classification"] != "EXITED_RC0":
                    _write_failed_process_receipt(
                        leases, staging_fd, role, receipt
                    )
                    raise GovernanceError(f"{role} evaluator did not exit RC0")
                payloads[role] = {}
                for name in ROLE_FILES:
                    content, output_validator = leases.enter_context(
                        _hold_existing_leaf_at(
                            role_fd, name, label=f"held {role} {name}"
                        )
                    )
                    payloads[role][name] = content
                    leaf_validators.append(output_validator)
                validate_barrier()
            summary, comparison = _compare_roles(payloads, proc["reference_bag"], freeze)
            for role, process in zip(ROLE_NAMES, processes):
                runtime = _validate_runtime_receipt(
                    payloads[role][RUNTIME_RECEIPT_NAME], role, freeze
                )
                _validate_runtime_process_binding(runtime, process, role)
            bound = _bound_summary(freeze, intent, processes, summary, comparison)
            bound_validator, _bound_record = leases.enter_context(
                _write_held_canonical_json_at(
                    staging_fd,
                    publisher.BOUND_SUMMARY_NAME,
                    bound,
                    label="bound G0 summary",
                )
            )
            leaf_validators.append(bound_validator)
            validate_barrier()
            preseal = publisher._inventory_open_result(staging_fd, durable=True)
            preseal_records, _preseal_ids, preseal_seals, preseal_payload = preseal
            if preseal_seals:
                raise GovernanceError("staging unexpectedly sealed before preseal barrier")
            _validate_snapshot_payload(
                freeze, intent, preseal_records, preseal_payload
            )
            validate_barrier()
            publisher.seal_staging_result_retained(
                intent, root=ROOT, staging_fd=staging_fd
            )
            validate_barrier()
            sealed = publisher._inventory_open_result(staging_fd, durable=True)
            sealed_records, _sealed_ids, sealed_seals, sealed_payload = sealed
            if set(sealed_seals) != {
                publisher.MANIFEST_NAME, publisher.RECEIPT_NAME
            }:
                raise GovernanceError("sealed staging evidence closure differs")
            publisher._validate_sealed_components(
                sealed_records,
                sealed_seals[publisher.MANIFEST_NAME],
                sealed_seals[publisher.RECEIPT_NAME],
                intent=intent,
                root=ROOT,
            )
            _validate_snapshot_payload(
                freeze, intent, sealed_records, sealed_payload
            )
            validate_barrier()
            closeout = publisher.publish_staging(
                intent,
                root=ROOT,
                closeout_path=closeout_path,
                staging_fd=staging_fd,
            )
            closeout_validator = leases.enter_context(
                _hold_existing_canonical_json_rooted(
                    ROOT,
                    closeout_path,
                    closeout,
                    label="held run publication closeout",
                )
            )
            leaf_validators.append(closeout_validator)
            validate_barrier(published=True)
            publisher.validate_closeout(closeout, intent=intent, root=ROOT)
            for role, descriptor in role_fds.items():
                publisher.assert_retained_workspace_directory(
                    ROOT, OUTPUT / role, descriptor, label=f"held published {role}"
                )
            validate_barrier(published=True)
    return 0


def run_evaluation() -> int:
    with _post_result_publication_semantics():
        return _run_evaluation_scoped()


def _validate_process_receipt(value: Mapping[str, Any], role: str, freeze: Mapping[str, Any]) -> None:
    expected_keys = {
        "schema_version", "status", "role", "pid", "process_started_before_wait",
        "attempt_count", "process_start_count", "no_retry", "timeout_seconds",
        "timed_out", "return_code", "termination_signal", "classification",
        "wait_error", "cleanup_errors", "child_reaped", "spawn_signal_guard",
        "stdout", "stderr", "authorized_canonical_argv", "actual_procfd_argv",
        "actual_procfd_aliases", "actual_procfd_binding_records",
        "pass_fd_numbers",
        "authorized_environment_template",
        "actual_environment_sha256", "freeze_hash", "launch_intent_hash",
        "process_receipt_hash",
    }
    if set(value) != expected_keys:
        raise GovernanceError(f"{role} process receipt key set differs")
    if value.get("schema_version") != PROCESS_SCHEMA or value.get("role") != role:
        raise GovernanceError(f"{role} process receipt schema/role differs")
    if value.get("status") != "COMPLETED_RC0":
        raise GovernanceError(f"{role} process receipt status differs")
    p07gov.validate_self_hash(value, "process_receipt_hash", label=f"{role} process receipt")
    if value.get("freeze_hash") != freeze["freeze_hash"]:
        raise GovernanceError(f"{role} process freeze binding differs")
    if value.get("authorized_canonical_argv") != freeze["authorized_role_argv"][role]:
        raise GovernanceError(f"{role} canonical argv differs")
    actual = value.get("actual_procfd_argv")
    canonical = value.get("authorized_canonical_argv")
    if not isinstance(actual, list) or not isinstance(canonical, list) or len(actual) != len(canonical):
        raise GovernanceError(f"{role} actual argv shape differs")
    aliases = value.get("actual_procfd_aliases")
    expected_alias_keys = {
        os.fspath(PYTHON), os.fspath(BOOTSTRAP), os.fspath(RAW_BAG),
        os.fspath(CONFIG), os.fspath(GFTT_VIO), os.fspath(XFEAT_VIO),
        os.fspath(OUTPUT / role), "${EPOCH_WRAPPER_PROCFD}",
        "${EVALUATOR_BASE_PROCFD}", "${TRAJECTORY_CORE_PROCFD}",
        "${ROLE_OUTPUT_DIRFD}",
    }
    if not isinstance(aliases, Mapping) or set(aliases) != expected_alias_keys:
        raise GovernanceError(f"{role} procfd alias key set differs")
    if any(
        re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", str(item)) is None
        for item in aliases.values()
    ):
        raise GovernanceError(f"{role} procfd alias value differs")
    if _materialize_strings(canonical, aliases) != actual:
        raise GovernanceError(f"{role} actual procfd argv does not map exactly to canonical argv")
    if value.get("actual_procfd_binding_records") != _procfd_binding_records(
        role, aliases, freeze
    ):
        raise GovernanceError(f"{role} procfd content bindings differ")
    if value.get("pass_fd_numbers") != _procfd_numbers(
        aliases, label=f"{role} process aliases"
    ):
        raise GovernanceError(f"{role} process pass-fd closure differs")
    if (
        aliases["${ROLE_OUTPUT_DIRFD}"] != aliases[os.fspath(OUTPUT / role)]
        or actual[0] != aliases[os.fspath(PYTHON)]
        or actual[1:3] != ["-I", "-B"]
        or actual[3] != aliases[os.fspath(BOOTSTRAP)]
    ):
        raise GovernanceError(f"{role} actual argv prefix differs")
    if value.get("authorized_environment_template") != freeze["authorized_environment_templates"][role]:
        raise GovernanceError(f"{role} environment template binding differs")
    materialized_environment = _materialize_environment(
        value["authorized_environment_template"], aliases
    )
    expected_environment_hash = hashlib.sha256(
        _canonical_json_bytes(materialized_environment)
    ).hexdigest()
    if value.get("actual_environment_sha256") != expected_environment_hash:
        raise GovernanceError(f"{role} exact materialized environment hash differs")
    p07gov.require_hash(value.get("launch_intent_hash"), f"{role} launch intent")
    if not isinstance(value.get("pid"), int) or int(value["pid"]) <= 0:
        raise GovernanceError(f"{role} PID receipt differs")
    exact = {
        "process_started_before_wait": True,
        "attempt_count": 1,
        "process_start_count": 1,
        "no_retry": True,
        "timeout_seconds": PROCESS_TIMEOUT_SECONDS,
        "timed_out": False,
        "return_code": 0,
        "termination_signal": None,
        "classification": "EXITED_RC0",
        "wait_error": None,
        "cleanup_errors": [],
        "child_reaped": True,
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise GovernanceError(f"{role} process receipt {key} differs")
    _validate_spawn_signal_guard(
        value.get("spawn_signal_guard"), process_started=True, success=True
    )
    for stream in ("stdout", "stderr"):
        item = value.get(stream)
        if not isinstance(item, Mapping) or set(item) != {"sha256", "size_bytes"}:
            raise GovernanceError(f"{role} {stream} receipt shape differs")
        p07gov.require_hash(item.get("sha256"), f"{role} {stream}")
        if not isinstance(item.get("size_bytes"), int) or item["size_bytes"] < 0:
            raise GovernanceError(f"{role} {stream} size differs")


def _validate_launch_intent(
    value: Mapping[str, Any], role: str, freeze: Mapping[str, Any]
) -> None:
    expected_keys = {
        "schema_version", "status", "role", "attempt_count",
        "authorized_process_start_count", "no_retry_after_pending_evidence",
        "timeout_seconds", "freeze_hash", "authorized_canonical_argv",
        "actual_procfd_argv", "actual_procfd_aliases",
        "actual_procfd_binding_records", "authorized_environment_template",
        "pass_fd_numbers", "spawn_signal_policy",
        "actual_environment_sha256", "launch_intent_hash",
    }
    if set(value) != expected_keys:
        raise GovernanceError(f"{role} launch-intent key set differs")
    p07gov.validate_self_hash(
        value, "launch_intent_hash", label=f"{role} launch intent"
    )
    exact = {
        "schema_version": LAUNCH_SCHEMA,
        "status": "DURABLE_PROCESS_LAUNCH_PENDING_NO_RETRY",
        "role": role,
        "attempt_count": 1,
        "authorized_process_start_count": 1,
        "no_retry_after_pending_evidence": True,
        "timeout_seconds": PROCESS_TIMEOUT_SECONDS,
        "spawn_signal_policy": _spawn_signal_policy(),
        "freeze_hash": freeze["freeze_hash"],
        "authorized_canonical_argv": freeze["authorized_role_argv"][role],
        "authorized_environment_template": freeze[
            "authorized_environment_templates"
        ][role],
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            raise GovernanceError(f"{role} launch-intent {key} differs")
    aliases = value.get("actual_procfd_aliases")
    argv = value.get("actual_procfd_argv")
    if not isinstance(aliases, Mapping) or not isinstance(argv, list):
        raise GovernanceError(f"{role} launch-intent procfd binding is malformed")
    expected_alias_keys = {
        os.fspath(PYTHON), os.fspath(BOOTSTRAP), os.fspath(RAW_BAG),
        os.fspath(CONFIG), os.fspath(GFTT_VIO), os.fspath(XFEAT_VIO),
        os.fspath(OUTPUT / role), "${EPOCH_WRAPPER_PROCFD}",
        "${EVALUATOR_BASE_PROCFD}", "${TRAJECTORY_CORE_PROCFD}",
        "${ROLE_OUTPUT_DIRFD}",
    }
    if set(aliases) != expected_alias_keys or any(
        not isinstance(item, str)
        or re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", item) is None
        for item in aliases.values()
    ):
        raise GovernanceError(f"{role} launch-intent procfd aliases differ")
    if _materialize_strings(exact["authorized_canonical_argv"], aliases) != argv:
        raise GovernanceError(f"{role} launch-intent procfd argv differs")
    if value.get("actual_procfd_binding_records") != _procfd_binding_records(
        role, aliases, freeze
    ):
        raise GovernanceError(f"{role} launch-intent content binding differs")
    if value.get("pass_fd_numbers") != _procfd_numbers(
        aliases, label=f"{role} launch aliases"
    ):
        raise GovernanceError(f"{role} launch-intent pass-fd closure differs")
    if (
        aliases["${ROLE_OUTPUT_DIRFD}"] != aliases[os.fspath(OUTPUT / role)]
        or argv[0] != aliases[os.fspath(PYTHON)]
        or argv[1:3] != ["-I", "-B"]
        or argv[3] != aliases[os.fspath(BOOTSTRAP)]
    ):
        raise GovernanceError(f"{role} launch-intent procfd prefix differs")
    expected_environment_hash = hashlib.sha256(
        _canonical_json_bytes(
            _materialize_environment(
                exact["authorized_environment_template"], aliases
            )
        )
    ).hexdigest()
    if value.get("actual_environment_sha256") != expected_environment_hash:
        raise GovernanceError(f"{role} launch-intent environment hash differs")


def _validate_snapshot_payload(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    payload: Mapping[str, bytes],
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_paths = {publisher.BOUND_SUMMARY_NAME} | {
        f"{role}/{name}" for role in ROLE_NAMES for name in ROLE_FILES
    } | {f"{role}_launch_intent.json" for role in ROLE_NAMES}
    if {str(item.get("path")) for item in records} != expected_paths or set(payload) != expected_paths:
        raise GovernanceError("published G0 payload closure differs")
    role_payloads = {
        role: {name: payload[f"{role}/{name}"] for name in ROLE_FILES}
        for role in ROLE_NAMES
    }
    summary, comparison = _compare_roles(role_payloads, None, freeze)
    try:
        bound = json.loads(payload[publisher.BOUND_SUMMARY_NAME])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GovernanceError("bound summary is invalid JSON") from error
    if not isinstance(bound, dict) or bound.get("schema_version") != BOUND_SCHEMA:
        raise GovernanceError("bound summary schema differs")
    expected_bound_keys = {
        "schema_version", "status", "freeze", "freeze_hash",
        "publication_intent_hash", "role_order", "role_processes",
        "comparison", "normalized_summary", "outcome_boundary",
        "bound_summary_hash",
    }
    if set(bound) != expected_bound_keys:
        raise GovernanceError("bound summary key set differs")
    if (
        bound.get("status") != "COMPLETED_PRIMARY_AND_VERIFICATION_RC0"
        or bound.get("role_order") != list(ROLE_NAMES)
        or bound.get("outcome_boundary") != OUTCOME_BOUNDARY
    ):
        raise GovernanceError("bound summary status/roles/outcome boundary differs")
    p07gov.validate_self_hash(bound, "bound_summary_hash", label="bound summary")
    if bound.get("freeze") != _workspace_record(FREEZE, "freeze") or bound.get("freeze_hash") != freeze["freeze_hash"]:
        raise GovernanceError("bound summary freeze binding differs")
    if bound.get("publication_intent_hash") != intent["publication_intent_hash"]:
        raise GovernanceError("bound summary intent binding differs")
    processes = bound.get("role_processes")
    if not isinstance(processes, list) or [item.get("role") for item in processes if isinstance(item, Mapping)] != list(ROLE_NAMES):
        raise GovernanceError("bound summary role process closure differs")
    for role, process in zip(ROLE_NAMES, processes):
        if not isinstance(process, Mapping):
            raise GovernanceError(f"{role} process receipt malformed")
        _validate_process_receipt(process, role, freeze)
        try:
            launch = json.loads(payload[f"{role}_launch_intent.json"])
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GovernanceError(f"{role} launch intent is invalid JSON") from error
        if not isinstance(launch, Mapping):
            raise GovernanceError(f"{role} launch intent is not an object")
        _validate_launch_intent(launch, role, freeze)
        if process.get("launch_intent_hash") != launch.get("launch_intent_hash"):
            raise GovernanceError(f"{role} process/launch-intent binding differs")
        runtime = _validate_runtime_receipt(
            role_payloads[role][RUNTIME_RECEIPT_NAME], role, freeze
        )
        _validate_runtime_process_binding(runtime, process, role)
    primary_aliases = processes[0]["actual_procfd_aliases"]
    verification_aliases = processes[1]["actual_procfd_aliases"]
    shared_keys = set(primary_aliases) - {
        os.fspath(OUTPUT / "primary"), "${ROLE_OUTPUT_DIRFD}"
    }
    verification_shared = set(verification_aliases) - {
        os.fspath(OUTPUT / "verification"), "${ROLE_OUTPUT_DIRFD}"
    }
    if shared_keys != verification_shared or any(
        primary_aliases[key] != verification_aliases[key] for key in shared_keys
    ):
        raise GovernanceError("primary/verification did not reuse exact shared procfd leases")
    if bound.get("comparison") != comparison or bound.get("normalized_summary") != summary:
        raise GovernanceError("bound summary scientific comparison differs")
    return bound, summary


def _scientific_failures(summary: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    support = summary.get("support")
    arms = summary.get("arms")
    if not isinstance(support, Mapping):
        return ["SUPPORT_OBJECT_ABSENT"]
    if support.get("ape_valid") is not True:
        failures.append("APE_SUPPORT_INVALID")
    if support.get("rpe_valid") is not True:
        failures.append("RPE_SUPPORT_INVALID")
    if support.get("grid_count") != EXPECTED_GRID_COUNT:
        failures.append("GRID_COUNT_INVALID")
    if not isinstance(arms, Mapping) or set(arms) != set(ARMS):
        failures.append("ARM_SET_INVALID")
        return failures
    for arm in sorted(ARMS):
        metrics = arms.get(arm)
        if not isinstance(metrics, Mapping):
            failures.append(f"{arm}_METRICS_ABSENT")
            continue
        for key in ("ape_rmse_m", "ape_median_m", "ape_max_m", "rpe_rmse_m", "rpe_median_m", "rpe_max_m"):
            value = metrics.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                failures.append(f"{arm}_{key}_INVALID")
    return failures


def _build_post_from_held(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    closeout: Mapping[str, Any],
    receipt: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    payload: Mapping[str, bytes],
) -> dict[str, Any]:
    bound, summary = _validate_snapshot_payload(freeze, intent, records, payload)
    failures = _scientific_failures(summary)
    result: dict[str, Any] = {
        "schema_version": POST_SCHEMA,
        "status": POST_PASS if not failures else POST_FAIL,
        "pass": not failures,
        "freeze": _workspace_record(FREEZE, "freeze"),
        "freeze_hash": freeze["freeze_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "result_receipt_hash": receipt["result_receipt_hash"],
        "publication_closeout_hash": closeout["publication_closeout_hash"],
        "published_payload_records": [dict(item) for item in records],
        "bound_summary_hash": bound["bound_summary_hash"],
        "strict_gates": {
            "primary_and_verification_process_rc0_once_no_retry": True,
            "summary_equal_after_reference_only_typed_normalization": True,
            "metrics_csv_bytes_equal": True,
            "grid_csv_bytes_equal": True,
            "actual_runtime_semantics_equal": True,
            "ape_valid": summary.get("support", {}).get("ape_valid"),
            "rpe_valid": summary.get("support", {}).get("rpe_valid"),
            "grid_count": summary.get("support", {}).get("grid_count"),
        },
        "failure_reasons": failures,
        "result_metrics": summary.get("arms") if not failures else None,
        "outcome_boundary": dict(OUTCOME_BOUNDARY),
        "post_process_start_count": 0,
        "post_hash": "0" * 64,
    }
    result["post_hash"] = _self_hash(result, "post_hash")
    return result


def _validate_closeout_against_held_seals(
    closeout: object,
    intent: Mapping[str, Any],
    receipt: Mapping[str, Any],
    seals: Mapping[str, bytes],
) -> dict[str, Any]:
    if not isinstance(closeout, Mapping):
        raise GovernanceError("publication closeout is not an object")
    # This reconstruction depends only on the already-held output directory,
    # its validated receipt, and its exact held seal bytes.  It therefore
    # cannot be satisfied by swapping the destination path between a
    # path-based closeout check and acquisition of the retained snapshot.
    expected = publisher._build_closeout_from_retained_snapshot(
        intent, receipt, seals, root=ROOT
    )
    if not _typed_tree_equal(dict(closeout), expected):
        raise GovernanceError("publication closeout differs from held P07 seals")
    p07gov.validate_self_hash(
        closeout, "publication_closeout_hash", label="publication closeout"
    )
    if closeout.get("result_receipt_hash") != receipt.get("result_receipt_hash"):
        raise GovernanceError("publication closeout/held receipt hash differs")
    for key, name in (
        ("receipt", publisher.RECEIPT_NAME),
        ("output_manifest", publisher.MANIFEST_NAME),
    ):
        content = seals[name]
        expected_record = {
            "path": p07gov.display_path(ROOT, OUTPUT / name),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        if closeout.get(key) != expected_record:
            raise GovernanceError(f"publication closeout held {key} record differs")
    return expected


@contextmanager
def _held_published_result(intent: Mapping[str, Any]):
    """Hold output and closeout inodes through the complete POST transaction."""

    top, parts, directory_identity = publisher._open_result_directory(ROOT, OUTPUT)
    try:
        first = publisher._inventory_open_result(top, durable=True)
        baseline = publisher._inventory_open_result(top, durable=True)
        if first != baseline:
            raise GovernanceError("published result changed before held use")
        records, _identities, seals, payload = baseline
        if set(seals) != {publisher.MANIFEST_NAME, publisher.RECEIPT_NAME}:
            raise GovernanceError("held published result lacks exact P07 seal files")
        receipt, validated_records = publisher._validate_sealed_components(
            records,
            seals[publisher.MANIFEST_NAME],
            seals[publisher.RECEIPT_NAME],
            intent=intent,
            root=ROOT,
        )
        if validated_records != records:
            raise GovernanceError("held published P07 record validation differs")

        def validate_live() -> None:
            current = publisher._inventory_open_result(top, durable=True)
            if current != baseline:
                raise GovernanceError("held published result changed during POST transaction")
            publisher.assert_retained_workspace_directory(
                ROOT, OUTPUT, top, label="held published G0 result"
            )

        validate_live()
        closeout_path = Path(str(intent["closeout_path_absolute"]))
        closeout_bytes = publisher.read_bytes_bound_input_rooted(
            ROOT, closeout_path, label="publication closeout retained bytes"
        )
        closeout = p07gov._json_object_bytes(
            closeout_bytes, label="publication closeout"
        )
        with publisher.retained_bound_input_validator(
            ROOT, closeout_path, closeout_bytes, label="publication closeout"
        ) as closeout_validator:
            _validate_closeout_against_held_seals(
                closeout, intent, receipt, seals
            )

            def validate_all() -> None:
                validate_live()
                closeout_validator()
                _validate_closeout_against_held_seals(
                    closeout, intent, receipt, seals
                )
                validate_live()
                closeout_validator()

            validate_all()
            yield (
                dict(closeout), receipt, records, dict(payload), dict(seals),
                validate_all,
            )
            validate_all()
    finally:
        os.close(top)
    publisher._assert_directory_reachable(
        ROOT, parts, directory_identity, label="held published G0 result"
    )


def _seal_post_scoped() -> int:
    freeze = validate_freeze_static(require_fresh_outputs=False)
    with ExitStack() as post_holds:
        with _held_exact_json_authority(
            FREEZE, freeze, label="held seal-post freeze"
        ) as freeze_validator:
            freeze_validator()
            if validate_freeze_static(require_fresh_outputs=False) != freeze:
                raise GovernanceError("held seal-post freeze semantic identity differs")
            if os.path.lexists(POST):
                raise GovernanceError("post namespace already contains evidence")
            intent = _load_exact_intent(freeze)
            intent_path = Path(str(intent["intent_path_absolute"]))
            with _held_exact_json_authority(
                intent_path, intent, label="held seal-post publication intent"
            ) as intent_validator:
                return _seal_post_with_held_authorities(
                    freeze,
                    intent,
                    freeze_validator,
                    intent_validator,
                    post_holds=post_holds,
                )


def _seal_post_with_held_authorities(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    freeze_validator: Any,
    intent_validator: Any,
    *,
    post_holds: ExitStack | None = None,
) -> int:
    if post_holds is None:
        with ExitStack() as owned_post_holds:
            return _seal_post_with_held_authorities(
                freeze,
                intent,
                freeze_validator,
                intent_validator,
                post_holds=owned_post_holds,
            )

    def validate_authorities() -> None:
        freeze_validator()
        if validate_freeze_static(require_fresh_outputs=False) != freeze:
            raise GovernanceError("held seal-post freeze changed")
        intent_validator()
        if _load_exact_intent(freeze) != intent:
            raise GovernanceError("held seal-post publication intent changed")

    validate_authorities()
    if os.path.lexists(POST):
        raise GovernanceError("post namespace already contains evidence")
    with _held_published_result(intent) as snapshot:
        closeout, receipt, records, payload, _seals, validate_live = snapshot
        post = _build_post_from_held(freeze, intent, closeout, receipt, records, payload)
        post_validator: Any = None

        def held_validator() -> None:
            validate_live()
            validate_authorities()
            _validate_closeout_against_held_seals(
                closeout, intent, receipt, _seals
            )
            rebuilt = _build_post_from_held(
                freeze, intent, closeout, receipt, records, payload
            )
            if not _typed_tree_equal(rebuilt, post):
                raise GovernanceError("held post payload differs during commit")
            if post_validator is not None:
                post_validator()
            validate_live()

        def retain_post_after_unlink(
            parent_fd: int,
            name: str,
            staged_fd: int,
            linked_content: bytes,
        ) -> None:
            nonlocal post_validator
            if post_validator is not None:
                raise GovernanceError("post own-inode lease was acquired twice")
            if linked_content != _render_canonical_json(post):
                raise GovernanceError("linked post bytes differ before retention")
            staged_identity = os.fstat(staged_fd)
            linked_identity = os.stat(
                name, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                staged_identity.st_nlink != 1
                or linked_identity.st_nlink != 1
                or _stable_leaf_token(staged_identity)
                != _stable_leaf_token(linked_identity)
            ):
                raise GovernanceError(
                    "post link is not the sole transactional staged inode"
                )
            post_validator = post_holds.enter_context(
                _hold_existing_canonical_json_rooted(
                    ROOT,
                    POST,
                    post,
                    label="held published post seal",
                    expected_identity=staged_identity,
                )
            )
            post_validator()

        guards = [
            _workspace_record(FREEZE, "freeze"),
            _workspace_record(CORRECTED_SEAL, "corrected seal"),
            _workspace_record(Path(str(intent["intent_path_absolute"])), "publication intent"),
            _workspace_record(Path(str(intent["closeout_path_absolute"])), "publication closeout"),
        ]
        publisher.publish_json_transactional_rooted(
            ROOT,
            POST,
            post,
            guard_records=guards,
            validate=held_validator,
            retain_linked=retain_post_after_unlink,
        )
        if post_validator is None:
            raise GovernanceError(
                "post publisher returned without retained own-inode binding"
            )
        post_validator()
        p07gov.validate_self_hash(post, "post_hash", label="post seal")
        validate_live()
        validate_authorities()
        held_validator()
        return 0 if post["pass"] else 3


def seal_post() -> int:
    with _post_result_publication_semantics():
        return _seal_post_scoped()


def _check_post_scoped() -> int:
    freeze = validate_freeze_static(require_fresh_outputs=False)
    with _held_exact_json_authority(
        FREEZE, freeze, label="held check-post freeze"
    ) as freeze_validator:
        freeze_validator()
        if validate_freeze_static(require_fresh_outputs=False) != freeze:
            raise GovernanceError("held check-post freeze semantic identity differs")
        intent = _load_exact_intent(freeze)
        intent_path = Path(str(intent["intent_path_absolute"]))
        with _held_exact_json_authority(
            intent_path, intent, label="held check-post publication intent"
        ) as intent_validator:
            return _check_post_with_held_authorities(
                freeze, intent, freeze_validator, intent_validator
            )


def _check_post_with_held_authorities(
    freeze: Mapping[str, Any],
    intent: Mapping[str, Any],
    freeze_validator: Any,
    intent_validator: Any,
) -> int:
    def validate_authorities() -> None:
        freeze_validator()
        if validate_freeze_static(require_fresh_outputs=False) != freeze:
            raise GovernanceError("held check-post freeze changed")
        intent_validator()
        if _load_exact_intent(freeze) != intent:
            raise GovernanceError("held check-post publication intent changed")

    validate_authorities()
    post_bytes = publisher.read_bytes_bound_input_rooted(
        ROOT, POST, label="post seal retained bytes"
    )
    observed = p07gov._json_object_bytes(post_bytes, label="post seal")
    p07gov.validate_self_hash(observed, "post_hash", label="post seal")
    with publisher.retained_bound_input_validator(
        ROOT, POST, post_bytes, label="post seal"
    ) as post_validator:
        post_validator()
        validate_authorities()
        with _held_published_result(intent) as snapshot:
            closeout, receipt, records, payload, _seals, validate_live = snapshot
            post_validator()
            expected = _build_post_from_held(
                freeze, intent, closeout, receipt, records, payload
            )
            if not _typed_tree_equal(observed, expected):
                raise GovernanceError("post seal differs from held published snapshot")
            validate_live()
            post_validator()
            validate_authorities()
        post_validator()
        validate_authorities()
    return 0 if observed.get("pass") is True else 3


def check_post() -> int:
    with _post_result_publication_semantics():
        return _check_post_scoped()


def _current_contract_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
    input_records = {
        role: _workspace_record(path, f"input {role}") for role, path in INPUTS.items()
    }
    helper_records = {
        role: _workspace_record(path, f"helper {role}") for role, path in HELPERS.items()
    }
    python_record = _external_record(PYTHON, "python interpreter")
    vins_runtime = _vins_external_runtime_records()
    authority = _contract_authority(
        input_records, helper_records, python_record, vins_runtime
    )
    return input_records, helper_records, python_record, vins_runtime, authority


def _assert_reserved_outputs_absent(payload: Mapping[str, Any]) -> None:
    reserved = payload.get("reserved_paths")
    if not isinstance(reserved, Mapping) or set(reserved) != {
        "destination", "staging", "intent", "closeout", "post",
        "probe_intent", "probe_failure",
    }:
        raise GovernanceError("freeze reserved paths are malformed")
    for label, raw in reserved.items():
        path = Path(str(raw))
        if label == "probe_intent":
            if path != PROBE_INTENT or not os.path.lexists(path):
                raise GovernanceError("runtime probe launch intent is not retained")
            continue
        if os.path.lexists(path):
            raise GovernanceError(f"reserved namespace already contains evidence: {label}")


def write_freeze() -> int:
    if os.path.lexists(FREEZE):
        raise GovernanceError("freeze namespace already contains evidence")
    pre_inputs, pre_helpers, pre_python, pre_vins_runtime, pre_authority = _current_contract_inputs()
    for path in (
        *publication_paths(pre_authority["job_hash"]), OUTPUT, POST,
        PROBE_INTENT, PROBE_FAILURE,
    ):
        if os.path.lexists(path):
            raise GovernanceError(f"reserved namespace already contains evidence: {path}")
    with ExitStack() as retained:
        runtime = _capture_runtime_closure(retained)
        payload = build_freeze(runtime)
        if (
            payload["input_records"] != pre_inputs
            or payload["helper_code_closure"] != pre_helpers
            or payload["python_interpreter"] != pre_python
            or payload["vins_external_runtime"] != pre_vins_runtime
            or payload["publication_authority"] != pre_authority
        ):
            raise GovernanceError("code/input authority changed during runtime capture")
        _assert_reserved_outputs_absent(payload)
        guards = [
            *payload["input_records"].values(),
            *payload["helper_code_closure"].values(),
            payload["expected_runtime_closure"]["probe_launch_intent_record"],
        ]
        py = payload["python_interpreter"]
        lease = backend.SealedFileLease(
            PYTHON,
            str(py["sha256"]),
            role="freeze_python_interpreter",
            label="freeze transaction Python",
            expected_size_bytes=int(py["size_bytes"]),
        )
        retained.enter_context(lease)
        vins_leases = _retained_external_record_validators(
            retained, payload["vins_external_runtime"], label="freeze_vins_runtime"
        )
        runtime_holds = _retained_runtime_file_holds(
            retained,
            payload["expected_runtime_closure"]["runtime_receipt"],
            label="freeze retained runtime",
        )
        def freeze_transaction_validator() -> None:
            lease.verify_unchanged()
            _validate_retained_authority([], vins_leases)
            _validate_runtime_file_holds(runtime_holds)
            _static_authority_check()
            _validate_freeze_runtime_static(payload["expected_runtime_closure"], payload)
            _assert_reserved_outputs_absent(payload)
            current = _current_contract_inputs()
            if current != (
                pre_inputs, pre_helpers, pre_python, pre_vins_runtime, pre_authority
            ):
                raise GovernanceError("freeze contract authority drifted during commit")
            _validate_runtime_file_holds(runtime_holds)
            _validate_retained_authority([], vins_leases)
            lease.verify_unchanged()

        publisher.publish_json_transactional_rooted(
            ROOT,
            FREEZE,
            payload,
            guard_records=guards,
            validate=freeze_transaction_validator,
        )
        _validate_runtime_file_holds(runtime_holds)
        _validate_retained_authority([], vins_leases)
        lease.verify_unchanged()
    validate_freeze_static(require_fresh_outputs=True)
    return 0


def preview_contract() -> dict[str, Any]:
    _inputs, _helpers, _python, _vins_runtime, authority = _current_contract_inputs()
    staging, intent, closeout = publication_paths(authority["job_hash"])
    return {
        "mode": "READ_ONLY_CODE_AUTHORITATIVE_CONTRACT_PREVIEW",
        "freeze_capture_executed": False,
        "roles": list(ROLE_NAMES),
        "canonical_argv": {role: canonical_role_argv(role) for role in ROLE_NAMES},
        "environment_templates": {role: _environment_template(role) for role in ROLE_NAMES},
        "reserved_paths": [
            os.fspath(path) for path in (
                FREEZE, staging, intent, closeout, OUTPUT, POST,
                PROBE_INTENT, PROBE_FAILURE,
            )
        ],
        "outcome_boundary": dict(OUTCOME_BOUNDARY),
        "publication_authority": authority,
    }


def main() -> int:
    if __name__ == "__main__":
        _validate_outer_workspace_module_closure()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action",
        required=True,
        choices=("preview-contract", "write-freeze", "check-start", "run", "seal-post", "check-post"),
    )
    action = parser.parse_args().action
    if action == "preview-contract":
        print(json.dumps(preview_contract(), indent=2, sort_keys=True))
        return 0
    if action == "write-freeze":
        return write_freeze()
    if action == "check-start":
        validate_freeze_static(require_fresh_outputs=True)
        print("PASS_START")
        return 0
    if action == "run":
        return run_evaluation()
    if action == "seal-post":
        return seal_post()
    return check_post()


if __name__ == "__main__":
    try:
        _exit_code = main()
    except BaseException as error:
        if isinstance(error, SystemExit):
            _exit_code = int(error.code or 0)
        else:
            print(f"GOVERNANCE_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
            _exit_code = 2
    finally:
        try:
            _outer_post_action_guard()
        except BaseException as error:
            print(f"OUTER_GUARD_ERROR:{type(error).__name__}:{error}", file=sys.stderr)
            _exit_code = 2
        finally:
            if _OUTER_WORKSPACE_FINDER is not None:
                try:
                    _OUTER_WORKSPACE_FINDER.close()
                except BaseException as error:
                    print(
                        f"OUTER_GUARD_ERROR:{type(error).__name__}:{error}",
                        file=sys.stderr,
                    )
                    _exit_code = 2
    raise SystemExit(_exit_code)
