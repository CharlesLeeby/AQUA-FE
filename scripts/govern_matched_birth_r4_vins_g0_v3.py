#!/usr/bin/env python3
"""Write-once, post-result exploratory G0 evaluation for the frozen r4 pair.

This controller never launches a detector or VINS.  ``write-freeze`` is the
only action allowed to perform the representative runtime-closure probe.
``run`` starts exactly two evaluator roles (primary and verification), once
each and without retry.  ``seal-post`` and every check action are process-free.
"""
from __future__ import annotations

import argparse
import ast
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
 outcome=None
 try:
  exec(code,namespace,namespace)
 except SystemExit as caught:
  outcome=caught
finally:
 os.close(f)
if outcome is None:
 completion=namespace.get('_AQUAFE_G0_OUTER_ACTION_CLEAN_SUCCESS')
 if completion!={'action':a[1],'exit_code':0}:
  raise RuntimeError('formal G0 governor clean completion sentinel differs')
 exit_code=0
else:
 exit_code=outcome.code
 if exit_code is None:
  exit_code=0
 if type(exit_code) is not int:
  raise RuntimeError('formal G0 governor exit code is not an integer')
 if exit_code==0:
  raise RuntimeError('formal G0 caught SystemExit zero is not clean completion')
if exit_code==0 and a[1]=='write-freeze':
 commit=namespace.get('_AQUAFE_G0_FINAL_SUCCESS_COMMIT')
 if not isinstance(commit,dict) or set(commit)!={'path','content','sha256','mode','required_records','required_absent'}:
  raise RuntimeError('formal G0 final success commit is absent')
 content=commit['content']
 path=commit['path']
 if not isinstance(content,bytes) or not isinstance(path,str) or not os.path.isabs(path) or os.path.normpath(path)!=path or os.path.realpath(os.path.dirname(path))!=os.path.dirname(path) or commit['sha256']!=hashlib.sha256(content).hexdigest() or commit['mode']!=0o444:
  raise RuntimeError('formal G0 final success commit differs')
 required=commit['required_records']
 if not isinstance(required,list) or len(required)!=2:
  raise RuntimeError('formal G0 final success authority differs')
 for record in required:
  if not isinstance(record,dict) or set(record)!={'path','sha256','size_bytes'}:
   raise RuntimeError('formal G0 required success record differs')
  rp=record['path']
  rf=os.open(rp,os.O_RDONLY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0))
  try:
   rs=os.fstat(rf)
   chunks=[]
   offset=0
   while offset<rs.st_size:
    chunk=os.pread(rf,min(1048576,rs.st_size-offset),offset)
    if not chunk:
     raise RuntimeError('formal G0 required success record short read')
    chunks.append(chunk)
    offset+=len(chunk)
   named=os.lstat(rp)
   if not stat.S_ISREG(rs.st_mode) or rs.st_nlink!=1 or key(rs)!=key(named) or rs.st_size!=record['size_bytes'] or hashlib.sha256(b''.join(chunks)).hexdigest()!=record['sha256']:
    raise RuntimeError('formal G0 required success record identity differs')
  finally:
   os.close(rf)
 absent=commit['required_absent']
 if not isinstance(absent,list) or len(absent)!=1 or not isinstance(absent[0],str) or os.path.lexists(absent[0]):
  raise RuntimeError('formal G0 final success absence authority differs')
 sys.stdout.flush()
 sys.stderr.flush()
 parent=os.path.dirname(path)
 name=os.path.basename(path)
 d=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0))
 leaf=-1
 try:
  leaf=os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_CLOEXEC|getattr(os,'O_NOFOLLOW',0),0o444,dir_fd=d)
  offset=0
  while offset<len(content):
   wrote=os.write(leaf,content[offset:])
   if wrote<=0:
    raise RuntimeError('formal G0 final success short write')
   offset+=wrote
  os.fchmod(leaf,0o444)
  os.fsync(leaf)
  os.fsync(d)
  ls=os.fstat(leaf)
  named=os.stat(name,dir_fd=d,follow_symlinks=False)
  if key(ls)!=key(named) or not stat.S_ISREG(ls.st_mode) or ls.st_nlink!=1 or stat.S_IMODE(ls.st_mode)!=0o444 or os.pread(leaf,len(content)+1,0)!=content:
   raise RuntimeError('formal G0 final success publication differs')
 finally:
  if leaf>=0:
   os.close(leaf)
  os.close(d)
 os._exit(0)
if exit_code==0:
 raise SystemExit(0)
