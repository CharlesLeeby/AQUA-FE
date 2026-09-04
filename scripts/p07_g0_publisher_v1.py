#!/usr/bin/env python3
"""No-clobber publisher and crash reconciler for one governed P07 G0 job.

An intent is written outside the final result directory before computation.
The evaluator writes only into the intent's staging directory.  A sealed
staging directory contains an SHA-256 manifest and a self-hashed receipt; it
is published with Linux ``renameat2(RENAME_NOREPLACE)``.  Neither incomplete
staging nor a partial intent is ever deleted by this module.
"""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
from typing import Any, Callable, Iterator, Mapping, Sequence

try:
    from scripts import p07_g0_governance_v1 as gov
except ModuleNotFoundError:
    import p07_g0_governance_v1 as gov  # type: ignore


INTENT_STATUS = "PLANNED_NO_CLOBBER_PUBLICATION"
RECEIPT_STATUS = "SEALED_STAGING_RESULT"
CLOSEOUT_STATUS = "ATOMICALLY_PUBLISHED_NO_CLOBBER"
MANIFEST_NAME = "output_manifest.sha256"
RECEIPT_NAME = "result_receipt_v1.json"
BOUND_SUMMARY_NAME = "bound_summary_v1.json"
PUBLICATION_POLICY = {
    "destination_must_not_exist": True,
    "atomic_rename_noreplace_required": True,
    "incomplete_staging_preserved": True,
    "intent_preserved": True,
    "manifest_and_receipt_required": True,
}

# Scientific inputs may live behind these two repository-root canonical links.
# The link text is part of the source contract; every component below the
# target is still opened with O_NOFOLLOW.  No other link is permitted.
SANCTIONED_INPUT_ROOT_TARGETS = {
    "logs": Path("/mnt/data/AQUA-FE_WS/logs"),
    "datasets": Path("/mnt/data/AQUA-FE_WS/datasets"),
}


def _directory_flags() -> int:
    required = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")
    if any(not hasattr(os, name) for name in required):
        raise gov.G0GovernanceError("platform lacks required no-follow directory flags")
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _workspace_parts(
    root: Path, path: Path, *, label: str
) -> tuple[Path, Path, tuple[str, ...]]:
    root_absolute = Path(os.path.abspath(os.fspath(root)))
    path_absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = path_absolute.relative_to(root_absolute)
    except ValueError as error:
        raise gov.G0GovernanceError(
            f"{label} escapes the workspace: {path_absolute}"
        ) from error
    parts = tuple(relative.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise gov.G0GovernanceError(f"unsafe {label} path: {path_absolute}")
    return root_absolute, path_absolute, parts


def _open_workspace_root(root: Path) -> tuple[int, Path]:
    root_absolute = Path(os.path.abspath(os.fspath(root)))
    try:
        descriptor = os.open(os.path.sep, _directory_flags())
    except OSError as error:
        raise gov.G0GovernanceError("cannot open filesystem root") from error
    try:
        for component in root_absolute.parts[1:]:
            try:
                before = os.stat(
                    component, dir_fd=descriptor, follow_symlinks=False
                )
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"workspace root ancestor is unavailable: {component}"
                ) from error
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise gov.G0GovernanceError(
                    f"workspace root ancestor is not a direct directory: {component}"
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=descriptor)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot no-follow open workspace root ancestor: {component}"
                ) from error
            opened = os.fstat(child)
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or not stat.S_ISDIR(opened.st_mode)
            ):
                os.close(child)
                raise gov.G0GovernanceError(
                    f"workspace root ancestor identity changed: {component}"
                )
            os.close(descriptor)
            descriptor = child
        return descriptor, root_absolute
    except BaseException:
        os.close(descriptor)
        raise


def _open_absolute_directory(path: Path, *, label: str) -> int:
    """Open one absolute directory from ``/`` without following any link."""

    absolute = Path(os.path.abspath(os.fspath(path)))
    if not absolute.is_absolute():
        raise gov.G0GovernanceError(f"{label} is not absolute")
    try:
        current = os.open(os.path.sep, _directory_flags())
    except OSError as error:
        raise gov.G0GovernanceError(f"cannot open filesystem root for {label}") from error
    try:
        for component in absolute.parts[1:]:
            try:
                before = os.stat(component, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"{label} directory component is unavailable: {component}"
                ) from error
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} directory component is not direct: {component}"
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot no-follow open {label} component: {component}"
                ) from error
            opened = os.fstat(child)
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or not stat.S_ISDIR(opened.st_mode)
            ):
                os.close(child)
                raise gov.G0GovernanceError(
                    f"{label} directory identity changed: {component}"
                )
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _identity_tuple(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(info.st_uid),
    )


def _open_direct_descendant_directory(
    start_fd: int, parts: Sequence[str], *, label: str
) -> int:
    """Open direct descendant directories while retaining caller ownership."""

    current = os.dup(start_fd)
    try:
        for component in parts:
            try:
                before = os.stat(component, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"{label} ancestor is unavailable: {component}"
                ) from error
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} ancestor is not a direct directory: {component}"
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot no-follow open {label} ancestor: {component}"
                ) from error
            opened = os.fstat(child)
            if opened.st_dev != before.st_dev or opened.st_ino != before.st_ino:
                os.close(child)
                raise gov.G0GovernanceError(
                    f"{label} ancestor identity changed: {component}"
                )
            os.close(current)
            current = child
        return current
    except BaseException:
        os.close(current)
        raise


def _open_directory_chain(
    root: Path, parts: Sequence[str], *, create: bool, label: str
) -> tuple[int, Path]:
    current, root_absolute = _open_workspace_root(root)
    try:
        for component in parts:
            try:
                before = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise gov.G0GovernanceError(
                        f"missing {label} directory component: {component}"
                    )
                try:
                    os.mkdir(component, 0o755, dir_fd=current)
                    os.fsync(current)
                except OSError as error:
                    raise gov.G0GovernanceError(
                        f"cannot create {label} directory component: {component}"
                    ) from error
                before = os.stat(component, dir_fd=current, follow_symlinks=False)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot inspect {label} directory component: {component}"
                ) from error
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} ancestor is not a direct directory: {component}"
                )
            try:
                child = os.open(component, _directory_flags(), dir_fd=current)
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot no-follow open {label} ancestor: {component}"
                ) from error
            opened = os.fstat(child)
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or not stat.S_ISDIR(opened.st_mode)
            ):
                os.close(child)
                raise gov.G0GovernanceError(
                    f"{label} ancestor identity changed: {component}"
                )
            os.close(current)
            current = child
        return current, root_absolute
    except BaseException:
        os.close(current)
        raise


def _open_parent(
    root: Path, path: Path, *, create: bool, label: str
) -> tuple[int, str, Path, tuple[str, ...], os.stat_result]:
    _root, path_absolute, parts = _workspace_parts(root, path, label=label)
    parent_parts = parts[:-1]
    parent, _ = _open_directory_chain(
        root, parent_parts, create=create, label=f"{label} parent"
    )
    return parent, parts[-1], path_absolute, parent_parts, os.fstat(parent)


def _assert_parent_reachable(
    root: Path,
    parent_parts: Sequence[str],
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    observed, _ = _open_directory_chain(
        root, parent_parts, create=False, label=f"{label} reachability"
    )
    try:
        info = os.fstat(observed)
        if info.st_dev != expected.st_dev or info.st_ino != expected.st_ino:
            raise gov.G0GovernanceError(f"{label} parent is no longer reachable")
    finally:
        os.close(observed)


def _assert_directory_reachable(
    root: Path,
    parts: Sequence[str],
    expected: os.stat_result,
    *,
    label: str,
) -> None:
    observed, _ = _open_directory_chain(
        root, parts, create=False, label=f"{label} reachability"
    )
    try:
        info = os.fstat(observed)
        if info.st_dev != expected.st_dev or info.st_ino != expected.st_ino:
            raise gov.G0GovernanceError(f"{label} is no longer reachable")
    finally:
        os.close(observed)


def _assert_safe_path(root: Path, path: Path, *, label: str, leaf_kind: str) -> None:
    """Reject every existing symlink/special component without creating paths."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    current, _ = _open_workspace_root(root)
    try:
        for index, component in enumerate(parts):
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return
            except OSError as error:
                raise gov.G0GovernanceError(
                    f"cannot inspect {label} component: {component}"
                ) from error
            final = index == len(parts) - 1
            if stat.S_ISLNK(info.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} contains a symlink component: {component}"
                )
            if final:
                if leaf_kind == "directory" and not stat.S_ISDIR(info.st_mode):
                    raise gov.G0GovernanceError(f"{label} is not a directory")
                if leaf_kind == "file" and (
                    not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                ):
                    raise gov.G0GovernanceError(
                        f"{label} is not a direct single-link regular file"
                    )
                return
            if not stat.S_ISDIR(info.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} ancestor is not a directory: {component}"
                )
            child = os.open(component, _directory_flags(), dir_fd=current)
            opened = os.fstat(child)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                os.close(child)
                raise gov.G0GovernanceError(
                    f"{label} ancestor identity changed: {component}"
                )
            os.close(current)
            current = child
    finally:
        os.close(current)


def path_state_rooted(root: Path, path: Path, *, label: str) -> str:
    """Return ABSENT/FILE/DIRECTORY without following any path component."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    current, _ = _open_workspace_root(root)
    try:
        for index, component in enumerate(parts):
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return "ABSENT"
            if stat.S_ISLNK(info.st_mode):
                raise gov.G0GovernanceError(f"{label} is a symlink")
            final = index == len(parts) - 1
            if final:
                if stat.S_ISDIR(info.st_mode):
                    return "DIRECTORY"
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    return "FILE"
                raise gov.G0GovernanceError(
                    f"{label} is not a direct governed path"
                )
            if not stat.S_ISDIR(info.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} ancestor is not a direct directory"
                )
            child = os.open(component, _directory_flags(), dir_fd=current)
            opened = os.fstat(child)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                os.close(child)
                raise gov.G0GovernanceError(f"{label} ancestor identity changed")
            os.close(current)
            current = child
    finally:
        os.close(current)


def _leaf_state(root: Path, path: Path, *, label: str) -> str:
    return path_state_rooted(root, path, label=label)


def _write_all(descriptor: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise gov.G0GovernanceError("short write while publishing G0 evidence")
        remaining = remaining[written:]


def _write_bytes_exclusive_rooted(root: Path, path: Path, data: bytes) -> None:
    parent, name, _absolute, parts, identity = _open_parent(
        root, path, create=True, label="G0 exclusive output"
    )
    try:
        flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
        try:
            descriptor = os.open(name, flags, 0o644, dir_fd=parent)
        except FileExistsError as error:
            raise gov.G0GovernanceError(
                f"refusing to clobber existing G0 file: {path}"
            ) from error
        try:
            _write_all(descriptor, data)
            os.fsync(descriptor)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or opened.st_nlink != 1
                or opened.st_size != len(data)
            ):
                raise gov.G0GovernanceError("published G0 file identity/size mismatch")
            os.lseek(descriptor, 0, os.SEEK_SET)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            if b"".join(chunks) != data:
                raise gov.G0GovernanceError("published G0 file bytes differ")
            reachable = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (
                stat.S_ISLNK(reachable.st_mode)
                or not stat.S_ISREG(reachable.st_mode)
                or reachable.st_nlink != 1
                or reachable.st_dev != opened.st_dev
                or reachable.st_ino != opened.st_ino
                or reachable.st_size != opened.st_size
            ):
                raise gov.G0GovernanceError("published G0 file path identity changed")
            os.fsync(parent)
            final_fd = os.fstat(descriptor)
            final_path = os.stat(name, dir_fd=parent, follow_symlinks=False)
            stable_fields = (
                "st_dev",
                "st_ino",
                "st_size",
                "st_mtime_ns",
                "st_ctime_ns",
                "st_nlink",
            )
            if any(
                getattr(final_fd, field) != getattr(opened, field)
                or getattr(final_path, field) != getattr(opened, field)
                for field in stable_fields
            ) or final_fd.st_nlink != 1:
                raise gov.G0GovernanceError(
                    "published G0 file changed before durable close"
                )
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)
    _assert_parent_reachable(root, parts, identity, label="G0 exclusive output")


