#!/usr/bin/env python3
"""Deterministically fan one bound NTNU ROS1 bag into closed record windows.

This module is deliberately a small materialization primitive.  It does not
publish final paths and it does not start ROS or VINS.  The caller supplies an
already-open source through ``/proc/self/fd/N`` and exclusive stage names.  A
single ROS1 reader walk covers the outer window bounds; records on a shared
endpoint are copied into both adjacent windows.
"""

from __future__ import annotations

import bisect
import ctypes
import errno
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import struct
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

import genpy
import rosbag


DEFAULT_TOPICS: Tuple[str, str] = (
    "/alphasense_driver_ros/cam0",
    "/alphasense_driver_ros/imu",
)
OUTPUT_COMPRESSION = rosbag.Compression.NONE
OUTPUT_CHUNK_THRESHOLD_BYTES = 768 * 1024
SCHEMA_VERSION = "aqua-fe-p07-ntnu-window-fanout-v1"
SELECTION_SEMANTICS = "ROS1_RECORD_TIME_CLOSED_INTERVAL_LOWER_BOUND_UPPER_BOUND"
_PROC_FD = re.compile(r"/proc/self/fd/([0-9]+)\Z")
_NSEC_PER_SEC = 1_000_000_000
_MAX_ROS1_TIME_NS = ((1 << 32) - 1) * _NSEC_PER_SEC + (_NSEC_PER_SEC - 1)
_CAMERA_DATATYPE = "sensor_msgs/Image"
_IMU_DATATYPE = "sensor_msgs/Imu"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_AT_FDCWD = -100
_RENAME_NOREPLACE = 1
_LIBC = ctypes.CDLL(None, use_errno=True)


class NTNUWindowFanoutError(RuntimeError):
    """The source topology or requested fanout is unsafe or ambiguous."""


class StageCleanupIncomplete(NTNUWindowFanoutError):
    """An automatic cleanup stopped after preserving an inode fail-closed."""

    def __init__(
        self,
        *,
        retained_path: Path,
        reason: str,
        retained_identity: Optional[Mapping[str, int]] = None,
    ) -> None:
        self.retained_path = Path(os.path.abspath(os.fspath(retained_path)))
        self.reason = reason
        self.retained_identity = (
            dict(retained_identity) if retained_identity is not None else None
        )
        super().__init__(
            "cleanup-incomplete: "
            f"reason={reason}; retained_path={os.fspath(self.retained_path)}"
        )


@dataclass(frozen=True)
class RecordWindow:
    """One relative, inclusive ROS1 record-time window."""

    window_id: str
    start_offset_ns: int
    end_offset_ns: int

    def __post_init__(self) -> None:
        if not isinstance(self.window_id, str) or not self.window_id:
            raise ValueError("window_id must be a non-empty string")
        if self.window_id != self.window_id.strip() or "\x00" in self.window_id:
            raise ValueError("window_id must be canonical non-NUL text")
        if type(self.start_offset_ns) is not int or type(self.end_offset_ns) is not int:
            raise TypeError("record-window offsets must be exact integers")
        if self.start_offset_ns < 0:
            raise ValueError("record-window start offset must be non-negative")
        if self.end_offset_ns <= self.start_offset_ns:
            raise ValueError("record-window end offset must be greater than start")


@dataclass
class _WindowState:
    window: RecordWindow
    staged_path: Path
    writer: Any
    audit_fd: int
    topic_counts: dict
    first_record_stamp_ns: Optional[int] = None
    last_record_stamp_ns: Optional[int] = None
    header_first_ns: Optional[dict] = None
    header_last_ns: Optional[dict] = None
    raw_record_transcripts: Optional[dict] = None

    def __post_init__(self) -> None:
        self.header_first_ns = {}
        self.header_last_ns = {}
        self.raw_record_transcripts = {}


def _exact_time_ns(value: Any, *, label: str) -> int:
    if not hasattr(value, "secs") or not hasattr(value, "nsecs"):
        raise NTNUWindowFanoutError(f"{label} is not an exact ROS time")
    secs = value.secs
    nsecs = value.nsecs
    if type(secs) is not int or type(nsecs) is not int:
        raise NTNUWindowFanoutError(f"{label} fields must be exact integers")
    if not 0 <= secs < (1 << 32) or not 0 <= nsecs < _NSEC_PER_SEC:
        raise NTNUWindowFanoutError(f"{label} is outside ROS1 time bounds")
    return secs * _NSEC_PER_SEC + nsecs


def _time_from_ns(value: int) -> genpy.Time:
    if type(value) is not int or not 0 <= value <= _MAX_ROS1_TIME_NS:
        raise NTNUWindowFanoutError("absolute record bound is outside ROS1 time")
    secs, nsecs = divmod(value, _NSEC_PER_SEC)
    return genpy.Time(secs, nsecs)


def _sha256_descriptor(descriptor: int) -> str:
    digest = hashlib.sha256()
    offset = 0
    while True:
        chunk = os.pread(descriptor, 1024 * 1024, offset)
        if not chunk:
            break
        digest.update(chunk)
        offset += len(chunk)
    return digest.hexdigest()


def _file_identity(info: os.stat_result) -> dict:
    return {
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "size_bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def _same_inode(info: os.stat_result, expected: os.stat_result) -> bool:
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_dev == expected.st_dev
        and info.st_ino == expected.st_ino
    )


def _descriptor_stat(descriptor: int) -> os.stat_result:
    """Stat an open descriptor, with a descriptor-bound Linux fallback."""

    try:
        return os.fstat(descriptor)
    except OSError as primary_error:
        try:
            return os.stat(f"/proc/self/fd/{descriptor}", follow_symlinks=True)
        except OSError:
            raise primary_error