raise outcome
"""
_OUTER_CARRIER_BINDING = globals().get("_AQUAFE_G0_OUTER_BINDING")
_OUTER_LIVE_MAIN_CODE = sys._getframe(0).f_code
_OUTER_PYTHON = "/usr/bin/python3.8"
_OUTER_SCRIPT = "/home/ma/AQUA-FE_WS/scripts/govern_matched_birth_r4_vins_g0_v3.py"
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
_AQUAFE_G0_FINAL_SUCCESS_COMMIT: dict[str, object] | None = None
_AQUAFE_G0_OUTER_ACTION_CLEAN_SUCCESS: dict[str, object] | None = None


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
        auxiliary_sources: Mapping[str, str] | None = None,
    ) -> None:
        self.scripts_path = scripts_path
        self.main_loader: _OuterBoundSourceLoader | None = None
        self.loaders: dict[str, _OuterBoundSourceLoader] = {}
        self.auxiliary_loaders: dict[str, _OuterBoundSourceLoader] = {}
        try:
            self.main_loader = _OuterBoundSourceLoader("__main__", main_path)
            if self.main_loader.get_code("__main__") != _OUTER_LIVE_MAIN_CODE:
                raise RuntimeError("outer live main code differs from bound source bytes")
            for name, path in sources.items():
                self.loaders[name] = _OuterBoundSourceLoader(name, path)
            for name, path in (auxiliary_sources or {}).items():
                self.auxiliary_loaders[name] = _OuterBoundSourceLoader(name, path)
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
        for loader in self.auxiliary_loaders.values():
            loader.validate(require_loaded=False)

    def close(self) -> None:
        if self.main_loader is not None:
            self.main_loader.close()
        for loader in self.loaders.values():
            loader.close()
        for loader in self.auxiliary_loaders.values():
            loader.close()


_OUTER_WORKSPACE_FINDER: _OuterWorkspaceFinder | None = None
_OUTER_WORKSPACE_SOURCES = {
    name: f"{_OUTER_ROOT}/scripts/{leaf}"
    for name, leaf in (
        ("scripts.formal_g0_child_bootstrap_v1", "formal_g0_child_bootstrap_v1.py"),
        ("scripts.formal_g0_child_bootstrap_v2", "formal_g0_child_bootstrap_v2.py"),
        ("scripts.p07_backend_evaluation_v1", "p07_backend_evaluation_v1.py"),
        ("scripts.p07_backend_formal_io_v1", "p07_backend_formal_io_v1.py"),
        ("scripts.p07_backend_replay_common_v1", "p07_backend_replay_common_v1.py"),
        ("scripts.p07_g0_governance_v1", "p07_g0_governance_v1.py"),
        ("scripts.p07_g0_publisher_v1", "p07_g0_publisher_v1.py"),
        ("scripts.run_p07_g0_evaluation_v1", "run_p07_g0_evaluation_v1.py"),
    )
}
_OUTER_WORKSPACE_EXPECTED = {
    "scripts.formal_g0_child_bootstrap_v1": (
        "331d687f6249a3b7a87898237c542948beb456f8942f59531fa6f63875faeeb5",
        80_068,
    ),
    "scripts.formal_g0_child_bootstrap_v2": (
        "3073b474c4ba2f2b1323ae6fc2f4b8068c69b633367d14c723e9ebb8ec81cab1",
        88_835,
    ),
    "scripts.p07_backend_evaluation_v1": (
        "d4c34bb87a6b70aade822ce40627d3014bdbec90013e062a2df6941630f054e4",
        42_206,
    ),
    "scripts.p07_backend_formal_io_v1": (
        "ca6cefc3f3b959dce69f887bab8dbae2a391b90acf58bff1a2ee7412ba846876",
        21_016,
    ),
    "scripts.p07_backend_replay_common_v1": (
        "930fa2934d28155c3c063908afd151d80f5545e67aca3a135d405c87b4c683f0",
        138_671,
    ),
    "scripts.p07_g0_governance_v1": (
        "d0063c06eaf1267e4da0e9847ce432048d239eef6699e0b2a1178da6e5c340c3",
        138_170,
    ),
    "scripts.p07_g0_publisher_v1": (
        "97bd0b37a8c5c282f65f14a8a8fe05716f67bc88d378bf54e6640ce23baa0b3b",
        116_515,
    ),
    "scripts.run_p07_g0_evaluation_v1": (
        "5321688f65e5c2556858962571082c0662e8024bf332ce1c32e2fa8d0acc1213",
        35_196,
    ),
}
_OUTER_AUXILIARY_SOURCES = {
    "epoch_wrapper": f"{_OUTER_ROOT}/scripts/evaluate_vins_common_support_epoch_v2.py",
    "evaluator_base": f"{_OUTER_ROOT}/scripts/evaluate_vins_common_support.py",
    "trajectory_core": f"{_OUTER_ROOT}/scripts/trajectory_eval_core.py",
    "vins_runner": f"{_OUTER_ROOT}/scripts/run_aqualoc_archaeo_vins_eval.sh",
}
_OUTER_AUXILIARY_EXPECTED = {
    "epoch_wrapper": (
        "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91",
        5_447,
    ),
    "evaluator_base": (
        "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110",
        27_933,
    ),
    "trajectory_core": (
        "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635",
        27_945,
    ),
    "vins_runner": (
        "c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc",
        53_436,
    ),
}
_OUTER_LEGACY_BOOTSTRAP_SHA256, _OUTER_LEGACY_BOOTSTRAP_SIZE = (
    _OUTER_WORKSPACE_EXPECTED["scripts.formal_g0_child_bootstrap_v1"]
)


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
        _OUTER_AUXILIARY_SOURCES,
    )
    if set(finder.loaders) != set(_OUTER_WORKSPACE_EXPECTED):
        finder.close()
        raise RuntimeError("outer workspace executable allowlist differs")
    if set(finder.auxiliary_loaders) != set(_OUTER_AUXILIARY_EXPECTED):
        finder.close()
        raise RuntimeError("outer auxiliary executable allowlist differs")
    for name, (sha256, size_bytes) in _OUTER_WORKSPACE_EXPECTED.items():
        if finder.loaders[name].bound_record != {
            "path": _OUTER_WORKSPACE_SOURCES[name],
            "sha256": sha256,
            "size_bytes": size_bytes,
        }:
            finder.close()
            raise RuntimeError(
                f"outer workspace source hard authority differs: {name}"
            )
    for name, (sha256, size_bytes) in _OUTER_AUXILIARY_EXPECTED.items():
        if finder.auxiliary_loaders[name].bound_record != {
            "path": _OUTER_AUXILIARY_SOURCES[name],
            "sha256": sha256,
            "size_bytes": size_bytes,
        }:
            finder.close()
            raise RuntimeError(
                f"outer auxiliary source hard authority differs: {name}"
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

from scripts import formal_g0_child_bootstrap_v1 as legacy_bootstrap
from scripts import formal_g0_child_bootstrap_v2 as bootstrap
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
        "scripts.formal_g0_child_bootstrap_v2": ROOT / "scripts/formal_g0_child_bootstrap_v2.py",
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


FREEZE_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-freeze-v4"
BOUND_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-bound-summary-v4"
PROCESS_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-process-role-v4"
LAUNCH_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-launch-intent-v3"
PROBE_LAUNCH_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-launch-intent-v3"
PROBE_FAILURE_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-failure-receipt-v3"
PROBE_SUCCESS_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-success-closeout-v3"
POST_SCHEMA = "aqua-fe-matched-birth-r4-vins-g0-post-seal-v4"
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
_DEFERRED_FREEZE_STACK: ExitStack | None = None


class _DeferrableExitStack(ExitStack):
    """An ExitStack whose exact object can be handed to the outer finalizer."""

    def __init__(self) -> None:
        super().__init__()
        self.deferred = False

    def defer_to_outer(self) -> None:
        if self.deferred:
            raise GovernanceError("freeze transaction stack was deferred twice")
        self.deferred = True

    def __exit__(self, *details: object) -> bool:
        if self.deferred:
            return False
        return bool(super().__exit__(*details))


def _finish_deferred_freeze_stack(error: BaseException | None) -> None:
    """Finish formal write-freeze holds only after the outer final checkpoint."""

    global _DEFERRED_FREEZE_STACK
    targets = _spawn_target_signals()
    previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, targets)
    first_close_error: BaseException | None = None
    try:
        stack = _DEFERRED_FREEZE_STACK
        if stack is None:
            return
        if isinstance(stack, _DeferrableExitStack):
            stack.deferred = False
        effective = error
        while True:
            try:
                if effective is None:
                    stack.close()
                else:
                    stack.__exit__(
                        type(effective), effective, effective.__traceback__
                    )
            except BaseException as close_error:
                if first_close_error is None:
                    first_close_error = close_error
                effective = close_error
                # ExitStack normally drains every callback even when one
                # raises.  A trace/injected BaseException can interrupt its
                # own dispatcher between callbacks; in that case, re-enter
                # the exact still-owned stack while target signals remain
                # blocked.
                if getattr(stack, "_exit_callbacks", ()):  # contextlib state
                    continue
            break
        if getattr(stack, "_exit_callbacks", ()):
            raise GovernanceError("deferred freeze stack did not fully drain")
        _DEFERRED_FREEZE_STACK = None
        if first_close_error is not None:
            raise first_close_error
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)

FREEZE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v3.json"
POST = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v3.json"
OUTPUT = ROOT / "papers/litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r3"
PROBE_INTENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v3.json"
PROBE_FAILURE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v3.json"
PROBE_SUCCESS = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_success_closeout_v3.json"
INCIDENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_g0_v3_runtime_alias_incident_v1.json"
INCIDENT_HUMAN = INCIDENT.with_suffix(".md")
INCIDENT_BUILDER = ROOT / "scripts/build_a02_matched_birth_r4_vins_g0_runtime_alias_incident_v1.py"
V2_GOVERNOR = ROOT / "scripts/govern_matched_birth_r4_vins_g0_v2.py"
V2_INCIDENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_g0_v2_adoption_incident_v1.json"
V2_FREEZE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v2.json"
V2_PROBE_INTENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v2.json"
V2_PROBE_FAILURE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v2.json"
V2_PROBE_SUCCESS = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_success_closeout_v2.json"
V2_POST = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v2.json"
V2_RESULT = ROOT / "papers/litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r2"
V1_RESULT = ROOT / "papers/litcmp_a02_4500_6300_common_support/formal900_r4_xfeatbirth_vs_gfttbirth_r1"
V1_JOB_HASH = "c51e1b38696ca9365bedf42aee2a2a734d2994cc5b5866930cf72a425e0612ec"
V1_PROBE_INTENT = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_launch_intent_v1.json"
V1_FREEZE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_freeze_v1.json"
V1_PROBE_FAILURE = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_runtime_probe_failure_receipt_v1.json"
V1_POST = ROOT / "papers/a02_4500_6300_matched_birth_formal900_r4_vins_eval_seal_v1.json"
V1_STAGING, V1_PUBLICATION_INTENT, V1_PUBLICATION_CLOSEOUT = (
    publisher.publication_paths(V1_RESULT, job_hash=V1_JOB_HASH)
)
V2_JOB_HASH = "48f29b21b4e9d31409a15fcf93458bc1309fb8a5b5d674c1d90d349f8ab862b2"
V2_STAGING, V2_PUBLICATION_INTENT, V2_PUBLICATION_CLOSEOUT = (
    publisher.publication_paths(V2_RESULT, job_hash=V2_JOB_HASH)
)
V2_GOVERNOR_SHA256 = "8c738362a7aee9adacd22c182a330a16df7c08ce253b36b2643e6451718c0fb9"
V2_GOVERNOR_SIZE = 296_051

INCIDENT_BUILDER_SHA256 = "91ad304e3c7107b467889cefc773360a190a03a4b5ef7ae73c2a585ea8c70896"
INCIDENT_BUILDER_SIZE = 111_097
# Frozen below after extracting the one top-level literal from the pinned source.
INCIDENT_BUILDER_CARRIER_SHA256 = "66b8bca3d5fa41bf9e65e3ebd329c5a143fd2c3ebea157e95ecfc9ff666a604c"
INCIDENT_BUILDER_CARRIER_SIZE = 11_561
INCIDENT_HUMAN_SHA256 = "70420b0d28b3f6de887ff594d7262f85bf7b27c342d6a2cb82564cfdd8913204"
INCIDENT_HUMAN_SIZE = 8_619
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

BOOTSTRAP = ROOT / "scripts/formal_g0_child_bootstrap_v2.py"
LEGACY_BOOTSTRAP = ROOT / "scripts/formal_g0_child_bootstrap_v1.py"
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
BOOTSTRAP_SHA256 = "3073b474c4ba2f2b1323ae6fc2f4b8068c69b633367d14c723e9ebb8ec81cab1"
BOOTSTRAP_SIZE = 88_835
LEGACY_BOOTSTRAP_SHA256 = _OUTER_LEGACY_BOOTSTRAP_SHA256
LEGACY_BOOTSTRAP_SIZE = _OUTER_LEGACY_BOOTSTRAP_SIZE
CHILD_PYTHON_OPTIONS = ["-I", "-B"]
CHILD_BOOTSTRAP_INDEX = 1 + len(CHILD_PYTHON_OPTIONS)
EXPECTED_CHILD_STDERR = (
    b"Failed to load Python extension for LZ4 support. "
    b"LZ4 compression will not be available.\n"
)
EXPECTED_CHILD_STDERR_SHA256 = "857f79ad98b5d842b860470a6675d7aeaa1d7ad4a7181b1c3966e7e9bd9c3fff"
EXPECTED_CHILD_STDERR_SIZE = 88
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


JOB_ID = "matched_birth_r4_vins_g0_v3"


def _contract_authority(
    input_records: Mapping[str, Any],
    helper_records: Mapping[str, Any],
    python_record: Mapping[str, Any],
    vins_runtime_records: Mapping[str, Any],
) -> dict[str, str]:
    plan_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-plan-contract-v3",
        "contrast": CONTRAST,
        "roles": list(ROLE_NAMES),
        "protocol": _protocol(),
        "outcome_boundary": OUTCOME_BOUNDARY,
        "publication_technical_boundary": PUBLICATION_TECHNICAL_BOUNDARY,
    }
    plan_hash = hashlib.sha256(_canonical_json_bytes(plan_contract)).hexdigest()
    backend_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-backend-contract-v3",
        "helper_code_closure": dict(helper_records),
        "python_interpreter": dict(python_record),
        "vins_external_runtime": dict(vins_runtime_records),
        "authorized_environment_templates": {
            role: _environment_template(role) for role in ROLE_NAMES
        },
    }
    backend_hash = hashlib.sha256(_canonical_json_bytes(backend_contract)).hexdigest()
    job_contract = {
        "schema_version": "aqua-fe-matched-birth-r4-g0-job-contract-v3",
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


_INCIDENT_STATIC_HELPERS_V1 = {
    "backend": ("930fa2934d28155c3c063908afd151d80f5545e67aca3a135d405c87b4c683f0", 138_671),
    "backend_evaluation": ("d4c34bb87a6b70aade822ce40627d3014bdbec90013e062a2df6941630f054e4", 42_206),
    "child_bootstrap": (BOOTSTRAP_SHA256, BOOTSTRAP_SIZE),
    "epoch_wrapper": ("3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91", 5_447),
    "evaluator_base": ("ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110", 27_933),
    "formal_io": ("ca6cefc3f3b959dce69f887bab8dbae2a391b90acf58bff1a2ee7412ba846876", 21_016),
    "p07_governance": ("d0063c06eaf1267e4da0e9847ce432048d239eef6699e0b2a1178da6e5c340c3", 138_170),
    "publisher": ("97bd0b37a8c5c282f65f14a8a8fe05716f67bc88d378bf54e6640ce23baa0b3b", 116_515),
    "runner": ("5321688f65e5c2556858962571082c0662e8024bf332ce1c32e2fa8d0acc1213", 35_196),
    "trajectory_core": ("aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635", 27_945),
    "vins_runner": ("c3bdb181fb4a0f9ef457f9dd0f7cffd4b1a79c8ed8dc2e529d62f02c9f98a1cc", 53_436),
}
_INCIDENT_STATIC_HELPER_PATHS_V1 = {
    key: os.fspath(path.relative_to(ROOT)) for key, path in HELPERS.items()
    if key != "governor"
}


def _incident_record(path: Path, sha256: str, size_bytes: int) -> dict[str, object]:
    return {
        "path": os.fspath(path.relative_to(ROOT)),
        "sha256": sha256,
        "size_bytes": size_bytes,
    }


def _v2_legacy_incident_adoption_namespace_contract_v1_unused(
    successor_sha256: str, successor_size_bytes: int
) -> dict[str, object]:
    """Pure successor namespace authority; it opens no scientific input file."""

    if (
        re.fullmatch(r"[0-9a-f]{64}", successor_sha256) is None
        or isinstance(successor_size_bytes, bool)
        or not isinstance(successor_size_bytes, int)
        or successor_size_bytes <= 0
    ):
        raise GovernanceError("incident successor governor identity differs")
    inputs: dict[str, dict[str, object]] = {
        "corrected_seal": _incident_record(CORRECTED_SEAL, CORRECTED_SEAL_SHA256, CORRECTED_SEAL_SIZE),
        "reference_bag": _incident_record(RAW_BAG, RAW_BAG_SHA256, RAW_BAG_SIZE),
        "reference_bag_manifest": _incident_record(REFERENCE_BAG_MANIFEST, REFERENCE_BAG_MANIFEST_SHA256, REFERENCE_BAG_MANIFEST_SIZE),
        "config": _incident_record(CONFIG, CONFIG_SHA256, CONFIG_SIZE),
        "config_sealed_authority": _incident_record(CONFIG_SEALED_AUTHORITY, CONFIG_SEALED_AUTHORITY_SHA256, CONFIG_SEALED_AUTHORITY_SIZE),
        "epoch_lock": _incident_record(EPOCH_LOCK, EPOCH_LOCK_FILE_SHA256, 4_446),
        "protocol_doc": _incident_record(PROTOCOL_DOC, "d3ae583ca799ef423054a5b9ece8b53e0000a8d3bbb1ea8c50121f7a60a40816", 7_036),
        "xfeat_feature_bag": _incident_record(XFEAT_FEATURE_BAG, XFEAT_FEATURE_SHA256, 27_396_366),
        "gftt_feature_bag": _incident_record(GFTT_FEATURE_BAG, GFTT_FEATURE_SHA256, 27_388_430),
    }
    for arm, vio in (("xfeat", XFEAT_VIO), ("gftt", GFTT_VIO)):
        authority = VINS_PROVENANCE_AUTHORITY[arm]
        sha, size = authority["vio_csv"]
        inputs[f"{arm}_vio"] = _incident_record(vio, sha, size)
        run = XFEAT_RUN if arm == "xfeat" else GFTT_RUN
        for leaf, key in (
            ("replay_manifest.txt", "replay_manifest_txt"),
            ("vins_env_manifest.txt", "vins_env_manifest_txt"),
            ("aqualoc_archaeo02_pinhole.yaml", "aqualoc_archaeo02_pinhole_yaml"),
            ("vins_aqualoc_archaeo_external.yaml", "vins_aqualoc_archaeo_external_yaml"),
            ("vins.log", "vins_log"),
        ):
            sha, size = authority[key]
            inputs[f"{arm}_{leaf.replace('.', '_')}"] = _incident_record(run / leaf, sha, size)
    helpers = {
        key: {
            "path": _INCIDENT_STATIC_HELPER_PATHS_V1[key],
            "sha256": identity[0],
            "size_bytes": identity[1],
        }
        for key, identity in _INCIDENT_STATIC_HELPERS_V1.items()
    }
    helpers["governor"] = {
        "path": "scripts/govern_matched_birth_r4_vins_g0_v2.py",
        "sha256": successor_sha256,
        "size_bytes": successor_size_bytes,
    }
    python_record = {
        "path": "/usr/bin/python3.8",
        "sha256": "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
        "size_bytes": 5_490_456,
    }
    vins_runtime = {
        "vins_binary": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["vins_binary"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["vins_binary"]["sha256"], "size_bytes": 13_104_360},
        "vins_library": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["vins_library"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["vins_library"]["sha256"], "size_bytes": 165_207_064},
        "camera_models_library": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["camera_models_library"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["camera_models_library"]["sha256"], "size_bytes": 2_970_640},
    }
    authority = _contract_authority(inputs, helpers, python_record, vins_runtime)
    staging, intent, closeout = publication_paths(authority["job_hash"])
    result: dict[str, object] = {
        "schema_version": "aqua-fe-matched-birth-r4-vins-g0-v2-incident-namespace-contract-v1",
        "successor_governor": {"path": "scripts/govern_matched_birth_r4_vins_g0_v2.py", "sha256": successor_sha256, "size_bytes": successor_size_bytes},
        "job_id": JOB_ID,
        "job_hash": authority["job_hash"],
        "destination": os.fspath(OUTPUT),
        "staging": os.fspath(staging),
        "intent": os.fspath(intent),
        "closeout": os.fspath(closeout),
        "freeze": os.fspath(FREEZE),
        "post": os.fspath(POST),
        "probe_intent": os.fspath(PROBE_INTENT),
        "probe_failure": os.fspath(PROBE_FAILURE),
        "probe_success": os.fspath(PROBE_SUCCESS),
    }
    return result


def _legacy_required_absences() -> tuple[Path, ...]:
    staging, intent, closeout = publisher.publication_paths(
        OLD_RESULT, job_hash=OLD_JOB_HASH
    )
    return (
        OLD_FREEZE, OLD_PROBE_FAILURE, OLD_RESULT, OLD_POST,
        staging, intent, closeout,
    )


def _validate_consumed_v1_intent(value: object) -> dict[str, Any]:
    keys = {
        "schema_version", "status", "attempt_count",
        "authorized_process_start_count", "no_retry_after_pending_evidence",
        "timeout_seconds", "authorized_canonical_argv", "actual_procfd_argv",
        "actual_environment", "actual_environment_sha256", "pass_fd_numbers",
        "spawn_signal_policy", "probe_source", "intent_path", "failure_path",
        "probe_launch_intent_hash",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise GovernanceError("consumed v1 intent field set differs")
    intent = dict(value)
    expected_canonical = [
        os.fspath(PYTHON), "-I", "-B", os.fspath(BOOTSTRAP),
        bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
    ]
    expected_actual = [
        "/proc/self/fd/12", "-I", "-B", "/proc/self/fd/13",
        bootstrap.PROBE_ARGUMENT, "/proc/self/fd/17", REFERENCE_TOPIC,
    ]
    expected_environment = {
        "AQUAFE_FORMAL_G0_BASE_FD": "/proc/self/fd/15",
        "AQUAFE_FORMAL_G0_CORE_FD": "/proc/self/fd/16",
        "AQUAFE_FORMAL_G0_ROLE": "runtime_probe",
        "AQUAFE_FORMAL_G0_WRAPPER_FD": "/proc/self/fd/14",
        "AQUAFE_P07_SEALED_EVALUATOR_BASE": "/proc/self/fd/15",
        "AQUAFE_P07_SEALED_EVALUATOR_CORE": "/proc/self/fd/16",
        "HOME": "/home/ma", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "LOGNAME": "ma", "MKL_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1", "SHELL": "/bin/bash", "USER": "ma",
    }
    expected_source = {
        "base": {"path": "scripts/evaluate_vins_common_support.py", "sha256": "ab6f2b5c1a10a41463657edee2724c022fc0248dc885096acb336e602384c110", "size_bytes": 27_933},
        "bootstrap": {"path": "scripts/formal_g0_child_bootstrap_v1.py", "sha256": BOOTSTRAP_SHA256, "size_bytes": BOOTSTRAP_SIZE},
        "core": {"path": "scripts/trajectory_eval_core.py", "sha256": "aa9ac4da81df7298d1f1c369548ca98a57235916004337cad66f4cf331560635", "size_bytes": 27_945},
        "python": {"path": os.fspath(PYTHON), "sha256": "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06", "size_bytes": 5_490_456},
        "reference_bag": {"path": "datasets/aqualoc/rosbags/archaeo02_4500_6300.bag", "sha256": RAW_BAG_SHA256, "size_bytes": RAW_BAG_SIZE},
        "wrapper": {"path": "scripts/evaluate_vins_common_support_epoch_v2.py", "sha256": "3c455299b23157cc749b474b9460ca4a408b3bee516e9d1bf2109f253cf89f91", "size_bytes": 5_447},
    }
    if (
        intent.get("schema_version") != PROBE_LAUNCH_SCHEMA.replace("-v2", "-v1")
        or intent.get("status") != "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY"
        or intent.get("attempt_count") != 1
        or intent.get("authorized_process_start_count") != 1
        or intent.get("no_retry_after_pending_evidence") is not True
        or intent.get("timeout_seconds") != RUNTIME_PROBE_TIMEOUT_SECONDS
        or intent.get("authorized_canonical_argv") != expected_canonical
        or intent.get("actual_procfd_argv") != expected_actual
        or intent.get("actual_environment") != expected_environment
        or intent.get("actual_environment_sha256")
        != hashlib.sha256(_canonical_json_bytes(expected_environment)).hexdigest()
        or intent.get("pass_fd_numbers") != [12, 13, 14, 15, 16, 17]
        or intent.get("spawn_signal_policy") != _spawn_signal_policy()
        or intent.get("probe_source") != expected_source
        or intent.get("intent_path") != os.fspath(OLD_PROBE_INTENT)
        or intent.get("failure_path") != os.fspath(OLD_PROBE_FAILURE)
    ):
        raise GovernanceError("consumed v1 intent semantics differ")
    p07gov.validate_self_hash(
        intent, "probe_launch_intent_hash", label="consumed v1 probe intent"
    )
    return intent


def _incident_intent_semantics(intent: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "attempt_count": intent["attempt_count"],
        "authorized_process_start_count": intent["authorized_process_start_count"],
        "no_retry_after_pending_evidence": intent["no_retry_after_pending_evidence"],
        "status": intent["status"],
    }


def _incident_builder_carrier_source() -> str:
    """Extract the carrier literal from the hard-pinned builder source."""

    source = INCIDENT_BUILDER.read_bytes()
    if (
        len(source) != INCIDENT_BUILDER_SIZE
        or hashlib.sha256(source).hexdigest() != INCIDENT_BUILDER_SHA256
    ):
        raise GovernanceError("incident builder hard authority differs")
    try:
        tree = ast.parse(source, filename=os.fspath(INCIDENT_BUILDER), mode="exec")
    except (SyntaxError, ValueError) as error:
        raise GovernanceError("incident builder source cannot be parsed") from error
    matches: list[str] = []
    for statement in tree.body:
        if (
            isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "_CARRIER_SOURCE"
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            matches.append(statement.value.value)
    if len(matches) != 1:
        raise GovernanceError("incident builder carrier authority differs")
    carrier = matches[0]
    encoded = carrier.encode("utf-8")
    if (
        len(encoded) != INCIDENT_BUILDER_CARRIER_SIZE
        or hashlib.sha256(encoded).hexdigest() != INCIDENT_BUILDER_CARRIER_SHA256
    ):
        raise GovernanceError("incident builder carrier literal differs")
    return carrier


def _validate_incident_adoption_v2_legacy_unused(
    value: object, *, old_intent: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    top = {
        "schema_version", "status", "scientific_role", "incident_class",
        "builder_identity", "builder_execution_contract", "human_record",
        "retained_v1_evidence", "static_control_flow_diagnosis",
        "retained_code_authorities", "successor_authorization",
        "outcome_firewall", "claim_boundary", "incident_hash",
    }
    if not isinstance(value, Mapping) or set(value) != top:
        raise GovernanceError("incident adoption top-level field set differs")
    incident = dict(value)
    consumed_intent = _validate_consumed_v1_intent(
        _load_json_static(OLD_PROBE_INTENT, "consumed v1 probe intent")
        if old_intent is None else old_intent
    )
    if (
        incident.get("schema_version")
        != "aqua-fe-matched-birth-r4-vins-g0-probe-stderr-incident-adoption-v1"
        or incident.get("status")
        != "ADOPTED_CONSUMED_V1_PROBE_INTENT_FOR_ONE_REPAIRED_V2_NAMESPACE"
        or incident.get("scientific_role")
        != "POST_INCIDENT_INFRASTRUCTURE_RECOVERY_NO_OUTCOME_SELECTION"
        or incident.get("incident_class")
        != "RUNTIME_PROBE_STDERR_GATE_FAILURE_RECEIPT_FALSE_NEGATIVE"
    ):
        raise GovernanceError("incident adoption schema/status differs")
    incident_clone = dict(incident)
    incident_clone["incident_hash"] = "0" * 64
    expected_incident_hash = hashlib.sha256(
        json.dumps(
            incident_clone, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True, allow_nan=False,
        ).encode("ascii") + b"\n"
    ).hexdigest()
    if incident.get("incident_hash") != expected_incident_hash:
        raise GovernanceError("incident adoption self-hash differs")
    successor = incident.get("successor_authorization")
    successor_keys = {
        "sole_governor", "v2_job_hash", "exact_namespace",
        "successor_namespace_contract",
        "stderr_allowlist_for_future_v2_probe",
        "all_other_stderr_is_terminal_failure",
        "visible_intent_without_exact_success_closeout_consumes_namespace_and_forbids_retry_or_continuation",
        "success_closeout_required_before_later_actions",
        "failure_receipt_is_best_effort_additive_not_retry_authority",
        "terminal_evidence_boundary",
        "old_v1_namespace_retry_or_mutation_authorized",
        "detector_or_feature_export_rerun_authorized", "vins_rerun_authorized",
        "scientific_or_evaluation_contract_change_authorized",
        "authorized_successor_evaluation_namespace_count",
        "authorized_action_sequence",
    }
    if not isinstance(successor, Mapping) or set(successor) != successor_keys:
        raise GovernanceError("incident successor authorization field set differs")
    sole = successor.get("sole_governor")
    if not isinstance(sole, Mapping) or set(sole) != {"path", "sha256", "size_bytes"}:
        raise GovernanceError("incident sole successor identity differs")
    live_governor = _workspace_record(Path(_OUTER_SCRIPT), "incident successor governor")
    live_governor["path"] = _OUTER_SCRIPT
    if dict(sole) != live_governor:
        raise GovernanceError("incident successor does not bind loaded governor")
    namespace = incident_adoption_namespace_contract_v1(
        str(sole["sha256"]), int(sole["size_bytes"])
    )
    expected_namespace = {
        "incident": os.fspath(INCIDENT),
        "freeze": namespace["freeze"],
        "probe_intent": namespace["probe_intent"],
        "probe_failure": namespace["probe_failure"],
        "probe_success": namespace["probe_success"],
        "result": namespace["destination"],
        "post": namespace["post"],
        "staging": namespace["staging"],
        "publication_intent": namespace["intent"],
        "publication_closeout": namespace["closeout"],
    }
    if (
        successor.get("v2_job_hash") != namespace["job_hash"]
        or successor.get("successor_namespace_contract") != namespace
        or successor.get("exact_namespace") != expected_namespace
        or successor.get("stderr_allowlist_for_future_v2_probe")
        != _child_stderr_contract()["allowed"]
        or successor.get("all_other_stderr_is_terminal_failure") is not True
        or successor.get("visible_intent_without_exact_success_closeout_consumes_namespace_and_forbids_retry_or_continuation") is not True
        or successor.get("success_closeout_required_before_later_actions") is not True
        or successor.get("failure_receipt_is_best_effort_additive_not_retry_authority") is not True
        or successor.get("terminal_evidence_boundary") != {
            "coverage":
                "FAIL_CLOSED_BY_VISIBLE_INTENT_WITHOUT_EXACT_SUCCESS_CLOSEOUT;RECEIPT_ONLY_WHEN_PARENT_OBSERVES_AND_COMMIT_SUCCEEDS",
            "unobservable_or_uncommittable_exclusions": [
                "SIGKILL", "SIGSTOP", "PROCESS_CRASH", "POWER_LOSS",
                "KERNEL_FAILURE", "STORAGE_FAILURE", "SIGNAL_API_FAILURE",
                "FAILURE_RECEIPT_WRITE_OR_FSYNC_FAILURE",
            ],
            "failure_receipt_io_failure_fallback":
                "VISIBLE_INTENT_ALONE_CONSUMES_NAMESPACE_NO_RETRY",
            "failure_receipt_durability_unconditional_claimed": False,
        }
        or successor.get("old_v1_namespace_retry_or_mutation_authorized") is not False
        or successor.get("detector_or_feature_export_rerun_authorized") is not False
        or successor.get("vins_rerun_authorized") is not False
        or successor.get("scientific_or_evaluation_contract_change_authorized") is not False
        or successor.get("authorized_successor_evaluation_namespace_count") != 1
        or successor.get("authorized_action_sequence")
        != ["write-freeze", "check-start", "run", "seal-post", "check-post"]
    ):
        raise GovernanceError("incident successor authorization differs")
    expected_builder_execution = {
        "working_directory": os.fspath(ROOT),
        "environment": {
            "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma",
            "SHELL": "/bin/bash",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "authorized_write_once_argv": [
            os.fspath(PYTHON), "-I", "-B", "-c",
            _incident_builder_carrier_source(),
            os.fspath(INCIDENT_BUILDER), INCIDENT_BUILDER_SHA256,
            "--action", "write-once",
            "--successor-governor-sha256", str(sole["sha256"]),
            "--successor-governor-size-bytes", str(sole["size_bytes"]),
            "--v2-job-hash", str(namespace["job_hash"]),
        ],
        "scientific_evaluator_detector_vins_process_start_count": 0,
        "builder_process_is_publication_control_plane_only": True,
        "publication":
            "O_TMPFILE_HELD_INODE_0444_FILE_FSYNC_HIDDEN_LINK_DIR_FSYNC_RENAMEAT2_NOREPLACE",
        "commit_linearization":
            "O_TMPFILE_HIDDEN_LINK_FSYNC_RENAMEAT2_NOREPLACE",
        "active_same_uid_namespace_adversary_out_of_scope": True,
    }
    if incident.get("builder_execution_contract") != expected_builder_execution:
        raise GovernanceError("incident builder execution contract differs")
    retained = incident.get("retained_v1_evidence")
    retained_keys = {
        "runtime_probe_launch_intent", "intent_semantics", "required_absences",
        "failure_receipt_missing", "stdout_bytes_recoverable",
        "stderr_bytes_recoverable",
    }
    old_stat = os.stat(OLD_PROBE_INTENT, follow_symlinks=False)
    old_record = {
        "path": os.fspath(OLD_PROBE_INTENT),
        "sha256": OLD_PROBE_INTENT_SHA256,
        "size_bytes": OLD_PROBE_INTENT_SIZE,
        "device_id": int(old_stat.st_dev),
        "inode": int(old_stat.st_ino),
        "mode_octal": format(stat.S_IMODE(old_stat.st_mode), "04o"),
        "uid": int(old_stat.st_uid),
        "nlink": int(old_stat.st_nlink),
    }
    if (
        not isinstance(retained, Mapping)
        or set(retained) != retained_keys
        or retained.get("runtime_probe_launch_intent") != old_record
        or retained.get("intent_semantics")
        != _incident_intent_semantics(consumed_intent)
        or retained.get("failure_receipt_missing") is not True
        or retained.get("stdout_bytes_recoverable") is not False
        or retained.get("stderr_bytes_recoverable") is not False
        or retained.get("required_absences")
        != [os.fspath(path) for path in _legacy_required_absences()]
    ):
        raise GovernanceError("incident retained v1 evidence differs")
    old_governor_record = {
        "path": os.fspath(ROOT / "scripts/govern_matched_birth_r4_vins_g0_v1.py"),
        "sha256": "afe10ee7ab413163be0ed208c6d62b7f906327b316a5e46bc9ec2aa882579de0",
        "size_bytes": 233_604,
    }
    expected_diagnosis = {
        "authority": old_governor_record,
        "classification": "MECHANICALLY_CHECKED_STATIC_CONTROL_FLOW_DEFECT",
        "facts": [
            "capture_returns_before_late_freeze_runtime_static_validation",
            "failure_receipt_backfill_is_scoped_inside_capture",
            "late_nonempty_stderr_rejection_is_outside_that_backfill_scope",
        ],
        "operator_observed_unsealed_diagnostic": {
            "text": "runtime probe emitted stderr",
            "classification": "OPERATOR_OBSERVED_UNSEALED_NOT_ORIGINAL_STREAM_BYTES",
            "roslz4_explanation": "INFERENCE_ONLY_NOT_A_V1_BYTE_CLAIM",
        },
    }
    if incident.get("static_control_flow_diagnosis") != expected_diagnosis:
        raise GovernanceError("incident static control-flow diagnosis differs")
    expected_code_authorities = {
        "v1_governor": old_governor_record,
        "child_bootstrap": {"path": os.fspath(BOOTSTRAP), "sha256": BOOTSTRAP_SHA256, "size_bytes": BOOTSTRAP_SIZE},
        "backend": {"path": os.fspath(ROOT / "scripts/p07_backend_replay_common_v1.py"), "sha256": "930fa2934d28155c3c063908afd151d80f5545e67aca3a135d405c87b4c683f0", "size_bytes": 138_671},
        "backend_evaluation": {"path": os.fspath(ROOT / "scripts/p07_backend_evaluation_v1.py"), "sha256": "d4c34bb87a6b70aade822ce40627d3014bdbec90013e062a2df6941630f054e4", "size_bytes": 42_206},
        "formal_io": {"path": os.fspath(ROOT / "scripts/p07_backend_formal_io_v1.py"), "sha256": "ca6cefc3f3b959dce69f887bab8dbae2a391b90acf58bff1a2ee7412ba846876", "size_bytes": 21_016},
        "p07_governance": {"path": os.fspath(ROOT / "scripts/p07_g0_governance_v1.py"), "sha256": "d0063c06eaf1267e4da0e9847ce432048d239eef6699e0b2a1178da6e5c340c3", "size_bytes": 138_170},
        "retained_publisher": {"path": os.fspath(ROOT / "scripts/p07_g0_publisher_v1.py"), "sha256": "97bd0b37a8c5c282f65f14a8a8fe05716f67bc88d378bf54e6640ce23baa0b3b", "size_bytes": 116_515},
        "runner": {"path": os.fspath(ROOT / "scripts/run_p07_g0_evaluation_v1.py"), "sha256": "5321688f65e5c2556858962571082c0662e8024bf332ce1c32e2fa8d0acc1213", "size_bytes": 35_196},
    }
    if incident.get("retained_code_authorities") != expected_code_authorities:
        raise GovernanceError("incident retained code authorities differ")
    for role, expected in expected_code_authorities.items():
        path = Path(str(expected["path"]))
        observed = _workspace_record(path, f"incident retained code {role}")
        observed["path"] = os.fspath(path)
        if observed != expected:
            raise GovernanceError(f"incident retained code live identity differs: {role}")
    expected_outcome_firewall = {
        "vio_metric_files_read": False,
        "trajectory_values_read_or_recorded": False,
        "arm_relative_result_available_to_builder": False,
        "result_conditioned_successor_selection": False,
    }
    if incident.get("outcome_firewall") != expected_outcome_firewall:
        raise GovernanceError("incident outcome firewall differs")
    expected_claim_boundary = {
        "v1_failure_receipt_reconstructed": False,
        "v1_stdout_or_stderr_content_claimed": False,
        "v1_freeze_pass_claimed": False,
        "scientific_outcome_claimed": False,
        "v2_is_additive_post_incident_exploratory": True,
    }
    if incident.get("claim_boundary") != expected_claim_boundary:
        raise GovernanceError("incident claim boundary differs")
    builder_record = _workspace_record(INCIDENT_BUILDER, "incident builder")
    if (
        builder_record.get("sha256") != INCIDENT_BUILDER_SHA256
        or builder_record.get("size_bytes") != INCIDENT_BUILDER_SIZE
    ):
        raise GovernanceError("incident builder hard authority differs")
    builder_record["path"] = os.fspath(INCIDENT_BUILDER)
    if incident.get("builder_identity") != builder_record:
        raise GovernanceError("incident builder identity differs")
    human_record = _workspace_record(INCIDENT_HUMAN, "human incident record")
    if (
        human_record.get("sha256") != INCIDENT_HUMAN_SHA256
        or human_record.get("size_bytes") != INCIDENT_HUMAN_SIZE
    ):
        raise GovernanceError("human incident hard authority differs")
    human_record["path"] = os.fspath(INCIDENT_HUMAN)
    if incident.get("human_record") != human_record:
        raise GovernanceError("incident human record differs")
    return incident


@contextmanager
def _held_incident_adoption_authority_v2_legacy_unused():
    """Retain the additive incident and consumed v1 intent for every action."""

    try:
        incident_stat = os.stat(INCIDENT, follow_symlinks=False)
    except FileNotFoundError as error:
        raise GovernanceError("missing incident adoption") from error
    if (
        not stat.S_ISREG(incident_stat.st_mode)
        or stat.S_ISLNK(incident_stat.st_mode)
        or incident_stat.st_nlink != 1
        or incident_stat.st_uid != os.getuid()
        or stat.S_IMODE(incident_stat.st_mode) != 0o444
    ):
        raise GovernanceError("incident adoption publication mode/identity differs")
    old_intent = _load_json_static(OLD_PROBE_INTENT, "consumed v1 probe intent")
    _validate_consumed_v1_intent(old_intent)
    incident = _load_json_static(INCIDENT, "incident adoption")
    _validate_incident_adoption(incident, old_intent=old_intent)
    old_live = _workspace_record(OLD_PROBE_INTENT, "consumed v1 probe intent")
    old_live["path"] = os.fspath(OLD_PROBE_INTENT)
    if old_live != {
        "path": os.fspath(OLD_PROBE_INTENT),
        "sha256": OLD_PROBE_INTENT_SHA256,
        "size_bytes": OLD_PROBE_INTENT_SIZE,
    }:
        raise GovernanceError("consumed v1 probe intent identity differs")
    for path in _legacy_required_absences():
        if os.path.lexists(path):
            raise GovernanceError(f"legacy v1 required absence differs: {path}")
    with ExitStack() as stack:
        validate_incident = stack.enter_context(
            _hold_existing_canonical_json_rooted(
                ROOT, INCIDENT, incident, label="held incident adoption",
                expected_identity=incident_stat,
            )
        )
        validate_old = stack.enter_context(
            _hold_existing_canonical_json_rooted(
                ROOT, OLD_PROBE_INTENT, old_intent,
                label="held consumed v1 probe intent",
            )
        )

        def validate() -> None:
            validate_incident()
            validate_old()
            _validate_consumed_v1_intent(old_intent)
            _validate_incident_adoption(incident, old_intent=old_intent)
            for path in _legacy_required_absences():
                if os.path.lexists(path):
                    raise GovernanceError(f"legacy v1 required absence drifted: {path}")

        validate()
        yield validate
        validate()


# ---------------------------------------------------------------------------
# v3 runtime-alias incident adoption
#
# The definitions above are retained byte-for-byte from v2 for reviewability.
# v3 deliberately overrides only the additive incident boundary below.  It
# never treats the consumed r2 staging namespace as resumable work.

V2_FAILURE_EVIDENCE_RECORDS: dict[str, dict[str, object]] = {
    os.fspath(V1_PROBE_INTENT): {
        "sha256": "d433ce9e5be085efc8854d60b2e34279c9f8e5dc3953e400e89751b53fdcba0a",
        "size_bytes": 3_626, "mode_octal": "0644", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_074_562,
    },
    os.fspath(V2_GOVERNOR): {
        "sha256": V2_GOVERNOR_SHA256, "size_bytes": V2_GOVERNOR_SIZE,
        "mode_octal": "0664", "uid": 1000, "nlink": 1,
        "device_id": 66_312, "inode": 6_075_788,
    },
    os.fspath(V2_INCIDENT): {
        "sha256": "2e3bb54156a99efb79aa59e6f2f8c85f4fbc07f46fc1c326073e1fd71c38f2df",
        "size_bytes": 23_926, "mode_octal": "0444", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_032_205,
    },
    os.fspath(V2_FREEZE): {
        "sha256": "0bd647c70544776e128cf43184b49effc3d5d20b2c15a05729103a8b8378c2f8",
        "size_bytes": 2_357_600, "mode_octal": "0600", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_074_534,
    },
    os.fspath(V2_PROBE_INTENT): {
        "sha256": "21e6a9aa5ec10a5602277f92c5ce6b256b0c62b6b575cf51cb4a3a3f8fa9113f",
        "size_bytes": 3_626, "mode_octal": "0644", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_074_532,
    },
    os.fspath(V2_PROBE_SUCCESS): {
        "sha256": "fb3dee0a08b2968fb403de5da3999d1db2315a7056e60296316e26edc2c4ebbc",
        "size_bytes": 858, "mode_octal": "0444", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_074_539,
    },
    os.fspath(V2_PUBLICATION_INTENT): {
        "sha256": "621100edd33c0f8980038b19660faa8810441175869851a6f59cd3a8f6fec5f1",
        "size_bytes": 1_751, "mode_octal": "0644", "uid": 1000,
        "nlink": 1, "device_id": 66_312, "inode": 6_165_375,
    },
}

_V2_STAGING_LEAVES = {
    "primary/common_grid_audit.csv": ("88cc1664c651585f51728af66543c2a6a82772a70b3aceeca2460793ae23f2fc", 2_802, "0664", 6_165_380),
    "primary/common_support_metrics.csv": ("a0be6693826227d6a07935dc7413b4f3799419a9551a14f0552c9671916a702c", 996, "0664", 6_165_381),
    "primary/common_support_summary.json": ("64f50d509045c6fb1b09ce350a4b4303400e914f5c60e76fec96a0f22efdb6c4", 3_760, "0664", 6_165_379),
    "primary/runtime_receipt.json": ("e714f919d86e82229cca9fa2dbea6698cea69cd8a3cbc26eebd954b5ef5d042e", 2_109_886, "0600", 6_165_382),
    "primary_launch_intent.json": ("d1b5d087962de8b909fd9f06c459f568daad2044eb405b9bd953ccac652dd195", 9_966, "0644", 6_165_378),
    "verification/common_grid_audit.csv": ("88cc1664c651585f51728af66543c2a6a82772a70b3aceeca2460793ae23f2fc", 2_802, "0664", 6_165_386),
    "verification/common_support_metrics.csv": ("a0be6693826227d6a07935dc7413b4f3799419a9551a14f0552c9671916a702c", 996, "0664", 6_165_387),
    "verification/common_support_summary.json": ("64f50d509045c6fb1b09ce350a4b4303400e914f5c60e76fec96a0f22efdb6c4", 3_760, "0664", 6_165_385),
    "verification/runtime_receipt.json": ("11256d1c808561d4fc4bd533f3706dad48451bf72f591e6479b988cf660e78c4", 2_109_896, "0600", 6_165_388),
    "verification_launch_intent.json": ("5a5a54aa7b743d62bb95ababc88e11fcd03401ed7b3ed151b85587a2473782ae", 10_011, "0644", 6_165_384),
}
for _relative, (_sha256, _size_bytes, _mode_octal, _inode) in _V2_STAGING_LEAVES.items():
    V2_FAILURE_EVIDENCE_RECORDS[os.fspath(V2_STAGING / _relative)] = {
        "sha256": _sha256, "size_bytes": _size_bytes,
        "mode_octal": _mode_octal, "uid": 1000, "nlink": 1,
        "device_id": 66_312, "inode": _inode,
    }
del _relative, _sha256, _size_bytes, _mode_octal, _inode

V2_STAGING_DIRECTORY_RECORDS = {
    os.fspath(V2_STAGING): {
        "mode_octal": "0700", "uid": 1000, "gid": 1000, "nlink": 4,
        "device_id": 66_312, "inode": 6_165_367,
    },
    os.fspath(V2_STAGING / "primary"): {
        "mode_octal": "0700", "uid": 1000, "gid": 1000, "nlink": 2,
        "device_id": 66_312, "inode": 6_165_377,
    },
    os.fspath(V2_STAGING / "verification"): {
        "mode_octal": "0700", "uid": 1000, "gid": 1000, "nlink": 2,
        "device_id": 66_312, "inode": 6_165_383,
    },
}


def _v2_failed_namespace_absences() -> tuple[Path, ...]:
    return (
        V1_FREEZE, V1_PROBE_FAILURE, V1_RESULT, V1_POST, V1_STAGING,
        V1_PUBLICATION_INTENT, V1_PUBLICATION_CLOSEOUT, V2_PROBE_FAILURE,
        V2_POST, V2_RESULT, V2_PUBLICATION_CLOSEOUT,
    )


def _incident_static_contract_inputs(
    successor_sha256: str, successor_size_bytes: int,
) -> tuple[
    dict[str, dict[str, object]], dict[str, dict[str, object]],
    dict[str, object], dict[str, dict[str, object]], dict[str, str],
]:
    """Build the hard-pinned successor inputs without opening workspace files."""
    if (
        re.fullmatch(r"[0-9a-f]{64}", successor_sha256) is None
        or isinstance(successor_size_bytes, bool)
        or not isinstance(successor_size_bytes, int)
        or successor_size_bytes <= 0
    ):
        raise GovernanceError("runtime-alias successor governor identity differs")
    inputs: dict[str, dict[str, object]] = {
        "corrected_seal": _incident_record(CORRECTED_SEAL, CORRECTED_SEAL_SHA256, CORRECTED_SEAL_SIZE),
        "reference_bag": _incident_record(RAW_BAG, RAW_BAG_SHA256, RAW_BAG_SIZE),
        "reference_bag_manifest": _incident_record(REFERENCE_BAG_MANIFEST, REFERENCE_BAG_MANIFEST_SHA256, REFERENCE_BAG_MANIFEST_SIZE),
        "config": _incident_record(CONFIG, CONFIG_SHA256, CONFIG_SIZE),
        "config_sealed_authority": _incident_record(CONFIG_SEALED_AUTHORITY, CONFIG_SEALED_AUTHORITY_SHA256, CONFIG_SEALED_AUTHORITY_SIZE),
        "epoch_lock": _incident_record(EPOCH_LOCK, EPOCH_LOCK_FILE_SHA256, 4_446),
        "protocol_doc": _incident_record(PROTOCOL_DOC, "d3ae583ca799ef423054a5b9ece8b53e0000a8d3bbb1ea8c50121f7a60a40816", 7_036),
        "xfeat_feature_bag": _incident_record(XFEAT_FEATURE_BAG, XFEAT_FEATURE_SHA256, 27_396_366),
        "gftt_feature_bag": _incident_record(GFTT_FEATURE_BAG, GFTT_FEATURE_SHA256, 27_388_430),
    }
    for arm, vio in (("xfeat", XFEAT_VIO), ("gftt", GFTT_VIO)):
        authority = VINS_PROVENANCE_AUTHORITY[arm]
        sha256, size_bytes = authority["vio_csv"]
        inputs[f"{arm}_vio"] = _incident_record(vio, sha256, size_bytes)
        run = XFEAT_RUN if arm == "xfeat" else GFTT_RUN
        for leaf, key in (
            ("replay_manifest.txt", "replay_manifest_txt"),
            ("vins_env_manifest.txt", "vins_env_manifest_txt"),
            ("aqualoc_archaeo02_pinhole.yaml", "aqualoc_archaeo02_pinhole_yaml"),
            ("vins_aqualoc_archaeo_external.yaml", "vins_aqualoc_archaeo_external_yaml"),
            ("vins.log", "vins_log"),
        ):
            sha256, size_bytes = authority[key]
            inputs[f"{arm}_{leaf.replace('.', '_')}"] = _incident_record(
                run / leaf, sha256, size_bytes
            )
    helpers = {
        key: {
            "path": _INCIDENT_STATIC_HELPER_PATHS_V1[key],
            "sha256": identity[0], "size_bytes": identity[1],
        }
        for key, identity in _INCIDENT_STATIC_HELPERS_V1.items()
    }
    helpers["governor"] = {
        "path": "scripts/govern_matched_birth_r4_vins_g0_v3.py",
        "sha256": successor_sha256, "size_bytes": successor_size_bytes,
    }
    python_record = {
        "path": "/usr/bin/python3.8",
        "sha256": "298a9e830ed52f36c299427565485d717d1ce0179c0597cc16560513eb780b06",
        "size_bytes": 5_490_456,
    }
    vins_runtime = {
        "vins_binary": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["vins_binary"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["vins_binary"]["sha256"], "size_bytes": 13_104_360},
        "vins_library": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["vins_library"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["vins_library"]["sha256"], "size_bytes": 165_207_064},
        "camera_models_library": {"path": os.fspath(VINS_EXTERNAL_RUNTIME["camera_models_library"]["path"]), "sha256": VINS_EXTERNAL_RUNTIME["camera_models_library"]["sha256"], "size_bytes": 2_970_640},
    }
    authority = _contract_authority(inputs, helpers, python_record, vins_runtime)
    return inputs, helpers, python_record, vins_runtime, authority


def incident_adoption_namespace_contract_v1(
    successor_sha256: str, successor_size_bytes: int
) -> dict[str, object]:
    """Pure v3 namespace authority; no scientific or failed-r2 file is opened."""

    _inputs, _helpers, _python, _vins, authority = (
        _incident_static_contract_inputs(successor_sha256, successor_size_bytes)
    )
    staging, intent, closeout = publication_paths(authority["job_hash"])
    return {
        "schema_version": "aqua-fe-matched-birth-r4-vins-g0-v3-runtime-alias-incident-namespace-contract-v1",
        "successor_governor": {
            "path": "scripts/govern_matched_birth_r4_vins_g0_v3.py",
            "sha256": successor_sha256, "size_bytes": successor_size_bytes,
        },
        "job_id": JOB_ID, "job_hash": authority["job_hash"],
        "destination": os.fspath(OUTPUT), "staging": os.fspath(staging),
        "intent": os.fspath(intent), "closeout": os.fspath(closeout),
        "freeze": os.fspath(FREEZE), "post": os.fspath(POST),
        "probe_intent": os.fspath(PROBE_INTENT),
        "probe_failure": os.fspath(PROBE_FAILURE),
        "probe_success": os.fspath(PROBE_SUCCESS),
    }


def _validate_live_successor_contract(
    sole: Mapping[str, object], namespace: Mapping[str, object],
) -> None:
    """Cross-bind live bytes and every reserved path to incident authority."""

    expected = _incident_static_contract_inputs(
        str(sole["sha256"]), int(sole["size_bytes"])
    )
    live = _current_contract_inputs()
    if not _typed_tree_equal(live, expected):
        raise GovernanceError("live successor input/helper/publication authority differs")
    authority = live[-1]
    staging, intent, closeout = publication_paths(authority["job_hash"])
    if (
        namespace.get("job_id") != authority["job_id"]
        or namespace.get("job_hash") != authority["job_hash"]
        or namespace.get("destination") != os.fspath(OUTPUT)
        or namespace.get("staging") != os.fspath(staging)
        or namespace.get("intent") != os.fspath(intent)
        or namespace.get("closeout") != os.fspath(closeout)
        or namespace.get("freeze") != os.fspath(FREEZE)
        or namespace.get("post") != os.fspath(POST)
        or namespace.get("probe_intent") != os.fspath(PROBE_INTENT)
        or namespace.get("probe_failure") != os.fspath(PROBE_FAILURE)
        or namespace.get("probe_success") != os.fspath(PROBE_SUCCESS)
    ):
        raise GovernanceError("live successor namespace/publication paths differ")


def _preaction_live_authority_check() -> None:
    """No action may observe or mutate its namespace before this barrier."""

    _static_authority_check()
    sole = _workspace_record(Path(_OUTER_SCRIPT), "preaction successor governor")
    sole["path"] = _OUTER_SCRIPT
    namespace = incident_adoption_namespace_contract_v1(
        str(sole["sha256"]), int(sole["size_bytes"])
    )
    _validate_live_successor_contract(sole, namespace)


def _live_exact_record(path: Path, expected: Mapping[str, object], label: str) -> bytes:
    try:
        info = os.stat(path, follow_symlinks=False)
    except FileNotFoundError as error:
        raise GovernanceError(f"missing {label}") from error
    if (
        not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
        or int(info.st_nlink) != expected["nlink"]
        or int(info.st_uid) != expected["uid"]
        or int(info.st_dev) != expected["device_id"]
        or int(info.st_ino) != expected["inode"]
        or format(stat.S_IMODE(info.st_mode), "04o") != expected["mode_octal"]
    ):
        raise GovernanceError(f"{label} filesystem identity differs")
    content = publisher.read_bytes_bound_input_rooted(ROOT, path, label=label)
    if (
        len(content) != expected["size_bytes"]
        or hashlib.sha256(content).hexdigest() != expected["sha256"]
    ):
        raise GovernanceError(f"{label} byte authority differs")
    return content


def _validate_v2_staging_directories() -> None:
    for raw, expected in V2_STAGING_DIRECTORY_RECORDS.items():
        path = Path(raw)
        info = os.stat(path, follow_symlinks=False)
        if (
            not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
            or format(stat.S_IMODE(info.st_mode), "04o") != expected["mode_octal"]
            or int(info.st_uid) != expected["uid"]
            or int(info.st_gid) != expected["gid"]
            or int(info.st_nlink) != expected["nlink"]
            or int(info.st_dev) != expected["device_id"]
            or int(info.st_ino) != expected["inode"]
        ):
            raise GovernanceError("consumed v2 staging directory identity differs")


@contextmanager
def _hold_exact_v2_directory(path: Path, expected: Mapping[str, object]):
    parent_fd = -1
    directory_fd = -1
    try:
        parent_fd, name, _absolute, parent_parts, parent_identity = (
            publisher._open_parent(
                ROOT, path, create=False, label="consumed v2 staging directory"
            )
        )
        directory_fd = os.open(
            name,
            os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC
            | getattr(os, "O_NOFOLLOW", 0),
            dir_fd=parent_fd,
        )

        def validate() -> None:
            held = os.fstat(directory_fd)
            reachable = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            for info in (held, reachable):
                if (
                    not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                    or format(stat.S_IMODE(info.st_mode), "04o")
                    != expected["mode_octal"]
                    or int(info.st_uid) != expected["uid"]
                    or int(info.st_gid) != expected["gid"]
                    or int(info.st_nlink) != expected["nlink"]
                    or int(info.st_dev) != expected["device_id"]
                    or int(info.st_ino) != expected["inode"]
                ):
                    raise GovernanceError(
                        "held consumed v2 staging directory identity differs"
                    )
            publisher._assert_parent_reachable(
                ROOT, parent_parts, parent_identity,
                label="held consumed v2 staging directory",
            )

        validate()
        yield validate
        validate()
    finally:
        if directory_fd >= 0:
            os.close(directory_fd)
        if parent_fd >= 0:
            os.close(parent_fd)


@contextmanager
def _hold_v2_absence(path: Path):
    parent_fd = -1
    try:
        parent_fd, name, _absolute, parent_parts, parent_identity = (
            publisher._open_parent(
                ROOT, path, create=False, label="consumed v2 required absence"
            )
        )

        def validate() -> None:
            publisher._assert_parent_reachable(
                ROOT, parent_parts, parent_identity,
                label="held consumed v2 absence parent",
            )
            try:
                os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return
            raise GovernanceError(f"consumed v2 failure absence drifted: {path}")

        validate()
        yield validate
        validate()
    finally:
        if parent_fd >= 0:
            os.close(parent_fd)


def _validate_v2_failure_semantics(records: Mapping[str, bytes]) -> None:
    v1_intent = p07gov._json_object_bytes(
        records[os.fspath(V1_PROBE_INTENT)], label="transitively retained v1 probe intent"
    )
    if (
        v1_intent.get("schema_version")
        != "aqua-fe-matched-birth-r4-vins-g0-runtime-probe-launch-intent-v1"
        or v1_intent.get("status")
        != "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY"
        or v1_intent.get("attempt_count") != 1
        or v1_intent.get("authorized_process_start_count") != 1
        or v1_intent.get("no_retry_after_pending_evidence") is not True
        or v1_intent.get("intent_path") != os.fspath(V1_PROBE_INTENT)
        or v1_intent.get("failure_path") != os.fspath(V1_PROBE_FAILURE)
        or v1_intent.get("probe_source", {}).get("bootstrap") != {
            "path": "scripts/formal_g0_child_bootstrap_v1.py",
            "sha256": LEGACY_BOOTSTRAP_SHA256,
            "size_bytes": LEGACY_BOOTSTRAP_SIZE,
        }
    ):
        raise GovernanceError("transitively retained v1 probe intent semantics differ")
    if p07gov.validate_self_hash(
        v1_intent, "probe_launch_intent_hash",
        label="transitively retained v1 probe intent",
    ) != "8db122e79ede30eeb3cdb30a3e01d999bd91b3e34979dbf0eaa650ee2692785f":
        raise GovernanceError("transitively retained v1 probe intent self hash differs")
    freeze = p07gov._json_object_bytes(records[os.fspath(V2_FREEZE)], label="consumed v2 freeze")
    intent = p07gov._json_object_bytes(
        records[os.fspath(V2_PUBLICATION_INTENT)], label="consumed v2 publication intent"
    )
    if (
        freeze.get("schema_version") != "aqua-fe-matched-birth-r4-vins-g0-freeze-v3"
        or freeze.get("status") != FREEZE_STATUS
        or freeze.get("reserved_paths", {}).get("destination") != os.fspath(V2_RESULT)
        or freeze.get("reserved_paths", {}).get("staging") != os.fspath(V2_STAGING)
        or intent.get("schema_version") != "isj-p07-g0-publication-intent-v1"
        or intent.get("status") != "PLANNED_NO_CLOBBER_PUBLICATION"
        or intent.get("job_hash") != V2_JOB_HASH
        or intent.get("destination_absolute") != os.fspath(V2_RESULT)
        or intent.get("staging_absolute") != os.fspath(V2_STAGING)
    ):
        raise GovernanceError("consumed v2 namespace semantics differ")
    for role in ROLE_NAMES:
        runtime_path = V2_STAGING / role / RUNTIME_RECEIPT_NAME
        runtime = p07gov._json_object_bytes(
            records[os.fspath(runtime_path)], label=f"consumed v2 {role} runtime receipt"
        )
        if (
            runtime.get("schema_version") != "aquafe-formal-g0-actual-runtime-receipt-v3"
            or runtime.get("status") != "ACTUAL_RUNTIME_CAPTURED"
            or runtime.get("role") != role
        ):
            raise GovernanceError(f"consumed v2 {role} runtime receipt semantics differ")
        try:
            legacy_bootstrap.validate_runtime_receipt_static(
                runtime, role=role,
                expected_closure=freeze["expected_runtime_closure"]["runtime_receipt"],
            )
        except legacy_bootstrap.FormalG0RuntimeError as error:
            if str(error) != "actual evaluator module differs: Cryptodome":
                raise GovernanceError(
                    f"consumed v2 {role} runtime-alias failure differs"
                ) from error
        else:
            raise GovernanceError(
                f"consumed v2 {role} no longer exhibits the adopted alias defect"
            )


def _incident_full_v2_record(path: Path) -> dict[str, object]:
    return {"path": os.fspath(path), **V2_FAILURE_EVIDENCE_RECORDS[os.fspath(path)]}


def _expected_runtime_closure_comparison() -> dict[str, Any]:
    role = {
        "persistent_modules": {
            "probe_required_row_count": 490, "actual_row_count": 490,
            "raw_exact_row_count": 110, "raw_mismatch_row_count": 380,
            "persistent_realpath_alias_row_count": 373,
            "sealed_source_role_locator_row_count": 7,
            "combined_persistent_and_sealed_change_row_count": 0,
            "typed_policy_match_count": 490, "missing_required_count": 0,
            "typed_mismatch_count": 0, "actual_extra_count": 0,
        },
        "persistent_proc_maps": {
            "files": {
                "probe_row_count": 332, "actual_row_count": 331,
                "raw_exact_required_match_count": 331,
                "typed_required_row_count": 331,
                "typed_required_match_count": 331,
                "persistent_realpath_alias_match_count": 0,
                "probe_only_optional_omission_count": 1,
                "missing_required_count": 0, "typed_mismatch_count": 0,
                "actual_extra_count": 0,
            },
            "rows": {
                "probe_row_count": 1702, "actual_row_count": 1697,
                "raw_exact_required_match_count": 1697,
                "typed_required_row_count": 1697,
                "typed_required_match_count": 1697,
                "persistent_realpath_alias_match_count": 0,
                "probe_only_optional_omission_count": 5,
                "missing_required_count": 0, "actual_extra_count": 0,
            },
            "sealed_rows": {
                "probe_row_count": 5, "actual_row_count": 5,
                "typed_required_match_count": 5,
                "missing_required_count": 0, "actual_extra_count": 0,
            },
        },
        "native_loaded_elf_closure": {
            "probe_row_count": 330, "actual_row_count": 329,
            "raw_exact_required_match_count": 329,
            "typed_required_row_count": 329,
            "typed_required_match_count": 329,
            "persistent_realpath_alias_match_count": 0,
            "probe_only_optional_omission_count": 1,
            "missing_required_count": 0, "typed_mismatch_count": 0,
            "actual_extra_count": 0,
        },
    }
    return {
        "schema_version":
            "aqua-fe-runtime-closure-probe-actual-typed-comparison-v1",
        "policy_source": {
            "path": os.fspath(BOOTSTRAP), "size_bytes": BOOTSTRAP_SIZE,
            "sha256": BOOTSTRAP_SHA256,
            "realpath_alias_requires_same_live_device_inode": True,
            "hardlink_without_realpath_alias_is_not_an_alias": True,
            "workload_only_additions_not_used_by_this_incident": True,
        },
        "roles": {
            "primary": json.loads(json.dumps(role)),
            "verification": json.loads(json.dumps(role)),
        },
        "role_to_role_actual_closure": {
            "persistent_modules_exact_tree_equal": True,
            "persistent_proc_maps_exact_tree_equal": True,
            "native_loaded_elf_closure_exact_tree_equal": True,
            "successor_runtime_semantic_identity_equal": True,
        },
    }


def _expected_probe_only_optional_elf() -> dict[str, Any]:
    identity = {
        "lexical_path": "/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2",
        "resolved_path": "/usr/lib/x86_64-linux-gnu/libtbbmalloc.so.2",
        "symlink": None, "size_bytes": 132_976,
        "sha256":
            "14147fcfadccacb4ddf94738143a3fa999a065a303dda898da8ab057cfb483b4",
        "stat": {
            "device": 66_312, "inode": 169_139, "mode": 420,
            "link_count": 1, "uid": 0, "gid": 0,
            "mtime_ns": 1_581_039_179_000_000_000,
            "ctime_ns": 1_740_666_764_578_004_477,
        },
    }
    rows = [
        {
            "device": "103:08", "inode": 169_139,
            "lexical_path": identity["lexical_path"],
            "file_size_bytes": 132_976, "file_sha256": identity["sha256"],
            "offset_hex": offset, "permissions": permissions,
        }
        for offset, permissions in (
            ("00000000", "r--p"), ("00006000", "r-xp"),
            ("00017000", "r--p"), ("0001d000", "r--p"),
            ("0001e000", "rw-p"),
        )
    ]
    return {
        "admission_type": "EXACT_PROBE_ONLY_OPTIONAL_PERSISTENT_ELF",
        "file_identity": dict(identity),
        "persistent_proc_maps": {
            "expected_file_record": dict(identity), "expected_rows": rows,
            "expected_file_record_count": 1, "expected_row_count": 5,
            "actual_role_counts": {
                "primary": {"file_records": 0, "rows": 0},
                "verification": {"file_records": 0, "rows": 0},
            },
            "entire_file_and_all_rows_omitted_by_each_role": True,
        },
        "native_loaded_elf_closure": {
            "expected_record": {
                "mapping_kind": "PERSISTENT_ELF", "file": dict(identity),
            },
            "expected_record_count": 1,
            "actual_role_record_counts": {"primary": 0, "verification": 0},
            "whole_persistent_elf_record_omitted_by_each_role": True,
        },
        "no_general_expected_runtime_subset_relaxation": True,
    }


def _expected_incident_adoption(
    *, sole: Mapping[str, object], builder: Mapping[str, object],
    human: Mapping[str, object], carrier_source: str,
) -> dict[str, Any]:
    """Independently reconstruct the producer's complete typed incident tree."""

    namespace = incident_adoption_namespace_contract_v1(
        str(sole["sha256"]), int(sole["size_bytes"])
    )
    simple = lambda path, sha256, size_bytes: {
        "path": os.fspath(path), "size_bytes": size_bytes, "sha256": sha256,
    }
    v2_governor = simple(V2_GOVERNOR, V2_GOVERNOR_SHA256, V2_GOVERNOR_SIZE)
    science: dict[str, object] = {}
    for name in EVALUATOR_FILES:
        science[name] = {
            "primary": _incident_full_v2_record(V2_STAGING / "primary" / name),
            "verification": _incident_full_v2_record(
                V2_STAGING / "verification" / name
            ),
            "byte_identical": True,
        }
    exact_namespace = {
        "incident": os.fspath(INCIDENT), "freeze": namespace["freeze"],
        "probe_intent": namespace["probe_intent"],
        "probe_failure": namespace["probe_failure"],
        "probe_success": namespace["probe_success"],
        "result": namespace["destination"], "post": namespace["post"],
        "staging": namespace["staging"],
        "publication_intent": namespace["intent"],
        "publication_closeout": namespace["closeout"],
    }
    v3_staging, v3_intent, v3_closeout = publication_paths(
        str(namespace["job_hash"])
    )
    pending_incident = INCIDENT.with_name(f".{INCIDENT.name}.pending_v1")
    required_absent = (
        INCIDENT, pending_incident,
        V1_FREEZE, V1_PROBE_FAILURE, V1_RESULT, V1_POST,
        V1_STAGING, V1_PUBLICATION_INTENT, V1_PUBLICATION_CLOSEOUT,
        V2_PROBE_FAILURE, V2_RESULT, V2_POST, V2_PUBLICATION_CLOSEOUT,
        FREEZE, PROBE_INTENT, PROBE_FAILURE, PROBE_SUCCESS, OUTPUT, POST,
        v3_staging, v3_intent, v3_closeout,
    )
    if len(required_absent) != 22 or len(set(required_absent)) != 22:
        raise GovernanceError("runtime-alias incident required absence closure differs")
    record: dict[str, Any] = {
        "schema_version":
            "aqua-fe-matched-birth-r4-vins-g0-runtime-alias-incident-adoption-v1",
        "status":
            "ADOPTED_CONSUMED_V2_RUNTIME_ALIAS_FAILURE_FOR_ONE_REPAIRED_V3_NAMESPACE",
        "scientific_role":
            "POST_INCIDENT_INFRASTRUCTURE_RECOVERY_NO_OUTCOME_SELECTION",
        "incident_class":
            "V2_RUN_RUNTIME_MODULE_LEXICAL_ALIAS_AND_PROBE_ONLY_OPTIONAL_ELF_FALSE_NEGATIVE",
        "builder_identity": dict(builder),
        "builder_execution_contract": {
            "working_directory": os.fspath(ROOT),
            "environment": {
                "HOME": "/home/ma", "USER": "ma", "LOGNAME": "ma",
                "SHELL": "/bin/bash",
                "PATH":
                    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                "PYTHONHASHSEED": "0", "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            "authorized_write_once_argv": [
                "/usr/bin/python3.8", "-I", "-B", "-c", carrier_source,
                os.fspath(INCIDENT_BUILDER), str(builder["sha256"]),
                "--action", "write-once", "--successor-governor-sha256",
                str(sole["sha256"]), "--successor-governor-size-bytes",
                str(sole["size_bytes"]), "--v3-job-hash",
                str(namespace["job_hash"]),
            ],
            "scientific_evaluator_detector_vins_process_start_count": 0,
            "builder_process_is_publication_control_plane_only": True,
            "publication":
                "O_TMPFILE_HELD_INODE_0444_FILE_FSYNC_HIDDEN_LINK_DIR_FSYNC_RENAMEAT2_NOREPLACE",
            "commit_linearization":
                "O_TMPFILE_HIDDEN_LINK_FSYNC_RENAMEAT2_NOREPLACE",
            "active_same_uid_namespace_adversary_out_of_scope": True,
            "required_absent_at_commit_count": len(required_absent),
            "required_absent_at_commit": [
                os.fspath(path) for path in required_absent
            ],
        },
        "human_record": dict(human),
        "retained_v2_evidence": {
            "governor": v2_governor,
            "prior_incident": {
                "file": _incident_full_v2_record(V2_INCIDENT),
                "self_hash":
                    "791ce7d3736570806d74128485f6f211e9e8f3859ca4b88c9b38f7235eb1050e",
            },
            "transitive_consumed_v1_evidence": {
                "runtime_probe_launch_intent": _incident_full_v2_record(
                    V1_PROBE_INTENT
                ),
                "probe_launch_intent_hash":
                    "8db122e79ede30eeb3cdb30a3e01d999bd91b3e34979dbf0eaa650ee2692785f",
                "intent_semantics": {
                    "attempt_count": 1,
                    "authorized_process_start_count": 1,
                    "no_retry_after_pending_evidence": True,
                    "status": "DURABLE_RUNTIME_PROBE_LAUNCH_PENDING_NO_RETRY",
                },
                "required_absences": [
                    os.fspath(path) for path in (
                        V1_FREEZE, V1_PROBE_FAILURE, V1_RESULT, V1_POST,
                        V1_STAGING, V1_PUBLICATION_INTENT,
                        V1_PUBLICATION_CLOSEOUT,
                    )
                ],
                "old_namespace_mutation_completion_or_retry_authorized": False,
            },
            "freeze": {
                "file": _incident_full_v2_record(V2_FREEZE),
                "self_hash":
                    "4fff2f905802d0f5ee7642fb828c43e552e12e8c031e54ad418a5302d0250496",
            },
            "runtime_probe": {
                "launch_intent": _incident_full_v2_record(V2_PROBE_INTENT),
                "success_closeout": _incident_full_v2_record(V2_PROBE_SUCCESS),
                "failure_receipt_absent": True,
            },
            "publication": {
                "job_hash": V2_JOB_HASH,
                "intent": _incident_full_v2_record(V2_PUBLICATION_INTENT),
                "staging": {
                    "device_id": 66_312, "inode": 6_165_367,
                    "uid": 1000, "gid": 1000, "mode_octal": "0700",
                },
                "destination_absent": True, "closeout_absent": True,
                "post_absent": True,
            },
            "roles": {
                role: {
                    "launch_intent": _incident_full_v2_record(
                        V2_STAGING / f"{role}_launch_intent.json"
                    ),
                    "runtime_receipt": _incident_full_v2_record(
                        V2_STAGING / role / RUNTIME_RECEIPT_NAME
                    ),
                    "evaluator_called": True, "evaluator_rc": 0,
                    "evaluator_error": None,
                }
                for role in ROLE_NAMES
            },
            "science_output_pair_identity": science,
        },
        "mechanical_runtime_alias_diagnosis": {
            "authority": {
                "v2_governor": v2_governor,
                "legacy_child_bootstrap": simple(
                    LEGACY_BOOTSTRAP, LEGACY_BOOTSTRAP_SHA256,
                    LEGACY_BOOTSTRAP_SIZE,
                ),
                "successor_child_bootstrap": simple(
                    BOOTSTRAP, BOOTSTRAP_SHA256, BOOTSTRAP_SIZE,
                ),
            },
            "classification":
                "MECHANICALLY_CHECKED_RUNTIME_CLOSURE_POLICY_FALSE_NEGATIVE",
            "repair_boundary":
                "GOVERNANCE_VALIDATION_ONLY_NO_SCIENTIFIC_COMPUTATION_CHANGE",
            "runtime_closure_comparison": _expected_runtime_closure_comparison(),
            "cryptodome_example": {
                "module_name": "Cryptodome",
                "expected_lexical_path":
                    "/lib/python3/dist-packages/Cryptodome/__init__.py",
                "actual_lexical_path":
                    "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
                "expected_realpath":
                    "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
                "actual_realpath":
                    "/usr/lib/python3/dist-packages/Cryptodome/__init__.py",
                "device_id": 66_312, "inode": 1_051_682,
                "size_bytes": 182,
                "sha256":
                    "20a3a80330f01736e2f67dd72da47b2d0d7df6abb06b537101ac009e57bd4e42",
            },
            "probe_only_optional_elf": _expected_probe_only_optional_elf(),
            "facts": [
                "both_roles_evaluator_called_rc0_error_null",
                "three_science_outputs_byte_identical_by_name",
                "runtime_receipts_not_byte_identical_due_to_role_and_output_identity",
                "v2_destination_closeout_post_absent", "no_v2_pass_claim",
            ],
        },
        "successor_authorization": {
            "sole_governor": dict(sole),
            "v3_job_hash": namespace["job_hash"],
            "successor_namespace_contract": namespace,
            "exact_namespace": exact_namespace,
            "repair_policy": {
                "runtime_closure_lexical_alias":
                    "PROBE_EXPECTED_ACTUAL_REALPATH_ALIAS_NORMALIZATION_ONLY_FOR_PERSISTENT_MODULES_PERSISTENT_PROC_MAPS_FILES_AND_ROWS_AND_NATIVE_LOADED_ELF_CLOSURE;SAME_FILE_IDENTITY_REQUIRED;ROLE_TO_ROLE_AND_ALL_SCIENTIFIC_SEMANTICS_UNCHANGED",
                "probe_only_optional_elf":
                    "EXACT_PROBE_ONLY_OPTIONAL_LIBTBBMALLOC_RECORD_ONLY;NO_GENERAL_EXPECTED_RUNTIME_SUBSET_RELAXATION",
            },
            "old_v1_or_v2_namespace_retry_mutation_or_completion_authorized": False,
            "detector_or_feature_export_rerun_authorized": False,
            "vins_rerun_authorized": False,
            "scientific_or_evaluation_contract_change_authorized": False,
            "authorized_successor_evaluation_namespace_count": 1,
            "authorized_action_sequence": [
                "write-freeze", "check-start", "run", "seal-post", "check-post",
            ],
        },
        "outcome_firewall": {
            "science_outputs_read_as_opaque_bytes": True,
            "science_metric_values_read_or_recorded": False,
            "trajectory_values_read_or_recorded": False,
            "arm_relative_result_available_to_builder": False,
            "result_conditioned_successor_selection": False,
        },
        "claim_boundary": {
            "v2_evaluator_rc0_receipts_claimed": True,
            "v2_science_outputs_role_byte_identity_claimed": True,
            "v2_runtime_receipts_byte_identical_claimed": False,
            "v2_publication_or_post_pass_claimed": False,
            "scientific_outcome_claimed": False,
            "v3_is_additive_post_incident_exploratory": True,
        },
        "incident_hash": "0" * 64,
    }
    # This schema deliberately uses the producer's canonical JSON line format.
    record["incident_hash"] = hashlib.sha256(
        _canonical_json_bytes(record) + b"\n"
    ).hexdigest()
    return record