def write_json_exclusive_rooted(
    root: Path, path: Path, payload: Mapping[str, Any]
) -> None:
    data = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    _write_bytes_exclusive_rooted(root, path, data)


def publish_json_transactional_rooted(
    root: Path,
    path: Path,
    payload: Mapping[str, Any],
    *,
    guard_records: Sequence[Mapping[str, object]],
    validate: Callable[[], None],
    retain_linked: Callable[[int, str, int, bytes], None] | None = None,
) -> dict[str, object]:
    """Commit one formal JSON leaf under retained inputs and own-inode rollback."""

    try:
        from scripts import p07_backend_formal_io_v1 as formal_io
    except ModuleNotFoundError:
        import p07_backend_formal_io_v1 as formal_io  # type: ignore

    root = root.absolute()
    absolute = gov.workspace_path(root, path, label="transactional formal output")
    relative = absolute.relative_to(root).as_posix()
    content = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    with formal_io.global_formal_lock():
        if formal_io.destination_exists(root, relative):
            raise FileExistsError(relative)
        expected_inputs: list[tuple[Path, bytes, str]] = []
        seen: set[str] = set()
        for index, record in enumerate(guard_records):
            if not isinstance(record, Mapping):
                raise gov.G0GovernanceError(
                    "transactional guard record is malformed"
                )
            guard_path = gov.workspace_path(
                root, record.get("path"), label=f"transactional input {index}"
            )
            display = gov.display_path(root, guard_path)
            if display in seen:
                continue
            observed_bytes, observed_record = (
                read_bytes_and_record_bound_input_rooted(
                    root, guard_path, label=f"transactional input {display}"
                )
            )
            if any(
                type(observed_record.get(key)) is not type(record.get(key))
                or observed_record.get(key) != record.get(key)
                for key in ("path", "sha256", "size_bytes")
            ):
                raise gov.G0GovernanceError(
                    f"transactional input record differs: {display}"
                )
            seen.add(display)
            expected_inputs.append((guard_path, observed_bytes, display))
        with ExitStack() as stack:
            validators = [
                stack.enter_context(
                    retained_bound_input_validator(
                        root, guard_path, expected, label=f"transactional {display}"
                    )
                )
                for guard_path, expected, display in expected_inputs
            ]

            def validate_snapshot() -> None:
                for validator in validators:
                    validator()
                validate()
                for validator in validators:
                    validator()

            validate_snapshot()
            with formal_io._parent_dirfd(root, relative) as (parent_fd, name):
                partial_prefix = f".{name}.partial.{os.getpid()}."
                preexisting = {
                    entry
                    for entry in os.listdir(parent_fd)
                    if entry.startswith(partial_prefix)
                }
                staged_fd = -1
                staged_identity: tuple[int, int] | None = None

                def pre_link_guard() -> None:
                    nonlocal staged_fd, staged_identity
                    candidates = [
                        entry
                        for entry in os.listdir(parent_fd)
                        if entry.startswith(partial_prefix)
                        and entry not in preexisting
                    ]
                    if len(candidates) != 1 or staged_fd >= 0:
                        raise gov.G0GovernanceError(
                            "transactional staged identity is ambiguous"
                        )
                    staged_fd = os.open(
                        candidates[0],
                        os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                        dir_fd=parent_fd,
                    )
                    staged = os.fstat(staged_fd)
                    if (
                        not stat.S_ISREG(staged.st_mode)
                        or staged.st_nlink != 1
                        or staged.st_size != len(content)
                        or _pread_exact(staged_fd, staged.st_size) != content
                    ):
                        raise gov.G0GovernanceError(
                            "transactional staged bytes/identity differ"
                        )
                    staged_identity = (staged.st_dev, staged.st_ino)
                    validate_snapshot()

                def post_link_guard() -> None:
                    linked = os.stat(
                        name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if staged_identity is None or (
                        linked.st_dev,
                        linked.st_ino,
                    ) != staged_identity:
                        raise gov.G0GovernanceError(
                            "transactional destination is not the staged inode"
                        )
                    validate_snapshot()

                def post_unlink_guard() -> None:
                    if staged_fd < 0 or staged_identity is None:
                        raise gov.G0GovernanceError(
                            "transactional staged identity unavailable after unlink"
                        )
                    staged = os.fstat(staged_fd)
                    linked = os.stat(
                        name, dir_fd=parent_fd, follow_symlinks=False
                    )
                    if (
                        staged.st_nlink != 1
                        or linked.st_nlink != 1
                        or (staged.st_dev, staged.st_ino) != staged_identity
                        or (linked.st_dev, linked.st_ino) != staged_identity
                        or _pread_exact(staged_fd, staged.st_size) != content
                    ):
                        raise gov.G0GovernanceError(
                            "transactional destination differs after temporary unlink"
                        )
                    if retain_linked is not None:
                        retain_linked(parent_fd, name, staged_fd, content)
                    validate_snapshot()

                try:
                    publish_kwargs: dict[str, object] = {
                        "pre_link_guard": pre_link_guard,
                        "post_link_guard": post_link_guard,
                    }
                    if retain_linked is not None:
                        publish_kwargs["post_unlink_guard"] = post_unlink_guard
                    result = formal_io.publish_bytes_no_clobber(
                        root, relative, content, **publish_kwargs
                    )
                    validate_snapshot()
                    return result
                except BaseException:
                    if staged_identity is not None:
                        try:
                            current = os.stat(
                                name, dir_fd=parent_fd, follow_symlinks=False
                            )
                        except FileNotFoundError:
                            current = None
                        if current is not None and (
                            current.st_dev,
                            current.st_ino,
                        ) == staged_identity:
                            os.unlink(name, dir_fd=parent_fd)
                            os.fsync(parent_fd)
                    raise
                finally:
                    if staged_fd >= 0:
                        os.close(staged_fd)


def _read_direct_bytes(
    root: Path, path: Path, *, label: str
) -> tuple[bytes, dict[str, object]]:
    parent, name, absolute, parts, identity = _open_parent(
        root, path, create=False, label=label
    )
    try:
        try:
            before = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError as error:
            raise gov.G0GovernanceError(f"missing {label}: {absolute}") from error
        if (
            stat.S_ISLNK(before.st_mode)
            or not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
        ):
            raise gov.G0GovernanceError(
                f"{label} is not a direct single-link regular file: {absolute}"
            )
        descriptor = os.open(
            name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent
        )
        try:
            opened = os.fstat(descriptor)
            if (
                opened.st_dev != before.st_dev
                or opened.st_ino != before.st_ino
                or opened.st_nlink != 1
                or not stat.S_ISREG(opened.st_mode)
            ):
                raise gov.G0GovernanceError(f"{label} identity changed before read")
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            content = b"".join(chunks)
            opened_after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        path_after = os.stat(name, dir_fd=parent, follow_symlinks=False)
        stable = (
            opened_after.st_dev == opened.st_dev
            and opened_after.st_ino == opened.st_ino
            and opened_after.st_size == opened.st_size == len(content)
            and opened_after.st_mtime_ns == opened.st_mtime_ns
            and opened_after.st_ctime_ns == opened.st_ctime_ns
            and opened_after.st_nlink == opened.st_nlink == 1
            and path_after.st_dev == opened.st_dev
            and path_after.st_ino == opened.st_ino
            and path_after.st_nlink == 1
            and stat.S_ISREG(path_after.st_mode)
            and not stat.S_ISLNK(path_after.st_mode)
        )
        if not stable:
            raise gov.G0GovernanceError(f"{label} changed while hashing")
        record = {
            "path": gov.display_path(root, absolute),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        return content, record
    finally:
        os.close(parent)
        _assert_parent_reachable(root, parts, identity, label=label)


def _direct_file_record(root: Path, path: Path, *, label: str) -> dict[str, object]:
    _content, record = _read_direct_bytes(root, path, label=label)
    return record


def direct_file_record_rooted(
    root: Path, path: Path, *, label: str
) -> dict[str, object]:
    return _direct_file_record(root, path, label=label)


def read_bytes_direct_rooted(
    root: Path, path: Path, *, label: str
) -> bytes:
    content, _record = _read_direct_bytes(root, path, label=label)
    return content


def _read_leaf_bytes_at(
    parent: int, name: str, *, absolute: Path, label: str
) -> tuple[bytes, os.stat_result]:
    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError as error:
        raise gov.G0GovernanceError(f"missing {label}: {absolute}") from error
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise gov.G0GovernanceError(
            f"{label} is not a direct single-link regular file: {absolute}"
        )
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent
        )
    except OSError as error:
        raise gov.G0GovernanceError(f"cannot no-follow open {label}: {absolute}") from error
    try:
        opened = os.fstat(descriptor)
        if _identity_tuple(opened) != _identity_tuple(before):
            raise gov.G0GovernanceError(f"{label} identity changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            _identity_tuple(after) != _identity_tuple(opened)
            or after.st_size != len(content)
            or after.st_nlink != 1
        ):
            raise gov.G0GovernanceError(f"{label} changed while reading")
    finally:
        os.close(descriptor)
    reachable = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _identity_tuple(reachable) != _identity_tuple(after):
        raise gov.G0GovernanceError(f"{label} path identity changed after read")
    return content, after


def _hash_leaf_record_at(
    parent: int, name: str, *, absolute: Path, root: Path, label: str
) -> tuple[dict[str, object], os.stat_result]:
    """Stream-hash one retained direct leaf without materializing its bytes."""

    try:
        before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError as error:
        raise gov.G0GovernanceError(f"missing {label}: {absolute}") from error
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise gov.G0GovernanceError(
            f"{label} is not a direct single-link regular file: {absolute}"
        )
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent
        )
    except OSError as error:
        raise gov.G0GovernanceError(f"cannot no-follow open {label}: {absolute}") from error
    digest = hashlib.sha256()
    size = 0
    try:
        opened = os.fstat(descriptor)
        if _identity_tuple(opened) != _identity_tuple(before):
            raise gov.G0GovernanceError(f"{label} identity changed before hashing")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        if _identity_tuple(after) != _identity_tuple(opened) or size != opened.st_size:
            raise gov.G0GovernanceError(f"{label} changed while hashing")
    finally:
        os.close(descriptor)
    reachable = os.stat(name, dir_fd=parent, follow_symlinks=False)
    if _identity_tuple(reachable) != _identity_tuple(after):
        raise gov.G0GovernanceError(f"{label} path identity changed after hashing")
    return {
        "path": gov.display_path(root, absolute),
        "sha256": digest.hexdigest(),
        "size_bytes": size,
    }, after