def _duplicate_cloexec(descriptor: int) -> int:
    if hasattr(fcntl, "F_DUPFD_CLOEXEC"):
        return fcntl.fcntl(descriptor, fcntl.F_DUPFD_CLOEXEC, 3)
    duplicate = os.dup(descriptor)
    os.set_inheritable(duplicate, False)
    return duplicate


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename without ever replacing an existing destination."""

    renameat2 = getattr(_LIBC, "renameat2", None)
    if renameat2 is None:
        raise NTNUWindowFanoutError(
            "renameat2(RENAME_NOREPLACE) is unavailable; cleanup is fail-closed"
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
        _AT_FDCWD,
        os.fsencode(source),
        _AT_FDCWD,
        os.fsencode(destination),
        _RENAME_NOREPLACE,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(
            error_number,
            os.strerror(error_number),
            os.fspath(destination),
        )


def _add_cleanup_note(error: BaseException, message: str) -> None:
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(message)
        return
    notes = list(getattr(error, "__notes__", []))
    notes.append(message)
    try:
        error.__notes__ = notes
    except (AttributeError, TypeError):
        pass


def _canonical_json_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _header_component_bytes(value: Any, *, label: str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise NTNUWindowFanoutError(f"unsupported {label} in ROS connection header")


def _connection_header_sha256(header: Mapping[Any, Any]) -> str:
    """Hash an exact ROS connection header without lossy text conversion."""

    encoded = []
    for key, value in header.items():
        key_bytes = _header_component_bytes(key, label="key")
        value_bytes = _header_component_bytes(value, label="value")
        encoded.append((key_bytes, value_bytes))
    encoded.sort(key=lambda item: item[0])
    digest = hashlib.sha256()
    digest.update(struct.pack("<Q", len(encoded)))
    for key_bytes, value_bytes in encoded:
        digest.update(struct.pack("<Q", len(key_bytes)))
        digest.update(key_bytes)
        digest.update(struct.pack("<Q", len(value_bytes)))
        digest.update(value_bytes)
    return digest.hexdigest()


def _update_raw_record_transcript(
    digest: Any,
    *,
    topic: str,
    record_ns: int,
    raw_message: Any,
    connection_header: Mapping[Any, Any],
) -> None:
    if not isinstance(raw_message, tuple) or len(raw_message) not in (4, 5):
        raise NTNUWindowFanoutError(f"unexpected raw ROS message tuple on {topic}")
    datatype = _header_component_bytes(raw_message[0], label="raw datatype")
    serialized = raw_message[1]
    md5sum = _header_component_bytes(raw_message[2], label="raw md5sum")
    if not isinstance(serialized, (bytes, bytearray)):
        raise NTNUWindowFanoutError(f"raw ROS payload is not bytes on {topic}")
    components = (
        topic.encode("utf-8"),
        struct.pack("<Q", record_ns),
        datatype,
        bytes(serialized),
        md5sum,
        _connection_header_sha256(connection_header).encode("ascii"),
    )
    digest.update(struct.pack("<Q", len(components)))
    for component in components:
        digest.update(struct.pack("<Q", len(component)))
        digest.update(component)


def _connection_record(connection: Any) -> dict:
    record = {
        "topic": str(connection.topic),
        "datatype": str(connection.datatype),
        "md5sum": str(connection.md5sum),
        "message_definition_sha256": hashlib.sha256(
            str(connection.msg_def).encode("utf-8")
        ).hexdigest(),
        "connection_header_sha256": _connection_header_sha256(connection.header),
    }
    record["connection_identity_sha256"] = _canonical_json_hash(record)
    return record


def _writer_identity() -> dict:
    writer = {
        "rosbag_format_version": 200,
        "compression": str(OUTPUT_COMPRESSION),
        "chunk_threshold_bytes": OUTPUT_CHUNK_THRESHOLD_BYTES,
        "raw_copy": True,
        "connection_header_preserved": True,
        "selection_semantics": SELECTION_SEMANTICS,
    }
    writer["writer_identity_sha256"] = _canonical_json_hash(writer)
    return writer


def _validate_topics(topics: Sequence[str]) -> Tuple[str, str]:
    materialized = tuple(topics)
    if len(materialized) != 2 or len(set(materialized)) != 2:
        raise ValueError("exactly two unique NTNU source topics are required")
    for topic in materialized:
        if not isinstance(topic, str) or not topic or not topic.startswith("/"):
            raise ValueError("NTNU topics must be non-empty absolute ROS names")
        if topic != topic.strip() or "\x00" in topic:
            raise ValueError("NTNU topics must be canonical non-NUL text")
    return materialized[0], materialized[1]


def _validate_windows(windows: Sequence[RecordWindow]) -> Tuple[RecordWindow, ...]:
    result = tuple(windows)
    if not result:
        raise ValueError("at least one record window is required")
    if any(not isinstance(window, RecordWindow) for window in result):
        raise TypeError("windows must contain only RecordWindow values")
    ids = [window.window_id for window in result]
    if len(ids) != len(set(ids)):
        raise ValueError("record-window IDs must be unique")
    for previous, current in zip(result, result[1:]):
        if current.start_offset_ns <= previous.start_offset_ns:
            raise ValueError("record windows must have strictly increasing starts")
        if current.end_offset_ns <= previous.end_offset_ns:
            raise ValueError("record windows must have strictly increasing ends")
        if current.start_offset_ns < previous.end_offset_ns:
            raise ValueError("record windows may meet at endpoints but not overlap inside")
    return result


def _assert_no_preserved_stage(path: Path) -> None:
    preserved_prefix = f".{path.name}.aqua-fe-preserved-"
    try:
        with os.scandir(path.parent) as entries:
            preserved = sorted(
                os.path.abspath(entry.path)
                for entry in entries
                if entry.name.startswith(preserved_prefix)
            )
    except OSError as error:
        raise NTNUWindowFanoutError(
            f"cannot inspect preserved stages for: {path}"
        ) from error
    if preserved:
        raise StageCleanupIncomplete(
            retained_path=Path(preserved[0]),
            reason="PRESERVED_STAGE_REQUIRES_SEPARATE_GOVERNANCE",
        )


def _stage_paths(
    windows: Sequence[RecordWindow], staged_output_paths: Mapping[str, os.PathLike]
) -> dict:
    expected = {window.window_id for window in windows}
    if set(staged_output_paths) != expected:
        raise ValueError("staged_output_paths must exactly cover the record-window IDs")
    result = {}
    lexical = set()
    for window in windows:
        raw = os.fspath(staged_output_paths[window.window_id])
        if not isinstance(raw, str) or not raw or "\x00" in raw:
            raise ValueError("stage paths must be non-empty filesystem text")
        absolute = os.path.abspath(raw)
        path = Path(absolute)
        if absolute in lexical:
            raise ValueError("stage paths must be distinct")
        lexical.add(absolute)
        try:
            parent_info = path.parent.stat()
        except OSError as error:
            raise NTNUWindowFanoutError(f"stage parent is unavailable: {path.parent}") from error
        if not stat.S_ISDIR(parent_info.st_mode):
            raise NTNUWindowFanoutError(f"stage parent is not a directory: {path.parent}")
        _assert_no_preserved_stage(path)
        try:
            os.lstat(path)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(path)
        result[window.window_id] = path
    return result


def _source_descriptor(source_proc_path: os.PathLike) -> Tuple[str, int, os.stat_result]:
    raw = os.fspath(source_proc_path)
    if not isinstance(raw, str):
        raise ValueError("source_proc_path must be filesystem text")
    match = _PROC_FD.fullmatch(raw)
    if match is None:
        raise ValueError("source_proc_path must be an exact /proc/self/fd/N path")
    borrowed_descriptor = int(match.group(1))
    try:
        descriptor = _duplicate_cloexec(borrowed_descriptor)
    except OSError as error:
        raise NTNUWindowFanoutError("source descriptor is unavailable") from error
    try:
        info = os.fstat(descriptor)
        access_mode = fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE
        if not stat.S_ISREG(info.st_mode):
            raise NTNUWindowFanoutError(
                "source descriptor must identify a regular file"
            )
        if access_mode == os.O_WRONLY:
            raise NTNUWindowFanoutError("source descriptor is not readable")
    except BaseException:
        os.close(descriptor)
        raise
    return f"/proc/self/fd/{descriptor}", descriptor, info


def _bag_begin_ns(source: Any) -> int:
    try:
        entry = next(source._get_entries())
    except StopIteration as error:
        raise NTNUWindowFanoutError("source bag is empty") from error
    except Exception as error:
        raise NTNUWindowFanoutError("cannot obtain exact source-bag begin index") from error
    return _exact_time_ns(entry.time, label="source bag begin")


def _source_connections(source: Any, topics: Sequence[str]) -> dict:
    result = {}
    for topic in topics:
        connections = list(source._get_connections(topic))
        if len(connections) != 1:
            raise NTNUWindowFanoutError(
                f"source topic must have exactly one connection: {topic} ({len(connections)})"
            )
        connection = connections[0]
        if connection.topic != topic:
            raise NTNUWindowFanoutError(
                f"source topic uses a non-exact canonical alias: {connection.topic!r}"
            )
        result[topic] = connection
    return result


def _topic_roles(connections: Mapping[str, Any]) -> Tuple[str, str]:
    cameras = [
        topic
        for topic, connection in connections.items()
        if str(connection.datatype) == _CAMERA_DATATYPE
    ]
    imus = [
        topic
        for topic, connection in connections.items()
        if str(connection.datatype) == _IMU_DATATYPE
    ]
    if len(cameras) != 1 or len(imus) != 1 or cameras[0] == imus[0]:
        raise NTNUWindowFanoutError(
            "selected topics must contain exactly one sensor_msgs/Image camera "
            "and one sensor_msgs/Imu"
        )
    return cameras[0], imus[0]


def _raw_header_stamp_ns(raw_message: Any, *, topic: str) -> int:
    if not isinstance(raw_message, tuple) or len(raw_message) not in (4, 5):
        raise NTNUWindowFanoutError(f"unexpected raw ROS message tuple on {topic}")
    serialized = raw_message[1]
    pytype = raw_message[4] if len(raw_message) == 5 else raw_message[3]
    if pytype is None or not isinstance(serialized, (bytes, bytearray)):
        raise NTNUWindowFanoutError(f"raw ROS message is not deserializable on {topic}")
    try:
        message = pytype()
        message.deserialize(serialized)
    except Exception as error:
        raise NTNUWindowFanoutError(f"cannot inspect raw message header on {topic}") from error
    header = getattr(message, "header", None)
    stamp = getattr(header, "stamp", None)
    if stamp is None:
        raise NTNUWindowFanoutError(f"selected message lacks Header.stamp on {topic}")
    return _exact_time_ns(stamp, label=f"Header.stamp on {topic}")


def _open_stage_writer(path: Path) -> Tuple[Any, os.stat_result, int]:
    _assert_no_preserved_stage(path)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(os.fspath(path), flags, 0o600)
    identity = None
    audit_descriptor = -1
    stream = None
    try:
        identity = _descriptor_stat(descriptor)
        if not stat.S_ISREG(identity.st_mode):
            raise NTNUWindowFanoutError(f"stage is not a regular file: {path}")
        audit_descriptor = _duplicate_cloexec(descriptor)
        stream = os.fdopen(descriptor, "w+b", closefd=True)
        descriptor = -1
        bag = rosbag.Bag(
            stream,
            "w",
            compression=OUTPUT_COMPRESSION,
            chunk_threshold=OUTPUT_CHUNK_THRESHOLD_BYTES,
        )
    except BaseException as error:
        try:
            if stream is not None:
                stream.close()
            elif descriptor >= 0:
                os.close(descriptor)
        except BaseException as close_error:
            _add_cleanup_note(error, f"stage descriptor close failed: {close_error!r}")
        if identity is not None:
            try:
                _unlink_owned_stage(
                    path,
                    identity,
                    audit_descriptor if audit_descriptor >= 0 else None,
                )
            except StageCleanupIncomplete as cleanup_error:
                _add_cleanup_note(error, str(cleanup_error))
            except BaseException as cleanup_error:
                _add_cleanup_note(error, f"stage preservation failed: {cleanup_error!r}")
        else:
            cleanup_error = StageCleanupIncomplete(
                retained_path=path,
                reason="IDENTITY_UNAVAILABLE_NO_AUTOMATIC_RECLAIM",
            )
            _add_cleanup_note(error, str(cleanup_error))
        if audit_descriptor >= 0:
            try:
                os.close(audit_descriptor)
            except BaseException as close_error:
                _add_cleanup_note(
                    error, f"stage audit descriptor close failed: {close_error!r}"
                )
        raise
    return bag, identity, audit_descriptor


def _unlink_owned_stage(
    path: Path,
    identity: os.stat_result,
    owned_descriptor: Optional[int] = None,
) -> None:
    """Move an owned stage to a preserved name and never reclaim it here.

    Linux has no ordinary-file unlink-by-handle primitive.  Consequently a
    final name-based unlink after an inode check would reopen a replacement
    race.  This routine only performs an atomic no-replace rename, verifies the
    moved name against the retained create-time descriptor when available, and
    then raises a structured cleanup-incomplete result.  Reclamation belongs to
    a separate governed workflow.
    """

    try:
        observed = os.lstat(path)
    except FileNotFoundError:
        raise StageCleanupIncomplete(
            retained_path=path,
            reason="STAGE_PATH_MISSING_NO_AUTOMATIC_RECLAIM",
        )
    if not _same_inode(observed, identity):
        raise StageCleanupIncomplete(
            retained_path=path,
            reason="UNRECOGNIZED_STAGE_REPLACEMENT_RETAINED",
            retained_identity=_file_identity(observed),
        )

    if owned_descriptor is not None:
        try:
            descriptor_info = _descriptor_stat(owned_descriptor)
            if not _same_inode(descriptor_info, identity):
                raise StageCleanupIncomplete(
                    retained_path=path,
                    reason="OWNED_DESCRIPTOR_IDENTITY_DRIFT_STAGE_RETAINED",
                    retained_identity=_file_identity(observed),
                )
            os.fsync(owned_descriptor)
        except StageCleanupIncomplete:
            raise
        except OSError as error:
            raise StageCleanupIncomplete(
                retained_path=path,
                reason="OWNED_DESCRIPTOR_UNAVAILABLE_STAGE_RETAINED",
                retained_identity=_file_identity(observed),
            ) from error

    quarantine = None
    for _attempt in range(32):
        candidate = path.with_name(
            f".{path.name}.aqua-fe-preserved-{os.getpid()}-{secrets.token_hex(16)}"
        )
        try:
            _rename_noreplace(path, candidate)
        except FileNotFoundError as error:
            raise StageCleanupIncomplete(
                retained_path=path,
                reason="STAGE_DISAPPEARED_BEFORE_PRESERVATION",
            ) from error
        except OSError as error:
            if error.errno == errno.EEXIST:
                continue
            raise StageCleanupIncomplete(
                retained_path=path,
                reason="PRESERVATION_RENAME_FAILED_STAGE_RETAINED",
                retained_identity=_file_identity(observed),
            ) from error
        quarantine = candidate
        break
    if quarantine is None:
        raise StageCleanupIncomplete(
            retained_path=path,
            reason="PRESERVATION_NAME_COLLISIONS_STAGE_RETAINED",
            retained_identity=_file_identity(observed),
        )

    try:
        moved = os.lstat(quarantine)
    except OSError as error:
        raise StageCleanupIncomplete(
            retained_path=quarantine,
            reason="PRESERVED_PATH_UNAVAILABLE_NO_AUTOMATIC_RECLAIM",
        ) from error
    if not _same_inode(moved, identity):
        raise StageCleanupIncomplete(
            retained_path=quarantine,
            reason="UNRECOGNIZED_MOVED_INODE_PRESERVED_NO_AUTOMATIC_RECLAIM",
            retained_identity=_file_identity(moved),
        )

    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(os.fspath(quarantine), flags)
        confirmed = _descriptor_stat(descriptor)
        if not _same_inode(confirmed, identity):
            raise StageCleanupIncomplete(
                retained_path=quarantine,
                reason="PRESERVED_NAME_REPLACED_NO_AUTOMATIC_RECLAIM",
                retained_identity=_file_identity(confirmed),
            )
        os.fsync(descriptor)
    except StageCleanupIncomplete:
        raise
    except OSError as error:
        raise StageCleanupIncomplete(
            retained_path=quarantine,
            reason="PRESERVED_DESCRIPTOR_UNAVAILABLE_NO_AUTOMATIC_RECLAIM",
            retained_identity=_file_identity(moved),
        ) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    raise StageCleanupIncomplete(
        retained_path=quarantine,
        reason="OWNED_STAGE_PRESERVED_NO_AUTOMATIC_RECLAIM",
        retained_identity=_file_identity(moved),
    )


def _open_bound_stage_reader(
    path: Path, expected_identity: os.stat_result
) -> Tuple[int, os.stat_result]:
    flags = os.O_RDONLY | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(os.fspath(path), flags)
    try:
        info = os.fstat(descriptor)
        if not _same_inode(info, expected_identity):
            raise NTNUWindowFanoutError(
                f"completed stage identity differs from the exclusive create: {path}"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor, info


def _revalidate_stage_path(
    path: Path,
    expected_create_identity: os.stat_result,
    expected_final_identity: Mapping[str, int],
) -> None:
    try:
        observed = os.lstat(path)
    except FileNotFoundError as error:
        raise NTNUWindowFanoutError(f"completed stage path disappeared: {path}") from error
    if (
        not _same_inode(observed, expected_create_identity)
        or _file_identity(observed) != dict(expected_final_identity)
    ):
        raise NTNUWindowFanoutError(
            f"completed stage path no longer names the audited inode: {path}"
        )


def _audit_output(
    source_proc_path: str,
    topics: Sequence[str],
    expected: Mapping[str, dict],
    state: _WindowState,
) -> dict:
    observed_connections = []
    observed_counts = {topic: 0 for topic in topics}
    header_first_ns = {}
    header_last_ns = {}
    first_record_ns = None
    last_record_ns = None
    previous_global_record_ns = -1
    previous_topic_record_ns = {topic: -1 for topic in topics}
    previous_topic_header_ns = {topic: -1 for topic in topics}
    transcripts = {topic: hashlib.sha256() for topic in topics}

    with rosbag.Bag(source_proc_path, "r") as bag:
        for topic in topics:
            connections = list(bag._get_connections(topic))
            if len(connections) != 1 or connections[0].topic != topic:
                raise NTNUWindowFanoutError(
                    f"staged output lacks one exact connection for {topic}"
                )
            connection = connections[0]
            identity = _connection_record(connection)
            if any(
                identity[key] != expected[topic][key]
                for key in (
                    "topic",
                    "datatype",
                    "md5sum",
                    "message_definition_sha256",
                    "connection_header_sha256",
                    "connection_identity_sha256",
                )
            ):
                raise NTNUWindowFanoutError(
                    f"staged output connection identity differs on {topic}"
                )
            observed_connections.append(
                {
                    **identity,
                    "output_connection_id": int(connection.id),
                }
            )
        all_connections = list(bag._get_connections())
        if len(all_connections) != len(topics):
            raise NTNUWindowFanoutError("staged output contains a distractor connection")

        for item in bag.read_messages(raw=True, return_connection_header=True):
            topic = str(item.topic)
            if topic not in expected:
                raise NTNUWindowFanoutError(
                    f"staged output contains an unrequested topic: {topic}"
                )
            record_ns = _exact_time_ns(item.timestamp, label="output record stamp")
            if record_ns < previous_global_record_ns:
                raise NTNUWindowFanoutError(
                    "staged output record stamps are non-monotonic"
                )
            if record_ns <= previous_topic_record_ns[topic]:
                raise NTNUWindowFanoutError(
                    f"staged output record stamps are not strictly increasing on {topic}"
                )
            previous_global_record_ns = record_ns
            previous_topic_record_ns[topic] = record_ns

            raw_message = item.message
            if not isinstance(raw_message, tuple) or len(raw_message) not in (4, 5):
                raise NTNUWindowFanoutError(
                    f"unexpected raw staged ROS message tuple on {topic}"
                )
            expected_connection = expected[topic]
            if (
                raw_message[0] != expected_connection["datatype"]
                or raw_message[2] != expected_connection["md5sum"]
                or _connection_header_sha256(item.connection_header)
                != expected_connection["connection_header_sha256"]
            ):
                raise NTNUWindowFanoutError(
                    f"staged raw message/connection identity drift on {topic}"
                )
            header_ns = _raw_header_stamp_ns(raw_message, topic=topic)
            if header_ns <= previous_topic_header_ns[topic]:
                raise NTNUWindowFanoutError(
                    f"staged Header.stamp is not strictly increasing on {topic}"
                )
            previous_topic_header_ns[topic] = header_ns
            _update_raw_record_transcript(
                transcripts[topic],
                topic=topic,
                record_ns=record_ns,
                raw_message=raw_message,
                connection_header=item.connection_header,
            )
            observed_counts[topic] += 1
            if first_record_ns is None:
                first_record_ns = record_ns
            last_record_ns = record_ns
            header_first_ns.setdefault(topic, header_ns)
            header_last_ns[topic] = header_ns

    if observed_counts != state.topic_counts:
        raise NTNUWindowFanoutError(
            f"staged output topic counts differ for window {state.window.window_id}"
        )
    if (
        first_record_ns != state.first_record_stamp_ns
        or last_record_ns != state.last_record_stamp_ns
        or header_first_ns != state.header_first_ns
        or header_last_ns != state.header_last_ns
        or {
            topic: transcripts[topic].hexdigest() for topic in topics
        }
        != {
            topic: state.raw_record_transcripts[topic].hexdigest()
            for topic in topics
        }
    ):
        raise NTNUWindowFanoutError(
            f"staged output record evidence differs for window {state.window.window_id}"
        )
    return {
        "connections": observed_connections,
        "topic_counts": observed_counts,
        "first_record_stamp_ns": first_record_ns,
        "last_record_stamp_ns": last_record_ns,
        "header_first_ns": header_first_ns,
        "header_last_ns": header_last_ns,
        "raw_record_transcript_sha256": _canonical_json_hash(
            {topic: transcripts[topic].hexdigest() for topic in topics}
        ),
    }


def _require_exact_keys(value: Any, expected: set, *, label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise NTNUWindowFanoutError(f"{label} does not have the exact receipt schema")


def _require_sha256(value: Any, *, label: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise NTNUWindowFanoutError(f"{label} is not a canonical SHA-256")


def _validate_file_identity(value: Any, *, label: str) -> None:
    _require_exact_keys(
        value,
        {"device", "inode", "size_bytes", "mtime_ns", "ctime_ns"},
        label=label,
    )
    for key in value:
        if type(value[key]) is not int or value[key] < 0:
            raise NTNUWindowFanoutError(f"{label}.{key} must be a non-negative integer")


def _validate_receipt(
    receipt: Any,
    windows: Sequence[RecordWindow],
    topics: Sequence[str],
    camera_topic: str,
    imu_topic: str,
) -> None:
    _require_exact_keys(
        receipt,
        {
            "schema_version",
            "source_descriptor_identity",
            "source_bag_begin_record_ns",
            "topics",
            "topic_roles",
            "reader_traversal_count",
            "output_validation_traversal_count",
            "reader_record_start_ns",
            "reader_record_end_ns",
            "reader_message_count",
            "selection_semantics",
            "writer_identity",
            "window_count",
            "observations",
            "receipt_schema_validated",
            "final_paths_published",
            "ros_or_vins_started",
            "held_out_trajectory_outcome_read",
        },
        label="fanout receipt",
    )
    if receipt["schema_version"] != SCHEMA_VERSION:
        raise NTNUWindowFanoutError("fanout receipt schema version differs")
    _validate_file_identity(
        receipt["source_descriptor_identity"], label="source_descriptor_identity"
    )
    if receipt["topics"] != list(topics):
        raise NTNUWindowFanoutError("fanout receipt topic order differs")
    if receipt["topic_roles"] != {"camera": camera_topic, "imu": imu_topic}:
        raise NTNUWindowFanoutError("fanout receipt topic roles differ")
    exact_integer_fields = (
        "source_bag_begin_record_ns",
        "reader_traversal_count",
        "reader_record_start_ns",
        "reader_record_end_ns",
        "reader_message_count",
        "window_count",
        "output_validation_traversal_count",
    )
    if any(type(receipt[key]) is not int or receipt[key] < 0 for key in exact_integer_fields):
        raise NTNUWindowFanoutError("fanout receipt contains a non-exact integer")
    if type(receipt["reader_traversal_count"]) is not int or receipt["reader_traversal_count"] != 1:
        raise NTNUWindowFanoutError("source reader traversal count must equal one")
    if receipt["reader_message_count"] <= 0:
        raise NTNUWindowFanoutError("source reader message count must be positive")
    if receipt["selection_semantics"] != SELECTION_SEMANTICS:
        raise NTNUWindowFanoutError("fanout receipt selection semantics differ")
    if receipt["window_count"] != len(windows):
        raise NTNUWindowFanoutError("fanout receipt window count differs")
    if receipt["output_validation_traversal_count"] != len(windows):
        raise NTNUWindowFanoutError("output validation traversal count differs")
    expected_reader_start = (
        receipt["source_bag_begin_record_ns"] + windows[0].start_offset_ns
    )
    expected_reader_end = (
        receipt["source_bag_begin_record_ns"] + windows[-1].end_offset_ns
    )
    if (
        receipt["reader_record_start_ns"] != expected_reader_start
        or receipt["reader_record_end_ns"] != expected_reader_end
    ):
        raise NTNUWindowFanoutError("source reader outer bounds differ")
    _time_from_ns(expected_reader_start)
    _time_from_ns(expected_reader_end)
    for flag, expected in (
        ("receipt_schema_validated", True),
        ("final_paths_published", False),
        ("ros_or_vins_started", False),
        ("held_out_trajectory_outcome_read", False),
    ):
        if receipt[flag] is not expected:
            raise NTNUWindowFanoutError(f"fanout receipt flag differs: {flag}")

    writer = receipt["writer_identity"]
    _require_exact_keys(
        writer,
        {
            "rosbag_format_version",
            "compression",
            "chunk_threshold_bytes",
            "raw_copy",
            "connection_header_preserved",
            "selection_semantics",
            "writer_identity_sha256",
        },
        label="writer_identity",
    )
    writer_body = dict(writer)
    writer_hash = writer_body.pop("writer_identity_sha256")
    _require_sha256(writer_hash, label="writer_identity_sha256")
    if writer_hash != _canonical_json_hash(writer_body):
        raise NTNUWindowFanoutError("writer identity hash differs")
    if writer != _writer_identity():
        raise NTNUWindowFanoutError("writer identity is not the fixed fanout writer")

    observations = receipt["observations"]
    if not isinstance(observations, list) or len(observations) != len(windows):
        raise NTNUWindowFanoutError("fanout observations do not exactly cover windows")
    for observation, window in zip(observations, windows):
        _require_exact_keys(
            observation,
            {
                "window_id",
                "staged_path",
                "stage_file_identity",
                "sha256",
                "size_bytes",
                "topic_counts",
                "total_messages",
                "raw_record_transcript_sha256",
                "record_filter_window",
                "evaluation_window",
                "bag_integrity",
                "writer_identity",
                "connections",
                "connection_identity_sha256",
            },
            label="fanout observation",
        )
        if observation["window_id"] != window.window_id:
            raise NTNUWindowFanoutError("fanout observation order differs")
        if (
            not isinstance(observation["staged_path"], str)
            or not os.path.isabs(observation["staged_path"])
        ):
            raise NTNUWindowFanoutError("staged path must be absolute receipt text")
        _validate_file_identity(
            observation["stage_file_identity"], label="stage_file_identity"
        )
        if observation["size_bytes"] != observation["stage_file_identity"]["size_bytes"]:
            raise NTNUWindowFanoutError("stage size differs from bound identity")
        _require_sha256(observation["sha256"], label="stage sha256")
        _require_sha256(
            observation["raw_record_transcript_sha256"],
            label="raw record transcript sha256",
        )
        counts = observation["topic_counts"]
        if (
            not isinstance(counts, dict)
            or set(counts) != set(topics)
            or any(type(counts[topic]) is not int or counts[topic] <= 0 for topic in topics)
        ):
            raise NTNUWindowFanoutError("observation topic counts differ")
        if (
            type(observation["total_messages"]) is not int
            or observation["total_messages"] < 0
            or observation["total_messages"] != sum(counts.values())
        ):
            raise NTNUWindowFanoutError("observation total message count differs")
        if observation["writer_identity"] != writer:
            raise NTNUWindowFanoutError("observation writer identity differs")

        record_filter = observation["record_filter_window"]
        _require_exact_keys(
            record_filter,
            {
                "selected_record_start_ns",
                "selected_record_end_ns",
                "first_record_stamp_ns",
                "last_record_stamp_ns",
                "lower_bound_inclusive",
                "upper_bound_inclusive",
                "selection_semantics",
            },
            label="record_filter_window",
        )
        expected_start = receipt["source_bag_begin_record_ns"] + window.start_offset_ns
        expected_end = receipt["source_bag_begin_record_ns"] + window.end_offset_ns
        if (
            record_filter["selected_record_start_ns"] != expected_start
            or record_filter["selected_record_end_ns"] != expected_end
            or record_filter["lower_bound_inclusive"] is not True
            or record_filter["upper_bound_inclusive"] is not True
            or record_filter["selection_semantics"] != SELECTION_SEMANTICS
            or type(record_filter["first_record_stamp_ns"]) is not int
            or type(record_filter["last_record_stamp_ns"]) is not int
            or not expected_start
            <= record_filter["first_record_stamp_ns"]
            <= record_filter["last_record_stamp_ns"]
            <= expected_end
        ):
            raise NTNUWindowFanoutError("record filter evidence differs")

        evaluation = observation["evaluation_window"]
        _require_exact_keys(
            evaluation,
            {
                "camera_topic",
                "start_ros_time_ns",
                "end_ros_time_ns",
                "first_header_stamp_ns",
                "last_header_stamp_ns",
                "stamp_source",
            },
            label="evaluation_window",
        )
        if (
            evaluation["camera_topic"] != camera_topic
            or type(evaluation["start_ros_time_ns"]) is not int
            or type(evaluation["end_ros_time_ns"]) is not int
            or evaluation["start_ros_time_ns"] != evaluation["first_header_stamp_ns"]
            or evaluation["end_ros_time_ns"] != evaluation["last_header_stamp_ns"]
            or evaluation["start_ros_time_ns"] > evaluation["end_ros_time_ns"]
            or evaluation["stamp_source"] != "sensor_message_Header.stamp"
        ):
            raise NTNUWindowFanoutError("evaluation-window evidence differs")

        integrity = observation["bag_integrity"]
        _require_exact_keys(
            integrity,
            {
                "topic_counts",
                "total_messages",
                "camera_topic",
                "imu_topic",
                "selected_camera_count",
                "selected_record_start_ns",
                "selected_record_end_ns",
                "first_record_stamp_ns",
                "last_record_stamp_ns",
                "start_ros_time_ns",
                "end_ros_time_ns",
                "header_stamp_ranges_ns",
                "stamp_source",
                "raw_record_transcript_sha256",
                "output_revalidated",
                "trajectory_values_interpreted",
            },
            label="bag_integrity",
        )
        if (
            integrity["topic_counts"] != counts
            or type(integrity["total_messages"]) is not int
            or integrity["total_messages"] < 0
            or integrity["total_messages"] != observation["total_messages"]
            or integrity["camera_topic"] != camera_topic
            or integrity["imu_topic"] != imu_topic
            or type(integrity["selected_camera_count"]) is not int
            or integrity["selected_camera_count"] < 0
            or integrity["selected_camera_count"] != counts[camera_topic]
            or integrity["selected_record_start_ns"]
            != record_filter["selected_record_start_ns"]
            or integrity["selected_record_end_ns"]
            != record_filter["selected_record_end_ns"]
            or integrity["first_record_stamp_ns"]
            != record_filter["first_record_stamp_ns"]
            or integrity["last_record_stamp_ns"] != record_filter["last_record_stamp_ns"]
            or integrity["start_ros_time_ns"] != evaluation["start_ros_time_ns"]
            or integrity["end_ros_time_ns"] != evaluation["end_ros_time_ns"]
            or integrity["stamp_source"] != "sensor_message_Header.stamp"
            or integrity["raw_record_transcript_sha256"]
            != observation["raw_record_transcript_sha256"]
            or integrity["output_revalidated"] is not True
            or integrity["trajectory_values_interpreted"] is not False
        ):
            raise NTNUWindowFanoutError("bag-integrity evidence differs")
        header_ranges = integrity["header_stamp_ranges_ns"]
        if not isinstance(header_ranges, dict) or set(header_ranges) != set(topics):
            raise NTNUWindowFanoutError("header stamp ranges differ")
        for topic in topics:
            _require_exact_keys(
                header_ranges[topic], {"first", "last"}, label="header stamp range"
            )
            if (
                type(header_ranges[topic]["first"]) is not int
                or type(header_ranges[topic]["last"]) is not int
                or header_ranges[topic]["first"] > header_ranges[topic]["last"]
            ):
                raise NTNUWindowFanoutError("header stamp range is invalid")
        if (
            header_ranges[camera_topic]["first"] != evaluation["start_ros_time_ns"]
            or header_ranges[camera_topic]["last"] != evaluation["end_ros_time_ns"]
        ):
            raise NTNUWindowFanoutError("camera header range differs")

        connections = observation["connections"]
        if not isinstance(connections, list) or len(connections) != len(topics):
            raise NTNUWindowFanoutError("output connections do not exactly cover topics")
        for connection, topic in zip(connections, topics):
            _require_exact_keys(
                connection,
                {
                    "topic",
                    "datatype",
                    "md5sum",
                    "message_definition_sha256",
                    "connection_header_sha256",
                    "connection_identity_sha256",
                    "output_connection_id",
                },
                label="output connection",
            )
            if (
                connection["topic"] != topic
                or type(connection["output_connection_id"]) is not int
                or connection["output_connection_id"] < 0
            ):
                raise NTNUWindowFanoutError("output connection order differs")
            for key in (
                "message_definition_sha256",
                "connection_header_sha256",
                "connection_identity_sha256",
            ):
                _require_sha256(connection[key], label=f"connection {key}")
            connection_body = dict(connection)
            connection_body.pop("output_connection_id")
            identity_hash = connection_body.pop("connection_identity_sha256")
            if identity_hash != _canonical_json_hash(connection_body):
                raise NTNUWindowFanoutError("output connection identity hash differs")
        _require_sha256(
            observation["connection_identity_sha256"],
            label="connection list identity sha256",
        )
        if observation["connection_identity_sha256"] != _canonical_json_hash(connections):
            raise NTNUWindowFanoutError("connection-list identity hash differs")


def materialize_ntnu_windows(
    source_proc_path: os.PathLike,
    windows: Sequence[RecordWindow],
    staged_output_paths: Mapping[str, os.PathLike],
    topics: Sequence[str] = DEFAULT_TOPICS,
) -> dict:
    """Write closed NTNU record windows to caller-owned exclusive stage paths.

    ``T0`` is the first record of the complete source bag, including topics
    excluded from output.  The function calls ``read_messages`` exactly once,
    with the selected two topics and the outer absolute bounds.  It never
    renames or links a stage into a final path.
    """

    selected_topics = _validate_topics(topics)
    selected_windows = _validate_windows(windows)
    stage_paths = _stage_paths(selected_windows, staged_output_paths)
    source_path, source_fd, source_info_before = _source_descriptor(source_proc_path)
    source_identity = _file_identity(source_info_before)
    created = []
    stage_identities = {}
    audit_descriptors = set()
    stage_audit_descriptors = {}

    try:
        with rosbag.Bag(source_path, "r") as source:
            source_begin_ns = _bag_begin_ns(source)
            source_connections = _source_connections(source, selected_topics)
            camera_topic, imu_topic = _topic_roles(source_connections)
            expected_connections = {
                topic: _connection_record(source_connections[topic])
                for topic in selected_topics
            }

            absolute_starts = [
                source_begin_ns + window.start_offset_ns for window in selected_windows
            ]
            absolute_ends = [
                source_begin_ns + window.end_offset_ns for window in selected_windows
            ]
            for bound in absolute_starts + absolute_ends:
                _time_from_ns(bound)
            reader_start_ns = absolute_starts[0]
            reader_end_ns = absolute_ends[-1]

            states = []
            with ExitStack() as writers:
                for window in selected_windows:
                    path = stage_paths[window.window_id]
                    writer, identity, audit_descriptor = _open_stage_writer(path)
                    created.append(path)
                    stage_identities[path] = identity
                    audit_descriptors.add(audit_descriptor)
                    stage_audit_descriptors[path] = audit_descriptor
                    writers.callback(writer.close)
                    states.append(
                        _WindowState(
                            window=window,
                            staged_path=path,
                            writer=writer,
                            audit_fd=audit_descriptor,
                            topic_counts={topic: 0 for topic in selected_topics},
                        )
                    )

                previous_global_record_ns = -1
                previous_topic_record_ns = {topic: -1 for topic in selected_topics}
                previous_topic_header_ns = {topic: -1 for topic in selected_topics}
                reader_message_count = 0
                messages = source.read_messages(
                    topics=list(selected_topics),
                    start_time=_time_from_ns(reader_start_ns),
                    end_time=_time_from_ns(reader_end_ns),
                    raw=True,
                    return_connection_header=True,
                )
                for item in messages:
                    reader_message_count += 1
                    topic = str(item.topic)
                    if topic not in expected_connections:
                        raise NTNUWindowFanoutError(
                            f"reader returned an unrequested topic: {topic}"
                        )
                    record_ns = _exact_time_ns(item.timestamp, label="source record stamp")
                    if not reader_start_ns <= record_ns <= reader_end_ns:
                        raise NTNUWindowFanoutError("ROS1 reader violated its closed bounds")
                    if record_ns < previous_global_record_ns:
                        raise NTNUWindowFanoutError(
                            "source reader record stamps are non-monotonic"
                        )
                    if record_ns <= previous_topic_record_ns[topic]:
                        raise NTNUWindowFanoutError(
                            f"source record stamps are not strictly increasing on {topic}"
                        )
                    previous_global_record_ns = record_ns
                    previous_topic_record_ns[topic] = record_ns

                    raw_message = item.message
                    expected = expected_connections[topic]
                    if (
                        raw_message[0] != expected["datatype"]
                        or raw_message[2] != expected["md5sum"]
                        or _connection_header_sha256(item.connection_header)
                        != expected["connection_header_sha256"]
                    ):
                        raise NTNUWindowFanoutError(
                            f"raw message/connection identity drift on {topic}"
                        )
                    header_ns = _raw_header_stamp_ns(raw_message, topic=topic)
                    if header_ns <= previous_topic_header_ns[topic]:
                        raise NTNUWindowFanoutError(
                            f"Header.stamp is not strictly increasing on {topic}"
                        )
                    previous_topic_header_ns[topic] = header_ns

                    # lower_bound(end >= t), upper_bound(start <= t).  With
                    # interior-disjoint windows this yields zero, one, or the
                    # two windows sharing an inclusive endpoint.
                    lower = bisect.bisect_left(absolute_ends, record_ns)
                    upper = bisect.bisect_right(absolute_starts, record_ns)
                    if lower > upper:
                        raise NTNUWindowFanoutError("invalid closed-window bisect range")
                    for index in range(lower, upper):
                        state = states[index]
                        if not absolute_starts[index] <= record_ns <= absolute_ends[index]:
                            raise NTNUWindowFanoutError("closed-window selection invariant failed")
                        state.writer.write(
                            topic,
                            raw_message,
                            item.timestamp,
                            raw=True,
                            connection_header=item.connection_header,
                        )
                        _update_raw_record_transcript(
                            state.raw_record_transcripts.setdefault(
                                topic, hashlib.sha256()
                            ),
                            topic=topic,
                            record_ns=record_ns,
                            raw_message=raw_message,
                            connection_header=item.connection_header,
                        )
                        state.topic_counts[topic] += 1
                        if state.first_record_stamp_ns is None:
                            state.first_record_stamp_ns = record_ns
                        state.last_record_stamp_ns = record_ns
                        if topic not in state.header_first_ns:
                            state.header_first_ns[topic] = header_ns
                        state.header_last_ns[topic] = header_ns

                if reader_message_count == 0:
                    raise NTNUWindowFanoutError("reader interval contains no selected messages")
                for state in states:
                    missing = [
                        topic for topic in selected_topics if state.topic_counts[topic] == 0
                    ]
                    if missing:
                        raise NTNUWindowFanoutError(
                            f"window {state.window.window_id} lacks selected topic(s): {missing}"
                        )

        source_info_after = os.fstat(source_fd)
        if _file_identity(source_info_after) != source_identity:
            raise NTNUWindowFanoutError("source descriptor identity changed during fanout")

        writer_identity = _writer_identity()
        observations = []
        final_stage_identities = {}
        for index, state in enumerate(states):
            create_identity = stage_identities[state.staged_path]
            stage_fd = state.audit_fd
            os.fsync(stage_fd)
            identity_before_audit = _file_identity(_descriptor_stat(stage_fd))
            if not _same_inode(_descriptor_stat(stage_fd), create_identity):
                raise NTNUWindowFanoutError(
                    f"retained stage descriptor identity differs: {state.staged_path}"
                )
            output_audit = _audit_output(
                f"/proc/self/fd/{stage_fd}",
                selected_topics,
                expected_connections,
                state,
            )
            stage_sha256 = _sha256_descriptor(stage_fd)
            identity_after_audit = _file_identity(_descriptor_stat(stage_fd))
            if identity_after_audit != identity_before_audit:
                raise NTNUWindowFanoutError(
                    f"completed stage changed during audit: {state.staged_path}"
                )

            final_stage_identities[state.staged_path] = identity_after_audit
            _revalidate_stage_path(
                state.staged_path,
                create_identity,
                identity_after_audit,
            )
            connections = output_audit["connections"]
            connection_identity_sha256 = _canonical_json_hash(connections)
            size_bytes = identity_after_audit["size_bytes"]
            record_filter_window = {
                "selected_record_start_ns": absolute_starts[index],
                "selected_record_end_ns": absolute_ends[index],
                "first_record_stamp_ns": int(output_audit["first_record_stamp_ns"]),
                "last_record_stamp_ns": int(output_audit["last_record_stamp_ns"]),
                "lower_bound_inclusive": True,
                "upper_bound_inclusive": True,
                "selection_semantics": SELECTION_SEMANTICS,
            }
            evaluation_window = {
                "camera_topic": camera_topic,
                "start_ros_time_ns": int(output_audit["header_first_ns"][camera_topic]),
                "end_ros_time_ns": int(output_audit["header_last_ns"][camera_topic]),
                "first_header_stamp_ns": int(
                    output_audit["header_first_ns"][camera_topic]
                ),
                "last_header_stamp_ns": int(
                    output_audit["header_last_ns"][camera_topic]
                ),
                "stamp_source": "sensor_message_Header.stamp",
            }
            bag_integrity = {
                "topic_counts": dict(output_audit["topic_counts"]),
                "total_messages": int(sum(output_audit["topic_counts"].values())),
                "camera_topic": camera_topic,
                "imu_topic": imu_topic,
                "selected_camera_count": int(
                    output_audit["topic_counts"][camera_topic]
                ),
                "selected_record_start_ns": record_filter_window[
                    "selected_record_start_ns"
                ],
                "selected_record_end_ns": record_filter_window[
                    "selected_record_end_ns"
                ],
                "first_record_stamp_ns": record_filter_window[
                    "first_record_stamp_ns"
                ],
                "last_record_stamp_ns": record_filter_window[
                    "last_record_stamp_ns"
                ],
                "start_ros_time_ns": evaluation_window["start_ros_time_ns"],
                "end_ros_time_ns": evaluation_window["end_ros_time_ns"],
                "header_stamp_ranges_ns": {
                    topic: {
                        "first": int(output_audit["header_first_ns"][topic]),
                        "last": int(output_audit["header_last_ns"][topic]),
                    }
                    for topic in selected_topics
                },
                "stamp_source": "sensor_message_Header.stamp",
                "raw_record_transcript_sha256": output_audit[
                    "raw_record_transcript_sha256"
                ],
                "output_revalidated": True,
                "trajectory_values_interpreted": False,
            }
            observations.append(
                {
                    "window_id": state.window.window_id,
                    "staged_path": os.fspath(state.staged_path),
                    "stage_file_identity": dict(identity_after_audit),
                    "sha256": stage_sha256,
                    "size_bytes": size_bytes,
                    "topic_counts": dict(output_audit["topic_counts"]),
                    "total_messages": int(sum(output_audit["topic_counts"].values())),
                    "raw_record_transcript_sha256": output_audit[
                        "raw_record_transcript_sha256"
                    ],
                    "record_filter_window": record_filter_window,
                    "evaluation_window": evaluation_window,
                    "bag_integrity": bag_integrity,
                    "writer_identity": dict(writer_identity),
                    "connections": connections,
                    "connection_identity_sha256": connection_identity_sha256,
                }
            )

        receipt = {
            "schema_version": SCHEMA_VERSION,
            "source_descriptor_identity": source_identity,
            "source_bag_begin_record_ns": source_begin_ns,
            "topics": list(selected_topics),
            "topic_roles": {"camera": camera_topic, "imu": imu_topic},
            "reader_traversal_count": 1,
            "output_validation_traversal_count": len(observations),
            "reader_record_start_ns": reader_start_ns,
            "reader_record_end_ns": reader_end_ns,
            "reader_message_count": reader_message_count,
            "selection_semantics": SELECTION_SEMANTICS,
            "writer_identity": writer_identity,
            "window_count": len(observations),
            "observations": observations,
            "receipt_schema_validated": True,
            "final_paths_published": False,
            "ros_or_vins_started": False,
            "held_out_trajectory_outcome_read": False,
        }
        _validate_receipt(
            receipt,
            selected_windows,
            selected_topics,
            camera_topic,
            imu_topic,
        )
        for state in states:
            _revalidate_stage_path(
                state.staged_path,
                stage_identities[state.staged_path],
                final_stage_identities[state.staged_path],
            )
        return receipt
    except BaseException as error:
        for path in reversed(created):
            identity = stage_identities.get(path)
            if identity is not None:
                try:
                    _unlink_owned_stage(
                        path,
                        identity,
                        stage_audit_descriptors.get(path),
                    )
                except StageCleanupIncomplete as cleanup_error:
                    _add_cleanup_note(error, str(cleanup_error))
                except BaseException as cleanup_error:
                    _add_cleanup_note(
                        error,
                        f"stage preservation failed after error: {path}: {cleanup_error!r}",
                    )
        raise
    finally:
        for descriptor in tuple(audit_descriptors):
            try:
                os.close(descriptor)
            except OSError:
                pass
        os.close(source_fd)
