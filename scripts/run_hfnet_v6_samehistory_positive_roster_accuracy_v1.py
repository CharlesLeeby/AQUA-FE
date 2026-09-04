#!/usr/bin/env python3
"""Exactly-once controller for the frozen HFNet-v6 roster accuracy analysis.

There are three deliberately separate phases:

``freeze-lock``
    Outcome-aware but pre-metric.  It verifies the published prestart seal and
    the terminal HFNet runability receipt, freezes the HFNet trajectory's
    float-epoch-to-camera-header bridge (maximum error 256 ns), then publishes
    one canonical per-case execution lock.  It never computes support, APE,
    RPE, or a ranking.

``check``
    Read-only authorization preflight.  It verifies canonical paths and JSON,
    all pinned file identities, receipt semantics, code self-identities, the
    frame/evo contracts, and destination absence.  It never loads coordinates.

``run``
    Requires the frozen authorization token, takes one atomic process claim,
    repeats the complete identity verification, invokes the pure evaluator
    only through its opaque ``ValidatedExecutionLock``, performs the real evo
    subprocess cross-check, re-verifies every scientific input, and publishes
    one terminal receipt.  Once the claim exists the case is consumed: every
    failure is terminal and retry is forbidden.

The publisher is suitable for the project's fuseblk volume: immutable files
are created through a temporary O_EXCL inode, file fsync, hard-link
no-replace, and directory fsync.  ``rename`` is intentionally never used.
"""

from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import sys
from typing import Any, Callable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = Path(__file__).resolve()
EVALUATOR = (
    ROOT
    / "scripts/evaluate_hfnet_v6_samehistory_positive_roster_common_support_v1.py"
)
DEFAULT_PREFREEZE_SEAL = Path(
    "/mnt/data/AQUA-FE_WS/locks/"
    "hfnet_v6_samehistory_positive_accuracy_prefreeze_seal_v1.json"
)
RUNTIME_ROOT = Path(
    "/mnt/data/AQUA-FE_WS/logs/published_hfnet_slam_v6/"
    "samehistory_old_positive_roster_v2"
)
DEFAULT_EXECUTION_LOCK_ROOT = RUNTIME_ROOT / "_accuracy_execution_locks_v1"
DEFAULT_ACCURACY_ROOT = RUNTIME_ROOT / "_accuracy_analysis_v1"

SCHEMA_VERSION = (
    "aqua-fe-hfnet-v6-samehistory-positive-roster-accuracy-controller-v1"
)
BRIDGE_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-hfnet-timestamp-bridge-v1"
)
VERIFICATION_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-formal-identity-verification-v1"
)
CLAIM_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-accuracy-start-once-claim-v1"
)
TERMINAL_SCHEMA = (
    "aqua-fe-hfnet-v6-samehistory-positive-accuracy-terminal-receipt-v1"
)
AUTHORIZATION_TOKEN = "RUN_FROZEN_HFNET_V6_SAMEHISTORY_ACCURACY_V1"
AUTHORIZATION_TOKEN_SHA256 = hashlib.sha256(AUTHORIZATION_TOKEN.encode("ascii")).hexdigest()
FREEZE_LOCK_AUTHORIZATION_TOKEN = "FREEZE_HFNET_V6_SAMEHISTORY_ACCURACY_LOCK_V1"

FINAL_PREFREEZE_IDENTITY = {
    "path": str(
        ROOT
        / "papers/hfnet_v6_samehistory_positive_accuracy_analysis_grid_prefreeze_v1.md"
    ),
    "size_bytes": 16_833,
    "sha256": "d31b9ee9f22ae47ba6e5b7d5d28f6a528331fd1c7071367ea28aed5032773f8d",
}
# The seal contains this controller's exact file identity, so pinning the raw
# seal hash here would create an impossible controller<->seal hash cycle.
# Instead, the controller identity field alone is replaced by this fixed
# sentinel and the hash of every other byte of the canonical seal is pinned.
# The unnormalised identity is still checked against the running controller.
PRESTART_SEAL_CONTROLLER_IDENTITY_SENTINEL = {
    "path": "<NORMALIZED_CONTROLLER_SELF>",
    "size_bytes": 0,
    "sha256": "0" * 64,
}
PRESTART_SEAL_SEMANTIC_PROJECTION_SHA256 = (
    "b6c6b8aa89f39318520074f915786bac6dfc16675c4848ae1bab140b7b45a7ad"
)
V2_ROSTER_AUTHORITY_IDENTITIES = {
    "whole_roster_pointer": {
        "path": "/mnt/data/AQUA-FE_WS/locks/hfnet_v6_samehistory_positive_roster_execution_lock_v2.json",
        "size_bytes": 5_296,
        "sha256": "f9b44e9c126e68d151368c84a562aef5f9b06e1200b6f5dd1b6fe55d33430df1",
    },
    "roster_lock": {
        "path": (
            "/mnt/data/AQUA-FE_WS/locks/"
            ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
            "a1df6b5e08cc9230/roster_lock.json"
        ),
        "size_bytes": 3_132,
        "sha256": "a1df6b5e08cc923087e563caddf017eac344d111ddc3b2db801949a620245289",
    },
    "roster_build_receipt": {
        "path": (
            "/mnt/data/AQUA-FE_WS/locks/"
            ".hfnet_v6_samehistory_positive_roster_execution_lock_v2.bundle-"
            "a1df6b5e08cc9230/build_receipt.json"
        ),
        "size_bytes": 5_379,
        "sha256": "946f272063bfc55dc11296fcdbc09197419bd506818959bced8a836140fe8017",
    },
    "prepared_runner": {
        "path": str(ROOT / "scripts/run_hfnet_v6_samehistory_positive_roster_v2.py"),
        "size_bytes": 7_639,
        "sha256": "ec1afff8b1f7a8fdac0e7d395648bd4aa4b47b107bd3c2871a034eb49ba83bbb",
    },
    "prestart_parser_supersession_protocol": {
        "path": str(
            ROOT
            / "papers/hfnet_v6_samehistory_positive_roster_prestart_parser_supersession_v2.md"
        ),
        "size_bytes": 4_653,
        "sha256": "cd8691886d6a9e219d0d87cb5b5a7df531433cf7f24ee3babb8190c8f58c5ae7",
    },
}
BRIDGE_MAX_ABSOLUTE_DELTA_NS = 256
EVO_MAX_RMSE_DISAGREEMENT_M = 1e-5
SOURCE_ORDER = ("reference", "hfnet", "learned_plus_klt", "klt")
ESTIMATE_ORDER = ("hfnet", "learned_plus_klt", "klt")
CASE_ORDER = (
    "a05_3300_3700",
    "a07_10800_11200",
    "a08_4500_4660",
    "a09_6000_6200",
    "fjord1_s83_d10",
    "mclab1_s60_d15",
    "cirs_s575_d30",
    "cirs_s900_d30",
    "a02_7600_8000",
    "mclab2_s110_d10",
)