def _hash_direct_record(
    root: Path, path: Path, *, label: str
) -> dict[str, object]:
    parent, name, absolute, parts, identity = _open_parent(
        root, path, create=False, label=label
    )
    try:
        record, _leaf = _hash_leaf_record_at(
            parent, name, absolute=absolute, root=root, label=label
        )
        return record
    finally:
        os.close(parent)
        _assert_parent_reachable(root, parts, identity, label=label)


def _hash_sanctioned_input_record(
    root: Path, path: Path, *, label: str
) -> dict[str, object]:
    _root, absolute, parts = _workspace_parts(root, path, label=label)
    if len(parts) < 2 or parts[0] not in SANCTIONED_INPUT_ROOT_TARGETS:
        raise gov.G0GovernanceError(f"{label} is not under a sanctioned input root")
    link_name = parts[0]
    expected_target = SANCTIONED_INPUT_ROOT_TARGETS[link_name]
    root_fd, _ = _open_workspace_root(root)
    target_fd = -1
    parent = -1
    try:
        try:
            link_before = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
            link_text = os.readlink(link_name, dir_fd=root_fd)
        except OSError as error:
            raise gov.G0GovernanceError(
                f"{label} canonical input root is unavailable: {link_name}"
            ) from error
        if (
            not stat.S_ISLNK(link_before.st_mode)
            or link_before.st_nlink != 1
            or link_text != os.fspath(expected_target)
        ):
            raise gov.G0GovernanceError(
                f"{label} canonical input root differs from frozen target: {link_name}"
            )
        target_fd = _open_absolute_directory(
            expected_target, label=f"{label} frozen {link_name} target"
        )
        target_identity = os.fstat(target_fd)
        parent = _open_direct_descendant_directory(
            target_fd, parts[1:-1], label=label
        )
        parent_identity = os.fstat(parent)
        record, leaf_identity = _hash_leaf_record_at(
            parent, parts[-1], absolute=absolute, root=root, label=label
        )
        link_after = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if (
            _identity_tuple(link_after) != _identity_tuple(link_before)
            or os.readlink(link_name, dir_fd=root_fd) != link_text
        ):
            raise gov.G0GovernanceError(
                f"{label} canonical input link changed while hashing"
            )
        reopened_target = _open_absolute_directory(
            expected_target, label=f"{label} frozen {link_name} reachability"
        )
        try:
            if _identity_tuple(os.fstat(reopened_target)) != _identity_tuple(
                target_identity
            ):
                raise gov.G0GovernanceError(
                    f"{label} frozen input target changed while hashing"
                )
            reopened_parent = _open_direct_descendant_directory(
                reopened_target, parts[1:-1], label=f"{label} reachability"
            )
            try:
                if _identity_tuple(os.fstat(reopened_parent)) != _identity_tuple(
                    parent_identity
                ):
                    raise gov.G0GovernanceError(
                        f"{label} parent is no longer canonically reachable"
                    )
                reachable_leaf = os.stat(
                    parts[-1], dir_fd=reopened_parent, follow_symlinks=False
                )
                if _identity_tuple(reachable_leaf) != _identity_tuple(leaf_identity):
                    raise gov.G0GovernanceError(
                        f"{label} leaf is no longer canonically reachable"
                    )
            finally:
                os.close(reopened_parent)
        finally:
            os.close(reopened_target)
        return record
    finally:
        if parent >= 0:
            os.close(parent)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(root_fd)


