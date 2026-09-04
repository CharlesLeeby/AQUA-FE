#!/usr/bin/env python3
"""Hardened publication primitives for unfrozen P07 backend governance.

The helpers in this module have no import-time side effects.  A destination is
published with a same-directory, fsynced temporary file and ``linkat``-style
no-replace semantics.  An existing destination is never unlinked.  Multi-file
bundles publish their authorization/commit document last and may resume only
when every already-published data file is byte-exact and the commit document is
still absent.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from typing import Callable, Iterator, Mapping, Sequence


GLOBAL_FLOCK = Path("/tmp/aquafe_p07_backend_formalization_v1.lock")


class FormalIOError(RuntimeError):
    """A formal path or publication invariant was violated."""


def json_bytes(payload: Mapping[str, object]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    ).encode("utf-8")


def _relative_parts(relative: str) -> tuple[str, ...]:
    pure = PurePosixPath(relative)
    if (
        not relative
        or "\x00" in relative
        or pure.is_absolute()
        or not pure.parts
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise FormalIOError(f"unsafe formal relative path: {relative!r}")
    return tuple(pure.parts)


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise FormalIOError("platform lacks required no-follow directory flags")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _open_root_dirfd(root: Path) -> int:
    """Open an absolute workspace root one direct component at a time."""

    root = root.absolute()
    try:
        current = os.open(os.path.sep, _directory_flags())
    except OSError as error:
        raise FormalIOError("cannot open filesystem root for formal I/O") from error
    try:
        for component in root.parts[1:]:
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise FormalIOError(
                    f"formal workspace root ancestor is unavailable: {component}"
                ) from error
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise FormalIOError(
                    f"formal workspace root ancestor is not direct: {component}"
                )
            child = os.open(component, _directory_flags(), dir_fd=current)
            opened = os.fstat(child)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                os.close(child)
                raise FormalIOError(
                    f"formal workspace root ancestor changed: {component}"
                )
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


@contextmanager
def _parent_dirfd(root: Path, relative: str) -> Iterator[tuple[int, str]]:
    parts = _relative_parts(relative)
    root = root.absolute()
    descriptors: list[int] = []
    try:
        current = _open_root_dirfd(root)
        descriptors.append(current)
        for component in parts[:-1]:
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise FormalIOError(
                    f"formal parent component is unavailable: {component}"
                ) from error
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise FormalIOError(
                    f"formal parent component is not a direct directory: {component}"
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise FormalIOError(
                    f"cannot no-follow open formal parent: {component}"
                ) from error
            descriptors.append(child)
            current = child
        yield current, parts[-1]
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _read_direct_at(parent_fd: int, name: str) -> tuple[bytes, os.stat_result]:
    flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as error:
        raise FormalIOError(f"cannot no-follow open formal file: {name}") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise FormalIOError(f"formal destination is not a regular file: {name}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks), info
    finally:
        os.close(fd)


def _pread_all(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    if offset != size:
        raise FormalIOError("short read while validating retained formal artifact")
    return b"".join(chunks)


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_uid,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid)


@contextmanager
def _retained_exact_leaf(
    root: Path, relative: str, expected: bytes
) -> Iterator[dict[str, object]]:
    """Retain a direct data leaf and its canonical parent through commit."""

    with _parent_dirfd(root, relative) as (parent_fd, name):
        flags = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            leaf_fd = os.open(name, flags, dir_fd=parent_fd)
        except OSError as error:
            raise FormalIOError(
                f"cannot retain formal bundle data leaf: {relative}"
            ) from error
        try:
            parent_info = os.fstat(parent_fd)
            leaf_info = os.fstat(leaf_fd)
            if not stat.S_ISREG(leaf_info.st_mode) or leaf_info.st_nlink != 1:
                raise FormalIOError(
                    f"formal bundle data leaf is not direct/single-link: {relative}"
                )
            if _pread_all(leaf_fd, leaf_info.st_size) != expected:
                raise FormalIOError(
                    f"formal bundle data leaf differs from expected bytes: {relative}"
                )
            yield {
                "root": root.absolute(),
                "relative": relative,
                "name": name,
                "parent_fd": parent_fd,
                "parent_identity": _directory_identity(parent_info),
                "leaf_fd": leaf_fd,
                "leaf_identity": _stat_identity(leaf_info),
                "expected": expected,
            }
        finally:
            os.close(leaf_fd)


def _validate_retained_exact_leaf(lease: Mapping[str, object]) -> None:
    root = lease["root"]
    relative = lease["relative"]
    name = lease["name"]
    parent_fd = lease["parent_fd"]
    leaf_fd = lease["leaf_fd"]
    expected = lease["expected"]
    if (
        not isinstance(root, Path)
        or not isinstance(relative, str)
        or not isinstance(name, str)
        or not isinstance(parent_fd, int)
        or not isinstance(leaf_fd, int)
        or not isinstance(expected, bytes)
    ):
        raise FormalIOError("invalid retained formal bundle lease")

    parent_info = os.fstat(parent_fd)
    leaf_info = os.fstat(leaf_fd)
    if _directory_identity(parent_info) != lease["parent_identity"]:
        raise FormalIOError(f"retained formal data parent drift: {relative}")
    if _stat_identity(leaf_info) != lease["leaf_identity"]:
        raise FormalIOError(f"retained formal data leaf drift: {relative}")
    if not stat.S_ISREG(leaf_info.st_mode) or leaf_info.st_nlink != 1:
        raise FormalIOError(f"retained formal data leaf is no longer direct: {relative}")
    if _pread_all(leaf_fd, leaf_info.st_size) != expected:
        raise FormalIOError(f"retained formal data bytes drift: {relative}")

    # A retained descriptor alone is insufficient: the canonical path must
    # still reach the exact retained parent and leaf (no rename/symlink swap).
    with _parent_dirfd(root, relative) as (canonical_parent_fd, canonical_name):
        canonical_parent = os.fstat(canonical_parent_fd)
        if _directory_identity(canonical_parent) != lease["parent_identity"]:
            raise FormalIOError(f"canonical formal data parent drift: {relative}")
        try:
            canonical_leaf = os.stat(
                canonical_name, dir_fd=canonical_parent_fd, follow_symlinks=False
            )
        except OSError as error:
            raise FormalIOError(
                f"canonical formal data leaf is unavailable: {relative}"
            ) from error
        if _stat_identity(canonical_leaf) != lease["leaf_identity"]:
            raise FormalIOError(f"canonical formal data leaf drift: {relative}")
        observed, opened = _read_direct_at(canonical_parent_fd, canonical_name)
        if _stat_identity(opened) != lease["leaf_identity"] or observed != expected:
            raise FormalIOError(f"canonical formal data bytes drift: {relative}")


def _write_all(fd: int, content: bytes) -> None:
    view = memoryview(content)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise FormalIOError("short write while staging formal artifact")
        view = view[written:]


def _fsync_directory(fd: int) -> None:
    os.fsync(fd)


def destination_exists(root: Path, relative: str) -> bool:
    with _parent_dirfd(root, relative) as (parent_fd, name):
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as error:
            raise FormalIOError(f"cannot inspect formal destination: {relative}") from error
        return True


def assert_all_absent(root: Path, relatives: Sequence[str]) -> None:
    present = [relative for relative in relatives if destination_exists(root, relative)]
    if present:
        raise FileExistsError(f"formal destinations already exist: {present}")


def read_direct_bytes(root: Path, relative: str) -> tuple[bytes, dict[str, int]]:
    """Read one existing formal file through a no-follow parent/file chain."""

    with _parent_dirfd(root, relative) as (parent_fd, name):
        content, info = _read_direct_at(parent_fd, name)
        if info.st_nlink != 1:
            raise FormalIOError(f"formal file has unexpected hard links: {relative}")
        return content, {
            "device": info.st_dev,
            "inode": info.st_ino,
            "size_bytes": info.st_size,
        }


def preflight_bundle_commit_absent(
    root: Path,
    data_artifacts: Sequence[tuple[str, bytes]],
    *,
    commit_relative: str,
) -> dict[str, object]:
    """Read-only collision/reconcile check for a commit-last bundle."""

    names = [relative for relative, _content in data_artifacts]
    if len([*names, commit_relative]) != len(set([*names, commit_relative])):
        raise FormalIOError("formal preflight bundle contains duplicate destinations")
    if destination_exists(root, commit_relative):
        raise FileExistsError(commit_relative)
    exact_existing: list[str] = []
    absent: list[str] = []
    for relative, expected in data_artifacts:
        if not destination_exists(root, relative):
            absent.append(relative)
            continue
        observed, _identity = read_direct_bytes(root, relative)
        if observed != expected:
            raise FormalIOError(
                f"formal crash-reconcile data differs from rebuilt bytes: {relative}"
            )
        exact_existing.append(relative)
    return {
        "commit_absent": True,
        "exact_existing_data": exact_existing,
        "absent_data": absent,
    }


def ensure_exact_leaf_directory(
    root: Path, parent_relative: str, leaf_name: str
) -> dict[str, int]:
    """Create at most one named leaf below an existing no-follow directory chain."""

    if not leaf_name or "/" in leaf_name or leaf_name in {".", ".."}:
        raise FormalIOError(f"unsafe formal leaf directory name: {leaf_name!r}")
    probe = f"{parent_relative.rstrip('/')}/.leaf-probe"
    with _parent_dirfd(root, probe) as (parent_fd, _probe_name):
        try:
            os.mkdir(leaf_name, 0o755, dir_fd=parent_fd)
        except FileExistsError:
            pass
        except OSError as error:
            raise FormalIOError(
                f"cannot create exact formal leaf directory: {leaf_name}"
            ) from error
        info = os.stat(leaf_name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise FormalIOError(
                f"formal leaf is not a direct directory: {leaf_name}"
            )
        child_fd = os.open(leaf_name, _directory_flags(), dir_fd=parent_fd)
        try:
            child_info = os.fstat(child_fd)
            if child_info.st_dev != info.st_dev or child_info.st_ino != info.st_ino:
                raise FormalIOError(f"formal leaf identity changed: {leaf_name}")
        finally:
            os.close(child_fd)
        _fsync_directory(parent_fd)
        return {"device": info.st_dev, "inode": info.st_ino}


def publish_bytes_no_clobber(
    root: Path,
    relative: str,
    content: bytes,
    *,
    allow_exact_existing: bool = False,
    pre_link_guard: Callable[[], None] | None = None,
    post_link_guard: Callable[[], None] | None = None,
    post_unlink_guard: Callable[[], None] | None = None,
) -> dict[str, object]:
    """Publish one regular file without ever replacing/unlinking a destination."""

    with _parent_dirfd(root, relative) as (parent_fd, name):
        try:
            existing_info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            existing_info = None
        if existing_info is not None:
            if not allow_exact_existing:
                raise FileExistsError(relative)
            observed, info = _read_direct_at(parent_fd, name)
            if observed != content or info.st_nlink != 1:
                raise FormalIOError(
                    f"crash-resume destination is not byte-exact/direct: {relative}"
                )
            return {
                "path": relative,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
                "device": info.st_dev,
                "inode": info.st_ino,
                "resumed_exact_existing": True,
            }

        temporary = f".{name}.partial.{os.getpid()}.{secrets.token_hex(12)}"
        temp_fd: int | None = None
        linked = False
        linked_guarded = False
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
            temp_fd = os.open(temporary, flags, 0o600, dir_fd=parent_fd)
            _write_all(temp_fd, content)
            os.fsync(temp_fd)
            temp_info = os.fstat(temp_fd)
            if not stat.S_ISREG(temp_info.st_mode) or temp_info.st_size != len(content):
                raise FormalIOError("staged formal artifact identity/size mismatch")
            if pre_link_guard is not None:
                pre_link_guard()
            try:
                os.link(
                    temporary,
                    name,
                    src_dir_fd=parent_fd,
                    dst_dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileExistsError:
                # The race winner is never touched.  Exact-resume is deliberately
                # limited to destinations that existed before this publication.
                raise FileExistsError(relative)
            linked = True
            _fsync_directory(parent_fd)
            if post_link_guard is not None:
                post_link_guard()
            linked_guarded = True
        finally:
            try:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
                finally:
                    _fsync_directory(parent_fd)
                # The destination is now the sole link, while the staged FD
                # and canonical parent are still retained by this function.
                if linked_guarded and post_unlink_guard is not None:
                    post_unlink_guard()
            finally:
                if temp_fd is not None:
                    os.close(temp_fd)

        if not linked:
            raise FormalIOError(f"formal artifact was not linked: {relative}")
        observed, final_info = _read_direct_at(parent_fd, name)
        if observed != content or final_info.st_nlink != 1:
            raise FormalIOError(f"published formal artifact drift: {relative}")
        return {
            "path": relative,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "device": final_info.st_dev,
            "inode": final_info.st_ino,
            "resumed_exact_existing": False,
        }


@contextmanager
def global_formal_lock(path: Path = GLOBAL_FLOCK) -> Iterator[None]:
    path = path.absolute()
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise FormalIOError(f"formal flock parent is unsafe: {path.parent}")
    flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        fd = os.open(path, flags, 0o600)
    except OSError as error:
        raise FormalIOError(f"cannot safely open formal flock: {path}") from error
    try:
        info = os.fstat(fd)
        path_info = os.lstat(path)
        if (
            not stat.S_ISREG(info.st_mode)
            or stat.S_ISLNK(path_info.st_mode)
            or info.st_dev != path_info.st_dev
            or info.st_ino != path_info.st_ino
            or info.st_uid != os.geteuid()
        ):
            raise FormalIOError(f"formal flock identity is unsafe: {path}")
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def publish_bundle_commit_last(
    root: Path,
    data_artifacts: Sequence[tuple[str, bytes]],
    *,
    commit_artifact: tuple[str, bytes],
    flock_path: Path = GLOBAL_FLOCK,
) -> list[dict[str, object]]:
    """Publish an exact-resumable bundle whose final item is authorization."""

    data_names = [relative for relative, _content in data_artifacts]
    commit_name, commit_content = commit_artifact
    names = [*data_names, commit_name]
    if len(names) != len(set(names)):
        raise FormalIOError("formal bundle contains duplicate destinations")
    with global_formal_lock(flock_path):
        if destination_exists(root, commit_name):
            raise FileExistsError(commit_name)
        records = [
            publish_bytes_no_clobber(
                root, relative, content, allow_exact_existing=True
            )
            for relative, content in data_artifacts
        ]
        with ExitStack() as stack:
            leases = [
                stack.enter_context(_retained_exact_leaf(root, relative, content))
                for relative, content in data_artifacts
            ]

            def validate_data_leases() -> None:
                for lease in leases:
                    _validate_retained_exact_leaf(lease)

            validate_data_leases()
            records.append(
                publish_bytes_no_clobber(
                    root,
                    commit_name,
                    commit_content,
                    allow_exact_existing=False,
                    pre_link_guard=validate_data_leases,
                    post_link_guard=validate_data_leases,
                )
            )
            validate_data_leases()
        return records


def publish_json_no_clobber(
    root: Path,
    relative: str,
    payload: Mapping[str, object],
    *,
    flock_path: Path = GLOBAL_FLOCK,
) -> dict[str, object]:
    with global_formal_lock(flock_path):
        return publish_bytes_no_clobber(root, relative, json_bytes(payload))