class ControllerError(RuntimeError):
    """A fail-closed contract error with a stable machine-readable code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ControllerError(code)


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_existing_path(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"PATH_NOT_ABSOLUTE:{label}")
    try:
        canonical = path.resolve(strict=True)
    except OSError as error:
        raise ControllerError(f"PATH_RESOLVE_FAILED:{label}:{type(error).__name__}") from error
    require(str(path) == str(canonical), f"PATH_NOT_CANONICAL:{label}")
    return canonical


def _canonical_future_path(path: Path, label: str) -> Path:
    require(path.is_absolute(), f"PATH_NOT_ABSOLUTE:{label}")
    try:
        canonical = path.resolve(strict=False)
    except OSError as error:
        raise ControllerError(f"PATH_RESOLVE_FAILED:{label}:{type(error).__name__}") from error
    require(str(path) == str(canonical), f"PATH_NOT_CANONICAL:{label}")
    return canonical


def _identity_shape(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), f"IDENTITY_NOT_OBJECT:{label}")
    require(set(value) == {"path", "size_bytes", "sha256"}, f"IDENTITY_KEYS:{label}")
    require(isinstance(value["path"], str), f"IDENTITY_PATH_TYPE:{label}")
    _canonical_existing_path(Path(value["path"]), f"identity:{label}")
    require(
        isinstance(value["size_bytes"], int)
        and not isinstance(value["size_bytes"], bool)
        and value["size_bytes"] >= 0,
        f"IDENTITY_SIZE:{label}",
    )
    digest = value["sha256"]
    require(
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest),
        f"IDENTITY_SHA256:{label}",
    )
    return value


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    size_bytes: int
    sha256: str
    st_dev: int
    st_ino: int
    st_mtime_ns: int
    st_mode: int
    st_nlink: int

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @property
    def stat_binding(self) -> dict[str, int]:
        return {
            "st_dev": self.st_dev,
            "st_ino": self.st_ino,
            "st_mtime_ns": self.st_mtime_ns,
            "st_mode": self.st_mode,
            "st_nlink": self.st_nlink,
        }


def _snapshot_from_fd(path: Path, descriptor: int) -> tuple[FileSnapshot, bytes]:
    before = os.fstat(descriptor)
    require(stat.S_ISREG(before.st_mode), f"NOT_REGULAR_FILE:{path}")
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    total = 0
    while True:
        block = os.read(descriptor, 1024 * 1024)
        if not block:
            break
        digest.update(block)
        chunks.append(block)
        total += len(block)
    after = os.fstat(descriptor)
    signature_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_mode,
        before.st_nlink,
    )
    signature_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_mode,
        after.st_nlink,
    )
    require(signature_before == signature_after, f"FILE_CHANGED_DURING_READ:{path}")
    require(total == after.st_size, f"FILE_SHORT_READ:{path}")
    return (
        FileSnapshot(
            path=str(path),
            size_bytes=after.st_size,
            sha256=digest.hexdigest(),
            st_dev=after.st_dev,
            st_ino=after.st_ino,
            st_mtime_ns=after.st_mtime_ns,
            st_mode=after.st_mode,
            st_nlink=after.st_nlink,
        ),
        b"".join(chunks),
    )


def snapshot_file(path: Path, label: str) -> tuple[FileSnapshot, bytes]:
    canonical = _canonical_existing_path(path, label)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(canonical), flags)
    except OSError as error:
        raise ControllerError(f"FILE_OPEN_FAILED:{label}:{error.errno}") from error
    try:
        snapshot, payload = _snapshot_from_fd(canonical, descriptor)
    finally:
        os.close(descriptor)
    try:
        leaf = os.lstat(str(canonical))
    except OSError as error:
        raise ControllerError(f"FILE_LSTAT_FAILED:{label}:{error.errno}") from error
    require(not stat.S_ISLNK(leaf.st_mode), f"FILE_LEAF_SYMLINK:{label}")
    require(
        (leaf.st_dev, leaf.st_ino, leaf.st_size, leaf.st_mtime_ns)
        == (snapshot.st_dev, snapshot.st_ino, snapshot.size_bytes, snapshot.st_mtime_ns),
        f"FILE_CHANGED_AFTER_READ:{label}",
    )
    return snapshot, payload


def verify_pinned_file(
    expected: Mapping[str, Any], label: str
) -> tuple[FileSnapshot, bytes]:
    _identity_shape(expected, label)
    observed, payload = snapshot_file(Path(str(expected["path"])), label)
    require(observed.identity == dict(expected), f"IDENTITY_MISMATCH:{label}")
    return observed, payload


def read_canonical_json_identity(
    expected: Mapping[str, Any], label: str
) -> tuple[dict[str, Any], FileSnapshot]:
    snapshot, payload = verify_pinned_file(expected, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ControllerError(f"JSON_INVALID:{label}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{label}")
    require(payload == canonical_json_bytes(value), f"JSON_NOT_CANONICAL:{label}")
    return value, snapshot


def read_canonical_json_path(path: Path, label: str) -> tuple[dict[str, Any], FileSnapshot]:
    snapshot, payload = snapshot_file(path, label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ControllerError(f"JSON_INVALID:{label}") from error
    require(isinstance(value, dict), f"JSON_ROOT_NOT_OBJECT:{label}")
    require(payload == canonical_json_bytes(value), f"JSON_NOT_CANONICAL:{label}")
    return value, snapshot


def _assert_same_snapshot(before: FileSnapshot, after: FileSnapshot, label: str) -> None:
    require(before == after, f"TOCTOU_DETECTED:{label}")


class IdentityLedger:
    """Keep pre-open snapshots and re-hash them before any final publication."""

    def __init__(self) -> None:
        self._values: dict[str, FileSnapshot] = {}

    def add(self, label: str, snapshot: FileSnapshot) -> None:
        require(label not in self._values, f"LEDGER_DUPLICATE_LABEL:{label}")
        self._values[label] = snapshot

    def verify_all(self) -> dict[str, Any]:
        post: dict[str, Any] = {}
        for label in sorted(self._values):
            before = self._values[label]
            after, _payload = snapshot_file(Path(before.path), f"post:{label}")
            _assert_same_snapshot(before, after, label)
            post[label] = {
                "identity": after.identity,
                "stat_binding": after.stat_binding,
            }
        return post

    def evidence(self) -> dict[str, Any]:
        return {
            label: {
                "identity": value.identity,
                "stat_binding": value.stat_binding,
            }
            for label, value in sorted(self._values.items())
        }


def fsync_directory(path: Path) -> None:
    descriptor = os.open(
        str(path), os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        require(written > 0, "ATOMIC_PUBLICATION_SHORT_WRITE")
        view = view[written:]


def atomic_publish_noreplace(path: Path, payload: bytes, mode: int = 0o444) -> FileSnapshot:
    """Publish immutable bytes without rename or replacement."""

    target = _canonical_future_path(path, "atomic_target")
    parent = target.parent
    require(parent.is_dir() and not parent.is_symlink(), "ATOMIC_PARENT_INVALID")
    temporary = parent / f".{target.name}.tmp-{os.getpid()}-{secrets.token_hex(12)}"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor: int | None = None
    linked = False
    try:
        descriptor = os.open(str(temporary), flags, 0o600)
        _write_all(descriptor, payload)
        os.fsync(descriptor)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
        try:
            os.link(str(temporary), str(target), follow_symlinks=False)
        except FileExistsError as error:
            raise ControllerError(f"PUBLICATION_EXISTS:{target}") from error
        except OSError as error:
            raise ControllerError(f"PUBLICATION_HARDLINK_FAILED:{target}:{error.errno}") from error
        linked = True
        fsync_directory(parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(str(temporary))
        except FileNotFoundError:
            pass
        except OSError:
            if not linked:
                raise
        if parent.exists():
            fsync_directory(parent)
    observed, observed_payload = snapshot_file(target, "published")
    require(observed_payload == payload, f"PUBLICATION_CONTENT_MISMATCH:{target}")
    return observed


def _mkdir_plain(path: Path) -> None:
    canonical = _canonical_future_path(path, "mkdir")
    if canonical.exists():
        require(canonical.is_dir() and not canonical.is_symlink(), f"DIRECTORY_INVALID:{path}")
        return
    _mkdir_plain(canonical.parent)
    try:
        os.mkdir(str(canonical), 0o755)
    except FileExistsError:
        require(canonical.is_dir() and not canonical.is_symlink(), f"DIRECTORY_RACE:{path}")
    fsync_directory(canonical.parent)


def _mkdir_exclusive(path: Path) -> None:
    target = _canonical_future_path(path, "exclusive_directory")
    require(target.parent.is_dir() and not target.parent.is_symlink(), "EXCLUSIVE_PARENT_INVALID")
    try:
        os.mkdir(str(target), 0o755)
    except FileExistsError as error:
        raise ControllerError(f"EXCLUSIVE_DIRECTORY_EXISTS:{target}") from error
    fsync_directory(target.parent)


def _destination_absent(path: Path, label: str) -> None:
    canonical = _canonical_future_path(path, label)
    try:
        os.lstat(str(canonical))
    except FileNotFoundError:
        return
    raise ControllerError(f"DESTINATION_EXISTS:{label}")


def require_distinct_canonical_paths(paths: Mapping[str, Path]) -> dict[str, Path]:
    canonical = {
        label: _canonical_future_path(path, f"destination:{label}")
        for label, path in paths.items()
    }
    by_text: dict[str, str] = {}
    for label, path in canonical.items():
        owner = by_text.setdefault(str(path), label)
        require(owner == label, f"DESTINATION_PATH_ALIAS:{owner}:{label}")
    existing: list[tuple[str, Path, os.stat_result]] = []
    for label, path in canonical.items():
        try:
            metadata = os.stat(str(path), follow_symlinks=False)
        except FileNotFoundError:
            continue
        existing.append((label, path, metadata))
    for index, (left_label, _left, left_stat) in enumerate(existing):
        for right_label, _right, right_stat in existing[index + 1 :]:
            require(
                (left_stat.st_dev, left_stat.st_ino)
                != (right_stat.st_dev, right_stat.st_ino),
                f"DESTINATION_INODE_ALIAS:{left_label}:{right_label}",
            )
    return canonical


def decimal_timestamp_to_ns(token: str, label: str) -> int:
    """Convert an integer-ns or decimal/scientific seconds token losslessly."""

    try:
        value = Decimal(token)
    except InvalidOperation as error:
        raise ControllerError(f"TIMESTAMP_DECIMAL_INVALID:{label}") from error
    require(value.is_finite(), f"TIMESTAMP_NONFINITE:{label}")
    # VINS/HFNet frequently serialize epoch nanoseconds as an integer, whereas
    # TUM uses epoch seconds (often scientific notation).  1e14 cleanly
    # separates every frozen source in this roster.
    nanoseconds = value if abs(value) >= Decimal("1e14") else value * Decimal(1_000_000_000)
    integral = nanoseconds.to_integral_value(rounding=ROUND_HALF_EVEN)
    require(nanoseconds == integral, f"TIMESTAMP_SUBNANOSECOND:{label}")
    result = int(integral)
    require(-(1 << 63) <= result < (1 << 63), f"TIMESTAMP_INT64_RANGE:{label}")
    return result


def _validate_strict_timestamps(values: Sequence[int], label: str) -> list[int]:
    output = [int(value) for value in values]
    require(output, f"TIMESTAMPS_EMPTY:{label}")
    require(
        all(right > left for left, right in zip(output, output[1:])),
        f"TIMESTAMPS_NOT_STRICT:{label}",
    )
    return output


def parse_ascii_pose_rows(
    payload: bytes,
    *,
    format_name: str,
    label: str,
    timestamps_only: bool,
) -> tuple[list[int], list[list[float]], list[list[float]]]:
    """Parse TUM, VINS CSV, or stock HFNet trajectory rows.

    Returned quaternions are always xyzw.  In timestamp-only mode coordinate
    tokens are neither converted nor retained; this is the freeze/check path.
    """

    try:
        lines = payload.decode("ascii").splitlines()
    except UnicodeError as error:
        raise ControllerError(f"TRAJECTORY_NOT_ASCII:{label}") from error
    timestamps: list[int] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    for line_number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = (
            [field.strip() for field in stripped.split(",")]
            if format_name == "VINS_QWXYZ_CSV"
            else stripped.split()
        )
        fields = [field for field in fields if field != ""]
        require(len(fields) >= 8, f"TRAJECTORY_FIELD_COUNT:{label}:{line_number}")
        timestamps.append(decimal_timestamp_to_ns(fields[0], f"{label}:{line_number}"))
        if timestamps_only:
            continue
        try:
            position = [float(value) for value in fields[1:4]]
            raw_quaternion = [float(value) for value in fields[4:8]]
        except ValueError as error:
            raise ControllerError(f"TRAJECTORY_NUMBER_INVALID:{label}:{line_number}") from error
        require(
            all(math.isfinite(value) for value in position + raw_quaternion),
            f"TRAJECTORY_NONFINITE:{label}:{line_number}",
        )
        quaternion = (
            [raw_quaternion[1], raw_quaternion[2], raw_quaternion[3], raw_quaternion[0]]
            if format_name == "VINS_QWXYZ_CSV"
            else raw_quaternion
        )
        norm = math.sqrt(sum(value * value for value in quaternion))
        require(norm > 1e-12, f"TRAJECTORY_ZERO_QUATERNION:{label}:{line_number}")
        quaternion = [value / norm for value in quaternion]
        positions.append(position)
        quaternions.append(quaternion)
    return _validate_strict_timestamps(timestamps, label), positions, quaternions


def bridge_hfnet_timestamps(
    hfnet_epoch_ns: Sequence[int], camera_headers_ns: Sequence[int]
) -> tuple[list[int], list[dict[str, int]]]:
    """Bijectively replace each stock epoch with one unique camera header."""

    stock = _validate_strict_timestamps(hfnet_epoch_ns, "hfnet_epoch")
    headers = _validate_strict_timestamps(camera_headers_ns, "camera_headers")
    mapped: list[int] = []
    evidence: list[dict[str, int]] = []
    used: set[int] = set()
    previous = -1 << 63
    for row, value in enumerate(stock):
        insertion = _bisect_left(headers, value)
        candidates = [index for index in (insertion - 1, insertion) if 0 <= index < len(headers)]
        require(candidates, f"HFNET_BRIDGE_NO_HEADER:{row}")
        distances = [(abs(headers[index] - value), index) for index in candidates]
        minimum = min(distance for distance, _index in distances)
        winners = [index for distance, index in distances if distance == minimum]
        require(len(winners) == 1, f"HFNET_BRIDGE_AMBIGUOUS:{row}")
        index = winners[0]
        require(minimum <= BRIDGE_MAX_ABSOLUTE_DELTA_NS, f"HFNET_BRIDGE_DELTA_GT_256NS:{row}")
        require(index not in used, f"HFNET_BRIDGE_HEADER_REUSED:{row}")
        canonical = headers[index]
        require(canonical > previous, f"HFNET_BRIDGE_NOT_STRICT:{row}")
        used.add(index)
        mapped.append(canonical)
        evidence.append(
            {
                "row": row,
                "serialized_epoch_ns": value,
                "camera_header_index": index,
                "canonical_header_ns": canonical,
                "signed_delta_ns": value - canonical,
                "absolute_delta_ns": minimum,
            }
        )
        previous = canonical
    return mapped, evidence


def _bisect_left(values: Sequence[int], target: int) -> int:
    low, high = 0, len(values)
    while low < high:
        middle = (low + high) // 2
        if values[middle] < target:
            low = middle + 1
        else:
            high = middle
    return low


def ordered_ns_digest(values: Sequence[int]) -> str:
    payload = "".join(f"{int(value)}\n" for value in values).encode("ascii")
    return sha256_bytes(payload)


def build_bridge_receipt(
    case_id: str,
    hfnet_trajectory: Mapping[str, Any],
    score_headers: Mapping[str, Any],
    serialized_ns: Sequence[int],
    mapped_ns: Sequence[int],
    rows: Sequence[Mapping[str, int]],
) -> dict[str, Any]:
    max_delta = max((int(row["absolute_delta_ns"]) for row in rows), default=0)
    require(max_delta <= BRIDGE_MAX_ABSOLUTE_DELTA_NS, "BRIDGE_RECEIPT_DELTA")
    return {
        "schema_version": BRIDGE_SCHEMA,
        "status": "PASS_BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT",
        "case_id": case_id,
        "hfnet_trajectory": dict(hfnet_trajectory),
        "score_camera_headers": dict(score_headers),
        "maximum_allowed_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
        "maximum_observed_absolute_delta_ns": max_delta,
        "mapping_count": len(rows),
        "serialized_epoch_ordered_integer_ns_sha256": ordered_ns_digest(serialized_ns),
        "canonical_header_ordered_integer_ns_sha256": ordered_ns_digest(mapped_ns),
        "mapping": [dict(row) for row in rows],
        "bijective": True,
        "source_header_reuse": False,
        "strictly_monotonic": True,
        "post_bridge_tolerance_ns": 0,
        "support_ape_rpe_or_ranking_computed": False,
    }


def import_evaluator(expected_identity: Mapping[str, Any]) -> tuple[Any, FileSnapshot]:
    observed, _payload = verify_pinned_file(expected_identity, "evaluator_self")
    require(Path(observed.path) == EVALUATOR, "EVALUATOR_NONCANONICAL_PATH")
    module_name = "_aqua_fe_frozen_roster_accuracy_evaluator_v1"
    spec = importlib.util.spec_from_file_location(module_name, observed.path)
    require(spec is not None and spec.loader is not None, "EVALUATOR_IMPORT_SPEC")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    after, _payload_after = snapshot_file(Path(observed.path), "evaluator_self_post_import")
    _assert_same_snapshot(observed, after, "evaluator_self_import")
    return module, observed


@contextlib.contextmanager
def locked_execution_lock(path: Path) -> Iterator[tuple[dict[str, Any], FileSnapshot]]:
    canonical = _canonical_existing_path(path, "execution_lock")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(str(canonical), flags)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ControllerError("EXECUTION_LOCK_BUSY") from error
        snapshot, payload = _snapshot_from_fd(canonical, descriptor)
        try:
            value = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ControllerError("EXECUTION_LOCK_JSON_INVALID") from error
        require(isinstance(value, dict), "EXECUTION_LOCK_ROOT_NOT_OBJECT")
        require(payload == canonical_json_bytes(value), "EXECUTION_LOCK_NOT_CANONICAL_JSON")
        yield value, snapshot
        post, _post_payload = _snapshot_from_fd(canonical, descriptor)
        _assert_same_snapshot(snapshot, post, "execution_lock")
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _case_row(seal: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    require(case_id in CASE_ORDER, f"UNKNOWN_CASE:{case_id}")
    rows = seal.get("cases")
    require(isinstance(rows, list), "SEAL_CASES_NOT_ARRAY")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("case_id") == case_id]
    require(len(matches) == 1, f"SEAL_CASE_ROW_COUNT:{case_id}")
    return matches[0]


def _seal_code_identity(seal: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    identities = seal.get("analysis_code_identities")
    require(isinstance(identities, Mapping), "SEAL_CODE_IDENTITIES_MISSING")
    return _identity_shape(identities.get(label), f"seal_code:{label}")


def prestart_seal_semantic_projection_sha256(seal: Mapping[str, Any]) -> str:
    """Hash the complete seal while breaking only the controller self-cycle."""

    require(isinstance(seal, Mapping), "PRESTART_SEAL_NOT_OBJECT")
    normalized = json.loads(canonical_json_bytes(seal).decode("utf-8"))
    identities = normalized.get("analysis_code_identities")
    require(
        isinstance(identities, dict)
        and set(identities)
        == {"formal_accuracy_controller", "roster_evaluator_core"},
        "PRESTART_SEAL_CODE_IDENTITY_SET",
    )
    identities["formal_accuracy_controller"] = dict(
        PRESTART_SEAL_CONTROLLER_IDENTITY_SENTINEL
    )
    return sha256_bytes(canonical_json_bytes(normalized))


def verify_prestart_seal(
    seal: Mapping[str, Any], seal_snapshot: FileSnapshot, *, require_pristine_destinations: bool
) -> None:
    require(
        seal_snapshot.path == str(DEFAULT_PREFREEZE_SEAL),
        "PRESTART_SEAL_NONCANONICAL_PATH",
    )
    require(
        seal.get("schema_version")
        == "aqua-fe-hfnet-v6-samehistory-positive-accuracy-prefreeze-seal-v1",
        "PRESTART_SEAL_SCHEMA",
    )
    require(
        seal.get("status") == "SEALED_OUTCOME_BLIND_BEFORE_ANY_HFNET_START",
        "PRESTART_SEAL_STATUS",
    )
    require(seal.get("case_order") == list(CASE_ORDER), "PRESTART_SEAL_CASE_ORDER")
    require(
        prestart_seal_semantic_projection_sha256(seal)
        == PRESTART_SEAL_SEMANTIC_PROJECTION_SHA256,
        "PRESTART_SEAL_SEMANTIC_PROJECTION_MISMATCH",
    )
    authorities = seal.get("authorities")
    require(isinstance(authorities, Mapping), "PRESTART_SEAL_AUTHORITIES")
    prefreeze = authorities.get("analysis_grid_prefreeze")
    require(prefreeze == FINAL_PREFREEZE_IDENTITY, "FINAL_PREFREEZE_IDENTITY_MISMATCH")
    verify_pinned_file(FINAL_PREFREEZE_IDENTITY, "final_prefreeze")
    for label, expected in V2_ROSTER_AUTHORITY_IDENTITIES.items():
        require(authorities.get(label) == expected, f"PRESTART_SEAL_NOT_V2_AUTHORITY:{label}")
        verify_pinned_file(expected, f"v2_authority:{label}")
    controller_expected = _seal_code_identity(seal, "formal_accuracy_controller")
    evaluator_expected = _seal_code_identity(seal, "roster_evaluator_core")
    controller_observed, _ = snapshot_file(CONTROLLER, "controller_self")
    require(controller_observed.identity == dict(controller_expected), "CONTROLLER_SELF_IDENTITY_MISMATCH")
    evaluator_observed, _ = snapshot_file(EVALUATOR, "evaluator_self")
    require(evaluator_observed.identity == dict(evaluator_expected), "EVALUATOR_SELF_IDENTITY_MISMATCH")
    claims = seal.get("claims")
    require(
        isinstance(claims, Mapping)
        and claims.get("accuracy_analysis_started") is False
        and claims.get("accuracy_measured") is False
        and claims.get("winner_or_ranking_authorized") is False,
        "PRESTART_SEAL_CLAIMS_NOT_PRISTINE",
    )
    require(
        seal_snapshot.identity["sha256"] == sha256_bytes(canonical_json_bytes(seal)),
        "PRESTART_SEAL_VALUE_IDENTITY_MISMATCH",
    )
    if require_pristine_destinations:
        namespace = seal.get("future_accuracy_namespace")
        require(isinstance(namespace, Mapping), "SEAL_ACCURACY_NAMESPACE")
        require(namespace.get("maximum_attempts_per_case") == 1, "SEAL_MAXIMUM_ATTEMPTS")
        require(namespace.get("retry_permitted") is False, "SEAL_RETRY_POLICY")
        require(namespace.get("replacement_output_permitted") is False, "SEAL_REPLACEMENT_POLICY")


def _identity_from_historical_source(source: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    if label == "reference":
        return _identity_shape(source.get("trajectory_or_container"), "historical_reference")
    return _identity_shape(source.get("trajectory"), f"historical_{label}")


def _historical_identity_entries(
    row: Mapping[str, Any]
) -> list[tuple[str, Mapping[str, Any]]]:
    historical = row.get("historical_sources")
    require(isinstance(historical, Mapping), "SEAL_HISTORICAL_SOURCES")
    entries: list[tuple[str, Mapping[str, Any]]] = [
        (
            "reference",
            _identity_shape(
                historical.get("reference", {}).get("trajectory_or_container"),
                "historical_reference",
            ),
        )
    ]
    for name in ("learned_plus_klt", "klt"):
        source = historical.get(name)
        require(isinstance(source, Mapping), f"SEAL_HISTORICAL_SOURCE:{name}")
        if "trajectory" in source:
            entries.append(
                (name, _identity_shape(source["trajectory"], f"historical_{name}"))
            )
            continue
        candidates = source.get("trajectory_candidates")
        require(isinstance(candidates, list) and candidates, f"HISTORICAL_CANDIDATES:{name}")
        for candidate in candidates:
            require(isinstance(candidate, Mapping), f"HISTORICAL_CANDIDATE_OBJECT:{name}")
            repeat = candidate.get("repeat")
            identity = _identity_shape(
                candidate.get("identity"), f"historical_{name}_repeat_{repeat}"
            )
            entries.append((f"{name}:repeat_{repeat}", identity))
        entries.append(
            (
                f"{name}:repeat_manifest",
                _identity_shape(
                    source.get("repeat_manifest"), f"historical_{name}_repeat_manifest"
                ),
            )
        )
    return entries


def _structural_input_lock(
    row: Mapping[str, Any],
    hfnet_trajectory_identity: Mapping[str, Any],
    bridge_identity: Mapping[str, Any],
) -> dict[str, Any]:
    historical = row.get("historical_sources")
    require(isinstance(historical, Mapping), "STRUCTURAL_HISTORICAL_SOURCES")
    return {
        "status": "PREFROZEN_THREE_SOURCE_UPPER_BOUND_NO_COORDINATE_LOAD",
        "structural_na_reasons": list(row.get("structural_na_reasons") or []),
        "hfnet": {
            "trajectory": dict(hfnet_trajectory_identity),
            "format": "HFNET_QXYZW_FLOAT_EPOCH",
            "timestamp_bridge_receipt": dict(bridge_identity),
        },
        "historical_sources": json.loads(
            canonical_json_bytes(historical).decode("utf-8")
        ),
        "coordinate_loading_permitted": False,
        "support_computation_permitted": False,
    }


def _matrix_inverse_rigid(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    require(len(matrix) == 4 and all(len(row) == 4 for row in matrix), "RIGID_MATRIX_SHAPE")
    values = [[float(value) for value in row] for row in matrix]
    rotation = [row[:3] for row in values[:3]]
    translation = [values[index][3] for index in range(3)]
    transpose = [[rotation[column][row] for column in range(3)] for row in range(3)]
    inverse_translation = [
        -sum(transpose[row][column] * translation[column] for column in range(3))
        for row in range(3)
    ]
    return [
        transpose[row] + [inverse_translation[row]] for row in range(3)
    ] + [[0.0, 0.0, 0.0, 1.0]]


def _matrix_binding(evaluator: Any, matrix: Sequence[Sequence[float]]) -> dict[str, Any]:
    import numpy as np

    values = np.asarray(matrix, dtype=float)
    return {
        "matrix": values.tolist(),
        "matrix_sha256": evaluator.static_matrix_sha256(values),
    }


def _frame_lock_contract(
    seal: Mapping[str, Any], row: Mapping[str, Any], evaluator: Any
) -> tuple[dict[str, Any], list[list[float]]]:
    dataset = str(row.get("dataset"))
    semantics = evaluator.DATASET_FRAME_CONTRACTS.get(dataset)
    require(isinstance(semantics, Mapping), f"DATASET_FRAME_CONTRACT_MISSING:{dataset}")
    global_contract = seal.get("analysis_contract")
    require(isinstance(global_contract, Mapping), "SEAL_ANALYSIS_CONTRACT")
    sealed_frames = global_contract.get("frame_contract")
    require(isinstance(sealed_frames, Mapping), "SEAL_FRAME_CONTRACT")
    dataset_frame = sealed_frames.get(dataset)
    require(isinstance(dataset_frame, Mapping), f"SEAL_DATASET_FRAME_CONTRACT:{dataset}")
    result: dict[str, Any] = {
        "dataset": dataset,
        "semantic_contract": dict(semantics),
        "common_target_frame": semantics["common_target_frame"],
        "per_source_pose_semantics_frozen": True,
        "static_transform_direction_tested": True,
        "interpolation_before_static_extrinsic": True,
        "target_before_alignment_fit": True,
    }
    estimate_matrix: list[list[float]] = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    if dataset == "AQUALOC_ARCHAEOLOGY":
        imu = dataset_frame.get("imu_T_camera")
        require(isinstance(imu, Mapping) and isinstance(imu.get("matrix"), list), "SEAL_AQUALOC_IMU_T_CAMERA")
        estimate_matrix = [[float(value) for value in values] for values in imu["matrix"]]
        inverse = _matrix_inverse_rigid(estimate_matrix)
        result.update(
            {
                "imu_T_camera": _matrix_binding(evaluator, estimate_matrix),
                "camera_T_imu": _matrix_binding(evaluator, inverse),
                "calibration_authority": dict(dataset_frame["calibration_authority"]),
                "inverse_forbidden_as_estimate_bridge": True,
            }
        )
    elif dataset == "CIRS":
        imu_vehicle = dataset_frame.get("imu_T_vehicle")
        vehicle_imu = dataset_frame.get("vehicle_T_imu")
        require(
            isinstance(imu_vehicle, Mapping)
            and isinstance(imu_vehicle.get("matrix"), list)
            and isinstance(vehicle_imu, Mapping)
            and isinstance(vehicle_imu.get("matrix"), list),
            "SEAL_CIRS_STATIC_MATRICES",
        )
        estimate_matrix = [
            [float(value) for value in values] for values in imu_vehicle["matrix"]
        ]
        result.update(
            {
                "imu_T_vehicle": _matrix_binding(evaluator, estimate_matrix),
                "vehicle_T_imu": _matrix_binding(evaluator, vehicle_imu["matrix"]),
                "published_common_vehicle_body_verified": True,
                "camera_transform_used_as_body_transform": False,
                "calibration_representation": "FULL_PRECISION_ORIGINAL_TF_PRIMARY",
                "canonical_zero_snapping": "DISPLAY_ONLY_NOT_NUMERIC",
                "original_quaternion_sealed": True,
                "historical_online_camera_extrinsic_ignored_for_body_bridge": True,
                "evidence_sha256": dict(dataset_frame["evidence_sha256"]),
            }
        )
    else:
        result.update(
            {
                "published_common_vehicle_body_verified": False,
                "camera_transform_used_as_body_transform": False,
            }
        )
    return result, estimate_matrix


def _source_lock_rows(
    seal: Mapping[str, Any],
    seal_snapshot: FileSnapshot,
    row: Mapping[str, Any],
    runability_receipt_identity: Mapping[str, Any],
    hfnet_trajectory_identity: Mapping[str, Any],
    bridge_identity: Mapping[str, Any],
    evaluator: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    historical = row.get("historical_sources")
    require(isinstance(historical, Mapping), "SEAL_HISTORICAL_SOURCES")
    frame_contract, estimate_matrix = _frame_lock_contract(seal, row, evaluator)
    semantics = frame_contract["semantic_contract"]
    sources: dict[str, Any] = {}
    for name in SOURCE_ORDER:
        if name == "hfnet":
            trajectory = dict(hfnet_trajectory_identity)
            format_name = "HFNET_QXYZW_FLOAT_EPOCH"
            topic = None
        elif name == "reference":
            source = historical["reference"]
            trajectory = dict(_identity_from_historical_source(source, name))
            format_name = source.get("format")
            topic = source.get("topic")
        else:
            source = historical[name]
            require(source.get("authorized_as_future_metric_input") is True, f"HISTORICAL_SOURCE_NOT_AUTHORIZED:{name}")
            trajectory = dict(_identity_from_historical_source(source, name))
            format_name = "VINS_QWXYZ_CSV"
            topic = None
        timestamp_contract: dict[str, Any] = {
            "unit": "integer_nanoseconds",
            "offset_ns": 0,
            "nearest_association": False,
            "extrapolation": False,
        }
        if name == "hfnet":
            timestamp_contract.update(
                {
                    "stock_epoch_bridge_max_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
                    "bridge_mapping": "BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT",
                    "source_header_reuse": False,
                    "bridge_receipt": dict(bridge_identity),
                }
            )
        is_reference = name == "reference"
        static_matrix = (
            [[1.0 if row_index == column else 0.0 for column in range(4)] for row_index in range(4)]
            if is_reference
            else estimate_matrix
        )
        source_frame = (
            semantics["reference_source_frame"]
            if is_reference
            else semantics["estimate_source_frame"]
        )
        target_frame = semantics["common_target_frame"]
        sources[name] = {
            "trajectory": trajectory,
            "format": format_name,
            "topic": topic,
            "timestamp_contract": timestamp_contract,
            "pose_convention": {
                "serialized": "world_T_source",
                "analysis": "world_T_target",
                "serialized_quaternion_order": (
                    "wxyz" if name in ("learned_plus_klt", "klt") else "xyzw"
                ),
                "analysis_quaternion_order": "xyzw",
                "quaternion_conversion": (
                    "LOSSLESS_PERMUTATION_WXYZ_TO_XYZW"
                    if name in ("learned_plus_klt", "klt")
                    else "IDENTITY_LOSSLESS"
                ),
                "static_transform": {
                    "identity": seal_snapshot.identity,
                    "source_frame": source_frame,
                    "target_frame": target_frame,
                    "source_T_target": static_matrix,
                    "convention": "source_T_target",
                    "semantic": (
                        semantics["reference_transform"]
                        if is_reference
                        else semantics["estimate_transform"]
                    ),
                },
            },
        }
    return sources, frame_contract


def _future_publication_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    future = row.get("future_accuracy_publication")
    require(isinstance(future, Mapping), "SEAL_CASE_FUTURE_PUBLICATION")
    result = {
        label: str(_canonical_future_path(Path(str(future[label])), f"future:{label}"))
        for label in ("output_dir", "process_claim", "terminal_receipt")
    }
    require(future.get("retry_permitted") is False, "FUTURE_RETRY_PERMITTED")
    require(future.get("replacement_output_permitted") is False, "FUTURE_REPLACEMENT_PERMITTED")
    require(future.get("maximum_claims") == 1, "FUTURE_MAXIMUM_CLAIMS")
    return {
        **result,
        "retry_permitted": False,
        "replacement_output_permitted": False,
        "maximum_claims": 1,
    }


def _evo_lock_contract(seal: Mapping[str, Any], seal_snapshot: FileSnapshot, evaluator: Any) -> dict[str, Any]:
    environment = seal.get("evo_environment")
    require(isinstance(environment, Mapping), "SEAL_EVO_ENVIRONMENT")
    require(environment.get("evo_ape") == dict(evaluator.EVO_APE_IDENTITY), "SEAL_EVO_APE_IDENTITY")
    require(environment.get("evo_rpe") == dict(evaluator.EVO_RPE_IDENTITY), "SEAL_EVO_RPE_IDENTITY")
    return {
        "evo_ape": dict(evaluator.EVO_APE_IDENTITY),
        "evo_rpe": dict(evaluator.EVO_RPE_IDENTITY),
        "environment_seal": seal_snapshot.identity,
        "environment_contract": dict(evaluator.EVO_ENVIRONMENT_CONTRACT),
        "version": evaluator.EVO_VERSION,
        "alignment": "OWN_GLOBAL_SE3_-a_FIXED_SCALE_1",
        "use_scale": False,
        "scale_flag": None,
        "timestamp_basis": "relative_zero_from_authoritative_integer_ns",
        "population_binding": "COUNT_AND_ORDERED_INTEGER_NS_LIST_SHA256",
        "maximum_absolute_rmse_disagreement_m": EVO_MAX_RMSE_DISAGREEMENT_M,
    }


def _native_sensitivity_lock(row: Mapping[str, Any]) -> dict[str, Any]:
    policy = row.get("native_reference_sensitivity")
    require(isinstance(policy, Mapping), "SEAL_NATIVE_SENSITIVITY")
    historical = row.get("historical_sources")
    require(isinstance(historical, Mapping), "SEAL_HISTORICAL_FOR_SENSITIVITY")
    reference = historical.get("reference")
    require(isinstance(reference, Mapping), "SEAL_REFERENCE_FOR_SENSITIVITY")
    result = {
        "required": policy.get("required") is True,
        "descriptive_only": policy.get("descriptive_only") is True,
        "run_only_after_primary_gate": policy.get("run_only_after_primary_gate") is True,
        "can_reopen_primary_gate": False,
        "expected_native_anchor_count": policy.get("expected_native_anchor_count"),
    }
    if result["required"]:
        result["native_reference"] = dict(
            _identity_shape(reference.get("trajectory_or_container"), "native_reference")
        )
    return result


def _score_headers(row: Mapping[str, Any]) -> tuple[list[int], Mapping[str, Any], FileSnapshot]:
    score = row.get("score_camera_headers")
    require(isinstance(score, Mapping), "SEAL_SCORE_HEADERS")
    identity = _identity_shape(score.get("identity"), "score_headers")
    snapshot, payload = verify_pinned_file(identity, "score_headers")
    try:
        lines = payload.decode("ascii").splitlines()
        values = [int(line) for line in lines if line.strip()]
    except (UnicodeError, ValueError) as error:
        raise ControllerError("SCORE_HEADERS_PARSE") from error
    canonical = "".join(f"{value}\n" for value in values).encode("ascii")
    require(canonical == payload, "SCORE_HEADERS_NOT_CANONICAL")
    values = _validate_strict_timestamps(values, "score_headers")
    require(len(values) == score.get("count"), "SCORE_HEADER_COUNT")
    require([values[0], values[-1]] == score.get("first_last_ns_inclusive"), "SCORE_HEADER_BOUNDARY")
    require(ordered_ns_digest(values) == score.get("ordered_integer_ns_ascii_lf_sha256"), "SCORE_HEADER_DIGEST")
    return values, identity, snapshot


def _runability_status(receipt: Mapping[str, Any], case_id: str) -> str:
    require(receipt.get("case_id") == case_id, "RUNABILITY_CASE_ID")
    status = receipt.get("status")
    if status in ("PASS", "PASS_SAMEHISTORY_COLDSTART_RUNABILITY"):
        normalized = "PASS"
    elif status in ("FAIL", "FAIL_SAMEHISTORY_COLDSTART_RUNABILITY"):
        normalized = "FAIL"
    else:
        raise ControllerError("RUNABILITY_STATUS_UNKNOWN")
    terminal = receipt.get("terminal_contract")
    require(
        isinstance(terminal, Mapping)
        and terminal.get("attempt_consumed") is True
        and terminal.get("retry_after_pass_or_fail") is False,
        "RUNABILITY_NOT_TERMINAL",
    )
    return normalized


def _hfnet_terminal_paths(row: Mapping[str, Any]) -> tuple[Path, Path]:
    future = row.get("future_hfnet_outputs_observed_absent")
    require(isinstance(future, Mapping), "SEAL_FUTURE_HFNET_PATHS")
    receipt = _canonical_existing_path(Path(str(future["terminal_runability_result"])), "hfnet_terminal")
    trajectory = _canonical_existing_path(Path(str(future["trajectory"])), "hfnet_trajectory")
    return receipt, trajectory


def execution_lock_paths(seal: Mapping[str, Any], case_id: str) -> tuple[Path, Path]:
    # The v2 seal may expose the namespace explicitly.  Deriving it from the
    # sealed future accuracy root is the backward-compatible equivalent and
    # avoids a controller-source/seal hash cycle.
    explicit = seal.get("future_accuracy_execution_lock_namespace")
    if isinstance(explicit, Mapping):
        lock_pattern = explicit.get("case_lock_pattern")
        bridge_pattern = explicit.get("case_bridge_receipt_pattern")
        require(isinstance(lock_pattern, str) and isinstance(bridge_pattern, str), "LOCK_NAMESPACE_PATTERNS")
        return (
            _canonical_future_path(Path(lock_pattern.format(case_id=case_id)), "execution_lock_output"),
            _canonical_future_path(Path(bridge_pattern.format(case_id=case_id)), "bridge_output"),
        )
    controller_contract = seal.get("future_accuracy_controller_contract")
    if isinstance(controller_contract, Mapping):
        freeze_contract = controller_contract.get("freeze_lock")
        if isinstance(freeze_contract, Mapping):
            lock_pattern = freeze_contract.get("canonical_execution_lock_pattern")
            bridge_pattern = freeze_contract.get("canonical_bridge_receipt_pattern")
            require(
                isinstance(lock_pattern, str) and isinstance(bridge_pattern, str),
                "SEALED_FREEZE_LOCK_PATTERNS",
            )
            return (
                _canonical_future_path(
                    Path(lock_pattern.format(case_id=case_id)), "execution_lock_output"
                ),
                _canonical_future_path(
                    Path(bridge_pattern.format(case_id=case_id)), "bridge_output"
                ),
            )
    namespace = seal.get("future_accuracy_namespace")
    require(isinstance(namespace, Mapping), "SEAL_FUTURE_ACCURACY_NAMESPACE")
    accuracy_root = Path(str(namespace.get("root")))
    root = _canonical_future_path(
        accuracy_root.parent / "_accuracy_execution_locks_v1", "derived_execution_lock_root"
    )
    return root / f"{case_id}.json", root / f"{case_id}.hfnet_timestamp_bridge_receipt.json"


def build_execution_lock(
    *,
    seal: Mapping[str, Any],
    seal_snapshot: FileSnapshot,
    row: Mapping[str, Any],
    evaluator: Any,
    runability_receipt_identity: Mapping[str, Any],
    hfnet_trajectory_identity: Mapping[str, Any],
    bridge_identity: Mapping[str, Any],
    score_headers_identity: Mapping[str, Any],
) -> dict[str, Any]:
    case_id = str(row["case_id"])
    structural = bool(row.get("structural_na_reasons"))
    frame_contract, _estimate_matrix = _frame_lock_contract(seal, row, evaluator)
    if structural:
        sources: dict[str, Any] = {}
        structural_inputs: Mapping[str, Any] | None = _structural_input_lock(
            row, hfnet_trajectory_identity, bridge_identity
        )
    else:
        sources, frame_contract = _source_lock_rows(
            seal,
            seal_snapshot,
            row,
            runability_receipt_identity,
            hfnet_trajectory_identity,
            bridge_identity,
            evaluator,
        )
        structural_inputs = None
    controller_identity = _seal_code_identity(seal, "formal_accuracy_controller")
    evaluator_identity = _seal_code_identity(seal, "roster_evaluator_core")
    result = {
        "schema_version": evaluator.ANALYSIS_LOCK_SCHEMA,
        "status": "LOCKED_BEFORE_ACCURACY",
        "case_id": case_id,
        "authority_hashes": dict(evaluator.FROZEN_AUTHORITY_HASHES),
        "v2_roster_authorities": json.loads(
            canonical_json_bytes(dict(evaluator.V2_ROSTER_AUTHORITY_IDENTITIES)).decode(
                "utf-8"
            )
        ),
        "analysis_grid_prefreeze": dict(evaluator.ANALYSIS_GRID_PREFREEZE_IDENTITY),
        "imported_pure_helpers": {
            "trajectory_eval_core": dict(evaluator.PURE_HELPER_IDENTITY)
        },
        "claims": {"analysis_started": False, "accuracy_measured": False},
        "controller": dict(controller_identity),
        "evaluator": dict(evaluator_identity),
        "prestart_seal": seal_snapshot.identity,
        "hfnet_runability_receipt": {
            "identity": dict(runability_receipt_identity),
            "status": "PASS",
        },
        "score_camera_headers": dict(score_headers_identity),
        "frame_convention_seal": seal_snapshot.identity,
        "frame_contract": frame_contract,
        "sources": sources,
        "evo_verification": _evo_lock_contract(seal, seal_snapshot, evaluator),
        "native_anchor_sensitivity": _native_sensitivity_lock(row),
        "publication": _future_publication_from_row(row),
        "controller_contract": {
            "authorization_token_sha256": AUTHORIZATION_TOKEN_SHA256,
            "bridge_max_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
            "canonical_paths_required": True,
            "identity_pre_and_post_hash_stat_required": True,
            "exactly_once_claim": True,
            "retry_permitted": False,
            "closed_gate_coordinate_load_forbidden": True,
            "evo_pass_before_accuracy_or_ranking_authorization": True,
            "fuse_publication": "TEMP_O_EXCL_FSYNC_HARDLINK_NOREPLACE_DIRECTORY_FSYNC_NO_RENAME",
        },
    }
    if structural_inputs is not None:
        result["structural_inputs"] = structural_inputs
    return result


def freeze_lock(case_id: str, prestart_seal_path: Path) -> dict[str, Any]:
    """Freeze one PASS runability outcome without computing support or metrics."""

    seal, seal_snapshot = read_canonical_json_path(prestart_seal_path, "prestart_seal")
    verify_prestart_seal(seal, seal_snapshot, require_pristine_destinations=False)
    row = _case_row(seal, case_id)
    lock_path, bridge_path = execution_lock_paths(seal, case_id)
    destinations = require_distinct_canonical_paths(
        {"execution_lock": lock_path, "bridge_receipt": bridge_path}
    )
    for label, path in destinations.items():
        _destination_absent(path, label)
    formal_destinations = require_distinct_canonical_paths(
        {
            label: Path(str(value))
            for label, value in _future_publication_from_row(row).items()
            if label in ("output_dir", "process_claim", "terminal_receipt")
        }
    )
    for label, path in formal_destinations.items():
        _destination_absent(path, f"formal_accuracy:{label}")
    receipt_path, trajectory_path = _hfnet_terminal_paths(row)
    receipt, receipt_snapshot = read_canonical_json_path(receipt_path, "hfnet_runability_receipt")
    require(_runability_status(receipt, case_id) == "PASS", "FREEZE_LOCK_REQUIRES_RUNABILITY_PASS")
    trajectory_snapshot, trajectory_payload = snapshot_file(trajectory_path, "hfnet_trajectory")
    pinned_trajectory = receipt.get("support", {}).get("trajectory", {}).get("identity")
    require(
        isinstance(pinned_trajectory, Mapping)
        and trajectory_snapshot.identity == dict(pinned_trajectory),
        "RUNABILITY_TRAJECTORY_IDENTITY_MISMATCH",
    )
    headers, headers_identity, headers_snapshot = _score_headers(row)
    serialized, _positions, _quaternions = parse_ascii_pose_rows(
        trajectory_payload,
        format_name="HFNET_QXYZW_FLOAT_EPOCH",
        label="hfnet_freeze",
        timestamps_only=True,
    )
    mapped, mappings = bridge_hfnet_timestamps(serialized, headers)
    bridge = build_bridge_receipt(
        case_id,
        trajectory_snapshot.identity,
        headers_identity,
        serialized,
        mapped,
        mappings,
    )
    evaluator, evaluator_snapshot = import_evaluator(
        _seal_code_identity(seal, "roster_evaluator_core")
    )
    controller_snapshot, _ = verify_pinned_file(
        _seal_code_identity(seal, "formal_accuracy_controller"), "controller_self"
    )
    ledger = IdentityLedger()
    for label, value in (
        ("prestart_seal", seal_snapshot),
        ("runability_receipt", receipt_snapshot),
        ("hfnet_trajectory", trajectory_snapshot),
        ("score_headers", headers_snapshot),
        ("controller", controller_snapshot),
        ("evaluator", evaluator_snapshot),
    ):
        ledger.add(label, value)
    # Historical identities are verified but their coordinate contents remain unopened.
    historical = row.get("historical_sources")
    require(isinstance(historical, Mapping), "SEAL_HISTORICAL_SOURCES")
    for name, identity in _historical_identity_entries(row):
        observed, _ = verify_pinned_file(identity, f"historical:{name}")
        ledger.add(f"historical:{name}", observed)
    ledger.verify_all()
    _mkdir_plain(bridge_path.parent)
    bridge_snapshot = atomic_publish_noreplace(bridge_path, canonical_json_bytes(bridge))
    lock = build_execution_lock(
        seal=seal,
        seal_snapshot=seal_snapshot,
        row=row,
        evaluator=evaluator,
        runability_receipt_identity=receipt_snapshot.identity,
        hfnet_trajectory_identity=trajectory_snapshot.identity,
        bridge_identity=bridge_snapshot.identity,
        score_headers_identity=headers_identity,
    )
    # Re-verify again immediately before the lock becomes the authorization boundary.
    ledger.verify_all()
    lock_snapshot = atomic_publish_noreplace(lock_path, canonical_json_bytes(lock))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "FROZEN_EXECUTION_LOCK_PUBLISHED_PRE_METRIC",
        "case_id": case_id,
        "prestart_seal": seal_snapshot.identity,
        "bridge_receipt": bridge_snapshot.identity,
        "execution_lock": lock_snapshot.identity,
        "bridge_max_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
        "support_computed": False,
        "ape_computed": False,
        "rpe_computed": False,
        "ranking_computed": False,
    }


def _verify_evo_tree(environment: Mapping[str, Any], ledger: IdentityLedger) -> dict[str, Any]:
    tree = environment.get("evo_implementation_tree")
    require(isinstance(tree, Mapping), "EVO_IMPLEMENTATION_TREE_MISSING")
    root = _canonical_existing_path(Path(str(tree.get("site_packages_root"))), "evo_site_packages")
    included = tree.get("included_roots")
    require(isinstance(included, list) and included, "EVO_INCLUDED_ROOTS")
    excluded = tree.get("excluded_path_component")
    require(excluded == "__pycache__", "EVO_TREE_EXCLUSION")
    files: list[Path] = []
    for relative in included:
        require(isinstance(relative, str) and relative, "EVO_INCLUDED_ROOT_NAME")
        subtree = _canonical_existing_path(root / relative, f"evo_tree_root:{relative}")
        require(subtree.is_dir() and not subtree.is_symlink(), f"EVO_TREE_ROOT_INVALID:{relative}")
        for path in subtree.rglob("*"):
            if excluded in path.relative_to(root).parts:
                continue
            metadata = os.lstat(str(path))
            require(not stat.S_ISLNK(metadata.st_mode), f"EVO_TREE_SYMLINK:{path}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            require(stat.S_ISREG(metadata.st_mode), f"EVO_TREE_SPECIAL:{path}")
            files.append(path)
    files.sort(key=lambda path: path.relative_to(root).as_posix())
    digest = hashlib.sha256()
    total = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        observed, _ = snapshot_file(path, f"evo_tree:{relative}")
        ledger.add(f"evo_tree:{relative}", observed)
        digest.update(
            f"{relative}\0{observed.size_bytes}\0{observed.sha256}\n".encode("ascii")
        )
        total += observed.size_bytes
    observed_tree = {
        "file_count": len(files),
        "total_bytes": total,
        "tree_sha256": digest.hexdigest(),
    }
    require(
        all(observed_tree[key] == tree.get(key) for key in observed_tree),
        "EVO_IMPLEMENTATION_TREE_IDENTITY_MISMATCH",
    )
    return observed_tree


def _verify_evo_inputs(
    seal: Mapping[str, Any], lock: Mapping[str, Any], ledger: IdentityLedger
) -> dict[str, Any]:
    environment = seal.get("evo_environment")
    require(isinstance(environment, Mapping), "SEAL_EVO_ENVIRONMENT")
    evo_lock = lock.get("evo_verification")
    require(isinstance(evo_lock, Mapping), "LOCK_EVO_VERIFICATION")
    direct_keys = (
        "evo_ape",
        "evo_rpe",
        "python_executable",
        "evo_distribution_record",
    )
    observed: dict[str, Any] = {}
    for key in direct_keys:
        identity = _identity_shape(environment.get(key), f"evo:{key}")
        snapshot, _ = verify_pinned_file(identity, f"evo:{key}")
        ledger.add(f"evo:{key}", snapshot)
        observed[key] = snapshot.identity
    for package in ("numpy", "scipy"):
        package_value = environment.get(package)
        require(isinstance(package_value, Mapping), f"EVO_PACKAGE:{package}")
        identity = _identity_shape(
            package_value.get("distribution_record"), f"evo:{package}:record"
        )
        snapshot, _ = verify_pinned_file(identity, f"evo:{package}:record")
        ledger.add(f"evo:{package}:record", snapshot)
        observed[f"{package}_record"] = snapshot.identity
    require(evo_lock.get("evo_ape") == observed["evo_ape"], "LOCK_EVO_APE_SEAL_MISMATCH")
    require(evo_lock.get("evo_rpe") == observed["evo_rpe"], "LOCK_EVO_RPE_SEAL_MISMATCH")
    observed["implementation_tree"] = _verify_evo_tree(environment, ledger)
    return observed


def _verify_input_aliases(ledger: IdentityLedger) -> None:
    by_path: dict[str, FileSnapshot] = {}
    by_inode: dict[tuple[int, int], str] = {}
    for label, value in ledger._values.items():
        existing = by_path.get(value.path)
        if existing is not None:
            require(existing.identity == value.identity, f"INPUT_PATH_IDENTITY_CONFLICT:{label}")
            continue
        by_path[value.path] = value
        inode = (value.st_dev, value.st_ino)
        owner = by_inode.setdefault(inode, value.path)
        require(owner == value.path, f"INPUT_HARDLINK_ALIAS:{owner}:{value.path}")


@dataclass
class VerifiedContext:
    case_id: str
    execution_lock: Mapping[str, Any]
    execution_lock_snapshot: FileSnapshot
    seal: Mapping[str, Any]
    seal_snapshot: FileSnapshot
    row: Mapping[str, Any]
    evaluator: Any
    evaluator_snapshot: FileSnapshot
    controller_snapshot: FileSnapshot
    ledger: IdentityLedger
    destinations: Mapping[str, Path]
    runability_receipt: Mapping[str, Any]
    bridge_receipt: Mapping[str, Any]


def verify_execution_context(
    case_id: str,
    execution_lock: Mapping[str, Any],
    execution_lock_snapshot: FileSnapshot,
    *,
    require_destinations_absent: bool,
) -> VerifiedContext:
    require(execution_lock.get("case_id") == case_id, "LOCK_CASE_ID_MISMATCH")
    require(execution_lock.get("status") == "LOCKED_BEFORE_ACCURACY", "LOCK_STATUS")
    controller_contract = execution_lock.get("controller_contract")
    require(isinstance(controller_contract, Mapping), "LOCK_CONTROLLER_CONTRACT")
    require(
        controller_contract.get("authorization_token_sha256") == AUTHORIZATION_TOKEN_SHA256,
        "LOCK_AUTHORIZATION_TOKEN_DIGEST",
    )
    require(
        controller_contract.get("bridge_max_absolute_delta_ns")
        == BRIDGE_MAX_ABSOLUTE_DELTA_NS,
        "LOCK_BRIDGE_NOT_256NS",
    )
    require(controller_contract.get("exactly_once_claim") is True, "LOCK_EXACTLY_ONCE")
    require(controller_contract.get("retry_permitted") is False, "LOCK_RETRY_POLICY")

    seal_identity = _identity_shape(execution_lock.get("prestart_seal"), "lock_prestart_seal")
    seal, seal_snapshot = read_canonical_json_identity(seal_identity, "prestart_seal")
    verify_prestart_seal(seal, seal_snapshot, require_pristine_destinations=False)
    row = _case_row(seal, case_id)
    canonical_lock_path, canonical_bridge_path = execution_lock_paths(seal, case_id)
    require(
        execution_lock_snapshot.path == str(canonical_lock_path),
        "EXECUTION_LOCK_NONCANONICAL_CASE_PATH",
    )
    controller_identity = _identity_shape(execution_lock.get("controller"), "lock_controller")
    require(
        dict(controller_identity) == dict(_seal_code_identity(seal, "formal_accuracy_controller")),
        "LOCK_CONTROLLER_SEAL_MISMATCH",
    )
    controller_snapshot, _ = verify_pinned_file(controller_identity, "controller_self")
    require(controller_snapshot.path == str(CONTROLLER), "CONTROLLER_PATH_MISMATCH")
    evaluator_identity = _identity_shape(execution_lock.get("evaluator"), "lock_evaluator")
    require(
        dict(evaluator_identity) == dict(_seal_code_identity(seal, "roster_evaluator_core")),
        "LOCK_EVALUATOR_SEAL_MISMATCH",
    )
    evaluator, evaluator_snapshot = import_evaluator(evaluator_identity)

    require(
        execution_lock.get("schema_version") == evaluator.ANALYSIS_LOCK_SCHEMA,
        "LOCK_EVALUATOR_SCHEMA_MISMATCH",
    )
    require(
        execution_lock.get("analysis_grid_prefreeze") == FINAL_PREFREEZE_IDENTITY,
        "LOCK_FINAL_PREFREEZE_MISMATCH",
    )
    require(
        execution_lock.get("frame_convention_seal") == seal_snapshot.identity,
        "FRAME_CONVENTION_SEAL_IDENTITY",
    )
    require(
        execution_lock.get("publication") == _future_publication_from_row(row),
        "LOCK_PUBLICATION_SEAL_MISMATCH",
    )
    publication = execution_lock["publication"]
    destinations = require_distinct_canonical_paths(
        {
            "output_dir": Path(str(publication["output_dir"])),
            "process_claim": Path(str(publication["process_claim"])),
            "terminal_receipt": Path(str(publication["terminal_receipt"])),
        }
    )
    if require_destinations_absent:
        for label, path in destinations.items():
            _destination_absent(path, label)

    ledger = IdentityLedger()
    ledger.add("execution_lock", execution_lock_snapshot)
    ledger.add("prestart_seal", seal_snapshot)
    ledger.add("controller", controller_snapshot)
    ledger.add("evaluator", evaluator_snapshot)

    receipt_lock = execution_lock.get("hfnet_runability_receipt")
    require(isinstance(receipt_lock, Mapping), "LOCK_RUNABILITY_RECEIPT")
    receipt_identity = _identity_shape(receipt_lock.get("identity"), "runability_receipt")
    receipt, receipt_snapshot = read_canonical_json_identity(
        receipt_identity, "runability_receipt"
    )
    status = _runability_status(receipt, case_id)
    require(status == receipt_lock.get("status"), "RUNABILITY_STATUS_LOCK_MISMATCH")
    require(status == "PASS", "FORMAL_ACCURACY_LOCK_REQUIRES_PASS")
    ledger.add("runability_receipt", receipt_snapshot)

    score_identity = _identity_shape(execution_lock.get("score_camera_headers"), "lock_score_headers")
    headers, sealed_score_identity, score_snapshot = _score_headers(row)
    require(dict(score_identity) == dict(sealed_score_identity), "LOCK_SCORE_HEADERS_SEAL_MISMATCH")
    ledger.add("score_headers", score_snapshot)

    structural = bool(row.get("structural_na_reasons"))
    sources = execution_lock.get("sources")
    trajectory_payloads: dict[str, bytes] = {}
    if structural:
        require(sources == {}, "STRUCTURAL_LOCK_SOURCES_MUST_BE_EMPTY")
        structural_inputs = execution_lock.get("structural_inputs")
        require(isinstance(structural_inputs, Mapping), "STRUCTURAL_INPUTS_MISSING")
        expected_structural = _structural_input_lock(
            row,
            structural_inputs.get("hfnet", {}).get("trajectory", {}),
            structural_inputs.get("hfnet", {}).get("timestamp_bridge_receipt", {}),
        )
        require(structural_inputs == expected_structural, "STRUCTURAL_INPUTS_NOT_CANONICAL")
        hfnet_identity = _identity_shape(
            structural_inputs["hfnet"]["trajectory"], "structural_hfnet_trajectory"
        )
        hfnet_snapshot, hfnet_payload = verify_pinned_file(
            hfnet_identity, "trajectory:hfnet"
        )
        ledger.add("trajectory:hfnet", hfnet_snapshot)
        trajectory_payloads["hfnet"] = hfnet_payload
        for name, identity in _historical_identity_entries(row):
            snapshot, _payload = verify_pinned_file(identity, f"structural:{name}")
            ledger.add(f"structural:{name}", snapshot)
        bridge_value = structural_inputs["hfnet"]["timestamp_bridge_receipt"]
    else:
        require(
            isinstance(sources, Mapping) and set(sources) == set(SOURCE_ORDER),
            "LOCK_SOURCE_SET",
        )
        for name in SOURCE_ORDER:
            source = sources[name]
            require(isinstance(source, Mapping), f"LOCK_SOURCE_OBJECT:{name}")
            identity = _identity_shape(source.get("trajectory"), f"trajectory:{name}")
            snapshot, payload = verify_pinned_file(identity, f"trajectory:{name}")
            ledger.add(f"trajectory:{name}", snapshot)
            trajectory_payloads[name] = payload
            pose = source.get("pose_convention")
            require(isinstance(pose, Mapping), f"LOCK_POSE_CONVENTION:{name}")
            transform = pose.get("static_transform")
            require(isinstance(transform, Mapping), f"LOCK_STATIC_TRANSFORM:{name}")
            static_identity = _identity_shape(transform.get("identity"), f"static_transform:{name}")
            require(dict(static_identity) == seal_snapshot.identity, f"STATIC_TRANSFORM_NOT_SEALED:{name}")
        bridge_value = sources["hfnet"].get("timestamp_contract", {}).get(
            "bridge_receipt"
        )

    bridge_identity = _identity_shape(bridge_value, "hfnet_bridge_receipt")
    require(bridge_identity["path"] == str(canonical_bridge_path), "BRIDGE_RECEIPT_NONCANONICAL_PATH")
    bridge, bridge_snapshot = read_canonical_json_identity(bridge_identity, "hfnet_bridge_receipt")
    ledger.add("hfnet_bridge_receipt", bridge_snapshot)
    require(
        bridge.get("schema_version") == BRIDGE_SCHEMA
        and bridge.get("status") == "PASS_BIJECTIVE_UNIQUE_SOURCE_CAMERA_HEADER_REPLACEMENT"
        and bridge.get("case_id") == case_id,
        "BRIDGE_RECEIPT_SCHEMA_STATUS_CASE",
    )
    require(
        bridge.get("maximum_allowed_absolute_delta_ns") == BRIDGE_MAX_ABSOLUTE_DELTA_NS,
        "BRIDGE_RECEIPT_LIMIT_NOT_256NS",
    )
    serialized, _unused_positions, _unused_quaternions = parse_ascii_pose_rows(
        trajectory_payloads["hfnet"],
        format_name="HFNET_QXYZW_FLOAT_EPOCH",
        label="hfnet_bridge_verify",
        timestamps_only=True,
    )
    mapped, mapping = bridge_hfnet_timestamps(serialized, headers)
    expected_bridge = build_bridge_receipt(
        case_id,
        dict(
            execution_lock["structural_inputs"]["hfnet"]["trajectory"]
            if structural
            else sources["hfnet"]["trajectory"]
        ),
        dict(score_identity),
        serialized,
        mapped,
        mapping,
    )
    require(bridge == expected_bridge, "BRIDGE_RECEIPT_VALUE_MISMATCH")
    if structural:
        expected_frame_contract, _matrix = _frame_lock_contract(seal, row, evaluator)
    else:
        expected_sources, expected_frame_contract = _source_lock_rows(
            seal,
            seal_snapshot,
            row,
            receipt_snapshot.identity,
            sources["hfnet"]["trajectory"],
            bridge_snapshot.identity,
            evaluator,
        )
        require(sources == expected_sources, "LOCK_SOURCE_CONTRACT_NOT_CANONICAL")
    require(
        execution_lock.get("frame_contract") == expected_frame_contract,
        "LOCK_FRAME_CONTRACT_NOT_CANONICAL",
    )
    require(
        execution_lock.get("evo_verification")
        == _evo_lock_contract(seal, seal_snapshot, evaluator),
        "LOCK_EVO_CONTRACT_NOT_CANONICAL",
    )
    require(
        execution_lock.get("native_anchor_sensitivity") == _native_sensitivity_lock(row),
        "LOCK_NATIVE_SENSITIVITY_NOT_CANONICAL",
    )
    require(
        execution_lock.get("authority_hashes") == dict(evaluator.FROZEN_AUTHORITY_HASHES)
        and execution_lock.get("v2_roster_authorities")
        == json.loads(
            canonical_json_bytes(dict(evaluator.V2_ROSTER_AUTHORITY_IDENTITIES)).decode(
                "utf-8"
            )
        )
        and execution_lock.get("analysis_grid_prefreeze")
        == dict(evaluator.ANALYSIS_GRID_PREFREEZE_IDENTITY)
        and execution_lock.get("imported_pure_helpers")
        == {"trajectory_eval_core": dict(evaluator.PURE_HELPER_IDENTITY)},
        "LOCK_EVALUATOR_AUTHORITIES_NOT_CANONICAL",
    )
    _verify_evo_inputs(seal, execution_lock, ledger)
    _verify_input_aliases(ledger)
    ledger.verify_all()
    return VerifiedContext(
        case_id=case_id,
        execution_lock=execution_lock,
        execution_lock_snapshot=execution_lock_snapshot,
        seal=seal,
        seal_snapshot=seal_snapshot,
        row=row,
        evaluator=evaluator,
        evaluator_snapshot=evaluator_snapshot,
        controller_snapshot=controller_snapshot,
        ledger=ledger,
        destinations=destinations,
        runability_receipt=receipt,
        bridge_receipt=bridge,
    )


def _ros_stamp_ns(stamp: Any, label: str) -> int:
    if hasattr(stamp, "to_nsec"):
        value = stamp.to_nsec()
    elif hasattr(stamp, "secs") and hasattr(stamp, "nsecs"):
        value = int(stamp.secs) * 1_000_000_000 + int(stamp.nsecs)
    else:
        raise ControllerError(f"ROS_STAMP_UNSUPPORTED:{label}")
    require(isinstance(value, int) and not isinstance(value, bool), f"ROS_STAMP_TYPE:{label}")
    return value


def _ros_pose(message: Any, label: str) -> tuple[list[float], list[float]]:
    value = message
    if hasattr(value, "pose"):
        value = value.pose
    if hasattr(value, "pose"):
        value = value.pose
    require(hasattr(value, "position") and hasattr(value, "orientation"), f"ROS_POSE_SHAPE:{label}")
    position = [float(value.position.x), float(value.position.y), float(value.position.z)]
    quaternion = [
        float(value.orientation.x),
        float(value.orientation.y),
        float(value.orientation.z),
        float(value.orientation.w),
    ]
    require(all(math.isfinite(number) for number in position + quaternion), f"ROS_POSE_NONFINITE:{label}")
    norm = math.sqrt(sum(number * number for number in quaternion))
    require(norm > 1e-12, f"ROS_POSE_ZERO_QUATERNION:{label}")
    return position, [number / norm for number in quaternion]


def load_rosbag_odometry(
    path: Path, topic: str, *, timestamps_only: bool
) -> tuple[list[int], list[list[float]], list[list[float]]]:
    require(isinstance(topic, str) and topic.startswith("/"), "ROSBAG_TOPIC_INVALID")
    try:
        import rosbag  # type: ignore
    except ImportError as error:
        raise ControllerError("ROSBAG_PYTHON_UNAVAILABLE") from error
    timestamps: list[int] = []
    positions: list[list[float]] = []
    quaternions: list[list[float]] = []
    try:
        with rosbag.Bag(str(path), "r") as bag:
            if timestamps_only:
                # ROS1 Header is the first field of both frozen odometry
                # message types: uint32 seq, time.sec, time.nsec.  Raw mode
                # therefore extracts only twelve header bytes and never
                # deserializes or instantiates any coordinate field.
                for row, (_topic, raw_message, _bag_stamp) in enumerate(
                    bag.read_messages(topics=[topic], raw=True)
                ):
                    require(
                        isinstance(raw_message, tuple) and len(raw_message) >= 2,
                        f"ROSBAG_RAW_MESSAGE_SHAPE:{topic}:{row}",
                    )
                    serialized = raw_message[1]
                    require(
                        isinstance(serialized, (bytes, bytearray))
                        and len(serialized) >= 12,
                        f"ROSBAG_RAW_HEADER_SHORT:{topic}:{row}",
                    )
                    _seq, seconds, nanoseconds = struct.unpack_from(
                        "<III", serialized, 0
                    )
                    require(nanoseconds < 1_000_000_000, f"ROSBAG_RAW_NSEC:{topic}:{row}")
                    timestamps.append(seconds * 1_000_000_000 + nanoseconds)
                return (
                    _validate_strict_timestamps(timestamps, f"rosbag:{topic}"),
                    positions,
                    quaternions,
                )
            for row, (_topic, message, bag_stamp) in enumerate(
                bag.read_messages(topics=[topic])
            ):
                header = getattr(message, "header", None)
                stamp = getattr(header, "stamp", bag_stamp)
                timestamps.append(_ros_stamp_ns(stamp, f"{topic}:{row}"))
                if not timestamps_only:
                    position, quaternion = _ros_pose(message, f"{topic}:{row}")
                    positions.append(position)
                    quaternions.append(quaternion)
    except ControllerError:
        raise
    except BaseException as error:
        raise ControllerError(f"ROSBAG_READ_FAILED:{type(error).__name__}") from error
    return _validate_strict_timestamps(timestamps, f"rosbag:{topic}"), positions, quaternions


def _source_native_series(
    source: Mapping[str, Any],
    *,
    timestamps_only: bool,
) -> tuple[list[int], list[list[float]], list[list[float]]]:
    identity = _identity_shape(source.get("trajectory"), "source_trajectory")
    path = Path(str(identity["path"]))
    format_name = source.get("format")
    if format_name == "ROSBAG_ODOMETRY":
        return load_rosbag_odometry(path, str(source.get("topic")), timestamps_only=timestamps_only)
    require(
        format_name in ("TUM", "VINS_QWXYZ_CSV", "HFNET_QXYZW_FLOAT_EPOCH"),
        f"TRAJECTORY_FORMAT_UNSUPPORTED:{format_name}",
    )
    _snapshot, payload = verify_pinned_file(identity, "source_trajectory_load")
    return parse_ascii_pose_rows(
        payload,
        format_name=str(format_name),
        label=str(format_name),
        timestamps_only=timestamps_only,
    )


def _bridge_mapped_timestamps(bridge: Mapping[str, Any]) -> list[int]:
    mapping = bridge.get("mapping")
    require(isinstance(mapping, list) and mapping, "BRIDGE_MAPPING_EMPTY")
    values = [int(row["canonical_header_ns"]) for row in mapping]
    return _validate_strict_timestamps(values, "bridge_mapped")


def load_locked_timestamp_series(context: VerifiedContext) -> Mapping[str, Any]:
    if context.row.get("structural_na_reasons"):
        return {}
    evaluator = context.evaluator
    sources = context.execution_lock["sources"]
    output: dict[str, Any] = {}
    for name in SOURCE_ORDER:
        timestamps, _positions, _quaternions = _source_native_series(
            sources[name], timestamps_only=True
        )
        if name == "hfnet":
            require(
                ordered_ns_digest(timestamps)
                == context.bridge_receipt["serialized_epoch_ordered_integer_ns_sha256"],
                "HFNET_TIMESTAMP_LOAD_BRIDGE_MISMATCH",
            )
            timestamps = _bridge_mapped_timestamps(context.bridge_receipt)
        output[name] = evaluator.LockedTimestampSeriesNs(
            stamps_ns=timestamps,
            trajectory_identity=dict(sources[name]["trajectory"]),
        )
    return output


def make_pose_loader(context: VerifiedContext) -> Callable[[], Mapping[str, Any]]:
    called = False

    def load() -> Mapping[str, Any]:
        nonlocal called
        require(
            not context.row.get("structural_na_reasons"),
            "STRUCTURAL_NA_COORDINATE_LOADER_FORBIDDEN",
        )
        require(not called, "POSE_LOADER_CALLED_MORE_THAN_ONCE")
        called = True
        evaluator = context.evaluator
        sources = context.execution_lock["sources"]
        output: dict[str, Any] = {}
        for name in SOURCE_ORDER:
            timestamps, positions, quaternions = _source_native_series(
                sources[name], timestamps_only=False
            )
            if name == "hfnet":
                require(
                    ordered_ns_digest(timestamps)
                    == context.bridge_receipt["serialized_epoch_ordered_integer_ns_sha256"],
                    "HFNET_POSE_LOAD_BRIDGE_MISMATCH",
                )
                timestamps = _bridge_mapped_timestamps(context.bridge_receipt)
            import numpy as np

            output[name] = evaluator.PoseSeriesNs(
                stamps_ns=timestamps,
                positions=np.asarray(positions, dtype=float),
                quaternions_xyzw=np.asarray(quaternions, dtype=float),
                trajectory_identity=dict(sources[name]["trajectory"]),
            )
        return output

    return load


def build_evo_ape_argv(
    executable: Path, reference_tum: Path, estimate_tum: Path
) -> list[str]:
    return [
        str(executable),
        "tum",
        str(reference_tum),
        str(estimate_tum),
        "-a",
        "-r",
        "trans_part",
        "--t_max_diff",
        "1e-9",
        "--t_offset",
        "0",
    ]


def build_evo_rpe_argv(
    executable: Path, reference_tum: Path, estimate_tum: Path
) -> list[str]:
    return [
        str(executable),
        "tum",
        str(reference_tum),
        str(estimate_tum),
        "-r",
        "trans_part",
        "-d",
        "10",
        "-u",
        "f",
        "--all_pairs",
        "--pairs_from_reference",
        "--t_max_diff",
        "1e-9",
        "--t_offset",
        "0",
    ]


def validate_evo_argv(argv: Sequence[str], kind: str) -> None:
    require(kind in ("APE", "RPE"), "EVO_ARGV_KIND")
    require("-s" not in argv and "--correct_scale" not in argv, "EVO_SIM3_FLAG_FORBIDDEN")
    require(argv.count("--t_max_diff") == 1, "EVO_SYNC_TOLERANCE_COUNT")
    tolerance_index = argv.index("--t_max_diff")
    require(argv[tolerance_index + 1] == "1e-9", "EVO_SYNC_TOLERANCE_VALUE")
    require(argv.count("--t_offset") == 1, "EVO_OFFSET_COUNT")
    offset_index = argv.index("--t_offset")
    require(argv[offset_index + 1] == "0", "EVO_OFFSET_VALUE")
    require(argv.count("-r") == 1 and argv[argv.index("-r") + 1] == "trans_part", "EVO_POSE_RELATION")
    if kind == "APE":
        require(argv.count("-a") == 1, "EVO_APE_ALIGNMENT_REQUIRED")
        forbidden = {"-d", "-u", "--all_pairs", "--pairs_from_reference"}
        require(not forbidden.intersection(argv), "EVO_APE_RPE_FLAGS")
    else:
        require("-a" not in argv, "EVO_RPE_ALIGNMENT_FORBIDDEN")
        require(
            argv.count("-d") == 1
            and argv[argv.index("-d") + 1] == "10"
            and argv.count("-u") == 1
            and argv[argv.index("-u") + 1] == "f"
            and argv.count("--all_pairs") == 1
            and argv.count("--pairs_from_reference") == 1,
            "EVO_RPE_EXACT_10_FRAME_FLAGS",
        )


def _relative_seconds_token(timestamp_ns: int, origin_ns: int) -> str:
    delta = timestamp_ns - origin_ns
    require(delta >= 0, "EVO_RELATIVE_TIMESTAMP_NEGATIVE")
    whole, fraction = divmod(delta, 1_000_000_000)
    return f"{whole}.{fraction:09d}"


def serialize_tum_full_poses(
    timestamps_ns: Sequence[int],
    positions: Any,
    quaternions_xyzw: Any,
    *,
    origin_ns: int,
) -> bytes:
    import numpy as np

    timestamps = _validate_strict_timestamps(timestamps_ns, "evo_tum")
    p = np.asarray(positions, dtype=float)
    q = np.asarray(quaternions_xyzw, dtype=float)
    require(p.shape == (len(timestamps), 3), "EVO_TUM_POSITION_SHAPE")
    require(q.shape == (len(timestamps), 4), "EVO_TUM_QUATERNION_SHAPE")
    require(np.all(np.isfinite(p)) and np.all(np.isfinite(q)), "EVO_TUM_NONFINITE")
    norms = np.linalg.norm(q, axis=1)
    require(np.all(norms > 1e-12), "EVO_TUM_ZERO_QUATERNION")
    q = q / norms[:, None]
    rows = []
    for timestamp, position, quaternion in zip(timestamps, p, q):
        tokens = [_relative_seconds_token(timestamp, origin_ns)] + [
            format(float(value), ".17g") for value in list(position) + list(quaternion)
        ]
        rows.append(" ".join(tokens) + "\n")
    return "".join(rows).encode("ascii")


def ordered_pair_ns_digest(pairs: Sequence[tuple[int, int]]) -> str:
    payload = "".join(f"{left},{right}\n" for left, right in pairs).encode("ascii")
    return sha256_bytes(payload)


def _material_value(material: Any, name: str) -> Any:
    if isinstance(material, Mapping):
        require(name in material, f"EVO_MATERIAL_FIELD:{name}")
        return material[name]
    require(hasattr(material, name), f"EVO_MATERIAL_FIELD:{name}")
    return getattr(material, name)


def materialize_evo_inputs(material: Any, output_root: Path) -> dict[str, Any]:
    """Publish full-pose TUM inputs from evaluator-produced common material."""

    import numpy as np

    timestamps = _validate_strict_timestamps(
        list(_material_value(material, "common_stamps_ns")), "evo_common_stamps"
    )
    origin = timestamps[0]
    poses = _material_value(material, "full_poses")
    require(isinstance(poses, Mapping) and set(poses) == set(SOURCE_ORDER), "EVO_FULL_POSE_SOURCE_SET")
    raw_segments = _material_value(material, "segments")
    require(isinstance(raw_segments, Sequence) and raw_segments, "EVO_SEGMENTS_EMPTY")
    segments: list[list[int]] = []
    flattened: list[int] = []
    for segment_index, raw in enumerate(raw_segments):
        indices = [int(value) for value in raw]
        require(indices, f"EVO_SEGMENT_EMPTY:{segment_index}")
        require(indices == list(range(indices[0], indices[-1] + 1)), f"EVO_SEGMENT_NOT_CONTIGUOUS:{segment_index}")
        require(0 <= indices[0] <= indices[-1] < len(timestamps), f"EVO_SEGMENT_RANGE:{segment_index}")
        segments.append(indices)
        flattened.extend(indices)
    require(flattened == list(range(len(timestamps))), "EVO_SEGMENTS_NOT_EXACT_PARTITION")

    tum_root = output_root / "evo" / "tum"
    _mkdir_plain(tum_root)
    all_tum: dict[str, FileSnapshot] = {}
    pose_arrays: dict[str, tuple[Any, Any]] = {}
    for name in SOURCE_ORDER:
        pose = poses[name]
        positions = _material_value(pose, "positions")
        quaternions = _material_value(pose, "quaternions_xyzw")
        pose_arrays[name] = (np.asarray(positions, dtype=float), np.asarray(quaternions, dtype=float))
        payload = serialize_tum_full_poses(
            timestamps, positions, quaternions, origin_ns=origin
        )
        all_tum[name] = atomic_publish_noreplace(tum_root / f"all_{name}.tum", payload)
    segment_tum: dict[str, dict[int, FileSnapshot]] = {name: {} for name in SOURCE_ORDER}
    rpe_pairs: list[tuple[int, int]] = []
    segment_membership: list[dict[str, Any]] = []
    for segment_index, indices in enumerate(segments):
        segment_timestamps = [timestamps[index] for index in indices]
        pairs = [
            (segment_timestamps[index], segment_timestamps[index + 10])
            for index in range(max(0, len(indices) - 10))
        ]
        for left, right in pairs:
            require(right - left == 1_000_000_000, f"EVO_RPE_PAIR_NOT_EXACT_1S:{segment_index}")
        rpe_pairs.extend(pairs)
        segment_membership.append(
            {
                "segment_index": segment_index,
                "common_index_first_last": [indices[0], indices[-1]],
                "pose_count": len(indices),
                "expected_exact_1s_pair_count": len(pairs),
                "ordered_integer_ns_sha256": ordered_ns_digest(segment_timestamps),
            }
        )
        if not pairs:
            continue
        for name in SOURCE_ORDER:
            positions, quaternions = pose_arrays[name]
            payload = serialize_tum_full_poses(
                segment_timestamps,
                positions[indices],
                quaternions[indices],
                origin_ns=origin,
            )
            segment_tum[name][segment_index] = atomic_publish_noreplace(
                tum_root / f"segment_{segment_index:03d}_{name}.tum", payload
            )
    population = {
        "common_pose_count": len(timestamps),
        "ordered_common_pose_ns_sha256": ordered_ns_digest(timestamps),
        "exact_1s_pair_count": len(rpe_pairs),
        "ordered_exact_1s_pair_ns_sha256": ordered_pair_ns_digest(rpe_pairs),
    }
    return {
        "all_tum": all_tum,
        "segment_tum": segment_tum,
        "segment_membership": segment_membership,
        "population": population,
    }


_RMSE_PATTERN = re.compile(
    r"(?mi)^\s*rmse\s+([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*$"
)
_PAIR_PATTERNS = (
    re.compile(r"(?i)compared\s+(\d+)\s+(?:absolute|relative)?\s*pose\s+pairs?"),
    re.compile(r"(?mi)^\s*(?:pairs|pair_count|pose_pairs)\s*[:= ]\s*(\d+)\s*$"),
)


def parse_evo_stdout(payload: bytes, *, expected_pair_count: int, label: str) -> tuple[float, int]:
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ControllerError(f"EVO_STDOUT_ENCODING:{label}") from error
    rmse_values = [float(value) for value in _RMSE_PATTERN.findall(text)]
    require(len(rmse_values) == 1, f"EVO_RMSE_PARSE_COUNT:{label}")
    rmse = rmse_values[0]
    require(math.isfinite(rmse) and rmse >= 0.0, f"EVO_RMSE_INVALID:{label}")
    counts: set[int] = set()
    for pattern in _PAIR_PATTERNS:
        counts.update(int(value) for value in pattern.findall(text))
    require(len(counts) == 1, f"EVO_PAIR_COUNT_PARSE:{label}")
    pair_count = next(iter(counts))
    require(pair_count == expected_pair_count, f"EVO_PAIR_COUNT_MISMATCH:{label}")
    return rmse, pair_count


def _evo_environment() -> dict[str, str]:
    # Absolute wrappers plus the sealed Python/site tree determine code.  Keep
    # locale/output stable and block caller PYTHONPATH injection.
    environment = {
        "HOME": "/home/ma",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "0",
    }
    return environment


def _run_one_evo(
    argv: Sequence[str],
    *,
    kind: str,
    expected_pair_count: int,
    log_root: Path,
    label: str,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    validate_evo_argv(argv, kind)
    require(Path(argv[0]).is_absolute(), f"EVO_EXECUTABLE_NOT_ABSOLUTE:{label}")
    try:
        process = subprocess.run(
            list(argv),
            cwd=str(log_root.parent.parent),
            env=_evo_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ControllerError(f"EVO_TIMEOUT:{label}") from error
    stdout = bytes(process.stdout)
    stderr = bytes(process.stderr)
    stdout_identity = atomic_publish_noreplace(log_root / f"{label}.stdout.log", stdout)
    stderr_identity = atomic_publish_noreplace(log_root / f"{label}.stderr.log", stderr)
    require(process.returncode == 0, f"EVO_RETURN_CODE:{label}:{process.returncode}")
    rmse, pair_count = parse_evo_stdout(
        stdout, expected_pair_count=expected_pair_count, label=label
    )
    return {
        "kind": kind,
        "argv": list(argv),
        "return_code": process.returncode,
        "stdout": stdout_identity.identity,
        "stderr": stderr_identity.identity,
        "parsed_rmse_m": rmse,
        "parsed_pair_count": pair_count,
    }


def _run_planned_evo_command(
    planned: Mapping[str, Any], *, output_root: Path
) -> dict[str, Any]:
    command_id = planned.get("command_id")
    kind = planned.get("kind")
    argv = planned.get("argv")
    require(isinstance(command_id, str) and command_id, "EVO_PLAN_COMMAND_ID")
    require(kind in ("APE", "RPE"), f"EVO_PLAN_COMMAND_KIND:{command_id}")
    require(isinstance(argv, list) and all(isinstance(value, str) for value in argv), f"EVO_PLAN_ARGV:{command_id}")
    validate_evo_argv(argv, str(kind))
    log_root = output_root / "outputs"
    _mkdir_plain(log_root)
    safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "_", command_id)
    try:
        process = subprocess.run(
            list(argv),
            cwd=str(output_root),
            env=_evo_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ControllerError(f"EVO_TIMEOUT:{command_id}") from error
    stdout = atomic_publish_noreplace(
        log_root / f"{safe_label}.stdout.log", bytes(process.stdout)
    )
    stderr = atomic_publish_noreplace(
        log_root / f"{safe_label}.stderr.log", bytes(process.stderr)
    )
    # The evaluator independently parses the sole RMSE line and derives every
    # RPE pair count from the sealed generated TUM population.
    require(process.returncode == 0, f"EVO_RETURN_CODE:{command_id}:{process.returncode}")
    return {
        "command_id": command_id,
        "argv": list(argv),
        "return_code": process.returncode,
        "stdout": stdout.identity,
        "stderr": stderr.identity,
    }


def execute_evaluator_evo_plan(
    context: VerifiedContext,
    primary_result: Mapping[str, Any],
    plan: Any,
    output_root: Path,
) -> dict[str, Any]:
    evaluator = context.evaluator
    require(isinstance(plan, evaluator.EvoAdapterPlan), "EVALUATOR_EVO_PLAN_TYPE")
    document = plan.document
    require(isinstance(document, Mapping), "EVALUATOR_EVO_PLAN_DOCUMENT")
    require(document.get("case_id") == context.case_id, "EVALUATOR_EVO_PLAN_CASE")
    require(document.get("status") == "PLANNED_NOT_EXECUTED", "EVALUATOR_EVO_PLAN_STATUS")
    require(document.get("subprocess_started") is False, "EVALUATOR_STARTED_SUBPROCESS")
    _mkdir_plain(output_root)
    root = output_root.resolve(strict=True)
    generated: dict[str, FileSnapshot] = {}
    for raw_path, payload in plan.generated_tum_payloads.items():
        require(isinstance(raw_path, str) and isinstance(payload, bytes), "EVO_PLAN_TUM_PAYLOAD_TYPE")
        path = _canonical_future_path(Path(raw_path), "evo_plan_tum")
        require(str(path).startswith(str(root) + os.sep), "EVO_PLAN_TUM_ESCAPES_OUTPUT")
        _mkdir_plain(path.parent)
        observed = atomic_publish_noreplace(path, payload)
        expected = document.get("generated_tum", {}).get(raw_path)
        require(isinstance(expected, Mapping) and observed.identity == dict(expected), "EVO_PLAN_TUM_IDENTITY_MISMATCH")
        generated[raw_path] = observed
    plan_snapshot = atomic_publish_noreplace(
        output_root / "evo_adapter_plan.json", canonical_json_bytes(dict(document))
    )
    commands = [
        _run_planned_evo_command(planned, output_root=output_root)
        for planned in document.get("commands", [])
    ]
    receipt = {
        "schema_version": "aqua-fe-hfnet-v6-positive-roster-evo-adapter-receipt-v1",
        "plan_core_sha256": document["plan_core_sha256"],
        "generated_tum": dict(document["generated_tum"]),
        "commands": commands,
    }
    receipt_snapshot = atomic_publish_noreplace(
        output_root / "evo_adapter_receipt.json", canonical_json_bytes(receipt)
    )

    def artifact_loader(identity: Mapping[str, Any]) -> bytes:
        _snapshot, payload = verify_pinned_file(identity, "evo_validator_artifact")
        return payload

    crosscheck = evaluator.validate_evo_adapter_receipt(
        plan,
        primary_result,
        receipt,
        artifact_loader,
    )
    require(isinstance(crosscheck, Mapping), "EVO_CROSSCHECK_RESULT_NOT_OBJECT")
    crosscheck_snapshot = atomic_publish_noreplace(
        output_root / "evo_crosscheck.json", canonical_json_bytes(dict(crosscheck))
    )
    return {
        "receipt": receipt,
        "crosscheck": dict(crosscheck),
        "evidence_identities": {
            "plan": plan_snapshot.identity,
            "receipt": receipt_snapshot.identity,
            "crosscheck": crosscheck_snapshot.identity,
            "generated_tum": {
                path: snapshot.identity for path, snapshot in sorted(generated.items())
            },
        },
    }


def execute_evo_crosscheck(
    context: VerifiedContext,
    primary_result: Mapping[str, Any],
    material: Any,
    output_root: Path,
) -> dict[str, Any]:
    if isinstance(material, context.evaluator.EvoAdapterPlan):
        return execute_evaluator_evo_plan(
            context, primary_result, material, output_root
        )
    inputs = materialize_evo_inputs(material, output_root)
    log_root = output_root / "evo" / "logs"
    _mkdir_plain(log_root)
    evo_lock = context.execution_lock["evo_verification"]
    ape_executable = Path(str(evo_lock["evo_ape"]["path"]))
    rpe_executable = Path(str(evo_lock["evo_rpe"]["path"]))
    jobs: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    population = dict(inputs["population"])
    require(population.get("exact_1s_pair_count", 0) >= 1, "EVO_NO_RPE_PAIRS")
    for arm in ESTIMATE_ORDER:
        ape_argv = build_evo_ape_argv(
            ape_executable,
            Path(inputs["all_tum"]["reference"].path),
            Path(inputs["all_tum"][arm].path),
        )
        ape = _run_one_evo(
            ape_argv,
            kind="APE",
            expected_pair_count=int(population["common_pose_count"]),
            log_root=log_root,
            label=f"ape_{arm}",
        )
        jobs.append({**ape, "arm": arm, "segment_index": None})
        rpe_sum_squares = 0.0
        rpe_pair_count = 0
        for segment in inputs["segment_membership"]:
            expected_pairs = int(segment["expected_exact_1s_pair_count"])
            if expected_pairs == 0:
                continue
            segment_index = int(segment["segment_index"])
            rpe_argv = build_evo_rpe_argv(
                rpe_executable,
                Path(inputs["segment_tum"]["reference"][segment_index].path),
                Path(inputs["segment_tum"][arm][segment_index].path),
            )
            rpe = _run_one_evo(
                rpe_argv,
                kind="RPE",
                expected_pair_count=expected_pairs,
                log_root=log_root,
                label=f"rpe_{arm}_segment_{segment_index:03d}",
            )
            jobs.append({**rpe, "arm": arm, "segment_index": segment_index})
            rpe_sum_squares += float(rpe["parsed_rmse_m"]) ** 2 * expected_pairs
            rpe_pair_count += expected_pairs
        require(rpe_pair_count == population["exact_1s_pair_count"], f"EVO_RPE_TOTAL_PAIR_COUNT:{arm}")
        metrics[arm] = {
            "translation_ape_rmse_m": float(ape["parsed_rmse_m"]),
            "translation_rpe_exact_1s_rmse_m": math.sqrt(rpe_sum_squares / rpe_pair_count),
            "population": population,
        }
    evo_receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": "EVO_SUBPROCESSES_PASS",
        "case_id": context.case_id,
        "evo_ape": dict(evo_lock["evo_ape"]),
        "evo_rpe": dict(evo_lock["evo_rpe"]),
        "sync_max_diff_seconds": "1e-9",
        "offset_seconds": "0",
        "scale_flag_used": False,
        "ape_alignment_flag": "-a",
        "rpe_alignment_flag_used": False,
        "population": population,
        "segment_membership": inputs["segment_membership"],
        "generated_tum_identities": {
            "all": {name: snapshot.identity for name, snapshot in inputs["all_tum"].items()},
            "segments": {
                name: {
                    str(index): snapshot.identity
                    for index, snapshot in sorted(values.items())
                }
                for name, values in inputs["segment_tum"].items()
            },
        },
        "jobs": jobs,
        "metrics_parsed_only_from_evo_stdout": metrics,
        "caller_supplied_scalar_accepted": False,
        "caller_supplied_population_accepted": False,
    }
    evaluator = context.evaluator
    if hasattr(evaluator, "validate_evo_adapter_receipt"):
        crosscheck = evaluator.validate_evo_adapter_receipt(
            primary_result, evo_receipt
        )
    else:
        require(hasattr(evaluator, "verify_evo_crosscheck"), "EVALUATOR_EVO_VALIDATOR_MISSING")
        primary_metrics = primary_result.get("metrics")
        require(isinstance(primary_metrics, Mapping), "PRIMARY_METRICS_MISSING")
        crosscheck = evaluator.verify_evo_crosscheck(primary_metrics, metrics, population)
    require(isinstance(crosscheck, Mapping), "EVO_CROSSCHECK_RESULT_NOT_OBJECT")
    return {"receipt": evo_receipt, "crosscheck": dict(crosscheck)}


def _formal_verification_receipt(
    context: VerifiedContext, post_verification: Mapping[str, Any]
) -> dict[str, Any]:
    if context.execution_lock.get("sources"):
        bridge_identity = context.execution_lock["sources"]["hfnet"][
            "timestamp_contract"
        ]["bridge_receipt"]
    else:
        bridge_identity = context.execution_lock["structural_inputs"]["hfnet"][
            "timestamp_bridge_receipt"
        ]
    return {
        "schema_version": VERIFICATION_SCHEMA,
        "status": "PASS_FORMAL_IDENTITY_VERIFICATION_BEFORE_METRICS",
        "case_id": context.case_id,
        "execution_lock": context.execution_lock_snapshot.identity,
        "execution_lock_value_sha256": sha256_bytes(
            canonical_json_bytes(context.execution_lock)
        ),
        "controller": context.controller_snapshot.identity,
        "evaluator": context.evaluator_snapshot.identity,
        "prestart_seal": context.seal_snapshot.identity,
        "runability_status_derived_from_receipt": _runability_status(
            context.runability_receipt, context.case_id
        ),
        "runability_receipt": context.execution_lock["hfnet_runability_receipt"]["identity"],
        "frame_convention_seal": context.execution_lock["frame_convention_seal"],
        "hfnet_timestamp_bridge_receipt": bridge_identity,
        "bridge_max_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
        "pre_metric_input_identity_and_stat_bindings": context.ledger.evidence(),
        "immediate_pre_metric_toctou_reverification": dict(post_verification),
        "execution_lock_file_identity_verified": True,
        "evaluator_self_identity_verified": True,
        "controller_self_identity_verified": True,
        "evidence_identities_verified": True,
        "pre_metric_toctou_verified": True,
        "coordinates_loaded": False,
        "metrics_computed": False,
    }


def _mint_validated_lock(
    context: VerifiedContext, verification_identity: Mapping[str, Any]
) -> Any:
    evaluator = context.evaluator
    require(hasattr(evaluator, "FormalIdentityVerification"), "EVALUATOR_FORMAL_VERIFICATION_API_MISSING")
    verification = evaluator.FormalIdentityVerification(
        verification_receipt_identity=dict(verification_identity),
        execution_lock_value_sha256=sha256_bytes(
            canonical_json_bytes(context.execution_lock)
        ),
        execution_lock_file_identity_verified=True,
        evaluator_self_identity_verified=True,
        controller_self_identity_verified=True,
        evidence_identities_verified=True,
        pre_metric_toctou_verified=True,
    )
    require(
        hasattr(evaluator, "validate_future_execution_lock"),
        "EVALUATOR_LOCK_VALIDATOR_MISSING",
    )
    return evaluator.validate_future_execution_lock(context.execution_lock, verification)


def _evaluate_with_material(
    context: VerifiedContext,
    validated_lock: Any,
    timestamps: Mapping[str, Any],
    pose_loader: Callable[[], Mapping[str, Any]],
    evo_output_root: Path,
) -> tuple[dict[str, Any], Any | None]:
    evaluator = context.evaluator
    if hasattr(evaluator, "evaluate_case_for_controller"):
        outcome = evaluator.evaluate_case_for_controller(
            context.case_id,
            timestamps,
            validated_lock,
            evo_output_root,
            pose_loader=pose_loader,
        )
    else:
        outcome = evaluator.evaluate_case(
            context.case_id,
            timestamps,
            validated_lock,
            pose_loader=pose_loader,
        )
    if isinstance(outcome, tuple):
        require(len(outcome) == 2, "EVALUATOR_CONTROLLER_TUPLE_SHAPE")
        public, material = outcome
    elif hasattr(outcome, "public_result"):
        public = outcome.public_result
        material = getattr(outcome, "evo_material", None)
    elif isinstance(outcome, Mapping):
        mutable = dict(outcome)
        material = mutable.pop("_controller_evo_material", None)
        public = mutable
    else:
        raise ControllerError("EVALUATOR_RESULT_INTERFACE_UNSUPPORTED")
    require(isinstance(public, Mapping), "EVALUATOR_PUBLIC_RESULT_NOT_OBJECT")
    return dict(public), material


def _status_requires_evo(primary: Mapping[str, Any]) -> bool:
    status = primary.get("accuracy_status")
    return status in (
        "EVO_CROSSCHECK_PENDING",
        "PRIMARY_METRICS_COMPUTED_EVO_PENDING",
    )


def _closed_result(primary: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(primary)
    status = str(result.get("accuracy_status"))
    require(
        status
        in (
            "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND",
            "NA_SUPPORT_GATE",
            "NA_ALIGNMENT_GATE",
        ),
        f"UNEXPECTED_PRIMARY_CLOSED_STATUS:{status}",
    )
    require("metrics" not in result, "CLOSED_GATE_HIDDEN_METRICS")
    support = result.get("support")
    if isinstance(support, Mapping) and status in (
        "STRUCTURAL_NA_PREFROZEN_UPPER_BOUND",
        "NA_SUPPORT_GATE",
    ):
        require(support.get("coordinates_loaded") is False, "CLOSED_GATE_COORDINATES_LOADED")
    return result


def _finalize_evo_result(
    context: VerifiedContext,
    primary: Mapping[str, Any],
    evo: Mapping[str, Any],
) -> dict[str, Any]:
    crosscheck = evo["crosscheck"]
    status = crosscheck.get("status")
    evaluator = context.evaluator
    if hasattr(evaluator, "finalize_primary_with_evo"):
        finalized = evaluator.finalize_primary_with_evo(primary, crosscheck)
        require(isinstance(finalized, Mapping), "EVALUATOR_FINALIZE_RESULT_NOT_OBJECT")
        result = dict(finalized)
        result["independent_evo_evidence"] = dict(evo.get("evidence_identities", {}))
        return result
    if hasattr(evaluator, "finalize_evo_crosscheck"):
        finalized = evaluator.finalize_evo_crosscheck(primary, evo["receipt"], crosscheck)
        require(isinstance(finalized, Mapping), "EVALUATOR_FINALIZE_RESULT_NOT_OBJECT")
        return dict(finalized)
    if status == "PASS":
        result = dict(primary)
        result["accuracy_status"] = "PASS_EVO_CROSSCHECK_ACCURACY_AUTHORIZED"
        result["independent_evo"] = dict(evo["receipt"])
        result["evo_crosscheck"] = dict(crosscheck)
        boundary = dict(result.get("claim_boundary", {}))
        boundary.update(
            {
                "accuracy_numeric_authorized": True,
                "ranking_authorized": True,
                "independent_evo_passed": True,
            }
        )
        result["claim_boundary"] = boundary
        return result
    require(status == "CLOSED_NO_RANKING", f"EVO_CROSSCHECK_STATUS:{status}")
    # Preserve population/identity diagnostics, but do not publish competing
    # unverified scalar values as formal accuracy numbers.
    return {
        "schema_version": primary.get("schema_version"),
        "case_id": context.case_id,
        "accuracy_status": "CLOSED_NO_RANKING",
        "support": primary.get("support"),
        "evo_crosscheck": dict(crosscheck),
        "independent_evo_evidence": {
            key: value
            for key, value in evo["receipt"].items()
            if key not in ("metrics_parsed_only_from_evo_stdout",)
        },
        "claim_boundary": {
            "accuracy_numeric_authorized": False,
            "ranking_computed": False,
            "ranking_authorized": False,
            "independent_evo_passed": False,
        },
    }


def check_case(case_id: str, execution_lock_path: Path) -> dict[str, Any]:
    with locked_execution_lock(execution_lock_path) as (lock, lock_snapshot):
        context = verify_execution_context(
            case_id,
            lock,
            lock_snapshot,
            require_destinations_absent=True,
        )
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "READY_FOR_EXACTLY_ONCE_ACCURACY_RUN",
            "case_id": case_id,
            "execution_lock": lock_snapshot.identity,
            "prestart_seal": context.seal_snapshot.identity,
            "controller": context.controller_snapshot.identity,
            "evaluator": context.evaluator_snapshot.identity,
            "runability_status_derived_from_receipt": "PASS",
            "bridge_max_absolute_delta_ns": BRIDGE_MAX_ABSOLUTE_DELTA_NS,
            "destinations": {label: str(path) for label, path in context.destinations.items()},
            "destinations_absent": True,
            "scientific_input_identities_verified": True,
            "scientific_input_toctou_verified": True,
            "coordinates_loaded": False,
            "support_computed": False,
            "ape_computed": False,
            "rpe_computed": False,
            "claim_created": False,
        }


def _claim_payload(context: VerifiedContext) -> dict[str, Any]:
    return {
        "schema_version": CLAIM_SCHEMA,
        "status": "CLAIMED_EXACTLY_ONCE_ACCURACY_ATTEMPT",
        "case_id": context.case_id,
        "execution_lock": context.execution_lock_snapshot.identity,
        "execution_lock_value_sha256": sha256_bytes(canonical_json_bytes(context.execution_lock)),
        "controller": context.controller_snapshot.identity,
        "evaluator": context.evaluator_snapshot.identity,
        "prestart_seal": context.seal_snapshot.identity,
        "authorization_token_sha256": AUTHORIZATION_TOKEN_SHA256,
        "maximum_attempts": 1,
        "retry_permitted": False,
        "claim_consumed_even_if_later_failure": True,
    }


def take_exactly_once_claim(
    path: Path, value: Mapping[str, Any]
) -> tuple[FileSnapshot, BaseException | None]:
    """Take the claim and recover ownership if a post-link sync/probe failed.

    A hard-link is the visibility boundary.  Once it exists, an exception from
    a later directory fsync, temp unlink, or verification probe must enter the
    terminal-receipt path instead of escaping as a pre-claim failure.
    """

    payload = canonical_json_bytes(value)
    try:
        return atomic_publish_noreplace(path, payload), None
    except BaseException as error:
        try:
            observed, observed_payload = snapshot_file(path, "claim_recovery")
        except BaseException:
            raise error
        require(observed_payload == payload, "CLAIM_RECOVERY_FOREIGN_OR_CORRUPT")
        return observed, error


def _failure_code(error: BaseException) -> str:
    if isinstance(error, ControllerError):
        return error.code
    evaluator_error_code = getattr(error, "code", None)
    if isinstance(evaluator_error_code, str):
        return f"EVALUATOR:{evaluator_error_code}"
    return f"{type(error).__name__}:{error}"


def _terminal_failure(
    context: VerifiedContext,
    claim_snapshot: FileSnapshot,
    error: BaseException,
    *,
    post_identity_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": TERMINAL_SCHEMA,
        "status": "CLOSED_TERMINAL_FAILURE_NO_RETRY",
        "case_id": context.case_id,
        "failure_code": _failure_code(error),
        "execution_lock": context.execution_lock_snapshot.identity,
        "process_claim": claim_snapshot.identity,
        "prestart_seal": context.seal_snapshot.identity,
        "post_identity_status": post_identity_status,
        "accuracy_numeric_authorized": False,
        "ranking_computed": False,
        "ranking_authorized": False,
        "terminal_contract": {
            "attempt_consumed": True,
            "maximum_attempts": 1,
            "retry_permitted": False,
            "replacement_terminal_receipt_permitted": False,
        },
    }


def run_case(
    case_id: str,
    execution_lock_path: Path,
    authorization_token: str,
) -> dict[str, Any]:
    require(
        secrets.compare_digest(authorization_token, AUTHORIZATION_TOKEN),
        "AUTHORIZATION_TOKEN_INVALID",
    )
    with locked_execution_lock(execution_lock_path) as (lock, lock_snapshot):
        context = verify_execution_context(
            case_id,
            lock,
            lock_snapshot,
            require_destinations_absent=True,
        )
        output_dir = context.destinations["output_dir"]
        claim_path = context.destinations["process_claim"]
        terminal_path = context.destinations["terminal_receipt"]
        require(output_dir.parent == terminal_path.parent, "OUTPUT_TERMINAL_PARENT_MISMATCH")
        _mkdir_plain(claim_path.parent)
        _mkdir_plain(terminal_path.parent)
        # Recheck after directory creation and immediately before the claim.
        for label, path in context.destinations.items():
            _destination_absent(path, label)
        context.ledger.verify_all()
        claim_snapshot, claim_post_link_error = take_exactly_once_claim(
            claim_path, _claim_payload(context)
        )
        terminal: dict[str, Any] | None = None
        post_identity_status = "NOT_YET_REVERIFIED"
        try:
            if claim_post_link_error is not None:
                raise claim_post_link_error
            _mkdir_exclusive(output_dir)
            pre_metric_post = context.ledger.verify_all()
            verification_value = _formal_verification_receipt(context, pre_metric_post)
            verification_path = output_dir / "formal_identity_verification.json"
            verification_snapshot = atomic_publish_noreplace(
                verification_path, canonical_json_bytes(verification_value)
            )
            validated_lock = _mint_validated_lock(context, verification_snapshot.identity)
            timestamps = load_locked_timestamp_series(context)
            primary, material = _evaluate_with_material(
                context,
                validated_lock,
                timestamps,
                make_pose_loader(context),
                output_dir / "evo_adapter",
            )
            if _status_requires_evo(primary):
                require(material is not None, "EVALUATOR_EVO_MATERIAL_MISSING")
                evo = execute_evo_crosscheck(context, primary, material, output_dir)
                scientific_result = _finalize_evo_result(context, primary, evo)
            else:
                require(material is None, "CLOSED_GATE_EXPOSED_EVO_MATERIAL")
                scientific_result = _closed_result(primary)
            # This second full hash/stat pass is the publication authorization.
            post_identities = context.ledger.verify_all()
            post_identity_status = "PASS_PRE_PUBLICATION_TOCTOU_REVERIFICATION"
            result_value = {
                "schema_version": SCHEMA_VERSION,
                "status": "FORMAL_ACCURACY_ANALYSIS_TERMINAL",
                "case_id": case_id,
                "execution_lock": lock_snapshot.identity,
                "formal_identity_verification": verification_snapshot.identity,
                "scientific_result": scientific_result,
                "post_publication_authorization_input_identities": post_identities,
                "retry_permitted": False,
            }
            result_snapshot = atomic_publish_noreplace(
                output_dir / "accuracy_result.json", canonical_json_bytes(result_value)
            )
            context.ledger.verify_all()
            accuracy_status = scientific_result.get("accuracy_status")
            accuracy_authorized = bool(
                scientific_result.get("claim_boundary", {}).get(
                    "accuracy_numeric_authorized", False
                )
            )
            ranking_authorized = bool(
                scientific_result.get("claim_boundary", {}).get(
                    "ranking_authorized", False
                )
            )
            terminal = {
                "schema_version": TERMINAL_SCHEMA,
                "status": "PASS_TERMINAL_RECEIPT",
                "case_id": case_id,
                "accuracy_status": accuracy_status,
                "execution_lock": lock_snapshot.identity,
                "process_claim": claim_snapshot.identity,
                "formal_identity_verification": verification_snapshot.identity,
                "accuracy_result": result_snapshot.identity,
                "post_identity_status": post_identity_status,
                "accuracy_numeric_authorized": accuracy_authorized,
                "ranking_computed": False,
                "ranking_authorized": ranking_authorized,
                "terminal_contract": {
                    "attempt_consumed": True,
                    "maximum_attempts": 1,
                    "retry_permitted": False,
                    "replacement_terminal_receipt_permitted": False,
                },
            }
        except BaseException as error:
            try:
                context.ledger.verify_all()
                post_identity_status = "PASS_AFTER_FAILURE"
            except BaseException as post_error:
                post_identity_status = f"FAIL:{_failure_code(post_error)}"
            terminal = _terminal_failure(
                context,
                claim_snapshot,
                error,
                post_identity_status=post_identity_status,
            )
        require(terminal is not None, "TERMINAL_VALUE_MISSING")
        try:
            terminal_snapshot = atomic_publish_noreplace(
                terminal_path, canonical_json_bytes(terminal)
            )
        except BaseException as error:
            raise ControllerError(
                f"TERMINAL_PUBLICATION_INDETERMINATE_NO_RETRY:{_failure_code(error)}"
            ) from error
        return {**terminal, "terminal_receipt_identity": terminal_snapshot.identity}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser(
        "freeze-lock", help="freeze one PASS HFNet result before any metric"
    )
    freeze.add_argument("--case-id", required=True, choices=CASE_ORDER)
    freeze.add_argument("--prestart-seal", type=Path, default=DEFAULT_PREFREEZE_SEAL)
    freeze.add_argument("--authorization-token", required=True)
    check = subparsers.add_parser("check", help="read-only formal execution preflight")
    check.add_argument("--case-id", required=True, choices=CASE_ORDER)
    check.add_argument("--execution-lock", required=True, type=Path)
    run = subparsers.add_parser("run", help="consume one exactly-once accuracy attempt")
    run.add_argument("--case-id", required=True, choices=CASE_ORDER)
    run.add_argument("--execution-lock", required=True, type=Path)
    run.add_argument("--authorization-token", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        if arguments.command == "freeze-lock":
            require(
                secrets.compare_digest(
                    arguments.authorization_token, FREEZE_LOCK_AUTHORIZATION_TOKEN
                ),
                "FREEZE_LOCK_AUTHORIZATION_TOKEN_INVALID",
            )
            result = freeze_lock(arguments.case_id, arguments.prestart_seal)
        elif arguments.command == "check":
            result = check_case(arguments.case_id, arguments.execution_lock)
        else:
            result = run_case(
                arguments.case_id,
                arguments.execution_lock,
                arguments.authorization_token,
            )
        sys.stdout.buffer.write(canonical_json_bytes(result))
        return 0
    except BaseException as error:
        code = _failure_code(error)
        claim_may_exist = code.startswith(
            "TERMINAL_PUBLICATION_INDETERMINATE_NO_RETRY"
        )
        sys.stdout.buffer.write(
            canonical_json_bytes(
                {
                    "schema_version": SCHEMA_VERSION,
                    "status": "BLOCKED_NO_ACCURACY_NO_RANKING",
                    "error": _failure_code(error),
                    "claim_created": claim_may_exist,
                    "retry_permitted": False if claim_may_exist else None,
                    "accuracy_numeric_authorized": False,
                    "ranking_computed": False,
                    "ranking_authorized": False,
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