def _read_sanctioned_input_bytes(
    root: Path, path: Path, *, label: str
) -> tuple[bytes, dict[str, object]]:
    """Read through one exact repository-root canonical link, and no others."""

    _root, absolute, parts = _workspace_parts(root, path, label=label)
    if len(parts) < 2 or parts[0] not in SANCTIONED_INPUT_ROOT_TARGETS:
        raise gov.G0GovernanceError(f"{label} is not under a sanctioned input root")
    link_name = parts[0]
    expected_target = SANCTIONED_INPUT_ROOT_TARGETS[link_name]
    root_fd, _ = _open_workspace_root(root)
    target_fd = -1
    parent = -1
    try:
        try:
            link_before = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
            link_text = os.readlink(link_name, dir_fd=root_fd)
        except OSError as error:
            raise gov.G0GovernanceError(
                f"{label} canonical input root is unavailable: {link_name}"
            ) from error
        if (
            not stat.S_ISLNK(link_before.st_mode)
            or link_before.st_nlink != 1
            or link_text != os.fspath(expected_target)
        ):
            raise gov.G0GovernanceError(
                f"{label} canonical input root differs from frozen target: {link_name}"
            )
        target_fd = _open_absolute_directory(
            expected_target, label=f"{label} frozen {link_name} target"
        )
        target_identity = os.fstat(target_fd)
        parent = _open_direct_descendant_directory(
            target_fd, parts[1:-1], label=label
        )
        parent_identity = os.fstat(parent)
        content, leaf_identity = _read_leaf_bytes_at(
            parent, parts[-1], absolute=absolute, label=label
        )

        link_after = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        if (
            _identity_tuple(link_after) != _identity_tuple(link_before)
            or os.readlink(link_name, dir_fd=root_fd) != link_text
        ):
            raise gov.G0GovernanceError(
                f"{label} canonical input link changed while reading"
            )
        reopened_target = _open_absolute_directory(
            expected_target, label=f"{label} frozen {link_name} reachability"
        )
        try:
            if _identity_tuple(os.fstat(reopened_target)) != _identity_tuple(
                target_identity
            ):
                raise gov.G0GovernanceError(
                    f"{label} frozen input target changed while reading"
                )
            reopened_parent = _open_direct_descendant_directory(
                reopened_target, parts[1:-1], label=f"{label} reachability"
            )
            try:
                if _identity_tuple(os.fstat(reopened_parent)) != _identity_tuple(
                    parent_identity
                ):
                    raise gov.G0GovernanceError(
                        f"{label} parent is no longer canonically reachable"
                    )
                reachable_leaf = os.stat(
                    parts[-1], dir_fd=reopened_parent, follow_symlinks=False
                )
                if _identity_tuple(reachable_leaf) != _identity_tuple(leaf_identity):
                    raise gov.G0GovernanceError(
                        f"{label} leaf is no longer canonically reachable"
                    )
            finally:
                os.close(reopened_parent)
        finally:
            os.close(reopened_target)
        return content, {
            "path": gov.display_path(root, absolute),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
    finally:
        if parent >= 0:
            os.close(parent)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(root_fd)


def read_bytes_bound_input_rooted(
    root: Path, path: Path, *, label: str
) -> bytes:
    """Read a bound input directly, allowing only frozen top-level links."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    if parts[0] in SANCTIONED_INPUT_ROOT_TARGETS:
        content, _record = _read_sanctioned_input_bytes(root, path, label=label)
    else:
        content, _record = _read_direct_bytes(root, path, label=label)
    return content


def _pread_exact(descriptor: int, size: int) -> bytes:
    chunks: list[bytes] = []
    offset = 0
    while offset < size:
        chunk = os.pread(descriptor, min(1024 * 1024, size - offset), offset)
        if not chunk:
            break
        chunks.append(chunk)
        offset += len(chunk)
    if offset != size:
        raise gov.G0GovernanceError("short retained governed-input read")
    return b"".join(chunks)


@contextmanager
def retained_bound_input_validator(
    root: Path, path: Path, expected: bytes, *, label: str
) -> Iterator[Callable[[], None]]:
    """Retain one direct or sanctioned-root input through a formal commit."""

    _root, absolute, parts = _workspace_parts(root, path, label=label)
    if parts[0] not in SANCTIONED_INPUT_ROOT_TARGETS:
        parent, name, _absolute, parent_parts, parent_identity = _open_parent(
            root, absolute, create=False, label=label
        )
        leaf = -1
        try:
            leaf = os.open(
                name,
                os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
                dir_fd=parent,
            )
            leaf_identity = os.fstat(leaf)
            if (
                not stat.S_ISREG(leaf_identity.st_mode)
                or leaf_identity.st_nlink != 1
                or _pread_exact(leaf, leaf_identity.st_size) != expected
            ):
                raise gov.G0GovernanceError(
                    f"{label} retained direct input differs"
                )

            def validate() -> None:
                if (
                    os.fstat(parent).st_dev != parent_identity.st_dev
                    or os.fstat(parent).st_ino != parent_identity.st_ino
                    or _identity_tuple(os.fstat(leaf))
                    != _identity_tuple(leaf_identity)
                    or _pread_exact(leaf, leaf_identity.st_size) != expected
                ):
                    raise gov.G0GovernanceError(
                        f"{label} retained direct input drifted"
                    )
                _assert_parent_reachable(
                    root, parent_parts, parent_identity, label=label
                )
                reachable = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if _identity_tuple(reachable) != _identity_tuple(leaf_identity):
                    raise gov.G0GovernanceError(
                        f"{label} retained direct path drifted"
                    )

            validate()
            yield validate
            validate()
        finally:
            if leaf >= 0:
                os.close(leaf)
            os.close(parent)
        return

    if len(parts) < 2:
        raise gov.G0GovernanceError(f"{label} lacks a sanctioned-root child")
    link_name = parts[0]
    expected_target = SANCTIONED_INPUT_ROOT_TARGETS[link_name]
    root_fd, _ = _open_workspace_root(root)
    target_fd = -1
    parent = -1
    leaf = -1
    try:
        link_identity = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
        link_text = os.readlink(link_name, dir_fd=root_fd)
        if (
            not stat.S_ISLNK(link_identity.st_mode)
            or link_identity.st_nlink != 1
            or link_text != os.fspath(expected_target)
        ):
            raise gov.G0GovernanceError(
                f"{label} sanctioned root differs from frozen target"
            )
        target_fd = _open_absolute_directory(
            expected_target, label=f"{label} frozen target"
        )
        target_identity = os.fstat(target_fd)
        parent = _open_direct_descendant_directory(
            target_fd, parts[1:-1], label=label
        )
        parent_identity = os.fstat(parent)
        leaf = os.open(
            parts[-1],
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=parent,
        )
        leaf_identity = os.fstat(leaf)
        if (
            not stat.S_ISREG(leaf_identity.st_mode)
            or leaf_identity.st_nlink != 1
            or _pread_exact(leaf, leaf_identity.st_size) != expected
        ):
            raise gov.G0GovernanceError(
                f"{label} retained sanctioned input differs"
            )

        def validate() -> None:
            current_link = os.stat(
                link_name, dir_fd=root_fd, follow_symlinks=False
            )
            if (
                _identity_tuple(current_link) != _identity_tuple(link_identity)
                or os.readlink(link_name, dir_fd=root_fd) != link_text
                or os.fstat(target_fd).st_dev != target_identity.st_dev
                or os.fstat(target_fd).st_ino != target_identity.st_ino
                or os.fstat(parent).st_dev != parent_identity.st_dev
                or os.fstat(parent).st_ino != parent_identity.st_ino
                or _identity_tuple(os.fstat(leaf))
                != _identity_tuple(leaf_identity)
                or _pread_exact(leaf, leaf_identity.st_size) != expected
            ):
                raise gov.G0GovernanceError(
                    f"{label} retained sanctioned input drifted"
                )
            reopened_target = _open_absolute_directory(
                expected_target, label=f"{label} frozen target reachability"
            )
            try:
                if (
                    os.fstat(reopened_target).st_dev != target_identity.st_dev
                    or os.fstat(reopened_target).st_ino != target_identity.st_ino
                ):
                    raise gov.G0GovernanceError(
                        f"{label} sanctioned target path drifted"
                    )
                reopened_parent = _open_direct_descendant_directory(
                    reopened_target, parts[1:-1], label=f"{label} reachability"
                )
                try:
                    reachable = os.stat(
                        parts[-1],
                        dir_fd=reopened_parent,
                        follow_symlinks=False,
                    )
                    if (
                        os.fstat(reopened_parent).st_dev != parent_identity.st_dev
                        or os.fstat(reopened_parent).st_ino != parent_identity.st_ino
                        or _identity_tuple(reachable)
                        != _identity_tuple(leaf_identity)
                    ):
                        raise gov.G0GovernanceError(
                            f"{label} sanctioned input path drifted"
                        )
                finally:
                    os.close(reopened_parent)
            finally:
                os.close(reopened_target)

        validate()
        yield validate
        validate()
    finally:
        if leaf >= 0:
            os.close(leaf)
        if parent >= 0:
            os.close(parent)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(root_fd)


def path_state_bound_input_rooted(
    root: Path, path: Path, *, label: str
) -> str:
    """Return ABSENT/FILE/DIRECTORY through an exact sanctioned root link.

    Direct workspace paths retain the stricter ``path_state_rooted`` behavior.
    For ``logs``/``datasets`` the only allowed symlink is the frozen top-level
    canonical link; every descendant is opened without following links.
    """

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    if parts[0] not in SANCTIONED_INPUT_ROOT_TARGETS:
        return path_state_rooted(root, path, label=label)
    if len(parts) < 2:
        raise gov.G0GovernanceError(f"{label} must name a sanctioned descendant")
    link_name = parts[0]
    expected_target = SANCTIONED_INPUT_ROOT_TARGETS[link_name]
    root_fd, _ = _open_workspace_root(root)
    target_fd = -1
    current = -1
    try:
        try:
            link_before = os.stat(link_name, dir_fd=root_fd, follow_symlinks=False)
            link_text = os.readlink(link_name, dir_fd=root_fd)
        except OSError as error:
            raise gov.G0GovernanceError(
                f"{label} canonical input root is unavailable: {link_name}"
            ) from error
        if (
            not stat.S_ISLNK(link_before.st_mode)
            or link_before.st_nlink != 1
            or link_text != os.fspath(expected_target)
        ):
            raise gov.G0GovernanceError(
                f"{label} canonical input root differs from frozen target: {link_name}"
            )
        target_fd = _open_absolute_directory(
            expected_target, label=f"{label} frozen {link_name} target"
        )
        target_identity = _identity_tuple(os.fstat(target_fd))

        def assert_state_reachable(
            traversed: Sequence[str],
            leaf: str,
            expected_leaf: os.stat_result | None,
        ) -> None:
            link_after = os.stat(
                link_name, dir_fd=root_fd, follow_symlinks=False
            )
            if (
                _identity_tuple(link_after) != _identity_tuple(link_before)
                or os.readlink(link_name, dir_fd=root_fd) != link_text
            ):
                raise gov.G0GovernanceError(
                    f"{label} canonical input link changed during inspection"
                )
            reopened = _open_absolute_directory(
                expected_target,
                label=f"{label} frozen {link_name} reachability",
            )
            try:
                if _identity_tuple(os.fstat(reopened)) != target_identity:
                    raise gov.G0GovernanceError(
                        f"{label} frozen input target changed during inspection"
                    )
                reopened_parent = _open_direct_descendant_directory(
                    reopened, traversed, label=f"{label} state reachability"
                )
                try:
                    if _identity_tuple(os.fstat(reopened_parent)) != _identity_tuple(
                        os.fstat(current)
                    ):
                        raise gov.G0GovernanceError(
                            f"{label} inspected parent is no longer reachable"
                        )
                    try:
                        reachable_leaf = os.stat(
                            leaf,
                            dir_fd=reopened_parent,
                            follow_symlinks=False,
                        )
                    except FileNotFoundError:
                        if expected_leaf is not None:
                            raise gov.G0GovernanceError(
                                f"{label} leaf disappeared during inspection"
                            )
                    else:
                        if expected_leaf is None or _identity_tuple(
                            reachable_leaf
                        ) != _identity_tuple(expected_leaf):
                            raise gov.G0GovernanceError(
                                f"{label} leaf state changed during inspection"
                            )
                finally:
                    os.close(reopened_parent)
            finally:
                os.close(reopened)

        current = os.dup(target_fd)
        for index, component in enumerate(parts[1:]):
            try:
                info = os.stat(component, dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                assert_state_reachable(parts[1 : 1 + index], component, None)
                return "ABSENT"
            if stat.S_ISLNK(info.st_mode):
                raise gov.G0GovernanceError(f"{label} contains a nested symlink")
            final = index == len(parts[1:]) - 1
            if final:
                if stat.S_ISDIR(info.st_mode):
                    state = "DIRECTORY"
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    state = "FILE"
                else:
                    raise gov.G0GovernanceError(
                        f"{label} is not a direct governed path"
                    )
                assert_state_reachable(parts[1:-1], component, info)
                return state
            if not stat.S_ISDIR(info.st_mode):
                raise gov.G0GovernanceError(
                    f"{label} ancestor is not a direct directory"
                )
            child = os.open(component, _directory_flags(), dir_fd=current)
            opened = os.fstat(child)
            if _identity_tuple(opened) != _identity_tuple(info):
                os.close(child)
                raise gov.G0GovernanceError(f"{label} ancestor identity changed")
            os.close(current)
            current = child
        raise gov.G0GovernanceError(f"{label} has no leaf")
    finally:
        if current >= 0:
            os.close(current)
        if target_fd >= 0:
            os.close(target_fd)
        os.close(root_fd)


def read_bytes_and_record_bound_input_rooted(
    root: Path, path: Path, *, label: str
) -> tuple[bytes, dict[str, object]]:
    """Return one stable byte snapshot and its exact record."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    if parts[0] in SANCTIONED_INPUT_ROOT_TARGETS:
        return _read_sanctioned_input_bytes(root, path, label=label)
    return _read_direct_bytes(root, path, label=label)


def direct_file_record_bound_input_rooted(
    root: Path, path: Path, *, label: str
) -> dict[str, object]:
    """Record a direct input or an exact sanctioned-root input."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    if parts[0] in SANCTIONED_INPUT_ROOT_TARGETS:
        return _hash_sanctioned_input_record(root, path, label=label)
    return _hash_direct_record(root, path, label=label)


def _read_direct_json(root: Path, path: Path, *, label: str) -> dict[str, Any]:
    content, _record = _read_direct_bytes(root, path, label=label)
    return gov._json_object_bytes(content, label=label)


def read_json_direct_rooted(
    root: Path, path: Path, *, label: str
) -> dict[str, Any]:
    """Read one governed JSON file without following any workspace component."""

    return _read_direct_json(root, path, label=label)


def create_workspace_directory(
    root: Path, path: Path, *, create_parents: bool, label: str
) -> None:
    parent, name, _absolute, parts, identity = _open_parent(
        root, path, create=create_parents, label=label
    )
    try:
        try:
            os.mkdir(name, 0o755, dir_fd=parent)
        except FileExistsError as error:
            raise gov.G0GovernanceError(f"refusing existing {label}: {path}") from error
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise gov.G0GovernanceError(f"created {label} is not a direct directory")
        child = os.open(name, _directory_flags(), dir_fd=parent)
        try:
            opened = os.fstat(child)
            if opened.st_dev != info.st_dev or opened.st_ino != info.st_ino:
                raise gov.G0GovernanceError(f"created {label} identity changed")
            os.fsync(child)
        finally:
            os.close(child)
        os.fsync(parent)
    finally:
        os.close(parent)
    _assert_parent_reachable(root, parts, identity, label=label)


def list_direct_regular_files_rooted(
    root: Path, directory: Path, *, label: str
) -> list[str]:
    """List a flat governed directory, rejecting links, subdirs, and races."""

    _root, _absolute, parts = _workspace_parts(root, directory, label=label)
    descriptor, _ = _open_directory_chain(
        root, parts, create=False, label=label
    )
    identity = os.fstat(descriptor)
    try:
        names = sorted(os.listdir(descriptor))
        for name in names:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
            ):
                raise gov.G0GovernanceError(
                    f"{label} contains a non-direct regular file: {name}"
                )
        after = os.fstat(descriptor)
        if (
            after.st_dev != identity.st_dev
            or after.st_ino != identity.st_ino
            or after.st_mtime_ns != identity.st_mtime_ns
            or after.st_ctime_ns != identity.st_ctime_ns
        ):
            raise gov.G0GovernanceError(f"{label} changed during inventory")
    finally:
        os.close(descriptor)
    _assert_directory_reachable(root, parts, identity, label=label)
    return names


@contextmanager
def retained_workspace_directory(
    root: Path,
    path: Path,
    *,
    label: str,
    relocated_to: Path | None = None,
) -> Iterator[int]:
    """Hold one no-follow workspace directory across an external operation."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    descriptor, _ = _open_directory_chain(
        root, parts, create=False, label=label
    )
    identity = os.fstat(descriptor)
    try:
        yield descriptor
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if after.st_dev != identity.st_dev or after.st_ino != identity.st_ino:
            raise gov.G0GovernanceError(f"{label} retained identity changed")
        try:
            _assert_directory_reachable(root, parts, identity, label=label)
        except gov.G0GovernanceError:
            if relocated_to is None:
                raise
            assert_retained_workspace_directory(
                root, relocated_to, descriptor, label=f"{label} relocated"
            )
    finally:
        os.close(descriptor)


def assert_retained_workspace_directory(
    root: Path, path: Path, descriptor: int, *, label: str
) -> None:
    """Require that ``path`` still names the exact retained directory FD."""

    _root, _absolute, parts = _workspace_parts(root, path, label=label)
    identity = os.fstat(descriptor)
    if not stat.S_ISDIR(identity.st_mode):
        raise gov.G0GovernanceError(f"{label} retained FD is not a directory")
    _assert_directory_reachable(root, parts, identity, label=label)


def read_json_retained_directory(
    descriptor: int, name: str, *, label: str
) -> dict[str, Any]:
    """Read one direct JSON child from an already retained directory."""

    if not name or "/" in name or name in {".", ".."}:
        raise gov.G0GovernanceError(f"unsafe retained {label} name")
    try:
        before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
    except FileNotFoundError as error:
        raise gov.G0GovernanceError(f"missing retained {label}: {name}") from error
    content, _identity = _read_regular_at(
        descriptor, name, before, label=label, durable=False
    )
    return gov._json_object_bytes(
        content, label=f"retained {label}", require_canonical=False
    )