def _validate_incident_adoption(
    value: object, *, old_intent: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    del old_intent
    if (
        INCIDENT_BUILDER_SHA256 == "0" * 64 or INCIDENT_BUILDER_SIZE <= 0
        or INCIDENT_BUILDER_CARRIER_SHA256 == "0" * 64
        or INCIDENT_BUILDER_CARRIER_SIZE <= 0
        or INCIDENT_HUMAN_SHA256 == "0" * 64 or INCIDENT_HUMAN_SIZE <= 0
    ):
        raise GovernanceError("runtime-alias incident hard pins are not frozen")
    sole = _workspace_record(Path(_OUTER_SCRIPT), "runtime-alias successor governor")
    sole["path"] = _OUTER_SCRIPT
    builder = _workspace_record(INCIDENT_BUILDER, "runtime-alias incident builder")
    builder["path"] = os.fspath(INCIDENT_BUILDER)
    human = _workspace_record(INCIDENT_HUMAN, "runtime-alias human record")
    human["path"] = os.fspath(INCIDENT_HUMAN)
    if (
        builder["sha256"] != INCIDENT_BUILDER_SHA256
        or builder["size_bytes"] != INCIDENT_BUILDER_SIZE
        or human["sha256"] != INCIDENT_HUMAN_SHA256
        or human["size_bytes"] != INCIDENT_HUMAN_SIZE
    ):
        raise GovernanceError("runtime-alias incident producer authority differs")
    expected = _expected_incident_adoption(
        sole=sole, builder=builder, human=human,
        carrier_source=_incident_builder_carrier_source(),
    )
    if not _typed_tree_equal(value, expected):
        raise GovernanceError("runtime-alias incident exact typed tree differs")
    _validate_live_successor_contract(
        sole, expected["successor_authorization"]["successor_namespace_contract"]
    )
    return dict(value)


@contextmanager
def _held_incident_adoption_authority():
    """Hold the new incident first, then every consumed-r2 evidence inode."""

    try:
        incident_stat = os.stat(INCIDENT, follow_symlinks=False)
    except FileNotFoundError as error:
        raise GovernanceError("missing incident adoption") from error
    if (
        not stat.S_ISREG(incident_stat.st_mode) or stat.S_ISLNK(incident_stat.st_mode)
        or incident_stat.st_nlink != 1 or incident_stat.st_uid != os.getuid()
        or stat.S_IMODE(incident_stat.st_mode) != 0o444
    ):
        raise GovernanceError(
            "runtime-alias incident publication mode/identity differs"
        )
    incident = _load_json_static(INCIDENT, "runtime-alias incident adoption")
    _validate_incident_adoption(incident)
    with ExitStack() as stack:
        validate_incident = stack.enter_context(
            _hold_existing_canonical_json_rooted(
                ROOT, INCIDENT, incident, label="held runtime-alias incident adoption",
                expected_identity=incident_stat,
            )
        )
        held: dict[str, bytes] = {}
        validators: list[Any] = []
        for raw, expected in sorted(V2_FAILURE_EVIDENCE_RECORDS.items()):
            path = Path(raw)
            content = _live_exact_record(path, expected, f"consumed v2 evidence {path.name}")
            held[raw] = content
            validators.append(stack.enter_context(
                publisher.retained_bound_input_validator(
                    ROOT, path, content, label=f"held consumed v2 evidence {path.name}"
                )
            ))
        directory_validators = [
            stack.enter_context(_hold_exact_v2_directory(Path(raw), expected))
            for raw, expected in sorted(V2_STAGING_DIRECTORY_RECORDS.items())
        ]
        absence_validators = [
            stack.enter_context(_hold_v2_absence(path))
            for path in _v2_failed_namespace_absences()
        ]

        def validate() -> None:
            validate_incident()
            _validate_incident_adoption(incident)
            for validator in validators:
                validator()
            for validator in directory_validators:
                validator()
            for validator in absence_validators:
                validator()
            _validate_v2_staging_directories()
            for raw, expected in V2_FAILURE_EVIDENCE_RECORDS.items():
                if _live_exact_record(
                    Path(raw), expected, f"consumed v2 evidence {Path(raw).name}"
                ) != held[raw]:
                    raise GovernanceError("consumed v2 evidence bytes drifted")
            _validate_v2_failure_semantics(held)

        validate()
        yield validate
        validate()


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
        expected_gid = os.fstat(parent_fd).st_gid
        if (
            not stat.S_ISDIR(created.st_mode)
            or stat.S_ISLNK(created.st_mode)
            or created.st_dev != opened.st_dev
            or created.st_ino != opened.st_ino
            or opened.st_uid != os.getuid()
            or opened.st_gid != expected_gid
            or created.st_gid != expected_gid
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
                or held.st_gid != expected_gid
                or reachable.st_gid != expected_gid
                or stat.S_IMODE(held.st_mode) != 0o700
                or stat.S_IMODE(reachable.st_mode) != 0o700
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
    return [
        os.fspath(PYTHON), *CHILD_PYTHON_OPTIONS, os.fspath(BOOTSTRAP),
        *_evaluator_tail(paths, os.fspath(OUTPUT / role)),
    ]


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
    legacy_bootstrap_record = _workspace_record(
        LEGACY_BOOTSTRAP, "legacy formal G0 child bootstrap"
    )
    if (
        legacy_bootstrap_record.get("sha256") != LEGACY_BOOTSTRAP_SHA256
        or legacy_bootstrap_record.get("size_bytes") != LEGACY_BOOTSTRAP_SIZE
    ):
        raise GovernanceError("legacy formal G0 child bootstrap authority differs")
    for role, (sha256, size_bytes) in _INCIDENT_STATIC_HELPERS_V1.items():
        helper_record = _workspace_record(
            HELPERS[role], f"hard-pinned formal helper {role}"
        )
        if (
            helper_record.get("sha256") != sha256
            or helper_record.get("size_bytes") != size_bytes
        ):
            raise GovernanceError(f"hard-pinned formal helper differs: {role}")
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
    value: object, *, process_started: bool, success: bool,
    require_deferred: bool = False,
) -> dict[str, Any]:
    expected_keys = {
        "policy", "prior_target_mask", "prior_handlers",
        "install_transition_mask_applied", "handlers_installed_before_popen",
        "spawn_target_mask", "pid_captured_while_handlers_installed",
        "received_signals", "cleanup_mode_before_restore",
        "child_reaped_before_restore", "restore_transition_mask_applied",
        "handlers_restored", "post_restore_target_mask", "handler_lifecycle",
        "handlers_active_after_child_reap",
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
        or value.get("child_reaped_before_restore") is not True
        or (success and received != [])
    ):
        raise GovernanceError("spawn signal guard authority differs")
    if require_deferred:
        if (
            value.get("handler_lifecycle") != "DEFERRED_THROUGH_PARENT_TRANSACTION"
            or value.get("handlers_active_after_child_reap") is not True
            or value.get("restore_transition_mask_applied") is not False
            or value.get("handlers_restored") is not False
            or value.get("post_restore_target_mask") is not None
            or value.get("cleanup_mode_before_restore") is not (not success)
        ):
            raise GovernanceError("deferred probe signal lifecycle differs")
    elif (
        value.get("handler_lifecycle") != "RESTORED_AFTER_CHILD_REAP"
        or value.get("handlers_active_after_child_reap") is not False
        or value.get("restore_transition_mask_applied") is not True
        or value.get("handlers_restored") is not True
        or value.get("post_restore_target_mask") != []
        or value.get("cleanup_mode_before_restore") is not True
    ):
        raise GovernanceError("restored child signal lifecycle differs")
    return dict(value)


class _SpawnSignalGuard:
    """Own termination signals through child and optional parent transaction."""

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
        self.post_intent_mode = False

    def _handler(self, signum: int, _frame: object) -> None:
        name = signal.Signals(signum).name
        if name not in self.received:
            self.received.append(name)
            self.received.sort(key=_SPAWN_SIGNAL_NAMES.index)
        if self.post_intent_mode and not self.cleanup_mode:
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
        # Popen can return a live child while a Python signal handler is
        # running.  Record signals without raising until the returned process
        # and PID have both been captured, then convert any pending signal into
        # the normal synchronous cleanup path.
        prior_cleanup = self.cleanup_mode
        self.cleanup_mode = True
        try:
            self.process = subprocess.Popen(tuple(argv), **kwargs)
            self.pid = int(self.process.pid)
            if self.pid <= 0:
                raise GovernanceError("spawned child PID is not positive")
            self.process_owned = True
        finally:
            self.cleanup_mode = prior_cleanup
        if self.received:
            self.cleanup_mode = True
            raise _SpawnTerminationSignal(self.received[0])
        return self.process, self.pid

    def begin_cleanup(self) -> None:
        self.cleanup_mode = True

    def activate_post_intent(self) -> None:
        """Turn each guarded target signal after durable intent into a Python failure."""

        self.post_intent_mode = True
        self.cleanup_mode = False
        if self.received:
            raise _SpawnTerminationSignal(self.received[0])

    def child_reaped_keep_handlers(self) -> None:
        """Retain handler ownership after reap for the parent transaction."""

        self.cleanup_mode = False
        if self.received:
            raise _SpawnTerminationSignal(self.received[0])

    def _audit(self, *, child_reaped: bool, deferred: bool) -> dict[str, Any]:
        return {
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
            "handler_lifecycle": (
                "DEFERRED_THROUGH_PARENT_TRANSACTION"
                if deferred else "RESTORED_AFTER_CHILD_REAP"
            ),
            "handlers_active_after_child_reap": deferred,
            "restore_transition_mask_applied": (
                False if deferred else self.restore_mask_applied
            ),
            "handlers_restored": False if deferred else self.handlers_restored,
            "post_restore_target_mask": None if deferred else self.post_restore_mask,
        }

    def deferred_audit(self, *, child_reaped: bool) -> dict[str, Any]:
        if not self.handlers_installed or self.handlers_restored:
            raise GovernanceError("probe signal handlers are not actively deferred")
        if self.process is not None and not child_reaped:
            raise GovernanceError("cannot snapshot deferred handlers before child reap")
        return self._audit(child_reaped=child_reaped, deferred=True)

    def finish(
        self, *, child_reaped: bool, before_restore: Any = None
    ) -> dict[str, Any]:
        self.cleanup_mode = True
        if self.process is not None and not child_reaped:
            raise GovernanceError("cannot restore spawn handlers before child reap")
        previous_mask = signal.pthread_sigmask(signal.SIG_BLOCK, self.targets)
        self.restore_mask_applied = True
        restore_error: BaseException | None = None
        try:
            prior_target_names = _spawn_target_signal_names(previous_mask)
            if prior_target_names not in ([], list(_SPAWN_SIGNAL_NAMES)):
                raise GovernanceError("spawn termination mask drifted before handler restore")
            pending = _spawn_target_signal_names(signal.sigpending())
            for name in pending:
                if name not in self.received:
                    self.received.append(name)
            self.received.sort(key=_SPAWN_SIGNAL_NAMES.index)
            if before_restore is not None:
                try:
                    before_restore()
                except BaseException as error:
                    # Handler restoration must still complete even when the
                    # terminal-evidence finalizer itself fails.  The durable
                    # intent remains the no-retry fallback in that case.
                    restore_error = error
            # Restore all handlers while every target remains blocked.  The
            # original mask is restored once, only after the handler set is
            # complete, so no target observes a partially restored set.
            for target in self.targets:
                prior = self.previous_handlers.get(target)
                if prior is None:
                    raise GovernanceError("spawn prior handler record is incomplete")
                signal.signal(target, prior)
            self.handlers_restored = True
        except BaseException as error:
            if restore_error is None:
                restore_error = error
        finally:
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        if restore_error is not None:
            raise restore_error
        observed_post_restore = _spawn_target_signal_names(
            signal.pthread_sigmask(signal.SIG_BLOCK, set())
        )
        # The outer deferred-stack drain may already own the exact target
        # transition mask.  It restores the original empty process mask only
        # after every held authority has closed.  Record that eventual policy
        # state here; no persisted receipt uses this restored audit for the
        # deferred probe lifecycle.
        self.post_restore_mask = (
            [] if prior_target_names == list(_SPAWN_SIGNAL_NAMES)
            else observed_post_restore
        )
        return self._audit(child_reaped=child_reaped, deferred=False)


def _probe_success_payload(
    *, intent: Mapping[str, Any], freeze: Mapping[str, Any]
) -> dict[str, Any]:
    """Final write-freeze success marker; later actions require this exact leaf."""

    payload: dict[str, Any] = {
        "schema_version": PROBE_SUCCESS_SCHEMA,
        "status": "COMMITTED_RUNTIME_PROBE_AND_FREEZE_SUCCESS_NO_RETRY",
        "probe_launch_intent_hash": intent["probe_launch_intent_hash"],
        "freeze_hash": freeze["freeze_hash"],
        "probe_intent_path": os.fspath(PROBE_INTENT),
        "freeze_path": os.fspath(FREEZE),
        "success_path": os.fspath(PROBE_SUCCESS),
        "process_start_count": 1,
        "no_retry": True,
        "success_hash": "0" * 64,
    }
    payload["success_hash"] = _self_hash(payload, "success_hash")
    return payload


def _validate_probe_success(
    value: object, *, intent: Mapping[str, Any], freeze: Mapping[str, Any]
) -> dict[str, Any]:
    keys = {
        "schema_version", "status", "probe_launch_intent_hash", "freeze_hash",
        "probe_intent_path", "freeze_path", "success_path",
        "process_start_count", "no_retry", "success_hash",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise GovernanceError("runtime probe success closeout field set differs")
    observed = dict(value)
    p07gov.validate_self_hash(
        observed, "success_hash", label="runtime probe success closeout"
    )
    expected = _probe_success_payload(intent=intent, freeze=freeze)
    if not _typed_tree_equal(observed, expected):
        raise GovernanceError("runtime probe success closeout semantics differ")
    return observed


def _load_probe_success(
    *, intent: Mapping[str, Any], freeze: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        identity = os.stat(PROBE_SUCCESS, follow_symlinks=False)
    except FileNotFoundError as error:
        raise GovernanceError("runtime probe success closeout is missing") from error
    if (
        not stat.S_ISREG(identity.st_mode)
        or stat.S_ISLNK(identity.st_mode)
        or identity.st_nlink != 1
        or identity.st_uid != os.getuid()
        or stat.S_IMODE(identity.st_mode) != 0o444
    ):
        raise GovernanceError("runtime probe success closeout mode/identity differs")
    return _validate_probe_success(
        _load_json_static(PROBE_SUCCESS, "runtime probe success closeout"),
        intent=intent,
        freeze=freeze,
    )


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
        os.fspath(PYTHON), *CHILD_PYTHON_OPTIONS, os.fspath(BOOTSTRAP),
        bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
    ]:
        actual = value["actual_procfd_argv"]
        if (
            len(actual) != len(canonical_argv)
            or actual[1:CHILD_BOOTSTRAP_INDEX] != CHILD_PYTHON_OPTIONS
            or actual[CHILD_BOOTSTRAP_INDEX + 1] != bootstrap.PROBE_ARGUMENT
            or actual[CHILD_BOOTSTRAP_INDEX + 3] != REFERENCE_TOPIC
            or any(
                re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", str(actual[index])) is None
                for index in (0, CHILD_BOOTSTRAP_INDEX, CHILD_BOOTSTRAP_INDEX + 2)
            )
            or not {
                int(str(actual[index]).rsplit("/", 1)[1])
                for index in (0, CHILD_BOOTSTRAP_INDEX, CHILD_BOOTSTRAP_INDEX + 2)
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
    classifications = {
        "PROCESS_START_ERROR", "SPAWN_WINDOW_ERROR_TERMINATED",
        "TIMEOUT_TERMINATED", "WAIT_ERROR_TERMINATED",
        "TERMINATED_BY_SIGNAL", "EXITED_NONZERO",
        "POST_WAIT_RECEIPT_VALIDATION_ERROR", "POST_WAIT_STDERR_POLICY_ERROR",
        "POST_RC0_PARENT_VALIDATION_ERROR",
        "POST_INTENT_PRESTART_PARENT_FAILURE",
    }
    start_count = value.get("process_start_count")
    pid = value.get("pid")
    timed_out = value.get("timed_out")
    return_code = value.get("return_code")
    termination_signal = value.get("termination_signal")
    classification = value.get("classification")
    wait_error = value.get("wait_error")
    cleanup_errors = value.get("cleanup_errors")
    if (
        value.get("schema_version") != PROBE_FAILURE_SCHEMA
        or value.get("status") != "TERMINAL_RUNTIME_PROBE_FAILURE_NO_RETRY"
        or value.get("attempt_count") != 1
        or type(start_count) is not int or start_count not in (0, 1)
        or value.get("no_retry") is not True
        or value.get("timeout_seconds") != RUNTIME_PROBE_TIMEOUT_SECONDS
        or classification not in classifications
        or value.get("probe_launch_intent_hash") != intent.get("probe_launch_intent_hash")
        or value.get("child_reaped") is not True
        or type(timed_out) is not bool
        or not isinstance(cleanup_errors, list)
        or any(
            not isinstance(item, Mapping)
            or set(item) != {"class", "message"}
            or not all(isinstance(part, str) for part in item.values())
            for item in cleanup_errors
        )
        or (
            wait_error is not None
            and (
                not isinstance(wait_error, Mapping)
                or set(wait_error) != {"class", "message"}
                or not all(isinstance(part, str) for part in wait_error.values())
            )
        )
    ):
        raise GovernanceError("runtime probe failure receipt is not terminal/reaped")
    for stream in ("stdout", "stderr"):
        record = value.get(stream)
        if (
            not isinstance(record, Mapping)
            or set(record) != {"sha256", "size_bytes"}
            or re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256"))) is None
            or isinstance(record.get("size_bytes"), bool)
            or not isinstance(record.get("size_bytes"), int)
            or int(record["size_bytes"]) < 0
        ):
            raise GovernanceError(f"runtime probe failure {stream} receipt differs")
    if start_count == 0:
        if (
            classification not in {
                "PROCESS_START_ERROR", "POST_INTENT_PRESTART_PARENT_FAILURE"
            }
            or pid is not None or return_code is not None
            or termination_signal is not None or timed_out
            or wait_error is None or cleanup_errors
        ):
            raise GovernanceError("runtime probe pre-start failure matrix differs")
    else:
        if (
            pid is None and classification != "SPAWN_WINDOW_ERROR_TERMINATED"
        ) or (
            pid is not None
            and (isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0)
        ):
            raise GovernanceError("runtime probe started failure PID differs")
        if isinstance(return_code, bool) or not isinstance(return_code, int):
            raise GovernanceError("runtime probe started failure return code differs")
        expected_signal = -return_code if return_code < 0 else None
        if termination_signal != expected_signal:
            raise GovernanceError("runtime probe failure termination signal differs")
        if timed_out != (classification == "TIMEOUT_TERMINATED"):
            raise GovernanceError("runtime probe failure timeout matrix differs")
        if classification == "TERMINATED_BY_SIGNAL" and return_code >= 0:
            raise GovernanceError("runtime probe signal classification differs")
        if classification == "EXITED_NONZERO" and return_code <= 0:
            raise GovernanceError("runtime probe nonzero-exit classification differs")
        if classification.startswith("POST_") and (
            return_code != 0 or timed_out or termination_signal is not None
            or wait_error is None or cleanup_errors
        ):
            raise GovernanceError("runtime probe post-RC0 failure matrix differs")
        if classification in {
            "SPAWN_WINDOW_ERROR_TERMINATED", "WAIT_ERROR_TERMINATED",
            "TIMEOUT_TERMINATED",
        } and wait_error is None:
            raise GovernanceError("runtime probe wait failure lacks error identity")
        if classification in {"TERMINATED_BY_SIGNAL", "EXITED_NONZERO"} and wait_error is not None:
            raise GovernanceError("runtime probe direct exit unexpectedly has wait error")
    _validate_spawn_signal_guard(
        value.get("spawn_signal_guard"),
        process_started=value.get("process_start_count") == 1,
        success=False,
        require_deferred=True,
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
        self.intent_durable = False
        self.signal_guard: _SpawnSignalGuard | None = None
        self.stdout = b""
        self.stderr = b""

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
        # Publish the complete payload to the transaction finalizer before the
        # first durable byte is attempted.  If the rooted writer reaches a
        # canonical durable leaf but is interrupted before returning, the
        # finalizer can recover and hold that exact intent for failure sealing.
        self.intent = intent
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
        self.intent_durable = True
        return intent

    def _recover_durable_intent(
        self, *, cause: BaseException | None = None
    ) -> bool:
        if self.intent is None or not os.path.lexists(self.intent_path):
            return False
        # A governance validation error from the original O_EXCL writer means
        # its visible inode/bytes already differed; never adopt that object.
        # Recovery is only for an external interruption after write/fsync but
        # before the context manager could return its validator.
        if isinstance(cause, GovernanceError):
            return False
        try:
            if self.intent_validator is not None:
                try:
                    self.intent_validator()
                except BaseException:
                    # Once the O_EXCL writer yielded, its original inode is
                    # authoritative.  Never adopt a same-byte replacement.
                    return False
            if self.intent_validator is None:
                # The O_EXCL leaf and parent fsync can complete before the
                # context manager yields its validator.  Re-acquire the exact
                # canonical visible intent in that narrow handoff window; no
                # process may start, and the recovered hold stays in the same
                # transaction stack through terminal failure publication.
                self.intent_validator = self.stack.enter_context(
                    _hold_existing_canonical_json_rooted(
                        ROOT,
                        self.intent_path,
                        self.intent,
                        label="recovered durable runtime probe launch intent",
                    )
                )
            self.intent_validator()
            observed = _load_json_static(
                self.intent_path, "recoverable durable runtime probe launch intent"
            )
            if not _typed_tree_equal(observed, self.intent):
                return False
            _validate_probe_launch_intent(
                observed,
                canonical_argv=self.canonical_argv,
                source_records=self.source_records,
                intent_path=self.intent_path,
                failure_path=self.failure_path,
            )
            self.intent_record = _workspace_record(
                self.intent_path, "recovered durable runtime probe launch intent"
            )
            self.intent_durable = True
            return True
        except BaseException:
            return False

    def _persist_failure(self, payload: Mapping[str, Any]) -> None:
        if self.intent is None:
            raise GovernanceError("runtime probe failure lacks retained launch intent")
        if self.intent_validator is None:
            if not self._recover_durable_intent():
                raise GovernanceError(
                    "runtime probe failure cannot recover its launch intent"
                )
        else:
            try:
                self.intent_validator()
            except BaseException:
                raise
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

    def _persist_parent_failure(
        self, error: BaseException, *, classification: str | None = None
    ) -> None:
        """Seal one catchable post-intent parent failure before handler restore."""

        if os.path.lexists(self.failure_path):
            return
        if self.intent is None or self.intent_validator is None:
            if not self._recover_durable_intent():
                return
        guard = self.signal_guard
        if guard is None:
            raise GovernanceError("runtime probe parent failure lacks signal guard")
        guard.begin_cleanup()
        observed = self.observed
        if observed is None:
            process = guard.process
            process_started = process is not None
            pid = guard.pid if process_started else None
            return_code = getattr(process, "returncode", None) if process_started else None
            if process_started and not isinstance(return_code, int):
                raise GovernanceError(
                    "runtime probe parent finalizer found an unreaped child"
                ) from error
            selected_classification = classification or (
                "WAIT_ERROR_TERMINATED" if process_started
                else "POST_INTENT_PRESTART_PARENT_FAILURE"
            )
            stdout = self.stdout
            stderr = self.stderr
        else:
            process_started = True
            pid = int(observed["pid"])
            return_code = int(observed["return_code"])
            selected_classification = (
                classification or "POST_RC0_PARENT_VALIDATION_ERROR"
            )
            stdout = observed["stdout"]
            stderr = observed["stderr"]
        failure = _probe_failure_payload(
            self.intent,
            pid=pid,
            process_started=process_started,
            timed_out=False,
            return_code=return_code,
            classification=selected_classification,
            wait_error=error,
            cleanup_errors=[],
            child_reaped=True,
            spawn_signal_guard=guard.deferred_audit(child_reaped=True),
            stdout=stdout,
            stderr=stderr,
        )
        self._persist_failure(failure)

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
        guard = _SpawnSignalGuard()
        self.signal_guard = guard
        guard.install()
        try:
            intent = self._persist_intent(command, environment, pass_fds, timeout)
        except BaseException as error:
            guard.begin_cleanup()
            try:
                if self._recover_durable_intent(cause=error):
                    self._persist_parent_failure(error)
            finally:
                guard.finish(child_reaped=True)
            raise
        # The intent hold was entered first.  The transaction finalizer is
        # therefore unwound while that exact inode is still retained, and the
        # post-validation writer is unwound before both of them.
        self.stack.enter_context(_ProbeSignalTransactionFinalizer(self, guard))
        self.stack.enter_context(_ProbePostValidationFailureGuard(self))
        guard.activate_post_intent()
        process: Any = None
        pid: int | None = None
        stdout = b""
        stderr = b""
        wait_error: BaseException | None = None
        timed_out = False
        cleanup_errors: list[dict[str, str]] = []
        child_reaped = True
        spawn_signal_guard: dict[str, Any]
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
            guard.begin_cleanup()
            spawn_signal_guard = guard.deferred_audit(child_reaped=True)
            failure = _probe_failure_payload(
                intent, pid=None, process_started=False, timed_out=False,
                return_code=None, classification="PROCESS_START_ERROR",
                wait_error=wait_error, cleanup_errors=[], child_reaped=True,
                spawn_signal_guard=spawn_signal_guard,
                stdout=b"", stderr=b"",
            )
            self._persist_failure(failure)
            guard.finish(child_reaped=True)
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
        if wait_error is None and return_code == 0 and not cleanup_errors and child_reaped:
            try:
                guard.child_reaped_keep_handlers()
            except BaseException as error:
                guard.begin_cleanup()
                wait_error = error
            spawn_signal_guard = guard.deferred_audit(child_reaped=True)
        else:
            guard.begin_cleanup()
            spawn_signal_guard = guard.deferred_audit(child_reaped=child_reaped)
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
            guard.finish(child_reaped=child_reaped)
            raise GovernanceError(
                "runtime probe failed after launch; terminal no-retry evidence written"
            ) from wait_error
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
        self.intent_validator()
        _validate_child_stderr_receipt(
            _stream_receipt(stderr), label="runtime probe raw capture"
        )
        return subprocess.CompletedProcess(command, int(return_code), stdout, stderr)


class _ProbeSignalTransactionFinalizer:
    """Retain probe handlers until every parent-side action checkpoint ends."""

    def __init__(self, capture: _OneRunProbeCapture,
                 guard: _SpawnSignalGuard) -> None:
        self.capture = capture
        self.guard = guard

    def __enter__(self) -> "_ProbeSignalTransactionFinalizer":
        return self

    def __exit__(self, error_type: object, error: object,
                 traceback: object) -> bool:
        if self.guard.handlers_restored:
            return False
        effective: BaseException | None = (
            error if isinstance(error, BaseException) else None
        )
        self.guard.begin_cleanup()
        if effective is None and self.guard.received:
            effective = _SpawnTerminationSignal(self.guard.received[0])
        if effective is not None:
            self.capture._persist_parent_failure(effective)

        def before_restore() -> None:
            nonlocal effective
            if effective is None and self.guard.received:
                effective = _SpawnTerminationSignal(self.guard.received[0])
            if effective is not None:
                self.capture._persist_parent_failure(effective)

        child_reaped = (
            self.guard.process is None
            or isinstance(getattr(self.guard.process, "returncode", None), int)
        )
        self.guard.finish(child_reaped=child_reaped, before_restore=before_restore)
        if error_type is None and effective is not None:
            raise effective
        return False


class _ProbePostValidationFailureGuard:
    """Turn every post-RC0 parent exception into terminal no-retry evidence."""

    def __init__(self, capture: _OneRunProbeCapture) -> None:
        self.capture = capture

    def __enter__(self) -> "_ProbePostValidationFailureGuard":
        return self

    def __exit__(self, error_type: object, error: object, traceback: object) -> bool:
        if error_type is None:
            return False
        capture = self.capture
        if capture.intent is None or os.path.lexists(capture.failure_path):
            return False
        if not isinstance(error, BaseException):
            error = GovernanceError("post-RC0 parent validation failed without exception identity")
        capture._persist_parent_failure(error)
        return False


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
        os.fspath(PYTHON), *CHILD_PYTHON_OPTIONS, os.fspath(BOOTSTRAP),
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
                classification = (
                    "POST_WAIT_STDERR_POLICY_ERROR"
                    if _stream_receipt(observed["stderr"])
                    not in _child_stderr_allowlist()
                    else "POST_WAIT_RECEIPT_VALIDATION_ERROR"
                )
                capture._persist_parent_failure(
                    error, classification=classification
                )
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
    _validate_child_stderr_receipt(
        _stream_receipt(observed["stderr"]), label="representative runtime probe"
    )
    bootstrap.validate_freeze_runtime_static(runtime_receipt)
    sealed_sources = runtime_receipt.get("sealed_sources")
    if not isinstance(sealed_sources, Mapping):
        raise GovernanceError("representative runtime probe sealed sources differ")
    probe_aliases = {
        os.fspath(PYTHON): observed["argv"][0],
        os.fspath(BOOTSTRAP): observed["argv"][CHILD_BOOTSTRAP_INDEX],
        os.fspath(RAW_BAG): observed["argv"][CHILD_BOOTSTRAP_INDEX + 2],
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
        "schema_version": "aqua-fe-matched-birth-r4-g0-expected-runtime-closure-v3",
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
        value.get("schema_version") != "aqua-fe-matched-birth-r4-g0-expected-runtime-closure-v3"
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
        process.get("spawn_signal_guard"), process_started=True, success=True,
        require_deferred=True,
    )
    canonical_argv = [
        os.fspath(PYTHON), *CHILD_PYTHON_OPTIONS, os.fspath(BOOTSTRAP),
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
        or actual_argv[1:CHILD_BOOTSTRAP_INDEX] != CHILD_PYTHON_OPTIONS
        or actual_argv[CHILD_BOOTSTRAP_INDEX + 1] != bootstrap.PROBE_ARGUMENT
        or actual_argv[CHILD_BOOTSTRAP_INDEX + 3] != REFERENCE_TOPIC
        or any(
            re.fullmatch(r"/proc/self/fd/[1-9][0-9]*", str(actual_argv[index])) is None
            for index in (0, CHILD_BOOTSTRAP_INDEX, CHILD_BOOTSTRAP_INDEX + 2)
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
    _validate_child_stderr_receipt(process.get("stderr"), label="runtime probe")
    execution = receipt.get("execution") if isinstance(receipt, Mapping) else None
    if (
        not isinstance(execution, Mapping)
        or set(execution) != {
            "sys_argv", "process_argv", "environment", "target_signal_mask"
        }
        or execution.get("process_argv") != actual_argv
        or execution.get("sys_argv") != actual_argv[CHILD_BOOTSTRAP_INDEX:]
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
        "bootstrap": actual_argv[CHILD_BOOTSTRAP_INDEX],
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
            "child_stderr_contract": _child_stderr_contract(),
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
            "probe_success": os.fspath(PROBE_SUCCESS),
        },
        "freeze_hash": "0" * 64,
    }
    payload["freeze_hash"] = _self_hash(payload, "freeze_hash")
    return payload


def _validate_record(record: Mapping[str, Any], path: Path, label: str) -> None:
    observed = _workspace_record(path, label)
    if dict(record) != observed:
        raise GovernanceError(f"{label} live record differs")


def validate_freeze_static(
    *, require_fresh_outputs: bool, require_probe_success: bool = True
) -> dict[str, Any]:
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
        "child_stderr_contract": _child_stderr_contract(),
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
        "probe_success": os.fspath(PROBE_SUCCESS),
    }
    if freeze.get("reserved_paths") != expected_reserved:
        raise GovernanceError("G0 reserved path authority differs")
    if os.path.lexists(PROBE_FAILURE):
        raise GovernanceError("runtime probe failure namespace contradicts successful freeze")
    intent = _load_json_static(PROBE_INTENT, "runtime probe launch intent")
    _validate_probe_launch_intent(
        intent,
        canonical_argv=[
            os.fspath(PYTHON), *CHILD_PYTHON_OPTIONS, os.fspath(BOOTSTRAP),
            bootstrap.PROBE_ARGUMENT, os.fspath(RAW_BAG), REFERENCE_TOPIC,
        ],
        source_records={
            "python": _external_record(PYTHON, "runtime-probe Python"),
            "bootstrap": _workspace_record(BOOTSTRAP, "runtime-probe bootstrap"),
            "wrapper": _workspace_record(WRAPPER, "runtime-probe wrapper"),
            "base": _workspace_record(BASE, "runtime-probe base"),
            "core": _workspace_record(CORE, "runtime-probe core"),
            "reference_bag": _workspace_record(RAW_BAG, "runtime-probe reference bag"),
        },
    )
    if require_probe_success:
        _load_probe_success(intent=intent, freeze=freeze)
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
    if (
        actual[0] != python_lease.proc_path
        or actual[1:CHILD_BOOTSTRAP_INDEX] != CHILD_PYTHON_OPTIONS
        or actual[CHILD_BOOTSTRAP_INDEX] != proc["child_bootstrap"]
    ):
        raise GovernanceError("actual role argv prefix is not exact sealed Python/bootstrap")
    if "/home/ma/.local" in environment.get("PATH", ""):
        raise GovernanceError("user-local PATH is forbidden")
    return actual, environment, mapping


def _stream_receipt(content: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}


def _child_stderr_allowlist() -> list[dict[str, object]]:
    return [_stream_receipt(b""), _stream_receipt(EXPECTED_CHILD_STDERR)]


def _child_stderr_contract() -> dict[str, object]:
    return {
        "policy": "EXACT_ALLOWLIST_ONLY;ANY_OTHER_BYTES_ARE_TERMINAL_FAILURE",
        "allowed": [
            {**_stream_receipt(b""), "meaning": "EMPTY_STDERR"},
            {
                **_stream_receipt(EXPECTED_CHILD_STDERR),
                "meaning": "EXACT_PREREGISTERED_ROSLZ4_WARNING_ONLY",
            },
        ],
    }


def _validate_child_stderr_receipt(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise GovernanceError(f"{label} stderr receipt is not an object")
    observed = dict(value)
    if observed not in _child_stderr_allowlist():
        raise GovernanceError(f"{label} stderr is outside the exact allowlist")
    return observed


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
    stderr_allowed = _stream_receipt(stderr) in _child_stderr_allowlist()
    classification = (
        "PROCESS_START_ERROR" if not process_started else
        "SPAWN_WINDOW_ERROR_TERMINATED" if spawn_window_error else
        "TIMEOUT_TERMINATED" if timed_out else
        "WAIT_ERROR_TERMINATED" if wait_error is not None else
        "TERMINATED_BY_SIGNAL" if termination_signal is not None else
        "POST_RC0_STDERR_POLICY_ERROR" if return_code == 0 and not stderr_allowed else
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
        or execution.get("sys_argv") != process_argv[CHILD_BOOTSTRAP_INDEX:]
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
        or actual[1:CHILD_BOOTSTRAP_INDEX] != CHILD_PYTHON_OPTIONS
        or actual[CHILD_BOOTSTRAP_INDEX] != aliases[os.fspath(BOOTSTRAP)]
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
    _validate_child_stderr_receipt(value.get("stderr"), label=role)


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
        or argv[1:CHILD_BOOTSTRAP_INDEX] != CHILD_PYTHON_OPTIONS
        or argv[CHILD_BOOTSTRAP_INDEX] != aliases[os.fspath(BOOTSTRAP)]
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
        "probe_intent", "probe_failure", "probe_success",
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
    _preaction_live_authority_check()
    global _DEFERRED_FREEZE_STACK, _AQUAFE_G0_FINAL_SUCCESS_COMMIT
    _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
    if os.path.lexists(FREEZE):
        raise GovernanceError("freeze namespace already contains evidence")
    pre_inputs, pre_helpers, pre_python, pre_vins_runtime, pre_authority = _current_contract_inputs()
    for path in (
        *publication_paths(pre_authority["job_hash"]), OUTPUT, POST,
        PROBE_INTENT, PROBE_FAILURE, PROBE_SUCCESS,
    ):
        if os.path.lexists(path):
            raise GovernanceError(f"reserved namespace already contains evidence: {path}")
    with _DeferrableExitStack() as retained:
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
        # Keep the launch intent and post-RC0 failure guard held through the
        # final static validation.  Any parent exception here consumes the
        # fresh probe namespace with a terminal failure receipt.
        validate_freeze_static(
            require_fresh_outputs=True, require_probe_success=False
        )
        if os.path.lexists(PROBE_SUCCESS):
            raise GovernanceError("runtime probe success namespace already contains evidence")
        if runtime.get("probe_launch_intent") is None:
            raise GovernanceError("runtime probe success lacks launch intent")
        success = _probe_success_payload(
            intent=runtime["probe_launch_intent"], freeze=payload
        )
        success_bytes = _render_canonical_json(success)
        _AQUAFE_G0_FINAL_SUCCESS_COMMIT = {
            "path": os.fspath(PROBE_SUCCESS),
            "content": success_bytes,
            "sha256": hashlib.sha256(success_bytes).hexdigest(),
            "mode": 0o444,
            "required_records": [
                _workspace_record(FREEZE, "final success freeze"),
                _workspace_record(PROBE_INTENT, "final success probe intent"),
            ],
            "required_absent": [os.fspath(PROBE_FAILURE)],
        }
        if _OUTER_GUARD_ACTIVE:
            if _DEFERRED_FREEZE_STACK is not None:
                raise GovernanceError("formal write-freeze deferred stack already exists")
            # Publish the same ExitStack object before making its local
            # context non-closing.  A signal in between causes the local with
            # statement to close it normally; a signal after defer_to_outer
            # is handled by the outer finalizer through the global reference.
            _DEFERRED_FREEZE_STACK = retained
            retained.defer_to_outer()
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
                PROBE_INTENT, PROBE_FAILURE, PROBE_SUCCESS,
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
    _preaction_live_authority_check()
    with _held_incident_adoption_authority() as validate_incident:
        validate_incident()
        if action == "preview-contract":
            print(json.dumps(preview_contract(), indent=2, sort_keys=True))
            result = 0
        elif action == "write-freeze":
            result = write_freeze()
        elif action == "check-start":
            validate_freeze_static(require_fresh_outputs=True)
            print("PASS_START")
            result = 0
        elif action == "run":
            result = run_evaluation()
        elif action == "seal-post":
            result = seal_post()
        else:
            result = check_post()
        validate_incident()
        return result


if __name__ == "__main__":
    _AQUAFE_G0_OUTER_ACTION_CLEAN_SUCCESS = None
    _action_error: BaseException | None = None
    try:
        _exit_code = main()
    except BaseException as error:
        _action_error = error
        if isinstance(error, SystemExit):
            # An action-internal SystemExit is still an interrupted formal
            # transaction, even when its payload is zero.  Only the explicit
            # final raise below may hand a successful code to the carrier.
            _exit_code = int(error.code or 0)
            if _exit_code == 0:
                _exit_code = 2
            _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
        else:
            _exit_code = 2
            _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
            try:
                print(
                    f"GOVERNANCE_ERROR:{type(error).__name__}:{error}",
                    file=sys.stderr,
                )
            except BaseException:
                pass
    finally:
        try:
            _outer_post_action_guard()
        except BaseException as error:
            if _action_error is None:
                _action_error = error
            _exit_code = 2
            _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
            try:
                print(
                    f"OUTER_GUARD_ERROR:{type(error).__name__}:{error}",
                    file=sys.stderr,
                )
            except BaseException:
                pass
        finally:
            if _OUTER_WORKSPACE_FINDER is not None:
                try:
                    _OUTER_WORKSPACE_FINDER.close()
                except BaseException as error:
                    if _action_error is None:
                        _action_error = error
                    _exit_code = 2
                    _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
                    try:
                        print(
                            f"OUTER_GUARD_ERROR:{type(error).__name__}:{error}",
                            file=sys.stderr,
                        )
                    except BaseException:
                        pass
            try:
                _finish_deferred_freeze_stack(_action_error)
            except BaseException as error:
                _exit_code = 2
                _AQUAFE_G0_FINAL_SUCCESS_COMMIT = None
                try:
                    print(
                        f"OUTER_GUARD_ERROR:{type(error).__name__}:{error}",
                        file=sys.stderr,
                    )
                except BaseException:
                    pass
    if _exit_code == 0 and _action_error is None:
        _AQUAFE_G0_OUTER_ACTION_CLEAN_SUCCESS = {
            "action": sys.argv[2], "exit_code": 0,
        }
    else:
        raise SystemExit(_exit_code)