def _write_bytes_exclusive_retained_directory(
    descriptor: int, name: str, data: bytes, *, label: str
) -> dict[str, object]:
    if not name or "/" in name or name in {".", ".."}:
        raise gov.G0GovernanceError(f"unsafe retained {label} name")
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        child = os.open(name, flags, 0o644, dir_fd=descriptor)
    except FileExistsError as error:
        raise gov.G0GovernanceError(
            f"refusing to clobber retained {label}: {name}"
        ) from error
    try:
        _write_all(child, data)
        os.fsync(child)
        opened = os.fstat(child)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size != len(data)
        ):
            raise gov.G0GovernanceError(f"retained {label} identity differs")
        os.lseek(child, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(child, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        if b"".join(chunks) != data:
            raise gov.G0GovernanceError(f"retained {label} bytes differ")
        reachable = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if _stat_token(reachable) != _stat_token(opened):
            raise gov.G0GovernanceError(f"retained {label} path identity changed")
        os.fsync(descriptor)
        final_fd = os.fstat(child)
        final_path = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
        if (
            _stat_token(final_fd) != _stat_token(opened)
            or _stat_token(final_path) != _stat_token(opened)
        ):
            raise gov.G0GovernanceError(f"retained {label} changed before close")
    finally:
        os.close(child)
    return {
        "path": name,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def write_json_exclusive_retained_directory(
    descriptor: int, name: str, payload: Mapping[str, Any], *, label: str
) -> dict[str, object]:
    data = json.dumps(
        payload,
        indent=2,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    return _write_bytes_exclusive_retained_directory(
        descriptor, name, data, label=label
    )


def publication_paths(
    output_dir: Path, *, job_hash: str
) -> tuple[Path, Path, Path]:
    """Return deterministic staging, intent, and closeout sibling paths."""

    digest = gov.require_hash(job_hash, "job_hash")
    output_dir = Path(os.path.abspath(os.fspath(output_dir)))
    stem = f".{output_dir.name}.{digest[:16]}"
    return (
        output_dir.with_name(stem + ".staging"),
        output_dir.with_name(stem + ".publication_intent_v1.json"),
        output_dir.with_name(stem + ".publication_closeout_v1.json"),
    )


def build_publication_intent(
    *,
    root: Path,
    job_id: str,
    job_hash: str,
    plan_hash: str,
    evaluation_lock_hash: str,
    backend_execution_lock_hash: str,
    g0_execution_authority_hash: str,
    evaluation_disposition: str,
    output_dir: Path,
) -> dict[str, Any]:
    if not isinstance(job_id, str) or gov.SAFE_ID_RE.fullmatch(job_id) is None:
        raise gov.G0GovernanceError("unsafe publication job_id")
    for label, value in (
        ("job_hash", job_hash),
        ("plan_hash", plan_hash),
        ("evaluation_lock_hash", evaluation_lock_hash),
        ("backend_execution_lock_hash", backend_execution_lock_hash),
        ("g0_execution_authority_hash", g0_execution_authority_hash),
    ):
        gov.require_hash(value, label)
    if evaluation_disposition not in (
        "EVALUATE_NUMERIC",
        "SKIP_NUMERIC_HARD_FAILURE",
    ):
        raise gov.G0GovernanceError("invalid publication disposition")
    destination = gov.workspace_path(
        root, output_dir, label="publication destination", require_absolute=True
    )
    staging, intent_path, closeout_path = publication_paths(
        destination, job_hash=job_hash
    )
    for label, path in (
        ("publication staging", staging),
        ("publication intent", intent_path),
        ("publication closeout", closeout_path),
    ):
        gov.workspace_path(root, path, label=label, require_absolute=True)
    payload: dict[str, Any] = {
        "schema_version": gov.PUBLICATION_INTENT_SCHEMA,
        "status": INTENT_STATUS,
        "job_id": job_id,
        "job_hash": job_hash,
        "plan_hash": plan_hash,
        "evaluation_lock_hash": evaluation_lock_hash,
        "backend_execution_lock_hash": backend_execution_lock_hash,
        "g0_execution_authority_hash": g0_execution_authority_hash,
        "evaluation_disposition": evaluation_disposition,
        "destination_absolute": os.fspath(destination),
        "staging_absolute": os.fspath(staging),
        "intent_path_absolute": os.fspath(intent_path),
        "closeout_path_absolute": os.fspath(closeout_path),
        "publication_policy": dict(PUBLICATION_POLICY),
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    payload["publication_intent_hash"] = gov.canonical_json_hash(payload)
    validate_publication_intent(payload, root=root)
    return payload


def validate_publication_intent(
    payload: Mapping[str, Any], *, root: Path
) -> str:
    if (
        payload.get("schema_version") != gov.PUBLICATION_INTENT_SCHEMA
        or payload.get("status") != INTENT_STATUS
    ):
        raise gov.G0GovernanceError("unexpected publication intent schema/status")
    digest = gov.validate_self_hash(
        payload, "publication_intent_hash", label="publication intent"
    )
    expected_keys = {
        "schema_version",
        "status",
        "job_id",
        "job_hash",
        "plan_hash",
        "evaluation_lock_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
        "evaluation_disposition",
        "destination_absolute",
        "staging_absolute",
        "intent_path_absolute",
        "closeout_path_absolute",
        "publication_policy",
        "outcome_boundary",
        "publication_intent_hash",
    }
    if set(payload) != expected_keys:
        raise gov.G0GovernanceError("publication intent key set mismatch")
    if payload.get("publication_policy") != PUBLICATION_POLICY:
        raise gov.G0GovernanceError("publication intent policy mismatch")
    if payload.get("evaluation_disposition") not in (
        "EVALUATE_NUMERIC",
        "SKIP_NUMERIC_HARD_FAILURE",
    ):
        raise gov.G0GovernanceError("publication intent disposition mismatch")
    if not isinstance(payload.get("job_id"), str) or gov.SAFE_ID_RE.fullmatch(
        str(payload.get("job_id"))
    ) is None:
        raise gov.G0GovernanceError("unsafe publication intent job_id")
    for key in (
        "job_hash",
        "plan_hash",
        "evaluation_lock_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
    ):
        gov.require_hash(payload.get(key), f"publication intent {key}")
    destination = gov.workspace_path(
        root,
        payload.get("destination_absolute"),
        label="publication destination",
        require_absolute=True,
    )
    staging = gov.workspace_path(
        root,
        payload.get("staging_absolute"),
        label="publication staging",
        require_absolute=True,
    )
    expected = publication_paths(destination, job_hash=str(payload["job_hash"]))
    observed = (
        staging,
        gov.workspace_path(
            root,
            payload.get("intent_path_absolute"),
            label="publication intent path",
            require_absolute=True,
        ),
        gov.workspace_path(
            root,
            payload.get("closeout_path_absolute"),
            label="publication closeout path",
            require_absolute=True,
        ),
    )
    if observed != expected or staging.parent != destination.parent:
        raise gov.G0GovernanceError("publication paths differ from deterministic contract")
    for label, path, kind in (
        ("publication destination", destination, "directory"),
        ("publication staging", staging, "directory"),
        ("publication intent", observed[1], "file"),
        ("publication closeout", observed[2], "file"),
    ):
        _assert_safe_path(root, path, label=label, leaf_kind=kind)
    if payload.get("outcome_boundary") != gov.OUTCOME_BOUNDARY:
        raise gov.G0GovernanceError("publication intent outcome boundary mismatch")
    return digest


def create_publication_intent(path: Path, payload: Mapping[str, Any], *, root: Path) -> None:
    validate_publication_intent(payload, root=root)
    expected = Path(str(payload["intent_path_absolute"]))
    if Path(os.path.abspath(os.fspath(path))) != expected:
        raise gov.G0GovernanceError("publication intent path differs from payload")
    destination = Path(str(payload["destination_absolute"]))
    staging = Path(str(payload["staging_absolute"]))
    closeout = Path(str(payload["closeout_path_absolute"]))
    # Creating the parent chain is itself root-anchored.  Lexists semantics are
    # deliberate: dangling symlinks and special files are evidence/collisions.
    parent, _name, _absolute, parts, identity = _open_parent(
        root, expected, create=True, label="publication intent"
    )
    try:
        for label, candidate in (
            ("destination", destination),
            ("staging", staging),
            ("closeout", closeout),
            ("intent", expected),
        ):
            try:
                os.stat(candidate.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise gov.G0GovernanceError(
                f"publication {label} already contains evidence"
            )
    finally:
        os.close(parent)
        _assert_parent_reachable(root, parts, identity, label="publication intent")
    write_json_exclusive_rooted(root, path, payload)
    if any(
        _leaf_state(root, candidate, label=f"publication {label}") != "ABSENT"
        for label, candidate in (
            ("destination", destination),
            ("staging", staging),
            ("closeout", closeout),
        )
    ):
        raise gov.G0GovernanceError("publication paths already contain evidence")


def _stat_token(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _read_regular_at(
    parent: int,
    name: str,
    before: os.stat_result,
    *,
    label: str,
    durable: bool,
) -> tuple[bytes, tuple[object, ...]]:
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_nlink != 1
    ):
        raise gov.G0GovernanceError(f"{label} is not a direct single-link file")
    descriptor = os.open(
        name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent
    )
    try:
        opened = os.fstat(descriptor)
        if _stat_token(opened) != _stat_token(before):
            raise gov.G0GovernanceError(f"{label} identity changed before read")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        content = b"".join(chunks)
        if durable:
            os.fsync(descriptor)
        after_fd = os.fstat(descriptor)
        after_path = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (
            _stat_token(after_fd) != _stat_token(opened)
            or _stat_token(after_path) != _stat_token(opened)
            or len(content) != opened.st_size
        ):
            raise gov.G0GovernanceError(f"{label} changed during direct read")
        digest = hashlib.sha256(content).hexdigest()
        return content, (*_stat_token(opened), digest)
    finally:
        os.close(descriptor)


def _inventory_open_result(
    top: int, *, durable: bool
) -> tuple[
    list[dict[str, object]],
    dict[str, tuple[object, ...]],
    dict[str, bytes],
    dict[str, bytes],
]:
    records: list[dict[str, object]] = []
    identities: dict[str, tuple[object, ...]] = {}
    seals: dict[str, bytes] = {}
    payload_bytes: dict[str, bytes] = {}

    def walk(descriptor: int, relative_parts: tuple[str, ...]) -> None:
        directory_before = os.fstat(descriptor)
        names = sorted(os.listdir(descriptor))
        for name in names:
            info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            relative = (*relative_parts, name)
            relative_text = "/".join(relative)
            if stat.S_ISLNK(info.st_mode):
                raise gov.G0GovernanceError(
                    f"symlink forbidden in G0 result: {relative_text}"
                )
            if stat.S_ISDIR(info.st_mode):
                child = os.open(name, _directory_flags(), dir_fd=descriptor)
                try:
                    opened = os.fstat(child)
                    if _stat_token(opened) != _stat_token(info):
                        raise gov.G0GovernanceError(
                            f"G0 result directory identity changed: {relative_text}"
                        )
                    walk(child, relative)
                    after_path = os.stat(
                        name, dir_fd=descriptor, follow_symlinks=False
                    )
                    after_fd = os.fstat(child)
                    if (
                        _stat_token(after_path) != _stat_token(opened)
                        or _stat_token(after_fd) != _stat_token(opened)
                    ):
                        raise gov.G0GovernanceError(
                            f"G0 result directory changed: {relative_text}"
                        )
                finally:
                    os.close(child)
                continue
            content, identity = _read_regular_at(
                descriptor,
                name,
                info,
                label=f"G0 result artifact {relative_text}",
                durable=durable,
            )
            identities[relative_text] = identity
            if relative_text in (MANIFEST_NAME, RECEIPT_NAME):
                seals[relative_text] = content
            else:
                payload_bytes[relative_text] = content
                records.append(
                    {
                        "path": relative_text,
                        "sha256": identity[-1],
                        "size_bytes": len(content),
                    }
                )
        if durable:
            os.fsync(descriptor)
        directory_after = os.fstat(descriptor)
        if _stat_token(directory_after) != _stat_token(directory_before):
            raise gov.G0GovernanceError(
                "G0 result directory changed during inventory"
            )
        directory_key = "/".join(relative_parts) or "."
        identities[f"DIR:{directory_key}"] = _stat_token(directory_after)

    walk(top, ())
    records.sort(key=lambda record: str(record["path"]))
    if not any(record["path"] == BOUND_SUMMARY_NAME for record in records):
        raise gov.G0GovernanceError("staging result lacks bound summary")
    return records, identities, seals, payload_bytes


def _same_result_inventory_after_directory_rename(
    before: tuple[
        list[dict[str, object]],
        dict[str, tuple[object, ...]],
        dict[str, bytes],
        dict[str, bytes],
    ],
    after: tuple[
        list[dict[str, object]],
        dict[str, tuple[object, ...]],
        dict[str, bytes],
        dict[str, bytes],
    ],
) -> bool:
    """Compare sealed contents while permitting only top-dir rename ctime drift."""

    before_records, before_identities, before_seals, before_payload = before
    after_records, after_identities, after_seals, after_payload = after
    if (
        before_records != after_records
        or before_seals != after_seals
        or before_payload != after_payload
        or set(before_identities) != set(after_identities)
    ):
        return False
    for name, expected in before_identities.items():
        observed = after_identities[name]
        if name == "DIR:.":
            # rename(2) may update only the renamed top directory's ctime.
            # Its device/inode/mode/nlink/size/mtime must still be exact;
            # every payload and descendant identity remains fully exact.
            if expected[:6] != observed[:6]:
                return False
        elif expected != observed:
            return False
    return True


def _open_result_directory(
    root: Path, directory: Path
) -> tuple[int, tuple[str, ...], os.stat_result]:
    _root, _absolute, parts = _workspace_parts(
        root, directory, label="G0 result directory"
    )
    top, _ = _open_directory_chain(
        root, parts, create=False, label="G0 result directory"
    )
    return top, parts, os.fstat(top)


def _payload_records(root: Path, directory: Path) -> list[dict[str, object]]:
    """Inventory and durably flush every payload through one retained dirfd."""

    top, parts, identity = _open_result_directory(root, directory)
    try:
        records, _identities, _seals, _payload_bytes = _inventory_open_result(
            top, durable=True
        )
    finally:
        os.close(top)
    _assert_directory_reachable(root, parts, identity, label="G0 result directory")
    return records


def _sealed_snapshot(
    root: Path, directory: Path
) -> tuple[list[dict[str, object]], bytes, bytes]:
    """Take two identical retained-dirfd snapshots around all seal files."""

    top, parts, identity = _open_result_directory(root, directory)
    try:
        first = _inventory_open_result(top, durable=True)
        second = _inventory_open_result(top, durable=True)
        if first != second:
            raise gov.G0GovernanceError(
                "G0 sealed result changed across retained-FD snapshots"
            )
        records, _identities, seals, _payload_bytes = second
        if set(seals) != {MANIFEST_NAME, RECEIPT_NAME}:
            raise gov.G0GovernanceError("G0 sealed result lacks exact seal files")
    finally:
        os.close(top)
    _assert_directory_reachable(root, parts, identity, label="G0 sealed result")
    return records, seals[MANIFEST_NAME], seals[RECEIPT_NAME]


def seal_staging_result_retained(
    intent: Mapping[str, Any], *, root: Path, staging_fd: int
) -> dict[str, Any]:
    """Seal the exact staging inode held by ``staging_fd`` without path reopen."""

    intent_hash = validate_publication_intent(intent, root=root)
    staging = Path(str(intent["staging_absolute"]))
    destination = Path(str(intent["destination_absolute"]))
    assert_retained_workspace_directory(
        root, staging, staging_fd, label="retained G0 staging"
    )
    if _leaf_state(root, destination, label="publication destination") != "ABSENT":
        raise gov.G0GovernanceError("destination exists before retained staging seal")
    for name in (MANIFEST_NAME, RECEIPT_NAME):
        try:
            os.stat(name, dir_fd=staging_fd, follow_symlinks=False)
        except FileNotFoundError:
            continue
        raise gov.G0GovernanceError("retained staging already has seal evidence")
    records, _identities, seals, _payload_bytes = _inventory_open_result(
        staging_fd, durable=True
    )
    if seals:
        raise gov.G0GovernanceError("retained staging unexpectedly has seal evidence")
    manifest_bytes = gov.render_sha256_manifest(records)
    manifest_record = _write_bytes_exclusive_retained_directory(
        staging_fd,
        MANIFEST_NAME,
        manifest_bytes,
        label="retained staging output manifest",
    )
    receipt: dict[str, Any] = {
        "schema_version": gov.RESULT_RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent_hash,
        "evaluation_disposition": intent["evaluation_disposition"],
        "destination_absolute": intent["destination_absolute"],
        "payload_records": records,
        "output_manifest": {
            "path": gov.display_path(root, destination / MANIFEST_NAME),
            "sha256": manifest_record["sha256"],
            "size_bytes": manifest_record["size_bytes"],
        },
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    receipt["result_receipt_hash"] = gov.canonical_json_hash(receipt)
    write_json_exclusive_retained_directory(
        staging_fd,
        RECEIPT_NAME,
        receipt,
        label="retained staging result receipt",
    )
    first = _inventory_open_result(staging_fd, durable=True)
    second = _inventory_open_result(staging_fd, durable=True)
    if first != second:
        raise gov.G0GovernanceError(
            "retained G0 sealed result changed across snapshots"
        )
    sealed_records, _sealed_identities, sealed_files, _sealed_payload_bytes = second
    if set(sealed_files) != {MANIFEST_NAME, RECEIPT_NAME}:
        raise gov.G0GovernanceError("retained G0 sealed result lacks exact seal files")
    _validate_sealed_components(
        sealed_records,
        sealed_files[MANIFEST_NAME],
        sealed_files[RECEIPT_NAME],
        intent=intent,
        root=root,
    )
    assert_retained_workspace_directory(
        root, staging, staging_fd, label="retained sealed G0 staging"
    )
    return receipt


def seal_staging_result(
    intent: Mapping[str, Any], *, root: Path
) -> dict[str, Any]:
    intent_hash = validate_publication_intent(intent, root=root)
    staging = Path(str(intent["staging_absolute"]))
    destination = Path(str(intent["destination_absolute"]))
    if _leaf_state(root, destination, label="publication destination") != "ABSENT":
        raise gov.G0GovernanceError("destination exists before staging seal")
    if _leaf_state(root, staging, label="publication staging") != "DIRECTORY":
        raise gov.G0GovernanceError("publication staging directory is missing")
    manifest_path = staging / MANIFEST_NAME
    receipt_path = staging / RECEIPT_NAME
    if any(
        _leaf_state(root, path, label=label) != "ABSENT"
        for path, label in (
            (manifest_path, "staging output manifest"),
            (receipt_path, "staging result receipt"),
        )
    ):
        raise gov.G0GovernanceError("staging already has seal evidence")
    records = _payload_records(root, staging)
    manifest_bytes = gov.render_sha256_manifest(records)
    _write_bytes_exclusive_rooted(root, manifest_path, manifest_bytes)
    manifest_record = _direct_file_record(
        root, manifest_path, label="staging output manifest"
    )
    receipt: dict[str, Any] = {
        "schema_version": gov.RESULT_RECEIPT_SCHEMA,
        "status": RECEIPT_STATUS,
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent_hash,
        "evaluation_disposition": intent["evaluation_disposition"],
        "destination_absolute": intent["destination_absolute"],
        "payload_records": records,
        # Bind the immutable final path while hashing the byte-identical
        # staging file.  A directory rename changes no file bytes.
        "output_manifest": {
            "path": gov.display_path(root, destination / MANIFEST_NAME),
            "sha256": manifest_record["sha256"],
            "size_bytes": manifest_record["size_bytes"],
        },
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    receipt["result_receipt_hash"] = gov.canonical_json_hash(receipt)
    write_json_exclusive_rooted(root, receipt_path, receipt)
    validate_sealed_result(staging, intent=intent, root=root)
    return receipt


def validate_result_receipt(
    payload: Mapping[str, Any], *, intent: Mapping[str, Any]
) -> str:
    if (
        payload.get("schema_version") != gov.RESULT_RECEIPT_SCHEMA
        or payload.get("status") != RECEIPT_STATUS
    ):
        raise gov.G0GovernanceError("unexpected result receipt schema/status")
    digest = gov.validate_self_hash(payload, "result_receipt_hash", label="result receipt")
    expected_keys = {
        "schema_version",
        "status",
        "job_id",
        "job_hash",
        "plan_hash",
        "evaluation_lock_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
        "publication_intent_hash",
        "evaluation_disposition",
        "destination_absolute",
        "payload_records",
        "output_manifest",
        "outcome_boundary",
        "result_receipt_hash",
    }
    if set(payload) != expected_keys:
        raise gov.G0GovernanceError("result receipt key set mismatch")
    expected = {
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "evaluation_disposition": intent["evaluation_disposition"],
        "destination_absolute": intent["destination_absolute"],
    }
    gov.exact_json_identity(payload, expected, label="result receipt")
    records = payload.get("payload_records")
    if not isinstance(records, list) or not records:
        raise gov.G0GovernanceError("result receipt has no payload records")
    if payload.get("outcome_boundary") != gov.OUTCOME_BOUNDARY:
        raise gov.G0GovernanceError("result receipt outcome boundary mismatch")
    manifest = payload.get("output_manifest")
    if not isinstance(manifest, Mapping) or set(manifest) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise gov.G0GovernanceError("result receipt manifest binding shape mismatch")
    return digest


def _validate_sealed_components(
    records: list[dict[str, object]],
    manifest_bytes: bytes,
    receipt_bytes: bytes,
    *,
    intent: Mapping[str, Any],
    root: Path,
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    receipt = gov._json_object_bytes(
        receipt_bytes, label="retained-snapshot result receipt"
    )
    validate_result_receipt(receipt, intent=intent)
    if manifest_bytes != gov.render_sha256_manifest(records):
        raise gov.G0GovernanceError("G0 output manifest differs from direct inventory")
    if records != receipt.get("payload_records"):
        raise gov.G0GovernanceError("receipt payload differs from output manifest")
    manifest_record = receipt.get("output_manifest")
    if not isinstance(manifest_record, Mapping):
        raise gov.G0GovernanceError("result receipt lacks manifest binding")
    expected_manifest = {
        "path": gov.display_path(
            root, Path(str(intent["destination_absolute"])) / MANIFEST_NAME
        ),
        "sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "size_bytes": len(manifest_bytes),
    }
    if dict(manifest_record) != expected_manifest:
        raise gov.G0GovernanceError("result receipt manifest binding mismatch")
    return receipt, records


def validate_sealed_result(
    directory: Path, *, intent: Mapping[str, Any], root: Path
) -> tuple[dict[str, Any], list[dict[str, object]]]:
    validate_publication_intent(intent, root=root)
    directory = Path(os.path.abspath(os.fspath(directory)))
    allowed = {
        Path(str(intent["staging_absolute"])),
        Path(str(intent["destination_absolute"])),
    }
    if directory not in allowed:
        raise gov.G0GovernanceError("sealed result is not an allowed result directory")
    if _leaf_state(root, directory, label="sealed result") != "DIRECTORY":
        raise gov.G0GovernanceError("sealed result is not a direct result directory")
    records, manifest_bytes, receipt_bytes = _sealed_snapshot(root, directory)
    return _validate_sealed_components(
        records,
        manifest_bytes,
        receipt_bytes,
        intent=intent,
        root=root,
    )


@contextmanager
def retained_sealed_result_snapshot(
    directory: Path, *, intent: Mapping[str, Any], root: Path
) -> Iterator[
    tuple[
        dict[str, Any],
        list[dict[str, object]],
        dict[str, bytes],
        dict[str, bytes],
    ]
]:
    """Yield one immutable-bytes view while retaining the exact result dirfd.

    The same directory descriptor and the same byte inventory cover manifest
    validation, caller-side semantic validation, and caller-side reduction.
    A final inventory is required to be byte- and identity-identical, so a
    mutate-use-restore attack (including restored mtime) is rejected by the
    retained inode/ctime tokens before the descriptor is released.
    """

    validate_publication_intent(intent, root=root)
    directory = Path(os.path.abspath(os.fspath(directory)))
    allowed = {
        Path(str(intent["staging_absolute"])),
        Path(str(intent["destination_absolute"])),
    }
    if directory not in allowed:
        raise gov.G0GovernanceError(
            "retained sealed result is not an allowed result directory"
        )
    top, parts, directory_identity = _open_result_directory(root, directory)
    try:
        initial = _inventory_open_result(top, durable=True)
        repeated = _inventory_open_result(top, durable=True)
        if initial != repeated:
            raise gov.G0GovernanceError(
                "G0 sealed result changed before retained snapshot use"
            )
        records, _identities, seals, payload_bytes = repeated
        if set(seals) != {MANIFEST_NAME, RECEIPT_NAME}:
            raise gov.G0GovernanceError(
                "G0 retained sealed result lacks exact seal files"
            )
        receipt, validated_records = _validate_sealed_components(
            records,
            seals[MANIFEST_NAME],
            seals[RECEIPT_NAME],
            intent=intent,
            root=root,
        )
        yield receipt, validated_records, dict(payload_bytes), dict(seals)
        final = _inventory_open_result(top, durable=True)
        if final != repeated:
            raise gov.G0GovernanceError(
                "G0 sealed result changed during retained snapshot use"
            )
        assert_retained_workspace_directory(
            root, directory, top, label="retained sealed G0 result"
        )
    finally:
        os.close(top)
    _assert_directory_reachable(
        root, parts, directory_identity, label="retained sealed G0 result"
    )


def rename_directory_noreplace(
    source: Path, destination: Path, *, root: Path
) -> None:
    """Atomically rename a directory while refusing an existing target."""

    _root, source_absolute, source_parts = _workspace_parts(
        root, source, label="G0 staging directory"
    )
    _root, destination_absolute, destination_parts = _workspace_parts(
        root, destination, label="G0 destination directory"
    )
    if source_parts[:-1] != destination_parts[:-1]:
        raise gov.G0GovernanceError(
            "G0 no-replace rename requires one canonical parent"
        )
    parent, _ = _open_directory_chain(
        root,
        source_parts[:-1],
        create=False,
        label="G0 publication parent",
    )
    parent_identity = os.fstat(parent)
    source_name = source_parts[-1]
    destination_name = destination_parts[-1]
    source_fd: int | None = None
    try:
        try:
            source_before = os.stat(
                source_name, dir_fd=parent, follow_symlinks=False
            )
        except FileNotFoundError as error:
            raise gov.G0GovernanceError(
                f"G0 staging directory is missing: {source_absolute}"
            ) from error
        if stat.S_ISLNK(source_before.st_mode) or not stat.S_ISDIR(
            source_before.st_mode
        ):
            raise gov.G0GovernanceError("G0 staging is not a direct directory")
        source_fd = os.open(source_name, _directory_flags(), dir_fd=parent)
        source_opened = os.fstat(source_fd)
        if _stat_token(source_opened) != _stat_token(source_before):
            raise gov.G0GovernanceError("G0 staging identity changed")
        try:
            os.stat(destination_name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise gov.G0GovernanceError(
                f"refusing to clobber existing destination: {destination_absolute}"
            )

        libc = ctypes.CDLL(None, use_errno=True)
        function = getattr(libc, "renameat2", None)
        if function is None:
            raise gov.G0GovernanceError(
                "renameat2 unavailable; strict publication refused"
            )
        function.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        function.restype = ctypes.c_int
        source_immediate = os.stat(
            source_name, dir_fd=parent, follow_symlinks=False
        )
        source_fd_immediate = os.fstat(source_fd)
        if (
            _stat_token(source_immediate) != _stat_token(source_opened)
            or _stat_token(source_fd_immediate) != _stat_token(source_opened)
        ):
            raise gov.G0GovernanceError(
                "G0 staging changed immediately before atomic rename"
            )
        result = function(
            parent,
            os.fsencode(source_name),
            parent,
            os.fsencode(destination_name),
            1,
        )
        if result != 0:
            code = ctypes.get_errno()
            if code in (errno.EEXIST, errno.ENOTEMPTY):
                raise gov.G0GovernanceError(
                    f"refusing to clobber existing destination: {destination_absolute}"
                )
            raise gov.G0GovernanceError(
                f"atomic no-replace publication failed: errno={code}"
            )
        try:
            os.stat(source_name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise gov.G0GovernanceError("G0 staging remains after atomic rename")
        destination_after = os.stat(
            destination_name, dir_fd=parent, follow_symlinks=False
        )
        retained_after = os.fstat(source_fd)
        if (
            stat.S_ISLNK(destination_after.st_mode)
            or not stat.S_ISDIR(destination_after.st_mode)
            or destination_after.st_dev != source_before.st_dev
            or destination_after.st_ino != source_before.st_ino
            or retained_after.st_dev != destination_after.st_dev
            or retained_after.st_ino != destination_after.st_ino
        ):
            raise gov.G0GovernanceError(
                "G0 destination identity changed after atomic rename"
            )
        os.fsync(parent)
    finally:
        if source_fd is not None:
            os.close(source_fd)
        os.close(parent)
    _assert_parent_reachable(
        root,
        source_parts[:-1],
        parent_identity,
        label="G0 publication parent",
    )


def _rename_retained_directory_noreplace_at(
    parent: int,
    source_name: str,
    destination_name: str,
    source_fd: int,
) -> None:
    """Rename the exact retained directory within one already retained parent."""

    source_identity = os.fstat(source_fd)
    try:
        source_path_identity = os.stat(
            source_name, dir_fd=parent, follow_symlinks=False
        )
    except FileNotFoundError as error:
        raise gov.G0GovernanceError("retained G0 staging is missing") from error
    if (
        _stat_token(source_path_identity) != _stat_token(source_identity)
        or not stat.S_ISDIR(source_identity.st_mode)
        or stat.S_ISLNK(source_path_identity.st_mode)
    ):
        raise gov.G0GovernanceError("retained G0 staging identity changed")
    try:
        os.stat(destination_name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise gov.G0GovernanceError(
            "refusing to clobber retained G0 publication destination"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, "renameat2", None)
    if function is None:
        raise gov.G0GovernanceError(
            "renameat2 unavailable; strict retained publication refused"
        )
    function.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    function.restype = ctypes.c_int
    result = function(
        parent,
        os.fsencode(source_name),
        parent,
        os.fsencode(destination_name),
        1,
    )
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise gov.G0GovernanceError(
                "refusing to clobber retained G0 publication destination"
            )
        raise gov.G0GovernanceError(
            f"retained atomic no-replace publication failed: errno={code}"
        )
    try:
        os.stat(source_name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        raise gov.G0GovernanceError(
            "retained G0 staging remains after atomic rename"
        )
    destination_identity = os.stat(
        destination_name, dir_fd=parent, follow_symlinks=False
    )
    retained_after = os.fstat(source_fd)
    if (
        destination_identity.st_dev != source_identity.st_dev
        or destination_identity.st_ino != source_identity.st_ino
        or retained_after.st_dev != source_identity.st_dev
        or retained_after.st_ino != source_identity.st_ino
        or not stat.S_ISDIR(destination_identity.st_mode)
        or stat.S_ISLNK(destination_identity.st_mode)
    ):
        raise gov.G0GovernanceError(
            "retained G0 destination identity changed after atomic rename"
        )
    os.fsync(parent)


def _build_closeout_from_retained_snapshot(
    intent: Mapping[str, Any],
    receipt: Mapping[str, Any],
    seal_bytes: Mapping[str, bytes],
    *,
    root: Path,
) -> dict[str, Any]:
    if set(seal_bytes) != {MANIFEST_NAME, RECEIPT_NAME}:
        raise gov.G0GovernanceError("retained publication seal set differs")
    destination = Path(str(intent["destination_absolute"]))

    def record(name: str) -> dict[str, object]:
        content = seal_bytes[name]
        return {
            "path": gov.display_path(root, destination / name),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }

    payload: dict[str, Any] = {
        "schema_version": gov.PUBLICATION_CLOSEOUT_SCHEMA,
        "status": CLOSEOUT_STATUS,
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "result_receipt_hash": receipt["result_receipt_hash"],
        "destination_absolute": intent["destination_absolute"],
        "receipt": record(RECEIPT_NAME),
        "output_manifest": record(MANIFEST_NAME),
        "atomic_operation": "renameat2(RENAME_NOREPLACE)",
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    payload["publication_closeout_hash"] = gov.canonical_json_hash(payload)
    return payload


def build_closeout(
    intent: Mapping[str, Any], *, root: Path
) -> dict[str, Any]:
    destination = Path(str(intent["destination_absolute"]))
    receipt, _records = validate_sealed_result(destination, intent=intent, root=root)
    receipt_path = destination / RECEIPT_NAME
    manifest_path = destination / MANIFEST_NAME
    payload: dict[str, Any] = {
        "schema_version": gov.PUBLICATION_CLOSEOUT_SCHEMA,
        "status": CLOSEOUT_STATUS,
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "result_receipt_hash": receipt["result_receipt_hash"],
        "destination_absolute": intent["destination_absolute"],
        "receipt": _direct_file_record(
            root, receipt_path, label="published result receipt"
        ),
        "output_manifest": _direct_file_record(
            root, manifest_path, label="published output manifest"
        ),
        "atomic_operation": "renameat2(RENAME_NOREPLACE)",
        "outcome_boundary": gov.OUTCOME_BOUNDARY,
    }
    payload["publication_closeout_hash"] = gov.canonical_json_hash(payload)
    return payload


def validate_closeout(
    payload: Mapping[str, Any], *, intent: Mapping[str, Any], root: Path
) -> str:
    if (
        payload.get("schema_version") != gov.PUBLICATION_CLOSEOUT_SCHEMA
        or payload.get("status") != CLOSEOUT_STATUS
    ):
        raise gov.G0GovernanceError("unexpected publication closeout schema/status")
    digest = gov.validate_self_hash(
        payload, "publication_closeout_hash", label="publication closeout"
    )
    expected_keys = {
        "schema_version",
        "status",
        "job_id",
        "job_hash",
        "plan_hash",
        "evaluation_lock_hash",
        "backend_execution_lock_hash",
        "g0_execution_authority_hash",
        "publication_intent_hash",
        "result_receipt_hash",
        "destination_absolute",
        "receipt",
        "output_manifest",
        "atomic_operation",
        "outcome_boundary",
        "publication_closeout_hash",
    }
    if set(payload) != expected_keys:
        raise gov.G0GovernanceError("publication closeout key set mismatch")
    if payload.get("atomic_operation") != "renameat2(RENAME_NOREPLACE)":
        raise gov.G0GovernanceError("publication closeout atomic operation mismatch")
    if payload.get("outcome_boundary") != gov.OUTCOME_BOUNDARY:
        raise gov.G0GovernanceError("publication closeout outcome boundary mismatch")
    expected = {
        "job_id": intent["job_id"],
        "job_hash": intent["job_hash"],
        "plan_hash": intent["plan_hash"],
        "evaluation_lock_hash": intent["evaluation_lock_hash"],
        "backend_execution_lock_hash": intent["backend_execution_lock_hash"],
        "g0_execution_authority_hash": intent["g0_execution_authority_hash"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "destination_absolute": intent["destination_absolute"],
    }
    gov.exact_json_identity(payload, expected, label="publication closeout")
    receipt, _records = validate_sealed_result(
        Path(str(intent["destination_absolute"])), intent=intent, root=root
    )
    if payload.get("result_receipt_hash") != receipt.get("result_receipt_hash"):
        raise gov.G0GovernanceError("publication closeout receipt hash mismatch")
    destination = Path(str(intent["destination_absolute"]))
    for key, name in (("receipt", RECEIPT_NAME), ("output_manifest", MANIFEST_NAME)):
        record = payload.get(key)
        if not isinstance(record, Mapping):
            raise gov.G0GovernanceError(f"publication closeout lacks {key}")
        expected_record = _direct_file_record(
            root, destination / name, label=f"closeout {key}"
        )
        if dict(record) != expected_record:
            raise gov.G0GovernanceError(
                f"publication closeout {key} exact destination record mismatch"
            )
    return digest


def publish_staging(
    intent: Mapping[str, Any],
    *,
    root: Path,
    closeout_path: Path,
    staging_fd: int | None = None,
) -> dict[str, Any]:
    validate_publication_intent(intent, root=root)
    staging = Path(str(intent["staging_absolute"]))
    destination = Path(str(intent["destination_absolute"]))
    expected_closeout = Path(str(intent["closeout_path_absolute"]))
    if Path(os.path.abspath(os.fspath(closeout_path))) != expected_closeout:
        raise gov.G0GovernanceError("closeout path differs from intent")
    _root, _staging_absolute, staging_parts = _workspace_parts(
        root, staging, label="publication staging"
    )
    _root, _destination_absolute, destination_parts = _workspace_parts(
        root, destination, label="publication destination"
    )
    _root, _closeout_absolute, closeout_parts = _workspace_parts(
        root, closeout_path, label="publication closeout"
    )
    if not (
        staging_parts[:-1]
        == destination_parts[:-1]
        == closeout_parts[:-1]
    ):
        raise gov.G0GovernanceError(
            "publication staging/destination/closeout require one parent"
        )
    parent, _ = _open_directory_chain(
        root,
        staging_parts[:-1],
        create=False,
        label="retained G0 publication parent",
    )
    parent_identity = os.fstat(parent)
    owned_staging_fd = staging_fd is None
    retained = staging_fd
    try:
        for name, label in (
            (destination_parts[-1], "publication destination"),
            (closeout_parts[-1], "publication closeout"),
        ):
            try:
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                continue
            raise gov.G0GovernanceError(f"{label} already exists")
        try:
            source_path_identity = os.stat(
                staging_parts[-1], dir_fd=parent, follow_symlinks=False
            )
        except FileNotFoundError as error:
            raise gov.G0GovernanceError("publication staging is missing") from error
        if retained is None:
            retained = os.open(
                staging_parts[-1], _directory_flags(), dir_fd=parent
            )
        retained_identity = os.fstat(retained)
        if (
            source_path_identity.st_dev != retained_identity.st_dev
            or source_path_identity.st_ino != retained_identity.st_ino
            or stat.S_ISLNK(source_path_identity.st_mode)
            or not stat.S_ISDIR(retained_identity.st_mode)
        ):
            raise gov.G0GovernanceError(
                "publication staging differs from retained directory"
            )
        first = _inventory_open_result(retained, durable=True)
        baseline = _inventory_open_result(retained, durable=True)
        if first != baseline:
            raise gov.G0GovernanceError(
                "retained G0 staging changed before publication"
            )
        records, _identities, seals, _payload_bytes = baseline
        if set(seals) != {MANIFEST_NAME, RECEIPT_NAME}:
            raise gov.G0GovernanceError(
                "retained G0 staging lacks exact seal files"
            )
        receipt, _validated_records = _validate_sealed_components(
            records,
            seals[MANIFEST_NAME],
            seals[RECEIPT_NAME],
            intent=intent,
            root=root,
        )
        if _inventory_open_result(retained, durable=True) != baseline:
            raise gov.G0GovernanceError(
                "retained G0 staging changed immediately before publication"
            )
        _rename_retained_directory_noreplace_at(
            parent,
            staging_parts[-1],
            destination_parts[-1],
            retained,
        )
        assert_retained_workspace_directory(
            root,
            destination,
            retained,
            label="retained published G0 destination",
        )
        if not _same_result_inventory_after_directory_rename(
            baseline, _inventory_open_result(retained, durable=True)
        ):
            raise gov.G0GovernanceError(
                "retained G0 result changed across atomic publication"
            )
        closeout = _build_closeout_from_retained_snapshot(
            intent, receipt, seals, root=root
        )
        if not _same_result_inventory_after_directory_rename(
            baseline, _inventory_open_result(retained, durable=True)
        ):
            raise gov.G0GovernanceError(
                "retained G0 result changed before closeout commit"
            )
        closeout_bytes = json.dumps(
            closeout,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8") + b"\n"
        _write_bytes_exclusive_retained_directory(
            parent,
            closeout_parts[-1],
            closeout_bytes,
            label="publication closeout",
        )
        if not _same_result_inventory_after_directory_rename(
            baseline, _inventory_open_result(retained, durable=True)
        ):
            raise gov.G0GovernanceError(
                "retained G0 result changed during closeout commit"
            )
        observed_closeout, _observed_identity = _read_leaf_bytes_at(
            parent,
            closeout_parts[-1],
            absolute=closeout_path,
            label="publication closeout",
        )
        if observed_closeout != closeout_bytes:
            raise gov.G0GovernanceError("publication closeout bytes differ")
        assert_retained_workspace_directory(
            root,
            destination,
            retained,
            label="closeout-bound G0 destination",
        )
        return closeout
    finally:
        if owned_staging_fd and retained is not None:
            os.close(retained)
        os.close(parent)
        _assert_parent_reachable(
            root,
            staging_parts[:-1],
            parent_identity,
            label="retained G0 publication parent",
        )


def reconcile_publication(
    intent_path: Path, *, root: Path, apply: bool = False
) -> dict[str, Any]:
    intent = _read_direct_json(root, intent_path, label="publication intent")
    validate_publication_intent(intent, root=root)
    if Path(os.path.abspath(os.fspath(intent_path))) != Path(
        str(intent["intent_path_absolute"])
    ):
        raise gov.G0GovernanceError("reconcile intent path differs from payload")
    staging = Path(str(intent["staging_absolute"]))
    destination = Path(str(intent["destination_absolute"]))
    closeout_path = Path(str(intent["closeout_path_absolute"]))
    closeout_state = _leaf_state(root, closeout_path, label="publication closeout")
    destination_state = _leaf_state(
        root, destination, label="publication destination"
    )
    staging_state = _leaf_state(root, staging, label="publication staging")
    if closeout_state == "FILE":
        if destination_state != "DIRECTORY" or staging_state != "ABSENT":
            raise gov.G0GovernanceError(
                "closed publication has contradictory staging/destination evidence"
            )
        closeout = _read_direct_json(
            root, closeout_path, label="publication closeout"
        )
        validate_closeout(closeout, intent=intent, root=root)
        state = "ALREADY_CLOSED"
    elif closeout_state != "ABSENT":
        raise gov.G0GovernanceError("publication closeout is not a direct file")
    elif destination_state == "DIRECTORY" and staging_state == "DIRECTORY":
        raise gov.G0GovernanceError("both staging and destination exist; preserve for audit")
    elif destination_state == "DIRECTORY":
        validate_sealed_result(destination, intent=intent, root=root)
        state = "DESTINATION_COMPLETE_CLOSEOUT_MISSING"
        if apply:
            closeout = build_closeout(intent, root=root)
            write_json_exclusive_rooted(root, closeout_path, closeout)
            state = "DESTINATION_RECONCILED_CLOSEOUT_WRITTEN"
    elif destination_state != "ABSENT":
        raise gov.G0GovernanceError("publication destination is not a directory")
    elif staging_state == "DIRECTORY":
        try:
            validate_sealed_result(staging, intent=intent, root=root)
        except gov.G0GovernanceError:
            state = "STAGING_INCOMPLETE_PRESERVED_MANUAL_REVIEW_REQUIRED"
        else:
            state = "STAGING_COMPLETE_READY_FOR_ATOMIC_PUBLICATION"
            if apply:
                publish_staging(intent, root=root, closeout_path=closeout_path)
                state = "STAGING_RECONCILED_AND_PUBLISHED"
    elif staging_state != "ABSENT":
        raise gov.G0GovernanceError("publication staging is not a directory")
    else:
        state = "INTENT_ONLY_SAFE_TO_RESUME_EXACT_JOB"
    final_destination_state = _leaf_state(
        root, destination, label="publication destination"
    )
    final_staging_state = _leaf_state(root, staging, label="publication staging")
    final_closeout_state = _leaf_state(
        root, closeout_path, label="publication closeout"
    )
    expected_final_states = {
        "ALREADY_CLOSED": ("DIRECTORY", "ABSENT", "FILE"),
        "DESTINATION_COMPLETE_CLOSEOUT_MISSING": (
            "DIRECTORY",
            "ABSENT",
            "ABSENT",
        ),
        "DESTINATION_RECONCILED_CLOSEOUT_WRITTEN": (
            "DIRECTORY",
            "ABSENT",
            "FILE",
        ),
        "STAGING_INCOMPLETE_PRESERVED_MANUAL_REVIEW_REQUIRED": (
            "ABSENT",
            "DIRECTORY",
            "ABSENT",
        ),
        "STAGING_COMPLETE_READY_FOR_ATOMIC_PUBLICATION": (
            "ABSENT",
            "DIRECTORY",
            "ABSENT",
        ),
        "STAGING_RECONCILED_AND_PUBLISHED": (
            "DIRECTORY",
            "ABSENT",
            "FILE",
        ),
        "INTENT_ONLY_SAFE_TO_RESUME_EXACT_JOB": (
            "ABSENT",
            "ABSENT",
            "ABSENT",
        ),
    }
    observed_final = (
        final_destination_state,
        final_staging_state,
        final_closeout_state,
    )
    if expected_final_states.get(state) != observed_final:
        raise gov.G0GovernanceError(
            f"publication state changed during reconcile: {state} {observed_final}"
        )
    return {
        "mode": "APPLY_RECONCILE" if apply else "READ_ONLY_RECONCILE",
        "state": state,
        "job_id": intent["job_id"],
        "publication_intent_hash": intent["publication_intent_hash"],
        "destination_exists": final_destination_state != "ABSENT",
        "staging_exists": final_staging_state != "ABSENT",
        "closeout_exists": final_closeout_state != "ABSENT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=gov.ROOT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = reconcile_publication(args.intent, root=args.root, apply=args.apply)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
